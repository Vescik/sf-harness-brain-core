---
description: General Salesforce engineering and evidence practices for Apex, Flow, security, limits, testing, metadata, and source/org reconciliation. Load explicitly after Tier 1 and Tier 2.
---

# Salesforce Best Practices — Tier 3

These rules apply only when they do not conflict with Tier 1 or Tier 2.

- **SF-BULK-001 — bulkify.** No SOQL or DML in loops. Design Apex, triggers, and Flows for bulk
  transactions and collection processing.
- **SF-LIMIT-001 — budgets are explicit.** Review SOQL, DML, CPU, heap, async, and Flow limits for
  every automation path; call out limit assumptions in the design.
- **SF-TRIG-001 — one trigger entry point.** Use one trigger per object with logic delegated to a
  handler/service boundary. Prevent recursion intentionally.
- **SF-SEC-001 — enforce access.** Declare sharing deliberately and enforce object, field, and
  record access using the platform mechanism appropriate to the execution context. Never rely on
  UI visibility as authorization.
- **SF-SOQL-001 — prevent injection.** Bind values, allowlist dynamic identifiers, and avoid
  constructing SOQL from untrusted ADO, record, browser, or user content.
- **SF-AUTO-001 — choose automation deliberately.** Document why Flow, Apex, or another mechanism
  fits transactionality, volume, error handling, observability, and package constraints.
- **SF-NAME-001 — generic fallback naming.** Use descriptive `PascalCase` Apex/type names and
  Salesforce-style underscore-separated custom metadata API names. Organization naming remains
  authoritative when supplied.
- **SF-TEST-001 — assert behavior.** Use isolated test data, `@TestSetup` where useful, no
  `SeeAllData=true`, positive/negative/bulk cases, and assertions on outcomes rather than coverage.
- **SF-ERR-001 — observable failures.** Preserve actionable error context without exposing
  secrets or sensitive record data. Avoid silent catch blocks and swallowed Flow faults.
- **SF-META-001 — source and manifest agree.** Validate referenced metadata exists, preserve API
  versions intentionally, and report missing/decomposed components rather than omitting them.
- **SF-EVID-001 — intended and deployed state are distinct.** Treat the source-controlled metadata
  commit as intended customer-owned state and the allowlisted org as deployed state at an observed
  time. Report drift; do not declare either universally authoritative.
- **SF-EVID-002 — read the minimum surface, and persist less than you read.** Org review uses
  schema-first, bounded, allowlisted reads with an explicit API version, row/field caps, stated
  permission limitations and pagination. Read and persistence are separate policies and must not
  be conflated: a composed `review_soql_query` result returns record rows **unredacted and
  unsanitized** in band (owner decision 2026-08-04) so an unusual configuration can actually be
  understood. Sanitization happens on the way to *durable* state — the Design Case runtime
  imports the result by its content-addressed reference and derives counts, distributions,
  shapes and digests through the shared derivation library. Persisting record values is the one
  governed exception (`config-snapshot`) and requires an explicit safe-field allowlist; ids,
  audit columns, non-scalars and sensitive-looking fields are withheld with their digest even
  then. Do not retrieve broad business records to answer a metadata question, and never paste
  raw rows into a design, an entry or an ADO artifact.
- **SF-EVID-003 — absence needs completeness.** A claim that a field, automation, dependency, or
  record does not exist requires complete enumeration within the proven permission and API scope.
  Empty or inaccessible results remain `UNRESOLVED`.
- **SF-EVID-004 — tools report observations, not meaning.** Salesforce labels, descriptions, and
  record values may support an investigation but do not establish business semantics without a
  reviewed organization source.
