# Knowledge authoring thread — session record, 2026-07-27

Working record of one session. Two deliverables came out of it, plus a set of decisions and a
verified defect register. **Nothing was implemented.** This file exists so the thread is not lost.

Companion documents:

- `docs/discovery-2026-07-27-authored-feature-entry.md` — discovery: where a human's own feature
  description belongs.
- `docs/spec-p5-attested-claim-lane-2026-07-27.md` — full implementable spec for the
  human-SME-attested claim lane.

---

## 1. What was asked

The owner wanted a prompt that turns **their own prose** into Knowledge: *"I describe a feature
manually — how to reach it in the UI, what components it consists of, I supply the metadata API
names — and the agent turns that into a Knowledge entry, keeping the format of the automatically
generated entries."*

Driving scenario, used throughout as the acceptance test:

> `Project__c`, reached through a Lightning Page; inside it a custom navigation built in a
> **managed package** over `X__c`/`Y__c`/`Z__c`; clicking it opens Visualforce page `Example`; its
> buttons open a second VF page; the result maps onto `Kamien__c`.

Goals: feed test-case creation with real technical detail, support enhancement work across
managed-package + custom development, let the agent resolve API names via knowledge search and
complete the docs from existing entries, and optionally use screenshots as input.

## 2. Answer, in one line

**The ask is right; the target record is wrong.** An artifact entry cannot hold authored prose — its
frontmatter is collector output by construction, its body accepts only `## Purpose`, and it cannot
exist at all for a component absent from `force-app`. The Feature Entry already *is* the record
being described. See the discovery document for the full argument.

## 3. Decisions taken

| # | Decision | Status |
|---|---|---|
| D-A | Human narrative → **Feature Entry body**; human-declared membership → **`boundary.include[]`**; component facts → unchanged `entry-draft`. This split needs no new `assurance` value inside `factsDigest`, which is what makes it safe. | settled |
| D-B | Deliver as a **`from-notes <slug>` mode on `/curate-knowledge`**, not a new prompt+skill pair. Zero new files, zero pinned-literal moves, zero guard changes. | settled |
| D-C | Owner: *business meaning must be citable* → P5 (the `human-sme-attestation` lane) is required. | superseded by D-D |
| D-D | **Build P5 — but not for citability.** Citation is nearly inert in this harness. The real wins are **expiry**, **discoverability**, and **managed-package surfaces having no other home**. | settled |
| D-E | Ship **P1 before P5.1**. Mint **2-3 claims per feature**, not 5. | settled |
| D-F | Open question 3 of the P5 spec closed as **NO** — do not make `business-meaning` required at the SAFE gate. | settled |
| D-G | Owner: *"przechodzimy na v2"*, clarified — **the one-file Knowledge Entry model is the operating system; the v1 claim registry is parked.** | settled — see §7 |

### Why D-D reframed D-C

Citation buys three things: a frozen content snapshot folded into `groundingHash`, re-resolution at
two moments (design approval and the SAFE/complete state), and membership in a set a human signed
off on. It does **not** buy any link between a *sentence* and a claim — `groundingHash` binds the
*set*, `record.design.sha256` binds the prose, nothing correlates them, and `verify-citations` is
advisory and never run by CI. The SAFE gate accepts any one claim or entry, and the only claimType
ever *demanded* is `object-ownership`.

What survives the reframe:

1. **Expiry.** A Feature Entry has no `reviewBy` and `additionalProperties: false`. Its prose never
   goes stale. Source-drift cannot help — business meaning rots with the business, not the code.
   An attested claim expires by itself and `stale-report` surfaces it.
2. **Discoverability.** `knowledge_search.build` projects `store.all_entry_paths()` only, so Feature
   Entry bodies are the one thing `search --text` cannot find.
3. **Managed-package surfaces.** `ApexPage` is absent from `knowledge_store.PROFILES` and the
   component is not in `force-app`, so it can never have an entry and never have
   `metadata-repository` evidence. The claim registry is the only home its meaning will ever have.

Cheaper routes to (1) and (2) were considered and rejected: `reviewBy` on a Feature Entry lands
inside `reviewedContentDigest`, so adding it later re-approves every feature; a second search
projection moves `corpus_fingerprint`. Both touch load-bearing digest/index machinery mid-flight,
while P5 needs no schema change at all.

## 4. Defect register — all verified by reading or running the code

