# Salesforce Managed-Package Copilot Brain-Core

A private, team-versioned GitHub Copilot harness for Salesforce development around any configured
closed managed package. It combines a minimal always-on safety/grounding kernel, five SDLC agents,
seven public prompt commands, twelve internal skills, governed but initially unseeded
Knowledge/Memory/QA layers, reconciled read-only org review, durable handoffs, and repeatable
validation. No object, namespace, package behavior, or business meaning is built in.

## Current authority

1. [.github/copilot-instructions.md](.github/copilot-instructions.md) — always-on safety kernel.
2. [docs/workspace-topology.md](docs/workspace-topology.md) — supported single-repository workspace.
3. [docs/compatibility.md](docs/compatibility.md) — runtime/version contract.
4. [.ai/contracts/execution-contract.md](.ai/contracts/execution-contract.md) — common skill
   execution, cache, output, and failure behavior.
5. [docs/grounding-architecture.md](docs/grounding-architecture.md) — Principles, claim/evidence,
   repository/org reconciliation, Knowledge promotion, and handoff architecture.
6. [IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) — as-built changes and remaining roadmap.

`HARNESS_BLUEPRINT.md`, `BUILD_REPORT.md`, `HARNESS_DIAGRAMS.md`, and `HANDOFF_FOR_FABLE.md` retain
the original design history. They are no longer the normative runtime specification where they
conflict with the files above.

## Architecture

| Layer | Location | Purpose |
|---|---|---|
| Safety and Principles | `.github/copilot-instructions.md`, `.github/instructions/` | Minimal always-on kernel; detailed role-loaded Tier 1 → 2 → 3 rules |
| Orchestration | `.github/agents/` | Design, investigation, development, QA strategy, independent review |
| Public commands | `.github/prompts/` | Seven deterministic slash-command entry points |
| Internal capabilities | `.github/skills/` | Twelve progressively loaded procedures hidden from the slash menu |
| Knowledge and contracts | `.ai/knowledge/`, `.ai/contracts/` | Schema-governed claims, immutable evidence, human reviews, source authority |
| Work state and QA | `.ai/change-records/`, `.ai/memory/`, `.ai/qa/` | Revisioned approvals/handoffs, durable decisions, and test inventory |
| Salesforce project | `sfdx-project.json`, `force-app/`, `manifest/`, `tests/e2e/` | Root SFDX project, source, manifests, and Salesforce tests |
| Runtime | `.vscode/mcp.json`, `.github/hooks/`, `scripts/` | Reconciled MCP/hidden-CLI review, guarded non-production tools, deterministic checks |
| Local/generated data | `.cache/`, `output/` | Ignored raw cache and human-review drafts |

## Start here

Follow [SETUP.md](SETUP.md). Clone this repository once, then open `sf-harness.code-workspace`.
The repository root is both the harness root and the only Salesforce DX project root. The
workspace exposes it once as `brain-core`; `sfdx-project.json`, `force-app/`, `manifest/`, and
`tests/e2e/` share the same branch, pull request, and commit history as the governance artifacts.

From the repository root, create/activate the virtual environment as described in SETUP, install
the pinned Node runtime, then run:

```bash
python -m pip install -r requirements-dev.lock
npm ci --ignore-scripts
python scripts/validate_harness.py
python scripts/preflight.py
python -m unittest discover -s tests -v
npm run prettier:verify
npm run lint
npm run test:unit:ci
```

The repository intentionally fails closed until `config/harness.local.json` contains real,
non-production, human-owned environment/process values and the package/component review scope.
Empty Knowledge produces explicit unknowns, not fabricated package facts.

`manifest/package.xml` is a generic starter manifest, not an approved deployment scope. Before an
org-facing retrieve, validation, or deployment, a human-accepted work record must narrow and bind
the manifest to the intended components; wildcard presence is never authorization.
