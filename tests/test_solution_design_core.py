from __future__ import annotations

import copy
import importlib.util
import json
import unicodedata
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "solution_design_core", ROOT / "scripts" / "solution_design_core.py"
)
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


DEFINITIONS = core.canonical_rule_definitions()
RULE_MAP = core.load_rule_map()
CAPABILITIES = core.load_capabilities()

DESIGN_TEXT = """# Solution Design — routing category

## 7. Chosen approach

### D-001 — add the routing category field

The field carries the classification chosen during Case intake.

#### option-b

Rejected: a formula field cannot be set by the intake automation.
"""


def verdict(rule_id: str, value: str = "honored", **extra: object) -> dict:
    entry = RULE_MAP["rules"].get(rule_id) or RULE_MAP["manualApplicability"][rule_id]
    payload = {
        "ruleId": rule_id,
        "tier": entry["tier"],
        "severity": entry["severity"],
        "verdict": value,
        "definitionDigest": DEFINITIONS[rule_id],
    }
    payload.update(extra)
    return payload


READY_RULES = [
    "MP-OWN-001",
    "ORG-DEC-001",
    "ORG-NAME-001",
    "SF-NAME-001",
    "SF-TEST-001",
    "SF-META-001",
    "MP-ABS-001",
    "SF-EVID-003",
]


def ready_state() -> dict:
    return {
        "schemaVersion": 1,
        "caseId": "SD-2026-08-05-routing-category",
        "status": "draft",
        "stateSequence": 4,
        "writerAssignment": {
            "writerId": "writer-one",
            "assignedAt": "2026-08-05T09:00:00Z",
            "assignmentSequence": 1,
            "transferReceiptRef": None,
        },
        "nextFocus": "none",
        "requirementSnapshot": {
            "sourceType": "human-request",
            "itemId": None,
            "itemType": "Requirement",
            "revision": None,
            "retrievedAt": "2026-08-05T09:00:00Z",
            "sourceDigest": "sha256:" + "a" * 64,
            "includedItems": [],
            "excludedItems": [],
            "acceptanceCriteria": [
                {
                    "acId": "AC-LOCAL-01",
                    "sourceItemId": None,
                    "sourceLocalKey": "local-1",
                    "lineageKey": "human:local-1",
                    "sourceRevision": None,
                    "summary": "Case intake stores the routing category.",
                    "textDigest": "sha256:" + "b" * 64,
                    "inScope": True,
                }
            ],
            "completeness": "complete",
            "attestationRef": "EV-ATT-001",
            "unresolvedContradictions": [],
        },
        "scope": {
            "frontierComplete": True,
            "components": [
                {
                    "componentId": "CMP-001",
                    "objectApiName": "Case",
                    "artefactType": "CustomField",
                    "apiName": "Case.Routing_Category__c",
                    "action": "create",
                    "disposition": "in-scope",
                    "dispositionReason": None,
                    "description": "Stores the routing category selected during Case classification.",
                    "componentOwnership": "subscriber-owned",
                    "hostObjectOwnership": "subscriber-owned",
                    "packageBoundaryRefs": [],
                    "extensionPointStatus": "not-applicable",
                    "sourceState": "absent",
                    "targetState": "proposed",
                    "evidenceRefs": ["EV-001"],
                    "decisionRefs": ["D-001"],
                    "acIds": ["AC-LOCAL-01"],
                }
            ],
        },
        "configurationArtefacts": [],
        "dataClassifications": [],
        "questions": [
            {
                "questionId": "Q-001",
                "question": "Does the Case object already carry a routing classification field?",
                "materiality": "blocking",
                "requiredAuthority": ["repository-receipt"],
                "status": "closed",
                "answer": "No such field is declared in the tracked source at the bound commit.",
                "closureAuthority": "repository-receipt",
                "evidenceRefs": ["EV-001"],
                "limitations": [],
                "route": "grounding",
            }
        ],
        "concernCoverage": [
            {
                "concernId": "COV-DATA-MODEL",
                "profileId": "data-model-and-configuration-integrity",
                "applicability": "applicable",
                "status": "addressed",
                "triggerRefs": ["CMP-001"],
                "treatmentRefs": ["#D-001"],
                "questionRefs": ["Q-001"],
                "riskRefs": [],
                "verificationRefs": ["V-001"],
                "notApplicableReason": None,
            },
            {
                "concernId": "COV-VERIFICATION",
                "profileId": "verification-feasibility",
                "applicability": "applicable",
                "status": "addressed",
                "triggerRefs": ["AC-LOCAL-01"],
                "treatmentRefs": ["V-001"],
                "questionRefs": [],
                "riskRefs": [],
                "verificationRefs": ["V-001"],
                "notApplicableReason": None,
            },
        ],
        "probes": [],
        "decisions": [
            {
                "decisionId": "D-001",
                "designAnchor": "#D-001",
                "summary": "Add a subscriber-owned picklist field on Case.",
                "rationaleSummary": "Keeps the classification queryable without touching package metadata.",
                "alternativeRefs": ["#option-b"],
                "trivialityReason": None,
                "status": "proposed",
                "materiality": "material",
                "acIds": ["AC-LOCAL-01"],
                "componentIds": ["CMP-001"],
                "questionIds": ["Q-001"],
                "evidenceRefs": ["EV-001"],
                "riskRefs": [],
                "verificationRefs": ["V-001"],
            }
        ],
        "riskObligations": [],
        "verificationContract": [
            {
                "verificationId": "V-001",
                "acIds": ["AC-LOCAL-01"],
                "decisionRefs": ["D-001"],
                "assertion": "A Case saved through intake carries the selected routing category.",
                "method": "apex-test",
                "stage": "pre-review",
                "executorRole": "development-assistant",
                "passCriteria": "Positive, negative and bulk cases all store the expected value.",
                "expectedEvidenceType": "verification-execution",
                "recheckProbeRefs": [],
            }
        ],
        "applicableRules": [verdict(rule_id) for rule_id in READY_RULES],
        "limitationRefs": [],
        "evidenceRefs": [
            {
                "receiptId": "EV-001",
                "path": "evidence/EV-001.json",
                "sha256": "sha256:" + "c" * 64,
                "sourceType": "repository-receipt",
                "assurance": "source-exact",
                "validationPurpose": "design-evidence",
                "environmentFitness": "not-environment-bound",
                "observedAt": "2026-08-05T09:10:00Z",
                "expiresAt": None,
                "completeness": "complete",
                "status": "current",
                "questionRefs": ["Q-001"],
                "probeRefs": [],
            }
        ],
        "knowledgeCandidates": [],
        "activeCandidateRef": None,
    }


