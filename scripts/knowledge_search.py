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
import json
import math
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from scripts import knowledge_store as store
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_search.py`
    import knowledge_store as store  # type: ignore

ANALYZER_VERSION = "1.0.0"
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

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
SF_SUFFIX = re.compile(r"__(c|r|e|mdt|b|x|kav|s|hd|share|history)$", re.IGNORECASE)
# Merge fields collapse to a single visible sentinel so two messages that differ only in
# their runtime variables share a fingerprint, while a message with no variable at all
# stays distinct. U+FFFC (OBJECT REPLACEMENT CHARACTER) can never occur in Flow source.
MERGE_PLACEHOLDER = "￼"
# Latin letters that carry no combining mark and therefore survive NFD unchanged; without
# this table Polish `ł` (and friends) block the folded alias used for diacritic-free recall.
STROKE_FOLDING = str.maketrans(
    {"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss"}
)


def fold_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.translate(STROKE_FOLDING))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def analyze(value: str) -> list[str]:
    """Tokens for one text value: full symbols preserved, plus split and folded aliases.

    Unlike the v1 tokenizer (ASCII-only `[a-z0-9]+`, which shreds Polish text and turns
    `Object__c.Field__c` into a stream of `c`), this keeps the exact scoped symbol, the
    Salesforce suffix as its own signal, and a diacritic-folded alias for recall.
    """
    text = unicodedata.normalize("NFKC", value)
    tokens: list[str] = []
    for raw in re.split(r"[\s,;:/\\()\[\]{}<>\"'`|!?]+", text):
        if not raw:
            continue
        symbol = raw.strip(".-").casefold()
        if not symbol:
            continue
        tokens.append(symbol)  # exact scoped symbol, e.g. engagement__c.status__c
        # Split dotted segments first so the Salesforce suffix is still attached when it is
        # detected; splitting on "_" up front would destroy `__c` before it can be indexed.
        for segment in re.split(r"\.+", CAMEL_BOUNDARY.sub(" ", raw)):
            segment = segment.strip().casefold()
            if not segment:
                continue
            suffix = SF_SUFFIX.search(segment)
            if suffix:
                tokens.append(suffix.group(0))
                segment = SF_SUFFIX.sub("", segment)
            for word in re.split(r"[_\s]+", segment):
                if not word:
                    continue
                tokens.append(word)
                folded_word = fold_diacritics(word)
                if folded_word != word:
                    tokens.append(folded_word)
        folded = fold_diacritics(symbol)
        if folded != symbol:
            tokens.append(folded)
    return [token for token in tokens if token]


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


PROFILE_PROJECTORS = {"Flow": _flow_facets, "CustomField": _custom_field_facets}


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
        }
    )


def collect_projections() -> list[dict[str, Any]]:
    latest = store.ledger_latest(store.read_ledger())
    projections = []
    for path in store.all_entry_paths():
        lane = store.compute_lane(path, latest)
        projections.append(project_entry(path, lane))
    return sorted(projections, key=lambda item: item["identity"])


