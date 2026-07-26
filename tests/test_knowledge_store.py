from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import knowledge_store as store
from scripts import relation_kinds

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

APEX_CLASS = """public with sharing class HarnessAlphaService {
    @AuraEnabled
    public static void run() {
        List<HarnessAlphaCase__c> rows = [SELECT Id FROM HarnessAlphaCase__c];
        update rows;
    }
}
"""

APEX_META = """<?xml version="1.0" encoding="UTF-8"?>
<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">
    <apiVersion>64.0</apiVersion>
    <status>Active</status>
</ApexClass>
"""

VALIDATION_RULE = """<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Status_Required</fullName>
    <active>true</active>
    <errorConditionFormula>ISBLANK(Status__c)</errorConditionFormula>
    <errorMessage>Status is required.</errorMessage>
    <errorDisplayField>Status__c</errorDisplayField>
</ValidationRule>
"""

PATCHED = ("ROOT", "ARTIFACTS_ROOT", "LEDGER_PATH", "REVIEW_ARTIFACT_ROOT", "LOCAL_CONFIG",
           "TAXONOMY_PATH", "FEATURES_ROOT", "FEATURE_LEDGER_PATH")


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
        store.FEATURES_ROOT = self.temp / ".ai/knowledge/features"
        store.FEATURE_LEDGER_PATH = self.temp / ".ai/knowledge/features-ledger.jsonl"
        self.addCleanup(lambda: [setattr(store, k, v) for k, v in self._saved.items()])
        flow_dir = self.temp / "force-app/main/default/flows"
        flow_dir.mkdir(parents=True)
        (flow_dir / "HarnessAlphaRouter.flow-meta.xml").write_text(FLOW_XML, encoding="utf-8")
        field_dir = self.temp / "force-app/main/default/objects/HarnessAlphaCase__c/fields"
        field_dir.mkdir(parents=True)
        (field_dir / "Status__c.field-meta.xml").write_text(FIELD_XML, encoding="utf-8")
        apex_dir = self.temp / "force-app/main/default/classes"
        apex_dir.mkdir(parents=True)
        (apex_dir / "HarnessAlphaService.cls").write_text(APEX_CLASS, encoding="utf-8")
        (apex_dir / "HarnessAlphaService.cls-meta.xml").write_text(APEX_META, encoding="utf-8")
        vr_dir = self.temp / "force-app/main/default/objects/HarnessAlphaCase__c/validationRules"
        vr_dir.mkdir(parents=True)
        (vr_dir / "Status_Required.validationRule-meta.xml").write_text(VALIDATION_RULE, encoding="utf-8")
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

    def review(self, identities=None):
        return store.command_entry_review(argparse.Namespace(identity=identities))

    def test_entry_review_renders_the_surface_before_approval(self) -> None:
        drafted = self.draft()
        result = self.review()
        self.assertEqual("REVIEW_READY", result["outcome"])
        artifact = self.temp / result["reviewArtifact"]
        text = artifact.read_text(encoding="utf-8")
        # The executor renders the attested body itself; the agent never authors it.
        self.assertIn("Routes alpha cases to the right queue.", text)
        self.assertIn("Attested body", text)
        self.assertIn(drafted["reviewedContentDigest"], text)
        self.assertIn("new approval", text)
        self.assertEqual([drafted["identity"]], result["classification"]["proseChanges"])
        self.assertIn(f"--entry {drafted['identity']}:{drafted['reviewedContentDigest']}", result["approveCommand"])

    def test_reviewed_command_approves_and_edits_after_review_are_rejected(self) -> None:
        drafted = self.draft()
        pins = self.review()["approveCommand"].split("--entry ")[1:]
        self.assertEqual("APPROVED", self.approve([pin.strip() for pin in pins])["outcome"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        # Re-review after a prose edit yields a different digest; the stale pin fails closed.
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.approve([pin.strip() for pin in pins])

    def test_entry_review_skips_invalid_drafts_and_reports_why(self) -> None:
        drafted = self.draft(purpose_file=None)  # facts extracted, description not authored yet
        result = self.review([drafted["identity"]])
        self.assertEqual("NOTHING_TO_REVIEW", result["outcome"])
        self.assertTrue(
            any("sentinel" in problem or "Purpose" in problem for problem in result["problems"]),
            f"the refusal must name why: {result['problems']}",
        )

    def test_entry_review_enforces_the_prose_chunk_cap(self) -> None:
        self.draft()
        self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        saved = store.PROSE_CHUNK_LIMIT
        store.PROSE_CHUNK_LIMIT = 1
        self.addCleanup(setattr, store, "PROSE_CHUNK_LIMIT", saved)
        result = self.review()
        self.assertEqual("CHUNK_TOO_LARGE", result["outcome"])
        self.assertTrue(result["capViolations"])

    def test_facts_only_reapproval_is_classified_separately(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8")
        redrafted = self.draft()  # same prose, regenerated facts
        result = self.review([redrafted["identity"]])
        self.assertEqual([redrafted["identity"]], result["classification"]["factsOnly"])
        self.assertEqual([], result["classification"]["proseChanges"])

    def test_apex_and_validation_rule_profiles_draft_and_approve(self) -> None:
        apex = self.draft(metadata_type="ApexClass", full_name="HarnessAlphaService")
        front, _ = store.split_entry((self.temp / apex["path"]).read_text(encoding="utf-8"))
        self.assertEqual("ApexClass", front["typeFacts"]["kind"])
        self.assertEqual("64.0", front["typeFacts"]["apiVersion"])
        self.assertIn("references", front["typeFacts"])
        # Heuristic Apex lineage must not be laundered as exact.
        self.assertTrue(all("assurance" in edge for edge in front["typeFacts"]["references"]))
        self.assertEqual([], front.get("intentionalErrors", []))

        rule = self.draft(
            metadata_type="ValidationRule", full_name="HarnessAlphaCase__c.Status_Required"
        )
        front, _ = store.split_entry((self.temp / rule["path"]).read_text(encoding="utf-8"))
        self.assertEqual("HarnessAlphaCase__c", front["typeFacts"]["object"])
        self.assertTrue(front["typeFacts"]["active"])
        # The rule itself must be IN the entry — an entry saying only "this rule has a
        # condition" cannot answer what the rule enforces.
        declared = front["typeFacts"]["errorCatalog"][0]
        self.assertEqual("ISBLANK(Status__c)", declared["condition"])
        self.assertEqual("Status is required.", declared["errorMessage"])
        # ...while staying out of intentionalErrors, which is FlowCustomError-only.
        self.assertEqual([], front.get("intentionalErrors", []))

        self.approve([f"{apex['identity']}:{apex['reviewedContentDigest']}",
                      f"{rule['identity']}:{rule['reviewedContentDigest']}"])
        for drafted in (apex, rule):
            self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])

    def test_every_profile_has_a_schema_and_an_adapter(self) -> None:
        for metadata_type, profile in store.PROFILES.items():
            with self.subTest(metadataType=metadata_type):
                self.assertIn(metadata_type, store.ADAPTERS)
                self.assertTrue((self.temp / "schemas" / profile["schema"]).is_file())

    def test_work_record_entry_refs_validate_and_track_lanes(self) -> None:
        from scripts import work_record

        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        lane = store.lane_for_identity(self.temp, drafted["identity"])
        reference = {
            "entryId": drafted["identity"],
            "reviewedContentDigest": lane["reviewedContentDigest"],
            "factsDigest": lane["factsDigest"],
            "sourceTreeDigest": lane["sourceTreeDigest"],
            "profile": lane["profile"],
        }
        work_record.validate_entry_refs(self.temp, [reference], require_current=True)
        tampered = dict(reference, reviewedContentDigest="sha256:" + "f" * 64)
        with self.assertRaises(work_record.WorkRecordError):
            work_record.validate_entry_refs(self.temp, [tampered], require_current=True)
        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("Active", "Draft"), encoding="utf-8")
        with self.assertRaises(work_record.WorkRecordError):  # drifted is not current
            work_record.validate_entry_refs(self.temp, [reference], require_current=True)
        work_record.validate_entry_refs(self.temp, [reference], require_current=False)

    def test_repo_only_claims_are_shadowed_by_approved_entries(self) -> None:
        from scripts import work_record

        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        claims_dir = self.temp / ".ai/knowledge/claims"
        evidence_dir = self.temp / ".ai/knowledge/evidence"
        claims_dir.mkdir(parents=True)
        evidence_dir.mkdir(parents=True)
        (claims_dir / "KCLM-ROUTER-DESC-001.yaml").write_text(
            "claimId: KCLM-ROUTER-DESC-001\nevidenceRefs: [KEVD-ROUTER-SRC-001]\n",
            encoding="utf-8",
        )
        expected = {
            "claimType": "component-description",
            "subject": {"kind": "automation", "identity": "HarnessAlphaRouter"},
        }
        (evidence_dir / "KEVD-ROUTER-SRC-001.yaml").write_text(
            "evidenceId: KEVD-ROUTER-SRC-001\nsourceType: metadata-repository\n",
            encoding="utf-8",
        )
        with self.assertRaises(work_record.WorkRecordError) as ctx:
            work_record._assert_not_shadowed(self.temp, "KCLM-ROUTER-DESC-001", expected)
        self.assertIn("shadowed-by-entry", str(ctx.exception))
        # An org-observation leg of the same claim type keeps its v1 standing.
        (evidence_dir / "KEVD-ROUTER-SRC-001.yaml").write_text(
            "evidenceId: KEVD-ROUTER-SRC-001\nsourceType: salesforce-org-review\n",
            encoding="utf-8",
        )
        work_record._assert_not_shadowed(self.temp, "KCLM-ROUTER-DESC-001", expected)

    # --- remaining adversarial-review evals (R-09..R-24) ---------------------------

    def test_r09_reparse_point_under_knowledge_fails_closed(self) -> None:
        target = self.temp / "elsewhere"
        target.mkdir()
        link = self.temp / ".ai/knowledge/artifacts-link"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as error:  # Windows without developer mode
            self.skipTest(f"symlink creation unavailable on this platform: {error}")
        with self.assertRaises(store.StoreError) as ctx:
            store.assert_no_reparse_points()
        self.assertIn("reparse", str(ctx.exception))

    def test_r10_sensitivity_flip_after_approval_invalidates(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("sensitivity: internal-sanitized", "sensitivity: public"),
            encoding="utf-8",
        )
        self.assertEqual("not-effective", self.lane_of(drafted["identity"])["lane"])

    def test_r11_provenance_tamper_is_detected_against_the_ledger(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("Reviewer Person", "Someone Else"),
            encoding="utf-8",
        )
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("not-effective", lane["lane"])
        self.assertTrue(any("provenance" in problem for problem in lane["problems"]))

    def test_r21_interrupted_chunk_leaves_only_completed_stamps_effective(self) -> None:
        first = self.draft()
        second = self.draft(metadata_type="CustomField", full_name="HarnessAlphaCase__c.Status__c")
        original_write = store.atomic_write
        calls = {"count": 0}

        def failing_write(path, text):
            calls["count"] += 1
            if calls["count"] > 1:
                raise OSError("simulated crash mid-chunk")
            return original_write(path, text)

        store.atomic_write = failing_write
        self.addCleanup(setattr, store, "atomic_write", original_write)
        with self.assertRaises(OSError):
            self.approve(
                [
                    f"{first['identity']}:{first['reviewedContentDigest']}",
                    f"{second['identity']}:{second['reviewedContentDigest']}",
                ]
            )
        store.atomic_write = original_write
        lanes = {entry["identity"]: entry["lane"] for entry in store.command_entry_status(argparse.Namespace(identity=None))["entries"]}
        # The journaled ledger records only what completed; the rest stays draft.
        self.assertEqual(1, sum(1 for lane in lanes.values() if lane == "approved-current"))
        self.assertEqual(1, sum(1 for lane in lanes.values() if lane == "draft"))
        self.assertEqual(1, len(store.read_ledger()))

    def test_r23_profile_patch_bump_changes_no_lane(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(
            path.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.0.9"),
            encoding="utf-8",
        )
        # reviewedContentDigest binds the profile MAJOR only, so a patch bump is a no-op.
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])

    def test_r24_body_with_dashes_and_fenced_yaml_has_one_boundary(self) -> None:
        body = "## Purpose\n\nSee below.\n\n---\n\n```yaml\nkey: value\n---\nother: value\n```\n"
        text = "---\nschemaVersion: 1\n---\n\n" + body
        frontmatter, parsed = store.split_entry(text)
        self.assertEqual({"schemaVersion": 1}, frontmatter)
        self.assertIn("```yaml", parsed)
        self.assertIn("other: value", parsed)
        self.assertEqual(store.semantics_digest(parsed), store.semantics_digest(parsed + "\n"))

    def test_yaml_11_bool_landmines_stay_strings(self) -> None:
        frontmatter, _ = store.split_entry("---\nvalue: NO\nother: 'yes'\n---\n\n")
        self.assertEqual("NO", frontmatter["value"])


