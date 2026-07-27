# Making Knowledge useful: relations, composition, and the feature tree

Date: 2026-07-24 · Status: plan, owner decision pending · Scope: T07/T08 follow-on

Success criteria this plan is written against:

- **Agents** — an agent answering a question about a component reaches the whole truth about it
  in one call, and can never mistake heuristic inference for a declared fact.
- **SDLC stages** — discovery, design, implementation, test and review each have a defined
  Knowledge entry point that returns what that stage actually needs.
- **Ad-hoc questions** — "how does X work?" is answerable by descending from a named parent
  through a tree of real artifacts, each one citable.

Everything below is grounded in a probe against real metadata
(`~/Desktop/salesforce_test_data`, 189 components) drafted into the one-file entry store and
indexed. Numbers in §2 are measured, not estimated.

---

## 1. Two defects fixed while probing

These were found by the probe and are already fixed in this branch; they are listed because
the rest of the plan depends on them.

**Index reuse was keyed on data but not on the code that produced it.**
`load_previous_projections()` keyed reuse on the entry file, its source fragments and the
ledger. Editing the lane logic left every projection reusable — no data had moved — so queries
went on serving fields the current code would never produce. Concretely: draft entries kept a
null citation digest written before the fix, and hydration dropped every relation hit as
`entry changed since the index was built` while nothing had changed but the code. Fixed with
`code_fingerprint()` — a digest of `knowledge_search.py`, `knowledge_store.py` and
`text_analysis.py` — folded into the reuse key, the corpus fingerprint and the generation id.
Editing the projector now discards the previous generation automatically; nobody has to
remember to pass `--full`. Pinned by `ProjectorVersionTests`.

**`--state draft` served drafts under a key named `approvedResults`.**
Any lane opt-in tipped non-current content into the one key a consumer is entitled to read as
effective approved knowledge. Split into `approvedResults` (only `approved-current`) and
`nonCurrentResults`, with a gap line naming the lanes served. Pinned in
`test_g14_draft_never_interleaves_with_approved`.

---

## 2. What the probe showed

| # | Finding | Evidence |
|---|---|---|
| F1 | **Consumers are wired to the layer that no longer receives repository knowledge.** 7 skills/agents name `knowledge_registry.py query` as their operational step-1 lookup. For the 10 entry-home metadata types the claim registry is frozen, so that query returns nothing and the agent concludes "no governed Knowledge" while the entry corpus holds the answer. Only `search-knowledge` names `knowledge_search.py`. | grep over `.github/skills`, `.github/prompts`, `.github/agents` |
| F2 | **Nearly half the corpus is invisible to relation traversal.** 88 of 189 entries have no outgoing edge at all: **all 20 CustomObject entries**, 63 of 93 CustomFields, 4 ApexClasses, 1 LWC. The object — the natural anchor of any feature question — is a leaf. | index scan |
| F3 | **Composition is not a graph question today.** "What is `Assignment__c` made of?" needs a different query per child type: `--facet field.object=` for fields, and for ValidationRule and RecordType **no object facet exists at all** — you list the type and read the object out of the `fullName` prefix. | `capabilities`; facet query returned 5 fields; VR query required manual prefix reading |
| F4 | **`operates-on` is semantically overloaded and cannot carry containment.** For Workflow, RecordType, ValidationRule and ApexTrigger it means *owning object*. For CustomField it is emitted only on rollup summaries and means the **child** object being summarised — the opposite direction. A tree built on `operates-on` files `Engagement__c.Total_Planned_Hours__c` under `EngagementPhase__c`. | `force_app_knowledge.py:722` vs `:1409, :2608, :2738, :1607`; 2 of 93 fields carry it |
| F5 | **`update-relations` is an infinite loop with a fake progress signal.** With entries present, `relations-worklist` reports 582 missing relation claims — **100% of them for entry-home types**. `relations-draft --limit 50` answers `"drafted": 50, "remainingMissing": 532` but writes a manifest with **0 bundles and 0 claims**: `draft()` skipped every component as entry-home. The skill's Phase 2 says "loop until zero `missing`". It can never reach zero, and every pass reports progress. | probe run, manifest inspection |
| F6 | **`relation-health` gives false assurance.** It only inspects `verified` relation *claims*. For entry-home types there will never be any, so it reports `HEALTHY` unconditionally while entry edges rot. | `force_app_knowledge.py:5258-5263` |
| F7 | **`feature-documentor` is a working crawler bolted to a dead writer.** `feature-crawl` still resolves a boundary (it reads the inventory, not entries), but `feature-draft` produced **0 claims** and the dossier rendered **64 components, every one "description pending"** — because descriptions are read from drafted claims, which no longer exist for these types. | probe run, `output/feature-dossiers/assignment-scheduling.md` |
| F8 | **Feature membership is a dragnet with no assurance marker.** 23 of 29 Apex members of the `Assignment__c` boundary joined **only through heuristic edges** (`object-token`, `var-field-ref`) — a class that merely mentions the object name in a comment is in. The dossier presents them flat, indistinguishable from declared members. | boundary vs inventory reference kinds |
| F9 | **The entry system has no concept of a feature.** `grep feature scripts/knowledge_store.py scripts/knowledge_search.py` → 0 hits. Feature tagging exists only as an advisory string on v1 claims. | grep |
| F10 | **Traversal does not scale and loses multiplicity.** `explain` and `impact` load the entire corpus (no postings). `impact` depth is silently clamped to 2. Incoming relation matching `break`s after the first matching edge per document, so an entry that both queries and DMLs the anchor reports one edge. | `knowledge_search.py:1159-1164, 1191, 1073-1074` |

