---
name: curate-knowledge
description: Knowledge maintenance session - health report, then approved refresh or batch drafting with human-approved promotion.
argument-hint: "refresh | batch <MetadataType> | health"
agent: knowledge-curator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal']
---

Use the [batch-knowledge skill](../skills/batch-knowledge/SKILL.md) (Refresh mode for `refresh`)
with the [search-knowledge skill](../skills/search-knowledge/SKILL.md) for drill-downs.

Modes:

- `health` (default): run inventory plus `python scripts/knowledge_registry.py stale-report`,
  `python scripts/force_app_knowledge.py relation-health`, and
  `python scripts/knowledge_registry.py keyword-report`; report counts and a prioritized
  maintenance recommendation. Read-only — change nothing.
- `refresh`: health first, then `python scripts/force_app_knowledge.py refresh --dry-run`,
  present the selection, and on the human's go-ahead execute the refresh workflow through
  proposal and chat-approved promotion.
- `batch <MetadataType>`: run the five batch-knowledge phases for that one type.

Every promotion requires the human's confirmation click; report any missing
`knowledge.chatReviewer` configuration and stop rather than improvising.

Return the mode, health counts, selections executed, claim/review IDs, skipped items with
reasons, and outstanding approvals.