if __name__ == "__main__":
    unittest.main()


class CrossPlatformDeterminismTests(KnowledgeStoreTests):
    """Windows-sensitive behavior. CI runs this suite on ubuntu-latest AND windows-latest,
    so these assertions are the cross-platform gate the review asked for (R-20 partial:
    correctness on Windows is covered here; Windows *latency* still needs a manual run)."""

    def test_entry_bytes_are_identical_across_repeated_drafts(self) -> None:
        first = self.draft()
        first_bytes = (self.temp / first["path"]).read_bytes()
        second = self.draft()
        self.assertEqual(first_bytes, (self.temp / second["path"]).read_bytes())
        self.assertEqual(first["reviewedContentDigest"], second["reviewedContentDigest"])

    def test_entries_are_written_with_lf_regardless_of_platform(self) -> None:
        drafted = self.draft()
        raw = (self.temp / drafted["path"]).read_bytes()
        self.assertNotIn(b"\r\n", raw)  # os.linesep must never leak into a digested file

    def test_crlf_and_lf_bodies_share_one_semantics_digest(self) -> None:
        lf = "## Purpose\n\nRoutes cases.\n"
        crlf = "## Purpose\r\n\r\nRoutes cases.\r\n"
        self.assertEqual(store.semantics_digest(lf), store.semantics_digest(crlf))

    def test_case_fold_collision_is_refused_not_silently_merged(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        twin = path.with_name(path.name.upper())
        if twin.exists():  # case-insensitive filesystem: the collision is physical
            self.skipTest("filesystem is case-insensitive; collision cannot be staged")
        twin.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.command_entry_check(argparse.Namespace())
        self.assertTrue(
            "case-fold" in str(ctx.exception) or "round-trip" in str(ctx.exception)
        )

    def test_windows_reserved_device_names_get_a_digest_suffix(self) -> None:
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            with self.subTest(name=reserved):
                stem = store.safe_name(reserved, f"Flow:c:{reserved}")
                self.assertNotEqual(reserved.casefold(), stem.casefold())
                self.assertTrue(stem.upper().startswith(reserved))

    def test_identity_normalization_is_nfkc_and_path_budget_is_enforced(self) -> None:
        # Composed and decomposed spellings must resolve to one identity, not two files.
        composed = store.safe_name("Zażółć__c", "CustomField:c:Zażółć__c")
        decomposed = store.safe_name("Zaz\u0307o\u0301łc\u0301__c", "CustomField:c:Zaz\u0307o\u0301łc\u0301__c")
        self.assertTrue(composed and decomposed)
        # A very long API name is protected by truncation, so the path stays in budget...
        long_path = store.entry_path("Flow", None, "X" * 400)
        self.assertLessEqual(len(str(long_path.relative_to(store.ROOT))), store.PATH_BUDGET)
        # ...and the budget itself is a real backstop, not decoration.
        saved = store.PATH_BUDGET
        store.PATH_BUDGET = 20
        self.addCleanup(setattr, store, "PATH_BUDGET", saved)
        with self.assertRaises(store.StoreError) as ctx:
            store.entry_path("Flow", None, "X" * 400)
        self.assertIn("budget", str(ctx.exception))

    def test_atomic_write_replaces_an_existing_file(self) -> None:
        # os.replace over an existing target is the Windows-fragile operation in the writer.
        path = self.temp / "atomic-target.md"
        store.atomic_write(path, "first\n")
        store.atomic_write(path, "second\n")
        self.assertEqual("second\n", path.read_text(encoding="utf-8"))
        self.assertFalse(path.with_suffix(".tmp").exists())


class EntryCitationVerificationTests(KnowledgeStoreTests):
    """verify-citations must cover both citation kinds, or an envelope is half-checked."""

    def registry(self):
        from scripts.knowledge_registry import KnowledgeRegistry

        return KnowledgeRegistry(self.temp)

    def test_verdicts_track_the_entry_lifecycle(self) -> None:
        drafted = self.draft()
        ref = {"entryId": drafted["identity"], "reviewedContentDigest": drafted["reviewedContentDigest"]}
        self.assertEqual("not-approved", self.registry().verify_entry_citations([ref])[0]["verdict"])

        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("current", self.registry().verify_entry_citations([ref])[0]["verdict"])

        flow = self.temp / "force-app/main/default/flows/HarnessAlphaRouter.flow-meta.xml"
        flow.write_text(FLOW_XML.replace("<status>Active</status>", "<status>Draft</status>"), encoding="utf-8")
        drifted = self.registry().verify_entry_citations([ref])[0]
        self.assertEqual("drifted", drifted["verdict"])
        self.assertEqual("warning", drifted["severity"])

        store.command_entry_revoke(argparse.Namespace(identity=drafted["identity"], rationale="x"))
        self.assertEqual("revoked", self.registry().verify_entry_citations([ref])[0]["verdict"])

    def test_missing_and_mismatched_citations_are_invalid(self) -> None:
        registry = self.registry()
        self.assertEqual("missing", registry.verify_entry_citations([{"entryId": "Flow:c:Nope"}])[0]["verdict"])
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        stale = {"entryId": drafted["identity"], "reviewedContentDigest": "sha256:" + "0" * 64}
        verdict = self.registry().verify_entry_citations([stale])[0]
        self.assertEqual("digest-mismatch", verdict["verdict"])
        self.assertEqual("invalid", verdict["severity"])

    def test_entry_coverage_separates_gaps_from_unprofiled_types(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        report = store.command_entry_coverage(argparse.Namespace())
        self.assertEqual({"approved-current": 1}, report["lanes"]["Flow"])
        # CustomField/ValidationRule sources exist without entries -> real gaps
        self.assertIn("CustomField", report["missingEntryCounts"])
        # A type with no profile is listed as unprofiled, never as a coverage gap
        self.assertNotIn("CustomObject", report["missingEntryCounts"])


class AdapterFaithfulnessTests(unittest.TestCase):
    """An entry must carry what the collector extracted.

    Hand-listing which facts to KEEP silently lost real content: validation rules arrived as
    `conditionPresent: true` with no formula, fields lost their picklist values and rollup
    definitions, Apex lost its sharing model. Adapters now pass everything through, and any
    fact a profile does not declare fails validation loudly instead of vanishing.
    """

    def test_adapters_drop_nothing_that_is_not_declared_and_justified(self) -> None:
        for metadata_type, adapter in store.ADAPTERS.items():
            if metadata_type == "Flow":
                continue  # bespoke adapter; its exclusions are asserted below
            with self.subTest(metadataType=metadata_type):
                facts = {"alpha": 1, "beta": "two", "gamma": ["three"]}
                carried, _errors, _assurance = adapter({"facts": facts, "metadataType": metadata_type})
                for key in facts:
                    self.assertIn(key, carried, f"{metadata_type} silently dropped {key}")

    def test_every_flow_exclusion_states_a_reason(self) -> None:
        for metadata_type, exclusions in store.FACT_EXCLUSIONS.items():
            for key, reason in exclusions.items():
                with self.subTest(metadataType=metadata_type, fact=key):
                    self.assertTrue(reason.strip(), f"{metadata_type}.{key} is excluded without a reason")

    def test_numeric_xml_text_is_normalized_but_other_text_is_verbatim(self) -> None:
        adapter = store.ADAPTERS["CustomField"]
        carried, _, _ = adapter({"facts": {"length": "18", "label": "18 characters", "object": "X__c"}})
        self.assertEqual(18, carried["length"])
        self.assertEqual("18 characters", carried["label"])

    def test_validation_rule_entry_carries_the_rule_itself(self) -> None:
        component = {
            "metadataType": "ValidationRule",
            "facts": {
                "object": "ClientProfile__c",
                "active": True,
                "errorDisplayField": "Health_Score__c",
                "errorCatalog": [
                    {
                        "component": "Health_Score_In_Range",
                        "kind": "validation-rule",
                        "condition": "NOT(ISBLANK(Health_Score__c))",
                        "errorMessage": "Health Score must be between 0 and 100.",
                    }
                ],
            },
        }
        carried, errors, _ = store.ADAPTERS["ValidationRule"](component)
        self.assertEqual("NOT(ISBLANK(Health_Score__c))", carried["errorCatalog"][0]["condition"])
        self.assertIn("between 0 and 100", carried["errorCatalog"][0]["errorMessage"])
        # A validation rule's message is not a Flow Custom Error and never enters that index.
        self.assertEqual([], errors)


class EdgeAssuranceTests(unittest.TestCase):
    """A kind-level heuristic must never be stored as source-exact.

    The collector sets its per-edge `heuristic` flag only for kinds that are heuristic
    *sometimes* (`queries-object` is structural from Flow XML, regex-derived from Apex). Reading
    only that flag meant kinds that are heuristic *always* — object-token, invokes-class,
    var-field-ref, soql-field — were stored source-exact: 414 of 595 edges in a 189-component
    probe corpus. The marker is inside factsDigest, so a human approved the false claim, and
    SAFE-CLAIM-001 v2 would then ground a work record on a regex match against a comment.
    """

    def test_kind_level_heuristics_are_never_stored_as_source_exact(self) -> None:
        component = {
            "metadataType": "ApexClass",
            "facts": {},
            "references": [
                {"kind": kind, "target": "Whatever__c"}
                for kind in sorted(relation_kinds.HEURISTIC_REF_KINDS)
            ],
        }
        carried, _errors, assurance = store.ADAPTERS["ApexClass"](component)
        for edge in carried["references"]:
            with self.subTest(kind=edge["kind"]):
                self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, edge["assurance"])
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, assurance["typeFacts"])

    def test_structural_kinds_stay_exact_unless_the_collector_flags_the_edge(self) -> None:
        component = {
            "metadataType": "ApexClass",
            "facts": {},
            "references": [
                {"kind": "operates-on", "target": "A__c"},
                # queries-object is structural from Flow XML and heuristic from an Apex regex,
                # so the per-edge flag carries what the kind alone cannot.
                {"kind": "queries-object", "target": "B__c"},
                {"kind": "queries-object", "target": "C__c", "heuristic": True},
            ],
        }
        carried, _errors, _assurance = store.ADAPTERS["ApexClass"](component)
        by_target = {edge["target"]: edge["assurance"] for edge in carried["references"]}
        self.assertEqual(relation_kinds.SOURCE_EXACT, by_target["A__c"])
        self.assertEqual(relation_kinds.SOURCE_EXACT, by_target["B__c"])
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, by_target["C__c"])

    def test_flow_edges_use_the_same_rule_as_every_other_type(self) -> None:
        # The Flow adapter is bespoke and derived assurance independently, which is exactly how
        # two implementations of one rule drift apart.
        carried, _errors, assurance = store.flow_type_facts(
            {"facts": {"processType": "AutoLaunchedFlow", "status": "Active"},
             "references": [{"kind": "launches-flow", "target": "Other"}]}
        )
        self.assertEqual(
            relation_kinds.SOURCE_DERIVED_HEURISTIC, carried["references"][0]["assurance"]
        )
        self.assertEqual(relation_kinds.SOURCE_DERIVED_HEURISTIC, assurance["typeFacts"])

    def test_every_declared_kind_resolves_to_a_declared_assurance(self) -> None:
        for kind in sorted(relation_kinds.ALL_REF_KINDS):
            with self.subTest(kind=kind):
                self.assertIn(
                    relation_kinds.edge_assurance(kind),
                    (relation_kinds.SOURCE_EXACT, relation_kinds.SOURCE_DERIVED_HEURISTIC),
                )


