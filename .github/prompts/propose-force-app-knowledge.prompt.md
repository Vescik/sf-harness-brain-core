---
name: propose-force-app-knowledge
description: Draft governed force-app Knowledge candidates and optionally submit an explicitly selected subset as proposed claims.
argument-hint: "[recordId=<ID>] [claimIds=<ID,ID,...>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_soql_query']
---

Use the [propose-force-app-knowledge skill](../skills/propose-force-app-knowledge/SKILL.md).

Require a current complete inventory. Generate schema-v3 drafts only when `force-app` is tracked
and clean at the exact commit. If `claimIds` is absent, return the candidate set without canonical
writes. If it is present, submit only those exact IDs through the guarded registry `propose`
commands. Never review, verify, promote, or imply deployed-org agreement.
