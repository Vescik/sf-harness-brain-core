---
name: curate-knowledge
description: Knowledge maintenance session - entry coverage, drafting, description, drift and feature boundaries, with human-approved promotion.
argument-hint: "health | entries | build <MetadataType> | describe | drafts | drift | feature <slug>"
agent: knowledge-curator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal']
---

Use the [search-knowledge skill](../skills/search-knowledge/SKILL.md) for drill-downs.

Modes (every metadata type with an entry profile is curated through the entry store; a type
without a profile has no Knowledge lane — report it as a profile gap, never improvise one):

- `entries`: `python scripts/knowledge_store.py entry-coverage` — per-type lanes, entries
  missing for profiled source components, and which types have no entry profile yet (those
  are not gaps). Read-only.
- `build <MetadataType>`: create entries for every artifact of that type that has none.
  `python scripts/knowledge_store.py entry-coverage` names the gaps, then
  `entry-draft --metadata-type <Type> --full-name <Name>` per artifact. Drafts land holding
  `<AGENT_DESCRIPTION>` — facts extracted, analysis pending. Report the count; do not describe
  in the same pass unless the human asks.
- `describe`: for each entry still holding the sentinel, `entry-context --identity <Identity>`
  then write 1-8 sentences from the source and the entries that use it, and store them with
  `entry-describe --identity <Identity> --purpose-file <file>`. State only what the source
  supports; leave a gap visible rather than inventing intent. Hand the described set to
  `/approve-drafts-knowledge`.
- `drafts`: `python scripts/knowledge_store.py entry-review` — render the review surface for
  outstanding drafts and hand the digest-pinned command to `/approve-drafts-knowledge`.
  Never approve from this cockpit.
- `drift`: `entry-coverage` plus `entry-status`; entries whose source moved sit in
  `approved-drifted`. Re-draft them and route through `/approve-drafts-knowledge`; there is
  no refresh wave for entries, only per-entry re-approval of what actually changed.
- `health` (default): run `python scripts/force_app_knowledge.py inventory`, then
  `entry-readiness` and `python scripts/knowledge_store.py entry-coverage`, plus
  `python scripts/knowledge_search.py edge-health`; report counts, drifted entries, and a
  prioritized maintenance recommendation. Read-only — change nothing.

Every approval requires the human's confirmation click; report any missing
`knowledge.chatReviewer` configuration and stop rather than improvising.

Return the mode, health counts, selections executed, entry identities touched, skipped items
with reasons, and outstanding approvals.

## Feature boundaries (contract §13)

A feature is a business grouping, so its boundary is authored, not discovered. Measured on a
20-object package: from one anchor, depth 1 reaches 3 objects, depth 2 reaches 13, depth 4
saturates at 17 — because every hop expands both along an object's own lookups and along every
field pointing at it. Depth alone cannot express a feature.

- `feature <slug>`: propose or revise the rule, then describe and route to approval.
  - `python scripts/force_app_knowledge.py feature-crawl --feature "<Name>" --anchors <A,B> --depth 1 [--hub <X>]`
    proposes a starting boundary; present it and let the human decide before writing a rule.
  - `python scripts/knowledge_store.py feature-propose --slug <slug> --name "<Name>" --anchor <A>
    [--hub <X>] [--depth N] [--include <Identity>] [--exclude <Identity>]
    [--assurance-floor source-exact|source-derived-heuristic] [--replace]`
  - `python scripts/knowledge_store.py feature-describe --slug <slug> --purpose-file <file>` —
    what the feature IS. No traversal can derive this; it is the part a reviewer actually reads.
  - `python scripts/knowledge_store.py feature-status [--slug <slug>]` — lanes. Read-only.
  - `python scripts/knowledge_search.py tree --feature <slug> [--include-heuristic]` — current
    membership with each node's reason and assurance. Advisory: never approved.
  - `python scripts/knowledge_search.py feature-dossier --feature <slug> [--include-heuristic]` —
    render the human-readable dossier from the APPROVED rule: what the feature is, the rule
    itself, members with why each belongs and how much that reason can be trusted, and the
    artifacts reached only by inference. The file is a generated view and is never citable.
  - `python scripts/knowledge_search.py feature-drift --feature <slug>` — what membership did
    since approval. `changed: "unknown"` means no baseline is available on this machine, which
    is not the same as "nothing changed".
  - Approval goes through [approve-knowledge-drafts](../skills/approve-knowledge-drafts/SKILL.md):
    `feature-review` renders the rule and the prose, and the human confirms
    `feature-approve --feature Feature:<slug>:sha256:<digest>` in chat.
  - `python scripts/knowledge_store.py feature-revoke --slug <slug> --rationale "<reason>"`.
  - `feature-check` is not part of this workflow: `validate_harness.py` runs it as the CI
    integrity gate over features and their ledger. CI runs it; you do not. If it fails, the
    failure names the feature file and the contract section — fix that, do not re-run it by hand.

What approval binds is the RULE and the description — never the member list. Membership depends
on the package as well as the rule, so storing it would mean every new artifact drifts every
feature that could contain it, and the reviewer would be re-approving a list they never read.
