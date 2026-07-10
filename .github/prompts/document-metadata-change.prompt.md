---
name: document-metadata-change
description: Generate reviewed technical documentation for one accepted metadata change.
argument-hint: "itemId=<ID> [manifestPath=<path>]"
agent: development-assistant
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce-readonly/*']
---

Use the [generate-technical-documentation skill](../skills/generate-technical-documentation/SKILL.md).

Require a numeric work item ID and an accepted design. Resolve exactly one named Salesforce
workspace root; validate the manifest and show detected scope before generation. Ask for missing
manual deployment steps with `#tool:vscode/askQuestions` and record an explicit `None` when the
human confirms there are none.

Save the draft under `output/documentation/`. Publication to ADO remains a human action.
