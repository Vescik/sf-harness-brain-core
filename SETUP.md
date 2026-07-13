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

> **Runtime enforcement depends on your VS Code build.** The custom-agent/tool hooks
> (`.github/hooks/`, `chat.hookFilesLocations`, `chat.useCustomAgentHooks`) and the `.vscode/mcp.json`
> `sandbox`/`sandboxEnabled` filesystem and network confinement are recent/preview Copilot surfaces.
> Where a build does not implement them, they are silently ignored and the guard scripts never run —
> reducing the harness to prompt-level guidance. Before relying on this workspace for governed work,
> verify in your exact VS Code version that (a) each `chat.*` customization key resolves in the
> Settings UI (no "Unknown Configuration Setting"), (b) the `PreToolUse` hooks actually fire, and
> (c) the MCP sandbox is honored. If any is unsupported, treat the corresponding controls as
> advisory and enforce equivalents inside the MCP wrapper scripts. The `scripts/*_guard.py` and
> `scripts/copilot_safety_hook.py` logic is unit-tested and correct in isolation; what is
> build-dependent is whether VS Code invokes it.

## 2. Clone and workspace layout

```bash
git clone <your-fork-url> sf-harness-brain-core
code sf-harness-brain-core/sf-harness.code-workspace
```

This is one Git repository and one Salesforce DX project. The repository root is the SFDX root;
do not create a nested Salesforce project or clone a second metadata repository. The workspace
presents exactly one named folder: `brain-core` → repository root (`.`).

Opening `sf-harness.code-workspace` is preferred, but opening the repository folder directly is
supported. MCP servers and tasks use `${workspaceFolder}` without a folder-name qualifier, so the
folder does not need to be displayed as `brain-core` for variable resolution.

Confirm `sfdx-project.json`, `force-app/`, `manifest/package.xml`, and `tests/e2e/` are present at
the repository root before continuing. Metadata-dependent skills reject a missing or ambiguous
root rather than searching subfolders, parent directories, sibling directories, or other checkouts.

## 3. Local configuration

From the repository root, copy `config/harness.example.json` to ignored
`config/harness.local.json`, then replace every placeholder with approved values. Keep
`workspace.salesforceRootName` set to `brain-core`; manifest and promoted-test paths are relative
to the repository/SFDX root. Do not add production aliases/origins. For each review-enabled
alias, record the exact expected sandbox hostname and organization ID, explicitly allow agent
review, configure the package namespaces and component API-name allowlist, and keep the review API
version/current evidence window deliberate. Only a development alias
may set `allowAgentWrite: true`. The example deliberately disables all writes. Enable a
development alias only after setting `safety.sharedSandboxWritesApproved: true` and recording the
human decision/work-item in `sharedSandboxApprovalRef`.

The checked-in `manifest/package.xml` is only a generic starter. Narrow it to the exact components
in the accepted work record before retrieve, validation, or deployment; a wildcard does not grant
scope and must not be used as a substitute for claim-backed ownership or human approval.

