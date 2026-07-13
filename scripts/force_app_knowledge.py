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


class ForceAppKnowledge:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()
        self.source_root = self.root / "force-app"
        self.cache_root = self.root / ".cache/knowledge-proposals"
        self.inventory_path = self.cache_root / "force-app-inventory.json"
        self.draft_root = self.cache_root / "force-app-drafts"

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

    def candidate_claims(self, component: dict[str, Any]) -> list[dict[str, Any]]:
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
        elif metadata_type in {"Flow", "ApexClass", "ApexTrigger"}:
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
                    "limitations": [common_limit, "Runtime paths, order of execution, and side effects are not established."],
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
        return candidates

    def draft(self, observed_at: datetime) -> dict[str, Any]:
        inventory = self.load_inventory()
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
            candidates = self.candidate_claims(component)
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
                "independenceKey": f"metadata-repository:{commit}",
                "authorityFor": authority_for,
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageKey": None,
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
                    "pagesFetched": 1,
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
                claim_id = stable_id(
                    "KCLM",
                    candidate["subject"]["identity"],
                    f"{candidate['claimType']}|{candidate['assertion']['predicate']}",
                )
                current_path = self.root / ".ai/knowledge/claims" / f"{claim_id}.yaml"
                expected_revision = 0
                revision = 1
                disposition = "new"
                if current_path.is_file():
                    current = yaml.safe_load(current_path.read_text(encoding="utf-8"))
                    if current.get("status") != "proposed":
                        bundles.append(
                            {
                                "claimId": claim_id,
                                "disposition": "existing-non-proposed",
                                "reason": f"existing status is {current.get('status')}",
                            }
                        )
                        continue
                    expected_revision = int(current["revision"])
                    revision = expected_revision + 1
                    disposition = "update-proposed"
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
                    "polarity": "positive",
                    "status": "proposed",
                    "assurance": "observed",
                    "scope": {
                        "environment": "not-applicable",
                        "orgKey": None,
                        "packageNamespace": None,
                        "packageKey": None,
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
                    "limitations": candidate["limitations"],
                    "supersedes": [],
                    "supersededBy": None,
                    "contradicts": [],
                    "relatedClaims": [],
                }
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
                            f".venv/bin/python scripts/knowledge_registry.py propose --claim-file {self.relative(claim_path)} "
                            f"--evidence-file {self.relative(evidence_path)} --expected-revision {expected_revision}"
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    draft = commands.add_parser("draft")
    draft.add_argument("--observed-at")
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
        else:
            observed_at = parse_time(args.observed_at) if args.observed_at else utc_now()
            result = builder.draft(observed_at)
            summary = {
                "path": builder.relative(builder.draft_root / "manifest.json"),
                "claims": result["claimCount"],
                "reviewStatus": result["reviewStatus"],
            }
    except (KnowledgeBuildError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
