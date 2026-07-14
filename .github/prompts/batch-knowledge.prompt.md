---
name: batch-knowledge
description: Convert one whole metadata type (e.g. all Flows) into governed Knowledge in a five-phase batch — discover, plan, verify the plan, execute in chunks, verify the result.
argument-hint: "type=<MetadataType> [chunk=<N, default 10>] [recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [batch-knowledge skill](../skills/batch-knowledge/SKILL.md).

Parse `type=<MetadataType>` (required — exactly one inventory metadata type per batch, e.g.
`Flow`, `ApprovalProcess`, `CustomObject`) and optional `chunk=<N>` (components per execution
chunk, default 10, max 25). Announce each phase as you enter it (DISCOVER → PLAN → VERIFY PLAN →
EXECUTE → VERIFY) and never skip or reorder phases; a failed verification returns to the phase
that caused it. Stop for the human's explicit go-ahead after presenting the plan, and rely on the
chat-approval dialog for every promotion batch.

If this batch continues an earlier interrupted run, do not reconstruct progress from chat
history: rerun `inventory` and `worklist --metadata-type <Type>` per the skill's resume rule and
continue from the first `pending` component.
