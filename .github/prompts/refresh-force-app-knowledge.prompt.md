---
name: refresh-force-app-knowledge
description: Re-draft drifted/expired/expiring verified claims against current source, then propose and chat-approve them.
argument-hint: "[type=<MetadataType>] [warnDays=<N>] [claimIds=<ID,ID,...>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Use the [batch-knowledge skill](../skills/batch-knowledge/SKILL.md) in its Refresh mode, with the
[propose-force-app-knowledge skill](../skills/propose-force-app-knowledge/SKILL.md) rules for
descriptions and chat approval.

Run `python scripts/force_app_knowledge.py inventory`, then
`python scripts/force_app_knowledge.py refresh --dry-run` (apply `type=` as `--metadata-type` and
`warnDays=` as `--warn-days`) and present the selection — per-claim reason (drift / expired /
expiring) and any `remaining` overflow — to the human before executing. Stop after inventory when
source is partial, dirty, untracked, or changed after scanning.

On go-ahead, run `refresh` without `--dry-run`, fill description sentinels from source, and submit
the manifest `propose` commands (they carry `--refresh-verified`). Submit no canonical proposal
beyond the approved selection; when `claimIds` is given, propose only those. Refreshed claims are
`proposed` and not effective until the human approves them in chat — request approval per chunk
with `approve-claim --claim-spec` batches.

Return the selection counts by reason, artifact paths, commit/tree digest, registry results, and
the outstanding human approval requirement.

Entry-home metadata types are not refreshed here: their staleness shows up as the
`approved-drifted` lane, resolved by re-drafting the affected entry and re-approving it
through `/approve-drafts-knowledge`. Report them instead of drafting refresh claims.
