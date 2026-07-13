---
name: document-metadata-change
description: Generate reviewed technical documentation for one accepted metadata change.
argument-hint: "recordId=<ID> itemId=<ID> [manifestPath=<path>]"
agent: development-assistant
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract']
---

Use the [generate-technical-documentation skill](../skills/generate-technical-documentation/SKILL.md).

Require a numeric work item ID plus a valid `recordId` whose design approval matches the current
scope/design hashes. Resolve `brain-core` as the one repository/SFDX workspace root; validate the manifest
and show detected scope before generation. Ask for missing
manual deployment steps with `#tool:vscode/askQuestions` and record an explicit `None` when the
human confirms there are none.

Save the draft under `output/documentation/`, include rule/claim/evidence references, and append the
artifact reference to the work record. Publication to ADO remains a human action.
