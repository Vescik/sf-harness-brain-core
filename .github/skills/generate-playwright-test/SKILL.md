---
name: generate-playwright-test
description: Generate a Playwright test from either an existing ADO Test Case (testCaseId) or steps described directly by a tester in chat — verified live against the sandbox UI with a persistent, pre-authenticated browser profile. Saves to output/generated-tests/ for human review.
---

# Skill: generate-playwright-test

The actual procedure behind the `/generate-playwright-test` prompt (blueprint section 11).

**Two equally-supported input sources** — the second is NOT a degraded fallback (blueprint
section 3: the team explicitly said testers will describe tests in chat, not only point at
existing Test Cases):

- **(a) `testCaseId`** — fetch full detail (steps, expected results) via the `fetch-test-case`
  skill.
- **(b) no `testCaseId`** — test steps described directly by the tester in the same
  conversation. No cache and no keywords to check, but everything from step 2 onward is
  identical.

## Hard safety rules (defense in depth, blueprint sections 3 and 14)

- **Authentication**: only via Playwright's persistent browser profile with a saved session —
  the human logs in once, manually, outside the agent's operation. The agent **never handles
  login credentials** in any form.
- **Environments**: the browser profile points at the dev/QA sandbox **only — never
  production** (same defense-in-depth as the deliberately absent prod entry in `mcp.json`).

## Procedure

1. **Collect the test steps** from source (a) or (b) above.
2. **Check `.ai/qa/ui-navigation-patterns.md`** for known UI quirks affecting the objects/pages
   in these steps — do not re-discover what is already recorded.
3. **Navigate the live application with Playwright** (`@playwright/cli` as the primary tool;
   `@playwright/mcp` only as fallback if the environment cannot run CLI + filesystem access —
   blueprint sections 3 and 14). Walk through the steps against the real app, collecting an
   accessibility snapshot at every step instead of guessing page structure.
   <!-- TODO(verify): exact @playwright/cli invocation syntax — a newer, still-evolving
   component (blueprint sections 14 and 16). -->
4. **If a new UI quirk is discovered** that `ui-navigation-patterns.md` does not document —
   **suggest adding it** (same suggest-then-confirm mechanism as the rest of the Knowledge
   layer). Do not write it silently.
5. **Generate the Playwright script**, preferring role/accessible-name selectors (stable, per
   Playwright's own recommendation) over auto-generated IDs (brittle).
6. **Save to `output/generated-tests/<name>.spec.ts`** for human review — **never directly into
   the real `tests/` directory** (blueprint section 3: generated, human-unverified content
   follows the same pattern as manual DOCX export and manual wiki publication; the human
   decides if and when it moves to
   `<TU_WSTAW_DOCELOWY_KATALOG_TESTS>`).
   <!-- While the target tests/ directory convention is unknown (blueprint section 16), the
   human has no documented destination to promote reviewed scripts into — scripts accumulate
   in output/generated-tests/ until it is decided. -->
