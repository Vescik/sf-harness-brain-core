from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import copilot_role_guard as guard
from scripts import salesforce_read as sr


def make_config(root: Path, *, enabled=True, alias="dev-sbx", read=True, review=True,
                objects=("Account", "Contact"), api="67.0") -> Path:
    config = {
        "salesforce": {
            "orgs": [
                {
                    "alias": alias,
                    "environment": "development",
                    "allowAgentRead": read,
                    "allowAgentReview": review,
                    "allowAgentWrite": False,
                    "expectedInstanceHost": "acme--dev.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00D000000000001AAA",
                }
            ],
            "review": {
                "enabled": enabled,
                "apiVersion": api,
                "requireDualSource": True,
                "allowedPackageNamespaces": ["c"],
                "allowedObjectApiNames": list(objects),
                "maxObjectsPerCall": 10,
                "maxFieldsPerObject": 500,
                "evidenceMaxAgeMinutes": 30,
            },
        }
    }
    path = root / "harness.local.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def query_runner(records=None):
    payload = {"status": 0, "result": {"records": records or [{"Id": "001", "Name": "Acme"}]}}
    return Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""))


class RecordsReadTests(unittest.TestCase):
    def _run(self, argv, *, config_kwargs=None, sandbox_ok=True, runner=None):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cfg = make_config(root, **(config_kwargs or {}))
            runner = runner or query_runner()
            with patch.object(sr, "CONFIG_PATH", cfg), \
                 patch.object(sr, "configured_identity", return_value=("acme--dev.sandbox.my.salesforce.com", "00D000000000001AAA")), \
                 patch.object(sr, "verify_is_sandbox", return_value=(sandbox_ok, "ok" if sandbox_ok else "not sandbox")), \
                 patch.object(sr.shutil, "which", return_value="/usr/bin/sf"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = sr.main(argv, runner=runner)
                return code, buf.getvalue(), runner

    def test_valid_records_read_builds_bounded_query(self) -> None:
        code, out, runner = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account", "--fields", "Id,Name", "--limit", "25"]
        )
        self.assertEqual(code, 0)
        query = runner.call_args.args[0][runner.call_args.args[0].index("--query") + 1]
        self.assertEqual(query, "SELECT Id, Name FROM Account LIMIT 25")
        self.assertIn("--target-org", runner.call_args.args[0])
        self.assertIn("recordCount", out)

    def test_default_fields_and_limit(self) -> None:
        code, _out, runner = self._run(["records", "--org", "dev-sbx", "--object", "Contact"])
        self.assertEqual(code, 0)
        query = runner.call_args.args[0][runner.call_args.args[0].index("--query") + 1]
        self.assertEqual(query, "SELECT Id FROM Contact LIMIT 50")

    def test_order_by_is_validated_and_included(self) -> None:
        code, _out, runner = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account", "--order-by", "CreatedDate DESC"]
        )
        self.assertEqual(code, 0)
        query = runner.call_args.args[0][runner.call_args.args[0].index("--query") + 1]
        self.assertEqual(query, "SELECT Id FROM Account ORDER BY CreatedDate DESC LIMIT 50")

    def test_object_outside_allowlist_is_blocked(self) -> None:
        code, out, runner = self._run(["records", "--org", "dev-sbx", "--object", "Opportunity"])
        self.assertEqual(code, 2)
        self.assertIn("allowlist", out)
        runner.assert_not_called()

    def test_wildcard_allowlist_permits_any_valid_object(self) -> None:
        code, _out, runner = self._run(
            ["records", "--org", "dev-sbx", "--object", "Opportunity"],
            config_kwargs={"objects": ("*",)},
        )
        self.assertEqual(code, 0)
        query = runner.call_args.args[0][runner.call_args.args[0].index("--query") + 1]
        self.assertEqual(query, "SELECT Id FROM Opportunity LIMIT 50")

    def test_wildcard_still_rejects_malformed_object_name(self) -> None:
        code, _out, runner = self._run(
            ["records", "--org", "dev-sbx", "--object", "Bad Name!"],
            config_kwargs={"objects": ("*",)},
        )
        self.assertEqual(code, 2)
        runner.assert_not_called()

    def test_injection_in_fields_is_blocked(self) -> None:
        for bad in ["Id,(SELECT Id FROM Contacts)", "Name;DROP", "Id WHERE", "Id)--"]:
            code, out, runner = self._run(
                ["records", "--org", "dev-sbx", "--object", "Account", "--fields", bad]
            )
            self.assertEqual(code, 2, bad)
            runner.assert_not_called()

    def test_limit_over_cap_is_blocked(self) -> None:
        code, out, _ = self._run(["records", "--org", "dev-sbx", "--object", "Account", "--limit", "5000"])
        self.assertEqual(code, 2)
        self.assertIn("limit", out)

    def test_malformed_order_by_is_blocked(self) -> None:
        code, _out, _ = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account", "--order-by", "Name; DROP"]
        )
        self.assertEqual(code, 2)

    def test_review_disabled_is_blocked(self) -> None:
        code, out, _ = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account"], config_kwargs={"enabled": False}
        )
        self.assertEqual(code, 2)
        self.assertIn("review is disabled", out)

    def test_org_without_review_grant_is_blocked(self) -> None:
        code, out, _ = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account"], config_kwargs={"review": False}
        )
        self.assertEqual(code, 2)

    def test_failed_sandbox_proof_blocks_read(self) -> None:
        code, out, runner = self._run(
            ["records", "--org", "dev-sbx", "--object", "Account"], sandbox_ok=False
        )
        self.assertEqual(code, 2)
        self.assertIn("sandbox proof failed", out)
        runner.assert_not_called()


