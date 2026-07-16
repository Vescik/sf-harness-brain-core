# Module Map — Copilot Harness Audit (read-only, report-only)

Audit date: 2026-07-16. Scope: everything enumerated in the audit brief (Task 1 inventory,
Task 2 connection graph, edge types E1–E8). This phase makes no judgment calls about defects —
it records facts only: what exists, what a module says about itself, what it references, and
whether each reference resolves.

**Location note (fact, not judgment):** `HARNESS_BLUEPRINT.md` and `HARNESS_DIAGRAMS.md` do not
live at the repository root. They live at `docs/archive/HARNESS_BLUEPRINT.md` and
`docs/archive/HARNESS_DIAGRAMS.md`. `docs/archive/README.md` states both are "historical input,
not runtime authority... kept for design rationale only," and that the diagrams file has "known
drift: some sections show four agents; the built harness has five." Both files also carry their
own top-of-file blockquote: the blueprint says "current runtime authority is listed in
`README.md`; do not use a conflicting historical statement as an execution rule"; the diagrams
file says "some counts and runtime layers are stale... current authority and as-built state are
in `README.md` and `IMPLEMENTATION_HANDOFF.md`." This context applies to every E8 edge below.

---

## Task 1 — Module inventory

### Entry instructions

| path | frontmatter fields | purpose |
|---|---|---|
| `.github/copilot-instructions.md` | none (plain markdown, no YAML block) | "This is the only substantive always-on repository instruction." Points to `.ai/repo-map.md` as the repo atlas; states 10 non-negotiable SAFE-* rules and a required grounding sequence; defines the "supported enforcement boundary." |

### Principles (`.github/instructions/`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.github/instructions/managed-package-constraints.instructions.md` | `description` | "Generic managed-package and closed-surface constraints. Load when a governed workflow touches a package-owned or ownership-unknown component." Tier 1 rules (MP-GEN-*, MP-OWN-*, MP-EXT-*, MP-AUTO-*). |
| `.github/instructions/organization-principles.instructions.md` | `description` | "Company policy, review, naming, decision, Knowledge-promotion, handoff, and shared-sandbox rules. Load explicitly for governed design, implementation, and review." Tier 2 rules (ORG-NAME-*, ORG-REVIEW-*, ORG-DEC-*, ORG-KNOW-*). |
| `.github/instructions/salesforce-best-practices.instructions.md` | `description` | "General Salesforce engineering and evidence practices for Apex, Flow, security, limits, testing, metadata, and source/org reconciliation. Load explicitly after Tier 1 and Tier 2." Tier 3 rules (SF-BULK-*, SF-LIMIT-*, SF-TRIG-*, SF-SEC-*, SF-SOQL-*, SF-AUTO-*, SF-NAME-*, SF-TEST-*, SF-ERR-*, SF-META-*, SF-EVID-*). |
| `.github/instructions/rule-registry.yaml` | n/a (YAML data file, not an `.instructions.md`) | Machine-readable registry backing the three instruction files above; not itself one of the three Principles tiers but a supporting module in the same directory. |

### Agents (`.github/agents/*.agent.md`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.github/agents/config-investigator.agent.md` | name, description, argument-hint, target, tools, hooks(PreToolUse) | Read-only evidence collector for allowlisted Salesforce components and package surfaces; creates sanitized observations and proposed claims without self-verifying them. |
| `.github/agents/development-assistant.agent.md` | name, description, argument-hint, target, tools, agents, handoffs, hooks(PreToolUse) | Implement a human-accepted Salesforce design in the repository-root SFDX project, verify it, and hand it to independent guardrail review. |
| `.github/agents/guardrail-reviewer.agent.md` | name, description, argument-hint, target, tools, handoffs, hooks(PreToolUse) | Independently review a design or implementation against package, organization, Salesforce, evidence-completeness, and role-boundary rules; never implement fixes. |
| `.github/agents/solution-designer.agent.md` | name, description, argument-hint, target, tools, agents, handoffs, hooks(PreToolUse) | Design the change before implementation, establish affected components and evidence, resolve managed-package constraints, and persist a human-reviewable design record. |
| `.github/agents/test-strategist.agent.md` | name, description, argument-hint, target, tools, handoffs, hooks(PreToolUse) | Assess QA inventory freshness and coverage sufficiency, select the appropriate QA skills, and produce a sourced coverage decision or reviewed test draft. |

Count: **5 agents.**

### Skills (`.github/skills/*/SKILL.md`)

All 22 share identical frontmatter shape: `name`, `description`, `user-invocable: false` (none is directly user-invocable; all are invoked by agents/prompts).