def evaluate(state: dict, design_text: str | None = DESIGN_TEXT) -> dict:
    return core.evaluate(
        state,
        design_text=design_text,
        capabilities=CAPABILITIES,
        rule_map=RULE_MAP,
        definitions=DEFINITIONS,
    )


def gate_ids(report: dict) -> set[str]:
    return {gap["gateId"] for gap in report["gaps"]}


class CanonicalizerTests(unittest.TestCase):
    def test_nfc_normalizes_composed_and_decomposed_forms(self) -> None:
        composed = unicodedata.normalize("NFC", "\u00e9")
        decomposed = unicodedata.normalize("NFD", "\u00e9")
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(
            core.canonical_bytes({composed: composed}),
            core.canonical_bytes({decomposed: decomposed}),
        )

    def test_keys_colliding_after_nfc_are_rejected(self) -> None:
        composed = unicodedata.normalize("NFC", "\u00e9")
        decomposed = unicodedata.normalize("NFD", "\u00e9")
        self.assertNotEqual(composed, decomposed)
        with self.assertRaises(core.SolutionDesignError):
            core.canonical_bytes({composed: 1, decomposed: 2})

    def test_binary_floats_are_forbidden(self) -> None:
        with self.assertRaises(core.SolutionDesignError):
            core.canonical_bytes({"value": 1.5})

    def test_integers_outside_int64_are_rejected(self) -> None:
        with self.assertRaises(core.SolutionDesignError):
            core.canonical_bytes({"value": 2**63})
        self.assertIn(b"9223372036854775807", core.canonical_bytes({"value": 2**63 - 1}))

    def test_keys_sort_by_code_point_and_slash_is_not_escaped(self) -> None:
        payload = core.canonical_bytes({"b": "a/b", "a": 1, "\U0001f600": 2})
        self.assertEqual(payload, '{"a":1,"b":"a/b","\U0001f600":2}'.encode("utf-8"))

    def test_no_trailing_newline_and_utf8_without_bom(self) -> None:
        payload = core.canonical_bytes({"a": "ą"})
        self.assertFalse(payload.endswith(b"\n"))
        self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))

    def test_document_digest_is_identical_across_line_endings_and_bom(self) -> None:
        lf = "# Title\nbody\n"
        crlf = "# Title\r\nbody\r\n"
        bom = "﻿# Title\nbody\n"
        self.assertEqual(core.text_digest(lf), core.text_digest(crlf))
        self.assertEqual(core.text_digest(lf), core.text_digest(bom))

    def test_case_version_tracks_state_sequence_state_and_document(self) -> None:
        state = ready_state()
        base = core.case_version(1, state, core.text_digest(DESIGN_TEXT))
        self.assertTrue(base.startswith("cv1_"))
        self.assertNotEqual(base, core.case_version(2, state, core.text_digest(DESIGN_TEXT)))
        self.assertNotEqual(
            base, core.case_version(1, state, core.text_digest(DESIGN_TEXT + "\nmore\n"))
        )
        mutated = copy.deepcopy(state)
        mutated["decisions"][0]["summary"] = "changed"
        self.assertNotEqual(base, core.case_version(1, mutated, core.text_digest(DESIGN_TEXT)))

    def test_case_version_and_candidate_digest_are_distinct_tokens(self) -> None:
        state = ready_state()
        version = core.case_version(1, state, core.text_digest(DESIGN_TEXT))
        digest = core.candidate_digest({"caseId": state["caseId"]})
        self.assertNotEqual(version, digest)
        self.assertTrue(digest.startswith("sha256:"))


