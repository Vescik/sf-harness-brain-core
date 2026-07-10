---
description: Company policy, review, naming, decision, Knowledge-promotion, handoff, and shared-sandbox rules. Load explicitly for governed design, implementation, and review.
---

# Organization Principles — Tier 2

These rules override general Salesforce practice and are overridden by Tier 1 package limits.

## Naming

- **ORG-NAME-001 — names remain provisional.** Company naming conventions are not yet supplied:
  `<TU_WSTAW_KONWENCJE_NAZEWNICZE_FIRMY>`. Use the Tier 3 convention only as a proposal and mark
  generated API names `PROVISIONAL — HUMAN REVIEW REQUIRED`.

## Review

- **ORG-REVIEW-001 — independent review is mandatory.** Every implementation must reach the
  Guardrail Reviewer before it is called complete. Missing company review criteria
  (`<TU_WSTAW_ZASADY_CODE_REVIEW>`) reduce the verdict to `INCOMPLETE — NEEDS HUMAN` when those
  criteria could affect safety, compliance, or release approval.
- **ORG-REVIEW-002 — generated output is unapproved.** Documentation, handovers, test scripts,
  and Knowledge suggestions remain drafts until a named human accepts or promotes them.

## Decisions

- **ORG-DEC-001 — persist material decisions.** Until
  `<TU_WSTAW_FORMAT_DOKUMENTOWANIA_DECYZJI>` is supplied, use the format in
  [decisions-log.md](../../.ai/memory/decisions-log.md) and record approver plus related evidence.
- **ORG-DEC-002 — accepted design is an implementation precondition.** Development requires a
  design record with `Status: Accepted`, an approver, timestamp, and no blocking question.

## Knowledge and handoffs

- **ORG-KNOW-001 — observations are proposals.** An investigator or model may create sanitized
  evidence and a proposed claim. Only a named human review bound to the evidence and scope may
  promote a claim to `verified`.
- **ORG-KNOW-002 — freshness is claim-specific.** A historically verified claim that passed its
  review-by time or an invalidating event is not safe to rely on until revalidated. Never extend
  freshness because the value looks plausible.
- **ORG-KNOW-003 — conflicting evidence is retained.** Do not overwrite, delete, or hide a prior
  claim when a new observation differs. Create immutable evidence and mark the normalized claim
  `contested` pending human reconciliation.
- **ORG-HAND-001 — persisted state outranks conversation.** Every governed role transition requires
  a schema-valid work record and handoff addressed to the target role. Missing, stale, wrong-role,
  or hash-mismatched handoffs must be rejected.
- **ORG-HAND-002 — approval is revision-bound.** Approval binds to the exact scope and design
  hashes. Any change invalidates approval and returns the work to human review.

## Shared Full Copy Sandbox

- **ORG-SBX-001 — read-only until coordination exists.** Shared-sandbox coordination rules are
  not yet supplied: `<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>`. Until they are, agents
  may query and describe the sandbox but must not create, update, delete, deploy, activate, or run
  a controlled mutation there.
- **ORG-SBX-002 — isolate and clean test data.** Once mutation is authorized, use uniquely named
  test records, document the owner/time window, avoid shared reference-data changes, and verify
  cleanup. A failed cleanup must be reported, never hidden.
