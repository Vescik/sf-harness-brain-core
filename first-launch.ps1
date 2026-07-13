#Requires -Version 5.1
<#
.SYNOPSIS
    First-launch onboarding for the brain-core Salesforce Copilot harness (Windows).

.DESCRIPTION
    Human-run setup helper. It is NOT an agent tool and is deliberately not on the role-guard
    allowlist. It:
      1. checks prerequisites (git, node, npm, py, sf);
      2. installs the pinned dependencies (npm ci, hash-pinned pip lock into .venv);
      3. creates config/harness.local.json from the tracked example if absent;
      4. collects ADO configuration interactively;
      5. walks you through authorizing each SANDBOX (sf org login web), auto-fills the
         expected host + organization id from `sf org display`, and refuses to record any
         org that is not a genuine sandbox (mirrors SAFE-ENV-001);
      6. runs preflight / validate to confirm the setup.

    JSON edits are performed by Python (the harness already depends on it) rather than
    PowerShell's ConvertTo-Json, which mangles single-element arrays on Windows PowerShell 5.1.

    Windows note: only REVIEW (read-only) Salesforce mode is supported here; development/write
    mode requires macOS/Linux (MCP sandboxing is unavailable on Windows). Orgs are therefore
    configured for review only (allowAgentWrite = false).

    Credentials are never handled by this script: `sf org login web` performs interactive
    browser OAuth, and no tokens/passwords are read, printed, or stored.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\first-launch.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipInstall,   # skip npm ci / pip install (deps already present)
    [switch]$NonInteractive # only run checks + install + verify, no prompts or org authorization
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$ConfigPath  = Join-Path $RepoRoot 'config\harness.local.json'
$ExamplePath = Join-Path $RepoRoot 'config\harness.example.json'
$SandboxHostPattern = '^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com$'

function Write-Step  { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "    [ok] $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Fail        { param([string]$m) Write-Host "    [x]  $m" -ForegroundColor Red; exit 1 }

function Test-Tool {
    param([string]$Name, [string[]]$VersionArgs)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { return $null }
    try { return (& $Name @VersionArgs 2>&1 | Select-Object -First 1) } catch { return 'present' }
}

# ---------------------------------------------------------------------------
Write-Step 'Checking prerequisites'
$py = 'py'
$pyIsLauncher = $true
if (-not (Get-Command 'py' -ErrorAction SilentlyContinue)) {
    if (Get-Command 'python' -ErrorAction SilentlyContinue) { $py = 'python'; $pyIsLauncher = $false }
    else { Fail 'Python launcher not found. Install Python 3.11+ from python.org (includes the py launcher).' }
}
$checks = [ordered]@{
    'git'    = (Test-Tool 'git'  @('--version'))
    'node'   = (Test-Tool 'node' @('--version'))
    'npm'    = (Test-Tool 'npm'  @('--version'))
    'sf'     = (Test-Tool 'sf'   @('--version'))
    'python' = (Test-Tool $py    @('--version'))
}
foreach ($k in $checks.Keys) {
    if ($null -eq $checks[$k]) { Fail "$k is not installed or not on PATH." }
    Write-Ok "$k -> $($checks[$k])"
}

# ---------------------------------------------------------------------------
if (-not $SkipInstall) {
    Write-Step 'Installing pinned dependencies'
    Write-Host '    npm ci --ignore-scripts (exact lockfile; do not use npm install)'
    npm ci --ignore-scripts
    if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed.' }
    Write-Ok 'node_modules installed from package-lock.json'

    $venv = Join-Path $RepoRoot '.venv'
    if (-not (Test-Path $venv)) {
        Write-Host '    creating .venv'
        if ($pyIsLauncher) { & $py -3 -m venv $venv } else { & $py -m venv $venv }
        if ($LASTEXITCODE -ne 0) { Fail 'could not create .venv' }
    }
    $venvPy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPy)) { $venvPy = Join-Path $venv 'bin\python' }
    Write-Host '    pip install --require-hashes -r requirements-dev.lock'
    & $venvPy -m pip install --disable-pip-version-check --require-hashes -r (Join-Path $RepoRoot 'requirements-dev.lock')
    if ($LASTEXITCODE -ne 0) { Fail 'pip install (hash-pinned) failed.' }
    Write-Ok 'Python validation dependencies installed into .venv'
} else {
    Write-Step 'Skipping dependency install (--SkipInstall)'
}

$venvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { $venvPy = Join-Path $RepoRoot '.venv\bin\python' }
if (-not (Test-Path $venvPy)) { $venvPy = $py }

# ---------------------------------------------------------------------------
Write-Step 'Preparing local configuration'
if (-not (Test-Path $ConfigPath)) {
    Copy-Item $ExamplePath $ConfigPath
    Write-Ok 'created config\harness.local.json from the example template'
} else {
    Write-Ok 'config\harness.local.json already exists (will update in place)'
}

# Collected values are passed to Python via environment variables; only set ones are applied.
$pending = @{}

if ($NonInteractive) {
    Write-Warn2 'Non-interactive: leaving ADO and sandbox values as-is. Fill them later and re-run without -NonInteractive.'
} else {
    # ----- ADO configuration -----
    Write-Step 'Azure DevOps configuration (press Enter to keep the current value)'
    $adoOrg   = Read-Host '    ADO organization'
    $adoProj  = Read-Host '    ADO project'
    $adoQuery = Read-Host '    ADO release saved-query id'
    if (-not [string]::IsNullOrWhiteSpace($adoOrg))   { $pending['HARNESS_ADO_ORG']   = $adoOrg.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($adoProj))  { $pending['HARNESS_ADO_PROJECT']= $adoProj.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($adoQuery)) { $pending['HARNESS_ADO_QUERY']  = $adoQuery.Trim() }

    # ----- Sandbox authorization -----
    Write-Step 'Sandbox authorization (review-only on Windows)'
    Write-Warn2 'Only genuine sandboxes are accepted (*--*.sandbox.my.salesforce.com, IsSandbox=true).'
    $environments = @('development', 'qa', 'uat')
    foreach ($envName in $environments) {
        $answer = Read-Host "    Authorize the '$envName' sandbox now? [y/N]"
        if ($answer -notmatch '^(y|yes)$') { Write-Warn2 "skipped '$envName' (placeholders remain; preflight stays fail-closed for it)"; continue }

        $alias = Read-Host "    Alias to use for '$envName'"
        if ([string]::IsNullOrWhiteSpace($alias)) { Write-Warn2 'no alias entered; skipping'; continue }
        $alias = $alias.Trim()

        $loginUrl = Read-Host '    Sandbox login URL [https://test.salesforce.com]'
        if ([string]::IsNullOrWhiteSpace($loginUrl)) { $loginUrl = 'https://test.salesforce.com' }

        Write-Host "    Launching browser login for alias '$alias' ..."
        sf org login web --instance-url $loginUrl --alias $alias
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "sf login did not complete for '$alias'; skipping."; continue }

        $display = $null
        try { $display = (sf org display --target-org $alias --json 2>$null | ConvertFrom-Json) } catch { }
        if (-not $display -or $display.status -ne 0) { Write-Warn2 "could not read org identity for '$alias'; skipping."; continue }

        $instanceUrl = $display.result.instanceUrl
        $orgId = if ($display.result.id) { $display.result.id } else { $display.result.orgId }
        $hostName = ([System.Uri]$instanceUrl).Host

        if ($hostName -notmatch $SandboxHostPattern) {
            Write-Warn2 "REFUSED: '$hostName' is not a sandbox host (needs *--*.sandbox.my.salesforce.com). Not recorded."
            continue
        }
        $q = $null
        try { $q = (sf data query --query 'SELECT IsSandbox FROM Organization LIMIT 1' --target-org $alias --json 2>$null | ConvertFrom-Json) } catch { }
        if (-not $q -or $q.result.records[0].IsSandbox -ne $true) {
            Write-Warn2 "REFUSED: live Organization.IsSandbox is not true for '$alias'. Not recorded."
            continue
        }

        $key = $envName.ToUpper()
        $pending["HARNESS_${key}_ALIAS"] = $alias
        $pending["HARNESS_${key}_HOST"]  = $hostName
        $pending["HARNESS_${key}_ORGID"] = $orgId
        Write-Ok "recorded '$envName': $alias -> $hostName ($orgId)"
    }

    # ----- Review allowlist -----
    Write-Step 'Review allowlist (objects the agent may read through the review facade)'
    $objects = Read-Host '    Comma-separated object API names (Enter to keep current)'
    if (-not [string]::IsNullOrWhiteSpace($objects)) { $pending['HARNESS_REVIEW_OBJECTS'] = $objects.Trim() }
}

