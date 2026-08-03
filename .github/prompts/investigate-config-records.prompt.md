---
name: investigate-config-records
description: Snapshot the configuration records held in one allowlisted reference-data object (statuses, settings) and report it read-only with a recorded digest.
argument-hint: "objectApiName=<API name> [org=<alias>] [fields=<A,B,C>] [recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_configured_orgs', 'salesforce-readonly/review_soql_query']
---

Use the [investigate-config-records skill](../skills/investigate-config-records/SKILL.md).

Require exactly one `objectApiName` (ask once with `#tool:vscode/askQuestions` if missing). The
object must be on the configured review allowlist and hold reference data — config tables such as
statuses, stages, or settings — not transactional records. Resolve a configured review-org alias
(there is no default) and always pass it as `--org`. Fields come from the guarded object
contract — caller-supplied `fields` must stay a subset of it; records come only from
`python scripts/salesforce_read.py records`, bounded, ordered by the natural key, and sanitized.

The outcome is a sanitized snapshot report under `output/` with its content digest and
observation time — never a verified fact and never citable Knowledge: record values drift
without any repository signal, so later work re-observes instead of re-reading. Report the
report path, row count, completeness, content digest, and limitations. When the caller provided
`recordId`, attach the evidence references to that work record; otherwise the investigation is
a standalone read.
