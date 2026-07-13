# Handoff for Fable — Audit Fix Verification

> Historical status (archived 2026-07-14): this handoff described a working tree whose changes
> have since been committed and pushed. Its "nothing was committed", untracked
> force-app-knowledge, and test/check counts no longer describe the repository; use the current
> CI run and `IMPLEMENTATION_HANDOFF.md` instead. The deferred items D1–D3 (live VS Code
> hook/sandbox/tool verification) remain genuinely open pilot gates.

**Branch:** `agent/hallucination-grounding-upgrade`
**Date applied:** 2026-07-13
**Context:** A three-part workspace audit (Copilot mapping, harness/orchestration gaps, reusability)
produced findings; this document lists exactly what was changed so a Fable checker can verify each
fix and adjudicate the items that were deliberately *deferred* (they need a live VS Code build or a
maintainer decision this session could not make).

All changes are working-tree edits only. **Nothing was committed or pushed.** The force-app-knowledge
feature that was already untracked before this session is still untracked (see Deferred D5).

---

## How to verify quickly

```bash
.venv/bin/python -m unittest discover -s tests -q      # expect: Ran 145 tests ... OK
.venv/bin/python scripts/validate_harness.py            # expect: PASS (2292 checks)
.venv/bin/python scripts/run_evals.py                   # expect: PASS 28 evals (with OR without config/harness.local.json)
node --check scripts/start_salesforce_mcp.mjs && node --check scripts/salesforce_review_server.mjs
```

All four passed at handoff time. 5 tests were added (140 → 145).

---

## APPLIED — verify these

### A1. `rm -fr` / `rm -f -r` destructive-command bypass (was: major G1)
- **File:** `scripts/copilot_safety_hook.py` (`DESTRUCTIVE_PATTERNS`, first entry).
- **Change:** replaced the order-dependent regex `rm\s+-[^\n]*r[^\n]*f` with a two-lookahead pattern
  matching a recursive flag (`-…r` / `--recursive`) and a force flag (`-…f` / `--force`) in any order.
- **Verify:** `rm -rf`, `rm -fr`, `rm -f -r`, `rm --recursive --force` all deny; `rm -i somefile` still
  allowed. Regression test: `tests/test_safety_hooks.py::test_recursive_force_rm_is_denied_regardless_of_flag_order`.
