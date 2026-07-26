# Completion audit — is the Knowledge master plan done?

> **Findings below are the record as audited and are NOT edited.** What closed each one is recorded
> in **[§ Disposition](#disposition-2026-07-25-after-remediation-waves-1-2-and-3-re-measured-2026-07-26-wave-4)** at the end. Read
> the finding for what was broken and the disposition row for where it stands. **The disposition is
> the only place this project states current status** — if a status line anywhere else disagrees
> with it, the status line is the stale one.

Date: 2026-07-25, last re-measured 2026-07-26 · Status **as audited**: **NOT COMPLETE — 6
blocking, 14 major** · Status **after remediation waves 1–4**: all 6 blocking and all 14 major
closed, and every "also open, minor" item with them; **7 items remain open**, none of them a known
defect: two wait on a `windows-latest` run, two are open by design until the first real approval,
two are built but unexercised, one is an owner decision — and every one is named in § Disposition →
Still open and nowhere else. The verdict on the plan as a whole is § Is the master plan complete?
· Scope: P0–P6 as shipped on `knowledge-relations-p0-p6` (25 commits, HEAD `0edc9c1`), plus four
uncommitted remediation waves in the working tree
· Supersedes the status line in `docs/knowledge-phase-audit-2026-07-25.md`, which read "P4 remains
BLOCKED" after P4 merged and has since been struck through there

## Is the master plan complete?

**No — and the honest answer has three parts, because a single word here is what undid the last
three waves of this project.** Each part below says what the evidence actually supports.

**1. Done, verified by execution on this machine.** Every gate in
`docs/knowledge-master-plan-2026-07-25.md` §8 — both tables, R1–R7, D1–D7, §10's sequencing — has
a behaviour behind it and an assertion pinning that behaviour. All **6 blocking** and all **14
major** findings in this document are closed, and all six of the "also open, minor" items are too.
The strongest positive result is unchanged and reproduces: the whole chain composes on the
189-component reference corpus — 189 collected → drafted → described → approved → `entry-check`
PASS → 189/189 `approved-current` → indexed → golden questions answered → `entryRef` bound and
validated → a source edit refuses the citation. The P0 headline gate (**0 laundered edges**)
reproduces from three independent paths. That is the part of "complete" that is earned.

**2. Verified only off-platform.** Every performance number this project has ever recorded is
macOS (Method M1). The plan budgets §4.2's freshness floor, §5's `context` and §6's `tree` /
`feature-drift` **at 15 k on `windows-latest`**, the team is Windows-only, and that leg has never
run — not once, in any wave. The Windows peak-RSS instrument is a different code path
(`kernel32.K32GetProcessMemoryInfo`) that has met only a doubled `kernel32` in a unit test. The
gates are also measured at 3 000 entries, not 15 k, with the projection done by arithmetic. So the
budgets are *implemented, asserted and green* — and *unverified where they are stated*. Those are
not the same claim and this document will not merge them again.

**3. Open by design until the first approval.** `.ai/knowledge/artifacts` is empty and must stay
so until a human approves the first entry. Every `validate_harness.py` PASS (2 647 checks) and
every `entry-check` PASS in this repository is therefore collected over **zero entries**: the
grounding checks run on an empty corpus and prove the plumbing, not the knowledge. The 189-entry
runs recorded throughout are temp-root substitutes. Golden (d) is in the same category one step
narrower — it is exercised end to end, but by a purpose-built 317-`fieldPermission` fixture rather
than by real package data.

**What that adds up to.** The plan is complete as *built* and incomplete as *verified*. Nothing
known is broken; nothing blocks the first entry approval mechanically (§ "Is the harness ready for
the first entry approval?" still governs whether it is safe); and the whole remaining gap is one
green `windows-latest` run away from being measurable, plus one real approval away from being
exercisable. Every item behind that judgement is listed once, with what would close it, in
§ Disposition → Still open — and nowhere else.

## Method, and why it is different from the last two audits

Every gate in `docs/knowledge-master-plan-2026-07-25.md` — §8's two tables, §1's R1–R7, §9's
D1–D7, §10's sequencing — was checked **by execution**, against the plan's own wording rather than
a list assembled while checking. Ten independent auditors ran the commands; every non-MET finding
was then handed to a hostile verifier instructed to refute it; a final critic re-attacked the audit
itself.

That last step earned its keep. It overturned five verdicts and found two defects that sat in the
seam between phases, where no single dimension owned them. Its central process finding:

> Every dimension audited its own phase on its own corpus. The pilot corpus computes as
> `approved-drifted` everywhere (its `force-app` tree is absent), so **no dimension except the
> critic ever exercised the default `approved-current` lane end to end.** A gate one dimension
> could not measure was scored UNVERIFIABLE instead of being handed to the dimension that already
> had the corpus.

The critic ran the whole chain once on one corpus — 189 components collected → 189 drafted → 189
approved → `entry-check` PASS → 189/189 `approved-current` → index → golden questions → `entryRef`
bound and validated → source drift refuses the citation. **The chain composes.** That is the
strongest positive result in this audit, and it is the reason the remaining defects are fixable
rather than structural.

## Verdict by phase

| Phase | Verdict | Blocking | Major |
|---|---|---|---|
| P0 fix merged defects | **complete** | 0 | 1 |
| P1 `belongs-to` | **complete** | 0 | 0 |
| P2 index derivation | incomplete | 3 | 5 |
| P3 `context --identity` | incomplete | 0 | 2 |
| P4 Feature Entry + tree | **incomplete — weakest phase** | 2 | 5 |
| P5 legacy machinery | incomplete | 0 | 1 |
| P6 consumers | incomplete | 0 | 2 |
| Cross-phase (seams) | incomplete | 1 | 2 |

P0's headline gate holds and reproduces from three independent paths: **0 laundered edges**, on
collector output and on 189 stored, approved projections. P1 reproduces to the digit — 109
`belongs-to` edges, CustomField zero-outgoing 63 → 0, `N_belongs_to` = 16 with CMDT included.
Everything downstream of P2 shipped with real behaviour and incomplete gates.

## Blocking

### B1 · `impact` never verifies or hydrates its anchor — it serves revoked and tampered entries

§4.1a is titled *"Lane discipline reaches `explain` and `impact`"*. It reached `explain`. `grep -rn
verify_anchor` returns three sites: the definition, `run_explain`, `run_context`. `run_impact` calls
neither `verify_anchor` nor `hydrate`; `traverse()` fetches the anchor document unconditionally and
lane-filters only *reached* nodes.

Executed: `impact --direction outgoing --include-heuristic` on a **revoked** anchor returns
`outcome: IMPACT` with a gap list byte-identical to the pre-revocation baseline. Same for an anchor
tampered at constant length and mtime. A tampered *dependency row* that `context` catches
(`hydrated: false` + gap) is served silently. `AnchorVerificationTests` iterates literally
`(("explain", …), ("context", …))` — `impact` is absent, so the green suite pins nothing.

This is the audit's own blocking finding #1 on a third surface — and `impact` is the command golden
questions (b) and (c) route through, and the traversal P4's `compute_membership` is built on. §4.2
made the coarse fingerprint mandatory *because* "correctness rests on hydration, not on the
fingerprint". On this surface that hydration does not exist. Survived every refutation angle.

### B2 · The one CI-enforced budget cannot run on the platform it is written for

`.github/workflows/harness-ci.yml` runs `knowledge_benchmark.py --assert-floor-us 2.67` on the
`windows-latest` leg. `knowledge_benchmark.py:25` is an unconditional `import resource` — Unix-only
stdlib. The command dies with `ModuleNotFoundError` before measuring anything. Reproduced by
blocking the import.

So the freshness floor the plan budgets **at p95 ≤ 40 ms on `windows-latest`** is enforced nowhere.
Two aggravations: the benchmark times `corpus_fingerprint` in a *warm* in-process loop after nine
other operations, while the budgeted quantity is the cold per-CLI floor (cold decomposition: 2.97
µs/entry → **46.2 ms projected at 15 k**, over budget, matching the P2 commit's own admitted 49 ms);
and the per-entry restatement did not close the "run it smaller" escape it was introduced for — CI's
600 entries gives 2.0 µs/entry PASS, 3 000 entries gives 4.43 µs/entry OVER BUDGET.

### B3 · `peakRssMb` is instrumented but budgeted nowhere

The P2 gate says *"`peakRssMb` **budgeted**, not merely measured"*. It is measured (46.2 MB at 600,
127.0 MB at 3 000) and asserted by nothing, for any command. The instrument is
`resource.getrusage` — the same Windows-unavailable module as B2 — and it measures the whole
benchmark process, including fixture writing, not the query. **0 of 5 traversals have a memory
budget.**

### B4 · `feature-drift` is permanently inert — nothing ever writes a membership baseline

`feature-baseline-<slug>.json` appears exactly once in the repository: as a *read* at
`knowledge_search.py:2033`. `tree` writes nothing — verified by running it and diffing the cache
directory. The ledger record contains no `membershipDigest` either, so §6's ruling ("the ledger pins
a `membershipDigest` only; the identity list lives in `.cache/`") is implemented as **neither half**.

`changed` can therefore only ever be `"unknown"`, the added/removed diff branch is unreachable, and
the gap text shipped to users says *"Run `tree` on the approving machine to write a baseline"* —
naming a command that does not do that. Hand-planting a baseline makes the compare branch work, so
the code is live but unreachable. The inversion §6 exists to prevent is avoided only by the command
doing nothing.

Compounding: `changedWithinTruncatedPrefix` does not exist anywhere, and `feature-drift` discards
`compute_membership`'s `limitsHit` — so a feature truncated at `maxNodes=2000` would be compared
digest-to-digest and reported `changed: true/false` with no disclosure. Worse than the `changed:
null` the correction was written to replace; masked today only by B4 itself.

### B5 · `feature-check` is not in CI, and the live tree fails it right now

```
$ python scripts/knowledge_store.py feature-check
{"outcome":"ERROR","reason":"feature-check failed:\n- .ai/knowledge/features/scheduling.md:
 unfilled <AGENT_...> sentinel present (contract §13)"}   exit 1
$ python scripts/validate_harness.py
PASS: harness validation (2615 checks)
```

§6 ruled that `feature-check` "joins `NOT_ON_PUBLIC_SURFACE` with its CI assertion in the same
commit". It went on the public surface instead — `NOT_ON_PUBLIC_SURFACE` at
`tests/test_knowledge_store.py:911` still holds only `entry-check` — so no CI step runs it. The
ruling's entire point was that a CI-only gate must be asserted to actually run in CI.

The failing record is `.ai/knowledge/features/scheduling.md`, **committed**: a fixture-derived draft
anchored on the *test* object `HarnessAlphaCase__c`, with an unfilled `<AGENT_FEATURE_DESCRIPTION>`
sentinel and no `features-ledger.jsonl` beside it. A manual-run leftover, sitting in the one
directory P4 spent 458 lines making governed. The two defects mask each other.

### B6 · Contract §13 does not exist

D7 fixed the Feature Entry contract section at §13. The citations shipped — `copilot_role_guard.py:258`,
`copilot_safety_hook.py:810`, `knowledge_store.py:1385` and `:1470`, `curate-knowledge.prompt.md:50`
— but `docs/knowledge-one-file-contract.md` ends at §11 (+§10a). Neither P4 commit touched the
contract. Every refusal and error message P4 ships points a reader at a section that does not exist,
which is the opposite of the legibility D7 was decided for. The feature-entry schema cites no
section at all. D5's `^(?!Feature:)` lookahead is likewise in none of the three envelope schemas —
two-segment identities are blocked only incidentally, by the three-segment `entryId` pattern.

## Major

**Cross-phase seams — the two defects no dimension owned**

- **Assurance is not enforced at the citation boundary.** `work_record.validate_entry_refs` accepts
  an `entryRef` for an entry whose `assurance.typeFacts` is `source-derived-heuristic` — accepted,
  no warning, no gap. `scripts/work_record.py` contains **zero** occurrences of the string
  `assurance`, while contract §8.1 restricts grounding to sections marked `source-exact` with full
  coverage, and §0.1's own stated consequence is *"after P0, ApexClass and ApexTrigger entries
  become ungroundable"*. P0 verified the marker is honest inside the store; P6 verified the ref
  *shape*; nobody checked assurance where it has consequences. The drift half of the same boundary
  does hold — editing a source fragment moves the lane and the citation is refused.
- **The `search-knowledge` command menu never got the R2 placeholder block.** It lists `context` but
  not `tree`, `feature-drift` or `feature-dossier`. P2 owned the block (never created it), P6 owns
  the prose (cannot append into a block that does not exist). An orphaned defect produced by the
  ownership split itself.

**P2**

- `--direction` was never threaded into `context` or `tree`; `compute_membership` hardcodes
  `direction="incoming"`. §10 assigns forward traversal to P2 explicitly.
- The `break` §4 names is still at `knowledge_search.py:1266-1267`: `search --relation-anchor …
  --direction incoming` still collapses two edges to one row, so golden question (d) answers
  differently depending on which command you ask.
- §4.3's "bytes, not just documents" test does not exist. `postingBytesRead` is emitted and pinned
  by nothing, so the exact regression §4.3 describes would ship green.
- The PermissionSet truncation family filter is **dead code**: the collector writes relation kinds
  into `truncatedFamilies`, the query-side map is keyed on XML family names. The test passes only
  because the fake store feeds a family name the collector never emits. Effect: the mandatory
  truncation gap becomes constant noise on unrelated queries.
- The benchmark's composition anchor times an empty answer. `parts_identity = first_of("CustomObject:")`
  is deterministically `BenchObject000__c`, and `index % 50 == 0` implies `index % 5 == 0` implies
  `is_apex` — so partition 0 holds only ApexClass. `explainWithParts` and `contextPack`, the two
  measurements added *specifically* so composition would not be timed against an empty answer, both
  measure `parts: []` at every size the project runs. (The corpus itself is genuinely mixed now:
  600 entries → 110 ApexClass / 147 CustomField / 50 CustomObject / 293 Flow, 40 of 50 objects with
  non-empty parts. The defect is anchor selection.) The only automated run is the smoke test at
  `entries=25`, whose corpus is `{"CustomObject": 25}` because `PARTITIONS=50 > 25`.

**P3**

- **Lane discipline is not identical to `search`.** `run_context` never calls the module's own
  `lane_split()`; a revoked row sits in the same `parts` array as approved rows with only a per-row
  `lifecycle` label. `search`, `explain` and `impact` all bucket. `context` is the documented step-1
  lookup for eight consumer surfaces, and `parts` is the composition primitive P4's membership is
  built on.
- No stated `peakRssMb` ceiling for `context` and no CI assertion of its p95. Commit `9253352`'s
  extrapolation ("~40 ms at 15 k") predates the corpus fix; today's mixed corpus gives 178.8 ms at
  6 000 on the same OS.
- `chains` — one of §5's six named sections — is absent; an execution chain still needs a separate
  `impact` call. `outgoing` is neither capped by `--top` nor filtered by `--include-heuristic`,
  while the gap line counts incoming only.

**P4**

- No absolute p95 or `peakRssMb` budget for `tree` or `feature-drift`; the benchmark does not touch
  either command. This is not a platform limitation — the instrument does not exist.
- `assert_no_reparse_points()` takes no argument and still rglobs all of `.ai/knowledge` from every
  feature command; it was never scoped to `FEATURES_ROOT`.
- Golden (e)'s below-floor count is wrong: `below_floor` is appended once per anchor walk and never
  de-duplicated before `len()`, so the answer claims "9 artifact(s)" while naming 5. The list is
  also silently capped at `[:50]`. The number a reviewer reads and the names they can act on
  disagree — in the one answer whose entire purpose is telling the truth about what is inferred.
- Nothing pins lane-filtered membership, `changed: "unknown"`, or truncation. All three behaviours
  work today and I verified them by execution; nothing stops a later edit reverting any of them.

**P5 / P6**

- `relation-health`'s orphan half is definitively absent: `entry_edge_health(live_component_ids)`
  never references its own parameter (proved by AST), and after deleting an entire referenced
  CustomObject from live source it still reported `findingCount: 0`. §8's cell is "lane-computed,
  **orphans reported**"; only the first clause is delivered.
- **Neither P6 count is asserted.** §7 says "Both counts are asserted. Neither is allowed to move
  silently." The earlier hand-assembled gate was removed after the phase audit and nothing replaced
  it. Set A is 8 of 8 and Set B is intact *today* — verified by hand, which is precisely the mode of
  verification the standing rule was written to end.
- The "obtain the citable ref with `entry-status --identity`" sentence is missing from 7 of 8 Set A
  surfaces, `search-knowledge`, and the dossier. The machinery is fail-closed independently
  (`ENTRY_REF_FIELDS` rejects a ref built from the `citation` block), so this is a prose gate only.

**P0**

- §0.5's standing test validates 3 hand-written samples, not "every type in
  `knowledge_store.PROFILES`" (10 types). Flow is never validated against its profile schema by any
  test or corpus. The plan chose this test specifically as *"the standing test that would have
  caught all six"*; as written it would not catch a seventh. One line fixes it:
  `assert set(SAMPLES) == set(store.PROFILES)`.

**§8 row 12 — the incremental check does not incrementally check**

Accepted on semantics by every dimension; fails on measurement. At 9 000 entries `entry-check
--changed-since HEAD` skips **9 000 of 9 000** fragment checks and takes **29.05 s vs 29.33 s**
full — 1 % saved, within noise. cProfile: the cost is `split_entry` YAML parsing (0.761 s of
1.446 s) and `validate_entry` (0.612 s); `regenerate_fragment_digest` — which the docstring blames
and which `--changed-since` skips — is absent from the top 14 frames. The row's remedy for a
>8 700-entry corpus reduces to the raised timeout alone.

## Corrections to the record

Findings from earlier documents and from this audit's own first pass that did **not** survive:

- **§8 row 3 "20 of 20 CustomObjects return non-empty `parts`" is MET** — on the default lane, no
  flags, reproducible in ~40 s from `~/Desktop/salesforce_test_data`. It was first scored
  UNVERIFIABLE only because that dimension did not know a sibling had already located the corpus.
- **The grounding timeout has 2.3× headroom, not 4 %.** Measured at the plan's own target: 15 000
  entries → 52.2/52.6/53.7 s against `GROUNDING_TIMEOUT_SECONDS = 120`, i.e. 3.48–3.58 ms/entry,
  matching the plan's stated 3.45 ms/entry within 4 %. The alarming figure came from extrapolating
  linearly off 189 entries, where fixed costs dominate.
- **Golden (a) is MET.** `entry-coverage`'s `missingEntries` values are object-qualified, so
  filtering on the `Assignment__c.` prefix yields the per-object denominator exactly (5 served + 1
  missing = 6 declared). The standing gap is a followable instruction, and the command is read-
  permitted for every consuming role. A `context` call that changed when an entry-less field
  appeared would mean the index had started asserting source composition — the opposite of "index
  never authority".
- **Golden (c) is MET on the plan's wording.** §4.1's stated remedy is the direction flag and
  nothing more; each served row is an ordered caller→callee `path`, hop-numbered, with per-hop
  `assurance` and path `minAssurance`, and the mandatory R6 gap fires without the flag. The async
  leg (`AssignmentChanged__e` has no outgoing edges) is R1 working as intended — an event may not
  assert its subscribers — and the continuation is one source-exact `context` call away, which is
  exactly the human-override case the Feature Entry's `include:` list exists for.
- **Cap-before-hydrate (P3 correction 1) shipped correctly** — cap at `:1809-1811`, hydrate at
  `:1814-1824`.
- **`relations-worklist` is MET**: 0 missing / 665 homed-in-entry, exactly the post-P2 figure the
  P1 note records.
- **`APEX_NEW_RE` does invalidate the index** — `code_fingerprint()` covers `relation_kinds`.
- **P4's "3 test failures" does not reproduce.** At HEAD: `pytest` → 1 failed / 693 passed / 1
  skipped; `unittest discover` (what CI runs) → 695 tests, 1 failure, 1 skipped. The single failure
  is `test_salesforce_review.py` — local `node_modules/@salesforce/mcp` JSON corruption, unrelated
  to Knowledge. `validate_harness.py` → PASS (2615 checks).

Two numbers in the plan text no longer reproduce and should be restated rather than defended:

- **595 / 414 → 662 / 481.** Same 189-component corpus, three independent measurement paths. The
  `object-token` / `var-field-ref` / `soql-field` breakdown matches verbatim (253/78/25); the delta
  is entirely `invokes-class` 58 → 125, from `APEX_NEW_RE`. The gate value (**0 laundered**) is met.
- **R6's "58 of 59 forward-chain edges are `invokes-class`" → 625 of 1330 (47 %).** Walking depth-2
  forward from every ApexClass/ApexTrigger anchor in the same corpus. R6's *conclusion* survives —
  the default filter still collapses the chain from 27 nodes to 2, so `--include-heuristic` really
  is required — but the cited measurement is stale or from a different denominator.

## What was never exercised by anyone

- **Golden (d)'s headline condition.** Neither the 189-component corpus nor the pilot contains a
  PermissionSet approaching the 300-ref cap, and no CustomField in the probe has ≥2 incoming grant
  edges — so neither multiplicity-on-grants nor the mandatory truncation gap has ever run on real
  data. Needs a fixture PermissionSet with >300 `fieldPermissions`.
- **`no agent self-approval`, at code level.** `knowledge-curator` and `config-investigator` are
  permitted `entry-approve` / `entry-revoke` / `feature-approve` by the role guard; the only control
  is the safety hook's `ask`. That is arguably the designed model (contract §6.1: the click *is* the
  mechanism) — but the hook fires for 2 of the 8 mutation commands, and no test asserts coverage of
  the rest.
- **Every "validator PASS" in this audit was collected over zero entries.** `.ai/knowledge/artifacts`
  is empty, so the validator's grounding checks run on an empty corpus.
- **`windows-latest` anything.** Per B2, that leg currently crashes before measuring.

## Also open, minor

`explain` still has no `--top` (70 unbounded incoming rows against an `EXPLAIN_TOP_DEFAULT` of 50,
with no R5 gap) · the dossier's no-description fallback still tells a reader to author an entry that
already exists, when the actionable step is `entry-describe` · `COLLECTOR_VERSION` is still `"1.6.0"`
after five new `belongs-to` emitters and `APEX_NEW_RE`, so no approved entry can be dated pre- or
post-P1 · no time limit among the traversal limits, and 2000/500 appear to be chosen constants
rather than "set from the P2 benchmark" · `DEPTH_LIMITS["context"]` and `["drift"]` are read by no
code path yet published by `capabilities` as enforced · the coarse fingerprint's
`max(mtime_ns, st_size)` folds size into the same max, so the size term is dead.

## Is the harness ready for the first entry approval?

> **As audited, and left unedited.** Two of the three residuals below have since closed —
> assurance **is** now enforced at the citation boundary (`work_record._assert_entry_is_groundable`,
> contract §8.1a) and `COLLECTOR_VERSION` **is** bumped to `1.7.0`. The third, on detecting an
> assurance regression after approval, is unchanged. Read § Disposition for status; this section is
> the record of what the risk looked like before the remediation waves.

**Yes mechanically, no safely.** Nothing blocks it: `entry-draft`/`entry-approve` work,
`entry-check` passes, D1's precondition (P0 + P1 landed) is satisfied, and the critic approved 189
entries and validated a bound `entryRef` end to end. But three residuals convert from free to
permanent at the first approval:

1. **Assurance is unenforced at the citation boundary** (seam finding above) — the first work record
   citing an ApexClass entry will bind knowledge §0.1 declares ungroundable, silently.
2. **Nothing detects an assurance regression after approval.** Executed: an approved entry survives
   a heuristic → source-exact flip with lane `approved-current`, unchanged `factsDigest`, and
   `entry-check` PASS. The plan states this at §9.1(4); it is currently harmless only because the
   corpus is empty.
3. **`COLLECTOR_VERSION` is not bumped**, so every entry approved from now on carries a provenance
   stamp that cannot date a `factsDigest` move.

## Suggested order

1. B1 (`impact` anchor verification) — smallest fix, largest safety delta, and it is a strict
   regression against a gate the audit already closed twice on sibling surfaces.
2. B5 + B6 together — delete or complete the leftover `scheduling.md`, wire `feature-check` into CI,
   write contract §13. These three are one commit and they currently mask each other.
3. The seam finding — teach `validate_entry_refs` to read `assurance.typeFacts` /
   `extractionCoverage`, or record an owner decision that §8.1 is advisory.
4. B2 + B3 — make `resource` optional, measure the cold first call in a fresh process, assert a
   `peakRssMb` ceiling. Until then no budget in the plan is enforced on the team's platform.
5. B4 — decide whether `feature-drift` ships with a baseline writer or is withdrawn until it has
   one. Shipping a command that can only answer `"unknown"` is worse than not shipping it.
6. The un-asserted gates (P6's two counts, P4's three behaviours, `postingBytesRead`, §0.5's
   `PROFILES` set). Every one of them is green today and free to move silently tomorrow — which is
   the failure mode this project has now hit three audits running.

## Standing rule, discharged

This document is the by-execution re-verification of P4's gate that
`docs/knowledge-phase-audit-2026-07-25.md` requires and that no document previously recorded. That
document's status line should be corrected: it says P4 is blocked; P4 merged in `7db8b51` and
`0edc9c1`.

**Discharged 2026-07-25 (wave 2).** The status line is corrected in place, with the old text struck
through and the successor records named. P4's gate now also has a dedicated by-execution record of
its own, `docs/knowledge-p4-completion-note.md`, in the shape `docs/knowledge-p1-completion-note.md`
established — because "a gate re-verified inside an audit of everything" is not the same artifact as
"a phase's completion note", and the standing rule asks for the latter.

## Disposition (2026-07-25, after remediation waves 1, 2 and 3; re-measured 2026-07-26, wave 4)

**How to read this, and what it is not.** Each row says what closed the finding and the evidence I
could confirm **by reading this working tree and running commands against it**. I did not have the
remediating agents' reports. Where a claim rests on a measurement someone else took and I did not
repeat, the row says so — an unverified number in a disposition table would reproduce the exact
failure this audit exists to document.

**Rows marked `[RE-READ 2026-07-25, wave 3]` were rewritten because the wave-2 text did not
reproduce.** Two did, and they are exactly the two that were written from what the remediation was
*meant* to do rather than from the tree. Wave 3 re-ran each: the commands and their measured output
are in the rows themselves.

**Method M1 — where every performance figure in this document and in
`docs/knowledge-p4-completion-note.md` comes from.** Cited by name from the rows rather than
restated, because the plan's standing rule is that a figure without its method is a quotation.

```
python scripts/knowledge_benchmark.py --entries 3000 --repeats 5 \
    --assert-floor-us 5.0 --assert-command-budgets      # exit 0, 2026-07-26, 43 s
```

That is the **exact** command the `harness-ci.yml` matrix runs. Corpus: the synthetic mixed
fixture the benchmark builds itself — 3 000 entries, `{Flow 1573, CustomField 787, ApexClass 590,
CustomObject 50}`, 4.0 MB of entry files, 15.4 MB of index. Platform: `macOS-27.0-arm64`,
Apple silicon, **CPython 3.9.6** (the repository `.venv`). Every latency row is **21 fresh
processes** timing their cold first call — a per-CLI-process quantity, which is what the plan
budgets — and every `peakRssMb` is that one process, never the benchmark process. Payload keys
are named wherever a row quotes a number: `commandBudgets.traversals.<name>.{minMs, p95Ms,
peakRssMb, postingBytesRead}`, `floorBudget.{perEntryMicroseconds, projectedMsAt15k}`,
`traversalLimits.limits.<name>`, `traversalObserved.regimes.<name>`.

**M1 is macOS.** Nothing in this document was measured on `windows-latest`, which is where the
plan states every budget and where the team actually works. That is a standing open item, not a
caveat on individual rows — see § Still open.

### Blocking

| # | Status | What closed it, and the evidence |
|---|---|---|
| B1 | **closed** | `run_impact` now returns `anchorIdentity` and `anchorLifecycle`, calls `verify_anchor`, and marks every served row `hydrated`. Executed on the 189-entry corpus: a **revoked** anchor returns `anchorLifecycle: revoked` plus `ANCHOR: … is in lane 'revoked', outside the requested approved-current … do not cite them as effective`; an identity no entry projects returns `anchorIdentity: null` plus an `ANCHOR:` gap distinguishing *absence of an ENTRY* from absence of the artifact. Recorded in contract §14.2. |
| B2 | **closed** | `[RE-MEASURED 2026-07-26, wave 4 — the numbers this row carried were taken before the gate was retuned.]` `import resource` is wrapped in `try/ModuleNotFoundError` with a `win32` branch using `kernel32.K32GetProcessMemoryInfo`, so the `windows-latest` leg reaches the measurement instead of dying at import. The floor is measured **cold, one fresh process per sample**, and the assertion is the *noise floor* rather than a p95 — a stated deviation, argued at length in the workflow step. CI asserts **`--assert-floor-us 5.0`**, not the 2.67 this row previously quoted: 2.67 is §4.2's 40 ms at 15 k and it failed 2 of 3 runs on a developer machine before ever reaching the slower runner. Method (M1 below): `perEntryMicroseconds` **2.33** → `projectedMsAt15k` **35.1**, p95 2.49 → 37.5 — inside both §4.2's 40 ms and the 5.0 µs gate, on macOS. **The Windows leg has still never run**, and that is where the budgeted number lives. |
| B3 | **closed** | `[RE-READ 2026-07-25, wave 3; FLOOR_BUDGET corrected and every figure re-measured 2026-07-26, wave 4.]` The shipped table is not flat: `COMMAND_BUDGETS` is `explain` 60/200 ms, `impact` 70/200 ms, `context` **300/500 ms**, `tree` and `drift` 60/250 ms (noise floor / p95), each with a 96 MB `peakRssMb` ceiling and `explain`/`impact`/`context` a 1 000 000-byte `postingBytesRead` ceiling. Nor is the set "5 of 5" of those rows: `PLAN_TRAVERSALS` is **floor / impact / context / tree / drift** — the plan's five, which include §4.2's freshness floor — and the floor is not a command, so its memory half is `FLOOR_BUDGET = `**`80 MB`** (wave 3 wrote 64; the code has said 80 since the row was written — see § Corrections to this audit's own text) with its latency half asserted by `--assert-floor-us`. `explain` is a sixth budgeted row beyond what the plan requires. Method M1: **all six PASS** — floor 27.3 MB, impact 19.8/21.0 ms · 31.8 MB, context 92.2/97.7 ms · 32.8 MB, tree 15.5/16.3 ms · 32.8 MB, drift 15.2/15.9 ms · 32.8 MB, explain 14.2/15.4 ms · 32.7 MB (`minMs`/`p95Ms` from `commandBudgets.traversals`) — each scoped to one fresh command process, not the benchmark process (whose own peak is 134.8 MB and is reported as an explicit upper bound). |
| B4 | **closed** | `tree` writes `.cache/knowledge-search/feature-baseline-<slug>.json` and reports `baseline: {written, path}` — and **declines** to write, with the reason in the payload, when the membership does not reproduce the approved digest or the traversal truncated. `feature-drift` answers `changed` from the ledger's `membershipDigest`, so it works with the cache deleted (executed: `changed: false`, `added: null` = *detail unavailable*, never *nothing added*). `changedWithinTruncatedPrefix` exists and fires: with `maxNodes` forced to 3, drift returns `changed: "unknown"`, `changedWithinTruncatedPrefix: true`, `truncated: true`, `limitsHit: ["nodes"]`. Full run in the P4 completion note. |
| B5 | **closed** | `.ai/knowledge/features/scheduling.md` is deleted (`git status` shows `D`). `feature-check` is declared in `NOT_ON_PUBLIC_SURFACE` in `tests/test_knowledge_store.py` **beside** `test_ci_only_commands_are_declared_and_actually_run_by_ci`, which is the half whose absence let the two defects mask each other. Executed: `feature-check` refuses an unfilled `<AGENT_FEATURE_DESCRIPTION>` sentinel citing §13, and returns `PASS` once removed. |
| B6 | **closed** | Contract §13 exists (§13.1–13.8), and §12 stays RESERVED per D7. D5's `^(?!Feature:)` lookahead is present in all three envelope schemas — `output-envelope`, `change-record`, `handoff-envelope` — each with a description saying it *backstops* the three-segment pattern rather than being the only block. |

### Major

| Finding | Status | What closed it, and the evidence |
|---|---|---|
| Seam · assurance unenforced at the citation boundary | **closed** | `work_record.py` gained `GROUNDING_ASSURANCE` / `GROUNDING_COVERAGE` and `_assert_entry_is_groundable`, called from `validate_entry_refs`. It reads the **approved frontmatter**, not the caller's ref, and requires *every* populated section to be `source-exact` + `full`. Blast radius measured on the reference corpus (189 components from `~/Desktop/salesforce_test_data`, drafted → approved → indexed in a temp root; wave 2, **not re-run in wave 4**): **58 of 189** entries ungroundable — 48/52 ApexClass, 5/5 ApexTrigger, 2/2 ValidationRule, 3/93 CustomField. Recorded in contract §8.1a, including the two facts §0.1 did not predict: ValidationRule loses grounding entirely, and CustomField is per-entry rather than per-type. |
| Seam · `search-knowledge` menu missing the R2 block | **closed** | The skill is modified in this tree and now names `tree`, `feature-drift` and `feature-dossier` alongside `context`. Verified by reading the file; I did not re-derive the ownership split. |
| P2 · `--direction` never threaded into `context`/`tree` | **closed** | Both parsers carry `--direction`; `context` returns `chainsMeta.direction` and `tree` returns `direction`. `tree`'s help states that `outgoing` is exploratory and writes no baseline, because the approved digest is defined on the incoming traversal — a distinction the finding did not ask for and that is correct. |
| P2 · the `break` collapsing multiplicity | **closed** | The `break` is gone; the loop now emits one row per edge in both directions, with the reason in a comment naming golden question (d). |
| P2 · §4.3's "bytes, not just documents" test | **closed** | `tests/test_knowledge_search.py` asserts on `counts["postingBytesRead"]` against the corpus posting total, not only `documentReads`. |
| P2 · PermissionSet truncation family filter is dead code | **closed** | `truncation_gaps` is keyed on **relation kinds**, which is what the collector actually writes into `typeFacts.truncatedFamilies`, and the comment above it records the mismatch it replaced. (Line numbers are deliberately not quoted here: three of the ones this table originally carried had already drifted by wave 4.) |
| P2 · benchmark composition anchor times an empty answer | **closed** | The anchor is chosen by `first_with_parts("CustomObject:")` with `first_of` only as a fallback, so `explainWithParts` and `contextPack` measure a non-empty composition. |
| P3 · `context` labels lanes but does not bucket | **closed** | `context` returns `parts`/`partsNonCurrent`, `permissions`/`permissionsNonCurrent`, `incoming`/`incomingNonCurrent`, `chains`/`chainsNonCurrent` — and `incoming`/`outgoing` are now **dicts keyed by relation kind**. Executed against the corpus; shape recorded in contract §14.1. |
| P3 · no `peakRssMb`/p95 for `context` | **closed** | `COMMAND_BUDGETS["context"]` is `{minMs 300, p95Ms 500, peakRssMb 96, postingBytesRead 1 000 000}` — wave 3 wrote "300 ms / 96 MB / 1.4 MB postings", which lost the p95 and overstated the byte ceiling by 40 %. Method M1: 92.2 ms noise floor, 97.7 ms p95, 32.8 MB, 785 484 posting bytes — PASS. Not measured at 15 k, not measured on Windows. |
| P3 · `chains` section absent | **closed** | `context` returns `chains`, `chainsNonCurrent` and `chainsMeta{direction, depth, limitsHit, excluded, note}`; the note explains `minAssurance`. Requires `--include-heuristic` per R6, with a mandatory gap when hops are dropped (executed: *"1 heuristic hop(s) were dropped from `chains`"*). |
| P4 · no budget for `tree`/`feature-drift` | **closed** | Both are in `COMMAND_BUDGETS` at **60 ms noise floor / 250 ms p95 / 96 MB** — not the "300 ms / 96 MB" wave 3 wrote for them. Method M1: `tree` 15.5/16.3 ms · 32.8 MB, `drift` 15.2/15.9 ms · 32.8 MB — PASS. |
| P4 · `assert_no_reparse_points()` unscoped | **closed** | Signature is now `assert_no_reparse_points(root: Path \| None = None)`, defaulting to the whole knowledge tree only when no root is passed; the docstring names the scale defect it fixes. |
| P4 · golden (e)'s below-floor count disagrees with its names | **closed** | Executed: `belowFloor` returns `count: 6`, six identities, `identitiesTruncated: 0`. The count and the names agree, and the truncation of the list is itself disclosed rather than silent. |
| P4 · nothing pins lane-filtered membership / `"unknown"` / truncation | **closed** | `tests/test_knowledge_search.py` carries cases for each, including one that forces `DEPTH_LIMITS["drift"]` and `TRAVERSAL_LIMITS` to exercise truncation. I confirmed the tests exist and the behaviours reproduce; I did not audit the tests for adequacy. |
| P5 · `relation-health` orphan half absent | **closed** | `entry_edge_health(live_component_ids)` now uses its parameter — `live_names` is derived from it and diffed against entry edges — and computes lanes through `compute_lane` rather than reading frontmatter, which is contract §4's requirement. **I did not re-run the delete-an-object experiment**, so the closure is verified by code, not by the finding's own reproduction. |
| P6 · neither consumer count is asserted | **closed** | `validate_harness.py` now **parses §7 of the plan** for the Set A and Set B bullets (`plan_consumer_set`) and asserts each named surface carries `SET_A_CALL` / `SET_B_CALL`. This is the specific remedy the phase audit's lesson called for: the gate counts the plan's named set, not a list assembled beside it. `[EXTENDED 2026-07-26, wave 4.]` §7 names **two** tokens per Set A surface and the gate now asserts both: `SET_A_CALL` and `SET_A_HYDRATION_RULE = "hydrated"`, one `audit.require` each, so 8 surfaces × 2 = 16 assertions. `grep -rl hydrated .github/` returns exactly the 9 files §7 says the whole check is — the 8 Set A surfaces plus `search-knowledge`. `validate_harness.py` PASSes at **2 647 checks**, measured 2026-07-26 (wave 3 recorded 2 634; 8 of the 13 added checks are one new `require` per Set A surface — I did not attribute the other 5 individually). |
| P6 · "obtain the citable ref with `entry-status --identity`" missing | **closed** | The sentence is present in all eight Set A surfaces plus `search-knowledge`. Verified by grep across `.github/skills`, `.github/agents`, `.github/prompts`. |
| P0 · §0.5's test validates 3 samples, not `PROFILES` | **closed** | `tests/test_knowledge_store.py:869` asserts `set(store.PROFILES) == set(self.SAMPLES)` and then validates each sample against its profile schema — the plan's named set, not a hand list. |
| §8 row 12 · `--changed-since` does not incrementally check | **closed** | `compute_lane` lost its partial mode entirely (the docstring records that it bought ~2 % and returned a lane that was *asserted rather than proven*), and `--changed-since` now skips **whole entries**. The remediation reports 40.4 s → 0.43 s at 9 000 entries; **I did not reproduce that measurement.** |

### The minor items, and the two findings this audit left unresolved

`[RENAMED 2026-07-26, wave 4 — this table was called "Still open" while nine of its ten rows read
"closed", which is how a reader ends up counting open items by eye. Everything genuinely open now
lives in the table after it, and only there.]`

| Finding | Status | Note |
|---|---|---|
| `COLLECTOR_VERSION` not bumped | **closed** | `1.6.0` → `1.7.0` in `force_app_knowledge.py`, which is the "still open, minor" item that had the largest permanent cost: it is the stamp that dates a `factsDigest` move, and it had to move before the first approval. |
| `explain` has no `--top` | **closed** | `explain.add_argument("--top", default=EXPLAIN_TOP_DEFAULT)`; `explain`'s `incoming` deliberately stays a flat array, unlike `context`'s dict. |
| Golden (d)'s headline condition never exercised | **closed** | `[RE-READ 2026-07-25, wave 3 — this row said OPEN in the wave that shipped the fixture.]` The fixture exists: `tests/test_knowledge_search.py::GrantTruncationEndToEndTests` writes a `HarnessGrantsHeavy` PermissionSet carrying **317 `fieldPermissions`** over the `MAX_USAGE_REFS = 300` cap, composed so the anchor field keeps *both* an edit and a read grant while the read family is still the tail that is cut. Run here: **5 of 5 pass in 4.9 s**, walking the whole chain on real collector output — the collector caps at 300 and names `truncatedFamilies: ["grants-field-read"]`; the index rolls it up into the reverse posting's `truncatedSources`; the mandatory gap fires on `search --relation-anchor` (with and without `--relation-kind`), on `explain` and on `context`; it stays silent both on an unrelated `belongs-to` query **and** on an object grant served by the very same capped PermissionSet; and the doubly-granted field returns **two rows, not one**. Both halves the finding named — the cap firing where it should, and multiplicity on grants — are now exercised. Re-run 2026-07-26: **5 of 5 in 4.96 s**. Closed **on a purpose-built fixture**, not on real package data; the residual is its own row below. |
| No agent self-approval, at code level | **closed as a ruling, 2026-07-26 (wave 4)** | The finding asked for the argument to be settled rather than left as a gap, and it is: **contract §6.5** now states the ruling normatively — the guard rows are the design, the hook's `ask` is the enforcement point, and the invariant means *no approval record without a human click*, which a guard row cannot violate. The coverage half is pinned by `tests/test_safety_hooks.py::test_every_approval_command_is_chat_confirmed_and_authoring_is_not`, which partitions the guard's own `KNOWLEDGE_STORE_MUTATION_COMMANDS` by verb: **4 approve/revoke commands assert `ask`, 4 authoring commands assert not-`ask`** — the plan's named set read from the code, so a ninth mutation command cannot land uncovered. `feature-approve` and `feature-revoke` were pinned by nothing before this. **No code changed**: the role guard is deliberately unchanged, and a future reader who "hardens" it by deleting those four rows breaks the documented workflow. |
| Every "validator PASS" collected over zero entries | **still open** | Unchanged and unclosable before the first approval; carried into § Still open below so it is stated once, with what would close it. `.ai/knowledge/artifacts` is empty in the repository and must stay so; the 189-entry runs in this disposition and in the P4 note were made in temp roots, which is the substitute — not the same thing as a governed corpus. |
| Dossier's no-description fallback | **closed 2026-07-26 (wave 4)** | Both states now name P5's remedies verbatim, gated on `store.PROFILES` the way P5 gates on `entry_draftable_types`: absent → *"run `entry-draft` then `entry-describe`"* for a type with an entry home, *"this type has no entry home; describe it in a claim"* otherwise; present-but-empty → *"the &lt;lane&gt; Knowledge Entry has no Purpose — run `entry-describe`"*. A third disagreement surfaced while proving the first two and was fixed with them: this dossier printed the raw `<AGENT_…>` sentinel into the Description column and **counted it as described**, while P5 treats it as an absence. |
| No time limit among traversal limits; 2000/500 look chosen, not measured | **closed 2026-07-26 (wave 4)** | `TRAVERSAL_LIMITS` is now `{"maxNodes": 5000, "maxFanout": 2000, "maxSeconds": 2.0}` and it is **derived**: `knowledge_benchmark.traversal_observations` walks the shipped `traverse()` over three regimes (hub / chain / leaf), `TRAVERSAL_LIMIT_BASIS` states one uniform rule — no limit below **3×** the worst legitimate walk projected to 15 k — and `assert_traversal_limits` re-checks it on every `--assert-command-budgets` run. Method M1: hub regime maxFanout 59, maxNodes 236, maxWalkMs 14.57 → projected at 15 k 295 / 1 180 / 72.8 ms; shipped values clear the required 885 / 3 540 / 0.219 s at **6.8× / 4.2× / ~29×**, all three PASS. The gate is deliberately one-sided — it fails when a limit drifts *below* the legitimate regime, never when a walk is merely wide. `maxSeconds` sits above every command p95 ceiling on purpose: it terminates pathology, it is not a second latency budget. **Depth stays out of the table** (R7: semantic, never benchmark-derived). |
| `DEPTH_LIMITS["context"]` / `["drift"]` published as enforced but read by no code path | **closed** | `[ADDED 2026-07-26, wave 4 — this "also open, minor" item had no disposition row, so the claim that all six closed was unbacked.]` All four keys are now read where R7 says they belong: `context` at its `traverse` call and again in `chainsMeta.depth`, `drift` at `run_feature_drift`'s membership recompute, `tree` and `impact` at theirs. `run_capabilities` publishes `depthLimits` from the same dict, so what it advertises is what runs. |
| Coarse fingerprint's dead size term | **closed** | The comment on `corpus_fingerprint` records that the size term is now folded separately rather than into the same `max()`, which is what made it dead: `max(newest, st_mtime_ns, st_size)` could only ever be won by a file larger than 1.7e18 bytes. |
| Numbers in the master plan that do not reproduce | **closed (wave 3)** | Wave 2 corrected all three in place with `[CORRECTED …]` and a summary table at the top of the plan: `414 / 595` → **0 laundered of 481 kind-level-heuristic edges in 771 stored**; R6's `58 of 59` → **481 of 589 (82 %) of the depth-2 Apex forward closure is kind-level heuristic**; §7's `≈596` and §8's `≈598` both removed in favour of deferring to `docs/knowledge-p1-completion-note.md`. **Its own replacement for R6's consequence then failed to reproduce**, which is why this row is wave 3 and not wave 2: "`AssignmentTrigger` returns 2 nodes instead of 19" counted rows across the *whole* payload, unhydrated half included, and called them nodes. Re-measured on a fresh 189-entry temp-root corpus, all `approved-current`: `impact --identity ApexTrigger:c:AssignmentTrigger --direction outgoing --depth 2 --include-heuristic` returns **11 rows / 8 distinct citable `nodes`**, and **2 rows / 1 node** without the flag — unchanged at `--depth 3`, `--depth 4` and `--top 200`; across all 57 Apex anchors **52 lose at least one citable node and 47 fall to zero**. R6 now states its corpus, its command and which payload key it counts, and the plan carries that as a standing rule. |

### Still open

**Added 2026-07-26 (wave 4).** Seven items, and they are the whole remainder. Nothing in this
project is open that is not in this table, and nothing in this table is stated anywhere else as a
status. None of them is a known defect.

| Finding | Status | What would close it |
|---|---|---|
| The `windows-latest` leg has never run | **OPEN — off-platform** | Every budget in this document, in the P4 note and in the master plan is macOS (method M1). The plan names `windows-latest` as authoritative and the team is Windows-only. Specifically off-platform: §4.2's *"p95 ≤ 40 ms at 15 k on windows-latest"*, §5's `context` budget, §6's `tree`/`feature-drift` budgets, every `peakRssMb` ceiling, and the Windows peak-RSS **instrument itself** — `kernel32.K32GetProcessMemoryInfo` is exercised only by unit test with a doubled `kernel32` and has never met a real Windows kernel. **Closed by:** one green `windows-latest` leg whose JSON reports `peakRssSource: kernel32…`. A leg that logs `MEMORY UNMEASURED` means the instrument failed and only the latency gate ran. |
| Every gate is measured at 3 000 entries, not 15 k | **OPEN — deviation, stated** | The ceilings are at `BUDGET_ENTRIES = 3000` because a 15 k fixture costs ~25 s to write and ~2 min to index per CI leg, and a gate that slow gets deleted. `context` is budgeted at 500 ms at 3 000 — *looser* than the plan's 400 ms at 15 k — and the traversal limits are projected to 15 k by **arithmetic, not measurement**. **Closed by:** the first green runs at a realistic corpus, which is also what should tighten every number. |
| Golden (d) is exercised by a fixture, not by package data | **OPEN — narrow** | `GrantTruncationEndToEndTests` builds a 317-`fieldPermission` PermissionSet specifically to overflow `MAX_USAGE_REFS = 300`. The behaviour is real and end-to-end, but no PermissionSet in the 189-component reference corpus approaches the cap. **Closed by:** running the same chain against a managed package whose grant bundles are naturally over the cap. |
| The row-lifecycle window is disclosed, not closed | **OPEN by design** | A served row's `lifecycle` is index-fresh; a source edit can make it stale between builds. Now stated on all four retrieval surfaces (`lifecycleBasis` + a mandatory gap) and contained at the citation boundary, which recomputes through `compute_lane` — contract §15. **Closed by:** per-row fragment hashing on the query path, or a `force-app/` term in the freshness fingerprint. Both re-spend the ~174 ms/call at 15 k that §4.2 removed; the trade was taken deliberately and the owner should know it was. |
| `TRAVERSAL_LIMITS["maxSeconds"]` has never fired on a real graph | **OPEN — minor** | No corpus on the development machine produces a walk within ~29× of the 2.0 s terminator, so it is exercised only by unit test (forcing the limit negative). **Closed by:** a real dense package graph, or accepting that a terminator that never fires is the intended outcome. |
| Nothing detects an assurance regression *after* approval | **OPEN — known, and stated in the plan** | An approved entry survives a `source-derived-heuristic` → `source-exact` flip with lane `approved-current`, an unchanged `factsDigest` and `entry-check` PASS. Master plan §9.1(4) states this as a fact about the design, not as an oversight; it is harmless today only because the corpus is empty, and it is one of the three residuals § "Is the harness ready for the first entry approval?" says convert from free to permanent at the first approval. **Closed by:** an owner decision — either fold the assurance markers into a digest the ledger pins, or accept that assurance is re-checked only at the citation boundary (§8.1a), which is where it currently has consequences. |
| Every validator and `entry-check` PASS is collected over **zero entries** | **OPEN by design** | `.ai/knowledge/artifacts` is empty and must stay so until a human approves the first entry, so `PASS (2 647 checks)` and `entry-check PASS` prove the plumbing and say nothing about grounding. The 189-entry runs recorded here and in the P4 note are temp-root substitutes. **Closed by:** the first governed approval, after which the § "Is the harness ready for the first entry approval?" residuals convert from free to permanent. |

### Corrections to this audit's own text

**Wave 4, and the irony is worth recording.** `knowledge_benchmark.FLOOR_BUDGET` has read
`{"peakRssMb": 80.0}` since the day it was written, with its own comment deriving 80 from
26.6–27.2 MB steady state plus the 44.7–48.1 MB compile path. Wave 3's B3 disposition row said
**64 MB**, and `docs/knowledge-p4-completion-note.md`'s R4 table repeated it. Nothing was broken by
it — the gate reads the constant, not the prose — but this is the audit's *own status page*
carrying a number that disagrees with the code it certifies, which is precisely the defect class
this document exists to catch. Three further figures in the same two documents drifted the same
way and are corrected with it: `context`'s posting ceiling (written 1.4 MB, shipped 1 000 000
bytes), `tree`/`drift`'s budgets (written 300 ms, shipped 60 ms noise floor / 250 ms p95), and the
CI floor assertion (written `--assert-floor-us 2.67`, shipped 5.0 with the deviation argued in the
workflow). The remedy is Method M1: every performance figure in both documents now cites one
named method — command, corpus, platform, payload key — instead of a value.

**Wave 3, on the disposition table above.** Two rows written in wave 2 did not survive being read
against the tree in wave 3, and both are replaced in place with a `[RE-READ …]` marker: the
**golden (d)** row said OPEN in the same wave that shipped the fixture closing it, and the **B3**
row misquoted the shipped `COMMAND_BUDGETS` (context is 300/500 ms, not a flat 300) and counted
"5 of 5" over a set that excluded the freshness floor — one of the plan's own five. Both are the
same failure mode as the original findings: a status written from intent rather than from the
tree. The remedy is the header rule above — **the disposition is the only place status lives** —
plus, in the plan, the standing requirement that every figure carry its corpus, command and
payload key.

**Wave 1, on R6's re-measurement.** This audit reported it as "**625 of 1330** forward-chain edges
are `invokes-class` (47 %)".
**That did not reproduce on the same corpus under any of five denominators I tried**
(distinct `(from, kind, to)` triples in the depth-2 closure; edges with per-anchor multiplicity;
`traverse()` reached nodes; last-hop kinds; depth-1 only). The closest shape match — `belongs-to` 5
and `operates-on` 5 exactly — was depth-1 outgoing edges of the Apex anchors, which totals 522, not
1330, and puts `object-token` above `invokes-class` rather than below it.

So the plan now carries a figure with its **method written beside it**, and the rule is restated on
the consequence rather than on the ratio. That is the durable lesson of all three audits in one
line: a number without a reproducible method is a claim, and this audit produced one of its own
while criticising two others.
