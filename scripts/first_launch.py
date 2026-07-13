#!/usr/bin/env python3
"""First-launch onboarding for the brain-core Salesforce Copilot harness.

Human-run setup helper for Windows, macOS, and Linux. It is NOT an agent tool and is
deliberately not on the role-guard allowlist. It:

  1. checks prerequisites (git, node, npm, sf, python);
  2. installs the pinned dependencies (npm ci, hash-pinned pip lock into .venv);
  3. creates config/harness.local.json from the tracked example if absent;
  4. collects ADO configuration interactively;
  5. walks you through authorizing each SANDBOX (``sf org login web``), auto-fills the
     expected host + organization id from ``sf org display``, and refuses to record any
     org that is not a genuine sandbox (mirrors SAFE-ENV-001);
  6. runs preflight / validate to confirm the setup.

Windows note: only REVIEW (read-only) Salesforce mode is supported there; development/write
mode requires macOS/Linux (MCP sandboxing is unavailable on Windows). Orgs are therefore
always configured for review only (allowAgentWrite = false).

Credentials are never handled by this script: ``sf org login web`` performs interactive
browser OAuth, and no tokens/passwords are read, printed, or stored.

Usage:
    python scripts/first_launch.py                 # full guided run
    python scripts/first_launch.py --skip-install  # deps already present
    python scripts/first_launch.py --non-interactive  # checks + install + verify only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "harness.local.json"
EXAMPLE_PATH = REPO_ROOT / "config" / "harness.example.json"
SANDBOX_HOST_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com$"
)
MIN_PYTHON = (3, 11)
IS_WINDOWS = os.name == "nt"


def _enable_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        os.system("")  # enables VT processing on Windows 10+ consoles
    return True


_COLOR = _enable_ansi()


def _c(code: str, message: str) -> str:
    return f"\033[{code}m{message}\033[0m" if _COLOR else message


def step(message: str) -> None:
    print(_c("36", f"\n==> {message}"))


def ok(message: str) -> None:
    print(_c("32", f"    [ok] {message}"))


def warn(message: str) -> None:
    print(_c("33", f"    [!]  {message}"))


def fail(message: str) -> None:
    print(_c("31", f"    [x]  {message}"))
    raise SystemExit(1)


def which(tool: str) -> str | None:
    """Resolve a tool on PATH (handles .cmd/.exe shims on Windows)."""
    return shutil.which(tool)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command without a shell; the first element must be a resolved path."""
    return subprocess.run(cmd, **kwargs)


def tool_version(path: str, args: list[str]) -> str:
    try:
        out = run([path, *args], capture_output=True, text=True, timeout=60)
        first = (out.stdout or out.stderr).strip().splitlines()
        return first[0] if first else "present"
    except Exception:  # noqa: BLE001 - reporting only
        return "present"


def venv_python() -> Path:
    if IS_WINDOWS:
        candidate = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = REPO_ROOT / ".venv" / "bin" / "python"
    return candidate


def check_prerequisites() -> dict[str, str]:
    step("Checking prerequisites")
    if sys.version_info < MIN_PYTHON:
        warn(
            f"this interpreter is Python {sys.version_info.major}.{sys.version_info.minor}; "
            f"the supported baseline is {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ (CI certifies 3.12). "
            "Install a current Python from python.org before a fresh setup."
        )
    tools = {"git": ["--version"], "node": ["--version"], "npm": ["--version"], "sf": ["--version"]}
    resolved: dict[str, str] = {}
    for name, args in tools.items():
        path = which(name)
        if path is None:
            fail(f"{name} is not installed or not on PATH.")
        resolved[name] = path
        ok(f"{name} -> {tool_version(path, args)}")
    ok(f"python -> {sys.version.split()[0]} ({sys.executable})")
    return resolved


