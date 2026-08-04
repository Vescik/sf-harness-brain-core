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
        # Agent-authored org-usage probes-files only (contract §6.6). Receipts in the same
        # tree are written exclusively by the entry-org-attach executor; nothing here is
        # Knowledge authority — canonical orgUsage flows only through the governed command.
        ".cache/org-usage/",
    ),
    # Repo-source Knowledge maintenance: fills draft sentinels and runs the governed knowledge
    # commands. Org surface is the read-only review_soql_query facade MCP tool only (owner
    # decision 2026-08-04); org terminal commands stay denied and there is no work-record
    # authority.
    "knowledge-curator": (
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
        "digest",
        "attach-rule",
        "add-question",
        "resolve-question",
        "capture-repository",
        "capture-org-review",
        "create-handoff",
        "bind-entry",
    },
    "config-investigator": {
        "validate",
        "context",
        "accept-handoff",
        "append-evidence",
        "digest",
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
        "digest",
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
        "digest",
        "capture-repository",
        "run-verification",
        "create-handoff",
    },
    # `transition` mirrors work_record.py role_allows_transition, which limits the reviewer to
    # review/safe -> complete/complete — without the grant, completion had no agent entry point.
    "guardrail-reviewer": {
        "validate",
        "context",
        "transition",
        "accept-handoff",
        "capture-repository",
        "capture-org-review",
        "run-verification",
        "append-review",
        "create-handoff",
    },
}

# Knowledge maintenance does not require the org-facing investigator surface.
KNOWLEDGE_MUTATION_ROLES = frozenset({"config-investigator", "knowledge-curator"})
# Roles allowed to run force_app_knowledge.py at all (extraction/drafting authority).
FORCE_APP_KNOWLEDGE_ROLES = frozenset({"config-investigator", "knowledge-curator"})
FORCE_APP_COMMAND_FLAGS = {
    "inventory": frozenset(),
    "entry-readiness": frozenset(),
    "entry-edge-health": frozenset(),
    # Read-only path/name -> component mapping for the selected-files lane; --write only saves
    # the derived view under the ignored .cache/knowledge-proposals/ workspace.
    "resolve": frozenset({"--path", "--name", "--write"}),
    # Writes only under the ignored .cache/knowledge-proposals/ workspace (evidence-doc F-14).
    "feature-crawl": frozenset({"--feature", "--anchors", "--depth", "--hub"}),
}

