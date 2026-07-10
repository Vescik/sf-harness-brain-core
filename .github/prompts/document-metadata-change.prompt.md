---
description: Generate technical documentation for one development from its package.xml manifest. Usage — /document-metadata-change itemId=<ID>
---

<!-- THIN WRAPPER (R6 / blueprint section 12): parse arguments, call the skill. Zero business
logic here — it lives in .github/skills/generate-technical-documentation/SKILL.md. -->

> **PRECONDITION NOTE** (blueprint sections 3 and 12 — deliberately NOT validated in code):
> this prompt assumes the development's `manifest/package.xml` contains the complete metadata
> for the documented development — and only that development. If the manifest is incomplete or
> mixes more than one change, the documentation will reflect that. Ensuring a clean, one-to-one
> manifest is the developer's responsibility before running this prompt.

Argument parsing (free text after the command, `name=value` convention — blueprint section 6):

- `itemId=${input:itemId}` — required (the ADO work item this development belongs to). If
  missing, ask; do not guess.

Steps:

1. Invoke the **`generate-technical-documentation` skill** with `itemId`.
2. Report where the result was saved (`output/documentation/<itemId>.md`) and that publication
   to the ADO wiki is a manual human step.
