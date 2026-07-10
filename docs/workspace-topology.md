# Workspace Topology

Status: normative
Owner: harness maintainers
Last verified: 2026-07-10

The supported developer layout is a two-root VS Code workspace:

```text
<parent>/
├── sf-harness-brain-core/   # workspace root name: brain-core
└── salesforce-metadata/     # workspace root name: salesforce
```

Open `sf-harness-brain-core/sf-harness.code-workspace`. The tracked workspace deliberately uses
the sibling name `salesforce-metadata`; clone or link the real SFDX repository at that path.

The `brain-core` repository owns instructions, agents, skills, Knowledge, Memory, QA indexes,
cache, and generated drafts. The `salesforce` repository owns `sfdx-project.json`, `force-app`,
`manifest`, tests, and deployment history. Skills must locate the named `salesforce` root and
must reject zero or multiple SFDX roots rather than falling back to the current directory.

Run `Harness: Preflight` after opening the workspace. Harness CI does not require the private
metadata repository, but any metadata-dependent prompt does.

The guarded Salesforce development MCP process starts with `salesforce-metadata` as its working
directory; it refuses to start when that root has no `sfdx-project.json`. Its MCP sandbox permits
writes only to the named Salesforce root; brain-core remains outside the server's write scope.

Do not copy `force-app` or `manifest` into the brain repository. Unlike the historical baseline,
the enhanced `.gitignore` does not silently hide those folders; preflight reports the unsupported
topology so metadata cannot disappear from source control unnoticed.
