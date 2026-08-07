#!/usr/bin/env python3
"""Solution Design loop worker: the four-operation mutating runtime.

NDJSON frames on stdin/stdout, one JSON object per line: {"id", "op", "params"} →
{"id", "ok", "result"|"error"}. Operations: `open`, `record`, `check`, `submit` — the whole
public surface (rebuild plan §3). `record` never refuses content: incomplete payloads are
recorded with annotations, subjects without discovery results yield `ungrounded` plan items,
and every unmet condition becomes design content. The single hard gate is `submit`
(invariants + candidate digest + human confirmation relayed by the MCP server).

Persistence is the case tree under .ai/change-records/<case-id>/ via governed_state's
lease + atomic pair commit — unchanged from the previous runtime (the part of it that was
right). record.json stays a schema-valid work record whose `solutionDesign` key is the loop
state: work_record.py owns everything downstream of acceptance (H3), and this worker never
writes a handoff.
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
except ModuleNotFoundError:  # imported as scripts.* by unit tests
    from scripts import governed_state as gs
    from scripts import solution_design_core as core


HARNESS_ROOT = Path(__file__).resolve().parents[1]
MAX_FRAME_BYTES = 4_000_000
CASES_DIRECTORY = ".ai/change-records"
RUNTIME_DIRECTORY = ".ai/.runtime/solution-design"
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
# Case storage (lease + atomic pair commit, carried over)
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

    def load(self, case_id: str) -> dict[str, Any]:
        gs.recover(self.runtime_root, self.directory(case_id))
        record_path = self.record_path(case_id)
        if not record_path.is_file():
            raise WorkerError("CASE_NOT_FOUND", f"no Design Case at {case_id}")
        return json.loads(record_path.read_text(encoding="utf-8"))

    def state_version(self, record: dict[str, Any]) -> str:
        state = record["solutionDesign"]
        return core.state_version(state["stateSequence"], state)

    def commit(self, case_id: str, record: dict[str, Any], design: str, *, lease: gs.Lease) -> None:
        record["updatedAt"] = utc_now()
        payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        gs.commit_pair(
            self.runtime_root,
            self.directory(case_id),
            [(self.record_path(case_id), payload),
             (self.design_path(case_id), design.encode("utf-8"))],
            lease=lease,
        )

    def write_json(self, case_id: str, relative: str, value: dict[str, Any]) -> Path:
        path = gs.contained_path(self.root, f"{CASES_DIRECTORY}/{case_id}/{relative}")
        payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        temporary = gs.write_temp(path, payload)
        gs.replace_with_retry(temporary, path)
        return path


def empty_change_record(case_id: str, title: str, at: str) -> dict[str, Any]:
    """A schema-valid work record whose Design Case state is the authority. Every legacy
    field is present at its neutral value so the record validates, and none of them is a
    second place to look for design state."""
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
        self.triggers = core.load_rule_triggers()
        self.loop_config = core.load_loop_config()

    def _render(self, state: dict[str, Any]) -> str:
        return core.render_design(state, state.get("prose") or {})

    # -- open --------------------------------------------------------------------------

    def op_open(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params.get("caseId") or ""
        title = params.get("title") or case_id
        source = params.get("source") or {}
        if source.get("kind") not in ("ado", "text"):
            raise WorkerError("INVALID_INPUT", "source.kind must be 'ado' or 'text'")
        if self.store.exists(case_id):
            record = self.store.load(case_id)
            state = record["solutionDesign"]
            return {
                "outcome": "REOPENED",
                "caseId": case_id,
                "stateVersion": self.store.state_version(record),
                "phase": state["phase"],
                "status": state["status"],
                "proposedSubjects": state.get("proposedSubjects", []),
            }
        requirement_text = source.get("text") or ""
        subjects = core.derive_subjects(f"{title}\n{requirement_text}")
        at = utc_now()
        record = empty_change_record(case_id, title, at)
        record["solutionDesign"] = core.new_state(
            case_id,
            {
                "kind": source["kind"],
                "itemId": source.get("itemId"),
                # ADO unreachable degrades to an unverified intake, never a refusal (§2).
                "verified": bool(source.get("verified")),
            },
            subjects,
        )
        if requirement_text:
            record["solutionDesign"]["requirementText"] = core.normalize_document(requirement_text)
        design = self._render(record["solutionDesign"])
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            self.store.commit(case_id, record, design, lease=lease)
        return {
            "outcome": "OPENED",
            "caseId": case_id,
            "stateVersion": self.store.state_version(record),
            "phase": "intake",
            "sourceVerified": bool(source.get("verified")),
            "proposedSubjects": subjects,
            "note": "confirm or extend the subject list via record(intake, {subjects}); "
                    "the confirmed list is what discovery-per-subject is measured against",
        }

    # -- record ------------------------------------------------------------------------

    def op_record(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params.get("caseId") or ""
        phase = params.get("phase") or ""
        payload = params.get("payload")
        if not isinstance(payload, dict):
            raise WorkerError("INVALID_INPUT", "payload must be an object")
        record = self.store.load(case_id)
        expected = params.get("stateVersion")
        current = self.store.state_version(record)
        if expected is not None and expected != current:
            # Concurrency safety, not advice: a stale writer must reload, or two writers
            # silently overwrite each other. This is the only non-submit error with teeth.
            raise WorkerError("STALE_STATE_VERSION", f"state moved (current {current}); reload and retry")
        state = core.record_payload(record["solutionDesign"], phase, payload)
        result: dict[str, Any] = {"outcome": "RECORDED", "phase": phase}
        if phase in ("verify", "iterate"):
            gap_ids = {gap["id"] for gap in core.verify_gaps(state, self.triggers)}
            state = core.update_iteration(state, gap_ids, int(self.loop_config["iterationCap"]))
            result["iteration"] = state["iteration"]
            if state["status"] == "blocked":
                result["outcome"] = "BLOCKED"
                result["unresolved"] = state["blocked"]["unresolved"]
        record["solutionDesign"] = state
        design = self._render(state)
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            self.store.commit(case_id, record, design, lease=lease)
        result["stateVersion"] = self.store.state_version(record)
        annotations = state.get("annotations", [])
        if annotations:
            result["annotations"] = annotations[-3:]
        return result

    # -- check -------------------------------------------------------------------------

    def op_check(self, params: dict[str, Any]) -> dict[str, Any]:
        record = self.store.load(params.get("caseId") or "")
        state = record["solutionDesign"]
        report = core.render_check(state, self.triggers)
        report["stateVersion"] = self.store.state_version(record)
        return report

    # -- submit: the single hard gate ---------------------------------------------------

    def op_submit(self, params: dict[str, Any]) -> dict[str, Any]:
        case_id = params.get("caseId") or ""
        stage = params.get("stage") or "prepare"
        record = self.store.load(case_id)
        state = record["solutionDesign"]

        if stage == "prepare":
            blockers = core.submit_blockers(state, self.triggers)
            if blockers:
                return {"outcome": "BLOCKED", "blockers": blockers}
            design = self._render(state)
            digest = core.narrative_digest(design)
            candidate_id = identifier("CAND")
            self.store.write_json(case_id, f"candidates/{candidate_id}/bundle.json", {
                "candidateId": candidate_id,
                "narrativeDigest": digest,
                "stateVersion": self.store.state_version(record),
                "preparedAt": utc_now(),
            })
            candidate_path = gs.contained_path(
                self.store.root, f"{CASES_DIRECTORY}/{case_id}/candidates/{candidate_id}/design.md"
            )
            temporary = gs.write_temp(candidate_path, design.encode("utf-8"))
            gs.replace_with_retry(temporary, candidate_path)
            state["candidate"] = {"id": candidate_id, "narrativeDigest": digest}
            record["solutionDesign"] = state
            with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
                self.store.commit(case_id, record, design, lease=lease)
            return {
                "outcome": "AWAITING_HUMAN",
                "candidateId": candidate_id,
                "narrativeDigest": digest,
            }

        if stage == "confirm":
            confirmation = params.get("confirmation") or {}
            answer = str(confirmation.get("answer") or "")
            reviewer = confirmation.get("reviewer")
            candidate = state.get("candidate")
            if not candidate:
                raise WorkerError("NO_CANDIDATE", "submit(prepare) has not produced a candidate")
            if confirmation.get("decision") == "revise":
                state["candidate"] = None
                record["solutionDesign"] = state
                with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
                    self.store.commit(case_id, record, self._render(state), lease=lease)
                return {"outcome": "REVISION_REQUESTED"}
            classification = core.classify_answer(answer)
            if classification == "non-answer":
                return {"outcome": "NOT_AN_ANSWER",
                        "note": "an empty or placeholder reply does not close the approval"}
            if classification == "delegated":
                # Run-242050 defect (§6): a reply that hands the decision back is NOT
                # human-attested evidence. It returns as an agent decision that needs its
                # own explicit acknowledgement.
                decision_id = identifier("AD")
                state["agentDecisions"].append({
                    "id": decision_id,
                    "question": f"approve candidate {candidate['id']} ({candidate['narrativeDigest'][:23]}…)?",
                    "humanReply": answer,
                    "status": "awaiting-acknowledgement",
                })
                record["solutionDesign"] = state
                with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
                    self.store.commit(case_id, record, self._render(state), lease=lease)
                return {
                    "outcome": "DELEGATED_BACK",
                    "agentDecisionId": decision_id,
                    "note": "the reply delegates the decision back; state the agent's own "
                            "decision and obtain a separate explicit acknowledgement "
                            "(submit stage=acknowledge)",
                }
            return self._approve(case_id, record, state, reviewer, answer,
                                 mechanism="human-candidate-confirmation")

        if stage == "acknowledge":
            acknowledgement = params.get("acknowledgement") or {}
            decision_id = acknowledgement.get("agentDecisionId")
            answer = str(acknowledgement.get("answer") or "")
            reviewer = acknowledgement.get("reviewer")
            pending = next(
                (d for d in state.get("agentDecisions", [])
                 if d["id"] == decision_id and d["status"] == "awaiting-acknowledgement"),
                None,
            )
            if pending is None:
                raise WorkerError("NO_PENDING_DECISION", f"no agent decision awaiting acknowledgement: {decision_id}")
            classification = core.classify_answer(answer)
            if classification != "complete":
                return {"outcome": "NOT_AN_ANSWER",
                        "note": "the acknowledgement must itself be an explicit answer"}
            pending["status"] = "acknowledged"
            pending["acknowledgedBy"] = reviewer
            return self._approve(case_id, record, state, reviewer, answer,
                                 mechanism="agent-decision-acknowledged")

        raise WorkerError("INVALID_INPUT", "stage must be prepare|confirm|acknowledge")

    def _approve(self, case_id: str, record: dict[str, Any], state: dict[str, Any],
                 reviewer: Any, answer: str, *, mechanism: str) -> dict[str, Any]:
        if not reviewer:
            raise WorkerError("INVALID_INPUT", "a reviewer identity is required to approve")
        candidate = state["candidate"]
        approval_id = identifier("AP")
        self.store.write_json(case_id, f"approvals/{approval_id}.json", {
            "approvalId": approval_id,
            "candidateId": candidate["id"],
            "narrativeDigest": candidate["narrativeDigest"],
            "reviewer": reviewer,
            "answer": answer,
            "mechanism": mechanism,
            "decidedAt": utc_now(),
        })
        state["status"] = "submitted"
        record["state"] = {"phase": "design", "status": "accepted"}
        record["design"]["sha256"] = candidate["narrativeDigest"].split(":", 1)[1]
        record["solutionDesign"] = state
        with gs.Lease.acquire(self.store.runtime_root, self.store.directory(case_id)) as lease:
            self.store.commit(case_id, record, self._render(state), lease=lease)
        return {
            "outcome": "APPROVED",
            "approvalId": approval_id,
            "candidateId": candidate["id"],
            "narrativeDigest": candidate["narrativeDigest"],
            "mechanism": mechanism,
        }


# --------------------------------------------------------------------------------------
# NDJSON loop
# --------------------------------------------------------------------------------------

OPERATIONS = {
    "open": "op_open",
    "record": "op_record",
    "check": "op_check",
    "submit": "op_submit",
}


def handle(worker: Worker, frame: dict[str, Any]) -> dict[str, Any]:
    request_id = frame.get("id")
    operation = frame.get("op")
    if operation not in OPERATIONS:
        return {"id": request_id, "ok": False,
                "error": {"code": "UNKNOWN_OPERATION", "message": f"unknown operation {operation!r}"}}
    params = frame.get("params")
    if not isinstance(params, dict):
        return {"id": request_id, "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "params must be an object"}}
    try:
        result = getattr(worker, OPERATIONS[operation])(params)
        return {"id": request_id, "ok": True, "result": result}
    except WorkerError as exc:
        return {"id": request_id, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except gs.LeaseUnavailable as exc:
        return {"id": request_id, "ok": False, "error": {"code": "CASE_BUSY", "message": str(exc)}}
    except (core.SolutionDesignError, gs.GovernedStateError) as exc:
        return {"id": request_id, "ok": False, "error": {"code": "REJECTED", "message": str(exc)}}
    except Exception as exc:  # never let one bad frame kill the worker
        print(f"solution-design worker: unexpected failure: {exc!r}", file=sys.stderr)
        return {"id": request_id, "ok": False,
                "error": {"code": "INTERNAL", "message": "the operation failed; see stderr"}}


def serve(stdin: Any, stdout: Any, root: Path) -> None:
    worker = Worker(root)
    for line in stdin:
        raw = line.strip()
        if not raw:
            continue
        if len(raw) > MAX_FRAME_BYTES:
            response = {"id": None, "ok": False,
                        "error": {"code": "FRAME_TOO_LARGE", "message": "request frame exceeds the bound"}}
        else:
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                frame = None
            if not isinstance(frame, dict):
                response = {"id": None, "ok": False,
                            "error": {"code": "MALFORMED_FRAME", "message": "each line must be one JSON object"}}
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
