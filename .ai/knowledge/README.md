# Knowledge Index

Knowledge uses the schema-v3 lifecycle in
[`../contracts/knowledge-lifecycle.md`](../contracts/knowledge-lifecycle.md). Canonical records live
in three directories:

| Directory | Authority |
|---|---|
| [`claims/`](claims/) | Scoped assertions and lifecycle state; validated by `schemas/knowledge-claim.schema.json`. |
| [`evidence/`](evidence/) | Immutable sanitized observation receipts; validated by `schemas/knowledge-evidence.schema.json`. |
| [`reviews/`](reviews/) | Immutable human promotion/reconciliation decisions; validated by `schemas/knowledge-review.schema.json`. |

The domain files below are generated, human-readable indexes. They are not sources of truth and
must not be hand-edited with factual entries.

| Domain view | Indexed claims |
|---|---|
| [current-implementation.md](current-implementation.md) | Current implementation, package installation, and scoped runtime behavior. |
| [business-processes.md](business-processes.md) | Business processes and system mappings. |
| [object-relations.md](object-relations.md) | Verified object and reference-data relations. |
| [object-descriptions.md](object-descriptions.md) | Object existence, ownership, and meaning. |
| [field-descriptions.md](field-descriptions.md) | Field schema and approved business meaning. |
| [automation-map.md](automation-map.md) | Scoped, complete automation inventory claims. |
| [integration-map.md](integration-map.md) | External-system and data-flow claims. |
| [glossary.md](glossary.md) | Approved business-to-technical terms. |
| [known-limitations.md](known-limitations.md) | Version-scoped package limitation claims. |
| [component-inventory.md](component-inventory.md) | Generic source-component claims for every other metadata type (layouts, permission sets, custom metadata, bundles, …). |
| [feature-map.md](feature-map.md) | Generated view grouping canonical claims by feature-membership tag (written by the feature documentor). |
| [claims-index.json](claims-index.json) | Machine-readable index of every canonical claim (status, keywords, description excerpt, and `usesObjects`/`usesFields` dependency summary) for search and duplicate lookup; only rows with `effective: true` are established facts. Validated by `schemas/knowledge-claims-index.schema.json`. Query the usage registry with `knowledge_registry.py query --uses-object/--uses-field/--invokes`; the `automation-map.md` view carries an "Automations by object" reverse index. |
| [keyword-taxonomy.md](keyword-taxonomy.md) | Separately curated vocabulary; terms are not factual evidence. |

## Retrieval rule

Treat a claim as established only when it is `verified`, within `reviewBy`, in matching scope,
supported by applicable evidence, and free of unresolved contradiction. Proposed, stale,
contested, superseded, or rejected claims may be shown as warnings but may not support a `SAFE`
verdict. Existing Knowledge and generated indexes never corroborate themselves.

This repository intentionally contains no organization or package facts until real, sanitized
evidence is reviewed. Never seed examples into the live index.

## Retrieval before build/test/document

Consuming workflows (solution design, technical documentation, test-case suggestion, feature
coverage, principle checks) query the registry for the components they touch — by subject and by the
usage registry — and cite effective claims or record an explicit gap; an empty base is never a
license to answer from model memory. Route retrieval through the
[`search-knowledge`](../../.github/skills/search-knowledge/SKILL.md) skill.

## Health & maintenance (read-only, advisory)

These deterministic reports surface coverage and validity without mutating any claim — transitioning
a claim to `stale` stays a governed human review.

| Command | Purpose |
|---|---|
| `python scripts/force_app_knowledge.py coverage` | Documentation coverage of the force-app source: documented / proposed / undocumented / drifted counts per metadata type plus a prioritised "document next" list (reuses the worklist's status + source-drift engine). |
| `python scripts/knowledge_registry.py stale-report [--warn-days N]` | Verified claims already past `reviewBy` (`expired`, no longer effective) or within `N` days of it (`expiring`), so re-verification can be scheduled. |
| `python scripts/knowledge_registry.py verify-citations --envelope <path>` | Checks a handoff/output envelope's cited `claimRefs` against current canonical state: `ok`, `missing`, `revision-mismatch`, `sha-mismatch`, or `not-effective` (stale/contested/superseded/rejected). |