---

## 3. The governing principle

Every design choice below follows from one rule, which the three-digest boundary already
implies but nothing states:

> **Locality rule.** An entry may assert only what is derivable from its own source fragments.
> Anything that requires another artifact to exist is derived in the index, never stored in
> the entry.

The rule is not stylistic — it is what protects approval from re-approval waves. A reverse
edge (`usedBy`) stored in an entry changes when a *different* artifact is added: in this
corpus, one new Apex class touching `Assignment__c` would move the `factsDigest` of six
already-approved entries and drift them all. At 15k entries a single commit could invalidate
dozens of human approvals. Resolved target identities have the same problem — resolving
`Assignment__c` to `CustomObject:c:Assignment__c` depends on that entry existing.

So: **entries hold local facts, the index holds all relationships.** This is the answer to the
first half of the brief ("relations should enrich individual entries") — they should, but only
with the part of a relation the artifact itself declares.

---

## 4. Ideas considered and challenged

| Idea | Verdict | Why |
|---|---|---|
| **A. Enrich entries with resolved relations + reverse `usedBy`** | **Rejected as stated, accepted in local form** | Reverse edges and resolved identities are non-local — they trigger exactly the re-approval wave the digest boundary exists to prevent (worked example above). What survives: containment derived from the artifact's own source. |
| **B. Do all resolution in the index** | **Accepted for reverse/transitive** | The index is disposable and never citable, which is fine — every *element* of a derived view is a citable entry. Where a durable artifact is needed (a dossier), render it deterministically and pin it with `--check`, like `feature-map.md`, rather than approving it. |
| **C. Feature Entry with a human-declared boundary** | **Accepted, in "approved rule, advisory membership" form** | F8 proves no amount of edge-following identifies a feature: `BillingEngineService` is in the `Assignment__c` boundary because it names the object. A feature is a business grouping and needs a human. But approving a *member list* would drift on every commit — so what is approved is the **boundary rule** (anchors, hubs, depth, explicit include/exclude); membership is recomputed and reported as an advisory. |
| **D. SDLC "context packs" as documented recipes** | **Collapses into two concrete changes** | A recipe that names the wrong command is F1 again. The real needs are (i) fix the consumer wiring and (ii) one composed `context` call, because answering "everything about `Assignment__c`" today takes six heterogeneous queries. |
| **E. Synthesised execution stories (trigger → handler → queueable → event)** | **Accepted only as a rendering of traversal** | `invokes-class` is heuristic. A narrative presented as Knowledge launders inference into apparent fact. Ship it as a chain view with per-hop assurance; never as an entry, never approved. |
| **F. Coverage as an SDLC gate** | **Deferred** | With 0 approved entries a gate blocks all work, and a gate applied early incentivises rubber-stamp approvals. Report-only first; revisit once coverage is meaningful. |
| **G. Retire `update-relations` / `relation-health`** | **Rescope, don't retire** | Relation claims still matter for the ~47 non-entry-home types (Layout, FlexiPage, ApprovalProcess, Workflow, DuplicateRule, CustomTab…). What must change is the scoping that produces F5 and F6. |

