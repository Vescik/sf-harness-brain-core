#!/usr/bin/env python3
"""Create and mutate durable governed work records without trusting chat history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

import yaml
from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.work_record by unit tests
    from scripts.schema_format import FORMAT_CHECKER


HARNESS_ROOT = Path(__file__).resolve().parents[1]
RECORD_SCHEMA = HARNESS_ROOT / "schemas" / "change-record.schema.json"
HANDOFF_SCHEMA = HARNESS_ROOT / "schemas" / "handoff-envelope.schema.json"
WORK_EVIDENCE_SCHEMA = HARNESS_ROOT / "schemas" / "work-evidence.schema.json"
SALESFORCE_REVIEW_SCHEMA = HARNESS_ROOT / "schemas" / "salesforce-org-review-evidence.schema.json"
VERIFICATION_POLICY_SCHEMA = HARNESS_ROOT / "schemas" / "verification-policy.schema.json"
VERIFICATION_RECEIPT_SCHEMA = HARNESS_ROOT / "schemas" / "verification-receipt.schema.json"
PRINCIPLE_REGISTRY_SCHEMA = HARNESS_ROOT / "schemas" / "principle-registry.schema.json"
VERIFICATION_POLICY_PATH = "config/verification-policy.json"
RULE_REGISTRY_PATH = ".github/instructions/rule-registry.yaml"

AGENT_ROLES = {
    "solution-designer",
    "config-investigator",
    "development-assistant",
    "test-strategist",
    "guardrail-reviewer",
}
ALL_ROLES = AGENT_ROLES | {"human", "system"}
HANDOFF_ROLES = AGENT_ROLES | {"human"}

RECORD_ID = re.compile(r"^ADO-[a-z0-9][a-z0-9-]{0,62}-[1-9][0-9]*$")
EVIDENCE_ID = re.compile(r"^EV-[A-Za-z0-9._-]+$")
HANDOFF_ID = re.compile(r"^HO-[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
RULE_ID = re.compile(r"^(SAFE|MP|ORG|SF)-[A-Z0-9-]+$")
ZERO_BYTE_SHA256 = hashlib.sha256(b"").hexdigest()

VALID_STATE_PAIRS = {
    ("intake", "draft"),
    ("intake", "incomplete"),
    ("intake", "blocked"),
    ("design", "draft"),
    ("design", "awaiting_human"),
    ("design", "accepted"),
    ("design", "incomplete"),
    ("design", "blocked"),
    ("development", "in_progress"),
    ("development", "incomplete"),
    ("development", "blocked"),
    ("qa", "in_progress"),
    ("qa", "incomplete"),
    ("qa", "blocked"),
    ("review", "ready"),
    ("review", "needs_fixes"),
    ("review", "incomplete"),
    ("review", "safe"),
    ("review", "stopped"),
    ("complete", "complete"),
}

ALLOWED_TRANSITIONS = {
    ("intake", "draft"): {
        ("design", "draft"),
        ("intake", "incomplete"),
        ("intake", "blocked"),
    },
    ("intake", "incomplete"): {("intake", "draft"), ("intake", "blocked")},
    ("intake", "blocked"): {("intake", "draft"), ("intake", "incomplete")},
    ("design", "draft"): {
        ("design", "awaiting_human"),
        ("design", "incomplete"),
        ("design", "blocked"),
    },
    ("design", "awaiting_human"): {
        ("design", "draft"),
        ("design", "incomplete"),
        ("design", "blocked"),
    },
    ("design", "incomplete"): {("design", "draft"), ("design", "blocked")},
    ("design", "blocked"): {("design", "draft"), ("design", "incomplete")},
    ("design", "accepted"): {
        ("development", "in_progress"),
        ("qa", "in_progress"),
        ("design", "blocked"),
    },
    ("development", "in_progress"): {
        ("review", "ready"),
        ("development", "incomplete"),
        ("development", "blocked"),
    },
    ("development", "incomplete"): {
        ("development", "in_progress"),
        ("development", "blocked"),
    },
    ("development", "blocked"): {
        ("development", "in_progress"),
        ("development", "incomplete"),
    },
    ("qa", "in_progress"): {
        ("review", "ready"),
        ("qa", "incomplete"),
        ("qa", "blocked"),
    },
    ("qa", "incomplete"): {("qa", "in_progress"), ("qa", "blocked")},
    ("qa", "blocked"): {("qa", "in_progress"), ("qa", "incomplete")},
    ("review", "needs_fixes"): {
        ("development", "in_progress"),
        ("design", "draft"),
        ("review", "incomplete"),
    },
    ("review", "incomplete"): {
        ("development", "in_progress"),
        ("qa", "in_progress"),
        ("design", "draft"),
        ("review", "stopped"),
    },
    ("review", "stopped"): {("design", "draft")},
    ("review", "safe"): {("complete", "complete")},
}

PROTECTED_TRANSITION_STATUSES = {"accepted", "safe", "needs_fixes", "stopped"}


class WorkRecordError(RuntimeError):
    """A safe, user-actionable work-record failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identifier(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:12]}"


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")


