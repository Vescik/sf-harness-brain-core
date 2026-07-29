# Handoff plan — 2026-07-29

**For whoever picks this up next, with no memory of the session that produced it.** Every line
number below was re-verified against the current working tree on 2026-07-29, after the 11 commits
described in §1. Read §2 before touching anything: several of the rules there are the reason the
work exists at all.

Background, if you want it: `docs/knowledge-thread-2026-07-27.md` is the session record —
decisions, the defect register, and what the first real end-to-end run revealed. You do not need to
read it to execute this plan.

---

## 1. Where things stand

Branch `knowledge-relations-p0-p6`, **11 commits ahead of `origin`**, nothing pushed.

| Commit | What |
|---|---|
| `d0b09c1` | D1 (`--depth 0` was inert), D2 (`hubs` were inert), D6 (`entry-draft` crashed on a real Flow) |
| `519c196` | first real store — 80 entries, 1 feature, session records |
| `0b41706` | **B1** — an object can join a boundary through its own field |
| `3212c1b` | **B2 + hyphens** — a lane-filtered match no longer reports as an absence |
| `806e6cb` | `--limitation` / `--clear-limitations` on `entry-describe` |
| `f749626` | 90 limitations populated across 69 entries |
| `285a43a` | `service-delivery` split into `service-request` + `ticketing` |
| `2b31a4a` | **D3** — boundary names checked before a human signs |
| `3797ebc`, `4546398` | session records |
| `e8418f4` | the store approved: 80 entries + 2 feature rules |

**The store currently in `.ai/knowledge/` is dummy test data** built from a Developer Edition org
(`devmp`), not from the company's MPSA sandboxes. It exists to prove the machinery; it is deleted
in Phase 1. Do not treat it as knowledge about anything.

State: 80 entries `approved-current`, 2 features `approved-current`, `entry-check` PASS with 80
ledger records, `feature-check` PASS with 4, `validate_harness.py` PASS at 3166 checks.

Known-failing test, **pre-existing and unrelated** — confirmed failing on a clean tree:
`tests/test_salesforce_review.py::PinnedSalesforceMcpCompatibilityTests::test_pinned_server_still_supports_the_bounded_startup_flags`
spawns the pinned `@salesforce/mcp` server with `--help` and times out at 30 s on this machine.
Ignore it; do not "fix" it as part of this plan.

---

## 2. Ground rules

Break any of these and the work is worse than not doing it.

1. **Never approve anything.** `entry-approve`, `feature-approve`, `entry-revoke`, `feature-revoke`
   are intercepted by `scripts/copilot_safety_hook.py`; the human's confirmation *is* the approval
   (contract §6.5). You may propose the digest-pinned command. You may not spend the click.
   Phase 1's deletion is **not** a revocation — see §4.
2. **Every regression test must be confirmed failing against the previous code first.** Back the
   file up, `git stash push <file>`, run the test, restore. A test that passes both before and after
   proves nothing. This was done for all 11 commits; keep it up.
3. **`--limitation` and prose are digest-bound.** `limitations` sits inside `factsDigest` inside
   `reviewedContentDigest` (`scripts/knowledge_store.py`, `_canonical_facts`). Changing either after
   approval invalidates it. Not an issue in Phase 1+ because the store is being emptied, but it is
   why the ordering in the previous session was what it was.
4. **Guard and parser move in the same commit.** `tests/test_guard_parser_contract.py` diffs
   `copilot_role_guard.KNOWLEDGE_*_COMMAND_FLAGS` against each script's `build_parser()` in *both*
   directions. A new subcommand or flag missing from the guard fails CI. Any `store_true` flag must
   also join `KNOWLEDGE_SEARCH_VALUELESS_FLAGS` / `KNOWLEDGE_STORE_VALUELESS_FLAGS`
   (`copilot_role_guard.py:315` / `:319`) or the guard skips the *next* token unvalidated — that is
   the documented `--full` fail-open, not a style nit.
5. **Editing `scripts/knowledge_search.py` invalidates the search index.** `code_fingerprint()`
   (`:471-495`) digests the file itself, so every projection is discarded and
   `knowledge_search.py build --check` fails until you run `build --full`. This is by design. Only
   `text_analysis.py` edits additionally need an `ANALYZER_VERSION` bump.
6. **CI runs on ubuntu-latest AND windows-latest** (`.github/workflows/harness-ci.yml`). Everything
   in the 11 commits was validated on macOS only. Forward slashes in every path literal; the
   percent-encoding and Windows reserved-device-name handling in `knowledge_store.py` is deliberate.
