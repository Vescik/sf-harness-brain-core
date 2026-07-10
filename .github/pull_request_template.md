## Purpose

Describe the harness behavior being changed and the developer/user outcome.

## Scope and evidence

- Related work item or decision:
- Affected agents/prompts/skills/rules:
- Human-owned assumptions or unresolved facts:
- Security or production-safety impact:

## Validation

- [ ] `python3 scripts/validate_harness.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 scripts/run_evals.py`
- [ ] `python3 scripts/preflight.py --capability base` with a local, non-production config
- [ ] VS Code **Chat: Run Customization Diagnostics** has no errors
- [ ] Handoffs and named tools were smoke-tested in the canonical workspace when affected
- [ ] No credential, customer data, cache, generated output, or local config is included

## Review gates

- [ ] Tier 1 managed-package constraints reviewed where applicable
- [ ] Independent Guardrail Reviewer result attached for implementation changes
- [ ] Human approval recorded for rule, taxonomy, release, or external-write changes
