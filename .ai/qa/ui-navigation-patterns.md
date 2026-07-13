# UI Navigation Patterns

UI quirks discovered during test automation by the `generate-playwright-test` skill — recorded
so the same quirk is never re-discovered from scratch, and so different generated tests handle
it consistently (docs/archive/HARNESS_BLUEPRINT.md sections 3 and 13). Same mechanism as the rest of
Knowledge: once discovered, written down, not re-derived.

Live navigation via Playwright still happens on every generation (it gives verified,
current selectors) — this file complements it with the non-obvious behaviors live navigation
alone would keep tripping over (e.g. "the default list view filter is Recently Viewed, switch
to All first").

New entries: when `generate-playwright-test` discovers an undocumented quirk, it **suggests**
adding it here — the same suggest-then-confirm habit as the rest of the harness.

## Entry format (template — copy for each new entry)

```
### <Object / page>
- Quirk: <e.g. "default list view filter is Recently Viewed, must switch to All">
- Correct procedure: <concrete workaround steps>
- Discovered: <date>, during test: <which Test Case / conversation>
```

---

<!-- No entries yet. Entries are added as quirks are actually discovered during automation —
never fabricated at build time. -->
