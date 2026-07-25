"""Knowledge Entry search (T08b): typed retrieval over one-file Knowledge Entries.

Implements the retrieval design frozen in docs/knowledge-one-file-contract.md and
docs/evidence-to-analyse.md §25: scope and trust are applied BEFORE ranking, results are
compact projections that always explain themselves, and the generated index is a
disposable cache — never a second source of truth.

Storage: `.cache/knowledge-search/gen-<digest>/` immutable generations plus a small
atomic `current.json` pointer. The cache is git-ignored, never approved, never citable;
every hit cites the canonical entry path with its digests.

Freshness is fail-closed: if the committed entry set no longer matches the generation the
pointer names, queries refuse with INDEX STALE rather than answering from a stale index.

Ranking never overrides authority: lifecycle lane, namespace/package scope, metadata type,
and typed facets are hard filters; BM25F only orders what survives them. Draft entries are
returned in a separate lane and never interleave with approved results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from scripts import knowledge_store as store
    from scripts import relation_kinds
    from scripts.text_analysis import ANALYZER_VERSION, analyze, fold_diacritics
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_search.py`
    import knowledge_store as store  # type: ignore
    import relation_kinds  # type: ignore
    from text_analysis import ANALYZER_VERSION, analyze, fold_diacritics  # type: ignore

INDEX_SCHEMA_VERSION = 1
POLICY_VERSION = "1.0.0"

# BM25F field weights (docs/evidence-to-analyse.md §25.8.3). Values are a starting point to
# be tuned on the golden set; identity and intentional-error text outrank everything else.
FIELD_WEIGHTS = {
    "identity": 6.0,
    "intentionalError": 6.0,
    "keyword": 3.0,
    "label": 3.0,
    "purpose": 2.0,
    "attribute": 1.5,
    "relationTarget": 1.0,
    "sourcePath": 0.2,
}
LEXICAL_CANDIDATE_CAP = 2000
# One vocabulary, per-command values. A single shared depth cannot serve both: reverse impact
# saturates fast, while a feature tree needs trigger -> handler -> queueable -> event.
DEPTH_LIMITS = {"impact": 2, "context": 1, "tree": 4, "drift": 4}
TRAVERSAL_LIMITS = {"maxNodes": 2000, "maxFanout": 500}
IMPACT_TOP_DEFAULT = 50
# The relation kind that carries composition. Named once so `parts` and the tree agree.
CONTAINMENT_KIND = "belongs-to"
BM25_K1 = 1.2
BM25_B = 0.75

ESTABLISHED_STATES = ("approved-current",)
ALL_LANES = (
    "approved-current",
    "approved-drifted",
    "draft",
    "revoked",
    "scope-mismatch",
    "unsupported-profile",
    "not-effective",
)

GLOBAL_FACETS = {
    "metadataType": "string",
    "fullName": "string",
    "namespace": "string",
    "packageVersionId": "string",
    "sourceApiVersion": "string",
    "sourcePath": "string",
    "profile.id": "string",
    "profile.version": "string",
    "effectiveState": "string",
    "extractionCoverage.typeFacts": "string",
}
PROFILE_FACETS = {
    "Flow": {
        "flow.processType": "string",
        "flow.status": "string",
        "flow.trigger.object": "string",
        "flow.trigger.type": "string",
        "flow.recordTriggerType": "string",
        "flow.hasIntentionalCustomError": "boolean",
        "flow.intentionalError.placement": "string",
        "flow.intentionalError.field": "string",
        "flow.intentionalError.usesLabel": "boolean",
    },
    "ApexClass": {
        "apex.kind": "string",
        "apex.sharing": "string",
        "apex.isTest": "boolean",
        "apex.apiVersion": "string",
        "apex.status": "string",
        "apex.superclass": "string",
        "apex.interfaces": "string",
        "apex.annotations": "string",
    },
    "ApexTrigger": {
        "apex.kind": "string",
        "apex.isTest": "boolean",
        "apex.apiVersion": "string",
        "trigger.object": "string",
        "trigger.events": "string",
    },
    "ValidationRule": {
        "validationRule.object": "string",
        "validationRule.active": "boolean",
        "validationRule.errorDisplayField": "string",
    },
    "PermissionSet": {
        "permissionSet.label": "string",
        "permissionSet.license": "string",
        "permissionSet.systemPermissions": "string",
        "permissionSet.objectPermissionCount": "number",
        "permissionSet.fieldPermissionCount": "number",
        "permissionSet.referencesTruncated": "boolean",
        "permissionSet.truncatedFamilies": "string",
    },
    "CustomObject": {
        "object.kind": "string",
        "object.sharingModel": "string",
        "object.deploymentStatus": "string",
        "object.eventType": "string",
        "object.customSettingsType": "string",
    },
    "RecordType": {
        "recordType.object": "string",
        "recordType.active": "boolean",
    },
    "CustomMetadata": {
        "customMetadata.type": "string",
        "customMetadata.protected": "boolean",
    },
    "LightningComponentBundle": {
        "lwc.isExposed": "boolean",
        "lwc.targets": "string",
    },
    "CustomField": {
        "field.object": "string",
        "field.type": "string",
        "field.required": "boolean",
        "field.unique": "boolean",
        "field.externalId": "boolean",
        "field.encrypted": "boolean",
        "field.referenceTo": "string",
        "field.controllingField": "string",
        "field.length": "number",
        "field.precision": "number",
        "field.scale": "number",
    },
}
FACET_OPERATORS = ("eq", "in", "exists", "prefix", "has", "gte", "lte")


class SearchError(RuntimeError):
    """Fail-closed search error; the message names the actionable reason."""


def cache_root() -> Path:
    return store.ROOT / ".cache/knowledge-search"


# --- analyzer (Unicode + Salesforce identifiers) ---------------------------------------

# Merge fields collapse to a single visible sentinel so two messages that differ only in
# their runtime variables share a fingerprint, while a message with no variable at all
# stays distinct. U+FFFC (OBJECT REPLACEMENT CHARACTER) can never occur in Flow source.
MERGE_PLACEHOLDER = "\ufffc"


def message_fingerprint(message: str) -> str:
    """Sanitized shape of an intentional error message.

    Merge fields collapse to a placeholder; literal constants (`20%`, thresholds) are kept
    because they are part of the author's intent, not runtime data.
    """
    text = unicodedata.normalize("NFKC", message)
    text = re.sub(r"\{![^}]*\}", MERGE_PLACEHOLDER, text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


# --- projections ------------------------------------------------------------------------


def _flow_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    trigger = facts.get("trigger", {}) or {}
    errors = front.get("intentionalErrors", []) or []
    facets: dict[str, Any] = {
        "flow.processType": facts.get("processType"),
        "flow.status": facts.get("status"),
        "flow.trigger.object": trigger.get("object"),
        "flow.trigger.type": trigger.get("type"),
        "flow.recordTriggerType": trigger.get("recordTriggerType"),
        "flow.hasIntentionalCustomError": bool(errors),
    }
    if errors:
        facets["flow.intentionalError.placement"] = sorted(
            {error.get("presentation", {}).get("mode") for error in errors if error.get("presentation")}
        )
        fields = sorted({e["presentation"].get("field") for e in errors if e.get("presentation", {}).get("field")})
        if fields:
            facets["flow.intentionalError.field"] = fields
        facets["flow.intentionalError.usesLabel"] = any(error.get("customLabelRefs") for error in errors)
    return facets


def _custom_field_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    reference_to = facts.get("referenceTo")
    if isinstance(reference_to, str):
        reference_to = [reference_to]
    return {
        "field.object": facts.get("object"),
        "field.type": facts.get("type"),
        "field.required": facts.get("required"),
        "field.unique": facts.get("unique"),
        "field.externalId": facts.get("externalId"),
        "field.encrypted": facts.get("encrypted"),
        "field.referenceTo": reference_to,
        "field.controllingField": facts.get("controllingField"),
        "field.length": facts.get("length"),
        "field.precision": facts.get("precision"),
        "field.scale": facts.get("scale"),
    }



def _apex_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "apex.kind": facts.get("kind"),
        "apex.sharing": facts.get("sharing"),
        "apex.isTest": facts.get("isTest"),
        "apex.apiVersion": facts.get("apiVersion"),
        "apex.status": facts.get("status"),
        "apex.superclass": facts.get("superclass"),
        "apex.interfaces": facts.get("interfaces"),
        "apex.annotations": facts.get("annotations"),
        "trigger.object": facts.get("triggerObject"),
        "trigger.events": facts.get("triggerEvents"),
    }


def _validation_rule_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "validationRule.object": facts.get("object"),
        "validationRule.active": facts.get("active"),
        "validationRule.errorDisplayField": facts.get("errorDisplayField"),
    }


def _permission_set_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "permissionSet.label": facts.get("label"),
        "permissionSet.license": facts.get("license"),
        "permissionSet.systemPermissions": facts.get("systemPermissions"),
        "permissionSet.objectPermissionCount": facts.get("objectPermissionCount"),
        "permissionSet.fieldPermissionCount": facts.get("fieldPermissionCount"),
        "permissionSet.referencesTruncated": facts.get("referencesTruncated"),
        "permissionSet.truncatedFamilies": facts.get("truncatedFamilies"),
    }



def _custom_object_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "object.kind": facts.get("objectKind"),
        "object.sharingModel": facts.get("sharingModel"),
        "object.deploymentStatus": facts.get("deploymentStatus"),
        "object.eventType": facts.get("eventType"),
        "object.customSettingsType": facts.get("customSettingsType"),
    }


def _record_type_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"recordType.object": facts.get("object"), "recordType.active": facts.get("active")}


def _custom_metadata_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"customMetadata.type": facts.get("type"), "customMetadata.protected": facts.get("protected")}


def _lwc_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"lwc.isExposed": facts.get("isExposed"), "lwc.targets": facts.get("targets")}


PROFILE_PROJECTORS = {
    "Flow": _flow_facets,
    "CustomField": _custom_field_facets,
    "ApexClass": _apex_facets,
    "ApexTrigger": _apex_facets,
    "ValidationRule": _validation_rule_facets,
    "PermissionSet": _permission_set_facets,
    "CustomObject": _custom_object_facets,
    "RecordType": _record_type_facets,
    "CustomMetadata": _custom_metadata_facets,
    "LightningComponentBundle": _lwc_facets,
}


def project_entry(path: Path, lane: dict[str, Any]) -> dict[str, Any]:
    """Compact, index-ready projection of one canonical entry. Never the authority."""
    front, body = store.split_entry(path.read_text(encoding="utf-8"))
    subject = front["subject"]
    identity = lane["identity"]
    facts = front.get("typeFacts", {})
    purpose = "\n".join(
        line for line in body.splitlines() if line.strip() and not line.startswith("## ")
    )
    facets: dict[str, Any] = {
        "metadataType": subject["metadataType"],
        "fullName": subject["fullName"],
        "namespace": subject.get("namespace"),
        "packageVersionId": front["scope"].get("packageVersionId"),
        "sourceApiVersion": front["scope"].get("sourceApiVersion"),
        "sourcePath": front["source"]["fragments"][0]["path"],
        "profile.id": front["profile"]["id"],
        "profile.version": front["profile"]["version"],
        "effectiveState": lane["lane"],
        "extractionCoverage.typeFacts": front.get("extractionCoverage", {}).get("typeFacts"),
    }
    projector = PROFILE_PROJECTORS.get(subject["metadataType"])
    if projector:
        facets.update({k: v for k, v in projector(front).items() if v is not None})

    edges = []
    for reference in facts.get("references", []) or []:
        edges.append(
            {
                "kind": reference["kind"],
                "target": reference["target"],
                "assurance": reference.get("assurance", "source-derived-heuristic"),
            }
        )

    errors = []
    for error in front.get("intentionalErrors", []) or []:
        message = error.get("messageTemplate", "")
        errors.append(
            {
                "elementApiName": error.get("elementApiName"),
                "elementLabel": error.get("elementLabel"),
                "messageTemplate": message,
                "resolvedDefaultText": error.get("resolvedDefaultText"),
                "fingerprint": message_fingerprint(message),
                "resolvedFingerprint": (
                    message_fingerprint(error["resolvedDefaultText"])
                    if error.get("resolvedDefaultText")
                    else None
                ),
                "presentation": error.get("presentation", {}),
                "reachability": error.get("reachability", {}),
                "limitations": error.get("limitations", []),
            }
        )

    fields: dict[str, list[str]] = {
        "identity": analyze(identity) + analyze(subject["fullName"]),
        "label": analyze(str(facts.get("label") or "")),
        "keyword": [token for kw in front.get("keywords", []) for token in analyze(kw)],
        "purpose": analyze(purpose),
        "attribute": [
            token
            for key, value in facets.items()
            if isinstance(value, str) and key not in {"sourcePath", "effectiveState"}
            for token in analyze(value)
        ],
        "relationTarget": [token for edge in edges for token in analyze(edge["target"])],
        "sourcePath": analyze(facets["sourcePath"]),
        "intentionalError": [
            token
            for error in errors
            for token in analyze(error["messageTemplate"] or "")
            + analyze(error.get("resolvedDefaultText") or "")
            + analyze(error.get("elementApiName") or "")
        ],
    }
    return {
        "identity": identity,
        "path": lane["path"],
        "lane": lane["lane"],
        "assurance": front.get("assurance", {}),
        "coverage": front.get("extractionCoverage", {}),
        "limitations": front.get("limitations", []),
        "candidateKeywords": front.get("candidateKeywords", []),
        "facets": facets,
        "edges": edges,
        "intentionalErrors": errors,
        "fields": fields,
        "citation": {
            "path": lane["path"],
            "entryDigest": lane.get("reviewedContentDigest"),
            "factsDigest": lane.get("factsDigest"),
            "sourceDigest": lane.get("sourceTreeDigest"),
            "profileDigest": front["profile"]["digest"],
        },
    }


# --- index build --------------------------------------------------------------------------


_CODE_FINGERPRINT: str | None = None


def code_fingerprint() -> str:
    """Digest of the code that produces projections and lanes.

    Reuse and freshness were keyed on the data alone. Editing the lane logic therefore left
    the previous generation entirely reusable — no entry file had moved, so every projection
    was reused — and queries went on serving fields the current code would never produce.
    Observed: draft entries kept the null citation digest written before the fix, so hydration
    dropped every relation hit as "entry changed since the index was built" while the entries
    were in fact untouched. A stat stamp cannot see a code change, so the code is part of the
    key: edit the projector and the previous generation is discarded automatically.

    relation_kinds is in the tuple even though nothing here derives assurance from it: the
    vocabulary decides what an entry ASSERTS, so moving a kind into HEURISTIC_REF_KINDS changes
    stored edges. Without it in the key, that edit would change no fingerprinted byte and every
    cached projection would be reused as fresh — serving the old `source-exact` marker."""

    global _CODE_FINGERPRINT
    if _CODE_FINGERPRINT is None:
        parts = []
        for module in (sys.modules[__name__], store, relation_kinds, sys.modules[analyze.__module__]):
            path = Path(getattr(module, "__file__", "") or "")
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
            parts.append((path.name, digest))
        _CODE_FINGERPRINT = store.canonical_digest(sorted(parts))
    return _CODE_FINGERPRINT


def corpus_fingerprint() -> str:
    """Coarse freshness signal: entry count, newest stamp, ledger stamp, analyzer, code.

    Recomputing the full projection per query re-parsed the whole corpus (~1s at 200 entries),
    so this replaced it with a per-file stat sweep — which was still linear: 11.6 µs per entry
    measured, i.e. ~174 ms of pure staleness-checking on every CLI call at 15k entries, before
    any query work, and materially worse on the team's NTFS + Defender path.

    Aggregating to (count, newest stamp) keeps the same guarantee at a fraction of the cost.
    Correctness never rested on this signal anyway: it decides only whether to TRUST the cache,
    and every result actually served is re-read and digest-checked in hydrate(). The narrow case
    it cannot see — two edits that cancel out in both count and newest mtime — is exactly the
    case hydration catches before anything leaves the process.
    """
    # os.scandir, not rglob+stat: the directory read already carries the metadata, so this is
    # one syscall per file instead of two. Measured 11.6 -> 3.4 µs per entry.
    newest = 0
    count = 0
    stack = [str(store.ARTIFACTS_ROOT)] if store.ARTIFACTS_ROOT.is_dir() else []
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.name.endswith(".md"):
                    stat = entry.stat(follow_symlinks=False)
                    count += 1
                    newest = max(newest, stat.st_mtime_ns, stat.st_size)
    ledger = store.LEDGER_PATH
    ledger_stat = (ledger.stat().st_size, ledger.stat().st_mtime_ns) if ledger.is_file() else (0, 0)
    return store.canonical_digest(
        {
            "entries": [count, newest],
            "ledger": ledger_stat,
            "analyzer": ANALYZER_VERSION,
            "code": code_fingerprint(),
        }
    )


def fold_target(target: str) -> str:
    """Posting key for an edge target. Folded like facet keys are folded on write."""
    return unicodedata.normalize("NFKC", target).casefold()


def build_relation_index(projections: list[dict[str, Any]]) -> dict[str, Any]:
    """Who points at each target, and what that target resolves to.

    The old posting was `target -> [identity]`: it answered "does anything reference this" and
    nothing else. The kind and the assurance — the two things that decide whether an edge may be
    shown by default and what it means — had to be recovered by re-reading every source document,
    which is why `explain` and `impact` scanned the whole corpus.

    Resolution is computed here, once, rather than stored in entries: an entry may not assert
    that its target exists, because that depends on another artifact. An unresolvable target is
    kept and labelled, never dropped — "this points somewhere I have no entry for" is a finding,
    and silently discarding it would make a partial graph look complete.
    """

    by_full_name: dict[str, list[str]] = defaultdict(list)
    identities = set()
    for item in projections:
        identities.add(item["identity"])
        full_name = item["facets"].get("fullName")
        if full_name:
            by_full_name[fold_target(str(full_name))].append(item["identity"])

    by_target: dict[str, dict[str, Any]] = {}
    for item in projections:
        for edge in item["edges"]:
            key = fold_target(edge["target"])
            row = by_target.setdefault(
                key, {"spellings": set(), "incoming": [], "targetIdentity": None, "resolution": "no-entry"}
            )
            row["spellings"].add(edge["target"])
            row["incoming"].append([item["identity"], edge["kind"], edge["assurance"]])

    for key, row in by_target.items():
        candidates = by_full_name.get(key, [])
        if not candidates and key in {fold_target(name) for name in identities}:
            candidates = [name for name in identities if fold_target(name) == key]
        if len(candidates) == 1:
            row["targetIdentity"] = candidates[0]
            row["resolution"] = "resolved"
        elif len(candidates) > 1:
            # Namespace twins. Guessing one would silently pick a package's artifact over the
            # subscriber's; the caller is told instead.
            row["resolution"] = "ambiguous"
            row["candidates"] = sorted(candidates)
        row["spellings"] = sorted(row["spellings"])
        row["incoming"] = sorted(row["incoming"])

    # Sources whose own edge list was capped by the collector. The entry records this locally
    # (typeFacts.referencesTruncated / truncatedFamilies) but nothing read it at query time, so
    # "which permission sets grant edit on this field?" returned a complete-looking list that
    # systematically omitted every PermissionSet with more than ~300 grants — and the collector
    # discards fieldPermissions FIRST, so the security question failed closed the wrong way.
    truncated: dict[str, list[str]] = {}
    for item in projections:
        families = item["facets"].get("permissionSet.truncatedFamilies")
        if item["facets"].get("permissionSet.referencesTruncated"):
            for family in (families or ["unspecified"]):
                truncated.setdefault(str(family), []).append(item["identity"])

    return {
        "byTarget": by_target,
        "byFullName": {name: sorted(ids) for name, ids in by_full_name.items()},
        "truncatedSources": {family: sorted(ids) for family, ids in truncated.items()},
    }


def entry_set_digest(projections: list[dict[str, Any]]) -> str:
    payload = sorted(
        (item["identity"], item["path"], item["lane"], item["citation"]["entryDigest"] or "")
        for item in projections
    )
    return store.canonical_digest(
        {
            "entries": payload,
            "analyzer": ANALYZER_VERSION,
            "schema": INDEX_SCHEMA_VERSION,
            "policy": POLICY_VERSION,
            "code": code_fingerprint(),
        }
    )


def _stamp_of(path: Path) -> list[Any]:
    try:
        stat = path.stat()
    except OSError:
        return [path.name, None, None]
    return [path.name, stat.st_size, stat.st_mtime_ns]


def projection_dependencies(path: Path, fragments: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything a projection's content AND lane depend on.

    The lane is not a function of the entry file alone: source drift moves it to
    approved-drifted and a ledger append can approve or revoke it. Keying reuse on the entry
    file alone silently served a stale lane (caught by the drifted-lane golden query), so the
    key covers the entry, every source fragment, and the ledger."""

    ledger = store.LEDGER_PATH
    return {
        "entry": _stamp_of(path),
        "sources": sorted(_stamp_of(store.ROOT / fragment["path"]) for fragment in fragments),
        "ledger": _stamp_of(ledger) if ledger.is_file() else None,
    }


