---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:600dc67749c4379848501d43d9f30f1b3b74f3702368d2a2e3fa3dd6ee81e82e
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:600dc67749c4379848501d43d9f30f1b3b74f3702368d2a2e3fa3dd6ee81e82e
  state: approved
limitations:
- Which flags are switched on is held in FeatureFlag__mdt records rather than in this
  class, so which behaviours the gate currently permits cannot be read from this source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:60410bca5cfcc2486c58f0206a460f6a4f939694c6d87229b58a1f13ab1331ca
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/FeatureFlags.cls
    sourceDigest: sha256:d436138e87e401c56a1744b24739cd98600270fe7fdf11ae34cbe532bfd85acc
subject:
  fullName: FeatureFlags
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - TestVisible
  apiVersion: '62.0'
  declarationKind: class
  description: Reads FeatureFlag__mdt (protected custom metadata) to gate package
    behavior. Protected metadata is invisible to subscribers, so these flags control
    internal, staged rollout of package logic only. * Test code can override any flag
    via setMock() without touching org data.
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: FeatureFlag__mdt
  - assurance: source-derived-heuristic
    kind: object-token
    target: FeatureFlag__mdt
  - assurance: source-derived-heuristic
    kind: object-token
    target: Is_Active__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: FeatureFlag__mdt.Is_Active__c
  sharingModel: with
  status: Active
---

## Purpose

FeatureFlags is the package's feature-flag gate: a caller names a flag and gets back whether that behaviour is switched on, answered from the FeatureFlag__mdt records, which are loaded once and cached for the rest of the transaction. A name with no matching record answers false, so code can be put behind a gate before the flag record exists without erroring. Its second entry point is the trigger framework's kill switch — TriggerHandler asks isTriggerBypassed with its own handler name before running, and a flag named Bypass_ plus that handler name, when active, makes the handler skip its work entirely. Because the underlying metadata is protected and therefore invisible to subscribers, the class comment scopes these flags to staged rollout of internal package logic rather than to subscriber-facing configuration. A test-only override lets tests force any flag's answer without touching org data, which is how the flag behaviour is exercised in tests.
