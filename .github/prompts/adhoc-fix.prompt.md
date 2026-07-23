---
name: adhoc-fix
description: Bounded defect fix express lane — edit the diagnosed component in force-app, write a fix note; deployment stays human.
argument-hint: "component=<Type:Name> [org=<alias>] plus the diagnosis or a pointer to it"
agent: development-assistant
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_object_contract']
---

Use the [adhoc-fix skill](../skills/adhoc-fix/SKILL.md).

Require a named target component and a written diagnosis (ask once with
`#tool:vscode/askQuestions` if either is missing). This lane replaces the accepted-design entry
gate only for a small bounded defect fix; retrieve the current org state first, make the smallest
coherent edit in `force-app/`, and write the fix note under
`output/documentation/adhoc-fixes/`.

The repository edit is the outcome — the agent never deploys. Report the fix note path, the
before → after of the defective element, the exact human deploy step, and the recommendation to
run an after-the-fact guardrail review. If the fix stops being small and bounded, stop and route
through the normal design lane.
