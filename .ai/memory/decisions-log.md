# Decisions Log

Persistent, versioned cross-work-item memory of the project — distinct from VS Code's built-in
Memory tool (local, per-machine), Copilot Memory, canonical Knowledge claims, and active work
records. This file records durable architectural decisions; it is not the workflow state store.

Two kinds of entries belong here:

1. **Discoveries of system facts with practical consequences** (e.g. "we established that field
   X controls Y — this changes the plan for Z").
2. **Accepted cross-work-item architectural decisions** whose effect outlives an individual work
   record. Active designs, approvals, evidence, coverage assessments, reviews, and handoffs live
   under `.ai/change-records/<record-id>/` and are referenced here only when they establish a
   durable project decision.

System facts are canonical Knowledge claims and must not be duplicated here. Chat-only decisions
are not durable.

## Entry format (template — copy for each new entry)

```
## <date> - <short title>
- Context: ...
- Finding / decision: ...
- Impact: ...
- Approved by: <who>
- Related: <link to a knowledge/ file or another entry>
```

---

<!-- Entries are appended below this line as they occur — never fabricated at build time. -->
## 2026-07-30 - Composed read-only SOQL is permitted and recommended (policy phase)

- Context: every prior design treated "the model never composes SOQL" as a fixed constraint
  (byte-pinned review profiles, constructed-only `salesforce_read.py` reads). The workspace owner
  directed a rule change on 2026-07-30: agents may compose read-only SOQL, and doing so is
  recommended — when a task depends on how data actually sits in records (structure, fill, real
  shapes), the agent should query rather than guess or raise a blocking question. Discovery and
  full enforcement inventory: `output/discovery-2026-07-30-model-composed-soql.md`.
- Finding / decision: composed read-only SOQL is policy-permitted and recommended for
  task-serving reconnaissance, through the governed `salesforce-readonly` facade only (the vendor
  `@salesforce/mcp` stays a private child of the facade; raw CLI and raw vendor tools remain
  denied). The mechanical surface shipped the same day: the `review_soql_query` facade tool —
  statement-validated (single read-only SELECT, FROM-object allowlist minus a hard
  secret-adjacent deny-set, bounded LIMIT), identity-gated per call, values sanitized
  (emails/record-Id-shaped strings redacted) and single-source (`IDENTITY_MATCH_ONLY`
  reconciliation). `review.allowedObjectApiNames` became optional (absent = all objects), and the
  guarded `salesforce_read.py records` lane remains for bounded row snapshots. Standing
  constraints unchanged:
  read-only, sandbox-only, bounded LIMIT, no secret-adjacent objects (a 17-entry test-pinned
  deny-set covering credential/auth surfaces plus org-management and runtime-log entities —
  enumerated in `.ai/contracts/tool-capabilities.md`; TraceFlag and RemoteSiteSetting-class
  config entities deliberately excluded as non-secret), results are untrusted observations, raw
  rows/PII never committed. This partially supersedes the 2026-07-14 entry's framing that org
  grounding happens only through fixed review tools; that entry's read-only and no-org-mutation
  decisions stand in full.
- Impact: agent guidance flips from "never query" to "query when data shape matters"; the
  2026-07-14 enforcement layers stay mechanically in force until the facade tool ships, so no
  runtime behavior changes yet — only expectations and constraint texts.
- Approved by: workspace owner directive, 2026-07-30.
- Related: `output/discovery-2026-07-30-model-composed-soql.md`, the 2026-07-14 MCP read-only
  entry below, `docs/grounding-architecture.md`.

## 2026-07-23 - Ad-hoc fix express lane: bounded defect fixes without an accepted design record

- Context: a diagnosed Flow defect could not be corrected by any agent — config-investigator has
  no write authority and development-assistant's entry gate requires an accepted design record,
  so an ad-hoc bugfix had no lane. The write plumbing already existed (development-assistant may
  edit force-app/, `sf project retrieve start` is role-guard-allowed with
  `autoApproveRetrieveWithReceipt` enabled); only the ceremony blocked the edit.
- Finding / decision: add the `adhoc-fix` prompt + skill for development-assistant only. Entry:
  a written diagnosis and a small bounded fix (one defect, smallest coherent component set, no
  new automation, no schema/permission changes). Procedure: retrieve current org state, confirm
  the diagnosis, minimal force-app edit, local verification, fix note under
  `output/documentation/adhoc-fixes/` (diagnosis, before/after, human deploy step, rollback),
  after-the-fact guardrail review recommended. Deploys remain human; the 2026-07-14 "org
  mutation is not an agent capability" decision stands. The review allowlist stays
  `allowedObjectApiNames: ["*"]` by owner choice.
- Impact: no guard/hook/script changes — the note path reuses development-assistant's existing
  `output/documentation/` write prefix and the retrieve permission already existed.
  `validate_harness.py` expected counts moved to 23 prompts / 24 skills; repo map regenerated.
  Scope growth escalates to the normal design lane; the accepted-design gate stays normative for
  everything else.
- Approved by: workspace owner directive of 2026-07-23 (chat decision: local edit + human
  deploy, light ceremony with after-the-fact review, development-assistant only).
- Related: `.github/skills/adhoc-fix/SKILL.md`, the 2026-07-14 "MCP is read-only" entry (still
  in force), `.ai/contracts/workflow-state-machine.md` (unchanged; ad-hoc fixes are standalone
  and do not create work records).


## 2026-07-23 - Record-held package configuration enters Knowledge via investigate-config-records

- Context: part of the managed package's configuration lives in org data records (config tables
  holding statuses and settings), which the metadata-file-only collector (1.6.0) can never
  observe. The evidence schema already reserved `org-soql-sample`, the claim schema already has
  `reference-data`, and `scripts/salesforce_read.py records` already provides the guarded bounded
  read — the capability existed but no governed workflow used it.
- Finding / decision: add the `investigate-config-records` prompt + skill (config-investigator
  role). One human-provided allowlisted object per invocation; snapshot granularity is one
  `reference-data` claim per object (ordered sanitized record list in facts, `sha256` digest),
  not per-record claims. The allowlist stays human-edited per use; no batch collector mode in
  this iteration. Ids, URLs, `attributes` payloads, audit fields, and free text are stripped;
  claims scope to `orgKey` with `repositoryCommit: null` and drift only via re-observation.
- Impact: no schema, guard, policy, or Python-script changes — the role guard, `reference-data`
  policy entry (180-day ceiling), and propose/reconcile/promote lifecycle already cover the flow.
  `validate_harness.py` expected counts moved to 22 prompts / 23 skills; repo map regenerated.
- Approved by: workspace owner plan approval of 2026-07-23.
- Related: `docs/grounding-architecture.md` (Knowledge boundary, reference-data snapshot bullet),
  `.github/skills/investigate-config-records/SKILL.md`.

## 2026-07-16 - Templates are normative or removed; two script-shadow templates deleted

- Context: the 2026-07-16 harness audit (audit/findings.md F-06) found the template layer
  partially decorative: `change-record.md` and `feature-dossier.md` had zero inbound references
  and duplicated structures owned by code (`scripts/work_record.py` design-narrative scaffold,
  `scripts/force_app_knowledge.py` `render_dossier`), so they silently drift when the scripts
  change; `knowledge-entry.md` was referenced only in passing by `keyword-taxonomy.md`.
