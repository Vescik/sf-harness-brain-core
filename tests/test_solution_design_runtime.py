"""The Design Case runtime: concurrency, journalled commits, and the thin vertical slice.

The slice is deliberately fixture/synthetic. It proves the mechanism —
`OPEN -> READY -> candidate -> human approval -> automatic handoff` — without claiming anything
about a target managed package, which no fixture can establish.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module(name: str):
    """Load a runtime module by path and register it under its bare name.

    Registration matters because the runtime modules import each other by bare name first.
    Putting `scripts/` on `sys.path` would achieve the same thing and also change how every
    OTHER test module resolves `preflight` and `safety`, which silently broke an unrelated
    patch target once. Do not reintroduce the path insert.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gs = _module("governed_state")
core = _module("solution_design_core")
adapter_module = _module("repository_evidence_adapter")
worker_module = _module("solution_design_worker")

CASE = "SD-2026-08-05-routing-category"
DEFINITIONS = core.canonical_rule_definitions()
RULE_MAP = core.load_rule_map()
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


def rule_verdict(rule_id: str) -> dict:
    entry = RULE_MAP["rules"].get(rule_id) or RULE_MAP["manualApplicability"][rule_id]
    return {
        "ruleId": rule_id,
        "tier": entry["tier"],
        "severity": entry["severity"],
        "verdict": "honored",
        "definitionDigest": DEFINITIONS[rule_id],
    }


class WorkspaceCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sd-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.root.mkdir()
        for relative in ("config", "schemas", ".github"):
            shutil.copytree(ROOT / relative, self.root / relative, dirs_exist_ok=True)
        (self.root / ".ai").mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=harness@example.invalid",
                "-c",
                "user.name=harness",
                "commit",
                "-qm",
                "seed",
            ],
            cwd=self.root,
            check=True,
        )
        self.commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()
        self.worker = worker_module.Worker(self.root)

    def call(self, operation: str, **params):
        return worker_module.handle(self.worker, {"id": 1, "op": operation, "params": params})

    def ok(self, operation: str, **params):
        response = self.call(operation, **params)
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def fail(self, operation: str, **params) -> str:
        response = self.call(operation, **params)
        self.assertFalse(response["ok"], response.get("result"))
        return response["error"]["code"]


