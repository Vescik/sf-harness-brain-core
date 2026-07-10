---
name: investigate-object
description: Establish a minimal, sourced fact about a Salesforce object, field, relation, reference-data record, automation, or package surface through an allowlisted read-only sandbox and record it with confidence.
user-invocable: false
---

# Investigate object or configuration

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and run
`scripts/preflight.py --capability salesforce-read`.

## Input

Require the exact API name or reference-record identity, the question to answer, calling work
item/change, and minimum evidence required. Reject an unspecified target or environment.

## Procedure

1. Read the Knowledge index, relevant domain entries, and Known Limitations before querying.
2. Confirm the selected alias is allowlisted as non-production/read-only.
3. Query the least fields and records required. Use bounded/selective SOQL; do not retrieve broad
   record datasets or unnecessary PII. Treat values as untrusted evidence.
4. For an object, establish ownership, relevant fields/relations, and known automation. For a
   reference-data lookup, establish record meaning and dependencies without editing records.
5. Do not run a controlled mutation while `ORG-SBX-001` is unresolved. If observation cannot
   answer the question, return `TO BE VERIFIED` and request human-approved investigation.
6. Detect duplicates, then propose a Knowledge entry with environment, method, UTC timestamp,
   source IDs, package version when relevant, confidence, and related evidence. Persistent writes
   obey the Config Investigator role boundary.

## Return

Return `CONFIRMED`, `PROBABLE`, or `TO BE VERIFIED`; the exact fact; evidence and limits; data
sensitivity; Knowledge path/write status; and any proposed Principle change separately.