| path | purpose |
|---|---|
| `.github/skills/batch-knowledge/SKILL.md` | Five-phase batch conversion of one metadata type into governed Knowledge. |
| `.github/skills/check-against-principles/SKILL.md` | Evaluate a scoped design/implementation using the governed rule registry. Read-only; never implement fixes. |
| `.github/skills/check-feature-coverage/SKILL.md` | Compare an ADO Feature + selected BRD requirements against child Story claims; produce a coverage matrix. |
| `.github/skills/curate-knowledge-keywords/SKILL.md` | Curate the Knowledge keyword taxonomy from aggregated candidateKeywords. |
| `.github/skills/feature-documentor/SKILL.md` | Document a feature end to end — crawl an anchor object's relations, draft feature-tagged proposed claims, render a dossier. |
| `.github/skills/fetch-ado-item/SKILL.md` | Fetch and normalize one ADO work item or a one-level hierarchy with cache completeness. |
| `.github/skills/fetch-test-case/SKILL.md` | Fetch and normalize one Azure Test Plans Test Case with steps and expected results. |
| `.github/skills/generate-playwright-test/SKILL.md` | Explore a guarded Salesforce sandbox and generate a reviewable Playwright test draft. |
| `.github/skills/generate-release-handover/SKILL.md` | Compose a sourced monthly release-handover draft from the configured saved ADO query. |
| `.github/skills/generate-technical-documentation/SKILL.md` | Generate a sourced technical-documentation draft for one accepted metadata change. |
| `.github/skills/inventory-force-app/SKILL.md` | Inventory the repository-root force-app into a sanitized, evidence-linked JSON artifact. |
| `.github/skills/inventory-force-app/references/coverage.md` | Supporting reference (not a SKILL.md): source-artifact-type → sanitized inventory field → governed claim candidate table. |
| `.github/skills/investigate-object/SKILL.md` | Collect bounded, sanitized, reconciled evidence for a scoped Salesforce component or package claim. |
| `.github/skills/propose-force-app-knowledge/SKILL.md` | Draft schema-v3 Knowledge claims and immutable evidence from a complete, clean force-app inventory. |
| `.github/skills/relation-health/SKILL.md` | Read-only report of verified relation claims whose source edge no longer exists in current force-app source. |
| `.github/skills/search-ado/SKILL.md` | Read-only ADO text search across wiki pages and work items. |
| `.github/skills/search-knowledge/SKILL.md` | Read-only search over the governed Knowledge registry. |
| `.github/skills/solution-design/SKILL.md` | Five-phase Solution Design workflow (discover, plan, verify plan, execute design package, verify outcome). |
| `.github/skills/suggest-test-cases/SKILL.md` | Rank existing synced Test Cases for a structured change using curated taxonomy evidence. |
| `.github/skills/sync-test-cases/SKILL.md` | Synchronize an allowlisted Azure Test Plan/Suite into deterministic committed QA indexes. |
| `.github/skills/tune-test-case-keywords/SKILL.md` | Curate one Test Case keyword mapping with a named human approver. |
| `.github/skills/update-knowledge-base/SKILL.md` | Govern proposed claims, immutable evidence, human reviews, lifecycle transitions, reconciliation, and generated Knowledge indexes. |
| `.github/skills/update-relations/SKILL.md` | Repo-wide incremental sweep proposing relation claims for every reference edge not yet captured. |

Empty subfolders present with zero files (structural scaffolding only): `.github/skills/inventory-force-app/agents/`, `.github/skills/propose-force-app-knowledge/agents/`.

Count: **22 skill directories.**

### Prompts (`.github/prompts/*.prompt.md`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.github/prompts/batch-knowledge.prompt.md` | name, description, argument-hint, agent, tools | Convert one whole metadata type into governed Knowledge via a five-phase batch. |
| `.github/prompts/check-against-principles.prompt.md` | name, description, argument-hint, agent, tools | Ad-hoc read-only review of a persisted design/implementation against every applicable Principle tier. |
| `.github/prompts/document-metadata-change.prompt.md` | name, description, argument-hint, agent, tools | Generate reviewed technical documentation for one accepted metadata change. |
| `.github/prompts/feature-documentor.prompt.md` | name, description, argument-hint, agent, tools | Document a Salesforce feature from anchor objects — crawl, tag, render dossier. |
| `.github/prompts/feature-health.prompt.md` | name, description, argument-hint, agent | Run the Feature/BRD-to-Story coverage gate before Solution Design. |
| `.github/prompts/fetch-ado-item.prompt.md` | name, description, argument-hint, agent | Fetch a validated ADO work item context and begin Solution Design. |
| `.github/prompts/generate-playwright-test.prompt.md` | name, description, argument-hint, agent | Generate and live-verify a Playwright draft from an ADO Test Case or tester-provided steps. |
| `.github/prompts/inventory-force-app.prompt.md` | name, description, argument-hint, agent | Inventory the root force-app as sanitized Knowledge evidence candidates without creating claims. |
| `.github/prompts/investigate-object.prompt.md` | name, description, argument-hint, agent, tools | Collect bounded, sanitized, reconciled evidence for one object/component; draft a proposed claim. |
| `.github/prompts/propose-force-app-knowledge.prompt.md` | name, description, argument-hint, agent, tools | Draft governed force-app Knowledge candidates and optionally submit a selected subset. |
| `.github/prompts/refresh-force-app-knowledge.prompt.md` | name, description, argument-hint, agent, tools | Run the governed force-app inventory and claim-draft stages, with optional proposal submission. |
| `.github/prompts/relation-health.prompt.md` | name, description, argument-hint, agent, tools | Report verified relation claims whose source edge no longer exists in force-app source (read-only). |
| `.github/prompts/release-handover.prompt.md` | name, description, argument-hint, agent, tools | Build a current monthly release handover from the configured saved ADO query. |
| `.github/prompts/search-ado.prompt.md` | name, description, argument-hint, agent, tools | Text-search Azure DevOps wikis and work items in the configured project. |
| `.github/prompts/search-knowledge.prompt.md` | name, description, argument-hint, agent, tools | Search governed Knowledge by subject, keyword, or text. |
| `.github/prompts/solution-design.prompt.md` | name, description, argument-hint, agent, tools | Run the five-phase Solution Design workflow. |
| `.github/prompts/suggest-test-cases.prompt.md` | name, description, argument-hint, agent, tools | Rank existing synced Test Cases relevant to one structured change. |
| `.github/prompts/sync-test-cases.prompt.md` | name, description, argument-hint, agent | Synchronize one validated Azure Test Plan/Suite into the committed QA index. |
| `.github/prompts/tune-test-case-keywords.prompt.md` | name, description, argument-hint, agent | Human-led admin curation of Test Case keywords. |
| `.github/prompts/update-relations.prompt.md` | name, description, argument-hint, agent, tools | Sweep force-app for reference edges not yet captured as relation claims. |

