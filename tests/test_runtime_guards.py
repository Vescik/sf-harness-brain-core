from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import playwright_guard
from scripts import verify_salesforce_org as verifier
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
ORG_ID = "00D000000000001AAA"
SANDBOX_HOST = "acme--dev.sandbox.my.salesforce.com"
SCRATCH_HOST = "mpsadev.scratch.my.salesforce.com"


class SalesforceProofTests(unittest.TestCase):
    def test_local_production_instance_stops_before_org_query(self) -> None:
        runner = Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": 0,
                        "result": {
                            "instanceUrl": "https://acme.my.salesforce.com",
                            "id": "00D000000000001AAA",
                        },
                    }
                ),
                stderr="",
            )
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "dev-sbx",
                expected_host=SANDBOX_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertFalse(ok)
        self.assertEqual(runner.call_count, 1)

    def test_false_is_sandbox_is_rejected(self) -> None:
        runner = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "instanceUrl": "https://acme--dev.sandbox.my.salesforce.com",
                                "id": "00D000000000001AAA",
                            },
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "records": [
                                    {"Id": "00D000000000001AAA", "IsSandbox": False}
                                ]
                            },
                        }
                    ),
                    stderr="",
                ),
            ]
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "dev-sbx",
                expected_host=SANDBOX_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertFalse(ok)

    def test_true_is_sandbox_passes(self) -> None:
        runner = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "instanceUrl": "https://acme--dev.sandbox.my.salesforce.com",
                                "id": "00D000000000001AAA",
                            },
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "records": [
                                    {"Id": "00D000000000001AAA", "IsSandbox": True}
                                ]
                            },
                        }
                    ),
                    stderr="",
                ),
            ]
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, reason = verifier.verify_is_sandbox(
                "dev-sbx",
                expected_host=SANDBOX_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "Organization.IsSandbox=true")

    def test_scratch_org_with_exact_identity_and_is_sandbox_passes(self) -> None:
        runner = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "instanceUrl": f"https://{SCRATCH_HOST}",
                                "id": ORG_ID,
                            },
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "records": [{"Id": ORG_ID, "IsSandbox": True}]
                            },
                        }
                    ),
                    stderr="",
                ),
            ]
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, reason = verifier.verify_is_sandbox(
                "mpsa-dev",
                expected_host=SCRATCH_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "Organization.IsSandbox=true")

    def test_scratch_org_still_requires_is_sandbox_true(self) -> None:
        runner = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "instanceUrl": f"https://{SCRATCH_HOST}",
                                "id": ORG_ID,
                            },
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "records": [{"Id": ORG_ID, "IsSandbox": False}]
                            },
                        }
                    ),
                    stderr="",
                ),
            ]
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "mpsa-dev",
                expected_host=SCRATCH_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertFalse(ok)

    def test_developer_edition_host_is_rejected_before_org_query(self) -> None:
        runner = Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": 0,
                        "result": {
                            "instanceUrl": "https://acme.develop.my.salesforce.com",
                            "id": ORG_ID,
                        },
                    }
                ),
                stderr="",
            )
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "dev-hub",
                expected_host=SCRATCH_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertFalse(ok)
        self.assertEqual(runner.call_count, 1)

    def test_live_org_id_must_match_configured_identity(self) -> None:
        runner = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "instanceUrl": f"https://{SCRATCH_HOST}",
                                "id": ORG_ID,
                            },
                        }
                    ),
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": 0,
                            "result": {
                                "records": [
                                    {"Id": "00D000000000002AAA", "IsSandbox": True}
                                ]
                            },
                        }
                    ),
                    stderr="",
                ),
            ]
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "mpsa-dev",
                expected_host=SCRATCH_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertFalse(ok)


class PlaywrightRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = {"https://acme--dev.sandbox.my.salesforce.com"}

    def test_safe_snapshot_is_allowed(self) -> None:
        self.assertIsNone(
            playwright_guard.validate_request("snapshot", [], self.allowed)
        )

    def test_cookie_command_is_denied(self) -> None:
        self.assertIsNotNone(
            playwright_guard.validate_request("cookie-list", [], self.allowed)
        )

    def test_production_navigation_is_denied(self) -> None:
        self.assertIsNotNone(
            playwright_guard.validate_request(
                "goto", ["https://acme.my.salesforce.com"], self.allowed
            )
        )

    def test_profile_override_is_denied(self) -> None:
        self.assertIsNotNone(
            playwright_guard.validate_request(
                "open",
                ["https://acme--dev.sandbox.my.salesforce.com", "--profile=/tmp/other"],
                self.allowed,
            )
        )

    def test_javascript_navigation_is_denied(self) -> None:
        self.assertIsNotNone(
            playwright_guard.validate_request(
                "open", ["javascript:alert(1)"], self.allowed
            )
        )

    def test_open_without_url_is_denied(self) -> None:
        self.assertIsNotNone(
            playwright_guard.validate_request("open", [], self.allowed)
        )

    def test_cli_version_match_is_exact(self) -> None:
        self.assertTrue(playwright_guard.version_matches("Version 0.1.17\n"))
        self.assertFalse(playwright_guard.version_matches("Version 0.1.170\n"))
        self.assertFalse(playwright_guard.version_matches("Version 0.1.17-beta\n"))


class ContractConsistencyTests(unittest.TestCase):
    def test_negative_completeness_fixtures_are_rejected(self) -> None:
        cases = json.loads(
            (ROOT / "evals/fixtures/invalid-contract-states.json").read_text(
                encoding="utf-8"
            )
        )["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                schema = json.loads(
                    (ROOT / "schemas" / case["schema"]).read_text(encoding="utf-8")
                )
                instance = deepcopy(
                    json.loads(
                        (ROOT / "evals/fixtures" / case["baseFixture"]).read_text(
                            encoding="utf-8"
                        )
                    )
                )
                for dotted, value in case["patch"].items():
                    target = instance
                    parts = dotted.split(".")
                    for part in parts[:-1]:
                        target = target[part]
                    target[parts[-1]] = value
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(instance)))


if __name__ == "__main__":
    unittest.main()