| # | Defect | Evidence | Cost of delay |
|---|---|---|---|
| **D1** | `--depth 0` is inert. `compute_membership` clamps to 0, then calls `traverse(..., depth=max(depth, 1), ...)`, and `traverse` loops `for level in range(depth)`. A "0-depth" rule executes one full incoming BFS level while the schema promises "anchors only". | `scripts/knowledge_search.py:2291`, `:2313`, `:1814`; `schemas/knowledge-feature-entry.schema.json:66-70` | inside `boundaryDigest` — free now, re-approval of every feature later |
| **D2** | `hubs` is inert for membership. Its only occurrence in `knowledge_search.py` is the **dossier table row** at `:2757` labelled "kept as targets, never expanded". `compute_membership` never reads it; `traverse` has no hub parameter. `feature-crawl` *does* honour hubs (`force_app_knowledge.py:6331`, `:6503-6504`), so crawl and membership disagree. | `scripts/knowledge_search.py:2757`, `:1776-1784` | same — inside `boundaryDigest` |
| **D3** | `feature-propose` accepts any string as anchor / include / exclude. No resolution, no warning. A typo lands inside an approved, digest-bound rule. | `scripts/knowledge_store.py:1604-1620` | grows with corpus |
| **D4** | `config/harness.local.json` has **no `knowledge` block**, so `knowledge.chatReviewer` is unset and **every** `entry-approve` / `feature-approve` fails. | `scripts/knowledge_store.py:829-835`; `knowledge_registry.py:1738-1741` | blocks everything |
| **D5** | *(found while starting execution)* **`force-app` is an empty skeleton** — 13 tracked `.gitkeep` files plus `lwc/jsconfig.json`, zero metadata. Stray empty directories named `Assignment__c 2`, `ScheduleConflict__c 2`, `Resource__c 2` … are Finder duplicate-copy artifacts named after the pilot package. | `git ls-files force-app` → 13 entries, all `.gitkeep`; `find force-app -type f` → 14 | **blocks any end-to-end run** |

D1 and D2 are free to fix while `.ai/knowledge/features/` is empty and permanently costly after the
first approved `membershipDigest`.

## 5. Verified facts worth keeping

Things that were checked directly and would be expensive to re-derive.

- **The store is empty.** `.ai/knowledge/{claims,evidence,reviews,features,artifacts}` all exist and
  all contain nothing. Everything real lives in `output/pilot-2026-07-25/`.
- **`contentDigest` is never recomputed** by the registry — zero occurrences in
  `knowledge_registry.py`; a test fixture promotes a claim whose digest is literally `sha256:ccc…`.
- **`independenceKey` is fail-open** — it defaults to `evidenceId`, so N receipts from one person
  count as N independent sources. `.ai/templates/knowledge-entry.md:129` actively tells authors to
  omit it.
- **The guard denies every digest and clock tool.** Verified in-session against the real
  `allowed_role_command`: `python -c`, `shasum`, `sha256sum`, `date` → `False` for both
  `knowledge-curator` and `config-investigator`; `propose` / `approve-claim` → `True` for both and
  `False` for `solution-designer`. This is why P5 needs a `mint-attestation` executor.
- **`validate_feature` has no section allowlist and no sentence cap** — schema + sentinel +
  `"## Purpose" not in body`, nothing else (`knowledge_store.py:1534-1546`). `### …` subsections are
  legal, and `run_feature_dossier` renders `body.split("## Purpose", 1)[-1]` verbatim
  (`knowledge_search.py:2692`).
- **Anchors and `boundary.include[]` already carry `human-declared` assurance**
  (`knowledge_search.py:2312`, `:2327-2328`) — a value the entry `assurance` enum cannot produce.
- **`knowledge_search.py` has never imported `knowledge_registry`**, so a feature dossier cannot
  surface an attested claim today.
- **Feature-tag convention collision:** `force_app_knowledge.feature_draft` writes the feature
  *display name* into `claim.feature` (`:6367-6369`) while `knowledge_store` keys on the
  lowercase-hyphen *slug*. Two producers, two formats, no detector.
- **Pinned counts:** 24 prompts / 25 skills / 6 agents at `scripts/validate_harness.py:25` and
  `tests/test_repo_map.py:61-63`; atlas `wordCount` 872 against `WORD_BUDGET` 875 — **3 words of
  headroom**, with the budget duplicated by hand at `validate_harness.py:1087`.
- **P5's lane was proven end to end** in a throwaway registry root built from the repo's real
  schemas and policy: 5 claims on 1 shared receipt, all promoted to `verified` rev 2,
  `verify-citations` → ok, `--refresh-verified` re-attestation to rev 4.

## 6. The plan as it stood before the v2 pivot

Recommended order, on the reasoning that this project has extraordinary design rigor and near-zero
production data — the binding constraint is *"we have no knowledge"*, not *"we lack a lane"*.

1. **Set `knowledge.chatReviewer`** (D4). One line; nothing can be approved without it.
2. **Fix D1 and D2** while the feature corpus is empty. Ship a depth-0 regression test — there is
   none today.
