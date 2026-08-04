from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as role_guard
from scripts import copilot_safety_hook as safety
from scripts import playwright_guard


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

    def test_retired_salesforce_read_surfaces_are_gone(self) -> None:
        # Owner decision 2026-08-04: configured-orgs enumeration lives on the
        # review_configured_orgs facade tool alone; the CLI twin was retired with
        # scripts/salesforce_read.py and must not resurface in the role guard.
        self.assertFalse(hasattr(role_guard, "salesforce_read_command_allowed"))


class DevToolBatchRetirementTests(unittest.TestCase):
    # Owner decision 2026-08-04: the batch-approval pipeline (plan file, approval script,
    # receipt/digest/TTL machinery) is deleted. A mutating dev tool now ALWAYS stops for its
    # per-invocation human confirmation, and none of the pipeline surfaces may resurface.
    def test_mutating_dev_tool_always_asks(self) -> None:
        result, reason = run_hook(
            "assign_permission_set",
            {"usernameOrAlias": "dev-sbx", "permSetName": "Engagement_Manager"},
            base_config(),
        )
        self.assertEqual("ask", result)
        self.assertIn("SAFE-HUMAN-001", reason)

    def test_pipeline_surfaces_are_gone(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "scripts" / "approve_dev_tool_batch.py").exists())
        self.assertFalse((root / "schemas" / "dev-tool-batch.schema.json").exists())
        self.assertFalse(hasattr(safety, "consume_devtool_batch_entry"))
        self.assertFalse(hasattr(safety, "devtool_entry_digest"))


if __name__ == "__main__":
    unittest.main()
