---
name: refresh-force-app-knowledge
description: Run the governed force-app inventory and claim-draft stages, with optional explicit proposal submission.
argument-hint: "[recordId=<ID>] [claimIds=<ID,ID,...>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Run the [inventory-force-app skill](../skills/inventory-force-app/SKILL.md), then the
[propose-force-app-knowledge skill](../skills/propose-force-app-knowledge/SKILL.md).

Stop after inventory when source is partial, dirty, untracked, or changed after scanning. Otherwise
generate schema-v3 drafts. Submit no canonical proposal unless `claimIds` explicitly selects it.
Return both artifact paths, commit/tree digest, coverage, selected registry results, limitations,
and the separate human review/promotion requirement.
