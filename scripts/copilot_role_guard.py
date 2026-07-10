#!/usr/bin/env python3
"""PreToolUse hook enforcing path boundaries for restricted custom agents."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Iterable


ALLOWED_PREFIXES = {
    "solution-designer": (
        ".ai/memory/decisions-log.md",
        ".ai/change-records/",
        ".cache/ado-items/",
    ),
    "config-investigator": (
        ".ai/knowledge/",
        ".ai/memory/decisions-log.md",
    ),
    "test-strategist": (
        ".ai/qa/",
        ".ai/memory/decisions-log.md",
        ".ai/change-records/",
        "output/generated-tests/",
        "output/feature-health/",
        "output/handover/",
        ".cache/ado-items/",
        ".cache/test-cases/",
    ),
    "development-assistant": (
        ".ai/change-records/",
        "output/documentation/",
        ".cache/ado-items/",
    ),
}

HARNESS_ROOT = Path(__file__).resolve().parents[1]
METADATA_ROOT = HARNESS_ROOT.parent / "salesforce-metadata"
METADATA_EDIT_PREFIXES = ("force-app/", "manifest/", "tests/")
PREFLIGHT_CAPABILITIES = {
    "solution-designer": {"base", "ado", "salesforce-read"},
    "config-investigator": {"base", "salesforce-read"},
    "development-assistant": {
        "base",
        "ado",
        "metadata",
        "salesforce-read",
        "salesforce-write",
    },
    "test-strategist": {"base", "ado", "playwright", "release", "salesforce-read"},
}

PATH_KEYS = {
    "path",
    "filepath",
    "file_path",
    "filename",
    "files",
    "paths",
}


def response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if decision is None:
        return {"continue": True}
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if reason:
        output["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": output}


def is_edit_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(token in lowered for token in ("edit", "createfile", "replace", "insert"))


def is_execute_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(token in lowered for token in ("execute", "terminal", "runinterminal"))


def terminal_command(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "text"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return ""


def allowed_role_command(command: str, root: Path, role: str) -> bool:
    if not command or re.search(r"[;&|`$<>\n\r]", command):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    executable = Path(parts[0]).name.lower()
    if executable not in {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}:
        return False
    index = 1
    if executable.startswith("py") and index < len(parts) and parts[index] == "-3":
        index += 1
    if index >= len(parts):
        return False
    script = Path(parts[index])
    if not script.is_absolute():
        script = root / script
    script = script.resolve(strict=False)
    preflight = (root / "scripts/preflight.py").resolve()
    browser_guard = (root / "scripts/playwright_guard.py").resolve()
    remainder = parts[index + 1 :]
    if script == preflight:
        return (
            len(remainder) == 2
            and remainder[0] == "--capability"
            and remainder[1] in PREFLIGHT_CAPABILITIES.get(role, set())
        )
    return role == "test-strategist" and script == browser_guard and bool(remainder)


def resolve_candidate(raw: str, resolution_root: Path) -> Path | None:
    if not raw or raw.startswith(("http://", "https://")):
        return None
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = resolution_root / candidate
    return candidate.resolve(strict=False)


def development_edit_allowed(raw: str, resolution_root: Path) -> bool:
    candidate = resolve_candidate(raw, resolution_root)
    if candidate is None:
        return True
    try:
        brain_relative = candidate.relative_to(HARNESS_ROOT).as_posix()
        return allowed(brain_relative, ALLOWED_PREFIXES["development-assistant"])
    except ValueError:
        pass
    try:
        metadata_relative = candidate.relative_to(METADATA_ROOT.resolve()).as_posix()
    except ValueError:
        return False
    return any(metadata_relative.startswith(prefix) for prefix in METADATA_EDIT_PREFIXES)


def guarded_browser_subcommand(command: str) -> str | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    for index, part in enumerate(parts):
        if Path(part).name == "playwright_guard.py":
            remainder = parts[index + 1 :]
            cursor = 0
            while cursor < len(remainder) and remainder[cursor].startswith("--"):
                if remainder[cursor] == "--session":
                    cursor += 2
                else:
                    cursor += 1
            return remainder[cursor] if cursor < len(remainder) else None
    return None


def collect_paths(value: Any, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if normalized in PATH_KEYS:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, str):
                            yield item
                        else:
                            yield from collect_paths(item, normalized)
                else:
                    yield from collect_paths(child, normalized)
            else:
                yield from collect_paths(child, normalized)
    elif isinstance(value, list):
        for child in value:
            yield from collect_paths(child, parent_key)


def normalize_path(raw: str, resolution_root: Path, policy_root: Path) -> str | None:
    if not raw or raw.startswith(("http://", "https://")):
        return None
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = resolution_root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(policy_root).as_posix()
    except ValueError:
        return f"OUTSIDE::{candidate.resolve(strict=False)}"


def allowed(relative_path: str, prefixes: tuple[str, ...]) -> bool:
    if relative_path.startswith("OUTSIDE::"):
        return False
    return any(
        relative_path.startswith(prefix)
        if prefix.endswith("/")
        else relative_path == prefix
        for prefix in prefixes
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=sorted(ALLOWED_PREFIXES))
    args = parser.parse_args()

    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps(response("ask", f"Role guard could not parse hook input: {exc}")))
        return 0

    tool_name = str(event.get("tool_name", ""))
    root = HARNESS_ROOT
    event_root = Path(event.get("cwd") or os.getcwd()).resolve()
    if is_execute_tool(tool_name):
        if event_root != root:
            print(
                json.dumps(
                    response(
                        "deny",
                        f"{args.role} guarded terminal commands must run from the brain-core root.",
                    )
                )
            )
            return 0
        command = terminal_command(event.get("tool_input", {}))
        if not allowed_role_command(command, root, args.role):
            print(
                json.dumps(
                    response(
                        "deny",
                        f"{args.role} terminal access is limited to its allowlisted preflight/guarded runner commands.",
                    )
                )
            )
            return 0
        if args.role == "test-strategist" and guarded_browser_subcommand(command) in {
            "click",
            "dblclick",
            "fill",
            "type",
            "select",
            "check",
            "uncheck",
            "press",
        }:
            print(
                json.dumps(
                    response(
                        "ask",
                        "SAFE-HUMAN-001 requires confirmation before a state-changing browser action.",
                    )
                )
            )
            return 0
        print(json.dumps(response()))
        return 0
    if not is_edit_tool(tool_name):
        print(json.dumps(response()))
        return 0

    raw_paths = list(collect_paths(event.get("tool_input", {})))
    if args.role == "development-assistant":
        if not raw_paths:
            print(
                json.dumps(
                    response(
                        "ask",
                        "development-assistant requested an edit whose target path could not be determined.",
                    )
                )
            )
            return 0
        denied_raw = sorted(
            raw for raw in raw_paths if not development_edit_allowed(raw, event_root)
        )
        if denied_raw:
            print(
                json.dumps(
                    response(
                        "deny",
                        f"development-assistant may edit only metadata force-app/manifest/tests, reviewed documentation/change records, and ignored ADO cache: {', '.join(denied_raw)}",
                    )
                )
            )
            return 0
        print(json.dumps(response()))
        return 0

    found = {
        normalized
        for raw in raw_paths
        if (normalized := normalize_path(raw, event_root, root)) is not None
    }
    if not found:
        print(
            json.dumps(
                response(
                    "ask",
                    f"{args.role} requested an edit whose target path could not be determined.",
                )
            )
        )
        return 0

    denied = sorted(path for path in found if not allowed(path, ALLOWED_PREFIXES[args.role]))
    if denied:
        print(
            json.dumps(
                response(
                    "deny",
                    f"{args.role} may not edit: {', '.join(denied)}",
                )
            )
        )
        return 0

    print(json.dumps(response()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
