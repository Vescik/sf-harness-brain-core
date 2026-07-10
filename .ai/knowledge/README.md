# Knowledge Index

Knowledge uses the schema-v2 lifecycle in
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
| [keyword-taxonomy.md](keyword-taxonomy.md) | Separately curated vocabulary; terms are not factual evidence. |

## Retrieval rule

Treat a claim as established only when it is `verified`, within `reviewBy`, in matching scope,
supported by applicable evidence, and free of unresolved contradiction. Proposed, stale,
contested, superseded, or rejected claims may be shown as warnings but may not support a `SAFE`
verdict. Existing Knowledge and generated indexes never corroborate themselves.

This repository intentionally contains no organization or package facts until real, sanitized
evidence is reviewed. Never seed examples into the live index.