class RuleRegistryTests(unittest.TestCase):
    def test_every_canonical_hard_rule_has_registry_semantics(self) -> None:
        self.assertEqual(core.validate_rule_registry(RULE_MAP, DEFINITIONS), [])

    def test_unmapped_hard_rule_fails_registry_validation(self) -> None:
        trimmed = copy.deepcopy(RULE_MAP)
        trimmed["manualApplicability"].pop("SAFE-ROLE-001")
        problems = core.validate_rule_registry(trimmed, DEFINITIONS)
        self.assertTrue(any("SAFE-ROLE-001" in problem for problem in problems))

    def test_registry_rejects_unknown_rule_id(self) -> None:
        extended = copy.deepcopy(RULE_MAP)
        extended["manualApplicability"]["MP-NOPE-999"] = {
            "tier": "tier-1",
            "severity": "blocking",
            "blockingSemantics": "never-blocks-submit",
            "reason": "invented",
        }
        problems = core.validate_rule_registry(extended, DEFINITIONS)
        self.assertTrue(any("MP-NOPE-999" in problem for problem in problems))

    def test_hard_rule_severity_cannot_be_lowered(self) -> None:
        lowered = copy.deepcopy(RULE_MAP)
        lowered["rules"]["MP-OWN-001"]["severity"] = "advisory"
        problems = core.validate_rule_registry(lowered, DEFINITIONS)
        self.assertTrue(any("cannot be advisory" in problem for problem in problems))

    def test_a_rule_may_not_be_both_selector_driven_and_manual(self) -> None:
        path = ROOT / "config" / "solution-design-rule-map.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(raw["rules"]) & set(raw["manualApplicability"]), set())


class ReadyFixtureTests(unittest.TestCase):
    def test_complete_case_reaches_ready(self) -> None:
        report = evaluate(ready_state())
        self.assertEqual(report["result"], "READY", report["gaps"])
        self.assertEqual(report["nextFocus"], "none")

    def test_identical_input_produces_identical_report(self) -> None:
        first = evaluate(ready_state())
        second = evaluate(ready_state())
        self.assertEqual(core.sd_digest(first), core.sd_digest(second))

    def test_malformed_state_is_reported_not_crashed(self) -> None:
        state = ready_state()
        state["status"] = "not-a-state"
        report = evaluate(state)
        self.assertEqual(report["result"], "MALFORMED")


class ConcernCoverageTests(unittest.TestCase):
    def test_omitted_material_concern_blocks_even_with_every_question_closed(self) -> None:
        state = ready_state()
        state["concernCoverage"] = [
            item
            for item in state["concernCoverage"]
            if item["profileId"] != "data-model-and-configuration-integrity"
        ]
        report = evaluate(state)
        self.assertEqual(report["result"], "OPEN")
        self.assertTrue(
            any(
                gap["entity"] == "data-model-and-configuration-integrity"
                and gap["requiredClosure"] == "concern-treatment"
                for gap in report["gaps"]
            )
        )

    def test_applicable_concern_cannot_be_declared_not_applicable(self) -> None:
        state = ready_state()
        state["concernCoverage"][0]["applicability"] = "not-applicable"
        state["concernCoverage"][0]["notApplicableReason"] = "considered"
        report = evaluate(state)
        self.assertIn("SD-G3", gate_ids(report))

    def test_empty_treatment_cannot_close_a_concern(self) -> None:
        state = ready_state()
        state["concernCoverage"][0]["treatmentRefs"] = []
        state["concernCoverage"][0]["questionRefs"] = []
        state["concernCoverage"][0]["riskRefs"] = []
        report = evaluate(state)
        self.assertTrue(any("empty treatment" in gap["detail"] for gap in report["gaps"]))

    def test_not_applicable_concern_needs_a_rationale(self) -> None:
        state = ready_state()
        state["concernCoverage"].append(
            {
                "concernId": "COV-UI",
                "profileId": "user-journey-and-accessibility",
                "applicability": "not-applicable",
                "status": "addressed",
                "triggerRefs": [],
                "treatmentRefs": [],
                "questionRefs": [],
                "riskRefs": [],
                "verificationRefs": [],
                "notApplicableReason": None,
            }
        )
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "concern-na-rationale" for gap in report["gaps"])
        )

    def test_trigger_valid_not_applicable_concern_passes(self) -> None:
        state = ready_state()
        state["concernCoverage"].append(
            {
                "concernId": "COV-UI",
                "profileId": "user-journey-and-accessibility",
                "applicability": "not-applicable",
                "status": "addressed",
                "triggerRefs": [],
                "treatmentRefs": [],
                "questionRefs": [],
                "riskRefs": [],
                "verificationRefs": [],
                "notApplicableReason": "No UI artefact is in scope; the change is a data-layer field only.",
            }
        )
        self.assertEqual(evaluate(state)["result"], "READY")

    def test_automation_on_package_boundary_raises_the_expected_concerns(self) -> None:
        state = ready_state()
        component = state["scope"]["components"][0]
        component["artefactType"] = "Flow"
        component["hostObjectOwnership"] = "package-owned"
        computed = core.concern_applicability(state)
        self.assertTrue(computed["transaction-and-automation"]["applicable"])
        self.assertTrue(computed["package-boundaries-and-upgrade"]["applicable"])
        self.assertTrue(computed["volume-and-performance"]["applicable"])


