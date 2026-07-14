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
3. Query existing Knowledge for the type to avoid rework:
   `python scripts/knowledge_registry.py query --subject-kind <kind> --claim-type <type>` for the
   applicable claim types (structural + `component-description`). Classify each component:
   `new` (no claims), `refresh` (claims stale/expired/superseded by source changes), or
   `current` (verified and fresh — skip by default).
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
   facts only).
3. Propose the chunk's claims with the manifest `propose` commands (the registry re-validates,
   reconciles, and rejects unfilled sentinels).
4. Request promotion for the chunk in ONE command so the human confirms once per chunk:
   `python scripts/knowledge_registry.py approve-claim --claim-spec <id>:<rev> --claim-spec ...`
   (max 25 specs). Rejected or failed items stay proposed — record them and continue with the
   next chunk unless a stop rule fired.
5. After each chunk, report progress: chunk n/N, claims proposed/verified/failed.

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
