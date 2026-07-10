# Contributing

This repository is a safety-sensitive AI development harness. Keep changes small, reviewable, and
traceable to a work item or recorded decision.

## Workflow

1. Branch from the current default branch; do not work directly on `main`.
2. Read `AGENTS.md`, the root Copilot instructions, and the applicable Tier 1–3 rule files.
3. Preserve role separation: design, implementation, testing, investigation, and independent
   guardrail review are distinct responsibilities.
4. Never replace a human-owned placeholder with an invented value.
5. Run the validation commands in the pull-request template.
6. Open a draft pull request early and include unresolved evidence gaps explicitly.

## Change rules

- Keep production aliases, production URLs, credentials, tokens, customer data, and local browser
  profiles out of the repository.
- Do not commit `config/harness.local.json`, `.cache/**`, or `output/**` artifacts.
- Any new public slash command needs an owner, stable name, pinned agent, input contract, and
  deterministic failure behavior.
- Any new custom agent needs a bounded role, current tool IDs, correction handoffs, and safety tests.
- Any new external integration needs a capability entry, preflight gate, allowlist, sanitized cache
  contract, and negative test.
- Changes to stable `SAFE-*`, `MP-*`, `ORG-*`, or `SF-*` rules require an explicit reviewer and a
  decision-log entry.

CI proves repository structure and deterministic controls. It does not replace live VS Code
Customization Diagnostics or non-production integration smoke tests.
