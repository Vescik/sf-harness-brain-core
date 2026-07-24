from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import knowledge_store as store

FLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Harness Alpha Router</label>
    <processType>AutoLaunchedFlow</processType>
    <status>Active</status>
    <start>
        <object>HarnessAlphaCase__c</object>
        <triggerType>RecordAfterSave</triggerType>
        <recordTriggerType>Update</recordTriggerType>
    </start>
    <variables>
        <name>caseRecord</name>
        <dataType>SObject</dataType>
        <objectType>HarnessAlphaCase__c</objectType>
        <isInput>true</isInput>
    </variables>
    <recordUpdates>
        <name>Update_Case</name>
        <object>HarnessAlphaCase__c</object>
        <inputAssignments><field>Status__c</field><value><stringValue>Done</stringValue></value></inputAssignments>
        <faultConnector><targetReference>Fault_Screen</targetReference></faultConnector>
    </recordUpdates>
    <customErrors>
        <name>Block_Discount</name>
        <label>Block Discount</label>
        <customErrorMessages>
            <errorMessage>Discount cannot exceed 20% for Standard tier.</errorMessage>
            <isFieldError>true</isFieldError>
            <fieldSelection>Status__c</fieldSelection>
        </customErrorMessages>
    </customErrors>
    <screens>
        <name>Fault_Screen</name>
        <label>Fault Screen</label>
        <fields>
            <name>Reason</name>
            <validationRule>
                <errorMessage>Reason is required before retry.</errorMessage>
                <formulaExpression>NOT(ISBLANK({!Reason}))</formulaExpression>
            </validationRule>
        </fields>
    </screens>
</Flow>
"""

FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Status__c</fullName>
    <label>Status</label>
    <type>Picklist</type>
    <required>true</required>
</CustomField>
"""

