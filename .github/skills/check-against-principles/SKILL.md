---
name: check-against-principles
description: Evaluate a scoped design or implementation using the governed rule registry, approved Knowledge Entries, repository/org reconciliation, approval hashes, and complete evidence. Read-only; never implement fixes.
user-invocable: false
---

# Check against Principles and evidence

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md),
[workflow state machine](../../../.ai/contracts/workflow-state-machine.md).

## Inputs

Require a valid `recordId`, optional incoming `handoffId`, exact proposed/implemented scope,
repository revisions/diff, environment proof, rule/entry references, current package
identity when applicable, and accepted design/approval hashes. Reject unspecified or chat-only scope.

## Procedure

1. Validate work state, handoff target/revision, approval binding, and affected-artifact list.
2. Load the governed rule registry and check Tier 1 package constraints, Tier 2 organization policy,
   and Tier 3 Salesforce practice in order. Apply precedence only to competing prescriptions.
3. Discover, then require. First establish the baseline of facts the design must address — do not
   rely only on what the author happened to cite. Query both layers:
   - the `knowledge_context` tool for each affected
     artifact (source-declared facts, parts, dependents, permission grants, in one call;
     `knowledge_resolve` maps bare names and paths to identities). Only
     `parts`, `permissions` and `incoming` are approved-current; the `partsNonCurrent` /
     `permissionsNonCurrent` / `incomingNonCurrent` siblings are opted-in lanes and can never
     make a premise `verified`. `incoming` and `outgoing` are keyed by relation kind, so iterate
     the keys rather than a flat list, and treat an absent kind as silence, not as absence. A row
     carrying `hydrated: false` failed re-reading, so it can never make a premise `verified` —
     record it as a gap;
   - the `knowledge_search` tool with a `relationAnchor` and `direction: incoming`
     for dependents beyond the context pack's depth-1 view. Only generic-bucket
     types (Settings, Letterhead, Group and similar label-only extraction) have no entry and
     no governed dependency lookup — name them explicitly when present, or the result looks
     clean while a whole class went unchecked.
   An empty result from either layer is a recorded gap, never proof that nothing depends on it. Then, for every material factual premise,
   require an `approved-current`, scope-matched entry (or an unexpired org-usage block for
   usage numbers). Drafts and model inference are not trusted facts. When a cited envelope
   carries entry references, `python scripts/knowledge_store.py entry-verify-citations
   --envelope <path>` reports any that no longer resolve to a current approved entry.
4. Compare intended customer-owned repository state with the latest complete org-review evidence.
   Report drift instead of selecting one source.
5. Distinguish an observed fact that violates a Principle from evidence that contests a factual
   entry. Principles do not rewrite facts; observations do not weaken rules.
6. Require complete environment proof, package/component ownership, version, supported extension
   point, role compliance, verification, coverage, and manual steps where relevant.
7. A drifted/revoked/partial entry, incomplete org review, ungrounded component, missing
   source/version, stale approval, or unresolved blocking question makes `SAFE` impossible.

## Output

Return a table with: tier, rule ID, entry identities, affected artifact, scope/freshness,
reconciliation, finding, and required action. End with exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State `recordId`, evidence completeness, repository/org drift, and that nothing was changed.

## Knowledge grounding: two layers

Query both layers through [search-knowledge](../search-knowledge/SKILL.md) and keep their
authorities apart. Approved one-file Knowledge Entries ground intended repository-source facts
(what a component declares, what touches a field) and are cited as `entryRef` with the entry
path and digests. Org usage is grounded only by an unexpired entry `orgUsage` block, cited
with its orgKey and observedAt; runtime behavior, business meaning, and vendor guarantees have
no governed Knowledge surface — mark them `UNVERIFIED` with their source instead of citing
the entry. Absence, deployed state, and semantics are never grounded by an entry, and a missing
search hit is never proof of absence.

Cite what the executor gives you, not what the view shows: obtain the citable ref with
the `knowledge_entry_status` tool. A search result, a
`context` pack and a generated dossier are never themselves citable.

An entry can be approved, current and still refuse to ground a fact: contract §8.1 grounds only
sections marked `source-exact` with full coverage, and the executor enforces that when the
`entryRef` is bound. **Apex-layer entries generally cannot be cited as positive grounding** —
their facts are regex-derived and honestly marked heuristic. Measured on the 189-component
reference package: 48 of 52 ApexClass, 5 of 5 ApexTrigger, 3 of 93 CustomField and 2 of 2
ValidationRule entries are refused. Read them for orientation, report the fact as inferred, and
report the fact as ungrounded instead. The refusal is the contract working, not a tooling
failure — never retry it with a different ref shape.
