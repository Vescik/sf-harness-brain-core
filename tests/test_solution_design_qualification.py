"""P8 qualification: the properties the rebuilt phase claims, checked as a set.

These are not unit tests of one function. Each case asserts something the Definition of Done
states about the *system*, and several of them exist to fail loudly if a later change quietly
reintroduces what a replacement phase removed.

What this module deliberately does NOT claim: native Windows behaviour, VS Code Policy
Diagnostics, or anything about the target managed package. Those are recorded as open in the
builder-side qualification report, not asserted here.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = _module("solution_design_core")
worker_module = _module("solution_design_worker")
mcp_server = ROOT / "scripts" / "solution_design_mcp_server.mjs"


class CanonicalPathTests(unittest.TestCase):
    """Exactly one Design Case creation and approval path exists."""

    def test_one_creation_path(self) -> None:
        prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(encoding="utf-8")
        skill = (ROOT / ".github/skills/solution-design/SKILL.md").read_text(encoding="utf-8")
        for text in (prompt, skill):
            self.assertNotIn("output/solution-design/", text)
            self.assertNotIn("ungoverned", text)
        self.assertIn("There is **one lane**", prompt)

    def test_the_five_phase_procedure_is_gone(self) -> None:
        skill = (ROOT / ".github/skills/solution-design/SKILL.md").read_text(encoding="utf-8")
        agent = (ROOT / ".github/agents/solution-designer.agent.md").read_text(encoding="utf-8")
        for text in (skill, agent):
            self.assertNotIn("DISCOVER", text)
            self.assertNotIn("five phases", text)
            self.assertNotIn("Phase 1", text)

    def test_the_designer_types_no_workflow_script(self) -> None:
        agent = (ROOT / ".github/agents/solution-designer.agent.md").read_text(encoding="utf-8")
        prompt = (ROOT / ".github/prompts/solution-design.prompt.md").read_text(encoding="utf-8")
        for text in (agent, prompt):
            self.assertNotIn("execute/runInTerminal", text)
            self.assertNotIn("work_record.py", text)

    def test_the_designer_holds_no_work_record_grant(self) -> None:
        guard = _module("copilot_role_guard")
        self.assertEqual(guard.WORK_RECORD_COMMANDS["solution-designer"], set())
        self.assertNotIn("output/solution-design/", guard.ALLOWED_PREFIXES["solution-designer"])

    def test_executor_authored_state_cannot_be_edited_directly(self) -> None:
        guard = _module("copilot_role_guard")
        for path in (
            ".ai/change-records/SD-2026-08-05-x/record.json",
            ".ai/change-records/SD-2026-08-05-x/evidence/EV-1.json",
            ".ai/change-records/SD-2026-08-05-x/candidates/CND-1/bundle.json",
            ".ai/change-records/SD-2026-08-05-x/approvals/AP-1.json",
            ".ai/change-records/SD-2026-08-05-x/reviews/DR-1.json",
            ".ai/change-records/SD-2026-08-05-x/divergences/DV-1.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(guard.is_governed_record_path(path))
        # The narrative stays freely editable — that is the point of the split.
        self.assertFalse(
            guard.is_governed_record_path(".ai/change-records/SD-2026-08-05-x/design.md")
        )


class CapabilityManifestTests(unittest.TestCase):
    """An unsupported capability must fail closed, and the v1 manifest must be complete."""

    manifest = core.load_capabilities()

    def test_every_concern_profile_is_implemented(self) -> None:
        self.assertEqual(
            sorted(self.manifest["concernProfiles"]), sorted(core.CONCERN_PROFILES)
        )

    def test_every_declared_probe_kind_has_a_deriver_or_a_reason(self) -> None:
        derivers = _module("sampling_derivers")
        # config-snapshot is the governed persistence exception rather than a derivation, and
        # object-contract is produced by the Salesforce facade, not by this library.
        exceptions = {"config-snapshot", "object-contract"}
        missing = sorted(
            set(self.manifest["probeKinds"]) - set(derivers.DERIVERS) - exceptions
        )
        self.assertEqual(missing, [])

    def test_every_allowed_transition_is_declared(self) -> None:
        declared = set(self.manifest["transitions"])
        for source, targets in core.ALLOWED_TRANSITIONS.items():
            for target in targets:
                with self.subTest(transition=f"{source}->{target}"):
                    self.assertIn(f"{source}->{target}", declared)

    def test_every_generated_section_has_a_renderer(self) -> None:
        self.assertEqual(
            sorted(self.manifest["generatedSections"]), sorted(core.GENERATED_SECTIONS)
        )

    def test_a_capability_outside_the_manifest_is_fail_closed(self) -> None:
        trimmed = json.loads(json.dumps(self.manifest))
        trimmed["probeKinds"] = []
        state = core.new_case_state("SD-2026-08-05-x", "w", at="2026-08-05T09:00:00Z")
        state["probes"] = [
            {
                "probeId": "P-001",
                "questionId": "Q-001",
                "origin": "question",
                "kind": "object-baseline",
                "target": {"objectApiName": "Case", "slice": None},
                "queryDigest": None,
                "suggestedSoql": None,
                "replaySpec": None,
                "expectedResultShape": "aggregate",
                "completenessCriterion": "count",
                "requiredness": "advisory",
                "conditionalPredicate": None,
                "notApplicableReason": None,
                "persistenceMode": "aggregate",
                "freshnessClass": "volume-observation",
                "stopCondition": "known",
                "status": "planned",
                "receiptRef": None,
                "fitnessVerdict": None,
                "decisionImpact": None,
                "recheckPlan": "never",
            }
        ]
        report = core.evaluate(state, design_text="# x\n", capabilities=trimmed)
        self.assertEqual(report["result"], "OPEN")
        self.assertTrue(
            any(gap["requiredClosure"] == "UNSUPPORTED_CAPABILITY" for gap in report["gaps"])
        )


class ToolSurfaceTests(unittest.TestCase):
    """No undeclared tool is reachable, and no human decision is model-authored."""

    source = mcp_server.read_text(encoding="utf-8")

    def declared(self) -> list[dict]:
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                'import { TOOL_DEFINITIONS } from "./scripts/solution_design_mcp_server.mjs";'
                " console.log(JSON.stringify(TOOL_DEFINITIONS));",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_every_declared_tool_is_granted_in_the_validator(self) -> None:
        validator = _module("validate_harness")
        for tool in self.declared():
            with self.subTest(tool=tool["name"]):
                self.assertIn(f"solution-design/{tool['name']}", validator.ALLOWED_TOOLS)

    def test_no_internal_operation_is_exposed_as_a_tool(self) -> None:
        names = {tool["name"] for tool in self.declared()}
        for internal in (
            "record-human-input",
            "confirm-candidate",
            "request-candidate-revision",
            "transfer-case-writer",
        ):
            with self.subTest(operation=internal):
                self.assertNotIn(internal, names)
                self.assertNotIn(internal.replace("-", "_"), names)

    def test_no_request_tool_carries_a_decision_field(self) -> None:
        for tool in self.declared():
            if not tool["name"].startswith("design_request_"):
                continue
            with self.subTest(tool=tool["name"]):
                for key in tool["inputSchema"]["properties"]:
                    self.assertNotRegex(key, r"(?i)answer|approv|decision|verdict|status")

    def test_the_wrapper_never_recomputes_a_digest(self) -> None:
        # The Python core is the single digest authority; a second canonicalizer in Node would
        # disagree on Unicode or integer edges exactly when it matters least visibly.
        self.assertNotIn("sd-c14n", self.source)
        self.assertNotIn("candidateDigestInput", self.source)

    def test_elicitation_has_no_fallback(self) -> None:
        self.assertIn("UNSUPPORTED_HOST_CAPABILITY", self.source)
        self.assertIn("clientSupportsElicitation", self.source)


class ConcurrencyQualificationTests(unittest.TestCase):
    """Eight users across cases; one named writer per case; explicit transfer."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        temporary = tempfile.TemporaryDirectory(prefix="sd-qual-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        # Only `config/` is read out of the temp root — schemas and instruction files resolve
        # against the real repository root — and no test here needs git history, so this stays
        # a single small copy rather than three directories and a subprocess.
        (self.root / "config").mkdir(parents=True)
        shutil.copytree(ROOT / "config", self.root / "config", dirs_exist_ok=True)
        (self.root / ".ai").mkdir()
        self.worker = worker_module.Worker(self.root)

    def call(self, operation: str, **params):
        return worker_module.handle(self.worker, {"id": 1, "op": operation, "params": params})

    def test_eight_writers_own_eight_cases_concurrently(self) -> None:
        versions = {}
        for index in range(1, 9):
            case = f"SD-2026-08-05-case-{index}"
            response = self.call("open", caseId=case, writerId=f"writer-{index}", title=f"case {index}")
            self.assertTrue(response["ok"], response.get("error"))
            versions[case] = (response["result"]["caseVersion"], f"writer-{index}")
        # Each writer can still mutate their own case afterwards: the lease is per case.
        for case, (version, writer) in versions.items():
            response = self.call(
                "apply",
                caseId=case,
                writerId=writer,
                expectedCaseVersion=version,
                operations=[
                    {
                        "kind": "question-upsert",
                        "payload": {
                            "questionId": "Q-001",
                            "question": "Which surface does this touch?",
                            "materiality": "advisory",
                            "requiredAuthority": ["knowledge-entry"],
                            "status": "open",
                            "answer": None,
                            "evidenceRefs": [],
                            "limitations": [],
                            "route": "grounding",
                        },
                    }
                ],
            )
            self.assertTrue(response["ok"], response.get("error"))

    def test_a_second_writer_is_rejected_and_transfer_is_explicit(self) -> None:
        case = "SD-2026-08-05-owned"
        opened = self.call("open", caseId=case, writerId="writer-one", title="t")["result"]
        operations = [
            {
                "kind": "question-upsert",
                "payload": {
                    "questionId": "Q-001",
                    "question": "q",
                    "materiality": "advisory",
                    "requiredAuthority": ["knowledge-entry"],
                    "status": "open",
                    "answer": None,
                    "evidenceRefs": [],
                    "limitations": [],
                    "route": "grounding",
                },
            }
        ]
        rejected = self.call(
            "apply",
            caseId=case,
            writerId="writer-two",
            expectedCaseVersion=opened["caseVersion"],
            operations=operations,
        )
        self.assertEqual(rejected["error"]["code"], "WRONG_WRITER")
        transferred = self.call(
            "transfer-case-writer",
            caseId=case,
            expectedCaseVersion=opened["caseVersion"],
            targetWriterId="writer-two",
            elicitation={"identity": "writer-one", "nonceDigest": "sha256:" + "a" * 64},
        )["result"]
        self.assertEqual(transferred["writer"]["writerId"], "writer-two")
        # The previous owner's token is invalid immediately, not merely their authority.
        stale = self.call(
            "apply",
            caseId=case,
            writerId="writer-one",
            expectedCaseVersion=opened["caseVersion"],
            operations=operations,
        )
        self.assertIn(stale["error"]["code"], {"WRONG_WRITER", "STALE_CASE_VERSION"})


class RetiredSurfaceQualificationTests(unittest.TestCase):
    """Every replacement phase removed its predecessor."""

    def test_the_retired_manifest_is_enforced_and_non_empty(self) -> None:
        manifest = json.loads(
            (ROOT / "config/retired-surfaces.json").read_text(encoding="utf-8")
        )
        self.assertTrue(manifest["retired"])
        validator = _module("validate_harness")
        audit = validator.Audit()
        validator.check_retired_surfaces(audit)
        self.assertEqual(audit.errors, [])
        self.assertGreater(audit.checks, 0)

    def test_no_runtime_package_acquisition_anywhere_in_the_mcp_configuration(self) -> None:
        for path in (".vscode/mcp.json", ".github/mcp.json"):
            with self.subTest(path=path):
                self.assertNotIn("npx", (ROOT / path).read_text(encoding="utf-8"))

    def test_every_third_party_python_import_is_admitted(self) -> None:
        validator = _module("validate_harness")
        audit = validator.Audit()
        validator.check_dependency_admissions(audit)
        self.assertEqual(audit.errors, [])


if __name__ == "__main__":
    unittest.main()
