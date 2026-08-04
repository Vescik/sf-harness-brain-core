"""The validator must degrade to named audit errors, never to a lost report.

Pins the 2026-08-04 deep-test fix: a malformed input file used to raise an uncaught
exception through a check_* function, discarding every already-collected finding
(25 confirmed crash sites). These tests state what must NOT happen again."""

from __future__ import annotations

import ast
import io
import json
import shutil
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


if __name__ == "__main__":
    unittest.main()
