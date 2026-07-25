# Phase audit — shipped phases, and P4's entry gate

Date: 2026-07-25 · Status: **P4 remains BLOCKED** · Scope: P0, P1, P2, P3, P5, P6

Three lenses (gate completeness, cross-phase regression, P4 readiness) re-verified every shipped
phase **by execution** against a 189-component reference corpus and a synthetic benchmark. All
three returned GAPS-FOUND: **31 findings, 7 flagged blocking**.

## Why this document exists

The plan required a gap check before each phase. For P0 that happened and it worked — 36 gaps,
six of them errors in the plan itself. After P0 the checks degraded into spot checks, and phases
shipped on the strength of their own commit messages. This audit is what the discipline should
have been throughout; it found two blocking defects in code already reported as done.

## Blocking findings, and their disposition

| # | Finding | Status |
|---|---|---|
| 1 | `explain` and `context` never lane-filtered or hydrated **the anchor**, so a revoked, drifted or silently tampered entry was served in full with its stale `entryDigest` — while `search` refused the same entry | **fixed** (`verify_anchor`) |
| 2 | `explain.parts` — the composition primitive P4's membership is built on — had no lane filter and no cap, serving revoked entries as parts of an approved object | **fixed** |
| 3 | The "mixed benchmark corpus" contained no CustomObject, ApexClass or ApexTrigger, so every traversal it existed to exercise was timing an **empty answer** | **fixed** (objects + a real Apex chain; verified reaching hop 2) |
| 4 | `peakRssMb` was not instrumented anywhere, so the memory half of every R4 budget was unmeasurable | **fixed** |
| 5 | `hydrate()` recomputes only `reviewedContentDigest`, which does not cover `source.fragments`, `scope` or `keywords` — an edit confined to those is invisible to both the coarse fingerprint and hydration | **open** |
| 6 | The 40 ms freshness budget is unverified on `windows-latest`; the macOS measurement is a warm in-process loop, while the thing budgeted is the cold per-CLI-process floor (35.6 ms p95 at 15k = 89 % of budget on a *faster* platform) | **open** |
| 7 | No reusable traversal exists for P4 to build `compute_membership` on — the BFS is inline in `run_impact`, single-anchor, and returns hits rather than a node set | **open, P4 design input** |

Findings 5–7 are why **P4 is not started**. 5 and 6 are correctness/measurement debt that P4 would
inherit and amplify; 7 is a refactor P4 needs before it can honour the plan's "one traversal
vocabulary" rule.

## Notable non-blocking findings

- **P6's Set A was 7 of 8, not the 8 of 8 reported.** The gate counted a set assembled by hand
  (including `search-knowledge`, which is the menu owner and not in Set A) rather than the set the
  plan names; `generate-technical-documentation` was missed. **Fixed** — and the lesson is the
  finding: a gate that counts its own list can be green and mean nothing.
- `context --identity` always returned `subject.purpose: null` — the projection tokenizes purpose
  for ranking but never kept the prose. **Fixed.**
- `context` filtered rows by lane but never labelled them. **Fixed.**
- `explain` still has no `--top`, so `incoming` is unbounded. **Open.**
- `APEX_NEW_RE` was a third `factsDigest` move, landing after D1 declared the window closed. It was
  free (zero approved entries) but was not re-authorised. **Recorded, not re-litigated.**
- `relation-health`'s entry population reports schema problems but does not yet diff entry edges
  against live source — the orphan half of its own acceptance line. **Open.**
- The dossier's no-description fallback misattributes the cause when an entry exists but is
  undescribed. **Open.**

## Standing rule for the remaining work

No phase starts until the previous phase's gate has been re-verified **by execution**, against
the plan's own list rather than a list assembled while checking. A phase's commit message is
evidence of intent, not of outcome.
