#!/usr/bin/env python3
"""Validate a rendered release-handover draft against the handover template.

The template (`.ai/templates/release-handover.md`) is the single, human-editable source of
the document structure. This checker re-derives the expected shape from the template at every
run — headings outside HTML comments and code fences, with `<placeholder>` spans matching any
text — so template edits are enforced automatically without touching this script. The line
`<!-- repeat-per-item -->` splits the template into the one-time prelude and the per-item
block that may repeat any number of times; without the marker the whole template is validated
as one flat sequence (reported as a warning).

Only structure is validated: heading sequence, levels, and per-item repetition. Body prose,
tables, bullets, and the conditional fallback texts are deliberately out of scope.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ".ai/templates/release-handover.md"
REPEAT_MARKER = "<!-- repeat-per-item -->"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
PLACEHOLDER_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class HeadingPattern:
    level: int
    label: str
    regex: re.Pattern

    @property
    def display(self) -> str:
        return f"{'#' * self.level} {self.label}"

    def matches(self, level: int, text: str) -> bool:
        return level == self.level and self.regex.fullmatch(text) is not None


@dataclass
class TemplateShape:
    prelude: list[HeadingPattern] = field(default_factory=list)
    item_block: list[HeadingPattern] = field(default_factory=list)
    has_marker: bool = False
    marker_count: int = 0


def _strip_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    visible: list[str] = []
    index = 0
    while index < len(line):
        if in_comment:
            end = line.find("-->", index)
            if end < 0:
                index = len(line)
            else:
                in_comment = False
                index = end + 3
        else:
            start = line.find("<!--", index)
            if start < 0:
                visible.append(line[index:])
                break
            visible.append(line[index:start])
            in_comment = True
            index = start + 4
    return "".join(visible), in_comment


def _visible_lines(text: str) -> list[tuple[int, str, bool]]:
    """Per line: (1-based number, comment-stripped text, is-repeat-marker).

    Lines inside code fences are dropped entirely so heading-shaped code never counts as
    structure; the marker is recognised before stripping because it is itself a comment.
    """
    result: list[tuple[int, str, bool]] = []
    in_comment = False
    in_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if in_fence:
            if stripped.startswith("```"):
                in_fence = False
            continue
        is_marker = not in_comment and stripped == REPEAT_MARKER
        visible, in_comment = _strip_comments(raw, in_comment)
        visible = visible.strip()
        if visible.startswith("```"):
            in_fence = True
            continue
        result.append((number, visible, is_marker))
    return result


def _heading_regex(text: str) -> re.Pattern:
    parts = PLACEHOLDER_RE.split(text)
    return re.compile(".+".join(re.escape(part) for part in parts))


def _headings(lines: list[tuple[int, str, bool]]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for number, visible, _ in lines:
        match = HEADING_RE.match(visible)
        if match:
            found.append((number, len(match.group(1)), match.group(2).strip()))
    return found


def parse_template(text: str) -> TemplateShape:
    shape = TemplateShape()
    seen_marker = False
    first_heading_skipped = False
    for number, visible, is_marker in _visible_lines(text):
        if is_marker:
            shape.marker_count += 1
            seen_marker = True
            continue
        match = HEADING_RE.match(visible)
        if not match:
            continue
        level, heading_text = len(match.group(1)), match.group(2).strip()
        if not first_heading_skipped:
            first_heading_skipped = True
            if level == 1 and heading_text.startswith("Template: "):
                continue
        pattern = HeadingPattern(level, heading_text, _heading_regex(heading_text))
        if seen_marker:
            shape.item_block.append(pattern)
        else:
            shape.prelude.append(pattern)
    shape.has_marker = shape.marker_count > 0
    return shape


def template_fixed_texts(text: str) -> list[str]:
    """The template's fixed (non-placeholder, non-structural) lines — its fallback texts."""
    texts: list[str] = []
    for _, visible, _ in _visible_lines(text):
        if not visible or visible.startswith(("#", "- ", "|")):
            continue
        if set(visible) <= {"-"} or PLACEHOLDER_RE.search(visible):
            continue
        if visible not in texts:
            texts.append(visible)
    return texts


def validate_draft(shape: TemplateShape, text: str) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    headings = _headings(_visible_lines(text))
    if shape.marker_count > 1:
        warnings.append("template defines multiple repeat-per-item markers; the first one is used")

    draft_index = 0
    for position, expected in enumerate(shape.prelude):
        if draft_index >= len(headings):
            errors.append(f"missing required section: {expected.display}")
            continue
        number, level, heading_text = headings[draft_index]
        if expected.matches(level, heading_text):
            draft_index += 1
            continue
        if any(later.matches(level, heading_text) for later in shape.prelude[position + 1 :]):
            errors.append(f"missing required section: {expected.display}")
            continue
        if position == 0 and expected.level == 1:
            errors.append(
                f"line {number}: draft title does not match the template document title "
                f"({expected.display})"
            )
        else:
            errors.append(
                f"line {number}: section not defined by the template at this position: "
                f"{'#' * level} {heading_text}"
            )
        draft_index += 1

    remaining = headings[draft_index:]
    items = 0
    if shape.has_marker and shape.item_block:
        opener = shape.item_block[0]
        index = 0
        while index < len(remaining):
            number, level, heading_text = remaining[index]
            if not opener.matches(level, heading_text):
                errors.append(
                    f"line {number}: section not defined by the template at this position: "
                    f"{'#' * level} {heading_text}"
                )
                index += 1
                continue
            items += 1
            index += 1
            section_index = 1
            while section_index < len(shape.item_block):
                section = shape.item_block[section_index]
                if index >= len(remaining):
                    errors.append(f"item at line {number}: missing required section {section.display}")
                    section_index += 1
                    continue
                inner_number, inner_level, inner_text = remaining[index]
                if section.matches(inner_level, inner_text):
                    index += 1
                    section_index += 1
                    continue
                if opener.matches(inner_level, inner_text):
                    errors.append(f"item at line {number}: missing required section {section.display}")
                    section_index += 1
                    continue
                if any(
                    later.matches(inner_level, inner_text)
                    for later in shape.item_block[section_index + 1 :]
                ):
                    errors.append(
                        f"item at line {number}: section {section.display} missing or out of "
                        f"order (line {inner_number})"
                    )
                    section_index += 1
                    continue
                errors.append(
                    f"line {inner_number}: section not defined by the template at this "
                    f"position: {'#' * inner_level} {inner_text}"
                )
                index += 1
        if items == 0 and not errors:
            warnings.append("zero item blocks: empty-release draft")
    else:
        if not shape.has_marker:
            warnings.append(
                "template defines no <!-- repeat-per-item --> marker; flat structure "
                "validation performed"
            )
        for number, level, heading_text in remaining:
            errors.append(
                f"line {number}: section not defined by the template at this position: "
                f"{'#' * level} {heading_text}"
            )

    return {
        "errors": errors,
        "items": items,
        "status": "fail" if errors else "pass",
        "warnings": warnings,
    }


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _report_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a rendered release-handover draft against the handover template."
    )
    parser.add_argument("draft", help="rendered handover draft (markdown) to validate")
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help="template to derive the expected structure from (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    draft_path = _resolve(args.draft)
    template_path = _resolve(args.template)
    result: dict = {"draft": _report_path(draft_path), "template": _report_path(template_path)}
    try:
        template_text = template_path.read_text(encoding="utf-8")
        draft_text = draft_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.update({"errors": [str(exc)], "items": 0, "status": "error", "warnings": []})
        print(json.dumps(result, sort_keys=True))
        return 2

    result.update(validate_draft(parse_template(template_text), draft_text))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
