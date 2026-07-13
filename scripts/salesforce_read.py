#!/usr/bin/env python3
"""Guarded, read-only Salesforce access for agents (structured SOQL + metadata retrieve).

Why this exists: the harness bans raw `sf` for agents and channels reads through validated,
allowlisted paths so an agent cannot read arbitrary objects/fields or enumerate orgs. This wrapper
extends that model to record reads and metadata retrieval without exposing a free-form query:

- The model never supplies a SOQL string. It supplies an allowlisted object, a validated field
  list, a bounded row limit, and an optional simple ORDER BY; the query is CONSTRUCTED here.
- The object must be in `salesforce.review.allowedObjectApiNames`; fields are validated; the row
  limit is capped; there is no WHERE/subquery surface (so cross-object reads are impossible).
- The target org must be a configured review org (allowAgentRead + allowAgentReview) and is proved
  to be a live non-production sandbox/scratch org before any read runs (reuses verify_salesforce_org).
- `retrieve` pulls only allowlisted metadata TYPES into an ignored cache directory; it never writes
  to the org and never overwrites tracked force-app source.

This is deliberately NOT a mutation tool: no DML, no deploy, no delete. It is safe to auto-approve.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

try:
    from verify_salesforce_org import configured_identity, verify_is_sandbox
except ModuleNotFoundError:  # imported as scripts.salesforce_read by unit tests
    from scripts.verify_salesforce_org import configured_identity, verify_is_sandbox

HARNESS_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = HARNESS_ROOT / "config" / "harness.local.json"

OBJECT_API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
# Simple field or relationship field (Account.Owner.Name), depth-bounded.
FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){0,4}$")
ORDER_BY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){0,4}(?:\s+(?:ASC|DESC))?$", re.IGNORECASE)
METADATA_NAME = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?$")
API_VERSION = re.compile(r"^\d{2,}\.0$")

# Read-only metadata types safe to retrieve for review. Deliberately excludes types that carry
# secrets or are irrelevant to code/schema review (e.g. NamedCredential, ConnectedApp, Certificate).
ALLOWED_METADATA_TYPES = frozenset(
    {
        "ApexClass",
        "ApexComponent",
        "ApexPage",
        "ApexTrigger",
        "AuraDefinitionBundle",
        "CustomField",
        "CustomMetadata",
        "CustomObject",
        "CustomTab",
        "FlexiPage",
        "Flow",
        "GlobalValueSet",
        "Layout",
        "LightningComponentBundle",
        "PermissionSet",
        "RecordType",
        "StaticResource",
        "ValidationRule",
    }
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_METADATA_COMPONENTS = 25
RETRIEVE_CACHE = ".cache/metadata-retrieve"


class ReadError(Exception):
    """Fail-closed read/validation error."""


def load_review_context(alias: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (org_entry, review_config) for an alias that is a configured review org."""

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise ReadError("config/harness.local.json is missing or invalid") from exc
    salesforce = config.get("salesforce", {})
    review = salesforce.get("review", {})
    if review.get("enabled") is not True:
        raise ReadError("Salesforce review is disabled in local configuration")
    entry = next(
        (
            candidate
            for candidate in salesforce.get("orgs", [])
            if isinstance(candidate, dict) and candidate.get("alias") == alias
        ),
        None,
    )
    if entry is None:
        raise ReadError(f"alias '{alias}' is not present in config/harness.local.json")
    if entry.get("allowAgentRead") is not True or entry.get("allowAgentReview") is not True:
        raise ReadError(f"alias '{alias}' does not grant agent read/review")
    if not API_VERSION.fullmatch(str(review.get("apiVersion", ""))):
        raise ReadError("review.apiVersion is missing or malformed")
    return entry, review


def prove_sandbox(alias: str, runner: Callable[..., Any]) -> None:
    """Reuse the harness sandbox proof; refuse to read otherwise."""

    identity = configured_identity(alias)
    if identity is None:
        raise ReadError("configured sandbox identity is missing or invalid")
    ok, reason = verify_is_sandbox(
        alias,
        expected_host=identity[0],
        expected_org_id=identity[1],
        runner=runner,
    )
    if not ok:
        raise ReadError(f"sandbox proof failed: {reason}")


def validate_object(object_api_name: str, review: dict[str, Any]) -> str:
    if not OBJECT_API_NAME.fullmatch(object_api_name):
        raise ReadError("objectApiName is malformed")
    allowlist = review.get("allowedObjectApiNames", [])
    # "*" opts into all objects; the name is still regex-validated above.
    if "*" not in allowlist and object_api_name not in allowlist:
        raise ReadError("objectApiName is outside the configured review allowlist")
    return object_api_name


