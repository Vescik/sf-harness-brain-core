# Compatibility Contract

Status: normative
Owner: harness maintainers
Last verified against vendor documentation: 2026-07-10

## Supported baseline

| Component | Supported baseline | Notes |
|---|---|---|
| VS Code | 1.112+; certify current stable before rollout | Windows is the primary platform. The configured MCP surface is read-only on every platform; guarded browser workflows remain macOS/Linux-only. |
| GitHub Copilot | Consolidated `GitHub.copilot` extension bundled/supported by the chosen VS Code release | The old separate Copilot Chat prerequisite is not used. |
| Python | 3.11+ | Runs preflight, validation, safety hooks, and tests using the standard library plus the dev requirement below. |
| PyYAML | `>=6,<7`; CI uses the lock file | Frontmatter and evaluation validation. |
| jsonschema | `>=4,<5`; CI uses the lock file | Draft 2020-12 configuration/cache/output validation. |
| Node.js | 22+ (`.nvmrc` pins 24) | The pinned `@salesforce/mcp` requires Node ≥22.19; CI installs the `.nvmrc` version. |
| Azure DevOps MCP | Local stdio `@azure-devops/mcp@2.8.1` (pinned in `.vscode/mcp.json`), domains work-items/wiki/test-plans/search | Switched from the hosted endpoint 2026-07-14: its toolset header was not honored, while local `-d` domain args are. No server-side read-only — read-only is harness policy (hooks); requires `az login`. |
| Salesforce DX MCP | `@salesforce/mcp@0.30.15` | Pinned to the version verified on 2026-07-10; update deliberately. |
| Playwright CLI | `@playwright/cli@0.1.17` | Use executable `playwright-cli` only through `scripts/playwright_guard.py`. |

## Required Copilot capabilities

- Repository and referenced instruction files
- Custom agents with structured handoffs
- Agent Skills and hidden internal skill commands
- Prompt files with custom-agent selection
- Subagent `agent` tool
- Workspace and agent-scoped hooks
- MCP servers and namespaced tools

## Verification boundary

Static validation in CI proves file shape and policy invariants. It does not prove that an
installed VS Code build exposes every tool. Before a developer pilot, open **Chat: Open
Customizations** and **Chat Diagnostics** on each supported platform and record:

- exactly five agents, twelve public prompts, sixteen internal skills, and three Principle files;
- no unresolved tool, handoff, frontmatter, hook, or MCP diagnostic;
- one successful harmless read call through each configured external server.

Since the 2026-07-14 decision the harness configures no write-mode Salesforce MCP server and no
OS-level MCP sandbox keys (the fleet runs Windows, where VS Code cannot sandbox MCP): both
configured servers are read-only by construction, org mutation is not an agent capability, and
the guarded wrapper, review facade, safety hook, and role guards are the enforcement layers.
Agents may request `sf project retrieve start` against a configured alias; the safety hook stops
each invocation for human confirmation. Deploys ship through the human-run release process
outside Copilot. Guarded browser execution remains macOS/Linux-only.

The certified external-work surface is limited to the five repository custom agents in a dedicated
pilot environment with no production authorization or browser session. Built-in/default Agent and
arbitrary terminal modes are not certified; hooks are not a general shell sandbox.

## Upgrade policy

Do not use `latest` for runtime dependencies in the shared workspace. `requirements-dev.txt`
declares supported ranges; `requirements-dev.lock` pins CI's resolved set. Upgrade one component
at a time, run static tests plus the behavioral evaluation suite, update the lock and this file,
and retain the previous pinned version until the pilot evidence is accepted.

The lock is **hash-pinned**: CI and SETUP install with `pip install --require-hashes`, which
verifies every downloaded artifact's sha256 (regenerate the `--hash` lines from the PyPI JSON API
as noted in `requirements-dev.txt` when bumping a pin). `typing_extensions` appears in the lock
only as a transitive of `referencing` under `python_version < '3.13'`; on Python 3.13+ it drops
out of the resolved set automatically. Supply-chain monitoring runs continuously via
`.github/dependabot.yml` (pip, npm, github-actions) plus a `npm audit --audit-level=critical` CI
gate; lower-severity npm advisories in the pinned `@salesforce/mcp` transitive tree are tracked by
Dependabot rather than hard-failing CI.

The current 24 non-critical npm findings were investigated on 2026-07-13 and are a recorded,
accepted risk: all are transitive to vendor-pinned Salesforce tooling, no stable upgrade resolves
them, and an in-range update was tested and rejected because it worsened the posture. See the
2026-07-13 entry in `.ai/memory/decisions-log.md` before attempting another upgrade.
