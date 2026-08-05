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
the `review_configured_orgs` facade tool); there is no default alias. The object must be on
`salesforce.review.allowedObjectApiNames`; if it is not, stop and report the missing allowlist
entry instead of widening scope. Optional: `fields` (must remain a subset of the reviewed field
contract), `slice` (a predicate that bounds the snapshot to the configuration the design needs),
`recordId` (work record to attach evidence to). Reject a generic "dump the org" or multiple
objects in one call.

**Row count is not a classification.** A configuration table with thousands of rows is still
configuration, and a small table is not automatically reference data. Classify from what the
records *do* — are they read by branching logic, do they carry active/default/priority flags or
effective windows, who maintains them — not from how many there are.

## Procedure

1. Check existing Knowledge for the object's source-declared shape — its fields, record types
   and validation rules — with
   the `knowledge_context` tool (identity `CustomObject:<ns|c>:<Object>`). Read
   the shape from `parts`, `permissions` and `incoming` — the approved-current buckets; the
   `*NonCurrent` siblings hold opted-in lanes and must not be treated as the object's declared
   shape. `incoming` and `outgoing` are keyed by relation kind, so iterate the keys, and never
   read a missing kind as an absence proof. A row with `hydrated: false` failed re-reading and
   is not part of the object's declared shape. Cite what the executor gives you, not what the
   view shows: obtain the citable ref with
   the `knowledge_entry_status` tool; the `context` pack
   is never itself citable, and Apex-layer entries generally cannot be cited as positive
   grounding at all (contract §8.1 grounds only `source-exact`, fully covered sections).
2. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured org with `nonProduction: true` (a Developer Edition legitimately reports `isSandbox: false`).
3. Call `review_object_contract` for the object's accessible field contract. Choose the snapshot
   fields from that contract only: the natural key (`Name`, a `DeveloperName`-like field, or an
   external-id field) plus the configuration-bearing fields (status values, flags, ordering,
   defaults). Exclude record Ids, audit fields (`CreatedBy`, `LastModifiedBy`, timestamps), owner
   fields, and free-text/long-text fields.
4. Scope before you snapshot. Run aggregates first through the facade — a row count, a
   distribution over the type/status discriminator, and a churn profile (recent creates and
   modifications) — so you know the shape of the table before selecting rows from it. Aggregates
   may cover the whole population; they carry no row values.
5. Snapshot only the slice the design needs. Read records through the governed
   `review_soql_query` facade tool, selecting every field explicitly — never `Id`, which must
   never be persisted:
   `SELECT <field, list> FROM <objectApiName> WHERE <slice predicate> ORDER BY <naturalKey> LIMIT <n>`.
   Always state the `LIMIT`; `ORDER BY` on the natural key makes the snapshot deterministic and
   digestable.
6. When completeness of the slice is material to the design, paginate deterministically by
   keyset — `WHERE <naturalKey> > '<last key of the previous page>'` in natural-key order — and
   record the count before and after, the page count and the final watermark. Do not paginate
   because a table is large; paginate because the design's conclusion depends on having seen
   every row of the slice.
5. Sanitize each returned row before any other use: the facade already strips vendor
   `attributes`; additionally drop any value outside the requested field list, keeping the
   `ORDER BY` order.
7. State completeness honestly, in one of three forms: `complete` (the slice was fully
   enumerated, with the pagination evidence to show it), `partial` (the read hit its limit and
   more rows exist), or `slice-bounded` (the snapshot deliberately covers only the predicate the
   design needs). A `partial` result supports no absence claim. A `slice-bounded` result supports
   no claim about the rest of the table — never generalize a slice to the whole object. Never
   treat a missing row as proof a config value does not exist.
8. Build the snapshot: object identity, the natural-key-ordered sanitized record list, row
   count, and `contentDigest` = `sha256:<64 hex>` over the canonical JSON (sorted keys, compact
   separators) of the ordered sanitized rows. Identity convention for records inside the
   snapshot: `<ObjectApiName>.<NaturalKey>` (mirrors the `Type__mdt.Record` CustomMetadata
   convention).
9. Write the snapshot report under `output/` (e.g.
   `output/reference-data/<objectApiName>-<orgKey>.md`): scope (exact `environment`, `orgKey`,
   namespace prefix), `observedAt`/`retrievedAt`, the sanitized rows, the completeness block,
   the `contentDigest`, a `sanitization` note naming the stripped surfaces, and limitations —
   above all that the values drift without any repository signal and expire with the org's
   refresh cadence.
10. When the caller provided `recordId`, attach the snapshot as work-record evidence with
   `python scripts/work_record.py append-evidence --record-id <ID> ...` (the report file is the
   artifact); otherwise the investigation is a standalone read.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, SOSL, or an unguarded Salesforce
  MCP tool; every read — scoping (counts, distributions) and the snapshot rows alike — runs
  verbatim through the governed `review_soql_query` facade tool (owner decisions 2026-07-30,
  2026-08-04; the retired `salesforce_read.py` lane no longer exists).
- Never snapshot more than one object per invocation, and never widen a slice to "see what is
  there" — widen it because a named design question needs the wider set.
- Never persist credentials, usernames, record Ids, URLs, `attributes` payloads, owner/audit
  values, or free-text business content; snapshot values are limited to the configuration-bearing
  fields the human scoped via the allowlist.
- Never call a snapshot `confirmed` or `verified`, and never present the report as citable
  Knowledge — later work cites approved entries and unexpired org-usage blocks, or re-observes.

## Return

Return `EVIDENCE COLLECTED` or `UNRESOLVED`; `recordId` when provided; the report path; exact
scope; row count and `enumerationComplete`; the content digest; limitations; and what a human
should verify next. No mutation of Salesforce is permitted.
