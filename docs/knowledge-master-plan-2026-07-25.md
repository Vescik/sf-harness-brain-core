# Master implementation plan — Knowledge relations, composition and the feature tree

Date: 2026-07-25 · Status: ~~**owner decisions settled (§9), ready to implement**~~ → **P0–P6 have
shipped on `knowledge-relations-p0-p6`; this document is now the gate list they are audited
against, not a forward plan.** Current state lives in one place —
`docs/knowledge-completion-audit-2026-07-25.md` § Disposition — and nowhere in this file. ·
Supersedes the phasing in `docs/knowledge-usefulness-plan-2026-07-24.md` (that document remains the
strategic rationale; this one is the executable plan)

> **Measurement corrections, 2026-07-25 (waves 2 and 3).** Four numbers below were measured against
> the code as it stood when they were written and no longer reproduce. Every one of them is
> corrected **in place** and marked `[CORRECTED …]`, with the old value kept struck through, because
> a plan whose numbers cannot be reproduced teaches the next implementer to trust commit messages
> instead — which is how this project acquired three audits. **No gate value changed**; only
> denominators and one share moved.
>
> | Where | Was | Is | Effect on the gate |
> |---|---|---|---|
> | §0.1, §8 row 1, P0 gate | 414 of 595 laundered | 0 of **481** kind-level-heuristic edges, in a corpus of **771** stored / **662** non-`belongs-to` | none — the gate value is **0 laundered**, and it is met |
> | R6, golden (c), §9.1 | 58 of 59 forward-chain edges are `invokes-class` | **481 of 589 (82 %)** forward edges in the depth-2 Apex closure are kind-level heuristic; `invokes-class` alone is 125 (21 %) | none — R6's rule stands, on a larger margin |
> | §7 "≈596" vs §8 "≈598" | disagreed with each other | both now defer to `docs/knowledge-p1-completion-note.md`, which is the plan's own designated home for a moving number | none — the bar was always "read from the note" |
> | R6, golden (c) — **wave 3** | `AssignmentTrigger` returns "2 nodes instead of 19" (wave 2's own re-grounding) | **8 citable `nodes` → 1** without `--include-heuristic`; the 19/2 was the *row* count of the whole payload, unhydrated half included | none — R6's rule reproduces strongly; only the figure moved |
>
> **The standing rule this third drift bought.** Every figure in this plan states the **corpus**, the
> **exact command**, the **platform**, and — for anything a command returns — **which key of the
> payload it counts**.
>
> **`[EXTENDED 2026-07-26, wave 4.]`** The platform was implicit, and a fourth figure drifted
> without it. Every budget in §4.2, §5 and §6 below is **stated** for 15 k on `windows-latest` and
> has only ever been **measured** at 3 000 entries on macOS — two different claims, and this plan
> will not let them read as one. The measured side lives under one named method, M1, in
> `docs/knowledge-completion-audit-2026-07-25.md` § Disposition, together with every open item and
> what would close it. **This document states gates; it states no status.**
> Three numbers in a row drifted here, and the third drifted *inside the wave that was correcting the
> other two*: not because anyone measured carelessly, but because "nodes" meant a different thing to
> each reader. A figure without its method is a quotation, and this document has now taught that
> lesson three times.
>
> Re-measured on the reference corpus (189 components from `~/Desktop/salesforce_test_data`,
> drafted, described and approved into a temp root via `knowledge_store.rooted()`, then indexed:
> 189/189 `approved-current`). The commands are recorded in `docs/knowledge-p4-completion-note.md`
> §"How these numbers were produced", and R6 carries its own command and payload key inline.

## How this plan was produced, and what changed

Six areas were specified independently against the real code, then attacked by three adversarial
reviews (ordering/dependency, governance/contract, scale/does-it-answer). All three returned
**NOT-READY** on the combined draft — 37 findings, 9 of them blocking. That verdict was on the
*draft*, and it did its job: the conflicts below are resolved here, and four defects the
strategic plan never saw are now the first things that ship.

I independently re-verified the four load-bearing findings rather than taking them on trust:

| Claim | My verification | Result |
|---|---|---|
| 70 % of stored edges launder heuristic inference as `source-exact` | scanned the 189-entry probe index against `HEURISTIC_REF_KINDS` | ~~**414 of 595 edges**~~ stored `source-exact`; **0** stored honestly — `[CORRECTED: 481 of 771, see §0.1]` |
| Every traversal is reverse-only, so "how does X work?" is unanswerable | `impact --identity ApexTrigger:c:AssignmentTrigger --depth 2` | **0 edges**; yet `explain` shows the trigger's 2 outgoing edges — data present, traversal missing |
| A per-query freshness floor grows linearly with the corpus | timed `corpus_fingerprint()` over the probe corpus | 2.19 ms / 189 entries = **11.6 µs per entry** → **~174 ms per CLI call at 15 k** on macOS, worse on NTFS+Defender |
| The CI gate dies on a timeout as the corpus grows | read `scripts/validate_harness.py:867-873` | `subprocess.run(..., timeout=30)` with **no `except`** — an uncaught `TimeoutExpired`, not a legible failure |

Two of these are defects in **already-merged code**, not in the plan. That reorders everything:
the plan now starts with a phase that fixes what is broken today.

---

## 1. Governing rules (these resolve most of the cross-area conflicts)

**R1 — Locality.** An entry asserts only what its own source declares. Reverse edges, resolved
identities and membership lists are derived in the index. *(Verified respected by every data
contract in the reviewed draft.)*

**R2 — One anchor, one owner.** Where several phases touch the same anchor, exactly one owns it:

| Anchor | Owner | Everyone else |
|---|---|---|
| `copilot_role_guard.KNOWLEDGE_*_COMMAND_FLAGS` rows | the phase that owns the **parser** | may not restate rows |
| `.github/skills/search-knowledge/SKILL.md` command menu | **P6** owns the prose; **P2 creates the placeholder block** it appends into | P2/P3/P4 append one line only |
| `tests/test_knowledge_search.py` fixture base class | **P2** (`EntryFixtureMixin`) | new classes inherit `EntryFixtureMixin, unittest.TestCase` — never another TestCase — and add fixtures in their own `setUp` after `super().setUp()` |
| `knowledge_search.run_capabilities` | **P2** | P3/P4 add only their own keys |
| Feature Entry shape, identity, schema, ledger | **P4** | P5 consumes P4's values verbatim |
| `validate_harness.EXPECTED_COUNTS`, `render_repo_map.WORD_BUDGET` | the phase that adds the prompt/skill | asserts `<= budget`, never a literal |

**R3 — Parser and guard land in one commit.** `tests/test_guard_parser_contract.py` asserts flag-set
equality in both directions, so a split commit is CI-red by construction. Corollary: every new
`store_true` flag joins `KNOWLEDGE_*_VALUELESS_FLAGS` in the same commit. *(A standing arity-derived
test replaces hand-listing — see P0.)*

**R4 — No unowned budget.** Every phase that adds a traversal states an **absolute** latency and
memory budget measured by `knowledge_benchmark.py`. A budget expressed as a ratio to an existing
floor cannot fail and is not a budget.

**R5 — Coverage is disclosed, never implied.** Any result enumerating artifacts states the
population it drew from. A partial list is more misleading than an empty one.

**R6 — Heuristic stays opt-out, and the honest answer may require the flag.** After P0 §0.1,
`invokes-class` is correctly marked heuristic — and ~~**58 of 59 forward-chain edges in the probe
corpus are `invokes-class`**~~ **`[CORRECTED 2026-07-25]` 481 of the 589 distinct forward edges
reachable within depth 2 of an Apex anchor are kind-level heuristic — 82 %, of which
`invokes-class` is 125 (21 %) and `object-token` 253 (43 %)**. Method, so it is reproducible:
depth-2 forward walk from every one of the 57 `ApexClass`/`ApexTrigger` anchors in the reference
corpus, counting each distinct `(from, kind, to)` edge once. The old figure is stale or from a
different denominator; it also named the wrong kind as the load-bearing one. So the execution chain
of golden question (c) is a *heuristic product*. The resolution is not to weaken the default:

- traversals keep excluding non-`source-exact` edges by default;
- `--include-heuristic` is **required** to answer (c), and the acceptance table says so;
- every chain carries per-hop `assurance` **and** a path-level `minAssurance` — a chain is only as
  trustworthy as its weakest hop;
- whenever the default filter drops hops, the result emits a **mandatory** gap naming
  `excluded.heuristicEdge` and the flag that would surface them. Silence is what turns an
  opt-out default into a false negative.

**The rule survives the correction with a larger margin than it was written on.** Re-measured the
consequence rather than the ratio. ~~Without `--include-heuristic`, `AssignmentTrigger` returns
**2 nodes instead of 19**, and **53 of the 57 Apex anchors lose at least one node**, four of them
dropping from 35–83 nodes to zero.~~ **`[CORRECTED 2026-07-25, wave 3 — the figure, not the rule.
The old one counted rows and called them nodes, and counted the unhydrated half of the payload as
answer.]`**

**Corpus:** 189 components from `~/Desktop/salesforce_test_data`, drafted, described and approved
into a temp root via `knowledge_store.rooted()`, then indexed — 189/189 `approved-current`.
**Command**, golden question (c)'s own anchor, run against that root:

```
python scripts/knowledge_search.py impact --identity ApexTrigger:c:AssignmentTrigger \
    --direction outgoing --depth 2 --include-heuristic
```

| What is counted | With `--include-heuristic` | Default (source-exact only) |
|---|---|---|
| `nodes` — citable: resolved, approved-current, `hydrated: true` | **11 rows / 8 distinct nodes** | **2 rows / 1 distinct node** |
| `nodesNonCurrent` — `resolved: false`, `hydrated: false`, no lane | 8 rows / 8 nodes | 0 |
| whole payload | 19 rows / 16 distinct nodes | 2 rows / 1 node |

Identical at `--depth 3` and `--depth 4` (the walk exhausts at `depthReached: 2`) and at
`--top 200`. The old "2 instead of 19" reproduces exactly — as the **row** count of the whole
payload, unhydrated half included. That is the one number a reader must not take as the answer,
because contract §14.2 rules an unhydrated row uncitable. Counted as this plan counts
everywhere else, the collapse is **8 citable nodes → 1**.

Across all 57 `ApexClass`/`ApexTrigger` anchors, same command and root: **52 lose at least one
citable node** without the flag and **47 fall to zero**, the largest being
`ApexClass:c:BillingEngineServiceTest` at **27 → 0**. That is the evidence for requiring the flag:
not that one kind dominates, but that the default answer to "how does this work?" is empty or
near-empty for almost every Apex anchor, which is exactly the false negative the mandatory gap
exists to name.

**R7 — One vocabulary, per-command values.** `DEPTH_LIMITS = {impact: 2, context: 1, tree: 4,
drift: 4}` — one constant, four values. Depth values are semantic requirements, not benchmark
outputs, so they are fixed here and not deferred.

---

## 2. Phase 0 — fix what is already broken (NEW, blocks everything)

None of this is in the strategic plan. All of it is live defect in merged code.

### 0.1 Heuristic laundering at the approval boundary — **the most severe item in this plan**

`knowledge_store._edges` (`scripts/knowledge_store.py:606-615`) derives edge assurance from the
per-edge `heuristic` flag only. The collector never sets that flag for kind-level heuristics, so
every `object-token`, `invokes-class`, `var-field-ref` and `soql-field` edge is stored
`source-exact`. Measured: ~~**414 of 595 probe edges**~~, 0 stored honestly.

**`[CORRECTED 2026-07-25]` The denominators moved; the defect and the gate did not.** Re-measured
on the same 189-component corpus after P0–P6 shipped: **771** stored edges, of which **662** are
not `belongs-to` (P1's kind did not exist when 595 was taken) and **481** are kind-level heuristic.
The per-kind breakdown reproduces verbatim for three of the four kinds — `object-token` 253,
`var-field-ref` 78, `soql-field` 25 — and the entire delta is `invokes-class` **58 → 125**, because
P2's `APEX_NEW_RE` made constructor calls visible. So the population of edges that *would* be
laundered grew by 67 while the number actually laundered stayed **0**. Read the gate as "**0**
kind-level-heuristic edges stored `source-exact`", never as a ratio: a ratio to a corpus is not a
budget, and this is precisely the escape R4 forbids elsewhere in this plan.

Consequences, in order of severity:

1. `assurance.typeFacts` is inside `factsDigest`, so a human **approves** the false marker.
2. SAFE-CLAIM-001 v2 grounds work records on sections marked `source-exact` with full coverage —
   so a design document can ground "ApexClass X operates on Assignment__c" on a **comment mention**.
3. `--include-heuristic` is largely a no-op: my earlier probe excluded exactly **1** edge for
   `Assignment__c` while 6 of its 7 incoming edges were kind-level heuristics.
4. The `search-knowledge` skill promises "heuristic edges stay out unless `--include-heuristic`".
   That promise is currently false for 70 % of them.

**Fix.** Fold `kind in HEURISTIC_REF_KINDS` into the stored assurance in `_edges` and
`flow_type_facts`. **Mandatory, not deferrable** — the draft offered it as an optional rider
(A1 D4, A3 alternative 1); both are deleted.

**Where the helper lives, and who may call it.** `edge_assurance(kind, heuristic_flag)` lives in
the kind-vocabulary leaf module (§0.2) and is called from exactly two places, both in the store:
`_edges` and `flow_type_facts`. The section-level rollups (`_assurance_for` and the Flow
equivalent) already derive from the per-edge values and need no change — `flow_type_facts` keeps
its signature.

**The projector must NOT import the vocabulary for assurance purposes.** An earlier draft of this
plan said the helper is "imported by the search projector", which was wrong and self-contradictory:
`project_entry` already copies the stored per-edge `assurance` verbatim, so there is nothing to
unify there, and applying the vocabulary at projection time would be precisely the override the
next sentence forbids. `knowledge_search`'s only reason to import the leaf is `code_fingerprint`.

**Why a single implementation is required — corrected argument.** The draft justified this by
citing contract §5.5 ("assurance regression → `approved-drifted`"). **That row is not
implemented.** Verified: `compute_lane` sets the lane solely via `regenerate_fragment_digest`,
which compares source-file bytes; nothing re-runs the collector, nothing diffs assurance, and no
entry records a collector version. The true argument is stronger and more alarming: *nothing
detects an assurance regression after approval at all*, so a divergence between the store and the
index would be permanent and silent. **P0 therefore also records in
`docs/knowledge-one-file-contract.md` that the §5.5 collector/assurance row is UNIMPLEMENTED**,
and that pre-approval ordering (D1) is the **only** control — not belt-and-braces, as an
implementer reading §5.5 would reasonably assume.

**Stated consequence: after P0, ApexClass and ApexTrigger entries become ungroundable.** Their
`typeFacts` assurance is `source-derived-heuristic`, and SAFE-CLAIM-001 v2 grounds only
source-exact sections with full coverage. This is **correct** — it is the defect being fixed, not
a regression — but it must be stated, because a work record that grounded on such an entry
yesterday will be refused tomorrow.

### 0.2 Kind vocabulary moves to a leaf module — `scripts/relation_kinds.py`

**All three sets move, not two.** `ALL_REF_KINDS` is *derived* (`OBJECT_REF_KINDS | frozenset{…}`),
so moving `HEURISTIC_REF_KINDS` alone is incoherent — the leaf would have to import the collector,
reinstating exactly the heavy import it exists to avoid. The leaf owns `OBJECT_REF_KINDS`,
`HEURISTIC_REF_KINDS`, `ALL_REF_KINDS` and `edge_assurance(kind, heuristic_flag)`, and imports
nothing but stdlib. `force_app_knowledge` **re-exports** all three so every existing reference
keeps working; `knowledge_store` imports the helper at module level (cheap — verified the collector
is imported only lazily today, marked "heavy module", and `knowledge_search` does not import it at
all).

**P0 owns re-pointing `tests/test_kind_contract.py`** at the leaf and re-verifying all five of its
assertions there.

**The leaf joins `code_fingerprint()`'s module tuple** — currently
`(knowledge_search, knowledge_store, text_analysis)`. Without this, editing `HEURISTIC_REF_KINDS`
changes no fingerprinted byte, the previous generation stays reusable, and **the index keeps
serving the old `source-exact` assurance** — the one defect P0 exists to fix would be silently
un-invalidatable. Pinned by a test in the `ProjectorVersionTests` pattern: mutate the leaf's
vocabulary, rebuild, assert the previous generation is discarded.

Rationale for the leaf at all: fingerprinting the 6 542-line collector would turn every P1/P5/P6
collector edit into a **~105 s full reprojection at 15 k** instead of a ~0.2 s incremental one.

Module name `scripts/relation_kinds.py`. `force_app_knowledge` re-imports all three sets with the
existing dual-import idiom (`try: from relation_kinds import … except ModuleNotFoundError: from
scripts.relation_kinds import …`) so the CLI keeps running standalone on Windows,
`force_app_knowledge.OBJECT_REF_KINDS` keeps resolving, and `tests/test_kind_contract.py` needs no
edit at all.

### 0.5 Six facts the collector emits that three profile schemas reject

Verified: `typeFacts` is `additionalProperties: false` in every profile, and the collector emits
`summaryFilterFields`, `lookupFilterPresent`, `lookupFilterFields` (CustomField),
`externalSharingModel`, `compactLayoutAssignment` (CustomObject) and `picklistScopes` (RecordType),
none of which are declared. `entry-draft` therefore fails outright on a rollup with a filter, an
object declaring an external sharing model, or a RecordType with picklist scoping — all normal
shapes. My probe corpus happens to contain none of them, which is exactly why this survived to now.

Declare the six properties. Safe: `profile.digest` is written once at draft time and is **not** an
input to `factsDigest`/`reviewedContentDigest`, so this moves no lane and needs no MAJOR bump.

Add the standing test that would have caught all six: for every type in `knowledge_store.PROFILES`,
adapter output must validate against the profile schema for a fixture exercising every optional
collector fact. `AdapterFaithfulnessTests` proves pass-through but never validates against a
schema — which is the hole.

### 0.3 CI gate fails legibly and incrementally

`validate_harness.py:872` runs `entry-check` under `timeout=30` with no handler. Measured
`compute_lane` ≈ 3.45 ms/entry → ~52 s at 15 k, crossing 30 s at **~8 700 entries** — inside the
target range. Two changes:

1. Wrap the grounding-command loop in `except subprocess.TimeoutExpired` →
   `audit.require(False, f"grounding command timed out: …")`, so the failure is legible instead of
   an uncaught traceback in two gates at once (the same command runs in `harness-ci.yml`).
2. Make `entry-check` incremental — **via git, not a stamp manifest**. Every stamp-manifest design
   fails here: `.cache/` is git-ignored so CI is always cold and the incremental path would never
   engage; a committed mtime-keyed manifest is inert because `git checkout` rewrites mtimes; and
   any committed manifest is forgeable unless it is itself governed, putting a new integrity hole
   inside the gate whose job is integrity.

   Instead: `entry-check --changed-since <ref>` asks **git** which entry files changed, and git is
   not forgeable by an agent editing a file. The expensive per-entry work (`regenerate_fragment_digest`
   SHA-256 over every source fragment, plus jsonschema validation) runs only on those. The
   **cross-entry checks — identity collision and case-fold collision — always run over the whole
   corpus**, because a per-entry skip would silently destroy them; they only parse identities and
   are cheap. `--full` remains the default and is what the nightly run uses. `entry-check` stays a
   read-only command: nothing is written, so it never becomes a writer.

   The `timeout=30` is also raised from a measured budget. The `except` wrap makes the failure
   legible; it does not make it stop happening.

**No second grounding subprocess may be added until this lands** — that rules out wiring
`feature-check` in P4 first.

### 0.4 Role-guard valueless-flag fix — constant **and** loop branch, in both guards

Verified fail-open today: `knowledge_search_command_allowed(['build','--full','--rm'], role)`
returns **True**, because the guard advances the index by 2 unconditionally, so the token after a
boolean is never validated.

The search guard has a `KNOWLEDGE_SEARCH_VALUELESS_FLAGS` branch and needs only `--full` added.
**The store guard has no such branch at all** — and §0.3 adds `entry-check --full`, which would be
the first boolean the store guard ever sees. Adding only the constant would close the hole in one
CLI and open it in the other **in the same release**. So: add the constant *and* mirror the branch
into `knowledge_store_command_allowed`.

The arity-derived membership test (walk argparse for `nargs == 0`) cannot detect a missing branch —
it would pass with `--full` legitimately in the set. So P0 also ships a **behavioural** test:
`knowledge_store_command_allowed(['entry-check','--full','--rm'], role)` and
`knowledge_search_command_allowed(['build','--full','--rm'], role)` must both be `False`.

### 0.5 Commit the working tree

`code_fingerprint()` and the `approvedResults`/`nonCurrentResults` split are uncommitted. Every
line anchor in the area specs is a working-tree offset. Commit before P1 starts.

**P0 gate:** full suite green; `validate_harness.py` PASS; a test asserting no kind-level-heuristic
edge is stored `source-exact`; probe re-scan reports ~~**0 laundered edges of 595** (from 414)~~
`[CORRECTED 2026-07-25: 0 laundered, out of 481 kind-level-heuristic edges in 771 stored]`; both
guard fail-opens return `False`; mutating the leaf's vocabulary discards the previous index
generation.

---

## 3. Phase 1 — `belongs-to` (the deadline phase)

**Why it has a deadline.** Verified: `_canonical_facts` (`knowledge_store.py:227-255`) copies
`typeFacts` verbatim into `factsDigest` → `reviewedContentDigest` → the ledger pin. Adding an edge
kind moves that digest for every emitting artifact. The window is open **today** —
`.ai/knowledge/artifacts/` and the ledger do not exist, and `.ai/**` is not gitignored — and
nothing in `compute_lane` would ever detect a late landing. Since P0 §0.1 moves the same digest,
**P0 and P1 share one window and should be one release.**

The reviewed alternative — partitioning containment into a digest-excluded key to remove the
deadline — is **rejected**: it would make containment an unreviewed assertion served as
source-exact, defeating the three-digest boundary. At zero entries the deadline costs nothing.

**Scope (5 types, per D2).** Emit `belongs-to` from the artifact's own path/declaration for
**CustomField** (`parse_field`, via `add_reference` so it dedupes against the existing rollup
`operates-on`), **ValidationRule** (inside the `if object_name:` guard — this is the one type where
the owner may legitimately be absent), **RecordType**, **ApexTrigger**, and **CustomMetadata**
(`parse_custom_metadata_record`, target `<Type>__mdt`). Register in
**`relation_kinds.OBJECT_REF_KINDS`** (the leaf, per §0.2) and `knowledge_registry.OBJECT_REF_KINDS`.
`ALL_REF_KINDS` is derived from `OBJECT_REF_KINDS` and needs no separate edit.

**Correction — the contract test does not pin this choice.** An earlier draft claimed extractor
OBJECT + registry OBJECT was the only classification passing all five assertions. I re-ran them
against each candidate: **two pass**, because
`test_crawl_object_kinds_match_registry_field_and_object_sets` only asserts
`FIELD ∪ OBJECT == extractor OBJECT`, so registry **FIELD** is equally green. That misplacement
would be silent and harmful: `claim_usage()` adds a FIELD-classified target to `usesFields` as well
as its owning object, so `--uses-field Assignment__c` would start matching an *object* name and
`usesFields` would be permanently polluted. P1 therefore ships the missing pin explicitly —
`belongs-to` asserted **in** `knowledge_registry.OBJECT_REF_KINDS` and **not in**
`FIELD_REF_KINDS`, plus a usage-derivation test that a `belongs-to` relation contributes to
`objects` only.

The six missing schema properties (§0.5) must already be declared, or P1's verification cannot
draft the population it needs to count.

`operates-on` is **not** removed anywhere (owner decision D-P1-a below). The point of `belongs-to`
is to stop overloading it, not to relitigate its per-type meaning.

**Verification must not pollute the governed tree.** The draft's steps ran `entry-draft` against
the real repository with cleanup that never touched `.ai/knowledge/artifacts`. A stray committed
entry would close the very window P1 exists to protect and silently flip `entry_home_types()`
repo-wide. Run against a temp root via `knowledge_store.rooted()`; `git status --porcelain .ai
.cache` must print nothing.

**P1 gate — corrected.** The earlier draft of this plan required "CustomObject leaf count 20 → 0",
which is **unachievable by construction and would violate R1**: `belongs-to` is a *child-side*
edge, `parse_object` emits no references at all, and storing the parent side (`contains`) would
require knowing every child — non-local, and a second digest move that re-opens the very approval
window P1 closes. Split the gate:

- **P1 measures the child side:** CustomField entries with zero outgoing edges **63 → 0**.
  CustomObject **stays at 20 by construction** — an expected result, not a failure.
- **P2 measures composition reachability:** all 20 objects return a non-empty `parts` via the
  *inverted* `belongs-to` posting. That is an inbound/derived measurement and never an
  outgoing-edge count.

The P1 completion note records **`N_belongs_to` = new component-relation candidates minted by
`belongs-to`, CustomMetadata included**. Re-measured on the probe corpus with D2 applied:
VR 2 + RecordType 7 + ApexTrigger 5 + CustomMetadata 2 = **16** (the draft's 14 predated D2).
The note is a **required output** consumed by P5's bar, which asserts `582 + N_belongs_to` read
from the note — never a literal.

---

## 4. Phase 2 — index derivation

Reverse-edge postings, build-time target resolution (unresolvable targets stay **visible** — an
unresolvable target is a finding), posting-backed `explain`/`impact` instead of full-corpus scans,
multiplicity restored (drop the `break` that collapses an entry both querying and writing the
anchor to one edge), chain-formatted output showing the path each hop arrived through, and
clamp-**and-report** depth (`depthRequested`/`depthLimit`/`depthReached`/`limitsHit`) replacing
today's silent clamp at 2.

### 4.1 Forward traversal — the gap that unmet a success criterion

Every traversal in the draft was reverse-only. I verified `impact` from `AssignmentTrigger`
returns **0 edges**, because nothing references a trigger. So the strategic plan's third success
criterion — *"how does X work?" answerable by descending from a named parent* — and P4's own
depth-cap rationale (*trigger → handler → queueable → event needs 3–4*) were **unmet by every
command the draft shipped**. An agent asking question (c) would get a set of classes that merely
*mention* the object, presented as a chain, with no execution ordering — precisely the "narrative
presented as Knowledge" the strategic plan's idea-E verdict warns against.

**Fix, and it is cheap:** `--direction outgoing|incoming` (default `incoming`) on the impact/chain
BFS, threaded into `context` and `tree`. No new posting — outgoing edges are already on the
projection, and the resolved `targetIdentity` is exactly the hop function. Per **R6**, the chain
requires `--include-heuristic` and reports per-hop plus path-level assurance.

### 4.1a Lane discipline reaches `explain` and `impact`

Both apply **no lifecycle filter and never hydrate**: verified, `run_explain` loads
`documents.identities()` wholesale and returns the projection verbatim including its `citation`.
So a revoked, drifted or tamper-failing entry that `search` refuses is served in full, with a
citation block, by the two commands golden questions (b) and (c) route through — and P3's `context`
and P4's `tree` are built on the same traversal, so it would propagate into every new surface.
P2 adds: `--state` (default `ESTABLISHED_STATES`), hydrate-before-serve on the anchor and every
served row, a bounded `--top` (default 50) so hydration stays affordable, and the
`approvedResults`/`nonCurrentResults` bucket split already pinned for `search` by `test_g14`.

**P2 also owns the depth-key rename** (`depth` → `depthRequested`/`depthLimit`/`depthReached`)
and the corresponding update to `test_impact_is_bounded_and_labels_static_basis`, which currently
pins `result["depth"] == 2`. No other phase may leave that test broken.

### 4.2 The per-query floor (R4)

`load_index()` → `corpus_fingerprint()` stats every entry file on **every** invocation: measured
11.6 µs/entry → **~174 ms at 15 k** before any query work, multiplied on the team's NTFS+Defender
path. The draft left this unowned and expressed P3's bar as a *ratio to it*, which can never fail.

Two corrections to the draft's own remedy, because it would not have moved the number:

- **Memoisation is a no-op here.** `corpus_fingerprint()` is called exactly once per CLI process
  (`load_index` is the only query-time caller), so per-process memoisation saves nothing in the
  case that was measured. It stays as a P3 optimisation, where the composed `context` call
  genuinely loads the index more than once.
- **A ceiling of 250 ms sits *above* the 174 ms already measured** — it could be certified with
  zero code change. The coarse signal is therefore **mandatory, not licensed**: replace the
  per-file stat sweep with artifacts-root recursive mtime + entry count + ledger stamp +
  `code_fingerprint()`. The docstring already argues this is safe — correctness rests on
  hydration, not on the fingerprint.

**Budget: p95 ≤ 40 ms at 15 k, measured on `windows-latest`** — the team's platform, not the
macOS number this plan was written against. `loadIndexMs` and `corpusFingerprintMs` join
`knowledge_benchmark`.

**The benchmark corpus must also change.** It seeds Flow entries only, so a 15 k run contains
**zero `belongs-to` edges** and cannot exercise `parts`, `context`, `tree` or `feature-drift` at
all. P2 extends it to a mixed corpus (CustomObject + CustomField + ApexClass/ApexTrigger in
package-realistic proportions). Without this, every later budget would be measured on a fixture
where the new code paths are dead.

### 4.3 Disclosure of what the index cannot see (R5)

- **`sourceCoverage`** on every incoming/impact/tree/context result. Only the 10 profiled types can
  appear as an edge *source*, so Profile, Layout, FlexiPage, ApprovalProcess, Workflow and
  DuplicateRule are structurally invisible. Today a field referenced only by a Profile and a Layout
  reports zero incoming edges — which reads as "nothing depends on it".
- **PermissionSet truncation.** `_parse_access_bundle` caps at 300 refs and cuts
  `grants-field-edit`/`grants-field-read` **first**. So question (d) returns a complete-looking
  list that systematically omits every PermissionSet with >300 grants — the normal case in a
  managed package. Roll `referencesTruncated` up into the manifest and emit a mandatory gap.
- **Bytes, not just documents.** The "never reads the whole corpus" test must assert on
  `postingBytesRead` as well as `documentReads` — the draft's counter was blind to posting files
  that reach ~15 MB at 15 k.

**P2 gate:** freshness floor p95 ≤ 40 ms at 15 k on `windows-latest`; `peakRssMb` **budgeted**, not
merely measured; all 20 probe objects return a non-empty `parts`; forward and reverse traversal
both answer; `explain`/`impact` refuse revoked and tampered entries; the hub-regime bar stated as
*behaviour* (`'fanout' in limitsHit`, bounded `nodesServed`) rather than a latency curve measured
in an unrepresentative fixture.

---

## 5. Phase 3 — `context --identity`

The one composed call replacing six heterogeneous queries. Sections: subject projection, `parts`
(inverted `belongs-to`), outgoing/incoming grouped by kind with per-edge assurance, permission
grants, chains, gaps. Lane discipline identical to `search` (`approvedResults`/`nonCurrentResults`
never merged).

Two corrections carried in from review:

- **Cap before hydrating.** The draft hydrated the first 60 rows of the *full* set and *then*
  capped per bucket by a different ordering — so some served rows carried `"hydrated": false`
  while hydrated rows were discarded. Up to ~105 ms spent on rows nobody sees, and the rows the
  caller is invited to cite are the ones **not** re-verified. Swap the order.
- **`partsCoverage` (R5).** `parts` enumerates artifacts that *happen to have an entry*, not the
  object's declared composition. On a 5 %-coverage corpus an object looks like it has five fields.
  Emit the denominator and a standing gap pointing at `entry-coverage`. This is the single most
  likely way the new commands mislead in practice.

Naming: `knowledge_store.py entry-context` (authoring surface) and `knowledge_search.py context`
(retrieval pack) both stay, documented and pinned.

**Budget (R4):** `context --identity` p95 ≤ 400 ms and a stated `peakRssMb` ceiling at 15 k on
`windows-latest`, measured on P2's mixed benchmark corpus. Depth is `DEPTH_LIMITS["context"] = 1`
(R7). New test class is `ContextCommandTests(EntryFixtureMixin, unittest.TestCase)` per R2 — never
inheriting `KnowledgeSearchTests`, which would re-run the golden suite and silently run it against
a fixture it was not written for.

---

## 6. Phase 4 — Feature Entry + tree

**P4 owns the Feature Entry entirely** (R2); P5 consumes its values. The draft had two areas
specifying incompatible ledgers, identity grammars, schemas, command names, hook messages and
error strings — unimplementable, and every one of them a security-boundary or approval-record
decision made twice.

Approved content is the **boundary rule** (anchors, hubs, depth, include/exclude,
`membershipAssuranceFloor`) plus a human description. Membership is recomputed, never approved.

Three corrections from review:

- **Membership must be lane-filtered.** Postings contain draft, revoked and not-effective entries;
  the draft's `compute_membership` took no lane argument. An approved feature's tree would present
  drafts as members with citation blocks, and the drift baseline would invert: `changed: true` when
  someone drafts an unrelated entry, `changed: false` when a real member is approved.
- **The baseline stays out of the ledger.** The draft wrote up to 2 000 index-derived identities
  into an append-only, human-attributed approval record — content the reviewer was explicitly told
  they were *not* approving, derived from a cache the constraints call "never authority". It goes
  to `.cache/` or the advisory review artifact.
- **Truncation answers honestly.** `changed: null` on any large feature makes the command useless
  exactly where features matter. The traversal is deterministic, so report
  `changedWithinTruncatedPrefix` with `truncated: true`.

One traversal-limits vocabulary and one hydration budget shared across `impact`, `context`, `tree`
and `drift` — with **per-command depth values** (R7), not one value pretending to fit four
commands.

**Four things the draft left unstated, each of which an implementer would otherwise invent:**

- **Where Feature Entry files live, and that they are governed.** `.ai/knowledge/features/<slug>.md`
  — *outside* `ARTIFACTS_ROOT`, so `all_entry_paths()` and `corpus_fingerprint()` never see them
  (this is also the fourth incidental block against a Feature being cited as an `entryRef`, and it
  must stay true). D4 governed only the ledger; the **file** needs its own
  `is_governed_record_path` arm in the same commit, or an agent can rewrite an approved boundary
  through the ordinary Write path with no refusal — a direct breach of "agents never self-approve".
- **Where the membership baseline lives, given §6 ruled it out of the ledger.** The ledger record
  pins a **`membershipDigest` only** — a digest is not a member list and cannot re-approve on
  drift. The identity list lives in `.cache/`, written by `tree`.
  ~~On a Windows team with per-developer caches the normal case is a machine that never held the
  approver's cache, so `feature-drift` with an absent or foreign baseline returns `baseline: null`,
  **`changed: "unknown"`** and a gap naming the reason.~~ **`[CORRECTED 2026-07-25, wave 3: this
  bullet disagreed with contract §13.7 and with the shipped `run_feature_drift`.]`** The two homes
  answer two different questions and conflating them is what makes the command useless on exactly
  the machine that needs it: **`changed` comes from the ledger digest**, so it still answers on a
  machine that never held the approver's cache — the normal Windows case — and an absent or foreign
  cache withholds only the **added/removed detail**, reported as a gap naming the remedy. `changed`
  is **`"unknown"`** when the ledger pins no `membershipDigest` or the feature is not approved, and
  is **never `false`** for a missing baseline, which is the exact inversion §6 exists to prevent.
  **Contract §13.7 is the normative statement of this split; this bullet must not disagree with it.**
- **`feature-approve` may succeed with a stale or absent index**, recording a null baseline. A
  governed human approval must not be blocked by a disposable cache.
- **The public-surface requirement.** A live test requires every `knowledge_store` subcommand to
  appear in a prompt/skill/agent or be declared in `NOT_ON_PUBLIC_SURFACE` with a CI assertion.
  **Ruling:** the feature commands are documented inside the existing `curate-knowledge` prompt and
  `approve-knowledge-drafts` skill — **no new prompt or skill**, so `EXPECTED_COUNTS` and the
  repo-map word budget stay pinned at 24/25/6/3. `feature-check` joins `NOT_ON_PUBLIC_SURFACE`
  with its CI assertion in the same commit.

**Budget (R4):** `tree` and `feature-drift` each state an absolute p95 and `peakRssMb` at 15 k on
`windows-latest`. `assert_no_reparse_points()` is scoped to `FEATURES_ROOT` for the feature
commands — a single-file `feature-status` must not walk the entire 15 k-file knowledge tree.

---

## 7. Phase 5 — legacy machinery · Phase 6 — consumers

**P5.** `relations-worklist` gains `homed-in-entry` so the loop can terminate; `relations-draft`
counters can never exceed what was written; `relation-health` gains an entry-edge population —
computed through `compute_lane`, **not** a raw frontmatter read, because contract §4 is explicit
that reading frontmatter never establishes approval (a file with `state: approved` and no ledger
record, or a revoked entry, would otherwise be reported as approved); `render_dossier` reads
descriptions from approved entries. Acceptance bar is **`582 + N_belongs_to`** homed-in-entry,
not 582 — the draft's number predated P1. ~~(≈596)~~ **`[CORRECTED 2026-07-25]` No parenthetical
figure. §7 said ≈596 and §8 said ≈598 for the same quantity, and both were wrong by the time P5
ran: the corpus figure is 665, because P2's `APEX_NEW_RE` minted ~67 further `invokes-class`
candidates after either number was written. The count is a property of the corpus *and* of the
extractor and moves whenever either does — which is why this plan told P5 to read
`docs/knowledge-p1-completion-note.md` rather than a literal. Only `N_belongs_to = 16` is fixed.
Read the note; assert against the note; never restate the total here.**

**P6.** Rewire the consumer surfaces — **11 files / 12 occurrences** of `knowledge_registry.py
query`, not the 7 the strategic plan stated. Two-layer rule preserved, with one correction:
**keep `--uses-object` / `--uses-field`** alongside the entry queries. Dropping them would make
Workflow, ApprovalProcess, Layout, FieldSet and every other unprofiled type invisible to a coverage
gate, with no gap line — a completeness regression in exactly the surfaces SAFE-EVID-001 governs.

**The gate is two counted sets, not "12 of 12".** Several of those 12 occurrences are the
*correct* layer-2 call this plan says to preserve, so a single 12/12 target would demand converting
exactly what §7 protects:

- **Set A — step-1 *source* lookup is the `knowledge_context` MCP tool** (10 surfaces):
  `solution-design`, `check-against-principles`, `check-feature-coverage`, `adhoc-fix`,
  `investigate-config-records`, `generate-technical-documentation`, `investigate-object`,
  `suggest-test-cases`, `development-assistant.agent.md`, `test-strategist.agent.md`.
- **Set B — stays layer-2, each with its stated reason**: `search-knowledge` step 2 (org/runtime/
  business/vendor questions), `batch-knowledge` (drill-downs), `propose-force-app-knowledge`
  (duplicate check while authoring v1 claims), plus every `--uses-object`/`--uses-field` call
  retained for unprofiled types.

Both counts are asserted. Neither is allowed to move silently.

Set A revision 2026-08-04 (owner decision, with the Knowledge MCP server): the step-1
surface moved from the CLI literal to the knowledge_context MCP tool, because two competing
lanes in agent-facing text rot into bypass — the v1-retirement lesson. The CLI menu survives
only in search-knowledge as the operator fallback, which stays deliberately outside Set A.
investigate-object and suggest-test-cases had adopted the step-1 lookup after this plan was
written and join the counted set (8 → 10).

**Each Set A surface owes two things, and the gate must count both.** `context --identity` is only
half of a correct step-1 lookup: a row carrying `hydrated: false` failed re-reading and is not a
fact (contract §14.2), so a surface that names the command but not the rule lets an agent cite a
row the index could not re-read — the retrieval defect P0–P4 spent four phases making visible,
re-introduced at the last hop. **`[ADDED 2026-07-25, wave 3.]`** This is not hypothetical: wave 2
reported the rule present in all eight Set A surfaces and `grep -rl hydrated .github/` returned
**two** — a claim about a set, made without counting the set, which is the failure mode §7 already
exists to stop. The gate therefore asserts **two tokens per Set A surface** — `context --identity`
and `hydrated` — over the surfaces this section names, never over a list kept beside it. The whole
check is that `grep -rl hydrated .github/` returns the eight Set A surfaces plus `search-knowledge`.
**`[ENFORCED 2026-07-26, wave 4.]`** Both tokens are now actually asserted:
`validate_harness.check_knowledge_consumer_sets` carries `SET_A_CALL` **and**
`SET_A_HYDRATION_RULE = "hydrated"`, one `audit.require` each over the set parsed from this
section — 8 surfaces × 2 = 16 assertions, and `grep -rl hydrated .github/` returns exactly the 9
files named above. Until then the second token was stated here and checked nowhere, which is the
same shape as the defect it describes.

Neither phase may describe a generated view as citable: the dossier and search results carry
"obtain the citable ref with `entry-status --identity`", never a hand-built `entryRef` (the
projection's `profileDigest` is a content digest and `validate_entry_refs` rejects it outright).

---

## 8. Acceptance criteria

Golden questions, traced end to end:

| # | Question | Today | Required | Phase |
|---|---|---|---|---|
| a | What is `Assignment__c` made of? | 3 different query shapes; VR/RecordType need reading a `fullName` prefix | one call, uniform, **with the coverage denominator** | P1+P2+P3 |
| b | What breaks if I change `Health_Score__c`? | works; depth silently clamped; no hop provenance; serves revoked entries | chain, per-hop assurance, reported limits, `sourceCoverage`, lane-filtered | P2 |
| c | How does conflict detection work? | **0 edges** — reverse-only traversal | forward chain, execution order — **with `--include-heuristic`, per-hop + path `minAssurance`** (~~58/59 chain edges are `invokes-class`~~ `[CORRECTED 2026-07-25: 82 % of the forward closure is kind-level heuristic; without the flag `AssignmentTrigger`'s citable `nodes` collapse from 8 to 1 — corpus, command and payload key in R6]`) | P2 §4.1 |
| d | Which permission sets grant edit? | multiplicity collapsed; >300-grant sets silently missing | all edges + mandatory truncation gap | P2 |
| e | What is in the feature, and what is only inferred? | 23/29 heuristic members shown flat and unlabelled | per-node assurance; below-floor summarised; **heuristic members require the flag** | P0+P4 |
| f | Is there approved knowledge at all? | lanes separated | preserved | — |

Structural gates:

| Gate | Today | Required |
|---|---|---|
| Edges laundering heuristic as source-exact | ~~**414 / 595**~~ `[CORRECTED: 481 kind-level-heuristic edges of 771 stored, all laundered before P0]` | **0** (P0) — an absolute count, never a ratio |
| CustomField entries with zero outgoing edges | 63 / 93 | **0** (P1) |
| CustomObject entries reachable by composition | 0 of 20 (leaves) | **20 of 20 return non-empty `parts`** via inverted `belongs-to` (P2 — never an outgoing-edge count, see §3) |
| Guard fail-open on a boolean flag | `build --full --rm` → **True** | `False` in both guards (P0) |
| `relations-worklist` missing | 582, loop cannot terminate | 0 missing / `582 + N_belongs_to` homed-in-entry, **read from `docs/knowledge-p1-completion-note.md`, never from a literal** — ~~(≈598)~~ `[CORRECTED 2026-07-25: parenthetical removed; it disagreed with §7's ≈596 and both predate the post-P2 total of 665 the note records]` |
| `relations-draft` counter honesty | reports 50, writes 0 | never exceeds `claimCount` |
| `relation-health` on rotting entry edges | `HEALTHY` unconditionally | lane-computed, orphans reported |
| Dossier descriptions | 64 / 64 "pending" | from approved entries |
| Consumers: step-1 source lookup on the entry index | 0 of 8 (Set A) | 8 of 8 |
| Consumers: legitimate layer-2 calls preserved | — | Set B unchanged, each with its reason |
| Per-CLI freshness floor at 15 k | ~174 ms, unowned | **p95 ≤ 40 ms on `windows-latest`** (P2) |
| CI gate at >8 700 entries | uncaught `TimeoutExpired` | legible failure + incremental check |
| Benchmark corpus | Flow-only → 0 `belongs-to` edges at any scale | mixed corpus exercising every new traversal |

Invariants after every phase: full suite green; validator PASS; index never authority; no agent
self-approval; heuristic never presented as exact; locality rule holds; approving an unrelated
artifact never drifts an existing approved entry.

---

## 9. Owner decisions — SETTLED 2026-07-25

All seven blocking decisions are closed. They are now constraints on implementation, not options.

**Settled before P0/P1:**

| # | Decision | Ruling | Consequence for implementation |
|---|---|---|---|
| D1 | P0 + P1 release shape | **One release, before any entry approval** | The digest window is closed by a single commit pair. No entry may be approved until both land — the alternative (excluding containment from `factsDigest`) was rejected because it would serve an unreviewed assertion as source-exact |
| D2 | CustomMetadata emits `belongs-to`? | **Yes, emit** | Adds a fifth emitting type to P1. `parse_custom_metadata_record` already derives the type from its own path, so this is locally derivable and the strategic plan's "no owner" claim was factually wrong. `N_belongs_to` in the P1 completion note must include CMDT records |
| D3 | Remove `operates-on` from VR/RecordType/ApexTrigger? | **No — additive only** | `operates-on` keeps its per-type meaning everywhere. `component_objects()`, `feature_crawl` and `claim_usage()` are untouched by P1, so any boundary shift in P5's `test_feature_documentor.py` is attributable to `belongs-to` alone |

**Settled before P4:**

| # | Decision | Ruling | Consequence for implementation |
|---|---|---|---|
| D4 | Feature ledger location | **Separate `.ai/knowledge/features-ledger.jsonl`** | Must be added to `is_governed_record_path` and to `feature-check`'s sequence/orphan validation. Keeps `corpus_fingerprint`'s reuse key untouched by feature approvals — a shared ledger would discard the whole artifact index on every one |
| D5 | Identity grammar | **`Feature:<slug>` — two segments** | Propagate into the safety-hook regex, the `^(?!Feature:)` lookahead in all three envelope schemas, the ledger record and every refusal message. Two segments cannot satisfy `work_record.entry_relative_path`'s unpack, so a Feature identity fails loudly instead of resolving to a nonexistent path under `ARTIFACTS_ROOT` |
| D6 | Membership-delta command name | **`feature-drift`** | The existing public `/feature-health` slash command (agent `test-strategist`, ADO Feature/BRD story coverage) is untouched. Name is consistent with the `approved-drifted` lane vocabulary |
| D7 | Contract section number | **§13; §12 reserved for parity certification** | The pre-existing dangling reference at line 398 keeps its intended meaning and needs no edit. Every shipped executor error string, schema `description` and skill line cites §13 |

**Still open (non-blocking, decide during implementation):** ~~collector version bump to 1.7.0
(inert but conventional)~~; ~~node/fanout/row/time traversal limits (set them from the P2
benchmark)~~ — **depth values are NOT among them**, they are semantic requirements fixed by R7;
`impact --format` default (recommend `chain`); whether `explain`/`impact` survive P3 (recommend
keep, revisit after P6 shows whether any consumer still calls them).

**`[CLOSED 2026-07-26, wave 4 — the two struck items above.]`** `COLLECTOR_VERSION` is `1.7.0`.
The traversal limits are now **set from the P2 benchmark**, which is what this line asked for and
what the completion audit called chosen constants: `knowledge_benchmark.traversal_observations`
walks the shipped `traverse()` over a hub / chain / leaf regime, `TRAVERSAL_LIMIT_BASIS` states one
uniform rule — no limit below **3×** the worst legitimate walk projected to 15 k — and
`assert_traversal_limits` re-checks it on every `--assert-command-budgets` run. Shipped:
`TRAVERSAL_LIMITS = {"maxNodes": 5000, "maxFanout": 2000, "maxSeconds": 2.0}`. The **time** limit
this line asked for now exists; a walk that trips it is disclosed through the same vocabulary as
the others, `limitsHit: ["time"]`, and it sits deliberately above every per-command p95 ceiling
because it terminates pathology rather than budgeting latency. Measurement and headroom: see
`docs/knowledge-completion-audit-2026-07-25.md` § Disposition (Method M1).

### 9.1 Gap-analysis outcome (2026-07-25)

Three lenses re-attacked this plan after the owner decisions landed and returned 36 gaps, all
three verdicts NOT-READY. I re-verified the load-bearing ones by measurement before accepting
them; the plan text above now carries every blocking and major gap. Four were errors **in this
plan**, not in the underlying design, and are worth naming because they were the ones a reviewer
was most likely to trust:

1. The P1 exit gate ("CustomObject leaves 20 → 0") was **unachievable by construction** and would
   have forced the implementer to violate R1 to pass it.
2. §0.2 moved `HEURISTIC_REF_KINDS` but not `OBJECT_REF_KINDS`, from which `ALL_REF_KINDS` is
   derived — a circular dependency inside the single commit that must close the digest window.
3. The leaf module was never added to `code_fingerprint()`, so editing the vocabulary would have
   changed no fingerprinted byte and the index would have gone on serving the old assurance —
   the one defect P0 exists to fix, silently un-invalidatable.
4. §0.1 justified its central rule by citing contract §5.5, which is **not implemented**. The true
   argument is stronger: nothing detects an assurance regression after approval *at all*.
5. §0.1 also said the assurance helper is "imported by the search projector" — wrong, and
   self-contradictory with the next clause. The projector already reads the stored marker verbatim.
6. The claim that `test_kind_contract.py` pins `belongs-to`'s registry classification is **false**;
   I re-ran all five assertions and registry `FIELD_REF_KINDS` is equally green, which would
   silently pollute `usesFields` with object names. P1 now ships the missing pin.

Two were genuine design gaps neither the strategic plan nor the area specs caught:

- After P0 marks `invokes-class` heuristic, ~~**58 of 59 forward-chain edges**~~ `[CORRECTED: 82 %
  of the depth-2 forward closure — see R6]` become opt-in, so
  golden question (c) needed an explicit assurance policy (**R6**) rather than an implied answer.
- Six facts the collector emits are rejected by three profile schemas (§0.5), so `entry-draft`
  fails on normal shapes. My probe corpus contains none of them — the same way the CustomField
  third of this gap survived unnoticed until now.

---

## 10. Sequencing

```
P0  fix merged defects      ─┐ one release, one digest window
P1  belongs-to              ─┘ MUST precede the first entry approval
P2  index derivation          owns: freshness floor, forward traversal, lane discipline on
                              explain/impact, DEPTH_LIMITS + the depth-key rename, the
                              EntryFixtureMixin refactor, run_capabilities, the SKILL.md
                              placeholder block, the mixed benchmark corpus
P3  context                   HARD on P2 (reads its postings; a soft dependency would read
                              a relations.json shape P2 replaces and silently return empty)
P4  Feature Entry + tree      needs P0 §0.3 landed first (no second grounding subprocess)
P5  legacy machinery          acceptance = 582 + N_belongs_to, read from the P1 note
P6  consumers                 owns the SKILL.md prose; two counted sets, both layers kept
```

## 11. Not in scope

No change to the claim registry's org-observation path; no removal of v1 relation claims for
unprofiled types; no deployment, org reads or Screen Validation; no new approval authority for
agents; no coverage gate (deferred — with 0 approved entries a gate blocks all work and
incentivises rubber-stamping).
