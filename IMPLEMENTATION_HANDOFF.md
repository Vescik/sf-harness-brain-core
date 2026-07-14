# Implementation Handoff — Copilot Brain-Core Enhancement

> Current topology (2026-07-10): the repository root is the only named `brain-core` workspace
> folder and the only SFDX project root. Root `sfdx-project.json`, `force-app/`, `manifest/`, and
> `tests/e2e/` are authoritative. Earlier two-folder or nested-`salesforce/` descriptions in this
> iteration history are superseded.

## Iteration 7 — Knowledge upgrade: total coverage and chat-approved promotion (2026-07-14)

### Changes

- Fixed the observed live failure where inventory + draft on an approval process produced
  nothing: `force_app_knowledge.py` now parses approval processes into automation-inventory
  candidates and every other source-format metadata file into a generic candidate in the new
  `component-inventory` domain (claim/evidence/policy schemas, policy config, registry domain
  views, generated index, and knowledge README extended). A recognized source file can no longer
  draft nothing.
- Added `knowledge_registry.py approve-claim`: one guarded command that builds the immutable
  review record itself (all binding digests computed), records it, promotes on `verify` (or
  binds a rejection), and re-renders the domain indexes. The safety hook answers `ask` for every
  invocation — the human's chat confirmation click is the approval — and the registry records
  the human named in `knowledge.chatReviewer` (new local-config key) with the new
  `copilot-chat-confirmation` review mechanism. Role guard allows the request for
  Config Investigator only; file-based `review`/`promote` and work-record approval remain
  human-terminal-only. SAFE-HUMAN-001, the knowledge lifecycle contract, the investigator agent,
  the propose skill, and SETUP §7 describe the new loop.

- AI description layer (same owner directive): behavior-bearing components additionally draft
  `component-description` claims with an `<AGENT_...>` sentinel the agent must replace with a
  source-grounded description of what the component does; the registry rejects unfilled
  sentinels, the claims carry `assurance: inferred` (schema carve-out allows verified+inferred
  for this claim type only), expire after 180 days, and become verified only through the human
  chat approval.

### Validation — 2026-07-14

- Harness validation: PASS — 2,414 checks. Unit suite: PASS — 192 tests. Safety evaluations:
  PASS — 31 scenarios.

## Iteration 6 — Read-only MCP model; human-approved CLI retrieve (2026-07-14)

### Changes

- Removed the `salesforce-development` MCP server, its `sf_dev_org` input, and the OS-level
  `sandbox`/`sandboxEnabled` keys from `.vscode/mcp.json` (owner decision — see the 2026-07-14
  decisions-log entry). The configured MCP surface is read-only by construction; the recurring
  Windows `exit code 2` startup error is gone.
- Widened the guarded `scripts/salesforce_read.py` read flow (structured records + cached
  metadata retrieve) to Solution Designer and Development Assistant, and wired the
  principles → knowledge → org-context sequence into the designer/developer agent bodies and the
  solution-design skill.
- Carved out `sf project retrieve start --target-org <configured-alias>` as the only raw
  Salesforce CLI agents may request: the global safety hook validates the alias against local
  configuration and answers `ask` (SAFE-HUMAN-001) so every retrieve needs human confirmation;
  the role guard permits the command for Development Assistant only. Deploys and all other raw
  CLI remain denied.
- Updated validator contracts (two read-only servers; a write server or sandbox keys reappearing
  now fails validation), tests (183), and safety evaluations (30).

### Validation — 2026-07-14

- Harness validation: PASS. Python unit suite: PASS — 183 tests. Safety evaluations: PASS — 30.

## Iteration 5 — Windows-first onboarding and shareability hardening (2026-07-14)

### Changes

- Replaced `first-launch.ps1` with cross-platform `scripts/first_launch.py` (same guided flow:
  prerequisite checks, pinned installs, config creation, ADO collection, sandbox authorization
  with host/`IsSandbox` proof, verification gates). Plain Python avoids PowerShell
  execution-policy blocks on managed Windows machines; a fresh `.venv` now requires
  Python 3.11+.
