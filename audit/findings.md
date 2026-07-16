# Audit Findings — Copilot Harness Workspace

Audit phase: read-only verification (2026-07-16), following `audit/module-map.md` and
`audit/unresolved.md`, checklist C1–C11. Every finding was re-verified against the actual files;
line numbers and quotes are literal.

**Recorded premises (user decisions, 2026-07-16, via interactive question):**

1. `docs/archive/HARNESS_BLUEPRINT.md` is an **outdated reference**; the **current workspace is
   the source of truth**. The C1–C11 workflow was kept, grounded in the workspace. Documented
   post-blueprint evolution is consolidated into grouped findings (B3 where rationale is
   recorded, B2 where a decision is still needed); individual F-NN entries are reserved for
   genuine defects and inconsistencies.
2. The parking-lot items that were later built (`.github/hooks/`, configured `.vscode/mcp.json`)
   are bucketed **B3 with rationale** cited from `.ai/memory/decisions-log.md`.

Buckets: B1 = implementation defect (directly fixable) · B2 = divergence needing a design
decision · B3 = deliberate deviation, rationale recorded. Class: M = mechanical (grep/ls
verifiable) · S = semantic (required judgment).

---

## Findings

### F-01 | Stale module counts in current-authority docs (README.md, SETUP.md) | B1 | M | APPROVED

- **Evidence:**
  - `README.md:4-5` — "five SDLC agents, **twelve public prompt commands, sixteen internal
    skills**, governed but initially unseeded Knowledge/Memory/QA layers"
  - `README.md:33` — "| Public commands | `.github/prompts/` | **Twelve** deterministic
    slash-command entry points |"
  - `README.md:34` — "| Internal capabilities | `.github/skills/` | **Sixteen** progressively
    loaded procedures hidden from the slash menu |"
  - `SETUP.md:147` — "Confirm exactly five agents, **twelve public prompts, sixteen internal
    skills**, three Principle"
  - `SETUP.md:149` — "Confirm `/` shows the **twelve prompts** once each and their argument hints."
  - Reality: `scripts/validate_harness.py:25` — `EXPECTED_COUNTS = {"agents": 5, "prompts": 20,
    "skills": 22, "instructions": 3}`; 20 `.prompt.md` files and 22 `SKILL.md` files exist on disk.
  - Root cause trail: `.ai/memory/decisions-log.md:69-70` (2026-07-14) — "counts moved to
    12 prompts / 16 skills and the validator now derives all counts from one constant" — the
    validator constant was subsequently bumped twice (to 20/22) but README/SETUP prose was not.
- **Blueprint reference:** C10 (documentation ↔ built files). README.md is the workspace's own
  declared "Current authority" (README.md:9), so this is an internal defect, not archive drift.
- **Proposed action (B1, str_replace-ready):**
  - `README.md`: "twelve public prompt commands, sixteen internal skills" → "twenty public prompt
    commands, twenty-two internal skills"
  - `README.md`: "Twelve deterministic slash-command entry points" → "Twenty deterministic
    slash-command entry points"
  - `README.md`: "Sixteen progressively loaded procedures hidden from the slash menu" →
    "Twenty-two progressively loaded procedures hidden from the slash menu"
  - `SETUP.md`: "Confirm exactly five agents, twelve public prompts, sixteen internal skills" →
    "Confirm exactly five agents, twenty public prompts, twenty-two internal skills"
  - `SETUP.md`: "Confirm `/` shows the twelve prompts once each" → "Confirm `/` shows the twenty
    prompts once each"
  - Alternative (sturdier): replace literal numbers with a pointer to the validator inventory line
    (`validate_harness.py:927-928` prints the derived counts) so prose cannot drift again.
- **Status:** FIXED 2026-07-16 — literal-number str_replace edits applied (README.md ×3,
  SETUP.md ×2); the validator-pointer alternative was not taken.

