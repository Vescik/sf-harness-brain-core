from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

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
                },
                {
                    "alias": "qa-sbx",
                    "environment": "qa",
                    "allowAgentRead": True,
                    "allowAgentWrite": False,
                },
            ]
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
    def test_designer_can_edit_decision_log(self) -> None:
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
        self.assertEqual(hook_decision(output), "continue")

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

    def test_role_root_cannot_be_shadowed_by_metadata_cwd(self) -> None:
        metadata_root = ROOT.parent / "salesforce-metadata"
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(metadata_root),
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
                    "command": "sed -i '' s/a/b/ ../salesforce-metadata/force-app/X.cls"
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
                    "path": "../salesforce-metadata/force-app/main/default/classes/X.cls"
                },
            },
            "--role",
            "development-assistant",
        )
        self.assertEqual(hook_decision(output), "continue")

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
        self.assertFalse(
            safety.is_salesforce_sandbox_origin("https://acme.my.salesforce.com")
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://acme--dev.sandbox.my.salesforce.com/unexpected-path"
            )
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

    def test_salesforce_development_path_must_stay_in_metadata_root(self) -> None:
        metadata_root = ROOT.parent / "salesforce-metadata"
        self.assertTrue(
            safety.within_root(
                str(metadata_root / "force-app/main/default/classes/X.cls"),
                metadata_root,
            )
        )
        self.assertFalse(
            safety.within_root(str(ROOT / ".github/copilot-instructions.md"), metadata_root)
        )

    def test_source_dir_array_is_included_in_path_enforcement(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT.parent / "salesforce-metadata"),
                "sourceDir": ["/tmp/outside.cls"],
            }
        )
        self.assertEqual(
            paths,
            [str(ROOT.parent / "salesforce-metadata"), "/tmp/outside.cls"],
        )

    def test_code_analyzer_path_arrays_are_included(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT.parent / "salesforce-metadata"),
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
