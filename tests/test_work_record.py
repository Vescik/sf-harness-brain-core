from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_record", ROOT / "scripts" / "work_record.py")
assert SPEC and SPEC.loader
work_record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(work_record)


class WorkRecordTests(unittest.TestCase):
    record_id = "ADO-example-project-123"
    claim_id = "KCLM-ACCOUNT-OWNERSHIP"
    rule_ids = ["SAFE-EVID-001", "MP-OWN-001", "ORG-KNOW-001", "SF-BULK-001"]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="work-record-v2-")
        self.root = Path(self.temporary.name)
        self.claim_effective = True
        self._create_contract_root()
        self.claim = self._ownership_claim()
        claim_path = self.root / ".ai" / "knowledge" / "claims" / f"{self.claim_id}.yaml"
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(yaml.safe_dump(self.claim, sort_keys=False), encoding="utf-8")
        self.claim_path = claim_path
        self._initialize_git_repository()
        self.claim_patch = patch.object(
            work_record,
            "effective_knowledge_claim",
            side_effect=self._effective_claim,
        )
        self.facade_patch = patch.object(
            work_record,
            "call_salesforce_review_facade",
            side_effect=self._salesforce_identity_receipt,
        )
        self.claim_patch.start()
        self.facade_patch.start()

    def tearDown(self) -> None:
        self.facade_patch.stop()
        self.claim_patch.stop()
        self.temporary.cleanup()

    def _create_contract_root(self) -> None:
        schema_names = [
            "principle-registry.schema.json",
            "salesforce-org-review-evidence.schema.json",
            "verification-policy.schema.json",
            "verification-receipt.schema.json",
            "work-evidence.schema.json",
        ]
        (self.root / "schemas").mkdir(parents=True)
        for name in schema_names:
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)

        source_by_rule = {
            "SAFE-EVID-001": ("kernel", ".github/copilot-instructions.md", "repository-policy", "global"),
            "MP-OWN-001": (
                "1",
                ".github/instructions/managed-package-constraints.instructions.md",
                "managed-package-policy",
                "managed-package",
            ),
            "ORG-KNOW-001": (
                "2",
                ".github/instructions/organization-principles.instructions.md",
                "organization-policy",
                "organization",
            ),
            "SF-BULK-001": (
                "3",
                ".github/instructions/salesforce-best-practices.instructions.md",
                "salesforce-platform-practice",
                "salesforce-platform",
            ),
        }
        rules = []
        for rule_id, (tier, source, kind, scope) in source_by_rule.items():
            path = self.root / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {rule_id}\n\nTest canonical rule source.\n", encoding="utf-8")
            rules.append(
                {
                    "ruleId": rule_id,
                    "tier": tier,
                    "status": "active",
                    "sourceFile": source,
                    "ownerRole": "test-policy-owner",
                    "basis": {
                        "kind": kind,
                        "completeness": "complete",
                        "sourceRefs": [source],
                        "claimRefs": [],
                    },
                    "scope": scope,
                    "review": {"lastReviewedAt": None, "reviewBy": None},
                }
            )
        registry = self.root / ".github" / "instructions" / "rule-registry.yaml"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(
            yaml.safe_dump({"schemaVersion": 1, "rules": rules}, sort_keys=False),
            encoding="utf-8",
        )

        config_dir = self.root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "harness.local.json").write_text(
            json.dumps(
                {
                    "workspace": {"manifestPath": "manifest/package.xml"},
                    "salesforce": {
                        "review": {
                            "enabled": True,
                            "requireDualSource": True,
                            "evidenceMaxAgeMinutes": 60,
                        },
                        "orgs": [
                            {
                                "alias": "SBX-DEV",
                                "environment": "development",
                                "allowAgentRead": True,
                                "allowAgentReview": True,
                            }
                        ],
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._write_verification_policy(exit_code=0)

        (self.root / "sfdx-project.json").write_text(
            json.dumps(
                {
                    "packageDirectories": [{"path": "force-app", "default": True}],
                    "name": "test-root-sfdx",
                    "namespace": "",
                    "sfdcLoginUrl": "https://test.salesforce.com",
                    "sourceApiVersion": "67.0",
                }
            ),
            encoding="utf-8",
        )
        (self.root / "force-app" / "main" / "default").mkdir(parents=True)
        (self.root / "tests" / "e2e").mkdir(parents=True)
        (self.root / "manifest").mkdir(parents=True)
        (self.root / "manifest" / "package.xml").write_text(
            "<Package xmlns=\"http://soap.sforce.com/2006/04/metadata\"><version>67.0</version></Package>\n",
            encoding="utf-8",
        )
        (self.root / "artifacts").mkdir()
        (self.root / "artifacts" / "design-source.json").write_text(
            '{"source":"ADO:example-project#123@7","complete":true}\n',
            encoding="utf-8",
        )
        (self.root / "artifacts" / "empty.txt").write_bytes(b"")

    def _write_verification_policy(self, *, exit_code: int) -> None:
        policy = {
            "$schema": "../schemas/verification-policy.schema.json",
            "schemaVersion": 1,
            "requiredForSafe": ["test-metadata-validate"],
            "profiles": {
                "test-metadata-validate": {
                    "description": "Deterministic test profile selected from repository policy.",
                    "workspaceRoot": "brain-core",
                    "allowedRoles": [
                        "development-assistant",
                        "test-strategist",
                        "guardrail-reviewer",
                    ],
                    "command": ["${PYTHON}", "-c", f"raise SystemExit({exit_code})"],
                    "timeoutSeconds": 5,
                    "maxOutputBytes": 1024,
                }
            },
        }
        (self.root / "config" / "verification-policy.json").write_text(
            json.dumps(policy, indent=2), encoding="utf-8"
        )

    def _ownership_claim(self) -> dict:
        return {
            "schemaVersion": 3,
            "claimId": self.claim_id,
            "revision": 2,
            "domain": "current-implementation",
            "claimType": "object-ownership",
            "subject": {"kind": "object", "identity": "Account"},
            "assertion": {"predicate": "ownership-classification", "value": "package-owned"},
            "statement": "Account ownership is package-bound in the reviewed scope.",
            "polarity": "positive",
            "status": "verified",
            "assurance": "corroborated",
            "scope": {
                "environment": "development",
                "orgKey": "ORG-TEST",
                "packageNamespace": "pkg",
                "packageKey": "PKG-TEST",
                "packageVersion": "3.4.0",
                "repositoryCommit": None,
            },
            "evidenceRefs": ["KEVD-ACCOUNT-OWNERSHIP"],
            "reviewRef": "KREV-ACCOUNT-OWNERSHIP",
            "observedAt": "2026-07-10T09:00:00Z",
            "verifiedAt": "2026-07-10T09:05:00Z",
            "reviewBy": "2099-08-09T09:05:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": ["account", "ownership"],
            "limitations": [],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
            "relatedClaims": [],
        }

    def _effective_claim(self, root: Path, claim_id: str) -> dict:
        if claim_id != self.claim_id or not self.claim_effective:
            raise work_record.WorkRecordError(f"Knowledge claim is not effective: {claim_id}")
        claim = yaml.safe_load(self.claim_path.read_text(encoding="utf-8"))
        return {
            "claim": claim,
            "sha256": work_record.file_hash(self.claim_path),
            "path": f".ai/knowledge/claims/{claim_id}.yaml",
        }

    def _salesforce_identity_receipt(self, root: Path, alias: str, tool: str, arguments: dict) -> dict:
        self.assertEqual(alias, "SBX-DEV")
        self.assertEqual(tool, "review_org_identity")
        self.assertEqual(arguments, {})
        now = work_record.utc_now()
        receipt = {
            "schemaVersion": 1,
            "runId": "123e4567-e89b-42d3-a456-426614174000",
            "generatedAt": now,
            "reviewType": "org-identity",
            "status": "VERIFIED",
            "target": {
                "environment": "development",
                "apiVersion": "67.0",
                "aliasPolicyMatched": True,
                "expectedHostMatched": True,
                "expectedOrgIdMatched": True,
                "isSandbox": True,
            },
            "sources": {
                "cli": {
                    "kind": "salesforce-cli",
                    "version": "@salesforce/cli/2.100.0",
                    "complete": True,
                    "retrievedAt": now,
                },
                "mcp": {
                    "kind": "salesforce-mcp",
                    "version": "0.30.15",
                    "complete": True,
                    "retrievedAt": now,
                },
            },
            "facts": {"identityPolicyMatched": True, "isSandbox": True},
            "reconciliation": {
                "status": "MATCH",
                "comparisons": [
                    {"fact": "organization-identity", "result": "MATCH"},
                    {"fact": "is-sandbox", "result": "MATCH"},
                ],
            },
            "completeness": {"complete": True, "dualSource": True, "truncated": False},
            "warnings": [],
        }
        receipt["sha256"] = work_record.canonical_embedded_digest(receipt)
        work_record.validate_salesforce_review_envelope(self.root, receipt)
        return receipt

    def _initialize_git_repository(self) -> None:
        commands = [
            ["git", "init", "-q", str(self.root)],
            ["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"],
            ["git", "-C", str(self.root), "config", "user.name", "Work Record Tests"],
            ["git", "-C", str(self.root), "add", "."],
            ["git", "-C", str(self.root), "commit", "-qm", "test baseline"],
        ]
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, text=True)

    def run_ok(self, *arguments: str) -> dict:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = work_record.main(["--root", str(self.root), *arguments])
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "ok")
        return payload

    def run_error(self, *arguments: str) -> str:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = work_record.main(["--root", str(self.root), *arguments])
        self.assertEqual(code, 2, stdout.getvalue())
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["status"], "error")
        return payload["error"]

    def command(self, name: str, current: dict, *arguments: str) -> dict:
        return self.run_ok(
            name,
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            *arguments,
        )

    def initialize(self) -> dict:
        arguments = [
            "init",
            "--record-id",
            self.record_id,
            "--organization",
            "example-org",
            "--project",
            "example-project",
            "--work-item-id",
            "123",
            "--work-item-type",
            "Story",
            "--work-item-url",
            "https://dev.azure.com/example-org/example-project/_workitems/edit/123",
            "--work-item-revision",
            "7",
            "--fetched-at",
            "2026-07-10T09:00:00Z",
            "--title",
            "Generic package-bound object extension",
            "--requested-outcome",
            "Design a safe extension around a verified Salesforce object boundary.",
            "--workspace-root",
            "brain-core",
            "--component",
            json.dumps({"name": "Account", "type": "CustomObject"}),
            "--path",
            "force-app/main/default/objects/Account/Account.object-meta.xml",
            "--environment-alias",
            "SBX-DEV",
        ]
        for rule_id in self.rule_ids:
            arguments.extend(["--rule-id", rule_id])
        return self.run_ok(*arguments)

    def bind_claim(self, current: dict) -> dict:
        return self.command(
            "bind-claim",
            current,
            "--role",
            "solution-designer",
            "--claim-id",
            self.claim_id,
        )

    def append_source_evidence(self, current: dict) -> dict:
        artifact = self.root / "artifacts" / "design-source.json"
        return self.command(
            "append-evidence",
            current,
            "--role",
            "solution-designer",
            "--evidence-id",
            "EV-design-source",
            "--evidence-type",
            "design-source",
            "--source-ref",
            "ADO:example-project#123@7",
            "--source-revision",
            "7",
            "--completeness",
            "complete",
            "--durability",
            "durable",
            "--summary",
            "Persisted source artifact used by the design.",
            "--artifact-path",
            "artifacts/design-source.json",
            "--artifact-sha256",
            work_record.file_hash(artifact),
        )

    def capture_repository(self, current: dict, role: str = "solution-designer") -> dict:
        return self.command(
            "capture-repository",
            current,
            "--role",
            role,
            "--workspace-root",
            "brain-core",
        )

    def capture_identity(self, current: dict) -> dict:
        return self.command(
            "capture-org-review",
            current,
            "--role",
            "solution-designer",
            "--review-type",
            "identity",
        )

    def transition(self, current: dict, role: str, phase: str, status: str, note: str) -> dict:
        return self.command(
            "transition",
            current,
            "--role",
            role,
            "--phase",
            phase,
            "--status",
            status,
            "--note",
            note,
        )

    def prepare_waiting(self, *, include_repository: bool = True) -> dict:
        current = self.initialize()
        current = self.bind_claim(current)
        current = self.append_source_evidence(current)
        if include_repository:
            current = self.capture_repository(current)
        current = self.capture_identity(current)
        current = self.transition(current, "solution-designer", "design", "draft", "Start design.")
        design = self.root / ".ai" / "change-records" / self.record_id / "design.md"
        design.write_text(design.read_text(encoding="utf-8") + "\nSourced design detail.\n", encoding="utf-8")
        return self.transition(
            current,
            "solution-designer",
            "design",
            "awaiting_human",
            "Sourced design is ready for human review.",
        )

    def approve(self, current: dict) -> dict:
        return self.command(
            "approve",
            current,
            "--expected-design-hash",
            current["designHash"],
            "--approver",
            "Human Reviewer",
            "--mechanism",
            "human-terminal",
            "--approval-ref",
            "terminal:review-session-123",
        )

    def prepare_review_ready(self) -> dict:
        current = self.approve(self.prepare_waiting())
        current = self.transition(
            current,
            "development-assistant",
            "development",
            "in_progress",
            "Implement the approved design.",
        )
        return self.transition(
            current,
            "development-assistant",
            "review",
            "ready",
            "Implementation is ready for independent review.",
        )

    def run_verification(self, current: dict) -> dict:
        return self.command(
            "run-verification",
            current,
            "--role",
            "test-strategist",
            "--profile-id",
            "test-metadata-validate",
        )

    def test_init_forces_unknown_ownership_and_rejects_self_declared_environment_proof(self) -> None:
        created = self.initialize()
        record = work_record.load_record(self.root, self.record_id)
        self.assertEqual(record["scope"]["components"][0]["ownership"], "unknown")
        self.assertIsNone(record["scope"]["components"][0]["ownershipClaimRef"])
        self.assertEqual(record["environment"]["status"], "unverified")
        self.assertEqual(created["groundingHash"], work_record.grounding_hash(record))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            work_record.main(
                [
                    "--root",
                    str(self.root),
                    "init",
                    "--record-id",
                    "ADO-example-project-999",
                    "--sandbox-verified",
                ]
            )

    def test_bind_claim_derives_package_ownership_and_rejects_ineffective_claim(self) -> None:
        current = self.initialize()
        self.claim_effective = False
        error = self.run_error(
            "bind-claim",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            "--role",
            "solution-designer",
            "--claim-id",
            self.claim_id,
        )
        self.assertIn("not effective", error)
        self.claim_effective = True
        bound = self.bind_claim(current)
        record = work_record.load_record(self.root, self.record_id)
        component = record["scope"]["components"][0]
        self.assertEqual(component["ownership"], "package-owned")
        self.assertEqual(component["ownershipClaimRef"], self.claim_id)
        self.assertEqual(component["packageNamespace"], "pkg")
        self.assertEqual(component["packageVersion"], "3.4.0")
        self.assertNotEqual(bound["scopeHash"], current["scopeHash"])
        self.assertEqual(record["claimRefs"][0]["sha256"], work_record.file_hash(self.claim_path))

    def test_claim_file_drift_invalidates_the_exact_binding(self) -> None:
        self.bind_claim(self.initialize())
        self.claim_path.write_text(self.claim_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        error = self.run_error("validate", "--record-id", self.record_id)
        self.assertIn("differs from its persisted source", error)

    def test_rehashed_component_ownership_fabrication_is_rejected(self) -> None:
        self.bind_claim(self.initialize())
        path = self.root / ".ai" / "change-records" / self.record_id / "record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        component = record["scope"]["components"][0]
        component["ownership"] = "subscriber-owned"
        component["packageNamespace"] = None
        component["packageVersion"] = None
        record["scopeHash"] = work_record.scope_hash(record["scope"])
        record["groundingHash"] = work_record.grounding_hash(record)
        work_record.atomic_write_json(path, record)
        error = self.run_error("validate", "--record-id", self.record_id)
        self.assertIn("does not match its structural Knowledge claim", error)

    def test_complete_durable_evidence_requires_a_real_nonempty_stable_artifact(self) -> None:
        current = self.bind_claim(self.initialize())
        error = self.run_error(
            "append-evidence",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            "--role",
            "solution-designer",
            "--evidence-id",
            "EV-empty",
            "--evidence-type",
            "design-source",
            "--source-ref",
            "ADO:example-project#123@7",
            "--completeness",
            "complete",
            "--durability",
            "durable",
            "--summary",
            "An empty artifact cannot prove completeness.",
            "--artifact-path",
            "artifacts/empty.txt",
            "--artifact-sha256",
            hashlib.sha256(b"").hexdigest(),
        )
        self.assertIn("empty artifact", error)
        self.assertFalse(
            (self.root / ".ai" / "change-records" / self.record_id / "evidence" / "EV-empty.json").exists()
        )
        appended = self.append_source_evidence(current)
        artifact = self.root / "artifacts" / "design-source.json"
        artifact.write_text('{"tampered":true}\n', encoding="utf-8")
        error = self.run_error("validate", "--record-id", self.record_id)
        self.assertIn("bound evidence artifact changed", error)
        self.assertGreater(appended["recordRevision"], current["recordRevision"])

    def test_repository_receipt_is_derived_and_ignores_only_record_self_mutation(self) -> None:
        current = self.capture_repository(self.append_source_evidence(self.bind_claim(self.initialize())))
        record = work_record.load_record(self.root, self.record_id)
        repository = record["repositories"][0]
        self.assertEqual(repository["dirtyPaths"], [])
        self.assertTrue(work_record.repository_snapshot_current(self.root, repository))
        # Later governed work-record mutations are excluded from the root source-tree receipt and
        # do not invalidate their own repository evidence.
        self.capture_identity(current)
        record = work_record.load_record(self.root, self.record_id)
        self.assertTrue(work_record.repository_snapshot_current(self.root, record["repositories"][0]))
        drift = self.root / "force-app" / "drift.txt"
        drift.parent.mkdir(parents=True, exist_ok=True)
        drift.write_text("uncommitted source drift\n", encoding="utf-8")
        self.assertFalse(work_record.repository_snapshot_current(self.root, record["repositories"][0]))

    def test_human_approval_rejects_missing_repository_receipt(self) -> None:
        current = self.prepare_waiting(include_repository=False)
        error = self.run_error(
            "approve",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            "--expected-design-hash",
            current["designHash"],
            "--approver",
            "Human Reviewer",
            "--mechanism",
            "human-terminal",
            "--approval-ref",
            "terminal:review-session-123",
        )
        self.assertIn("clean base repository snapshot", error)

    def test_blocking_question_requires_a_bound_resolution_before_approval(self) -> None:
        current = self.initialize()
        current = self.bind_claim(current)
        current = self.append_source_evidence(current)
        current = self.capture_repository(current)
        current = self.capture_identity(current)
        current = self.command(
            "add-question",
            current,
            "--role",
            "solution-designer",
            "--question-id",
            "BQ-ownership",
            "--question",
            "Is Account package-owned in this exact scope?",
            "--owner",
            "solution-designer",
        )
        current = self.transition(current, "solution-designer", "design", "draft", "Start design.")
        current = self.transition(
            current,
            "solution-designer",
            "design",
            "awaiting_human",
            "Request review.",
        )
        error = self.run_error(
            "approve",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            "--expected-design-hash",
            current["designHash"],
            "--approver",
            "Human Reviewer",
            "--mechanism",
            "human-terminal",
            "--approval-ref",
            "terminal:review-session-123",
        )
        self.assertIn("unresolved blocking questions", error)
        current = self.command(
            "resolve-question",
            current,
            "--role",
            "solution-designer",
            "--question-id",
            "BQ-ownership",
            "--resolution-ref",
            self.claim_id,
        )
        approved = self.approve(current)
        self.assertEqual(approved["state"], {"phase": "design", "status": "accepted"})

    def test_fixed_verification_profile_derives_failure_and_blocks_safe(self) -> None:
        self._write_verification_policy(exit_code=7)
        current = self.prepare_review_ready()
        verified = self.run_verification(current)
        self.assertEqual(verified["verificationStatus"], "failed")
        error = self.run_error(
            "append-review",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(verified["recordRevision"]),
            "--expected-record-hash",
            verified["recordHash"],
            "--role",
            "guardrail-reviewer",
            "--verdict",
            "SAFE",
        )
        self.assertIn("passed verification", error)

    def test_safe_label_cannot_be_fabricated_without_executed_required_profile(self) -> None:
        current = self.prepare_review_ready()
        error = self.run_error(
            "append-review",
            "--record-id",
            self.record_id,
            "--expected-revision",
            str(current["recordRevision"]),
            "--expected-record-hash",
            current["recordHash"],
            "--role",
            "guardrail-reviewer",
            "--verdict",
            "SAFE",
            "--finding",
            "A model-authored SAFE statement is not execution evidence.",
        )
        self.assertIn("passed verification", error)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            work_record.main(
                [
                    "--root",
                    str(self.root),
                    "run-verification",
                    "--status",
                    "passed",
                ]
            )

    def test_valid_derived_flow_reaches_safe_and_complete(self) -> None:
        current = self.run_verification(self.prepare_review_ready())
        self.assertEqual(current["verificationStatus"], "passed")
        reviewed = self.command(
            "append-review",
            current,
            "--role",
            "guardrail-reviewer",
            "--verdict",
            "SAFE",
            "--finding",
            "All fixed gates passed for the exact grounded snapshot.",
        )
        self.assertEqual(reviewed["state"], {"phase": "review", "status": "safe"})
        completed = self.transition(
            reviewed,
            "guardrail-reviewer",
            "complete",
            "complete",
            "Complete after the independent SAFE verdict.",
        )
        self.assertEqual(completed["state"], {"phase": "complete", "status": "complete"})
        validated = self.run_ok("validate", "--record-id", self.record_id)
        self.assertTrue(validated["valid"])

    def test_handoff_binds_exact_rules_claims_scope_and_record_hash(self) -> None:
        current = self.approve(self.prepare_waiting())
        created = self.command(
            "create-handoff",
            current,
            "--from-role",
            "solution-designer",
            "--to-role",
            "development-assistant",
            "--reason",
            "Transfer the approved grounded design.",
            "--summary",
            "Use only the persisted scope, rules, claims, and evidence.",
            "--next-phase",
            "development",
            "--next-status",
            "in_progress",
        )
        path = (
            self.root
            / ".ai"
            / "change-records"
            / self.record_id
            / "handoffs"
            / f"{created['handoffId']}.json"
        )
        handoff = json.loads(path.read_text(encoding="utf-8"))
        record = work_record.load_record(self.root, self.record_id)
        self.assertEqual(handoff["recordHash"], work_record.json_hash(record))
        self.assertEqual(handoff["groundingHash"], record["groundingHash"])
        self.assertEqual(handoff["claimRefs"], record["claimRefs"])
        self.assertEqual(handoff["ruleRefs"], record["ruleRefs"])
        handoff["claimRefs"] = []
        work_record.atomic_write_json(path, handoff)
        error = self.run_error("validate", "--record-id", self.record_id)
        self.assertIn("stale grounding", error)

    def test_handoff_fixtures_match_v2_schema(self) -> None:
        schema = json.loads((ROOT / "schemas" / "handoff-envelope.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for name in ("handoff.pending.json", "handoff.consumed.json"):
            fixture = json.loads((ROOT / "evals" / "fixtures" / name).read_text())
            errors = sorted(validator.iter_errors(fixture), key=lambda error: list(error.path))
            self.assertEqual(errors, [], f"{name}: {[error.message for error in errors]}")


if __name__ == "__main__":
    unittest.main()
