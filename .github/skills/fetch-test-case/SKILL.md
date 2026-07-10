---
name: fetch-test-case
description: Fetch one specific Test Case with cache-first logic via the Azure Test Plans API. Returns full detail (steps, expected results).
---

# Skill: fetch-test-case

Extracted from `sync-test-cases` for reuse — the same moment as with `fetch-ado-item`
(blueprint section 3, reusability rule): `sync-test-cases` calls this in a loop over a whole
suite; `generate-playwright-test` calls it once, directly, for a single ID.

## Procedure

1. **Cache first.** Check `.cache/test-cases/<id>.json` and its `_fetchedAt` field (never
   filesystem mtime). Fresh → return it without a fetch. Stale → say so explicitly and ask
   whether to refresh — never silently serve stale data.
2. **Fetch via the Test Plans API** (Azure DevOps MCP, `test-plans` domain — a different API
   model than work-item relations, which is why the `work-items` domain does not cover this).
   <!-- TODO(verify): exact tool names in the test-plans domain of the ADO MCP server —
   blueprint section 14 flags them as unverified at build time. -->
3. **Write to cache**: `.cache/test-cases/<id>.json` with `_fetchedAt`.
4. **Return full detail** — steps, expected results, title, priority/tags if available. Like
   `fetch-ado-item`, this returns a context structure for the consumer, not a human-facing
   answer.
