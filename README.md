# Salesforce Managed-Package Workspace — brain-core harness

A GitHub Copilot "brain-core" harness for a VS Code workspace, built for SDLC work on a **closed
Salesforce managed package**. It gives Copilot an explicit, structured brain — Principles,
Knowledge, Memory, Orchestration, QA — so the agent stays effective despite having no access to
the package's source.

**The binding specification is [`HARNESS_BLUEPRINT.md`](HARNESS_BLUEPRINT.md).** This README is
a short orientation only; the blueprint is the source of truth (with
[`HARNESS_DIAGRAMS.md`](HARNESS_DIAGRAMS.md) as a companion) and [`BUILD_REPORT.md`](BUILD_REPORT.md)
records how the workspace was actually built and every open item.

## Layout

| Path | What it is | Loaded |
|---|---|---|
| `.github/copilot-instructions.md` | Thin table-of-contents + precedence order | Always |
| `.github/instructions/` | 3 Principles files (`applyTo: "**"`) | Always |
| `.github/agents/` | 5 SDLC agent profiles | On selection / handoff |
| `.github/skills/` | 12 reusable skill procedures | Progressive discovery |
| `.github/prompts/` | 7 thin `/command` wrappers | On `/name` |
| `.ai/knowledge/` | Facts about the system (start at its `README.md`) | On demand |
| `.ai/memory/decisions-log.md` | The team's curated decision memory | On demand |
| `.ai/qa/` | Synced Test Case index, keywords map, UI quirks | On demand |
| `.ai/templates/` | Output formats | On demand |
| `.cache/` | Raw fetched data (gitignored) | — |
| `output/` | AI-generated artifacts for human review | — |
| `.vscode/settings.json` | Activation layer — pins Copilot file loading | At workspace open |

## Getting started

See **[`SETUP.md`](SETUP.md)** for prerequisites, how this repo is distributed and kept in sync
across the team, and how to confirm Copilot has actually loaded the harness.

## Deliberately not here (parked — blueprint §15)

A configured `.vscode/mcp.json`, `.github/hooks/`, and anything tied to the deployment
git / Salesforce DevOps Center flow. This repo versions the **brain**, not the package metadata.