The file holds identifiers, allowlists, and paths, not secrets. ADO uses OAuth through VS Code; Salesforce uses
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
python -m pip install --require-hashes -r requirements-dev.lock
npm ci --ignore-scripts
npm install --global @playwright/cli@0.1.17
python scripts/validate_harness.py
python -m unittest discover -s tests -v
python scripts/run_evals.py
python scripts/preflight.py
npm run prettier:verify
npm run lint
npm run test:unit:ci
```

Use the equivalent `py -3` command on Windows when a virtual environment is not active. The same
commands are available through `Terminal: Run Task` as Harness: Validate, Harness: Test, Harness:
Evals, and Harness: Preflight.

## 5. Verify Copilot customizations

1. Trust the cloned repository only after reviewing it; the single named workspace folder
   `brain-core` resolves to its root.
2. Open **Chat: Open Customizations** / Chat Diagnostics.
3. Confirm exactly five agents, ten public prompts, fourteen internal skills, three Principle
   files, the safety hook, and three MCP servers without diagnostics.
4. Confirm `/` shows the ten prompts once each and their argument hints.
5. Verify Solution Designer and Development Assistant handoff buttons use `send: false`.
6. Run one harmless ADO read, then the three bounded Salesforce review calls against the configured
   synthetic/pilot component. Confirm no raw CLI/query/alias or sensitive payload appears in Chat.
7. Run a negative canary: a request to deploy/query production must be denied.

## 6. External runtimes

- `ado-readonly` uses the Azure-hosted remote MCP with `wit,wiki,testplan` toolsets and
  `X-MCP-Readonly: true`.
- `salesforce-readonly` starts through `scripts/salesforce_review_server.mjs`. It binds one exact
  review-enabled sandbox and exposes only identity, configured-package, and allowlisted-object
  review. Internally it reconciles fixed Salesforce MCP and private CLI receipts, redacts raw
  identity/record payloads, and returns `VERIFIED`, `MISMATCH`, `INCOMPLETE`, or `BLOCKED`.
- The model never receives direct `sf`/`sfdx`, arbitrary SOQL, an alias, directory, Tooling flag,
  `list_all_orgs`, or raw vendor output. MCP/CLI agreement is transport corroboration from the same
  org, not independent package/business authority.
- Salesforce development starts separately through `scripts/start_salesforce_mcp.mjs`, which
  rejects aliases not allowlisted by local configuration and exposes writes only for the approved
  development alias. Its reads use the review facade.
- Browser workflows use `scripts/playwright_guard.py`, not direct CLI or an MCP server. The wrapper
  exposes a narrow non-credential command set, uses the configured profile, checks current/all-tab
  origins around every action, and closes the session on drift. State-changing UI actions still
  require per-operation human confirmation.

## 7. Team workflow

- Pull before starting work.
- Create a branch; do not commit directly to `main`.
- Investigators prepare sanitized schema-v3 YAML only in ignored `.cache/knowledge-proposals/` and
  use the guarded `propose` command to create immutable evidence and `proposed` claims. A named human uses
  the Knowledge review/promotion command before a claim becomes trusted; raw cache and unreviewed
  `output/` remain ignored.
- Resume governed work from `recordId` and `handoffId`. Validate record revision, role, scope/design
  hashes, approval, evidence, and repository commits; chat history is not workflow state.
- Agents stop at `design/awaiting_human`. After reviewing the persisted record and design, a named
  human may bind approval from a direct terminal outside Copilot with the exact guarded command:

  ```bash
  python scripts/work_record.py approve \
    --record-id "$RECORD_ID" \
    --expected-revision "$RECORD_REVISION" \
    --expected-record-hash "$RECORD_HASH" \
    --expected-design-hash "$DESIGN_HASH" \
    --approver "$APPROVER" \
    --mechanism human-terminal \
    --approval-ref "$APPROVAL_REF"
  ```

  The global Copilot hook always denies agent-originated invocation of this subcommand. Approval
  never comes from chat text, an agent confirmation, or a manually edited record. In the current
  controlled pilot the approver identity/reference is human-asserted and hash-bound, not verified
  through a provider API or signature; close that identity-authenticity gate before team-wide use.
- Run validation and tests before pushing.
- Open a PR and obtain the owners/reviewers required by repository governance.
- Never use broad `git add -A` in a mixed workspace; stage intentional paths.

## 8. Troubleshooting

- Missing customizations: check VS Code version, workspace file, Settings UI, and Chat Diagnostics.
- MCP server missing: run `MCP: List Servers`; validate local config and OAuth/CLI authorization.
  If VS Code reports that `workspaceFolder` cannot be resolved, pull the current configuration,
  confirm `.vscode/mcp.json` contains `${workspaceFolder}` without `:brain-core`, then restart the
  MCP server or reload the window.
- Salesforce review blocked: verify the exact alias, expected hostname/organization ID, review
  permission, package namespace, component allowlist, pinned runtime, and dual-source result. Never
  bypass the facade with raw MCP, `ALLOW_ALL_ORGS`, a default org, or direct CLI.
- Salesforce project missing: restore root `sfdx-project.json`, `force-app/`, `manifest/`, and
  `tests/e2e/` from this repository; do not fall back to a subfolder, parent/sibling directory, or
  second checkout.
- Preflight failure: fix the reported dependency/configuration; do not ask the model to bypass it.

## 9. Human-owned rollout blockers

Before a real developer pilot, provide company naming/review policy, shared-sandbox coordination,
the real package/component ownership and risk registry with version-scoped sources, ADO
project/query, approved Salesforce aliases, allowed browser origins/profile, and promoted tests path. The harness
will remain conservative while any relevant value is unknown.
