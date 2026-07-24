from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.force_app_knowledge import (
    ForceAppKnowledge,
    KnowledgeBuildError,
    canonical,
    digest_bytes,
    sanitize_literal,
    stable_id,
)


ROOT = Path(__file__).resolve().parents[1]


OBJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessEngagement</label><pluralLabel>HarnessEngagements</pluralLabel>
  <deploymentStatus>Deployed</deploymentStatus><sharingModel>ReadWrite</sharingModel>
</CustomObject>
"""
FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Account__c</fullName><label>Account</label><type>Lookup</type>
  <referenceTo>Account</referenceTo><relationshipName>HarnessEngagements</relationshipName>
</CustomField>
"""
NAMED_CREDENTIAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessBilling API</label><endpoint>https://billing.example.test/v1</endpoint>
  <password>never-export-this-secret</password>
</NamedCredential>
"""
APPROVAL_PROCESS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ApprovalProcess xmlns="http://soap.sforce.com/2006/04/metadata">
  <active>true</active><label>HarnessEngagement Approval v2</label>
  <entryCriteria><criteriaItems><field>HarnessEngagement__c.Status__c</field></criteriaItems></entryCriteria>
  <approvalStep><name>Step_1</name></approvalStep>
  <approvalStep><name>Step_2</name></approvalStep>
</ApprovalProcess>
"""
PERMISSION_SET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessEngagement Manager</label><hasActivationRequired>false</hasActivationRequired>
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
            self.root / "force-app/main/default/objects/HarnessEngagement__c/HarnessEngagement__c.object-meta.xml",
            OBJECT_XML,
        )
        write(
            self.root / "force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml",
            FIELD_XML,
        )
        write(
            self.root / "force-app/main/default/triggers/HarnessEngagementTrigger.trigger",
            "trigger HarnessEngagementTrigger on HarnessEngagement__c (before insert, after update) {}\n",
        )
        write(
            self.root / "force-app/main/default/namedCredentials/HarnessBilling.namedCredential-meta.xml",
            NAMED_CREDENTIAL_XML,
        )
        write(
            self.root / "force-app/main/default/lwc/harnessEngagementCard/harnessEngagementCard.js-meta.xml",
            """<LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata"><isExposed>true</isExposed><targets><target>lightning__RecordPage</target></targets></LightningComponentBundle>""",
        )
        write(
            self.root / "force-app/main/default/lwc/harnessEngagementCard/harnessEngagementCard.js",
            "import NAME from '@salesforce/schema/HarnessEngagement__c.Name';\n",
        )
        write(
            self.root
            / "force-app/main/default/approvalProcesses/HarnessEngagement__c.HarnessEngagement_Approval_v2.approvalProcess-meta.xml",
            APPROVAL_PROCESS_XML,
        )
        write(
            self.root / "force-app/main/default/permissionsets/HarnessEngagement_Manager.permissionset-meta.xml",
            PERMISSION_SET_XML,
        )
        (self.root / "schemas").mkdir()
        for name in (
            "knowledge-claim.schema.json",
            "knowledge-evidence.schema.json",
            "force-app-knowledge-inventory.schema.json",
            "force-app-knowledge-draft-manifest.schema.json",
            "force-app-knowledge-worklist.schema.json",
            "force-app-relations-worklist.schema.json",
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
            if claim["subject"]["identity"] == "HarnessEngagement__c.HarnessEngagement_Approval_v2"
        )
        self.assertEqual("automation-inventory", approval["claimType"])
        facts = approval["assertion"]["value"]["facts"]
        self.assertEqual("HarnessEngagement__c", facts["object"])
        self.assertTrue(facts["active"])
        self.assertEqual(2, facts["stepCount"])
        permission_set = next(
            claim
            for claim in claims
            if claim["subject"]["identity"] == "PermissionSet:HarnessEngagement_Manager"
        )
        self.assertEqual("component-inventory", permission_set["domain"])
        for bundle in manifest["bundles"]:
            if "claimFile" not in bundle:
                continue
            # Manifest commands must run on Windows terminals too: a bare `python`
            # launcher with forward-slash paths, never a venv-relative interpreter.
            self.assertTrue(
                bundle["command"].startswith("python scripts/knowledge_registry.py propose"),
                bundle["command"],
            )
            self.assertNotIn(".venv", bundle["command"])
            self.assertNotIn("\\", bundle["command"])
            evidence = (self.root / bundle["evidenceFile"]).read_text(encoding="utf-8")
            self.assertNotIn("never-export-this-secret", evidence)

    def test_companion_meta_files_do_not_mint_duplicate_components(self) -> None:
        # X.cls-meta.xml describes X.cls (already parsed as ApexClass) — no "Cls:X" duplicate.
        # X.resource-meta.xml IS the component when the content file has no dedicated parser.
        write(
            self.root / "force-app/main/default/classes/HarnessEngagementService.cls",
            "public with sharing class HarnessEngagementService {}\n",
        )
        write(
            self.root / "force-app/main/default/classes/HarnessEngagementService.cls-meta.xml",
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
        self.assertIn("ApexClass:HarnessEngagementService", ids)
        self.assertNotIn("Cls:HarnessEngagementService", ids)
        self.assertIn("StaticResource:Assets", ids)
        # Collector 1.5.0: cmdt record identity carries the __mdt type qualifier.
        self.assertIn("CustomMetadata:KC_Setting__mdt.Default_Limits", ids)
        self.assertNotIn("Md:KC_Setting.Default_Limits", ids)
        self.assertNotIn("CustomMetadata:KC_Setting.Default_Limits", ids)
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
            all("HarnessEngagement_Approval_v2" in claim["subject"]["identity"] for claim in claims)
        )
        with self.assertRaisesRegex(KnowledgeBuildError, "available types"):
            self.builder.draft(
                datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc), "NoSuchType"
            )

    def test_drafts_seed_candidate_keywords_from_usage(self) -> None:
        self.builder.inventory()
        manifest = self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in manifest["bundles"]
            if "claimFile" in bundle
        ]
        for claim in claims:
            # keywords always stays empty until a curated taxonomy term is approved.
            self.assertEqual([], claim["keywords"])
            # candidateKeywords is advisory and never exceeds the schema's cap of five.
            self.assertLessEqual(len(claim["candidateKeywords"]), 5)
        # The trigger's usage registry (operates on HarnessEngagement__c) seeds an advisory candidate term.
        trigger = next(
            claim
            for claim in claims
            if claim["claimType"] == "automation-inventory"
            and claim["subject"]["identity"] == "HarnessEngagementTrigger"
        )
        self.assertIn("harnessengagement", trigger["candidateKeywords"])

    def test_flow_usage_registry_records_objects_and_fields(self) -> None:
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessEngagement Router</label><status>Active</status><processType>AutoLaunchedFlow</processType>
  <start><object>HarnessEngagement__c</object><triggerType>RecordAfterSave</triggerType><recordTriggerType>Create</recordTriggerType></start>
  <recordLookups><name>GetAccount</name><object>Account</object><queriedFields>Name</queriedFields></recordLookups>
  <recordUpdates><name>SetStatus</name><object>HarnessEngagement__c</object>
    <inputAssignments><field>Status__c</field></inputAssignments></recordUpdates>
  <actionCalls><name>Notify</name><actionType>apex</actionType><actionName>HarnessEngagementNotifier</actionName></actionCalls>
  <decisions><name>IsActive</name></decisions>
</Flow>
"""
        write(
            self.root / "force-app/main/default/flows/HarnessEngagementRouter.flow-meta.xml",
            flow_xml,
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "flow"], cwd=self.root, check=True)
        inventory = self.builder.inventory()
        flow = next(c for c in inventory["components"] if c["metadataType"] == "Flow")
        facts = flow["facts"]
        self.assertEqual(["Account", "HarnessEngagement__c"], facts["referencedObjects"])
        self.assertEqual(1, facts["elementCounts"]["decisions"])
        references = {(ref["kind"], ref["target"]) for ref in flow["references"]}
        self.assertIn(("reads-field", "Account.Name"), references)
        self.assertIn(("writes-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("invokes-apex", "HarnessEngagementNotifier"), references)
        self.assertNotIn("errorCatalog", flow["facts"])

    FLOW_ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Discount Guard</label><status>Active</status><processType>AutoLaunchedFlow</processType>
  <start>
    <object>HarnessEngagement__c</object><triggerType>RecordBeforeSave</triggerType><recordTriggerType>Update</recordTriggerType>
    <connector><targetReference>Check_Tier</targetReference></connector>
  </start>
  <decisions>
    <name>Check_Tier</name><label>Check Tier</label>
    <rules>
      <name>Standard_Tier</name><label>Standard Tier</label>
      <conditions>
        <leftValueReference>$Record.Tier__c</leftValueReference>
        <operator>EqualTo</operator>
        <rightValue><stringValue>Standard</stringValue></rightValue>
      </conditions>
      <connector><targetReference>Block_Discount</targetReference></connector>
    </rules>
    <defaultConnector><targetReference>Set_Status</targetReference></defaultConnector>
  </decisions>
  <customErrors>
    <name>Block_Discount</name><label>Block Discount</label>
    <customErrorMessages>
      <errorMessage>Discount cannot exceed 20% for {!$Label.Tier_Name}.</errorMessage>
      <isFieldError>true</isFieldError>
      <fieldSelection>Discount__c</fieldSelection>
    </customErrorMessages>
  </customErrors>
  <recordUpdates>
    <name>Set_Status</name><object>HarnessEngagement__c</object>
    <inputAssignments><field>Status__c</field></inputAssignments>
    <connector><targetReference>Confirm_Screen</targetReference></connector>
    <faultConnector><targetReference>Confirm_Screen</targetReference></faultConnector>
  </recordUpdates>
  <screens>
    <name>Confirm_Screen</name><label>Confirm</label>
    <fields>
      <name>Discount_Input</name>
      <validationRule>
        <errorMessage>Enter a discount below the tier cap.</errorMessage>
        <formulaExpression>{!Discount_Input} &lt;= 0.2</formulaExpression>
      </validationRule>
    </fields>
  </screens>
</Flow>
"""
    CUSTOM_LABELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomLabels xmlns="http://soap.sforce.com/2006/04/metadata">
  <labels><fullName>Tier_Name</fullName><value>Standard tier</value></labels>
