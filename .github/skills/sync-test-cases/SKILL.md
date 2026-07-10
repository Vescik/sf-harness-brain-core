---
name: sync-test-cases
description: Sync Test Cases from Azure Test Plans into the local QA layer — accepts a link, a Suite ID, or a Plan ID (all suites); writes a lightweight committed index per suite and reports orphaned keywords-map entries.
---

# Skill: sync-test-cases

The actual procedure behind the `/sync-test-cases` prompt (blueprint section 11). Two-tier
storage (blueprint section 3): full detail (steps, expected results) goes to
`.cache/test-cases/<id>.json` — a pure mirror of ADO, not versioned, ADO stays the source of
truth; the lightweight index goes to `.ai/qa/test-cases/`, committed, a shared team resource.

## Procedure

1. **Parse the input** — one of three equivalent forms:
   - a link to Azure Test Plans → extract `suiteId` / `planId` from it;
   - a direct `suiteId`;
   - a `planId` only → **enumerate all suites in that plan**, then repeat the rest of this
     procedure for each suite in a loop. The file structure (one file per suite) handles this
     without changes — it simply produces more files at once.
2. **List Test Case IDs in the suite** via the Test Plans API (Plan → Suite → Test Case is a
   separate API model from work-item relations).
   <!-- TODO(verify): exact tool names in the test-plans domain — blueprint section 14. -->
3. **For each ID, call the `fetch-test-case` skill** — the cache updates itself as a side
   effect.
4. **Write the lightweight index** to `.ai/qa/test-cases/<suiteId>-<name>.md` — ID, title,
   priority/tags if available, last-synced timestamp (`_fetchedAt` from cache); **no full
   steps** (those stay in cache). Entry format per `.ai/qa/test-cases/README.md`. These files
   are machine-written and overwritten on every sync.
5. **Orphan check**: scan `.ai/qa/keywords-map.md` for entries pointing at Test Cases that no
   longer exist in the freshly fetched list. **Report any orphaned entries explicitly** — never
   delete them silently, never ignore them; the keywords map is human-curated and only a human
   removes its entries.
