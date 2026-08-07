#!/usr/bin/env python3
"""Feature Knowledge v2 core: model, digests, validation, lanes.

One canonical, human-approved, citable document per Feature
(`.ai/knowledge/features/<slug>/feature.md`). The frontmatter is the typed model — nodes,
relations, claims, entry points, questions, artifact bindings — with executor-allocated
stable IDs; the body is the human narrative. Membership is explicit curated topology:
graph traversal proposes candidates, only a recorded draft operation admits a component.

This module is pure domain logic used by `knowledge_store.py` (the CLI/executor surface):
no I/O beyond reading named schema/config files, no ledger writes, no process state.

Authority (master plan §9): human approval may establish business meaning and curated
interpretation; it may never turn a technical assertion without repository/org evidence
into a citable fact, and a heuristic is never citable at all — enforced here at validate
time, not left to review prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts import knowledge_store as ks
except ImportError:  # invoked as a script with scripts/ on sys.path
    import knowledge_store as ks

HARNESS_ROOT = Path(__file__).resolve().parents[1]
FEATURE_SCHEMA_PATH = HARNESS_ROOT / "schemas" / "knowledge-feature.schema.json"

VOCAB_VERSION = "feature-vocab-v1"
FEATURE_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
FEATURE_SENTINEL = "<AGENT_FEATURE_DESCRIPTION>"
ID_KINDS = ("FN", "FR", "FC", "FQ", "FB")
ID_RE = re.compile(r"^(FN|FR|FC|FQ|FB)-[0-9]{3,6}$")

LAYERS = (
    "domain-data", "business-rules", "processing", "automation", "code", "ui",
    "access", "integration", "configuration", "reporting", "shared",
)

# RB-2: feature layers are contextual roles and deliberately NOT the canonical storage
# families. The two vocabularies are similar on purpose and different on purpose — this map
# documents the correspondence, and a pin test asserts the difference stays conscious
# (families that gain or lose a name must revisit this map, never silently drift).
LAYER_FAMILY_NOTES = {
    "objects": ("domain-data", "business-rules"),
    "automation": ("automation",),
    "code": ("code", "processing"),
    "ui": ("ui",),
    "access": ("access",),
    "integration": ("integration",),
    "configuration": ("configuration",),
    "reporting": ("reporting",),
    "shared": ("shared",),
}

CLAIM_TYPES = (
    "feature-purpose", "feature-boundary", "component-role", "entry-point",
    "data-relationship", "calculation-lineage", "processing-order",
    "access-boundary", "integration-contract", "invariant", "known-limitation",
)

# Claim-type × authority matrix (master plan §9.2), frozen as data. `human-attested` is
# authority for declared business semantics only; technical assertions need repository or
# governed org evidence. A claim outside its row fails validation — approval cannot launder.
HUMAN_ATTESTABLE_CLAIM_TYPES = frozenset({
    "feature-purpose", "feature-boundary", "component-role", "entry-point",
    "invariant", "known-limitation",
})
SOURCE_REQUIRED_CLAIM_TYPES = frozenset(CLAIM_TYPES) - HUMAN_ATTESTABLE_CLAIM_TYPES

CITABLE_AUTHORITIES = frozenset({"source-exact", "human-attested", "org-observed"})

# Body sections (§6.3): the core three are mandatory; the rest render only when the feature
# actually has content for them (an explicit reviewed "Not applicable" is content too).
BODY_SECTIONS = (
    "Purpose and boundary", "Business journey", "Domain and data model", "Business rules",
    "Calculation and processing", "Automation", "Code responsibilities", "UI",
    "Access and security", "Integrations", "Configuration", "Reporting",
    "Invariants", "Known limitations", "Open questions", "Evidence map",
)
CORE_BODY_SECTIONS = ("Purpose and boundary", "Domain and data model", "Evidence map")


class FeatureError(ks.StoreError):
    """Domain error; the message is the actionable reason. A StoreError subclass so the
    executor CLI's fail-closed handling covers both lanes with one except clause."""


# --------------------------------------------------------------------------------------
# Identity and paths (v2: a directory per feature)
# --------------------------------------------------------------------------------------


