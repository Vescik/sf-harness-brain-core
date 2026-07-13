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
        ".cache/ado-items/",
    ),
    "config-investigator": (
        ".cache/knowledge-proposals/",
    ),
    "test-strategist": (
        ".ai/qa/",
        "output/generated-tests/",
        "output/feature-health/",
        "output/handover/",
        ".cache/ado-items/",
        ".cache/test-cases/",
    ),
    "development-assistant": (
        "output/documentation/",
        ".cache/ado-items/",
    ),
    "guardrail-reviewer": (),
}

HARNESS_ROOT = Path(__file__).resolve().parents[1]
METADATA_ROOT = HARNESS_ROOT
METADATA_EDIT_PREFIXES = ("force-app/", "manifest/", "tests/e2e/")
PREFLIGHT_CAPABILITIES = {
    "solution-designer": {"base", "ado", "salesforce-review"},
    "config-investigator": {"base", "metadata", "salesforce-review"},
    "development-assistant": {
        "base",
        "ado",
        "metadata",
        "salesforce-review",
        "salesforce-write",
    },
    "test-strategist": {"base", "ado", "playwright", "release", "salesforce-review"},
    "guardrail-reviewer": {"base", "salesforce-review"},
}

WORK_RECORD_COMMANDS = {
    "solution-designer": {
        "init",
        "validate",
        "context",
        "transition",
        "accept-handoff",
        "append-evidence",
        "attach-rule",
        "bind-claim",
        "add-question",
        "resolve-question",
        "capture-repository",
        "capture-org-review",
        "create-handoff",
    },
    "config-investigator": {
        "validate",
        "context",
        "accept-handoff",
        "append-evidence",
        "add-question",
        "capture-org-review",
        "create-handoff",
    },
    "development-assistant": {
        "validate",
        "context",
        "transition",
        "accept-handoff",
        "append-evidence",
        "capture-repository",
        "run-verification",
        "create-handoff",
    },
    "test-strategist": {
        "validate",
        "context",
        "transition",
        "accept-handoff",
        "append-evidence",
        "capture-repository",
        "run-verification",
        "create-handoff",
    },
    "guardrail-reviewer": {
        "validate",
        "context",
        "accept-handoff",
        "capture-repository",
        "capture-org-review",
        "run-verification",
        "append-review",
        "create-handoff",
    },
}

