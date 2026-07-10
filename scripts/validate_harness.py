#!/usr/bin/env python3
"""Deterministic structural and contract validation for the Copilot brain-core."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {"agents": 5, "prompts": 7, "skills": 12, "instructions": 3}
BUILT_IN_AGENTS = {"agent", "ask", "plan", "edit"}
ALLOWED_TOOLS = {
    "read",
    "search",
    "edit/editFiles",
    "execute/runInTerminal",
    "web/fetch",
    "vscode/askQuestions",
    "agent",
    "ado-readonly/*",
    "salesforce-readonly/*",
    "salesforce-development/*",
}
LEGACY_TOOLS = {"readFile", "editFiles", "runInTerminal", "fetch", "codebase", "githubRepo"}
REQUIRED_SETTINGS = (
    "github.copilot.chat.codeGeneration.useInstructionFiles",
    "chat.includeApplyingInstructions",
    "chat.includeReferencedInstructions",
    "chat.instructionsFilesLocations",
    "chat.promptFilesLocations",
    "chat.agentFilesLocations",
    "chat.useAgentSkills",
    "chat.agentSkillsLocations",
    "chat.useAgentsMdFile",
    "chat.hookFilesLocations",
    "chat.useCustomAgentHooks",
    "chat.useCustomizationsInParentRepositories",
)
EXPECTED_HUMAN_PLACEHOLDERS = {
    "<TU_WSTAW_INVOICE_UPDATE_SAFE_CONDITION>",
    "<TU_WSTAW_INVOICE_RULE_SOURCE>",
    "<TU_WSTAW_PACKAGE_VERSION>",
    "<TU_WSTAW_RULE_VERIFICATION_DATE>",
    "<TU_WSTAW_PELNA_LISTA_OBIEKTOW_WYSOKIEGO_RYZYKA>",
    "<TU_WSTAW_KONWENCJE_NAZEWNICZE_FIRMY>",
    "<TU_WSTAW_ZASADY_CODE_REVIEW>",
    "<TU_WSTAW_FORMAT_DOKUMENTOWANIA_DECYZJI>",
    "<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>",
}


class Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.checks = 0

    def require(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.require(False, message)


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def frontmatter(path: Path, audit: Audit) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    audit.require(match is not None, f"{relative(path)}: missing YAML frontmatter")
    if match is None:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        audit.require(False, f"{relative(path)}: invalid YAML frontmatter: {exc}")
        return {}, text[match.end() :]
    audit.require(isinstance(data, dict), f"{relative(path)}: frontmatter must be an object")
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def load_json(path: Path, audit: Audit) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        audit.require(False, f"{relative(path)}: invalid JSON: {exc}")
        return {}


def load_jsonc(path: Path, audit: Audit) -> Any:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        audit.require(False, f"{relative(path)}: invalid JSONC: {exc}")
        return {}


def check_required_files(audit: Audit) -> None:
    required = (
        "AGENTS.md",
        "README.md",
        "SETUP.md",
        "IMPLEMENTATION_HANDOFF.md",
        "sf-harness.code-workspace",
        ".github/copilot-instructions.md",
        ".github/hooks/safety.json",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".vscode/settings.json",
        ".vscode/mcp.json",
        "config/harness.example.json",
        "schemas/harness-config.schema.json",
        "requirements-dev.lock",
        "scripts/playwright_guard.py",
        "scripts/verify_salesforce_org.py",
        ".ai/contracts/execution-contract.md",
        ".ai/contracts/tool-capabilities.md",
    )
    for name in required:
        audit.require((ROOT / name).is_file(), f"required file is missing: {name}")
    audit.require(not any((ROOT / ".github/chatmodes").glob("*")), "legacy chat mode files remain")
    audit.require(not (ROOT / "force-app").exists(), "brain-core must not contain force-app")
    audit.require(not (ROOT / "manifest").exists(), "brain-core must not contain manifest")


def check_customizations(audit: Audit) -> None:
    agent_paths = sorted((ROOT / ".github/agents").glob("*.agent.md"))
    prompt_paths = sorted((ROOT / ".github/prompts").glob("*.prompt.md"))
    skill_paths = sorted((ROOT / ".github/skills").glob("*/SKILL.md"))
    instruction_paths = sorted((ROOT / ".github/instructions").glob("*.instructions.md"))
    actual = {
        "agents": len(agent_paths),
        "prompts": len(prompt_paths),
        "skills": len(skill_paths),
        "instructions": len(instruction_paths),
    }
    for kind, expected in EXPECTED_COUNTS.items():
        audit.require(actual[kind] == expected, f"expected {expected} {kind}, found {actual[kind]}")

    agents: dict[str, dict[str, Any]] = {}
    for path in agent_paths:
        data, _ = frontmatter(path, audit)
        name = data.get("name")
        audit.require(name == path.name.removesuffix(".agent.md"), f"{relative(path)}: name must match filename")
        audit.require(data.get("target") == "vscode", f"{relative(path)}: target must be vscode")
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        audit.require(bool(data.get("argument-hint")), f"{relative(path)}: argument-hint is required")
        tools = data.get("tools")
        audit.require(isinstance(tools, list), f"{relative(path)}: tools must be an array")
        if isinstance(tools, list):
            unknown = sorted(set(tools) - ALLOWED_TOOLS)
            legacy = sorted(set(tools) & LEGACY_TOOLS)
            audit.require(not unknown, f"{relative(path)}: unknown tools: {unknown}")
            audit.require(not legacy, f"{relative(path)}: legacy tools: {legacy}")
            if data.get("agents"):
                audit.require("agent" in tools, f"{relative(path)}: agents allowlist requires the agent tool")
        if isinstance(name, str):
            agents[name] = data

    for name, data in agents.items():
        path_label = f".github/agents/{name}.agent.md"
        for child in data.get("agents", []) or []:
            audit.require(child in agents, f"{path_label}: unknown delegated agent {child!r}")
        handoffs = data.get("handoffs", []) or []
        audit.require(isinstance(handoffs, list), f"{path_label}: handoffs must be an array")
        if isinstance(handoffs, list):
            for index, handoff in enumerate(handoffs):
                label = f"{path_label}: handoff {index + 1}"
                audit.require(isinstance(handoff, dict), f"{label} must be an object")
                if not isinstance(handoff, dict):
                    continue
                audit.require(bool(handoff.get("label")), f"{label} needs label")
                audit.require(bool(handoff.get("prompt")), f"{label} needs prompt")
                target = handoff.get("agent")
                audit.require(target in agents or target in BUILT_IN_AGENTS, f"{label} has unknown agent {target!r}")
                audit.require(handoff.get("send") is False, f"{label} must remain human-triggered with send: false")

    guardrail_tools = set(agents.get("guardrail-reviewer", {}).get("tools", []))
    audit.require("edit/editFiles" not in guardrail_tools, "guardrail-reviewer must not edit")
    audit.require("execute/runInTerminal" not in guardrail_tools, "guardrail-reviewer must not execute")
    audit.require("salesforce-development/*" not in guardrail_tools, "guardrail-reviewer must not mutate Salesforce")

    prompt_names: list[str] = []
    for path in prompt_paths:
        data, body = frontmatter(path, audit)
        name = data.get("name")
        audit.require(name == path.name.removesuffix(".prompt.md"), f"{relative(path)}: name must match filename")
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        audit.require(bool(data.get("argument-hint")), f"{relative(path)}: argument-hint is required")
        prompt_agent = data.get("agent")
        audit.require(prompt_agent in agents or prompt_agent in BUILT_IN_AGENTS, f"{relative(path)}: unknown agent {prompt_agent!r}")
        tools = data.get("tools")
        if tools is not None:
            audit.require(isinstance(tools, list), f"{relative(path)}: tools must be an array")
            if isinstance(tools, list):
                audit.require(not (set(tools) - ALLOWED_TOOLS), f"{relative(path)}: unknown tools {sorted(set(tools) - ALLOWED_TOOLS)}")
        audit.require("skill](" in body.lower(), f"{relative(path)}: prompt must link its skill")
        if isinstance(name, str):
            prompt_names.append(name)

    public_skill_names: list[str] = []
    for path in skill_paths:
        data, body = frontmatter(path, audit)
        folder = path.parent.name
        audit.require(data.get("name") == folder, f"{relative(path)}: name must match skill folder")
        description = data.get("description")
        audit.require(isinstance(description, str) and 1 <= len(description) <= 1024, f"{relative(path)}: description must be 1..1024 characters")
        audit.require(data.get("user-invocable") is False, f"{relative(path)}: internal skill must set user-invocable: false")
        audit.require("shared execution contract" in body.lower(), f"{relative(path)}: shared execution contract is required")
        if data.get("user-invocable") is not False and isinstance(data.get("name"), str):
            public_skill_names.append(data["name"])

    public_commands = prompt_names + public_skill_names
    audit.require(len(public_commands) == 7, f"expected 7 public slash commands, found {len(public_commands)}")
    audit.require(len(public_commands) == len(set(public_commands)), "public slash-command names collide")

    for path in instruction_paths:
        data, _ = frontmatter(path, audit)
        audit.require(bool(data.get("description")), f"{relative(path)}: description is required")
        audit.require(bool(data.get("applyTo")), f"{relative(path)}: applyTo is required")


def check_links(audit: Audit) -> None:
    paths = [ROOT / ".github/copilot-instructions.md", ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "SETUP.md"]
    paths.extend((ROOT / ".github").glob("**/*.md"))
    paths.extend((ROOT / ".ai/contracts").glob("*.md"))
    paths.extend((ROOT / ".ai/templates").glob("*.md"))
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw in pattern.findall(text):
            target = raw.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (path.parent / target).resolve()
            audit.require(resolved.exists(), f"{relative(path)}: broken relative link {raw!r}")


def check_settings_and_mcp(audit: Audit) -> None:
    settings = load_jsonc(ROOT / ".vscode/settings.json", audit)
    workspace = load_json(ROOT / "sf-harness.code-workspace", audit)
    workspace_settings = workspace.get("settings", {}) if isinstance(workspace, dict) else {}
    for key in REQUIRED_SETTINGS:
        audit.require(key in settings, f".vscode/settings.json: missing {key}")
        audit.require(key in workspace_settings, f"sf-harness.code-workspace: missing {key}")
        if key in settings and key in workspace_settings:
            audit.require(settings[key] == workspace_settings[key], f"workspace setting differs from folder setting: {key}")
    audit.require(settings.get("chat.useCustomizationsInParentRepositories") is False, "parent repository customizations must be disabled")
    folders = {(item.get("name"), item.get("path")) for item in workspace.get("folders", [])}
    audit.require(("brain-core", ".") in folders, "workspace must name the brain-core root")
    audit.require(("salesforce", "../salesforce-metadata") in folders, "workspace must name the Salesforce metadata root")

    mcp = load_json(ROOT / ".vscode/mcp.json", audit)
    servers = mcp.get("servers", {}) if isinstance(mcp, dict) else {}
    audit.require(set(servers) == {"ado-readonly", "salesforce-readonly", "salesforce-development"}, "MCP server set is unexpected")
    ado = servers.get("ado-readonly", {})
    audit.require(ado.get("headers", {}).get("X-MCP-Readonly") == "true", "ADO MCP must be read-only")
    audit.require(ado.get("headers", {}).get("X-MCP-Toolsets") == "wit,wiki,testplan", "ADO MCP toolsets must be bounded")
    audit.require("${env:ADO_ORGANIZATION}" in ado.get("url", ""), "ADO MCP organization must come from the preflight-checked environment")
    audit.require(not any(item.get("id") == "ado_org" for item in mcp.get("inputs", [])), "independent ADO organization prompt is forbidden")
    for name in ("salesforce-readonly", "salesforce-development"):
        server = servers.get(name, {})
        audit.require(server.get("command") == "node", f"{name}: wrapper must run with node")
        audit.require("scripts/start_salesforce_mcp.mjs" in server.get("args", []), f"{name}: guarded wrapper is required")
        audit.require(server.get("sandboxEnabled") is True, f"{name}: sandboxEnabled must be true")
    serialized = json.dumps(mcp).lower()
    for forbidden in ("@latest", "allow_all_orgs", "default_target_org", "login.salesforce.com"):
        audit.require(forbidden not in serialized, f"MCP config contains forbidden token {forbidden!r}")
    allow_write = mcp.get("sandbox", {}).get("filesystem", {}).get("allowWrite", [])
    audit.require(allow_write == ["${workspaceFolder:salesforce}"], "MCP write sandbox must contain only the named Salesforce root")
    domains = set(mcp.get("sandbox", {}).get("network", {}).get("allowedDomains", []))
    audit.require("*.salesforce.com" not in domains and "*.force.com" not in domains, "broad production-capable Salesforce domains are forbidden")
    audit.require("*.sandbox.my.salesforce.com" in domains, "sandbox Salesforce API domain is required")

    hooks = load_json(ROOT / ".github/hooks/safety.json", audit)
    pre = hooks.get("hooks", {}).get("PreToolUse", []) if isinstance(hooks, dict) else []
    audit.require(len(pre) == 1, "exactly one global PreToolUse hook is required")
    if pre:
        audit.require(pre[0].get("command") == "python3 scripts/copilot_safety_hook.py", "global safety hook command differs")
        audit.require("timeout" in pre[0] and "timeoutSec" not in pre[0], "hook must use the current timeout property")
        audit.require(pre[0].get("timeout", 0) >= 10, "global hook timeout must accommodate guarded command parsing")

    launcher = (ROOT / "scripts/start_salesforce_mcp.mjs").read_text(encoding="utf-8")
    for marker in (
        "verify_salesforce_org.py",
        'environment !== "development"',
        "METADATA_ROOT",
        "development mode is disabled on Windows",
        "Organization.IsSandbox",
    ):
        audit.require(marker in launcher, f"Salesforce MCP launcher is missing runtime gate: {marker}")
    audit.require('"data,metadata,testing,code-analysis"' not in launcher, "broad Salesforce data-write toolset is forbidden")

    development = (ROOT / ".github/agents/development-assistant.agent.md").read_text(encoding="utf-8")
    development_frontmatter = yaml.safe_load(development.split("---", 2)[1])
    audit.require("execute/runInTerminal" in development_frontmatter.get("tools", []), "Development Assistant needs guarded preflight execution")
    audit.require("development-assistant" in json.dumps(development_frontmatter.get("hooks", {})), "Development Assistant role guard is required")
    doc_prompt, _ = frontmatter(ROOT / ".github/prompts/document-metadata-change.prompt.md", audit)
    audit.require("salesforce-development/*" not in doc_prompt.get("tools", []), "Documentation prompt must not inherit Salesforce write tools")
    audit.require("execute/runInTerminal" in doc_prompt.get("tools", []), "Documentation prompt needs guarded metadata/ADO preflight execution")
    release_prompt, _ = frontmatter(ROOT / ".github/prompts/release-handover.prompt.md", audit)
    audit.require("execute/runInTerminal" in release_prompt.get("tools", []), "Release prompt needs guarded release/ADO preflight execution")
    role_guard = (ROOT / "scripts/copilot_role_guard.py").read_text(encoding="utf-8")
    audit.require(role_guard.count('".cache/ado-items/"') >= 3, "ADO cache must be writable by its three consuming roles")
    audit.require('".cache/test-cases/"' in role_guard, "Test Strategist must be able to write Test Case cache")
    development_capabilities = re.search(
        r'"development-assistant":\s*\{(.*?)\}', role_guard, re.DOTALL
    )
    audit.require(
        development_capabilities is not None
        and all(
            f'"{capability}"' in development_capabilities.group(1)
            for capability in ("ado", "metadata")
        ),
        "Development Assistant must allow both documentation preflight capabilities",
    )

    compatibility = (ROOT / "docs/compatibility.md").read_text(encoding="utf-8")
    audit.require("1.112" in compatibility, "compatibility baseline must include VS Code 1.112 MCP sandbox support")
    audit.require("Windows is read-only" in compatibility, "Windows external-write limitation must be explicit")
    agents_contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    audit.require("Built-in/default Agent mode" in agents_contract, "supported custom-agent boundary must be explicit")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    audit.require("dedicated OS account, VM, or container" in security, "production credential isolation is required")


def check_ci(audit: Audit) -> None:
    path = ROOT / ".github/workflows/harness-ci.yml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        audit.require(False, f"{relative(path)}: invalid workflow YAML: {exc}")
        return
    audit.require(data.get("permissions", {}).get("contents") == "read", "CI permissions must be contents: read")
    serialized = path.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", serialized, flags=re.MULTILINE)
    audit.require(bool(uses), "CI must use explicit actions")
    for value in uses:
        revision = value.rsplit("@", 1)[-1]
        audit.require(bool(re.fullmatch(r"[0-9a-f]{40}", revision)), f"CI action is not SHA-pinned: {value}")
    audit.require("ubuntu-latest" in serialized and "windows-latest" in serialized, "CI must cover Linux and Windows")
    audit.require("requirements-dev.lock" in serialized, "CI must install the resolved dependency lock")


def check_secret_signatures(audit: Audit) -> None:
    patterns = (
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
        re.compile(r"\bforce://[^\s]+@[^\s]+"),
    )
    completed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    audit.require(completed.returncode == 0, "could not enumerate repository files for secret scan")
    for name in completed.stdout.splitlines():
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            audit.require(pattern.search(text) is None, f"{name}: high-confidence secret signature detected")


def check_schemas_and_evals(audit: Audit) -> None:
    mappings = {
        "ado-item-cache.schema.json": ("ado-item.complete.json", "ado-item.partial.json"),
        "test-case-cache.schema.json": ("test-cases.complete.json", "test-cases.partial.json"),
        "output-envelope.schema.json": ("output.incomplete.json",),
    }
    for schema_name, fixture_names in mappings.items():
        schema_path = ROOT / "schemas" / schema_name
        schema = load_json(schema_path, audit)
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # jsonschema exposes several schema-error subclasses
            audit.require(False, f"{relative(schema_path)}: invalid JSON Schema: {exc}")
            continue
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for fixture_name in fixture_names:
            fixture_path = ROOT / "evals/fixtures" / fixture_name
            fixture = load_json(fixture_path, audit)
            errors = sorted(validator.iter_errors(fixture), key=lambda item: list(item.path))
            audit.require(not errors, f"{relative(fixture_path)}: schema failure: {errors[0].message if errors else ''}")

    negative_path = ROOT / "evals/fixtures/invalid-contract-states.json"
    negative = load_json(negative_path, audit)
    for case in negative.get("cases", []):
        schema = load_json(ROOT / "schemas" / case["schema"], audit)
        instance = deepcopy(
            load_json(ROOT / "evals/fixtures" / case["baseFixture"], audit)
        )
        for dotted, value in case.get("patch", {}).items():
            target = instance
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        errors = list(Draft202012Validator(schema).iter_errors(instance))
        audit.require(bool(errors), f"negative contract fixture was incorrectly accepted: {case.get('id')}")

    for filename, minimum in (("safety-scenarios.yaml", 10), ("agent-scenarios.yaml", 10)):
        path = ROOT / "evals" / filename
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            audit.require(False, f"{relative(path)}: invalid evaluation YAML: {exc}")
            continue
        audit.require(data.get("schemaVersion") == 1, f"{relative(path)}: schemaVersion must be 1")
        scenarios = data.get("scenarios", [])
        audit.require(isinstance(scenarios, list) and len(scenarios) >= minimum, f"{relative(path)}: expected at least {minimum} scenarios")
        ids = [scenario.get("id") for scenario in scenarios if isinstance(scenario, dict)]
        audit.require(len(ids) == len(set(ids)), f"{relative(path)}: scenario IDs must be unique")


def check_placeholders(audit: Audit) -> None:
    found: set[str] = set()
    for base in (ROOT / ".github", ROOT / ".ai/contracts"):
        for path in base.glob("**/*"):
            if path.is_file():
                found.update(re.findall(r"<TU_WSTAW_[^>]+>", path.read_text(encoding="utf-8")))
    audit.require(found == EXPECTED_HUMAN_PLACEHOLDERS, f"human placeholder register drifted: found {sorted(found)}")


def main() -> int:
    audit = Audit()
    check_required_files(audit)
    check_customizations(audit)
    check_links(audit)
    check_settings_and_mcp(audit)
    check_ci(audit)
    check_schemas_and_evals(audit)
    check_placeholders(audit)
    check_secret_signatures(audit)
    if audit.errors:
        print(f"FAIL: harness validation ({len(audit.errors)} errors, {audit.checks} checks)")
        for message in audit.errors:
            print(f"- {message}")
        return 1
    print(f"PASS: harness validation ({audit.checks} checks)")
    print("Inventory: 5 agents, 7 prompts, 12 internal skills, 3 scoped instruction files")
    print("Contracts: workspace, MCP, hooks, schemas, fixtures, and governance are coherent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
