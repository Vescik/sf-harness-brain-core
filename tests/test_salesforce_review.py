from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
ORG_ID = "00D000000000001AAA"
HOST = "example--dev.sandbox.my.salesforce.com"
SCRATCH_HOST = "mpsadev.scratch.my.salesforce.com"


FAKE_CLI = r"""
const args = process.argv.slice(2);
const out = (value) => process.stdout.write(JSON.stringify(value));
if (args[0] === "version") {
  out({architecture: "test", cliVersion: "@salesforce/cli/2.141.6", nodeVersion: process.version});
} else if (args[0] === "org" && args[1] === "display") {
  out({status: 0, result: {
    id: "00D000000000001AAA",
    instanceUrl: "https://" + (process.env.SF_FAKE_INSTANCE_HOST || "example--dev.sandbox.my.salesforce.com"),
    accessToken: "Bearer SHOULD_NEVER_ESCAPE",
    clientId: "sensitive-client",
    username: "person@example.invalid",
    sfdxAuthUrl: "force://sensitive"
  }});
} else if (args[0] === "data" && args[1] === "query") {
  out({status: 0, result: {done: true, totalSize: 1, records: [
    {attributes: {type: "Organization", url: "/services/data/private"}, Id: "00D000000000001AAA", IsSandbox: process.env.SF_FAKE_IS_SANDBOX !== "false"}
  ]}});
} else if (args[0] === "package" && args[1] === "installed") {
  if (process.env.SF_FAKE_CLI_PACKAGE_ERROR === "1") {
    process.exitCode = 3;
  } else out({status: 0, result: [
    {
      Id: "0A3000000000001AAA",
      SubscriberPackageId: "033000000000001AAA",
      SubscriberPackageName: "Example Managed Package",
      SubscriberPackageNamespace: "examplepkg",
      SubscriberPackageVersionId: "04t000000000001AAA",
      SubscriberPackageVersionName: "Synthetic Release",
      SubscriberPackageVersionNumber: "1.2.3.4"
    },
    {
      Id: "0A3000000000002AAA",
      SubscriberPackageName: "Unrelated Package",
      SubscriberPackageNamespace: "otherpkg",
      SubscriberPackageVersionNumber: "9.9.9.9"
    }
  ]});
} else if (args[0] === "sobject" && args[1] === "describe") {
  out({status: 0, result: {
    name: "ExampleManagedObject__c",
    label: "Sensitive label is discarded",
    fields: [
      {name: "Amount__c", type: "double", label: "Amount"},
      {name: "Name", type: "string", label: "Name", picklistValues: [{value: "private"}]}
    ]
  }});
} else {
  process.exitCode = 3;
}
"""


