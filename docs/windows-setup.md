# Windows Setup & MCP Fix — Step by Step

This is the practical runbook for running the brain-core harness on **Windows** in VS Code + GitHub
Copilot. The MCP surface is **read-only on every platform**: the read-only Salesforce facade and
ADO reads work in full; agents never deploy. The only raw Salesforce CLI an agent may request is
`sf project retrieve start`, which always stops for your approval.

> The single most common failure ("Blocked by Pre-Tool Use hook" / "Organization name is required")
> is **not** a config-file problem — it's a missing **`ADO_ORGANIZATION` environment variable**.
> See **Step 4**. That is the fix for the MCP issue.

---

## Step 1 — Prerequisites

Install and confirm each is on `PATH` (open a **new** PowerShell and run the checks):

| Tool | Requirement | Check |
|---|---|---|
| VS Code + GitHub Copilot / Copilot Chat | current stable | — |
| Python | **3.11+**, exposed as **`python`** (python.org installer; this repo uses `python`, not `py -3`) | `python --version` |
| Node.js | **22+** (the pinned `@salesforce/mcp` needs ≥22.19) | `node --version` |
| Salesforce CLI | v2 | `sf --version` |
| Git | any recent | `git --version` |

If `python --version` fails but `py --version` works, add Python to PATH (re-run the installer →
"Add python.exe to PATH") so plain `python` resolves.

## Step 2 — Get the workspace and open it

```powershell
git clone <your-fork-url> sf-harness-brain-core
code sf-harness-brain-core\sf-harness.code-workspace
```

Open the `sf-harness.code-workspace` (single-root `brain-core`). Trust the workspace only after you
have reviewed it.

## Step 3 — Install dependencies (guided)

From the repo root, run the onboarding script (it checks prerequisites, installs the pinned
dependencies, creates `config\harness.local.json`, collects ADO settings, and walks sandbox
authorization). It is plain Python — no PowerShell execution policy is involved, so it also works
in organizations where `.ps1` scripts are blocked:

```powershell
python scripts\first_launch.py
```

Manual equivalent, if you prefer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
npm ci --ignore-scripts
```

**Then select the `.venv` interpreter** (required): Command Palette → **Python: Select Interpreter**
→ choose `.venv`. The agents run guarded scripts as `python scripts/<name>.py …`, and VS Code's
integrated terminal only resolves `python` to the venv (with `jsonschema`/`PyYAML`) after you select
it. Without this, commands fail with `ModuleNotFoundError: No module named 'jsonschema'`.

## Step 4 — ⭐ Fix the MCP block: set `ADO_ORGANIZATION` (this is the fix)

Putting the org in `config\harness.local.json` is **necessary but not sufficient**. The local ADO
MCP server receives its organization from `${env:ADO_ORGANIZATION}` (an **environment variable**
in the server args), and the safety hook independently checks that the env var **exactly equals**
`ado.organization` in your config. If the env var is missing:

- the server gets no org argument → it fails to start, and
- the hook sees runtime-org `""` ≠ policy-org → **"Blocked by Pre-Tool Use hook"**.

The server also needs your own Azure sign-in once: `az login` (Azure CLI). Agents never see or
handle those credentials.

Set it to the **exact same org slug** as `ado.organization` in your config (the short slug, e.g.
`contoso` — not the full URL):

```powershell
# Option A — persistent (recommended). Sets a user env var; affects NEW processes only.
setx ADO_ORGANIZATION "your-org-slug"
#   then FULLY QUIT VS Code (all windows; confirm no Code.exe in Task Manager) and reopen.
#   "Reload Window" is NOT enough — env vars are read at process launch.

