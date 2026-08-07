from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.schema_format import FORMAT_CHECKER

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE_SCHEMAS = (
    "output-envelope.schema.json",
    "change-record.schema.json",
    "handoff-envelope.schema.json",
)


class SchemaFormatTests(unittest.TestCase):
    """Guard against regressing to a bare FormatChecker(), which silently skips date-time/uri."""

    def test_date_time_format_is_enforced(self) -> None:
        self.assertIn("date-time", FORMAT_CHECKER.checkers)
        validator = Draft202012Validator(
            {"type": "string", "format": "date-time"}, format_checker=FORMAT_CHECKER
        )
        self.assertTrue(list(validator.iter_errors("not-a-timestamp")))
        self.assertFalse(list(validator.iter_errors("2026-07-13T09:00:00Z")))
        self.assertFalse(list(validator.iter_errors("2026-07-13T09:00:00+00:00")))

    def test_uri_format_is_enforced(self) -> None:
        self.assertIn("uri", FORMAT_CHECKER.checkers)
        validator = Draft202012Validator(
            {"type": "string", "format": "uri"}, format_checker=FORMAT_CHECKER
        )
        self.assertTrue(list(validator.iter_errors("not a uri")))
        self.assertFalse(list(validator.iter_errors("https://example.sandbox.my.salesforce.com")))

    def test_non_string_values_are_left_to_type_validation(self) -> None:
        # Format checks must not fire on non-strings (mirrors jsonschema's built-in behavior).
        validator = Draft202012Validator(
            {"format": "date-time"}, format_checker=FORMAT_CHECKER
        )
        self.assertFalse(list(validator.iter_errors(12345)))


class FeatureEntryCitationBoundaryTests(unittest.TestCase):
    """Owner decision D5/D7: a Feature Entry is never citable, and §13 says so.

    Both halves were shipped un-asserted once already — the lookahead existed in no envelope
    schema (Feature identities were blocked only incidentally, by the three-segment entryId
    shape) and the contract section every refusal cites was never written."""

    def entry_id_schema(self, name: str) -> dict:
        schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        return schema["$defs"]["entryRef"]["properties"]["entryId"]

    def test_feature_identities_are_rejected_by_an_explicit_lookahead(self) -> None:
        for name in ENVELOPE_SCHEMAS:
            with self.subTest(schema=name):
                subschema = self.entry_id_schema(name)
                # The literal is asserted, not just the outcome: widening the segment shape
                # later must not silently restore Feature identities as citable.
                self.assertIn("(?!Feature:)", subschema["pattern"])
                validator = Draft202012Validator(subschema)
                self.assertTrue(list(validator.iter_errors("Feature:scheduling")))
                self.assertTrue(list(validator.iter_errors("Feature:scheduling:anything")))
                self.assertFalse(list(validator.iter_errors("ApexClass:c:AssignmentService")))

    def test_entry_id_description_points_at_the_governing_section(self) -> None:
        for name in ENVELOPE_SCHEMAS:
            with self.subTest(schema=name):
                self.assertIn("§13", self.entry_id_schema(name)["description"])

    def test_feature_schema_cites_the_governing_section(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/knowledge-feature.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("§13", schema["description"])

    def test_feature_ref_is_claim_scoped_in_every_envelope(self) -> None:
        for name in ENVELOPE_SCHEMAS:
            with self.subTest(schema=name):
                schema = json.loads((ROOT / f"schemas/{name}").read_text(encoding="utf-8"))
                defs = schema.get("$defs") or schema.get("definitions")
                ref = defs["featureRef"]
                self.assertEqual(1, ref["properties"]["claimIds"]["minItems"])
                validator = Draft202012Validator(ref)
                self.assertTrue(list(validator.iter_errors({
                    "featureId": "Feature:invoice-finance",
                    "reviewedContentDigest": "sha256:" + "a" * 64,
                    "modelDigest": "sha256:" + "b" * 64,
                    "claimIds": [],
                })))

    def test_every_shipped_reference_to_contract_section_13_resolves(self) -> None:
        contract = (ROOT / "docs/knowledge-one-file-contract.md").read_text(encoding="utf-8")
        headings = set(re.findall(r"^## (\d+[a-z]?)\.", contract, flags=re.MULTILINE))
        # §12 is held for parity certification (D7) so the number cannot be reused silently.
        self.assertIn("12", headings)
        self.assertIn("13", headings)
        self.assertIn("Feature Knowledge", contract)
        # The section is load-bearing because shipped refusals send a reader to it; if nothing
        # cites it any more, this assertion is the place to notice.
        citing = [
            path
            for path in (
                *ROOT.glob("scripts/*.py"),
                *ROOT.glob("schemas/*.json"),
                *ROOT.glob(".github/prompts/*.md"),
            )
            if "§13" in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(citing)


if __name__ == "__main__":
    unittest.main()
