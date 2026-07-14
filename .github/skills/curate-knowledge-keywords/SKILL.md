---
name: curate-knowledge-keywords
description: Curate the Knowledge keyword taxonomy from aggregated candidateKeywords - run the deterministic keyword report, present ranked candidate terms with their claims, and add only terms the human explicitly confirms. Taxonomy growth is never silent; verified claims are never rewritten.
user-invocable: false
---

# Curate Knowledge keywords

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
growth rule of [`.ai/knowledge/keyword-taxonomy.md`](../../../.ai/knowledge/keyword-taxonomy.md):
the taxonomy grows **only through explicit human confirmation** — never add a term silently.

## Inputs

Require a named human approver present in chat. Candidate terms come only from
`candidateKeywords` on canonical claims (filled during description writing); never invent terms
in this session.

## Procedure

1. Run `python scripts/knowledge_registry.py keyword-report`. It aggregates `candidateKeywords`
   across all canonical claims, ranked by frequency, with the claim IDs behind each term and
   whether the term is already approved.
2. Present the ranked candidates: term, count, sample claims, and any existing taxonomy term that
   already covers the concept (a synonym must map to the existing term, not become a new one).
   Preserve Polish business terms verbatim — do not translate them.
3. For each term the human explicitly confirms, add one list item under the `## Terms` heading of
   `.ai/knowledge/keyword-taxonomy.md` in the machine-parsed format
   `- <term> — <one line on what it covers, plus absorbed synonyms>`. One confirmation per term;
   a batch "add them all" needs the human to name the terms it covers. No confirmation means no
   write.
4. Never edit canonical claims in this session. Promotion into a claim's `keywords` happens on
   the claim's next natural revision through the governed propose/approve cycle — the registry
   accepts a `keywords` entry only when it is an approved taxonomy term.
5. Re-read the taxonomy before writing to detect concurrent changes; apply confirmed edits
   atomically and preserve unrelated entries.

## Return

Return the terms confirmed/declined with counts, the exact taxonomy lines added, claims whose
next revision should adopt promoted terms, and any synonym-mapping questions left open.
