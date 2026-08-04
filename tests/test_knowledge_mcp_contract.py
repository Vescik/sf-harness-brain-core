"""Pin the knowledge MCP server's executor surface to the argparse trees it wraps.

The server (scripts/knowledge_mcp_server.mjs) shells out to the Knowledge executors with a
subcommand allowlist that is data, not code. These tests import that data via node and pin
it in both directions, mirroring test_guard_parser_contract.py: every allowlisted
subcommand must exist in the wrapped parser (drift when a subcommand is renamed), every
tool must map into the allowlist, and — the negative pin that keeps v2 honest — no
write-capable subcommand is ever reachable through the server. The write path over MCP is
a deliberate non-goal (SAFE-HUMAN-001: approval stays a human chat action); loosening this
test is a policy change, not a refactor.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import force_app_knowledge
from scripts import knowledge_search
from scripts import knowledge_store

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "knowledge_mcp_server.mjs"

EXPECTED_TOOLS = {
    "knowledge_context",
    "knowledge_search",
    "knowledge_impact",
    "knowledge_resolve",
    "knowledge_entry_status",
    "knowledge_explain",
    "knowledge_tree",
    "knowledge_feature_drift",
    "knowledge_feature_dossier",
    "knowledge_edge_health",
    "knowledge_capabilities",
}

# Flags the server's argv builder may emit per tool. A flag listed here that the parser
# drops (or renames) fails test_server_flags_exist_on_parsers before it fails at runtime.
SERVER_FLAGS = {
    "knowledge_context": {"--identity", "--top", "--direction", "--include-heuristic"},
    "knowledge_search": {
        "--text",
        "--identity",
        "--metadata-type",
        "--namespace",
        "--facet",
        "--relation-anchor",
        "--relation-kind",
        "--direction",
        "--include-heuristic",
        "--mode",
        "--top",
    },
    "knowledge_impact": {"--identity", "--direction", "--depth", "--top", "--include-heuristic"},
    "knowledge_resolve": {"--name", "--path"},
    "knowledge_entry_status": {"--identity"},
    "knowledge_explain": {"--identity", "--top", "--include-heuristic"},
    "knowledge_tree": {"--feature", "--direction", "--include-heuristic"},
    "knowledge_feature_drift": {"--feature", "--include-heuristic"},
    "knowledge_feature_dossier": {"--feature", "--include-heuristic"},
    "knowledge_edge_health": set(),
    "knowledge_capabilities": {"--metadata-type"},
}

# Write-capable subcommands that must exist in the parsers (so the negative pin below can
# never pass vacuously after a rename) and must never appear in the server allowlist.
WRITE_SENTINELS = {
    "knowledge_store.py": {"entry-draft", "entry-approve", "entry-revoke", "entry-org-attach", "feature-propose"},
    "force_app_knowledge.py": {"feature-crawl"},
}

PARSERS = {
    "knowledge_search.py": knowledge_search.build_parser(),
    "knowledge_store.py": knowledge_store.build_parser(),
    "force_app_knowledge.py": force_app_knowledge.build_parser(),
}

EXPORT_SNIPPET = """
const { pathToFileURL } = await import("node:url");
const server = await import(pathToFileURL(process.env.KNOWLEDGE_MCP_SERVER_PATH).href);
process.stdout.write(JSON.stringify({
  allowlist: server.SUBCOMMAND_ALLOWLIST,
  executors: server.TOOL_EXECUTORS,
  tools: server.TOOL_DEFINITIONS,
}));
"""


def subcommand_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("parser has no subcommands")


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }


def parser_action(parser: argparse.ArgumentParser, flag: str) -> argparse.Action:
    for action in parser._actions:
        if flag in action.option_strings:
            return action
    raise AssertionError(f"parser has no {flag}")


def property_flag(name: str) -> str:
    return "--" + re.sub(r"([A-Z])", lambda match: "-" + match.group(1).lower(), name)


class KnowledgeMcpContractTests(unittest.TestCase):
    exports: dict

    @classmethod
    def setUpClass(cls) -> None:
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", EXPORT_SNIPPET],
            env={**os.environ, "KNOWLEDGE_MCP_SERVER_PATH": str(SERVER)},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        cls.exports = json.loads(completed.stdout)

    def test_tool_set_is_pinned(self) -> None:
        tool_names = {tool["name"] for tool in self.exports["tools"]}
        self.assertEqual(tool_names, EXPECTED_TOOLS)
        self.assertEqual(set(self.exports["executors"]), EXPECTED_TOOLS)

    def test_every_tool_maps_to_an_allowlisted_subcommand(self) -> None:
        allowlist = self.exports["allowlist"]
        for name, executor in self.exports["executors"].items():
            with self.subTest(tool=name):
                self.assertIn(executor["script"], allowlist)
                self.assertIn(executor["subcommand"], allowlist[executor["script"]])

    def test_allowlisted_subcommands_exist_in_the_parsers(self) -> None:
        for script, subcommands in self.exports["allowlist"].items():
            with self.subTest(script=script):
                self.assertIn(script, PARSERS)
                available = subcommand_parsers(PARSERS[script])
                for subcommand in subcommands:
                    self.assertIn(subcommand, available)

    def test_no_write_capable_subcommand_is_reachable(self) -> None:
        allowlist = self.exports["allowlist"]
        self.assertEqual(allowlist["knowledge_store.py"], ["entry-status"])
        # `inventory` is the missing-inventory self-heal (generated-cache class, like
        # `build`) — reachable by the server, never mapped to a tool.
        self.assertEqual(sorted(allowlist["force_app_knowledge.py"]), ["inventory", "resolve"])
        # The full knowledge_search.py surface is exposed (owner decision 2026-08-04:
        # MCP-only definitions); the script has no write-capable subcommand — `build`
        # writes only the gitignored generated cache.
        self.assertEqual(
            sorted(allowlist["knowledge_search.py"]),
            sorted(subcommand_parsers(PARSERS["knowledge_search.py"])),
        )
        for script, sentinels in WRITE_SENTINELS.items():
            parser_subcommands = set(subcommand_parsers(PARSERS[script]))
            with self.subTest(script=script):
                # The sentinels must exist — a rename would otherwise make this pin vacuous.
                self.assertEqual(sentinels - parser_subcommands, set())
                self.assertEqual(sentinels & set(self.exports["allowlist"][script]), set())

    def test_resolve_write_flag_is_unconstructable(self) -> None:
        resolve_parser = subcommand_parsers(PARSERS["force_app_knowledge.py"])["resolve"]
        self.assertIn("--write", option_strings(resolve_parser))
        (resolve_tool,) = [t for t in self.exports["tools"] if t["name"] == "knowledge_resolve"]
        self.assertEqual(
            set(resolve_tool["inputSchema"]["properties"]), {"names", "paths"}
        )

    def test_server_flags_exist_on_parsers(self) -> None:
        for name, flags in SERVER_FLAGS.items():
            executor = self.exports["executors"][name]
            parser = subcommand_parsers(PARSERS[executor["script"]])[executor["subcommand"]]
            with self.subTest(tool=name):
                self.assertEqual(flags - option_strings(parser), set())

    def test_enum_values_match_parser_choices(self) -> None:
        # A renamed argparse choice (e.g. a search mode) must fail here, not surface at
        # runtime as an EXECUTOR OUTPUT NOT JSON error after argparse exits 2.
        for tool in self.exports["tools"]:
            executor = self.exports["executors"][tool["name"]]
            parser = subcommand_parsers(PARSERS[executor["script"]])[executor["subcommand"]]
            for name, spec in tool["inputSchema"]["properties"].items():
                if "enum" not in spec:
                    continue
                action = parser_action(parser, property_flag(name))
                with self.subTest(tool=tool["name"], argument=name):
                    self.assertEqual(set(spec["enum"]), set(action.choices))

    def test_impact_depth_maximum_matches_the_executor_limit(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "knowledge_search.py"), "capabilities"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        limits = json.loads(completed.stdout)["depthLimits"]
        (impact_tool,) = [t for t in self.exports["tools"] if t["name"] == "knowledge_impact"]
        self.assertEqual(
            impact_tool["inputSchema"]["properties"]["depth"]["maximum"], limits["impact"]
        )

    def test_definitions_are_read_only_and_steering(self) -> None:
        for tool in self.exports["tools"]:
            with self.subTest(tool=tool["name"]):
                self.assertIs(tool["annotations"]["readOnlyHint"], True)
                self.assertIs(tool["annotations"]["destructiveHint"], False)
                self.assertTrue(tool["description"])
                self.assertTrue(tool["inputSchema"]["additionalProperties"] is False)
        for name in ("knowledge_context", "knowledge_search", "knowledge_impact"):
            (tool,) = [t for t in self.exports["tools"] if t["name"] == name]
            self.assertIn("BEFORE searching force-app", tool["description"])


if __name__ == "__main__":
    unittest.main()