def load_previous_projections() -> dict[str, dict[str, Any]]:
    """Projections from the current generation, keyed by path+stamp for reuse."""
    root = cache_root()
    pointer = root / "current.json"
    if not pointer.is_file():
        return {}
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
        documents_path = root / current.get("directory", "") / "documents.jsonl"
        manifest = json.loads((root / current["directory"] / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}
    if manifest.get("analyzerVersion") != ANALYZER_VERSION or manifest.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        return {}  # a projection built by a different analyzer may not be reused
    if manifest.get("codeFingerprint") != code_fingerprint():
        return {}  # projections built by different projector/lane code may not be reused
    reusable: dict[str, dict[str, Any]] = {}
    try:
        for line in documents_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            document = json.loads(line)
            if document.get("_deps"):
                reusable[document["path"]] = document
    except (OSError, ValueError):
        return {}
    return reusable


def collect_projections(reuse: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project every entry, reusing unchanged ones from the previous generation.

    A full projection costs ~5 ms per entry (measured), so rebuilding 15k entries after a
    single approval would take over a minute. Reuse is keyed on the entry's path plus its
    size/mtime stamp and is only ever a cache: anything whose stamp moved is re-projected,
    and a changed analyzer version discards the whole previous generation."""

    reuse = reuse if reuse is not None else {}
    latest = store.ledger_latest(store.read_ledger())
    projections: list[dict[str, Any]] = []
    stats = {"reused": 0, "projected": 0}
    for path in store.all_entry_paths():
        relative = path.relative_to(store.ROOT).as_posix()
        cached = reuse.get(relative)
        if cached is not None:
            fragments = cached.get("_deps", {}).get("sourcePaths") or []
            expected = projection_dependencies(path, [{"path": item} for item in fragments])
            if cached["_deps"].get("stamps") == expected:
                projections.append(cached)
                stats["reused"] += 1
                continue
        lane = store.compute_lane(path, latest)
        document = project_entry(path, lane)
        front, _ = store.split_entry(path.read_text(encoding="utf-8"))
        fragment_paths = [fragment["path"] for fragment in front["source"]["fragments"]]
        document["_deps"] = {
            "sourcePaths": fragment_paths,
            "stamps": projection_dependencies(path, front["source"]["fragments"]),
        }
        projections.append(document)
        stats["projected"] += 1
    return sorted(projections, key=lambda item: item["identity"]), stats


def build_index(check: bool = False, full: bool = False) -> dict[str, Any]:
    projections, stats = collect_projections({} if full else load_previous_projections())
    generation = entry_set_digest(projections)
    root = cache_root()
    pointer = root / "current.json"
    if check:
        if not pointer.is_file():
            raise SearchError("INDEX STALE / REBUILD REQUIRED: no generation pointer")
        current = json.loads(pointer.read_text(encoding="utf-8"))
        if current.get("generation") != generation:
            raise SearchError("INDEX STALE / REBUILD REQUIRED: entry set changed since the last build")
        return {"outcome": "PASS", "generation": generation, "entries": len(projections)}

    generation_dir = root / f"gen-{generation[7:23]}"
    generation_dir.mkdir(parents=True, exist_ok=True)
    documents = generation_dir / "documents.jsonl"
    offsets: dict[str, list[int]] = {}
    lanes: dict[str, list[str]] = defaultdict(list)
    facet_postings: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    token_postings: dict[str, list[str]] = defaultdict(list)
    relation_postings: dict[str, list[str]] = defaultdict(list)
    document_frequency: dict[str, int] = defaultdict(int)
    field_length_totals: dict[str, list[int]] = defaultdict(list)
    position = 0
    with documents.open("w", encoding="utf-8", newline="\n") as handle:
        for item in projections:
            line = json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n"
            encoded = line.encode("utf-8")
            offsets[item["identity"]] = [position, len(encoded)]
            position += len(encoded)
            handle.write(line)
            lanes[item["lane"]].append(item["identity"])
            for key, value in item["facets"].items():
                values = value if isinstance(value, list) else [value]
                for entry in values:
                    if entry is None:
                        continue
                    facet_postings[key][str(entry).casefold()].append(item["identity"])
            for edge in item["edges"]:
                relation_postings[edge["target"]].append(item["identity"])
                relation_postings[fold_target(edge["target"])].append(item["identity"])
            seen_tokens = {token for field in item["fields"].values() for token in field}
            for token in seen_tokens:
                token_postings[token].append(item["identity"])
                document_frequency[token] += 1
            for field, tokens in item["fields"].items():
                field_length_totals[field].append(len(tokens))
    postings = {
        "offsets": offsets,
        "lanes": {lane: sorted(ids) for lane, ids in lanes.items()},
        "facets": {
            key: {value: sorted(ids) for value, ids in values.items()}
            for key, values in facet_postings.items()
        },
        "tokens": {token: sorted(ids) for token, ids in token_postings.items()},
        "relations": {target: sorted(set(ids)) for target, ids in relation_postings.items()},
        "reverse": build_relation_index(projections),
        "documentFrequency": dict(document_frequency),
        "averageFieldLength": {
            field: (sum(lengths) / len(lengths)) if lengths else 1.0
            for field, lengths in field_length_totals.items()
        },
        "documentCount": len(projections),
    }
    for name, payload in (
        ("offsets", postings["offsets"]),
        ("lanes", postings["lanes"]),
        ("facets", postings["facets"]),
        ("relations", postings["relations"]),
        ("reverse", postings["reverse"]),
        ("tokens", postings["tokens"]),
        ("stats", {
            "documentFrequency": postings["documentFrequency"],
            "averageFieldLength": postings["averageFieldLength"],
            "documentCount": postings["documentCount"],
        }),
    ):
        with (generation_dir / f"{name}.json").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    manifest = {
        "kind": "knowledge-search-manifest",
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "analyzerVersion": ANALYZER_VERSION,
        "policyVersion": POLICY_VERSION,
        "generation": generation,
        "entryCount": len(projections),
        "laneCounts": {
            lane: sum(1 for item in projections if item["lane"] == lane) for lane in ALL_LANES
        },
        "metadataTypeCounts": {
            metadata_type: sum(
                1 for item in projections if item["facets"]["metadataType"] == metadata_type
            )
            for metadata_type in sorted({item["facets"]["metadataType"] for item in projections})
        },
        "corpusFingerprint": corpus_fingerprint(),
        "codeFingerprint": code_fingerprint(),
        "documentsDigest": store.canonical_digest(documents.read_text(encoding="utf-8")),
        "complete": True,
    }
    with (generation_dir / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temp_pointer = root / "current.json.tmp"
    with temp_pointer.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {"generation": generation, "directory": generation_dir.name}, indent=2, sort_keys=True
            )
            + "\n"
        )
    temp_pointer.replace(pointer)
    for stale in root.glob("gen-*"):
        if stale.is_dir() and stale.name != generation_dir.name:
            shutil.rmtree(stale, ignore_errors=True)
    return {
        "outcome": "BUILT",
        "generation": generation,
        "entries": len(projections),
        "reusedProjections": stats["reused"],
        "rebuiltProjections": stats["projected"],
    }


def load_index() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the current generation, refusing to answer from a stale or partial index."""
    root = cache_root()
    pointer = root / "current.json"
    if not pointer.is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: run `knowledge_search.py build`")
    current = json.loads(pointer.read_text(encoding="utf-8"))
    generation_dir = root / current.get("directory", "")
    manifest_path = generation_dir / "manifest.json"
    documents_path = generation_dir / "documents.jsonl"
    if not manifest_path.is_file() or not documents_path.is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: generation is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("complete") or manifest.get("analyzerVersion") != ANALYZER_VERSION:
        raise SearchError("INDEX STALE / REBUILD REQUIRED: incompatible or partial generation")
    if manifest.get("corpusFingerprint") != corpus_fingerprint():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: entries changed since the last build")
    if not (generation_dir / "offsets.json").is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: generation predates the postings index")
    return DocumentStore(documents_path, generation_dir), manifest


class DocumentStore:
    """Random-access reader over one generation.

    Queries resolve a candidate identity set from the postings first and hydrate only those
    documents by byte offset; parsing every line made query latency linear in corpus size,
    which is what broke the p95 budget past ~5 000 entries (review package §8)."""

    def __init__(self, path: Path, generation_dir: Path):
        self.path = path
        self.generation_dir = generation_dir
        self._cache: dict[str, dict[str, Any]] = {}
        self._postings: dict[str, Any] = {}
        self.document_reads = 0
        self.posting_bytes = 0

    def posting_file(self, name: str) -> dict[str, Any]:
        """Load one posting file on first use.

        Token postings dominate the index by volume but are only needed for lexical queries;
        loading them for an identity or facet lookup was pure latency."""
        if name not in self._postings:
            path = self.generation_dir / f"{name}.json"
            self._postings[name] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            # Counted so a query can report how much index it touched. documentReads alone is
            # blind to this: a regression that loaded every posting family per query — token
            # postings reach ~15 MB at 15k entries — would not move that counter at all.
            self.posting_bytes += path.stat().st_size if path.is_file() else 0
        return self._postings[name]

    @property
    def postings(self) -> dict[str, Any]:
        # Compatibility surface for callers that read a specific family.
        return {
            "offsets": self.posting_file("offsets"),
            "facets": self.posting_file("facets"),
            "documentFrequency": self.posting_file("stats").get("documentFrequency", {}),
            "averageFieldLength": self.posting_file("stats").get("averageFieldLength", {}),
        }

    @property
    def count(self) -> int:
        return int(self.posting_file("stats").get("documentCount", 0))

    def identities(self) -> list[str]:
        return sorted(self.posting_file("offsets"))

    def get(self, identity: str) -> dict[str, Any] | None:
        if identity in self._cache:
            return self._cache[identity]
        location = self.posting_file("offsets").get(identity)
        if location is None:
            return None
        offset, length = location
        with self.path.open("rb") as handle:
            handle.seek(offset)
            document = json.loads(handle.read(length).decode("utf-8"))
        self.document_reads += 1
        self._cache[identity] = document
        return document

    def load_many(self, identities: Iterable[str]) -> list[dict[str, Any]]:
        return [document for document in (self.get(identity) for identity in identities) if document]

    def lane_ids(self, lanes: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for lane in lanes:
            result.update(self.posting_file("lanes").get(lane, []))
        return result

    def facet_ids(self, key: str, value: str) -> set[str] | None:
        """Identity set for an exact facet value; None when the operator needs full evaluation."""
        values = self.posting_file("facets").get(key)
        if values is None:
            return set()
        return set(values.get(value.casefold(), []))

    def token_ids(self, token: str) -> set[str]:
        return set(self.posting_file("tokens").get(token, []))

    def relation_ids(self, target: str) -> set[str]:
        return set(self.posting_file("relations").get(target, []))

    def target_row(self, target: str) -> dict[str, Any]:
        """Everything the index knows about one edge target: who points at it, what it is."""
        reverse = self.posting_file("reverse").get("byTarget", {})
        return reverse.get(fold_target(target), {
            "spellings": [], "incoming": [], "targetIdentity": None, "resolution": "no-target"
        })

    def incoming_edges(
        self, target: str, *, kinds: set[str] | None = None, include_heuristic: bool = False
    ) -> list[dict[str, Any]]:
        """Every edge pointing at `target`, one row per edge.

        One row per EDGE, not per source: an entry that both queries and writes the same object
        is two facts about it, and collapsing them to one hid half the answer."""

        rows = []
        for source, kind, assurance in self.target_row(target)["incoming"]:
            if kinds is not None and kind not in kinds:
                continue
            if not include_heuristic and assurance != relation_kinds.SOURCE_EXACT:
                continue
            rows.append({"source": source, "kind": kind, "assurance": assurance})
        return rows

    def identities_for_full_name(self, full_name: str) -> list[str]:
        return list(self.posting_file("reverse").get("byFullName", {}).get(fold_target(full_name), []))


# --- query ----------------------------------------------------------------------------------


def facet_value(document: dict[str, Any], key: str) -> Any:
    return document["facets"].get(key)


def facet_matches(document: dict[str, Any], key: str, operator: str, value: str) -> bool:
    actual = facet_value(document, key)
    if operator == "exists":
        return actual is not None
    if actual is None:
        return False
    if isinstance(actual, bool):
        return operator == "eq" and str(actual).casefold() == value.casefold()
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        try:
            number = float(value)
        except ValueError:
            raise SearchError(f"facet {key} expects a number, got {value!r}")
        return {"eq": actual == number, "gte": actual >= number, "lte": actual <= number}.get(
            operator, False
        )
    if isinstance(actual, list):
        casefolded = [str(item).casefold() for item in actual]
        if operator in {"has", "eq"}:
            return value.casefold() in casefolded
        if operator == "in":
            return bool(set(casefolded) & {part.casefold() for part in value.split("|")})
        if operator == "prefix":
            return any(item.startswith(value.casefold()) for item in casefolded)
        return False
    text = str(actual).casefold()
    if operator == "eq":
        return text == value.casefold()
    if operator == "in":
        return text in {part.casefold() for part in value.split("|")}
    if operator == "prefix":
        return text.startswith(value.casefold())
    if operator == "has":
        return value.casefold() in text
    raise SearchError(f"operator {operator!r} is not valid for facet {key}")


def parse_facet(expression: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_.]*)(?::([a-z]+))?=(.*)", expression)
    if not match:
        raise SearchError(f"--facet must be key[:op]=value, got {expression!r}")
    key, operator, value = match.group(1), match.group(2) or "eq", match.group(3)
    if operator not in FACET_OPERATORS:
        raise SearchError(f"unknown operator {operator!r}; valid: {', '.join(FACET_OPERATORS)}")
    known = set(GLOBAL_FACETS) | {facet for facets in PROFILE_FACETS.values() for facet in facets}
    if key not in known:
        raise SearchError(f"unknown facet {key!r}; run `capabilities` for the valid set")
    return key, operator, value


def bm25f(store_index: "DocumentStore", candidates: list[dict[str, Any]], query_tokens: list[str]) -> dict[str, tuple[float, list[dict[str, Any]]]]:
    """Rank candidates with corpus statistics precomputed at build time.

    Document frequencies and average field lengths come from the postings index, so ranking
    no longer has to read the whole corpus on every query."""

    if not query_tokens:
        return {}
    statistics = store_index.posting_file("stats")
    document_frequency = statistics.get("documentFrequency", {})
    average_length = statistics.get("averageFieldLength", {})
    total = max(store_index.count, 1)
    scored: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    for document in candidates:
        score = 0.0
        matched: list[dict[str, Any]] = []
        for token in set(query_tokens):
            frequency = document_frequency.get(token, 0)
            idf = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            weighted_tf = 0.0
            for field, tokens in document["fields"].items():
                count = tokens.count(token)
                if not count:
                    continue
                length = len(tokens) or 1
                norm = 1 - BM25_B + BM25_B * (length / (average_length.get(field) or 1.0))
                weighted_tf += FIELD_WEIGHTS.get(field, 1.0) * count / norm
                matched.append({"field": field, "match": "lexical", "value": token})
            if weighted_tf:
                score += idf * (weighted_tf * (BM25_K1 + 1)) / (weighted_tf + BM25_K1)
        if score:
            scored[document["identity"]] = (score, matched)
    return scored


def hit_of(document: dict[str, Any], score: float, matched: list[dict[str, Any]], match_class: str) -> dict[str, Any]:
    return {
        "artifactId": document["identity"],
        "metadataType": document["facets"]["metadataType"],
        "fullName": document["facets"]["fullName"],
        "matchClass": match_class,
        "score": round(score, 4),
        "scoreComparableWithinQueryOnly": True,
        "matchedOn": matched[:8],
        "lifecycle": document["lane"],
        "assurance": document["assurance"],
        "scope": {
            "namespace": document["facets"]["namespace"],
            "packageVersionId": document["facets"]["packageVersionId"],
            "sourceApiVersion": document["facets"]["sourceApiVersion"],
        },
        "coverage": document["coverage"],
        "limitations": document["limitations"],
        "citation": document["citation"],
    }


def hydrate(hits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-read and digest-check the canonical entries behind the results we are about to serve.

    Contract §25.6: compact search first, then load and verify the selected entries. This is
    what makes the cheap freshness fingerprint safe — a file that changed without changing its
    stat signature still cannot be served, because its recomputed lane and digest are checked
    here before the hit leaves the process."""

    verified: list[dict[str, Any]] = []
    gaps: list[str] = []
    for hit in hits:
        path = store.ROOT / hit["citation"]["path"]
        if not path.is_file():
            gaps.append(f"{hit['artifactId']}: entry file disappeared since the index was built")
            continue
        # The ledger is already covered by the freshness fingerprint (a ledger append or
        # revocation invalidates the whole generation), so hydration only has to prove the
        # FILE still holds the content the projection was built from — which is exactly the
        # case a stat-based fingerprint could theoretically miss. Re-reading the 15k-line
        # ledger per query was pure overhead.
        try:
            frontmatter, body = store.split_entry(path.read_text(encoding="utf-8"))
            recomputed = store.reviewed_content_digest(frontmatter, body)
        except store.StoreError as error:
            gaps.append(f"{hit['artifactId']}: entry no longer parses ({error})")
            continue
        subject = frontmatter["subject"]
        identity = store.identity_of(
            subject["metadataType"], subject.get("namespace"), subject["fullName"]
        )
        if identity != hit["artifactId"] or recomputed != hit["citation"]["entryDigest"]:
            gaps.append(
                f"{hit['artifactId']}: entry changed since the index was built — rebuild the index"
            )
            continue
        verified.append(hit)
    return verified, gaps


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    documents, manifest = load_index()
    states = list(args.state or ESTABLISHED_STATES)
    facets = [parse_facet(expression) for expression in (args.facet or [])]
    excluded = defaultdict(int)
    interpreted: dict[str, Any] = {
        "mode": args.mode,
        "text": args.text,
        "identity": args.identity,
        "states": states,
        "metadataType": args.metadata_type,
        "namespace": args.namespace,
        "facets": [f"{key}:{operator}={value}" for key, operator, value in facets],
        "relation": (
            {"anchor": args.relation_anchor, "kind": args.relation_kind, "direction": args.direction}
            if args.relation_anchor
            else None
        ),
        "top": args.top,
    }

    # Hard filters resolve to identity sets through the postings index; only the survivors
    # are hydrated. Exact-equality facets narrow via postings, other operators are evaluated
    # on the (already narrowed) candidate documents.
    all_ids = set(documents.identities())
    candidate_ids = documents.lane_ids(states)
    excluded["lifecycle"] = len(all_ids) - len(candidate_ids)
    if args.metadata_type:
        by_type = documents.facet_ids("metadataType", args.metadata_type)
        excluded["metadataType"] = len(candidate_ids - by_type)
        candidate_ids &= by_type
    if args.namespace is not None:
        wanted = "c" if args.namespace == "c" else args.namespace
        by_namespace = (
            documents.facet_ids("namespace", wanted)
            if args.namespace != "c"
            else candidate_ids - set().union(*(
                set(values) for values in documents.posting_file("facets").get("namespace", {}).values()
            ) or [set()])
        )
        excluded["scope"] = len(candidate_ids - by_namespace)
        candidate_ids &= by_namespace
    exact_facets = [item for item in facets if item[1] == "eq"]
    other_facets = [item for item in facets if item[1] != "eq"]
    for key, _operator, value in exact_facets:
        by_facet = documents.facet_ids(key, value)
        excluded["facet"] += len(candidate_ids - by_facet)
        candidate_ids &= by_facet
    lexical_truncated = 0
    if args.text and not other_facets:
        # Seed candidates from the RAREST query token and intersect outwards. A common term
        # ("queue") matches the whole corpus, so a naive union would hydrate everything and
        # put latency back where the postings index was meant to remove it.
        frequency = documents.posting_file("stats").get("documentFrequency", {})
        tokens_by_rarity = sorted(set(analyze(args.text)), key=lambda token: frequency.get(token, 0))
        token_ids: set[str] = set()
        for token in tokens_by_rarity:
            posting = documents.token_ids(token)
            if not posting:
                continue
            token_ids = posting if not token_ids else (token_ids | posting)
            if len(token_ids) >= LEXICAL_CANDIDATE_CAP:
                break
        candidate_ids &= token_ids
        if len(candidate_ids) > LEXICAL_CANDIDATE_CAP:
            # Never silently truncate: the cap is reported alongside the results.
            rarest = documents.token_ids(tokens_by_rarity[0]) & candidate_ids
            lexical_truncated = len(candidate_ids) - len(rarest if rarest else candidate_ids)
            if rarest:
                candidate_ids = rarest
            else:
                candidate_ids = set(sorted(candidate_ids)[:LEXICAL_CANDIDATE_CAP])
    needs_full_scan = bool(args.text) or bool(other_facets) or args.mode == "intentional-flow-error" or (
        not args.identity and not args.relation_anchor
    )
    candidates = documents.load_many(sorted(candidate_ids)) if needs_full_scan else []
    if other_facets:
        kept = []
        for document in candidates:
            if all(facet_matches(document, key, operator, value) for key, operator, value in other_facets):
                kept.append(document)
            else:
                excluded["facet"] += 1
        candidates = kept

    gaps: list[str] = []
    results: list[dict[str, Any]] = []
    match_class = "structured"

    if args.mode == "intentional-flow-error":
        # FlowCustomError-only lookup: exact source text, then resolved label default, then
        # a sanitized fingerprint. Never falls back to fault paths or generic runtime text.
        needle = (args.text or "").strip()
        if not needle:
            raise SearchError("intentional-flow-error mode requires --text")
        fingerprint = message_fingerprint(needle)
        for document in candidates:
            for error in document["intentionalErrors"]:
                kind = None
                if error["messageTemplate"].strip() == needle:
                    kind = "exact-source-message"
                elif error.get("resolvedDefaultText") and error["resolvedDefaultText"].strip() == needle:
                    kind = "exact-resolved-label"
                elif error.get("elementApiName") and error["elementApiName"] == needle:
                    kind = "element-api-name"
                elif (
                    fingerprint
                    and fingerprint != MERGE_PLACEHOLDER
                    and fingerprint in {error["fingerprint"], error.get("resolvedFingerprint")}
                ):
                    kind = "safe-fingerprint"
                if kind:
                    hit = hit_of(document, 1.0, [{"field": "intentionalError", "match": kind, "value": needle}], kind)
                    hit["intentionalError"] = {
                        "elementApiName": error["elementApiName"],
                        "elementLabel": error["elementLabel"],
                        "presentation": error["presentation"],
                        "reachability": error["reachability"],
                        "basis": "source-declared",
                        "note": (
                            "Source declares this template on the named element; this does not "
                            "attribute any org runtime error to this Flow (contract §8.2)."
                        ),
                        "limitations": error["limitations"],
                    }
                    results.append(hit)
        if not results:
            gaps.append("No intentional Flow error matched.")
    elif args.relation_anchor:
        # incoming (default): who points AT the anchor — "which automations write this field".
        # outgoing: what the anchor itself declares — "what does this Flow touch".
        anchor = args.relation_anchor
        direction = args.direction or "incoming"
        if direction == "incoming":
            scan = documents.load_many(sorted(documents.relation_ids(anchor) & candidate_ids))
        else:
            anchor_ids = ({anchor} & set(documents.posting_file("offsets"))) | documents.facet_ids("fullName", anchor)
            scan = documents.load_many(sorted(anchor_ids & candidate_ids))
        for document in scan:
            is_anchor = anchor in {document["identity"], document["facets"]["fullName"]}
            if direction == "outgoing" and not is_anchor:
                continue
            for edge in document["edges"]:
                if args.relation_kind and edge["kind"] != args.relation_kind:
                    continue
                if not args.include_heuristic and edge["assurance"] != "source-exact":
                    excluded["heuristicEdge"] += 1
                    continue
                if direction == "incoming" and edge["target"] != anchor:
                    continue
                results.append(
                    hit_of(
                        document,
                        1.0,
                        [
                            {
                                "field": "relations.target",
                                "match": "exact-relation",
                                "relationKind": edge["kind"],
                                "value": edge["target"],
                            }
                        ],
                        "exact-relation",
                    )
                )
                if direction == "incoming":
                    break
        if not results:
            gaps.append(
                "No exact relation edge matched; heuristic edges are excluded unless "
                "--include-heuristic is set, and absence of an edge is not proof of absence."
            )
    elif args.identity:
        wanted = {args.identity} & set(documents.posting_file("offsets"))
        wanted |= documents.facet_ids("fullName", args.identity)
        for document in documents.load_many(sorted(wanted & candidate_ids)):
            results.append(
                hit_of(document, 1.0, [{"field": "identity", "match": "exact-identity", "value": args.identity}], "exact-identity")
            )
        if len({hit["artifactId"] for hit in results}) > 1 and args.namespace is None:
            return {
                "outcome": "AMBIGUOUS",
                "interpretedQuery": interpreted,
                "reason": "identity exists in multiple namespaces; pass --namespace to disambiguate",
                "candidates": sorted(hit["artifactId"] for hit in results),
                "indexGeneration": manifest["generation"],
            }
    elif args.text:
        tokens = analyze(args.text)
        scored = bm25f(documents, candidates, tokens)
        match_class = "lexical"
        for document in candidates:
            if document["identity"] in scored:
                score, matched = scored[document["identity"]]
                results.append(hit_of(document, score, matched, "structured-plus-lexical" if facets else "lexical"))
        results.sort(key=lambda hit: (-hit["score"], hit["artifactId"]))
        if lexical_truncated:
            gaps.append(
                f"Lexical candidate set capped at {LEXICAL_CANDIDATE_CAP}; {lexical_truncated} "
                "lower-signal matches were not ranked. Narrow with a facet or a rarer term."
            )
        if not results:
            gaps.append("No lexical match; try --state draft, relax a facet, or check the analyzer aliases.")
    else:
        results = [hit_of(document, 0.0, [], "structured") for document in candidates]
        results.sort(key=lambda hit: hit["artifactId"])

    draft_lane = (
        [
            hit_of(document, 0.0, [], "draft-lane")
            for document in documents.load_many(sorted(documents.lane_ids(["draft"]))[:10])
        ]
        if "draft" not in states
        else []
    )
    relaxations = []
    if not results:
        if args.metadata_type:
            relaxations.append("remove --metadata-type")
        if facets:
            relaxations.append("remove one facet")
        if "draft" not in states and draft_lane:
            relaxations.append("add --state draft (separate lane, never merged with approved)")
        if args.relation_anchor and not args.include_heuristic:
            relaxations.append("add --include-heuristic (separate assurance lane)")

    if not results and args.identity:
        # An exact identity that matched nothing is either absent or lane-filtered, and those are
        # very different answers. Reporting neither — an empty result with an empty gaps array —
        # is the worst of the three: it reads as "no such thing" when the entry is sitting in the
        # index, revoked or drifted, one --state away.
        known = documents.get(args.identity)
        if known is not None:
            gaps.append(
                f"{args.identity} exists in this index in lane '{known['lane']}', which is outside "
                f"the requested {', '.join(states)}. It was not served. Pass --state {known['lane']} "
                "to see it, in its own bucket — it is not approved-current knowledge."
            )
        else:
            gaps.append(
                f"No entry in this index generation projects {args.identity}. That is absence of "
                "an ENTRY, not absence of the artifact."
            )

    served, hydration_gaps = hydrate(results[: args.top])
    gaps.extend(hydration_gaps)
    # `--state draft` (or any other lane opt-in) must not tip non-current content into a key
    # named `approvedResults`: a consumer reading that key is entitled to treat every hit in
    # it as effective approved knowledge. Opted-in lanes are served in their own bucket, each
    # hit still carrying its `lifecycle`.
    if excluded.get("heuristicEdge") and not args.include_heuristic:
        # Reporting the count only in excludedCounts was survivable while almost nothing was
        # excluded. Once kind-level heuristics are marked honestly, a default relation query
        # drops most of the graph — 44 of 50 edges for a hub object in the probe corpus — and a
        # silently narrowed answer reads exactly like a complete one.
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) were excluded; they are inferred "
            "(regex-derived), not declared. Add --include-heuristic to see them, in their own "
            "assurance lane."
        )
    current = [hit for hit in served if hit["lifecycle"] == "approved-current"]
    non_current = [hit for hit in served if hit["lifecycle"] != "approved-current"]
    if non_current:
        lanes = sorted({hit["lifecycle"] for hit in non_current})
        gaps.append(
            f"{len(non_current)} result(s) served from opted-in lane(s) {', '.join(lanes)}; "
            "they are not approved-current knowledge and must not be cited as effective."
        )
    return {
        "outcome": "OK" if served else "NO_MATCH",
        "interpretedQuery": interpreted,
        "approvedResults": current,
        "nonCurrentResults": non_current,
        "draftCandidates": [hit["artifactId"] for hit in draft_lane][:10],
        "excludedCounts": dict(sorted(excluded.items())),
        "facetCounts": {
            "metadataType": manifest["metadataTypeCounts"],
            "lifecycle": manifest["laneCounts"],
        },
        "suggestedRelaxations": relaxations,
        "gaps": gaps,
        "matchClass": match_class,
        "indexGeneration": manifest["generation"],
    }


def source_coverage(manifest: dict[str, Any]) -> dict[str, Any]:
    """What could possibly have appeared as an edge source in this result.

    Only entry-homed types produce entries, so Profile, Layout, FlexiPage, ApprovalProcess,
    Workflow, DuplicateRule and the rest can never appear as a source however many of them
    reference the anchor. A field referenced only by a Profile and a Layout reports zero
    incoming edges — which reads as "nothing depends on it" unless the population is stated."""

    return {
        "entryHomedTypes": sorted(store.PROFILES),
        "inCorpus": manifest.get("metadataTypeCounts", {}),
        "note": (
            "Only the metadata types listed in entryHomedTypes can appear as an edge source. "
            "Profile, Layout, FlexiPage, ApprovalProcess, Workflow, DuplicateRule and other "
            "non-entry-homed types are structurally absent from this result."
        ),
    }


TRUNCATION_FAMILY_KINDS = {
    "fieldPermissions": {"grants-field-read", "grants-field-edit", "grants-field-permission"},
    "objectPermissions": {"grants-object-permission", "grants-object-view-all", "grants-object-modify-all"},
    "recordTypes": {"grants-record-type"},
    "classAccesses": {"grants-class-access"},
}


def truncation_gaps(documents: "DocumentStore", kinds: Iterable[str]) -> list[str]:
    """Warn when a kind in this result belongs to a family some source had capped.

    A missing grant is indistinguishable from an absent grant, and the collector cuts
    fieldPermissions first — so the security question fails closed in the wrong direction
    unless the incompleteness is stated."""

    truncated = documents.posting_file("reverse").get("truncatedSources", {})
    if not truncated:
        return []
    wanted = set(kinds)
    gaps = []
    for family, sources in sorted(truncated.items()):
        family_kinds = TRUNCATION_FAMILY_KINDS.get(family)
        if wanted and family_kinds and not (wanted & family_kinds):
            continue
        gaps.append(
            f"{len(sources)} entr(y/ies) had their {family} edge list capped by the collector; "
            "edges of that family may be missing from this result and absence is not proof of "
            "absence."
        )
    return gaps


def lane_split(rows: list[dict[str, Any]], key: str = "lifecycle") -> tuple[list, list]:
    """approved-current rows and opted-in-lane rows, never merged into one array."""
    current = [row for row in rows if row.get(key) == "approved-current"]
    other = [row for row in rows if row.get(key) != "approved-current"]
    return current, other


def _requested_states(args: argparse.Namespace) -> list[str]:
    return list(getattr(args, "state", None) or ESTABLISHED_STATES)


def run_explain(args: argparse.Namespace) -> dict[str, Any]:
    documents, manifest = load_index()
    document = documents.get(args.identity)
    if document is None:
        raise SearchError(f"no entry projection for {args.identity}")
    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    include_heuristic = bool(getattr(args, "include_heuristic", False))

    # Incoming edges come from the reverse posting rather than a full-corpus scan, and carry
    # their lane so a revoked or tampered entry cannot be served as a dependency.
    rows: list[dict[str, Any]] = []
    excluded = {"lifecycle": 0, "heuristicEdge": 0}
    seen_targets = {document["identity"], document["facets"].get("fullName")}
    for target in sorted(name for name in seen_targets if name):
        for edge in documents.incoming_edges(target, include_heuristic=True):
            if edge["assurance"] != relation_kinds.SOURCE_EXACT and not include_heuristic:
                excluded["heuristicEdge"] += 1
                continue
            if edge["source"] not in allowed:
                excluded["lifecycle"] += 1
                continue
            source = documents.get(edge["source"])
            rows.append({**edge, "lifecycle": source["lane"] if source else None})
    rows.sort(key=lambda item: (item["source"], item["kind"], item["assurance"]))
    current, non_current = lane_split(rows)

    gaps: list[str] = []
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) excluded; add --include-heuristic."
        )
    if excluded["lifecycle"]:
        gaps.append(
            f"{excluded['lifecycle']} edge(s) came from entries outside {', '.join(states)}."
        )
    if non_current:
        gaps.append(
            f"{len(non_current)} incoming edge(s) are declared by entries in opted-in lane(s); "
            "they are not approved-current knowledge and must not be cited as effective."
        )
    gaps.extend(truncation_gaps(documents, {row["kind"] for row in rows}))

    return {
        "outcome": "EXPLAIN",
        "artifactId": document["identity"],
        "lifecycle": document["lane"],
        "facets": document["facets"],
        "assurance": document["assurance"],
        "coverage": document["coverage"],
        "limitations": document["limitations"],
        "outgoing": document["edges"],
        "incoming": current,
        "incomingNonCurrent": non_current,
        "parts": documents.incoming_edges(
            document["facets"].get("fullName") or document["identity"],
            kinds={CONTAINMENT_KIND}, include_heuristic=include_heuristic,
        ),
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {"documentReads": documents.document_reads, "postingBytesRead": documents.posting_bytes},
        "intentionalErrors": [
            {
                "elementApiName": error["elementApiName"],
                "presentation": error["presentation"],
                "reachability": error["reachability"],
                "basis": "source-declared",
            }
            for error in document["intentionalErrors"]
        ],
        "citation": document["citation"],
        "indexGeneration": manifest["generation"],
    }


def run_impact(args: argparse.Namespace) -> dict[str, Any]:
    """Reverse or forward traversal from an anchor, one chain per reached node.

    Direction matters more than it looks. Reverse answers "what breaks if I change this" —
    who points at the anchor. Forward answers "how does this work" — what the anchor invokes,
    then what that invokes. Only reverse existed, so `impact` from an ApexTrigger returned zero
    edges: nothing references a trigger. The outgoing edges were on the projection the whole
    time; only the traversal was missing.
    """

    documents, manifest = load_index()
    limit = DEPTH_LIMITS["impact"]
    requested = int(getattr(args, "depth", 1) or 1)
    depth = max(1, min(requested, limit))
    direction = getattr(args, "direction", None) or "incoming"
    include_heuristic = bool(getattr(args, "include_heuristic", False))
    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    top = int(getattr(args, "top", None) or IMPACT_TOP_DEFAULT)

    excluded = {"lifecycle": 0, "heuristicEdge": 0}
    limits_hit: set[str] = set()
    # `path` carries how a node was reached. A flat hop-2 row names an edge target that is only
    # accidentally connectable to the anchor, so a reader cannot tell a real chain from a
    # coincidence of naming.
    chains: list[dict[str, Any]] = []
    visited = {args.identity}
    frontier = [{"node": args.identity, "path": [], "minAssurance": relation_kinds.SOURCE_EXACT}]

    for level in range(depth):
        next_frontier: list[dict[str, Any]] = []
        for item in sorted(frontier, key=lambda entry: entry["node"]):
            document = documents.get(item["node"])
            names = {item["node"]}
            if document:
                full_name = document["facets"].get("fullName")
                if full_name:
                    names.add(str(full_name))
            hops = []
            if direction == "incoming":
                for name in sorted(names):
                    for edge in documents.incoming_edges(name, include_heuristic=True):
                        hops.append((edge["source"], edge["kind"], name, edge["assurance"]))
            else:
                for edge in (document or {}).get("edges", []):
                    row = documents.target_row(edge["target"])
                    resolved = row.get("targetIdentity")
                    hops.append((resolved or edge["target"], edge["kind"], edge["target"], edge["assurance"]))
            if len(hops) > TRAVERSAL_LIMITS["maxFanout"]:
                limits_hit.add("fanout")
                hops = sorted(hops)[: TRAVERSAL_LIMITS["maxFanout"]]
            for node, kind, via, assurance in sorted(hops):
                if assurance != relation_kinds.SOURCE_EXACT and not include_heuristic:
                    excluded["heuristicEdge"] += 1
                    continue
                reached = documents.get(node)
                if reached is None:
                    # Forward hop into something with no entry: kept, labelled, never dropped.
                    lifecycle = None
                elif node not in allowed:
                    excluded["lifecycle"] += 1
                    continue
                else:
                    lifecycle = reached["lane"]
                if node in visited:
                    continue
                weakest = (
                    relation_kinds.SOURCE_DERIVED_HEURISTIC
                    if relation_kinds.SOURCE_DERIVED_HEURISTIC in (assurance, item["minAssurance"])
                    else relation_kinds.SOURCE_EXACT
                )
                step = {"from": item["node"], "kind": kind, "to": node, "via": via, "assurance": assurance}
                chains.append({
                    "node": node, "hop": level + 1, "lifecycle": lifecycle,
                    "resolved": reached is not None,
                    "path": item["path"] + [step],
                    "minAssurance": weakest,
                })
                next_frontier.append({"node": node, "path": item["path"] + [step], "minAssurance": weakest})
                if len(chains) >= TRAVERSAL_LIMITS["maxNodes"]:
                    limits_hit.add("nodes")
                    break
            if "nodes" in limits_hit:
                break
        visited |= {row["node"] for row in next_frontier}
        frontier = next_frontier
        if not frontier or "nodes" in limits_hit:
            break

    chains.sort(key=lambda row: (row["hop"], row["node"]))
    served = chains[:top]
    if len(chains) > top:
        limits_hit.add("top")
    current, non_current = lane_split(served)

    gaps: list[str] = []
    if requested > limit:
        gaps.append(f"depth {requested} was reduced to the {limit}-hop limit for impact.")
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic hop(s) excluded. Execution chains are built "
            "from inferred edges (invokes-class is regex-derived), so answering \"how does this "
            "work\" needs --include-heuristic; each hop then carries its own assurance."
        )
    if excluded["lifecycle"]:
        gaps.append(f"{excluded['lifecycle']} node(s) outside {', '.join(states)} were excluded.")
    if non_current:
        gaps.append(
            f"{len(non_current)} node(s) served from opted-in lane(s); they are not "
            "approved-current knowledge and must not be cited as effective."
        )
    if limits_hit:
        gaps.append(f"traversal limits reached: {', '.join(sorted(limits_hit))}.")
    gaps.extend(truncation_gaps(documents, {step["kind"] for row in served for step in row["path"]}))

    return {
        "outcome": "IMPACT",
        "anchor": args.identity,
        "direction": direction,
        "depthRequested": requested,
        "depthLimit": limit,
        "depthReached": max((row["hop"] for row in served), default=0),
        "limitsHit": sorted(limits_hit),
        "nodes": current,
        "nodesNonCurrent": non_current,
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {
            "documentReads": documents.document_reads,
            "postingBytesRead": documents.posting_bytes,
            "nodesServed": len(served),
        },
        "note": "Static source-declared edges only; absence of an edge is not proof of absence.",
        "indexGeneration": manifest["generation"],
    }


PERMISSION_KINDS = {
    kind for kinds in TRUNCATION_FAMILY_KINDS.values() for kind in kinds
} | {"grants-flow-access", "grants-custom-permission", "grants-user-permission"}
CONTEXT_TOP_DEFAULT = 25


def run_context(args: argparse.Namespace) -> dict[str, Any]:
    """Everything about one artifact, in one call.

    Answering "tell me about X" took six heterogeneous queries — identity lookup, a facet query
    per child type, incoming relations, outgoing relations, impact, permission grants — each
    with its own shape and its own lane semantics, and two of them (ValidationRule, RecordType)
    had no object facet at all, so the owner had to be read out of a fullName prefix by hand.

    Sections are capped BEFORE hydration, not after. Hydrating first and capping second spent
    the budget on rows the caller never sees and left the rows they are invited to cite
    unverified — inverting the point of the budget.
    """

    documents, manifest = load_index()
    document = documents.get(args.identity)
    if document is None:
        candidates = documents.identities_for_full_name(args.identity)
        if len(candidates) == 1:
            document = documents.get(candidates[0])
        elif len(candidates) > 1:
            return {
                "outcome": "AMBIGUOUS",
                "query": args.identity,
                "candidates": sorted(candidates),
                "gaps": [
                    "A bare name that exists in several namespaces is never resolved by ranking; "
                    "pass the full <MetadataType>:<ns|c>:<FullName> identity."
                ],
                "indexGeneration": manifest["generation"],
            }
    if document is None:
        return {
            "outcome": "NO_ENTRY",
            "query": args.identity,
            "entryExists": False,
            "gaps": [
                f"No Knowledge Entry projects {args.identity} in this index generation. That is "
                "absence of an ENTRY, not absence of the artifact — check `entry-coverage` for "
                "the source-side denominator."
            ],
            "indexGeneration": manifest["generation"],
        }

    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    include_heuristic = bool(getattr(args, "include_heuristic", False))
    top = int(getattr(args, "top", None) or CONTEXT_TOP_DEFAULT)
    names = {document["identity"]}
    full_name = document["facets"].get("fullName")
    if full_name:
        names.add(str(full_name))

    incoming: list[dict[str, Any]] = []
    excluded = {"lifecycle": 0, "heuristicEdge": 0, "cap": 0}
    for name in sorted(names):
        for edge in documents.incoming_edges(name, include_heuristic=True):
            if edge["assurance"] != relation_kinds.SOURCE_EXACT and not include_heuristic:
                excluded["heuristicEdge"] += 1
                continue
            if edge["source"] not in allowed:
                excluded["lifecycle"] += 1
                continue
            incoming.append(edge)

    def bucket(rows: list[dict[str, Any]], kinds: set[str] | None, invert: bool = False):
        chosen = [
            row for row in rows
            if kinds is None or ((row["kind"] in kinds) is not invert)
        ]
        chosen.sort(key=lambda row: (row["kind"], row["source"]))
        if len(chosen) > top:
            excluded["cap"] += len(chosen) - top
        return chosen[:top]

    parts = bucket(incoming, {CONTAINMENT_KIND})
    permissions = bucket(incoming, PERMISSION_KINDS)
    other_incoming = bucket(incoming, {CONTAINMENT_KIND} | PERMISSION_KINDS, invert=True)

    # Hydration runs over what SURVIVED the cap, so a served row is a verified row.
    served_sources = {row["source"] for row in parts + permissions + other_incoming}
    hydrated, hydration_gaps = hydrate(
        [
            {"artifactId": identity, "citation": documents.get(identity)["citation"]}
            for identity in sorted(served_sources)
            if documents.get(identity)
        ]
    )
    verified = {hit["artifactId"] for hit in hydrated}
    for row in parts + permissions + other_incoming:
        row["hydrated"] = row["source"] in verified

    gaps = list(hydration_gaps)
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) excluded; add --include-heuristic."
        )
    if excluded["lifecycle"]:
        gaps.append(f"{excluded['lifecycle']} edge(s) came from entries outside {', '.join(states)}.")
    if excluded["cap"]:
        gaps.append(f"{excluded['cap']} row(s) beyond --top {top} were not returned.")
    gaps.append(
        "`parts` lists artifacts that have a Knowledge Entry in this index generation, not the "
        "object's declared composition. Run `python scripts/knowledge_store.py entry-coverage` "
        "for the source-side denominator."
    )
    gaps.extend(truncation_gaps(documents, {row["kind"] for row in incoming}))

    return {
        "outcome": "CONTEXT",
        "artifactId": document["identity"],
        "lifecycle": document["lane"],
        "subject": {
            "facets": document["facets"],
            "purpose": document.get("purpose"),
            "assurance": document["assurance"],
            "coverage": document["coverage"],
            "limitations": document["limitations"],
            "citation": document["citation"],
        },
        "parts": parts,
        "partsCoverage": {
            "basis": f"inverted {CONTAINMENT_KIND} edges in this index generation",
            "entriesByType": manifest.get("metadataTypeCounts", {}),
        },
        "permissions": permissions,
        "incoming": other_incoming,
        "outgoing": document["edges"],
        "intentionalErrors": document["intentionalErrors"],
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {
            "documentReads": documents.document_reads,
            "postingBytesRead": documents.posting_bytes,
        },
        "indexGeneration": manifest["generation"],
    }


def run_capabilities(args: argparse.Namespace) -> dict[str, Any]:
    facets = dict(GLOBAL_FACETS)
    if args.metadata_type:
        facets.update(PROFILE_FACETS.get(args.metadata_type, {}))
    else:
        for profile_facets in PROFILE_FACETS.values():
            facets.update(profile_facets)
    return {
        "outcome": "CAPABILITIES",
        "metadataType": args.metadata_type,
        "facets": dict(sorted(facets.items())),
        "operators": list(FACET_OPERATORS),
        "modes": ["hybrid", "intentional-flow-error"],
        "lifecycleLanes": list(ALL_LANES),
        "defaultStates": list(ESTABLISHED_STATES),
        "analyzerVersion": ANALYZER_VERSION,
        "supportedProfiles": sorted(PROFILE_FACETS),
        # --relation-kind accepted any string and capabilities listed none, so the only way to
        # learn the vocabulary was to guess or read the collector.
        "relationKinds": sorted(relation_kinds.ALL_REF_KINDS),
        "heuristicRelationKinds": sorted(relation_kinds.HEURISTIC_REF_KINDS),
        "containmentKind": CONTAINMENT_KIND,
        "directions": ["incoming", "outgoing"],
        "depthLimits": dict(DEPTH_LIMITS),
        "assuranceLanes": {
            relation_kinds.SOURCE_EXACT: "declared in source; served by default",
            relation_kinds.SOURCE_DERIVED_HEURISTIC: (
                "inferred (regex-derived); excluded unless --include-heuristic. Execution chains "
                "are built from these, so answering \"how does this work\" requires the flag."
            ),
        },
    }


def command_build(args: argparse.Namespace) -> dict[str, Any]:
    return build_index(check=args.check, full=args.full)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge_search", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="rebuild the generated search cache")
    build.add_argument("--check", action="store_true")
    build.add_argument("--full", action="store_true", help="ignore reusable projections")
    build.set_defaults(func=command_build)

    search = commands.add_parser("search", help="typed retrieval over approved entries")
    search.add_argument("--text", default=None)
    search.add_argument("--identity", default=None)
    search.add_argument("--metadata-type", default=None)
    search.add_argument("--namespace", default=None)
    search.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    search.add_argument("--facet", action="append", default=None, help="key[:op]=value")
    search.add_argument("--relation-anchor", default=None)
    search.add_argument("--relation-kind", default=None)
    search.add_argument("--direction", default=None, choices=["outgoing", "incoming"])
    search.add_argument("--include-heuristic", action="store_true")
    search.add_argument("--mode", default="hybrid", choices=["hybrid", "intentional-flow-error"])
    search.add_argument("--top", type=int, default=10)
    search.set_defaults(func=run_search)

    explain = commands.add_parser("explain", help="one artifact with usage and reverse usage")
    explain.add_argument("--identity", required=True)
    explain.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    explain.add_argument("--include-heuristic", action="store_true")
    explain.set_defaults(func=run_explain)

    impact = commands.add_parser("impact", help="bounded dependency traversal, either direction")
    impact.add_argument("--identity", required=True)
    impact.add_argument("--depth", type=int, default=1)
    impact.add_argument(
        "--direction", default="incoming", choices=["incoming", "outgoing"],
        help="incoming: who points at the anchor (what breaks if I change it). "
        "outgoing: what the anchor reaches (how it works).",
    )
    impact.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    impact.add_argument("--top", type=int, default=IMPACT_TOP_DEFAULT)
    impact.add_argument("--include-heuristic", action="store_true")
    impact.set_defaults(func=run_impact)

    context = commands.add_parser(
        "context", help="one composed pack for an artifact: parts, usage, permissions, coverage"
    )
    context.add_argument("--identity", required=True)
    context.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    context.add_argument("--top", type=int, default=CONTEXT_TOP_DEFAULT)
    context.add_argument("--include-heuristic", action="store_true")
    context.set_defaults(func=run_context)

    capabilities = commands.add_parser("capabilities", help="valid facets, operators, modes")
    capabilities.add_argument("--metadata-type", default=None)
    capabilities.set_defaults(func=run_capabilities)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except (SearchError, store.StoreError) as error:
        print(json.dumps({"outcome": "ERROR", "reason": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
