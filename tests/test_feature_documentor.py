from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.force_app_knowledge import ForceAppKnowledge, KnowledgeBuildError, feature_slug
from scripts.knowledge_registry import KnowledgeRegistry


ROOT = Path(__file__).resolve().parents[1]
OBSERVED_AT = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def obj(label: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<label>{label}</label><pluralLabel>{label}s</pluralLabel>"
        "<deploymentStatus>Deployed</deploymentStatus><sharingModel>ReadWrite</sharingModel>"
        "</CustomObject>\n"
    )


def lookup(name: str, target: str, field_type: str = "Lookup") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<fullName>{name}</fullName><label>{name}</label><type>{field_type}</type>"
        f"<referenceTo>{target}</referenceTo><relationshipName>{name}Rel</relationshipName>"
        "</CustomField>\n"
    )


FLOW_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
    "<label>HarnessEngagement After Save</label><status>Active</status>"
    "<processType>AutoLaunchedFlow</processType>"
    "<start><object>HarnessEngagement__c</object><triggerType>RecordAfterSave</triggerType>"
    "<recordTriggerType>CreateAndUpdate</recordTriggerType></start></Flow>\n"
)


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class FeatureCrawlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="feature-documentor-")
        self.root = Path(self.temporary.name)
        base = self.root / "force-app/main/default"
        # Anchor object with an outbound lookup to a standard object.
        write(base / "objects/HarnessEngagement__c/HarnessEngagement__c.object-meta.xml", obj("HarnessEngagement"))
        write(base / "objects/HarnessEngagement__c/fields/Account__c.field-meta.xml", lookup("Account__c", "Account"))
        # A different object with an inbound lookup back to the anchor.
        write(base / "objects/HarnessInvoice__c/HarnessInvoice__c.object-meta.xml", obj("HarnessInvoice"))
        write(base / "objects/HarnessInvoice__c/fields/HarnessEngagement__c.field-meta.xml", lookup("HarnessEngagement__c", "HarnessEngagement__c"))
        # An unrelated object that must not be pulled into the boundary at depth 1.
        write(base / "objects/Skill__c/Skill__c.object-meta.xml", obj("Skill"))
        write(base / "objects/Skill__c/fields/Level__c.field-meta.xml", lookup("Level__c", "Account"))
        # An automation that operates on the anchor.
        write(base / "flows/HarnessEngagement_After_Save.flow-meta.xml", FLOW_XML)

        (self.root / "schemas").mkdir()
        for name in (
            "knowledge-claim.schema.json",
            "knowledge-evidence.schema.json",
            "force-app-knowledge-inventory.schema.json",
            "force-app-knowledge-draft-manifest.schema.json",
            "force-app-knowledge-worklist.schema.json",
            "feature-crawl.schema.json",
        ):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "config").mkdir()
        shutil.copy2(ROOT / "config/knowledge-policy.json", self.root / "config/knowledge-policy.json")
        (self.root / ".ai/knowledge/claims").mkdir(parents=True)
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "fixture@example.invalid"],
            ["git", "config", "user.name", "Fixture"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=self.root, check=True)
        self.builder = ForceAppKnowledge(self.root)
        self.builder.inventory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_crawl_finds_outbound_and_reverse_relations_within_depth(self) -> None:
        crawl = self.builder.feature_crawl("HarnessBilling", ["HarnessEngagement__c"], depth=1)
        self.assertEqual("harnessbilling", crawl["slug"])
        # Boundary spans the anchor, the object it references, and the object referencing it.
        self.assertIn("HarnessEngagement__c", crawl["objects"])
        self.assertIn("HarnessInvoice__c", crawl["objects"])
        self.assertIn("Account", crawl["objects"])
        # The unrelated object stays out of the boundary.
        self.assertNotIn("Skill__c", crawl["objects"])

        outbound = crawl["relations"]["outbound"]
        self.assertIn(
            {"fromObject": "HarnessEngagement__c", "field": "Account__c", "toObject": "Account", "type": "Lookup"},
            outbound,
        )
        inbound = crawl["relations"]["inbound"]
        self.assertIn(
            {"fromObject": "HarnessInvoice__c", "field": "HarnessEngagement__c", "toObject": "HarnessEngagement__c", "type": "Lookup"},
            inbound,
        )
        automation_ids = {item["id"] for item in crawl["automations"]}
        self.assertIn("Flow:HarnessEngagement_After_Save", automation_ids)
        self.assertIn("Flow:HarnessEngagement_After_Save", crawl["componentIds"])
        self.assertNotIn("CustomObject:Skill__c", crawl["componentIds"])
        # A crawl file is persisted for the draft/dossier steps.
        self.assertTrue(self.builder.crawl_path("harnessbilling").is_file())

    def test_feature_draft_tags_claims_and_writes_dossier(self) -> None:
        self.builder.feature_crawl("HarnessBilling", ["HarnessEngagement__c"], depth=1)
        result = self.builder.feature_draft("HarnessBilling", OBSERVED_AT)
        self.assertGreater(result["manifest"]["claimCount"], 0)
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in result["manifest"]["bundles"]
            if "claimFile" in bundle
        ]
        # Every drafted claim carries the feature tag.
        for claim in claims:
            self.assertEqual(["HarnessBilling"], claim["feature"])
        # The anchor object's existence claim is tagged and present.
        object_claims = [c for c in claims if c["claimType"] == "object-existence"]
        self.assertTrue(any(c["subject"]["identity"] == "HarnessEngagement__c" for c in object_claims))
        # The unrelated object never gets a claim.
        self.assertFalse(any(c["subject"]["identity"] == "Skill__c" for c in object_claims))

        dossier = self.root / result["dossierPath"]
        self.assertTrue(dossier.is_file())
        text = dossier.read_text(encoding="utf-8")
        self.assertIn("# Feature Dossier — HarnessBilling", text)
        self.assertIn("### Inbound", text)
        self.assertIn("HarnessInvoice__c", text)
        self.assertIn("## Automations", text)
        self.assertIn("HarnessEngagement_After_Save", text)

    def test_crawl_requires_an_anchor(self) -> None:
        with self.assertRaisesRegex(KnowledgeBuildError, "at least one anchor"):
            self.builder.feature_crawl("HarnessBilling", [])

    def test_hub_stop_list_prevents_expansion(self) -> None:
        # With HarnessInvoice__c on the hub list it stays a relation endpoint but is not pulled in.
        crawl = self.builder.feature_crawl("HarnessBilling", ["HarnessEngagement__c"], depth=1, hubs=["HarnessInvoice__c"])
        self.assertNotIn("HarnessInvoice__c", crawl["objects"])
        self.assertIn("HarnessInvoice__c", crawl["hubStopList"])