7. **Counts are pinned in two places.** 24 prompts / 25 skills / 6 agents at
   `scripts/validate_harness.py:25` and `tests/test_repo_map.py:61-63`, plus the repo-map word
   budget (`scripts/render_repo_map.py:31`, duplicated by hand at `validate_harness.py:1087`).
   **Nothing in this plan adds a prompt or skill**, so none of these should move. If you find
   yourself editing them, stop and re-read the phase.
8. **`origin` is PUBLIC** (`Vescik/sf-harness-brain-core`). The dummy entries describe a real org's
   objects. Do not push this branch to `origin` until Phase 1 has removed them — that ordering is
   the whole reason Phase 1 precedes Phase 3.

---

## Phase 0 — pending, human only

A private snapshot repo exists: **`Vescik/sf-harness-knowledge-pilot`** (created, empty).

The push was blocked by the permission classifier, so the owner runs it:

```bash
git remote add pilot https://github.com/Vescik/sf-harness-knowledge-pilot.git
git push pilot knowledge-relations-p0-p6:main
```

This preserves all 111 commits, including the approved store, in a private repo.

**Open decision, owner's call.** `force-app/main/default/**` is gitignored, so the retrieved
metadata will **not** reach the snapshot. Without it every entry reads `approved-drifted` on
checkout (measured: removing a source file moves its entry to that lane, it is not revoked). If the
snapshot should be self-contained, add one clearly-labelled commit *to the pilot remote only* that
`git add -f`s `force-app/main/default`. Do not do this without the owner saying so — it deviates
from the `.gitignore` policy deliberately set by `chore/ignore-force-app-metadata`.

**Phase 1 does not depend on this.** The knowledge lives in commits `519c196`, `f749626` and
`e8418f4` in local history; deleting the files is a new commit, not a history rewrite.

---

## Phase 3 — push to origin (after Phase 1, before or after Phase 2)

Once Phase 1 has landed, the branch carries no org metadata and no entries describing one, so it is
safe for the public remote. This also gets the 11 commits onto **both CI legs** for the first time —
see ground rule 6. The commit immediately before this work was literally *"Fix what the first CI run
found, on both legs"*, so expect Windows to have opinions.

Pushing is outward-facing: propose the command, let the owner run it.

---

## Phase 1 — clean the workspace (S)

Goal: return this repo to a state fit for company use — no dummy knowledge, no retrieved metadata,
every fix from the 11 commits retained.

### 1a. Remove the tracked store

84 files were added under `.ai/knowledge/` since `e441442`: 80 entries, 2 feature entries, and both
ledgers. At `e441442` the directories `artifacts/` and `features/` **did not exist in git at all**,
and neither ledger existed — verified with `git ls-tree -r --name-only e441442 .ai/knowledge`. So
the target state is exactly `e441442`'s.

```bash
git rm -r --quiet .ai/knowledge/artifacts .ai/knowledge/features
git rm --quiet .ai/knowledge/artifacts-ledger.jsonl .ai/knowledge/features-ledger.jsonl
```

**This is a deletion, not a revocation, and that is correct here.** `entry-revoke` appends a
revocation record and leaves a revoked entry in the store — the right tool for retiring knowledge
you once meant. This corpus was never meant; it is test data being discarded wholesale, and 80
revocations would leave a store full of tombstones for an org nobody works on.

### 1b. Remove the gitignored leftovers

None of these are in git; they are on disk and must not reach a company workspace.

| Path | Files |
|---|---|
| `force-app/main/default/**` (keep the 13 tracked `.gitkeep`) | 104 |
| `.cache/**` | 169 |
| `output/knowledge-approvals/` | 11 |
| `output/feature-dossiers/` | 3 |

Delete the metadata **without touching `.gitkeep`**:

```bash
find force-app/main/default -type f ! -name '.gitkeep' -delete
find force-app/main/default -type d -empty -delete    # leaves the .gitkeep-bearing dirs
rm -rf .cache/* output/knowledge-approvals output/feature-dossiers
git status --short force-app     # MUST be empty: all 13 .gitkeep still tracked and unmodified
```

### 1c. Keep

- `config/harness.local.json` — gitignored, and its `knowledge.chatReviewer` block is real
  configuration added this session. Without it **every** approval fails. Leave it.
- Every code fix and test from the 11 commits.
- Every document under `docs/`.

### 1d. Verify

```bash
.venv/bin/python scripts/knowledge_store.py entry-check      # entries 0, ledgerRecords 0, PASS
.venv/bin/python scripts/knowledge_store.py feature-check    # features 0, ledgerRecords 0, PASS
.venv/bin/python scripts/validate_harness.py                 # PASS, counts 6/24/25/3 unchanged
.venv/bin/python -m pytest tests/ -q                         # only the known MCP timeout fails
```