class EvidenceAuthorityTests(unittest.TestCase):
    def test_blocking_question_cannot_be_closed_by_prose(self) -> None:
        state = ready_state()
        state["questions"][0]["evidenceRefs"] = []
        report = evaluate(state)
        self.assertTrue(any("model prose is not evidence" in gap["detail"] for gap in report["gaps"]))

    def test_needs_human_question_cannot_be_ready(self) -> None:
        state = ready_state()
        state["questions"][0]["status"] = "needs-human"
        report = evaluate(state)
        self.assertEqual(report["result"], "OPEN")
        self.assertTrue(any(gap["route"] == "human-input" for gap in report["gaps"]))

    def test_devmp_receipt_cannot_close_a_target_package_question(self) -> None:
        state = ready_state()
        state["questions"][0]["requiredAuthority"] = ["org-soql-sample"]
        state["evidenceRefs"][0].update(
            {
                "sourceType": "org-soql-sample",
                "assurance": "org-observed",
                "environmentFitness": "non-representative-devmp",
            }
        )
        report = evaluate(state)
        self.assertTrue(
            any("non-representative-devmp" in gap["detail"] for gap in report["gaps"])
        )

    def test_transport_mechanics_receipt_is_ineligible_for_design_closure(self) -> None:
        state = ready_state()
        state["evidenceRefs"][0]["validationPurpose"] = "transport-mechanics"
        report = evaluate(state)
        self.assertTrue(
            any("transport-mechanics-receipt" in gap["detail"] for gap in report["gaps"])
        )

    def test_authority_mismatch_is_reported(self) -> None:
        state = ready_state()
        state["questions"][0]["requiredAuthority"] = ["production-authoritative-human"]
        report = evaluate(state)
        self.assertTrue(any("authority-mismatch" in gap["detail"] for gap in report["gaps"]))

    def test_contested_receipt_cannot_support_a_decision(self) -> None:
        state = ready_state()
        state["evidenceRefs"][0]["status"] = "contested"
        report = evaluate(state)
        self.assertTrue(any(gap["gateId"] == "SD-G5" for gap in report["gaps"]))

    def test_incomplete_evidence_is_ineligible(self) -> None:
        state = ready_state()
        state["evidenceRefs"][0]["completeness"] = "incomplete"
        report = evaluate(state)
        self.assertTrue(any("incomplete-evidence" in gap["detail"] for gap in report["gaps"]))


