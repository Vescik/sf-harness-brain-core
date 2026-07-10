# QA Test Case Index — `.ai/qa/test-cases/`

Lightweight, committed index of Test Cases synced from Azure Test Plans. Written and
overwritten by the `sync-test-cases` skill — treat these files as machine-generated: do NOT
hand-edit them (hand-curated data belongs in `../keywords-map.md`, which sync never touches).

**Naming convention**: one file per Test Suite, named `<suiteId>-<name>.md` — the suite is a
natural boundary from day one, so the split is per-suite immediately, not threshold-based like
the Knowledge object files (HARNESS_BLUEPRINT.md sections 3, 5 and 13).

**Entry format inside each suite file** (index only — full steps and expected results stay in
`.cache/test-cases/<id>.json`, mirrored from ADO, which remains the source of truth):

```
### <Test Case ID> - <Title>
- Priority / tags: <if available in ADO>
- Last synced: <_fetchedAt from cache>
```

<!-- No suite files yet. They are produced only by a real /sync-test-cases run — never
fabricated at build time. -->
