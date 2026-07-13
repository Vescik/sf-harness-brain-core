---
name: update-knowledge-base
description: Govern proposed Salesforce/package claims, immutable evidence, human reviews, lifecycle transitions, reconciliation, and generated Knowledge indexes. Never promote model inference or unreviewed observations.
user-invocable: false
---

# Govern the Knowledge base

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md), and
[source authority contract](../../../.ai/contracts/source-authority.md).

## Input

Require a schema-valid claim/evidence/review operation with stable IDs, normalized
`(subject, predicate, scope)`, source authority, scope lineage, timestamps, sensitivity,
limitations, and expected revision. Reject raw records, secrets/PII, rules disguised as facts,
model-only evidence, mutable evidence, or unknown fields.

## Procedure

1. Validate schemas and apply the claim-type evidence/freshness policy.
2. Search canonical claims using normalized subject, predicate, scope, environment, package version,
   repository lineage, aliases, and related claims.
3. Evidence is immutable. Corrections create a new evidence record and retain history.
4. Investigators/models may create `proposed` only. Prepare sanitized schema-v3 claim/evidence
   drafts under `.cache/knowledge-proposals/`, then run the guarded `propose` command; it is the
   only agent path that writes canonical Knowledge. `verified`, `rejected`, `contested`,
   `superseded`, and re-verification require the lifecycle transition and human review defined by
   policy. A human cannot make unsupported evidence true.
5. A different value in the same normalized scope marks the claim contested; never overwrite.
   Different environments/package versions may retain parallel claims.
6. Re-read target revisions immediately before the atomic operation; stop on concurrency drift.
7. Regenerate human-readable domain indexes deterministically from canonical claims. Unreviewed,
   stale, contested, rejected, and superseded states remain visible but are never presented as
   trusted current facts.
8. Append claim/evidence/review references to the relevant work record and retain audit history.

## Return

Return `PROPOSED`, `VERIFIED`, `REJECTED`, `CONTESTED`, `STALE`, `SUPERSEDED`, `DUPLICATE`, or
`INVALID`; IDs/revisions; transition/review; source authority; freshness; files changed; index
status; conflicts; and recovery action. Never return `VERIFIED` without a valid human review.
