# Keyword Taxonomy

Controlled vocabulary of terms — shared between object descriptions (the optional "Keywords"
field in `.ai/templates/knowledge-entry.md`) and the QA layer (`.ai/qa/keywords-map.md`). Its
purpose: two descriptions of the same thing (e.g. "Billing" vs "Invoicing") resolve to one
shared term once, instead of the model re-guessing synonymy every time
(docs/archive/HARNESS_BLUEPRINT.md section 3).

This file is separately human-curated; it is not a generated claim index. A taxonomy term is never
evidence that an object, field, process, or package behavior exists. Canonical claims may reference
only already-approved terms, and evidence must establish the underlying fact independently.

**Growth rule — the defining property of this file**: the taxonomy grows **only through
explicit human confirmation**. Skills (`tune-test-case-keywords`, `curate-knowledge-keywords`,
`investigate-object`, `suggest-test-cases`) may *suggest* a new term, but may never add one
silently. Uncontrolled vocabulary growth would recreate exactly the chaos this file exists to
prevent.

**Machine-checked contract**: `knowledge_registry.py` parses the list items under `## Terms`
(format: `- <term> — <notes>`) as the approved vocabulary and rejects, at propose time, any
claim whose `keywords` contains a term not in that list. Model-suggested terms belong in a
claim's `candidateKeywords` (advisory, free-form, captured during description writing);
`python scripts/knowledge_registry.py keyword-report` aggregates them for a human curation
session (`curate-knowledge-keywords`). Promotion never rewrites verified claims — an approved
term enters `keywords` on the claim's next governed revision.

Language rule (build contract R7): Polish domain/business terms are preserved **verbatim** as
taxonomy terms where the business uses them — do not translate them into English.

## Terms

<!-- No terms yet. Machine-parsed format per term (one list item):
- <term> — <one line on what it covers, plus known synonyms it absorbs>
First terms are added via /tune-test-case-keywords or the curate-knowledge-keywords session
(model suggests, human confirms) — never fabricated at build time. -->
