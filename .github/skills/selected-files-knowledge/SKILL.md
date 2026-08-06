---
name: selected-files-knowledge
description: Convert an explicitly selected handful of force-app files (pinned to chat or named in the prompt) into governed Knowledge Entries - mechanical path/name resolution, a human-approved plan, then draft/describe with one approval pass. Mixed metadata types are legal; selections beyond one approval chunk are split or narrowed.
user-invocable: false
---

# Selected-files Knowledge (the pin lane)

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[one-file Entry contract](../../../docs/knowledge-one-file-contract.md) — source boundaries,
AI-description rules, and chat-approval mechanics all apply unchanged. This skill changes only
HOW components are selected: by file, instead of by type-wide curation
(`/curate-knowledge build <MetadataType>`).

Requires the `config-investigator` role. Mixed metadata types in one selection are expected —
that is the point of this lane. The whole selection must fit one chat-approval chunk
(25 components); refuse larger selections and name the split: `/curate-knowledge build` covers
a whole metadata type per run, or the human re-pins a selection of at most 25.

## 1 — Gate

1. Run `python scripts/preflight.py --capability metadata` and
   `python scripts/force_app_knowledge.py inventory`.
2. Stop on a partial inventory or a dirty tree. When a **selected** file is untracked or
   modified, name the exact paths and say plainly: *commit these files first — Knowledge
   evidence binds to a commit, so the file you just wrote cannot be documented until it is
   committed.* This is the expected first failure for "document what I just built"; report it
   as the remedy, not as an error.
3. Confirm `knowledge.chatReviewer` is configured in `config/harness.local.json` (a JSON
   config file, not a git setting); without it no approval can complete and the lane should
   not start.

## 2 — Resolve (mechanical, never by eye)

Run one `python scripts/force_app_knowledge.py resolve --path <path> --name <name> --write`
call carrying every selected input (repeat the flags per input; paths and names may mix). The
resolver matches lexically against the inventory: casefolded paths, companion `-meta.xml`
siblings, LWC/Aura bundle members, directory expansion, and multi-component files expanding to
all their components. Never translate a path or name into a component id yourself, and never
"correct" the resolver's answer.

Present the resolution table: per input → component(s), lane (`entry`, or `none` for a type
without an entry profile), current status — plus every `ambiguous`, `unmatched`, and
`unsupported` input with its candidates/suggestions/reason. Resolve ambiguity by asking the
human with one `#tool:vscode/askQuestions` call listing the candidate ids; an unmatched or
unsupported input is reported and dropped, never silently substituted. A `no-entry-profile`
component is a profile gap to report (extend `knowledge_store.PROFILES`), never something to
document through an improvised side channel.

## 3 — Plan and go-ahead

Produce a one-screen plan: per component its disposition (new / refresh / skip-current /
no-entry-profile), and the entry it will produce; then the expected approval pass — one
`/approve-drafts-knowledge` chunk for the drafted entries. Ask the human explicitly
(one `#tool:vscode/askQuestions` call): approve, change the selection, or cancel. Never execute
without this go-ahead, regardless of how small the selection is.

Skip-current is the default for components already documented and fresh (`approved-current`
entries) — list them as skipped, do not redraft.

## 4 — Execute (entry-profiled components)

Per component:

1. `python scripts/knowledge_store.py entry-draft --metadata-type <Type> --full-name <Name>` —
   a drifted entry redrafts the same way (facts carry forward; the body returns to draft).
2. `python scripts/knowledge_store.py entry-context --identity <Identity>`, then author the 1–8
   sentence Purpose from source and callers, and store it with
   `python scripts/knowledge_store.py entry-describe --identity <Identity> --purpose-file <file>`.
3. Hand every described draft to `/approve-drafts-knowledge` as **one** chunk. Never approve
   from this skill.

## 5 — Org sampling (default follow-up)

For CustomObject and CustomField entries the entry-lane org-sampling step of
[investigate-object](../investigate-object/SKILL.md) applies unchanged and by default: when
`python scripts/preflight.py --capability salesforce-review` passes and the entry's org lane
is not `org-fresh`, compose the probes-file and run
`python scripts/knowledge_store.py entry-org-attach --identity <id> --org <alias>
--probes-file <path>`; when no org is configured or containment refuses, skip silently and
report the reason.

## Return

Per original input: `documented` / `refreshed` / `skipped-current` / `no-entry-profile` /
`ambiguous-unresolved` / `unmatched` / `unsupported`, plus component ids, entry identities and
lanes, the approval outcomes, and any commit-first stop with its paths.