Count: **20 prompts.** 5 of 20 have no `tools` field (only name/description/argument-hint/agent): `feature-health`, `fetch-ado-item`, `generate-playwright-test`, `sync-test-cases`, `tune-test-case-keywords`.

### Knowledge (`.ai/knowledge/`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.ai/knowledge/README.md` | none | Index of the Knowledge registry: names `claims/`, `evidence/`, `reviews/` as canonical directories; lists domain-index files + `claims-index.json` + `keyword-taxonomy.md`; states the retrieval rule; documents `coverage`/`stale-report`/`verify-citations` commands. |
| `.ai/knowledge/automation-map.md` | none | Domain index: scoped, complete automation inventory claims. |
| `.ai/knowledge/business-processes.md` | none | Domain index: business processes and system mappings. |
| `.ai/knowledge/component-inventory.md` | none | Domain index: generic source-component claims for every other metadata type. |
| `.ai/knowledge/current-implementation.md` | none | Domain index: current implementation, package installation, scoped runtime behavior. |
| `.ai/knowledge/feature-map.md` | none | Generated claim index grouping claims by feature-membership tag, written by feature-documentor; currently empty. |
| `.ai/knowledge/field-descriptions.md` | none | Domain index: field schema and approved business meaning. |
| `.ai/knowledge/glossary.md` | none | Domain index: approved business-to-technical terms. |
| `.ai/knowledge/integration-map.md` | none | Domain index: external-system and data-flow claims. |
| `.ai/knowledge/keyword-taxonomy.md` | none | Separately curated vocabulary; terms are not factual evidence. |
| `.ai/knowledge/known-limitations.md` | none | Domain index: version-scoped package limitation claims. |
| `.ai/knowledge/object-descriptions.md` | none | Domain index: object existence, ownership, and meaning. |
| `.ai/knowledge/object-relations.md` | none | Domain index: verified object and reference-data relations. |
| `.ai/knowledge/claims-index.json` | n/a (JSON) | Machine-readable index of every canonical claim; currently empty (`claimCount: 0`). |
| `.ai/knowledge/claims/` | n/a (dir) | Canonical scoped-assertion YAML records (schema `knowledge-claim.schema.json`); currently empty save `.gitkeep`. |
| `.ai/knowledge/evidence/` | n/a (dir) | Immutable sanitized observation receipts (schema `knowledge-evidence.schema.json`); currently empty save `.gitkeep`. |
| `.ai/knowledge/reviews/` | n/a (dir) | Immutable human promotion/reconciliation decisions (schema `knowledge-review.schema.json`); currently empty save `.gitkeep`. |

Count: **13 knowledge `.md` files** + 1 JSON index + 3 schema-backed subdirectories (all currently empty scaffolds).

### Memory (`.ai/memory/`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.ai/memory/decisions-log.md` | none | "Persistent, versioned cross-work-item memory of the project" for durable architectural decisions — explicitly distinct from Copilot Memory, canonical Knowledge claims, and active work-record state. 5 dated entries (2026-07-13, 2026-07-14), each with Context/Finding/Impact/Approved-by/Related fields. |

### Templates (`.ai/templates/*.md`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.ai/templates/change-record.md` | none | Design-narrative shape for a work record; states machine workflow state lives in a sibling `record.json`, not this file. No "Used by skill" header, unlike the other 5. |
| `.ai/templates/feature-dossier.md` | none | Shape of the generated Feature Dossier; states feature-documentor writes it via `render_dossier`, and to edit the generator, not the output. |
| `.ai/templates/feature-health-report.md` | HTML-comment header: "Used by skill: check-feature-coverage... Output: output/feature-health/\<featureId\>.md... Source: docs/archive/HARNESS_BLUEPRINT.md section 13" | 6 mandatory sections; empty sections require explicit "none". |
| `.ai/templates/knowledge-entry.md` | none | Shape of a Schema-v3 Knowledge claim proposal; names the 3 canonical YAML paths and required creation sequence. No "Used by skill" header. |
| `.ai/templates/release-handover.md` | HTML-comment header: "Used by skill: generate-release-handover (invoked via /release-handover, monthly). Output: output/handover/\<month\>.md... Source: docs/archive/HARNESS_BLUEPRINT.md section 13" | Monthly release-handover shape; DOCX/PDF export is a manual human step. |
| `.ai/templates/technical-documentation.md` | HTML-comment header: "Used by skill: generate-technical-documentation (invoked via /document-metadata-change). Output: output/documentation/\<itemId\>.md... Source: docs/archive/HARNESS_BLUEPRINT.md section 13" | 9 mandatory sections for one accepted metadata change's documentation. |

Count: **6 templates.** Every header-bearing template cites `docs/archive/HARNESS_BLUEPRINT.md section 13` as its "Source" — the templates layer explicitly derives its contract from the now-archived/superseded blueprint.

### QA (`.ai/qa/**`)

| path | frontmatter fields | purpose |
|---|---|---|
| `.ai/qa/ui-navigation-patterns.md` | none | UI quirks discovered by generate-playwright-test during automation, recorded to avoid re-discovery; currently zero entries. |
| `.ai/qa/keywords-map.md` | none | Human-curated Test Case ID → keywords map maintained by tune-test-case-keywords, kept separate from auto-synced files; currently zero entries. |
| `.ai/qa/test-cases/README.md` | none | Explains the committed QA test-case index: one file per Test Suite (`<suiteId>-<name>.md`), written/overwritten by sync-test-cases, index-only (full steps live in `.cache/test-cases/<id>.json`). Currently zero suite files exist — only this README. |