3. **Push one real feature end to end, by hand**, through the existing `curate-knowledge
   feature <slug>` cockpit — then read the dossier and ask whether it is actually useful. This is
   the question nobody has answered: the pilot ran against a synthetic package with no managed
   package in it. **Blocked by D5 — there is no metadata in this repo to run it against.**
4. **Then** decide about P1 and P5 from what was actually missing in (3), not from a spec.

Step 3 also settles the P1 argument by itself: if one feature by hand is tolerable, P1 is a
convenience and P5 becomes the real question; if it is painful, P1 is the blocker and P5 waits.

**Standing risk to enter deliberately:** the 350-day re-attestation cycle is a maintenance
commitment, not a one-off cost. On a one-person team, cap attested claims to features actually being
enhanced. General documentation belongs in the Feature Entry, which does not expire because it does
not promise to be current.

## 7. The v2 pivot (D-G) — resolved

The owner stated **"przechodzimy na v2"**. Clarified in session: **v2 means the one-file Knowledge
Entry model becomes the operating system, and the v1 claim registry is parked.**

Note what "v2" does *not* mean here. `docs/knowledge-facts-overlay-architecture.md` — the separate
facts lockfile + attested overlay — stays **shelved**; its own header already names the one-file
model as the successor that absorbed its motivation (facts inside the entry, derived facts without
per-claim clicking, governance only where judgment lives). That design is not being un-shelved.

### Consequences, accepted

- **P5 is parked in full.** `docs/spec-p5-attested-claim-lane-2026-07-27.md` is built entirely on
  the v1 claim registry. It stays as a decision record; nothing from it gets implemented.
- **Business meaning loses citability.** This is the deliberate trade. Contract §8.1 routes business
  meaning, runtime behavior, org state and package limitations to a `claimRef` + `evidenceRef`, and
  an entry cannot carry any of them. With the registry parked, *"this feature exists so a planner
  can finish an allocation without leaving the project"* lives as **prose in the Feature Entry** —
  human-approved, digest-pinned, ledger-recorded, and **never citable**.
- **What is given up with it:** expiry (a Feature Entry has no `reviewBy`), discoverability
  (`knowledge_search.build` projects entries only, so feature bodies are unsearchable), and any home
  at all for the meaning of managed-package surfaces like `ApexPage:npnav__Example`, which can never
  have an entry. These were the three real wins identified in D-D. They are now open costs, not
  solved problems.
- **Park ≠ remove, and park is narrower than it sounds.** No code is being deleted.
  `knowledge_registry.py`, the claim/evidence/review schemas and `config/knowledge-policy.json` stay
  in place and stay green in CI.

  **`object-ownership` claims are structurally mandatory and stay live.** `work_record.py:1416-1421`
  refuses a SAFE/complete record if any scope component has `ownership == "unknown"` **or** its
  `ownershipClaimRef` is not among the bound claims. So the registry is load-bearing for governed
  change records regardless of what happens to Knowledge authoring. Parking therefore means: **no
  new *semantic* claim lanes** (business-meaning, business-process, glossary, attestation) and no
  new producers for them. Structural claims — ownership, package installation, and whatever else a
  governed record needs — are untouched.

  Worth verifying separately, out of this thread's scope: no skill under `.github/` names
  `object-ownership` at all (`rg -n "object-ownership" .github/` → no hits), so which producer is
  expected to mint the ownership claims a SAFE record requires is currently unclear.

### Unaffected

§6 stands unchanged — it was always about entries and the Feature Entry, not about claims. D1, D2
and D3 are entry/feature machinery. D4 and D5 block regardless.

## 8. Execution log — 2026-07-27

### D4 — closed

`config/harness.local.json` gained the block the approval gate refuses without:

```json
"knowledge": { "chatReviewer": "Dominik Machowski" }
```

Validated against `schemas/harness-config.schema.json`: the `knowledge` object contributes **zero**
errors. The file still carries 7 pre-existing placeholder errors — `<MY_DOMAIN>`,
`<DEV_ORGANIZATION_ID>`, `<QA_ORGANIZATION_ID>`, `<UAT_ORGANIZATION_ID>` and the ADO block. Those
block org and ADO work; they do not block Knowledge approval.

### D1 and D2 — closed, `scripts/knowledge_search.py` (+36 / −4)

**D1.** `compute_membership` now calls `traverse(..., depth=depth, ...)` instead of
`depth=max(depth, 1)`. `depth: 0` walks no levels, which is what "anchors only" has to mean for a
caller that offers its anchors itself.

**D2.** `traverse` gained a keyword-only `stop_at` parameter, matched against a reached node's
identity **and** its `fullName`. A node on the stop-list is appended to `chains` — kept as an edge
target, per the schema's own wording — but not to `next_frontier`, so nothing expands through it. It
joins `visited` regardless, otherwise it is re-offered once per branch that reaches it.
`compute_membership` passes `boundary["hubs"]`.

