#!/usr/bin/env python3
"""Workspace PreToolUse hook blocking production and destructive agent operations."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# Recursive+force `rm` is handled by has_recursive_force_rm() (tokenized, any flag order,
# quote/backslash-splice resistant) rather than a regex, to avoid catastrophic backtracking
# on large inputs and to scope flag detection to each command segment.
DESTRUCTIVE_PATTERNS = (
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
SCRATCH_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com$",
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
SALESFORCE_REVIEW_TOOLS = {
    "review_org_identity",
    "review_installed_packages",
    "review_object_contract",
}

# MCP tool classification. VS Code may hand the hook either a "server/tool" name or a BARE "tool"
# name (observed live: `core_list_orgs`). Server-prefix matching alone therefore leaks — classify by
# the unqualified tool token too, and fail-closed on unrecognized MCP-shaped tools.
ADO_TOOL_PREFIXES = (
    "core_", "wit_", "wiki", "testplan", "build_", "repo_", "release_",
    "pipelines_", "search_", "advsec_", "work_item",
)
ENUMERATION_TOOLS = frozenset({"list_all_orgs", "core_list_orgs", "core_list_projects"})
SALESFORCE_DEV_TOOL_TOKENS = frozenset({
    "run_soql_query", "list_all_orgs", "deploy_metadata", "retrieve_metadata",
    "run_apex_test", "run_apex_tests", "run_agent_test", "resume_tool_operation",
    "create_scratch_org", "delete_org", "assign_permission_set", "run_code_analyzer",
    "get_username", "deploy", "retrieve",
})
# Built-in editor/agent tools that are safe to pass through (edits are governed by the role guard;
# terminal/sf/browser are handled by the dedicated checks below). VS Code's built-ins are
# snake_case (list_dir, read_file, grep_search, …), so this set uses their real names.
BUILTIN_TOOL_NAMES = frozenset({
    # camel/slash and short forms
    "read", "search", "codebase", "usages", "edit", "editfiles", "createfile",
    "new", "insert", "replace", "applypatch", "runinterminal", "runcommands",
    "terminal", "execute", "fetch", "fetchwebpage", "opensimplebrowser",
    "askquestion", "askquestions", "agent", "think", "todos", "problems",
    "changes", "testfailure", "findtestfiles", "runtests", "extensions",
    "githubrepo", "vscodeapi",
    # real VS Code snake_case tool names
    "read_file", "list_dir", "file_search", "grep_search", "semantic_search",
    "run_in_terminal", "get_terminal_output", "create_file", "create_directory",
    "insert_edit_into_file", "replace_string_in_file", "apply_patch", "get_errors",
    "list_code_usages", "test_search", "run_tests", "get_changed_files", "run_task",
    "get_task_output", "fetch_webpage", "open_simple_browser", "run_vscode_command",
    "get_search_view_results", "test_failure", "get_project_setup_info",
})
SALESFORCE_OBJECT_API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
WORK_RECORD_SCRIPT = re.compile(
    r"(?:^|[\s\"';&|()])(?:[A-Za-z]:)?/?(?:[^\s\"';&|()]+/)*"
    r"work_record\.py(?=$|[\s\"';&|()])",
    re.IGNORECASE,
)
WORK_RECORD_MODULE = re.compile(
    r"(?:^|[\s\"';&|()])-m\s*(?:scripts\.)?work_record(?=$|[\s\"';&|()])",
    re.IGNORECASE,
)
SF_TOKEN = re.compile(r"\bsf(?:\.cmd|\.exe)?\b", re.IGNORECASE)
COMMAND_SEPARATORS = re.compile(r"[;&|\n\r]")


def dequote(command: str) -> str:
    """Collapse shell quote and backslash splices the way the shell does before exec.

    `s''f`, `s""f`, and `s\\f` all execute as `sf`; stripping these characters lets the
    static prefilters see the real token instead of the obfuscated spelling.
    """

    return command.replace("'", "").replace('"', "").replace("\\", "")


def has_recursive_force_rm(text: str) -> bool:
    """Detect `rm` with both a recursive and a force flag in any order.

    Tokenized per command segment (split on shell separators) so a force flag belonging to a
    later command cannot combine with an earlier `rm -r`. De-quoted first so `r''m`/`r\\m`
    splices are caught. Linear in input length — no regex backtracking on the hook hot path.
    """

    for segment in COMMAND_SEPARATORS.split(dequote(text)):
        tokens = segment.split()
        rm_seen = False
        recursive = False
        force = False
        for token in tokens:
            base = token.rsplit("/", 1)[-1]
            if base == "rm":
                rm_seen = True
                continue
            if not rm_seen or not token.startswith("-"):
                continue
            if token.startswith("--"):
                recursive = recursive or token == "--recursive"
                force = force or token == "--force"
            else:
                recursive = recursive or "r" in token[1:].lower()
                force = force or "f" in token[1:].lower()
        if rm_seen and recursive and force:
            return True
    return False


# Set by main() so denial logging can name the tool without threading it through every call.
_EVENT_TOOL_NAME = ""


def _log_decision(decision: str, reason: str | None) -> None:
    """Append deny/ask decisions to an ignored local log so blocked agents are diagnosable.

    VS Code shows the reason only transiently (if at all); without a durable trail the user
    cannot tell which hook denied what. Never raises — observability must not break enforcement.
    """

    try:
        log_dir = HARNESS_ROOT / ".cache"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "copilot_safety_hook",
            "tool": _EVENT_TOOL_NAME,
            "decision": decision,
            "reason": reason or "",
        }
        with (log_dir / "denials.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def hook_response(decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
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
        parsed = urlparse(origin)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and bool(parsed.hostname)
        and bool(
            SANDBOX_HOST.fullmatch(parsed.hostname or "")
            or SCRATCH_HOST.fullmatch(parsed.hostname or "")
        )
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


def salesforce_review_tool_error(
    config: dict[str, Any] | None,
    tool_name: str,
    tool_input: Any,
) -> str | None:
    if config is None:
        return "local harness configuration is missing"
    review = config.get("salesforce", {}).get("review", {})
    if review.get("enabled") is not True or review.get("requireDualSource") is not True:
        return "dual-source Salesforce org review is disabled"
    if not any(
        org.get("allowAgentRead") is True and org.get("allowAgentReview") is True
        for org in config.get("salesforce", {}).get("orgs", [])
    ):
        return "no configured sandbox alias grants agent review"
    lowered = tool_name.lower()
    matched = next((name for name in SALESFORCE_REVIEW_TOOLS if lowered.endswith(name)), None)
    if matched is None:
        return "raw or unknown Salesforce read tool is forbidden"
    if not isinstance(tool_input, dict):
        return "Salesforce review input must be an object"
    keys = set(tool_input)
    if matched in {"review_org_identity", "review_installed_packages"}:
        if keys:
            return "this Salesforce review tool accepts no model-controlled arguments"
        return None
    if keys != {"objectApiName"}:
        return "object review accepts only objectApiName"
    object_name = tool_input.get("objectApiName")
    if not isinstance(object_name, str) or not SALESFORCE_OBJECT_API_NAME.fullmatch(object_name):
        return "objectApiName is malformed"
    allowlist = review.get("allowedObjectApiNames", [])
    # "*" opts into all objects; the name is still regex-validated above, so this only widens
    # which objects are readable, never how they are named.
    if "*" not in allowlist and object_name not in allowlist:
        return "objectApiName is outside the configured review allowlist"
    return None


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


def is_terminal_tool(tool_name: str) -> bool:
    """Return whether a Copilot tool name represents terminal/shell execution."""

    lowered = tool_name.lower()
    # Match real shell/task/command execution tokens. "terminal" covers run_in_terminal /
    # execute/runInTerminal / get_terminal_output; runtask/runcommands are VS Code runners that can
    # spawn shell. A bare "run" substring wrongly matched MCP tools like run_soql_query / run_tests,
    # so it is excluded in favor of these specific tokens.
    return any(
        token in lowered
        for token in ("terminal", "execute", "shell", "runtask", "run_task", "runcommands", "run_commands")
    )


def is_work_record_approval_command(command: str) -> bool:
    """Detect human-only work-record approval, including wrapped and Windows forms."""

    # Fold line continuations, normalize Windows path separators, then drop quotes so
    # `-m 'work_record'` and `python3 -m"work_record"` splices cannot hide the module name.
    normalized = re.sub(r"\\\r?\n", " ", command).replace("\\", "/")
    normalized = normalized.replace("'", "").replace('"', "")
    matches = list(WORK_RECORD_SCRIPT.finditer(normalized)) + list(
        WORK_RECORD_MODULE.finditer(normalized)
    )
    for match in matches:
        # Approval may follow global parser flags, but not a later shell command.
        same_command = re.split(r"[;&|\r\n]", normalized[match.end() :], maxsplit=1)[0]
        if re.search(r"[$`*?\[]", same_command):
            # The resulting subcommand cannot be proven before shell expansion.
            return True
        lexical_command = same_command.replace('"', "").replace("'", "")
        if re.search(
            r"(?:^|\s)approve(?=$|\s|[()])",
            lexical_command,
            re.IGNORECASE,
        ):
            return True
    return False


def target_orgs(parts: list[str]) -> list[str]:
    targets: list[str] = []
    for index, part in enumerate(parts):
        if part in ("--target-org", "-o") and index + 1 < len(parts):
            targets.append(parts[index + 1])
        if part.startswith("--target-org="):
            targets.append(part.split("=", 1)[1])
    return targets


def approved_retrieve_command(parts: list[str], config: dict[str, Any] | None) -> bool:
    """True when the direct CLI command is exactly `sf project retrieve start …` against one
    configured read-allowed non-production alias.

    Retrieve is the only raw Salesforce CLI surface agents may request; it is read-direction
    (org → repository) and still requires per-invocation human confirmation (SAFE-HUMAN-001).
    Deploys, queries, logins, and every other raw subcommand stay denied.
    """

    if [part.lower() for part in parts[1:4]] != ["project", "retrieve", "start"]:
        return False
    targets = target_orgs(parts)
    if len(targets) != 1 or config is None:
        return False
    alias = targets[0]
    if PRODUCTION_PATTERNS[0].search(alias):
        return False
    for org in config.get("salesforce", {}).get("orgs", []):
        if org.get("alias") == alias and org.get("allowAgentRead") is True:
            return True
    return False


def direct_sf_command(command: str) -> list[str] | None:
    # The shell collapses quote/backslash splices (`s''f`, `s""f`, `s\f`) back to `sf` before
    # execution, so a prefilter over the raw string alone misses them. Test a de-spliced copy
    # too; the metacharacter gate below still runs against the original command.
    if not SF_TOKEN.search(command) and not SF_TOKEN.search(dequote(command)):
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


def within_salesforce_source(raw: str, root: Path) -> bool:
    """Restrict MCP filesystem arguments to Salesforce project artifacts at repo root."""

    if not raw or raw.startswith(("http://", "https://")):
        return True
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return relative == "sfdx-project.json" or any(
        relative == prefix or relative.startswith(f"{prefix}/")
        for prefix in ("force-app", "manifest", "tests/e2e")
    )


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
    global _EVENT_TOOL_NAME
    _EVENT_TOOL_NAME = tool_name
    lowered_name = tool_name.lower()
    # Unqualified tool token, so a bare `core_list_orgs` is classified the same as `ado-readonly/core_list_orgs`.
    bare_tool = tool_name.rsplit("/", 1)[-1].lower()
    is_ado = "ado-readonly" in lowered_name or bare_tool.startswith(ADO_TOOL_PREFIXES)
    is_sf_review = "salesforce-readonly" in lowered_name or bare_tool in SALESFORCE_REVIEW_TOOLS
    is_sf_dev = "salesforce-development" in lowered_name or bare_tool in SALESFORCE_DEV_TOOL_TOKENS
    tool_input = event.get("tool_input", {})
    text = flatten(tool_input)
    root = HARNESS_ROOT
    command = terminal_command(tool_input)

    if is_terminal_tool(tool_name) and is_work_record_approval_command(command):
        print(
            json.dumps(
                hook_response(
                    "deny",
                    "SAFE-HUMAN-001: Copilot cannot invoke work-record approval; "
                    "a named human must run it directly outside Copilot.",
                )
            )
        )
        return 0

    if has_recursive_force_rm(text) or any(pattern.search(text) for pattern in DESTRUCTIVE_PATTERNS):
        print(json.dumps(hook_response("deny", "Destructive operation blocked by SAFE-ROLE-001.")))
        return 0

    if any(token in lowered_name for token in SENSITIVE_TOOL_TOKENS):
        if any(pattern.search(text) for pattern in PRODUCTION_PATTERNS):
            print(json.dumps(hook_response("deny", "Production target blocked by SAFE-ENV-001.")))
            return 0

    config = load_config(root)
    if bare_tool in ENUMERATION_TOOLS:
        print(json.dumps(hook_response("deny", "Org/project enumeration is disabled; the harness is bound to one org.")))
        return 0
    if is_ado:
        if config is None:
            print(json.dumps(hook_response("deny", "ADO read blocked: local harness configuration is missing.")))
            return 0
        scope_error = ado_scope_error(config, tool_input)
        if scope_error:
            print(json.dumps(hook_response("deny", f"ADO read blocked: {scope_error}.")))
            return 0
    if is_sf_review:
        scope_error = salesforce_review_tool_error(config, tool_name, tool_input)
        if scope_error:
            print(
                json.dumps(
                    hook_response(
                        "deny",
                        f"Salesforce org review blocked: {scope_error}.",
                    )
                )
            )
            return 0
    for raw_url in extract_urls(text):
        parsed_url = urlparse(raw_url.rstrip(".,);]"))
        hostname = (parsed_url.hostname or "").lower()
        if hostname.endswith(SALESFORCE_HOST_SUFFIXES) and not is_salesforce_sandbox_origin(
            f"{parsed_url.scheme}://{parsed_url.netloc}"
        ):
            print(json.dumps(hook_response("deny", "Non-sandbox Salesforce URL blocked by SAFE-ENV-001.")))
            return 0
    if is_sf_dev:
        if any(token in bare_tool for token in ("run_soql_query", "list_all_orgs")):
            print(
                json.dumps(
                    hook_response(
                        "deny",
                        "Raw Salesforce query/org enumeration is disabled; use the review facade.",
                    )
                )
            )
            return 0
        if config is None or not sandbox_write_approved(config):
            print(json.dumps(hook_response("deny", "Salesforce development blocked: shared-sandbox approval is missing.")))
            return 0
        metadata_root = root
        paths = collect_filesystem_paths(tool_input)
        filesystem_tool = any(token in lowered_name for token in ("deploy_metadata", "retrieve_metadata"))
        if filesystem_tool and not paths:
            print(json.dumps(hook_response("deny", "Salesforce metadata tool must declare a root project source path.")))
            return 0
        outside = [path for path in paths if not within_salesforce_source(path, metadata_root)]
        if outside:
            print(json.dumps(hook_response("deny", "Salesforce development path is outside root force-app/manifest/tests/e2e source.")))
            return 0
        if development_tool_requires_confirmation(lowered_name):
            print(json.dumps(hook_response("ask", "SAFE-HUMAN-001 requires confirmation for this approved non-production mutation.")))
            return 0
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
        if approved_retrieve_command(sf_parts, config):
            print(json.dumps(hook_response("ask", "SAFE-HUMAN-001 requires confirmation before retrieving org metadata into the project via Salesforce CLI.")))
            return 0
        print(json.dumps(hook_response("deny", "Direct Salesforce CLI is disabled except human-approved `sf project retrieve start`; use the guarded read tools.")))
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

    # Fail-closed backstop: an MCP-shaped tool the hook did not positively classify (a new server
    # tool, or a bare name the guards above did not recognize) must not silently auto-run.
    recognized = (
        is_ado
        or is_sf_review
        or is_sf_dev
        or is_terminal_tool(tool_name)
        or bare_tool in BUILTIN_TOOL_NAMES
        or lowered_name in BUILTIN_TOOL_NAMES
    )
    # Only a server-PREFIXED tool from an unknown server is fail-closed. Bare tool names are left
    # to the explicit token guards above (enumeration deny, ADO/SF classification) — matching bare
    # names by shape ("_") wrongly caught VS Code's snake_case built-ins (list_dir, read_file, …).
    mcp_shaped = "/" in tool_name
    if tool_name and not recognized and mcp_shaped:
        print(
            json.dumps(
                hook_response(
                    "ask",
                    f"Unrecognized tool '{tool_name}' is not an allowlisted capability; "
                    "confirm before running (SAFE-TOOL-001 fail-closed).",
                )
            )
        )
        return 0

    print(json.dumps(hook_response()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
