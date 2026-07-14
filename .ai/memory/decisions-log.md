# Decisions Log

Persistent, versioned cross-work-item memory of the project — distinct from VS Code's built-in
Memory tool (local, per-machine), Copilot Memory, canonical Knowledge claims, and active work
records. This file records durable architectural decisions; it is not the workflow state store.

Two kinds of entries belong here:

1. **Discoveries of system facts with practical consequences** (e.g. "we established that field
   X controls Y — this changes the plan for Z").
2. **Accepted cross-work-item architectural decisions** whose effect outlives an individual work
   record. Active designs, approvals, evidence, coverage assessments, reviews, and handoffs live
   under `.ai/change-records/<record-id>/` and are referenced here only when they establish a
   durable project decision.

System facts are canonical Knowledge claims and must not be duplicated here. Chat-only decisions
are not durable.

## Entry format (template — copy for each new entry)

```
## <date> - <short title>
- Context: ...
- Finding / decision: ...
- Impact: ...
- Approved by: <who>
- Related: <link to a knowledge/ file or another entry>
```

---

<!-- Entries are appended below this line as they occur — never fabricated at build time. -->

## 2026-07-14 - Knowledge upgrade: total metadata coverage and chat-approved promotion

- Context: running the documentation pipeline on an approval process produced nothing (only 10
  metadata types had parsers/claim candidates), and promotion required a hand-written review YAML
  with digests plus two terminal commands — the feature added work instead of removing it. The
  workspace owner directed a careful autonomy upgrade.
- Finding / decision: (1) coverage is now total — approval processes draft automation-inventory
  claims and every other source-format metadata file drafts a generic claim into the new
  `component-inventory` domain (schema/policy/registry extended); a recognized source file can no
  longer draft nothing. (2) Agents may request promotion/rejection via the new
  `knowledge_registry.py approve-claim` command: the safety hook answers `ask` so a human
  confirms every invocation in the chat dialog, the reviewer identity comes from the human-owned
  `knowledge.chatReviewer` value in ignored local configuration, and the recorded mechanism is
  `copilot-chat-confirmation` (new review-schema enum value). The registry computes all binding
  digests itself and re-renders the domain indexes. File-based `review`/`promote` remain
  human-terminal-only; work-record approval is unchanged (terminal-only).
- Impact: the propose → approve loop happens in one chat session with one human click per claim;
  SAFE-HUMAN-001 was reworded to distinguish the recorded chat-confirmation dialog from chat
  text (which is still never approval).
- Approved by: workspace owner directive, 2026-07-14.
- Related: `.ai/contracts/knowledge-lifecycle.md`, `docs/force-app-knowledge-architecture.md`.

## 2026-07-14 - MCP is read-only; org mutation is not an agent capability

- Context: the fleet runs Windows, where VS Code cannot sandbox MCP processes, so the
  `salesforce-development` write server was permanently blocked there and produced a recurring,
  confusing `exit code 2` MCP startup error. The workspace owner directed a model change: MCP
  exists to gather information and support solution design/development, not to deploy or
  retrieve.
- Finding / decision: the `salesforce-development` MCP server, its `sf_dev_org` input, and the
  OS-level `sandbox`/`sandboxEnabled` keys are removed from `.vscode/mcp.json`. The configured
  MCP surface (`ado-readonly`, `salesforce-readonly`) is read-only by construction. Agents ground
  context in the connected org through the review facade and the guarded
  `scripts/salesforce_read.py` (now also available to Solution Designer and Development
  Assistant). The only raw Salesforce CLI agents may request is `sf project retrieve start`
  against a configured non-production alias, and the safety hook stops every invocation for
  human confirmation (SAFE-HUMAN-001); deploys and all other raw CLI stay denied and ship
  through the human-run release process outside Copilot.
- Impact: the Windows MCP error is gone; the write-capable attack/blast surface is gone with it
  (no MCP write path exists to protect, so losing OS sandboxing on Windows no longer degrades
  the model). Enforcement layers: guarded wrapper, review facade, global safety hook, role
  guards, validator checks (which now fail if a write server or sandbox keys reappear without a
  new recorded decision).
- Approved by: workspace owner directive, 2026-07-14.
- Related: `docs/compatibility.md` (verification boundary), `SETUP.md` §3/§6,
  `docs/windows-setup.md`.

## 2026-07-13 - npm audit findings in the pinned Node tree are accepted, not fixable today

- Context: `npm audit` reports 24 findings (6 low, 17 moderate, 1 high `protobufjs`) in the
  pinned dependency tree. The workspace upgrade policy requires a tested vendor-supported update
  or a recorded risk decision. A resolution attempt was run on 2026-07-13.
- Finding / decision: every finding is a transitive dependency of vendor-pinned Salesforce
  tooling and none is resolvable on stable channels today. Evidence: `@salesforce/mcp@0.30.15`
  is the latest published version (npm's suggested "fix" `0.3.0` is a downgrade artifact);
  the `@salesforce/sfdx-lwc-jest` fix ships only in `8.0.0`, which is dist-tagged `prerelease`;
  a full in-range `npm update` was tested and made the posture worse (37 findings, 9 high) by
  pulling newer transitives with fresh advisories, then was reverted. Decision: keep the pinned
  baseline, accept the 24 findings, and revisit on each Dependabot vendor release.
- Impact: exposure is bounded by the existing controls — the tree is installed with
  `--ignore-scripts`, runs only on the local pilot workstation (never in an org or CI deploy
  path), the MCP servers run under the workspace sandbox/wrapper policy, CI hard-fails only on
  `critical`, and Dependabot watches pip/npm/actions weekly. The `protobufjs` high is a DoS in
  JSON descriptor parsing inside `@salesforce/mcp`'s telemetry chain, not an harness-reachable
  code path. Re-evaluate when `@salesforce/mcp` publishes a new stable or `sfdx-lwc-jest@8`
  leaves prerelease; do not adopt prerelease tooling in this governance-pinned workspace.
- Approved by: workspace owner directive of 2026-07-13 (Windows-rollout goal); formal team
  sign-off pending at pilot review.
- Related: `docs/compatibility.md` (upgrade policy), `SECURITY.md` (dependency posture).