</CustomLabels>
"""

    def test_flow_error_catalog_captures_declared_error_surfaces(self) -> None:
        write(
            self.root / "force-app/main/default/flows/DiscountGuard.flow-meta.xml",
            self.FLOW_ERROR_XML,
        )
        write(
            self.root / "force-app/main/default/labels/CustomLabels.labels-meta.xml",
            self.CUSTOM_LABELS_XML,
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "error-flow"], cwd=self.root, check=True)
        inventory = self.builder.inventory()
        flow = next(c for c in inventory["components"] if c["metadataType"] == "Flow")
        facts = flow["facts"]
        self.assertEqual(1, facts["elementCounts"]["customErrors"])
        catalog = {entry["kind"]: entry for entry in facts["errorCatalog"]}
        self.assertEqual({"custom-error", "fault-path", "screen-validation"}, set(catalog))

        custom_error = catalog["custom-error"]
        self.assertEqual("Block_Discount", custom_error["component"])
        self.assertEqual("Block Discount", custom_error["componentLabel"])
        self.assertEqual(
            "Discount cannot exceed 20% for {!$Label.Tier_Name}.", custom_error["errorMessage"]
        )
        self.assertEqual(
            "Discount cannot exceed 20% for Standard tier.",
            custom_error["resolvedErrorMessage"],
        )
        self.assertTrue(custom_error["isFieldError"])
        self.assertEqual("Discount__c", custom_error["fieldSelection"])
        self.assertEqual(
            "HarnessEngagement__c / Update / RecordBeforeSave", custom_error["triggerContext"]
        )
        self.assertEqual(
            [[{
                "decision": "Check_Tier",
                "outcome": "Standard_Tier",
                "outcomeLabel": "Standard Tier",
                "conditions": ["$Record.Tier__c EqualTo Standard"],
            }]],
            custom_error["paths"],
        )
        self.assertNotIn("pathsTruncated", custom_error)

        fault = catalog["fault-path"]
        self.assertEqual("Set_Status", fault["component"])
        self.assertEqual("Confirm_Screen", fault["faultTarget"])
        self.assertEqual([[{"decision": "Check_Tier", "default": True}]], fault["paths"])

        screen = catalog["screen-validation"]
        self.assertEqual("Discount_Input", screen["component"])
        self.assertEqual("Confirm", screen["componentLabel"])
        self.assertEqual("Enter a discount below the tier cap.", screen["errorMessage"])
        self.assertEqual("{!Discount_Input} <= 0.2", screen["condition"])
        self.assertNotIn("resolvedErrorMessage", screen)
        # Normal and fault connectors both reach the screen, but the decision scenario is one.
        self.assertEqual([[{"decision": "Check_Tier", "default": True}]], screen["paths"])

        references = {(ref["kind"], ref["target"]) for ref in flow["references"]}
        self.assertIn(("references-field", "HarnessEngagement__c.Discount__c"), references)

        claims = self.builder.candidate_claims(flow)
        statement = next(
            claim for claim in claims if claim["claimType"] == "automation-inventory"
        )["statement"]
        self.assertIn("3 error surface(s)", statement)
        self.assertIn("Discount cannot exceed 20%", statement)

    def test_flow_error_paths_survive_loops_and_report_every_route(self) -> None:
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Loop Guard</label><status>Draft</status><processType>AutoLaunchedFlow</processType>
  <start><connector><targetReference>First_Gate</targetReference></connector></start>
  <decisions>
    <name>First_Gate</name>
    <rules><name>Fast_Lane</name><connector><targetReference>Raise_Error</targetReference></connector></rules>
    <defaultConnector><targetReference>Each_Item</targetReference></defaultConnector>
  </decisions>
  <loops>
    <name>Each_Item</name>
    <nextValueConnector><targetReference>Tag_Item</targetReference></nextValueConnector>
    <noMoreValuesConnector><targetReference>Second_Gate</targetReference></noMoreValuesConnector>
  </loops>
  <assignments>
    <name>Tag_Item</name>
    <connector><targetReference>Each_Item</targetReference></connector>
  </assignments>
  <decisions>
    <name>Second_Gate</name>
    <rules><name>Slow_Lane</name><connector><targetReference>Raise_Error</targetReference></connector></rules>
  </decisions>
  <customErrors>
    <name>Raise_Error</name>
    <customErrorMessages><errorMessage>Blocked.</errorMessage></customErrorMessages>
  </customErrors>
</Flow>
"""
        path = self.root / "force-app/main/default/flows/LoopGuard.flow-meta.xml"
        write(path, flow_xml)
        flow = self.builder.parse_flow(path)
        entry = flow["facts"]["errorCatalog"][0]
        self.assertEqual("Blocked.", entry["errorMessage"])
        self.assertEqual(
            [
                [{"decision": "First_Gate", "outcome": "Fast_Lane"}],
                [
                    {"decision": "First_Gate", "default": True},
                    {"decision": "Second_Gate", "outcome": "Slow_Lane"},
                ],
            ],
            entry["paths"],
        )
        self.assertNotIn("pathsTruncated", entry)

    def test_error_surface_extraction_toggle_disables_the_catalog(self) -> None:
        write(
            self.root / "config/knowledge-extraction.json",
            json.dumps({"$schema": "x", "schemaVersion": 1, "errorSurfaceExtraction": False}),
        )
        flow_path = self.root / "force-app/main/default/flows/DiscountGuard.flow-meta.xml"
        write(flow_path, self.FLOW_ERROR_XML)
        builder = ForceAppKnowledge(self.root)
        flow = builder.parse_flow(flow_path)
        self.assertNotIn("errorCatalog", flow["facts"])
        self.assertNotIn(
            ("references-field", "HarnessEngagement__c.Discount__c"),
            {(ref["kind"], ref["target"]) for ref in flow["references"]},
        )
        vr_path = (
            self.root
            / "force-app/main/default/objects/HarnessEngagement__c/validationRules/Status_Required.validationRule-meta.xml"
        )
        write(
            vr_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Status_Required</fullName><active>true</active>
  <errorConditionFormula>ISBLANK(Status__c)</errorConditionFormula>
  <errorMessage>Status is required</errorMessage><errorDisplayField>Status__c</errorDisplayField>
</ValidationRule>
""",
        )
        vr = builder.parse_validation_rule(vr_path)
        self.assertTrue(vr["facts"]["errorMessagePresent"])
        self.assertNotIn("errorCatalog", vr["facts"])

    def test_validation_rule_and_layout_get_dedicated_parsers(self) -> None:
        write(
            self.root
            / "force-app/main/default/objects/HarnessEngagement__c/validationRules/Status_Required.validationRule-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Status_Required</fullName><active>true</active>
  <errorConditionFormula>ISBLANK(Status__c)</errorConditionFormula>
  <errorMessage>Status is required</errorMessage><errorDisplayField>Status__c</errorDisplayField>
</ValidationRule>
""",
        )
        write(
            self.root / "force-app/main/default/layouts/HarnessEngagement__c-HarnessEngagement Layout.layout-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Layout xmlns="http://soap.sforce.com/2006/04/metadata">
  <layoutSections><layoutColumns><layoutItems><field>Status__c</field></layoutItems></layoutColumns></layoutSections>
  <relatedLists><relatedList>RelatedContactList</relatedList></relatedLists>
</Layout>
""",
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "vr-layout"], cwd=self.root, check=True)
        inventory = self.builder.inventory()
        by_type = {c["metadataType"]: c for c in inventory["components"]}
        self.assertIn("ValidationRule", by_type)
        self.assertIn("Layout", by_type)
        vr = by_type["ValidationRule"]
        self.assertEqual("HarnessEngagement__c", vr["facts"]["object"])
        self.assertTrue(vr["facts"]["errorMessagePresent"])
        catalog_entry = vr["facts"]["errorCatalog"][0]
        self.assertEqual("validation-rule", catalog_entry["kind"])
        self.assertEqual("Status_Required", catalog_entry["component"])
        self.assertEqual("Status is required", catalog_entry["errorMessage"])
        self.assertEqual("ISBLANK(Status__c)", catalog_entry["condition"])
        self.assertEqual("Status__c", catalog_entry["fieldSelection"])
        self.assertNotIn("resolvedErrorMessage", catalog_entry)
        self.assertIn(
            ("references-field", "HarnessEngagement__c.Status__c"),
            {(ref["kind"], ref["target"]) for ref in vr["references"]},
        )
        layout = by_type["Layout"]
        self.assertEqual("HarnessEngagement__c", layout["facts"]["object"])
        self.assertIn(
            ("places-field", "HarnessEngagement__c.Status__c"),
            {(ref["kind"], ref["target"]) for ref in layout["references"]},
        )

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
            == "PermissionSet:HarnessEngagement_Manager"
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

    APEX_SERVICE = """public with sharing class HarnessEngagementService {
    public void run() {
        List<HarnessEngagement__c> rows = [
            SELECT Id, Name, Status__c, (SELECT Id FROM Contacts)
            FROM HarnessEngagement__c
            WHERE Status__c = 'Open' AND OwnerId != null AND Name LIKE :prefix
            ORDER BY CreatedDate DESC
            LIMIT 10
        ];
        HarnessEngagement__c current = rows[0];
        current.Status__c = 'Closed';
        Account related = [SELECT Id FROM Account WHERE Id = :current.Account__c];
        System.debug(related.Industry);
        related.clone();
        update current;
        HarnessEngagementNotifier.notifyOwner(current);
    }
}
"""

    def apex_component(self, builder=None):
        write(
            self.root / "force-app/main/default/classes/HarnessEngagementService.cls",
            self.APEX_SERVICE,
        )
        target = builder or self.builder
        return target.parse_apex(
            self.root / "force-app/main/default/classes/HarnessEngagementService.cls", "ApexClass"
        )

    def test_apex_soql_field_and_variable_heuristics(self) -> None:
        component = self.apex_component()
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        # SELECT-list fields, standard fields included; subquery content dropped.
        self.assertIn(("soql-field", "HarnessEngagement__c.Name"), references)
        self.assertIn(("soql-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("soql-field", "Account.Id"), references)
        self.assertNotIn(("soql-field", "HarnessEngagement__c.Contacts"), references)
        # WHERE-clause fields via comparison and LIKE operators; bind vars/keywords excluded.
        self.assertIn(("soql-field", "HarnessEngagement__c.OwnerId"), references)
        no_keywords = {
            target for kind, target in references if kind == "soql-field"
        }
        self.assertFalse({t for t in no_keywords if t.endswith((".LIMIT", ".ORDER", ".null"))})
        # Local variable resolution: declared sObject vars map member reads to Object.Field;
        # method calls are excluded.
        self.assertIn(("var-field-ref", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("var-field-ref", "Account.Industry"), references)
        self.assertNotIn(("var-field-ref", "Account.clone"), references)
        # The invokes-class heuristic still excludes system types.
        invoked = {target for kind, target in references if kind == "invokes-class"}
        self.assertIn("HarnessEngagementNotifier", invoked)
        self.assertNotIn("System", invoked)

    def test_extraction_config_overrides_and_defaults(self) -> None:
        # Defaults apply without a config file.
        self.assertEqual(300, self.builder.max_usage_refs)
        self.assertTrue(self.builder.soql_field_extraction)
        self.assertTrue(self.builder.local_variable_resolution)
        # Local config tunes the extractor: caps, extra system types, feature switches.
        (self.root / "config/knowledge-extraction.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "maxUsageRefs": 5,
                    "additionalSystemTypes": ["HarnessEngagementNotifier"],
                    "soqlFieldExtraction": False,
                    "localVariableResolution": False,
                }
            ),
            encoding="utf-8",
        )
        tuned = ForceAppKnowledge(self.root)
        self.assertEqual(5, tuned.max_usage_refs)
        component = self.apex_component(tuned)
        kinds = {ref["kind"] for ref in component["references"]}
        self.assertNotIn("soql-field", kinds)
        self.assertNotIn("var-field-ref", kinds)
        self.assertNotIn(
            "HarnessEngagementNotifier",
            {ref["target"] for ref in component["references"] if ref["kind"] == "invokes-class"},
        )

    def test_refresh_selects_only_drifted_and_expiring_claims(self) -> None:
        self.builder.inventory()
        manifest = self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        claims_root = self.root / ".ai/knowledge/claims"
        by_type: dict[str, dict] = {}
        for bundle in manifest["bundles"]:
            if "claimFile" not in bundle:
                continue
            claim = yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            verified = dict(
                claim,
                status="verified",
                revision=2,
                reviewRef="KREV-TEST-1",
                verifiedAt="2026-07-10T12:00:00Z",
                reviewBy="2027-07-10T12:00:00Z",
            )
            (claims_root / f"{claim['claimId']}.yaml").write_text(
                yaml.safe_dump(verified, sort_keys=False), encoding="utf-8"
            )
            by_type.setdefault(claim["claimType"], verified)

        now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
        result = self.builder.refresh(now)
        self.assertEqual(0, result["refreshSelected"])
        self.assertEqual("no-op", result["reviewStatus"])

        def rewrite(record: dict, **overrides) -> dict:
            updated = dict(record, **overrides)
            (claims_root / f"{record['claimId']}.yaml").write_text(
                yaml.safe_dump(updated, sort_keys=False), encoding="utf-8"
            )
            return updated

        expired = rewrite(by_type["component-inventory"], reviewBy="2026-07-01T00:00:00Z")
        expiring = rewrite(by_type["object-existence"], reviewBy="2026-08-01T00:00:00Z")
        drifted = rewrite(by_type["field-schema"], evidenceRefs=["KEVD-SOMETHING-ELSE-0000000001"])

        # Dry run reports the selection without touching the drafts workspace.
        manifest_before = (self.root / ".cache/knowledge-proposals/force-app-drafts/manifest.json").read_bytes()
        preview = self.builder.refresh(now, warn_days=30, dry_run=True)
        self.assertTrue(preview["dryRun"])
        self.assertEqual(3, preview["refreshSelected"])
        self.assertEqual(1, preview["driftCount"])
        self.assertEqual(1, preview["expiredCount"])
        self.assertEqual(1, preview["expiringCount"])
        self.assertEqual(
            {expired["claimId"], expiring["claimId"], drifted["claimId"]},
            {entry["claimId"] for entry in preview["selection"]},
        )
        self.assertEqual(
            manifest_before,
            (self.root / ".cache/knowledge-proposals/force-app-drafts/manifest.json").read_bytes(),
        )

        # Default horizon: drift and expired only; expiring claims wait for warn-days.
        result = self.builder.refresh(now)
        self.assertEqual(2, result["refreshSelected"])
        self.assertEqual(0, result["expiringCount"])
        self.assertEqual(2, result["claimCount"])
        drafted_ids = {
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))["claimId"]
            for bundle in result["bundles"]
            if "claimFile" in bundle
        }
        self.assertEqual({expired["claimId"], drifted["claimId"]}, drafted_ids)

        # The limit caps a run and reports the remainder for the next pass.
        capped = self.builder.refresh(now, warn_days=30, limit=1, dry_run=True)
        self.assertEqual(1, capped["refreshSelected"])
        self.assertEqual(2, capped["remaining"])

    def test_coverage_summarizes_documentation_state(self) -> None:
        self.builder.inventory()
        # No claims yet: everything undocumented, 0% coverage, all queued to document next.
        result = self.builder.coverage(write=True)
        self.assertEqual("force-app-knowledge-coverage", result["kind"])
        self.assertEqual(0, result["totals"]["documented"])
        self.assertGreater(result["totals"]["undocumented"], 0)
        self.assertEqual(0, result["totals"]["coveragePercent"])
        self.assertEqual(result["totals"]["undocumented"], len(result["documentNext"]))
        self.assertIn("CustomObject", result["byMetadataType"])
        self.assertTrue(
            (self.root / ".cache/knowledge-proposals/force-app-coverage.json").is_file()
        )

        # Verified claim citing the component's current evidence -> documented.
        inventory = json.loads(self.builder.inventory_path.read_text(encoding="utf-8"))
        obj = next(c for c in inventory["components"] if c["metadataType"] == "CustomObject")
        candidate = self.builder.candidate_claims(obj)[0]
        claim_id = self.builder.expected_claim_id(candidate)
        current_evidence = stable_id(
            "KEVD", obj["id"], f"repo-{digest_bytes(canonical(obj).encode('utf-8'))}"
        )
        claim_file = self.root / ".ai/knowledge/claims" / f"{claim_id}.yaml"
        claim_file.write_text(
            yaml.safe_dump(
                {"revision": 2, "status": "verified", "evidenceRefs": [current_evidence]}
            ),
            encoding="utf-8",
        )
        documented = self.builder.coverage()
        self.assertEqual(1, documented["byMetadataType"]["CustomObject"]["documented"])

        # Same claim citing stale evidence (source drifted since verification) -> drifted.
        claim_file.write_text(
            yaml.safe_dump(
                {"revision": 2, "status": "verified", "evidenceRefs": ["KEVD-STALE-0000000001"]}
            ),
            encoding="utf-8",
        )
        drifted = self.builder.coverage()
        self.assertEqual(1, drifted["byMetadataType"]["CustomObject"]["drifted"])
        self.assertTrue(any(e["status"] == "stale-refresh" for e in drifted["documentNext"]))

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

    def test_dashboard_renders_with_graceful_panels_and_escaping(self) -> None:
        # Without an inventory the coverage/relation panels degrade to "unavailable" and the
        # command still succeeds; nothing raises on a store this root does not carry.
        result = self.builder.dashboard()
        page_path = self.root / "output/knowledge-dashboard.html"
        self.assertTrue(page_path.is_file())
        self.assertEqual("unavailable", result["sections"]["coverage"])
        page = page_path.read_text(encoding="utf-8")
        self.assertIn("unavailable", page)
        self.assertNotIn("<script", page)

        # With an inventory, coverage renders; a hostile statement in a claim is escaped.
        self.builder.inventory()
        manifest = self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        bundle = next(item for item in manifest["bundles"] if "claimFile" in item)
        claim = yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
        claim["candidateKeywords"] = ["<script>alert(1)</script>"]
        (self.root / ".ai/knowledge/claims" / f"{claim['claimId']}.yaml").write_text(
            yaml.safe_dump(claim, sort_keys=False), encoding="utf-8"
        )
        result = self.builder.dashboard()
        self.assertEqual("ok", result["sections"]["coverage"])
        page = page_path.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_dashboard_guard_allows_every_role_with_bounded_flags(self) -> None:
        from scripts import copilot_role_guard as role_guard

        for role in (
            "solution-designer",
            "config-investigator",
            "knowledge-curator",
            "development-assistant",
            "test-strategist",
            "guardrail-reviewer",
        ):
            with self.subTest(role=role):
                self.assertTrue(
                    role_guard.force_app_knowledge_command_allowed(["dashboard"], role)
                )
                self.assertTrue(
                    role_guard.force_app_knowledge_command_allowed(
                        ["dashboard", "--warn-days", "45"], role
                    )
                )
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["dashboard", "--warn-days", "9999"], "solution-designer"
            )
        )
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["dashboard", "--unknown"], "solution-designer"
            )
        )
        # The all-roles carve-out never leaks into the drafting commands.
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(["inventory"], "solution-designer")
        )

    def test_worklist_requires_a_current_inventory(self) -> None:
        with self.assertRaisesRegex(KnowledgeBuildError, "run inventory first"):
            self.builder.worklist()
        self.builder.inventory()
        field = self.root / "force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml"
        field.write_text(FIELD_XML.replace("Account</label>", "Client Account</label>"), encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeBuildError, "changed after inventory"):
            self.builder.worklist()

    def test_dirty_or_changed_source_cannot_be_commit_bound_evidence(self) -> None:
        self.builder.inventory()
        field = self.root / "force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml"
        field.write_text(FIELD_XML.replace("Account</label>", "Client Account</label>"), encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeBuildError, "changed after inventory"):
            self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

        inventory = self.builder.inventory()
        self.assertFalse(inventory["workspaceStatus"]["clean"])
        with self.assertRaisesRegex(KnowledgeBuildError, "not clean at HEAD"):
            self.builder.draft(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))


NEW_STYLE_NAMED_CREDENTIAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessBilling API v2</label>
  <namedCredentialType>SecuredEndpoint</namedCredentialType>
  <namedCredentialParameters>
    <parameterName>url</parameterName>
    <parameterType>Url</parameterType>
    <parameterValue>https://api.billing.example.test/v2/base?tenant=42</parameterValue>
  </namedCredentialParameters>
  <namedCredentialParameters>
    <parameterName>X-Api-Key</parameterName>
    <parameterType>HttpHeader</parameterType>
    <parameterValue>never-export-this-secret</parameterValue>
  </namedCredentialParameters>
</NamedCredential>
"""


class DefectBatchTests(unittest.TestCase):
    """Phase 1 defect fixes: type-name minting, Apex meta facts, tab gating, NC endpoints."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        (self.root / "force-app/main/default").mkdir(parents=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generic_token_type_names(self) -> None:
        cases = {
            "Home.flexipage-meta.xml": ("FlexiPage", "<FlexiPage><masterLabel>Home</masterLabel></FlexiPage>"),
            "HarnessBilling.dataSource-meta.xml": ("ExternalDataSource", "<ExternalDataSource><label>HarnessBilling</label></ExternalDataSource>"),
            "Ops.permissionsetgroup-meta.xml": ("PermissionSetGroup", "<PermissionSetGroup><label>Ops</label></PermissionSetGroup>"),
            "Ops_Mute.mutingpermissionset-meta.xml": ("MutingPermissionSet", "<MutingPermissionSet><label>Ops Mute</label></MutingPermissionSet>"),
            "Azure.authprovider-meta.xml": ("AuthProvider", "<AuthProvider><friendlyName>Azure</friendlyName></AuthProvider>"),
        }
        for filename, (expected_type, xml) in cases.items():
            path = self.root / "force-app/main/default/misc" / filename
            write(path, f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n')
            component = self.builder.parse_generic_meta(path)
            self.assertEqual(expected_type, component["metadataType"], filename)

    def test_apex_meta_api_version_status(self) -> None:
        cls = self.root / "force-app/main/default/classes/HarnessBillingService.cls"
        write(cls, "public with sharing class HarnessBillingService {}\n")
        write(
            cls.with_name("HarnessBillingService.cls-meta.xml"),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<apiVersion>61.0</apiVersion><status>Active</status></ApexClass>\n",
        )
        component = self.builder.parse_apex(cls, "ApexClass")
        self.assertEqual("61.0", component["facts"]["apiVersion"])
        self.assertEqual("Active", component["facts"]["status"])

    def test_apex_without_meta_sibling_still_parses(self) -> None:
        cls = self.root / "force-app/main/default/classes/Plain.cls"
        write(cls, "public class Plain {}\n")
        component = self.builder.parse_apex(cls, "ApexClass")
        self.assertNotIn("apiVersion", component["facts"])
        self.assertNotIn("status", component["facts"])

    def test_tab_crawl_requires_known_object(self) -> None:
        tab = {
            "metadataType": "CustomTab",
            "name": "HarnessEngagement__c",
            "path": "force-app/main/default/tabs/HarnessEngagement__c.tab-meta.xml",
            "references": [],
        }
        self.assertEqual(
            {"HarnessEngagement__c"},
            ForceAppKnowledge.component_objects(tab, {"HarnessEngagement__c"}),
        )
        self.assertEqual(set(), ForceAppKnowledge.component_objects(tab, {"Other__c"}))
        # Legacy behavior without a known-objects set: name-based association stands.
        self.assertEqual({"HarnessEngagement__c"}, ForceAppKnowledge.component_objects(tab))

    def test_named_credential_url_parameter_host(self) -> None:
        path = (
            self.root
            / "force-app/main/default/namedCredentials/HarnessBillingV2.namedCredential-meta.xml"
        )
        write(path, NEW_STYLE_NAMED_CREDENTIAL_XML)
        component = self.builder.parse_integration(path, "NamedCredential")
        self.assertEqual("api.billing.example.test", component["facts"]["endpointHost"])
        serialized = canonical(component)
        self.assertNotIn("never-export-this-secret", serialized)
        self.assertNotIn("tenant=42", serialized)


FLOW_DATA_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Escalation Router</label><status>Active</status><processType>AutoLaunchedFlow</processType>
  <start>
    <object>Case</object><triggerType>RecordAfterSave</triggerType><recordTriggerType>Update</recordTriggerType>
    <doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>
    <filterLogic>and</filterLogic>
    <filters><field>Priority</field><operator>EqualTo</operator><value><stringValue>High</stringValue></value></filters>
    <scheduledPaths><name>DayLater</name><offsetNumber>1</offsetNumber><offsetUnit>Days</offsetUnit></scheduledPaths>
  </start>
  <variables><name>varAccount</name><dataType>SObject</dataType><objectType>Account</objectType>
    <isCollection>false</isCollection><isInput>true</isInput><isOutput>false</isOutput></variables>
  <recordLookups>
    <name>GetAccount</name><object>Account</object>
    <filters><field>Industry</field><operator>EqualTo</operator><value><stringValue>Energy</stringValue></value></filters>
    <queriedFields>Name</queriedFields><queriedFields>OwnerId</queriedFields>
    <outputReference>varAccount</outputReference>
    <getFirstRecordOnly>true</getFirstRecordOnly><sortField>CreatedDate</sortField><sortOrder>Desc</sortOrder>
  </recordLookups>
  <recordUpdates>
    <name>CloseStale</name><object>Case</object>
    <filters><field>Status</field><operator>EqualTo</operator><value><stringValue>Stale</stringValue></value></filters>
    <inputAssignments><field>Status</field><value><stringValue>Closed</stringValue></value></inputAssignments>
  </recordUpdates>
  <recordCreates><name>LogEntry</name><inputReference>varAccount</inputReference></recordCreates>
  <decisions><name>IsVip</name><rules><name>Vip</name>
    <conditions><leftValueReference>$Record.Tier__c</leftValueReference><operator>EqualTo</operator></conditions>
    <conditions><leftValueReference>varAccount.Rating</leftValueReference><operator>EqualTo</operator></conditions>
    <conditions><leftValueReference>$Record.Owner__r.Region__c</leftValueReference><operator>EqualTo</operator></conditions>
  </rules></decisions>
  <formulas><name>DaysOpen</name><dataType>Number</dataType>
    <expression>TODAY() - {!$Record.CreatedDate__c}</expression></formulas>
</Flow>
"""


class FlowReworkTests(unittest.TestCase):
    """Phase 3: per-element data operations, entry conditions, polarity fix, dml-object."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.path = self.root / "force-app/main/default/flows/EscalationRouter.flow-meta.xml"
        write(self.path, FLOW_DATA_MODEL_XML)
        self.flow = ForceAppKnowledge(self.root).parse_flow(self.path)
        self.references = {
            (ref["kind"], ref["target"]) for ref in self.flow["references"]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_start_facts_capture_entry_conditions_and_schedule(self) -> None:
        start = self.flow["facts"]["start"]
        self.assertEqual(
            [{"field": "Priority", "operator": "EqualTo", "value": "High"}],
            start["entryConditions"],
        )
        self.assertEqual("and", start["filterLogic"])
        self.assertTrue(start["requiresRecordChanged"])
        self.assertEqual(
            [{"name": "DayLater", "offsetNumber": "1", "offsetUnit": "Days"}],
            start["scheduledPaths"],
        )
        self.assertIn(("filters-field", "Case.Priority"), self.references)

    def test_data_operations_record_object_fields_and_output_target(self) -> None:
        operations = {item["element"]: item for item in self.flow["facts"]["dataOperations"]}
        lookup = operations["GetAccount"]
        self.assertEqual("lookup", lookup["kind"])
        self.assertEqual("Account", lookup["object"])
        self.assertEqual(["Industry"], lookup["filterFields"])
        self.assertEqual(["Name", "OwnerId"], lookup["retrievedFields"])
        self.assertEqual("varAccount", lookup["outputTarget"])
        self.assertTrue(lookup["getFirstRecordOnly"])
        self.assertEqual("CreatedDate", lookup["sortField"])

    def test_update_filters_are_selection_criteria_not_writes(self) -> None:
        self.assertIn(("filters-field", "Case.Status"), self.references)
        self.assertIn(("writes-field", "Case.Status"), self.references)
        operations = {item["element"]: item for item in self.flow["facts"]["dataOperations"]}
        update = operations["CloseStale"]
        self.assertEqual(["Status"], update["filterFields"])
        self.assertEqual(["Status"], update["writtenFields"])

    def test_dml_and_query_object_edges_emitted(self) -> None:
        self.assertIn(("queries-object", "Account"), self.references)
        self.assertIn(("dml-object", "Case"), self.references)
        # inputReference-only create resolves its object through the variable's objectType.
        self.assertIn(("dml-object", "Account"), self.references)
        operations = {item["element"]: item for item in self.flow["facts"]["dataOperations"]}
        self.assertEqual("Account", operations["LogEntry"]["object"])

    def test_flow_queries_object_is_structural_not_heuristic(self) -> None:
        for reference in self.flow["references"]:
            if reference["kind"] == "queries-object":
                self.assertNotIn("heuristic", reference)

    def test_decision_and_formula_field_references(self) -> None:
        self.assertIn(("references-field", "Case.Tier__c"), self.references)
        self.assertIn(("references-field", "Account.Rating"), self.references)
        self.assertIn(("references-field", "Case.CreatedDate__c"), self.references)
        # Relationship paths are not resolved — never guessed across objects.
        self.assertNotIn(
            ("references-field", "Case.Owner__r.Region__c"), self.references
        )
        formulas = self.flow["facts"]["formulas"]
        self.assertEqual(
            [{"name": "DaysOpen", "dataType": "Number", "fieldRefs": ["Case.CreatedDate__c"]}],
            formulas,
        )

    def test_variables_fact_records_subflow_contract(self) -> None:
        self.assertEqual(
            [
                {
                    "name": "varAccount",
                    "dataType": "SObject",
                    "objectType": "Account",
                    "isCollection": False,
                    "isInput": True,
                    "isOutput": False,
                }
            ],
            self.flow["facts"]["variables"],
        )


ROLLUP_FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Total_Billed__c</fullName><label>Total Billed</label><type>Currency</type>
  <summaryForeignKey>HarnessBillingEvent__c.HarnessEngagement__c</summaryForeignKey>
  <summarizedField>HarnessBillingEvent__c.Amount__c</summarizedField>
  <summaryOperation>sum</summaryOperation>
  <summaryFilterItems><field>HarnessBillingEvent__c.Status__c</field><operation>equals</operation><value>Billed</value></summaryFilterItems>
</CustomField>
"""
PICKLIST_FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Stage__c</fullName><label>Stage</label><type>Picklist</type>
  <trackHistory>true</trackHistory>
  <valueSet>
    <restricted>true</restricted>
    <controllingField>Type__c</controllingField>
    <valueSetDefinition>
      <sorted>false</sorted>
      <value><fullName>Draft</fullName><label>Draft</label><default>true</default><isActive>true</isActive></value>
      <value><fullName>Won</fullName><label>Won</label><isActive>true</isActive></value>
    </valueSetDefinition>
  </valueSet>
</CustomField>
"""
FORMULA_FIELD_META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Client_Region__c</fullName><label>Client Region</label><type>Text</type>
  <formula>HarnessEngagement__r.Region__c &amp; TEXT(Status__c)</formula>
  <formulaTreatBlanksAs>BlankAsBlank</formulaTreatBlanksAs>
</CustomField>
"""


class ObjectFieldOverhaulTests(unittest.TestCase):
    """Phase 4: objectKind discrimination, picklist vocabulary, roll-up and formula lineage."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.objects = self.root / "force-app/main/default/objects"
        # Lookup fields that make relationship chains resolvable.
        write(
            self.objects / "Assignment__c/fields/HarnessEngagement__c.field-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>HarnessEngagement__c</fullName><type>Lookup</type>"
            "<referenceTo>HarnessEngagement__c</referenceTo>"
            "<relationshipName>Assignments</relationshipName></CustomField>\n",
        )
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def parse(self, relative: str, xml: str) -> dict:
        path = self.objects / relative
        write(path, xml)
        if relative.endswith(".object-meta.xml"):
            return self.builder.parse_object(path)
        return self.builder.parse_field(path)

    def test_object_kind_discrimination(self) -> None:
        cases = {
            "HarnessEngagement__c/HarnessEngagement__c.object-meta.xml": ("customObject", "<CustomObject><label>E</label></CustomObject>"),
            "FeatureFlag__mdt/FeatureFlag__mdt.object-meta.xml": ("customMetadataType", "<CustomObject><label>F</label></CustomObject>"),
            "HarnessBillingRaised__e/HarnessBillingRaised__e.object-meta.xml": ("platformEvent", "<CustomObject><label>B</label><eventType>HighVolume</eventType></CustomObject>"),
            "Archive__b/Archive__b.object-meta.xml": ("bigObject", "<CustomObject><label>A</label></CustomObject>"),
            "Config__c/Config__c.object-meta.xml": ("customSetting", "<CustomObject><label>C</label><customSettingsType>Hierarchy</customSettingsType></CustomObject>"),
            "Account/Account.object-meta.xml": ("standardObjectExtension", "<CustomObject><enableFeeds>true</enableFeeds></CustomObject>"),
        }
        for relative, (expected, xml) in cases.items():
            component = self.parse(relative, f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n')
            self.assertEqual(expected, component["facts"]["objectKind"], relative)

    def test_object_enrichment_facts(self) -> None:
        component = self.parse(
            "HarnessEngagement__c/HarnessEngagement__c.object-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>HarnessEngagement</label><description>Client harnessEngagement.</description>"
            "<enableHistory>true</enableHistory>"
            "<nameField><type>AutoNumber</type><label>HarnessEngagement No</label>"
            "<displayFormat>ENG-{0000}</displayFormat></nameField>"
            "<compactLayoutAssignment>HarnessEngagement_Compact</compactLayoutAssignment>"
            "</CustomObject>\n",
        )
        facts = component["facts"]
        self.assertEqual("Client harnessEngagement.", facts["description"])
        self.assertTrue(facts["enableHistory"])
        self.assertEqual(
            {"type": "AutoNumber", "label": "HarnessEngagement No", "displayFormat": "ENG-{0000}"},
            facts["nameField"],
        )
        self.assertEqual("HarnessEngagement_Compact", facts["compactLayoutAssignment"])

    def test_field_picklist_values_and_dependency(self) -> None:
        component = self.parse(
            "HarnessEngagement__c/fields/Stage__c.field-meta.xml", PICKLIST_FIELD_XML
        )
        facts = component["facts"]
        self.assertTrue(facts["picklistRestricted"])
        self.assertFalse(facts["picklistSorted"])
        self.assertEqual(2, facts["picklistValueCount"])
        self.assertEqual(
            {"fullName": "Draft", "label": "Draft", "default": True, "isActive": True},
            facts["picklistValues"][0],
        )
        self.assertNotIn("picklistValuesTruncated", facts)
        self.assertTrue(facts["trackHistory"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("picklist-dependency", "HarnessEngagement__c.Type__c"), references)

    def test_field_global_value_set_edge(self) -> None:
        component = self.parse(
            "HarnessEngagement__c/fields/Region__c.field-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Region__c</fullName><type>Picklist</type>"
            "<valueSet><valueSetName>Regions</valueSetName></valueSet></CustomField>\n",
        )
        self.assertEqual("Regions", component["facts"]["valueSetName"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-value-set", "Regions"), references)

    def test_field_rollup_deterministic_refs(self) -> None:
        component = self.parse(
            "HarnessEngagement__c/fields/Total_Billed__c.field-meta.xml", ROLLUP_FIELD_XML
        )
        facts = component["facts"]
        self.assertEqual("sum", facts["summaryOperation"])
        self.assertEqual(["HarnessBillingEvent__c.Status__c"], facts["summaryFilterFields"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "HarnessBillingEvent__c.HarnessEngagement__c"), references)
        self.assertIn(("references-field", "HarnessBillingEvent__c.Amount__c"), references)
        self.assertIn(("references-field", "HarnessBillingEvent__c.Status__c"), references)
        self.assertIn(("operates-on", "HarnessBillingEvent__c"), references)
        for reference in component["references"]:
            self.assertNotIn("heuristic", reference, reference)

    def test_field_formula_relationship_chain_resolution(self) -> None:
        component = self.parse(
            "Assignment__c/fields/Client_Region__c.field-meta.xml", FORMULA_FIELD_META_XML
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        # HarnessEngagement__r resolves via Assignment__c.HarnessEngagement__c lookup → HarnessEngagement__c.
        self.assertIn(("references-field", "HarnessEngagement__c.Region__c"), references)
        # Bare token attributed to the owning object; the chained token must NOT be.
        self.assertIn(("references-field", "Assignment__c.Status__c"), references)
        self.assertNotIn(("references-field", "Assignment__c.Region__c"), references)
        for reference in component["references"]:
            if reference["kind"] == "references-field":
                self.assertTrue(reference.get("heuristic"), reference)

    def test_field_lookup_filter_fields(self) -> None:
        component = self.parse(
            "Assignment__c/fields/Resource__c.field-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Resource__c</fullName><type>Lookup</type><referenceTo>Resource__c</referenceTo>"
            "<lookupFilter><active>true</active>"
            "<filterItems><field>Resource__c.Active__c</field><operation>equals</operation><value>true</value></filterItems>"
            "<filterItems><field>$Source.Status__c</field><operation>equals</operation><value>Open</value></filterItems>"
            "</lookupFilter></CustomField>\n",
        )
        facts = component["facts"]
        self.assertTrue(facts["lookupFilterPresent"])
        self.assertEqual(
            ["$Source.Status__c", "Resource__c.Active__c"], facts["lookupFilterFields"]
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("filters-field", "Resource__c.Active__c"), references)
        self.assertNotIn(("filters-field", "$Source.Status__c"), references)


WORKFLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Workflow xmlns="http://soap.sforce.com/2006/04/metadata">
  <alerts>
    <fullName>Escalation_Alert</fullName>
    <template>unfiled$public/EscalationNotice</template>
    <recipients><type>owner</type></recipients>
    <recipients><recipient>Support_Team</recipient><type>group</type></recipients>
    <ccEmails>ops@example.test</ccEmails>
    <senderType>CurrentUser</senderType>
  </alerts>
  <fieldUpdates>
    <fullName>Close_Case</fullName><field>Status</field><operation>Literal</operation>
    <literalValue>Closed</literalValue><reevaluateOnChange>false</reevaluateOnChange>
  </fieldUpdates>
  <fieldUpdates>
    <fullName>Stamp_Account</fullName><field>Last_Case_Closed__c</field>
    <operation>Formula</operation><formula>NOW()</formula>
    <targetObject>Account</targetObject>
  </fieldUpdates>
  <outboundMessages>
    <fullName>Notify_ERP</fullName>
    <endpointUrl>https://erp.example.test/hooks/case</endpointUrl>
    <integrationUser>integration@example.test</integrationUser>
    <fields>Id</fields><fields>Status</fields>
    <includeSessionId>false</includeSessionId>
  </outboundMessages>
  <rules>
    <fullName>Escalate_High_Priority</fullName>
    <active>true</active>
    <triggerType>onCreateOrTriggeringUpdate</triggerType>
    <criteriaItems><field>Case.Priority</field><operation>equals</operation><value>High</value></criteriaItems>
    <booleanFilter>1</booleanFilter>
    <actions><name>Close_Case</name><type>FieldUpdate</type></actions>
    <workflowTimeTriggers>
      <timeLength>1</timeLength><workflowTimeTriggerUnit>Days</workflowTimeTriggerUnit>
      <offsetFromField>Case.CreatedDate</offsetFromField>
      <actions><name>Escalation_Alert</name><type>Alert</type></actions>
    </workflowTimeTriggers>
  </rules>
  <tasks>
    <fullName>Follow_Up</fullName><assignedToType>role</assignedToType>
    <subject>Follow up with customer</subject><status>Not Started</status>
    <priority>Normal</priority><dueDateOffset>3</dueDateOffset>
  </tasks>
</Workflow>
"""


class WorkflowParserTests(unittest.TestCase):
    """Phase 5: the legacy workflow engine becomes a first-class automation component."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.path = self.root / "force-app/main/default/workflows/Case.workflow-meta.xml"
        write(self.path, WORKFLOW_XML)
        self.builder = ForceAppKnowledge(self.root)
        self.workflow = self.builder.parse_workflow(self.path)
        self.references = {
            (ref["kind"], ref["target"]) for ref in self.workflow["references"]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workflow_component_identity_and_rules(self) -> None:
        self.assertEqual("Workflow:Case", self.workflow["id"])
        facts = self.workflow["facts"]
        self.assertEqual(1, facts["ruleCount"])
        self.assertEqual(1, facts["activeRuleCount"])
        rule = facts["rules"][0]
        self.assertEqual("Escalate_High_Priority", rule["name"])
        self.assertEqual(
            [{"field": "Case.Priority", "operator": "equals", "value": "High"}],
            rule["criteria"],
        )
        self.assertEqual(
            [{"offset": "1", "unit": "Days", "offsetFromField": "Case.CreatedDate"}],
            rule["timeTriggers"],
        )
        self.assertIn(("filters-field", "Case.Priority"), self.references)

    def test_workflow_field_update_cross_object_write(self) -> None:
        self.assertIn(("writes-field", "Case.Status"), self.references)
        self.assertIn(("writes-field", "Account.Last_Case_Closed__c"), self.references)
        updates = {item["name"]: item for item in self.workflow["facts"]["fieldUpdates"]}
        self.assertEqual("Closed", updates["Close_Case"]["literalValue"])
        self.assertEqual("Account", updates["Stamp_Account"]["targetObject"])

    def test_workflow_alert_omits_email_addresses(self) -> None:
        alert = self.workflow["facts"]["alerts"][0]
        self.assertEqual("unfiled$public/EscalationNotice", alert["template"])
        self.assertEqual(["group", "owner"], alert["recipientTypes"])
        serialized = canonical(self.workflow)
        self.assertNotIn("ops@example.test", serialized)
        self.assertNotIn("integration@example.test", serialized)
        self.assertIn(
            ("uses-template", "unfiled$public/EscalationNotice"), self.references
        )
        self.assertIn(("sends-alert", "Case.Escalation_Alert"), self.references)

    def test_workflow_outbound_message_host_and_payload(self) -> None:
        message = self.workflow["facts"]["outboundMessages"][0]
        self.assertEqual("erp.example.test", message["endpointHost"])
        self.assertEqual(["Id", "Status"], message["fields"])
        self.assertIn(("reads-field", "Case.Status"), self.references)

    def test_workflow_routes_to_automation_claim_with_stub(self) -> None:
        claims = self.builder.candidate_claims(self.workflow)
        claim_types = [claim["claimType"] for claim in claims]
        self.assertIn("automation-inventory", claim_types)
        self.assertIn("component-description", claim_types)
        automation = next(
            claim for claim in claims if claim["claimType"] == "automation-inventory"
        )
        self.assertEqual("automation-map", automation["domain"])


APEX_SERVICE_SOURCE = """public with sharing class HarnessBillingService implements Queueable, Database.AllowsCallouts {
    @AuraEnabled
    public static void bill(Id harnessEngagementId) {
        HarnessEngagement__c harnessEngagement = [SELECT Id, Status__c FROM HarnessEngagement__c WHERE Id = :harnessEngagementId];
        harnessEngagement.Status__c = 'Billed';
        update harnessEngagement;
        insert new LogEntry__c(Message__c = 'billed');
        Database.upsert(harnessEngagement, false);
        HttpRequest request = new HttpRequest();
        request.setEndpoint('callout:HarnessBilling_API/v1/invoices');
        HttpRequest raw = new HttpRequest();
        raw.setEndpoint('https://legacy.example.test/api?key=abc');
    }
}
"""
APEX_TRIGGER_SOURCE = """trigger CaseTrigger on Case (before update) {
    for (Case record : Trigger.new) {
        record.Priority = 'High';
    }
    update Trigger.new;
}
"""


class ApexExtractionTests(unittest.TestCase):
    """Phase 6: declaration facts, DML targets, callout edges, dynamic SOQL toggle."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        (self.root / "force-app/main/default").mkdir(parents=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def parse_source(self, name: str, source: str, metadata_type: str = "ApexClass") -> dict:
        folder = "triggers" if metadata_type == "ApexTrigger" else "classes"
        suffix = ".trigger" if metadata_type == "ApexTrigger" else ".cls"
        path = self.root / f"force-app/main/default/{folder}/{name}{suffix}"
        write(path, source)
        return self.builder.parse_apex(path, metadata_type)

    def test_apex_declaration_facts(self) -> None:
        component = self.parse_source("HarnessBillingService", APEX_SERVICE_SOURCE)
        facts = component["facts"]
        self.assertEqual("with", facts["sharingModel"])
        self.assertEqual(["Database.AllowsCallouts", "Queueable"], facts["interfaces"])
        self.assertIn("AuraEnabled", facts["annotations"])
        self.assertNotIn("isTest", facts)

    def test_apex_dml_targets_via_var_map_and_new(self) -> None:
        component = self.parse_source("HarnessBillingService", APEX_SERVICE_SOURCE)
        facts = component["facts"]
        self.assertEqual(
            {"HarnessEngagement__c": ["update", "upsert"], "LogEntry__c": ["insert"]},
            facts["dmlTargets"],
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("dml-object", "HarnessEngagement__c"), references)
        self.assertIn(("dml-object", "LogEntry__c"), references)
        for reference in component["references"]:
            if reference["kind"] == "dml-object":
                self.assertTrue(reference.get("heuristic"))

    def test_trigger_context_variable_seeding(self) -> None:
        component = self.parse_source("CaseTrigger", APEX_TRIGGER_SOURCE, "ApexTrigger")
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("var-field-ref", "Case.Priority"), references)

    def test_apex_callout_edges(self) -> None:
        component = self.parse_source("HarnessBillingService", APEX_SERVICE_SOURCE)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-named-credential", "HarnessBilling_API"), references)
        self.assertIn(("callout-endpoint", "legacy.example.test"), references)
        serialized = canonical(component)
        self.assertNotIn("key=abc", serialized)

    def test_dynamic_soql_from_objects_covered_by_baseline_scan(self) -> None:
        # SOQL_FROM_RE runs over the whole source, so Database.query string literals yield the
        # same heuristic queries-object edge as inline SOQL — no separate toggle needed.
        source = (
            "public class Finder { public void run() { "
            "List<SObject> rows = Database.query('SELECT Id FROM ScheduleConflict__c'); } }\n"
        )
        component = self.parse_source("Finder", source)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("queries-object", "ScheduleConflict__c"), references)


