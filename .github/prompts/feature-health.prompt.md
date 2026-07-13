---
name: feature-health
description: Run the Feature/BRD-to-Story coverage gate before Solution Design.
argument-hint: "itemId=<Feature ID> [recordId=<ID>]"
agent: test-strategist
---

Use the [check-feature-coverage skill](../skills/check-feature-coverage/SKILL.md).

Require one numeric `itemId`. Verify the item is a Feature and the ADO result is fresh and
complete. If the ID is missing, ask once with `#tool:vscode/askQuestions`.

Save the report under `output/feature-health/`, return its `PASS`, `WARN`, `BLOCKED`, or
`INCOMPLETE` status, and surface every gap, orphan, ambiguity, partial source, and package warning.
The health check is a read and does not require a work record: only when the caller provided
`recordId` attach the report/evidence references to that record.
