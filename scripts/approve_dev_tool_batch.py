#!/usr/bin/env python3
"""Human-terminal-only approval of a Salesforce dev-tool batch plan.

An agent writes a schema-valid plan under `.cache/devtool-batches/`; a NAMED HUMAN reviews it and
runs this script directly outside Copilot (the safety hook denies every Copilot invocation, like
`work_record.py approve`). Approval produces a hash-pinned receipt under `.cache/receipts/`; the
safety hook then allows only calls that byte-match an unused plan entry (single-use, TTL-bounded)
instead of asking per invocation. Production targets, org writes, and destructive operations are
unaffected — the hook's own denies run before any receipt is consulted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.approve_dev_tool_batch by unit tests
    from scripts.schema_format import FORMAT_CHECKER

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / ".cache" / "devtool-batches"
RECEIPTS_DIR = ROOT / ".cache" / "receipts"
CONFIG_PATH = ROOT / "config" / "harness.local.json"
TTL_MINUTES = 60


class ApprovalError(RuntimeError):
    pass


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_plan(raw_path: str) -> tuple[Path, dict]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    try:
        path.relative_to(PLAN_DIR.resolve())
    except ValueError as exc:
        raise ApprovalError(f"plan must live under {PLAN_DIR.relative_to(ROOT)}") from exc
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"cannot read plan: {exc}") from exc
    schema = json.loads((ROOT / "schemas/dev-tool-batch.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(plan), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "<root>"
        raise ApprovalError(f"plan schema failure at {location}: {errors[0].message}")
    return path, plan


def validate_org(plan: dict) -> None:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalError("config/harness.local.json is missing or invalid") from exc
    if config.get("safety", {}).get("batchDevToolApproval") is not True:
        raise ApprovalError("safety.batchDevToolApproval is disabled in local configuration")
    alias = plan["orgAlias"]
    entry = next(
        (
            candidate
            for candidate in config.get("salesforce", {}).get("orgs", [])
            if isinstance(candidate, dict) and candidate.get("alias") == alias
        ),
        None,
    )
    if entry is None or entry.get("allowAgentRead") is not True:
        raise ApprovalError(f"orgAlias {alias!r} is not a configured read-allowed org")
    if "prod" in alias.lower():
        raise ApprovalError("production-like aliases can never be batch-approved")


def entry_digest(entry: dict) -> str:
    return sha256(canonical({"tool": entry["tool"], "arguments": entry["arguments"]}))


def repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def approve(plan_path: Path, plan: dict, approver: str) -> Path:
    plan_digest = sha256(canonical(plan))
    receipt = {
        "kind": "dev-tool-batch-receipt",
        "planDigest": f"sha256:{plan_digest}",
        "planFile": repo_relative(plan_path),
        "orgAlias": plan["orgAlias"],
        "purpose": plan["purpose"],
        "approver": approver,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "ttlMinutes": TTL_MINUTES,
        "entries": [
            {"tool": entry["tool"], "digest": entry_digest(entry), "used": False}
            for entry in plan["entries"]
        ],
    }
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS_DIR / f"devtool-batch-{plan_digest[:12]}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-file", required=True, help="plan under .cache/devtool-batches/")
    parser.add_argument(
        "--approver", required=True, help="full name of the human approving this exact plan"
    )
    args = parser.parse_args(argv)
    approver = args.approver.strip()
    try:
        if not approver or approver.startswith("<"):
            raise ApprovalError("--approver must name the approving human")
        plan_path, plan = load_plan(args.plan_file)
        validate_org(plan)
        print("Reviewing plan:")
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        receipt_path = approve(plan_path, plan, approver)
    except ApprovalError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(
        json.dumps(
            {
                "approved": True,
                "receipt": repo_relative(receipt_path),
                "entries": len(plan["entries"]),
                "ttlMinutes": TTL_MINUTES,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
