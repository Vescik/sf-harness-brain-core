---
description: Sync Test Cases from Azure Test Plans into the local QA index. Usage — /sync-test-cases link=<URL> | suiteId=<ID> | planId=<ID>
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill. Zero business
logic here — it lives in .github/skills/sync-test-cases/SKILL.md. Also invocable by the Test
Strategist agent when broader coverage judgment is needed (multi-consumer pattern). -->

Argument parsing (free text after the command, `name=value` convention — blueprint section 6).
**Three equivalent ways to point at the scope** — exactly one is expected:

- `link=${input:link}` — a full Azure Test Plans URL (the skill extracts suiteId/planId).
- `suiteId=${input:suiteId}` — a direct Suite ID (sync that one suite).
- `planId=${input:planId}` — a Plan ID only (the skill enumerates and syncs ALL suites in the
  plan).

If none of the three is present, ask for one; do not guess.

Steps:

1. Invoke the **`sync-test-cases` skill** with whichever scope argument was provided.
2. Report which suite file(s) were written under `.ai/qa/test-cases/`, and surface any
   orphaned `keywords-map.md` entries the skill flagged.
