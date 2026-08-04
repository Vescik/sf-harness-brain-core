# Salesforce Managed-Package Copilot Brain-Core

A private, team-versioned GitHub Copilot harness for Salesforce development around any configured
closed managed package. It combines a minimal always-on safety/grounding kernel, six SDLC agents,
twenty-four public prompt commands, twenty-five internal skills, governed but initially unseeded
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
6. [docs/force-app-knowledge-architecture.md](docs/force-app-knowledge-architecture.md) — governed
   source inventory and Knowledge-proposal pipeline.

The original design history (`HARNESS_BLUEPRINT.md`, `BUILD_REPORT.md`, `HARNESS_DIAGRAMS.md`,
and both `HANDOFF_FOR_FABLE*.md` reviews) was removed from the working tree on 2026-07-16; it
remains in git history under the tag `design-history` (`git show design-history:docs/archive/README.md`
for the index). It was historical input only, never the normative runtime specification.

## Architecture

| Layer | Location | Purpose |
|---|---|---|
| Safety and Principles | `.github/copilot-instructions.md`, `.github/instructions/` | Minimal always-on kernel; detailed role-loaded Tier 1 → 2 → 3 rules |
| Orchestration | `.github/agents/` | Design, investigation, development, QA strategy, independent review |
| Public commands | `.github/prompts/` | Twenty-four deterministic slash-command entry points |
| Internal capabilities | `.github/skills/` | Twenty-five progressively loaded procedures hidden from the slash menu |
| Knowledge and contracts | `.ai/knowledge/`, `.ai/contracts/` | Schema-governed claims, immutable evidence, human reviews, source authority |
| Work state and QA | `.ai/change-records/`, `.ai/memory/`, `.ai/qa/` | Revisioned approvals/handoffs, durable decisions, and test inventory |
| Salesforce project | `sfdx-project.json`, `force-app/`, `manifest/`, `tests/e2e/` | Root SFDX project, source, manifests, and Salesforce tests |
| Runtime | `.vscode/mcp.json`, `.github/hooks/`, `scripts/` | Reconciled MCP/hidden-CLI review, guarded non-production tools, deterministic checks |
| Local/generated data | `.cache/`, `output/` | Ignored raw cache and human-review drafts |

## Changing the release-handover document shape

The `/release-handover` document is rendered strictly from
[.ai/templates/release-handover.md](.ai/templates/release-handover.md) — edit that one file to
change the structure; no prompt, skill, or script change is needed. The render check
([scripts/validate_handover_output.py](scripts/validate_handover_output.py)) re-derives the
expected headings from the template at every run, so edits are enforced automatically on the
next generation. Keep the `repeat-per-item` marker comment (it marks the block repeated per
work item; the harness audit requires exactly one), and note that
[scripts/validate_harness.py](scripts/validate_harness.py) link-checks relative links inside
templates.

## Start here

Follow [SETUP.md](SETUP.md) — or, if you are setting up a machine from scratch, the
zero-assumptions walkthrough in
[docs/setup-zero-to-first-prompt.md](docs/setup-zero-to-first-prompt.md). Clone this repository
once, then open `sf-harness.code-workspace`.
The repository root is both the harness root and the only Salesforce DX project root. The
workspace exposes it once as `brain-core`; `sfdx-project.json`, `force-app/`, `manifest/`, and
`tests/e2e/` share the same branch, pull request, and commit history as the governance artifacts.
Opening the repository root directly is also supported; MCP and tasks use the unqualified
`${workspaceFolder}` variable so they do not depend on a display-name alias.

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
```

The repository intentionally fails closed until `config/harness.local.json` contains real,
non-production, human-owned environment/process values and the package/component review scope.
Empty Knowledge produces explicit unknowns, not fabricated package facts.

`manifest/package.xml` is a generic starter manifest, not an approved deployment scope. Before an
org-facing retrieve, validation, or deployment, a human-accepted work record must narrow and bind
the manifest to the intended components; wildcard presence is never authorization.
