# Discovery: authoring Knowledge from a human's own feature description

Status: **discovery — not planned, not implemented** (2026-07-27).
No repo changes made. This is the discovery record for the planning stage.

## The ask

> "Add a prompt that produces a Knowledge entry from *my own* prose: I describe a feature
> manually — how to reach it in the UI, what components it consists of — I supply the
> metadata API names, and the agent turns that into a Knowledge entry, keeping the format
> of the automatically generated entries."

## Verdict

**Worth building — reshaped.** The need is real and nothing covers it today. The *target
record* in the ask is wrong: an artifact entry cannot hold authored prose, by construction.
The Feature Entry already is the record being described, and roughly 70 % of the mechanism
already exists and is unused. The work is an **input contract plus name verification**, not
a new lane.

The literal form of the ask — "same format as the auto-generated entries" — is the one thing
that must not be built. See [Do not do](#do-not-do).

## Why the literal ask cannot work

An artifact entry (`.ai/knowledge/artifacts/<Type>/<ns|c>/<name>.md`) is collector output.
Three independent walls:

| Wall | Where |
|---|---|
| Every structured field (`typeFacts`, `source`, `scope`, `profile`, `extractionCoverage`, `assurance`) is derived by the executor from a real file. The only caller-authored inputs on the whole write path are `--purpose-file` and up to 5 `--candidate-keyword`. | `scripts/knowledge_store.py:744-816`; contract §6.4.6 |
| The approvable body is `## Purpose` **only** — any other `## ` heading is rejected. "How to get there" has no slot. The restriction is deliberate and its expiry is gated on a reviewer-authority matrix. | `scripts/knowledge_store.py:376-378`; `docs/knowledge-one-file-contract.md:94-106` |
| An entry cannot exist for a component absent from `force-app`: the schema demands a `^force-app/` fragment with a re-hashable digest. | `schemas/knowledge-entry.schema.json:68-87` |

Under those, the deeper constraint: the entry `assurance` enum has exactly two values —
`source-exact` and `source-derived-heuristic` — **both meaning "from source"**. There is no
honest marker for a sentence a person typed. And `assurance` sits inside `factsDigest`
inside `reviewedContentDigest` (`scripts/knowledge_store.py:266-310`), so a mismarked
sentence would be a *human-approved* false marker, which §8.1a would then let ground a work
record. That is precisely the defect P0 exists to close.

The prose lane at artifact level is also doctrinally closed on purpose: `entry-describe`
caps at 1–8 sentences and `entry-context`'s own guidance string is *"do not infer intent the
source does not support"* (`scripts/knowledge_store.py:983-987`, `:1010-1015`), echoed in
`.github/prompts/curate-knowledge.prompt.md:25-26`. Authored intent is exactly what that
rule excludes.

## What already exists

| Lane | Covers | Authored input? |
|---|---|---|
| `entry-draft` / `entry-context` / `entry-describe` | 10 profiled metadata types, source-derived facts + 1–8 source-grounded sentences. **Citable.** | body prose only, must be source-grounded |
| `feature-propose` / `feature-describe` / `feature-review` / `feature-approve` (`scripts/knowledge_store.py:1604-1772`) — reachable only via `/curate-knowledge feature <slug>` | a human-authored boundary **rule** plus unlimited free-form prose. **Never citable.** | **fully authored** |
| `/feature-documentor` → `force_app_knowledge.py feature-crawl` / `feature-draft` | older lane; crawls the object graph, drafts feature-tagged claims + dossier | no |
| v1 claim registry (`knowledge_registry.py propose` / `approve-claim`) | claim + immutable evidence + human review; doctrinal home for `business-meaning` / `business-process` / `glossary` via `human-sme-attestation` | **zero producers exist** |

### The Feature Entry is already the record the user is describing

Verified directly:

- `validate_feature` runs the JSON schema, the `<AGENT_...>` sentinel check, and
  `"## Purpose" not in body` — **and nothing else** (`scripts/knowledge_store.py:1534-1546`).
  No section allowlist, no sentence cap. `### How to get there` is legal, because
  `"### x".startswith("## ")` is `False`.
- `run_feature_dossier` renders `body.split("## Purpose", 1)[-1]` verbatim
  (`scripts/knowledge_search.py:2692`), so every `###` subsection reaches the reader.
- Anchors and `boundary.include[]` are offered at hop 0 with assurance **`human-declared`**
  (`scripts/knowledge_search.py:2312`, `:2327-2328`) — a value the entry enum cannot produce.
  The user's declared components already travel correctly marked, with no schema change.
- Approval mechanics are identical: `render_entry`, digest pin, separate append-only
  `features-ledger.jsonl`, one human click.

So: same file family, same rendering, same governance — and it is the **only** record kind
in the system that contains no extracted content at all, which is exactly why it can carry
authored prose honestly.

### What is genuinely missing

1. An **input contract** that accepts a practitioner's own account. Today `feature <slug>`
   assumes the human already knows slug, anchors, hubs, depth and includes — it is an
   operator cockpit, not an authoring flow.
2. **Any verification of the API names.** `command_feature_propose` strips whitespace and
   writes (`scripts/knowledge_store.py:1604-1620`). A typo lands inside an approved,
   digest-bound rule and surfaces later only as a member with `resolved: false`.
3. A **citable** home for "why this feature exists" — the claim lane is designed for it and
   has never been built.

## Defects found along the way (all verified by reading the code)

| # | Defect | Evidence |
|---|---|---|
| D1 | `--depth 0` is inert. `compute_membership` clamps to 0, then calls `traverse(..., depth=max(depth, 1), ...)`, and `traverse` loops `for level in range(depth)`. A "0-depth" rule executes one full incoming BFS level — the schema promises "anchors only". | `scripts/knowledge_search.py:2291`, `:2313`, `:1814`; `schemas/knowledge-feature-entry.schema.json:66-70` |
| D2 | `hubs` is inert for membership. The only occurrence in `knowledge_search.py` is the **dossier table row** at `:2757` labelled "kept as targets, never expanded". `compute_membership` never reads it and `traverse` has no hub parameter. `feature-crawl` *does* honour hubs (`force_app_knowledge.py:6331`, `:6503-6504`), so crawl and membership disagree. `hubs` is inside `boundaryDigest`. | `scripts/knowledge_search.py:2757`, `:1776-1784` |
| D3 | `feature-propose` accepts any string as anchor / include / exclude. No resolution, no warning. | `scripts/knowledge_store.py:1604-1620` |
| D4 | `config/harness.local.json` has **no `knowledge` block**, so `knowledge.chatReviewer` is unset and both `feature-approve` and `entry-approve` fail today. | `scripts/knowledge_store.py:829-835`; `config/harness.local.json` |

D1 and D2 are free to fix now (`.ai/knowledge/features/` is empty) and permanently costly
after the first approved `membershipDigest` — both fields are digest-bound, so changing them
later is a re-approval of every feature.

## Recommended shape

Route one paragraph into two existing lanes and **say out loud which half went where**.

- Human narrative (why it exists, how to reach it in the UI, what it is called by the
  business) → **Feature Entry body**, multi-section.
- Human-declared membership (the API names) → **`boundary.include[]`**, already marked
  `human-declared`.
- Component facts → unchanged, `entry-draft` from source.

That split needs **no new assurance value inside `factsDigest`**, which is what makes it safe.

### P1 — `from-notes <slug>` mode on `/curate-knowledge` (M)

Zero new files, zero pinned-literal moves, zero guard changes.

1. Persist the pasted prose verbatim to `.cache/knowledge-proposals/feature-notes/<slug>.notes.md`.
2. `force_app_knowledge.py inventory`, then **read `.cache/force-app-inventory.json`** for
   `components[]`. The CLI prints only `{path, components: <count>, genericFiles, clean,
   status}` (`scripts/force_app_knowledge.py:6700-6707`) — a procedure that greps stdout for
   a component name finds a number.
3. `knowledge_store.py entry-coverage` for lanes / profiled / unprofiled types.
4. Print a **three-way resolution table** and stop for corrections:
   - resolved + profiled → `--include`, gets an entry;
   - resolved but unprofiled (FlexiPage, Layout, Tab, CustomApplication, QuickAction — none
     in `PROFILES`, `scripts/knowledge_store.py:66-105`, and precisely the types a
     UI-navigation description names) → can never be a member, goes to prose;
   - unresolved → **never** enters `boundary.include` under any circumstance.
5. `feature-propose … --depth 1 --assurance-floor source-exact` (never `--hub`, see D2).
6. `feature-describe --purpose-file` **in the same session** (see the sequencing gate below).
7. Per resolved profiled component with no entry: `entry-draft` → `entry-context` →
   `entry-describe`, all in the same session.
8. `knowledge_search.py build`, then `tree --feature <slug>`, then route to
   `/approve-drafts-knowledge`.

Body skeleton: `## Purpose` + `### How to get there` + `### What it is made of` +
`### Not covered / as-of disclosures`.

Also in P1: add a `## Feature Entries` subsection to the **body** of
`.github/skills/approve-knowledge-drafts/SKILL.md` — the prompt routes feature approval
there and the skill currently contains zero occurrences of "feature".

**Sequencing is a CI gate, not style.** `feature-propose` writes `FEATURE_SENTINEL`
(`:1618`), `feature-check` raises on it (`:1905-1917`), and `validate_harness.py:1016` runs
it. Symmetrically `entry-draft` without `--purpose-file` writes `<AGENT_DESCRIPTION>`
(`:758-763`), `entry-check` aggregates unconditionally (`:1321-1331`), run at
`validate_harness.py:1011`. Propose→describe and every draft→describe must complete in one
session or the tree is validator-red.

### P2 — close D1 and D2 while the corpus is empty (S)

Fix the `max(depth, 1)` clamp and ship the missing depth-0 test; then either implement
`hubs` as a stop-list in `compute_membership` or delete it from schema, `canonical_boundary`,
`feature-review` and the dossier. Add both to the disposition table in
`docs/knowledge-completion-audit-2026-07-25.md` — it declares itself the single source of
open status. Once depth 0 is real, `from-notes` can offer "exactly the components I named".

### P3 — NEW read-only `knowledge_store.py component-resolve` (M)

Turns the resolution table from an agent's word into an executor receipt and closes D3.
Wraps `ForceAppKnowledge(ROOT).inventory()` and the same `<Type>:<Name>` id match
`collector_component` uses (`scripts/knowledge_store.py:505-518`). Returns per name
`{name, status, identity, metadataType, profiled, path, closestMatches}` with status in
`resolved | ambiguous | no-entry-home | not-in-source`, plus a `population` block naming
`componentsScanned` and `profiledTypes`. Soft-fail like `entry-coverage` (`:1158-1166`).

Inside `command_feature_propose`, surface unresolved names as an **advisory** in the return
payload and the `feature-review` surface. Do **not** raise — a hard gate breaks
`tests/test_knowledge_store.py:1085-1092` and `:1301-1307` (fixtures with no
`object-meta.xml`) and couples a pure file write to git.

### P4 — OPTIONAL: promote to a standalone `/describe-feature` prompt + skill (M)

Pure UX. Costs six coordinated pinned literals plus an atlas regeneration for zero capability
the mode does not already have. P4 of the master plan set the precedent of documenting
feature commands inside `curate-knowledge` rather than tripping the pins.

### P5 — OPTIONAL, separate project: the human-attested claim lane (XL)

The only way to make "why this feature exists" **citable**. Needs a conventions decision
first, not code: the `sourceLocator` shape for a persisted attestation, the canonicalization
rule for `contentDigest` over prose (the registry asserts it and never recomputes it), an
evidenceId/claimId minting convention, and whether `collector.kind: "human"` is finally
exercised. Structural precedent: `.github/skills/investigate-config-records/SKILL.md:70-102`.

Ceiling to state up front: `component-description` accepts only `metadata-repository`
evidence (`config/knowledge-policy.json`), so this lane never gives a hand-written
*component* description a claim home. It buys the feature-level "why" and nothing else.

## Do not do

- **Do not** add `--facts-file` / `--from-description` / `--ui-path` to `entry-draft`, and do
  not add a `human-declared` value to the entry `assurance` enum
  (`schemas/knowledge-entry.schema.json:123-129`). The human would approve a false marker
  and §8.1a would let it ground a work record.
- **Do not** use `--depth 0` to mean "only what I named" until D1 is fixed.
- **Do not** offer `--hub` in this workflow until D2 is resolved — a reviewer would approve a
  digest-bound field that `tree` / `feature-dossier` / `feature-drift` silently ignore.
- **Do not** add a hard resolution gate inside `command_feature_propose`.
- **Do not** leave sentinels behind (see the sequencing gate).
- **Do not** store the resolved component list as prose in the body — it is recomputable from
  `boundary.include[]`, so a stored copy is a shadow member list that drifts against the
  recomputed one inside the same rendered dossier. The **unresolved** list is the opposite
  case: it has no other home in the system, so keep it, stamp it with the date and inventory
  generation, and label it an as-of disclosure that rots.
- **Do not** hand-mint `human-sme-attestation` evidence to shortcut P5.
- **Do not** write `.ai/knowledge/**` with Write/Edit — `is_governed_record_path` denies it
  case-folded (`scripts/copilot_role_guard.py:1144-1161`).
- **Do not** report a lane from a raw frontmatter read — lanes come only from
  `entry-status` / `feature-status` receipts.

Two more honest disclosures belong in the body: nothing sanitizes typed prose
(`normalize_body` is NFC + line endings + rstrip, `scripts/knowledge_store.py:193-196`; §9's
sanitizer lives in the collector this lane bypasses), and `force-app` is repository truth,
not deployed org state.

## CI checklist (P1)

- **No count pin moves.** Live: 24 prompts / 25 skills / 6 agents, matching `EXPECTED_COUNTS`
  at `scripts/validate_harness.py:25` and `tests/test_repo_map.py:61-63`. A mode is a body
  edit, not a file.
- **Repo-map must be regenerated anyway** — `build_model()` hashes every prompt/skill into
  `sourceDigests` and stores `argumentHint` (`scripts/render_repo_map.py:141-147`, `:210-214`).
  Run `python3 scripts/render_repo_map.py render` and commit `.ai/repo-map.md` + `.json`.
- **Word budget:** committed `wordCount` 872 against `WORD_BUDGET` 875
  (`scripts/render_repo_map.py:31`, duplicated at `scripts/validate_harness.py:1087-1088`).
  Prompts render as `- /{name} → {agent}` only, so the `argument-hint` change is free — but
  skill `description` **is** rendered, so touch only the *body* of
  `approve-knowledge-drafts/SKILL.md`, never its frontmatter `description`.
- **Command prefix:** write every guarded command as `python scripts/<name>.py …` with
  forward slashes. Note the alternation at `scripts/validate_harness.py:843` omits
  `knowledge_store`, so a bare `scripts/knowledge_store.py …` passes CI green and is denied at
  runtime. There is no mechanical net.
- **No guard change needed** — every command in the procedure is already allowlisted for
  `knowledge-curator` (`scripts/copilot_role_guard.py:211`, `:244-273`, `:282`, `:305`).
- P3 only: the new subcommand's parser and its
  `KNOWLEDGE_STORE_COMMAND_FLAGS["component-resolve"]` entry must land in **one commit** —
  `tests/test_guard_parser_contract.py:62-118` diffs both directions. Keep it out of
  `KNOWLEDGE_STORE_MUTATION_COMMANDS` and the safety-hook approve/revoke partition. The name
  must appear verbatim on a public surface (`tests/test_knowledge_store.py:966-1013`).
- P4 only: six literals — `scripts/validate_harness.py:25` (24→25, 25→26),
  `tests/test_repo_map.py:62-63`, `scripts/render_repo_map.py:31` and
  `scripts/validate_harness.py:1087-1088` (875→890; one prompt+skill pair measures 885).

## Open questions for the owner

1. **`knowledge.chatReviewer` is unset** (D4). Nothing approves until it is set. Who is it?
2. **Must the "why" be citable?** If yes, P5 stops being optional and the whole shape changes.
   If no, the Feature Entry's deliberate non-citability is a feature, not a limitation.
3. **D1 — fix the clamp, or amend the schema** to stop promising "anchors only"?
4. **D2 — implement `hubs`, or remove it** from the schema and `canonical_boundary` before the
   first approval? It is inside `boundaryDigest`.
5. **Should Feature bodies be indexed?** `knowledge_search.build` projects
   `store.all_entry_paths()` only (`scripts/knowledge_search.py:709`), so the most
   human-legible text in the store is the one thing `search --text` cannot find. Touching
   this moves `corpus_fingerprint`.
6. The `knowledge-curator` agent's step-6 stop rule is *"a description you cannot ground in
   source — pause and report, never improvise"*
   (`.github/agents/knowledge-curator.agent.md:56`), and its `argument-hint` does not even
   list the existing `feature <slug>` mode. Carve out feature prose there, or route
   `from-notes` to `config-investigator`?
7. Do D1/D2 need to enter the completion-audit register before they can be fixed?

## Method note

Findings were produced by a 13-agent discovery workflow (6 parallel readers → 3 independent
designs under different priors → 3 adversarial critics → synthesis), then the load-bearing
claims were re-verified by hand: the depth clamp, the `hubs` occurrence set, `validate_feature`,
the missing `chatReviewer`, the inventory CLI output shape, the pinned counts and the word
budget. Four claims asserted by designs were disproved by the critics and dropped.
