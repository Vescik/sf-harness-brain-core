---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:22f39574533844bea90a26c1d99d20f4c5aa135ca4dec1fabc8fed98af35fbc7
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:22f39574533844bea90a26c1d99d20f4c5aa135ca4dec1fabc8fed98af35fbc7
  state: approved
limitations:
- This test substitutes the setting through the test-visible override, so it cannot
  establish that case-insensitive handler-name matching or the real hierarchy custom
  setting lookup behave as described.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:e41c75203f887ad1134b8ccb906b9ffcac485ac67d20746bda1cdc79cd80684c
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/TriggerBypassTest.cls
    sourceDigest: sha256:b879b66469e52057afd4ebeaee8c8adbac88aeff1478171a1823b005731a172a
subject:
  fullName: TriggerBypassTest
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
    target: TriggerBypass
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TriggerBypass__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Bypassed_Handlers__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Disable_All__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: TriggerBypass__c
  sharingModel: omitted
  status: Active
---

## Purpose

This test pins the three branches of the bypass decision by substituting the setting through the test-visible override instead of relying on org data. It fixes the default: with no setting present, no handler is bypassed. It fixes the master switch: when the disable-all flag is on, any handler name reports as bypassed regardless of the named list. It fixes the named list: a handler in the semicolon-delimited list is bypassed while one absent from it is not, and because the list under test is written with a space after the separator, it also pins that surrounding whitespace around a name is tolerated. Case-insensitive matching and the real hierarchy-setting lookup are not covered here.