class ProbeClosureTests(unittest.TestCase):
    def _with_probe(self, **overrides: object) -> dict:
        state = ready_state()
        probe = {
            "probeId": "P-001",
            "questionId": "Q-001",
            "origin": "question",
            "kind": "object-baseline",
            "target": {"objectApiName": "Case", "slice": None},
            "queryDigest": None,
            "suggestedSoql": "SELECT COUNT() FROM Case",
            "replaySpec": None,
            "expectedResultShape": "aggregate",
            "completenessCriterion": "total row count for the object",
            "requiredness": "hard",
            "conditionalPredicate": None,
            "notApplicableReason": None,
            "persistenceMode": "aggregate",
            "freshnessClass": "volume-observation",
            "stopCondition": "the baseline is known",
            "status": "closed",
            "receiptRef": "EV-001",
            "fitnessVerdict": "fit",
            "decisionImpact": "confirmed-premise",
            "recheckPlan": "never",
        }
        probe.update(overrides)
        state["probes"] = [probe]
        return state

    def test_hard_probe_cannot_be_closed_as_not_applicable(self) -> None:
        report = evaluate(self._with_probe(status="not-applicable", receiptRef=None))
        self.assertTrue(
            any("hard probe cannot be closed as not-applicable" in gap["detail"] for gap in report["gaps"])
        )

    def test_conditional_probe_needs_a_predicate_reason(self) -> None:
        report = evaluate(
            self._with_probe(requiredness="conditional", status="not-applicable", receiptRef=None)
        )
        self.assertTrue(any("predicate-based reason" in gap["detail"] for gap in report["gaps"]))
        ok = evaluate(
            self._with_probe(
                requiredness="conditional",
                status="not-applicable",
                receiptRef=None,
                notApplicableReason="The object holds no effective-window fields, so effectivity cannot collide.",
            )
        )
        self.assertEqual(ok["result"], "READY", ok["gaps"])

    def test_advisory_probe_never_blocks(self) -> None:
        report = evaluate(self._with_probe(requiredness="advisory", status="planned", receiptRef=None))
        self.assertEqual(report["result"], "READY", report["gaps"])

    def test_negative_fitness_reopens_option_selection(self) -> None:
        report = evaluate(self._with_probe(fitnessVerdict="not-fit"))
        self.assertTrue(any(gap["requiredClosure"] == "fitness-reentry" for gap in report["gaps"]))

    def test_inconclusive_fitness_routes_to_human(self) -> None:
        report = evaluate(self._with_probe(fitnessVerdict="inconclusive"))
        self.assertTrue(
            any(
                gap["requiredClosure"] == "fitness-reentry" and gap["route"] == "human-input"
                for gap in report["gaps"]
            )
        )

    def test_rechecked_hard_probe_needs_a_replayable_spec(self) -> None:
        report = evaluate(self._with_probe(recheckPlan="before-development"))
        self.assertTrue(any(gap["requiredClosure"] == "replay-spec" for gap in report["gaps"]))
        replay = {
            "kind": "canonical-soql",
            "canonicalTemplate": "SELECT COUNT() FROM Case",
            "parameters": [],
            "apiMode": "data",
            "replayable": True,
        }
        ok = evaluate(self._with_probe(recheckPlan="before-development", replaySpec=replay))
        self.assertEqual(ok["result"], "READY", ok["gaps"])

    def test_unsupported_probe_kind_is_fail_closed(self) -> None:
        report = evaluate(self._with_probe(kind="migration-readiness"))
        self.assertTrue(
            any(gap["requiredClosure"] == "UNSUPPORTED_CAPABILITY" for gap in report["gaps"])
        )
        self.assertEqual(report["result"], "OPEN")


class ScopeAndRequirementTests(unittest.TestCase):
    def test_summary_only_children_cannot_close_the_requirement_gate(self) -> None:
        state = ready_state()
        state["requirementSnapshot"]["completeness"] = "partial"
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "requirement-completeness" for gap in report["gaps"])
        )

    def test_human_requirement_without_attestation_routes_to_human_input(self) -> None:
        state = ready_state()
        state["requirementSnapshot"]["attestationRef"] = None
        report = evaluate(state)
        self.assertTrue(
            any(
                gap["requiredClosure"] == "requirement-attestation" and gap["route"] == "human-input"
                for gap in report["gaps"]
            )
        )

    def test_unknown_ownership_blocks_a_modified_component(self) -> None:
        state = ready_state()
        state["scope"]["components"][0]["componentOwnership"] = "unknown"
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "ownership-classification" for gap in report["gaps"])
        )

    def test_unknown_ownership_on_dependency_only_does_not_block(self) -> None:
        state = ready_state()
        state["scope"]["components"].append(
            {
                "componentId": "CMP-002",
                "objectApiName": "Case",
                "artefactType": "Flow",
                "apiName": "ns__Case_Package_Flow",
                "action": "dependency-only",
                "disposition": "dependency-only",
                "dispositionReason": "Runs on the same object but is not modified.",
                "description": "Existing package automation observed for orientation.",
                "componentOwnership": "unknown",
                "hostObjectOwnership": "unknown",
                "packageBoundaryRefs": ["Case"],
                "extensionPointStatus": "unknown",
                "sourceState": "present",
                "targetState": "unchanged",
                "evidenceRefs": [],
                "decisionRefs": [],
                "acIds": [],
            }
        )
        report = evaluate(state)
        self.assertFalse(
            any(gap["requiredClosure"] == "ownership-classification" for gap in report["gaps"]),
            report["gaps"],
        )

    def test_frontier_component_without_disposition_blocks(self) -> None:
        state = ready_state()
        state["scope"]["components"][0]["disposition"] = "unknown"
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "frontier-disposition" for gap in report["gaps"])
        )

    def test_configuration_artefact_requires_a_classification(self) -> None:
        state = ready_state()
        state["configurationArtefacts"] = [
            {
                "configurationArtefactId": "CFG-001",
                "objectApiName": "ns__Rule__c",
                "classificationRef": "CLS-404",
                "naturalKeyFields": ["ns__DeveloperName__c"],
                "sliceRef": None,
                "action": "modify-records",
                "description": "Adds routing rules.",
                "evidenceRefs": ["EV-001"],
                "decisionRefs": ["D-001"],
                "acIds": ["AC-LOCAL-01"],
                "migrationRefs": [],
                "rollbackRef": None,
                "verificationRefs": ["V-001"],
            }
        ]
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "data-classification" for gap in report["gaps"])
        )


