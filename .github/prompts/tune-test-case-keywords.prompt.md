---
description: "ADMIN (curation, not daily developer work): tune the Test Case → keywords map with human approval of every change. Usage — /tune-test-case-keywords testCaseId=<ID>"
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill. Zero business
logic here — it lives in .github/skills/tune-test-case-keywords/SKILL.md. -->

> **ADMIN PROMPT — not a developer tool.** This is a curation session with a human approving
> every change (blueprint sections 3 and 12), a different category from `/fetch-ado-item` or
> `/document-metadata-change` run in daily development work. Nothing in the harness requires
> this to have ever been run — `suggest-test-cases` works uncurated from day one, just with
> lower match confidence.

Argument parsing (free text after the command, `name=value` convention — blueprint section 6):

- `testCaseId=${input:testCaseId}` — required. If missing, ask; do not guess.

Steps:

1. Invoke the **`tune-test-case-keywords` skill** with `testCaseId`. Human-in-the-loop rules
   (confirmation of every write; explicit consent before any taxonomy extension) are enforced
   by the skill.
2. Report what was written to `.ai/qa/keywords-map.md`, and whether the taxonomy was extended.
