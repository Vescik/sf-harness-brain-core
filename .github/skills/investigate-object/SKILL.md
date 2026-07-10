---
name: investigate-object
description: Generalized procedure for investigating an unknown system element — a real custom object with fields, or a lookup-to-reference-data pattern. Checks Knowledge first, investigates read-safely on the sandbox, and records the finding in the Knowledge layer.
---

# Skill: investigate-object

Used by the Solution Designer and the Development Assistant **through the Config
Investigator** — one consistent procedure instead of duplicated logic across agent files
(blueprint sections 3 and 11).

Covers **both** patterns of this org's hybrid data model:

- **Real object with fields** (e.g. `Invoice__c`): describe the schema, check relations, test
  on the sandbox.
- **Lookup-to-reference-data pattern**: the "picklist-looking" field is a lookup to runtime
  records on a Reference Data object — inspect the reference records themselves, their meaning
  and dependencies.

## Procedure

1. **Check whether we already know.** Read `.ai/knowledge/README.md` first (the navigational
   index), then the relevant domain file(s). If the fact is already recorded, use it — do not
   re-investigate.
2. **Describe.** For a real object: describe the schema (fields, relations). For the
   reference-data pattern: describe/query the reference records, what each means, what depends
   on them.
3. **Controlled sandbox test — only if the risk is acceptable.** This is a shared Full Copy
   Sandbox: follow the shared-sandbox rules in
   `.github/instructions/organization-principles.instructions.md`. If the risk is NOT
   acceptable, skip to step 5.
4. **Record the finding** using the format in `.ai/templates/knowledge-entry.md` — always with
   a confidence level and how it was established. **Optionally add the "Keywords" field** with
   terms from `.ai/knowledge/keyword-taxonomy.md` if the object matches an existing term; if no
   term fits, omit the field — never invent a term, never block the write on this. If the
   target Knowledge file is not obvious, route the finding through the `update-knowledge-base`
   skill instead of guessing or duplicating.
5. **If ambiguous — ask a human instead of guessing.** An unresolved question is recorded as
   "to be verified", not silently resolved.

Also consult `.ai/knowledge/known-limitations.md` when the investigated element belongs to the
managed package — a discovered limitation found there may already answer the question.

Read-only stance: this skill establishes facts. It never modifies org configuration beyond the
controlled test in step 3, and never touches anything outside the dev sandbox.