### Storage conventions

- **`.cache/`** (gitignored; skeleton kept via `.gitkeep`): `ado-items/` (empty), `test-cases/` (empty), `knowledge-proposals/` (populated: `force-app-inventory.json`, `force-app-worklist-CustomObject.json`, `feature-billing.json`, `force-app-drafts/` with ~80 draft YAMLs + `manifest.json`), plus root `denials.log`. `.gitignore` comment cites "blueprint §13 and §17" as policy source.
- **`output/`** (gitignored generated content for human review; skeleton kept via `.gitkeep`): `documentation/` (empty), `feature-dossiers/` (populated: `billing.md`), `handover/` (empty), `solution-design/` (empty), `generated-tests/` (empty), `feature-health/` (empty). `.gitignore`'s own comment flags this policy as **PROVISIONAL**: "blueprint §13 says output/ git policy 'depends on the subfolder' and does not resolve which subfolders are committed... Revisit per §13 — see docs/archive/BUILD_REPORT.md flag 24."
- **`force-app/main/default/**`**: org metadata content is gitignored (human-retrieved/deployed only); skeleton kept via `.gitkeep`, same pattern.
- Other `.gitignore` sections: OS noise, local Salesforce CLI tooling state, local harness config (`config/harness.local.json`, `config/harness.json` — comment states only `harness.example.json` is meant to be tracked), general dev-tooling noise.
- `output/feature-dossiers/` is the one `output/` subfolder without a committed `.gitkeep`, even though it's populated and actively referenced by `feature-documentor/SKILL.md` and `feature-dossier.md`.

### Documentation modules

| path | frontmatter | purpose |
|---|---|---|
| `docs/archive/HARNESS_BLUEPRINT.md` (1380 lines) | none (blockquote status note instead) | "Harness Blueprint — Salesforce Managed Package Workspace (historical design record)." Own blockquote: "this document preserves the original rationale and functional essence... Current runtime authority is listed in `README.md`; do not use a conflicting historical statement as an execution rule." Polish-language. |
| `docs/archive/HARNESS_DIAGRAMS.md` (386 lines) | none (blockquote status note instead) | "Harness Diagrams — original architecture flows (historical)." Own blockquote: "some counts and runtime layers are stale... current authority and as-built state are in `README.md` and `IMPLEMENTATION_HANDOFF.md`." Diagram-only companion to the blueprint, all Mermaid. English-language. |

Not found at repository root (only present under `docs/archive/`) — see location note at top of this document.

### `.ai/contracts/` (referenced by other modules; not named as its own category in the audit brief, flagged for completeness)

| path |
|---|
| `.ai/contracts/execution-contract.md` |
| `.ai/contracts/knowledge-lifecycle.md` |
| `.ai/contracts/source-authority.md` |
| `.ai/contracts/tool-capabilities.md` |
| `.ai/contracts/workflow-state-machine.md` |

This directory is heavily referenced (E4, below) by nearly every agent/skill but was not one of the six categories named in the audit brief (Principles/Agents/Skills/Prompts/Knowledge/Memory/Templates/QA). Recorded here as an inbound-heavy module family the brief's category list omits.

---

## Task 2 — Connection graph

### E1 — prompt → skill

Every one of the 20 prompts carries exactly one `Use the [<skill> skill](../skills/<dir>/SKILL.md)` link (two for `refresh-force-app-knowledge.prompt.md`), and every link resolves.

| source (file:line) | target (literal text) | resolves |
|---|---|---|
| batch-knowledge.prompt.md:9 | `../skills/batch-knowledge/SKILL.md` | yes |
| check-against-principles.prompt.md:9 | `../skills/check-against-principles/SKILL.md` | yes |
| document-metadata-change.prompt.md:9 | `../skills/generate-technical-documentation/SKILL.md` | yes |
| feature-documentor.prompt.md:9 | `../skills/feature-documentor/SKILL.md` | yes |
| feature-health.prompt.md:8 | `../skills/check-feature-coverage/SKILL.md` | yes |
| fetch-ado-item.prompt.md:8 | `../skills/fetch-ado-item/SKILL.md` | yes |
| generate-playwright-test.prompt.md:8 | `../skills/generate-playwright-test/SKILL.md` | yes |
| inventory-force-app.prompt.md:9 | `../skills/inventory-force-app/SKILL.md` | yes |
| investigate-object.prompt.md:9 | `../skills/investigate-object/SKILL.md` | yes |
| propose-force-app-knowledge.prompt.md:9 | `../skills/propose-force-app-knowledge/SKILL.md` | yes |
| refresh-force-app-knowledge.prompt.md:9 | `../skills/inventory-force-app/SKILL.md` | yes |
| refresh-force-app-knowledge.prompt.md:10 | `../skills/propose-force-app-knowledge/SKILL.md` | yes |
| relation-health.prompt.md:9 | `../skills/relation-health/SKILL.md` | yes |
| release-handover.prompt.md:9 | `../skills/generate-release-handover/SKILL.md` | yes |
| search-ado.prompt.md:9 | `../skills/search-ado/SKILL.md` | yes |
| search-knowledge.prompt.md:9 | `../skills/search-knowledge/SKILL.md` | yes |
| solution-design.prompt.md:9 | `../skills/solution-design/SKILL.md` | yes |
| suggest-test-cases.prompt.md:9 | `../skills/suggest-test-cases/SKILL.md` | yes |
| sync-test-cases.prompt.md:8 | `../skills/sync-test-cases/SKILL.md` | yes |
| tune-test-case-keywords.prompt.md:8 | `../skills/tune-test-case-keywords/SKILL.md` | yes |
| update-relations.prompt.md:9 | `../skills/update-relations/SKILL.md` | yes |