def atomic_write_text(path: Path, value: str) -> None:
    _atomic_write(path, value.encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkRecordError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkRecordError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkRecordError(f"expected a JSON object in {path}")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkRecordError(f"required file is missing: {path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise WorkRecordError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkRecordError(f"expected a YAML object in {path}")
    return value


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise WorkRecordError(f"{label} is not a valid date-time") from exc
    if parsed.tzinfo is None:
        raise WorkRecordError(f"{label} must include a timezone")
    return parsed


def contained_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    normalized = safe_relative_path(relative)
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkRecordError(f"path escapes workspace root: {relative}") from exc
    if must_exist and not candidate.is_file():
        raise WorkRecordError(f"required file is missing: {relative}")
    return candidate


def validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    messages = []
    for error in errors[:8]:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    suffix = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
    raise WorkRecordError(f"{label} schema validation failed: {'; '.join(messages)}{suffix}")


def ensure_record_id(record_id: str) -> None:
    if not RECORD_ID.fullmatch(record_id):
        raise WorkRecordError("record ID must match ADO-<project-slug>-<positive-item-id>")


def data_root(path: str | Path | None) -> Path:
    return Path(path or HARNESS_ROOT).expanduser().resolve()


def record_directory(root: Path, record_id: str) -> Path:
    ensure_record_id(record_id)
    base = (root / ".ai" / "change-records").resolve()
    candidate = (base / record_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise WorkRecordError("record path escapes .ai/change-records") from exc
    return candidate


def record_path(root: Path, record_id: str) -> Path:
    return record_directory(root, record_id) / "record.json"


def handoff_path(root: Path, record_id: str, handoff_id: str) -> Path:
    if not HANDOFF_ID.fullmatch(handoff_id):
        raise WorkRecordError("invalid handoff ID")
    return record_directory(root, record_id) / "handoffs" / f"{handoff_id}.json"


def evidence_path(root: Path, record_id: str, evidence_id: str) -> Path:
    if not EVIDENCE_ID.fullmatch(evidence_id):
        raise WorkRecordError("invalid evidence ID")
    return record_directory(root, record_id) / "evidence" / f"{evidence_id}.json"


def safe_relative_path(raw: str) -> str:
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise WorkRecordError(f"path must be a normalized workspace-relative path: {raw!r}")
    return candidate.as_posix()


def state_pair(record_or_state: dict[str, Any]) -> tuple[str, str]:
    state = record_or_state.get("state", record_or_state)
    return str(state.get("phase")), str(state.get("status"))


def state_object(pair: tuple[str, str]) -> dict[str, str]:
    return {"phase": pair[0], "status": pair[1]}


def scope_hash(scope: dict[str, Any]) -> str:
    components = sorted(
        (deepcopy(component) for component in scope.get("components", [])),
        key=lambda component: canonical_bytes(component),
    )
    normalized = {
        "workspaceRoot": scope.get("workspaceRoot"),
        "components": components,
        "paths": sorted(set(scope.get("paths", []))),
    }
    return json_hash(normalized)


def grounding_hash(record: dict[str, Any]) -> str:
    """Bind approval and handoffs to the exact deterministic grounding snapshot."""

    return json_hash(
        {
            "scopeHash": record.get("scopeHash"),
            "ruleRefs": sorted(
                deepcopy(record.get("ruleRefs", [])),
                key=lambda item: item.get("ruleId", ""),
            ),
            "claimRefs": sorted(
                deepcopy(record.get("claimRefs", [])),
                key=lambda item: item.get("claimId", ""),
            ),
            "repositories": sorted(
                [
                    {
                        "workspaceRoot": item.get("workspaceRoot"),
                        "remote": item.get("remote"),
                        "branch": item.get("branch"),
                        "baseCommit": item.get("baseCommit"),
                    }
                    for item in record.get("repositories", [])
                ],
                key=lambda item: item.get("workspaceRoot", ""),
            ),
            "environmentAlias": record.get("environment", {}).get("alias"),
        }
    )


def parse_component(raw: str) -> dict[str, Any]:
    try:
        component = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkRecordError(f"--component must be a JSON object: {exc}") from exc
    if not isinstance(component, dict):
        raise WorkRecordError("--component must be a JSON object")
    allowed = {"name", "type", "ownership", "packageNamespace", "packageVersion"}
    unknown = sorted(set(component) - allowed)
    if unknown:
        raise WorkRecordError(f"unknown component fields: {', '.join(unknown)}")
    missing = sorted({"name", "type"} - set(component))
    if missing:
        raise WorkRecordError(f"missing component fields: {', '.join(missing)}")
    if component.get("ownership", "unknown") != "unknown":
        raise WorkRecordError(
            "component ownership starts unknown; bind a fresh verified object-ownership claim"
        )
    if component.get("packageNamespace") is not None or component.get("packageVersion") is not None:
        raise WorkRecordError(
            "package namespace/version must be derived from a bound ownership claim"
        )
    normalized = {
        "name": str(component["name"]).strip(),
        "type": str(component["type"]).strip(),
        "ownership": "unknown",
        "ownershipClaimRef": None,
        "packageNamespace": None,
        "packageVersion": None,
    }
    if not normalized["name"] or not normalized["type"]:
        raise WorkRecordError("component name and type cannot be blank")
    return normalized


def contract_schema(root: Path, filename: str) -> Path:
    local = root / "schemas" / filename
    return local if local.is_file() else HARNESS_ROOT / "schemas" / filename


def load_rule_registry(root: Path) -> tuple[dict[str, Any], Path]:
    path = contained_path(root, RULE_REGISTRY_PATH)
    registry = load_yaml(path)
    validate_schema(
        registry,
        contract_schema(root, "principle-registry.schema.json"),
        "Principle registry",
    )
    return registry, path


def resolved_rule_ref(root: Path, rule_id: str) -> dict[str, Any]:
    if not RULE_ID.fullmatch(rule_id):
        raise WorkRecordError(f"invalid rule ID: {rule_id}")
    registry, registry_path = load_rule_registry(root)
    rule = next((item for item in registry["rules"] if item.get("ruleId") == rule_id), None)
    if rule is None:
        raise WorkRecordError(f"rule is absent from the canonical registry: {rule_id}")
    if rule.get("status") != "active" or rule.get("basis", {}).get("completeness") != "complete":
        raise WorkRecordError(f"rule is not active and complete: {rule_id}")
    source = contained_path(root, str(rule["sourceFile"]))
    return {
        "ruleId": rule_id,
        "tier": rule["tier"],
        "sourceFile": rule["sourceFile"],
        "registrySha256": file_hash(registry_path),
        "sourceSha256": file_hash(source),
    }


def validate_rule_refs(root: Path, references: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for reference in references:
        rule_id = str(reference.get("ruleId", ""))
        if rule_id in seen:
            raise WorkRecordError(f"duplicate rule reference: {rule_id}")
        seen.add(rule_id)
        if reference != resolved_rule_ref(root, rule_id):
            raise WorkRecordError(f"rule reference changed or is stale: {rule_id}")


def effective_knowledge_claim(root: Path, claim_id: str) -> dict[str, Any]:
    """Resolve one currently effective claim through the governed Knowledge registry."""

    try:
        from scripts.knowledge_registry import ContractError, KnowledgeRegistry
    except ModuleNotFoundError:
        try:
            from knowledge_registry import ContractError, KnowledgeRegistry
        except ModuleNotFoundError as exc:
            raise WorkRecordError("the governed Knowledge registry is unavailable") from exc
    try:
        result = KnowledgeRegistry(root).effective_claim(claim_id)
    except ContractError as exc:
        raise WorkRecordError(f"Knowledge claim is not effective: {claim_id}: {exc}") from exc
    if not isinstance(result, dict):
        raise WorkRecordError(f"Knowledge registry returned an invalid claim result: {claim_id}")
    return result


def claim_reference_from_result(
    root: Path,
    claim_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    claim = result.get("claim")
    sha256 = result.get("sha256")
    relative_path = result.get("path")
    if not isinstance(claim, dict) or claim.get("claimId") != claim_id:
        raise WorkRecordError(f"Knowledge registry returned the wrong claim identity: {claim_id}")
    if claim.get("status") != "verified":
        raise WorkRecordError(f"Knowledge claim is not verified: {claim_id}")
    expected_path = f".ai/knowledge/claims/{claim_id}.yaml"
    if relative_path != expected_path or not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        raise WorkRecordError(f"Knowledge registry returned an invalid claim binding: {claim_id}")
    path = contained_path(root, expected_path)
    if file_hash(path) != sha256:
        raise WorkRecordError(f"Knowledge claim changed while it was being bound: {claim_id}")
    required = {
        "revision",
        "claimType",
        "subject",
        "assertion",
        "scope",
        "reviewRef",
        "verifiedAt",
        "reviewBy",
    }
    missing = sorted(required - set(claim))
    if missing:
        raise WorkRecordError(
            f"Knowledge claim is missing binding fields ({', '.join(missing)}): {claim_id}"
        )
    if not claim.get("reviewRef") or not claim.get("verifiedAt"):
        raise WorkRecordError(f"Knowledge claim lacks a verified human-review binding: {claim_id}")
    return {
        "claimId": claim_id,
        "revision": claim["revision"],
        "path": expected_path,
        "sha256": sha256,
        "claimType": claim["claimType"],
        "subject": deepcopy(claim["subject"]),
        "assertion": deepcopy(claim["assertion"]),
        "scope": deepcopy(claim["scope"]),
        "reviewRef": claim["reviewRef"],
        "verifiedAt": claim["verifiedAt"],
        "reviewBy": claim["reviewBy"],
    }


def resolved_claim_ref(root: Path, claim_id: str) -> dict[str, Any]:
    return claim_reference_from_result(root, claim_id, effective_knowledge_claim(root, claim_id))


def persisted_claim_ref(root: Path, claim_id: str) -> dict[str, Any]:
    """Reconstruct a historical binding without treating the claim as current."""

    expected_path = f".ai/knowledge/claims/{claim_id}.yaml"
    path = contained_path(root, expected_path)
    claim = load_yaml(path)
    result = {
        "claim": {**claim, "status": "verified"},
        "sha256": file_hash(path),
        "path": expected_path,
    }
    # The reference stores only the verified projection. Overriding status here permits
    # historical validation after the registry later marks the source claim stale or
    # superseded; current gates always resolve through effective_knowledge_claim instead.
    return claim_reference_from_result(root, claim_id, result)


def validate_claim_refs(
    root: Path,
    references: list[dict[str, Any]],
    *,
    require_current: bool,
) -> None:
    seen: set[str] = set()
    for reference in references:
        claim_id = str(reference.get("claimId", ""))
        if claim_id in seen:
            raise WorkRecordError(f"duplicate Knowledge claim reference: {claim_id}")
        seen.add(claim_id)
        expected = resolved_claim_ref(root, claim_id) if require_current else persisted_claim_ref(root, claim_id)
        if reference != expected:
            qualifier = "effective" if require_current else "persisted"
            raise WorkRecordError(f"Knowledge claim reference differs from its {qualifier} source: {claim_id}")


def validate_component_claim_bindings(root: Path, record: dict[str, Any]) -> None:
    by_id = {item["claimId"]: item for item in record.get("claimRefs", [])}
    alias = record.get("environment", {}).get("alias")
    configured_environment: str | None = None
    if alias:
        entry, _ = configured_org(root, str(alias))
        configured_environment = str(entry["environment"])
    for component in record["scope"]["components"]:
        claim_id = component.get("ownershipClaimRef")
        if component["ownership"] == "unknown":
            if claim_id is not None:
                raise WorkRecordError("unknown component ownership cannot cite an ownership claim")
            continue
        reference = by_id.get(claim_id)
        if reference is None:
            raise WorkRecordError(
                f"component ownership claim is not bound: {component['name']}"
            )
        subject = reference["subject"]
        assertion = reference["assertion"]
        if (
            reference["claimType"] != "object-ownership"
            or component["type"].lower() not in {"customobject", "object"}
            or subject.get("kind") != "object"
            or subject.get("identity") != component["name"]
            or assertion.get("predicate") != "ownership-classification"
            or assertion.get("value") != component["ownership"]
        ):
            raise WorkRecordError(
                f"component ownership does not match its structural Knowledge claim: {component['name']}"
            )
        claim_scope = reference["scope"]
        claim_environment = claim_scope.get("environment")
        if claim_environment != "not-applicable" and claim_environment != configured_environment:
            raise WorkRecordError(
                f"component ownership claim targets a different environment: {component['name']}"
            )
        if component["ownership"] == "package-owned":
            if (
                component["packageNamespace"] != claim_scope.get("packageNamespace")
                or component["packageVersion"] != claim_scope.get("packageVersion")
            ):
                raise WorkRecordError(
                    f"component package identity does not match its ownership claim: {component['name']}"
                )
        elif any(
            claim_scope.get(field) is not None
            for field in ("packageNamespace", "packageKey", "packageVersion")
        ):
            raise WorkRecordError(
                f"non-package component cites package-scoped ownership: {component['name']}"
            )


def workspace_path(root: Path, workspace_root: str) -> Path:
    if workspace_root != "brain-core":
        raise WorkRecordError(f"unsupported workspace root: {workspace_root}")
    return root.resolve()


def run_git(path: Path, *arguments: str, required: bool = True) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkRecordError(f"repository inspection failed for {path}") from exc
    if completed.returncode != 0:
        if required:
            raise WorkRecordError(f"repository inspection failed for {path}: {' '.join(arguments)}")
        return None
    return completed.stdout.strip()


def privacy_preserving_remote(value: str | None) -> str | None:
    if not value:
        return None
    # Repository lineage needs stable equality, not a potentially credential-bearing URL.
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def repository_state(root: Path, workspace_root: str) -> dict[str, Any]:
    path = workspace_path(root, workspace_root)
    if not path.is_dir():
        raise WorkRecordError(f"workspace root is missing: {workspace_root}")
    repository_root_text = run_git(path, "rev-parse", "--show-toplevel")
    if not repository_root_text:
        raise WorkRecordError(f"workspace root is not inside a Git repository: {workspace_root}")
    repository_root = Path(repository_root_text).resolve()
    try:
        workspace_relative = path.relative_to(repository_root)
    except ValueError as exc:
        raise WorkRecordError(f"workspace root escapes its Git repository: {workspace_root}") from exc
    if workspace_relative != Path("."):
        raise WorkRecordError("brain-core must be the Git repository root")
    pathspecs = (
        "sfdx-project.json",
        ".forceignore",
        "config/project-scratch-def.json",
        "force-app",
        "manifest",
        "tests/e2e",
    )
    head = run_git(repository_root, "rev-parse", "HEAD")
    if head is None or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise WorkRecordError(f"repository HEAD is not a full commit: {workspace_root}")
    branch = run_git(
        repository_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        required=False,
    )
    status = run_git(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *pathspecs,
    ) or ""
    dirty_paths: list[str] = []
    for line in status.splitlines():
        raw = line[3:] if len(line) >= 4 else line
        # For a rename, retain only the destination path while preserving that the tree is dirty.
        relative = raw.rsplit(" -> ", 1)[-1].strip('"')
        dirty_paths.append(relative)
    remote = run_git(
        repository_root,
        "config",
        "--get",
        "remote.origin.url",
        required=False,
    )
    return {
        "workspaceRoot": workspace_root,
        "remote": privacy_preserving_remote(remote),
        "branch": branch or None,
        "headCommit": head,
        "dirtyPaths": sorted(set(dirty_paths)),
        "capturedAt": utc_now(),
    }


def repository_snapshot_current(root: Path, reference: dict[str, Any]) -> bool:
    actual = repository_state(root, reference["workspaceRoot"])
    return (
        actual["headCommit"] == reference["headCommit"]
        and actual["dirtyPaths"] == reference["dirtyPaths"]
        and actual["branch"] == reference["branch"]
        and actual["remote"] == reference["remote"]
    )


def load_local_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "harness.local.json"
    return load_json(path)


def configured_org(root: Path, alias: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_local_config(root)
    entry = next(
        (
            item
            for item in config.get("salesforce", {}).get("orgs", [])
            if item.get("alias") == alias
        ),
        None,
    )
    if not isinstance(entry, dict):
        raise WorkRecordError("record environment alias is not present in local policy")
    if (
        entry.get("environment") not in {"development", "qa", "uat"}
        or entry.get("allowAgentRead") is not True
        or entry.get("allowAgentReview") is not True
    ):
        raise WorkRecordError("record environment alias is not authorized for org review")
    review = config.get("salesforce", {}).get("review", {})
    if review.get("enabled") is not True or review.get("requireDualSource") is not True:
        raise WorkRecordError("dual-transport Salesforce review is not enabled")
    return entry, config


def assert_fresh_environment_receipt(
    root: Path,
    record: dict[str, Any],
    evidence_by_path: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    environment = record["environment"]
    if not (
        environment.get("status") == "verified"
        and environment.get("isSandbox") is True
        and environment.get("alias")
        and environment.get("verificationRef")
        and environment.get("verifiedAt")
    ):
        raise WorkRecordError("a fresh reconciled sandbox identity receipt is required")
    pair_value = evidence_by_path.get(str(environment["verificationRef"]))
    if pair_value is None:
        raise WorkRecordError("environment verification receipt is missing")
    reference, receipt = pair_value
    if (
        reference["type"] != "salesforce-org-identity"
        or receipt.get("reviewType") != "org-identity"
        or receipt.get("status") != "VERIFIED"
        or receipt.get("generatedAt") != environment["verifiedAt"]
        or receipt.get("facts", {}).get("isSandbox") is not True
        or receipt.get("target", {}).get("isSandbox") is not True
    ):
        raise WorkRecordError("environment verification is not a VERIFIED sandbox identity receipt")
    entry, config = configured_org(root, str(environment["alias"]))
    if receipt.get("target", {}).get("environment") != entry.get("environment"):
        raise WorkRecordError("environment receipt does not match the configured environment")
    max_age = config["salesforce"]["review"]["evidenceMaxAgeMinutes"]
    age_seconds = (
        datetime.now(timezone.utc)
        - parse_time(str(environment["verifiedAt"]), "verifiedAt")
    ).total_seconds()
    if age_seconds < 0 or age_seconds > max_age * 60:
        raise WorkRecordError("Salesforce identity receipt is not fresh")
    return receipt


def canonical_embedded_digest(value: dict[str, Any], digest_field: str = "sha256") -> str:
    unsigned = {key: child for key, child in value.items() if key != digest_field}
    return json_hash(unsigned)


def validate_salesforce_review_envelope(root: Path, envelope: dict[str, Any]) -> None:
    validate_schema(
        envelope,
        contract_schema(root, "salesforce-org-review-evidence.schema.json"),
        "Salesforce review evidence",
    )
    if envelope.get("sha256") != canonical_embedded_digest(envelope):
        raise WorkRecordError("Salesforce review evidence digest is invalid")


def call_salesforce_review_facade(
    root: Path,
    alias: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call the fixed local facade directly and return only its normalized envelope."""

    script = root / "scripts" / "salesforce_review_server.mjs"
    if not script.is_file():
        raise WorkRecordError("Salesforce review facade is missing")
    messages = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "work-record", "version": "1.0.0"},
                    },
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                }
            ),
            "",
        ]
    )
    try:
        completed = subprocess.run(
            ["node", str(script), "--org", alias],
            cwd=root,
            input=messages,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkRecordError("Salesforce review facade was unavailable") from exc
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 1_048_576:
        raise WorkRecordError("Salesforce review facade did not return a bounded successful receipt")
    response: dict[str, Any] | None = None
    for line in completed.stdout.splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("id") == 2:
            response = candidate
            break
    envelope = response.get("result", {}).get("structuredContent") if response else None
    if not isinstance(envelope, dict):
        raise WorkRecordError("Salesforce review facade response was malformed")
    validate_salesforce_review_envelope(root, envelope)
    return envelope


def load_verification_policy(root: Path) -> tuple[dict[str, Any], Path]:
    path = contained_path(root, VERIFICATION_POLICY_PATH)
    policy = load_json(path)
    validate_schema(
        policy,
        contract_schema(root, "verification-policy.schema.json"),
        "verification policy",
    )
    missing = sorted(set(policy["requiredForSafe"]) - set(policy["profiles"]))
    if missing:
        raise WorkRecordError(f"verification policy references missing profiles: {missing}")
    return policy, path


def resolved_profile_command(
    root: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
) -> list[str]:
    config = load_local_config(root)
    alias = record.get("environment", {}).get("alias")
    substitutions = {
        "${PYTHON}": sys.executable,
        "${SALESFORCE_ALIAS}": str(alias or ""),
        "${MANIFEST_PATH}": str(config.get("workspace", {}).get("manifestPath", "")),
    }
    result: list[str] = []
    for raw in profile["command"]:
        if raw in substitutions:
            value = substitutions[raw]
            if not value:
                raise WorkRecordError(f"verification placeholder is unresolved: {raw}")
            result.append(value)
        elif "${" in raw:
            raise WorkRecordError("verification placeholders must occupy an entire command argument")
        else:
            result.append(raw)
    return result


def stream_receipt(handle: Any) -> dict[str, Any]:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest(), "retained": False}


def execute_verification_profile(
    root: Path,
    record: dict[str, Any],
    role: str,
    profile_id: str,
) -> dict[str, Any]:
    policy, policy_path = load_verification_policy(root)
    profile = policy["profiles"].get(profile_id)
    if not isinstance(profile, dict):
        raise WorkRecordError(f"verification profile is not configured: {profile_id}")
    if role not in profile["allowedRoles"]:
        raise WorkRecordError(f"role cannot run verification profile: {profile_id}")
    repository = next(
        (
            item
            for item in record["repositories"]
            if item["workspaceRoot"] == profile["workspaceRoot"]
        ),
        None,
    )
    if repository is None or not repository_snapshot_current(root, repository):
        raise WorkRecordError("verification requires a current captured repository snapshot")
    if repository["dirtyPaths"]:
        raise WorkRecordError("verification requires a clean commit-bound repository")
    command = resolved_profile_command(root, record, profile)
    started_at = utc_now()
    timed_out = False
    exit_code: int | None = None
    with tempfile.TemporaryFile() as stdout_handle, tempfile.TemporaryFile() as stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace_path(root, profile["workspaceRoot"]),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=os.environ.copy(),
                shell=False,
            )
            try:
                exit_code = process.wait(timeout=profile["timeoutSeconds"])
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait(timeout=10)
        except OSError:
            exit_code = 127
        stdout = stream_receipt(stdout_handle)
        stderr = stream_receipt(stderr_handle)
    over_limit = max(stdout["bytes"], stderr["bytes"]) > profile["maxOutputBytes"]
    status = (
        "timed-out"
        if timed_out
        else "output-limit-exceeded"
        if over_limit
        else "passed"
        if exit_code == 0
        else "failed"
    )
    receipt = {
        "schemaVersion": 1,
        "receiptType": "verification-execution",
        "verificationId": identifier("VR"),
        "profileId": profile_id,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "performedBy": role,
        "workspaceRoot": profile["workspaceRoot"],
        "repositoryHeadCommit": repository["headCommit"],
        "policySha256": file_hash(policy_path),
        "commandSha256": json_hash(command),
        "status": status,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }
    validate_schema(
        receipt,
        contract_schema(root, "verification-receipt.schema.json"),
        "verification receipt",
    )
    return receipt


def current_approval(record: dict[str, Any]) -> dict[str, Any] | None:
    design_hash = record.get("design", {}).get("sha256")
    expected_scope = record.get("scopeHash")
    expected_grounding = record.get("groundingHash")
    for approval in reversed(record.get("approvals", [])):
        if (
            approval.get("status") == "active"
            and approval.get("scopeHash") == expected_scope
            and approval.get("designHash") == design_hash
            and approval.get("groundingHash") == expected_grounding
        ):
            return approval
    return None


def open_question_ids(record: dict[str, Any]) -> list[str]:
    return [
        str(question.get("id"))
        for question in record.get("blockingQuestions", [])
        if question.get("status") == "open"
    ]


def load_bound_evidence(
    root: Path,
    record: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    directory = record_directory(root, record["recordId"])
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for reference in record.get("evidenceRefs", []):
        path = _resolve_record_relative(directory, root, reference["path"])
        result[reference["path"]] = (reference, load_json(path))
    return result


def _resolve_record_relative(record_dir: Path, root: Path, relative: str) -> Path:
    normalized = safe_relative_path(relative)
    record_candidate = (record_dir / normalized).resolve()
    if record_candidate.exists():
        try:
            record_candidate.relative_to(record_dir.resolve())
        except ValueError as exc:
            raise WorkRecordError(f"required path escapes record directory: {relative}") from exc
        return record_candidate
    root_candidate = (root / normalized).resolve()
    try:
        root_candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkRecordError(f"required path escapes workspace root: {relative}") from exc
    return root_candidate


def validate_record_semantics(root: Path, record: dict[str, Any], *, check_design: bool = True) -> None:
    pair = state_pair(record)
    if pair not in VALID_STATE_PAIRS:
        raise WorkRecordError(f"invalid phase/status pair: {pair[0]}/{pair[1]}")
    calculated_scope = scope_hash(record["scope"])
    if calculated_scope != record.get("scopeHash"):
        raise WorkRecordError("scopeHash does not match the canonical scope")
    if grounding_hash(record) != record.get("groundingHash"):
        raise WorkRecordError("groundingHash does not match rules, claims, scope, repositories, and environment")
    validate_rule_refs(root, record.get("ruleRefs", []))
    validate_claim_refs(root, record.get("claimRefs", []), require_current=False)
    validate_component_claim_bindings(root, record)

    record_dir = record_directory(root, record["recordId"])
    design = _resolve_record_relative(record_dir, root, record["design"]["path"])
    if not design.is_file():
        raise WorkRecordError(f"design narrative is missing: {design}")
    actual_design_hash = file_hash(design)
    if check_design and actual_design_hash != record["design"]["sha256"]:
        raise WorkRecordError(
            "design narrative hash changed; transition it through the work-record command before relying on it"
        )

    approval_required = pair in {
        ("design", "accepted"),
        ("development", "in_progress"),
        ("development", "incomplete"),
        ("development", "blocked"),
        ("qa", "in_progress"),
        ("qa", "incomplete"),
        ("qa", "blocked"),
        ("review", "ready"),
        ("review", "needs_fixes"),
        ("review", "incomplete"),
        ("review", "safe"),
        ("review", "stopped"),
        ("complete", "complete"),
    }
    if approval_required and current_approval(record) is None:
        raise WorkRecordError("current state requires a human approval bound to the exact scope and design")

    evidence_ids: set[str] = set()
    evidence_by_path: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for reference in record.get("evidenceRefs", []):
        evidence_id = reference["evidenceId"]
        if evidence_id in evidence_ids:
            raise WorkRecordError(f"duplicate evidence reference: {evidence_id}")
        evidence_ids.add(evidence_id)
        evidence_file = _resolve_record_relative(record_dir, root, reference["path"])
        if not evidence_file.is_file():
            raise WorkRecordError(f"evidence file is missing: {reference['path']}")
        if file_hash(evidence_file) != reference["sha256"]:
            raise WorkRecordError(f"evidence hash mismatch: {evidence_id}")
        evidence = load_json(evidence_file)
        if reference["type"].startswith("salesforce-"):
            validate_salesforce_review_envelope(root, evidence)
        elif reference["type"].startswith("verification:"):
            validate_schema(
                evidence,
                contract_schema(root, "verification-receipt.schema.json"),
                f"verification evidence {evidence_id}",
            )
        else:
            validate_schema(
                evidence,
                contract_schema(root, "work-evidence.schema.json"),
                f"work evidence {evidence_id}",
            )
            if evidence.get("evidenceId") != evidence_id or evidence.get("recordId") != record["recordId"]:
                raise WorkRecordError(f"work evidence identity mismatch: {evidence_id}")
            artifact = evidence["artifact"]
            artifact_path = _resolve_record_relative(record_dir, root, artifact["path"])
            if not artifact_path.is_file() or file_hash(artifact_path) != artifact["sha256"]:
                raise WorkRecordError(f"bound evidence artifact changed: {evidence_id}")
        evidence_by_path[reference["path"]] = (reference, evidence)

    repository_roots: set[str] = set()
    for repository in record.get("repositories", []):
        workspace_root = repository["workspaceRoot"]
        if workspace_root in repository_roots:
            raise WorkRecordError(f"duplicate repository snapshot: {workspace_root}")
        repository_roots.add(workspace_root)

    verification_ids: set[str] = set()
    verification_policy, verification_policy_path = load_verification_policy(root)
    for verification in record.get("verification", []):
        verification_id = verification["verificationId"]
        if verification_id in verification_ids:
            raise WorkRecordError(f"duplicate verification receipt: {verification_id}")
        verification_ids.add(verification_id)
        pair_value = evidence_by_path.get(verification["evidenceRef"])
        if pair_value is None:
            raise WorkRecordError(f"verification evidence is missing: {verification_id}")
        reference, receipt = pair_value
        profile = verification_policy["profiles"].get(verification["profileId"])
        if (
            not isinstance(profile, dict)
            or reference["type"] != f"verification:{verification['profileId']}"
            or reference["sha256"] != verification["receiptSha256"]
            or receipt.get("verificationId") != verification_id
            or receipt.get("profileId") != verification["profileId"]
            or receipt.get("performedBy") != verification["role"]
            or receipt.get("completedAt") != verification["performedAt"]
            or receipt.get("status") != verification["status"]
            or receipt.get("repositoryHeadCommit") != verification["repositoryHeadCommit"]
            or receipt.get("workspaceRoot") != profile.get("workspaceRoot")
            or receipt.get("policySha256") != file_hash(verification_policy_path)
            or receipt.get("commandSha256")
            != json_hash(resolved_profile_command(root, record, profile))
        ):
            raise WorkRecordError(f"verification entry does not match its receipt: {verification_id}")
        if parse_time(receipt["completedAt"], "verification completedAt") < parse_time(
            receipt["startedAt"], "verification startedAt"
        ):
            raise WorkRecordError(f"verification receipt has reversed timestamps: {verification_id}")
        output_over_limit = max(receipt["stdout"]["bytes"], receipt["stderr"]["bytes"]) > profile[
            "maxOutputBytes"
        ]
        if (receipt["status"] == "output-limit-exceeded") != output_over_limit:
            raise WorkRecordError(f"verification output-limit status is inconsistent: {verification_id}")

    environment = record["environment"]
    if environment["status"] == "verified":
        pair_value = evidence_by_path.get(environment["verificationRef"])
        if pair_value is None:
            raise WorkRecordError("environment verification receipt is missing")
        reference, receipt = pair_value
        if (
            reference["type"] != "salesforce-org-identity"
            or receipt.get("reviewType") != "org-identity"
            or receipt.get("status") != "VERIFIED"
            or receipt.get("generatedAt") != environment["verifiedAt"]
            or receipt.get("facts", {}).get("isSandbox") is not True
            or receipt.get("target", {}).get("isSandbox") is not True
        ):
            raise WorkRecordError("environment verification is not a VERIFIED org-identity receipt")

    valid_resolution_refs = {item["claimId"] for item in record.get("claimRefs", [])} | evidence_ids
    for question in record.get("blockingQuestions", []):
        if question["status"] == "open" and question.get("resolutionRef") is not None:
            raise WorkRecordError(f"open blocking question has a resolution: {question['id']}")
        if question["status"] == "resolved" and question.get("resolutionRef") not in valid_resolution_refs:
            raise WorkRecordError(f"blocking question resolution is not grounded: {question['id']}")

    if pair in {("review", "safe"), ("complete", "complete")}:
        if open_question_ids(record):
            raise WorkRecordError("SAFE/complete state cannot contain an open blocking question")
        durable = [
            evidence
            for reference, evidence in evidence_by_path.values()
            if reference["durability"] == "durable"
            and reference["completeness"] == "complete"
            and evidence.get("receiptType") == "bound-artifact"
        ]
        if not durable:
            raise WorkRecordError("SAFE/complete state requires durable complete bound-artifact evidence")
        if any(item["completeness"] != "complete" for item in record["evidenceRefs"]):
            raise WorkRecordError("SAFE/complete state cannot rely on partial evidence")
        if not (
            environment.get("status") == "verified"
            and environment.get("isSandbox") is True
            and environment.get("verificationRef")
            and environment.get("verifiedAt")
        ):
            raise WorkRecordError("SAFE/complete state requires verified non-production environment evidence")
        assert_fresh_environment_receipt(root, record, evidence_by_path)
        if not record["ruleRefs"] or not {"kernel", "1", "2", "3"}.issubset(
            {item["tier"] for item in record["ruleRefs"]}
        ):
            raise WorkRecordError("SAFE/complete state requires applicable rules from kernel and Tiers 1-3")
        if not record["claimRefs"]:
            raise WorkRecordError("SAFE/complete state requires fresh verified Knowledge claims")
        validate_claim_refs(root, record["claimRefs"], require_current=True)
        bound_claims = {item["claimId"] for item in record["claimRefs"]}
        if any(
            component["ownership"] == "unknown"
            or component["ownershipClaimRef"] not in bound_claims
            for component in record["scope"]["components"]
        ):
            raise WorkRecordError("SAFE/complete state requires claim-backed component ownership")
        repository = next(
            (
                item
                for item in record["repositories"]
                if item["workspaceRoot"] == record["scope"]["workspaceRoot"]
            ),
            None,
        )
        if repository is None or repository["dirtyPaths"] or not repository_snapshot_current(root, repository):
            raise WorkRecordError("SAFE/complete state requires a current clean commit-bound repository")
        approval = current_approval(record)
        assert approval is not None
        passed_by_profile = {
            item["profileId"]: item
            for item in record["verification"]
            if item["status"] == "passed"
            and item["repositoryHeadCommit"] == repository["headCommit"]
            and parse_time(item["performedAt"], "verification performedAt")
            >= parse_time(approval["approvedAt"], "approval approvedAt")
        }
        missing_profiles = sorted(
            set(verification_policy["requiredForSafe"]) - set(passed_by_profile)
        )
        if missing_profiles:
            raise WorkRecordError(f"SAFE/complete state is missing required verification profiles: {missing_profiles}")
        review = record.get("review")
        if not review or review.get("role") != "guardrail-reviewer" or review.get("verdict") != "SAFE":
            raise WorkRecordError("SAFE/complete state requires an independent SAFE review")

    current_handoff_id = record.get("currentHandoffId")
    if current_handoff_id:
        path = handoff_path(root, record["recordId"], current_handoff_id)
        if path.exists():
            handoff = load_json(path)
            validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
            if handoff.get("status") != "pending":
                raise WorkRecordError("currentHandoffId does not reference a pending handoff")
            if handoff.get("recordRevision") != record["recordRevision"]:
                raise WorkRecordError("pending handoff binds to a stale record revision")
            if handoff.get("recordHash") != json_hash(record):
                raise WorkRecordError("pending handoff binds to a stale record hash")
            if handoff.get("scopeHash") != record["scopeHash"]:
                raise WorkRecordError("pending handoff binds to a stale scope")
            if handoff.get("scope") != record["scope"] or scope_hash(handoff["scope"]) != handoff["scopeHash"]:
                raise WorkRecordError("pending handoff component scope does not match its scope hash")
            if handoff.get("designHash") != record["design"]["sha256"]:
                raise WorkRecordError("pending handoff binds to a stale design")
            if (
                handoff.get("groundingHash") != record["groundingHash"]
                or handoff.get("ruleRefs") != record["ruleRefs"]
                or handoff.get("claimRefs") != record["claimRefs"]
            ):
                raise WorkRecordError("pending handoff binds to stale grounding")


def load_record(root: Path, record_id: str, *, check_design: bool = True) -> dict[str, Any]:
    record = load_json(record_path(root, record_id))
    validate_schema(record, RECORD_SCHEMA, "change record")
    if record.get("recordId") != record_id:
        raise WorkRecordError("record ID does not match its directory")
    validate_record_semantics(root, record, check_design=check_design)
    return record


def check_expected(record: dict[str, Any], revision: int, expected_hash: str) -> None:
    if record["recordRevision"] != revision:
        raise WorkRecordError(
            f"stale record revision: expected {revision}, current is {record['recordRevision']}"
        )
    actual_hash = json_hash(record)
    if actual_hash != expected_hash:
        raise WorkRecordError(f"stale record hash: expected {expected_hash}, current is {actual_hash}")


def append_event(
    record: dict[str, Any],
    *,
    action: str,
    role: str,
    from_state: dict[str, str] | None,
    note: str,
    at: str,
) -> None:
    record["events"].append(
        {
            "eventId": identifier("ET"),
            "at": at,
            "action": action,
            "role": role,
            "fromState": deepcopy(from_state),
            "toState": deepcopy(record["state"]),
            "note": note,
        }
    )


def bump(record: dict[str, Any], at: str) -> None:
    record["recordRevision"] += 1
    record["updatedAt"] = at


def persist_record(root: Path, record: dict[str, Any], *, check_design: bool = True) -> dict[str, Any]:
    validate_schema(record, RECORD_SCHEMA, "change record")
    validate_record_semantics(root, record, check_design=check_design)
    atomic_write_json(record_path(root, record["recordId"]), record)
    return summary(record)


def summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": record["recordId"],
        "recordRevision": record["recordRevision"],
        "recordHash": json_hash(record),
        "state": deepcopy(record["state"]),
        "scopeHash": record["scopeHash"],
        "groundingHash": record["groundingHash"],
        "designHash": record["design"]["sha256"],
        "currentHandoffId": record["currentHandoffId"],
    }


def render_design(record_id: str, title: str, requested_outcome: str) -> str:
    return f"""# Design Narrative — {record_id}: {title}

> Machine state, approvals, evidence, verdicts, and handoffs live in `record.json`.

## Requested outcome

{requested_outcome}

## Source context

To be established from sourced evidence.

## Affected components

To be established without assuming package ownership or extension points.

## Applicable rule IDs and known limitations

To be established from the applicable policy and verified limitations.

## Proposed design

Draft — not approved.

## Alternatives and trade-offs

To be evaluated.

## Assumptions, unknowns, and blocking questions

See the structured lists in `record.json`.

## Verification and coverage plan

To be established.

## Human review notes

Approval must be recorded through the human-only approval mechanism and bound to this file hash.
"""


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    ensure_record_id(args.record_id)
    directory = record_directory(root, args.record_id)
    target = directory / "record.json"
    if target.exists() or directory.exists() and any(directory.iterdir()):
        raise WorkRecordError(f"record already exists or directory is not empty: {args.record_id}")

    components = sorted(
        [parse_component(raw) for raw in (args.component or [])],
        key=lambda component: canonical_bytes(component),
    )
    if not components:
        raise WorkRecordError("governed Salesforce work requires at least one scoped component")
    paths = sorted(set(safe_relative_path(path) for path in (args.path or [])))
    if args.environment_alias:
        configured_org(root, args.environment_alias)
    rule_refs = sorted(
        [resolved_rule_ref(root, rule_id) for rule_id in set(args.rule_id or [])],
        key=lambda item: item["ruleId"],
    )
    timestamp = utc_now()
    design_text = render_design(args.record_id, args.title, args.requested_outcome)
    design_path = directory / "design.md"
    atomic_write_text(design_path, design_text)
    scope = {
        "workspaceRoot": args.workspace_root,
        "components": components,
        "paths": paths,
    }
    state = {"phase": "intake", "status": "draft"}
    record: dict[str, Any] = {
        "schemaVersion": 2,
        "recordId": args.record_id,
        "recordRevision": 1,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "workItem": {
            "system": "azure-devops",
            "organization": args.organization,
            "project": args.project,
            "id": args.work_item_id,
            "type": args.work_item_type,
            "url": args.work_item_url,
            "revision": args.work_item_revision,
            "fetchedAt": args.fetched_at,
        },
        "state": state,
        "requestedOutcome": args.requested_outcome,
        "scope": scope,
        "scopeHash": scope_hash(scope),
        "environment": {
            "status": "unverified",
            "alias": args.environment_alias,
            "isSandbox": None,
            "verificationRef": None,
            "verifiedAt": None,
        },
        "ruleRefs": rule_refs,
        "claimRefs": [],
        "contextRefs": [],
        "assumptions": [],
        "unknowns": [],
        "blockingQuestions": [],
        "design": {"path": "design.md", "sha256": file_hash(design_path)},
        "approvals": [],
        "evidenceRefs": [],
        "implementation": {"filesChanged": [], "notes": []},
        "verification": [],
        "review": None,
        "repositories": [],
        "currentHandoffId": None,
        "handoffHistoryRefs": [],
        "events": [
            {
                "eventId": identifier("ET"),
                "at": timestamp,
                "action": "init",
                "role": "solution-designer",
                "fromState": None,
                "toState": deepcopy(state),
                "note": "Initialized governed work record.",
            }
        ],
    }
    record["groundingHash"] = grounding_hash(record)
    return persist_record(root, record)


def command_validate(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    record = load_record(root, args.record_id)
    directory = record_directory(root, args.record_id)
    for relative in record["handoffHistoryRefs"]:
        handoff = load_json(directory / relative)
        validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
        if handoff["recordId"] != args.record_id:
            raise WorkRecordError(f"handoff belongs to another record: {relative}")
    result = summary(record)
    result["valid"] = True
    result["evidenceCount"] = len(record["evidenceRefs"])
    result["handoffHistoryCount"] = len(record["handoffHistoryRefs"])
    return result


def command_context(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in AGENT_ROLES:
        raise WorkRecordError("context role must be a governed agent role")
    record = load_record(root, args.record_id)
    handoff_summary: dict[str, Any] | None = None
    if args.handoff_id:
        handoff = load_json(handoff_path(root, args.record_id, args.handoff_id))
        validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
        if handoff["status"] != "pending":
            raise WorkRecordError("handoff is not pending")
        if handoff["toRole"] != args.role:
            raise WorkRecordError("handoff is addressed to another role")
        if record["currentHandoffId"] != args.handoff_id:
            raise WorkRecordError("handoff is not the record's current handoff")
        if handoff["recordRevision"] != record["recordRevision"] or handoff["recordHash"] != json_hash(record):
            raise WorkRecordError("handoff is stale relative to the current record")
        if (
            handoff["scope"] != record["scope"]
            or scope_hash(handoff["scope"]) != handoff["scopeHash"]
            or handoff["scopeHash"] != record["scopeHash"]
        ):
            raise WorkRecordError("handoff component scope is stale relative to the current record")
        handoff_summary = {
            "handoffId": handoff["handoffId"],
            "handoffHash": json_hash(handoff),
            "fromRole": handoff["fromRole"],
            "toRole": handoff["toRole"],
            "reason": handoff["reason"],
            "requiredReads": handoff["requiredReads"],
            "requiredActions": handoff["requiredActions"],
            "prohibitedActions": handoff["prohibitedActions"],
            "unresolvedQuestions": handoff["unresolvedQuestions"],
            "completeness": handoff["completeness"],
        }
    return {
        **summary(record),
        "role": args.role,
        "workItem": deepcopy(record["workItem"]),
        "requestedOutcome": record["requestedOutcome"],
        "scope": deepcopy(record["scope"]),
        "groundingHash": record["groundingHash"],
        "ruleRefs": deepcopy(record["ruleRefs"]),
        "claimRefs": deepcopy(record["claimRefs"]),
        "environment": deepcopy(record["environment"]),
        "contextRefs": deepcopy(record["contextRefs"]),
        "evidenceRefs": deepcopy(record["evidenceRefs"]),
        "blockingQuestions": deepcopy(record["blockingQuestions"]),
        "approvalCurrent": current_approval(record) is not None,
        "repositories": deepcopy(record["repositories"]),
        "handoff": handoff_summary,
    }


def role_allows_transition(role: str, current: tuple[str, str], target: tuple[str, str]) -> bool:
    if role == "solution-designer":
        return target[0] in {"intake", "design"}
    if role == "development-assistant":
        return target[0] == "development" or target == ("review", "ready")
    if role == "test-strategist":
        return target[0] == "qa" or target == ("review", "ready")
    if role == "guardrail-reviewer":
        return current == ("review", "safe") and target == ("complete", "complete")
    return False


def refresh_preapproval_design(root: Path, record: dict[str, Any]) -> None:
    directory = record_directory(root, record["recordId"])
    design_path = _resolve_record_relative(directory, root, record["design"]["path"])
    actual = file_hash(design_path)
    if actual == record["design"]["sha256"]:
        return
    if current_approval(record) is not None or state_pair(record) not in {
        ("intake", "draft"),
        ("intake", "incomplete"),
        ("intake", "blocked"),
        ("design", "draft"),
        ("design", "awaiting_human"),
        ("design", "incomplete"),
        ("design", "blocked"),
    }:
        raise WorkRecordError("design changed after approval or implementation started; re-open through human governance")
    record["design"]["sha256"] = actual


def supersede_active_approvals(record: dict[str, Any], *, at: str, reason: str) -> None:
    for approval in record["approvals"]:
        if approval.get("status") == "active":
            approval["status"] = "superseded"
            approval["invalidatedAt"] = at
            approval["invalidationReason"] = reason


def command_transition(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in AGENT_ROLES:
        raise WorkRecordError("transition role must be a governed agent role")
    record = load_record(root, args.record_id, check_design=False)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume or supersede the pending handoff before transitioning state")
    refresh_preapproval_design(root, record)
    current = state_pair(record)
    target = (args.phase, args.status)
    if target not in VALID_STATE_PAIRS:
        raise WorkRecordError(f"invalid target state: {target[0]}/{target[1]}")
    if target[1] in PROTECTED_TRANSITION_STATUSES:
        raise WorkRecordError(
            "target status is protected; use approve, append-review, or the dedicated review-ready transition"
        )
    if target == ("complete", "complete") and current != ("review", "safe"):
        raise WorkRecordError("completion is allowed only from review/safe")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise WorkRecordError(
            f"transition is not allowed: {current[0]}/{current[1]} -> {target[0]}/{target[1]}"
        )
    if not role_allows_transition(args.role, current, target):
        raise WorkRecordError(f"{args.role} is not authorized for the requested transition")
    if target == ("review", "ready") and current_approval(record) is None:
        raise WorkRecordError("review readiness requires a current human-approved design")

    before = deepcopy(record["state"])
    timestamp = utc_now()
    if target == ("design", "draft") and current_approval(record) is not None:
        supersede_active_approvals(record, at=timestamp, reason=args.note)
    record["state"] = state_object(target)
    if args.file_changed:
        if args.role != "development-assistant":
            raise WorkRecordError("only development-assistant may add implementation file paths")
        record["implementation"]["filesChanged"] = sorted(
            set(record["implementation"]["filesChanged"])
            | {safe_relative_path(path) for path in args.file_changed}
        )
    if args.implementation_note:
        if args.role != "development-assistant":
            raise WorkRecordError("only development-assistant may add implementation notes")
        record["implementation"]["notes"].extend(args.implementation_note)
    append_event(
        record,
        action="transition",
        role=args.role,
        from_state=before,
        note=args.note,
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_append_evidence(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in AGENT_ROLES:
        raise WorkRecordError("evidence role must be a governed agent role")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("the source role cannot mutate evidence after creating a pending handoff")
    if not EVIDENCE_ID.fullmatch(args.evidence_id):
        raise WorkRecordError("evidence ID must start with EV-")
    if any(item["evidenceId"] == args.evidence_id for item in record["evidenceRefs"]):
        raise WorkRecordError(f"evidence ID already exists: {args.evidence_id}")
    path = evidence_path(root, args.record_id, args.evidence_id)
    if path.exists():
        raise WorkRecordError(f"evidence file already exists: {path}")
    if not args.artifact_path or not args.artifact_sha256:
        raise WorkRecordError("evidence requires an existing --artifact-path and --artifact-sha256")
    artifact_path = safe_relative_path(args.artifact_path)
    if not SHA256.fullmatch(args.artifact_sha256):
        raise WorkRecordError("artifact SHA-256 must be 64 lowercase hexadecimal characters")
    artifact = _resolve_record_relative(record_directory(root, args.record_id), root, artifact_path)
    if not artifact.is_file() or file_hash(artifact) != args.artifact_sha256:
        raise WorkRecordError("evidence artifact is missing or its SHA-256 does not match")
    if args.completeness == "complete" and args.artifact_sha256 == ZERO_BYTE_SHA256:
        raise WorkRecordError("an empty artifact cannot support complete evidence")
    ephemeral_segments = {".cache", ".sf", ".sfdx", "node_modules", "output", "tmp", "temp"}
    if args.durability == "durable" and any(
        part.lower() in ephemeral_segments for part in Path(artifact_path).parts
    ):
        raise WorkRecordError("cache, tool-state, dependency, and output artifacts cannot be durable")
    timestamp = utc_now()
    retrieved_at = args.retrieved_at or timestamp
    evidence = {
        "schemaVersion": 1,
        "receiptType": "bound-artifact",
        "evidenceId": args.evidence_id,
        "recordId": args.record_id,
        "recordedAt": timestamp,
        "recordedBy": args.role,
        "type": args.evidence_type,
        "sourceRef": args.source_ref,
        "sourceRevision": args.source_revision,
        "retrievedAt": retrieved_at,
        "completeness": args.completeness,
        "durability": args.durability,
        "summary": args.summary,
        "artifact": {"path": artifact_path, "sha256": args.artifact_sha256},
    }
    validate_schema(
        evidence,
        contract_schema(root, "work-evidence.schema.json"),
        "work evidence",
    )
    atomic_write_json(path, evidence)
    reference = {
        "evidenceId": args.evidence_id,
        "path": f"evidence/{args.evidence_id}.json",
        "sha256": file_hash(path),
        "type": args.evidence_type,
        "completeness": args.completeness,
        "durability": args.durability,
        "sourceRef": args.source_ref,
        "sourceRevision": args.source_revision,
        "retrievedAt": retrieved_at,
    }
    record["evidenceRefs"].append(reference)
    before = deepcopy(record["state"])
    append_event(
        record,
        action="append-evidence",
        role=args.role,
        from_state=before,
        note=f"Appended evidence {args.evidence_id} ({args.completeness}, {args.durability}).",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_attach_rule(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role != "solution-designer":
        raise WorkRecordError("only solution-designer may attach applicable Principle rules")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before changing grounding")
    reference = resolved_rule_ref(root, args.rule_id)
    by_id = {item["ruleId"]: item for item in record["ruleRefs"]}
    by_id[args.rule_id] = reference
    record["ruleRefs"] = sorted(by_id.values(), key=lambda item: item["ruleId"])
    before = deepcopy(record["state"])
    timestamp = utc_now()
    record["groundingHash"] = grounding_hash(record)
    append_event(
        record,
        action="attach-rule",
        role=args.role,
        from_state=before,
        note=f"Attached active Principle {args.rule_id}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_bind_claim(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role != "solution-designer":
        raise WorkRecordError("only solution-designer may bind verified Knowledge claims")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before changing grounding")
    if current_approval(record) is not None or state_pair(record) not in {
        ("intake", "draft"),
        ("intake", "incomplete"),
        ("intake", "blocked"),
        ("design", "draft"),
        ("design", "awaiting_human"),
        ("design", "incomplete"),
        ("design", "blocked"),
    }:
        raise WorkRecordError("Knowledge grounding can change only before human design approval")

    reference = resolved_claim_ref(root, args.claim_id)
    replaced_claim_id: str | None = None
    if reference["claimType"] == "object-ownership":
        subject = reference["subject"]
        assertion = reference["assertion"]
        asserted_ownership = assertion.get("value")
        if (
            subject.get("kind") != "object"
            or assertion.get("predicate") != "ownership-classification"
            or not isinstance(asserted_ownership, str)
            or asserted_ownership not in {"package-owned", "subscriber-owned", "platform"}
        ):
            raise WorkRecordError("object-ownership claim has an invalid structural assertion")
        matches = [
            component
            for component in record["scope"]["components"]
            if component["name"] == subject.get("identity")
            and component["type"].lower() in {"customobject", "object"}
        ]
        if len(matches) != 1:
            raise WorkRecordError(
                "object-ownership claim must identify exactly one scoped CustomObject"
            )
        component = matches[0]
        replaced_claim_id = component.get("ownershipClaimRef")
        if replaced_claim_id and replaced_claim_id != args.claim_id and any(
            question.get("status") == "resolved"
            and question.get("resolutionRef") == replaced_claim_id
            for question in record["blockingQuestions"]
        ):
            raise WorkRecordError(
                "cannot replace an ownership claim used to resolve a blocking question"
            )
        ownership = asserted_ownership
        claim_scope = reference["scope"]
        if ownership == "package-owned":
            namespace = claim_scope.get("packageNamespace")
            version = claim_scope.get("packageVersion")
            if not namespace or not version:
                raise WorkRecordError(
                    "package-owned claim must bind package namespace and version"
                )
        else:
            if any(
                claim_scope.get(field) is not None
                for field in ("packageNamespace", "packageKey", "packageVersion")
            ):
                raise WorkRecordError(
                    "non-package ownership claim cannot bind package identity"
                )
            namespace = None
            version = None
        component.update(
            {
                "ownership": ownership,
                "ownershipClaimRef": args.claim_id,
                "packageNamespace": namespace,
                "packageVersion": version,
            }
        )

    by_id = {item["claimId"]: item for item in record["claimRefs"]}
    if replaced_claim_id and replaced_claim_id != args.claim_id:
        by_id.pop(replaced_claim_id, None)
    by_id[args.claim_id] = reference
    record["claimRefs"] = sorted(by_id.values(), key=lambda item: item["claimId"])
    record["scopeHash"] = scope_hash(record["scope"])
    before = deepcopy(record["state"])
    timestamp = utc_now()
    record["groundingHash"] = grounding_hash(record)
    append_event(
        record,
        action="bind-claim",
        role=args.role,
        from_state=before,
        note=f"Bound effective Knowledge claim {args.claim_id}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_add_question(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in {"solution-designer", "config-investigator"}:
        raise WorkRecordError("role may not add a design blocking question")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before adding a question")
    if any(item["id"] == args.question_id for item in record["blockingQuestions"]):
        raise WorkRecordError(f"blocking question already exists: {args.question_id}")
    before = deepcopy(record["state"])
    timestamp = utc_now()
    record["blockingQuestions"].append(
        {
            "id": args.question_id,
            "question": args.question,
            "owner": args.owner,
            "status": "open",
            "resolutionRef": None,
        }
    )
    append_event(
        record,
        action="add-question",
        role=args.role,
        from_state=before,
        note=f"Added blocking question {args.question_id}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_resolve_question(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role != "solution-designer":
        raise WorkRecordError("only solution-designer may bind a sourced question resolution")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before resolving a question")
    question = next(
        (item for item in record["blockingQuestions"] if item["id"] == args.question_id),
        None,
    )
    if question is None or question["status"] != "open":
        raise WorkRecordError("blocking question is missing or already resolved")
    valid_refs = {item["claimId"] for item in record["claimRefs"]} | {
        item["evidenceId"] for item in record["evidenceRefs"]
    }
    if args.resolution_ref not in valid_refs:
        raise WorkRecordError("question resolution must cite a bound claim or evidence ID")
    before = deepcopy(record["state"])
    timestamp = utc_now()
    question["status"] = "resolved"
    question["resolutionRef"] = args.resolution_ref
    append_event(
        record,
        action="resolve-question",
        role=args.role,
        from_state=before,
        note=f"Resolved blocking question {args.question_id} with {args.resolution_ref}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_capture_repository(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in {
        "solution-designer",
        "development-assistant",
        "test-strategist",
        "guardrail-reviewer",
    }:
        raise WorkRecordError("role may not capture repository lineage")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before capturing repository state")
    existing = next(
        (item for item in record["repositories"] if item["workspaceRoot"] == args.workspace_root),
        None,
    )
    if existing is None and args.role != "solution-designer":
        raise WorkRecordError("solution-designer must capture the immutable base commit first")
    captured = repository_state(root, args.workspace_root)
    captured["baseCommit"] = existing["baseCommit"] if existing else captured["headCommit"]
    if existing and (
        existing["remote"] != captured["remote"]
        or existing["branch"] != captured["branch"]
    ):
        raise WorkRecordError("repository remote or branch changed after the base snapshot")
    remaining = [
        item for item in record["repositories"] if item["workspaceRoot"] != args.workspace_root
    ]
    record["repositories"] = sorted(
        [*remaining, captured], key=lambda item: item["workspaceRoot"]
    )
    before = deepcopy(record["state"])
    timestamp = utc_now()
    record["groundingHash"] = grounding_hash(record)
    append_event(
        record,
        action="capture-repository",
        role=args.role,
        from_state=before,
        note=f"Captured {args.workspace_root} at {captured['headCommit']}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def command_capture_org_review(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in {
        "solution-designer",
        "config-investigator",
        "guardrail-reviewer",
    }:
        raise WorkRecordError("role may not persist Salesforce review evidence")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before capturing org evidence")
    alias = record["environment"].get("alias")
    if not alias:
        raise WorkRecordError("record has no configured Salesforce alias")
    org_entry, _ = configured_org(root, alias)
    tool = {
        "identity": "review_org_identity",
        "packages": "review_installed_packages",
        "object": "review_object_contract",
    }[args.review_type]
    arguments: dict[str, Any] = {}
    if args.review_type == "object":
        if not args.object_api_name:
            raise WorkRecordError("object review requires --object-api-name")
        arguments["objectApiName"] = args.object_api_name
    elif args.object_api_name:
        raise WorkRecordError("--object-api-name is valid only for object review")
    envelope = call_salesforce_review_facade(root, alias, tool, arguments)
    if envelope.get("target", {}).get("environment") != org_entry.get("environment"):
        raise WorkRecordError("Salesforce review receipt targets the wrong configured environment")
    evidence_id = f"EV-SF-{envelope['reviewType'].upper().replace('-', '_')}-{envelope['runId']}"
    path = evidence_path(root, args.record_id, evidence_id)
    if path.exists():
        raise WorkRecordError("Salesforce review evidence ID already exists")
    atomic_write_json(path, envelope)
    reference = {
        "evidenceId": evidence_id,
        "path": f"evidence/{evidence_id}.json",
        "sha256": file_hash(path),
        "type": {
            "org-identity": "salesforce-org-identity",
            "installed-packages": "salesforce-installed-packages",
            "object-contract": "salesforce-object-contract",
        }[envelope["reviewType"]],
        "completeness": "complete" if envelope["status"] == "VERIFIED" else "partial",
        "durability": "durable",
        "sourceRef": f"salesforce-review-facade:{tool}",
        "sourceRevision": envelope["sha256"],
        "retrievedAt": envelope["generatedAt"],
    }
    record["evidenceRefs"].append(reference)
    if envelope["reviewType"] == "org-identity":
        if (
            envelope["status"] == "VERIFIED"
            and envelope.get("facts", {}).get("isSandbox") is True
            and envelope.get("target", {}).get("isSandbox") is True
        ):
            record["environment"] = {
                "status": "verified",
                "alias": alias,
                "isSandbox": envelope["facts"]["isSandbox"],
                "verificationRef": reference["path"],
                "verifiedAt": envelope["generatedAt"],
            }
        else:
            record["environment"] = {
                "status": "unverified",
                "alias": alias,
                "isSandbox": None,
                "verificationRef": None,
                "verifiedAt": None,
            }
    before = deepcopy(record["state"])
    timestamp = utc_now()
    append_event(
        record,
        action="capture-org-review",
        role=args.role,
        from_state=before,
        note=f"Captured {envelope['reviewType']} receipt {evidence_id} with status {envelope['status']}.",
        at=timestamp,
    )
    bump(record, timestamp)
    result = persist_record(root, record)
    result.update(
        {
            "evidenceId": evidence_id,
            "salesforceReviewStatus": envelope["status"],
            "reconciliation": envelope["reconciliation"]["status"],
        }
    )
    return result


def command_run_verification(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in {"development-assistant", "test-strategist", "guardrail-reviewer"}:
        raise WorkRecordError("role may not execute a fixed verification profile")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("consume the pending handoff before verification")
    if current_approval(record) is None:
        raise WorkRecordError("verification requires the current human-approved design")
    receipt = execute_verification_profile(root, record, args.role, args.profile_id)
    evidence_id = f"EV-{receipt['verificationId']}"
    path = evidence_path(root, args.record_id, evidence_id)
    atomic_write_json(path, receipt)
    reference = {
        "evidenceId": evidence_id,
        "path": f"evidence/{evidence_id}.json",
        "sha256": file_hash(path),
        "type": f"verification:{receipt['profileId']}",
        "completeness": "complete"
        if receipt["status"] in {"passed", "failed"}
        else "partial",
        "durability": "durable",
        "sourceRef": f"verification-policy:{receipt['profileId']}",
        "sourceRevision": receipt["policySha256"],
        "retrievedAt": receipt["completedAt"],
    }
    record["evidenceRefs"].append(reference)
    record["verification"].append(
        {
            "verificationId": receipt["verificationId"],
            "profileId": receipt["profileId"],
            "performedAt": receipt["completedAt"],
            "role": args.role,
            "status": receipt["status"],
            "evidenceRef": reference["path"],
            "receiptSha256": reference["sha256"],
            "repositoryHeadCommit": receipt["repositoryHeadCommit"],
        }
    )
    before = deepcopy(record["state"])
    timestamp = utc_now()
    append_event(
        record,
        action="run-verification",
        role=args.role,
        from_state=before,
        note=f"Verification profile {args.profile_id} finished with {receipt['status']}.",
        at=timestamp,
    )
    bump(record, timestamp)
    result = persist_record(root, record)
    result.update(
        {
            "verificationId": receipt["verificationId"],
            "verificationStatus": receipt["status"],
            "evidenceId": evidence_id,
        }
    )
    return result


def _required_reads(root: Path, record: dict[str, Any], values: Iterable[str]) -> list[dict[str, Any]]:
    directory = record_directory(root, record["recordId"])
    requested = [
        record["design"]["path"],
        *(item["path"] for item in record.get("claimRefs", [])),
        *values,
    ]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in requested:
        normalized = safe_relative_path(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        path = _resolve_record_relative(directory, root, normalized)
        if not path.is_file():
            raise WorkRecordError(f"required-read path is missing: {normalized}")
        result.append({"path": normalized, "sha256": file_hash(path)})
    return result


def _selected_evidence(record: dict[str, Any], requested: Sequence[str]) -> list[dict[str, Any]]:
    by_id = {item["evidenceId"]: item for item in record["evidenceRefs"]}
    ids = list(requested) if requested else list(by_id)
    missing = sorted(set(ids) - set(by_id))
    if missing:
        raise WorkRecordError(f"unknown evidence IDs: {', '.join(missing)}")
    return [deepcopy(by_id[item]) for item in ids]


def _handoff_target_allowed(record: dict[str, Any], from_role: str, to_role: str) -> bool:
    pair = state_pair(record)
    if from_role == to_role:
        return False
    if to_role == "development-assistant":
        return pair in {("design", "accepted"), ("review", "needs_fixes"), ("review", "incomplete")}
    if to_role == "guardrail-reviewer":
        return pair[0] == "design" or pair == ("review", "ready")
    if to_role == "config-investigator":
        return pair[0] in {"intake", "design", "development", "qa"}
    if to_role == "test-strategist":
        return pair[0] in {"design", "development", "qa"}
    if to_role == "solution-designer":
        return pair != ("complete", "complete")
    if to_role == "human":
        return pair != ("complete", "complete")
    return False


def command_create_handoff(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.from_role not in AGENT_ROLES or args.to_role not in HANDOFF_ROLES:
        raise WorkRecordError("handoff roles are not governed roles")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("record already has a pending handoff")
    if not _handoff_target_allowed(record, args.from_role, args.to_role):
        raise WorkRecordError("handoff target is not allowed from the current state")
    handoff_id = args.handoff_id or identifier("HO")
    if not HANDOFF_ID.fullmatch(handoff_id):
        raise WorkRecordError("invalid handoff ID")
    path = handoff_path(root, args.record_id, handoff_id)
    if path.exists():
        raise WorkRecordError(f"handoff already exists: {handoff_id}")
    selected_evidence = _selected_evidence(record, args.evidence_id or [])
    open_questions = open_question_ids(record)
    completeness = "partial" if open_questions or any(
        item["completeness"] != "complete" for item in selected_evidence
    ) else args.completeness
    expected_next = None
    if args.next_phase or args.next_status:
        if not args.next_phase or not args.next_status:
            raise WorkRecordError("--next-phase and --next-status must be supplied together")
        expected_pair = (args.next_phase, args.next_status)
        if expected_pair not in VALID_STATE_PAIRS:
            raise WorkRecordError("expected next state is invalid")
        expected_next = state_object(expected_pair)

    timestamp = utc_now()
    before = deepcopy(record["state"])
    record["currentHandoffId"] = handoff_id
    append_event(
        record,
        action="create-handoff",
        role=args.from_role,
        from_state=before,
        note=f"Created handoff {handoff_id} to {args.to_role}.",
        at=timestamp,
    )
    bump(record, timestamp)
    validate_schema(record, RECORD_SCHEMA, "change record")
    validate_record_semantics(root, record)
    resulting_record_hash = json_hash(record)
    handoff = {
        "schemaVersion": 2,
        "handoffId": handoff_id,
        "recordId": args.record_id,
        "recordRevision": record["recordRevision"],
        "recordHash": resulting_record_hash,
        "status": "pending",
        "fromRole": args.from_role,
        "toRole": args.to_role,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "reason": args.reason,
        "summary": args.summary,
        "state": deepcopy(record["state"]),
        "expectedNextState": expected_next,
        "scope": deepcopy(record["scope"]),
        "scopeHash": record["scopeHash"],
        "designHash": record["design"]["sha256"],
        "groundingHash": record["groundingHash"],
        "ruleRefs": deepcopy(record["ruleRefs"]),
        "claimRefs": deepcopy(record["claimRefs"]),
        "requiredReads": _required_reads(root, record, args.required_read or []),
        "evidenceRefs": selected_evidence,
        "repositories": deepcopy(record["repositories"]),
        "unresolvedQuestions": open_questions,
        "requiredActions": list(args.required_action or []),
        "prohibitedActions": list(args.prohibited_action or []),
        "completeness": completeness,
        "consumedAt": None,
        "consumedBy": None,
        "consumedRecordRevision": None,
    }
    validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
    atomic_write_json(path, handoff)
    atomic_write_json(record_path(root, args.record_id), record)
    result = summary(record)
    result.update({"handoffId": handoff_id, "handoffHash": json_hash(handoff)})
    return result


def command_accept_handoff(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role not in AGENT_ROLES:
        raise WorkRecordError("handoff consumer must be a governed agent role")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"] != args.handoff_id:
        raise WorkRecordError("handoff is not the record's current handoff")
    path = handoff_path(root, args.record_id, args.handoff_id)
    handoff = load_json(path)
    validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
    actual_handoff_hash = json_hash(handoff)
    if actual_handoff_hash != args.expected_handoff_hash:
        raise WorkRecordError(
            f"stale handoff hash: expected {args.expected_handoff_hash}, current is {actual_handoff_hash}"
        )
    if handoff["status"] != "pending":
        raise WorkRecordError("handoff is not pending")
    if handoff["toRole"] != args.role:
        raise WorkRecordError("handoff is addressed to another role")
    if handoff["recordRevision"] != record["recordRevision"] or handoff["recordHash"] != json_hash(record):
        raise WorkRecordError("handoff is stale relative to the current record")
    if (
        handoff["scope"] != record["scope"]
        or scope_hash(handoff["scope"]) != handoff["scopeHash"]
        or handoff["scopeHash"] != record["scopeHash"]
        or handoff["designHash"] != record["design"]["sha256"]
        or handoff["groundingHash"] != record["groundingHash"]
        or handoff["ruleRefs"] != record["ruleRefs"]
        or handoff["claimRefs"] != record["claimRefs"]
    ):
        raise WorkRecordError("handoff grounding, scope, or design no longer matches the record")

    timestamp = utc_now()
    before = deepcopy(record["state"])
    record["currentHandoffId"] = None
    history_ref = f"handoffs/{args.handoff_id}.json"
    if history_ref not in record["handoffHistoryRefs"]:
        record["handoffHistoryRefs"].append(history_ref)
    append_event(
        record,
        action="accept-handoff",
        role=args.role,
        from_state=before,
        note=f"Consumed handoff {args.handoff_id} from {handoff['fromRole']}.",
        at=timestamp,
    )
    bump(record, timestamp)
    handoff["status"] = "consumed"
    handoff["updatedAt"] = timestamp
    handoff["consumedAt"] = timestamp
    handoff["consumedBy"] = args.role
    handoff["consumedRecordRevision"] = record["recordRevision"]
    validate_schema(handoff, HANDOFF_SCHEMA, "handoff")
    validate_schema(record, RECORD_SCHEMA, "change record")
    validate_record_semantics(root, record)
    atomic_write_json(path, handoff)
    atomic_write_json(record_path(root, args.record_id), record)
    result = summary(record)
    result.update({"acceptedHandoffId": args.handoff_id, "handoffHash": json_hash(handoff)})
    return result


def command_append_review(args: argparse.Namespace) -> dict[str, Any]:
    root = data_root(args.root)
    if args.role != "guardrail-reviewer":
        raise WorkRecordError("only guardrail-reviewer may append the independent review")
    record = load_record(root, args.record_id)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("guardrail-reviewer must consume the pending handoff before reviewing")
    if state_pair(record) != ("review", "ready"):
        raise WorkRecordError("formal review is allowed only from review/ready")
    if current_approval(record) is None:
        raise WorkRecordError("formal review requires the current human-approved design")
    if args.verdict == "SAFE":
        if open_question_ids(record):
            raise WorkRecordError("SAFE is forbidden while a blocking question remains open")
        if not record["evidenceRefs"]:
            raise WorkRecordError("SAFE requires evidence")
        if any(item["completeness"] != "complete" for item in record["evidenceRefs"]):
            raise WorkRecordError("SAFE is forbidden with partial evidence")
        if not any(
            item["durability"] == "durable" and item["completeness"] == "complete"
            for item in record["evidenceRefs"]
        ):
            raise WorkRecordError("SAFE requires at least one durable complete evidence reference")
        environment = record["environment"]
        if not (
            environment["status"] == "verified"
            and environment["isSandbox"] is True
            and environment["verificationRef"]
        ):
            raise WorkRecordError("SAFE requires verified sandbox evidence")
        if not any(item["status"] == "passed" for item in record["verification"]):
            raise WorkRecordError("SAFE requires passed verification evidence")
    target_status = {
        "SAFE": "safe",
        "NEEDS_FIXES": "needs_fixes",
        "INCOMPLETE": "incomplete",
        "STOPPED": "stopped",
    }[args.verdict]
    timestamp = utc_now()
    before = deepcopy(record["state"])
    record["review"] = {
        "reviewId": args.review_id or identifier("RV"),
        "reviewedAt": timestamp,
        "role": "guardrail-reviewer",
        "verdict": args.verdict,
        "findings": list(args.finding or []),
    }
    record["state"] = {"phase": "review", "status": target_status}
    append_event(
        record,
        action="append-review",
        role="guardrail-reviewer",
        from_state=before,
        note=f"Recorded independent verdict {args.verdict}.",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def _assert_not_agent_context() -> None:
    """In-process SAFE-HUMAN-001 backstop: refuse approval when ``SF_HARNESS_AGENT_CONTEXT`` is set.

    The role guard denies `approve` to every custom agent and the global safety hook blocks it
    from the default Copilot terminal; both are string matchers a renamed invocation could evade.
    This check adds a matcher-independent layer, but it is ONLY active once the agent runner
    exports ``SF_HARNESS_AGENT_CONTEXT``. Until a runner is wired to set it (see
    HANDOFF_FOR_FABLE_CHECKER.md), this provides no runtime protection on its own.
    """

    if os.environ.get("SF_HARNESS_AGENT_CONTEXT", "").strip():
        raise WorkRecordError(
            "SAFE-HUMAN-001: work-record approval cannot run inside an agent context; "
            "a named human must run it directly in an unmanaged terminal."
        )


def command_approve(args: argparse.Namespace) -> dict[str, Any]:
    """Human-only command; role guards must deny this subcommand to every agent."""

    _assert_not_agent_context()
    root = data_root(args.root)
    record = load_record(root, args.record_id, check_design=False)
    check_expected(record, args.expected_revision, args.expected_record_hash)
    if record["currentHandoffId"]:
        raise WorkRecordError("resolve the pending handoff before approval")
    if state_pair(record) != ("design", "awaiting_human"):
        raise WorkRecordError("human design approval is allowed only from design/awaiting_human")
    if open_question_ids(record):
        raise WorkRecordError("human approval is blocked by unresolved blocking questions")
    if not record["ruleRefs"] or not {"kernel", "1", "2", "3"}.issubset(
        {item["tier"] for item in record["ruleRefs"]}
    ):
        raise WorkRecordError("human approval requires applicable rules from kernel and Tiers 1-3")
    if not record["claimRefs"]:
        raise WorkRecordError("human approval requires at least one fresh verified Knowledge claim")
    validate_claim_refs(root, record["claimRefs"], require_current=True)
    bound_claims = {item["claimId"] for item in record["claimRefs"]}
    if any(
        component["ownership"] == "unknown"
        or component["ownershipClaimRef"] not in bound_claims
        for component in record["scope"]["components"]
    ):
        raise WorkRecordError("human approval requires claim-backed component ownership")
    repository = next(
        (
            item
            for item in record["repositories"]
            if item["workspaceRoot"] == record["scope"]["workspaceRoot"]
        ),
        None,
    )
    if repository is None or repository["dirtyPaths"] or not repository_snapshot_current(root, repository):
        raise WorkRecordError("human approval requires a current clean base repository snapshot")
    evidence_by_path = load_bound_evidence(root, record)
    assert_fresh_environment_receipt(root, record, evidence_by_path)
    if not any(
        reference["durability"] == "durable"
        and reference["completeness"] == "complete"
        and evidence.get("receiptType") == "bound-artifact"
        for reference, evidence in evidence_by_path.values()
    ):
        raise WorkRecordError(
            "human approval requires durable complete evidence bound to an existing artifact"
        )
    directory = record_directory(root, args.record_id)
    design = _resolve_record_relative(directory, root, record["design"]["path"])
    actual_design_hash = file_hash(design)
    if actual_design_hash != args.expected_design_hash:
        raise WorkRecordError(
            f"design hash differs from the human-reviewed hash: expected {args.expected_design_hash}, current {actual_design_hash}"
        )
    record["design"]["sha256"] = actual_design_hash
    if args.mechanism == "github-review" and not args.approval_ref.startswith("https://github.com/"):
        raise WorkRecordError("github-review mechanism requires an https://github.com/ approval reference")
    timestamp = utc_now()
    before = deepcopy(record["state"])
    record["approvals"].append(
        {
            "approvalId": args.approval_id or identifier("AP"),
            "kind": "design",
            "approver": args.approver,
            "approvedAt": timestamp,
            "mechanism": args.mechanism,
            "approvalRef": args.approval_ref,
            "scopeHash": record["scopeHash"],
            "designHash": actual_design_hash,
            "groundingHash": record["groundingHash"],
            "status": "active",
            "invalidatedAt": None,
            "invalidationReason": None,
        }
    )
    record["state"] = {"phase": "design", "status": "accepted"}
    append_event(
        record,
        action="approve",
        role="human",
        from_state=before,
        note=f"Human approval recorded through {args.mechanism}: {args.approval_ref}",
        at=timestamp,
    )
    bump(record, timestamp)
    return persist_record(root, record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="workspace data root; defaults to the brain-core repository")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="initialize a governed record and narrative design")
    init.add_argument("--record-id", required=True)
    init.add_argument("--organization", required=True)
    init.add_argument("--project", required=True)
    init.add_argument("--work-item-id", required=True, type=int)
    init.add_argument("--work-item-type", required=True)
    init.add_argument("--work-item-url")
    init.add_argument("--work-item-revision", type=int)
    init.add_argument("--fetched-at")
    init.add_argument("--title", required=True)
    init.add_argument("--requested-outcome", required=True)
    init.add_argument("--workspace-root", choices=["brain-core"], default="brain-core")
    init.add_argument(
        "--component",
        action="append",
        help='JSON object with name and type; ownership is derived later from verified Knowledge',
    )
    init.add_argument("--path", action="append")
    init.add_argument("--environment-alias")
    init.add_argument("--rule-id", action="append")
    init.set_defaults(func=command_init)

    validate = subparsers.add_parser("validate", help="validate record, design, evidence, and handoffs")
    validate.add_argument("--record-id", required=True)
    validate.set_defaults(func=command_validate)

    context = subparsers.add_parser("context", help="return a bounded role context manifest")
    context.add_argument("--record-id", required=True)
    context.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    context.add_argument("--handoff-id")
    context.set_defaults(func=command_context)

    transition = subparsers.add_parser("transition", help="perform an authorized state transition")
    transition.add_argument("--record-id", required=True)
    transition.add_argument("--expected-revision", required=True, type=int)
    transition.add_argument("--expected-record-hash", required=True)
    transition.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    transition.add_argument("--phase", required=True)
    transition.add_argument("--status", required=True)
    transition.add_argument("--note", required=True)
    transition.add_argument("--file-changed", action="append")
    transition.add_argument("--implementation-note", action="append")
    transition.set_defaults(func=command_transition)

    evidence = subparsers.add_parser("append-evidence", help="append a sourced evidence envelope")
    evidence.add_argument("--record-id", required=True)
    evidence.add_argument("--expected-revision", required=True, type=int)
    evidence.add_argument("--expected-record-hash", required=True)
    evidence.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    evidence.add_argument("--evidence-id", required=True)
    evidence.add_argument("--evidence-type", required=True)
    evidence.add_argument("--source-ref", required=True)
    evidence.add_argument("--source-revision")
    evidence.add_argument("--retrieved-at")
    evidence.add_argument("--completeness", required=True, choices=["complete", "partial"])
    evidence.add_argument("--durability", required=True, choices=["durable", "ephemeral"])
    evidence.add_argument("--summary", required=True)
    evidence.add_argument("--artifact-path", required=True)
    evidence.add_argument("--artifact-sha256", required=True)
    evidence.set_defaults(func=command_append_evidence)

    attach_rule = subparsers.add_parser("attach-rule", help="bind an active canonical Principle rule")
    attach_rule.add_argument("--record-id", required=True)
    attach_rule.add_argument("--expected-revision", required=True, type=int)
    attach_rule.add_argument("--expected-record-hash", required=True)
    attach_rule.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    attach_rule.add_argument("--rule-id", required=True)
    attach_rule.set_defaults(func=command_attach_rule)

    bind_claim = subparsers.add_parser(
        "bind-claim",
        help="bind one currently effective Knowledge claim and derive object ownership",
    )
    bind_claim.add_argument("--record-id", required=True)
    bind_claim.add_argument("--expected-revision", required=True, type=int)
    bind_claim.add_argument("--expected-record-hash", required=True)
    bind_claim.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    bind_claim.add_argument("--claim-id", required=True)
    bind_claim.set_defaults(func=command_bind_claim)

    add_question = subparsers.add_parser("add-question", help="persist an unresolved blocking question")
    add_question.add_argument("--record-id", required=True)
    add_question.add_argument("--expected-revision", required=True, type=int)
    add_question.add_argument("--expected-record-hash", required=True)
    add_question.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    add_question.add_argument("--question-id", required=True)
    add_question.add_argument("--question", required=True)
    add_question.add_argument("--owner", required=True)
    add_question.set_defaults(func=command_add_question)

    resolve_question = subparsers.add_parser(
        "resolve-question", help="resolve a blocking question with a bound claim/evidence ID"
    )
    resolve_question.add_argument("--record-id", required=True)
    resolve_question.add_argument("--expected-revision", required=True, type=int)
    resolve_question.add_argument("--expected-record-hash", required=True)
    resolve_question.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    resolve_question.add_argument("--question-id", required=True)
    resolve_question.add_argument("--resolution-ref", required=True)
    resolve_question.set_defaults(func=command_resolve_question)

    repository = subparsers.add_parser(
        "capture-repository", help="capture an actual Git base/head/dirty-state receipt"
    )
    repository.add_argument("--record-id", required=True)
    repository.add_argument("--expected-revision", required=True, type=int)
    repository.add_argument("--expected-record-hash", required=True)
    repository.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    repository.add_argument("--workspace-root", required=True, choices=["brain-core"])
    repository.set_defaults(func=command_capture_repository)

    org_review = subparsers.add_parser(
        "capture-org-review", help="persist a normalized fixed-profile MCP plus CLI receipt"
    )
    org_review.add_argument("--record-id", required=True)
    org_review.add_argument("--expected-revision", required=True, type=int)
    org_review.add_argument("--expected-record-hash", required=True)
    org_review.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    org_review.add_argument("--review-type", required=True, choices=["identity", "packages", "object"])
    org_review.add_argument("--object-api-name")
    org_review.set_defaults(func=command_capture_org_review)

    verification = subparsers.add_parser(
        "run-verification", help="execute one human-configured fixed verification profile"
    )
    verification.add_argument("--record-id", required=True)
    verification.add_argument("--expected-revision", required=True, type=int)
    verification.add_argument("--expected-record-hash", required=True)
    verification.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    verification.add_argument("--profile-id", required=True)
    verification.set_defaults(func=command_run_verification)

    create = subparsers.add_parser("create-handoff", help="persist a role handoff")
    create.add_argument("--record-id", required=True)
    create.add_argument("--expected-revision", required=True, type=int)
    create.add_argument("--expected-record-hash", required=True)
    create.add_argument("--handoff-id")
    create.add_argument("--from-role", required=True, choices=sorted(AGENT_ROLES))
    create.add_argument("--to-role", required=True, choices=sorted(HANDOFF_ROLES))
    create.add_argument("--reason", required=True)
    create.add_argument("--summary", required=True)
    create.add_argument("--required-read", action="append")
    create.add_argument("--evidence-id", action="append")
    create.add_argument("--required-action", action="append")
    create.add_argument("--prohibited-action", action="append")
    create.add_argument("--completeness", choices=["complete", "partial"], default="complete")
    create.add_argument("--next-phase")
    create.add_argument("--next-status")
    create.set_defaults(func=command_create_handoff)

    accept = subparsers.add_parser("accept-handoff", help="consume the current persisted handoff")
    accept.add_argument("--record-id", required=True)
    accept.add_argument("--expected-revision", required=True, type=int)
    accept.add_argument("--expected-record-hash", required=True)
    accept.add_argument("--handoff-id", required=True)
    accept.add_argument("--expected-handoff-hash", required=True)
    accept.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    accept.set_defaults(func=command_accept_handoff)

    review = subparsers.add_parser("append-review", help="append an independent formal verdict")
    review.add_argument("--record-id", required=True)
    review.add_argument("--expected-revision", required=True, type=int)
    review.add_argument("--expected-record-hash", required=True)
    review.add_argument("--role", required=True, choices=sorted(AGENT_ROLES))
    review.add_argument("--review-id")
    review.add_argument("--verdict", required=True, choices=["SAFE", "NEEDS_FIXES", "INCOMPLETE", "STOPPED"])
    review.add_argument("--finding", action="append")
    review.set_defaults(func=command_append_review)

    approve = subparsers.add_parser(
        "approve",
        help="HUMAN-ONLY: bind approval to current scope and design hashes; agent guards must deny",
    )
    approve.add_argument("--record-id", required=True)
    approve.add_argument("--expected-revision", required=True, type=int)
    approve.add_argument("--expected-record-hash", required=True)
    approve.add_argument("--expected-design-hash", required=True)
    approve.add_argument("--approval-id")
    approve.add_argument("--approver", required=True)
    approve.add_argument("--mechanism", required=True, choices=["human-terminal", "github-review"])
    approve.add_argument("--approval-ref", required=True)
    approve.set_defaults(func=command_approve)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except WorkRecordError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", **result}, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
