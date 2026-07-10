# Handoff for Fable — review of distribution + activation layers

**Reviewer:** Fable · **Author:** Opus 4.8 · **Date:** 2026-07-09
**Scope of this review:** ONLY the two layers just implemented (findings 1 + 2). The rest of the
harness was built and audited earlier — see `BUILD_REPORT.md` for that history; no need to
re-review it unless a change below affects it.

---

## 1. What you're reviewing and why

The user asked to implement two gaps found in a missing-layer brainstorm:

1. **Distribution layer** — the harness declares `.ai/` a "shared, committed team resource"
   (blueprint §13), but the workspace had no git and dev environments (intDev) lack it. Without
   version control the shared brain lives on one laptop.
2. **Activation layer** — nothing pinned how VS Code/Copilot discover the harness files, so
   loading depended on each developer's settings and version.

**Critical constraint to check me against:** blueprint §15 / rule R5 park all *deployment* git
(intDev, UAT→Prod, Salesforce DevOps Center, metadata versioning). The user's request lifts that
exclusion **only for versioning the brain**. Verify I did not stray into the parked topic.

## 2. Exactly what changed

| Change | File(s) | Note |
|---|---|---|
| Initialized repo (branch `main`), **no commit** | `.git/` | Initial commit left for the user (`SETUP.md` §3) |
| Expanded gitignore + metadata safety net | `.gitignore` | Ignores `force-app/`, `manifest/`, `.sfdx/`, `.sf/`, `.localdevserver/`, `node_modules/`, `*.log`, `.cache/**`, `.DS_Store` |
| Activation config | `.vscode/settings.json` | 6 Copilot discovery keys, verified against VS Code docs |
| Orientation + ops docs | `README.md`, `SETUP.md` | Distribution model, sync ritual, first-run checklist |
| Logged the extension | `BUILD_REPORT.md` (new "Post-audit extension" section, flags 23–25) | R2 discipline |

Nothing in `.github/` or `.ai/` content was modified. No `.vscode/mcp.json`, no `.github/hooks/`,
no deployment/pipeline anything.

## 3. Verification already done (please spot-check, don't assume)

- `git check-ignore` confirms: `.cache/*.json`, `force-app/...`, `manifest/package.xml`,
  `.sfdx/`, `node_modules/` → ignored; `.ai/memory/decisions-log.md`, `.cache/.gitkeep`,
  `.vscode/settings.json` → tracked.
- `git add -A --dry-run` shows only brain files + structure `.gitkeep`s staged; `.DS_Store`
  excluded.
- Settings keys verified against the official VS Code AI-settings reference (not from memory):
  `github.copilot.chat.codeGeneration.useInstructionFiles`, `chat.includeApplyingInstructions`,
  `chat.instructionsFilesLocations`, `chat.promptFilesLocations`, `chat.agentFilesLocations`,
  `chat.agentSkillsLocations`.

## 4. Please focus your review here (highest-judgment calls)

1. **`.gitignore` ignoring `force-app/` + `manifest/` (BUILD_REPORT flag 23).** This is the one
   real design decision. Rationale: protect the §15 parking by preventing metadata from leaking
   into the brain repo if an SFDX project colocates. Risk: silently drops metadata for anyone who
   *intends* a combined repo. Is the safety-net-plus-loud-docs approach right, or should the
   entries be removed in favor of docs-only (relying on the "separate repo" model and accepting
   the accidental-`git add -A` risk)? I chose protection over purity; challenge it.
2. **No initial commit (flag 25).** I followed "commit only when the user asks." Acceptable for a
   handoff, or should the brain have a baseline commit so history starts clean? Your call to
   recommend.
3. **`output/` git policy still open (flag 24).** Blueprint §13 says "depends on subfolder" but
   never resolves it. I left `output/` tracked-as-structure and did NOT decide. Confirm that
   punting is correct, or propose the per-subfolder split (e.g. ignore `generated-tests/`,
   keep `handover/`).
4. **Activation framing honesty.** Current VS Code defaults already point at `.github/*` and
   default the instruction toggles to `true`, so the harness would largely load without this
   file. I framed the value as *deterministic pinning across versions/users*, not "turning on
   what's off." Confirm that framing is accurate and not overselling.
5. **Version sensitivity (2 open TODO(verify)).** `chat.agentFilesLocations` /
   `chat.agentSkillsLocations` are the newest keys; exact minimum VS Code/Copilot versions are
   unverified (`SETUP.md` §1). Flag if you can pin them.

## 5. What I deliberately did NOT do

- No commit / no remote / no push (user hasn't asked; teed up in `SETUP.md`).
- No `.vscode/mcp.json`, no hooks, no deployment/pipeline config (§15 parked).
- Did not fix the known-stale `HARNESS_DIAGRAMS.md` (still shows 4 agents) — pre-existing,
  tracked in the audit addendum, out of this scope.
- Did not fill any `<TU_WSTAW_...>` placeholder — those need the human/team.

## 6. Suggested review method

1. Read `BUILD_REPORT.md` → "Post-audit extension" section (flags 23–25) for the decisions.
2. Diff the five changed files against the intent in §2 above.
3. Re-run the two verification commands in §3 to confirm, don't trust.
4. Return a verdict per focus item in §4: **accept / change / needs discussion**, with the
   `force-app` gitignore call (item 1) as the one that most needs a second opinion.