- Finding / decision: each `.ai/templates/*.md` file must be normative — referenced by its
  producing skill or read by its producing script — or removed. Accordingly `change-record.md`
  and `feature-dossier.md` are deleted (their structures stay script-owned), and
  `knowledge-entry.md` is kept and cited by the `investigate-object` and `update-knowledge-base`
  skills as the human-facing companion to `schemas/knowledge-claim.schema.json`.
- Impact: the remaining templates (`technical-documentation.md`, `feature-health-report.md`,
  `release-handover.md`, `knowledge-entry.md`) are all consumer-referenced; no template can
  silently lie about a structure owned elsewhere.
- Approved by: workspace owner, 2026-07-16 audit review (findings.md F-06).
- Related: audit/findings.md (F-06), `.ai/templates/`, the F-07 entry below.

## 2026-07-16 - tool-capabilities contract wired into every agent role

- Context: the 2026-07-16 harness audit (audit/findings.md F-07) found
  `.ai/contracts/tool-capabilities.md` (Status: normative) loaded by no agent or skill, while
  `.ai/repo-map.md` declares contracts "loaded per role" — unlike the other four contracts,
  which are all consumed.
- Finding / decision: keep the contract normative and wire it into the Load list of all five
  agents (solution-designer, config-investigator, development-assistant, guardrail-reviewer,
  test-strategist) — every agent dispatches namespaced `ado-readonly/*` /
  `salesforce-readonly/review_*` tools that the contract maps.
- Impact: `repo-map.md`'s "loaded per role" claim is true again; namespaced-tool dispatch is
  grounded in the capability map instead of model memory.
- Approved by: workspace owner, 2026-07-16 audit review (findings.md F-07).
- Related: audit/findings.md (F-07), `.ai/contracts/tool-capabilities.md`, `.ai/repo-map.md`.

## 2026-07-14 - Knowledge upgrade: total metadata coverage and chat-approved promotion

- Context: running the documentation pipeline on an approval process produced nothing (only 10
  metadata types had parsers/claim candidates), and promotion required a hand-written review YAML
  with digests plus two terminal commands — the feature added work instead of removing it. The
  workspace owner directed a careful autonomy upgrade.
- Finding / decision: (1) coverage is now total — approval processes draft automation-inventory
  claims and every other source-format metadata file drafts a generic claim into the new
  `component-inventory` domain (schema/policy/registry extended); a recognized source file can no
  longer draft nothing. (2) Agents may request promotion/rejection via the new
  `knowledge_registry.py approve-claim` command: the safety hook answers `ask` so a human
  confirms every invocation in the chat dialog, the reviewer identity comes from the human-owned
  `knowledge.chatReviewer` value in ignored local configuration, and the recorded mechanism is
  `copilot-chat-confirmation` (new review-schema enum value). The registry computes all binding
  digests itself and re-renders the domain indexes. File-based `review`/`promote` remain
  human-terminal-only; work-record approval is unchanged (terminal-only).
- Impact: the propose → approve loop happens in one chat session with one human click per claim;
  SAFE-HUMAN-001 was reworded to distinguish the recorded chat-confirmation dialog from chat
  text (which is still never approval).
- Approved by: workspace owner directive, 2026-07-14.
- Related: `.ai/contracts/knowledge-lifecycle.md`, `docs/force-app-knowledge-architecture.md`.

## 2026-07-14 - Batch knowledge conversion: one metadata type per run, chunked chat approval

- Context: the team must convert a large existing architecture into Knowledge; doing it
  component-by-component does not scale, and mixing metadata types in one run makes review
  sloppy. The owner requested a batch flow (one type per batch, e.g. all Flows) following
  discovery → planning → plan verification → execution → result verification.
- Finding / decision: new public `/batch-knowledge type=<MetadataType> [chunk=N]` prompt backed
  by a five-phase skill. Supporting mechanics: `force_app_knowledge.py draft --metadata-type`
  filters drafting to one type; `knowledge_registry.py approve-claim --claim-spec
  <claimId>:<revision>` (repeatable, capped at 25) lets one human confirmation click approve one
  chunk. Skips already-verified fresh claims; stop rules pause instead of improvising; a batch
  report lands in `output/documentation/`.
- Impact: converting e.g. 60 flows costs ~6 confirmation clicks (10-component chunks) while
  every claim still gets an individually recorded chat-approval review; counts moved to
  12 prompts / 16 skills and the validator now derives all counts from one constant.
- Approved by: workspace owner directive, 2026-07-14.
- Related: `docs/force-app-knowledge-architecture.md` (batch section), the two 2026-07-14
  knowledge entries below.

## 2026-07-14 - AI description layer: agents author what components do

- Context: purely mechanical claims ("X exists at commit Y, 2 steps") carry no understanding —
  the owner asked whether the agent should participate in knowledge creation because structural
  facts alone make the knowledge base useless for questions like "what does this flow do".
- Finding / decision: behavior-bearing components (Flow, Apex, triggers, approval processes,
  LWC/Aura) draft an additional `component-description` claim whose description is an
  `<AGENT_...>` sentinel. The agent reads the actual source and writes 2–6 sentences (purpose,
  trigger, key actions, what it reads/changes) strictly from source; the registry rejects
  unfilled sentinels at propose time. These claims carry `assurance: inferred` (a schema
  carve-out allows verified+inferred only for this claim type) and become `verified` solely
  through the human chat approval — SAFE-CLAIM-001 is preserved: the model proposes, the human
  verifies.
- Impact: knowledge answers "what does this component do", not just "does it exist"; the human
  reviews exactly the sentence the model inferred before it becomes trusted; descriptions expire
  after 180 days (shorter than structural claims) because they drift with code.
- Approved by: workspace owner directive, 2026-07-14.
- Related: `docs/force-app-knowledge-architecture.md`, the 2026-07-14 chat-approval entry above.

## 2026-07-14 - MCP is read-only; org mutation is not an agent capability

- Context: the fleet runs Windows, where VS Code cannot sandbox MCP processes, so the
  `salesforce-development` write server was permanently blocked there and produced a recurring,
  confusing `exit code 2` MCP startup error. The workspace owner directed a model change: MCP
  exists to gather information and support solution design/development, not to deploy or
  retrieve.
- Finding / decision: the `salesforce-development` MCP server, its `sf_dev_org` input, and the
  OS-level `sandbox`/`sandboxEnabled` keys are removed from `.vscode/mcp.json`. The configured
  MCP surface (`ado-readonly`, `salesforce-readonly`) is read-only by construction. Agents ground
  context in the connected org through the review facade and the guarded
  `scripts/salesforce_read.py` (now also available to Solution Designer and Development
  Assistant). The only raw Salesforce CLI agents may request is `sf project retrieve start`
  against a configured non-production alias, and the safety hook stops every invocation for
  human confirmation (SAFE-HUMAN-001); deploys and all other raw CLI stay denied and ship
  through the human-run release process outside Copilot.
- Impact: the Windows MCP error is gone; the write-capable attack/blast surface is gone with it
  (no MCP write path exists to protect, so losing OS sandboxing on Windows no longer degrades
  the model). Enforcement layers: guarded wrapper, review facade, global safety hook, role
  guards, validator checks (which now fail if a write server or sandbox keys reappear without a
  new recorded decision).