# Knowledge mutation is intentionally narrower than filesystem edit permission. Models may validate
# the registry, and only the Investigator may submit a schema-valid proposed claim/evidence set.
# Human review and promotion commands are never agent-allowlisted.
KNOWLEDGE_REGISTRY_COMMANDS = {
    "solution-designer": {"validate", "query"},
    "config-investigator": {"validate", "query", "propose"},
    "development-assistant": {"validate", "query"},
    "test-strategist": {"validate", "query"},
    "guardrail-reviewer": {"validate", "query"},
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


def flag_values(parts: list[str], flag: str) -> list[str]:
    values: list[str] = []
    for index, part in enumerate(parts):
        if part == flag and index + 1 < len(parts):
            values.append(parts[index + 1])
        elif part.startswith(f"{flag}="):
            values.append(part.split("=", 1)[1])
    return values


def work_record_command_allowed(parts: list[str], role: str) -> bool:
    if not parts or "--root" in parts or any(part.startswith("--root=") for part in parts):
        return False
    command = parts[0]
    if command == "approve" or command not in WORK_RECORD_COMMANDS.get(role, set()):
        return False
    if command in {
        "context",
        "transition",
        "append-evidence",
        "accept-handoff",
        "append-review",
        "attach-rule",
        "bind-claim",
        "add-question",
        "resolve-question",
        "capture-repository",
        "capture-org-review",
        "run-verification",
    }:
        return flag_values(parts[1:], "--role") == [role]
    if command == "create-handoff":
        return flag_values(parts[1:], "--from-role") == [role]
    return command in {"init", "validate"}


def proposal_draft_path_allowed(raw: str, root: Path) -> bool:
    path = Path(raw)
    if path.is_absolute():
        return False
    draft_root = (root / ".cache/knowledge-proposals").resolve(strict=False)
    candidate = (root / path).resolve(strict=False)
    try:
        relative = candidate.relative_to(draft_root)
    except ValueError:
        return False
    return bool(relative.parts) and candidate.suffix.lower() in {".yaml", ".yml"}


def knowledge_registry_command_allowed(
    parts: list[str], role: str, root: Path = HARNESS_ROOT
) -> bool:
    if not parts or "--root" in parts or any(part.startswith("--root=") for part in parts):
        return False
    command = parts[0]
    if command not in KNOWLEDGE_REGISTRY_COMMANDS.get(role, set()):
        return False
    if command == "validate":
        return len(parts) == 1
    if command == "query":
        allowed_flags = {
            "--claim-id",
            "--domain",
            "--claim-type",
            "--subject-kind",
            "--subject-identity",
            "--environment",
            "--org-key",
            "--package-namespace",
            "--at",
        }
        semantic_filter_seen = False
        index = 1
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                if flag not in allowed_flags or not value:
                    return False
                semantic_filter_seen = semantic_filter_seen or flag != "--at"
                index += 1
                continue
            if token not in allowed_flags or index + 1 >= len(parts) or parts[index + 1].startswith("--"):
                return False
            semantic_filter_seen = semantic_filter_seen or token != "--at"
            index += 2
        return index == len(parts) and semantic_filter_seen
    if command != "propose" or role != "config-investigator":
        return False
    values: dict[str, list[str]] = {
        "--claim-file": [],
        "--evidence-file": [],
        "--expected-revision": [],
    }
    index = 1
    while index < len(parts):
        token = parts[index]
        if "=" in token:
            flag, value = token.split("=", 1)
            if flag not in values or not value:
                return False
            values[flag].append(value)
            index += 1
            continue
        if token not in values or index + 1 >= len(parts) or parts[index + 1].startswith("--"):
            return False
        values[token].append(parts[index + 1])
        index += 2
    if (
        len(values["--claim-file"]) != 1
        or not values["--evidence-file"]
        or len(values["--evidence-file"]) > 10
        or len(values["--expected-revision"]) != 1
        or not values["--expected-revision"][0].isdigit()
    ):
        return False
    draft_paths = [*values["--claim-file"], *values["--evidence-file"]]
    return all(proposal_draft_path_allowed(value, root) for value in draft_paths)


def force_app_knowledge_command_allowed(parts: list[str], role: str) -> bool:
    if role != "config-investigator" or not parts:
        return False
    if parts == ["inventory"]:
        return True
    if parts == ["draft"]:
        return True
    if len(parts) == 3 and parts[0] == "draft" and parts[1] == "--observed-at":
        return bool(
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                parts[2],
            )
        )
    return False


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
    work_record = (root / "scripts/work_record.py").resolve()
    knowledge_registry = (root / "scripts/knowledge_registry.py").resolve()
    force_app_knowledge = (root / "scripts/force_app_knowledge.py").resolve()
    remainder = parts[index + 1 :]
    if script == preflight:
        return (
            len(remainder) == 2
            and remainder[0] == "--capability"
            and remainder[1] in PREFLIGHT_CAPABILITIES.get(role, set())
        )
    if script == work_record:
        return work_record_command_allowed(remainder, role)
    if script == knowledge_registry:
        return knowledge_registry_command_allowed(remainder, role, root)
    if script == force_app_knowledge:
        return force_app_knowledge_command_allowed(remainder, role)
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
        brain_relative = candidate.relative_to(METADATA_ROOT.resolve()).as_posix()
    except ValueError:
        return False
    if any(brain_relative.startswith(prefix) for prefix in METADATA_EDIT_PREFIXES):
        return True
    if is_governed_record_path(brain_relative):
        return False
    return allowed(brain_relative, ALLOWED_PREFIXES["development-assistant"])


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
    if is_governed_record_path(relative_path):
        return False
    return any(
        relative_path.startswith(prefix)
        if prefix.endswith("/")
        else relative_path == prefix
        for prefix in prefixes
    )


def role_path_allowed(relative_path: str, role: str) -> bool:
    if role == "solution-designer" and re.fullmatch(
        r"\.ai/change-records/[^/]+/design\.md", relative_path
    ):
        return True
    return allowed(relative_path, ALLOWED_PREFIXES[role])


def is_governed_record_path(relative_path: str) -> bool:
    return bool(
        re.fullmatch(r"\.ai/change-records/[^/]+/record\.json", relative_path)
        or re.fullmatch(r"\.ai/change-records/[^/]+/handoffs/[^/]+\.json", relative_path)
        or re.fullmatch(r"\.ai/change-records/[^/]+/evidence/[^/]+\.json", relative_path)
        or re.fullmatch(r"\.ai/knowledge/(claims|evidence|reviews)/[^/]+\.(yaml|yml|json)", relative_path)
        or re.fullmatch(r"\.ai/knowledge/(automation-map|business-processes|current-implementation|field-descriptions|glossary|integration-map|known-limitations|object-descriptions|object-relations)\.md", relative_path)
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
                        f"development-assistant may edit only root Salesforce force-app/manifest/tests/e2e source, reviewed documentation/change records, and ignored ADO cache: {', '.join(denied_raw)}",
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

    denied = sorted(path for path in found if not role_path_allowed(path, args.role))
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
