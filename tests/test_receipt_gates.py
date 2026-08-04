from __future__ import annotations

import json
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import copilot_role_guard as role_guard
from scripts import copilot_safety_hook as safety


ORIGIN = "https://acme--dev.sandbox.my.salesforce.com"


def base_config(**safety_flags: bool) -> dict:
    return {
        "safety": {
            "sharedSandboxWritesApproved": True,
            "sharedSandboxApprovalRef": "MPS-1",
            **safety_flags,
        },
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


class BrowserLaneRetirementTests(unittest.TestCase):
    """The browser automation lane is gone (2026-08-05); its receipt machinery must stay gone.

    A re-added session-receipt bypass would soften SAFE-HUMAN-001 without any surviving
    executor to write receipts, so the absence itself is the contract.
    """

    def test_browser_session_receipt_machinery_is_gone(self) -> None:
        self.assertFalse(hasattr(safety, "browser_session_approved"))
        self.assertFalse(hasattr(safety, "playwright_session_name"))
        self.assertFalse(hasattr(safety, "STATE_CHANGING_BROWSER"))
        self.assertFalse((Path(safety.__file__).resolve().parents[1] / "scripts/playwright_guard.py").exists())

    def test_guard_invocation_is_denied_not_asked(self) -> None:
        command = "python scripts/playwright_guard.py --session sf-harness click role=button"
        result, reason = run_hook("execute/runInTerminal", {"command": command}, base_config())
        self.assertEqual("deny", result)
        self.assertIn("Direct browser tooling is disabled", reason)


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
