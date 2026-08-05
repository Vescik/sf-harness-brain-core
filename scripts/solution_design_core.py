#!/usr/bin/env python3
"""Pure Design Case domain logic: canonicalization, gates, applicability, transitions.

This module owns the semantics of the Solution Design rebuild. It performs no I/O beyond
reading explicitly named configuration files, holds no process state, and never mutates a
case: every entry point takes the structured state plus its context and returns a value.
The mutating runtime (`solution_design_worker.py`) and the read-only diagnostic CLI
(`solution_design.py`) are the only callers that touch the filesystem.

Two digests exist and are deliberately different:

* `caseVersion` (`cv1_<hex>`) — the opaque optimistic-concurrency token over state sequence,
  normalized structured state and the current `design.md` byte digest.
* `candidateDigest` (`sha256:<hex>`) — the immutable approval identity over the candidate
  bundle input.

Both use the versioned `sd-c14n-v1` canonicalizer defined in this module. `work_record.py`'s
`canonical_bytes` is a *different*, laxer serializer and is never substituted for it.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.solution_design_core by unit tests
    from scripts.schema_format import FORMAT_CHECKER


HARNESS_ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-state.schema.json"
EVIDENCE_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-evidence.schema.json"
CANDIDATE_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-candidate.schema.json"
RECEIPT_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-transition-receipt.schema.json"
RULE_MAP_SCHEMA = HARNESS_ROOT / "schemas" / "solution-design-rule-map.schema.json"
RULE_MAP_PATH = HARNESS_ROOT / "config" / "solution-design-rule-map.json"
CAPABILITIES_PATH = HARNESS_ROOT / "config" / "solution-design-capabilities.json"
INSTRUCTION_FILES = (
    HARNESS_ROOT / ".github" / "copilot-instructions.md",
    HARNESS_ROOT / ".github" / "instructions" / "managed-package-constraints.instructions.md",
    HARNESS_ROOT / ".github" / "instructions" / "organization-principles.instructions.md",
    HARNESS_ROOT / ".github" / "instructions" / "salesforce-best-practices.instructions.md",
)

CANONICALIZER_VERSION = "sd-c14n-v1"
CASE_VERSION_PREFIX = "cv1_"
SOURCE_AUTHORITY_POLICY_VERSION = "sa-v1"

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

RULE_ID = re.compile(r"^(SAFE|MP|ORG|SF)-[A-Z0-9-]+$")
RULE_DEFINITION = re.compile(r"^\s*[-*]\s+\*\*(?P<id>(?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\b", re.MULTILINE)
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\?\?\?|<[A-Za-z][A-Za-z0-9 _/-]{0,60}>")
GENERATED_BLOCK = re.compile(
    r"<!--\s*BEGIN GENERATED:(?P<name>[A-Z0-9-]+)\s*-->(?P<body>.*?)<!--\s*END GENERATED:(?P=name)\s*-->",
    re.DOTALL,
)

STATES = (
    "draft",
    "awaiting_human_input",
    "candidate",
    "awaiting_design_review",
    "awaiting_human",
    "accepted",
    "development",
    "review",
    "complete",
)

# §8.3. Every durable transition the rebuilt lifecycle allows. There is no generic set-status.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("draft", "awaiting_human_input", "candidate"),
    "awaiting_human_input": ("draft",),
    "candidate": ("awaiting_design_review", "awaiting_human", "draft"),
    "awaiting_design_review": ("draft", "awaiting_human_input", "awaiting_human"),
    "awaiting_human": ("draft", "accepted"),
    "accepted": ("development", "draft"),
    "development": ("draft", "review"),
    "review": ("development", "draft", "complete"),
    "complete": (),
}

CONCERN_PROFILES = (
    "data-model-and-configuration-integrity",
    "security-and-execution-context",
    "transaction-and-automation",
    "volume-and-performance",
    "integrations-and-contracts",
    "user-journey-and-accessibility",
    "errors-and-observability",
    "package-boundaries-and-upgrade",
    "migration-rollout-rollback",
    "verification-feasibility",
)

CONCERN_IDS = {profile: "COV-" + profile.upper().replace("-", "-") for profile in CONCERN_PROFILES}

# Artefact types that execute inside a save transaction or otherwise run code.
AUTOMATION_ARTEFACTS = frozenset(
    {"ApexTrigger", "Flow", "FlowDefinition", "WorkflowRule", "ApprovalProcess", "ApexClass"}
)
UI_ARTEFACTS = frozenset(
    {"LightningComponentBundle", "AuraDefinitionBundle", "FlexiPage", "Layout", "ApexPage", "QuickAction"}
)
INTEGRATION_ARTEFACTS = frozenset(
    {"ApexClass", "NamedCredential", "RemoteSiteSetting", "PlatformEventChannel", "ConnectedApp"}
)
SECURITY_ARTEFACTS = frozenset(
    {"PermissionSet", "PermissionSetGroup", "Profile", "SharingRules", "MutingPermissionSet", "Queue", "Role"}
)
MUTATING_ACTIONS = frozenset({"create", "modify", "delete", "retire"})
MUTATING_CONFIG_ACTIONS = frozenset({"create-records", "modify-records", "delete-records", "retire"})

# §12.1. Which receipt source types may close a question that demands a given authority.
CLOSURE_AUTHORITY: dict[str, frozenset[str]] = {
    "knowledge-entry": frozenset({"knowledge-entry"}),
    "repository-receipt": frozenset({"repository-receipt"}),
    "org-object-contract": frozenset({"org-object-contract"}),
    "org-soql-sample": frozenset({"org-soql-sample"}),
    "human-sme-attestation": frozenset({"human-sme-attestation"}),
    "vendor-documentation": frozenset({"vendor-documentation", "human-sme-attestation"}),
    "ado-approved-artifact": frozenset({"ado-approved-artifact"}),
    "production-authoritative-human": frozenset({"production-authoritative-human"}),
}

# Question statuses that are routing, not closure. §10.4.
UNCLOSED_QUESTION_STATUSES = frozenset(
    {"open", "evidence-planned", "observed", "contested", "needs-human", "stale"}
)
HUMAN_AUTHORITIES = frozenset(
    {"human-sme-attestation", "production-authoritative-human", "vendor-documentation"}
)


class SolutionDesignError(RuntimeError):
    """A safe, user-actionable Design Case failure."""


# --------------------------------------------------------------------------------------
# sd-c14n-v1
# --------------------------------------------------------------------------------------


def _normalize(value: Any, *, path: str = "$") -> Any:
    """Recursively apply NFC and the sd-c14n-v1 type restrictions."""
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
    """sd-c14n-v1 canonical bytes: NFC, closed type set, sorted keys, UTF-8, no trailing newline."""
    normalized = _normalize(value)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def sd_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_digest(text: str) -> str:
    """Digest of a normalized design document: UTF-8, no BOM, LF line endings."""
    return "sha256:" + hashlib.sha256(normalize_document(text).encode("utf-8")).hexdigest()


def normalize_document(text: str) -> str:
    """UTF-8 without BOM and LF only, so Windows/macOS/Linux produce identical bytes."""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def case_version(state_sequence: int, structured_state: dict[str, Any], design_digest: str) -> str:
    """Opaque optimistic-concurrency token. Excludes timestamps and unrelated record state."""
    envelope = {
        "canonicalizer": CANONICALIZER_VERSION,
        "stateSequence": state_sequence,
        "structuredState": structured_state,
        "designDigest": design_digest,
    }
    return CASE_VERSION_PREFIX + hashlib.sha256(canonical_bytes(envelope)).hexdigest()


# --------------------------------------------------------------------------------------
# Configuration loading
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


def validate_against(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    messages = []
    for error in errors[:8]:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    suffix = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
    raise SolutionDesignError(f"{label} schema validation failed: {'; '.join(messages)}{suffix}")


CAPABILITY_KEYS = (
    "schemaVersion",
    "manifestVersion",
    "gateEvaluatorVersion",
    "materialSince",
    "concernProfiles",
    "probeKinds",
    "evidenceSourceTypes",
    "configurationActions",
    "componentActions",
    "adapters",
    "riskPolicies",
    "transitions",
    "generatedSections",
)


def load_capabilities(path: Path | None = None) -> dict[str, Any]:
    manifest = _load_json(path or CAPABILITIES_PATH)
    missing = [key for key in CAPABILITY_KEYS if key not in manifest]
    if missing:
        raise SolutionDesignError(f"capability manifest is missing keys: {', '.join(sorted(missing))}")
    unknown = sorted(set(manifest) - set(CAPABILITY_KEYS))
    if unknown:
        raise SolutionDesignError(f"capability manifest has unknown keys: {', '.join(unknown)}")
    if manifest["schemaVersion"] != 1:
        raise SolutionDesignError("capability manifest schemaVersion must be 1")
    unknown_profiles = sorted(set(manifest["concernProfiles"]) - set(CONCERN_PROFILES))
    if unknown_profiles:
        raise SolutionDesignError(
            f"capability manifest declares unknown concern profiles: {', '.join(unknown_profiles)}"
        )
    return manifest


def capability_digest(manifest: dict[str, Any]) -> str:
    return sd_digest(manifest)


def load_rule_map(path: Path | None = None) -> dict[str, Any]:
    rule_map = _load_json(path or RULE_MAP_PATH)
    validate_against(rule_map, RULE_MAP_SCHEMA, "rule map")
    overlap = sorted(set(rule_map["rules"]) & set(rule_map["manualApplicability"]))
    if overlap:
        raise SolutionDesignError(
            f"rule appears in both selector and manual registries: {', '.join(overlap)}"
        )
    return rule_map


def canonical_rule_definitions(paths: Iterable[Path] = INSTRUCTION_FILES) -> dict[str, str]:
    """Map every canonical rule ID to the digest of its normalized definition line.

    A rule ID declared twice across the instruction sources is a defect: the registry could
    then bind a candidate to an ambiguous definition.
    """
    definitions: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise SolutionDesignError(f"instruction source is missing: {path}")
        text = normalize_document(path.read_text(encoding="utf-8"))
        lines = text.split("\n")
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


def validate_rule_registry(
    rule_map: dict[str, Any], definitions: dict[str, str]
) -> list[str]:
    """Bidirectional registry check (§13.2). Returns the list of problems, empty when clean."""
    problems: list[str] = []
    mapped = set(rule_map["rules"]) | set(rule_map["manualApplicability"])
    canonical = set(definitions)
    for rule_id in sorted(mapped - canonical):
        problems.append(f"registry references unknown rule {rule_id}")
    for rule_id in sorted(canonical - mapped):
        problems.append(
            f"canonical hard rule {rule_id} has no registry entry and no manualApplicability entry"
        )
    tiers = {"SAFE": "kernel", "MP": "tier-1", "ORG": "tier-2", "SF": "tier-3"}
    for registry in ("rules", "manualApplicability"):
        for rule_id, entry in rule_map[registry].items():
            expected = tiers.get(rule_id.split("-", 1)[0])
            if expected and entry["tier"] != expected:
                problems.append(
                    f"{rule_id} is declared {entry['tier']} but its ID prefix means {expected}"
                )
            if entry["tier"] in ("kernel", "tier-1") and entry["severity"] != "blocking":
                problems.append(f"{rule_id} is a hard rule and cannot be advisory")
    return problems


# --------------------------------------------------------------------------------------
# Applicability
# --------------------------------------------------------------------------------------


def _components(state: dict[str, Any]) -> list[dict[str, Any]]:
    return list(state.get("scope", {}).get("components", []))


def _in_scope_components(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _components(state) if item.get("disposition") == "in-scope"]


def _selector_matches(selector: dict[str, Any], state: dict[str, Any], concerns: set[str]) -> bool:
    if selector.get("always") is True:
        return bool(_in_scope_components(state)) or bool(state.get("configurationArtefacts"))
    if "concernProfiles" in selector:
        if not concerns & set(selector["concernProfiles"]):
            return False
        if len(selector) == 1:
            return True
    component_keys = {
        "componentActions": "action",
        "artefactTypes": "artefactType",
        "componentOwnership": "componentOwnership",
        "hostObjectOwnership": "hostObjectOwnership",
    }
    active_component_keys = {key: field for key, field in component_keys.items() if key in selector}
    if active_component_keys:
        for component in _in_scope_components(state):
            if all(
                component.get(field) in selector[key]
                for key, field in active_component_keys.items()
            ):
                break
        else:
            return False
    config_keys = {"configurationActions": "action"}
    active_config_keys = {key: field for key, field in config_keys.items() if key in selector}
    if active_config_keys:
        for artefact in state.get("configurationArtefacts", []):
            if all(
                artefact.get(field) in selector[key] for key, field in active_config_keys.items()
            ):
                break
        else:
            return False
    if "dataRoles" in selector:
        roles = {item.get("dataRole") for item in state.get("dataClassifications", [])}
        if not roles & set(selector["dataRoles"]):
            return False
    return bool(active_component_keys or active_config_keys or "dataRoles" in selector or "concernProfiles" in selector)


def applicable_rule_ids(
    state: dict[str, Any], rule_map: dict[str, Any], applicable_concerns: Iterable[str]
) -> list[str]:
    """Selector-driven rules whose triggers are present in the structured state."""
    concerns = set(applicable_concerns)
    selected: list[str] = []
    for rule_id, entry in sorted(rule_map["rules"].items()):
        selectors = entry.get("whenAny") or [entry["when"]]
        if any(_selector_matches(selector, state, concerns) for selector in selectors):
            selected.append(rule_id)
    return selected


def concern_applicability(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Deterministic concern applicability from ACs, scope, actions, ownership and classification.

    Returns profileId -> {"applicable": bool, "triggers": [...]}. The model never sets this;
    a concern the model failed to author still shows up here (§10.5).
    """
    components = _in_scope_components(state)
    configuration = list(state.get("configurationArtefacts", []))
    classifications = list(state.get("dataClassifications", []))
    result: dict[str, dict[str, Any]] = {
        profile: {"applicable": False, "triggers": []} for profile in CONCERN_PROFILES
    }

    def mark(profile: str, trigger: str) -> None:
        entry = result[profile]
        entry["applicable"] = True
        if trigger not in entry["triggers"]:
            entry["triggers"].append(trigger)

    mutating_components = [c for c in components if c.get("action") in MUTATING_ACTIONS]
    mutating_config = [c for c in configuration if c.get("action") in MUTATING_CONFIG_ACTIONS]

    if mutating_components or mutating_config or classifications:
        for component in mutating_components:
            mark("data-model-and-configuration-integrity", component["componentId"])
        for artefact in mutating_config:
            mark("data-model-and-configuration-integrity", artefact["configurationArtefactId"])
        for classification in classifications:
            mark("data-model-and-configuration-integrity", classification["classificationId"])

    for component in components:
        artefact_type = component.get("artefactType", "")
        action = component.get("action")
        if artefact_type in SECURITY_ARTEFACTS and action in MUTATING_ACTIONS:
            mark("security-and-execution-context", component["componentId"])
        if artefact_type in AUTOMATION_ARTEFACTS and action in MUTATING_ACTIONS:
            mark("security-and-execution-context", component["componentId"])
            mark("transaction-and-automation", component["componentId"])
            mark("volume-and-performance", component["componentId"])
            mark("errors-and-observability", component["componentId"])
        if artefact_type in UI_ARTEFACTS and action in MUTATING_ACTIONS:
            mark("user-journey-and-accessibility", component["componentId"])
        if artefact_type in INTEGRATION_ARTEFACTS and action in MUTATING_ACTIONS:
            mark("integrations-and-contracts", component["componentId"])
        if (
            component.get("componentOwnership") in ("package-owned", "unknown")
            or component.get("hostObjectOwnership") in ("package-owned", "unknown")
        ):
            mark("package-boundaries-and-upgrade", component["componentId"])

    for artefact in mutating_config:
        mark("migration-rollout-rollback", artefact["configurationArtefactId"])
        mark("volume-and-performance", artefact["configurationArtefactId"])
    for component in mutating_components:
        if component.get("action") in ("delete", "retire"):
            mark("migration-rollout-rollback", component["componentId"])

    for criterion in state.get("requirementSnapshot", {}).get("acceptanceCriteria", []):
        if criterion.get("inScope"):
            mark("verification-feasibility", criterion["acId"])

    return result


