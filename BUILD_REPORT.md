# Build Report — original brain-core build (historical)

> Historical status: records the original scaffold before the operational hardening work. Current
> repository and implementation state lives in `IMPLEMENTATION_HANDOFF.md`.

Build completed 2026-07-09 against `HARNESS_BLUEPRINT.md` (binding, R1) with
`HARNESS_DIAGRAMS.md` as companion-only. This report is a build artifact, not part of the
harness — it exists per contract rule R2 (record, don't silently improve).

## Verification results

- **Structural diff vs blueprint section 5**: every specified file exists. Extra files, all
  accounted for: `HARNESS_DIAGRAMS.md` (pre-existing companion), `.ai/qa/test-cases/README.md`
  (authorized addition, see R2-4), `.gitignore` (required by section 17), `.gitkeep` files
  (see R2-10), this report. **None of the R5-excluded items exist**: no `.github/hooks/`, no
  `.vscode/mcp.json`, nothing git/deployment-related beyond the required `.gitignore`, no
  org-diff-check skill. `.cache/` and `output/` are structure only — no fictional content.
- **Cross-reference integrity**: all 12 skill names referenced by prompts/agents/skills match
  existing skill directories exactly; all 10 Knowledge domain files are indexed in
  `.ai/knowledge/README.md`; all 4 templates referenced by skills exist in `.ai/templates/`.
- **Mechanical**: code fences balanced in every generated markdown file; frontmatter present
  and closed on all 3 `.instructions.md`, 5 `.agent.md`, 7 `.prompt.md`, 12 `SKILL.md`; every
  `<TU_WSTAW_...>` occurrence is an intended, commented placeholder (inventory below).
- **`.gitignore` behavior**: verified in a throwaway git repo — `.gitkeep` files remain
  tracked, cached JSON under `.cache/` is ignored.

## R2 flags (inconsistencies / ambiguities / instructed deviations — blueprint followed or deviation logged)

1. **Diagrams show 4 agents, blueprint specifies 5.** `HARNESS_DIAGRAMS.md` sections 1.1 and
   1.3 omit `test-strategist.agent.md` (diagram 2.1 correctly shows five). Blueprint wins (R1):
   five agents built. The diagrams file needs a refresh — not done here (out of scope).
2. **"Same 4 columns" never enumerated.** Blueprint section 13 says the release-handover
   technical table uses "the same 4 columns" as `technical-documentation.md`, but only three
   attributes (type, name, purpose) are ever enumerated. Resolution: both tables built with a
   fourth column `Manual steps reference`, flagged in-file with `TODO(verify)` — needs team
   confirmation of the intended fourth column.
3. **Blueprint's inline section-11 flowcharts lag its own step text.** The `sync-test-cases`
   mermaid omits the orphaned-keywords check (step 5); the `generate-playwright-test` mermaid
   omits the new-quirk-suggestion branch (step 4). Step text governs; both built per text.
4. **`.ai/qa/test-cases/README.md` is not in the section-5 tree.** Added under explicit batch-2
   instruction to document the `<suiteId>-<name>.md` naming convention. Authorized addition.
5. **Invoice__c risk register kept verbatim in Polish** inside
   `managed-package-constraints.instructions.md` — a deliberate R7 tension: the batch
   instruction required the block verbatim with `<TU_WSTAW>` fields intact, and the placeholder
   text must stay greppable against blueprint section 16. Translate the labels later if
   preferred; content-neutral change.
6. **Agent `tools:` values are not prescribed by the blueprint** (section 6 lists the fields,
   section 10 only implies read/write boundaries). Conservative, boundary-shaped tool sets
   supplied (Reviewer: no edit/run tools; Investigator: editFiles scoped to Knowledge writes),
   each with an in-file `TODO(verify)`.
7. **Agent `model:` deliberately omitted** — the blueprint prescribes no per-agent model;
   each frontmatter carries a comment saying so instead of an invented value.
8. **`agents:` whitelists are an encoding interpretation** — section 10's "on demand"
   relationships (Designer↔Investigator, Developer↔Investigator/Strategist) were mapped onto
   the optional `agents` frontmatter field from section 6.
9. **Fail-fast Query-ID check in `generate-release-handover` (step 0)** — an instructed
   extension from the skills batch prompt, not blueprint section 11. Consistent with the
   blueprint's never-guess-the-release-scope decision; logged as an extension.
10. **`.gitkeep` files** — not mentioned in the blueprint; used so empty structural folders
    survive under git, with `.gitignore` rules verified to keep them tracked inside `.cache/`.
11. **This workspace is not currently a git repository**, and the root has no
    `sfdx-project.json` (section 5 labels the root by it). Built at the repo root as
    instructed; the `.gitignore` becomes effective when git is initialized.
12. **`/feature-health` is operated by the Developer before Solution Design** — reads
    counterintuitively (the Designer is the next actor) but the blueprint states it
    consistently in sections 10 and 12; followed as written.
13. **R7 translations of blueprint-Polish field labels**: `Powiązane` → `Related`,
    `pewne/prawdopodobne/do zweryfikowania` → `confirmed/probable/to be verified`, etc., in
    templates and scaffolds (except flag 5 above).
14. **Diagram 1.1 layer map matches the built structure otherwise** — no other blueprint↔
    diagram conflicts encountered during the build.

## R4 — TODO(verify) inventory (12 markers, 5 distinct questions)

| # | Question | Files |
|---|---|---|
| 1 | Does `applyTo: "**"` in a separate `.instructions.md` behave identically to inlining into `copilot-instructions.md` in every context? (Plan B: merge the three Principles files in as sections.) | `.github/copilot-instructions.md` |
| 2 | Exact interactive-question tool name: `vscode/askQuestion` vs `vscode/askQuestions` | `.github/skills/generate-technical-documentation/SKILL.md`, `.ai/templates/technical-documentation.md` |
| 3 | Exact ADO MCP `test-plans` domain tool names (and Salesforce DX MCP toolsets; VS Code agent tool identifiers) | `.github/skills/fetch-test-case/SKILL.md`, `.github/skills/sync-test-cases/SKILL.md`, all five `.github/agents/*.agent.md` |
| 4 | Exact `@playwright/cli` invocation syntax | `.github/skills/generate-playwright-test/SKILL.md` |
| 5 | Intended fourth column of the artifact table (see R2-2) | `.ai/templates/technical-documentation.md` |

## Prioritized placeholder checklist (`<TU_WSTAW_...>`)

Ordered: harness-blocking first, cosmetic last. Each line: placeholder — file(s) — what
breaks/degrades while empty.

**Blocking (a whole prompt cannot run):**

1. `<TU_WSTAW_QUERY_ID>` — `.github/skills/generate-release-handover/SKILL.md`,
   `.github/prompts/release-handover.prompt.md`, `.ai/templates/release-handover.md` —
   `/release-handover` fails fast by design: without the saved ADO Query ID there is no way to
   determine the release scope.

**High (always-active safety rules are incomplete):**

2. `<TU_WSTAW_PELNA_LISTA_OBIEKTOW_WYSOKIEGO_RYZYKA>` —
   `.github/instructions/managed-package-constraints.instructions.md` — no always-active
   warning exists for any high-risk package object other than Invoice__c; conflicts surface
   only after the damage or via ad-hoc discovery.
3. `<TU_WSTAW>` (Invoice on-update Flow condition) — same file — any proposed on-update Flow
   on Invoice__c must be escalated instead of approved, since the safe-condition is unknown.
4. `<TU_WSTAW: dokumentacja vendora / ustalone doswiadczalnie / wsparcie vendora>` (rule
   source) — same file — the Invoice rule cannot be re-verified after a package upgrade;
   upgrades may silently invalidate it.

**Medium (a phase or agent degrades):**

5. `<TU_WSTAW_ZASADY_PRACY_NA_WSPOLDZIELONYM_SANDBOXIE>` —
   `.github/instructions/organization-principles.instructions.md` — agent-run controlled
   sandbox tests (investigate-object step 3) proceed with no coordination protocol against
   two-developer collisions.
6. `<TU_WSTAW_DECYZJA_ZAPIS_DO_ADO>` — `.github/agents/guardrail-reviewer.agent.md` — the
   Reviewer treats ADO as read-only and hands notes to a human for manual publication (safe
   default; costs one manual paste per review).
7. `<TU_WSTAW_ZASADY_CODE_REVIEW>` — `organization-principles.instructions.md` —
   company-specific review criteria are not enforced; only generic best practices and package
   constraints are checked.
8. `<TU_WSTAW_KONWENCJE_NAZEWNICZE_FIRMY>` — `organization-principles.instructions.md` —
   generated metadata may not match company conventions and needs manual renaming in review.

**Low (cosmetic / deferred decisions):**

9. `<TU_WSTAW_FORMAT_DOKUMENTOWANIA_DECYZJI>` — `organization-principles.instructions.md` —
   agents default to the existing decisions-log format; entries may need reformatting if the
   company expects a different one.
10. `<TU_WSTAW_DOCELOWY_KATALOG_TESTS>` — `.github/skills/generate-playwright-test/SKILL.md` —
    reviewed Playwright scripts have no documented promotion destination and accumulate in
    `output/generated-tests/`.

## Post-audit extension — distribution + activation layers (2026-07-09)

Implemented at explicit user request (findings 1 and 2 from the missing-layer brainstorm). This
is an authorized scope extension beyond the blueprint: the user directive lifts the §15/R5 git
exclusion **for the brain-versioning scope only**. The parked *deployment* git topic (intDev/
UAT→Prod, DevOps Center, metadata versioning) is untouched — and the new `.gitignore` rules
actively protect that parking.

**Files added/changed:**

- `git init -b main` — the repository now exists (branch `main`). **No commit was made** — per
  standing guidance commits happen only when the user asks; the initial commit is teed up in
  `SETUP.md` §3 for the user to run.
- `.gitignore` — expanded from cache/DS_Store to also keep Salesforce metadata & tooling
  (`force-app/`, `manifest/`, `.sfdx/`, `.sf/`, `.localdevserver/`, `node_modules/`, `*.log`)
  out of the brain repo. Verified via `git check-ignore`: cache JSON + all metadata paths
  ignored; `.gitkeep`, `.ai/`, `.vscode/settings.json` tracked.
- `.vscode/settings.json` — activation layer. Pins the six Copilot file-discovery keys
  (verified against the current VS Code AI-settings reference). NOT the excluded `mcp.json`.
- `README.md`, `SETUP.md` — distribution model, sync ritual, activation, first-run checklist.

**New R2 flags:**

23. **`.gitignore` ignores `force-app/` and `manifest/` — a documented safety net, not a
    metadata-versioning decision.** Risk: if a developer deliberately colocates their SFDX
    project at this root expecting it tracked, this silently drops metadata from commits.
    Mitigated by loud documentation in `.gitignore` and `SETUP.md` §2–3, and the recommended
    model (harness = its own repo). **Flagged for Fable review** as the highest-judgment call
    in this extension.
24. **`output/` per-subfolder git policy left undecided.** Blueprint §13 says output git
    tracking "depends on the subfolder" but never resolves which subfolders are committed vs
    ignored (e.g. `generated-tests/` is unverified content; `handover/` may be shareable).
    Not decided here — `output/` stays tracked-as-structure as originally built. Surfaced by
    finding 1, left open on purpose (R2: no silent decision).
25. **No initial commit made.** Deliberate (commit-only-when-asked). Consequence: the repo has
    no history yet; Fable reviews the working tree.

**New TODO(verify) (2, folded into the table below via files):**

- Exact minimum VS Code + GitHub Copilot versions supporting agent + skill files — `SETUP.md` §1.
- Stability of `chat.agentFilesLocations` / `chat.agentSkillsLocations` across versions —
  `.vscode/settings.json`.

**New placeholder:** none emitted (no §16 data was needed by this extension).

### Independent Fable review + resolutions (2026-07-10)

An independent reviewer (Fable, fresh context, verify-don't-trust) reviewed this extension via
`HANDOFF_FOR_FABLE.md`. Verdict: **accept with minor changes**; all handoff claims verified true,
§15 parking confirmed intact. Five required changes raised — all applied and re-verified:

1. **`output/` sync-ritual contradiction (blocking) — FIXED.** SETUP §4's `git add -A` ritual
   would have silently committed generated artifacts, despite the text saying not to.
   Resolution: `output/**` content now gitignored (structure kept via `.gitkeep`, same pattern
   as `.cache/`), **provisional** pending the §13 per-subfolder decision (flag 24). SETUP §4
   updated to match.
2. **`chat.useAgentSkills` missing — FIXED.** Independently confirmed against the VS Code 1.108
   release notes (the key was not in the current Agent Skills doc; it is the 1.108-era opt-in
   enable-gate). Added to `.vscode/settings.json`.
3. **Version pins resolved — FIXED.** Agents ~v1.106, skills v1.108 (default-on later stable);
   binding minimum VS Code ≥ 1.108. Written into `SETUP.md` §1 and the settings.json version
   note; the prior `TODO(verify)` is retired.
4. **Root-anchored the Salesforce ignore entries — FIXED.** `/force-app/`, `/manifest/`,
   `/.sfdx/`, `/.sf/`, `/.localdevserver/` (leading `/`) so a legitimately-named nested folder
   is never caught. Verified: root `manifest/` ignored, `.ai/knowledge/manifest/` not.
5. **`HANDOFF_FOR_FABLE.md` fate — DECIDED.** Kept tracked as review provenance (small, documents
   a real review, sits alongside this report); this section is its durable record.

Re-verification after fixes: `git add -A --dry-run` → 62 paths, brain + structure only, no
metadata/`.DS_Store` leak; `output/**` content ignored, `.gitkeep` tracked; settings.json valid
JSONC with all 7 keys. Fable's accepted-as-is items: no-initial-commit (correct under
commit-only-when-asked) and the `force-app`/`manifest` safety-net approach (correct;
root-anchoring tweak applied).

---

## Architect audit addendum (post-build coverage & hallucination check, 2026-07-09)

A full content-level audit of every generated file against its blueprint section found **no
coverage gaps** and **no unflagged hallucinations**, but surfaced these additional minor R2
flags (unspecified additions — all consistent with the blueprint's ethos, none silently made):

15. **`knowledge-entry.md` "Keywords" field** — required by sections 3 and 11 (optional
    keywords on object entries) but absent from section 13's template block. Blueprint-internal
    inconsistency, resolved in favor of the explicit section-3/11 decisions.
16. **`release-handover.md` template header carries a "Source query" line** — not in section
    13's header spec (period + date only). Added to make the blocking `<TU_WSTAW_QUERY_ID>`
    visible at point of use.
17. **`tune-test-case-keywords` cache-miss behavior** ("not cached → point the human at
    /sync-test-cases") — unspecified in section 11; added rather than leaving the miss case
    undefined.
18. **`update-knowledge-base` "no existing file fits → propose + confirm with human"** —
    section 11 covers routing to existing files only; extension follows the ask-don't-guess
    habit.
19. **`salesforce-best-practices` two elaborations** beyond section 7's enumerated list
    ("batch of 200" phrasing; "assert behavior, not just coverage") — standard industry
    content, in-scope for the file's declared source, but not blueprint-enumerated.
20. **`copilot-instructions.md` "Reference layers" section** — beyond the strict "TOC +
    precedence" spec; a navigational pointer mirroring the section-4 layer map.
21. **`fetch-ado-item.prompt.md` optional pass-throughs** (`childDetail=`,
    `includeTestCases=`) — section 12 lists only `itemId`/`mode`; pass-throughs mirror the
    skill's parameters.
22. **Prompt frontmatter omits `tools`** — section 6 lists it as an available field; omitted
    deliberately since prompts are thin and the skills carry the logic.

**Contained hallucination-risk area (highest-priority verification item):** the agent
`tools:` arrays (`search`, `codebase`, `editFiles`, `runCommands`, `fetch`) are
plausible-but-unverified VS Code tool identifiers not sourced from the blueprint. Every
instance carries an in-file `TODO(verify)`. If a name is wrong, VS Code may ignore it or the
agent may load without the intended tool. Verify against current VS Code custom-agent docs
before first use — or delete the `tools:` lines to inherit defaults.

**Verified clean (checked against the blueprint, could have been hallucinated but were not)**:
extension IDs (`yzane.markdown-pdf`, vscode-pandoc), `@playwright/cli`-primary /
`@playwright/mcp`-fallback rationale, `X-MCP-Readonly` header note, `${input:...}` syntax,
wiki-page native link type, precedence chain, both Test Case relation sources + dedup,
one-level-down hierarchy rule, BRD full-content exception, `_fetchedAt` cache convention,
"Tested based on acceptance criteria" fallback, 15–20-object split threshold, all
defense-in-depth rules (no prod MCP entry, dev/QA-only browser profile, no credentials
through the agent).

**Section-16 placeholders NOT emitted into any harness file** (no generated file needed them;
they become relevant only with the parked `mcp.json` work): `<TU_WSTAW_NAMESPACE_PAKIETU>`,
the `sf` CLI aliases, the ADO organization/project names, and the final choice of the
markdown→DOCX/PDF extension (default Markdown PDF documented in prompt/skill text).