def install_dependencies(npm_path: str) -> None:
    step("Installing pinned dependencies")
    print("    npm ci --ignore-scripts (exact lockfile; do not use npm install)")
    if run([npm_path, "ci", "--ignore-scripts"], cwd=REPO_ROOT).returncode != 0:
        fail("npm ci failed.")
    ok("node_modules installed from package-lock.json")

    venv_dir = REPO_ROOT / ".venv"
    if not venv_dir.exists():
        print("    creating .venv")
        if sys.version_info < MIN_PYTHON:
            fail(
                f"refusing to create a fresh .venv with Python "
                f"{sys.version_info.major}.{sys.version_info.minor}; re-run with Python "
                f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+."
            )
        if run([sys.executable, "-m", "venv", str(venv_dir)]).returncode != 0:
            fail("could not create .venv")
    py = venv_python()
    if not py.exists():
        fail(f"venv python not found at {py}")
    print("    pip install --require-hashes -r requirements-dev.lock")
    result = run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            str(REPO_ROOT / "requirements-dev.lock"),
        ]
    )
    if result.returncode != 0:
        fail("pip install (hash-pinned) failed.")
    ok("Python validation dependencies installed into .venv")


def prepare_config() -> None:
    step("Preparing local configuration")
    if not CONFIG_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
        ok("created config/harness.local.json from the example template")
    else:
        ok("config/harness.local.json already exists (will update in place)")


def prompt(text: str) -> str:
    try:
        return input(f"    {text}: ").strip()
    except EOFError:
        return ""