- Added `docs/setup-zero-to-first-prompt.md`: a zero-assumptions manual walkthrough (Windows
  primary, macOS/Linux inline) from tool installation to the first Copilot prompt, including the
  `ADO_ORGANIZATION` env var, interpreter selection, and the review-only Windows scope.
- Archived the historical design documents (`HARNESS_BLUEPRINT.md` — Polish, `BUILD_REPORT.md`,
  `HARNESS_DIAGRAMS.md`, both `HANDOFF_FOR_FABLE*.md`) into `docs/archive/` with an index and
  status banners; root-level docs are now the only operating surface.
- Fixed documentation count drift: five agents, eleven public prompts, fifteen internal skills
  everywhere (README, SETUP §5, compatibility contract).
- Enforced the manifest rule: `preflight --capability salesforce-write` now fails while the
  configured manifest contains any wildcard `<members>*</members>` entry (3 new unit tests).
- Investigated and recorded the npm-audit posture: all 24 findings are transitive to
  vendor-pinned Salesforce tooling; `@salesforce/mcp@0.30.15` is the latest stable, the
  `sfdx-lwc-jest` fix is prerelease-only, and a full in-range update was tested and rejected
  (worsened to 37 findings / 9 high). Risk acceptance recorded in `.ai/memory/decisions-log.md`,
  `SECURITY.md`, and `docs/compatibility.md`.

### Validation — 2026-07-14

- Harness validation: PASS — 2,416 checks.
- Python unit suite: PASS — 178 tests.
- Deterministic safety evaluations: PASS — 28 scenarios.
- Prettier, ESLint, and LWC unit gates: PASS (LWC still `--passWithNoTests`).

## Current flat-root validation — 2026-07-10

- Harness validation: PASS — 1,536 checks.
- Python unit suite: PASS — 125 tests.
- Deterministic safety evaluations: PASS — 28 scenarios.
- Salesforce Prettier and ESLint gates: PASS.
- LWC unit gate: PASS with `--passWithNoTests`; this proves the runner works, not test coverage.
- Root `npm ci --ignore-scripts`: PASS. `npm audit` still reports 24 transitive findings
  (6 low, 17 moderate, 1 high); no automatic or breaking dependency fix was applied.

## Status

- Repository: `<your-fork-url>`
- Visibility: private
- Baseline branch: `main`
- Prior enhancement branch: `agent/enhance-copilot-harness`
- Active grounding/topology branch: `agent/hallucination-grounding-upgrade`
- Baseline commit: `66649b6` (`Baseline brain-core harness`)
- Working copy: `<workspace-root>` (the cloned repository root)
- Protected source: a separate legacy workspace outside this repository — never edited by this implementation
- Prior enhancement draft pull request: `<your-fork-url>/pull/1`
- Publication state: verify the active branch and CI live in Git/GitHub; this handoff does not use
  a stale prose assertion as repository authority.
- Overall state: grounding and flat-root implementation is locally green for a controlled pilot;
  live Copilot/MCP/model evidence, real configuration/Knowledge, dependency risk acceptance, and
  authenticated approvals remain rollout gates.

## Goal

Preserve the functional essence of the Salesforce managed-package brain-core while making its
GitHub Copilot instructions, agents, handoffs, prompts, skills, workspace integration, safety
controls, validation, and team operating model reliable enough for a controlled developer pilot.

## Operating loop

Every iteration follows:

1. Discover the current behavior and constraints.
2. Plan the smallest coherent improvement wave.
3. Execute only in the isolated clone.
4. Verify structure, behavior, safety, and documentation.
5. Iterate when acceptance criteria are not yet met.

This file is updated after every iteration with changes, evidence, remaining risks, and roadmap.

## Iteration 0 — Isolated baseline and publication

### Changes

- Created the private GitHub repository at `<your-fork-url>`.
- Cloned it to an isolated directory, outside the original workspace.
- Copied the current harness content without its `.git` directory or `.DS_Store` files.
- Created and pushed an immutable baseline commit on `main`.
- Created `agent/enhance-copilot-harness` for all implementation work.

### Why

The source workspace had no commits or remote and the user explicitly required that it remain
untouched. A baseline commit creates a reviewable before/after comparison while the private
repository protects future internal Salesforce, ADO, QA, and decision data.