DEEP_APPROVAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ApprovalProcess xmlns="http://soap.sforce.com/2006/04/metadata">
  <active>true</active><label>Discount Approval</label>
  <recordEditability>AdminOnly</recordEditability>
  <allowRecall>true</allowRecall>
  <finalApprovalRecordLock>true</finalApprovalRecordLock>
  <entryCriteria>
    <criteriaItems><field>HarnessEngagement__c.Discount__c</field><operation>greaterThan</operation><value>20</value></criteriaItems>
    <booleanFilter>1</booleanFilter>
  </entryCriteria>
  <approvalStep>
    <name>Manager_Review</name><label>Manager Review</label>
    <assignedApprover>
      <approver><type>relatedUserField</type><name>Manager__c</name></approver>
      <approver><type>user</type><name>jane.doe@example.test</name></approver>
      <whenMultipleApprovers>FirstResponse</whenMultipleApprovers>
    </assignedApprover>
    <rejectBehavior><type>RejectRequest</type></rejectBehavior>
    <approvalActions><action><name>Flag_Review</name><type>FieldUpdate</type></action></approvalActions>
  </approvalStep>
  <finalApprovalActions>
    <action><name>Set_Approved</name><type>FieldUpdate</type></action>
    <action><name>Approval_Notice</name><type>Alert</type></action>
  </finalApprovalActions>
  <approvalPageFields><field>Name</field><field>Discount__c</field></approvalPageFields>
  <emailTemplate>unfiled$public/ApprovalRequest</emailTemplate>
  <allowedSubmitters><type>owner</type></allowedSubmitters>
  <allowedSubmitters><submitter>ops.user@example.test</submitter><type>user</type></allowedSubmitters>
