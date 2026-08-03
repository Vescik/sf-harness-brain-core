from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import render_repo_map, validate_harness
from scripts.render_repo_map import (
    RepoMapError,
    build_model,
    frontmatter,
    one_liner,
    render,
    render_md,
    word_count,
)

ROOT = Path(__file__).resolve().parents[1]


class RepoMapParsingTests(unittest.TestCase):
    def test_frontmatter_parses_yaml_header_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text(
                "---\nname: sample\ndescription: One thing. Two thing.\n---\nBody text\n",
                encoding="utf-8",
            )
            data, body = frontmatter(path)
        self.assertEqual("sample", data["name"])
        self.assertEqual("Body text\n", body)

    def test_frontmatter_rejects_unterminated_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("---\nname: broken\n", encoding="utf-8")
            with self.assertRaisesRegex(RepoMapError, "unterminated"):
                frontmatter(path)

    def test_one_liner_takes_first_sentence_and_truncates(self) -> None:
        self.assertEqual("Short summary", one_liner("Short summary. More detail follows."))
        long = " ".join(f"w{i}" for i in range(30))
        self.assertTrue(one_liner(long).endswith(" …"))
        self.assertLessEqual(len(one_liner(long).split()), render_repo_map.ONE_LINER_WORDS + 1)


class RepoMapRenderTests(unittest.TestCase):
    def test_model_and_md_are_deterministic_and_match_committed_artifacts(self) -> None:
        first = build_model()
        second = build_model()
        self.assertEqual(first, second)
        md = render_md(first)
        self.assertEqual(md, render_md(second))
        self.assertEqual(md, (ROOT / ".ai/repo-map.md").read_text(encoding="utf-8"))
        committed = json.loads((ROOT / ".ai/repo-map.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["wordCount"], word_count(md))
        # Coverage: every agent, skill, prompt, instruction, and contract is indexed.
        self.assertEqual(6, len(first["agents"]))
        self.assertEqual(26, len(first["skills"]))
        self.assertEqual(25, len(first["prompts"]))
        self.assertEqual(5, len(first["contracts"]))

    def test_word_budget_is_enforced(self) -> None:
        with mock.patch.object(render_repo_map, "WORD_BUDGET", 50):
            with self.assertRaisesRegex(RepoMapError, "word budget"):
                render_md(build_model())

    def test_seed_must_cover_tracked_top_level_directories(self) -> None:
        seed = json.loads((ROOT / "config/repo-map-seed.json").read_text(encoding="utf-8"))
        seed["directories"] = [
            entry for entry in seed["directories"] if entry["path"] != "scripts"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            trimmed = Path(tmp) / "seed.json"
            trimmed.write_text(json.dumps(seed), encoding="utf-8")
            with mock.patch.object(render_repo_map, "SEED_PATH", trimmed):
                with self.assertRaisesRegex(RepoMapError, "lacks top-level"):
                    build_model()

    def test_seed_rejects_untracked_directory_entries(self) -> None:
        seed = json.loads((ROOT / "config/repo-map-seed.json").read_text(encoding="utf-8"))
        seed["directories"].append({"path": "no-such-dir", "purpose": "ghost"})
        with tempfile.TemporaryDirectory() as tmp:
            extended = Path(tmp) / "seed.json"
            extended.write_text(json.dumps(seed), encoding="utf-8")
            with mock.patch.object(render_repo_map, "SEED_PATH", extended):
                with self.assertRaisesRegex(RepoMapError, "no tracked files"):
                    build_model()

    def test_check_mode_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            md_copy = Path(tmp) / "repo-map.md"
            json_copy = Path(tmp) / "repo-map.json"
            md_copy.write_text(
                (ROOT / ".ai/repo-map.md").read_text(encoding="utf-8") + "tampered\n",
                encoding="utf-8",
            )
            json_copy.write_text(
                (ROOT / ".ai/repo-map.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with mock.patch.object(render_repo_map, "MAP_MD_PATH", md_copy), mock.patch.object(
                render_repo_map, "MAP_JSON_PATH", json_copy
            ):
                with self.assertRaisesRegex(RepoMapError, "drifted"):
                    render(check=True)

    def test_committed_artifacts_pass_check_mode(self) -> None:
        result = render(check=True)
        self.assertEqual("check", result["mode"])
        self.assertLessEqual(result["words"], render_repo_map.WORD_BUDGET)


class KnowledgeConsumerSetTests(unittest.TestCase):
    """Master plan §7: "Both counts are asserted. Neither is allowed to move silently."

    These sit beside the repo-map tests because both read `.github/**` as the consumer-surface
    inventory. The point of every case below is that the gate measures the plan's named sets,
    not a list assembled next to it — the previous gate counted its own list (`search-knowledge`
    included, which owns the command menu and is not a Set A consumer) and was therefore green
    and meaningless.
    """

    PLAN_TEXT = (ROOT / validate_harness.KNOWLEDGE_MASTER_PLAN).read_text(encoding="utf-8")

    def sets(self) -> tuple[tuple[int | None, list[str]], tuple[int | None, list[str]]]:
        return (
            validate_harness.plan_consumer_set(self.PLAN_TEXT, "Set A"),
            validate_harness.plan_consumer_set(self.PLAN_TEXT, "Set B"),
        )

    def audit_root(self, root: Path) -> list[str]:
        audit = validate_harness.Audit()
        validate_harness.check_knowledge_consumer_sets(audit, root)
        return audit.errors

    def harness_copy(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "docs").mkdir(parents=True)
        (root / validate_harness.KNOWLEDGE_MASTER_PLAN).write_text(self.PLAN_TEXT, encoding="utf-8")
        shutil.copytree(ROOT / ".github", root / ".github")
        return root

    def test_plan_still_names_both_sets_in_the_parsed_shape(self) -> None:
        (declared_a, set_a), (_declared_b, set_b) = self.sets()
        self.assertEqual(8, declared_a, "§7 declares Set A as 8 surfaces")
        self.assertEqual(declared_a, len(set_a))
        self.assertEqual(3, len(set_b), f"§7 names three Set B surfaces, parsed {set_b}")
        self.assertNotIn("search-knowledge", set_a, "the menu owner is Set B, never Set A")
        self.assertIn("search-knowledge", set_b)
        self.assertEqual(set(), set(set_a) & set(set_b))

    def test_live_tree_meets_both_counts(self) -> None:
        (_declared_a, set_a), (_declared_b, set_b) = self.sets()
        self.assertEqual([], self.audit_root(ROOT))
        for name in set_a:
            path = validate_harness.consumer_surface_path(ROOT, name)
            self.assertIn(validate_harness.SET_A_CALL, path.read_text(encoding="utf-8"), name)
        for name in set_b:
            path = validate_harness.consumer_surface_path(ROOT, name)
            self.assertIn(validate_harness.SET_B_CALL, path.read_text(encoding="utf-8"), name)

    def test_set_a_surface_dropping_the_entry_lookup_fails_by_name(self) -> None:
        (_declared_a, set_a), _b = self.sets()
        for name in set_a:
            with self.subTest(surface=name), tempfile.TemporaryDirectory() as tmp:
                root = self.harness_copy(tmp)
                path = validate_harness.consumer_surface_path(root, name)
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        validate_harness.SET_A_CALL, "knowledge_registry.py query --subject-identity"
                    ),
                    encoding="utf-8",
                )
                errors = self.audit_root(root)
                self.assertTrue(errors, f"reverting {name} to a layer-2 step-1 lookup went unnoticed")
                self.assertTrue(
                    any("Set A" in message and name.removesuffix(".agent.md") in message for message in errors),
                    errors,
                )

    def test_live_tree_carries_the_hydration_rule_on_every_set_a_surface(self) -> None:
        """§7's second token. Wave 2 reported this present on all eight and it was present on two,
        so the assertion iterates the plan's Set A rather than the surfaces that happen to have it."""

        (_declared_a, set_a), _b = self.sets()
        for name in set_a:
            path = validate_harness.consumer_surface_path(ROOT, name)
            self.assertIn(
                validate_harness.SET_A_HYDRATION_RULE, path.read_text(encoding="utf-8"), name
            )

    def test_set_a_surface_dropping_the_hydration_rule_fails_by_name(self) -> None:
        (_declared_a, set_a), _b = self.sets()
        for name in set_a:
            with self.subTest(surface=name), tempfile.TemporaryDirectory() as tmp:
                root = self.harness_copy(tmp)
                path = validate_harness.consumer_surface_path(root, name)
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        validate_harness.SET_A_HYDRATION_RULE, "resolved"
                    ),
                    encoding="utf-8",
                )
                errors = self.audit_root(root)
                self.assertTrue(errors, f"{name} losing the re-read rule went unnoticed")
                self.assertTrue(
                    any(
                        "Set A" in message
                        and validate_harness.SET_A_HYDRATION_RULE in message
                        and name.removesuffix(".agent.md") in message
                        for message in errors
                    ),
                    errors,
                )

    def test_set_b_surface_dropping_its_layer_two_call_fails_by_name(self) -> None:
        _a, (_declared_b, set_b) = self.sets()
        for name in set_b:
            with self.subTest(surface=name), tempfile.TemporaryDirectory() as tmp:
                root = self.harness_copy(tmp)
                path = validate_harness.consumer_surface_path(root, name)
                path.write_text(
                    path.read_text(encoding="utf-8").replace(validate_harness.SET_B_CALL, "REMOVED"),
                    encoding="utf-8",
                )
                errors = self.audit_root(root)
                self.assertTrue(
                    any("Set B" in message and name in message for message in errors), errors
                )

    def test_dropping_the_unprofiled_type_calls_fails_with_the_type_named(self) -> None:
        """The clause that has no surface of its own: the retained --uses-object/--uses-field."""

        with tempfile.TemporaryDirectory() as tmp:
            root = self.harness_copy(tmp)
            for path in sorted((root / ".github").rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                if any(flag in text for flag in validate_harness.UNPROFILED_TYPE_CALLS):
                    for flag in validate_harness.UNPROFILED_TYPE_CALLS:
                        text = text.replace(flag, "--subject-identity")
                    path.write_text(text, encoding="utf-8")
            errors = self.audit_root(root)
            for metadata_type in ("Workflow", "ApprovalProcess", "Layout", "FieldSet"):
                self.assertTrue(
                    any(metadata_type in message for message in errors),
                    f"{metadata_type} became invisible with no gap line: {errors}",
                )

    def test_a_plan_edit_that_erases_a_set_fails_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.harness_copy(tmp)
            plan = root / validate_harness.KNOWLEDGE_MASTER_PLAN
            plan.write_text(
                self.PLAN_TEXT.replace("- **Set A —", "- Set A was here:"), encoding="utf-8"
            )
            self.assertTrue(any("cannot measure anything" in m for m in self.audit_root(root)))


if __name__ == "__main__":
    unittest.main()
