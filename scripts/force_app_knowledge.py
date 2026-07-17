#!/usr/bin/env python3
"""Inventory root force-app and draft governed Knowledge claim/evidence candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.force_app_knowledge by unit tests
    from scripts.schema_format import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "force-app"
CACHE_ROOT = ROOT / ".cache/knowledge-proposals"
INVENTORY_PATH = CACHE_ROOT / "force-app-inventory.json"
DRAFT_ROOT = CACHE_ROOT / "force-app-drafts"
SCHEMA_VERSION = 1
COLLECTOR_VERSION = "1.0.0"
CUSTOM_OBJECT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:__c|__mdt|__e|__x))\b")
# Custom-field token inside a formula/expression (validation rules). Standard fields cannot be told
# apart from function names by source alone, so the usage registry records custom fields only.
FORMULA_FIELD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*__c)\b")
# Upper bound on emitted usage references per component (permission sets and layouts can enumerate
# hundreds of field grants). The total is always recorded in facts even when references are capped.
MAX_USAGE_REFS = 300
TRIGGER_RE = re.compile(
    r"\btrigger\s+([A-Za-z][A-Za-z0-9_]*)\s+on\s+([A-Za-z][A-Za-z0-9_]*)\s*\(([^)]+)\)",
    re.IGNORECASE | re.MULTILINE,
)
CLASS_RE = re.compile(
    r"\b(?:public|private|protected|global)?\s*(?:with\s+sharing|without\s+sharing|inherited\s+sharing)?\s*"
    r"(?:abstract\s+|virtual\s+)?(class|interface|enum)\s+([A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
APEX_IMPORT_RE = re.compile(r"@salesforce/apex/([A-Za-z0-9_]+\.[A-Za-z0-9_]+)")
SCHEMA_IMPORT_RE = re.compile(r"@salesforce/schema/([A-Za-z0-9_.]+)")
AURA_CONTROLLER_RE = re.compile(r"\bcontroller\s*=\s*[\"']([A-Za-z][A-Za-z0-9_]*)[\"']")
# Source-token heuristics for Apex usage. These read declared source only and are best-effort: they
# do not resolve variable types or dynamic SOQL, so the automation-inventory claim records an
# explicit heuristic limitation.
SOQL_FROM_RE = re.compile(r"\bFROM\s+([A-Za-z][A-Za-z0-9_]*)", re.IGNORECASE)
DML_RE = re.compile(r"\b(insert|update|upsert|delete|undelete)\b", re.IGNORECASE)
APEX_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\.[A-Za-z_][A-Za-z0-9_]*\s*\(")
# Common platform types/namespaces excluded from the invokes-class heuristic to reduce noise.
APEX_SYSTEM_TYPES = frozenset(
    {
        "System", "Database", "Schema", "String", "Integer", "Decimal", "Double", "Boolean",
        "Date", "Datetime", "Time", "Math", "JSON", "Test", "Limits", "UserInfo", "Trigger",
        "List", "Map", "Set", "Id", "Blob", "Long", "Object", "SObject", "Type", "Label",
        "ApexPages", "PageReference", "Http", "HttpRequest", "HttpResponse", "Messaging", "Address",
        "Pattern", "Matcher", "Exception", "DmlException", "SObjectType", "SObjectField",
    }
)

# Reference kinds whose target names an object (its head token before any `.field`). Used by the
# feature crawl to associate an automation/UI component with the objects it touches. subflow,
# action, apex-method, apex-controller, invokes-apex, invokes-class, and related-list targets name
# automations/methods/related lists, not objects.
OBJECT_REF_KINDS = frozenset(
    {
        "relationship",
        "operates-on",
        "object-token",
        "schema",
        "reads-field",
        "writes-field",
        "references-field",
        "places-field",
        "grants-field-permission",
        "queries-object",
        "dml-object",
        "grants-object-permission",
    }
)
# Reference kinds derived via regex source-token heuristics rather than structural XML/JS parsing
# (Apex object tokens, SOQL FROM targets, and invoked-class names). Best-effort: dynamic references
# and unresolved variable types may be missing or approximate. Drives component-relation claims'
# heuristic flag and assurance level.
HEURISTIC_REF_KINDS = frozenset({"object-token", "queries-object", "invokes-class"})
AUTOMATION_TYPES = frozenset(
    {"Flow", "ApexClass", "ApexTrigger", "ApprovalProcess", "ValidationRule"}
)
UI_TYPES = frozenset(
    {"LightningComponentBundle", "AuraDefinitionBundle", "ApexPage", "FlexiPage", "Layout", "CustomTab"}
)


class KnowledgeBuildError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise KnowledgeBuildError("--observed-at must include a timezone")
    return value.astimezone(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def direct_text(element: ET.Element, name: str) -> str | None:
    for child in list(element):
        if local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def descendant_texts(element: ET.Element, name: str) -> list[str]:
    values = {
        child.text.strip()
        for child in element.iter()
        if local_name(child.tag) == name and child.text and child.text.strip()
    }
    return sorted(values)


def boolean(raw: str | None) -> bool | None:
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return None


def compact(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None and value != []}


def path_line(path: Path, needle: str | None) -> int | None:
    if not needle:
        return None
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if needle in line:
            return number
    return None


def object_from_path(path: Path) -> str:
    parts = path.parts
    index = parts.index("objects")
    return parts[index + 1]


def stable_id(prefix: str, identity: str, discriminator: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", identity.upper()).strip("-") or "ITEM"
    suffix = digest_bytes(f"{identity}|{discriminator}".encode("utf-8"))[:10].upper()
    maximum_slug = 80 - len(prefix) - len(suffix) - 2
    return f"{prefix}-{slug[:maximum_slug].rstrip('-')}-{suffix}"


def feature_slug(feature: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", feature.strip().lower()).strip("-")
    if not slug:
        raise KnowledgeBuildError("feature name must contain at least one alphanumeric character")
    return slug


class ForceAppKnowledge:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()
        self.source_root = self.root / "force-app"
        self.cache_root = self.root / ".cache/knowledge-proposals"
        self.inventory_path = self.cache_root / "force-app-inventory.json"
        self.draft_root = self.cache_root / "force-app-drafts"
        self.dossier_root = self.root / "output/feature-dossiers"

    def git(self, *args: str, check: bool = True) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=False
        )
        if check and completed.returncode:
            raise KnowledgeBuildError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout.strip()

    def repository_commit(self) -> str:
        commit = self.git("rev-parse", "HEAD")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise KnowledgeBuildError("repository HEAD is not a full Git commit")
        return commit

    def source_status(self) -> list[str]:
        output = self.git("status", "--porcelain", "--", "force-app")
        return output.splitlines() if output else []

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def component(
        self,
        metadata_type: str,
        name: str,
        path: Path,
        facts: dict[str, Any],
        references: list[dict[str, str]] | None = None,
        needle: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": f"{metadata_type}:{name}",
            "metadataType": metadata_type,
            "name": name,
            "path": self.relative(path),
            "sha256": file_digest(path),
            "facts": compact(facts),
            "references": sorted(
                references or [], key=lambda item: (item["kind"], item["target"])
            ),
        }
        line = path_line(path, needle)
        if line is not None:
            result["line"] = line
        return result

    def parse_xml(self, path: Path) -> ET.Element:
        return ET.parse(path).getroot()

    def parse_object(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = object_from_path(path)
        label = direct_text(root, "label")
        return self.component(
            "CustomObject",
            name,
            path,
            {
                "label": label,
                "pluralLabel": direct_text(root, "pluralLabel"),
                "deploymentStatus": direct_text(root, "deploymentStatus"),
                "sharingModel": direct_text(root, "sharingModel"),
            },
            needle=f"<label>{label}</label>" if label else None,
        )

    def parse_field(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        object_name = object_from_path(path)
        field_name = direct_text(root, "fullName") or path.name.removesuffix(
            ".field-meta.xml"
        )
        targets = descendant_texts(root, "referenceTo")
        return self.component(
            "CustomField",
            f"{object_name}.{field_name}",
            path,
            {
                "object": object_name,
                "fullName": field_name,
                "label": direct_text(root, "label"),
                "type": direct_text(root, "type"),
                "required": boolean(direct_text(root, "required")),
                "unique": boolean(direct_text(root, "unique")),
                "relationshipName": direct_text(root, "relationshipName"),
                "referenceTo": targets,
                "formula": direct_text(root, "formula"),
            },
            [{"kind": "relationship", "target": target} for target in targets],
            f"<fullName>{field_name}</fullName>",
        )

    # Flow data elements and the field-usage polarity each implies. Read from source only: which
    # objects/fields the Flow declares it touches, never runtime values. recordDeletes filters are
    # counted as writes because the element mutates records.
    FLOW_DATA_ELEMENTS = {
        "recordLookups": "reads-field",
        "recordCreates": "writes-field",
        "recordUpdates": "writes-field",
        "recordDeletes": "writes-field",
    }

    @staticmethod
    def _flow_element_fields(element: ET.Element) -> set[str]:
        """Field API names a Flow data element declares (queried fields, assignments, filters)."""

        fields: set[str] = set(descendant_texts(element, "queriedFields"))
        for child in element.iter():
            if local_name(child.tag) == "field" and child.text and child.text.strip():
                fields.add(child.text.strip())
        return fields

    def parse_flow(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        starts = [item for item in root.iter() if local_name(item.tag) == "start"]
        start = starts[0] if starts else root
        object_name = direct_text(start, "object") or direct_text(root, "object")
        references = []
        if object_name:
            references.append({"kind": "operates-on", "target": object_name})
        references.extend(
            {"kind": "subflow", "target": value}
            for value in descendant_texts(root, "flowName")
        )
        references.extend(
            {"kind": "action", "target": value}
            for value in descendant_texts(root, "actionName")
        )
        # Usage registry: objects and fields the Flow's data elements declare they read or write.
        referenced_objects: set[str] = set()
        if object_name:
            referenced_objects.add(object_name)
        for tag, kind in self.FLOW_DATA_ELEMENTS.items():
            for element in (item for item in root.iter() if local_name(item.tag) == tag):
                element_object = direct_text(element, "object")
                if element_object:
                    referenced_objects.add(element_object)
                for field in self._flow_element_fields(element):
                    target = f"{element_object}.{field}" if element_object else field
                    references.append({"kind": kind, "target": target})
        # Invoked Apex: actionCalls whose actionType is apex name a class the Flow depends on.
        for element in (item for item in root.iter() if local_name(item.tag) == "actionCalls"):
            if direct_text(element, "actionType") == "apex":
                action = direct_text(element, "actionName")
                if action:
                    references.append({"kind": "invokes-apex", "target": action})
        element_counts = {
            key: sum(1 for item in root.iter() if local_name(item.tag) == tag)
            for key, tag in (
                ("decisions", "decisions"),
                ("loops", "loops"),
                ("screens", "screens"),
                ("subflows", "subflows"),
                ("actionCalls", "actionCalls"),
                ("recordLookups", "recordLookups"),
                ("recordCreates", "recordCreates"),
                ("recordUpdates", "recordUpdates"),
                ("recordDeletes", "recordDeletes"),
            )
        }
        name = path.name.removesuffix(".flow-meta.xml")
        return self.component(
            "Flow",
            name,
            path,
            {
                "label": direct_text(root, "label"),
                "status": direct_text(root, "status"),
                "processType": direct_text(root, "processType"),
                "object": object_name,
                "triggerType": direct_text(start, "triggerType"),
                "recordTriggerType": direct_text(start, "recordTriggerType"),
                "referencedObjects": sorted(referenced_objects),
                "elementCounts": {key: value for key, value in element_counts.items() if value}
                or None,
            },
            references,
            name,
        )

    def parse_apex(self, path: Path, metadata_type: str) -> dict[str, Any]:
        source = path.read_text(encoding="utf-8", errors="replace")
        references = [
            {"kind": "object-token", "target": value}
            for value in sorted(set(CUSTOM_OBJECT_RE.findall(source)))
        ]
        if metadata_type == "ApexTrigger":
            match = TRIGGER_RE.search(source)
            name = match.group(1) if match else path.stem
            facts: dict[str, Any] = {}
            if match:
                facts = {
                    "object": match.group(2),
                    "events": sorted(value.strip() for value in match.group(3).split(",")),
                }
                references.append({"kind": "operates-on", "target": match.group(2)})
        else:
            match = CLASS_RE.search(source)
            name = match.group(2) if match else path.stem
            facts = {"declarationKind": match.group(1).lower() if match else "unknown"}
        # Usage registry (source-token heuristic): objects queried, DML verbs used, classes invoked.
        soql_objects = sorted(set(SOQL_FROM_RE.findall(source)))
        references.extend({"kind": "queries-object", "target": value} for value in soql_objects)
        dml_operations = sorted({value.lower() for value in DML_RE.findall(source)})
        invoked = sorted(
            value
            for value in set(APEX_CALL_RE.findall(source))
            if value not in APEX_SYSTEM_TYPES and value != name
        )
        references.extend({"kind": "invokes-class", "target": value} for value in invoked)
        if soql_objects:
            facts["soqlObjects"] = soql_objects
        if dml_operations:
            facts["dmlOperations"] = dml_operations
        return self.component(metadata_type, name, path, facts, references, name)

    def parse_lwc(self, bundle: Path) -> dict[str, Any]:
        files = sorted(path for path in bundle.rglob("*") if path.is_file())
        meta = next((path for path in files if path.name.endswith(".js-meta.xml")), files[0])
        facts: dict[str, Any] = {}
        if meta.name.endswith(".js-meta.xml"):
            root = self.parse_xml(meta)
            facts = {
                "isExposed": boolean(direct_text(root, "isExposed")),
                "targets": descendant_texts(root, "target"),
                "masterLabel": direct_text(root, "masterLabel"),
            }
        references: list[dict[str, str]] = []
        for path in files:
            if path.suffix == ".js":
                source = path.read_text(encoding="utf-8", errors="replace")
                references.extend(
                    {"kind": "apex-method", "target": value}
                    for value in APEX_IMPORT_RE.findall(source)
                )
                references.extend(
                    {"kind": "schema", "target": value}
                    for value in SCHEMA_IMPORT_RE.findall(source)
                )
        return self.component(
            "LightningComponentBundle", bundle.name, meta, facts, references, "<isExposed>"
        )

    def parse_aura(self, bundle: Path) -> dict[str, Any]:
        files = sorted(path for path in bundle.rglob("*") if path.is_file())
        primary = next((path for path in files if path.suffix == ".cmp"), files[0])
        controllers = set()
        for path in files:
            controllers.update(
                AURA_CONTROLLER_RE.findall(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            )
        return self.component(
            "AuraDefinitionBundle",
            bundle.name,
            primary,
            {"definitionTypes": sorted({path.suffix.lstrip(".") for path in files})},
            [{"kind": "apex-controller", "target": value} for value in controllers],
            bundle.name,
        )

    def parse_integration(self, path: Path, metadata_type: str) -> dict[str, Any]:
        root = self.parse_xml(path)
        endpoint = direct_text(root, "url") or direct_text(root, "endpoint")
        host = urlsplit(endpoint).hostname if endpoint else None
        suffixes = {
            "NamedCredential": ".namedCredential-meta.xml",
            "ExternalCredential": ".externalCredential-meta.xml",
            "RemoteSiteSetting": ".remoteSite-meta.xml",
        }
        name = path.name.removesuffix(suffixes[metadata_type])
        return self.component(
            metadata_type,
            name,
            path,
            {
                "label": direct_text(root, "label") or direct_text(root, "masterLabel"),
                "endpointHost": host,
            },
            needle=host or name,
        )

    def parse_approval_process(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".approvalProcess-meta.xml")
        object_name = name.split(".", 1)[0] if "." in name else None
        steps = [item for item in root.iter() if local_name(item.tag) == "approvalStep"]
        references = []
        if object_name:
            references.append({"kind": "operates-on", "target": object_name})
        return self.component(
            "ApprovalProcess",
            name,
            path,
            {
                "object": object_name,
                "label": direct_text(root, "label"),
                "active": boolean(direct_text(root, "active")),
                "stepCount": len(steps),
                "entryCriteriaPresent": any(
                    local_name(item.tag) == "entryCriteria" for item in root.iter()
                ),
            },
            references,
            name,
        )

    def parse_validation_rule(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        try:
            object_name: str | None = object_from_path(path)
        except ValueError:
            object_name = None
        rule = path.name.removesuffix(".validationRule-meta.xml")
        name = f"{object_name}.{rule}" if object_name else rule
        formula = direct_text(root, "errorConditionFormula") or ""
        references: list[dict[str, str]] = []
        if object_name:
            references.append({"kind": "operates-on", "target": object_name})
            for field in sorted(set(FORMULA_FIELD_RE.findall(formula))):
                references.append({"kind": "references-field", "target": f"{object_name}.{field}"})
        return self.component(
            "ValidationRule",
            name,
            path,
            {
                "object": object_name,
                "active": boolean(direct_text(root, "active")),
                "errorDisplayField": direct_text(root, "errorDisplayField"),
                "errorMessagePresent": direct_text(root, "errorMessage") is not None,
            },
            references,
            rule,
        )

    def parse_permission_set(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".permissionset-meta.xml")
        object_perms = [e for e in root.iter() if local_name(e.tag) == "objectPermissions"]
        field_perms = [e for e in root.iter() if local_name(e.tag) == "fieldPermissions"]
        references: list[dict[str, str]] = []
        for element in object_perms:
            target = direct_text(element, "object")
            if target:
                references.append({"kind": "grants-object-permission", "target": target})
        for element in field_perms:
            target = direct_text(element, "field")
            if target:
                references.append({"kind": "grants-field-permission", "target": target})
        references.sort(key=lambda item: (item["kind"], item["target"]))
        facts: dict[str, Any] = {
            "label": direct_text(root, "label"),
            "hasActivationRequired": boolean(direct_text(root, "hasActivationRequired")),
            "objectPermissionCount": len(object_perms),
            "fieldPermissionCount": len(field_perms),
        }
        if len(references) > MAX_USAGE_REFS:
            facts["referencesTruncated"] = True
            references = references[:MAX_USAGE_REFS]
        return self.component("PermissionSet", name, path, facts, references, name)

    def parse_layout(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".layout-meta.xml")
        object_name = name.split("-", 1)[0] if "-" in name else None
        field_targets: set[str] = set()
        for element in root.iter():
            if local_name(element.tag) == "layoutItems":
                field = direct_text(element, "field")
                if field:
                    field_targets.add(f"{object_name}.{field}" if object_name else field)
        references = [{"kind": "places-field", "target": target} for target in sorted(field_targets)]
        references.extend(
            {"kind": "related-list", "target": value}
            for value in descendant_texts(root, "relatedList")
        )
        facts = {
            "object": object_name,
            "fieldCount": len(field_targets),
        }
        if len(references) > MAX_USAGE_REFS:
            facts["referencesTruncated"] = True
            references = references[:MAX_USAGE_REFS]
        return self.component("Layout", name, path, facts, references, name)

    GENERIC_META = re.compile(r"^(?P<name>.+)\.(?P<token>[A-Za-z0-9_]+)-meta\.xml$")

    # Suffix tokens whose naive capitalization is not the Metadata API type name (validated by a
    # simulated all-types corpus, 2026-07-14): `X.md-meta.xml` is CustomMetadata, not "Md", etc.
    GENERIC_TOKEN_TYPES = {
        "md": "CustomMetadata",
        "app": "CustomApplication",
        "tab": "CustomTab",
        "page": "ApexPage",
        "component": "ApexComponent",
        "email": "EmailTemplate",
        "resource": "StaticResource",
        "permissionset": "PermissionSet",
        "labels": "CustomLabels",
        "site": "CustomSite",
    }

    def parse_generic_meta(self, path: Path) -> dict[str, Any]:
        """Fallback for every source-format metadata file without a dedicated parser.

        Coverage must be total: an unrecognized type (layout, permission set, custom metadata,
        queue, label, …) still yields an inventory component and a generic component-inventory
        claim instead of silently producing nothing (observed live with an approval process).
        """

        match = self.GENERIC_META.match(path.name)
        if match is None:
            raise ValueError(f"not a source-format metadata file: {path.name}")
        token = match.group("token")
        metadata_type = self.GENERIC_TOKEN_TYPES.get(
            token.lower(), token[0].upper() + token[1:]
        )
        root = self.parse_xml(path)
        return self.component(
            metadata_type,
            match.group("name"),
            path,
            {
                "label": direct_text(root, "label")
                or direct_text(root, "masterLabel")
                or direct_text(root, "fullName"),
                "rootElement": local_name(root.tag),
            },
        )

    def inventory(self) -> dict[str, Any]:
        if not self.source_root.is_dir():
            raise KnowledgeBuildError("required root force-app directory is missing")
        components: list[dict[str, Any]] = []
        diagnostics: list[dict[str, str]] = []
        handled: set[Path] = set()

        parsers: list[tuple[str, Any]] = [
            ("*.object-meta.xml", self.parse_object),
            ("*.field-meta.xml", self.parse_field),
            ("*.flow-meta.xml", self.parse_flow),
            ("*.approvalProcess-meta.xml", self.parse_approval_process),
            ("*.validationRule-meta.xml", self.parse_validation_rule),
            ("*.permissionset-meta.xml", self.parse_permission_set),
            ("*.layout-meta.xml", self.parse_layout),
        ]
        for pattern, parser in parsers:
            for path in sorted(self.source_root.rglob(pattern)):
                try:
                    components.append(parser(path))
                    handled.add(path)
                except (ET.ParseError, OSError, ValueError, IndexError) as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for folder, metadata_type, suffix in (
            ("classes", "ApexClass", ".cls"),
            ("triggers", "ApexTrigger", ".trigger"),
        ):
            for path in sorted((self.source_root / "main/default" / folder).glob(f"*{suffix}")):
                try:
                    components.append(self.parse_apex(path, metadata_type))
                    handled.add(path)
                except OSError as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for folder, parser in (("lwc", self.parse_lwc), ("aura", self.parse_aura)):
            base = self.source_root / "main/default" / folder
            if base.is_dir():
                for bundle in sorted(path for path in base.iterdir() if path.is_dir()):
                    try:
                        components.append(parser(bundle))
                        handled.update(path for path in bundle.rglob("*") if path.is_file())
                    except (ET.ParseError, OSError, IndexError) as exc:
                        diagnostics.append(
                            {"severity": "error", "path": self.relative(bundle), "message": str(exc)}
                        )
        for pattern, metadata_type in (
            ("*.namedCredential-meta.xml", "NamedCredential"),
            ("*.externalCredential-meta.xml", "ExternalCredential"),
            ("*.remoteSite-meta.xml", "RemoteSiteSetting"),
        ):
            for path in sorted(self.source_root.rglob(pattern)):
                try:
                    components.append(self.parse_integration(path, metadata_type))
                    handled.add(path)
                except (ET.ParseError, OSError) as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        # Total coverage: every remaining source-format metadata file gets at least a generic
        # component so the draft never silently skips a metadata type.
        for path in sorted(self.source_root.rglob("*-meta.xml")):
            if path in handled:
                continue
            # Companion-meta rule: `X.cls-meta.xml` describes `X.cls`. When the sibling content
            # file was already parsed (Apex, bundles), the meta is bookkeeping — skip it instead
            # of minting a duplicate "Cls:X" component. When the sibling exists but has no
            # dedicated parser (static resources, pages, email templates), the meta IS the
            # component and the sibling is its content.
            sibling = path.with_name(path.name.removesuffix("-meta.xml"))
            if sibling != path and sibling.is_file() and sibling in handled:
                handled.add(path)
                continue
            try:
                components.append(self.parse_generic_meta(path))
                handled.add(path)
                if sibling != path and sibling.is_file():
                    handled.add(sibling)
            except (ET.ParseError, OSError, ValueError) as exc:
                diagnostics.append(
                    {"severity": "error", "path": self.relative(path), "message": str(exc)}
                )

        all_files = sorted(path for path in self.source_root.rglob("*") if path.is_file())
        recognized_paths = {item["path"] for item in components}
        generic = [
            {
                "path": self.relative(path),
                "sha256": file_digest(path),
                "category": path.parent.name,
            }
            for path in all_files
            if path not in handled and self.relative(path) not in recognized_paths
        ]
        components.sort(key=lambda item: (item["metadataType"], item["name"], item["path"]))
        source_manifest = [{"path": self.relative(path), "sha256": file_digest(path)} for path in all_files]
        counts = Counter(item["metadataType"] for item in components)
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-knowledge-inventory",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": self.repository_commit(),
            "sourceRoot": "force-app",
            "sourceTreeDigest": f"sha256:{digest_bytes(canonical(source_manifest).encode('utf-8'))}",
            "workspaceStatus": {
                "clean": not self.source_status(),
                "changes": self.source_status(),
            },
            "completeness": {
                "status": "complete" if not diagnostics else "partial",
                "filesScanned": len(all_files),
                "recognizedComponents": len(components),
                "genericFiles": len(generic),
                "diagnostics": diagnostics,
            },
            "coverage": dict(sorted(counts.items())),
            "components": components,
            "genericFiles": generic,
        }
        self.validate_record(
            result, "force-app-knowledge-inventory.schema.json", "force-app inventory"
        )
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.inventory_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return result

    def load_inventory(self) -> dict[str, Any]:
        if not self.inventory_path.is_file():
            raise KnowledgeBuildError("force-app inventory is missing; run inventory first")
        inventory = json.loads(self.inventory_path.read_text(encoding="utf-8"))
        if inventory.get("schemaVersion") != SCHEMA_VERSION:
            raise KnowledgeBuildError("unsupported force-app inventory schema version")
        return inventory

    def current_tree_digest(self) -> str:
        files = sorted(path for path in self.source_root.rglob("*") if path.is_file())
        manifest = [{"path": self.relative(path), "sha256": file_digest(path)} for path in files]
        return f"sha256:{digest_bytes(canonical(manifest).encode('utf-8'))}"

    def validate_record(self, value: dict[str, Any], schema_name: str, label: str) -> None:
        schema = json.loads((self.root / "schemas" / schema_name).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "<root>"
            raise KnowledgeBuildError(f"{label} schema failure at {location}: {errors[0].message}")

    DESCRIPTION_SENTINEL = (
        "<AGENT_WRITES_WHAT_THIS_COMPONENT_DOES_BASED_ON_ITS_SOURCE_BEFORE_PROPOSING>"
    )

    KEYWORD_SUFFIX_RE = re.compile(r"__(?:c|r|mdt|e|x|b|p|latitude__s|longitude__s)$", re.IGNORECASE)

    @classmethod
    def keyword_seeds(cls, component: dict[str, Any]) -> list[str]:
        """Advisory candidate keywords derived from the objects/fields a component uses.

        Source-grounded terms only (object/field API names, suffix-stripped and de-camelised) that
        seed the human keyword-curation queue. Never promoted automatically: they land in
        `candidateKeywords`, and only a curated taxonomy term ever enters `keywords`.
        """

        tokens: set[str] = set()
        facts = component.get("facts", {})
        obj = facts.get("object")
        if isinstance(obj, str):
            tokens.add(obj)
        for value in facts.get("referencedObjects", []) or []:
            tokens.add(str(value))
        for reference in component.get("references", []):
            if reference["kind"] in OBJECT_REF_KINDS:
                tokens.update(str(reference["target"]).split("."))
        terms: set[str] = set()
        for token in tokens:
            term = cls.KEYWORD_SUFFIX_RE.sub("", token)
            term = re.sub(r"\s+", " ", term.replace("_", " ").strip().lower())
            if 1 <= len(term) <= 60:
                terms.add(term)
        return sorted(terms)[:5]

    def candidate_claims(
        self, component: dict[str, Any], feature: list[str] | None = None
    ) -> list[dict[str, Any]]:
        metadata_type = component["metadataType"]
        facts = component["facts"]
        common_limit = "Repository metadata establishes intended source only; deployed org state was not reconciled."
        candidates: list[dict[str, Any]] = []
        if metadata_type == "CustomObject":
            candidates.append(
                {
                    "domain": "object-descriptions",
                    "claimType": "object-existence",
                    "subject": {"kind": "object", "identity": component["name"]},
                    "assertion": {"predicate": "exists-in-accessible-schema", "value": True},
                    "statement": f"{component['name']} is defined in the Salesforce metadata repository at the recorded commit.",
                    "limitations": [common_limit, "Business meaning and ownership are not established by this claim."],
                }
            )
        elif metadata_type == "CustomField":
            identity = f"{facts['object']}.{facts['fullName']}"
            candidates.append(
                {
                    "domain": "field-descriptions",
                    "claimType": "field-schema",
                    "subject": {"kind": "field", "identity": identity},
                    "assertion": {"predicate": "source-defined-field-schema", "value": facts},
                    "statement": f"{identity} has the recorded source-format field definition at the repository commit.",
                    "limitations": [common_limit, "Business meaning and effective org accessibility are not established."],
                }
            )
            for target in facts.get("referenceTo", []):
                candidates.append(
                    {
                        "domain": "object-relations",
                        "claimType": "object-relation",
                        "subject": {"kind": "relation", "identity": f"{identity}->{target}"},
                        "assertion": {"predicate": "references-object", "value": target},
                        "statement": f"{identity} references {target} in source-format metadata.",
                        "limitations": [common_limit, "Business cardinality and reference-data semantics are not established."],
                    }
                )
        elif metadata_type in {"Flow", "ApexClass", "ApexTrigger", "ApprovalProcess", "ValidationRule"}:
            automation_limits = [common_limit, "Runtime paths, order of execution, and side effects are not established."]
            if metadata_type in {"ApexClass", "ApexTrigger", "ValidationRule"}:
                automation_limits.append(
                    "Object/field usage is a source-token heuristic: dynamic references, standard-field "
                    "usage, and unresolved variable types may be missing or approximate."
                )
            candidates.append(
                {
                    "domain": "automation-map",
                    "claimType": "automation-inventory",
                    "subject": {"kind": "automation", "identity": component["name"]},
                    "assertion": {
                        "predicate": "source-defined-automation",
                        "value": {"metadataType": metadata_type, "facts": facts, "references": component["references"]},
                    },
                    "statement": f"{component['name']} is a source-defined {metadata_type} component at the repository commit.",
                    "limitations": automation_limits,
                }
            )
        elif metadata_type in {"NamedCredential", "ExternalCredential", "RemoteSiteSetting"}:
            candidates.append(
                {
                    "domain": "integration-map",
                    "claimType": "integration",
                    "subject": {"kind": "integration", "identity": component["name"]},
                    "assertion": {
                        "predicate": "source-defined-integration-config",
                        "value": {"metadataType": metadata_type, "facts": facts},
                    },
                    "statement": f"{component['name']} is a source-defined {metadata_type} component at the repository commit.",
                    "limitations": [common_limit, "Authentication, payloads, data direction, and business ownership are not established."],
                }
            )
        else:
            # Total coverage: any other metadata type (layout, permission set, custom metadata,
            # LWC/Aura bundle, queue, label, …) yields a generic component-inventory claim so the
            # documentation pipeline never produces nothing for a recognized source file.
            candidates.append(
                {
                    "domain": "component-inventory",
                    "claimType": "component-inventory",
                    "subject": {"kind": "component", "identity": component["id"]},
                    "assertion": {
                        "predicate": "source-defined-component",
                        "value": {"metadataType": metadata_type, "facts": facts},
                    },
                    "statement": f"{component['name']} is a source-defined {metadata_type} component at the repository commit.",
                    "limitations": [common_limit, "Business meaning, runtime behavior, and org deployment state are not established."],
                }
            )
        # AI description layer (owner decision 2026-07-14): behavior-bearing components also get a
        # description stub. The agent must read the component source and replace the sentinel with
        # what the component actually does before proposing; the registry rejects unfilled
        # sentinels and the description claim stays assurance=inferred until a human chat-approves.
        if metadata_type in {
            "Flow",
            "ApexClass",
            "ApexTrigger",
            "ApprovalProcess",
            "ValidationRule",
            "LightningComponentBundle",
            "AuraDefinitionBundle",
        }:
            candidates.append(
                {
                    "domain": "automation-map"
                    if metadata_type in {"Flow", "ApexClass", "ApexTrigger", "ApprovalProcess", "ValidationRule"}
                    else "component-inventory",
                    "claimType": "component-description",
                    "subject": {"kind": "component", "identity": component["id"]},
                    "assertion": {
                        "predicate": "describes-source-declared-behavior",
                        "value": {
                            "metadataType": metadata_type,
                            "description": self.DESCRIPTION_SENTINEL,
                        },
                    },
                    "assurance": "inferred",
                    "statement": f"Model-inferred, human-reviewed description of what {component['name']} does according to its source at the repository commit.",
                    "limitations": [
                        common_limit,
                        "The description interprets source only; business intent and runtime behavior in the org are not established.",
                    ],
                }
            )
        seeds = self.keyword_seeds(component)
        if seeds:
            for candidate in candidates:
                candidate["candidateKeywords"] = seeds
        if feature:
            for candidate in candidates:
                candidate["feature"] = list(feature)
        return candidates

    def relation_candidates(self, component: dict[str, Any]) -> list[dict[str, Any]]:
        """First-class component-relation claims for every reference edge this component carries.

        `CustomField.referenceTo` edges are excluded: `candidate_claims()` already emits those as
        `object-relation` claims. Every other reference kind (a Flow's `operates-on`/`reads-field`/
        `writes-field`/`invokes-apex`, an Apex class's `queries-object`/`invokes-class`, an LWC's
        `apex-method`/`schema`, permission-set/layout grants, …) is otherwise only visible embedded
        inside its owning component's own claim. This promotes each edge to its own independently
        reconcilable, deterministically-identified relation claim, so it can be created, tracked,
        and later flagged as orphaned on its own instead of only as a side effect of that owning
        claim being drafted.
        """

        if component["metadataType"] == "CustomField":
            return []
        common_limit = "Repository metadata establishes intended source only; deployed org state was not reconciled."
        candidates: list[dict[str, Any]] = []
        for reference in component["references"]:
            kind = reference["kind"]
            target = reference["target"]
            heuristic = kind in HEURISTIC_REF_KINDS
            identity = f"{component['id']}->{kind}->{target}"
            candidates.append(
                {
                    "domain": "object-relations",
                    "claimType": "component-relation",
                    "subject": {"kind": "relation", "identity": identity},
                    "assertion": {
                        "predicate": kind,
                        "value": {
                            "target": target,
                            "sourceMetadataType": component["metadataType"],
                            "heuristic": heuristic,
                        },
                    },
                    "assurance": "inferred" if heuristic else "observed",
                    "statement": f"{component['id']} has a {kind} reference to {target} in source-format metadata.",
                    "limitations": [common_limit] + (
                        [
                            "Source-token heuristic: dynamic references and unresolved variable "
                            "types may be missing or approximate."
                        ]
                        if heuristic
                        else ["Business cardinality and reference-data semantics are not established."]
                    ),
                }
            )
        return candidates

    def all_relation_candidates(self, component: dict[str, Any]) -> list[dict[str, Any]]:
        """Every relation-claim candidate (object-relation + component-relation) for one component."""

        if component["metadataType"] == "CustomField":
            return [
                candidate
                for candidate in self.candidate_claims(component)
                if candidate["claimType"] == "object-relation"
            ]
        return self.relation_candidates(component)

    def expected_claim_id(self, candidate: dict[str, Any]) -> str:
        return stable_id(
            "KCLM",
            candidate["subject"]["identity"],
            f"{candidate['claimType']}|{candidate['assertion']['predicate']}",
        )

    def worklist(
        self, metadata_type: str | None = None, write: bool = False
    ) -> dict[str, Any]:
        """Derive per-component batch status from ground truth instead of kept state.

        The worklist is recomputed on every call from the inventory (component digests), the
        draft directory (drafts current at the same tree digest), and the canonical claim
        registry. It therefore cannot drift after a crash or an interrupted batch: resume is
        simply "run worklist again and continue from the first pending component".
        """

        inventory = self.load_inventory()
        if metadata_type is not None and metadata_type not in inventory["coverage"]:
            available = sorted(inventory["coverage"])
            raise KnowledgeBuildError(
                f"inventory has no components of metadata type {metadata_type!r}; "
                f"available types: {', '.join(available)}"
            )
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")

        claims_root = self.root / ".ai/knowledge/claims"
        manifest_path = self.draft_root / "manifest.json"
        drafts_current = False
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            drafts_current = manifest.get("sourceTreeDigest") == inventory["sourceTreeDigest"]

        items: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for component in inventory["components"]:
            if metadata_type is not None and component["metadataType"] != metadata_type:
                continue
            component_digest = digest_bytes(canonical(component).encode("utf-8"))
            current_evidence_id = stable_id(
                "KEVD", component["id"], f"repo-{component_digest}"
            )
            claim_states: list[dict[str, Any]] = []
            for candidate in self.candidate_claims(component):
                claim_id = self.expected_claim_id(candidate)
                state: dict[str, Any] = {
                    "claimId": claim_id,
                    "claimType": candidate["claimType"],
                }
                canonical_path = claims_root / f"{claim_id}.yaml"
                if canonical_path.is_file():
                    record = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))
                    state["revision"] = int(record["revision"])
                    status = record.get("status")
                    if status == "verified":
                        state["state"] = (
                            "verified-current"
                            if current_evidence_id in record.get("evidenceRefs", [])
                            else "verified-stale"
                        )
                        if record.get("reviewBy"):
                            state["reviewBy"] = record["reviewBy"]
                    elif status == "proposed":
                        state["state"] = "proposed"
                    else:
                        state["state"] = "attention"
                        state["reason"] = f"canonical status is {status}"
                elif drafts_current and (self.draft_root / f"{claim_id}.yaml").is_file():
                    state["state"] = "drafted"
                else:
                    state["state"] = "missing"
                claim_states.append(state)

            states = {state["state"] for state in claim_states}
            if "attention" in states:
                status = "blocked"
            elif "verified-stale" in states:
                status = "stale-refresh"
            elif "missing" in states:
                status = "pending"
            elif "drafted" in states:
                status = "drafted"
            elif "proposed" in states:
                status = "proposed"
            else:
                status = "verified-current"
            item = {
                "componentId": component["id"],
                "metadataType": component["metadataType"],
                "name": component["name"],
                "path": component["path"],
                "sha256": component["sha256"],
                "status": status,
                "claims": claim_states,
            }
            if status == "blocked":
                item["reason"] = "; ".join(
                    f"{state['claimId']}: {state['reason']}"
                    for state in claim_states
                    if state["state"] == "attention"
                )
            items.append(item)
            counts[status] += 1

        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-knowledge-worklist",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            **({"metadataTypeFilter": metadata_type} if metadata_type else {}),
            "counts": dict(sorted(counts.items())),
            "items": items,
        }
        self.validate_record(
            result, "force-app-knowledge-worklist.schema.json", "force-app worklist"
        )
        if write:
            suffix = f"-{metadata_type}" if metadata_type else ""
            worklist_path = self.cache_root / f"force-app-worklist{suffix}.json"
            self.cache_root.mkdir(parents=True, exist_ok=True)
            worklist_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            result["path"] = self.relative(worklist_path)
        return result

    def relations_worklist(
        self, metadata_type: str | None = None, write: bool = False
    ) -> dict[str, Any]:
        """Edge-granular status for every object-relation/component-relation candidate.

        Mirrors `worklist()`'s ground-truth-recomputation contract but at reference-edge
        granularity: one component can carry many relation edges independently at different
        states (some already verified, one newly added), which a single per-component status
        cannot represent. Read-only; never proposes. Because a candidate's deterministic claim ID
        is derived from its own (component, kind, target) identity, an unchanged edge always
        regenerates the same ID and is reported `verified-current`/`proposed` as-is — a rerun with
        no source changes reports identical output, which is what lets a sweep touch only what's
        new.
        """

        inventory = self.load_inventory()
        if metadata_type is not None and metadata_type not in inventory["coverage"]:
            available = sorted(inventory["coverage"])
            raise KnowledgeBuildError(
                f"inventory has no components of metadata type {metadata_type!r}; "
                f"available types: {', '.join(available)}"
            )
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")

        claims_root = self.root / ".ai/knowledge/claims"
        items: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for component in inventory["components"]:
            if metadata_type is not None and component["metadataType"] != metadata_type:
                continue
            component_digest = digest_bytes(canonical(component).encode("utf-8"))
            current_evidence_id = stable_id("KEVD", component["id"], f"repo-{component_digest}")
            for candidate in self.all_relation_candidates(component):
                claim_id = self.expected_claim_id(candidate)
                value = candidate["assertion"]["value"]
                if candidate["claimType"] == "object-relation":
                    target, heuristic = value, False
                else:
                    target, heuristic = value["target"], value["heuristic"]
                item: dict[str, Any] = {
                    "claimId": claim_id,
                    "claimType": candidate["claimType"],
                    "sourceComponentId": component["id"],
                    "sourceMetadataType": component["metadataType"],
                    "predicate": candidate["assertion"]["predicate"],
                    "target": target,
                    "heuristic": heuristic,
                }
                canonical_path = claims_root / f"{claim_id}.yaml"
                if canonical_path.is_file():
                    record = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))
                    item["revision"] = int(record["revision"])
                    status = record.get("status")
                    if status == "verified":
                        item["state"] = (
                            "verified-current"
                            if current_evidence_id in record.get("evidenceRefs", [])
                            else "verified-stale"
                        )
                        if record.get("reviewBy"):
                            item["reviewBy"] = record["reviewBy"]
                    elif status == "proposed":
                        item["state"] = "proposed"
                    else:
                        item["state"] = "blocked"
                        item["reason"] = f"canonical status is {status}"
                else:
                    item["state"] = "missing"
                items.append(item)
                counts[item["state"]] += 1

        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-relations-worklist",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            **({"metadataTypeFilter": metadata_type} if metadata_type else {}),
            "counts": dict(sorted(counts.items())),
            "items": items,
        }
        self.validate_record(
            result, "force-app-relations-worklist.schema.json", "force-app relations worklist"
        )
        if write:
            suffix = f"-{metadata_type}" if metadata_type else ""
            path = self.cache_root / f"force-app-relations-worklist{suffix}.json"
            self.cache_root.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result["path"] = self.relative(path)
        return result

    def relation_health(self, write: bool = False) -> dict[str, Any]:
        """Read-only: verified relation claims whose source edge no longer exists in current source.

        Knowledge is append-only, so a deleted field/component or a retargeted reference doesn't
        remove or update its old claim by itself — this diffs every `verified` object-relation/
        component-relation claim's `subject.identity` against the live set derived fresh from
        `all_relation_candidates()` for the current inventory, and flags the ones with no live
        match for human stale-marking. Never mutates Knowledge; marking an orphan `stale` remains a
        separate governed `review`/`promote` step.
        """

        inventory = self.load_inventory()
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")
        live_component_ids = {component["id"] for component in inventory["components"]}
        live_identities: set[str] = set()
        for component in inventory["components"]:
            for candidate in self.all_relation_candidates(component):
                live_identities.add(candidate["subject"]["identity"])

        orphaned: list[dict[str, Any]] = []
        claims_root = self.root / ".ai/knowledge/claims"
        for path in sorted(claims_root.glob("*.yaml")):
            claim = yaml.safe_load(path.read_text(encoding="utf-8"))
            claim_type = claim.get("claimType")
            if claim_type not in {"object-relation", "component-relation"}:
                continue
            if claim.get("status") != "verified":
                continue
            identity = claim["subject"]["identity"]
            if identity in live_identities:
                continue
            if claim_type == "component-relation":
                source_component_id = identity.split("->", 1)[0]
            else:
                # object-relation identity is "{Object}.{Field}->{Target}"; the owning CustomField
                # component id is the metadata-type-prefixed form of that same head token.
                source_component_id = f"CustomField:{identity.split('->', 1)[0]}"
            reason = (
                "component removed"
                if source_component_id not in live_component_ids
                else "edge no longer present in source"
            )
            orphaned.append(
                {
                    "claimId": claim["claimId"],
                    "claimType": claim_type,
                    "subjectIdentity": identity,
                    "reason": reason,
                    "revision": int(claim["revision"]),
                }
            )

        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-relation-health",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            "orphanedCount": len(orphaned),
            "orphaned": orphaned,
        }
        self.validate_record(
            result, "force-app-relation-health.schema.json", "force-app relation health"
        )
        if write:
            path = self.cache_root / "force-app-relation-health.json"
            self.cache_root.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result["path"] = self.relative(path)
        return result

    # Component statuses that count as documented / undocumented / drifted for coverage. Drift
    # ("stale-refresh") means a verified claim exists but the component's current source digest no
    # longer matches the evidence it was verified against — a report-only re-review signal.
    COVERAGE_DOCUMENTED = "verified-current"
    COVERAGE_UNDOCUMENTED = "pending"
    COVERAGE_DRIFTED = "stale-refresh"
    COVERAGE_ATTENTION = ("blocked", COVERAGE_DRIFTED, COVERAGE_UNDOCUMENTED)

    def coverage(self, write: bool = False) -> dict[str, Any]:
        """Documentation coverage of the force-app source, derived from the worklist.

        Read-only. Reuses the worklist's per-component status (which already checks canonical claims
        and source-digest drift) to report, per metadata type, how many components are documented by
        a fresh verified claim vs proposed vs undocumented vs drifted, plus a prioritised
        "document next" list. It never mutates Knowledge — marking a drifted claim stale stays a
        governed human review.
        """

        worklist = self.worklist(metadata_type=None)
        items = worklist["items"]
        by_type: dict[str, Counter[str]] = {}
        for item in items:
            by_type.setdefault(item["metadataType"], Counter())[item["status"]] += 1

        def summarize(bucket: Counter[str]) -> dict[str, int]:
            total = sum(bucket.values())
            documented = bucket.get(self.COVERAGE_DOCUMENTED, 0)
            return {
                "total": total,
                "documented": documented,
                "proposed": bucket.get("proposed", 0) + bucket.get("drafted", 0),
                "undocumented": bucket.get(self.COVERAGE_UNDOCUMENTED, 0),
                "drifted": bucket.get(self.COVERAGE_DRIFTED, 0),
                "blocked": bucket.get("blocked", 0),
                "coveragePercent": round(100 * documented / total) if total else 0,
            }

        by_metadata_type = {name: summarize(bucket) for name, bucket in sorted(by_type.items())}
        overall = Counter()
        for bucket in by_type.values():
            overall.update(bucket)
        priority = {"blocked": 0, self.COVERAGE_DRIFTED: 1, self.COVERAGE_UNDOCUMENTED: 2}
        document_next = sorted(
            (
                {
                    "componentId": item["componentId"],
                    "metadataType": item["metadataType"],
                    "name": item["name"],
                    "path": item["path"],
                    "status": item["status"],
                    **({"reason": item["reason"]} if "reason" in item else {}),
                }
                for item in items
                if item["status"] in priority
            ),
            key=lambda entry: (priority[entry["status"]], entry["metadataType"], entry["name"]),
        )
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-knowledge-coverage",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": worklist["repositoryCommit"],
            "sourceTreeDigest": worklist["sourceTreeDigest"],
            "totals": summarize(overall),
            "byMetadataType": by_metadata_type,
            "documentNext": document_next,
        }
        if write:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            coverage_path = self.cache_root / "force-app-coverage.json"
            coverage_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            result["path"] = self.relative(coverage_path)
        return result

    def draft(
        self,
        observed_at: datetime,
        metadata_type: str | None = None,
        feature: list[str] | None = None,
        component_ids: set[str] | None = None,
        include_relations: bool = False,
        claim_ids: set[str] | None = None,
        refresh_claim_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        inventory = self.load_inventory()
        if metadata_type is not None:
            available = sorted(inventory["coverage"])
            if metadata_type not in inventory["coverage"]:
                raise KnowledgeBuildError(
                    f"inventory has no components of metadata type {metadata_type!r}; "
                    f"available types: {', '.join(available)}"
                )
        if inventory["completeness"]["status"] != "complete":
            raise KnowledgeBuildError("inventory is partial; resolve diagnostics before drafting")
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")
        changes = self.source_status()
        if changes:
            raise KnowledgeBuildError(
                "force-app is not clean at HEAD; metadata-repository evidence cannot be bound to a commit: "
                + "; ".join(changes[:20])
            )
        commit = self.repository_commit()
        if inventory["repositoryCommit"] != commit:
            raise KnowledgeBuildError("repository HEAD changed after inventory; rerun inventory")

        policy = json.loads((self.root / "config/knowledge-policy.json").read_text(encoding="utf-8"))
        self.draft_root.mkdir(parents=True, exist_ok=True)
        for old in self.draft_root.glob("*.yaml"):
            old.unlink()
        bundles: list[dict[str, Any]] = []
        for component in inventory["components"]:
            if metadata_type is not None and component["metadataType"] != metadata_type:
                continue
            if component_ids is not None and component["id"] not in component_ids:
                continue
            candidates = self.candidate_claims(component, feature)
            if include_relations:
                candidates = candidates + self.relation_candidates(component)
            if not candidates:
                continue
            if claim_ids is not None:
                candidates = [
                    candidate for candidate in candidates
                    if self.expected_claim_id(candidate) in claim_ids
                ]
                if not candidates:
                    continue
            component_digest = digest_bytes(canonical(component).encode("utf-8"))
            authority_for = sorted({item["claimType"] for item in candidates})
            evidence_id = stable_id("KEVD", component["id"], f"repo-{component_digest}")
            evidence = {
                "schemaVersion": 3,
                "evidenceId": evidence_id,
                "sourceType": "metadata-repository",
                "sourceLocator": f"git://{commit}/{component['path']}",
                "authorityFor": authority_for,
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageVersion": None,
                "repositoryCommit": commit,
                "observedAt": iso(observed_at),
                "retrievedAt": iso(observed_at),
                "sourceRevision": f"sha256:{component['sha256']}",
                "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": COLLECTOR_VERSION},
                "completeness": {
                    "status": "complete",
                    "enumerationComplete": False,
                    "permissionsProven": False,
                    "missingSegments": [],
                },
                "sensitivity": "internal-sanitized",
                "sanitization": {"rawDataCommitted": False, "redactions": []},
                "contentDigest": f"sha256:{component_digest}",
                "summary": f"Sanitized source-format observation of {component['id']} at {component['path']}.",
            }
            self.validate_record(evidence, "knowledge-evidence.schema.json", evidence_id)
            evidence_path = self.draft_root / f"{evidence_id}.yaml"
            evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")

            for candidate in candidates:
                claim_id = self.expected_claim_id(candidate)
                current_path = self.root / ".ai/knowledge/claims" / f"{claim_id}.yaml"
                expected_revision = 0
                revision = 1
                disposition = "new"
                if current_path.is_file():
                    current = yaml.safe_load(current_path.read_text(encoding="utf-8"))
                    status = current.get("status")
                    if status == "proposed":
                        expected_revision = int(current["revision"])
                        revision = expected_revision + 1
                        disposition = "update-proposed"
                    elif (
                        refresh_claim_ids is not None
                        and claim_id in refresh_claim_ids
                        and status in {"verified", "stale"}
                    ):
                        # Refresh selection: demote the drifted/expired claim to a new proposed
                        # revision against current evidence; the registry requires the explicit
                        # --refresh-verified acknowledgement emitted in the manifest command.
                        expected_revision = int(current["revision"])
                        revision = expected_revision + 1
                        disposition = "refresh-verified"
                    else:
                        bundles.append(
                            {
                                "claimId": claim_id,
                                "disposition": "existing-non-proposed",
                                "reason": f"existing status is {status}",
                            }
                        )
                        continue
                max_days = int(policy["claimPolicies"][candidate["claimType"]]["maxReviewAgeDays"])
                claim = {
                    "schemaVersion": 3,
                    "claimId": claim_id,
                    "revision": revision,
                    "domain": candidate["domain"],
                    "claimType": candidate["claimType"],
                    "subject": candidate["subject"],
                    "assertion": candidate["assertion"],
                    "statement": candidate["statement"],
                    "status": "proposed",
                    "assurance": candidate.get("assurance", "observed"),
                    "scope": {
                        "environment": "not-applicable",
                        "orgKey": None,
                        "packageNamespace": None,
                        "packageVersion": None,
                        "repositoryCommit": commit,
                    },
                    "evidenceRefs": [evidence_id],
                    "reviewRef": None,
                    "observedAt": iso(observed_at),
                    "verifiedAt": None,
                    "reviewBy": iso(observed_at + timedelta(days=max_days)),
                    "sensitivity": "internal-sanitized",
                    "keywords": [],
                    "candidateKeywords": candidate.get("candidateKeywords", []),
                    "limitations": candidate["limitations"],
                    "supersedes": [],
                    "supersededBy": None,
                    "contradicts": [],
                }
                if candidate.get("feature"):
                    claim["feature"] = candidate["feature"]
                self.validate_record(claim, "knowledge-claim.schema.json", claim_id)
                claim_path = self.draft_root / f"{claim_id}.yaml"
                claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
                bundles.append(
                    {
                        "claimId": claim_id,
                        "evidenceId": evidence_id,
                        "claimFile": self.relative(claim_path),
                        "evidenceFile": self.relative(evidence_path),
                        "expectedRevision": expected_revision,
                        "disposition": disposition,
                        "command": (
                            f"python scripts/knowledge_registry.py propose --claim-file {self.relative(claim_path)} "
                            f"--evidence-file {self.relative(evidence_path)} --expected-revision {expected_revision}"
                            + (" --refresh-verified" if disposition == "refresh-verified" else "")
                        ),
                    }
                )

        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-knowledge-draft-manifest",
            "generatedAt": iso(observed_at),
            "repositoryCommit": commit,
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            "reviewStatus": "draft",
            **({"metadataTypeFilter": metadata_type} if metadata_type else {}),
            "claimCount": sum("claimFile" in item for item in bundles),
            "bundles": bundles,
            "limitations": [
                "Drafts are proposed claims only and are not verified Knowledge.",
                "Repository evidence establishes intended source, not deployed org state or business meaning.",
                "Each selected claim must be submitted through knowledge_registry.py and remains subject to reconciliation and human review.",
            ],
        }
        self.validate_record(
            manifest,
            "force-app-knowledge-draft-manifest.schema.json",
            "force-app draft manifest",
        )
        (self.draft_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return manifest

    def relations_draft(
        self,
        observed_at: datetime,
        metadata_type: str | None = None,
        limit: int = 200,
        include_heuristic: bool = False,
    ) -> dict[str, Any]:
        """Draft only the relation-claim candidates not yet captured as a canonical claim.

        Thin wrapper: takes up to `limit` `missing` items from `relations_worklist()` (excluding
        source-token-heuristic edges by default — see `HEURISTIC_REF_KINDS`, the highest-noise
        source of false positives), then drafts exactly those candidates through the existing
        `draft()` pipeline restricted with `component_ids`/`claim_ids`, so no other candidate for
        the same components (its primary claim, or an unselected relation edge) is drafted as a
        side effect. Like every `draft()` call, this clears `.cache/knowledge-proposals/
        force-app-drafts/` first — do not interleave with an in-progress unrelated batch draft.
        """

        if limit < 1:
            raise KnowledgeBuildError("relations-draft limit must be at least 1")
        worklist = self.relations_worklist(metadata_type)
        missing = [item for item in worklist["items"] if item["state"] == "missing"]
        eligible = [item for item in missing if include_heuristic or not item["heuristic"]]
        selected = eligible[:limit]
        claim_ids = {item["claimId"] for item in selected}
        component_ids = {item["sourceComponentId"] for item in selected}
        if claim_ids:
            manifest = self.draft(
                observed_at,
                component_ids=component_ids,
                include_relations=True,
                claim_ids=claim_ids,
            )
        else:
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "kind": "force-app-knowledge-draft-manifest",
                "generatedAt": iso(observed_at),
                "repositoryCommit": worklist["repositoryCommit"],
                "sourceTreeDigest": worklist["sourceTreeDigest"],
                "reviewStatus": "no-op",
                "claimCount": 0,
                "bundles": [],
                "limitations": [],
            }
        manifest["totalMissing"] = len(missing)
        manifest["heuristicSkipped"] = len(missing) - len(eligible)
        manifest["drafted"] = len(claim_ids)
        manifest["remainingMissing"] = len(missing) - len(claim_ids)
        return manifest

    def refresh(
        self,
        observed_at: datetime,
        metadata_type: str | None = None,
        warn_days: int = 0,
        limit: int = 200,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Re-draft only the verified claims that drifted or are (nearly) past re-review.

        Without this, the store decays silently: every verified claim carries a `reviewBy`
        deadline after which it stops being effective, and a full `draft` rerun is the only
        recovery — re-touching claims that are still perfectly current. `refresh` selects the
        minimal set instead: claims whose source drifted after verification (`verified-stale`
        in either worklist) plus claims past `reviewBy` at `observed_at` (and, with
        `warn_days`, claims expiring within that window), then delegates to `draft()`
        restricted to exactly those claim/component IDs. Like every `draft()` call this clears
        the drafts workspace first; `--dry-run` reports the selection without touching it.
        """

        if limit < 1:
            raise KnowledgeBuildError("refresh limit must be at least 1")
        if warn_days < 0:
            raise KnowledgeBuildError("refresh warn-days must not be negative")
        horizon = observed_at + timedelta(days=warn_days)

        def classify(state: str, review_by: str | None) -> str | None:
            if state == "verified-stale":
                return "drift"
            if state == "verified-current" and review_by:
                deadline = parse_time(review_by)
                if deadline <= observed_at:
                    return "expired"
                if warn_days and deadline <= horizon:
                    return "expiring"
            return None

        worklist = self.worklist(metadata_type)
        matches: list[dict[str, Any]] = []
        for item in worklist["items"]:
            for state in item["claims"]:
                reason = classify(state["state"], state.get("reviewBy"))
                if reason:
                    matches.append(
                        {
                            "claimId": state["claimId"],
                            "claimType": state["claimType"],
                            "componentId": item["componentId"],
                            "reason": reason,
                            "relation": False,
                        }
                    )
        # CustomField object-relation claims appear in both worklists (all_relation_candidates
        # reuses candidate_claims for fields) — count each claim once.
        seen_claims = {match["claimId"] for match in matches}
        for item in self.relations_worklist(metadata_type)["items"]:
            reason = classify(item["state"], item.get("reviewBy"))
            if reason and item["claimId"] not in seen_claims:
                matches.append(
                    {
                        "claimId": item["claimId"],
                        "claimType": item["claimType"],
                        "componentId": item["sourceComponentId"],
                        "reason": reason,
                        "relation": True,
                    }
                )

        selected = matches[:limit]
        claim_ids = {match["claimId"] for match in selected}
        component_ids = {match["componentId"] for match in selected}
        reasons = Counter(match["reason"] for match in selected)
        summary = {
            "refreshSelected": len(selected),
            "driftCount": reasons["drift"],
            "expiredCount": reasons["expired"],
            "expiringCount": reasons["expiring"],
            "remaining": len(matches) - len(selected),
        }
        if dry_run:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "kind": "force-app-knowledge-refresh-selection",
                "generatedAt": iso(observed_at),
                "repositoryCommit": worklist["repositoryCommit"],
                "sourceTreeDigest": worklist["sourceTreeDigest"],
                "dryRun": True,
                **summary,
                "selection": selected,
            }
        if claim_ids:
            manifest = self.draft(
                observed_at,
                component_ids=component_ids,
                include_relations=any(match["relation"] for match in selected),
                claim_ids=claim_ids,
                refresh_claim_ids=claim_ids,
            )
        else:
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "kind": "force-app-knowledge-draft-manifest",
                "generatedAt": iso(observed_at),
                "repositoryCommit": worklist["repositoryCommit"],
                "sourceTreeDigest": worklist["sourceTreeDigest"],
                "reviewStatus": "no-op",
                "claimCount": 0,
                "bundles": [],
                "limitations": [],
            }
        manifest.update(summary)
        return manifest

    # -- Feature documentor -------------------------------------------------------------------

    def crawl_path(self, slug: str) -> Path:
        return self.cache_root / f"feature-{slug}.json"

    @staticmethod
    def component_objects(component: dict[str, Any]) -> set[str]:
        """Objects a component touches: its object folder, name/reference associations.

        Combines three source-grounded signals so the crawl associates each component with the
        objects it belongs to: (1) the `objects/<Object>/…` folder it lives in (fields, validation
        rules, record types, list views); (2) a naming convention for object-scoped surfaces
        (`Object-Layout` layouts, object-named tabs); (3) reference edges parsed from the source
        (a Flow's `operates-on`, an Apex object token, an LWC `@salesforce/schema` import). It never
        guesses beyond what the source shows — FlexiPage/formula/roll-up associations are not
        derivable here and are reported as crawl limitations.
        """

        objects: set[str] = set()
        path = component["path"]
        if "/objects/" in path:
            objects.add(path.split("/objects/", 1)[1].split("/", 1)[0])
        metadata_type = component["metadataType"]
        if metadata_type == "Layout":
            objects.add(component["name"].split("-", 1)[0])
        elif metadata_type == "CustomTab":
            objects.add(component["name"])
        for reference in component["references"]:
            if reference["kind"] in OBJECT_REF_KINDS:
                objects.add(reference["target"].split(".", 1)[0])
        return {name for name in objects if name}

    def feature_crawl(
        self,
        feature: str,
        anchors: list[str],
        depth: int = 1,
        hubs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Crawl the metadata graph out from anchor objects and record the feature boundary.

        BFS over the inventory reference graph, in both directions (a field on the anchor →
        outbound related object; a field on any other object referencing the anchor → inbound child
        relationship). Object hops are bounded by `depth`; objects on the `hubs` stop-list are kept
        as relation endpoints but never expanded, so a utility object referenced everywhere cannot
        drag the whole org into one feature. The result is a sanitized, schema-valid boundary the
        caller presents to a human before any claim is drafted.
        """

        if not anchors:
            raise KnowledgeBuildError("feature crawl requires at least one anchor object")
        if depth < 0:
            raise KnowledgeBuildError("crawl depth must not be negative")
        slug = feature_slug(feature)
        hub_set = {name for name in (hubs or []) if name}
        inventory = self.load_inventory()
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")
        components = inventory["components"]

        known_objects = {c["name"] for c in components if c["metadataType"] == "CustomObject"}
        fields = [c for c in components if c["metadataType"] == "CustomField"]
        fields_by_owner: dict[str, list[dict[str, Any]]] = {}
        fields_referencing: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            owner = field["facts"].get("object")
            if owner:
                fields_by_owner.setdefault(owner, []).append(field)
            for target in field["facts"].get("referenceTo", []) or []:
                fields_referencing.setdefault(target, []).append(field)

        anchor_set = list(dict.fromkeys(anchors))
        unresolved = sorted(name for name in anchor_set if name not in known_objects)
        boundary_objects: set[str] = set(anchor_set)
        frontier: set[str] = set(anchor_set)
        for _ in range(depth):
            next_frontier: set[str] = set()
            for obj in sorted(frontier):
                for field in fields_by_owner.get(obj, []):
                    for target in field["facts"].get("referenceTo", []) or []:
                        if target in hub_set or target in boundary_objects:
                            continue
                        boundary_objects.add(target)
                        next_frontier.add(target)
                for field in fields_referencing.get(obj, []):
                    owner = field["facts"].get("object")
                    if not owner or owner in hub_set or owner in boundary_objects:
                        continue
                    boundary_objects.add(owner)
                    next_frontier.add(owner)
            if not next_frontier:
                break
            frontier = next_frontier

        def relation(field: dict[str, Any], from_object: str, to_object: str) -> dict[str, str]:
            return {
                "fromObject": from_object,
                "field": field["facts"].get("fullName", field["name"]),
                "toObject": to_object,
                "type": field["facts"].get("type") or "Unknown",
            }

        outbound: list[dict[str, str]] = []
        inbound: list[dict[str, str]] = []
        for anchor in anchor_set:
            for field in fields_by_owner.get(anchor, []):
                for target in field["facts"].get("referenceTo", []) or []:
                    outbound.append(relation(field, anchor, target))
            for field in fields_referencing.get(anchor, []):
                owner = field["facts"].get("object") or "Unknown"
                inbound.append(relation(field, owner, anchor))
        outbound.sort(key=lambda item: (item["fromObject"], item["field"], item["toObject"]))
        inbound.sort(key=lambda item: (item["fromObject"], item["field"], item["toObject"]))

        junctions: list[dict[str, Any]] = []
        for obj in sorted(boundary_objects):
            master_details = sorted(
                field["facts"].get("fullName", field["name"])
                for field in fields_by_owner.get(obj, [])
                if field["facts"].get("type") == "MasterDetail"
            )
            if len(master_details) >= 2:
                junctions.append({"object": obj, "masterDetailFields": master_details})

        automations: list[dict[str, str]] = []
        ui: list[dict[str, str]] = []
        supporting: list[dict[str, str]] = []
        component_ids: set[str] = set()
        for component in components:
            metadata_type = component["metadataType"]
            if metadata_type == "CustomObject":
                if component["name"] in boundary_objects:
                    component_ids.add(component["id"])
                continue
            if metadata_type == "CustomField":
                if component["facts"].get("object") in boundary_objects:
                    component_ids.add(component["id"])
                continue
            touched = self.component_objects(component) & boundary_objects
            if not touched:
                continue
            component_ids.add(component["id"])
            summary = {
                "id": component["id"],
                "metadataType": metadata_type,
                "name": component["name"],
                "path": component["path"],
            }
            if metadata_type in AUTOMATION_TYPES:
                automations.append(summary)
            elif metadata_type in UI_TYPES:
                ui.append(summary)
            else:
                supporting.append(summary)
        for bucket in (automations, ui, supporting):
            bucket.sort(key=lambda item: (item["metadataType"], item["name"]))

        limitations = [
            "Feature boundary derives from source-format metadata and reference edges only; deployed "
            "org state was not reconciled.",
            "Object association for FlexiPages, cross-object formula fields, and roll-up summaries is "
            "not derivable from parsed references and may be incomplete.",
        ]
        if unresolved:
            limitations.append(
                "Anchors not found as custom objects in the repository (may be standard objects or "
                f"typos): {', '.join(unresolved)}."
            )
        crawl = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "feature-crawl",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            "feature": feature,
            "slug": slug,
            "anchors": anchor_set,
            "depth": depth,
            "hubStopList": sorted(hub_set),
            "objects": sorted(boundary_objects),
            "unresolvedAnchors": unresolved,
            "relations": {"outbound": outbound, "inbound": inbound, "junctions": junctions},
            "automations": automations,
            "ui": ui,
            "supporting": supporting,
            "componentIds": sorted(component_ids),
            "limitations": limitations,
        }
        self.validate_record(crawl, "feature-crawl.schema.json", "feature crawl")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.crawl_path(slug).write_text(
            json.dumps(crawl, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return crawl

    def load_crawl(self, slug: str) -> dict[str, Any]:
        path = self.crawl_path(slug)
        if not path.is_file():
            raise KnowledgeBuildError(
                f"feature crawl is missing for {slug!r}; run feature-crawl first"
            )
        crawl = json.loads(path.read_text(encoding="utf-8"))
        self.validate_record(crawl, "feature-crawl.schema.json", "feature crawl")
        return crawl

    def feature_draft(self, feature: str, observed_at: datetime) -> dict[str, Any]:
        """Draft feature-tagged claims restricted to a crawl boundary, then render the dossier."""

        slug = feature_slug(feature)
        crawl = self.load_crawl(slug)
        if crawl["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after the feature crawl; rerun feature-crawl")
        manifest = self.draft(
            observed_at,
            feature=[crawl["feature"]],
            component_ids=set(crawl["componentIds"]),
        )
        dossier = self.render_dossier(crawl, manifest)
        return {
            "feature": crawl["feature"],
            "slug": slug,
            "manifest": manifest,
            "dossierPath": self.relative(dossier),
        }

    def render_dossier(self, crawl: dict[str, Any], manifest: dict[str, Any]) -> Path:
        """Render the human-readable feature dossier from the crawl boundary and drafted claims."""

        feature = crawl["feature"]
        descriptions: dict[str, str] = {}
        for bundle in manifest.get("bundles", []):
            claim_file = bundle.get("claimFile")
            if not claim_file:
                continue
            claim = yaml.safe_load((self.root / claim_file).read_text(encoding="utf-8"))
            if claim.get("claimType") == "component-description":
                text = claim["assertion"]["value"].get("description", "")
                descriptions[str(claim["subject"]["identity"])] = text

        def describe(component_id: str) -> str:
            text = descriptions.get(component_id)
            if not text or text.startswith("<AGENT_"):
                return "_description pending (fill the draft sentinel before proposing)_"
            return text.replace("\n", " ").strip()

        def esc(value: Any) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")

        lines = [
            f"# Feature Dossier — {feature}",
            "",
            "Draft documentation generated by the feature documentor from source-format metadata at "
            f"commit `{crawl['repositoryCommit'][:12]}`. Not verified Knowledge: every fact below is "
            "a proposed claim until a human review promotes it. Do not publish to ADO or a production "
            "wiki from here.",
            "",
            "## Overview",
            "",
            f"- **Anchor objects:** {', '.join(f'`{name}`' for name in crawl['anchors'])}",
            f"- **Crawl depth:** {crawl['depth']}",
            f"- **Objects in boundary:** {len(crawl['objects'])}",
            f"- **Drafted proposed claims:** {manifest.get('claimCount', 0)}",
        ]
        if crawl["hubStopList"]:
            lines.append(f"- **Hub stop-list (not expanded):** {', '.join(crawl['hubStopList'])}")
        if crawl["unresolvedAnchors"]:
            lines.append(f"- **Unresolved anchors:** {', '.join(crawl['unresolvedAnchors'])}")

        lines.extend(["", "## Relations", "", "### Outbound (anchor references another object)", ""])
        outbound = crawl["relations"]["outbound"]
        if outbound:
            lines.extend(["| From | Field | To | Type |", "|---|---|---|---|"])
            lines.extend(
                f"| `{esc(r['fromObject'])}` | `{esc(r['field'])}` | `{esc(r['toObject'])}` | {esc(r['type'])} |"
                for r in outbound
            )
        else:
            lines.append("_No outbound relations found._")
        lines.extend(["", "### Inbound (another object references the anchor)", ""])
        inbound = crawl["relations"]["inbound"]
        if inbound:
            lines.extend(["| From | Field | To | Type |", "|---|---|---|---|"])
            lines.extend(
                f"| `{esc(r['fromObject'])}` | `{esc(r['field'])}` | `{esc(r['toObject'])}` | {esc(r['type'])} |"
                for r in inbound
            )
        else:
            lines.append("_No inbound relations found._")
        junctions = crawl["relations"]["junctions"]
        if junctions:
            lines.extend(["", "### Junction objects (many-to-many bridges)", ""])
            lines.extend(
                f"- `{esc(j['object'])}` — master-detail to {', '.join(f'`{esc(f)}`' for f in j['masterDetailFields'])}"
                for j in junctions
            )

        for heading, bucket in (
            ("Automations", crawl["automations"]),
            ("UI surfaces", crawl["ui"]),
            ("Supporting components", crawl["supporting"]),
        ):
            lines.extend(["", f"## {heading}", ""])
            if bucket:
                lines.extend(["| Type | Name | Description |", "|---|---|---|"])
                lines.extend(
                    f"| {esc(item['metadataType'])} | `{esc(item['name'])}` | {esc(describe(item['id']))} |"
                    for item in bucket
                )
            else:
                lines.append(f"_No {heading.lower()} in the boundary._")

        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {esc(item)}" for item in crawl["limitations"])
        lines.extend(
            [
                "",
                "## Source traceability",
                "",
                f"- Repository commit: `{crawl['repositoryCommit']}`",
                f"- Source tree digest: `{crawl['sourceTreeDigest']}`",
                f"- Crawl generated at: {crawl['generatedAt']}",
                "",
            ]
        )
        self.dossier_root.mkdir(parents=True, exist_ok=True)
        dossier_path = self.dossier_root / f"{crawl['slug']}.md"
        dossier_path.write_text("\n".join(lines), encoding="utf-8")
        return dossier_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    draft = commands.add_parser("draft")
    draft.add_argument("--observed-at")
    draft.add_argument(
        "--metadata-type",
        help="draft candidates only for this inventory metadata type (batch mode)",
    )
    worklist = commands.add_parser("worklist")
    worklist.add_argument(
        "--metadata-type",
        help="report batch status only for this inventory metadata type",
    )
    worklist.add_argument(
        "--write",
        action="store_true",
        help="also save the derived worklist under .cache/knowledge-proposals/",
    )
    coverage = commands.add_parser(
        "coverage", help="report documentation coverage of force-app source (read-only)"
    )
    coverage.add_argument(
        "--write",
        action="store_true",
        help="also save the coverage report under .cache/knowledge-proposals/",
    )
    relations_worklist = commands.add_parser(
        "relations-worklist",
        help="report edge-granular object-relation/component-relation claim status (read-only)",
    )
    relations_worklist.add_argument(
        "--metadata-type",
        help="report relation status only for this source component's inventory metadata type",
    )
    relations_worklist.add_argument(
        "--write",
        action="store_true",
        help="also save the derived relations worklist under .cache/knowledge-proposals/",
    )
    relations_draft = commands.add_parser(
        "relations-draft",
        help="draft only object-relation/component-relation candidates not yet captured",
    )
    relations_draft.add_argument("--observed-at")
    relations_draft.add_argument(
        "--metadata-type",
        help="draft relation candidates only for this source component's inventory metadata type",
    )
    relations_draft.add_argument(
        "--limit",
        type=int,
        default=200,
        help="cap the number of relation claims drafted this run (default 200)",
    )
    relations_draft.add_argument(
        "--include-heuristic",
        action="store_true",
        help="also draft source-token-heuristic edges (Apex object-token/queries-object/invokes-class); excluded by default",
    )
    refresh = commands.add_parser(
        "refresh",
        help="re-draft only verified claims that drifted or are past/near their reviewBy deadline",
    )
    refresh.add_argument("--observed-at")
    refresh.add_argument(
        "--metadata-type",
        help="refresh candidates only for this inventory metadata type",
    )
    refresh.add_argument(
        "--warn-days",
        type=int,
        default=0,
        help="also select verified claims expiring within this many days (default 0: drift and expired only)",
    )
    refresh.add_argument(
        "--limit",
        type=int,
        default=200,
        help="cap the number of claims refreshed this run (default 200)",
    )
    refresh.add_argument(
        "--dry-run",
        action="store_true",
        help="report the refresh selection without clearing or writing the drafts workspace",
    )
    relation_health = commands.add_parser(
        "relation-health",
        help="report verified relation claims whose source edge no longer exists (read-only)",
    )
    relation_health.add_argument(
        "--write",
        action="store_true",
        help="also save the derived relation-health report under .cache/knowledge-proposals/",
    )
    crawl = commands.add_parser(
        "feature-crawl", help="crawl the metadata graph from anchor objects into a feature boundary"
    )
    crawl.add_argument("--feature", required=True)
    crawl.add_argument("--anchors", required=True, help="comma-separated anchor object API names")
    crawl.add_argument("--depth", type=int, default=1, help="object hops to expand (default 1)")
    crawl.add_argument(
        "--hub",
        action="append",
        default=[],
        help="object to keep as a relation endpoint but never expand (repeatable)",
    )
    feature_draft = commands.add_parser(
        "feature-draft",
        help="draft feature-tagged claims for a crawl boundary and render its dossier",
    )
    feature_draft.add_argument("--feature", required=True)
    feature_draft.add_argument("--observed-at")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    builder = ForceAppKnowledge()
    try:
        if args.command == "inventory":
            result = builder.inventory()
            summary = {
                "path": builder.relative(builder.inventory_path),
                "components": result["completeness"]["recognizedComponents"],
                "genericFiles": result["completeness"]["genericFiles"],
                "clean": result["workspaceStatus"]["clean"],
                "status": result["completeness"]["status"],
            }
        elif args.command == "worklist":
            result = builder.worklist(args.metadata_type, args.write)
            summary = {
                "counts": result["counts"],
                "components": len(result["items"]),
            }
            if args.metadata_type:
                summary["metadataTypeFilter"] = args.metadata_type
            if "path" in result:
                summary["path"] = result["path"]
        elif args.command == "coverage":
            result = builder.coverage(args.write)
            summary = {
                "totals": result["totals"],
                "documentNext": len(result["documentNext"]),
            }
            if "path" in result:
                summary["path"] = result["path"]
        elif args.command == "relations-worklist":
            result = builder.relations_worklist(args.metadata_type, args.write)
            summary = {
                "counts": result["counts"],
                "edges": len(result["items"]),
            }
            if args.metadata_type:
                summary["metadataTypeFilter"] = args.metadata_type
            if "path" in result:
                summary["path"] = result["path"]
        elif args.command == "relations-draft":
            observed_at = parse_time(args.observed_at) if args.observed_at else utc_now()
            result = builder.relations_draft(
                observed_at, args.metadata_type, args.limit, args.include_heuristic
            )
            summary = {
                "path": builder.relative(builder.draft_root / "manifest.json"),
                "drafted": result["drafted"],
                "totalMissing": result["totalMissing"],
                "heuristicSkipped": result["heuristicSkipped"],
                "remainingMissing": result["remainingMissing"],
                "reviewStatus": result["reviewStatus"],
            }
            if args.metadata_type:
                summary["metadataTypeFilter"] = args.metadata_type
        elif args.command == "refresh":
            observed_at = parse_time(args.observed_at) if args.observed_at else utc_now()
            result = builder.refresh(
                observed_at,
                args.metadata_type,
                warn_days=args.warn_days,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            summary = {
                "refreshSelected": result["refreshSelected"],
                "driftCount": result["driftCount"],
                "expiredCount": result["expiredCount"],
                "expiringCount": result["expiringCount"],
                "remaining": result["remaining"],
            }
            if args.dry_run:
                summary["dryRun"] = True
                summary["selection"] = result["selection"]
            else:
                summary["path"] = builder.relative(builder.draft_root / "manifest.json")
                summary["reviewStatus"] = result["reviewStatus"]
            if args.metadata_type:
                summary["metadataTypeFilter"] = args.metadata_type
        elif args.command == "relation-health":
            result = builder.relation_health(args.write)
            summary = {
                "orphanedCount": result["orphanedCount"],
            }
            if "path" in result:
                summary["path"] = result["path"]
        elif args.command == "feature-crawl":
            anchors = [name.strip() for name in args.anchors.split(",") if name.strip()]
            result = builder.feature_crawl(args.feature, anchors, args.depth, args.hub)
            summary = {
                "feature": result["feature"],
                "path": builder.relative(builder.crawl_path(result["slug"])),
                "objects": len(result["objects"]),
                "outboundRelations": len(result["relations"]["outbound"]),
                "inboundRelations": len(result["relations"]["inbound"]),
                "junctions": len(result["relations"]["junctions"]),
                "automations": len(result["automations"]),
                "ui": len(result["ui"]),
                "components": len(result["componentIds"]),
                "unresolvedAnchors": result["unresolvedAnchors"],
            }
        elif args.command == "feature-draft":
            observed_at = parse_time(args.observed_at) if args.observed_at else utc_now()
            result = builder.feature_draft(args.feature, observed_at)
            summary = {
                "feature": result["feature"],
                "claims": result["manifest"]["claimCount"],
                "dossierPath": result["dossierPath"],
                "reviewStatus": result["manifest"]["reviewStatus"],
            }
        else:
            observed_at = parse_time(args.observed_at) if args.observed_at else utc_now()
            result = builder.draft(observed_at, args.metadata_type)
            summary = {
                "path": builder.relative(builder.draft_root / "manifest.json"),
                "claims": result["claimCount"],
                "reviewStatus": result["reviewStatus"],
            }
            if args.metadata_type:
                summary["metadataTypeFilter"] = args.metadata_type
    except (KnowledgeBuildError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
