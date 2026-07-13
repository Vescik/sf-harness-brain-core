# Knowledge Claim Lifecycle

Status: normative
Schema version: 2

This contract defines how an observation becomes reusable Knowledge. The model may propose a
claim, but it is never itself an evidence source and may never promote a claim to `verified`.

## Canonical records

The canonical layer consists of three independently validated record types:

- **Claim** — a scoped assertion in `.ai/knowledge/claims/<claimId>.yaml`.
- **Evidence** — an immutable, sanitized observation receipt in
  `.ai/knowledge/evidence/<evidenceId>.yaml`.
- **Review** — an immutable human decision in `.ai/knowledge/reviews/<reviewId>.yaml` that records
  a lifecycle transition or reconciliation.

The Markdown domain files in `.ai/knowledge/` are generated indexes, not sources of truth. Raw
Salesforce responses stay outside committed Knowledge. Evidence receipts contain only the minimum
sanitized summary, provenance, completeness, and digest needed to reproduce or re-run the check.

## Lifecycle

Allowed claim states and transitions:

```text
proposed  -> verified | rejected
verified  -> stale | contested | superseded
stale     -> verified | contested | superseded
contested -> verified | superseded
```

- Investigators and models create only `proposed` claims.
- `verified` requires at least one applicable evidence record, a human review record, a matching
  scope, and the evidence minimum in `config/knowledge-policy.json`. Managed-package scope uses
  the configurable package namespace as its primary identity; a local package key/name is only an
  optional aid.
- `contested` preserves both incompatible assertions. Never overwrite either side silently.
- `stale` means the claim is not currently safe to rely on; it does not assert that the claim is
  false.
- `superseded` requires an explicit replacement claim and review. Newer evidence alone is not
  sufficient when environment, package version, or other scope differs.
- `rejected` and `superseded` records remain in version control for auditability.

Evidence records are immutable. A correction or a repeated observation creates a new evidence ID.
A review is also immutable; a later decision creates a new review and increments the claim
revision.

## Deterministic registry operations

`scripts/knowledge_registry.py` exposes separate commands so runtime role policy can allow proposal
work without granting promotion authority:

- Investigator draft inputs live only under ignored `.cache/knowledge-proposals/`; role guards
  deny proposal inputs elsewhere and deny direct edits to canonical Knowledge.
- `propose` validates and atomically writes sanitized evidence plus a `proposed` claim. New claims
  require expected revision `0`; proposal updates require the exact current revision.
- `validate` checks schemas, filenames, cross-references, policy, and rule-ID uniqueness.
- `review` records an immutable schema-valid human review against the exact current claim revision.
- `promote` requires a previously recorded `verify` review and the exact expected claim revision;
  it atomically advances the claim to the next revision.
- `reconcile` is read-only and classifies duplicate, conflict, parallel-scope, or new assertions.
- `render-indexes` deterministically rebuilds or checks the Markdown domain views.

In the current controlled pilot, `auditReceipt` binds a human-entered mechanism/reference and a
recomputed content digest to the exact claim, scope, and evidence manifest. The digest detects
tampering but does not itself verify a GitHub/ADO actor or cryptographic signature. Provider or
signature verification is a team-wide rollout gate, not a capability claimed by this registry.

Role guards should allow `propose`, `validate`, `reconcile`, and index checking independently from
the human-only `review` and `promote` mechanisms. The registry script accepts no alternate root, so
all writes remain under the canonical repository paths.

## Assurance and evidence

Assurance describes how a claim is supported; it is separate from lifecycle status:

- `observed` — supported by a direct, scoped observation.
- `corroborated` — supported by independent applicable evidence.
- `reported` — supported by an accountable human or approved artifact for a domain where that
  source is authoritative.
- `inferred` — reasoned from evidence but not directly established.
- `unknown` — evidence is missing or insufficient.

`inferred` and `unknown` claims cannot be `verified`. A single record sample cannot prove universal
behavior. Failure to observe an item cannot prove absence unless the evidence record demonstrates
complete enumeration, sufficient permissions, and all pages fetched.

## Freshness

Every claim has `observedAt` and `reviewBy`. Verified claims also have `verifiedAt`. Evidence keeps
`observedAt` separate from `retrievedAt`.

Freshness is evaluated against the committed policy and the current scope fingerprint. Event-driven
invalidators (for example a package upgrade, metadata deployment, sandbox refresh, permission
change, or source revision) take precedence over the maximum review age. An expired or invalidated
claim is effectively stale even before a maintainer commits the status transition.

Stale, contested, proposed, rejected, or scope-mismatched claims cannot support a `SAFE` verdict.

## Reconciliation

Compare claims only after normalizing `(subject, predicate, scope)`:

1. Same assertion and scope: attach new evidence through a review; do not create a duplicate.
2. Different value, same subject/predicate/scope: mark the claims contested and retain both.
3. Different environment, package version, or repository revision: keep parallel scoped claims.
4. Proven temporal replacement in the same lineage: create an explicit supersession review.
5. Missing or partial enumeration: return unresolved; do not create a negative claim.

Principles are prescriptions and Knowledge claims are facts. A fact that shows the org violates a
Principle is a compliance finding, not a reason to rewrite the fact. A discovered package
limitation may propose a Principle change, but promotion into a rule is a separate owner-reviewed
operation recorded in the Principle registry.

## Retrieval rule

Consumers may use only claims that are `verified`, current under the policy, in matching scope, and
free of unresolved contradiction. Generated domain indexes may display other states as warnings,
but must never present them as established facts.
