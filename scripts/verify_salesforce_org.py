#!/usr/bin/env python3
"""Prove through Salesforce itself that an authorized alias resolves to a sandbox org."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Any, Callable
from pathlib import Path
from urllib.parse import urlparse


QUERY = "SELECT Id, IsSandbox FROM Organization LIMIT 1"
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ORG_ID = re.compile(r"^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$")
SANDBOX_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com$",
    re.IGNORECASE,
)
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "harness.local.json"


def parse_sandbox_instance(payload: str) -> bool:
    return parse_org_display(payload) is not None


def parse_org_display(payload: str) -> tuple[str, str] | None:
    try:
        data = json.loads(payload)
        instance_url = str(data["result"]["instanceUrl"])
        org_id = str(data["result"].get("id") or data["result"].get("orgId") or "")
        parsed = urlparse(instance_url)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    valid = (
        data.get("status") == 0
        and parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and bool(SANDBOX_HOST.fullmatch(parsed.hostname or ""))
        and bool(ORG_ID.fullmatch(org_id))
    )
    return ((parsed.hostname or "").lower(), org_id) if valid else None


def parse_org_query(payload: str) -> tuple[bool, str] | None:
    try:
        data = json.loads(payload)
        records = data["result"]["records"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    valid = (
        data.get("status") == 0
        and isinstance(records, list)
        and len(records) == 1
        and isinstance(records[0].get("IsSandbox"), bool)
    )
    if not valid:
        return None
    org_id = str(records[0].get("Id") or "")
    if org_id and not ORG_ID.fullmatch(org_id):
        return None
    return records[0]["IsSandbox"], org_id


def parse_is_sandbox(payload: str) -> bool:
    parsed = parse_org_query(payload)
    return parsed is not None and parsed[0] is True


def verify_is_sandbox(
    alias: str,
    *,
    expected_host: str | None = None,
    expected_org_id: str | None = None,
    timeout: int = 25,
    runner: Callable[..., Any] = subprocess.run,
) -> tuple[bool, str]:
    if not ALIAS.fullmatch(alias) or re.search(
        r"(^|[^a-z])(prod|production)([^a-z]|$)", alias, re.IGNORECASE
    ):
        return False, "alias is invalid or production-like"
    executable = shutil.which("sf")
    if executable is None:
        return False, "Salesforce CLI is unavailable"
    try:
        local = runner(
            [
                executable,
                "org",
                "display",
                "--target-org",
                alias,
                "--json",
            ],
            text=True,
            capture_output=True,
            timeout=min(timeout, 10),
            check=False,
        )
        identity = parse_org_display(local.stdout) if len(local.stdout) <= 1_000_000 else None
        if local.returncode != 0 or identity is None:
            return False, "locally authorized instance URL is not a recognized sandbox host"
        host, local_org_id = identity
        if expected_host is not None and host != expected_host.lower():
            return False, "locally authorized sandbox host does not match local policy"
        if expected_org_id is not None and local_org_id != expected_org_id:
            return False, "locally authorized organization does not match local policy"
        completed = runner(
            [
                executable,
                "data",
                "query",
                "--query",
                QUERY,
                "--target-org",
                alias,
                "--json",
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "sandbox identity query failed"
    if completed.returncode != 0:
        return False, "sandbox identity query was rejected or failed"
    query_identity = parse_org_query(completed.stdout) if len(completed.stdout) <= 1_000_000 else None
    if query_identity is None or query_identity[0] is not True:
        return False, "Organization.IsSandbox was false, missing, or malformed"
    if expected_org_id is not None and query_identity[1] != expected_org_id:
        return False, "live Organization identity does not match local policy"
    return True, "Organization.IsSandbox=true"


def configured_identity(alias: str) -> tuple[str, str] | None:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    entry = next(
        (
            candidate
            for candidate in config.get("salesforce", {}).get("orgs", [])
            if candidate.get("alias") == alias
        ),
        None,
    )
    if not isinstance(entry, dict):
        return None
    host = str(entry.get("expectedInstanceHost", "")).lower()
    org_id = str(entry.get("expectedOrganizationId", ""))
    if not SANDBOX_HOST.fullmatch(host) or not ORG_ID.fullmatch(org_id):
        return None
    return host, org_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True)
    args = parser.parse_args()
    identity = configured_identity(args.org)
    if identity is None:
        print("ERROR: Salesforce sandbox proof failed: configured identity is missing or invalid")
        return 2
    ok, reason = verify_is_sandbox(
        args.org,
        expected_host=identity[0],
        expected_org_id=identity[1],
    )
    if not ok:
        print(f"ERROR: Salesforce sandbox proof failed: {reason}")
        return 2
    print(f"PASS: Salesforce alias '{args.org}' proved Organization.IsSandbox=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
