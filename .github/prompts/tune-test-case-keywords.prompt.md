---
name: tune-test-case-keywords
description: Human-led admin curation of Test Case keywords using the controlled taxonomy.
argument-hint: "testCaseId=<ID> approver=<name>"
agent: test-strategist
---

Use the [tune-test-case-keywords skill](../skills/tune-test-case-keywords/SKILL.md).

Require a numeric Test Case ID and a named human approver. Show the existing map entry, candidate
terms, evidence, and exact proposed diff. Use `#tool:vscode/askQuestions` for explicit approval.
Taxonomy extension and keyword-map update are separate confirmations. No confirmation means no
write.