class ProfileSchemaCoverageTests(unittest.TestCase):
    """Every fact an adapter carries must be declared by its profile schema.

    typeFacts is additionalProperties:false, so an undeclared fact does not degrade — it fails
    the draft outright. Six such facts shipped undetected (summaryFilterFields,
    lookupFilterPresent, lookupFilterFields, externalSharingModel, compactLayoutAssignment,
    picklistScopes) because AdapterFaithfulnessTests proves pass-through but never validates the
    result against the schema that has to accept it.
    """

    SAMPLES = {
        "CustomField": {
            "object": "A__c", "type": "Summary", "summaryOperation": "sum",
            "summaryForeignKey": "B__c.A__c", "summarizedField": "B__c.Hours__c",
            "summaryFilterFields": ["B__c.Active__c"], "lookupFilterPresent": True,
            "lookupFilterFields": ["B__c.Status__c"],
        },
        "CustomObject": {
            "objectKind": "custom", "sharingModel": "ReadWrite",
            "externalSharingModel": "Private", "compactLayoutAssignment": "SYSTEM",
        },
        "RecordType": {
            "object": "A__c", "active": True,
            "picklistScopes": [{"picklist": "Status__c", "valueCount": 3, "defaults": ["New"]}],
        },
        "Flow": {
            "processType": "AutoLaunchedFlow", "status": "Active",
            "object": "A__c", "triggerType": "RecordAfterSave", "recordTriggerType": "Update",
            "variables": [
                {"name": "record", "dataType": "SObject", "objectType": "A__c",
                 "isInput": True, "isOutput": False, "isCollection": False}
            ],
            "dataOperations": [{"operation": "update", "object": "A__c", "element": "Set_Status"}],
            "errorCatalog": [
                {"kind": "custom-error", "component": "Block_Discount",
                 "componentLabel": "Block Discount", "errorMessage": "Discount too high: $Label.Cap",
                 "resolvedErrorMessage": "Discount too high: 20%",
                 "isFieldError": True, "fieldSelection": "Status__c",
                 "triggerContext": "after-save", "paths": [["Decision", "Yes"]],
                 "pathsTruncated": True}
            ],
        },
        "ApexClass": {
            "declarationKind": "class", "sharingModel": "with sharing",
            "superclass": "BaseHandler", "interfaces": ["Queueable"], "isTest": False,
            "annotations": ["@AuraEnabled"], "description": "Routes alpha cases.",
            "apiVersion": "64.0", "status": "Active", "soqlObjects": ["A__c"],
            "dmlOperations": ["update"], "dmlTargets": {"A__c": ["update"]},
        },
        "ApexTrigger": {
            "object": "A__c", "events": ["after update"], "annotations": [],
            "apiVersion": "64.0", "status": "Active", "soqlObjects": ["A__c"],
            "dmlOperations": ["insert"], "dmlTargets": {"B__c": ["insert"]},
            "description": "Delegates to the handler.",
        },
        "ValidationRule": {
            "object": "A__c", "active": True, "errorDisplayField": "Status__c",
            "errorMessagePresent": True,
            "errorCatalog": [
                {"component": "Status_Required", "kind": "validation-rule",
                 "errorMessage": "Status is required.", "fieldSelection": "Status__c",
                 "condition": "ISBLANK(Status__c)", "resolvedErrorMessage": "Status is required."}
            ],
        },
        "PermissionSet": {
            "label": "Alpha Ops", "description": "Grants alpha access.", "license": "Salesforce",
            "hasActivationRequired": False, "objectAccess": {"A__c": "CRE+VA"},
            "systemPermissions": ["ViewSetup"], "objectPermissionCount": 2,
            "fieldPermissionCount": 400, "classAccessCount": 1, "customPermissionCount": 1,
            "recordTypeCount": 1, "flowAccessCount": 1, "userPermissionCount": 1,
            "tabCount": 1, "pageAccessCount": 1, "applicationVisibilityCount": 1,
            "referencesTruncated": True, "truncatedFamilies": ["grants-field-edit"],
        },
        "CustomMetadata": {
            "type": "Routing__mdt", "record": "Default", "label": "Default",
            "protected": False, "fieldsPopulated": ["Threshold__c"],
            "values": [{"field": "Threshold__c", "value": 20}],
        },
        "LightningComponentBundle": {
            "isExposed": True, "targets": ["lightning__RecordPage"], "masterLabel": "Alpha Card",
            "description": "Shows the alpha case.",
            "targetConfigs": [{"targets": "lightning__RecordPage", "objects": ["A__c"]}],
            "apiProperties": ["recordId"], "wiredAdapters": ["getRecord"],
        },
    }

    def test_a_sample_exists_for_every_profiled_type(self) -> None:
        # The plan chose this test as "the standing test that would have caught all six"
        # undeclared properties. Three hand-written samples would not have caught a seventh:
        # Flow, Apex, PermissionSet, CustomMetadata and LWC were validated against their profile
        # schemas by no test and by no corpus. The set equality is what makes it standing — a
        # new profiled type cannot be added without a fixture that has to validate.
        self.assertEqual(set(store.PROFILES), set(self.SAMPLES))

    def test_adapter_output_validates_against_the_profile_schema(self) -> None:
        for metadata_type, facts in self.SAMPLES.items():
            with self.subTest(metadataType=metadata_type):
                carried, errors, _assurance = store.ADAPTERS[metadata_type](
                    {
                        "metadataType": metadata_type,
                        "facts": facts,
                        # An edge exercises the shape every profile declares and none of the
                        # hand-written samples reached.
                        "references": [{"kind": "operates-on", "target": "A__c"}],
                    }
                )
                schema = store.load_schema(store.PROFILES[metadata_type]["schema"])
                payload = {"typeFacts": carried, "intentionalErrors": errors}
                problems = sorted(
                    error.message
                    for error in Draft202012Validator(schema).iter_errors(payload)
                )
                self.assertEqual([], problems, f"{metadata_type}: {problems}")


