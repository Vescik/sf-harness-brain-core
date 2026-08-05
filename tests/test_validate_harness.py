"""The validator must degrade to named audit errors, never to a lost report.

Pins the 2026-08-04 deep-test fix: a malformed input file used to raise an uncaught
exception through a check_* function, discarding every already-collected finding
(25 confirmed crash sites). These tests state what must NOT happen again."""

from __future__ import annotations

import ast
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from scripts import validate_harness

ROOT = Path(__file__).resolve().parents[1]


class TempRootBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_audit(self, check, **kwargs) -> validate_harness.Audit:
        audit = validate_harness.Audit()
        check(audit, **kwargs)
        return audit


class TestRunChecksWrapper(unittest.TestCase):
    def test_crash_becomes_named_error_and_later_checks_still_run(self) -> None:
        audit = validate_harness.Audit()
        ran: list[str] = []

        def boom(a: validate_harness.Audit) -> None:
            raise RuntimeError("kaput")

        def after(a: validate_harness.Audit) -> None:
            ran.append("after")
            a.require(True, "never fails")

        with redirect_stderr(io.StringIO()):
            validate_harness.run_checks(audit, [boom, after])
        self.assertEqual(ran, ["after"])
        self.assertTrue(
            any("boom crashed (RuntimeError: kaput)" in message for message in audit.errors),
            audit.errors,
        )


class TestLazyScriptsImportsForbidden(unittest.TestCase):
    """C6: `from scripts.… import …` inside a function body resolves only when the repo
    root is on sys.path — it broke `python scripts/validate_harness.py` (the CI
    invocation) as soon as .ai/knowledge/artifacts/ existed. Header imports carry the
    dual-mode fallback; function bodies must not import siblings at all."""

    def test_no_function_level_scripts_imports(self) -> None:
        tree = ast.parse((ROOT / "scripts/validate_harness.py").read_text(encoding="utf-8"))
        offenders = [
            inner.module
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for inner in ast.walk(node)
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("scripts")
        ]
        self.assertEqual(offenders, [])

    def test_canonical_digest_bound_at_module_level(self) -> None:
        self.assertTrue(callable(validate_harness.canonical_digest))


class TestGuardedReads(TempRootBase):
    def test_required_text_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.required_text(self.root / "missing.md", audit), "")
        self.assertTrue(any("unreadable" in message for message in audit.errors), audit.errors)

    def test_frontmatter_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.frontmatter(self.root / "missing.md", audit), ({}, ""))
        self.assertTrue(any("unreadable" in message for message in audit.errors), audit.errors)

    def test_load_jsonc_records_unreadable(self) -> None:
        audit = validate_harness.Audit()
        self.assertEqual(validate_harness.load_jsonc(self.root / "missing.jsonc", audit), {})
        self.assertTrue(any("invalid JSONC" in message for message in audit.errors), audit.errors)


class TestSalesforceProjectShape(TempRootBase):
    def test_list_shaped_sfdx_project_is_reported_not_raised(self) -> None:
        (self.root / "sfdx-project.json").write_text("[]", encoding="utf-8")
        audit = self.run_audit(validate_harness.check_salesforce_project, root=self.root)
        self.assertTrue(
            any("must be a JSON object" in message for message in audit.errors), audit.errors
        )


class TestApplyPatch(unittest.TestCase):
    def test_applies_dotted_path(self) -> None:
        instance = {"completeness": {"status": "partial"}}
        validate_harness.apply_patch(instance, "completeness.status", "complete")
        self.assertEqual(instance["completeness"]["status"], "complete")

    def test_missing_key_raises_caught_types(self) -> None:
        with self.assertRaises(KeyError):
            validate_harness.apply_patch({}, "missing.deep.path", 1)
        with self.assertRaises(TypeError):
            validate_harness.apply_patch([], "missing.path", 1)


class TestPlanConsumerSet(unittest.TestCase):
    def test_unclosed_bold_intro_is_unparsed_not_a_crash(self) -> None:
        self.assertEqual(
            validate_harness.plan_consumer_set("- **Set A — intro never closes\n\n", "Set A"),
            (None, []),
        )

    def test_missing_colon_is_unparsed_not_a_crash(self) -> None:
        self.assertEqual(
            validate_harness.plan_consumer_set("- **Set A — intro** no colon here\n\n", "Set A"),
            (None, []),
        )


class GithubCopyBase(TempRootBase):
    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(ROOT / ".github", self.root / ".github")

    def rewrite_frontmatter(self, rel: str, mutate) -> None:
        import yaml

        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        _, body = text.split("---\n", 2)[1:]
        data = yaml.safe_load(text.split("---\n", 2)[1])
        mutate(data)
        path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + body,
                        encoding="utf-8")


