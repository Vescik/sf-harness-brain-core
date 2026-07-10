---
description: Generate a Playwright test from an existing ADO Test Case OR from steps described directly in chat — two equal modes. Usage — /generate-playwright-test testCaseId=<ID> | /generate-playwright-test + steps in the message
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill. Zero business
logic here — it lives in .github/skills/generate-playwright-test/SKILL.md. Run by a QA tester
or by the Developer after development is done; also orchestrable by the Test Strategist
(multi-consumer pattern). -->

**The only prompt with two equal ways to use it** — not one mode with an optional parameter
treated as secondary (blueprint sections 3 and 12):

- **Mode A**: `testCaseId=${input:testCaseId}` — points at an existing Test Case in Azure Test
  Plans.
- **Mode B**: no `testCaseId` — the test steps are described by the tester directly in this
  message/conversation. This is a first-class input, not a degraded fallback.

Argument parsing (free text after the command, `name=value` convention — blueprint section 6):
if `testCaseId=` is present, use Mode A; otherwise treat the message content as the test steps
(Mode B). If neither an ID nor any recognizable steps are present, ask; do not guess.

Steps:

1. Invoke the **`generate-playwright-test` skill** with the Test Case ID (Mode A) or the
   in-chat steps (Mode B). Both lead to the identical procedure from that point on — live
   Playwright verification included.
2. Report where the generated script was saved (`output/generated-tests/<name>.spec.ts`) and
   that moving it into the real `tests/` directory is a human decision after review — never
   automatic.
