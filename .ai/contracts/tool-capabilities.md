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
| Guarded structured record read (allowlisted objects, bounded rows, no free-form SOQL) | `scripts/salesforce_read.py records` guarded terminal command | investigator, review |
| Guarded metadata retrieve (allowlisted types → ignored cache dir) | `scripts/salesforce_read.py retrieve` guarded terminal command | investigator, review |
| Salesforce non-production metadata/test operations | `salesforce-development/*` guarded DX MCP | development only |
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
profiles through the pinned Salesforce MCP and a private Salesforce CLI allowlist, normalizes both
receipts, removes credentials/identity details/raw records, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

Raw `list_all_orgs`, arbitrary `run_soql_query`, aliases, directories, Tooling flags, CLI commands,
and vendor payloads are not exposed to an agent. MCP/CLI agreement is transport corroboration from
the same org, not independent truth.

For record-level reads and metadata retrieval, the investigator and reviewer roles use the guarded
`scripts/salesforce_read.py` wrapper rather than raw CLI. It never accepts a free-form SOQL string:
the caller supplies an allowlisted object, a validated field list, a bounded row limit (≤200), and
an optional simple `ORDER BY`; the wrapper constructs the `SELECT`, proves the target is a live
non-production sandbox, and there is no `WHERE`/subquery surface, so cross-object or arbitrary reads
are impossible. `retrieve` pulls only allowlisted metadata types into an ignored cache directory and
never writes to the org or tracked source. Object access is bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` opts into every object
(the object name is still API-name validated, so injection is impossible, but any object becomes
readable). On a full-copy sandbox that means record reads can reach copied production data across
all objects — prefer an explicit list when the org holds sensitive data, or restrict which roles
hold record-read access (currently investigator and reviewer only).

Development mode registers only approved metadata, testing, and code-analysis capabilities for one
locally authorized, allowlisted development sandbox. All reads use the facade. Development starts
in the named metadata root only after an approval reference enables shared-sandbox writes. It does
not enable broad data tools, `ALLOW_ALL_ORGS`, default orgs, users, DevOps Center, or non-GA tools.