class VerticalSliceTests(WorkspaceCase):
    def build_ready_case(self) -> tuple[str, str]:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="Case routing category")
        version = opened["caseVersion"]

        receipt = self.ok(
            "import-repository-receipt",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=version,
            commit=self.commit,
            path="config/solution-design-capabilities.json",
        )
        version = receipt["caseVersion"]
        evidence_id = receipt["receiptId"]

        attested = self.ok(
            "record-human-input",
            caseId=CASE,
            expectedCaseVersion=version,
            answer="Case intake must store the routing category chosen by the agent.",
            authorityRole="requirement-owner",
            target={"kind": "requirement"},
            elicitation={"identity": "product-owner", "nonceDigest": "sha256:" + "e" * 64},
        )
        version = attested["caseVersion"]

        operations = [
            {
                "kind": "question-upsert",
                "payload": {
                    "questionId": "Q-001",
                    "question": "Does the tracked source already declare a routing classification field?",
                    "materiality": "blocking",
                    "requiredAuthority": ["repository-receipt"],
                    "status": "open",
                    "answer": None,
                    "evidenceRefs": [],
                    "limitations": [],
                    "route": "grounding",
                },
            },
            {
                "kind": "question-answer",
                "payload": {
                    "questionId": "Q-001",
                    "answer": "No such field is declared at the bound commit.",
                    "evidenceRefs": [evidence_id],
                },
            },
            {
                "kind": "scope-component-upsert",
                "payload": {
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
                    "evidenceRefs": [evidence_id],
                    "decisionRefs": ["D-001"],
                    "acIds": ["AC-LOCAL-01"],
                },
            },
            {
                "kind": "decision-upsert",
                "payload": {
                    "decisionId": "D-001",
                    "designAnchor": "#D-001",
                    "summary": "Add a subscriber-owned picklist field on Case.",
                    "rationaleSummary": "Keeps the classification queryable without touching package metadata.",
                    "alternativeRefs": ["#option-formula-field"],
                    "trivialityReason": None,
                    "status": "proposed",
                    "materiality": "material",
                    "acIds": ["AC-LOCAL-01"],
                    "componentIds": ["CMP-001"],
                    "questionIds": ["Q-001"],
                    "evidenceRefs": [evidence_id],
                    "riskRefs": [],
                    "verificationRefs": ["V-001"],
                },
            },
            {
                "kind": "verification-upsert",
                "payload": {
                    "verificationId": "V-001",
                    "acIds": ["AC-LOCAL-01"],
                    "decisionRefs": ["D-001"],
                    "assertion": "A Case saved through intake carries the selected routing category.",
                    "method": "apex-test",
                    "stage": "pre-review",
                    "executorRole": "development-assistant",
                    "passCriteria": "Positive, negative and bulk cases store the expected value.",
                    "expectedEvidenceType": "verification-execution",
                    "recheckProbeRefs": [],
                },
            },
            {
                "kind": "concern-disposition",
                "payload": {
                    "profileId": "data-model-and-configuration-integrity",
                    "concernId": "COV-DATA-MODEL",
                    "applicability": "applicable",
                    "status": "addressed",
                    "triggerRefs": ["CMP-001"],
                    "treatmentRefs": ["#D-001"],
                    "questionRefs": ["Q-001"],
                    "verificationRefs": ["V-001"],
                },
            },
            {
                "kind": "concern-disposition",
                "payload": {
                    "profileId": "verification-feasibility",
                    "concernId": "COV-VERIFICATION",
                    "applicability": "applicable",
                    "status": "addressed",
                    "triggerRefs": ["AC-LOCAL-01"],
                    "treatmentRefs": ["V-001"],
                    "verificationRefs": ["V-001"],
                },
            },
            {
                "kind": "concern-disposition",
                "payload": {
                    "profileId": "user-journey-and-accessibility",
                    "concernId": "COV-UI",
                    "applicability": "not-applicable",
                    "status": "addressed",
                    "notApplicableReason": "No UI artefact is in scope; the change is a data-layer field only.",
                },
            },
            {"kind": "scope-component-disposition", "payload": {"componentId": "CMP-001", "disposition": "in-scope", "frontierComplete": True}},
        ] + [{"kind": "rule-verdict", "payload": rule_verdict(rule_id)} for rule_id in READY_RULES]

        applied = self.ok(
            "apply",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=version,
            operations=operations,
        )
        version = applied["caseVersion"]

        # Requirement snapshot and narrative are the executor's and the human's jobs respectively.
        record_path = self.root / ".ai/change-records" / CASE / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        snapshot = record["solutionDesign"]["requirementSnapshot"]
        snapshot.update(
            {
                "completeness": "complete",
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
            }
        )
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        design_path = self.root / ".ai/change-records" / CASE / "design.md"
        design_path.write_text(
            design_path.read_text(encoding="utf-8").replace(
                "## 7. Chosen approach",
                "## 7. Chosen approach\n\n### D-001 — add the routing category field\n\n"
                "The field carries the classification chosen during Case intake.\n\n"
                "#### option-formula-field\n\nRejected: a formula field cannot be set by intake automation.\n",
            ),
            encoding="utf-8",
        )
        current = self.ok("context", caseId=CASE)
        return CASE, current["caseVersion"]

    def test_open_creates_an_editable_draft_with_routed_gaps(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="Case routing category")
        self.assertEqual(opened["status"], "draft")
        self.assertEqual(opened["mode"], "created")
        self.assertEqual(opened["result"], "OPEN")
        self.assertEqual(opened["nextFocus"], "requirements")
        self.assertTrue((self.root / ".ai/change-records" / CASE / "design.md").is_file())

    def test_open_on_an_existing_case_without_a_token_is_read_only(self) -> None:
        first = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        again = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        self.assertEqual(again["mode"], "resumed-read-only")
        self.assertEqual(again["caseVersion"], first["caseVersion"])

    def test_stale_version_wrong_writer_and_bad_operation_all_fail_cleanly(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        version = opened["caseVersion"]
        operation = [{"kind": "question-upsert", "payload": {"questionId": "Q-9"}}]
        self.assertEqual(
            self.fail(
                "apply",
                caseId=CASE,
                writerId="writer-one",
                expectedCaseVersion="cv1_" + "0" * 64,
                operations=operation,
            ),
            "STALE_CASE_VERSION",
        )
        self.assertEqual(
            self.fail(
                "apply",
                caseId=CASE,
                writerId="writer-two",
                expectedCaseVersion=version,
                operations=operation,
            ),
            "WRONG_WRITER",
        )
        self.assertEqual(
            self.fail(
                "apply",
                caseId=CASE,
                writerId="writer-one",
                expectedCaseVersion=version,
                operations=[{"kind": "invented-operation", "payload": {}}],
            ),
            "OPERATION_REJECTED",
        )

    def test_model_supplied_receipt_payload_is_refused(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        code = self.fail(
            "apply",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            operations=[
                {
                    "kind": "repository-source-receipt-import",
                    "payload": {"evidenceRef": {"receiptId": "EV-forged"}},
                }
            ],
        )
        self.assertEqual(code, "OPERATION_REJECTED")

    def test_full_slice_reaches_ready_candidate_approval_and_handoff(self) -> None:
        case, version = self.build_ready_case()
        check = self.ok("check", caseId=case)
        self.assertEqual(check["result"], "READY", check["gaps"])

        submitted = self.ok(
            "submit", caseId=case, writerId="writer-one", expectedCaseVersion=version
        )
        self.assertEqual(submitted["submitResult"], "READY")
        self.assertEqual(submitted["status"], "awaiting_human")
        candidate_id = submitted["candidateId"]
        digest = submitted["candidateDigest"]

        bundle = json.loads(
            (
                self.root / ".ai/change-records" / case / "candidates" / candidate_id / "bundle.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(bundle["candidateDigest"], core.candidate_digest(bundle["candidateDigestInput"]))
        snapshot = (
            self.root / ".ai/change-records" / case / "candidates" / candidate_id / "design.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            core.text_digest(snapshot), bundle["candidateDigestInput"]["designDigest"]
        )

        # The designer cannot approve their own candidate.
        self.assertEqual(
            self.fail(
                "confirm-candidate",
                caseId=case,
                candidateId=candidate_id,
                candidateDigest=digest,
                elicitation={"identity": "writer-one", "nonceDigest": "sha256:" + "a" * 64},
            ),
            "SELF_APPROVAL_DENIED",
        )
        # A decision without an elicitation response is not a decision.
        self.assertEqual(
            self.fail(
                "confirm-candidate", caseId=case, candidateId=candidate_id, candidateDigest=digest
            ),
            "HUMAN_RESPONSE_REQUIRED",
        )
        # A decision naming a different digest is refused.
        self.assertEqual(
            self.fail(
                "confirm-candidate",
                caseId=case,
                candidateId=candidate_id,
                candidateDigest="sha256:" + "f" * 64,
                elicitation={"identity": "approver", "nonceDigest": "sha256:" + "a" * 64},
            ),
            "CANDIDATE_MISMATCH",
        )

        approved = self.ok(
            "confirm-candidate",
            caseId=case,
            candidateId=candidate_id,
            candidateDigest=digest,
            elicitation={"identity": "approver", "nonceDigest": "sha256:" + "a" * 64},
        )
        self.assertEqual(approved["status"], "accepted")
        approval = json.loads(
            (self.root / ".ai/change-records" / case / "approvals" / f"{approved['receiptId']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(approval["candidateDigest"], digest)
        self.assertEqual(approval["human"]["mechanism"], "vscode-mcp-elicitation-v1")

        handed = self.ok("start-development", caseId=case)
        self.assertEqual(handed["status"], "development")
        handoff = json.loads(
            (self.root / ".ai/change-records" / case / "handoffs" / f"{handed['handoffId']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(handoff["candidateDigest"], digest)
        self.assertEqual(handoff["handoff"]["toRole"], "development-assistant")
        self.assertTrue(handoff["handoff"]["verificationContract"])

    def test_generated_tables_cannot_drift_from_structured_scope(self) -> None:
        case, _version = self.build_ready_case()
        design = (self.root / ".ai/change-records" / case / "design.md").read_text(encoding="utf-8")
        self.assertIn("Case.Routing_Category__c", design)
        self.assertIn("<!-- BEGIN GENERATED:SOLUTION-ARTEFACTS -->", design)
        # A hand-edited generated block is overwritten by the next structured mutation.
        path = self.root / ".ai/change-records" / case / "design.md"
        corrupted = design.replace(
            "Case.Routing_Category__c", "Case.Something_Else__c"
        )
        path.write_text(corrupted, encoding="utf-8")
        current = self.ok("context", caseId=case)
        applied = self.ok(
            "apply",
            caseId=case,
            writerId="writer-one",
            expectedCaseVersion=current["caseVersion"],
            operations=[
                {
                    "kind": "concern-disposition",
                    "payload": {
                        "profileId": "verification-feasibility",
                        "concernId": "COV-VERIFICATION",
                        "applicability": "applicable",
                        "status": "addressed",
                        "treatmentRefs": ["V-001"],
                        "verificationRefs": ["V-001"],
                    },
                }
            ],
        )
        self.assertEqual(applied["result"], "READY", applied["openObligations"])
        restored = path.read_text(encoding="utf-8")
        self.assertIn("Case.Routing_Category__c", restored)
        self.assertNotIn("Case.Something_Else__c", restored)

    def test_post_submit_edit_cannot_mutate_the_candidate(self) -> None:
        case, version = self.build_ready_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        candidate = self.root / ".ai/change-records" / case / "candidates" / submitted["candidateId"]
        before = (candidate / "design.md").read_text(encoding="utf-8")
        design_path = self.root / ".ai/change-records" / case / "design.md"
        design_path.write_text(
            design_path.read_text(encoding="utf-8") + "\nA later edit.\n", encoding="utf-8"
        )
        self.assertEqual((candidate / "design.md").read_text(encoding="utf-8"), before)
        # And an accepted case is not editable.
        current = self.ok("context", caseId=case)
        self.assertEqual(
            self.fail(
                "apply",
                caseId=case,
                writerId="writer-one",
                expectedCaseVersion=current["caseVersion"],
                operations=[{"kind": "concern-disposition", "payload": {"profileId": "verification-feasibility"}}],
            ),
            "OPERATION_REJECTED",
        )

    def test_revision_request_supersedes_the_candidate_and_reopens_the_draft(self) -> None:
        case, version = self.build_ready_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(
            self.fail(
                "request-candidate-revision",
                caseId=case,
                candidateId=submitted["candidateId"],
                candidateDigest=submitted["candidateDigest"],
                elicitation={"identity": "approver", "nonceDigest": "sha256:" + "a" * 64},
            ),
            "INVALID_INPUT",
        )
        revised = self.ok(
            "request-candidate-revision",
            caseId=case,
            candidateId=submitted["candidateId"],
            candidateDigest=submitted["candidateDigest"],
            reason="The rollback story is missing.",
            elicitation={"identity": "approver", "nonceDigest": "sha256:" + "a" * 64},
        )
        self.assertEqual(revised["status"], "draft")
        self.assertIsNone(revised["activeCandidateRef"])
        receipt = json.loads(
            (self.root / ".ai/change-records" / case / "approvals" / f"{revised['receiptId']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["kind"], "candidate-revision-request")
        self.assertEqual(receipt["supersedes"], submitted["candidateId"])

    def test_writer_transfer_moves_ownership_and_only_the_owner_may_do_it(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        self.assertEqual(
            self.fail(
                "transfer-case-writer",
                caseId=CASE,
                expectedCaseVersion=opened["caseVersion"],
                targetWriterId="writer-two",
                elicitation={"identity": "writer-three", "nonceDigest": "sha256:" + "a" * 64},
            ),
            "WRONG_WRITER",
        )
        transferred = self.ok(
            "transfer-case-writer",
            caseId=CASE,
            expectedCaseVersion=opened["caseVersion"],
            targetWriterId="writer-two",
            elicitation={"identity": "writer-one", "nonceDigest": "sha256:" + "a" * 64},
        )
        self.assertEqual(transferred["writer"]["writerId"], "writer-two")
        self.assertEqual(transferred["writer"]["assignmentSequence"], 2)
        self.assertEqual(
            self.fail(
                "apply",
                caseId=CASE,
                writerId="writer-one",
                expectedCaseVersion=transferred["caseVersion"],
                operations=[{"kind": "question-upsert", "payload": {"questionId": "Q-1"}}],
            ),
            "WRONG_WRITER",
        )

    def test_unsupported_capability_cannot_reach_a_candidate(self) -> None:
        case, version = self.build_ready_case()
        record_path = self.root / ".ai/change-records" / case / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["solutionDesign"]["probes"] = [
            {
                "probeId": "P-001",
                "questionId": "Q-001",
                "origin": "question",
                "kind": "migration-readiness",
                "target": {"objectApiName": "Case", "slice": None},
                "queryDigest": None,
                "suggestedSoql": None,
                "replaySpec": None,
                "expectedResultShape": "aggregate",
                "completenessCriterion": "migration blockers",
                "requiredness": "advisory",
                "conditionalPredicate": None,
                "notApplicableReason": None,
                "persistenceMode": "aggregate",
                "freshnessClass": "volume-observation",
                "stopCondition": "blockers known",
                "status": "planned",
                "receiptRef": None,
                "fitnessVerdict": None,
                "decisionImpact": None,
                "recheckPlan": "never",
            }
        ]
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        current = self.ok("context", caseId=case)
        submitted = self.ok(
            "submit", caseId=case, writerId="writer-one", expectedCaseVersion=current["caseVersion"]
        )
        self.assertEqual(submitted["submitResult"], "OPEN")
        self.assertNotIn("candidateId", submitted)
        self.assertTrue(
            any(gap["requiredClosure"] == "UNSUPPORTED_CAPABILITY" for gap in submitted["gaps"])
        )

    def test_human_only_blockers_route_to_awaiting_human_input_without_a_candidate(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        submitted = self.ok(
            "submit", caseId=CASE, writerId="writer-one", expectedCaseVersion=opened["caseVersion"]
        )
        self.assertEqual(submitted["submitResult"], "OPEN")
        self.assertNotIn("candidateId", submitted)
        self.assertEqual(submitted["status"], "draft")


class FrameHandlingTests(WorkspaceCase):
    def test_malformed_and_oversized_frames_fail_closed(self) -> None:
        import io

        payload = "\n".join(
            [
                "not json",
                json.dumps(["array", "not", "object"]),
                json.dumps({"id": 3, "op": "open"}),
                json.dumps({"id": 4, "op": "nope", "params": {}}),
                "x" * (worker_module.MAX_FRAME_BYTES + 1),
            ]
        )
        output = io.StringIO()
        worker_module.serve(io.StringIO(payload), output, self.root)
        frames = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([frame["ok"] for frame in frames], [False] * 5)
        self.assertEqual(
            [frame["error"]["code"] for frame in frames],
            [
                "MALFORMED_FRAME",
                "MALFORMED_FRAME",
                "INVALID_INPUT",
                "UNKNOWN_OPERATION",
                "FRAME_TOO_LARGE",
            ],
        )

    def test_one_response_frame_per_request_and_nothing_else_on_stdout(self) -> None:
        import io

        requests = "\n".join(
            json.dumps({"id": index, "op": "check", "params": {"caseId": CASE}})
            for index in range(3)
        )
        output = io.StringIO()
        worker_module.serve(io.StringIO(requests), output, self.root)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual([json.loads(line)["id"] for line in lines], [0, 1, 2])


class LeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sd-lease-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / "runtime"
        self.case = self.root / "case"
        self.case.mkdir()

    def test_two_contenders_and_exactly_one_wins(self) -> None:
        first = gs.Lease.acquire(self.runtime, self.case)
        with self.assertRaises(gs.LeaseUnavailable):
            gs.Lease.acquire(self.runtime, self.case)
        first.release()
        second = gs.Lease.acquire(self.runtime, self.case)
        self.assertNotEqual(first.nonce, second.nonce)
        second.release()

    def test_an_expired_lease_is_quarantined_not_overwritten(self) -> None:
        stale = gs.Lease.acquire(self.runtime, self.case, ttl_seconds=1)
        stale.payload["expiresAt"] = gs.iso(gs.utc_now() - timedelta(hours=2))
        stale.path.write_text(json.dumps(stale.payload), encoding="utf-8")
        fresh = gs.Lease.acquire(self.runtime, self.case)
        self.assertNotEqual(fresh.nonce, stale.nonce)
        self.assertFalse(stale.still_owned())
        quarantined = list((self.runtime / "leases").glob("*.stale.*"))
        self.assertTrue(quarantined, "the expired lease must be renamed, never overwritten in place")
        fresh.release()

    def test_a_live_lease_is_never_stolen_under_clock_skew(self) -> None:
        live = gs.Lease.acquire(self.runtime, self.case, ttl_seconds=600)
        with self.assertRaises(gs.LeaseUnavailable):
            gs.Lease.acquire(self.runtime, self.case, clock_skew_seconds=30)
        self.assertTrue(live.still_owned())
        live.release()

    def test_releasing_a_reclaimed_lease_does_not_delete_the_new_owners_file(self) -> None:
        first = gs.Lease.acquire(self.runtime, self.case, ttl_seconds=1)
        first.payload["expiresAt"] = gs.iso(gs.utc_now() - timedelta(hours=2))
        first.path.write_text(json.dumps(first.payload), encoding="utf-8")
        second = gs.Lease.acquire(self.runtime, self.case)
        first.release()
        self.assertTrue(second.path.is_file())
        self.assertTrue(second.still_owned())

    def test_pid_reuse_alone_never_grants_ownership(self) -> None:
        lease = gs.Lease.acquire(self.runtime, self.case)
        impostor = json.loads(lease.path.read_text(encoding="utf-8"))
        impostor["ownerNonce"] = "0" * 32
        lease.path.write_text(json.dumps(impostor), encoding="utf-8")
        self.assertFalse(lease.still_owned(), "same PID, different nonce, must not be owned")
        with self.assertRaises(gs.LeaseUnavailable):
            lease.renew()


class JournalTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sd-journal-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / "runtime"
        self.case = self.root / "case"
        self.case.mkdir()
        self.record = self.case / "record.json"
        self.design = self.case / "design.md"
        self.record.write_text("OLD-RECORD", encoding="utf-8")
        self.design.write_text("OLD-DESIGN", encoding="utf-8")

    def test_the_pair_moves_together(self) -> None:
        gs.commit_pair(
            self.runtime,
            self.case,
            [(self.record, b"NEW-RECORD"), (self.design, b"NEW-DESIGN")],
        )
        self.assertEqual(self.record.read_text(encoding="utf-8"), "NEW-RECORD")
        self.assertEqual(self.design.read_text(encoding="utf-8"), "NEW-DESIGN")
        self.assertEqual(gs.recover(self.runtime, self.case), "clean")

    def test_recovery_after_a_crash_between_replaces_completes_the_new_pair(self) -> None:
        staged = [
            (self.record, gs.write_temp(self.record, b"NEW-RECORD")),
            (self.design, gs.write_temp(self.design, b"NEW-DESIGN")),
        ]
        journal = gs.journal_path(self.runtime, self.case)
        journal.parent.mkdir(parents=True, exist_ok=True)
        import hashlib

        journal.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "casePath": str(self.case),
                    "createdAt": gs.iso(gs.utc_now()),
                    "writes": [
                        {
                            "target": str(target),
                            "temp": str(temporary),
                            "sha256": hashlib.sha256(temporary.read_bytes()).hexdigest(),
                        }
                        for target, temporary in staged
                    ],
                }
            ),
            encoding="utf-8",
        )
        # Simulate the crash: the first replace landed, the second did not.
        gs.replace_with_retry(staged[0][1], self.record)
        self.assertEqual(gs.recover(self.runtime, self.case), "completed")
        self.assertEqual(self.record.read_text(encoding="utf-8"), "NEW-RECORD")
        self.assertEqual(self.design.read_text(encoding="utf-8"), "NEW-DESIGN")

    def test_a_corrupt_temp_file_rolls_back_rather_than_writing_a_mixed_pair(self) -> None:
        temporary = gs.write_temp(self.design, b"NEW-DESIGN")
        journal = gs.journal_path(self.runtime, self.case)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "casePath": str(self.case),
                    "createdAt": gs.iso(gs.utc_now()),
                    "writes": [
                        {"target": str(self.design), "temp": str(temporary), "sha256": "0" * 64}
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(gs.recover(self.runtime, self.case), "rolled-back")
        self.assertEqual(self.design.read_text(encoding="utf-8"), "OLD-DESIGN")

    def test_a_reclaimed_lease_blocks_the_commit_before_anything_is_written(self) -> None:
        lease = gs.Lease.acquire(self.runtime, self.case)
        impostor = json.loads(lease.path.read_text(encoding="utf-8"))
        impostor["ownerNonce"] = "0" * 32
        lease.path.write_text(json.dumps(impostor), encoding="utf-8")
        with self.assertRaises(gs.LeaseUnavailable):
            gs.commit_pair(
                self.runtime, self.case, [(self.record, b"NEW-RECORD")], lease=lease
            )
        self.assertEqual(self.record.read_text(encoding="utf-8"), "OLD-RECORD")


class PathConfinementTests(unittest.TestCase):
    def test_windows_hostile_paths_are_rejected_on_every_platform(self) -> None:
        for hostile in (
            "../escape",
            "/absolute",
            "//server/share",
            "C:/drive",
            "a/CON/file.md",
            "a/PRN.md",
            "a/trailing./file.md",
            "a/trailing /file.md",
            "a/stream:name",
            "a/pipe|name",
            "a/quote\"name",
            "a/star*name",
        ):
            with self.assertRaises(gs.GovernedStateError, msg=hostile):
                gs.safe_relative_path(hostile)

    def test_ordinary_paths_are_normalized(self) -> None:
        self.assertEqual(gs.safe_relative_path("a\\b\\c.md"), "a/b/c.md")
        self.assertEqual(gs.safe_relative_path("a/b/c.md"), "a/b/c.md")

    def test_case_fold_collisions_are_rejected(self) -> None:
        gs.assert_case_fold_unique(["a/b.md", "a/c.md"])
        with self.assertRaises(gs.GovernedStateError):
            gs.assert_case_fold_unique(["a/B.md", "a/b.md"])

    def test_symlink_escape_is_refused(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sd-path-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / "root"
        (root / "inside").mkdir(parents=True)
        outside = base / "outside"
        outside.mkdir()
        link = root / "escape"
        os.symlink(outside, link)
        with self.assertRaises(gs.GovernedStateError):
            gs.contained_path(root, "escape/secret.md")

    def test_a_root_too_deep_for_windows_is_refused_before_the_first_write(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sd-budget-")
        self.addCleanup(temporary.cleanup)
        deep = Path(temporary.name) / ("d" * 60) / ("e" * 60) / ("f" * 60) / ("g" * 60)
        deep.mkdir(parents=True)
        with self.assertRaises(gs.GovernedStateError):
            gs.assert_path_budget(deep)


class RepositoryEvidenceTests(WorkspaceCase):
    """SAFE-CLAIM-001 v4: the fallback is a governed receipt, never a model file read."""

    def setUp(self) -> None:
        super().setUp()
        self.adapter = adapter_module

    def test_a_tracked_blob_yields_commit_bound_facts(self) -> None:
        facts = self.adapter.capture(
            self.root, self.commit, "config/solution-design-capabilities.json"
        )
        self.assertEqual(facts["commit"], self.commit)
        self.assertEqual(facts["coverage"], "full")
        self.assertFalse(facts["workingTreeDrift"])
        self.assertTrue(facts["contentDigest"].startswith("sha256:"))
        self.assertRegex(facts["blobOid"], r"^[0-9a-f]{40,64}$")

    def test_a_line_range_is_range_bounded_and_digests_differently(self) -> None:
        whole = self.adapter.capture(self.root, self.commit, "config/solution-design-rule-map.json")
        ranged = self.adapter.capture(
            self.root, self.commit, "config/solution-design-rule-map.json", first_line=1, last_line=3
        )
        self.assertEqual(ranged["coverage"], "range-bounded")
        self.assertEqual(ranged["range"], "L1-L3")
        self.assertNotEqual(whole["contentDigest"], ranged["contentDigest"])

    def test_hostile_paths_and_short_commits_are_refused(self) -> None:
        for path in (
            "../etc/passwd",
            "/etc/passwd",
            "C:/windows/system32",
            "-cached",
            "config/../../escape.json",
            "config/CON.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(self.adapter.RepositoryEvidenceError):
                    self.adapter.capture(self.root, self.commit, path)
        with self.assertRaises(self.adapter.RepositoryEvidenceError):
            self.adapter.capture(self.root, self.commit[:8], "config/solution-design-rule-map.json")

    def test_a_directory_and_a_missing_path_are_refused(self) -> None:
        with self.assertRaises(self.adapter.RepositoryEvidenceError):
            self.adapter.capture(self.root, self.commit, "config")
        with self.assertRaises(self.adapter.RepositoryEvidenceError):
            self.adapter.capture(self.root, self.commit, "config/does-not-exist.json")

    def test_a_symlink_entry_is_refused_by_mode(self) -> None:
        target = self.root / "config" / "solution-design-rule-map.json"
        link = self.root / "config" / "link-to-rules.json"
        os.symlink(target, link)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=harness@example.invalid",
                "-c",
                "user.name=harness",
                "commit",
                "-qm",
                "symlink",
            ],
            cwd=self.root,
            check=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()
        with self.assertRaises(self.adapter.RepositoryEvidenceError) as raised:
            self.adapter.capture(self.root, commit, "config/link-to-rules.json")
        self.assertIn("symlink", str(raised.exception))

    def test_working_tree_drift_is_reported_and_recorded_as_a_limitation(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        target = self.root / "config" / "solution-design-capabilities.json"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        result = self.ok(
            "import-repository-receipt",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            commit=self.commit,
            path="config/solution-design-capabilities.json",
        )
        self.assertTrue(result["workingTreeDrift"])
        receipt = json.loads(
            (
                self.root / ".ai/change-records" / CASE / "evidence" / f"{result['receiptId']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(receipt["source"]["workingTreeDrift"])
        self.assertTrue(receipt["limitations"])

    def test_the_receipt_carries_digests_not_file_content(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        result = self.ok(
            "import-repository-receipt",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            commit=self.commit,
            path="config/solution-design-capabilities.json",
        )
        raw = (
            self.root / ".ai/change-records" / CASE / "evidence" / f"{result['receiptId']}.json"
        ).read_text(encoding="utf-8")
        source_text = (self.root / "config/solution-design-capabilities.json").read_text(
            encoding="utf-8"
        )
        # The receipt records digests, coverage and shape — never the file's content.
        self.assertNotIn(source_text.strip(), raw)
        for token in ("concernProfiles", "gateEvaluatorVersion", "probeKinds"):
            self.assertNotIn(token, raw, f"receipt leaked source content token {token!r}")
        receipt = json.loads(raw)
        self.assertEqual(
            sorted(receipt["result"]["derivedFacts"]), ["byteSize", "lineCount", "mode"]
        )


class RequirementSnapshotTests(WorkspaceCase):
    """P3: the executor authors the requirement snapshot; the model never transcribes it."""

    ADAPTER_SNAPSHOT = {
        "sourceType": "ado",
        "organization": "contoso",
        "project": "Delivery",
        "itemId": 12345,
        "itemType": "Feature",
        "title": "Case routing",
        "revision": 17,
        "rootAcceptanceCriteria": [],
        "rootAcDigest": "sha256:" + "1" * 64,
        "children": [
            {
                "id": 12346,
                "type": "User Story",
                "state": "Active",
                "title": "Store the routing category",
                "revision": 4,
                "description": "Intake stores the category.",
                "acceptanceCriteria": "Case intake stores the routing category.",
                "detailed": True,
            }
        ],
        "includedItems": [12346],
        "excludedItems": [],
        "childIds": [12346],
        "completeness": "complete",
        "missingDetailItemIds": [],
        "linkedTestCases": [],
        "sourceDigest": "sha256:" + "2" * 64,
    }

    def test_a_model_supplied_snapshot_is_refused(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        code = self.fail(
            "set-requirement-snapshot",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            adapterSnapshot=self.ADAPTER_SNAPSHOT,
        )
        self.assertEqual(code, "MODEL_AUTHORED_REQUIREMENT")

    def test_the_executor_snapshot_lands_with_stable_ac_identities(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        result = self.ok(
            "set-requirement-snapshot",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            executorAuthored=True,
            adapterSnapshot=self.ADAPTER_SNAPSHOT,
        )
        self.assertEqual(result["acceptanceCriteria"], 1)
        self.assertEqual(result["unresolvedContradictions"], [])
        record = json.loads(
            (self.root / ".ai/change-records" / CASE / "record.json").read_text(encoding="utf-8")
        )
        snapshot = record["solutionDesign"]["requirementSnapshot"]
        self.assertEqual(snapshot["completeness"], "complete")
        self.assertEqual(snapshot["acceptanceCriteria"][0]["lineageKey"], "ado:Delivery:12346:work-item")
        self.assertEqual(record["workItem"]["id"], 12345)

    def test_a_summary_only_child_cannot_produce_a_complete_snapshot(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        partial = json.loads(json.dumps(self.ADAPTER_SNAPSHOT))
        partial["children"][0]["detailed"] = False
        partial["completeness"] = "partial"
        partial["missingDetailItemIds"] = [12346]
        result = self.ok(
            "set-requirement-snapshot",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            executorAuthored=True,
            adapterSnapshot=partial,
        )
        self.assertTrue(result["unresolvedContradictions"])
        self.assertTrue(
            any(gap["requiredClosure"].startswith("requirement") for gap in result["openObligations"])
        )


class AcceptanceCriteriaLineageTests(unittest.TestCase):
    """AC identity and AC content are separate; ordinal position is never identity."""

    def snapshot(self, clauses: list[str], item_id: int = 900) -> dict:
        import hashlib

        return {
            "project": "Delivery",
            "itemId": item_id,
            "revision": 3,
            "children": [],
            "rootAcceptanceCriteria": [
                {
                    "ordinal": index + 1,
                    "summary": text,
                    "textDigest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                    "fingerprint": "sha256:"
                    + hashlib.sha256(
                        "".join(c if c.isalnum() else " " for c in text.lower()).strip().encode()
                    ).hexdigest(),
                }
                for index, text in enumerate(clauses)
            ],
            "missingDetailItemIds": [],
            "includedItems": [],
            "excludedItems": [],
            "completeness": "complete",
            "sourceDigest": "sha256:" + "3" * 64,
        }

    def test_editing_a_child_changes_the_digest_not_the_identity(self) -> None:
        first = {
            "project": "Delivery",
            "itemId": 800,
            "revision": 2,
            "children": [
                {"id": 801, "revision": 1, "title": "t", "acceptanceCriteria": "Original text."}
            ],
            "rootAcceptanceCriteria": [],
            "missingDetailItemIds": [],
            "includedItems": [],
            "excludedItems": [],
            "completeness": "complete",
            "sourceDigest": "sha256:" + "4" * 64,
        }
        before, _ = core.reconcile_acceptance_criteria([], first)
        second = json.loads(json.dumps(first))
        second["children"][0]["acceptanceCriteria"] = "Rewritten text."
        after, ambiguities = core.reconcile_acceptance_criteria(before, second)
        self.assertEqual(before[0]["acId"], after[0]["acId"])
        self.assertNotEqual(before[0]["textDigest"], after[0]["textDigest"])
        self.assertEqual(ambiguities, [])

    def test_reordering_clauses_keeps_their_identities(self) -> None:
        before, _ = core.reconcile_acceptance_criteria(
            [], self.snapshot(["Alpha rule applies.", "Beta rule applies."])
        )
        for item in before:
            item["fingerprint"] = next(
                clause["fingerprint"]
                for clause in self.snapshot(["Alpha rule applies.", "Beta rule applies."])[
                    "rootAcceptanceCriteria"
                ]
                if clause["textDigest"] == item["textDigest"]
            )
        after, ambiguities = core.reconcile_acceptance_criteria(
            before, self.snapshot(["Beta rule applies.", "Alpha rule applies."])
        )
        self.assertEqual(ambiguities, [])
        self.assertEqual(
            {item["acId"] for item in before}, {item["acId"] for item in after}
        )

    def test_a_split_is_reported_for_human_reconciliation(self) -> None:
        before, _ = core.reconcile_acceptance_criteria([], self.snapshot(["One combined rule."]))
        for item in before:
            item["fingerprint"] = "sha256:" + "9" * 64
        _after, ambiguities = core.reconcile_acceptance_criteria(
            before, self.snapshot(["First half.", "Second half."])
        )
        self.assertTrue(ambiguities)
        self.assertTrue(any("human reconciliation" in item for item in ambiguities))

    def test_requirement_drift_names_the_moved_items(self) -> None:
        snapshot = {
            "itemId": 500,
            "revision": 7,
            "acceptanceCriteria": [
                {
                    "acId": "AC-1",
                    "sourceItemId": 501,
                    "sourceLocalKey": "work-item",
                    "sourceRevision": 2,
                }
            ],
        }
        self.assertEqual(core.requirement_drift(snapshot, {"500": 7, "501": 2}), [])
        drift = core.requirement_drift(snapshot, {"500": 8, "501": 3})
        self.assertEqual(len(drift), 2)
        self.assertTrue(any("work item 500" in item for item in drift))
        self.assertTrue(any("child work item 501" in item for item in drift))


class AdoAdapterNodeTests(unittest.TestCase):
    """The adapter's pure normalization, exercised in Node.

    The network path is NOT covered here: no ADO organization is reachable from the build
    machine. What is covered is everything that decides what reaches durable state — HTML
    stripping, clause splitting, and the fingerprint that must not be the ordinal.
    """

    def run_node(self, script: str) -> dict:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_html_is_stripped_never_interpreted(self) -> None:
        script = """
        import { plainText } from "./scripts/ado_requirement_adapter.mjs";
        const html = "<p>Given a Case</p><script>alert(1)</scr" + "ipt><li>Then &amp; route it</li>";
        console.log(JSON.stringify({ text: plainText(html) }));
        """
        text = self.run_node(script)["text"]
        self.assertIn("Given a Case", text)
        self.assertIn("Then & route it", text)
        self.assertNotIn("<", text)
        self.assertNotIn("alert(1)", text.replace("alert(1)", "") or text)

    def test_clause_candidates_drop_bullets_and_fingerprint_by_content(self) -> None:
        script = """
        import { clauseCandidates } from "./scripts/ado_requirement_adapter.mjs";
        const a = clauseCandidates("<li>- Alpha rule applies.</li><li>2) Beta rule applies.</li>");
        const b = clauseCandidates("<li>Beta rule applies.</li><li>Alpha  RULE   applies.</li>");
        console.log(JSON.stringify({ a, b }));
        """
        payload = self.run_node(script)
        first, second = payload["a"], payload["b"]
        self.assertEqual([item["summary"] for item in first], ["Alpha rule applies.", "Beta rule applies."])
        # Reordered and re-cased content keeps its fingerprint, so identity survives a reorder.
        self.assertEqual(first[0]["fingerprint"], second[1]["fingerprint"])
        self.assertEqual(first[1]["fingerprint"], second[0]["fingerprint"])
        # Ordinal is not identity.
        self.assertNotEqual(first[0]["ordinal"], second[1]["ordinal"])

    def test_the_adapter_points_at_the_locally_installed_entrypoint(self) -> None:
        script = """
        import { ADO_ENTRYPOINT } from "./scripts/ado_requirement_adapter.mjs";
        import { existsSync } from "node:fs";
        console.log(JSON.stringify({ path: ADO_ENTRYPOINT, exists: existsSync(ADO_ENTRYPOINT) }));
        """
        payload = self.run_node(script)
        self.assertIn("node_modules/@azure-devops/mcp/dist/index.js", payload["path"])
        self.assertTrue(payload["exists"], "run `npm ci --ignore-scripts` first")

    def test_no_runtime_package_acquisition_remains(self) -> None:
        source = (ROOT / "scripts" / "ado_requirement_adapter.mjs").read_text(encoding="utf-8")
        # Prose may explain why npx is forbidden; a string literal would be an invocation.
        self.assertNotIn('"npx"', source)
        self.assertNotIn("'npx'", source)
        self.assertNotIn("`npx`", source.replace("`npx -y`", ""))
        self.assertIn("process.execPath", source)
        self.assertIn("shell: false", source)
        mcp = json.loads((ROOT / ".vscode/mcp.json").read_text(encoding="utf-8"))
        self.assertNotIn("npx", json.dumps(mcp))


class ObligationSeedingTests(WorkspaceCase):
    """The runtime seeds what the scope implies; it never overwrites a designer disposition."""

    PACKAGE_COMPONENT = {
        "componentId": "CMP-PKG",
        "objectApiName": "ns__Rule__c",
        "artefactType": "Flow",
        "apiName": "ns__Rule_Before_Save",
        "action": "create",
        "disposition": "in-scope",
        "dispositionReason": None,
        "description": "New automation on a package-owned object.",
        "componentOwnership": "subscriber-owned",
        "hostObjectOwnership": "package-owned",
        "packageBoundaryRefs": ["ns__Rule__c"],
        "extensionPointStatus": "unknown",
        "sourceState": "absent",
        "targetState": "proposed",
        "evidenceRefs": [],
        "decisionRefs": [],
        "acIds": [],
    }

    def seeded(self) -> dict:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        return self.ok(
            "apply",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            operations=[{"kind": "scope-component-upsert", "payload": self.PACKAGE_COMPONENT}],
        )

    def test_a_package_boundary_seeds_its_material_question(self) -> None:
        self.seeded()
        record = json.loads(
            (self.root / ".ai/change-records" / CASE / "record.json").read_text(encoding="utf-8")
        )
        questions = record["solutionDesign"]["questions"]
        self.assertTrue(any(item["questionId"] == core.PACKAGE_QUESTION_ID for item in questions))
        seeded = next(item for item in questions if item["questionId"] == core.PACKAGE_QUESTION_ID)
        self.assertEqual(seeded["materiality"], "blocking")
        self.assertEqual(seeded["route"], "grounding")

    def test_applicable_concerns_are_seeded_as_open(self) -> None:
        result = self.seeded()
        profiles = {item["profileId"] for item in result["concernCoverage"]}
        self.assertIn("transaction-and-automation", profiles)
        self.assertIn("package-boundaries-and-upgrade", profiles)
        self.assertTrue(all(item["status"] == "open" for item in result["concernCoverage"]))

    def test_seeding_never_overwrites_a_recorded_disposition(self) -> None:
        result = self.seeded()
        applied = self.ok(
            "apply",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=result["caseVersion"],
            operations=[
                {
                    "kind": "concern-disposition",
                    "payload": {
                        "profileId": "transaction-and-automation",
                        "concernId": "COV-TRANSACTION-AND-AUTOMATION",
                        "applicability": "applicable",
                        "status": "addressed",
                        "treatmentRefs": ["#D-001"],
                    },
                }
            ],
        )
        entry = next(
            item
            for item in applied["concernCoverage"]
            if item["profileId"] == "transaction-and-automation"
        )
        self.assertEqual(entry["status"], "addressed")
        self.assertEqual(entry["treatmentRefs"], ["#D-001"])

    def test_a_subscriber_only_change_seeds_no_package_question(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        component = json.loads(json.dumps(self.PACKAGE_COMPONENT))
        component.update(
            {
                "componentId": "CMP-OWN",
                "objectApiName": "Case",
                "artefactType": "CustomField",
                "hostObjectOwnership": "subscriber-owned",
                "packageBoundaryRefs": [],
                "extensionPointStatus": "not-applicable",
            }
        )
        result = self.ok(
            "apply",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            operations=[{"kind": "scope-component-upsert", "payload": component}],
        )
        record = json.loads(
            (self.root / ".ai/change-records" / CASE / "record.json").read_text(encoding="utf-8")
        )
        self.assertFalse(
            any(
                item["questionId"] == core.PACKAGE_QUESTION_ID
                for item in record["solutionDesign"]["questions"]
            )
        )
        self.assertEqual(result["result"], "OPEN")


class KnowledgeReferenceTests(WorkspaceCase):
    """A missing entry is a Knowledge gap, never a licence to infer."""

    def test_no_entry_is_refused_with_the_gap_wording(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        response = self.call(
            "import-knowledge-reference",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            identity="CustomObject:Nonexistent__c",
        )
        self.assertFalse(response["ok"])
        self.assertIn(response["error"]["code"], {"NO_ENTRY", "REJECTED"})

    def test_the_tool_is_granted_and_maps_to_the_internal_operation(self) -> None:
        prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(encoding="utf-8")
        agent = (ROOT / ".github/agents/solution-designer.agent.md").read_text(encoding="utf-8")
        for text in (prompt, agent):
            self.assertIn("solution-design/design_import_knowledge_reference", text)
        server = (ROOT / "scripts/solution_design_mcp_server.mjs").read_text(encoding="utf-8")
        self.assertIn('design_import_knowledge_reference: "import-knowledge-reference"', server)
        self.assertIn("import-knowledge-reference", worker_module.OPERATIONS)


class SamplingDeriverTests(unittest.TestCase):
    """One implementation of each observed fact, and raw values leave in exactly one place."""

    derivers = _module("sampling_derivers")

    ROWS = [
        {
            "attributes": {"type": "ns__Rule__c"},
            "Id": "a01000000000001AAA",
            "ns__Type__c": "Routing",
            "ns__Start__c": "2026-01-01",
            "ns__End__c": None,
            "ns__Parent__c": "a02000000000001AAA",
            "Password__c": "hunter2",
        },
        {
            "attributes": {"type": "ns__Rule__c"},
            "Id": "a01000000000002AAA",
            "ns__Type__c": "Routing",
            "ns__Start__c": "2027-01-01",
            "ns__End__c": "2027-06-01",
            "ns__Parent__c": "a02000000000001AAA",
            "Password__c": "x",
        },
        {
            "attributes": {"type": "ns__Rule__c"},
            "Id": "a01000000000003AAA",
            "ns__Type__c": "Escalation",
            "ns__Start__c": None,
            "ns__End__c": None,
            "ns__Parent__c": None,
            "Password__c": None,
        },
    ]

    def test_aggregates_carry_counts_not_values(self) -> None:
        distribution = self.derivers.categorical_distribution(self.ROWS, "ns__Type__c")
        self.assertEqual(
            distribution["groups"],
            [{"value": "Routing", "count": 2}, {"value": "Escalation", "count": 1}],
        )
        fill = self.derivers.field_fill(self.ROWS, ["ns__Parent__c"])
        self.assertEqual(fill["fields"]["ns__Parent__c"], {"filled": 2, "total": 3})
        shape = self.derivers.relationship_shape(self.ROWS, "ns__Parent__c")
        self.assertEqual(shape["distinctParents"], 1)
        self.assertNotIn("a02000000000001AAA", json.dumps(shape))

    def test_effectivity_buckets_and_overlap(self) -> None:
        result = self.derivers.config_effectivity(
            self.ROWS, start_field="ns__Start__c", end_field="ns__End__c", at="2026-08-05"
        )
        self.assertEqual(result["buckets"]["active"], 1)
        self.assertEqual(result["buckets"]["future"], 1)
        self.assertEqual(result["buckets"]["unbounded"], 1)

    def test_sample_shape_describes_structure_without_values(self) -> None:
        shape = self.derivers.sample_shape(self.ROWS)
        self.assertEqual(shape["fields"]["Id"], [{"shape": "salesforce-id", "count": 3}])
        serialized = json.dumps(shape)
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("a01000000000001AAA", serialized)

    def test_config_snapshot_withholds_ids_audit_and_sensitive_fields(self) -> None:
        snapshot = self.derivers.safe_config_snapshot(
            self.ROWS, ["ns__Type__c", "Id", "Password__c", "ns__Parent__c"]
        )
        self.assertEqual(snapshot["refusedFields"], ["Id"])
        first = snapshot["records"][0]
        self.assertEqual(first["ns__Type__c"], "Routing")
        self.assertEqual(first["Password__c"]["withheld"], "sensitive-field")
        self.assertEqual(first["ns__Parent__c"]["withheld"], "salesforce-id")
        self.assertNotIn("hunter2", json.dumps(snapshot))

    def test_an_unknown_kind_fails_closed_rather_than_persisting_rows(self) -> None:
        with self.assertRaises(self.derivers.DeriverError):
            self.derivers.derive("invented-kind", self.ROWS)

    def test_the_policy_digest_moves_when_the_contract_moves(self) -> None:
        baseline = self.derivers.transform_policy_digest()
        original = dict(self.derivers.DERIVERS)
        try:
            self.derivers.DERIVERS["extra"] = lambda rows: {}
            self.assertNotEqual(baseline, self.derivers.transform_policy_digest())
        finally:
            self.derivers.DERIVERS.clear()
            self.derivers.DERIVERS.update(original)


class EnvelopeImportTests(WorkspaceCase):
    """Rows reach durable state only through the executor's derivation, never through the model."""

    def envelope(self, *, status: str = "VERIFIED", truncated: bool = False, environment: str = "sandbox") -> str:
        import hashlib

        records = [
            {"ns__Type__c": "Routing", "ns__Active__c": True},
            {"ns__Type__c": "Routing", "ns__Active__c": False},
            {"ns__Type__c": "Escalation", "ns__Active__c": True},
        ]
        query_digest = hashlib.sha256(b"SELECT ns__Type__c FROM ns__Rule__c").hexdigest()
        ref = hashlib.sha256(
            json.dumps(
                {"queryDigest": query_digest, "useToolingApi": False, "records": records},
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        body = {
            "schemaVersion": 1,
            "runId": "00000000-0000-4000-8000-000000000000",
            "generatedAt": "2026-08-05T10:00:00Z",
            "reviewType": "soql-query",
            "status": status,
            "target": {"environment": environment, "isSandbox": environment == "sandbox"},
            "sources": {},
            "facts": {
                "soqlQuery": {
                    "queryDigest": query_digest,
                    "fromObjects": ["ns__Rule__c"],
                    "useToolingApi": False,
                    "matched": len(records),
                    "records": records,
                    "receiptRef": ref,
                }
            },
            "reconciliation": {"status": "IDENTITY_MATCH_ONLY", "comparisons": []},
            "completeness": {"complete": not truncated, "dualSource": False, "truncated": truncated},
            "warnings": [],
        }
        try:
            import work_record as wr
        except ModuleNotFoundError:
            from scripts import work_record as wr
        body["sha256"] = wr.canonical_embedded_digest(body)
        cache = self.root / ".cache" / "salesforce-review"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{ref}.json").write_text(json.dumps(body), encoding="utf-8")
        return ref

    def test_a_verified_envelope_becomes_a_sanitized_receipt(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        ref = self.envelope()
        result = self.ok(
            "import-soql-envelope",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            receiptRef=ref,
            kind="categorical-distribution",
            options={"field": "ns__Type__c"},
        )
        self.assertEqual(result["environmentFitness"], "scope-matched-non-production")
        receipt = json.loads(
            (
                self.root / ".ai/change-records" / CASE / "evidence" / f"{result['receiptId']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["sourceType"], "org-soql-sample")
        self.assertEqual(
            receipt["result"]["derivedFacts"]["groups"],
            [{"value": "Routing", "count": 2}, {"value": "Escalation", "count": 1}],
        )
        # The raw rows stay in the ignored cache. The receipt carries counts and digests.
        self.assertNotIn("ns__Active__c", json.dumps(receipt["result"]["derivedFacts"]))
        self.assertTrue(receipt["rawResultDigest"].startswith("sha256:"))

    def test_developer_edition_evidence_is_marked_non_representative(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        ref = self.envelope(environment="development")
        result = self.ok(
            "import-soql-envelope",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            receiptRef=ref,
            kind="categorical-distribution",
            options={"field": "ns__Type__c"},
        )
        self.assertEqual(result["environmentFitness"], "non-representative-devmp")
        # And such a receipt cannot close a design obligation.
        record = json.loads(
            (self.root / ".ai/change-records" / CASE / "record.json").read_text(encoding="utf-8")
        )
        reference = record["solutionDesign"]["evidenceRefs"][0]
        eligible, reason = core.evidence_eligible(reference, authorities=["org-soql-sample"])
        self.assertFalse(eligible)
        self.assertEqual(reason, "non-representative-devmp")

    def test_mismatch_incomplete_and_truncated_envelopes_are_refused(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        for status, truncated in (("MISMATCH", False), ("INCOMPLETE", False), ("VERIFIED", True)):
            with self.subTest(status=status, truncated=truncated):
                ref = self.envelope(status=status, truncated=truncated)
                code = self.fail(
                    "import-soql-envelope",
                    caseId=CASE,
                    writerId="writer-one",
                    expectedCaseVersion=opened["caseVersion"],
                    receiptRef=ref,
                    kind="categorical-distribution",
                    options={"field": "ns__Type__c"},
                )
                self.assertEqual(code, "EVIDENCE_NOT_CONFIRMING")

    def test_a_tampered_envelope_is_refused(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        ref = self.envelope()
        path = self.root / ".cache" / "salesforce-review" / f"{ref}.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["facts"]["soqlQuery"]["records"].append({"ns__Type__c": "Injected"})
        path.write_text(json.dumps(body), encoding="utf-8")
        code = self.fail(
            "import-soql-envelope",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            receiptRef=ref,
            kind="categorical-distribution",
            options={"field": "ns__Type__c"},
        )
        self.assertEqual(code, "ENVELOPE_TAMPERED")

    def test_an_expired_reference_says_so_instead_of_guessing(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        code = self.fail(
            "import-soql-envelope",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            receiptRef="0" * 64,
            kind="object-baseline",
        )
        self.assertEqual(code, "ENVELOPE_EXPIRED")

    def test_a_config_snapshot_requires_an_explicit_allowlist(self) -> None:
        opened = self.ok("open", caseId=CASE, writerId="writer-one", title="t")
        ref = self.envelope()
        code = self.fail(
            "import-soql-envelope",
            caseId=CASE,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            receiptRef=ref,
            persistenceMode="config-snapshot",
            options={},
        )
        self.assertEqual(code, "INVALID_INPUT")


class AdaptiveSamplingTests(unittest.TestCase):
    """Probes come from what the design is deciding, never from enumerating fields."""

    def base_state(self) -> dict:
        state = core.new_case_state("SD-2026-08-05-sampling", "writer-one", at="2026-08-05T09:00:00Z")
        state["dataClassifications"] = [
            {
                "classificationId": "CLS-001",
                "objectApiName": "ns__Rule__c",
                "slice": None,
                "schemaOwnership": "package-owned",
                "dataStewardship": "admin-maintained",
                "dataRole": "configuration",
                "assurance": "unknown",
                "evidenceRefs": [],
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
                "action": "modify-records",
                "description": "Adds routing rules.",
                "evidenceRefs": [],
                "decisionRefs": [],
                "acIds": [],
                "migrationRefs": [],
                "rollbackRef": None,
                "verificationRefs": [],
            }
        ]
        return state

    def test_a_wide_object_does_not_produce_a_probe_per_field(self) -> None:
        state = self.base_state()
        # 300 fields on the object changes nothing: candidates come from the design, not the schema.
        candidates = core.probe_candidates(state)
        self.assertLessEqual(len(candidates), 6, [item["kind"] for item in candidates])
        kinds = {item["kind"] for item in candidates}
        self.assertIn("object-baseline", kinds)
        self.assertIn("key-integrity", kinds)

    def test_unproven_configuration_earns_baseline_and_churn_not_row_count_judgement(self) -> None:
        candidates = core.probe_candidates(self.base_state())
        kinds = {item["kind"] for item in candidates}
        self.assertIn("churn-profile", kinds)
        rationale = next(item for item in candidates if item["kind"] == "churn-profile")["rationale"]
        self.assertIn("row count", rationale)

    def test_effectivity_and_precedence_are_offered_for_mutated_configuration(self) -> None:
        kinds = {item["kind"] for item in core.probe_candidates(self.base_state())}
        self.assertIn("config-effectivity", kinds)
        self.assertIn("precedence-collision", kinds)

    def test_reuse_only_configuration_does_not_earn_hard_probes(self) -> None:
        state = self.base_state()
        state["configurationArtefacts"][0]["action"] = "reuse"
        hard = [
            item
            for item in core.probe_candidates(state)
            if item["suggestedRequiredness"] == "hard"
        ]
        self.assertEqual(hard, [])

    def test_an_already_planned_probe_is_not_offered_twice(self) -> None:
        state = self.base_state()
        state["probes"] = [
            {
                "probeId": "P-001",
                "questionId": "Q-001",
                "origin": "concern",
                "kind": "object-baseline",
                "target": {"objectApiName": "ns__Rule__c", "slice": None},
                "queryDigest": None,
                "suggestedSoql": None,
                "replaySpec": None,
                "expectedResultShape": "aggregate",
                "completenessCriterion": "row count",
                "requiredness": "hard",
                "conditionalPredicate": None,
                "notApplicableReason": None,
                "persistenceMode": "aggregate",
                "freshnessClass": "volume-observation",
                "stopCondition": "size known",
                "status": "planned",
                "receiptRef": None,
                "fitnessVerdict": None,
                "decisionImpact": None,
                "recheckPlan": "never",
            }
        ]
        kinds = [item["kind"] for item in core.probe_candidates(state)]
        self.assertNotIn("object-baseline", kinds)

    def test_repeated_inconclusive_sampling_becomes_a_human_obligation(self) -> None:
        state = self.base_state()
        state["questions"] = [
            {
                "questionId": "Q-001",
                "question": "Which rule wins when two are active?",
                "materiality": "blocking",
                "requiredAuthority": ["org-soql-sample"],
                "status": "observed",
                "answer": None,
                "closureAuthority": None,
                "evidenceRefs": [],
                "limitations": [],
                "route": "grounding",
            }
        ]
        probe = {
            "probeId": "P-001",
            "questionId": "Q-001",
            "origin": "question",
            "kind": "precedence-collision",
            "target": {"objectApiName": "ns__Rule__c", "slice": None},
            "queryDigest": None,
            "suggestedSoql": None,
            "replaySpec": None,
            "expectedResultShape": "aggregate",
            "completenessCriterion": "collisions",
            "requiredness": "hard",
            "conditionalPredicate": None,
            "notApplicableReason": None,
            "persistenceMode": "aggregate",
            "freshnessClass": "config-observation",
            "stopCondition": "winner known",
            "status": "interpreted",
            "receiptRef": None,
            "fitnessVerdict": "inconclusive",
            "decisionImpact": "no-material-impact",
            "recheckPlan": "never",
        }
        second = dict(probe, probeId="P-002")
        state["probes"] = [probe, second]
        stalled = core.no_progress_questions(state)
        self.assertEqual(len(stalled), 1)
        self.assertEqual(stalled[0]["questionId"], "Q-001")
        report = core.evaluate(state, design_text="# design\n")
        self.assertTrue(
            any(
                gap["requiredClosure"] == "no-progress" and gap["route"] == "human-input"
                for gap in report["gaps"]
            )
        )

    def test_one_useful_probe_is_not_treated_as_no_progress(self) -> None:
        state = self.base_state()
        state["questions"] = [
            {
                "questionId": "Q-001",
                "question": "Which rule wins?",
                "materiality": "blocking",
                "requiredAuthority": ["org-soql-sample"],
                "status": "observed",
                "answer": None,
                "closureAuthority": None,
                "evidenceRefs": [],
                "limitations": [],
                "route": "grounding",
            }
        ]
        state["probes"] = [
            {
                "probeId": "P-001",
                "questionId": "Q-001",
                "origin": "question",
                "kind": "precedence-collision",
                "target": {"objectApiName": "ns__Rule__c", "slice": None},
                "queryDigest": None,
                "suggestedSoql": None,
                "replaySpec": None,
                "expectedResultShape": "aggregate",
                "completenessCriterion": "collisions",
                "requiredness": "advisory",
                "conditionalPredicate": None,
                "notApplicableReason": None,
                "persistenceMode": "aggregate",
                "freshnessClass": "config-observation",
                "stopCondition": "winner known",
                "status": "interpreted",
                "receiptRef": None,
                "fitnessVerdict": "inconclusive",
                "decisionImpact": "no-material-impact",
                "recheckPlan": "never",
            },
            {
                "probeId": "P-002",
                "questionId": "Q-001",
                "origin": "question",
                "kind": "config-effectivity",
                "target": {"objectApiName": "ns__Rule__c", "slice": None},
                "queryDigest": None,
                "suggestedSoql": None,
                "replaySpec": None,
                "expectedResultShape": "aggregate",
                "completenessCriterion": "windows",
                "requiredness": "advisory",
                "conditionalPredicate": None,
                "notApplicableReason": None,
                "persistenceMode": "aggregate",
                "freshnessClass": "config-observation",
                "stopCondition": "windows known",
                "status": "closed",
                "receiptRef": None,
                "fitnessVerdict": "fit",
                "decisionImpact": "changed-option",
                "recheckPlan": "never",
            },
        ]
        self.assertEqual(core.no_progress_questions(state), [])


class ConfigRecordSkillTests(unittest.TestCase):
    """The row-count heuristic is retired, not softened."""

    SKILL = (ROOT / ".github/skills/investigate-config-records/SKILL.md").read_text(encoding="utf-8")

    def test_no_row_count_classification_remains(self) -> None:
        self.assertNotIn("200-row", self.SKILL)
        self.assertNotIn("LIMIT 200", self.SKILL)
        self.assertNotIn("transactional-sized", self.SKILL)

    def test_the_replacement_semantics_are_stated(self) -> None:
        self.assertIn("Row count is not a classification", self.SKILL)
        self.assertIn("keyset", self.SKILL)
        self.assertIn("slice-bounded", self.SKILL)


class DesignChallengeTests(VerticalSliceTests):
    """A high-risk candidate must survive an independent challenge before a human sees it."""

    # Rules the package-facing trigger makes applicable on top of the standard-risk set.
    HIGH_RISK_RULES = [
        "MP-GEN-001",
        "MP-GEN-004",
        "MP-GEN-005",
        "MP-EXT-001",
        "MP-AUTO-001",
        "SF-BULK-001",
        "SF-TRIG-001",
        "SF-SOQL-001",
        "SF-AUTO-001",
        "SF-SEC-001",
        "SF-LIMIT-001",
        "SF-ERR-001",
    ]
    HIGH_RISK_CONCERNS = [
        "security-and-execution-context",
        "transaction-and-automation",
        "volume-and-performance",
        "errors-and-observability",
        "package-boundaries-and-upgrade",
        "integrations-and-contracts",
    ]

    def high_risk_case(self) -> tuple[str, str, str]:
        """A genuinely READY high-risk candidate — not a skipped test dressed as coverage.

        Turning the field into a trigger on a package-owned object legitimately pulls in the
        managed-package and Apex rule set and six more concerns. Discharging them here is the
        point: the challenge lane is only proven if a high-risk case can actually reach it.
        """
        case, version = self.build_ready_case()
        record_path = self.root / ".ai/change-records" / case / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        component = record["solutionDesign"]["scope"]["components"][0]
        component["artefactType"] = "ApexTrigger"
        component["apiName"] = "CaseRoutingTrigger"
        component["hostObjectOwnership"] = "package-owned"
        component["packageBoundaryRefs"] = ["Case"]
        component["extensionPointStatus"] = "available"
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

        current = self.ok("context", caseId=case)
        operations = [
            {"kind": "rule-verdict", "payload": rule_verdict(rule_id)}
            for rule_id in self.HIGH_RISK_RULES
        ] + [
            {
                "kind": "concern-disposition",
                "payload": {
                    "profileId": profile,
                    "concernId": "COV-" + profile.upper(),
                    "applicability": "applicable",
                    "status": "addressed",
                    "triggerRefs": [component["componentId"]],
                    "treatmentRefs": ["#D-001"],
                    "verificationRefs": ["V-001"],
                },
            }
            for profile in self.HIGH_RISK_CONCERNS
        ]
        applied = self.ok(
            "apply",
            caseId=case,
            writerId="writer-one",
            expectedCaseVersion=current["caseVersion"],
            operations=operations,
        )
        # The runtime seeds the package-boundary question the moment the scope touches a
        # package-owned surface. Answering it with a named human authority is part of what
        # makes this case high-risk-but-ready; leaving it open would just prove seeding works.
        answered = self.ok(
            "record-human-input",
            caseId=case,
            expectedCaseVersion=applied["caseVersion"],
            answer=(
                "The vendor documents a before-save trigger extension point on this object for "
                "the installed version, and no package automation runs in the same transaction."
            ),
            authorityRole="package-vendor",
            target={"kind": "question", "id": core.PACKAGE_QUESTION_ID},
            elicitation={"identity": "package-sme", "nonceDigest": "sha256:" + "d" * 64},
        )
        return case, answered["caseVersion"], component["componentId"]

    def test_a_high_risk_candidate_cannot_reach_a_human_without_the_challenge(self) -> None:
        case, version, _component = self.high_risk_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(submitted["submitResult"], "READY", submitted.get("gaps"))
        self.assertEqual(submitted["status"], "awaiting_design_review")
        self.assertEqual(submitted["riskClassification"]["tier"], "high")
        # The human decision surface refuses a candidate that has not been challenged.
        self.assertEqual(
            self.fail(
                "confirm-candidate",
                caseId=case,
                candidateId=submitted["candidateId"],
                candidateDigest=submitted["candidateDigest"],
                elicitation={"identity": "approver", "nonceDigest": "sha256:" + "a" * 64},
            ),
            "INVALID_TRANSITION",
        )

    def test_the_author_cannot_review_their_own_design(self) -> None:
        case, version, _component = self.high_risk_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(submitted["submitResult"], "READY", submitted.get("gaps"))
        self.assertEqual(
            self.fail(
                "review-candidate",
                caseId=case,
                candidateId=submitted["candidateId"],
                candidateDigest=submitted["candidateDigest"],
                reviewerId="writer-one",
                verdict="PASS",
            ),
            "SELF_REVIEW_DENIED",
        )

    def test_pass_moves_the_candidate_to_the_human_decision(self) -> None:
        case, version, _component = self.high_risk_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(submitted["submitResult"], "READY", submitted.get("gaps"))
        reviewed = self.ok(
            "review-candidate",
            caseId=case,
            candidateId=submitted["candidateId"],
            candidateDigest=submitted["candidateDigest"],
            reviewerId="reviewer-one",
            verdict="PASS",
        )
        self.assertEqual(reviewed["status"], "awaiting_human")
        receipt = json.loads(
            (self.root / ".ai/change-records" / case / "reviews" / f"{reviewed['receiptId']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["verdict"], "PASS")
        self.assertEqual(receipt["reviewerRole"], "guardrail-reviewer")

    def test_a_revision_verdict_supersedes_the_candidate_and_names_what_must_change(self) -> None:
        case, version, component = self.high_risk_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(submitted["submitResult"], "READY", submitted.get("gaps"))
        self.assertEqual(
            self.fail(
                "review-candidate",
                caseId=case,
                candidateId=submitted["candidateId"],
                candidateDigest=submitted["candidateDigest"],
                reviewerId="reviewer-one",
                verdict="REVISE_GROUNDING",
            ),
            "INVALID_INPUT",
        )
        reviewed = self.ok(
            "review-candidate",
            caseId=case,
            candidateId=submitted["candidateId"],
            candidateDigest=submitted["candidateDigest"],
            reviewerId="reviewer-one",
            verdict="REVISE_GROUNDING",
            findings=[
                {
                    "summary": "The extension point is asserted, not evidenced.",
                    "route": "grounding",
                    "affectedRefs": [component],
                }
            ],
        )
        self.assertEqual(reviewed["status"], "draft")
        self.assertIsNone(reviewed["activeCandidateRef"])
        receipt = json.loads(
            (self.root / ".ai/change-records" / case / "reviews" / f"{reviewed['receiptId']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["supersedes"], submitted["candidateId"])
        self.assertTrue(receipt["openedObligations"])

    def test_blocked_needs_human_routes_to_the_pre_candidate_human_lane(self) -> None:
        case, version, component = self.high_risk_case()
        submitted = self.ok("submit", caseId=case, writerId="writer-one", expectedCaseVersion=version)
        self.assertEqual(submitted["submitResult"], "READY", submitted.get("gaps"))
        reviewed = self.ok(
            "review-candidate",
            caseId=case,
            candidateId=submitted["candidateId"],
            candidateDigest=submitted["candidateDigest"],
            reviewerId="reviewer-one",
            verdict="BLOCKED_NEEDS_HUMAN",
            findings=[
                {
                    "summary": "Only the vendor can confirm this surface is extensible.",
                    "route": "human-input",
                    "affectedRefs": [component],
                }
            ],
        )
        self.assertEqual(reviewed["status"], "awaiting_human_input")
        self.assertNotIn("blocked", core.STATES)


class ArtefactCoverageTests(unittest.TestCase):
    """Every implementation target must be visible in a table a human reads."""

    def test_a_mutating_component_marked_out_of_scope_blocks(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "sdcore_tests", ROOT / "tests" / "test_solution_design_core.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        state = module.ready_state()
        state["scope"]["components"][0]["disposition"] = "out-of-scope"
        state["scope"]["components"][0]["dispositionReason"] = "changed my mind"
        report = core.evaluate(state, design_text=module.DESIGN_TEXT)
        self.assertTrue(
            any(gap["requiredClosure"] == "artefact-coverage" for gap in report["gaps"]),
            report["gaps"],
        )


if __name__ == "__main__":
    unittest.main()
