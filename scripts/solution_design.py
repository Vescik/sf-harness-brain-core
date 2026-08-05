#!/usr/bin/env python3
"""Read-only Design Case diagnostics and test harness.

This is the public Python entry point and it is **read-only by construction**. It has no
transition verb, no approval verb and no way to write a case: every mutation goes through the
MCP runtime and its internal NDJSON worker. That split is the point — the previous architecture
let an agent type workflow commands, and the rebuild removes that surface rather than guarding
it.

Verbs:

  check <case-id>        run every computed gate and print the routed gaps
  context <case-id>      print the current case summary
  render <case-id>       print design.md as the runtime would regenerate it (does not write)
  registry               validate the rule applicability registry against the instruction files
  capabilities           print the active capability manifest and its digest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import solution_design_core as core
    from solution_design_worker import CaseStore, Worker, WorkerError
except ModuleNotFoundError:  # imported as scripts.solution_design by unit tests
    from scripts import solution_design_core as core
    from scripts.solution_design_worker import CaseStore, Worker, WorkerError


HARNESS_ROOT = Path(__file__).resolve().parents[1]

READ_ONLY_COMMANDS = ("check", "context", "render", "registry", "capabilities")


def command_check(worker: Worker, case_id: str) -> dict:
    return worker.op_check({"caseId": case_id})


def command_context(worker: Worker, case_id: str) -> dict:
    return worker.op_context({"caseId": case_id, "view": "all"})


def command_render(worker: Worker, case_id: str) -> str:
    record, design = worker.store.load(case_id)
    return core.render_generated_sections(design, record["solutionDesign"])


def command_registry() -> dict:
    rule_map = core.load_rule_map()
    definitions = core.canonical_rule_definitions()
    problems = core.validate_rule_registry(rule_map, definitions)
    return {
        "policyVersion": rule_map["policyVersion"],
        "canonicalRules": len(definitions),
        "selectorDriven": len(rule_map["rules"]),
        "manualApplicability": len(rule_map["manualApplicability"]),
        "problems": problems,
    }


def command_capabilities() -> dict:
    manifest = core.load_capabilities()
    return {
        "manifestVersion": manifest["manifestVersion"],
        "gateEvaluatorVersion": manifest["gateEvaluatorVersion"],
        "capabilityManifestDigest": core.capability_digest(manifest),
        "concernProfiles": manifest["concernProfiles"],
        "probeKinds": manifest["probeKinds"],
        "evidenceSourceTypes": manifest["evidenceSourceTypes"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None, help="workspace root (defaults to this repository)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "context", "render"):
        sub = subparsers.add_parser(name)
        sub.add_argument("case_id")
    subparsers.add_parser("registry")
    subparsers.add_parser("capabilities")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = Path(arguments.root).resolve() if arguments.root else HARNESS_ROOT
    try:
        if arguments.command == "registry":
            result = command_registry()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1 if result["problems"] else 0
        if arguments.command == "capabilities":
            print(json.dumps(command_capabilities(), indent=2, sort_keys=True))
            return 0
        worker = Worker(root)
        if arguments.command == "render":
            sys.stdout.write(command_render(worker, arguments.case_id))
            return 0
        handler = {"check": command_check, "context": command_context}[arguments.command]
        result = handler(worker, arguments.case_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        if arguments.command == "check":
            return 0 if result["result"] == "READY" else 2
        return 0
    except (WorkerError, core.SolutionDesignError) as exc:
        print(f"solution-design: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
