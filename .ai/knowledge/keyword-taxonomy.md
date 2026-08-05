# Keyword Taxonomy

Controlled vocabulary of terms shared between Knowledge entry descriptions and the QA layer.
Its purpose: two descriptions of the same thing (e.g. "Billing" vs "Invoicing") resolve to one
shared term once, instead of the model re-guessing synonymy every time
(historical design blueprint section 3; git tag `design-history`).

This file is separately human-curated; it is not a generated claim index. A taxonomy term is never
evidence that an object, field, process, or package behavior exists. Governed Knowledge may
reference only already-approved terms, and evidence must establish the underlying fact
independently.

**Growth rule — the defining property of this file**: the taxonomy grows **only through
explicit human confirmation**. Skills (`tune-test-case-keywords`, `investigate-object`) may *suggest* a new term, but may
never add one silently. Uncontrolled
vocabulary growth would recreate exactly the chaos this file exists to prevent.

**Machine-checked contract**: `knowledge_store.py` parses the list items under `## Terms`
(format: `- <term> — <notes>`) as the approved vocabulary for entry keywords.
Model-suggested terms belong in an entry's `candidateKeywords` (advisory, free-form, captured
during description writing) and await a human curation session. Approval never rewrites
approved entries — an approved term enters `keywords` on the entry's next governed revision.

Language rule (build contract R7): Polish domain/business terms are preserved **verbatim** as
taxonomy terms where the business uses them — do not translate them into English.

## Terms

<!-- No terms yet. Machine-parsed format per term (one list item):
- <term> — <one line on what it covers, plus known synonyms it absorbs>
First terms are added via /tune-test-case-keywords or a curation session
(model suggests, human confirms) — never fabricated at build time. -->
