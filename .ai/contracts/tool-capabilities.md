# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki/test-plan reads + project-scoped text search | `ado-readonly/*` local stdio MCP (`@azure-devops/mcp`, version-pinned, domains bounded to work-items/wiki/test-plans/search) | intake, feature health, QA sync, handover, search-ado |
| Reconciled Salesforce org identity | `salesforce-readonly/review_org_identity` | investigator, design, review |
| Reconciled installed package inventory | `salesforce-readonly/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce-readonly/review_object_contract` | investigator, design, review, QA |
| Scoped enumeration of configured org aliases (requires `safety.allowScopedEnumeration`) | `salesforce-readonly/review_configured_orgs` or `scripts/salesforce_read.py orgs` | investigator |
| Composed read-only SOQL (verbatim, Salesforce MCP transport only, unredacted single-source rows) | `salesforce-readonly/review_soql_query` | investigator, design, development, knowledge curation |
| Guarded structured record read (allowlisted objects, bounded rows, no free-form SOQL) | `scripts/salesforce_read.py records` guarded terminal command | investigator, review |
| Guarded metadata retrieve (allowlisted types → ignored cache dir) | `scripts/salesforce_read.py retrieve` guarded terminal command | investigator, review |
| Salesforce non-production source retrieve into the project (per-invocation human confirmation; the only direct `sf` command not denied) | `sf project retrieve start` guarded terminal command | development only |
| Browser exploration/test generation | pinned `playwright-cli` through guarded terminal execution | Test Strategist only |
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
and vendor payloads are not exposed to an agent. MCP/CLI agreement is transport corroboration from
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

Policy (owner decision 2026-07-31): any proven non-production org may be read. With
`salesforce.review.allowAnyNonProduction` enabled, an alias absent from local configuration is
admitted on live identity proof alone — a canonical sandbox, scratch, or Developer Edition host
whose `Organization.IsSandbox` value matches that signature — and the proven identity is frozen
for the rest of the session. Configured entries keep their pinned host/organization-ID lane, and
an entry marked `environment: "production"` is a hard deny the toggle never overrides. Production
signatures stay refused in every lane.

For record-level reads and metadata retrieval, the investigator and reviewer roles use the guarded
`scripts/salesforce_read.py` wrapper rather than raw CLI. It never accepts a free-form SOQL string:
the caller supplies an allowlisted object, a validated field list, a bounded row limit (≤200), and
an optional simple `ORDER BY`; the wrapper constructs the `SELECT`, proves the target is a live
non-production org, and there is no `WHERE`/subquery surface, so cross-object or arbitrary reads
are impossible. `retrieve` pulls only allowlisted metadata types into an ignored cache directory and
never writes to the org or tracked source. Object access is bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` opts into every object
(the object name is still API-name validated, so injection is impossible, but any object becomes
readable). On a full-copy sandbox that means record reads can reach copied production data across
all objects — prefer an explicit list when the org holds sensitive data, or restrict which roles
hold record-read access (currently investigator and reviewer only).

Development mode exists only as a launcher lane (`start_salesforce_mcp.mjs --mode development`),
not as a configured MCP server: `.vscode/mcp.json` registers no `salesforce-development` entry and
`validate_harness.py` fails if one reappears (owner decision 2026-07-14), so no agent-facing
`salesforce-development` tool surface exists; the safety hook keeps its dev-tool classifier as
defense in depth. If a human starts that lane it registers only metadata, testing, and
code-analysis toolsets for one locally authorized alias granting `allowAgentWrite`, requires the
shared-sandbox approval reference, is disabled on Windows, and still proves live non-production
identity first. It does not enable broad data tools, `ALLOW_ALL_ORGS`, default orgs, users,
DevOps Center, or non-GA tools. Ordinary development work needs none of it: reads go through the
facade, repository edits stay in `force-app`/`manifest`/`tests/e2e`, org retrieves use
`sf project retrieve start` behind a per-invocation human confirmation (every other direct
`sf`/`sfdx` invocation is denied), and deploys are always performed by a human.
