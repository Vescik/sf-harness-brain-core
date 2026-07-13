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

    def test_mcp_network_allows_scratch_but_not_developer_edition_domains(self) -> None:
        mcp = json.loads((ROOT / ".vscode/mcp.json").read_text(encoding="utf-8"))
        domains = set(mcp["sandbox"]["network"]["allowedDomains"])
        self.assertIn("*.scratch.my.salesforce.com", domains)
        self.assertNotIn("*.develop.my.salesforce.com", domains)
        self.assertNotIn("*.salesforce.com", domains)

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
