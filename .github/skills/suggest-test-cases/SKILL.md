---
name: suggest-test-cases
description: Rank existing synced Test Cases for a structured change using curated taxonomy evidence, artifact identity, business context, negative evidence, and bounded model reasoning; suggestions are never formal coverage.
user-invocable: false
---

# Suggest Test Cases

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

## Inputs

Require structured touched artifacts (`type`, `API name`, purpose), work-item title/description,
affected business processes, and QA index source timestamp/completeness. Bound the candidate set;
an empty/stale/partial relevant index must be disclosed.

## Procedure

1. Validate curated keywords against the controlled taxonomy. A shared generic term alone is not
   an unquestioned high-confidence match; consider specificity and negative evidence.
2. Assign strongest evidence to an exact Test Case mapping or direct artifact/API-name coverage.
3. Expand technical to business vocabulary only through verified object/process/glossary entries.
4. Use model reasoning over the bounded candidate index to assess behavioral relevance, including
   reasons a superficially similar Case does not apply.
5. Deduplicate and group:
   - `High probability`: direct curated mapping or specific artifact/behavior evidence.
   - `Worth checking`: indirect process/context evidence.
   - `Rejected candidate`: useful negative evidence when a plausible title does not apply.
6. Every candidate cites signals, counter-signals, source suite/timestamp, and rationale.

## Return

Return ranked suggestions and rejected candidates plus QA completeness. Label all as unconfirmed;
only formal ADO Test Case relations count as confirmed coverage.
