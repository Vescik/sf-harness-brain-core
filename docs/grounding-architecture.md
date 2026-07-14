# Grounding and Hallucination-Reduction Architecture

Status: normative

## Objective

Reduce unsupported system/package claims by making the model a proposer and orchestrator rather
than the authority that verifies facts. The harness is package-agnostic: no object, namespace,
package behavior, or business meaning is assumed until scoped evidence and human review establish
it.

## Governed sequence

1. **Principles gate** — select applicable rule IDs and permitted evidence/action scope.
2. **Claim inventory** — list the material factual propositions required by the task.
3. **Knowledge lookup** — use only verified, fresh, uncontested, scope-matched claims.
4. **Repository review** — inspect intended customer-owned metadata at a recorded commit.
5. **Org review** — only for missing, stale, critical, or drift-sensitive facts, through the
   bounded Salesforce review facade.
6. **Reconciliation** — classify agreement, incompleteness, mismatch, and repository/org drift.
7. **Human promotion** — observations become trusted Knowledge only through an immutable review.
8. **Persisted handoff** — transition using validated work-record and handoff IDs, never chat alone.

## Repository grounding boundary

The harness root and Salesforce DX project root are the same directory. The checked-in workspace
exposes that directory once as `brain-core`; no `salesforce` workspace folder or nested SFDX root
exists. Repository observations, design hashes, implementation paths, and handoffs therefore
refer to one commit lineage. Tools must not search a subfolder or parent directory, or substitute
a separately cloned metadata repository.

This shared root does not expand tool authority. Salesforce MCP filesystem inputs and role writes
remain bounded to approved metadata/test subpaths such as `force-app/`, `manifest/`, and
`tests/e2e/`. Changes to Principles, Knowledge, approvals, handoffs, configuration, or other
harness files remain governed by their role-specific mechanisms.

## Authority depends on claim type

| Claim type | Required authority | What an org observation cannot establish alone |
|---|---|---|
| Safety or company policy | Versioned Principle plus named owner/source | Whether the policy should change |
| Intended metadata | Repository commit plus accepted design | What is currently deployed |
| Deployed configuration | Current bounded org evidence | Business meaning or intended design |
| Managed-package limitation | Version-scoped vendor/approved source | Inaccessible package internals or vendor guarantee |
| Business meaning | Reviewed organization/SME source | Meaning inferred from labels or sample values |
| Reference-data value | Bounded current org observation | Universal semantics or permanence |
| Absence | Complete enumeration, permissions, pagination, and freshness | Absence inferred from an empty/inaccessible result |

Principle precedence applies to competing prescriptions, not to facts. When an observation violates
a Principle, record noncompliance. When sources disagree on a normalized claim, mark it contested.

## Salesforce review boundary

Agents never receive raw Salesforce CLI, arbitrary SOQL, aliases, directories, Tooling flags, or
raw vendor payloads. The `salesforce-readonly` facade exposes only:

- `review_org_identity`
- `review_installed_packages`
- `review_object_contract`
- `review_configured_orgs` (only when `safety.allowScopedEnumeration` is enabled; lists the
  locally configured aliases and permissions only — never unconfigured orgs, ids, or hosts)

The facade binds one configured allowlisted sandbox, runs fixed evidence profiles through the pinned
Salesforce MCP and a private CLI allowlist, sanitizes both receipts, and reconciles them. Results are
`VERIFIED`, `MISMATCH`, `INCOMPLETE`, or `BLOCKED`.

MCP/CLI agreement corroborates transport from the same org; it is not an independent source of
business or vendor truth. Mismatch, truncation, schema drift, identity failure, or one missing
transport prevents Knowledge promotion and `SAFE`.

## Knowledge boundary

- Evidence is immutable and corrections create new receipts.
- Agents/investigators may create `proposed` claims only.
- Human reviews promote, reject, contest, supersede, or reverify claims.
- Verified claims may become stale after `reviewBy` or an invalidating event.
- Different environments, package versions, or repository lineages remain separate scopes.
- Domain Markdown is a generated view; canonical claims/evidence/reviews are schema-controlled.
- Raw records, secrets, credentials, broad org payloads, and chain-of-thought are never committed.
- Human review and approval receipts are currently hash-bound assertions. Their actor identity is
  not independently provider- or signature-verified; team-wide rollout remains blocked on that
  authenticity control.

## Handoff boundary

Each governed item has a per-record directory containing machine state, narrative design, immutable
evidence references, and handoffs. Approval binds to scope/design hashes. Every mutation requires an
expected revision. Handoff consumption validates the target role, record revision, hashes, evidence,
and repository lineage. A new chat must resume from `recordId` and `handoffId` alone.

## Acceptance gates

- Every material claim in a design/review has claim and evidence references.
- Every trusted claim is schema-valid, human-reviewed, fresh, scoped, and uncontested.
- No model-only inference is verified Knowledge.
- No incomplete/mismatched org review or source/org drift yields `SAFE`.
- Direct CLI, arbitrary query, default org, production, and raw sensitive output remain blocked.
- Deterministic fresh-chat handoff and negative false-safe fixtures must pass locally and in CI.
  No cross-model behavior matrix is currently certified; model/host scenarios remain a pilot gate
  until each explicit model and version is executed and its evidence recorded.
