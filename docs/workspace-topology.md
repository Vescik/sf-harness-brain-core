# Workspace Topology

Status: normative
Owner: harness maintainers
Last verified: 2026-07-10

The supported developer layout is one Git repository whose root is both the harness root and the
only Salesforce DX project root:

```text
sf-harness-brain-core/       # Git repository, SFDX root, workspace folder: brain-core
├── sfdx-project.json
├── force-app/               # Salesforce metadata source
├── manifest/                # package.xml and related manifests
├── tests/e2e/               # promoted Salesforce end-to-end tests
├── .github/                 # Copilot instructions, agents, prompts, skills, hooks
├── .ai/                     # governed Knowledge and durable work state
├── scripts/                 # harness runtime and validation
└── sf-harness.code-workspace
```

Open `sf-harness-brain-core/sf-harness.code-workspace`. It exposes one named folder:
`brain-core` maps to `.`. There is no second named Salesforce folder and no nested SFDX project.
The single root keeps metadata, governance, source control, review, and branch history together.
Opening the repository directory directly is also valid. Runtime configuration uses unqualified
`${workspaceFolder}` variables, which resolve in both direct-folder and single-root workspace-file
sessions.

The root owns `sfdx-project.json`, `force-app/`, `manifest/`, `tests/e2e/`, instructions, agents,
skills, Knowledge, Memory, QA indexes, cache, and generated drafts. Skills must resolve
`brain-core` as the one SFDX root and must reject a missing or ambiguous project rather than
searching a subfolder, parent directory, sibling directory, or other checkout.

Run `Harness: Preflight` after opening the workspace. Harness CI and metadata-dependent prompts
operate against the same checkout, so Salesforce metadata and the governing design/handoff remain
reviewable in one pull request.

The guarded Salesforce development MCP process starts from `brain-core` and refuses to start when
root `sfdx-project.json` is missing. Root identity does not grant root-wide write authority: MCP
filesystem inputs and role permissions remain bounded to approved metadata/test subpaths such as
`force-app/`, `manifest/`, and `tests/e2e/`. Harness instructions, Knowledge, work records,
configuration, and other governance content remain outside the Salesforce write scope.

Root `manifest/package.xml` is a generic starter manifest. It must be narrowed and bound to the
accepted work record before an org-facing operation; wildcard members are not authorization.

Do not create a nested `.git` or `sfdx-project.json`, relocate metadata to another directory, or
duplicate `force-app/` under a wrapper folder. Salesforce source and manifests are tracked at the
repository root alongside the harness that governs their lifecycle.