FAKE_MCP = r"""
import { appendFileSync } from "node:fs";
import { createInterface } from "node:readline";
if (process.env.SF_FAKE_MCP_MARKER) appendFileSync(process.env.SF_FAKE_MCP_MARKER, "started\n");
const lines = createInterface({input: process.stdin});
const send = (message) => process.stdout.write(JSON.stringify(message) + "\n");
lines.on("line", (line) => {
  const message = JSON.parse(line);
  if (message.method === "initialize") {
    send({jsonrpc: "2.0", id: message.id, result: {
      protocolVersion: "2025-06-18", capabilities: {tools: {}}, serverInfo: {name: "fake", version: "1"}
    }});
    return;
  }
  if (message.method !== "tools/call") return;
  if (process.env.SF_FAKE_MCP_ERROR === "1") {
    send({jsonrpc: "2.0", id: message.id, result: {
      isError: true, content: [{type: "text", text: "synthetic failure"}]
    }});
    return;
  }
  const input = message.params.arguments;
  let payload;
  if (input.query.includes("FROM Organization")) {
    payload = {done: true, totalSize: 1, records: [
      {attributes: {type: "Organization", url: "/private"}, Id: "00D000000000001AAA", IsSandbox: process.env.SF_FAKE_IS_SANDBOX !== "false"}
    ]};
  } else if (input.query.includes("FROM InstalledSubscriberPackage")) {
    const build = process.env.SF_FAKE_MISMATCH === "1" ? 5 : 4;
    payload = {done: true, totalSize: 1, records: [{
      attributes: {type: "InstalledSubscriberPackage", url: "/private"},
      SubscriberPackage: {NamespacePrefix: "examplepkg", Name: "Example Managed Package"},
      SubscriberPackageVersion: {Name: "Synthetic Release", MajorVersion: 1, MinorVersion: 2, PatchVersion: 3, BuildNumber: build}
    }]};
  } else if (input.query.includes("FROM EntityDefinition")) {
    payload = {done: true, totalSize: 1, records: [
      {attributes: {url: "/private"}, QualifiedApiName: "ExampleManagedObject__c"}
    ]};
  } else if (input.query.includes("FROM FieldDefinition")) {
    payload = {done: true, totalSize: 2, records: [
      {attributes: {url: "/private"}, QualifiedApiName: "Name", DataType: "Text(80)"},
      {attributes: {url: "/private"}, QualifiedApiName: "Amount__c", DataType: "Number(18, 2)"}
    ]};
  } else if (input.query.includes("COUNT(Id)")) {
    payload = {done: true, totalSize: 1, records: [
      {attributes: {type: "AggregateResult"}, recordCount: 1204}
    ]};
  } else if (input.query.includes("FROM Contact")) {
    payload = {done: true, totalSize: 2, records: [
      {attributes: {type: "Contact", url: "/private"}, Name: "Ada Example", Email: "ada@example.com", AccountId: "001000000000001AAA", Status__c: "Active"},
      {attributes: {type: "Contact", url: "/private"}, Name: "Bob Example", Email: "bob@example.com", AccountId: "001000000000002AAA", Status__c: "Draft"}
    ]};
  } else if (input.query.includes("FROM Case")) {
    payload = {done: false, totalSize: 5000, records: [
      {attributes: {type: "Case", url: "/private"}, Subject: "Synthetic truncated page"}
    ]};
  } else {
    send({jsonrpc: "2.0", id: message.id, result: {isError: true, content: [{type: "text", text: "denied"}]}});
    return;
  }
  send({jsonrpc: "2.0", id: message.id, result: {
    isError: false,
    content: [{type: "text", text: "SOQL query results:\n\n" + JSON.stringify(payload, null, 2)}]
  }});
});
"""


def local_config(expected_host: str = HOST) -> dict[str, Any]:
    return {
        "salesforce": {
            "orgs": [
                {
                    "alias": "dev-sbx",
                    "environment": "development",
                    "allowAgentRead": True,
                    "allowAgentWrite": False,
                    "allowAgentReview": True,
                    "expectedInstanceHost": expected_host,
                    "expectedOrganizationId": ORG_ID,
                }
            ],
            "review": {
                "enabled": True,
                "apiVersion": "67.0",
                "requireDualSource": True,
                "allowedPackageNamespaces": ["examplepkg"],
                "allowedObjectApiNames": ["ExampleManagedObject__c"],
                "maxObjectsPerCall": 10,
                "maxFieldsPerObject": 500,
                "evidenceMaxAgeMinutes": 30,
            },
        }
    }


