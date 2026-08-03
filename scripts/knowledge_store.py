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
    from scripts.relation_kinds import edge_assurance
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_store.py`
    from knowledge_registry import canonical_digest  # type: ignore
    from relation_kinds import edge_assurance  # type: ignore

ARTIFACTS_ROOT = ROOT / ".ai/knowledge/artifacts"
LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-ledger.jsonl"
# Features live OUTSIDE ARTIFACTS_ROOT so all_entry_paths(), corpus_fingerprint() and the
# artifact index never see them — a Feature is not a Salesforce artifact and must never be
# citable as an entryRef. Their ledger is separate for the same reason it is separate in the
# contract: the artifact ledger's stamp is folded into every projection's reuse key, so sharing
# one file would discard the entire artifact index on every feature approval.
FEATURES_ROOT = ROOT / ".ai/knowledge/features"
FEATURE_LEDGER_PATH = ROOT / ".ai/knowledge/features-ledger.jsonl"
REVIEW_ARTIFACT_ROOT = ROOT / "output/knowledge-approvals"
SCHEMA_DIR = ROOT / "schemas"
LOCAL_CONFIG = ROOT / "config/harness.local.json"
TAXONOMY_PATH = ROOT / ".ai/knowledge/keyword-taxonomy.md"
# Org-usage layer (contract v1.2 §6.6): a SEPARATE append-only ledger — the approval ledger is
# never written by attach/detach, which is half of the approval-preservation argument.
ORG_LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-org-ledger.jsonl"
ORG_USAGE_CACHE = ROOT / ".cache/org-usage"
KNOWLEDGE_POLICY_PATH = ROOT / "config/knowledge-policy.json"

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
    "ApexClass": {"id": "salesforce.apex", "version": "1.0.0", "schema": "knowledge-profile-apex.schema.json"},
    "ApexTrigger": {"id": "salesforce.apex", "version": "1.0.0", "schema": "knowledge-profile-apex.schema.json"},
    "ValidationRule": {
        "id": "salesforce.validation-rule",
        "version": "1.0.0",
        "schema": "knowledge-profile-validationrule.schema.json",
    },
    "PermissionSet": {
        "id": "salesforce.permission-set",
        "version": "1.0.0",
        "schema": "knowledge-profile-permissionset.schema.json",
    },
    "CustomObject": {
        "id": "salesforce.custom-object",
        "version": "1.0.0",
        "schema": "knowledge-profile-customobject.schema.json",
    },
    "RecordType": {
        "id": "salesforce.record-type",
        "version": "1.0.0",
        "schema": "knowledge-profile-recordtype.schema.json",
    },
    "CustomMetadata": {
        "id": "salesforce.custom-metadata",
        "version": "1.0.0",
        "schema": "knowledge-profile-custommetadata.schema.json",
    },
    "LightningComponentBundle": {
        "id": "salesforce.lightning-component",
        "version": "1.0.0",
        "schema": "knowledge-profile-lwc.schema.json",
    },
}


class StoreError(RuntimeError):
    """Fail-closed executor error; message is the actionable reason."""


import contextlib


@contextlib.contextmanager
def rooted(root: Path):
    """Bind module paths to a different repo root (work_record gates, unit tests)."""
    global ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH
    global FEATURES_ROOT, FEATURE_LEDGER_PATH, ORG_LEDGER_PATH, ORG_USAGE_CACHE, KNOWLEDGE_POLICY_PATH
    saved = (ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH,
             FEATURES_ROOT, FEATURE_LEDGER_PATH, ORG_LEDGER_PATH, ORG_USAGE_CACHE, KNOWLEDGE_POLICY_PATH)
    ROOT = Path(root).resolve()
    ARTIFACTS_ROOT = ROOT / ".ai/knowledge/artifacts"
    LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-ledger.jsonl"
    FEATURES_ROOT = ROOT / ".ai/knowledge/features"
    FEATURE_LEDGER_PATH = ROOT / ".ai/knowledge/features-ledger.jsonl"
    REVIEW_ARTIFACT_ROOT = ROOT / "output/knowledge-approvals"
    LOCAL_CONFIG = ROOT / "config/harness.local.json"
    TAXONOMY_PATH = ROOT / ".ai/knowledge/keyword-taxonomy.md"
    ORG_LEDGER_PATH = ROOT / ".ai/knowledge/artifacts-org-ledger.jsonl"
    ORG_USAGE_CACHE = ROOT / ".cache/org-usage"
    KNOWLEDGE_POLICY_PATH = ROOT / "config/knowledge-policy.json"
    try:
        yield
    finally:
        (ROOT, ARTIFACTS_ROOT, LEDGER_PATH, REVIEW_ARTIFACT_ROOT, LOCAL_CONFIG, TAXONOMY_PATH,
         FEATURES_ROOT, FEATURE_LEDGER_PATH, ORG_LEDGER_PATH, ORG_USAGE_CACHE, KNOWLEDGE_POLICY_PATH) = saved


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


def relative_path(path: Path) -> str:
    """Repo-relative path as DATA: always forward slashes, on every platform.

    `relative_path(path)` renders backslashes on Windows, which is the team's only
    platform. Every path this executor emits is compared against, or pasted next to, a path
    built elsewhere with `as_posix()` — `work_record.entry_relative_path` is one — so the two
    forms silently stop matching there and nowhere else. Path separators are a rendering
    detail of the local filesystem; a citation is a record, and its form must not depend on
    which machine wrote it.
    """
    return path.relative_to(ROOT).as_posix()


def entry_path(metadata_type: str, namespace: str | None, full_name: str) -> Path:
    identity = identity_of(metadata_type, namespace, full_name)
    path = ARTIFACTS_ROOT / metadata_type / (namespace or "c") / f"{safe_name(full_name, identity)}.md"
    if len(relative_path(path)) > PATH_BUDGET:
        raise StoreError(f"derived path exceeds {PATH_BUDGET}-char budget for {identity}")
    return path


def assert_no_reparse_points(root: Path | None = None) -> None:
    """Refuse a symlink/junction anywhere under the tree a command is about to write.

    Scoped, because the walk is the command's own cost: a single-file feature-status or
    feature-propose paying an rglob over a 15 k-entry artifact corpus is a scale defect, and the
    artifact corpus is not what those commands write anyway. Each caller passes the root it
    governs, so the check still covers every path it can create (§6, R4)."""

    base = root if root is not None else ROOT / ".ai/knowledge"
    if not base.exists():
        return
    scope = base.relative_to(ROOT).as_posix() if base.is_relative_to(ROOT) else str(base)
    for path in base.rglob("*"):
        if path.is_symlink():
            raise StoreError(f"reparse point/symlink under {scope}: {path} (contract §3)")


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


def read_ledger(path: Path | None = None) -> list[dict[str, Any]]:
    ledger = path or LEDGER_PATH
    if not ledger.exists():
        return []
    records = []
    for index, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
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


def append_ledger(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    ledger = path or LEDGER_PATH
    records = read_ledger(ledger)
    sequence = len(records)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
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
    """Effectiveness lane for one entry — always the full check.

    There is deliberately no partial mode. One existed, skipping the source-fragment re-digest
    on the theory that it was the expensive part; profiling at 9 000 entries put the cost in
    YAML parsing and jsonschema validation instead and left the re-digest out of the top frames
    entirely, so the partial mode bought ~2 % while returning a lane that was asserted rather
    than proven. `entry-check --changed-since` now skips whole entries instead."""

    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_entry(text)
    subject = frontmatter["subject"]
    identity = identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"])
    expected = entry_path(subject["metadataType"], subject.get("namespace"), subject["fullName"])
    result = {"identity": identity, "path": relative_path(path), "problems": validate_entry(frontmatter, body)}
    if path.resolve() != expected.resolve():
        result["lane"] = "not-effective"
        result["problems"].append(f"path/identity round-trip failed (expected {expected.relative_to(ROOT)})")
        return result
    if frontmatter["lifecycle"]["state"] == "draft":
        # A draft is never served, so its outstanding work is not an integrity failure. An
        # entry still awaiting its description belongs in `draft` with the reason attached —
        # reporting it as `not-effective` made ordinary unfinished work look like corruption.
        result["lane"] = "draft"
        # The digest is a pure function of content, so it exists even while the entry is
        # unfinished. Withholding it made draft-lane search hits fail hydration and vanish.
        result["reviewedContentDigest"] = reviewed_content_digest(frontmatter, body)
        result["sourceTreeDigest"] = frontmatter["scope"]["sourceTreeDigest"]
        result["profile"] = (
            f"{frontmatter['profile']['id']}@{frontmatter['profile']['version'].split('.', 1)[0]}"
        )
        return result
    if result["problems"]:
        result["lane"] = "not-effective"
        return result
    recomputed = reviewed_content_digest(frontmatter, body)
    result["reviewedContentDigest"] = recomputed
    ledger_record = latest.get(identity)
    if ledger_record is None:
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
    elif any(
        frontmatter["approval"].get(field) != ledger_record.get(field)
        for field in ("reviewedBy", "reviewedAt", "mechanism")
    ):
        # The ledger is authoritative for who approved, when, and by which mechanism
        # (contract §5.3). Content tampering is caught by the digest; provenance tampering
        # would otherwise be invisible, so the mirror is compared field by field.
        result["lane"] = "not-effective"
        result["problems"].append("in-file approval provenance mismatches the ledger record")
    else:
        regenerated = regenerate_fragment_digest(frontmatter)
        result["lane"] = "approved-current" if regenerated else "approved-drifted"
        result["factsDigest"] = facts_digest(frontmatter)
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


def all_entry_paths(include_case_twins: bool = False) -> list[Path]:
    if not ARTIFACTS_ROOT.exists():
        return []
    if include_case_twins:
        # `rglob("*.md")` is case-sensitive on Linux, so `NAME.MD` — exactly the kind of file
        # the case-fold gate exists to refuse — was invisible to the one check meant to see it,
        # and `entry-check` passed over a collision that breaks every Windows/macOS checkout.
        return sorted(
            path for path in ARTIFACTS_ROOT.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".md"
        )
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


def render_decision_path(path: Any) -> str:
    """One reachability path, rendered for the profile's `decisionGuards: [string]`.

    The collector emits `paths` as a list of PATHS, each a list of hop OBJECTS
    (`{decision, outcome?, outcomeLabel?, conditions?, default?}`, force_app_knowledge.py:960-966).
    Joining those with `" -> ".join(...)` raised `TypeError: sequence item 0: expected str
    instance, dict found` on the first real Flow that declared a custom error behind a decision —
    an unhandled crash, not a degraded fact, so the whole entry could not be drafted. The pilot
    never hit it because its fixture errors sit on the trigger path with no decision above them.

    A hop renders as the decision name, qualified by the branch that reaches it: the outcome label
    when there is one, the API outcome name otherwise, and `default` for the else-branch. An
    unrecognised hop degrades to its decision name rather than raising — a guard string is
    disclosure, and losing the whole entry to gain a punctuation mark is the wrong trade.
    """

    if not isinstance(path, list):
        return str(path)
    steps: list[str] = []
    for hop in path:
        if not isinstance(hop, dict):
            steps.append(str(hop))
            continue
        decision = str(hop.get("decision") or "").strip()
        if not decision:
            continue
        branch = hop.get("outcomeLabel") or hop.get("outcome")
        if branch:
            steps.append(f"{decision} [{branch}]")
        elif hop.get("default"):
            steps.append(f"{decision} [default]")
        else:
            steps.append(decision)
    return " -> ".join(steps)


def flow_type_facts(component: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    facts = component.get("facts", {})
    references = [
        {
            "kind": ref["kind"],
            "target": ref["target"],
            "assurance": edge_assurance(ref["kind"], bool(ref.get("heuristic"))),
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
                "decisionGuards": [render_decision_path(p) for p in item.get("paths", [])],
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


def _edges(component: dict[str, Any]) -> list[dict[str, Any]]:
    """Collector references as profile edges, with assurance derived from the kind vocabulary.

    Reading only the collector's per-edge `heuristic` flag was a laundering bug: the flag is set
    for kinds that are heuristic only *sometimes* (`queries-object` is structural from Flow XML
    and regex-derived from Apex), never for kinds that are heuristic *always* (`object-token`,
    `invokes-class`, `var-field-ref`, `soql-field`). Measured on a 189-component probe corpus,
    414 of 595 edges therefore claimed `source-exact` for a regex match — inside factsDigest,
    so a human approved the claim, and SAFE-CLAIM-001 v2 would ground a work record on it."""

    return [
        {
            "kind": reference["kind"],
            "target": reference["target"],
            "assurance": edge_assurance(reference["kind"], bool(reference.get("heuristic"))),
        }
        for reference in component.get("references", [])
    ]


def _assurance_for(edges: list[dict[str, Any]]) -> dict[str, str]:
    """Section marker is the weakest member (contract §2.1)."""
    heuristic = any(edge["assurance"] == "source-derived-heuristic" for edge in edges)
    return {"typeFacts": "source-derived-heuristic" if heuristic else "source-exact"}


# Collector facts deliberately not carried into an entry, with the reason. Everything else is
# passed through: hand-listing what to KEEP silently lost real content — validation rules
# arrived as `conditionPresent: true` without the formula, fields lost their picklist values
# and rollup definitions, Apex lost its sharing model and SOQL/DML targets. Anything the
# collector emits that a profile does not declare now fails draft validation loudly instead
# of disappearing from the entry.
FACT_EXCLUSIONS: dict[str, dict[str, str]] = {
    "Flow": {
        "errorCatalog": "screen-validation and fault-path entries must never reach an entry; "
        "author-declared Custom Errors are carried in intentionalErrors instead (contract §7)",
        "elementCounts": "shape statistics, not an assertion about the artifact",
        "start": "already represented by trigger/*",
        "referencedObjects": "already represented as typed reference edges",
        "dataOperations": "already represented by operations[]",
        "variables": "carried by the Flow profile mapping",
        "formulas": "expression bodies belong to the source, not the entry",
        "label": "not a behavioural fact for Flow entries",
        "object": "already represented by trigger.object",
        "triggerType": "already represented by trigger.type",
        "recordTriggerType": "already represented by trigger.recordTriggerType",
        "processType": "carried by the Flow profile mapping",
        "status": "carried by the Flow profile mapping",
    },
}


def _normalize_fact(value: Any) -> Any:
    """Digit-only XML text becomes an integer; everything else is carried verbatim.

    Salesforce emits numeric attributes (field length, precision, scale) as text. Normalizing
    them keeps numeric facets comparable without inventing or losing information."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _passthrough_adapter(metadata_type: str):
    """Carry the collector's facts faithfully; exclusions must be declared and justified."""

    excluded = set(FACT_EXCLUSIONS.get(metadata_type, {}))

    def adapter(component: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
        facts = component.get("facts", {})
        edges = _edges(component)
        type_facts = {
            key: _normalize_fact(value)
            for key, value in facts.items()
            if key not in excluded and value is not None
        }
        if metadata_type in {"ApexClass", "ApexTrigger"}:
            type_facts["kind"] = metadata_type
        if edges:
            type_facts["references"] = edges
        return type_facts, [], _assurance_for(edges)

    return adapter


ADAPTERS = {
    # Flow keeps a bespoke adapter: it is the only type with intentionalErrors, which must be
    # derived from the customErrors element class rather than passed through.
    "Flow": flow_type_facts,
    **{
        metadata_type: _passthrough_adapter(metadata_type)
        for metadata_type in (
            "CustomField",
            "ApexClass",
            "ApexTrigger",
            "ValidationRule",
            "PermissionSet",
            "CustomObject",
            "RecordType",
            "CustomMetadata",
            "LightningComponentBundle",
        )
    },
}


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
        raise StoreError(
            f"unsupported metadata type {metadata_type!r}; profiled types: "
            + ", ".join(sorted(PROFILES))
        )
    component = collector_component(metadata_type, args.full_name)
    type_facts, intentional, assurance = adapter(component)
    # Without an authored description the entry carries a sentinel: the facts are extracted,
    # but the artifact cannot be approved until an agent has read the source and written what
    # the component does. An empty body would look finished; a sentinel cannot be approved.
    purpose = Path(args.purpose_file).read_text(encoding="utf-8") if args.purpose_file else ""
    body = (
        "## Purpose\n\n" + normalize_body(purpose)
        if purpose.strip()
        else "## Purpose\n\n<AGENT_DESCRIPTION>\n"
    )
    from scripts.force_app_knowledge import COLLECTOR_VERSION, file_digest

    fragment_path = ROOT / component["path"]
    fragments = [{"path": component["path"], "sourceDigest": f"sha256:{file_digest(fragment_path)}"}]
    coverage = {
        "typeFacts": "partial" if type_facts.get("referencesTruncated") else "full"
    }
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
            # Dates a factsDigest move for a future auditor; lives in scope so a collector
            # release alone never moves factsDigest or the reviewed digest.
            "collectorVersion": COLLECTOR_VERSION,
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
    # M-R4 carry-forward (contract §2.3): a redraft rebuilds this frontmatter wholesale and must
    # not silently drop the digest-excluded org observation an earlier attach persisted.
    carry_forward_org_usage(frontmatter, entry_path(metadata_type, args.namespace, args.full_name))
    frontmatter["lifecycle"]["contentDigest"] = reviewed_content_digest(frontmatter, body)
    problems = [
        problem
        for problem in validate_entry(frontmatter, body)
        if "sentinel" not in problem or purpose.strip()
    ]
    if problems:
        raise StoreError("draft validation failed: " + "; ".join(problems))
    path = entry_path(metadata_type, args.namespace, args.full_name)
    assert_no_casefold_collision(path)
    atomic_write(path, render_entry(frontmatter, body))
    return {
        "outcome": "DRAFTED",
        "identity": identity_of(metadata_type, args.namespace, args.full_name),
        "path": relative_path(path),
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


def classify_chunk(resolved: list[tuple[str, dict[str, Any], str, str]], latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Split a chunk into prose-bearing and facts-only re-approvals (contract §6.4.4)."""
    prose, facts_only = [], []
    for identity, _front, body, _digest in resolved:
        previous = latest.get(identity)
        if previous is None or previous.get("semanticsDigest") != semantics_digest(body):
            prose.append(identity)
        else:
            facts_only.append(identity)
    return {"proseChanges": sorted(prose), "factsOnly": sorted(facts_only)}


def command_entry_context(args: argparse.Namespace) -> dict[str, Any]:
    """Everything needed to WRITE a description, in one read-only call.

    A description is an analysis of the artifact, not a copy of its `description` element —
    most real components have none. So this returns the artifact's own source, its extracted
    facts, and how the rest of the package uses it, because "what this component does" is
    usually only answerable from the definition plus its callers."""

    assert_no_reparse_points()
    metadata_type, namespace_segment, full_name = args.identity.split(":", 2)
    namespace = None if namespace_segment == "c" else namespace_segment
    path = entry_path(metadata_type, namespace, full_name)
    if not path.is_file():
        raise StoreError(f"no entry for {args.identity}; draft it first")
    frontmatter, body = split_entry(path.read_text(encoding="utf-8"))

    sources = []
    for fragment in frontmatter["source"]["fragments"]:
        source_path = ROOT / fragment["path"]
        text = source_path.read_text(encoding="utf-8", errors="replace") if source_path.is_file() else ""
        truncated = len(text) > args.max_source_chars
        sources.append(
            {
                "path": fragment["path"],
                "truncated": truncated,
                "text": text[: args.max_source_chars],
            }
        )

    # Reverse usage: who points at this artifact. An entry that only describes itself misses
    # the half of "what it does" that lives in its callers.
    identity = identity_of(metadata_type, namespace, full_name)
    targets = {identity, full_name}
    if "." in full_name:
        targets.add(full_name.split(".", 1)[1])
    latest = ledger_latest(read_ledger())
    used_by: list[dict[str, Any]] = []
    for other in all_entry_paths():
        if other == path:
            continue
        try:
            other_front, _ = split_entry(other.read_text(encoding="utf-8"))
        except StoreError:
            continue
        other_subject = other_front["subject"]
        other_identity = identity_of(
            other_subject["metadataType"], other_subject.get("namespace"), other_subject["fullName"]
        )
        for edge in (other_front.get("typeFacts", {}).get("references") or []):
            if edge.get("target") in targets:
                used_by.append(
                    {"source": other_identity, "kind": edge["kind"], "assurance": edge.get("assurance")}
                )
    return {
        "outcome": "CONTEXT",
        "identity": identity,
        "describedYet": "<AGENT_" not in body,
        "currentBody": body,
        "typeFacts": frontmatter.get("typeFacts", {}),
        "intentionalErrors": frontmatter.get("intentionalErrors", []),
        "uses": frontmatter.get("typeFacts", {}).get("references", []),
        "usedBy": sorted(used_by, key=lambda item: (item["source"], item["kind"])),
        "source": sources,
        "guidance": (
            "Write 1-8 sentences stating what this component does, from the source above and "
            "how it is used. Do not restate the facts, do not infer intent the source does not "
            "support, and leave the gap visible if the source does not say why it exists."
        ),
    }


def command_entry_describe(args: argparse.Namespace) -> dict[str, Any]:
    """Write the agent-authored description into an existing entry.

    The description is the one part of an entry a model produces rather than extracts, so it
    is the one part a human must actually read. Structured facts are never touched here: this
    command replaces only the attested body, recomputes the digests, and returns the entry to
    `draft` — an approval bound to the previous text cannot survive new text (contract §5.5).

    `--limitation` writes the one required, digest-bound field that had no write path at all.
    `limitations` is inside `factsDigest`, printed to the approver, and read by six projection
    sites — and it was `[]` on every entry of the first real store, because `entry-draft`
    hardcodes it and no subcommand could set it. The caveats existed; they were stranded in
    prose, where no consumer reads them. It rides this command because the invalidation
    semantics a limitation needs are exactly the ones a new description already has.
    """

    assert_no_reparse_points()
    metadata_type, namespace_segment, full_name = args.identity.split(":", 2)
    namespace = None if namespace_segment == "c" else namespace_segment
    path = entry_path(metadata_type, namespace, full_name)
    if not path.is_file():
        raise StoreError(f"no entry to describe: {args.identity}")
    frontmatter, previous_body = split_entry(path.read_text(encoding="utf-8"))
    description = normalize_body(Path(args.purpose_file).read_text(encoding="utf-8"))
    if not description.strip():
        raise StoreError("the description file is empty")
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", description.strip()) if part.strip()]
    if not 1 <= len(sentences) <= 8:
        raise StoreError(
            f"a description must be 1-8 sentences, got {len(sentences)} — it states what the "
            "component does, it is not a transcript of its source"
        )
    body = "## Purpose\n\n" + description
    limitations = [str(item).strip() for item in (getattr(args, "limitation", None) or []) if str(item).strip()]
    if limitations and getattr(args, "clear_limitations", False):
        raise StoreError("--clear-limitations cannot be combined with --limitation")
    if limitations:
        # Replace rather than append: a limitation set is a statement about THIS text, and an
        # append-only field would silently carry a caveat that the new description answered.
        frontmatter["limitations"] = sorted(dict.fromkeys(limitations))
    elif getattr(args, "clear_limitations", False):
        frontmatter["limitations"] = []
    problems = validate_entry(frontmatter, body)
    if problems:
        raise StoreError("description rejected: " + "; ".join(problems))
    was_approved = frontmatter["lifecycle"]["state"] == "approved"
    frontmatter["lifecycle"]["state"] = "draft"
    frontmatter["approval"] = {
        "reviewedContentDigest": None,
        "reviewedBy": None,
        "reviewedAt": None,
        "mechanism": None,
    }
    frontmatter["lifecycle"]["contentDigest"] = reviewed_content_digest(frontmatter, body)
    atomic_write(path, render_entry(frontmatter, body))
    return {
        "outcome": "DESCRIBED",
        "identity": args.identity,
        "limitations": frontmatter.get("limitations", []),
        "path": relative_path(path),
        "reviewedContentDigest": frontmatter["lifecycle"]["contentDigest"],
        "previousApprovalInvalidated": was_approved,
        "sentences": len(sentences),
        "replacedSentinel": "<AGENT_" in previous_body,
    }


def command_entry_review(args: argparse.Namespace) -> dict[str, Any]:
    """Render the executor-authored review surface a human approves against.

    Contract §6.3: the diff a reviewer reads is produced here, never by the agent, and it
    exists BEFORE the approval click. The printed command carries the exact digest set, so
    any edit between review and approval fails the pin in entry-approve (§6.2).
    """
    assert_no_reparse_points()
    latest = ledger_latest(read_ledger())
    wanted = set(args.identity or [])
    resolved: list[tuple[str, dict[str, Any], str, str]] = []
    problems: list[str] = []
    for path in all_entry_paths():
        frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
        subject = frontmatter["subject"]
        identity = identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"])
        if wanted and identity not in wanted:
            continue
        if not wanted and frontmatter["lifecycle"]["state"] != "draft":
            continue
        entry_problems = validate_entry(frontmatter, body)
        if "## Purpose" not in body:
            entry_problems.append("approval requires a '## Purpose' section (contract §2.2)")
        if entry_problems:
            problems.extend(f"{identity}: {problem}" for problem in entry_problems)
            continue
        resolved.append((identity, frontmatter, body, reviewed_content_digest(frontmatter, body)))
    if not resolved:
        return {"outcome": "NOTHING_TO_REVIEW", "problems": problems}

    classification = classify_chunk(resolved, latest)
    chunk_id = canonical_digest(sorted((identity, digest) for identity, _f, _b, digest in resolved))[7:19]
    lines = [
        f"# Knowledge approval review — chunk {chunk_id}",
        "",
        f"Entries: {len(resolved)} (prose changes: {len(classification['proseChanges'])}, "
        f"facts-only: {len(classification['factsOnly'])})",
        "",
        "Read every Purpose section below. Approving binds these exact digests; any edit "
        "afterwards invalidates the pin and the chunk is rejected.",
        "",
    ]
    for identity, frontmatter, body, digest in resolved:
        previous = latest.get(identity)
        change = "new approval" if previous is None else (
            "prose changed" if previous.get("semanticsDigest") != semantics_digest(body) else "facts-only re-approval"
        )
        lines += [
            f"## {identity}",
            "",
            f"- change: {change}",
            f"- digest: `{digest}`",
            f"- source: `{frontmatter['source']['fragments'][0]['path']}`",
            f"- coverage: {json.dumps(frontmatter.get('extractionCoverage', {}), sort_keys=True)}",
            f"- assurance: {json.dumps(frontmatter.get('assurance', {}), sort_keys=True)}",
            f"- limitations: {json.dumps(frontmatter.get('limitations', []), sort_keys=True)}",
            "",
            "### Attested body (exactly what approval covers)",
            "",
            body.strip() or "(empty — cannot be approved)",
            "",
        ]
        if frontmatter.get("intentionalErrors"):
            lines += ["### Source-declared intentional errors", ""]
            for error in frontmatter["intentionalErrors"]:
                lines.append(
                    f"- `{error['elementApiName']}` → {json.dumps(error.get('messageTemplate'))} "
                    f"({error.get('presentation', {}).get('mode')})"
                )
            lines.append("")
        if frontmatter.get("orgUsage"):
            # Contract §14.3 / §5.7: org data is disclosed beside — never inside — what the
            # click approves; expired/superseded values are withheld (expired means absent).
            org = compute_org_lane(frontmatter, identity, org_ledger_latest())
            lines += [
                "### Observed org data — machine-attested, expiring, NOT covered by this approval",
                "",
            ]
            for key, value in sorted(org["orgs"].items()):
                if value.get("status") == "org-fresh":
                    block = (frontmatter["orgUsage"].get("orgs") or {}).get(key, {})
                    probe_labels = ", ".join(sorted(block.get("probes") or {}))
                    record_count = None
                    for probe in (block.get("probes") or {}).values():
                        if probe.get("kind") == "object-shape":
                            record_count = (probe.get("results") or {}).get("recordCount")
                    summary = f"org-fresh; probes: {probe_labels or '(none)'}"
                    if record_count is not None:
                        summary += f"; recordCount {record_count}"
                    lines.append(
                        f"- `{key}` ({value.get('environment')}): {summary}; "
                        f"observed {value['observedAt']}, expires {value['expiresAt']}"
                    )
                else:
                    lines.append(
                        f"- `{key}`: {value.get('status')} — values withheld "
                        f"(observed {value.get('observedAt', 'unknown')})"
                    )
            lines.append("")
    REVIEW_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    artifact = REVIEW_ARTIFACT_ROOT / f"{chunk_id}-review.md"
    with artifact.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))

    pins = " ".join(f"--entry {identity}:{digest}" for identity, _f, _b, digest in resolved)
    caps: list[str] = []
    if classification["proseChanges"] and len(resolved) > PROSE_CHUNK_LIMIT:
        caps.append(
            f"chunk carries prose changes and exceeds the {PROSE_CHUNK_LIMIT}-entry cap — split it"
        )
    if len(resolved) > MANIFEST_CHUNK_LIMIT:
        caps.append(f"chunk exceeds the {MANIFEST_CHUNK_LIMIT}-entry hard cap — split it")
    return {
        "outcome": "REVIEW_READY" if not caps else "CHUNK_TOO_LARGE",
        "chunkId": chunk_id,
        "reviewArtifact": relative_path(artifact),
        "entries": len(resolved),
        "classification": classification,
        "capViolations": caps,
        "problems": problems,
        "approveCommand": f"python scripts/knowledge_store.py entry-approve {pins}",
    }


def command_entry_coverage(args: argparse.Namespace) -> dict[str, Any]:
    """Per-metadata-type coverage of the entry store against force-app source.

    This is the entry-layer answer to the collector's `coverage` report: which profiled
    artifacts have an entry, which lane those entries are in, and which source components
    still have none. Types without a profile are reported separately so their absence reads
    as "no entry home yet", never as a coverage gap."""

    from scripts.force_app_knowledge import ForceAppKnowledge

    latest = ledger_latest(read_ledger())
    lanes: dict[str, dict[str, int]] = {}
    entry_names: dict[str, set[str]] = {}
    for path in all_entry_paths():
        lane = compute_lane(path, latest)
        metadata_type, _namespace, full_name = lane["identity"].split(":", 2)
        lanes.setdefault(metadata_type, {})
        lanes[metadata_type][lane["lane"]] = lanes[metadata_type].get(lane["lane"], 0) + 1
        entry_names.setdefault(metadata_type, set()).add(full_name)

    source_counts: dict[str, int] = {}
    gaps: dict[str, list[str]] = {}
    try:
        inventory = ForceAppKnowledge(ROOT).inventory()
    except Exception as error:  # inventory is optional context, never a hard failure here
        return {
            "outcome": "COVERAGE",
            "lanes": lanes,
            "sourceComparison": f"unavailable: {error}",
            "profiledTypes": sorted(PROFILES),
        }
    for component in inventory.get("components", []):
        metadata_type = component["metadataType"]
        source_counts[metadata_type] = source_counts.get(metadata_type, 0) + 1
        if metadata_type in PROFILES and component["name"] not in entry_names.get(metadata_type, set()):
            gaps.setdefault(metadata_type, []).append(component["name"])
    return {
        "outcome": "COVERAGE",
        "profiledTypes": sorted(PROFILES),
        "lanes": {key: dict(sorted(value.items())) for key, value in sorted(lanes.items())},
        "sourceComponents": dict(sorted(source_counts.items())),
        "missingEntries": {key: sorted(value)[:50] for key, value in sorted(gaps.items())},
        "missingEntryCounts": {key: len(value) for key, value in sorted(gaps.items())},
        "unprofiledTypes": sorted(set(source_counts) - set(PROFILES)),
        "note": (
            "Unprofiled types have no entry home yet and keep their v1 repository claims; "
            "that is not a coverage gap (docs/knowledge-one-file-contract.md §1)."
        ),
    }


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
    org_latest = org_ledger_latest()
    lanes = []
    for path in all_entry_paths():
        lane = compute_lane(path, latest)
        if args.identity and lane["identity"] != args.identity:
            continue
        frontmatter, _body = split_entry(path.read_text(encoding="utf-8"))
        if frontmatter.get("orgUsage") or org_latest.get(lane["identity"]):
            org = compute_org_lane(frontmatter, lane["identity"], org_latest)
            disclosed: dict[str, Any] = {
                "section": org["section"],
                "orgs": [
                    {"orgKey": key, **value} for key, value in sorted(org["orgs"].items())
                ],
            }
            if org.get("problems"):
                disclosed["problems"] = org["problems"]
            lane["orgUsage"] = disclosed
        lanes.append(lane)
    return {"outcome": "STATUS", "entries": lanes}


def changed_entry_paths(ref: str) -> set[str] | None:
    """Entry files git reports as changed since `ref`, or None if git cannot answer.

    Git is the authority on what changed, which is what makes the narrow check safe. A stamp
    manifest cannot do this job: one under `.cache/` is git-ignored so CI is always cold, one
    keyed on mtime is inert because `git checkout` rewrites mtimes, and a committed one is
    forgeable — an agent could mark a tampered entry unchanged and skip it past the gate.

    Untracked files are counted as changed, and that is not a detail: `git diff` reports only
    tracked paths, so a brand-new entry — the single most common thing to check — is invisible
    to it. `--others` without `--exclude-standard` on purpose: an entry hidden behind a gitignore
    rule must be checked, not excused. Either subprocess failing yields None, which degrades the
    caller to a full check."""

    import subprocess

    relative = ARTIFACTS_ROOT.relative_to(ROOT).as_posix()
    changed: set[str] = set()
    for command in (
        ["git", "diff", "--name-only", ref, "--", relative],
        ["git", "ls-files", "--others", "--", relative],
    ):
        try:
            completed = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        changed |= {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    return changed


PLAIN_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def identity_from_entry_path(path: Path) -> str | None:
    """The entry's identity read off its path alone, or None when the path cannot prove it.

    `entry_path()` derives the path FROM the identity, so the mapping inverts whenever
    `safe_name` had nothing to escape, truncate or disambiguate — the ordinary case, since
    Salesforce API names are ASCII identifiers. A percent-escape, the 100-char cut or a
    Windows-reserved stem all add or lose bytes, and returning None there is what keeps the
    narrow check honest: an entry whose identity its path cannot prove is opened and parsed
    rather than assumed."""

    try:
        parts = path.relative_to(ARTIFACTS_ROOT).parts
    except ValueError:
        return None
    if len(parts) != 3 or not parts[2].endswith(".md"):
        return None
    metadata_type, namespace, full_name = parts[0], parts[1], parts[2][:-3]
    if not PLAIN_SAFE_NAME_RE.fullmatch(full_name):
        return None
    try:
        if entry_path(metadata_type, namespace, full_name) != path:
            return None
    except StoreError:
        return None
    return identity_of(metadata_type, namespace, full_name)


def command_entry_check(args: argparse.Namespace) -> dict[str, Any]:
    """Whole-corpus integrity gate. `--changed-since` narrows only the per-entry work.

    The per-entry pass is the cost, and it is not where the first version of this command looked
    for it. Profiled at 9 000 entries: `split_entry` (YAML) and `validate_entry` (jsonschema)
    dominate, while `regenerate_fragment_digest` — the only thing the narrow mode used to skip —
    does not reach the top frames at all. That mode saved 2 %, inside noise. `--changed-since
    <ref>` therefore skips the WHOLE per-entry pass for entries git reports as untouched.

    The cross-entry checks — identity collision and case-fold collision — still run over the
    whole corpus; a per-entry skip would silently destroy them (§0.3). They need only an
    identity and a path, and `identity_from_entry_path` reads the identity back off the path
    without opening the file, which is what makes the wider skip possible.

    What the skip rests on, stated because it is the whole safety argument: git — not a
    forgeable manifest — says these bytes are the bytes at <ref>, and <ref> was itself checked
    in full. An unanswerable ref degrades to a full check, never to a pass, and `--full` (no
    flag) stays the default the nightly and CI runs use. Read-only either way."""

    assert_no_reparse_points()
    latest = ledger_latest(read_ledger())
    ref = getattr(args, "changed_since", None)
    changed = changed_entry_paths(ref) if ref else None
    problems: list[str] = []
    seen_identities: dict[str, str] = {}
    seen_casefold: dict[str, str] = {}
    skipped = 0
    for path in all_entry_paths(include_case_twins=True):
        relative = path.relative_to(ROOT).as_posix()
        identity = (
            identity_from_entry_path(path)
            if changed is not None and relative not in changed
            else None
        )
        if identity is not None:
            skipped += 1
        else:
            lane = compute_lane(path, latest)
            identity = lane["identity"]
            problems.extend(f"{relative}: {problem}" for problem in lane["problems"])
        if identity in seen_identities:
            problems.append(f"identity {identity} resolves to two files: {seen_identities[identity]} and {relative}")
        seen_identities[identity] = relative
        folded = relative.casefold()
        if folded in seen_casefold and seen_casefold[folded] != relative:
            problems.append(f"case-fold collision: {seen_casefold[folded]} vs {relative}")
        seen_casefold[folded] = relative
    if problems:
        raise StoreError("entry-check failed:\n- " + "\n- ".join(problems))
    result: dict[str, Any] = {
        "outcome": "PASS",
        "entries": len(seen_identities),
        "ledgerRecords": len(read_ledger()),
    }
    # Advisory org-lane disclosure (contract §14.3): counts + non-fresh attention list. CI
    # never fails on expiry; the HARD tamper check (digest vs org ledger, containment) is
    # validate_harness's. Gated on the org ledger existing so an org-free workspace pays
    # nothing extra here.
    if ORG_LEDGER_PATH.exists():
        org_latest = org_ledger_latest()
        org_counts: dict[str, int] = {}
        org_attention: list[str] = []
        for path in all_entry_paths():
            frontmatter, _body = split_entry(path.read_text(encoding="utf-8"))
            subject = frontmatter["subject"]
            identity = identity_of(subject["metadataType"], subject.get("namespace"), subject["fullName"])
            if not (frontmatter.get("orgUsage") or org_latest.get(identity)):
                continue
            org = compute_org_lane(frontmatter, identity, org_latest)
            if org["section"] in ("org-not-effective",) and not org["orgs"]:
                org_counts["org-not-effective"] = org_counts.get("org-not-effective", 0) + 1
                org_attention.append(f"{identity}: org-not-effective ({'; '.join(org.get('problems', []))})")
            for key, value in org["orgs"].items():
                org_counts[value["status"]] = org_counts.get(value["status"], 0) + 1
                if value["status"] != "org-fresh":
                    org_attention.append(f"{identity} [{key}]: {value['status']}")
        if org_counts:
            result["orgUsage"] = {"counts": dict(sorted(org_counts.items())), "attention": sorted(org_attention)}
    if ref:
        result["changedSince"] = ref
        result["entriesSkipped"] = skipped
        if changed is None:
            result["gap"] = f"git could not report changes since {ref}; every entry was checked in full"
    return result


# --- org-usage layer (contract v1.2 — §2.3 storage, §4 org lanes, §6.6 attach) ----------
#
# Everything here is digest-EXCLUDED: _canonical_facts and reviewed_content_digest enumerate
# closed key sets that never mention orgUsage, so attach/detach provably cannot move an
# approval (contract §5.7); both commands verify that invariant at runtime and refuse to
# write when it would not hold. Authority is machine attestation — the parallel org ledger,
# the sectionDigest, and the sealed receipt — never a human click (owner D-3, 2026-08-03).


class ProbeDropped(Exception):
    """One probe failed derivation; it is dropped and reported, never partially persisted."""


ORG_ATTACH_METADATA_TYPES = frozenset({"CustomObject", "CustomField"})
ORG_PROBE_KINDS = frozenset(
    {
        "object-shape",
        "record-type-distribution",
        "field-fill",
        "field-cardinality",
        "picklist-distribution",
        "recency-window",
        "lookup-shape",
        "record-sample",
    }
)
# Which probe kinds make sense per wave-1 entry type; the entry schema's kind enum is the
# backstop (schemas/knowledge-entry.schema.json $defs.orgUsageProbe).
PROBE_APPLICABILITY = {
    "CustomObject": ORG_PROBE_KINDS,
    "CustomField": frozenset(
        {"field-fill", "field-cardinality", "picklist-distribution", "lookup-shape"}
    ),
}
PROBE_LABEL_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
ORG_API_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,120}$")
EXPLICIT_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
LAST_N_DAYS_RE = re.compile(r"LAST_N_DAYS\s*:\s*(\d+)", re.IGNORECASE)
FROM_OBJECT_RE = re.compile(r"\bFROM\s+([A-Za-z][A-Za-z0-9_]*)", re.IGNORECASE)

# Embedded probes-file schema (owner D-3: executor rigor without a registered schema file).
# Labels are free slugs — owner D-5' 2026-08-03: several probes of one kind under different
# WHERE criteria are legal and encouraged; the closed instrument is the kind enum plus the
# per-kind results shapes in the entry schema.
PROBES_FILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["probes"],
    "properties": {
        "probes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "kind", "query"],
                "properties": {
                    "label": {"type": "string", "pattern": PROBE_LABEL_RE.pattern},
                    "kind": {"enum": sorted(ORG_PROBE_KINDS)},
                    "query": {"type": "string", "minLength": 15, "maxLength": 4000},
                    "field": {"type": "string", "pattern": ORG_API_NAME_RE.pattern},
                    "windowDays": {"type": "integer", "minimum": 1, "maximum": 3650},
                    "targetObjects": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "pattern": ORG_API_NAME_RE.pattern,
                        },
                    },
                },
            },
        }
    },
}


def org_usage_policy() -> dict[str, Any]:
    """The orgUsage policy block; attach fails closed without it (contract §6.6)."""
    if not KNOWLEDGE_POLICY_PATH.exists():
        raise StoreError("config/knowledge-policy.json is missing; the orgUsage policy block is required")
    block = json.loads(KNOWLEDGE_POLICY_PATH.read_text(encoding="utf-8")).get("orgUsage")
    if not isinstance(block, dict):
        raise StoreError("config/knowledge-policy.json has no orgUsage block (contract §6.6)")
    return block


def org_id_digest(expected_organization_id: str) -> str:
    """sha256 of the CONFIGURED expectedOrganizationId — the raw 00D id is never stored."""
    import hashlib

    return "sha256:" + hashlib.sha256(expected_organization_id.encode("utf-8")).hexdigest()


def configured_org(alias: str) -> dict[str, Any]:
    if not LOCAL_CONFIG.exists():
        raise StoreError("config/harness.local.json is required for org attach")
    config = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
    for org in config.get("salesforce", {}).get("orgs", []):
        if org.get("alias") == alias:
            return org
    raise StoreError(f"org alias {alias!r} is not configured")


def _origin_remote_urls() -> list[str]:
    """Every git remote URL; ANY subprocess failure is a refusal, never a pass (§6.6)."""
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "-v"],
            text=True, capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreError("containment: git remote enumeration failed — refusing, never passing (gate 1)") from exc
    if completed.returncode != 0:
        raise StoreError("containment: git remote enumeration failed — refusing, never passing (gate 1)")
    urls = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls.add(parts[1])
    return sorted(urls)


def assert_containment(policy: dict[str, Any]) -> None:
    """Gate 1 (owner D-1 2026-08-03): org-bearing entries live only in the private company
    clone. Empty allowlist — the shipped default on the public origin — refuses everywhere
    and is the standing kill switch. Zero remotes with a SUCCESSFUL enumeration is local-only
    and passes; a failed enumeration never does."""
    allowlist = policy.get("allowedOriginRemotes") or []
    if not allowlist:
        raise StoreError(
            "containment: orgUsage.allowedOriginRemotes is empty — org attach is refused in "
            "this workspace (gate 1; org-bearing entries live only in the company's private "
            "enterprise repository)"
        )
    off_list = [url for url in _origin_remote_urls() if url not in allowlist]
    if off_list:
        raise StoreError("containment: git remote(s) outside the allowlist: " + ", ".join(off_list))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso_or_none(value: Any, context: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProbeDropped(f"{context}: expected an ISO datetime, got {type(value).__name__}")
    try:
        return _parse_iso(value).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ProbeDropped(f"{context}: unparseable datetime {value!r}")


def carry_forward_org_usage(frontmatter: dict[str, Any], path: Path) -> None:
    """Preserve a digest-excluded orgUsage section across a wholesale frontmatter rebuild."""
    if not path.is_file():
        return
    previous, _previous_body = split_entry(path.read_text(encoding="utf-8"))
    if "orgUsage" in previous:
        frontmatter["orgUsage"] = previous["orgUsage"]


def load_probes_file(
    path_text: str, metadata_type: str, object_api_name: str, policy: dict[str, Any]
) -> list[dict[str, Any]]:
    from jsonschema import Draft202012Validator

    path = Path(path_text)
    if not path.is_file():
        raise StoreError(f"probes file not found: {path_text}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoreError(f"probes file is not valid JSON: {exc}") from exc
    errors = sorted(e.message for e in Draft202012Validator(PROBES_FILE_SCHEMA).iter_errors(payload))
    if errors:
        raise StoreError("probes file failed validation: " + "; ".join(errors[:5]))
    probes = payload["probes"]
    labels = [probe["label"] for probe in probes]
    if len(labels) != len(set(labels)):
        raise StoreError("probes file has duplicate labels")
    applicable = PROBE_APPLICABILITY.get(metadata_type, frozenset())
    sample_rows_max = int(policy.get("sampleRowsMax", 50))
    max_columns = int(policy.get("maxSampleColumns", 20))
    for probe in probes:
        label, kind = probe["label"], probe["kind"]
        query = probe["query"].strip()
        probe["query"] = query
        if kind not in applicable:
            raise StoreError(f"probe {label!r}: kind {kind!r} is not applicable to {metadata_type}")
        limit_match = EXPLICIT_LIMIT_RE.search(query)
        if not limit_match:
            raise StoreError(
                f"probe {label!r}: an explicit trailing LIMIT is required — the executed-query "
                "digest must be recomputable from the submitted text (contract §6.6)"
            )
        limit = int(limit_match.group(1))
        from_objects = FROM_OBJECT_RE.findall(query)
        if len(from_objects) != 1 or from_objects[0] != object_api_name:
            raise StoreError(
                f"probe {label!r}: exactly one FROM naming the entry's object "
                f"{object_api_name!r} is required"
            )
        upper = query.upper()
        select_clause = query[: upper.find(" FROM ")] if " FROM " in upper else query
        if any(item.count(".") > 2 for item in select_clause.split(",")):
            raise StoreError(f"probe {label!r}: dotted parent paths deeper than 2 hops (D-NEST)")
        if kind == "record-sample":
            if limit > sample_rows_max:
                raise StoreError(
                    f"probe {label!r}: record-sample LIMIT {limit} exceeds sampleRowsMax {sample_rows_max}"
                )
            if select_clause.count(",") + 1 > max_columns:
                raise StoreError(f"probe {label!r}: more than {max_columns} sample columns")
        if kind == "recency-window" and not (probe.get("windowDays") or LAST_N_DAYS_RE.search(query)):
            raise StoreError(f"probe {label!r}: recency-window needs LAST_N_DAYS in the query or windowDays")
        if kind == "lookup-shape" and not probe.get("targetObjects"):
            raise StoreError(f"probe {label!r}: lookup-shape needs a targetObjects mapping")
    return probes


def _scalar_row(facts: dict[str, Any], label: str) -> dict[str, Any]:
    records = facts.get("records") or []
    if len(records) != 1 or not isinstance(records[0], dict):
        raise ProbeDropped(f"{label}: expected exactly one aggregate row")
    return {key: value for key, value in records[0].items() if key != "attributes"}


def _int_items(row: dict[str, Any]) -> list[tuple]:
    return [
        (key, value)
        for key, value in row.items()
        if isinstance(value, int) and not isinstance(value, bool)
    ]


def _derive_object_shape(facts, probe, policy):
    row = _scalar_row(facts, probe["label"])
    if not isinstance(row.get("recordCount"), int):
        raise ProbeDropped(f"{probe['label']}: alias the count as recordCount (SELECT COUNT(Id) recordCount ...)")
    results: dict[str, Any] = {"recordCount": row["recordCount"]}
    for key in ("createdFirst", "createdLast", "lastModifiedMax"):
        if key in row:
            results[key] = _iso_or_none(row[key], f"{probe['label']}.{key}")
    return results, []


def _derive_distribution(facts, probe, policy):
    floor = int(policy.get("usageGroupSuppressionFloor", 5))
    groups: list[dict[str, Any]] = []
    folded_groups = 0
    folded_count = 0
    for record in facts.get("records") or []:
        if not isinstance(record, dict):
            raise ProbeDropped(f"{probe['label']}: malformed GROUP BY row")
        row = {key: value for key, value in record.items() if key != "attributes"}
        ints = _int_items(row)
        rest = [(key, value) for key, value in row.items() if (key, value) not in ints]
        if len(ints) != 1 or len(rest) != 1:
            raise ProbeDropped(f"{probe['label']}: each GROUP BY row must carry one group key and one count")
        count = ints[0][1]
        key_value = rest[0][1]
        key = "(null)" if key_value is None else str(key_value)[:80]
        if count < floor:
            folded_groups += 1
            folded_count += count
        else:
            groups.append({"key": key, "recordCount": count})
    groups.sort(key=lambda item: (-item["recordCount"], item["key"]))
    results: dict[str, Any] = {"groups": groups[:200], "suppressionFloor": floor}
    if folded_groups:
        results["otherBucket"] = {"suppressedGroups": folded_groups, "recordCount": folded_count}
    if probe.get("field"):
        results["field"] = probe["field"]
    return results, []


def _derive_fill_like(facts, probe, policy, value_key, target_objects=None):
    row = _scalar_row(facts, probe["label"])
    total = row.get("totalCount")
    if not isinstance(total, int):
        raise ProbeDropped(f"{probe['label']}: alias COUNT(Id) as totalCount")
    fields = []
    for key, value in sorted(row.items()):
        if key == "totalCount" or not (isinstance(value, int) and not isinstance(value, bool)):
            continue
        entry: dict[str, Any] = {"field": key, value_key: value, "totalCount": total}
        if target_objects is not None:
            target = target_objects.get(key)
            if not target:
                raise ProbeDropped(f"{probe['label']}: no targetObjects mapping for field {key!r}")
            entry["targetObject"] = target
        fields.append(entry)
    if not fields:
        raise ProbeDropped(f"{probe['label']}: no per-field counts found (alias each COUNT(field) as the field name)")
    return {"fields": fields[:200]}, []


def _derive_field_fill(facts, probe, policy):
    return _derive_fill_like(facts, probe, policy, "filledCount")


def _derive_field_cardinality(facts, probe, policy):
    return _derive_fill_like(facts, probe, policy, "distinctCount")


def _derive_lookup_shape(facts, probe, policy):
    return _derive_fill_like(facts, probe, policy, "filledCount", probe.get("targetObjects") or {})


def _derive_recency_window(facts, probe, policy):
    row = _scalar_row(facts, probe["label"])
    count = row.get("recordCount")
    if not isinstance(count, int):
        raise ProbeDropped(f"{probe['label']}: alias COUNT(Id) as recordCount")
    declared = probe.get("windowDays")
    match = LAST_N_DAYS_RE.search(probe["query"])
    parsed = int(match.group(1)) if match else None
    if declared and parsed and declared != parsed:
        raise ProbeDropped(f"{probe['label']}: windowDays {declared} disagrees with LAST_N_DAYS:{parsed}")
    window = declared or parsed
    return {"windows": [{"windowDays": window, "recordCount": count}]}, []


def _flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "attributes":
            continue
        path_key = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten_record(value, path_key + "."))
        else:
            out[path_key] = value
    return out


def _collect_structure(record: dict[str, Any], prefix: str, out: dict[str, dict[str, Any]]) -> None:
    for key, value in record.items():
        if key == "attributes":
            continue
        path_key = f"{prefix}{key}"
        if isinstance(value, dict):
            info = out.setdefault(path_key, {"types": set(), "populated": 0})
            info["populated"] += 1
            attributes = value.get("attributes")
            if isinstance(attributes, dict) and isinstance(attributes.get("type"), str):
                info["types"].add(attributes["type"])
            _collect_structure(value, path_key + ".", out)


def _derive_record_sample(facts, probe, policy):
    records = [record for record in (facts.get("records") or []) if isinstance(record, dict)]
    if not records:
        raise ProbeDropped(f"{probe['label']}: zero rows sampled")
    sample_size = len(records)
    if sample_size > int(policy.get("sampleRowsMax", 50)):
        raise ProbeDropped(f"{probe['label']}: sample of {sample_size} rows exceeds sampleRowsMax")
    fill: dict[str, int] = {}
    relationship: dict[str, dict[str, Any]] = {}
    for record in records:
        for path_key, value in _flatten_record(record).items():
            populated = value is not None and value != ""
            fill[path_key] = fill.get(path_key, 0) + (1 if populated else 0)
        _collect_structure(record, "", relationship)
    field_fill = [
        {"field": key, "populatedCount": count, "sampleSize": sample_size}
        for key, count in sorted(fill.items())
        if ORG_API_NAME_RE.fullmatch(key)  # closed vocabulary: residual keys are dropped
    ][:40]
    if not field_fill:
        raise ProbeDropped(f"{probe['label']}: no conforming sampled columns")
    structure_rows = []
    for prefix, info in sorted(relationship.items()):
        types = sorted(info["types"])
        if not types or not ORG_API_NAME_RE.fullmatch(types[0]) or not ORG_API_NAME_RE.fullmatch(prefix):
            continue
        structure_rows.append(
            {
                "path": prefix,
                "targetObject": types[0],
                "populated": f"{info['populated']}/{sample_size}",
                "sampleSize": sample_size,
                "polymorphicObservedType": types[1] if len(types) > 1 else None,
            }
        )
    return {"sampleSize": sample_size, "fieldFill": field_fill}, structure_rows[:40]


DERIVERS = {
    "object-shape": _derive_object_shape,
    "record-type-distribution": _derive_distribution,
    "picklist-distribution": _derive_distribution,
    "field-fill": _derive_field_fill,
    "field-cardinality": _derive_field_cardinality,
    "lookup-shape": _derive_lookup_shape,
    "recency-window": _derive_recency_window,
    "record-sample": _derive_record_sample,
}


def _facade_call(alias: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Facade subprocess client — the executor observes; the agent never carries attested
    bytes (fabrication defense: agents cannot mint digests). Imported lazily because
    work_record imports this module."""
    try:
        from scripts.work_record import call_salesforce_review_facade
    except ModuleNotFoundError:  # invoked as a script
        from work_record import call_salesforce_review_facade  # type: ignore
    return call_salesforce_review_facade(ROOT, alias, tool, arguments)


def org_ledger_latest() -> dict[str, dict[str, Any]]:
    return ledger_latest(read_ledger(ORG_LEDGER_PATH))


def compute_org_lane(
    frontmatter: dict[str, Any],
    identity: str,
    org_latest: "dict[str, dict[str, Any]] | None" = None,
    now: "datetime | None" = None,
) -> dict[str, Any]:
    """Read-time org lanes (contract §4) — parallel to compute_lane; never touches approval.

    Freshness applies min(stored expiresAt, observedAt + CURRENT policy window): the stored
    stamp is a ceiling, not a grant, so tightening the policy expires existing blocks
    retroactively. A missing policy block behaves as a zero-day window — fail-closed to
    org-expired, never to fresh."""
    from datetime import timedelta

    if org_latest is None:
        org_latest = org_ledger_latest()
    moment = now or datetime.now(timezone.utc)
    section = frontmatter.get("orgUsage")
    record = org_latest.get(identity)
    if not section:
        if record is not None and record.get("action") == "attach":
            return {
                "section": "org-not-effective",
                "orgs": {},
                "problems": ["orgUsage section missing while the latest org-ledger record is an attach"],
            }
        return {"section": "org-absent", "orgs": {}}
    orgs = section.get("orgs") or {}
    recomputed = canonical_digest(orgs)
    problems: list[str] = []
    if section.get("sectionDigest") != recomputed:
        problems.append("orgUsage.sectionDigest does not recompute (hand-edit or corruption)")
    if record is None:
        problems.append("orgUsage present without any org-ledger record")
    elif record.get("orgUsageDigest") != recomputed:
        problems.append(
            "orgUsage digest is not the latest org-ledger record (replay or crash — "
            "recover forward with entry-org-attach or entry-org-detach, contract §6.6)"
        )
    if problems:
        return {
            "section": "org-not-effective",
            "orgs": {key: {"status": "org-not-effective"} for key in orgs},
            "problems": problems,
        }
    try:
        max_age_days = int(org_usage_policy().get("maxOrgUsageAgeDays", 0))
    except StoreError:
        max_age_days = 0
    config_orgs: dict[str, dict[str, Any]] = {}
    if LOCAL_CONFIG.exists():
        raw = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        config_orgs = {org.get("alias"): org for org in raw.get("salesforce", {}).get("orgs", [])}
    lanes: dict[str, dict[str, Any]] = {}
    for key, block in orgs.items():
        observed = _parse_iso(block["observedAt"])
        effective_expiry = min(_parse_iso(block["expiresAt"]), observed + timedelta(days=max_age_days))
        configured = config_orgs.get(key)
        status, reason = "org-fresh", None
        if configured is None:
            status, reason = "org-superseded", "alias is no longer configured"
        elif (
            not configured.get("expectedOrganizationId")
            or org_id_digest(configured["expectedOrganizationId"]) != block.get("orgIdDigest")
        ):
            status, reason = "org-superseded", "configured org identity changed (sandbox refresh)"
        elif configured.get("refreshedAt") and observed < _parse_iso(configured["refreshedAt"]):
            status, reason = "org-superseded", "observed before the owner-declared sandbox refresh"
        elif moment >= effective_expiry:
            status = "org-expired"
        lane: dict[str, Any] = {
            "status": status,
            "observedAt": block["observedAt"],
            "expiresAt": effective_expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "environment": block.get("environment"),
        }
        if "fullCopy" in block:
            lane["fullCopy"] = block["fullCopy"]
        if reason:
            lane["reason"] = reason
        lanes[key] = lane
    return {"section": "org-effective", "orgs": lanes}


def command_entry_org_attach(args: argparse.Namespace) -> dict[str, Any]:
    """Machine-attested org attach (contract §6.6; click-free by owner D-3: the human
    approved the INSTRUMENT — closed shapes, executor derivers, sanitization, expiry, the
    containment allowlist — not each number). Fail-closed preconditions run in contract
    order; ANY identity or environment mismatch mid-run aborts the WHOLE attach."""
    import hashlib
    from datetime import timedelta

    assert_no_reparse_points()
    policy = org_usage_policy()
    assert_containment(policy)
    metadata_type, namespace_segment, full_name = args.identity.split(":", 2)
    if metadata_type not in ORG_ATTACH_METADATA_TYPES:
        raise StoreError(
            "org attach is wave-1 only ("
            + ", ".join(sorted(ORG_ATTACH_METADATA_TYPES))
            + f"); got {metadata_type!r}"
        )
    namespace = None if namespace_segment == "c" else namespace_segment
    path = entry_path(metadata_type, namespace, full_name)
    if not path.is_file():
        raise StoreError(f"no entry for {args.identity}")
    frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
    if frontmatter.get("sensitivity") == "public":
        raise StoreError("org observations cannot attach to a public-sensitivity entry")
    org = configured_org(args.org)
    if org.get("environment") not in {"development", "qa", "uat"}:
        raise StoreError(f"org {args.org!r}: environment {org.get('environment')!r} is not attachable")
    if org.get("allowAgentRead") is not True or org.get("allowAgentReview") is not True:
        raise StoreError(f"org {args.org!r} does not allow agent read+review")
    expected_org_id = org.get("expectedOrganizationId")
    if not expected_org_id:
        raise StoreError(
            "dynamic-lane refused (owner D-4): the alias has no configured expectedOrganizationId"
        )
    object_api_name = full_name.split(".", 1)[0]
    probes = load_probes_file(args.probes_file, metadata_type, object_api_name, policy)

    digest_before = reviewed_content_digest(frontmatter, body)
    executed: dict[str, dict[str, Any]] = {}
    receipt_probes: dict[str, dict[str, Any]] = {}
    structure_rows: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for probe in probes:
        label = probe["label"]
        envelope = _facade_call(args.org, "review_soql_query", {"query": probe["query"]})
        target = envelope.get("target") or {}
        if (
            target.get("environment") == "dynamic"
            or target.get("nonProduction") is not True
            or target.get("expectedOrgIdMatched") is not True
            or target.get("environment") != org.get("environment")
        ):
            raise StoreError(
                f"probe {label!r}: org identity/environment mismatch — the whole attach is "
                "aborted and nothing is persisted (one attach is one org snapshot, contract §6.6)"
            )
        if envelope.get("status") != "VERIFIED" or (envelope.get("completeness") or {}).get("complete") is not True:
            dropped.append({"label": label, "reason": f"status {envelope.get('status')}"})
            continue
        facts = (envelope.get("facts") or {}).get("soqlQuery") or {}
        query_digest = hashlib.sha256(probe["query"].encode("utf-8")).hexdigest()
        if facts.get("queryDigest") != query_digest:
            raise StoreError(
                f"probe {label!r}: QUERY_DIGEST_MISMATCH — the facade executed different text "
                "than was submitted; refusing the whole attach"
            )
        if facts.get("fromObjects") != [object_api_name]:
            raise StoreError(
                f"probe {label!r}: envelope fromObjects {facts.get('fromObjects')!r} is not the entry's object"
            )
        try:
            results, rows = DERIVERS[probe["kind"]](facts, probe, policy)
        except ProbeDropped as reason:
            dropped.append({"label": label, "reason": str(reason)})
            continue
        executed[label] = {
            "kind": probe["kind"],
            "queryDigest": f"sha256:{query_digest}",
            "completeness": "complete",
            "results": results,
        }
        structure_rows.extend(rows)
        receipt_probes[label] = {
            "queryText": probe["query"],
            "queryDigest": f"sha256:{query_digest}",
            "kind": probe["kind"],
            "envelope": envelope,
        }
    if not executed:
        raise StoreError("no probe completed — nothing to persist; dropped: " + json.dumps(dropped))

    observed_at = _utc_now_iso()
    max_age_days = int(policy.get("maxOrgUsageAgeDays", 0))
    if max_age_days < 1:
        raise StoreError("orgUsage.maxOrgUsageAgeDays must be a positive integer")
    expires_at = (_parse_iso(observed_at) + timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    block: dict[str, Any] = {
        "environment": org["environment"],
        "orgIdDigest": org_id_digest(expected_org_id),
        "observedAt": observed_at,
        "expiresAt": expires_at,
        "shapeVersion": 1,
        "transport": "mcp-review-facade",
        "assurance": "org-observed",
        "probes": executed,
    }
    if isinstance(org.get("fullCopy"), bool):
        block["fullCopy"] = org["fullCopy"]
    if structure_rows:
        seen_paths = set()
        unique_rows = []
        for row in structure_rows:
            if row["path"] not in seen_paths:
                seen_paths.add(row["path"])
                unique_rows.append(row)
        block["recordStructure"] = unique_rows[:40]

    run_id = observed_at.replace("-", "").replace(":", "") + "-" + canonical_digest(
        {"identity": args.identity, "orgKey": args.org, "queries": sorted(p["query"] for p in probes)}
    )[7:15]
    wrapper: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": run_id,
        "identity": args.identity,
        "orgKey": args.org,
        "attachedAt": observed_at,
        "probes": receipt_probes,
    }
    receipt_digest = canonical_digest(wrapper)
    wrapper["wrapperDigest"] = receipt_digest
    block["receiptDigest"] = receipt_digest

    orgs = dict((frontmatter.get("orgUsage") or {}).get("orgs") or {})
    orgs[args.org] = block
    frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}

    problems = [
        problem
        for problem in validate_entry(frontmatter, body)
        if "sentinel" not in problem  # a draft entry awaiting its description may still attach
    ]
    if problems:
        raise StoreError("attach would leave an invalid entry: " + "; ".join(problems))
    digest_after = reviewed_content_digest(frontmatter, body)
    if digest_after != digest_before:
        raise StoreError("INVARIANT BREACH: attach would move the approval digest — refusing (contract §5.7)")

    receipt_path = ORG_USAGE_CACHE / safe_name(args.identity, args.identity) / f"{run_id}.json"
    if len(relative_path(receipt_path)) > PATH_BUDGET:
        raise StoreError(f"receipt path exceeds the {PATH_BUDGET}-char budget (contract §3)")
    # Write ordering (contract §6.6): receipt -> entry -> org ledger. A crash between the last
    # two leaves org-not-effective and a failing validate check; recovery is forward-only.
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    atomic_write(path, render_entry(frontmatter, body))
    append_ledger(
        [
            {
                "action": "attach",
                "identity": args.identity,
                "orgKey": args.org,
                "orgUsageDigest": frontmatter["orgUsage"]["sectionDigest"],
                "observedAt": observed_at,
                "expiresAt": expires_at,
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": receipt_digest,
            }
        ],
        ORG_LEDGER_PATH,
    )
    return {
        "outcome": "ORG_ATTACHED",
        "identity": args.identity,
        "orgKey": args.org,
        "probes": sorted(executed),
        "dropped": dropped,
        "observedAt": observed_at,
        "expiresAt": expires_at,
        "approvalDigestBefore": digest_before,
        "approvalDigestAfter": digest_after,
        "approvalPreserved": digest_after == digest_before,
        "receipt": relative_path(receipt_path),
    }


def command_entry_org_detach(args: argparse.Namespace) -> dict[str, Any]:
    """Remove one org's block; approvals are untouched by the same closed-key-set argument."""
    assert_no_reparse_points()
    metadata_type, namespace_segment, full_name = args.identity.split(":", 2)
    namespace = None if namespace_segment == "c" else namespace_segment
    path = entry_path(metadata_type, namespace, full_name)
    if not path.is_file():
        raise StoreError(f"no entry for {args.identity}")
    frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
    org_usage = frontmatter.get("orgUsage") or {}
    orgs = dict(org_usage.get("orgs") or {})
    if args.org not in orgs:
        raise StoreError(f"no org block for {args.org!r} on {args.identity}")
    digest_before = reviewed_content_digest(frontmatter, body)
    orgs.pop(args.org)
    if orgs:
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        new_digest = frontmatter["orgUsage"]["sectionDigest"]
    else:
        frontmatter.pop("orgUsage", None)
        new_digest = None
    problems = [p for p in validate_entry(frontmatter, body) if "sentinel" not in p]
    if problems:
        raise StoreError("detach would leave an invalid entry: " + "; ".join(problems))
    digest_after = reviewed_content_digest(frontmatter, body)
    if digest_after != digest_before:
        raise StoreError("INVARIANT BREACH: detach would move the approval digest — refusing (contract §5.7)")
    atomic_write(path, render_entry(frontmatter, body))
    append_ledger(
        [
            {
                "action": "detach",
                "identity": args.identity,
                "orgKey": args.org,
                "orgUsageDigest": new_digest,
                "rationale": args.rationale,
                "detachedAt": _utc_now_iso(),
            }
        ],
        ORG_LEDGER_PATH,
    )
    return {
        "outcome": "ORG_DETACHED",
        "identity": args.identity,
        "orgKey": args.org,
        "remainingOrgs": sorted(orgs),
        "approvalPreserved": digest_after == digest_before,
    }


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

    context = commands.add_parser(
        "entry-context", help="source, facts and reverse usage for writing a description"
    )
    context.add_argument("--identity", required=True)
    context.add_argument("--max-source-chars", type=int, default=8000)
    context.set_defaults(func=command_entry_context)

    describe = commands.add_parser(
        "entry-describe", help="write the agent-authored description into an existing entry"
    )
    describe.add_argument("--identity", required=True)
    describe.add_argument("--purpose-file", required=True)
    describe.add_argument("--limitation", action="append", default=None)
    describe.add_argument("--clear-limitations", action="store_true")
    describe.set_defaults(func=command_entry_describe)

    review = commands.add_parser(
        "entry-review", help="render the executor-authored review surface and the pinned command"
    )
    review.add_argument("--identity", action="append", default=None)
    review.set_defaults(func=command_entry_review)

    revoke = commands.add_parser("entry-revoke", help="append a revocation for an identity")
    revoke.add_argument("--identity", required=True)
    revoke.add_argument("--rationale", required=True)
    revoke.set_defaults(func=command_entry_revoke)

    status = commands.add_parser("entry-status", help="computed lanes for entries")
    status.add_argument("--identity", default=None)
    status.set_defaults(func=command_entry_status)

    coverage = commands.add_parser(
        "entry-coverage", help="entry coverage per metadata type against force-app source"
    )
    coverage.set_defaults(func=command_entry_coverage)

    org_attach = commands.add_parser(
        "entry-org-attach",
        help="run governed SOQL probes and attach the derived orgUsage block (click-free; contract §6.6)",
    )
    org_attach.add_argument("--identity", required=True)
    org_attach.add_argument("--org", required=True)
    org_attach.add_argument("--probes-file", required=True)
    org_attach.set_defaults(func=command_entry_org_attach)

    org_detach = commands.add_parser(
        "entry-org-detach", help="remove one org's usage block and append the detach to the org ledger"
    )
    org_detach.add_argument("--identity", required=True)
    org_detach.add_argument("--org", required=True)
    org_detach.add_argument("--rationale", required=True)
    org_detach.set_defaults(func=command_entry_org_detach)

    check = commands.add_parser("entry-check", help="CI validation of all entries and the ledger")
    check.add_argument(
        "--changed-since",
        default=None,
        help="git ref: re-digest source fragments only for entries changed since it "
        "(collision checks always cover the whole corpus)",
    )
    check.set_defaults(func=command_entry_check)

    propose = commands.add_parser("feature-propose", help="write a feature's boundary rule as a draft")
    propose.add_argument("--slug", required=True)
    propose.add_argument("--name", required=True)
    propose.add_argument("--anchor", action="append", default=None)
    propose.add_argument("--hub", action="append", default=None)
    propose.add_argument("--depth", type=int, default=1)
    propose.add_argument("--include", action="append", default=None)
    propose.add_argument("--exclude", action="append", default=None)
    propose.add_argument(
        "--assurance-floor", default="source-exact",
        choices=["source-exact", "source-derived-heuristic"],
    )
    propose.add_argument("--replace", action="store_true")
    propose.set_defaults(func=command_feature_propose)

    fdescribe = commands.add_parser("feature-describe", help="write what the feature IS")
    fdescribe.add_argument("--slug", required=True)
    fdescribe.add_argument("--purpose-file", required=True)
    fdescribe.set_defaults(func=command_feature_describe)

    fstatus = commands.add_parser("feature-status", help="lanes for every feature")
    fstatus.add_argument("--slug", default=None)
    fstatus.set_defaults(func=command_feature_status)

    freview = commands.add_parser("feature-review", help="render the human review surface")
    freview.add_argument("--slug", action="append", default=None)
    freview.set_defaults(func=command_feature_review)

    fapprove = commands.add_parser("feature-approve", help="digest-pinned approval of boundary rules")
    fapprove.add_argument("--feature", action="append", default=None)
    fapprove.set_defaults(func=command_feature_approve)

    frevoke = commands.add_parser("feature-revoke", help="revoke an approved feature")
    frevoke.add_argument("--slug", required=True)
    frevoke.add_argument("--rationale", required=True)
    frevoke.set_defaults(func=command_feature_revoke)

    fcheck = commands.add_parser("feature-check", help="CI validation of features and their ledger")
    fcheck.set_defaults(func=command_feature_check)
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


# --- Feature Entries (contract §13) -----------------------------------------------------
#
# A Feature Entry approves a BOUNDARY RULE and a human description — never a member list.
# That split is the whole design. Membership is a function of the rule AND of the package,
# so storing it would mean every new artifact drifts every feature that could contain it,
# and a reviewer would be re-approving a list they never read. Membership is recomputed on
# demand and reported as an advisory; `feature-drift` says what moved since approval.


FEATURE_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
FEATURE_SENTINEL = "<AGENT_FEATURE_DESCRIPTION>"


BOUNDARY_NAME_CLOSEST = 3


def source_object_names() -> tuple[set[str], str | None]:
    """Every component and owning-object name force-app currently holds.

    One cached JSON read, the same source `entry-coverage` uses, deliberately NOT an rglob over
    the artifact corpus: a single-feature command paying a walk over a 15 k-entry store is the
    scale defect this module already warns about. Returns the reason instead of raising when the
    inventory is unavailable — a boundary must still be writable on a machine that has not run
    `inventory` yet.
    """

    from scripts.force_app_knowledge import ForceAppKnowledge

    try:
        inventory = ForceAppKnowledge(ROOT).inventory()
    except Exception as error:  # noqa: BLE001 - advisory context, never a hard failure
        return set(), f"unavailable: {error}"
    names: set[str] = set()
    for component in inventory.get("components", []):
        name = component.get("name")
        if not name:
            continue
        names.add(str(name))
        owner = (component.get("facts") or {}).get("object")
        if owner:
            names.add(str(owner))
        if "." in str(name):
            names.add(str(name).split(".", 1)[0])
    return names, None


def resolve_boundary_names(names: list[str]) -> dict[str, Any]:
    """Advisory: does each name in a boundary rule exist in this workspace's source?

    `feature-propose` stripped whitespace and wrote, so a typo landed inside a rule that a human
    then approved and a digest then pinned. Worse, an unresolvable name and a name the walk simply
    never reached produce the SAME silence — measured on the first real store, where a rule
    declared four hubs, none fired, and nothing distinguished "correct but not reached" from
    "does not exist".

    Advisory on purpose. A hard gate here would reject an anchor whose object-meta.xml is absent
    from a fixture, and would couple a pure file write to git and to the inventory schema — the
    failure `entry-coverage` deliberately soft-handles. The reviewer is told; nothing is refused.
    """

    import difflib

    known, unavailable = source_object_names()
    rows: dict[str, Any] = {}
    for name in sorted({str(item).strip() for item in names if str(item).strip()}):
        if unavailable:
            rows[name] = {"status": "unknown", "closest": []}
            continue
        if name in known:
            rows[name] = {"status": "in-source", "closest": []}
            continue
        rows[name] = {
            "status": "not-in-workspace",
            # A near miss is the typo signal. An exact absence with no near miss is usually a
            # standard or packaged object, which is a legitimate hub and not an error.
            "closest": difflib.get_close_matches(name, sorted(known), n=BOUNDARY_NAME_CLOSEST, cutoff=0.8),
        }
    return {
        "names": rows,
        "basis": unavailable or "force-app inventory",
        "notInWorkspace": sorted(n for n, row in rows.items() if row["status"] == "not-in-workspace"),
    }


def feature_identity(slug: str) -> str:
    """`Feature:<slug>` — two segments, deliberately.

    Three segments would match the artifact identity shape closely enough that
    work_record.entry_relative_path's unpack succeeds and produces a path under
    ARTIFACTS_ROOT that does not exist. Two segments cannot be unpacked that way, so a
    Feature offered as an entryRef fails loudly instead of resolving to nothing."""

    return f"Feature:{slug}"


def feature_path(slug: str) -> Path:
    if not FEATURE_SLUG_RE.match(slug):
        raise StoreError(
            f"feature slug {slug!r} must be lowercase alphanumeric with single hyphens"
        )
    if slug.upper().split("-")[0] in WINDOWS_RESERVED:
        raise StoreError(f"feature slug {slug!r} starts with a Windows reserved device name")
    return FEATURES_ROOT / f"{slug}.md"


def all_feature_paths() -> list[Path]:
    return sorted(FEATURES_ROOT.glob("*.md")) if FEATURES_ROOT.exists() else []


def canonical_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    """The rule in a form whose digest is stable under reordering.

    Anchors and hubs are sets in meaning, so `[A, B]` and `[B, A]` are the same rule and must
    not produce different digests — otherwise a cosmetic edit would demand re-approval."""

    return {
        "anchors": sorted(set(boundary.get("anchors") or [])),
        "hubs": sorted(set(boundary.get("hubs") or [])),
        "depth": int(boundary.get("depth", 1)),
        "include": sorted(set(boundary.get("include") or [])),
        "exclude": sorted(set(boundary.get("exclude") or [])),
        "membershipAssuranceFloor": boundary.get("membershipAssuranceFloor") or "source-exact",
    }


def boundary_digest(boundary: dict[str, Any]) -> str:
    return canonical_digest(canonical_boundary(boundary))


def feature_reviewed_content_digest(frontmatter: dict[str, Any], body: str) -> str:
    """What approval binds: the identity, the rule, the prose, the sensitivity.

    Membership is absent by construction — that is what makes an approved feature immune to
    package growth."""

    return canonical_digest(
        {
            "identity": feature_identity(frontmatter["subject"]["slug"]),
            "kind": "feature-entry",
            "schemaVersion": frontmatter["schemaVersion"],
            "boundaryDigest": boundary_digest(frontmatter["boundary"]),
            "semanticsDigest": semantics_digest(body),
            "sensitivity": frontmatter["sensitivity"],
        }
    )


def validate_feature(frontmatter: dict[str, Any], body: str) -> list[str]:
    problems: list[str] = []
    schema = load_schema("knowledge-feature-entry.schema.json")
    from jsonschema import Draft202012Validator

    problems.extend(
        error.message for error in Draft202012Validator(schema).iter_errors(frontmatter)
    )
    if SENTINEL_PATTERN.search(body):
        problems.append("unfilled <AGENT_...> sentinel present (contract §13)")
    if "## Purpose" not in body:
        problems.append("body must carry a '## Purpose' section")
    return problems


def compute_feature_lane(path: Path, latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Lane for one Feature Entry.

    No source-fragment check: a Feature has no source. Its facts are the human's rule, so the
    only things that can invalidate it are an edit to that rule, an edit to the prose, or a
    ledger move."""

    frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
    slug = frontmatter.get("subject", {}).get("slug", "")
    identity = feature_identity(slug)
    result: dict[str, Any] = {
        "identity": identity,
        "path": relative_path(path),
        "problems": validate_feature(frontmatter, body),
    }
    if result["problems"] or frontmatter.get("lifecycle", {}).get("state") == "draft":
        result["lane"] = "draft" if not result["problems"] else "not-effective"
        result["reviewedContentDigest"] = (
            feature_reviewed_content_digest(frontmatter, body) if not result["problems"] else None
        )
        result["boundaryDigest"] = (
            boundary_digest(frontmatter["boundary"]) if not result["problems"] else None
        )
        return result

    digest = feature_reviewed_content_digest(frontmatter, body)
    record = latest.get(identity)
    result["reviewedContentDigest"] = digest
    result["boundaryDigest"] = boundary_digest(frontmatter["boundary"])
    if record is None:
        result["lane"] = "not-effective"
        result["problems"].append("file claims approved but no ledger record approves it")
    elif record.get("action") == "revoke":
        result["lane"] = "revoked"
    elif record.get("reviewedContentDigest") != digest:
        result["lane"] = "not-effective"
        result["problems"].append("content digest does not match the approved ledger record")
    elif any(
        frontmatter["approval"].get(field) != record.get(field)
        for field in ("reviewedBy", "reviewedAt", "mechanism")
    ):
        result["lane"] = "not-effective"
        result["problems"].append("in-file approval provenance mismatches the ledger record")
    else:
        result["lane"] = "approved-current"
    return result


def command_feature_propose(args: argparse.Namespace) -> dict[str, Any]:
    """Write (or replace) a feature's boundary rule as a draft.

    The rule is authored, not discovered. `feature-crawl` proposes a starting point, but what
    lands here is a human's decision about where the feature ends — which is why depth alone
    is not enough: on a 20-object package depth 2 already reaches 13 objects."""

    assert_no_reparse_points(FEATURES_ROOT)
    path = feature_path(args.slug)
    if path.exists() and not args.replace:
        raise StoreError(f"{feature_identity(args.slug)} already exists; pass --replace to rewrite its rule")
    boundary = {
        "anchors": [item.strip() for item in (args.anchor or []) if item.strip()],
        "hubs": [item.strip() for item in (args.hub or []) if item.strip()],
        "depth": int(args.depth),
        "include": [item.strip() for item in (args.include or []) if item.strip()],
        "exclude": [item.strip() for item in (args.exclude or []) if item.strip()],
        "membershipAssuranceFloor": args.assurance_floor,
    }
    if not boundary["anchors"]:
        raise StoreError("a feature boundary needs at least one --anchor")
    body = f"## Purpose\n\n{FEATURE_SENTINEL}\n"
    if path.exists():
        _previous_front, previous_body = split_entry(path.read_text(encoding="utf-8"))
        if FEATURE_SENTINEL not in previous_body:
            body = previous_body  # keep an authored description across a rule change
    frontmatter: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "feature-entry",
        "subject": {"slug": args.slug, "name": args.name},
        "boundary": canonical_boundary(boundary),
        "lifecycle": {"state": "draft", "contentDigest": None},
        "limitations": [],
        "keywords": [],
        "candidateKeywords": [],
        "sensitivity": "internal-sanitized",
        "approval": {
            "reviewedContentDigest": None, "reviewedBy": None,
            "reviewedAt": None, "mechanism": None,
        },
    }
    digest = feature_reviewed_content_digest(frontmatter, body)
    frontmatter["lifecycle"]["contentDigest"] = digest
    atomic_write(path, render_entry(frontmatter, body))
    return {
        "outcome": "PROPOSED",
        "identity": feature_identity(args.slug),
        "path": relative_path(path),
        "boundary": frontmatter["boundary"],
        "boundaryDigest": boundary_digest(frontmatter["boundary"]),
        "reviewedContentDigest": digest,
        "describedYet": FEATURE_SENTINEL not in body,
        "nameResolution": resolve_boundary_names(
            boundary["anchors"] + boundary["hubs"] + boundary["include"] + boundary["exclude"]
        ),
    }


def command_feature_describe(args: argparse.Namespace) -> dict[str, Any]:
    """Write the human description of what the feature IS.

    A boundary rule says which artifacts; it cannot say why they belong together. That is the
    part no traversal can derive and the part a reviewer is really approving."""

    assert_no_reparse_points(FEATURES_ROOT)
    path = feature_path(args.slug)
    if not path.is_file():
        raise StoreError(f"no feature to describe: {feature_identity(args.slug)}")
    frontmatter, _previous = split_entry(path.read_text(encoding="utf-8"))
    description = normalize_body(Path(args.purpose_file).read_text(encoding="utf-8"))
    if not description.strip():
        raise StoreError("the description file is empty")
    if SENTINEL_PATTERN.search(description):
        raise StoreError("the description still contains an <AGENT_...> sentinel")
    body = f"## Purpose\n\n{description}"
    frontmatter["lifecycle"] = {"state": "draft", "contentDigest": None}
    frontmatter["approval"] = {
        "reviewedContentDigest": None, "reviewedBy": None, "reviewedAt": None, "mechanism": None,
    }
    digest = feature_reviewed_content_digest(frontmatter, body)
    frontmatter["lifecycle"]["contentDigest"] = digest
    atomic_write(path, render_entry(frontmatter, body))
    return {
        "outcome": "DESCRIBED",
        "identity": feature_identity(args.slug),
        "reviewedContentDigest": digest,
        "note": "rewriting a description returns the feature to draft; the previous approval covered the previous text",
    }


def command_feature_status(args: argparse.Namespace) -> dict[str, Any]:
    latest = ledger_latest(read_ledger(FEATURE_LEDGER_PATH))
    wanted = feature_identity(args.slug) if getattr(args, "slug", None) else None
    features = []
    for path in all_feature_paths():
        lane = compute_feature_lane(path, latest)
        if wanted and lane["identity"] != wanted:
            continue
        features.append(lane)
    return {"outcome": "STATUS", "features": features, "count": len(features)}


def command_feature_review(args: argparse.Namespace) -> dict[str, Any]:
    """Render what a human must read before approving, and the digest-pinned command."""

    latest = ledger_latest(read_ledger(FEATURE_LEDGER_PATH))
    wanted = {feature_identity(slug) for slug in (args.slug or [])}
    resolved = []
    skipped = []
    for path in all_feature_paths():
        lane = compute_feature_lane(path, latest)
        if wanted and lane["identity"] not in wanted:
            continue
        if lane["problems"]:
            skipped.append({"identity": lane["identity"], "reasons": lane["problems"]})
            continue
        # D7: an explicit --slug is a request to RE-render — the remedy `feature-approve` and
        # `feature-drift` both prescribe when no membershipDigest could be pinned. Only a bare
        # sweep skips the already-approved, and it must say so rather than answer with silence.
        if lane["lane"] == "approved-current" and not wanted:
            skipped.append({"identity": lane["identity"],
                            "reasons": ["already approved-current; name it with --slug to re-render"]})
            continue
        frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
        resolved.append((lane["identity"], frontmatter, body, lane["reviewedContentDigest"]))
    if not resolved:
        return {"outcome": "NOTHING_TO_REVIEW", "skipped": skipped}
    chunk_id = canonical_digest(sorted((identity, digest) for identity, _f, _b, digest in resolved))[7:19]
    lines = [f"# Feature approval review — chunk {chunk_id}", "",
             f"Features: {len(resolved)}", "",
             "You are approving a BOUNDARY RULE and a description — not a member list. Membership "
             "is recomputed from the rule, so adding an artifact to the package cannot change what "
             "you approved here. `feature-drift` reports what membership did afterwards.", ""]
    for identity, frontmatter, body, digest in resolved:
        boundary = frontmatter["boundary"]
        lines += [
            f"## {identity}", "",
            f"- name: {frontmatter['subject']['name']}",
            f"- digest: `{digest}`",
            f"- anchors: {', '.join(boundary['anchors']) or '(none)'}",
            f"- hubs (kept as targets, never expanded): {', '.join(boundary['hubs']) or '(none)'}",
            f"- depth: {boundary['depth']}",
            f"- explicit include: {', '.join(boundary['include']) or '(none)'}",
            f"- explicit exclude: {', '.join(boundary['exclude']) or '(none)'}",
            f"- membership assurance floor: {boundary['membershipAssuranceFloor']}",
        ]
        # Every name in the rule is about to be pinned by a digest, and nothing checked that any
        # of them exists: `feature-propose` strips whitespace and writes. An unresolvable name and
        # a name the walk never reached look identical in every other output.
        resolution = resolve_boundary_names(
            boundary["anchors"] + boundary["hubs"] + boundary["include"] + boundary["exclude"]
        )
        absent = resolution["notInWorkspace"]
        if resolution["basis"].startswith("unavailable"):
            lines.append(
                f"- name check: NOT RUN ({resolution['basis']}) — no name in this rule was verified"
            )
        elif absent:
            lines.append("- name check: the following are NOT in this workspace's force-app source:")
            for name in absent:
                closest = resolution["names"][name]["closest"]
                lines.append(
                    f"    - `{name}`"
                    + (f" — did you mean {', '.join(f'`{item}`' for item in closest)}?" if closest
                       else " (no near match; expected for a standard or packaged object)")
                )
        else:
            lines.append("- name check: every name in this rule resolves to force-app source")
        lines += ["", "### Attested body (exactly what approval covers)", "", body.strip(), ""]
    REVIEW_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    artifact = REVIEW_ARTIFACT_ROOT / f"{chunk_id}-feature-review.md"
    atomic_write(artifact, "\n".join(lines) + "\n")
    command = "python scripts/knowledge_store.py feature-approve " + " ".join(
        f"--feature {identity}:{digest}" for identity, _f, _b, digest in resolved
    )
    return {
        "outcome": "REVIEW_READY",
        "chunkId": chunk_id,
        "reviewArtifact": relative_path(artifact),
        "features": [identity for identity, _f, _b, _d in resolved],
        "approveCommand": command,
        "skipped": skipped,
    }


def approval_membership_digest(boundary: dict[str, Any]) -> dict[str, Any]:
    """The digest of the membership this rule produces right now, and what qualifies it.

    §6 lets the approval record pin a `membershipDigest` and nothing more — a digest is not a
    member list and cannot re-approve on drift, which is the whole reason the identity list
    lives in the disposable `.cache/` instead. Without this pin `feature-drift` could only ever
    answer "unknown", which is what shipped.

    The digest is None rather than an exception when no index is reachable: §6 requires
    feature-approve to succeed with a stale or absent index, because a governed human approval
    must not be blocked by a disposable cache. Null is legible downstream — `feature-drift`
    reports `changed: "unknown"` with the reason and never `false`.

    Truncation is carried out with it (§6 correction 3). The traversal is deterministic, so a
    digest over a truncated prefix is a real answer — but only if it is named as one at the
    moment it is pinned, rather than discovered later by whoever compares against it.

    The parameters are the BASELINE's, not a caller's: a digest is only comparable with one
    recomputed the same way, so the incoming traversal, the drift depth limit, the default
    established lane and the rule's own assurance floor are fixed here to match what
    `feature-drift` recomputes."""

    try:  # local import: the index reader, and knowledge_search imports this module
        from scripts import knowledge_search
    except ModuleNotFoundError:  # invoked as `python scripts/knowledge_store.py`
        import knowledge_search  # type: ignore
    try:
        documents, _manifest = knowledge_search.load_index()
        membership = knowledge_search.compute_membership(
            documents,
            boundary,
            allowed=documents.lane_ids(knowledge_search.ESTABLISHED_STATES),
            include_heuristic=False,
            direction=knowledge_search.BASELINE_DIRECTION,
            depth_limit=knowledge_search.DEPTH_LIMITS["drift"],
        )
    except knowledge_search.SearchError as error:
        return {"membershipDigest": None, "unreachable": str(error), "limitsHit": [], "laneExcludedCount": 0}
    return {
        "membershipDigest": membership["membershipDigest"],
        "unreachable": None,
        "limitsHit": membership["limitsHit"],
        "laneExcludedCount": membership["laneExcluded"]["count"],
    }


def command_feature_approve(args: argparse.Namespace) -> dict[str, Any]:
    assert_no_reparse_points(FEATURES_ROOT)
    pins: dict[str, str] = {}
    for raw in args.feature or []:
        identity, _, digest = raw.rpartition(":sha256:")
        if not identity or not digest:
            raise StoreError(f"malformed pin {raw!r}; expected Feature:<slug>:sha256:<digest>")
        pins[identity] = f"sha256:{digest}"
    if not pins:
        raise StoreError("at least one --feature Feature:<slug>:sha256:<digest> pin is required")
    reviewer = reviewer_identity()
    latest = ledger_latest(read_ledger(FEATURE_LEDGER_PATH))
    resolved = []
    for identity, pinned in sorted(pins.items()):
        slug = identity.split(":", 1)[1] if identity.startswith("Feature:") else ""
        path = feature_path(slug)
        if not path.is_file():
            raise StoreError(f"{identity}: no such feature")
        lane = compute_feature_lane(path, latest)
        if lane["problems"]:
            raise StoreError(f"{identity}: not approvable — {'; '.join(lane['problems'])}")
        if lane["reviewedContentDigest"] != pinned:
            raise StoreError(
                f"{identity}: pinned digest does not match current content — re-render the review "
                "rather than retrying with a fresh digest"
            )
        resolved.append((identity, path, lane))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    chunk_id = canonical_digest(sorted(pins.items()))[7:19]
    records = []
    unpinned: list[str] = []
    truncated: list[str] = []
    lane_dropped: list[str] = []
    for identity, path, lane in resolved:
        frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
        membership = approval_membership_digest(frontmatter["boundary"])
        membership_digest = membership["membershipDigest"]
        if membership["unreachable"]:
            unpinned.append(f"{identity}: {membership['unreachable']}")
        elif membership["limitsHit"]:
            truncated.append(f"{identity}: {', '.join(membership['limitsHit'])}")
        if membership["laneExcludedCount"]:
            lane_dropped.append(f"{identity}: {membership['laneExcludedCount']} artifact(s)")
        frontmatter["lifecycle"] = {"state": "approved", "contentDigest": lane["reviewedContentDigest"]}
        frontmatter["approval"] = {
            "reviewedContentDigest": lane["reviewedContentDigest"],
            "reviewedBy": reviewer, "reviewedAt": now,
            "mechanism": "copilot-chat-entry-confirmation",
        }
        atomic_write(path, render_entry(frontmatter, body))
        records.append({
            "action": "approve", "identity": identity,
            "reviewedContentDigest": lane["reviewedContentDigest"],
            "boundaryDigest": lane["boundaryDigest"],
            "semanticsDigest": semantics_digest(body),
            # A digest, never a list: it says WHETHER membership moved, and cannot re-approve
            # the artifacts it summarises. The list `feature-drift` needs to say WHICH moved is
            # written to `.cache/` by `tree`. Null when no index was reachable at approval time.
            "membershipDigest": membership_digest,
            "reviewedBy": reviewer, "reviewedAt": now,
            "mechanism": "copilot-chat-entry-confirmation", "chunkId": chunk_id,
        })
    append_ledger(records, FEATURE_LEDGER_PATH)
    result = {
        "outcome": "APPROVED", "chunkId": chunk_id,
        "approved": [record["identity"] for record in records], "reviewedBy": reviewer,
        "note": "the ledger records the boundary and membership digests, never a member list",
    }
    gaps: list[str] = []
    if unpinned:
        # Approval is not blocked by a missing cache, but the consequence has to be visible at
        # the moment it is incurred rather than discovered later as a `changed: "unknown"`.
        gaps.append(
            "No membershipDigest could be pinned for " + "; ".join(unpinned)
            + ". `feature-drift` will answer changed: \"unknown\" — never false — until the "
            "feature is re-approved against a reachable index (`knowledge_search.py build`)."
        )
    if truncated:
        gaps.append(
            "The membership traversal hit its limits for " + "; ".join(truncated)
            + ", so the pinned digest covers a deterministic PREFIX of the membership rather "
            "than all of it, and `feature-drift` will answer "
            "`changedWithinTruncatedPrefix` instead of `changed`."
        )
    if lane_dropped:
        gaps.append(
            "The lifecycle lane filter removed reached artifact(s) from the membership the "
            "pinned digest covers — " + "; ".join(lane_dropped)
            + ". The digest is honest for the established lanes; it simply does not include "
            "them. `tree --feature <slug>` names them under `laneExcluded`."
        )
    if gaps:
        result["gaps"] = gaps
    return result


def command_feature_revoke(args: argparse.Namespace) -> dict[str, Any]:
    assert_no_reparse_points(FEATURES_ROOT)
    identity = feature_identity(args.slug)
    latest = ledger_latest(read_ledger(FEATURE_LEDGER_PATH))
    if identity not in latest or latest[identity].get("action") == "revoke":
        raise StoreError(f"{identity}: nothing to revoke")
    reviewer = reviewer_identity()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    append_ledger([{
        "action": "revoke", "identity": identity, "rationale": args.rationale,
        "reviewedBy": reviewer, "reviewedAt": now,
        "mechanism": "copilot-chat-entry-confirmation",
    }], FEATURE_LEDGER_PATH)
    return {"outcome": "REVOKED", "identity": identity, "rationale": args.rationale}


def command_feature_check(args: argparse.Namespace) -> dict[str, Any]:
    """CI integrity gate over the feature corpus and its ledger."""

    assert_no_reparse_points(FEATURES_ROOT)
    records = read_ledger(FEATURE_LEDGER_PATH)
    latest = ledger_latest(records)
    problems: list[str] = []
    seen: dict[str, str] = {}
    for path in all_feature_paths():
        lane = compute_feature_lane(path, latest)
        problems.extend(f"{lane['path']}: {problem}" for problem in lane["problems"])
        if lane["identity"] in seen:
            problems.append(f"identity {lane['identity']} resolves to two files")
        seen[lane["identity"]] = lane["path"]
    for identity in latest:
        if identity not in seen:
            problems.append(f"ledger approves {identity} but no feature file round-trips to it")
    if problems:
        raise StoreError("feature-check failed:\n- " + "\n- ".join(problems))
    return {"outcome": "PASS", "features": len(seen), "ledgerRecords": len(records)}


if __name__ == "__main__":
    raise SystemExit(main())