</ApprovalProcess>
"""


class ApprovalProcessDeepeningTests(unittest.TestCase):
    """Phase 7: criteria, approver routing, and the cross-file workflow-action chain."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.path = (
            self.root
            / "force-app/main/default/approvalProcesses/HarnessEngagement__c.Discount_Approval.approvalProcess-meta.xml"
        )
        write(self.path, DEEP_APPROVAL_XML)
        self.process = ForceAppKnowledge(self.root).parse_approval_process(self.path)
        self.references = {
            (ref["kind"], ref["target"]) for ref in self.process["references"]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_entry_criteria_filters(self) -> None:
        facts = self.process["facts"]
        self.assertEqual(
            [
                {
                    "field": "HarnessEngagement__c.Discount__c",
                    "operator": "greaterThan",
                    "value": "20",
                }
            ],
            facts["entryCriteria"]["criteria"],
        )
        self.assertIn(("filters-field", "HarnessEngagement__c.Discount__c"), self.references)

    def test_step_approvers_omit_usernames(self) -> None:
        step = self.process["facts"]["steps"][0]
        self.assertEqual("FirstResponse", step["whenMultipleApprovers"])
        self.assertEqual("RejectRequest", step["rejectBehavior"])
        self.assertEqual(
            [{"type": "relatedUserField", "field": "Manager__c"}, {"type": "user"}],
            step["approvers"],
        )
        serialized = canonical(self.process)
        self.assertNotIn("jane.doe@example.test", serialized)
        self.assertNotIn("ops.user@example.test", serialized)
        self.assertIn(("references-field", "HarnessEngagement__c.Manager__c"), self.references)

    def test_action_sets_link_workflow_components(self) -> None:
        action_sets = self.process["facts"]["actionSets"]
        self.assertEqual(
            [
                {"name": "Set_Approved", "type": "FieldUpdate"},
                {"name": "Approval_Notice", "type": "Alert"},
            ],
            action_sets["finalApproval"],
        )
        self.assertIn(
            ("uses-workflow-action", "HarnessEngagement__c.Set_Approved"), self.references
        )
        self.assertIn(
            ("uses-workflow-action", "HarnessEngagement__c.Flag_Review"), self.references
        )
        self.assertIn(("sends-alert", "HarnessEngagement__c.Approval_Notice"), self.references)
        self.assertIn(
            ("uses-template", "unfiled$public/ApprovalRequest"), self.references
        )

    def test_lock_and_page_field_facts(self) -> None:
        facts = self.process["facts"]
        self.assertEqual("AdminOnly", facts["recordEditability"])
        self.assertTrue(facts["allowRecall"])
        self.assertTrue(facts["finalApprovalRecordLock"])
        self.assertEqual(["Discount__c", "Name"], sorted(facts["approvalPageFields"]))
        self.assertEqual(["owner", "user"], facts["allowedSubmitterTypes"])
        self.assertIn(("references-field", "HarnessEngagement__c.Discount__c"), self.references)
        self.assertIn(("references-field", "HarnessEngagement__c.Name"), self.references)


class RecordDataModelTests(unittest.TestCase):
    """Phase 8: RecordType, value sets, BusinessProcess, DuplicateRule."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        (self.root / "force-app/main/default").mkdir(parents=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_record_type_scoping_and_business_process_edge(self) -> None:
        path = (
            self.root
            / "force-app/main/default/objects/Case/recordTypes/Support.recordType-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<RecordType xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Support</fullName><label>Support</label><active>true</active>"
            "<businessProcess>Support_Process</businessProcess>"
            "<picklistValues><picklist>Priority</picklist>"
            "<values><fullName>High</fullName><default>true</default></values>"
            "<values><fullName>Low</fullName></values></picklistValues>"
            "</RecordType>\n",
        )
        component = self.builder.parse_record_type(path)
        self.assertEqual("RecordType:Case.Support", component["id"])
        facts = component["facts"]
        self.assertTrue(facts["active"])
        self.assertEqual(
            [{"picklist": "Priority", "valueCount": 2, "defaults": ["High"]}],
            facts["picklistScopes"],
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "Case"), references)
        self.assertIn(("references-field", "Case.Priority"), references)
        self.assertIn(("uses-business-process", "Case.Support_Process"), references)

    def test_standard_value_set_lifecycle_flags(self) -> None:
        path = (
            self.root
            / "force-app/main/default/standardValueSets/OpportunityStage.standardValueSet-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<StandardValueSet xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<sorted>false</sorted>"
            "<standardValue><fullName>Prospecting</fullName><default>true</default>"
            "<probability>10</probability><forecastCategory>Pipeline</forecastCategory></standardValue>"
            "<standardValue><fullName>Closed Won</fullName><closed>true</closed><won>true</won>"
            "<probability>100</probability></standardValue>"
            "</StandardValueSet>\n",
        )
        component = self.builder.parse_value_set(path, "StandardValueSet")
        self.assertEqual("StandardValueSet:OpportunityStage", component["id"])
        won = component["facts"]["values"][1]
        self.assertTrue(won["closed"])
        self.assertTrue(won["won"])
        self.assertEqual("100", won["probability"])

    def test_business_process_ordered_values_and_value_set_link(self) -> None:
        path = (
            self.root
            / "force-app/main/default/objects/Opportunity/businessProcesses/Sales.businessProcess-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<BusinessProcess xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Sales</fullName><isActive>true</isActive>"
            "<values><fullName>Qualify</fullName><default>true</default></values>"
            "<values><fullName>Close</fullName></values>"
            "</BusinessProcess>\n",
        )
        component = self.builder.parse_business_process(path)
        facts = component["facts"]
        self.assertEqual("StageName", facts["lifecycleField"])
        self.assertEqual(["Qualify", "Close"], [v["fullName"] for v in facts["values"]])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "Opportunity.StageName"), references)
        self.assertIn(("uses-value-set", "OpportunityStage"), references)

    def test_duplicate_rule_error_catalog_and_matching_rule_edge(self) -> None:
        path = (
            self.root
            / "force-app/main/default/duplicateRules/Lead.Standard_Lead_Duplicate_Rule.duplicateRule-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<DuplicateRule xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<masterLabel>Standard Lead Duplicate Rule</masterLabel><isActive>true</isActive>"
            "<actionOnInsert>Block</actionOnInsert><actionOnUpdate>Allow</actionOnUpdate>"
            "<alertText>You're creating a duplicate lead.</alertText>"
            "<securityOption>EnforceSharingRules</securityOption>"
            "<duplicateRuleMatchRules>"
            "<matchingRule>Standard_Lead_Match</matchingRule>"
            "<matchingRuleObjectType>Contact</matchingRuleObjectType>"
            "<objectMapping><inputObject>Lead</inputObject><outputObject>Contact</outputObject>"
            "<mappingFields><inputField>Email</inputField><outputField>Email</outputField></mappingFields>"
            "</objectMapping>"
            "</duplicateRuleMatchRules>"
            "</DuplicateRule>\n",
        )
        component = self.builder.parse_duplicate_rule(path)
        facts = component["facts"]
        self.assertEqual("Block", facts["actionOnInsert"])
        entry = facts["errorCatalog"][0]
        self.assertEqual("duplicate-alert", entry["kind"])
        self.assertEqual("You're creating a duplicate lead.", entry["errorMessage"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-matching-rule", "Contact.Standard_Lead_Match"), references)
        self.assertIn(("references-field", "Lead.Email"), references)
        self.assertIn(("references-field", "Contact.Email"), references)
        claims = self.builder.candidate_claims(component)
        automation = next(
            claim for claim in claims if claim["claimType"] == "automation-inventory"
        )
        self.assertIn("duplicate lead", automation["statement"])


class LwcDeepeningTests(unittest.TestCase):
    """Phase 9: targetConfigs placement, markup literals, labels, composition."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        bundle = self.root / "force-app/main/default/lwc/harnessEngagementPanel"
        write(
            bundle / "harnessEngagementPanel.js-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<isExposed>true</isExposed><masterLabel>HarnessEngagement Panel</masterLabel>"
            "<targets><target>lightning__RecordPage</target></targets>"
            "<targetConfigs>"
            '<targetConfig targets="lightning__RecordPage">'
            "<objects><object>HarnessEngagement__c</object><object>Account</object></objects>"
            "</targetConfig>"
            "</targetConfigs>"
            "</LightningComponentBundle>\n",
        )
        write(
            bundle / "harnessEngagementPanel.js",
            "import { LightningElement, api, wire } from 'lwc';\n"
            "import getSummary from '@salesforce/apex/HarnessEngagementController.getSummary';\n"
            "import HEADER_LABEL from '@salesforce/label/c.HarnessEngagement_Header';\n"
            "import { getRecord } from 'lightning/uiRecordApi';\n"
            "const FIELDS = ['HarnessEngagement__c.Status__c', 'HarnessEngagement__c.Name'];\n"
            "export default class HarnessEngagementPanel extends LightningElement {\n"
            "  @api recordId;\n"
            "  @wire(getRecord, { recordId: '$recordId', fields: FIELDS }) record;\n"
            "}\n",
        )
        write(
            bundle / "harnessEngagementPanel.html",
            "<template>\n"
            '  <lightning-record-form object-api-name="HarnessEngagement__c" field-name="Owner__c">\n'
            "  </lightning-record-form>\n"
            "  <c-status-badge></c-status-badge>\n"
            "</template>\n",
        )
        self.bundle = bundle
        self.component = ForceAppKnowledge(self.root).parse_lwc(bundle)
        self.references = {
            (ref["kind"], ref["target"]) for ref in self.component["references"]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_target_config_objects_are_placement_edges(self) -> None:
        self.assertEqual(
            [{"targets": "lightning__RecordPage", "objects": ["Account", "HarnessEngagement__c"]}],
            self.component["facts"]["targetConfigs"],
        )
        self.assertIn(("operates-on", "HarnessEngagement__c"), self.references)
        self.assertIn(("operates-on", "Account"), self.references)

    def test_js_wire_field_literals_are_heuristic_refs(self) -> None:
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), self.references)
        for reference in self.component["references"]:
            if reference["target"] == "HarnessEngagement__c.Status__c":
                self.assertTrue(reference.get("heuristic"))

    def test_label_import_and_embedded_component(self) -> None:
        self.assertIn(("uses-label", "HarnessEngagement_Header"), self.references)
        self.assertIn(("embeds-component", "statusBadge"), self.references)
        self.assertIn(("apex-method", "HarnessEngagementController.getSummary"), self.references)
        self.assertEqual(["recordId"], self.component["facts"]["apiProperties"])
        self.assertEqual(["getRecord"], self.component["facts"]["wiredAdapters"])

    def test_html_field_literal_qualified_by_unambiguous_object(self) -> None:
        self.assertIn(("references-field", "HarnessEngagement__c.Owner__c"), self.references)

    def test_markup_toggle_disables_html_scanning(self) -> None:
        write(
            self.root / "config/knowledge-extraction.json",
            '{"schemaVersion": 1, "markupFieldExtraction": false}\n',
        )
        component = ForceAppKnowledge(self.root).parse_lwc(self.bundle)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertNotIn(("embeds-component", "statusBadge"), references)
        self.assertNotIn(("references-field", "HarnessEngagement__c.Status__c"), references)
        # Deterministic imports and targetConfigs stay on regardless of the toggle.
        self.assertIn(("uses-label", "HarnessEngagement_Header"), references)
        self.assertIn(("operates-on", "HarnessEngagement__c"), references)


FLEXIPAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="http://soap.sforce.com/2006/04/metadata">
  <masterLabel>HarnessEngagement Record Page</masterLabel>
  <type>RecordPage</type>
  <sobjectType>HarnessEngagement__c</sobjectType>
  <template><name>flexipage:recordHomeTemplateDesktop</name></template>
  <flexiPageRegions>
    <name>main</name><type>Region</type>
    <itemInstances>
      <componentInstance>
        <componentName>c:harnessEngagementPanel</componentName>
        <componentInstanceProperties><name>flowName</name><value>Escalation_Router</value></componentInstanceProperties>
        <visibilityRule>
          <criteria><leftValue>{!Record.Status__c}</leftValue><operator>EQUAL</operator><rightValue>Open</rightValue></criteria>
        </visibilityRule>
      </componentInstance>
    </itemInstances>
    <itemInstances>
      <componentInstance><componentName>flexipage:reportChart</componentName></componentInstance>
    </itemInstances>
    <itemInstances>
      <fieldInstance><fieldItem>Record.Discount__c</fieldItem></fieldInstance>
    </itemInstances>
  </flexiPageRegions>
</FlexiPage>
"""


class FlexiPageParserTests(unittest.TestCase):
    """Phase 10: the record page's component/field wiring becomes visible."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        path = (
            self.root
            / "force-app/main/default/flexipages/HarnessEngagement_Record_Page.flexipage-meta.xml"
        )
        write(path, FLEXIPAGE_XML)
        self.page = ForceAppKnowledge(self.root).parse_flexipage(path)
        self.references = {
            (ref["kind"], ref["target"]) for ref in self.page["references"]
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_flexipage_identity_and_facts(self) -> None:
        self.assertEqual("FlexiPage:HarnessEngagement_Record_Page", self.page["id"])
        facts = self.page["facts"]
        self.assertEqual("RecordPage", facts["pageType"])
        self.assertEqual("HarnessEngagement__c", facts["object"])
        self.assertEqual("flexipage:recordHomeTemplateDesktop", facts["template"])
        self.assertEqual(2, facts["componentCount"])
        self.assertEqual(1, facts["fieldInstanceCount"])
        self.assertEqual(["HarnessEngagement__c.Status__c"], facts["visibilityRuleFields"])

    def test_flexipage_edges(self) -> None:
        self.assertIn(("operates-on", "HarnessEngagement__c"), self.references)
        self.assertIn(("places-field", "HarnessEngagement__c.Discount__c"), self.references)
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), self.references)
        self.assertIn(("displays-component", "harnessEngagementPanel"), self.references)
        self.assertIn(("displays-component", "flexipage:reportChart"), self.references)
        self.assertIn(("launches-flow", "Escalation_Router"), self.references)


DEEP_LAYOUT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Layout xmlns="http://soap.sforce.com/2006/04/metadata">
  <layoutSections>
    <label>HarnessEngagement Details</label>
    <layoutColumns>
      <layoutItems><behavior>Required</behavior><field>Status__c</field></layoutItems>
      <layoutItems><behavior>Readonly</behavior><field>Total_Billed__c</field></layoutItems>
      <layoutItems><behavior>Edit</behavior><field>Name</field></layoutItems>
      <layoutItems><page>HarnessEngagementSummary</page></layoutItems>
    </layoutColumns>
  </layoutSections>
  <platformActionList>
    <actionListContext>Record</actionListContext>
    <platformActionListItems><actionName>HarnessEngagement__c.New_Milestone</actionName><actionType>QuickAction</actionType></platformActionListItems>
  </platformActionList>
  <relatedLists>
    <fields>NAME</fields><fields>STATUS</fields>
    <relatedList>Milestones__r</relatedList>
  </relatedLists>
</Layout>
"""
QUICK_ACTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<QuickAction xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>New Milestone</label>
  <type>Create</type>
  <targetObject>Milestone__c</targetObject>
  <targetParentField>HarnessEngagement__c</targetParentField>
  <quickActionLayout>
    <layoutSectionStyle>TwoColumnsLeftToRight</layoutSectionStyle>
    <quickActionLayoutColumns>
      <quickActionLayoutItems><field>Name</field><uiBehavior>Edit</uiBehavior></quickActionLayoutItems>
      <quickActionLayoutItems><field>Due_Date__c</field><uiBehavior>Required</uiBehavior></quickActionLayoutItems>
    </quickActionLayoutColumns>
  </quickActionLayout>
  <fieldOverrides><field>Status__c</field><formula>"Planned"</formula></fieldOverrides>
  <successMessage>Milestone created.</successMessage>
</QuickAction>
"""


class LayoutQuickActionTests(unittest.TestCase):
    """Phase 11: layout field behavior + quick-action entry points."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_layout_field_behavior_sections_and_actions(self) -> None:
        path = (
            self.root
            / "force-app/main/default/layouts/HarnessEngagement__c-HarnessEngagement Layout.layout-meta.xml"
        )
        write(path, DEEP_LAYOUT_XML)
        layout = self.builder.parse_layout(path)
        facts = layout["facts"]
        self.assertEqual(["HarnessEngagement__c.Status__c"], facts["requiredOnLayout"])
        self.assertEqual(["HarnessEngagement__c.Total_Billed__c"], facts["readonlyOnLayout"])
        self.assertEqual(["HarnessEngagement Details"], facts["sections"])
        self.assertEqual(
            [{"name": "Milestones__r", "fields": ["NAME", "STATUS"]}],
            facts["relatedLists"],
        )
        references = {(ref["kind"], ref["target"]) for ref in layout["references"]}
        self.assertIn(("action", "HarnessEngagement__c.New_Milestone"), references)
        self.assertIn(("displays-component", "HarnessEngagementSummary"), references)
        self.assertIn(("related-list", "Milestones__r"), references)

    def test_quick_action_target_fields_and_parent(self) -> None:
        path = (
            self.root
            / "force-app/main/default/quickActions/HarnessEngagement__c.New_Milestone.quickAction-meta.xml"
        )
        write(path, QUICK_ACTION_XML)
        action = self.builder.parse_quick_action(path)
        facts = action["facts"]
        self.assertEqual("Create", facts["actionType"])
        self.assertEqual("Milestone__c", facts["object"])
        self.assertEqual(2, facts["fieldCount"])
        self.assertEqual("Milestone created.", facts["successMessage"])
        references = {(ref["kind"], ref["target"]) for ref in action["references"]}
        self.assertIn(("operates-on", "Milestone__c"), references)
        self.assertIn(("places-field", "Milestone__c.Due_Date__c"), references)
        self.assertIn(("references-field", "Milestone__c.Status__c"), references)
        self.assertIn(("references-field", "Milestone__c.HarnessEngagement__c"), references)

    def test_quick_action_flow_variant(self) -> None:
        path = (
            self.root
            / "force-app/main/default/quickActions/Run_Escalation.quickAction-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<QuickAction xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Run Escalation</label><type>Flow</type>"
            "<flowDefinition>Escalation_Router</flowDefinition></QuickAction>\n",
        )
        action = self.builder.parse_quick_action(path)
        references = {(ref["kind"], ref["target"]) for ref in action["references"]}
        self.assertIn(("launches-flow", "Escalation_Router"), references)


class CustomApplicationTests(unittest.TestCase):
    """Phase 12: app navigation scope and per-profile page assignment."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        path = self.root / "force-app/main/default/applications/Service.app-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomApplication xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Service Console</label><navType>Console</navType><uiType>Lightning</uiType>"
            "<formFactors>Large</formFactors>"
            "<tabs>standard-Account</tabs><tabs>HarnessEngagement__c</tabs>"
            "<utilityBar>Service_UtilityBar</utilityBar>"
            "<profileActionOverrides>"
            "<actionName>View</actionName><content>HarnessEngagement_Record_Page</content>"
            "<formFactor>Large</formFactor><pageOrSobjectType>HarnessEngagement__c</pageOrSobjectType>"
            "<recordType>HarnessEngagement__c.Support</recordType><type>Flexipage</type>"
            "<profile>Support Agent</profile>"
            "</profileActionOverrides>"
            "</CustomApplication>\n",
        )
        self.app = ForceAppKnowledge(self.root).parse_custom_application(path)
        self.references = {(ref["kind"], ref["target"]) for ref in self.app["references"]}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_application_tabs_and_utility_bar(self) -> None:
        facts = self.app["facts"]
        self.assertEqual("Console", facts["navType"])
        self.assertEqual(["standard-Account", "HarnessEngagement__c"], facts["tabs"])
        self.assertTrue(facts["hasUtilityBar"])
        self.assertIn(("operates-on", "Account"), self.references)
        self.assertIn(("displays-component", "HarnessEngagement__c"), self.references)
        self.assertIn(("displays-component", "Service_UtilityBar"), self.references)

    def test_application_profile_override_assignment(self) -> None:
        override = self.app["facts"]["overrides"][0]
        self.assertEqual(
            {
                "action": "View",
                "content": "HarnessEngagement_Record_Page",
                "type": "Flexipage",
                "object": "HarnessEngagement__c",
                "recordType": "HarnessEngagement__c.Support",
                "profile": "Support Agent",
                "formFactor": "Large",
            },
            override,
        )
        self.assertIn(("overrides-view", "HarnessEngagement_Record_Page"), self.references)


DEEP_PERMISSION_SET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>HarnessEngagement Manager</label>
  <license>Salesforce</license>
  <hasActivationRequired>false</hasActivationRequired>
  <objectPermissions>
    <object>HarnessEngagement__c</object>
    <allowCreate>true</allowCreate><allowRead>true</allowRead><allowEdit>true</allowEdit>
    <allowDelete>false</allowDelete><viewAllRecords>true</viewAllRecords><modifyAllRecords>false</modifyAllRecords>
  </objectPermissions>
  <fieldPermissions><field>HarnessEngagement__c.Status__c</field><readable>true</readable><editable>true</editable></fieldPermissions>
  <fieldPermissions><field>HarnessEngagement__c.Margin__c</field><readable>true</readable><editable>false</editable></fieldPermissions>
  <fieldPermissions><field>HarnessEngagement__c.Secret__c</field><readable>false</readable><editable>false</editable></fieldPermissions>
  <classAccesses><apexClass>HarnessBillingService</apexClass><enabled>true</enabled></classAccesses>
  <customPermissions><name>Can_Override_Price</name><enabled>true</enabled></customPermissions>
  <recordTypeVisibilities><recordType>HarnessEngagement__c.Standard</recordType><visible>true</visible></recordTypeVisibilities>
  <flowAccesses><flow>Escalation_Router</flow><enabled>true</enabled></flowAccesses>
  <userPermissions><name>ModifyAllData</name><enabled>true</enabled></userPermissions>
</PermissionSet>
"""
PROFILE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Profile xmlns="http://soap.sforce.com/2006/04/metadata">
  <custom>true</custom>
  <userLicense>Salesforce</userLicense>
  <fieldPermissions><field>HarnessEngagement__c.Status__c</field><readable>true</readable><editable>false</editable></fieldPermissions>
  <layoutAssignments><layout>HarnessEngagement__c-HarnessEngagement Layout</layout><recordType>HarnessEngagement__c.Standard</recordType></layoutAssignments>
  <recordTypeVisibilities><recordType>HarnessEngagement__c.Standard</recordType><visible>true</visible><default>true</default></recordTypeVisibilities>
  <applicationVisibilities><application>Service</application><visible>true</visible><default>true</default></applicationVisibilities>
  <loginIpRanges><startAddress>10.0.0.1</startAddress><endAddress>10.0.0.255</endAddress></loginIpRanges>
  <loginHours><mondayStart>420</mondayStart><mondayEnd>1140</mondayEnd></loginHours>
</Profile>
"""


