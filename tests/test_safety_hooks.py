from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import copilot_safety_hook as safety


ROOT = Path(__file__).resolve().parents[1]


def hook_decision(output: dict[str, Any]) -> str:
    if output.get("continue") is True:
        return "continue"
    return str(output.get("hookSpecificOutput", {}).get("permissionDecision"))


def run_hook(script: str, event: dict[str, Any], *args: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def write_local_config(root: Path) -> None:
    config = {
        "salesforce": {
            "orgs": [
                {
                    "alias": "dev-sbx",
                    "environment": "development",
                    "allowAgentRead": True,
                    "allowAgentWrite": True,
                    "allowAgentReview": True,
                    "expectedInstanceHost": "example--dev.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00D000000000001AAA",
                },
                {
                    "alias": "qa-sbx",
                    "environment": "qa",
                    "allowAgentRead": True,
                    "allowAgentWrite": False,
                    "allowAgentReview": False,
                    "expectedInstanceHost": "example--qa.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00D000000000002AAA",
                },
            ],
            "review": {
                "enabled": True,
                "apiVersion": "67.0",
                "requireDualSource": True,
                "allowedPackageNamespaces": ["examplepkg"],
                "allowedObjectApiNames": ["ExampleManagedObject__c"],
                "maxObjectsPerCall": 10,
                "maxFieldsPerObject": 500,
                "evidenceMaxAgeMinutes": 30,
            },
        },
        "browser": {
            "allowedOrigins": ["https://example--dev.sandbox.my.salesforce.com"]
        },
        "safety": {
            "sharedSandboxWritesApproved": True,
            "sharedSandboxApprovalRef": "DEC-EXAMPLE-1",
        },
    }
    (root / "config").mkdir()
    (root / "config/harness.local.json").write_text(json.dumps(config), encoding="utf-8")


class GlobalSafetyHookTests(unittest.TestCase):
    def test_write_command_cannot_use_read_only_alias(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "sf data upsert bulk --file records.csv --sobject Account --target-org qa-sbx"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_write_to_read_only_alias_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "sf project deploy start --target-org qa-sbx"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_wrapped_salesforce_command_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "bash -c 'sf data query --target-org dev-sbx --query SELECT'"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_recursive_force_rm_is_denied_regardless_of_flag_order(self) -> None:
        for command in (
            "rm -rf output",
            "rm -fr output",
            "rm -f -r output",
            "rm --recursive --force output",
            "rm -r-f output",
            "/bin/rm -Rf output",
            'rm "-rf" output',  # quote splice: shell strips quotes -> rm -rf
            "r''m -rf output",  # quote splice in the command name
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_benign_rm_and_chained_flags_are_not_over_blocked(self) -> None:
        # Non-recursive rm, and a force flag that belongs to a *different* command segment,
        # must not trip the destructive gate.
        for command in ("rm -i stale.lock", "rm -f a.log && grep -r TODO src", "rm -r data"):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "continue")

    def test_quote_and_backslash_spliced_salesforce_command_is_denied(self) -> None:
        for command in (
            "s''f project deploy start --target-org dev-sbx",
            's""f org delete --target-org dev-sbx',
            "s\\f org delete --target-org dev-sbx",  # backslash splice -> sf
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_work_record_approval_module_form_is_denied(self) -> None:
        for command in (
            "python3 -m scripts.work_record approve --record-id CR-1",
            "PYTHONPATH=scripts python3 -m work_record approve --record-id CR-1",
            "python3 -mwork_record approve --record-id CR-1",  # no space after -m
            "python3 -m 'work_record' approve --record-id CR-1",  # quoted module name
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_development_mcp_without_approval_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            config_path = root / "config/harness.local.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["safety"]["sharedSandboxWritesApproved"] = False
            config["safety"]["sharedSandboxApprovalRef"] = ""
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "salesforce-development/deploy_metadata",
                    "tool_input": {"component": "Example__c"},
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_missing_target_org_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {"command": "sf data query --query 'SELECT Id FROM Account'"},
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_direct_browser_tool_is_denied_even_for_allowlisted_origin(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "playwright/browser_navigate",
                    "tool_input": {
                        "url": "https://example--dev.sandbox.my.salesforce.com/lightning/page/home"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_unallowlisted_browser_origin_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "playwright/browser_navigate",
                    "tool_input": {"url": "https://example.invalid"},
                },
            )
            self.assertEqual(hook_decision(output), "deny")


class RoleGuardTests(unittest.TestCase):
    def test_investigator_can_edit_only_ignored_knowledge_proposal_drafts(self) -> None:
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {
                    "path": ".cache/knowledge-proposals/claim.yaml"
                },
            },
            "--role",
            "config-investigator",
        )
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {
                    "path": ".ai/knowledge/claims/CLM-FAKE.yaml"
                },
            },
            "--role",
            "config-investigator",
        )
        self.assertEqual(hook_decision(allowed), "continue")
        self.assertEqual(hook_decision(denied), "deny")

    def test_investigator_propose_command_is_bound_to_draft_directory(self) -> None:
        command = (
            "python3 scripts/knowledge_registry.py propose "
            "--claim-file .cache/knowledge-proposals/claim.yaml "
            "--evidence-file .cache/knowledge-proposals/evidence.yaml "
            "--expected-revision 0"
        )
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {"command": command},
            },
            "--role",
            "config-investigator",
        )
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": command.replace(
                        ".cache/knowledge-proposals/claim.yaml",
                        "output/claim.yaml",
                    )
                },
            },
            "--role",
            "config-investigator",
        )
        self.assertEqual(hook_decision(allowed), "continue")
        self.assertEqual(hook_decision(denied), "deny")

    def test_investigator_force_app_knowledge_commands_are_narrowly_allowlisted(self) -> None:
        from scripts import copilot_role_guard as role_guard

        self.assertTrue(
            role_guard.force_app_knowledge_command_allowed(
                ["inventory"], "config-investigator"
            )
        )
        self.assertTrue(
            role_guard.force_app_knowledge_command_allowed(
                ["draft", "--observed-at", "2026-07-10T12:00:00Z"],
                "config-investigator",
            )
        )
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["inventory", "--root", "/tmp/other"], "config-investigator"
            )
        )
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["draft"], "development-assistant"
            )
        )

    def test_designer_cannot_edit_decision_log_directly(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".ai/memory/decisions-log.md"},
            },
            "--role",
            "solution-designer",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_designer_can_write_ado_cache_only(self) -> None:
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".cache/ado-items/1201.json"},
            },
            "--role",
            "solution-designer",
        )
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".cache/test-cases/701.json"},
            },
            "--role",
            "solution-designer",
        )
        self.assertEqual(hook_decision(allowed), "continue")
        self.assertEqual(hook_decision(denied), "deny")

    def test_designer_cannot_edit_metadata(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": "force-app/classes/X.cls"},
            },
            "--role",
            "solution-designer",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_file_allowlist_does_not_allow_a_suffix(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".ai/memory/decisions-log.md.backup"},
            },
            "--role",
            "solution-designer",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_role_policy_remains_enforced_from_single_root(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".ai/knowledge/fake.md"},
            },
            "--role",
            "config-investigator",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_ambiguous_edit_requires_approval(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"content": "no path"},
            },
            "--role",
            "test-strategist",
        )
        self.assertEqual(hook_decision(output), "ask")

    def test_strategist_terminal_metadata_write_is_denied(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": "sed -i '' s/a/b/ force-app/X.cls"
                },
            },
            "--role",
            "test-strategist",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_strategist_guarded_browser_click_requires_confirmation(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": "python3 scripts/playwright_guard.py --session sf-harness click e12"
                },
            },
            "--role",
            "test-strategist",
        )
        self.assertEqual(hook_decision(output), "ask")

    def test_strategist_can_write_bounded_caches(self) -> None:
        for path in (".cache/ado-items/1201.json", ".cache/test-cases/701.json"):
            with self.subTest(path=path):
                output = run_hook(
                    "copilot_role_guard.py",
                    {
                        "cwd": str(ROOT),
                        "tool_name": "edit/editFiles",
                        "tool_input": {"path": path},
                    },
                    "--role",
                    "test-strategist",
                )
                self.assertEqual(hook_decision(output), "continue")

    def test_developer_metadata_edit_is_allowed(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {
                    "path": "force-app/main/default/classes/X.cls"
                },
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(output), "continue")

    def test_developer_can_edit_salesforce_e2e_but_not_harness_tests(self) -> None:
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": "tests/e2e/example.spec.ts"},
            },
            "--role",
            "development-assistant",
        )
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": "tests/test_safety_hooks.py"},
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(allowed), "continue")
        self.assertEqual(hook_decision(denied), "deny")

    def test_developer_policy_edit_is_denied(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".github/copilot-instructions.md"},
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_developer_documentation_output_is_allowed(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": "output/documentation/example.md"},
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(output), "continue")

    def test_developer_can_write_ado_cache_but_not_test_cache(self) -> None:
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".cache/ado-items/1201.json"},
            },
            "--role",
            "development-assistant",
        )
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": ".cache/test-cases/701.json"},
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(allowed), "continue")
        self.assertEqual(hook_decision(denied), "deny")

    def test_developer_terminal_is_preflight_only(self) -> None:
        denied = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {"command": "sed -i s/a/b/ .github/copilot-instructions.md"},
            },
            "--role",
            "development-assistant",
        )
        allowed = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": "python3 scripts/preflight.py --capability metadata"
                },
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(denied), "deny")
        self.assertEqual(hook_decision(allowed), "continue")

    def test_developer_documentation_preflights_are_allowed(self) -> None:
        for capability in ("metadata", "ado"):
            with self.subTest(capability=capability):
                output = run_hook(
                    "copilot_role_guard.py",
                    {
                        "cwd": str(ROOT),
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {
                            "command": f"python3 scripts/preflight.py --capability {capability}"
                        },
                    },
                    "--role",
                    "development-assistant",
                )
                self.assertEqual(hook_decision(output), "continue")


