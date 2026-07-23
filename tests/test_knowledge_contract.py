from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from scripts.knowledge_registry import (
    ContractError,
    KnowledgeRegistry,
    canonical_digest,
    file_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals/fixtures"
SCHEMA_FILES = (
    "knowledge-claim.schema.json",
    "knowledge-evidence.schema.json",
    "knowledge-review.schema.json",
    "knowledge-claims-index.schema.json",
    "principle-registry.schema.json",
    "knowledge-policy.schema.json",
    "force-app-knowledge-draft-manifest.schema.json",
)
DOMAIN_FILES = (
    "current-implementation.md",
    "business-processes.md",
    "object-relations.md",
    "object-descriptions.md",
    "field-descriptions.md",
    "automation-map.md",
    "integration-map.md",
    "glossary.md",
    "known-limitations.md",
    "component-inventory.md",
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class KnowledgeSchemaTests(unittest.TestCase):
    def validator(self, name: str) -> Draft202012Validator:
        schema = load_json(ROOT / "schemas" / name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def assert_valid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertEqual([], errors, [error.message for error in errors])

    def assert_invalid(self, fixture: str, schema: str) -> None:
        errors = list(self.validator(schema).iter_errors(load_yaml(FIXTURES / fixture)))
        self.assertTrue(errors, f"{fixture} was incorrectly accepted")

    def test_schemas_are_valid(self) -> None:
        for name in SCHEMA_FILES:
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(load_json(ROOT / "schemas" / name))

    def test_positive_knowledge_fixtures(self) -> None:
        self.assert_valid("knowledge-evidence.complete.yaml", "knowledge-evidence.schema.json")
        self.assert_valid("knowledge-claim.proposed.yaml", "knowledge-claim.schema.json")
        self.assert_valid("knowledge-claim.verified.yaml", "knowledge-claim.schema.json")
        self.assert_valid("knowledge-review.verify.yaml", "knowledge-review.schema.json")

    def test_v3_fixtures_are_current_for_the_2026_07_10_baseline(self) -> None:
        for fixture in (
            "knowledge-evidence.complete.yaml",
            "knowledge-claim.proposed.yaml",
            "knowledge-claim.verified.yaml",
            "knowledge-review.verify.yaml",
        ):
            with self.subTest(fixture=fixture):
                self.assertEqual(3, load_yaml(FIXTURES / fixture)["schemaVersion"])
        claim = load_yaml(FIXTURES / "knowledge-claim.verified.yaml")
        baseline = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        review_by = datetime.fromisoformat(claim["reviewBy"].replace("Z", "+00:00"))
        self.assertGreater(review_by, baseline)

    def test_structural_object_assertions_reject_semantic_shape_shifting(self) -> None:
        validator = self.validator("knowledge-claim.schema.json")
        existence = load_yaml(FIXTURES / "knowledge-claim.proposed.yaml")
        existence["assertion"]["predicate"] = "looks-like-it-exists"
        self.assertTrue(list(validator.iter_errors(existence)))

        ownership = load_yaml(FIXTURES / "knowledge-claim.proposed.yaml")
        ownership["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-OWNERSHIP-001"
        ownership["claimType"] = "object-ownership"
        ownership["assertion"] = {
            "predicate": "ownership-classification",
            "value": "package-owned",
        }
        self.assertEqual([], list(validator.iter_errors(ownership)))

        invented = copy.deepcopy(ownership)
        invented["assertion"]["value"] = "probably-package-owned"
        self.assertTrue(list(validator.iter_errors(invented)))

        subscriber_with_package_scope = copy.deepcopy(ownership)
        subscriber_with_package_scope["assertion"]["value"] = "subscriber-owned"
        self.assertTrue(list(validator.iter_errors(subscriber_with_package_scope)))

        package_without_namespace = copy.deepcopy(ownership)
        package_without_namespace["scope"]["packageNamespace"] = None
        self.assertTrue(list(validator.iter_errors(package_without_namespace)))

    def test_query_cli_is_executable_and_requires_a_filter(self) -> None:
        command = [sys.executable, "scripts/knowledge_registry.py", "query"]
        denied = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, denied.returncode)
        self.assertIn("requires at least one Knowledge filter", denied.stdout)

        accepted = subprocess.run(
            command + ["--domain", "object-descriptions", "--at", "2026-07-10T12:00:00Z"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        self.assertEqual(0, json.loads(accepted.stdout)["count"])

    def test_invalid_promotion_and_raw_data_are_rejected(self) -> None:
        self.assert_invalid(
            "knowledge-claim.invalid-verified-without-review.yaml",
            "knowledge-claim.schema.json",
        )
        self.assert_invalid(
            "knowledge-evidence.invalid-raw.yaml", "knowledge-evidence.schema.json"
        )
        self.assert_invalid(
            "knowledge-review.invalid-model-reviewer.yaml",
            "knowledge-review.schema.json",
        )

    def test_policy_is_schema_valid_and_covers_every_claim_type(self) -> None:
        policy = load_json(ROOT / "config/knowledge-policy.json")
        errors = list(
            self.validator("knowledge-policy.schema.json").iter_errors(policy)
        )
        self.assertEqual([], errors, [error.message for error in errors])
        claim_schema = load_json(ROOT / "schemas/knowledge-claim.schema.json")
        claim_types = set(claim_schema["$defs"]["claimType"]["enum"])
        self.assertEqual(claim_types, set(policy["claimPolicies"]))
        evidence_schema = load_json(ROOT / "schemas/knowledge-evidence.schema.json")
        source_types = set(evidence_schema["properties"]["sourceType"]["enum"])
        for name, claim_policy in policy["claimPolicies"].items():
            with self.subTest(claimType=name):
                self.assertLessEqual(set(claim_policy["allowedEvidenceTypes"]), source_types)

    def test_rule_registry_matches_generic_runtime_rule_ids(self) -> None:
        registry = load_yaml(ROOT / ".github/instructions/rule-registry.yaml")
        errors = list(
            self.validator("principle-registry.schema.json").iter_errors(registry)
        )
        self.assertEqual([], errors, [error.message for error in errors])
        source_files = (
            ROOT / ".github/copilot-instructions.md",
            ROOT / ".github/instructions/managed-package-constraints.instructions.md",
            ROOT / ".github/instructions/organization-principles.instructions.md",
            ROOT / ".github/instructions/salesforce-best-practices.instructions.md",
        )
        source_ids: set[str] = set()
        pattern = re.compile(r"\*\*((?:SAFE|MP|ORG|SF)-[A-Z0-9-]+)\s+—")
        for path in source_files:
            source_ids.update(pattern.findall(path.read_text(encoding="utf-8")))
        expected = {rule_id for rule_id in source_ids if not rule_id.startswith("MP-INV-")}
        actual = [rule["ruleId"] for rule in registry["rules"]]
        self.assertEqual(expected, set(actual))
        self.assertEqual(len(actual), len(set(actual)))
        self.assertFalse(any(rule_id.startswith("MP-INV-") for rule_id in actual))

    def test_live_knowledge_has_no_unverified_example_or_canonical_fact(self) -> None:
        relations = (ROOT / ".ai/knowledge/object-relations.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Invoice__c", relations)
        self.assertNotIn("ExampleManagedObject__c", relations)
        for directory in ("claims", "evidence", "reviews"):
            files = [
                path.name
                for path in (ROOT / ".ai/knowledge" / directory).iterdir()
                if path.is_file()
            ]
            self.assertEqual([".gitkeep"], files)
        for filename in DOMAIN_FILES:
            text = (ROOT / ".ai/knowledge" / filename).read_text(encoding="utf-8")
            self.assertIn("BEGIN GENERATED CLAIM INDEX", text)
            self.assertIn("END GENERATED CLAIM INDEX", text)


class KnowledgeRegistryWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="knowledge-registry-test-")
        self.root = Path(self.temporary.name)
        (self.root / "schemas").mkdir()
        for name in SCHEMA_FILES:
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "config").mkdir()
        shutil.copy2(
            ROOT / "config/knowledge-policy.json",
            self.root / "config/knowledge-policy.json",
        )
        (self.root / ".github/instructions").mkdir(parents=True)
        shutil.copy2(
            ROOT / ".github/copilot-instructions.md",
            self.root / ".github/copilot-instructions.md",
        )
        for source in (ROOT / ".github/instructions").glob("*.instructions.md"):
            shutil.copy2(source, self.root / ".github/instructions" / source.name)
        shutil.copy2(
            ROOT / ".github/instructions/rule-registry.yaml",
            self.root / ".github/instructions/rule-registry.yaml",
        )
        for directory in ("claims", "evidence", "reviews"):
            (self.root / ".ai/knowledge" / directory).mkdir(parents=True, exist_ok=True)
        for filename in DOMAIN_FILES:
            target = self.root / ".ai/knowledge" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / ".ai/knowledge" / filename, target)
        (self.root / "inputs").mkdir()
        for fixture in (
            "knowledge-evidence.complete.yaml",
            "knowledge-claim.proposed.yaml",
            "knowledge-review.verify.yaml",
        ):
            shutil.copy2(FIXTURES / fixture, self.root / "inputs" / fixture)
        self.registry = KnowledgeRegistry(
            self.root,
            current_time=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def propose(self) -> dict:
        return self.registry.propose(
            self.root / "inputs/knowledge-claim.proposed.yaml",
            [self.root / "inputs/knowledge-evidence.complete.yaml"],
            expected_revision=0,
        )

    def promote(self) -> dict:
        self.propose()
        self.registry.record_review(
            self.root / "inputs/knowledge-review.verify.yaml"
        )
        return self.registry.promote(
            "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001",
            "KREV-EXAMPLEMANAGEDOBJECT-VERIFY-001",
            expected_revision=1,
        )

    @staticmethod
    def bind_review(review: dict, claim: dict, evidence: list[dict]) -> None:
        review.update(KnowledgeRegistry.review_bindings(claim, evidence))
        receipt = copy.deepcopy(review["auditReceipt"])
        receipt.pop("receiptDigest", None)
        review["auditReceipt"]["receiptDigest"] = canonical_digest(receipt)

    def test_propose_validate_review_promote_flow(self) -> None:
        proposed = self.propose()
        self.assertEqual("proposed", proposed["status"])
        self.assertEqual(
            {"claims": 1, "evidence": 1, "reviews": 0, "rules": 50},
            self.registry.validate_all(),
        )
        review = self.registry.record_review(
            self.root / "inputs/knowledge-review.verify.yaml"
        )
        self.assertEqual("verify", review["decision"])
        promoted = self.registry.promote(
            "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001",
            "KREV-EXAMPLEMANAGEDOBJECT-VERIFY-001",
            expected_revision=1,
        )
        self.assertEqual({"claimId": "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", "status": "verified", "revision": 2}, promoted)
        claim = load_yaml(
            self.root
            / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        self.assertEqual("verified", claim["status"])
        self.assertEqual("KREV-EXAMPLEMANAGEDOBJECT-VERIFY-001", claim["reviewRef"])
        self.assertEqual(
            {"claims": 1, "evidence": 1, "reviews": 1, "rules": 50},
            self.registry.validate_all(),
        )

    def write_chat_reviewer(self, value: str = "Jan Kowalski") -> None:
        (self.root / "config/harness.local.json").write_text(
            json.dumps({"knowledge": {"chatReviewer": value}}), encoding="utf-8"
        )

    def test_approve_claim_chat_verify_promotes_and_renders(self) -> None:
        self.propose()
        self.write_chat_reviewer()
        result = self.registry.approve_claim("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", 1)
        self.assertEqual("verified", result["status"])
        self.assertEqual(2, result["revision"])
        self.assertEqual("copilot-chat-confirmation", result["mechanism"])
        claim = load_yaml(
            self.root / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        self.assertEqual("verified", claim["status"])
        self.assertEqual(result["reviewId"], claim["reviewRef"])
        review = load_yaml(
            self.root / f".ai/knowledge/reviews/{result['reviewId']}.yaml"
        )
        self.assertEqual({"type": "human", "identity": "Jan Kowalski"}, review["reviewer"])
        self.assertEqual(
            "copilot-chat-confirmation", review["auditReceipt"]["mechanism"]
        )
        rendered = (self.root / ".ai/knowledge/object-descriptions.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", rendered)

    def test_approve_claim_chat_reject_binds_review(self) -> None:
        self.propose()
        self.write_chat_reviewer()
        result = self.registry.approve_claim(
            "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", 1, decision="reject"
        )
        self.assertEqual("rejected", result["status"])
        claim = load_yaml(
            self.root / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        self.assertEqual("rejected", claim["status"])
        self.assertEqual(result["reviewId"], claim["reviewRef"])

    def test_filled_description_claim_flows_to_verified_inferred(self) -> None:
        commit = "a" * 40
        evidence = {
            "schemaVersion": 3,
            "evidenceId": "KEVD-DESC-FLOW-001",
            "sourceType": "metadata-repository",
            "sourceLocator": f"git://{commit}/force-app/main/default/flows/Example.flow-meta.xml",
            "independenceKey": f"metadata-repository:{commit}",
            "authorityFor": ["component-description"],
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageKey": None,
            "packageVersion": None,
            "repositoryCommit": commit,
            "observedAt": "2026-07-10T11:00:00Z",
            "retrievedAt": "2026-07-10T11:00:00Z",
            "sourceRevision": f"sha256:{'b' * 64}",
            "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": "2"},
            "completeness": {
                "status": "complete",
                "enumerationComplete": False,
                "permissionsProven": False,
                "pagesFetched": 1,
                "missingSegments": [],
            },
            "sensitivity": "internal-sanitized",
            "sanitization": {"rawDataCommitted": False, "redactions": []},
            "contentDigest": f"sha256:{'c' * 64}",
            "summary": "Sanitized source observation of Flow:Example.",
        }
        claim = {
            "schemaVersion": 3,
            "claimId": "KCLM-DESC-FLOW-001",
            "revision": 1,
            "domain": "automation-map",
            "claimType": "component-description",
            "subject": {"kind": "component", "identity": "Flow:Example"},
            "assertion": {
                "predicate": "describes-source-declared-behavior",
                "value": {
                    "metadataType": "Flow",
                    "description": (
                        "Record-triggered flow on Engagement__c that runs after save when Status__c "
                        "changes to Approved, updates the related Account rating, and sends a "
                        "notification to the record owner."
                    ),
                },
            },
            "statement": "Model-inferred, human-reviewed description of what Flow:Example does according to its source.",
            "polarity": "positive",
            "status": "proposed",
            "assurance": "inferred",
            "scope": {
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageKey": None,
                "packageVersion": None,
                "repositoryCommit": commit,
            },
            "evidenceRefs": ["KEVD-DESC-FLOW-001"],
            "reviewRef": None,
            "observedAt": "2026-07-10T11:00:00Z",
            "verifiedAt": None,
            "reviewBy": "2027-01-06T11:00:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": [],
            "limitations": ["The description interprets source only."],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
            "relatedClaims": [],
        }
        (self.root / "inputs/desc-claim.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        (self.root / "inputs/desc-evidence.yaml").write_text(
            yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8"
        )
        proposed = self.registry.propose(
            self.root / "inputs/desc-claim.yaml",
            [self.root / "inputs/desc-evidence.yaml"],
            expected_revision=0,
        )
        self.assertEqual("proposed", proposed["status"])
        self.write_chat_reviewer()
        result = self.registry.approve_claim("KCLM-DESC-FLOW-001", 1)
        self.assertEqual("verified", result["status"])
        promoted = load_yaml(self.root / ".ai/knowledge/claims/KCLM-DESC-FLOW-001.yaml")
        self.assertEqual("verified", promoted["status"])
        self.assertEqual("inferred", promoted["assurance"])
        rendered = (self.root / ".ai/knowledge/automation-map.md").read_text(encoding="utf-8")
        self.assertIn("KCLM-DESC-FLOW-001", rendered)

    def test_trimmed_usage_claim_is_searchable_by_object_and_field(self) -> None:
        # A claim authored WITHOUT the now-optional fields (polarity, packageKey, relatedClaims,
        # evidence independenceKey/pagesFetched) still proposes, promotes, and renders — and its
        # usage registry is searchable by object and by field.
        commit = "a" * 40
        evidence = {
            "schemaVersion": 3,
            "evidenceId": "KEVD-FLOW-ROUTER-001",
            "sourceType": "metadata-repository",
            "sourceLocator": f"git://{commit}/force-app/main/default/flows/EngagementRouter.flow-meta.xml",
            "authorityFor": ["automation-inventory"],
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageVersion": None,
            "repositoryCommit": commit,
            "observedAt": "2026-07-10T11:00:00Z",
            "retrievedAt": "2026-07-10T11:00:00Z",
            "sourceRevision": f"sha256:{'b' * 64}",
            "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": "2"},
            "completeness": {
                "status": "complete",
                "enumerationComplete": False,
                "permissionsProven": False,
                "missingSegments": [],
            },
            "sensitivity": "internal-sanitized",
            "sanitization": {"rawDataCommitted": False, "redactions": []},
            "contentDigest": f"sha256:{'c' * 64}",
            "summary": "Sanitized source observation of Flow:EngagementRouter.",
        }
        claim = {
            "schemaVersion": 3,
            "claimId": "KCLM-FLOW-ROUTER-001",
            "revision": 1,
            "domain": "automation-map",
            "claimType": "automation-inventory",
            "subject": {"kind": "automation", "identity": "EngagementRouter"},
            "assertion": {
                "predicate": "source-defined-automation",
                "value": {
                    "metadataType": "Flow",
                    "facts": {"object": "Engagement__c", "referencedObjects": ["Account", "Engagement__c"]},
                    "references": [
                        {"kind": "operates-on", "target": "Engagement__c"},
                        {"kind": "reads-field", "target": "Account.Name"},
                        {"kind": "writes-field", "target": "Engagement__c.Status__c"},
                        {"kind": "invokes-apex", "target": "EngagementNotifier"},
                    ],
                },
            },
            "statement": "EngagementRouter is a source-defined Flow component at the repository commit.",
            "status": "proposed",
            "assurance": "observed",
            "scope": {
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageVersion": None,
                "repositoryCommit": commit,
            },
            "evidenceRefs": ["KEVD-FLOW-ROUTER-001"],
            "reviewRef": None,
            "observedAt": "2026-07-10T11:00:00Z",
            "verifiedAt": None,
            "reviewBy": "2026-12-01T11:00:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": [],
            "candidateKeywords": ["engagement"],
            "limitations": ["Repository metadata establishes intended source only."],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
        }
        (self.root / "inputs/flow-claim.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        (self.root / "inputs/flow-evidence.yaml").write_text(
            yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8"
        )
        proposed = self.registry.propose(
            self.root / "inputs/flow-claim.yaml",
            [self.root / "inputs/flow-evidence.yaml"],
            expected_revision=0,
        )
        self.assertEqual("proposed", proposed["status"])
        self.write_chat_reviewer()
        self.assertEqual("verified", self.registry.approve_claim("KCLM-FLOW-ROUTER-001", 1)["status"])

        by_object = self.registry.query(uses_object="Engagement__c")
        self.assertEqual(1, by_object["count"])
        self.assertEqual("KCLM-FLOW-ROUTER-001", by_object["claims"][0]["claim"]["claimId"])
        self.assertEqual(1, self.registry.query(uses_field="Account.Name")["count"])
        self.assertEqual(1, self.registry.query(invokes="EngagementNotifier")["count"])
        self.assertEqual(0, self.registry.query(uses_object="Contact")["count"])

        index = load_json(self.root / ".ai/knowledge/claims-index.json")
        row = next(r for r in index["claims"] if r["claimId"] == "KCLM-FLOW-ROUTER-001")
        self.assertEqual(["Account", "Engagement__c"], row["usesObjects"])
        self.assertIn("Engagement__c.Status__c", row["usesFields"])
        self.assertNotIn("emitsErrors", row)
        automation_map = (self.root / ".ai/knowledge/automation-map.md").read_text(encoding="utf-8")
        self.assertIn("## Automations by object", automation_map)

    def test_error_catalog_claim_is_searchable_by_pasted_error_message(self) -> None:
        # A Flow claim carrying facts.errorCatalog: a user-pasted error message must rank the
        # emitting automation via --search, and the claims index must expose emitsErrors.
        commit = "a" * 40
        evidence = {
            "schemaVersion": 3,
            "evidenceId": "KEVD-FLOW-GUARD-001",
            "sourceType": "metadata-repository",
            "sourceLocator": f"git://{commit}/force-app/main/default/flows/DiscountGuard.flow-meta.xml",
            "authorityFor": ["automation-inventory"],
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageVersion": None,
            "repositoryCommit": commit,
            "observedAt": "2026-07-10T11:00:00Z",
            "retrievedAt": "2026-07-10T11:00:00Z",
            "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": "1.2.0"},
            "completeness": {
                "status": "complete",
                "enumerationComplete": False,
                "permissionsProven": False,
                "missingSegments": [],
            },
            "sensitivity": "internal-sanitized",
            "sanitization": {"rawDataCommitted": False, "redactions": []},
            "contentDigest": f"sha256:{'c' * 64}",
            "summary": "Sanitized source observation of Flow:DiscountGuard.",
        }
        claim = {
            "schemaVersion": 3,
            "claimId": "KCLM-FLOW-GUARD-001",
            "revision": 1,
            "domain": "automation-map",
            "claimType": "automation-inventory",
            "subject": {"kind": "automation", "identity": "DiscountGuard"},
            "assertion": {
                "predicate": "source-defined-automation",
                "value": {
                    "metadataType": "Flow",
                    "facts": {
                        "object": "Engagement__c",
                        "errorCatalog": [
                            {
                                "component": "Block_Discount",
                                "kind": "custom-error",
                                "errorMessage": "Discount cannot exceed 20% for {!$Label.Tier_Name}.",
                                "resolvedErrorMessage": "Discount cannot exceed 20% for Standard tier.",
                                "fieldSelection": "Discount__c",
                                "triggerContext": "Engagement__c / Update / RecordBeforeSave",
                                "paths": [
                                    [
                                        {
                                            "decision": "Check_Tier",
                                            "outcome": "Standard_Tier",
                                            "conditions": ["$Record.Tier__c EqualTo Standard"],
                                        }
                                    ]
                                ],
                            }
                        ],
                    },
                    "references": [{"kind": "operates-on", "target": "Engagement__c"}],
                },
            },
            "statement": "DiscountGuard is a source-defined Flow component at the repository commit"
            ' that declares 1 error surface(s), including: "Discount cannot exceed 20% for'
            ' {!$Label.Tier_Name}.".',
            "status": "proposed",
            "assurance": "observed",
            "scope": {
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageVersion": None,
                "repositoryCommit": commit,
            },
            "evidenceRefs": ["KEVD-FLOW-GUARD-001"],
            "reviewRef": None,
            "observedAt": "2026-07-10T11:00:00Z",
            "verifiedAt": None,
            "reviewBy": "2026-12-01T11:00:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": [],
            "candidateKeywords": [],
            "limitations": ["Repository metadata establishes intended source only."],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
        }
        (self.root / "inputs/guard-claim.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        (self.root / "inputs/guard-evidence.yaml").write_text(
            yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8"
        )
        self.registry.propose(
            self.root / "inputs/guard-claim.yaml",
            [self.root / "inputs/guard-evidence.yaml"],
            expected_revision=0,
        )
        self.write_chat_reviewer()
        self.assertEqual(
            "verified", self.registry.approve_claim("KCLM-FLOW-GUARD-001", 1)["status"]
        )

        # Admin pastes the message the user saw (label already substituted by the platform).
        pasted = self.registry.query(search="Discount cannot exceed 20% for Standard tier")
        self.assertGreaterEqual(pasted["count"], 1)
        self.assertEqual(
            "KCLM-FLOW-GUARD-001", pasted["claims"][0]["claim"]["claimId"]
        )
        # The error component name is searchable too.
        by_component = self.registry.query(search="block discount")
        self.assertEqual("KCLM-FLOW-GUARD-001", by_component["claims"][0]["claim"]["claimId"])

        index = load_json(self.root / ".ai/knowledge/claims-index.json")
        row = next(r for r in index["claims"] if r["claimId"] == "KCLM-FLOW-GUARD-001")
        self.assertEqual(
            [
                "Discount cannot exceed 20% for {!$Label.Tier_Name}.",
                "Discount cannot exceed 20% for Standard tier.",
            ],
            row["emitsErrors"],
        )

    def propose_variant(
        self, claim_id: str, identity: str, related: list[str] | None = None
    ) -> None:
        base = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        variant = copy.deepcopy(base)
        variant["claimId"] = claim_id
        variant["subject"]["identity"] = identity
        variant["statement"] = f"{identity} exists in the accessible schema."
        if related is not None:
            variant["relatedClaims"] = related
        path = self.root / f"inputs/{claim_id}.yaml"
        path.write_text(yaml.safe_dump(variant, sort_keys=False), encoding="utf-8")
        self.registry.propose(
            path,
            [self.root / "inputs/knowledge-evidence.complete.yaml"],
            expected_revision=0,
        )

    def test_query_related_traverses_the_claim_graph_with_annotations(self) -> None:
        self.promote()  # KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001 verified
        anchor = "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001"
        self.propose_variant("KCLM-EXAMPLE-RELATED-001", "RelatedOne__c", [anchor])
        self.propose_variant(
            "KCLM-EXAMPLE-RELATED-002", "RelatedTwo__c", ["KCLM-EXAMPLE-RELATED-001"]
        )

        one_hop = self.registry.query(related=anchor)
        self.assertEqual(2, one_hop["count"])
        by_id = {match["claim"]["claimId"]: match for match in one_hop["claims"]}
        self.assertEqual(0, by_id[anchor]["distance"])
        self.assertTrue(by_id[anchor]["effective"])
        neighbor = by_id["KCLM-EXAMPLE-RELATED-001"]
        self.assertEqual(1, neighbor["distance"])
        self.assertFalse(neighbor["effective"])
        self.assertEqual("status is proposed", neighbor["nonEffectiveReason"])
        self.assertEqual({"edge": "relatedClaims", "from": anchor}, neighbor["via"])

        two_hops = self.registry.query(related=anchor, depth=2)
        self.assertEqual(3, two_hops["count"])
        self.assertIn(
            "KCLM-EXAMPLE-RELATED-002",
            {match["claim"]["claimId"] for match in two_hops["claims"]},
        )

        with self.assertRaisesRegex(ContractError, "--depth"):
            self.registry.query(related=anchor, depth=9)
        with self.assertRaisesRegex(ContractError, "--related"):
            self.registry.query(related=anchor, domain="object-descriptions")
        with self.assertRaisesRegex(ContractError, "does not exist"):
            self.registry.query(related="KCLM-NOPE-000")

    def promote_usage_claim(self) -> None:
        commit = "a" * 40
        evidence = {
            "schemaVersion": 3,
            "evidenceId": "KEVD-FLOW-ROUTER-002",
            "sourceType": "metadata-repository",
            "sourceLocator": f"git://{commit}/force-app/main/default/flows/EngagementRouter.flow-meta.xml",
            "authorityFor": ["automation-inventory"],
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageVersion": None,
            "repositoryCommit": commit,
            "observedAt": "2026-07-10T11:00:00Z",
            "retrievedAt": "2026-07-10T11:00:00Z",
            "sourceRevision": f"sha256:{'b' * 64}",
            "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": "2"},
            "completeness": {
                "status": "complete",
                "enumerationComplete": False,
                "permissionsProven": False,
                "missingSegments": [],
            },
            "sensitivity": "internal-sanitized",
            "sanitization": {"rawDataCommitted": False, "redactions": []},
            "contentDigest": f"sha256:{'c' * 64}",
            "summary": "Sanitized source observation of Flow:EngagementRouter.",
        }
        claim = {
            "schemaVersion": 3,
            "claimId": "KCLM-FLOW-ROUTER-002",
            "revision": 1,
            "domain": "automation-map",
            "claimType": "automation-inventory",
            "subject": {"kind": "automation", "identity": "EngagementRouter"},
            "assertion": {
                "predicate": "source-defined-automation",
                "value": {
                    "metadataType": "Flow",
                    "facts": {"object": "Engagement__c", "referencedObjects": ["Account"]},
                    "references": [
                        {"kind": "operates-on", "target": "Engagement__c"},
                        {"kind": "reads-field", "target": "Account.Name"},
                        {"kind": "invokes-apex", "target": "EngagementNotifier"},
                    ],
                },
            },
            "statement": "EngagementRouter is a source-defined Flow that routes engagements.",
            "status": "proposed",
            "assurance": "observed",
            "scope": {
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageVersion": None,
                "repositoryCommit": commit,
            },
            "evidenceRefs": ["KEVD-FLOW-ROUTER-002"],
            "reviewRef": None,
            "observedAt": "2026-07-10T11:00:00Z",
            "verifiedAt": None,
            "reviewBy": "2026-12-01T11:00:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": [],
            "candidateKeywords": [],
            "limitations": ["Repository metadata establishes intended source only."],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
        }
        (self.root / "inputs/flow-claim-2.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        (self.root / "inputs/flow-evidence-2.yaml").write_text(
            yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8"
        )
        self.registry.propose(
            self.root / "inputs/flow-claim-2.yaml",
            [self.root / "inputs/flow-evidence-2.yaml"],
            expected_revision=0,
        )
        self.write_chat_reviewer()
        self.registry.approve_claim("KCLM-FLOW-ROUTER-002", 1)

    def test_query_search_ranks_over_subject_and_usage_tokens(self) -> None:
        self.promote()
        self.promote_usage_claim()

        # Subject-identity tokens (camel-split) rank the flow claim first.
        routed = self.registry.query(search="engagement router")
        self.assertGreaterEqual(routed["count"], 1)
        self.assertEqual("KCLM-FLOW-ROUTER-002", routed["claims"][0]["claim"]["claimId"])
        self.assertGreater(routed["claims"][0]["score"], 0)

        # Usage-registry targets are searchable: Account.Name reaches the flow claim even
        # though "account" appears nowhere in its statement.
        by_usage = self.registry.query(search="account")
        self.assertEqual(1, by_usage["count"])
        self.assertEqual("KCLM-FLOW-ROUTER-002", by_usage["claims"][0]["claim"]["claimId"])

        # Zero-score results drop out entirely and --top caps the list.
        self.assertEqual(0, self.registry.query(search="zzzunknownterm")["count"])
        self.assertEqual(1, self.registry.query(search="the", top=1)["count"])
        with self.assertRaisesRegex(ContractError, "--top"):
            self.registry.query(search="engagement", top=0)

        # Search composes with structured filters: rank only the survivors.
        composed = self.registry.query(search="engagement", claim_type="object-existence")
        self.assertTrue(
            all(m["claim"]["claimType"] == "object-existence" for m in composed["claims"])
        )

    def test_explain_aggregates_subject_usage_and_reverse_usage(self) -> None:
        self.promote()
        self.promote_usage_claim()

        subject = self.registry.explain("EngagementRouter")
        self.assertEqual(1, subject["claimCount"])
        self.assertIn("automation-inventory", subject["claims"])
        self.assertEqual(
            ["Account", "Engagement__c"], subject["usage"]["objects"]
        )
        self.assertEqual(["Account.Name"], subject["usage"]["fields"])
        self.assertEqual(["EngagementNotifier"], subject["usage"]["invokes"])

        reverse = self.registry.explain("Engagement__c")
        self.assertEqual(0, reverse["claimCount"])
        self.assertEqual(1, len(reverse["usedBy"]))
        self.assertEqual("KCLM-FLOW-ROUTER-002", reverse["usedBy"][0]["claimId"])
        self.assertEqual(["objects"], reverse["usedBy"][0]["via"])

        with self.assertRaisesRegex(ContractError, "identity"):
            self.registry.explain("")

    MANIFEST_COMMIT = "a" * 40

    def manifest_bundle_evidence(self, identity: str) -> dict:
        return {
            "schemaVersion": 3,
            "evidenceId": f"KEVD-MANIFEST-{identity.upper()}-001",
            "sourceType": "metadata-repository",
            "sourceLocator": f"git://{self.MANIFEST_COMMIT}/force-app/main/default/tabs/{identity}.tab-meta.xml",
            "authorityFor": ["component-inventory", "object-existence"],
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageVersion": None,
            "repositoryCommit": self.MANIFEST_COMMIT,
            "observedAt": "2026-07-10T11:00:00Z",
            "retrievedAt": "2026-07-10T11:00:00Z",
            "sourceRevision": f"sha256:{'b' * 64}",
            "collector": {"kind": "tool", "name": "force_app_knowledge.py", "version": "2"},
            "completeness": {
                "status": "complete",
                "enumerationComplete": False,
                "permissionsProven": False,
                "missingSegments": [],
            },
            "sensitivity": "internal-sanitized",
            "sanitization": {"rawDataCommitted": False, "redactions": []},
            "contentDigest": f"sha256:{'c' * 64}",
            "summary": f"Sanitized source observation of {identity}.",
        }

    def manifest_bundle_claim(self, claim_id: str, identity: str) -> dict:
        base = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim = copy.deepcopy(base)
        claim["claimId"] = claim_id
        claim["subject"] = {"kind": "component", "identity": identity}
        claim["domain"] = "component-inventory"
        claim["claimType"] = "component-inventory"
        claim["assertion"] = {
            "predicate": "source-defined-component",
            "value": {"metadataType": "CustomTab"},
        }
        claim["statement"] = f"{identity} is defined in force-app source."
        claim["scope"] = {
            "environment": "not-applicable",
            "orgKey": None,
            "packageNamespace": None,
            "packageVersion": None,
            "repositoryCommit": self.MANIFEST_COMMIT,
        }
        claim["evidenceRefs"] = [f"KEVD-MANIFEST-{identity.upper()}-001"]
        return claim

    def propose_manifest_bundle(self, claim_id: str, identity: str, drafts: Path) -> dict:
        claim = self.manifest_bundle_claim(claim_id, identity)
        evidence = self.manifest_bundle_evidence(identity)
        draft_path = drafts / f"{claim_id}.yaml"
        draft_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        evidence_path = drafts / f"{evidence['evidenceId']}.yaml"
        evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
        self.registry.propose(draft_path, [evidence_path], expected_revision=0)
        return {
            "claimId": claim_id,
            "evidenceId": evidence["evidenceId"],
            "claimFile": f".cache/knowledge-proposals/force-app-drafts/{claim_id}.yaml",
            "evidenceFile": f".cache/knowledge-proposals/force-app-drafts/{evidence['evidenceId']}.yaml",
            "expectedRevision": 0,
            "disposition": "new",
            "command": "python scripts/knowledge_registry.py propose ...",
        }

    def write_manifest(self, bundles: list[dict]) -> Path:
        drafts = self.root / ".cache/knowledge-proposals/force-app-drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schemaVersion": 1,
            "kind": "force-app-knowledge-draft-manifest",
            "generatedAt": "2026-07-10T11:00:00Z",
            "repositoryCommit": "a" * 40,
            "sourceTreeDigest": f"sha256:{'d' * 64}",
            "reviewStatus": "draft",
            "claimCount": sum("claimFile" in bundle for bundle in bundles),
            "bundles": bundles,
            "limitations": ["Drafts are proposed claims only and are not verified Knowledge."],
        }
        path = drafts / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def test_approve_manifest_promotes_inventory_claims_and_skips_the_rest(self) -> None:
        self.write_chat_reviewer()
        drafts = self.root / ".cache/knowledge-proposals/force-app-drafts"
        drafts.mkdir(parents=True, exist_ok=True)

        bundles: list[dict] = []
        # Two proposable component-inventory claims.
        for index, identity in enumerate(("ComponentOne", "ComponentTwo"), start=1):
            bundles.append(
                self.propose_manifest_bundle(f"KCLM-MANIFEST-INV-00{index}", identity, drafts)
            )
        # An object-existence claim: proposed, but NOT manifest-approvable.
        guarded = self.manifest_bundle_claim("KCLM-MANIFEST-OBJ-001", "GuardedObject")
        guarded["domain"] = "object-descriptions"
        guarded["claimType"] = "object-existence"
        guarded["subject"] = {"kind": "object", "identity": "GuardedObject__c"}
        guarded["assertion"] = {"predicate": "exists-in-accessible-schema", "value": True}
        guarded_evidence = self.manifest_bundle_evidence("GuardedObject")
        guarded_path = drafts / "KCLM-MANIFEST-OBJ-001.yaml"
        guarded_path.write_text(yaml.safe_dump(guarded, sort_keys=False), encoding="utf-8")
        guarded_evidence_path = drafts / f"{guarded_evidence['evidenceId']}.yaml"
        guarded_evidence_path.write_text(
            yaml.safe_dump(guarded_evidence, sort_keys=False), encoding="utf-8"
        )
        self.registry.propose(guarded_path, [guarded_evidence_path], expected_revision=0)
        bundles.append(
            {
                "claimId": "KCLM-MANIFEST-OBJ-001",
                "evidenceId": guarded_evidence["evidenceId"],
                "claimFile": ".cache/knowledge-proposals/force-app-drafts/KCLM-MANIFEST-OBJ-001.yaml",
                "evidenceFile": f".cache/knowledge-proposals/force-app-drafts/{guarded_evidence['evidenceId']}.yaml",
                "expectedRevision": 0,
                "disposition": "new",
                "command": "python scripts/knowledge_registry.py propose ...",
            }
        )
        # A skipped bundle without a claim file (existing-non-proposed).
        bundles.append(
            {
                "claimId": "KCLM-MANIFEST-SKIPPED-001",
                "disposition": "existing-non-proposed",
                "reason": "existing status is verified",
            }
        )
        manifest_path = self.write_manifest(bundles)

        result = self.registry.approve_manifest(manifest_path)
        self.assertEqual(2, result["counts"]["approved"])
        self.assertEqual(2, result["counts"]["skipped"])
        self.assertEqual("copilot-chat-manifest-confirmation", result["mechanism"])
        skip_reasons = {entry["claimId"]: entry["reason"] for entry in result["skipped"]}
        self.assertIn("per-claim approval", skip_reasons["KCLM-MANIFEST-OBJ-001"])
        self.assertIn("no drafted claim", skip_reasons["KCLM-MANIFEST-SKIPPED-001"])

        for approved in result["approved"]:
            claim = load_yaml(self.root / f".ai/knowledge/claims/{approved['claimId']}.yaml")
            self.assertEqual("verified", claim["status"])
            review = load_yaml(self.root / f".ai/knowledge/reviews/{approved['reviewId']}.yaml")
            self.assertEqual(
                "copilot-chat-manifest-confirmation", review["auditReceipt"]["mechanism"]
            )
            self.assertIn(
                f"manifest/sha256:{result['manifestSha256']}",
                review["auditReceipt"]["reference"],
            )
            self.registry.verify_audit_receipt(review)
        # Full registry still validates after the batch (reviews bind correctly).
        self.registry.validate_all()
        # The untouched object claim is still proposed.
        self.assertEqual(
            "proposed",
            load_yaml(self.root / ".ai/knowledge/claims/KCLM-MANIFEST-OBJ-001.yaml")["status"],
        )

    def test_approve_manifest_skips_drifted_content_and_fails_closed_without_policy(self) -> None:
        self.write_chat_reviewer()
        drafts = self.root / ".cache/knowledge-proposals/force-app-drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        claim_id = "KCLM-MANIFEST-DRIFT-001"
        bundle = self.propose_manifest_bundle(claim_id, "DriftingComponent", drafts)
        # Draft file drifts after propose: the human would approve unseen content — skip.
        claim = self.manifest_bundle_claim(claim_id, "DriftingComponent")
        drifted = dict(claim, statement="Changed after proposal.")
        (drafts / f"{claim_id}.yaml").write_text(
            yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8"
        )
        manifest_path = self.write_manifest([bundle])
        result = self.registry.approve_manifest(manifest_path)
        self.assertEqual(0, result["counts"]["approved"])
        self.assertIn("drifted", result["skipped"][0]["reason"])

        # Policy knob absent -> manifest approval is disabled entirely.
        policy = load_json(self.root / "config/knowledge-policy.json")
        del policy["promotion"]["manifestApproval"]
        (self.root / "config/knowledge-policy.json").write_text(
            json.dumps(policy, indent=2), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "manifestApproval"):
            self.registry.approve_manifest(manifest_path)

    def test_stale_report_flags_expired_and_expiring_verified_claims(self) -> None:
        # promote() yields a verified claim with reviewBy 2026-08-08 (29 days after the 2026-07-10 now).
        self.promote()
        current = self.registry.stale_report(warn_days=30)
        self.assertEqual(0, current["expiredCount"])
        self.assertEqual(1, current["expiringCount"])
        self.assertEqual(
            "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", current["expiring"][0]["claimId"]
        )

        narrow = self.registry.stale_report(warn_days=7)
        self.assertEqual(0, narrow["expiredCount"])
        self.assertEqual(0, narrow["expiringCount"])

        future = self.registry.stale_report(
            warn_days=30, at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(1, future["expiredCount"])
        self.assertFalse(future["expired"][0]["effective"])

    def test_verify_citations_checks_existence_freshness_and_digest(self) -> None:
        self.promote()
        claim_id = "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001"
        path = self.root / ".ai/knowledge/claims" / f"{claim_id}.yaml"
        sha = file_sha256(path)

        ok = self.registry.verify_citations([{"claimId": claim_id, "revision": 2, "sha256": sha}])
        self.assertEqual("ok", ok["citations"][0]["verdict"])
        self.assertEqual({"ok": 1, "warning": 0, "invalid": 0}, ok["counts"])

        missing = self.registry.verify_citations([{"claimId": "KCLM-NO-SUCH-CLAIM-0001"}])
        self.assertEqual("missing", missing["citations"][0]["verdict"])
        self.assertEqual("invalid", missing["citations"][0]["severity"])

        bad_sha = self.registry.verify_citations([{"claimId": claim_id, "sha256": "0" * 64}])
        self.assertEqual("sha-mismatch", bad_sha["citations"][0]["verdict"])

        bad_rev = self.registry.verify_citations([{"claimId": claim_id, "revision": 5}])
        self.assertEqual("revision-mismatch", bad_rev["citations"][0]["verdict"])

        expired = self.registry.verify_citations(
            [{"claimId": claim_id, "revision": 2}],
            at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual("not-effective", expired["citations"][0]["verdict"])
        self.assertEqual("warning", expired["citations"][0]["severity"])

    def test_approve_claim_batch_cli_argument_contract(self) -> None:
        # The CLI runs against the repository root, not the temp fixture — so assert the
        # argument-contract behavior here (batch/single exclusivity, spec parsing, requirements).
        for bad_args, expected in (
            (["--claim-spec", "KCLM-X:1", "--claim-id", "KCLM-X"], "not both"),
            (["--claim-spec", "no-revision"], "claimId>:<revision"),
            ([], "requires --claim-id"),
        ):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/knowledge_registry.py"),
                    "approve-claim",
                    *bad_args,
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=30,
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn(expected, completed.stdout)

    def test_propose_rejects_unfilled_description_sentinel(self) -> None:
        claim = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim["statement"] = (
            "Sentinel test claim <AGENT_WRITES_WHAT_THIS_COMPONENT_DOES_BASED_ON_ITS_SOURCE>."
        )
        (self.root / "inputs/sentinel-claim.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "placeholder is unfilled"):
            self.registry.propose(
                self.root / "inputs/sentinel-claim.yaml",
                [self.root / "inputs/knowledge-evidence.complete.yaml"],
                expected_revision=0,
            )

    def test_approve_claim_requires_a_named_human_reviewer(self) -> None:
        self.propose()
        with self.assertRaisesRegex(ContractError, "chat reviewer identity"):
            self.registry.approve_claim("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", 1)
        self.write_chat_reviewer("<FULL_NAME_OF_THE_HUMAN_WHO_APPROVES_KNOWLEDGE_IN_CHAT>")
        with self.assertRaisesRegex(ContractError, "must name the approving human"):
            self.registry.approve_claim("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", 1)

    def test_expected_revision_prevents_lost_update(self) -> None:
        self.propose()
        with self.assertRaisesRegex(ContractError, "expected revision 2, found 1"):
            self.registry.promote(
                "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001",
                "KREV-EXAMPLEMANAGEDOBJECT-VERIFY-001",
                expected_revision=2,
            )
        claim = load_yaml(
            self.root
            / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        self.assertEqual("proposed", claim["status"])
        self.assertEqual(1, claim["revision"])

    def test_effective_claim_and_filtered_query_exclude_expired_records(self) -> None:
        self.promote()
        claim_id = "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001"
        effective = self.registry.effective_claim(claim_id)
        self.assertEqual(claim_id, effective["claim"]["claimId"])
        self.assertEqual(
            ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml",
            effective["path"],
        )
        self.assertRegex(effective["sha256"], r"^[0-9a-f]{64}$")

        result = self.registry.query(
            subject_identity="examplepkg__ExampleManagedObject__c",
            environment="qa",
            package_namespace="examplepkg",
        )
        self.assertEqual(1, result["count"])
        self.assertEqual(claim_id, result["claims"][0]["claim"]["claimId"])
        self.assertEqual(0, self.registry.query(domain="automation-map")["count"])
        with self.assertRaisesRegex(ContractError, "requires at least one"):
            self.registry.query()

        after_expiry = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            0,
            self.registry.query(claim_id=claim_id, at=after_expiry)["count"],
        )
        with self.assertRaisesRegex(ContractError, "not current, verified"):
            self.registry.effective_claim(claim_id, at=after_expiry)

    def test_effective_claim_fails_closed_on_an_active_contradiction(self) -> None:
        self.promote()
        original_id = "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001"
        conflicting = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        conflicting["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-CONFLICT-001"
        conflicting["assertion"]["value"] = False
        conflicting["polarity"] = "negative"
        conflicting["contradicts"] = [original_id]
        conflict_path = self.root / "inputs/active-conflict.yaml"
        conflict_path.write_text(
            yaml.safe_dump(conflicting, sort_keys=False), encoding="utf-8"
        )
        self.registry.propose(conflict_path, [], expected_revision=0)

        with self.assertRaisesRegex(ContractError, "non-contradicted"):
            self.registry.effective_claim(original_id)
        self.assertEqual(0, self.registry.query(claim_id=original_id)["count"])

    def test_audit_receipt_digest_is_recomputed_not_shape_checked(self) -> None:
        self.propose()
        review = load_yaml(self.root / "inputs/knowledge-review.verify.yaml")
        review["auditReceipt"]["reference"] = "synthetic://tampered-approval"
        tampered = self.root / "inputs/tampered-review.yaml"
        tampered.write_text(yaml.safe_dump(review, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "auditReceipt digest"):
            self.registry.record_review(tampered)

    def test_review_binding_rejects_digest_shaped_but_wrong_evidence_manifest(self) -> None:
        self.propose()
        review = load_yaml(self.root / "inputs/knowledge-review.verify.yaml")
        review["evidenceManifest"][0]["recordDigest"] = "sha256:" + ("f" * 64)
        tampered = self.root / "inputs/tampered-manifest.yaml"
        tampered.write_text(yaml.safe_dump(review, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "evidenceManifest"):
            self.registry.record_review(tampered)

    def test_propose_rejects_verified_input(self) -> None:
        verified = load_yaml(FIXTURES / "knowledge-claim.verified.yaml")
        path = self.root / "inputs/verified.yaml"
        path.write_text(yaml.safe_dump(verified, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "status: proposed"):
            self.registry.propose(
                path,
                [self.root / "inputs/knowledge-evidence.complete.yaml"],
                expected_revision=0,
            )

    def test_refresh_verified_repropose_requires_the_explicit_flag(self) -> None:
        # Refresh workflow: a verified claim may be demoted to a new proposed revision only
        # under the explicit --refresh-verified acknowledgement; the plain propose path keeps
        # rejecting any replacement of non-proposed claims.
        self.promote()
        refreshed = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        refreshed["revision"] = 3
        path = self.root / "inputs/knowledge-claim.refresh.yaml"
        path.write_text(yaml.safe_dump(refreshed, sort_keys=False), encoding="utf-8")
        evidence = [self.root / "inputs/knowledge-evidence.complete.yaml"]
        with self.assertRaisesRegex(ContractError, "non-proposed claim"):
            self.registry.propose(path, evidence, expected_revision=2)
        result = self.registry.propose(
            path, evidence, expected_revision=2, refresh_verified=True
        )
        self.assertEqual({"claimId": "KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", "status": "proposed", "revision": 3, "reconciliation": "new"}, result)
        canonical_claim = load_yaml(
            self.root / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        self.assertEqual("proposed", canonical_claim["status"])
        self.assertEqual(3, canonical_claim["revision"])
        # The refresh flag never lets revision optimism slip.
        with self.assertRaisesRegex(ContractError, "expected revision"):
            self.registry.propose(path, evidence, expected_revision=5, refresh_verified=True)

    def test_reconcile_distinguishes_duplicate_conflict_and_parallel_scope(self) -> None:
        self.propose()
        base = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        duplicate = copy.deepcopy(base)
        duplicate["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-DUPLICATE-001"
        self.assertEqual("duplicate", self.registry.reconcile(duplicate)["status"])
        conflict = copy.deepcopy(duplicate)
        conflict["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-CONFLICT-001"
        conflict["assertion"]["value"] = False
        conflict["polarity"] = "negative"
        self.assertEqual("conflict", self.registry.reconcile(conflict)["status"])
        parallel = copy.deepcopy(duplicate)
        parallel["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-PARALLEL-001"
        parallel["scope"]["environment"] = "uat"
        parallel["scope"]["orgKey"] = "synthetic-uat"
        self.assertEqual("parallel-scope", self.registry.reconcile(parallel)["status"])

    def test_reconcile_ignores_rejected_and_superseded_history(self) -> None:
        self.propose()
        path = (
            self.root
            / ".ai/knowledge/claims/KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001.yaml"
        )
        candidate = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        candidate["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-RETRY-001"
        for status in ("rejected", "superseded"):
            with self.subTest(status=status):
                historical = load_yaml(path)
                historical["status"] = status
                historical["reviewRef"] = "KREV-EXAMPLEMANAGEDOBJECT-HISTORY-001"
                if status == "superseded":
                    historical["supersededBy"] = candidate["claimId"]
                path.write_text(
                    yaml.safe_dump(historical, sort_keys=False), encoding="utf-8"
                )
                self.assertEqual("new", self.registry.reconcile(candidate)["status"])

    def test_render_indexes_is_deterministic_and_checkable(self) -> None:
        self.propose()
        with self.assertRaisesRegex(ContractError, "indexes drifted"):
            self.registry.render_indexes(check=True)
        self.registry.render_indexes(check=False)
        self.registry.render_indexes(check=True)
        rendered = (self.root / ".ai/knowledge/object-descriptions.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", rendered)
        self.assertIn("proposed", rendered)
        self.assertIn("Non-effective records — untrusted", rendered)
        self.assertIn(
            "examplepkg__ExampleManagedObject__c exists in the accessible schema.",
            rendered,
        )
        self.assertNotIn("Synthetic fixture only; ExampleManagedObject__c", rendered)

    def test_render_indexes_promotes_only_effective_facts_to_trusted_section(self) -> None:
        self.promote()
        self.registry.render_indexes(check=False)
        rendered = (self.root / ".ai/knowledge/object-descriptions.md").read_text(
            encoding="utf-8"
        )
        trusted, untrusted = rendered.split("## Non-effective records — untrusted", 1)
        self.assertIn("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", trusted)
        self.assertIn("Only rows in this section are eligible as grounded facts", trusted)
        self.assertNotIn("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", untrusted)
        self.assertNotIn("Synthetic fixture only; ExampleManagedObject__c", rendered)

    def test_render_indexes_emits_deterministic_claims_index(self) -> None:
        self.propose()
        self.registry.render_indexes(check=False)
        index_path = self.root / ".ai/knowledge/claims-index.json"
        first = index_path.read_text(encoding="utf-8")
        index = json.loads(first)
        self.assertEqual("knowledge-claims-index", index["kind"])
        self.assertEqual(1, index["claimCount"])
        row = index["claims"][0]
        self.assertEqual("KCLM-EXAMPLEMANAGEDOBJECT-EXISTS-001", row["claimId"])
        self.assertFalse(row["effective"])
        self.assertEqual([], row["candidateKeywords"])
        self.registry.render_indexes(check=False)
        self.assertEqual(first, index_path.read_text(encoding="utf-8"))
        self.registry.render_indexes(check=True)
        index_path.write_text(first.replace('"claimCount": 1', '"claimCount": 2'), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "indexes drifted"):
            self.registry.render_indexes(check=True)

    def test_claims_index_marks_promoted_claims_effective(self) -> None:
        self.promote()
        self.registry.render_indexes(check=False)
        index = json.loads(
            (self.root / ".ai/knowledge/claims-index.json").read_text(encoding="utf-8")
        )
        self.assertTrue(index["claims"][0]["effective"])
        self.assertEqual("verified", index["claims"][0]["status"])

    def test_query_matches_keyword_tiers_and_description_text(self) -> None:
        claim = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim["candidateKeywords"] = ["Revenue Adjustment"]
        path = self.root / "inputs/candidate-keyword-claim.yaml"
        path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        self.registry.propose(
            path,
            [self.root / "inputs/knowledge-evidence.complete.yaml"],
            expected_revision=0,
        )
        self.write_chat_reviewer()
        self.registry.approve_claim(claim["claimId"], 1)

        by_candidate = self.registry.query(keyword="revenue adjustment")
        self.assertEqual(1, by_candidate["count"])
        self.assertEqual("candidateKeywords", by_candidate["claims"][0]["keywordTier"])
        self.assertEqual(0, self.registry.query(keyword="no-such-term")["count"])

        by_text = self.registry.query(text="exists in the accessible QA schema")
        self.assertEqual(1, by_text["count"])
        self.assertEqual(0, self.registry.query(text="no such statement fragment")["count"])

    def test_propose_rejects_keywords_outside_the_approved_taxonomy(self) -> None:
        claim = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim["keywords"] = ["Rozliczenia"]
        path = self.root / "inputs/taxonomy-keyword-claim.yaml"
        path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        evidence = [self.root / "inputs/knowledge-evidence.complete.yaml"]
        with self.assertRaisesRegex(ContractError, "approved terms"):
            self.registry.propose(path, evidence, expected_revision=0)

        taxonomy = self.root / ".ai/knowledge/keyword-taxonomy.md"
        taxonomy.write_text(
            "# Keyword Taxonomy\n\n## Terms\n\n- Rozliczenia — billing settlement processes\n",
            encoding="utf-8",
        )
        proposed = self.registry.propose(path, evidence, expected_revision=0)
        self.assertEqual("proposed", proposed["status"])

    def test_taxonomy_parser_ignores_comments_and_the_live_taxonomy_is_empty(self) -> None:
        taxonomy = self.root / ".ai/knowledge/keyword-taxonomy.md"
        taxonomy.write_text(
            "# Keyword Taxonomy\n\n## Terms\n\n"
            "<!-- Format example, not a term:\n- <term> — <what it covers>\n-->\n"
            "- Rozliczenia — billing settlement processes\n",
            encoding="utf-8",
        )
        self.assertEqual({"Rozliczenia"}, self.registry.approved_taxonomy_terms())
        # The live repository taxonomy holds only the commented format example — zero terms.
        self.assertEqual(set(), KnowledgeRegistry(ROOT).approved_taxonomy_terms())

    def test_keyword_report_aggregates_candidates_for_human_curation(self) -> None:
        claim = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim["candidateKeywords"] = ["revenue adjustment", "billing event"]
        path = self.root / "inputs/report-claim.yaml"
        path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        self.registry.propose(
            path,
            [self.root / "inputs/knowledge-evidence.complete.yaml"],
            expected_revision=0,
        )
        report = self.registry.keyword_report()
        self.assertEqual(2, report["candidateTermCount"])
        terms = {item["term"]: item for item in report["candidateTerms"]}
        self.assertEqual({"revenue adjustment", "billing event"}, set(terms))
        self.assertEqual([claim["claimId"]], terms["revenue adjustment"]["claimIds"])
        self.assertFalse(terms["revenue adjustment"]["approved"])

    def test_review_file_must_be_human_and_schema_valid(self) -> None:
        self.propose()
        invalid = self.root / "inputs/invalid-review.yaml"
        shutil.copy2(FIXTURES / "knowledge-review.invalid-model-reviewer.yaml", invalid)
        with self.assertRaisesRegex(ContractError, "schema failure"):
            self.registry.record_review(invalid)

    def test_negative_claim_requires_enumeration_and_permission_proof(self) -> None:
        evidence = load_yaml(self.root / "inputs/knowledge-evidence.complete.yaml")
        evidence["evidenceId"] = "KEVD-EXAMPLEMANAGEDOBJECT-ABSENCE-001"
        evidence["completeness"]["enumerationComplete"] = False
        evidence["completeness"]["permissionsProven"] = False
        evidence_path = self.root / "inputs/negative-evidence.yaml"
        evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")

        claim = load_yaml(self.root / "inputs/knowledge-claim.proposed.yaml")
        claim["claimId"] = "KCLM-EXAMPLEMANAGEDOBJECT-ABSENCE-001"
        claim["polarity"] = "negative"
        claim["assertion"]["value"] = False
        claim["evidenceRefs"] = [evidence["evidenceId"]]
        claim_path = self.root / "inputs/negative-claim.yaml"
        claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        self.registry.propose(claim_path, [evidence_path], expected_revision=0)

        review = load_yaml(self.root / "inputs/knowledge-review.verify.yaml")
        review["reviewId"] = "KREV-EXAMPLEMANAGEDOBJECT-ABSENCE-001"
        review["claimId"] = claim["claimId"]
        review["evidenceRefs"] = [evidence["evidenceId"]]
        self.bind_review(review, claim, [evidence])
        review_path = self.root / "inputs/negative-review.yaml"
        review_path.write_text(yaml.safe_dump(review, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "negative claim lacks complete enumeration"):
            self.registry.record_review(review_path)

    def test_evidence_chronology_is_enforced(self) -> None:
        evidence = load_yaml(self.root / "inputs/knowledge-evidence.complete.yaml")
        evidence["retrievedAt"] = "2026-07-09T09:59:00Z"
        path = self.root / "inputs/backdated-retrieval.yaml"
        path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "retrievedAt precedes observedAt"):
            self.registry.propose(
                self.root / "inputs/knowledge-claim.proposed.yaml",
                [path],
                expected_revision=0,
            )


if __name__ == "__main__":
    unittest.main()
