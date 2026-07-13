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

The pinned Node dependency tree carries 24 known non-critical advisories, all transitive to
vendor-pinned Salesforce tooling. They were investigated on 2026-07-13, are not resolvable on
stable release channels, and are formally accepted with mitigations (install with
`--ignore-scripts`, local-workstation-only execution, Dependabot monitoring, CI failing on
`critical`). See the 2026-07-13 entry in `.ai/memory/decisions-log.md` for evidence and
re-evaluation triggers. Do not run `npm audit fix --force` or adopt prerelease packages to clear
the count; both were evaluated and rejected.

## Pilot threat model

The controlled-pilot threat model requires a dedicated OS account, VM, or container whose agent
process can access only approved sandbox CLI authorizations and a sandbox-only browser profile.
Built-in/default Agent mode and arbitrary terminal workflows are not supported for external work;
hooks cannot secure dynamically constructed shell programs. Any production credential/session or
reachable production path in that pilot environment is a release-blocking security defect.
