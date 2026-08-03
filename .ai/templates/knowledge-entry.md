# Template: Knowledge records

One governed record shape exists — pick the surface by the question being answered, never by
convenience.

| Content | Home | Created by |
|---|---|---|
| Repository-source facts about a force-app artifact (profiled metadata types) | one-file Knowledge Entry under `.ai/knowledge/artifacts/` | `knowledge_store.py entry-draft` — never hand-written |
| Org usage of an object/field | `orgUsage` block on the artifact's entry | `knowledge_store.py entry-org-attach` — executor-only |
| Org observations, reference data, business/vendor/runtime semantics | sanitized investigation report under `output/` | investigate-object / investigate-config-records — never citable |

---

## 1. One-file Knowledge Entry (repository-source facts)

Contract: [`docs/knowledge-one-file-contract.md`](../../docs/knowledge-one-file-contract.md).

**You never write these files by hand.** The artifacts path is governed: the executor derives
every structured field from source, computes the digests, and writes atomically. A human
authors only the attested prose, and only through the draft command's `--purpose-file`.

```text
python scripts/knowledge_store.py entry-draft \
  --metadata-type Flow --full-name <ApiName> [--namespace <ns>] --purpose-file <file.md>
python scripts/knowledge_store.py entry-review          # executor renders the review surface
/approve-drafts-knowledge                                # human reads it, confirms in chat
```

Shape of a written entry (illustrative — the executor produces it):

```markdown
---
schemaVersion: 1
subject: {metadataType: Flow, fullName: <ApiName>, namespace: null}
profile: {id: salesforce.flow, version: 1.0.0, digest: sha256:...}
scope: {sourceApiVersion: "64.0", sourceTreeDigest: sha256:..., packageVersionId: null}
source: {fragments: [{path: force-app/..., sourceDigest: sha256:...}]}
lifecycle: {state: draft, contentDigest: sha256:...}
typeFacts: {...}                # profile-validated; never free-form
intentionalErrors: [...]        # Flow only: author-declared FlowCustomError, originTag pinned
extractionCoverage: {typeFacts: full}
assurance: {typeFacts: source-exact}
limitations: []                 # digest-bound
notes: []                       # advisory, digest-excluded
keywords: []                    # approved taxonomy terms only
candidateKeywords: []           # advisory, never in established ranking
sensitivity: internal-sanitized # digest-bound
approval: {reviewedContentDigest: null, reviewedBy: null, reviewedAt: null, mechanism: null}
---

## Purpose

<2–6 sentences a human vouches for. The only approvable body section in the pilot.>
```

Rules that hold regardless of what a file looks like on disk:

- **The ledger is the approval authority.** `.ai/knowledge/artifacts-ledger.jsonl` is
  append-only; an entry is `approved-current` only when its recomputed digest is the latest
  ledger record for its identity. Editing the frontmatter's `approval` block or flipping
  `lifecycle.state` by hand does not approve anything — it makes the entry non-effective.
- **Effectiveness is computed, never read.** Ask the executor
  (`entry-status`, `entry-check`, or the search tools); a raw file read never establishes
  approval.
- Facts regenerate freely: an identical collector result changes nothing, a changed assertion
  moves the entry to `approved-drifted` until it is re-approved.
- Retract with `entry-revoke --identity <Identity> --rationale <reason>`, never by deleting or
  editing the file.
- Entries ground **positive, source-exact, fully-covered repository facts only**. Absence,
  runtime behavior, business meaning, package limitations, and vendor guarantees have no
  governed Knowledge surface — reports carry them as `UNVERIFIED` observations; org usage is
  grounded only by an unexpired `orgUsage` block.