# --------------------------------------------------------------------------------------
# Evidence helpers
# --------------------------------------------------------------------------------------


def _evidence_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["receiptId"]: item for item in state.get("evidenceRefs", [])}


def evidence_eligible(receipt: dict[str, Any], *, authorities: Iterable[str]) -> tuple[bool, str]:
    """Can this receipt close a design obligation demanding one of `authorities`?"""
    allowed: set[str] = set()
    for authority in authorities:
        allowed |= CLOSURE_AUTHORITY.get(authority, frozenset())
    if receipt.get("sourceType") not in allowed:
        return False, "authority-mismatch"
    if receipt.get("status") != "current":
        return False, f"receipt-{receipt.get('status')}"
    if receipt.get("validationPurpose") != "design-evidence":
        return False, "transport-mechanics-receipt"
    if receipt.get("environmentFitness") == "non-representative-devmp":
        return False, "non-representative-devmp"
    if receipt.get("completeness") == "incomplete":
        return False, "incomplete-evidence"
    return True, "eligible"


# --------------------------------------------------------------------------------------
# Gate evaluation
# --------------------------------------------------------------------------------------


def _gap(gate: str, entity: str, closure: str, route: str, detail: str) -> dict[str, str]:
    return {
        "gateId": gate,
        "entity": entity,
        "requiredClosure": closure,
        "route": route,
        "detail": detail,
    }


