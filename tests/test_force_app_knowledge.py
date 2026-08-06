from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
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


def lookup_field(name: str, target: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<fullName>{name}</fullName><label>{name}</label><type>Lookup</type>"
        f"<referenceTo>{target}</referenceTo><relationshipName>{name}Rel</relationshipName>"
        "</CustomField>\n"
    )


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
        # Generic-bucket component: the durable unprofiled probe (label/rootElement only —
        # no entry profile by design, unlike the waved types that gain profiles over time).
        write(
            self.root / "force-app/main/default/letterhead/HarnessBrand.letterhead-meta.xml",
            """<Letterhead xmlns="http://soap.sforce.com/2006/04/metadata"><name>HarnessBrand</name></Letterhead>""",
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
            "force-app-knowledge-inventory.schema.json",
            "force-app-knowledge-resolve.schema.json",
        ):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "config").mkdir()
        shutil.copy2(
            ROOT / "config/knowledge-policy.json",
            self.root / "config/knowledge-policy.json",
        )
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        self.builder = ForceAppKnowledge(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

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

    def test_f5_entry_readiness_reports_the_entry_side_denominator(self) -> None:
        self.builder.inventory()
        entries = {
            "CustomObject:HarnessEngagement__c": {"purpose": "Real.", "lane": "approved-current"}
        }
        with unittest.mock.patch.object(
            ForceAppKnowledge, "entry_descriptions", lambda self: entries
        ):
            result = self.builder.entry_readiness()
        self.assertEqual("force-app-entry-readiness", result["kind"])
        bucket = result["byMetadataType"]["CustomObject"]
        self.assertGreaterEqual(bucket["components"], 1)
        self.assertEqual(1, bucket["byLane"]["approved-current"])
        self.assertGreaterEqual(result["totals"]["noEntry"], 1)
        # The basis must name its denominator and the companion surface, or one report gets
        # mistaken for another.
        self.assertIn("live entry-profiled force-app components", result["basis"])
        self.assertIn("entry-edge-health", result["basis"])

    def test_entry_readiness_separates_undescribed_from_missing(self) -> None:
        # KM-16D 2026-08-06: a 527-draft store answered `documentNext: 0` and the agent read
        # it as "nothing awaits description". The two debts have different remedies and must
        # never collapse into one number: no entry -> entry-draft, sentinel -> entry-describe.
        self.builder.inventory()
        entries = {
            "CustomObject:HarnessEngagement__c": {"purpose": "", "lane": "draft"},
        }
        with unittest.mock.patch.object(
            ForceAppKnowledge, "entry_descriptions", lambda self: entries
        ):
            result = self.builder.entry_readiness()
        bucket = result["byMetadataType"]["CustomObject"]
        self.assertEqual(1, bucket["undescribed"])
        self.assertEqual(1, result["totals"]["undescribed"])
        self.assertIn(
            {"componentId": "CustomObject:HarnessEngagement__c", "metadataType": "CustomObject"},
            result["describeNext"],
        )
        # The undescribed draft has an entry, so it must NOT appear in documentNext…
        self.assertNotIn(
            "CustomObject:HarnessEngagement__c",
            {row["componentId"] for row in result["documentNext"]},
        )
        # …and a described entry contributes to neither worklist.
        described = {
            "CustomObject:HarnessEngagement__c": {"purpose": "Real.", "lane": "draft"},
        }
        with unittest.mock.patch.object(
            ForceAppKnowledge, "entry_descriptions", lambda self: described
        ):
            result = self.builder.entry_readiness()
        self.assertEqual(0, result["totals"]["undescribed"])
        self.assertEqual([], result["describeNext"])
        # The basis must teach the remedy split by name.
        self.assertIn("describeNext", result["basis"])
        self.assertIn("entry-describe", result["basis"])

    def test_resolve_maps_paths_and_names_onto_components(self) -> None:
        self.builder.inventory()
        result = self.builder.resolve(
            paths=[
                "force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml",
                "force-app\\main\\default\\triggers\\HarnessEngagementTrigger.trigger",
                str(self.root / "force-app/main/default/lwc/harnessEngagementCard/harnessEngagementCard.js"),
                "force-app/main/default/objects/HarnessEngagement__c",
                "not-force-app/readme.md",
            ],
            names=["HarnessBilling", "HarnessBrand", "Account__c.field-meta.xml", "NoSuchComponent"],
        )
        by_input = {selection["input"]: selection for selection in result["selections"]}

        field = by_input["force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml"]
        self.assertEqual("resolved", field["resolution"])
        self.assertEqual(["CustomField:HarnessEngagement__c.Account__c"], field["componentIds"])

        # Windows separators normalize; the pinned path still resolves exactly.
        trigger = by_input["force-app\\main\\default\\triggers\\HarnessEngagementTrigger.trigger"]
        self.assertEqual("resolved", trigger["resolution"])
        self.assertEqual(["ApexTrigger:HarnessEngagementTrigger"], trigger["componentIds"])

        # A file inside an LWC bundle resolves to the bundle component, and an absolute path
        # resolves through its force-app segment.
        member = by_input[str(self.root / "force-app/main/default/lwc/harnessEngagementCard/harnessEngagementCard.js")]
        self.assertEqual("resolved", member["resolution"])
        self.assertEqual(["LightningComponentBundle:harnessEngagementCard"], member["componentIds"])

        directory = by_input["force-app/main/default/objects/HarnessEngagement__c"]
        self.assertEqual("expanded", directory["resolution"])
        self.assertEqual(
            ["CustomField:HarnessEngagement__c.Account__c", "CustomObject:HarnessEngagement__c"],
            directory["componentIds"],
        )

        outside = by_input["not-force-app/readme.md"]
        self.assertEqual("unsupported", outside["resolution"])

        credential = by_input["HarnessBilling"]
        self.assertEqual("resolved", credential["resolution"])
        self.assertEqual(["NamedCredential:HarnessBilling"], credential["componentIds"])

        letterhead = by_input["HarnessBrand"]
        self.assertEqual("resolved", letterhead["resolution"])
        self.assertEqual(["Letterhead:HarnessBrand"], letterhead["componentIds"])

        basename = by_input["Account__c.field-meta.xml"]
        self.assertEqual("resolved", basename["resolution"])

        unmatched = by_input["NoSuchComponent"]
        self.assertEqual("unmatched", unmatched["resolution"])
        self.assertIn("suggestions", unmatched)

        items = {item["componentId"]: item for item in result["components"]}
        self.assertFalse(result["entryHomeActive"])
        # Entry-profiled types route to the entry lane even before the first entry exists.
        self.assertEqual("entry", items["CustomField:HarnessEngagement__c.Account__c"]["lane"])
        self.assertEqual("no-entry", items["CustomField:HarnessEngagement__c.Account__c"]["status"])
        # Wave 2 profiled the integration family: NamedCredential now routes to the entry lane.
        self.assertEqual("entry", items["NamedCredential:HarnessBilling"]["lane"])
        self.assertEqual("no-entry", items["NamedCredential:HarnessBilling"]["status"])
        # A type without an entry profile has NO Knowledge lane since the claim registry
        # retired; the gap is reported, never a pseudo-status. The probe is a generic-bucket
        # type (Letterhead) that stays unprofiled by design, not by backlog.
        self.assertEqual("none", items["Letterhead:HarnessBrand"]["lane"])
        self.assertEqual("no-entry-profile", items["Letterhead:HarnessBrand"]["status"])
        self.assertIn("knowledge_store.PROFILES", items["Letterhead:HarnessBrand"]["reason"])

    def test_resolve_reports_ambiguity_and_never_guesses(self) -> None:
        write(
            self.root / "force-app/main/default/classes/HarnessBilling.cls",
            "public with sharing class HarnessBilling {}\n",
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "ambiguity fixture"], cwd=self.root, check=True)
        self.builder.inventory()
        result = self.builder.resolve(
            paths=[
                "force-app/main/default/classes/HarnessBilling.cls-meta.xml",
                "force-app//main/default/Triggers/HarnessEngagementTrigger.trigger",
            ],
            names=["HarnessBilling", "HarnessEngagementTrigger"],
        )
        by_input = {selection["input"]: selection for selection in result["selections"]}
        ambiguous = by_input["HarnessBilling"]
        self.assertEqual("ambiguous", ambiguous["resolution"])
        self.assertEqual(
            ["ApexClass:HarnessBilling", "NamedCredential:HarnessBilling"],
            ambiguous["candidates"],
        )
        # A component matching through two of its own aliases is not an ambiguity.
        self.assertEqual("resolved", by_input["HarnessEngagementTrigger"]["resolution"])
        # A pinned companion meta file resolves to its content-file component.
        companion = by_input["force-app/main/default/classes/HarnessBilling.cls-meta.xml"]
        self.assertEqual("resolved", companion["resolution"])
        self.assertEqual(["ApexClass:HarnessBilling"], companion["componentIds"])
        # Doubled separators and a wrong-case segment still match: the team's filesystems are
        # case-insensitive, so the path the developer pinned genuinely names this file.
        sloppy = by_input["force-app//main/default/Triggers/HarnessEngagementTrigger.trigger"]
        self.assertEqual("resolved", sloppy["resolution"])
        self.assertEqual(["ApexTrigger:HarnessEngagementTrigger"], sloppy["componentIds"])

    def test_resolve_expands_multi_component_files_and_companion_content(self) -> None:
        labels = "".join(
            f"<labels><fullName>Harness_{name}</fullName><value>{name}</value></labels>"
            for name in ("Alpha", "Beta")
        )
        write(
            self.root / "force-app/main/default/labels/HarnessLabels.labels-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<CustomLabels xmlns="http://soap.sforce.com/2006/04/metadata">{labels}</CustomLabels>\n',
        )
        write(self.root / "force-app/main/default/staticresources/HarnessLogo.resource", "PNGBYTES")
        write(
            self.root / "force-app/main/default/staticresources/HarnessLogo.resource-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<StaticResource xmlns="http://soap.sforce.com/2006/04/metadata">'
            "<contentType>image/png</contentType><cacheControl>Public</cacheControl></StaticResource>\n",
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "multi-component fixture"], cwd=self.root, check=True)
        self.builder.inventory()
        result = self.builder.resolve(
            paths=[
                "force-app/main/default/labels/HarnessLabels.labels-meta.xml",
                "force-app/main/default/staticresources/HarnessLogo.resource",
            ],
            names=["HarnessLabels.labels-meta.xml"],
        )
        by_input = {selection["input"]: selection for selection in result["selections"]}
        # A file defining several components expands to ALL of them — nothing silently drops.
        expanded = by_input["force-app/main/default/labels/HarnessLabels.labels-meta.xml"]
        self.assertEqual("expanded", expanded["resolution"])
        self.assertEqual(
            ["CustomLabel:Harness_Alpha", "CustomLabel:Harness_Beta", "CustomLabels:HarnessLabels"],
            expanded["componentIds"],
        )
        # The same file mentioned by basename expands identically instead of ambiguating.
        by_name = by_input["HarnessLabels.labels-meta.xml"]
        self.assertEqual("expanded", by_name["resolution"])
        self.assertEqual(expanded["componentIds"], by_name["componentIds"])
        # A pinned content file resolves through its companion meta component.
        content = by_input["force-app/main/default/staticresources/HarnessLogo.resource"]
        self.assertEqual("resolved", content["resolution"])
        self.assertEqual(["StaticResource:HarnessLogo"], content["componentIds"])

    def test_resolve_refuses_expansions_beyond_one_approval_chunk(self) -> None:
        labels = "".join(
            f"<labels><fullName>Harness_L{i:02d}</fullName><value>v{i}</value></labels>"
            for i in range(30)
        )
        write(
            self.root / "force-app/main/default/labels/HarnessBig.labels-meta.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<CustomLabels xmlns="http://soap.sforce.com/2006/04/metadata">{labels}</CustomLabels>\n',
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "big labels fixture"], cwd=self.root, check=True)
        self.builder.inventory()
        result = self.builder.resolve(
            paths=["force-app/main/default/labels/HarnessBig.labels-meta.xml"], names=[]
        )
        refused = result["selections"][0]
        self.assertEqual("unsupported", refused["resolution"])
        self.assertIn("expands to 31 components", refused["reason"])
        self.assertIn("split it per metadata type", refused["reason"])
        # The refused expansion computes no statuses and reports no components.
        self.assertEqual([], result["components"])

    def test_resolve_requires_inputs_and_bounds_them(self) -> None:
        self.builder.inventory()
        with self.assertRaisesRegex(KnowledgeBuildError, "at least one"):
            self.builder.resolve(paths=[], names=[])
        with self.assertRaisesRegex(KnowledgeBuildError, "at most 50"):
            self.builder.resolve(paths=[], names=[f"Name{i}" for i in range(51)])
        with self.assertRaisesRegex(KnowledgeBuildError, "rerun inventory"):
            write(self.root / "force-app/main/default/classes/Drift.cls", "public class Drift {}\n")
            self.builder.resolve(paths=[], names=["HarnessBilling"])

    def test_resolve_write_persists_schema_valid_derived_view(self) -> None:
        self.builder.inventory()
        result = self.builder.resolve(paths=[], names=["HarnessBilling"], write=True)
        path = self.root / result["path"]
        self.assertTrue(path.is_file())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("force-app-knowledge-resolve", saved["kind"])
        self.assertNotIn("path", saved)

    def test_selected_files_guard_bounds_resolve(self) -> None:
        from scripts import copilot_role_guard as role_guard

        for role in ("config-investigator", "knowledge-curator"):
            with self.subTest(role=role):
                self.assertTrue(
                    role_guard.force_app_knowledge_command_allowed(
                        ["resolve", "--path", "force-app/main/default/classes/Foo.cls",
                         "--name", "Foo", "--write"],
                        role,
                    )
                )
        # Read-only, but never for roles without extraction authority.
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["resolve", "--path", "force-app/x"], "development-assistant"
            )
        )
        investigator = "config-investigator"
        # An input is required; a bare --write carries none.
        self.assertFalse(role_guard.force_app_knowledge_command_allowed(["resolve"], investigator))
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(["resolve", "--write"], investigator)
        )
        # No force-app segment, or traversal — rejected regardless of shape.
        for bad_path in ("/etc/passwd", "force-app/../secrets"):
            with self.subTest(path=bad_path):
                self.assertFalse(
                    role_guard.force_app_knowledge_command_allowed(
                        ["resolve", "--path", bad_path], investigator
                    )
                )
        self.assertFalse(
            role_guard.force_app_knowledge_command_allowed(
                ["resolve", "--unknown", "x"], investigator
            )
        )
        # The inputs a real developer pastes must pass: absolute Windows paths (the resolver
        # keeps everything from the force-app segment down), layout paths and fullNames with
        # spaces, component ids with colons, and the = flag form.
        for good in (
            ["resolve", "--path", "C:\\repo\\force-app\\main\\default\\triggers\\X.trigger"],
            ["resolve", "--path",
             "force-app/main/default/layouts/Account-Account Layout.layout-meta.xml"],
            ["resolve", "--name", "Account-Account Layout"],
            ["resolve", "--name", "Layout:Account-Account Layout"],
            ["resolve", "--path=force-app/main/default/classes/Foo.cls", "--name=Foo"],
        ):
            with self.subTest(command=good):
                self.assertTrue(
                    role_guard.force_app_knowledge_command_allowed(good, investigator)
                )
    def test_changed_source_invalidates_the_cached_inventory(self) -> None:
        self.builder.inventory()
        field = self.root / "force-app/main/default/objects/HarnessEngagement__c/fields/Account__c.field-meta.xml"
        field.write_text(FIELD_XML.replace("Account</label>", "Client Account</label>"), encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeBuildError, "changed after inventory"):
            self.builder.resolve(paths=[], names=["HarnessBilling"])

        inventory = self.builder.inventory()
        self.assertFalse(inventory["workspaceStatus"]["clean"])


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

    def test_constructed_classes_are_invoked_classes(self) -> None:
        """`new X().run()` is the standard trigger-handler idiom and matched nothing.

        The call regex needs an identifier immediately followed by `.`, so a constructor call
        was invisible. That broke the first hop of every execution chain: traversing outward
        from a trigger reached the object it operates on and stopped, leaving "how does this
        work?" unanswerable for the most common shape in a Salesforce package."""

        source = (
            "trigger HarnessAlphaTrigger on HarnessAlphaCase__c(before insert) {\n"
            "    new HarnessAlphaHandler().run();\n"
            "}\n"
        )
        component = self.parse_source("HarnessAlphaTrigger", source, "ApexTrigger")
        references = {(ref["kind"], ref["target"]) for ref in component["references"]}
        self.assertIn(("invokes-class", "HarnessAlphaHandler"), references)
        self.assertIn(("belongs-to", "HarnessAlphaCase__c"), references)

    def test_construction_still_excludes_platform_types(self) -> None:
        source = (
            "public class HarnessAlphaHandler {\n"
            "    public void run() {\n"
            "        Map<Id, String> seen = new Map<Id, String>();\n"
            "        HarnessAlphaQueueable job = new HarnessAlphaQueueable();\n"
            "    }\n"
            "}\n"
        )
        component = self.parse_source("HarnessAlphaHandler", source)
        invoked = {ref["target"] for ref in component["references"] if ref["kind"] == "invokes-class"}
        self.assertIn("HarnessAlphaQueueable", invoked)
        self.assertNotIn("Map", invoked)

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
        self.assertEqual("Your case was escalated", component["facts"]["subject"])

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

    def test_declarations_are_not_read_out_of_comments(self) -> None:
        """Regression from real package source: a header comment reading "Base class for all
        trigger handlers" made CLASS_RE name the class `for`. Two real classes then shared one
        identity and one silently overwrote the other in the entry store."""
        temporary = tempfile.TemporaryDirectory(prefix="apex-comment-names-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        classes = root / "force-app/main/default/classes"
        classes.mkdir(parents=True)
        (classes / "TriggerHandler.cls").write_text(
            "/**\n"
            " * @description Base class for all trigger handlers in the package.\n"
            " * One trigger per object dispatches to a single subclass of this handler.\n"
            " */\n"
            "public virtual class TriggerHandler {\n}\n",
            encoding="utf-8",
        )
        triggers = root / "force-app/main/default/triggers"
        triggers.mkdir(parents=True)
        (triggers / "OrderTrigger.trigger").write_text(
            "// This trigger on legacy notes used to be handled elsewhere\n"
            "trigger OrderTrigger on Order__c (before insert) {}\n",
            encoding="utf-8",
        )
        builder = ForceAppKnowledge(root)
        klass = builder.parse_apex(classes / "TriggerHandler.cls", "ApexClass")
        trigger = builder.parse_apex(triggers / "OrderTrigger.trigger", "ApexTrigger")
        self.assertEqual("ApexClass:TriggerHandler", klass["id"])
        self.assertEqual("ApexTrigger:OrderTrigger", trigger["id"])

    def test_prose_is_never_mistaken_for_code(self) -> None:
        """Regression from real package source: comments and assertion strings were scanned as
        code. `FROM the ledger` in a comment produced an object named `the`, and
        'name defaulted from account' in a test assertion produced `account`."""
        temporary = tempfile.TemporaryDirectory(prefix="apex-prose-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        classes = root / "force-app/main/default/classes"
        classes.mkdir(parents=True)
        (classes / "LedgerService.cls").write_text(
            "/**\n"
            " * @description Reads entries selected from the ledger for a client.\n"
            " */\n"
            "public with sharing class LedgerService {\n"
            "    public void run() {\n"
            "        List<Invoice__c> rows = [SELECT Id FROM Invoice__c];\n"
            "        String dynamic = 'SELECT Id FROM BillingEvent__c';\n"
            "        System.assertEquals('x', 'y', 'name defaulted from account');\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        facts = ForceAppKnowledge(root).parse_apex(classes / "LedgerService.cls", "ApexClass")["facts"]
        objects = set(facts.get("soqlObjects") or [])
        self.assertIn("Invoice__c", objects)
        self.assertIn("BillingEvent__c", objects, "dynamic SOQL in a string literal must survive")
        self.assertNotIn("the", objects, "comment prose must not become an object")
        self.assertNotIn("account", objects, "assertion-message prose must not become an object")

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


ENTRY_EDGE_APEX_SOURCE = """public with sharing class HarnessEngagementService {
    public void link(Id engagementId) {
        HarnessEngagement__c engagement = [SELECT Id, Invoice__c FROM HarnessEngagement__c];
        engagement.Invoice__c = null;
        update engagement;
    }
}
"""


class EntryEdgeHealthTests(unittest.TestCase):
    """`relation-health` must report entry-side orphans, not just count lanes.

    The completion audit proved the orphan half absent by AST — `entry_edge_health` never
    referenced its own `live_component_ids` parameter — and by execution: deleting an entire
    referenced CustomObject from live source still reported `findingCount: 0`. These tests are
    that reproduction, so a regression cannot pass them by counting lanes alone.
    """

    def setUp(self) -> None:
        import argparse

        import scripts.knowledge_store as store

        self.store = store
        self.argparse = argparse
        temporary = tempfile.TemporaryDirectory(prefix="entry-edge-health-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        base = self.root / "force-app/main/default"
        write(base / "objects/HarnessEngagement__c/HarnessEngagement__c.object-meta.xml", OBJECT_XML)
        # Two lookups from the same object: one to a package-local target that a deletion can
        # settle, one to the standard `Account` that live source can never settle.
        write(
            base / "objects/HarnessEngagement__c/fields/Invoice__c.field-meta.xml",
            lookup_field("Invoice__c", "HarnessInvoice__c"),
        )
        write(
            base / "objects/HarnessEngagement__c/fields/Account__c.field-meta.xml",
            lookup_field("Account__c", "Account"),
        )
        write(base / "objects/HarnessInvoice__c/HarnessInvoice__c.object-meta.xml", OBJECT_XML)
        # An Apex class carries the case the four original tests could not see: its extractors
        # emit BARE `__c` tokens (`Invoice__c`), while a live field is only ever indexed under
        # `Object.Field`. Every one of the 164 false orphans on the reference corpus had this
        # shape, so the fixture has to contain it or the diff is only ever tested on the shape
        # that already worked.
        write(base / "classes/HarnessEngagementService.cls", ENTRY_EDGE_APEX_SOURCE)
        (self.root / "schemas").mkdir()
        for name in (
            "force-app-knowledge-inventory.schema.json",
            "knowledge-entry.schema.json",
            "knowledge-profile-customfield.schema.json",
        ):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "config").mkdir()
        shutil.copy2(ROOT / "config/knowledge-policy.json", self.root / "config/knowledge-policy.json")
        (self.root / "config/harness.local.json").write_text(
            json.dumps({"knowledge": {"chatReviewer": "Reviewer Person"}}), encoding="utf-8"
        )
        (self.root / ".ai/knowledge").mkdir(parents=True)
        self.purpose = self.root / "purpose.md"
        self.purpose.write_text("Links an engagement to its invoice.", encoding="utf-8")
        self.commit("fixture")
        self.builder = ForceAppKnowledge(self.root)
        self.builder.inventory()

    def commit(self, message: str) -> None:
        for command in (
            ["git", "init", "-q"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message],
        ):
            subprocess.run(command, cwd=self.root, check=True, capture_output=True)

    def approved_entry(self, full_name: str, metadata_type: str = "CustomField") -> str:
        """Draft and approve one entry through the governed store commands."""

        with self.store.rooted(self.root):
            drafted = self.store.command_entry_draft(
                self.argparse.Namespace(
                    metadata_type=metadata_type,
                    full_name=full_name,
                    namespace=None,
                    purpose_file=str(self.purpose),
                    source_api_version="64.0",
                    candidate_keyword=None,
                )
            )
            self.store.command_entry_approve(
                self.argparse.Namespace(
                    entry=[f"{drafted['identity']}:{drafted['reviewedContentDigest']}"]
                )
            )
        return drafted["identity"]

    def drop_invoice_object(self) -> None:
        shutil.rmtree(self.root / "force-app/main/default/objects/HarnessInvoice__c")
        self.commit("delete HarnessInvoice__c")
        self.builder.inventory()  # the health report refuses a stale inventory

    def test_deleted_edge_target_is_reported_as_an_orphan(self) -> None:
        self.approved_entry("HarnessEngagement__c.Invoice__c")
        healthy = self.builder.entry_edge_report()
        self.assertEqual({"approved-current": 1}, healthy["entriesByLane"])
        self.assertEqual(0, healthy["findingCount"], healthy["findings"])

        self.drop_invoice_object()
        report = self.builder.entry_edge_report()
        # The audit's own reproduction: the lane count is unchanged, so a check that only
        # counted lanes would still say HEALTHY here.
        self.assertEqual({"approved-current": 1}, report["entriesByLane"])
        self.assertEqual(1, report["findingCount"], report["findings"])
        finding = report["findings"][0]
        self.assertEqual("CustomField:c:HarnessEngagement__c.Invoice__c", finding["identity"])
        self.assertEqual("approved-current", finding["lifecycleState"])
        self.assertEqual("relationship", finding["kind"])
        self.assertEqual("HarnessInvoice__c", finding["target"])
        self.assertEqual("HarnessInvoice__c", finding["missingComponent"])
        # Same two reason strings as the claim-side orphan list, so the report has one dialect.
        self.assertEqual("edge no longer present in source", finding["reason"])
        self.assertIn(
            finding["reason"],
            {"component removed", "edge no longer present in source"},
        )

    def test_targets_source_cannot_settle_are_never_called_orphans(self) -> None:
        # `Account` is absent from force-app by nature. Reporting it would make the orphan
        # list unreadable — every lookup to a standard object would be permanent rot.
        self.approved_entry("HarnessEngagement__c.Account__c")
        entry = self.root / ".ai/knowledge/artifacts/objects/c/HarnessEngagement__c/fields/Account__c.md"
        # The edge is really stored — silence here is a decision, not an empty graph.
        self.assertIn("target: Account\n", entry.read_text(encoding="utf-8"))
        report = self.builder.entry_edge_report()
        self.assertEqual(0, report["findingCount"], report["findings"])

    def test_removed_subject_component_is_reported_before_its_edges(self) -> None:
        self.approved_entry("HarnessEngagement__c.Invoice__c")
        shutil.rmtree(self.root / "force-app/main/default/objects/HarnessEngagement__c/fields")
        self.commit("delete the described fields")
        self.builder.inventory()
        report = self.builder.entry_edge_report()
        reasons = {finding["reason"] for finding in report["findings"]}
        self.assertIn("component removed", reasons)
        # An entry whose own subject is gone is one finding, not one per stale edge.
        self.assertNotIn("edge no longer present in source", reasons)

    def test_a_bare_field_name_behind_a_heuristic_edge_is_not_an_orphan(self) -> None:
        """The 164-false-positive defect, in one entry.

        `object-token` emits the token the regex found — `Invoice__c`, with no owner — while the
        live field is `HarnessEngagement__c.Invoice__c`. Diffed against the full names alone the
        bare token matches nothing and every field an Apex class touches is reported removed
        while its file sits in source. The four tests this class shipped with used `Object.Field`
        targets exclusively, which is exactly why none of them saw it.
        """

        identity = self.approved_entry("HarnessEngagementService", "ApexClass")
        entry = self.root / ".ai/knowledge/artifacts/code/ApexClass/c/HarnessEngagementService.md"
        body = entry.read_text(encoding="utf-8")
        self.assertIn("target: Invoice__c\n", body, "fixture must store the bare-name edge")
        self.assertIn("kind: object-token", body)

        report = self.builder.entry_edge_report()
        self.assertEqual(0, report["findingCount"], report["findings"])
        self.assertNotIn(identity, {finding.get("identity") for finding in report["findings"]})
        # Present, not merely unreported: the name was settled against the live field index.
        self.assertIn("0 approved-entry edge targets were left undecidable", report["note"])

    def test_a_clean_fully_approved_corpus_reports_no_orphans(self) -> None:
        """Nothing deleted, every draftable component approved: the orphan count is zero.

        This is the audit's reproduction at fixture scale, and it counts the STORE's set of
        draftable types rather than a list assembled here — a gate that counts its own list can
        be green and mean nothing. On the 189-component reference package the same measurement
        read 164 before this fix and 0 after.
        """

        inventory = self.builder.load_inventory()
        draftable = self.builder.entry_draftable_types()
        components = [
            component
            for component in inventory["components"]
            if component["metadataType"] in draftable
        ]
        self.assertGreater(len(components), 3, "fixture must span more than one metadata type")
        for component in components:
            self.approved_entry(component["name"], component["metadataType"])

        report = self.builder.entry_edge_report()
        self.assertEqual({"approved-current": len(components)}, report["entriesByLane"])
        self.assertEqual(0, report["findingCount"], report["findings"])
        self.assertIn("0 approved-entry edge targets were left undecidable", report["note"])

    def test_an_undecidable_target_is_disclosed_rather_than_claimed(self) -> None:
        """A bare heuristic token that matches nothing settles nothing, and says so.

        One deletion reaches the same entry down two edges. `var-field-ref` wrote the owner into
        its target (`HarnessEngagement__c.Invoice__c`), so that one is settled and reported.
        `object-token` wrote the bare token, which after the deletion could be that field, a
        field on any other object, or a name the regex read out of a string literal — so it is
        disclosed as a population instead of being claimed (a false positive) or dropped (a
        false negative, which is what made the lane count mean nothing).
        """

        self.approved_entry("HarnessEngagementService", "ApexClass")
        (self.root / "force-app/main/default/objects/HarnessEngagement__c/fields/Invoice__c.field-meta.xml").unlink()
        self.commit("delete the Invoice__c field")
        self.builder.inventory()

        report = self.builder.entry_edge_report()
        self.assertEqual(1, report["findingCount"], report["findings"])
        self.assertEqual("var-field-ref", report["findings"][0]["kind"])
        self.assertEqual(
            "HarnessEngagement__c.Invoice__c", report["findings"][0]["missingComponent"]
        )
        self.assertIn(
            "1 approved-entry edge target(s) across 1 name(s) are UNDECIDABLE", report["note"]
        )
        self.assertIn("Names: Invoice__c.", report["note"])

    def test_a_declared_edge_target_is_still_decidable_when_a_field_shares_its_name(self) -> None:
        """The live-field index must not swallow a genuine orphan.

        A lookup's `relationship` target is an object because its kind says so, so a same-named
        field elsewhere cannot stand in for it — otherwise the fix for the false positives would
        have bought silence on the true ones.
        """

        base = self.root / "force-app/main/default"
        write(
            base / "objects/HarnessEngagement__c/fields/HarnessInvoice__c.field-meta.xml",
            lookup_field("HarnessInvoice__c", "Account"),
        )
        self.commit("add a field named after the invoice object")
        self.builder.inventory()
        self.approved_entry("HarnessEngagement__c.Invoice__c")
        self.drop_invoice_object()

        report = self.builder.entry_edge_report()
        findings = [
            finding for finding in report["findings"] if finding.get("kind") == "relationship"
        ]
        self.assertEqual(1, len(findings), report["findings"])
        self.assertEqual("HarnessInvoice__c", findings[0]["missingComponent"])
        self.assertEqual("source-exact", findings[0]["assurance"])

    def test_lane_is_computed_so_an_unledgered_entry_is_never_diffed(self) -> None:
        # Contract §4: reading `lifecycle.state` out of frontmatter never establishes approval.
        # A file that says `approved` with no ledger record is quarantined, and its edges are
        # not worth diffing — the entry itself is not trusted.
        self.approved_entry("HarnessEngagement__c.Invoice__c")
        (self.root / ".ai/knowledge/artifacts-ledger.jsonl").write_text("", encoding="utf-8")
        self.drop_invoice_object()
        report = self.builder.entry_edge_report()
        self.assertEqual({"not-effective": 1}, report["entriesByLane"])
        reasons = {finding["reason"] for finding in report["findings"]}
        self.assertIn("approved state without any ledger record (quarantined)", reasons)
        self.assertNotIn("edge no longer present in source", reasons)


class ModuleStructureTests(unittest.TestCase):
    def test_no_class_defines_the_same_method_twice(self) -> None:
        """A redefined method is a silent deletion of the first one.

        A second `entry_home_types` added for the dossier shadowed the gated one `draft()`
        calls, so drafting skipped every entry-profiled component in a repo with zero entries
        — every repo today — and `feature-draft` returned an empty manifest. Nothing failed;
        the manifest was simply empty. Python will not warn, so this does.
        """

        import ast

        source = (ROOT / "scripts/force_app_knowledge.py").read_text(encoding="utf-8")
        duplicates = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ClassDef):
                continue
            seen: set[str] = set()
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name in seen:
                    duplicates.append(f"{node.name}.{item.name} (line {item.lineno})")
                seen.add(item.name)
        self.assertEqual([], duplicates)


class CollectorVersionTests(unittest.TestCase):
    def test_collector_version_is_past_the_belongs_to_expansion(self) -> None:
        """The one number that lets a future auditor date a factsDigest move.

        P1 added the `belongs-to` emitters and the Apex `new` detector, so entries extracted
        before and after it are not interchangeable. 1.6.0 could not tell them apart.
        """

        from scripts.force_app_knowledge import COLLECTOR_VERSION

        version = tuple(int(part) for part in COLLECTOR_VERSION.split("."))
        self.assertGreaterEqual(version, (1, 7, 0), COLLECTOR_VERSION)
