---
name: curate-knowledge
description: Knowledge maintenance session - health report, then approved refresh or batch drafting with human-approved promotion.
argument-hint: "health | entries | drafts | drift | refresh | batch <MetadataType>"
agent: knowledge-curator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal']
---

Use the [batch-knowledge skill](../skills/batch-knowledge/SKILL.md) (Refresh mode for `refresh`)
with the [search-knowledge skill](../skills/search-knowledge/SKILL.md) for drill-downs.

Modes (entry-home metadata types are curated through the entry store; every other type
still runs the claim workflows below):

- `entries`: `python scripts/knowledge_store.py entry-coverage` — per-type lanes, entries
  missing for profiled source components, and which types have no entry profile yet (those
  are not gaps). Read-only.
- `drafts`: `python scripts/knowledge_store.py entry-review` — render the review surface for
  outstanding drafts and hand the digest-pinned command to `/approve-drafts-knowledge`.
  Never approve from this cockpit.
- `drift`: `entry-coverage` plus `entry-status`; entries whose source moved sit in
  `approved-drifted`. Re-draft them and route through `/approve-drafts-knowledge`; there is
  no refresh wave for entries, only per-entry re-approval of what actually changed.
- `health` (default): run inventory plus `python scripts/knowledge_registry.py stale-report`,
  `python scripts/force_app_knowledge.py relation-health`, and
  `python scripts/knowledge_registry.py keyword-report`; report counts and a prioritized
  maintenance recommendation. Read-only — change nothing.
- `refresh`: health first, then `python scripts/force_app_knowledge.py refresh --dry-run`,
  present the selection, and on the human's go-ahead execute the refresh workflow through
  proposal and chat-approved promotion.
- `batch <MetadataType>`: run the five batch-knowledge phases for that one type. Refuse
  entry-home types and point at `entry-draft` — the registry rejects those proposals anyway.

Every promotion requires the human's confirmation click; report any missing
`knowledge.chatReviewer` configuration and stop rather than improvising.

Return the mode, health counts, selections executed, claim/review IDs, skipped items with
reasons, and outstanding approvals.
