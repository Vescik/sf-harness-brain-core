#!/usr/bin/env python3
"""Prove that an authorized alias resolves to a non-production Salesforce org.

Two proof lanes exist. A configured org entry with identity pins keeps the strict
lane: live host and organization ID must match the pinned values. When
`salesforce.review.allowAnyNonProduction` is true (owner decision 2026-07-31),
an alias without a usable entry takes the dynamic lane: the live identity must
carry a canonical non-production hostname (sandbox, scratch, or Developer
Edition) and an Organization row consistent with that hostname. Production is
always refused: by alias pattern, by an entry marked `environment: production`,
and by the host/IsSandbox signature check in both lanes.
"""

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
SCRATCH_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com$",
    re.IGNORECASE,
)
DEV_EDITION_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com$",
    re.IGNORECASE,
)
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "harness.local.json"


def is_allowed_non_production_host(host: str) -> bool:
    """Accept a canonical Salesforce sandbox, scratch-org, or Developer Edition hostname."""

    return bool(
        SANDBOX_HOST.fullmatch(host)
        or SCRATCH_HOST.fullmatch(host)
        or DEV_EDITION_HOST.fullmatch(host)
    )


def expected_is_sandbox(host: str) -> bool:
    """Organization.IsSandbox is true for sandboxes and scratch orgs, false for Dev Edition."""

    return not DEV_EDITION_HOST.fullmatch(host)


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
        and is_allowed_non_production_host(parsed.hostname or "")
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
    pinned = expected_host is not None or expected_org_id is not None
    normalized_expected_host = str(expected_host or "").lower()
    normalized_expected_org_id = str(expected_org_id or "")
    if pinned:
        if not is_allowed_non_production_host(normalized_expected_host):
            return False, "configured non-production host is missing or invalid"
        if not ORG_ID.fullmatch(normalized_expected_org_id):
            return False, "configured organization ID is missing or invalid"
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
            return False, "locally authorized instance URL is not a recognized non-production host"
        host, local_org_id = identity
        if pinned:
            if host != normalized_expected_host:
                return False, "locally authorized non-production host does not match local policy"
            if local_org_id != normalized_expected_org_id:
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
        return False, "org identity query failed"
    if completed.returncode != 0:
        return False, "org identity query was rejected or failed"
    query_identity = parse_org_query(completed.stdout) if len(completed.stdout) <= 1_000_000 else None
    if query_identity is None:
        return False, "Organization identity row was missing or malformed"
    if query_identity[0] is not expected_is_sandbox(host):
        return False, "Organization.IsSandbox does not match the non-production host signature"
    if pinned:
        if query_identity[1] != normalized_expected_org_id:
            return False, "live Organization identity does not match local policy"
    elif query_identity[1] and query_identity[1] != local_org_id:
        return False, "live Organization identity does not match the authorized alias"
    return True, f"non-production identity proven for host '{host}'"


def load_config() -> dict[str, Any] | None:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return config if isinstance(config, dict) else None


def org_entry(alias: str) -> dict[str, Any] | None:
    config = load_config()
    if config is None:
        return None
    entry = next(
        (
            candidate
            for candidate in config.get("salesforce", {}).get("orgs", [])
            if isinstance(candidate, dict) and candidate.get("alias") == alias
        ),
        None,
    )
    return entry


def allow_any_non_production() -> bool:
    config = load_config()
    if config is None:
        return False
    return (
        config.get("salesforce", {}).get("review", {}).get("allowAnyNonProduction")
        is True
    )


def configured_identity(alias: str) -> tuple[str, str] | None:
    entry = org_entry(alias)
    if not isinstance(entry, dict):
        return None
    host = str(entry.get("expectedInstanceHost", "")).lower()
    org_id = str(entry.get("expectedOrganizationId", ""))
    if not is_allowed_non_production_host(host) or not ORG_ID.fullmatch(org_id):
        return None
    return host, org_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True)
    args = parser.parse_args()
    entry = org_entry(args.org)
    if isinstance(entry, dict) and str(entry.get("environment", "")).lower() == "production":
        print("ERROR: Salesforce org proof failed: alias is marked production in local policy")
        return 2
    identity = configured_identity(args.org)
    if identity is not None:
        ok, reason = verify_is_sandbox(
            args.org,
            expected_host=identity[0],
            expected_org_id=identity[1],
        )
    elif allow_any_non_production():
        ok, reason = verify_is_sandbox(args.org)
    else:
        print(
            "ERROR: Salesforce org proof failed: configured identity is missing or invalid "
            "(set salesforce.review.allowAnyNonProduction to permit any proven non-production org)"
        )
        return 2
    if not ok:
        print(f"ERROR: Salesforce org proof failed: {reason}")
        return 2
    print(f"PASS: Salesforce alias '{args.org}' proved a non-production identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
