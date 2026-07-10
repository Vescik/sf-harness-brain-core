---
name: tune-test-case-keywords
description: Admin curation of the Test Case → keywords map, human-in-the-loop — the model suggests candidates from the controlled taxonomy, the human approves every change; a term outside the taxonomy requires explicit consent to extend it.
---

# Skill: tune-test-case-keywords

The actual procedure behind the **admin** prompt `/tune-test-case-keywords` (blueprint
section 11) — a curation tool with a human confirming every change, deliberately separate from
the developer-facing prompts. `suggest-test-cases` never requires this to have been run — it
works uncurated from day one, just with lower match confidence.

## Procedure

1. **Fetch the Test Case's title/description** from `.cache/test-cases/<id>.json`. (If it is
   not cached, that suggests the suite was never synced — point the human at
   `/sync-test-cases` rather than fetching ad hoc.)
2. **Suggest candidate keywords from the existing `.ai/knowledge/keyword-taxonomy.md`** — the
   same model reasoning as in `suggest-test-cases`, just in the opposite direction (text →
   taxonomy term, not term → text).
3. **The human confirms, corrects, or rejects.** Nothing is written without confirmation.
4. **If the human wants a term outside the taxonomy** — ask explicitly whether to extend
   `keyword-taxonomy.md`. **Never add a new term silently** (blueprint section 3: uncontrolled
   vocabulary growth recreates exactly the chaos the taxonomy exists to prevent). The taxonomy
   grows only through this explicit consent.
5. **Write the approved keywords** to `.ai/qa/keywords-map.md` in its documented entry format
   (Test Case ID, keywords, last-curated date, who approved). This file is human-curated and
   survives syncs — `sync-test-cases` never overwrites it.