### F-02 | Three referenced `.cache/` subdirectories have no tracked skeleton | B1 | M | APPROVED

- **Evidence:**
  - `.github/skills/search-ado/SKILL.md:27` — "check `.cache/ado-wiki/` first"; `:31` — "write the
    page atomically to `.cache/ado-wiki/<12-hex-digest-of-wiki+path>.json`"; `:46` — "Cache writes
    go only to `.cache/ado-wiki/`."
  - `.github/agents/development-assistant.agent.md:80-81` — "write one schema-valid plan
    (`schemas/dev-tool-batch.schema.json`) under `.cache/devtool-batches/`"; `:83` — "never edit
    `.cache/receipts/`."
  - On disk, `.cache/` contains only `ado-items/.gitkeep`, `test-cases/.gitkeep`,
    `knowledge-proposals/.gitkeep` (plus runtime content). `ado-wiki/`, `devtool-batches/`,
    `receipts/` do not exist and are not documented as created-on-first-use.
  - The workspace's own contract: `.gitignore:6-7` — "The folder structure itself stays tracked
    via .gitkeep, so re-include directories and .gitkeep explicitly."
- **Blueprint reference:** C4 (file-path contracts).
- **Proposed action (B1):** create `.cache/ado-wiki/.gitkeep`, `.cache/devtool-batches/.gitkeep`,
  `.cache/receipts/.gitkeep` (matching the pattern the other three cache subdirs follow), or —
  if runtime creation is preferred — add an explicit "created on first use" note next to each
  reference and to the `.gitignore` comment block.
- **Status:** FIXED 2026-07-16 — `.cache/ado-wiki/.gitkeep`, `.cache/devtool-batches/.gitkeep`,
  `.cache/receipts/.gitkeep` created; `git check-ignore -v` confirms each matches the
  `!.cache/**/.gitkeep` re-include rule.

### F-03 | `generate-release-handover` never references its template | B1 | M | APPROVED

- **Evidence:**
  - `.ai/templates/release-handover.md` exists (64 lines, sections: Header, Handover description,
    Table of contents, per-item Summary/Technical table/Tests).
  - `.github/skills/generate-release-handover/SKILL.md:31` — "Compose every item section." — no
    mention of the template anywhere in the skill (grep for "template" across `.github/` hits only
    the two skills below).
  - Workspace convention that establishes the contract:
    `.github/skills/generate-technical-documentation/SKILL.md:39` — "Fill every section of the
    technical-documentation template and common output envelope"; and
    `.github/skills/check-feature-coverage/SKILL.md:36` — "Save all mandatory sections using the
    Feature Health template and the output envelope."
  - Content is currently consistent (both skill `:31-32` and the template's Tests section carry
    the exact fallback "Tested based on acceptance criteria"), but nothing ties them together.
- **Blueprint reference:** C5 (template ↔ skill field contract); blueprint §11 skill 6.
- **Proposed action (B1, str_replace-ready in
  `.github/skills/generate-release-handover/SKILL.md`):**
  - old: "6. Compose every item section."
  - new: "6. Compose every item section using the
    [release-handover template](../../../.ai/templates/release-handover.md)."
- **Status:** FIXED 2026-07-16 — str_replace applied (old string is the unique prefix of skill
  line 31; the rest of the sentence, "When no formal Test Case exists…", is preserved).

### F-04 | `feature-map.md` missing from the Knowledge index | B1 | M | APPROVED

- **Evidence:**
  - `.ai/knowledge/feature-map.md:1-4` — "# Feature Map — Generated Claim Index / Generated view
    grouping canonical claims by the feature-membership tag written by the feature documentor.
    Do not hand-edit." — a generated domain view like the twelve that are indexed.
  - `.ai/knowledge/README.md:16-29` — the "Domain view" table lists 12 rows
    (current-implementation … keyword-taxonomy); `grep -c "feature-map" .ai/knowledge/README.md`
    returns 0.
  - No dead entries in the other direction: every file the index lists exists on disk.
