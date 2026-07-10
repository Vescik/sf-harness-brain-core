# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki/test-plan reads | `ado-readonly/*` remote MCP, server-side read-only | intake, feature health, QA sync, handover |
| Salesforce org list and SOQL read | `salesforce-readonly/*` guarded DX MCP | investigator, design, review, QA |
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

Read-only mode registers `list_all_orgs` and `run_soql_query`. Development mode registers only
the pinned GA `metadata`, `testing`, and `code-analysis` toolsets plus those same two read tools
for one locally authorized, allowlisted, non-production alias. It starts in the named Salesforce
metadata root only after an approval reference enables shared-sandbox writes. It does not enable
the broad data-write toolset, `ALLOW_ALL_ORGS`, users, DevOps Center, or non-GA tools.
