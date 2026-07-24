---
name: search-knowledge
description: Search governed Knowledge - approved one-file Entries for repository-source facts and the claim registry for org observations and semantics; effective facts are reported separately from non-effective records.
argument-hint: "keyword=<term> | text=<fragment> | subject=<identity> | uses-object=<Object> | uses-field=<Object.Field> | error=<pasted message> [type=<MetadataType>] [namespace=<ns>] [domain=<domain>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [search-knowledge skill](../skills/search-knowledge/SKILL.md).

Require at least one filter (`keyword`, `text`, `subject`, `error`, or a dependency lookup
`uses-object`/`uses-field`/`invokes`; ask once with `#tool:vscode/askQuestions` if none was given)
and pass the rest through as narrowing filters.

Route by question type: repository-source facts (what a component declares, what touches a field,
which Flow emits a pasted message) come from approved Knowledge Entries; org state, runtime
behavior, business meaning, and package/vendor questions come from the claim registry. Report the
two layers separately with their own citations, and never present a stale index or a missing hit
as proof of absence.

This command is read-only: it never creates, promotes, or edits Knowledge. Present effective
facts first, then non-effective matches with their reasons, and finish with gaps worth
investigating (`/investigate-object`) or drafting (`/propose-force-app-knowledge`).
