# Master implementation plan — Knowledge relations, composition and the feature tree

Date: 2026-07-25 · Status: **owner decisions settled (§9), ready to implement** · Supersedes the phasing in
`docs/knowledge-usefulness-plan-2026-07-24.md` (that document remains the strategic rationale;
this one is the executable plan)

## How this plan was produced, and what changed

Six areas were specified independently against the real code, then attacked by three adversarial
reviews (ordering/dependency, governance/contract, scale/does-it-answer). All three returned
**NOT-READY** on the combined draft — 37 findings, 9 of them blocking. That verdict was on the
*draft*, and it did its job: the conflicts below are resolved here, and four defects the
strategic plan never saw are now the first things that ship.

I independently re-verified the four load-bearing findings rather than taking them on trust:

| Claim | My verification | Result |
|---|---|---|
| 70 % of stored edges launder heuristic inference as `source-exact` | scanned the 189-entry probe index against `HEURISTIC_REF_KINDS` | **414 of 595 edges** stored `source-exact`; **0** stored honestly |
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
| `.github/skills/search-knowledge/SKILL.md` command menu | **P6** | appends one line to a fixed placeholder block |
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

---

## 2. Phase 0 — fix what is already broken (NEW, blocks everything)

None of this is in the strategic plan. All of it is live defect in merged code.

### 0.1 Heuristic laundering at the approval boundary — **the most severe item in this plan**

`knowledge_store._edges` (`scripts/knowledge_store.py:606-615`) derives edge assurance from the
per-edge `heuristic` flag only. The collector never sets that flag for kind-level heuristics, so
every `object-token`, `invokes-class`, `var-field-ref` and `soql-field` edge is stored
`source-exact`. Measured: **414 of 595 probe edges**, 0 stored honestly.

Consequences, in order of severity:

1. `assurance.typeFacts` is inside `factsDigest`, so a human **approves** the false marker.
2. SAFE-CLAIM-001 v2 grounds work records on sections marked `source-exact` with full coverage —
   so a design document can ground "ApexClass X operates on Assignment__c" on a **comment mention**.
3. `--include-heuristic` is largely a no-op: my earlier probe excluded exactly **1** edge for
   `Assignment__c` while 6 of its 7 incoming edges were kind-level heuristics.
4. The `search-knowledge` skill promises "heuristic edges stay out unless `--include-heuristic`".
   That promise is currently false for 70 % of them.

**Fix.** Fold `kind in HEURISTIC_REF_KINDS` into the stored assurance in `_edges` and
`flow_type_facts`. This is **mandatory and not deferrable** — the draft offered it as an optional
rider (A1 D4, A3 alternative 1); both are deleted. It must be the **single** implementation: one
helper in the store, imported by the search projector, never re-derived query-side, because a
projection-time override would silently downgrade an approved entry's assurance with no lane
movement — and contract §5.5 makes an assurance regression `approved-drifted`.

### 0.2 Kind vocabulary moves to a leaf module

`HEURISTIC_REF_KINDS` / `ALL_REF_KINDS` move into a small leaf module imported by both
`force_app_knowledge` and `knowledge_store`/`knowledge_search`. Without this, folding the
vocabulary into `code_fingerprint()` would mean fingerprinting the 6 542-line collector — turning
every P1/P5/P6 collector edit into a **~105 s full reprojection at 15 k** instead of a ~0.2 s
incremental one. `tests/test_kind_contract.py` pins the leaf as the single source.

### 0.3 CI gate fails legibly and incrementally

`validate_harness.py:872` runs `entry-check` under `timeout=30` with no handler. Measured
`compute_lane` ≈ 3.45 ms/entry → ~52 s at 15 k, crossing 30 s at **~8 700 entries** — inside the
target range. Wrap the loop in `except subprocess.TimeoutExpired` → `audit.require(False, …)`, and
make `entry-check` incremental (stamp-compare, `--full` for nightly). **No second grounding
subprocess may be added until this lands** — that rules out wiring `feature-check` in P4 first.

### 0.4 Role-guard valueless-flag fix

`knowledge_search_command_allowed(['build','--full','--rm'], role)` returns **True** today: the
guard advances the index by 2 unconditionally, so the token after a boolean flag is never
validated. Add `--full` to `KNOWLEDGE_SEARCH_VALUELESS_FLAGS`, introduce
`KNOWLEDGE_STORE_VALUELESS_FLAGS`, and replace hand-listing with a test that walks argparse for
`nargs == 0` — making every future boolean self-enforcing (R3).

### 0.5 Commit the working tree

`code_fingerprint()` and the `approvedResults`/`nonCurrentResults` split are uncommitted. Every
line anchor in the area specs is a working-tree offset. Commit before P1 starts.

**P0 gate:** full suite green; `validate_harness.py` PASS; a test asserting no
kind-level-heuristic edge is stored `source-exact`; probe re-scan reports **0 laundered edges of
595** (from 414).

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
`force_app_knowledge.OBJECT_REF_KINDS` and `knowledge_registry.OBJECT_REF_KINDS` — verified this is
the **only** classification of four candidates that satisfies all five assertions in
`test_kind_contract.py` without editing the test. `ALL_REF_KINDS` is derived and needs no edit.

`operates-on` is **not** removed anywhere (owner decision D-P1-a below). The point of `belongs-to`
is to stop overloading it, not to relitigate its per-type meaning.

**Verification must not pollute the governed tree.** The draft's steps ran `entry-draft` against
the real repository with cleanup that never touched `.ai/knowledge/artifacts`. A stray committed
entry would close the very window P1 exists to protect and silently flip `entry_home_types()`
repo-wide. Run against a temp root via `knowledge_store.rooted()`; `git status --porcelain .ai
.cache` must print nothing.

