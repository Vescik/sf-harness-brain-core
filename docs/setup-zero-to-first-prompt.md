# Zero to First Prompt — complete manual setup walkthrough

This guide assumes **nothing**: a fresh Windows machine, no tools installed, and no prior
knowledge of this workspace. Every step shows the exact command, what success looks like, and
what to do when it fails. It is the manual alternative to the guided script
(`python scripts/first_launch.py`) — you can switch to the script at any point after Part 2.

macOS/Linux users: the flow is identical; path and activation differences are called out inline.

**What you are setting up.** This repository is a governed GitHub Copilot workspace ("harness")
for Salesforce development around a closed managed package. It gives Copilot five specialized
agents, guarded read-only access to Azure DevOps and a Salesforce sandbox, and safety rails that
fail closed. Nothing here contains credentials; you authorize everything locally in Parts 6–7.

**Scope (important).** The MCP surface is **read-only on every platform**: repository work, ADO
reads, and read-only Salesforce org access all work; agents never deploy to the org. The only raw
Salesforce CLI an agent may request is `sf project retrieve start`, and it always stops for your
approval. Guarded browser (Playwright) execution remains macOS/Linux-only (see
`docs/compatibility.md`).

---

## Part 1 — Install the tools

Open **PowerShell** (Start menu → type `powershell`). After each install, **close and reopen**
PowerShell before running the check — PATH changes only apply to new windows.

### 1.1 Git

- Download from <https://git-scm.com/download/win> and run the installer with default options,
  or with winget: `winget install --id Git.Git -e`
- Check: `git --version` → prints something like `git version 2.45.0.windows.1`

### 1.2 Python 3.12

- Download the latest 3.12.x from <https://www.python.org/downloads/windows/> and run it.
- **On the first installer screen tick "Add python.exe to PATH"** — this checkbox is off by
  default and skipping it is the most common setup mistake.
- Or with winget: `winget install --id Python.Python.3.12 -e`
- Check: `python --version` → `Python 3.12.x`
- If `python --version` opens the Microsoft Store or fails while `py --version` works: re-run
  the installer → Modify → tick the PATH option, or disable the Store alias under
  Settings → Apps → Advanced app settings → App execution aliases.
- The supported baseline is Python 3.11+; CI certifies 3.12, so install 3.12.

### 1.3 Node.js 24

- Download the Node 24 (LTS) Windows installer from <https://nodejs.org/> and run it with
  default options, or: `winget install --id OpenJS.NodeJS.LTS -e`
- Check: `node --version` → `v24.x.x` (22.19+ is the minimum; 24 matches `.nvmrc` and CI), and
  `npm --version` prints a version.

### 1.4 Salesforce CLI

- Download the Windows x64 installer from
  <https://developer.salesforce.com/tools/salesforcecli> and run it, or:
  `winget install --id Salesforce.sf -e`
- Check: `sf --version` → `@salesforce/cli/2.x.x ...`

### 1.5 VS Code + GitHub Copilot

- Install VS Code from <https://code.visualstudio.com/> (or `winget install -e --id Microsoft.VisualStudioCode`).
- Open VS Code → Extensions view (`Ctrl+Shift+X`) → install **GitHub Copilot** and sign in with
  your GitHub account when prompted (your organization must have a Copilot license for you).
- Check: the Copilot Chat icon appears in the VS Code sidebar/title bar.

If your organization blocks installers or winget, request Git, Python 3.12, Node 24, Salesforce
CLI, and VS Code through your IT software catalog — no admin-only or unusual components are used.

---

## Part 2 — Get the workspace

Pick a folder you own (example: `C:\dev`) and clone the repository. Your team lead gives you the
repository URL and access.

```powershell
cd C:\dev
git clone <repository-url> sf-harness-brain-core
code sf-harness-brain-core\sf-harness.code-workspace
```

VS Code opens and asks whether you trust the workspace. Review the folder, then choose **Trust**
(the Copilot customizations do not load in Restricted Mode). When VS Code offers the
workspace-recommended extensions, install them.

> From here on, the guided script can do Parts 3–8 for you: open the VS Code terminal
> (`` Ctrl+` ``) and run `python scripts\first_launch.py`. It is plain Python — no PowerShell
> execution policy involved. To continue manually, keep going.

---

## Part 3 — Python environment

In the VS Code terminal (`` Ctrl+` ``), from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock
```

Success ends with `Successfully installed jsonschema... PyYAML...`. The `--require-hashes` flag
verifies every downloaded package against the pinned checksums — do not replace this command
with a plain `pip install`.

**Now select the interpreter (required, easy to miss):** Command Palette (`Ctrl+Shift+P`) →
**Python: Select Interpreter** → pick the entry ending in `.venv\Scripts\python.exe`. Without
this, harness scripts later fail with `ModuleNotFoundError: No module named 'jsonschema'`.

macOS/Linux: `python3 -m venv .venv`, then use `.venv/bin/python` in place of
`.\.venv\Scripts\python.exe` throughout.

## Part 4 — Node dependencies

```powershell
npm ci --ignore-scripts
```

Success prints `added NNN packages`. Use exactly `npm ci --ignore-scripts` — not `npm install`
(which can rewrite the lockfile) and not without `--ignore-scripts` (which would run arbitrary
package install scripts).

`npm audit` will report ~24 known advisories afterwards. **This is expected and formally
accepted** — they are transitive to Salesforce's own pinned tooling and not fixable on stable
channels today; see `SECURITY.md` and the 2026-07-13 entry in `.ai/memory/decisions-log.md`.
Do not run `npm audit fix --force`.

## Part 5 — First verification checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py
```