# Option B — per session (quick test). Launch VS Code FROM this same shell so it inherits the var.
$env:ADO_ORGANIZATION = "your-org-slug"
code .
```

Verify it took effect (in a shell that will launch VS Code):

```powershell
echo $env:ADO_ORGANIZATION        # must print your slug, matching config exactly
```

## Step 5 — Fill `config\harness.local.json`

This file is **gitignored** — it lives only on this machine and does not sync via git, so you fill
it here on Windows. Set at minimum:

- `ado.organization` — the org slug (must equal `ADO_ORGANIZATION` from Step 4)
- `ado.project` — your ADO project (the hook requires every ADO call to carry this)
- `ado.releaseQueryId` — your saved release query id (only for release flows)
- For each sandbox under `salesforce.orgs`: `alias`, `expectedInstanceHost`, `expectedOrganizationId`
- `salesforce.review.allowedObjectApiNames` — objects the agent may read; `["*"]` = all objects
  (keep tighter if the org holds sensitive data)

`python scripts\first_launch.py` fills the ADO and sandbox values for you interactively; edit the
file directly only if you skip the script. For a fully manual, zero-assumptions walkthrough see
[setup-zero-to-first-prompt.md](setup-zero-to-first-prompt.md).

## Step 6 — Authorize a sandbox (review-only)

Windows supports **review (read-only)** only. Authorize a genuine **sandbox** (full-copy or
partial) — the harness accepts `*--*.sandbox.my.salesforce.com` (or a scratch org). A Developer
Edition org (`*.develop.my.salesforce.com`, `IsSandbox=false`) is **rejected** on purpose.

```powershell
# alias MUST match the alias in harness.local.json
sf org login web --instance-url https://<MYDOMAIN>--<SANDBOX>.sandbox.my.salesforce.com --alias mpsa_dev_sbx
sf org display --target-org mpsa_dev_sbx --json
#   copy instanceUrl host -> expectedInstanceHost, id -> expectedOrganizationId in the config
```

> **There is no development/write MCP server** (removed 2026-07-14 — it produced the expected but
> confusing `exit code 2` startup error on Windows). Agents never mutate the org: reads go through
> `salesforce-readonly` and the guarded `salesforce_read.py`; metadata comes into the project only
> via human-approved `sf project retrieve start`; deploys are a human-run release step.

## Step 7 — Start the MCP servers

When VS Code prompts *"The MCP servers … may have new tools … Start them now?"*, start
**`salesforce-readonly`** and **`ado-readonly`** (the only configured servers). When prompted for
the `sf_read_org` input, enter your authorized sandbox alias (e.g. `mpsa_dev_sbx`).

## Step 8 — Pre-approve tools (fewer clicks)

- **Terminal scripts** are already pre-approved via `chat.tools.terminal.autoApprove` in settings —
  no action needed.
- **MCP read tools** cannot be pre-approved from a committed setting. Run **`Chat: Manage Tool
  Approval`** (Command Palette), expand `salesforce-readonly` and `ado-readonly`, and trust all
  their tools at **workspace** scope.

## Step 9 — Verify

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py          # structure OK
.\.venv\Scripts\python.exe scripts\preflight.py --capability ado             # PASS once env var == config
.\.venv\Scripts\python.exe scripts\preflight.py --capability salesforce-review   # PASS once sandbox authorized + config filled
```

Then in Copilot Chat: run `/fetch-ado-item <id>` and a Salesforce review. ADO calls should no
longer be blocked, and the read facade should return results.

---

## Troubleshooting — the exact errors and their fixes

**First stop for any "Blocked by Pre-Tool Use hook": read `.cache\denials.log`.** Both hooks append
every deny/ask there as one JSON line with timestamp, which hook fired, the role, the tool, and the
exact reason — so you no longer have to guess which guard blocked what:

```powershell
Get-Content .cache\denials.log -Tail 20
```

| Symptom | Cause | Fix |
|---|---|---|
| `Blocked by Pre-Tool Use hook` on ADO calls | `ADO_ORGANIZATION` env var unset or ≠ `ado.organization` | Step 4: set the env var to the exact slug, **fully restart** VS Code |
| `Organization name is required. Provide it as a parameter…` | ADO MCP URL is org-less because the env var is unset | Step 4 |
| `preflight --capability ado` fails: "ADO_ORGANIZATION must exactly match…" | env var missing or mismatched | Step 4 (exact match, no trailing spaces) |
| `Salesforce MCP startup blocked: development mode is disabled on Windows` / `exit code 2` | Stale MCP config — the `salesforce-development` server was removed 2026-07-14 | Pull the latest `main` and reload VS Code; only `salesforce-readonly` and `ado-readonly` should be listed |
| `MCP startup blocked: … Organization.IsSandbox … proof failed` | target org isn't a real sandbox, or config still has `<PLACEHOLDER>` values | Step 5/6: authorize a real sandbox, fill host/orgId |
| `webidl.util.markAsUncloneable is not a function` | Node < 22 | Install Node 22+ (Step 1) |
| ADO call still runs without being scoped / lists all orgs | Known hook-matching gap (see below) | Track the hardening fix; interim, do not rely on the hook to block bare-named MCP tools |

## Known limitations

- **Hook tool-name matching — FIXED.** The safety hook now classifies MCP tools by their bare tool
  token as well as the server prefix, hard-denies org/project enumeration (`core_list_orgs`,
  `core_list_projects`, `list_all_orgs`), and fails closed (asks) on any unrecognized MCP-shaped
  tool. Bare `core_list_orgs`/`run_soql_query`/`deploy_metadata` are no longer bypassable.
- **ADO toolset bounding — FIXED by the stdio switch.** The hosted endpoint did not honor the
  `X-MCP-Toolsets` header, so the harness now runs the local `@azure-devops/mcp` (version-pinned)
  whose `-d work-items wiki test-plans` domain args are actually honored. The local server has no
  server-side read-only mode; read-only remains harness policy (hooks + role guard) — an accepted
  owner decision (2026-07-14). Org-scope + enumeration guards stay the effective control.
