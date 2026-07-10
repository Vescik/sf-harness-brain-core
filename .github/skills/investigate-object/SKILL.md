---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence for a scoped Salesforce component or package claim and create a proposed Knowledge claim. Use for missing, stale, contested, or drift-sensitive facts; never self-verify a claim.
user-invocable: false
---

# Investigate a Salesforce component claim

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md), and
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md). Run
`scripts/preflight.py --capability salesforce-review`.

## Input

Require `recordId`, exact claim question/type, normalized package/component subject, environment,
criticality, minimum evidence policy, and why current Knowledge/repository evidence is insufficient.
Reject a generic “inspect the org,” unspecified target, arbitrary query, record dump, or component
outside the configured review allowlist.

## Procedure

1. Validate the work record and read relevant verified Knowledge plus metadata-repository state.
2. Classify the source authority required. A package guarantee needs a vendor source; business
   meaning needs reviewed human evidence; live deployed configuration may use org observation.
3. Define the smallest factual proposition. For a negative claim, require completeness, permission,
   pagination, and freshness proof before absence is eligible.
4. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured sandbox.
5. Call only the necessary guarded review tool:
   - `review_installed_packages` for package identity/version;
   - `review_object_contract` for an allowlisted object's accessible existence/field contract.
6. Treat MCP/CLI agreement as transport corroboration. On `MISMATCH`, `INCOMPLETE`, truncation,
   schema drift, sensitive-output detection, or scope mismatch, return unresolved and do not promote.
7. Create immutable sanitized evidence and one `proposed` claim through the governed Knowledge
   command. Record limitations, repository drift, package version, and missing authority.
8. Append evidence references to the work record. Human review is a separate operation.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, arbitrary SOQL/SOSL, an alias, a directory, a Tooling
  flag, broad record retrieval, or an unguarded Salesforce MCP tool.
- Never infer inaccessible package internals or treat no returned row/component as proof of absence.
- Never return or persist credentials, usernames, raw org/package/record IDs, URLs, raw vendor
  payloads, labels/help text, picklist values, or unnecessary business data.
- Never call a proposed observation `confirmed` or `verified`.

## Return

Return `EVIDENCE COLLECTED`, `INFERRED`, or `UNRESOLVED`; `recordId`; `claimId`; `evidenceId`
values; exact scope; source/reconciliation status; repository drift; limitations; missing authority;
and required human review. No mutation of Salesforce is permitted.