# ---------------------------------------------------------------------------
if ($pending.Count -gt 0) {
    Write-Step 'Writing configuration'
    foreach ($k in $pending.Keys) { Set-Item -Path "Env:$k" -Value $pending[$k] }
    $env:HARNESS_CONFIG_PATH = $ConfigPath
    $applier = @'
import json, os
path = os.environ["HARNESS_CONFIG_PATH"]
with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)

def val(key):
    v = os.environ.get(key)
    return v if v else None

ado_org = val("HARNESS_ADO_ORG")
if ado_org:
    cfg["ado"]["organization"] = ado_org
    cfg["ado"]["allowedHttpsOrigins"] = [f"https://dev.azure.com/{ado_org}"]
if val("HARNESS_ADO_PROJECT"):
    cfg["ado"]["project"] = val("HARNESS_ADO_PROJECT")
if val("HARNESS_ADO_QUERY"):
    cfg["ado"]["releaseQueryId"] = val("HARNESS_ADO_QUERY")

for env_name in ("development", "qa", "uat"):
    key = env_name.upper()
    alias = val(f"HARNESS_{key}_ALIAS")
    host = val(f"HARNESS_{key}_HOST")
    org_id = val(f"HARNESS_{key}_ORGID")
    if alias and host and org_id:
        for org in cfg["salesforce"]["orgs"]:
            if org.get("environment") == env_name:
                org["alias"] = alias
                org["expectedInstanceHost"] = host
                org["expectedOrganizationId"] = org_id
                org["allowAgentRead"] = True
                org["allowAgentReview"] = True
                org["allowAgentWrite"] = False

objects = val("HARNESS_REVIEW_OBJECTS")
if objects:
    cfg["salesforce"]["review"]["allowedObjectApiNames"] = [
        part.strip() for part in objects.split(",") if part.strip()
    ]

with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
print("config updated")
'@
    & $venvPy -c $applier
    if ($LASTEXITCODE -ne 0) { Fail 'failed to write config\harness.local.json' }
    Write-Ok 'config\harness.local.json saved'
}

# ---------------------------------------------------------------------------
Write-Step 'Verifying the harness'
& $venvPy (Join-Path $RepoRoot 'scripts\validate_harness.py')
$validateOk = ($LASTEXITCODE -eq 0)

Write-Host "`n    preflight (fails closed until every placeholder is filled):"
& $venvPy (Join-Path $RepoRoot 'scripts\preflight.py') --capability salesforce-review
$preflightOk = ($LASTEXITCODE -eq 0)

# ---------------------------------------------------------------------------
Write-Step 'Summary'
if ($validateOk)  { Write-Ok 'harness structure valid' } else { Write-Warn2 'validate_harness reported issues (see above)' }
if ($preflightOk) {
    Write-Ok 'preflight passed - the harness is ready'
} else {
    Write-Warn2 'preflight is fail-closed: fill any remaining <PLACEHOLDER> values in config\harness.local.json (ADO and/or a sandbox) and re-run this script.'
}
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host '  - In VS Code, start the Salesforce MCP; when prompted for "sf_read_org", enter an authorized alias.'
Write-Host '  - Only review (read-only) mode works on Windows; development/write mode requires macOS/Linux.'
Write-Host '  - config\harness.local.json is gitignored and never leaves this machine.'
