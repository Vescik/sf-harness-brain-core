---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:0facfa57dbcc699010ded3a5eab0a69ba403be37bac843126f64ba7366d97841
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:0facfa57dbcc699010ded3a5eab0a69ba403be37bac843126f64ba7366d97841
  state: approved
limitations:
- All three tests run off the mock map, so this entry cannot establish that the real
  metadata path — cache population and the active check on the record — behaves as
  FeatureFlags describes.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:cc68b426887556bcf6c7b55284fe03f90a87841874061a3b4772d09658d1f569
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/FeatureFlagsTest.cls
    sourceDigest: sha256:bb414f68f82e1ecb2a59cf501a7661d23c397d4026898541bb5378c718c6a212
subject:
  fullName: FeatureFlagsTest
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - IsTest
  apiVersion: '62.0'
  declarationKind: class
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: FeatureFlags
  sharingModel: omitted
  status: Active
---

## Purpose

Pins the three behaviours of FeatureFlags that its callers depend on: that a mocked answer wins over whatever the metadata would say, in both the true and the false direction; that an unrecognised flag name comes back false rather than failing, which is what makes it safe to gate code ahead of the flag record; and that asking whether a handler is bypassed resolves to the Bypass_ prefixed flag for that handler name. All three run entirely off the mock map, so the tests never insert or read org data and stay valid whatever FeatureFlag__mdt records are deployed. The consequence is that the real metadata path — cache population and the active check on the record — is not exercised here.
