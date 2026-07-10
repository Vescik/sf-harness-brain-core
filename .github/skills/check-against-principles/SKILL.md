---
name: check-against-principles
description: Evaluate a scoped Salesforce design or implementation against managed-package, organization, and platform rules with evidence completeness. Use during design or independent review; never use it to implement fixes.
user-invocable: false
---

# Check against principles

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

## Inputs

- Proposed change or implementation diff, affected artifacts, environment, and accepted design.
- Evidence sources with fetch/verification timestamps.
- Current package version when a package surface is affected.

Reject an unspecified scope or unproven non-production environment.

## Procedure

1. Build the affected-artifact list; do not review only the user's summary when a diff exists.
2. Check Tier 1 [Managed Package Constraints](../../instructions/managed-package-constraints.instructions.md)
   and relevant [Known Limitations](../../../.ai/knowledge/known-limitations.md).
3. Check Tier 2 [Organization Principles](../../instructions/organization-principles.instructions.md).
4. Check Tier 3 [Salesforce Best Practices](../../instructions/salesforce-best-practices.instructions.md).
5. Check evidence completeness, accepted-design alignment, environment proof, role boundaries,
   verification evidence, manual steps, and test coverage.
6. A relevant placeholder, stale/partial source, unknown ownership, missing package source/version,
   or missing acceptance makes `SAFE` impossible.

## Output

Return a table with: tier, rule ID, affected artifact, evidence, finding, required action. End with
exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State the evidence completeness and whether anything was changed (`none`; this skill is read-only).
