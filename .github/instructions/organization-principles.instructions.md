---
applyTo: "**"
---

# Organization Principles

Source: the company's internal standards. Middle tier in the precedence hierarchy: overrides
general Salesforce best practices, is overridden by Managed Package Constraints (see
`.github/copilot-instructions.md`).

This file is a SKELETON to be filled by a human (blueprint sections 7 and 16). Every
`<TU_WSTAW_...>` below marks missing company-specific content.

## Company naming conventions

<TU_WSTAW_KONWENCJE_NAZEWNICZE_FIRMY>
<!-- While empty: the agent falls back to the generic naming rules in
salesforce-best-practices.instructions.md, so generated metadata may not match existing
company conventions and will need manual renaming in review. -->

## Code review rules

<TU_WSTAW_ZASADY_CODE_REVIEW>
<!-- While empty: the Guardrail Reviewer can only check changes against generic best practices
and package constraints — company-specific review criteria are silently not enforced. -->

## Decision-documenting format

<TU_WSTAW_FORMAT_DOKUMENTOWANIA_DECYZJI>
<!-- While empty: agents default to the entry format already defined in
.ai/memory/decisions-log.md; if the company expects a different/richer format, entries written
in the meantime may need reformatting. -->

## Working on the shared Full Copy Sandbox

<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>
<!-- While empty: there is no stated rule mitigating the known risk of two developers
colliding on the same shared Full Copy Sandbox (blueprint section 7) — controlled tests run by
agents (investigate-object step 3) proceed without a coordination protocol. -->