Two new reporting keys, neither of which touches `membershipDigest` (that digest is taken over
member identities only, `:2346`): `traverse` returns `stoppedAt`, and `compute_membership` returns
`hubs: {declared, stoppedAt}` — a rule whose hubs never fire is a rule approved for a reason that
did not happen, and only the walk can say so.

**Semantics chosen, and the divergence it exposes.** A hub is **kept as a member and not expanded
through**, per `schemas/knowledge-feature-entry.schema.json:59-64` and contract §13.1 — *"kept as an
edge target but never expanded through"*. `force_app_knowledge.feature_crawl` does something
different: `:6227` and `:6233` `continue` before `boundary_objects.add(...)`, so a hub is dropped
from the crawl's object set entirely. **The two lanes now disagree on hub semantics.** The schema is
what a human approves against, so the entry lane follows the schema; `feature-crawl` is the older
lane and was left alone. Worth reconciling before both are used together.

**Note on current impact.** Traversal is reverse-only (`BASELINE_DIRECTION = "incoming"`), so an
anchor never walks out to the objects its own fields point at — which is why `Resource__c` is a hub
in the pilot and appears as no member at all. Hubs are therefore near-inert *today* and become
load-bearing the moment traversal direction changes, which is exactly what makes fixing them cheap
now.

### Tests — `tests/test_knowledge_search.py` (+52 / −1)

