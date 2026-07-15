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
    "<label>Engagement After Save</label><status>Active</status>"
    "<processType>AutoLaunchedFlow</processType>"
    "<start><object>Engagement__c</object><triggerType>RecordAfterSave</triggerType>"
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
        write(base / "objects/Engagement__c/Engagement__c.object-meta.xml", obj("Engagement"))
        write(base / "objects/Engagement__c/fields/Account__c.field-meta.xml", lookup("Account__c", "Account"))
        # A different object with an inbound lookup back to the anchor.
        write(base / "objects/Invoice__c/Invoice__c.object-meta.xml", obj("Invoice"))
        write(base / "objects/Invoice__c/fields/Engagement__c.field-meta.xml", lookup("Engagement__c", "Engagement__c"))
        # An unrelated object that must not be pulled into the boundary at depth 1.
        write(base / "objects/Skill__c/Skill__c.object-meta.xml", obj("Skill"))
        write(base / "objects/Skill__c/fields/Level__c.field-meta.xml", lookup("Level__c", "Account"))
        # An automation that operates on the anchor.
        write(base / "flows/Engagement_After_Save.flow-meta.xml", FLOW_XML)

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
        crawl = self.builder.feature_crawl("Billing", ["Engagement__c"], depth=1)
        self.assertEqual("billing", crawl["slug"])
        # Boundary spans the anchor, the object it references, and the object referencing it.
        self.assertIn("Engagement__c", crawl["objects"])
        self.assertIn("Invoice__c", crawl["objects"])
        self.assertIn("Account", crawl["objects"])
        # The unrelated object stays out of the boundary.
        self.assertNotIn("Skill__c", crawl["objects"])

        outbound = crawl["relations"]["outbound"]
        self.assertIn(
            {"fromObject": "Engagement__c", "field": "Account__c", "toObject": "Account", "type": "Lookup"},
            outbound,
        )
        inbound = crawl["relations"]["inbound"]
        self.assertIn(
            {"fromObject": "Invoice__c", "field": "Engagement__c", "toObject": "Engagement__c", "type": "Lookup"},
            inbound,
        )
        automation_ids = {item["id"] for item in crawl["automations"]}
        self.assertIn("Flow:Engagement_After_Save", automation_ids)
        self.assertIn("Flow:Engagement_After_Save", crawl["componentIds"])
        self.assertNotIn("CustomObject:Skill__c", crawl["componentIds"])
        # A crawl file is persisted for the draft/dossier steps.
        self.assertTrue(self.builder.crawl_path("billing").is_file())

    def test_feature_draft_tags_claims_and_writes_dossier(self) -> None:
        self.builder.feature_crawl("Billing", ["Engagement__c"], depth=1)
        result = self.builder.feature_draft("Billing", OBSERVED_AT)
        self.assertGreater(result["manifest"]["claimCount"], 0)
        claims = [
            yaml.safe_load((self.root / bundle["claimFile"]).read_text(encoding="utf-8"))
            for bundle in result["manifest"]["bundles"]
            if "claimFile" in bundle
        ]
        # Every drafted claim carries the feature tag.
        for claim in claims:
            self.assertEqual(["Billing"], claim["feature"])
        # The anchor object's existence claim is tagged and present.
        object_claims = [c for c in claims if c["claimType"] == "object-existence"]
        self.assertTrue(any(c["subject"]["identity"] == "Engagement__c" for c in object_claims))
        # The unrelated object never gets a claim.
        self.assertFalse(any(c["subject"]["identity"] == "Skill__c" for c in object_claims))

        dossier = self.root / result["dossierPath"]
        self.assertTrue(dossier.is_file())
        text = dossier.read_text(encoding="utf-8")
        self.assertIn("# Feature Dossier — Billing", text)
        self.assertIn("### Inbound", text)
        self.assertIn("Invoice__c", text)
        self.assertIn("## Automations", text)
        self.assertIn("Engagement_After_Save", text)

    def test_crawl_requires_an_anchor(self) -> None:
        with self.assertRaisesRegex(KnowledgeBuildError, "at least one anchor"):
            self.builder.feature_crawl("Billing", [])

    def test_hub_stop_list_prevents_expansion(self) -> None:
        # With Invoice__c on the hub list it stays a relation endpoint but is not pulled in.
        crawl = self.builder.feature_crawl("Billing", ["Engagement__c"], depth=1, hubs=["Invoice__c"])
        self.assertNotIn("Invoice__c", crawl["objects"])
        self.assertIn("Invoice__c", crawl["hubStopList"])


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
            self.claim("KCLM-ORDER-EXISTS-A0000000001", ["Billing"]),
            self.claim("KCLM-ORDER-EXISTS-B0000000002", ["Billing", "Revenue"]),
        ]
        rendered = self.registry.rendered_feature_map(claims, OBSERVED_AT)
        self.assertIn("## Billing", rendered)
        self.assertIn("## Revenue", rendered)
        self.assertIn("KCLM-ORDER-EXISTS-A0000000001", rendered)
        # Proposed claims are never presented as effective facts.
        self.assertIn("| no |", rendered)

    def test_empty_feature_map_has_empty_state(self) -> None:
        rendered = self.registry.rendered_feature_map([self.claim("KCLM-X-0000000001", [])], OBSERVED_AT)
        self.assertIn("_No feature-tagged claims are indexed._", rendered)

    def test_index_row_carries_feature(self) -> None:
        claim = self.claim("KCLM-ORDER-EXISTS-A0000000001", ["Billing"])
        path = self.registry.root / ".ai/knowledge/claims/KCLM-ORDER-EXISTS-A0000000001.yaml"
        write(path, yaml.safe_dump(claim))
        row = self.registry.claims_index_row(claim, path, OBSERVED_AT)
        self.assertEqual(["Billing"], row["feature"])


class FeatureSlugTests(unittest.TestCase):
    def test_slug_normalizes(self) -> None:
        self.assertEqual("billing-events", feature_slug("  Billing  Events!! "))

    def test_slug_rejects_empty(self) -> None:
        with self.assertRaises(KnowledgeBuildError):
            feature_slug("!!!")


if __name__ == "__main__":
    unittest.main()