def gate_g0(state: dict[str, Any], capabilities: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G0 — runtime capability ceiling. Always OPEN when a needed capability is missing."""
    gaps: list[dict[str, str]] = []
    supported_probe_kinds = set(capabilities["probeKinds"])
    for probe in state.get("probes", []):
        if probe["kind"] not in supported_probe_kinds:
            gaps.append(
                _gap(
                    "SD-G0",
                    probe["probeId"],
                    "UNSUPPORTED_CAPABILITY",
                    "grounding",
                    f"probe kind {probe['kind']} is not in capability manifest "
                    f"{capabilities['manifestVersion']}",
                )
            )
    supported_sources = set(capabilities["evidenceSourceTypes"])
    for receipt in state.get("evidenceRefs", []):
        if receipt["sourceType"] not in supported_sources:
            gaps.append(
                _gap(
                    "SD-G0",
                    receipt["receiptId"],
                    "UNSUPPORTED_CAPABILITY",
                    "grounding",
                    f"evidence source type {receipt['sourceType']} is not implemented",
                )
            )
    supported_component_actions = set(capabilities["componentActions"])
    for component in _components(state):
        if component["action"] not in supported_component_actions:
            gaps.append(
                _gap(
                    "SD-G0",
                    component["componentId"],
                    "UNSUPPORTED_CAPABILITY",
                    "design",
                    f"component action {component['action']} is not implemented",
                )
            )
    supported_config_actions = set(capabilities["configurationActions"])
    for artefact in state.get("configurationArtefacts", []):
        if artefact["action"] not in supported_config_actions:
            gaps.append(
                _gap(
                    "SD-G0",
                    artefact["configurationArtefactId"],
                    "UNSUPPORTED_CAPABILITY",
                    "design",
                    f"configuration action {artefact['action']} is not implemented",
                )
            )
    supported_profiles = set(capabilities["concernProfiles"])
    for profile, verdict in concern_applicability(state).items():
        if verdict["applicable"] and profile not in supported_profiles:
            gaps.append(
                _gap(
                    "SD-G0",
                    profile,
                    "UNSUPPORTED_CAPABILITY",
                    "design",
                    f"concern profile {profile} is applicable but not implemented in "
                    f"{capabilities['manifestVersion']}",
                )
            )
    return gaps


def gate_g1(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G1 — requirement integrity."""
    gaps: list[dict[str, str]] = []
    snapshot = state.get("requirementSnapshot", {})
    if snapshot.get("completeness") == "absent":
        gaps.append(
            _gap("SD-G1", "requirementSnapshot", "requirement-source", "requirements", "no requirement source is bound")
        )
        return gaps
    if snapshot.get("completeness") != "complete":
        gaps.append(
            _gap(
                "SD-G1",
                "requirementSnapshot",
                "requirement-completeness",
                "requirements",
                "child items are summary-only or the hierarchy was not fully retrieved",
            )
        )
    criteria = snapshot.get("acceptanceCriteria", [])
    if not criteria:
        gaps.append(
            _gap("SD-G1", "requirementSnapshot", "acceptance-criteria", "requirements", "no acceptance criteria")
        )
    seen: set[str] = set()
    for criterion in criteria:
        if criterion["acId"] in seen:
            gaps.append(
                _gap("SD-G1", criterion["acId"], "ac-identity", "requirements", "duplicate AC identity")
            )
        seen.add(criterion["acId"])
    for contradiction in snapshot.get("unresolvedContradictions", []):
        gaps.append(
            _gap("SD-G1", "requirementSnapshot", "requirement-contradiction", "requirements", contradiction)
        )
    if snapshot.get("sourceType") == "human-request" and not snapshot.get("attestationRef"):
        gaps.append(
            _gap(
                "SD-G1",
                "requirementSnapshot",
                "requirement-attestation",
                "human-input",
                "an explicit human requirement needs a named pre-candidate attestation receipt",
            )
        )
    return gaps


def gate_g2(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G2 — scope integrity."""
    gaps: list[dict[str, str]] = []
    components = _components(state)
    if not components and not state.get("configurationArtefacts"):
        gaps.append(_gap("SD-G2", "scope", "implementation-target", "design", "the case has no implementation target"))
    for component in components:
        cid = component["componentId"]
        if component.get("disposition") == "unknown":
            gaps.append(_gap("SD-G2", cid, "frontier-disposition", "grounding", "frontier component has no disposition"))
        if component.get("disposition") in ("out-of-scope", "dependency-only") and not component.get(
            "dispositionReason"
        ):
            gaps.append(
                _gap("SD-G2", cid, "frontier-disposition", "grounding", "excluded component has no reason")
            )
        if component.get("action") not in MUTATING_ACTIONS:
            continue
        if component.get("componentOwnership") == "unknown":
            gaps.append(
                _gap("SD-G2", cid, "ownership-classification", "grounding", "modified component ownership is unknown")
            )
        if component.get("hostObjectOwnership") == "unknown":
            gaps.append(
                _gap("SD-G2", cid, "ownership-classification", "grounding", "host object ownership is unknown")
            )
        if not component.get("evidenceRefs"):
            gaps.append(
                _gap("SD-G2", cid, "component-evidence", "grounding", "create/modify/delete target has no evidence")
            )
        if (
            component.get("componentOwnership") == "package-owned"
            or component.get("hostObjectOwnership") == "package-owned"
        ) and component.get("extensionPointStatus") == "unknown":
            gaps.append(
                _gap("SD-G2", cid, "extension-point", "grounding", "package-facing target has unknown extension point")
            )
    classifications = {item["classificationId"] for item in state.get("dataClassifications", [])}
    for artefact in state.get("configurationArtefacts", []):
        aid = artefact["configurationArtefactId"]
        if artefact["classificationRef"] not in classifications:
            gaps.append(
                _gap("SD-G2", aid, "data-classification", "grounding", "configuration artefact has no classification")
            )
        if artefact["action"] in MUTATING_CONFIG_ACTIONS and not artefact.get("evidenceRefs"):
            gaps.append(
                _gap("SD-G2", aid, "configuration-evidence", "grounding", "record change has no evidence")
            )
    for classification in state.get("dataClassifications", []):
        if classification["assurance"] == "unknown" and any(
            artefact["classificationRef"] == classification["classificationId"]
            and artefact["action"] in MUTATING_CONFIG_ACTIONS
            for artefact in state.get("configurationArtefacts", [])
        ):
            gaps.append(
                _gap(
                    "SD-G2",
                    classification["classificationId"],
                    "data-classification",
                    "grounding",
                    "records are changed but the slice classification assurance is unknown",
                )
            )
    return gaps


def gate_g3(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G3 — concern coverage and claim/evidence integrity."""
    gaps: list[dict[str, str]] = []
    computed = concern_applicability(state)
    declared = {item["profileId"]: item for item in state.get("concernCoverage", [])}
    for profile, verdict in computed.items():
        entry = declared.get(profile)
        if verdict["applicable"]:
            if entry is None:
                gaps.append(
                    _gap(
                        "SD-G3",
                        profile,
                        "concern-treatment",
                        "design",
                        "concern is deterministically applicable but absent from the case",
                    )
                )
                continue
            if entry["applicability"] != "applicable":
                gaps.append(
                    _gap(
                        "SD-G3",
                        profile,
                        "concern-treatment",
                        "design",
                        "concern was declared not-applicable but its triggers are present: "
                        + ", ".join(verdict["triggers"][:5]),
                    )
                )
                continue
            if entry["status"] == "open":
                gaps.append(_gap("SD-G3", profile, "concern-treatment", "design", "concern is unaddressed"))
                continue
            has_treatment = bool(
                entry.get("treatmentRefs")
                or entry.get("questionRefs")
                or entry.get("riskRefs")
            )
            if not has_treatment:
                gaps.append(
                    _gap("SD-G3", profile, "concern-treatment", "design", "concern has an empty treatment")
                )
            if entry["status"] == "risk-raised" and not entry.get("riskRefs"):
                gaps.append(
                    _gap("SD-G3", profile, "concern-treatment", "design", "risk-raised concern links no risk")
                )
        elif entry is not None and entry["applicability"] == "not-applicable":
            if not entry.get("notApplicableReason"):
                gaps.append(
                    _gap(
                        "SD-G3",
                        profile,
                        "concern-na-rationale",
                        "design",
                        "not-applicable concern has no trigger-aware rationale",
                    )
                )

    evidence = _evidence_index(state)
    for question in state.get("questions", []):
        if question["materiality"] != "blocking":
            continue
        qid = question["questionId"]
        if question["status"] in UNCLOSED_QUESTION_STATUSES:
            route = "human-input" if question["status"] == "needs-human" else question["route"]
            gaps.append(
                _gap("SD-G3", qid, "question-closure", route, f"blocking question is {question['status']}")
            )
            continue
        refs = question.get("evidenceRefs", [])
        if not refs:
            gaps.append(
                _gap(
                    "SD-G3",
                    qid,
                    "question-closure",
                    question["route"],
                    "blocking question was closed without a receipt; model prose is not evidence",
                )
            )
            continue
        if not any(
            receipt_id in evidence
            and evidence_eligible(evidence[receipt_id], authorities=question["requiredAuthority"])[0]
            for receipt_id in refs
        ):
            reasons = sorted(
                {
                    evidence_eligible(evidence[receipt_id], authorities=question["requiredAuthority"])[1]
                    for receipt_id in refs
                    if receipt_id in evidence
                }
            ) or ["missing-receipt"]
            gaps.append(
                _gap(
                    "SD-G3",
                    qid,
                    "question-closure",
                    question["route"],
                    "no linked receipt satisfies the required authority: " + ", ".join(reasons),
                )
            )
    return gaps


def gate_g4(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G4 — probe closure."""
    gaps: list[dict[str, str]] = []
    evidence = _evidence_index(state)
    questions = {item["questionId"]: item for item in state.get("questions", [])}
    for probe in state.get("probes", []):
        pid = probe["probeId"]
        if probe["requiredness"] == "advisory":
            continue
        if probe["status"] == "not-applicable":
            if probe["requiredness"] == "conditional" and probe.get("notApplicableReason"):
                continue
            gaps.append(
                _gap(
                    "SD-G4",
                    pid,
                    "probe-closure",
                    "grounding",
                    "a hard probe cannot be closed as not-applicable"
                    if probe["requiredness"] == "hard"
                    else "conditional probe needs a predicate-based reason",
                )
            )
            continue
        if probe["status"] == "blocked":
            gaps.append(_gap("SD-G4", pid, "probe-closure", "human-input", "probe is blocked on human authority"))
            continue
        if probe["status"] != "closed":
            gaps.append(_gap("SD-G4", pid, "probe-closure", "grounding", f"probe is {probe['status']}"))
            continue
        receipt_id = probe.get("receiptRef")
        receipt = evidence.get(receipt_id) if receipt_id else None
        if receipt is None:
            gaps.append(_gap("SD-G4", pid, "probe-closure", "grounding", "closed probe has no receipt"))
            continue
        question = questions.get(probe["questionId"])
        authorities = question["requiredAuthority"] if question else [receipt["sourceType"]]
        eligible, reason = evidence_eligible(receipt, authorities=authorities)
        if not eligible:
            gaps.append(_gap("SD-G4", pid, "probe-closure", "grounding", f"probe receipt is {reason}"))
            continue
        if receipt["status"] == "stale":
            gaps.append(_gap("SD-G4", pid, "probe-freshness", "grounding", "decision-critical probe is stale"))
        if probe.get("fitnessVerdict") == "not-fit":
            gaps.append(
                _gap("SD-G4", pid, "fitness-reentry", "design", "negative fitness has not reopened option selection")
            )
        if probe.get("fitnessVerdict") == "inconclusive":
            gaps.append(
                _gap("SD-G4", pid, "fitness-reentry", "human-input", "inconclusive fitness needs a human route")
            )
        if probe["requiredness"] == "hard" and probe["recheckPlan"] not in ("never", "manual-only"):
            spec = probe.get("replaySpec")
            if not spec or not spec.get("replayable"):
                gaps.append(
                    _gap(
                        "SD-G4",
                        pid,
                        "replay-spec",
                        "grounding",
                        "a rechecked hard probe needs a durable replayable spec or an approved manual-only route",
                    )
                )
    return gaps


def gate_g5(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G5 — decision integrity."""
    gaps: list[dict[str, str]] = []
    evidence = _evidence_index(state)
    for decision in state.get("decisions", []):
        did = decision["decisionId"]
        if decision.get("materiality") == "trivial":
            if not decision.get("trivialityReason"):
                gaps.append(_gap("SD-G5", did, "decision-alternatives", "design", "trivial decision has no reason"))
            continue
        if not decision.get("alternativeRefs") and not decision.get("trivialityReason"):
            gaps.append(
                _gap("SD-G5", did, "decision-alternatives", "design", "material decision considers no alternative")
            )
        for field, closure in (
            ("acIds", "decision-ac-link"),
            ("componentIds", "decision-component-link"),
            ("evidenceRefs", "decision-evidence-link"),
            ("verificationRefs", "decision-verification-link"),
        ):
            if not decision.get(field):
                gaps.append(_gap("SD-G5", did, closure, "design", f"decision has no {field}"))
        for receipt_id in decision.get("evidenceRefs", []):
            receipt = evidence.get(receipt_id)
            if receipt is None:
                gaps.append(_gap("SD-G5", did, "decision-evidence-link", "grounding", f"unknown receipt {receipt_id}"))
            elif receipt["status"] in ("contested", "superseded"):
                gaps.append(
                    _gap(
                        "SD-G5",
                        did,
                        "decision-evidence-link",
                        "grounding",
                        f"decision relies on a {receipt['status']} premise",
                    )
                )
    return gaps


def gate_g6(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G6 — risk integrity."""
    gaps: list[dict[str, str]] = []
    for risk in state.get("riskObligations", []):
        rid = risk["riskId"]
        if risk["status"] == "open":
            gaps.append(_gap("SD-G6", rid, "risk-resolution", "design", "risk obligation is open"))
            continue
        if risk["status"] == "accepted" and not risk.get("acceptedRiskReceiptRef"):
            gaps.append(
                _gap(
                    "SD-G6",
                    rid,
                    "risk-acceptance",
                    "human-input",
                    "accepted risk needs a pre-candidate human authority receipt",
                )
            )
        if risk["status"] == "mitigated" and not risk.get("mitigationDesignRef"):
            gaps.append(_gap("SD-G6", rid, "risk-mitigation", "design", "mitigated risk names no design treatment"))
        missing = sorted(set(risk.get("requiredClosures", [])) - set(risk.get("satisfiedClosures", [])))
        for closure in missing:
            gaps.append(_gap("SD-G6", rid, closure, "grounding", f"required risk closure {closure} is missing"))
        if risk["status"] == "mitigated" and not risk.get("verificationRefs"):
            gaps.append(
                _gap("SD-G6", rid, "risk-verification", "verification", "mitigation is never proven by a verification")
            )
    return gaps


def gate_g7(state: dict[str, Any]) -> list[dict[str, str]]:
    """SD-G7 — AC and Verification Contract coverage."""
    gaps: list[dict[str, str]] = []
    contract = state.get("verificationContract", [])
    covered: set[str] = set()
    for entry in contract:
        covered |= set(entry.get("acIds", []))
    decided: set[str] = set()
    for decision in state.get("decisions", []):
        decided |= set(decision.get("acIds", []))
    targeted: set[str] = set()
    for component in _in_scope_components(state):
        targeted |= set(component.get("acIds", []))
    for artefact in state.get("configurationArtefacts", []):
        targeted |= set(artefact.get("acIds", []))
    for criterion in state.get("requirementSnapshot", {}).get("acceptanceCriteria", []):
        if not criterion.get("inScope"):
            continue
        ac_id = criterion["acId"]
        if ac_id not in decided:
            gaps.append(_gap("SD-G7", ac_id, "ac-decision", "design", "AC maps to no decision"))
        if ac_id not in targeted:
            gaps.append(_gap("SD-G7", ac_id, "ac-target", "design", "AC maps to no implementation target"))
        if ac_id not in covered:
            gaps.append(
                _gap("SD-G7", ac_id, "verification-contract", "verification", "AC has no verification assertion")
            )
    ac_ids = {
        criterion["acId"]
        for criterion in state.get("requirementSnapshot", {}).get("acceptanceCriteria", [])
    }
    for entry in contract:
        unknown = sorted(set(entry.get("acIds", [])) - ac_ids)
        for ac_id in unknown:
            gaps.append(
                _gap(
                    "SD-G7",
                    entry["verificationId"],
                    "verification-contract",
                    "verification",
                    f"verification references unknown AC {ac_id}",
                )
            )
    return gaps


def gate_g8(
    state: dict[str, Any],
    rule_map: dict[str, Any],
    definitions: dict[str, str],
    applicable_concerns: Iterable[str],
) -> list[dict[str, str]]:
    """SD-G8 — rules and limitations."""
    gaps: list[dict[str, str]] = []
    required = set(applicable_rule_ids(state, rule_map, applicable_concerns))
    for rule_id, entry in rule_map["manualApplicability"].items():
        if entry["blockingSemantics"] == "designer-declared-verdict-required":
            required.add(rule_id)
    verdicts = {item["ruleId"]: item for item in state.get("applicableRules", [])}
    for rule_id in sorted(required):
        verdict = verdicts.get(rule_id)
        if verdict is None:
            registry = rule_map["rules"].get(rule_id) or rule_map["manualApplicability"][rule_id]
            gaps.append(
                _gap(
                    "SD-G8",
                    rule_id,
                    "rule-verdict",
                    registry.get("route", "design"),
                    "applicable rule has no verdict",
                )
            )
            continue
        if verdict["verdict"] == "violated":
            gaps.append(_gap("SD-G8", rule_id, "rule-verdict", "design", "hard rule is violated"))
        elif verdict["verdict"] == "tension" and not (
            verdict.get("mitigation") or verdict.get("humanReceiptRef")
        ):
            gaps.append(
                _gap("SD-G8", rule_id, "rule-verdict", "design", "tension has no mitigation or human decision")
            )
        elif verdict["verdict"] == "not-applicable" and not verdict.get("notApplicableReason"):
            gaps.append(
                _gap(
                    "SD-G8",
                    rule_id,
                    "rule-verdict",
                    "design",
                    "an applicable rule was marked not-applicable without a changed applicability fact",
                )
            )
        expected = definitions.get(rule_id)
        if expected and verdict.get("definitionDigest") != expected:
            gaps.append(
                _gap(
                    "SD-G8",
                    rule_id,
                    "rule-definition-digest",
                    "design",
                    "the rule text changed after the verdict was recorded",
                )
            )
    for verdict in state.get("applicableRules", []):
        if verdict["ruleId"] not in definitions:
            gaps.append(
                _gap("SD-G8", verdict["ruleId"], "rule-verdict", "design", "verdict names an unknown rule")
            )
    for limitation in state.get("limitationRefs", []):
        if not limitation.get("affectedRefs"):
            gaps.append(
                _gap(
                    "SD-G8",
                    limitation["limitationId"],
                    "limitation-link",
                    "design",
                    "limitation is not linked to an affected component, decision or AC",
                )
            )
        if not (
            limitation.get("mitigationRef")
            or limitation.get("acceptedRiskReceiptRef")
            or limitation.get("verificationRefs")
        ):
            gaps.append(
                _gap(
                    "SD-G8",
                    limitation["limitationId"],
                    "limitation-link",
                    "design",
                    "limitation has neither mitigation, accepted risk nor verification consequence",
                )
            )
    return gaps


def gate_g9(state: dict[str, Any], design_text: str | None) -> list[dict[str, str]]:
    """SD-G9 — questions and document integrity."""
    gaps: list[dict[str, str]] = []
    for question in state.get("questions", []):
        if question["materiality"] != "blocking":
            continue
        if question["status"] in ("open", "contested", "stale", "needs-human"):
            route = "human-input" if question["status"] == "needs-human" else question["route"]
            gaps.append(
                _gap(
                    "SD-G9",
                    question["questionId"],
                    "question-closure",
                    route,
                    f"blocking question is {question['status']}; an owner route is not an answer",
                )
            )
    if design_text is None:
        gaps.append(_gap("SD-G9", "design.md", "design-document", "design", "the design document is missing"))
        return gaps
    text = normalize_document(design_text)
    authored = GENERATED_BLOCK.sub("", text)
    for match in PLACEHOLDER.finditer(authored):
        gaps.append(
            _gap(
                "SD-G9",
                "design.md",
                "placeholder",
                "design",
                f"unresolved placeholder {match.group(0)!r} in authored narrative",
            )
        )
        break
    for decision in state.get("decisions", []):
        anchor = decision["designAnchor"].lstrip("#")
        if anchor not in authored:
            gaps.append(
                _gap(
                    "SD-G9",
                    decision["decisionId"],
                    "design-anchor",
                    "design",
                    f"decision anchor {decision['designAnchor']} is not present in the narrative",
                )
            )

    # Every implementation target must be visible in a table. The tables are projections, so
    # this checks the ENTITIES that feed them — an out-of-scope disposition on a component the
    # design still mutates would silently drop it from Solution Artefacts.
    rendered_components = {
        component["componentId"]
        for component in _components(state)
        if component.get("disposition") != "out-of-scope"
    }
    for component in _components(state):
        if component.get("action") in MUTATING_ACTIONS and component["componentId"] not in rendered_components:
            gaps.append(
                _gap(
                    "SD-G9",
                    component["componentId"],
                    "artefact-coverage",
                    "design",
                    "a component the design creates, modifies or deletes is marked out-of-scope, "
                    "so it would never appear in Solution Artefacts",
                )
            )
    for artefact in state.get("configurationArtefacts", []):
        if artefact["action"] in MUTATING_CONFIG_ACTIONS and not artefact.get("description"):
            gaps.append(
                _gap(
                    "SD-G9",
                    artefact["configurationArtefactId"],
                    "artefact-coverage",
                    "design",
                    "a record change with no description renders an empty Configuration "
                    "Artefacts row, which tells a human nothing",
                )
            )
    return gaps


def risk_classification(state: dict[str, Any]) -> dict[str, Any]:
    """SD-G10 — selects the next transition; never blocks candidate creation."""
    triggers: list[str] = []
    computed = concern_applicability(state)
    for component in _in_scope_components(state):
        if component["action"] not in MUTATING_ACTIONS:
            continue
        artefact_type = component.get("artefactType", "")
        if artefact_type in AUTOMATION_ARTEFACTS and component.get("hostObjectOwnership") in (
            "package-owned",
            "unknown",
        ):
            triggers.append(f"automation-on-package-boundary:{component['componentId']}")
        if artefact_type in SECURITY_ARTEFACTS:
            triggers.append(f"security-or-sharing-change:{component['componentId']}")
        if artefact_type in INTEGRATION_ARTEFACTS and artefact_type != "ApexClass":
            triggers.append(f"public-integration-contract:{component['componentId']}")
        if component.get("extensionPointStatus") in ("unavailable", "unknown") and (
            component.get("hostObjectOwnership") == "package-owned"
        ):
            triggers.append(f"closed-package-surface:{component['componentId']}")
    for artefact in state.get("configurationArtefacts", []):
        if artefact["action"] in ("delete-records", "retire"):
            triggers.append(f"irreversible-data-change:{artefact['configurationArtefactId']}")
        if artefact["action"] in MUTATING_CONFIG_ACTIONS:
            classification = next(
                (
                    item
                    for item in state.get("dataClassifications", [])
                    if item["classificationId"] == artefact["classificationRef"]
                ),
                None,
            )
            if classification and classification.get("dataRole") in ("configuration", "reference-data"):
                triggers.append(
                    f"configuration-precedence-impact:{artefact['configurationArtefactId']}"
                )
    for receipt in state.get("evidenceRefs", []):
        if receipt["status"] == "contested":
            triggers.append(f"contested-evidence:{receipt['receiptId']}")
    for risk in state.get("riskObligations", []):
        if risk["status"] == "accepted" and risk["severity"] == "high":
            triggers.append(f"accepted-high-risk:{risk['riskId']}")
    if computed["volume-and-performance"]["applicable"] and not any(
        probe["kind"] in ("object-baseline", "eligibility-count") for probe in state.get("probes", [])
    ):
        triggers.append("unknown-production-volume")
    deduped = sorted(set(triggers))
    return {"tier": "high" if deduped else "standard", "triggers": deduped}


ROUTE_PRIORITY = ("requirements", "grounding", "design", "verification", "human-input")


def next_focus(gaps: list[dict[str, str]]) -> str:
    """Deterministic draft focus (§8.2). The model never sets this."""
    routes = {gap["route"] for gap in gaps}
    for route in ROUTE_PRIORITY:
        if route in routes:
            return route
    return "none"


def evaluate(
    state: dict[str, Any],
    *,
    design_text: str | None,
    capabilities: dict[str, Any] | None = None,
    rule_map: dict[str, Any] | None = None,
    definitions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run every computed gate against one state/document snapshot. Read-only.

    Returns `{"result": READY|OPEN|MALFORMED, "gaps": [...], "nextFocus": ..., ...}`.
    """
    capabilities = capabilities or load_capabilities()
    rule_map = rule_map or load_rule_map()
    definitions = definitions if definitions is not None else canonical_rule_definitions()
    try:
        validate_against(state, STATE_SCHEMA, "solution design state")
    except SolutionDesignError as exc:
        return {
            "result": "MALFORMED",
            "gaps": [_gap("SD-SCHEMA", "solutionDesign", "schema-valid-state", "design", str(exc))],
            "nextFocus": "design",
            "gateEvaluatorVersion": capabilities["gateEvaluatorVersion"],
            "capabilityManifestDigest": capability_digest(capabilities),
            "riskClassification": {"tier": "standard", "triggers": []},
            "applicableConcerns": [],
        }
    computed = concern_applicability(state)
    applicable_concerns = [profile for profile, verdict in computed.items() if verdict["applicable"]]
    gaps: list[dict[str, str]] = []
    gaps += gate_g0(state, capabilities)
    gaps += gate_g1(state)
    gaps += gate_g2(state)
    gaps += gate_g3(state)
    gaps += gate_g4(state)
    gaps += gate_g5(state)
    gaps += gate_g6(state)
    gaps += gate_g7(state)
    gaps += gate_g8(state, rule_map, definitions, applicable_concerns)
    gaps += gate_g9(state, design_text)
    # §15.4: repeated sampling that changes nothing is a loop, not diligence. Route it to a
    # human instead of letting the designer issue unbounded SOQL against the same question.
    for stalled in no_progress_questions(state):
        gaps.append(
            _gap(
                "SD-G4",
                stalled["questionId"],
                "no-progress",
                "human-input",
                f"{stalled['attempts']} probes have not moved this question "
                f"({stalled['unhelpful']} inconclusive or without material impact); it needs a "
                f"human or vendor authority, not another query",
            )
        )
    return {
        "result": "READY" if not gaps else "OPEN",
        "gaps": gaps,
        "nextFocus": next_focus(gaps),
        "gateEvaluatorVersion": capabilities["gateEvaluatorVersion"],
        "capabilityManifestDigest": capability_digest(capabilities),
        "riskClassification": risk_classification(state),
        "applicableConcerns": sorted(applicable_concerns),
    }


def human_only_blockers(gaps: list[dict[str, str]]) -> bool:
    """True when every remaining blocking gap needs human or vendor authority (§9.2 design_submit)."""
    return bool(gaps) and all(gap["route"] == "human-input" for gap in gaps)


def transition_allowed(current: str, target: str) -> bool:
    if current not in ALLOWED_TRANSITIONS:
        raise SolutionDesignError(f"unknown state {current}")
    if target not in STATES:
        raise SolutionDesignError(f"unknown state {target}")
    return target in ALLOWED_TRANSITIONS[current]


# --------------------------------------------------------------------------------------
# Candidate binding and targeted invalidation
# --------------------------------------------------------------------------------------


def applicable_policy_snapshot(
    state: dict[str, Any],
    rule_map: dict[str, Any],
    definitions: dict[str, str],
    applicable_concerns: Iterable[str],
) -> dict[str, Any]:
    selected = set(applicable_rule_ids(state, rule_map, applicable_concerns))
    for rule_id, entry in rule_map["manualApplicability"].items():
        if entry["blockingSemantics"] == "designer-declared-verdict-required":
            selected.add(rule_id)
    verdicts = {item["ruleId"]: item for item in state.get("applicableRules", [])}
    rules = []
    for rule_id in sorted(selected):
        verdict = verdicts.get(rule_id, {})
        registry = rule_map["rules"].get(rule_id) or rule_map["manualApplicability"][rule_id]
        rules.append(
            {
                "ruleId": rule_id,
                "severity": registry["severity"],
                "verdict": verdict.get("verdict", "honored"),
                "definitionDigest": definitions.get(rule_id, verdict.get("definitionDigest", "")),
            }
        )
    snapshot = {
        "rules": rules,
        "limitationDigests": sorted(
            sd_digest(limitation) for limitation in state.get("limitationRefs", [])
        ),
        "riskProfileDigests": sorted(
            sd_digest({"profileId": risk["profileId"], "requiredClosures": risk["requiredClosures"]})
            for risk in state.get("riskObligations", [])
        ),
        "sourceAuthorityPolicyVersion": SOURCE_AUTHORITY_POLICY_VERSION,
    }
    snapshot["applicablePolicyDigest"] = sd_digest(
        {key: value for key, value in snapshot.items() if key != "applicablePolicyDigest"}
    )
    return snapshot


def candidate_digest(digest_input: dict[str, Any]) -> str:
    """SHA-256 over sd-c14n-v1 bytes. The Node wrapper never recomputes this."""
    return sd_digest(digest_input)


INVALIDATION_SOURCES = (
    "requirement-revision",
    "scope-change",
    "design-narrative",
    "evidence-change",
    "policy-change",
    "verification-change",
    "org-package-fingerprint",
    "capability-or-evaluator-change",
)


def targeted_invalidation(
    state: dict[str, Any], changed_refs: Iterable[str]
) -> dict[str, list[str]]:
    """Which questions, probes, decisions and ACs depend on the changed references.

    A change invalidates only dependent state (§17.5), never every receipt in the case.
    """
    changed = set(changed_refs)
    questions = [
        question["questionId"]
        for question in state.get("questions", [])
        if changed & set(question.get("evidenceRefs", []))
    ]
    probes = [
        probe["probeId"]
        for probe in state.get("probes", [])
        if probe.get("receiptRef") in changed or probe["questionId"] in questions
    ]
    decisions = [
        decision["decisionId"]
        for decision in state.get("decisions", [])
        if changed & set(decision.get("evidenceRefs", []))
        or set(questions) & set(decision.get("questionIds", []))
    ]
    acs = sorted(
        {
            ac_id
            for decision in state.get("decisions", [])
            if decision["decisionId"] in decisions
            for ac_id in decision.get("acIds", [])
        }
    )
    risks = [
        risk["riskId"]
        for risk in state.get("riskObligations", [])
        if changed & set(risk.get("evidenceRefs", []))
    ]
    return {
        "questions": sorted(set(questions)),
        "probes": sorted(set(probes)),
        "decisions": sorted(set(decisions)),
        "acceptanceCriteria": acs,
        "risks": sorted(set(risks)),
    }


def candidate_superseding_change(
    previous: dict[str, Any], current: dict[str, Any], *, previous_design: str, current_design: str
) -> list[str]:
    """Material differences that supersede a pending candidate/approval/handoff (§21.5)."""
    reasons: list[str] = []
    if sd_digest(previous.get("requirementSnapshot")) != sd_digest(current.get("requirementSnapshot")):
        reasons.append("requirement-revision")
    if sd_digest(previous.get("scope")) != sd_digest(current.get("scope")):
        reasons.append("scope-change")
    if sd_digest(previous.get("configurationArtefacts")) != sd_digest(
        current.get("configurationArtefacts")
    ) or sd_digest(previous.get("dataClassifications")) != sd_digest(
        current.get("dataClassifications")
    ):
        reasons.append("scope-change")
    if text_digest(previous_design) != text_digest(current_design):
        reasons.append("design-narrative")
    if sd_digest(previous.get("evidenceRefs")) != sd_digest(current.get("evidenceRefs")):
        reasons.append("evidence-change")
    if sd_digest(previous.get("applicableRules")) != sd_digest(
        current.get("applicableRules")
    ) or sd_digest(previous.get("limitationRefs")) != sd_digest(current.get("limitationRefs")):
        reasons.append("policy-change")
    if sd_digest(previous.get("verificationContract")) != sd_digest(
        current.get("verificationContract")
    ):
        reasons.append("verification-change")
    return sorted(set(reasons))


# --------------------------------------------------------------------------------------
# Case construction and typed mutation
# --------------------------------------------------------------------------------------

EMPTY_REQUIREMENT = {
    "sourceType": "human-request",
    "itemId": None,
    "itemType": None,
    "revision": None,
    "retrievedAt": None,
    "sourceDigest": None,
    "includedItems": [],
    "excludedItems": [],
    "acceptanceCriteria": [],
    "completeness": "absent",
    "attestationRef": None,
    "unresolvedContradictions": [],
    "linkedTestCaseIds": [],
}


def new_case_state(case_id: str, writer_id: str, *, at: str) -> dict[str, Any]:
    """A fresh Design Case. Empty component scope is explicitly permitted (§9.2 design_open)."""
    return {
        "schemaVersion": 1,
        "caseId": case_id,
        "status": "draft",
        "stateSequence": 1,
        "writerAssignment": {
            "writerId": writer_id,
            "assignedAt": at,
            "assignmentSequence": 1,
            "transferReceiptRef": None,
        },
        "nextFocus": "requirements",
        "requirementSnapshot": dict(EMPTY_REQUIREMENT),
        "scope": {"components": [], "frontierComplete": False},
        "configurationArtefacts": [],
        "dataClassifications": [],
        "questions": [],
        "concernCoverage": [],
        "probes": [],
        "decisions": [],
        "riskObligations": [],
        "verificationContract": [],
        "applicableRules": [],
        "limitationRefs": [],
        "evidenceRefs": [],
        "knowledgeCandidates": [],
        "activeCandidateRef": None,
    }


OPERATION_KINDS = (
    "scope-component-upsert",
    "scope-component-disposition",
    "configuration-artefact-upsert",
    "data-classification-upsert",
    "question-upsert",
    "question-answer",
    "concern-disposition",
    "probe-plan",
    "probe-import-receipt",
    "probe-interpret",
    "knowledge-reference-import",
    "repository-source-receipt-import",
    "decision-upsert",
    "risk-resolution",
    "verification-upsert",
    "rule-verdict",
    "limitation-link",
    "human-answer-link",
)

# Operations whose payload can only be produced by the executor. The model names the subject;
# the runtime authors the receipt and substitutes the resolved payload before this module sees
# it. Accepting a model-authored payload here would make prose into evidence.
EXECUTOR_AUTHORED_OPERATIONS = frozenset(
    {
        "probe-import-receipt",
        "knowledge-reference-import",
        "repository-source-receipt-import",
        "human-answer-link",
    }
)

MUTABLE_STATUSES = frozenset({"draft"})

_COLLECTIONS = {
    "scope-component-upsert": ("scope.components", "componentId"),
    "configuration-artefact-upsert": ("configurationArtefacts", "configurationArtefactId"),
    "data-classification-upsert": ("dataClassifications", "classificationId"),
    "question-upsert": ("questions", "questionId"),
    "probe-plan": ("probes", "probeId"),
    "decision-upsert": ("decisions", "decisionId"),
    "verification-upsert": ("verificationContract", "verificationId"),
    "rule-verdict": ("applicableRules", "ruleId"),
    "limitation-link": ("limitationRefs", "limitationId"),
}


def _collection(state: dict[str, Any], dotted: str) -> list[dict[str, Any]]:
    if dotted == "scope.components":
        return state["scope"]["components"]
    return state[dotted]


def _upsert(items: list[dict[str, Any]], key: str, payload: dict[str, Any]) -> None:
    identity = payload.get(key)
    if not identity:
        raise SolutionDesignError(f"operation payload is missing {key}")
    for index, existing in enumerate(items):
        if existing.get(key) == identity:
            items[index] = payload
            return
    items.append(payload)


def _find(items: list[dict[str, Any]], key: str, identity: str) -> dict[str, Any]:
    for item in items:
        if item.get(key) == identity:
            return item
    raise SolutionDesignError(f"{key} {identity} does not exist in this case")


def apply_operations(
    state: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply an atomic list of typed operations to a copy of the state.

    Pure: raises on the first invalid operation and returns a new state otherwise, so the
    caller either commits every operation or none. Closure authority is enforced here, not in
    the tool wrapper — a hard evidence question cannot be closed by model prose at any layer.
    """
    if state["status"] not in MUTABLE_STATUSES:
        raise SolutionDesignError(
            f"a case in state '{state['status']}' is not editable; a revision creates a new draft"
        )
    if not operations:
        raise SolutionDesignError("design_apply requires at least one operation")
    if len(operations) > 200:
        raise SolutionDesignError("design_apply accepts at most 200 operations per call")

    working = json.loads(json.dumps(state))  # deep copy through the closed JSON type set
    for index, operation in enumerate(operations):
        kind = operation.get("kind")
        if kind not in OPERATION_KINDS:
            raise SolutionDesignError(f"operation {index}: unknown kind {kind!r}")
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            raise SolutionDesignError(f"operation {index}: payload must be an object")
        if kind in EXECUTOR_AUTHORED_OPERATIONS and not operation.get("executorAuthored"):
            raise SolutionDesignError(
                f"operation {index}: '{kind}' carries executor-authored evidence and cannot be "
                f"applied from a model-supplied payload"
            )
        try:
            _apply_one(working, kind, payload)
        except SolutionDesignError as exc:
            raise SolutionDesignError(f"operation {index} ({kind}): {exc}") from exc

    working["stateSequence"] = state["stateSequence"] + 1
    return working


def _apply_one(state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    if kind in _COLLECTIONS:
        dotted, key = _COLLECTIONS[kind]
        _upsert(_collection(state, dotted), key, payload)
        return

    if kind == "scope-component-disposition":
        component = _find(state["scope"]["components"], "componentId", payload.get("componentId", ""))
        disposition = payload.get("disposition")
        if disposition not in ("in-scope", "dependency-only", "out-of-scope", "unknown"):
            raise SolutionDesignError(f"unknown disposition {disposition!r}")
        if disposition in ("out-of-scope", "dependency-only") and not payload.get("reason"):
            raise SolutionDesignError("an excluded component needs a reason")
        component["disposition"] = disposition
        component["dispositionReason"] = payload.get("reason")
        if payload.get("frontierComplete") is not None:
            state["scope"]["frontierComplete"] = bool(payload["frontierComplete"])
        return

    if kind == "question-answer":
        question = _find(state["questions"], "questionId", payload.get("questionId", ""))
        answer = payload.get("answer")
        if not answer:
            raise SolutionDesignError("an answer is required")
        refs = payload.get("evidenceRefs") or []
        evidence = _evidence_index(state)
        eligible = [
            ref
            for ref in refs
            if ref in evidence
            and evidence_eligible(evidence[ref], authorities=question["requiredAuthority"])[0]
        ]
        question["answer"] = answer
        question["evidenceRefs"] = list(refs)
        question["limitations"] = list(payload.get("limitations") or [])
        if eligible:
            question["status"] = "closed"
            question["closureAuthority"] = evidence[eligible[0]]["sourceType"]
            return
        if question["materiality"] == "advisory":
            question["status"] = "closed"
            question["closureAuthority"] = None
            return
        # A blocking question with no eligible receipt is routed, never closed.
        if set(question["requiredAuthority"]) & HUMAN_AUTHORITIES:
            question["status"] = "needs-human"
            question["route"] = "human-input"
        else:
            question["status"] = "evidence-planned"
        question["closureAuthority"] = None
        return

    if kind == "concern-disposition":
        profile = payload.get("profileId")
        if profile not in CONCERN_PROFILES:
            raise SolutionDesignError(f"unknown concern profile {profile!r}")
        entry = {
            "concernId": payload.get("concernId") or "COV-" + profile.upper(),
            "profileId": profile,
            "applicability": payload.get("applicability", "applicable"),
            "status": payload.get("status", "open"),
            "triggerRefs": list(payload.get("triggerRefs") or []),
            "treatmentRefs": list(payload.get("treatmentRefs") or []),
            "questionRefs": list(payload.get("questionRefs") or []),
            "riskRefs": list(payload.get("riskRefs") or []),
            "verificationRefs": list(payload.get("verificationRefs") or []),
            "notApplicableReason": payload.get("notApplicableReason"),
        }
        _upsert(state["concernCoverage"], "profileId", entry)
        return

    if kind == "probe-import-receipt":
        probe = _find(state["probes"], "probeId", payload.get("probeId", ""))
        receipt = payload.get("evidenceRef")
        if not isinstance(receipt, dict):
            raise SolutionDesignError("an imported receipt reference is required")
        _upsert(state["evidenceRefs"], "receiptId", receipt)
        probe["receiptRef"] = receipt["receiptId"]
        probe["status"] = "imported"
        if payload.get("replaySpec") is not None:
            probe["replaySpec"] = payload["replaySpec"]
        if payload.get("queryDigest") is not None:
            probe["queryDigest"] = payload["queryDigest"]
        return

    if kind == "probe-interpret":
        probe = _find(state["probes"], "probeId", payload.get("probeId", ""))
        fitness = payload.get("fitnessVerdict")
        if fitness not in ("fit", "fit-with-constraints", "not-fit", "inconclusive"):
            raise SolutionDesignError(f"unknown fitness verdict {fitness!r}")
        impact = payload.get("decisionImpact")
        if impact not in (
            "changed-scope",
            "changed-option",
            "changed-risk",
            "changed-verification",
            "confirmed-premise",
            "no-material-impact",
        ):
            raise SolutionDesignError(f"unknown decision impact {impact!r}")
        if probe["status"] not in ("imported", "interpreted", "closed"):
            raise SolutionDesignError("a probe must carry a receipt before it can be interpreted")
        probe["fitnessVerdict"] = fitness
        probe["decisionImpact"] = impact
        probe["status"] = "closed" if fitness in ("fit", "fit-with-constraints") else "interpreted"
        if payload.get("recheckPlan") is not None:
            probe["recheckPlan"] = payload["recheckPlan"]
        return

    if kind in ("knowledge-reference-import", "repository-source-receipt-import"):
        receipt = payload.get("evidenceRef")
        if not isinstance(receipt, dict):
            raise SolutionDesignError("an executor-authored receipt reference is required")
        _upsert(state["evidenceRefs"], "receiptId", receipt)
        return

    if kind == "human-answer-link":
        receipt = payload.get("evidenceRef")
        if not isinstance(receipt, dict):
            raise SolutionDesignError("an executor-authored human receipt reference is required")
        _upsert(state["evidenceRefs"], "receiptId", receipt)
        target = payload.get("target") or {}
        kind_of_target = target.get("kind")
        if kind_of_target == "question":
            question = _find(state["questions"], "questionId", target.get("id", ""))
            question["evidenceRefs"] = sorted(set(question["evidenceRefs"]) | {receipt["receiptId"]})
            eligible, _reason = evidence_eligible(receipt, authorities=question["requiredAuthority"])
            if eligible:
                question["status"] = "closed"
                question["closureAuthority"] = receipt["sourceType"]
                question["answer"] = payload.get("answer") or question["answer"]
        elif kind_of_target == "risk":
            risk = _find(state["riskObligations"], "riskId", target.get("id", ""))
            risk["acceptedRiskReceiptRef"] = receipt["receiptId"]
            risk["status"] = "accepted"
        elif kind_of_target == "requirement":
            state["requirementSnapshot"]["attestationRef"] = receipt["receiptId"]
        elif kind_of_target == "rule":
            rule = _find(state["applicableRules"], "ruleId", target.get("id", ""))
            rule["humanReceiptRef"] = receipt["receiptId"]
        else:
            raise SolutionDesignError(f"unknown human-answer target {kind_of_target!r}")
        return

    if kind == "risk-resolution":
        risk = _find(state["riskObligations"], "riskId", payload.get("riskId", ""))
        status = payload.get("status")
        if status not in ("open", "mitigated", "accepted", "not-applicable"):
            raise SolutionDesignError(f"unknown risk status {status!r}")
        if status == "accepted" and not risk.get("acceptedRiskReceiptRef"):
            raise SolutionDesignError(
                "accepting a risk needs a pre-candidate human authority receipt; link it first"
            )
        risk["status"] = status
        if payload.get("mitigationDesignRef") is not None:
            risk["mitigationDesignRef"] = payload["mitigationDesignRef"]
        if payload.get("satisfiedClosures") is not None:
            risk["satisfiedClosures"] = list(payload["satisfiedClosures"])
        if payload.get("verificationRefs") is not None:
            risk["verificationRefs"] = list(payload["verificationRefs"])
        return

    raise SolutionDesignError(f"operation kind {kind!r} has no implementation")


# --------------------------------------------------------------------------------------
# Generated-section renderers (§20)
# --------------------------------------------------------------------------------------

GENERATED_SECTIONS = (
    "ACCEPTANCE-CRITERIA",
    "CURRENT-STATE-GROUNDING",
    "DATA-CLASSIFICATIONS",
    "CONCERN-COVERAGE",
    "SOLUTION-ARTEFACTS",
    "CONFIGURATION-ARTEFACTS",
    "DECISIONS",
    "RISKS-LIMITATIONS",
    "VERIFICATION-CONTRACT",
    "EVIDENCE-APPENDIX",
)

ACTION_LABELS = {
    "use": "Reuse",
    "create": "Create",
    "modify": "Modify",
    "delete": "Delete",
    "retire": "Retire",
    "dependency-only": "Dependency only",
}
CONFIG_ACTION_LABELS = {
    "create-records": "Create records",
    "modify-records": "Modify records",
    "delete-records": "Delete records",
    "reuse": "Reuse",
    "retire": "Retire",
    "dependency-only": "Dependency only",
}


def _cell(value: Any) -> str:
    """Render one table cell so no authored value can break the row or the marker contract."""
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value) if value else "—"
    else:
        text = str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = text.replace("|", "\\|").replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return text.strip() or "—"


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    body = [f"| {' | '.join(_cell(cell) for cell in row)} |" for row in rows]
    if not body:
        body = [f"| {' | '.join('—' for _ in headers)} |"]
    return "\n".join(lines + body)


def render_section(name: str, state: dict[str, Any]) -> str:
    if name == "ACCEPTANCE-CRITERIA":
        decisions_by_ac: dict[str, list[str]] = {}
        for decision in state["decisions"]:
            for ac_id in decision["acIds"]:
                decisions_by_ac.setdefault(ac_id, []).append(decision["decisionId"])
        verifications_by_ac: dict[str, list[str]] = {}
        for entry in state["verificationContract"]:
            for ac_id in entry["acIds"]:
                verifications_by_ac.setdefault(ac_id, []).append(entry["verificationId"])
        return _table(
            ["AC ID", "Source item", "Requirement summary", "In scope", "Decision refs", "Verification refs"],
            [
                [
                    criterion["acId"],
                    criterion["sourceItemId"],
                    criterion["summary"],
                    "yes" if criterion["inScope"] else "no",
                    decisions_by_ac.get(criterion["acId"]),
                    verifications_by_ac.get(criterion["acId"]),
                ]
                for criterion in state["requirementSnapshot"]["acceptanceCriteria"]
            ],
        )
    if name == "CURRENT-STATE-GROUNDING":
        evidence = _evidence_index(state)
        rows = []
        for question in state["questions"]:
            first = next((evidence[ref] for ref in question["evidenceRefs"] if ref in evidence), None)
            rows.append(
                [
                    question["question"],
                    question["answer"] if question["status"] == "closed" else f"[{question['status']}]",
                    question["closureAuthority"] or question["requiredAuthority"],
                    question["evidenceRefs"],
                    (first or {}).get("status"),
                    question["limitations"],
                ]
            )
        return _table(
            ["Question", "Answer/observation", "Authority", "Evidence ref", "Freshness", "Limitations"],
            rows,
        )
    if name == "DATA-CLASSIFICATIONS":
        return _table(
            ["Object / Slice", "Schema Ownership", "Data Stewardship", "Data Role", "Assurance", "Evidence", "Notes"],
            [
                [
                    item["objectApiName"]
                    + (f" — {item['slice']['predicateTemplate']}" if item.get("slice") else ""),
                    item["schemaOwnership"],
                    item["dataStewardship"],
                    item["dataRole"],
                    item["assurance"],
                    item["evidenceRefs"],
                    item["limitations"],
                ]
                for item in state["dataClassifications"]
            ],
        )
    if name == "CONCERN-COVERAGE":
        computed = concern_applicability(state)
        rows = []
        for entry in state["concernCoverage"]:
            if entry["applicability"] == "not-applicable" and not computed[entry["profileId"]][
                "applicable"
            ]:
                treatment = entry["notApplicableReason"]
            else:
                treatment = entry["treatmentRefs"]
            rows.append(
                [
                    entry["profileId"],
                    entry["applicability"],
                    treatment,
                    (entry["questionRefs"] or []) + (entry["riskRefs"] or []),
                    entry["verificationRefs"],
                ]
            )
        return _table(
            ["Concern", "Applicability", "Treatment / decision", "Questions / risks", "Verification"],
            rows,
        )
    if name == "SOLUTION-ARTEFACTS":
        rows = []
        for component in state["scope"]["components"]:
            if component["disposition"] == "out-of-scope":
                continue
            api_name = component["apiName"]
            if component.get("provisionalApiName"):
                api_name = f"{api_name} (PROVISIONAL)"
            rows.append(
                [
                    component["objectApiName"],
                    component["artefactType"],
                    api_name,
                    ACTION_LABELS[component["action"]],
                    component["description"],
                ]
            )
        return _table(["Object", "Artefact Type", "API Name", "Action", "Description"], rows)
    if name == "CONFIGURATION-ARTEFACTS":
        classifications = {item["classificationId"]: item for item in state["dataClassifications"]}
        rows = []
        for artefact in state["configurationArtefacts"]:
            classification = classifications.get(artefact["classificationRef"], {})
            slice_text = ", ".join(artefact["naturalKeyFields"]) or "—"
            if classification.get("slice"):
                slice_text = classification["slice"]["predicateTemplate"]
            rows.append(
                [
                    artefact["objectApiName"],
                    slice_text,
                    CONFIG_ACTION_LABELS[artefact["action"]],
                    artefact["description"],
                ]
            )
        return _table(
            ["Object", "Configuration Slice / Natural Key", "Action", "Description"], rows
        )
    if name == "DECISIONS":
        return _table(
            ["Decision ID", "Decision", "Rationale", "Alternatives rejected", "Evidence", "ACs", "Risks"],
            [
                [
                    decision["decisionId"],
                    decision["summary"],
                    decision["rationaleSummary"],
                    decision["alternativeRefs"] or decision["trivialityReason"],
                    decision["evidenceRefs"],
                    decision["acIds"],
                    decision["riskRefs"],
                ]
                for decision in state["decisions"]
            ],
        )
    if name == "RISKS-LIMITATIONS":
        rows = [
            [
                risk["riskId"],
                "risk",
                risk["summary"],
                risk["impact"],
                risk["mitigationDesignRef"] or risk["acceptedRiskReceiptRef"],
                risk["evidenceRefs"],
                risk["verificationRefs"],
            ]
            for risk in state["riskObligations"]
        ]
        rows += [
            [
                limitation["limitationId"],
                limitation["class"],
                limitation["summary"],
                limitation["impact"],
                limitation.get("mitigationRef") or limitation.get("acceptedRiskReceiptRef"),
                limitation.get("sourceAuthority"),
                limitation.get("verificationRefs"),
            ]
            for limitation in state["limitationRefs"]
        ]
        return _table(
            ["ID", "Type", "Risk / limitation", "Impact", "Mitigation / acceptance", "Evidence", "Verification"],
            rows,
        )
    if name == "VERIFICATION-CONTRACT":
        return _table(
            ["Verification ID", "AC", "Assertion", "Method", "Pass criteria", "Expected evidence", "Executor / Stage"],
            [
                [
                    entry["verificationId"],
                    entry["acIds"],
                    entry["assertion"],
                    entry["method"],
                    entry["passCriteria"],
                    entry["expectedEvidenceType"],
                    f"{entry['executorRole']} / {entry['stage']}",
                ]
                for entry in state["verificationContract"]
            ],
        )
    if name == "EVIDENCE-APPENDIX":
        return _table(
            ["Evidence ID", "Source type", "Subject", "Observed/source revision", "Completeness", "Freshness", "Limitations"],
            [
                [
                    receipt["receiptId"],
                    receipt["sourceType"],
                    (receipt["questionRefs"] or []) + (receipt["probeRefs"] or []),
                    receipt["observedAt"],
                    receipt["completeness"],
                    receipt["status"],
                    receipt["assurance"],
                ]
                for receipt in state["evidenceRefs"]
            ],
        )
    raise SolutionDesignError(f"unknown generated section {name!r}")


def render_generated_sections(text: str, state: dict[str, Any]) -> str:
    """Replace the body of every generated marker block with its current projection.

    Content inside the markers is a projection, never author input: a manual edit is
    overwritten and cannot change structured scope, the evidence manifest or the candidate
    digest indirectly. Narrative outside the markers is never reformatted.
    """
    normalized = normalize_document(text)

    def replace(match: "re.Match[str]") -> str:
        name = match.group("name")
        if name not in GENERATED_SECTIONS:
            return match.group(0)
        body = render_section(name, state)
        return (
            f"<!-- BEGIN GENERATED:{name} -->\n{body}\n<!-- END GENERATED:{name} -->"
        )

    return GENERATED_BLOCK.sub(replace, normalized)


DESIGN_SCAFFOLD_SECTIONS = (
    ("1. Executive summary", None),
    ("2. Problem and measurable outcome", None),
    ("3. Requirement scope and Acceptance Criteria", "ACCEPTANCE-CRITERIA"),
    ("4. Current state and grounding", "CURRENT-STATE-GROUNDING"),
    ("5. Configuration and data architecture", "DATA-CLASSIFICATIONS"),
    ("6. Options considered", None),
    ("7. Chosen approach", "CONCERN-COVERAGE"),
    ("8. Solution Artefacts", "SOLUTION-ARTEFACTS"),
    ("9. Configuration Artefacts", "CONFIGURATION-ARTEFACTS"),
    ("10. Detailed design and interactions", None),
    ("11. Security, transactions, volume and error handling", None),
    ("12. Decisions", "DECISIONS"),
    ("13. Risks and Known Limitations", "RISKS-LIMITATIONS"),
    ("14. Verification Contract", "VERIFICATION-CONTRACT"),
    ("15. Rollout, migration and rollback", None),
    ("16. Open questions", None),
    ("17. Evidence appendix", "EVIDENCE-APPENDIX"),
)


def design_scaffold(case_id: str, title: str, state: dict[str, Any]) -> str:
    """The §20.1 document skeleton with empty generated blocks, ready for human narrative."""
    parts = [f"# Solution Design — {title}", "", f"Case: `{case_id}`", ""]
    for heading, section in DESIGN_SCAFFOLD_SECTIONS:
        parts.append(f"## {heading}")
        parts.append("")
        if section:
            parts.append(f"<!-- BEGIN GENERATED:{section} -->")
            parts.append(render_section(section, state))
            parts.append(f"<!-- END GENERATED:{section} -->")
            parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------
# Requirement snapshot and AC lineage (§10.1)
# --------------------------------------------------------------------------------------


def _ac_id(project: str, item_id: int, local_key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{project}-{item_id}-{local_key}").strip("-")
    return f"AC-{slug}"[:120]


def reconcile_acceptance_criteria(
    previous: list[dict[str, Any]], snapshot: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Map adapter output onto stable AC identities.

    Identity and content are separate. A child work item that represents one AC derives its
    identity from project/item id plus a durable source-local key, so editing its text changes
    `textDigest` and not `acId`.

    An unkeyed rich-text field has no such durable key, so the reconciliation is conservative:
    a clause whose normalized fingerprint matches exactly one previous clause keeps that
    identity; anything else — a split, a merge, a rewrite, or two clauses collapsing to the
    same fingerprint — is reported for human reconciliation rather than silently reassigned.
    Ordinal position is never identity, because a reorder would then rewrite every AC.
    """
    project = str(snapshot.get("project") or "local")
    criteria: list[dict[str, Any]] = []
    ambiguities: list[str] = []
    previous_by_lineage = {item["lineageKey"]: item for item in previous}

    for child in snapshot.get("children", []):
        lineage = f"ado:{project}:{child['id']}:work-item"
        existing = previous_by_lineage.get(lineage)
        summary = child.get("acceptanceCriteria") or child.get("title") or ""
        criteria.append(
            {
                "acId": existing["acId"] if existing else _ac_id(project, child["id"], "work-item"),
                "sourceItemId": child["id"],
                "sourceLocalKey": "work-item",
                "lineageKey": lineage,
                "sourceRevision": child.get("revision"),
                "summary": summary[:2000] or f"Child work item {child['id']}",
                "textDigest": "sha256:" + hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                "inScope": existing["inScope"] if existing else True,
            }
        )

    clauses = snapshot.get("rootAcceptanceCriteria", [])
    previous_clauses = [
        item for item in previous if item["sourceLocalKey"].startswith("ac-clause")
    ]
    fingerprint_index: dict[str, list[dict[str, Any]]] = {}
    for item in previous_clauses:
        fingerprint_index.setdefault(item.get("fingerprint", item["textDigest"]), []).append(item)

    for clause in clauses:
        fingerprint = clause["fingerprint"]
        matches = fingerprint_index.get(fingerprint, [])
        if len(matches) == 1:
            identity = matches[0]["acId"]
            lineage = matches[0]["lineageKey"]
        elif len(matches) > 1:
            ambiguities.append(
                f"acceptance-criteria clause {clause['ordinal']} matches {len(matches)} prior "
                f"clauses; human reconciliation required before this snapshot can be trusted"
            )
            continue
        else:
            local_key = f"ac-clause-{clause['ordinal']}"
            identity = _ac_id(project, snapshot["itemId"], local_key)
            lineage = f"ado:{project}:{snapshot['itemId']}:{local_key}"
            if previous_clauses and len(previous_clauses) != len(clauses):
                ambiguities.append(
                    f"acceptance-criteria clause count moved from {len(previous_clauses)} to "
                    f"{len(clauses)}; a split, merge or rewrite needs human reconciliation"
                )
        criteria.append(
            {
                "acId": identity,
                "sourceItemId": snapshot["itemId"],
                "sourceLocalKey": f"ac-clause-{clause['ordinal']}",
                "lineageKey": lineage,
                "sourceRevision": snapshot.get("revision"),
                "summary": clause["summary"],
                "textDigest": clause["textDigest"],
                "inScope": True,
            }
        )

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in criteria:
        if item["acId"] in seen:
            ambiguities.append(f"duplicate acceptance-criteria identity {item['acId']}")
            continue
        seen.add(item["acId"])
        deduped.append(item)
    return deduped, sorted(set(ambiguities))


def requirement_snapshot_from_adapter(
    snapshot: dict[str, Any], previous: dict[str, Any], *, at: str
) -> dict[str, Any]:
    """Build the durable requirement snapshot from executor-authored adapter output."""
    criteria, ambiguities = reconcile_acceptance_criteria(
        previous.get("acceptanceCriteria", []), snapshot
    )
    contradictions = list(ambiguities)
    for item_id in snapshot.get("missingDetailItemIds", []):
        contradictions.append(
            f"child work item {item_id} arrived summary-only; a summary child cannot satisfy "
            f"acceptance-criteria completeness"
        )
    return {
        "sourceType": "ado",
        "itemId": snapshot["itemId"],
        "itemType": snapshot.get("itemType") or None,
        "revision": snapshot.get("revision"),
        "retrievedAt": at,
        "sourceDigest": snapshot["sourceDigest"],
        "includedItems": list(snapshot.get("includedItems", [])),
        "excludedItems": list(snapshot.get("excludedItems", [])),
        "acceptanceCriteria": criteria,
        "completeness": "complete"
        if snapshot.get("completeness") == "complete" and criteria and not contradictions
        else ("partial" if criteria else "absent"),
        "attestationRef": previous.get("attestationRef"),
        "unresolvedContradictions": sorted(set(contradictions))[:50],
        "linkedTestCaseIds": sorted(set(snapshot.get("linkedTestCases") or []))[:200],
    }


def requirement_drift(
    snapshot: dict[str, Any], observed_revisions: dict[str, int]
) -> list[str]:
    """Revisions that moved since the snapshot was taken (§25 P3.4)."""
    drifted: list[str] = []
    root_id = snapshot.get("itemId")
    if root_id is not None:
        observed = observed_revisions.get(str(root_id), observed_revisions.get(root_id))
        if observed is not None and observed != snapshot.get("revision"):
            drifted.append(
                f"work item {root_id} moved from revision {snapshot.get('revision')} to {observed}"
            )
    by_item = {
        criterion["sourceItemId"]: criterion["sourceRevision"]
        for criterion in snapshot.get("acceptanceCriteria", [])
        if criterion.get("sourceItemId") and criterion["sourceLocalKey"] == "work-item"
    }
    for item_id, revision in sorted(by_item.items()):
        observed = observed_revisions.get(str(item_id), observed_revisions.get(item_id))
        if observed is not None and observed != revision:
            drifted.append(f"child work item {item_id} moved from revision {revision} to {observed}")
    return drifted


# --------------------------------------------------------------------------------------
# Obligation seeding (§11.1 step 4, §11.3)
# --------------------------------------------------------------------------------------

PACKAGE_QUESTION_ID = "Q-PKG-BOUNDARY"
PACKAGE_QUESTION = (
    "Which supported extension point covers this change on the package-owned or "
    "ownership-unknown surface, and what existing package automation runs in the same "
    "transaction?"
)


def seed_obligations(state: dict[str, Any]) -> dict[str, Any]:
    """Add the obligations the scope implies but nobody authored yet.

    Strictly additive. Seeding never overwrites a disposition the designer recorded, because
    that would let the runtime silently undo a human judgement; it only makes a computed
    obligation visible before the designer trips over it at submit.
    """
    computed = concern_applicability(state)
    declared = {item["profileId"] for item in state.get("concernCoverage", [])}
    for profile, verdict in computed.items():
        if not verdict["applicable"] or profile in declared:
            continue
        state["concernCoverage"].append(
            {
                "concernId": "COV-" + profile.upper(),
                "profileId": profile,
                "applicability": "applicable",
                "status": "open",
                "triggerRefs": list(verdict["triggers"])[:20],
                "treatmentRefs": [],
                "questionRefs": [],
                "riskRefs": [],
                "verificationRefs": [],
                "notApplicableReason": None,
            }
        )

    # A package boundary is the one question this workspace exists to stop people skipping.
    package_facing = [
        component["componentId"]
        for component in _in_scope_components(state)
        if component.get("action") in MUTATING_ACTIONS
        and (
            component.get("componentOwnership") in ("package-owned", "unknown")
            or component.get("hostObjectOwnership") in ("package-owned", "unknown")
        )
    ]
    existing = {question["questionId"] for question in state.get("questions", [])}
    if package_facing and PACKAGE_QUESTION_ID not in existing:
        state["questions"].append(
            {
                "questionId": PACKAGE_QUESTION_ID,
                "question": PACKAGE_QUESTION,
                "materiality": "blocking",
                "requiredAuthority": [
                    "vendor-documentation",
                    "knowledge-entry",
                    "human-sme-attestation",
                ],
                "status": "open",
                "answer": None,
                "closureAuthority": None,
                "evidenceRefs": [],
                "limitations": [],
                "route": "grounding",
            }
        )
    return state


# --------------------------------------------------------------------------------------
# Adaptive sampling (§15)
# --------------------------------------------------------------------------------------

NO_PROGRESS_ATTEMPTS = 2
CONFIG_ROLES = frozenset({"configuration", "reference-data", "mixed"})


def probe_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Probes worth running, derived from what the design is actually deciding.

    Candidates come from open material questions, record-driven configuration and risk
    triggers — never from enumerating fields. A wide object must not produce one obligation per
    field; that is the failure that made the previous sampling advice unusable on a real package.
    Only an activated candidate becomes a tracked probe, and only a tracked probe can block.
    """
    candidates: list[dict[str, Any]] = []
    planned = {(probe["kind"], probe["target"]["objectApiName"]) for probe in state.get("probes", [])}

    def offer(kind: str, obj: str, why: str, question: str | None, requiredness: str) -> None:
        if (kind, obj) in planned:
            return
        planned.add((kind, obj))
        candidates.append(
            {
                "kind": kind,
                "target": {"objectApiName": obj},
                "rationale": why,
                "questionId": question,
                "suggestedRequiredness": requiredness,
            }
        )

    classifications = {item["classificationId"]: item for item in state.get("dataClassifications", [])}
    for artefact in state.get("configurationArtefacts", []):
        obj = artefact["objectApiName"]
        classification = classifications.get(artefact["classificationRef"], {})
        mutating = artefact["action"] in MUTATING_CONFIG_ACTIONS
        if classification.get("assurance") in (None, "unknown"):
            offer(
                "object-baseline",
                obj,
                "the slice classification is unproven, and size plus date span is the cheapest "
                "first observation",
                None,
                "hard" if mutating else "advisory",
            )
            offer(
                "churn-profile",
                obj,
                "change frequency separates admin-maintained configuration from package-seeded "
                "rows far better than row count does",
                None,
                "conditional",
            )
        if classification.get("dataRole") in CONFIG_ROLES and mutating:
            offer(
                "config-effectivity",
                obj,
                "records the design changes may carry effective windows that decide which one "
                "actually applies",
                None,
                "conditional",
            )
            offer(
                "precedence-collision",
                obj,
                "two active records in one scope change the outcome, and the design has to say "
                "which wins",
                None,
                "conditional",
            )
        if artefact.get("naturalKeyFields"):
            offer(
                "key-integrity",
                obj,
                "the design addresses these records by natural key, so nulls or duplicates in it "
                "break the change",
                None,
                "hard" if mutating else "advisory",
            )

    for question in state.get("questions", []):
        if question["status"] not in UNCLOSED_QUESTION_STATUSES:
            continue
        if "org-soql-sample" not in question["requiredAuthority"]:
            continue
        subject = next(
            (
                artefact["objectApiName"]
                for artefact in state.get("configurationArtefacts", [])
                if artefact["objectApiName"].lower() in question["question"].lower()
            ),
            None,
        ) or next(
            (
                component["objectApiName"]
                for component in _in_scope_components(state)
                if component["objectApiName"].lower() in question["question"].lower()
            ),
            None,
        )
        if subject:
            offer(
                "categorical-distribution",
                subject,
                f"open question {question['questionId']} needs an org observation",
                question["questionId"],
                "hard" if question["materiality"] == "blocking" else "advisory",
            )

    for risk in state.get("riskObligations", []):
        if risk["status"] != "open" or risk["severity"] != "high":
            continue
        for component in _in_scope_components(state):
            if component["componentId"] in risk.get("triggerRefs", []):
                offer(
                    "object-baseline",
                    component["objectApiName"],
                    f"high risk {risk['riskId']} depends on the volume this automation will face",
                    None,
                    "conditional",
                )
    return candidates


def no_progress_questions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Questions where repeated sampling has stopped changing anything.

    Issuing more SOQL against a question that two probes already failed to close is not
    diligence, it is a loop. Such a question becomes a human obligation instead.
    """
    stalled: list[dict[str, Any]] = []
    for question in state.get("questions", []):
        if question["status"] in ("closed", "needs-human"):
            continue
        probes = [probe for probe in state.get("probes", []) if probe["questionId"] == question["questionId"]]
        if len(probes) < NO_PROGRESS_ATTEMPTS:
            continue
        unhelpful = [
            probe
            for probe in probes
            if probe.get("fitnessVerdict") == "inconclusive"
            or probe.get("decisionImpact") == "no-material-impact"
        ]
        if len(unhelpful) >= NO_PROGRESS_ATTEMPTS:
            stalled.append(
                {
                    "questionId": question["questionId"],
                    "attempts": len(probes),
                    "unhelpful": len(unhelpful),
                }
            )
    return stalled
