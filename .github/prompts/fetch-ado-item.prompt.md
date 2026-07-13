---
name: fetch-ado-item
description: Fetch a validated Azure DevOps work item context and begin Solution Design.
argument-hint: "itemId=<ID> [recordId=<ID>] [mode=single|hierarchy] [childDetail=summary|full] [includeTestCases=true|false]"
agent: solution-designer
---

Use the [fetch-ado-item skill](../skills/fetch-ado-item/SKILL.md).

Parse the invocation text as `name=value` arguments. `itemId` is required and numeric. Reject an
unknown option or invalid enum before using a tool. If `itemId` is missing, ask once with
`#tool:vscode/askQuestions`; never guess.

Fetch the context, disclose cache freshness/completeness, then continue the Solution Designer
procedure. Create or validate the deterministic per-item work record and return its `recordId`.
Do not merely print raw ADO content and stop; ADO intent is not implementation evidence.
