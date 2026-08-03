---
name: investigate-config-records
description: Take a bounded, sanitized snapshot of the configuration records held in one allowlisted reference-data object (statuses, settings, config tables) and report it read-only. Use when package behavior is driven by org records rather than metadata.
user-invocable: false
---

# Investigate configuration records in a reference-data object

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[source authority contract](../../../.ai/contracts/source-authority.md). Run
`python scripts/preflight.py --capability salesforce-review`.

Authority basis: per the grounding architecture, a reference-data snapshot is eligible only
through a bounded current org observation — these values live in records, not in source files, so
the metadata repository has no authority here. This skill is the deliberate reference-data
exception to the record-persistence prohibition in
[investigate-object](../investigate-object/SKILL.md): it persists only the sanitized
configuration-bearing values of one human-allowlisted object; everything that skill otherwise
forbids (Ids, URLs, audit fields, free text, unscoped business data) stays forbidden here.
The outcome is a snapshot REPORT under `output/` (owner decision D-A, 2026-08-03, v1
retirement): reference-data snapshots are documentation with a recorded digest and observation
time, not citable Knowledge; record data drifts without any repository signal, so a snapshot
must be re-observed, never re-read from an old report.

## Input

Require exactly one `objectApiName` and one `org` — a configured review-org alias (enumerable via
`python scripts/salesforce_read.py orgs`); there is no default alias. The object must be on
`salesforce.review.allowedObjectApiNames`; if it is not, stop and report the missing allowlist
entry instead of widening scope. Optional: `fields` (must remain a subset of the reviewed field
contract), `recordId` (work record to attach evidence to). Reject a generic "dump the org",
multiple objects in one call, or an object that is transactional rather than reference data — a
snapshot that fills the row cap is treated as transactional and returned unresolved.

## Procedure

1. Check existing Knowledge for the object's source-declared shape — its fields, record types
   and validation rules — with
   `python scripts/knowledge_search.py context --identity CustomObject:<ns|c>:<Object>`. Read
   the shape from `parts`, `permissions` and `incoming` — the approved-current buckets; the
   `*NonCurrent` siblings hold opted-in lanes and must not be treated as the object's declared
   shape. `incoming` and `outgoing` are keyed by relation kind, so iterate the keys, and never
   read a missing kind as an absence proof. A row with `hydrated: false` failed re-reading and
   is not part of the object's declared shape. Cite what the executor gives you, not what the
   view shows: obtain the citable ref with
   `python scripts/knowledge_store.py entry-status --identity <Identity>`; the `context` pack
   is never itself citable, and Apex-layer entries generally cannot be cited as positive
   grounding at all (contract §8.1 grounds only `source-exact`, fully covered sections).
2. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured org with `nonProduction: true` (a Developer Edition legitimately reports `isSandbox: false`).
3. Call `review_object_contract` for the object's accessible field contract. Choose the snapshot
   fields from that contract only: the natural key (`Name`, a `DeveloperName`-like field, or an
   external-id field) plus the configuration-bearing fields (status values, flags, ordering,
   defaults). Exclude record Ids, audit fields (`CreatedBy`, `LastModifiedBy`, timestamps), owner
   fields, and free-text/long-text fields.
4. Read records only through the guarded facade, passing every flag explicitly — omitting
   `--fields` silently defaults to `Id`, which must never be persisted:
   `python scripts/salesforce_read.py records --org <alias> --object <objectApiName>
   --fields <field,list> --order-by <naturalKey> --limit 200`.
   200 is the facade's hard cap (its silent default is 50); `--order-by` on the natural key makes
   the snapshot deterministic and digestable.
5. Sanitize each returned row before any other use: drop the `attributes` key (its `url` embeds
   the record Id) and any value outside the requested field list, keeping `--order-by` order.
6. Assess completeness. If the returned row count equals the limit, enumeration is not proven
   complete: record `enumerationComplete: false`, assert no absence, and return `UNRESOLVED` —
   the object is transactional-sized, not a config table. Never treat a missing row as proof a
   config value does not exist.
7. Build the snapshot: object identity, the natural-key-ordered sanitized record list, row
   count, and `contentDigest` = `sha256:<64 hex>` over the canonical JSON (sorted keys, compact
   separators) of the ordered sanitized rows. Identity convention for records inside the
   snapshot: `<ObjectApiName>.<NaturalKey>` (mirrors the `Type__mdt.Record` CustomMetadata
   convention).
8. Write the snapshot report under `output/` (e.g.
   `output/reference-data/<objectApiName>-<orgKey>.md`): scope (exact `environment`, `orgKey`,
   namespace prefix), `observedAt`/`retrievedAt`, the sanitized rows, the completeness block,
   the `contentDigest`, a `sanitization` note naming the stripped surfaces, and limitations —
   above all that the values drift without any repository signal and expire with the org's
   refresh cadence.
9. When the caller provided `recordId`, attach the snapshot as work-record evidence with
   `python scripts/work_record.py append-evidence --record-id <ID> ...` (the report file is the
   artifact); otherwise the investigation is a standalone read.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, SOSL, a Tooling flag, or an unguarded Salesforce
  MCP tool; snapshot records flow only through `salesforce_read.py records`. Composed read-only
  SOQL (owner decision 2026-07-30) runs through the governed `review_soql_query` facade tool —
  useful for scoping (counts, distributions) before a snapshot; the snapshot rows themselves stay
  on the `salesforce_read.py records` lane.
- Never exceed the 200-row or configured field caps, chain calls to paginate past them, or
  snapshot more than one object per invocation.
- Never persist credentials, usernames, record Ids, URLs, `attributes` payloads, owner/audit
  values, or free-text business content; snapshot values are limited to the configuration-bearing
  fields the human scoped via the allowlist.
- Never call a snapshot `confirmed` or `verified`, and never present the report as citable
  Knowledge — later work cites approved entries and unexpired org-usage blocks, or re-observes.

## Return

Return `EVIDENCE COLLECTED` or `UNRESOLVED`; `recordId` when provided; the report path; exact
scope; row count and `enumerationComplete`; the content digest; limitations; and what a human
should verify next. No mutation of Salesforce is permitted.
