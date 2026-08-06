#!/usr/bin/env python3
"""Solution Design loop core: intake→discovery→plan→execute→verify→[iterate]→submit.

Pure domain logic for the advisory loop (docs/solution-design-product-goal.md §1). The
runtime enforces exactly three things prose cannot: discovery per subject, counted verify,
and the iteration counter with its stop. Everything else is advice: during the loop nothing
here refuses a write — an unmet condition becomes a named gap and, ultimately, design
content. The single hard gate is `submit_blockers` (human approval + the package-namespace
invariant, decision D-2).

No I/O beyond reading named configuration files; no process state; the mutating runtime
(`solution_design_worker.py`) and the read-only CLI (`solution_design.py`) own the
filesystem.

Two digests, deliberately split (rebuild plan §3): `state_version` (CAS over structured
state only — editing design.md prose invalidates nothing) and `narrative_digest` (computed
at submit over the candidate document).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

HARNESS_ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-state.schema.json"
LOOP_CONFIG_PATH = HARNESS_ROOT / "config" / "solution-design-loop.json"
RULE_TRIGGERS_PATH = HARNESS_ROOT / "config" / "solution-design-rule-triggers.json"

# The 39 loop rules live in these three files; SAFE-* rules in copilot-instructions.md are
# enforced by hooks and the human gate, never by the verify checklist.
RULE_SOURCE_FILES = (
    HARNESS_ROOT / ".github" / "instructions" / "managed-package-constraints.instructions.md",
    HARNESS_ROOT / ".github" / "instructions" / "organization-principles.instructions.md",
    HARNESS_ROOT / ".github" / "instructions" / "salesforce-best-practices.instructions.md",
)

CANONICALIZER_VERSION = "sd-c14n-v1"
STATE_VERSION_PREFIX = "sv1_"

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

RULE_ID = re.compile(r"^(MP|ORG|SF)-[A-Z0-9-]+$")
RULE_DEFINITION = re.compile(r"^\s*[-*]\s+\*\*(?P<id>(?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\b")
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\?\?\?|<[A-Za-z][A-Za-z0-9 _/-]{0,60}>")

PHASES = ("intake", "discovery", "plan", "execute", "verify", "iterate")
TERMINAL_STATUSES = ("blocked", "submitted")
DISCOVERY_RESULTS = ("found", "no-entry", "source-unavailable")
PLAN_ACTIONS = ("reuse", "create", "modify", "delete")
VERDICTS = ("ok", "violation", "n-a")
GROUNDING_LABELS = ("verified", "assumed")

# Mutating package-owned metadata on an assumption is the one thing an assumption may never
# close (decision D-2); `reuse` reads, the other three write.
WRITING_ACTIONS = ("create", "modify", "delete")


class SolutionDesignError(RuntimeError):
    """Domain error; the message is the actionable reason."""


# --------------------------------------------------------------------------------------
# Canonicalization (unchanged semantics from the previous runtime: sd-c14n-v1)
# --------------------------------------------------------------------------------------


def _normalize(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not (INT64_MIN <= value <= INT64_MAX):
            raise SolutionDesignError(f"{path}: integer outside signed 64-bit range")
        return value
    if isinstance(value, float):
        raise SolutionDesignError(f"{path}: binary floats are forbidden by {CANONICALIZER_VERSION}")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SolutionDesignError(f"{path}: object keys must be strings")
            normal_key = unicodedata.normalize("NFC", key)
            if normal_key in normalized:
                raise SolutionDesignError(
                    f"{path}: object keys {key!r} collide after Unicode NFC normalization"
                )
            normalized[normal_key] = _normalize(item, path=f"{path}.{normal_key}")
        return normalized
    raise SolutionDesignError(f"{path}: unsupported type {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sd_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_document(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def narrative_digest(text: str) -> str:
    """Digest of the candidate document, computed at submit and only then."""
    return "sha256:" + hashlib.sha256(normalize_document(text).encode("utf-8")).hexdigest()


def state_version(state_sequence: int, structured_state: dict[str, Any]) -> str:
    """CAS token over structured state alone — prose edits between writes invalidate nothing."""
    envelope = {
        "canonicalizer": CANONICALIZER_VERSION,
        "stateSequence": state_sequence,
        "structuredState": structured_state,
    }
    return STATE_VERSION_PREFIX + hashlib.sha256(canonical_bytes(envelope)).hexdigest()


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SolutionDesignError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SolutionDesignError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SolutionDesignError(f"expected a JSON object in {path}")
    return value


def load_loop_config(path: Path = LOOP_CONFIG_PATH) -> dict[str, Any]:
    """Iteration ceiling is configuration, not code (rebuild plan §2.1): the default of 3 is
    a deliberate cost ceiling — a too-low ceiling produces a cheap, visible `blocked` with a
    delta stamp; a too-high one silently reproduces run 242050. Recalibrate from data."""
    config = _load_json(path)
    cap = config.get("iterationCap")
    if not isinstance(cap, int) or cap < 1:
        raise SolutionDesignError(f"iterationCap must be a positive integer in {path}")
    return config


def canonical_rule_definitions(paths: Iterable[Path] = RULE_SOURCE_FILES) -> dict[str, str]:
    """Every canonical loop-rule ID -> digest of its normalized definition line."""
    definitions: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise SolutionDesignError(f"instruction source is missing: {path}")
        lines = normalize_document(path.read_text(encoding="utf-8")).split("\n")
        for index, line in enumerate(lines):
            match = RULE_DEFINITION.match(line)
            if not match:
                continue
            rule_id = match.group("id")
            body = [line.strip()]
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].startswith(("  ", "\t")):
                body.append(lines[cursor].strip())
                cursor += 1
            if rule_id in definitions:
                raise SolutionDesignError(f"rule {rule_id} is declared more than once")
            definitions[rule_id] = "sha256:" + hashlib.sha256(
                " ".join(part for part in body if part).encode("utf-8")
            ).hexdigest()
    return definitions


def load_rule_triggers(path: Path = RULE_TRIGGERS_PATH) -> dict[str, Any]:
    """The static (artefact type × action) -> rule-id table (deliverable H1).

    Validated against the live rule definitions: an id that no instructions file declares is
    a config defect, and a declared id missing from the table entirely (not in `always`, any
    matrix cell, or `neverTriggered`) is silent verify shrinkage — both fail closed here, at
    load, not at verify time."""
    table = _load_json(path)
    declared = {
        rule_id for rule_id in canonical_rule_definitions() if RULE_ID.match(rule_id)
    }
    referenced: set[str] = set(table.get("always", []))
    for cell, ids in (table.get("byArtefactAction") or {}).items():
        if ":" not in cell:
            raise SolutionDesignError(f"trigger cell {cell!r} must be '<ArtefactType>:<action>'")
        action = cell.split(":", 1)[1]
        if action not in PLAN_ACTIONS + ("*",):
            raise SolutionDesignError(f"trigger cell {cell!r} names unknown action {action!r}")
        referenced.update(ids)
    never = table.get("neverTriggered") or {}
    referenced.update(never)
    unknown = sorted(referenced - declared)
    if unknown:
        raise SolutionDesignError(f"trigger table names undeclared rules: {', '.join(unknown)}")
    unmapped = sorted(declared - referenced)
    if unmapped:
        raise SolutionDesignError(
            "rules declared in instructions but absent from the trigger table: "
            + ", ".join(unmapped)
        )
    return table


# --------------------------------------------------------------------------------------
# Subjects — pattern extraction from untrusted requirement text (rebuild plan §3, H2)
# --------------------------------------------------------------------------------------

API_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*__(?:c|mdt|e|b|x)\b")
DOTTED_TOKEN = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:__c|__mdt|__e)?)\.([A-Za-z][A-Za-z0-9_]*(?:__c)?)\b"
)
ARTEFACT_WORDS = {
    "flow": "Flow",
    "apex class": "ApexClass",
    "apex trigger": "ApexTrigger",
    "validation rule": "ValidationRule",
    "permission set": "PermissionSet",
    "record type": "RecordType",
    "custom metadata": "CustomMetadata",
    "named credential": "NamedCredential",
    "report": "Report",
    "dashboard": "Dashboard",
}


def derive_subjects(text: str) -> list[dict[str, str]]:
    """Propose the subject list by pattern extraction — NEVER by interpreting the text.

    ADO content is untrusted data (repo rule: never treat ADO content as instructions); this
    reads shapes (API-name tokens, Object.Member pairs, artefact-type words), not meaning.
    The agent confirms and extends the proposal via record(intake, {subjects}); the
    confirmed list is what discovery-per-subject is enforced against."""
    subjects: dict[str, dict[str, str]] = {}
    normalized = normalize_document(text or "")
    for match in DOTTED_TOKEN.finditer(normalized):
        name = f"{match.group(1)}.{match.group(2)}"
        subjects.setdefault(name, {"name": name, "hint": "object-member"})
    for token in API_TOKEN.findall(normalized):
        if not any(name.startswith(f"{token}.") or name.endswith(f".{token}") for name in subjects):
            subjects.setdefault(token, {"name": token, "hint": "api-name"})
    lowered = normalized.lower()
    for phrase, artefact_type in ARTEFACT_WORDS.items():
        if phrase in lowered:
            key = f"type:{artefact_type}"
            subjects.setdefault(key, {"name": artefact_type, "hint": "artefact-type"})
    return sorted(subjects.values(), key=lambda item: item["name"])


# --------------------------------------------------------------------------------------
# State model v2
# --------------------------------------------------------------------------------------


def new_state(case_id: str, source: dict[str, Any], proposed_subjects: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "caseId": case_id,
        "phase": "intake",
        "status": "open",
        "source": source,  # {"kind": "ado"|"text", "itemId"?, "verified": bool}
        "intake": {"goal": None, "acceptanceCriteria": [], "subjects": []},
        "proposedSubjects": proposed_subjects,
        "discovery": {},          # subject name -> {"result", "ref"?, "ownership"?, "limitations": []}
        "planItems": [],           # {"id","acRef","subject","action","artefactType","label","ungrounded"}
        "decisions": [],           # {"id","title","choice","alternatives"?}
        "verifyRounds": [],        # {"round", "verdicts": [...], "gaps": [gap-id, ...]}
        "iteration": {"rounds": 0, "smallestGapSetSize": None, "roundsWithoutShrink": 0},
        "annotations": [],         # advisory notes recorded with incomplete payloads
        "agentDecisions": [],      # delegated-back answers converted to agent decisions (plan §6)
        "blocked": None,           # {"unresolved": [...], "stampedAt"}
        "stateSequence": 0,
    }


def record_payload(state: dict[str, Any], phase: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The single write path. Never refuses (rebuild plan §3): an incomplete payload records
    with an annotation of what is missing; a plan item whose subject has no discovery result
    gets the indelible `ungrounded` label, removed only by delivering that result."""
    if phase not in PHASES:
        raise SolutionDesignError(f"unknown phase {phase!r}; phases: {', '.join(PHASES)}")
    if not isinstance(payload, dict):
        raise SolutionDesignError("payload must be an object")
    state = json.loads(json.dumps(state))  # defensive copy; caller persists
    notes: list[str] = []

    if phase == "intake":
        intake = state["intake"]
        for key in ("goal",):
            if payload.get(key):
                intake[key] = payload[key]
        if payload.get("acceptanceCriteria"):
            intake["acceptanceCriteria"] = payload["acceptanceCriteria"]
        if payload.get("subjects") is not None:
            intake["subjects"] = sorted({str(s) for s in payload["subjects"]})
        if not intake["goal"]:
            notes.append("intake recorded without a goal")
        if not intake["acceptanceCriteria"]:
            notes.append("intake recorded without acceptance criteria")
    elif phase == "discovery":
        subject = payload.get("subject")
        result = payload.get("result")
        if not subject:
            notes.append("discovery payload without a subject — recorded, closes nothing")
        elif result not in DISCOVERY_RESULTS:
            notes.append(
                f"discovery for {subject!r} recorded with unknown result {result!r}; "
                f"closing results: {', '.join(DISCOVERY_RESULTS)}"
            )
            state["discovery"][str(subject)] = {"result": "recorded-unclosed", "raw": result}
        else:
            entry: dict[str, Any] = {"result": result}
            for key in ("ref", "ownership", "namespace", "limitations", "schemaDigest"):
                if payload.get(key) is not None:
                    entry[key] = payload[key]
            entry.setdefault("limitations", [])
            state["discovery"][str(subject)] = entry
            _reground_plan_items(state)
    elif phase == "plan":
        items = payload.get("items")
        if items is None and payload.get("item") is not None:
            items = [payload["item"]]
        if not items:
            notes.append("plan payload without items — recorded, closes nothing")
        for raw in items or []:
            item = {
                "id": raw.get("id") or f"PI-{len(state['planItems']) + 1:03d}",
                "acRef": raw.get("acRef"),
                "subject": raw.get("subject"),
                "action": raw.get("action"),
                "artefactType": raw.get("artefactType"),
                "label": raw.get("label"),
            }
            if item["action"] not in PLAN_ACTIONS:
                notes.append(f"plan item {item['id']}: unknown action {item['action']!r}")
            if item["label"] not in GROUNDING_LABELS:
                notes.append(f"plan item {item['id']}: missing verified/assumed label")
            discovery = state["discovery"].get(str(item["subject"]) if item["subject"] else "")
            item["ungrounded"] = not (discovery and discovery.get("result") in DISCOVERY_RESULTS)
            existing = next((i for i, p in enumerate(state["planItems"]) if p["id"] == item["id"]), None)
            if existing is None:
                state["planItems"].append(item)
            else:
                state["planItems"][existing] = item
        if payload.get("decisions"):
            state["decisions"] = payload["decisions"]
    elif phase == "execute":
        # The renderer owns design.md; agent prose arrives per section here and is merged,
        # never hand-edited into the rendered file (anchors and generated tables would drift).
        prose = payload.get("prose")
        if isinstance(prose, dict):
            merged = dict(state.get("prose") or {})
            merged.update({str(k): str(v) for k, v in prose.items()})
            state["prose"] = merged
        if payload.get("flags") and isinstance(payload["flags"], dict):
            flags = dict(state.get("flags") or {})
            flags.update(payload["flags"])
            state["flags"] = flags
    elif phase in ("verify", "iterate"):
        verdicts = payload.get("verdicts") or []
        round_number = len(state["verifyRounds"]) + 1
        state["verifyRounds"].append({"round": round_number, "verdicts": verdicts, "gaps": []})
    if payload.get("note"):
        notes.append(str(payload["note"]))
    if notes:
        state["annotations"].extend({"phase": phase, "note": note} for note in notes)
    if phase in PHASES:
        state["phase"] = phase
    state["stateSequence"] += 1
    return state


