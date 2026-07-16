# Unresolved Edges and Orphan Candidates — Copilot Harness Audit

Companion to `module-map.md`. Read-only, report-only: no defect judgment, no fixes. Facts only.

---

## (a) Edges whose target does not resolve

### E5 — cache paths referenced but not provisioned on disk

| source (file:line) | target | status |
|---|---|---|
| `.github/agents/development-assistant.agent.md:80` | `.cache/devtool-batches/` | no — directory does not exist, no `.gitkeep`, not among the three provisioned `.cache/` subdirs (`ado-items/`, `test-cases/`, `knowledge-proposals/`) |
| `.github/agents/development-assistant.agent.md:83` | `.cache/receipts/` | no — same as above |
| `.github/skills/search-ado/SKILL.md:27,31,46` | `.cache/ado-wiki/` (×3 references) | no — same as above |

### E8 — documentation vs. built reality (structural, all within `docs/archive/HARNESS_BLUEPRINT.md` and `docs/archive/HARNESS_DIAGRAMS.md`)

| source | claimed | actual | status |
|---|---|---|---|
| Blueprint §5, line 500 | `HARNESS_BLUEPRINT.md` lives at repo root, "stays in repo permanently" | Lives at `docs/archive/HARNESS_BLUEPRINT.md` | no |
| Blueprint §5 file tree (lines 507-512) | 4 agents (test-strategist absent) | 5 agents on disk | no |
| Diagram §1.3 (lines 81-85) | Same 4 agents (test-strategist absent) | 5 agents on disk | no |
| Blueprint §5 + §11 skills list | 12 skills | 22 skills on disk | no — 10 unlisted: curate-knowledge-keywords, solution-design, batch-knowledge, update-relations, feature-documentor, inventory-force-app, propose-force-app-knowledge, relation-health, search-ado, search-knowledge |
| Diagram §1.3 skills list (S1-S12) | Same 12 skills | 22 skills on disk | no — same 10 unlisted |
| Blueprint §5 + §12 prompts list | 7 prompts | 20 prompts on disk | no — 13 unlisted: batch-knowledge, check-against-principles, feature-documentor, inventory-force-app, investigate-object, propose-force-app-knowledge, refresh-force-app-knowledge, relation-health, search-ado, search-knowledge, solution-design, suggest-test-cases, update-relations |
| Diagram §1.3 prompts list (P1-P7) | Same 7 prompts | 20 prompts on disk | no — same 13 unlisted |
| Blueprint §5 + §8 knowledge list | 11 files (README + 10 domain files) | 13 md files + claims-index.json + 3 subdirs on disk | no — unlisted: component-inventory.md, feature-map.md, claims-index.json, claims/, evidence/, reviews/ |
| Diagram §1.4 knowledge list (K0-K10) | Same 11 files | Same actual reality | no — same items unlisted |
| Blueprint §5 + §13 templates list | 4 templates | 6 templates on disk | no — unlisted: change-record.md, feature-dossier.md |
| Diagram §1.4 templates list (T1-T4) | Same 4 templates | Same actual reality | no — same items unlisted |
| Blueprint §5 — `.ai/contracts/` | Not present anywhere in file tree | 5 contract files on disk, heavily referenced by nearly every agent/skill | no — whole directory absent from blueprint's model |
| Blueprint §5 + §13 `.cache/` list | 2 subdirs (ado-items/, test-cases/) | 3 subdirs on disk | no — unlisted: knowledge-proposals/ (populated, ~80 files) |
| Diagram §1.5 cache structure | Same 2 subdirs | Same actual reality | no |
| Blueprint §5 + §13 `output/` list | 4 subdirs | 6 subdirs on disk | no — unlisted: feature-dossiers/, solution-design/ |
| Diagram §1.5 output structure | Same 4 subdirs | Same actual reality | no |

### E6 — template↔skill claims with no resolving counterpart

| item | status |
|---|---|
| `.ai/templates/change-record.md` — all 9 sections | no — zero skill claims to produce this template by literal filename; `solution-design/SKILL.md` Phase 2 defines its own differently-named/ordered section list for `design.md` without citing this template |
| `.ai/templates/knowledge-entry.md` | no — zero skill references this template's filename anywhere; template itself has no "Used by skill" back-reference either (two-way silence) |
| `.ai/templates/feature-health-report.md` §5 "Open questions" | no — no skill step explicitly names/produces this section |
| `.ai/templates/technical-documentation.md` §6 "Verification approach" | no — no skill step explicitly produces this section |
| `.ai/templates/technical-documentation.md` §8 "Known limitations/open questions" | no — only implicitly covered by the same Knowledge-query step used for §5, not separately addressed |

