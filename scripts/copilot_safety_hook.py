#!/usr/bin/env python3
"""Workspace PreToolUse hook blocking production and destructive agent operations."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

DESTRUCTIVE_PATTERNS = (
    re.compile(r"(^|\s)rm\s+-[^\n]*r[^\n]*f", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-[^\n]*f", re.IGNORECASE),
    re.compile(r"\bsf\s+org\s+delete\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
)

PRODUCTION_PATTERNS = (
    re.compile(r"(^|[^a-z])(prod|production)([^a-z]|$)", re.IGNORECASE),
    re.compile(r"https://login\.salesforce\.com", re.IGNORECASE),
)

SENSITIVE_TOOL_TOKENS = (
    "terminal",
    "execute",
    "web",
    "fetch",
    "browser",
    "playwright",
    "salesforce",
    "deploy",
    "mcp",
)

SANDBOX_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\."
    r"(?:my\.salesforce\.com|lightning\.force\.com|my\.site\.com)$",
    re.IGNORECASE,
)

SALESFORCE_HOST_SUFFIXES = (
    ".salesforce.com",
    ".force.com",
    ".my.site.com",
)

FILESYSTEM_KEYS = {
    "directory",
    "dir",
    "path",
    "filepath",
    "file_path",
    "manifest",
    "manifestpath",
    "manifest_path",
    "sourcepath",
    "source_path",
    "targetpath",
    "target_path",
    "sourcedir",
    "targetdir",
    "projectdir",
    "source_dir",
    "target_dir",
    "project_dir",
    "target",
    "configpath",
    "config_path",
    "resultsfile",
    "results_file",
}

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def hook_response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if decision is None:
        return {"continue": True}
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if reason:
        output["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": output}


def flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(flatten(child) for child in value)
    return str(value)


def load_config(root: Path) -> dict[str, Any] | None:
    path = root / "config" / "harness.local.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def is_salesforce_sandbox_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin.rstrip("/"))
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and bool(parsed.hostname)
        and bool(SANDBOX_HOST.fullmatch(parsed.hostname or ""))
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


def allowed_origins(config: dict[str, Any]) -> set[str]:
    return {
        str(origin).rstrip("/")
        for origin in config.get("browser", {}).get("allowedOrigins", [])
        if isinstance(origin, str)
        and "<" not in origin
        and is_salesforce_sandbox_origin(origin)
    }


def sandbox_write_approved(config: dict[str, Any]) -> bool:
    safety = config.get("safety", {})
    return safety.get("sharedSandboxWritesApproved") is True and bool(
        str(safety.get("sharedSandboxApprovalRef", "")).strip()
    )


def development_tool_requires_confirmation(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(
        token in lowered
        for token in (
            "deploy",
            "retrieve",
            "delete",
            "create",
            "update",
            "assign",
            "activate",
            "resume",
        )
    )


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https://[^\s'\"<>]+", text)


def terminal_command(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "text"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return flatten(tool_input)


def target_orgs(parts: list[str]) -> list[str]:
    targets: list[str] = []
    for index, part in enumerate(parts):
        if part in ("--target-org", "-o") and index + 1 < len(parts):
            targets.append(parts[index + 1])
        if part.startswith("--target-org="):
            targets.append(part.split("=", 1)[1])
    return targets


def direct_sf_command(command: str) -> list[str] | None:
    if not re.search(r"\bsf(?:\.cmd|\.exe)?\b", command, re.IGNORECASE):
        return None
    if re.search(r"[;&|`$<>\n\r]", command):
        raise ValueError("compound, redirected, or substituted Salesforce commands are forbidden")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"Salesforce command could not be parsed: {exc}") from exc
    if not parts or Path(parts[0]).name.lower() not in {"sf", "sf.cmd", "sf.exe"}:
        raise ValueError("Salesforce CLI must be invoked directly, without a shell or environment wrapper")
    return parts


def collect_filesystem_paths(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in FILESYSTEM_KEYS:
                if isinstance(child, str):
                    found.append(child)
                elif isinstance(child, list):
                    found.extend(item for item in child if isinstance(item, str))
                    for item in child:
                        if not isinstance(item, str):
                            found.extend(collect_filesystem_paths(item))
                else:
                    found.extend(collect_filesystem_paths(child))
            else:
                found.extend(collect_filesystem_paths(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_filesystem_paths(child))
    return found


def collect_named_values(value: Any, names: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in names:
                if isinstance(child, (str, int)):
                    found.append(str(child))
                elif isinstance(child, list):
                    found.extend(str(item) for item in child if isinstance(item, (str, int)))
            found.extend(collect_named_values(child, names))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_named_values(child, names))
    return found


def ado_scope_error(
    config: dict[str, Any],
    tool_input: Any,
    *,
    runtime_org: str | None = None,
) -> str | None:
    ado = config.get("ado", {})
    configured_org = str(ado.get("organization", ""))
    configured_project = str(ado.get("project", ""))
    effective_org = os.environ.get("ADO_ORGANIZATION", "") if runtime_org is None else runtime_org
    if not configured_org or effective_org != configured_org:
        return "ADO runtime organization does not match local policy"
    projects = collect_named_values(
        tool_input,
        {"project", "projectid", "project_id", "projectname", "project_name"},
    )
    if not projects:
        return "ADO tool call does not prove its configured project scope"
    if any(project != configured_project for project in projects):
        return "ADO tool call targets a project outside local policy"
    for raw_url in extract_urls(flatten(tool_input)):
        parsed = urlparse(raw_url.rstrip(".,);]"))
        if parsed.hostname == "dev.azure.com":
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(parts) < 2 or parts[0] != configured_org or parts[1] != configured_project:
                return "ADO URL is outside the configured organization/project"
    return None


def within_root(raw: str, root: Path) -> bool:
    if not raw or raw.startswith(("http://", "https://")):
        return True
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def guarded_playwright_subcommand(command: str) -> str | None:
    if re.search(r"[;&|`$<>\n\r]", command):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    expected = (HARNESS_ROOT / "scripts/playwright_guard.py").resolve()
    for index, part in enumerate(parts):
        if Path(part).name != "playwright_guard.py":
            continue
        script = Path(part)
        if not script.is_absolute():
            script = HARNESS_ROOT / script
        if script.resolve(strict=False) != expected:
            return None
        remainder = parts[index + 1 :]
        cursor = 0
        while cursor < len(remainder) and remainder[cursor].startswith("--"):
            if remainder[cursor] == "--session":
                cursor += 2
            else:
                cursor += 1
        return remainder[cursor] if cursor < len(remainder) else None
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps(hook_response("ask", f"Safety hook could not parse input: {exc}")))
        return 0

    tool_name = str(event.get("tool_name", ""))
    lowered_name = tool_name.lower()
    tool_input = event.get("tool_input", {})
    text = flatten(tool_input)
    root = HARNESS_ROOT

    if any(pattern.search(text) for pattern in DESTRUCTIVE_PATTERNS):
        print(json.dumps(hook_response("deny", "Destructive operation blocked by SAFE-ROLE-001.")))
        return 0

    if any(token in lowered_name for token in SENSITIVE_TOOL_TOKENS):
        if any(pattern.search(text) for pattern in PRODUCTION_PATTERNS):
            print(json.dumps(hook_response("deny", "Production target blocked by SAFE-ENV-001.")))
            return 0

    config = load_config(root)
    if "ado-readonly" in lowered_name:
        if config is None:
            print(json.dumps(hook_response("deny", "ADO read blocked: local harness configuration is missing.")))
            return 0
        scope_error = ado_scope_error(config, tool_input)
        if scope_error:
            print(json.dumps(hook_response("deny", f"ADO read blocked: {scope_error}.")))
            return 0
    for raw_url in extract_urls(text):
        parsed_url = urlparse(raw_url.rstrip(".,);]"))
        hostname = (parsed_url.hostname or "").lower()
        if hostname.endswith(SALESFORCE_HOST_SUFFIXES) and not is_salesforce_sandbox_origin(
            f"{parsed_url.scheme}://{parsed_url.netloc}"
        ):
            print(json.dumps(hook_response("deny", "Non-sandbox Salesforce URL blocked by SAFE-ENV-001.")))
            return 0
    if "salesforce-development" in lowered_name:
        if config is None or not sandbox_write_approved(config):
            print(json.dumps(hook_response("deny", "Salesforce development blocked: shared-sandbox approval is missing.")))
            return 0
        metadata_root = root.parent / "salesforce-metadata"
        paths = collect_filesystem_paths(tool_input)
        filesystem_tool = any(token in lowered_name for token in ("deploy_metadata", "retrieve_metadata"))
        if filesystem_tool and not paths:
            print(json.dumps(hook_response("deny", "Salesforce metadata tool must declare a directory/path inside the named metadata root.")))
            return 0
        outside = [path for path in paths if not within_root(path, metadata_root)]
        if outside:
            print(json.dumps(hook_response("deny", "Salesforce development path is outside the named metadata root.")))
            return 0
        if development_tool_requires_confirmation(lowered_name):
            print(json.dumps(hook_response("ask", "SAFE-HUMAN-001 requires confirmation for this approved non-production mutation.")))
            return 0
    command = terminal_command(tool_input)
    try:
        sf_parts = direct_sf_command(command)
    except ValueError as exc:
        print(json.dumps(hook_response("deny", f"Salesforce command blocked: {exc}.")))
        return 0
    if sf_parts is not None:
        targets = target_orgs(sf_parts)
        if len(targets) != 1:
            print(json.dumps(hook_response("deny", "Salesforce command must specify exactly one allowlisted --target-org; defaults and multiple targets are forbidden.")))
            return 0
        print(json.dumps(hook_response("deny", "Direct Salesforce CLI is disabled; use the guarded namespaced MCP server.")))
        return 0

    if re.search(r"(?:@salesforce/mcp|ALLOW_ALL_ORGS|DEFAULT_TARGET_ORG|\bsfdx\b)", command, re.IGNORECASE):
        print(json.dumps(hook_response("deny", "An unguarded Salesforce runtime/default target is forbidden.")))
        return 0

    if "playwright" in lowered_name or "playwright-cli" in command:
        print(json.dumps(hook_response("deny", "Direct browser tooling is disabled; use scripts/playwright_guard.py.")))
        return 0
    if "playwright_guard.py" in command:
        browser_subcommand = guarded_playwright_subcommand(command)
        if browser_subcommand is None:
            print(json.dumps(hook_response("deny", "Guarded browser command is wrapped, malformed, or outside the harness.")))
            return 0
        if config is None:
            print(json.dumps(hook_response("deny", "Browser operation blocked: config/harness.local.json is missing or invalid.")))
            return 0
        allowed = allowed_origins(config)
        for raw_url in extract_urls(text):
            parsed = urlparse(raw_url.rstrip(".,);]"))
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in allowed:
                print(json.dumps(hook_response("deny", f"Browser origin '{origin}' is not allowlisted.")))
                return 0
        if browser_subcommand in {
            "click",
            "dblclick",
            "fill",
            "type",
            "select",
            "check",
            "uncheck",
            "press",
        }:
            print(json.dumps(hook_response("ask", "SAFE-HUMAN-001 requires confirmation before a state-changing browser action.")))
            return 0

    print(json.dumps(hook_response()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
