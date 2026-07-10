---
name: sync-test-cases
description: Synchronize one validated Azure Test Plan or Suite into the committed QA index.
argument-hint: "link=<ADO Test Plans URL> | suiteId=<ID> [planId=<ID>] | planId=<ID>"
agent: test-strategist
---

Use the [sync-test-cases skill](../skills/sync-test-cases/SKILL.md).

Accept exactly one scope form. Reject conflicting or malformed inputs before fetching. A URL must
match the configured ADO organization/project and use HTTPS. Ask once when no scope is supplied.

Report suites/cases requested, completed, skipped, failed, and partial. Never delete a curated
keyword entry automatically.
