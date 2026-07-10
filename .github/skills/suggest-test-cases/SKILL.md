---
name: suggest-test-cases
description: Match existing Test Cases to a development — keywords-map hard match first, then multi-signal model reasoning over the synced QA index. Always grouped by confidence with explicit rationale; always a suggestion, never confirmed coverage.
---

# Skill: suggest-test-cases

Called by `generate-technical-documentation` (fills its "Suggested Test Cases" section);
potentially reusable in the future by `check-feature-coverage` for Feature-level test coverage
(blueprint sections 3 and 11).

Matching is **multi-signal model reasoning, not a rigid keyword-matching algorithm** — a
matching algorithm would be a "custom script" moved from the document layer to the search
layer, avoided for the same reasons as both (blueprint section 3). Gradual-strengthening model:
works reasonably from day one with zero curation, gets better as `keywords-map.md` is tuned,
never blocks on curation being absent.

## Procedure

1. **Check `.ai/qa/keywords-map.md` FIRST.** If a touched artifact has keywords (terms from
   `.ai/knowledge/keyword-taxonomy.md`) and some Test Case carries the same keywords in the
   map — that is a **hard, high-confidence match**, no further reasoning needed.
2. **For artifacts with no map hit** — expand technical vocabulary into business vocabulary via
   `.ai/knowledge/object-descriptions.md` and `.ai/knowledge/business-processes.md`.
3. **Model reasoning over the synced titles**: with the gathered context (touched artifacts
   from `package.xml` + business vocabulary + the Feature/Story title and description), assess
   the relevance of the Test Case titles in `.ai/qa/test-cases/*.md` — by reasoning, NOT by
   string-matching.
4. **Group the result**:
   - **High probability** — a keywords-map hit, or a direct hit on an artifact name.
   - **Worth checking** — a hit only via business context/description.
   Every suggestion carries an **explicit rationale**. The output is always a suggestion for
   human review — **never presented as confirmed coverage** (confirmed coverage is the
   formally-linked-Test-Cases mechanism in `release-handover`, a different thing — do not mix
   them).
5. **If `.ai/qa/` has nothing synced for the touched areas — say so explicitly** and suggest
   running `/sync-test-cases` for the relevant suite, instead of a silent empty section.
