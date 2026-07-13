# Keywords Map

Human-curated map of Test Case ID → keywords, maintained by the `tune-test-case-keywords`
skill (admin prompt `/tune-test-case-keywords`), with a human approving every change. Kept
**separate** from the auto-synced `test-cases/*.md` files on purpose: those are machine-written
and overwritten on every `/sync-test-cases`; this file is curated and must survive syncs
(docs/archive/HARNESS_BLUEPRINT.md sections 3 and 13).

Rules:

- Keywords come **only** from `.ai/knowledge/keyword-taxonomy.md`. A term outside the taxonomy
  requires explicit human consent to extend the taxonomy first — never a silent addition.
- Consulted as the **first-priority signal** by `suggest-test-cases` (hard match beats fuzzy
  model reasoning).
- Orphan risk: if a Test Case disappears from a sync, its entry here becomes orphaned —
  `sync-test-cases` checks for this and reports it explicitly; it never silently deletes or
  ignores an orphan.

## Entry format (template — copy for each new entry)

```
### <Test Case ID>
- Keywords: <list of terms from keyword-taxonomy.md>
- Last curated: <date>, approved by: <who>
```

---

<!-- No entries yet. Entries are added only via /tune-test-case-keywords with human
confirmation — never fabricated at build time. -->