Not an E1 edge but noted for completeness (prompt→prompt references found in prompt bodies, no E-type slot for this in the brief): `search-ado.prompt.md:15` → `/fetch-ado-item`; `search-knowledge.prompt.md:16` → `/investigate-object`, `/propose-force-app-knowledge`; `suggest-test-cases.prompt.md:13` → `/sync-test-cases`; `suggest-test-cases.prompt.md:15` → `/feature-health`. All resolve to real prompts.

### E2 — skill → skill

| source (file:line) | target (literal text) | resolves |
|---|---|---|
| batch-knowledge/SKILL.md:11 | `../propose-force-app-knowledge/SKILL.md` | yes |
| feature-documentor/SKILL.md:12 | `../inventory-force-app/SKILL.md` | yes |
| feature-documentor/SKILL.md:13 | `../propose-force-app-knowledge/SKILL.md` | yes |
| feature-documentor/SKILL.md:14 | `../update-knowledge-base/SKILL.md` | yes |
| feature-documentor/SKILL.md:47 | `../propose-force-app-knowledge/SKILL.md` | yes |
| generate-release-handover/SKILL.md:26 | `../search-ado/SKILL.md` | yes |
| search-ado/SKILL.md:37 | `../fetch-ado-item/SKILL.md` | yes |
| propose-force-app-knowledge/SKILL.md:12 | `../update-knowledge-base/SKILL.md` | yes |
| propose-force-app-knowledge/SKILL.md:48 | `../curate-knowledge-keywords/SKILL.md` | yes |
| generate-technical-documentation/SKILL.md:30 | `../search-knowledge/SKILL.md` | yes |
| generate-technical-documentation/SKILL.md:36 | `suggest-test-cases` (bare name, no path/link) | yes |
| solution-design/SKILL.md:14 | `../check-against-principles/SKILL.md` | yes |
| solution-design/SKILL.md:28 | `../fetch-ado-item/SKILL.md` | yes |
| suggest-test-cases/SKILL.md:23 | `../search-knowledge/SKILL.md` | yes |
| update-relations/SKILL.md:11 | `../propose-force-app-knowledge/SKILL.md` | yes |
| update-relations/SKILL.md:74 | `../relation-health/SKILL.md` | yes |
| search-knowledge/SKILL.md:48 | `../propose-force-app-knowledge/SKILL.md` | yes |
| search-knowledge/SKILL.md:49 | `../investigate-object/SKILL.md` | yes |

Skills with zero outbound E2 edges: check-against-principles, check-feature-coverage, curate-knowledge-keywords, fetch-ado-item, fetch-test-case, generate-playwright-test, inventory-force-app, investigate-object, relation-health, sync-test-cases, tune-test-case-keywords, update-knowledge-base.

### E3 — agent → skill

| source (file:line) | target (literal text) | resolves |
|---|---|---|
| config-investigator.agent.md:22 | `../skills/investigate-object/SKILL.md` | yes |
| config-investigator.agent.md:23 | `../skills/update-knowledge-base/SKILL.md` | yes |
| config-investigator.agent.md:24 | `../skills/inventory-force-app/SKILL.md` | yes |
| config-investigator.agent.md:25 | `../skills/propose-force-app-knowledge/SKILL.md` | yes |
| config-investigator.agent.md:27 | `../skills/feature-documentor/SKILL.md` | yes |
| guardrail-reviewer.agent.md:33 | `../skills/check-against-principles/SKILL.md` | yes |
| solution-designer.agent.md:34 | `../skills/check-against-principles/SKILL.md` | yes |
| solution-designer.agent.md:35 | `../skills/solution-design/SKILL.md` | yes |
| test-strategist.agent.md:30 | "Load only the QA skill selected for the current record" (no literal skill named) | ambiguous |

`development-assistant.agent.md` has **zero** E3 edges — unlike the other four agents, its body never links a `.github/skills/*/SKILL.md` path, despite being the implementation-role agent.

Not an E3 edge but a real connection type the brief has no slot for (agent→agent via frontmatter `agents:` array and `handoffs[].agent:`): `development-assistant.agent.md` frontmatter `agents: [config-investigator, test-strategist]`; handoffs to `guardrail-reviewer`/`solution-designer`; `solution-designer.agent.md`, `test-strategist.agent.md`, `guardrail-reviewer.agent.md` handoffs. All targets resolve to real agent names.

### E4 — skill/agent/instructions → knowledge/memory/template/qa/contracts path

