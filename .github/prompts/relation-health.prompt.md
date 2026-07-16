---
name: relation-health
description: Report verified relation claims whose source edge no longer exists in current force-app source (read-only; flags candidates for human stale-marking).
argument-hint: "[recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Use the [relation-health skill](../skills/relation-health/SKILL.md).

The health check is a read and does not require a work record: only when the caller provided
`recordId` attach the report/claim references to that record.
