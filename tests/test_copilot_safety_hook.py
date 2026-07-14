from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from scripts import copilot_role_guard as role_guard
from scripts import copilot_safety_hook as safety
from scripts import knowledge_registry, work_record


def decision(output: dict[str, object]) -> tuple[str, str]:
    hook = output.get("hookSpecificOutput")
    if isinstance(hook, dict):
        return str(hook.get("permissionDecision")), str(
            hook.get("permissionDecisionReason", "")
        )
    return "continue", ""


class HumanApprovalBoundaryTests(unittest.TestCase):
    def run_hook(self, tool_name: str, command: str) -> tuple[str, str]:
        event = {"tool_name": tool_name, "tool_input": {"command": command}}
        stdout = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(event))),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(safety.main(), 0)
        return decision(json.loads(stdout.getvalue()))

    def test_detects_direct_wrapped_module_and_windows_approval_forms(self) -> None:
        commands = (
            "python3 scripts/work_record.py approve --record-id WR-1",
            "python3 /tmp/repo/scripts/work_record.py --root . approve --record-id WR-1",
            r"py -3 scripts\work_record.py approve --record-id WR-1",
            "bash -c 'python3 scripts/work_record.py approve --record-id WR-1'",
            "python3 -m scripts.work_record approve --record-id WR-1",
            "python3 scripts/work_record.py 'approve' --record-id WR-1",
            "python3 scripts/work_record.py ap''prove --record-id WR-1",
            "python3 scripts/work_record.py $(printf approve) --record-id WR-1",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(safety.is_work_record_approval_command(command))

    def test_every_terminal_tool_form_denies_approval(self) -> None:
        for tool_name in (
            "execute/runInTerminal",
            "run_in_terminal",
            "shell/execute",
            "executeCommand",
            "runTask",
        ):
            with self.subTest(tool_name=tool_name):
                actual, reason = self.run_hook(
                    tool_name,
                    "python3 scripts/work_record.py approve --record-id WR-1",
                )
                self.assertEqual(actual, "deny")
                self.assertIn("SAFE-HUMAN-001", reason)

    def test_non_approval_work_record_commands_are_not_caught_by_this_gate(self) -> None:
        self.assertFalse(
            safety.is_work_record_approval_command(
                "python3 scripts/work_record.py validate --record-id WR-1"
            )
        )
        self.assertFalse(
            safety.is_work_record_approval_command(
                "python3 scripts/work_record.py validate --record-id WR-1 && echo approve"
            )
        )

    def test_non_terminal_text_is_not_treated_as_an_approval_invocation(self) -> None:
        actual, _ = self.run_hook(
            "edit/editFiles",
            "python3 scripts/work_record.py approve --record-id WR-1",
        )
        self.assertEqual(actual, "continue")


class AgentCommandSurfaceTests(unittest.TestCase):
    @staticmethod
    def subcommands(parser: object) -> set[str]:
        for action in parser._actions:  # type: ignore[attr-defined]
            if action.dest == "command" and action.choices:
                return set(action.choices)
        return set()

    def test_work_record_allowlists_reference_only_implemented_commands(self) -> None:
        implemented = self.subcommands(work_record.build_parser())
        agent_allowed = set().union(*role_guard.WORK_RECORD_COMMANDS.values())
        self.assertEqual(agent_allowed - implemented, set())
        self.assertEqual(implemented - agent_allowed, {"approve"})
        for role in role_guard.WORK_RECORD_COMMANDS:
            with self.subTest(role=role):
                self.assertFalse(
                    role_guard.work_record_command_allowed(["approve"], role)
                )

    def test_knowledge_allowlists_keep_human_lifecycle_commands_out(self) -> None:
        implemented = self.subcommands(knowledge_registry.build_parser())
        agent_allowed = set().union(*role_guard.KNOWLEDGE_REGISTRY_COMMANDS.values())
        self.assertEqual(agent_allowed - implemented, set())
        # Only the file-based human review/promotion mechanisms stay agent-forbidden; the
        # read-only reconcile/render-indexes checks are legitimate agent self-verification
        # (2026-07-14 usability fix — denying them caused live flailing).
        self.assertEqual(implemented - agent_allowed, {"review", "promote"})
        self.assertTrue(
            role_guard.knowledge_registry_command_allowed(
                ["query", "--domain", "object-model"], "solution-designer"
            )
        )
        self.assertFalse(
            role_guard.knowledge_registry_command_allowed(
                ["query", "--at", "2026-07-10T12:00:00Z"],
                "solution-designer",
            )
        )
        self.assertFalse(
            role_guard.knowledge_registry_command_allowed(
                ["query", "--domain", "object-model", "--unknown", "value"],
                "solution-designer",
            )
        )
        self.assertTrue(
            role_guard.knowledge_registry_command_allowed(
                [
                    "propose",
                    "--claim-file",
                    ".cache/knowledge-proposals/claim.yaml",
                    "--evidence-file",
                    ".cache/knowledge-proposals/evidence.yaml",
                    "--expected-revision",
                    "0",
                ],
                "config-investigator",
            )
        )
        for unsafe_path in (
            "output/claim.yaml",
            ".ai/knowledge/claims/CLM-FAKE.yaml",
            ".cache/knowledge-proposals/../../config/harness.example.json",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                self.assertFalse(
                    role_guard.knowledge_registry_command_allowed(
                        [
                            "propose",
                            "--claim-file",
                            unsafe_path,
                            "--evidence-file",
                            ".cache/knowledge-proposals/evidence.yaml",
                            "--expected-revision",
                            "0",
                        ],
                        "config-investigator",
                    )
                )


if __name__ == "__main__":
    unittest.main()
