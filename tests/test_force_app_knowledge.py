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
        # 8 claims: object, field, relation, trigger automation, approval-process automation,
        # named-credential integration, plus generic component-inventory for the LWC bundle and
        # the permission set — full coverage means no recognized component drafts nothing.
        self.assertEqual(8, manifest["claimCount"])
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
            },
            {claim["claimType"] for claim in claims},
        )
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
            if claim["subject"]["identity"] == "Permissionset:Engagement_Manager"
        )
        self.assertEqual("component-inventory", permission_set["domain"])
        for bundle in manifest["bundles"]:
            if "claimFile" not in bundle:
                continue
            self.assertIn("scripts/knowledge_registry.py propose", bundle["command"])
            evidence = (self.root / bundle["evidenceFile"]).read_text(encoding="utf-8")
            self.assertNotIn("never-export-this-secret", evidence)

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
