---
name: search-knowledge
description: Search governed Knowledge by subject, keyword, or text; effective verified facts are reported separately from non-effective records.
argument-hint: "keyword=<term> | text=<fragment> | subject=<identity> [domain=<domain>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [search-knowledge skill](../skills/search-knowledge/SKILL.md).

Require at least one filter (`keyword`, `text`, or `subject`; ask once with
`#tool:vscode/askQuestions` if none was given) and pass the rest through as narrowing filters.

This command is read-only: it never creates, promotes, or edits Knowledge. Present effective
verified facts first, then non-effective matches with their reasons, and finish with gaps worth
investigating (`/investigate-object`) or drafting (`/propose-force-app-knowledge`).