class AgentDescriptionTests(KnowledgeStoreTests):
    """The description is the one part of an entry a model writes rather than extracts."""

    def describe(self, identity: str, text: str):
        path = self.temp / "description.md"
        path.write_text(text, encoding="utf-8")
        return store.command_entry_describe(
            argparse.Namespace(identity=identity, purpose_file=str(path))
        )

    def test_undescribed_draft_carries_a_sentinel_and_cannot_be_approved(self) -> None:
        drafted = self.draft(purpose_file=None)
        body = (self.temp / drafted["path"]).read_text(encoding="utf-8")
        self.assertIn("<AGENT_DESCRIPTION>", body)
        review = store.command_entry_review(argparse.Namespace(identity=[drafted["identity"]]))
        self.assertEqual("NOTHING_TO_REVIEW", review["outcome"])
        self.assertTrue(any("sentinel" in problem for problem in review["problems"]))

    def test_describe_replaces_the_sentinel_and_unlocks_review(self) -> None:
        drafted = self.draft(purpose_file=None)
        described = self.describe(
            drafted["identity"],
            "Routes engagement records to the owning queue after save. Blocks the update when "
            "the discount exceeds the approved threshold.",
        )
        self.assertEqual("DESCRIBED", described["outcome"])
        self.assertTrue(described["replacedSentinel"])
        self.assertEqual(2, described["sentences"])
        review = store.command_entry_review(argparse.Namespace(identity=[drafted["identity"]]))
        self.assertEqual("REVIEW_READY", review["outcome"])

    def test_rewriting_a_description_invalidates_an_existing_approval(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        self.assertEqual("approved-current", self.lane_of(drafted["identity"])["lane"])
        result = self.describe(drafted["identity"], "A materially different description.")
        self.assertTrue(result["previousApprovalInvalidated"])
        self.assertEqual("draft", self.lane_of(drafted["identity"])["lane"])

    def test_description_length_is_bounded_and_emptiness_refused(self) -> None:
        drafted = self.draft(purpose_file=None)
        with self.assertRaises(store.StoreError):
            self.describe(drafted["identity"], "   ")
        with self.assertRaises(store.StoreError) as ctx:
            self.describe(drafted["identity"], " ".join(f"Sentence {i}." for i in range(20)))
        self.assertIn("1-8 sentences", str(ctx.exception))

    def test_describe_never_touches_extracted_facts(self) -> None:
        drafted = self.draft()
        before, _ = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.describe(drafted["identity"], "Rewritten description of the component.")
        after, body = store.split_entry((self.temp / drafted["path"]).read_text(encoding="utf-8"))
        self.assertEqual(before["typeFacts"], after["typeFacts"])
        self.assertEqual(before["intentionalErrors"], after["intentionalErrors"])
        self.assertIn("Rewritten description", body)


class DraftLaneHonestyTests(KnowledgeStoreTests):
    """Unfinished work and broken work must not look the same."""

    def test_undescribed_draft_reports_draft_with_the_reason(self) -> None:
        drafted = self.draft(purpose_file=None)
        lane = self.lane_of(drafted["identity"])
        self.assertEqual("draft", lane["lane"])
        self.assertTrue(any("sentinel" in problem for problem in lane["problems"]))

    def test_tampered_approved_entry_still_reports_not_effective(self) -> None:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        self.assertEqual("not-effective", self.lane_of(drafted["identity"])["lane"])


class WorkflowReachabilityTests(unittest.TestCase):
    """Every executor command must be reachable from the public surface AND permitted.

    A command that exists but no prompt, skill or agent ever names is dead machinery; a
    command a prompt names but the guard denies is a broken prompt. Both failed silently
    until this test: the approval skill was not loaded by its own agent, and nothing on the
    public surface drafted or described an entry at all.
    """

    HARNESS = Path(__file__).resolve().parents[1]

    def surface_text(self) -> str:
        parts = []
        for pattern in (".github/prompts/*.prompt.md", ".github/skills/*/SKILL.md", ".github/agents/*.agent.md"):
            for path in sorted(self.HARNESS.glob(pattern)):
                parts.append(path.read_text(encoding="utf-8"))
        return "\n".join(parts)

    # Commands that belong to CI rather than to a person, with the reason.
    NOT_ON_PUBLIC_SURFACE = {
        "entry-check": "CI integrity gate, run by validate_harness",
        "feature-check": "CI integrity gate over features and their ledger, run by validate_harness",
    }

    def test_every_entry_command_is_named_on_the_public_surface(self) -> None:
        surface = self.surface_text()
        commands = set(store.build_parser()._subparsers._group_actions[0].choices)
        for command in sorted(commands - set(self.NOT_ON_PUBLIC_SURFACE)):
            with self.subTest(command=command):
                self.assertIn(
                    command, surface, f"{command} is not reachable from any prompt, skill or agent"
                )

    def test_ci_only_commands_are_declared_and_actually_run_by_ci(self) -> None:
        workflow = (self.HARNESS / ".github/workflows/harness-ci.yml").read_text(encoding="utf-8")
        validator = (self.HARNESS / "scripts/validate_harness.py").read_text(encoding="utf-8")
        for command, reason in self.NOT_ON_PUBLIC_SURFACE.items():
            with self.subTest(command=command):
                self.assertTrue(reason.strip())
                # Being NAMED in the validator is not being RUN by it. feature-check was named
                # in a prompt, in the role guard and in this file's own docstrings while being
                # executed by nothing — and the live tree failed it for a day while
                # validate_harness reported PASS. The pin is the argv, not the mention.
                self.assertTrue(
                    f'"scripts/knowledge_store.py", "{command}"' in validator
                    or f"python scripts/knowledge_store.py {command}" in workflow,
                    f"{command} is declared CI-only but no CI step runs it",
                )

    def test_every_grounding_subprocess_is_covered_by_the_timeout_handler(self) -> None:
        # §0.3 item 1: an uncaught TimeoutExpired surfaces as a bare traceback in two gates at
        # once, attributable to nothing. The handler exists — this asserts that the loop the
        # grounding commands are actually run in is the one wrapped by it, so adding a second
        # subprocess outside it cannot pass review by looking adjacent to the first.
        import ast

        source = (self.HARNESS / "scripts/validate_harness.py").read_text(encoding="utf-8")
        loops = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.For)
            and "feature-check" in {
                literal.value
                for literal in ast.walk(node.iter)
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str)
            }
        ]
        self.assertEqual(1, len(loops), "the grounding command loop was not found")
        handlers = [
            handler
            for statement in ast.walk(loops[0])
            if isinstance(statement, ast.Try)
            for handler in statement.handlers
        ]
        self.assertTrue(
            any(
                isinstance(handler.type, ast.Attribute)
                and handler.type.attr == "TimeoutExpired"
                for handler in handlers
            ),
            "grounding commands run outside the subprocess.TimeoutExpired handler",
        )

    def test_the_curator_agent_loads_the_skills_its_prompts_use(self) -> None:
        agent = (self.HARNESS / ".github/agents/knowledge-curator.agent.md").read_text(encoding="utf-8")
        for skill in ("approve-knowledge-drafts", "propose-force-app-knowledge", "batch-knowledge"):
            with self.subTest(skill=skill):
                self.assertIn(skill, agent, f"knowledge-curator does not load {skill}")

    def test_each_workflow_step_is_permitted_for_the_curator_and_denied_elsewhere(self) -> None:
        from scripts import copilot_role_guard as guard

        mutations = [
            "python scripts/knowledge_store.py entry-draft --metadata-type Flow --full-name X",
            "python scripts/knowledge_store.py entry-describe --identity Flow:c:X --purpose-file d.md",
            "python scripts/knowledge_store.py entry-approve --entry Flow:c:X:sha256:" + "a" * 64,
        ]
        reads = [
            "python scripts/knowledge_store.py entry-context --identity Flow:c:X",
            "python scripts/knowledge_store.py entry-coverage",
            "python scripts/knowledge_store.py entry-review",
        ]
        for command in mutations:
            with self.subTest(command=command.split("py ")[1].split()[0]):
                self.assertTrue(guard.allowed_role_command(command, self.HARNESS, "knowledge-curator"))
                self.assertFalse(guard.allowed_role_command(command, self.HARNESS, "solution-designer"))
        for command in reads:
            with self.subTest(command=command.split("py ")[1].split()[0]):
                for role in ("knowledge-curator", "solution-designer", "guardrail-reviewer"):
                    self.assertTrue(guard.allowed_role_command(command, self.HARNESS, role))


