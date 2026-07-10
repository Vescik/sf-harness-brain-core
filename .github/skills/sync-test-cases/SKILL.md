---
name: sync-test-cases
description: Synchronize an allowlisted Azure Test Plan or Suite into deterministic committed QA indexes, with pagination, partial-run reporting, and global orphan candidates. Use internally from the public sync prompt or Test Strategist.
user-invocable: false
---

# Sync Test Cases

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and run
`scripts/preflight.py --capability ado`.

## Input

Accept exactly one scope:

- configured HTTPS Test Plans URL; or
- positive `suiteId` plus its `planId`; or
- positive `planId` for all suites.

Reject zero/multiple forms, arbitrary hosts, a mismatched organization/project, or path traversal.
Confirm before a plan-wide sync above the configured suite/case limit.

## Procedure

1. List suites when the scope is a plan; continue all pages and record continuation/partial state.
2. List Test Case IDs for each suite, then call `fetch-test-case` with `onStale=refresh`.
3. Sanitize suite names to a deterministic slug and write one sorted index to
   `.ai/qa/test-cases/<suiteId>-<slug>.md`. Use atomic replacement only after that suite succeeds;
   retain the previous index on partial failure.
4. Include schema version, plan/suite IDs, source revision/timestamp, retrievedAt, completeness, and
   each Case's ID/title/priority/tags. Full steps stay in ignored cache.
5. Deduplicate a Case within an index. A Case may legitimately appear in several suites.
6. Compute orphan candidates against the union of every successfully refreshed in-scope index
   plus direct ADO existence—not absence from one suite. Report; never delete curated keywords.

## Return

Report suites/cases requested, completed, unchanged, failed, and partial; files written/retained;
orphan candidates; pagination; and a rerun/resume action.