| source (file:line) | target (literal path) | resolves |
|---|---|---|
| `.github/copilot-instructions.md:5` | `.ai/repo-map.md` | yes |
| `managed-package-constraints.instructions.md:12` | `../../.ai/knowledge/known-limitations.md` | yes |
| `organization-principles.instructions.md:28` | `../../.ai/memory/decisions-log.md` | yes |
| `config-investigator.agent.md:20` | `../../.ai/contracts/source-authority.md` | yes |
| `config-investigator.agent.md:21` | `../../.ai/contracts/knowledge-lifecycle.md` | yes |
| `development-assistant.agent.md:32` | `../../.ai/contracts/execution-contract.md` | yes |
| `development-assistant.agent.md:33` | `../../.ai/contracts/workflow-state-machine.md` | yes |
| `solution-designer.agent.md:32` | `../../.ai/contracts/source-authority.md` | yes |
| `solution-designer.agent.md:33` | `../../.ai/contracts/workflow-state-machine.md` | yes |
| `guardrail-reviewer.agent.md:31` | `../../.ai/contracts/source-authority.md` | yes |
| `guardrail-reviewer.agent.md:32` | `../../.ai/contracts/workflow-state-machine.md` | yes |
| `test-strategist.agent.md:29` | `../../.ai/contracts/execution-contract.md` | yes |
| `test-strategist.agent.md:30` | `../../.ai/contracts/workflow-state-machine.md` | yes |
| `test-strategist.agent.md:51` | `.ai/qa/**` (write-scope pattern) | yes |
| `check-feature-coverage/SKILL.md:9` | `../../../.ai/contracts/execution-contract.md` | yes |
| `check-against-principles/SKILL.md:9-11` | execution-contract.md, source-authority.md, knowledge-lifecycle.md, workflow-state-machine.md | yes (all 4) |
| `curate-knowledge-keywords/SKILL.md:9-10,28` | execution-contract.md; `.ai/knowledge/keyword-taxonomy.md` (×2) | yes (all) |
| `batch-knowledge/SKILL.md:9-10` | execution-contract.md, knowledge-lifecycle.md | yes |
| `fetch-test-case/SKILL.md:9` | execution-contract.md | yes |
| `fetch-ado-item/SKILL.md:9` | execution-contract.md | yes |
| `inventory-force-app/SKILL.md:9-11` | execution-contract.md, knowledge-lifecycle.md, source-authority.md | yes |
| `inventory-force-app/SKILL.md:29` | `references/coverage.md` | yes |
| `feature-documentor/SKILL.md:9-14` | execution-contract.md, knowledge-lifecycle.md, source-authority.md (+3 skill links, counted under E2) | yes |
| `search-ado/SKILL.md:9` | execution-contract.md | yes |
| `generate-release-handover/SKILL.md:9` | execution-contract.md | yes |
| `generate-playwright-test/SKILL.md:9` | execution-contract.md | yes |
| `sync-test-cases/SKILL.md:9,28` | execution-contract.md; `.ai/qa/test-cases/<suiteId>-<slug>.md` (pattern) | yes |
| `generate-technical-documentation/SKILL.md:9` | execution-contract.md | yes |
| `investigate-object/SKILL.md:9-11` | execution-contract.md, source-authority.md, knowledge-lifecycle.md | yes |
| `propose-force-app-knowledge/SKILL.md:9-11,55` | execution-contract.md, knowledge-lifecycle.md, source-authority.md; `.ai/knowledge/claims-index.json` | yes (all) |
| `relation-health/SKILL.md:9-10` | execution-contract.md, knowledge-lifecycle.md | yes |
| `suggest-test-cases/SKILL.md:9` | execution-contract.md | yes |
| `search-knowledge/SKILL.md:9-10,32,38` | execution-contract.md, knowledge-lifecycle.md; `.ai/knowledge/claims-index.json`; `.ai/knowledge/keyword-taxonomy.md` | yes (all) |
| `solution-design/SKILL.md:9-10,36` | execution-contract.md, source-authority.md; `.ai/knowledge/known-limitations.md` | yes (all) |
| `tune-test-case-keywords/SKILL.md:9` | execution-contract.md | yes |
| `update-relations/SKILL.md:9-10` | execution-contract.md, knowledge-lifecycle.md | yes |
| `update-knowledge-base/SKILL.md:9-11` | execution-contract.md, knowledge-lifecycle.md, source-authority.md | yes |
| `.ai/knowledge/README.md:4` | `../contracts/knowledge-lifecycle.md` | yes |
| `.ai/knowledge/README.md:47` | `../../.github/skills/search-knowledge/SKILL.md` | yes (cross-category, out-of-brief-scope back-link) |

Every `.ai/contracts/*.md` target resolves. `tool-capabilities.md` exists on disk but has **zero inbound references** found anywhere in agents/skills/instructions/prompts/knowledge — see unresolved.md orphan list.

### E5 — skill/agent → cache/output path

| source (file:line) | target (literal path) | resolves |
|---|---|---|
| config-investigator.agent.md:43,55 | `.cache/knowledge-proposals/` | yes |
| development-assistant.agent.md:80 | `.cache/devtool-batches/` | **no** — not provisioned on disk, no `.gitkeep` |
| development-assistant.agent.md:83 | `.cache/receipts/` | **no** — not provisioned on disk, no `.gitkeep` |
| test-strategist.agent.md:51 | `output/` (general write scope) | yes |
| batch-knowledge/SKILL.md:30 | `.cache/knowledge-proposals/` | yes |
| batch-knowledge/SKILL.md:91 | `output/documentation/batch-knowledge-<Type>-<date>.md` (pattern) | yes |
| fetch-ado-item/SKILL.md:25 | `.cache/ado-items/<id>.json` (pattern) | yes |
| feature-documentor/SKILL.md:43 | `output/feature-dossiers/<slug>.md` (pattern) | yes (dir exists, populated, but not `.gitkeep`-tracked — see storage conventions) |
| generate-technical-documentation/SKILL.md:41 | `output/documentation/<itemId>.md` (pattern) | yes |
| generate-release-handover/SKILL.md:33 | `output/handover/<period>.md` (pattern) | yes |
| propose-force-app-knowledge/SKILL.md:23 | `.cache/knowledge-proposals/force-app-drafts/manifest.json` | yes |
| generate-playwright-test/SKILL.md:42 | `output/generated-tests/` | yes |
| solution-design/SKILL.md:70 | `output/solution-design/<itemId>-design.md` (pattern) | yes |
| fetch-test-case/SKILL.md:19 | `.cache/test-cases/<id>.json` (pattern) | yes |
| update-knowledge-base/SKILL.md:27 | `.cache/knowledge-proposals/` | yes |
| update-relations/SKILL.md:55 | `.cache/knowledge-proposals/force-app-drafts/` | yes |
| update-relations/SKILL.md:62 | `output/documentation/update-relations-<date>.md` (pattern) | yes |
| search-ado/SKILL.md:27,31,46 | `.cache/ado-wiki/` (×3) | **no** — directory does not exist on disk, no `.gitkeep`, not among the three provisioned `.cache/` subdirs |
| inventory-force-app/SKILL.md:19 | `.cache/knowledge-proposals/force-app-inventory.json` | yes |