**P1 gate:** CustomObject and CustomField leaf counts go **20 → 0** and **63 → 0**; the P1
completion note records `N_belongs_to` (measured +14 relation candidates on the probe corpus) —
a **required output** consumed by P5's acceptance bar.

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
projection, and the resolved `targetIdentity` is exactly the hop function.

### 4.2 The per-query floor (R4)

`load_index()` → `corpus_fingerprint()` stats every entry file on **every** invocation: measured
11.6 µs/entry → **~174 ms at 15 k** before any query work, per process, multiplied on the team's
NTFS+Defender path. The draft left this unowned and expressed P3's bar as a *ratio to it*, which
can never fail. **P2 owns it with an absolute ceiling** (p95 ≤ 250 ms at 15 k), memoised per
process, `loadIndexMs`/`corpusFingerprintMs` added to the benchmark. The docstring's own argument
licenses a coarser signal: correctness rests on hydration, not on the fingerprint.

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

**P2 gate:** absolute latency ceiling met; `peakRssMb` measured at a 15 k scale run; forward and
reverse traversal both answer; the hub-regime bar stated as *behaviour* (`'fanout' in limitsHit`,
bounded `nodesServed`) rather than a latency curve measured in an unrepresentative fixture.

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

One traversal-limits constant and one hydration budget shared across `impact`, `context`, `tree`
and `drift` — not four vocabularies.

---

## 7. Phase 5 — legacy machinery · Phase 6 — consumers

**P5.** `relations-worklist` gains `homed-in-entry` so the loop can terminate; `relations-draft`
counters can never exceed what was written; `relation-health` gains an entry-edge population —
computed through `compute_lane`, **not** a raw frontmatter read, because contract §4 is explicit
that reading frontmatter never establishes approval (a file with `state: approved` and no ledger
record, or a revoked entry, would otherwise be reported as approved); `render_dossier` reads
descriptions from approved entries. Acceptance bar is **`582 + N_belongs_to`** homed-in-entry
(≈596), not 582 — the draft's number predated P1.

**P6.** Rewire the consumer surfaces — **11 files / 12 occurrences**, not the 7 the strategic plan
stated. Two-layer rule preserved, with one correction: **keep `--uses-object` / `--uses-field`**
alongside the entry queries. Dropping them would make Workflow, ApprovalProcess, Layout, FieldSet
and every other unprofiled type invisible to a coverage gate, with no gap line — a completeness
regression in exactly the surfaces SAFE-EVID-001 governs.

Neither phase may describe a generated view as citable: the dossier and search results carry
"obtain the citable ref with `entry-status --identity`", never a hand-built `entryRef` (the
projection's `profileDigest` is a content digest and `validate_entry_refs` rejects it outright).

---

## 8. Acceptance criteria

Golden questions, traced end to end:

| # | Question | Today | Required | Phase |
|---|---|---|---|---|
| a | What is `Assignment__c` made of? | 3 different query shapes; VR/RecordType need reading a `fullName` prefix | one call, uniform, **with the coverage denominator** | P1+P3 |
| b | What breaks if I change `Health_Score__c`? | works; depth silently clamped; no hop provenance | chain, per-hop assurance, reported limits, `sourceCoverage` | P2 |
| c | How does conflict detection work? | **0 edges** — reverse-only traversal | forward chain, execution order | P2 §4.1 |
| d | Which permission sets grant edit? | multiplicity collapsed; >300-grant sets silently missing | all edges + mandatory truncation gap | P2 |
| e | What is in the feature, and what is only inferred? | 23/29 heuristic members shown flat and unlabelled | per-node assurance; below-floor summarised | P0+P4 |
| f | Is there approved knowledge at all? | lanes separated | preserved | — |

Structural gates:

| Gate | Today | Required |
|---|---|---|
| Edges laundering heuristic as source-exact | **414 / 595** | **0** |
| Entries with zero outgoing edges | 88 / 189 | 0 CustomObject, 0 CustomField |
| `relations-worklist` missing | 582, loop cannot terminate | 0 missing / ≈596 homed-in-entry |
| `relations-draft` counter honesty | reports 50, writes 0 | never exceeds `claimCount` |
| `relation-health` on rotting entry edges | `HEALTHY` unconditionally | lane-computed, orphans reported |
| Dossier descriptions | 64 / 64 "pending" | from approved entries |
| Consumers reaching the entry index | 1 of 12 occurrences | 12 of 12, both layers kept |
| Per-CLI freshness floor at 15 k | ~174 ms, unowned | absolute ceiling, owned by P2 |
| CI gate at >8 700 entries | uncaught `TimeoutExpired` | legible failure + incremental check |

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

**Still open (non-blocking, decide during implementation):** collector version bump to 1.7.0
(inert but conventional); traversal-limit values (proposed, not derived — set them from the P2
benchmark); `impact --format` default (recommend `chain`); whether `explain`/`impact` survive P3
(recommend keep, revisit after P6 shows whether any consumer still calls them).

---

## 10. Sequencing

```
P0  fix merged defects      ─┐ one release, one digest window
P1  belongs-to              ─┘ MUST precede the first entry approval
P2  index derivation          (owns the freshness floor + forward traversal)
P3  context                   (consumes P2)
P4  Feature Entry + tree      (needs P0 §0.3 landed first)
P5  legacy machinery          (acceptance = 582 + N_belongs_to)
P6  consumers                 (owns the SKILL.md menu; keeps both layers)
```

## 11. Not in scope

No change to the claim registry's org-observation path; no removal of v1 relation claims for
unprofiled types; no deployment, org reads or Screen Validation; no new approval authority for
agents; no coverage gate (deferred — with 0 approved entries a gate blocks all work and
incentivises rubber-stamping).
