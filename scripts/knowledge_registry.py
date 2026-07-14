#!/usr/bin/env python3
"""Validate and manage schema-v3 Knowledge records without external system access."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.knowledge_registry by unit tests
    from scripts.schema_format import FORMAT_CHECKER


DEFAULT_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_CLAIM_STATUSES = {"proposed", "verified", "stale", "contested"}
EFFECTIVE_CLAIM_STATUSES = {"verified"}
SCOPE_FIELDS = (
    "environment",
    "orgKey",
    "packageNamespace",
    "packageKey",
    "packageVersion",
    "repositoryCommit",
)


class ContractError(ValueError):
    """A deterministic Knowledge contract failure."""


DOMAIN_VIEWS: dict[str, tuple[str, str]] = {
    "current-implementation": (
        "Current Implementation",
        "Generated view of canonical claims describing implementation, package installation, and scoped\n"
        "runtime behavior. Do not hand-edit. Only current `verified` claims are established facts; every\n"
        "row must link to its canonical claim and evidence.",
    ),
    "business-processes": (
        "Business Processes",
        "Generated view of canonical business-process claims. Business meaning requires a named accountable\n"
        "SME or approved artifact; technical metadata alone cannot establish it. Do not hand-edit.",
    ),
    "object-relations": (
        "Object Relations",
        "Generated view of canonical relation claims, including lookup-to-reference-data patterns only\n"
        "after they are established from scoped evidence. Do not hand-edit or place illustrative examples\n"
        "in this live retrieval surface.",
    ),
    "object-descriptions": (
        "Object Descriptions",
        "Generated view of canonical object existence, ownership, and approved meaning claims. Namespace or\n"
        "appearance alone does not prove managed-package ownership. Do not hand-edit.",
    ),
    "field-descriptions": (
        "Field Descriptions",
        "Generated view of canonical field-schema and approved business-meaning claims. A describe result\n"
        "can establish accessible schema, but not business meaning by itself. Do not hand-edit.",
    ),
    "automation-map": (
        "Automation Map",
        "Generated view of canonical automation-inventory claims. Absence claims require complete\n"
        "enumeration, sufficient permissions, and all pages fetched. Do not hand-edit.",
    ),
    "integration-map": (
        "Integration Map",
        "Generated view of canonical integration and data-flow claims. Configuration evidence and business\n"
        "ownership evidence remain distinct. Do not hand-edit.",
    ),
    "glossary": (
        "Glossary",
        "Generated view of approved business-to-technical glossary claims. Preserve Polish business terms\n"
        "verbatim. A model suggestion is not evidence; a named SME or approved artifact is required.",
    ),
    "known-limitations": (
        "Known Limitations",
        "Generated view of canonical, version-scoped package-limitation claims. An observed behavior is not\n"
        "automatically a vendor constraint. A Principle change is a separate owner-reviewed operation in\n"
        "the rule registry. Do not hand-edit.",
    ),
    "component-inventory": (
        "Component Inventory",
        "Generated view of canonical component-inventory claims: every source-format metadata component\n"
        "(approval processes get richer automation claims; layouts, permission sets, custom metadata,\n"
        "labels, and any other type land here generically). Source existence only — business meaning,\n"
        "runtime behavior, and org state are not established by these claims. Do not hand-edit.",
    ),
}


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load YAML {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{path} must contain one YAML object")
    return data


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{path} must contain one JSON object")
    return data


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} is not a valid UTC date-time") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return parsed


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(value: Any) -> str:
    payload = canonical(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class KnowledgeRegistry:
    def __init__(self, root: Path, current_time: datetime | None = None):
        self.root = root.resolve()
        self.claims = self.root / ".ai/knowledge/claims"
        self.evidence = self.root / ".ai/knowledge/evidence"
        self.reviews = self.root / ".ai/knowledge/reviews"
        self.schemas = self.root / "schemas"
        self.policy_path = self.root / "config/knowledge-policy.json"
        self.registry_path = self.root / ".github/instructions/rule-registry.yaml"
        self.current_time = current_time

    def at_time(self, at: datetime | None = None) -> datetime:
        value = at or self.current_time or utc_now()
        if value.tzinfo is None:
            raise ContractError("effective time must include a timezone")
        return value.astimezone(timezone.utc)

    def contained_input(self, raw: str) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ContractError(f"input path escapes repository root: {raw}") from exc
        if not path.is_file():
            raise ContractError(f"input file does not exist: {raw}")
        return path

    def schema(self, filename: str) -> dict[str, Any]:
        schema = load_json(self.schemas / filename)
        Draft202012Validator.check_schema(schema)
        return schema

    def validate_data(self, data: dict[str, Any], schema_name: str, label: str) -> None:
        validator = Draft202012Validator(
            self.schema(schema_name), format_checker=FORMAT_CHECKER
        )
        errors = sorted(validator.iter_errors(data), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.path) or "<root>"
            raise ContractError(f"{label}: schema failure at {location}: {first.message}")

    def validate_scope(self, scope: dict[str, Any], label: str = "Knowledge scope") -> None:
        claim_schema = self.schema("knowledge-claim.schema.json")
        scope_schema = copy.deepcopy(claim_schema["properties"]["scope"])
        scope_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        errors = sorted(
            Draft202012Validator(scope_schema, format_checker=FORMAT_CHECKER).iter_errors(
                scope
            ),
            key=lambda item: list(item.path),
        )
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.path) or "<root>"
            raise ContractError(f"{label}: schema failure at {location}: {first.message}")

    def records(self, directory: Path) -> list[tuple[Path, dict[str, Any]]]:
        return [(path, load_yaml(path)) for path in sorted(directory.glob("*.yaml"))]

    def claim_path(self, claim_id: str) -> Path:
        return self.claims / f"{claim_id}.yaml"

    def evidence_path(self, evidence_id: str) -> Path:
        return self.evidence / f"{evidence_id}.yaml"

    def review_path(self, review_id: str) -> Path:
        return self.reviews / f"{review_id}.yaml"

    @staticmethod
    def evidence_manifest(evidence_records: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "evidenceId": str(record["evidenceId"]),
                "recordDigest": canonical_digest(record),
            }
            for record in sorted(evidence_records, key=lambda item: str(item["evidenceId"]))
        ]

    @classmethod
    def review_bindings(
        cls, claim: dict[str, Any], evidence_records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "claimDigest": canonical_digest(claim),
            "scopeDigest": canonical_digest(claim["scope"]),
            "evidenceManifest": cls.evidence_manifest(evidence_records),
        }

    @classmethod
    def verify_review_bindings(
        cls,
        review: dict[str, Any],
        claim: dict[str, Any],
        evidence_records: list[dict[str, Any]],
    ) -> None:
        cls.verify_audit_receipt(review)
        claim_evidence = sorted(str(ref) for ref in claim["evidenceRefs"])
        review_evidence = sorted(str(ref) for ref in review["evidenceRefs"])
        if review_evidence != claim_evidence:
            raise ContractError(
                "human review must bind the claim's exact evidence reference set"
            )
        expected = cls.review_bindings(claim, evidence_records)
        for field in ("claimDigest", "scopeDigest", "evidenceManifest"):
            if review[field] != expected[field]:
                raise ContractError(
                    f"human review {field} does not bind the exact pre-promotion record"
                )

    @staticmethod
    def verify_audit_receipt(review: dict[str, Any]) -> None:
        receipt = copy.deepcopy(review["auditReceipt"])
        supplied = receipt.pop("receiptDigest")
        expected = canonical_digest(receipt)
        if supplied != expected:
            raise ContractError(
                "human review auditReceipt digest does not bind its mechanism, reference, and verifiedAt"
            )

    @staticmethod
    def structured_fact(claim: dict[str, Any]) -> str:
        identity = str(claim["subject"]["identity"])
        value = claim["assertion"]["value"]
        if claim["claimType"] == "object-existence":
            verb = "exists" if value is True else "does not exist"
            return f"{identity} {verb} in the accessible schema."
        if claim["claimType"] == "package-installation":
            verb = "is installed" if value is True else "is not installed"
            return f"Package {identity} {verb}."
        if claim["claimType"] == "object-ownership":
            return f"{identity} ownership is classified as {value}."
        predicate = str(claim["assertion"]["predicate"])
        return f"{identity}: {predicate} = {canonical(value)}"

    @staticmethod
    def is_fresh(claim: dict[str, Any], at: datetime) -> bool:
        if claim["status"] != "verified":
            return False
        return parse_time(claim["verifiedAt"], "claim verifiedAt") <= at < parse_time(
            claim["reviewBy"], "claim reviewBy"
        )

    @staticmethod
    def verify_evidence_scope(claim: dict[str, Any], evidence: dict[str, Any]) -> None:
        claim_scope = claim["scope"]
        evidence_id = str(evidence["evidenceId"])

        if evidence["environment"] == "not-applicable":
            if evidence["orgKey"] is not None:
                raise ContractError(
                    f"{evidence_id}: not-applicable evidence must not name an org"
                )
        elif (
            evidence["environment"] != claim_scope["environment"]
            or evidence["orgKey"] != claim_scope["orgKey"]
        ):
            raise ContractError(f"{evidence_id}: environment or org scope mismatch")

        for field in (
            "packageNamespace",
            "packageKey",
            "packageVersion",
            "repositoryCommit",
        ):
            claim_value = claim_scope[field]
            evidence_value = evidence[field]
            if claim_value is not None or evidence_value is not None:
                if claim_value != evidence_value:
                    raise ContractError(f"{evidence_id}: {field} scope mismatch")

        if (
            evidence["sourceType"] == "metadata-repository"
            and claim_scope["repositoryCommit"] is None
        ):
            raise ContractError(
                f"{evidence_id}: repository evidence requires a repository-scoped claim"
            )

    @staticmethod
    def validate_temporal_claim(claim: dict[str, Any]) -> None:
        observed = parse_time(claim["observedAt"], "claim observedAt")
        review_by = parse_time(claim["reviewBy"], "claim reviewBy")
        if review_by <= observed:
            raise ContractError(
                f"{claim['claimId']}: reviewBy must be later than observedAt"
            )

    @staticmethod
    def validate_claim_references(
        claim: dict[str, Any], claim_by_id: dict[str, dict[str, Any]]
    ) -> None:
        claim_id = str(claim["claimId"])
        for field in ("supersedes", "contradicts", "relatedClaims"):
            refs = [str(ref) for ref in claim[field]]
            if claim_id in refs:
                raise ContractError(f"{claim_id}: {field} may not reference itself")
            missing = sorted(set(refs) - set(claim_by_id))
            if missing:
                raise ContractError(f"{claim_id}: missing {field} refs {missing}")
        superseded_by = claim.get("supersededBy")
        if superseded_by == claim_id:
            raise ContractError(f"{claim_id}: supersededBy may not reference itself")
        if superseded_by and superseded_by not in claim_by_id:
            raise ContractError(f"{claim_id}: missing supersededBy ref {superseded_by}")

    def validate_principles(self, principle_registry: dict[str, Any]) -> None:
        rules = principle_registry["rules"]
        rule_ids = [str(rule["ruleId"]) for rule in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ContractError("Principle registry contains duplicate rule IDs")

        source_paths = [self.root / ".github/copilot-instructions.md"] + sorted(
            (self.root / ".github/instructions").glob("*.instructions.md")
        )
        pattern = re.compile(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—")
        occurrences: dict[str, list[str]] = {}
        for path in source_paths:
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            for rule_id in pattern.findall(path.read_text(encoding="utf-8")):
                occurrences.setdefault(rule_id, []).append(relative)
        duplicate_sources = sorted(
            rule_id for rule_id, locations in occurrences.items() if len(locations) != 1
        )
        if duplicate_sources:
            raise ContractError(
                f"Principle IDs must occur exactly once in runtime sources: {duplicate_sources}"
            )
        if set(rule_ids) != set(occurrences):
            raise ContractError(
                "Principle registry/source mismatch: "
                f"missing={sorted(set(occurrences) - set(rule_ids))}, "
                f"extra={sorted(set(rule_ids) - set(occurrences))}"
            )
        by_id = {str(rule["ruleId"]): rule for rule in rules}
        for rule_id, locations in occurrences.items():
            if str(by_id[rule_id]["sourceFile"]) != locations[0]:
                raise ContractError(
                    f"{rule_id}: registry sourceFile does not match its runtime source"
                )

    def validate_all(
        self, at: datetime | None = None, *, enforce_current: bool = True
    ) -> dict[str, int]:
        effective_at = self.at_time(at)
        policy = load_json(self.policy_path)
        self.validate_data(policy, "knowledge-policy.schema.json", str(self.policy_path))
        principle_registry = load_yaml(self.registry_path)
        self.validate_data(
            principle_registry, "principle-registry.schema.json", str(self.registry_path)
        )
        self.validate_principles(principle_registry)

        evidence_by_id: dict[str, dict[str, Any]] = {}
        for path, record in self.records(self.evidence):
            self.validate_data(record, "knowledge-evidence.schema.json", str(path))
            if parse_time(record["retrievedAt"], "evidence retrievedAt") < parse_time(
                record["observedAt"], "evidence observedAt"
            ):
                raise ContractError(f"{path}: retrievedAt precedes observedAt")
            evidence_id = str(record["evidenceId"])
            if path.stem != evidence_id or evidence_id in evidence_by_id:
                raise ContractError(f"evidence filename/ID is duplicated or mismatched: {path}")
            evidence_by_id[evidence_id] = record

        review_by_id: dict[str, dict[str, Any]] = {}
        for path, record in self.records(self.reviews):
            self.validate_data(record, "knowledge-review.schema.json", str(path))
            self.verify_audit_receipt(record)
            reviewed_at = parse_time(record["reviewedAt"], "reviewedAt")
            audit_verified_at = parse_time(
                record["auditReceipt"]["verifiedAt"], "audit receipt verifiedAt"
            )
            if audit_verified_at > reviewed_at:
                raise ContractError(f"{path}: audit receipt postdates its review")
            if reviewed_at > effective_at:
                raise ContractError(f"{path}: review is dated in the future")
            review_id = str(record["reviewId"])
            if path.stem != review_id or review_id in review_by_id:
                raise ContractError(f"review filename/ID is duplicated or mismatched: {path}")
            review_by_id[review_id] = record

        claim_by_id: dict[str, dict[str, Any]] = {}
        for path, record in self.records(self.claims):
            self.validate_data(record, "knowledge-claim.schema.json", str(path))
            self.validate_temporal_claim(record)
            claim_id = str(record["claimId"])
            if path.stem != claim_id or claim_id in claim_by_id:
                raise ContractError(f"claim filename/ID is duplicated or mismatched: {path}")
            claim_by_id[claim_id] = record

        for claim_id, claim in claim_by_id.items():
            missing_evidence = sorted(set(claim["evidenceRefs"]) - set(evidence_by_id))
            if missing_evidence:
                raise ContractError(f"{claim_id}: missing evidence refs {missing_evidence}")
            for evidence_ref in claim["evidenceRefs"]:
                self.verify_evidence_scope(claim, evidence_by_id[evidence_ref])
            review_ref = claim.get("reviewRef")
            if review_ref and review_ref not in review_by_id:
                raise ContractError(f"{claim_id}: missing review ref {review_ref}")
            if claim["status"] == "verified":
                if not review_ref:
                    raise ContractError(f"{claim_id}: verified claim has no review")
                review = review_by_id[review_ref]
                if (
                    review["claimId"] != claim_id
                    or review["decision"] != "verify"
                    or review["resultingStatus"] != "verified"
                    or claim["revision"] != review["claimRevision"] + 1
                    or claim["verifiedAt"] != review["reviewedAt"]
                ):
                    raise ContractError(f"{claim_id}: verified state does not match its review")
                if enforce_current and not self.is_fresh(claim, effective_at):
                    raise ContractError(f"{claim_id}: verified claim is expired or not yet effective")
            self.validate_claim_references(claim, claim_by_id)

        for review_id, review in review_by_id.items():
            claim = claim_by_id.get(review["claimId"])
            if claim is None:
                raise ContractError(f"{review_id}: missing claim {review['claimId']}")
            if claim["revision"] < review["claimRevision"]:
                raise ContractError(f"{review_id}: review targets a future claim revision")
            missing_evidence = sorted(set(review["evidenceRefs"]) - set(evidence_by_id))
            if missing_evidence:
                raise ContractError(f"{review_id}: missing evidence refs {missing_evidence}")
            is_current_review = claim.get("reviewRef") == review_id
            is_pending_review = claim["revision"] == review["claimRevision"]
            if review["decision"] == "verify" and (is_current_review or is_pending_review):
                reviewed_claim = copy.deepcopy(claim)
                if is_current_review:
                    reviewed_claim["status"] = review["reviewedStatus"]
                    reviewed_claim["revision"] = review["claimRevision"]
                    reviewed_claim["reviewRef"] = None
                    reviewed_claim["verifiedAt"] = None
                records = [evidence_by_id[ref] for ref in review["evidenceRefs"]]
                self.verify_review_bindings(review, reviewed_claim, records)
                self.evaluate_verify_review(
                    review,
                    reviewed_claim,
                    records,
                    effective_at,
                    require_current=enforce_current,
                )

        verified_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for claim in claim_by_id.values():
            if claim["status"] == "verified":
                verified_by_key.setdefault(self.reconciliation_key(claim), []).append(claim)
        for claims in verified_by_key.values():
            values = {canonical(claim["assertion"]["value"]) for claim in claims}
            if len(values) > 1:
                raise ContractError(
                    "contradictory verified claims coexist: "
                    f"{sorted(str(claim['claimId']) for claim in claims)}"
                )
            if len(claims) > 1:
                raise ContractError(
                    "duplicate verified claims coexist: "
                    f"{sorted(str(claim['claimId']) for claim in claims)}"
                )

        rule_ids = [rule["ruleId"] for rule in principle_registry["rules"]]

        return {
            "claims": len(claim_by_id),
            "evidence": len(evidence_by_id),
            "reviews": len(review_by_id),
            "rules": len(rule_ids),
        }

    def claim_is_effective(self, claim: dict[str, Any], at: datetime) -> bool:
        if claim["status"] not in EFFECTIVE_CLAIM_STATUSES or not self.is_fresh(claim, at):
            return False
        if claim["contradicts"] or claim.get("supersededBy") is not None:
            return False
        reconciliation = self.reconcile(claim)
        if reconciliation["conflictingClaimRefs"]:
            return False
        claim_id = str(claim["claimId"])
        for _, other in self.records(self.claims):
            if (
                other["claimId"] != claim_id
                and other["status"] in ACTIVE_CLAIM_STATUSES
                and claim_id in other["contradicts"]
            ):
                return False
        return True

    def effective_claim(
        self, claim_id: str, at: datetime | None = None
    ) -> dict[str, Any]:
        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        path = self.claim_path(claim_id)
        if not path.is_file():
            raise ContractError(f"Knowledge claim does not exist: {claim_id}")
        claim = load_yaml(path)
        if not self.claim_is_effective(claim, effective_at):
            raise ContractError(
                f"Knowledge claim is not current, verified, and non-contradicted: {claim_id}"
            )
        return {
            "claim": copy.deepcopy(claim),
            "sha256": file_sha256(path),
            "path": path.relative_to(self.root).as_posix(),
        }

    def query(
        self,
        *,
        claim_id: str | None = None,
        domain: str | None = None,
        claim_type: str | None = None,
        subject_kind: str | None = None,
        subject_identity: str | None = None,
        environment: str | None = None,
        org_key: str | None = None,
        package_namespace: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        filters = {
            "claim_id": claim_id,
            "domain": domain,
            "claim_type": claim_type,
            "subject_kind": subject_kind,
            "subject_identity": subject_identity,
            "environment": environment,
            "org_key": org_key,
            "package_namespace": package_namespace,
        }
        if not any(value is not None for value in filters.values()):
            raise ContractError("query requires at least one Knowledge filter")
        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        matches: list[dict[str, Any]] = []
        for path, claim in self.records(self.claims):
            if claim_id is not None and claim["claimId"] != claim_id:
                continue
            if domain is not None and claim["domain"] != domain:
                continue
            if claim_type is not None and claim["claimType"] != claim_type:
                continue
            if subject_kind is not None and claim["subject"]["kind"] != subject_kind:
                continue
            if subject_identity is not None and claim["subject"]["identity"] != subject_identity:
                continue
            if environment is not None and claim["scope"]["environment"] != environment:
                continue
            if org_key is not None and claim["scope"]["orgKey"] != org_key:
                continue
            if (
                package_namespace is not None
                and claim["scope"]["packageNamespace"] != package_namespace
            ):
                continue
            if not self.claim_is_effective(claim, effective_at):
                continue
            matches.append(
                {
                    "claim": copy.deepcopy(claim),
                    "sha256": file_sha256(path),
                    "path": path.relative_to(self.root).as_posix(),
                }
            )
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "count": len(matches),
            "claims": matches,
        }

    def write_evidence_immutable(self, record: dict[str, Any]) -> None:
        self.validate_data(record, "knowledge-evidence.schema.json", "proposed evidence")
        if parse_time(record["retrievedAt"], "evidence retrievedAt") < parse_time(
            record["observedAt"], "evidence observedAt"
        ):
            raise ContractError("evidence retrievedAt precedes observedAt")
        path = self.evidence_path(record["evidenceId"])
        if path.exists():
            if canonical(load_yaml(path)) != canonical(record):
                raise ContractError(f"evidence is immutable and already exists: {record['evidenceId']}")
            return
        atomic_yaml_write(path, record)

    def write_proposed_claim(self, record: dict[str, Any], expected_revision: int) -> None:
        self.validate_data(record, "knowledge-claim.schema.json", "proposed claim")
        self.validate_temporal_claim(record)
        if record["status"] != "proposed":
            raise ContractError("propose accepts only status: proposed")
        path = self.claim_path(record["claimId"])
        if path.exists():
            current = load_yaml(path)
            self.validate_data(current, "knowledge-claim.schema.json", str(path))
            if current["status"] != "proposed":
                raise ContractError("propose may not replace a non-proposed claim")
            if current["revision"] != expected_revision:
                raise ContractError(
                    f"expected revision {expected_revision}, found {current['revision']}"
                )
            if record["revision"] != expected_revision + 1:
                raise ContractError("updated proposal revision must equal expected revision + 1")
        else:
            if expected_revision != 0 or record["revision"] != 1:
                raise ContractError("new proposal requires expected revision 0 and revision 1")
        missing = [ref for ref in record["evidenceRefs"] if not self.evidence_path(ref).is_file()]
        if missing:
            raise ContractError(f"proposed claim references missing evidence: {missing}")
        atomic_yaml_write(path, record)

    def propose(
        self, claim_file: Path, evidence_files: list[Path], expected_revision: int
    ) -> dict[str, Any]:
        claim = load_yaml(claim_file)
        proposed_evidence = [load_yaml(path) for path in evidence_files]
        for record in proposed_evidence:
            self.validate_data(record, "knowledge-evidence.schema.json", "proposed evidence")
        self.validate_data(claim, "knowledge-claim.schema.json", "proposed claim")
        self.validate_temporal_claim(claim)
        if claim["status"] != "proposed":
            raise ContractError("propose accepts only status: proposed")
        if "<AGENT_" in canonical(claim):
            raise ContractError(
                "draft placeholder is unfilled: read the component source and replace the "
                "<AGENT_...> sentinel with a real description before proposing"
            )
        if parse_time(claim["reviewBy"], "claim reviewBy") <= self.at_time():
            raise ContractError("proposed claim is already expired at current time")

        proposed_by_id = {str(record["evidenceId"]): record for record in proposed_evidence}
        if len(proposed_by_id) != len(proposed_evidence):
            raise ContractError("proposal contains duplicate evidence IDs")
        existing_evidence = {
            str(record["evidenceId"]): record for _, record in self.records(self.evidence)
        }
        available = set(proposed_by_id) | set(existing_evidence)
        missing = sorted(set(claim["evidenceRefs"]) - available)
        if missing:
            raise ContractError(f"proposed claim references missing evidence: {missing}")

        for evidence_id, record in proposed_by_id.items():
            existing = existing_evidence.get(evidence_id)
            if existing is not None and canonical(existing) != canonical(record):
                raise ContractError(f"evidence is immutable and already exists: {evidence_id}")
        for evidence_ref in claim["evidenceRefs"]:
            self.verify_evidence_scope(
                claim,
                proposed_by_id[evidence_ref]
                if evidence_ref in proposed_by_id
                else existing_evidence[evidence_ref],
            )

        existing_claims = {str(record["claimId"]): record for _, record in self.records(self.claims)}
        references_with_candidate = dict(existing_claims)
        references_with_candidate[str(claim["claimId"])] = claim
        self.validate_claim_references(claim, references_with_candidate)
        reconciliation = self.reconcile(claim)
        if reconciliation["duplicateClaimRefs"]:
            raise ContractError(
                "proposal duplicates active claim(s): "
                f"{reconciliation['duplicateClaimRefs']}"
            )
        conflicts = reconciliation["conflictingClaimRefs"]
        if conflicts and sorted(claim["contradicts"]) != conflicts:
            raise ContractError(
                "proposal conflicts must be declared exactly in contradicts: "
                f"{conflicts}"
            )
        if not conflicts and claim["contradicts"]:
            raise ContractError("proposal declares contradicts refs without an active conflict")

        # Check optimistic concurrency before any new evidence is persisted.
        current = existing_claims.get(str(claim["claimId"]))
        if current is None:
            if expected_revision != 0 or claim["revision"] != 1:
                raise ContractError("new proposal requires expected revision 0 and revision 1")
        else:
            if current["status"] != "proposed":
                raise ContractError("propose may not replace a non-proposed claim")
            if current["revision"] != expected_revision:
                raise ContractError(
                    f"expected revision {expected_revision}, found {current['revision']}"
                )
            if claim["revision"] != expected_revision + 1:
                raise ContractError(
                    "updated proposal revision must equal expected revision + 1"
                )

        for record in proposed_evidence:
            self.write_evidence_immutable(record)
        self.write_proposed_claim(claim, expected_revision)
        return {
            "claimId": claim["claimId"],
            "status": "proposed",
            "revision": claim["revision"],
            "reconciliation": reconciliation["status"],
        }

    def evaluate_verify_review(
        self,
        review: dict[str, Any],
        claim: dict[str, Any],
        evidence_records: list[dict[str, Any]],
        effective_at: datetime | None = None,
        *,
        require_current: bool = True,
    ) -> None:
        if review["decision"] != "verify":
            return
        now = self.at_time(effective_at)
        if claim["status"] not in {"proposed", "stale"}:
            raise ContractError("verify review may promote only a proposed or stale claim")
        if review["reviewedStatus"] != claim["status"]:
            raise ContractError("reviewedStatus does not match the pre-promotion claim")
        self.verify_review_bindings(review, claim, evidence_records)
        policy = load_json(self.policy_path)
        if review["policyVersion"] != policy["schemaVersion"]:
            raise ContractError("review policyVersion does not match active Knowledge policy")
        claim_policy = policy["claimPolicies"][claim["claimType"]]
        review_time = parse_time(review["reviewedAt"], "reviewedAt")
        audit_time = parse_time(
            review["auditReceipt"]["verifiedAt"], "audit receipt verifiedAt"
        )
        freshness_time = parse_time(
            review["freshness"]["evaluatedAt"], "freshness evaluatedAt"
        )
        if review_time > now:
            raise ContractError("reviewedAt may not be in the future")
        if audit_time > review_time:
            raise ContractError("audit receipt may not postdate its review")
        if freshness_time != review_time:
            raise ContractError("freshness must be evaluated at reviewedAt")
        if parse_time(claim["observedAt"], "claim observedAt") > review_time:
            raise ContractError("claim observation may not postdate its review")
        allowed = set(claim_policy["allowedEvidenceTypes"])
        for evidence in evidence_records:
            self.validate_data(
                evidence,
                "knowledge-evidence.schema.json",
                f"evidence {evidence.get('evidenceId', '<unknown>')}",
            )
            if evidence["sourceType"] not in allowed:
                raise ContractError(
                    f"{evidence['evidenceId']}: source type is not authoritative for {claim['claimType']}"
                )
            if claim["claimType"] not in evidence["authorityFor"]:
                raise ContractError(
                    f"{evidence['evidenceId']}: authorityFor omits {claim['claimType']}"
                )
            if evidence["completeness"]["status"] != "complete":
                raise ContractError(f"{evidence['evidenceId']}: partial evidence cannot verify")
            self.verify_evidence_scope(claim, evidence)
            observed = parse_time(evidence["observedAt"], "evidence observedAt")
            retrieved = parse_time(evidence["retrievedAt"], "evidence retrievedAt")
            if retrieved < observed or review_time < retrieved:
                raise ContractError(f"{evidence['evidenceId']}: invalid evidence/review chronology")
            age = review_time - observed
            if age > timedelta(days=claim_policy["maxReviewAgeDays"]):
                raise ContractError(f"{evidence['evidenceId']}: evidence is stale under policy")
            if claim["polarity"] == "negative" and (
                not evidence["completeness"]["enumerationComplete"]
                or not evidence["completeness"]["permissionsProven"]
            ):
                raise ContractError(
                    f"{evidence['evidenceId']}: negative claim lacks complete enumeration or permission proof"
                )
            if (
                claim["polarity"] == "negative"
                and age > timedelta(days=policy["negativeClaims"]["maxReviewAgeDays"])
            ):
                raise ContractError(f"{evidence['evidenceId']}: negative-claim evidence is stale")
        independent = {record["independenceKey"] for record in evidence_records}
        if len(independent) < claim_policy["minimumIndependentEvidence"]:
            raise ContractError("review does not meet independent evidence minimum")
        review_by = parse_time(claim["reviewBy"], "claim reviewBy")
        if review_by <= review_time:
            raise ContractError("claim reviewBy must be later than promotion review")
        if review_by > review_time + timedelta(days=claim_policy["maxReviewAgeDays"]):
            raise ContractError("claim reviewBy exceeds the policy freshness window")
        if require_current and review_by <= now:
            raise ContractError("claim is already expired at current time")

    def record_review(self, review_file: Path) -> dict[str, Any]:
        return self.record_review_data(load_yaml(review_file))

    def record_review_data(self, review: dict[str, Any]) -> dict[str, Any]:
        self.validate_data(review, "knowledge-review.schema.json", "Knowledge review")
        self.verify_audit_receipt(review)
        path = self.review_path(review["reviewId"])
        if path.exists():
            if canonical(load_yaml(path)) == canonical(review):
                return {"reviewId": review["reviewId"], "status": "already-recorded"}
            raise ContractError(f"review is immutable and already exists: {review['reviewId']}")
        claim_path = self.claim_path(review["claimId"])
        if not claim_path.is_file():
            raise ContractError(f"review claim does not exist: {review['claimId']}")
        claim = load_yaml(claim_path)
        self.validate_data(claim, "knowledge-claim.schema.json", str(claim_path))
        self.validate_temporal_claim(claim)
        if claim["revision"] != review["claimRevision"]:
            raise ContractError("review claimRevision does not match current claim revision")
        evidence_records: list[dict[str, Any]] = []
        for evidence_id in review["evidenceRefs"]:
            evidence_path = self.evidence_path(evidence_id)
            if not evidence_path.is_file():
                raise ContractError(f"review evidence does not exist: {evidence_id}")
            evidence_records.append(load_yaml(evidence_path))
        self.verify_review_bindings(review, claim, evidence_records)
        reconciliation = self.reconcile(claim)
        if review["decision"] == "verify" and (
            reconciliation["duplicateClaimRefs"]
            or reconciliation["conflictingClaimRefs"]
        ):
            raise ContractError(
                "verify review is blocked by unresolved Knowledge reconciliation"
            )
        self.evaluate_verify_review(review, claim, evidence_records, self.at_time())
        atomic_yaml_write(path, review)
        return {"reviewId": review["reviewId"], "decision": review["decision"]}

    def promote(self, claim_id: str, review_id: str, expected_revision: int) -> dict[str, Any]:
        claim_path = self.claim_path(claim_id)
        review_path = self.review_path(review_id)
        if not claim_path.is_file():
            raise ContractError("claim must exist before promotion")
        claim = load_yaml(claim_path)
        self.validate_data(claim, "knowledge-claim.schema.json", str(claim_path))
        if claim["revision"] != expected_revision:
            raise ContractError(
                f"expected revision {expected_revision}, found {claim['revision']}"
            )
        if not review_path.is_file():
            raise ContractError("recorded human review must exist before promotion")
        review = load_yaml(review_path)
        self.validate_data(review, "knowledge-review.schema.json", str(review_path))
        if review["claimId"] != claim_id or review["claimRevision"] != expected_revision:
            raise ContractError("review does not target the expected claim revision")
        evidence_records = [load_yaml(self.evidence_path(ref)) for ref in review["evidenceRefs"]]
        self.verify_review_bindings(review, claim, evidence_records)
        reconciliation = self.reconcile(claim)
        if reconciliation["duplicateClaimRefs"]:
            raise ContractError(
                "promotion duplicates active claim(s): "
                f"{reconciliation['duplicateClaimRefs']}"
            )
        if reconciliation["conflictingClaimRefs"]:
            raise ContractError(
                "promotion is blocked by conflicting active claim(s): "
                f"{reconciliation['conflictingClaimRefs']}"
            )
        self.evaluate_verify_review(review, claim, evidence_records, self.at_time())
        if review["decision"] != "verify" or review["resultingStatus"] != "verified":
            raise ContractError("promote requires a verify review with verified result")

        promoted = copy.deepcopy(claim)
        promoted["revision"] = expected_revision + 1
        promoted["status"] = "verified"
        promoted["reviewRef"] = review_id
        promoted["verifiedAt"] = review["reviewedAt"]
        self.validate_data(promoted, "knowledge-claim.schema.json", "promoted claim")

        current = load_yaml(claim_path)
        if current["revision"] != expected_revision:
            raise ContractError("claim changed after validation; promotion aborted")
        atomic_yaml_write(claim_path, promoted)
        return {"claimId": claim_id, "status": "verified", "revision": promoted["revision"]}

    def approve_claim(
        self,
        claim_id: str,
        expected_revision: int,
        decision: str = "verify",
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """One-command chat-approval review: build the immutable review record (all digests
        computed here), record it, and — for verify — promote the claim and refresh the
        generated domain indexes.

        The approving human is named once in ignored local configuration
        (`knowledge.chatReviewer`); the VS Code confirmation dialog raised by the safety hook and
        the non-auto-approved terminal command is the recorded approval mechanism
        (`copilot-chat-confirmation`). Owner decision 2026-07-14 — this replaces hand-written
        review YAML for the common promote/reject path; the file-based `review` + `promote`
        commands remain for external mechanisms (github-review, ado-approval).
        """

        if decision not in {"verify", "reject"}:
            raise ContractError("approve-claim decision must be verify or reject")
        local_config_path = self.root / "config" / "harness.local.json"
        try:
            local_config = json.loads(local_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(
                "cannot read config/harness.local.json for the chat reviewer identity"
            ) from exc
        reviewer = str(local_config.get("knowledge", {}).get("chatReviewer", "")).strip()
        if not reviewer or reviewer.startswith("<"):
            raise ContractError(
                "knowledge.chatReviewer in config/harness.local.json must name the approving "
                "human before chat approval"
            )
        claim_path = self.claim_path(claim_id)
        if not claim_path.is_file():
            raise ContractError(f"claim does not exist: {claim_id}")
        claim = load_yaml(claim_path)
        self.validate_data(claim, "knowledge-claim.schema.json", str(claim_path))
        if claim["revision"] != expected_revision:
            raise ContractError(
                f"expected revision {expected_revision}, found {claim['revision']}"
            )
        if claim["status"] not in {"proposed", "stale", "contested"}:
            raise ContractError(f"claim status {claim['status']} is not reviewable")
        evidence_records = []
        for evidence_id in sorted(str(ref) for ref in claim["evidenceRefs"]):
            evidence_path = self.evidence_path(evidence_id)
            if not evidence_path.is_file():
                raise ContractError(f"claim evidence does not exist: {evidence_id}")
            evidence_records.append(load_yaml(evidence_path))
        at = self.at_time()
        reviewed_at = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = "CHAT-VERIFY" if decision == "verify" else "CHAT-REJECT"
        review_id = f"KREV-{claim_id[5:61]}-R{expected_revision}-{suffix}"
        receipt = {
            "mechanism": "copilot-chat-confirmation",
            "reference": f"vscode-chat://approve-claim/{claim_id}/r{expected_revision}",
            "verifiedAt": reviewed_at,
        }
        receipt["receiptDigest"] = canonical_digest(receipt)
        review = {
            "schemaVersion": 3,
            "reviewId": review_id,
            "reviewType": "promotion" if decision == "verify" else "rejection",
            "claimId": claim_id,
            "claimRevision": expected_revision,
            "reviewedStatus": claim["status"],
            "decision": decision,
            "resultingStatus": "verified" if decision == "verify" else "rejected",
            "reviewer": {"type": "human", "identity": reviewer},
            "reviewedAt": reviewed_at,
            "evidenceRefs": sorted(str(ref) for ref in claim["evidenceRefs"]),
            "policyVersion": 1,
            "scopeMatch": True,
            "freshness": {
                "status": "current",
                "evaluatedAt": reviewed_at,
                "triggeredInvalidators": [],
            },
            "conflictingClaimRefs": [],
            **self.review_bindings(claim, evidence_records),
            "auditReceipt": receipt,
            "rationale": rationale
            or (
                f"Chat-approval {decision} by {reviewer} through the guarded approve-claim "
                "command; digests were computed from the exact pre-review records."
            ),
        }
        self.record_review_data(review)
        if decision == "verify":
            promoted = self.promote(claim_id, review_id, expected_revision)
            self.render_indexes(check=False)
            return {
                "claimId": claim_id,
                "reviewId": review_id,
                "status": "verified",
                "revision": promoted["revision"],
                "reviewer": reviewer,
                "mechanism": "copilot-chat-confirmation",
            }
        rejected = copy.deepcopy(claim)
        rejected["revision"] = expected_revision + 1
        rejected["status"] = "rejected"
        rejected["reviewRef"] = review_id
        self.validate_data(rejected, "knowledge-claim.schema.json", "rejected claim")
        current = load_yaml(claim_path)
        if current["revision"] != expected_revision:
            raise ContractError("claim changed after validation; rejection aborted")
        atomic_yaml_write(claim_path, rejected)
        self.render_indexes(check=False)
        return {
            "claimId": claim_id,
            "reviewId": review_id,
            "status": "rejected",
            "revision": rejected["revision"],
            "reviewer": reviewer,
            "mechanism": "copilot-chat-confirmation",
        }

    @staticmethod
    def reconciliation_key(claim: dict[str, Any]) -> tuple[str, str, str]:
        return (
            canonical(claim["subject"]),
            str(claim["assertion"]["predicate"]),
            canonical(claim["scope"]),
        )

    def reconcile(self, candidate: dict[str, Any]) -> dict[str, Any]:
        self.validate_data(candidate, "knowledge-claim.schema.json", "reconciliation candidate")
        candidate_key = self.reconciliation_key(candidate)
        candidate_subject_predicate = candidate_key[:2]
        duplicate: list[str] = []
        conflict: list[str] = []
        parallel_scope: list[str] = []
        for _, existing in self.records(self.claims):
            if (
                existing["claimId"] == candidate["claimId"]
                or existing["status"] not in ACTIVE_CLAIM_STATUSES
            ):
                continue
            existing_key = self.reconciliation_key(existing)
            if existing_key == candidate_key:
                if canonical(existing["assertion"]["value"]) == canonical(
                    candidate["assertion"]["value"]
                ):
                    duplicate.append(existing["claimId"])
                else:
                    conflict.append(existing["claimId"])
            elif existing_key[:2] == candidate_subject_predicate:
                parallel_scope.append(existing["claimId"])
        status = "conflict" if conflict else "duplicate" if duplicate else "parallel-scope" if parallel_scope else "new"
        return {
            "status": status,
            "duplicateClaimRefs": sorted(duplicate),
            "conflictingClaimRefs": sorted(conflict),
            "parallelScopeClaimRefs": sorted(parallel_scope),
        }

    @staticmethod
    def escape_table(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    def non_effective_reason(self, claim: dict[str, Any], at: datetime) -> str:
        if claim["status"] != "verified":
            return f"status is {claim['status']}"
        if not self.is_fresh(claim, at):
            return "verification is expired or not yet effective"
        if claim.get("supersededBy") is not None:
            return f"superseded by {claim['supersededBy']}"
        reconciliation = self.reconcile(claim)
        if reconciliation["conflictingClaimRefs"]:
            return "active conflict: " + ", ".join(
                reconciliation["conflictingClaimRefs"]
            )
        return "referenced by an active contradiction"

    def rendered_domain(
        self, domain: str, claims: list[dict[str, Any]], at: datetime
    ) -> str:
        title, description = DOMAIN_VIEWS[domain]
        lines = [f"# {title} — Generated Claim Index", "", description, "", "<!-- BEGIN GENERATED CLAIM INDEX -->", ""]
        if not claims:
            lines.append("_No canonical claims are indexed._")
        else:
            effective = [claim for claim in claims if self.claim_is_effective(claim, at)]
            untrusted = [claim for claim in claims if claim not in effective]
            lines.extend(
                [
                    "## Effective current verified facts",
                    "",
                    "Only rows in this section are eligible as grounded facts.",
                    "",
                    "| Claim | Review by | Structured fact | Evidence |",
                    "|---|---|---|---|",
                ]
            )
            if not effective:
                lines.append("| _None_ | — | — | — |")
            for claim in sorted(effective, key=lambda item: item["claimId"]):
                evidence_links = ", ".join(
                    f"[{ref}](evidence/{ref}.yaml)" for ref in claim["evidenceRefs"]
                )
                lines.append(
                    "| "
                    f"[{claim['claimId']}](claims/{claim['claimId']}.yaml) | "
                    f"{claim['reviewBy']} | "
                    f"{self.escape_table(self.structured_fact(claim))} | "
                    f"{evidence_links} |"
                )
            lines.extend(
                [
                    "",
                    "## Non-effective records — untrusted",
                    "",
                    "These records are visible for workflow and audit purposes only. They are not established facts.",
                    "",
                    "| Claim | Status | Review by | Structured assertion | Why non-effective |",
                    "|---|---|---|---|---|",
                ]
            )
            if not untrusted:
                lines.append("| _None_ | — | — | — | — |")
            for claim in sorted(untrusted, key=lambda item: item["claimId"]):
                lines.append(
                    "| "
                    f"[{claim['claimId']}](claims/{claim['claimId']}.yaml) | "
                    f"{claim['status']} | {claim['reviewBy']} | "
                    f"{self.escape_table(self.structured_fact(claim))} | "
                    f"{self.escape_table(self.non_effective_reason(claim, at))} |"
                )
        lines.extend(["", "<!-- END GENERATED CLAIM INDEX -->", ""])
        return "\n".join(lines)

    def render_indexes(self, check: bool) -> dict[str, Any]:
        effective_at = self.at_time()
        self.validate_all(effective_at, enforce_current=False)
        by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in DOMAIN_VIEWS}
        for path, claim in self.records(self.claims):
            self.validate_data(claim, "knowledge-claim.schema.json", str(path))
            by_domain[claim["domain"]].append(claim)
        drift: list[str] = []
        for domain, claims in by_domain.items():
            path = self.root / ".ai/knowledge" / f"{domain}.md"
            expected = self.rendered_domain(domain, claims, effective_at)
            if check:
                actual = path.read_text(encoding="utf-8") if path.is_file() else ""
                if actual != expected:
                    drift.append(path.relative_to(self.root).as_posix())
            else:
                atomic_text_write(path, expected)
        if drift:
            raise ContractError(f"generated Knowledge indexes drifted: {drift}")
        return {"domains": len(by_domain), "mode": "check" if check else "write"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")

    propose = commands.add_parser("propose")
    propose.add_argument("--claim-file", required=True)
    propose.add_argument("--evidence-file", action="append", default=[])
    propose.add_argument("--expected-revision", required=True, type=int)

    review = commands.add_parser("review")
    review.add_argument("--review-file", required=True)

    promote = commands.add_parser("promote")
    promote.add_argument("--claim-id", required=True)
    promote.add_argument("--review-id", required=True)
    promote.add_argument("--expected-revision", required=True, type=int)

    approve = commands.add_parser("approve-claim")
    approve.add_argument("--claim-id")
    approve.add_argument("--expected-revision", type=int)
    approve.add_argument(
        "--claim-spec",
        action="append",
        default=[],
        help="batch form: <claimId>:<revision>, repeatable (max 25 per invocation)",
    )
    approve.add_argument("--decision", choices=("verify", "reject"), default="verify")
    approve.add_argument("--rationale")

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--claim-file", required=True)

    query = commands.add_parser("query")
    query.add_argument("--claim-id")
    query.add_argument("--domain", choices=sorted(DOMAIN_VIEWS))
    query.add_argument("--claim-type")
    query.add_argument("--subject-kind")
    query.add_argument("--subject-identity")
    query.add_argument("--environment", choices=("development", "qa", "uat", "not-applicable"))
    query.add_argument("--org-key")
    query.add_argument("--package-namespace")
    query.add_argument("--at")

    render = commands.add_parser("render-indexes")
    render.add_argument("--check", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    registry = KnowledgeRegistry(DEFAULT_ROOT)
    try:
        if args.command == "validate":
            result = registry.validate_all()
        elif args.command == "propose":
            result = registry.propose(
                registry.contained_input(args.claim_file),
                [registry.contained_input(path) for path in args.evidence_file],
                args.expected_revision,
            )
        elif args.command == "review":
            result = registry.record_review(registry.contained_input(args.review_file))
        elif args.command == "promote":
            result = registry.promote(args.claim_id, args.review_id, args.expected_revision)
        elif args.command == "approve-claim":
            if args.claim_spec:
                if args.claim_id is not None or args.expected_revision is not None:
                    raise ContractError(
                        "use either --claim-id/--expected-revision or repeatable --claim-spec, not both"
                    )
                if len(args.claim_spec) > 25:
                    raise ContractError("a chat-approval batch is capped at 25 claims")
                batch: list[tuple[str, int]] = []
                for spec in args.claim_spec:
                    claim_id, separator, revision = spec.rpartition(":")
                    if not separator or not revision.isdigit():
                        raise ContractError(
                            f"--claim-spec must be <claimId>:<revision>, got {spec!r}"
                        )
                    batch.append((claim_id, int(revision)))
                results = [
                    registry.approve_claim(claim_id, revision, args.decision, args.rationale)
                    for claim_id, revision in batch
                ]
                result = {"batch": results, "count": len(results)}
            else:
                if args.claim_id is None or args.expected_revision is None:
                    raise ContractError(
                        "approve-claim requires --claim-id and --expected-revision (or --claim-spec)"
                    )
                result = registry.approve_claim(
                    args.claim_id, args.expected_revision, args.decision, args.rationale
                )
        elif args.command == "reconcile":
            result = registry.reconcile(load_yaml(registry.contained_input(args.claim_file)))
        elif args.command == "query":
            result = registry.query(
                claim_id=args.claim_id,
                domain=args.domain,
                claim_type=args.claim_type,
                subject_kind=args.subject_kind,
                subject_identity=args.subject_identity,
                environment=args.environment,
                org_key=args.org_key,
                package_namespace=args.package_namespace,
                at=parse_time(args.at, "query --at") if args.at else None,
            )
        elif args.command == "render-indexes":
            result = registry.render_indexes(args.check)
        else:  # pragma: no cover - argparse guarantees a known command
            raise ContractError(f"unsupported command: {args.command}")
    except ContractError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
