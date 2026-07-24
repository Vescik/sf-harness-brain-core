---
name: approve-drafts-knowledge
description: Review and promote draft one-file Knowledge Entries; the executor renders the review surface and the human confirms the digest-pinned approval in chat.
argument-hint: "[identity=<MetadataType>:<ns|c>:<FullName>] [identity=...]"
agent: knowledge-curator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [approve-knowledge-drafts skill](../skills/approve-knowledge-drafts/SKILL.md).

Parse optional `identity=` arguments; with none, offer every draft entry. Render the review
surface with `entry-review` first, show the human the artifact path, the per-entry change class,
and the digest set, and only then run the returned digest-pinned `entry-approve` command.

Your invocation of this command means you intend to review drafts — it is not an approval by
itself. The confirmation click is the approval, it binds exactly the digests shown, and any edit
made after the review invalidates it.