PATCHED = ("ROOT", "ARTIFACTS_ROOT", "LEDGER_PATH", "REVIEW_ARTIFACT_ROOT", "LOCAL_CONFIG", "TAXONOMY_PATH")


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.temp, True)
        self._saved = {name: getattr(store, name) for name in PATCHED}
        store.ROOT = self.temp
        store.ARTIFACTS_ROOT = self.temp / ".ai/knowledge/artifacts"
        store.LEDGER_PATH = self.temp / ".ai/knowledge/artifacts-ledger.jsonl"
        store.REVIEW_ARTIFACT_ROOT = self.temp / "output/knowledge-approvals"
        store.LOCAL_CONFIG = self.temp / "config/harness.local.json"
        store.TAXONOMY_PATH = self.temp / ".ai/knowledge/keyword-taxonomy.md"
        self.addCleanup(lambda: [setattr(store, k, v) for k, v in self._saved.items()])
        flow_dir = self.temp / "force-app/main/default/flows"
        flow_dir.mkdir(parents=True)
        (flow_dir / "HarnessAlphaRouter.flow-meta.xml").write_text(FLOW_XML, encoding="utf-8")
        field_dir = self.temp / "force-app/main/default/objects/HarnessAlphaCase__c/fields"
        field_dir.mkdir(parents=True)
        (field_dir / "Status__c.field-meta.xml").write_text(FIELD_XML, encoding="utf-8")
        (self.temp / ".ai/knowledge").mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1] / "schemas", self.temp / "schemas")
        (self.temp / "config").mkdir()
        (self.temp / "config/harness.local.json").write_text(
            json.dumps({"knowledge": {"chatReviewer": "Reviewer Person"}}), encoding="utf-8"
        )
        purpose = self.temp / "purpose.md"
        purpose.write_text("Routes alpha cases to the right queue.", encoding="utf-8")
        self.purpose = str(purpose)
        import subprocess

        for command in (
            ["git", "init", "-q"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=self.temp, check=True, capture_output=True)

    def draft(self, **overrides):
        args = argparse.Namespace(
            metadata_type="Flow",
            full_name="HarnessAlphaRouter",
            namespace=None,
            purpose_file=self.purpose,
            source_api_version="64.0",
            candidate_keyword=None,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return store.command_entry_draft(args)

    def approve(self, pins):
        return store.command_entry_approve(argparse.Namespace(entry=pins))

    def lane_of(self, identity):
        result = store.command_entry_status(argparse.Namespace(identity=identity))
        self.assertEqual(1, len(result["entries"]))
        return result["entries"][0]

    def test_draft_approve_happy_path_and_decoy_exclusion(self) -> None:
        drafted = self.draft()
        self.assertEqual("DRAFTED", drafted["outcome"])
        path = self.temp / drafted["path"]
        frontmatter, body = store.split_entry(path.read_text(encoding="utf-8"))
        # R-13: exactly the customErrors element; screen validation and fault path excluded.
        self.assertEqual(1, len(frontmatter["intentionalErrors"]))
        error = frontmatter["intentionalErrors"][0]
        self.assertEqual("customErrors", error["originTag"])
        self.assertEqual("Block_Discount", error["elementApiName"])
        self.assertEqual({"mode": "field", "field": "Status__c"}, error["presentation"])
        self.assertNotIn("Reason is required", json.dumps(frontmatter))
        self.assertIn("## Purpose", body)
        self.assertEqual("draft", self.lane_of(drafted["identity"])["lane"])
        approved = self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("APPROVED", approved["outcome"])
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("approved-current", lane["lane"])
        artifact = store.REVIEW_ARTIFACT_ROOT / f"{approved['chunkId']}.md"
        self.assertIn("Full body", artifact.read_text(encoding="utf-8"))
        self.assertEqual("PASS", store.command_entry_check(argparse.Namespace())["outcome"])

    def test_customfield_draft_is_supported(self) -> None:
        drafted = self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual("Picklist", frontmatter["typeFacts"]["type"])
        self.assertEqual([], frontmatter.get("intentionalErrors", []))

    def test_namespace_c_is_reserved(self) -> None:
        with self.assertRaises(store.StoreError):
            self.draft(namespace="c")

    def test_hand_flipped_state_without_ledger_is_quarantined(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        text = path.read_text(encoding="utf-8").replace("state: draft", "state: approved")
        path.write_text(text, encoding="utf-8")
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])

    def test_approval_toctou_pin_mismatch_rejects_chunk(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "wrong queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertIn("digest pin mismatch", str(ctx.exception))

    def test_byte_replay_of_old_approval_is_not_current(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        old_bytes = path.read_text(encoding="utf-8")
        (self.temp / "purpose.md").write_text("Corrected purpose text.", encoding="utf-8")
        redrafted = self.draft()
        self.approve([f"{redrafted['identity']}:{redrafted['reviewedContentDigest']}"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        path.write_text(old_bytes, encoding="utf-8")  # replay previously approved bytes
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])  # ledger latest wins (R-01)

    def test_revocation_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        store.command_entry_revoke(
            argparse.Namespace(identity=drafted["identity"], rationale="mis-approved")
        )
        self.assertEqual("revoked", self.lane_of(drafted["identity"])["lane"])

    def test_source_drift_moves_to_drifted_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("Update</recordTriggerType>", "Create</recordTriggerType>"), encoding="utf-8")
        self.assertEqual("approved-drifted", self.lane_of(drafted["identity"])["lane"])

    def test_wrong_path_copy_fails_round_trip(self) -> None:
        drafted = self.draft()
        source = self.temp / drafted["path"]
        rogue = store.ARTIFACTS_ROOT / "CustomField" / "c" / source.name
        rogue.parent.mkdir(parents=True, exist_ok=True)
        rogue.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_check(argparse.Namespace())
        self.assertIn("round-trip", str(ctx.exception))

    def test_duplicate_frontmatter_keys_rejected(self) -> None:
        with self.assertRaises(store.StoreError):
            store.split_entry("---\na: 1\na: 2\n---\n\nbody\n")

    def test_alias_and_merge_keys_rejected(self) -> None:
        with self.assertRaises(store.StoreError):
            store.split_entry("---\nbase: &b {x: 1}\nother: *b\n---\n\n")

    def test_facts_digest_is_enumeration_order_invariant(self) -> None:
        base = {
            "typeFacts": {
                "processType": "Flow",
                "references": [
                    {"kind": "writes-field", "target": "B.F", "assurance": "source-exact"},
                    {"kind": "operates-on", "target": "A", "assurance": "source-exact"},
                ],
            },
            "limitations": ["b", "a"],
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {"typeFacts": "source-exact"},
        }
        reordered = json.loads(json.dumps(base))
        reordered["typeFacts"]["references"].reverse()
        reordered["limitations"].reverse()
        self.assertEqual(store.facts_digest(base), store.facts_digest(reordered))  # R-03

    def test_truncation_digest_uses_full_identity(self) -> None:
        long_a = "A" * 120 + "X"
        long_b = "A" * 120 + "Y"
        name_a = store.safe_name(long_a, f"CustomField:c:{long_a}")
        name_b = store.safe_name(long_b, f"CustomField:c:{long_b}")
        self.assertNotEqual(name_a, name_b)  # R-14
        self.assertTrue(len(name_a) <= store.SAFE_NAME_BUDGET + 9)

    def test_autolaunched_beta_family_drafts_without_trigger(self) -> None:
        # Second independent fixture family (HarnessBeta*): autolaunched, no trigger object.
        flow_dir = self.temp / "force-app/main/default/flows"
        (flow_dir / "HarnessBetaDispatch.flow-meta.xml").write_text(
            FLOW_XML.replace("HarnessAlphaRouter", "HarnessBetaDispatch")
            .replace(
                "<start>\n        <object>HarnessAlphaCase__c</object>\n"
                "        <triggerType>RecordAfterSave</triggerType>\n"
                "        <recordTriggerType>Update</recordTriggerType>\n    </start>",
                "<start></start>",
            ),
            encoding="utf-8",
        )
        drafted = self.draft(full_name="HarnessBetaDispatch")
        frontmatter, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertNotIn("trigger", frontmatter["typeFacts"])
        self.assertEqual(1, len(frontmatter["intentionalErrors"]))

    def test_yaml_11_bool_landmines_stay_strings(self) -> None:
        frontmatter, _ = store.split_entry("---\nvalue: NO\nother: 'yes'\n---\n\n")
        self.assertEqual("NO", frontmatter["value"])


if __name__ == "__main__":
    unittest.main()