APPROVAL_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<ApprovalProcess xmlns="http://soap.sforce.com/2006/04/metadata">'
    "<active>true</active><label>HarnessEngagement Approval</label>"
    "<entryCriteria><criteriaItems><field>HarnessEngagement__c.Name</field></criteriaItems></entryCriteria>"
    "<approvalStep><name>Step_1</name></approvalStep></ApprovalProcess>\n"
)


class DossierDescriptionTests(unittest.TestCase):
    """The dossier must name the remedy that matches the state it found.

    The fallback used to print "no Knowledge Entry and no drafted claim" against a component
    whose entry was on disk and merely undescribed — telling a human to author a file that
    already exists instead of running `entry-describe`. Four states, four sentences, and a
    reader who follows any of them gets a command that works.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="dossier-description-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        base = self.root / "force-app/main/default"
        write(base / "objects/HarnessEngagement__c/HarnessEngagement__c.object-meta.xml", obj("HarnessEngagement"))
        # Flow has a Knowledge Entry home; ApprovalProcess does not. Both are drafted a
        # component-description claim, so both exercise the entry-less half of the fallback.
        write(base / "flows/HarnessEngagement_After_Save.flow-meta.xml", FLOW_XML)
        write(
            base
            / "approvalProcesses/HarnessEngagement__c.HarnessEngagement_Approval.approvalProcess-meta.xml",
            APPROVAL_XML,
        )
        shutil.copytree(ROOT / "schemas", self.root / "schemas")
        (self.root / "config").mkdir()
        shutil.copy2(ROOT / "config/knowledge-policy.json", self.root / "config/knowledge-policy.json")
        (self.root / "config/harness.local.json").write_text(
            '{"knowledge": {"chatReviewer": "Reviewer Person"}}', encoding="utf-8"
        )
        (self.root / ".ai/knowledge/claims").mkdir(parents=True)
        self.purpose = self.root / "purpose.md"
        self.purpose.write_text("Stamps the engagement summary after save.", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=self.root, check=True, capture_output=True)
        self.builder = ForceAppKnowledge(self.root)
        self.builder.inventory()
        self.builder.feature_crawl("HarnessBilling", ["HarnessEngagement__c"], depth=1)
        self.drafted = self.builder.feature_draft("HarnessBilling", OBSERVED_AT)

    def dossier(self) -> str:
        """Re-render from the persisted crawl so each state is read off the same boundary."""

        import json

        crawl = json.loads(self.builder.crawl_path("harnessbilling").read_text(encoding="utf-8"))
        self.builder.render_dossier(crawl, self.drafted["manifest"])
        return (self.root / self.drafted["dossierPath"]).read_text(encoding="utf-8")

    def flow_row(self, text: str) -> str:
        return next(line for line in text.splitlines() if "`HarnessEngagement_After_Save`" in line)

    def approve_flow_entry(self, body: str | None = None) -> None:
        """Approve the Flow entry through the governed commands, optionally with a blank Purpose."""

        import argparse

        import scripts.knowledge_store as store

        with store.rooted(self.root):
            drafted = store.command_entry_draft(
                argparse.Namespace(
                    metadata_type="Flow",
                    full_name="HarnessEngagement_After_Save",
                    namespace=None,
                    purpose_file=str(self.purpose),
                    source_api_version="64.0",
                    candidate_keyword=None,
                )
            )
            store.command_entry_approve(
                argparse.Namespace(entry=[f"{drafted['identity']}:{drafted['reviewedContentDigest']}"])
            )
            if body is None:
                return
            path = self.root / drafted["path"]
            frontmatter, _previous = store.split_entry(path.read_text(encoding="utf-8"))
            digest = store.reviewed_content_digest(frontmatter, body)
            store.atomic_write(path, store.render_entry(frontmatter, body))
            store.command_entry_approve(argparse.Namespace(entry=[f"{drafted['identity']}:{digest}"]))

    def describe_claim(self, identity: str, description: str) -> None:
        """Replace the drafted description sentinel with real prose."""

        for bundle in self.drafted["manifest"]["bundles"]:
            path = self.root / bundle.get("claimFile", "")
            if not bundle.get("claimFile"):
                continue
            claim = yaml.safe_load(path.read_text(encoding="utf-8"))
            if claim["claimType"] != "component-description" or claim["subject"]["identity"] != identity:
                continue
            claim["assertion"]["value"]["description"] = description
            path.write_text(yaml.safe_dump(claim, sort_keys=True), encoding="utf-8")
            return
        self.fail(f"no drafted component-description claim for {identity}")

    def test_no_entry_and_no_claim_names_the_type_appropriate_remedy(self) -> None:
        text = self.dossier()
        self.assertIn(
            "_no description: no Knowledge Entry and no drafted claim — "
            "run `entry-draft` then `entry-describe`_",
            self.flow_row(text),
        )
        # A type with no entry home must never be told to run `entry-draft`: the command
        # refuses it, so the instruction would fail in the reader's hands.
        approval = next(
            line for line in text.splitlines() if "HarnessEngagement_Approval`" in line
        )
        self.assertIn("this type has no entry home; describe it in a claim", approval)
        self.assertNotIn("entry-draft", approval)

    def test_a_described_entry_renders_its_purpose_with_no_remedy(self) -> None:
        self.approve_flow_entry()
        row = self.flow_row(self.dossier())
        self.assertIn("Stamps the engagement summary after save.", row)
        self.assertNotIn("entry-describe", row)
        self.assertNotIn("no Knowledge Entry", row)

    def test_an_undescribed_entry_sends_the_reader_to_entry_describe(self) -> None:
        # The audit's reproduction: blank one approved entry's Purpose.
        self.approve_flow_entry(body="## Purpose\n")
        row = self.flow_row(self.dossier())
        self.assertIn(
            "_no description: the approved-current Knowledge Entry has no Purpose — "
            "run `entry-describe`_",
            row,
        )
        # The old text sent them to author an entry that is already on disk.
        self.assertNotIn("no Knowledge Entry and no drafted claim", row)
        self.assertNotIn("entry-draft", row)

    def test_a_claim_covers_an_undescribed_entry_but_still_names_the_gap(self) -> None:
        self.describe_claim("Flow:HarnessEngagement_After_Save", "Drafted claim prose.")
        self.approve_flow_entry(body="## Purpose\n")
        row = self.flow_row(self.dossier())
        self.assertIn("Drafted claim prose.", row)
        self.assertIn("approved-current Knowledge Entry has no Purpose: run `entry-describe`", row)


class FeatureIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="feature-index-")
        self.root = Path(self.temporary.name)
        (self.root / "schemas").mkdir()
        for name in ("knowledge-claim.schema.json", "knowledge-claims-index.schema.json"):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / ".ai/knowledge/claims").mkdir(parents=True)
        self.registry = KnowledgeRegistry(self.root, current_time=OBSERVED_AT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def claim(self, claim_id: str, features: list[str]) -> dict:
        return {
            "schemaVersion": 3,
            "claimId": claim_id,
            "revision": 1,
            "domain": "object-descriptions",
            "claimType": "object-existence",
            "subject": {"kind": "object", "identity": "Order__c"},
            "assertion": {"predicate": "exists-in-accessible-schema", "value": True},
            "statement": "Fixture claim.",
            "polarity": "positive",
            "status": "proposed",
            "assurance": "observed",
            "scope": {
                "environment": "not-applicable",
                "orgKey": None,
                "packageNamespace": None,
                "packageKey": None,
                "packageVersion": None,
                "repositoryCommit": None,
            },
            "evidenceRefs": ["KEVD-FIXTURE-0000000001"],
            "reviewRef": None,
            "observedAt": "2026-07-10T12:00:00Z",
            "verifiedAt": None,
            "reviewBy": "2026-08-10T12:00:00Z",
            "sensitivity": "internal-sanitized",
            "keywords": [],
            "candidateKeywords": [],
            "feature": features,
            "limitations": [],
            "supersedes": [],
            "supersededBy": None,
            "contradicts": [],
            "relatedClaims": [],
        }

    def test_feature_map_groups_claims_by_feature(self) -> None:
        claims = [
            self.claim("KCLM-ORDER-EXISTS-A0000000001", ["HarnessBilling"]),
            self.claim("KCLM-ORDER-EXISTS-B0000000002", ["HarnessBilling", "Revenue"]),
        ]
        rendered = self.registry.rendered_feature_map(claims, OBSERVED_AT)
        self.assertIn("## HarnessBilling", rendered)
        self.assertIn("## Revenue", rendered)
        self.assertIn("KCLM-ORDER-EXISTS-A0000000001", rendered)
        # Proposed claims are never presented as effective facts.
        self.assertIn("| no |", rendered)

    def test_empty_feature_map_has_empty_state(self) -> None:
        rendered = self.registry.rendered_feature_map([self.claim("KCLM-X-0000000001", [])], OBSERVED_AT)
        self.assertIn("_No feature-tagged claims are indexed._", rendered)

    def test_index_row_carries_feature(self) -> None:
        claim = self.claim("KCLM-ORDER-EXISTS-A0000000001", ["HarnessBilling"])
        path = self.registry.root / ".ai/knowledge/claims/KCLM-ORDER-EXISTS-A0000000001.yaml"
        write(path, yaml.safe_dump(claim))
        row = self.registry.claims_index_row(claim, path, OBSERVED_AT)
        self.assertEqual(["HarnessBilling"], row["feature"])


class FeatureSlugTests(unittest.TestCase):
    def test_slug_normalizes(self) -> None:
        self.assertEqual("harnessbilling-events", feature_slug("  HarnessBilling  Events!! "))

    def test_slug_rejects_empty(self) -> None:
        with self.assertRaises(KnowledgeBuildError):
            feature_slug("!!!")


if __name__ == "__main__":
    unittest.main()
