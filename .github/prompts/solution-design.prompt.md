---
name: solution-design
description: Open or continue a Design Case — an executed evidence loop over one canonical, versioned design whose readiness is computed, not announced.
argument-hint: "itemId=<ADO ID> | caseId=<Design Case ID> | or a written requirement"
agent: solution-designer
tools: ['read', 'search', 'edit/editFiles', 'vscode/askQuestions', 'agent', 'knowledge/*', 'ado-readonly/*', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_soql_query', 'solution-design/design_open', 'solution-design/design_context', 'solution-design/design_check', 'solution-design/design_apply', 'solution-design/design_import_repository_receipt', 'solution-design/design_import_knowledge_reference', 'solution-design/design_import_soql_envelope', 'solution-design/design_submit', 'solution-design/design_request_human_input', 'solution-design/design_request_candidate_decision', 'solution-design/design_request_writer_transfer']
---

Use the [solution-design skill](../skills/solution-design/SKILL.md).

Parse the invocation as `name=value` arguments or a free-text requirement. One of `itemId`,
`caseId` or a written requirement is required; ask once with `#tool:vscode/askQuestions` if all
three are missing. There is **one lane**: `design_open` creates or resumes the canonical Design
Case. A design that lives only in chat or only in a file is not a Design Case.

Do not announce phases. `design_check` computes readiness and returns routed gaps; work the gap
its route names, then check again. An `OPEN` draft is still freely editable — nothing blocks you
from repairing it. Never type a workflow script, never copy a digest or a handoff id, and never
answer a human-bound request tool yourself: the VS Code elicitation response is the decision.

End with the case id, the current `caseVersion`, status, `nextFocus`, the open obligations grouped
by route, and — when a candidate exists — its id and digest. Never claim a readiness the runtime
did not return.
