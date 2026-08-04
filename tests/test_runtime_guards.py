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
        self.assertEqual(reason, f"non-production identity proven for host '{SANDBOX_HOST}'")

    def test_both_sf_calls_get_the_full_sixty_second_budget(self) -> None:
        # Regression pin (owner-reported live failure, 2026-08-04): a cold `sf` start
        # regularly exceeds 10s, and the old `min(timeout, 10)` cap on `org display` failed
        # the non-production proof on latency alone. Both calls must receive the full
        # 60s default; re-introducing a shorter hidden cap must fail here by name.
        runner = Mock(
            side_effect=self._display_and_query(SANDBOX_HOST, ORG_ID, True)
        )
        with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
            ok, _ = verifier.verify_is_sandbox(
                "dev-sbx",
                expected_host=SANDBOX_HOST,
                expected_org_id=ORG_ID,
                runner=runner,
            )
        self.assertTrue(ok)
        timeouts = [call.kwargs["timeout"] for call in runner.call_args_list]
        self.assertEqual([60, 60], timeouts)

    def _display_and_query(self, host: str, org_id: str, is_sandbox: bool) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": 0,
                        "result": {"instanceUrl": f"https://{host}", "id": org_id},
                    }
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": 0,
                        "result": {"records": [{"Id": org_id, "IsSandbox": is_sandbox}]},
                    }
                ),
                stderr="",
            ),
        ]

    def test_dynamic_lane_accepts_sandbox_scratch_and_dev_edition(self) -> None:
        # Owner decision 2026-07-31: no pins supplied -> the live identity itself must prove a
        # non-production host with a consistent Organization row.
        for host, is_sandbox in (
            (SANDBOX_HOST, True),
            (SCRATCH_HOST, True),
            ("orgfarm-x-dev-ed.develop.my.salesforce.com", False),
        ):
            with self.subTest(host=host):
                runner = Mock(side_effect=self._display_and_query(host, ORG_ID, is_sandbox))
                with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
                    ok, reason = verifier.verify_is_sandbox("dev-box", runner=runner)
                self.assertTrue(ok, reason)

    def test_denied_organization_id_is_refused_in_both_lanes(self) -> None:
        # review.deniedOrganizationIds (owner 2026-08-04) is the org-level brake of the
        # read-anywhere convention; the 15-character prefix is the identity, so an
        # 18-character live ID must still match a 15-character denylist entry.
        denied = frozenset({ORG_ID[:15]})
        for pins in ({}, {"expected_host": SANDBOX_HOST, "expected_org_id": ORG_ID}):
            with self.subTest(pinned=bool(pins)):
                runner = Mock(side_effect=self._display_and_query(SANDBOX_HOST, ORG_ID, True))
                with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
                    ok, reason = verifier.verify_is_sandbox(
                        "dev-box", denied_org_ids=denied, runner=runner, **pins
                    )
                self.assertFalse(ok)
                self.assertIn("deniedOrganizationIds", reason)

    def test_dynamic_lane_rejects_production_signature_and_identity_drift(self) -> None:
        cases = [
            # Production host never parses as non-production, with or without pins.
            self._display_and_query("acme.my.salesforce.com", ORG_ID, False),
            # Dev Edition host must report IsSandbox=false; true is a spoofed signature.
            self._display_and_query("orgfarm-x-dev-ed.develop.my.salesforce.com", ORG_ID, True),
            # Sandbox host reporting IsSandbox=false stays refused in the dynamic lane too.
            self._display_and_query(SANDBOX_HOST, ORG_ID, False),
        ]
        # Organization row naming a different org than the authorized alias is drift.
        drift = self._display_and_query(SANDBOX_HOST, ORG_ID, True)
        drift[1] = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": 0,
                    "result": {"records": [{"Id": "00D000000000009AAA", "IsSandbox": True}]},
                }
            ),
            stderr="",
        )
        cases.append(drift)
        for side_effect in cases:
            with self.subTest(case=side_effect[0].stdout[:80]):
                runner = Mock(side_effect=side_effect)
                with patch.object(verifier.shutil, "which", return_value="/usr/bin/sf"):
                    ok, _ = verifier.verify_is_sandbox("dev-box", runner=runner)
                self.assertFalse(ok)

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
        self.assertEqual(reason, f"non-production identity proven for host '{SCRATCH_HOST}'")

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
