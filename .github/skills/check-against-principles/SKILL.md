---
name: check-against-principles
description: Systematically check a proposed change against the three Principles files in precedence order, plus the granular known-limitations catalog. Ends with a clear verdict.
---

# Skill: check-against-principles

The core logic of the Guardrail Reviewer — but the Solution Designer may run it earlier, to
catch a vendor-constraint conflict before anyone starts implementing, not only at the very end
(blueprint section 11).

## Procedure

Check the proposed change against each source **in precedence order** (see
`.github/copilot-instructions.md`):

1. **Managed Package Constraints**
   (`.github/instructions/managed-package-constraints.instructions.md`) — hard vendor
   constraints, highest precedence. **Plus**: check `.ai/knowledge/known-limitations.md` for
   granular limitations affecting the specific objects/functions/pages this change touches —
   the thin always-active file deliberately does not contain them.
2. **Organization Principles**
   (`.github/instructions/organization-principles.instructions.md`) — company standards.
3. **Salesforce Best Practices**
   (`.github/instructions/salesforce-best-practices.instructions.md`) — industry-general.

A conflict found at a higher tier is not softened by compliance at a lower tier.

## Verdict — always one of three, stated explicitly

- **Safe to proceed** — no conflicts found at any tier.
- **Needs fixes** — specific, listed conflicts that can be resolved; each cites the exact rule
  and file it comes from.
- **Stop — too risky** — a hard Managed Package Constraint (or known limitation) is violated
  and no compliant variant is apparent; escalate to a human.

Never end without a verdict, and never merge tiers in the report — the reader must see which
level of the hierarchy raised each finding.
