#!/usr/bin/env python3
"""Inventory root force-app source and ground the one-file Knowledge Entry lanes."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator

try:
    from schema_format import FORMAT_CHECKER
except ModuleNotFoundError:  # imported as scripts.force_app_knowledge by unit tests
    from scripts.schema_format import FORMAT_CHECKER

# The reference-kind vocabulary lives in a leaf module so knowledge_store and knowledge_search can
# read it without importing this 6.5k-line collector — see scripts/relation_kinds.py. Re-exported
# here because every existing caller and tests/test_kind_contract.py read them off this module.
try:
    from relation_kinds import (  # noqa: F401
        ALL_REF_KINDS,
        HEURISTIC_REF_KINDS,
        OBJECT_REF_KINDS,
        SOURCE_DERIVED_HEURISTIC,
        edge_assurance,
    )
except ModuleNotFoundError:  # imported as scripts.force_app_knowledge by unit tests
    from scripts.relation_kinds import (  # noqa: F401
        ALL_REF_KINDS,
        HEURISTIC_REF_KINDS,
        OBJECT_REF_KINDS,
        SOURCE_DERIVED_HEURISTIC,
        edge_assurance,
    )


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "force-app"
CACHE_ROOT = ROOT / ".cache/knowledge-proposals"
INVENTORY_PATH = CACHE_ROOT / "force-app-inventory.json"
DRAFT_ROOT = CACHE_ROOT / "force-app-drafts"
SCHEMA_VERSION = 1
COLLECTOR_VERSION = "1.8.0"
CUSTOM_OBJECT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:__c|__mdt|__e|__x))\b")
# Custom-field token inside a formula/expression (validation rules). Standard fields cannot be told
# apart from function names by source alone, so the usage registry records custom fields only.
FORMULA_FIELD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*__c)\b")
# Cross-object formula span: one or more `X__r` relationship hops followed by the field. `X__r`
# names the lookup field `X__c` on the current object; each hop resolves through the repo field
# inventory, so the final Object.Field is exact whenever every hop's lookup is in the repo.
FORMULA_CHAIN_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]*__r(?:\.[A-Za-z][A-Za-z0-9_]*__r)*)\.([A-Za-z][A-Za-z0-9_]*)\b"
)
# Bound on picklist values recorded per field; the total count is always kept in facts.
PICKLIST_VALUE_CAP = 100
# Upper bound on emitted usage references per component (permission sets and layouts can enumerate
# hundreds of field grants). The total is always recorded in facts even when references are capped.
MAX_USAGE_REFS = 300
# $Label token inside an error-message template, in both formula ($Label.X) and flow-merge-field
# ({!$Label.X}) spelling. Resolved against repo CustomLabels so a user-pasted message matches the
# stored text even when the flow author routed it through a label.
LABEL_TOKEN_RE = re.compile(r"\{!\$Label\.([A-Za-z][A-Za-z0-9_]*)\}|\$Label\.([A-Za-z][A-Za-z0-9_]*)")
# Caps for the backward connector-path walk behind each error surface: enough to describe the
# decision scenario without enumerating a combinatorial flow, with pathsTruncated recorded when hit.
FLOW_ERROR_PATH_CAP = 5
FLOW_ERROR_PATH_DEPTH = 20
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
LABEL_IMPORT_RE = re.compile(r"@salesforce/label/c\.([A-Za-z0-9_]+)")
LWC_API_PROP_RE = re.compile(r"@api\s+(?:get\s+)?([A-Za-z_][A-Za-z0-9_]*)")
LWC_WIRE_RE = re.compile(r"@wire\(\s*([A-Za-z_][A-Za-z0-9_]*)")
# Markup literals (markupFieldExtraction): record-form object/field attributes and child
# component tags. Only literal attribute values match — `{bound}` expressions are skipped.
LWC_HTML_OBJECT_RE = re.compile(r"object-api-name\s*=\s*\"([A-Za-z][A-Za-z0-9_]*)\"")
LWC_HTML_FIELD_RE = re.compile(r"field-name\s*=\s*\"([A-Za-z][A-Za-z0-9_.]*)\"")
LWC_EMBED_RE = re.compile(r"<c-([a-z][a-z0-9-]*)")
# `Object.Field` string literal inside JS (e.g. @wire(getRecord) fields arrays) — a heuristic:
# any dotted capitalized string matches, so edges carry the per-reference flag.
LWC_JS_FIELD_LITERAL_RE = re.compile(
    r"['\"]([A-Z][A-Za-z0-9_]*(?:__c)?\.[A-Za-z][A-Za-z0-9_]*)['\"]"
)
AURA_CONTROLLER_RE = re.compile(r"\bcontroller\s*=\s*[\"']([A-Za-z][A-Za-z0-9_]*)[\"']")
# Visualforce/Aura markup extraction. VF is not reliably well-formed XML (merge fields inside
# attributes), so the shared parser is regex-based over the raw markup.
VF_STANDARD_CONTROLLER_RE = re.compile(r'standardController\s*=\s*"([^"]+)"', re.IGNORECASE)
VF_EXTENSIONS_RE = re.compile(r'extensions\s*=\s*"([^"]+)"', re.IGNORECASE)
VF_INPUT_FIELD_RE = re.compile(
    r'<apex:inputField[^>]*value\s*=\s*"\{!([A-Za-z0-9_.]+)\}"', re.IGNORECASE
)
VF_OUTPUT_FIELD_RE = re.compile(
    r'<apex:outputField[^>]*value\s*=\s*"\{!([A-Za-z0-9_.]+)\}"', re.IGNORECASE
)
VF_ACTION_METHOD_RE = re.compile(r'action\s*=\s*"\{!([A-Za-z_][A-Za-z0-9_]*)\}"')
VF_EMBED_RE = re.compile(r"<c:([A-Za-z][A-Za-z0-9_]*)")
MARKUP_ATTRIBUTE_TYPE_RE = re.compile(
    r'<(?:apex|aura):attribute[^>]*type\s*=\s*"([^"]+)"', re.IGNORECASE
)
AURA_IMPLEMENTS_RE = re.compile(r'implements\s*=\s*"([^"]+)"', re.IGNORECASE)
AURA_EXTENDS_RE = re.compile(r'extends\s*=\s*"([^"]+)"', re.IGNORECASE)
AURA_RECORD_OBJECT_RE = re.compile(
    r'(?:sObjectName|objectApiName)\s*=\s*"([A-Za-z][A-Za-z0-9_]*)"', re.IGNORECASE
)
AURA_RECORD_FIELDS_RE = re.compile(r'\bfields\s*=\s*"([A-Za-z0-9_,\s.]+)"', re.IGNORECASE)
MARKUP_LABEL_RE = re.compile(r"\$Label\.(?:c\.)?([A-Za-z][A-Za-z0-9_]*)")
APEX_LABEL_RE = re.compile(r"\b(?:System\.)?Label\.([A-Za-z][A-Za-z0-9_]*)")
# $Permission token in validation-rule/flow formulas — closes the "who can trigger this branch"
# chain against permission-set grants-custom-permission edges.
PERMISSION_TOKEN_RE = re.compile(r"\$Permission\.([A-Za-z][A-Za-z0-9_]*)")
# Source-token heuristics for Apex usage. These read declared source only and are best-effort: they
# do not resolve variable types or dynamic SOQL, so the automation-inventory claim records an
# explicit heuristic limitation.
# A bare `FROM x` also matches prose inside string literals ("name defaulted from account"),
# and string literals cannot simply be stripped because dynamic SOQL lives in them
# (Database.query('SELECT Id FROM Account')). Binding FROM to its SELECT keeps dynamic SOQL
# and rejects prose. The bounded gap stops one SELECT from claiming a FROM far below it.
SOQL_FROM_RE = re.compile(
    r"\bSELECT\b[\s\S]{0,600}?\bFROM\s+([A-Za-z][A-Za-z0-9_]*)", re.IGNORECASE
)
DML_RE = re.compile(r"\b(insert|update|upsert|delete|undelete)\b", re.IGNORECASE)
APEX_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\.[A-Za-z_][A-Za-z0-9_]*\s*\(")
# Construction, which the call regex above cannot see: it requires an identifier immediately
# followed by `.`, so `new AssignmentTriggerHandler().run()` — the standard one-trigger-per-object
# handler idiom — matched nothing. That made the first hop of every execution chain invisible:
# `impact --direction outgoing` from a trigger reached the object it operates on and stopped.
APEX_NEW_RE = re.compile(r"\bnew\s+([A-Z][A-Za-z0-9_]{2,})\s*\(")
# Inline SOQL blocks for field-level extraction (standard fields included — the FROM object gives
# the context that FORMULA_FIELD_RE lacks). Still a source-token heuristic: dynamic SOQL strings
# and relationship paths are not resolved.
SOQL_BLOCK_RE = re.compile(r"\[\s*(SELECT\b[^\]]*?)\]", re.IGNORECASE | re.DOTALL)
SOQL_KEYWORDS = frozenset(
    {
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "NULL", "TRUE", "FALSE", "LIKE", "IN",
        "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "ASC", "DESC", "NULLS", "FIRST",
        "LAST", "TODAY", "YESTERDAY", "TOMORROW", "THIS_WEEK", "LAST_WEEK", "NEXT_WEEK",
        "THIS_MONTH", "LAST_MONTH", "NEXT_MONTH", "THIS_YEAR", "LAST_YEAR", "NEXT_YEAR",
        "INCLUDES", "EXCLUDES", "WITH", "SECURITY_ENFORCED", "USER_MODE", "SYSTEM_MODE",
        "FOR", "UPDATE", "VIEW", "REFERENCE", "ALL", "ROWS", "TYPEOF", "END", "WHEN", "THEN", "ELSE",
    }
)
SOQL_COMPARISON_FIELD_RE = re.compile(r"(?<!\.)\b([A-Za-z][A-Za-z0-9_]*)\s*(?:=|!=|<>|<=|>=|<|>)")
SOQL_OPERATOR_FIELD_RE = re.compile(
    r"(?<!\.)\b([A-Za-z][A-Za-z0-9_]*)\s+(?:LIKE|IN|NOT\s+IN|INCLUDES|EXCLUDES)\b", re.IGNORECASE
)
SOQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# Local sObject variable declarations (`Account record;` / `ParentObject__c row = ...`). Only types that
# are custom-object tokens or SOQL FROM targets in the same file are treated as objects, so an
# ordinary class instance never masquerades as an sObject.
APEX_VAR_DECL_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:__c|__mdt|__e|__x)?)\s+([a-z][A-Za-z0-9_]*)\s*[=;]"
)
# Apex declaration facts: sharing posture, annotations, inheritance, and test markers read from
# the class header. Source-token level, but the header grammar is regular enough to be reliable.
APEX_SHARING_RE = re.compile(r"\b(with|without|inherited)\s+sharing\b", re.IGNORECASE)
# An annotation only counts when it opens a token: preceded by line start, whitespace or `(`.
# `user@example.com` in a comment therefore no longer registers as an annotation, and the
# per-line filter below drops ApexDoc tags (`@description`, `@param`) that live inside
# comment blocks. Verified against real package source, where the naive pattern reported
# `description` 39 times and an email domain once, against 25 genuine annotations.
APEX_ANNOTATION_RE = re.compile(r"(?:(?<=^)|(?<=[\s(]))@([A-Za-z][A-Za-z0-9_]*)")
APEX_COMMENT_LINE_RE = re.compile(r"^\s*(?:\*|//|/\*)")
# ApexDoc `@description` in the header block: the author stating what the class is for.
# Declarative metadata carries the same thing in <description>; Apex keeps it in a comment,
# which is why it has to be read from the comment rather than from code lines.
APEXDOC_DESCRIPTION_RE = re.compile(
    r"@description\s+(.+?)(?=\n\s*\*\s*@|\n\s*\*/)", re.DOTALL | re.IGNORECASE
)
APEX_EXTENDS_RE = re.compile(r"\bextends\s+([A-Za-z][A-Za-z0-9_]*)")
APEX_IMPLEMENTS_RE = re.compile(r"\bimplements\s+([A-Za-z0-9_.,<>\s]+?)\s*\{")
APEX_TEST_RE = re.compile(r"@isTest\b|\btestMethod\b", re.IGNORECASE)
# DML statements and Database.* calls with the expression that follows the verb: either a
# `new Type(...)` construction (type is direct) or a variable resolved via the declaration map.
APEX_DML_TARGET_RE = re.compile(
    r"\b(insert|update|upsert|delete|undelete)\s+(?:as\s+(?:user|system)\s+)?"
    r"(new\s+)?([A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
APEX_DATABASE_DML_RE = re.compile(
    r"\bDatabase\.(insert|update|upsert|delete|undelete)[A-Za-z]*\s*\(\s*"
    r"(new\s+)?([A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
# Loop variable declarations (`for (Case item : Trigger.new)`) — the one declaration form the
# `[=;]`-anchored APEX_VAR_DECL_RE cannot see, and the dominant shape in trigger code.
APEX_LOOP_VAR_RE = re.compile(
    r"\bfor\s*\(\s*([A-Z][A-Za-z0-9_]*)\s+([a-z][A-Za-z0-9_]*)\s*:"
)
# Outbound callout surfaces: named-credential literals are deterministic; raw URL literals are a
# heuristic (string may never reach a request) and collapse to their hostname.
APEX_CALLOUT_NC_RE = re.compile(r"['\"]callout:([A-Za-z][A-Za-z0-9_]*)")
APEX_ENDPOINT_URL_RE = re.compile(r"['\"](https?://[^'\"\s]+)['\"]")
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

AUTOMATION_TYPES = frozenset(
    {
        "Flow",
        "ApexClass",
        "ApexTrigger",
        "ApprovalProcess",
        "ValidationRule",
        "Workflow",
        "DuplicateRule",
        "AssignmentRules",
        "AutoResponseRules",
        "EscalationRules",
    }
)
UI_TYPES = frozenset(
    {
        "LightningComponentBundle",
        "AuraDefinitionBundle",
        "ApexPage",
        "FlexiPage",
        "Layout",
        "CustomTab",
        "QuickAction",
        "CustomApplication",
        "ApexComponent",
    }
)


def code_lines(source: str) -> str:
    """Source with comment-only lines removed, for declaration and annotation scanning.

    Apex regexes that scan raw source read prose as code: a header comment reading
    "Base class for all trigger handlers" made CLASS_RE report the class name as `for`, and
    two real classes then collided on one identity — one silently overwrote the other.
    Only whole comment lines are dropped; comments are never stripped mid-line because
    string literals legitimately contain `//` (endpoint URLs)."""

    return "\n".join(
        line for line in source.splitlines() if not APEX_COMMENT_LINE_RE.match(line)
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


# Hard sanitization lines for captured criteria/filter literals. Values are org configuration
# (picklist states, thresholds, routing keys) and are captured by policy, but anything that looks
# like a credential, email address, or IP address is dropped entirely, and URLs collapse to their
# hostname — matching the endpoint-host rule used for integration metadata.
LITERAL_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|bearer|authorization|client[_-]?secret)\b"
)
LITERAL_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
LITERAL_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LITERAL_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
LITERAL_MAX_LENGTH = 200


def sanitize_literal(value: str | None) -> str | None:
    """Criteria/filter literal safe for the sanitized inventory, or None when it must be dropped."""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if "://" in text:
        return urlsplit(text).hostname
    if LITERAL_SECRET_RE.search(text) or LITERAL_ENTROPY_RE.search(text):
        return None
    if LITERAL_EMAIL_RE.search(text) or LITERAL_IP_RE.search(text):
        return None
    if len(text) > LITERAL_MAX_LENGTH:
        return text[: LITERAL_MAX_LENGTH - 1] + "…"
    return text


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


class ForceAppKnowledge:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()
        self.source_root = self.root / "force-app"
        self.cache_root = self.root / ".cache/knowledge-proposals"
        self.inventory_path = self.cache_root / "force-app-inventory.json"
        # Extractor tuning: config/knowledge-extraction.json overrides; built-in defaults keep
        # template repos working without local configuration.
        extraction: dict[str, Any] = {}
        extraction_path = self.root / "config/knowledge-extraction.json"
        if extraction_path.is_file():
            try:
                extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise KnowledgeBuildError(f"config/knowledge-extraction.json is not valid JSON: {exc}")
        self.max_usage_refs = int(extraction.get("maxUsageRefs", MAX_USAGE_REFS))
        self.apex_system_types = APEX_SYSTEM_TYPES | set(extraction.get("additionalSystemTypes", []))
        self.soql_field_extraction = bool(extraction.get("soqlFieldExtraction", True))
        self.local_variable_resolution = bool(extraction.get("localVariableResolution", True))
        self.error_surface_extraction = bool(extraction.get("errorSurfaceExtraction", True))
        self.markup_field_extraction = bool(extraction.get("markupFieldExtraction", True))
        self._custom_labels: dict[str, str] | None = None
        self._relationship_targets: dict[tuple[str, str], str] | None = None

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

    @staticmethod
    def _object_kind(name: str, root: ET.Element) -> str:
        """What this .object file actually is — the top routing fact for every consumer.

        Custom settings, platform events, big objects, custom metadata types, and standard-object
        extension files all share the CustomObject source format and are indistinguishable by
        suffix-blind parsing."""

        if name.endswith("__mdt"):
            return "customMetadataType"
        if name.endswith("__e") or direct_text(root, "eventType"):
            return "platformEvent"
        if name.endswith("__b"):
            return "bigObject"
        if direct_text(root, "customSettingsType"):
            return "customSetting"
        if name.endswith(("__c", "__x")):
            return "customObject"
        return "standardObjectExtension"

    def parse_object(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = object_from_path(path)
        label = direct_text(root, "label")
        name_field = next(
            (item for item in list(root) if local_name(item.tag) == "nameField"), None
        )
        return self.component(
            "CustomObject",
            name,
            path,
            {
                "label": label,
                "pluralLabel": direct_text(root, "pluralLabel"),
                "description": direct_text(root, "description"),
                "objectKind": self._object_kind(name, root),
                "deploymentStatus": direct_text(root, "deploymentStatus"),
                "sharingModel": direct_text(root, "sharingModel"),
                "externalSharingModel": direct_text(root, "externalSharingModel"),
                "customSettingsType": direct_text(root, "customSettingsType"),
                "eventType": direct_text(root, "eventType"),
                "publishBehavior": direct_text(root, "publishBehavior"),
                "nameField": compact(
                    {
                        "type": direct_text(name_field, "type"),
                        "label": direct_text(name_field, "label"),
                        "displayFormat": direct_text(name_field, "displayFormat"),
                    }
                )
                if name_field is not None
                else None,
                "enableHistory": boolean(direct_text(root, "enableHistory")),
                "enableFeeds": boolean(direct_text(root, "enableFeeds")),
                "enableActivities": boolean(direct_text(root, "enableActivities")),
                "enableReports": boolean(direct_text(root, "enableReports")),
                "enableSearch": boolean(direct_text(root, "enableSearch")),
                "compactLayoutAssignment": direct_text(root, "compactLayoutAssignment"),
            },
            needle=f"<label>{label}</label>" if label else None,
        )

    def relationship_targets(self) -> dict[tuple[str, str], str]:
        """(object, lookup-field stem) → referenced object, from every repo field file.

        `X__r` in a formula names the lookup field `X__c` on the current object; resolving a hop
        needs the whole field inventory, so the map is built once per run (custom_labels pattern)."""

        if self._relationship_targets is None:
            targets: dict[tuple[str, str], str] = {}
            if self.source_root.is_dir():
                for path in sorted(self.source_root.rglob("*.field-meta.xml")):
                    try:
                        root = self.parse_xml(path)
                        owner = object_from_path(path)
                    except (ET.ParseError, OSError, ValueError):
                        continue
                    field_name = direct_text(root, "fullName") or path.name.removesuffix(
                        ".field-meta.xml"
                    )
                    reference_to = descendant_texts(root, "referenceTo")
                    if reference_to and field_name.endswith("__c"):
                        targets[(owner, field_name[:-3])] = reference_to[0]
            self._relationship_targets = targets
        return self._relationship_targets

    def formula_field_references(
        self, object_name: str, formula: str
    ) -> list[dict[str, Any]]:
        """references-field edges for a formula: resolved `__r` chains, then same-object tokens.

        Chains resolve hop by hop through relationship_targets(); an unresolvable hop drops the
        span entirely — the extractor never guesses the owning object. Matched spans are removed
        before the bare-token pass so `Status__c` inside `ParentObject__r.Status__c` is not also
        misattributed to the formula's own object. All edges are regex-derived → per-ref heuristic."""

        references: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(target: str) -> None:
            if target not in seen:
                seen.add(target)
                references.append(
                    {"kind": "references-field", "target": target, "heuristic": True}
                )

        for match in FORMULA_CHAIN_RE.finditer(formula):
            chain, final_field = match.group(1), match.group(2)
            current = object_name
            for hop in chain.split("."):
                resolved = self.relationship_targets().get((current, hop[:-3]))
                if resolved is None:
                    current = None
                    break
                current = resolved
            if current:
                add(f"{current}.{final_field}")
        remaining = FORMULA_CHAIN_RE.sub(" ", formula)
        for token in sorted(set(FORMULA_FIELD_RE.findall(remaining))):
            add(f"{object_name}.{token}")
        return references

    def cap_references(
        self,
        references: list[dict[str, Any]],
        priorities: dict[str, int] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Uniform edge cap: prioritized cut at max_usage_refs plus truncation disclosure.

        Returns (kept, truncation_facts); merge the facts dict into the parser's facts so
        `referencesTruncated`/`truncatedFamilies` reach extraction coverage. Lower priority
        rank survives longest; unlisted kinds rank 50; the sort is stable so document order
        is preserved within a rank, and kept edges keep their original relative order."""

        if len(references) <= self.max_usage_refs:
            return references, {}
        ranked = sorted(
            enumerate(references),
            key=lambda item: ((priorities or {}).get(item[1]["kind"], 50), item[0]),
        )
        kept_positions = sorted(position for position, _ in ranked[: self.max_usage_refs])
        dropped = [reference for _, reference in ranked[self.max_usage_refs :]]
        return [references[position] for position in kept_positions], {
            "referencesTruncated": True,
            "truncatedFamilies": sorted({reference["kind"] for reference in dropped}),
        }

    def parse_field(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        object_name = object_from_path(path)
        field_name = direct_text(root, "fullName") or path.name.removesuffix(
            ".field-meta.xml"
        )
        targets = descendant_texts(root, "referenceTo")
        references: list[dict[str, Any]] = [
            {"kind": "relationship", "target": target} for target in targets
        ]
        seen_references = {("relationship", target) for target in targets}

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        # Containment. A plain Text/Number/Checkbox field emitted no references at all (63 of 93
        # fields in a 189-component probe corpus), so composition was not a graph question: the
        # owning object was reachable only through a per-type facet. This is the child side; the
        # index inverts it. Not `operates-on`, which on a rollup names the summarised CHILD object.
        add_reference("belongs-to", object_name)

        # Picklist vocabulary: local values, global value-set link, dependency wiring.
        value_set = next(
            (item for item in list(root) if local_name(item.tag) == "valueSet"), None
        )
        value_set_name = None
        picklist_restricted = None
        picklist_sorted = None
        controlling_field = None
        picklist_values: list[dict[str, Any]] = []
        picklist_value_count = 0
        if value_set is not None:
            value_set_name = direct_text(value_set, "valueSetName")
            picklist_restricted = boolean(direct_text(value_set, "restricted"))
            controlling_field = direct_text(value_set, "controllingField")
            definition = next(
                (
                    item
                    for item in list(value_set)
                    if local_name(item.tag) == "valueSetDefinition"
                ),
                None,
            )
            if definition is not None:
                picklist_sorted = boolean(direct_text(definition, "sorted"))
                for value in (
                    item for item in definition.iter() if local_name(item.tag) == "value"
                ):
                    picklist_value_count += 1
                    if len(picklist_values) < PICKLIST_VALUE_CAP:
                        picklist_values.append(
                            compact(
                                {
                                    "fullName": direct_text(value, "fullName"),
                                    "label": direct_text(value, "label"),
                                    "default": boolean(direct_text(value, "default")),
                                    "isActive": boolean(direct_text(value, "isActive")),
                                }
                            )
                        )
            add_reference("uses-value-set", value_set_name)
            if controlling_field:
                add_reference("picklist-dependency", f"{object_name}.{controlling_field}")
        # Roll-up summary: declared Object.Field paths — deterministic lineage, no heuristics.
        summary_foreign_key = direct_text(root, "summaryForeignKey")
        summarized_field = direct_text(root, "summarizedField")
        summary_filters = [
            entry
            for item in list(root)
            if local_name(item.tag) == "summaryFilterItems"
            for entry in self._criteria_entries(item)
        ]
        add_reference("references-field", summary_foreign_key)
        add_reference("references-field", summarized_field)
        if summarized_field and "." in summarized_field:
            add_reference("operates-on", summarized_field.split(".", 1)[0])
        for entry in summary_filters:
            add_reference("references-field", entry["field"])
        # Lookup filter: fields constraining which records the lookup accepts.
        lookup_filter = next(
            (item for item in list(root) if local_name(item.tag) == "lookupFilter"), None
        )
        lookup_filter_entries = (
            self._criteria_entries(lookup_filter) if lookup_filter is not None else []
        )
        for entry in lookup_filter_entries:
            if not entry["field"].startswith("$"):
                add_reference("filters-field", entry["field"])
        formula = direct_text(root, "formula")
        if formula:
            for reference in self.formula_field_references(object_name, formula):
                if (reference["kind"], reference["target"]) not in seen_references:
                    seen_references.add((reference["kind"], reference["target"]))
                    references.append(reference)
        return self.component(
            "CustomField",
            f"{object_name}.{field_name}",
            path,
            {
                "object": object_name,
                "fullName": field_name,
                "label": direct_text(root, "label"),
                "description": direct_text(root, "description"),
                "inlineHelpText": direct_text(root, "inlineHelpText"),
                "type": direct_text(root, "type"),
                "required": boolean(direct_text(root, "required")),
                "unique": boolean(direct_text(root, "unique")),
                "externalId": boolean(direct_text(root, "externalId")),
                "caseSensitive": boolean(direct_text(root, "caseSensitive")),
                "encrypted": (
                    True
                    if direct_text(root, "encryptionScheme")
                    or direct_text(root, "type") == "EncryptedText"
                    else None
                ),
                "length": direct_text(root, "length"),
                "precision": direct_text(root, "precision"),
                "scale": direct_text(root, "scale"),
                "defaultValue": sanitize_literal(direct_text(root, "defaultValue")),
                "trackHistory": boolean(direct_text(root, "trackHistory")),
                "trackFeedHistory": boolean(direct_text(root, "trackFeedHistory")),
                "relationshipName": direct_text(root, "relationshipName"),
                "relationshipLabel": direct_text(root, "relationshipLabel"),
                "relationshipOrder": direct_text(root, "relationshipOrder"),
                "deleteConstraint": direct_text(root, "deleteConstraint"),
                "reparentableMasterDetail": boolean(
                    direct_text(root, "reparentableMasterDetail")
                ),
                "writeRequiresMasterRead": boolean(
                    direct_text(root, "writeRequiresMasterRead")
                ),
                "referenceTo": targets,
                "formula": formula,
                "formulaTreatBlanksAs": direct_text(root, "formulaTreatBlanksAs"),
                "valueSetName": value_set_name,
                "picklistRestricted": picklist_restricted,
                "picklistSorted": picklist_sorted,
                "controllingField": controlling_field,
                "picklistValues": picklist_values or None,
                "picklistValueCount": picklist_value_count or None,
                "picklistValuesTruncated": (
                    True if picklist_value_count > len(picklist_values) else None
                ),
                "summaryOperation": direct_text(root, "summaryOperation"),
                "summaryForeignKey": summary_foreign_key,
                "summarizedField": summarized_field,
                "summaryFilterFields": sorted({entry["field"] for entry in summary_filters})
                or None,
                "lookupFilterPresent": True if lookup_filter is not None else None,
                "lookupFilterFields": sorted(
                    {entry["field"] for entry in lookup_filter_entries}
                )
                or None,
            },
            references,
            f"<fullName>{field_name}</fullName>",
        )

    # Flow data elements and the record operation each performs. Read from source only: which
    # objects/fields the Flow declares it touches, never runtime values. Field polarity is routed
    # per child tag instead of per element: queriedFields are reads, inputAssignments are writes,
    # and filters are selection criteria (filters-field) on every element kind — an update's
    # filter fields select records, they are not written.
    FLOW_DATA_ELEMENTS = {
        "recordLookups": "lookup",
        "recordCreates": "create",
        "recordUpdates": "update",
        "recordDeletes": "delete",
    }

    @staticmethod
    def _criteria_entries(element: ET.Element) -> list[dict[str, Any]]:
        """Declared filter/criteria rows under a metadata element, values sanitized.

        Handles the two source shapes that repeat across automation metadata: Flow-style
        <filters> (field/operator with the literal wrapped in a typed <value> child or given
        as an <elementReference>) and Workflow/rule-style <criteriaItems> (field/operation/
        value). Literals pass sanitize_literal — captured by policy, minus credentials,
        emails, IPs, and URL paths."""

        entries: list[dict[str, Any]] = []
        for item in element.iter():
            if local_name(item.tag) not in {
                "filters",
                "criteriaItems",
                "filterItems",
                "summaryFilterItems",
            }:
                continue
            field = direct_text(item, "field")
            if not field:
                continue
            operator = direct_text(item, "operator") or direct_text(item, "operation")
            value = direct_text(item, "value") or direct_text(item, "valueField")
            element_reference = direct_text(item, "elementReference")
            if value is None:
                for child in list(item):
                    if local_name(child.tag) != "value":
                        continue
                    for typed in list(child):
                        if not (typed.text and typed.text.strip()):
                            continue
                        if local_name(typed.tag) == "elementReference":
                            element_reference = element_reference or typed.text.strip()
                        else:
                            value = typed.text.strip()
                        break
            entries.append(
                compact(
                    {
                        "field": field,
                        "operator": operator,
                        "value": sanitize_literal(value),
                        "elementReference": element_reference,
                    }
                )
            )
        return entries

    def custom_labels(self) -> dict[str, str]:
        """Custom label values from force-app *.labels-meta.xml, loaded once per run.

        Loaded independently of the per-parser inventory loop: flows may parse before the
        labels file is reached, so $Label resolution cannot rely on scan order."""

        if self._custom_labels is None:
            labels: dict[str, str] = {}
            if self.source_root.is_dir():
                for path in sorted(self.source_root.rglob("*.labels-meta.xml")):
                    try:
                        root = self.parse_xml(path)
                    except (ET.ParseError, OSError):
                        continue
                    for element in root.iter():
                        if local_name(element.tag) != "labels":
                            continue
                        name = direct_text(element, "fullName")
                        value = direct_text(element, "value")
                        if name and value:
                            labels[name] = value
            self._custom_labels = labels
        return self._custom_labels

    def resolved_error_message(self, message: str) -> str | None:
        """Message with $Label tokens substituted, or None when nothing resolved.

        Tokens without a matching repo label stay raw, so a partially resolved template is
        still returned as long as at least one label substituted."""

        labels = self.custom_labels()

        def substitute(match: re.Match[str]) -> str:
            name = match.group(1) or match.group(2)
            return labels.get(name, match.group(0))

        resolved = LABEL_TOKEN_RE.sub(substitute, message)
        return resolved if resolved != message else None

    @staticmethod
    def _flow_condition_text(condition: ET.Element) -> str:
        """`leftValueReference operator right` for one decision-rule condition."""

        right: str | None = None
        for child in list(condition):
            if local_name(child.tag) == "rightValue":
                for value in list(child):
                    if value.text and value.text.strip():
                        right = value.text.strip()
                        break
        parts = [
            part
            for part in (
                direct_text(condition, "leftValueReference"),
                direct_text(condition, "operator"),
                right,
            )
            if part
        ]
        return " ".join(parts)

    @classmethod
    def _flow_reverse_graph(cls, flow_root: ET.Element) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """target element -> [(source element, edge metadata)] over declared connectors.

        Decision-rule edges carry the outcome name/label and serialized conditions;
        defaultConnector edges are marked default and faultConnector edges fault. The start
        element is the pseudo-node "$start" (element names cannot contain "$")."""

        reverse: dict[str, list[tuple[str, dict[str, Any]]]] = {}

        def add_edge(source: str, connector: ET.Element, meta: dict[str, Any]) -> None:
            target = direct_text(connector, "targetReference")
            if target:
                reverse.setdefault(target, []).append((source, meta))

        for element in list(flow_root):
            tag = local_name(element.tag)
            if tag == "start":
                # Direct connector plus any scheduled-path connectors.
                for connector in element.iter():
                    if local_name(connector.tag) == "connector":
                        add_edge("$start", connector, {})
                continue
            name = direct_text(element, "name")
            if not name:
                continue
            if tag == "decisions":
                for child in list(element):
                    if local_name(child.tag) == "rules":
                        meta: dict[str, Any] = {}
                        outcome = direct_text(child, "name")
                        if outcome:
                            meta["outcome"] = outcome
                        outcome_label = direct_text(child, "label")
                        if outcome_label and outcome_label != outcome:
                            meta["outcomeLabel"] = outcome_label
                        conditions = [
                            text
                            for text in (
                                cls._flow_condition_text(condition)
                                for condition in list(child)
                                if local_name(condition.tag) == "conditions"
                            )
                            if text
                        ]
                        if conditions:
                            meta["conditions"] = conditions
                        for connector in list(child):
                            if local_name(connector.tag) == "connector":
                                add_edge(name, connector, meta)
                    elif local_name(child.tag) == "defaultConnector":
                        add_edge(name, child, {"default": True})
                continue
            for connector in element.iter():
                connector_tag = local_name(connector.tag)
                if connector_tag in {"connector", "nextValueConnector", "noMoreValuesConnector"}:
                    add_edge(name, connector, {})
                elif connector_tag == "faultConnector":
                    add_edge(name, connector, {"fault": True})
        return reverse

    @classmethod
    def _flow_error_paths(
        cls, reverse: dict[str, list[tuple[str, dict[str, Any]]]], element_name: str
    ) -> tuple[list[list[dict[str, Any]]], bool]:
        """Simple paths from the flow start to an error element, as decision hops only.

        Backward DFS over the reverse graph; the per-path visited set makes loops safe. Caps:
        FLOW_ERROR_PATH_CAP paths and FLOW_ERROR_PATH_DEPTH elements per path, with the
        truncation flag set when either cap cut real exploration short."""

        paths: list[list[dict[str, Any]]] = []
        truncated = False

        def visit(node: str, trail: tuple[str, ...], hops: tuple[dict[str, Any], ...]) -> None:
            nonlocal truncated
            if len(paths) > FLOW_ERROR_PATH_CAP:
                return
            if node == "$start":
                paths.append(list(reversed(hops)))
                return
            if len(trail) >= FLOW_ERROR_PATH_DEPTH:
                truncated = True
                return
            predecessors = sorted(
                reverse.get(node, []), key=lambda item: (item[0], str(item[1]))
            )
            for source, meta in predecessors:
                if source in trail:
                    continue
                hop: dict[str, Any] | None = None
                if "outcome" in meta or meta.get("default"):
                    hop = {"decision": source}
                    for key in ("outcome", "outcomeLabel", "conditions", "default"):
                        if key in meta:
                            hop[key] = meta[key]
                visit(source, trail + (source,), hops + ((hop,) if hop else ()))

        visit(element_name, (element_name,), ())
        if len(paths) > FLOW_ERROR_PATH_CAP:
            paths = paths[:FLOW_ERROR_PATH_CAP]
            truncated = True
        paths.sort(key=lambda path: (len(path), json.dumps(path, sort_keys=True)))
        # Distinct element routes can share the same decision hops (e.g. a normal and a fault
        # connector into the same screen) — only the decision scenario is reported, once.
        unique: list[list[dict[str, Any]]] = []
        seen: set[str] = set()
        for path in paths:
            key = json.dumps(path, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique, truncated

    def _flow_error_catalog(
        self, flow_root: ET.Element, object_name: str | None, trigger_context: str | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Declared error surfaces: custom errors, screen validation messages, fault paths.

        Source-declared author text and the decision outcomes that statically guard it —
        never runtime values or record data."""

        reverse = self._flow_reverse_graph(flow_root)
        entries: list[dict[str, Any]] = []
        references: list[dict[str, str]] = []
        seen_references: set[tuple[str, str]] = set()

        def entry(component: str, kind: str, node: str, **extra: Any) -> dict[str, Any]:
            item: dict[str, Any] = {"component": component, "kind": kind, **extra}
            message = item.get("errorMessage")
            if isinstance(message, str):
                resolved = self.resolved_error_message(message)
                if resolved:
                    item["resolvedErrorMessage"] = resolved
            if trigger_context:
                item["triggerContext"] = trigger_context
            paths, paths_truncated = self._flow_error_paths(reverse, node)
            if paths:
                item["paths"] = paths
            if paths_truncated:
                item["pathsTruncated"] = True
            return compact(item)

        for element in list(flow_root):
            tag = local_name(element.tag)
            name = direct_text(element, "name")
            if not name:
                continue
            if tag == "customErrors":
                label = direct_text(element, "label")
                for message_element in list(element):
                    if local_name(message_element.tag) != "customErrorMessages":
                        continue
                    field_selection = direct_text(message_element, "fieldSelection")
                    entries.append(
                        entry(
                            name,
                            "custom-error",
                            name,
                            componentLabel=label,
                            errorMessage=direct_text(message_element, "errorMessage"),
                            isFieldError=boolean(direct_text(message_element, "isFieldError")),
                            fieldSelection=field_selection,
                        )
                    )
                    if field_selection and object_name:
                        reference = ("references-field", f"{object_name}.{field_selection}")
                        if reference not in seen_references:
                            seen_references.add(reference)
                            references.append({"kind": reference[0], "target": reference[1]})
            elif tag == "screens":
                screen_label = direct_text(element, "label")
                for field in (item for item in element.iter() if local_name(item.tag) == "fields"):
                    field_name = direct_text(field, "name")
                    for rule in list(field):
                        if local_name(rule.tag) != "validationRule":
                            continue
                        message = direct_text(rule, "errorMessage")
                        if not message:
                            continue
                        entries.append(
                            entry(
                                field_name or name,
                                "screen-validation",
                                name,
                                componentLabel=screen_label,
                                errorMessage=message,
                                condition=direct_text(rule, "formulaExpression"),
                            )
                        )
            for connector in list(element):
                if local_name(connector.tag) == "faultConnector":
                    entries.append(
                        entry(
                            name,
                            "fault-path",
                            name,
                            faultTarget=direct_text(connector, "targetReference"),
                        )
                    )
        return entries, references

    @staticmethod
    def _flow_variables(root: ET.Element) -> list[dict[str, Any]]:
        """Declared Flow variables: the data-shape contract for subflow I/O and inputReference."""

        variables: list[dict[str, Any]] = []
        for element in (item for item in root.iter() if local_name(item.tag) == "variables"):
            name = direct_text(element, "name")
            if not name:
                continue
            variables.append(
                compact(
                    {
                        "name": name,
                        "dataType": direct_text(element, "dataType"),
                        "objectType": direct_text(element, "objectType"),
                        "isCollection": boolean(direct_text(element, "isCollection")),
                        "isInput": boolean(direct_text(element, "isInput")),
                        "isOutput": boolean(direct_text(element, "isOutput")),
                    }
                )
            )
        return variables

    @staticmethod
    def _flow_reference_field(
        token: str, object_name: str | None, variable_objects: dict[str, str]
    ) -> str | None:
        """`Object.Field` for a `$Record.X`/`variable.X` reference token, None when unresolvable.

        Relationship paths (more than one hop) are not resolved — the extractor never guesses
        across objects it has not parsed."""

        parts = token.split(".")
        if len(parts) != 2:
            return None
        head, field = parts
        if head in {"$Record", "$Record__Prior"} and object_name:
            return f"{object_name}.{field}"
        if head in variable_objects:
            return f"{variable_objects[head]}.{field}"
        return None

    def parse_flow(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        starts = [item for item in root.iter() if local_name(item.tag) == "start"]
        start = starts[0] if starts else root
        object_name = direct_text(start, "object") or direct_text(root, "object")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        if object_name:
            add_reference("operates-on", object_name)
        for value in descendant_texts(root, "flowName"):
            add_reference("subflow", value)
        for value in descendant_texts(root, "actionName"):
            add_reference("action", value)
        variables = self._flow_variables(root)
        variable_objects = {
            item["name"]: item["objectType"] for item in variables if item.get("objectType")
        }
        # Usage registry: per-element record operations with polarity routed per child tag —
        # queriedFields are reads, inputAssignments are writes, filters are selection criteria.
        referenced_objects: set[str] = set()
        if object_name:
            referenced_objects.add(object_name)
        data_operations: list[dict[str, Any]] = []
        for tag, operation in self.FLOW_DATA_ELEMENTS.items():
            for element in (item for item in root.iter() if local_name(item.tag) == tag):
                input_reference = direct_text(element, "inputReference")
                element_object = direct_text(element, "object")
                if element_object is None and input_reference:
                    element_object = variable_objects.get(input_reference.split(".", 1)[0])
                if element_object:
                    referenced_objects.add(element_object)

                def qualified(field: str) -> str:
                    return f"{element_object}.{field}" if element_object else field

                filters = self._criteria_entries(element)
                filter_fields = sorted({entry["field"] for entry in filters})
                retrieved_fields = descendant_texts(element, "queriedFields")
                written_fields = sorted(
                    {
                        field
                        for assignment in element.iter()
                        if local_name(assignment.tag) == "inputAssignments"
                        for field in [direct_text(assignment, "field")]
                        if field
                    }
                )
                output_target = (
                    direct_text(element, "outputReference")
                    or direct_text(element, "assignRecordIdToReference")
                    or (
                        "auto"
                        if boolean(direct_text(element, "storeOutputAutomatically"))
                        else None
                    )
                )
                for field in filter_fields:
                    add_reference("filters-field", qualified(field))
                for field in retrieved_fields:
                    add_reference("reads-field", qualified(field))
                for field in written_fields:
                    add_reference("writes-field", qualified(field))
                if element_object:
                    if operation == "lookup":
                        add_reference("queries-object", element_object)
                    else:
                        add_reference("dml-object", element_object)
                data_operations.append(
                    compact(
                        {
                            "element": direct_text(element, "name"),
                            "kind": operation,
                            "object": element_object,
                            "inputReference": input_reference,
                            "filterFields": filter_fields,
                            "filterLogic": direct_text(element, "filterLogic"),
                            "filters": filters,
                            "retrievedFields": retrieved_fields,
                            "writtenFields": written_fields,
                            "outputTarget": output_target,
                            "getFirstRecordOnly": boolean(
                                direct_text(element, "getFirstRecordOnly")
                            ),
                            "sortField": direct_text(element, "sortField"),
                            "sortOrder": direct_text(element, "sortOrder"),
                            "limit": direct_text(element, "limit"),
                        }
                    )
                )
        # Decision conditions and formula expressions reference record/variable fields.
        for condition in (item for item in root.iter() if local_name(item.tag) == "conditions"):
            token = direct_text(condition, "leftValueReference")
            if token:
                add_reference(
                    "references-field",
                    self._flow_reference_field(token, object_name, variable_objects),
                )
        formulas: list[dict[str, Any]] = []
        for element in (item for item in root.iter() if local_name(item.tag) == "formulas"):
            formula_name = direct_text(element, "name")
            expression = direct_text(element, "expression") or ""
            field_refs = sorted(
                {
                    resolved
                    for token in re.findall(r"\{!([A-Za-z0-9_$]+\.[A-Za-z0-9_.]+)\}", expression)
                    for resolved in [
                        self._flow_reference_field(token, object_name, variable_objects)
                    ]
                    if resolved
                }
            )
            for target in field_refs:
                add_reference("references-field", target)
            if formula_name:
                formulas.append(
                    compact(
                        {
                            "name": formula_name,
                            "dataType": direct_text(element, "dataType"),
                            "fieldRefs": field_refs,
                        }
                    )
                )
        # Invoked Apex: actionCalls whose actionType is apex name a class the Flow depends on.
        for element in (item for item in root.iter() if local_name(item.tag) == "actionCalls"):
            if direct_text(element, "actionType") == "apex":
                add_reference("invokes-apex", direct_text(element, "actionName"))
        # $Label tokens anywhere in the flow (error messages, text templates, formulas) are a
        # label dependency — the reverse index behind "what breaks if this label changes".
        raw_source = path.read_text(encoding="utf-8", errors="replace")
        for match in LABEL_TOKEN_RE.finditer(raw_source):
            add_reference("uses-label", match.group(1) or match.group(2))
        for permission in sorted(set(PERMISSION_TOKEN_RE.findall(raw_source))):
            add_reference("references-custom-permission", permission)
        trigger_type = direct_text(start, "triggerType")
        record_trigger_type = direct_text(start, "recordTriggerType")
        # Entry conditions and scheduling on the start element: why a record-triggered flow does
        # or does not fire, invisible before collector 1.3.0.
        entry_conditions = self._criteria_entries(start) if start is not root else []
        for entry in entry_conditions:
            add_reference(
                "filters-field",
                f"{object_name}.{entry['field']}" if object_name else entry["field"],
            )
        scheduled_paths = [
            compact(
                {
                    "name": direct_text(element, "name"),
                    "offsetNumber": direct_text(element, "offsetNumber"),
                    "offsetUnit": direct_text(element, "offsetUnit"),
                    "recordField": direct_text(element, "recordField"),
                    "timeSource": direct_text(element, "timeSource"),
                }
            )
            for element in start.iter()
            if local_name(element.tag) == "scheduledPaths"
        ]
        start_facts = compact(
            {
                "entryConditions": entry_conditions,
                "filterLogic": direct_text(start, "filterLogic"),
                "filterFormula": direct_text(start, "filterFormula"),
                "requiresRecordChanged": boolean(
                    direct_text(start, "doesRequireRecordChangedToMeetCriteria")
                ),
                "scheduledPaths": scheduled_paths,
            }
        )
        # Error catalog: declared error surfaces plus the decision paths that guard them, so a
        # user-pasted error message can be traced back to this Flow and its triggering scenario.
        error_catalog: list[dict[str, Any]] = []
        if self.error_surface_extraction:
            trigger_context = (
                " / ".join(
                    part for part in (object_name, record_trigger_type, trigger_type) if part
                )
                or None
            )
            error_catalog, error_references = self._flow_error_catalog(
                root, object_name, trigger_context
            )
            references.extend(error_references)
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
                ("customErrors", "customErrors"),
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
                "triggerType": trigger_type,
                "recordTriggerType": record_trigger_type,
                "start": start_facts or None,
                "referencedObjects": sorted(referenced_objects),
                "dataOperations": data_operations or None,
                "variables": variables or None,
                "formulas": formulas or None,
                "elementCounts": {key: value for key, value in element_counts.items() if value}
                or None,
                "errorCatalog": error_catalog or None,
            },
            references,
            name,
        )

    def parse_workflow(self, path: Path) -> dict[str, Any]:
        """One Workflow component per object file: rules, field updates, alerts, messages, tasks.

        The legacy workflow engine is live business logic — criteria fields explain why records
        change, fieldUpdates are the actual writes (cross-object via targetObject), alerts and
        outbound messages are notification/integration surfaces. Recipient email addresses and
        integration usernames are never captured; endpoints collapse to their hostname."""

        root = self.parse_xml(path)
        object_name = path.name.removesuffix(".workflow-meta.xml")
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        seen_references: set[tuple[str, str]] = {("operates-on", object_name)}

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        def qualified(field: str) -> str:
            return field if "." in field else f"{object_name}.{field}"

        def action_entries(element: ET.Element) -> list[dict[str, Any]]:
            entries = []
            for action in element.iter():
                if local_name(action.tag) != "actions":
                    continue
                entries.append(
                    compact(
                        {
                            "name": direct_text(action, "name"),
                            "type": direct_text(action, "type"),
                        }
                    )
                )
            return entries

        rules: list[dict[str, Any]] = []
        field_updates: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        outbound_messages: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        for element in list(root):
            tag = local_name(element.tag)
            name = direct_text(element, "fullName")
            if tag == "rules":
                criteria = self._criteria_entries(element)
                for entry in criteria:
                    add_reference("filters-field", qualified(entry["field"]))
                formula = direct_text(element, "formula")
                formula_fields: list[str] = []
                if formula:
                    for reference in self.formula_field_references(object_name, formula):
                        formula_fields.append(reference["target"])
                        add_reference("filters-field", reference["target"], heuristic=True)
                actions = action_entries(element)
                for action in actions:
                    if action.get("type") == "Alert" and action.get("name"):
                        add_reference("sends-alert", f"{object_name}.{action['name']}")
                time_triggers = [
                    compact(
                        {
                            "offset": direct_text(trigger, "timeLength"),
                            "unit": direct_text(trigger, "workflowTimeTriggerUnit"),
                            "offsetFromField": direct_text(trigger, "offsetFromField"),
                        }
                    )
                    for trigger in element.iter()
                    if local_name(trigger.tag) == "workflowTimeTriggers"
                ]
                rules.append(
                    compact(
                        {
                            "name": name,
                            "active": boolean(direct_text(element, "active")),
                            "triggerType": direct_text(element, "triggerType"),
                            "criteria": criteria,
                            "formulaFields": sorted(set(formula_fields)) or None,
                            "booleanFilter": direct_text(element, "booleanFilter"),
                            "timeTriggers": time_triggers,
                            "actions": actions,
                        }
                    )
                )
            elif tag == "fieldUpdates":
                field = direct_text(element, "field")
                target_object = direct_text(element, "targetObject")
                write_object = target_object or object_name
                if field:
                    add_reference(
                        "writes-field",
                        field if "." in field else f"{write_object}.{field}",
                    )
                formula = direct_text(element, "formula")
                if formula:
                    for reference in self.formula_field_references(object_name, formula):
                        add_reference("references-field", reference["target"], heuristic=True)
                field_updates.append(
                    compact(
                        {
                            "name": name,
                            "field": field,
                            "operation": direct_text(element, "operation"),
                            "targetObject": target_object,
                            "literalValue": sanitize_literal(
                                direct_text(element, "literalValue")
                            ),
                            "reevaluateOnChange": boolean(
                                direct_text(element, "reevaluateOnChange")
                            ),
                        }
                    )
                )
            elif tag == "alerts":
                template = direct_text(element, "template")
                add_reference("uses-template", template)
                recipient_types = sorted(
                    {
                        value
                        for recipient in element.iter()
                        if local_name(recipient.tag) == "recipients"
                        for value in [direct_text(recipient, "type")]
                        if value
                    }
                )
                alerts.append(
                    compact(
                        {
                            "name": name,
                            "template": template,
                            "recipientTypes": recipient_types,
                            "senderType": direct_text(element, "senderType"),
                        }
                    )
                )
            elif tag == "outboundMessages":
                endpoint = direct_text(element, "endpointUrl")
                fields = descendant_texts(element, "fields")
                for field in fields:
                    add_reference("reads-field", qualified(field))
                outbound_messages.append(
                    compact(
                        {
                            "name": name,
                            "endpointHost": urlsplit(endpoint).hostname if endpoint else None,
                            "fields": fields,
                            "includeSessionId": boolean(
                                direct_text(element, "includeSessionId")
                            ),
                        }
                    )
                )
            elif tag == "tasks":
                tasks.append(
                    compact(
                        {
                            "name": name,
                            "assignedToType": direct_text(element, "assignedToType"),
                            "subject": direct_text(element, "subject"),
                            "status": direct_text(element, "status"),
                            "priority": direct_text(element, "priority"),
                            "dueDateOffset": direct_text(element, "dueDateOffset"),
                        }
                    )
                )
        # Uniform bounds: true totals always stay in the *Count facts; the inlined arrays
        # are capped with per-array flags plus the aggregate factsTruncated.
        capped_arrays = {
            "rules": rules,
            "fieldUpdates": field_updates,
            "alerts": alerts,
            "outboundMessages": outbound_messages,
            "tasks": tasks,
        }
        array_flags = {
            f"{key}Truncated": True if len(value) > self.MAX_RULE_ENTRIES else None
            for key, value in capped_arrays.items()
        }
        facts_truncated = any(array_flags.values())
        references, truncation = self.cap_references(
            references,
            {
                "operates-on": 0,
                "writes-field": 1,
                "filters-field": 2,
                "sends-alert": 3,
                "uses-template": 4,
                "references-field": 5,
                "reads-field": 6,
            },
        )
        return self.component(
            "Workflow",
            object_name,
            path,
            {
                "object": object_name,
                **{
                    key: value[: self.MAX_RULE_ENTRIES] or None
                    for key, value in capped_arrays.items()
                },
                **array_flags,
                "ruleCount": len(rules) or None,
                "activeRuleCount": sum(1 for rule in rules if rule.get("active")) or None,
                "fieldUpdateCount": len(field_updates) or None,
                "alertCount": len(alerts) or None,
                "factsTruncated": True if facts_truncated else None,
                **truncation,
            },
            references,
            object_name,
        )

    def parse_apex(self, path: Path, metadata_type: str) -> dict[str, Any]:
        raw_source = path.read_text(encoding="utf-8", errors="replace")
        # Every token scan below runs over code lines only. Prose is not code: a comment
        # reading "selected from the ledger" made SOQL_FROM_RE report an object named `the`,
        # and "Base class for all trigger handlers" named a class `for`. Line-level filtering
        # keeps dynamic SOQL in string literals (Database.query('... FROM X')) intact, which
        # wholesale comment stripping would not.
        source = code_lines(raw_source)
        references: list[dict[str, Any]] = [
            {"kind": "object-token", "target": value}
            for value in sorted(set(CUSTOM_OBJECT_RE.findall(source)))
        ]
        trigger_object: str | None = None
        if metadata_type == "ApexTrigger":
            match = TRIGGER_RE.search(source)
            name = match.group(1) if match else path.stem
            facts: dict[str, Any] = {}
            if match:
                trigger_object = match.group(2)
                facts = {
                    "object": trigger_object,
                    "events": sorted(value.strip() for value in match.group(3).split(",")),
                }
                references.append({"kind": "belongs-to", "target": trigger_object})
                references.append({"kind": "operates-on", "target": trigger_object})
        else:
            match = CLASS_RE.search(source)
            name = match.group(2) if match else path.stem
            facts = {"declarationKind": match.group(1).lower() if match else "unknown"}
            # Header facts: sharing posture, inheritance, and the file-level annotation set.
            header_end = source.find("{", match.end()) if match else -1
            header = source[: header_end if header_end != -1 else len(source)]
            sharing = APEX_SHARING_RE.search(header)
            facts["sharingModel"] = sharing.group(1).lower() if sharing else "omitted"
            extends = APEX_EXTENDS_RE.search(header)
            if extends:
                facts["superclass"] = extends.group(1)
            implements = APEX_IMPLEMENTS_RE.search(source[: header_end + 1] if header_end != -1 else source)
            if implements:
                facts["interfaces"] = sorted(
                    {
                        re.sub(r"<.*", "", token.strip())
                        for token in implements.group(1).split(",")
                        if token.strip()
                    }
                )
            if APEX_TEST_RE.search(source):
                facts["isTest"] = True
        annotations = sorted(
            {
                value
                for line in source.splitlines()
                if not APEX_COMMENT_LINE_RE.match(line)
                for value in APEX_ANNOTATION_RE.findall(line)
            }
        )
        if annotations:
            facts["annotations"] = annotations
        # Companion meta (`X.cls-meta.xml`): the inventory loop skips it as a component, but its
        # apiVersion/status are the only source of "is this class deployed as Active".
        header_doc = APEXDOC_DESCRIPTION_RE.search(raw_source)
        if header_doc:
            documented = re.sub(r"\s*\n\s*\*\s*", " ", header_doc.group(1))
            documented = re.sub(r"\s+", " ", documented).strip()
            if documented:
                facts["description"] = documented
        meta_path = path.with_name(path.name + "-meta.xml")
        if meta_path.is_file():
            try:
                meta_root = self.parse_xml(meta_path)
            except (ET.ParseError, OSError):
                meta_root = None
            if meta_root is not None:
                facts["apiVersion"] = direct_text(meta_root, "apiVersion")
                facts["status"] = direct_text(meta_root, "status")
        # Usage registry (source-token heuristic): objects queried, DML verbs used, classes invoked.
        # queries-object is emitted structurally by parse_flow too, so the heuristic marker lives
        # on the reference itself here instead of on the kind. The FROM scan runs over the whole
        # source, so dynamic-SOQL string literals (Database.query('SELECT … FROM X')) are covered
        # by the same heuristic as inline queries.
        soql_objects = sorted(set(SOQL_FROM_RE.findall(source)))
        references.extend(
            {"kind": "queries-object", "target": value, "heuristic": True}
            for value in soql_objects
        )
        dml_operations = sorted({value.lower() for value in DML_RE.findall(source)})
        invoked = sorted(
            value
            for value in set(APEX_CALL_RE.findall(source)) | set(APEX_NEW_RE.findall(source))
            if value not in self.apex_system_types and value != name
        )
        references.extend({"kind": "invokes-class", "target": value} for value in invoked)
        known_objects = set(CUSTOM_OBJECT_RE.findall(source)) | set(soql_objects)
        if trigger_object:
            known_objects.add(trigger_object)
        declarations = self._apex_var_types(source, known_objects)
        # DML targets: `insert new Type(...)` resolves directly; `update variable` resolves via
        # the declaration map. Both are source-token heuristics (dml-object, per-ref flag).
        dml_targets: dict[str, set[str]] = {}
        for pattern in (APEX_DML_TARGET_RE, APEX_DATABASE_DML_RE):
            for verb, is_new, token in pattern.findall(source):
                target = (
                    token
                    if is_new and (token in known_objects or CUSTOM_OBJECT_RE.fullmatch(token))
                    else declarations.get(token)
                )
                if target:
                    dml_targets.setdefault(target, set()).add(verb.lower())
        references.extend(
            {"kind": "dml-object", "target": target, "heuristic": True}
            for target in sorted(dml_targets)
        )
        # Outbound callouts: named-credential literals are deterministic component links; raw
        # URL hosts are heuristic endpoints.
        for credential in sorted(set(APEX_CALLOUT_NC_RE.findall(source))):
            references.append({"kind": "uses-named-credential", "target": credential})
        for label in sorted(set(APEX_LABEL_RE.findall(source))):
            references.append({"kind": "uses-label", "target": label})
        callout_hosts = sorted(
            {
                host
                for url in APEX_ENDPOINT_URL_RE.findall(source)
                for host in [urlsplit(url).hostname]
                if host
            }
        )
        references.extend(
            {"kind": "callout-endpoint", "target": host} for host in callout_hosts
        )
        if self.soql_field_extraction:
            references.extend(self.soql_field_references(source))
        if self.local_variable_resolution:
            references.extend(self.variable_field_references(source, declarations))
        if soql_objects:
            facts["soqlObjects"] = soql_objects
        if dml_operations:
            facts["dmlOperations"] = dml_operations
        if dml_targets:
            facts["dmlTargets"] = {
                target: sorted(verbs) for target, verbs in sorted(dml_targets.items())
            }
        return self.component(metadata_type, name, path, facts, references, name)

    @staticmethod
    def soql_field_references(source: str) -> list[dict[str, str]]:
        """SELECT/WHERE field identifiers from inline SOQL, standard fields included.

        Heuristic (kind `soql-field`): subqueries and function calls are stripped, dotted
        relationship paths and bind variables are skipped, and the FROM object provides the
        `Object.Field` context that formula-token matching cannot.
        """

        targets: set[str] = set()
        for block in SOQL_BLOCK_RE.findall(source):
            flat = re.sub(r"\s+", " ", block)
            # Drop parenthesized segments (subqueries, function args) BEFORE locating FROM, so a
            # `(SELECT ... FROM Contacts)` subquery cannot claim the outer query's object slot.
            flat = re.sub(r"\([^)]*\)", " ", flat)
            from_match = SOQL_FROM_RE.search(flat)
            if not from_match:
                continue
            object_name = from_match.group(1)
            select_segment = flat[: from_match.start()]
            select_segment = re.sub(r"^\s*SELECT\s+", "", select_segment, flags=re.IGNORECASE)
            for token in select_segment.split(","):
                token = token.strip()
                if not SOQL_IDENTIFIER_RE.fullmatch(token) or token.upper() in SOQL_KEYWORDS:
                    continue
                targets.add(f"{object_name}.{token}")
            clause_segment = flat[from_match.end():]
            clause_fields = SOQL_COMPARISON_FIELD_RE.findall(clause_segment)
            clause_fields += SOQL_OPERATOR_FIELD_RE.findall(clause_segment)
            for field in clause_fields:
                if field.upper() in SOQL_KEYWORDS:
                    continue
                targets.add(f"{object_name}.{field}")
        return [{"kind": "soql-field", "target": target} for target in sorted(targets)]

    @staticmethod
    def _apex_var_types(source: str, known_objects: set[str]) -> dict[str, str]:
        """Locally declared sObject variables → their object type.

        A declaration's type counts as an object only when the same file already establishes it
        as one (custom-object token, SOQL FROM target, or the trigger's own object), so ordinary
        class instances are never misread as sObjects. Covers `Type name = …;` declarations and
        `for (Type name : …)` loop variables — the dominant shape in trigger code."""

        declarations: dict[str, str] = {}
        for pattern in (APEX_VAR_DECL_RE, APEX_LOOP_VAR_RE):
            for type_name, variable in pattern.findall(source):
                if type_name in known_objects:
                    declarations[variable] = type_name
        return declarations

    @staticmethod
    def variable_field_references(
        source: str, declarations: dict[str, str]
    ) -> list[dict[str, str]]:
        """Field accesses through locally declared sObject variables (kind `var-field-ref`).

        Method calls (`record.clone()`) are excluded.
        """

        targets: set[str] = set()
        for variable, type_name in declarations.items():
            member_re = re.compile(
                rf"\b{re.escape(variable)}\.([A-Za-z][A-Za-z0-9_]*)\b(?!\s*\()"
            )
            for field in member_re.findall(source):
                targets.add(f"{type_name}.{field}")
        return [{"kind": "var-field-ref", "target": target} for target in sorted(targets)]

    @staticmethod
    def _lwc_bundle_name(kebab: str) -> str:
        head, *rest = kebab.split("-")
        return head + "".join(part.capitalize() for part in rest)

    def parse_lwc(self, bundle: Path) -> dict[str, Any]:
        files = sorted(path for path in bundle.rglob("*") if path.is_file())
        meta = next((path for path in files if path.name.endswith(".js-meta.xml")), files[0])
        facts: dict[str, Any] = {}
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        if meta.name.endswith(".js-meta.xml"):
            root = self.parse_xml(meta)
            facts = {
                "isExposed": boolean(direct_text(root, "isExposed")),
                "targets": descendant_texts(root, "target"),
                "masterLabel": direct_text(root, "masterLabel"),
            }
            # targetConfigs declare which objects the component is exposed on — the strongest
            # placement edge a bundle carries, and plain XML to read.
            target_configs: list[dict[str, Any]] = []
            for config in (
                item for item in root.iter() if local_name(item.tag) == "targetConfig"
            ):
                objects = descendant_texts(config, "object")
                target_configs.append(
                    compact(
                        {
                            "targets": config.get("targets"),
                            "objects": objects or None,
                        }
                    )
                )
                for object_name in objects:
                    add_reference("operates-on", object_name)
            facts["targetConfigs"] = target_configs or None
        api_properties: set[str] = set()
        wired_adapters: set[str] = set()
        html_objects: set[str] = set()
        html_fields: set[str] = set()
        for path in files:
            if path.suffix == ".js":
                source = path.read_text(encoding="utf-8", errors="replace")
                for value in APEX_IMPORT_RE.findall(source):
                    add_reference("apex-method", value)
                for value in SCHEMA_IMPORT_RE.findall(source):
                    add_reference("schema", value)
                for value in LABEL_IMPORT_RE.findall(source):
                    add_reference("uses-label", value)
                api_properties.update(LWC_API_PROP_RE.findall(source))
                wired_adapters.update(LWC_WIRE_RE.findall(source))
                if self.markup_field_extraction:
                    for value in LWC_JS_FIELD_LITERAL_RE.findall(source):
                        add_reference("references-field", value, heuristic=True)
            elif path.suffix == ".html" and self.markup_field_extraction:
                markup = path.read_text(encoding="utf-8", errors="replace")
                html_objects.update(LWC_HTML_OBJECT_RE.findall(markup))
                html_fields.update(LWC_HTML_FIELD_RE.findall(markup))
                for value in LWC_EMBED_RE.findall(markup):
                    add_reference("embeds-component", self._lwc_bundle_name(value))
        for object_name in sorted(html_objects):
            add_reference("operates-on", object_name)
        # Field-name literals qualify against the markup's object only when it is unambiguous;
        # with several record forms on different objects the owner cannot be told from source.
        if len(html_objects) == 1:
            owner = next(iter(html_objects))
            for field in sorted(html_fields):
                add_reference(
                    "references-field",
                    field if "." in field else f"{owner}.{field}",
                    heuristic=True,
                )
        if api_properties:
            facts["apiProperties"] = sorted(api_properties)
        if wired_adapters:
            facts["wiredAdapters"] = sorted(wired_adapters)
        return self.component(
            "LightningComponentBundle", bundle.name, meta, facts, references, "<isExposed>"
        )

    @staticmethod
    def _markup_field_reference(
        token: str, default_object: str | None
    ) -> str | None:
        """`Object.Field` for a VF/Aura `{!X.Y}` binding token, None when unresolvable.

        The head must be the page's standard-controller object or a custom-object token —
        controller properties (`{!acct.Name}`) cannot be typed from markup alone."""

        parts = token.split(".")
        if len(parts) != 2:
            return None
        head, field = parts
        if head == default_object or CUSTOM_OBJECT_RE.fullmatch(head):
            return f"{head}.{field}"
        return None

    def parse_visualforce(self, path: Path, metadata_type: str) -> dict[str, Any]:
        """Visualforce page/component: controller wiring and field bindings from markup.

        Regex-based — VF markup is not reliably well-formed XML. inputField bindings are UI
        writes, outputField bindings are reads; both are per-reference heuristics."""

        source = path.read_text(encoding="utf-8", errors="replace")
        references: list[dict[str, Any]] = [
            {"kind": "object-token", "target": value}
            for value in sorted(set(CUSTOM_OBJECT_RE.findall(source)))
        ]
        seen_references: set[tuple[str, str]] = {
            (item["kind"], item["target"]) for item in references
        }

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        standard_controller = next(
            iter(VF_STANDARD_CONTROLLER_RE.findall(source)), None
        )
        # Every edge below is regex-derived from possibly-malformed markup (docstring), so
        # each carries the heuristic marker — stamping them source-exact laundered assurance.
        add_reference("operates-on", standard_controller, heuristic=True)
        controller = next(iter(AURA_CONTROLLER_RE.findall(source)), None)
        add_reference("apex-controller", controller, heuristic=True)
        extensions = [
            value.strip()
            for match in VF_EXTENSIONS_RE.findall(source)
            for value in match.split(",")
            if value.strip()
        ]
        for extension in extensions:
            add_reference("apex-controller", extension, heuristic=True)
        if self.markup_field_extraction:
            for pattern, kind in (
                (VF_INPUT_FIELD_RE, "writes-field"),
                (VF_OUTPUT_FIELD_RE, "reads-field"),
            ):
                for token in pattern.findall(source):
                    add_reference(
                        kind,
                        self._markup_field_reference(token, standard_controller),
                        heuristic=True,
                    )
        for label in sorted(set(MARKUP_LABEL_RE.findall(source))):
            add_reference("uses-label", label, heuristic=True)
        for embed in sorted(set(VF_EMBED_RE.findall(source))):
            add_reference("embeds-component", embed, heuristic=True)
        attribute_objects = sorted(
            {
                value
                for value in MARKUP_ATTRIBUTE_TYPE_RE.findall(source)
                for value in [re.sub(r"^List<\s*|\s*>$", "", value.strip())]
                if CUSTOM_OBJECT_RE.fullmatch(value)
            }
        )
        for value in attribute_objects:
            add_reference("operates-on", value, heuristic=True)
        facts: dict[str, Any] = {
            "standardController": standard_controller,
            "controller": controller,
            "extensions": extensions or None,
            "actionMethods": sorted(set(VF_ACTION_METHOD_RE.findall(source))) or None,
        }
        meta_path = path.with_name(path.name + "-meta.xml")
        if meta_path.is_file():
            try:
                meta_root = self.parse_xml(meta_path)
            except (ET.ParseError, OSError):
                meta_root = None
            if meta_root is not None:
                facts["label"] = direct_text(meta_root, "label")
                facts["apiVersion"] = direct_text(meta_root, "apiVersion")
        return self.component(
            metadata_type, path.stem, path, compact(facts), references, path.stem
        )

    def parse_aura(self, bundle: Path) -> dict[str, Any]:
        files = sorted(path for path in bundle.rglob("*") if path.is_file())
        primary = next((path for path in files if path.suffix == ".cmp"), files[0])
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        implements: set[str] = set()
        extends = None
        record_objects: set[str] = set()
        record_field_lists: list[tuple[str | None, str]] = []
        for path in files:
            source = path.read_text(encoding="utf-8", errors="replace")
            # All markup-derived edges are regex reads — carry the heuristic marker.
            for value in AURA_CONTROLLER_RE.findall(source):
                add_reference("apex-controller", value, heuristic=True)
            for label in MARKUP_LABEL_RE.findall(source):
                add_reference("uses-label", label, heuristic=True)
            if path.suffix not in {".cmp", ".app", ".evt", ".design"}:
                continue
            for match in AURA_IMPLEMENTS_RE.findall(source):
                implements.update(part.strip() for part in match.split(",") if part.strip())
            extends = extends or next(iter(AURA_EXTENDS_RE.findall(source)), None)
            for value in VF_EMBED_RE.findall(source):
                add_reference("embeds-component", value, heuristic=True)
            for value in MARKUP_ATTRIBUTE_TYPE_RE.findall(source):
                bare = re.sub(r"^List<\s*|\s*>$", "", value.strip())
                if CUSTOM_OBJECT_RE.fullmatch(bare):
                    add_reference("operates-on", bare, heuristic=True)
            if self.markup_field_extraction:
                objects = AURA_RECORD_OBJECT_RE.findall(source)
                record_objects.update(objects)
                owner = objects[0] if len(set(objects)) == 1 else None
                for fields in AURA_RECORD_FIELDS_RE.findall(source):
                    record_field_lists.append((owner, fields))
        for owner in sorted(record_objects):
            add_reference("operates-on", owner, heuristic=True)
        for owner, fields in record_field_lists:
            if not owner:
                continue
            for field in fields.split(","):
                field = field.strip()
                if field and "." not in field:
                    add_reference("references-field", f"{owner}.{field}", heuristic=True)
        return self.component(
            "AuraDefinitionBundle",
            bundle.name,
            primary,
            compact(
                {
                    "definitionTypes": sorted({path.suffix.lstrip(".") for path in files}),
                    "implements": sorted(implements) or None,
                    "extends": extends,
                }
            ),
            references,
            bundle.name,
        )

    # Record-field token inside FlexiPage visibility rules and field items.
    FLEXIPAGE_RECORD_FIELD_RE = re.compile(r"\{!Record\.([A-Za-z][A-Za-z0-9_]*)\}")
    # Component-instance property names that carry a Flow API name. Name-pattern detection —
    # the launches-flow kind stays kind-level heuristic.
    FLEXIPAGE_FLOW_PROPERTIES = frozenset({"flowName", "flowApiName"})

    def parse_flexipage(self, path: Path) -> dict[str, Any]:
        """Lightning page: what users actually see, and which components/flows it wires in.

        componentInstances name LWC/Aura/standard components; their properties carry flow API
        names; fieldInstances place record fields; visibility rules read record fields."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".flexipage-meta.xml")
        object_name = direct_text(root, "sobjectType")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        add_reference("operates-on", object_name)
        template = next(
            (item for item in list(root) if local_name(item.tag) == "template"), None
        )
        component_count = 0
        field_count = 0
        visibility_fields: set[str] = set()
        for instance in root.iter():
            tag = local_name(instance.tag)
            if tag == "componentInstance":
                component_count += 1
                component_name = direct_text(instance, "componentName")
                if component_name:
                    add_reference(
                        "displays-component",
                        component_name.removeprefix("c:"),
                    )
                for prop in instance.iter():
                    if local_name(prop.tag) != "componentInstanceProperties":
                        continue
                    if direct_text(prop, "name") in self.FLEXIPAGE_FLOW_PROPERTIES:
                        add_reference("launches-flow", direct_text(prop, "value"))
            elif tag == "fieldInstance":
                field_count += 1
                field_item = direct_text(instance, "fieldItem")
                if field_item and field_item.startswith("Record."):
                    field = field_item.removeprefix("Record.")
                    add_reference(
                        "places-field",
                        f"{object_name}.{field}" if object_name else field,
                    )
            elif tag == "criteria":
                left_value = direct_text(instance, "leftValue") or ""
                for field in self.FLEXIPAGE_RECORD_FIELD_RE.findall(left_value):
                    target = f"{object_name}.{field}" if object_name else field
                    visibility_fields.add(target)
                    add_reference("references-field", target)
        region_count = sum(
            1 for item in root.iter() if local_name(item.tag) == "flexiPageRegions"
        )
        references, truncation = self.cap_references(
            references,
            {
                "operates-on": 0,
                "launches-flow": 1,
                "displays-component": 2,
                "places-field": 3,
                "references-field": 4,
            },
        )
        return self.component(
            "FlexiPage",
            name,
            path,
            {
                "label": direct_text(root, "masterLabel"),
                "pageType": direct_text(root, "type"),
                "object": object_name,
                "template": direct_text(template, "name") if template is not None else None,
                "regionCount": region_count or None,
                "componentCount": component_count or None,
                "fieldInstanceCount": field_count or None,
                "visibilityRuleFields": sorted(visibility_fields) or None,
                **truncation,
            },
            references,
            name,
        )

    INTEGRATION_SUFFIXES = {
        "NamedCredential": ".namedCredential-meta.xml",
        "ExternalCredential": ".externalCredential-meta.xml",
        "RemoteSiteSetting": ".remoteSite-meta.xml",
        "ExternalDataSource": ".dataSource-meta.xml",
        "ExternalServiceRegistration": ".externalServiceRegistration-meta.xml",
        "ConnectedApp": ".connectedApp-meta.xml",
        "AuthProvider": ".authprovider-meta.xml",
        "CspTrustedSite": ".cspTrustedSite-meta.xml",
        "CorsWhitelistOrigin": ".corsWhitelistOrigin-meta.xml",
    }

    def parse_integration(self, path: Path, metadata_type: str) -> dict[str, Any]:
        """Integration surfaces: endpoints (host only), auth topology, pre-authorizations.

        Hard sanitization lines: never consumer keys, certificates, secrets, usernames,
        passwords, auth-parameter values, contact e-mails, or URL paths/queries."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(self.INTEGRATION_SUFFIXES[metadata_type])
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        def host_of(url: str | None) -> str | None:
            return urlsplit(url).hostname if url else None

        endpoint = (
            direct_text(root, "url")
            or direct_text(root, "endpoint")
            or direct_text(root, "endpointUrl")
            or direct_text(root, "urlPattern")
        )
        facts: dict[str, Any] = {
            "label": direct_text(root, "label") or direct_text(root, "masterLabel"),
        }
        if metadata_type == "NamedCredential":
            external_credential = None
            if endpoint is None:
                # New-style (SecuredEndpoint) named credentials carry the endpoint as a
                # namedCredentialParameters entry with parameterType=Url instead of <endpoint>.
                for parameter in root.iter():
                    if local_name(parameter.tag) != "namedCredentialParameters":
                        continue
                    parameter_type = direct_text(parameter, "parameterType")
                    if parameter_type == "Url" and endpoint is None:
                        endpoint = direct_text(parameter, "parameterValue")
                    external_credential = external_credential or direct_text(
                        parameter, "externalCredential"
                    )
            add_reference("uses-external-credential", external_credential)
            add_reference("references-auth-provider", direct_text(root, "authProvider"))
            facts.update(
                {
                    "namedCredentialType": direct_text(root, "namedCredentialType"),
                    "protocol": direct_text(root, "protocol"),
                    "principalType": direct_text(root, "principalType"),
                    "generateAuthorizationHeader": boolean(
                        direct_text(root, "generateAuthorizationHeader")
                    ),
                    "allowMergeFieldsInBody": boolean(
                        direct_text(root, "allowMergeFieldsInBody")
                    ),
                    "allowMergeFieldsInHeader": boolean(
                        direct_text(root, "allowMergeFieldsInHeader")
                    ),
                    "externalCredential": external_credential,
                }
            )
        elif metadata_type == "ExternalCredential":
            principals: list[dict[str, Any]] = []
            for parameter in root.iter():
                if local_name(parameter.tag) != "externalCredentialParameters":
                    continue
                parameter_type = direct_text(parameter, "parameterType")
                if parameter_type in {"NamedPrincipal", "PerUserPrincipal"}:
                    principals.append(
                        compact(
                            {
                                "name": direct_text(parameter, "parameterName"),
                                "type": parameter_type,
                                "sequence": direct_text(parameter, "sequenceNumber"),
                            }
                        )
                    )
                elif parameter_type == "AuthProvider":
                    add_reference(
                        "references-auth-provider",
                        direct_text(parameter, "authProvider")
                        or direct_text(parameter, "parameterValue"),
                    )
            facts.update(
                {
                    "authenticationProtocol": direct_text(root, "authenticationProtocol"),
                    "authenticationProtocolVariant": direct_text(
                        root, "authenticationProtocolVariant"
                    ),
                    "principals": principals or None,
                }
            )
        elif metadata_type == "RemoteSiteSetting":
            facts.update(
                {
                    "isActive": boolean(direct_text(root, "isActive")),
                    "disableProtocolSecurity": boolean(
                        direct_text(root, "disableProtocolSecurity")
                    ),
                }
            )
        elif metadata_type == "ExternalDataSource":
            add_reference("references-auth-provider", direct_text(root, "authProvider"))
            facts.update(
                {
                    "sourceType": direct_text(root, "type"),
                    "principalType": direct_text(root, "principalType"),
                    "protocol": direct_text(root, "protocol"),
                    "isWritable": boolean(direct_text(root, "isWritable")),
                }
            )
        elif metadata_type == "ExternalServiceRegistration":
            named_credential = direct_text(root, "namedCredential")
            add_reference("uses-named-credential", named_credential)
            facts.update(
                {
                    "registrationProviderType": direct_text(
                        root, "registrationProviderType"
                    ),
                    "namedCredential": named_credential,
                    "status": direct_text(root, "status"),
                    "schemaPresent": (
                        True
                        if direct_text(root, "schema")
                        or direct_text(root, "schemaUrl")
                        or direct_text(root, "schemaUploadFileName")
                        else None
                    ),
                }
            )
        elif metadata_type == "ConnectedApp":
            oauth = next(
                (item for item in list(root) if local_name(item.tag) == "oauthConfig"),
                None,
            )
            for profile in descendant_texts(root, "profileName"):
                add_reference("grants-to-profile", profile)
            for permission_set in descendant_texts(root, "permissionsetName"):
                add_reference("grants-to-permission-set", permission_set)
            canvas_url = next(
                (
                    direct_text(item, "canvasUrl")
                    for item in root.iter()
                    if local_name(item.tag) == "canvasConfig"
                ),
                None,
            )
            facts.update(
                {
                    "oauthScopes": (
                        descendant_texts(oauth, "scopes") if oauth is not None else []
                    )
                    or None,
                    "isAdminApproved": boolean(
                        direct_text(oauth, "isAdminApproved")
                        if oauth is not None
                        else None
                    ),
                    "ipRelaxation": direct_text(root, "ipRelaxation"),
                    "callbackHost": host_of(
                        direct_text(oauth, "callbackUrl") if oauth is not None else None
                    ),
                    "canvasHost": host_of(canvas_url),
                    "samlConfigPresent": (
                        True
                        if any(
                            local_name(item.tag) == "samlConfig" for item in root.iter()
                        )
                        else None
                    ),
                }
            )
        elif metadata_type == "AuthProvider":
            # Registration handlers create users — security-critical code worth an edge.
            add_reference("invokes-class", direct_text(root, "registrationHandler"))
            add_reference("invokes-class", direct_text(root, "plugin"))
            facts.update(
                {
                    "label": direct_text(root, "friendlyName") or facts["label"],
                    "providerType": direct_text(root, "providerType"),
                    "authorizeHost": host_of(direct_text(root, "authorizeUrl")),
                    "tokenHost": host_of(direct_text(root, "tokenUrl")),
                    "executionUserPresent": (
                        True if direct_text(root, "executionUser") else None
                    ),
                }
            )
        elif metadata_type == "CspTrustedSite":
            facts.update(
                {
                    "isActive": boolean(direct_text(root, "isActive")),
                    "context": direct_text(root, "context"),
                    "directives": sorted(
                        local_name(element.tag).removeprefix("isApplicableTo")
                        for element in root.iter()
                        if local_name(element.tag).startswith("isApplicableTo")
                        and boolean(element.text)
                    )
                    or None,
                }
            )
        facts["endpointHost"] = host_of(endpoint)
        return self.component(
            metadata_type,
            name,
            path,
            facts,
            references,
            needle=facts["endpointHost"] or name,
        )

    def parse_platform_event_channel(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".platformEventChannel-meta.xml")
        return self.component(
            "PlatformEventChannel",
            name,
            path,
            {
                "label": direct_text(root, "channelLabel") or direct_text(root, "label"),
                "channelType": direct_text(root, "channelType"),
            },
            needle=name,
        )

    def parse_platform_event_channel_member(self, path: Path) -> dict[str, Any]:
        """Channel member: which event/CDC entity streams through which channel."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".platformEventChannelMember-meta.xml")
        entity = direct_text(root, "selectedEntity")
        channel = direct_text(root, "eventChannel")
        enriched = descendant_texts(root, "name")
        references: list[dict[str, Any]] = []
        if entity:
            references.append({"kind": "operates-on", "target": entity})
            if entity.endswith("ChangeEvent"):
                # CDC entity → base object: name-derived, so the edge carries the flag.
                references.append(
                    {
                        "kind": "operates-on",
                        "target": entity.removesuffix("ChangeEvent"),
                        "heuristic": True,
                    }
                )
            references.extend(
                {"kind": "references-field", "target": f"{entity}.{field}"}
                for field in enriched
            )
        if channel:
            references.append({"kind": "relationship", "target": channel})
        return self.component(
            "PlatformEventChannelMember",
            name,
            path,
            {
                "eventChannel": channel,
                "selectedEntity": entity,
                "enrichedFields": enriched or None,
            },
            references,
            name,
        )

    def parse_approval_process(self, path: Path) -> dict[str, Any]:
        """Approval process with criteria, approver routing, and workflow-action wiring.

        The action sets reference the owning object's Workflow fieldUpdates/alerts by name —
        "final approval writes Object.Field" lives across two files, and the
        `uses-workflow-action`/`sends-alert` edges close that chain. User approver names are
        never captured (usernames); related-user-field approvers are a field read."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".approvalProcess-meta.xml")
        object_name = name.split(".", 1)[0] if "." in name else None
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        def qualified(field: str) -> str:
            if "." in field or not object_name:
                return field
            return f"{object_name}.{field}"

        def direct_child(element: ET.Element, tag: str) -> ET.Element | None:
            return next(
                (item for item in list(element) if local_name(item.tag) == tag), None
            )

        add_reference("operates-on", object_name)

        def criteria_block(element: ET.Element | None) -> dict[str, Any] | None:
            if element is None:
                return None
            criteria = self._criteria_entries(element)
            for entry in criteria:
                add_reference("filters-field", qualified(entry["field"]))
            formula = direct_text(element, "formula")
            formula_fields: list[str] = []
            if formula and object_name:
                for reference in self.formula_field_references(object_name, formula):
                    formula_fields.append(reference["target"])
                    add_reference("filters-field", reference["target"], heuristic=True)
            return compact(
                {
                    "criteria": criteria,
                    "formulaFields": sorted(set(formula_fields)) or None,
                    "booleanFilter": direct_text(element, "booleanFilter"),
                }
            ) or None

        def action_entries(element: ET.Element | None) -> list[dict[str, Any]]:
            if element is None:
                return []
            actions = []
            for action in element.iter():
                if local_name(action.tag) != "action":
                    continue
                action_name = direct_text(action, "name")
                action_type = direct_text(action, "type")
                actions.append(compact({"name": action_name, "type": action_type}))
                if action_name and object_name:
                    if action_type == "Alert":
                        add_reference("sends-alert", f"{object_name}.{action_name}")
                    elif action_type in {"FieldUpdate", "Task", "OutboundMessage"}:
                        add_reference(
                            "uses-workflow-action", f"{object_name}.{action_name}"
                        )
            return actions

        entry_criteria = criteria_block(direct_child(root, "entryCriteria"))
        steps: list[dict[str, Any]] = []
        for order, step in enumerate(
            (item for item in root.iter() if local_name(item.tag) == "approvalStep"), 1
        ):
            approvers: list[dict[str, Any]] = []
            when_multiple = None
            assigned = direct_child(step, "assignedApprover")
            if assigned is not None:
                when_multiple = direct_text(assigned, "whenMultipleApprovers")
                for approver in assigned.iter():
                    if local_name(approver.tag) != "approver":
                        continue
                    approver_type = direct_text(approver, "type")
                    approver_name = direct_text(approver, "name")
                    if approver_type == "relatedUserField" and approver_name:
                        add_reference("references-field", qualified(approver_name))
                        approvers.append(
                            {"type": approver_type, "field": approver_name}
                        )
                    elif approver_type == "queue" and approver_name:
                        approvers.append({"type": approver_type, "name": approver_name})
                    else:
                        # User approvers: type only — usernames are never captured.
                        approvers.append(compact({"type": approver_type}))
            reject = direct_child(step, "rejectBehavior")
            steps.append(
                compact(
                    {
                        "order": order,
                        "name": direct_text(step, "name"),
                        "label": direct_text(step, "label"),
                        "entryCriteria": criteria_block(
                            direct_child(step, "entryCriteria")
                        ),
                        "approvers": approvers or None,
                        "whenMultipleApprovers": when_multiple,
                        "rejectBehavior": (
                            direct_text(reject, "type") if reject is not None else None
                        ),
                        "approvalActions": action_entries(
                            direct_child(step, "approvalActions")
                        )
                        or None,
                        "rejectionActions": action_entries(
                            direct_child(step, "rejectionActions")
                        )
                        or None,
                    }
                )
            )
        action_sets = compact(
            {
                "initialSubmission": action_entries(
                    direct_child(root, "initialSubmissionActions")
                )
                or None,
                "finalApproval": action_entries(direct_child(root, "finalApprovalActions"))
                or None,
                "finalRejection": action_entries(
                    direct_child(root, "finalRejectionActions")
                )
                or None,
                "recall": action_entries(direct_child(root, "recallActions")) or None,
            }
        )
        page_fields_element = direct_child(root, "approvalPageFields")
        approval_page_fields = (
            descendant_texts(page_fields_element, "field")
            if page_fields_element is not None
            else []
        )
        for field in approval_page_fields:
            add_reference("references-field", qualified(field))
        email_template = direct_text(root, "emailTemplate")
        add_reference("uses-template", email_template)
        submitter_types = sorted(
            {
                value
                for element in root.iter()
                if local_name(element.tag) == "allowedSubmitters"
                for value in [direct_text(element, "type")]
                if value
            }
        )
        references, approval_truncation = self.cap_references(
            references,
            {
                "operates-on": 0,
                "sends-alert": 1,
                "uses-workflow-action": 2,
                "uses-template": 3,
                "filters-field": 4,
                "references-field": 5,
            },
        )
        return self.component(
            "ApprovalProcess",
            name,
            path,
            {
                "object": object_name,
                "label": direct_text(root, "label"),
                "active": boolean(direct_text(root, "active")),
                "recordEditability": direct_text(root, "recordEditability"),
                "allowRecall": boolean(direct_text(root, "allowRecall")),
                "finalApprovalRecordLock": boolean(
                    direct_text(root, "finalApprovalRecordLock")
                ),
                "finalRejectionRecordLock": boolean(
                    direct_text(root, "finalRejectionRecordLock")
                ),
                "entryCriteria": entry_criteria,
                "steps": steps[: self.MAX_RULES] or None,
                "stepsTruncated": True if len(steps) > self.MAX_RULES else None,
                "factsTruncated": True if len(steps) > self.MAX_RULES else None,
                "actionSets": action_sets or None,
                "approvalPageFields": approval_page_fields or None,
                "emailTemplate": email_template,
                "allowedSubmitterTypes": submitter_types or None,
                "stepCount": len(steps),
                "entryCriteriaPresent": any(
                    local_name(item.tag) == "entryCriteria" for item in root.iter()
                ),
                **approval_truncation,
            },
            references,
            name,
        )

    # Standard lifecycle picklists behind BusinessProcess files, per object. The order of a
    # process's values IS the pipeline; the value set carries the closed/won/converted semantics.
    BUSINESS_PROCESS_FIELDS = {
        "Opportunity": ("StageName", "OpportunityStage"),
        "Case": ("Status", "CaseStatus"),
        "Lead": ("Status", "LeadStatus"),
        "Solution": ("Status", "SolutionStatus"),
    }

    def parse_record_type(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".recordType-meta.xml"
        )
        references: list[dict[str, Any]] = [
            {"kind": "belongs-to", "target": object_name},
            {"kind": "operates-on", "target": object_name},
        ]
        business_process = direct_text(root, "businessProcess")
        if business_process:
            references.append(
                {
                    "kind": "uses-business-process",
                    "target": f"{object_name}.{business_process}",
                }
            )
        picklist_scopes: list[dict[str, Any]] = []
        for block in (
            item for item in root.iter() if local_name(item.tag) == "picklistValues"
        ):
            picklist = direct_text(block, "picklist")
            if not picklist:
                continue
            references.append(
                {"kind": "references-field", "target": f"{object_name}.{picklist}"}
            )
            values = [
                value
                for item in block.iter()
                if local_name(item.tag) == "values"
                for value in [direct_text(item, "fullName")]
                if value
            ]
            defaults = [
                value
                for item in block.iter()
                if local_name(item.tag) == "values"
                and boolean(direct_text(item, "default"))
                for value in [direct_text(item, "fullName")]
                if value
            ]
            picklist_scopes.append(
                compact(
                    {
                        "picklist": picklist,
                        "valueCount": len(values),
                        "defaults": defaults or None,
                    }
                )
            )
        return self.component(
            "RecordType",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "label": direct_text(root, "label"),
                "description": direct_text(root, "description"),
                "active": boolean(direct_text(root, "active")),
                "businessProcess": business_process,
                "picklistScopes": picklist_scopes or None,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    def parse_value_set(self, path: Path, metadata_type: str) -> dict[str, Any]:
        """GlobalValueSet / StandardValueSet: the org's controlled vocabularies.

        Standard sets carry lifecycle semantics — which OpportunityStage values are closed/won,
        which LeadStatus converts — answering "what counts as a won deal here" from source."""

        root = self.parse_xml(path)
        suffix = (
            ".globalValueSet-meta.xml"
            if metadata_type == "GlobalValueSet"
            else ".standardValueSet-meta.xml"
        )
        name = path.name.removesuffix(suffix)
        values: list[dict[str, Any]] = []
        value_count = 0
        for element in root.iter():
            if local_name(element.tag) not in {"customValue", "standardValue"}:
                continue
            value_count += 1
            if len(values) < PICKLIST_VALUE_CAP:
                values.append(
                    compact(
                        {
                            "fullName": direct_text(element, "fullName"),
                            "label": direct_text(element, "label"),
                            "default": boolean(direct_text(element, "default")),
                            "isActive": boolean(direct_text(element, "isActive")),
                            "closed": boolean(direct_text(element, "closed")),
                            "won": boolean(direct_text(element, "won")),
                            "converted": boolean(direct_text(element, "converted")),
                            "probability": direct_text(element, "probability"),
                            "forecastCategory": direct_text(element, "forecastCategory"),
                        }
                    )
                )
        return self.component(
            metadata_type,
            name,
            path,
            {
                "masterLabel": direct_text(root, "masterLabel"),
                "description": direct_text(root, "description"),
                "sorted": boolean(direct_text(root, "sorted")),
                "values": values or None,
                "valueCount": value_count or None,
                "valuesTruncated": True if value_count > len(values) else None,
            },
            needle=name,
        )

    def parse_business_process(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".businessProcess-meta.xml"
        )
        # Document order is the pipeline order — do not sort.
        values = [
            compact(
                {
                    "fullName": direct_text(item, "fullName"),
                    "default": boolean(direct_text(item, "default")),
                }
            )
            for item in root.iter()
            if local_name(item.tag) == "values"
        ]
        lifecycle_field, standard_value_set = self.BUSINESS_PROCESS_FIELDS.get(
            object_name, (None, None)
        )
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        if lifecycle_field:
            references.append(
                {
                    "kind": "references-field",
                    "target": f"{object_name}.{lifecycle_field}",
                }
            )
        if standard_value_set:
            references.append({"kind": "uses-value-set", "target": standard_value_set})
        return self.component(
            "BusinessProcess",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "description": direct_text(root, "description"),
                "isActive": boolean(direct_text(root, "isActive")),
                "values": values or None,
                "lifecycleField": lifecycle_field,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    def parse_duplicate_rule(self, path: Path) -> dict[str, Any]:
        """Duplicate rule: block/alert behavior, matching-rule link, and the alert text.

        `alertText` is a user-facing warning users paste verbatim — it joins facts.errorCatalog
        (kind `duplicate-alert`) so the BM25 error-trace pipeline resolves it like validation-rule
        and Flow messages."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".duplicateRule-meta.xml")
        object_name = name.split(".", 1)[0] if "." in name else None
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        add_reference("operates-on", object_name)
        match_rules: list[dict[str, Any]] = []
        for block in (
            item
            for item in root.iter()
            if local_name(item.tag) == "duplicateRuleMatchRules"
        ):
            matching_rule = direct_text(block, "matchingRule")
            matching_object = direct_text(block, "matchingRuleObjectType")
            if matching_rule:
                target = (
                    f"{matching_object}.{matching_rule}"
                    if matching_object and "." not in matching_rule
                    else matching_rule
                )
                add_reference("uses-matching-rule", target)
            mapped: list[dict[str, str]] = []
            for mapping in (
                item for item in block.iter() if local_name(item.tag) == "mappingFields"
            ):
                input_field = direct_text(mapping, "inputField")
                output_field = direct_text(mapping, "outputField")
                entry = compact({"input": input_field, "output": output_field})
                if entry:
                    mapped.append(entry)
                if input_field and object_name:
                    add_reference(
                        "references-field",
                        input_field
                        if "." in input_field
                        else f"{object_name}.{input_field}",
                    )
                if output_field and matching_object:
                    add_reference(
                        "references-field",
                        output_field
                        if "." in output_field
                        else f"{matching_object}.{output_field}",
                    )
            match_rules.append(
                compact(
                    {
                        "matchingRule": matching_rule,
                        "matchingRuleObjectType": matching_object,
                        "mappedFields": mapped or None,
                    }
                )
            )
        for entry in self._criteria_entries(root):
            add_reference(
                "filters-field",
                entry["field"]
                if "." in entry["field"]
                else (f"{object_name}.{entry['field']}" if object_name else entry["field"]),
            )
        alert_text = direct_text(root, "alertText")
        error_catalog: list[dict[str, Any]] = []
        if self.error_surface_extraction and alert_text:
            error_catalog.append(
                compact(
                    {
                        "component": name,
                        "kind": "duplicate-alert",
                        "errorMessage": alert_text,
                        "resolvedErrorMessage": self.resolved_error_message(alert_text),
                    }
                )
            )
        return self.component(
            "DuplicateRule",
            name,
            path,
            {
                "object": object_name,
                "label": direct_text(root, "masterLabel"),
                "active": boolean(direct_text(root, "isActive")),
                "sortOrder": direct_text(root, "sortOrder"),
                "actionOnInsert": direct_text(root, "actionOnInsert"),
                "actionOnUpdate": direct_text(root, "actionOnUpdate"),
                "securityOption": direct_text(root, "securityOption"),
                "operationsOnInsert": descendant_texts(root, "operationsOnInsert") or None,
                "operationsOnUpdate": descendant_texts(root, "operationsOnUpdate") or None,
                "matchRules": match_rules or None,
                "errorCatalog": error_catalog or None,
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
        references: list[dict[str, Any]] = []
        if object_name:
            # Inside the guard: a validation rule is the one owned type whose owner may
            # legitimately be absent (object_from_path raises and is caught above).
            references.append({"kind": "belongs-to", "target": object_name})
            references.append({"kind": "operates-on", "target": object_name})
            # Cross-object chains resolve through repo lookups; bare tokens attribute to the
            # owning object only after matched chains are removed (no more misattributing
            # `Status__c` inside `ParentObject__r.Status__c` to the rule's own object).
            references.extend(self.formula_field_references(object_name, formula))
        error_message = direct_text(root, "errorMessage")
        for match in LABEL_TOKEN_RE.finditer(f"{formula} {error_message or ''}"):
            label = match.group(1) or match.group(2)
            reference = {"kind": "uses-label", "target": label}
            if label and reference not in references:
                references.append(reference)
        for permission in sorted(set(PERMISSION_TOKEN_RE.findall(formula))):
            references.append(
                {"kind": "references-custom-permission", "target": permission}
            )
        error_catalog: list[dict[str, Any]] | None = None
        if self.error_surface_extraction and error_message:
            catalog_entry: dict[str, Any] = {
                "component": rule,
                "kind": "validation-rule",
                "errorMessage": error_message,
                "fieldSelection": direct_text(root, "errorDisplayField"),
                "condition": formula or None,
            }
            resolved = self.resolved_error_message(error_message)
            if resolved:
                catalog_entry["resolvedErrorMessage"] = resolved
            error_catalog = [compact(catalog_entry)]
        return self.component(
            "ValidationRule",
            name,
            path,
            {
                "object": object_name,
                "active": boolean(direct_text(root, "active")),
                "errorDisplayField": direct_text(root, "errorDisplayField"),
                "errorMessagePresent": error_message is not None,
                "errorCatalog": error_catalog,
            },
            references,
            rule,
        )

    def _parse_access_bundle(
        self, root: ET.Element
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Grant families shared by PermissionSet, Profile, and MutingPermissionSet.

        Field grants carry their level: `grants-field-edit` when editable (edit implies read),
        else `grants-field-read` — one edge per field, same edge count as the legacy
        level-blind `grants-field-permission` (kept declared for historical claims, no longer
        emitted). Object CRUD is a compact facts map plus rare high-signal view-all/modify-all
        edges. Emission is priority-ordered before the maxUsageRefs cap so system permissions
        and object grants survive truncation; fieldPermissions are cut first, with the dropped
        families named in facts.truncatedFamilies."""

        object_access: dict[str, str] = {}
        system_permissions: list[str] = []
        counts: dict[str, int] = {}
        # (priority, kind, target); lower priority survives the cap longer.
        prioritized: list[tuple[int, str, str]] = []
        for element in root.iter():
            tag = local_name(element.tag)
            if tag == "userPermissions":
                counts["userPermissions"] = counts.get("userPermissions", 0) + 1
                permission = direct_text(element, "name")
                if permission and boolean(direct_text(element, "enabled")):
                    system_permissions.append(permission)
                    prioritized.append((0, "grants-user-permission", permission))
            elif tag == "objectPermissions":
                counts["objectPermissions"] = counts.get("objectPermissions", 0) + 1
                target = direct_text(element, "object")
                if not target:
                    continue
                letters = "".join(
                    letter
                    for letter, flag in (
                        ("C", "allowCreate"),
                        ("R", "allowRead"),
                        ("E", "allowEdit"),
                        ("D", "allowDelete"),
                    )
                    if boolean(direct_text(element, flag))
                )
                if boolean(direct_text(element, "viewAllRecords")):
                    letters += "+VA"
                    prioritized.append((1, "grants-object-view-all", target))
                if boolean(direct_text(element, "modifyAllRecords")):
                    letters += "+MA"
                    prioritized.append((1, "grants-object-modify-all", target))
                object_access[target] = letters
                prioritized.append((1, "grants-object-permission", target))
            elif tag == "classAccesses":
                counts["classAccesses"] = counts.get("classAccesses", 0) + 1
                target = direct_text(element, "apexClass")
                if target and boolean(direct_text(element, "enabled")):
                    prioritized.append((2, "grants-class-access", target))
            elif tag == "customPermissions":
                counts["customPermissions"] = counts.get("customPermissions", 0) + 1
                target = direct_text(element, "name")
                if target and boolean(direct_text(element, "enabled")):
                    prioritized.append((3, "grants-custom-permission", target))
            elif tag == "recordTypeVisibilities":
                counts["recordTypeVisibilities"] = (
                    counts.get("recordTypeVisibilities", 0) + 1
                )
                target = direct_text(element, "recordType")
                if target and boolean(direct_text(element, "visible")):
                    prioritized.append((4, "grants-record-type", target))
            elif tag == "flowAccesses":
                counts["flowAccesses"] = counts.get("flowAccesses", 0) + 1
                target = direct_text(element, "flow")
                if target and boolean(direct_text(element, "enabled")):
                    prioritized.append((5, "grants-flow-access", target))
            elif tag == "fieldPermissions":
                counts["fieldPermissions"] = counts.get("fieldPermissions", 0) + 1
                target = direct_text(element, "field")
                if not target:
                    continue
                if boolean(direct_text(element, "editable")):
                    prioritized.append((6, "grants-field-edit", target))
                elif boolean(direct_text(element, "readable")):
                    prioritized.append((6, "grants-field-read", target))
            elif tag in {"pageAccesses", "tabSettings", "tabVisibilities", "applicationVisibilities"}:
                counts[tag] = counts.get(tag, 0) + 1
        prioritized.sort()
        truncated_families = sorted(
            {kind for _, kind, _ in prioritized[self.max_usage_refs :]}
        )
        references = [
            {"kind": kind, "target": target}
            for _, kind, target in prioritized[: self.max_usage_refs]
        ]
        facts = compact(
            {
                "objectAccess": object_access or None,
                "systemPermissions": sorted(system_permissions) or None,
                "objectPermissionCount": counts.get("objectPermissions"),
                "fieldPermissionCount": counts.get("fieldPermissions"),
                "classAccessCount": counts.get("classAccesses"),
                "customPermissionCount": counts.get("customPermissions"),
                "recordTypeCount": counts.get("recordTypeVisibilities"),
                "flowAccessCount": counts.get("flowAccesses"),
                "userPermissionCount": counts.get("userPermissions"),
                "tabCount": counts.get("tabSettings") or counts.get("tabVisibilities"),
                "pageAccessCount": counts.get("pageAccesses"),
                "applicationVisibilityCount": counts.get("applicationVisibilities"),
                "referencesTruncated": True if truncated_families else None,
                "truncatedFamilies": truncated_families or None,
            }
        )
        return facts, references

    def parse_permission_set(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".permissionset-meta.xml")
        facts, references = self._parse_access_bundle(root)
        facts = {
            "label": direct_text(root, "label"),
            "description": direct_text(root, "description"),
            "license": direct_text(root, "license"),
            "hasActivationRequired": boolean(direct_text(root, "hasActivationRequired")),
            **facts,
        }
        # Counts default to 0 for the two families every permission set historically reported.
        facts.setdefault("objectPermissionCount", 0)
        facts.setdefault("fieldPermissionCount", 0)
        return self.component("PermissionSet", name, path, compact(facts), references, name)

    def parse_profile(self, path: Path) -> dict[str, Any]:
        """Profile: the same grant families as PermissionSet plus UI shape and posture.

        Layout assignments answer "which layout does this profile see per record type";
        login IP ranges and hours are captured as presence + count only — never the values."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".profile-meta.xml")
        facts, references = self._parse_access_bundle(root)
        layout_count = 0
        layout_targets: list[str] = []
        seen_layouts: set[str] = set()
        for element in root.iter():
            if local_name(element.tag) != "layoutAssignments":
                continue
            layout_count += 1
            layout = direct_text(element, "layout")
            if layout and layout not in seen_layouts:
                seen_layouts.add(layout)
                layout_targets.append(layout)
        # Layout assignment is the question Profile components exist to answer, so those
        # edges rank first; a re-cap over the combined list must disclose what it drops —
        # the previous silent `len(references) < max_usage_refs` guard did not.
        references.extend(
            {"kind": "assigns-layout", "target": target} for target in layout_targets
        )
        references, truncation = self.cap_references(references, {"assigns-layout": 0})
        if truncation:
            facts["referencesTruncated"] = True
            facts["truncatedFamilies"] = sorted(
                set(facts.get("truncatedFamilies") or [])
                | set(truncation["truncatedFamilies"])
            )
        default_record_types = {}
        for element in root.iter():
            if local_name(element.tag) != "recordTypeVisibilities":
                continue
            record_type = direct_text(element, "recordType")
            if record_type and boolean(direct_text(element, "default")) and "." in record_type:
                default_record_types[record_type.split(".", 1)[0]] = record_type
        default_application = next(
            (
                direct_text(element, "application")
                for element in root.iter()
                if local_name(element.tag) == "applicationVisibilities"
                and boolean(direct_text(element, "default"))
            ),
            None,
        )
        ip_range_count = sum(
            1 for element in root.iter() if local_name(element.tag) == "loginIpRanges"
        )
        login_hours_present = any(
            local_name(element.tag) == "loginHours" for element in root.iter()
        )
        facts = {
            "label": direct_text(root, "label") or name,
            "custom": boolean(direct_text(root, "custom")),
            "userLicense": direct_text(root, "userLicense"),
            **facts,
            "layoutAssignmentCount": layout_count or None,
            "defaultRecordTypes": default_record_types or None,
            "defaultApplication": default_application,
            "loginIpRangesPresent": True if ip_range_count else None,
            "loginIpRangeCount": ip_range_count or None,
            "loginHoursPresent": True if login_hours_present else None,
        }
        return self.component("Profile", name, path, compact(facts), references, name)

    # Bound on recorded list-view columns; the count is always kept.
    LIST_VIEW_COLUMN_CAP = 50

    def parse_list_view(self, path: Path) -> dict[str, Any]:
        """List view: the working sets users operate from — columns and filter criteria."""

        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".listView-meta.xml"
        )
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        seen_references: set[tuple[str, str]] = {("operates-on", object_name)}

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        def qualified(field: str) -> str:
            return field if "." in field else f"{object_name}.{field}"

        columns = [
            element.text.strip()
            for element in root.iter()
            if local_name(element.tag) == "columns"
            and element.text
            and element.text.strip()
        ]
        for column in columns:
            add_reference("references-field", qualified(column))
        filters = self._criteria_entries(root)
        for entry in filters:
            add_reference("filters-field", qualified(entry["field"]))
        return self.component(
            "ListView",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "label": direct_text(root, "label"),
                "filterScope": direct_text(root, "filterScope"),
                "queue": direct_text(root, "queue"),
                "booleanFilter": direct_text(root, "booleanFilter"),
                "columns": columns[: self.LIST_VIEW_COLUMN_CAP] or None,
                "columnCount": len(columns) or None,
                "columnsTruncated": True
                if len(columns) > self.LIST_VIEW_COLUMN_CAP
                else None,
                "factsTruncated": True
                if len(columns) > self.LIST_VIEW_COLUMN_CAP
                else None,
                "filters": filters or None,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    def parse_field_set(self, path: Path) -> dict[str, Any]:
        """Field set: a dynamic UI contract — VF/LWC iterate these fields without a layout."""

        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".fieldSet-meta.xml"
        )
        displayed = [
            field
            for element in root.iter()
            if local_name(element.tag) == "displayedFields"
            for field in [direct_text(element, "field")]
            if field
        ]
        available = [
            field
            for element in root.iter()
            if local_name(element.tag) == "availableFields"
            for field in [direct_text(element, "field")]
            if field
        ]
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        references.extend(
            {"kind": "places-field", "target": f"{object_name}.{field}"}
            for field in sorted(set(displayed))
        )
        references.extend(
            {"kind": "references-field", "target": f"{object_name}.{field}"}
            for field in sorted(set(available) - set(displayed))
        )
        return self.component(
            "FieldSet",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "label": direct_text(root, "label"),
                "description": direct_text(root, "description"),
                "displayedFields": displayed or None,
                "availableFields": available or None,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    # sharedTo grantee element tags whose text names an org principal.
    SHARING_GRANTEE_TAGS = frozenset(
        {
            "group",
            "role",
            "roleAndSubordinates",
            "roleAndSubordinatesInternal",
            "queue",
            "portalRole",
            "portalRoleAndSubordinates",
            "allInternalUsers",
            "allCustomerPortalUsers",
            "allPartnerUsers",
            "guestUser",
        }
    )

    def parse_sharing_rules(self, path: Path) -> dict[str, Any]:
        """Sharing rules: which field values open records to which groups/roles/queues."""

        root = self.parse_xml(path)
        object_name = path.name.removesuffix(".sharingRules-meta.xml")
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        seen_references: set[tuple[str, str]] = {("operates-on", object_name)}

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        def grantees(element: ET.Element) -> list[dict[str, str]]:
            entries: list[dict[str, str]] = []
            for shared_to in element.iter():
                if local_name(shared_to.tag) != "sharedTo" and local_name(
                    shared_to.tag
                ) not in {"sharedFrom"}:
                    continue
                direction = local_name(shared_to.tag)
                for grantee in list(shared_to):
                    tag = local_name(grantee.tag)
                    if tag not in self.SHARING_GRANTEE_TAGS:
                        continue
                    value = grantee.text.strip() if grantee.text else None
                    entries.append(compact({"direction": direction, "type": tag, "name": value}))
                    if direction == "sharedTo":
                        add_reference("shares-with", f"{tag}:{value}" if value else tag)
            return entries

        criteria_rules: list[dict[str, Any]] = []
        owner_rules: list[dict[str, Any]] = []
        for element in root.iter():
            tag = local_name(element.tag)
            if tag == "sharingCriteriaRules":
                criteria = self._criteria_entries(element)
                for entry in criteria:
                    add_reference(
                        "filters-field",
                        entry["field"]
                        if "." in entry["field"]
                        else f"{object_name}.{entry['field']}",
                    )
                criteria_rules.append(
                    compact(
                        {
                            "name": direct_text(element, "fullName"),
                            "label": direct_text(element, "label"),
                            "accessLevel": direct_text(element, "accessLevel"),
                            "criteria": criteria,
                            "booleanFilter": direct_text(element, "booleanFilter"),
                            "sharedTo": grantees(element) or None,
                        }
                    )
                )
            elif tag == "sharingOwnerRules":
                owner_rules.append(
                    compact(
                        {
                            "name": direct_text(element, "fullName"),
                            "accessLevel": direct_text(element, "accessLevel"),
                            "parties": grantees(element) or None,
                        }
                    )
                )
        sharing_truncated = (
            len(criteria_rules) > self.MAX_RULES or len(owner_rules) > self.MAX_RULES
        )
        references, truncation = self.cap_references(
            references, {"operates-on": 0, "shares-with": 1, "filters-field": 2}
        )
        return self.component(
            "SharingRules",
            object_name,
            path,
            {
                "object": object_name,
                "criteriaRules": criteria_rules[: self.MAX_RULES] or None,
                "ownerRules": owner_rules[: self.MAX_RULES] or None,
                "criteriaRuleCount": len(criteria_rules) or None,
                "ownerRuleCount": len(owner_rules) or None,
                "rulesTruncated": True if sharing_truncated else None,
                "factsTruncated": True if sharing_truncated else None,
                **truncation,
            },
            references,
            object_name,
        )

    # Bounds for routing-rule files: real Case assignment files run to hundreds of entries.
    # True totals stay in ruleCount/entryCount; the caps only bound the inlined structures.
    MAX_RULES = 50
    MAX_RULE_ENTRIES = 100
    # Rule-file container/entry tags and component types per suffix token.
    RULE_FILE_KINDS = {
        "assignmentRules": ("AssignmentRules", "assignmentRule"),
        "autoResponseRules": ("AutoResponseRules", "autoresponseRule"),
        "escalationRules": ("EscalationRules", "escalationRule"),
    }

    def parse_rule_file(self, path: Path, token: str) -> dict[str, Any]:
        """Assignment/auto-response/escalation rules: which fields route records where.

        Queue targets join the component graph via `assigns-to`; user targets are suppressed
        (usernames). Sender/notify e-mail addresses are never captured."""

        metadata_type, rule_tag = self.RULE_FILE_KINDS[token]
        root = self.parse_xml(path)
        object_name = path.name.removesuffix(f".{token}-meta.xml")
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        seen_references: set[tuple[str, str]] = {("operates-on", object_name)}

        def add_reference(kind: str, target: str | None, *, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        def routed(element: ET.Element) -> dict[str, Any]:
            assigned_to_type = direct_text(element, "assignedToType")
            assigned_to = direct_text(element, "assignedTo")
            if assigned_to_type == "Queue":
                add_reference("assigns-to", assigned_to)
                return {"assignedToType": assigned_to_type, "assignedTo": assigned_to}
            if assigned_to_type:
                # User/role targets: type only — usernames are never captured.
                return {"assignedToType": assigned_to_type}
            return {}

        rules: list[dict[str, Any]] = []
        for rule in (item for item in root.iter() if local_name(item.tag) == rule_tag):
            entries: list[dict[str, Any]] = []
            for order, entry in enumerate(
                (item for item in rule.iter() if local_name(item.tag) == "ruleEntry"), 1
            ):
                criteria = self._criteria_entries(entry)
                for item in criteria:
                    add_reference(
                        "filters-field",
                        item["field"]
                        if "." in item["field"]
                        else f"{object_name}.{item['field']}",
                    )
                formula = direct_text(entry, "formula")
                if formula:
                    for reference in self.formula_field_references(object_name, formula):
                        # Formula edges are regex-derived; keep their heuristic marker —
                        # re-emitting them bare would launder assurance (contract §6).
                        add_reference(
                            "filters-field",
                            reference["target"],
                            heuristic=bool(reference.get("heuristic")),
                        )
                template = direct_text(entry, "template")
                add_reference("uses-template", template)
                escalation_actions = []
                for action in (
                    item
                    for item in entry.iter()
                    if local_name(item.tag) == "escalationAction"
                ):
                    action_template = direct_text(action, "assignToTemplate") or direct_text(
                        action, "notifyTemplate"
                    )
                    add_reference("uses-template", action_template)
                    escalation_actions.append(
                        compact(
                            {
                                "minutesToEscalation": direct_text(
                                    action, "minutesToEscalation"
                                ),
                                "notifyCaseOwner": boolean(
                                    direct_text(action, "notifyCaseOwner")
                                ),
                                **routed(action),
                            }
                        )
                    )
                entries.append(
                    compact(
                        {
                            "order": order,
                            "criteria": criteria,
                            "booleanFilter": direct_text(entry, "booleanFilter"),
                            "template": template,
                            "escalationActions": escalation_actions or None,
                            **routed(entry),
                        }
                    )
                )
            entries_truncated = len(entries) > self.MAX_RULE_ENTRIES
            rules.append(
                compact(
                    {
                        "name": direct_text(rule, "fullName"),
                        "active": boolean(direct_text(rule, "active")),
                        "entries": entries[: self.MAX_RULE_ENTRIES] or None,
                        "entryCount": len(entries) or None,
                        "entriesTruncated": True if entries_truncated else None,
                    }
                )
            )
        rules_truncated = len(rules) > self.MAX_RULES
        facts_truncated = rules_truncated or any(
            rule.get("entriesTruncated") for rule in rules[: self.MAX_RULES]
        )
        references, truncation = self.cap_references(
            references,
            {"operates-on": 0, "assigns-to": 1, "uses-template": 2, "filters-field": 3},
        )
        return self.component(
            metadata_type,
            object_name,
            path,
            {
                "object": object_name,
                "rules": rules[: self.MAX_RULES] or None,
                "ruleCount": len(rules) or None,
                "rulesTruncated": True if rules_truncated else None,
                "factsTruncated": True if facts_truncated else None,
                **truncation,
            },
            references,
            object_name,
        )

    def parse_queue(self, path: Path) -> dict[str, Any]:
        """Queue: routing topology — which objects route through it. Member counts only."""

        root = self.parse_xml(path)
        name = direct_text(root, "name") or path.name.removesuffix(".queue-meta.xml")
        served = sorted(set(descendant_texts(root, "sobjectType")))
        member_counts: dict[str, int] = {}
        for element in root.iter():
            tag = local_name(element.tag)
            if tag in {"users", "roles", "publicGroups", "rolesAndSubordinates"}:
                member_counts[tag] = member_counts.get(tag, 0) + len(
                    [child for child in list(element) if child.text and child.text.strip()]
                )
        return self.component(
            "Queue",
            name,
            path,
            {
                "name": name,
                "doesSendEmailToMembers": boolean(
                    direct_text(root, "doesSendEmailToMembers")
                ),
                "memberCounts": {k: v for k, v in sorted(member_counts.items()) if v}
                or None,
                "servesObjects": served or None,
            },
            [{"kind": "serves-object", "target": target} for target in served],
            name,
        )

    def parse_role(self, path: Path) -> dict[str, Any]:
        """Role: the hierarchy node behind sharing rollup and implicit access."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".role-meta.xml")
        parent = direct_text(root, "parentRole")
        return self.component(
            "Role",
            name,
            path,
            {
                "label": direct_text(root, "label") or direct_text(root, "name") or name,
                "caseAccessLevel": direct_text(root, "caseAccessLevel"),
                "contactAccessLevel": direct_text(root, "contactAccessLevel"),
                "opportunityAccessLevel": direct_text(root, "opportunityAccessLevel"),
                "mayForecastManagerShare": boolean(
                    direct_text(root, "mayForecastManagerShare")
                ),
                # Role descriptions sometimes embed person names — sanitized like literals.
                "description": sanitize_literal(direct_text(root, "description")),
            },
            [{"kind": "reports-to", "target": parent}] if parent else [],
            name,
        )

    def parse_muting_permission_set(self, path: Path) -> dict[str, Any]:
        """Muting permission set: negative grants, facts-only by design.

        Muted access must never mix into positive-grant aggregation, so the shared access
        bundle's facts are remapped under muted* keys and its edges are discarded — the PSG's
        `mutes-permission-set` edge (Phase 18) already links the component into the graph."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".mutingpermissionset-meta.xml")
        bundle_facts, _ = self._parse_access_bundle(root)
        facts: dict[str, Any] = {"label": direct_text(root, "label")}
        for key, value in bundle_facts.items():
            if key == "objectAccess":
                facts["mutedObjectAccess"] = value
            elif key == "systemPermissions":
                facts["mutedSystemPermissions"] = value
            elif key in {"referencesTruncated", "truncatedFamilies"}:
                continue
            else:
                facts[key] = value
        return self.component("MutingPermissionSet", name, path, compact(facts), [], name)

    def parse_delegate_group(self, path: Path) -> dict[str, Any]:
        """Delegated-admin group: its assignable permission sets/profiles are an escalation path."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".delegateGroup-meta.xml")
        assignable_permission_sets = descendant_texts(root, "permissionSets")
        assignable_profiles = descendant_texts(root, "profiles")
        roles = descendant_texts(root, "roles")
        references: list[dict[str, Any]] = [
            {"kind": "grants-to-permission-set", "target": target}
            for target in assignable_permission_sets
        ]
        references.extend(
            {"kind": "grants-to-profile", "target": target}
            for target in assignable_profiles
        )
        return self.component(
            "DelegateGroup",
            name,
            path,
            {
                "label": direct_text(root, "label") or name,
                "loginAccess": boolean(direct_text(root, "loginAccess")),
                "administersRoles": roles or None,
                "assignablePermissionSetCount": len(assignable_permission_sets) or None,
                "assignableProfileCount": len(assignable_profiles) or None,
            },
            references,
            name,
        )

    def parse_layout(self, path: Path) -> dict[str, Any]:
        """Page layout: placed fields with their UI behavior, sections, actions, related lists.

        `behavior=Required` on a layout makes a field mandatory in that UI even when the field
        itself is not required — the classic "why is this required?" answer, kept in facts."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".layout-meta.xml")
        object_name = name.split("-", 1)[0] if "-" in name else None

        def qualified(field: str) -> str:
            return f"{object_name}.{field}" if object_name else field

        field_targets: set[str] = set()
        required_on_layout: set[str] = set()
        readonly_on_layout: set[str] = set()
        display_targets: set[str] = set()
        for element in root.iter():
            if local_name(element.tag) != "layoutItems":
                continue
            field = direct_text(element, "field")
            if field:
                field_targets.add(qualified(field))
                behavior = direct_text(element, "behavior")
                if behavior == "Required":
                    required_on_layout.add(qualified(field))
                elif behavior == "Readonly":
                    readonly_on_layout.add(qualified(field))
            for tag in ("page", "component", "reportChartComponent"):
                value = direct_text(element, tag)
                if value:
                    display_targets.add(value)
        sections = [
            direct_text(element, "label")
            for element in root.iter()
            if local_name(element.tag) == "layoutSections" and direct_text(element, "label")
        ]
        action_names = sorted(
            {
                value
                for element in root.iter()
                if local_name(element.tag)
                in {"platformActionListItems", "quickActionListItems"}
                for value in [
                    direct_text(element, "actionName")
                    or direct_text(element, "quickActionName")
                ]
                if value
            }
        )
        related_lists: list[dict[str, Any]] = []
        for element in root.iter():
            if local_name(element.tag) != "relatedLists":
                continue
            list_name = direct_text(element, "relatedList")
            if not list_name:
                continue
            related_lists.append(
                compact(
                    {
                        "name": list_name,
                        # Columns are child-object field names; the child object is not
                        # resolvable from the relationship name alone, so they stay facts.
                        "fields": descendant_texts(element, "fields") or None,
                    }
                )
            )
        references: list[dict[str, Any]] = []
        if object_name:
            # The Object-LayoutName filename split is the SFDX layout naming contract,
            # so the owning-object edge is a direct read, not a guess.
            references.append({"kind": "operates-on", "target": object_name})
        references.extend(
            {"kind": "places-field", "target": target} for target in sorted(field_targets)
        )
        references.extend(
            {"kind": "related-list", "target": item["name"]} for item in related_lists
        )
        references.extend({"kind": "action", "target": value} for value in action_names)
        references.extend(
            {"kind": "displays-component", "target": value}
            for value in sorted(display_targets)
        )
        references, truncation = self.cap_references(
            references,
            {
                "operates-on": 0,
                "places-field": 1,
                "related-list": 2,
                "action": 3,
                "displays-component": 4,
            },
        )
        facts = compact(
            {
                "object": object_name,
                "fieldCount": len(field_targets),
                "requiredOnLayout": sorted(required_on_layout) or None,
                "readonlyOnLayout": sorted(readonly_on_layout) or None,
                "sections": sections or None,
                "relatedLists": related_lists or None,
                "actionCount": len(action_names) or None,
                **truncation,
            }
        )
        return self.component("Layout", name, path, facts, references, name)

    # Bound on recorded per-app action overrides; the count is always kept.
    APPLICATION_OVERRIDE_CAP = 50

    def parse_custom_application(self, path: Path) -> dict[str, Any]:
        """Lightning/classic app: navigation scope and per-profile page assignments.

        `profileActionOverrides` is where app+profile+recordType → FlexiPage assignment lives in
        source format — the only way to answer "which record page does profile X actually get"."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".app-meta.xml")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        tabs = [
            element.text.strip()
            for element in root.iter()
            if local_name(element.tag) == "tabs" and element.text and element.text.strip()
        ]
        for tab in tabs:
            if tab.startswith("standard-"):
                add_reference("operates-on", tab.removeprefix("standard-"))
            else:
                add_reference("displays-component", tab)
        utility_bar = direct_text(root, "utilityBar")
        add_reference("displays-component", utility_bar)
        overrides: list[dict[str, Any]] = []
        override_count = 0
        for element in root.iter():
            if local_name(element.tag) not in {"actionOverrides", "profileActionOverrides"}:
                continue
            override_count += 1
            content = direct_text(element, "content")
            add_reference("overrides-view", content)
            subject = direct_text(element, "pageOrSobjectType")
            if len(overrides) < self.APPLICATION_OVERRIDE_CAP:
                overrides.append(
                    compact(
                        {
                            "action": direct_text(element, "actionName"),
                            "content": content,
                            "type": direct_text(element, "type"),
                            "object": subject,
                            "recordType": direct_text(element, "recordType"),
                            "profile": direct_text(element, "profile"),
                            "formFactor": direct_text(element, "formFactor"),
                        }
                    )
                )
        references, truncation = self.cap_references(
            references,
            {"operates-on": 0, "displays-component": 1, "overrides-view": 2},
        )
        return self.component(
            "CustomApplication",
            name,
            path,
            {
                "label": direct_text(root, "label"),
                "navType": direct_text(root, "navType"),
                "uiType": direct_text(root, "uiType"),
                "formFactors": descendant_texts(root, "formFactors") or None,
                "tabs": tabs or None,
                "hasUtilityBar": True if utility_bar else None,
                "overrides": overrides or None,
                "overrideCount": override_count or None,
                "overridesTruncated": (
                    True if override_count > len(overrides) else None
                ),
                "factsTruncated": (
                    True if override_count > len(overrides) else None
                ),
                **truncation,
            },
            references,
            name,
        )

    def parse_quick_action(self, path: Path) -> dict[str, Any]:
        """Quick action: a create/update/flow/component entry point users actually fill in."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".quickAction-meta.xml")
        object_name = direct_text(root, "targetObject") or (
            name.split(".", 1)[0] if "." in name else None
        )
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        def qualified(field: str) -> str:
            if "." in field or not object_name:
                return field
            return f"{object_name}.{field}"

        add_reference("operates-on", object_name)
        layout_fields = [
            field
            for element in root.iter()
            if local_name(element.tag) == "quickActionLayoutItems"
            for field in [direct_text(element, "field")]
            if field
        ]
        for field in layout_fields:
            add_reference("places-field", qualified(field))
        override_fields = [
            field
            for element in root.iter()
            if local_name(element.tag) == "fieldOverrides"
            for field in [direct_text(element, "field")]
            if field
        ]
        for field in override_fields:
            add_reference("references-field", qualified(field))
        target_parent_field = direct_text(root, "targetParentField")
        if target_parent_field:
            add_reference("references-field", qualified(target_parent_field))
        add_reference("launches-flow", direct_text(root, "flowDefinition"))
        for tag in ("lightningWebComponent", "lightningComponent", "page"):
            add_reference("displays-component", direct_text(root, tag))
        return self.component(
            "QuickAction",
            name,
            path,
            {
                "label": direct_text(root, "label"),
                "actionType": direct_text(root, "type"),
                "object": object_name,
                "targetRecordType": direct_text(root, "targetRecordType"),
                "targetParentField": target_parent_field,
                "fieldCount": len(layout_fields) or None,
                "overrideCount": len(override_fields) or None,
                "successMessage": direct_text(root, "successMessage"),
            },
            references,
            name,
        )

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
        "permissionsetgroup": "PermissionSetGroup",
        "mutingpermissionset": "MutingPermissionSet",
        "labels": "CustomLabels",
        "site": "CustomSite",
        "flexipage": "FlexiPage",
        "datasource": "ExternalDataSource",
        "authprovider": "AuthProvider",
    }

    def parse_report_type(self, path: Path) -> dict[str, Any]:
        """Custom report type: a deterministic object/field surface exposed to report builders."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".reportType-meta.xml")
        base_object = direct_text(root, "baseObject")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        add_reference("operates-on", base_object)
        tables: set[str] = set()
        column_count = 0
        for column in (
            item for item in root.iter() if local_name(item.tag) == "columns"
        ):
            field = direct_text(column, "field")
            table = direct_text(column, "table")
            if not field:
                continue
            column_count += 1
            if table:
                tables.add(table)
            # Join-path tables (Base.Child__r) name relationships, not objects — only the base
            # table's fields resolve deterministically.
            if table and "." not in table:
                add_reference("references-field", f"{table}.{field}")
        return self.component(
            "ReportType",
            name,
            path,
            {
                "label": direct_text(root, "label"),
                "description": direct_text(root, "description"),
                "baseObject": base_object,
                "category": direct_text(root, "category"),
                "deployed": boolean(direct_text(root, "deployed")),
                "tables": sorted(tables) or None,
                "columnCount": column_count or None,
            },
            references,
            name,
        )

    # Bound on recorded report filters/columns; totals always kept.
    REPORT_ITEM_CAP = 50

    def parse_report(self, path: Path) -> dict[str, Any]:
        """Report: the org's used-field vocabulary — columns, filters, groupings.

        Column tokens mix API names with opaque standard-report tokens (FK_ACCOUNT.NAME), so
        every field edge is a per-reference heuristic. Filter values are captured (sanitized)."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".report-meta.xml")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_field_reference(kind: str, token: str | None) -> None:
            if not token or "." not in token:
                return
            if (kind, token) not in seen_references:
                seen_references.add((kind, token))
                references.append({"kind": kind, "target": token, "heuristic": True})

        column_count = 0
        for column in (
            item for item in root.iter() if local_name(item.tag) == "columns"
        ):
            field = direct_text(column, "field")
            if field:
                column_count += 1
                add_field_reference("references-field", field)
        filters: list[dict[str, Any]] = []
        filter_count = 0
        for item in (
            element
            for element in root.iter()
            if local_name(element.tag) == "criteriaItems"
        ):
            column = direct_text(item, "column")
            if not column:
                continue
            filter_count += 1
            add_field_reference("filters-field", column)
            if len(filters) < self.REPORT_ITEM_CAP:
                filters.append(
                    compact(
                        {
                            "column": column,
                            "operator": direct_text(item, "operator"),
                            "value": sanitize_literal(direct_text(item, "value")),
                        }
                    )
                )
        groupings = sorted(
            {
                field
                for element in root.iter()
                if local_name(element.tag) in {"groupingsDown", "groupingsAcross"}
                for field in [direct_text(element, "field")]
                if field
            }
        )
        for field in groupings:
            add_field_reference("references-field", field)
        time_frame = next(
            (
                item
                for item in list(root)
                if local_name(item.tag) == "timeFrameFilter"
            ),
            None,
        )
        relative = self.relative(path)
        folder = relative.split("/reports/", 1)[1].rsplit("/", 1)[0] if "/reports/" in relative and "/" in relative.split("/reports/", 1)[1] else None
        references, truncation = self.cap_references(
            references, {"filters-field": 0, "references-field": 1}
        )
        return self.component(
            "Report",
            # Folder-qualified identity: two same-named reports in different folders are
            # distinct components (the EmailTemplate precedent) — the bare stem collided.
            f"{folder}/{name}" if folder else name,
            path,
            {
                "label": direct_text(root, "name"),
                "format": direct_text(root, "format"),
                "reportType": direct_text(root, "reportType"),
                "scope": direct_text(root, "scope"),
                "folder": folder,
                "columnCount": column_count or None,
                "filters": filters or None,
                "filterCount": filter_count or None,
                "filtersTruncated": True if filter_count > len(filters) else None,
                "factsTruncated": True if filter_count > len(filters) else None,
                **truncation,
                "groupings": groupings or None,
                "hasChart": (
                    True
                    if any(local_name(item.tag) == "chart" for item in root.iter())
                    else None
                ),
                "timeFrame": (
                    compact(
                        {
                            "dateColumn": direct_text(time_frame, "dateColumn"),
                            "interval": direct_text(time_frame, "interval"),
                        }
                    )
                    if time_frame is not None
                    else None
                )
                or None,
            },
            references,
            name,
        )

    def parse_dashboard(self, path: Path) -> dict[str, Any]:
        """Dashboard: report wiring and run-as posture (mode only — never the username)."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".dashboard-meta.xml")
        relative = self.relative(path)
        folder = (
            relative.split("/dashboards/", 1)[1].rsplit("/", 1)[0]
            if "/dashboards/" in relative
            and "/" in relative.split("/dashboards/", 1)[1]
            else None
        )
        reports = sorted(set(descendant_texts(root, "report")))
        running_user_policy = direct_text(root, "dashboardType") or (
            "SpecifiedUser" if direct_text(root, "runningUser") else None
        )
        return self.component(
            "Dashboard",
            # Folder-qualified identity, matching the Report/EmailTemplate convention.
            f"{folder}/{name}" if folder else name,
            path,
            {
                "folder": folder,
                "label": direct_text(root, "title") or direct_text(root, "masterLabel"),
                "runningUserPolicy": running_user_policy,
                "componentCount": sum(
                    1
                    for item in root.iter()
                    if local_name(item.tag) == "dashboardComponent"
                )
                or None,
                "reports": reports or None,
            },
            [{"kind": "displays-component", "target": value} for value in reports],
            name,
        )

    def parse_path_assistant(self, path: Path) -> dict[str, Any]:
        """Path: per-stage key fields and guidance — process knowledge in the org's own words."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".pathAssistant-meta.xml")
        object_name = direct_text(root, "entityName")
        driving_field = direct_text(root, "fieldName")
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                references.append({"kind": kind, "target": target})

        add_reference("operates-on", object_name)
        if object_name and driving_field:
            add_reference("references-field", f"{object_name}.{driving_field}")
        steps: list[dict[str, Any]] = []
        for step in (
            item for item in root.iter() if local_name(item.tag) == "pathAssistantSteps"
        ):
            fields = descendant_texts(step, "fieldNames")
            for field in fields:
                if object_name:
                    add_reference("places-field", f"{object_name}.{field}")
            info = direct_text(step, "info")
            steps.append(
                compact(
                    {
                        "value": direct_text(step, "picklistValueName"),
                        "fields": fields or None,
                        "guidance": sanitize_literal(
                            re.sub(r"<[^>]+>", " ", info).strip() if info else None
                        ),
                    }
                )
            )
        return self.component(
            "PathAssistant",
            name,
            path,
            {
                "label": direct_text(root, "masterLabel"),
                "active": boolean(direct_text(root, "active")),
                "object": object_name,
                "drivingField": (
                    f"{object_name}.{driving_field}"
                    if object_name and driving_field
                    else driving_field
                ),
                "recordType": direct_text(root, "recordTypeName"),
                "steps": steps or None,
            },
            references,
            name,
        )

    def parse_custom_metadata_record(self, path: Path) -> dict[str, Any]:
        """Custom-metadata record: configuration masquerading as data.

        Automation branches on these records, so names and populated fields matter. Values are
        the one place in the schema family where secrets get stashed — every value passes
        sanitize_literal, and values on protected records are dropped entirely."""

        root = self.parse_xml(path)
        stem = path.name.removesuffix(".md-meta.xml")
        type_name, _, record = stem.partition(".")
        if not type_name.endswith("__mdt"):
            type_name = f"{type_name}__mdt"
        protected = boolean(direct_text(root, "protected"))
        fields_populated: list[str] = []
        values: list[dict[str, Any]] = []
        for element in root.iter():
            if local_name(element.tag) != "values":
                continue
            field = direct_text(element, "field")
            if not field:
                continue
            value_element = next(
                (item for item in list(element) if local_name(item.tag) == "value"), None
            )
            raw_value = (
                value_element.text.strip()
                if value_element is not None
                and value_element.text
                and value_element.text.strip()
                else None
            )
            if raw_value is not None:
                fields_populated.append(field)
                if not protected:
                    values.append(
                        compact({"field": field, "value": sanitize_literal(raw_value)})
                    )
        references: list[dict[str, Any]] = [
            {"kind": "belongs-to", "target": type_name},
            {"kind": "operates-on", "target": type_name},
        ]
        references.extend(
            {"kind": "references-field", "target": f"{type_name}.{field}"}
            for field in sorted(set(fields_populated))
        )
        return self.component(
            "CustomMetadata",
            f"{type_name}.{record}",
            path,
            {
                "type": type_name,
                "record": record,
                "label": direct_text(root, "label"),
                "protected": protected,
                "fieldsPopulated": sorted(set(fields_populated)) or None,
                "values": values or None,
            },
            references,
            record,
        )

    def parse_permission_set_group(self, path: Path) -> dict[str, Any]:
        root = self.parse_xml(path)
        name = path.name.removesuffix(".permissionsetgroup-meta.xml")
        included = descendant_texts(root, "permissionSets")
        muted = descendant_texts(root, "mutingPermissionSets")
        references: list[dict[str, Any]] = [
            {"kind": "includes-permission-set", "target": target} for target in included
        ]
        references.extend(
            {"kind": "mutes-permission-set", "target": target} for target in muted
        )
        return self.component(
            "PermissionSetGroup",
            name,
            path,
            {
                "label": direct_text(root, "label"),
                "status": direct_text(root, "status"),
                "permissionSetCount": len(included) or None,
                "mutingPermissionSetCount": len(muted) or None,
            },
            references,
            name,
        )

    def parse_custom_tab(self, path: Path) -> dict[str, Any]:
        """Custom tab: which variant it is — object tabs confirm nav-level object exposure."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".tab-meta.xml")
        references: list[dict[str, Any]] = []
        flexi_page = direct_text(root, "flexiPage")
        vf_page = direct_text(root, "page")
        lwc = direct_text(root, "lwcComponent")
        aura = direct_text(root, "auraComponent")
        url = direct_text(root, "url")
        if boolean(direct_text(root, "customObject")):
            tab_kind = "object"
            references.append({"kind": "operates-on", "target": name})
        elif flexi_page:
            tab_kind = "flexiPage"
            references.append({"kind": "displays-component", "target": flexi_page})
        elif vf_page:
            tab_kind = "visualforce"
            references.append({"kind": "displays-component", "target": vf_page})
        elif lwc:
            tab_kind = "lwc"
            references.append({"kind": "displays-component", "target": lwc})
        elif aura:
            tab_kind = "aura"
            references.append({"kind": "displays-component", "target": aura})
        elif url:
            tab_kind = "web"
        else:
            tab_kind = "unknown"
        return self.component(
            "CustomTab",
            name,
            path,
            {
                "label": direct_text(root, "label") or direct_text(root, "masterLabel"),
                "tabKind": tab_kind,
                "urlHost": urlsplit(url).hostname if url else None,
            },
            references,
            name,
        )

    # Standard objects whose merge-field heads appear in classic email templates. Custom
    # objects match CUSTOM_OBJECT_RE instead.
    EMAIL_MERGE_STANDARD_HEADS = frozenset(
        {"Account", "Contact", "Lead", "Case", "Opportunity", "User", "Organization"}
    )
    EMAIL_MERGE_RE = re.compile(r"\{!([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\}")
    EMAIL_RELATED_TO_RE = re.compile(r'relatedToType\s*=\s*"([A-Za-z][A-Za-z0-9_]*)"')

    def parse_email_template(self, path: Path) -> dict[str, Any]:
        """Email template: the target of every `uses-template` edge, plus its field diet.

        Component identity is `Folder/Name` — the exact format workflow alerts, approval
        processes, and routing rules reference. Broken merge fields render blank silently, so
        the template's Object.Field reads matter for rename impact."""

        source = path.read_text(encoding="utf-8", errors="replace")
        folder = path.parent.name
        name = f"{folder}/{path.stem}"
        references: list[dict[str, Any]] = []
        seen_references: set[tuple[str, str]] = set()

        def add_reference(kind: str, target: str | None, heuristic: bool = False) -> None:
            if target and (kind, target) not in seen_references:
                seen_references.add((kind, target))
                reference: dict[str, Any] = {"kind": kind, "target": target}
                if heuristic:
                    reference["heuristic"] = True
                references.append(reference)

        # Template bodies are free text, not XML — every edge here is regex-derived and
        # carries the heuristic marker.
        related_to = next(iter(self.EMAIL_RELATED_TO_RE.findall(source)), None)
        add_reference("operates-on", related_to, heuristic=True)
        if self.markup_field_extraction:
            for head, field in self.EMAIL_MERGE_RE.findall(source):
                if head in self.EMAIL_MERGE_STANDARD_HEADS or CUSTOM_OBJECT_RE.fullmatch(
                    head
                ):
                    add_reference("references-field", f"{head}.{field}", heuristic=True)
            for value in sorted(set(VF_EMBED_RE.findall(source))):
                add_reference("embeds-component", value, heuristic=True)
        for match in LABEL_TOKEN_RE.finditer(source):
            add_reference("uses-label", match.group(1) or match.group(2), heuristic=True)
        facts: dict[str, Any] = {}
        meta_path = path.with_name(path.name + "-meta.xml")
        if meta_path.is_file():
            try:
                meta_root = self.parse_xml(meta_path)
            except (ET.ParseError, OSError):
                meta_root = None
            if meta_root is not None:
                facts = {
                    "templateType": direct_text(meta_root, "type"),
                    "subject": sanitize_literal(direct_text(meta_root, "subject")),
                    "encoding": direct_text(meta_root, "encodingKey"),
                    "letterhead": direct_text(meta_root, "letterhead"),
                    "relatedEntityType": direct_text(meta_root, "relatedEntityType"),
                    "available": boolean(direct_text(meta_root, "available")),
                }
        facts["folder"] = folder
        return self.component(
            "EmailTemplate", name, path, compact(facts), references, path.stem
        )

    def parse_static_resource(self, path: Path) -> dict[str, Any]:
        """Static resource boundary: type and cache posture. Contents stay a black box —
        scanning minified vendor bundles would flood the graph with edges from code the team
        does not own."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".resource-meta.xml")
        return self.component(
            "StaticResource",
            name,
            path,
            {
                "contentType": direct_text(root, "contentType"),
                "cacheControl": direct_text(root, "cacheControl"),
                "description": direct_text(root, "description"),
            },
            needle=name,
        )

    def parse_compact_layout(self, path: Path) -> dict[str, Any]:
        """Compact layout: the at-a-glance identity fields (highlights panel, mobile cards)."""

        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".compactLayout-meta.xml"
        )
        # Document order matters — the first field is the highlight title.
        fields = [
            element.text.strip()
            for element in root.iter()
            if local_name(element.tag) == "fields"
            and element.text
            and element.text.strip()
        ]
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        references.extend(
            {"kind": "places-field", "target": f"{object_name}.{field}"}
            for field in sorted(set(fields))
        )
        return self.component(
            "CompactLayout",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "label": direct_text(root, "label"),
                "fields": fields or None,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    def parse_web_link(self, path: Path) -> dict[str, Any]:
        """Custom button/link: a legacy navigation/integration surface.

        JavaScript buttons are a tech-debt flag (blocked in Lightning); their body is never
        stored. URL targets collapse to their hostname."""

        root = self.parse_xml(path)
        object_name = object_from_path(path)
        name = direct_text(root, "fullName") or path.name.removesuffix(
            ".webLink-meta.xml"
        )
        link_type = direct_text(root, "linkType")
        url_text = direct_text(root, "url") or ""
        references: list[dict[str, Any]] = [{"kind": "operates-on", "target": object_name}]
        page = direct_text(root, "page")
        if page:
            references.append({"kind": "displays-component", "target": page})
        target_host = None
        if link_type == "url" and "://" in url_text:
            target_host = urlsplit(url_text).hostname
        if link_type != "javascript" and url_text:
            seen = {(item["kind"], item["target"]) for item in references}
            for reference in self.formula_field_references(object_name, url_text):
                if (reference["kind"], reference["target"]) not in seen:
                    seen.add((reference["kind"], reference["target"]))
                    references.append(reference)
        return self.component(
            "WebLink",
            f"{object_name}.{name}",
            path,
            {
                "object": object_name,
                "fullName": name,
                "label": direct_text(root, "masterLabel"),
                "displayType": direct_text(root, "displayType"),
                "linkType": link_type,
                "openType": direct_text(root, "openType"),
                "page": page,
                "targetHost": target_host,
                "isJavascript": True if link_type == "javascript" else None,
            },
            references,
            f"<fullName>{name}</fullName>",
        )

    def parse_matching_rules(self, path: Path) -> list[dict[str, Any]]:
        """MatchingRules file → one MatchingRule component per nested rule.

        Identity `Object.RuleName` matches the target format DuplicateRule's
        `uses-matching-rule` edges emit, so the dedupe graph resolves end to end. Which fields
        participate in identity matching is another load-bearing-field signal."""

        root = self.parse_xml(path)
        object_name = path.name.removesuffix("-meta.xml").split(".", 1)[0]
        components: list[dict[str, Any]] = []
        for rule in (item for item in root.iter() if local_name(item.tag) == "matchingRules"):
            name = direct_text(rule, "fullName")
            if not name:
                continue
            items = [
                compact(
                    {
                        "field": direct_text(item, "fieldName"),
                        "matchingMethod": direct_text(item, "matchingMethod"),
                        "blankValueBehavior": direct_text(item, "blankValueBehavior"),
                    }
                )
                for item in rule.iter()
                if local_name(item.tag) == "matchingRuleItems"
            ]
            references: list[dict[str, Any]] = [
                {"kind": "operates-on", "target": object_name}
            ]
            references.extend(
                {"kind": "references-field", "target": f"{object_name}.{item['field']}"}
                for item in items
                if item.get("field")
            )
            components.append(
                self.component(
                    "MatchingRule",
                    f"{object_name}.{name}",
                    path,
                    {
                        "object": object_name,
                        "fullName": name,
                        "label": direct_text(rule, "label"),
                        "ruleStatus": direct_text(rule, "ruleStatus"),
                        "booleanFilter": direct_text(rule, "booleanFilter"),
                        "items": items or None,
                    },
                    references,
                    f"<fullName>{name}</fullName>",
                )
            )
        return components

    def parse_flow_definition(self, path: Path) -> dict[str, Any]:
        """FlowDefinition: the legacy activation pointer that can contradict the Flow's status.

        `activeVersionNumber: 0` means the like-named Flow is OFF even when its own metadata
        says Active — the one fact an automation-inventory consumer must be able to join."""

        root = self.parse_xml(path)
        name = path.name.removesuffix(".flowDefinition-meta.xml")
        raw_version = direct_text(root, "activeVersionNumber")
        try:
            active = int(raw_version) > 0 if raw_version is not None else None
        except ValueError:
            active = None
        return self.component(
            "FlowDefinition",
            name,
            path,
            {
                "activeVersionNumber": raw_version,
                "active": active,
                "description": direct_text(root, "description"),
            },
            [{"kind": "relationship", "target": f"Flow.{name}"}],
            name,
        )

    def parse_custom_labels(self, path: Path) -> list[dict[str, Any]]:
        """CustomLabels file → one container plus one CustomLabel component per label.

        Label values are user-pasted UI text — the per-label component (and its value-bearing
        claim statement) makes them BM25-searchable, and consumer `uses-label` edges turn the
        reference graph into the label's blast-radius index."""

        root = self.parse_xml(path)
        components: list[dict[str, Any]] = []
        label_count = 0
        for element in root.iter():
            if local_name(element.tag) != "labels":
                continue
            name = direct_text(element, "fullName")
            if not name:
                continue
            label_count += 1
            components.append(
                self.component(
                    "CustomLabel",
                    name,
                    path,
                    {
                        "value": sanitize_literal(direct_text(element, "value")),
                        "language": direct_text(element, "language"),
                        "protected": boolean(direct_text(element, "protected")),
                        "categories": direct_text(element, "categories"),
                        "shortDescription": direct_text(element, "shortDescription"),
                    },
                    needle=f"<fullName>{name}</fullName>",
                )
            )
        components.append(
            self.component(
                "CustomLabels",
                path.name.removesuffix(".labels-meta.xml"),
                path,
                {"labelCount": label_count},
            )
        )
        return components

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
            ("*.recordType-meta.xml", self.parse_record_type),
            ("*.businessProcess-meta.xml", self.parse_business_process),
            ("*.listView-meta.xml", self.parse_list_view),
            ("*.fieldSet-meta.xml", self.parse_field_set),
            ("*.sharingRules-meta.xml", self.parse_sharing_rules),
            ("*.queue-meta.xml", self.parse_queue),
            *(
                (f"*.{token}-meta.xml", partial(self.parse_rule_file, token=token))
                for token in self.RULE_FILE_KINDS
            ),
            ("*.flow-meta.xml", self.parse_flow),
            ("*.workflow-meta.xml", self.parse_workflow),
            ("*.approvalProcess-meta.xml", self.parse_approval_process),
            ("*.validationRule-meta.xml", self.parse_validation_rule),
            ("*.duplicateRule-meta.xml", self.parse_duplicate_rule),
            ("*.permissionset-meta.xml", self.parse_permission_set),
            ("*.profile-meta.xml", self.parse_profile),
            ("*.layout-meta.xml", self.parse_layout),
            ("*.flexipage-meta.xml", self.parse_flexipage),
            ("*.quickAction-meta.xml", self.parse_quick_action),
            ("*.app-meta.xml", self.parse_custom_application),
            ("*.md-meta.xml", self.parse_custom_metadata_record),
            ("*.permissionsetgroup-meta.xml", self.parse_permission_set_group),
            ("*.tab-meta.xml", self.parse_custom_tab),
            ("*.reportType-meta.xml", self.parse_report_type),
            ("*.report-meta.xml", self.parse_report),
            ("*.dashboard-meta.xml", self.parse_dashboard),
            ("*.pathAssistant-meta.xml", self.parse_path_assistant),
            ("*.flowDefinition-meta.xml", self.parse_flow_definition),
            ("*.compactLayout-meta.xml", self.parse_compact_layout),
            ("*.webLink-meta.xml", self.parse_web_link),
            ("*.role-meta.xml", self.parse_role),
            ("*.mutingpermissionset-meta.xml", self.parse_muting_permission_set),
            ("*.delegateGroup-meta.xml", self.parse_delegate_group),
            ("*.platformEventChannel-meta.xml", self.parse_platform_event_channel),
            (
                "*.platformEventChannelMember-meta.xml",
                self.parse_platform_event_channel_member,
            ),
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
        # Directory-routed source types are discovered anywhere under the package directory.
        # SFDX projects commonly group metadata per domain (main/default/<domain>/classes/...),
        # and a hard-coded main/default/<folder> glob silently skipped every such class: they
        # fell through to the generic handler as `Cls`/`Trigger` with no references at all,
        # so the whole Apex usage registry came out empty on real projects.
        for folder, metadata_type, suffix in (
            ("classes", "ApexClass", ".cls"),
            ("triggers", "ApexTrigger", ".trigger"),
        ):
            for path in sorted(self.source_root.rglob(f"{folder}/*{suffix}")):
                try:
                    components.append(self.parse_apex(path, metadata_type))
                    handled.add(path)
                except OSError as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for folder, metadata_type, suffix in (
            ("pages", "ApexPage", ".page"),
            ("components", "ApexComponent", ".component"),
        ):
            for path in sorted(self.source_root.rglob(f"{folder}/*{suffix}")):
                try:
                    components.append(self.parse_visualforce(path, metadata_type))
                    handled.add(path)
                except OSError as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for path in sorted(self.source_root.rglob("*.labels-meta.xml")):
            try:
                components.extend(self.parse_custom_labels(path))
                handled.add(path)
            except (ET.ParseError, OSError) as exc:
                diagnostics.append(
                    {"severity": "error", "path": self.relative(path), "message": str(exc)}
                )
        for path in sorted(self.source_root.rglob("email/**/*.email")):
            try:
                components.append(self.parse_email_template(path))
                handled.add(path)
            except OSError as exc:
                diagnostics.append(
                    {"severity": "error", "path": self.relative(path), "message": str(exc)}
                )
        for path in sorted(self.source_root.rglob("*.resource-meta.xml")):
            try:
                components.append(self.parse_static_resource(path))
                handled.add(path)
                sibling = path.with_name(path.name.removesuffix("-meta.xml"))
                if sibling.is_file():
                    handled.add(sibling)
            except (ET.ParseError, OSError) as exc:
                diagnostics.append(
                    {"severity": "error", "path": self.relative(path), "message": str(exc)}
                )
        # SFDX uses the singular suffix; the plural glob is a safety net for hand-named files.
        for pattern in ("*.matchingRule-meta.xml", "*.matchingRules-meta.xml"):
            for path in sorted(self.source_root.rglob(pattern)):
                if path in handled:
                    continue
                try:
                    components.extend(self.parse_matching_rules(path))
                    handled.add(path)
                except (ET.ParseError, OSError) as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for folder, parser in (("lwc", self.parse_lwc), ("aura", self.parse_aura)):
            for base in sorted(path for path in self.source_root.rglob(folder) if path.is_dir()):
                for bundle in sorted(path for path in base.iterdir() if path.is_dir()):
                    try:
                        components.append(parser(bundle))
                        handled.update(path for path in bundle.rglob("*") if path.is_file())
                    except (ET.ParseError, OSError, IndexError) as exc:
                        diagnostics.append(
                            {"severity": "error", "path": self.relative(bundle), "message": str(exc)}
                        )
        for pattern, metadata_type in (
            ("*.globalValueSet-meta.xml", "GlobalValueSet"),
            ("*.standardValueSet-meta.xml", "StandardValueSet"),
        ):
            for path in sorted(self.source_root.rglob(pattern)):
                try:
                    components.append(self.parse_value_set(path, metadata_type))
                    handled.add(path)
                except (ET.ParseError, OSError) as exc:
                    diagnostics.append(
                        {"severity": "error", "path": self.relative(path), "message": str(exc)}
                    )
        for pattern, metadata_type in (
            ("*.namedCredential-meta.xml", "NamedCredential"),
            ("*.externalCredential-meta.xml", "ExternalCredential"),
            ("*.remoteSite-meta.xml", "RemoteSiteSetting"),
            ("*.dataSource-meta.xml", "ExternalDataSource"),
            ("*.externalServiceRegistration-meta.xml", "ExternalServiceRegistration"),
            ("*.connectedApp-meta.xml", "ConnectedApp"),
            ("*.authprovider-meta.xml", "AuthProvider"),
            ("*.cspTrustedSite-meta.xml", "CspTrustedSite"),
            ("*.corsWhitelistOrigin-meta.xml", "CorsWhitelistOrigin"),
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

    RESOLVE_INPUT_CAP = 50
    # One expansion (a directory, or a source file defining many components) larger than the
    # 25-spec chat-approval chunk is refused with a pointer, never silently truncated: the lane
    # cannot promote it in one pass, and a truncated match would misreport coverage.
    RESOLVE_EXPANSION_CAP = 25
    # Bundle components record one file inside their directory as `path` (the .js-meta.xml for
    # LWC), so a pinned sibling file resolves through the bundle directory, not an exact path.
    BUNDLE_METADATA_TYPES = frozenset({"LightningComponentBundle", "AuraDefinitionBundle"})

    def resolve(
        self, paths: list[str], names: list[str], write: bool = False
    ) -> dict[str, Any]:
        """Map pinned file paths and mentioned component names onto inventory components.

        Read-only ground for the selected-files lane: an agent handed pinned files or free-text
        names must never map them to components by eye. Matching is purely lexical against the
        current inventory — input paths are never opened — and every match carries its lane
        (`entry` for entry-profiled types, `none` for types without an entry profile) plus the
        current documentation status on that lane, so the caller can plan without further
        lookups. Paths match
        case-insensitively (the team's filesystems are case-insensitive) and through companion
        siblings (`X.cls-meta.xml` ↔ `X.cls`). A file defining several components (labels,
        matching rules) expands to all of them — pinning the file means all of it. Ambiguity is
        reported, never guessed: a name matching components in different files returns them as
        `ambiguous`.
        """

        inputs = [("path", raw) for raw in paths] + [("name", raw) for raw in names]
        if not inputs:
            raise KnowledgeBuildError("resolve needs at least one --path or --name")
        if len(inputs) > self.RESOLVE_INPUT_CAP:
            raise KnowledgeBuildError(
                f"resolve accepts at most {self.RESOLVE_INPUT_CAP} inputs per call"
            )
        inventory = self.load_inventory()
        if inventory["sourceTreeDigest"] != self.current_tree_digest():
            raise KnowledgeBuildError("force-app changed after inventory; rerun inventory")

        components = inventory["components"]
        by_path: dict[str, list[dict[str, Any]]] = {}
        for component in components:
            by_path.setdefault(component["path"].casefold(), []).append(component)
        generic_paths = {item["path"].casefold() for item in inventory.get("genericFiles", [])}
        profiled = self.entry_draftable_types()
        entries = self.entry_descriptions()

        matched_items: dict[str, dict[str, Any]] = {}

        def item_for(component: dict[str, Any]) -> dict[str, Any]:
            cached = matched_items.get(component["id"])
            if cached is not None:
                return cached
            item: dict[str, Any] = {
                "componentId": component["id"],
                "metadataType": component["metadataType"],
                "name": component["name"],
                "path": component["path"],
                "lane": "entry" if component["metadataType"] in profiled else "none",
            }
            if item["lane"] == "entry":
                entry = entries.get(component["id"])
                if entry is None:
                    item["status"] = "no-entry"
                else:
                    item["status"] = str(entry["lane"])
                    item["described"] = bool(entry["purpose"])
            else:
                # No entry profile means no Knowledge lane at all since the claim registry
                # retired (owner D-B): report the gap, never a pseudo-status.
                item["status"] = "no-entry-profile"
                item["reason"] = (
                    f"{component['metadataType']} has no entry profile; extend "
                    "knowledge_store.PROFILES to document it"
                )
            matched_items[component["id"]] = item
            return item

        def normalize(raw: str) -> str | None:
            text = re.sub(r"/+", "/", raw.strip().replace("\\", "/")).rstrip("/")
            while text.startswith("./"):
                text = text[2:]
            if not text or ".." in text.split("/"):
                return None
            lowered = text.casefold()
            if lowered == "force-app" or lowered.startswith("force-app/"):
                return text
            # Absolute paths (macOS or Windows) and workspace-prefixed paths: keep everything
            # from the force-app segment down.
            marker = lowered.find("/force-app/")
            if marker >= 0:
                return text[marker + 1 :]
            if lowered.endswith("/force-app"):
                return "force-app"
            return None

        def aliases(component: dict[str, Any]) -> set[str]:
            basename = component["path"].rsplit("/", 1)[-1]
            trimmed = re.sub(r"\.[A-Za-z0-9]+-meta\.xml$", "", basename)
            bare = re.sub(r"\.[A-Za-z0-9]+$", "", basename)
            return {component["name"], component["id"], basename, trimmed, bare}

        alias_index: dict[str, list[dict[str, Any]]] = {}
        suggestion_pool: set[str] = set()
        for component in components:
            for alias in aliases(component):
                suggestion_pool.add(alias)
                bucket = alias_index.setdefault(alias.casefold(), [])
                # Case-variant aliases of one component casefold to the same key; a component
                # matching its own name twice must not read as an ambiguity.
                if all(hit is not component for hit in bucket):
                    bucket.append(component)

        selections: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()

        def record(kind: str, raw: str, resolution: str, **extra: Any) -> None:
            selections.append({"input": raw, "kind": kind, "resolution": resolution, **extra})
            counts[resolution] += 1

        def record_matches(kind: str, raw: str, hits: list[dict[str, Any]]) -> None:
            if len(hits) == 1:
                record(kind, raw, "resolved", componentIds=[item_for(hits[0])["componentId"]])
            elif len(hits) > self.RESOLVE_EXPANSION_CAP:
                record(
                    kind, raw, "unsupported",
                    reason=f"expands to {len(hits)} components — more than the "
                    f"{self.RESOLVE_EXPANSION_CAP}-component chunk one review pass can honestly "
                    "cover; narrow the selection or split it per metadata type",
                )
            else:
                record(
                    kind, raw, "expanded",
                    componentIds=sorted(item_for(hit)["componentId"] for hit in hits),
                )

        for raw in paths:
            if not raw.strip():
                record("path", "(empty)", "unsupported", reason="empty input")
                continue
            normalized = normalize(raw)
            if normalized is None:
                record("path", raw, "unsupported", reason="not a force-app path")
                continue
            key = normalized.casefold()
            hits = by_path.get(key, [])
            if not hits and key.endswith("-meta.xml"):
                # Companion sibling: the pinned meta file of a content-file component
                # (X.cls-meta.xml -> X.cls).
                hits = by_path.get(key[: -len("-meta.xml")], [])
            if not hits:
                # Companion sibling the other way: the pinned content file of a meta-file
                # component (X.resource -> X.resource-meta.xml).
                hits = by_path.get(key + "-meta.xml", [])
            if hits:
                record_matches("path", raw, hits)
                continue
            if key in generic_paths:
                record(
                    "path", raw, "unsupported",
                    reason="generic file — the inventory recognizes no component in it and no Knowledge is drafted for it",
                )
                continue
            bundle_hits = [
                candidate
                for candidate in components
                if candidate["metadataType"] in self.BUNDLE_METADATA_TYPES
                and key.startswith(candidate["path"].casefold().rsplit("/", 1)[0] + "/")
            ]
            if bundle_hits:
                record_matches("path", raw, bundle_hits)
                continue
            directory_hits = [
                candidate for candidate in components
                if candidate["path"].casefold().startswith(key + "/")
            ]
            if directory_hits:
                record_matches("path", raw, directory_hits)
                continue
            basename = normalized.rsplit("/", 1)[-1]
            record(
                "path", raw, "unmatched",
                suggestions=difflib.get_close_matches(basename, sorted(suggestion_pool), n=3, cutoff=0.6),
            )

        for raw in names:
            token = raw.strip()
            if not token:
                record("name", "(empty)", "unsupported", reason="empty input")
                continue
            hits = alias_index.get(token.casefold(), [])
            if not hits:
                record(
                    "name", raw, "unmatched",
                    suggestions=difflib.get_close_matches(token, sorted(suggestion_pool), n=3, cutoff=0.6),
                )
            elif len(hits) == 1 or len({hit["path"] for hit in hits}) == 1:
                # All candidates in one source file: the name denotes that file's contents,
                # exactly like pinning the file itself — expand, don't ambiguate.
                record_matches("name", raw, hits)
            else:
                record(
                    "name", raw, "ambiguous",
                    candidates=sorted(item_for(hit)["componentId"] for hit in hits),
                )

        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "force-app-knowledge-resolve",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "sourceTreeDigest": inventory["sourceTreeDigest"],
            "entryHomeActive": bool(self.entry_home_types()),
            "counts": dict(sorted(counts.items())),
            "selections": selections,
            "components": sorted(matched_items.values(), key=lambda item: item["componentId"]),
        }
        self.validate_record(
            result, "force-app-knowledge-resolve.schema.json", "force-app resolve"
        )
        if write:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            resolve_path = self.cache_root / "force-app-resolve.json"
            resolve_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            result["path"] = self.relative(resolve_path)
        return result

    # Suffixes that make a target name package-local: only this source tree can create one, so
    # live source can settle whether it still exists. A standard object (`Account`), a system
    # permission (`ViewAllData`), a platform type or a bare Apex name is NOT decidable from
    # source alone — absence from force-app is its ordinary state — so those targets are never
    # called orphans. Stating that limit is the point: a report that guessed would be unreadable.
    LOCAL_NAME_SUFFIXES = ("__c", "__e", "__mdt", "__b", "__x")

    @classmethod
    def _local_custom_name(cls, name: str) -> bool:
        """True when force-app is the only place this API name can come from."""

        for suffix in cls.LOCAL_NAME_SUFFIXES:
            if name.endswith(suffix):
                # `ns__Thing__c` is owned by an installed package. It is not in this repo and
                # never will be, so its absence is not rot.
                return "__" not in name[: -len(suffix)]
        return False

    @classmethod
    def _decidable_targets(cls, target: str) -> list[str]:
        """The component names inside one edge target whose existence live source can settle.

        Edge targets are written the way source writes them — a bare object/class name, or
        `Object.Member` for a field, record type or approval process. `Account.Name` yields
        nothing: neither segment is package-local. `Engagement__c.Status__c` yields the owning
        object and the field's own component name, because a deleted object and a deleted field
        are different findings and a reader needs to be told which one happened.
        """

        object_name, _, member = target.partition(".")
        if not member:
            return [target] if cls._local_custom_name(target) else []
        names = [object_name] if cls._local_custom_name(object_name) else []
        if names and cls._local_custom_name(member):
            names.append(target)
        return names

    @classmethod
    def _edge_target_verdict(
        cls,
        target: str,
        heuristic: bool,
        live_names: set[str],
        live_members: set[str],
    ) -> tuple[list[str], list[str]]:
        """(gone, undecidable) component names for one edge target, against live source.

        The bare-name case is the whole reason this exists. A regex extractor emits the token it
        found — `object-token` on `a.Allocation_Percent__c` yields `Allocation_Percent__c` with no
        owner — while a live field is only ever indexed under `Object.Field`. Diffing the bare
        token against the full names alone therefore reported 164 orphans on a 189-component
        corpus with nothing deleted, every one of them present all along, so the handful a real
        deletion produces arrived unreadable. Matching a bare token against every live
        component's own trailing name settles those.

        What is left over is genuinely ambiguous, and is returned as such rather than guessed at:
        an unmatched bare token may be a deleted object, a deleted field on any object, or a name
        the regex read out of a string literal that never was a component. R5 — coverage is
        disclosed, never implied — makes that a population to state, not an orphan to claim and
        not a silent drop, because a silent drop is what made the lane count mean nothing.
        Dotted targets carry their own owner, so nothing about them is ambiguous.
        """

        _object_name, _, member = target.partition(".")
        if member:
            names = cls._decidable_targets(target)
            return [name for name in names if name.casefold() not in live_names], []
        if not cls._local_custom_name(target) or target.casefold() in live_names:
            return [], []
        if not heuristic:
            # A declared edge names what its kind says it names — a lookup's `relationship`
            # target is an object — so absence from the live component names settles it, and a
            # field that happens to share the name cannot stand in for the deleted object.
            return [target], []
        if target.casefold() in live_members:
            return [], []
        return [], [target]

    def entry_edge_health(self, live_component_ids: set[str]) -> dict[str, Any]:
        """Rot in the entry-side relation graph, which the claim-side check cannot see.

        relation_health only inspects `verified` relation CLAIMS. For the ten entry-home types
        there will never be any, so it reported HEALTHY unconditionally while entry edges went
        stale underneath it — a clean bill of health over an unexamined graph.

        The orphan diff mirrors the claim-side one: an entry is append-only, so deleting the
        object a field belongs to, or the class a trigger invokes, removes nothing from the
        entry that points at it. `live_component_ids` is the same live set the claim-side diff
        is computed against, and the reasons are the claim side's words so the two halves of
        one report read as one report.

        Lanes are computed, never read: contract §4 is explicit that reading `lifecycle.state`
        out of frontmatter does not establish approval. A file saying `approved` with no ledger
        record is precisely the case that check exists to catch — so `not-effective` is
        inspected too, and reports what compute_lane refused it for.
        """

        try:
            from scripts.knowledge_store import (  # local import: keeps the CLI standalone
                all_entry_paths, compute_lane, ledger_latest, read_ledger, rooted, split_entry,
            )
        except ModuleNotFoundError:
            from knowledge_store import (  # type: ignore
                all_entry_paths, compute_lane, ledger_latest, read_ledger, rooted, split_entry,
            )

        live_names = {
            component_id.split(":", 1)[1].casefold() for component_id in live_component_ids
        }
        # A field lives under `Object.Field`; the token a regex extractor emits for it does not.
        # This is the index that lets a bare token be settled at all — see _edge_target_verdict.
        live_members = {name.rpartition(".")[2] for name in live_names if "." in name}
        by_lane: Counter[str] = Counter()
        findings: list[dict[str, Any]] = []
        undecidable: set[tuple[str, str, str]] = set()
        with rooted(self.root):
            latest = ledger_latest(read_ledger())
            for path in all_entry_paths():
                try:
                    lane = compute_lane(path, latest)
                    frontmatter, _body = split_entry(path.read_text(encoding="utf-8"))
                except Exception as error:  # unparsable entry is itself a finding
                    findings.append({"path": str(path), "reason": f"entry does not parse: {error}"})
                    continue
                by_lane[lane["lane"]] += 1
                if lane["lane"] in {"draft", "revoked"}:
                    # Unfinished work and deliberately retired knowledge are not corruption.
                    continue
                row = {
                    "path": lane["path"], "identity": lane["identity"],
                    "lifecycleState": lane["lane"],
                }
                for problem in lane["problems"]:
                    findings.append({**row, "reason": problem})
                if lane["lane"] not in {"approved-current", "approved-drifted"}:
                    # An entry the ledger does not stand behind is already reported above; its
                    # edges are not worth diffing, because the entry itself is not trusted.
                    continue
                subject = frontmatter["subject"]
                component_id = f"{subject['metadataType']}:{subject['fullName']}"
                if component_id not in live_component_ids:
                    findings.append({**row, "reason": "component removed"})
                    continue
                for reference in frontmatter.get("typeFacts", {}).get("references", []) or []:
                    kind = str(reference["kind"])
                    # The stored marker is authoritative — it is inside factsDigest, so it is what
                    # a human approved. edge_assurance only fills in for an entry written before
                    # the field existed, using the same rule that stamped the others.
                    assurance = str(
                        reference.get("assurance")
                        or edge_assurance(kind, bool(reference.get("heuristic")))
                    )
                    missing, ambiguous = self._edge_target_verdict(
                        str(reference["target"]),
                        assurance == SOURCE_DERIVED_HEURISTIC,
                        live_names,
                        live_members,
                    )
                    for name in ambiguous:
                        undecidable.add((lane["identity"], kind, name))
                    for name in missing:
                        # Same two reason strings the claim-side orphan list uses, so one report
                        # does not speak two dialects; `missingComponent` says which end went.
                        findings.append(
                            {**row, "reason": "edge no longer present in source",
                             "kind": kind, "target": reference["target"],
                             "missingComponent": name, "assurance": assurance}
                        )
        return {
            "entriesByLane": dict(sorted(by_lane.items())),
            "findingCount": len(findings),
            "findings": sorted(
                findings,
                key=lambda item: (item.get("path", ""), item.get("target", ""), item["reason"]),
            ),
            "note": (
                "Lanes are computed from the ledger, not read from frontmatter. Drafts and "
                "revoked entries are skipped; every other entry is checked for integrity, and "
                "approved ones also have their stored edges diffed against live source. Only "
                "package-local targets (__c/__e/__mdt/__b/__x, unnamespaced) are decidable: a "
                "standard object, a system permission or a bare Apex name is absent from "
                "force-app by nature, so its absence is never reported as rot. "
                + self._undecidable_note(undecidable)
            ),
        }

    # How many undecidable targets the note names before it stops. A disclosure has to stay
    # readable to be read at all — the defect this whole check is recovering from was 164 rows
    # nobody could get through.
    UNDECIDABLE_NOTE_SAMPLE = 5

    @classmethod
    def _undecidable_note(cls, undecidable: set[tuple[str, str, str]]) -> str:
        """The disclosed-population sentence: what the diff refused to decide, and why.

        The count is stated even when it is zero. A disclosure that appears only when non-empty
        cannot be told apart from a build where nothing was disclosed because nothing was looked
        at, which is the failure this file already made once.
        """

        if not undecidable:
            return (
                "0 approved-entry edge targets were left undecidable: every bare package-local "
                "target matched a live component or a live field."
            )
        names = sorted({name for _identity, _kind, name in undecidable})
        shown = ", ".join(names[: cls.UNDECIDABLE_NOTE_SAMPLE])
        if len(names) > cls.UNDECIDABLE_NOTE_SAMPLE:
            shown += f", … ({len(names) - cls.UNDECIDABLE_NOTE_SAMPLE} more)"
        return (
            f"{len(undecidable)} approved-entry edge target(s) across {len(names)} name(s) are "
            "UNDECIDABLE and are disclosed rather than counted: a bare package-local name reached "
            "through a heuristic extractor may be an object, a field on any object, or a token "
            "the regex read out of a string literal, so its absence supports no claim in either "
            f"direction. Names: {shown}."
        )

    def entry_edge_report(self) -> dict[str, Any]:
        """Read-only rot report for the approved-entry relation graph.

        The live set comes from a fresh inventory, exactly the diff basis the retired
        claim-side relation-health used, so orphan reasons stay comparable over time."""

        inventory = self.inventory()
        live = {component["id"] for component in inventory.get("components", [])}
        return self.entry_edge_health(live)

    ENTRY_READINESS_SAMPLE_CAP = 50

    def entry_readiness(self) -> dict[str, Any]:
        """Which live components of entry-homed types carry a Knowledge Entry, per lane.

        The denominator is live entry-profiled components — the v1 `coverage` command divided
        claim-documented components by a claims worklist, and mistaking one denominator for
        the other is how a fully-approved entry store once read as 0% documented."""

        inventory = self.inventory()
        draftable = self.entry_draftable_types()
        entries = self.entry_descriptions()
        by_type: dict[str, dict[str, Any]] = {}
        missing: list[dict[str, str]] = []
        undescribed: list[dict[str, str]] = []
        for component in inventory.get("components", []):
            metadata_type = component["metadataType"]
            if metadata_type not in draftable:
                continue
            bucket = by_type.setdefault(
                metadata_type, {"components": 0, "byLane": Counter(), "noEntry": 0, "undescribed": 0}
            )
            bucket["components"] += 1
            entry = entries.get(component["id"])
            if entry is None:
                bucket["noEntry"] += 1
                missing.append(
                    {"componentId": component["id"], "metadataType": metadata_type}
                )
            else:
                bucket["byLane"][str(entry["lane"])] += 1
                # A drafted entry whose Purpose is still the sentinel is a different debt
                # than a missing entry — the remedy is `entry-describe`, not `entry-draft`.
                # Measured live (KM-16D, 2026-08-06): reporting only `documentNext: 0` on a
                # 527-draft store read as "nothing awaits description" to the very agent this
                # report steers.
                if not entry.get("purpose"):
                    bucket["undescribed"] += 1
                    undescribed.append(
                        {"componentId": component["id"], "metadataType": metadata_type}
                    )
        missing.sort(key=lambda row: (row["metadataType"], row["componentId"]))
        undescribed.sort(key=lambda row: (row["metadataType"], row["componentId"]))
        return {
            "kind": "force-app-entry-readiness",
            "generatedAt": iso(utc_now()),
            "repositoryCommit": inventory["repositoryCommit"],
            "byMetadataType": {
                name: {
                    "components": bucket["components"],
                    "byLane": dict(sorted(bucket["byLane"].items())),
                    "noEntry": bucket["noEntry"],
                    "undescribed": bucket["undescribed"],
                }
                for name, bucket in sorted(by_type.items())
            },
            "totals": {
                "components": sum(b["components"] for b in by_type.values()),
                "withEntry": sum(sum(b["byLane"].values()) for b in by_type.values()),
                "noEntry": sum(b["noEntry"] for b in by_type.values()),
                "undescribed": sum(b["undescribed"] for b in by_type.values()),
            },
            "documentNext": missing[: self.ENTRY_READINESS_SAMPLE_CAP],
            "documentNextTruncated": max(0, len(missing) - self.ENTRY_READINESS_SAMPLE_CAP),
            "describeNext": undescribed[: self.ENTRY_READINESS_SAMPLE_CAP],
            "describeNextTruncated": max(0, len(undescribed) - self.ENTRY_READINESS_SAMPLE_CAP),
            "basis": (
                "live entry-profiled force-app components against Knowledge Entry lanes; "
                "`documentNext` lists components with NO entry (remedy: entry-draft), "
                "`describeNext` lists drafted entries still holding the description sentinel "
                "(remedy: entry-describe); `entry-edge-health` answers whether edge targets "
                "still exist in source."
            ),
        }

    # Metadata types with an implemented one-file Knowledge Entry profile — the set the
    # entry lanes (resolve, entry-readiness) divide the live source by.
    def entry_home_types(self) -> frozenset[str]:
        artifacts_root = self.root / ".ai/knowledge/artifacts"
        if not artifacts_root.is_dir() or not any(artifacts_root.rglob("*.md")):
            return frozenset()
        try:
            from scripts.knowledge_store import PROFILES
        except ModuleNotFoundError:  # invoked as a script
            from knowledge_store import PROFILES  # type: ignore
        return frozenset(PROFILES)

    @staticmethod
    def component_objects(
        component: dict[str, Any], known_objects: set[str] | None = None
    ) -> set[str]:
        """Objects a component touches: its object folder, name/reference associations.

        Combines three source-grounded signals so the crawl associates each component with the
        objects it belongs to: (1) the `objects/<Object>/…` folder it lives in (fields, validation
        rules, record types, list views); (2) a naming convention for object-scoped surfaces
        (`Object-Layout` layouts, and tabs whose name matches a repository custom object — web,
        Visualforce, and FlexiPage tabs share the CustomTab type but name no object, so the tab
        association is gated on `known_objects` when provided); (3) reference edges parsed from the
        source (a Flow's `operates-on`, an Apex object token, an LWC `@salesforce/schema` import,
        a formula's resolved `__r` chain, a roll-up's summarized field). It never guesses beyond
        what the source shows — FlexiPage associations are not derivable here and are reported as
        a crawl limitation.
        """

        objects: set[str] = set()
        path = component["path"]
        if "/objects/" in path:
            objects.add(path.split("/objects/", 1)[1].split("/", 1)[0])
        metadata_type = component["metadataType"]
        if metadata_type == "Layout":
            objects.add(component["name"].split("-", 1)[0])
        elif metadata_type == "CustomTab" and (
            known_objects is None or component["name"] in known_objects
        ):
            objects.add(component["name"])
        for reference in component["references"]:
            if reference["kind"] in OBJECT_REF_KINDS:
                objects.add(reference["target"].split(".", 1)[0])
        return {name for name in objects if name}

    def entry_descriptions(self) -> dict[str, dict[str, str]]:
        """`<MetadataType>:<FullName>` -> the entry's Purpose prose and its computed lane.

        An undescribed entry is kept with an empty `purpose` rather than dropped. Dropping it
        made the dossier indistinguishable from "no entry exists", and the two states have
        different remedies — `entry-describe` against `entry-draft`.
        """

        try:
            from scripts.knowledge_store import (
                all_entry_paths, compute_lane, ledger_latest, read_ledger, rooted, split_entry,
            )
        except ModuleNotFoundError:
            from knowledge_store import (  # type: ignore
                all_entry_paths, compute_lane, ledger_latest, read_ledger, rooted, split_entry,
            )

        found: dict[str, dict[str, str]] = {}
        with rooted(self.root):
            latest = ledger_latest(read_ledger())
            for path in all_entry_paths():
                try:
                    lane = compute_lane(path, latest)
                    frontmatter, body = split_entry(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                purpose = ""
                for block in body.split("## "):
                    if block.startswith("Purpose"):
                        purpose = block[len("Purpose"):].strip()
                        break
                if purpose.startswith("<AGENT_"):
                    purpose = ""  # the draft sentinel is an absence, not a description
                subject = frontmatter["subject"]
                found[f"{subject['metadataType']}:{subject['fullName']}"] = {
                    "purpose": purpose, "lane": lane["lane"],
                }
        return found

    def entry_draftable_types(self) -> set[str]:
        """Metadata types `entry-draft` will accept, from the store's own profile table.

        Read rather than restated: `entry-draft` refuses every other type, so a dossier that
        told a reader to draft an entry for a Layout would be naming a command that fails.

        Deliberately NOT `entry_home_types`: that one answers a different question — whether
        this repo has entries yet, and therefore whether drafting a repository claim would be
        dead work. Naming both the same shadowed the gated one and made `draft()` skip every
        entry-profiled component in a repo with zero entries, which is every repo today.
        """

        try:
            from scripts.knowledge_store import PROFILES
        except ModuleNotFoundError:
            from knowledge_store import PROFILES  # type: ignore
        return set(PROFILES)



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    resolve = commands.add_parser(
        "resolve",
        help="map file paths / component names onto inventory components with lane and "
        "documentation status (read-only)",
    )
    resolve.add_argument(
        "--path",
        action="append",
        default=[],
        help="a force-app file or directory path to resolve; repeatable",
    )
    resolve.add_argument(
        "--name",
        action="append",
        default=[],
        help="a component name, id, or source-file basename to resolve; repeatable",
    )
    resolve.add_argument(
        "--write",
        action="store_true",
        help="also save the resolution under .cache/knowledge-proposals/",
    )
    commands.add_parser(
        "entry-readiness",
        help="entry-side coverage: live entry-profiled components against entry lanes (read-only)",
    )
    commands.add_parser(
        "entry-edge-health",
        help="rot report for the approved-entry relation graph against live source (read-only)",
    )
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
        elif args.command == "resolve":
            result = builder.resolve(args.path, args.name, args.write)
            # The selections ARE the output: a caller resolving three pinned files must not
            # need --write plus a file read to learn what they mapped to.
            summary = {
                "counts": result["counts"],
                "entryHomeActive": result["entryHomeActive"],
                "selections": result["selections"],
                "components": result["components"],
            }
            if "path" in result:
                summary["path"] = result["path"]
        elif args.command == "entry-readiness":
            result = builder.entry_readiness()
            summary = {
                "totals": result["totals"],
                "documentNext": len(result["documentNext"]),
                "documentNextTruncated": result["documentNextTruncated"],
                "describeNext": len(result["describeNext"]),
                "describeNextTruncated": result["describeNextTruncated"],
            }
        elif args.command == "entry-edge-health":
            result = builder.entry_edge_report()
            summary = {
                "findingCount": result["findingCount"],
                "entriesByLane": result["entriesByLane"],
            }
    except (KnowledgeBuildError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