### Verification

- GitHub authentication confirmed for the repository owner account.
- Remote repository created successfully.
- Baseline push to `origin/main` succeeded.
- Enhancement branch exists locally and is based on commit `66649b6`.
- Original workspace remains an uncommitted, separate Git repository; no commands in this
  implementation write to it.

### Discovery observations carried forward

- Agent handoffs use string arrays instead of current structured handoff objects.
- Delegating agents omit the required `agent` tool.
- Several tool identifiers are legacy or unqualified.
- Prompt files do not pin an execution agent or required tools.
- The root instruction file overstates the reliability and ordering of `applyTo: "**"` files.
- Most skills are strong procedural drafts but lack configured MCP/CLI execution dependencies,
  stable data contracts, pagination/error policies, and behavioral evaluations.
- Organization rules, high-risk package data, release scope, and target test location still
  contain human-owned placeholders.
- No repeatable CI validator or GitHub governance layer exists.
- A legacy placeholder `.github/chatmodes/test.chatmode.md` exists and should be removed after
  confirming that no supported workflow depends on it.

## Current loop completion

- Iteration 1 — native Copilot correctness and safety: complete.
- Iteration 2 — executable intelligence and contracts: complete for the repository layer.
- Iteration 3 — deterministic quality, governance artifacts, and local proof: complete.
- Iteration 4 — Principles → Knowledge → repository/org review grounding, work-record v2,
  false-`SAFE` rejection, and one-root SFDX topology: complete locally.
- Prior enhancement publication evidence remains historical. Current branch publication and CI
  must be verified live after each new commit.

## Iteration 4 — Grounded Salesforce solution design and flat-root SFDX

### Changes

- Added schema-v3 Knowledge claims, immutable evidence, human review bindings, effective-claim
  queries, contradiction/freshness checks, and deterministic generated indexes.
- Added revisioned work records that bind Principles, verified claims, component ownership,
  repository commits, bounded Salesforce org receipts, durable artifacts, human approval,
  verification profiles, reviews, and handoffs to exact hashes.
- Made `SAFE` a derived state: fabricated ownership, environment labels, evidence, approvals,
  test results, and verdict strings are rejected by runtime contracts and adversarial tests.
- Restricted the Investigator to ignored proposal drafts and `proposed` canonical Knowledge;
  review/promotion and work-record approval remain human-only commands.
- Moved the Salesforce DX project to the repository root so the first/only `brain-core` workspace
  is directly recognized by Salesforce extensions. MCP development writes remain bounded to
  `force-app/`, `manifest/`, and `tests/e2e/`, with governance/config paths explicitly denied.
- Kept the package generic: no invoice object, namespace, installed version, or business meaning
  exists in runtime authority until scoped evidence and human review establish it.

### Known limits

- Static tests cannot certify VS Code extension-host discovery or model behavior; run Chat
  Diagnostics, handoffs, MCP tool resolution, and the manual model/version scenarios on the pilot
  workstation.
- Human approval/review identities are currently asserted and hash-bound, not provider/signature
  authenticated.
- Both local Salesforce MCP servers share VS Code's top-level sandbox policy; the read-only facade
  is tool-surface read-only but inherits the same narrow source write allowance at OS level.
- The pinned Node dependency tree has 24 audit findings (6 low, 17 moderate, 1 high). Do not apply
  an untested automatic upgrade; record a risk decision or certify a vendor-supported update.

## Iteration 1 — Native Copilot correctness and safety

### Changes

- Replaced the table-of-contents-only root instruction with an always-on safety kernel containing
  stable `SAFE-*` rule IDs, explicit precedence, fail-closed evidence handling, external-content
  prompt-injection boundaries, approval gates, credential rules, role boundaries, and provenance.
- Reworked all three Principle files with stable Tier 1/2/3 rule IDs and safe fallback behavior
  for human-owned placeholders. Missing sandbox coordination now permits reads only; an unknown
  package condition can no longer yield a Safe verdict.
- Corrected all five agents to current VS Code tool names, added `read`, added `target: vscode`,
  enabled the required `agent` tool for subagent allowlists, and replaced string handoffs with
  structured, human-triggered (`send: false`) handoffs including correction paths.
