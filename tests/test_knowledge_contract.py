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
