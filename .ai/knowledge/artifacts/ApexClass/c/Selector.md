---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:7e4508c00a1f566c6fb2e2d4e06a7b100b88139ac43cd0170a78b5b22667ff2f
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:7e4508c00a1f566c6fb2e2d4e06a7b100b88139ac43cd0170a78b5b22667ff2f
  state: approved
limitations:
- The system-mode counterpart method the class header describes is not defined here,
  so how the package's rare system-mode reads are performed cannot be read from this
  class.
- This repository contains no subclass of Selector, so what a real selector declares
  and queries is not visible from the source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:f7cc2038a186269aa94539ec39da7b38d511f9ec6d50d43b06818959581b1c25
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/Selector.cls
    sourceDigest: sha256:9199d1a01a5361944963c7b95d8ececaadb124ca6750f2b479dc70d61e576c14
subject:
  fullName: Selector
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '62.0'
  declarationKind: class
  description: Abstract base for all selectors. Concrete selectors declare their SObjectType
    and default field list; the base provides common, bulk-safe query helpers. ALL
    SOQL in the package lives in selectors, and every query runs WITH USER_MODE so
    CRUD/FLS is enforced by the platform. * A selectById(...)/selectByIdSystem(...)
    pair documents the rare system-mode reads.
  kind: ApexClass
  sharingModel: with
  status: Active
---

## Purpose

Selector is the query layer of this framework: a concrete selector declares only the object it reads and the fields it wants, and this base assembles the SOQL text around them so no subclass hand-writes a query string. Every read is executed through Database.queryWithBinds at AccessLevel.USER_MODE, which pushes CRUD and field-level security enforcement onto the platform instead of onto each caller, and Id is appended to the projection when a subclass leaves it out. Alongside a by-Id read, it offers protected helpers that let a subclass supply its own WHERE clause with bind variables, and optionally an ORDER BY and a row cap, while still reusing the declared field list and the user-mode enforcement. The class header states the package convention that all SOQL lives in selectors and that a system-mode counterpart method documents the rare exceptions, but no system-mode method is defined here and this repository contains no subclass of Selector, so what a real selector looks like is not visible from the source.
