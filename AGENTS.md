# Agent Compatibility Contract

Use `.github/copilot-instructions.md` as the canonical always-on safety and grounding kernel.
Governed work must run through the checked-in workspace and a checked-in custom agent. Treat
`brain-core` (`.`) as the only named workspace folder and the only SFDX root; never search a
subfolder, parent, sibling, or second checkout for metadata. Salesforce writes remain bounded to
the authorized root subpaths, not to harness policy or governed-state files. Load the persisted
work record before acting, and load detailed Principles, contracts, Knowledge, and skills only
through the active role.
Built-in/default Agent mode and arbitrary terminal workflows are not supported for external
systems or governed state changes.
