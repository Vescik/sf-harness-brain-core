---
name: solution-design
description: Open or continue a Solution Design case — the intake→discovery→plan→execute→verify→iterate loop with one hard gate at human approval.
argument-hint: "itemId=<ADO ID> | caseId=<Design Case ID> | or a written requirement"
agent: solution-designer
tools: ['read', 'search', 'edit/editFiles', 'vscode/askQuestions', 'agent', 'knowledge/*', 'ado-readonly/*', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_soql_query', 'solution-design/design_open', 'solution-design/design_record', 'solution-design/design_check', 'solution-design/design_submit']
---

Use the [solution-design skill](../skills/solution-design/SKILL.md).

Parse the invocation as `name=value` arguments or a free-text requirement. One of `itemId`,
`caseId` or a written requirement is required; ask once with `#tool:vscode/askQuestions` if all
three are missing. `design_open` creates or resumes the canonical case — a design that lives
only in chat or only in a file is not a Design Case.

Work the loop in order — intake, discovery per subject, plan, execute, verify, iterate — and
say which phase you are in. The runtime never refuses a write during the loop: record what you
have, let `design_check` count what is missing, and turn unmet conditions into design content.
The single hard gate is `design_submit`; a `blocked` stop with a stamped delta is a valid,
reportable outcome.

End with the case id, phase, status, the current gap count, and — when a candidate exists —
its id and narrative digest. Never claim a readiness the runtime did not count.
