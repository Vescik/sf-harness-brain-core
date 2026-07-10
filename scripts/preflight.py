#!/usr/bin/env python3
"""Fail-closed local preflight for configuration and external workflow dependencies."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

try:
    from copilot_safety_hook import is_salesforce_sandbox_origin
    from verify_salesforce_org import verify_is_sandbox
except ModuleNotFoundError:  # imported as scripts.preflight by unit tests
    from scripts.copilot_safety_hook import is_salesforce_sandbox_origin
    from scripts.verify_salesforce_org import verify_is_sandbox


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "harness.local.json"
SCHEMA_PATH = ROOT / "schemas" / "harness-config.schema.json"
PLACEHOLDER = re.compile(r"<[^>]+>")
PLAYWRIGHT_CLI_VERSION = "0.1.17"


def playwright_version_matches(stdout: str) -> bool:
    match = re.search(r"(?<![0-9.])(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?![0-9.])", stdout)
    return match is not None and match.group(1) == PLAYWRIGHT_CLI_VERSION


def error(message: str) -> None:
    print(f"ERROR: {message}")


def load_config() -> dict:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(
            "config/harness.local.json is missing; copy config/harness.example.json and fill it"
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"config/harness.local.json is invalid JSON: {exc}")
    if PLACEHOLDER.search(json.dumps(config)):
        raise ValueError("config/harness.local.json still contains <PLACEHOLDER> values")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(config),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise ValueError(f"config schema validation failed at {location}: {first.message}")
    return config


def validate_origins(values: list[str], label: str) -> list[str]:
    failures: list[str] = []
    for value in values:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            failures.append(f"{label} origin must be HTTPS: {value}")
        if re.search(r"(^|[^a-z])(prod|production)([^a-z]|$)", value, re.IGNORECASE):
            failures.append(f"{label} production-like origin is forbidden: {value}")
        if value.rstrip("/") == "https://login.salesforce.com":
            failures.append("Salesforce production login origin is forbidden")
        if label == "Browser" and not is_salesforce_sandbox_origin(value):
            failures.append(f"Browser origin must be an explicit Salesforce sandbox host: {value}")
        if label == "ADO":
            parts = [part for part in parsed.path.split("/") if part]
            if parsed.hostname != "dev.azure.com" or len(parts) != 1:
                failures.append(
                    f"ADO origin must be exactly https://dev.azure.com/<organization>: {value}"
                )
    return failures


def validate_config(config: dict) -> list[str]:
    failures: list[str] = []
    aliases: set[str] = set()
    for org in config.get("salesforce", {}).get("orgs", []):
        alias = str(org.get("alias", ""))
        environment = str(org.get("environment", "")).lower()
        if not alias or alias in aliases:
            failures.append(f"Salesforce alias is missing or duplicated: {alias!r}")
        aliases.add(alias)
        if environment not in {"development", "qa", "uat"}:
            failures.append(f"Salesforce environment is not non-production: {environment!r}")
        if re.search(r"(^|[^a-z])(prod|production)([^a-z]|$)", alias, re.IGNORECASE):
            failures.append(f"Production-like Salesforce alias is forbidden: {alias}")
        if org.get("allowAgentWrite") and environment != "development":
            failures.append(f"Only development aliases may allow agent writes: {alias}")
    write_aliases = [
        str(org.get("alias", ""))
        for org in config.get("salesforce", {}).get("orgs", [])
        if org.get("allowAgentWrite") is True
    ]
    safety = config.get("safety", {})
    if write_aliases and safety.get("sharedSandboxWritesApproved") is not True:
        failures.append("Salesforce writes require approved shared-sandbox coordination")
    if safety.get("sharedSandboxWritesApproved") is True and not str(
        safety.get("sharedSandboxApprovalRef", "")
    ).strip():
        failures.append("shared-sandbox write approval requires a non-empty approval reference")
    failures.extend(
        validate_origins(config.get("browser", {}).get("allowedOrigins", []), "Browser")
    )
    failures.extend(
        validate_origins(config.get("ado", {}).get("allowedHttpsOrigins", []), "ADO")
    )
    expected_ado_origin = (
        f"https://dev.azure.com/{config.get('ado', {}).get('organization', '')}"
    )
    if config.get("ado", {}).get("allowedHttpsOrigins") != [expected_ado_origin]:
        failures.append(
            "ado.allowedHttpsOrigins must contain only the configured organization origin"
        )
    if config.get("workspace", {}).get("salesforceRootName") != "salesforce":
        failures.append("workspace.salesforceRootName must be 'salesforce'")
    return failures


def metadata_root() -> Path:
    return ROOT.parent / "salesforce-metadata"


def contained_workspace_path(root: Path, raw: str, label: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative to the named Salesforce root")
    candidate = (root / path).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes the named Salesforce root") from exc
    return candidate


def validate_metadata(config: dict) -> list[str]:
    failures: list[str] = []
    root = metadata_root()
    if not (root / "sfdx-project.json").is_file():
        failures.append(f"named Salesforce root is missing sfdx-project.json: {root}")
    try:
        manifest = contained_workspace_path(
            root, config["workspace"]["manifestPath"], "workspace.manifestPath"
        )
        contained_workspace_path(
            root,
            config["workspace"]["promotedTestsPath"],
            "workspace.promotedTestsPath",
        )
    except ValueError as exc:
        failures.append(str(exc))
        return failures
    if not manifest.is_file():
        failures.append(f"configured manifest does not exist: {manifest}")
    if not (root / "force-app").is_dir():
        failures.append(f"force-app does not exist: {root / 'force-app'}")
    if (ROOT / "force-app").exists() or (ROOT / "manifest").exists():
        failures.append("unsupported combined topology: metadata exists inside brain-core")
    return failures


def validate_capability(config: dict, capability: str) -> list[str]:
    failures: list[str] = []
    if capability in {"metadata", "salesforce-write", "playwright"}:
        failures.extend(validate_metadata(config))
    if capability in {"ado", "release"}:
        configured_org = str(config.get("ado", {}).get("organization", ""))
        runtime_org = os.environ.get("ADO_ORGANIZATION", "")
        if runtime_org != configured_org:
            failures.append(
                "ADO_ORGANIZATION must exactly match ado.organization in local configuration"
            )
    if capability in {"salesforce-read", "salesforce-write"}:
        for command in ("node", "npx", "sf"):
            if shutil.which(command) is None:
                failures.append(f"required command is not installed: {command}")
        key = "allowAgentWrite" if capability == "salesforce-write" else "allowAgentRead"
        if shutil.which("sf") is not None:
            for org in config.get("salesforce", {}).get("orgs", []):
                if org.get(key) is True:
                    ok, reason = verify_is_sandbox(str(org.get("alias", "")))
                    if not ok:
                        failures.append(
                            f"Salesforce alias {org.get('alias')!r} failed live sandbox proof: {reason}"
                        )
    if capability == "salesforce-write" and not any(
        org.get("allowAgentWrite") is True for org in config["salesforce"]["orgs"]
    ):
        failures.append("no non-production Salesforce alias allows agent writes")
    if capability == "playwright":
        if shutil.which("playwright-cli") is None:
            failures.append("playwright-cli is not installed")
        else:
            try:
                version = subprocess.run(
                    ["playwright-cli", "--version"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if version.returncode != 0 or not playwright_version_matches(version.stdout):
                    failures.append(
                        f"playwright-cli must be pinned to {PLAYWRIGHT_CLI_VERSION}"
                    )
            except (OSError, subprocess.SubprocessError):
                failures.append("playwright-cli version check failed")
        profile = Path(config["browser"]["profileDirectory"]).expanduser()
        if not profile.is_absolute() or not profile.is_dir():
            failures.append(f"browser profile directory is missing or not absolute: {profile}")
    if capability == "release":
        query_id = str(config.get("ado", {}).get("releaseQueryId", ""))
        if not query_id:
            failures.append("ADO saved release Query ID is missing")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capability",
        default="base",
        choices=(
            "base",
            "ado",
            "metadata",
            "salesforce-read",
            "salesforce-write",
            "playwright",
            "release",
        ),
    )
    args = parser.parse_args()
    try:
        config = load_config()
    except ValueError as exc:
        error(str(exc))
        return 2
    failures = validate_config(config)
    failures.extend(validate_capability(config, args.capability))
    if failures:
        for failure in failures:
            error(failure)
        return 2
    print(f"PASS: harness preflight ({args.capability})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
