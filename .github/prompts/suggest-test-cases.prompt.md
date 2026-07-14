---
name: suggest-test-cases
description: Rank existing synced Test Cases relevant to one structured change using taxonomy evidence and bounded reasoning.
argument-hint: "itemId=<ADO ID> [recordId=<ID>]"
agent: test-strategist
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*']
---

Use the [suggest-test-cases skill](../skills/suggest-test-cases/SKILL.md).

Require one numeric `itemId` (ask once with `#tool:vscode/askQuestions` if missing). Rank only
Test Cases from the current synced inventory; if the cache is stale or missing, stop and run
`/sync-test-cases` first instead of guessing.

Suggestions are advisory relevance ranking, never formal coverage — coverage verdicts belong to
`/feature-health`. Return the ranked cases with the taxonomy/artifact evidence behind each, the
negative evidence considered, and the inventory freshness. Attach results to the work record only
when the caller provided `recordId`.
