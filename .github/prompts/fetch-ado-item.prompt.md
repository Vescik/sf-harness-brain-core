---
description: Fetch an Azure DevOps work item (any type) with cache-first and scope logic, then hand off to the Solution Designer. Usage — /fetch-ado-item itemId=<ID> mode=<single|hierarchy>
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill, hand off.
Zero business logic lives here — it all lives in .github/skills/fetch-ado-item/SKILL.md.
The name deliberately does not say "US"/"feature" — the item can be any type (Story, Bug,
Task, Feature, Epic). -->

Argument parsing (blueprint section 6 caveat: text after the command is free text, not a
parsed schema — read it per the `name=value` convention):

- `itemId=${input:itemId}` — required. If missing, ask for it; do not guess.
- `mode=${input:mode}` — optional (`single` or `hierarchy`). If absent, the skill infers the
  default from the Work Item Type.
- Optional pass-throughs if the user provides them: `childDetail=`, `includeTestCases=`.

Steps:

1. Invoke the **`fetch-ado-item` skill** with the parsed arguments.
2. With the returned context, **hand off to the `solution-designer` agent** — this prompt is
   the entry point to the SDLC pipeline (blueprint section 10), not a dead end leaving data
   alone in chat.