Commit. Say in the message that the corpus was dummy Developer-Edition data, that the machinery it
proved is retained, and that the snapshot lives in the private pilot repo.

---

## Phase 2 — D7 (S)

**`feature-review` cannot render a surface for an already-approved feature, which blocks the exact
remedy the tool itself prescribes.**

`scripts/knowledge_store.py:1839`, inside `command_feature_review` (def at `:1825`):

```python
        if lane["lane"] == "approved-current":
            continue
```

Unconditional — it ignores an explicit `--slug`. The entry-side equivalent at `:1112` reads
`if not wanted and frontmatter["lifecycle"]["state"] != "draft":`. Those two words are the whole
difference, and entry-side re-review is a *designed* path: `classify_chunk` (`:944`) exists solely
to label re-approvals, printing `- change: facts-only re-approval`.

Why it matters: when `feature-approve` cannot reach an index it pins no `membershipDigest` and says
so (`:2016-2021`), and `feature-drift` repeats the advice (`knowledge_search.py:2711-2717`) — *"re-approved
against a reachable index"*. Neither is reachable. `command_feature_approve` (`:1948-1971`) would
happily accept the re-approval; only the review surface refuses to render the pinned command. The
only workaround is `feature-propose --replace` + `feature-describe`, which returns the feature to
`draft` and changes its digest — a different approval, not a re-approval.

This bit for real: both features had to be approved twice on 2026-07-28, because approving 80
entries moved them all out of `draft` and staled the index the digest is computed against.

### Fix

```python
-        if lane["lane"] == "approved-current":
-            continue
+        if not wanted and lane["lane"] == "approved-current":
+            continue
```

Companion, same function, matching the B2 precedent from `3212c1b` — a bare `feature-review` over a
fully-approved store currently returns `"skipped": []`, telling the caller nothing:

```python
        if lane["lane"] == "approved-current":
            if not wanted:
                skipped.append({"identity": lane["identity"],
                                "reasons": ["already approved-current; name it with --slug to re-render"]})
                continue
```

### Test

Add to `FeatureEntryTests` (`tests/test_knowledge_store.py:1186`; helpers `self.propose()`,
`self.describe()`, `self.approve_feature()` at `:1194-1216`): approve a feature, then assert
`command_feature_review(Namespace(slug=["scheduling"]))` returns `REVIEW_READY` with an
`approveCommand` carrying the same digest, while `Namespace(slug=None)` still returns
`NOTHING_TO_REVIEW`.

### Notes

- **No test pins the current behaviour.** All three existing `NOTHING_TO_REVIEW` assertions are other
  paths (`tests/test_knowledge_store.py:335`, `:958` are entry-side invalid drafts; `:1258-1262` hits
  the `lane["problems"]` branch at `:1835`, not `:1839`).
- No guard or parser change: `--slug` is already allowlisted at `copilot_role_guard.py:270`, and
  `feature-review` is correctly outside `KNOWLEDGE_STORE_MUTATION_COMMANDS`.
- No contract amendment: §13.5 step 3 never says the surface renders only drafts.
- **Follow-on, do not bundle:** the feature review artifact has no `- change:` line, so a re-rendered
  surface is byte-identical to the original and a reviewer cannot tell they are re-approving. Add the
  entry-side equivalent as a separate item.

---

## Phase 4 — the improvement register

Independent of each other. Ranked by value; take them in order unless something argues otherwise.

### 4a. F3 — no snippet in `search` rows or `explain` (M)

**Reword the item before you start: "no retrieval surface" is false.** `context --identity` already
returns the full Purpose (`knowledge_search.py:2297`, pinned by `tests/test_knowledge_search.py:698`).
Scope this to `search` and `explain`, and copy `context` as the precedent.

Today a `search` row gives isolated matched tokens, so every ranking error costs a file open —
retrieval is a file locator, not an answering system. The prose is already in memory: `project_entry`
(`:352`) stores it at `:437`, `load_many` (`:937`) has it before `hit_of` (`:1079`) runs.

- **`explain` (S):** add to the return dict at `:1782`, next to `"facets"` (`:1788`):
  `"purpose": document.get("purpose")` plus a `"purposeBasis"` string.
- **`search` (M):** add a `purpose_snippet(document, matched)` helper beside `hit_of`; window ~240
  chars centred on the longest matched `purpose` term, clip on word boundaries with `…`. Return
  `None` when the text starts with `<AGENT_` — an unfilled draft sentinel is an absence, not prose,
  and `--state draft` routes drafts through this same funnel.
