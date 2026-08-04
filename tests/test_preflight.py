from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts import copilot_role_guard as role_guard
from scripts import preflight


ROOT = Path(__file__).resolve().parents[1]


def safe_config() -> dict:
    return {
        "schemaVersion": 1,
        "ado": {
            "organization": "example-org",
            "project": "Example Project",
            "releaseQueryId": "query-1",
            "allowedHttpsOrigins": ["https://dev.azure.com/example-org"],
        },
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
        "safety": {
            "sharedSandboxWritesApproved": True,
            "sharedSandboxApprovalRef": "DEC-EXAMPLE-1",
        },
        "workspace": {
            "salesforceRootName": "brain-core",
            "manifestPath": "manifest/package.xml",
        },
        "cache": {
            "adoItemMaxAgeMinutes": 30,
            "testCaseMaxAgeMinutes": 1440,
            "onStaleDefault": "ask",
        },
    }


class PreflightValidationTests(unittest.TestCase):
    def test_workspace_root_is_the_only_salesforce_project(self) -> None:
        workspace = json.loads(
            (ROOT / "sf-harness.code-workspace").read_text(encoding="utf-8")
        )
        folders = {
            (item.get("name"), item.get("path"))
            for item in workspace.get("folders", [])
        }
        self.assertEqual(folders, {("brain-core", ".")})
        self.assertTrue((ROOT / "sfdx-project.json").is_file())
        self.assertTrue((ROOT / "manifest/package.xml").is_file())
        self.assertTrue((ROOT / "force-app").is_dir())
        self.assertTrue((ROOT / "tests/e2e").is_dir())
        self.assertFalse((ROOT / "salesforce/sfdx-project.json").exists())
        self.assertFalse(
            any(
                Path(item["path"]).is_absolute()
                or ".." in Path(item["path"]).parts
                for item in workspace.get("folders", [])
            )
        )

    def test_mcp_is_read_only_by_construction(self) -> None:
        # 2026-07-14 decision: no write-mode Salesforce MCP server and no OS sandbox keys
        # (Windows fleet); the wrapper, review facade, and safety hook are the enforcement
        # layers. ADO runs the local stdio server (pinned, domain-bounded) — it has no
        # server-side read-only mode, so ADO read-only is harness policy, not construction
        # (owner decision 2026-07-14).
        mcp = json.loads((ROOT / ".vscode/mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(mcp["servers"]), {"ado-readonly", "salesforce-readonly", "knowledge"}
        )
        knowledge = mcp["servers"]["knowledge"]
        self.assertEqual(["scripts/knowledge_mcp_server.mjs"], knowledge["args"])
        self.assertNotIn("sandbox", mcp)
        readonly_args = mcp["servers"]["salesforce-readonly"]["args"]
        self.assertEqual(readonly_args[readonly_args.index("--mode") + 1], "review")
        ado = mcp["servers"]["ado-readonly"]
        self.assertEqual("stdio", ado["type"])
        self.assertIn("@azure-devops/mcp@2.8.1", ado["args"])
        self.assertEqual(
            ["work-items", "wiki", "test-plans", "search"],
            ado["args"][ado["args"].index("-d") + 1 :],
        )

    def test_safe_non_production_config_passes(self) -> None:
        self.assertEqual(preflight.validate_config(safe_config()), [])

    def test_scratch_org_host_is_accepted(self) -> None:
        config = safe_config()
        scratch_host = "mpsadev.scratch.my.salesforce.com"
        config["salesforce"]["orgs"][0]["expectedInstanceHost"] = scratch_host
        self.assertEqual(preflight.validate_config(config), [])
        schema = json.loads(
            (ROOT / "schemas/harness-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(config)), [])

    def test_developer_edition_host_pin_is_accepted_unconditionally(self) -> None:
        """Owner 2026-08-04: any non-production host shape passes preflight; no toggle exists."""
        config = safe_config()
        config["salesforce"]["orgs"][0]["expectedInstanceHost"] = (
            "orgfarm-x-dev-ed.develop.my.salesforce.com"
        )
        self.assertEqual(
            [item for item in preflight.validate_config(config) if "identity host" in item],
            [],
        )

    def test_production_host_pin_stays_rejected(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["expectedInstanceHost"] = "acme.my.salesforce.com"
        self.assertTrue(
            any("identity host" in item for item in preflight.validate_config(config))
        )

    def test_production_alias_is_rejected(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["alias"] = "production"
        failures = preflight.validate_config(config)
        self.assertTrue(any("Production-like Salesforce alias" in item for item in failures))

    def test_retired_allow_agent_flags_are_ignored(self) -> None:
        """Owner 2026-08-04: allowAgent* flags are tolerated in old configs, read by nothing."""
        config = safe_config()
        config["salesforce"]["orgs"][0]["allowAgentRead"] = False
        config["salesforce"]["orgs"][0]["allowAgentReview"] = False
        config["salesforce"]["orgs"][1]["allowAgentWrite"] = True
        self.assertEqual(preflight.validate_config(config), [])

    def test_pinless_entry_and_empty_org_list_pass(self) -> None:
        """A minimal {alias, environment} entry (or none at all) is a valid read config —
        the facade proves live identity per call; pins only add the exact-org lane."""
        config = safe_config()
        config["salesforce"]["orgs"] = [{"alias": "any-dev", "environment": "development"}]
        self.assertEqual(preflight.validate_config(config), [])
        config["salesforce"]["orgs"] = []
        self.assertEqual(preflight.validate_config(config), [])
        schema = json.loads(
            (ROOT / "schemas/harness-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(config)), [])

    def test_identity_pins_must_travel_together(self) -> None:
        config = safe_config()
        del config["salesforce"]["orgs"][0]["expectedOrganizationId"]
        failures = preflight.validate_config(config)
        self.assertTrue(any("pins must be set together" in item for item in failures))
        schema = json.loads(
            (ROOT / "schemas/harness-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(list(Draft202012Validator(schema).iter_errors(config)), [])

    def test_denied_organization_ids_shape_is_validated(self) -> None:
        config = safe_config()
        config["salesforce"]["review"]["deniedOrganizationIds"] = ["not-an-id"]
        failures = preflight.validate_config(config)
        self.assertTrue(any("deniedOrganizationIds" in item for item in failures))

    def test_unknown_environment_is_rejected(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["environment"] = "staging"
        failures = preflight.validate_config(config)
        self.assertTrue(any("not non-production" in item for item in failures))

    def test_shared_sandbox_approval_requires_reference(self) -> None:
        config = safe_config()
        config["safety"]["sharedSandboxWritesApproved"] = True
        config["safety"]["sharedSandboxApprovalRef"] = ""
        failures = preflight.validate_config(config)
        self.assertTrue(any("approval reference" in item for item in failures))

    def test_production_login_origin_is_rejected(self) -> None:
        failures = preflight.validate_origins(
            ["https://login.salesforce.com"], "Origin"
        )
        self.assertTrue(any("production login" in item.lower() for item in failures))

    def test_non_https_origin_is_rejected(self) -> None:
        failures = preflight.validate_origins(["http://example.invalid"], "Origin")
        self.assertTrue(any("must be HTTPS" in item for item in failures))

    def test_playwright_capability_is_retired(self) -> None:
        # The browser lane was removed 2026-08-05; the capability must not silently
        # come back on either side of the guard/parser contract.
        self.assertNotIn("playwright", role_guard.PREFLIGHT_CAPABILITIES)
        source = Path(preflight.__file__).read_text(encoding="utf-8")
        self.assertNotIn("playwright", source)

    def test_release_capability_rejects_placeholder_or_blank_query_id(self) -> None:
        # The skill contract promises DEPENDENCY UNAVAILABLE for placeholder configuration;
        # the capability layer must make that deterministic, not just the global config scan.
        config = safe_config()
        with patch.dict("os.environ", {"ADO_ORGANIZATION": "example-org"}, clear=False):
            for value in ("", "   ", "<ADO_SAVED_QUERY_ID>", "<anything>"):
                config["ado"]["releaseQueryId"] = value
                failures = preflight.validate_capability(config, "release")
                self.assertTrue(any("release Query ID" in item for item in failures), value)
            config["ado"]["releaseQueryId"] = "query-1"
            self.assertEqual(preflight.validate_capability(config, "release"), [])

    def test_pass_receipt_is_reused_until_config_or_env_changes(self) -> None:
        with TemporaryDirectory() as name:
            root = Path(name)
            config_path = root / "config" / "harness.local.json"
            config_path.parent.mkdir()
            config_path.write_text('{"a": 1}', encoding="utf-8")
            with (
                patch.object(preflight, "ROOT", root),
                patch.object(preflight, "CONFIG_PATH", config_path),
                patch.object(preflight, "RECEIPT_DIR", root / ".cache/preflight"),
            ):
                self.assertIsNone(preflight.load_fresh_receipt("ado", 30))
                preflight.write_receipt("ado")
                self.assertIsNotNone(preflight.load_fresh_receipt("ado", 30))
                # zero max-age disables reuse; config change invalidates the digest binding
                self.assertIsNone(preflight.load_fresh_receipt("ado", 0))
                config_path.write_text('{"a": 2}', encoding="utf-8")
                self.assertIsNone(preflight.load_fresh_receipt("ado", 30))
                # a receipt for one capability never satisfies another
                preflight.write_receipt("metadata")
                self.assertIsNone(preflight.load_fresh_receipt("salesforce-review", 30))

    def test_ado_receipt_binds_the_runtime_organization(self) -> None:
        with TemporaryDirectory() as name:
            root = Path(name)
            config_path = root / "config" / "harness.local.json"
            config_path.parent.mkdir()
            config_path.write_text("{}", encoding="utf-8")
            with (
                patch.object(preflight, "ROOT", root),
                patch.object(preflight, "CONFIG_PATH", config_path),
                patch.object(preflight, "RECEIPT_DIR", root / ".cache/preflight"),
                patch.dict("os.environ", {"ADO_ORGANIZATION": "org-one"}),
            ):
                preflight.write_receipt("ado")
                self.assertIsNotNone(preflight.load_fresh_receipt("ado", 30))
                with patch.dict("os.environ", {"ADO_ORGANIZATION": "org-two"}):
                    self.assertIsNone(preflight.load_fresh_receipt("ado", 30))

    def test_workspace_path_traversal_is_rejected(self) -> None:
        with TemporaryDirectory() as name:
            with self.assertRaisesRegex(ValueError, "escapes"):
                preflight.contained_workspace_path(
                    Path(name), "../../private.xml", "workspace.manifestPath"
                )

    def test_absolute_workspace_path_is_rejected(self) -> None:
        with TemporaryDirectory() as name:
            outside = (Path(name).parent / "private.xml").resolve()
            with self.assertRaisesRegex(ValueError, "must be relative"):
                preflight.contained_workspace_path(
                    Path(name), str(outside), "workspace.manifestPath"
                )

    def test_ado_runtime_org_must_match_config(self) -> None:
        config = safe_config()
        with patch.dict("os.environ", {"ADO_ORGANIZATION": "other-org"}, clear=False):
            failures = preflight.validate_capability(config, "ado")
        self.assertTrue(any("must exactly match" in item for item in failures))

    def test_ado_origin_must_match_configured_organization(self) -> None:
        config = safe_config()
        config["ado"]["allowedHttpsOrigins"] = ["https://dev.azure.com/other-org"]
        failures = preflight.validate_config(config)
        self.assertTrue(any("must contain only" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