---

## (b) Modules with zero inbound edges (orphan candidates)

| module | evidence of zero inbound reference |
|---|---|
| `.ai/contracts/tool-capabilities.md` | Exists on disk (5 contract files present); the other 4 contracts (`execution-contract.md`, `source-authority.md`, `knowledge-lifecycle.md`, `workflow-state-machine.md`) are each referenced by multiple agents/skills (see E4 table in module-map.md), but `tool-capabilities.md` has zero hits across agents, skills, instructions, and prompts. |
| `.github/skills/inventory-force-app/agents/` | Empty subdirectory (zero files). No inbound reference found anywhere pointing at this path. |
| `.github/skills/propose-force-app-knowledge/agents/` | Empty subdirectory (zero files). No inbound reference found anywhere pointing at this path. |
| `.ai/knowledge/feature-map.md` | Exists on disk, generated-by-convention (per its own header, written by feature-documentor), but is the one knowledge file **not indexed in `.ai/knowledge/README.md`** — no inbound README pointer (E7 reverse-check). It does have a producer (feature-documentor), so this is an indexing gap, not a fully unreferenced file — noted distinctly from the two truly-orphan `agents/` folders above. |
| `.ai/templates/change-record.md` | No skill/agent references this template by literal filename anywhere in `.github/`. (It does have an implicit conceptual link — `solution-designer.agent.md` produces "change-record artifacts" in prose — but never cites this specific template file, and no header on the template points back either.) |
| `.ai/templates/knowledge-entry.md` | No skill/agent references this template by literal filename anywhere in `.github/`. No header on the template points back either — the only template with zero connection in both directions. |
| `.github/instructions/rule-registry.yaml` | Present in the same directory as the three `.instructions.md` Principles files and is their machine-readable backing data, but no fork traced an explicit inbound reference to this exact filename from any agent/skill/prompt body during this pass — flagged here rather than silently assumed connected, since verifying its consumer(s) was outside every fork's assigned edge-type scope (E1–E8 as defined don't cover "principles file → registry" as a slot). Needs a targeted check in a follow-up pass before being called a true orphan. |

---

## Anything not classifiable under E1–E8 (reported, not dropped)

