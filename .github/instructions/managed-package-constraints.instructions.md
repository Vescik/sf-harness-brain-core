---
description: Generic managed-package and closed-surface constraints. Load when a governed workflow touches a package-owned or ownership-unknown component.
---

# Managed Package Constraints — Tier 1

These rules override Organization Principles and general Salesforce practice.

## Global rules

- **MP-GEN-001 — inspect before change.** Check
  [Known Limitations](../../.ai/knowledge/known-limitations.md) for every affected package object,
  page, function, and automation surface.
- **MP-GEN-002 — closed means closed.** Do not propose edits to vendor-owned metadata or runtime
  behavior that the organization cannot deploy. Design only through verified extension points.
- **MP-GEN-003 — unknown is incomplete.** If ownership, extensibility, automation interaction, or
  upgrade behavior is unknown, return `INCOMPLETE — NEEDS HUMAN` and request investigation.
- **MP-GEN-004 — upgrades require re-verification.** A constraint without a source and verified
  package version cannot support a `Safe` verdict after a package upgrade.
- **MP-GEN-005 — package identity is scoped evidence.** Package namespace, subscriber package,
  installed version, target environment, and observation time must be established before a
  package-specific claim can be used. Evidence for one package version or org is not portable to
  another without review.
- **MP-GEN-006 — transport agreement is not independent truth.** Agreement between Salesforce MCP
  and CLI increases confidence that an org observation was transported correctly, but both read
  the same org. It cannot establish business meaning, vendor guarantees, or inaccessible package
  internals without an authoritative source.

## Generic component rules

- **MP-OWN-001 — classify ownership before design.** Classify every affected component as
  `package-owned`, `subscriber-owned`, `platform`, or `unknown`, with package namespace/version
  evidence where applicable. `unknown` is blocking for mutations and `Safe` verdicts.
- **MP-EXT-001 — extension points require evidence.** Treat a package surface as closed unless a
  version-scoped vendor source, reviewed package contract, or approved observation establishes a
  supported extension point.
- **MP-AUTO-001 — transaction interaction is high risk.** New save-transaction automation on a
  package-owned or ownership-unknown object is `INCOMPLETE — NEEDS HUMAN` until package behavior,
  existing accessible automation, recursion/ordering risk, and the supported extension point are
  verified for the installed version.
- **MP-ABS-001 — non-observation is not absence.** A query that returns no accessible automation or
  dependency cannot establish that none exists. Absence requires complete enumeration, permission
  proof, pagination proof, and a current evidence policy.
- **MP-DRIFT-001 — reconcile source and org.** When versioned Knowledge, the metadata repository,
  and the reviewed org observation disagree, record `CONTESTED` or `SOURCE/ORG DRIFT`; never choose
  a convenient source or overwrite the prior claim automatically.
- **MP-REG-001 — package rules are registered, not improvised.** Package/component-specific rules
  must exist in the governed rule registry with an owner, source, scope, package version, and review
  date. No package-specific rules are verified in this generic repository until that registry is
  populated with real human-owned evidence.
- **MP-UNKNOWN-001 — fail closed.** An unclassified package component may be investigated and a
  design may be drafted, but it cannot receive `Safe` for a mutation until its ownership, risk
  classification, supported extension point, and sources are reviewed.