class AccessModelTests(unittest.TestCase):
    """Phase 13: level-aware grants, CRUD map, Profile parsing, cap priorities."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def parse_permission_set(self, xml: str) -> dict:
        path = (
            self.root
            / "force-app/main/default/permissionsets/HarnessEngagement_Manager.permissionset-meta.xml"
        )
        write(path, xml)
        return self.builder.parse_permission_set(path)

    def test_field_grants_carry_levels(self) -> None:
        component = self.parse_permission_set(DEEP_PERMISSION_SET_XML)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("grants-field-edit", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("grants-field-read", "HarnessEngagement__c.Margin__c"), references)
        # No grant at all → no edge; the legacy level-blind kind is no longer emitted.
        self.assertNotIn(
            ("grants-field-read", "HarnessEngagement__c.Secret__c"), references
        )
        self.assertFalse(
            any(ref["kind"] == "grants-field-permission" for ref in component["references"])
        )

    def test_object_access_map_and_grant_edges(self) -> None:
        component = self.parse_permission_set(DEEP_PERMISSION_SET_XML)
        facts = component["facts"]
        self.assertEqual({"HarnessEngagement__c": "CRE+VA"}, facts["objectAccess"])
        self.assertEqual(["ModifyAllData"], facts["systemPermissions"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("grants-object-permission", "HarnessEngagement__c"), references)
        self.assertIn(("grants-object-view-all", "HarnessEngagement__c"), references)
        self.assertNotIn(("grants-object-modify-all", "HarnessEngagement__c"), references)
        self.assertIn(("grants-class-access", "HarnessBillingService"), references)
        self.assertIn(("grants-custom-permission", "Can_Override_Price"), references)
        self.assertIn(("grants-record-type", "HarnessEngagement__c.Standard"), references)
        self.assertIn(("grants-flow-access", "Escalation_Router"), references)
        self.assertIn(("grants-user-permission", "ModifyAllData"), references)

    def test_cap_priority_cuts_field_grants_first(self) -> None:
        rows = "".join(
            f"<fieldPermissions><field>HarnessEngagement__c.F{i}__c</field>"
            "<readable>true</readable><editable>false</editable></fieldPermissions>"
            for i in range(400)
        )
        xml = DEEP_PERMISSION_SET_XML.replace("</PermissionSet>", rows + "</PermissionSet>")
        component = self.parse_permission_set(xml)
        facts = component["facts"]
        self.assertTrue(facts["referencesTruncated"])
        self.assertEqual(["grants-field-read"], facts["truncatedFamilies"])
        kinds = {ref["kind"] for ref in component["references"]}
        # High-priority families survive the cap intact.
        self.assertIn("grants-user-permission", kinds)
        self.assertIn("grants-object-permission", kinds)
        self.assertIn("grants-class-access", kinds)
        self.assertEqual(403, facts["fieldPermissionCount"])

    def test_profile_layout_assignment_and_posture(self) -> None:
        path = self.root / "force-app/main/default/profiles/Support Agent.profile-meta.xml"
        write(path, PROFILE_XML)
        component = self.builder.parse_profile(path)
        self.assertEqual("Profile:Support Agent", component["id"])
        facts = component["facts"]
        self.assertTrue(facts["custom"])
        self.assertEqual(
            {"HarnessEngagement__c": "HarnessEngagement__c.Standard"}, facts["defaultRecordTypes"]
        )
        self.assertEqual("Service", facts["defaultApplication"])
        self.assertTrue(facts["loginIpRangesPresent"])
        self.assertEqual(1, facts["loginIpRangeCount"])
        self.assertTrue(facts["loginHoursPresent"])
        serialized = canonical(component)
        self.assertNotIn("10.0.0.1", serialized)
        self.assertNotIn("420", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(
            ("assigns-layout", "HarnessEngagement__c-HarnessEngagement Layout"), references
        )
        self.assertIn(("grants-field-read", "HarnessEngagement__c.Status__c"), references)


class ListSharingQueueTests(unittest.TestCase):
    """Phase 14: list views, field sets, sharing rules, queues."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_list_view_columns_and_filters(self) -> None:
        path = (
            self.root
            / "force-app/main/default/objects/HarnessEngagement__c/listViews/Open.listView-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ListView xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Open</fullName><label>Open HarnessEngagements</label>"
            "<filterScope>Everything</filterScope>"
            "<columns>NAME</columns><columns>Status__c</columns>"
            "<filters><field>Status__c</field><operation>equals</operation><value>Open</value></filters>"
            "</ListView>\n",
        )
        component = self.builder.parse_list_view(path)
        facts = component["facts"]
        self.assertEqual("Everything", facts["filterScope"])
        self.assertEqual(
            [{"field": "Status__c", "operator": "equals", "value": "Open"}],
            facts["filters"],
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "HarnessEngagement__c.NAME"), references)
        self.assertIn(("filters-field", "HarnessEngagement__c.Status__c"), references)

    def test_field_set_displayed_vs_available(self) -> None:
        path = (
            self.root
            / "force-app/main/default/objects/HarnessEngagement__c/fieldSets/HarnessBilling.fieldSet-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<FieldSet xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>HarnessBilling</fullName><label>HarnessBilling Fields</label>"
            "<displayedFields><field>Amount__c</field></displayedFields>"
            "<availableFields><field>Margin__c</field></availableFields>"
            "</FieldSet>\n",
        )
        component = self.builder.parse_field_set(path)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("places-field", "HarnessEngagement__c.Amount__c"), references)
        self.assertIn(("references-field", "HarnessEngagement__c.Margin__c"), references)

    def test_sharing_rules_criteria_and_grantees(self) -> None:
        path = (
            self.root
            / "force-app/main/default/sharingRules/HarnessEngagement__c.sharingRules-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<SharingRules xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<sharingCriteriaRules>"
            "<fullName>EMEA_Read</fullName><accessLevel>Read</accessLevel>"
            "<criteriaItems><field>Region__c</field><operation>equals</operation><value>EMEA</value></criteriaItems>"
            "<sharedTo><roleAndSubordinates>EMEA_Sales</roleAndSubordinates></sharedTo>"
            "</sharingCriteriaRules>"
            "<sharingOwnerRules>"
            "<fullName>Ops_Full</fullName><accessLevel>Edit</accessLevel>"
            "<sharedFrom><group>Field_Ops</group></sharedFrom>"
            "<sharedTo><group>HQ_Ops</group></sharedTo>"
            "</sharingOwnerRules>"
            "</SharingRules>\n",
        )
        component = self.builder.parse_sharing_rules(path)
        facts = component["facts"]
        rule = facts["criteriaRules"][0]
        self.assertEqual("Read", rule["accessLevel"])
        self.assertEqual(
            [{"field": "Region__c", "operator": "equals", "value": "EMEA"}],
            rule["criteria"],
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("filters-field", "HarnessEngagement__c.Region__c"), references)
        self.assertIn(
            ("shares-with", "roleAndSubordinates:EMEA_Sales"), references
        )
        self.assertIn(("shares-with", "group:HQ_Ops"), references)
        # sharedFrom parties are ownership scoping, not grants.
        self.assertNotIn(("shares-with", "group:Field_Ops"), references)

    def test_queue_serves_objects_with_member_counts_only(self) -> None:
        path = self.root / "force-app/main/default/queues/Tier1_Support.queue-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Queue xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<name>Tier1_Support</name><doesSendEmailToMembers>true</doesSendEmailToMembers>"
            "<email>tier1@example.test</email>"
            "<queueSobject><sobjectType>Case</sobjectType></queueSobject>"
            "<queueSobject><sobjectType>Lead</sobjectType></queueSobject>"
            "<queueMembers><users><user>agent.one@example.test</user><user>agent.two@example.test</user></users></queueMembers>"
            "</Queue>\n",
        )
        component = self.builder.parse_queue(path)
        facts = component["facts"]
        self.assertEqual(["Case", "Lead"], facts["servesObjects"])
        self.assertEqual({"users": 2}, facts["memberCounts"])
        serialized = canonical(component)
        self.assertNotIn("tier1@example.test", serialized)
        self.assertNotIn("agent.one@example.test", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("serves-object", "Case"), references)
        self.assertIn(("serves-object", "Lead"), references)


class RuleFileTests(unittest.TestCase):
    """Phase 15: shared assignment/auto-response/escalation rule parsing."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_assignment_rules_queue_targets_never_users(self) -> None:
        path = (
            self.root
            / "force-app/main/default/assignmentRules/Case.assignmentRules-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<AssignmentRules xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<assignmentRule><fullName>Standard</fullName><active>true</active>"
            "<ruleEntry>"
            "<criteriaItems><field>Case.Priority</field><operation>equals</operation><value>High</value></criteriaItems>"
            "<assignedTo>Tier1_Support</assignedTo><assignedToType>Queue</assignedToType>"
            "<template>unfiled$public/CaseAck</template>"
            "</ruleEntry>"
            "<ruleEntry>"
            "<criteriaItems><field>Case.Priority</field><operation>equals</operation><value>Low</value></criteriaItems>"
            "<assignedTo>jane.doe@example.test</assignedTo><assignedToType>User</assignedToType>"
            "</ruleEntry>"
            "</assignmentRule>"
            "</AssignmentRules>\n",
        )
        component = self.builder.parse_rule_file(path, token="assignmentRules")
        self.assertEqual("AssignmentRules:Case", component["id"])
        rule = component["facts"]["rules"][0]
        self.assertTrue(rule["active"])
        self.assertEqual(2, len(rule["entries"]))
        self.assertEqual(
            {"assignedToType": "User"},
            {
                key: value
                for key, value in rule["entries"][1].items()
                if key.startswith("assigned")
            },
        )
        serialized = canonical(component)
        self.assertNotIn("jane.doe@example.test", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("filters-field", "Case.Priority"), references)
        self.assertIn(("assigns-to", "Tier1_Support"), references)
        self.assertIn(("uses-template", "unfiled$public/CaseAck"), references)
        claims = self.builder.candidate_claims(component)
        self.assertIn("automation-inventory", [claim["claimType"] for claim in claims])

    def test_escalation_rules_actions(self) -> None:
        path = (
            self.root
            / "force-app/main/default/escalationRules/Case.escalationRules-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<EscalationRules xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<escalationRule><fullName>SLA</fullName><active>true</active>"
            "<ruleEntry>"
            "<criteriaItems><field>Case.Status</field><operation>equals</operation><value>New</value></criteriaItems>"
            "<escalationAction><minutesToEscalation>60</minutesToEscalation>"
            "<assignedTo>Tier2_Support</assignedTo><assignedToType>Queue</assignedToType>"
            "<notifyCaseOwner>true</notifyCaseOwner></escalationAction>"
            "</ruleEntry>"
            "</escalationRule>"
            "</EscalationRules>\n",
        )
        component = self.builder.parse_rule_file(path, token="escalationRules")
        action = component["facts"]["rules"][0]["entries"][0]["escalationActions"][0]
        self.assertEqual("60", action["minutesToEscalation"])
        self.assertTrue(action["notifyCaseOwner"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("assigns-to", "Tier2_Support"), references)


class IntegrationFamilyTests(unittest.TestCase):
    """Phase 16: credential chains, posture facts, connected-app grants."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_named_credential_external_credential_chain(self) -> None:
        path = self.base / "namedCredentials/HarnessBillingV2.namedCredential-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>HarnessBilling v2</label><namedCredentialType>SecuredEndpoint</namedCredentialType>"
            "<namedCredentialParameters><parameterName>url</parameterName><parameterType>Url</parameterType>"
            "<parameterValue>https://api.billing.example.test/v2</parameterValue></namedCredentialParameters>"
            "<namedCredentialParameters><parameterType>Authentication</parameterType>"
            "<externalCredential>HarnessBilling_OAuth</externalCredential></namedCredentialParameters>"
            "</NamedCredential>\n",
        )
        component = self.builder.parse_integration(path, "NamedCredential")
        self.assertEqual("api.billing.example.test", component["facts"]["endpointHost"])
        self.assertEqual("HarnessBilling_OAuth", component["facts"]["externalCredential"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-external-credential", "HarnessBilling_OAuth"), references)

    def test_external_credential_principals_no_secrets(self) -> None:
        path = self.base / "externalCredentials/HarnessBilling_OAuth.externalCredential-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ExternalCredential xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>HarnessBilling OAuth</label>"
            "<authenticationProtocol>OAuth</authenticationProtocol>"
            "<authenticationProtocolVariant>ClientCredentialsClientSecretBasic</authenticationProtocolVariant>"
            "<externalCredentialParameters><parameterName>HarnessBillingPrincipal</parameterName>"
            "<parameterType>NamedPrincipal</parameterType><sequenceNumber>1</sequenceNumber></externalCredentialParameters>"
            "<externalCredentialParameters><parameterName>clientSecret</parameterName>"
            "<parameterType>AuthParameter</parameterType><parameterValue>super-secret-value</parameterValue></externalCredentialParameters>"
            "<externalCredentialParameters><parameterType>AuthProvider</parameterType>"
            "<authProvider>AzureAD</authProvider></externalCredentialParameters>"
            "</ExternalCredential>\n",
        )
        component = self.builder.parse_integration(path, "ExternalCredential")
        facts = component["facts"]
        self.assertEqual("OAuth", facts["authenticationProtocol"])
        self.assertEqual(
            [{"name": "HarnessBillingPrincipal", "type": "NamedPrincipal", "sequence": "1"}],
            facts["principals"],
        )
        self.assertNotIn("super-secret-value", canonical(component))
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-auth-provider", "AzureAD"), references)

    def test_remote_site_posture_facts(self) -> None:
        path = self.base / "remoteSiteSettings/Legacy.remoteSite-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<RemoteSiteSetting xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Legacy</fullName><url>http://legacy.example.test/api</url>"
            "<isActive>true</isActive><disableProtocolSecurity>true</disableProtocolSecurity>"
            "</RemoteSiteSetting>\n",
        )
        component = self.builder.parse_integration(path, "RemoteSiteSetting")
        facts = component["facts"]
        self.assertTrue(facts["isActive"])
        self.assertTrue(facts["disableProtocolSecurity"])
        self.assertEqual("legacy.example.test", facts["endpointHost"])

    def test_external_service_registration_credential_reuse(self) -> None:
        path = (
            self.base
            / "externalServiceRegistrations/HarnessBillingAPI.externalServiceRegistration-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ExternalServiceRegistration xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>HarnessBilling API</label><namedCredential>HarnessBillingV2</namedCredential>"
            "<registrationProviderType>Custom</registrationProviderType>"
            "<schema>{&quot;openapi&quot;: &quot;3.0.0&quot;}</schema>"
            "<status>Complete</status></ExternalServiceRegistration>\n",
        )
        component = self.builder.parse_integration(path, "ExternalServiceRegistration")
        facts = component["facts"]
        self.assertTrue(facts["schemaPresent"])
        self.assertNotIn("openapi", canonical(component["facts"].get("schema", "")))
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-named-credential", "HarnessBillingV2"), references)

    def test_connected_app_scopes_and_grants_no_secrets(self) -> None:
        path = self.base / "connectedApps/Partner_Portal.connectedApp-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ConnectedApp xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Partner Portal</label><contactEmail>owner@example.test</contactEmail>"
            "<oauthConfig>"
            "<callbackUrl>https://portal.example.test/oauth/callback?tenant=9</callbackUrl>"
            "<consumerKey>3MVG9-never-export</consumerKey>"
            "<scopes>Api</scopes><scopes>RefreshToken</scopes>"
            "<isAdminApproved>true</isAdminApproved>"
            "</oauthConfig>"
            "<ipRelaxation>ENFORCE</ipRelaxation>"
            "<profileName>Partner User</profileName>"
            "<permissionsetName>Portal_Access</permissionsetName>"
            "</ConnectedApp>\n",
        )
        component = self.builder.parse_integration(path, "ConnectedApp")
        facts = component["facts"]
        self.assertEqual(["Api", "RefreshToken"], facts["oauthScopes"])
        self.assertTrue(facts["isAdminApproved"])
        self.assertEqual("ENFORCE", facts["ipRelaxation"])
        self.assertEqual("portal.example.test", facts["callbackHost"])
        serialized = canonical(component)
        self.assertNotIn("3MVG9-never-export", serialized)
        self.assertNotIn("owner@example.test", serialized)
        self.assertNotIn("tenant=9", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("grants-to-profile", "Partner User"), references)
        self.assertIn(("grants-to-permission-set", "Portal_Access"), references)

    def test_external_data_source_typing_and_claim_routing(self) -> None:
        path = self.base / "dataSources/ERP.dataSource-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ExternalDataSource xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>ERP</label><type>OData4</type>"
            "<endpoint>https://erp.example.test/odata</endpoint>"
            "<principalType>NamedUser</principalType><protocol>Password</protocol>"
            "<isWritable>true</isWritable></ExternalDataSource>\n",
        )
        component = self.builder.parse_integration(path, "ExternalDataSource")
        facts = component["facts"]
        self.assertEqual("OData4", facts["sourceType"])
        self.assertEqual("erp.example.test", facts["endpointHost"])
        self.assertTrue(facts["isWritable"])
        claims = self.builder.candidate_claims(component)
        self.assertIn("integration", [claim["claimType"] for claim in claims])


