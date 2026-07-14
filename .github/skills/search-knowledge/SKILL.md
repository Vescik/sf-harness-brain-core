---
name: search-knowledge
description: Read-only search over the governed Knowledge registry - by subject, approved or candidate keyword, and statement/description text - reporting effective facts separately from non-effective records. Never proposes, promotes, or edits Knowledge.
user-invocable: false
---

# Search Knowledge

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
retrieval rule of the [Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md):
only a `verified`, fresh, scope-matched, uncontradicted claim is an established fact.

## Inputs

At least one of: a subject identity (object/field/component API name), a keyword, or a free-text
fragment. Optional narrowing: domain, claim type, environment/org scope.

## Procedure

1. Query the registry deterministically — never grep the claim YAML by hand:
   - exact subject: `python scripts/knowledge_registry.py query --subject-identity <identity>`
   - keyword: `python scripts/knowledge_registry.py query --keyword <term>` (matches approved
     `keywords` and advisory `candidateKeywords`; the result names which tier matched)
   - text: `python scripts/knowledge_registry.py query --text <fragment>` (statement + component
     description substring)
   - combine with `--domain`, `--claim-type`, `--environment`, `--org-key` as needed.
2. For a broad scan, read the generated `.ai/knowledge/claims-index.json` — one row per claim
   with status, keywords, and description excerpt. Only rows with `effective: true` are facts.
3. For vocabulary questions ("what process terms exist?"), run
   `python scripts/knowledge_registry.py keyword-report` and read
   `.ai/knowledge/keyword-taxonomy.md` (approved terms) — candidate terms are suggestions
   awaiting human curation, never evidence.
4. Report effective claims (with claim IDs and evidence refs) separately from non-effective
   matches (proposed/stale/contested/superseded/rejected), each with its reason. An empty result
   is "no governed Knowledge", never license to answer from model memory.

## Boundaries

Read-only: never propose, approve, edit claims/evidence/reviews, or grow the keyword taxonomy
from this skill. Missing knowledge is a finding — route creation to
[propose-force-app-knowledge](../propose-force-app-knowledge/SKILL.md) or
[investigate-object](../investigate-object/SKILL.md).

## Return

Return the filters used, effective claims (ID, statement, keywords, evidence refs), non-effective
matches with reasons, keyword tier for keyword hits, and suggested next steps for gaps.
