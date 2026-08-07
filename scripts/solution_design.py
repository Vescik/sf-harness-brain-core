#!/usr/bin/env python3
"""Read-only Solution Design loop CLI: diagnostics only, no mutation verbs.

Mutations flow exclusively through the MCP server's four tools; this CLI exists for CI and
operators. `check` prints the advisory gap report, `render` re-renders design.md from state,
`triggers` validates the H1 rule-trigger table against the live instructions files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import solution_design_core as core
    import solution_design_worker as worker_module
except ModuleNotFoundError:
    from scripts import solution_design_core as core
    from scripts import solution_design_worker as worker_module

READ_ONLY_COMMANDS = ("check", "render", "triggers")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=None, help="workspace root (defaults to this repository)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "render"):
        sub = subparsers.add_parser(name)
        sub.add_argument("case_id")
    subparsers.add_parser("triggers")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = Path(arguments.root).resolve() if arguments.root else Path(worker_module.HARNESS_ROOT)
    try:
        if arguments.command == "triggers":
            table = core.load_rule_triggers()
            print(json.dumps({
                "policyVersion": table.get("policyVersion"),
                "always": len(table.get("always", [])),
                "matrixCells": len(table.get("byArtefactAction", {})),
                "neverTriggered": len(table.get("neverTriggered", {})),
                "outcome": "VALID",
            }, indent=2, sort_keys=True))
            return 0
        worker = worker_module.Worker(root)
        if arguments.command == "render":
            record = worker.store.load(arguments.case_id)
            state = record["solutionDesign"]
            sys.stdout.write(core.render_design(state, state.get("prose") or {}))
            return 0
        print(json.dumps(worker.op_check({"caseId": arguments.case_id}), indent=2, sort_keys=True))
        return 0
    except (worker_module.WorkerError, core.SolutionDesignError) as exc:
        print(f"solution-design: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
