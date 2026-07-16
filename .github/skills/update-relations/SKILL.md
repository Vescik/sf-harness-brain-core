---
name: update-relations
description: Repo-wide incremental sweep proposing governed object-relation/component-relation claims for every reference edge not yet captured, reusing the deterministic claim-ID/reconciliation mechanism so reruns only touch what's new since the last run.
user-invocable: false
---

# Update relation claims

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md), and the
[propose-force-app-knowledge skill](../propose-force-app-knowledge/SKILL.md) (its source
boundaries and chat-approval mechanics apply here). Requires the `config-investigator` role.

Unlike `batch-knowledge`, this is not a five-phase workflow: relation claims are purely structural
(`assurance: observed` for structural edges, `inferred` for Apex source-token heuristics) and carry
no `<AGENT_...>` description sentinel to author. There is no judgment call in deciding *what* to
propose — everything `relations-worklist` reports `missing` is the plan — so the batch-knowledge
PLAN/VERIFY PLAN phases collapse into one read-only discovery step. The only genuine judgment left
is how many approval clicks the human wants to spend per run.

## Phase 1 — DISCOVER

1. Run `python scripts/preflight.py --capability metadata` and
   `python scripts/force_app_knowledge.py inventory`. Stop on a dirty tree or partial inventory.
2. Run `python scripts/force_app_knowledge.py relations-worklist --write` (optionally
   `--metadata-type <Type>` to scope one type at a time). Report the counts by state — `missing`,
   `proposed`, `verified-current`, `verified-stale`, `blocked`. If `missing` is very large (several
   hundred or more), say so explicitly before drafting anything: consider scoping the run to one
   `--metadata-type` at a time rather than sweeping the whole repository in one pass, purely for
   review-batch ergonomics — there is no correctness reason to scope, only a human-attention one.
3. Confirm `knowledge.chatReviewer` is configured; without it, promotion cannot complete and the
   sweep should not start.

## Phase 2 — EXECUTE (repeat until zero `missing`)

1. `python scripts/force_app_knowledge.py relations-draft --limit <N>` (default 200; the registry
   role guard caps `--limit` at 2000). By default this **excludes source-token-heuristic edges**
   (Apex `object-token`/`queries-object`/`invokes-class` — the highest-noise, `assurance: inferred`
   source); pass `--include-heuristic` only once the high-confidence structural edges are clear, and
   present heuristic-derived claims in their own visually separated batch so the human gives them
   the extra scrutiny their lower assurance warrants.
2. No description-writing step: every drafted relation claim is already complete. Propose them with
   the manifest's `propose` commands (the registry re-validates and reconciles; a true duplicate is
   rejected, not silently absorbed — this should not happen for a `missing`-derived candidate, since
   its claim ID is deterministic and wasn't on disk yet, but treat a rejection as a stop-rule event
   and report it rather than retrying blindly).
3. Request promotion in batches of up to 25 via
   `python scripts/knowledge_registry.py approve-claim --claim-spec <id>:<rev> --claim-spec ...`
   (the existing hard cap on that mechanism). Present each batch as a scannable table — source
   component, predicate, target, heuristic true/false — so the human's one confirmation click is
   informed, not blind.
4. Re-run `relations-worklist` and report progress from its counts. Repeat from step 1 until
   `missing` is zero (or the caller stops the sweep deliberately).

Every `draft`/`relations-draft` call clears `.cache/knowledge-proposals/force-app-drafts/` first —
do not interleave an `update-relations` run with an in-progress unrelated `batch-knowledge` batch.

## Phase 3 — VERIFY

1. Re-run `relations-worklist` — confirm `missing` is zero (or explain what remains and why).
2. `python scripts/knowledge_registry.py render-indexes --check` must pass.
3. Write a report to `output/documentation/update-relations-<date>.md`: scope, batches executed,
   claims created/verified/rejected, heuristic-derived claims called out separately, and follow-ups.
   The report is a draft artifact for human review, not canonical Knowledge.

## Prohibitions

- Never treat `relations-draft`'s default heuristic exclusion as optional busywork to skip — Apex
  source-token edges are the least reliable signal in this system; propose them only with the
  extra scrutiny this skill calls for.
- Never propose a relation claim outside the deterministic identity scheme `relation_candidates()`
  produces; never hand-author a relation claim's `subject.identity` or `assertion.value`.
- Never mark an orphaned relation claim `stale` from this skill — that is
  [relation-health](../relation-health/SKILL.md)'s read-only report plus a separate human-governed
  `review`/`promote` step, not part of this sweep.

## Return

Return `COMPLETE`, `PARTIAL`, or `BLOCKED`; the metadata-type scope (if any); counts by state
before/after; claim/review IDs per batch; heuristic-flagged claims called out separately; the
report path; and every stop-rule event with its phase.