class VfAuraLabelsTests(unittest.TestCase):
    """Phase 17: Visualforce parsing, Aura deepening, per-label components."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_visualforce_controller_and_field_io(self) -> None:
        path = self.base / "pages/HarnessEngagementEdit.page"
        write(
            path,
            '<apex:page standardController="HarnessEngagement__c" extensions="HarnessEngagementExt,AuditExt">\n'
            '  <apex:inputField value="{!HarnessEngagement__c.Status__c}"/>\n'
            '  <apex:outputField value="{!HarnessEngagement__c.Total_Billed__c}"/>\n'
            '  <apex:outputText value="{!$Label.HarnessEngagement_Header}"/>\n'
            '  <apex:commandButton action="{!save}" value="Save"/>\n'
            "  <c:statusBadge/>\n"
            "</apex:page>\n",
        )
        write(
            path.with_name("HarnessEngagementEdit.page-meta.xml"),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ApexPage xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<apiVersion>61.0</apiVersion><label>HarnessEngagement Edit</label></ApexPage>\n",
        )
        component = self.builder.parse_visualforce(path, "ApexPage")
        facts = component["facts"]
        self.assertEqual("HarnessEngagement__c", facts["standardController"])
        self.assertEqual(["HarnessEngagementExt", "AuditExt"], facts["extensions"])
        self.assertEqual(["save"], facts["actionMethods"])
        self.assertEqual("61.0", facts["apiVersion"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "HarnessEngagement__c"), references)
        self.assertIn(("apex-controller", "HarnessEngagementExt"), references)
        self.assertIn(("writes-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("reads-field", "HarnessEngagement__c.Total_Billed__c"), references)
        self.assertIn(("uses-label", "HarnessEngagement_Header"), references)
        self.assertIn(("embeds-component", "statusBadge"), references)

    def test_aura_record_data_and_implements(self) -> None:
        bundle = self.base / "aura/harnessEngagementCard"
        write(
            bundle / "harnessEngagementCard.cmp",
            '<aura:component controller="HarnessEngagementController" '
            'implements="flexipage:availableForAllPageTypes,force:hasRecordId">\n'
            '  <aura:attribute name="row" type="HarnessEngagement__c"/>\n'
            '  <force:recordData sObjectName="HarnessEngagement__c" fields="Name,Status__c"/>\n'
            "  <c:statusBadge/>\n"
            "  <div>{!$Label.c.HarnessEngagement_Header}</div>\n"
            "</aura:component>\n",
        )
        component = self.builder.parse_aura(bundle)
        facts = component["facts"]
        self.assertIn("flexipage:availableForAllPageTypes", facts["implements"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("apex-controller", "HarnessEngagementController"), references)
        self.assertIn(("operates-on", "HarnessEngagement__c"), references)
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("uses-label", "HarnessEngagement_Header"), references)
        self.assertIn(("embeds-component", "statusBadge"), references)

    def test_custom_labels_promoted_with_searchable_statement(self) -> None:
        path = self.base / "labels/CustomLabels.labels-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomLabels xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<labels><fullName>HarnessEngagement_Header</fullName>"
            "<value>HarnessEngagement overview</value><language>en_US</language>"
            "<protected>false</protected><categories>UI</categories>"
            "<shortDescription>Header text</shortDescription></labels>"
            "<labels><fullName>Blocked_Message</fullName>"
            "<value>This harnessEngagement is blocked by finance.</value><language>en_US</language>"
            "<protected>true</protected><shortDescription>Blocked banner</shortDescription></labels>"
            "</CustomLabels>\n",
        )
        components = self.builder.parse_custom_labels(path)
        self.assertEqual(3, len(components))
        by_id = {component["id"]: component for component in components}
        label = by_id["CustomLabel:Blocked_Message"]
        self.assertEqual(
            "This harnessEngagement is blocked by finance.", label["facts"]["value"]
        )
        self.assertEqual(2, by_id["CustomLabels:CustomLabels"]["facts"]["labelCount"])
        claims = self.builder.candidate_claims(label)
        self.assertIn("blocked by finance", claims[0]["statement"])

    def test_label_consumers_emit_uses_label(self) -> None:
        apex = self.base / "classes/Banner.cls"
        write(
            apex,
            "public class Banner { String text = System.Label.Blocked_Message; }\n",
        )
        component = self.builder.parse_apex(apex, "ApexClass")
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("uses-label", "Blocked_Message"), references)


class CmdtPermissionTabTests(unittest.TestCase):
    """Phase 18: cmdt records, $Permission gates, PSG composition, tab kinds."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_cmdt_record_identity_and_redaction(self) -> None:
        path = self.base / "customMetadata/ServiceBinding.HarnessBilling.md-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomMetadata xmlns="http://soap.sforce.com/2006/04/metadata" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            "<label>HarnessBilling</label><protected>false</protected>"
            "<values><field>Endpoint__c</field>"
            '<value xsi:type="xsd:string">https://api.example.test/billing?key=1</value></values>'
            "<values><field>ApiKey__c</field>"
            '<value xsi:type="xsd:string">password=super-secret</value></values>'
            "<values><field>Active__c</field><value xsi:type=\"xsd:boolean\">true</value></values>"
            "</CustomMetadata>\n",
        )
        component = self.builder.parse_custom_metadata_record(path)
        self.assertEqual("CustomMetadata:ServiceBinding__mdt.HarnessBilling", component["id"])
        facts = component["facts"]
        self.assertEqual(
            ["Active__c", "ApiKey__c", "Endpoint__c"], facts["fieldsPopulated"]
        )
        values = {item["field"]: item.get("value") for item in facts["values"]}
        self.assertEqual("api.example.test", values["Endpoint__c"])
        self.assertNotIn("value", [k for k in values if values.get("ApiKey__c")])
        serialized = canonical(component)
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("key=1", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "ServiceBinding__mdt"), references)
        self.assertIn(
            ("references-field", "ServiceBinding__mdt.Endpoint__c"), references
        )

    def test_cmdt_protected_record_drops_values(self) -> None:
        path = self.base / "customMetadata/ServiceBinding.Secret.md-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomMetadata xmlns="http://soap.sforce.com/2006/04/metadata" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            "<label>Secret</label><protected>true</protected>"
            "<values><field>Token__c</field>"
            '<value xsi:type="xsd:string">plain-but-protected</value></values>'
            "</CustomMetadata>\n",
        )
        component = self.builder.parse_custom_metadata_record(path)
        self.assertEqual(["Token__c"], component["facts"]["fieldsPopulated"])
        self.assertNotIn("values", component["facts"])
        self.assertNotIn("plain-but-protected", canonical(component))

    def test_permission_token_edges_from_validation_rule_and_flow(self) -> None:
        rule_path = (
            self.base
            / "objects/HarnessEngagement__c/validationRules/Price_Guard.validationRule-meta.xml"
        )
        write(
            rule_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Price_Guard</fullName><active>true</active>"
            "<errorConditionFormula>NOT($Permission.Can_Override_Price)</errorConditionFormula>"
            "<errorMessage>You cannot override the price.</errorMessage>"
            "</ValidationRule>\n",
        )
        rule = self.builder.parse_validation_rule(rule_path)
        references = {(ref["kind"], ref["target"]) for ref in rule["references"]}
        self.assertIn(
            ("references-custom-permission", "Can_Override_Price"), references
        )
        flow_path = self.base / "flows/Override_Gate.flow-meta.xml"
        write(
            flow_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Override Gate</label><status>Active</status>"
            "<formulas><name>CanOverride</name><dataType>Boolean</dataType>"
            "<expression>{!$Permission.Can_Override_Price}</expression></formulas>"
            "</Flow>\n",
        )
        flow = self.builder.parse_flow(flow_path)
        flow_references = {(ref["kind"], ref["target"]) for ref in flow["references"]}
        self.assertIn(
            ("references-custom-permission", "Can_Override_Price"), flow_references
        )

    def test_permission_set_group_composition(self) -> None:
        path = self.base / "permissionsetgroups/Ops.permissionsetgroup-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<PermissionSetGroup xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Ops</label><status>Updated</status>"
            "<permissionSets>HarnessEngagement_Manager</permissionSets>"
            "<permissionSets>HarnessBilling_Reader</permissionSets>"
            "<mutingPermissionSets>Ops_Mute</mutingPermissionSets>"
            "</PermissionSetGroup>\n",
        )
        component = self.builder.parse_permission_set_group(path)
        self.assertEqual(2, component["facts"]["permissionSetCount"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("includes-permission-set", "HarnessEngagement_Manager"), references)
        self.assertIn(("mutes-permission-set", "Ops_Mute"), references)

    def test_tab_kind_variants(self) -> None:
        object_tab = self.base / "tabs/HarnessEngagement__c.tab-meta.xml"
        write(
            object_tab,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomTab xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<customObject>true</customObject><label>HarnessEngagements</label>"
            "<motif>Custom54</motif></CustomTab>\n",
        )
        component = self.builder.parse_custom_tab(object_tab)
        self.assertEqual("object", component["facts"]["tabKind"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "HarnessEngagement__c"), references)
        web_tab = self.base / "tabs/Portal.tab-meta.xml"
        write(
            web_tab,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CustomTab xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Portal</label><url>https://portal.example.test/home?x=1</url>"
            "</CustomTab>\n",
        )
        component = self.builder.parse_custom_tab(web_tab)
        self.assertEqual("web", component["facts"]["tabKind"])
        self.assertEqual("portal.example.test", component["facts"]["urlHost"])
        self.assertNotIn("x=1", canonical(component))
        self.assertEqual([], component["references"])


class AnalyticsPathTests(unittest.TestCase):
    """Phase 19: report types, reports, dashboards, path guidance."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_report_type_base_object_and_columns(self) -> None:
        path = self.base / "reportTypes/HarnessEngagements_with_Milestones.reportType-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ReportType xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>HarnessEngagements with Milestones</label><baseObject>HarnessEngagement__c</baseObject>"
            "<category>other</category><deployed>true</deployed>"
            "<sections><masterLabel>Fields</masterLabel>"
            "<columns><field>Status__c</field><table>HarnessEngagement__c</table><checkedByDefault>true</checkedByDefault></columns>"
            "<columns><field>Due_Date__c</field><table>HarnessEngagement__c.Milestones__r</table><checkedByDefault>false</checkedByDefault></columns>"
            "</sections></ReportType>\n",
        )
        component = self.builder.parse_report_type(path)
        facts = component["facts"]
        self.assertEqual("HarnessEngagement__c", facts["baseObject"])
        self.assertEqual(
            ["HarnessEngagement__c", "HarnessEngagement__c.Milestones__r"], facts["tables"]
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "HarnessEngagement__c"), references)
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), references)
        # Join-path fields stay facts-only; the child object is not resolvable.
        self.assertNotIn(
            ("references-field", "HarnessEngagement__c.Milestones__r.Due_Date__c"), references
        )

    def test_report_bounded_refs_with_values(self) -> None:
        path = self.base / "reports/Sales/Open_HarnessEngagements.report-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Report xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<name>Open HarnessEngagements</name><format>Summary</format>"
            "<reportType>HarnessEngagements_with_Milestones</reportType>"
            "<columns><field>HarnessEngagement__c.Status__c</field></columns>"
            "<filter><criteriaItems><column>HarnessEngagement__c.Region__c</column>"
            "<operator>equals</operator><value>EMEA</value></criteriaItems></filter>"
            "<groupingsDown><field>HarnessEngagement__c.Owner__c</field></groupingsDown>"
            "<timeFrameFilter><dateColumn>HarnessEngagement__c.CreatedDate</dateColumn>"
            "<interval>INTERVAL_CURRENT</interval></timeFrameFilter>"
            "</Report>\n",
        )
        component = self.builder.parse_report(path)
        facts = component["facts"]
        self.assertEqual("Sales", facts["folder"])
        self.assertEqual(
            [{"column": "HarnessEngagement__c.Region__c", "operator": "equals", "value": "EMEA"}],
            facts["filters"],
        )
        self.assertEqual(
            {"dateColumn": "HarnessEngagement__c.CreatedDate", "interval": "INTERVAL_CURRENT"},
            facts["timeFrame"],
        )
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("filters-field", "HarnessEngagement__c.Region__c"), references)
        for reference in component["references"]:
            self.assertTrue(reference.get("heuristic"), reference)

    def test_dashboard_report_links_without_running_user(self) -> None:
        path = self.base / "dashboards/Sales/Pipeline.dashboard-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Dashboard xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<title>Pipeline</title><runningUser>ops.admin@example.test</runningUser>"
            "<leftSection><dashboardComponent><report>Sales/Open_HarnessEngagements</report></dashboardComponent></leftSection>"
            "</Dashboard>\n",
        )
        component = self.builder.parse_dashboard(path)
        facts = component["facts"]
        self.assertEqual("SpecifiedUser", facts["runningUserPolicy"])
        self.assertNotIn("ops.admin@example.test", canonical(component))
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("displays-component", "Sales/Open_HarnessEngagements"), references)

    def test_path_assistant_guidance_and_step_fields(self) -> None:
        path = self.base / "pathAssistants/HarnessEngagement_Path.pathAssistant-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<PathAssistant xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<masterLabel>HarnessEngagement Path</masterLabel><active>true</active>"
            "<entityName>HarnessEngagement__c</entityName><fieldName>Status__c</fieldName>"
            "<pathAssistantSteps>"
            "<picklistValueName>Kickoff</picklistValueName>"
            "<fieldNames>Owner__c</fieldNames><fieldNames>Start_Date__c</fieldNames>"
            "<info>&lt;p&gt;Confirm the &lt;b&gt;start date&lt;/b&gt; with the client.&lt;/p&gt;</info>"
            "</pathAssistantSteps>"
            "</PathAssistant>\n",
        )
        component = self.builder.parse_path_assistant(path)
        facts = component["facts"]
        self.assertEqual("HarnessEngagement__c.Status__c", facts["drivingField"])
        step = facts["steps"][0]
        self.assertEqual("Kickoff", step["value"])
        self.assertIn("start date", step["guidance"])
        self.assertNotIn("<b>", step["guidance"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "HarnessEngagement__c.Status__c"), references)
        self.assertIn(("places-field", "HarnessEngagement__c.Start_Date__c"), references)


class MatchingFlowDefinitionTests(unittest.TestCase):
    """Phase 20: matching-rule components resolve dedupe links; flow activation pointer."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_matching_rules_per_rule_components_resolve_duplicate_link(self) -> None:
        path = self.base / "matchingRules/Contact.matchingRule-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MatchingRules xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<matchingRules><fullName>Standard_Lead_Match</fullName>"
            "<label>Standard Lead Match</label><ruleStatus>Active</ruleStatus>"
            "<matchingRuleItems><fieldName>Email</fieldName><matchingMethod>Exact</matchingMethod>"
            "<blankValueBehavior>NullNotAllowed</blankValueBehavior></matchingRuleItems>"
            "</matchingRules>"
            "<matchingRules><fullName>Fuzzy_Name</fullName><ruleStatus>Inactive</ruleStatus>"
            "<matchingRuleItems><fieldName>LastName</fieldName><matchingMethod>LastName</matchingMethod>"
            "<blankValueBehavior>MatchBlanks</blankValueBehavior></matchingRuleItems>"
            "</matchingRules>"
            "</MatchingRules>\n",
        )
        components = self.builder.parse_matching_rules(path)
        self.assertEqual(2, len(components))
        by_id = {component["id"]: component for component in components}
        # Identity matches the uses-matching-rule target Phase 8's DuplicateRule emits.
        rule = by_id["MatchingRule:Contact.Standard_Lead_Match"]
        self.assertEqual("Active", rule["facts"]["ruleStatus"])
        self.assertEqual(
            [{"field": "Email", "matchingMethod": "Exact", "blankValueBehavior": "NullNotAllowed"}],
            rule["facts"]["items"],
        )
        references = {(ref["kind"], ref["target"]) for ref in rule["references"]}
        self.assertIn(("operates-on", "Contact"), references)
        self.assertIn(("references-field", "Contact.Email"), references)

    def test_flow_definition_active_override_relationship(self) -> None:
        path = self.base / "flowDefinitions/Escalation_Router.flowDefinition-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<FlowDefinition xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<activeVersionNumber>0</activeVersionNumber>"
            "<description>Deactivated pending rework.</description>"
            "</FlowDefinition>\n",
        )
        component = self.builder.parse_flow_definition(path)
        facts = component["facts"]
        self.assertEqual("0", facts["activeVersionNumber"])
        self.assertFalse(facts["active"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("relationship", "Flow.Escalation_Router"), references)


class CompactLayoutWebLinkTests(unittest.TestCase):
    """Phase 21: highlight fields and legacy button surfaces."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.objects = self.root / "force-app/main/default/objects"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_compact_layout_places_fields(self) -> None:
        path = (
            self.objects
            / "HarnessEngagement__c/compactLayouts/HarnessEngagement_Compact.compactLayout-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CompactLayout xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>HarnessEngagement_Compact</fullName><label>HarnessEngagement Compact</label>"
            "<fields>Name</fields><fields>Status__c</fields></CompactLayout>\n",
        )
        component = self.builder.parse_compact_layout(path)
        self.assertEqual(["Name", "Status__c"], component["facts"]["fields"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("places-field", "HarnessEngagement__c.Status__c"), references)

    def test_web_link_kinds_host_only_no_js_body(self) -> None:
        url_link = self.objects / "HarnessEngagement__c/webLinks/Open_Portal.webLink-meta.xml"
        write(
            url_link,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<WebLink xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Open_Portal</fullName><masterLabel>Open Portal</masterLabel>"
            "<displayType>button</displayType><linkType>url</linkType><openType>newWindow</openType>"
            "<url>https://portal.example.test/view?id={!HarnessEngagement__c.External_Id__c}</url>"
            "</WebLink>\n",
        )
        component = self.builder.parse_web_link(url_link)
        facts = component["facts"]
        self.assertEqual("portal.example.test", facts["targetHost"])
        self.assertNotIn("isJavascript", facts)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(
            ("references-field", "HarnessEngagement__c.External_Id__c"), references
        )
        js_link = self.objects / "HarnessEngagement__c/webLinks/Legacy_JS.webLink-meta.xml"
        write(
            js_link,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<WebLink xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Legacy_JS</fullName><masterLabel>Legacy JS</masterLabel>"
            "<displayType>button</displayType><linkType>javascript</linkType>"
            "<url>alert('secret-internal-logic');</url></WebLink>\n",
        )
        component = self.builder.parse_web_link(js_link)
        self.assertTrue(component["facts"]["isJavascript"])
        self.assertNotIn("secret-internal-logic", canonical(component))
        page_link = self.objects / "HarnessEngagement__c/webLinks/Summary.webLink-meta.xml"
        write(
            page_link,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<WebLink xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<fullName>Summary</fullName><linkType>page</linkType>"
            "<page>HarnessEngagementSummary</page></WebLink>\n",
        )
        component = self.builder.parse_web_link(page_link)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("displays-component", "HarnessEngagementSummary"), references)


class EmailStaticResourceTests(unittest.TestCase):
    """Phase 22: template targets, merge-field diet, resource cache posture."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_email_template_merge_fields_and_target_format(self) -> None:
        path = self.base / "email/unfiled$public/EscalationNotice.email"
        write(
            path,
            "Dear {!Contact.FirstName},\n"
            "Case {!Case.CaseNumber} for {!HarnessEngagement__c.Name} was escalated.\n"
            "{!$Label.Escalation_Footer}\n"
            "Regards, {!ignored.lowerHead}\n",
        )
        write(
            path.with_name("EscalationNotice.email-meta.xml"),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<EmailTemplate xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<type>text</type><subject>Your case was escalated</subject>"
            "<available>true</available><encodingKey>UTF-8</encodingKey>"
            "</EmailTemplate>\n",
        )
        component = self.builder.parse_email_template(path)
        # Identity matches the uses-template target format emitted by Workflow/approvals.
        self.assertEqual("EmailTemplate:unfiled$public/EscalationNotice", component["id"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("references-field", "Contact.FirstName"), references)
        self.assertIn(("references-field", "Case.CaseNumber"), references)
        self.assertIn(("references-field", "HarnessEngagement__c.Name"), references)
        self.assertNotIn(("references-field", "ignored.lowerHead"), references)
        self.assertIn(("uses-label", "Escalation_Footer"), references)

    def test_email_template_subject_searchable_statement(self) -> None:
        path = self.base / "email/unfiled$public/EscalationNotice.email"
        write(path, "body\n")
        write(
            path.with_name("EscalationNotice.email-meta.xml"),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<EmailTemplate xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<type>text</type><subject>Your case was escalated</subject></EmailTemplate>\n",
        )
        component = self.builder.parse_email_template(path)
        claims = self.builder.candidate_claims(component)
        self.assertIn("Your case was escalated", claims[0]["statement"])

    def test_static_resource_cache_posture(self) -> None:
        path = self.base / "staticresources/Assets.resource-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<StaticResource xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<contentType>application/zip</contentType><cacheControl>Public</cacheControl>"
            "<description>Vendor charting bundle.</description></StaticResource>\n",
        )
        component = self.builder.parse_static_resource(path)
        facts = component["facts"]
        self.assertEqual("application/zip", facts["contentType"])
        self.assertEqual("Public", facts["cacheControl"])


class RoleMutingDelegateTests(unittest.TestCase):
    """Phase 23: role hierarchy, negative grants, delegated-admin blast radius."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_role_hierarchy_reports_to(self) -> None:
        path = self.base / "roles/EMEA_Sales.role-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Role xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<name>EMEA Sales</name><parentRole>Global_Sales</parentRole>"
            "<caseAccessLevel>Edit</caseAccessLevel>"
            "<opportunityAccessLevel>Read</opportunityAccessLevel>"
            "</Role>\n",
        )
        component = self.builder.parse_role(path)
        self.assertEqual("Edit", component["facts"]["caseAccessLevel"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("reports-to", "Global_Sales"), references)

    def test_muting_permission_set_facts_only_no_grant_edges(self) -> None:
        path = self.base / "mutingpermissionsets/Ops_Mute.mutingpermissionset-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MutingPermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Ops Mute</label>"
            "<objectPermissions><object>HarnessEngagement__c</object>"
            "<allowDelete>true</allowDelete></objectPermissions>"
            "<fieldPermissions><field>HarnessEngagement__c.Margin__c</field>"
            "<readable>true</readable><editable>true</editable></fieldPermissions>"
            "<userPermissions><name>ModifyAllData</name><enabled>true</enabled></userPermissions>"
            "</MutingPermissionSet>\n",
        )
        component = self.builder.parse_muting_permission_set(path)
        facts = component["facts"]
        self.assertEqual({"HarnessEngagement__c": "D"}, facts["mutedObjectAccess"])
        self.assertEqual(["ModifyAllData"], facts["mutedSystemPermissions"])
        # Negative grants never enter the positive usage graph.
        self.assertEqual([], component["references"])

    def test_delegate_group_assignables(self) -> None:
        path = self.base / "delegateGroups/Regional_Admins.delegateGroup-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<DelegateGroup xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<label>Regional Admins</label><loginAccess>true</loginAccess>"
            "<roles>EMEA_Sales</roles>"
            "<permissionSets>HarnessEngagement_Manager</permissionSets>"
            "<profiles>Support Agent</profiles>"
            "</DelegateGroup>\n",
        )
        component = self.builder.parse_delegate_group(path)
        facts = component["facts"]
        self.assertTrue(facts["loginAccess"])
        self.assertEqual(["EMEA_Sales"], facts["administersRoles"])
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("grants-to-permission-set", "HarnessEngagement_Manager"), references)
        self.assertIn(("grants-to-profile", "Support Agent"), references)


class AuthCspEventChannelTests(unittest.TestCase):
    """Phase 24: identity providers, browser egress, event streaming."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "force-app/main/default"
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_auth_provider_hosts_and_handler_no_username(self) -> None:
        path = self.base / "authproviders/AzureAD.authprovider-meta.xml"
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<AuthProvider xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<friendlyName>Azure AD</friendlyName><providerType>OpenIdConnect</providerType>"
            "<authorizeUrl>https://login.microsoftonline.com/tenant-guid/authorize</authorizeUrl>"
            "<tokenUrl>https://login.microsoftonline.com/tenant-guid/token</tokenUrl>"
            "<consumerKey>never-export-consumer</consumerKey>"
            "<executionUser>integration@example.test</executionUser>"
            "<registrationHandler>AzureRegistrationHandler</registrationHandler>"
            "</AuthProvider>\n",
        )
        component = self.builder.parse_integration(path, "AuthProvider")
        facts = component["facts"]
        self.assertEqual("OpenIdConnect", facts["providerType"])
        self.assertEqual("login.microsoftonline.com", facts["authorizeHost"])
        self.assertTrue(facts["executionUserPresent"])
        serialized = canonical(component)
        self.assertNotIn("integration@example.test", serialized)
        self.assertNotIn("never-export-consumer", serialized)
        self.assertNotIn("tenant-guid", serialized)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("invokes-class", "AzureRegistrationHandler"), references)

    def test_csp_and_cors_host_facts(self) -> None:
        csp = self.base / "cspTrustedSites/Maps.cspTrustedSite-meta.xml"
        write(
            csp,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CspTrustedSite xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<endpointUrl>https://maps.example.test</endpointUrl><isActive>true</isActive>"
            "<context>LEX</context>"
            "<isApplicableToImgSrc>true</isApplicableToImgSrc>"
            "<isApplicableToConnectSrc>false</isApplicableToConnectSrc>"
            "</CspTrustedSite>\n",
        )
        component = self.builder.parse_integration(csp, "CspTrustedSite")
        facts = component["facts"]
        self.assertEqual("maps.example.test", facts["endpointHost"])
        self.assertEqual(["ImgSrc"], facts["directives"])
        cors = self.base / "corsWhitelistOrigins/Portal.corsWhitelistOrigin-meta.xml"
        write(
            cors,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CorsWhitelistOrigin xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<urlPattern>https://portal.example.test</urlPattern>"
            "</CorsWhitelistOrigin>\n",
        )
        component = self.builder.parse_integration(cors, "CorsWhitelistOrigin")
        self.assertEqual("portal.example.test", component["facts"]["endpointHost"])
        claims = self.builder.candidate_claims(component)
        self.assertIn("integration", [claim["claimType"] for claim in claims])

    def test_event_channel_member_cdc_base_object_heuristic(self) -> None:
        path = (
            self.base
            / "platformEventChannelMembers/Orders_AccountChangeEvent.platformEventChannelMember-meta.xml"
        )
        write(
            path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<PlatformEventChannelMember xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<eventChannel>Orders__chn</eventChannel>"
            "<selectedEntity>AccountChangeEvent</selectedEntity>"
            "<enrichedFields><name>Industry</name></enrichedFields>"
            "</PlatformEventChannelMember>\n",
        )
        component = self.builder.parse_platform_event_channel_member(path)
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("operates-on", "AccountChangeEvent"), references)
        self.assertIn(("operates-on", "Account"), references)
        self.assertIn(("relationship", "Orders__chn"), references)
        self.assertIn(("references-field", "AccountChangeEvent.Industry"), references)
        for reference in component["references"]:
            if reference["target"] == "Account":
                self.assertTrue(reference.get("heuristic"))


