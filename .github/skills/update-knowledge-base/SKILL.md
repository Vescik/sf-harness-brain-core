---
name: update-knowledge-base
description: Validate, deduplicate, route, and atomically record a sourced system fact in the allowlisted Knowledge domains while keeping the Knowledge index accurate. Never use for rules, guesses, or raw record dumps.
user-invocable: false
---

# Update Knowledge base

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

## Input

Require a typed finding: name/API identity, factual statement, confidence, method, source
environment/IDs, UTC verification date, investigator, sensitivity, related evidence, and optional
existing taxonomy keywords. Reject unsupported confidence, missing source, secrets/PII, or a rule.

## Procedure

1. Consult the Knowledge index and route only to an allowlisted `.ai/knowledge/*.md` domain.
2. Search API identity, aliases, and semantic content for duplicates or conflicts. Update/relate a
   verified entry instead of creating a second source of truth.
3. If no domain fits, propose a new domain and receive human approval before creating it.
4. Re-read target and index immediately before writing; stop on concurrent change.
5. Build the entry with the Knowledge template. Keywords must already exist in the taxonomy.
6. Apply target plus any required README index update as one reviewed operation; if either fails,
   report partial state and do not claim success.

## Return

Return `RECORDED`, `DUPLICATE`, `CONFLICT — NEEDS HUMAN`, or `REJECTED`; target path; source and
confidence; files changed; index status; and any proposed Principle/taxonomy action separately.
