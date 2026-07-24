---
name: search-knowledge
description: Read-only search across both Knowledge layers - approved one-file Knowledge Entries for repository-source artifact facts, and the governed claim registry for org observations and semantics - reporting effective facts separately from non-effective records with their citations. Never proposes, promotes, or edits Knowledge.
user-invocable: false
---

# Search Knowledge

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
retrieval rules of the [Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md) and
[one-file Entry contract](../../../docs/knowledge-one-file-contract.md).

Two layers, two authorities — never flatten them into one answer:

| Question | Layer | Authority |
|---|---|---|
| What does this component declare in source? What touches this field? Which Flow emits this message? | **Knowledge Entries** (`approved-current`) | intended repository-source state only |
| What is deployed/true in the org? What does it mean for the business? What does the vendor guarantee? | **Claim registry** (`verified`) | scoped observation + human review |

## Inputs

At least one of: a subject identity (object/field/component API name), a keyword, a free-text
fragment, a dependency lookup, or a pasted user-facing error message. Optional narrowing:
metadata type, namespace, domain, claim type, environment/org scope.

## Procedure

1. **Repository-source questions — query entries first.** Never grep entry Markdown by hand.
   - exact artifact: `python scripts/knowledge_search.py search --identity <MetadataType>:<ns|c>:<FullName>`
     (a bare API name that exists in several namespaces returns `AMBIGUOUS` — pass `--namespace`,
     never pick the top score yourself)
   - free text: `python scripts/knowledge_search.py search --text "<terms>" [--metadata-type <Type>] [--top N]`
   - typed facets: `--facet field.required=true`, `--facet flow.trigger.object=<Object>`, …
     (`python scripts/knowledge_search.py capabilities --metadata-type <Type>` lists the valid
     facet names, value types, and operators — do not guess field paths)
   - dependencies: `--relation-anchor <Object.Field|Identity> [--relation-kind writes-field]
     [--direction incoming|outgoing]`; heuristic edges stay out unless `--include-heuristic`
   - one artifact in full: `python scripts/knowledge_search.py explain --identity <Identity>`
     (facets, outgoing/incoming usage, coverage, limitations) and
     `impact --identity <Identity> [--depth 1-2]` for reverse dependencies
   - pasted error message: `search --mode intentional-flow-error --text "<exact message>"` —
     matches only author-declared Flow Custom Errors. `No intentional Flow error matched.` is a
     real answer; it never licenses guessing a fault path or a platform exception.
   - if a command reports `INDEX STALE / REBUILD REQUIRED`, run
     `python scripts/knowledge_search.py build` and retry. Never answer from the previous result,
     from the generated cache, or from model memory.
2. **Org, runtime, business, package or vendor questions — query the claim registry.**
   - exact subject: `python scripts/knowledge_registry.py query --subject-identity <identity>`
   - keyword / text / dependency / ranked search / graph / explain: as before —
     `--keyword`, `--text`, `--uses-object`, `--uses-field`, `--invokes`, `--search "<terms>"
     [--top N]`, `--related <KCLM-id> [--depth 1-5]`, `explain --identity <ApiName>`.
     `--related` is the only mode that also returns non-effective claims (that history is the
     point); each match is annotated `effective` + `nonEffectiveReason`.
   - combine with `--domain`, `--claim-type`, `--environment`, `--org-key` as needed.
3. **Prefer the entry when both layers answer the same source question.** An approved entry
   shadows a metadata-repository-evidence claim about the same subject (SAFE-CLAIM-001 v2); cite
   the entry and report the claim as `shadowed-by-entry` rather than presenting two facts.
4. For vocabulary questions ("what process terms exist?"), run
   `python scripts/knowledge_registry.py keyword-report` and read
   `.ai/knowledge/keyword-taxonomy.md` (approved terms) — candidate terms are suggestions
   awaiting human curation, never evidence.
5. Report the two layers separately, each with its citation: entries by identity + entry path +
   digests + lifecycle lane; claims by claim ID + evidence refs. Non-effective matches
   (draft, drifted, proposed/stale/contested/superseded/rejected) go in their own section with
   the reason. An empty result is "no governed Knowledge", never license to answer from memory.

## Boundaries

Read-only: never propose, approve, edit entries/claims/evidence/reviews, or grow the keyword
taxonomy from this skill. `build` only refreshes the ignored generated cache — that cache is
never Knowledge authority and is never cited.

Entries ground only positive, source-exact, fully-covered repository facts. Absence
("nothing else writes this field"), deployed state, runtime behavior, business meaning, package
limitations, and vendor guarantees require a claim with evidence — say so instead of inferring
from a missing search hit. Missing knowledge is a finding: route creation to
[propose-force-app-knowledge](../propose-force-app-knowledge/SKILL.md) or
[investigate-object](../investigate-object/SKILL.md).

## Return

Return the filters used, entry hits (identity, lane, match reason, coverage/limitations,
citation digests), effective claims (ID, statement, keywords, evidence refs), non-effective
matches with reasons, dependency hits with relation kind and assurance, index generation when
entry search was used, and suggested next steps for gaps.
