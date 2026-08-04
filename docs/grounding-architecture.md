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

Agents never receive raw Salesforce CLI, aliases, directories, Tooling flags, or raw vendor
payloads. Composed read-only SOQL is permitted — and, for record data-shape questions,
recommended (owner decisions 2026-07-30 and 2026-08-04) — through the governed
`salesforce-readonly` facade's `review_soql_query` tool only. The 2026-08-04 decision removed
the statement blockade: the statement executes verbatim over the pinned Salesforce MCP (never
the CLI) against the identity-proven non-production org, and rows return unredacted in a
single-source envelope. An explicitly configured `review.allowedObjectApiNames` list is still
honored. The facade exposes only:

- `review_org_identity`
- `review_installed_packages`
- `review_object_contract`
- `review_configured_orgs` (only when `safety.allowScopedEnumeration` is enabled; lists the
  locally configured aliases and permissions only — never unconfigured orgs, ids, or hosts)
- `review_soql_query` (composed read-only SOQL; executed verbatim, single-source, rows
  unredacted)

The facade binds one configured allowlisted non-production org (sandbox, scratch org, or an owner-admitted Developer Edition), runs fixed evidence profiles — plus
verbatim composed statements for `review_soql_query` — through the pinned
Salesforce MCP and a private CLI allowlist, sanitizes the profile receipts, and reconciles what
is dual-sourced. Results are `VERIFIED`, `MISMATCH`, `INCOMPLETE`, or `BLOCKED`.

MCP/CLI agreement corroborates transport from the same org; it is not an independent source of
business or vendor truth. Mismatch, truncation, schema drift, identity failure, or one missing
transport prevents Knowledge promotion and `SAFE`.

## Knowledge boundary

Knowledge is the one-file entry model (the v1 claim registry retired 2026-08-03; see
`docs/knowledge-one-file-contract.md` for the normative contract):

- Agents may create and edit `draft` entries only; approval is digest-pinned and human
  (`entry-approve`/`feature-approve` through the chat confirmation dialog, or a human terminal).
- An approved entry is citable at its approved digest; editing the source or the entry reopens
  a draft — stale approvals never carry forward silently.
- Different environments, package versions, or repository lineages remain separate scopes.
- Raw records, secrets, credentials, broad org payloads, and chain-of-thought are never committed.
- Reference-data snapshots are the one governed record-value path: for a single human-allowlisted
  configuration object, `investigate-config-records` reads bounded rows through the
  `review_soql_query` facade tool, strips Ids/URLs/audit surfaces, and captures a sanitized,
  digest-bound snapshot — not a raw record dump; approval still requires a human, and the
  snapshot drifts only via re-observation because no repository commit backs it.
- Human review and approval receipts are currently hash-bound assertions. Their actor identity is
  not independently provider- or signature-verified; team-wide rollout remains blocked on that
  authenticity control.

## Handoff boundary

Each governed item has a per-record directory containing machine state, narrative design, immutable
evidence references, and handoffs. Approval binds to scope/design hashes. Every mutation requires an
expected revision. Handoff consumption validates the target role, record revision, hashes, evidence,
and repository lineage. A new chat must resume from `recordId` and `handoffId` alone.

## Acceptance gates

- Every material fact in a design/review is grounded in an approved-current Knowledge entry.
- Every trusted entry is schema-valid, human-approved at its current digest, and in scope.
- No model-only inference is verified Knowledge.
- No incomplete/mismatched org review or source/org drift yields `SAFE`.
- Direct CLI, default org, and production remain blocked; composed read-only SOQL executes
  only through the identity-gated facade, verbatim over the Salesforce MCP transport.
- Deterministic fresh-chat handoff and negative false-safe fixtures must pass locally and in CI.
  No cross-model behavior matrix is currently certified; model/host scenarios remain a pilot gate
  until each explicit model and version is executed and its evidence recorded.
