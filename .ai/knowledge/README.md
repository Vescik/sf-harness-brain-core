# Knowledge Index

Governed Knowledge lives in the one-file entry store
([`docs/knowledge-one-file-contract.md`](../../docs/knowledge-one-file-contract.md)); the v1
claim registry retired on 2026-08-03 (see `.ai/memory/decisions-log.md`).

| Surface | Authority |
|---|---|
| `artifacts/<MetadataType>/<ns|c>/<FullName>.md` | One-file Knowledge Entries — executor-derived repository facts plus human-attested prose. Written only by `scripts/knowledge_store.py`; never hand-edited. |
| `artifacts-ledger.jsonl` | Append-only approval ledger; approval binds to `reviewedContentDigest`, latest-wins. |
| `artifacts-org-ledger.jsonl` | Append-only org-usage ledger (`entry-org-attach`/`detach`); entries carry expiring `orgUsage` blocks. |
| `features/<slug>.md` + `features-ledger.jsonl` | Feature Entries — human-approved boundary rules and prose; never citable as `entryRef`. |
| [keyword-taxonomy.md](keyword-taxonomy.md) | Separately curated vocabulary; terms are not factual evidence. |

These directories and ledgers materialize on first executor write; their absence on a fresh
clone is normal.

## Retrieval rule

Treat an entry as established only when the executor computes lane `approved-current`
(`entry-status`/`entry-check` — never a raw file read), and cite only source-exact,
fully-covered sections (contract §8.1). Org usage grounds only from an unexpired `orgUsage`
block, cited with orgKey and observedAt. Drafted, drifted, revoked, or org-expired records may
be shown as warnings but may not support a `SAFE` verdict. Existing Knowledge and generated
views never corroborate themselves.

This repository intentionally contains no organization or package facts until real, sanitized
evidence is reviewed. Never seed examples into the live store.