**Chosen design = A(local) + B + C + D + E(as view) + G.** It is a composition, not one idea:
each layer does the thing it is structurally allowed to do.

---

## 5. The design, in four layers

```
Layer 4  consumers          skills/agents call the entry index for source questions
Layer 3  feature            Feature Entry = approved boundary RULE; tree = rendered view
Layer 2  index (derived)    reverse edges, resolved targets, context packs, chains
Layer 1  entry (local)      containment edge derived from the artifact's own source
```

### Layer 1 — `belongs-to`: the missing local edge

A new relation kind, emitted by the extractor from the artifact's **own** source or path:

| Type | Source of the owner | Today |
|---|---|---|
| CustomField | `typeFacts.object` (already extracted) | facet only; `operates-on` means something else (F4) |
| ValidationRule | `fullName` prefix / path | `operates-on` — correct meaning, wrong to overload |
| RecordType | `fullName` prefix / path | `operates-on` — same |
| ApexTrigger | trigger declaration | `operates-on` — same |
| ListView, CompactLayout, FieldSet, WebLink (later) | path | none |

`belongs-to` is emitted **in addition to** the existing kinds, never replacing them —
`operates-on` keeps its per-type meaning, including the rollup direction on CustomField, and
`belongs-to` always means "this artifact is part of that object". The parent side (`contains`)
is **not** stored: it requires knowing all children, which is non-local. The index inverts it.

This closes F2 (20 objects and 63 fields stop being leaves), F3 (composition becomes one
uniform traversal instead of a per-type facet hunt) and F4 (no overloading).

> **Ordering constraint — this must land before the first approval.** Adding an edge kind
> changes `typeFacts.references` → `factsDigest` → `reviewedContentDigest`. Today the
> repository holds **zero** entries, so the cost is zero. Every entry approved before this
> lands must be re-approved after it.

### Layer 2 — what the index derives

- **Reverse postings** (`relations-reverse.json`): target → sources, so `impact` and `explain`
  stop scanning the whole corpus (F10). Same lazily-loaded posting-file pattern as the rest.
- **Resolved targets**: `{target, targetIdentity|null, resolution: exact|unresolved}` computed
  at build time. Unresolved targets stay visible — an unresolvable target is a finding
  (a component outside the repo, or a typo), not something to drop.
- **`context --identity <Identity> [--depth 1]`** — the composed pack that replaces six calls:
  the entry projection (purpose, facts, coverage, limitations, citation), **parts** (inverted
  `belongs-to`), **outgoing** and **incoming** edges grouped by kind with per-edge assurance,
  **permission grants** touching it, and the gaps. This is the call every consumer skill makes.
- **Chain view** (`impact --format chain`): shows the path a hop arrived through, not a flat
  edge list. Today hop-2 rows like `ConflictDetectionTest invokes-class → TestDataFactory_SCH`
  appear under "impact of `Assignment__c`" with no visible connection to the anchor.
- **Multiplicity**: drop the `break` so an entry that queries *and* writes the anchor reports
  both edges (F10).

### Layer 3 — Feature Entry and the feature tree

`.ai/knowledge/features/<slug>.md`, same Markdown + frontmatter shape, same digest-pinned
chat approval as artifact entries. What it holds:

```yaml
boundary:
  anchors: [Assignment__c]
  hubs: [Attachment__c]              # kept as endpoint, never expanded
  depth: 1
  include: [ApexClass:c:ConflictDetectionQueueable]   # human override
  exclude: [ApexClass:c:BillingEngineService]         # human override
  membershipAssuranceFloor: source-exact              # heuristic members opt-in
```

