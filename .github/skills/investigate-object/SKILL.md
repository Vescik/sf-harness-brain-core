---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence about a scoped Salesforce component or package question, report it read-only, and persist org observations only through the governed entry-org-attach lane.
user-invocable: false
---

# Investigate a Salesforce component question

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[source authority contract](../../../.ai/contracts/source-authority.md). Run
`python scripts/preflight.py --capability salesforce-review`.

This is a read-only investigation lane (owner decision D-A, 2026-08-03, v1 retirement): the
outcome is a sanitized report, optionally persisted org-usage numbers via the governed
`entry-org-attach` executor. Nothing here creates citable Knowledge by itself — durable
repository facts live in one-file Knowledge Entries, and semantic org/vendor conclusions
belong in the report (or, when boundary-level, in a Feature Entry's human prose).

## Input

Require the exact question, normalized package/component subject, environment, criticality,
and why current Knowledge/repository evidence is insufficient.
`recordId` (the work record to attach evidence to) is required only when governed delivery work
raised the investigation; without one this is a standalone read, which is a valid lane and not a
reason to stop.
Reject a generic “inspect the org,” unspecified target, record dump, or component outside the
configured review allowlist. Route record data-shape questions (structure, fill, distributions)
to the governed record reads instead of rejecting them (owner decision 2026-07-30):
`review_soql_query` on the facade, or
[investigate-config-records](../investigate-config-records/SKILL.md).

## Procedure

1. Validate the work record when one was provided, then read relevant approved Knowledge
   Entries plus metadata-repository state (the `knowledge_context` tool;
   re-read any `hydrated: false` row from its entry file before relying on it).
2. Classify the source authority required. A package guarantee needs a vendor source; business
   meaning needs reviewed human evidence; live deployed configuration may use org observation.
3. Define the smallest factual proposition. For an absence question, require completeness,
   permission, pagination, and freshness proof before absence may even be reported — and report
   it as an observation with its enumeration bounds, never as proof.
4. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured org with `nonProduction: true` (a Developer Edition legitimately reports `isSandbox: false`).
5. Call only the necessary guarded review tool:
   - `review_installed_packages` for package identity/version;
   - `review_object_contract` for an allowlisted object's accessible existence/field contract.
6. Treat MCP/CLI agreement as transport corroboration. On `MISMATCH`, `INCOMPLETE`, truncation,
   schema drift, sensitive-output detection, or scope mismatch, return unresolved.
7. Write the sanitized findings as a report under `output/` (investigation reports are
   documentation, not Knowledge authority). Record limitations, repository drift, package
   version, and missing authority in the report itself.
8. When the finding should outlive the chat and the subject has an approved entry
   (CustomObject, CustomField), persist the numbers through the org-sampling step below
   instead of quoting transcript values.
9. When the caller provided `recordId`, append evidence references to that work record. Human
   review is a separate operation.

## Entry-lane org sampling (governed persistence)

When an org alias with allowAgentRead+allowAgentReview is configured and
`python scripts/preflight.py --capability salesforce-review` passes, org sampling is the
default persistence path for object/field usage numbers. For each target entry whose org lane
is not already `org-fresh` (recompute it with
the `knowledge_entry_status` tool — never from chat history):
compose read-only SOQL probes for the entry's object — aggregates (COUNT, GROUP BY, COUNT(field)
fill counts) plus one bounded row sample (explicit `LIMIT 25`, `ORDER BY CreatedDate DESC`,
at most 20 contract-derived columns; never select Id, Email-type, or long-text values — measure
their fill with aggregate probes instead). Several probes of one kind under different WHERE
criteria are legal and encouraged when data diversity depends on status or record type
(owner decision D-5', 2026-08-03). Write the probes-file under `.cache/org-usage/pending/`
(`{"probes": [{"label", "kind", "query"}]}`) and run
`python scripts/knowledge_store.py entry-org-attach --identity <id> --org <alias>
--probes-file <path>` — the executor re-runs every probe through the governed facade, derives
the closed count/shape vocabulary (row values never persist), and attaches click-free with the
machine attestation the owner approved as the instrument. When no org is configured or
containment refuses, skip silently and report `orgUsage: skipped (<reason>)`. An expired or
superseded org block is absent for grounding: re-attach or run a live probe, never cite it.
`entry-org-detach --identity <id> --org <alias> --rationale <text>` is the rollback.

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
- Never call an observation `confirmed` or `verified`, and never present the report as citable
  Knowledge — only approved entries and unexpired org-usage blocks ground later work.

## Return

Return `EVIDENCE COLLECTED`, `INFERRED`, or `UNRESOLVED`; `recordId` when provided; the report
path under `output/`; any entry identities with freshly attached org usage; exact scope;
source/reconciliation status; repository drift; limitations; missing authority; and what a
human should verify next. No mutation of Salesforce is permitted.