- **Agent → agent edges** (frontmatter `agents:` arrays, `handoffs[].agent:` fields) — a real, heavily-used connection type with no slot in E1–E8. All targets resolve to real agent names. Example: `development-assistant.agent.md` frontmatter `agents: [config-investigator, test-strategist]`; handoff chains link all 5 agents into the pipeline described in Blueprint §10 / Diagram §2.1.
- **Prompt → prompt edges** (one prompt's body telling the user/agent to run another prompt) — no slot in E1–E8. Found: `search-ado.prompt.md` → `/fetch-ado-item`; `search-knowledge.prompt.md` → `/investigate-object`, `/propose-force-app-knowledge`; `suggest-test-cases.prompt.md` → `/sync-test-cases`, `/feature-health`. All resolve to real prompts.
- **`.ai/contracts/` as a category** — the audit brief's Task 1 category list (Entry instructions / Principles / Agents / Skills / Prompts / Knowledge / Memory / Templates / QA / Storage / Documentation) has no slot for this directory, despite it being one of the most heavily inbound-referenced module families in the whole workspace (E4). Inventoried in module-map.md under its own ad hoc heading rather than omitted.
- **Internal self-contradiction within a single documentation file** (distinct from doc-vs-reality drift): Blueprint §5's file tree and Diagram §1.3 both show 4 agents, while Blueprint §10's own heading ("pięć agentów" / five agents) and full prose, and Diagram §2.1's own heading ("Five-agent SDLC pipeline") and flowchart, both show 5 and include test-strategist. This is two sections of the *same* document pair disagreeing with each other, not just with the built harness — reported under E8 in module-map.md but called out here separately since it's a different kind of fact than doc-vs-disk drift.

---

## Completion summary

**Modules counted per category:**
- Entry instructions: 1 (`copilot-instructions.md`)
- Principles: 3 `.instructions.md` files + 1 supporting `rule-registry.yaml`
- Agents: 5
- Skills: 22 (+ 1 non-SKILL reference doc `inventory-force-app/references/coverage.md`; + 2 empty `agents/` subfolders)
- Prompts: 20
- Knowledge: 13 `.md` files + 1 JSON index + 3 schema-backed subdirectories (all currently empty scaffolds)
- Memory: 1 (`decisions-log.md`)
- Templates: 6
- QA: 3 files (`ui-navigation-patterns.md`, `keywords-map.md`, `test-cases/README.md`) + empty `test-cases/` suite-file scaffold
- Storage conventions: `.cache/` (3 subdirs), `output/` (6 subdirs), `.gitignore` (documented)
- Documentation: 2 (`docs/archive/HARNESS_BLUEPRINT.md`, `docs/archive/HARNESS_DIAGRAMS.md` — not at repo root)
- Ad hoc / brief-omitted category: `.ai/contracts/` — 5 files

**Edges counted per type:**
- E1 (prompt→skill): 21 edges, 21 resolve, 0 unresolved, 0 ambiguous
- E2 (skill→skill): 18 edges, 18 resolve, 0 unresolved, 0 ambiguous
- E3 (agent→skill): 9 edges, 8 resolve, 0 unresolved, 1 ambiguous (test-strategist.agent.md:30)
- E4 (→knowledge/memory/template/qa/contracts path): ~55 edges across all agents/skills/instructions, all resolve
- E5 (→cache/output path): 19 edges, 16 resolve, 3 unresolved (`.cache/devtool-batches/`, `.cache/receipts/`, `.cache/ado-wiki/`)
- E6 (template section ↔ producing skill step): 6 templates checked; 4 have a resolving producer (with some individual unmapped sections — see above), 2 have none (`change-record.md`, `knowledge-entry.md`)
- E7 (knowledge README index ↔ actual file): 15 index entries, all 15 resolve; 1 reverse-direction gap (`feature-map.md` not indexed)
- E8 (documentation ↔ built reality): 16 structural comparisons made, 14 do not resolve (only the two agent-count prose statements — Blueprint §10 and Diagram §2.1 — match actual reality of 5 agents, while every file-list/count elsewhere in the same two documents does not)

**Unresolved edge count:** 3 (E5) + 14 (E8) + 5 template-section gaps (E6) + 1 ambiguous (E3) = **22 non-resolving items** (mixing "no" and "ambiguous" per the brief's three-way classification; see full breakdown above).

**Orphan count:** 6 modules with zero (or, for `feature-map.md`, zero *indexed*) inbound references — `.ai/contracts/tool-capabilities.md`, `inventory-force-app/agents/`, `propose-force-app-knowledge/agents/`, `.ai/knowledge/feature-map.md`, `.ai/templates/change-record.md`, `.ai/templates/knowledge-entry.md` — plus one flagged-but-unverified candidate (`.github/instructions/rule-registry.yaml`, needs a targeted follow-up check since no fork's assigned scope covered "principles→registry" as an edge type).

**Anything not classifiable under E1–E8 (explicit, not silently skipped):**
1. Agent→agent edges (frontmatter `agents:`, `handoffs[].agent:`) — no E-type slot; resolve.
2. Prompt→prompt edges (body text pointing to other slash-prompts) — no E-type slot; resolve.
3. `.ai/contracts/` as a whole category — not named in the brief's Task 1 category list despite being heavily referenced.
4. Internal self-contradiction between Blueprint §5/Diagram §1.3 (4 agents) and Blueprint §10/Diagram §2.1 (5 agents) within the same document pair — a different kind of fact than doc-vs-disk drift, reported separately.
5. `rule-registry.yaml`'s consumer(s) were not conclusively traced by any fork's assigned scope — flagged as needing a targeted follow-up rather than asserted as either resolved or orphaned.

**Process note (transparency, not in scope of the technical audit but relevant to how these findings were produced):** three of the five parallel research forks used to gather this audit lost track of their own task assignment partway through and initially returned coordinator-style status text instead of findings on their first stop. All three were resumed with corrective prompts; two then produced complete reports, and the third refused the resume message (treating it as a suspected prompt injection) — that slice (documentation modules / E8) was completed directly by the coordinating session instead of the fork. This is disclosed here for transparency about provenance; it does not by itself indicate any finding above is inaccurate, but the E8 section should be weighted as coordinator-verified rather than fork-verified if that distinction matters for follow-up work.
