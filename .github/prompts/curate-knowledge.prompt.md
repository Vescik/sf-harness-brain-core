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
- `describe`: `python scripts/force_app_knowledge.py entry-readiness` lists the worklist in
  `describeNext` (drafted entries still holding the sentinel — distinct from `documentNext`,
  which lists components with no entry at all); for each, `entry-context --identity <Identity>`
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

Every approval requires the human's confirmation click; the reviewer identity is
`knowledge.chatReviewer` in `config/harness.local.json` (a JSON config file — never probe it
via `git config`). Report it missing from that file and stop rather than improvising.

Return the mode, health counts, selections executed, entry identities touched, skipped items
with reasons, and outstanding approvals.

## Feature Knowledge (contract §13)

A Feature is curated, explicit topology — never a recomputed membership. Interactive
authoring has its own entry point: [/author-feature](author-feature.prompt.md) runs the
staged conversation (purpose → domain → processing → UI → access → evidence → approval)
through the [author-feature skill](../skills/author-feature/SKILL.md). From this cockpit you
only need the surrounding lifecycle:

- `python scripts/knowledge_store.py feature-status [--slug <slug>]` — lanes. Read-only.
- `python scripts/knowledge_store.py feature-context --slug <slug>` — the approved
  architecture in one read (never a citation receipt).
- `python scripts/knowledge_store.py feature-search [--text …] [--layer …] [--artifact-id …]`
  — discovery over approved features; hits are never citable.
- `python scripts/knowledge_store.py feature-verify-citations --slug <slug> --claim FC-…`
  — the ONLY producer of a citable featureRef; claim-scoped, transitively checked against
  the artifact bindings.
- Approval goes through [approve-knowledge-drafts](../skills/approve-knowledge-drafts/SKILL.md):
  `feature-review` renders the full package (topology, claims with authority, binding
  currency, narrative) and the human confirms
  `feature-approve --feature Feature:<slug>:sha256:<digest>` in chat.
- `python scripts/knowledge_store.py feature-revoke --slug <slug> --rationale "<reason>"`.
- `feature-check` is not part of this workflow: `validate_harness.py` runs it as the CI
  integrity gate over features and their ledger. CI runs it; you do not.

What approval binds is the reviewed MODEL and narrative — nodes, relations, claims with
their authority classes, artifact bindings pinned by digest. Graph traversal only ever
proposes candidates; a component joins the Feature exclusively through a recorded draft
operation the reviewer can see.