class SafetyClassificationTests(unittest.TestCase):
    def test_salesforce_review_identity_with_empty_input_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            event = {
                "tool_name": "salesforce-readonly/review_org_identity",
                "tool_input": {},
            }
            stdout = StringIO()
            with (
                patch.object(safety, "HARNESS_ROOT", root),
                patch("sys.stdin", StringIO(json.dumps(event))),
                patch("sys.stdout", stdout),
            ):
                self.assertEqual(safety.main(), 0)
            self.assertEqual(hook_decision(json.loads(stdout.getvalue())), "continue")

    def test_salesforce_review_surface_is_exact_and_model_cannot_supply_scope(self) -> None:
        config = {
            "salesforce": {
                "orgs": [
                    {
                        "allowAgentRead": True,
                        "allowAgentReview": True,
                    }
                ],
                "review": {
                    "enabled": True,
                    "requireDualSource": True,
                    "allowedObjectApiNames": ["ExampleManagedObject__c"],
                },
            }
        }
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce-readonly/review_org_identity",
                {},
            )
        )
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce-readonly/review_object_contract",
                {"objectApiName": "ExampleManagedObject__c"},
            )
        )
        for tool, tool_input in (
            ("salesforce-readonly/run_soql_query", {"query": "SELECT Name FROM Contact"}),
            ("salesforce-readonly/list_all_orgs", {}),
            ("salesforce-readonly/review_org_identity", {"usernameOrAlias": "other"}),
            (
                "salesforce-readonly/review_object_contract",
                {"objectApiName": "Unlisted__c"},
            ),
        ):
            with self.subTest(tool=tool):
                self.assertIsNotNone(
                    safety.salesforce_review_tool_error(config, tool, tool_input)
                )

    def test_wildcard_object_allowlist_permits_any_valid_object_but_not_malformed(self) -> None:
        config = {
            "salesforce": {
                "orgs": [{"allowAgentRead": True, "allowAgentReview": True}],
                "review": {
                    "enabled": True,
                    "requireDualSource": True,
                    "allowedObjectApiNames": ["*"],
                },
            }
        }
        # any well-formed object is allowed under "*"
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce-readonly/review_object_contract",
                {"objectApiName": "AnyCustom__c"},
            )
        )
        # a malformed object name is still rejected even with "*"
        self.assertIsNotNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce-readonly/review_object_contract",
                {"objectApiName": "bad name!"},
            )
        )
        # "*" does not open raw query / org enumeration
        self.assertIsNotNone(
            safety.salesforce_review_tool_error(
                config, "salesforce-readonly/run_soql_query", {"query": "SELECT Id FROM Account"}
            )
        )

    def test_bare_mcp_tool_names_are_gated_not_bypassed(self) -> None:
        # VS Code sometimes passes bare tool names (no server prefix); the guard must still fire.
        for name, tool_input in (
            ("core_list_orgs", {}),
            ("core_list_projects", {}),
            ("list_all_orgs", {}),
            ("run_soql_query", {"query": "SELECT Id FROM Account"}),
            ("deploy_metadata", {"sourceDir": "/etc"}),
        ):
            with self.subTest(tool=name):
                output = run_hook("copilot_safety_hook.py", {"tool_name": name, "tool_input": tool_input})
                self.assertEqual(hook_decision(output), "deny")

    def test_unrecognized_mcp_tool_fails_closed_to_ask(self) -> None:
        for name in ("some_server/unknown_tool", "weird_mcp_tool"):
            with self.subTest(tool=name):
                output = run_hook("copilot_safety_hook.py", {"tool_name": name, "tool_input": {}})
                self.assertEqual(hook_decision(output), "ask")

    def test_builtin_tools_still_pass(self) -> None:
        for name, tool_input in (
            ("read", {"path": "x"}),
            ("search", {"query": "foo"}),
            ("edit/editFiles", {"path": "force-app/x.cls"}),
            ("web/fetch", {"url": "https://example.com"}),
            ("vscode/askQuestions", {}),
        ):
            with self.subTest(tool=name):
                output = run_hook("copilot_safety_hook.py", {"tool_name": name, "tool_input": tool_input})
                self.assertEqual(hook_decision(output), "continue")

    def test_work_record_commands_are_role_bound_and_approval_is_never_allowed(self) -> None:
        from scripts import copilot_role_guard as role_guard

        self.assertTrue(
            role_guard.work_record_command_allowed(
                ["context", "--record-id", "WR-1", "--role", "solution-designer"],
                "solution-designer",
            )
        )
        self.assertFalse(
            role_guard.work_record_command_allowed(
                ["context", "--record-id", "WR-1", "--role", "development-assistant"],
                "solution-designer",
            )
        )
        self.assertTrue(
            role_guard.work_record_command_allowed(
                [
                    "append-review",
                    "--record-id",
                    "WR-1",
                    "--role",
                    "guardrail-reviewer",
                ],
                "guardrail-reviewer",
            )
        )
        for role in role_guard.WORK_RECORD_COMMANDS:
            with self.subTest(role=role):
                self.assertFalse(
                    role_guard.work_record_command_allowed(
                        ["approve", "--record-id", "WR-1"], role
                    )
                )

    def test_governed_work_record_json_cannot_be_edited_directly(self) -> None:
        from scripts import copilot_role_guard as role_guard

        self.assertTrue(
            role_guard.is_governed_record_path(
                ".ai/change-records/WR-1/record.json"
            )
        )
        self.assertFalse(
            role_guard.allowed(
                ".ai/change-records/WR-1/record.json",
                (".ai/change-records/",),
            )
        )

    def test_knowledge_registry_agent_surface_cannot_promote(self) -> None:
        from scripts import copilot_role_guard as role_guard

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
        self.assertFalse(
            role_guard.knowledge_registry_command_allowed(
                [
                    "propose",
                    "--claim-file",
                    "output/claim.yaml",
                    "--evidence-file",
                    ".cache/knowledge-proposals/evidence.yaml",
                    "--expected-revision",
                    "0",
                ],
                "config-investigator",
            )
        )
        for command in ("review", "promote", "reconcile", "render-indexes"):
            with self.subTest(command=command):
                self.assertFalse(
                    role_guard.knowledge_registry_command_allowed(
                        [command], "config-investigator"
                    )
                )

    def test_ado_scope_requires_matching_org_and_project(self) -> None:
        config = {
            "ado": {"organization": "example-org", "project": "Example Project"}
        }
        self.assertIsNone(
            safety.ado_scope_error(
                config,
                {"project": "Example Project", "id": 1201},
                runtime_org="example-org",
            )
        )
        self.assertIsNotNone(
            safety.ado_scope_error(
                config,
                {"project": "Other Project", "id": 1201},
                runtime_org="example-org",
            )
        )
        self.assertIsNotNone(
            safety.ado_scope_error(
                config,
                {"id": 1201},
                runtime_org="example-org",
            )
        )
        self.assertIsNotNone(
            safety.ado_scope_error(
                config,
                {"project": "Example Project"},
                runtime_org="other-org",
            )
        )
    def test_sandbox_origin_recognition_is_strict(self) -> None:
        self.assertTrue(
            safety.is_salesforce_sandbox_origin(
                "https://acme--dev.sandbox.my.salesforce.com"
            )
        )
        self.assertTrue(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin("https://acme.my.salesforce.com")
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://acme.develop.my.salesforce.com"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://acme--dev.sandbox.my.salesforce.com/unexpected-path"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com:443"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com//"
            )
        )

    def test_allowed_origins_include_configured_scratch_but_not_developer_edition(self) -> None:
        config = {
            "browser": {
                "allowedOrigins": [
                    "https://mpsadev.scratch.my.salesforce.com",
                    "https://acme.develop.my.salesforce.com",
                ]
            }
        }
        self.assertEqual(
            safety.allowed_origins(config),
            {"https://mpsadev.scratch.my.salesforce.com"},
        )

    def test_multiple_target_orgs_are_detected(self) -> None:
        parts = [
            "sf",
            "data",
            "query",
            "--target-org",
            "dev-sbx",
            "--target-org=qa-sbx",
        ]
        self.assertEqual(safety.target_orgs(parts), ["dev-sbx", "qa-sbx"])

    def test_salesforce_development_paths_are_bounded_inside_single_root(self) -> None:
        for path in (
            ROOT / "sfdx-project.json",
            ROOT / "force-app/main/default/classes/X.cls",
            ROOT / "manifest/package.xml",
            ROOT / "tests/e2e/example.spec.ts",
        ):
            with self.subTest(path=path):
                self.assertTrue(safety.within_salesforce_source(str(path), ROOT))
        for path in (
            ROOT,
            ROOT / ".github/copilot-instructions.md",
            ROOT / "scripts/preflight.py",
            ROOT / "tests/test_safety_hooks.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(safety.within_salesforce_source(str(path), ROOT))

    def test_source_dir_array_is_included_in_path_enforcement(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT / "force-app"),
                "sourceDir": ["/tmp/outside.cls"],
            }
        )
        self.assertEqual(
            paths,
            [str(ROOT / "force-app"), "/tmp/outside.cls"],
        )

    def test_code_analyzer_path_arrays_are_included(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT / "force-app"),
                "target": ["/tmp/outside.cls"],
                "configPath": "/tmp/analyzer.yml",
                "resultsFile": "/tmp/results.html",
            }
        )
        self.assertIn("/tmp/outside.cls", paths)
        self.assertIn("/tmp/analyzer.yml", paths)
        self.assertIn("/tmp/results.html", paths)

    def test_resumed_salesforce_operation_requires_confirmation(self) -> None:
        self.assertTrue(
            safety.development_tool_requires_confirmation(
                "salesforce-development/resume_tool_operation"
            )
        )


if __name__ == "__main__":
    unittest.main()
