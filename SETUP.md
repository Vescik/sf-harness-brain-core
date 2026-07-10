# Setup and Operations

## 1. Prerequisites

- VS Code 1.112+ on macOS/Linux; certify current stable for team rollout. Windows pilot support is
  read-only for external Salesforce/browser workflows because MCP sandboxing is unavailable.
- Consolidated GitHub Copilot extension and the recommendations in `.vscode/extensions.json`.
- Git, Python 3.11+, Node.js 20+, Salesforce CLI, and `@playwright/cli@0.1.17` when
  browser generation is used.
- Local Salesforce CLI authorization for approved non-production aliases. Authenticate manually;
  never give credentials or session material to an agent.

Use a dedicated pilot OS account, VM, or container. Authorize only the approved sandboxes in that
environment and use a separate browser profile containing no production session. A human must
confirm the authorization inventory before opening VS Code. Do not use built-in/default Agent mode
or an arbitrary terminal for ADO, Salesforce, or browser work; only the five custom agents are in
the certified enforcement boundary.

See [docs/compatibility.md](docs/compatibility.md) for the tested contract.

## 2. Clone and workspace layout

```bash
git clone https://github.com/Vescik/sf-harness-brain-core.git
git clone <salesforce-metadata-repository-url> salesforce-metadata
code sf-harness-brain-core/sf-harness.code-workspace
```

Both repositories must share a parent directory. The workspace names them `brain-core` and
`salesforce`. Metadata-dependent skills reject missing or ambiguous roots.

## 3. Local configuration

Copy `config/harness.example.json` to ignored `config/harness.local.json`, then replace every
placeholder with approved values. Do not add production aliases/origins. Only a development alias
may set `allowAgentWrite: true`. The example deliberately disables all writes. Enable a
development alias only after setting `safety.sharedSandboxWritesApproved: true` and recording the
human decision/work-item in `sharedSandboxApprovalRef`.

The file holds identifiers and paths, not secrets. ADO uses OAuth through VS Code; Salesforce uses
existing CLI authorization; Playwright uses a human-created persistent profile outside Git.
Alias names and environment labels are not treated as proof: Salesforce MCP startup first checks
the locally authorized sandbox instance hostname, then queries `Organization.IsSandbox`, and stops
unless Salesforce returns `true`. Direct agent use of `sf`, `sfdx`, or an unguarded Salesforce MCP
launcher is denied.

Set `ADO_ORGANIZATION` to the exact non-secret organization slug in local configuration before
opening VS Code. The MCP URL uses this environment variable, preflight requires equality, and the
global hook also requires every ADO tool call to carry the configured project:

```bash
# macOS/Linux
export ADO_ORGANIZATION="example-org"
# Windows PowerShell
$env:ADO_ORGANIZATION = "example-org"
```

Launch VS Code from the environment where this variable is set, or configure it through the
approved workstation-management mechanism. Do not substitute an independent organization prompt.

## 4. Install validation dependencies

```bash
python3 -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
npm install --global @playwright/cli@0.1.17
python3 scripts/validate_harness.py
python3 -m unittest discover -s tests -v
python3 scripts/run_evals.py
python3 scripts/preflight.py
```

Use the equivalent `py -3` command on Windows when a virtual environment is not active. The same
commands are available through `Terminal: Run Task` as Harness: Validate, Harness: Test, Harness:
Evals, and Harness: Preflight.

## 5. Verify Copilot customizations

1. Trust both workspace roots only after reviewing them.
2. Open **Chat: Open Customizations** / Chat Diagnostics.
3. Confirm exactly five agents, seven public prompts, twelve internal skills, three Principle
   files, the safety hook, and three MCP servers without diagnostics.
4. Confirm `/` shows the seven prompts once each and their argument hints.
5. Verify Solution Designer and Development Assistant handoff buttons use `send: false`.
6. Run one harmless read-only call through `ado-readonly` and `salesforce-readonly`.
7. Run a negative canary: a request to deploy/query production must be denied.

## 6. External runtimes

- `ado-readonly` uses the Azure-hosted remote MCP with `wit,wiki,testplan` toolsets and
  `X-MCP-Readonly: true`.
- Salesforce servers start through `scripts/start_salesforce_mcp.mjs`, which rejects aliases not
  allowlisted by local configuration. The development server exposes writes only for the approved
  development alias.
- Browser workflows use `scripts/playwright_guard.py`, not direct CLI or an MCP server. The wrapper
  exposes a narrow non-credential command set, uses the configured profile, checks current/all-tab
  origins around every action, and closes the session on drift. State-changing UI actions still
  require per-operation human confirmation.

## 7. Team workflow

- Pull before starting work.
- Create a branch; do not commit directly to `main`.
- Review generated `.ai/knowledge`, Memory, QA, and taxonomy changes carefully; raw cache and
  unreviewed `output/` remain ignored.
- Run validation and tests before pushing.
- Open a PR and obtain the owners/reviewers required by repository governance.
- Never use broad `git add -A` in a mixed workspace; stage intentional paths.

## 8. Troubleshooting

- Missing customizations: check VS Code version, workspace file, Settings UI, and Chat Diagnostics.
- MCP server missing: run `MCP: List Servers`; validate local config and OAuth/CLI authorization.
- Salesforce server blocked: verify the exact alias and permission in `harness.local.json`; never
  bypass the wrapper with `ALLOW_ALL_ORGS` or a default org.
- Metadata root missing: clone/link the SFDX repository as sibling `salesforce-metadata`.
- Preflight failure: fix the reported dependency/configuration; do not ask the model to bypass it.

## 9. Human-owned rollout blockers

Before a real developer pilot, provide company naming/review policy, shared-sandbox coordination,
complete high-risk package rules with sources, the Invoice update condition, ADO project/query,
approved Salesforce aliases, allowed browser origins/profile, and promoted tests path. The harness
will remain conservative while any relevant value is unknown.
