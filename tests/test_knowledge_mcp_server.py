"""Drive scripts/knowledge_mcp_server.mjs over stdio, the way an MCP host does.

Pattern follows tests/test_salesforce_review.py: spawn the real server, speak line-delimited
JSON-RPC, assert on the envelopes. The store on a fresh clone is empty, so empty-store
results are asserted as valid NO_ENTRY / NO_MATCH / unmatched envelopes — deliberately not
skipped: that shape is exactly what agents must learn to read as "missing entry, not
missing artifact". The interpreter is pinned to the one running this suite via
KNOWLEDGE_MCP_PYTHON so CI never depends on the server's own candidate order.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "knowledge_mcp_server.mjs"
# An identity no entry will ever project — keeps the NO_ENTRY asserts stable even after
# the store gains real entries.
PROBE_IDENTITY = "CustomObject:c:KnowledgeMcpSmokeProbe__c"
GENERATION_POINTER = ROOT / ".cache" / "knowledge-search" / "current.json"
INVENTORY_PATH = ROOT / ".cache" / "knowledge-proposals" / "force-app-inventory.json"


class KnowledgeMcpClient:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["node", str(SERVER)],
            cwd=ROOT,
            env={**os.environ, "KNOWLEDGE_MCP_PYTHON": sys.executable},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 1

    def raw_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        request_id = self.next_id
        self.next_id += 1
        self.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            + "\n"
        )
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != request_id:
            raise AssertionError(response)
        return response

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.raw_request(method, params)
        if "error" in response:
            raise AssertionError(response)
        return response["result"]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def call_error(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        response = self.raw_request("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" not in response:
            raise AssertionError(f"expected an error response, got {response}")
        return response["error"]["message"]

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()


class KnowledgeMcpFailLoudTests(unittest.TestCase):
    def test_non_json_input_stops_the_server_loudly(self) -> None:
        process = subprocess.Popen(
            ["node", str(SERVER)],
            cwd=ROOT,
            env={**os.environ, "KNOWLEDGE_MCP_PYTHON": sys.executable},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, stderr = process.communicate(input="this is not json\n", timeout=30)
        self.assertEqual(process.returncode, 2)
        self.assertIn("was not JSON", stderr)


class KnowledgeMcpServerTests(unittest.TestCase):
    client: KnowledgeMcpClient

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = KnowledgeMcpClient()
        cls.initialize_result = cls.client.request(
            "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_initialize_and_ping(self) -> None:
        self.assertEqual(self.initialize_result["serverInfo"]["name"], "sf-harness-knowledge")
        self.assertEqual(self.initialize_result["protocolVersion"], "2025-06-18")
        self.assertIn("knowledge_entry_status", self.initialize_result["instructions"])
        self.assertEqual(self.client.request("ping"), {})

    def test_tools_list_pins_the_eleven_tools(self) -> None:
        tools = self.client.request("tools/list")["tools"]
        self.assertEqual(
            {tool["name"] for tool in tools},
            {
                "knowledge_context",
                "knowledge_search",
                "knowledge_impact",
                "knowledge_resolve",
                "knowledge_entry_status",
                "knowledge_explain",
                "knowledge_feature_search",
                "knowledge_feature_context",
                "knowledge_feature_status",
                "knowledge_edge_health",
                "knowledge_capabilities",
            },
        )
        for tool in tools:
            self.assertIs(tool["annotations"]["readOnlyHint"], True)

    def test_context_returns_no_entry_for_uncovered_identity(self) -> None:
        result = self.client.call("knowledge_context", {"identity": PROBE_IDENTITY})
        envelope = result["structuredContent"]
        self.assertEqual(envelope["outcome"], "NO_ENTRY")
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), envelope)

    def test_search_returns_a_valid_empty_envelope(self) -> None:
        result = self.client.call("knowledge_search", {"text": "knowledge-mcp-smoke-probe-zzz"})
        envelope = result["structuredContent"]
        self.assertIn(envelope["outcome"], {"NO_MATCH", "NO_ENTRY", "MATCH"})
        self.assertFalse(result["isError"])

    def test_impact_traverses_without_error(self) -> None:
        result = self.client.call(
            "knowledge_impact",
            {"identity": PROBE_IDENTITY, "direction": "outgoing", "includeHeuristic": True},
        )
        self.assertNotEqual(result["structuredContent"].get("outcome"), "ERROR")
        self.assertFalse(result["isError"])

    def test_resolve_reports_unmatched_not_error(self) -> None:
        result = self.client.call("knowledge_resolve", {"names": ["KnowledgeMcpSmokeProbeZZZ"]})
        envelope = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertEqual(len(envelope["selections"]), 1)
        self.assertEqual(envelope["selections"][0]["resolution"], "unmatched")

    def test_entry_status_returns_status_envelope(self) -> None:
        result = self.client.call("knowledge_entry_status", {"identity": PROBE_IDENTITY})
        self.assertEqual(result["structuredContent"]["outcome"], "STATUS")

    def test_stale_index_is_rebuilt_transparently(self) -> None:
        # Owner decision D2: the INDEX STALE -> build -> retry dance must never reach the
        # agent. The pointer lives in the gitignored generated cache; deleting it is the
        # exact staleness the CLI refuses on, and the server must self-heal it.
        if GENERATION_POINTER.exists():
            GENERATION_POINTER.unlink()
        result = self.client.call("knowledge_context", {"identity": PROBE_IDENTITY})
        self.assertEqual(result["structuredContent"]["outcome"], "NO_ENTRY")
        self.assertTrue(GENERATION_POINTER.exists())

    def test_missing_inventory_is_rebuilt_transparently(self) -> None:
        # A fresh checkout has no generated inventory and the executor fails non-JSON on
        # it — the exact state a clone or CI runs in. The server must self-heal it the
        # same bounded way as INDEX STALE, or resolve dies precisely where it is needed
        # most (first contact with a fresh workspace).
        if INVENTORY_PATH.exists():
            INVENTORY_PATH.unlink()
        result = self.client.call("knowledge_resolve", {"names": ["KnowledgeMcpSmokeProbeZZZ"]})
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["selections"][0]["resolution"], "unmatched")
        self.assertTrue(INVENTORY_PATH.exists())

    def test_disallowed_tool_name_is_a_normalized_error(self) -> None:
        message = self.client.call_error("knowledge_store_entry_draft", {})
        self.assertIn("UNKNOWN TOOL", message)

    def test_write_flag_cannot_be_smuggled_into_resolve(self) -> None:
        message = self.client.call_error("knowledge_resolve", {"names": ["X"], "write": True})
        self.assertIn("INVALID INPUT", message)
        self.assertIn("write", message)

    def test_input_validation_rejects_bad_shapes(self) -> None:
        self.assertIn(
            "missing required argument: identity",
            self.client.call_error("knowledge_context", {}),
        )
        self.assertIn(
            "at least one of",
            self.client.call_error("knowledge_search", {}),
        )
        self.assertIn(
            "integer between 1 and 50",
            self.client.call_error("knowledge_context", {"identity": PROBE_IDENTITY, "top": 0}),
        )
        self.assertIn(
            "at most 400",
            self.client.call_error("knowledge_context", {"identity": "x" * 401}),
        )
        self.assertIn(
            "must be one of",
            self.client.call_error(
                "knowledge_impact", {"identity": PROBE_IDENTITY, "direction": "sideways"}
            ),
        )

    def test_unknown_method_is_method_not_found(self) -> None:
        response = self.client.raw_request("resources/list")
        self.assertEqual(response["error"]["code"], -32601)

    def assert_parser_accepted(self, result: dict[str, Any]) -> None:
        """The pin is flag acceptance by the live argparse surface: a dropped or renamed
        flag makes argparse exit 2 with usage text on stderr, which the server reports as
        EXECUTOR OUTPUT NOT JSON. A domain-level ERROR envelope is a legitimate answer."""
        envelope = result["structuredContent"]
        if envelope.get("outcome") == "ERROR":
            self.assertNotIn("EXECUTOR OUTPUT NOT JSON", envelope["reason"])

    def test_every_optional_flag_reaches_the_live_parser(self) -> None:
        result = self.client.call(
            "knowledge_context",
            {"identity": PROBE_IDENTITY, "top": 5, "direction": "outgoing", "includeHeuristic": True},
        )
        self.assertEqual(result["structuredContent"]["outcome"], "NO_ENTRY")
        result = self.client.call(
            "knowledge_search",
            {
                "text": "order",
                "metadataType": "CustomObject",
                "namespace": "c",
                "facet": ["apex.apiVersion=59.0"],
                "mode": "hybrid",
                "top": 5,
            },
        )
        self.assert_parser_accepted(result)
        self.assertFalse(result["isError"])
        result = self.client.call(
            "knowledge_search",
            {
                "relationAnchor": PROBE_IDENTITY,
                "relationKind": "belongs-to",
                "direction": "incoming",
                "includeHeuristic": True,
            },
        )
        self.assert_parser_accepted(result)
        result = self.client.call(
            "knowledge_search",
            {"text": "Something went wrong with the flow", "mode": "intentional-flow-error"},
        )
        self.assert_parser_accepted(result)
        result = self.client.call(
            "knowledge_impact",
            {"identity": PROBE_IDENTITY, "direction": "incoming", "depth": 2, "top": 5},
        )
        self.assert_parser_accepted(result)
        self.assertFalse(result["isError"])
        result = self.client.call(
            "knowledge_resolve",
            {"names": ["KnowledgeMcpSmokeProbeZZZ"], "paths": ["force-app/main/default"]},
        )
        self.assertEqual(len(result["structuredContent"]["selections"]), 2)

    def test_curator_surfaces_round_trip(self) -> None:
        result = self.client.call("knowledge_edge_health", {})
        self.assertEqual(result["structuredContent"]["outcome"], "EDGE_HEALTH")
        result = self.client.call("knowledge_capabilities", {})
        self.assertEqual(result["structuredContent"]["outcome"], "CAPABILITIES")
        result = self.client.call("knowledge_capabilities", {"metadataType": "CustomObject"})
        self.assertEqual(result["structuredContent"]["outcome"], "CAPABILITIES")
        result = self.client.call(
            "knowledge_explain", {"identity": PROBE_IDENTITY, "top": 5, "includeHeuristic": True}
        )
        self.assert_parser_accepted(result)
        # Feature v2 surfaces: search answers a domain envelope on an empty corpus; the
        # slug-addressed reads answer a DOMAIN error (no feature file) for an unknown but
        # well-formed slug — never an argparse failure.
        result = self.client.call("knowledge_feature_search", {"text": "anything"})
        self.assertEqual(result["structuredContent"]["outcome"], "SEARCH")
        for name, extra in (
            ("knowledge_feature_context", {}),
            ("knowledge_feature_status", {"claimIds": ["FC-001"]}),
        ):
            result = self.client.call(name, {"feature": "no-such-feature", **extra})
            self.assertEqual("ERROR", result["structuredContent"]["outcome"])
            self.assertIn("no feature at", result["structuredContent"]["reason"])

    def test_resolve_requires_names_or_paths(self) -> None:
        message = self.client.call_error("knowledge_resolve", {})
        self.assertIn("at least one of names, paths", message)
        message = self.client.call_error("knowledge_resolve", {"names": []})
        self.assertIn("at least one of names, paths", message)

    def test_array_arguments_are_bounded(self) -> None:
        message = self.client.call_error("knowledge_resolve", {"names": ["x"] * 41})
        self.assertIn("at most 40 items", message)
        message = self.client.call_error("knowledge_resolve", {"names": [""]})
        self.assertIn("non-empty strings", message)


if __name__ == "__main__":
    unittest.main()
