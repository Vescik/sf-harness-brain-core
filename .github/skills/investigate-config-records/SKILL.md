---
name: investigate-config-records
description: Take a bounded, sanitized snapshot of the configuration records held in one allowlisted reference-data object (statuses, settings, config tables) and create a proposed reference-data Knowledge claim. Use when package behavior is driven by org records rather than metadata; never self-verify a claim.
user-invocable: false
---

# Investigate configuration records in a reference-data object

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md), and
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md). Run
`python scripts/preflight.py --capability salesforce-review`.

Authority basis: per the grounding architecture, a reference-data value claim is eligible only
through a bounded current org observation — these values live in records, not in source files, so
the metadata repository has no authority here. This skill is the deliberate reference-data
exception to the record-persistence prohibition in
[investigate-object](../investigate-object/SKILL.md): it persists only the sanitized
configuration-bearing values of one human-allowlisted object; everything that skill otherwise
forbids (Ids, URLs, audit fields, free text, unscoped business data) stays forbidden here.

## Input

Require exactly one `objectApiName` and one `org` — a configured review-org alias (enumerable via
`python scripts/salesforce_read.py orgs`); there is no default alias. The object must be on
`salesforce.review.allowedObjectApiNames`; if it is not, stop and report the missing allowlist
entry instead of widening scope. Optional: `fields` (must remain a subset of the reviewed field
contract), `recordId` (work record to attach evidence to). Reject a generic "dump the org",
multiple objects in one call, or an object that is transactional rather than reference data — a
snapshot that fills the row cap is treated as transactional and returned unresolved.

## Procedure

1. Check existing Knowledge both ways: `python scripts/knowledge_registry.py query
   --subject-identity <objectApiName>` shows effective claims only; earlier PROPOSED snapshots are
   invisible to it and surface only through the reconcile step below.
2. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured sandbox.
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
7. Build the snapshot facts: object identity, the natural-key-ordered sanitized record list, row
   count, and `contentDigest` = `sha256:<64 hex>` over the canonical JSON (sorted keys, compact
   separators) of the ordered sanitized rows. Identity convention for records inside facts:
   `<ObjectApiName>.<NaturalKey>` (mirrors the `Type__mdt.Record` CustomMetadata convention).
8. Author one immutable evidence file under `.cache/knowledge-proposals/` (the only path this
   role may write), valid against `schemas/knowledge-evidence.schema.json`: `sourceType:
   "org-soql-sample"`; `sourceLocator:
   "soql://<orgKey>?object=<objectApiName>&fields=<...>&orderby=<naturalKey>&limit=200"`;
   `authorityFor: ["reference-data"]`; scope with the sandbox `environment` (development/qa/uat)
   and the non-null configured `orgKey`; `observedAt` and `retrievedAt`; the `contentDigest`; the
   completeness block; `sanitization: {rawDataCommitted: false, redactions: [...]}` naming the
   stripped surfaces; and a sanitized `summary`. Record the collector as this skill with the
   `salesforce_read.py` transport.
9. Author one `proposed` claim file in the same directory; the
   [knowledge-entry template](../../../.ai/templates/knowledge-entry.md) is the human-facing
   companion to the claim schema. Set `claimType: "reference-data"`, `domain:
   "current-implementation"`, subject `{kind: "object", identity: <objectApiName>}`, assertion
   predicate `holds-reference-data-records` with the snapshot as value, a bounded `statement`,
   `assurance: "observed"`, `sensitivity: "internal-sanitized"`, `keywords: []` with suggestions
   in `candidateKeywords` (the taxonomy is human-gated), `observedAt`, and `reviewBy` no more
   than 180 days after `observedAt` (the reference-data policy ceiling; prefer 90 for volatile
   tables). Scope must carry the exact `environment`, `orgKey`, and the namespace prefix of the
   object API name (null for subscriber objects) — matching the evidence; `repositoryCommit` is
   null because this fact does not live in the repository. Mint IDs with the stable-id
   convention (`PREFIX-<SLUG>-<10-hex-suffix>`): claimId slug from the object API name with
   discriminator `reference-data|holds-reference-data-records|<orgKey>` so each org gets its own
   parallel-scoped claim; evidenceId discriminator `soql-<contentDigest>`. State in limitations
   that record data drifts without any repository signal, so the claim must be re-observed, not
   re-read from git.
10. Reconcile before submitting: `python scripts/knowledge_registry.py reconcile --claim-file
    <claim>` schema-validates the draft and classifies it against all claims, including proposed
    ones; declare any surfaced conflict in `contradicts` or stop. Then submit:
    `python scripts/knowledge_registry.py propose --claim-file <claim>
    --evidence-file <evidence> --expected-revision <n>`; for re-observation of an already
    verified snapshot pass `--refresh-verified` with the current revision. After a successful
    propose, run `python scripts/knowledge_registry.py render-indexes` so the generated views
    stay clean.
11. When the caller provided `recordId`, attach the evidence with
    `python scripts/work_record.py append-evidence --record-id <ID> ...`; otherwise the
    investigation is a standalone read.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, arbitrary SOQL/SOSL, a Tooling flag, or an
  unguarded Salesforce MCP tool; records flow only through `salesforce_read.py records`.
- Never exceed the 200-row or configured field caps, chain calls to paginate past them, or
  snapshot more than one object per invocation.
- Never persist credentials, usernames, record Ids, URLs, `attributes` payloads, owner/audit
  values, or free-text business content; snapshot values are limited to the configuration-bearing
  fields the human scoped via the allowlist.
- Never call a proposed snapshot `confirmed` or `verified`, and never promote — human chat
  approval is a separate operation.

## Return

Return `EVIDENCE COLLECTED` or `UNRESOLVED`; `recordId` when provided; `claimId`; `evidenceId`
values; exact scope; row count and `enumerationComplete`; the content digest; reconciliation
classification and prior related claims (added / refreshed / contested); limitations; and the
required human review step. No mutation of Salesforce is permitted.
