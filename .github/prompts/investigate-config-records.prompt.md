---
name: investigate-config-records
description: Snapshot the configuration records held in one allowlisted reference-data object (statuses, settings) and draft a proposed reference-data Knowledge claim.
argument-hint: "objectApiName=<API name> [org=<alias>] [fields=<A,B,C>] [recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_configured_orgs']
---

Use the [investigate-config-records skill](../skills/investigate-config-records/SKILL.md).

Require exactly one `objectApiName` (ask once with `#tool:vscode/askQuestions` if missing). The
object must be on the configured review allowlist and hold reference data — config tables such as
statuses, stages, or settings — not transactional records. Resolve a configured review-org alias
(there is no default) and always pass it as `--org`. Fields come from the guarded object
contract — caller-supplied `fields` must stay a subset of it; records come only from
`python scripts/salesforce_read.py records`, bounded, ordered by the natural key, and sanitized.

The outcome is a schema-valid PROPOSED `reference-data` claim with immutable `org-soql-sample`
evidence — never a verified fact: promotion needs a separate human chat approval. Report the claim
ID, row count, completeness, content digest, limitations, and any prior claims the snapshot
refreshes or contests. When the caller provided `recordId`, attach the evidence references to that
work record; otherwise the investigation is a standalone read.
