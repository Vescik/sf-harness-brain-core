# Governed Work-Record State Machine

Status: normative
Schema version: 1

This contract defines durable workflow state for governed Salesforce work. Chat history, handoff
button text, ignored cache, and generated output are navigation aids only. The authoritative state is
the validated `.ai/change-records/<record-id>/record.json` file and its referenced handoff envelopes.

## Record layout

```text
.ai/change-records/<record-id>/
├── record.json
├── design.md
├── evidence/
│   └── <evidence-id>.json
└── handoffs/
    └── <handoff-id>.json
```

Record IDs use `ADO-<project-slug>-<positive-item-id>`. A record is scoped to one work item and
must never be reused as a global "active task" pointer. Two concurrent work items have two records.

## Authority and durability

- `record.json` is the current machine-readable state. `design.md` is human-readable narrative and
  must not duplicate phase, status, approvals, handoffs, or verdicts.
- Every mutation requires the caller's expected record revision and canonical SHA-256 hash. A stale
  caller must reload instead of overwriting newer state.
- Writes use a temporary file in the destination directory, `fsync`, and atomic replacement.
- Raw ADO/Salesforce/browser content stays in its governed source or ignored cache. Durable records
  store only source identifiers, revisions, timestamps, hashes, bounded factual summaries, and
  reproducible references.
- An ignored `.cache/**` or `output/**` path may be supporting evidence but cannot be the only
  evidence for an accepted design, `SAFE` review, or completed record.
- No record contains credentials, cookies, tokens, raw personal data, or model chain-of-thought.

## Phases and statuses

The state is a `(phase, status)` pair. Supported pairs are:

| Phase | Statuses |
|---|---|
| `intake` | `draft`, `incomplete`, `blocked` |
| `design` | `draft`, `awaiting_human`, `accepted`, `incomplete`, `blocked` |
| `development` | `in_progress`, `incomplete`, `blocked` |
| `qa` | `in_progress`, `incomplete`, `blocked` |
| `review` | `ready`, `needs_fixes`, `incomplete`, `safe`, `stopped` |
| `complete` | `complete` |

Normal transitions are:

```text
intake/draft
  -> design/draft
  -> design/awaiting_human
  -> design/accepted                  # human-only approve command
  -> development/in_progress | qa/in_progress
  -> review/ready
  -> review/needs_fixes | review/incomplete | review/safe | review/stopped
  -> development/in_progress          # from needs_fixes only
  -> complete/complete                 # from safe only
```

Any active phase may move to its `incomplete` or `blocked` state when evidence or authority is
missing. Recovery must return through a permitted role transition; callers cannot skip directly to
`accepted`, `safe`, or `complete`.

## Role authority

- `solution-designer`: initialize a record, maintain pre-approval design state, append sourced
  evidence, and create handoffs. It cannot approve its design.
- `config-investigator`: append investigation evidence and hand it back. It cannot change design,
  implementation, approval, or review state.
- `development-assistant`: consume an accepted development handoff, record implementation and
  verification evidence, and create a review handoff. It cannot approve or review itself.
- `test-strategist`: append QA evidence and move an accepted record through QA to review readiness.
- `guardrail-reviewer`: consume a review handoff and append an independent verdict. It cannot edit
  design or implementation evidence.
- `human`: approve the exact current scope and design through a human-only mechanism, or make the
  final policy/process decision outside agent authority.

## Approval invariant

Only `scripts/work_record.py approve` may create an approval. The command requires an explicit
`--mechanism` value (`human-terminal` or `github-review`), a named approver, an external approval
reference, the current record revision/hash, and the exact design hash reviewed by the human.

The approval stores both `scopeHash` and `designHash`. A later scope or design change makes the
approval invalid. Reopening design marks the prior approval `superseded` before narrative edits are
allowed; approval history is never deleted. Other commands cannot manufacture an approval or
transition into `design/accepted`. Agent role guards must never allow the `approve` subcommand.

For the controlled pilot, `approver`, `mechanism`, and `approvalRef` are human-entered assertions
whose hashes and state binding are tamper-evident; they are not independent proof of actor identity.
Team-wide `SAFE` certification requires a future provider-verified GitHub/ADO receipt or signed
approval challenge bound to the same scope, design, grounding, and commit hashes.

## Handoff invariant

A handoff contains identifiers and bounded evidence references, not the prior chat. It binds to the
record revision, record hash, full generic component scope, scope hash, design hash, source role, and
target role that existed when the handoff was created. Every scoped component states its ownership
as `package-owned`, `subscriber-owned`, `platform`, or `unknown`; package namespace/version remain
nullable until sourced evidence establishes them.

The target role may consume a handoff only when:

1. the envelope validates against `schemas/handoff-envelope.schema.json`;
2. its status is `pending` and it is the record's current handoff;
3. the current record revision/hash, scope hash, and design hash match the envelope;
4. the consuming role equals `toRole`; and
5. all required-read paths are valid workspace-relative paths.

A stale, ambiguous, superseded, or wrongly addressed handoff is rejected. A fresh chat resumes by
record ID and handoff ID, reloads the persisted files, and does not reconstruct state from prose.

## Review and completion invariant

`SAFE` requires all of the following:

- a current human approval bound to the exact scope and design;
- no open blocking question;
- at least one durable, complete evidence reference;
- no partial evidence reference presented as sufficient;
- a verified non-production environment reference;
- recorded verification evidence; and
- an independent `guardrail-reviewer` verdict.

`complete/complete` is allowed only from `review/safe`. A failed or partial condition produces
`INCOMPLETE`, `NEEDS_FIXES`, or `STOPPED`; it is never silently downgraded to a warning.
