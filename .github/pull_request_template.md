## Purpose

Describe the harness behavior being changed and the developer/user outcome.

## Scope and evidence

- Related work item or decision:
- Affected agents/prompts/skills/rules:
- Human-owned assumptions or unresolved facts:
- Security or production-safety impact:
- Work `recordId` / handoff IDs when governed:
- Rule, Knowledge entry, and human review references:
- Knowledge freshness or source/org drift:

## Validation

- [ ] `python3 scripts/validate_harness.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 scripts/run_evals.py`
- [ ] `npm ci --ignore-scripts`
- [ ] `npm run prettier:verify && npm run lint`
- [ ] `python3 scripts/preflight.py --capability base` with a local, non-production config
- [ ] VS Code **Chat: Run Customization Diagnostics** has no errors
- [ ] Handoffs and named tools were smoke-tested in the canonical workspace when affected
- [ ] Every material system/package fact is grounded in an approved-current Knowledge entry
- [ ] No draft, superseded, or scope-mismatched entry is presented as trusted Knowledge
- [ ] Approval and handoff references match the current record revision and scope/design hashes
- [ ] Salesforce reads used only the governed facade/wrapper; no raw CLI, raw vendor MCP tool, or alias was exposed
- [ ] No credential, customer data, cache, generated output, or local config is included

## Review gates

- [ ] Tier 1 managed-package constraints reviewed where applicable
- [ ] Independent Guardrail Reviewer result attached for implementation changes
- [ ] Human approval recorded for rule, taxonomy, release, or external-write changes
