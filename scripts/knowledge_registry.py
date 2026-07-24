#!/usr/bin/env python3
"""Validate and manage schema-v3 Knowledge records without external system access."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.text_analysis import analyze as analyze_text
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_registry.py`
    from text_analysis import analyze as analyze_text  # type: ignore
from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.knowledge_registry by unit tests
    from scripts.schema_format import FORMAT_CHECKER


DEFAULT_ROOT = Path(__file__).resolve().parents[1]

# Claim types whose repository-derived leg moved to one-file Knowledge Entries
# (docs/knowledge-one-file-contract.md §1, SAFE-CLAIM-001 v2). Their org/vendor/SME legs stay
# here; a proposal backed ONLY by metadata-repository receipts is routed to the entry store.
ENTRY_HOME_CLAIM_TYPES = frozenset(
    {
        "automation-inventory",
        "component-description",
        "component-inventory",
        "field-schema",
        "integration",
        "object-existence",
        "object-ownership",
        "object-relation",
        "component-relation",
    }
)
# Metadata types with an implemented entry profile (scripts/knowledge_store.py PROFILES).
# The freeze below applies only to these: a type without a profile has no other home yet.
ENTRY_PROFILED_METADATA_TYPES = frozenset(
    {"Flow", "CustomField", "ApexClass", "ApexTrigger", "ValidationRule", "PermissionSet"}
)

ACTIVE_CLAIM_STATUSES = {"proposed", "verified", "stale", "contested"}
EFFECTIVE_CLAIM_STATUSES = {"verified"}
SCOPE_FIELDS = (
    "environment",
    "orgKey",
    "packageNamespace",
    "packageVersion",
    "repositoryCommit",
)

# Reference-kind vocabulary for the component usage registry carried in assertion.value.references.
# Field kinds name an `Object.Field`; object kinds name a bare object; invoke kinds name another
# automation/method; external kinds name things outside the repo component graph (related lists,
# hosts, org principals) and are excluded from usage derivation. Every kind the extractor
# (force_app_knowledge.ALL_REF_KINDS) can emit must be classified in exactly one of these sets —
# tests/test_kind_contract.py pins that invariant.
FIELD_REF_KINDS = frozenset(
    {
        "reads-field",
        "writes-field",
        "references-field",
        "places-field",
        "grants-field-permission",
        "schema",
        # Apex source-token heuristics (collector 1.1.0): SOQL SELECT/WHERE fields and
        # local-variable member accesses. Same Object.Field target shape, assurance stays inferred.
        "soql-field",
        "var-field-ref",
        # Filter/criteria fields (collector 1.3.0): fields an automation filters records by —
        # reads used for selection, distinct from the reads-field retrieval polarity.
        "filters-field",
        # Dependent-picklist wiring (collector 1.3.0): target is the controlling field.
        "picklist-dependency",
        # Level-aware field grants (collector 1.4.0): edit implies read; one edge per field.
        "grants-field-read",
        "grants-field-edit",
    }
)
OBJECT_REF_KINDS = frozenset(
    {
        "operates-on",
        "object-token",
        "relationship",
        "queries-object",
        "dml-object",
        "grants-object-permission",
        # High-signal record-visibility grants (collector 1.4.0).
        "grants-object-view-all",
        "grants-object-modify-all",
        # Queue routing (collector 1.5.0): target is the object the queue serves.
        "serves-object",
    }
)
INVOKE_REF_KINDS = frozenset(
    {
        "invokes-apex",
        "invokes-class",
        "subflow",
        "action",
        "apex-method",
        "apex-controller",
        # Field/business-process → value-set dependency (collector 1.3.0): target names a
        # GlobalValueSet or StandardValueSet component.
        "uses-value-set",
        # Workflow/approval notification wiring (collector 1.3.0): sends-alert targets an
        # Object.AlertName workflow alert; uses-template targets an EmailTemplate folder/name.
        "sends-alert",
        "uses-template",
        # Apex `callout:Name` literal (collector 1.3.0): target names a NamedCredential.
        "uses-named-credential",
        # Approval-process action wiring (collector 1.4.0): target is Object.ActionName inside
        # the owning object's Workflow component (fieldUpdates/tasks/outboundMessages).
        "uses-workflow-action",
        # Record-type → business-process and duplicate-rule → matching-rule links (collector
        # 1.4.0): targets are Object.Name component identities.
        "uses-business-process",
        "uses-matching-rule",
        # UI/code text and composition wiring (collector 1.4.0): uses-label targets a
        # CustomLabel name; embeds-component targets a child component bundle;
        # displays-component targets a rendered component; launches-flow targets a Flow.
        "uses-label",
        "embeds-component",
        "displays-component",
        "launches-flow",
        # App action override (collector 1.4.0): target names the FlexiPage assigned as the
        # view/edit/new page for an object (optionally per profile/record type).
        "overrides-view",
        # Access-model grants (collector 1.4.0): targets name repo components (Apex class,
        # CustomPermission, Object.RecordType, Flow, Layout).
        "grants-class-access",
        "grants-custom-permission",
        "grants-record-type",
        "grants-flow-access",
        "assigns-layout",
        # Routing rules (collector 1.5.0): target names a Queue component (user targets are
        # suppressed at extraction).
        "assigns-to",
        # Integration topology (collector 1.5.0): credential chains and pre-authorizations.
        "uses-external-credential",
        "references-auth-provider",
        "grants-to-profile",
        "grants-to-permission-set",
        # $Permission gates and permission-set-group composition (collector 1.5.0).
        "references-custom-permission",
        "includes-permission-set",
        "mutes-permission-set",
        # Role hierarchy (collector 1.6.0): target names the parent Role component.
        "reports-to",
    }
)
# Kinds whose targets are not repo components, objects, or fields (a layout's related-list name,
# an Apex callout's endpoint hostname; org principals as the extractor grows). Deliberately
# excluded from usesObjects/usesFields/invokes derivation so those query surfaces stay precise.
EXTERNAL_REF_KINDS = frozenset(
    {
        "related-list",
        "callout-endpoint",
        # System permissions (ModifyAllData, AuthorApex, …) are platform capability strings,
        # not repo components.
        "grants-user-permission",
        # Sharing grantees (collector 1.5.0): targets are org principals (role:X, group:Y).
        "shares-with",
    }
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
        self._record_cache: dict[Path, list[tuple[Path, dict[str, Any]]]] = {}

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
        """Parsed records for one store directory, memoized per registry instance.

        `query` validates, then re-reads, and every effectiveness check reconciles — which
        re-read the same YAML repeatedly and made a broad query super-linear in store size.
        The cache is dropped on every write (see `invalidate_cache`), so a mutating command
        never observes stale records."""

        cached = self._record_cache.get(directory)
        if cached is None:
            cached = [(path, load_yaml(path)) for path in sorted(directory.glob("*.yaml"))]
            self._record_cache[directory] = cached
        return [(path, copy.deepcopy(record)) for path, record in cached]

    def invalidate_cache(self) -> None:
        self._record_cache.clear()

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
    def derived_polarity(claim: dict[str, Any]) -> str:
        """Polarity of a claim, derived when the optional field is absent.

        A false-valued object-existence or package-installation claim is negative; every other
        source-defined claim is positive. An explicitly stored polarity is honoured, but the
        false-value rule always wins so negative-claim governance cannot be bypassed by omitting it.
        """

        value = claim.get("assertion", {}).get("value")
        if claim.get("claimType") in {"object-existence", "package-installation"} and value is False:
            return "negative"
        return claim.get("polarity", "positive")

    @staticmethod
    def claim_usage(claim: dict[str, Any]) -> dict[str, list[str]]:
        """Objects, fields, and invoked components a claim's subject uses.

        Reads the structured `references`/`facts` carried in assertion.value for source-defined
        component and automation claims. Powers the --uses-object/--uses-field/--invokes queries and
        the claims-index usesObjects/usesFields summary. Returns empty lists for claims without a
        usage payload.
        """

        value = claim.get("assertion", {}).get("value")
        claim_type = claim.get("claimType")
        objects: set[str] = set()
        fields: set[str] = set()
        invokes: set[str] = set()
        if claim_type == "object-relation" and isinstance(value, str) and value:
            # Bare-string target: this relation type only ever asserts an object reference.
            objects.add(value)
        elif claim_type == "component-relation" and isinstance(value, dict):
            predicate = str(claim.get("assertion", {}).get("predicate", ""))
            target = str(value.get("target", ""))
            if target:
                if predicate in FIELD_REF_KINDS:
                    fields.add(target)
                    objects.add(target.split(".", 1)[0])
                elif predicate in OBJECT_REF_KINDS:
                    objects.add(target.split(".", 1)[0])
                elif predicate in INVOKE_REF_KINDS:
                    invokes.add(target)
        elif isinstance(value, dict):
            facts = value.get("facts")
            if isinstance(facts, dict):
                if isinstance(facts.get("object"), str):
                    objects.add(facts["object"])
                for name in facts.get("referencedObjects", []) or []:
                    objects.add(str(name))
            for reference in value.get("references", []) or []:
                kind = reference.get("kind")
                target = str(reference.get("target", ""))
                if not target:
                    continue
                if kind in FIELD_REF_KINDS:
                    fields.add(target)
                    objects.add(target.split(".", 1)[0])
                elif kind in OBJECT_REF_KINDS:
                    objects.add(target.split(".", 1)[0])
                elif kind in INVOKE_REF_KINDS:
                    invokes.add(target)
        return {
            "objects": sorted(name for name in objects if name),
            "fields": sorted(fields),
            "invokes": sorted(invokes),
        }

    @staticmethod
    def claim_error_catalog(claim: dict[str, Any]) -> list[dict[str, Any]]:
        """errorCatalog entries carried in assertion.value.facts; empty when absent.

        Powers the search corpus and the claims-index emitsErrors summary so a user-pasted
        error message finds the automation that declares it."""

        value = claim.get("assertion", {}).get("value")
        if not isinstance(value, dict):
            return []
        facts = value.get("facts")
        if not isinstance(facts, dict):
            return []
        return [entry for entry in facts.get("errorCatalog") or [] if isinstance(entry, dict)]

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
            claim_value = claim_scope.get(field)
            evidence_value = evidence.get(field)
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
            refs = [str(ref) for ref in claim.get(field, [])]
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

    def claim_ineffective_reason(self, claim: dict[str, Any], at: datetime) -> str | None:
        """Why a claim is not an established fact, or None when it is one.

        Consumers must be able to say WHY a match was withheld — silently dropping
        non-effective records is what let stale or contested knowledge look like absence."""

        if claim["status"] not in EFFECTIVE_CLAIM_STATUSES:
            return f"status:{claim['status']}"
        if not self.is_fresh(claim, at):
            return "expired"
        if claim["contradicts"]:
            return "contested"
        if claim.get("supersededBy") is not None:
            return "superseded"
        if self.reconcile(claim)["conflictingClaimRefs"]:
            return "conflicting-scope"
        claim_id = str(claim["claimId"])
        for _, other in self.records(self.claims):
            if (
                other["claimId"] != claim_id
                and other["status"] in ACTIVE_CLAIM_STATUSES
                and claim_id in other["contradicts"]
            ):
                return "contradicted-by-active-claim"
        return None

    def claim_is_effective(self, claim: dict[str, Any], at: datetime) -> bool:
        return self.claim_ineffective_reason(claim, at) is None

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
        keyword: str | None = None,
        text: str | None = None,
        feature: str | None = None,
        uses_object: str | None = None,
        uses_field: str | None = None,
        invokes: str | None = None,
        related: str | None = None,
        depth: int = 1,
        search: str | None = None,
        top: int = 10,
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
            "keyword": keyword,
            "text": text,
            "feature": feature,
            "uses_object": uses_object,
            "uses_field": uses_field,
            "invokes": invokes,
            "related": related,
            "search": search,
        }
        if not any(value is not None for value in filters.values()):
            raise ContractError("query requires at least one Knowledge filter")
        if related is not None:
            others = {name for name, value in filters.items() if value is not None} - {"related"}
            if others:
                raise ContractError(
                    "--related traverses the claim graph on its own; combine it only with "
                    "--depth/--at"
                )
            return self.related_query(related, depth, at)
        if not 1 <= top:
            raise ContractError("query --top must be at least 1")
        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        matches: list[dict[str, Any]] = []
        non_effective: list[dict[str, Any]] = []
        applied_filters = {
            name: value
            for name, value in {
                "claim-id": claim_id,
                "domain": domain,
                "claim-type": claim_type,
                "subject-kind": subject_kind,
                "subject-identity": subject_identity,
                "environment": environment,
                "org-key": org_key,
                "package-namespace": package_namespace,
                "keyword": keyword,
                "text": text,
                "feature": feature,
                "uses-object": uses_object,
                "uses-field": uses_field,
                "invokes": invokes,
                "search": search,
            }.items()
            if value is not None
        }
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
            if feature is not None and not any(
                feature.casefold() == str(tag).casefold()
                for tag in claim.get("feature", []) or []
            ):
                continue
            keyword_tier = None
            if keyword is not None:
                needle = keyword.casefold()
                if any(needle == str(term).casefold() for term in claim["keywords"]):
                    keyword_tier = "keywords"
                elif any(
                    needle == str(term).casefold()
                    for term in claim.get("candidateKeywords", [])
                ):
                    keyword_tier = "candidateKeywords"
                if keyword_tier is None:
                    continue
            if text is not None:
                haystack = str(claim["statement"])
                value = claim["assertion"]["value"]
                if isinstance(value, dict) and isinstance(value.get("description"), str):
                    haystack += "\n" + value["description"]
                if text.casefold() not in haystack.casefold():
                    continue
            if uses_object is not None or uses_field is not None or invokes is not None:
                usage = self.claim_usage(claim)
                if uses_object is not None and uses_object.casefold() not in {
                    name.casefold() for name in usage["objects"]
                }:
                    continue
                if uses_field is not None and uses_field.casefold() not in {
                    name.casefold() for name in usage["fields"]
                }:
                    continue
                if invokes is not None and invokes.casefold() not in {
                    name.casefold() for name in usage["invokes"]
                }:
                    continue
            ineffective = self.claim_ineffective_reason(claim, effective_at)
            if ineffective is not None:
                non_effective.append(
                    {
                        "claimId": claim["claimId"],
                        "status": claim["status"],
                        "subject": copy.deepcopy(claim["subject"]),
                        "nonEffectiveReason": ineffective,
                    }
                )
                continue
            match = {
                "claim": copy.deepcopy(claim),
                "sha256": file_sha256(path),
                "path": path.relative_to(self.root).as_posix(),
            }
            if keyword_tier is not None:
                match["keywordTier"] = keyword_tier
            matches.append(match)
        if search is not None:
            matches = self.rank_matches(matches, search, top)
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "appliedFilters": applied_filters,
            "count": len(matches),
            "claims": matches,
            "nonEffectiveCount": len(non_effective),
            "nonEffectiveMatches": sorted(non_effective, key=lambda item: str(item["claimId"]))[:25],
        }

    # Claim-graph edges used by --related traversal and the search corpus.
    RELATION_EDGE_FIELDS = ("relatedClaims", "contradicts", "supersedes")

    @classmethod
    def claim_edges(cls, claim: dict[str, Any]) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        for field in cls.RELATION_EDGE_FIELDS:
            for ref in claim.get(field) or []:
                edges.append((field, str(ref)))
        if claim.get("supersededBy"):
            edges.append(("supersededBy", str(claim["supersededBy"])))
        return edges

    def related_query(
        self, claim_id: str, depth: int, at: datetime | None = None
    ) -> dict[str, Any]:
        """Breadth-first neighborhood of a claim over its reconciliation/relation edges.

        Unlike plain query this deliberately returns non-effective claims too — superseded,
        contested, and rejected history is exactly what the graph exists to expose. Every match
        carries `effective` plus `nonEffectiveReason` so a consumer can still fail closed.
        """

        if not 1 <= depth <= 5:
            raise ContractError("query --depth must be between 1 and 5")
        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        claims_by_id: dict[str, dict[str, Any]] = {}
        paths_by_id: dict[str, Path] = {}
        for path, claim in self.records(self.claims):
            claims_by_id[str(claim["claimId"])] = claim
            paths_by_id[str(claim["claimId"])] = path
        if claim_id not in claims_by_id:
            raise ContractError(f"Knowledge claim does not exist: {claim_id}")
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for source_id, claim in claims_by_id.items():
            for edge, target in self.claim_edges(claim):
                adjacency.setdefault(source_id, []).append((edge, target))
                adjacency.setdefault(target, []).append((edge, source_id))
        visited: dict[str, dict[str, Any]] = {claim_id: {"distance": 0}}
        frontier = [claim_id]
        for distance in range(1, depth + 1):
            next_frontier: list[str] = []
            for node in frontier:
                for edge, neighbor in adjacency.get(node, []):
                    if neighbor in visited:
                        continue
                    visited[neighbor] = {
                        "distance": distance,
                        "via": {"edge": edge, "from": node},
                    }
                    next_frontier.append(neighbor)
            frontier = next_frontier
        matches: list[dict[str, Any]] = []
        for neighbor_id, info in sorted(
            visited.items(), key=lambda item: (item[1]["distance"], item[0])
        ):
            claim = claims_by_id.get(neighbor_id)
            if claim is None:
                continue
            path = paths_by_id[neighbor_id]
            effective = self.claim_is_effective(claim, effective_at)
            match: dict[str, Any] = {
                "claim": copy.deepcopy(claim),
                "sha256": file_sha256(path),
                "path": path.relative_to(self.root).as_posix(),
                "distance": info["distance"],
                "effective": effective,
            }
            if "via" in info:
                match["via"] = info["via"]
            if not effective:
                match["nonEffectiveReason"] = self.non_effective_reason(claim, effective_at)
            matches.append(match)
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "count": len(matches),
            "claims": matches,
        }

    SEARCH_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

    @classmethod
    def search_tokens(cls, value: str) -> list[str]:
        """Delegates to the shared analyzer so both Knowledge layers tokenize identically.

        The former ASCII-only regex dropped Polish text entirely and reduced
        `Object__c.Field__c` to a stream of `c`; see scripts/text_analysis.py."""
        return analyze_text(value)

    def search_corpus(
        self, claim: dict[str, Any], claims_by_id: dict[str, dict[str, Any]]
    ) -> list[str]:
        """Token document for BM25: statement, description, keywords, subject, predicate,
        usage-registry targets (objects, fields, invokes), declared error-catalog messages, and
        the subject identities of every related/contradicting/superseding claim — so a search
        for an object name or a pasted error message also surfaces the claims connected to it."""

        parts: list[str] = [str(claim["statement"])]
        value = claim["assertion"]["value"]
        if isinstance(value, dict) and isinstance(value.get("description"), str):
            parts.append(value["description"])
        parts.extend(str(term) for term in claim.get("keywords") or [])
        parts.extend(str(term) for term in claim.get("candidateKeywords") or [])
        parts.append(str(claim["subject"]["kind"]))
        parts.append(str(claim["subject"]["identity"]))
        parts.append(str(claim["assertion"]["predicate"]))
        usage = self.claim_usage(claim)
        parts.extend(usage["objects"] + usage["fields"] + usage["invokes"])
        for catalog_entry in self.claim_error_catalog(claim):
            for key in ("errorMessage", "resolvedErrorMessage", "component"):
                if isinstance(catalog_entry.get(key), str):
                    parts.append(catalog_entry[key])
        for _, target in self.claim_edges(claim):
            neighbor = claims_by_id.get(target)
            if neighbor is not None:
                parts.append(str(neighbor["subject"]["identity"]))
        tokens: list[str] = []
        for part in parts:
            tokens.extend(self.search_tokens(part))
        return tokens

    def rank_matches(
        self, matches: list[dict[str, Any]], search: str, top: int
    ) -> list[dict[str, Any]]:
        """BM25 (k1=1.5, b=0.75) over the filtered survivors; zero-score matches drop out."""

        query_tokens = self.search_tokens(search)
        if not query_tokens or not matches:
            return []
        claims_by_id = {
            str(claim["claimId"]): claim for _, claim in self.records(self.claims)
        }
        documents = [self.search_corpus(match["claim"], claims_by_id) for match in matches]
        total = len(documents)
        average_length = sum(len(doc) for doc in documents) / total
        document_frequency: Counter[str] = Counter()
        for doc in documents:
            document_frequency.update(set(doc))
        k1, b = 1.5, 0.75
        ranked: list[tuple[float, dict[str, Any]]] = []
        for match, doc in zip(matches, documents):
            frequencies = Counter(doc)
            score = 0.0
            for term in query_tokens:
                occurrences = frequencies.get(term, 0)
                if not occurrences:
                    continue
                idf = math.log(
                    (total - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                    + 1
                )
                length_norm = 1 - b + b * (len(doc) / average_length if average_length else 1.0)
                score += idf * occurrences * (k1 + 1) / (occurrences + k1 * length_norm)
            if score > 0:
                ranked.append((score, match))
        ranked.sort(key=lambda item: (-item[0], item[1]["claim"]["claimId"]))
        results = []
        for score, match in ranked[:top]:
            match["score"] = round(score, 6)
            results.append(match)
        return results

    def explain(
        self, identity: str, kind: str | None = None, at: datetime | None = None
    ) -> dict[str, Any]:
        """One-call composite view of a subject: its claims, what it uses, what uses it.

        Aggregates only effective claims (same contract as query). `usedBy` matches the
        usage registry in reverse: every effective claim whose objects/fields/invokes contain
        the identity. `relations` lists the one-hop claim-graph edges of the subject's claims
        with each neighbor's subject identity resolved for readability.
        """

        if not identity:
            raise ContractError("explain requires a subject identity")
        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        needle = identity.casefold()
        claims_by_id: dict[str, dict[str, Any]] = {}
        effective_records: list[tuple[Path, dict[str, Any]]] = []
        for path, claim in self.records(self.claims):
            claims_by_id[str(claim["claimId"])] = claim
            if self.claim_is_effective(claim, effective_at):
                effective_records.append((path, claim))
        subject_claims: list[dict[str, Any]] = []
        used_by: list[dict[str, Any]] = []
        usage_totals: dict[str, set[str]] = {"objects": set(), "fields": set(), "invokes": set()}
        for path, claim in effective_records:
            subject = claim["subject"]
            is_subject = str(subject["identity"]).casefold() == needle and (
                kind is None or subject["kind"] == kind
            )
            if is_subject:
                subject_claims.append(
                    {
                        "claim": copy.deepcopy(claim),
                        "sha256": file_sha256(path),
                        "path": path.relative_to(self.root).as_posix(),
                    }
                )
                usage = self.claim_usage(claim)
                for category in usage_totals:
                    usage_totals[category].update(usage[category])
                continue
            usage = self.claim_usage(claim)
            via = [
                category
                for category in ("objects", "fields", "invokes")
                if needle in {name.casefold() for name in usage[category]}
            ]
            if via:
                used_by.append(
                    {
                        "claimId": claim["claimId"],
                        "claimType": claim["claimType"],
                        "subject": copy.deepcopy(claim["subject"]),
                        "via": via,
                    }
                )
        relations: list[dict[str, Any]] = []
        for entry in subject_claims:
            for edge, target in self.claim_edges(entry["claim"]):
                neighbor = claims_by_id.get(target)
                relations.append(
                    {
                        "claimId": entry["claim"]["claimId"],
                        "edge": edge,
                        "target": target,
                        **(
                            {
                                "targetSubject": copy.deepcopy(neighbor["subject"]),
                                "targetStatus": neighbor["status"],
                            }
                            if neighbor is not None
                            else {}
                        ),
                    }
                )
        claims_by_type: dict[str, list[dict[str, Any]]] = {}
        for entry in subject_claims:
            claims_by_type.setdefault(entry["claim"]["claimType"], []).append(entry)
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "identity": identity,
            **({"kind": kind} if kind is not None else {}),
            "claimCount": len(subject_claims),
            "claims": claims_by_type,
            "usage": {category: sorted(values) for category, values in usage_totals.items()},
            "usedBy": sorted(used_by, key=lambda item: item["claimId"]),
            "relations": relations,
        }

    TAXONOMY_TERM = re.compile(r"^[-*]\s+\**([^—:*]+?)\**\s*(?:[—:].*)?$")

    def approved_taxonomy_terms(self) -> set[str]:
        """Parse the approved terms out of the human-curated keyword taxonomy.

        Terms live as list items under the `## Terms` heading of
        `.ai/knowledge/keyword-taxonomy.md`: `- <term> — <what it covers>`. The taxonomy grows
        only through explicit human confirmation; this parser never writes.
        """

        path = self.root / ".ai/knowledge/keyword-taxonomy.md"
        if not path.is_file():
            return set()
        terms: set[str] = set()
        in_terms = False
        in_comment = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if in_comment:
                if "-->" in stripped:
                    in_comment = False
                continue
            if stripped.startswith("<!--"):
                in_comment = "-->" not in stripped
                continue
            if stripped.startswith("## "):
                in_terms = stripped == "## Terms"
                continue
            if not in_terms:
                continue
            match = self.TAXONOMY_TERM.match(stripped)
            if match:
                terms.add(match.group(1).strip())
        return terms

    def enforce_keyword_taxonomy(self, claim: dict[str, Any]) -> None:
        keywords = [str(term) for term in claim["keywords"]]
        if not keywords:
            return
        approved = self.approved_taxonomy_terms()
        unapproved = sorted(term for term in keywords if term not in approved)
        if unapproved:
            raise ContractError(
                "claim keywords must be approved terms from .ai/knowledge/keyword-taxonomy.md "
                f"(the taxonomy grows only through explicit human confirmation): {unapproved}; "
                "put model-suggested terms in candidateKeywords instead"
            )

    def keyword_report(self) -> dict[str, Any]:
        approved = self.approved_taxonomy_terms()
        candidates: dict[str, list[str]] = {}
        for _, claim in self.records(self.claims):
            for term in claim.get("candidateKeywords", []):
                candidates.setdefault(str(term), []).append(str(claim["claimId"]))
        report = [
            {
                "term": term,
                "count": len(claim_ids),
                "approved": term in approved,
                "claimIds": sorted(claim_ids),
            }
            for term, claim_ids in candidates.items()
        ]
        report.sort(key=lambda item: (-item["count"], item["term"]))
        return {
            "approvedTermCount": len(approved),
            "candidateTermCount": len(report),
            "candidateTerms": report,
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
        self.invalidate_cache()

    def write_proposed_claim(
        self, record: dict[str, Any], expected_revision: int, refresh_verified: bool = False
    ) -> None:
        self.validate_data(record, "knowledge-claim.schema.json", "proposed claim")
        self.validate_temporal_claim(record)
        if record["status"] != "proposed":
            raise ContractError("propose accepts only status: proposed")
        path = self.claim_path(record["claimId"])
        if path.exists():
            current = load_yaml(path)
            self.validate_data(current, "knowledge-claim.schema.json", str(path))
            if current["status"] != "proposed" and not (
                refresh_verified and current["status"] in {"verified", "stale"}
            ):
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
        self.invalidate_cache()

    def enforce_entry_home_freeze(
        self,
        claim: dict[str, Any],
        proposed_by_id: dict[str, Any],
        existing_evidence: dict[str, Any],
    ) -> None:
        """Repository-derived facts are proposed as Knowledge Entries, not claims.

        Frozen at T07 P2, but only where the entry store can actually hold the fact: the
        metadata type must have an implemented entry profile AND this workspace must have
        adopted the entry store. Freezing unconditionally would strand the repository facts
        of every metadata type whose profile has not shipped yet — a capability regression,
        not a migration. Legs backed by org, vendor, SME, or ADO receipts always stay here."""

        if claim["claimType"] not in ENTRY_HOME_CLAIM_TYPES:
            return
        metadata_type = claim.get("assertion", {}).get("value")
        metadata_type = metadata_type.get("metadataType") if isinstance(metadata_type, dict) else None
        if metadata_type not in ENTRY_PROFILED_METADATA_TYPES:
            return
        artifacts_root = self.root / ".ai/knowledge/artifacts"
        if not artifacts_root.is_dir() or not any(artifacts_root.rglob("*.md")):
            return
        source_types = set()
        for evidence_ref in claim["evidenceRefs"]:
            record = proposed_by_id.get(evidence_ref) or existing_evidence.get(evidence_ref)
            if isinstance(record, dict) and record.get("sourceType"):
                source_types.add(record["sourceType"])
        if source_types and source_types == {"metadata-repository"}:
            raise ContractError(
                f"{metadata_type} repository facts belong to the one-file Knowledge Entry store, "
                "which this workspace already uses: run "
                "`python scripts/knowledge_store.py entry-draft` and approve with "
                "/approve-drafts-knowledge (SAFE-CLAIM-001 v2). A claim here needs org, vendor, "
                "SME, or ADO evidence."
            )

    def propose(
        self,
        claim_file: Path,
        evidence_files: list[Path],
        expected_revision: int,
        refresh_verified: bool = False,
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
        self.enforce_keyword_taxonomy(claim)
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

        self.enforce_entry_home_freeze(claim, proposed_by_id, existing_evidence)
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
            if current["status"] != "proposed" and not (
                refresh_verified and current["status"] in {"verified", "stale"}
            ):
                # A verified claim whose source drifted or whose reviewBy passed has no other
                # lifecycle route back through review. --refresh-verified demotes it to a new
                # proposed revision against fresh evidence — fail-safe by construction: the
                # claim stops being effective until a human re-approves it, and the model
                # still cannot create any status other than proposed.
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
        self.write_proposed_claim(claim, expected_revision, refresh_verified)
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
            if self.derived_polarity(claim) == "negative" and (
                not evidence["completeness"]["enumerationComplete"]
                or not evidence["completeness"]["permissionsProven"]
            ):
                raise ContractError(
                    f"{evidence['evidenceId']}: negative claim lacks complete enumeration or permission proof"
                )
            if (
                self.derived_polarity(claim) == "negative"
                and age > timedelta(days=policy["negativeClaims"]["maxReviewAgeDays"])
            ):
                raise ContractError(f"{evidence['evidenceId']}: negative-claim evidence is stale")
        independent = {
            record.get("independenceKey", record["evidenceId"]) for record in evidence_records
        }
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
        self.invalidate_cache()
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
        self.invalidate_cache()
        return {"claimId": claim_id, "status": "verified", "revision": promoted["revision"]}

    def approve_claim(
        self,
        claim_id: str,
        expected_revision: int,
        decision: str = "verify",
        rationale: str | None = None,
        manifest_sha: str | None = None,
        render: bool = True,
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
        if manifest_sha is not None and decision != "verify":
            raise ContractError("manifest approval supports only the verify decision")
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
        if manifest_sha is not None:
            suffix = "MANIFEST-VERIFY"
            mechanism = "copilot-chat-manifest-confirmation"
            reference = (
                f"vscode-chat://approve-claim/manifest/sha256:{manifest_sha}/"
                f"{claim_id}/r{expected_revision}"
            )
        else:
            suffix = "CHAT-VERIFY" if decision == "verify" else "CHAT-REJECT"
            mechanism = "copilot-chat-confirmation"
            reference = f"vscode-chat://approve-claim/{claim_id}/r{expected_revision}"
        review_id = f"KREV-{claim_id[5:61]}-R{expected_revision}-{suffix}"
        receipt = {
            "mechanism": mechanism,
            "reference": reference,
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
            if render:
                self.render_indexes(check=False)
            return {
                "claimId": claim_id,
                "reviewId": review_id,
                "status": "verified",
                "revision": promoted["revision"],
                "reviewer": reviewer,
                "mechanism": mechanism,
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
        self.invalidate_cache()
        if render:
            self.render_indexes(check=False)
        return {
            "claimId": claim_id,
            "reviewId": review_id,
            "status": "rejected",
            "revision": rejected["revision"],
            "reviewer": reviewer,
            "mechanism": mechanism,
        }

    def approve_manifest(
        self, manifest_path: Path, rationale: str | None = None
    ) -> dict[str, Any]:
        """One human confirmation approves a draft manifest's low-risk claims.

        Owner decision 2026-07-17: only the claim types named in
        `promotion.manifestApproval.allowedClaimTypes` (component-inventory — generic existence
        records) qualify; everything else in the manifest is skipped with a reason and keeps the
        per-claim/25-spec approval path. Each promoted claim still gets its own immutable review,
        but every audit receipt carries the manifest's content digest under the
        `copilot-chat-manifest-confirmation` mechanism, so the one confirmation is the recorded
        approval for exactly the enumerated content. A claim whose canonical record drifted from
        the drafted file (revision or digest) is skipped, never approved.
        """

        policy = load_json(self.policy_path)
        manifest_policy = policy.get("promotion", {}).get("manifestApproval")
        if not isinstance(manifest_policy, dict):
            raise ContractError(
                "knowledge policy does not enable manifest approval "
                "(promotion.manifestApproval is absent)"
            )
        allowed_types = set(manifest_policy.get("allowedClaimTypes") or [])
        max_claims = int(manifest_policy.get("maxClaims", 0))
        if not allowed_types or max_claims < 1:
            raise ContractError("promotion.manifestApproval must name claim types and a cap")
        manifest = load_json(manifest_path)
        self.validate_data(
            manifest, "force-app-knowledge-draft-manifest.schema.json", "draft manifest"
        )
        manifest_sha = file_sha256(manifest_path)

        approvable: list[tuple[str, int]] = []
        skipped: list[dict[str, str]] = []

        def skip(claim_id: str, reason: str) -> None:
            skipped.append({"claimId": claim_id, "reason": reason})

        for bundle in manifest["bundles"]:
            claim_id = str(bundle["claimId"])
            claim_file = bundle.get("claimFile")
            if not claim_file:
                skip(claim_id, f"bundle has no drafted claim ({bundle.get('disposition')})")
                continue
            draft_path = self.root / claim_file
            if not draft_path.is_file():
                skip(claim_id, "drafted claim file is missing")
                continue
            draft = load_yaml(draft_path)
            claim_type = str(draft.get("claimType", ""))
            if claim_type not in allowed_types:
                skip(
                    claim_id,
                    f"claim type {claim_type} requires per-claim approval "
                    "(not in promotion.manifestApproval.allowedClaimTypes)",
                )
                continue
            canonical_path = self.claim_path(claim_id)
            if not canonical_path.is_file():
                skip(claim_id, "claim has not been proposed")
                continue
            canonical_claim = load_yaml(canonical_path)
            if canonical_claim.get("status") != "proposed":
                skip(claim_id, f"canonical status is {canonical_claim.get('status')}")
                continue
            if canonical_claim.get("revision") != draft.get("revision"):
                skip(claim_id, "canonical revision drifted from the drafted revision")
                continue
            if canonical_digest(canonical_claim) != canonical_digest(draft):
                skip(claim_id, "canonical claim content drifted from the drafted content")
                continue
            approvable.append((claim_id, int(canonical_claim["revision"])))

        if len(approvable) > max_claims:
            raise ContractError(
                f"manifest holds {len(approvable)} approvable claims, above the "
                f"promotion.manifestApproval.maxClaims cap of {max_claims}"
            )
        approved: list[dict[str, Any]] = []
        for claim_id, revision in approvable:
            result = self.approve_claim(
                claim_id,
                revision,
                decision="verify",
                rationale=rationale,
                manifest_sha=manifest_sha,
                render=False,
            )
            approved.append(
                {
                    "claimId": claim_id,
                    "reviewId": result["reviewId"],
                    "revision": result["revision"],
                }
            )
        if approved:
            self.render_indexes(check=False)
        return {
            "manifestSha256": manifest_sha,
            "approved": approved,
            "skipped": skipped,
            "counts": {"approved": len(approved), "skipped": len(skipped)},
            "mechanism": "copilot-chat-manifest-confirmation",
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

    def stale_report(self, warn_days: int = 30, at: datetime | None = None) -> dict[str, Any]:
        """Report verified claims whose freshness window has passed or is about to (read-only).

        A verified claim stops being an established fact once `reviewBy` passes (`is_fresh`). This
        surfaces `expired` claims (already past `reviewBy`, so no longer effective) and `expiring`
        claims (within `warn_days` of expiry) so a human can schedule re-verification. It never
        mutates status — transitioning a claim to `stale` remains a governed human review.
        """

        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        horizon = effective_at + timedelta(days=warn_days)
        expired: list[dict[str, Any]] = []
        expiring: list[dict[str, Any]] = []
        for _, claim in self.records(self.claims):
            if claim["status"] != "verified":
                continue
            review_by = parse_time(claim["reviewBy"], "claim reviewBy")
            entry = {
                "claimId": claim["claimId"],
                "claimType": claim["claimType"],
                "subject": claim["subject"],
                "reviewBy": claim["reviewBy"],
                "effective": self.claim_is_effective(claim, effective_at),
            }
            if review_by <= effective_at:
                expired.append(entry)
            elif review_by <= horizon:
                expiring.append(entry)
        expired.sort(key=lambda item: (item["reviewBy"], item["claimId"]))
        expiring.sort(key=lambda item: (item["reviewBy"], item["claimId"]))
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "warnDays": warn_days,
            "expiredCount": len(expired),
            "expiringCount": len(expiring),
            "expired": expired,
            "expiring": expiring,
        }

    HARD_CITATION_STATUSES = {"rejected", "superseded"}

    def verify_entry_citations(self, entry_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Advisory verdicts for cited Knowledge Entries (SAFE-CLAIM-001 v2 entryRefs).

        Mirrors verify_citations for the entry layer so an envelope carrying both citation
        kinds is checked end to end instead of half-checked."""

        try:
            from scripts import knowledge_store
        except ModuleNotFoundError:  # invoked as a script
            import knowledge_store  # type: ignore
        results: list[dict[str, Any]] = []
        for reference in entry_refs:
            entry_id = str(reference.get("entryId", ""))
            record: dict[str, Any] = {"entryId": entry_id}
            lane = knowledge_store.lane_for_identity(self.root, entry_id) if entry_id else None
            if lane is None:
                record.update(verdict="missing", severity="invalid", reason="no entry with this identity")
            elif lane["lane"] == "revoked":
                record.update(verdict="revoked", severity="invalid", reason="approval was revoked")
            elif lane["lane"] == "draft":
                record.update(verdict="not-approved", severity="invalid", reason="entry is still a draft")
            elif lane["lane"] == "not-effective":
                record.update(
                    verdict="not-effective",
                    severity="invalid",
                    reason="; ".join(lane.get("problems", [])) or "entry failed its integrity checks",
                )
            elif reference.get("reviewedContentDigest") and lane.get("reviewedContentDigest") != reference["reviewedContentDigest"]:
                record.update(
                    verdict="digest-mismatch",
                    severity="invalid",
                    reason="cited content digest is not the entry's current approved digest",
                )
            elif lane["lane"] == "approved-drifted":
                record.update(
                    verdict="drifted",
                    severity="warning",
                    reason="source moved on since approval; re-approve before citing as current",
                )
            else:
                record.update(verdict="current", severity="ok", reason="approved-current")
            results.append(record)
        return results

    def verify_citations(
        self,
        claim_refs: list[dict[str, Any]],
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """Validate cited claim references against current canonical state (read-only, advisory).

        Each reference (from a handoff/output envelope `claimRefs` entry, or a `<claimId>:<revision>`
        spec) is checked for existence, revision/sha match against the current claim file, and
        effectiveness. Citing a missing/rejected/superseded claim or a drifted snapshot is `invalid`;
        citing a stale or contested claim is a `warning`. Nothing is mutated.
        """

        effective_at = self.at_time(at)
        self.validate_all(effective_at, enforce_current=False)
        citations: list[dict[str, Any]] = []
        for ref in claim_refs:
            claim_id = str(ref["claimId"])
            revision = ref.get("revision")
            sha = ref.get("sha256")
            entry: dict[str, Any] = {"claimId": claim_id}
            if revision is not None:
                entry["revision"] = revision
            path = self.claim_path(claim_id)
            if not path.is_file():
                verdict, severity, reason = "missing", "invalid", "no canonical claim with this id"
            else:
                claim = load_yaml(path)
                if sha is not None and file_sha256(path) != sha:
                    verdict, severity, reason = (
                        "sha-mismatch", "invalid",
                        "cited snapshot digest does not match the current claim",
                    )
                elif revision is not None and int(claim["revision"]) != int(revision):
                    verdict, severity, reason = (
                        "revision-mismatch", "invalid",
                        f"cited revision {revision} != current revision {claim['revision']}",
                    )
                elif not self.claim_is_effective(claim, effective_at):
                    verdict = "not-effective"
                    reason = self.non_effective_reason(claim, effective_at)
                    severity = (
                        "invalid"
                        if claim.get("status") in self.HARD_CITATION_STATUSES
                        else "warning"
                    )
                else:
                    verdict, severity, reason = "ok", "ok", None
            entry["verdict"] = verdict
            entry["severity"] = severity
            if reason:
                entry["reason"] = reason
            citations.append(entry)
        counts = Counter(item["severity"] for item in citations)
        return {
            "effectiveAt": effective_at.isoformat().replace("+00:00", "Z"),
            "citationCount": len(citations),
            "counts": {
                "ok": counts.get("ok", 0),
                "warning": counts.get("warning", 0),
                "invalid": counts.get("invalid", 0),
            },
            "citations": citations,
        }

    @staticmethod
    def entry_refs_from_envelope(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        """Optional entryRefs array from an output/handoff/change-record envelope."""
        raw = envelope.get("entryRefs") or []
        return [item if isinstance(item, dict) else {"entryId": str(item)} for item in raw]

    @staticmethod
    def claim_refs_from_envelope(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize an envelope's claimRefs (objects or bare id strings) to dicts with claimId."""

        raw = envelope.get("claimRefs")
        if not isinstance(raw, list):
            raise ContractError("envelope has no claimRefs array to verify")
        refs: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                refs.append({"claimId": item})
            elif isinstance(item, dict) and "claimId" in item:
                refs.append(item)
            else:
                raise ContractError(f"unrecognized claimRefs entry: {item!r}")
        return refs

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
        if domain == "automation-map" and claims:
            by_object: dict[str, set[str]] = {}
            for claim in claims:
                for obj in self.claim_usage(claim)["objects"]:
                    by_object.setdefault(obj, set()).add(str(claim["claimId"]))
            if by_object:
                lines.extend(
                    [
                        "",
                        "## Automations by object",
                        "",
                        "Reverse index derived from the source-declared component usage registry. Includes "
                        "non-effective claims; confirm status in the tables above before relying on a row.",
                        "",
                        "| Object | Automations |",
                        "|---|---|",
                    ]
                )
                for obj in sorted(by_object):
                    automations = ", ".join(
                        f"[{claim_id}](claims/{claim_id}.yaml)"
                        for claim_id in sorted(by_object[obj])
                    )
                    lines.append(f"| {self.escape_table(obj)} | {automations} |")
        lines.extend(["", "<!-- END GENERATED CLAIM INDEX -->", ""])
        return "\n".join(lines)

    def claims_index_row(
        self, claim: dict[str, Any], path: Path, at: datetime
    ) -> dict[str, Any]:
        row = {
            "claimId": claim["claimId"],
            "revision": claim["revision"],
            "domain": claim["domain"],
            "claimType": claim["claimType"],
            "subject": claim["subject"],
            "predicate": claim["assertion"]["predicate"],
            "status": claim["status"],
            "effective": self.claim_is_effective(claim, at),
            "reviewBy": claim["reviewBy"],
            "keywords": claim["keywords"],
            "candidateKeywords": claim.get("candidateKeywords", []),
            "statement": claim["statement"],
            "evidenceRefs": claim["evidenceRefs"],
            "path": path.relative_to(self.root).as_posix(),
        }
        if claim.get("feature"):
            row["feature"] = claim["feature"]
        value = claim["assertion"]["value"]
        if isinstance(value, dict) and isinstance(value.get("description"), str):
            row["descriptionExcerpt"] = value["description"][:240]
        usage = self.claim_usage(claim)
        if usage["objects"]:
            row["usesObjects"] = usage["objects"]
        if usage["fields"]:
            row["usesFields"] = usage["fields"]
        emits_errors: list[str] = []
        for catalog_entry in self.claim_error_catalog(claim):
            for key in ("errorMessage", "resolvedErrorMessage"):
                message = catalog_entry.get(key)
                if isinstance(message, str) and message:
                    text = message[:160]
                    if text not in emits_errors:
                        emits_errors.append(text)
        if emits_errors:
            row["emitsErrors"] = emits_errors
        return row

    def rendered_feature_map(self, claims: list[dict[str, Any]], at: datetime) -> str:
        """Group feature-tagged claims under each feature heading.

        Generated deterministically alongside the domain views. A claim may carry several feature
        tags and therefore appear under more than one heading; only effective verified rows are
        established facts. The feature tag is written by the feature documentor and is advisory
        grouping metadata, never part of claim identity.
        """

        title = "Feature Map"
        description = (
            "Generated view grouping canonical claims by the feature-membership tag written by the\n"
            "feature documentor. Do not hand-edit. A claim may appear under several features; only\n"
            "rows marked effective are established current facts."
        )
        by_feature: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            for feature in claim.get("feature", []) or []:
                by_feature.setdefault(str(feature), []).append(claim)
        lines = [
            f"# {title} — Generated Claim Index",
            "",
            description,
            "",
            "<!-- BEGIN GENERATED CLAIM INDEX -->",
            "",
        ]
        if not by_feature:
            lines.append("_No feature-tagged claims are indexed._")
        else:
            for feature in sorted(by_feature):
                lines.extend(
                    [
                        f"## {self.escape_table(feature)}",
                        "",
                        "| Claim | Type | Subject | Status | Effective | Structured fact |",
                        "|---|---|---|---|---|---|",
                    ]
                )
                for claim in sorted(by_feature[feature], key=lambda item: item["claimId"]):
                    effective = "yes" if self.claim_is_effective(claim, at) else "no"
                    subject = f"{claim['subject']['kind']}:{claim['subject']['identity']}"
                    lines.append(
                        "| "
                        f"[{claim['claimId']}](claims/{claim['claimId']}.yaml) | "
                        f"{claim['claimType']} | {self.escape_table(subject)} | "
                        f"{claim['status']} | {effective} | "
                        f"{self.escape_table(self.structured_fact(claim))} |"
                    )
                lines.append("")
            lines.pop()  # trailing blank before the end marker is added below
        lines.extend(["", "<!-- END GENERATED CLAIM INDEX -->", ""])
        return "\n".join(lines)

    def rendered_claims_index(self, rows: list[dict[str, Any]]) -> str:
        index = {
            "schemaVersion": 1,
            "kind": "knowledge-claims-index",
            "claimCount": len(rows),
            "claims": sorted(rows, key=lambda row: str(row["claimId"])),
        }
        self.validate_data(index, "knowledge-claims-index.schema.json", "claims index")
        return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def render_indexes(self, check: bool) -> dict[str, Any]:
        effective_at = self.at_time()
        self.validate_all(effective_at, enforce_current=False)
        by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in DOMAIN_VIEWS}
        all_claims: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        for path, claim in self.records(self.claims):
            self.validate_data(claim, "knowledge-claim.schema.json", str(path))
            by_domain[claim["domain"]].append(claim)
            all_claims.append(claim)
            index_rows.append(self.claims_index_row(claim, path, effective_at))
        drift: list[str] = []
        rendered = [
            (self.root / ".ai/knowledge" / f"{domain}.md", self.rendered_domain(domain, claims, effective_at))
            for domain, claims in by_domain.items()
        ]
        rendered.append(
            (self.root / ".ai/knowledge/feature-map.md", self.rendered_feature_map(all_claims, effective_at))
        )
        rendered.append(
            (self.root / ".ai/knowledge/claims-index.json", self.rendered_claims_index(index_rows))
        )
        for path, expected in rendered:
            if check:
                actual = path.read_text(encoding="utf-8") if path.is_file() else ""
                if actual != expected:
                    drift.append(path.relative_to(self.root).as_posix())
            else:
                atomic_text_write(path, expected)
        if drift:
            raise ContractError(f"generated Knowledge indexes drifted: {drift}")
        return {
            "domains": len(by_domain),
            "claims": len(index_rows),
            "mode": "check" if check else "write",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")

    propose = commands.add_parser("propose")
    propose.add_argument("--claim-file", required=True)
    propose.add_argument("--evidence-file", action="append", default=[])
    propose.add_argument("--expected-revision", required=True, type=int)
    propose.add_argument(
        "--refresh-verified",
        action="store_true",
        help="allow replacing a verified/stale claim with a new proposed revision (refresh workflow)",
    )

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
    approve.add_argument(
        "--manifest",
        help="approve a draft manifest's component-inventory claims in one confirmation "
        "(policy promotion.manifestApproval; other claim types are skipped with reasons)",
    )

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
    query.add_argument(
        "--keyword",
        help="match one approved keyword or candidate keyword (exact term, case-insensitive)",
    )
    query.add_argument(
        "--text",
        help="substring match over claim statement and component description",
    )
    query.add_argument(
        "--feature",
        help="match one feature-membership tag (exact name, case-insensitive)",
    )
    query.add_argument(
        "--uses-object",
        help="match claims whose subject uses this object (from the component usage registry)",
    )
    query.add_argument(
        "--uses-field",
        help="match claims whose subject uses this Object.Field (from the component usage registry)",
    )
    query.add_argument(
        "--invokes",
        help="match claims whose subject invokes this Apex class, subflow, or action",
    )
    query.add_argument(
        "--related",
        help="traverse the claim graph (relatedClaims/contradicts/supersedes/supersededBy) "
        "from this claim ID; includes non-effective claims, annotated",
    )
    query.add_argument(
        "--depth",
        type=int,
        default=1,
        help="graph hops for --related (1-5, default 1)",
    )
    query.add_argument(
        "--search",
        help="ranked full-text search (BM25) over statements, descriptions, keywords, "
        "subject identities, and usage-registry targets",
    )
    query.add_argument(
        "--top",
        type=int,
        default=10,
        help="maximum ranked results for --search (default 10)",
    )
    query.add_argument("--at")

    explain = commands.add_parser(
        "explain",
        help="composite view of one subject: its effective claims, usage, reverse usage, and relations",
    )
    explain.add_argument("--identity", required=True)
    explain.add_argument("--kind")
    explain.add_argument("--at")

    render = commands.add_parser("render-indexes")
    render.add_argument("--check", action="store_true")

    commands.add_parser(
        "keyword-report",
        help="aggregate candidateKeywords across claims for a human taxonomy-curation session",
    )

    stale = commands.add_parser(
        "stale-report",
        help="list verified claims past or approaching their reviewBy freshness deadline (read-only)",
    )
    stale.add_argument(
        "--warn-days",
        type=int,
        default=30,
        help="also report claims expiring within this many days (default 30)",
    )
    stale.add_argument("--at")

    citations = commands.add_parser(
        "verify-citations",
        help="check an envelope's cited claimRefs resolve to existing, effective claims (advisory)",
    )
    citations.add_argument(
        "--envelope", help="path to a handoff/output envelope JSON whose claimRefs are verified"
    )
    citations.add_argument(
        "--claim-ref",
        action="append",
        default=[],
        metavar="KCLM-...[:REV]",
        help="verify a single claim id, optionally :revision (repeatable)",
    )
    citations.add_argument("--at")
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
                refresh_verified=args.refresh_verified,
            )
        elif args.command == "review":
            result = registry.record_review(registry.contained_input(args.review_file))
        elif args.command == "promote":
            result = registry.promote(args.claim_id, args.review_id, args.expected_revision)
        elif args.command == "approve-claim":
            if args.manifest is not None:
                if (
                    args.claim_id is not None
                    or args.expected_revision is not None
                    or args.claim_spec
                ):
                    raise ContractError(
                        "--manifest cannot be combined with --claim-id/--expected-revision/--claim-spec"
                    )
                if args.decision != "verify":
                    raise ContractError("manifest approval supports only the verify decision")
                result = registry.approve_manifest(
                    registry.contained_input(args.manifest), args.rationale
                )
            elif args.claim_spec:
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
                keyword=args.keyword,
                text=args.text,
                feature=args.feature,
                uses_object=args.uses_object,
                uses_field=args.uses_field,
                invokes=args.invokes,
                related=args.related,
                depth=args.depth,
                search=args.search,
                top=args.top,
                at=parse_time(args.at, "query --at") if args.at else None,
            )
        elif args.command == "explain":
            result = registry.explain(
                args.identity,
                kind=args.kind,
                at=parse_time(args.at, "explain --at") if args.at else None,
            )
        elif args.command == "render-indexes":
            result = registry.render_indexes(args.check)
        elif args.command == "keyword-report":
            result = registry.keyword_report()
        elif args.command == "stale-report":
            result = registry.stale_report(
                args.warn_days,
                at=parse_time(args.at, "stale-report --at") if args.at else None,
            )
        elif args.command == "verify-citations":
            if bool(args.envelope) == bool(args.claim_ref):
                raise ContractError(
                    "verify-citations requires exactly one of --envelope or --claim-ref"
                )
            entry_refs: list[dict[str, Any]] = []
            if args.envelope:
                envelope = load_json(registry.contained_input(args.envelope))
                claim_refs = registry.claim_refs_from_envelope(envelope)
                entry_refs = registry.entry_refs_from_envelope(envelope)
            else:
                claim_refs = []
                for spec in args.claim_ref:
                    claim_id, separator, revision = spec.rpartition(":")
                    if separator and revision.isdigit():
                        claim_refs.append({"claimId": claim_id, "revision": int(revision)})
                    else:
                        claim_refs.append({"claimId": spec})
            result = registry.verify_citations(
                claim_refs,
                at=parse_time(args.at, "verify-citations --at") if args.at else None,
            )
            if entry_refs:
                entry_results = registry.verify_entry_citations(entry_refs)
                result["entryCitations"] = entry_results
                result["entryInvalid"] = sum(
                    1 for item in entry_results if item["severity"] == "invalid"
                )
                result["entryWarnings"] = sum(
                    1 for item in entry_results if item["severity"] == "warning"
                )
        else:  # pragma: no cover - argparse guarantees a known command
            raise ContractError(f"unsupported command: {args.command}")
    except ContractError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