# One-file Knowledge Entry executor (docs/knowledge-one-file-contract.md v1.1). Reads are
# available to every role; mutations require the knowledge mutation roles, all writes flow
# through the executor (the artifacts path itself is governed), and the safety hook answers
# `ask` for the four approval/revocation commands — its pattern is
# `(?:entry|feature)-(?:approve|revoke)`, one alternation over both record kinds, because a
# Feature approval is the same act as an entry approval. The other four commands in
# KNOWLEDGE_STORE_MUTATION_COMMANDS (entry-draft, entry-describe, feature-propose,
# feature-describe) write no approval record and are gated by the mutation role alone.
# tests/test_guard_parser_contract.py diffs these flags against knowledge_store.build_parser.
# entry-review only renders a review artifact under output/; it mutates no Knowledge, so it
# stays outside the mutation set while still being a curator/investigator-shaped action.
KNOWLEDGE_STORE_MUTATION_COMMANDS = frozenset(
    {"entry-draft", "entry-describe", "entry-approve", "entry-revoke",
     # feature-review / feature-status / feature-check are reads, matching entry-review.
     "feature-propose", "feature-describe", "feature-approve", "feature-revoke",
     # Org-usage attach/detach (contract §6.6): mutations that deliberately spend NO chat
     # click (owner D-3 2026-08-03, schema-as-instrument) — the verb-partition test asserts
     # they sit in the authoring bucket. Role-narrowed further by ORG_ATTACH_ROLES below.
     "entry-org-attach", "entry-org-detach"}
)
# Narrower than KNOWLEDGE_MUTATION_ROLES: only the org-facing investigator may attach org
# observations; the curator never gains org authority (contract §6.6).
ORG_ATTACH_COMMANDS = frozenset({"entry-org-attach", "entry-org-detach"})
ORG_ATTACH_ROLES = frozenset({"config-investigator"})
KNOWLEDGE_STORE_COMMAND_FLAGS = {
    "entry-draft": frozenset(
        {
            "--metadata-type",
            "--full-name",
            "--namespace",
            "--purpose-file",
            "--source-api-version",
            "--candidate-keyword",
        }
    ),
    "entry-approve": frozenset({"--entry"}),
    "entry-review": frozenset({"--identity"}),
    "entry-describe": frozenset({"--identity", "--purpose-file", "--limitation", "--clear-limitations"}),
    "entry-context": frozenset({"--identity", "--max-source-chars"}),
    "entry-revoke": frozenset({"--identity", "--rationale"}),
    "entry-status": frozenset({"--identity"}),
    "entry-coverage": frozenset(),
    "entry-check": frozenset({"--changed-since"}),
    # Read-only citation verdicts (entryRefs); the entry-side successor of the registry's
    # verify-citations, relocated in v1-retirement P0. Reads stay universal.
    "entry-verify-citations": frozenset({"--envelope", "--entry-ref"}),
    "entry-org-attach": frozenset({"--identity", "--org", "--probes-file"}),
    "entry-org-detach": frozenset({"--identity", "--org", "--rationale"}),
    # Feature Entries (contract §13). The boundary rule is human-authored, so propose/describe
    # are mutations; review/status/check are reads, mirroring the entry-review precedent.
    "feature-propose": frozenset(
        {"--slug", "--name", "--anchor", "--hub", "--depth", "--include", "--exclude",
         "--assurance-floor", "--replace"}
    ),
    "feature-describe": frozenset({"--slug", "--purpose-file"}),
    "feature-status": frozenset({"--slug"}),
    "feature-review": frozenset({"--slug"}),
    "feature-approve": frozenset({"--feature"}),
    "feature-revoke": frozenset({"--slug", "--rationale"}),
    "feature-check": frozenset(),
}


# Knowledge Entry search (docs/knowledge-one-file-contract.md, T08b). Every role may read;
# `build` writes only the git-ignored generated cache under .cache/knowledge-search/, which
# is never Knowledge authority, so it needs no mutation role. Flags mirror the parser and are
# pinned by tests/test_guard_parser_contract.py.
KNOWLEDGE_SEARCH_COMMAND_FLAGS = {
    "build": frozenset({"--check", "--full"}),
    "search": frozenset(
        {
            "--text",
            "--identity",
            "--metadata-type",
            "--namespace",
            "--state",
            "--facet",
            "--relation-anchor",
            "--relation-kind",
            "--direction",
            "--include-heuristic",
            "--mode",
            "--top",
        }
    ),
    "explain": frozenset({"--identity", "--state", "--top", "--include-heuristic"}),
    "impact": frozenset(
        {"--identity", "--depth", "--direction", "--state", "--top", "--include-heuristic"}
    ),
    "context": frozenset(
        {"--identity", "--state", "--top", "--include-heuristic", "--direction"}
    ),
    "tree": frozenset({"--feature", "--state", "--include-heuristic", "--direction"}),
    "feature-drift": frozenset({"--feature", "--state", "--include-heuristic"}),
    "feature-dossier": frozenset({"--feature", "--state", "--include-heuristic"}),
    "edge-health": frozenset(),
    "capabilities": frozenset({"--metadata-type"}),
}
# Boolean flags take no value, so the parser must not skip the token after them. A flag missing
# from these sets is a fail-open, not a cosmetic slip: the guard skips the next token unvalidated,
# so `build --full --rm` was allowed outright. tests/test_guard_parser_contract.py derives these
# from argparse (`nargs == 0`) so a future store_true cannot be forgotten.
KNOWLEDGE_SEARCH_VALUELESS_FLAGS = frozenset({"--check", "--full", "--include-heuristic"})
# Empty because no knowledge_store subcommand declares a boolean yet. The constant and its
# branch in knowledge_store_command_allowed exist so the first one cannot fail open the way
# `--full` did on the search side; the arity-derived contract test is what will require it here.
KNOWLEDGE_STORE_VALUELESS_FLAGS: frozenset[str] = frozenset({"--replace", "--clear-limitations"})