class CriteriaInfrastructureTests(unittest.TestCase):
    """Phase 2: sanitize_literal, shared criteria parsing, per-reference heuristic flag."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="force-app-knowledge-")
        self.root = Path(self.temporary.name)
        (self.root / "force-app/main/default").mkdir(parents=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sanitize_literal_keeps_plain_config_values(self) -> None:
        self.assertEqual("Active", sanitize_literal("Active"))
        self.assertEqual("EMEA — Tier 1", sanitize_literal("  EMEA — Tier 1 "))
        self.assertIsNone(sanitize_literal(None))
        self.assertIsNone(sanitize_literal("   "))

    def test_sanitize_literal_urls_collapse_to_host(self) -> None:
        self.assertEqual(
            "api.example.test", sanitize_literal("https://api.example.test/v1?tenant=42")
        )

    def test_sanitize_literal_drops_secrets_emails_ips(self) -> None:
        self.assertIsNone(sanitize_literal("password=hunter2"))
        self.assertIsNone(sanitize_literal("A" * 44))
        self.assertIsNone(sanitize_literal("ops@example.test"))
        self.assertIsNone(sanitize_literal("10.20.30.40"))

    def test_sanitize_literal_truncates_long_values(self) -> None:
        value = "word " * 60
        sanitized = sanitize_literal(value)
        self.assertIsNotNone(sanitized)
        self.assertLessEqual(len(sanitized), 200)
        self.assertTrue(sanitized.endswith("…"))

    def test_criteria_entries_flow_and_workflow_shapes(self) -> None:
        import xml.etree.ElementTree as ET

        flow_style = ET.fromstring(
            "<start>"
            "<filters><field>Status__c</field><operator>EqualTo</operator>"
            "<value><stringValue>Active</stringValue></value></filters>"
            "<filters><field>Owner__c</field><operator>EqualTo</operator>"
            "<value><elementReference>varOwner</elementReference></value></filters>"
            "</start>"
        )
        entries = ForceAppKnowledge._criteria_entries(flow_style)
        self.assertEqual(
            [
                {"field": "Status__c", "operator": "EqualTo", "value": "Active"},
                {"field": "Owner__c", "operator": "EqualTo", "elementReference": "varOwner"},
            ],
            entries,
        )
        rule_style = ET.fromstring(
            "<rule><criteriaItems><field>Case.Status</field><operation>equals</operation>"
            "<value>New</value></criteriaItems></rule>"
        )
        self.assertEqual(
            [{"field": "Case.Status", "operator": "equals", "value": "New"}],
            ForceAppKnowledge._criteria_entries(rule_style),
        )

    def test_relation_candidates_per_reference_heuristic(self) -> None:
        component = {
            "id": "Flow:Demo",
            "metadataType": "Flow",
            "name": "Demo",
            "path": "force-app/main/default/flows/Demo.flow-meta.xml",
            "references": [
                {"kind": "references-field", "target": "HarnessEngagement__c.Status__c"},
                {
                    "kind": "references-field",
                    "target": "HarnessEngagement__c.Guess__c",
                    "heuristic": True,
                },
            ],
        }
        first, second = self.builder.relation_candidates(component)
        self.assertEqual("observed", first["assurance"])
        self.assertFalse(first["assertion"]["value"]["heuristic"])
        self.assertEqual("inferred", second["assurance"])
        self.assertTrue(second["assertion"]["value"]["heuristic"])


if __name__ == "__main__":
    unittest.main()


class NestedSourceLayoutTests(unittest.TestCase):
    """Domain-grouped SFDX layouts must extract exactly like the flat one.

    Regression: directory-routed types (Apex, Visualforce, LWC/Aura, email templates) were
    globbed from a hard-coded `main/default/<folder>`, so a project grouping metadata per
    domain (`main/default/<domain>/classes/...`) silently produced `Cls`/`Trigger`/`Js`
    components with no references — the entire Apex usage registry came out empty. Found on
    real package metadata, not in synthetic fixtures.
    """

    def build(self, relative: str) -> dict:
        temporary = tempfile.TemporaryDirectory(prefix="nested-layout-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        classes = root / "force-app" / relative / "classes"
        classes.mkdir(parents=True)
        (classes / "OrderService.cls").write_text(
            "public with sharing class OrderService {\n"
            "    public void run() { List<Order__c> rows = [SELECT Id FROM Order__c]; update rows; }\n"
            "}\n",
            encoding="utf-8",
        )
        (classes / "OrderService.cls-meta.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<apiVersion>62.0</apiVersion><status>Active</status></ApexClass>\n",
            encoding="utf-8",
        )
        triggers = root / "force-app" / relative / "triggers"
        triggers.mkdir(parents=True)
        (triggers / "OrderTrigger.trigger").write_text(
            "trigger OrderTrigger on Order__c (before insert) {}\n", encoding="utf-8"
        )
        import subprocess

        for command in (
            ["git", "init", "-q"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=root, check=True, capture_output=True)
        for name in ("force-app-knowledge-inventory.schema.json",):
            (root / "schemas").mkdir(exist_ok=True)
            shutil.copy2(ROOT / "schemas" / name, root / "schemas" / name)
        components = {}
        for component in ForceAppKnowledge(root).inventory()["components"]:
            components.setdefault(component["metadataType"], []).append(component)
        return components

    def test_apexdoc_tags_and_emails_are_not_annotations(self) -> None:
        """Regression from real package source: the naive `@word` scan reported ApexDoc tags
        (`@description` x39) and an email domain as Apex annotations, drowning the 25 real
        ones. Only token-opening `@Name` outside comment lines counts."""
        temporary = tempfile.TemporaryDirectory(prefix="apex-annotations-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        classes = root / "force-app/main/default/classes"
        classes.mkdir(parents=True)
        (classes / "Documented.cls").write_text(
            "/**\n"
            " * @description Selector for Account, owned by someone@example.com\n"
            " * @param input the value\n"
            " * @return nothing\n"
            " */\n"
            "@IsTest\n"
            "public with sharing class Documented {\n"
            "    @TestVisible private static String note = 'contact us at team@example.com';\n"
            "}\n",
            encoding="utf-8",
        )
        component = ForceAppKnowledge(root).parse_apex(classes / "Documented.cls", "ApexClass")
        self.assertEqual(["IsTest", "TestVisible"], component["facts"]["annotations"])

    def test_flat_and_domain_grouped_layouts_extract_the_same_types(self) -> None:
        for layout in ("main/default", "main/default/billing"):
            with self.subTest(layout=layout):
                components = self.build(layout)
                self.assertIn("ApexClass", components)
                self.assertIn("ApexTrigger", components)
                self.assertNotIn("Cls", components)
                self.assertNotIn("Trigger", components)
                apex = components["ApexClass"][0]
                self.assertEqual("62.0", apex["facts"].get("apiVersion"))
                self.assertTrue(apex["references"], "nested Apex must still yield usage references")
