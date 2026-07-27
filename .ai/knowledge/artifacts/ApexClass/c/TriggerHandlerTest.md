---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:c431ff23f057121b6d3cc4e526e93a6e21b7048d16383225c4421c8dcb379963
  state: draft
limitations: []
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:d550ef7caaba32801a8203c5022e4c7525df6497c73566a0fdea4401ea9a7e10
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/TriggerHandlerTest.cls
    sourceDigest: sha256:b6fd963cb021c7bc3f7c7a4b6b3544b862e274068ed0e537c1ec8836979b6710
subject:
  fullName: TriggerHandlerTest
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - IsTest
  apiVersion: '62.0'
  declarationKind: class
  dmlOperations:
  - insert
  - update
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TestHandler
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TriggerHandler
  sharingModel: omitted
  status: Active
---

## Purpose

Pins the dispatch and guard behaviour of the TriggerHandler base class using a private inner subclass that counts how often each context hook fires. It asserts that a handler put into a simulated before-insert context routes to beforeInsert exactly once, that a handler name registered through the static bypass API makes run do nothing while isBypassed reports true, that exceeding a configured maximum loop count raises TriggerHandlerException, and that running with no trigger context at all raises the same exception. The tests drive the handler through its test-visible context setter rather than through a real trigger, so they cover the dispatcher and its in-memory guards but leave the FeatureFlags and TriggerBypass bypass paths that validateRun also consults unpinned.
