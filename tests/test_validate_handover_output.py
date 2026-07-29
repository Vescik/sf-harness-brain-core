from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import validate_handover_output as render_check


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_TEMPLATE = ROOT / ".ai/templates/release-handover.md"

TEMPLATE = """# Template: Release Handover

<!--
Header comment: consumer, output location, rules.
-->

# Release Handover — <release period>

## Header

- Release period: `<month/year>`

## Handover description

<!-- General introduction. -->

## Table of contents

- `<User Story ID> - <Title>`

---

<!-- The section below repeats for EVERY item in the release. -->
<!-- repeat-per-item -->

## <User Story ID> - <Title>

Category: `<ADO Category field value>`

### Summary

<!-- AI-generated. -->

### Acceptance criteria

- `<Acceptance criterion>`

No acceptance criteria documented

### Technical table

| Component type | Name | Purpose (one sentence) | Manual steps reference |
|---|---|---|---|

No published technical documentation — [Missing Wiki Link]

### Tests

- `<Test Case title>`

Tested based on acceptance criteria
"""


def build_draft(template_text: str, items: int) -> str:
    """Generate a minimal conforming draft from any template — the proof that edits flow."""
    shape = render_check.parse_template(template_text)
    lines: list[str] = []
    for pattern in shape.prelude:
        lines.append(f"{'#' * pattern.level} {re.sub(r'<[^>]+>', 'X', pattern.label)}")
        lines.append("")
        lines.append("filler")
        lines.append("")
    for _ in range(items):
        for pattern in shape.item_block:
            lines.append(f"{'#' * pattern.level} {re.sub(r'<[^>]+>', 'X', pattern.label)}")
            lines.append("")
            lines.append("filler")
            lines.append("")
    return "\n".join(lines)


class TemplateParsingTests(unittest.TestCase):
    def test_template_metadata_h1_and_comments_are_not_structure(self) -> None:
        shape = render_check.parse_template(TEMPLATE)
        labels = [pattern.label for pattern in shape.prelude]
        self.assertEqual(
            ["Release Handover — <release period>", "Header", "Handover description", "Table of contents"],
            labels,
        )
        self.assertTrue(shape.has_marker)
        self.assertEqual(1, shape.marker_count)
        self.assertEqual(
            ["<User Story ID> - <Title>", "Summary", "Acceptance criteria", "Technical table", "Tests"],
            [pattern.label for pattern in shape.item_block],
        )

    def test_fixed_texts_exclude_bullets_tables_rulers_and_placeholders(self) -> None:
        self.assertEqual(
            [
                "No acceptance criteria documented",
                "No published technical documentation — [Missing Wiki Link]",
                "Tested based on acceptance criteria",
            ],
            render_check.template_fixed_texts(TEMPLATE),
        )

    def test_canonical_template_parses_with_marker_and_three_fallbacks(self) -> None:
        # Pins the derivation rules against the committed template. This test should only
        # change when the derivation semantics change, not when sections are edited.
        text = CANONICAL_TEMPLATE.read_text(encoding="utf-8")
        shape = render_check.parse_template(text)
        self.assertEqual(1, shape.marker_count)
        self.assertGreaterEqual(len(shape.prelude), 1)
        self.assertGreaterEqual(len(shape.item_block), 1)
        self.assertEqual(
            [
                "No acceptance criteria documented",
                "No published technical documentation — [Missing Wiki Link]",
                "Tested based on acceptance criteria",
            ],
            render_check.template_fixed_texts(text),
        )


