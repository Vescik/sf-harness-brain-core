#!/usr/bin/env python3
"""Run a narrow Playwright CLI surface and close the session on origin drift."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from copilot_safety_hook import allowed_origins
    from preflight import load_config
except ModuleNotFoundError:  # imported as scripts.playwright_guard by unit tests
    from scripts.copilot_safety_hook import allowed_origins
    from scripts.preflight import load_config


PINNED_VERSION = "0.1.17"
SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
ALLOWED_COMMANDS = {
    "open",
    "close",
    "goto",
    "click",
    "dblclick",
    "fill",
    "type",
    "hover",
    "select",
    "check",
    "uncheck",
    "snapshot",
    "find",
    "go-back",
    "go-forward",
    "reload",
    "press",
    "tab-list",
    "tab-new",
    "tab-close",
    "tab-select",
    "generate-locator",
    "console",
    "screenshot",
}
URL_COMMANDS = {"open", "goto", "tab-new"}


def version_matches(stdout: str) -> bool:
    match = re.search(r"(?<![0-9.])(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?![0-9.])", stdout)
    return match is not None and match.group(1) == PINNED_VERSION


def fail(message: str) -> int:
    print(f"ERROR: guarded Playwright blocked: {message}")
    return 2


def origin(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
        return None


def validate_request(command: str, arguments: list[str], allowed: set[str]) -> str | None:
    if command not in ALLOWED_COMMANDS:
        return f"subcommand '{command}' is not in the safe allowlist"
    if any(value.startswith(("--profile", "--config", "--filename")) for value in arguments):
        return "profile, config, and output paths are controlled by the wrapper"
    scheme_values = [
        value for value in arguments if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    ]
    if any(not value.startswith("https://") for value in scheme_values):
        return "only explicit HTTPS navigation is allowed; file/data/javascript schemes are denied"
    urls = [value for value in arguments if value.startswith("https://")]
    if command in URL_COMMANDS and len(urls) != 1:
        return f"{command} requires exactly one explicit allowlisted HTTPS URL"
    for value in urls:
        candidate = origin(value)
        if candidate not in allowed:
            return f"origin '{candidate or value}' is not allowlisted"
    return None


def run_cli(executable: str, session: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, f"-s={session}", *args],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def collect_http_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(collect_http_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_http_values(child))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        found.append(value)
    return found


def close_session(executable: str, session: str) -> None:
    try:
        run_cli(executable, session, ["close"])
    except (OSError, subprocess.SubprocessError):
        pass


def verify_session_origins(executable: str, session: str, allowed: set[str]) -> tuple[bool, str]:
    current = run_cli(executable, session, ["eval", "() => location.origin", "--raw"])
    if current.returncode != 0:
        return False, "could not verify current location.origin"
    current_origin = current.stdout.strip().strip('"')
    if current_origin not in allowed:
        return False, f"current origin drifted to '{current_origin}'"
    tabs = run_cli(executable, session, ["tab-list", "--json"])
    if tabs.returncode != 0:
        return False, "could not inspect all open tabs"
    try:
        tab_payload = json.loads(tabs.stdout)
    except json.JSONDecodeError:
        return False, "tab inspection returned malformed JSON"
    for url in collect_http_values(tab_payload):
        if origin(url) not in allowed:
            return False, f"an open tab drifted to unallowlisted origin '{origin(url)}'"
    return True, current_origin


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="sf-harness")
    parser.add_argument("command")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.platform == "win32":
        return fail("browser execution is disabled on Windows for this pilot")
    if not SESSION.fullmatch(args.session):
        return fail("invalid session name")
    try:
        config = load_config()
    except ValueError as exc:
        return fail(str(exc))
    allowed = allowed_origins(config)
    if not allowed:
        return fail("no valid Salesforce sandbox origin is configured")
    error = validate_request(args.command, args.arguments, allowed)
    if error:
        return fail(error)
    executable = shutil.which("playwright-cli")
    if executable is None:
        return fail("playwright-cli is not installed")
    version = subprocess.run(
        [executable, "--version"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if version.returncode != 0 or not version_matches(version.stdout):
        return fail(f"playwright-cli must be pinned to {PINNED_VERSION}")
    profile = Path(config["browser"]["profileDirectory"]).expanduser().resolve()
    if args.command not in {"open", "close"}:
        ok, reason = verify_session_origins(executable, args.session, allowed)
        if not ok:
            close_session(executable, args.session)
            return fail(f"pre-action origin check failed: {reason}")
    command_args = [args.command, *args.arguments]
    if args.command == "open":
        command_args.extend(["--headed", "--persistent", "--profile", str(profile)])
    completed = run_cli(executable, args.session, command_args)
    if completed.returncode != 0:
        close_session(executable, args.session)
        return fail("Playwright CLI command failed; session closed")
    if args.command != "close":
        ok, reason = verify_session_origins(executable, args.session, allowed)
        if not ok:
            close_session(executable, args.session)
            return fail(f"post-action origin check failed: {reason}; session closed")
    if completed.stdout:
        print(completed.stdout.rstrip())
    print(f"PASS: guarded Playwright {args.command} on an allowlisted origin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