def feature_identity(slug: str) -> str:
    """`Feature:<slug>` — deliberately two segments so it can never satisfy an Artifact
    entryRef (three segments); the envelope schemas also reject it by lookahead."""
    if not FEATURE_SLUG_RE.match(slug or ""):
        raise FeatureError(f"invalid feature slug {slug!r}")
    return f"Feature:{slug}"


def feature_dir(slug: str) -> Path:
    feature_identity(slug)
    if slug.split("-", 1)[0].upper() in ks.WINDOWS_RESERVED:
        raise FeatureError(f"slug {slug!r} collides with a Windows reserved device name")
    return ks.FEATURES_ROOT / slug


def feature_path(slug: str) -> Path:
    return feature_dir(slug) / "feature.md"


def all_feature_paths() -> list[Path]:
    if not ks.FEATURES_ROOT.is_dir():
        return []
    return sorted(ks.FEATURES_ROOT.glob("*/feature.md"))


# --------------------------------------------------------------------------------------
# IDs
# --------------------------------------------------------------------------------------


def allocate_id(frontmatter: dict[str, Any], kind: str) -> str:
    """Monotonic per-kind counters in draft state; deleting tombstones, never reassigns."""
    if kind not in ID_KINDS:
        raise FeatureError(f"unknown id kind {kind!r}")
    counters = frontmatter["draft"].setdefault("idCounters", {})
    counters[kind] = int(counters.get(kind, 0)) + 1
    return f"{kind}-{counters[kind]:03d}"


# --------------------------------------------------------------------------------------
# Digests
# --------------------------------------------------------------------------------------


def model_digest(frontmatter: dict[str, Any]) -> str:
    """Digest over the reviewed model: topology + bindings, excluding operational fields."""
    return ks.canonical_digest({
        "model": frontmatter.get("model", {}),
        "artifactBindings": frontmatter.get("artifactBindings", []),
    })


def feature_reviewed_content_digest(frontmatter: dict[str, Any], body: str) -> str:
    """The approval digest (§10.2): identity, schema+vocab versions, model, narrative,
    limitations, sensitivity. Excludes draft.version, approval mirror and keywords
    (keywords follow the artifact precedent: taxonomy-validated, digest-excluded)."""
    subject = frontmatter["subject"]
    return ks.canonical_digest({
        "identity": feature_identity(subject["slug"]),
        "name": subject["name"],
        "kind": "feature-knowledge",
        "schemaVersion": frontmatter["schemaVersion"],
        "vocabVersion": frontmatter["vocabVersion"],
        "modelDigest": model_digest(frontmatter),
        "semanticsDigest": ks.semantics_digest(body),
        "limitations": sorted(frontmatter.get("limitations", [])),
        "sensitivity": frontmatter["sensitivity"],
    })


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def _live(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if not item.get("tombstoned")]