def knowledge_search_command_allowed(parts: list[str], role: str) -> bool:
    if not parts or parts[0] not in KNOWLEDGE_SEARCH_COMMAND_FLAGS:
        return False
    allowed_flags = KNOWLEDGE_SEARCH_COMMAND_FLAGS[parts[0]]
    index = 1
    while index < len(parts):
        token = parts[index]
        if not token.startswith("--"):
            return False
        if "=" in token:
            flag = token.split("=", 1)[0]
            index += 1
        elif token in KNOWLEDGE_SEARCH_VALUELESS_FLAGS:
            flag = token
            index += 1
        else:
            flag = token
            index += 2
        if flag not in allowed_flags:
            return False
    return True


def knowledge_store_command_allowed(parts: list[str], role: str) -> bool:
    if not parts or parts[0] not in KNOWLEDGE_STORE_COMMAND_FLAGS:
        return False
    command = parts[0]
    if command in ORG_ATTACH_COMMANDS and role not in ORG_ATTACH_ROLES:
        return False
    if command in KNOWLEDGE_STORE_MUTATION_COMMANDS and role not in KNOWLEDGE_MUTATION_ROLES:
        return False
    allowed_flags = KNOWLEDGE_STORE_COMMAND_FLAGS[command]
    index = 1
    while index < len(parts):
        token = parts[index]
        if not token.startswith("--"):
            return False
        if "=" in token:
            flag = token.split("=", 1)[0]
            index += 1
        elif token in KNOWLEDGE_STORE_VALUELESS_FLAGS:
            flag = token
            index += 1
        else:
            flag = token
            index += 2
        if flag not in allowed_flags:
            return False
    return True

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
    # Contract-surface entry: flagless; authorization for the exact ["orgs"] invocation is the
    # fast path in salesforce_read_command_allowed, and any flagged variant stays denied.
    "orgs": frozenset(),
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
        "bind-entry",
        "add-question",
        "resolve-question",
        "capture-repository",
        "capture-org-review",
        "run-verification",
    }:
        return flag_values(parts[1:], "--role") == [role]
    if command == "create-handoff":
        return flag_values(parts[1:], "--from-role") == [role]
    return command in {"init", "validate", "digest"}


def handover_draft_path_allowed(raw: str, root: Path) -> bool:
    """Rendered handover drafts only: containment mirror of manifest_input_path_allowed."""
    path = Path(raw)
    if path.is_absolute():
        return False
    draft_root = (root / "output/handover").resolve(strict=False)
    candidate = (root / path).resolve(strict=False)
    try:
        relative = candidate.relative_to(draft_root)
    except ValueError:
        return False
    return bool(relative.parts) and candidate.suffix.lower() == ".md"