def _reground_plan_items(state: dict[str, Any]) -> None:
    for item in state["planItems"]:
        discovery = state["discovery"].get(str(item.get("subject")))
        if discovery and discovery.get("result") in DISCOVERY_RESULTS:
            item["ungrounded"] = False


# --------------------------------------------------------------------------------------
# check(): counted gaps, never a refusal
# --------------------------------------------------------------------------------------

DISCOVERY_CALLS = (
    {"tool": "review_org_identity", "arguments": {}},
    {"tool": "review_installed_packages", "arguments": {}},
    {"tool": "review_object_contract", "arguments": {"objectApiName": "<subject>"}},
    {"tool": "knowledge_resolve", "arguments": {"names": ["<subject>"]}},
    {"tool": "knowledge_context", "arguments": {"identity": "<resolved identity>"}},
)


def compute_gaps(state: dict[str, Any], triggers: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every gap is {what, forWhom, howToClose?}; the tool-call handle appears ONLY for
    discovery gaps — for plan and verify the gap names what is missing, never how to get it
    (the anti-action-compiler boundary, rebuild plan §3)."""
    gaps: list[dict[str, Any]] = []
    intake = state["intake"]
    if not intake["goal"]:
        gaps.append({"id": "intake:goal", "what": "no recorded goal", "forWhom": "agent"})
    if not intake["acceptanceCriteria"]:
        gaps.append({"id": "intake:ac", "what": "no acceptance criteria", "forWhom": "agent"})
    subjects = intake["subjects"] or [s["name"] for s in state.get("proposedSubjects", [])]
    if not intake["subjects"]:
        gaps.append({
            "id": "intake:subjects",
            "what": "subject list not confirmed (proposal pending)",
            "forWhom": "agent",
        })
    for subject in subjects:
        entry = state["discovery"].get(subject)
        if not entry or entry.get("result") not in DISCOVERY_RESULTS:
            gaps.append({
                "id": f"discovery:{subject}",
                "what": f"no discovery result for {subject} "
                        "(found/no-entry/source-unavailable all close it — looked, not found)",
                "forWhom": "agent",
                "howToClose": DISCOVERY_CALLS,
            })
    ac_ids = {ac.get("id") or f"AC-{i+1:03d}" for i, ac in enumerate(_ac_list(intake))}
    covered = {item.get("acRef") for item in state["planItems"]}
    for ac_id in sorted(ac_ids - covered):
        gaps.append({"id": f"plan:{ac_id}", "what": f"{ac_id} has no plan item", "forWhom": "agent"})
    for item in state["planItems"]:
        if item.get("ungrounded"):
            gaps.append({
                "id": f"plan:{item['id']}:ungrounded",
                "what": f"plan item {item['id']} ({item.get('subject')}) has no discovery result",
                "forWhom": "agent",
            })
    if triggers is not None and state["verifyRounds"]:
        for gap in verify_gaps(state, triggers):
            gaps.append(gap)
    elif triggers is not None and state["phase"] in ("verify", "iterate"):
        for gap in verify_gaps(state, triggers):
            gaps.append(gap)
    return gaps


def _ac_list(intake: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, ac in enumerate(intake.get("acceptanceCriteria") or []):
        if isinstance(ac, dict):
            out.append({"id": ac.get("id") or f"AC-{i+1:03d}", "text": ac.get("text", "")})
        else:
            out.append({"id": f"AC-{i+1:03d}", "text": str(ac)})
    return out


# --------------------------------------------------------------------------------------
# Verify: triggered checklist + counted verdicts (rebuild plan §5)
# --------------------------------------------------------------------------------------


def triggered_items(state: dict[str, Any], triggers: dict[str, Any]) -> list[dict[str, str]]:
    """The verify checklist: rules from the static table + limitations from discovery."""
    items: dict[str, dict[str, str]] = {}
    for rule_id in triggers.get("always", []):
        items[rule_id] = {"id": rule_id, "kind": "rule"}
    matrix = triggers.get("byArtefactAction") or {}
    for item in state["planItems"]:
        artefact = item.get("artefactType") or "?"
        for cell in (f"{artefact}:{item.get('action')}", f"{artefact}:*"):
            for rule_id in matrix.get(cell, []):
                items[rule_id] = {"id": rule_id, "kind": "rule"}
    for subject, entry in state["discovery"].items():
        for index, limitation in enumerate(entry.get("limitations") or []):
            lim_id = f"LIM:{subject}:{index+1}"
            items[lim_id] = {"id": lim_id, "kind": "limitation", "text": str(limitation)}
    return sorted(items.values(), key=lambda item: item["id"])


def verify_gaps(state: dict[str, Any], triggers: dict[str, Any]) -> list[dict[str, Any]]:
    checklist = {item["id"] for item in triggered_items(state, triggers)}
    latest = state["verifyRounds"][-1] if state["verifyRounds"] else {"verdicts": []}
    verdicts = {v.get("itemId"): v for v in latest.get("verdicts", [])}
    gaps: list[dict[str, Any]] = []
    for item_id in sorted(checklist):
        verdict = verdicts.get(item_id)
        if verdict is None:
            gaps.append({"id": f"verify:{item_id}", "what": f"{item_id} has no verdict", "forWhom": "agent"})
            continue
        if verdict.get("verdict") not in VERDICTS:
            gaps.append({"id": f"verify:{item_id}", "what": f"{item_id} verdict is not ok/violation/n-a", "forWhom": "agent"})
        elif not verdict.get("sentence"):
            gaps.append({"id": f"verify:{item_id}", "what": f"{item_id} verdict has no sentence", "forWhom": "agent"})
        elif verdict.get("verdict") == "violation" and not verdict.get("addressedBy"):
            gaps.append({
                "id": f"verify:{item_id}:unaddressed",
                "what": f"violation on {item_id} has no treatment (named delta)",
                "forWhom": "agent",
            })
    return gaps


def update_iteration(state: dict[str, Any], gap_ids: set[str], cap: int) -> dict[str, Any]:
    """The counted stop (rebuild plan §2, P-3): measure = smallest gap-set size reached so
    far (oscillation is not progress); stop after two consecutive rounds without shrink;
    absolute safety at `cap` rounds. Returns the updated state; sets status=blocked with a
    delta stamp when the stop fires. Round 1 may legally reshuffle the set."""
    state = json.loads(json.dumps(state))
    ledger = state["iteration"]
    ledger["rounds"] += 1
    size = len(gap_ids)
    smallest = ledger["smallestGapSetSize"]
    if smallest is None or size < smallest:
        ledger["smallestGapSetSize"] = size
        ledger["roundsWithoutShrink"] = 0
    else:
        ledger["roundsWithoutShrink"] += 1
    stopped = ledger["roundsWithoutShrink"] >= 2 or ledger["rounds"] >= cap
    if stopped and gap_ids:
        state["status"] = "blocked"
        state["blocked"] = {"unresolved": sorted(gap_ids)}
    return state


# --------------------------------------------------------------------------------------
# Renderer: five mandatory sections, conditional only on trigger (rebuild plan §2.2)
# --------------------------------------------------------------------------------------

MANDATORY_SECTIONS = (
    "Outcome and scope",
    "Current state → target state → delta",
    "Solution Artefacts",
    "Decisions, constraints and known limitations",
    "Verification and rollback",
)

# name -> predicate over state; a conditional section renders ONLY when triggered.
CONDITIONAL_SECTIONS = {
    "Configuration records": lambda s: any(
        (i.get("artefactType") or "") in ("CustomMetadata", "CustomSetting") for i in s["planItems"]
    ),
    "Security and access": lambda s: any(
        (i.get("artefactType") or "") in ("PermissionSet", "PermissionSetGroup", "Profile", "SharingRules")
        for i in s["planItems"]
    ),
    "Integrations": lambda s: any(
        (i.get("artefactType") or "") in ("NamedCredential", "ExternalCredential", "ConnectedApp",
                                          "ExternalServiceRegistration", "RemoteSiteSetting")
        for i in s["planItems"]
    ),
    "Data migration": lambda s: bool(s.get("flags", {}).get("dataMigration")),
    "Volume and limits": lambda s: bool(s.get("flags", {}).get("highVolume")),
    "Observability": lambda s: bool(s.get("flags", {}).get("observability")),
}


def render_design(state: dict[str, Any], prose: dict[str, str] | None = None) -> str:
    """Render design.md. Mandatory sections always render with content (agent prose or an
    honest generated stub naming what is open — never empty, never a placeholder token);
    conditional sections render only when triggered. Decision anchors `#D-xxx` are inserted
    here, by the renderer, never by the model (rebuild plan §3). Internal identifiers, rule
    verdicts and gate mechanics stay out of the document (product goal §2)."""
    prose = prose or {}
    lines: list[str] = [f"# Solution Design — {state['caseId']}", ""]
    if state.get("status") == "blocked" and state.get("blocked"):
        unresolved = ", ".join(state["blocked"].get("unresolved", [])) or "unknown"
        lines += [f"> **Blocked — unresolved: {unresolved}.** Human decision required.", ""]

    for section in MANDATORY_SECTIONS:
        lines += [f"## {section}", ""]
        body = (prose.get(section) or "").strip()
        if section == "Solution Artefacts":
            lines += _artefacts_table(state)
            if body:
                lines += ["", body]
        elif section == "Decisions, constraints and known limitations":
            lines += _decisions_block(state, body)
        elif body:
            lines += [body]
        else:
            lines += [_mandatory_stub(section, state)]
        lines += [""]

    for section, predicate in CONDITIONAL_SECTIONS.items():
        if not predicate(state):
            continue
        body = (prose.get(section) or "").strip()
        lines += [f"## {section}", "", body or _mandatory_stub(section, state), ""]
    return "\n".join(lines).rstrip() + "\n"


def _mandatory_stub(section: str, state: dict[str, Any]) -> str:
    open_items = [a["note"] for a in state.get("annotations", [])][:3]
    suffix = f" Open: {'; '.join(open_items)}." if open_items else ""
    return f"*Not yet authored — open content for “{section}”.*{suffix}"


def _artefacts_table(state: dict[str, Any]) -> list[str]:
    rows = ["| Object | Artefact Type | API Name | Description |", "|---|---|---|---|"]
    for item in state["planItems"]:
        subject = str(item.get("subject") or "—")
        obj = subject.split(".", 1)[0] if "." in subject else subject
        name = subject.split(".", 1)[1] if "." in subject else subject
        label = item.get("label") or "unlabelled"
        marker = " **[ungrounded]**" if item.get("ungrounded") else ""
        rows.append(
            f"| {obj} | {item.get('artefactType') or '—'} ({item.get('action') or '—'}) "
            f"| {name} | {label}{marker} |"
        )
    if len(rows) == 2:
        rows.append("| — | — | — | *no plan items recorded yet* |")
    return rows


def _decisions_block(state: dict[str, Any], body: str) -> list[str]:
    lines: list[str] = []
    for index, decision in enumerate(state.get("decisions", []), start=1):
        anchor = f"D-{index:03d}"
        title = decision.get("title") or decision.get("choice") or "decision"
        lines.append(f'- <a id="{anchor}"></a>**{anchor}** — {title}')
        if decision.get("alternatives"):
            lines.append(f"  - alternatives considered: {', '.join(map(str, decision['alternatives']))}")
    limitations = [
        f"- {subject}: {text}"
        for subject, entry in sorted(state["discovery"].items())
        for text in entry.get("limitations") or []
    ]
    if limitations:
        lines += ["", "Known limitations (from discovery):", *limitations]
    if body:
        lines += ["", body]
    if not lines:
        lines = [_mandatory_stub("Decisions, constraints and known limitations", state)]
    return lines


# --------------------------------------------------------------------------------------
# Submit: the single hard gate (rebuild plan §6)
# --------------------------------------------------------------------------------------

DELEGATING_PATTERNS = (
    "do twojej decyzji", "jak uważasz", "zdecyduj sam", "zdecyduj sama", "ty zdecyduj",
    "up to you", "your call", "you decide", "whatever you think", "as you see fit",
    "twoja decyzja", "jak wolisz",
)
NON_ANSWERS = ("", "n/a", "na", "unknown", "tbd", "-", "?")


def classify_answer(answer: str) -> str:
    """'complete' | 'delegated' | 'non-answer'. A delegating reply is a real sentence that
    hands the decision back — it must return as an AGENT decision requiring its own
    acknowledgement, never as human-attested evidence (run-242050 defect, plan §6). The
    empty class is separate because the text is empty/placeholder rather than deflecting."""
    stripped = (answer or "").strip().lower().rstrip(".!")
    if stripped in NON_ANSWERS:
        return "non-answer"
    if any(pattern in stripped for pattern in DELEGATING_PATTERNS):
        return "delegated"
    return "complete"


def submit_blockers(state: dict[str, Any], triggers: dict[str, Any]) -> list[str]:
    """Invariants that block submit — and ONLY submit; the loop never refuses.

    D-2: an assumption never closes a change to package-namespace metadata — a
    create/modify/delete plan item on a package-owned subject without a discovery result of
    `found` blocks the gate."""
    blockers: list[str] = []
    for item in state["planItems"]:
        if item.get("action") not in WRITING_ACTIONS:
            continue
        entry = state["discovery"].get(str(item.get("subject"))) or {}
        package_owned = (entry.get("ownership") == "package") or bool(entry.get("namespace"))
        if package_owned and entry.get("result") != "found":
            blockers.append(
                f"plan item {item['id']}: {item['action']} on package-namespace subject "
                f"{item.get('subject')} rests on an assumption (discovery result: "
                f"{entry.get('result') or 'none'}) — D-2 blocks submit, not the loop"
            )
    if not state["verifyRounds"]:
        blockers.append("no verify round recorded — submit requires at least one counted verify")
    else:
        for gap in verify_gaps(state, triggers):
            blockers.append(f"open verify gap: {gap['what']}")
    return blockers


def render_check(state: dict[str, Any], triggers: dict[str, Any] | None) -> dict[str, Any]:
    gaps = compute_gaps(state, triggers)
    return {
        "phase": state["phase"],
        "status": state["status"],
        "gaps": gaps,
        "gapCount": len(gaps),
        "iteration": state["iteration"],
        "advisory": True,  # check() counts; it never blocks (the gate is design_submit)
    }