def validate_fields(fields: list[str], review: dict[str, Any]) -> list[str]:
    if not fields:
        return ["Id"]
    max_fields = int(review.get("maxFieldsPerObject", 500))
    if len(fields) > max_fields:
        raise ReadError(f"too many fields requested (max {max_fields})")
    for field in fields:
        if not FIELD.fullmatch(field):
            raise ReadError(f"field is malformed: {field!r}")
    return fields


def validate_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1 or limit > MAX_LIMIT:
        raise ReadError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def validate_order_by(order_by: str | None) -> str | None:
    if order_by is None:
        return None
    if not ORDER_BY.fullmatch(order_by.strip()):
        raise ReadError("order-by is malformed (expected field with optional ASC/DESC)")
    return order_by.strip()


def build_query(object_api_name: str, fields: list[str], limit: int, order_by: str | None) -> str:
    clause = f"SELECT {', '.join(fields)} FROM {object_api_name}"
    if order_by:
        clause += f" ORDER BY {order_by}"
    clause += f" LIMIT {limit}"
    return clause


def run_records(args: argparse.Namespace, runner: Callable[..., Any]) -> int:
    entry, review = load_review_context(args.org)
    object_api_name = validate_object(args.object, review)
    fields = validate_fields(
        [item.strip() for item in (args.fields.split(",") if args.fields else []) if item.strip()],
        review,
    )
    limit = validate_limit(args.limit)
    order_by = validate_order_by(args.order_by)
    prove_sandbox(args.org, runner)
    query = build_query(object_api_name, fields, limit, order_by)

    executable = shutil.which("sf")
    if executable is None:
        raise ReadError("Salesforce CLI is unavailable")
    completed = runner(
        [
            executable,
            "data",
            "query",
            "--query",
            query,
            "--target-org",
            args.org,
            "--api-version",
            str(review["apiVersion"]),
            "--json",
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise ReadError("Salesforce read query was rejected or failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReadError("Salesforce returned an unparseable response") from exc
    records = payload.get("result", {}).get("records", [])
    print(json.dumps({"query": query, "recordCount": len(records), "records": records}, indent=2))
    return 0


def validate_metadata_specs(specs: list[str]) -> list[str]:
    if not specs:
        raise ReadError("at least one --metadata Type:Name is required")
    if len(specs) > MAX_METADATA_COMPONENTS:
        raise ReadError(f"too many components requested (max {MAX_METADATA_COMPONENTS})")
    validated: list[str] = []
    for spec in specs:
        if spec.count(":") != 1:
            raise ReadError(f"metadata spec must be Type:Name, got {spec!r}")
        mtype, name = spec.split(":", 1)
        if mtype not in ALLOWED_METADATA_TYPES:
            raise ReadError(f"metadata type is not allowlisted for retrieval: {mtype}")
        if not METADATA_NAME.fullmatch(name):
            raise ReadError(f"metadata name is malformed: {name!r}")
        validated.append(f"{mtype}:{name}")
    return validated


def run_retrieve(args: argparse.Namespace, runner: Callable[..., Any]) -> int:
    entry, review = load_review_context(args.org)
    specs = validate_metadata_specs(args.metadata or [])
    prove_sandbox(args.org, runner)

    executable = shutil.which("sf")
    if executable is None:
        raise ReadError("Salesforce CLI is unavailable")
    target_dir = (HARNESS_ROOT / RETRIEVE_CACHE).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "project",
        "retrieve",
        "start",
        "--target-org",
        args.org,
        "--target-metadata-dir",
        str(target_dir),
        "--api-version",
        str(review["apiVersion"]),
        "--json",
    ]
    for spec in specs:
        command.extend(["--metadata", spec])
    completed = runner(command, text=True, capture_output=True, timeout=180, check=False)
    if completed.returncode != 0:
        raise ReadError("metadata retrieve was rejected or failed")
    print(json.dumps({"retrieved": specs, "outputDir": RETRIEVE_CACHE}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    records = sub.add_parser("records", help="read records from an allowlisted object")
    records.add_argument("--org", required=True)
    records.add_argument("--object", required=True)
    records.add_argument("--fields")
    records.add_argument("--limit", type=int)
    records.add_argument("--order-by", dest="order_by")
    records.set_defaults(func=run_records)

    retrieve = sub.add_parser("retrieve", help="retrieve allowlisted metadata into an ignored cache dir")
    retrieve.add_argument("--org", required=True)
    retrieve.add_argument("--metadata", action="append")
    retrieve.set_defaults(func=run_retrieve)
    return parser


def main(argv: list[str] | None = None, runner: Callable[..., Any] = subprocess.run) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, runner)
    except ReadError as exc:
        print(f"ERROR: Salesforce read blocked: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