- Added agent-scoped role hooks for Designer, Investigator, Developer, and Test Strategist write
  and preflight-only terminal boundaries.
- Pinned all seven prompt files to intentional agents, added `name` and `argument-hint`, linked
  their skills, validated inputs before tools, and removed dependence on the previously selected
  Ask/Plan/Agent mode.
- Hid all twelve internal skills from the slash-command menu with `user-invocable: false`, leaving
  exactly seven stable public prompt commands and eliminating prompt/skill name collisions.
- Removed the obsolete placeholder `.github/chatmodes/test.chatmode.md`.
- Added `AGENTS.md`, current activation settings, referenced-instruction loading, hook loading,
  extension recommendations, VS Code tasks, and a canonical `sf-harness.code-workspace`.
- Established `brain-core` (`.`) as the one named workspace folder and the repository root as the
  SFDX root; Salesforce metadata and harness governance share one branch and pull-request lineage.
- Added compatibility and workspace-topology contracts.
- Added a common skill execution contract, tool-capability map, change-record template, local
  configuration example, global production/destructive-operation hook, and role write guard.

### Architecture decisions

- The five-role SDLC and twelve capabilities remain intact; orchestration is now encoded in native
  objects rather than prose-only intentions.
- The harness and Salesforce DX project use the same repository root. Deterministic tool routing
  resolves `brain-core` once, while least-privilege MCP writes remain bounded to approved root
  metadata/test subpaths.
- Human-owned business/package values remain placeholders. Each now has a conservative runtime
  fallback instead of silently weakening safety.
- Hooks are introduced despite the original parking-lot decision because the new hardening goal
  explicitly requires enforceable safety; hooks supplement, not replace, model instructions.

### Verification

- Python compilation passed for both safety-hook scripts.
- All 27 YAML frontmatter blocks parsed successfully.
- Solution Designer write to `.ai/memory/decisions-log.md` was allowed.
- Solution Designer write to `force-app/classes/X.cls` was denied.
- A terminal command targeting `production` was denied by `SAFE-ENV-001`.
- A destructive `rm -rf` command was denied by `SAFE-ROLE-001`.
- Live VS Code Customization Diagnostics remain a developer-machine gate because `code` is not
  installed in this execution environment.

### Risks carried into Iteration 2

- External MCP servers and their guarded startup/preflight are not yet configured.
- Existing skill bodies still need task-specific schemas, completeness, pagination, and failure
  hardening beyond the new shared contract.
- The role guard depends on Preview hook support and must be verified against real VS Code tool
  input shapes; ambiguous edit targets intentionally require user approval.
- Historical README, SETUP, blueprint, diagrams, and build-report authority still need alignment.
- Static CI and behavioral fixtures do not exist yet.

The MCP, skill-contract, documentation-authority, CI, and fixture gaps above were addressed in the
current loop. Preview-host behavior still requires the live gates listed below.

## Iteration 2 — Executable intelligence and contracts

### Changes

- Added one ignored, schema-validated local configuration contract for ADO, approved
  non-production Salesforce aliases, browser origins/profile, workspace paths, and cache policy.
- Added a fail-closed preflight that validates configuration and checks dependencies per
  capability without relying on a default Salesforce org.
- Added a bounded read-only Azure DevOps MCP server plus separate guarded Salesforce read and
  development servers. The wrapper pins `@salesforce/mcp@0.30.15`, rejects production-like or
  unallowlisted aliases, verifies a locally authorized sandbox host plus live
  `Organization.IsSandbox=true`, and enables writes only for an approved development alias.
- Bound the ADO MCP organization to the preflight-checked `ADO_ORGANIZATION` environment value and
  made the global hook reject calls without the configured project or with mismatched ADO URLs.
- Removed raw Salesforce CLI from all supported agent workflows and limited MCP write scope to
  approved metadata/test subpaths under the repository/SFDX root. Development edits are restricted
  to those paths plus reviewed documentation/change-record paths.
- Added a pinned guarded Playwright runner that denies credential/storage/code/upload/network
  surfaces, checks current/all-tab origins around actions, and closes on origin drift. Generated
  test code is never executed before human review/promotion.
