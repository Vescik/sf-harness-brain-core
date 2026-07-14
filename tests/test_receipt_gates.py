from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import approve_dev_tool_batch as approve_batch
from scripts import copilot_role_guard as role_guard
from scripts import copilot_safety_hook as safety
from scripts import playwright_guard
from scripts import salesforce_read


ORIGIN = "https://acme--dev.sandbox.my.salesforce.com"


def now_iso(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def base_config(**safety_flags: bool) -> dict:
    return {
        "safety": {
            "sharedSandboxWritesApproved": True,
            "sharedSandboxApprovalRef": "MPS-1",
            **safety_flags,
        },
        "browser": {"allowedOrigins": [ORIGIN], "profileDirectory": "/tmp/profile"},
        "salesforce": {
            "review": {
                "enabled": True,
                "requireDualSource": True,
                "apiVersion": "67.0",
                "allowedObjectApiNames": ["*"],
                "allowedPackageNamespaces": ["c"],
                "maxFieldsPerObject": 500,
            },
            "orgs": [
                {
                    "alias": "dev-sbx",
                    "environment": "development",
                    "allowAgentRead": True,
                    "allowAgentReview": True,
                    "allowAgentWrite": False,
                }
            ],
        },
    }


def decision(output: dict[str, object]) -> tuple[str, str]:
    hook = output.get("hookSpecificOutput")
    if isinstance(hook, dict):
        return str(hook.get("permissionDecision")), str(hook.get("permissionDecisionReason", ""))
    return "continue", ""


def run_hook(tool_name: str, tool_input: dict, config: dict | None) -> tuple[str, str]:
    event = {"tool_name": tool_name, "tool_input": tool_input}
    stdout = StringIO()
    with (
        patch("sys.stdin", StringIO(json.dumps(event))),
        patch("sys.stdout", stdout),
        patch.object(safety, "load_config", lambda root: config),
    ):
        assert safety.main() == 0
    return decision(json.loads(stdout.getvalue()))


class BrowserSessionApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="receipts-")
        self.receipts = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def write_receipt(self, session: str = "sf-harness", origin: str = ORIGIN, **extra) -> None:
        payload = {
            "kind": "browser-session-approval",
            "session": session,
            "origin": origin,
            "issuedAt": now_iso(),
            **extra,
        }
        (self.receipts / f"browser-session-{session}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def click(self, config: dict, session: str = "sf-harness") -> tuple[str, str]:
        command = f"python scripts/playwright_guard.py --session {session} click role=button"
        with patch.object(safety, "RECEIPTS_DIR", self.receipts):
            return run_hook("execute/runInTerminal", {"command": command}, config)

    def test_state_change_asks_without_a_receipt(self) -> None:
        result, reason = self.click(base_config(browserSessionApproval=True))
        self.assertEqual("ask", result)
        self.assertIn("SAFE-HUMAN-001", reason)

    def test_fresh_same_session_receipt_allows(self) -> None:
        self.write_receipt()
        result, _ = self.click(base_config(browserSessionApproval=True))
        self.assertEqual("continue", result)

    def test_receipt_is_ignored_when_the_toggle_is_off(self) -> None:
        self.write_receipt()
        result, _ = self.click(base_config(browserSessionApproval=False))
        self.assertEqual("ask", result)

    def test_expired_wrong_session_or_foreign_origin_receipts_re_ask(self) -> None:
        config = base_config(browserSessionApproval=True)
        self.write_receipt(issuedAt=now_iso(-safety.BROWSER_SESSION_TTL_MINUTES - 5))
        self.assertEqual("ask", self.click(config)[0])
        self.write_receipt(session="other")
        self.assertEqual("ask", self.click(config)[0])
        self.write_receipt(origin="https://evil.example.test")
        self.assertEqual("ask", self.click(config)[0])

    def test_navigation_commands_do_not_consult_receipts(self) -> None:
        self.write_receipt(origin="https://evil.example.test")
        command = f"python scripts/playwright_guard.py goto {ORIGIN}"
        with patch.object(safety, "RECEIPTS_DIR", self.receipts):
            result, _ = run_hook(
                "execute/runInTerminal",
                {"command": command},
                base_config(browserSessionApproval=True),
            )
        self.assertEqual("continue", result)

    def test_guard_writes_and_drops_session_receipts(self) -> None:
        with patch.object(playwright_guard, "RECEIPTS_DIR", self.receipts):
            playwright_guard.write_session_receipt("s1", ORIGIN)
            path = playwright_guard.session_receipt_path("s1")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(ORIGIN, saved["origin"])
            self.assertEqual("s1", saved["session"])
            playwright_guard.drop_session_receipt("s1")
            self.assertFalse(path.exists())


class RetrieveAutoApproveTests(unittest.TestCase):
    RETRIEVE = {"command": "sf project retrieve start --target-org dev-sbx"}

    def test_asks_without_a_fresh_preflight_receipt(self) -> None:
        config = base_config(autoApproveRetrieveWithReceipt=True)
        with patch("scripts.preflight.load_fresh_receipt", lambda *args: None):
            result, reason = run_hook("execute/runInTerminal", self.RETRIEVE, config)
        self.assertEqual("ask", result)
        self.assertIn("SAFE-HUMAN-001", reason)

    def test_fresh_receipt_and_clean_tree_allow(self) -> None:
        config = base_config(autoApproveRetrieveWithReceipt=True)
        with (
            patch("scripts.preflight.load_fresh_receipt", lambda *args: {"result": "PASS"}),
            patch.object(safety, "force_app_is_clean", lambda: True),
        ):
            result, _ = run_hook("execute/runInTerminal", self.RETRIEVE, config)
        self.assertEqual("continue", result)

    def test_dirty_tree_or_disabled_toggle_still_asks(self) -> None:
        with (
            patch("scripts.preflight.load_fresh_receipt", lambda *args: {"result": "PASS"}),
            patch.object(safety, "force_app_is_clean", lambda: False),
        ):
            result, _ = run_hook(
                "execute/runInTerminal",
                self.RETRIEVE,
                base_config(autoApproveRetrieveWithReceipt=True),
            )
        self.assertEqual("ask", result)
        with patch("scripts.preflight.load_fresh_receipt", lambda *args: {"result": "PASS"}):
            result, _ = run_hook(
                "execute/runInTerminal",
                self.RETRIEVE,
                base_config(autoApproveRetrieveWithReceipt=False),
            )
        self.assertEqual("ask", result)

    def test_deploy_and_unconfigured_alias_never_inherit_the_receipt(self) -> None:
        config = base_config(autoApproveRetrieveWithReceipt=True)
        with (
            patch("scripts.preflight.load_fresh_receipt", lambda *args: {"result": "PASS"}),
            patch.object(safety, "force_app_is_clean", lambda: True),
        ):
            result, _ = run_hook(
                "execute/runInTerminal",
                {"command": "sf project deploy start --target-org dev-sbx"},
                config,
            )
            self.assertEqual("deny", result)
            result, _ = run_hook(
                "execute/runInTerminal",
                {"command": "sf project retrieve start --target-org other-sbx"},
                config,
            )
            self.assertEqual("deny", result)


class ScopedEnumerationTests(unittest.TestCase):
    def test_bare_enumeration_tools_stay_denied(self) -> None:
        result, reason = run_hook("list_all_orgs", {}, base_config(allowScopedEnumeration=True))
        self.assertEqual("deny", result)
        self.assertIn("enumeration", reason.lower())

    def test_review_configured_orgs_requires_the_toggle(self) -> None:
        denied = safety.salesforce_review_tool_error(
            base_config(allowScopedEnumeration=False),
            "salesforce-readonly/review_configured_orgs",
            {},
        )
        self.assertIn("allowScopedEnumeration", denied)
        allowed = safety.salesforce_review_tool_error(
            base_config(allowScopedEnumeration=True),
            "salesforce-readonly/review_configured_orgs",
            {},
        )
        self.assertIsNone(allowed)
        with_args = safety.salesforce_review_tool_error(
            base_config(allowScopedEnumeration=True),
            "salesforce-readonly/review_configured_orgs",
            {"alias": "dev-sbx"},
        )
        self.assertIn("no model-controlled arguments", with_args)

    def test_salesforce_read_orgs_lists_only_configured_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "harness.local.json"
            config_path.write_text(
                json.dumps(base_config(allowScopedEnumeration=True)), encoding="utf-8"
            )
            stdout = StringIO()
            with (
                patch.object(salesforce_read, "CONFIG_PATH", config_path),
                patch("sys.stdout", stdout),
            ):
                self.assertEqual(0, salesforce_read.main(["orgs"]))
            payload = json.loads(stdout.getvalue())
        self.assertEqual(1, payload["orgCount"])
        self.assertEqual("dev-sbx", payload["orgs"][0]["alias"])
        self.assertNotIn("expectedInstanceHost", json.dumps(payload))

    def test_salesforce_read_orgs_fails_closed_without_the_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "harness.local.json"
            config_path.write_text(json.dumps(base_config()), encoding="utf-8")
            with (
                patch.object(salesforce_read, "CONFIG_PATH", config_path),
                patch("sys.stdout", StringIO()),
            ):
                self.assertEqual(2, salesforce_read.main(["orgs"]))

    def test_role_guard_allows_only_the_bare_orgs_form(self) -> None:
        self.assertTrue(
            role_guard.salesforce_read_command_allowed(["orgs"], "config-investigator")
        )
        self.assertFalse(
            role_guard.salesforce_read_command_allowed(["orgs", "--root", "/tmp"], "config-investigator")
        )


class DevToolBatchTests(unittest.TestCase):
    # assign_permission_set is one of the mutating dev tools that trips the per-invocation ask
    # (development_tool_requires_confirmation); pure test-runner tools never asked to begin with.
    ENTRY_INPUT = {"usernameOrAlias": "dev-sbx", "permSetName": "Engagement_Manager"}

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="devtool-")
        self.receipts = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def write_batch_receipt(self, used: bool = False, **overrides) -> Path:
        digest = safety.devtool_entry_digest("assign_permission_set", self.ENTRY_INPUT)
        receipt = {
            "kind": "dev-tool-batch-receipt",
            "orgAlias": "dev-sbx",
            "approvedAt": now_iso(),
            "ttlMinutes": 60,
            "entries": [{"tool": "assign_permission_set", "digest": digest, "used": used}],
            **overrides,
        }
        path = self.receipts / "devtool-batch-abc123.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return path

    def run_devtool(self, config: dict) -> tuple[str, str]:
        with patch.object(safety, "RECEIPTS_DIR", self.receipts):
            return run_hook("assign_permission_set", dict(self.ENTRY_INPUT), config)

    def test_devtool_asks_without_a_matching_receipt(self) -> None:
        result, reason = self.run_devtool(base_config(batchDevToolApproval=True))
        self.assertEqual("ask", result)
        self.assertIn("SAFE-HUMAN-001", reason)

    def test_matching_entry_allows_once_and_is_burned(self) -> None:
        path = self.write_batch_receipt()
        config = base_config(batchDevToolApproval=True)
        self.assertEqual("continue", self.run_devtool(config)[0])
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(saved["entries"][0]["used"])
        self.assertEqual("ask", self.run_devtool(config)[0])

    def test_expired_receipt_or_disabled_toggle_asks(self) -> None:
        self.write_batch_receipt(approvedAt=now_iso(-120))
        self.assertEqual("ask", self.run_devtool(base_config(batchDevToolApproval=True))[0])
        self.write_batch_receipt()
        self.assertEqual("ask", self.run_devtool(base_config(batchDevToolApproval=False))[0])

    def test_different_arguments_do_not_match_the_entry(self) -> None:
        self.write_batch_receipt()
        config = base_config(batchDevToolApproval=True)
        with patch.object(safety, "RECEIPTS_DIR", self.receipts):
            result, _ = run_hook(
                "assign_permission_set",
                {"usernameOrAlias": "dev-sbx", "permSetName": "System_Admin_Lite"},
                config,
            )
        self.assertEqual("ask", result)

    def test_copilot_cannot_invoke_the_batch_approval_script(self) -> None:
        for command in (
            "python scripts/approve_dev_tool_batch.py --plan-file .cache/devtool-batches/p.json --approver 'Jan'",
            r"py -3 scripts\approve_dev_tool_batch.py --plan-file p.json --approver Jan",
            "bash -c 'python scripts/approve_dev_tool_batch.py --plan-file p.json --approver Jan'",
        ):
            with self.subTest(command=command):
                result, reason = run_hook(
                    "execute/runInTerminal", {"command": command}, base_config()
                )
                self.assertEqual("deny", result)
                self.assertIn("SAFE-HUMAN-001", reason)


class ApproveDevToolBatchScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="approve-batch-")
        root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.plan_dir = root / "plans"
        self.receipts = root / "receipts"
        self.plan_dir.mkdir()
        self.config_path = root / "harness.local.json"
        self.config_path.write_text(
            json.dumps(base_config(batchDevToolApproval=True)), encoding="utf-8"
        )
        self.plan = {
            "schemaVersion": 1,
            "kind": "dev-tool-batch-plan",
            "orgAlias": "dev-sbx",
            "purpose": "Run local Apex tests after the accepted design change.",
            "entries": [
                {"tool": "run_apex_tests", "arguments": {"usernameOrAlias": "dev-sbx"}}
            ],
        }

    def run_script(self, plan: dict, approver: str = "Jan Kowalski") -> tuple[int, str]:
        plan_path = self.plan_dir / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        stdout = StringIO()
        with (
            patch.object(approve_batch, "PLAN_DIR", self.plan_dir),
            patch.object(approve_batch, "RECEIPTS_DIR", self.receipts),
            patch.object(approve_batch, "CONFIG_PATH", self.config_path),
            patch("sys.stdout", stdout),
        ):
            code = approve_batch.main(["--plan-file", str(plan_path), "--approver", approver])
        return code, stdout.getvalue()

    def test_valid_plan_produces_a_hook_consumable_receipt(self) -> None:
        code, output = self.run_script(self.plan)
        self.assertEqual(0, code, output)
        receipt_path = next(self.receipts.glob("devtool-batch-*.json"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual("dev-tool-batch-receipt", receipt["kind"])
        self.assertEqual("Jan Kowalski", receipt["approver"])
        expected = safety.devtool_entry_digest("run_apex_tests", {"usernameOrAlias": "dev-sbx"})
        self.assertEqual(expected, receipt["entries"][0]["digest"])
        self.assertFalse(receipt["entries"][0]["used"])

    def test_schema_invalid_and_forbidden_plans_are_rejected(self) -> None:
        invalid = dict(self.plan, entries=[{"tool": "deploy", "arguments": {}}])
        self.assertEqual(2, self.run_script(invalid)[0])
        production = dict(self.plan, orgAlias="prod-full")
        self.assertEqual(2, self.run_script(production)[0])
        self.assertEqual(2, self.run_script(self.plan, approver="<NAME>")[0])

    def test_disabled_toggle_blocks_approval(self) -> None:
        self.config_path.write_text(json.dumps(base_config()), encoding="utf-8")
        code, output = self.run_script(self.plan)
        self.assertEqual(2, code)
        self.assertIn("batchDevToolApproval", output)


if __name__ == "__main__":
    unittest.main()
