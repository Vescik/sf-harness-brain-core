"""The reference-kind vocabulary, and the one rule that derives an edge's assurance from it.

This is a leaf module: it imports nothing but the standard library, so anything that needs the
vocabulary can have it without paying for the 6.5k-line collector. That matters twice over.

The collector (`scripts/force_app_knowledge.py`) re-exports every set defined here, so callers
and `tests/test_kind_contract.py` keep reading `force_app_knowledge.OBJECT_REF_KINDS` unchanged.
`scripts/knowledge_store.py` imports `edge_assurance` to stamp entries. `scripts/knowledge_search.py`
imports this module only so `code_fingerprint()` can digest it: a change to the vocabulary changes
what entries assert, so it has to invalidate the search index the same way editing the projector
does. Fingerprinting the collector instead would turn every extractor edit into a full
reprojection of the corpus.

`edge_assurance` lives here rather than in the store because assurance is a pure function of the
vocabulary: a kind is heuristic or it is not. Keeping the rule beside the set it reads is what
stops the store and the index from ever disagreeing about the same edge.
"""

from __future__ import annotations

SOURCE_EXACT = "source-exact"
SOURCE_DERIVED_HEURISTIC = "source-derived-heuristic"

# Reference kinds whose target names an object (its head token before any `.field`). Used by the
# feature crawl to associate an automation/UI component with the objects it touches. subflow,
# action, apex-method, apex-controller, invokes-apex, invokes-class, and related-list targets name
# automations/methods/related lists, not objects.
OBJECT_REF_KINDS = frozenset(
    {
        "relationship",
        "operates-on",
        # Containment, child side only: "this artifact is declared inside that object". The
        # parent side is derived by inverting this in the search index — knowing an object's
        # children requires reading every other artifact, which no single entry may assert.
        # Emitted in addition to `operates-on`, never instead of it: that kind means the owning
        # object for a ValidationRule/RecordType/ApexTrigger but the *summarised child* object
        # on a rollup CustomField, so it cannot carry containment.
        "belongs-to",
        "object-token",
        "schema",
        "reads-field",
        "writes-field",
        "references-field",
        "places-field",
        "grants-field-permission",
        "queries-object",
        "dml-object",
        "grants-object-permission",
        "soql-field",
        "var-field-ref",
        "filters-field",
        "picklist-dependency",
        "grants-field-read",
        "grants-field-edit",
        "grants-object-view-all",
        "grants-object-modify-all",
        "serves-object",
    }
)
# Reference kinds derived via regex source-token heuristics rather than structural XML/JS parsing
# (Apex object tokens and invoked-class names). Best-effort: dynamic references and unresolved
# variable types may be missing or approximate. Drives component-relation claims' heuristic flag
# and assurance level. Kinds emitted both structurally and heuristically (queries-object from Flow
# XML vs Apex SOQL regex) are not listed here — those references carry a per-edge heuristic flag.
HEURISTIC_REF_KINDS = frozenset(
    {
        "object-token",
        "invokes-class",
        "soql-field",
        "var-field-ref",
        "callout-endpoint",
        # FlexiPage flow wiring is detected by property-name pattern (flowName/flowApiName).
        "launches-flow",
    }
)
# Canonical vocabulary of every reference kind this extractor can emit
# (force_app_knowledge.ALL_REF_KINDS is derived from it).
ALL_REF_KINDS = OBJECT_REF_KINDS | frozenset(
    {
        "subflow",
        "action",
        "apex-method",
        "apex-controller",
        "invokes-apex",
        "invokes-class",
        "related-list",
        "uses-value-set",
        "sends-alert",
        "uses-template",
        "uses-named-credential",
        "callout-endpoint",
        "uses-workflow-action",
        "uses-business-process",
        "uses-matching-rule",
        "uses-label",
        "embeds-component",
        "displays-component",
        "launches-flow",
        "overrides-view",
        "grants-class-access",
        "grants-custom-permission",
        "grants-record-type",
        "grants-flow-access",
        "grants-user-permission",
        "assigns-layout",
        "shares-with",
        "assigns-to",
        "uses-external-credential",
        "references-auth-provider",
        "grants-to-profile",
        "grants-to-permission-set",
        "references-custom-permission",
        "includes-permission-set",
        "mutes-permission-set",
        "reports-to",
    }
)


def edge_assurance(kind: str, heuristic_flag: bool = False) -> str:
    """How much an edge of this kind can be trusted.

    An edge is heuristic if its KIND is regex-derived, or if the collector flagged that particular
    reference (some kinds — `queries-object` — are structural from Flow XML and heuristic from an
    Apex SOQL regex, so the flag carries what the kind cannot).

    Reading only the per-edge flag was the bug: the collector never sets it for kind-level
    heuristics, so 414 of 595 edges in a 189-component probe corpus were stored `source-exact`.
    That marker is inside factsDigest, so a human approved it, and SAFE-CLAIM-001 v2 would then
    ground a work record on what is really a regex match against a comment.
    """

    if heuristic_flag or kind in HEURISTIC_REF_KINDS:
        return SOURCE_DERIVED_HEURISTIC
    return SOURCE_EXACT
