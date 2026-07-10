---
name: generate-playwright-test
description: Generate and live-verify a Playwright draft from an ADO Test Case or tester-provided steps.
argument-hint: "testCaseId=<ID> | steps=<quoted steps>"
agent: test-strategist
---

Use the [generate-playwright-test skill](../skills/generate-playwright-test/SKILL.md).

Accept exactly one input source: numeric `testCaseId` or substantive in-chat steps. Confirm the
configured origin is allowlisted and non-production before starting a browser, and repeat the
check after redirects. Ask for approval before any state-changing step.

Generate, lint, and execute the resulting draft against the sandbox. Save it under
`output/generated-tests/` with verification evidence; promotion to the real tests directory is a
human action.
