---
name: solution-design
description: Run the five-phase Solution Design workflow (discover, plan, verify, execute, verify) grounded in Principles, verified Knowledge, and live Salesforce evidence.
argument-hint: "itemId=<ADO ID> [recordId=<ID>] [objects=<ApiName,ApiName>] | or a written requirement"
agent: solution-designer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'agent', 'ado-readonly/*', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract']
---

Use the [solution-design skill](../skills/solution-design/SKILL.md).

Parse the invocation as `name=value` arguments or a free-text requirement. `itemId` (numeric) or a
written requirement is required; ask once with `#tool:vscode/askQuestions` if both are missing.
`recordId` is optional — without it the design is an ungoverned draft under
`output/solution-design/`; with it the design is persisted through the governed work record.

Announce each phase as you enter it (DISCOVER → PLAN → VERIFY → EXECUTE → VERIFY) and do not skip
or reorder phases. A failed verification returns to the phase that caused it — say so explicitly.
Ground every material design decision in a Principle rule ID, a verified Knowledge claim, or a
fresh Salesforce receipt; a decision that cannot cite its grounding is a blocking question, not a
default. End with the skill's return envelope, including the rule-verdict table and the design
document path.