- **Labelling is the load-bearing part.** Do not name the search-row key `purpose`; a full-text key
  implies the whole approved statement. Use `snippet` + `snippetBasis` saying it is an excerpt, that
  it is clipped for display, and that the citable unit is `citation.path` + `citation.entryDigest`.
  This matches the file's existing self-describing convention (`draftCandidatesBasis` `:1479`,
  `lifecycleBasis` `:1476`).
- **Safety argument for the commit message:** `hydrate()` (`:1102`) runs at `:1447` before hits are
  served and drops any hit whose whole-file digest no longer matches, so a served snippet is provably
  a substring of the file named in `citation`.
- No rebuild, no schema bump — read-side only.

### 4b. F2 — function words score and the verdict is still `OK` (M)

A sentence-shaped query whose only content word matches nothing returns `outcome: OK` on the strength
of `the` and `is`. A store whose entire pitch is honest absence reporting is manufacturing relevance.

**Do not touch `scripts/text_analysis.py`.** No stopword list, no `ANALYZER_VERSION` bump, no
reindex — the fix is corpus-derived and lives entirely in `knowledge_search.py`.

1. New helper `query_term_stats(...)` above `bm25f` (`:1044`), reading the
   `posting_file("stats")["documentFrequency"]` that `:1053` and `:1207` already read. One row per
   token: `{term, documentFrequency, corpusSize, idf, matched, saturated}` where `saturated` is
   `df >= DF_SATURATION * count`. Add `DF_SATURATION = 0.5` beside `BM25_K1`/`BM25_B` at `:93-94`.
2. In `run_search`, after the `interpreted` dict closes at `:1174` — **before** the seeding block at
   `:1203`, which is guarded by `and not other_facets` and cannot host it — compute `query_terms` and
   emit it as `"queryTerms"` next to `"interpretedQuery"` at `:1474`.
3. In the `elif args.text:` branch after `results.sort(...)` (`:1366`), derive contributing terms from
   `scored`, **not** from `hit["matchedOn"]` which `hit_of` truncates to 8 (`:1088`). If nothing
   discriminating contributed, empty `results` and append a gap naming the facts; `:1473` then yields
   `NO_MATCH` on its own — do not edit `:1473`. Separately, when the rarest query term has
   `documentFrequency == 0`, disclose it even when results *are* served.
- **No rebuild needed** — `documentFrequency` is already persisted at build time (`:789`, `:804`).
- Protect `tests/test_knowledge_search.py:330` (`mpsaCard`, the B2 test): it depends on
  `lexical_token_ids`, which is exactly why step 2 must not touch seeding. `:513` already accepts
  either outcome; `:520-524` already expects `NO_MATCH`.

### 4c. F4 — dossier path collision and a discarded lane-drop count (M)

Two independent halves. **Half 1 first** — it also unblocks the P5.3 work in
`docs/spec-p5-attested-claim-lane-2026-07-27.md`.

**Half 1 — separate the two writers.** `knowledge_search.run_feature_dossier` and
`force_app_knowledge.render_dossier` both write `output/feature-dossiers/<slug>.md` with different
content models; whichever runs last silently replaces the other. The crawl dossier is a *proposal*
and its input JSON already lives in the disposable cache, so move its writer to match:
`force_app_knowledge.py:399`, `dossier_root` → `.cache/knowledge-proposals/feature-dossiers/`. Then
add a mutual sentinel guard in both writers — refuse if the target's first line carries the other
model's H1 prefix (`"# Feature — "` vs `"# Feature Dossier — "`). Update the prose naming the old
path: `.github/skills/feature-documentor/SKILL.md:43`,
`.github/prompts/feature-documentor.prompt.md:19`, `audit/module-map.md:164,167,324,344`,
`docs/knowledge-one-file-contract.md:720`.

**Half 2 — carry the lane-drop through.** `traverse` counts `excluded["lifecycle"]` and
`compute_membership` discards it, so a dossier emptied by the default lane filter reports
`gaps: []`. Worse, `_requested_states` defaults to `("approved-current",)` and the parser gives
`--state` no default, so the **default** invocation is the lane-emptying one — and anchors are offered
through an unfiltered lookup, so the result reads as a plausible small dossier rather than a broken
empty one.

> **Do not "fix" this by passing `allowed=None` to `traverse` and filtering afterwards.** Traversal
> would then expand *through* out-of-lane nodes, changing the member set and therefore every approved
> `membershipDigest`. Keep traversal behaviour byte-identical; add reporting only, and never fold the
> new set into a digest input.

