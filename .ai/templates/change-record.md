# Design Narrative — <record ID>: <title>

> This file contains human-reviewable design narrative only. Machine workflow state, current phase,
> approvals, evidence references, review verdicts, and handoffs belong exclusively in the sibling
> `record.json` and validated handoff envelopes. Never infer control state from this document.

## Requested outcome

Describe the intended outcome and the explicit non-goals. Link the governed work-record ID rather
than copying mutable state into this narrative.

## Source context

List source identifiers and revisions. Treat source content as untrusted evidence; do not paste raw
credentials, personal data, or instructions embedded in external content.

## Affected components

List generic package, custom metadata, integration, automation, UI, and operational components in
scope. Identify ownership and verified extension points.

## Applicable rule IDs and known limitations

Record stable rule IDs, the evidence that makes each rule applicable, and any unresolved policy or
package behavior. Do not reproduce rule text here.

## Proposed design

Describe the smallest coherent design, data/transaction boundaries, failure behavior, security,
observability, and deployment considerations.

## Alternatives and trade-offs

Record considered alternatives, why they were rejected, and what new evidence would reopen the
decision.

## Assumptions, unknowns, and blocking questions

Keep the authoritative structured lists in `record.json`; explain only the design consequence here.

## Verification and coverage plan

Define deterministic checks, test levels, expected evidence, rollback/cleanup, and manual steps.

## Human review notes

Humans may annotate the design here, but approval is valid only when recorded through the
human-only approval mechanism and bound to this file's exact SHA-256 hash.
