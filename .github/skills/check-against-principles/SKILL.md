---
name: check-against-principles
description: Evaluate a scoped design or implementation using the governed rule registry, fresh verified claims, repository/org reconciliation, approval hashes, and complete evidence. Read-only; never implement fixes.
user-invocable: false
---

# Check against Principles and evidence

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md), and
[workflow state machine](../../../.ai/contracts/workflow-state-machine.md).

## Inputs

Require a valid `recordId`, optional incoming `handoffId`, exact proposed/implemented scope,
repository revisions/diff, environment proof, rule/claim/evidence references, current package
identity when applicable, and accepted design/approval hashes. Reject unspecified or chat-only scope.

## Procedure

1. Validate work state, handoff target/revision, approval binding, and affected-artifact list.
2. Load the governed rule registry and check Tier 1 package constraints, Tier 2 organization policy,
   and Tier 3 Salesforce practice in order. Apply precedence only to competing prescriptions.
3. Discover, then require. First query Knowledge for each affected artifact
   (`python scripts/knowledge_registry.py query --subject-identity <ApiName>`, and `--uses-object` /
   `--uses-field` for dependents) to establish the baseline of verified facts the design must address —
   do not rely only on what the author happened to cite. Then, for every material factual premise,
   require a `verified`, fresh, scope-matched, uncontested claim backed by the claim-type evidence
   policy. Proposals and model inference are not trusted facts. When a cited handoff carries claim
   references, `python scripts/knowledge_registry.py verify-citations --envelope <path>` reports any
   that no longer resolve to an effective claim.
4. Compare intended customer-owned repository state with the latest complete org-review evidence.
   Report drift instead of selecting one source.
5. Distinguish an observed fact that violates a Principle from evidence that contests a factual
   claim. Principles do not rewrite facts; observations do not weaken rules.
6. Require complete environment proof, package/component ownership, version, supported extension
   point, role compliance, verification, coverage, and manual steps where relevant.
7. A stale/unreviewed/partial/contested claim, incomplete org review, unknown ownership, missing
   source/version, stale approval, or unresolved blocking question makes `SAFE` impossible.

## Output

Return a table with: tier, rule ID, claim/evidence IDs, affected artifact, scope/freshness,
reconciliation, finding, and required action. End with exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State `recordId`, evidence completeness, repository/org drift, and that nothing was changed.