- Approved by: workspace owner directive, 2026-07-14.
- Related: `docs/compatibility.md` (verification boundary), `SETUP.md` §3/§6,
  `docs/windows-setup.md`.

## 2026-07-13 - npm audit findings in the pinned Node tree are accepted, not fixable today

- Context: `npm audit` reports 24 findings (6 low, 17 moderate, 1 high `protobufjs`) in the
  pinned dependency tree. The workspace upgrade policy requires a tested vendor-supported update
  or a recorded risk decision. A resolution attempt was run on 2026-07-13.
- Finding / decision: every finding is a transitive dependency of vendor-pinned Salesforce
  tooling and none is resolvable on stable channels today. Evidence: `@salesforce/mcp@0.30.15`
  is the latest published version (npm's suggested "fix" `0.3.0` is a downgrade artifact);
  the `@salesforce/sfdx-lwc-jest` fix ships only in `8.0.0`, which is dist-tagged `prerelease`;
  a full in-range `npm update` was tested and made the posture worse (37 findings, 9 high) by
  pulling newer transitives with fresh advisories, then was reverted. Decision: keep the pinned
  baseline, accept the 24 findings, and revisit on each Dependabot vendor release.
- Impact: exposure is bounded by the existing controls — the tree is installed with
  `--ignore-scripts`, runs only on the local pilot workstation (never in an org or CI deploy
  path), the MCP servers run under the workspace sandbox/wrapper policy, CI hard-fails only on
  `critical`, and Dependabot watches pip/npm/actions weekly. The `protobufjs` high is a DoS in
  JSON descriptor parsing inside `@salesforce/mcp`'s telemetry chain, not an harness-reachable
  code path. Re-evaluate when `@salesforce/mcp` publishes a new stable or `sfdx-lwc-jest@8`
  leaves prerelease; do not adopt prerelease tooling in this governance-pinned workspace.
- Approved by: workspace owner directive of 2026-07-13 (Windows-rollout goal); formal team
  sign-off pending at pilot review.
- Related: `docs/compatibility.md` (upgrade policy), `SECURITY.md` (dependency posture).

## 2026-07-31 - Any non-production org is permitted for agent reads; production is the only deny

- Context: the review lane admitted only aliases pre-registered in `config/harness.local.json`
  with pinned host/organization-ID identity, and only sandbox/scratch hosts. Testing the
  workspace against ad-hoc orgs (scratch orgs, Developer Edition orgs) required a config edit for
  every alias, and Developer Edition hosts were refused outright.
- Finding / decision: owner reverses the allowlist-only posture. New
  `salesforce.review.allowAnyNonProduction` toggle (default `false`): when enabled, an alias with
  no config entry is admitted on live identity proof alone — the host must match the canonical
  sandbox (`*--*.sandbox.my.salesforce.com`), scratch (`*.scratch.my.salesforce.com`), or
  Developer Edition (`*.develop.my.salesforce.com`) signature and `Organization.IsSandbox` must
  match that signature (true for sandbox/scratch, false for Dev Edition). The proven identity is
  frozen for the rest of the session. Explicit entries keep the pinned lane; the new
  `environment: "production"` entry value is a hard deny marker no toggle overrides; production
  signatures (other hosts, prod-like aliases) stay refused everywhere.
- Impact: `verify_salesforce_org.py` (dynamic lane), `start_salesforce_mcp.mjs`,
  `salesforce_review_server.mjs` (dynamic runtime + identity freeze), `copilot_safety_hook.py`
  review gate, `salesforce_read.py`, `schemas/harness-config.schema.json`,
  `schemas/salesforce-org-review-evidence.schema.json` (target.environment gains `dynamic`,
  `isSandbox` becomes a real boolean), and the pinned tests. Dev Edition envelopes report
  `isSandbox: false` by design.
- Approved by: workspace owner (chat, 2026-07-31).
- Related: entry "2026-07-30 - Composed read-only SOQL is permitted and recommended (policy phase)".

## 2026-08-02 - `nonProduction` is the org-safety verdict; `isSandbox` is only an attribute

- Context: the 2026-07-31 decision admitted Developer Edition orgs, and the review facade proves
  them correctly — but the *receipt* still carried the verdict in `isSandbox`, which Salesforce
  reports as `false` for a Dev Edition by design. Every consumer gate demanded `isSandbox is
  True`, and `change-record.schema.json` pinned `isSandbox: {const: true}` for a verified
  environment. Measured live: `preflight` PASSED and the review returned `VERIFIED`, yet the
  receipt read `target.isSandbox: false` and the agent refused, quoting SAFE-ENV-001's "exact
  allowlisted sandbox". The 2026-07-31 migration was half-finished — it relaxed the evidence
  schema and never followed through to the record schema, the gates, or the agent-facing text.
- Finding / decision: split the two meanings. The receipt gains `nonProduction` — the security
  verdict, set only where the proof already holds (live host matches `NON_PRODUCTION_HOST` **and**
  `Organization.IsSandbox` matches what that host shape implies). `isSandbox` stays as Salesforce's
  attribute, explicitly documented as not a gate. Every gate keys on `nonProduction`.
  **Fail-closed:** a receipt without the fact does not pass — no fallback to `isSandbox`, so the
  weaker predicate cannot remain the real boundary. Receipts expire in 30 minutes, so the
  migration costs at most one `capture-org-review`.
- Impact: `salesforce_review_server.mjs` (proof, `baseTarget`, identity facts; `validateMcpIdentity`
  now fails closed instead of comparing a record to itself when no identity is frozen),
  `schemas/salesforce-org-review-evidence.schema.json` (`nonProduction` required in `target` and
  `identityFacts`; new `unprovenTarget` pins the enumeration receipt's all-false shape so it can
  no longer be misread as a failed proof), `schemas/change-record.schema.json` (verified
  environments now require `nonProduction: true`; `isSandbox` relaxed to a plain boolean),
  `work_record.py` (six gates + an explicit reject of the dynamic lane, previously only emergent),
  and the agent-facing wording in SAFE-ENV-001, two skills, the facade's tool descriptions and
  `docs/grounding-architecture.md`. New tests pin a **configured** Dev Edition (the shape the owner
  actually runs, previously uncovered — both existing Dev Edition tests used the dynamic lane).
- Approved by: workspace owner (chat, 2026-08-02).
- Related: entry "2026-07-31 - Any non-production org is permitted for agent reads; production is
  the only deny".

## 2026-08-03 - Documenting existing state is record-free; a work record is only for governed delivery

- Context: the owner tried to build Knowledge for a **Flow** — existing functionality retrieved
  from the org, not a new development — and the agent demanded a `recordId` before proceeding.
  There was nothing valid to supply: `change-record.schema.json` pins `recordId` to
  `^ADO-<project>-<n>$` and requires `workItem.system == "azure-devops"` with an integer `id`, so
  a work record is **unconstructable without a real ADO work item**. The only way to satisfy the
  demand was to fabricate an ADO number.
- Finding: nothing mechanical required it. `knowledge_registry.py propose` takes no record
  argument; `recordId` is not a field in `knowledge-claim`, `knowledge-evidence`, or
  `knowledge-entry`; the dependency runs record → knowledge via the *optional* `claimRefs`/
  `entryRefs` ("present only when entries are bound"), never the reverse. The requirement lived
  purely in agent-facing prose, written for the org-investigation lane and applied to all lanes.
  `investigate-config-records` already had the correct conditional wording — this was a
  half-finished migration, not a missing design.
- Decision: **the requirement is conditional on the lane.** Governed delivery work supplies a work
  record and evidence attaches to it. Knowledge that documents existing state — the force-app
  Knowledge and Entry lanes (`inventory-force-app`, `propose-force-app-knowledge`,
  `batch-knowledge`, `refresh-force-app-knowledge`, `feature-documentor`, `update-relations`) — is
  record-free by construction, and no agent may block it for a record or invite a fabricated ID.
  Its audit trail is the canonical records plus the append-only entry ledger; a parallel
  "documentation record" type was considered and rejected as ceremony.
- Impact: six agent-facing layers, all of which would have reproduced the failure one level up if
  only the obvious one were fixed — `AGENTS.md` (always-on shim, kept under its 150-word cap),
  `.github/copilot-instructions.md` grounding sequence step 1 (the kernel names Knowledge
  promotion explicitly), `config-investigator.agent.md` (required procedure + return contract),
  `investigate-object/SKILL.md` (input, procedure steps 1 and 8, return — it contradicted its own
  prompt, which says `[recordId=<ID>]` … "otherwise the investigation is a standalone read"), and
  `update-knowledge-base/SKILL.md` step 8. No schema, executor, or gate changed.
- Tests: `RecordFreeKnowledgeLaneTests` in `tests/test_knowledge_contract.py` — a sentence-level
  guard that any demand naming a work record must carry a lane qualifier, a self-check that pins
  the seven verbatim pre-fix sentences so the guard cannot go inert, and a generic contradiction
  test asserting no skill requires what its own prompt marks optional (11 prompt/skill pairs).
- Approved by: workspace owner (chat, 2026-08-03) — asked whether to fix all layers or only the
  agent; owner chose all layers plus the test.
- Not verified live: the symptom was observed in the Copilot host, this fix is text-only and has
  not been re-driven against a live session.

## 2026-08-03 - Org-usage layer: owner gate decisions D-1..D-6 (+D-5'), Phase 1 authorized

- Context: the org-usage layer (agents run governed SOQL when documenting metadata and persist
  aggregates/shape in the entry's `orgUsage` section) was designed 2026-07-29, transport-amended
  2026-07-30 (`review_soql_query` replaces the probe catalog), and re-planned 2026-08-03 by a
  9-agent workflow with adversarial verification
  (`output/plan-2026-08-03-org-usage-implementation.md` — A-minimal architecture + B grafts,
  zero CI-pin churn). The owner answered the gate questions in chat, 2026-08-03:
- **D-1 (gate 1, containment):** org-bearing entries live only in the **private company clone**
  ("to będzie używane w company, w prywatnym sklonowanym repo"). Mechanism: attach refuses
  unless origin matches `orgUsage.allowedOriginRemotes` (allowlist-shaped; shipped EMPTY on the
  public product repo = attach refuses everywhere; a failing `git remote` is a refusal).
  Merge-back of org-bearing entries to the public origin is permanently forbidden.
  **Refined same day (owner, chat): SINGLE-REPO model.** The owner clones this repo into a new
  repository in the company's GitHub Enterprise org; that one repo IS the whole workspace, and
  query results (orgUsage sections + the org ledger) are committed there. No mechanism change
  was needed — the containment check is origin-allowlist-shaped and does not care whether the
  private location is a fork, a clone, or a standalone repo. Operating rules recorded in
  contract §6.6: the enterprise repo's `allowedOriginRemotes` carries the enterprise URL(s)
  (both ssh and https forms, exact strings from `git remote -v`); the public origin URL is
  NEVER allowlisted; while a temporary public remote exists for a product-update sync, attach
  refuses by design — remove it after the sync (or sync via git bundle).
- **D-2 (gate 4, expiry):** `maxOrgUsageAgeDays = 90` — PROVISIONAL: the sandbox refresh
  cadence and per-alias full-copy-vs-partial facts are still owed before Phase 4; if cadence
  proves < 90d the value must be trimmed. `compute_org_lane` applies
  `min(stored expiresAt, observedAt + current policy)` so tightening expires retroactively.
  **Half-delivered same day (owner, chat): EVERY company sandbox is a full copy** (the managed
  package requires it) → set `fullCopy: true` on every alias in the enterprise repo's
  harness config. `fullCopy` is a descriptive label, never a gate — nothing in the layer
  refuses or requires it; it only labels representativeness in orgUsage blocks and
  disclosures. Still owed: the refresh cadence (the only remaining D-2 fact).
- **D-3 (governance):** schema-as-instrument, click-free attach. The human approves the
  INSTRUMENT once (closed kind enum + per-kind result shapes + executor derivers + sanitization
  + expiry + allowlist), not each number; attach/detach stay in the authoring bucket of the
  verb-partition test. Empty allowlist remains the brake.
- **D-4:** dynamic-lane receipts refused — attach is configured-org only (orgIdDigest needs the
  configured `expectedOrganizationId`).
- **D-5 + D-5' (owner modification):** sampling defaults LIMIT 25 / CreatedDate DESC /
  ≤20 columns / §2.3 exclusion rules ACCEPTED, **with query freedom**: the agent may compose
  several probes of one kind with different WHERE criteria (per status etc.) and aggregate
  queries at its discretion. Consequence: the instrument closes over the **kind enum + per-kind
  result shapes**, NOT a fixed label list — labels are free slugs, queryText stays in the
  receipt, only executor-derived numbers persist.
- **D-6:** no new prompt/skill — sampling folds into batch-knowledge + propose-force-app-knowledge
  as a default-on step (dedicated investigate-usage prompt only if the pilot shows the need).
  **Amended same day (owner, chat):** `/feature-documentor` also samples BY DEFAULT — anchors
  only (not all wave-1 boundary members): step 6a attaches to each wave-1 anchor's entry when a
  review org is configured, and the dossier cites the entries' fresh `orgUsage` (orgKey +
  observedAt) instead of transcript numbers. Feature Entries themselves still cannot carry
  `orgUsage` (wave-1 pin); the feature lane consumes it from the artifact entries.
- Phase 1 implemented same day on branch `feat/org-usage-layer` (contract v1.2 §2.3/§3/§4/§5.5/
  §5.7/§6.6/§14.3; `orgUsage` $defs family + wave-1 pin in knowledge-entry schema; policy block
  90d; harness-config `fullCopy`/`refreshedAt`; `.cache/org-usage/.gitkeep`).
- Phases 2+3 implemented same day, one commit (the entry-command reachability pin couples the
  executor to its workflow surface): `entry-org-attach`/`entry-org-detach` executors (facade
  subprocess client; containment fail-closed on `git remote` failure; whole-run abort on any
  identity/environment mismatch; per-kind derivers — row values never persist; receipt wrapper
  under `.cache/org-usage/`; separate append-only `artifacts-org-ledger.jsonl`),
  `compute_org_lane` with the min(expiresAt, observedAt+policy) retroactivity rule and the
  `refreshedAt` fallback detector, entry-draft carry-forward, guard mirrors + ORG_ATTACH_ROLES
  (config-investigator only) + `.cache/org-usage/` write prefix, `validate_harness`
  `check_org_usage` hard gate (ledger monotonic, digest==ledger-latest, containment),
  INDEX_SCHEMA_VERSION 1→2 with metadata-only projection (probe values structurally excluded
  from BM25/facets) and the context `orgUsage` bucket, entry-status/entry-check/entry-review
  disclosure (expired ⇒ values withheld), default-on sampling steps in batch-knowledge and
  propose-force-app-knowledge, router/handoff sentences in investigate-object, solution-design,
  solution-designer and config-investigator, RecordFree SURFACES extended, 2 deny eval
  scenarios, and `tests/test_org_usage.py`. Phase 4 (live enablement in the private pilot
  clone) blocked on the owed D-2 facts + D-1 allowlist fill.
- Approved by: workspace owner (chat, 2026-08-03).
- Related: entries "2026-07-30 - model-composed SOQL", "2026-07-14 - MCP is read-only".

## 2026-08-03 - Selected-files Knowledge lane ("pin lane"): owner decisions D-1..D-4, build authorized

- Context: neither existing lane fits "document exactly these files" — `/batch-knowledge` is
  one-metadata-type-only and `/propose-force-app-knowledge` drafts the whole inventory. The
  developer gesture is pinning files to Copilot chat or naming them in the prompt; a selection
  is usually mixed-type. Discovery + plan:
  `output/discovery-2026-08-03-selected-files-knowledge.md`.
- **D-1:** a NEW prompt `pin-knowledge` + skill `selected-files-knowledge` (not a `files=`
  argument on propose — that would overload an already dense skill with a second selection
  model). Prompt/skill count pins move 24→25 / 25→26.
- **D-2:** ALWAYS present the resolution table + per-component plan and require an explicit
  go-ahead before executing — no fast path for small selections; consistent with batch Phase 3.
- **D-3:** a pinned directory EXPANDS to its contained components with a hard cap of 25 (the
  chat-approval chunk); larger expansions are refused with a pointer to `/batch-knowledge`,
  never silently truncated.
- **D-4:** the new read-only `resolve` command is guarded to `FORCE_APP_KNOWLEDGE_ROLES`
  (config-investigator + knowledge-curator), matching `worklist` — not the dashboard-style
  every-role carve-out.
- Phase 1 implemented same day: `force_app_knowledge.py resolve` (lexical path/name→component
  mapping — casefolded paths, companion `-meta.xml` siblings both ways, LWC/Aura bundle-member
  and directory resolution, multi-component files expand to ALL components, ambiguity reported
  never guessed, expansion cap 25, input cap 50), `draft --component <Type:Name>` exposing the
  pre-existing `component_ids` filter (CLI-boundary cap 25 in `cli_component_ids`; `draft()`
  itself deliberately uncapped for relations-draft/feature-draft; unknown ids raise;
  `--component` + `--metadata-type` mutually exclusive at both draft() and guard), the
  `force-app-knowledge-resolve` schema, guard mirrors (path hygiene = force-app segment + no
  traversal; spaces/colons legal for Layout names and component ids), and tests incl. the
  adversarial-review round (multi-component files, companions, case-insensitivity, guard
  accept/deny matrix, cap boundaries).
- Phase 2 implemented same day: public prompt `pin-knowledge` + hidden skill
  `selected-files-knowledge` (selection sources in priority order, mechanical resolve,
  always plan + go-ahead, entry/claim execution with approvals counted by CLAIM — each
  `approve-claim` command caps at 25 specs and a component can produce several claims;
  oversized mixed selections are split per metadata type via `/batch-knowledge` or re-pinned),
  count pins 24→25 / 25→26, repo-map word budget 875→900 (synced in `render_repo_map.py` and
  `validate_harness.py`), regenerated repo map, two `agent-scenarios.yaml` behavioral
  scenarios, config-investigator routing + record-free list, and the architecture doc's
  selected-files section. Both phases passed an adversarial verification round
  (8 + 3 findings, all fixed and re-probed) on top of the deterministic gate.
- Approved by: workspace owner (chat, 2026-08-03).
- Related: entries "2026-08-03 - Documenting existing state is record-free",
  "2026-07-27 - Knowledge v2 one-file entries".

## 2026-08-03 - v1 claim registry retirement approved; P0 decoupling executed

- Context: the workspace operates on one-file Knowledge Entries (2026-07-27 decision), but
  the v1 claim registry (claims/evidence/reviews, worklists, batch promotion) still owns
  large parts of the code and text surface. Its status surfaces (worklist, coverage,
  dashboard, stale-report) compute from a claim corpus that is empty (zero claims were
  ever committed) and frozen by `enforce_entry_home_freeze`, so they read "nothing
  documented" forever regardless of entry approvals. Full inventory:
  `output/discovery-2026-08-03-v1-claim-registry-removal.md`.
- Finding / decision: the owner approved removing the v1 claim registry entirely, in
  phases (P0 relocations -> P1 work-record surgery -> P2 engine deletion -> P3 text ->
  P4 data/docs -> P5 live verification). Owner decisions D-A..D-G (org/vendor/SME
  observation home, work-record ownership gate replacement, unprofiled-type dependency
  lookups, envelope verification, relation lane, keyword curation, envelope claimRefs
  fields) remain open and gate the later phases.
- Impact (P0, this entry): the entry store no longer depends on the retiring module.
  `canonical` / `canonical_digest` moved verbatim to the new leaf `scripts/knowledge_digest.py`
  (digest bytes pinned by `tests/test_knowledge_digest.py`; a serialization change would
  silently revoke every approved entry); entry citation verdicts moved to
  `knowledge_store.verify_entry_citations` with a new read-only `entry-verify-citations`
  CLI (guard-listed, named in generate-release-handover; the registry method now
  delegates); `force_app_knowledge.entry_home_types` reads `knowledge_store.PROFILES`
  instead of the registry mirror constant. A dependency-direction test pins that
  `knowledge_store.py` never re-imports `knowledge_registry`. No v1 behavior changed;
  registry CLI surface, guard tables for it, and all v1 tests are untouched until P2.
- Approved by: workspace owner (chat, 2026-08-03).
- Related: entry "2026-07-27 - Knowledge v2 one-file entries";
  `output/discovery-2026-08-03-v1-claim-registry-removal.md`.

## 2026-08-03 - v1 retirement gate decisions D-A/D-B/D-C/D-G; P1 work-record surgery executed

- Context: the phased v1 claim-registry removal (see the P0 entry above) left seven owner
  decisions open. Four gate P1/P2 and were put to the owner explicitly.
- Finding / decision (owner, chat 2026-08-03):
  D-B - work-record component grounding is ENTRY-BASED and FAIL-CLOSED: every scope
  component must be covered by a bound approved-current entry (the component itself or its
  owning CustomObject); a metadata type without an entry profile blocks SAFE/approval, and
  the remedy is extending knowledge_store.PROFILES, never widening the gate.
  D-A - org/vendor/SME observations lose the registry: investigate-config-records and
  investigate-object become read-only investigations reporting into output/ (org sampling
  stays entry-org-attach); semantic org facts live as prose, uncited.
  D-C - check-feature-coverage drops the registry dependency lookup and must NAME the
  metadata types its result did not cover; a mechanical inventory-based lookup is backlog.
  D-G - claimRefs/ownership fields are REMOVED from change-record/handoff/output envelope
  schemas outright (no legacy compatibility fields; no records exist on disk).
- Impact (P1, this entry): work_record.py loses bind-claim, claimRefs, the KnowledgeRegistry
  import and the ownership fields on components (components are name+type only); SAFE and
  human-approval gates now require entryRefs plus component_entry_coverage_problems() == [].
  The three envelope schemas and all envelope fixtures dropped claim shapes; the governed
  output-envelope arm now REQUIRES entryRefs (was: claimRefs minItems 1 — without the
  required key the arm would have been fail-open). test_work_record.py re-grounded on a
  patched entry lane, with new negative pins: ownership fields refused at parse and at
  schema, approval fail-closed on uncovered components and unprofiled types.
- Approved by: workspace owner (chat, 2026-08-03, AskUserQuestion with recommendations).
- Related: the P0 entry above; output/discovery-2026-08-03-v1-claim-registry-removal.md.

## 2026-08-04 - v1 retirement executed end to end (P2-P4); docs archival deferred

- Context: continuation of the phased v1 claim-registry removal (P0/P1 entries above).
- Finding / decision: P2a/P2b/P3/P4 executed. The engine is gone
  (scripts/knowledge_registry.py, the collector's claim-drafting half, guard/hook surfaces,
  CI steps, six v1 schemas, the claim keys of knowledge-policy.json); the text layer speaks
  entries only (six prompts + seven skills + knowledge-lifecycle.md deleted; investigate-*
  rewritten read-only per D-A; SAFE-CLAIM-001 v3 + SAFE-HUMAN-001 + ORG-KNOW-001..003
  rewritten; counts prompts 25->19, skills 26->19, contracts 5->4); the empty v1 data files
  (.ai/knowledge claims/evidence/reviews dirs, claims-index.json, 11 rendered domain stubs)
  are deleted with their write-guard arms, and .ai/knowledge/README.md now documents the
  entry store. The normative org-sampling spec lives in investigate-object/SKILL.md.
  Historical docs that describe the v1 system (docs/spec-p5-attested-claim-lane-2026-07-27.md,
  docs/force-app-knowledge-architecture.md, the knowledge plans/threads) stay in docs/ as
  decision records; moving them out of the repo belongs to the separately owner-gated
  workspace-cleanup plan, not to this retirement.
- Impact: the P5 attested-claim lane design is permanently superseded (no registry to attach
  it to). check-feature-coverage must name unprofiled-type dependents as an uncovered class
  (owner D-C). Live verification of the surviving flows against real Copilot (retirement P5)
  is still outstanding.
- Approved by: workspace owner (chat, 2026-08-03, direction + D-A..D-G).
- Related: the two v1-retirement entries above; output/discovery-2026-08-03-v1-claim-registry-removal.md.

## 2026-08-04 — All-type entry-profile expansion ("Knowledge musi pokrywać wszystkie typy")

- Decision: every metadata type the collector parses into reviewable components gets an
  entry profile — 48 new types across five groups (UI 16, automation 8, access 7,
  data/config 8, integration 9), taking knowledge_store.PROFILES from 10 to 58 types over
  45 profile schemas (shared: apex, value-set, routing-rules, integration, visualforce).
  The parse_generic_meta fall-through bucket (Settings, Letterhead, Group, Network,
  Certificate, Document, Territory2, translations and similar label-only extraction) and
  the CustomLabels container stay deliberately inventory-only: an entry carrying only
  {label, rootElement} cannot be honestly reviewed. Follow-up path recorded in the plan:
  dedicated parsers for CustomPermission, LightningMessageChannel, CustomSite,
  CustomNotificationType, then profiles.
- Preceded by collector wave 1.8.0 (same day): assurance-laundering fixes (rule-file
  formulas, Visualforce/Aura/EmailTemplate regex edges), folder-qualified Report/Dashboard
  identities, uniform truncation (shared cap_references + factsTruncated aggregate mapped
  to extractionCoverage partial), Profile assigns-layout silent-drop fix, Layout
  operates-on edge.
- Consequences: work-record D-B fail-closed coverage widens automatically (reads PROFILES
  live); D-C "not covered" lists now name only the generic-bucket remainder; coverage ≠
  citability stands — heuristic-edge sections stay ungroundable per §8.1a; population
  remains demand-driven under unchanged approval chunk caps. Unprofiled-probe tests
  re-grounded from Layout/NamedCredential to Letterhead.
- Approved by: workspace owner (chat, 2026-08-04, "zrob plan i dodaj wszystkie profile").
- Related: output/plan-2026-08-04-all-type-knowledge-profiles.md.

## 2026-08-04 — Knowledge MCP is the agents' only named read surface (server + full wiring)

- Decision: expose governed Knowledge retrieval as a first-class MCP server
  (`scripts/knowledge_mcp_server.mjs`, 11 read-only tools: context, search, impact,
  resolve, entry-status + explain, tree, feature-drift, feature-dossier, edge-health,
  capabilities) and make it the **default first source** for repository questions in every
  agent definition. Native force-app search stays legitimate only after a recorded
  `NO_ENTRY` gap or to verify/edit actual source.
- D1 (scope): all six agents get `knowledge/*`. D2 (stale index): the wrapper rebuilds the
  gitignored cache once and retries once, so the INDEX STALE dance never reaches agents.
  D4 (hardness): middle — the native `search` grant was REMOVED from solution-designer,
  config-investigator and guardrail-reviewer (readers; `knowledge_resolve` covers
  name/path→file discovery over the full inventory), kept for development-assistant,
  test-strategist, knowledge-curator (they edit/verify source content). D5 (definitions):
  FULL transition — no CLI dual-path in agent-facing text; owner's rationale is the
  v1-retirement lesson that two competing lanes in definitions rot into bypass.
- Set A re-pin: `validate_harness.py` SET_A_CALL moved from the CLI literal to
  `knowledge_context`; master-plan §7 Set A now counts **10** surfaces
  (investigate-object and suggest-test-cases joined — both had adopted the step-1 lookup
  after the plan was written; suggest-test-cases was also still citing the retired v1
  `query --subject-identity` interface, fixed here). The CLI command menu survives only in
  search-knowledge as the operator fallback. Curator store-maintenance commands
  (inventory, entry-readiness, entry-coverage) stay terminal by design; write lanes
  (draft/approve/pin) stay chat+terminal — SAFE-HUMAN-001 untouched.
- Wiring: `.vscode/mcp.json` + new `.github/mcp.json` (Copilot CLI reads only the latter);
  validator pins both configs, the server-set, the tool allowlist↔argparse contract
  (tests/test_knowledge_mcp_contract.py) and readOnlyHint; smoke over real stdio in
  tests/test_knowledge_mcp_server.py.
- Measurement: baseline (pre-wiring, clone at c992317) recorded in
  harness-lab RESULTS-LOG — Knowledge never consulted in 3/6 runs, consulted late
  (call 13/13/30) in the rest; the after-leg runs on the wired HEAD.
- Approved by: workspace owner (chat, 2026-08-04 — "chcę żeby knowledge search był default",
  full-MCP + środkowa twardość wybrane w AskUserQuestion).
- Related: output/discovery-2026-08-03-knowledge-mcp-server.md (plan + execution update).

## 2026-08-04 — Composed-SOQL blockade removed; SOQL recommended for designer/curator/developer, MCP-transport only

- Owner directive (chat, 2026-08-04, over-engineering review): "blokada powinna być w ogóle
  zdjęta jeśli chodzi o odpalanie SOQL"; SOQL usage is to be RECOMMENDED for the Solution
  Designer, the Knowledge agent, and the Development Assistant — "ale tylko przez Salesforce
  MCP, a nie CLI".
- `review_soql_query` is now a governed pass-through: the statement executes VERBATIM over
  the pinned Salesforce MCP child against the identity-proven non-production org. Removed:
  statement grammar validation, the 17-object secret-adjacent deny-set (NamedCredential …
  SamlSsoConfig), LIMIT parsing/rewriting and the `soqlMaxRows` policy key, email/record-Id
  redaction + 120-char truncation, and the sensitive-output blanking for SOQL envelopes.
  Accepted consequence, stated to the owner: sandbox record values (emails, record Ids,
  secret-adjacent objects) are now agent-visible and appear in transcripts.
- Kept: one-alias binding; non-production identity proof (now cached per server session —
  the CLI leg no longer re-runs three subprocesses per query; every MCP leg still re-checks
  org id + sandbox flag); an EXPLICITLY configured `review.allowedObjectApiNames` list;
  payload byte caps + SOQL timeout; `queryDigest` now over the verbatim submitted statement;
  `fromObjects` extraction (org-sampling executor contract). `entry-org-attach` unchanged.
- The "MCP not CLI" rule is enforcement-unchanged: the safety hook still denies every raw
  `sf`/`sfdx` data command and raw vendor tools; the facade's SOQL data path never touched
  the CLI. Knowledge Curator gains `salesforce-readonly/review_soql_query` as its only org
  surface (role-guard terminal denials unchanged).
- Envelope schema: `facts.soqlQuery` slimmed to queryDigest/fromObjects/useToolingApi/
  matched/records; missing-LIMIT overflow now surfaces as INCOMPLETE/RESULT_TRUNCATED
  instead of a server-side LIMIT rewrite.
- Related: output/discovery-2026-08-04-soql-unblock.md (decision record, layer map, accepted
  risks, out-of-scope follow-ups: salesforce_read.py retirement, org-sampling ceremony).

## 2026-08-04 — salesforce_read.py CLI lane retired (redundant after the SOQL unblock)

- Owner directive (chat, 2026-08-04, follow-up to the SOQL unblock): remove the redundant
  script, its test, and every reference. `scripts/salesforce_read.py` (records/retrieve/orgs)
  and `tests/test_salesforce_read.py` are deleted.
- Rationale: with `review_soql_query` unblocked, the structured record-read lane was a second,
  CLI-transport path to the same rows — exactly the parallel-lane rot the v1 retirement warned
  about. `orgs` was a twin of `review_configured_orgs`; `retrieve` cached metadata agents can
  get authoritatively via `review_object_contract` facts or the human-confirmed
  `sf project retrieve start`.
- Layers removed with it: role-guard SALESFORCE_READ_* surface + dispatch, the auto-approve
  regex in `.vscode/settings.json`/`sf-harness.code-workspace`, the `salesforce-read` preflight
  capability (choices + role-guard mirror), validate_harness required-file + guarded-name pins,
  and the config key `review.maxObjectsPerCall` (schema-optional now, read by nothing; removed
  from the example config, tolerated in existing local configs).
- Negative pins added: the script must not reappear (guard-parser contract), the old command
  shape denies for every role (safety-hook tests), the guard surface must not resurface
  (receipt-gate tests).
- Agent-facing text now routes record reads to `review_soql_query`; investigate-config-records
  snapshots run their SELECT through the facade (explicit field list, never Id, LIMIT 200,
  ORDER BY natural key) — the skill's own sanitization rules are unchanged.
- Gate: validate_harness 2594 checks PASS, 966 unit tests OK (1 skip), run_evals 38/38.

## 2026-08-04 — Over-engineering slimming wave 1 (owner AskUserQuestion decisions)

Owner picked, from the 2026-08-04 over-engineering review: (A) dev-tool batch approval
pipeline DELETED entirely; (B) SAFE-HUMAN-001 kept at two layers — global safety hook +
in-process work_record backstop (role-guard special-case and settings.json deny regexes
removed); (C) knowledge benchmark REMOVED from CI entirely (stays a local script);
(D) rule-registry.yaml retired — rule IDs validate against .github/copilot-instructions.md
directly. Each lands as its own commit with the full gate.

### A — dev-tool batch pipeline deleted
- Gone: scripts/approve_dev_tool_batch.py, schemas/dev-tool-batch.schema.json,
  .cache/devtool-batches/, hook surfaces (DEVTOOL_BATCH_*, devtool_entry_digest,
  consume_devtool_batch_entry, approve-script deny trap), the role-guard write prefix,
  the eval scenario, validator pins, and both DevToolBatch test classes.
- Kept on purpose: the dev-tool CLASSIFIER and the per-invocation SAFE-HUMAN-001 ask —
  a mutating dev tool now always stops for its own confirmation. That is the whole cost:
  one click per call on the human-started, macOS-only dev lane (Windows fleet never could
  start it).
- safety.batchDevToolApproval: schema-tolerated with a "retired, read by nothing"
  description (existing local configs stay valid); removed from the example config.
- Pins: mutating dev tool always asks; pipeline surfaces must not resurface.

### B — SAFE-HUMAN-001 deduplicated to two layers
- Kept: the global safety hook (primary wall, incl. the knowledge approve trap) and the
  in-process SF_HARNESS_AGENT_CONTEXT backstop in work_record.py (catches non-Copilot agent
  contexts).
- Removed: the explicit `"approve": false` regex entry in .vscode/settings.json +
  code-workspace (the allow-patterns' `(?!approve\b)` lookahead still leaves the click to a
  human — validate_harness now pins "nothing auto-approves" instead of "an explicit deny
  exists"), and the guard's `command == "approve"` special-case (set membership already
  excludes it; outcome pin test_work_record_approve_stays_unreachable_for_every_role stays).

### C — knowledge benchmark removed from CI (stays a local tool)
- The harness-ci.yml budget step (3000-entry fixture, 21 cold processes per budgeted command,
  both matrix legs, the dominant cost of the 16-18 min Windows leg) is gone; the owner chose
  full removal over a smoke bound. knowledge_benchmark.py keeps its budget constants as the
  local reference; its docstring says local-only. Pin inverted:
  test_the_benchmark_gate_stays_out_of_ci.

### D — rule-registry.yaml retired; rules resolve from the Principle sources
- The 20KB registry gave 50 rules identical boilerplate metadata (all active/complete,
  review: null) and existed so attach-rule could bind a ruleRef. Now
  work_record.resolved_rule_ref scans the four Principle sources for the bolded
  `**<ID> — …**` declaration line; the tier derives from WHICH file declares the rule
  (RULE_SOURCE_TIERS: kernel/1/2/3). ruleRef loses registrySha256 (change-record + handoff
  schemas updated); sourceSha256 still pins the text the rule was checked against.
- validate_harness pins the invariant that keeps resolution unambiguous: every rule ID is
  declared exactly once across the sources. principle-registry.schema.json deleted;
  MP-REG-001 reworded (declared, not registered); check-against-principles loads the
  instruction files; CODEOWNERS row dropped.
- Retirement pins: registry file and schema must not return
  (test_rule_ids_declare_exactly_once_and_the_registry_stays_retired).

## 2026-08-04 — Deps hygiene: 18 Dependabot alerts cleared by a lockfile refresh; audit gate tightened to high

- All 18 open alerts (brace-expansion ×6 DoS, undici ×5, ip-address ×3, postcss ×2,
  fast-uri, hono) were transitive and IN-RANGE: one `npm update undici ip-address fast-uri
  hono brace-expansion postcss` cleared every high/moderate they raised — undici 8.10.0,
  ip-address 10.4.0, fast-uri 3.1.5, hono 4.13.0, postcss 8.5.25, brace-expansion
  1.1.18/2.1.4/5.0.9. The @salesforce/mcp@0.30.15 + provider 0.9.8 pins and the overrides
  block are untouched; lockfile-only diff.
- Reachability (discovery output/discovery-2026-08-04-dependabot-alerts.md): nothing was a
  live exploit path — hono/ip-address sit in the MCP SDK's HTTP transport (we spawn stdio),
  postcss/brace-expansion are dev-tooling, undici talks only to the identity-proven org.
- CI npm-audit gate tightened `--audit-level=critical` → `high` (prod tree is now clean at
  high; moderate stays non-blocking by design).
- Accepted residual, documented in the workflow comment: moderate fast-xml-parser advisory
  (<5.7.0) on a 4.x copy nested under the MCP code-analyzer provider — unfixable in range
  from this repo.

## 2026-08-04 — Validator crash-class hardening (deep-test gap fix)

- Context: a 39-case mutation test of `scripts/validate_harness.py` (driver kept in the
  builder workspace, findings in `output/deep-test-2026-08-04-validate-harness.md`)
  confirmed 25 inputs where a malformed file raised an uncaught traceback through a
  `check_*` function. `Audit.require` collects without aborting, so the crash discarded
  every already-collected finding; exit stayed 1 (no false-green) but the report was
  lost. Worst case (C6): the lazy `from scripts.knowledge_digest import canonical_digest`
  in `check_org_usage` fails with ModuleNotFoundError under `python
  scripts/validate_harness.py` — the CI invocation — the moment `.ai/knowledge/artifacts/`
  exists, i.e. on the first org-bearing clone (org-usage Phase 4). Latent here only
  because the public origin has no artifacts directory.
- Finding / decision: full hardening set (owner choice over a minimal wrapper-only
  variant): (1) `run_checks` wrapper in `main()` converts any check crash into a named
  audit error, traceback to stderr, remaining checks keep running; (2) C6 import moved
  to the header with the existing dual-mode fallback, so direct-run CI exercises it
  every run; (3) guarded reads — `required_text` helper at ~13 named-file reads,
  OSError handling in `frontmatter()`/`load_jsonc()`; (4) parse guards in
  `plan_consumer_set`, the negative-fixture patch loop (`apply_patch` helper), and the
  development-assistant frontmatter read (now the shared helper); (5) tools/hooks
  frontmatter guards in `check_customizations` (`array of tool-name strings`,
  `json.dumps(..., default=str)`); (6) `check_placeholders` skips undecodable files like
  every other full-tree scanner; (7) missing dev dependency now prints the remedy
  (.venv / requirements-dev.lock) instead of a bare ImportError.
- Impact: post-fix driver rerun: 0 crashes — 37/39 clean FAIL reports with attributable
  errors, 2 designed PASSes (binary asset skipped; foreign-cwd run). Pristine repo:
  PASS 2561 checks; suite 975 tests OK; evals 37 PASS. New
  `tests/test_validate_harness.py` (15 tests) pins the wrapper, the no-lazy-`scripts.*`
  -import rule (AST scan), guarded reads, and the hostile-frontmatter cases. Deliberately
  NOT hardened per-site: every remaining type-blind `.get()` (the wrapper subsumes them);
  a stray binary under `.github/` is by decision not a defect.
- Approved by: owner (chat, 2026-08-04; depth question answered "full set").
- Related: output/deep-test-2026-08-04-validate-harness.md (untracked research doc),
  tests/test_validate_harness.py, docs/grounding-architecture.md (unchanged semantics).

## 2026-08-04 — Org gates slimmed to read-anywhere + deniedOrganizationIds

- Context: live failure — MCP startup blocked on a Developer Edition alias by the
  launcher's startup identity subprocess (which also silently killed the verifier at 30 s
  against its legitimate 2×60 s budget, misreporting cold-start latency as identity
  failure). A mechanics map showed `allowAgentWrite` dead (write lane unreachable four
  ways), `allowAgentRead`/`allowAgentReview` only ever checked as a pair and bypassed
  under `allowAnyNonProduction`, and the facade already re-proving live non-production
  identity on every tool call.
