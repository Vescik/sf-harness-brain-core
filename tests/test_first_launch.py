"""Onboarding must accept exactly the org shapes the runtime accepts.

`first_launch.py` had no tests, and it silently drifted: it kept requiring
`*--*.sandbox.my.salesforce.com` with `IsSandbox=true` long after the 2026-07-31 decision
admitted scratch orgs and Developer Editions. The result was that the one org shape a
tester is most likely to have could not be onboarded at all — the config entry had to be
hand-written, which is how the drift stayed invisible.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("first_launch", ROOT / "scripts" / "first_launch.py")
assert SPEC and SPEC.loader
first_launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(first_launch)


class HostClassificationTests(unittest.TestCase):
    def test_sandbox_and_scratch_expect_is_sandbox_true(self) -> None:
        for host in (
            "acme--dev.sandbox.my.salesforce.com",
            "mpsadev.scratch.my.salesforce.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(first_launch.classify_non_production_host(host), (True, True))

    def test_developer_edition_expects_is_sandbox_false(self) -> None:
        """Salesforce reports false for a Developer Edition; that is the proof, not a failure."""
        self.assertEqual(
            first_launch.classify_non_production_host("orgfarm-x-dev-ed.develop.my.salesforce.com"),
            (True, False),
        )

    def test_production_and_login_hosts_are_refused(self) -> None:
        for host in (
            "acme.my.salesforce.com",
            "login.salesforce.com",
            "acme.develop.my.salesforce.com.evil.test",
            "",
        ):
            with self.subTest(host=host):
                self.assertIsNone(first_launch.classify_non_production_host(host))


class ConfigWritingTests(unittest.TestCase):
    def test_developer_edition_turns_on_allow_any_non_production(self) -> None:
        """Without the toggle, preflight rejects the very entry onboarding just wrote."""
        cfg = {
            "ado": {},
            "salesforce": {"orgs": [{"environment": "development"}], "review": {}},
        }
        pending = {
            "org.development": {
                "alias": "devmp",
                "host": "orgfarm-x-dev-ed.develop.my.salesforce.com",
                "orgId": "00D000000000000EAA",
            },
            "review.allowAnyNonProduction": True,
        }
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config(pending)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(written["salesforce"]["review"]["allowAnyNonProduction"])
        org = written["salesforce"]["orgs"][0]
        self.assertEqual(org["expectedInstanceHost"], "orgfarm-x-dev-ed.develop.my.salesforce.com")
        self.assertFalse(org["allowAgentWrite"])

    def test_sandbox_onboarding_does_not_touch_the_toggle(self) -> None:
        cfg = {
            "ado": {},
            "salesforce": {"orgs": [{"environment": "development"}], "review": {}},
        }
        pending = {
            "org.development": {
                "alias": "dev-sbx",
                "host": "acme--dev.sandbox.my.salesforce.com",
                "orgId": "00D000000000001AAA",
            },
        }
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "harness.local.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(first_launch, "CONFIG_PATH", path):
                first_launch.apply_config(pending)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("allowAnyNonProduction", written["salesforce"]["review"])


if __name__ == "__main__":
    unittest.main()