- Reworked all twelve skills around explicit inputs, dependency gates, untrusted-data handling,
  bounded pagination, freshness/completeness, atomic-write behavior, failure states, provenance,
  and human approval boundaries while preserving their original functional roles.
- Added normative execution and tool-capability contracts plus versioned schemas for ADO item
  cache, Test Case cache, generated-output evidence, and local configuration.
- Added sanitized complete/partial cache and output fixtures. The exact cache field vocabulary now
  matches the shared contract (`schemaVersion`, `source.retrievedAt`, and `completeness`).
- Replaced historical setup claims with a current single-repository operating guide and marked the
  blueprint/build/Fable/diagram documents as historical input rather than runtime authority.

### Architecture decisions

- External text is evidence, never executable instruction.
- No production alias, URL, default org, `ALLOW_ALL_ORGS`, or `@latest` dependency is configured;
  actual Salesforce identity is proved rather than inferred from an alias.
- ADO remains server-side read-only. Salesforce read and development capabilities are separate,
  with local CLI authorization kept outside the agent and repository.
- Generated drafts and raw cache remain ignored; curated Knowledge/Memory/QA changes remain
  reviewed repository content.
- Missing human-owned policy narrows or blocks behavior rather than being replaced with a guess.
- The certified external-work boundary is the five custom agents in a dedicated pilot environment
  with no production CLI/browser authorization. Built-in/default Agent and arbitrary terminal
  modes are explicitly unsupported because pattern hooks are not a general shell sandbox.

## Iteration 3 — Quality, governance, and proof

### Changes

- Added `scripts/validate_harness.py`, which validates customization inventory and frontmatter,
  tool IDs, delegation/handoff graphs, public command uniqueness, Markdown links, settings parity,
  MCP/hook safety, schema fixtures, placeholder register, CI pinning, and secret signatures.
- Added focused unit tests for preflight rules, global production/destructive/browser/Salesforce
  controls, and role-specific path boundaries.
- Added twenty-three executable safety scenarios and twelve manual forward scenarios for model/host
  behavior. Manual scenarios cover prompt injection, partial evidence, missing approval, sandbox
  writes, pagination, taxonomy approval, release completeness, browser origins, production,
  precedence, and Knowledge conflicts.
- Added a SHA-pinned, read-only GitHub Actions pipeline for Python 3.12 on Linux and Windows, using
  a resolved validation dependency lock.
- Added CODEOWNERS, a pull-request template, contribution policy, and security policy.
- Added VS Code tasks for preflight, validation, unit tests, and deterministic evaluations.

### Historical local verification snapshot — pre-grounding/topology hardening, 2026-07-10

The counts below describe that completed iteration and are not current certification totals. Use
the latest local/CI run for the current one-root topology and record its exact counts separately.

- `python scripts/validate_harness.py`: PASS — 942 checks.
- `python -m unittest discover -s tests -v`: PASS — 52 tests.
- `python scripts/run_evals.py`: PASS — 23 deterministic scenarios.
- Python compile, Salesforce MCP launcher parse, workflow YAML parse, and `git diff --check`: PASS.
- Ignore canaries for local config, raw ADO cache, and generated handover output: PASS.
- Production aliases/hosts, raw/wrapped/substituted Salesforce CLI, default/multiple targets,
  broad Salesforce MCP/data surfaces, ADO scope drift, browser credential/navigation surfaces,
  metadata path traversal, out-of-role edits/terminal commands, ambiguous writes, allowlist suffix
  bypasses, and contradictory completeness states: denied, rejected, or escalated as designed.
- GitHub Actions run `29106567102`: Linux PASS, Windows PASS, with SHA-pinned Node 24 action
  runtimes and no deprecation annotation. GitGuardian: PASS.
- Independent read-only final audit: GO — no remaining P0/P1 blocker for the controlled-pilot
  branch.

### Readiness assessment

