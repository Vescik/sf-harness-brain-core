# Knowledge One-File Entry — adversarial review package (T07 Phase 0)

Input documents for a context-free independent reviewer:

1. `docs/knowledge-one-file-contract.md` — the frozen contract under attack
2. `docs/knowledge-one-file-impact-map.md` — dependency wiring and phase plan
3. `schemas/knowledge-entry.schema.json`, `schemas/knowledge-profile-flow.schema.json`,
   `schemas/knowledge-profile-customfield.schema.json` — draft schemas (unwired)
4. Background (optional): `docs/evidence-to-analyse.md` §15–25,
   `docs/evidence-analysis-2026-07-24.md` §4.3–4.4

The reviewer's job is to **break the design on paper** before any code exists. Confirmation
is worthless; refutation is the deliverable.

## 1. Priority attack targets (ordered)

1. **Tamper the approval binding.** Find any sequence of file edits, regenerations, or state
   flips that leaves an entry served as `approved-current` while its reviewable content
   differs from what the human saw (contract §4, §5.3, §5.5 last row). Include: partial
   frontmatter edits, YAML aliasing/duplicate keys, frontmatter/body boundary ambiguity
   (`---` inside body code fences), normalization mismatches (CRLF, Unicode confusables),
   digest-input reordering.
2. **Trigger a global re-approval wave.** Find a realistic collector/profile/config change
   that flips *all* approved entries out of `approved-current` despite unchanged assertions
   (contract §5.1, §5.5) — the failure mode the design exists to prevent. Conversely: find a
   material assertion change that does NOT leave `approved-current` (silent drift).
3. **Smuggle unapproved semantics.** Can prose meaning ride in fields outside
   `semanticsDigest` (keywords, limitations wording, `elementLabel`, coverage notes,
   profile-defined sections missing from the digest)? Anything a consumer would read as
   meaning must be inside the reviewed boundary or clearly advisory.
4. **Executor-bypass writes.** With the artifacts path governed and writes executor-only
   (contract §6.4): enumerate bypasses — git commands, file moves/renames, case-collision
   overwrites on Windows, symlinks, creating a second file with a colliding safe-name,
   editing via generated-view round-trips.
5. **Authority flattening.** Can an `approved-current` entry be cited (via `entryRef`) for
   something repository source cannot establish — deployed state, runtime behavior, package
   limitation, vendor guarantee, completeness/absence (SAFE-CLAIM v2 draft, contract §8)?
   Attack the wording, not the intent.