class VerificationContractTests(unittest.TestCase):
    def test_ac_without_verification_blocks(self) -> None:
        state = ready_state()
        state["verificationContract"] = []
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "verification-contract" for gap in report["gaps"])
        )

    def test_verification_referencing_unknown_ac_blocks(self) -> None:
        state = ready_state()
        state["verificationContract"][0]["acIds"] = ["AC-LOCAL-01", "AC-GHOST"]
        report = evaluate(state)
        self.assertTrue(any("unknown AC AC-GHOST" in gap["detail"] for gap in report["gaps"]))


class RuleVerdictTests(unittest.TestCase):
    def test_missing_verdict_for_applicable_rule_blocks(self) -> None:
        state = ready_state()
        state["applicableRules"] = [
            item for item in state["applicableRules"] if item["ruleId"] != "MP-OWN-001"
        ]
        report = evaluate(state)
        self.assertTrue(
            any(
                gap["entity"] == "MP-OWN-001" and gap["requiredClosure"] == "rule-verdict"
                for gap in report["gaps"]
            )
        )

    def test_violated_hard_rule_cannot_submit(self) -> None:
        state = ready_state()
        state["applicableRules"] = [
            verdict("MP-OWN-001", "violated") if item["ruleId"] == "MP-OWN-001" else item
            for item in state["applicableRules"]
        ]
        report = evaluate(state)
        self.assertEqual(report["result"], "OPEN")
        self.assertTrue(any("hard rule is violated" in gap["detail"] for gap in report["gaps"]))

    def test_tension_needs_mitigation_or_a_human_receipt(self) -> None:
        state = ready_state()
        state["applicableRules"] = [
            verdict("SF-TEST-001", "tension") if item["ruleId"] == "SF-TEST-001" else item
            for item in state["applicableRules"]
        ]
        self.assertEqual(evaluate(state)["result"], "OPEN")
        state["applicableRules"] = [
            verdict("SF-TEST-001", "tension", mitigation="Manual UAT covers the async path.")
            if item["ruleId"] == "SF-TEST-001"
            else item
            for item in state["applicableRules"]
        ]
        self.assertEqual(evaluate(state)["result"], "READY", evaluate(state)["gaps"])

    def test_changed_rule_text_invalidates_the_verdict(self) -> None:
        state = ready_state()
        state["applicableRules"][0]["definitionDigest"] = "sha256:" + "f" * 64
        report = evaluate(state)
        self.assertTrue(
            any(gap["requiredClosure"] == "rule-definition-digest" for gap in report["gaps"])
        )

    def test_package_automation_selects_mp_auto_001(self) -> None:
        state = ready_state()
        component = state["scope"]["components"][0]
        component["artefactType"] = "Flow"
        component["hostObjectOwnership"] = "package-owned"
        concerns = [
            profile
            for profile, item in core.concern_applicability(state).items()
            if item["applicable"]
        ]
        selected = core.applicable_rule_ids(state, RULE_MAP, concerns)
        self.assertIn("MP-AUTO-001", selected)
        self.assertIn("MP-EXT-001", selected)
        self.assertIn("SF-BULK-001", selected)


class DocumentIntegrityTests(unittest.TestCase):
    def test_missing_design_document_blocks(self) -> None:
        report = evaluate(ready_state(), design_text=None)
        self.assertTrue(any(gap["requiredClosure"] == "design-document" for gap in report["gaps"]))

    def test_placeholder_in_authored_narrative_blocks(self) -> None:
        report = evaluate(ready_state(), design_text=DESIGN_TEXT + "\nRollback: TBD\n")
        self.assertTrue(any(gap["requiredClosure"] == "placeholder" for gap in report["gaps"]))

    def test_placeholder_inside_a_generated_block_is_not_authored_content(self) -> None:
        generated = (
            DESIGN_TEXT
            + "\n<!-- BEGIN GENERATED:DECISIONS -->\n| D-001 | TBD |\n<!-- END GENERATED:DECISIONS -->\n"
        )
        self.assertEqual(evaluate(ready_state(), design_text=generated)["result"], "READY")

    def test_missing_decision_anchor_blocks(self) -> None:
        report = evaluate(ready_state(), design_text="# Solution Design\n\nNo anchors here.\n")
        self.assertTrue(any(gap["requiredClosure"] == "design-anchor" for gap in report["gaps"]))

    def test_row_value_with_pipes_and_headings_cannot_corrupt_state(self) -> None:
        state = ready_state()
        state["decisions"][0]["summary"] = "Value | with | pipes\n## Fake heading\n<!-- END GENERATED:DECISIONS -->"
        report = evaluate(state)
        self.assertEqual(report["result"], "READY", report["gaps"])


