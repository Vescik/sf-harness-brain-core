---
name: search-knowledge
description: Search governed Knowledge - approved one-file Entries and their org-usage blocks; effective facts are reported separately from non-effective records.
argument-hint: "keyword=<term> | text=<fragment> | subject=<identity> | anchor=<Identity> | error=<pasted message> [type=<MetadataType>] [namespace=<ns>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [search-knowledge skill](../skills/search-knowledge/SKILL.md).

Require at least one filter (`keyword`, `text`, `subject`, `error`, or a dependency lookup
via `anchor=<Identity>` — the skill's `--relation-anchor` search; ask once with
`#tool:vscode/askQuestions` if none was given) and pass the rest through as narrowing filters.

Route by question type: repository-source facts (what a component declares, what touches a field,
which Flow emits a pasted message) come from approved Knowledge Entries; org usage numbers come
from unexpired entry `orgUsage` blocks; org state beyond that needs a fresh governed receipt,
and business meaning or vendor guarantees have no governed Knowledge surface — report the gap
honestly instead of inferring. Never present a stale index or a missing hit as proof of absence.

This command is read-only: it never creates, promotes, or edits Knowledge. Present effective
facts first, then non-effective matches with their reasons, and finish with gaps worth
investigating (`/investigate-object`) or drafting (`/pin-knowledge`, `/curate-knowledge`).