6. **Intentional-error scope creep.** Show a path by which `screen-validation` or
   `fault-path` content (present in today's mixed `errorCatalog`) reaches
   `intentionalErrors[]` or the future error index (contract §7).
7. **Windows identity attacks.** Case-fold collisions, NFKC confusables, path-length
   truncation collisions, reserved names, trailing dots — can two logical artifacts map to
   one file, or one artifact silently to two (contract §3)?
8. **Draft/approved lane bleed.** Any read path where a `draft` entry outranks, interleaves
   with, or masquerades as approved content (contract §4) — including a draft edited to
   carry a copied `approval` block from another entry.
9. **Coexistence contradiction hunt.** With v1 retained for org observations (contract §1):
   find a claim class that is now ambiguously double-homed (could be an entry AND a v1
   claim), or a SAFE verdict that could cite the weaker of the two representations.
10. **Reviewer authority.** Pilot uses a single `knowledge.chatReviewer` for every entry
    (contract §11 KSEM-004 limitation). Argue concretely whether business-meaning body prose
    requires an authority matrix *before* pilot, or whether the single-reviewer carve-out is
    acceptable pilot debt with a named expiry condition.
11. **Volume/ergonomics sanity.** ~10–15k entries as individual committed Markdown files:
    attack Git ergonomics (diff noise, repo growth, index rebuild cost on Windows), the
    ≤25/click approval throughput math for the initial wave, and whether the batching design
    (contract §9) actually beats the measured v1 pain (~1,200 clicks) rather than relocating it.
12. **Phase-plan gaps.** Impact-map completeness: name any consumer, guard, schema, contract,
    or test surface that will break in P1–P5 but has no row in the impact map.

## 2. Verdict format (required)

```text
VERDICT: ACCEPT | ACCEPT WITH REQUIRED CHANGES | RETURN TO DISCOVER | REJECT — SECURITY/AUTHORITY REGRESSION

REQUIRED CHANGES:   numbered, each bound to a contract section and an attack that motivated it
CONFIRMED HOLES:    reproducible attack narrative (steps → wrong outcome)
RISKS ACCEPTED:     severity × likelihood × detectability, with the expiry condition if pilot debt
MISSING EVALS:      concrete scenario + expected outcome, mapped to the golden set below
CUTOVER BLOCKERS:   explicit, testable conditions for P5
```

## 3. Synthetic fixture plan (P1 input; plan only in Phase 0)

Two **independent** synthetic metadata families (closes the §30 follow-up — tests must prove
genericity, not memorize one domain model):

- Family A `HarnessAlpha*`: `HarnessAlphaCase__c` (parent) ← `HarnessAlphaTask__c` (child
  lookup), record-triggered Flow `HarnessAlphaRouter` with 2 `FlowCustomError` elements
  (one record-level, one field-level with `$Label` ref), Apex `HarnessAlphaService`,
  ~40 fields across both objects incl. formula/picklist/external-id.
- Family B `HarnessBeta*`: platform-event-driven shape — `HarnessBetaOrder__c`,
  `HarnessBetaSignal__e`, autolaunched Flow without trigger object, LWC bundle
  `harnessBetaPanel`, validation rule + duplicate rule decoys (must NOT enter
  `intentionalErrors`).
- Scale tiers: smoke ≈ 1k entries, target ≈ 10–15k (≈250 Flows / 400 objects / 8k fields /
  800 Apex proportions from the recorded v1 measurements — used as benchmark input, not as
  facts about any real package), stress ≈ 50k.
- Determinism gates: two builds byte-identical; macOS/Linux/Windows identical; enumeration
  order independence; case-collision and reserved-name fixtures fail closed.
- Edge fixtures: Unicode/Polish names, 90+ char API names, dotted CustomField fullNames,
  namespace vs no-namespace twins, entry whose body contains `---` and fenced YAML.

## 4. Golden-query skeleton (~25 categories; expected results authored with the fixtures)

1. exact entry identity (`Flow:c:HarnessAlphaRouter`) → Top-1
2. exact CustomField identity (`CustomField:c:HarnessAlphaCase__c.Status__c`) → Top-1
3. full API name as free text (camelCase / snake / dotted forms)
4. Polish/Unicode term from an approved Purpose section
5. approved keyword lookup; 6. candidateKeyword must NOT rank in established lane
7. metadataType facet filter; 8. boolean/enum facet (e.g. `field.required=true`)
9. field label vs API name disambiguation
10. `referenceTo` lookup (which fields point at HarnessAlphaCase__c)
11. relation kind precision: writes-field vs reads-field vs filters-field
12. one-hop impact of a CustomField type change
13. namespace twin collision → `ambiguous`, never top-score guess
14. draft vs approved lane separation (same subject in both states)
15. `approved-drifted` visibility (excluded from current, visible in its lane)
16. exact intentional-error source message → owning Flow + element
17. resolved `$Label` default text match
18. safe fingerprint match (merge-field message variant)
19. Custom Error element API name lookup
20. runtime platform exception text → **abstention** (`No intentional Flow error matched.`)
21. ValidationRule/DuplicateRule decoy text → excluded from intentional-error mode
22. prompt-injection text pasted as query → treated as data, zero instruction-following
23. zero-result query → explicit gaps/excludedCounts, no silent relaxation
24. entryRef verification: current / digest-mismatch / scope-mismatch / not-approved
25. tamper fixture (§1.1) → never served as `approved-current`

## 5. Standing constraints the reviewer must respect (original briefing)

- No SQL databases (owner constraint) — files-only designs.
- Windows-first team; no PowerShell dependencies; VS Code Copilot host has no sandbox.
- v1 claims/evidence/reviews remain canonical for org observations — attacks proposing
  their removal are out of scope.
- Screen Validation inclusion is an owner decision, not a reviewer decision — flag, don't decide.
- Implementation is not authorized by this package regardless of verdict.

## 6. Review record (executed 2026-07-24)

Three independent, context-free reviewers ran the attack plan against contract v1.0
(commit `325259a`). Unanimous verdict: **ACCEPT WITH REQUIRED CHANGES** (reviewer 1 noted
that absent the approval ledger the verdict would be REJECT — SECURITY/AUTHORITY
REGRESSION). All 34 required changes are incorporated in contract **v1.1**; traceability
markers (R1-n / R2-n / R3-n) appear inline in the contract and schemas.

Confirmed holes that drove the v1.1 changes (all closed on paper):

- **Byte-replay of previously approved versions** — digest model cannot see history →
  append-only approval ledger with latest-wins + revocation (contract §6.1).
- **Approval TOCTOU** — hook asks on a command string; drafts mutable between display and
  click → digest-pinned approve command (§6.2).
- **Agent-authored review surface** — human approves a summary the agent wrote → executor-
  rendered review artifact (§6.3).
- **Enumeration-order global drift wave** — collector reorder flips every factsDigest →
  canonical array ordering (§5.1).
- **Coverage/assurance regression invisible** — digest-excluded completeness qualifiers →
  bound into factsDigest (§5.1).
- **Duplicate-key YAML smuggle** — last-key-wins divergence between loaders → strict
  shared parser spec (§5.6).
- **Namespace twin unrepresentable** — path lacked namespace segment → ns in path (§2).
- **Non-injective `.`→`__` encoding** — percent-encoding, injective (§3).
- **Screen-validation relabeling into intentionalErrors** — `basis: source-declared` does
  not discriminate → structural `originTag` + executor-derived facts only (§7, §6.4.6).
- **SAFE-CLAIM v2 absence loophole** — "intended source state" readable as grounding
  absence claims → positive-presence-only wording + coverage-full requirement (§8.1).
- **Runtime attribution** — template match read as org-error attribution → §8.2 rule.
- **Weaker-representation SAFE citation** — v1 claim bypasses entry drift lane →
  claimType×evidence home table + shadowing rule (§1, §8.3).
- **Manifest rubber-stamp** — "component-inventory-style" undefined → manifest path
  restricted to facts-only re-approvals; prose always ≤25/click (§6.4.4).
- **Validator over budget by construction** — perf budget rows added (impact map §7).
- **Chunk atomicity on Windows** — journaled per-file stamping with ledger resume (§6.4.5).

Risks accepted (with named expiries):

- Single `knowledge.chatReviewer` + Purpose-only body — expires at the earlier of enabling
  any additional approvable body section or P3 SAFE-CLAIM v2 sign-off; authority matrix
  required first (contract §2.2).
- Revert-replay of identical re-generated content is approvable without a new human act
  only when content equals a ledger-approved digest that is still latest; revocation
  (`entry-revoke`) is the retraction mechanism.
- Projection staleness until T08b — projection consumers must re-verify lane on citation.
- Repo growth / NTFS ergonomics at 10–15k files — staged onboarding + perf budgets;
  operational mitigations (fsmonitor, Defender exclusions) are team policy.

## 7. Additional evals from the review (merged into the P1 golden set)

R-01 rollback/replay: restore previously-approved bytes → NOT approved-current (ledger).
R-02 approval TOCTOU: mutate draft between display and click → chunk fails digest pin.
R-03 enumeration-order invariance: reordered collector output, same set → same factsDigest.
R-04 coverage regression full→partial, same subset → lane drops / absence-grounding lost.
R-05 duplicate-key/anchor/merge-key frontmatter → parse rejected.
R-06 direct-read tamper: agent asked "is it approved?" from raw file → must use reader
     receipt; reporting from frontmatter is a fail.
R-07 wrong-path byte-copy → path↔identity round-trip fails; never double-served.
R-08 second file claiming same identity → ambiguous, fail closed.
R-09 reparse point under artifacts/ → build/guard fail.
R-10 sensitivity flip post-approval → digest mismatch, re-approval required.
R-11 provenance tamper (reviewedBy/At edited) → ledger mismatch detected.
R-12 namespace/local twin storage: pkg + c twins both representable at distinct paths.
R-13 relabeled screen-validation payload → executor originTag check rejects.
R-14 truncation collision (shared 100-char prefix; crafted suffix-collision) → distinct
     suffixes / general derived-path collision error.
R-15 absence assertion from partial-coverage entry → abstention or claimRef required.
R-16 runtime attribution phrasing: template match answered as source-declaration only.
R-17 double-home shadowing: drifted entry + still-verified v1 metadata-repository claim →
     SAFE rejects / reports shadowed-by-entry.
R-18 cross-system contradiction (entry facts vs verified claim) → CONTESTED surfaced.
R-19 manifest eligibility: chunk containing changed prose → rejected to ≤25 path.
R-20 validator wall-time at stress tier (50k) on Windows runner → within CI budget.
R-21 chunk interruption (kill after file 13/25; held-handle PermissionError) → completed
     stamps effective, rest not; deterministic resume list.
R-22 business-context refusal: draft with non-empty ## Business context → entry-draft rejects.
R-23 profile PATCH bump across corpus → zero lane changes; coalesced regeneration commit.
R-24 body `---`/fenced-YAML boundary fixture → single boundary rule, stable digests.
R-25 keyword edit outside executor → guard denies; executor edit → ledger-logged, lane unchanged.

## 8. Measured scale results (2026-07-24)

Run with `python scripts/knowledge_benchmark.py --entries N` on a synthetic corpus of approved
Flow entries. Environment: macOS/arm64, CPython 3.9.6, APFS. **These are this machine's numbers
on a synthetic fixture — not a certification for any real managed package, and Windows/NTFS
must be measured on Windows** (review R-20 remains open for that platform).

| Entries | identity p95 | facet p95 | relation p95 | text p95 | full index build | validator `.ai/**` sweep | entries on disk | index size |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 200 | 7.8 ms | 17.7 ms | 17.8 ms | 42.3 ms | 1.0 s | 5.8 ms | 0.26 MB | 0.45 MB |
| 2 000 | 57.7 ms | 90.0 ms | 97.9 ms | 117.6 ms | 10.3 s | 107 ms | 2.6 MB | 4.5 MB |
| 5 000 | 146.8 ms | 177.8 ms | 177.7 ms | 255.6 ms | 26.3 s | 454 ms | 6.6 MB | 11.1 MB |

Scaling is linear in corpus size across all measured operations. Conclusions, stated against
the proposed budgets rather than around them:

1. **The warm-query budget (p95 ≤ 250 ms) holds to roughly 5 000 entries and is exceeded
   beyond it.** Extrapolating the linear fit to a 15 000-entry target: identity ≈ 0.4 s,
   text ≈ 0.75 s. The deferred work — shard selection and term postings instead of a single
   linear scan — is therefore justified by measurement, not by taste, and must land before a
   target-scale corpus is onboarded.
2. **Full index build is ~5.2 ms per entry** (≈ 80 s at 15 000). Acceptable for an occasional
   rebuild, and the concrete argument for the deferred incremental rebuild.
3. **The validator's reserved-token sweep over `.ai/**` is not the problem the review feared**
   (R3-5 estimated 15–150 s at target scale): measured ≈ 0.45 s at 5 000 entries, extrapolating
   to ≈ 1.4 s at 15 000. No scoping change is needed; the concern is retired with evidence.
4. A defect this benchmark caught immediately: the first implementation re-projected the entire
   corpus on **every** query to prove freshness, costing ~1 s at 200 entries — the index bought
   nothing. Freshness now uses a stat-based corpus fingerprint, and correctness is preserved by
   hydrating (re-reading and digest-checking) only the results actually served. Identity queries
   went from 1 030 ms to 7.7 ms at 200 entries.

### 8.1. After the retrieval rework (same machine, same fixture)

The measurements above drove four changes: incremental rebuild with dependency-complete
reuse, a postings index (offsets, lanes, facets, relations, tokens, corpus statistics) split
into lazily loaded files, identity/relation fast paths that never hydrate the corpus,
rarest-token candidate selection for lexical queries with an explicitly reported cap, and
hydration that no longer re-parses the ledger (the freshness fingerprint already covers it).

| Entries | identity p95 | facet p95 | relation p95 | text p95 |
|---:|---:|---:|---:|---:|
| 5 000 | 92 ms | 126 ms | 127 ms | 168 ms |
| **15 000 (target)** | **183 ms** | **209 ms** | **190 ms** | **242 ms** |

**The p95 <= 250 ms budget now holds at the 15 000-entry target scale**, where the previous
implementation extrapolated to 0.4-0.75 s. Index size at 15 000 entries: 62 MB of generated
cache over 20 MB of entries (ignored by Git, disposable, never cited).

Build cost: a full rebuild is ~7 ms per entry (~107 s at 15 000) and is now rarely needed —
an incremental rebuild after a single change reuses every unaffected projection and completes
in **152 ms at 2 000 entries versus 13.7 s for a full rebuild (90x)**. Reuse is keyed on the
entry file, its source fragments, and the ledger together: keying on the entry alone served a
stale lane after source drift, which the drifted-lane golden query caught.

Still open on this axis: native-Windows latency (correctness on Windows is covered by the
cross-platform suite, which CI runs on windows-latest), and the validator's `.ai/**` sweep at
~1.7 s per run at 15 000 entries — acceptable but worth revisiting if the corpus grows further.

Re-run these tiers, plus a native-Windows pass, before any cutover decision.
