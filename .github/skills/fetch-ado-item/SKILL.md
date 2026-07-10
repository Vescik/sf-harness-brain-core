---
name: fetch-ado-item
description: Fetch an Azure DevOps work item with cache-first logic and scope-matching — single or hierarchy mode, tiered child detail, optional linked Test Cases. Returns a context structure for other prompts/skills, not a human-facing answer.
---

# Skill: fetch-ado-item

Multi-consumer (the reason this logic lives here and not in a prompt — blueprint section 3):
called by the `/fetch-ado-item` prompt, and by the `generate-technical-documentation` and
`generate-release-handover` skills.

## Parameters

- `itemId` (required) — the work item ID. Any type: Story, Bug, Task, Feature, Epic.
- `mode=<single|hierarchy>` (optional) — see default inference below.
- `childDetail=<summary|full>` (optional, default `summary`) — detail tier for
  parent/siblings/children in `hierarchy` mode.
- `includeTestCases=<true|false>` (optional, default `false`) — independent of
  `mode`/`childDetail`.

## Procedure

1. **Cache first.** Before any MCP call, check `.cache/ado-items/<itemId>.json` and its
   `_fetchedAt` field (never filesystem mtime). Fresh entry → use it, skip the fetch. If the
   cache is stale, say so explicitly and ask whether to refresh — never silently serve stale
   data, never build separate TTL logic.
2. **Infer mode if not provided**, from `Work Item Type`:
   - Feature / Epic → `hierarchy`.
   - Task / Bug → `single`.
   - User Story → default `single`, but signal: "this Story has N sibling stories under the
     same parent — pull the full context?" instead of guessing blindly.
3. **Mode `single`**: only the specified item — full description, comments, attachments.
4. **Mode `hierarchy`**: the item + its parent + all the parent's children (siblings) + all the
   item's own children. **One level down, not two** — deliberately no grandchildren (e.g. Tasks
   under a sibling Story): usually executional breakdown with no design-relevant content.
   - **No-parent fallback**: restrict to "item + own children" and state this explicitly — not
     a silent error, not an unexplained partial result.
5. **Detail tiers**: full description + comments + attachments always for the specified
   `itemId`. For parent/siblings/children in `hierarchy` mode, apply `childDetail`:
   - `summary` (default) — title, type, state, assignee only (designed for Solution Designer
     context).
   - `full` — complete content of every child (needed by e.g. `check-feature-coverage`, which
     compares each Story's actual text against the Feature/BRD).
6. **`includeTestCases=true`**: Test Cases link to a Story/Bug via a different mechanism than
   the Parent/Child hierarchy ("Tested By/Tests"; the team sees them mixed under "Related" in
   the UI). Check **both sources and merge with deduplication**:
   - the formal "Tested By/Tests" relation, and
   - plain "Related" links filtered to `Work Item Type = Test Case`.
   Return Test Case names only — no steps.
7. **Attachments**: metadata (name, type, size) always cached; content fetched only on explicit
   demand. (Single deliberate exception: the BRD in `check-feature-coverage` — owned by that
   skill, not this one.)
8. **Write-back to cache**: after fetching, save **each item from the tree separately** as
   `.cache/ado-items/<id>.json` with `_fetchedAt` — never one file per tree, so any item fetched
   once is a cache hit when later requested directly.

## Returns

A built context structure (JSON-like), **not a ready human-facing answer** — the consumer (a
prompt or another skill) decides what to do with it.
