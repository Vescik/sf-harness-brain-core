---
name: propose-force-app-knowledge
description: Draft schema-v3 Knowledge claims and immutable metadata-repository evidence from a complete, clean force-app inventory, submit an explicitly selected subset as proposed claims, and optionally request chat-approved promotion. Use after inventory-force-app.
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

1. Run `python scripts/force_app_knowledge.py draft`.
2. Inspect `.cache/knowledge-proposals/force-app-drafts/manifest.json`. Drafts are schema-v3
   `proposed` claims and immutable sanitized evidence only; they are not canonical or verified.
3. Preserve source boundaries:
   - repository metadata establishes intended customer-owned source at a commit;
   - it does not establish deployment, runtime behavior, business meaning, effective access,
     package internals, or negative claims;
   - coverage is total: approval processes draft automation claims, and every other metadata
     type (layouts, permission sets, custom metadata, bundles, …) drafts a generic
     `component-inventory` claim — the draft never silently produces nothing for a source file.
4. Present candidate IDs, domains, statements, limitations, and reconciliation risk. Do not submit
   the whole set by default.
5. Only when the caller explicitly selects claim IDs, run each selected manifest command through
   `python scripts/knowledge_registry.py propose`. The registry performs schema validation,
   reconciliation, immutable evidence checks, and optimistic concurrency.
6. After proposing, offer chat-approved promotion: for each claim the caller wants verified, run
   `python scripts/knowledge_registry.py approve-claim --claim-id <id> --expected-revision <n>`
   (add `--decision reject` to reject). The safety hook stops every invocation for the human's
   confirmation click, and the registry records the local-config `knowledge.chatReviewer` as the
   human reviewer with mechanism `copilot-chat-confirmation`, then re-renders the domain indexes.
   If `knowledge.chatReviewer` is unset, report the exact config key and stop — never guess an
   approver. Never call the file-based `review`/`promote` commands or edit canonical Knowledge
   directly.

## Return

Return `DRAFTED`, `PROPOSED`, `VERIFIED`, `REJECTED`, `DUPLICATE`, `CONTESTED`, or `BLOCKED`;
commit/tree digest; selected claim/evidence IDs; revisions; registry results (including review
IDs for chat approvals); limitations; and any remaining human follow-up.
