#!/usr/bin/env python3
"""Execute deterministic safety and role-guard evaluation scenarios."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evals" / "safety-scenarios.yaml"


def decision(output: dict[str, Any]) -> tuple[str, str]:
    hook = output.get("hookSpecificOutput")
    if isinstance(hook, dict):
        return str(hook.get("permissionDecision", "continue")), str(
            hook.get("permissionDecisionReason", "")
        )
    if output.get("continue") is True:
        return "continue", ""
    return "unknown", ""


def run_scenario(scenario: dict[str, Any], temporary: Path) -> tuple[bool, str]:
    cwd = temporary if scenario.get("workingDirectory") == "temporary" else ROOT
    event = dict(scenario.get("event", {}))
    event["cwd"] = str(cwd)
    guard = scenario.get("guard")
    if guard == "global":
        command = [sys.executable, str(ROOT / "scripts/copilot_safety_hook.py")]
    elif guard == "role":
        command = [
            sys.executable,
            str(ROOT / "scripts/copilot_role_guard.py"),
            "--role",
            str(scenario.get("role")),
        ]
    else:
        return False, f"unknown guard {guard!r}"
    completed = subprocess.run(
        command,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return False, f"guard exited {completed.returncode}: {completed.stderr.strip()}"
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return False, f"guard returned invalid JSON: {exc}: {completed.stdout!r}"
    actual, reason = decision(output)
    expected = str(scenario.get("expectedDecision"))
    if actual != expected:
        return False, f"expected {expected}, got {actual}; reason={reason!r}"
    required_reason = scenario.get("reasonContains")
    if required_reason and str(required_reason) not in reason:
        return False, f"reason does not contain {required_reason!r}: {reason!r}"
    return True, actual


def main() -> int:
    data = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios", [])
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="brain-core-evals-") as temp_name:
        temporary = Path(temp_name)
        for scenario in scenarios:
            ok, detail = run_scenario(scenario, temporary)
            marker = "PASS" if ok else "FAIL"
            print(f"{marker}: {scenario.get('id')} ({detail})")
            if not ok:
                failures.append(str(scenario.get("id")))
    if failures:
        print(f"FAIL: {len(failures)} of {len(scenarios)} deterministic evaluations failed")
        return 1
    print(f"PASS: {len(scenarios)} deterministic safety evaluations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