def force_app_knowledge_command_allowed(parts: list[str], role: str) -> bool:
    if not parts or parts[0] not in FORCE_APP_COMMAND_FLAGS:
        return False
    if role not in FORCE_APP_KNOWLEDGE_ROLES:
        return False
    if parts == ["inventory"]:
        return True
    if parts[0] == "feature-crawl":
        index = 1
        seen_feature = False
        while index < len(parts):
            token = parts[index]
            if "=" in token:
                flag, value = token.split("=", 1)
                index += 1
            else:
                flag, value = token, parts[index + 1] if index + 1 < len(parts) else ""
                index += 2
            if flag not in FORCE_APP_COMMAND_FLAGS[parts[0]]:
                return False
            if flag == "--feature":
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,79}", value):
                    return False
                seen_feature = True
            elif flag == "--anchors":
                names = [name.strip() for name in value.split(",") if name.strip()]
                if not names or len(names) > 10 or not all(
                    re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name) for name in names
                ):
                    return False
            elif flag == "--hub":
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value):
                    return False
            elif flag == "--depth":
                if not value.isdigit() or not 1 <= int(value) <= 3:
                    return False
        return seen_feature
    if parts[0] == "resolve":
        # Read-only lexical mapping of paths/names onto inventory components; it never opens
        # the input paths, so validation is argument hygiene, not filesystem authority. The
        # resolver deliberately accepts absolute macOS/Windows paths and keeps everything from
        # the force-app segment down (pinned files arrive as absolute paths on the Windows
        # team's machines), so the guard requires that segment rather than repo-relativity.
        # Names carry spaces and colons legitimately (Layout fullNames, component ids).
        index = 1
        seen_input = False
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
            if flag == "--path":
                if not re.fullmatch(r"[A-Za-z0-9_.:\\/ \-]{1,300}", value):
                    return False
                normalized = value.replace("\\", "/")
                if "force-app" not in normalized.casefold() or ".." in normalized.split("/"):
                    return False
                seen_input = True
            elif flag == "--name":
                if not re.fullmatch(r"[A-Za-z0-9_.: \-]{1,120}", value):
                    return False
                seen_input = True
            else:
                return False
        return seen_input
    return False


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
    force_app_knowledge = (root / "scripts/force_app_knowledge.py").resolve()
    salesforce_read = (root / "scripts/salesforce_read.py").resolve()
    validate_harness = (root / "scripts/validate_harness.py").resolve()
    run_evals = (root / "scripts/run_evals.py").resolve()
    validate_handover_output = (root / "scripts/validate_handover_output.py").resolve()
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
    if script == (root / "scripts/knowledge_store.py").resolve():
        return knowledge_store_command_allowed(remainder, role)
    if script == (root / "scripts/knowledge_search.py").resolve():
        return knowledge_search_command_allowed(remainder, role)
    if script == force_app_knowledge:
        return force_app_knowledge_command_allowed(remainder, role)
    if script == salesforce_read:
        return salesforce_read_command_allowed(remainder, role)
    if script == validate_handover_output:
        # Read-only render self-check, every role (same rationale as validate_harness above).
        # --template is deliberately NOT accepted here: guarded agents may only check a draft
        # against the canonical committed template; the flag exists for humans, tests, and CI.
        return len(remainder) == 1 and handover_draft_path_allowed(remainder[0], root)
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
    # The one-file entry patterns match case-folded so NTFS case variants (Foo.MD, .AI/...)
    # cannot slip past the governed boundary (contract §3, review R1-10).
    lowered = relative_path.casefold()
    return bool(
        re.fullmatch(r"\.ai/change-records/[^/]+/record\.json", relative_path)
        or re.fullmatch(r"\.ai/change-records/[^/]+/handoffs/[^/]+\.json", relative_path)
        or re.fullmatch(r"\.ai/change-records/[^/]+/evidence/[^/]+\.json", relative_path)
        or re.fullmatch(r"\.ai/knowledge/artifacts/.+\.md", lowered)
        or lowered == ".ai/knowledge/artifacts-ledger.jsonl"
        # Feature Entries and their ledger. The FILE needs its own arm, not just the ledger:
        # without it an agent could rewrite an approved boundary rule through the ordinary
        # write path and the digest pin would never see it.
        or re.fullmatch(r"\.ai/knowledge/features/[^/]+\.md", lowered)
        or lowered == ".ai/knowledge/features-ledger.jsonl"
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
                        "force_app_knowledge.py, salesforce_read.py, "
                        "validate_handover_output.py), "
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
