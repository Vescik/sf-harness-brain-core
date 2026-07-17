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
    stable_id,
)


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
        # The trigger's usage registry (operates on Engagement__c) seeds an advisory candidate term.
        trigger = next(
            claim
            for claim in claims
            if claim["claimType"] == "automation-inventory"
            and claim["subject"]["identity"] == "EngagementTrigger"
        )
        self.assertIn("engagement", trigger["candidateKeywords"])

    def test_flow_usage_registry_records_objects_and_fields(self) -> None:
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <label>Engagement Router</label><status>Active</status><processType>AutoLaunchedFlow</processType>
  <start><object>Engagement__c</object><triggerType>RecordAfterSave</triggerType><recordTriggerType>Create</recordTriggerType></start>
  <recordLookups><name>GetAccount</name><object>Account</object><queriedFields>Name</queriedFields></recordLookups>
  <recordUpdates><name>SetStatus</name><object>Engagement__c</object>
    <inputAssignments><field>Status__c</field></inputAssignments></recordUpdates>
  <actionCalls><name>Notify</name><actionType>apex</actionType><actionName>EngagementNotifier</actionName></actionCalls>
  <decisions><name>IsActive</name></decisions>
</Flow>
"""
        write(
            self.root / "force-app/main/default/flows/EngagementRouter.flow-meta.xml",
            flow_xml,
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "flow"], cwd=self.root, check=True)
        inventory = self.builder.inventory()
        flow = next(c for c in inventory["components"] if c["metadataType"] == "Flow")
        facts = flow["facts"]
        self.assertEqual(["Account", "Engagement__c"], facts["referencedObjects"])
        self.assertEqual(1, facts["elementCounts"]["decisions"])
        references = {(ref["kind"], ref["target"]) for ref in flow["references"]}
        self.assertIn(("reads-field", "Account.Name"), references)
        self.assertIn(("writes-field", "Engagement__c.Status__c"), references)
        self.assertIn(("invokes-apex", "EngagementNotifier"), references)

    def test_validation_rule_and_layout_get_dedicated_parsers(self) -> None:
        write(
            self.root
            / "force-app/main/default/objects/Engagement__c/validationRules/Status_Required.validationRule-meta.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
  <fullName>Status_Required</fullName><active>true</active>
  <errorConditionFormula>ISBLANK(Status__c)</errorConditionFormula>
  <errorMessage>Status is required</errorMessage><errorDisplayField>Status__c</errorDisplayField>
</ValidationRule>
""",
        )
        write(
            self.root / "force-app/main/default/layouts/Engagement__c-Engagement Layout.layout-meta.xml",
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
        self.assertEqual("Engagement__c", vr["facts"]["object"])
        self.assertTrue(vr["facts"]["errorMessagePresent"])
        self.assertIn(
            ("references-field", "Engagement__c.Status__c"),
            {(ref["kind"], ref["target"]) for ref in vr["references"]},
        )
        layout = by_type["Layout"]
        self.assertEqual("Engagement__c", layout["facts"]["object"])
        self.assertIn(
            ("places-field", "Engagement__c.Status__c"),
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
