# Evidence analysis — discovery & planning review of `docs/evidence-to-analyse.md`

## Document status

- **Purpose:** independent architect review of `docs/evidence-to-analyse.md` (5,924 lines):
  verify its evidence against the actual repository, analyse each proposal by priority, and
  record pros/cons and an implement / don't-implement decision per item.
- **Character:** discovery + planning artifact. This is **not** an implementation authorization,
  not a policy change, and not a work record. Every "IMPLEMENT" verdict below means
  "worth implementing, subject to the listed gates" — not "start now".
- **Snapshot date:** 2026-07-24, commit `16b23f6`, branch `main`.
- **Method:** full read of the evidence document, followed by five parallel read-only
  verification sweeps against the repository (role guard & validator; prompt/skill/agent
  surface; work-record state machine & handoffs; Knowledge engine internals; release/evals/CI).
- **Verdict vocabulary:**
  - `IMPLEMENT` — evidence confirmed, benefit clear, risk bounded; plan it.
  - `IMPLEMENT WITH CHANGES` — direction right, but the proposed shape needs modification.
  - `SPLIT` — part worth doing now, part gated.
  - `DEFER` — do not plan yet; explicit prerequisite missing.
  - `DECISION REQUIRED` — cannot be resolved by an agent; owner must choose.
  - `REJECT` — do not implement as proposed.

---

## 1. Executive summary of decisions