class FeatureEntryTests(KnowledgeStoreTests):
    """A Feature Entry approves a BOUNDARY RULE, never a member list.

    That split is the whole design. Membership is a function of the rule AND of the package, so
    storing it would mean every new artifact drifts every feature that could contain it — and a
    reviewer would be re-approving a list they never read.
    """

    def propose(self, **kwargs):
        args = argparse.Namespace(
            slug="scheduling", name="Scheduling", anchor=["HarnessAlphaCase__c"], hub=None,
            depth=1, include=None, exclude=None, assurance_floor="source-exact", replace=False,
        )
        for key, value in kwargs.items():
            setattr(args, key, value)
        return store.command_feature_propose(args)

    def describe(self, slug="scheduling", text="Allocating people and detecting overlaps."):
        path = self.temp / "fdesc.md"
        path.write_text(text, encoding="utf-8")
        return store.command_feature_describe(
            argparse.Namespace(slug=slug, purpose_file=str(path))
        )

    def approve_feature(self, slug="scheduling"):
        review = store.command_feature_review(argparse.Namespace(slug=[slug]))
        pins = [
            part for part in review["approveCommand"].split() if part.startswith("Feature:")
        ]
        return store.command_feature_approve(argparse.Namespace(feature=pins))

    def lane(self, slug="scheduling"):
        latest = store.ledger_latest(store.read_ledger(store.FEATURE_LEDGER_PATH))
        return store.compute_feature_lane(store.feature_path(slug), latest)

    def test_a_feature_cannot_be_approved_before_it_is_described(self) -> None:
        self.propose()
        review = store.command_feature_review(argparse.Namespace(slug=None))
        self.assertEqual("NOTHING_TO_REVIEW", review["outcome"])
        self.assertTrue(review["skipped"])

    def test_approval_binds_the_rule_and_the_prose(self) -> None:
        self.propose()
        self.describe()
        result = self.approve_feature()
        self.assertEqual("APPROVED", result["outcome"])
        self.assertEqual("approved-current", self.lane()["lane"])

    def test_the_ledger_records_digests_and_no_member_list(self) -> None:
        self.propose()
        self.describe()
        self.approve_feature()
        record = store.read_ledger(store.FEATURE_LEDGER_PATH)[-1]
        self.assertIn("boundaryDigest", record)
        # §6: a membershipDigest is pinned, a member LIST never is. The digest says whether
        # membership moved; it cannot re-approve the artifacts it summarises, and the reviewer
        # was told they were not approving a list.
        self.assertIn("membershipDigest", record)
        for forbidden in ("members", "memberCount"):
            self.assertNotIn(forbidden, record)

    def test_reordering_anchors_is_the_same_rule(self) -> None:
        # Anchors and hubs are sets in meaning; a cosmetic reorder must not demand re-approval.
        first = self.propose(anchor=["A__c", "B__c"])
        second = self.propose(anchor=["B__c", "A__c"], replace=True)
        self.assertEqual(first["boundaryDigest"], second["boundaryDigest"])

    def test_changing_the_rule_returns_the_feature_to_draft(self) -> None:
        self.propose()
        self.describe()
        self.approve_feature()
        self.propose(depth=2, replace=True)
        self.assertNotEqual("approved-current", self.lane()["lane"])

    def test_rewriting_the_description_returns_the_feature_to_draft(self) -> None:
        self.propose()
        self.describe()
        self.approve_feature()
        self.describe(text="A different account of what this feature is.")
        self.assertEqual("draft", self.lane()["lane"])

    def test_features_live_outside_the_artifact_corpus(self) -> None:
        # If a Feature ever landed under ARTIFACTS_ROOT it would enter the artifact index and
        # could be offered as an entryRef, and every artifact reader would meet a file with no
        # subject.metadataType.
        self.propose()
        self.describe()
        self.assertNotIn(
            store.feature_path("scheduling").resolve(),
            {path.resolve() for path in store.all_entry_paths()},
        )
        self.assertNotEqual(store.FEATURE_LEDGER_PATH, store.LEDGER_PATH)

    def test_a_feature_identity_has_two_segments(self) -> None:
        # Three would satisfy work_record.entry_relative_path's unpack and resolve to a path
        # under ARTIFACTS_ROOT that does not exist, failing silently instead of loudly.
        self.assertEqual("Feature:scheduling", store.feature_identity("scheduling"))
        self.assertEqual(2, len(store.feature_identity("scheduling").split(":")))

    def test_feature_check_catches_an_approved_file_with_no_ledger_record(self) -> None:
        self.propose()
        self.describe()
        self.approve_feature()
        store.FEATURE_LEDGER_PATH.unlink()
        with self.assertRaises(store.StoreError) as raised:
            store.command_feature_check(argparse.Namespace())
        self.assertIn("no ledger record approves it", str(raised.exception))

    def test_a_slug_cannot_escape_the_features_directory(self) -> None:
        for hostile in ("../escape", "Upper", "trailing-", "con", "with space"):
            with self.subTest(slug=hostile):
                with self.assertRaises(store.StoreError):
                    store.feature_path(hostile)


    # --- the store half of the drift baseline (§6) --------------------------------------
    #
    # Neither half existed, so `feature-drift` could only ever answer "unknown" — its compare
    # branch was live but unreachable. The ledger pins a DIGEST: it answers whether membership
    # moved and is portable to a machine that never held the approver's `.cache/`, which on this
    # Windows team is the normal case. The identity list that says WHICH artifacts moved stays
    # in that disposable cache, written by `knowledge_search tree`.

    def test_approval_succeeds_and_pins_null_when_no_index_is_reachable(self) -> None:
        # §6 is explicit: a governed human approval must not be blocked by a disposable cache.
        # Null is not "no change" — it is the input `feature-drift` turns into changed:"unknown".
        self.propose()
        self.describe()
        result = self.approve_feature()
        self.assertEqual("APPROVED", result["outcome"])
        record = store.read_ledger(store.FEATURE_LEDGER_PATH)[-1]
        self.assertIsNone(record["membershipDigest"])
        gap = "\n".join(result["gaps"])
        self.assertIn('changed: "unknown"', gap)
        self.assertIn("never false", gap)

    def test_a_reachable_index_pins_the_digest_it_computes(self) -> None:
        captured: dict[str, object] = {}

        def fake(boundary):
            captured["boundary"] = boundary
            return {"membershipDigest": "sha256:" + "b" * 64, "unreachable": None, "limitsHit": []}

        self.propose()
        self.describe()
        with unittest.mock.patch.object(store, "approval_membership_digest", fake):
            result = self.approve_feature()
        self.assertNotIn("gaps", result)
        record = store.read_ledger(store.FEATURE_LEDGER_PATH)[-1]
        self.assertEqual("sha256:" + "b" * 64, record["membershipDigest"])
        # The rule, not a member list, is what membership is computed from.
        self.assertEqual(["HarnessAlphaCase__c"], captured["boundary"]["anchors"])

    def test_a_truncated_membership_says_so_when_it_is_pinned(self) -> None:
        # §6 correction 3. The traversal is deterministic, so a digest over a prefix is a real
        # answer — but silence about the cut turns the later comparison into a claim about
        # artifacts nobody reached.
        def fake(_boundary):
            return {
                "membershipDigest": "sha256:" + "d" * 64, "unreachable": None,
                "limitsHit": ["maxNodes"],
            }

        self.propose()
        self.describe()
        with unittest.mock.patch.object(store, "approval_membership_digest", fake):
            result = self.approve_feature()
        gap = "\n".join(result["gaps"])
        self.assertIn("maxNodes", gap)
        self.assertIn("PREFIX", gap)
        self.assertIn("changedWithinTruncatedPrefix", gap)
        self.assertEqual(
            "sha256:" + "d" * 64,
            store.read_ledger(store.FEATURE_LEDGER_PATH)[-1]["membershipDigest"],
        )

    def test_the_digest_is_computed_on_the_baseline_traversal_and_the_established_lane(self) -> None:
        # A digest is only comparable with one recomputed the same way. `feature-drift` fixes the
        # incoming traversal, the drift depth limit and the default established lane; if either
        # half of this boundary drifts on any of them, every comparison silently becomes a
        # comparison of two different questions and reports drift that never happened.
        from scripts import knowledge_search

        seen: dict[str, object] = {}

        class FakeDocuments:
            def lane_ids(self, lanes):
                seen["lanes"] = tuple(lanes)
                return {"anything"}

        def fake_load_index():
            return FakeDocuments(), {"generation": "g"}

        def fake_compute_membership(documents, boundary, **kwargs):
            seen.update(kwargs)
            return {"membershipDigest": "sha256:" + "c" * 64, "limitsHit": []}

        with unittest.mock.patch.object(knowledge_search, "load_index", fake_load_index), \
                unittest.mock.patch.object(knowledge_search, "compute_membership", fake_compute_membership):
            membership = store.approval_membership_digest({"anchors": ["A__c"], "depth": 1})

        self.assertEqual("sha256:" + "c" * 64, membership["membershipDigest"])
        self.assertIsNone(membership["unreachable"])
        self.assertEqual(knowledge_search.BASELINE_DIRECTION, seen["direction"])
        self.assertEqual(knowledge_search.DEPTH_LIMITS["drift"], seen["depth_limit"])
        self.assertFalse(seen["include_heuristic"])
        self.assertEqual(tuple(knowledge_search.ESTABLISHED_STATES), seen["lanes"])
        self.assertEqual({"anything"}, seen["allowed"])