class RoutingAndTransitionTests(unittest.TestCase):
    def test_next_focus_prefers_the_earliest_route(self) -> None:
        gaps = [
            {"gateId": "SD-G7", "entity": "AC-1", "requiredClosure": "x", "route": "verification", "detail": ""},
            {"gateId": "SD-G1", "entity": "req", "requiredClosure": "y", "route": "requirements", "detail": ""},
        ]
        self.assertEqual(core.next_focus(gaps), "requirements")
        self.assertEqual(core.next_focus([]), "none")

    def test_human_only_blockers_detects_the_awaiting_human_input_route(self) -> None:
        human = [{"gateId": "SD-G6", "entity": "R-001", "requiredClosure": "x", "route": "human-input", "detail": ""}]
        mixed = human + [
            {"gateId": "SD-G2", "entity": "CMP-001", "requiredClosure": "y", "route": "grounding", "detail": ""}
        ]
        self.assertTrue(core.human_only_blockers(human))
        self.assertFalse(core.human_only_blockers(mixed))
        self.assertFalse(core.human_only_blockers([]))

    def test_allowed_and_forbidden_transitions(self) -> None:
        self.assertTrue(core.transition_allowed("draft", "candidate"))
        self.assertTrue(core.transition_allowed("awaiting_human", "accepted"))
        self.assertFalse(core.transition_allowed("draft", "accepted"))
        self.assertFalse(core.transition_allowed("candidate", "accepted"))
        self.assertFalse(core.transition_allowed("complete", "draft"))
        with self.assertRaises(core.SolutionDesignError):
            core.transition_allowed("draft", "blocked")

    def test_there_is_no_generic_blocked_state(self) -> None:
        self.assertNotIn("blocked", core.STATES)


class RiskClassificationTests(unittest.TestCase):
    def test_plain_field_change_is_standard_risk(self) -> None:
        self.assertEqual(core.risk_classification(ready_state())["tier"], "standard")

    def test_automation_on_package_boundary_is_high_risk(self) -> None:
        state = ready_state()
        state["scope"]["components"][0]["artefactType"] = "ApexTrigger"
        state["scope"]["components"][0]["hostObjectOwnership"] = "package-owned"
        classification = core.risk_classification(state)
        self.assertEqual(classification["tier"], "high")
        self.assertTrue(
            any(trigger.startswith("automation-on-package-boundary") for trigger in classification["triggers"])
        )

    def test_contested_evidence_is_a_high_risk_trigger(self) -> None:
        state = ready_state()
        state["evidenceRefs"][0]["status"] = "contested"
        self.assertEqual(core.risk_classification(state)["tier"], "high")

    def test_irreversible_record_change_is_high_risk(self) -> None:
        state = ready_state()
        state["dataClassifications"] = [
            {
                "classificationId": "CLS-001",
                "objectApiName": "ns__Rule__c",
                "slice": None,
                "schemaOwnership": "package-owned",
                "dataStewardship": "admin-maintained",
                "dataRole": "configuration",
                "assurance": "observed-config-like",
                "evidenceRefs": ["EV-001"],
                "limitations": [],
            }
        ]
        state["configurationArtefacts"] = [
            {
                "configurationArtefactId": "CFG-001",
                "objectApiName": "ns__Rule__c",
                "classificationRef": "CLS-001",
                "naturalKeyFields": ["ns__DeveloperName__c"],
                "sliceRef": "CLS-001",
                "action": "delete-records",
                "description": "Retires superseded routing rules.",
                "evidenceRefs": ["EV-001"],
                "decisionRefs": ["D-001"],
                "acIds": ["AC-LOCAL-01"],
                "migrationRefs": [],
                "rollbackRef": None,
                "verificationRefs": ["V-001"],
            }
        ]
        classification = core.risk_classification(state)
        self.assertEqual(classification["tier"], "high")
        self.assertTrue(
            any(trigger.startswith("irreversible-data-change") for trigger in classification["triggers"])
        )