| # | Topic (evidence-doc ID) | Verdict | One-line rationale |
|---|---|---|---|
| 1 | T11 Release handover corrections (§28) | **IMPLEMENT** | Small, verified, no permission change; wiki-fallback removal and template-only rendering are real behavioral fixes. |
| 2 | §30 Fixture leak (`Invoice__c` / `MP-INV-` denylist) | **IMPLEMENT (P1 gate)** | Confirmed portability defect in runtime validation; must be fixed before any new Knowledge model is built on top of it. |
| 3 | T07 One-file Knowledge model (§24) | **DECISION REQUIRED → conditional design-only GO** | Third Knowledge architecture in 48 h with zero real data; conflicts with the same-day "stay on v1, pilot first" decision. Design + adversarial review only; no storage code before an explicit owner supersession or pilot data. |
| 4 | T08 Knowledge Search (§25) | **SPLIT** | Storage-agnostic fixes (tokenizer, query cost, result transparency) are worth doing on v1 now; the full typed-query/index engine is gated on the T07 contract freeze. |
| 5 | T04 Work records, handoffs, approval (F-04…F-09, F-11) | **IMPLEMENT** | All contradictions confirmed in code; fixes are contract/UX-level with no permission expansion; highest correctness value per unit of effort. |
| 6 | T01 Broad agent, narrow executor (§2, F-01) | **IMPLEMENT WITH CHANGES** | Diagnosis confirmed; but the "broad sandboxed terminal" precondition does not exist on the Windows/VS Code host. Middle path: policy-checked Git dev-loop classes inside the existing guard, shadow mode first. |
| 7 | T02 Prompt & skill architecture (F-02, F-06, F-07, F-10…F-16) | **IMPLEMENT** | Confirmed drift and duplication; mostly mechanical contract alignment + CI checks. Coordinate with the already-approved test-case-creator removals to avoid double count churn. |
| 8 | T03 Complete SDLC stage UX (F-03, §6) | **SPLIT** | `/sdlc-develop`, QA entry, and formal review entry: implement. Navigator: defer (optional by the doc's own acceptance criteria). Mass renaming to `/sdlc-*`: not recommended. |
| 9 | T05 Evals & real pilot (F-17, F-20) | **IMPLEMENT (cross-cutting, pull earlier)** | Confirmed: no executed behavioral evals, no pilot data. This is the single highest-leverage item — it gates T01 enforcement and unblocks the T07 decision. |
| 10 | T10 Minimal clean-Salesforce baseline (§27) | **IMPLEMENT** | Small, anti-bloat by design; the §27.2 materialization filter is the most valuable part. |
| 11 | T09 Package constraint register (§26) | **IMPLEMENT (contract only)** | Schema + empty registry + validation; values stay owner-supplied. No enforcement until populated. |
| 12 | T06 Managed-package release lifecycle (F-18, §7.2–7.3) | **DEFER** | Confirmed absent, design direction sound, but hard-blocked by the F-19 operating-mode decision and by SDLC/eval stability. |
| 13 | F-19 Operating mode (closed-extension vs owned 2GP) | **DECISION REQUIRED** | Genuinely blocking for T06; current scaffold (empty namespace, validator-enforced) matches `closed-package-extension`. Recommend confirming that as the v1 profile. |

Recommended wave order (adjusted from the doc's §29.2 — changes in bold):

```text
Wave 0 — quick wins:            T11  +  §30 fixture-leak fix  +  F-16 generated inventory counts
Wave 1 — workflow correctness:  T04  (state machine, handoff UX, mode matrix, contract fixes)
Wave 2 — v1-safe search fixes:  T08a (tokenizer, query cost, result transparency — storage-agnostic)
Wave 3 — autonomy middle path:  T01  (Git dev-loop classes, shadow mode)  +  T05 eval harness
Wave 4 — surface architecture:  T02  +  T03 (missing stage entries; no Navigator yet)
Wave 5 — Knowledge model:       T07 design freeze + adversarial review → pilot → then T08b engine
Wave 6 — policy scaffolds:      T10  +  T09
Wave 7 — release lifecycle:     T06  (only after F-19 decision + Wave 3 evidence)
```

The main deviation from the evidence doc: **T07/T08 (owner priorities 2–3) are moved after
workflow correctness and the pilot**, because the standing owner decision of the same day
("v2 shelved — current may be fine, it needs testing") and the absence of any real dataset
(F-20, confirmed) make a third storage redesign the riskiest place to start. See §4.

---

## 2. Evidence verification result

The document's OBSERVATIONs are **overwhelmingly accurate**. Every file:line citation checked
resolved to the claimed content. Confirmed highlights:

- Role guard is a closed read-only command allowlist (`scripts/copilot_role_guard.py:722-857`);
  `git commit`/branch-create/push/`curl`/`python -c` are test-pinned as denied
  (`tests/test_safety_hooks.py:658-683`); the guard itself documents prior agent flailing
  (`copilot_role_guard.py:55-58`).
- 18/23 prompts declare frontmatter `tools:`; the 5 exceptions match the doc's list exactly.
- No `development/in_progress → qa/in_progress` transition exists
  (`scripts/work_record.py:101-130`), and the `review/needs_fixes → development → review`
  fix loop bypasses QA.
- All three record-requirement contradictions (Solution Designer, Config Investigator,
  Test Strategist) are real, as are the `/investigate-object`, `/check-against-principles`,
  and `/propose-force-app-knowledge` prompt-vs-skill contract conflicts.
- The Knowledge query path is as expensive as claimed: flat `glob("*.yaml")`, full
  `validate_all()` per query, per-candidate `reconcile()` re-scans, per-query BM25 corpus
  rebuild, `claims-index.json` generated but never read by the engine
  (`scripts/knowledge_registry.py:357, 759-769, 845-847, 1050, 2184`).
- The tokenizer keeps only `[a-z0-9]`, so Polish text and `Object__c.Field__c` symbols are
  shredded (`knowledge_registry.py:1003-1007`).
- `errorCatalog` mixes `custom-error`, `screen-validation`, `fault-path`
  (`force_app_knowledge.py:1052-1090`); only Flow, ValidationRule, DuplicateRule emit it.
- `validate_harness.py:835-845` denylists the literal strings `Invoice__c` / `MP-INV-` across
  `.github`, `.ai`, `config`, `schemas`, `scripts`; `tests/test_knowledge_contract.py:196-200`
  pins the same; both introduced together in commit `07c1788`.
- No release record, release schema, package executor, or Package Release Manager exists
  anywhere; `sfdx-project.json` has an empty namespace enforced by the validator.
- `evals/agent-scenarios.yaml` is explicitly manual; `run_evals.py` executes only
  `safety-scenarios.yaml` (deterministic hook decisions), no behavioral agent flows.
- Stale counts in `README.md`, `SETUP.md`, `.ai/repo-map.md` confirmed (5/20/22 vs actual 6/23/24).

### Corrections and nuances the evidence doc missed

These change fix shape or severity, not direction:

1. **F-05 is a UX gap, not a state-machine gap.** `work_record.py:2165-2166` already permits
   handoffs to Test Strategist from design/development/qa. Only the agents' `handoffs:`
   frontmatter fails to advertise it. Fix is a few frontmatter lines, not workflow code.
2. **F-10 was a deliberate permission lift.** The role guard intentionally grants Knowledge
   Curator parity for repo-source commands (`copilot_role_guard.py:147-218`); only the three
   skills' text was never updated. Fix = skill `allowedRoles` text, trivial.
3. **§28's extra sections are not in the template.** `.ai/templates/release-handover.md`
   contains no `Generation Metadata` / `Warnings` / `Release Scope Overview` — those were
   agent-added beyond the template at generation time. The fix is a template-only rendering
   contract in the prompt/skill (the skill is actually named `generate-release-handover`,
   not `release-handover` — the correction must target the right file).
4. **§28's wiki concern is real:** the current skill explicitly instructs a `search_wiki`
   fallback via the search-ado skill when no attached link exists; removing that fallback is
   a genuine behavioral change, correctly scoped.
5. **F-02's worst example is weaker than stated.** `/document-metadata-change` omits the
   `agent` tool, but its skill's Config-Investigator consultation is written as a role-bound
   consult, not an `agent` tool call, so the practical breakage is smaller. The general
   prompt-tools-override risk stands.
6. **The proposed lifecycle partially exists already.** `intake/draft` is implemented
   (`work_record.py:58-79`); §7.1's target machine is an extension, not a rebuild.
7. **F-14/feature-documentor:** `feature-crawl`/`feature-draft` are indeed absent from the
   role guard (the public prompt cannot execute its own core procedure), though no literal
   "human-terminal-only" marking exists in code.
8. **Fixture volume:** ~198 occurrences of `Engagement__c` and ~11 of `Invoice__c` in
   `tests/` — the §30 neutralization is a sizeable but mechanical test refactor.

---

## 3. Standing constraints the evidence doc under-weights

These come from decisions already recorded in this workspace and materially affect verdicts:

- **C-A — "v2 shelved, stay on v1, pilot first" (owner, 2026-07-24).** After the facts+overlay
  design was completed, the owner decided *not* to implement it: "current may be fine, it
  needs testing." §24's one-file model is a *third* architecture direction recorded the same
  day. Both cannot be the operative decision simultaneously.
- **C-B — the claims lifecycle is not dormant.** `investigate-config-records`,
  `investigate-object`, and feature-coverage consumers actively use registry org-observation
  claims. Any storage change must keep the evidence-ledger path working (the doc's §18.1
  FAIL-7 acknowledges this; §24 must inherit it too).
- **C-C — the work-record SAFE gate hard-requires `claimRef`s.** If repository knowledge moves
  out of the claims registry, `work_record.py` grounding checks and `SAFE-CLAIM-001`
  (Tier 1) must be formally changed — an owner-reviewed safety change, exactly as §16.10 says.
- **C-D — no SQL databases** (standing owner constraint). All §25 index designs comply
  (files-only JSON); any future deviation needs a new decision.
- **C-E — Windows-only team, no host sandbox.** The VS Code Copilot host provides no
  filesystem/network/secret isolation for a "broad sandboxed terminal". The evidence doc's own
  §2.6 caveat ("if the host does not provide sandboxing, keep guarded executors") is the
  *actual operating condition*, not an edge case.
- **C-F — test-case ranking ecosystem already slated for removal** (separate discovery,
  2026-07-24): `suggest-test-cases`, `sync-test-cases`, `tune-test-case-keywords` prompts+skills
  are to be replaced by `create-test-cases`. This shrinks the public surface 23→21 prompts /
  24→22 skills independently of T02, resolves three of the F-06(c) standalone-prompt
  contradictions by deletion, and means any count-pinning work should be batched with it.

---

## 4. Per-topic analysis (owner priority order)

### 4.1. T11 — Release handover corrections (§28) — **IMPLEMENT**

**What it is.** Keep `/release-handover` as an independent, cyclic ADO-driven report generator;
correct three behaviors: (1) wiki content only from links explicitly attached to the Work Item
(no `search_wiki` fallback), (2) list all linked Test Cases regardless of execution status,
(3) render strictly and only the sections of `.ai/templates/release-handover.md`, which becomes
the single manually-editable source of truth; forbid agent-added sections.

**Verification.** Template exists with Header / Handover description / ToC / per-item
Summary + Technical table + Tests sections and none of the offending extras; the skill
(`generate-release-handover`) currently *does* instruct the `search_wiki` fallback; no current
execution-status filtering mandate was found (so (2) is mostly codification).

**Pros.** Smallest scoped item on the list; no permission, state-machine, or schema changes;
removes a real wrong-document risk (wrong wiki page silently attached); template-only rendering
eliminates prompt/template drift by construction; aligns with the layer-responsibility
principle (§6.1) without waiting for T02.

**Cons / risks.** Minor: removing the wiki fallback reduces recall when teams forget to attach
links — but that is precisely the intended signal ("no published documentation"). Template
enforcement is prompt-level (not machine-checked) unless a small render-check is added.

**Decision.** IMPLEMENT as Wave 0. Scope: edit `.github/prompts/release-handover.prompt.md` +
`.github/skills/generate-release-handover/SKILL.md` only; template untouched; consider one CI
assertion that the skill contains no section list of its own (drift guard). Effort: S.

---

### 4.2. §30 — Business-object names leaked into runtime authority — **IMPLEMENT (P1, gate for T07/T08)**

**What it is.** Replace the literal `Invoice__c` / `MP-INV-` denylist in `validate_harness.py`
and `test_knowledge_contract.py` with structural/provenance-based checks; neutralize and
diversify business-shaped fixtures (`Engagement__c` family); prove via regression test that a
legitimate object named `Invoice__c` can pass the full Knowledge lifecycle.

**Verification.** Fully confirmed, including the introducing commit `07c1788`. The concern's
two-level split is accurate: no active auto-targeting logic exists, but the negative hardcode
is enforced by both CI and first-launch validation — a real harness-portability defect, not
cosmetics.

**Pros.** Removes a false global contract before it gets baked into any new Knowledge model;
makes the harness actually reusable by other teams; the fix direction (provenance checks over
name denylists) also generalizes to future fixture hygiene; mechanical, testable.

**Cons / risks.** ~200 fixture occurrences to touch — noisy diff; must not weaken the original
intent (preventing demo content from becoming package facts), so the structural replacement
check has to land in the same change, not later. Root-cause discovery of `07c1788` (per §30.5)
should stay time-boxed — the history interpretation in the doc is already plausible.

**Decision.** IMPLEMENT as Wave 0/P1 and treat as an entry condition for T07/T08, exactly as
the doc recommends. Effort: M (mostly tests).

---

### 4.3. T07 — One-file Knowledge model (§24) — **DECISION REQUIRED → conditional design-only GO**

**What it is.** One type-aware Knowledge Entry file per logical Salesforce artifact, shared by
agent and human; agent drafts, user consciously invokes `/approve-drafts-knowledge`, approval
is digest-bound; versioned metadata-type profiles; Flow entries persist only source-declared
intentional Custom Errors.

**Verification.** The supporting evidence is solid: the v1 engine's cost profile is confirmed
(§2 above), the store is empty (no migration debt), a `knowledge-entry.md` template already
exists in `.ai/templates/`, and the collector already extracts most of the Flow pilot slice
(FlowCustomError, `$Label` resolution, decision guards). The *measured* scale numbers
(30–40k YAML, ~1,200 clicks) are recorded design evidence, not re-measured — the doc itself
says so.

**Pros.**
- Removes per-record human approval from mechanical extraction — the single biggest measured
  governance cost.
- One readable file per component is a genuinely better human and agent UX than
  claim/evidence/review triples; the empty store makes now the cheapest possible moment.
- The §24 model already internalizes the failure analysis of variant B (no separate overlay
  lifecycle, digest-bound approval, no timestamps/self-commit).
- Intentional-errors-only scoping for Flow is a wise, owner-confirmed narrowing.

**Cons / risks.**
- **Architecture churn:** this is the third Knowledge architecture direction within two days
  (v1 → facts+overlay → one-file), with zero real-world data behind any of them (F-20
  confirmed). The same-day standing decision C-A explicitly chose "stay on v1, test first."
- **Mutable-file approval provenance:** a single editable file carrying both generated facts
  and approved semantics re-imports part of variant B's FAIL-4/FAIL-5 (approval status
  adjacent to regenerable content). The digest-binding design mitigates but does not
  eliminate it; this is the weakest point and the first thing an adversarial reviewer should
  attack (§24.10 Q1–Q3 are the right questions).
- **C-C:** the work-record SAFE gate hard-requires `claimRef`s; one-file citations require a
  Tier 1 `SAFE-CLAIM` change plus consumer rewiring (`knowledge-lifecycle`,
  `source-authority`, six consumer skills).
- **C-B:** the evidence ledger for org observations must remain a separate immutable lane —
  the one-file entry cannot absorb org/runtime receipts without recreating the mixed-truth
  problem.
- Collector becomes Trusted Computing Base; schema work (type profiles) is substantial.

**Decision.** DECISION REQUIRED first: the owner must explicitly either (a) supersede the
"stay on v1, pilot first" decision with the one-file direction, or (b) run the pilot on v1
first. **Recommendation: a bounded middle path** — freeze the one-file *contract* (entry
schema, identity, approval digest boundary, Flow+CustomField profiles — §25.16 Phase 0
deliverables), submit it to independent adversarial review, and in parallel run a small
synthetic-fixture pilot; write no storage code (`knowledge_store.py` or equivalent) until
both gates pass. This preserves momentum without a third unvalidated rebuild. §30 fix is a
hard prerequisite. Effort to the gate: M; full implementation: XL.

---

### 4.4. T08 — Knowledge Search (§25) — **SPLIT**

**What it is.** Typed query contract, generated files-only index cache with immutable
generations, BM25F with a Unicode/Salesforce-aware analyzer, bidirectional relation graph,
FlowCustomError-only error search, `knowledge_capabilities` introspection.

**Verification.** Every claimed defect of the current engine is confirmed (see §2). The plan
itself is internally consistent, respects C-D (files-only), and its phase gates are testable.

**Pros.** Two-step retrieval (compact projection → selective hydration) directly addresses
the measured O(N)-per-query cost and agent context waste; explainable matches and abstention
semantics ("no result ≠ proof of absence") are genuine epistemic improvements; the
intentional-error mode cleanly separates from the mixed `errorCatalog`.

**Cons / risks.** The full engine is ~9 phases of work bound to a storage contract (T07) that
is not yet decided — building it now would freeze the wrong data model; relevance/performance
gates (100% Top-1 etc.) are aspirational until a golden set exists; index freshness machinery
(immutable generations, atomic pointer, Windows semantics) is the most defect-prone part.

**Decision.** SPLIT:
- **T08a — implement now, storage-agnostic (Wave 2):** fix the tokenizer (NFKC/casefold,
  preserve full API symbols and `__c/__r/__mdt/__e` suffixes, keep Polish tokens); stop
  running `validate_all()` + per-candidate `reconcile()` inside `query()` (validate once,
  memoize effectiveness); make `query()` report applied filters and non-effective matches
  (the skill already promises both — confirmed prompt/implementation gap); fix the
  `search-knowledge` skill's hardcoded `python` → venv-aware invocation. These survive any
  T07 outcome and pay off immediately.
- **T08b — defer the typed-query engine, index generations, graph modes, and
  intentional-error mode** until the T07 contract freeze; then follow §25.16's phase order,
  which is well-constructed. The §25 golden-query categories should be created *before*
  T08b regardless — they double as v1 regression tests.

---

### 4.5. T04 — Work records, handoffs, approval (F-04, F-05, F-06, F-07, F-08, F-09, F-11) — **IMPLEMENT**

**Verification.** All confirmed; see §2 and nuances 1–2.

**Per-finding decisions:**

| Finding | Decision | Shape |
|---|---|---|
| F-04 no `development → qa` transition | **IMPLEMENT** | Add the transition + downstream-receipt invalidation to `work_record.py` and the contract; add the QA-mandatory-vs-waiver default as an owner decision (recommend: mandatory by default, persisted waiver allowed — matches the doc). |
| F-05 no Test Strategist incoming handoff UX | **IMPLEMENT** | Frontmatter-only: add `test-strategist` handoff entries to solution-designer and development-assistant agents. The state code already allows it. |
| F-06 contradictory record requirements | **IMPLEMENT** | Adopt the three-mode taxonomy (`standalone-read` / `governed-stage` / `admin-maintenance`) as prompt+skill frontmatter; relax the three agents' absolute record language to mode-conditional; add a CI contract test (prompt mode ⊆ agent modes ⊆ skill mode). This is the doc's single best low-cost idea. |
| F-07 `/investigate-object` dual contract | **IMPLEMENT WITH CHANGES** | Prefer one skill with two declared modes over two new skills — smaller surface, same guarantee. Standalone mode must not mutate claims. |
| F-08 advisory check vs formal review | **IMPLEMENT WITH CHANGES** | Two modes of one skill (advisory lint without `SAFE`; formal review requiring record+handoff), not two agents — answers the doc's own reviewer question 6 in the cheaper direction. Formal verdict only via consumed handoff. |
| F-09 adhoc-fix review path | **DECISION REQUIRED** | The express lane was *deliberately* record-less (decision log, 3 CI pins). Recommend the cheap option first: explicit "formal review unavailable in express lane" disclaimer in the output envelope; revisit the lightweight-record option after pilot data shows how often adhoc fixes actually occur. |
| F-11 propose/promotion contradiction | **IMPLEMENT** | Keep the chat-approve promotion (it is the established safety-hook `ask` pattern) and fix the prompt wording to declare it: "requesting approval is part of the workflow; promotion itself is a human chat decision." Removing the capability would regress the working curator flow. |

**Pros.** Removes the direct causes of agent stalls and inconsistent behavior with zero
permission expansion; everything is testable in CI; prerequisites for T01/T02/T03.

**Cons.** `work_record.py` transition changes need careful test updates (the state machine is
contract-pinned); mode taxonomy touches all 23 prompts (batch with C-F removals).

**Decision.** IMPLEMENT as Wave 1. Effort: M.

---

### 4.6. T01 — Broad agent, narrow executor (§2, F-01) — **IMPLEMENT WITH CHANGES**

**Verification.** The allowlist reality, the flailing history, and the test-pinned denials are
all confirmed. The doc's own caveat (§2.6: without host sandboxing, keep guarded executors)
is decisive under C-E.

**Pros of the target principle.** Correct diagnosis: command-shape friction is not a security
control; effect-based policy is more maintainable; three-outcome ALLOW/ASK/DENY with
receipts is a better model than binary allowlists; the doc's risk-class list (§2.3) is a
sound enforcement target.

**Cons / risks of the proposal as written.** The "broad sandboxed terminal" precondition is
unavailable: VS Code Copilot on Windows offers no filesystem/network/secret isolation, so a
generic terminal would inherit credentials and unrestricted egress — the doc itself forbids
that. Full argv-normalization + semantic policy engine is a large build with its own attack
surface; deleting the allowlist wholesale is explicitly (and rightly) warned against.

**Decision.** IMPLEMENT WITH CHANGES — a middle path inside the existing guard, in this order:
1. Extend the guard with **policy-checked Git dev-loop classes** (not raw pass-through):
   branch create/switch on non-protected branches, scoped `add`/`commit` on the current work
   branch, `fetch`, upstream compare. Push stays `ASK`; force-push, `reset --hard`,
   `clean -f`, branch `-D`, push-to-main stay `DENY` (keep the existing test pins, add new
   ones for the allowed classes).
2. Add **denial telemetry** (operation class + reason, no payload) so the next widening round
   is evidence-driven rather than anecdotal.
3. Run **shadow/audit mode** for any reclassification before switching enforcement, per §8
   Phase 2.
4. Revisit the full side-effect-policy model only if/when a sandboxed execution boundary
   exists on the host.
Prerequisites: T04 (a normal Git loop presumes an authorized work branch concept), and the
T05 security evals for each newly allowed class (`EVAL-EXEC-*` list is good as written).
Effort: L.

---

### 4.7. T02 — Prompt & skill architecture (F-02, F-10, F-12…F-16) — **IMPLEMENT**

**Per-finding decisions:**

| Finding | Decision | Shape |
|---|---|---|
| F-02 prompt-level `tools:` overrides | **IMPLEMENT** | Stage prompts drop `tools:` (agent owns the surface); prompt-level `tools:` allowed only as an explicit reduced profile with a frontmatter marker; CI detects unmarked overrides. Add the host-precedence assumption to the compatibility notes (it is documented VS Code behavior but untested cross-version — doc's caveat is fair). |
| F-10 curator/skill role text drift | **IMPLEMENT** | Add `allowedRoles` to the three skills (the guard already grants parity — deliberate lift, confirmed); org-facing steps stay Config-Investigator-only. Trivial. |
| F-12 feature-health "gate" that gates nothing | **IMPLEMENT WITH CHANGES** | Cheapest honest fix: stop calling it a gate in prompt text, OR make design check a receipt/waiver. Recommend the receipt check only if intake (T03) lands; otherwise rename now. |
| F-13 prompt/skill body duplication | **IMPLEMENT** | Already independently confirmed by `audit/findings.md` F-05. Prompt = entry/args/mode/outcome; skill = procedure. Mechanical. |
| F-14 overlapping entries | **IMPLEMENT PARTIALLY** | Fold `/batch-knowledge` and `/refresh-force-app-knowledge` into `/curate-knowledge` aliases with a deprecation note (the doc's §21.7 alias pattern); keep `/relation-health` (distinct report). Fix `/feature-documentor`'s broken procedure (its `feature-crawl`/`feature-draft` commands are absent from the role guard — either allowlist them for the role or mark the prompt human-assisted; confirmed gap). C-F already removes three more overlapping prompts. |
| F-15 input grammar | **IMPLEMENT** | `name=value` + one documented free-text fallback everywhere; fix `docs/setup-zero-to-first-prompt.md:235` (`/fetch-ado-item 12345` vs required `itemId=`) — confirmed. |
| F-16 stale inventory counts | **IMPLEMENT (Wave 0)** | Generate the inventory block (validator already owns `EXPECTED_COUNTS`); README/SETUP/repo-map reference the generated output. Batch with C-F count changes (23/24 → 21/22) to avoid two churn rounds. |

**Pros.** Directly reduces the "two simultaneously true instructions" failure mode; mostly
mechanical; each item independently shippable.

**Cons.** Touches many files at once — needs the CI contract tests *first* so the alignment
can't silently regress (the existing guard↔parser contract test is the model to copy).

**Decision.** IMPLEMENT as Wave 4 (after T04 supplies the mode taxonomy), except F-16 which
is Wave 0. Effort: M.

---

### 4.8. T03 — Complete SDLC stage UX (F-03, §6.2, §6.4) — **SPLIT**

**Verification.** F-03 confirmed: Development Assistant has only `/adhoc-fix` and
`/document-metadata-change`; the normal implementation procedure lives only in agent
instructions. The intake phase already exists in the state machine.

**Decisions:**
- `/sdlc-develop` (or `/develop`) — **IMPLEMENT**. The most-used stage must have a public,
  testable entry with record+handoff gates. Critical severity is justified.
- QA stage entry + Test Strategist incoming handoff — **IMPLEMENT** (with T04's F-04/F-05).
- `/sdlc-review` formal entry — **IMPLEMENT** (with T04's F-08 split; the formal mode of the
  review skill becomes this entry).
- `/sdlc-status` + read-only Navigator — **DEFER**. The doc's own NAV-006 says every stage
  must work without it; therefore it is by definition not on the critical path. Build it only
  after stage entries exist and the pilot shows resume-in-fresh-chat friction. The NAV-001…007
  acceptance criteria are good and should be kept for that moment.
- Renaming the existing surface to a `/sdlc-*` namespace — **REJECT for now**. Adding missing
  entries is additive and safe; renaming working prompts churns challenge tests, docs, and
  user habit for cosmetic gain. Revisit after T02's dedup settles the surface. Prefix
  namespacing for the expert menu (`evidence-*`, `knowledge-*`, …) can ride along with T02
  renames only where a prompt is already being touched.

**Effort:** M (develop/qa/review entries), Navigator excluded.

---

### 4.9. T05 — Evals & real pilot (F-17, F-20) — **IMPLEMENT, pull earlier than the doc's wave 4**

**Verification.** Confirmed: `agent-scenarios.yaml` is manual-only; `run_evals.py` executes
only deterministic safety scenarios; no golden-path behavioral eval; no real pilot data
anywhere (empty store, empty change-records, skeleton force-app).

**Pros.** Every major open decision in this document (T07 supersession, T01 enforcement
switch, T06 start) is blocked on exactly the evidence a pilot + eval harness would produce.
The owner's own stance ("current may be fine, it needs testing") makes this the most
owner-aligned item on the list. The doc's eval catalog (EVAL-STAGE/EXEC/REL) is concrete and
mostly automatable.

**Cons.** Behavioral evals of a VS Code Copilot host are partly manual by nature; the harness
can only pin what is scriptable (hook decisions, contract parity, state transitions) — the
matrix (model × host version) will stay a recorded-manual-run artifact for now, as the doc's
§13.1 admits.

**Decision.** IMPLEMENT incrementally starting Wave 3: (1) synthetic golden-path fixture
(one change record walked Intake→…→Complete via scripted `work_record.py` calls — automatable
today), (2) the EVAL-EXEC security set for every T01 class before its enforcement flips,
(3) one real, non-critical pilot change with the §8 Phase 5 metrics recorded. The pilot
doubles as the v1-Knowledge validation the owner asked for — schedule it *before* the T07
storage decision.

---

### 4.10. T10 — Minimal clean-Salesforce baseline (§27) — **IMPLEMENT**

**Verification.** No conflicting local encyclopedia exists today; `config/` has analyzer and
policy files but no engineering-policy or platform-baseline file; the §27.2 filter matches the
workspace's existing anti-bloat posture.

**Pros.** The materialization filter (§27.2) is the keeper — it prevents the workspace from
accreting Salesforce tutorials; the five-category target (baseline, project decisions,
analyzer policy, typed facts, exceptions) is small and testable; empty-by-default values
respect the reusable-harness principle.

**Cons.** Marginal near-term value while `force-app` is a skeleton; the API-version-sensitive
rules need a maintenance owner or they rot (the `reviewedAt` field mitigates).

**Decision.** IMPLEMENT as Wave 6, effort S–M: add the filter text to contributor docs, one
`project engineering policy` skeleton file, pin the Code Analyzer config posture. No
encyclopedia content.

---

### 4.11. T09 — Package constraint register (§26) — **IMPLEMENT (contract only)**

**Verification.** `config/managed-package-constraints.yaml` does not exist; no package catalog
exists in `config/` (only org aliases + `allowedPackageNamespaces` in review policy).

**Pros.** The namespace-vs-prefix distinction and the four-authority split are correct and
cheap to encode as schema; the "empty arrays are intentional" stance is exactly right for a
reusable harness; having the contract ready unblocks T06 later without inventing values.

**Cons.** Zero runtime value until the organization supplies values; a small risk that an
empty registry gets treated as "no constraints exist" — the `unknownPrefix: review-required`
default handles this and must be preserved.

**Decision.** IMPLEMENT contract-only (schema + empty registry + validator wiring +
`draft`-cannot-authorize semantics) as Wave 6. No enforcement logic beyond schema validation
until values are populated and reviewed. Effort: S.

---

### 4.12. T06 — Managed-package release lifecycle (F-18) + F-19 operating mode — **DEFER + DECISION REQUIRED**

**Verification.** Confirmed absent in full: no release records, schema, executor, or agent;
`/release-handover` is reporting only; empty namespace is validator-enforced, consistent with
a generic harness around a closed vendor package.

**Pros of the proposal.** The separation (change lifecycle ≠ release lifecycle), the separate
release record with exact artifact binding, the REL-001…018 criteria, request-ID idempotency
for builds, and the human-only promotion gate are all sound and should be kept as the design
of record for when this starts. The Dev Hub / `SAFE-ENV-001` tension analysis is accurate and
must not be shortcut by allowlisting a production alias.

**Cons / blockers.** F-19 is a genuine decision blocker: `closed-package-extension` vs
`owned-managed-2gp` changes the entire control plane (namespace, Dev Hub, executor scope).
The current scaffold *is* the closed-extension profile. Building release machinery before the
SDLC stages, evals, and pilot exist would automate an unvalidated process.

**Decision.**
- **F-19: DECISION REQUIRED (owner).** Recommendation: confirm `closed-package-extension` as
  the explicit v1 operating mode (matches everything currently enforced), record it in config
  and contracts, and treat `owned-managed-2gp` as a future second profile with its own
  contracts — option 3 of the doc, sequenced.
- **T06: DEFER** to Wave 7, gated on F-19 + Wave 3 eval evidence + T04/T03 stability. When it
  starts, follow §7.2–7.3 as written; keep `/release-handover` out of it (per §28/§29 the
  handover stays an independent report).

---

## 5. What this analysis explicitly recommends *against*

1. **Do not start Knowledge storage implementation** (one-file store, `knowledge_store.py`,
   or index engine) before the §30 fix, the owner's explicit supersession of the
   stay-on-v1 decision, and an adversarial review of the frozen entry contract.
2. **Do not delete the command allowlist wholesale** — the doc agrees; there is no host
   sandbox to catch what the allowlist currently catches (C-E).
3. **Do not build the SDLC Navigator first** — it is optional by its own acceptance criteria
   and would front-load the least valuable part of T03.
4. **Do not rename the existing public prompt surface into `/sdlc-*`** while the surface is
   still being deduplicated and three prompts are already scheduled for removal (C-F).
5. **Do not expand executor autonomy without the corresponding EVAL-EXEC security evals**
   landing in the same change.
6. **Do not treat the §16.6/§25 scale numbers as re-verified** — they are recorded design
   evidence from the shelved v2 work; the synthetic benchmark fixture must reproduce them
   before any performance-driven cutover.

## 6. Open owner decisions (consolidated)

| # | Decision | Blocking | Recommendation |
|---|---|---|---|
| D1 | Supersede "stay on v1, pilot first" with the one-file Knowledge direction? | T07, T08b | Freeze contract + adversarial review + synthetic pilot first; decide with that evidence. |
| D2 | Operating mode: `closed-package-extension` vs `owned-managed-2gp` | T06 | Confirm closed-package-extension as explicit v1 profile now. |
| D3 | QA mandatory after Development, or risk-profile waiver? | T04/F-04 | Mandatory by default with persisted waiver. |
| D4 | Ad-hoc fix: lightweight review record or explicit out-of-SAFE disclaimer? | T04/F-09 | Disclaimer now; revisit after pilot frequency data. |
| D5 | Git autonomy: is feature-branch push `ALLOW` or `ASK`? | T01 | `ASK` initially; revisit with denial telemetry. |
| D6 | Flow Screen Validation into intentional-error scope? | T07 pilot | Keep out of v1 (doc's own default); decide after pilot search results. |

---

*Prepared 2026-07-24 as review input. Implementation of any item above requires the normal
governed workflow (work record, design approval, human deploy) — nothing here changes that.*
