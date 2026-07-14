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
4. **Write the AI descriptions.** Every behavior-bearing draft (Flow, Apex, trigger, approval
   process, LWC/Aura) includes a `component-description` claim whose description is an
   `<AGENT_...>` sentinel. For each one you intend to propose: read the component's actual source
   file, then replace the sentinel with 2–6 sentences covering purpose, trigger/entry conditions,
   the key steps or actions, and what the component reads or changes. Describe only what the
   source shows — never business intent, org runtime behavior, or anything you cannot point to in
   the file. These claims stay `assurance: inferred` and the registry rejects any unfilled
   sentinel at propose time.

   While writing each description, also fill the claim's `candidateKeywords` with 0–5 terms
   naming the business process or feature the source visibly serves (e.g. "revenue adjustment",
   "billing event"). Ground every term in the source (object names, labels, action names);
   preserve Polish business terms verbatim; never invent product names. Candidate keywords are
   advisory suggestions for later human taxonomy curation
   ([curate-knowledge-keywords](../curate-knowledge-keywords/SKILL.md)) — the `keywords` field
   itself accepts only approved taxonomy terms, and the registry rejects anything else at
   propose time.
5. Before selecting candidates, look up what the registry already knows so proposals never
   duplicate or ignore related Knowledge: `python scripts/knowledge_registry.py query
   --subject-identity <identity>` for exact-subject duplicates, and `--keyword <term>` /
   `--text <fragment>` for related claims by approved or candidate keyword and description text.
   The generated `.ai/knowledge/claims-index.json` is the same data as one scannable file.
6. Present candidate IDs, domains, statements, limitations, and reconciliation risk. Do not submit
   the whole set by default.
7. Only when the caller explicitly selects claim IDs, run each selected manifest command through
   `python scripts/knowledge_registry.py propose`. The registry performs schema validation,
   reconciliation, immutable evidence checks, and optimistic concurrency.
8. After proposing, offer chat-approved promotion: for each claim the caller wants verified, run
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
