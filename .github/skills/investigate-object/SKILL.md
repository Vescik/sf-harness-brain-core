---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence for a scoped Salesforce component or package claim and create a proposed Knowledge claim. Use for missing, stale, contested, or drift-sensitive facts; never self-verify a claim.
user-invocable: false
---

# Investigate a Salesforce component claim

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md), and
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md). Run
`python scripts/preflight.py --capability salesforce-review`.

## Input

Require the exact claim question/type, normalized package/component subject, environment,
criticality, minimum evidence policy, and why current Knowledge/repository evidence is insufficient.
`recordId` (the work record to attach evidence to) is required only when governed delivery work
raised the investigation; without one this is a standalone read, which is a valid lane and not a
reason to stop.
Reject a generic “inspect the org,” unspecified target, record dump, or component outside the
configured review allowlist. Route record data-shape questions (structure, fill, distributions)
to the governed record reads instead of rejecting them (owner decision 2026-07-30):
`review_soql_query` on the facade, `salesforce_read.py records`, or
`investigate-config-records`. When the finding should outlive the chat and the subject is a
wave-1 entry (CustomObject, CustomField), persist it instead of quoting transcript numbers:
compose the probes and run the governed `python scripts/knowledge_store.py entry-org-attach`
per the batch-knowledge skill's entry-lane org-sampling step — an expired or superseded org
block is absent for grounding, and a persisted design may cite only unexpired org numbers with
their orgKey and observedAt.

## Procedure

1. Validate the work record when one was provided, then read relevant verified Knowledge plus
   metadata-repository state.
2. Classify the source authority required. A package guarantee needs a vendor source; business
   meaning needs reviewed human evidence; live deployed configuration may use org observation.
3. Define the smallest factual proposition. For a negative claim, require completeness, permission,
   pagination, and freshness proof before absence is eligible.
4. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured org with `nonProduction: true` (a Developer Edition legitimately reports `isSandbox: false`).
5. Call only the necessary guarded review tool:
   - `review_installed_packages` for package identity/version;
   - `review_object_contract` for an allowlisted object's accessible existence/field contract.
6. Treat MCP/CLI agreement as transport corroboration. On `MISMATCH`, `INCOMPLETE`, truncation,
   schema drift, sensitive-output detection, or scope mismatch, return unresolved and do not promote.
7. Create immutable sanitized evidence and one `proposed` claim through the governed Knowledge
   command; the [knowledge-entry template](../../../.ai/templates/knowledge-entry.md) is the
   human-facing companion to the claim schema. Record limitations, repository drift, package
   version, and missing authority.
8. When the caller provided `recordId`, append evidence references to that work record. Human
   review is a separate operation.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, SOSL, an alias, a directory, a Tooling flag, broad
  record retrieval, or an unguarded Salesforce MCP tool; composed read-only SOQL runs only
  through the governed facade's `review_soql_query` tool — never through raw CLI or raw vendor
  tools.
- Never infer inaccessible package internals or treat no returned row/component as proof of absence.
- Never return or persist credentials, usernames, raw org/package/record IDs, URLs, raw vendor
  payloads, labels/help text, picklist values, or unnecessary business data. For configuration
  values held as records in a reference-data table, use the governed exception
  [investigate-config-records](../investigate-config-records/SKILL.md) instead.
- Never call a proposed observation `confirmed` or `verified`.

## Return

Return `EVIDENCE COLLECTED`, `INFERRED`, or `UNRESOLVED`; `recordId` when provided; `claimId`; `evidenceId`
values; exact scope; source/reconciliation status; repository drift; limitations; missing authority;
and required human review. No mutation of Salesforce is permitted.