class MetadataRetrieveTests(unittest.TestCase):
    def _run(self, argv, runner=None):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cfg = make_config(root)
            runner = runner or Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
            with patch.object(sr, "CONFIG_PATH", cfg), \
                 patch.object(sr, "HARNESS_ROOT", root), \
                 patch.object(sr, "configured_identity", return_value=("acme--dev.sandbox.my.salesforce.com", "00D000000000001AAA")), \
                 patch.object(sr, "verify_is_sandbox", return_value=(True, "ok")), \
                 patch.object(sr.shutil, "which", return_value="/usr/bin/sf"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = sr.main(argv, runner=runner)
                return code, buf.getvalue(), runner

    def test_allowlisted_type_builds_retrieve_command(self) -> None:
        code, out, runner = self._run(
            ["retrieve", "--org", "dev-sbx", "--metadata", "ApexClass:MyController", "--metadata", "CustomObject:Account"]
        )
        self.assertEqual(code, 0)
        cmd = runner.call_args.args[0]
        self.assertIn("--target-metadata-dir", cmd)
        self.assertEqual(cmd.count("--metadata"), 2)

    def test_disallowed_metadata_type_is_blocked(self) -> None:
        code, out, runner = self._run(["retrieve", "--org", "dev-sbx", "--metadata", "NamedCredential:Secret"])
        self.assertEqual(code, 2)
        self.assertIn("not allowlisted", out)
        runner.assert_not_called()

    def test_malformed_metadata_name_is_blocked(self) -> None:
        code, _out, runner = self._run(["retrieve", "--org", "dev-sbx", "--metadata", "ApexClass:../etc/passwd"])
        self.assertEqual(code, 2)
        runner.assert_not_called()


class RoleGuardSurfaceTests(unittest.TestCase):
    def test_records_and_retrieve_allowed_for_review_role(self) -> None:
        self.assertTrue(guard.salesforce_read_command_allowed(
            ["records", "--org", "dev-sbx", "--object", "Account", "--fields", "Id,Name"], "config-investigator"))
        self.assertTrue(guard.salesforce_read_command_allowed(
            ["retrieve", "--org", "dev-sbx", "--metadata", "ApexClass:X"], "guardrail-reviewer"))

    def test_missing_org_or_unknown_flag_or_root_is_denied(self) -> None:
        self.assertFalse(guard.salesforce_read_command_allowed(["records", "--object", "Account"], "config-investigator"))
        self.assertFalse(guard.salesforce_read_command_allowed(
            ["records", "--org", "dev-sbx", "--query", "SELECT"], "config-investigator"))
        self.assertFalse(guard.salesforce_read_command_allowed(
            ["records", "--org", "dev-sbx", "--object", "Account", "--root", "/tmp"], "config-investigator"))

    def test_unknown_subcommand_is_denied(self) -> None:
        self.assertFalse(guard.salesforce_read_command_allowed(["delete", "--org", "dev-sbx"], "config-investigator"))


if __name__ == "__main__":
    unittest.main()
