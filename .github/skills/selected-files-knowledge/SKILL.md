---
name: selected-files-knowledge
description: Convert an explicitly selected handful of force-app files (pinned to chat or named in the prompt) into governed Knowledge - mechanical path/name resolution, a human-approved plan, then per-lane draft/describe/propose with one approval pass per lane. Mixed metadata types are legal; selections beyond one approval chunk route to batch-knowledge.
user-invocable: false
---

# Selected-files Knowledge (the pin lane)

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md), and the
[propose-force-app-knowledge skill](../propose-force-app-knowledge/SKILL.md) — its source
boundaries, AI-description rules, entries-vs-claims routing, and chat-approval mechanics all
apply unchanged. This skill changes only HOW components are selected: by file, instead of by
one metadata type (`batch-knowledge`) or by the whole inventory (`propose-force-app-knowledge`).

Requires the `config-investigator` role. Mixed metadata types in one selection are expected —
that is the point of this lane. The whole selection must fit one chat-approval chunk
(25 components); refuse larger selections and name the split: `/batch-knowledge` covers a
whole metadata type per run (one run per type for a mixed set), or the human re-pins a
selection of at most 25.

## 1 — Gate

1. Run `python scripts/preflight.py --capability metadata` and
   `python scripts/force_app_knowledge.py inventory`.
2. Stop on a partial inventory or a dirty tree. When a **selected** file is untracked or
   modified, name the exact paths and say plainly: *commit these files first — Knowledge
   evidence binds to a commit, so the file you just wrote cannot be documented until it is
   committed.* This is the expected first failure for "document what I just built"; report it
   as the remedy, not as an error.
3. Confirm `knowledge.chatReviewer` is configured; without it no promotion can complete and the
   lane should not start.

## 2 — Resolve (mechanical, never by eye)

Run one `python scripts/force_app_knowledge.py resolve --path <path> --name <name> --write`
call carrying every selected input (repeat the flags per input; paths and names may mix). The
resolver matches lexically against the inventory: casefolded paths, companion `-meta.xml`
siblings, LWC/Aura bundle members, directory expansion, and multi-component files expanding to
all their components. Never translate a path or name into a component id yourself, and never
"correct" the resolver's answer.

Present the resolution table: per input → component(s), lane (`entry` or `claim`), current
status — plus every `ambiguous`, `unmatched`, and `unsupported` input with its
candidates/suggestions/reason. Resolve ambiguity by asking the human with one
`#tool:vscode/askQuestions` call listing the candidate ids; an unmatched or unsupported input
is reported and dropped, never silently substituted.

## 3 — Plan and go-ahead

Produce a one-screen plan: per component its disposition (new / refresh / skip-current /
blocked), its lane, and the claims or entry it will produce; then the expected approval
passes — one `/approve-drafts-knowledge` chunk for the entry-lane components, and the
claim-lane promotions counted by CLAIM, not by component: each `approve-claim` command
carries at most 25 `--claim-spec` pairs, and a component can produce several claims, so
state the expected number of commands (`ceil(claims / 25)`). Ask the human explicitly
(one `#tool:vscode/askQuestions` call): approve, change the selection, or cancel. Never execute
without this go-ahead, regardless of how small the selection is.

Skip-current is the default for components already documented and fresh (`approved-current`
entries; `verified-current` claim components) — list them as skipped, do not redraft. A
`blocked` claim component (any canonical claim status other than verified or proposed —
rejected, contested, superseded, …) is reported with its status, never overwritten.

## 4 — Execute, entry lane (entry-profiled components)

Per component, exactly as batch-knowledge's entry lane:

1. `python scripts/knowledge_store.py entry-draft --metadata-type <Type> --full-name <Name>` —
   a stale entry redrafts the same way (facts carry forward; the body returns to draft).
2. `python scripts/knowledge_store.py entry-context --identity <Identity>`, then author the 1–8
   sentence Purpose from source and callers, and store it with
   `python scripts/knowledge_store.py entry-describe --identity <Identity> --purpose-file <file>`.
3. Hand every described draft to `/approve-drafts-knowledge` as **one** chunk. Never approve
   from this skill.

## 5 — Execute, claim lane (all other components)

1. One `python scripts/force_app_knowledge.py draft --component <Type:Name>` call listing every
   claim-lane component (repeatable flag; never combine with `--metadata-type`). The call
   clears and regenerates `.cache/knowledge-proposals/force-app-drafts/` — do not interleave
   with an in-progress batch draft (the batch resume rule recovers it, but the interleaving
   wastes the batch's drafts).
2. Fill every `<AGENT_...>` description sentinel and refine `candidateKeywords` per the propose
   skill's rules, then submit the manifest `propose` commands.
3. Request promotion in as few commands as the guard's 25-spec cap allows:
   `python scripts/knowledge_registry.py approve-claim --claim-spec <id>:<rev> --claim-spec ...`
   — when the selection's claims exceed 25, split into consecutive commands of at most 25
   specs each (one human confirmation per command, as planned in step 3).

## 6 — Org sampling (default follow-up)

For CustomObject and CustomField entries the batch-knowledge entry-lane org-sampling step
applies unchanged and by default: when `python scripts/preflight.py --capability
salesforce-review` passes and the entry's org lane is not `org-fresh`, compose the probes-file
and run `python scripts/knowledge_store.py entry-org-attach --identity <id> --org <alias>
--probes-file <path>`; when no org is configured or containment refuses, skip silently and
report the reason.

## Return

Per original input: `documented` / `refreshed` / `skipped-current` / `blocked` /
`ambiguous-unresolved` / `unmatched` / `unsupported`, plus component ids, entry identities and
lanes, claim/review IDs, the approval outcomes, and any commit-first stop with its paths.
