# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki/test-plan reads + project-scoped text search | `ado-readonly/*` local stdio MCP (`@azure-devops/mcp`, version-pinned, domains bounded to work-items/wiki/test-plans/search) | intake, feature health, QA sync, handover, search-ado |
| Reconciled Salesforce org identity | `salesforce-readonly/review_org_identity` | investigator, design, review |
| Reconciled installed package inventory | `salesforce-readonly/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce-readonly/review_object_contract` | investigator, design, review, QA |
| Scoped enumeration of configured org aliases (requires `safety.allowScopedEnumeration`) | `salesforce-readonly/review_configured_orgs` | investigator |
| Composed read-only SOQL incl. record reads (verbatim, Salesforce MCP transport only, unredacted single-source rows) | `salesforce-readonly/review_soql_query` | investigator, design, development, knowledge curation |
| Salesforce non-production source retrieve into the project (per-invocation human confirmation; the only direct `sf` command not denied) | `sf project retrieve start` guarded terminal command | development only |
| Solution Design loop state (four tools: open, record, check, submit) | `solution-design/*` local stdio MCP (`scripts/solution_design_mcp_server.mjs` over one persistent internal worker) | design (guardrail-reviewer holds `design_check` read) |
| Human approval of a design candidate | the elicitation inside `solution-design/design_submit` (native VS Code MCP elicitation; digest-bound, single-use nonce) | named humans only |
| Interactive human confirmation | `vscode/askQuestions` | prompts and approval gates |
| Subagent delegation | `agent` plus explicit `agents` allowlist | Designer, Developer |

## Azure DevOps actions used

- `wit_work_item`: get, get_batch, list_comments, list_revisions
- `wit_query`: get, get_results
- `wit_work_item_attachment`: download only after MIME/size validation
- `wiki`: list/get operations only (`wiki_list_wikis`, `wiki_list_pages`, `wiki_get_page`,
  `wiki_get_page_content`); `wiki_create_or_update_page` is never used
- `search_wiki`, `search_workitem`: always with the configured `project` (the hook denies
  unscoped calls); `search_code` is exposed by the domain but unused
- `testplan`: list_plans, list_suites, list_cases

Exact dispatcher input schemas come from the running server and must be captured in sanitized
fixtures. The server organization comes only from `ADO_ORGANIZATION`, which must equal local
configuration; the global hook rejects calls without the configured project or with a mismatched
project/ADO URL. The local stdio server has no server-side read-only mode, and its domains do
include write-capable tools; agents are policy-bound to the read actions listed above (owner
decision 2026-07-14 — no hook denylist on ADO writes yet; revisit if governed ADO writes become
desirable).

## Salesforce tools used

The model-facing read server is a narrow local facade bound to one configured, exact non-production
alias. It exposes only the review tools above (configured-orgs enumeration is additionally gated
by `safety.allowScopedEnumeration` and reflects local configuration only — never unconfigured
orgs, ids, or hosts). Internally it executes fixed, checked-in query
profiles — plus validated composed read-only statements for `review_soql_query` — through the
pinned Salesforce MCP and a private Salesforce CLI allowlist, normalizes the
receipts, removes credentials/identity details/raw sensitive values, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

Raw `list_all_orgs`, raw `run_soql_query`, aliases, directories, Tooling flags, CLI commands,
and vendor payloads are not exposed to an agent.

## Solution Design runtime

`solution-design` is registered in `.vscode/mcp.json` only. `.github/mcp.json` stays
Knowledge-only because the human-bound approval surface this runtime depends on is native VS Code
MCP elicitation, which the CLI host does not provide.

Model-facing tools — exactly four: `design_open`, `design_record`, `design_check`,
`design_submit`. The loop runtime advises and never refuses a write; the single hard gate is
the human elicitation inside `design_submit`.

The request tools carry **no** answer, approval, decision or status field. They initiate an
elicitation; the client response selects the internal operation. The internal operations —
`record-human-input`, `confirm-candidate`, `request-candidate-revision`, `transfer-case-writer` —
are not tools and are never granted. A `solution-design/*` wildcard grant is a contract failure
and the validator rejects it.

The Node wrapper never computes a `caseVersion` or a `candidateDigest`: the Python core is the
single digest authority. See `.ai/contracts/solution-design-runtime.md` for the state machine,
closure authority and gate semantics. MCP/CLI agreement is transport corroboration from
the same org, not independent truth.

Policy (owner decision 2026-07-30, widened 2026-08-04): composed read-only SOQL is permitted —
and recommended whenever a task depends on record data structure — through the governed facade's
`review_soql_query` tool only, for the Solution Designer, Knowledge Curator, Development
Assistant, and Config Investigator roles. The 2026-08-04 decision removed the statement
blockade entirely: no grammar validation, no secret-adjacent object deny-set, no LIMIT
policing, no value redaction. The statement executes verbatim over the pinned Salesforce MCP
child — never the CLI — against the identity-proven non-production org, and rows return
unredacted (`attributes` noise stripped), bounded only by payload size and timeout. An
absent `review.allowedObjectApiNames` key means all objects (equivalent to `["*"]`) — an explicit
list remains supported and honored for orgs holding sensitive data. The raw paths above stay
denied regardless: SOQL never runs through raw CLI or raw vendor tools.

Policy (owner decision 2026-08-04, superseding the 2026-07-31 toggle): any proven
non-production org may be read, unconditionally — which org a developer connects is the
developer's responsibility. An alias absent from local configuration is admitted on live
identity proof alone — a canonical sandbox, scratch, or Developer Edition host whose
`Organization.IsSandbox` value matches that signature — and the proven identity is frozen for
the rest of the session. Entries carrying both identity pins keep the exact-org lane; pinless
entries use the same discovery proof. Two hard brakes remain: an entry marked
`environment: "production"` denies its alias, and any organization ID listed in
`salesforce.review.deniedOrganizationIds` is refused at proof time whatever alias resolves to
it. Production signatures stay refused in every lane.

Record-level reads run through `review_soql_query` alone: the guarded
`scripts/salesforce_read.py` CLI wrapper (structured record reads, cached metadata retrieve,
orgs listing) was retired on 2026-08-04 as a redundant second lane once composed SOQL was
unblocked. Metadata comes into the project only via the human-confirmed
`sf project retrieve start`. Object access is bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` (or omitting it)
opts into every object. On a full-copy sandbox that means record reads can reach copied
production data across all objects — prefer an explicit list when the org holds sensitive
data.

There is no development/write mode at all: the launcher's development lane was retired
2026-08-04 (it had been dead weight since the 2026-07-14 write-server removal — unreachable
from any configured surface, disabled on Windows, and guarded four ways). The launcher spawns
only the review facade; `.vscode/mcp.json` registers no `salesforce-development` entry and
`validate_harness.py` fails if one reappears; the safety hook keeps its dev-tool classifier as
defense in depth. Reads go through the facade, repository edits stay in
`force-app`/`manifest`/`tests/e2e`, org retrieves use `sf project retrieve start` behind a
per-invocation human confirmation (every other direct `sf`/`sfdx` invocation is denied), and
deploys are always performed by a human.
