# Setup & Operations

How to install, distribute, and run the brain-core harness. Covers the two layers added after
the initial build: **distribution** (how the shared brain is versioned and kept in sync) and
**activation** (how VS Code + Copilot are pinned to load it). For the architecture itself, see
[`HARNESS_BLUEPRINT.md`](HARNESS_BLUEPRINT.md).

---

## 1. Prerequisites

- **VS Code ≥ 1.108** (recommend a recent stable) with the **GitHub Copilot** + **GitHub Copilot
  Chat** extensions. Version rationale, per VS Code release notes: **custom agent files**
  (`.agent.md`, `chat.agentFilesLocations`) landed ~**v1.106**; **agent skills**
  (`.github/skills`, `chat.agentSkillsLocations`, `chat.useAgentSkills`) landed in **v1.108**
  (opt-in there, default-on in later stable). Skills are the newest dependency, so **1.108 is
  the binding minimum**. If `/`-prompts, agent selection, or skills do not appear, the installed
  version is too old (or skills are disabled) — update / enable before troubleshooting anything
  else.
- Git (for distribution — see §3).
- MCP servers (Salesforce DX, Azure DevOps) and Playwright are **not** configured by this repo
  yet — that is parked (blueprint §15). Skills that call them will not function until MCP is set
  up in a later, dedicated session.

## 2. What this repository is (and is not)

This repo is the **brain** — Principles, Knowledge, Memory, QA index, skills, agents, prompts,
templates. It is **not** the Salesforce metadata / deployment repository. The deployment git
story (intDev has no git; UAT→Prod does; Salesforce DevOps Center) is deliberately parked
(blueprint §15) and untouched here.

## 3. Distribution — versioning the shared brain

`.ai/` is a **shared, committed team resource** (blueprint §13): design notes in the decisions
log, investigation findings in Knowledge, and the synced QA index are only useful if the whole
team sees the same copy. That requires version control — which is why this layer exists.

**Recommended model:** keep this harness as its **own git repository**, separate from any SFDX
project. Each developer clones it and opens it as (or alongside) their VS Code workspace.

```bash
# One-time, by whoever publishes the harness:
#   git init has already been run in this folder (branch: main).
#   Create an empty remote repo, then:
git add -A
git commit -m "Initial brain-core harness"
git remote add origin <your-harness-repo-url>
git push -u origin main

# Each teammate:
git clone <your-harness-repo-url> sf-harness
code sf-harness
```

**Brain repo ≠ metadata repo.** If an SFDX project ever ends up at this same root, `.gitignore`
keeps `force-app/`, `manifest/`, `.sfdx/`, `.sf/` and tooling **out** of the brain repo (skills
still read `manifest/package.xml` at runtime from the working tree — it just is not committed
here). This is a deliberate, documented safety net that preserves the §15 parking; it is not a
decision about how metadata should be versioned elsewhere.

## 4. Sync ritual

Because `.ai/` is shared and persistent, keep it current:

- **Before a work session:** `git pull` — start from the team's latest Knowledge/Memory/QA.
- **After any write to `.ai/knowledge/`, `.ai/memory/decisions-log.md`, or `.ai/qa/`:**
  `git add -A && git commit && git push` — a design note or a finding that stays only on your
  disk is lost to the team (the exact failure the persistent decisions log exists to prevent).
- `.cache/` and generated `output/` content are gitignored by nature (see `.gitignore`), so the
  `git add -A` above will not sweep them in. The `output/` ignore is **provisional** pending the
  per-subfolder git policy left open in blueprint §13 (BUILD_REPORT flag 24).

## 5. Activation — making Copilot load the harness

`.vscode/settings.json` pins Copilot's file discovery so loading does not depend on each
developer's personal settings or version defaults:

- `github.copilot.chat.codeGeneration.useInstructionFiles` → loads `copilot-instructions.md`
- `chat.includeApplyingInstructions` + `chat.instructionsFilesLocations` → load the three
  `applyTo: "**"` Principles files on every request
- `chat.promptFilesLocations`, `chat.agentFilesLocations`, `chat.agentSkillsLocations` → discover
  prompts, agents, and skills
- `chat.useAgentSkills` → the skills enable-gate (opt-in on v1.108-era installs)

**Confirm it loaded:**

1. Type `/` in Copilot Chat — the seven prompts (e.g. `/fetch-ado-item`, `/feature-health`)
   should appear.
2. The five agents should be selectable in the chat agent picker.
3. Ask a plain question and confirm the Principles are being honored (e.g. it should refuse a
   record-triggered Flow "on create" on `Invoice__c`, citing Managed Package Constraints).

If prompts/agents/skills do not appear, re-check the Prerequisites version note in §1 — the
settings keys are version-sensitive (see the `TODO(verify)` in `.vscode/settings.json`).

## 6. First-run checklist

- [ ] `git remote` configured and initial commit pushed (§3).
- [ ] Extensions updated to a version that shows agents + skills (§1).
- [ ] `/`-prompts and agents visible in Copilot Chat (§5).
- [ ] Highest-priority `<TU_WSTAW_...>` placeholders filled — see the prioritized checklist in
      [`BUILD_REPORT.md`](BUILD_REPORT.md) (the release-handover Query ID blocks `/release-handover`;
      the high-risk object list and Invoice condition affect always-active safety).
