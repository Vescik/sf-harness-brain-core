---
name: tune-test-case-keywords
description: Curate one Test Case keyword mapping with a named human approver, current Case evidence, controlled taxonomy, deterministic upsert, and separate approval for taxonomy growth. Use only through the admin prompt.
user-invocable: false
---

# Tune Test Case keywords

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

## Inputs

Require positive `testCaseId`, named approver, current date, and a fresh full Test Case cache entry.
If missing/stale, call `fetch-test-case`; 404/deleted requires an orphan decision, not curation.

## Procedure

1. Show the current Case title/description and existing map entry.
2. Suggest specific existing taxonomy terms with evidence and counter-evidence. Never invent a term.
3. Show the exact deterministic upsert diff (one entry per Test Case, sorted unique keywords).
4. Ask the human to approve/reject/edit the map update. No approval means no write.
5. If a requested term is absent, separately show the taxonomy definition/synonyms and ask whether
   to extend the taxonomy. Approval of one write does not approve the other.
6. Re-read both files before writing to detect concurrent changes. Apply approved edits atomically,
   preserve unrelated entries, and record approver/date.

## Return

Return approved/rejected actions, exact files/terms changed, concurrent-change status, and any
remaining orphan/taxonomy question.