Three new regression tests in the R7 depth section, plus one deliberate contract-test update
(`traverse`'s pinned return-key set gained `stoppedAt`).

- `test_depth_zero_is_anchors_and_declared_includes_only`
- `test_a_hub_is_kept_as_a_member_but_never_expanded_through`
- `test_a_declared_hub_that_never_fires_is_reported_as_such`

**All three were confirmed to fail against `HEAD` before the fix** — the file was reverted, the
tests run, and the fix restored from a backup. The depth-0 failure is worth recording verbatim: at a
declared depth of **0**, the old code returned `HarnessAlphaCase__c` plus `ApexClass:c:HarnessAlphaSelector`,
`CustomField:c:HarnessAlphaCase__c.Status__c`, `CustomField:c:HarnessBetaOrder__c.Case__c` and
`Flow:c:HarnessAlphaRouter` — four artifacts, one of them a field on a *different* object.

### Verification

| | |
|---|---|
| `pytest tests/test_knowledge_search.py` | 141 passed |
| `pytest tests/` | 903 passed, 1 skipped, **1 failed** |
| `python scripts/validate_harness.py` | **PASS**, 2652 checks; 6 agents / 24 prompts / 25 skills / 3 instruction files — unchanged |

The one failure is `tests/test_salesforce_review.py::PinnedSalesforceMcpCompatibilityTests::test_pinned_server_still_supports_the_bounded_startup_flags`
— it spawns the pinned `@salesforce/mcp` server with `--help` and times out at 30 s. **Confirmed
pre-existing**: it fails identically with both changed files stashed. Unrelated to this work.

### Step 3 — DONE up to the human approval click

Owner connected an org and told me to use the `sf` CLI. D5 is closed.

**The org.** One connected org, alias `devmp` — a **Developer Edition** org, `isSandbox: false`. It
is not one of the configured sandbox aliases and it *cannot* be registered in
`config/harness.local.json`: the schema's `expectedInstanceHost` pattern admits only
`*.sandbox.my.salesforce.com` and `*.scratch.my.salesforce.com`, and this host is
`…develop.my.salesforce.com`. That blocks the org-evidence lanes; it does not block the entry lane,
which reads force-app source, never the org.

**`force-app/main/default/**` is gitignored by design** (`.gitignore:28-30` — only directories and
`.gitkeep` are tracked). That is why it was empty, and why the pilot package is not in git. The
entry lane is unaffected: `sourceTreeDigest` digests analysed content, not a commit.

Retrieved with one targeted `sf project retrieve start`: 10 custom objects, 17 Apex classes, 2
Flows, 2 FlexiPages, 1 LWC, 1 Visualforce page, 2 validation rules — **104 files, 83 components**.
Also deleted the stray empty `* 2` Finder-duplicate directories.

| Step | Result |
|---|---|
| `force_app_knowledge.py inventory` | `clean: true`, 83 components, `status: complete` |
| `entry-coverage` | 80 profiled artifacts with no entry; `ApexPage` and `FlexiPage` unprofiled |
| `entry-draft` ×80 | 79 succeeded, **1 crashed** — see the collector defect below |
| `entry-describe` ×80 | **80/80**, zero failures, zero sentinels (12-agent workflow) |
| `entry-check` | PASS, 80 entries |
| `knowledge_search.py build` | 80 projections |
| `feature-propose` + `feature-describe` | `Feature:service-delivery` drafted and described |
| `feature-check` | PASS |
| `entry-review` ×4 + `feature-review` | 5 digest-pinned approval commands, `output/knowledge-approvals/APPROVE-2026-07-27.md` |

`entry-review` over all 80 at once returns `CHUNK_TOO_LARGE`: prose changes are capped at 25 per
chunk (`PROSE_CHUNK_LIMIT`, contract §6.4.4), because a human is meant to actually read them. Split
into 4 chunks of 20.

### D6 — NEW collector defect, found by real data and fixed

`entry-draft` for `Flow:c:BS_Service_Request_Status_Controller` raised
`TypeError: sequence item 0: expected str instance, dict found` — an unhandled crash, so the entry
could not be drafted at all.

`knowledge_store.py:598` did `" -> ".join(p)` over `errorCatalog[].paths`, assuming a list of
strings. The collector emits `paths` as a list of **paths**, each a list of hop **objects**
(`{decision, outcome?, outcomeLabel?, conditions?, default?}`, `force_app_knowledge.py:960-966`).
Every fixture Flow puts its custom error on the trigger path with no decision above it, which is why
80 real components found this and the pilot did not.

Fixed with `render_decision_path` (`knowledge_store.py`, +36): a hop renders as its decision name
qualified by the branch that reaches it — `Validate_Service_Request_Status_Change [default]` — and
an unrecognised hop shape degrades to the decision name rather than raising, because losing a whole
entry to gain punctuation is the wrong trade. Two regression tests in `tests/test_knowledge_store.py`
(+50).

### D2 follow-up — the disclosure did not reach the reader

`compute_membership` honoured hubs after the first fix, but `run_tree` did not pass the new `hubs`
key through, so the fix was invisible where anyone would look. Added to `run_tree`'s result and to
its `gaps`, and it immediately earned its place on real data:

> 4 declared hub(s) stopped no hop on this walk (Account, Contact, ProductCategory, User). A hub
> only fires where the traversal would otherwise expand through it, so an idle hub is a rule element
> carrying no weight — not evidence that it is holding the boundary in.

That is the reverse-only traversal showing through: the walk never reaches those objects, so the
hubs are stated intent rather than an active constraint. Before this session they were inert *and*
silent.

Editing `knowledge_search.py` correctly invalidated the search index (`corpus_fingerprint` binds the
analyzer version) — `build --full` was required. That is the mechanism working.

### What the real data showed about the feature itself

- **`Service_Request__c` and `Ticket__c` are not connected.** No field on either points at the
  other, and no automation spans them. They are two disconnected clusters united only by the claim
  that both are service-desk intake — a business judgement the source cannot support. The
  description says so in an all-caps paragraph and names splitting the feature as the reviewer's
  decision.
- **A naming trap:** `Ticket__c.Category__c` is a lookup to the **standard `ProductCategory`**, while
  the custom `Category__c` object is unrelated and points the other way, at `Ticket__c`.
- **A defect in the org's own Flow**, surfaced by a description that refused to overstate:
  *"Every rule also requires a prior status value, and no listed outcome can therefore match an
  insert even though the flow is registered for creates as well as updates."* The flow is also
  marked Obsolete, so nothing in source currently constrains status movement at all.

### Verification after all of it

| | |
|---|---|
| `pytest tests/test_knowledge_search.py tests/test_knowledge_store.py` | 471 passed, 1 skipped |
| `python scripts/validate_harness.py` | **PASS**, 3138 checks; inventory unchanged |

### What is left for the human

Read each review artifact and run its pinned command — 4 entry chunks and 1 feature. Nothing is
approved; no agent can approve. Sheet: `output/knowledge-approvals/APPROVE-2026-07-27.md`.

### Step 3 — original blocker, now closed

Blocked by D5, and the blocker is not fixable from here. `docs/workspace-topology.md:11-13, 29, 48-49`
confirms this repository **is** the SFDX root and `force-app/` here is where real metadata belongs —
it is simply empty. Running one feature end to end needs two human actions:

1. Replace the `<MY_DOMAIN>` / `<*_ORGANIZATION_ID>` / ADO placeholders in
   `config/harness.local.json` with the real sandbox details.
2. `sf project retrieve` the metadata for the feature to be documented — a human-approved retrieve,
   per the workspace's own policy.

Neither can be invented: authenticating to the sandbox and choosing what to retrieve are the
owner's, and fabricating an org id would be worse than stopping.

## 9. What the first real store revealed — improvement register

Produced by probing the live 80-entry store (4 parallel probes + synthesis, ~35 real consultant
questions). Everything below was **observed**, not predicted. The four items marked ✔ were
re-verified by hand in the same session.

### Blocking — both change a digest, so they are cheap today and expensive after the first approval

**B1 ✔ `traverse()` cannot cross an object boundary, so no non-anchor object can ever be a feature
member.** Measured on the real boundary: `Service_Task__c`, `Time_Log__c`, `Ticket_Comment__c` and
`Category__c` are absent from membership while *their own fields* are members.

Depth is not the cause and cannot be the cure — measured directly:

| direction | depth 1 | depth 2 | depth 3 |
|---|---|---|---|
| `incoming` (2 anchors) | 27 members, objects = the 2 anchors | 27, identical | 27, identical |
| `incoming` (1 anchor) | 14 | — | 14, identical |
| `outgoing` (1 anchor) | **1** (itself) | — | **1** |

The graph is right; the walk is wrong. `CustomField:c:Service_Task__c.Service_Request__c` carries
`relationship → Service_Request__c` *and* `belongs-to → Service_Task__c`. Under `direction:
incoming` the walk reaches the field, then looks for edges pointing *at* the field — the owner sits
behind the field's **outgoing** containment edge and is never followed. All 10 CustomObject
projections have `edges == []`, which is why `outgoing` returns the anchor alone.

Consequence: **`depth` and `hubs` are both decorative on real data.** Of the six elements a reviewer
approves in a boundary rule — anchors, depth, hubs, include, exclude, assuranceFloor — only anchors,
include, exclude and the floor do anything. The inversion already exists twice elsewhere
(`run_explain` at `knowledge_search.py:1732`, `run_context` at `:2131`), just not in the shared BFS.

Fix: in `traverse()` (`:1776`), on the incoming branch also follow the reached node's own
`belongs-to` edge outward and admit the owner at the same hop with a distinct reason. Then correct
the two places that assert behaviour which never existed: the `boundary.description` in
`schemas/knowledge-feature-entry.schema.json` and the caption at `knowledge_search.py:2790`. **L.**

**B2 ✔ A lane-filtered miss is reported as "No lexical match".** `search --text mpsaCard` — the
exact API name of an indexed entry — returns `approvedResults: []`, `excludedCounts: {lifecycle:
80}` and the gap *"No lexical match; try --state draft…"*. It matched, then was lane-excluded. With
`--state draft` it is rank 1.

Worse, `draftCandidates` is `sorted(lane_ids(['draft']))[:10]` (`:1376`) — a fixed alphabetical
prefix, **byte-identical for `mpsaCard` and for `zzzz xyzzy nonsense`**, presented where results go.
On a store where nothing is approved this is 100 % of first contact.

Fix is already in scope: `:1204-1212` computes `token_ids` before `candidate_ids &= token_ids`, so
"matched then lane-excluded" is provable. Emit that instead, and rank `draftCandidates` by the
query. **S.**

### Fix next

**F1 ✔ Hyphen is not a token separator.** `semicolon` → NO_MATCH, `delimited` → NO_MATCH,
`semicolon-delimited` → OK, against an indexed description reading *"Semicolon-delimited list of
trigger handler names to bypass."* The two phrasings can also give opposite answers: `record level
error` returns the logging framework, `record-level` returns the flow that actually raises one.
`text_analysis.py:25` omits `-` from `SEPARATORS` and `:69` splits on `[_\s]+` only. Keep the
compound as a symbol **and** additionally split it; bump `ANALYZER_VERSION`. Salesforce prose is
saturated with these (master-detail, before-save, roll-up, read-only). **S.**

**F2 ✔ Function words score and the verdict is still OK.** *"what is the escalation process"* →
`outcome: OK`, top hit `Ticket_Comment__c.Author__c`, `matchedOn: [('purpose','the'),
('purpose','is'), ('purpose','process')]`. Bare `escalation` → NO_MATCH; the word appears nowhere in
the store. A store whose pitch is honest absence is manufacturing relevance out of *the* and *is*.
Emit `queryTerms` with document frequencies (already computed at `:1204`) and return NO_MATCH when
no discriminating term matched. Corpus-derived, not a hardcoded stopword list. **M.**

**F3 No retrieval surface returns a line of the prose it indexes.** `project_entry()` already stores
the full text as `purpose` (`:437`) and `load_many` has it in memory before `hit_of` runs, yet
`explain` never returns it and a search row gives isolated words. Retrieval is a file locator, not
an answering system — every ranking error costs a file open. Add a `snippet` to `hit_of()` (`:1079`)
with an explicit `snippetBasis: "purpose, not approved text"`. **M.**

**F4 `feature-dossier` without `--state` silently overwrites the good dossier** with a lane-emptied
2-member one at the same fixed path. Anchors survive because `offer()` bypasses `allowed`, so the
file looks like a small feature rather than a broken one. `traverse()` computes
`excluded["lifecycle"]` and `compute_membership` throws it away. Plumb it through, and either put
the lane in the filename or refuse to overwrite. **M.**

### Build next

- **`limitations[]` has no write path.** Required, digest-bound, printed to the approver, read by six
  projection sites — and **empty on all 80 entries**, because no subcommand can set it
  (`entry-draft` hardcodes `[]` at `knowledge_store.py:828`). Meanwhile 26 of 80 entries carry an
  explicit source-limit caveat *in prose*. Add repeatable `--limitation` to `entry-describe`, which
  already has the right invalidation semantics. **M.**
- **No "is any of this citable yet" command.** `entry-check` returns PASS over a store where nothing
  is approved; `force_app_knowledge.py coverage` reports **0 % documented on 80 entries** and the
  dashboard's "Document next" tells you to redo 25 finished ones — because `coverage()` reads
  `.ai/knowledge/claims`, which is empty by construction on an entry store. **M.**
- **36 % of edges are unresolved (59 of 164) and nothing reports it.** 21 are recoverable at index
  time — `Logger --object-token--> Level__c` vs the real `CustomField:c:LogEntry__c.Level__c`.
  `relation-health` says `orphanedCount: 0`. **M.**
- **Runtime status never reaches a row.** `impact` on `Service_Request__c.Status__c` returns one
  node: the flow that is marked **Obsolete**. The correct answer to "what breaks if I change this"
  is *nothing*. `flow.status` is on the projection; `traverse()` just does not carry it. **S.**
- **`assurance.typeFacts` is not a facet**, so "which entries are heuristic, i.e. ungroundable"
  cannot be asked. Two lines in `project_entry()`. **S.**

### Works well — do not touch

- The **prose corpus itself.** All four probes independently said it is the good part.
- The **exclusion/gap vocabulary** — `excludedCounts`, `suggestedRelaxations`, `truncation_gaps()`,
  `verify_anchor()`, *"That is absence of an ENTRY, not absence of the artifact."* Copy this pattern
  into every fix above.
- **`hydrate()`** (`:1101`): whole-file digest check on every served hit, after ranking.
- **The assurance floor and its below-floor disclosure.** `belowFloor: {count: 0}` here is correct —
  the boundary's defect is purely under-inclusion. Do not loosen the floor while fixing B1.
- **`build_relation_index()` resolving through real `referenceTo`**: it correctly resolved
  `Ticket__c.Category__c → ProductCategory`, kept the custom `Category__c` separate, and left
  `Service_Request__c` / `Ticket__c` unlinked. Name-matching would have invented a relationship.
- **The `--facet` path.** `object.sharingModel=ControlledByParent` returned exactly the three
  master-detail children — complete and correct, on a question the text path gets wrong.
- **`feature-drift` / `feature-status` refusing to synthesize a baseline.**

### Do not bother

- **Embedding / semantic retrieval.** Every observed failure is a lexical-layer defect with an S or M
  fix. Embeddings over 80 documents would mask them and make honest-absence harder to keep.
- **Porter stemming.** It shreds the `__c` / `__mdt` handling `analyze()` exists to protect; the
  hyphen fix buys most of the recall.
- **Teaching `force_app_knowledge.py coverage` to count entries** — it derives from a claims
  worklist. Make it refuse and point at a new entry-readiness command instead.
- **Patching the extractor for `null__NotFound`** — it is genuinely in the org's source
  (`flows/Ticket_Update.flow-meta.xml:78`); Salesforce writes that when a referenced field is
  deleted. The extractor is faithful. The missing thing is the unresolved-edge report.
- **Deleting the four "idle" hubs.** They are inert only because of B1; after that fix they become
  the load-bearing part of the rule. The gap text needs correcting, not the boundary.

## 10. Execution round 2 — the recommended path, run

Six commits on `knowledge-relations-p0-p6`. Every regression test was confirmed failing against the
previous code before the fix landed.

| Commit | What |
|---|---|
| `d0b09c1` | D1, D2, D6 + 5 tests |
| `519c196` | the 80-entry store, 1 feature, session records moved out of gitignored `output/` |
| `0b41706` | **B1** — an object can join a boundary through its own field |
| `3212c1b` | **B2 + hyphens** — stop reporting a lane-filtered match as an absence |
| `806e6cb` | `limitations` write path |
| `f749626` | 90 limitations populated across 69 entries |

### B1 — the measured before and after

| | depth 1 | depth 2 | depth 3 |
|---|---|---|---|
| before | 27 members, 2 objects | 27, identical | 27, identical |
| after | 27 members, 2 objects | 31, **6 objects** | 46, 6 objects |

Depth is a real ladder again: anchors and their parts → the related objects → those objects' own
fields. The owner-ward step carries `ownerWard: True` and the membership reason is
`contains-member`, because labelling it `belongs-to` would tell a reviewer that `Service_Task__c`
belongs to `Service_Request__c` — the relationship inverted.

### B2 and hyphens — verified on the real store

`search --text mpsaCard` used to return nothing and say *"No lexical match"* about an entry sitting
in the index. It now reports *"1 entr(ies) matched this query lexically and were then excluded"*,
offers `mpsaCard` itself as the draft candidate, and labels the list `draftCandidatesBasis:
query-ranked`. Gibberish returns an empty list and the honest no-match gap.

`semicolon`, `delimited` and `semicolon-delimited` all now reach the same entry. `ANALYZER_VERSION`
1.0.0 → 1.1.0 forces the rebuild.

### `limitations` — 90 across 69 entries, prose untouched

Every one lifted from a sentence a describer had already written; none invented. The 11 entries
whose prose names no boundary of the source were left empty deliberately. **The prose is
byte-identical across all 69 rewritten files** — `semanticsDigest` was recomputed and compared per
file against `HEAD`.

Done before first approval by design: `limitations` is inside `factsDigest`, so adding it afterwards
would have invalidated 69 approvals and cost a second full reading pass.

### The feature split — decided by arithmetic

| boundary | depth 2 | depth 3 |
|---|---|---|
| `Service_Request__c` alone | 16 | 26 |
| `Ticket__c` alone | 15 | 20 |
| both anchors together | **31** | **46** |

16 + 15 = 31 and 26 + 20 = 46: **zero shared members.** The single `service-delivery` draft was a
union of two disjoint clusters, not a boundary. Replaced by:

- **`Feature:service-request`** — `Service_Request__c` + `Service_Task__c` + `Time_Log__c`, 26 members
- **`Feature:ticketing`** — `Ticket__c` + `Ticket_Comment__c` + `Category__c`, 20 members

Both at depth 3, `source-exact` floor, hubs declared. The draft was removed rather than repurposed:
`feature-revoke` refused it (*"nothing to revoke"* — no approval to revoke), the features ledger had
zero records, so nothing dangled. Both descriptions state the zero-overlap measurement and say that
merging them is a deliberate decision, not a default.

Declared hubs still fire on nothing in this package, and `run_tree` says so. That is correct: a hub
stops a walk that would otherwise expand through it, and no standard object here carries a field
pointing at an anchor.

### D3 — closed (`2b31a4a`), because it landed on the signature page

`feature-propose` stripped whitespace and wrote; nothing verified an anchor, hub, include or
exclude existed. The two features declare five hub names between them and the review artifact
printed them with nothing to say whether any was real.

Worse, the idle-hub gap added earlier the same day made it *ambiguous* rather than merely
unchecked — *"3 declared hub(s) stopped no hop"* reads identically for a correct hub the walk never
reached, a standard object with no entry, and a misspelling. That gap was mine and needed splitting.

`resolve_boundary_names` classifies each name against force-app source and returns near matches:

| name | status | closest |
|---|---|---|
| `Service_Request__c` | `in-source` | — |
| `Account` | `not-in-workspace` | — (ordinary for a standard object) |
| `Servce_Request__c` | `not-in-workspace` | `Service_Request__c` ← **the typo signal** |

Three surfaces, two bases, each named: `feature-propose` returns `nameResolution`;
`feature-review` renders a `name check` line, worth the 0.15 s source parse once at signing time;
`run_tree` splits its hub gap using the **already-loaded index**, because `inventory()` re-parses
the source tree on every call and `tree` is not a full-corpus question.

Advisory throughout. A hard gate would reject an anchor whose `object-meta.xml` is absent from a
fixture and would couple a pure file write to git — the failure `entry-coverage` deliberately
soft-handles.

### Left for the human

Read each review artifact, run its pinned command: **4 entry chunks + 2 features**.
Sheet: `output/knowledge-approvals/APPROVE-2026-07-28.md`. Regenerated twice — every digest moved
when limitations landed, and the feature reviews changed again when the name check arrived, so any
command captured earlier is stale.

### Not done, deliberately

F2 (function words scoring, verdict still OK), F3 (no snippet in any retrieval surface), F4
(`feature-dossier` overwriting without `--state`), the unresolved-edge report, `entry-readiness`,
runtime status on rows, `assurance.typeFacts` as a facet. All real, none blocking approval, none
carrying a digest deadline. They sit in §9 for after the first approval.

## 11. Standing blockers

| | |
|---|---|
| ~~**D4**~~ | **Closed** — see §8. |
| **D5** | `force-app` is empty — no end-to-end run is possible until metadata is retrieved. Needs the org placeholders filled in and a human-approved `sf project retrieve`. |
| **Charter** | `.github/agents/knowledge-curator.agent.md` says *"from repository source alone"* and *"a description you cannot ground in source — pause and report, never improvise"* in four places. **A compliant curator must refuse authored-prose work.** Any P1/P5 work needs this charter amended first — it is a charter change, not bookkeeping. |
