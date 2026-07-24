---
name: approve-knowledge-drafts
description: Human-initiated promotion of draft one-file Knowledge Entries - renders the executor-authored review surface, presents the exact digest set, and runs the digest-pinned approval the human confirms in chat. Never approves content the human has not been shown.
user-invocable: false
---

# Approve Knowledge drafts

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[one-file Knowledge Entry contract](../../../docs/knowledge-one-file-contract.md) (§6 approval
mechanism, §9 batching).

This skill exists because the developer consciously invoked the prompt: that invocation is the
declaration that they intend to review drafts. It is **not** a licence to self-approve. The agent
only renders and executes; the human reads the rendered body and clicks the confirmation.

## Inputs

Optional `identity` values (`<MetadataType>:<ns|c>:<FullName>`). With none, every `draft` entry
is offered. Nothing else is accepted — scope is entry identities, never free text.

## Procedure

1. Render the review surface with the executor — never write the summary yourself:
   `python scripts/knowledge_store.py entry-review [--identity <Identity> ...]`
   It writes `output/knowledge-approvals/<chunkId>-review.md` (full attested body per entry,
   change class, coverage, assurance, limitations, source-declared intentional errors) and
   returns the exact digest-pinned `entry-approve` command.
2. Stop on `NOTHING_TO_REVIEW` (report the listed validation problems) or `CHUNK_TOO_LARGE`
   (report the cap violation and split the chunk). Entries with unfilled `<AGENT_…>` sentinels,
   unapproved keywords, a missing `## Purpose`, or a failing path round-trip never reach review.
3. Present to the human, in the chat: the chunk id, the review-artifact path, the per-entry
   change class (new approval / prose changed / facts-only re-approval), and the digest set.
   Ask them to read the artifact. Do not paraphrase or summarise the attested bodies — the
   rendered artifact is the review surface.
4. On their go-ahead, run the returned command verbatim. The safety hook answers `ask`; their
   click is recorded as mechanism `copilot-chat-entry-confirmation` with the reviewer identity
   from local `knowledge.chatReviewer`. Report a missing/placeholder reviewer configuration and
   stop rather than improvising one.
5. Never edit an entry between review and approval. Any change invalidates the pin and the
   executor rejects the whole chunk — re-render instead of retrying with fresh digests.
6. Report the ledger outcome: approved identities, chunk id, and anything skipped with its
   reason. Approval writes an append-only record; correcting a mistaken approval is
   `entry-revoke --identity <Identity> --rationale <reason>`, not a file edit.

## Boundaries

The agent may not: approve without the human's confirmation click, approve entries outside the
rendered digest set, author or alter the review surface, edit entry files directly (the artifacts
path is governed — writes flow only through the executor), or promote v1 claims from here
(that is `approve-claim` in the claim registry).

Batching follows the contract: chunks containing prose changes stay within the 25-entry cap; the
larger facts-only path is for re-approvals whose attested body is unchanged. Splitting a chunk is
always preferable to asking for one oversized confirmation.

## Return

Return the chunk id, review-artifact path, per-entry change class, approved identities with their
digests, the recorded reviewer and mechanism, skipped entries with reasons, and any remaining
drafts still awaiting review.