def validate_feature(frontmatter: dict[str, Any], body: str) -> list[str]:
    """Every problem as one actionable sentence. Schema, closure, authority, taxonomy,
    narrative core — the full §16.2 pre-approval surface minus the human."""
    from jsonschema import Draft202012Validator

    problems: list[str] = []
    schema = json.loads(FEATURE_SCHEMA_PATH.read_text(encoding="utf-8"))
    problems.extend(
        error.message for error in Draft202012Validator(schema).iter_errors(frontmatter)
    )
    if problems:
        return problems  # closure checks below assume a schema-valid shape

    model = frontmatter["model"]
    nodes = {n["id"]: n for n in _live(model["nodes"])}
    relations = {r["id"]: r for r in _live(model["relations"])}
    claims = {c["id"]: c for c in _live(model["claims"])}
    questions = {q["id"]: q for q in _live(model["unresolved"])}
    bindings = {b["id"]: b for b in _live(frontmatter["artifactBindings"])}
    all_ids = set(nodes) | set(relations) | set(claims) | set(questions) | set(bindings)

    # Reference closure — an id named anywhere must exist and not be tombstoned.
    for node in nodes.values():
        if node["kind"] == "artifact" and not node.get("artifactId"):
            problems.append(f"{node['id']}: an artifact node requires artifactId")
        if node.get("role") == "other" and not node.get("roleNote"):
            problems.append(f"{node['id']}: role 'other' requires roleNote")
        for claim_id in node.get("evidenceClaimIds", []):
            if claim_id not in claims:
                problems.append(f"{node['id']}: evidence claim {claim_id} does not exist")
    for relation in relations.values():
        for end in ("from", "to"):
            if relation[end] not in nodes:
                problems.append(f"{relation['id']}: {end} node {relation[end]} does not exist")
        for binding_id in relation.get("evidenceRefs", []):
            if binding_id not in bindings:
                problems.append(f"{relation['id']}: binding {binding_id} does not exist")
        if relation["assurance"] == "source-exact" and not relation.get("evidenceRefs"):
            problems.append(
                f"{relation['id']}: a source-exact relation requires at least one artifact binding"
            )
    for entry_point in model["entryPoints"]:
        if entry_point["nodeId"] not in nodes:
            problems.append(f"entry point names missing node {entry_point['nodeId']}")
    for claim in claims.values():
        for dep in claim.get("dependsOn", []):
            if dep not in all_ids:
                problems.append(f"{claim['id']}: dependsOn {dep} does not exist")
        for binding_id in claim.get("evidenceRefs", []):
            if binding_id not in bindings:
                problems.append(f"{claim['id']}: binding {binding_id} does not exist")
        # Authority matrix (§9.2): approval cannot launder.
        if claim["authority"] == "human-attested" and claim["type"] in SOURCE_REQUIRED_CLAIM_TYPES:
            problems.append(
                f"{claim['id']}: claim type {claim['type']} requires repository/org evidence; "
                f"human attestation is not authority for it"
            )
        if claim["authority"] == "source-exact" and not claim.get("evidenceRefs"):
            problems.append(f"{claim['id']}: a source-exact claim requires an artifact binding")
        if claim["authority"] in ("source-derived-heuristic", "unresolved"):
            if claim["citationPolicy"] != "never-citable":
                problems.append(
                    f"{claim['id']}: {claim['authority']} material is never citable "
                    f"(citationPolicy must be never-citable)"
                )

    # Keywords: taxonomy-validated (owner decision RB-3) — the artifact precedent, wired
    # rather than repeated as dead fields.
    approved_terms = ks.approved_taxonomy_terms()
    for keyword in frontmatter.get("keywords", []):
        if keyword not in approved_terms:
            problems.append(f"keyword {keyword!r} is not in the approved taxonomy")

    # Narrative: core sections present and non-empty; only known section names; sentinel.
    if FEATURE_SENTINEL in body or ks.SENTINEL_PATTERN.search(body):
        problems.append("unfilled sentinel present in the narrative")
    sections = _body_sections(body)
    for section in CORE_BODY_SECTIONS:
        if not sections.get(section, "").strip():
            problems.append(f"core narrative section {section!r} is missing or empty")
    for name in sections:
        if name not in BODY_SECTIONS:
            problems.append(f"unknown narrative section {name!r}")
    return problems


def _body_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in (body or "").splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = line[3:].strip()
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


# --------------------------------------------------------------------------------------
# Lifecycle lane
# --------------------------------------------------------------------------------------