class TestCustomizationsHostileFrontmatter(GithubCopyBase):
    def test_null_tools_recorded_not_raised(self) -> None:
        self.rewrite_frontmatter(
            ".github/agents/guardrail-reviewer.agent.md",
            lambda data: data.update(tools=None),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(
            any("tools must be an array" in message for message in audit.errors), audit.errors
        )

    def test_unhashable_tools_recorded_not_raised(self) -> None:
        self.rewrite_frontmatter(
            ".github/agents/development-assistant.agent.md",
            lambda data: data.update(tools=[{"a": 1}]),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(
            any("tools must be an array" in message for message in audit.errors), audit.errors
        )

    def test_date_valued_hooks_serialize_without_raising(self) -> None:
        import datetime

        self.rewrite_frontmatter(
            ".github/agents/guardrail-reviewer.agent.md",
            lambda data: data.setdefault("hooks", {}).update(probe=datetime.date(2026, 1, 1)),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertNotIn(
            "guardrail-reviewer role guard is required", audit.errors
        )  # original hooks content still present; the date must not abort serialization


class TestPlaceholdersBinaryFile(TempRootBase):
    def test_binary_asset_is_skipped_not_a_crash(self) -> None:
        github = self.root / ".github"
        github.mkdir()
        (github / "probe.bin").write_bytes(b"\xff\xfe\x00\xffnot-utf8")
        (github / "placeholders.md").write_text(
            "\n".join(sorted(validate_harness.EXPECTED_HUMAN_PLACEHOLDERS)), encoding="utf-8"
        )
        audit = self.run_audit(validate_harness.check_placeholders, root=self.root)
        self.assertEqual(audit.errors, [])


class TestRetiredSurfaceScan(TempRootBase):
    """A retired surface must be unreachable, and the scan must prove it rather than pass idly."""

    MANIFEST = {
        "schemaVersion": 1,
        "retired": [
            {
                "name": "ghost-lane",
                "retiredIn": "P1",
                "retiredOn": "2026-08-05",
                "replacement": "the replacement lane",
                "tokens": ["ghost-lane"],
                "historicalAllowlist": ["docs/history.md"],
            }
        ],
    }

    def seed(self, files: dict[str, str]) -> None:
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "config" / "retired-surfaces.json").write_text(
            json.dumps(self.MANIFEST), encoding="utf-8"
        )
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

    def test_live_reference_to_a_retired_surface_fails(self) -> None:
        self.seed({".github/prompts/live.md": "Run ghost-lane first.\n"})
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertTrue(audit.errors)
        self.assertIn("ghost-lane", audit.errors[0])
        self.assertIn(".github/prompts/live.md", audit.errors[0])

    def test_historical_document_may_keep_describing_it(self) -> None:
        self.seed({"docs/history.md": "The ghost-lane skill was retired in P1.\n"})
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertEqual(audit.errors, [])
        self.assertEqual(audit.checks, 1)

    def test_missing_manifest_is_an_audit_error_not_a_crash(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        audit = self.run_audit(validate_harness.check_retired_surfaces, root=self.root)
        self.assertTrue(audit.errors)


class TestDependencyAdmission(unittest.TestCase):
    """DEP-01 must be able to fail. A gate that cannot see a real import proves nothing."""

    def test_live_tree_admits_every_third_party_python_import(self) -> None:
        audit = validate_harness.Audit()
        validate_harness.check_dependency_admissions(audit)
        self.assertEqual(audit.errors, [])
        self.assertGreater(audit.checks, 0)

    def test_extension_modules_are_not_mistaken_for_third_party(self) -> None:
        detected = set(validate_harness.third_party_python_imports(ROOT))
        self.assertIn("jsonschema", detected)
        self.assertIn("yaml", detected)
        for stdlib_extension in ("math", "unicodedata", "hashlib"):
            self.assertNotIn(stdlib_extension, detected)

    def test_admission_records_are_schema_valid_and_named_by_digest(self) -> None:
        import hashlib as _hashlib

        from jsonschema import Draft202012Validator

        schema = json.loads(
            (ROOT / "schemas/dependency-admission.schema.json").read_text(encoding="utf-8")
        )
        records = sorted((ROOT / "config/dependency-admissions").glob("*/*.json"))
        self.assertTrue(records, "the rebuild admits at least one pre-existing exception")
        for path in records:
            record = json.loads(path.read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema).iter_errors(record))
            self.assertEqual(errors, [], f"{path.name}: {[e.message for e in errors][:3]}")
            canonical = f"{record['ecosystem']}:{record['packageName'].lower()}"
            self.assertEqual(
                record["nameDigest12"],
                _hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12],
            )
            self.assertEqual(path.name, f"{record['safeSlug']}--{record['nameDigest12']}.json")


if __name__ == "__main__":
    unittest.main()