Body: what the feature *is*, in business terms — the one thing no extractor can derive.

**The approved content is the rule, not the member list.** Adding a class to the package does
not drift the feature entry, because the human approved the boundary, not a snapshot. A
separate `feature-health` command reports "membership changed since approval" as an advisory
with the added/removed identities — visible, but never a lane change.

The **tree** (`knowledge_search.py tree --feature <slug>` or `--anchor <Identity>`) descends
from the parent: object → its parts (`belongs-to` inverted) → what operates on it → what those
invoke. Every node carries:

```json
{"identity": "...", "lifecycle": "draft|approved-current|...",
 "membership": {"reason": "belongs-to|references-member|declared-include",
                "assurance": "source-exact|source-derived-heuristic|human-declared",
                "hop": 1, "viaEdge": {"source": "...", "kind": "..."}}}
```

Per-node assurance is the direct answer to F8: the 23 heuristic members are still shown, in
their own lane, labelled with the edge that let them in. Below the assurance floor they are
counted and summarised rather than listed inline.

### Layer 4 — consumers

The rewiring, which is where most of the day-one value is (F1).

| Surface | Change |
|---|---|
| `solution-design` | step 1 calls `context --identity` for each touched component before designing |
| `check-against-principles` | source questions to entries; `verify-citations` extended to `entryRef` |
| `check-feature-coverage` | boundary from the Feature Entry, not an ad-hoc anchor list |
| `adhoc-fix`, `investigate-config-records` | entry lookup first, claim registry for org/business only |
| `development-assistant`, `test-strategist` (agents) | same routing rule in their procedure |
| `search-knowledge` | already correct — add `context` and `tree` to its command menu |
| `generate-technical-documentation` | descriptions from approved entries, not drafted claims |

---

## 6. Disposition of the existing relation / feature machinery

The brief asked specifically whether `update-relations` and friends need refactoring after the
move to the entry system. They do — one of them is actively harmful.

**`update-relations` (prompt + skill + `relations-worklist` / `relations-draft`)** — **must be
fixed before anyone runs it again.** The prompt already carries a carve-out note telling the
agent that entry-home types live in entries, but the *tooling* does not honour it: the worklist
counts those edges as `missing` and `relations-draft` reports a `drafted` count for components
it silently skipped (F5). Fix:
- `relations-worklist` gets a new state `homed-in-entry` for entry-home components; `missing`
  means "a relation claim is genuinely owed". The loop can then terminate.
- `relations-draft` counts what it actually wrote; `drafted` never exceeds the manifest's
  `claimCount`. The counter that lies is the reason the loop is invisible.
- Skill Phase 2 termination condition restated against the corrected counts.

**`relation-health`** — extend, not replace. Keep the verified-claim orphan check for
non-entry-home types; add an entry-edge check (an entry edge whose target no longer resolves)
and report the two populations separately. Without this it reports `HEALTHY` over a rotting
graph (F6).

**`feature-documentor` (prompt + skill + `feature-crawl` / `feature-draft` / `render_dossier`)**
— largest refactor. `feature-crawl`'s BFS logic is sound and worth keeping; it becomes the
**proposal engine for a Feature Entry's boundary rule**, not a producer of claims.
`feature-draft` stops drafting v1 claims for entry-home types. `render_dossier` reads
descriptions from **approved entries** instead of drafted claims — which is what turns the
current all-"description pending" table (F7) into a real document. Membership rows gain the
assurance column (F8).

**`feature-map.md` and the v1 `feature` tag** — unchanged. They group claim-based org and
business knowledge. The new tree is a different artifact over a different corpus; the two must
not be conflated, hence the distinct name (`feature-tree`, not `feature-map`).

---

## 7. Phase plan

Each phase is independently shippable and independently verifiable. Phases 1–2 are the
ordering-constrained ones.

### Phase 1 — `belongs-to` (must precede first approval)