class ReparseScopeTests(KnowledgeStoreTests):
    """The symlink walk is the command's own cost, so it covers the tree the command writes.

    Unscoped, `feature-status` on one 500-byte file paid an rglob over the whole 15 k-entry
    artifact corpus — a corpus it does not read, cannot write, and whose symlinks are the entry
    commands' business (§6, R4)."""

    def link(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(self.temp)

    def test_a_symlink_in_the_artifact_corpus_does_not_block_a_feature_command(self) -> None:
        self.link(store.ARTIFACTS_ROOT / "Flow" / "c" / "escape.md")
        store.command_feature_propose(
            argparse.Namespace(
                slug="scheduling", name="Scheduling", anchor=["HarnessAlphaCase__c"], hub=None,
                depth=1, include=None, exclude=None, assurance_floor="source-exact", replace=False,
            )
        )
        self.assertTrue(store.feature_path("scheduling").is_file())

    def test_a_symlink_in_the_feature_tree_still_refuses_a_feature_command(self) -> None:
        self.link(store.FEATURES_ROOT / "escape.md")
        with self.assertRaises(store.StoreError) as raised:
            store.command_feature_check(argparse.Namespace())
        self.assertIn("reparse point", str(raised.exception))

    def test_a_symlink_in_the_artifact_corpus_still_refuses_an_entry_command(self) -> None:
        self.link(store.ARTIFACTS_ROOT / "Flow" / "c" / "escape.md")
        with self.assertRaises(store.StoreError):
            self.draft()


class IncrementalEntryCheckTests(KnowledgeStoreTests):
    """`--changed-since` must skip the work, and must not skip the guarantees.

    Measured at 9 000 entries, the first version skipped 9 000 of 9 000 fragment re-digests and
    saved 1 % — because the cost is YAML parsing and jsonschema validation, not the re-digest it
    skipped. Skipping the whole per-entry pass takes the same corpus from 40.4 s to 0.43 s. What
    may never be skipped is the cross-entry pass and the answer for anything git cannot vouch
    for."""

    def commit(self) -> None:
        import subprocess

        for command in (
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "entries"],
        ):
            subprocess.run(command, cwd=self.temp, check=True, capture_output=True)

    def check(self, ref=None):
        return store.command_entry_check(argparse.Namespace(changed_since=ref))

    def approved_entry(self) -> dict:
        drafted = self.draft()
        self.approve([f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
        return drafted

    def test_an_unchanged_entry_is_never_opened(self) -> None:
        # The point of the fix, asserted where it cannot be faked by a timing claim: if the
        # per-entry pass ran at all, parsing would raise.
        self.approved_entry()
        self.commit()

        def explode(_text):
            raise AssertionError("an unchanged entry was parsed")

        with unittest.mock.patch.object(store, "split_entry", explode):
            result = self.check("HEAD")
        self.assertEqual("PASS", result["outcome"])
        self.assertEqual(1, result["entriesSkipped"])
        self.assertEqual(1, result["entries"])

    def test_a_changed_entry_is_still_checked_in_full(self) -> None:
        drafted = self.approved_entry()
        self.commit()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            self.check("HEAD")
        self.assertIn("recomputed digest is not the latest ledger record", str(raised.exception))

    def test_an_untracked_entry_counts_as_changed(self) -> None:
        # `git diff` reports tracked paths only, so a brand-new entry — the commonest thing there
        # is to check — would otherwise be invisible to the ref and skipped unexamined.
        drafted = self.approved_entry()
        path = self.temp / drafted["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("right queue", "other queue"), encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.check("HEAD")

    def test_the_cross_entry_checks_still_cover_skipped_entries(self) -> None:
        # §0.3: "a per-entry skip would silently destroy them". The skipped entry contributes its
        # identity — read off its path — so a second file claiming that identity still collides.
        drafted = self.approved_entry()
        self.commit()
        original = self.temp / drafted["path"]
        impostor = original.with_name("Impostor.md")
        impostor.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            result = self.check("HEAD")
            self.fail(f"the collision was not detected: {result}")
        self.assertIn(f"identity {drafted['identity']} resolves to two files", str(raised.exception))

    def test_an_unanswerable_ref_degrades_to_a_full_check(self) -> None:
        self.approved_entry()
        self.commit()
        result = self.check("no-such-ref")
        self.assertEqual(0, result["entriesSkipped"])
        self.assertIn("git could not report changes", result["gap"])

    def test_full_is_the_default_and_skips_nothing(self) -> None:
        self.approved_entry()
        self.commit()
        result = self.check()
        self.assertNotIn("entriesSkipped", result)
        self.assertNotIn("changedSince", result)

    def test_entry_check_writes_nothing(self) -> None:
        # A read-only gate that acquired a writer would put a new integrity hole inside the
        # command whose job is integrity.
        self.approved_entry()
        self.commit()
        before = {path: path.read_bytes() for path in sorted(self.temp.rglob("*")) if path.is_file()}
        self.check("HEAD")
        after = {path: path.read_bytes() for path in sorted(self.temp.rglob("*")) if path.is_file()}
        self.assertEqual(before, after)


class PathDerivedIdentityTests(KnowledgeStoreTests):
    """An identity read off a path is what makes the whole-entry skip possible — and it is only
    allowed when the path can prove it. `entry_path()` derives the path FROM the identity, so
    the inverse is exact for plain ASCII names and lossy for everything else; the lossy cases
    must fall back to parsing rather than guess."""

    def test_a_plain_entry_path_round_trips_to_its_identity(self) -> None:
        drafted = self.draft()
        path = self.temp / drafted["path"]
        self.assertEqual(drafted["identity"], store.identity_from_entry_path(path))

    def test_an_escaped_or_truncated_name_refuses_to_answer(self) -> None:
        for full_name in ("Odd Name__c", "Ünicode__c", "A" * 120):
            with self.subTest(fullName=full_name):
                path = store.entry_path("Flow", None, full_name)
                self.assertIsNone(
                    store.identity_from_entry_path(path),
                    f"{full_name} claimed an identity its path cannot prove",
                )

    def test_a_path_outside_the_artifact_corpus_refuses_to_answer(self) -> None:
        self.assertIsNone(store.identity_from_entry_path(store.FEATURES_ROOT / "scheduling.md"))
        self.assertIsNone(store.identity_from_entry_path(store.ARTIFACTS_ROOT / "Flow" / "loose.md"))