def build_index(check: bool = False) -> dict[str, Any]:
    projections = collect_projections()
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
    with documents.open("w", encoding="utf-8", newline="\n") as handle:
        for item in projections:
            handle.write(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n")
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
    return {"outcome": "BUILT", "generation": generation, "entries": len(projections)}


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
    projections = collect_projections()
    if entry_set_digest(projections) != manifest["generation"]:
        raise SearchError("INDEX STALE / REBUILD REQUIRED: entries changed since the last build")
    documents = [json.loads(line) for line in documents_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return documents, manifest


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


def bm25f(documents: list[dict[str, Any]], candidates: list[dict[str, Any]], query_tokens: list[str]) -> dict[str, tuple[float, list[dict[str, Any]]]]:
    if not query_tokens:
        return {}
    document_frequency: dict[str, int] = defaultdict(int)
    field_lengths: dict[str, list[int]] = defaultdict(list)
    for document in documents:
        seen = {token for field in document["fields"].values() for token in field}
        for token in seen:
            document_frequency[token] += 1
        for field, tokens in document["fields"].items():
            field_lengths[field].append(len(tokens))
    average_length = {
        field: (sum(lengths) / len(lengths)) if lengths else 1.0 for field, lengths in field_lengths.items()
    }
    total = max(len(documents), 1)
    scored: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    for document in candidates:
        score = 0.0
        matched: list[dict[str, Any]] = []
        for token in set(query_tokens):
            idf = math.log(1 + (total - document_frequency.get(token, 0) + 0.5) / (document_frequency.get(token, 0) + 0.5))
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

    candidates: list[dict[str, Any]] = []
    for document in documents:
        if document["lane"] not in states:
            excluded["lifecycle:" + document["lane"]] += 1
            continue
        if args.metadata_type and document["facets"]["metadataType"] != args.metadata_type:
            excluded["metadataType"] += 1
            continue
        if args.namespace is not None:
            wanted = None if args.namespace == "c" else args.namespace
            if document["facets"]["namespace"] != wanted:
                excluded["scope"] += 1
                continue
        if any(not facet_matches(document, key, operator, value) for key, operator, value in facets):
            excluded["facet"] += 1
            continue
        candidates.append(document)

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
        for document in candidates:
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
        for document in candidates:
            if document["identity"] == args.identity or document["facets"]["fullName"] == args.identity:
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
        if not results:
            gaps.append("No lexical match; try --state draft, relax a facet, or check the analyzer aliases.")
    else:
        results = [hit_of(document, 0.0, [], "structured") for document in candidates]
        results.sort(key=lambda hit: hit["artifactId"])

    draft_lane = [
        hit_of(document, 0.0, [], "draft-lane")
        for document in documents
        if document["lane"] == "draft" and "draft" not in states
    ]
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

    return {
        "outcome": "OK" if results else "NO_MATCH",
        "interpretedQuery": interpreted,
        "approvedResults": results[: args.top],
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


def run_explain(args: argparse.Namespace) -> dict[str, Any]:
    documents, manifest = load_index()
    document = next((item for item in documents if item["identity"] == args.identity), None)
    if document is None:
        raise SearchError(f"no entry projection for {args.identity}")
    incoming = [
        {"source": other["identity"], "kind": edge["kind"], "assurance": edge["assurance"]}
        for other in documents
        for edge in other["edges"]
        if edge["target"] in {document["identity"], document["facets"]["fullName"]}
    ]
    return {
        "outcome": "EXPLAIN",
        "artifactId": document["identity"],
        "lifecycle": document["lane"],
        "facets": document["facets"],
        "assurance": document["assurance"],
        "coverage": document["coverage"],
        "limitations": document["limitations"],
        "outgoing": document["edges"],
        "incoming": sorted(incoming, key=lambda item: (item["source"], item["kind"])),
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
    documents, manifest = load_index()
    depth = max(1, min(args.depth, 2))
    by_identity = {document["identity"]: document for document in documents}
    frontier = {args.identity}
    visited: set[str] = set()
    paths: list[dict[str, Any]] = []
    for level in range(depth):
        next_frontier: set[str] = set()
        for document in documents:
            for edge in document["edges"]:
                if edge["target"] in frontier or edge["target"] in {
                    by_identity[node]["facets"]["fullName"] for node in frontier if node in by_identity
                }:
                    if not args.include_heuristic and edge["assurance"] != "source-exact":
                        continue
                    if document["identity"] in visited:
                        continue
                    paths.append(
                        {
                            "source": document["identity"],
                            "kind": edge["kind"],
                            "target": edge["target"],
                            "assurance": edge["assurance"],
                            "hop": level + 1,
                            "lifecycle": document["lane"],
                        }
                    )
                    next_frontier.add(document["identity"])
        visited |= frontier
        frontier = next_frontier - visited
        if not frontier:
            break
    return {
        "outcome": "IMPACT",
        "anchor": args.identity,
        "depth": depth,
        "edges": sorted(paths, key=lambda item: (item["hop"], item["source"], item["kind"])),
        "note": "Static source-declared edges only; absence of an edge is not proof of absence.",
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
    }


def command_build(args: argparse.Namespace) -> dict[str, Any]:
    return build_index(check=args.check)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge_search", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="rebuild the generated search cache")
    build.add_argument("--check", action="store_true")
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
    explain.set_defaults(func=run_explain)

    impact = commands.add_parser("impact", help="bounded reverse-dependency traversal")
    impact.add_argument("--identity", required=True)
    impact.add_argument("--depth", type=int, default=1)
    impact.add_argument("--include-heuristic", action="store_true")
    impact.set_defaults(func=run_impact)

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
