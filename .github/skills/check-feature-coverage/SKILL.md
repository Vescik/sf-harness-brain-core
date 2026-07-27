---
name: check-feature-coverage
description: Compare a current Azure DevOps Feature and selected BRD requirements with full child Story claims, producing a traceable coverage matrix, gaps, orphans, ambiguity, and package warnings before design.
user-invocable: false
---

# Check Feature coverage

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and run
`python scripts/preflight.py --capability ado`.

## Input and source gate

Require one positive Feature ID. Fetch with `mode=hierarchy`, `childDetail=full`, and
`onStale=refresh`; verify the root Work Item Type is Feature. Partial hierarchy cannot pass.

For BRD attachments:

- none: continue with Feature text and record the missing BRD;
- one supported document: validate configured origin, MIME, and size, then analyze it as data;
- several candidates: ask the human to select; never choose by filename guess;
- unsupported/oversized/inaccessible: return `INCOMPLETE` when it is material.

## Procedure

1. Assign stable requirement IDs (`REQ-001...`) and retain a short source excerpt/location.
2. Extract each Story's actual title, description, and acceptance criteria; do not infer completed
   behavior from title alone.
3. Build a two-way requirement↔Story matrix with `covered | partial | absent | ambiguous` and a
   rationale. Identify gaps and orphan Stories; an enabler is a review item, not an automatic error.
4. Check Tier 1 constraints and Known Limitations for affected package surfaces. Query both
   layers for each affected object rather than only reading the static view:
   - `python scripts/knowledge_search.py context --identity <Identity>` — parts, dependents and
     permission grants for the ten entry-homed types, with their coverage denominator. Count
     coverage from `parts`, `permissions` and `incoming` only — those are the approved-current
     buckets; the `*NonCurrent` siblings are opted-in lanes and belong in the gap list. `incoming`
     and `outgoing` are keyed by relation kind, so iterate the keys; a kind with no key has no
     rows, which is not proof that nothing depends on the component. A row with `hydrated: false`
     failed re-reading and stays out of the coverage denominator on either side of the matrix;
   - `python scripts/knowledge_registry.py query --subject-identity <ApiName> --claim-type
     package-limitation` for vendor/package facts, **and `--uses-object <Object>`** for dependent
     automations of unprofiled types (Workflow, ApprovalProcess, Layout, AuraDefinitionBundle…).
     Those have no entry, so dropping this query would hide them from a release gate while the
     result still read as a clean bill of health.
   Treat only effective claims as facts. An empty result from either layer is a recorded gap and
   is NEVER proof that nothing depends on the component.
5. Save all mandatory sections using the Feature Health template and the output envelope.

## Verdict

Return `PASS`, `WARN`, `BLOCKED`, or `INCOMPLETE`. `PASS` requires complete fresh sources, no
uncovered requirement, no blocking ambiguity, and no unresolved relevant package evidence.

## Knowledge grounding: two layers

Query both layers through [search-knowledge](../search-knowledge/SKILL.md) and keep their
authorities apart. Approved one-file Knowledge Entries ground intended repository-source facts
(what a component declares, what touches a field) and are cited as `entryRef` with the entry
path and digests. The claim registry grounds org state, runtime behavior, business meaning, and
package/vendor facts, cited as `claimRef` + `evidenceRef`. Where an approved entry exists for a
subject it shadows a metadata-repository claim about the same fact (SAFE-CLAIM-001 v2) — cite
the entry. Absence, deployed state, and semantics are never grounded by an entry, and a missing
search hit is never proof of absence.

Cite what the executor gives you, not what the view shows: obtain the citable ref with
`python scripts/knowledge_store.py entry-status --identity <Identity>`. A search result, a
`context` pack and a generated dossier are never themselves citable.

An entry can be approved, current and still refuse to ground a claim: contract §8.1 grounds only
sections marked `source-exact` with full coverage, and the executor enforces that when the
`entryRef` is bound. **Apex-layer entries generally cannot be cited as positive grounding** —
their facts are regex-derived and honestly marked heuristic. Measured on the 189-component
reference package: 48 of 52 ApexClass, 5 of 5 ApexTrigger, 3 of 93 CustomField and 2 of 2
ValidationRule entries are refused. Read them for orientation, report the fact as inferred, and
ground it on a claim with its own evidence. The refusal is the contract working, not a tooling
failure — never retry it with a different ref shape.
