from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals" / "fixtures"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class OutputEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(ROOT / "schemas" / "output-envelope.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )
        cls.grounded = load_json(
            FIXTURES / "output.grounded-success.valid.json"
        )

    def assert_valid(self, instance: dict) -> None:
        errors = sorted(
            self.validator.iter_errors(instance),
            key=lambda item: list(item.absolute_path),
        )
        self.assertFalse(errors, errors[0].message if errors else "")

    def assert_invalid(self, instance: dict) -> None:
        self.assertTrue(list(self.validator.iter_errors(instance)))

    def test_valid_fixtures_cover_success_accepted_and_promoted(self) -> None:
        for name in (
            "output.incomplete.json",
            "output.grounded-success.valid.json",
            "output.grounded-accepted.valid.json",
            "output.grounded-promoted.valid.json",
        ):
            with self.subTest(name=name):
                self.assert_valid(load_json(FIXTURES / name))

    def test_invalid_fixtures_are_rejected(self) -> None:
        for name in (
            "output.grounded-success.invalid-null-record.json",
            "output.grounded-success.invalid-empty-grounding.json",
            "output.grounded-accepted.invalid-no-handoff.json",
        ):
            with self.subTest(name=name):
                self.assert_invalid(load_json(FIXTURES / name))

    def test_grounded_success_requires_all_four_hashes(self) -> None:
        for field in ("recordHash", "scopeHash", "designHash", "groundingHash"):
            instance = copy.deepcopy(self.grounded)
            del instance["recordRef"][field]
            with self.subTest(field=field):
                self.assert_invalid(instance)

    def test_grounded_success_requires_every_grounding_reference_class(self) -> None:
        for field in (
            "sourceRefs",
            "ruleRefs",
            "claimRefs",
            "evidenceRefs",
            "verification",
        ):
            instance = copy.deepcopy(self.grounded)
            instance[field] = []
            with self.subTest(field=field):
                self.assert_invalid(instance)

    def test_grounded_success_requires_knowledge_timestamp(self) -> None:
        instance = copy.deepcopy(self.grounded)
        instance["knowledgeSnapshotAt"] = None
        self.assert_invalid(instance)

    def test_grounded_success_requires_a_persisted_handoff(self) -> None:
        instance = copy.deepcopy(self.grounded)
        instance["recordRef"]["consumedHandoffId"] = None
        instance["recordRef"]["createdHandoffId"] = None
        self.assert_invalid(instance)

    def test_cache_read_cannot_claim_accepted_or_promoted(self) -> None:
        for review_status in ("accepted", "promoted"):
            instance = load_json(FIXTURES / "output.incomplete.json")
            instance["status"] = "success"
            instance["completeness"] = {"status": "complete", "missingEvidence": []}
            instance["reviewStatus"] = review_status
            with self.subTest(reviewStatus=review_status):
                self.assert_invalid(instance)


if __name__ == "__main__":
    unittest.main()