- Finding / decision (owner, chat): which org a developer connects is the developer's
  responsibility. Retired: the three per-org `allowAgent*` flags, the
  `allowAnyNonProduction` toggle (dynamic lane is the unconditional default), the
  launcher's development/write mode and its startup `verify_salesforce_org.py` spawn,
  `preflight --capability salesforce-write`, and the manifest-wildcard gate. Added, as
  the owner's one required dependency: `salesforce.review.deniedOrganizationIds` — org
  IDs refused at live proof time in both facade legs (`ORG_ID_DENIED`) and in
  verify/preflight, matched on the 15-character prefix. Identity pins became optional
  (both-or-neither; lone pin is CONFIG_INVALID). Supersedes the 2026-07-31
  allowAnyNonProduction decision and the 2026-08-04 "Kept: … identity proof" line as far
  as the STARTUP proof goes — the per-call facade proof it praised is exactly what
  remains. D-4 unchanged: Knowledge org-attach still requires the configured
  `expectedOrganizationId`; work records still require a configured entry (dynamic
  receipts refused).
- Impact: minimal org entry is `{alias, environment}`; unlisted aliases readable on live
  proof; production refusal unchanged (alias pattern, environment marker, per-call
  host/IsSandbox signature, `nonProduction` receipt fact; SAFE-ENV-001 reworded off
  "exact allowlisted"). retrieve-start allowance re-keyed to configured non-production
  entry. Schema tolerates retired keys in old configs. Gate: 977 unit tests OK, 37/37
  evals, validator green (modulo the unrelated local IMPLEMENTATION_HANDOFF.md
  deletion); live devmp end-to-end VERIFIED through launcher → facade →
  review_org_identity. Full write-up: output/discovery-2026-08-04-org-gate-slimming.md.
- Approved by: owner (chat, 2026-08-04; option "full cut + org-id denylist").
- Related: entries 2026-07-31 (any non-production reads), 2026-08-04 (composed-SOQL
  blockade removed), .ai/contracts/tool-capabilities.md, SETUP.md §3.
