#!/usr/bin/env python3
"""PreToolUse hook enforcing path boundaries for restricted custom agents."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ALLOWED_PREFIXES = {
    "solution-designer": (
        ".cache/ado-items/",
        ".cache/ado-wiki/",
        "output/solution-design/",
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
        ".cache/ado-wiki/",
        ".cache/test-cases/",
    ),
    "development-assistant": (
        "output/documentation/",
        ".cache/ado-items/",
        ".cache/ado-wiki/",
        # Agent-authored dev-tool batch PLANS only; approval stays human-terminal-only
        # (scripts/approve_dev_tool_batch.py — the safety hook denies Copilot invocations)
        # and receipts under .cache/receipts/ are written exclusively by governed executors.
        ".cache/devtool-batches/",
    ),
    "guardrail-reviewer": (),
}

HARNESS_ROOT = Path(__file__).resolve().parents[1]
METADATA_ROOT = HARNESS_ROOT
METADATA_EDIT_PREFIXES = ("force-app/", "manifest/", "tests/e2e/")
# Preflight is a read-only, fail-closed diagnostic; restricting which CAPABILITY a role may
# even ASK about only produced live agent flailing (denied 5-8 commands in a row before giving
# up — 2026-07-14 usability fix). Every role may run every preflight check, including the bare
# no-argument form; the mutating boundaries stay where they belong (hook + write guards).
PREFLIGHT_CAPABILITIES = frozenset(
    {
        "base",
        "ado",
        "release",
        "metadata",
        "salesforce-read",
        "salesforce-write",
        "salesforce-review",
        "playwright",
    }
)

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
# `approve-claim` (owner decision 2026-07-14) lets the Investigator REQUEST promotion/rejection;
# the safety hook answers `ask`, so a human confirms every invocation in chat and the registry
# records the local-config reviewer identity with mechanism copilot-chat-confirmation. The
# file-based review/promote commands remain human-terminal-only.
_KNOWLEDGE_READ_COMMANDS = {
    "validate",
    "query",
    "explain",
    "render-indexes",
    "reconcile",
    "keyword-report",
    "stale-report",
    "verify-citations",
}
KNOWLEDGE_REGISTRY_COMMANDS = {
    "solution-designer": set(_KNOWLEDGE_READ_COMMANDS),
    "config-investigator": _KNOWLEDGE_READ_COMMANDS | {"propose", "approve-claim"},
    "development-assistant": set(_KNOWLEDGE_READ_COMMANDS),
    "test-strategist": set(_KNOWLEDGE_READ_COMMANDS),
    "guardrail-reviewer": set(_KNOWLEDGE_READ_COMMANDS),
}

# Per-subcommand flag allowlists for the two knowledge CLIs. tests/test_guard_parser_contract.py
# diffs these against the scripts' argparse parsers, so a parser flag added without a guard
# decision (or a guard typo) fails CI instead of silently denying/allowing at runtime.
KNOWLEDGE_QUERY_FLAGS = frozenset({
    "--claim-id",
    "--domain",
    "--claim-type",
    "--subject-kind",
    "--subject-identity",
    "--environment",
    "--org-key",
    "--package-namespace",
    "--keyword",
    "--text",
    "--feature",
    "--uses-object",
    "--uses-field",
    "--invokes",
    "--related",
    "--depth",
    "--search",
    "--top",
    "--at",
})
# Flags that do not count as a semantic filter on their own (query must narrow by content).
KNOWLEDGE_QUERY_NON_SEMANTIC_FLAGS = frozenset({"--at", "--depth", "--top"})
KNOWLEDGE_APPROVE_FLAGS = frozenset({
    "--claim-id",
    "--expected-revision",
    "--claim-spec",
    "--decision",
    "--rationale",
})
KNOWLEDGE_PROPOSE_FLAGS = frozenset(
    {"--claim-file", "--evidence-file", "--expected-revision", "--refresh-verified"}
)
KNOWLEDGE_COMMAND_FLAGS = {
    "validate": frozenset(),
    "keyword-report": frozenset(),
    "render-indexes": frozenset({"--check"}),
    "reconcile": frozenset({"--claim-file"}),
    "query": KNOWLEDGE_QUERY_FLAGS,
    "explain": frozenset({"--identity", "--kind", "--at"}),
    "stale-report": frozenset({"--warn-days", "--at"}),
    "verify-citations": frozenset({"--envelope", "--claim-ref", "--at"}),
    "propose": KNOWLEDGE_PROPOSE_FLAGS,
    "approve-claim": KNOWLEDGE_APPROVE_FLAGS,
}

# Roles allowed to run force_app_knowledge.py at all (extraction/drafting authority).
FORCE_APP_KNOWLEDGE_ROLES = frozenset({"config-investigator"})
FORCE_APP_COMMAND_FLAGS = {
    "inventory": frozenset(),
    "worklist": frozenset({"--metadata-type", "--write"}),
    "coverage": frozenset({"--write"}),
    "relations-worklist": frozenset({"--metadata-type", "--write"}),
    "relation-health": frozenset({"--write"}),
    "relations-draft": frozenset({"--observed-at", "--metadata-type", "--limit", "--include-heuristic"}),
    "refresh": frozenset({"--observed-at", "--metadata-type", "--warn-days", "--limit", "--dry-run"}),
    "draft": frozenset({"--observed-at", "--metadata-type"}),
}

PATH_KEYS = {
    "path",
    "filepath",
    "file_path",
    "filename",
    "files",
    "paths",
}

# Guarded read-only Salesforce access (structured SOQL + metadata retrieve). Available to the
# design/build/verify roles so an agent can ground its context in the connected org (principles →
# knowledge → org reality) without delegating every record read. The script itself enforces the
# object allowlist, field/limit bounds, and the live sandbox proof. No mutation surface.
# (Widened from investigator/reviewer-only by the 2026-07-14 owner decision on the read-only
# MCP/CLI model — see .ai/memory/decisions-log.md.)
SALESFORCE_READ_ROLES = {
    "solution-designer",
    "config-investigator",
    "development-assistant",
    "guardrail-reviewer",
}
SALESFORCE_READ_FLAGS = {
    "records": {"--org", "--object", "--fields", "--limit", "--order-by"},
    "retrieve": {"--org", "--metadata"},
}


def salesforce_read_command_allowed(parts: list[str], role: str) -> bool:
    if role not in SALESFORCE_READ_ROLES or not parts:
        return False
    if "--root" in parts or any(part.startswith("--root=") for part in parts):
        return False
    if parts == ["orgs"]:
        # Scoped enumeration of configured aliases only; the script enforces the safety toggle.
        return True
    allowed = SALESFORCE_READ_FLAGS.get(parts[0])
    if allowed is None:
        return False
    rest = parts[1:]
    seen_org = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--") and "=" in token:
            flag = token.split("=", 1)[0]
            if flag not in allowed:
                return False
            seen_org = seen_org or flag == "--org"
            index += 1
            continue
        if token not in allowed or index + 1 >= len(rest) or rest[index + 1].startswith("--"):
            return False
        seen_org = seen_org or token == "--org"
        index += 2
    return seen_org


# Set by main() so denial logging can name the tool/role without threading them everywhere.
_EVENT_CONTEXT = {"tool": "", "role": ""}


def _log_decision(decision: str, reason: str | None) -> None:
    """Append deny/ask decisions to an ignored local log; never raises (see safety hook twin)."""

    try:
        log_dir = HARNESS_ROOT / ".cache"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "copilot_role_guard",
            "role": _EVENT_CONTEXT["role"],
            "tool": _EVENT_CONTEXT["tool"],
            "decision": decision,
            "reason": reason or "",
        }
        with (log_dir / "denials.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if decision is None:
        return {"continue": True}
    _log_decision(decision, reason)
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
    }
    if reason:
        output["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": output}


def is_edit_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    # "create_file"/"apply_patch"/"write" are VS Code's snake_case editor tools; the earlier
    # camelCase-only tokens ("createfile") missed them, letting edits bypass role path boundaries.
    return any(
        token in lowered
        for token in ("edit", "createfile", "create_file", "replace", "insert", "patch", "write")
    )


def is_execute_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    # runTask/run_task and runCommands/run_commands can spawn shell; they must obey the same
    # command allowlist as the terminal tools.
    return any(
        token in lowered
        for token in ("execute", "terminal", "runinterminal", "run_in_terminal", "runtask", "run_task", "runcommands", "run_commands")
    )


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
    if command in {"validate", "keyword-report"}:
        return len(parts) == 1
    if command == "render-indexes":
        return parts[1:] in ([], ["--check"])
    if command == "reconcile":
        # Read-only classification of a DRAFT claim against the registry; input stays in the
        # ignored proposal workspace like propose inputs.
        if len(parts) == 3 and parts[1] == "--claim-file":
            return proposal_draft_path_allowed(parts[2], root)
        if len(parts) == 2 and parts[1].startswith("--claim-file="):
            return proposal_draft_path_allowed(parts[1].split("=", 1)[1], root)
        return False
    if command == "query":
        allowed_flags = KNOWLEDGE_QUERY_FLAGS
        semantic_filter_seen = False
        index = 1
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                if flag not in allowed_flags or not value:
                    return False
                semantic_filter_seen = semantic_filter_seen or flag not in KNOWLEDGE_QUERY_NON_SEMANTIC_FLAGS
                index += 1
                continue
            if token not in allowed_flags or index + 1 >= len(parts) or parts[index + 1].startswith("--"):
                return False
            semantic_filter_seen = semantic_filter_seen or token not in KNOWLEDGE_QUERY_NON_SEMANTIC_FLAGS
            index += 2
        return index == len(parts) and semantic_filter_seen
    if command == "explain":
        # Read-only composite subject view; requires the identity so it cannot dump the store.
        allowed_flags = KNOWLEDGE_COMMAND_FLAGS["explain"]
        identity_seen = False
        index = 1
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                if flag not in allowed_flags or not value:
                    return False
                identity_seen = identity_seen or flag == "--identity"
                index += 1
                continue
            if token not in allowed_flags or index + 1 >= len(parts) or parts[index + 1].startswith("--"):
                return False
            identity_seen = identity_seen or token == "--identity"
            index += 2
        return identity_seen
    if command in {"stale-report", "verify-citations"}:
        # Read-only advisory reports; envelope inputs stay repository-contained at runtime.
        allowed_flags = KNOWLEDGE_COMMAND_FLAGS[command]
        index = 1
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                if flag not in allowed_flags or not value:
                    return False
                index += 1
                continue
            if token not in allowed_flags or index + 1 >= len(parts) or parts[index + 1].startswith("--"):
                return False
            index += 2
        return True
    if command == "approve-claim":
        if role != "config-investigator":
            return False
        allowed_flags = KNOWLEDGE_APPROVE_FLAGS
        seen: dict[str, str] = {}
        claim_specs: list[str] = []
        index = 1
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag = token
                if index + 1 >= len(parts) or parts[index + 1].startswith("--"):
                    return False
                value = parts[index + 1]
                index += 2
            if flag not in allowed_flags or not value:
                return False
            if flag == "--claim-spec":
                claim_specs.append(value)
            else:
                seen[flag] = value
        if seen.get("--decision", "verify") not in {"verify", "reject"}:
            return False
        if claim_specs:
            # Batch form: one human confirmation covers up to 25 explicit claim:revision pairs.
            return (
                "--claim-id" not in seen
                and "--expected-revision" not in seen
                and len(claim_specs) <= 25
                and all(
                    re.fullmatch(r"KCLM-[A-Z0-9][A-Z0-9-]{2,79}:\d+", spec)
                    for spec in claim_specs
                )
            )
        return (
            bool(re.fullmatch(r"KCLM-[A-Z0-9][A-Z0-9-]{2,79}", seen.get("--claim-id", "")))
            and seen.get("--expected-revision", "").isdigit()
        )
    if command != "propose" or role != "config-investigator":
        return False
    # --refresh-verified is the explicit acknowledgement that a verified/stale claim is being
    # demoted to a new proposed revision (refresh workflow); the registry enforces when it is
    # actually applicable, the guard only recognizes the bare flag.
    values: dict[str, list[str]] = {
        flag: [] for flag in KNOWLEDGE_PROPOSE_FLAGS - {"--refresh-verified"}
    }
    index = 1
    while index < len(parts):
        token = parts[index]
        if token == "--refresh-verified":
            index += 1
            continue
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
    if role not in FORCE_APP_KNOWLEDGE_ROLES or not parts:
        return False
    if parts[0] not in FORCE_APP_COMMAND_FLAGS:
        return False
    if parts == ["inventory"]:
        return True
    if parts[0] == "worklist":
        # Derived read-only batch status; --write only saves the derived view under the
        # ignored .cache/knowledge-proposals/ workspace.
        index = 1
        while index < len(parts):
            token = parts[index]
            if token == "--write":
                index += 1
                continue
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
                index += 2
            if flag != "--metadata-type" or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value):
                return False
        return True
    if parts[0] == "coverage":
        # Read-only documentation-coverage summary; --write only saves the derived view under the
        # ignored .cache/knowledge-proposals/ workspace.
        return parts[1:] in ([], ["--write"])
    if parts[0] == "relations-worklist":
        # Derived read-only edge-granular relation-claim status; --write only saves the derived
        # view under the ignored .cache/knowledge-proposals/ workspace. Same shape as worklist.
        index = 1
        while index < len(parts):
            token = parts[index]
            if token == "--write":
                index += 1
                continue
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
                index += 2
            if flag != "--metadata-type" or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value):
                return False
        return True
    if parts[0] == "relation-health":
        # Read-only orphaned relation-claim report; --write only saves the derived view under the
        # ignored .cache/knowledge-proposals/ workspace. Never mutates Knowledge.
        return parts[1:] in ([], ["--write"])
    if parts[0] == "relations-draft":
        # Drafts only proposed-candidate files under the ignored .cache/knowledge-proposals/
        # workspace, same authority as draft. --limit is bounded to guard against an unbounded
        # repo-wide sweep dumping thousands of drafts in one call.
        text_validators = {
            "--observed-at": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            "--metadata-type": r"[A-Za-z][A-Za-z0-9_]{0,79}",
        }
        index = 1
        while index < len(parts):
            token = parts[index]
            if token == "--include-heuristic":
                index += 1
                continue
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
                index += 2
            if flag == "--limit":
                if not value.isdigit() or not (1 <= int(value) <= 2000):
                    return False
                continue
            pattern = text_validators.get(flag)
            if pattern is None or not re.fullmatch(pattern, value):
                return False
        return True
    if parts[0] == "refresh":
        # Selects only drifted/expired/expiring verified claims and delegates to draft with the
        # same authority; outputs stay under the ignored .cache/knowledge-proposals/ workspace.
        # --warn-days is bounded to a year so a typo cannot select the entire verified store,
        # and --limit shares the relations-draft anti-sweep bound.
        text_validators = {
            "--observed-at": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            "--metadata-type": r"[A-Za-z][A-Za-z0-9_]{0,79}",
        }
        index = 1
        while index < len(parts):
            token = parts[index]
            if token == "--dry-run":
                index += 1
                continue
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
                index += 2
            if flag == "--limit":
                if not value.isdigit() or not (1 <= int(value) <= 2000):
                    return False
                continue
            if flag == "--warn-days":
                if not value.isdigit() or not (0 <= int(value) <= 365):
                    return False
                continue
            pattern = text_validators.get(flag)
            if pattern is None or not re.fullmatch(pattern, value):
                return False
        return True
    if parts[0] != "draft":
        return False
    validators = {
        "--observed-at": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        "--metadata-type": r"[A-Za-z][A-Za-z0-9_]{0,79}",
    }
    index = 1
    while index < len(parts):
        token = parts[index]
        if "=" in token:
            flag, value = token.split("=", 1)
            index += 1
        else:
            flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
            index += 2
        pattern = validators.get(flag)
        if pattern is None or not re.fullmatch(pattern, value):
            return False
    return True


# Read-only orientation commands available to every role. Rationale: a default-deny terminal
# that blocks `git status`/`ls`/`grep` doesn't make the harness safer — it paralyzes the agent
# into thrashing (documented incidents), while the genuinely dangerous operations (sf, deploys,
# rm, redirects, chaining) are blocked elsewhere. The metacharacter gate in allowed_role_command
# already rejects ; & | < > ` $ and newlines, so none of these can chain, redirect, or substitute.
SIMPLE_READ_COMMANDS = frozenset({
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "where", "which",
    "grep", "findstr", "rg", "tree", "find",
    # PowerShell read cmdlets (Windows default shell)
    "get-childitem", "get-content", "get-location", "get-item", "select-string", "test-path",
})
GIT_READ_SUBCOMMANDS = frozenset({
    "status", "diff", "log", "show", "blame", "describe", "shortlog",
    "rev-parse", "ls-files", "grep", "branch", "remote",
})
# Tool version checks are pure orientation; denying them only makes agents flail.
VERSION_CHECK_EXECUTABLES = frozenset({"python", "python3", "py", "node", "npm", "git"})
GIT_BRANCH_LIST_FLAGS = frozenset({"-a", "--all", "-v", "-vv", "-l", "--list", "-r", "--remotes"})
# Flags that turn a read command into a write/exec primitive.
FIND_FORBIDDEN_TOKENS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls"})


def read_only_orientation_command(parts: list[str]) -> bool:
    """Return whether argv is a non-mutating orientation command safe for every role."""

    executable = Path(parts[0]).name.lower().removesuffix(".exe")
    if executable in VERSION_CHECK_EXECUTABLES and parts[1:] == ["--version"]:
        return True
    if executable in SIMPLE_READ_COMMANDS:
        rest = parts[1:]
        if executable == "find" and any(
            token in FIND_FORBIDDEN_TOKENS or token.startswith("-fprint") for token in rest
        ):
            return False
        if executable == "tree" and "-o" in rest:
            return False
        if executable == "rg" and any(token == "--pre" or token.startswith("--pre=") for token in rest):
            return False
        return True
    if executable == "git" and len(parts) >= 2:
        subcommand = parts[1].lower()
        if subcommand not in GIT_READ_SUBCOMMANDS:
            return False
        rest = parts[2:]
        if any(token.startswith("--output") for token in rest):
            return False
        if subcommand == "branch":
            # Listing only: any non-flag argument would create a branch; -d/-D would delete one.
            return all(token in GIT_BRANCH_LIST_FLAGS for token in rest)
        if subcommand == "remote":
            return rest in ([], ["-v"])
        return True
    return False


def allowed_role_command(command: str, root: Path, role: str) -> bool:
    if not command or re.search(r"[;&|`$<>\n\r]", command):
        return False
    # Normalize Windows path separators before POSIX shlex, which otherwise treats "\" as an
    # escape and collapses `.venv\Scripts\python.exe` into one mangled token — silently denying
    # every native Windows command. The guarded scripts take no backslash-bearing arguments.
    try:
        parts = shlex.split(command.replace("\\", "/"))
    except ValueError:
        return False
    if not parts:
        return False
    if read_only_orientation_command(parts):
        return True
    executable = Path(parts[0]).name.lower()
    if (
        role == "development-assistant"
        and executable.removesuffix(".exe").removesuffix(".cmd") == "sf"
        and [part.lower() for part in parts[1:4]] == ["project", "retrieve", "start"]
    ):
        # Read-direction org → repository retrieve. The global safety hook still requires exactly
        # one allowlisted --target-org and per-invocation human confirmation (SAFE-HUMAN-001);
        # deploys and all other raw Salesforce CLI subcommands remain denied.
        return True
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
    salesforce_read = (root / "scripts/salesforce_read.py").resolve()
    validate_harness = (root / "scripts/validate_harness.py").resolve()
    run_evals = (root / "scripts/run_evals.py").resolve()
    remainder = parts[index + 1 :]
    # Read-only self-verification available to every role: agents legitimately check their own
    # work (2026-07-14 usability fix — these were denied and caused live flailing).
    if script in (validate_harness, run_evals):
        return not remainder
    if script == preflight:
        index2 = 0
        while index2 < len(remainder):
            token = remainder[index2]
            if token == "--force":
                index2 += 1
                continue
            if token == "--capability" and index2 + 1 < len(remainder):
                if remainder[index2 + 1] not in PREFLIGHT_CAPABILITIES:
                    return False
                index2 += 2
                continue
            if token == "--max-age-minutes" and index2 + 1 < len(remainder):
                if not remainder[index2 + 1].isdigit():
                    return False
                index2 += 2
                continue
            if token.startswith("--capability="):
                if token.split("=", 1)[1] not in PREFLIGHT_CAPABILITIES:
                    return False
                index2 += 1
                continue
            if token.startswith("--max-age-minutes="):
                if not token.split("=", 1)[1].isdigit():
                    return False
                index2 += 1
                continue
            return False
        return True
    if script == work_record:
        return work_record_command_allowed(remainder, role)
    if script == knowledge_registry:
        return knowledge_registry_command_allowed(remainder, role, root)
    if script == force_app_knowledge:
        return force_app_knowledge_command_allowed(remainder, role)
    if script == salesforce_read:
        return salesforce_read_command_allowed(remainder, role)
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
    _EVENT_CONTEXT["tool"] = tool_name
    _EVENT_CONTEXT["role"] = args.role
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
                        f"{args.role}: this exact command is outside the terminal allowlist. "
                        "Allowed families: guarded harness scripts (scripts/preflight.py, "
                        "validate_harness.py, run_evals.py, work_record.py, "
                        "knowledge_registry.py, force_app_knowledge.py, salesforce_read.py), "
                        "read-only git (status/diff/log/show/ls-files), file reads "
                        "(ls/cat/grep/type/Get-Content), and tool --version checks — all plain, "
                        "single commands with no ; & | < > ` $ chaining. Do not retry variants "
                        "of a denied command; use one of these instead.",
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