Expected: `PASS: harness validation (…N checks)`. If this fails, your clone or install is
incomplete — fix that before continuing.

```powershell
.\.venv\Scripts\python.exe scripts\preflight.py
```

Expected **at this stage**: `ERROR: config/harness.local.json still contains <PLACEHOLDER>
values` (or that the file is missing). That is correct — the harness fails closed until Part 6
is done. Any other error means a real problem.

---

## Part 6 — Local configuration

Create your machine-local config from the tracked example:

```powershell
Copy-Item config\harness.example.json config\harness.local.json
```

This file is **gitignored**: it never leaves your machine and is never committed. Open it in
VS Code and replace the `<PLACEHOLDER>` values. You cannot invent these — get them from your
team lead / harness maintainer:

| Field | What it is | Where it comes from |
|---|---|---|
| `ado.organization` | Azure DevOps organization slug (e.g. `contoso`, not a URL) | team lead |
| `ado.project` | ADO project name | team lead |
| `ado.releaseQueryId` | Saved ADO query id for release scope (only release flows need it) | team lead |
| `salesforce.orgs[].alias` | Your local alias for each sandbox (you choose it; reuse it in Part 7) | you |
| `salesforce.orgs[].expectedInstanceHost` | The sandbox My Domain host | filled in Part 7 |
| `salesforce.orgs[].expectedOrganizationId` | The sandbox org id | filled in Part 7 |
| `salesforce.review.allowedObjectApiNames` | Objects the agent may read via the review facade | team lead (keep narrow) |
| `browser.profileDirectory` | Playwright browser profile path | skip on Windows (browser mode is macOS/Linux only) |

Leave every `allowAgentWrite` as `false`. Write mode is a separate, human-approved decision and
does not run on Windows at all.

## Part 7 — Set `ADO_ORGANIZATION` and authorize a sandbox

### 7.1 The environment variable (the #1 setup pitfall)

The ADO MCP server URL is built from an **environment variable**, and the safety hook requires
it to exactly equal `ado.organization` in your config. Set it persistently:

```powershell
setx ADO_ORGANIZATION "your-org-slug"
```

Then **fully quit VS Code** (all windows — check no `Code.exe` remains in Task Manager) and
reopen it. "Reload Window" is NOT enough; environment variables are read at process launch.
Verify in a new terminal: `echo $env:ADO_ORGANIZATION` prints your slug.

macOS/Linux: `export ADO_ORGANIZATION="your-org-slug"` in your shell profile, then launch VS
Code from that shell.

### 7.2 Authorize the sandbox

Ask your team lead which sandbox to use and its login URL. Then (alias must match Part 6):

```powershell
sf org login web --instance-url https://test.salesforce.com --alias my_review_sbx
```

A browser opens; sign in with **your own** sandbox user. Never paste credentials into a
terminal, a file, or Copilot chat. Then read the org identity:

```powershell
sf org display --target-org my_review_sbx --json
```

From the JSON `result`, copy the host part of `instanceUrl` (looks like
`mydomain--sbxname.sandbox.my.salesforce.com`) into `expectedInstanceHost` and `id` into
`expectedOrganizationId` in `config\harness.local.json`. Only genuine sandboxes are accepted:
the host must match `*--*.sandbox.my.salesforce.com` and the org must report `IsSandbox=true` —
production and Developer Edition orgs are refused by design.

## Part 8 — Final verification

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py                            # structure
.\.venv\Scripts\python.exe scripts\preflight.py --capability ado                  # ADO wiring
.\.venv\Scripts\python.exe scripts\preflight.py --capability salesforce-review    # sandbox wiring
.\.venv\Scripts\python.exe -m unittest discover -s tests                          # optional, ~20s
```

All should PASS now. If `--capability ado` fails on "ADO_ORGANIZATION must exactly match",
re-check Part 7.1 (exact slug, no trailing spaces, VS Code fully restarted).

## Part 9 — First Copilot prompt

1. VS Code may prompt *"The MCP servers … Start them now?"* — start **`salesforce-readonly`**
   and **`ado-readonly`** (the only configured servers; both are read-only).
2. When prompted for the `sf_read_org` input, enter your sandbox alias (e.g. `my_review_sbx`).
3. Reduce approval clicks: Command Palette → **Chat: Manage Tool Approval** → trust all tools
   under `salesforce-readonly` and `ado-readonly` at **workspace** scope. Never enable global
   auto-approve (`/yolo`).
4. Open Copilot Chat and run your first command:

   ```text
   /fetch-ado-item 12345
   ```

   (any real work-item id from your ADO project). The agent should return the item summary
   without ever showing raw CLI commands or credentials.
5. Sanity-check the rails with a negative test: ask the agent to query production. It must be
   denied.

**Where to go next:** `README.md` for the architecture, `SETUP.md` §5–7 for the full operating
model (work records, approvals, knowledge), and the eleven `/` prompt commands in Copilot Chat.

## When something fails

Read `.cache\denials.log` first — every hook denial is appended there as one JSON line with the
reason:

```powershell
Get-Content .cache\denials.log -Tail 20
```

Then use the symptom table in [windows-setup.md](windows-setup.md#troubleshooting--the-exact-errors-and-their-fixes).
The three most common failures are: `ADO_ORGANIZATION` not set / VS Code not fully restarted
(Part 7.1), the `.venv` interpreter not selected (Part 3), and placeholders still present in
`config\harness.local.json` (Part 6).