- **Check for:** false positives on benign commands containing both an `-r*` and `-f*` flag on one line
  (over-blocking is the safe direction, but confirm it doesn't break a legit allowlisted command).

### A2. `s''f` quote-splicing bypass of the direct-`sf` block (was: major G3)
- **File:** `scripts/copilot_safety_hook.py::direct_sf_command`.
- **Change:** the `\bsf\b` prefilter now also runs against a de-quoted copy of the command, so shell
  quote splices (`s''f`, `s""f`) that collapse to `sf` at exec time are caught. The metacharacter
  fail-closed gate still runs against the original string.
- **Verify:** `s''f project deploy start …` and `s""f org delete …` deny. Test:
  `test_quote_spliced_salesforce_command_is_denied`. Confirm the existing `bash -c 'sf …'` wrapped-command
  test still denies (it does).
- **Check for:** any legitimate command that contains adjacent quotes collapsing to `sf` as a substring
  and would now be mis-parsed — I judged this negligible; confirm.

### A3. `-m work_record approve` bypass + in-script approval guard (was: major G2)
- **Files:** `scripts/copilot_safety_hook.py` (`WORK_RECORD_MODULE` regex now matches `-m work_record`
  as well as `-m scripts.work_record`); `scripts/work_record.py` (new `_assert_not_agent_context()`
  called first in `command_approve`).
- **Change rationale:** the role guard already denies `approve` to all 5 agents; the gap was the global
  hook protecting the *default* Copilot. The regex is tightened, AND — per the audit's recommendation to
  move enforcement into the script itself — `command_approve` now refuses if `SF_HARNESS_AGENT_CONTEXT`
  is set to any non-empty value.
- **Verify:** `PYTHONPATH=scripts python3 -m work_record approve …` denies at the hook. Tests:
  `test_work_record_approval_module_form_is_denied`, and `ApprovalContextGuardTests` in `tests/test_work_record.py`.
- **⚠ IMPORTANT — this guard is dormant until wired.** Nothing currently sets `SF_HARNESS_AGENT_CONTEXT`.
  For it to actually enforce, the agent runner / hook layer must export it for agent-invoked terminals.
  **Decision for the maintainer:** either (a) wire that env var, or (b) adopt the stronger inverse —
  require a positive out-of-band human token to *permit* approval (this changes the documented human
  workflow + tests, so I did not impose it). Renamed/copied-script invocation of `approve` still cannot
  be caught by string matching alone; the env-marker guard is the only mechanism that survives a rename.

### A4. Non-deterministic ADO safety eval (was: minor G4)
- **File:** `evals/safety-scenarios.yaml`, scenario `ado-call-without-runtime-policy-denied`.
- **Root cause (corrected from audit):** the audit suggested `workingDirectory: temporary`, but the hook
  loads config from `HARNESS_ROOT` (its own repo path), *not* the event `cwd` — so a temp dir would not
  change config presence. Instead I changed `reasonContains` from `local harness configuration is missing`
  to `ADO read blocked`, the common prefix of *both* deny branches (missing config, and org/project
  mismatch when config is present).
- **Verify:** `run_evals.py` passes both with `config/harness.local.json` present and moved aside
  (confirmed at handoff). This was the 1/28 that failed on a configured dev machine.

### A5. No LICENSE (was: blocker B1-reuse)
- **Files:** added `LICENSE` (MIT); added `"license": "MIT"` to `package.json`.
- **⚠ DECISION NEEDED:** I chose **MIT** as the conventional default for shareable dev tooling and used a
  neutral copyright line (`2026 sf-harness-brain-core contributors`). Confirm MIT is the intended license
  (the audit noted MIT/Apache-2.0/BSL as candidates) and set the correct copyright holder.

### A6. Stray `config/harness.json` (was: major M1/G5)
- **Changes:** deleted the empty untracked file; added `config/harness.json` to `.gitignore`; added it to
  the CI `git check-ignore` canary line in `harness-ci.yml`.
- **Verify:** `git check-ignore config/harness.json` returns the path; validator still passes.

### A7. Personal identity sweep (was: major M2/M3 + minors)
- **`.github/CODEOWNERS`:** all `@Vescik` → `@your-org/harness-maintainers` (placeholder). Validator only
  checks the owned *paths*, not owner names — still passes.
- **`SETUP.md`:** clone URL → `git clone <your-fork-url> sf-harness-brain-core`.
- **`schemas/*.json` (18 files):** `$id` host `https://github.com/Vescik/sf-harness-brain-core/schemas/…`
  → `urn:sf-harness-brain-core:…`. Confirmed no schema `$ref` dereferences these, so URN is safe.
- **`IMPLEMENTATION_HANDOFF.md`:** `/Users/dmachowski/…` paths, `Vescik/…` repo URLs, PR #1 link, and the
  `account Vescik` line → neutral placeholders (`<your-fork-url>`, `<workspace-root>`).
- **Verify:** `grep -rn "Vescik\|/Users/dmachowski" --include='*.md' --include='*.json' .` (excluding this
  handoff and node_modules/.git) should return nothing in tracked source. Note: `BUILD_REPORT.md` /
  `HANDOFF_FOR_FABLE.md` may still carry historical references — see D4.

### A8. CI Node pinning + editor recommendations (was: minors m3, M-copilot)
- **`.github/workflows/harness-ci.yml`:** added an `actions/setup-node@…v4.0.2` step (`node-version-file: .nvmrc`)
  before `npm ci`. **⚠ VERIFY THE SHA:** I used `60edb5dd545a775178f52524783378180af0d1f8` (setup-node v4.0.2)
  from memory and could not network-verify it. Confirm it resolves to the real tag, or re-pin.
- **`.nvmrc`:** added, contents `20` (matches `engines.node >=20`).
- **`.vscode/extensions.json`:** added `github.copilot-chat` and `ms-python.python`.
- **Verify:** validator's CI-SHA-pin check (40-hex) still passes; confirm the SHA on GitHub.

### A9. Enforcement/preview-feature honesty note (partial mitigation of B1/B2-copilot)
- **File:** `SETUP.md` — added a blockquote after the compatibility link warning that the hooks
  (`chat.hookFilesLocations`, `chat.useCustomAgentHooks`, `.github/hooks/`) and the `mcp.json`
  `sandbox`/`sandboxEnabled` keys are recent/preview surfaces that are silently ignored where a build
  doesn't implement them, reducing the harness to prompt-level guidance; instructs the operator to verify
  in their exact build. This is documentation only — see D1/D2 for why the config itself was not gutted.

---

## DEFERRED — need a live VS Code build or a maintainer decision

These are the audit's highest-uncertainty items. I did **not** change the machinery because doing so
blindly could break a working VS Code Insiders setup, and I cannot verify against a live editor here.

### D1. (BLOCKER, copilot) Are `.github/hooks/` + `chat.hookFilesLocations` + `chat.useCustomAgentHooks` real?
The hook schema (`PreToolUse`, `type: command`, `timeout`) is identical to Claude Code's format. If VS
Code/Copilot does not implement workspace/agent hooks, **none of the guard scripts ever run** and the
harness's core safety claim is prompt-level only. **Action for checker:** open the target VS Code version,
confirm in Settings UI whether these keys resolve and whether `PreToolUse` hooks fire. If unsupported:
move enforcement into `start_salesforce_mcp.mjs` / `salesforce_review_server.mjs`, and remove the
`validate_harness.py` assertions that currently *require* the invented keys (institutionalizing the fiction).

### D2. (BLOCKER, copilot) Are `mcp.json` `sandbox` / `sandboxEnabled` real keys?
VS Code's documented `mcp.json` supports only `inputs`/`servers`. If `sandbox`/`sandboxEnabled` are
ignored, the filesystem deny-lists and network allowlist are non-enforcing. Same remediation path: enforce
inside the MCP wrapper scripts, and update `validate_harness.py:427-460`.

### D3. (MAJOR, copilot) Unverified setting keys, tool identifiers, and the ADO MCP endpoint
- `chat.includeApplyingInstructions`, `chat.includeReferencedInstructions`,
  `chat.useCustomizationsInParentRepositories` — confirm each resolves; remove no-ops.
- Tool ids in agent/prompt `tools:` (`execute/runInTerminal`, `web/fetch`, `vscode/askQuestions`, bare
  `read`) — copy exact names from the Chat tool picker; `validate_harness.py` only checks them against its
  own list, not the editor.
- `.vscode/mcp.json` ADO server `https://mcp.dev.azure.com/${env:ADO_ORGANIZATION}` + `X-MCP-*` headers —
  confirm the hosted endpoint exists, else switch to the official stdio server (`npx @azure-devops/mcp`).

### D4. (MAJOR, reuse) Internal history docs ship publicly
`HARNESS_BLUEPRINT.md` (92 KB), `HARNESS_DIAGRAMS.md`, `HANDOFF_FOR_FABLE.md`, `BUILD_REPORT.md` are tracked
(git stores 100644 regardless of the local 600 perms). No secrets, but ~125 KB of superseded internal
narrative. **Decision:** move to `docs/history/` or drop from the public tree. Left in place this session.

### D5. (BLOCKER, reuse) Uncommitted force-app-knowledge feature
18 modified + 12 untracked files (scripts/schemas/prompts/2 skills/docs/validator changes) implement a
feature the *working-tree* README/SETUP already describe ("10 prompts, 14 skills"), but HEAD has 7/12.
**Commit the whole set atomically** before sharing, or the pushed repo's docs describe a system it doesn't
contain. (This session's fixes touch some of those same files — e.g. `validate_harness.py` is already
modified — so stage them together.)

### D6. (MAJOR, copilot) Instruction files have no `applyTo`
By design (the validator asserts `applyTo` is absent; rules load via Markdown links from agent bodies).
Risk: link-following is not a guaranteed context-inclusion mechanism. **Recommendation:** make the "Load …"
lines an imperative first step in each `.agent.md`, or add `applyTo` globs + adjust the validator. Not
changed this session because it contradicts an assertion the validator enforces — a maintainer call.

---

## Files changed this session
```
LICENSE                                   (new)
.nvmrc                                    (new)
HANDOFF_FOR_FABLE_CHECKER.md              (new, this file)
.gitignore
.github/CODEOWNERS
.github/workflows/harness-ci.yml
.vscode/extensions.json
package.json
SETUP.md
IMPLEMENTATION_HANDOFF.md
schemas/*.json                            (18 files: $id host only)
scripts/copilot_safety_hook.py
scripts/work_record.py
evals/safety-scenarios.yaml
tests/test_safety_hooks.py                (+3 tests)
tests/test_work_record.py                 (+2 tests)
config/harness.json                       (deleted)
```
