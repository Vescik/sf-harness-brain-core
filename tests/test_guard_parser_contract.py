from __future__ import annotations

import argparse
import unittest
import unittest.mock

from scripts import copilot_role_guard as guard
from scripts import force_app_knowledge
from scripts import knowledge_registry
from scripts import knowledge_search
from scripts import knowledge_store
from scripts import salesforce_read
from scripts import work_record


# Subcommands that exist in the CLI parsers but are deliberately NOT reachable through the
# role guard. Adding a parser subcommand that appears in neither the guard allowlists nor
# this map fails the contract tests below: every new command needs an explicit decision.
INTENTIONALLY_UNGUARDED = {
    "knowledge_registry": {
        "review": "human-terminal-only: file-based review recording",
        "promote": "human-terminal-only: file-based promotion",
    },
    "force_app_knowledge": {},
    "knowledge_store": {},
    "knowledge_search": {},
    "salesforce_read": {},
    "work_record": {
        "approve": "human-terminal-only: SAFE-HUMAN-001 — hard-denied for every role "
        "in work_record_command_allowed and by the global safety hook",
    },
}

# Parser flags the guard deliberately does not accept for a guarded subcommand.
# Empty today: the guard mirrors every parser flag. Add entries only with a rationale.
INTENTIONALLY_EXCLUDED_FLAGS: dict[str, dict[str, set[str]]] = {
    "knowledge_registry": {},
    "force_app_knowledge": {},
    "knowledge_store": {},
    "knowledge_search": {},
    "salesforce_read": {},
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
    """Pin the role-guard allowlists to the argparse surface of the guarded CLIs.

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

    def test_knowledge_store_guard_mirrors_parser(self) -> None:
        self.contract(
            "knowledge_store",
            knowledge_store.build_parser(),
            guard.KNOWLEDGE_STORE_COMMAND_FLAGS,
        )

    def test_knowledge_search_guard_mirrors_parser(self) -> None:
        self.contract(
            "knowledge_search",
            knowledge_search.build_parser(),
            guard.KNOWLEDGE_SEARCH_COMMAND_FLAGS,
        )

    def test_salesforce_read_guard_mirrors_parser(self) -> None:
        self.contract(
            "salesforce_read",
            salesforce_read.build_parser(),
            guard.SALESFORCE_READ_FLAGS,
        )

    def test_salesforce_read_guard_behavior_pins(self) -> None:
        role = sorted(guard.SALESFORCE_READ_ROLES)[0]
        # Bare scoped enumeration is allowed; any flagged variant of it is not.
        self.assertTrue(guard.salesforce_read_command_allowed(["orgs"], role))
        self.assertFalse(guard.salesforce_read_command_allowed(["orgs", "--json"], role))
        # --org stays mandatory for records/retrieve.
        self.assertFalse(
            guard.salesforce_read_command_allowed(["records", "--object", "Account"], role)
        )
        # Repeated --metadata (argparse append) is a valid guarded shape.
        self.assertTrue(
            guard.salesforce_read_command_allowed(
                ["retrieve", "--org", "dev-sbx", "--metadata", "Flow:A", "--metadata", "Flow:B"],
                role,
            )
        )

    def test_work_record_guard_covers_parser_commands(self) -> None:
        # The work_record guard validates command membership per role plus role-binding
        # flags — it keeps no per-command flag allowlists, so the contract() flag diff
        # does not apply. This is the command-set half: every parser subcommand must be
        # granted to at least one role or declared INTENTIONALLY_UNGUARDED, and a role
        # grant for a command the parser no longer defines fails in the other direction.
        parsers = subcommand_parsers(work_record.build_parser())
        granted = set().union(*guard.WORK_RECORD_COMMANDS.values())
        unguarded = INTENTIONALLY_UNGUARDED["work_record"]
        self.assertEqual(
            set(),
            granted & set(unguarded),
            "work_record: a subcommand cannot be both role-granted and intentionally unguarded",
        )
        self.assertEqual(
            set(parsers),
            granted | set(unguarded),
            "work_record: every parser subcommand needs a role grant or an "
            "INTENTIONALLY_UNGUARDED declaration (and stale grants must be removed)",
        )

    def test_work_record_approve_stays_unreachable_for_every_role(self) -> None:
        # `approve` is human-terminal-only (SAFE-HUMAN-001): the guard hard-denies it
        # before consulting the role sets, independent of the global hook's own deny.
        for role in guard.WORK_RECORD_COMMANDS:
            with self.subTest(role=role):
                self.assertFalse(
                    guard.work_record_command_allowed(["approve", "--record", "rec-1"], role)
                )

    def test_knowledge_search_is_read_only_for_every_role(self) -> None:
        # Search never mutates canonical Knowledge; `build` only writes the ignored cache.
        for role in guard.WORK_RECORD_COMMANDS:
            with self.subTest(role=role):
                self.assertTrue(
                    guard.knowledge_search_command_allowed(["search", "--text", "x"], role)
                )
                self.assertTrue(guard.knowledge_search_command_allowed(["build", "--check"], role))
                self.assertFalse(guard.knowledge_search_command_allowed(["search", "--rm"], role))

    def test_knowledge_store_mutation_commands_are_role_bound(self) -> None:
        # Entry mutations stay with the knowledge roles; reads stay universal. The approve
        # and revoke commands additionally require the safety hook's chat confirmation.
        self.assertEqual(
            frozenset({
                "entry-draft", "entry-describe", "entry-approve", "entry-revoke",
                "feature-propose", "feature-describe", "feature-approve", "feature-revoke",
            }),
            guard.KNOWLEDGE_STORE_MUTATION_COMMANDS,
        )
        # Reads stay universal, matching the entry-review precedent.
        for read_only in ("entry-review", "feature-review", "feature-status", "feature-check"):
            self.assertNotIn(read_only, guard.KNOWLEDGE_STORE_MUTATION_COMMANDS)
        self.assertLessEqual(
            guard.KNOWLEDGE_STORE_MUTATION_COMMANDS,
            set(guard.KNOWLEDGE_STORE_COMMAND_FLAGS),
        )

    def valueless_flags(self, parser: argparse.ArgumentParser) -> set[str]:
        """Every `store_true`-style flag any subcommand of this parser declares."""
        found: set[str] = set()
        for subparser in subcommand_parsers(parser).values():
            for action in subparser._actions:
                if action.option_strings and action.nargs == 0:
                    found.update(
                        option for option in action.option_strings if option.startswith("--")
                    )
        return found - {"--help"}

    def test_valueless_flag_sets_cover_every_boolean_the_parsers_declare(self) -> None:
        # A boolean missing from these sets is a fail-open: the guard skips the token after it
        # without validating, so `build --full --rm` was allowed outright. Deriving the
        # expectation from argparse means a future store_true cannot be forgotten by hand.
        for label, parser, declared in (
            ("knowledge_search", knowledge_search.build_parser(), guard.KNOWLEDGE_SEARCH_VALUELESS_FLAGS),
            ("knowledge_store", knowledge_store.build_parser(), guard.KNOWLEDGE_STORE_VALUELESS_FLAGS),
        ):
            with self.subTest(cli=label):
                self.assertLessEqual(
                    self.valueless_flags(parser),
                    set(declared),
                    f"{label}: boolean flags missing from the valueless set fail open",
                )

    def test_a_token_after_a_boolean_flag_is_still_validated(self) -> None:
        # The membership test above cannot catch a missing branch in the guard's own loop: the
        # flag would legitimately sit in the set while the loop skipped past the token after it.
        # This is the behavioural pin. `build --full --rm` was allowed outright before the fix.
        role = sorted(guard.KNOWLEDGE_MUTATION_ROLES)[0]
        self.assertFalse(guard.knowledge_search_command_allowed(["build", "--full", "--rm"], role))
        self.assertTrue(guard.knowledge_search_command_allowed(["build", "--full"], role))
        # A flag that genuinely takes a value still consumes it.
        self.assertTrue(
            guard.knowledge_store_command_allowed(["entry-check", "--changed-since", "HEAD"], role)
        )

    def test_the_store_guard_has_the_branch_its_first_boolean_will_need(self) -> None:
        # knowledge_store declares no boolean yet, so this exercises the loop against a
        # simulated one. Without the branch the guard consumes `--rm` as `--flag`'s value and
        # returns True — the exact fail-open the search guard shipped with.
        role = sorted(guard.KNOWLEDGE_MUTATION_ROLES)[0]
        with unittest.mock.patch.dict(
            guard.KNOWLEDGE_STORE_COMMAND_FLAGS, {"entry-status": frozenset({"--flag"})}
        ), unittest.mock.patch.object(
            guard, "KNOWLEDGE_STORE_VALUELESS_FLAGS", frozenset({"--flag"})
        ):
            self.assertTrue(guard.knowledge_store_command_allowed(["entry-status", "--flag"], role))
            self.assertFalse(
                guard.knowledge_store_command_allowed(["entry-status", "--flag", "--rm"], role)
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
