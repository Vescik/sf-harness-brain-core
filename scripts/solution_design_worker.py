#!/usr/bin/env python3
"""Internal mutating Design Case worker. Newline-delimited JSON in, one frame out.

This process is not a human command surface and has no argparse verbs. The Node MCP wrapper
owns exactly one of these and serializes every case mutation through it; the public CLI
(`solution_design.py`) is read-only and cannot reach any operation here.

Invariants this file exists to hold:

* one response frame per request, and **nothing else on stdout** — diagnostics go to stderr;
* malformed or oversized frames fail closed with a typed error, never a partial mutation;
* every mutation of an existing case proves `expectedCaseVersion`, holds the case lease, and
  re-checks both the lease and the on-disk document digest immediately before commit;
* `record.json` and `design.md` are replaced as one journalled pair;
* the model can request a human-bound operation but can never author its result: the three
  `*-human` operations require an elicitation response the wrapper obtained from VS Code.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import governed_state as gs
    import solution_design_core as core
    from repository_evidence_adapter import RepositoryEvidenceError, capture
except ModuleNotFoundError:  # imported as scripts.solution_design_worker by unit tests
    from scripts import governed_state as gs
    from scripts import solution_design_core as core
    from scripts.repository_evidence_adapter import RepositoryEvidenceError, capture


HARNESS_ROOT = Path(__file__).resolve().parents[1]
MAX_FRAME_BYTES = 4_000_000
CASES_DIRECTORY = ".ai/change-records"
RUNTIME_DIRECTORY = ".ai/.runtime/solution-design"
EVIDENCE_TRANSFORM_VERSION = 1
CASE_ID = re.compile(
    r"^(ADO-[a-z0-9][a-z0-9-]{0,62}-[1-9][0-9]*|SD-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]{0,40})$"
)


class WorkerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def identifier(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------------------
# Case storage
# --------------------------------------------------------------------------------------


class CaseStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        gs.assert_path_budget(self.root)
        self.runtime_root = self.root / RUNTIME_DIRECTORY

    def directory(self, case_id: str) -> Path:
        if not CASE_ID.match(case_id or ""):
            raise WorkerError(
                "INVALID_CASE_ID",
                "case id must be ADO-<project-slug>-<item-id> or SD-<yyyy-mm-dd>-<slug>",
            )
        return gs.contained_path(self.root, f"{CASES_DIRECTORY}/{case_id}")

    def record_path(self, case_id: str) -> Path:
        return self.directory(case_id) / "record.json"

    def design_path(self, case_id: str) -> Path:
        return self.directory(case_id) / "design.md"

    def exists(self, case_id: str) -> bool:
        return self.record_path(case_id).is_file()

    def load(self, case_id: str) -> tuple[dict[str, Any], str]:
        gs.recover(self.runtime_root, self.directory(case_id))
        record_path = self.record_path(case_id)
        if not record_path.is_file():
            raise WorkerError("CASE_NOT_FOUND", f"no Design Case at {case_id}")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        design = self.design_path(case_id).read_text(encoding="utf-8")
        return record, core.normalize_document(design)

    def case_version(self, record: dict[str, Any], design: str) -> str:
        state = record["solutionDesign"]
        return core.case_version(state["stateSequence"], state, core.text_digest(design))

    def commit(
        self,
        case_id: str,
        record: dict[str, Any],
        design: str,
        *,
        lease: gs.Lease,
        expected_design_digest: str | None,
    ) -> None:
        """Write the record/document pair atomically, re-checking the document immediately first."""
        design_path = self.design_path(case_id)
        if expected_design_digest is not None and design_path.is_file():
            current = core.text_digest(design_path.read_text(encoding="utf-8"))
            if current != expected_design_digest:
                raise WorkerError(
                    "STALE_CASE_VERSION",
                    "design.md changed on disk while this operation was computing; reload and retry",
                )
        record["updatedAt"] = utc_now()
        payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        gs.commit_pair(
            self.runtime_root,
            self.directory(case_id),
            [(self.record_path(case_id), payload), (design_path, design.encode("utf-8"))],
            lease=lease,
        )

    def write_json(self, case_id: str, relative: str, value: dict[str, Any]) -> Path:
        path = gs.contained_path(self.root, f"{CASES_DIRECTORY}/{case_id}/{relative}")
        payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        temporary = gs.write_temp(path, payload)
        gs.replace_with_retry(temporary, path)
        return path


def empty_change_record(case_id: str, title: str, at: str) -> dict[str, Any]:
    """A schema-valid change record whose Design Case state is the authority.

    Every legacy field is present at its neutral value so the record validates, and none of
    them is a second place to look for design state.
    """
    return {
        "schemaVersion": 1,
        "recordId": case_id,
        "recordRevision": 1,
        "createdAt": at,
        "updatedAt": at,
        "workItem": None,
        "state": {"phase": "design", "status": "draft"},
        "requestedOutcome": title,
        "scope": {"workspaceRoot": "brain-core", "components": [], "paths": []},
        "scopeHash": core.sd_digest({"components": [], "paths": []}).split(":", 1)[1],
        "groundingHash": core.sd_digest({"grounding": []}).split(":", 1)[1],
        "environment": {
            "status": "unverified",
            "alias": None,
            "isSandbox": None,
            "nonProduction": None,
            "verificationRef": None,
            "verifiedAt": None,
        },
        "ruleRefs": [],
        "contextRefs": [],
        "assumptions": [],
        "unknowns": [],
        "blockingQuestions": [],
        "design": {"path": "design.md", "sha256": "0" * 64},
        "approvals": [],
        "evidenceRefs": [],
        "implementation": {"status": "not_started", "components": [], "commits": []},
        "verification": [],
        "review": {"status": "not_started", "verdict": None, "reviewer": None, "recordedAt": None},
        "repositories": [],
        "currentHandoffId": None,
        "handoffHistoryRefs": [],
        "events": [],
    }


# --------------------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------------------


class Worker:
    def __init__(self, root: Path) -> None:
        self.store = CaseStore(root)
        self.capabilities = core.load_capabilities()
        self.rule_map = core.load_rule_map()
        self.definitions = core.canonical_rule_definitions()

    # -- helpers ---------------------------------------------------------------------

    def _evaluate(self, record: dict[str, Any], design: str) -> dict[str, Any]:
        return core.evaluate(
            record["solutionDesign"],
            design_text=design,
            capabilities=self.capabilities,
            rule_map=self.rule_map,
            definitions=self.definitions,
        )

    def _require_writer(self, record: dict[str, Any], writer_id: str | None) -> None:
        assigned = record["solutionDesign"]["writerAssignment"]["writerId"]
        if writer_id is None:
            raise WorkerError("WRITER_REQUIRED", "a writer identity is required to mutate a case")
        if writer_id != assigned:
            raise WorkerError(
                "WRONG_WRITER",
                f"{assigned} owns this case; a second writer cannot mutate it. Transfer is explicit.",
            )

    def _require_version(self, record: dict[str, Any], design: str, expected: str | None) -> None:
        current = self.store.case_version(record, design)
        if expected != current:
            raise WorkerError(
                "STALE_CASE_VERSION",
                f"expectedCaseVersion does not match the current case; reload. current={current}",
            )

    def _summary(self, case_id: str, record: dict[str, Any], design: str) -> dict[str, Any]:
        state = record["solutionDesign"]
        report = self._evaluate(record, design)
        return {
            "caseId": case_id,
            "caseVersion": self.store.case_version(record, design),
            "status": state["status"],
            "nextFocus": report["nextFocus"],
            "writer": state["writerAssignment"],
            "result": report["result"],
            "openObligations": report["gaps"],
            "applicableConcerns": report["applicableConcerns"],
            "riskClassification": report["riskClassification"],
            "activeCandidateRef": state["activeCandidateRef"],
        }

    def _render_and_commit(
        self,
        case_id: str,
        record: dict[str, Any],
        design: str,
        *,
        lease: gs.Lease,
        expected_design_digest: str,
    ) -> tuple[dict[str, Any], str]:
        rendered = core.render_generated_sections(design, record["solutionDesign"])
        record["solutionDesign"]["nextFocus"] = self._evaluate(record, rendered)["nextFocus"]
        record["design"]["sha256"] = core.text_digest(rendered).split(":", 1)[1]
        record["recordRevision"] = record["recordRevision"] + 1
        self.store.commit(
            case_id, record, rendered, lease=lease, expected_design_digest=expected_design_digest
        )
        return record, rendered

    # -- op: open --------------------------------------------------------------------

    def op_open(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params.get("caseId")
        if not isinstance(case_id, str) or not case_id:
            raise WorkerError("INVALID_INPUT", "caseId is required")
        writer_id = params.get("writerId")
        if not isinstance(writer_id, str) or not writer_id:
            raise WorkerError("INVALID_INPUT", "writerId is required")

        if self.store.exists(case_id):
            record, design = self.store.load(case_id)
            if params.get("expectedCaseVersion") is None:
                # Resume is read-only: it may report drift but never persists a refresh.
                summary = self._summary(case_id, record, design)
                summary["mode"] = "resumed-read-only"
                return summary
            with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
                record, design = self.store.load(case_id)
                self._require_writer(record, writer_id)
                self._require_version(record, design, params["expectedCaseVersion"])
                record, design = self._render_and_commit(
                    case_id,
                    record,
                    design,
                    lease=lease,
                    expected_design_digest=core.text_digest(design),
                )
            summary = self._summary(case_id, record, design)
            summary["mode"] = "refreshed"
            return summary

        at = utc_now()
        directory = self.store.directory(case_id)
        if directory.exists():
            raise WorkerError("CASE_PATH_TAKEN", f"{case_id} already has a directory without a record")
        with gs.Lease.acquire(self.store.runtime_root, directory) as lease:
            if self.store.exists(case_id):  # lost the creation race
                raise WorkerError("CASE_EXISTS", f"{case_id} was created concurrently; reload")
            state = core.new_case_state(case_id, writer_id, at=at)
            title = params.get("title") or case_id
            if params.get("orRequirement"):
                state["requirementSnapshot"]["completeness"] = "partial"
                state["requirementSnapshot"]["retrievedAt"] = at
                state["requirementSnapshot"]["sourceDigest"] = core.sd_digest(
                    {"intake": params["orRequirement"]}
                )
            record = empty_change_record(case_id, title, at)
            record["solutionDesign"] = state
            design = core.design_scaffold(case_id, title, state)
            record["design"]["sha256"] = core.text_digest(design).split(":", 1)[1]
            self.store.commit(case_id, record, design, lease=lease, expected_design_digest=None)
        summary = self._summary(case_id, record, design)
        summary["mode"] = "created"
        return summary

    # -- op: context / check ---------------------------------------------------------

    def op_context(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        record, design = self.store.load(case_id)
        summary = self._summary(case_id, record, design)
        view = params.get("view") or "summary"
        state = record["solutionDesign"]
        if view in ("grounding", "all"):
            summary["questions"] = state["questions"]
            summary["probes"] = state["probes"]
            summary["evidence"] = state["evidenceRefs"]
        if view in ("decisions", "all"):
            summary["decisions"] = state["decisions"]
            summary["scope"] = state["scope"]
            summary["configurationArtefacts"] = state["configurationArtefacts"]
            summary["dataClassifications"] = state["dataClassifications"]
            summary["riskObligations"] = state["riskObligations"]
            summary["applicableRules"] = state["applicableRules"]
        if view in ("verification", "all"):
            summary["verificationContract"] = state["verificationContract"]
            summary["requirementSnapshot"] = state["requirementSnapshot"]
        summary["concernCoverage"] = state["concernCoverage"]
        return summary

    def op_check(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        record, design = self.store.load(case_id)
        report = self._evaluate(record, design)
        return {
            "caseId": case_id,
            "caseVersion": self.store.case_version(record, design),
            "result": report["result"],
            "gaps": report["gaps"],
            "nextFocus": report["nextFocus"],
            "riskClassification": report["riskClassification"],
            "gateEvaluatorVersion": report["gateEvaluatorVersion"],
            "capabilityManifestDigest": report["capabilityManifestDigest"],
        }

    # -- op: apply -------------------------------------------------------------------

    def op_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        operations = params.get("operations")
        if not isinstance(operations, list):
            raise WorkerError("INVALID_INPUT", "operations must be a list")
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            self._require_writer(record, params.get("writerId"))
            self._require_version(record, design, params.get("expectedCaseVersion"))
            try:
                record["solutionDesign"] = core.apply_operations(
                    record["solutionDesign"], operations
                )
            except core.SolutionDesignError as exc:
                raise WorkerError("OPERATION_REJECTED", str(exc)) from exc
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        return self._summary(case_id, record, design)

    # -- op: evidence import ---------------------------------------------------------

    def op_import_repository_receipt(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            self._require_writer(record, params.get("writerId"))
            self._require_version(record, design, params.get("expectedCaseVersion"))
            try:
                facts = capture(
                    self.store.root,
                    params.get("commit", ""),
                    params.get("path", ""),
                    first_line=params.get("firstLine"),
                    last_line=params.get("lastLine"),
                )
            except RepositoryEvidenceError as exc:
                raise WorkerError("REPOSITORY_EVIDENCE_REFUSED", str(exc)) from exc
            receipt_id = identifier("EV")
            at = utc_now()
            receipt = {
                "schemaVersion": 1,
                "receiptId": receipt_id,
                "caseId": case_id,
                "questionId": params.get("questionId"),
                "probeId": params.get("probeId"),
                "sourceType": "repository-receipt",
                "assurance": "source-exact",
                "validationPurpose": "design-evidence",
                "environmentFitness": "not-environment-bound",
                "org": None,
                "package": None,
                "query": None,
                "source": {
                    "kind": "git-blob",
                    "identity": facts["repositoryIdentity"],
                    "revision": facts["commit"],
                    "path": facts["path"],
                    "blobOid": facts["blobOid"],
                    "range": facts["range"],
                    "contentDigest": facts["contentDigest"],
                    "coverage": facts["coverage"],
                    "workingTreeDrift": facts["workingTreeDrift"],
                },
                "human": None,
                "observedAt": at,
                "expiresAt": None,
                "result": {
                    "kind": "repository-source",
                    "completeness": "complete" if facts["coverage"] == "full" else "slice-bounded",
                    "derivedFacts": {
                        "lineCount": facts["lineCount"],
                        "byteSize": facts["byteSize"],
                        "mode": facts["mode"],
                    },
                },
                "transform": {
                    "version": EVIDENCE_TRANSFORM_VERSION,
                    "policyDigest": core.sd_digest({"transform": "repository-source", "version": 1}),
                },
                "rawResultDigest": facts["blobDigest"],
                "sensitivityClass": "non-sensitive",
                "limitations": (
                    ["The working tree differs from this commit; the receipt describes the commit, not the workspace."]
                    if facts["workingTreeDrift"]
                    else []
                ),
                "sha256": "sha256:" + "0" * 64,
            }
            receipt["sha256"] = core.sd_digest(
                {key: value for key, value in receipt.items() if key != "sha256"}
            )
            core.validate_against(receipt, core.EVIDENCE_SCHEMA, "repository evidence receipt")
            self.store.write_json(case_id, f"evidence/{receipt_id}.json", receipt)
            reference = {
                "receiptId": receipt_id,
                "path": f"evidence/{receipt_id}.json",
                "sha256": receipt["sha256"],
                "sourceType": "repository-receipt",
                "assurance": "source-exact",
                "validationPurpose": "design-evidence",
                "environmentFitness": "not-environment-bound",
                "observedAt": at,
                "expiresAt": None,
                "completeness": receipt["result"]["completeness"],
                "status": "current",
                "questionRefs": [params["questionId"]] if params.get("questionId") else [],
                "probeRefs": [params["probeId"]] if params.get("probeId") else [],
            }
            operation = {
                "kind": "repository-source-receipt-import",
                "executorAuthored": True,
                "payload": {"evidenceRef": reference},
            }
            record["solutionDesign"] = core.apply_operations(record["solutionDesign"], [operation])
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, design)
        summary["receiptId"] = receipt_id
        summary["workingTreeDrift"] = facts["workingTreeDrift"]
        return summary

    # -- op: submit ------------------------------------------------------------------

    def op_submit(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            self._require_writer(record, params.get("writerId"))
            self._require_version(record, design, params.get("expectedCaseVersion"))
            state = record["solutionDesign"]
            if state["status"] not in ("draft", "awaiting_human_input"):
                raise WorkerError("INVALID_TRANSITION", f"cannot submit from {state['status']}")
            # Render every generated section in memory first, so the candidate and the working
            # copy are hashed from identical final bytes.
            rendered = core.render_generated_sections(design, state)
            report = self._evaluate(record, rendered)
            if report["result"] != "READY":
                if core.human_only_blockers(report["gaps"]):
                    state["status"] = "awaiting_human_input"
                state["nextFocus"] = report["nextFocus"]
                state["stateSequence"] += 1
                record, design = self._render_and_commit(
                    case_id,
                    record,
                    design,
                    lease=lease,
                    expected_design_digest=core.text_digest(design),
                )
                summary = self._summary(case_id, record, design)
                summary["submitResult"] = report["result"]
                summary["gaps"] = report["gaps"]
                return summary

            candidate_id = identifier("CND")
            design_digest = core.text_digest(rendered)
            parent_version = self.store.case_version(record, design)
            policy = core.applicable_policy_snapshot(
                state, self.rule_map, self.definitions, report["applicableConcerns"]
            )
            digest_input = {
                "bundleSchemaVersion": 1,
                "gateEvaluatorVersion": report["gateEvaluatorVersion"],
                "capabilityManifestDigest": report["capabilityManifestDigest"],
                "caseId": case_id,
                "candidateId": candidate_id,
                "submittedFromCaseVersion": parent_version,
                "requirementSnapshot": state["requirementSnapshot"],
                "designDigest": design_digest,
                "structuredStateSnapshot": state,
                "evidenceManifest": [
                    {
                        "receiptId": item["receiptId"],
                        "sha256": item["sha256"],
                        "sourceType": item["sourceType"],
                        "completeness": item["completeness"],
                        "observedAt": item["observedAt"],
                        "expiresAt": item["expiresAt"],
                    }
                    for item in state["evidenceRefs"]
                ],
                "applicablePolicySnapshot": policy,
                "verificationContract": state["verificationContract"],
                "sourceRefs": [],
                "orgPackageFingerprints": [],
                "gateReport": {"result": report["result"], "gaps": report["gaps"]},
                "riskClassification": report["riskClassification"],
                "authorWriterAssignment": state["writerAssignment"],
                "concernCoverage": state["concernCoverage"],
                "knownLimitations": state["limitationRefs"],
                "acceptedRiskReceiptRefs": sorted(
                    {
                        risk["acceptedRiskReceiptRef"]
                        for risk in state["riskObligations"]
                        if risk.get("acceptedRiskReceiptRef")
                    }
                ),
                "recheckPlan": [
                    {
                        "probeId": probe["probeId"],
                        "trigger": probe["recheckPlan"],
                        "replayable": bool((probe.get("replaySpec") or {}).get("replayable")),
                    }
                    for probe in state["probes"]
                    if probe["recheckPlan"] not in ("never",)
                ],
            }
            bundle = {
                "schemaVersion": 1,
                "candidateId": candidate_id,
                "caseId": case_id,
                "createdAt": utc_now(),
                "candidateDigest": core.candidate_digest(digest_input),
                "candidateDigestInput": digest_input,
                "supersededAt": None,
                "supersededReason": None,
            }
            core.validate_against(bundle, core.CANDIDATE_SCHEMA, "candidate bundle")
            self.store.write_json(case_id, f"candidates/{candidate_id}/bundle.json", bundle)
            snapshot = gs.contained_path(
                self.store.root, f"{CASES_DIRECTORY}/{case_id}/candidates/{candidate_id}/design.md"
            )
            gs.replace_with_retry(gs.write_temp(snapshot, rendered.encode("utf-8")), snapshot)

            tier = report["riskClassification"]["tier"]
            state["status"] = "awaiting_design_review" if tier == "high" else "awaiting_human"
            state["activeCandidateRef"] = {
                "candidateId": candidate_id,
                "candidateDigest": bundle["candidateDigest"],
                "createdAt": bundle["createdAt"],
                "submittedFromCaseVersion": parent_version,
                "status": "in-design-review" if tier == "high" else "awaiting-human",
            }
            state["stateSequence"] += 1
            record["state"] = {"phase": "design", "status": "awaiting_human"}
            record["design"]["sha256"] = design_digest.split(":", 1)[1]
            record["recordRevision"] += 1
            self.store.commit(
                case_id, record, rendered, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, rendered)
        summary["submitResult"] = "READY"
        summary["candidateId"] = candidate_id
        summary["candidateDigest"] = bundle["candidateDigest"]
        return summary

    # -- human-bound operations ------------------------------------------------------

    def _human_block(self, params: dict[str, Any]) -> dict[str, Any]:
        """Only the wrapper may supply this: it is the VS Code elicitation response envelope."""
        block = params.get("elicitation")
        if not isinstance(block, dict):
            raise WorkerError(
                "HUMAN_RESPONSE_REQUIRED",
                "this operation requires a native VS Code elicitation response",
            )
        identity = block.get("identity")
        nonce_digest = block.get("nonceDigest")
        if not identity or not nonce_digest:
            raise WorkerError("HUMAN_RESPONSE_REQUIRED", "the elicitation response is incomplete")
        return {
            "identity": identity,
            "mechanism": "vscode-mcp-elicitation-v1",
            "elicitationNonceDigest": nonce_digest,
            "identityAssurance": "named-user-assertion",
        }

    def _write_receipt(self, case_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        receipt["sha256"] = core.sd_digest(
            {key: value for key, value in receipt.items() if key != "sha256"}
        )
        core.validate_against(receipt, core.RECEIPT_SCHEMA, "transition receipt")
        folder = {"AP": "approvals", "DR": "reviews", "HO": "handoffs"}[receipt["receiptId"][:2]]
        self.store.write_json(case_id, f"{folder}/{receipt['receiptId']}.json", receipt)
        return receipt

    def op_record_human_input(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        human = self._human_block(params)
        answer = params.get("answer")
        if not answer:
            raise WorkerError("INVALID_INPUT", "an answer is required")
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            self._require_version(record, design, params.get("expectedCaseVersion"))
            state = record["solutionDesign"]
            if state["status"] not in ("draft", "awaiting_human_input"):
                raise WorkerError(
                    "INVALID_TRANSITION",
                    "human input is pre-candidate: it cannot be introduced after submit",
                )
            receipt_id = identifier("EV")
            at = utc_now()
            receipt = {
                "schemaVersion": 1,
                "receiptId": receipt_id,
                "caseId": case_id,
                "questionId": params.get("target", {}).get("id")
                if params.get("target", {}).get("kind") == "question"
                else None,
                "probeId": None,
                "sourceType": params.get("sourceType", "human-sme-attestation"),
                "assurance": "human-asserted",
                "validationPurpose": "design-evidence",
                "environmentFitness": "not-environment-bound",
                "org": None,
                "package": None,
                "query": None,
                "source": None,
                "human": {
                    "identity": human["identity"],
                    "authorityRole": params.get("authorityRole", "subject-matter-expert"),
                    "mechanism": "vscode-mcp-elicitation-v1",
                    "applicabilityScope": params.get("applicabilityScope"),
                    "effectiveAt": at,
                },
                "observedAt": at,
                "expiresAt": params.get("expiresAt"),
                "result": {
                    "kind": "human-answer",
                    "completeness": "complete",
                    "derivedFacts": {"answer": answer},
                },
                "transform": {
                    "version": EVIDENCE_TRANSFORM_VERSION,
                    "policyDigest": core.sd_digest({"transform": "human-answer", "version": 1}),
                },
                "rawResultDigest": None,
                "sensitivityClass": "non-sensitive",
                "limitations": params.get("limitations") or [],
                "sha256": "sha256:" + "0" * 64,
            }
            receipt["sha256"] = core.sd_digest(
                {key: value for key, value in receipt.items() if key != "sha256"}
            )
            core.validate_against(receipt, core.EVIDENCE_SCHEMA, "human evidence receipt")
            self.store.write_json(case_id, f"evidence/{receipt_id}.json", receipt)
            reference = {
                "receiptId": receipt_id,
                "path": f"evidence/{receipt_id}.json",
                "sha256": receipt["sha256"],
                "sourceType": receipt["sourceType"],
                "assurance": "human-asserted",
                "validationPurpose": "design-evidence",
                "environmentFitness": "not-environment-bound",
                "observedAt": at,
                "expiresAt": params.get("expiresAt"),
                "completeness": "complete",
                "status": "current",
                "questionRefs": [receipt["questionId"]] if receipt["questionId"] else [],
                "probeRefs": [],
            }
            record["solutionDesign"] = core.apply_operations(
                state,
                [
                    {
                        "kind": "human-answer-link",
                        "executorAuthored": True,
                        "payload": {
                            "evidenceRef": reference,
                            "target": params.get("target") or {},
                            "answer": answer,
                        },
                    }
                ],
            )
            record["solutionDesign"]["status"] = "draft"
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, design)
        summary["receiptId"] = receipt_id
        return summary

    def op_confirm_candidate(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._candidate_decision(params, approve=True)

    def op_request_candidate_revision(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._candidate_decision(params, approve=False)

    def _candidate_decision(self, params: dict[str, Any], *, approve: bool) -> dict[str, Any]:
        case_id = params["caseId"]
        human = self._human_block(params)
        reason = params.get("reason")
        if not approve and not reason:
            raise WorkerError("INVALID_INPUT", "a revision request requires a human reason")
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            state = record["solutionDesign"]
            active = state.get("activeCandidateRef")
            if not active:
                raise WorkerError("NO_CANDIDATE", "this case has no candidate awaiting a decision")
            if state["status"] != "awaiting_human":
                raise WorkerError(
                    "INVALID_TRANSITION",
                    f"a candidate in {state['status']} is not awaiting a human decision",
                )
            if params.get("candidateId") != active["candidateId"] or params.get(
                "candidateDigest"
            ) != active["candidateDigest"]:
                raise WorkerError(
                    "CANDIDATE_MISMATCH",
                    "the decision names a different candidate identity or digest",
                )
            if human["identity"] == state["writerAssignment"]["writerId"]:
                raise WorkerError(
                    "SELF_APPROVAL_DENIED",
                    "the case writer cannot approve their own candidate",
                )
            receipt = {
                "schemaVersion": 1,
                "receiptId": identifier("AP"),
                "kind": "candidate-approval" if approve else "candidate-revision-request",
                "caseId": case_id,
                "recordedAt": utc_now(),
                "caseVersionAtCommit": self.store.case_version(record, design),
                "candidateId": active["candidateId"],
                "candidateDigest": active["candidateDigest"],
                "human": human,
                "reason": reason,
                "verdict": None,
                "reviewerRole": None,
                "findings": [],
                "writerTransfer": None,
                "handoff": None,
                "supersedes": None if approve else active["candidateId"],
                "openedObligations": [] if approve else ["human-requested-revision"],
                "sha256": "sha256:" + "0" * 64,
            }
            self._write_receipt(case_id, receipt)
            if approve:
                state["status"] = "accepted"
                active["status"] = "accepted"
                record["state"] = {"phase": "design", "status": "accepted"}
            else:
                state["status"] = "draft"
                state["activeCandidateRef"] = None
                record["state"] = {"phase": "design", "status": "draft"}
            state["stateSequence"] += 1
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, design)
        summary["decision"] = "approved" if approve else "revision-requested"
        summary["receiptId"] = receipt["receiptId"]
        return summary

    def op_transfer_case_writer(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        human = self._human_block(params)
        target = params.get("targetWriterId")
        if not target:
            raise WorkerError("INVALID_INPUT", "targetWriterId is required")
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            self._require_version(record, design, params.get("expectedCaseVersion"))
            state = record["solutionDesign"]
            if state["status"] == "complete":
                raise WorkerError("INVALID_TRANSITION", "a completed case has no writer to transfer")
            assignment = state["writerAssignment"]
            if human["identity"] != assignment["writerId"]:
                raise WorkerError(
                    "WRONG_WRITER", "only the current owner may transfer this case"
                )
            receipt = {
                "schemaVersion": 1,
                "receiptId": identifier("AP"),
                "kind": "writer-transfer",
                "caseId": case_id,
                "recordedAt": utc_now(),
                "caseVersionAtCommit": self.store.case_version(record, design),
                "candidateId": None,
                "candidateDigest": None,
                "human": human,
                "reason": params.get("reason"),
                "verdict": None,
                "reviewerRole": None,
                "findings": [],
                "writerTransfer": {
                    "fromWriterId": assignment["writerId"],
                    "toWriterId": target,
                    "assignmentSequence": assignment["assignmentSequence"] + 1,
                },
                "handoff": None,
                "supersedes": None,
                "openedObligations": [],
                "sha256": "sha256:" + "0" * 64,
            }
            self._write_receipt(case_id, receipt)
            state["writerAssignment"] = {
                "writerId": target,
                "assignedAt": receipt["recordedAt"],
                "assignmentSequence": assignment["assignmentSequence"] + 1,
                "transferReceiptRef": receipt["receiptId"],
            }
            state["stateSequence"] += 1
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, design)
        summary["receiptId"] = receipt["receiptId"]
        return summary

    def op_start_development(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params["caseId"]
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            record, design = self.store.load(case_id)
            state = record["solutionDesign"]
            if state["status"] != "accepted":
                raise WorkerError(
                    "INVALID_TRANSITION", f"development starts from accepted, not {state['status']}"
                )
            active = state["activeCandidateRef"]
            bundle_path = gs.contained_path(
                self.store.root,
                f"{CASES_DIRECTORY}/{case_id}/candidates/{active['candidateId']}/bundle.json",
            )
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            if bundle["candidateDigest"] != active["candidateDigest"]:
                raise WorkerError("CANDIDATE_MISMATCH", "the stored candidate digest changed")
            report = self._evaluate(record, design)
            if report["capabilityManifestDigest"] != bundle["candidateDigestInput"][
                "capabilityManifestDigest"
            ] or report["gateEvaluatorVersion"] != bundle["candidateDigestInput"][
                "gateEvaluatorVersion"
            ]:
                raise WorkerError(
                    "EVALUATOR_MIGRATION",
                    "the capability manifest or gate evaluator changed materially since approval; "
                    "the candidate must be recomputed before development",
                )
            digest_input = bundle["candidateDigestInput"]
            receipt = {
                "schemaVersion": 1,
                "receiptId": identifier("HO"),
                "kind": "development-handoff",
                "caseId": case_id,
                "recordedAt": utc_now(),
                "caseVersionAtCommit": self.store.case_version(record, design),
                "candidateId": active["candidateId"],
                "candidateDigest": active["candidateDigest"],
                "human": None,
                "reason": None,
                "verdict": None,
                "reviewerRole": None,
                "findings": [],
                "writerTransfer": None,
                "handoff": {
                    "toRole": "development-assistant",
                    "allowedScope": digest_input["structuredStateSnapshot"]["scope"]["components"]
                    + digest_input["structuredStateSnapshot"]["configurationArtefacts"],
                    "verificationContract": digest_input["verificationContract"],
                    "recheckPlan": digest_input["recheckPlan"],
                    "risksAndLimitations": digest_input["structuredStateSnapshot"][
                        "riskObligations"
                    ]
                    + digest_input["knownLimitations"],
                    "repositoryBaseline": None,
                    "requiredReads": [
                        f"{CASES_DIRECTORY}/{case_id}/candidates/{active['candidateId']}/design.md",
                        f"{CASES_DIRECTORY}/{case_id}/candidates/{active['candidateId']}/bundle.json",
                    ],
                    "prohibitedActions": [
                        "no org mutation, deploy or activation",
                        "no design edit; a material divergence is reported, not absorbed",
                        "no scope beyond the accepted candidate",
                    ],
                },
                "supersedes": None,
                "openedObligations": [],
                "sha256": "sha256:" + "0" * 64,
            }
            self._write_receipt(case_id, receipt)
            state["status"] = "development"
            state["stateSequence"] += 1
            record["state"] = {"phase": "development", "status": "in_progress"}
            record["currentHandoffId"] = receipt["receiptId"]
            record, design = self._render_and_commit(
                case_id, record, design, lease=lease, expected_design_digest=core.text_digest(design)
            )
        summary = self._summary(case_id, record, design)
        summary["handoffId"] = receipt["receiptId"]
        return summary


OPERATIONS = {
    "open": "op_open",
    "context": "op_context",
    "check": "op_check",
    "apply": "op_apply",
    "submit": "op_submit",
    "import-repository-receipt": "op_import_repository_receipt",
    "record-human-input": "op_record_human_input",
    "confirm-candidate": "op_confirm_candidate",
    "request-candidate-revision": "op_request_candidate_revision",
    "transfer-case-writer": "op_transfer_case_writer",
    "start-development": "op_start_development",
}


def handle(worker: Worker, frame: dict[str, Any]) -> dict[str, Any]:
    request_id = frame.get("id")
    operation = frame.get("op")
    if operation not in OPERATIONS:
        return {
            "id": request_id,
            "ok": False,
            "error": {"code": "UNKNOWN_OPERATION", "message": f"unknown operation {operation!r}"},
        }
    params = frame.get("params")
    if not isinstance(params, dict):
        return {
            "id": request_id,
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "params must be an object"},
        }
    try:
        result = getattr(worker, OPERATIONS[operation])(params)
        return {"id": request_id, "ok": True, "result": result}
    except WorkerError as exc:
        return {"id": request_id, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except gs.LeaseUnavailable as exc:
        return {"id": request_id, "ok": False, "error": {"code": "CASE_BUSY", "message": str(exc)}}
    except (core.SolutionDesignError, gs.GovernedStateError, RepositoryEvidenceError) as exc:
        return {"id": request_id, "ok": False, "error": {"code": "REJECTED", "message": str(exc)}}
    except Exception as exc:  # never let one bad frame kill the worker
        print(f"solution-design worker: unexpected failure: {exc!r}", file=sys.stderr)
        return {
            "id": request_id,
            "ok": False,
            "error": {"code": "INTERNAL", "message": "the operation failed; see stderr"},
        }


def serve(stdin: Any, stdout: Any, root: Path) -> None:
    worker = Worker(root)
    for line in stdin:
        raw = line.strip()
        if not raw:
            continue
        if len(raw) > MAX_FRAME_BYTES:
            response = {
                "id": None,
                "ok": False,
                "error": {"code": "FRAME_TOO_LARGE", "message": "request frame exceeds the bound"},
            }
        else:
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                frame = None
            if not isinstance(frame, dict):
                response = {
                    "id": None,
                    "ok": False,
                    "error": {"code": "MALFORMED_FRAME", "message": "each line must be one JSON object"},
                }
            else:
                response = handle(worker, frame)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


def main() -> int:
    root = Path(os.environ.get("SD_WORKSPACE_ROOT") or HARNESS_ROOT)
    serve(sys.stdin, sys.stdout, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
