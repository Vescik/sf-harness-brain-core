---
name: author-feature
description: Build or refine one Feature Knowledge document interactively — curated topology, claims with honest authority, artifact bindings — and route it to digest-pinned human approval.
argument-hint: "feature slug or name (e.g. invoice-finance)"
agent: knowledge-curator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions', 'knowledge/*']
---

Use the [author-feature skill](../skills/author-feature/SKILL.md).

Parse the invocation as a feature slug (lowercase-hyphen) or a human name to slugify. One
Feature = one canonical document at `.ai/knowledge/features/<slug>/feature.md`; chat is
never state — every accepted step is written through
`python scripts/knowledge_store.py feature-record` and a resumed conversation starts from
the file, not from memory.

You propose from existing Knowledge (resolve → context → entry status); the user decides
what the Feature IS. Graph results are candidates, never members. Never invent an ID,
never mark a technical guess human-attested, and never call heuristic material citable —
the executor enforces all three, so a rejected batch is a correction, not an obstacle.

End with the feature identity, lane, draft version, open questions, and — after review —
the digest-pinned approve command for the human.