Three referenced cache paths do not exist as provisioned directories: `.cache/devtool-batches/`, `.cache/receipts/` (development-assistant.agent.md), `.cache/ado-wiki/` (search-ado/SKILL.md). May be create-on-first-use at runtime — reported as fact, not judged.

### E6 — template section ↔ producing skill step

| template file | sections | claiming skill | resolves |
|---|---|---|---|
| `change-record.md` (9 sections) | all 9 | **none found.** Repo-wide grep for "change-record" under `.github/` hits only `.github/CODEOWNERS:7` (path ownership) and a generic phrase in `solution-designer.agent.md:62` ("change-record artifacts") that never names this template file. `solution-design/SKILL.md` Phase 2 defines its own inline section list for `design.md`, with different names/order, never citing this template. | **no** |
| `feature-dossier.md` (7 sections) | all | `feature-documentor/SKILL.md:41-43` writes `output/feature-dossiers/<slug>.md` via a script (`force_app_knowledge.py feature-draft`); template line 7 says edit the generator, not the output — true producer is a script, not skill prose. | yes (path/skill pairing); section-level mapping is via script, not literal skill text |
| `feature-health-report.md` (6 sections) | all | `check-feature-coverage/SKILL.md:36` ("Save all mandatory sections using the Feature Health template"), bidirectional with template's own header. §5 "Open questions" has no explicit skill step naming it. | yes; §5 unmapped |
| `knowledge-entry.md` | all | **none found.** Repo-wide grep for "knowledge-entry" under `.github/` returns zero hits; no "Used by skill" header on this template either — genuine two-way silence. | **no** |
| `release-handover.md` | all | `generate-release-handover/SKILL.md:33`, bidirectional with template header. Section itemization (Summary/Technical table/Tests) is aggregate only, not per-section. | yes |
| `technical-documentation.md` (9 sections) | all | `generate-technical-documentation/SKILL.md:39` ("Fill every section of the technical-documentation template"), bidirectional with template header. §6 "Verification approach" and §8 "Known limitations/open questions" have no dedicated producing step. | yes; §6, §8 unmapped |

No skill/agent file anywhere references any of the four attributed templates (`feature-dossier.md`, `feature-health-report.md`, `release-handover.md`, `technical-documentation.md`) by literal filename — all matches rely on generic phrasing or output-path pattern matching, not a hard file-path link.

### E7 — knowledge README index ↔ actual file

| source (file:line) | target (literal text) | resolves |
|---|---|---|
| README.md:9 | `[claims/](claims/)` | yes (empty save `.gitkeep`) |
| README.md:10 | `[evidence/](evidence/)` | yes (empty save `.gitkeep`) |
| README.md:11 | `[reviews/](reviews/)` | yes (empty save `.gitkeep`) |
| README.md:18 | `[current-implementation.md](current-implementation.md)` | yes |
| README.md:19 | `[business-processes.md](business-processes.md)` | yes |
| README.md:20 | `[object-relations.md](object-relations.md)` | yes |
| README.md:21 | `[object-descriptions.md](object-descriptions.md)` | yes |
| README.md:22 | `[field-descriptions.md](field-descriptions.md)` | yes |
| README.md:23 | `[automation-map.md](automation-map.md)` | yes |
| README.md:24 | `[integration-map.md](integration-map.md)` | yes |
| README.md:25 | `[glossary.md](glossary.md)` | yes |
| README.md:26 | `[known-limitations.md](known-limitations.md)` | yes |
| README.md:27 | `[component-inventory.md](component-inventory.md)` | yes |
| README.md:28 | `[claims-index.json](claims-index.json)` | yes |
| README.md:29 | `[keyword-taxonomy.md](keyword-taxonomy.md)` | yes |

**Reverse check — actual `.ai/knowledge/*.md` files NOT mentioned in the README index:** `feature-map.md` exists on disk (generated by feature-documentor per its own header) but has zero mention anywhere in README.md (confirmed by full-file read and grep). No other knowledge file is unindexed.

### E8 — documentation ↔ built reality

