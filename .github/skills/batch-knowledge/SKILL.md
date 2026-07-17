---
name: batch-knowledge
description: Five-phase batch conversion of one metadata type into governed Knowledge - discover the component set and existing claims, plan chunked work, verify the plan with the human, execute draft/describe/propose/chat-approve per chunk, and verify the resulting Knowledge. One metadata type per batch.
user-invocable: false
---

# Batch Knowledge workflow

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md), and the
[propose-force-app-knowledge skill](../propose-force-app-knowledge/SKILL.md) (its source
boundaries, description rules, and chat-approval mechanics all apply here).

Requires the `config-investigator` role. Exactly one metadata type per batch — never mix types
(e.g. Flow and CustomObject) in one run. The workflow is a loop, not a line: a failed
verification returns to the phase that produced the defect.

## Phase 1 — DISCOVER

1. Run `python scripts/preflight.py --capability metadata` and
   `python scripts/force_app_knowledge.py inventory`. Stop on a dirty tree or partial inventory —
   report the exact diagnostics instead of proceeding.
2. From the inventory `coverage` map, confirm the requested type exists and note its component
   count. If it is absent, list the available types and stop.
3. Derive the batch worklist from ground truth:
   `python scripts/force_app_knowledge.py worklist --metadata-type <Type> --write`. It joins the
   inventory, current drafts, and canonical claims into one status per component — `pending`,
   `drafted`, `proposed`, `verified-current` (skip by default), `stale-refresh` (source changed
   after verification), or `blocked` (rejected/contested/superseded claims; report, never
   overwrite). The written file under `.cache/knowledge-proposals/` is a derived view for the
   human — the registry stays the source of truth, so rerunning the command can never disagree
   with reality. Use `python scripts/knowledge_registry.py query` only for drill-downs the
   worklist does not answer.
4. Confirm `knowledge.chatReviewer` is configured; without it promotion cannot complete and the
   batch should not start.

## Phase 2 — PLAN

Produce a batch plan the human can read in one screen:

- component list with disposition (new / refresh / skip-current) and the claims each will
  produce (structural + description where behavior-bearing);
- chunking: components per chunk (default 10, max 25 — the chat-approval batch cap), chunk order
  (alphabetical unless the human reorders), and the expected number of approval clicks
  (one per chunk);
- stop rules: dirty tree, propose failure, reconciliation conflict, or a description you cannot
  ground in source — each pauses the batch and reports, never improvises.

## Phase 3 — VERIFY PLAN

1. Re-check the tree is still clean at the inventory commit.
2. Reconcile the plan against the registry: no chunk may duplicate an active claim
   (`reconcile` on a sample or rely on propose-time reconciliation with the stop rule).
3. Present the plan and ask the human explicitly (one `#tool:vscode/askQuestions` call): approve
   the plan, change chunking/scope, or cancel. Do not execute without this go-ahead.

## Phase 4 — EXECUTE (per chunk, in order)

1. `python scripts/force_app_knowledge.py draft --metadata-type <Type>` — drafts regenerate for
   the whole type; work through them chunk by chunk.
2. For every behavior-bearing draft in the chunk: read the component's actual source and replace
   the `<AGENT_...>` description sentinel per the propose skill's rules (2–6 sentences, source
   facts only), and refine `candidateKeywords` (0–5 terms; drafts arrive pre-seeded from the usage
   registry — keep the apt ones, add source-grounded business-process/feature terms; advisory only,
   `keywords` stays taxonomy-approved terms).
3. Propose the chunk's claims with the manifest `propose` commands (the registry re-validates,
   reconciles, and rejects unfilled sentinels).
4. Request promotion for the chunk in ONE command so the human confirms once per chunk:
   `python scripts/knowledge_registry.py approve-claim --claim-spec <id>:<rev> --claim-spec ...`
   (max 25 specs). Rejected or failed items stay proposed — record them and continue with the
   next chunk unless a stop rule fired.
5. After each chunk, re-run
   `python scripts/force_app_knowledge.py worklist --metadata-type <Type> --write` and report
   progress from its counts: chunk n/N, components pending/proposed/verified-current, plus any
   claims that failed their propose or approval step.

### Resume rule

An interrupted batch (crash, closed session, stop rule) needs no saved progress state. On
restart: rerun `inventory`, then `worklist --metadata-type <Type>`. Components already
`verified-current` are done — skip them; `proposed` components only need their approval step;
continue executing from the first `pending` or `drafted` component. Never reconstruct progress
from chat history or a hand-maintained checklist — the derived worklist is recomputed from the
registry and cannot drift.

## Refresh mode (drift + expiry maintenance)

Use refresh mode when the batch goal is keeping existing Knowledge current rather than
documenting new components — the store decays without it: every verified claim stops being
effective at its `reviewBy` deadline, and `stale-refresh` components hold claims whose source
changed after verification.

1. DISCOVER: `python scripts/force_app_knowledge.py refresh --dry-run --warn-days 30`
   (optionally `--metadata-type <Type>`). The selection lists each claim with its reason —
   `drift` (source changed), `expired` (past reviewBy), `expiring` (within the warn window) —
   plus `remaining` when the `--limit` cap truncated the sweep. `python scripts/knowledge_registry.py
   stale-report` gives the registry-wide expiry view when scoping the run.
2. VERIFY PLAN: present the dry-run selection to the human exactly like a batch plan (counts by
   reason, expected approval clicks) and get the explicit go-ahead.
3. EXECUTE: `python scripts/force_app_knowledge.py refresh` with the same filters. Drafts land in
   the same workspace with disposition `refresh-verified`, and their manifest `propose` commands
   carry `--refresh-verified` — the explicit acknowledgement that a verified/stale claim is being
   demoted to a new proposed revision against current evidence. Fill description sentinels and
   propose/approve per chunk exactly as in Phase 4. Until re-approval the refreshed claims are
   `proposed` and not effective — schedule the run so the approval step follows promptly.
4. VERIFY: rerun `refresh --dry-run` — a clean pass selects nothing (or only the `remaining`
   overflow for the next run) — then continue with Phase 5 as usual.

## Phase 5 — VERIFY

1. Query the registry for the type again and compare against the plan: every planned component
   has its expected claims `verified` (or an explained exception).
2. `python scripts/knowledge_registry.py render-indexes --check` must pass.
3. Write a batch report to `output/documentation/batch-knowledge-<Type>-<date>.md`: scope,
   chunks executed, claims created/verified/rejected/failed, skipped-current components, and
   follow-ups. The report is a draft artifact for human review, not canonical Knowledge.

## Return

Return `COMPLETE`, `PARTIAL`, or `BLOCKED`; the type and component counts per disposition;
claim/review IDs per chunk; the report path; and every stop-rule event with its phase.
