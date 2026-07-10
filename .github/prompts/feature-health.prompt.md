---
description: Feature-level gate before Solution Design — check whether a Feature (and attached BRD) is completely broken down into User Stories. Usage — /feature-health itemId=<FeatureID>
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill. Zero business
logic here — it lives in .github/skills/check-feature-coverage/SKILL.md.
Naming note (blueprint sections 12 and 16): "/feature-health" is a WORKING NAME — renaming it
is a purely cosmetic file rename; the logic stays in the skill. -->

Run at the **Feature level, not a single Story**, before the Solution Design phase — a gap
caught here costs a conversation; caught after design, it costs a redesign (blueprint
section 3).

Argument parsing (free text after the command, `name=value` convention — blueprint section 6):

- `itemId=${input:itemId}` — required, the Feature's ID. If missing, ask; do not guess.

Steps:

1. Invoke the **`check-feature-coverage` skill** with `itemId`.
2. Report where the report was saved (`output/feature-health/<featureId>.md`) and surface any
   blocking gaps or early warnings it found.
