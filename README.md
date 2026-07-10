# Salesforce Managed-Package Copilot Brain-Core

A private, team-versioned GitHub Copilot harness for Salesforce development around a closed
managed package. It combines an always-on safety contract, five SDLC agents, seven public prompt
commands, twelve internal skills, verified Knowledge/Memory/QA layers, guarded external tools,
and repeatable validation.

## Current authority

1. [.github/copilot-instructions.md](.github/copilot-instructions.md) — always-on safety kernel.
2. [docs/workspace-topology.md](docs/workspace-topology.md) — supported two-root workspace.
3. [docs/compatibility.md](docs/compatibility.md) — runtime/version contract.
4. [.ai/contracts/execution-contract.md](.ai/contracts/execution-contract.md) — common skill
   execution, cache, output, and failure behavior.
5. [IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) — as-built changes and remaining roadmap.

`HARNESS_BLUEPRINT.md`, `BUILD_REPORT.md`, `HARNESS_DIAGRAMS.md`, and `HANDOFF_FOR_FABLE.md` retain
the original design history. They are no longer the normative runtime specification where they
conflict with the files above.

## Architecture

| Layer | Location | Purpose |
|---|---|---|
| Safety and Principles | `.github/copilot-instructions.md`, `.github/instructions/` | Always-on rules with Tier 1 → 2 → 3 precedence |
| Orchestration | `.github/agents/` | Design, investigation, development, QA strategy, independent review |
| Public commands | `.github/prompts/` | Seven deterministic slash-command entry points |
| Internal capabilities | `.github/skills/` | Twelve progressively loaded procedures hidden from the slash menu |
| Knowledge and contracts | `.ai/knowledge/`, `.ai/contracts/` | Sourced facts and execution/data contracts |
| Memory and QA | `.ai/memory/`, `.ai/change-records/`, `.ai/qa/` | Accepted decisions, handoffs, and test inventory |
| Runtime | `.vscode/mcp.json`, `.github/hooks/`, `scripts/` | Guarded non-production tools and deterministic policy checks |
| Local/generated data | `.cache/`, `output/` | Ignored raw cache and human-review drafts |

## Start here

Follow [SETUP.md](SETUP.md). The supported layout uses `sf-harness.code-workspace` with the
`brain-core` repository beside a `salesforce-metadata` SFDX repository.

Run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_harness.py
python3 scripts/preflight.py
python3 -m unittest discover -s tests -v
```

The repository intentionally fails closed until `config/harness.local.json` contains real,
non-production, human-owned environment and process values.