| source (file:section/line) | literal target/count claimed | actual disk reality | resolves |
|---|---|---|---|
| Blueprint §5 file tree, lines 500 | `HARNESS_BLUEPRINT.md` listed as living at repo root ("ten dokument — zostaje w repo na stałe" / "stays in repo permanently") | Lives at `docs/archive/HARNESS_BLUEPRINT.md` | **no** |
| Blueprint §5 file tree, lines 507-512 | 4 agents: solution-designer, config-investigator, development-assistant, guardrail-reviewer (test-strategist absent) | 5 agents on disk (adds test-strategist) | **no** |
| Blueprint §10 heading + prose, lines 714, 732-792 | "pięć agentów" (five agents), and prose fully describes all 5 including test-strategist | 5 agents on disk | yes — **but this directly contradicts Blueprint §5's own file tree in the same document** (see above) |
| Diagram §1.3 (`*.github/`* structure), lines 64-106, mirrors Blueprint §5 | Same 4 agents (A1-A4), test-strategist absent | 5 agents on disk | **no** — matches the archive README's own stated "known drift: four vs five agents" |
| Diagram §2.1 "Five-agent SDLC pipeline", lines 165-182 | Explicitly includes Test Strategist in the flowchart and heading | 5 agents on disk | yes — **also internally inconsistent with the same file's own §1.3** |
| Blueprint §5 + §11 skills list, lines 513-525, 796-1093 | 12 skills: investigate-object, fetch-ado-item, check-against-principles, generate-technical-documentation, check-feature-coverage, generate-release-handover, fetch-test-case, sync-test-cases, suggest-test-cases, tune-test-case-keywords, generate-playwright-test, update-knowledge-base | 22 skills on disk | **no** — 10 built skills absent from blueprint: curate-knowledge-keywords, solution-design, batch-knowledge, update-relations, feature-documentor, inventory-force-app, propose-force-app-knowledge, relation-health, search-ado, search-knowledge |
| Diagram §1.3 skills list (S1-S12), lines 86-97 | Same 12 skills as blueprint | 22 skills on disk | **no** — same 10 missing |
| Blueprint §5 + §12 prompts list, lines 526-533, 1094-1145 | 7 prompts: fetch-ado-item, document-metadata-change, feature-health, release-handover, sync-test-cases, tune-test-case-keywords, generate-playwright-test | 20 prompts on disk | **no** — 13 built prompts absent: batch-knowledge, check-against-principles, feature-documentor, inventory-force-app, investigate-object, propose-force-app-knowledge, refresh-force-app-knowledge, relation-health, search-ado, search-knowledge, solution-design, suggest-test-cases, update-relations |
| Diagram §1.3 prompts list (P1-P7), lines 99-105 | Same 7 prompts as blueprint | 20 prompts on disk | **no** — same 13 missing |
| Blueprint §5 + §8 `.ai/knowledge/` list, lines 534-546 | 11 files: README.md + 10 domain files (no component-inventory.md, no feature-map.md; no claims/evidence/reviews/claims-index.json) | 13 `.md` files + claims-index.json + 3 subdirs on disk | **no** — missing: component-inventory.md, feature-map.md, claims-index.json, claims/, evidence/, reviews/ |
| Diagram §1.4 `.ai/` structure, lines 108-142 | Same 11-file knowledge list, same 4 templates, same 3 QA items | Actual: 13 knowledge md + schema-v3 additions; 6 templates; QA matches | **no** for knowledge/templates counts; QA structure itself resolves |
| Blueprint §5 + §13 `.ai/templates/` list, lines 549-553, 1216-1288 | 4 templates: technical-documentation, feature-health-report, knowledge-entry, release-handover | 6 templates on disk | **no** — missing change-record.md, feature-dossier.md |
| Blueprint §5, no `.ai/contracts/` entry anywhere | `.ai/contracts/` not present in file tree at all | 5 contract files on disk, heavily referenced by nearly every agent/skill (see E4) | **no** — entire directory absent from the blueprint's structural model |
| Blueprint §5 + §13 `.cache/` list, lines 559-563, 1146-1182 | 2 subdirs: ado-items/, test-cases/ | 3 subdirs on disk: adds knowledge-proposals/ (populated with ~80 files), plus denials.log | **no** |
| Blueprint §5 + §13 `output/` list, lines 564-572 | 4 subdirs: documentation/, feature-health/, handover/, generated-tests/ | 6 subdirs on disk: adds feature-dossiers/, solution-design/ | **no** |
| Diagram §1.5 `.cache/`/`output/` structure, lines 144-159 | Same 2 cache + 4 output subdirs as blueprint | Same actual reality as above | **no** |

**Summary count claims:** neither document states a bare numeric count like "4 agents" in running prose (the archive README's own "four vs five" framing refers to what the diagram's agent list *shows*, not a stated digit) — the drift is structural (file/entity lists), not a false arithmetic claim, except where §5's tree and §10's prose contradict each other within the same document.

---

## Notes carried forward from all contributing passes (not silently dropped)

- `.ai/contracts/tool-capabilities.md` — zero inbound references found anywhere (agents, skills, instructions, prompts, knowledge). Orphan candidate — see unresolved.md.
- Two empty `agents/` subfolders under skills (`inventory-force-app/agents/`, `propose-force-app-knowledge/agents/`) — zero inbound or outbound references anywhere. Orphan candidates — see unresolved.md.
- `change-record.md` and `knowledge-entry.md` templates carry no "Used by skill" header and no skill references them back — genuine two-way silence, structurally different from the other four templates (which are one-way-silent: named forward by their own header, not named back by skill prose).
- `test-strategist.agent.md:30` ("Load only the QA skill selected for the current record") is a category reference, not a literal target — marked ambiguous, not guessed. Candidate QA skills in scope: check-feature-coverage, sync-test-cases, suggest-test-cases, generate-playwright-test, tune-test-case-keywords, fetch-test-case.
- All Knowledge/Memory/QA content files are in a genuinely empty/scaffold state (no claims, only 5 decision-log entries, no test-case suite files, no UI-quirk or keyword-map entries) — stated as observed fact, not a defect characterization.