class DraftValidationTests(unittest.TestCase):
    def validate(self, template_text: str, draft_text: str) -> dict:
        return render_check.validate_draft(
            render_check.parse_template(template_text), draft_text
        )

    def test_conforming_two_item_draft_passes(self) -> None:
        result = self.validate(TEMPLATE, build_draft(TEMPLATE, items=2))
        self.assertEqual("pass", result["status"], result["errors"])
        self.assertEqual(2, result["items"])
        self.assertEqual([], result["warnings"])

    def test_agent_added_section_fails(self) -> None:
        # The exact T11 drift class: sections invented beyond the template.
        draft = build_draft(TEMPLATE, items=1) + "\n## Generation Metadata\n\nfiller\n"
        result = self.validate(TEMPLATE, draft)
        self.assertEqual("fail", result["status"])
        self.assertTrue(any("Generation Metadata" in error for error in result["errors"]))

    def test_missing_item_section_fails(self) -> None:
        draft = build_draft(TEMPLATE, items=1).replace("### Tests\n\nfiller\n", "")
        result = self.validate(TEMPLATE, draft)
        self.assertEqual("fail", result["status"])
        self.assertTrue(any("### Tests" in error for error in result["errors"]))

    def test_reordered_prelude_fails(self) -> None:
        draft = build_draft(TEMPLATE, items=0).replace(
            "## Header\n\nfiller\n\n## Handover description",
            "## Handover description\n\nfiller\n\n## Header",
        )
        result = self.validate(TEMPLATE, draft)
        self.assertEqual("fail", result["status"])

    def test_demoted_item_heading_level_fails(self) -> None:
        draft = build_draft(TEMPLATE, items=1).replace("## X - X", "### X - X")
        result = self.validate(TEMPLATE, draft)
        self.assertEqual("fail", result["status"])

    def test_zero_items_pass_with_warning(self) -> None:
        result = self.validate(TEMPLATE, build_draft(TEMPLATE, items=0))
        self.assertEqual("pass", result["status"], result["errors"])
        self.assertEqual(0, result["items"])
        self.assertTrue(any("empty-release" in warning for warning in result["warnings"]))

    def test_edited_template_reshapes_the_expectation(self) -> None:
        # The core property: a user template edit changes what passes, with no script change.
        edited = TEMPLATE.replace(
            "## Table of contents",
            "## Table of contents\n\n## Deployment notes",
        ).replace(
            "### Technical table\n\n| Component type | Name | Purpose (one sentence) | Manual steps reference |\n|---|---|---|---|\n\nNo published technical documentation — [Missing Wiki Link]\n\n### Tests",
            "### Tests\n\n### Technical table",
        )
        new_shape_draft = build_draft(edited, items=1)
        self.assertEqual("pass", self.validate(edited, new_shape_draft)["status"])
        old_shape_draft = build_draft(TEMPLATE, items=1)
        self.assertEqual("fail", self.validate(edited, old_shape_draft)["status"])

    def test_marker_less_template_validates_flat_with_warning(self) -> None:
        flat_template = TEMPLATE.replace("<!-- repeat-per-item -->\n", "")
        result = self.validate(flat_template, build_draft(flat_template, items=0))
        self.assertEqual("pass", result["status"], result["errors"])
        self.assertTrue(any("repeat-per-item" in warning for warning in result["warnings"]))

    def test_heading_inside_code_fence_is_not_structure(self) -> None:
        draft = build_draft(TEMPLATE, items=1) + "\n```\n## Not A Section\n```\n"
        self.assertEqual("pass", self.validate(TEMPLATE, draft)["status"])

    def test_crlf_draft_passes(self) -> None:
        draft = build_draft(TEMPLATE, items=1).replace("\n", "\r\n")
        self.assertEqual("pass", self.validate(TEMPLATE, draft)["status"])


class MainTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = render_check.main(argv)
        return code, json.loads(stdout.getvalue())

    def test_exit_codes_and_json_shape(self) -> None:
        with TemporaryDirectory() as name:
            template_path = Path(name) / "template.md"
            template_path.write_text(TEMPLATE, encoding="utf-8")
            good = Path(name) / "good.md"
            good.write_text(build_draft(TEMPLATE, items=1), encoding="utf-8")
            bad = Path(name) / "bad.md"
            bad.write_text("# Wrong Title\n\n## Rogue\n", encoding="utf-8")

            code, result = self.run_main([str(good), "--template", str(template_path)])
            self.assertEqual(0, code)
            self.assertEqual("pass", result["status"])
            self.assertEqual(1, result["items"])
            self.assertEqual(
                ["draft", "errors", "items", "status", "template", "warnings"],
                sorted(result),
            )

            code, result = self.run_main([str(bad), "--template", str(template_path)])
            self.assertEqual(1, code)
            self.assertEqual("fail", result["status"])

            code, result = self.run_main(
                [str(Path(name) / "absent.md"), "--template", str(template_path)]
            )
            self.assertEqual(2, code)
            self.assertEqual("error", result["status"])


if __name__ == "__main__":
    unittest.main()