def sf_json(sf_path: str, args: list[str]) -> dict | None:
    try:
        out = run([sf_path, *args, "--json"], capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001 - any failure means "could not read"
        return None


def collect_ado(pending: dict[str, object]) -> None:
    step("Azure DevOps configuration (press Enter to keep the current value)")
    ado_org = prompt("ADO organization")
    ado_project = prompt("ADO project")
    ado_query = prompt("ADO release saved-query id")
    if ado_org:
        pending["ado.organization"] = ado_org
    if ado_project:
        pending["ado.project"] = ado_project
    if ado_query:
        pending["ado.releaseQueryId"] = ado_query


def authorize_sandboxes(sf_path: str, pending: dict[str, object]) -> None:
    step("Sandbox authorization (review-only; writes stay disabled)")
    warn("Only genuine sandboxes are accepted (*--*.sandbox.my.salesforce.com, IsSandbox=true).")
    for env_name in ("development", "qa", "uat"):
        answer = prompt(f"Authorize the '{env_name}' sandbox now? [y/N]").lower()
        if answer not in {"y", "yes"}:
            warn(f"skipped '{env_name}' (placeholders remain; preflight stays fail-closed for it)")
            continue

        alias = prompt(f"Alias to use for '{env_name}'")
        if not alias:
            warn("no alias entered; skipping")
            continue

        login_url = prompt("Sandbox login URL [https://test.salesforce.com]")
        if not login_url:
            login_url = "https://test.salesforce.com"

        print(f"    Launching browser login for alias '{alias}' ...")
        login = run([sf_path, "org", "login", "web", "--instance-url", login_url, "--alias", alias])
        if login.returncode != 0:
            warn(f"sf login did not complete for '{alias}'; skipping.")
            continue

        display = sf_json(sf_path, ["org", "display", "--target-org", alias])
        if not display or display.get("status") != 0:
            warn(f"could not read org identity for '{alias}'; skipping.")
            continue
        result = display.get("result") or {}
        instance_url = result.get("instanceUrl") or ""
        org_id = result.get("id") or result.get("orgId") or ""
        host = urlsplit(instance_url).hostname or ""

        if not SANDBOX_HOST_PATTERN.match(host):
            warn(
                f"REFUSED: '{host}' is not a sandbox host "
                "(needs *--*.sandbox.my.salesforce.com). Not recorded."
            )
            continue

        query = sf_json(
            sf_path,
            [
                "data",
                "query",
                "--query",
                "SELECT IsSandbox FROM Organization LIMIT 1",
                "--target-org",
                alias,
            ],
        )
        records = ((query or {}).get("result") or {}).get("records") or []
        if not records or records[0].get("IsSandbox") is not True:
            warn(f"REFUSED: live Organization.IsSandbox is not true for '{alias}'. Not recorded.")
            continue

        pending[f"org.{env_name}"] = {"alias": alias, "host": host, "orgId": org_id}
        ok(f"recorded '{env_name}': {alias} -> {host} ({org_id})")


def collect_review_allowlist(pending: dict[str, object]) -> None:
    step("Review allowlist (objects the agent may read through the review facade)")
    objects = prompt("Comma-separated object API names (Enter to keep current)")
    if objects:
        pending["review.objects"] = [part.strip() for part in objects.split(",") if part.strip()]


def apply_config(pending: dict[str, object]) -> None:
    step("Writing configuration")
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        cfg = json.load(fh)

    ado_org = pending.get("ado.organization")
    if ado_org:
        cfg["ado"]["organization"] = ado_org
        cfg["ado"]["allowedHttpsOrigins"] = [f"https://dev.azure.com/{ado_org}"]
    if pending.get("ado.project"):
        cfg["ado"]["project"] = pending["ado.project"]
    if pending.get("ado.releaseQueryId"):
        cfg["ado"]["releaseQueryId"] = pending["ado.releaseQueryId"]

    for env_name in ("development", "qa", "uat"):
        entry = pending.get(f"org.{env_name}")
        if not entry:
            continue
        for org in cfg["salesforce"]["orgs"]:
            if org.get("environment") == env_name:
                org["alias"] = entry["alias"]
                org["expectedInstanceHost"] = entry["host"]
                org["expectedOrganizationId"] = entry["orgId"]
                org["allowAgentRead"] = True
                org["allowAgentReview"] = True
                org["allowAgentWrite"] = False

    if pending.get("review.objects"):
        cfg["salesforce"]["review"]["allowedObjectApiNames"] = pending["review.objects"]

    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    ok("config/harness.local.json saved")


def verify() -> tuple[bool, bool]:
    step("Verifying the harness")
    py = venv_python()
    runner = str(py) if py.exists() else sys.executable
    validate = run([runner, str(REPO_ROOT / "scripts" / "validate_harness.py")], cwd=REPO_ROOT)
    print("\n    preflight (fails closed until every placeholder is filled):")
    preflight = run(
        [runner, str(REPO_ROOT / "scripts" / "preflight.py"), "--capability", "salesforce-review"],
        cwd=REPO_ROOT,
    )
    return validate.returncode == 0, preflight.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="skip npm ci / pip install (dependencies already present)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="only run checks + install + verify; no prompts or org authorization",
    )
    args = parser.parse_args()
    os.chdir(REPO_ROOT)

    resolved = check_prerequisites()

    if args.skip_install:
        step("Skipping dependency install (--skip-install)")
    else:
        install_dependencies(resolved["npm"])

    prepare_config()

    pending: dict[str, object] = {}
    if args.non_interactive:
        warn(
            "Non-interactive: leaving ADO and sandbox values as-is. "
            "Fill them later and re-run without --non-interactive."
        )
    else:
        collect_ado(pending)
        authorize_sandboxes(resolved["sf"], pending)
        collect_review_allowlist(pending)

    if pending:
        apply_config(pending)

    validate_ok, preflight_ok = verify()

    step("Summary")
    if validate_ok:
        ok("harness structure valid")
    else:
        warn("validate_harness reported issues (see above)")
    if preflight_ok:
        ok("preflight passed - the harness is ready")
    else:
        warn(
            "preflight is fail-closed: fill any remaining <PLACEHOLDER> values in "
            "config/harness.local.json (ADO and/or a sandbox) and re-run this script."
        )
    print(_c("36", "\nNext steps:"))
    print("  - In VS Code, select the .venv interpreter (Python: Select Interpreter).")
    print(
        "  - Start the Salesforce MCP; when prompted for \"sf_read_org\", enter an "
        "authorized alias."
    )
    print("  - Only review (read-only) mode works on Windows; development/write mode requires macOS/Linux.")
    print("  - config/harness.local.json is gitignored and never leaves this machine.")


if __name__ == "__main__":
    main()
