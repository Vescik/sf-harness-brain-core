"""One-file Knowledge Entry executor (T07 P1).

Implements docs/knowledge-one-file-contract.md v1.1: strict canonical parsing, the
three-digest boundary, the append-only approval ledger, computed effectiveness lanes,
and the executor-only write path (entry-draft / entry-approve / entry-revoke) plus the
read commands (entry-status, entry-check, entry-review-render).

Design invariants enforced here, not by callers:
- all structured frontmatter (typeFacts, intentionalErrors, source.*, scope.*) is derived
  by this executor from force-app source via the collector; callers author only body
  prose and candidateKeywords (contract §6.4.6);
- approval binds to reviewedContentDigest and is authoritative in the ledger, latest-wins
  (contract §6.1); byte-replay of previously approved versions is not effective;
- entry-approve is digest-pinned on the command line (contract §6.2);
- the artifacts path is governed: raw edits are denied by the role guard, writes happen
  only here, atomically, with a path<->identity round-trip check (contract §3, §6.4).
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from scripts.knowledge_registry import canonical_digest
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_store.py`
    from knowledge_registry import canonical_digest  # type: ignore

ARTIFACTS_ROOT = ROOT / ".ai/knowledge/artifacts"
LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-ledger.jsonl"
REVIEW_ARTIFACT_ROOT = ROOT / "output/knowledge-approvals"
SCHEMA_DIR = ROOT / "schemas"
LOCAL_CONFIG = ROOT / "config/harness.local.json"
TAXONOMY_PATH = ROOT / ".ai/knowledge/keyword-taxonomy.md"

SENTINEL_PATTERN = re.compile(r"<AGENT_[A-Z0-9_]*>?")
PROSE_CHUNK_LIMIT = 25
MANIFEST_CHUNK_LIMIT = 500
SAFE_NAME_BUDGET = 100
PATH_BUDGET = 200
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}

PROFILES = {
    "Flow": {"id": "salesforce.flow", "version": "1.0.0", "schema": "knowledge-profile-flow.schema.json"},
    "CustomField": {
        "id": "salesforce.custom-field",
        "version": "1.0.0",
        "schema": "knowledge-profile-customfield.schema.json",
    },
}


class StoreError(RuntimeError):
    """Fail-closed executor error; message is the actionable reason."""


import contextlib


@contextlib.contextmanager
def rooted(root: Path):
    """Bind module paths to a different repo root (work_record gates, unit tests)."""
    global ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH
    saved = (ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH)
    ROOT = Path(root).resolve()
    ARTIFACTS_ROOT = ROOT / ".ai/knowledge/artifacts"
    LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-ledger.jsonl"
    REVIEW_ARTIFACT_ROOT = ROOT / "output/knowledge-approvals"
    LOCAL_CONFIG = ROOT / "config/harness.local.json"
    TAXONOMY_PATH = ROOT / ".ai/knowledge/keyword-taxonomy.md"
    try:
        yield
    finally:
        ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH = saved


# --- strict canonical parser (contract §5.6) -------------------------------------------


class StrictLoader(yaml.SafeLoader):
    """YAML 1.2-leaning strict loader: no duplicate keys, no anchors/aliases/merge keys."""

    def compose_node(self, parent, index):  # type: ignore[override]
        if self.check_event(yaml.events.AliasEvent):
            raise StoreError("frontmatter rejects YAML aliases/anchors (contract §5.6)")
        return super().compose_node(parent, index)


def _strict_mapping(loader: StrictLoader, node: yaml.nodes.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key == "<<":
            raise StoreError("frontmatter rejects YAML merge keys (contract §5.6)")
        if key in mapping:
            raise StoreError(f"frontmatter rejects duplicate key {key!r} (contract §5.6)")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_mapping
)
# YAML 1.1 boolean landmines (NO/on/off) stay strings under this narrowed resolver set.
for boolish in "yYnNoO":
    if boolish in StrictLoader.yaml_implicit_resolvers:
        StrictLoader.yaml_implicit_resolvers[boolish] = [
            (tag, regexp)
            for tag, regexp in StrictLoader.yaml_implicit_resolvers[boolish]
            if tag != "tag:yaml.org,2002:bool"
        ]


def split_entry(text: str) -> tuple[dict[str, Any], str]:
    """Exactly one frontmatter block: starts '---\\n', ends first '\\n---\\n'."""
    if not text.startswith("---\n"):
        raise StoreError("entry must start with a '---' frontmatter block")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise StoreError("unterminated frontmatter block")
    # StrictLoader subclasses SafeLoader (no object construction) and additionally rejects
    # duplicate keys, aliases/anchors, and merge keys (contract §5.6).
    loader = StrictLoader(text[4:end + 1])
    try:
        frontmatter = loader.get_single_data()
    finally:
        loader.dispose()
    if not isinstance(frontmatter, dict):
        raise StoreError("frontmatter must be a mapping")
    return frontmatter, text[end + 5:]


def normalize_body(body: str) -> str:
    text = unicodedata.normalize("NFC", body.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n") + "\n" if any(line for line in lines) else ""


# --- identity, safe names, paths (contract §3) -----------------------------------------


def identity_of(metadata_type: str, namespace: str | None, full_name: str) -> str:
    return f"{metadata_type}:{namespace or 'c'}:{full_name}"


def safe_name(full_name: str, identity: str) -> str:
    normalized = unicodedata.normalize("NFKC", full_name)
    encoded = "".join(
        ch if re.fullmatch(r"[A-Za-z0-9_-]", ch) else "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
        for ch in normalized
    )
    suffix = ""
    if len(encoded) > SAFE_NAME_BUDGET or encoded.rstrip(". ") != encoded:
        digest = canonical_digest(unicodedata.normalize("NFKC", identity))[7:15]
        cut = encoded[:SAFE_NAME_BUDGET]
        if "%" in cut[-2:]:  # never split a %XX triplet
            cut = cut[: cut.rindex("%")]
        encoded, suffix = cut.rstrip(". "), f"-{digest}"
    stem = encoded + suffix
    if stem.split("-", 1)[0].upper() in WINDOWS_RESERVED or stem.upper() in WINDOWS_RESERVED:
        stem += "-" + canonical_digest(unicodedata.normalize("NFKC", identity))[7:15]
    return stem


def entry_path(metadata_type: str, namespace: str | None, full_name: str) -> Path:
    identity = identity_of(metadata_type, namespace, full_name)
    path = ARTIFACTS_ROOT / metadata_type / (namespace or "c") / f"{safe_name(full_name, identity)}.md"
    if len(str(path.relative_to(ROOT))) > PATH_BUDGET:
        raise StoreError(f"derived path exceeds {PATH_BUDGET}-char budget for {identity}")
    return path


def assert_no_reparse_points() -> None:
    knowledge_root = ROOT / ".ai/knowledge"
    for path in knowledge_root.rglob("*"):
        if path.is_symlink():
            raise StoreError(f"reparse point/symlink under .ai/knowledge: {path} (contract §3)")


# --- digests (contract §5) -------------------------------------------------------------


def _canonical_facts(frontmatter: dict[str, Any]) -> dict[str, Any]:
    facts = copy.deepcopy(
        {
            "typeFacts": frontmatter.get("typeFacts") or {},
            "intentionalErrors": frontmatter.get("intentionalErrors") or [],
            "limitations": sorted(frontmatter.get("limitations") or []),
            "extractionCoverage": frontmatter.get("extractionCoverage") or {},
            "assurance": frontmatter.get("assurance") or {},
        }
    )
    type_facts = facts["typeFacts"]
    if isinstance(type_facts.get("references"), list):
        type_facts["references"] = sorted(
            type_facts["references"], key=lambda item: (item.get("kind", ""), item.get("target", ""))
        )
    if isinstance(type_facts.get("variables"), list):
        type_facts["variables"] = sorted(
            type_facts["variables"], key=lambda item: item.get("apiName", "")
        )
    for error in facts["intentionalErrors"]:
        if isinstance(error.get("customLabelRefs"), list):
            error["customLabelRefs"] = sorted(error["customLabelRefs"])
    return facts


def facts_digest(frontmatter: dict[str, Any]) -> str:
    return canonical_digest(_canonical_facts(frontmatter))


def semantics_digest(body: str) -> str:
    return canonical_digest(normalize_body(body))


def reviewed_content_digest(frontmatter: dict[str, Any], body: str) -> str:
    subject = frontmatter["subject"]
    profile = frontmatter["profile"]
    return canonical_digest(
        {
            "identity": identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"]),
            "profileMajor": f"{profile['id']}@{profile['version'].split('.', 1)[0]}",
            "factsDigest": facts_digest(frontmatter),
            "semanticsDigest": semantics_digest(body),
            "sensitivity": frontmatter["sensitivity"],
        }
    )


# --- ledger (contract §6.1) ------------------------------------------------------------


def read_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    records = []
    for index, line in enumerate(LEDGER_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("sequence") != index:
            raise StoreError(f"ledger sequence break at line {index} (append-only violated)")
        records.append(record)
    return records


def ledger_latest(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[record["identity"]] = record
    return latest


def append_ledger(entries: list[dict[str, Any]]) -> None:
    records = read_ledger()
    sequence = len(records)
    with LEDGER_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            sequence += 1
            handle.write(json.dumps({"sequence": sequence, **entry}, sort_keys=True) + "\n")


# --- validation and lanes (contract §4) -------------------------------------------------


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate_entry(frontmatter: dict[str, Any], body: str) -> list[str]:
    from jsonschema import Draft202012Validator

    problems: list[str] = []
    envelope = Draft202012Validator(load_schema("knowledge-entry.schema.json"))
    problems.extend(error.message for error in envelope.iter_errors(frontmatter))
    metadata_type = frontmatter.get("subject", {}).get("metadataType")
    profile = PROFILES.get(metadata_type or "")
    if profile is None:
        problems.append(f"unsupported profile for metadataType {metadata_type!r}")
    else:
        profile_validator = Draft202012Validator(load_schema(profile["schema"]))
        payload = {
            "typeFacts": frontmatter.get("typeFacts", {}),
            "intentionalErrors": frontmatter.get("intentionalErrors", []),
        }
        problems.extend(error.message for error in profile_validator.iter_errors(payload))
    raw = yaml.dump(frontmatter, sort_keys=True) + body
    if SENTINEL_PATTERN.search(raw):
        problems.append("unfilled <AGENT_...> sentinel present (contract §6.4.6)")
    sections = [line for line in body.splitlines() if line.startswith("## ")]
    if any(section != "## Purpose" for section in sections):
        problems.append("pilot body may contain only '## Purpose' (contract §2.2)")
    approved_terms = approved_taxonomy_terms()
    for keyword in frontmatter.get("keywords", []):
        if keyword not in approved_terms:
            problems.append(f"keyword {keyword!r} is not in the approved taxonomy")
    return problems


def approved_taxonomy_terms() -> set[str]:
    if not TAXONOMY_PATH.exists():
        return set()
    terms: set[str] = set()
    in_terms = False
    for line in TAXONOMY_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().lower() == "## terms":
            in_terms = True
            continue
        if in_terms and line.startswith("## "):
            break
        if in_terms and line.startswith("- "):
            terms.add(line[2:].split("—", 1)[0].strip().strip("`"))
    return terms


def compute_lane(path: Path, latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_entry(text)
    subject = frontmatter["subject"]
    identity = identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"])
    expected = entry_path(subject["metadataType"], subject.get("namespace"), subject["fullName"])
    result = {"identity": identity, "path": str(path.relative_to(ROOT)), "problems": validate_entry(frontmatter, body)}
    if path.resolve() != expected.resolve():
        result["lane"] = "not-effective"
        result["problems"].append(f"path/identity round-trip failed (expected {expected.relative_to(ROOT)})")
        return result
    if result["problems"]:
        result["lane"] = "not-effective"
        return result
    recomputed = reviewed_content_digest(frontmatter, body)
    result["reviewedContentDigest"] = recomputed
    ledger_record = latest.get(identity)
    if frontmatter["lifecycle"]["state"] == "draft":
        result["lane"] = "draft"
    elif ledger_record is None:
        result["lane"] = "not-effective"
        result["problems"].append("approved state without any ledger record (quarantined)")
    elif ledger_record["action"] == "revoke":
        result["lane"] = "revoked"
    elif ledger_record["reviewedContentDigest"] != recomputed:
        result["lane"] = "not-effective"
        result["problems"].append("recomputed digest is not the latest ledger record")
    elif frontmatter["approval"].get("reviewedContentDigest") != recomputed:
        result["lane"] = "not-effective"
        result["problems"].append("in-file approval mirror mismatches recomputation")
    else:
        current_facts = facts_digest(frontmatter)
        regenerated = regenerate_fragment_digest(frontmatter)
        result["lane"] = "approved-current" if regenerated else "approved-drifted"
        result["factsDigest"] = current_facts
    result["sourceTreeDigest"] = frontmatter["scope"]["sourceTreeDigest"]
    result["profile"] = f"{frontmatter['profile']['id']}@{frontmatter['profile']['version'].split('.', 1)[0]}"
    return result


def lane_for_identity(root: Path, identity: str) -> dict[str, Any] | None:
    """Compute the effectiveness lane for one identity under an explicit repo root."""
    with rooted(root):
        latest = ledger_latest(read_ledger())
        for path in all_entry_paths():
            try:
                lane = compute_lane(path, latest)
            except StoreError:
                continue
            if lane["identity"] == identity:
                return lane
    return None


def regenerate_fragment_digest(frontmatter: dict[str, Any]) -> bool:
    """True when every recorded source fragment still matches the working tree."""
    from scripts.force_app_knowledge import file_digest  # local import: heavy module

    for fragment in frontmatter["source"]["fragments"]:
        fragment_path = ROOT / fragment["path"]
        if not fragment_path.exists():
            return False
        if file_digest(fragment_path) != fragment["sourceDigest"].removeprefix("sha256:"):
            return False
    return True


def all_entry_paths() -> list[Path]:
    if not ARTIFACTS_ROOT.exists():
        return []
    return sorted(ARTIFACTS_ROOT.rglob("*.md"))


# --- collector adapters (contract §6.4.6, §7) ------------------------------------------


def collector_component(metadata_type: str, full_name: str) -> dict[str, Any]:
    from scripts.force_app_knowledge import ForceAppKnowledge

    builder = ForceAppKnowledge(ROOT)
    inventory = builder.inventory()
    wanted = f"{metadata_type}:{full_name}"
    for component in inventory.get("components", []):
        if component.get("id") == wanted:
            return component
    raise StoreError(f"component {wanted} not found in force-app source")


_OPERATION_KINDS = {"lookup": "recordLookup", "create": "recordCreate", "update": "recordUpdate", "delete": "recordDelete"}


def flow_type_facts(component: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    facts = component.get("facts", {})
    references = [
        {
            "kind": ref["kind"],
            "target": ref["target"],
            "assurance": "source-derived-heuristic" if ref.get("heuristic") else "source-exact",
        }
        for ref in component.get("references", [])
    ]
    type_facts: dict[str, Any] = {
        "processType": facts.get("processType") or "Flow",
        "status": facts.get("status") or "Draft",
    }
    trigger = {
        key: value
        for key, value in {
            "object": facts.get("object"),
            "type": facts.get("triggerType"),
            "recordTriggerType": facts.get("recordTriggerType"),
        }.items()
        if value
    }
    if trigger:
        type_facts["trigger"] = trigger
    variables = [
        {
            key: value
            for key, value in {
                "apiName": item.get("name"),
                "dataType": item.get("dataType") or "String",
                "objectType": item.get("objectType"),
                "isInput": item.get("isInput"),
                "isOutput": item.get("isOutput"),
                "isCollection": item.get("isCollection"),
            }.items()
            if value is not None
        }
        for item in facts.get("variables") or []
        if item.get("name")
    ]
    if variables:
        type_facts["variables"] = variables
    operations = [
        {
            key: value
            for key, value in {
                "kind": _OPERATION_KINDS.get(op.get("operation", "")),
                "object": op.get("object"),
                "elementApiName": op.get("element"),
            }.items()
            if value
        }
        for op in facts.get("dataOperations") or []
        if _OPERATION_KINDS.get(op.get("operation", "")) and op.get("object")
    ]
    if operations:
        type_facts["operations"] = operations
    if references:
        type_facts["references"] = references
    heuristic = any(ref["assurance"] == "source-derived-heuristic" for ref in references)
    assurance = {"typeFacts": "source-derived-heuristic" if heuristic else "source-exact"}
    intentional = []
    for item in facts.get("errorCatalog") or []:
        if item.get("kind") != "custom-error":
            continue  # screen-validation and fault-path never enter (contract §7)
        error: dict[str, Any] = {
            "kind": "flow-custom-error",
            "originTag": "customErrors",
            "elementApiName": item.get("component", ""),
            "messageTemplate": item.get("errorMessage", ""),
            "presentation": (
                {"mode": "field", "field": item["fieldSelection"]}
                if item.get("isFieldError") and item.get("fieldSelection")
                else {"mode": "record"}
            ),
            "reachability": {
                "triggerContext": item.get("triggerContext") or "not-derived",
                "decisionGuards": [" -> ".join(p) if isinstance(p, list) else str(p) for p in item.get("paths", [])],
                "truncated": bool(item.get("pathsTruncated")),
            },
            "basis": "source-declared",
            "limitations": [],
        }
        if item.get("componentLabel"):
            error["elementLabel"] = item["componentLabel"]
        if item.get("resolvedErrorMessage"):
            error["resolvedDefaultText"] = item["resolvedErrorMessage"]
        labels = re.findall(r"\$Label\.[A-Za-z0-9_.]+", item.get("errorMessage", ""))
        if labels:
            error["customLabelRefs"] = sorted(set(labels))
        intentional.append(error)
    return type_facts, intentional, assurance


def custom_field_type_facts(component: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    facts = component.get("facts", {})

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    type_facts = {
        key: value
        for key, value in {
            "object": facts.get("object"),
            "type": facts.get("type") or "Text",
            "label": facts.get("label"),
            "required": facts.get("required"),
            "unique": facts.get("unique"),
            "externalId": facts.get("externalId"),
            "encrypted": facts.get("encrypted"),
            "trackHistory": facts.get("trackHistory"),
            "length": as_int(facts.get("length")),
            "precision": as_int(facts.get("precision")),
            "scale": as_int(facts.get("scale")),
            "referenceTo": facts.get("referenceTo"),
            "relationshipName": facts.get("relationshipName"),
            "deleteConstraint": facts.get("deleteConstraint"),
            "controllingField": facts.get("controllingField"),
            "description": facts.get("description"),
            "inlineHelpText": facts.get("inlineHelpText"),
        }.items()
        if value is not None
    }
    if facts.get("formula"):
        type_facts["formula"] = {"returnType": facts.get("type") or "Text"}
    return type_facts, [], {"typeFacts": "source-exact"}


ADAPTERS = {"Flow": flow_type_facts, "CustomField": custom_field_type_facts}


# --- write path -------------------------------------------------------------------------


def render_entry(frontmatter: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.dump(frontmatter, sort_keys=True, allow_unicode=True, default_flow_style=False) + "---\n\n" + normalize_body(body)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    temp.replace(path)


def assert_no_casefold_collision(path: Path) -> None:
    parent = path.parent
    if not parent.exists():
        return
    for sibling in parent.iterdir():
        if sibling != path and sibling.name.casefold() == path.name.casefold():
            raise StoreError(f"case-fold path collision: {sibling.name} vs {path.name} (contract §3)")


def command_entry_draft(args: argparse.Namespace) -> dict[str, Any]:
    if args.namespace == "c":
        raise StoreError("namespace literal 'c' is reserved (contract §2.1)")
    assert_no_reparse_points()
    metadata_type = args.metadata_type
    adapter = ADAPTERS.get(metadata_type)
    profile = PROFILES.get(metadata_type)
    if adapter is None or profile is None:
        raise StoreError(f"unsupported metadata type {metadata_type!r} in pilot (Flow, CustomField)")
    component = collector_component(metadata_type, args.full_name)
    type_facts, intentional, assurance = adapter(component)
    purpose = Path(args.purpose_file).read_text(encoding="utf-8") if args.purpose_file else ""
    body = "## Purpose\n\n" + normalize_body(purpose) if purpose.strip() else ""
    from scripts.force_app_knowledge import file_digest

    fragment_path = ROOT / component["path"]
    fragments = [{"path": component["path"], "sourceDigest": f"sha256:{file_digest(fragment_path)}"}]
    coverage = {"typeFacts": "full"}
    if intentional:
        coverage["intentionalErrors"] = "full"
        assurance = {**assurance, "intentionalErrors": "source-exact"}
    frontmatter: dict[str, Any] = {
        "schemaVersion": 1,
        "subject": {"metadataType": metadata_type, "fullName": args.full_name, "namespace": args.namespace},
        "profile": {
            "id": profile["id"],
            "version": profile["version"],
            "digest": canonical_digest(load_schema(profile["schema"])),
        },
        "scope": {
            "sourceApiVersion": args.source_api_version,
            "sourceTreeDigest": canonical_digest(sorted((f["path"], f["sourceDigest"]) for f in fragments)),
            "packageVersionId": None,
        },
        "source": {"fragments": fragments},
        "lifecycle": {"state": "draft", "contentDigest": "sha256:" + "0" * 64},
        "typeFacts": type_facts,
        "extractionCoverage": coverage,
        "assurance": assurance,
        "limitations": [],
        "keywords": [],
        "candidateKeywords": list(args.candidate_keyword or [])[:5],
        "sensitivity": "internal-sanitized",
        "approval": {"reviewedContentDigest": None, "reviewedBy": None, "reviewedAt": None, "mechanism": None},
    }
    if intentional:
        frontmatter["intentionalErrors"] = intentional
    frontmatter["lifecycle"]["contentDigest"] = reviewed_content_digest(frontmatter, body)
    problems = validate_entry(frontmatter, body)
    if problems:
        raise StoreError("draft validation failed: " + "; ".join(problems))
    path = entry_path(metadata_type, args.namespace, args.full_name)
    assert_no_casefold_collision(path)
    atomic_write(path, render_entry(frontmatter, body))
    return {
        "outcome": "DRAFTED",
        "identity": identity_of(metadata_type, args.namespace, args.full_name),
        "path": str(path.relative_to(ROOT)),
        "reviewedContentDigest": frontmatter["lifecycle"]["contentDigest"],
    }


def parse_pins(pins: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pin in pins:
        identity, _, digest = pin.rpartition(":sha256:")
        if not identity or not digest:
            raise StoreError(f"--entry must be <identity>:sha256:<digest>, got {pin!r}")
        parsed[identity] = f"sha256:{digest}"
    return parsed


def reviewer_identity() -> str:
    if not LOCAL_CONFIG.exists():
        raise StoreError("config/harness.local.json with knowledge.chatReviewer is required for approval")
    reviewer = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8")).get("knowledge", {}).get("chatReviewer")
    if not reviewer or reviewer.startswith("<"):
        raise StoreError("knowledge.chatReviewer is not configured")
    return reviewer


def command_entry_approve(args: argparse.Namespace) -> dict[str, Any]:
    assert_no_reparse_points()
    pins = parse_pins(args.entry or [])
    if not pins:
        raise StoreError("at least one --entry <identity>:sha256:<digest> pin is required (contract §6.2)")
    records = read_ledger()
    latest = ledger_latest(records)
    prose_count = 0
    resolved: list[tuple[Path, dict[str, Any], str, str]] = []
    for identity, pinned_digest in pins.items():
        metadata_type, namespace_segment, full_name = identity.split(":", 2)
        namespace = None if namespace_segment == "c" else namespace_segment
        path = entry_path(metadata_type, namespace, full_name)
        if not path.exists():
            raise StoreError(f"{identity}: entry file missing at {path.relative_to(ROOT)}")
        frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
        problems = validate_entry(frontmatter, body)
        if problems:
            raise StoreError(f"{identity}: validation failed: " + "; ".join(problems))
        if "## Purpose" not in body:
            raise StoreError(f"{identity}: approval requires a '## Purpose' section (contract §2.2)")
        recomputed = reviewed_content_digest(frontmatter, body)
        if recomputed != pinned_digest:
            raise StoreError(
                f"{identity}: digest pin mismatch (pinned {pinned_digest[:20]}…, recomputed {recomputed[:20]}…) — chunk rejected (contract §6.2)"
            )
        previous = latest.get(identity)
        if previous is None or previous.get("semanticsDigest") != semantics_digest(body):
            prose_count += 1
        resolved.append((path, frontmatter, body, recomputed))
    if prose_count and len(pins) > PROSE_CHUNK_LIMIT:
        raise StoreError(f"chunks containing prose changes are capped at {PROSE_CHUNK_LIMIT} entries (contract §6.4.4)")
    if len(pins) > MANIFEST_CHUNK_LIMIT:
        raise StoreError(f"chunks are capped at {MANIFEST_CHUNK_LIMIT} entries (contract §6.4.4)")
    reviewer = reviewer_identity()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chunk_id = canonical_digest(sorted(pins.items()))[7:19]
    REVIEW_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    artifact_lines = [f"# Knowledge approval chunk {chunk_id}", ""]
    ledger_entries = []
    for path, frontmatter, body, digest in resolved:
        subject = frontmatter["subject"]
        identity = identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"])
        artifact_lines += [f"## {identity}", "", f"- digest: `{digest}`", "", "### Full body", "", body or "(empty)", ""]
        frontmatter["lifecycle"]["state"] = "approved"
        frontmatter["approval"] = {
            "reviewedContentDigest": digest,
            "reviewedBy": reviewer,
            "reviewedAt": now,
            "mechanism": "copilot-chat-entry-confirmation",
        }
        atomic_write(path, render_entry(frontmatter, body))
        ledger_entries.append(
            {
                "action": "approve",
                "identity": identity,
                "reviewedContentDigest": digest,
                "semanticsDigest": semantics_digest(body),
                "reviewedBy": reviewer,
                "reviewedAt": now,
                "mechanism": "copilot-chat-entry-confirmation",
                "chunkId": chunk_id,
            }
        )
        append_ledger([ledger_entries[-1]])  # per-file journaled stamping (contract §6.4.5)
    with (REVIEW_ARTIFACT_ROOT / f"{chunk_id}.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(artifact_lines))
    return {"outcome": "APPROVED", "chunkId": chunk_id, "entries": len(resolved)}


def command_entry_revoke(args: argparse.Namespace) -> dict[str, Any]:
    latest = ledger_latest(read_ledger())
    record = latest.get(args.identity)
    if record is None or record["action"] == "revoke":
        raise StoreError(f"{args.identity}: nothing to revoke")
    reviewer = reviewer_identity()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_ledger(
        [
            {
                "action": "revoke",
                "identity": args.identity,
                "reviewedContentDigest": record["reviewedContentDigest"],
                "reviewedBy": reviewer,
                "reviewedAt": now,
                "mechanism": "copilot-chat-entry-confirmation",
                "chunkId": None,
                "rationale": args.rationale,
            }
        ]
    )
    return {"outcome": "REVOKED", "identity": args.identity}


def command_entry_status(args: argparse.Namespace) -> dict[str, Any]:
    latest = ledger_latest(read_ledger())
    lanes = [compute_lane(path, latest) for path in all_entry_paths()]
    if args.identity:
        lanes = [lane for lane in lanes if lane["identity"] == args.identity]
    return {"outcome": "STATUS", "entries": lanes}


def command_entry_check(_args: argparse.Namespace) -> dict[str, Any]:
    assert_no_reparse_points()
    latest = ledger_latest(read_ledger())
    problems: list[str] = []
    seen_identities: dict[str, str] = {}
    seen_casefold: dict[str, str] = {}
    for path in all_entry_paths():
        lane = compute_lane(path, latest)
        problems.extend(f"{lane['path']}: {problem}" for problem in lane["problems"])
        identity = lane["identity"]
        if identity in seen_identities:
            problems.append(f"identity {identity} resolves to two files: {seen_identities[identity]} and {lane['path']}")
        seen_identities[identity] = lane["path"]
        folded = lane["path"].casefold()
        if folded in seen_casefold and seen_casefold[folded] != lane["path"]:
            problems.append(f"case-fold collision: {seen_casefold[folded]} vs {lane['path']}")
        seen_casefold[folded] = lane["path"]
    if problems:
        raise StoreError("entry-check failed:\n- " + "\n- ".join(problems))
    return {"outcome": "PASS", "entries": len(seen_identities), "ledgerRecords": len(read_ledger())}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge_store", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("entry-draft", help="derive and write a draft entry from source")
    draft.add_argument("--metadata-type", required=True)
    draft.add_argument("--full-name", required=True)
    draft.add_argument("--namespace", default=None)
    draft.add_argument("--purpose-file", default=None)
    draft.add_argument("--source-api-version", default="64.0")
    draft.add_argument("--candidate-keyword", action="append", default=None)
    draft.set_defaults(func=command_entry_draft)

    approve = commands.add_parser("entry-approve", help="digest-pinned chat-approved promotion")
    approve.add_argument("--entry", action="append", default=None, help="<identity>:sha256:<digest>")
    approve.set_defaults(func=command_entry_approve)

    revoke = commands.add_parser("entry-revoke", help="append a revocation for an identity")
    revoke.add_argument("--identity", required=True)
    revoke.add_argument("--rationale", required=True)
    revoke.set_defaults(func=command_entry_revoke)

    status = commands.add_parser("entry-status", help="computed lanes for entries")
    status.add_argument("--identity", default=None)
    status.set_defaults(func=command_entry_status)

    check = commands.add_parser("entry-check", help="CI validation of all entries and the ledger")
    check.set_defaults(func=command_entry_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except StoreError as error:
        print(json.dumps({"outcome": "ERROR", "reason": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
