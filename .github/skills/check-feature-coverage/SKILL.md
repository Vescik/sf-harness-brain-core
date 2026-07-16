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
4. Check Tier 1 constraints and Known Limitations for affected package surfaces. Query the registry
   for each affected object rather than only reading the static view: `python
   scripts/knowledge_registry.py query --subject-identity <ApiName> --claim-type package-limitation`
   and `--uses-object <Object>` for dependent automations. Treat only effective claims as facts;
   record an explicit gap when Knowledge is empty.
5. Save all mandatory sections using the Feature Health template and the output envelope.

## Verdict

Return `PASS`, `WARN`, `BLOCKED`, or `INCOMPLETE`. `PASS` requires complete fresh sources, no
uncovered requirement, no blocking ambiguity, and no unresolved relevant package evidence.