def compute_feature_lane(path: Path, latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """draft / approved-current / not-effective / revoked. A Feature has no source
    fragments, so there is no drift lane at the document level — evidence drift is
    claim-scoped and computed by verification, never stored here."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = ks.split_entry(text)
    slug = frontmatter.get("subject", {}).get("slug", "")
    identity = feature_identity(slug)
    problems = validate_feature(frontmatter, body)
    result: dict[str, Any] = {"identity": identity, "path": ks.relative_path(path), "problems": problems}
    record = latest.get(identity)
    if record and record.get("action") == "revoke":
        result["lane"] = "revoked"
        return result
    # F-3 lesson applied at birth: a DRAFT with outstanding work (unfilled sentinel, empty
    # core sections) is lane `draft` with its problems listed — outstanding work, not
    # corruption. Problems make an APPROVED document not-effective; they gate approval.
    if frontmatter.get("lifecycle", {}).get("state") == "draft":
        result["lane"] = "draft"
        if not problems:
            result["reviewedContentDigest"] = feature_reviewed_content_digest(frontmatter, body)
            result["modelDigest"] = model_digest(frontmatter)
        return result
    if problems:
        result["lane"] = "not-effective"
        return result
    digest = feature_reviewed_content_digest(frontmatter, body)
    result["reviewedContentDigest"] = digest
    result["modelDigest"] = model_digest(frontmatter)
    if not record or record.get("reviewedContentDigest") != digest:
        result["lane"] = "not-effective"
        result["problems"].append(
            "lifecycle says approved but the ledger does not hold this exact digest"
        )
        return result
    result["lane"] = "approved-current"
    return result


def verify_feature_citations(
    frontmatter: dict[str, Any],
    body: str,
    latest_record: dict[str, Any] | None,
    requested_ids: list[str],
    binding_resolver,
    requested_digests: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Claim-level verification (§10.3): the only producer of a citable featureRef.

    Verdicts: `current` (citable), `degraded` (selected claims citable, unrelated evidence
    drifted), `drifted`, `superseded` (requested digests no longer the approved ones),
    `not-citable`, `not-approved`, `unknown-id`, `invalid`, `unknown` (verification could
    not complete). Only `current` and `degraded` return a receipt."""
    problems = validate_feature(frontmatter, body)
    if problems:
        return {"verdict": "invalid", "problems": problems[:5]}
    digest = feature_reviewed_content_digest(frontmatter, body)
    if frontmatter["lifecycle"]["state"] != "approved" or not latest_record \
            or latest_record.get("action") == "revoke" \
            or latest_record.get("reviewedContentDigest") != digest:
        return {"verdict": "not-approved",
                "problems": ["the document is not approved-current in the feature ledger"]}
    current_model = model_digest(frontmatter)
    if requested_digests:
        if requested_digests.get("reviewedContentDigest") not in (None, digest) \
                or requested_digests.get("modelDigest") not in (None, current_model):
            return {"verdict": "superseded",
                    "problems": ["the reference pins digests that are no longer the approved ones"]}

    model = frontmatter["model"]
    claims = {c["id"]: c for c in _live(model["claims"])}
    relations = {r["id"]: r for r in _live(model["relations"])}
    bindings = {b["id"]: b for b in _live(frontmatter["artifactBindings"])}

    def closure_bindings(start: str) -> set[str]:
        """TRANSITIVE evidence dependencies (§10.3 step 5): follow dependsOn through
        claims and relations to every binding the requested statement ultimately rests on."""
        seen: set[str] = set()
        found: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in claims:
                found.update(claims[current].get("evidenceRefs", []))
                stack.extend(claims[current].get("dependsOn", []))
            elif current in relations:
                found.update(relations[current].get("evidenceRefs", []))
            # a node/question dep must simply exist live; validate_feature guaranteed it
        return found

    selected_binding_ids: set[str] = set()
    for requested in requested_ids:
        if requested in claims:
            claim = claims[requested]
            if claim["citationPolicy"] != "citable-after-approval" \
                    or claim["authority"] not in CITABLE_AUTHORITIES:
                return {"verdict": "not-citable",
                        "problems": [f"{requested} is {claim['authority']}/{claim['citationPolicy']}"]}
            selected_binding_ids.update(closure_bindings(requested))
        elif requested in relations:
            relation = relations[requested]
            if relation["assurance"] not in CITABLE_AUTHORITIES:
                return {"verdict": "not-citable",
                        "problems": [f"{requested} assurance is {relation['assurance']}"]}
            selected_binding_ids.update(relation.get("evidenceRefs", []))
        else:
            return {"verdict": "unknown-id",
                    "problems": [f"{requested} does not exist in the reviewed model"]}

    def binding_state(binding_id: str) -> str:
        binding = bindings.get(binding_id)
        if binding is None:
            return "unknown"
        try:
            receipt = binding_resolver(binding["entryId"])
        except Exception:
            return "unknown"
        return "current" if receipt["reviewedContentDigest"] == binding["reviewedContentDigest"] \
            else "drifted"

    selected_states = {binding_id: binding_state(binding_id) for binding_id in selected_binding_ids}
    if any(state == "drifted" for state in selected_states.values()):
        return {"verdict": "drifted",
                "problems": [f"binding {b} drifted" for b, s in selected_states.items() if s == "drifted"]}
    if any(state == "unknown" for state in selected_states.values()):
        return {"verdict": "unknown",
                "problems": [f"binding {b} could not be verified" for b, s in selected_states.items()
                             if s == "unknown"]}
    other_states = {binding_id: binding_state(binding_id)
                    for binding_id in bindings if binding_id not in selected_binding_ids}
    health = "degraded" if any(state != "current" for state in other_states.values()) else "current"
    return {
        "verdict": health,
        "receipt": {
            "featureId": feature_identity(frontmatter["subject"]["slug"]),
            "reviewedContentDigest": digest,
            "modelDigest": current_model,
            "claimIds": sorted(requested_ids),
        },
    }


MAX_OPERATIONS_PER_CALL = 40
MAX_SECTION_CHARS = 8000

OPERATION_KINDS = {
    "node": ("set", "remove"),
    "relation": ("set", "remove"),
    "claim": ("set", "withdraw"),
    "binding": ("bind", "unbind"),
    "section": ("replace",),
    "meta": ("set", "add-question", "resolve-question"),
}


def apply_operations(
    frontmatter: dict[str, Any],
    body: str,
    operations: list[dict[str, Any]],
    binding_resolver,
) -> tuple[dict[str, Any], str, list[str]]:
    """Apply one batch of typed operations to a draft. Fail-closed BEFORE any result is
    returned: unknown kinds/ops/ids, oversized payloads and broken closure reject the whole
    batch — this is Knowledge governance (the entry-lane posture), not the advisory SD loop.
    The executor allocates IDs; the caller never invents one. Returns the new
    (frontmatter, body, applied-summary)."""
    if not isinstance(operations, list) or not operations:
        raise FeatureError("operations must be a non-empty list")
    if len(operations) > MAX_OPERATIONS_PER_CALL:
        raise FeatureError(f"at most {MAX_OPERATIONS_PER_CALL} operations per call")
    fm = json.loads(json.dumps(frontmatter))
    new_body = body
    applied: list[str] = []

    def bucket(name: str) -> list[dict[str, Any]]:
        return fm["model"][name] if name != "binding" else fm["artifactBindings"]

    def find(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
        for item in items:
            if item.get("id") == item_id and not item.get("tombstoned"):
                return item
        raise FeatureError(f"{item_id} does not exist (or is tombstoned)")

    for index, operation in enumerate(operations):
        kind = operation.get("kind")
        op = operation.get("op")
        data = operation.get("data")
        if kind not in OPERATION_KINDS or op not in OPERATION_KINDS.get(kind, ()):
            raise FeatureError(f"operation {index}: unknown kind/op {kind!r}/{op!r}")
        if not isinstance(data, dict):
            raise FeatureError(f"operation {index}: data must be an object")

        if kind in ("node", "relation", "claim"):
            names = {"node": ("nodes", "FN"), "relation": ("relations", "FR"), "claim": ("claims", "FC")}
            collection, prefix = names[kind]
            items = fm["model"][collection]
            if op in ("remove", "withdraw"):
                find(items, data.get("id", "")).update({"tombstoned": True})
                applied.append(f"{op} {data['id']}")
                continue
            item = dict(data)
            if item.get("id"):
                existing = find(items, item["id"])
                existing.update(item)
                applied.append(f"update {item['id']}")
            else:
                item["id"] = allocate_id(fm, prefix)
                items.append(item)
                applied.append(f"add {item['id']}")
        elif kind == "binding":
            if op == "unbind":
                find(fm["artifactBindings"], data.get("id", "")).update({"tombstoned": True})
                applied.append(f"unbind {data['id']}")
                continue
            entry_id = data.get("entryId") or ""
            receipt = binding_resolver(entry_id)  # raises unless approved-current
            binding = {
                "id": allocate_id(fm, "FB"),
                "entryId": entry_id,
                "reviewedContentDigest": receipt["reviewedContentDigest"],
                "factsDigest": receipt["factsDigest"],
                "sourceTreeDigest": receipt["sourceTreeDigest"],
                "profile": receipt["profile"],
            }
            if data.get("sections"):
                binding["sections"] = list(data["sections"])[:10]
            fm["artifactBindings"].append(binding)
            applied.append(f"bind {binding['id']} -> {entry_id}")
        elif kind == "section":
            name = data.get("name")
            text = str(data.get("text") or "")
            if name not in BODY_SECTIONS:
                raise FeatureError(f"operation {index}: unknown narrative section {name!r}")
            if len(text) > MAX_SECTION_CHARS:
                raise FeatureError(f"operation {index}: section text exceeds {MAX_SECTION_CHARS} chars")
            new_body = _replace_section(new_body, fm["subject"]["name"], name, text)
            applied.append(f"replace section {name}")
        elif kind == "meta":
            if op == "add-question":
                question = {"id": allocate_id(fm, "FQ"), "question": str(data.get("question") or "")}
                if not question["question"]:
                    raise FeatureError(f"operation {index}: a question requires text")
                fm["model"]["unresolved"].append(question)
                applied.append(f"add {question['id']}")
            elif op == "resolve-question":
                find(fm["model"]["unresolved"], data.get("id", ""))["resolution"] = str(
                    data.get("resolution") or ""
                )
                applied.append(f"resolve {data['id']}")
            else:
                if data.get("name"):
                    fm["subject"]["name"] = str(data["name"])
                if data.get("entryPoints") is not None:
                    fm["model"]["entryPoints"] = data["entryPoints"]
                for key in ("limitations", "keywords", "candidateKeywords"):
                    if data.get(key) is not None:
                        fm[key] = data[key]
                if data.get("sensitivity"):
                    fm["sensitivity"] = data["sensitivity"]
                applied.append("set meta")

    # Whole-batch closure: schema must hold after apply (narrative gaps are allowed in a
    # draft; broken references are not).
    problems = [
        p for p in validate_feature(fm, new_body)
        if "sentinel" not in p and "core narrative" not in p
    ]
    if problems:
        raise FeatureError("batch rejected: " + "; ".join(problems[:5]))
    fm["draft"]["version"] = int(fm["draft"]["version"]) + 1
    fm["lifecycle"]["state"] = "draft"
    fm["approval"] = {"reviewedContentDigest": None, "reviewedBy": None, "reviewedAt": None, "mechanism": None}
    return fm, new_body, applied


def _replace_section(body: str, title: str, name: str, text: str) -> str:
    sections = _body_sections(body)
    sections[name] = text
    ordered = [section for section in BODY_SECTIONS if section in sections]
    lines = [f"# {title}", ""]
    for section in ordered:
        lines += [f"## {section}", "", sections[section].strip() or FEATURE_SENTINEL, ""]
    return "\n".join(lines).rstrip() + "\n"


def new_feature_frontmatter(slug: str, name: str) -> dict[str, Any]:
    feature_identity(slug)
    return {
        "schemaVersion": 2,
        "kind": "feature-knowledge",
        "subject": {"slug": slug, "name": name},
        "vocabVersion": VOCAB_VERSION,
        "model": {"nodes": [], "relations": [], "entryPoints": [], "claims": [], "unresolved": []},
        "artifactBindings": [],
        "limitations": [],
        "keywords": [],
        "candidateKeywords": [],
        "sensitivity": "internal-sanitized",
        "draft": {"version": 0, "idCounters": {}},
        "lifecycle": {"state": "draft"},
        "approval": {"reviewedContentDigest": None, "reviewedBy": None, "reviewedAt": None, "mechanism": None},
    }


def initial_body(name: str) -> str:
    return (
        f"# {name}\n\n"
        f"## Purpose and boundary\n\n{FEATURE_SENTINEL}\n\n"
        f"## Domain and data model\n\n{FEATURE_SENTINEL}\n\n"
        f"## Evidence map\n\n{FEATURE_SENTINEL}\n"
    )
