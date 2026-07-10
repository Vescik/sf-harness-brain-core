---
applyTo: "**"
---

# Managed Package Constraints

Source: hard limitations imposed by the package vendor. **Top tier in the precedence
hierarchy** — overrides both Organization Principles and general Salesforce best practices
(see `.github/copilot-instructions.md`). These are constraints, not suggestions.

This file is **deliberately thin** (blueprint sections 3 and 7): it loads into every request
via `applyTo: "**"`, so it holds only (a) the general rule below and (b) the few broad,
object-level entries worth keeping always active. The growing, granular catalog of discovered
limitations (a specific closed VF page, a specific function) lives in
`.ai/knowledge/known-limitations.md` and is consulted on demand — do not let it accumulate here.

## General rule

Respect the discovered constraints of the package's closed surfaces. Before proposing any
change that touches package objects, pages or automation, **check
`.ai/knowledge/known-limitations.md`** for granular limitations affecting exactly what the
change touches.

## High-risk object register

<!-- Structure per blueprint section 7 — one block per high-risk object. -->

### Invoice__c

- Ryzyko: wysoki wolumen rekordow, duzo automatyzacji wewnatrz pakietu
- Zakazane: record-triggered Flow "before/after create" (koliduje z automatyzacja pakietu)
- Dozwolone: Flow "on update" pod warunkiem <TU_WSTAW>, custom button niezalezny od zapisu
  <!-- While <TU_WSTAW> is empty: the condition under which an on-update Flow is safe is
  unknown, so any proposed on-update Flow on Invoice__c must be treated as unverified and
  escalated to a human instead of approved. -->
- Zrodlo reguly: <TU_WSTAW: dokumentacja vendora / ustalone doswiadczalnie / wsparcie vendora>
  <!-- While empty: the rule's authority is untraceable — it cannot be re-verified after a
  package upgrade, so upgrades may silently invalidate it. -->

<TU_WSTAW_PELNA_LISTA_OBIEKTOW_WYSOKIEGO_RYZYKA>
<!-- Section-16 placeholder: Invoice__c is the only confirmed example. While the full list is
missing, agents have no always-active warning for any other high-risk package object — a
design or implementation touching one of them will not be flagged until the limitation is
discovered the hard way and cataloged. -->
