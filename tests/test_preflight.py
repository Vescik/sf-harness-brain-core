from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jsonschema import Draft202012Validator

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
        "browser": {
            "allowedOrigins": ["https://example--dev.sandbox.my.salesforce.com"],
            "profileDirectory": "/tmp/example-profile",
        },
        "workspace": {
            "salesforceRootName": "brain-core",
            "manifestPath": "manifest/package.xml",
            "promotedTestsPath": "tests/e2e",
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
        self.assertEqual(set(mcp["servers"]), {"ado-readonly", "salesforce-readonly"})
        self.assertNotIn("sandbox", mcp)
        readonly_args = mcp["servers"]["salesforce-readonly"]["args"]
        self.assertEqual(readonly_args[readonly_args.index("--mode") + 1], "review")
        ado = mcp["servers"]["ado-readonly"]
        self.assertEqual("stdio", ado["type"])
        self.assertIn("@azure-devops/mcp@2.8.1", ado["args"])
        self.assertEqual(
            ["work-items", "wiki", "test-plans"],
            ado["args"][ado["args"].index("-d") + 1 :],
        )

    def test_safe_non_production_config_passes(self) -> None:
        self.assertEqual(preflight.validate_config(safe_config()), [])

    def test_scratch_org_host_and_browser_origin_are_accepted(self) -> None:
        config = safe_config()
        scratch_host = "mpsadev.scratch.my.salesforce.com"
        config["salesforce"]["orgs"][0]["expectedInstanceHost"] = scratch_host
        config["browser"]["allowedOrigins"] = [f"https://{scratch_host}"]
        self.assertEqual(preflight.validate_config(config), [])
        schema = json.loads(
            (ROOT / "schemas/harness-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(config)), [])

    def test_developer_edition_host_is_rejected_by_logic_and_schema(self) -> None:
        config = safe_config()
        develop_host = "acme.develop.my.salesforce.com"
        config["salesforce"]["orgs"][0]["expectedInstanceHost"] = develop_host
        config["browser"]["allowedOrigins"] = [f"https://{develop_host}"]
        failures = preflight.validate_config(config)
        self.assertTrue(any("sandbox or scratch" in item for item in failures))
        schema = json.loads(
            (ROOT / "schemas/harness-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(list(Draft202012Validator(schema).iter_errors(config)), [])

    def test_production_alias_is_rejected(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["alias"] = "production"
        failures = preflight.validate_config(config)
        self.assertTrue(any("Production-like Salesforce alias" in item for item in failures))

    def test_only_development_may_allow_writes(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][1]["allowAgentWrite"] = True
        failures = preflight.validate_config(config)
        self.assertTrue(any("Only development aliases" in item for item in failures))

    def test_review_requires_read_permission(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["allowAgentRead"] = False
        failures = preflight.validate_config(config)
        self.assertTrue(any("review requires read permission" in item for item in failures))

    def test_review_requires_explicit_alias(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["allowAgentReview"] = False
        failures = preflight.validate_config(config)
        self.assertTrue(any("no alias grants" in item for item in failures))

    def test_unknown_environment_is_rejected(self) -> None:
        config = safe_config()
        config["salesforce"]["orgs"][0]["environment"] = "staging"
        failures = preflight.validate_config(config)
        self.assertTrue(any("not non-production" in item for item in failures))

    def test_write_alias_requires_shared_sandbox_approval(self) -> None:
        config = safe_config()
        config["safety"]["sharedSandboxWritesApproved"] = False
        config["safety"]["sharedSandboxApprovalRef"] = ""
        failures = preflight.validate_config(config)
        self.assertTrue(any("shared-sandbox coordination" in item for item in failures))

    def test_production_login_origin_is_rejected(self) -> None:
        failures = preflight.validate_origins(
            ["https://login.salesforce.com"], "Browser"
        )
        self.assertTrue(any("production login" in item.lower() for item in failures))

    def test_production_my_domain_browser_origin_is_rejected(self) -> None:
        failures = preflight.validate_origins(
            ["https://acme.my.salesforce.com"], "Browser"
        )
        self.assertTrue(any("explicit Salesforce sandbox or scratch host" in item for item in failures))

    def test_scratch_browser_origin_is_accepted_but_develop_origin_is_rejected(self) -> None:
        self.assertEqual(
            preflight.validate_origins(
                ["https://mpsadev.scratch.my.salesforce.com"], "Browser"
            ),
            [],
        )
        failures = preflight.validate_origins(
            ["https://acme.develop.my.salesforce.com"], "Browser"
        )
        self.assertTrue(any("sandbox or scratch host" in item for item in failures))

    def test_non_https_origin_is_rejected(self) -> None:
        failures = preflight.validate_origins(["http://example.invalid"], "Browser")
        self.assertTrue(any("must be HTTPS" in item for item in failures))

    def test_browser_and_promoted_tests_sections_are_optional(self) -> None:
        # Windows-only deployments never use guarded Playwright; forcing those placeholder
        # values was pure setup friction (owner observation, 2026-07-14).
        config = safe_config()
        del config["browser"]
        del config["workspace"]["promotedTestsPath"]
        self.assertEqual(preflight.validate_config(config), [])
        failures = preflight.validate_capability(config, "playwright")
        self.assertTrue(any("browser" in failure for failure in failures))
        self.assertTrue(any("promotedTestsPath" in failure for failure in failures))

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

    def test_wildcard_manifest_blocks_salesforce_write(self) -> None:
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Package xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            "  <types><members>*</members><name>CustomObject</name></types>\n"
            "  <types><members>ExampleClass</members><name>ApexClass</name></types>\n"
            "  <version>67.0</version>\n"
            "</Package>\n"
        )
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "manifest").mkdir()
            (root / "manifest" / "package.xml").write_text(manifest, encoding="utf-8")
            with patch.object(preflight, "metadata_root", return_value=root):
                failures = preflight.manifest_wildcard_failures(safe_config())
        self.assertEqual(len(failures), 1)
        self.assertIn("wildcard", failures[0])
        self.assertIn("CustomObject", failures[0])
        self.assertNotIn("ApexClass", failures[0])

    def test_narrowed_manifest_passes_wildcard_gate(self) -> None:
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Package xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            "  <types><members>ExampleManagedObject__c</members><name>CustomObject</name></types>\n"
            "  <version>67.0</version>\n"
            "</Package>\n"
        )
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "manifest").mkdir()
            (root / "manifest" / "package.xml").write_text(manifest, encoding="utf-8")
            with patch.object(preflight, "metadata_root", return_value=root):
                self.assertEqual(preflight.manifest_wildcard_failures(safe_config()), [])

    def test_malformed_manifest_fails_wildcard_gate(self) -> None:
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "manifest").mkdir()
            (root / "manifest" / "package.xml").write_text("<Package>", encoding="utf-8")
            with patch.object(preflight, "metadata_root", return_value=root):
                failures = preflight.manifest_wildcard_failures(safe_config())
        self.assertEqual(len(failures), 1)
        self.assertIn("not valid XML", failures[0])

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
