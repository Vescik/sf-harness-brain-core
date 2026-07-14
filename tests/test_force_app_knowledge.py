from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.force_app_knowledge import ForceAppKnowledge, KnowledgeBuildError


ROOT = Path(__file__).resolve().parents[1]


OBJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Engagement</label><pluralLabel>Engagements</pluralLabel>
  <deploymentStatus>Deployed</deploymentStatus><sharingModel>ReadWrite</sharingModel>
</CustomObject>
"""
FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Account__c</fullName><label>Account</label><type>Lookup</type>
  <referenceTo>Account</referenceTo><relationshipName>Engagements</relationshipName>
</CustomField>
"""
NAMED_CREDENTIAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Billing API</label><endpoint>https://billing.example.test/v1</endpoint>
  <password>never-export-this-secret</password>
</NamedCredential>
"""
APPROVAL_PROCESS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ApprovalProcess xmlns="http://soap.sforce.com/2006/04/metadata">
  <active>true</active><label>Engagement Approval v2</label>
  <entryCriteria><criteriaItems><field>Engagement__c.Status__c</field></criteriaItems></entryCriteria>
  <approvalStep><name>Step_1</name></approvalStep>
  <approvalStep><name>Step_2</name></approvalStep>
</ApprovalProcess>
"""
PERMISSION_SET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Engagement Manager</label><hasActivationRequired>false</hasActivationRequired>
</PermissionSet>
"""


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class ForceAppKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        write(
            self.root / "force-app/main/default/objects/Engagement__c/Engagement__c.object-meta.xml",
            OBJECT_XML,
        )
        write(
            self.root / "force-app/main/default/objects/Engagement__c/fields/Account__c.field-meta.xml",
            FIELD_XML,
        )
        write(
            self.root / "force-app/main/default/triggers/EngagementTrigger.trigger",
            "trigger EngagementTrigger on Engagement__c (before insert, after update) {}\n",
        )
        write(
            self.root / "force-app/main/default/namedCredentials/Billing.namedCredential-meta.xml",
            NAMED_CREDENTIAL_XML,
        )
        write(
            self.root / "force-app/main/default/lwc/engagementCard/engagementCard.js-meta.xml",
            """<LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata"><isExposed>true</isExposed><targets><target>lightning__RecordPage</target></targets></LightningComponentBundle>""",
        )
        write(
            self.root / "force-app/main/default/lwc/engagementCard/engagementCard.js",
            "import NAME from '@salesforce/schema/Engagement__c.Name';\n",
        )
        write(
            self.root
            / "force-app/main/default/approvalProcesses/Engagement__c.Engagement_Approval_v2.approvalProcess-meta.xml",
            APPROVAL_PROCESS_XML,
        )
        write(
            self.root / "force-app/main/default/permissionsets/Engagement_Manager.permissionset-meta.xml",
            PERMISSION_SET_XML,
        )
        (self.root / "schemas").mkdir()
        for name in (
            "knowledge-claim.schema.json",
            "knowledge-evidence.schema.json",
            "force-app-knowledge-inventory.schema.json",
            "force-app-knowledge-draft-manifest.schema.json",
            "force-app-knowledge-worklist.schema.json",
        ):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "config").mkdir()
        shutil.copy2(
            ROOT / "config/knowledge-policy.json",
            self.root / "config/knowledge-policy.json",
        )
        (self.root / ".ai/knowledge/claims").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_clean_inventory_generates_schema_valid_sanitized_drafts(self) -> None:
        inventory = self.builder.inventory()
        self.assertTrue(inventory["workspaceStatus"]["clean"])
        self.assertEqual("complete", inventory["completeness"]["status"])
        self.assertNotIn(
            "never-export-this-secret",
            self.builder.inventory_path.read_text(encoding="utf-8"),
        )

        manifest = self.builder.draft(
            datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        )
        # 11 claims: object, field, relation, trigger automation, approval-process automation,
        # named-credential integration, generic component-inventory for the LWC bundle and the
        # permission set, plus three AI description stubs (trigger, approval process, LWC) —
        # full coverage means no recognized component drafts nothing.
        self.assertEqual(11, manifest["claimCount"])
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in manifest["bundles"]
            if "claimFile" in bundle
        ]
        self.assertEqual(
            {
                "object-existence",
                "field-schema",
                "object-relation",
                "automation-inventory",
                "integration",
                "component-inventory",
                "component-description",
            },
            {claim["claimType"] for claim in claims},
        )
        descriptions = [c for c in claims if c["claimType"] == "component-description"]
        self.assertEqual(3, len(descriptions))
        for claim in descriptions:
            self.assertEqual("inferred", claim["assurance"])
            self.assertIn("<AGENT_", claim["assertion"]["value"]["description"])
        self.assertNotIn("runtime-behavior", {claim["claimType"] for claim in claims})
        approval = next(
            claim
            for claim in claims
            if claim["subject"]["identity"] == "Engagement__c.Engagement_Approval_v2"
        )
        self.assertEqual("automation-inventory", approval["claimType"])
        facts = approval["assertion"]["value"]["facts"]
        self.assertEqual("Engagement__c", facts["object"])
        self.assertTrue(facts["active"])
        self.assertEqual(2, facts["stepCount"])
        permission_set = next(
            claim
            for claim in claims
            if claim["subject"]["identity"] == "PermissionSet:Engagement_Manager"
        )
        self.assertEqual("component-inventory", permission_set["domain"])
        for bundle in manifest["bundles"]:
            if "claimFile" not in bundle:
                continue
            self.assertIn("scripts/knowledge_registry.py propose", bundle["command"])
            evidence = (self.root / bundle["evidenceFile"]).read_text(encoding="utf-8")
            self.assertNotIn("never-export-this-secret", evidence)

    def test_companion_meta_files_do_not_mint_duplicate_components(self) -> None:
        # X.cls-meta.xml describes X.cls (already parsed as ApexClass) — no "Cls:X" duplicate.
        # X.resource-meta.xml IS the component when the content file has no dedicated parser.
        write(
            self.root / "force-app/main/default/classes/EngagementService.cls",
            "public with sharing class EngagementService {}\n",
        )
        write(
            self.root / "force-app/main/default/classes/EngagementService.cls-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata"><apiVersion>67.0</apiVersion><status>Active</status></ApexClass>
""",
        )
        write(
            self.root / "force-app/main/default/staticresources/Assets.resource-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<StaticResource xmlns="http://soap.sforce.com/2006/04/metadata"><cacheControl>Public</cacheControl><contentType>application/zip</contentType></StaticResource>
""",
        )
        write(self.root / "force-app/main/default/staticresources/Assets.resource", "PKfake")
        write(
            self.root
            / "force-app/main/default/customMetadata/KC_Setting.Default_Limits.md-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<CustomMetadata xmlns="http://soap.sforce.com/2006/04/metadata"><label>Default Limits</label><protected>false</protected></CustomMetadata>
""",
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "companions"], cwd=self.root, check=True)
        inventory = self.builder.inventory()
        ids = [component["id"] for component in inventory["components"]]
        self.assertIn("ApexClass:EngagementService", ids)
        self.assertNotIn("Cls:EngagementService", ids)
        self.assertIn("StaticResource:Assets", ids)
        self.assertIn("CustomMetadata:KC_Setting.Default_Limits", ids)
        self.assertNotIn("Md:KC_Setting.Default_Limits", ids)
        generic_paths = {item["path"] for item in inventory["genericFiles"]}
        self.assertNotIn(
            "force-app/main/default/staticresources/Assets.resource", generic_paths
        )

    def test_metadata_type_filter_drafts_one_type_per_batch(self) -> None:
        self.builder.inventory()
        manifest = self.builder.draft(
            datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc), "ApprovalProcess"
        )
        self.assertEqual("ApprovalProcess", manifest["metadataTypeFilter"])
        # One automation claim + one description stub for the single approval process.
        self.assertEqual(2, manifest["claimCount"])
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in manifest["bundles"]
            if "claimFile" in bundle
        ]
        self.assertTrue(
            all("Engagement_Approval_v2" in claim["subject"]["identity"] for claim in claims)
        )
        with self.assertRaisesRegex(KnowledgeBuildError, "available types"):
            self.builder.draft(
                datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc), "NoSuchType"
            )

    def test_drafts_include_empty_candidate_keywords(self) -> None:
        self.builder.inventory()
        manifest = self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in manifest["bundles"]
            if "claimFile" in bundle
        ]
        for claim in claims:
            self.assertEqual([], claim["keywords"])
            self.assertEqual([], claim["candidateKeywords"])

    def test_worklist_derives_component_status_from_ground_truth(self) -> None:
        self.builder.inventory()
        # Fresh registry, no drafts: everything is pending.
        result = self.builder.worklist()
        self.assertEqual({"pending"}, set(result["counts"]))
        self.assertTrue(all(item["status"] == "pending" for item in result["items"]))
        self.assertTrue(
            all(state["state"] == "missing" for item in result["items"] for state in item["claims"])
        )

        # Current drafts flip components to drafted.
        manifest = self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        result = self.builder.worklist()
        self.assertEqual({"drafted"}, set(result["counts"]))

        # Walk one single-claim component (the permission set) through the claim lifecycle.
        bundle = next(
            item
            for item in manifest["bundles"]
            if "claimFile" in item
            and yaml.safe_load((self.root / item["claimFile"]).read_text(encoding="utf-8"))[
                "subject"
            ]["identity"]
            == "PermissionSet:Engagement_Manager"
        )
        claim = yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
        canonical_path = self.root / ".ai/knowledge/claims" / f"{claim['claimId']}.yaml"

        def component_status() -> str:
            worklist = self.builder.worklist(metadata_type="PermissionSet")
            self.assertEqual(1, len(worklist["items"]))
            return worklist["items"][0]["status"]

        canonical_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
        self.assertEqual("proposed", component_status())

        verified = dict(claim, status="verified", revision=2, reviewRef="KREV-TEST-1",
                        verifiedAt="2026-07-10T12:00:00Z")
        canonical_path.write_text(yaml.safe_dump(verified, sort_keys=False), encoding="utf-8")
        self.assertEqual("verified-current", component_status())

        stale = dict(verified, evidenceRefs=["KEVD-SOMETHING-ELSE-0000000001"])
        canonical_path.write_text(yaml.safe_dump(stale, sort_keys=False), encoding="utf-8")
        self.assertEqual("stale-refresh", component_status())

        rejected = dict(claim, status="rejected", revision=2, reviewRef="KREV-TEST-1")
        canonical_path.write_text(yaml.safe_dump(rejected, sort_keys=False), encoding="utf-8")
        worklist = self.builder.worklist(metadata_type="PermissionSet")
        self.assertEqual("blocked", worklist["items"][0]["status"])
        self.assertIn("rejected", worklist["items"][0]["reason"])

    def test_worklist_write_persists_schema_valid_derived_view(self) -> None:
        self.builder.inventory()
        result = self.builder.worklist(metadata_type="CustomObject", write=True)
        path = self.root / result["path"]
        self.assertTrue(path.is_file())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("force-app-knowledge-worklist", saved["kind"])
        self.assertEqual("CustomObject", saved["metadataTypeFilter"])
        self.assertNotIn("path", saved)
        with self.assertRaisesRegex(KnowledgeBuildError, "available types"):
            self.builder.worklist(metadata_type="NoSuchType")

    def test_worklist_requires_a_current_inventory(self) -> None:
        with self.assertRaisesRegex(KnowledgeBuildError, "run inventory first"):
            self.builder.worklist()
        self.builder.inventory()
        field = self.root / "force-app/main/default/objects/Engagement__c/fields/Account__c.field-meta.xml"
        field.write_text(FIELD_XML.replace("Account</label>", "Client Account</label>"), encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeBuildError, "changed after inventory"):
            self.builder.worklist()

    def test_dirty_or_changed_source_cannot_be_commit_bound_evidence(self) -> None:
        self.builder.inventory()
        field = self.root / "force-app/main/default/objects/Engagement__c/fields/Account__c.field-meta.xml"
        field.write_text(FIELD_XML.replace("Account</label>", "Client Account</label>"), encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeBuildError, "changed after inventory"):
            self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

        inventory = self.builder.inventory()
        self.assertFalse(inventory["workspaceStatus"]["clean"])
        with self.assertRaisesRegex(KnowledgeBuildError, "not clean at HEAD"):
            self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
