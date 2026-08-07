"""Feature Knowledge v2 tests (master plan §23, unit level).

Interactive multi-turn authoring runs live in harness-lab; everything mechanical is pinned
here: the authority matrix, executor-owned ids, batch fail-closure, taxonomy keywords,
digest stability, claim-level citation with transitive binding drift, and the guard that
storage families and feature layers stay consciously different vocabularies (RB-2).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import feature_knowledge as fk  # noqa: E402
from scripts import knowledge_store as store  # noqa: E402


def ns(**kw):
    return argparse.Namespace(**kw)


RECEIPT = {
    "reviewedContentDigest": "sha256:" + "a" * 64,
    "factsDigest": "sha256:" + "b" * 64,
    "sourceTreeDigest": "sha256:" + "c" * 64,
    "profile": "salesforce.custom-object@1",
}


class FeatureFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp()).resolve()
        (self.temp / ".ai/knowledge").mkdir(parents=True)
        (self.temp / "config").mkdir()
        (self.temp / "config/harness.local.json").write_text(
            json.dumps({"knowledge": {"chatReviewer": "Reviewer Person"}}), encoding="utf-8"
        )
        (self.temp / ".ai/knowledge/keyword-taxonomy.md").write_text(
            "## Terms\n- billing\n- invoicing\n", encoding="utf-8"
        )
        self._rooted = store.rooted(self.temp)
        self._rooted.__enter__()
        self.addCleanup(self._rooted.__exit__, None, None, None)
        self.receipts = {"CustomObject:c:Invoice__c": dict(RECEIPT)}
        self._orig_resolver = store._feature_binding_resolver

        def stub(entry_id):
            if entry_id not in self.receipts:
                raise store.StoreError(f"binding target {entry_id} has no Knowledge Entry")
            return dict(self.receipts[entry_id])

        store._feature_binding_resolver = stub
        self.addCleanup(setattr, store, "_feature_binding_resolver", self._orig_resolver)

    def record(self, operations, expected_version=None, slug="invoice-finance"):
        if expected_version is None:
            frontmatter, _, _ = store._load_feature(slug)
            expected_version = frontmatter["draft"]["version"]
        ops_path = self.temp / "ops.json"
        ops_path.write_text(json.dumps({"operations": operations}), encoding="utf-8")
        return store.command_feature_record(
            ns(slug=slug, expected_version=expected_version, operations_file=str(ops_path))
        )

    def open_and_seed(self):
        store.command_feature_open(ns(slug="invoice-finance", name="Invoice Finance"))
        return self.record([
            {"kind": "binding", "op": "bind", "data": {"entryId": "CustomObject:c:Invoice__c"}},
            {"kind": "node", "op": "set", "data": {
                "kind": "artifact", "artifactId": "CustomObject:c:Invoice__c",
                "featureLayer": "domain-data", "role": "aggregate-root"}},
            {"kind": "claim", "op": "set", "data": {
                "type": "data-relationship", "layer": "domain-data", "authority": "source-exact",
                "text": "Invoice aggregates lines.", "evidenceRefs": ["FB-001"],
                "citationPolicy": "citable-after-approval"}},
            {"kind": "claim", "op": "set", "data": {
                "type": "feature-purpose", "layer": "domain-data", "authority": "human-attested",
                "text": "Bills delivered work.", "citationPolicy": "citable-after-approval"}},
            {"kind": "section", "op": "replace", "data": {"name": "Purpose and boundary", "text": "Bills."}},
            {"kind": "section", "op": "replace", "data": {"name": "Domain and data model", "text": "Invoice__c."}},
            {"kind": "section", "op": "replace", "data": {"name": "Evidence map", "text": "FB-001."}},
        ])

    def approve(self, slug="invoice-finance"):
        review = store.command_feature_review(ns(slug=[slug]))
        pin = review["approveCommand"].split('--feature "')[1].rstrip('"')
        return store.command_feature_approve(ns(feature=[pin]))


class AuthorityMatrixTests(FeatureFixture):
    def test_human_attestation_cannot_launder_technical_claims(self) -> None:
        self.open_and_seed()
        with self.assertRaises(store.StoreError) as ctx:
            self.record([{"kind": "claim", "op": "set", "data": {
                "type": "calculation-lineage", "layer": "processing", "authority": "human-attested",
                "text": "X calculates Y.", "citationPolicy": "citable-after-approval"}}])
        self.assertIn("not authority", str(ctx.exception))

    def test_heuristic_material_is_never_citable(self) -> None:
        self.open_and_seed()
        with self.assertRaises(store.StoreError):
            self.record([{"kind": "claim", "op": "set", "data": {
                "type": "component-role", "layer": "code", "authority": "source-derived-heuristic",
                "text": "Guess.", "citationPolicy": "citable-after-approval"}}])

    def test_source_exact_requires_a_binding(self) -> None:
        self.open_and_seed()
        with self.assertRaises(store.StoreError):
            self.record([{"kind": "claim", "op": "set", "data": {
                "type": "access-boundary", "layer": "access", "authority": "source-exact",
                "text": "No binding.", "citationPolicy": "citable-after-approval"}}])


class ExecutorTests(FeatureFixture):
    def test_ids_are_executor_allocated_and_monotonic(self) -> None:
        result = self.open_and_seed()
        self.assertIn("add FN-001", result["applied"])
        self.assertIn("add FC-001", result["applied"])
        result = self.record([{"kind": "meta", "op": "add-question", "data": {"question": "Who owns tax?"}}])
        self.assertIn("add FQ-001", result["applied"])

    def test_tombstoned_ids_are_never_reassigned(self) -> None:
        self.open_and_seed()
        self.record([{"kind": "claim", "op": "withdraw", "data": {"id": "FC-002"}}])
        result = self.record([{"kind": "claim", "op": "set", "data": {
            "type": "invariant", "layer": "domain-data", "authority": "human-attested",
            "text": "One invoice per order.", "citationPolicy": "citable-after-approval"}}])
        self.assertIn("add FC-003", result["applied"])  # not FC-002 again

    def test_stale_expected_version_is_refused(self) -> None:
        self.open_and_seed()
        with self.assertRaises(store.StoreError) as ctx:
            self.record([{"kind": "meta", "op": "set", "data": {"name": "X"}}], expected_version=0)
        self.assertIn("stale draft version", str(ctx.exception))

    def test_a_rejected_batch_changes_nothing(self) -> None:
        self.open_and_seed()
        before = fk.feature_path("invoice-finance").read_text(encoding="utf-8")
        with self.assertRaises(store.StoreError):
            self.record([
                {"kind": "meta", "op": "set", "data": {"name": "Renamed"}},
                {"kind": "claim", "op": "set", "data": {
                    "type": "data-relationship", "layer": "domain-data",
                    "authority": "human-attested", "text": "laundered",
                    "citationPolicy": "citable-after-approval"}},
            ])
        self.assertEqual(before, fk.feature_path("invoice-finance").read_text(encoding="utf-8"))

    def test_binding_comes_from_the_live_store_never_pasted(self) -> None:
        store.command_feature_open(ns(slug="invoice-finance", name="Invoice Finance"))
        with self.assertRaises(store.StoreError):
            self.record([{"kind": "binding", "op": "bind",
                          "data": {"entryId": "CustomObject:c:Nope__c"}}])

    def test_keywords_are_taxonomy_validated(self) -> None:
        self.open_and_seed()
        self.record([{"kind": "meta", "op": "set", "data": {"keywords": ["billing"]}}])
        with self.assertRaises(store.StoreError):
            self.record([{"kind": "meta", "op": "set", "data": {"keywords": ["not-a-term"]}}])

    def test_material_edit_returns_an_approved_feature_to_draft(self) -> None:
        self.open_and_seed()
        self.approve()
        self.record([{"kind": "meta", "op": "set", "data": {"name": "Invoice Finance II"}}])
        lane = store.command_feature_status(ns(slug="invoice-finance"))["features"][0]
        self.assertEqual("draft", lane["lane"])


class ApprovalTests(FeatureFixture):
    def test_approval_pins_the_digest_and_appends_the_ledger(self) -> None:
        self.open_and_seed()
        result = self.approve()
        self.assertEqual("APPROVED", result["outcome"])
        lane = store.command_feature_status(ns(slug="invoice-finance"))["features"][0]
        self.assertEqual("approved-current", lane["lane"])
        records = store.read_ledger(store.FEATURE_LEDGER_PATH)
        self.assertEqual(1, len(records))
        for key in ("reviewedContentDigest", "modelDigest", "semanticsDigest"):
            self.assertIn(key, records[0])

    def test_a_stale_pin_is_refused(self) -> None:
        self.open_and_seed()
        review = store.command_feature_review(ns(slug=["invoice-finance"]))
        pin = review["approveCommand"].split('--feature "')[1].rstrip('"')
        self.record([{"kind": "meta", "op": "set", "data": {"name": "Moved"}}])
        with self.assertRaises(store.StoreError) as ctx:
            store.command_feature_approve(ns(feature=[pin]))
        self.assertIn("digest pin mismatch", str(ctx.exception))

    def test_unfilled_core_sections_block_approval_but_not_the_draft_lane(self) -> None:
        store.command_feature_open(ns(slug="invoice-finance", name="Invoice Finance"))
        lane = store.command_feature_status(ns(slug="invoice-finance"))["features"][0]
        self.assertEqual("draft", lane["lane"])  # F-3 posture: outstanding work, not corruption
        review = store.command_feature_review(ns(slug=["invoice-finance"]))
        self.assertIn("blocked", review)

    def test_check_passes_over_drafts_and_fails_on_ledger_orphan(self) -> None:
        self.open_and_seed()
        self.assertEqual("PASS", store.command_feature_check(ns())["outcome"])
        self.approve()
        fk.feature_path("invoice-finance").unlink()
        with self.assertRaises(store.StoreError) as ctx:
            store.command_feature_check(ns())
        self.assertIn("no feature file exists", str(ctx.exception))


class CitationTests(FeatureFixture):
    def verify(self, claims):
        return store.command_feature_verify_citations(
            ns(slug="invoice-finance", claim=claims, envelope=None)
        )["citations"][0]

    def test_current_claim_returns_a_receipt(self) -> None:
        self.open_and_seed()
        self.approve()
        row = self.verify(["FC-001"])
        self.assertEqual("current", row["verdict"])
        self.assertEqual(["FC-001"], row["receipt"]["claimIds"])

    def test_transitive_binding_drift_blocks_the_dependent_claim(self) -> None:
        self.open_and_seed()
        # FC-003 depends on FC-001 which carries FB-001 — drift must travel the chain.
        self.record([{"kind": "claim", "op": "set", "data": {
            "type": "invariant", "layer": "domain-data", "authority": "human-attested",
            "text": "Totals reconcile.", "dependsOn": ["FC-001"],
            "citationPolicy": "citable-after-approval"}}])
        self.approve()
        self.receipts["CustomObject:c:Invoice__c"]["reviewedContentDigest"] = "sha256:" + "f" * 64
        row = self.verify(["FC-003"])
        self.assertEqual("drifted", row["verdict"])

    def test_unrelated_drift_degrades_but_still_cites(self) -> None:
        self.open_and_seed()
        self.approve()
        self.receipts["CustomObject:c:Invoice__c"]["reviewedContentDigest"] = "sha256:" + "f" * 64
        row = self.verify(["FC-002"])  # human-attested purpose, no bindings
        self.assertEqual("degraded", row["verdict"])
        self.assertIn("receipt", row)

    def test_never_citable_and_unknown_ids_fail_explicitly(self) -> None:
        self.open_and_seed()
        self.record([{"kind": "claim", "op": "set", "data": {
            "type": "component-role", "layer": "code", "authority": "source-derived-heuristic",
            "text": "Guess.", "citationPolicy": "never-citable"}}])
        self.approve()
        self.assertEqual("not-citable", self.verify(["FC-003"])["verdict"])
        self.assertEqual("unknown-id", self.verify(["FC-099"])["verdict"])

    def test_envelope_mode_detects_superseded_digests(self) -> None:
        self.open_and_seed()
        self.approve()
        receipt = self.verify(["FC-002"])["receipt"]
        envelope = {"featureRefs": [receipt, {**receipt, "modelDigest": "sha256:" + "9" * 64}]}
        env_path = self.temp / "env.json"
        env_path.write_text(json.dumps(envelope), encoding="utf-8")
        result = store.command_feature_verify_citations(ns(slug=None, claim=None, envelope=str(env_path)))
        self.assertEqual(["current", "superseded"], [c["verdict"] for c in result["citations"]])

    def test_a_draft_is_never_citable(self) -> None:
        self.open_and_seed()
        self.assertEqual("not-approved", self.verify(["FC-001"])["verdict"])


class ReadSurfaceTests(FeatureFixture):
    def test_search_serves_only_approved_features_and_is_not_citable(self) -> None:
        self.open_and_seed()
        result = store.command_feature_search(ns(text=None, artifact_id=None, layer=None,
                                                 role=None, claim_type=None, top=10))
        self.assertEqual([], result["hits"])
        self.assertEqual(1, result["draftCount"])
        self.approve()
        result = store.command_feature_search(ns(text="delivered", artifact_id=None, layer=None,
                                                 role=None, claim_type=None, top=10))
        self.assertEqual(1, len(result["hits"]))
        self.assertIn("never citable", result["note"])
        by_artifact = store.command_feature_search(ns(text=None, artifact_id="CustomObject:c:Invoice__c",
                                                      layer=None, role=None, claim_type=None, top=10))
        self.assertEqual(1, len(by_artifact["hits"]))

    def test_context_refuses_drafts_and_reports_binding_health(self) -> None:
        self.open_and_seed()
        self.assertEqual("NOT_APPROVED",
                         store.command_feature_context(ns(slug="invoice-finance"))["outcome"])
        self.approve()
        context = store.command_feature_context(ns(slug="invoice-finance"))
        self.assertEqual("CONTEXT", context["outcome"])
        self.assertEqual({"FB-001": "current"}, context["bindingHealth"])
        self.assertIn("not a citation receipt", context["note"])


class SeparationTests(unittest.TestCase):
    def test_feature_identity_never_satisfies_an_entry_ref(self) -> None:
        import re
        pattern = json.loads((ROOT / "schemas/output-envelope.schema.json").read_text())[
            "$defs"]["entryRef"]["properties"]["entryId"]["pattern"]
        self.assertIsNone(re.match(pattern, "Feature:invoice-finance"))

    def test_feature_ref_defs_exist_in_all_three_envelopes(self) -> None:
        for name in ("output-envelope", "handoff-envelope", "change-record"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
            defs = schema.get("$defs") or schema.get("definitions")
            self.assertIn("featureRef", defs, name)
            self.assertIn("featureRefs", schema["properties"], name)
            self.assertEqual(
                ["featureId", "reviewedContentDigest", "modelDigest", "claimIds"],
                defs["featureRef"]["required"], name,
            )

    def test_layers_and_storage_families_differ_consciously(self) -> None:
        # RB-2: the two vocabularies are similar on purpose and different on purpose. This
        # pin fails when either side changes silently: revisit LAYER_FAMILY_NOTES, never
        # let the dictionaries converge or drift by accident.
        self.assertEqual(set(store.FAMILY_BY_TYPE.values()), set(fk.LAYER_FAMILY_NOTES))
        mapped_layers = {layer for layers in fk.LAYER_FAMILY_NOTES.values() for layer in layers}
        self.assertEqual(set(fk.LAYERS), mapped_layers)
        self.assertNotEqual(set(fk.LAYERS), set(store.FAMILY_BY_TYPE.values()))

    def test_features_live_outside_the_artifact_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".ai/knowledge/features/x").mkdir(parents=True)
            (root / ".ai/knowledge/features/x/feature.md").write_text("---\n---\nbody\n")
            with store.rooted(root):
                self.assertEqual([], store.all_entry_paths())


if __name__ == "__main__":
    unittest.main()