- **Extractor**: emit `belongs-to` in `parse_custom_field`, `parse_validation_rule`,
  `parse_record_type`, `parse_apex_trigger`; register the kind in
  `force_app_knowledge.ALL_REF_KINDS` + `OBJECT_REF_KINDS`, and classify it in
  `knowledge_registry.OBJECT_REF_KINDS`.
- **Store/schemas**: no adapter change (pass-through carries it); the `references` block in
  each profile schema already accepts any `^[a-z][a-z-]{2,40}$` kind.
- **Verify**: `tests/test_kind_contract.py` (already pins the vocabulary — it will fail until
  the kind is classified in all sets, which is the intended forcing function); a new extractor
  test asserting a rollup field carries **both** `operates-on → child object` and
  `belongs-to → owning object` without confusing them; probe re-run showing CustomObject and
  CustomField leaf counts drop from 20 and 63 to 0.

### Phase 2 — index derivation

- Reverse postings + resolved targets in `project_entry` / postings build.
- `explain` and `impact` read postings instead of scanning; drop the incoming `break`; add
  `--format chain`.
- **Verify**: golden queries for reverse traversal and multiplicity; `knowledge_benchmark.py`
  gains an `impact`/`context` measurement — the acceptance bar is that `impact` latency stops
  growing linearly with corpus size (today it is a full scan).

### Phase 3 — `context`

- `knowledge_search.py context --identity <Identity> [--depth 1] [--include-heuristic]`.
- **Verify**: a golden test asserting that the single call returns everything the six
  current calls return for `Assignment__c`, with lane and assurance preserved per section.

### Phase 4 — Feature Entry + tree

- `feature-propose` (boundary from a crawl), `feature-describe`, `feature-review`,
  `feature-approve`, `feature-health` in `knowledge_store.py`; `tree` in `knowledge_search.py`;
  `schemas/knowledge-feature-entry.schema.json`; role-guard command allowlist + parser-contract
  test; safety-hook `ask` on `feature-approve` (same mechanism as `entry-approve`).
- **Verify**: approving a feature then adding an unrelated class does **not** move the feature
  entry's digest; `feature-health` reports the membership delta; the tree labels the 23
  heuristic members of the `Assignment__c` boundary as such.

### Phase 5 — machinery fixes (§6)

- `relations-worklist` `homed-in-entry` state + schema update; honest `relations-draft`
  counters; `relation-health` entry-edge check; `feature-documentor` repointed at entries.
- **Verify**: probe re-run — `relations-worklist` reports 0 `missing` and 582 `homed-in-entry`;
  a dossier for `Assignment Scheduling` renders real descriptions for every described entry.

### Phase 6 — consumer rewiring

- The seven surfaces in §5 Layer 4; prompt/skill count pins updated in CI.
- **Verify**: `validate_harness.py` PASS; a scripted read-through of each changed procedure
  confirming the first knowledge call for a source question is the entry index.

---

## 8. Open decisions for the owner

1. **`belongs-to` before approvals** — confirm Phase 1 lands before any entry is approved. This
   is the only decision with a deadline; everything else can be sequenced freely.
2. **Feature Entry as a governed artifact** — it adds an approval surface. The alternative is a
   purely generated tree with no human boundary, which F8 says will be a dragnet. Recommend
   accepting it, with the "approved rule, advisory membership" split that keeps it drift-free.
3. **Feature file location** — `.ai/knowledge/features/` alongside `artifacts/`, sharing the
   ledger, versus a separate ledger. Recommend the shared ledger: one approval mechanism, one
   revocation path.
4. **`--depth` cap for `tree`** — `impact` is clamped at 2. A feature tree needs 3–4 to reach
   trigger → handler → queueable → event. Recommend a per-command cap with the reached limit
   reported in the result, never silently clamped.

## 9. What this plan does not do

No changes to the claim registry's org-observation path; no removal of v1 relation claims for
non-entry-home types; no deployment, org reads, or Screen Validation; no new approval authority
for agents — every new surface routes through the same human confirmation as `entry-approve`;
no gate on coverage (deferred, §4 F).