class ReviewFacade:
    def __init__(
        self,
        directory: Path,
        *,
        mismatch: bool = False,
        expected_host: str = HOST,
        cli_host: str = HOST,
        mcp_error: bool = False,
        cli_package_error: bool = False,
        allowed_objects: Any = "default",
        scoped_enumeration: bool = False,
        alias: str = "dev-sbx",
        drop_org_entry: bool = False,
        allow_any_non_production: bool = False,
        is_sandbox: bool = True,
    ):
        config_path = directory / "harness.local.json"
        policy_path = directory / "salesforce-review-policy.json"
        cli_path = directory / "fake-cli.mjs"
        mcp_path = directory / "fake-mcp.mjs"
        marker_path = directory / "mcp-started.txt"
        config = local_config(expected_host)
        if allowed_objects is None:
            del config["salesforce"]["review"]["allowedObjectApiNames"]
        elif allowed_objects != "default":
            config["salesforce"]["review"]["allowedObjectApiNames"] = allowed_objects
        if scoped_enumeration:
            config["safety"] = {"allowScopedEnumeration": True}
        if drop_org_entry:
            config["salesforce"]["orgs"] = []
        if allow_any_non_production:
            config["salesforce"]["review"]["allowAnyNonProduction"] = True
        config_path.write_text(json.dumps(config), encoding="utf-8")
        policy_path.write_text(
            (ROOT / "config" / "salesforce-review-policy.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        cli_path.write_text(textwrap.dedent(FAKE_CLI), encoding="utf-8")
        mcp_path.write_text(textwrap.dedent(FAKE_MCP), encoding="utf-8")
        self.marker_path = marker_path
        env = {
            **os.environ,
            "SF_HARNESS_TEST_MODE": "1",
            "SF_HARNESS_CONFIG_PATH": str(config_path),
            "SF_HARNESS_REVIEW_POLICY_PATH": str(policy_path),
            "SF_HARNESS_SF_EXECUTABLE": "node",
            "SF_HARNESS_SF_ARGS_JSON": json.dumps([str(cli_path)]),
            "SF_HARNESS_MCP_COMMAND": "node",
            "SF_HARNESS_MCP_ARGS_JSON": json.dumps([str(mcp_path)]),
            "SF_FAKE_MCP_MARKER": str(marker_path),
            "SF_FAKE_MISMATCH": "1" if mismatch else "0",
            "SF_FAKE_INSTANCE_HOST": cli_host,
            "SF_FAKE_MCP_ERROR": "1" if mcp_error else "0",
            "SF_FAKE_CLI_PACKAGE_ERROR": "1" if cli_package_error else "0",
            "SF_FAKE_IS_SANDBOX": "true" if is_sandbox else "false",
        }
        self.process = subprocess.Popen(
            ["node", str(ROOT / "scripts" / "salesforce_review_server.mjs"), "--org", alias],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 1

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        request_id = self.next_id
        self.next_id += 1
        self.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assert_response(response, request_id)
        return response["result"]

    @staticmethod
    def assert_response(response: dict[str, Any], request_id: int) -> None:
        if response.get("id") != request_id or "error" in response:
            raise AssertionError(response)

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return result["structuredContent"]

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()


class SalesforceReviewFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (ROOT / "schemas" / "salesforce-org-review-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )

    def assert_valid_evidence(self, evidence: dict[str, Any]) -> None:
        errors = list(
            Draft202012Validator(
                self.schema, format_checker=FormatChecker()
            ).iter_errors(evidence)
        )
        self.assertEqual(errors, [], [error.message for error in errors])
        without_hash = {key: value for key, value in evidence.items() if key != "sha256"}
        canonical = json.dumps(
            without_hash,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(evidence["sha256"], hashlib.sha256(canonical).hexdigest())

    def assert_invalid_evidence(self, evidence: dict[str, Any]) -> None:
        errors = list(
            Draft202012Validator(
                self.schema, format_checker=FormatChecker()
            ).iter_errors(evidence)
        )
        self.assertNotEqual(errors, [])

    def test_dynamic_lane_admits_unlisted_alias_on_live_proof(self) -> None:
        # Owner decision 2026-07-31: with allowAnyNonProduction, an alias with no config entry
        # is admitted purely on live identity proof and reported as environment=dynamic.
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                alias="scratch-box",
                drop_org_entry=True,
                allow_any_non_production=True,
                cli_host=SCRATCH_HOST,
                allowed_objects=None,
            )
            try:
                facade.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                identity = facade.call("review_org_identity")
                soql = facade.call("review_soql_query", {"query": "SELECT Id FROM Contact"})
            finally:
                facade.close()
            for evidence in (identity, soql):
                self.assert_valid_evidence(evidence)
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assertEqual(evidence["target"]["environment"], "dynamic")
                serialized = json.dumps(evidence)
                self.assertNotIn(SCRATCH_HOST, serialized)
                self.assertNotIn(ORG_ID, serialized)
            self.assertTrue(identity["target"]["isSandbox"])

    def test_dynamic_lane_verifies_developer_edition_with_is_sandbox_false(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                alias="devmp",
                drop_org_entry=True,
                allow_any_non_production=True,
                cli_host="orgfarm-x-dev-ed.develop.my.salesforce.com",
                is_sandbox=False,
                allowed_objects=None,
            )
            try:
                facade.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                identity = facade.call("review_org_identity")
            finally:
                facade.close()
            self.assert_valid_evidence(identity)
            self.assertEqual(identity["status"], "VERIFIED")
            self.assertEqual(identity["target"]["environment"], "dynamic")
            self.assertFalse(identity["target"]["isSandbox"])

    def test_dynamic_lane_refuses_spoofed_developer_edition_sandbox_flag(self) -> None:
        # A develop.my.salesforce.com host must report IsSandbox=false; true means the org's
        # signature is inconsistent and the identity gate fails closed.
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                alias="devmp",
                drop_org_entry=True,
                allow_any_non_production=True,
                cli_host="orgfarm-x-dev-ed.develop.my.salesforce.com",
                is_sandbox=True,
                allowed_objects=None,
            )
            try:
                facade.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                identity = facade.call("review_org_identity")
            finally:
                facade.close()
            self.assert_valid_evidence(identity)
            self.assertNotEqual(identity["status"], "VERIFIED")
            self.assertIn("NOT_SANDBOX", identity["warnings"])

    def test_tools_are_exact_and_verified_evidence_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                facade.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                tools = facade.request("tools/list")["tools"]
                self.assertEqual(
                    [tool["name"] for tool in tools],
                    [
                        "review_org_identity",
                        "review_installed_packages",
                        "review_configured_orgs",
                        "review_object_contract",
                        "review_soql_query",
                    ],
                )

                identity = facade.call("review_org_identity")
                packages = facade.call("review_installed_packages")
                object_contract = facade.call(
                    "review_object_contract",
                    {"objectApiName": "ExampleManagedObject__c"},
                )
                for evidence in (identity, packages, object_contract):
                    self.assertEqual(evidence["status"], "VERIFIED")
                    self.assert_valid_evidence(evidence)
                    serialized = json.dumps(evidence)
                    for forbidden in (
                        "SHOULD_NEVER_ESCAPE",
                        "sensitive-client",
                        "person@example.invalid",
                        "force://",
                        ORG_ID,
                        HOST,
                        "attributes",
                        "/private",
                    ):
                        self.assertNotIn(forbidden, serialized)
                package_text = json.dumps(packages)
                self.assertIn("examplepkg", package_text)
                self.assertNotIn("otherpkg", package_text)
                self.assertNotIn("Unrelated Package", package_text)
                self.assertNotIn("packageCount", packages["facts"])
                self.assertEqual(
                    object_contract["facts"]["object"]["fields"],
                    [
                        {"name": "Amount__c", "typeFamily": "number"},
                        {"name": "Name", "typeFamily": "text"},
                    ],
                )
            finally:
                facade.close()

    def test_package_disagreement_returns_mismatch_without_unreconciled_values(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), mismatch=True)
            try:
                evidence = facade.call("review_installed_packages")
                self.assertEqual(evidence["status"], "MISMATCH")
                self.assertEqual(evidence["warnings"], ["EVIDENCE_MISMATCH"])
                self.assertNotIn("packages", evidence["facts"])
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_identity_mismatch_blocks_before_mcp_child_starts(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                expected_host="other--dev.sandbox.my.salesforce.com",
            )
            try:
                evidence = facade.call("review_org_identity")
                self.assertEqual(evidence["status"], "BLOCKED")
                self.assertIn("IDENTITY_HOST_MISMATCH", evidence["warnings"])
                self.assertFalse(facade.marker_path.exists())
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_scratch_org_identity_is_verified_by_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                expected_host=SCRATCH_HOST,
                cli_host=SCRATCH_HOST,
            )
            try:
                evidence = facade.call("review_org_identity")
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assertTrue(evidence["target"]["expectedHostMatched"])
                self.assertTrue(evidence["target"]["expectedOrgIdMatched"])
                self.assertTrue(evidence["target"]["isSandbox"])
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_scratch_org_instance_url_with_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                expected_host=SCRATCH_HOST,
                cli_host=f"{SCRATCH_HOST}/unexpected",
            )
            try:
                evidence = facade.call("review_org_identity")
                self.assertEqual(evidence["status"], "BLOCKED")
                self.assertIn("IDENTITY_HOST_MISMATCH", evidence["warnings"])
                self.assertFalse(facade.marker_path.exists())
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_model_supplied_query_or_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                evidence = facade.call(
                    "review_org_identity",
                    {"query": "SELECT Name FROM Contact", "usernameOrAlias": "other"},
                )
                self.assertEqual(evidence["status"], "BLOCKED")
                self.assertEqual(evidence["warnings"], ["QUERY_PROFILE_DENIED"])
                self.assertFalse(facade.marker_path.exists())
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_composed_query_rows_are_sanitized_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), allowed_objects=None)
            try:
                evidence = facade.call(
                    "review_soql_query",
                    {"query": "SELECT Name, Email, AccountId, Status__c FROM Contact"},
                )
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assert_valid_evidence(evidence)
                facts = evidence["facts"]["soqlQuery"]
                self.assertEqual(facts["fromObjects"], ["Contact"])
                self.assertEqual(facts["limit"], 200)
                self.assertFalse(facts["hasWhere"])
                self.assertFalse(facts["useToolingApi"])
                self.assertEqual(facts["matched"], 2)
                self.assertEqual(facts["records"][0]["Email"], "redacted-email")
                self.assertEqual(facts["records"][0]["AccountId"], "redacted-id")
                self.assertEqual(facts["records"][0]["Name"], "Ada Example")
                self.assertIn("email:records[].Email", facts["sanitization"]["redactions"])
                self.assertIn("id:records[].AccountId", facts["sanitization"]["redactions"])
                self.assertEqual(
                    evidence["reconciliation"]["status"], "IDENTITY_MATCH_ONLY"
                )
                self.assertFalse(evidence["completeness"]["dualSource"])
                serialized = json.dumps(evidence)
                for forbidden in (
                    "ada@example.com",
                    "bob@example.com",
                    "001000000000001AAA",
                    "attributes",
                    "/private",
                ):
                    self.assertNotIn(forbidden, serialized)
            finally:
                facade.close()

    def test_composed_aggregate_query_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), allowed_objects=None)
            try:
                evidence = facade.call(
                    "review_soql_query",
                    {"query": "SELECT COUNT(Id) recordCount FROM Opportunity"},
                )
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assert_valid_evidence(evidence)
                facts = evidence["facts"]["soqlQuery"]
                self.assertEqual(facts["records"], [{"recordCount": 1204}])
                self.assertEqual(facts["matched"], 1)
                self.assertEqual(facts["fromObjects"], ["Opportunity"])
            finally:
                facade.close()

    def test_composed_query_truncation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), allowed_objects=None)
            try:
                evidence = facade.call(
                    "review_soql_query",
                    {"query": "SELECT Subject FROM Case LIMIT 50"},
                )
                self.assertEqual(evidence["status"], "INCOMPLETE")
                self.assertIn("RESULT_TRUNCATED", evidence["warnings"])
                self.assertTrue(evidence["completeness"]["truncated"])
                self.assertEqual(evidence["facts"], {})
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_composed_query_validator_blocks_before_any_process(self) -> None:
        denied = (
            ("SELECT Id FROM Account; DELETE FROM Account", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id FROM Account -- comment", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id /* c */ FROM Account", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id FROM Account FOR UPDATE", "QUERY_VALIDATION_DENIED"),
            ("UPDATE Account SET Name = 'x'", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id FROM Account WHERE Name = '${X}'", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id FROM Account LIMIT 500", "QUERY_VALIDATION_DENIED"),
            ("SELECT Id FROM NamedCredential", "OBJECT_NOT_ALLOWLISTED"),
            ("SELECT Id FROM namedcredential", "OBJECT_NOT_ALLOWLISTED"),
            ("SELECT Body FROM ApexLog", "OBJECT_NOT_ALLOWLISTED"),
            ("SELECT SandboxName FROM SandboxInfo", "OBJECT_NOT_ALLOWLISTED"),
            # Server-side length floor mirrors the hook's 8-char bound and the tool schema's
            # minLength (tests/test_safety_hooks.py pins the hook side of this mirror).
            ("SELECT ", "QUERY_VALIDATION_DENIED"),
        )
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), allowed_objects=None)
            try:
                for query, warning in denied:
                    with self.subTest(query=query):
                        evidence = facade.call("review_soql_query", {"query": query})
                        self.assertEqual(evidence["status"], "BLOCKED")
                        self.assertEqual(evidence["warnings"], [warning])
                        self.assert_valid_evidence(evidence)
                self.assertFalse(facade.marker_path.exists())
            finally:
                facade.close()

    def test_composed_query_respects_explicit_object_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                evidence = facade.call(
                    "review_soql_query", {"query": "SELECT Name FROM Contact"}
                )
                self.assertEqual(evidence["status"], "BLOCKED")
                self.assertEqual(evidence["warnings"], ["OBJECT_NOT_ALLOWLISTED"])
                self.assertFalse(facade.marker_path.exists())
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_never_query_deny_set_is_pinned(self) -> None:
        # Widening or shrinking the secret-adjacent deny-set must be a deliberate, reviewed
        # change — same discipline as the role-grant pins in test_guard_parser_contract.
        source = (ROOT / "scripts" / "salesforce_review_server.mjs").read_text(encoding="utf-8")
        match = re.search(
            r"NEVER_QUERY_OBJECTS = Object\.freeze\(new Set\(\[(.*?)\]\)\)", source, re.S
        )
        self.assertIsNotNone(match)
        names = set(re.findall(r'"([a-z0-9]+)"', match.group(1)))
        self.assertEqual(
            names,
            {
                "namedcredential",
                "externalcredential",
                "connectedapplication",
                "authprovider",
                "authsession",
                "loginhistory",
                "loginip",
                "oauthtoken",
                "setupaudittrail",
                "twofactorinfo",
                "twofactormethodsinfo",
                "sandboxinfo",
                "sandboxprocess",
                "apexlog",
                "eventlogfile",
                "certificate",
                "samlssoconfig",
            },
        )

    def test_configured_orgs_envelopes_are_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), scoped_enumeration=True)
            try:
                evidence = facade.call("review_configured_orgs")
                self.assertEqual(evidence["status"], "VERIFIED")
                self.assertEqual(evidence["reviewType"], "configured-orgs")
                self.assertEqual(evidence["facts"]["orgCount"], 1)
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                evidence = facade.call("review_configured_orgs")
                self.assertEqual(evidence["status"], "BLOCKED")
                self.assertEqual(evidence["warnings"], ["SCOPED_ENUMERATION_DISABLED"])
                self.assert_valid_evidence(evidence)
            finally:
                facade.close()

    def test_incomplete_evidence_distinguishes_one_source_from_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), mcp_error=True)
            try:
                one_source = facade.call("review_installed_packages")
                self.assertEqual(one_source["status"], "INCOMPLETE")
                self.assertEqual(one_source["reconciliation"]["status"], "SINGLE_SOURCE")
                self.assertTrue(one_source["sources"]["cli"]["complete"])
                self.assertFalse(one_source["sources"]["mcp"]["complete"])
                self.assert_valid_evidence(one_source)
            finally:
                facade.close()

        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(
                Path(name),
                mcp_error=True,
                cli_package_error=True,
            )
            try:
                no_sources = facade.call("review_installed_packages")
                self.assertEqual(no_sources["status"], "INCOMPLETE")
                self.assertEqual(no_sources["reconciliation"]["status"], "NOT_RUN")
                self.assertFalse(no_sources["sources"]["cli"]["complete"])
                self.assertFalse(no_sources["sources"]["mcp"]["complete"])
                self.assert_valid_evidence(no_sources)
            finally:
                facade.close()

    def test_schema_rejects_cross_field_contract_contradictions(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                verified = facade.call("review_org_identity")
            finally:
                facade.close()

        mutations: list[dict[str, Any]] = []

        wrong_status = copy.deepcopy(verified)
        wrong_status["status"] = "MISMATCH"
        mutations.append(wrong_status)

        swapped_source = copy.deepcopy(verified)
        swapped_source["sources"]["cli"]["kind"] = "salesforce-mcp"
        mutations.append(swapped_source)

        unavailable_complete_source = copy.deepcopy(verified)
        unavailable_complete_source["sources"]["cli"]["version"] = "unavailable"
        mutations.append(unavailable_complete_source)

        unproven_target = copy.deepcopy(verified)
        unproven_target["target"]["expectedOrgIdMatched"] = False
        mutations.append(unproven_target)

        inconsistent_reconciliation = copy.deepcopy(verified)
        inconsistent_reconciliation["reconciliation"]["comparisons"][0]["result"] = "MISMATCH"
        mutations.append(inconsistent_reconciliation)

        invented_comparison = copy.deepcopy(verified)
        invented_comparison["reconciliation"]["comparisons"][0]["fact"] = "organization-name"
        mutations.append(invented_comparison)

        incomplete_verified = copy.deepcopy(verified)
        incomplete_verified["completeness"]["complete"] = False
        mutations.append(incomplete_verified)

        arbitrary_fact = copy.deepcopy(verified)
        arbitrary_fact["facts"]["organizationName"] = "Invented"
        mutations.append(arbitrary_fact)

        warning_on_verified = copy.deepcopy(verified)
        warning_on_verified["warnings"] = ["MCP_TIMEOUT"]
        mutations.append(warning_on_verified)

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_invalid_evidence(mutation)

    def test_schema_rejects_mismatch_incomplete_and_blocked_fact_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), mismatch=True)
            try:
                mismatch = facade.call("review_installed_packages")
            finally:
                facade.close()
        mismatched_raw_facts = copy.deepcopy(mismatch)
        mismatched_raw_facts["facts"]["packages"] = []
        self.assert_invalid_evidence(mismatched_raw_facts)

        mismatch_without_mismatch = copy.deepcopy(mismatch)
        mismatch_without_mismatch["reconciliation"]["comparisons"][0]["result"] = "MATCH"
        self.assert_invalid_evidence(mismatch_without_mismatch)

        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name), mcp_error=True)
            try:
                incomplete = facade.call("review_installed_packages")
            finally:
                facade.close()
        incomplete_with_fact = copy.deepcopy(incomplete)
        incomplete_with_fact["facts"] = {"packages": []}
        self.assert_invalid_evidence(incomplete_with_fact)

        incomplete_claiming_both_sources = copy.deepcopy(incomplete)
        incomplete_claiming_both_sources["sources"]["mcp"]["complete"] = True
        self.assert_invalid_evidence(incomplete_claiming_both_sources)

        with tempfile.TemporaryDirectory() as name:
            facade = ReviewFacade(Path(name))
            try:
                blocked = facade.call(
                    "review_object_contract",
                    {"objectApiName": "NotAllowlisted__c"},
                )
            finally:
                facade.close()
        self.assert_valid_evidence(blocked)

        blocked_with_fact = copy.deepcopy(blocked)
        blocked_with_fact["facts"] = {"objectApiName": "NotAllowlisted__c"}
        self.assert_invalid_evidence(blocked_with_fact)

        blocked_without_blocking_reason = copy.deepcopy(blocked)
        blocked_without_blocking_reason["warnings"] = ["MCP_TIMEOUT"]
        self.assert_invalid_evidence(blocked_without_blocking_reason)


class SalesforceReviewConfigContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        harness_schema = json.loads(
            (ROOT / "schemas" / "harness-config.schema.json").read_text(encoding="utf-8")
        )
        cls.review_schema = harness_schema["properties"]["salesforce"]["properties"]["review"]
        cls.validator = Draft202012Validator(cls.review_schema)

    @staticmethod
    def review_config(*, enabled: bool) -> dict[str, Any]:
        return {
            "enabled": enabled,
            "apiVersion": "67.0",
            "requireDualSource": True,
            "allowedPackageNamespaces": ["examplepkg"] if enabled else [],
            "allowedObjectApiNames": ["ExampleManagedObject__c"] if enabled else [],
            "maxObjectsPerCall": 10,
            "maxFieldsPerObject": 500,
            "evidenceMaxAgeMinutes": 30,
        }

    def test_disabled_review_requires_empty_package_and_object_allowlists(self) -> None:
        disabled = self.review_config(enabled=False)
        self.assertEqual(list(self.validator.iter_errors(disabled)), [])

        for key, value in (
            ("allowedPackageNamespaces", ["examplepkg"]),
            ("allowedObjectApiNames", ["ExampleManagedObject__c"]),
        ):
            populated = copy.deepcopy(disabled)
            populated[key] = value
            with self.subTest(key=key):
                self.assertNotEqual(list(self.validator.iter_errors(populated)), [])

    def test_enabled_review_requires_both_nonempty_allowlists(self) -> None:
        enabled = self.review_config(enabled=True)
        self.assertEqual(list(self.validator.iter_errors(enabled)), [])

        for key in ("allowedPackageNamespaces", "allowedObjectApiNames"):
            empty = copy.deepcopy(enabled)
            empty[key] = []
            with self.subTest(key=key):
                self.assertNotEqual(list(self.validator.iter_errors(empty)), [])

    def test_server_refuses_to_start_when_review_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            config = local_config()
            config["salesforce"]["review"] = self.review_config(enabled=False)
            config_path = directory / "harness.local.json"
            policy_path = directory / "salesforce-review-policy.json"
            marker_path = directory / "mcp-started.txt"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            policy_path.write_text(
                (ROOT / "config" / "salesforce-review-policy.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["node", str(ROOT / "scripts" / "salesforce_review_server.mjs"), "--org", "dev-sbx"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "SF_HARNESS_TEST_MODE": "1",
                    "SF_HARNESS_CONFIG_PATH": str(config_path),
                    "SF_HARNESS_REVIEW_POLICY_PATH": str(policy_path),
                    "SF_FAKE_MCP_MARKER": str(marker_path),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("REVIEW_DISABLED", completed.stderr)
            self.assertFalse(marker_path.exists())

    def _startup_refusal(self, config: dict[str, Any]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            config_path = directory / "harness.local.json"
            policy_path = directory / "salesforce-review-policy.json"
            marker_path = directory / "mcp-started.txt"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            policy_path.write_text(
                (ROOT / "config" / "salesforce-review-policy.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts" / "salesforce_review_server.mjs"),
                    "--org",
                    "dev-sbx",
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "SF_HARNESS_TEST_MODE": "1",
                    "SF_HARNESS_CONFIG_PATH": str(config_path),
                    "SF_HARNESS_REVIEW_POLICY_PATH": str(policy_path),
                    "SF_FAKE_MCP_MARKER": str(marker_path),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertFalse(marker_path.exists())
            return completed

    def test_server_refuses_production_host_pins(self) -> None:
        # A production my.salesforce.com host never matches the non-production pin pattern.
        completed = self._startup_refusal(local_config("acme.my.salesforce.com"))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("CONFIG_INVALID", completed.stderr)

    def test_server_refuses_alias_marked_production_even_with_allow_any(self) -> None:
        # environment=production is the owner's explicit deny marker; allowAnyNonProduction
        # never overrides it.
        config = local_config()
        config["salesforce"]["orgs"][0] = {"alias": "dev-sbx", "environment": "production"}
        config["salesforce"]["review"]["allowAnyNonProduction"] = True
        completed = self._startup_refusal(config)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("ALIAS_MARKED_PRODUCTION", completed.stderr)

    def test_server_refuses_unlisted_alias_without_allow_any_non_production(self) -> None:
        config = local_config()
        config["salesforce"]["orgs"] = []
        completed = self._startup_refusal(config)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("ALIAS_NOT_ALLOWLISTED", completed.stderr)



class PinnedSalesforceMcpCompatibilityTests(unittest.TestCase):
    MCP_ROOT = ROOT / "node_modules" / "@salesforce" / "mcp"
    PROVIDER_ROOT = MCP_ROOT / "node_modules" / "@salesforce" / "mcp-provider-dx-core"

    def test_package_manifest_lockfile_and_installed_runtime_are_exact(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        installed = json.loads((self.MCP_ROOT / "package.json").read_text(encoding="utf-8"))
        provider = json.loads((self.PROVIDER_ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(package["dependencies"]["@salesforce/mcp"], "0.30.15")
        self.assertEqual(
            lock["packages"]["node_modules/@salesforce/mcp"]["version"],
            "0.30.15",
        )
        self.assertEqual(installed["version"], "0.30.15")
        self.assertEqual(provider["version"], "0.9.8")

    def test_pinned_server_still_supports_the_bounded_startup_flags(self) -> None:
        completed = subprocess.run(
            ["node", str(self.MCP_ROOT / "bin" / "run.js"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, output)
        for flag in ("--orgs=<value>", "--tools=<value>", "--no-telemetry"):
            with self.subTest(flag=flag):
                self.assertIn(flag, output)

    def test_pinned_query_tool_input_and_text_response_shape_match_facade_parser(self) -> None:
        query_source = (
            self.PROVIDER_ROOT / "lib" / "tools" / "run_soql_query.js"
        ).read_text(encoding="utf-8")
        for contract_fragment in (
            "query: z.string()",
            "usernameOrAlias: usernameOrAliasParam",
            "directory: directoryParam",
            "useToolingApi: useToolingApiParam",
            "return 'run_soql_query'",
            "outputSchema: undefined",
            "SOQL query results:\\n\\n",
        ):
            with self.subTest(fragment=contract_fragment):
                self.assertIn(contract_fragment, query_source)

        helper_uri = (self.PROVIDER_ROOT / "lib" / "shared" / "utils.js").as_uri()
        node_script = (
            f"import {{ textResponse }} from {json.dumps(helper_uri)};"
            "process.stdout.write(JSON.stringify(textResponse('SOQL query results:\\n\\n{}')));"
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", node_script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "isError": False,
                "content": [
                    {"type": "text", "text": "SOQL query results:\n\n{}"}
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