Accumulate `excluded_identities` in `traverse`, union it in `compute_membership`, **subtract
`member_ids` before counting** — an artifact reachable by another in-lane path is not excluded, and
this is the exact double-count trap the `belowFloor` comment documents having already been fixed once.
Surface it in `run_tree`, `run_feature_drift`, `run_feature_dossier`, and in the approval receipt at
`knowledge_store.py:1941-1945`, where a human currently pins a membership digest without being told
how many artifacts the lane filter removed from it.

### 4d. Edge resolution and the coverage surface (M)

**Fix the resolution before reporting it — publishing today's values would be legibly wrong.**

`build_relation_index` (`knowledge_search.py:562`) computes a per-target `resolution`
(`resolved` / `no-entry` / `ambiguous`) that **nothing reads**: four occurrences, three writes and one
default, and both `target_row` callers (`:1897`, `:1904`) read only `targetIdentity`. Measured on the
dummy store: 62 of 164 edges `no-entry`, of which **21 name a field that does have an approved entry**
— `by_full_name` (`:576-582`) keys on the qualified `Object.Field` while extractors emit bare member
tokens. `force_app_knowledge.py:5307` already builds exactly the index that fixes this. The
consequence is not cosmetic: `impact --identity ApexClass:c:Logger --direction outgoing --depth 2`
dead-ends at depth 1 on five targets that are approved entries in the same index.

1. Add a `by_member` index keyed on the bare member name; resolve a single candidate as
   `resolved-by-member` (a distinct value keeps the qualified/bare distinction visible), multiple as
   `ambiguous`. This repairs `impact`/`context`/`tree` for free.
2. Add `decidable: bool` using `entry_edge_health`'s published rule — only unnamespaced
   `__c`/`__e`/`__mdt`/`__b`/`__x` targets are decidable. Treat `<Custom__c>.<StandardField>` as
   undecidable too; `Category__c.Id` will never have a CustomField entry.
3. Roll the counts into the generation manifest beside `laneCounts` so `build --check` pins them.
4. New read-only `knowledge_search.py edge-health`, registered in
   `copilot_role_guard.KNOWLEDGE_SEARCH_COMMAND_FLAGS` (`:281-309`) in the same commit. Surface
   `truncatedSources` (`:624`) too — computed since forever, never exposed.
5. `coverage`/`dashboard` report **0 % documented on a store with 80 approved entries**, and the
   "Document next" panel lists 25 components that are already done, because `coverage()` (`:5492`)
   derives from a claims worklist reading `.ai/knowledge/claims` — empty by construction on an
   entry store. **Make it refuse** rather than teaching it a second denominator: raise
   `KnowledgeBuildError` naming the replacements. `dashboard`'s `panel()` already catches that and
   degrades to "unavailable — run <remedy>".
6. New `force_app_knowledge.py entry-readiness` as the entry-side counterpart, deliberately separate
   so neither denominator can be mistaken for the other.

**Two traps.** `tests/test_force_app_knowledge.py:774-786` asserts `coveragePercent == 0` on a
fixture with an empty claims dir — gate the refusal on *"no claims AND approved entries exist"* (the
fixture has no entries) rather than weakening it. And `relation-health` validates against
`force-app-relation-health.schema.json` (pinned by `tests/test_force_app_knowledge.py:3536-3580`), so
any new field needs the schema updated in the same commit.

**Do not rebuild `entry_edge_health`** (`force_app_knowledge.py:5272-5378`). It already exists and
answers a *different* question — "does this edge target still exist in force-app source?" versus
"does it have an entry?". Both reports must say so, or a reader will assume one supersedes the other.

---

## 5. Not in this plan

Recorded so nobody re-derives them:

- **P1 `from-notes`** — a mode that turns a human's own prose into a Feature Entry.
  `docs/discovery-2026-07-27-authored-feature-entry.md`. Judged a *convenience*, not a blocker,
  after one feature was authored by hand without it.
- **P5, the attested-claim lane** — `docs/spec-p5-attested-claim-lane-2026-07-27.md`. **Parked**: the
  owner moved the operating system to the one-file entry model and parked the v1 claim registry.
  Accepted consequence: business meaning is not citable. Note that `object-ownership` claims remain
  structurally required by `work_record.py`'s SAFE/complete gate, so "parked" means no new *semantic*
  claim lanes, not a dead registry.
- **Pointing the harness at the real MPSA org** — `config/harness.local.json` still holds
  `<MY_DOMAIN>` and `<*_ORGANIZATION_ID>` placeholders, and the schema's `expectedInstanceHost`
  pattern accepts only `*.sandbox.` and `*.scratch.` hosts, so the Developer Edition org used for the
  pilot could never have been registered. Owner decision, not a task.
