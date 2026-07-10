# Workspace Instructions — Table of Contents & Precedence

This file is deliberately thin (blueprint section 7): it points to the three Principles files
and states the order in which they win — it does not duplicate their content.

## Principles files

| File | Source of its rules |
|---|---|
| `.github/instructions/managed-package-constraints.instructions.md` | Hard limitations imposed by the package vendor |
| `.github/instructions/organization-principles.instructions.md` | The company's internal standards |
| `.github/instructions/salesforce-best-practices.instructions.md` | Industry-general Salesforce practice |

All three carry `applyTo: "**"` and are active in every request.

## Precedence on conflict

**Managed Package Constraints > Organization Principles > Salesforce best practices (general).**

Rationale (blueprint section 3): a constraint technically imposed by the vendor is harder than
our internal preference, which in turn is harder than a general industry good practice.

## Reference layers (loaded on demand, not automatically)

- `.ai/knowledge/` — facts about the system; start at `.ai/knowledge/README.md`.
- `.ai/memory/decisions-log.md` — the team's curated decision memory.
- `.ai/templates/` — output formats; `.ai/qa/` — synced Test Case index.

Knowledge holds facts, Principles hold rules — never mix the two (blueprint section 3).

<!-- TODO(verify): blueprint section 6 — confirm empirically that applyTo: "**" in a separate
.instructions.md file behaves identically to content inlined here, in EVERY context (including
a purely conversational question with no file open). If it does not, plan B is to move the
three Principles files' content into this file as sections. -->
