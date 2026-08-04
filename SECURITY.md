# Security Policy

## Supported version

Only the latest commit on the default branch is supported during the controlled pilot.

## Reporting

Do not open a public issue for a credential leak, production-access path, prompt-injection bypass,
unsafe tool permission, or customer-data exposure. Use this private repository's **Security →
Report a vulnerability** flow when available; otherwise contact the repository owner privately.

Include the affected rule/tool, minimal sanitized reproduction, impact, and proposed containment.
Do not include live credentials, production identifiers, or business records.

## Immediate containment

If sensitive data or a secret is committed, stop agent workflows, revoke/rotate the secret at its
source, restrict repository access if needed, and preserve an audit trail. Removing a Git commit is
not sufficient containment by itself.

## Dependency vulnerability posture

The pinned Node dependency tree carries a small number of moderate advisories (12 as of
2026-08-05, zero high/critical), all transitive to the vendor-pinned `@salesforce/mcp` runtime.
The 2026-08-04 deps-hygiene pass cleared every high advisory in-range and tightened the CI gate
from `critical` to `high` (`npm audit --omit=dev --audit-level=high`); remaining moderates are
accepted with mitigations (install with `--ignore-scripts`, local-workstation-only execution,
Dependabot monitoring). See the 2026-07-13 and 2026-08-04 entries in
`.ai/memory/decisions-log.md` for evidence and re-evaluation triggers. Do not run
`npm audit fix --force` or adopt prerelease packages to clear the count; both were evaluated
and rejected.

## Pilot threat model

The controlled-pilot threat model requires a dedicated OS account, VM, or container whose agent
process can access only approved sandbox CLI authorizations.
Built-in/default Agent mode and arbitrary terminal workflows are not supported for external work;
hooks cannot secure dynamically constructed shell programs. Any production credential/session or
reachable production path in that pilot environment is a release-blocking security defect.
