from __future__ import annotations

import argparse
import unittest

from scripts import copilot_role_guard as guard
from scripts import force_app_knowledge
from scripts import knowledge_registry


# Subcommands that exist in the CLI parsers but are deliberately NOT reachable through the
# role guard. Adding a parser subcommand that appears in neither the guard allowlists nor
# this map fails the contract tests below: every new command needs an explicit decision.
INTENTIONALLY_UNGUARDED = {
    "knowledge_registry": {
        "review": "human-terminal-only: file-based review recording",
        "promote": "human-terminal-only: file-based promotion",
    },
    "force_app_knowledge": {
        "feature-crawl": "human-terminal-only: feature boundary exploration",
        "feature-draft": "human-terminal-only: feature dossier drafting",
    },
}

# Parser flags the guard deliberately does not accept for a guarded subcommand.
# Empty today: the guard mirrors every parser flag. Add entries only with a rationale.
INTENTIONALLY_EXCLUDED_FLAGS: dict[str, dict[str, set[str]]] = {
    "knowledge_registry": {},
    "force_app_knowledge": {},
}


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


class GuardParserContractTests(unittest.TestCase):
    """Pin the role-guard allowlists to the argparse surface of both knowledge CLIs.

    The guard re-implements flag validation instead of importing the parsers (it must stay
    dependency-free and fail closed), which historically drifted when a parser grew a flag
    the guard did not know about. These tests make that drift a CI failure in both
    directions.
    """

    def contract(self, script_name: str, parser: argparse.ArgumentParser, guarded: dict[str, frozenset]) -> None:
        parsers = subcommand_parsers(parser)
        unguarded = INTENTIONALLY_UNGUARDED[script_name]
        excluded = INTENTIONALLY_EXCLUDED_FLAGS[script_name]

        self.assertEqual(
            set(),
            set(guarded) & set(unguarded),
            f"{script_name}: a subcommand cannot be both guarded and intentionally unguarded",
        )
        self.assertEqual(
            set(parsers),
            set(guarded) | set(unguarded),
            f"{script_name}: every parser subcommand needs a guard allowlist entry or an "
            "INTENTIONALLY_UNGUARDED declaration (and stale entries must be removed)",
        )
        for command, guard_flags in guarded.items():
            parser_flags = option_strings(parsers[command])
            self.assertEqual(
                set(),
                set(guard_flags) - parser_flags,
                f"{script_name} {command}: guard allows flags the parser does not define",
            )
            self.assertEqual(
                set(),
                parser_flags - set(guard_flags) - excluded.get(command, set()),
                f"{script_name} {command}: parser defines flags the guard would silently "
                "deny; allow them or declare them in INTENTIONALLY_EXCLUDED_FLAGS",
            )

    def test_knowledge_registry_guard_mirrors_parser(self) -> None:
        self.contract(
            "knowledge_registry",
            knowledge_registry.build_parser(),
            guard.KNOWLEDGE_COMMAND_FLAGS,
        )

    def test_force_app_knowledge_guard_mirrors_parser(self) -> None:
        self.contract(
            "force_app_knowledge",
            force_app_knowledge.build_parser(),
            guard.FORCE_APP_COMMAND_FLAGS,
        )

    def test_query_flag_constants_stay_consistent(self) -> None:
        self.assertLessEqual(guard.KNOWLEDGE_QUERY_NON_SEMANTIC_FLAGS, guard.KNOWLEDGE_QUERY_FLAGS)
        self.assertIs(guard.KNOWLEDGE_COMMAND_FLAGS["query"], guard.KNOWLEDGE_QUERY_FLAGS)
        self.assertIs(guard.KNOWLEDGE_COMMAND_FLAGS["approve-claim"], guard.KNOWLEDGE_APPROVE_FLAGS)
        self.assertIs(guard.KNOWLEDGE_COMMAND_FLAGS["propose"], guard.KNOWLEDGE_PROPOSE_FLAGS)

    def test_role_grants_are_pinned(self) -> None:
        # Knowledge mutation stays with the knowledge roles: read commands for everyone,
        # propose/approve-claim only where a human confirmation flow exists. Widening a role
        # here must be a deliberate, reviewed change.
        self.assertEqual(
            frozenset({"config-investigator", "knowledge-curator"}),
            guard.KNOWLEDGE_MUTATION_ROLES,
        )
        for role, commands in guard.KNOWLEDGE_REGISTRY_COMMANDS.items():
            extra = commands - guard._KNOWLEDGE_READ_COMMANDS
            if role in guard.KNOWLEDGE_MUTATION_ROLES:
                self.assertEqual({"propose", "approve-claim"}, extra, role)
            else:
                self.assertEqual(set(), extra, role)
        self.assertEqual(
            set(guard.KNOWLEDGE_COMMAND_FLAGS),
            set().union(*guard.KNOWLEDGE_REGISTRY_COMMANDS.values()),
            "flag allowlists and role command grants must cover the same command set",
        )
        self.assertEqual(
            frozenset({"config-investigator", "knowledge-curator"}),
            guard.FORCE_APP_KNOWLEDGE_ROLES,
        )
        # The curator never gains org-facing or work-record authority.
        self.assertNotIn("knowledge-curator", guard.SALESFORCE_READ_ROLES)
        self.assertNotIn("knowledge-curator", getattr(guard, "WORK_RECORD_COMMANDS", {}))


if __name__ == "__main__":
    unittest.main()
