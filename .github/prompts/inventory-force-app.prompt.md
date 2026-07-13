---
name: inventory-force-app
description: Inventory the root force-app as sanitized Knowledge evidence candidates without creating claims.
argument-hint: "[recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Use the [inventory-force-app skill](../skills/inventory-force-app/SKILL.md).

If this is governed work, require and validate `recordId`; otherwise state that the run is a
repository inventory only. Inventory the single root `force-app`, report coverage, generic files,
diagnostics, commit/tree digest, and whether source cleanliness permits governed claim drafting.
Do not create or promote claims.
