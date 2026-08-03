"""Org-usage layer tests (contract v1.2 §2.3/§4/§6.6; plan §11).

The facade subprocess is stubbed with canned envelopes — fully offline. The negative tests
are the point: what must NOT happen is org data inside an approval digest, an attach on an
uncontained origin, an expired block rendered as fresh, or a curator holding org authority.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import copilot_role_guard as guard
from scripts import knowledge_store as store
from scripts import validate_harness
from scripts.force_app_knowledge import file_digest
from scripts.knowledge_registry import canonical_digest

ORG_ID = "00D000000000001EAA"
ALLOWED_REMOTE = "git@example.com:acme/private-pilot.git"
IDENTITY = "CustomObject:c:Invoice__c"

Q_SHAPE = (
    "SELECT COUNT(Id) recordCount, MIN(CreatedDate) createdFirst, "
    "MAX(CreatedDate) createdLast FROM Invoice__c LIMIT 1"
)
Q_DIST = (
    "SELECT RecordType.DeveloperName k, COUNT(Id) c FROM Invoice__c "
    "GROUP BY RecordType.DeveloperName LIMIT 200"
)
Q_SAMPLE = (
    "SELECT Name, Status__c, Account__r.Name, Account__r.RecordType.DeveloperName "
    "FROM Invoice__c ORDER BY CreatedDate DESC LIMIT 25"
)


def sha(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def envelope(query: str, records: list, **overrides) -> dict:
    body = {
        "status": "VERIFIED",
        "completeness": {"complete": True},
        "target": {
            "environment": "development",
            "nonProduction": True,
            "expectedOrgIdMatched": True,
        },
        "facts": {
            "soqlQuery": {
                "queryDigest": sha(query),
                "fromObjects": ["Invoice__c"],
                "records": records,
            }
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(body.get(key), dict):
            body[key].update(value)
        else:
            body[key] = value
    return body


def sample_records(count: int = 25) -> list:
    rows = []
    for index in range(count):
        rows.append(
            {
                "Name": f"INV-{index:04d}",
                "Status__c": "Active" if index < 20 else None,
                "Account__r": (
                    {
                        "attributes": {"type": "Account"},
                        "Name": f"Acct {index}",
                        "RecordType": {
                            "attributes": {"type": "RecordType"},
                            "DeveloperName": "Customer",
                        },
                    }
                    if index % 5
                    else None
                ),
            }
        )
    return rows


CANNED = {
    Q_SHAPE: envelope(
        Q_SHAPE,
        [{
            "recordCount": 57,
            "createdFirst": "2021-01-05T08:00:00.000+0000",
            "createdLast": "2026-07-30T00:00:00Z",
        }],
    ),
    Q_DIST: envelope(
        Q_DIST,
        [
            {"k": "Standard", "c": 40},
            {"k": "Premium", "c": 12},
            {"k": "Legacy", "c": 3},
            {"k": None, "c": 2},
        ],
    ),
    Q_SAMPLE: envelope(Q_SAMPLE, sample_records()),
}


class OrgUsageBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self._rooted = store.rooted(self.root)
        self._rooted.__enter__()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: self._rooted.__exit__(None, None, None))
        self.write_policy()
        self.write_local_config()
        self.real_origin_remote_urls = store._origin_remote_urls  # pre-patch original
        containment = unittest.mock.patch.object(
            store, "_origin_remote_urls", return_value=[ALLOWED_REMOTE]
        )
        containment.start()
        self.addCleanup(containment.stop)

    # --- fixtures ------------------------------------------------------------------

    def write_policy(self, allowlist=(ALLOWED_REMOTE,), max_age_days: int = 90) -> None:
        payload = {
            "orgUsage": {
                "allowedOriginRemotes": list(allowlist),
                "maxOrgUsageAgeDays": max_age_days,
                "maxSampleColumns": 20,
                "sampleRows": 25,
                "sampleRowsMax": 50,
                "usageGroupSuppressionFloor": 5,
            }
        }
        path = self.root / "config/knowledge-policy.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def write_local_config(
        self,
        org_id: str = ORG_ID,
        environment: str = "development",
        refreshed_at: "str | None" = None,
        alias: str = "dev-sbx",
    ) -> None:
        org = {
            "alias": alias,
            "environment": environment,
            "allowAgentRead": True,
            "allowAgentWrite": False,
            "allowAgentReview": True,
            "expectedOrganizationId": org_id,
            "fullCopy": False,
        }
        if refreshed_at:
            org["refreshedAt"] = refreshed_at
        payload = {
            "knowledge": {"chatReviewer": "Owner Human"},
            "salesforce": {"orgs": [org]},
        }
        path = self.root / "config/harness.local.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def write_source_fragment(self) -> dict:
        fragment_path = self.root / "force-app/main/default/objects/Invoice__c/Invoice__c.object-meta.xml"
        fragment_path.parent.mkdir(parents=True, exist_ok=True)
        fragment_path.write_text("<CustomObject/>\n", encoding="utf-8")
        relative = "force-app/main/default/objects/Invoice__c/Invoice__c.object-meta.xml"
        return {"path": relative, "sourceDigest": f"sha256:{file_digest(fragment_path)}"}

    def base_entry(self, metadata_type: str = "CustomObject", full_name: str = "Invoice__c"):
        fragment = self.write_source_fragment()
        frontmatter = {
            "schemaVersion": 1,
            "subject": {"metadataType": metadata_type, "fullName": full_name, "namespace": None},
            "profile": {
                "id": "salesforce.custom-object",
                "version": "1.0.0",
                "digest": canonical_digest(store.load_schema("knowledge-profile-customobject.schema.json")),
            },
            "scope": {
                "sourceApiVersion": "64.0",
                "sourceTreeDigest": canonical_digest([(fragment["path"], fragment["sourceDigest"])]),
                "packageVersionId": None,
                "collectorVersion": "1.7.0",
            },
            "source": {"fragments": [fragment]},
            "lifecycle": {"state": "draft", "contentDigest": "sha256:" + "0" * 64},
            "typeFacts": {"objectKind": "custom"},
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {"typeFacts": "source-exact"},
            "limitations": [],
            "keywords": [],
            "candidateKeywords": [],
            "sensitivity": "internal-sanitized",
            "approval": {
                "reviewedContentDigest": None,
                "reviewedBy": None,
                "reviewedAt": None,
                "mechanism": None,
            },
        }
        body = "## Purpose\n\nHolds customer invoices raised by the billing feature.\n"
        return frontmatter, body

    def write_entry(self, frontmatter, body) -> Path:
        subject = frontmatter["subject"]
        path = store.entry_path(subject["metadataType"], subject.get("namespace"), subject["fullName"])
        path.parent.mkdir(parents=True, exist_ok=True)
        store.atomic_write(path, store.render_entry(frontmatter, body))
        return path

    def approve(self, frontmatter, body) -> str:
        digest = store.reviewed_content_digest(frontmatter, body)
        frontmatter["lifecycle"]["state"] = "approved"
        frontmatter["approval"] = {
            "reviewedContentDigest": digest,
            "reviewedBy": "Owner Human",
            "reviewedAt": "2026-08-01T09:00:00Z",
            "mechanism": "copilot-chat-entry-confirmation",
        }
        store.append_ledger(
            [{
                "action": "approve",
                "identity": IDENTITY,
                "reviewedContentDigest": digest,
                "semanticsDigest": store.semantics_digest(body),
                "reviewedBy": "Owner Human",
                "reviewedAt": "2026-08-01T09:00:00Z",
                "mechanism": "copilot-chat-entry-confirmation",
            }]
        )
        return digest

    def probes_file(self, probes) -> str:
        path = self.root / ".cache/org-usage/pending/probes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"probes": probes}), encoding="utf-8")
        return str(path)

    def default_probes(self):
        return [
            {"label": "object-shape", "kind": "object-shape", "query": Q_SHAPE},
            {"label": "record-type-distribution", "kind": "record-type-distribution", "query": Q_DIST},
            {"label": "record-sample-recent", "kind": "record-sample", "query": Q_SAMPLE},
        ]

    def attach(self, probes=None, org: str = "dev-sbx", canned=None):
        args = type("Args", (), {})()
        args.identity = IDENTITY
        args.org = org
        args.probes_file = self.probes_file(probes if probes is not None else self.default_probes())
        calls = []

        def fake_facade(alias, tool, arguments):
            calls.append((alias, tool, arguments))
            table = canned if canned is not None else CANNED
            result = table[arguments["query"]]
            return json.loads(json.dumps(result))  # deep copy

        with unittest.mock.patch.object(store, "_facade_call", side_effect=fake_facade):
            result = store.command_entry_org_attach(args)
        return result, calls

    def detach(self, org: str = "dev-sbx", rationale: str = "test rollback"):
        args = type("Args", (), {})()
        args.identity = IDENTITY
        args.org = org
        args.rationale = rationale
        return store.command_entry_org_detach(args)


class TestAttachHappyPath(OrgUsageBase):
    def test_attach_preserves_approval_and_derives_closed_shapes(self) -> None:
        frontmatter, body = self.base_entry()
        self.approve(frontmatter, body)
        path = self.write_entry(frontmatter, body)
        approval_ledger_before = store.LEDGER_PATH.read_bytes()
        facts_before = store.facts_digest(frontmatter)
        semantics_before = store.semantics_digest(body)
        reviewed_before = store.reviewed_content_digest(frontmatter, body)

        result, calls = self.attach()

        self.assertEqual("ORG_ATTACHED", result["outcome"])
        self.assertTrue(result["approvalPreserved"])
        self.assertEqual(3, len(calls))
        written, new_body = store.split_entry(path.read_text(encoding="utf-8"))
        # All three digests byte-identical; the approval ledger untouched; lane still current.
        self.assertEqual(facts_before, store.facts_digest(written))
        self.assertEqual(semantics_before, store.semantics_digest(new_body))
        self.assertEqual(reviewed_before, store.reviewed_content_digest(written, new_body))
        self.assertEqual(approval_ledger_before, store.LEDGER_PATH.read_bytes())
        lane = store.compute_lane(path, store.ledger_latest(store.read_ledger()))
        self.assertEqual("approved-current", lane["lane"])
        self.assertEqual([], lane["problems"])
        # Entry validates against the real schema, orgUsage included.
        self.assertEqual([], store.validate_entry(written, new_body))
        block = written["orgUsage"]["orgs"]["dev-sbx"]
        # Distribution: suppression floor folded Legacy(3) + null(2) into otherBucket.
        dist = block["probes"]["record-type-distribution"]["results"]
        self.assertEqual(
            [{"key": "Standard", "recordCount": 40}, {"key": "Premium", "recordCount": 12}],
            dist["groups"],
        )
        self.assertEqual({"suppressedGroups": 2, "recordCount": 5}, dist["otherBucket"])
        # Sample: counts only, never values; free label under D-5'.
        sample = block["probes"]["record-sample-recent"]["results"]
        self.assertEqual(25, sample["sampleSize"])
        fills = {item["field"]: item["populatedCount"] for item in sample["fieldFill"]}
        self.assertEqual(25, fills["Name"])
        self.assertEqual(20, fills["Status__c"])
        self.assertEqual(20, fills["Account__r.Name"])
        structure = {row["path"]: row for row in block["recordStructure"]}
        self.assertEqual("Account", structure["Account__r"]["targetObject"])
        self.assertEqual("20/25", structure["Account__r"]["populated"])
        self.assertEqual("RecordType", structure["Account__r.RecordType"]["targetObject"])
        # Timestamps normalized to UTC Z form.
        shape = block["probes"]["object-shape"]["results"]
        self.assertEqual(57, shape["recordCount"])
        self.assertEqual("2021-01-05T08:00:00Z", shape["createdFirst"])
        # Org ledger appended, approval ledger separate.
        org_records = store.read_ledger(store.ORG_LEDGER_PATH)
        self.assertEqual(1, len(org_records))
        self.assertEqual("attach", org_records[0]["action"])
        self.assertEqual(written["orgUsage"]["sectionDigest"], org_records[0]["orgUsageDigest"])
        # Receipt carries the exact queryText the entry only holds a digest of.
        receipt = json.loads((self.root / result["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(Q_SAMPLE, receipt["probes"]["record-sample-recent"]["queryText"])
        self.assertEqual(receipt["wrapperDigest"], block["receiptDigest"])
        # Fresh lane computed from the written state.
        org = store.compute_org_lane(written, IDENTITY)
        self.assertEqual("org-fresh", org["orgs"]["dev-sbx"]["status"])

    def test_replace_per_orgkey_and_detach_roundtrip(self) -> None:
        frontmatter, body = self.base_entry()
        self.approve(frontmatter, body)
        path = self.write_entry(frontmatter, body)
        self.attach()
        self.attach()  # replace, not append
        written, _ = store.split_entry(path.read_text(encoding="utf-8"))
        self.assertEqual(["dev-sbx"], sorted(written["orgUsage"]["orgs"]))
        self.assertEqual(2, len(store.read_ledger(store.ORG_LEDGER_PATH)))
        result = self.detach()
        self.assertEqual("ORG_DETACHED", result["outcome"])
        self.assertTrue(result["approvalPreserved"])
        written, new_body = store.split_entry(path.read_text(encoding="utf-8"))
        self.assertNotIn("orgUsage", written)
        self.assertEqual("org-absent", store.compute_org_lane(written, IDENTITY)["section"])
        lane = store.compute_lane(path, store.ledger_latest(store.read_ledger()))
        self.assertEqual("approved-current", lane["lane"])


class TestDigestExclusion(OrgUsageBase):
    def test_canonical_facts_never_contain_org_usage(self) -> None:
        frontmatter, body = self.base_entry()
        frontmatter["orgUsage"] = {"sectionDigest": "sha256:" + "a" * 64, "orgs": {"x": {"anything": 1}}}
        self.assertNotIn("orgUsage", json.dumps(store._canonical_facts(frontmatter)))

    def test_arbitrary_org_usage_mutation_moves_no_approval_digest(self) -> None:
        frontmatter, body = self.base_entry()
        baseline = (
            store.facts_digest(frontmatter),
            store.semantics_digest(body),
            store.reviewed_content_digest(frontmatter, body),
        )
        for mutation in (
            {"sectionDigest": "sha256:" + "b" * 64, "orgs": {"dev-sbx": {"probes": {"p": 1}}}},
            {"sectionDigest": "sha256:" + "c" * 64, "orgs": {}},
            None,
        ):
            if mutation is None:
                frontmatter.pop("orgUsage", None)
            else:
                frontmatter["orgUsage"] = mutation
            self.assertEqual(
                baseline,
                (
                    store.facts_digest(frontmatter),
                    store.semantics_digest(body),
                    store.reviewed_content_digest(frontmatter, body),
                ),
            )

    def test_schema_never_requires_org_usage_nor_binds_it_to_coverage(self) -> None:
        schema = store.load_schema("knowledge-entry.schema.json")
        self.assertNotIn("orgUsage", schema["required"])
        for conditional in schema["allOf"]:
            then_block = json.dumps(conditional.get("then", {}))
            if "extractionCoverage" in then_block or "assurance" in then_block:
                self.assertNotIn("orgUsage", then_block)

    def test_wave1_pin_rejects_org_usage_on_other_types(self) -> None:
        from jsonschema import Draft202012Validator

        schema = store.load_schema("knowledge-entry.schema.json")
        frontmatter, _body = self.base_entry()
        frontmatter["subject"]["metadataType"] = "Flow"
        frontmatter["orgUsage"] = {
            "sectionDigest": "sha256:" + "a" * 64,
            "orgs": {
                "dev-sbx": {
                    "environment": "development",
                    "orgIdDigest": "sha256:" + "a" * 64,
                    "observedAt": "2026-08-03T10:00:00Z",
                    "expiresAt": "2026-11-01T10:00:00Z",
                    "shapeVersion": 1,
                    "transport": "mcp-review-facade",
                    "assurance": "org-observed",
                    "probes": {
                        "object-shape": {
                            "kind": "object-shape",
                            "queryDigest": "sha256:" + "a" * 64,
                            "completeness": "complete",
                            "results": {"recordCount": 1},
                        }
                    },
                    "receiptDigest": "sha256:" + "a" * 64,
                }
            },
        }
        errors = list(Draft202012Validator(schema).iter_errors(frontmatter))
        self.assertTrue(errors, "a Flow entry with orgUsage must be schema-invalid (wave-1 pin)")


class TestContainment(OrgUsageBase):
    def test_empty_allowlist_refuses_everywhere(self) -> None:
        self.write_policy(allowlist=())
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        with self.assertRaisesRegex(store.StoreError, "containment"):
            self.attach()
        self.assertFalse(store.ORG_LEDGER_PATH.exists())

    def test_off_list_remote_refuses(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        with unittest.mock.patch.object(
            store, "_origin_remote_urls", return_value=["git@github.com:public/origin.git"]
        ):
            with self.assertRaisesRegex(store.StoreError, "outside the allowlist"):
                self.attach()

    def test_git_failure_is_a_refusal_never_a_pass(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        with unittest.mock.patch.object(
            store,
            "_origin_remote_urls",
            side_effect=store.StoreError("containment: git remote enumeration failed — refusing, never passing (gate 1)"),
        ):
            with self.assertRaisesRegex(store.StoreError, "refusing, never passing"):
                self.attach()
        self.assertFalse(store.ORG_LEDGER_PATH.exists())

    def test_git_failure_real_subprocess(self) -> None:
        # Belt and braces: the REAL enumeration (pre-patch original) against a tmp root that
        # is not a git repository refuses; a broken git is never indistinguishable from clean.
        self.assertNotIn(".git", [p.name for p in self.root.iterdir()])
        with unittest.mock.patch.object(store, "_origin_remote_urls", self.real_origin_remote_urls):
            with self.assertRaisesRegex(store.StoreError, "containment"):
                store.assert_containment({"allowedOriginRemotes": [ALLOWED_REMOTE]})


class TestComputeOrgLane(OrgUsageBase):
    def manual_attach(
        self,
        observed_at: str = "2026-08-03T10:00:00Z",
        expires_at: "str | None" = None,
        org_id: str = ORG_ID,
    ):
        frontmatter, body = self.base_entry()
        expires = expires_at or (
            (store._parse_iso(observed_at) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        block = {
            "environment": "development",
            "orgIdDigest": store.org_id_digest(org_id),
            "fullCopy": False,
            "observedAt": observed_at,
            "expiresAt": expires,
            "shapeVersion": 1,
            "transport": "mcp-review-facade",
            "assurance": "org-observed",
            "probes": {
                "object-shape": {
                    "kind": "object-shape",
                    "queryDigest": f"sha256:{sha(Q_SHAPE)}",
                    "completeness": "complete",
                    "results": {"recordCount": 57},
                }
            },
            "receiptDigest": "sha256:" + "d" * 64,
        }
        orgs = {"dev-sbx": block}
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        path = self.write_entry(frontmatter, body)
        store.append_ledger(
            [{
                "action": "attach",
                "identity": IDENTITY,
                "orgKey": "dev-sbx",
                "orgUsageDigest": frontmatter["orgUsage"]["sectionDigest"],
                "observedAt": observed_at,
                "expiresAt": expires,
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": block["receiptDigest"],
            }],
            store.ORG_LEDGER_PATH,
        )
        return frontmatter, body, path

    def status_at(self, frontmatter, now: str) -> str:
        lane = store.compute_org_lane(
            frontmatter, IDENTITY, now=store._parse_iso(now)
        )
        return lane["orgs"]["dev-sbx"]["status"]

    def test_fresh_and_expired_by_wall_clock(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        self.assertEqual("org-fresh", self.status_at(frontmatter, "2026-08-10T10:00:00Z"))
        self.assertEqual("org-expired", self.status_at(frontmatter, "2026-11-02T10:00:01Z"))

    def test_policy_tightening_expires_retroactively(self) -> None:
        frontmatter, _body, _path = self.manual_attach()  # stored expiresAt = obs + 90d
        self.write_policy(max_age_days=1)
        self.assertEqual("org-expired", self.status_at(frontmatter, "2026-08-05T10:00:01Z"))
        # And at no point can a block past min() be fresh.
        self.assertEqual("org-fresh", self.status_at(frontmatter, "2026-08-03T12:00:00Z"))

    def test_org_id_change_supersedes(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        self.write_local_config(org_id="00D000000000002EAA")
        self.assertEqual("org-superseded", self.status_at(frontmatter, "2026-08-10T10:00:00Z"))

    def test_owner_declared_refresh_supersedes_even_when_org_id_survives(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        self.write_local_config(refreshed_at="2026-08-04T00:00:00Z")
        self.assertEqual("org-superseded", self.status_at(frontmatter, "2026-08-10T10:00:00Z"))

    def test_unconfigured_alias_supersedes(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        self.write_local_config(alias="other-org")
        self.assertEqual("org-superseded", self.status_at(frontmatter, "2026-08-10T10:00:00Z"))

    def test_hand_edit_is_org_not_effective(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        frontmatter["orgUsage"]["orgs"]["dev-sbx"]["probes"]["object-shape"]["results"]["recordCount"] = 9999
        lane = store.compute_org_lane(frontmatter, IDENTITY)
        self.assertEqual("org-not-effective", lane["section"])
        self.assertEqual("org-not-effective", lane["orgs"]["dev-sbx"]["status"])

    def test_ledger_replay_is_quarantined(self) -> None:
        frontmatter, body, path = self.manual_attach()
        old_text = path.read_text(encoding="utf-8")
        # Second attach supersedes the first in the ledger…
        orgs = dict(frontmatter["orgUsage"]["orgs"])
        orgs["dev-sbx"] = dict(orgs["dev-sbx"], observedAt="2026-08-05T10:00:00Z")
        store.append_ledger(
            [{
                "action": "attach",
                "identity": IDENTITY,
                "orgKey": "dev-sbx",
                "orgUsageDigest": canonical_digest(orgs),
                "observedAt": "2026-08-05T10:00:00Z",
                "expiresAt": "2026-11-03T10:00:00Z",
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": "sha256:" + "e" * 64,
            }],
            store.ORG_LEDGER_PATH,
        )
        # …so restoring the first file bytes (sealed but stale) is not effective.
        restored, _ = store.split_entry(old_text)
        lane = store.compute_org_lane(restored, IDENTITY)
        self.assertEqual("org-not-effective", lane["section"])

    def test_missing_section_with_attach_ledger_is_not_effective(self) -> None:
        frontmatter, _body, _path = self.manual_attach()
        frontmatter.pop("orgUsage")
        lane = store.compute_org_lane(frontmatter, IDENTITY)
        self.assertEqual("org-not-effective", lane["section"])


class TestAttachRefusals(OrgUsageBase):
    def test_public_sensitivity_refused(self) -> None:
        frontmatter, body = self.base_entry()
        frontmatter["sensitivity"] = "public"
        self.write_entry(frontmatter, body)
        with self.assertRaisesRegex(store.StoreError, "public-sensitivity"):
            self.attach()

    def test_wave1_only(self) -> None:
        args = type("Args", (), {})()
        args.identity = "Flow:c:Some_Flow"
        args.org = "dev-sbx"
        args.probes_file = self.probes_file(self.default_probes())
        with self.assertRaisesRegex(store.StoreError, "wave-1"):
            store.command_entry_org_attach(args)

    def test_dynamic_lane_refused_without_expected_org_id(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        config = json.loads((self.root / "config/harness.local.json").read_text(encoding="utf-8"))
        del config["salesforce"]["orgs"][0]["expectedOrganizationId"]
        (self.root / "config/harness.local.json").write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(store.StoreError, "dynamic-lane refused"):
            self.attach()

    def test_mid_run_identity_mismatch_aborts_everything(self) -> None:
        frontmatter, body = self.base_entry()
        self.approve(frontmatter, body)
        path = self.write_entry(frontmatter, body)
        before = path.read_bytes()
        canned = json.loads(json.dumps(CANNED))
        canned[Q_DIST]["target"]["expectedOrgIdMatched"] = False
        with self.assertRaisesRegex(store.StoreError, "whole attach is"):
            self.attach(canned=canned)
        self.assertEqual(before, path.read_bytes())
        self.assertFalse(store.ORG_LEDGER_PATH.exists())

    def test_wrong_environment_aborts(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        canned = json.loads(json.dumps(CANNED))
        canned[Q_SHAPE]["target"]["environment"] = "qa"
        with self.assertRaisesRegex(store.StoreError, "mismatch"):
            self.attach(canned=canned)

    def test_query_digest_mismatch_refuses(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        canned = json.loads(json.dumps(CANNED))
        canned[Q_SHAPE]["facts"]["soqlQuery"]["queryDigest"] = "0" * 64
        with self.assertRaisesRegex(store.StoreError, "QUERY_DIGEST_MISMATCH"):
            self.attach(canned=canned)

    def test_missing_trailing_limit_refused_before_any_facade_call(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        probes = [{
            "label": "object-shape",
            "kind": "object-shape",
            "query": "SELECT COUNT(Id) recordCount FROM Invoice__c",
        }]
        with self.assertRaisesRegex(store.StoreError, "explicit trailing LIMIT"):
            result, calls = self.attach(probes=probes)
        # attach() raised before returning calls; assert via a fresh mock that nothing ran
        args = type("Args", (), {})()
        args.identity = IDENTITY
        args.org = "dev-sbx"
        args.probes_file = self.probes_file(probes)
        with unittest.mock.patch.object(store, "_facade_call") as facade:
            with self.assertRaises(store.StoreError):
                store.command_entry_org_attach(args)
        facade.assert_not_called()

    def test_sample_limit_above_policy_refused(self) -> None:
        frontmatter, body = self.base_entry()
        self.write_entry(frontmatter, body)
        probes = [{
            "label": "record-sample-wide",
            "kind": "record-sample",
            "query": "SELECT Name FROM Invoice__c ORDER BY CreatedDate DESC LIMIT 60",
        }]
        with self.assertRaisesRegex(store.StoreError, "sampleRowsMax"):
            self.attach(probes=probes)

    def test_blocked_probe_is_dropped_but_others_persist(self) -> None:
        frontmatter, body = self.base_entry()
        self.approve(frontmatter, body)
        path = self.write_entry(frontmatter, body)
        canned = json.loads(json.dumps(CANNED))
        canned[Q_DIST]["status"] = "BLOCKED"
        result, _calls = self.attach(canned=canned)
        self.assertEqual(["record-type-distribution"], [item["label"] for item in result["dropped"]])
        written, _ = store.split_entry(path.read_text(encoding="utf-8"))
        self.assertNotIn("record-type-distribution", written["orgUsage"]["orgs"]["dev-sbx"]["probes"])
        self.assertIn("object-shape", written["orgUsage"]["orgs"]["dev-sbx"]["probes"])

    def test_all_probes_blocked_persists_nothing(self) -> None:
        frontmatter, body = self.base_entry()
        path = self.write_entry(frontmatter, body)
        before = path.read_bytes()
        canned = json.loads(json.dumps(CANNED))
        for value in canned.values():
            value["status"] = "BLOCKED"
        with self.assertRaisesRegex(store.StoreError, "no probe completed"):
            self.attach(canned=canned)
        self.assertEqual(before, path.read_bytes())
        self.assertFalse(store.ORG_LEDGER_PATH.exists())


class TestGuardRoleBinding(unittest.TestCase):
    def test_attach_is_config_investigator_only(self) -> None:
        parts = ["entry-org-attach", "--identity", IDENTITY, "--org", "dev-sbx",
                 "--probes-file", ".cache/org-usage/pending/probes.json"]
        self.assertTrue(guard.knowledge_store_command_allowed(parts, "config-investigator"))
        for role in ("knowledge-curator", "development-assistant", "solution-designer",
                     "test-strategist", "guardrail-reviewer"):
            self.assertFalse(guard.knowledge_store_command_allowed(parts, role), role)

    def test_detach_role_and_flag_surface(self) -> None:
        parts = ["entry-org-detach", "--identity", IDENTITY, "--org", "dev-sbx",
                 "--rationale", "sandbox refreshed"]
        self.assertTrue(guard.knowledge_store_command_allowed(parts, "config-investigator"))
        self.assertFalse(guard.knowledge_store_command_allowed(parts, "knowledge-curator"))
        self.assertFalse(
            guard.knowledge_store_command_allowed(
                ["entry-org-attach", "--identity", IDENTITY, "--org", "dev-sbx", "--rm"],
                "config-investigator",
            )
        )

    def test_probes_dir_is_writable_by_config_investigator_only(self) -> None:
        self.assertIn(".cache/org-usage/", guard.ALLOWED_PREFIXES["config-investigator"])
        for role, prefixes in guard.ALLOWED_PREFIXES.items():
            if role != "config-investigator":
                self.assertNotIn(".cache/org-usage/", prefixes, role)


class TestCarryForward(OrgUsageBase):
    def test_helper_preserves_org_usage_across_rebuild(self) -> None:
        frontmatter, body = self.base_entry()
        frontmatter["orgUsage"] = {
            "sectionDigest": "sha256:" + "a" * 64,
            "orgs": {"dev-sbx": {"marker": True}},
        }
        path = self.write_entry(frontmatter, body)
        rebuilt, _body = self.base_entry()
        self.assertNotIn("orgUsage", rebuilt)
        store.carry_forward_org_usage(rebuilt, path)
        self.assertEqual(frontmatter["orgUsage"], rebuilt["orgUsage"])

    def test_entry_draft_calls_the_carry_forward(self) -> None:
        # Source pin: the wholesale rebuild in entry-draft must route through the helper —
        # deleting the call is exactly the regression M-R4 predicts.
        self.assertIn("carry_forward_org_usage", inspect.getsource(store.command_entry_draft))


class TestRenderersWithholdStaleValues(OrgUsageBase):
    def test_entry_review_separates_and_withholds(self) -> None:
        # An old observation (2020) is expired under any policy; its values must not render.
        lane_test = TestComputeOrgLane("test_fresh_and_expired_by_wall_clock")
        frontmatter, body = self.base_entry()
        observed = "2020-01-01T00:00:00Z"
        block = {
            "environment": "development",
            "orgIdDigest": store.org_id_digest(ORG_ID),
            "observedAt": observed,
            "expiresAt": "2020-03-31T00:00:00Z",
            "shapeVersion": 1,
            "transport": "mcp-review-facade",
            "assurance": "org-observed",
            "probes": {
                "object-shape": {
                    "kind": "object-shape",
                    "queryDigest": f"sha256:{sha(Q_SHAPE)}",
                    "completeness": "complete",
                    "results": {"recordCount": 424242},
                }
            },
            "receiptDigest": "sha256:" + "d" * 64,
        }
        orgs = {"dev-sbx": block}
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        self.write_entry(frontmatter, body)
        store.append_ledger(
            [{
                "action": "attach",
                "identity": IDENTITY,
                "orgKey": "dev-sbx",
                "orgUsageDigest": frontmatter["orgUsage"]["sectionDigest"],
                "observedAt": observed,
                "expiresAt": "2020-03-31T00:00:00Z",
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": block["receiptDigest"],
            }],
            store.ORG_LEDGER_PATH,
        )
        args = type("Args", (), {})()
        args.identity = [IDENTITY]
        result = store.command_entry_review(args)
        artifact = (self.root / result["reviewArtifact"]).read_text(encoding="utf-8")
        self.assertIn("NOT covered by this approval", artifact)
        self.assertIn("values withheld", artifact)
        self.assertNotIn("424242", artifact, "expired org values must never render")

    def test_entry_status_and_check_disclose_org_lane(self) -> None:
        frontmatter, body = self.base_entry()
        matrix = TestComputeOrgLane("test_fresh_and_expired_by_wall_clock")
        del matrix  # only the helper shape below is needed
        observed = store._utc_now_iso()
        expires = (
            datetime.now(timezone.utc) + timedelta(days=90)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = {
            "environment": "development",
            "orgIdDigest": store.org_id_digest(ORG_ID),
            "observedAt": observed,
            "expiresAt": expires,
            "shapeVersion": 1,
            "transport": "mcp-review-facade",
            "assurance": "org-observed",
            "probes": {
                "object-shape": {
                    "kind": "object-shape",
                    "queryDigest": f"sha256:{sha(Q_SHAPE)}",
                    "completeness": "complete",
                    "results": {"recordCount": 57},
                }
            },
            "receiptDigest": "sha256:" + "d" * 64,
        }
        orgs = {"dev-sbx": block}
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        self.write_entry(frontmatter, body)
        store.append_ledger(
            [{
                "action": "attach",
                "identity": IDENTITY,
                "orgKey": "dev-sbx",
                "orgUsageDigest": frontmatter["orgUsage"]["sectionDigest"],
                "observedAt": observed,
                "expiresAt": expires,
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": block["receiptDigest"],
            }],
            store.ORG_LEDGER_PATH,
        )
        status_args = type("Args", (), {})()
        status_args.identity = IDENTITY
        status = store.command_entry_status(status_args)
        disclosed = status["entries"][0]["orgUsage"]
        self.assertEqual("org-effective", disclosed["section"])
        self.assertEqual("org-fresh", disclosed["orgs"][0]["status"])
        check_args = type("Args", (), {})()
        check_args.changed_since = None
        check = store.command_entry_check(check_args)
        self.assertEqual({"org-fresh": 1}, check["orgUsage"]["counts"])


class TestSearchProjectionExcludesValues(OrgUsageBase):
    def org_bearing_projection(self):
        from scripts import knowledge_search

        frontmatter, body = self.base_entry()
        block = {
            "environment": "development",
            "orgIdDigest": store.org_id_digest(ORG_ID),
            "observedAt": "2026-08-03T10:00:00Z",
            "expiresAt": "2026-11-01T10:00:00Z",
            "shapeVersion": 1,
            "transport": "mcp-review-facade",
            "assurance": "org-observed",
            "probes": {
                "object-shape": {
                    "kind": "object-shape",
                    "queryDigest": f"sha256:{sha(Q_SHAPE)}",
                    "completeness": "complete",
                    "results": {"recordCount": 424242},
                },
                "record-type-distribution": {
                    "kind": "record-type-distribution",
                    "queryDigest": f"sha256:{sha(Q_DIST)}",
                    "completeness": "complete",
                    "results": {
                        "groups": [{"key": "SecretSegment", "recordCount": 99}],
                        "suppressionFloor": 5,
                    },
                },
            },
            "receiptDigest": "sha256:" + "d" * 64,
        }
        orgs = {"dev-sbx": block}
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        path = self.write_entry(frontmatter, body)
        lane = store.compute_lane(path, store.ledger_latest(store.read_ledger()))
        return knowledge_search.project_entry(path, lane)

    def test_probe_values_never_enter_bm25_text_or_facets(self) -> None:
        projection = self.org_bearing_projection()
        searchable = json.dumps({"fields": projection["fields"], "facets": projection["facets"]})
        self.assertNotIn("424242", searchable, "a probe count is findable — M #18 violated")
        self.assertNotIn("SecretSegment", searchable, "a group key is findable — M #18 violated")
        self.assertNotIn("secretsegment", searchable)

    def test_projection_carries_metadata_only(self) -> None:
        projection = self.org_bearing_projection()
        self.assertEqual(1, len(projection["orgUsage"]))
        row = projection["orgUsage"][0]
        self.assertLessEqual(
            set(row), {"orgKey", "environment", "observedAt", "expiresAt", "fullCopy"}
        )
        self.assertNotIn("424242", json.dumps(projection["orgUsage"]))

    def test_context_bucket_recomputes_expiry_at_read_time(self) -> None:
        from scripts import knowledge_search

        expired = knowledge_search.org_usage_bucket(
            {"orgUsage": [{"orgKey": "dev-sbx", "environment": "development",
                           "observedAt": "2020-01-01T00:00:00Z", "expiresAt": "2020-03-31T00:00:00Z"}]}
        )
        self.assertIn("treat as absent", expired[0]["status"])
        future = knowledge_search.org_usage_bucket(
            {"orgUsage": [{"orgKey": "dev-sbx", "environment": "development",
                           "observedAt": "2026-08-03T10:00:00Z", "expiresAt": "2099-01-01T00:00:00Z"}]}
        )
        self.assertIn("entry-status", future[0]["status"])
        self.assertIn("NOT covered by entry approval", future[0]["attribution"])
        # A block with no parseable expiry is expired, never fresh (fail-closed).
        broken = knowledge_search.org_usage_bucket(
            {"orgUsage": [{"orgKey": "dev-sbx", "environment": "development"}]}
        )
        self.assertIn("treat as absent", broken[0]["status"])


class TestValidateHarnessOrgGate(OrgUsageBase):
    def run_check(self):
        audit = validate_harness.Audit()
        validate_harness.check_org_usage(audit, root=self.root)
        return audit

    def seal_and_ledger(self, frontmatter):
        store.append_ledger(
            [{
                "action": "attach",
                "identity": IDENTITY,
                "orgKey": "dev-sbx",
                "orgUsageDigest": frontmatter["orgUsage"]["sectionDigest"],
                "observedAt": frontmatter["orgUsage"]["orgs"]["dev-sbx"]["observedAt"],
                "expiresAt": frontmatter["orgUsage"]["orgs"]["dev-sbx"]["expiresAt"],
                "shapeVersion": 1,
                "transport": "mcp-review-facade",
                "receiptDigest": "sha256:" + "d" * 64,
            }],
            store.ORG_LEDGER_PATH,
        )

    def org_bearing_entry(self):
        frontmatter, body = self.base_entry()
        block = {
            "environment": "development",
            "orgIdDigest": store.org_id_digest(ORG_ID),
            "observedAt": "2026-08-03T10:00:00Z",
            "expiresAt": "2026-11-01T10:00:00Z",
            "shapeVersion": 1,
            "transport": "mcp-review-facade",
            "assurance": "org-observed",
            "probes": {
                "object-shape": {
                    "kind": "object-shape",
                    "queryDigest": f"sha256:{sha(Q_SHAPE)}",
                    "completeness": "complete",
                    "results": {"recordCount": 57},
                }
            },
            "receiptDigest": "sha256:" + "d" * 64,
        }
        orgs = {"dev-sbx": block}
        frontmatter["orgUsage"] = {"sectionDigest": canonical_digest(orgs), "orgs": orgs}
        path = self.write_entry(frontmatter, body)
        return frontmatter, path

    def test_clean_org_bearing_corpus_passes_with_containment(self) -> None:
        frontmatter, _path = self.org_bearing_entry()
        self.seal_and_ledger(frontmatter)
        fake = unittest.mock.Mock()
        fake.returncode = 0
        fake.stdout = f"origin\t{ALLOWED_REMOTE} (fetch)\norigin\t{ALLOWED_REMOTE} (push)\n"
        with unittest.mock.patch("subprocess.run", return_value=fake):
            audit = self.run_check()
        self.assertEqual([], audit.errors)

    def test_tampered_section_digest_fails(self) -> None:
        frontmatter, path = self.org_bearing_entry()
        self.seal_and_ledger(frontmatter)
        frontmatter["orgUsage"]["orgs"]["dev-sbx"]["probes"]["object-shape"]["results"]["recordCount"] = 1
        self.write_entry(frontmatter, store.split_entry(path.read_text(encoding="utf-8"))[1])
        fake = unittest.mock.Mock(returncode=0, stdout=f"origin\t{ALLOWED_REMOTE} (fetch)\n")
        with unittest.mock.patch("subprocess.run", return_value=fake):
            audit = self.run_check()
        self.assertTrue(any("does not recompute" in error for error in audit.errors))

    def test_org_bearing_without_ledger_record_fails(self) -> None:
        self.org_bearing_entry()  # no ledger record appended
        fake = unittest.mock.Mock(returncode=0, stdout=f"origin\t{ALLOWED_REMOTE} (fetch)\n")
        with unittest.mock.patch("subprocess.run", return_value=fake):
            audit = self.run_check()
        self.assertTrue(any("latest org-ledger record" in error for error in audit.errors))

    def test_org_bearing_with_empty_allowlist_fails_containment(self) -> None:
        frontmatter, _path = self.org_bearing_entry()
        self.seal_and_ledger(frontmatter)
        self.write_policy(allowlist=())
        audit = self.run_check()
        self.assertTrue(any("containment fails" in error for error in audit.errors))

    def test_git_failure_fails_containment_never_passes(self) -> None:
        frontmatter, _path = self.org_bearing_entry()
        self.seal_and_ledger(frontmatter)
        fake = unittest.mock.Mock(returncode=128, stdout="")
        with unittest.mock.patch("subprocess.run", return_value=fake):
            audit = self.run_check()
        self.assertTrue(any("containment fails" in error for error in audit.errors))

    def test_ledger_sequence_break_fails(self) -> None:
        store.ORG_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        store.ORG_LEDGER_PATH.write_text(
            json.dumps({"sequence": 2, "action": "attach", "identity": IDENTITY}) + "\n",
            encoding="utf-8",
        )
        audit = self.run_check()
        self.assertTrue(any("sequence break" in error for error in audit.errors))


if __name__ == "__main__":
    unittest.main()
