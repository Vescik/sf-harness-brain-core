---
description: Hard managed-package and closed-surface constraints. Apply before any design, implementation, test, or review that touches package objects, automation, pages, or data.
applyTo: "**"
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

## High-risk object register

### Invoice__c

- **MP-INV-001 — create automation prohibited.** Do not create a before-create or after-create
  record-triggered Flow on `Invoice__c`; it conflicts with package automation.
- **MP-INV-002 — update automation unverified.** An update-triggered Flow is allowed only when
  the condition `<TU_WSTAW_INVOICE_UPDATE_SAFE_CONDITION>` is supplied and verified. Until then,
  every proposal for an update-triggered Flow is `INCOMPLETE — NEEDS HUMAN`.
- **MP-INV-003 — independent action provisionally allowed.** A custom button that does not run in
  the record-save transaction may be proposed, but still requires Known Limitations review.
- Rule source: `<TU_WSTAW_INVOICE_RULE_SOURCE>`.
- Verified against package version: `<TU_WSTAW_PACKAGE_VERSION>`.
- Last verified: `<TU_WSTAW_RULE_VERIFICATION_DATE>`.

### Unclassified objects

The complete register is still human-owned:
`<TU_WSTAW_PELNA_LISTA_OBIEKTOW_WYSOKIEGO_RYZYKA>`.

- **MP-UNKNOWN-001 — fail closed.** A package object not yet classified may be investigated and a
  design may be drafted, but it cannot receive a `Safe` verdict for new save-transaction
  automation until a human confirms its risk classification and source.
