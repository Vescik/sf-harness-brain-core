---
name: propose-force-app-knowledge
description: Draft schema-v3 Knowledge claims and immutable metadata-repository evidence from a complete, clean force-app inventory, then optionally submit an explicitly selected subset as proposed claims. Use after inventory-force-app; never verify or promote claims.
user-invocable: false
---

# Propose force-app Knowledge

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md),
[source authority contract](../../../.ai/contracts/source-authority.md), and
[update-knowledge-base skill](../update-knowledge-base/SKILL.md).

## Entry gate

Require the `config-investigator` role and a complete current inventory. Require every `force-app`
file to be tracked and clean at the exact inventory commit. Stop on untracked/modified metadata,
source-tree drift, parser errors, or changed `HEAD`.

## Procedure

1. Run `.venv/bin/python scripts/force_app_knowledge.py draft`.
2. Inspect `.cache/knowledge-proposals/force-app-drafts/manifest.json`. Drafts are schema-v3
   `proposed` claims and immutable sanitized evidence only; they are not canonical or verified.
3. Preserve source boundaries:
   - repository metadata establishes intended customer-owned source at a commit;
   - it does not establish deployment, runtime behavior, business meaning, effective access,
     package internals, or negative claims;
   - LWC/Aura and generic files remain inventory-only when no applicable claim type exists.
4. Present candidate IDs, domains, statements, limitations, and reconciliation risk. Do not submit
   the whole set by default.
5. Only when the caller explicitly selects claim IDs, run each selected manifest command through
   `scripts/knowledge_registry.py propose`. The registry performs schema validation,
   reconciliation, immutable evidence checks, and optimistic concurrency.
6. Never call `review`, `promote`, or edit canonical Knowledge directly. Human review and
   promotion remain separate lifecycle operations.

## Return

Return `DRAFTED`, `PROPOSED`, `DUPLICATE`, `CONTESTED`, or `BLOCKED`; commit/tree digest; selected
claim/evidence IDs; revisions; registry result; limitations; and required human review.