class CandidateBindingTests(unittest.TestCase):
    def _digest_input(self) -> dict:
        state = ready_state()
        concerns = [
            profile
            for profile, item in core.concern_applicability(state).items()
            if item["applicable"]
        ]
        return {
            "bundleSchemaVersion": 1,
            "gateEvaluatorVersion": CAPABILITIES["gateEvaluatorVersion"],
            "capabilityManifestDigest": core.capability_digest(CAPABILITIES),
            "caseId": state["caseId"],
            "candidateId": "CND-0001",
            "submittedFromCaseVersion": core.case_version(
                state["stateSequence"], state, core.text_digest(DESIGN_TEXT)
            ),
            "requirementSnapshot": state["requirementSnapshot"],
            "designDigest": core.text_digest(DESIGN_TEXT),
            "structuredStateSnapshot": state,
            "evidenceManifest": [
                {
                    "receiptId": "EV-001",
                    "sha256": state["evidenceRefs"][0]["sha256"],
                    "sourceType": "repository-receipt",
                    "completeness": "complete",
                    "observedAt": state["evidenceRefs"][0]["observedAt"],
                    "expiresAt": None,
                }
            ],
            "applicablePolicySnapshot": core.applicable_policy_snapshot(
                state, RULE_MAP, DEFINITIONS, concerns
            ),
            "verificationContract": state["verificationContract"],
            "sourceRefs": [],
            "orgPackageFingerprints": [],
            "gateReport": {"result": "READY", "gaps": []},
            "riskClassification": core.risk_classification(state),
            "authorWriterAssignment": state["writerAssignment"],
            "concernCoverage": state["concernCoverage"],
            "knownLimitations": [],
            "acceptedRiskReceiptRefs": [],
            "recheckPlan": [],
        }

    def test_every_semantically_approved_field_changes_the_digest(self) -> None:
        base = self._digest_input()
        baseline = core.candidate_digest(base)
        mutations = {
            "gateEvaluatorVersion": "sd-gate-v2",
            "capabilityManifestDigest": "sha256:" + "0" * 64,
            "caseId": "SD-2026-08-05-other-case",
            "candidateId": "CND-0002",
            "submittedFromCaseVersion": "cv1_" + "0" * 64,
            "designDigest": "sha256:" + "1" * 64,
            "requirementSnapshot": {"sourceType": "ado"},
            "structuredStateSnapshot": {"changed": True},
            "evidenceManifest": [],
            "applicablePolicySnapshot": {"applicablePolicyDigest": "sha256:" + "2" * 64},
            "verificationContract": [],
            "sourceRefs": [{"kind": "git-blob"}],
            "orgPackageFingerprints": [{"orgIdDigest": "sha256:" + "3" * 64}],
            "gateReport": {"result": "OPEN"},
            "riskClassification": {"tier": "high", "triggers": ["x"]},
            "authorWriterAssignment": {"writerId": "writer-two"},
            "concernCoverage": [],
            "knownLimitations": [{"limitationId": "LIM-1"}],
            "acceptedRiskReceiptRefs": ["EV-RISK-1"],
            "recheckPlan": [{"probeId": "P-001"}],
            "bundleSchemaVersion": 2,
        }
        self.assertEqual(set(mutations), set(base))
        for field, value in mutations.items():
            mutated = copy.deepcopy(base)
            mutated[field] = value
            self.assertNotEqual(
                baseline, core.candidate_digest(mutated), f"{field} does not bind the digest"
            )

    def test_policy_snapshot_digest_covers_its_own_inputs(self) -> None:
        state = ready_state()
        concerns = [
            profile
            for profile, item in core.concern_applicability(state).items()
            if item["applicable"]
        ]
        snapshot = core.applicable_policy_snapshot(state, RULE_MAP, DEFINITIONS, concerns)
        mutated = copy.deepcopy(snapshot)
        mutated["rules"][0]["verdict"] = "tension"
        recomputed = core.sd_digest(
            {key: value for key, value in mutated.items() if key != "applicablePolicyDigest"}
        )
        self.assertNotEqual(snapshot["applicablePolicyDigest"], recomputed)


class InvalidationTests(unittest.TestCase):
    def test_targeted_invalidation_only_touches_dependents(self) -> None:
        state = ready_state()
        affected = core.targeted_invalidation(state, ["EV-001"])
        self.assertEqual(affected["questions"], ["Q-001"])
        self.assertEqual(affected["decisions"], ["D-001"])
        self.assertEqual(affected["acceptanceCriteria"], ["AC-LOCAL-01"])
        unrelated = core.targeted_invalidation(state, ["EV-999"])
        self.assertEqual(unrelated["questions"], [])
        self.assertEqual(unrelated["decisions"], [])

    def test_scope_and_narrative_changes_supersede_a_candidate(self) -> None:
        previous = ready_state()
        current = copy.deepcopy(previous)
        current["scope"]["components"][0]["action"] = "modify"
        reasons = core.candidate_superseding_change(
            previous, current, previous_design=DESIGN_TEXT, current_design=DESIGN_TEXT
        )
        self.assertIn("scope-change", reasons)
        narrative = core.candidate_superseding_change(
            previous, previous, previous_design=DESIGN_TEXT, current_design=DESIGN_TEXT + "\nmore\n"
        )
        self.assertEqual(narrative, ["design-narrative"])

    def test_unrelated_change_does_not_supersede(self) -> None:
        previous = ready_state()
        current = copy.deepcopy(previous)
        current["knowledgeCandidates"] = [{"subject": "Case routing", "reason": "worth documenting"}]
        self.assertEqual(
            core.candidate_superseding_change(
                previous, current, previous_design=DESIGN_TEXT, current_design=DESIGN_TEXT
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
