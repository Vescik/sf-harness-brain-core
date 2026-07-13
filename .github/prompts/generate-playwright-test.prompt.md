---
name: generate-playwright-test
description: Generate and live-verify a Playwright draft from an ADO Test Case or tester-provided steps.
argument-hint: "recordId=<ID> (testCaseId=<ID> | steps=<quoted steps>)"
agent: test-strategist
---

Use the [generate-playwright-test skill](../skills/generate-playwright-test/SKILL.md).

Require a valid `recordId` and accept exactly one input source: numeric `testCaseId` or substantive
in-chat steps. Confirm the
configured origin is allowlisted and non-production before starting a browser, and repeat the
check after redirects. Ask for approval before any state-changing step.

Use guarded live exploration to verify the approved steps, then generate and statically review the
resulting draft. Never execute model-generated code in this repository. Save it under
`output/generated-tests/` with exploration/static-review evidence and append the artifact reference
to the work record; human review and promotion precede execution in the trusted test runner.
