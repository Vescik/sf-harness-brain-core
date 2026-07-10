#!/usr/bin/env python3
"""Prove through Salesforce itself that an authorized alias resolves to a sandbox org."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse


QUERY = "SELECT IsSandbox FROM Organization LIMIT 1"
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SANDBOX_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com$",
    re.IGNORECASE,
)


def parse_sandbox_instance(payload: str) -> bool:
    try:
        data = json.loads(payload)
        instance_url = str(data["result"]["instanceUrl"])
        parsed = urlparse(instance_url)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False
    return (
        data.get("status") == 0
        and parsed.scheme == "https"
        and bool(SANDBOX_HOST.fullmatch(parsed.hostname or ""))
    )


def parse_is_sandbox(payload: str) -> bool:
    try:
        data = json.loads(payload)
        records = data["result"]["records"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False
    return (
        data.get("status") == 0
        and isinstance(records, list)
        and len(records) == 1
        and records[0].get("IsSandbox") is True
    )


def verify_is_sandbox(
    alias: str,
    *,
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
        if (
            local.returncode != 0
            or len(local.stdout) > 1_000_000
            or not parse_sandbox_instance(local.stdout)
        ):
            return False, "locally authorized instance URL is not a recognized sandbox host"
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
    if len(completed.stdout) > 1_000_000 or not parse_is_sandbox(completed.stdout):
        return False, "Organization.IsSandbox was false, missing, or malformed"
    return True, "Organization.IsSandbox=true"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True)
    args = parser.parse_args()
    ok, reason = verify_is_sandbox(args.org)
    if not ok:
        print(f"ERROR: Salesforce sandbox proof failed: {reason}")
        return 2
    print(f"PASS: Salesforce alias '{args.org}' proved Organization.IsSandbox=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
