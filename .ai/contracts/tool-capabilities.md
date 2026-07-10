# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki/test-plan reads | `ado-readonly/*` remote MCP, server-side read-only | intake, feature health, QA sync, handover |
| Reconciled Salesforce org identity | `salesforce-readonly/review_org_identity` | investigator, design, review |
| Reconciled installed package inventory | `salesforce-readonly/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce-readonly/review_object_contract` | investigator, design, review, QA |
| Salesforce non-production metadata/test operations | `salesforce-development/*` guarded DX MCP | development only |
| Browser exploration/test generation | pinned `playwright-cli` through guarded terminal execution | Test Strategist only |
| Interactive human confirmation | `vscode/askQuestions` | prompts and approval gates |
| Subagent delegation | `agent` plus explicit `agents` allowlist | Designer, Developer |

## Azure DevOps remote actions used

- `wit_work_item`: get, get_batch, list_comments, list_revisions
- `wit_query`: get, get_results
- `wit_work_item_attachment`: download only after MIME/size validation
- `wiki`: list/get operations only
- `testplan`: list_plans, list_suites, list_cases

Exact dispatcher input schemas come from the running server and must be captured in sanitized
fixtures. The server organization comes only from `ADO_ORGANIZATION`, which must equal local
configuration; the global hook rejects calls without the configured project or with a mismatched
project/ADO URL. No ADO write tool is enabled in this version.

## Salesforce tools used

The model-facing read server is a narrow local facade bound to one configured, exact non-production
alias. It exposes only the three review tools above. Internally it executes fixed, checked-in query
profiles through the pinned Salesforce MCP and a private Salesforce CLI allowlist, normalizes both
receipts, removes credentials/identity details/raw records, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

Raw `list_all_orgs`, arbitrary `run_soql_query`, aliases, directories, Tooling flags, CLI commands,
and vendor payloads are not exposed to an agent. MCP/CLI agreement is transport corroboration from
the same org, not independent truth.

Development mode registers only approved metadata, testing, and code-analysis capabilities for one
locally authorized, allowlisted development sandbox. All reads use the facade. Development starts
in the named metadata root only after an approval reference enables shared-sandbox writes. It does
not enable broad data tools, `ALLOW_ALL_ORGS`, default orgs, users, DevOps Center, or non-GA tools.
