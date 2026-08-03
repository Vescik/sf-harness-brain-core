from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_harness import reserved_fixture_leaks


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals/fixtures"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class KnowledgeSchemaTests(unittest.TestCase):
    def validator(self, name: str) -> Draft202012Validator:
        schema = load_json(ROOT / "schemas" / name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def assert_valid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertEqual([], errors, [error.message for error in errors])

    def assert_invalid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertTrue(errors, f"{fixture} was incorrectly accepted")

    def test_rule_registry_matches_generic_runtime_rule_ids(self) -> None:
        registry = load_yaml(ROOT / ".github/instructions/rule-registry.yaml")
        errors = list(
            self.validator("principle-registry.schema.json").iter_errors(registry)
        )
        self.assertEqual([], errors, [error.message for error in errors])
        source_files = (
            ROOT / ".github/copilot-instructions.md",
            ROOT / ".github/instructions/managed-package-constraints.instructions.md",
            ROOT / ".github/instructions/organization-principles.instructions.md",
            ROOT / ".github/instructions/salesforce-best-practices.instructions.md",
        )
        source_ids: set[str] = set()
        pattern = re.compile(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—")
        for path in source_files:
            source_ids.update(pattern.findall(path.read_text(encoding="utf-8")))
        actual = [rule["ruleId"] for rule in registry["rules"]]
        self.assertEqual(source_ids, set(actual))
        self.assertEqual(len(actual), len(set(actual)))

    def test_live_knowledge_has_no_reserved_fixture_leak(self) -> None:
        """Reserved synthetic fixture identifiers must never reach live Knowledge
        surfaces. Legal Salesforce names (including ones that collide with old
        example names, e.g. Invoice__c) are governed by provenance and lifecycle
        rules, not by a name denylist."""
        surfaces: list[Path] = []
        knowledge_root = ROOT / ".ai/knowledge"
        surfaces.extend(sorted(knowledge_root.glob("*.md")))
        artifacts_root = knowledge_root / "artifacts"
        if artifacts_root.exists():
            surfaces.extend(sorted(artifacts_root.rglob("*.md")))
        features_root = knowledge_root / "features"
        if features_root.exists():
            surfaces.extend(sorted(features_root.glob("*.md")))
        for name in ("artifacts-ledger.jsonl", "features-ledger.jsonl"):
            ledger = knowledge_root / name
            if ledger.exists():
                surfaces.append(ledger)
        self.assertTrue(surfaces, "no live Knowledge surfaces found to scan")
        for surface in surfaces:
            leaks = reserved_fixture_leaks(surface.read_text(encoding="utf-8"))
            self.assertEqual([], leaks, f"{surface}: reserved fixture tokens leaked: {leaks}")

    def test_legal_business_names_are_not_screened_as_fixture_leaks(self) -> None:
        """Regression for the retired name denylist (introduced in 07c1788): a real
        team's legally named metadata and rule prefixes must pass the
        runtime-authority leak scan."""
        legal_text = "Flow writes Invoice__c.Status__c under rule MP-INV-001."
        self.assertEqual([], reserved_fixture_leaks(legal_text))
        self.assertEqual(
            ["HarnessEngagement"],
            reserved_fixture_leaks("references HarnessEngagement__c"),
        )

class RecordFreeKnowledgeLaneTests(unittest.TestCase):
    """FIND-34: documenting existing state must never be gated on a work record.

    A work record is unconstructable without a real ADO work item
    (``change-record.schema.json`` pins ``recordId`` to ``^ADO-<project>-<n>$`` and requires
    ``workItem.system == "azure-devops"`` with an integer ``id``), while the Knowledge layer
    carries no record reference at all — ``knowledge_store.py entry-draft`` takes no record
    argument and no entry schema defines the field. The dependency runs
    record -> knowledge (optional ``entryRefs``), never the other way.

    So an agent-facing sentence that demands a work record unconditionally cannot be satisfied by
    the honest caller; the only way out is to fabricate an ADO number. These surfaces may require
    a record for governed delivery work, but the requirement must always be qualified.
    """

    SURFACES = (
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/agents/config-investigator.agent.md",
        ".github/skills/investigate-object/SKILL.md",
        ".github/skills/investigate-config-records/SKILL.md",
        # Named directly (not only via the prompt-hint scan below, which silently drops a
        # skill if its prompt's [recordId= hint is removed): the record-free entry lane
        # that carries the org-sampling step (org-usage layer, 2026-08-03).
        ".github/skills/selected-files-knowledge/SKILL.md",
    )
    RECORD = re.compile(r"work[- ]record|`recordid`", re.I)
    DEMAND = re.compile(
        r"\b(require|append|validate|establish|return|attach|bind|resume|load)\w*", re.I
    )
    QUALIFIER = re.compile(r"\b(when|if|optional|governed|provided|record-free)\b", re.I)

    # Verbatim pre-fix wording. Kept so the guard above can never go inert: if a rewrite of the
    # regexes stops flagging these, the guard has stopped guarding.
    HISTORICAL_UNCONDITIONAL_DEMANDS = (
        "Require the calling `recordId`, claim question, claim type, scope, and evidence policy.",
        "Load the persisted work record before acting, and load detailed Principles, contracts, "
        "Knowledge, and skills only through the active role.",
        "Establish the custom role, requested outcome, persisted work record, environment, "
        "and scope.",
        "Require `recordId`, exact claim question/type, normalized package/component subject, "
        "environment, criticality, minimum evidence policy, and why current Knowledge/repository "
        "evidence is insufficient.",
        "Validate the work record and read relevant verified Knowledge plus metadata-repository "
        "state.",
        "Append evidence references to the work record. Human review is a separate operation.",
        "Append claim/evidence/review references to the relevant work record and retain audit "
        "history.",
    )

    @classmethod
    def unqualified_demands(cls, text: str) -> list[str]:
        """Sentences that both demand something and name a work record, with no qualifier."""
        collapsed = " ".join(text.split())
        return [
            sentence
            for sentence in re.split(r"(?<=[.;])\s+", collapsed)
            if cls.RECORD.search(sentence)
            and cls.DEMAND.search(sentence)
            and not cls.QUALIFIER.search(sentence)
        ]

    def test_knowledge_surfaces_never_demand_a_work_record_unconditionally(self) -> None:
        for relative_path in self.SURFACES:
            with self.subTest(surface=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertEqual(
                    [],
                    self.unqualified_demands(text),
                    f"{relative_path} demands a work record without qualifying the lane; "
                    "documenting existing state is record-free (FIND-34)",
                )

    def test_the_guard_still_flags_the_wording_it_was_written_against(self) -> None:
        for demand in self.HISTORICAL_UNCONDITIONAL_DEMANDS:
            with self.subTest(demand=demand[:60]):
                self.assertNotEqual([], self.unqualified_demands(demand))

    def test_a_skill_never_requires_what_its_own_prompt_marks_optional(self) -> None:
        """`investigate-object` shipped a prompt saying `[recordId=<ID>]` … "otherwise the
        investigation is a standalone read" beside a skill saying "Require `recordId`". A skill
        must not contradict the optionality its own prompt advertises."""
        for prompt_path in sorted((ROOT / ".github/prompts").glob("*.prompt.md")):
            prompt_text = prompt_path.read_text(encoding="utf-8")
            hint = re.search(r"^argument-hint:\s*\"(.*)\"", prompt_text, re.M)
            if not hint or "[recordId=" not in hint.group(1):
                continue
            for skill_name in re.findall(r"\.\./skills/([a-z0-9-]+)/SKILL\.md", prompt_text):
                skill_path = ROOT / ".github/skills" / skill_name / "SKILL.md"
                with self.subTest(prompt=prompt_path.name, skill=skill_name):
                    self.assertEqual(
                        [],
                        self.unqualified_demands(skill_path.read_text(encoding="utf-8")),
                        f"{skill_path.name} requires a work record that "
                        f"{prompt_path.name} marks optional",
                    )


if __name__ == "__main__":
    unittest.main()