- **Blueprint reference:** C6 (knowledge index completeness); blueprint §11 skill 12
  (`update-knowledge-base` maintains the README on every new Knowledge file).
- **Proposed action (B1, str_replace-ready in `.ai/knowledge/README.md`):** insert after the
  `component-inventory.md` row:
  `| [feature-map.md](feature-map.md) | Generated view grouping canonical claims by feature-membership tag (written by the feature documentor). |`
  (If the README table is meant to be produced by the index renderer, fix the renderer instead —
  same target state.)
- **Status:** FIXED 2026-07-16 — row inserted after the `component-inventory.md` row; verified
  the table is hand-maintained (no script references `knowledge/README`), so no renderer change
  was needed.

### F-05 | Prompt bodies restate skill procedure (thin-wrapper rule divergence) | B2 | S

- **Evidence (all four restate content that also lives in the invoked skill):**
  - `.github/prompts/batch-knowledge.prompt.md:12-14` — "optional `chunk=<N>` (components per
    execution chunk, default 10, max 25). Announce each phase as you enter it (DISCOVER → PLAN →
    VERIFY PLAN → EXECUTE → VERIFY) and never skip or reorder phases"; `:18-20` — a restated resume
    rule ("rerun `inventory` and `worklist --metadata-type <Type>` per the skill's resume rule").
    Duplicated constant: `.github/skills/batch-knowledge/SKILL.md:43` — "(default 10, max 25 — the
    chat-approval batch cap)".
  - `.github/prompts/solution-design.prompt.md:16-18` — "Announce each phase as you enter it
    (DISCOVER → PLAN → VERIFY → EXECUTE → VERIFY) and do not skip or reorder phases. A failed
    verification returns to the phase that caused it".
  - `.github/prompts/refresh-force-app-knowledge.prompt.md:12` — "Stop after inventory when source
    is partial, dirty, untracked, or changed after scanning."
  - `.github/prompts/feature-documentor.prompt.md:12-16` — crawl-boundary procedure ("The crawl
    reads only tracked `force-app` source at a clean commit … keep the boundary tight with `depth`
    and `hubs`, and present it for confirmation before drafting").
- **Assessment:** no prompt contains logic *absent* from its skill — the defect is duplication
  (drift risk, e.g. the chunk cap lives in two places), not hidden business logic. The
  thin-wrapper rule ("Prompts are always thin … No business logic lives in `.prompt.md`") exists
  only in the archived blueprint (§11/§12); no current-authority doc restates or retires it.
- **Blueprint reference:** C1; blueprint §11 (reusability rule), §12 (thin wrappers).
- **Proposed action (B2 — drafted decision text, apply to a current-authority doc, not the
  archived blueprint):** *"Prompt files remain argument-parsing + skill invocation. They MAY
  restate safety framing and phase-announcement discipline verbatim from the skill, but MUST NOT
  carry numeric limits, resume procedures, or stop conditions — those live only in the SKILL.md,
  which the prompt links."* If accepted, trim the duplicated constants/procedures from the four
  prompts; if rejected, record the duplication as accepted convention.

### F-06 | Template layer partially decorative: three templates have no producing consumer | B2 | S | APPROVED

- **Evidence:**
  - `.ai/templates/change-record.md:1` — "# Design Narrative — <record ID>: <title>" — zero
    inbound references anywhere in the workspace; the scaffold is instead embedded in code:
    `scripts/work_record.py:1350` — `return f"""# Design Narrative — {record_id}: {title}`.
  - `.ai/templates/feature-dossier.md` — zero references from the feature-documentor skill or
    scripts; the dossier structure is hardcoded in `scripts/force_app_knowledge.py:1844`
    (`def render_dossier(...)`).
  - `.ai/templates/knowledge-entry.md` — only inbound reference is a field mention in
    `.ai/knowledge/keyword-taxonomy.md:4`; claim drafting is done by scripts validated against
    `schemas/knowledge-claim.schema.json` (which `knowledge-entry.md:4-6` itself defers to).
  - Only scripts-side use of the templates directory is the validator's existence glob:
    `scripts/validate_harness.py:383` — `paths.extend((ROOT / ".ai/templates").glob("*.md"))`.
- **Assessment:** two templates (`technical-documentation.md`, `feature-health-report.md`) are
  normative (skill-referenced); three are shadow copies of structures owned elsewhere. When
  `work_record.py` or `render_dossier` changes, the template silently lies.
- **Blueprint reference:** C5; blueprint §4 ("Skills apply Templates").
- **Proposed action (B2 — drafted decision):** *"Each `.ai/templates/*.md` file is either
  (a) normative — referenced by the producing skill or read by the producing script — or
  (b) removed. Script-embedded scaffolds (`work_record.py` design narrative,
  `render_dossier`) either read their template file or the duplicate template is deleted;
  `knowledge-entry.md` is either cited by `investigate-object`/`update-knowledge-base` as the
  human-facing companion to the claim schema, or removed in favor of the schema."*
- **Status:** FIXED 2026-07-16 — decision recorded amendment-first in
  `.ai/memory/decisions-log.md` ("2026-07-16 - Templates are normative or removed"; the workspace,
  not the archived blueprint, is the source of truth per premise 1). `change-record.md` and
  `feature-dossier.md` deleted (`git rm`); `knowledge-entry.md` kept and cited by
  `investigate-object/SKILL.md` (step 7) and `update-knowledge-base/SKILL.md` (step 4).

### F-07 | `tool-capabilities.md` contract is loaded by no role or skill | B2 | S | APPROVED

- **Evidence:**
  - `.ai/repo-map.md:11` — "`.ai/contracts` | Normative execution/knowledge/workflow/tooling
    contracts, **loaded per role**".
  - Repo-wide grep: `tool-capabilities` is referenced only by `.ai/repo-map.md`,
    `.ai/repo-map.json`, `scripts/validate_harness.py`, and the audit files. No agent or skill
    loads it — unlike the other four contracts (e.g. `execution-contract` is applied by every
    skill, `source-authority`/`workflow-state-machine` are loaded by four agents,
    `knowledge-lifecycle` by the knowledge skills).
- **Blueprint reference:** C3 extended to contracts (brief: "extend it if you discover more
  contract types"). The contracts layer itself is post-blueprint (covered by F-10).
- **Proposed action (B2 — drafted decision):** *"Either wire `tool-capabilities.md` into the
  agents that dispatch namespaced tools (add it to each agent's Load list, matching the pattern of
  the other contracts), or reclassify it: change its `Status: normative` header to a maintenance
  reference and move it (or note it) accordingly so `repo-map.md`'s 'loaded per role' claim stays
  true."*
- **Status:** FIXED 2026-07-16 — wiring option chosen; decision recorded amendment-first in
  `.ai/memory/decisions-log.md` ("2026-07-16 - tool-capabilities contract wired into every agent
  role"). `[tool capability map](../../.ai/contracts/tool-capabilities.md)` added to the Load
  list of all five `.github/agents/*.agent.md` files.

### F-08 | `applyTo` frontmatter absent on all three instruction files | B3 | M

- **Evidence:**
  - `.github/instructions/managed-package-constraints.instructions.md:1-3`,
    `organization-principles.instructions.md:1-3`,
    `salesforce-best-practices.instructions.md:1-3` — frontmatter contains only `description:`
    (each description begins "Load … explicitly"); no `applyTo:` anywhere in the workspace.
  - Blueprint §6 specified scoped instructions with `applyTo: <glob>`.
- **Recorded rationale (why B3):**
  - `IMPLEMENTATION_HANDOFF.md:213` — "The root instruction file overstates the reliability and
    ordering of `applyTo: \"**\"` files." (carried-forward discovery observation that motivated
    the redesign; blueprint §6 itself flagged this exact uncertainty as "to verify empirically").
  - `.github/copilot-instructions.md:3-4` — "Detailed Principles, Knowledge, skills, and workflow
    contracts are loaded explicitly by the supported custom agent for the task." — the
    explicit-load model is consistently implemented (every agent's Load list names its tiers).
- **Blueprint reference:** C7; blueprint §6 (including its own "Plan B" note anticipating this).
- **Action:** none (deliberate, documented deviation — effectively the blueprint's Plan B).

### F-09 | Parking-lot items built: `.github/hooks/` and configured `.vscode/mcp.json` | B3 | M

- **Evidence:**
  - `.github/hooks/safety.json` exists (12 lines); wired via `.vscode/settings.json`
    (`"chat.hookFilesLocations": { ".github/hooks": true }`) and every agent's `PreToolUse`
    role-guard hook (e.g. `.github/agents/guardrail-reviewer.agent.md:17-21`).
  - `.vscode/mcp.json` exists, fully configured (two servers: `ado-readonly`,
    `salesforce-readonly`).
  - Blueprint §15 parked both: "Hooks (`.github/hooks/*.json`) and enforcement scripts …
    `.vscode/mcp.json` fully configured — part of 'execution harness'".
- **Recorded rationale (why B3, per user decision 2026-07-16):**
  - `.ai/memory/decisions-log.md:94-117` (2026-07-14 — "MCP is read-only; org mutation is not an
    agent capability"): documents the current mcp.json surface ("The configured MCP surface
    (`ado-readonly`, `salesforce-readonly`) is read-only by construction") and names the
    enforcement layers the hooks belong to ("guarded wrapper, review facade, global safety hook,
    role guards, validator checks").
  - `README.md:38` lists `.github/hooks/` in the Runtime layer of the as-built architecture.
- **Blueprint reference:** C11; blueprint §15. Remaining §15 items verified NOT built:
  no `org-diff-check` skill (grep: only archive mentions), nothing git/deployment-automated
  (deploys are human-run per `copilot-instructions.md:60-61`).
- **Action:** none (rationale recorded above).

### F-10 | Grouped post-blueprint evolution (built-but-not-specified / specified-but-rebuilt) | B3 | S

- **Scope (consolidated per user decision):** relative to blueprint §4–§5/§10–§12 the workspace
  adds or reshapes — 10 additional skills (batch-knowledge, curate-knowledge-keywords,
  feature-documentor, inventory-force-app, propose-force-app-knowledge, relation-health,
  search-ado, search-knowledge, solution-design, update-relations); 13 additional prompts; the
  fifth agent (test-strategist) as a first-class `.agent.md`; the `.ai/contracts/` layer
  (5 files); `rule-registry.yaml` (402 lines); the schema-v3 claims/evidence/reviews Knowledge
  model replacing free-form knowledge files; `component-inventory.md`, `feature-map.md`,
  `claims-index.json`; templates `change-record.md`, `feature-dossier.md`; `output/feature-dossiers/`,
  `output/solution-design/`; `.cache/knowledge-proposals/`; the generated atlas
  `.ai/repo-map.md`/`repo-map.json`; CI (`.github/workflows/harness-ci.yml`), `CODEOWNERS`,
  `dependabot.yml`; and the redesign of `copilot-instructions.md` from "table of contents +
  precedence order" (blueprint §7) into the Safety and Grounding Kernel — including that the
  explicit MP > Org > SF precedence sentence now lives in the tier files rather than the kernel
  (see C9 note in the summary).
- **Recorded rationale (why B3):**
  - `README.md:22-25` — "The original design history (`HARNESS_BLUEPRINT.md`, …) lives in
    docs/archive/ … It is historical input only and is not the normative runtime specification
    where it conflicts with the files above."
  - `.ai/memory/decisions-log.md` 2026-07-14 entries (lines 34-117) record the knowledge-coverage,
    batch-conversion, AI-description, and MCP-model decisions with "Approved by: workspace owner
    directive".
  - User decision 2026-07-16 (premise 1 above): workspace is the source of truth.
- **Verified consistency inside the evolution:** the generated atlas `.ai/repo-map.md` matches
  disk exactly (5 agents, 22 skills at lines 44-65, 20 public commands at lines 69-88,
  5 contracts, 3 instructions), and `validate_harness.py:25` pins the same counts.
- **Blueprint reference:** C10 / axis 2(b) and 2(a) consolidated.
- **Action:** none beyond F-01 (the one place where the workspace's own docs failed to keep up).

### F-11 | HARNESS_DIAGRAMS.md contradicts itself on agent count (4 vs 5) | B3 | M

- **Evidence:**
  - `docs/archive/HARNESS_DIAGRAMS.md:81-84` (§1.3 "Workspace structure — `.github/`") — agent
    nodes `A1` solution-designer, `A2` config-investigator, `A3` development-assistant,
    `A4` guardrail-reviewer; no test-strategist node.
  - `docs/archive/HARNESS_DIAGRAMS.md:165` — "### 2.1 **Five-agent** SDLC pipeline"; `:175` —
    `TS["Test Strategist<br/>(test-strategist)"]`.
- **Why B3 despite being a genuine self-contradiction:** the file's own banner,
  `docs/archive/HARNESS_DIAGRAMS.md:3` — "Historical status: some counts and runtime layers are
  stale. The functional flows remain design [record]" — and README.md:22-25 demote it to a frozen
  historical record; editing archived history is out of scope per the recorded premises.
- **Blueprint reference:** C10 (audit every diagram).
- **Action:** none (recorded rationale: archived, banner-disclaimed). If the archive is ever
  revised, §1.3 should gain the `A5` test-strategist node.

### F-12 | Blueprint §16 exact placeholders superseded — documented, not silent | B3 | M

- **Evidence:**
  - `<TU_WSTAW_NAMESPACE_PAKIETU>` (blueprint §16) — absent from the workspace; superseded by the
    generic-package design: `.github/instructions/managed-package-constraints.instructions.md:47-50`
    — "**MP-REG-001 — package rules are registered, not improvised.** … No package-specific rules
    are verified in this generic repository until that registry is populated with real human-owned
    evidence."
  - `<TU_WSTAW_QUERY_ID>` (blueprint §16) — absent; superseded by runtime configuration:
    `.github/skills/generate-release-handover/SKILL.md:14-16` — "Require `period=YYYY-MM` and
    `ado.releaseQueryId` from `config/harness.local.json`. **Historical document placeholders are
    not runtime configuration.** Missing/placeholder/invalid query configuration returns
    `DEPENDENCY UNAVAILABLE`".
  - The four placeholders that DO exist (all in
    `.github/instructions/organization-principles.instructions.md:12,19,27,52` —
    `<TU_WSTAW_KONWENCJE_NAZEWNICZE_FIRMY>`, `<TU_WSTAW_ZASADY_CODE_REVIEW>`,
    `<TU_WSTAW_FORMAT_DOKUMENTOWANIA_DECYZJI>`,
    `<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>`) correspond to blueprint §16's
    descriptive items and are drift-guarded: `scripts/validate_harness.py:56-61`
    (`EXPECTED_HUMAN_PLACEHOLDERS`) fails validation if the set changes. Each placeholder carries
    an explicit fail-safe behavior in its rule text (e.g. `organization-principles:12-13` —
    "mark generated API names `PROVISIONAL — HUMAN REVIEW REQUIRED`"), and
    `.github/agents/guardrail-reviewer.agent.md:58` — "No unresolved relevant placeholder may
    produce `SAFE`."
- **Blueprint reference:** C8; blueprint §16.
- **Action:** none — nothing was silently filled with guessed values and nothing was silently
  dropped; both exact tokens were replaced by documented mechanisms.

### F-13 | Untracked stale root duplicates: `SETUP 2.md`, `SECURITY 2.md` | (unbucketed) | M

- **Discovered during:** fix execution of F-01 (2026-07-16). Not fixed inline per procedure.
- **Evidence:**
  - `SETUP 2.md` (untracked, repo root) line 138 — "Confirm exactly five agents, eleven public
    prompts, fifteen internal skills, three Principle" and line 140 — "Confirm `/` shows the
    eleven prompts once each and their argument hints." — one generation *staler* than the
    counts F-01 fixed (11/15 vs the pre-fix 12/16 and actual 20/22).
  - `SECURITY 2.md` (untracked, repo root) — content duplicate of `SECURITY.md`.
  - Both appear in `git status` as `??`; they look like editor/Finder copy artifacts
    ("<name> 2.md") rather than intentional documents.
- **Proposed action (needs human triage):** confirm they are accidental copies and delete them;
  they were deliberately left untouched by the F-01 fix.
- **Status:** OPEN — awaiting bucketing and approval.

---

## Open questions (batched)

- **OQ-1 — test-strategist skill links.** `.github/agents/test-strategist.agent.md:30-31` says
  "Load only the QA skill selected for the current record" but, unlike the other four agents
  (whose Load lists name their skills — cf. `.ai/repo-map.md:36-40`), links no skill files.
  Is the missing enumeration deliberate progressive loading (six QA skills exist and preloading
  all is wasteful) or an omission that should list the QA skills the way config-investigator lists
  its five? (This is the module-map's one ambiguous E3 edge.)
- **OQ-2 — decisions-log currency.** `.ai/memory/decisions-log.md`'s latest entry is 2026-07-14,
  but git history shows substantial 2026-07-15/16 architecture passes (per-metadata usage registry
  + consumer wiring, `edb024c` relation-claim sweep). Does ORG-DEC-001
  (`organization-principles.instructions.md:26-28`) require log entries for these, or are commit
  messages the accepted record for harness-construction (as opposed to governed-workflow)
  decisions?
- **OQ-3 — output/ git policy is still PROVISIONAL against an archived authority.**
  `.gitignore:15-19` — "PROVISIONAL: blueprint §13 says output/ git policy 'depends on the
  subfolder' and does not resolve which subfolders are committed. … Revisit per §13 — see
  docs/archive/BUILD_REPORT.md flag 24." With the blueprint demoted to historical reference
  (premise 1), which current-authority document now owns this pending decision?

---

## Completion summary

**Findings per bucket:** B1 = 4 (F-01, F-02, F-03, F-04) · B2 = 3 (F-05, F-06, F-07) ·
B3 = 5 (F-08, F-09, F-10, F-11, F-12). Total 12. (+ F-13, unbucketed, appended during fix
execution 2026-07-16.)

**Fix execution 2026-07-16:** FIXED — F-01, F-02, F-03, F-04 (B1, approved), F-06, F-07 (B2,
approved; amendments recorded in `.ai/memory/decisions-log.md` per owner decision). Not
approved / untouched — F-05 (B2, open), F-08–F-12 (B3). New — F-13 (open).

**Findings per class:** M = 8 (F-01, F-02, F-03, F-04, F-08, F-09, F-11, F-12) ·
S = 4 (F-05, F-06, F-07, F-10).

**Checklist C1–C11:**

| Item | Status | Notes / findings |
|---|---|---|
| C1 prompts thin | findings | F-05 (four prompts restate skill procedure; no prompt holds logic absent from its skill). Other 16 prompts verified thin. |
| C2 declared consumers reference the skill | clean | Spot-checked agent Load lists against `.ai/repo-map.md:36-40` and skill files (config-investigator ↔ its 5 skills; solution-designer/guardrail-reviewer ↔ check-against-principles, solution-design); module-map E1 21/21, E2 18/18 confirmed by sampling. |
| C3 skill existence / orphans | clean (F-07 for the extended contract type) | All 22 skills exist and are consumed: 19 via prompts; `curate-knowledge-keywords` ← propose-force-app-knowledge SKILL.md; `fetch-test-case` ← sync-test-cases, tune-test-case-keywords, generate-playwright-test SKILL.md; `update-knowledge-base` ← config-investigator.agent.md + feature-documentor + propose-force-app-knowledge. No dangling skill references. The two empty `agents/` subdirs flagged in unresolved.md are untracked filesystem noise (git ls-files shows nothing) — not modules. Contract-type extension: F-07 (tool-capabilities orphan). |
| C4 file-path contracts | findings | F-02 (three missing `.cache/` skeletons). `.gitignore:8` covers `.cache/**` ✓. All 6 `output/` subdirs exist and map to producers ✓ (the 2 beyond blueprint §5 fold into F-10; §15 anticipated additions). |
| C5 template ↔ skill contract | findings | F-03, F-06. Critical pair verified intact: `generate-technical-documentation/SKILL.md:39` fills the template; the skill's procedure runs `suggest-test-cases` on touched artifacts; `technical-documentation.md` §9 "Suggested Test Cases" documents itself as "Result of the suggest-test-cases skill" with confidence grouping and the explicit-none + /sync-test-cases fallback ✓. |
| C6 knowledge index | findings | F-04 (`feature-map.md` unindexed). No dead entries ✓. |
| C7 frontmatter | findings | F-08 (applyTo — B3, documented). Agents: name/description/tools/handoffs/hooks/target present on all 5 ✓. Skills: name/description (+ user-invocable) on all 22 ✓. Prompts: name/description/agent/tools/argument-hint ✓ (fields beyond blueprint §6 fold into F-10). Slash-menu collision regression: 16 prompt/skill name pairs exist but every skill is `user-invocable: false` (e.g. `search-ado/SKILL.md:4`), so no skill enters the slash menu — the fix has not regressed ✓. |
| C8 placeholders | findings (informational) | F-12 — both §16 exact tokens superseded with documented mechanisms; the four live tokens are validator-registered (`validate_harness.py:56-61`). No silent fills, no silent drops ✓. |
| C9 precedence hierarchy | clean | Stated with consistent semantics at every occurrence: `managed-package-constraints:7` ("These rules override Organization Principles and general Salesforce practice"), `organization-principles:7` ("override general Salesforce practice and are overridden by Tier 1"), `salesforce-best-practices:7` ("apply only when they do not conflict with Tier 1 or Tier 2"), `check-against-principles/SKILL.md:23-24` ("Tier 1 … Tier 2 … Tier 3 in order. Apply precedence only to competing prescriptions"), `guardrail-reviewer.agent.md:40` ("Tier 1 → Tier 2 → Tier 3 order"). No contradictions. Note: `copilot-instructions.md` no longer carries the explicit precedence sentence (kernel redesign, part of F-10); its `:56` preserves the tier order. |
| C10 documentation ↔ built | findings | F-01 (current-authority docs stale — the real defect), F-11 (archive self-contradiction), F-10 (archive drift, consolidated). Generated atlas `.ai/repo-map.md` matches disk exactly ✓. Every diagram in HARNESS_DIAGRAMS.md checked; §1.3/§1.4/§1.5 stale counts are banner-disclaimed (F-10/F-11). |
| C11 parking-lot boundary | findings | F-09 (hooks + mcp.json — B3 per user decision). `org-diff-check` not built ✓; nothing git/deployment-automated ✓. |

**Open questions:** 3 (OQ-1, OQ-2, OQ-3).