| Area | Current maturity | Evidence boundary |
|---|---:|---|
| Copilot instruction configuration | 8/10 | Static discovery, precedence, references, and fail-closed rules pass; live VS Code Diagnostics remain. |
| Agent orchestration | 8/10 | Native tools, subagents, structured correction handoffs, edit/terminal boundaries, and tool paths validate; live handoff/tool resolution remains. |
| Skills and prompts | 7.5/10 | Stable public surface, executable contracts, guarded runtimes, and negative fixtures exist; real external smoke tests and seeded organization Knowledge remain. |
| Pipeline and governance artifacts | 8/10 | Cross-platform SHA-pinned CI is green; squash-only/branch cleanup are configured, but private-repository branch protection requires a GitHub plan upgrade. |
| Developer readiness | Conditional controlled pilot | Not ready for unsupervised/team-wide rollout until the live gates and human inputs below are closed. |

### Live gates intentionally not claimed by local CI

- Run VS Code **Chat: Run Customization Diagnostics** on a supported Stable build with zero
  unresolved agents, prompts, skills, hooks, handoffs, or tools.
- Complete one harmless ADO read and Salesforce read against approved non-production targets.
- Confirm the dedicated pilot account/VM/container exposes no production CLI authorization or
  browser session; do not use built-in/default Agent for external workflows.
- Smoke-test a guarded development action only after shared-sandbox coordination is supplied.
- Execute the twelve manual agent scenarios and attach observed evidence to the PR.
- Seed a small verified organization/package/QA Knowledge slice; current mechanics are testable,
  but organizational intelligence is intentionally not fabricated.
- Upgrade the private repository to a GitHub plan that supports branch protection (or move it to
  an eligible organization), then require both Harness CI contexts. The API returned HTTP 403 on
  the current plan. Add another maintainer before team rollout; current bus factor is one.

## Publication result

- Enhancement branch is pushed and draft PR #1 is open.
- Repository merge policy is squash-only; merge commits and rebase merges are disabled; merged
  branches are deleted automatically.
- Classic protection was attempted with strict Linux/Windows Harness CI, pull-request-only flow,
  linear history, conversation resolution, and force-push/deletion bans. GitHub rejected it with
  `Upgrade to GitHub Pro or make this repository public to enable this feature` (HTTP 403).
- The private repository remains the correct choice for future Salesforce/ADO/QA Knowledge. Do
  not make it public to obtain free protection; upgrade/move the repository instead.
- The original legacy workspace (outside this repository) was not edited; all implementation,
  validation, commits, and publication occurred in the isolated clone.

## Human-owned inputs that must not be invented

- Company naming and code-review conventions.
- Shared Full Copy Sandbox coordination rules.
- Package/component ownership and risk registry with authoritative, version-scoped sources.
- Supported extension-point and transaction-interaction evidence for the selected pilot component.
- Azure DevOps organization/project and saved release Query ID.
- Salesforce dev/QA/UAT aliases and package namespace.
- Final promoted Playwright test directory.

Until supplied, the enhanced harness will fail closed or clearly degrade the affected workflows;
it will not guess these values.

## force-app Knowledge extension (2026-07-10)

Added a governed repository-root `force-app` inventory and Knowledge proposal workflow. The
extension adds two hidden skills, three public prompts routed to `config-investigator`, a bounded
`scripts/force_app_knowledge.py` runtime, inventory/draft-manifest schemas, role-guard coverage,
tests, and `docs/force-app-knowledge-architecture.md`. Current customization totals are five
agents, ten public prompts, and fourteen internal skills.

The live run remains fail-closed: metadata preflight reports placeholder local configuration and
the current `force-app` contains untracked source. No source file was falsely bound to the current
commit and no canonical Knowledge claim was created. Unit fixtures prove clean committed source
can generate schema-v3 sanitized drafts and that changed/dirty source is rejected.

## Pilot exit criteria

- All agents, prompts, instructions, and skills load without VS Code customization diagnostics.
- Every configured tool identifier resolves.
- Every handoff and correction path works and preserves the required context.
- Restricted agents cannot perform implementation or external writes outside their role.
- Within the five supported custom agents and isolated pilot environment, no production Salesforce
  authorization or browser session is available.
- Blocking human-owned placeholders fail closed with actionable messages.
- Structural validation and the safety evaluation suite pass in CI.
- Setup documentation allows a new developer to verify the workspace deterministically.
- The final branch is pushed and a draft PR explains changes, validation, and remaining roadmap.
