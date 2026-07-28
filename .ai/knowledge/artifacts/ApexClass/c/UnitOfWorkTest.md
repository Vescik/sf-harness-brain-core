---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:91513d4fc776c6c47b997ac40ac3a6bc84da180351e08cd6cba75b1f0bc66874
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:91513d4fc776c6c47b997ac40ac3a6bc84da180351e08cd6cba75b1f0bc66874
  state: approved
limitations:
- Every case builds the unit of work through the system-mode factory, so this entry
  cannot establish how the default user-mode CRUD and field-level enforcement path
  behaves.
- The savepoint rollback on a failed commit and the publish-after-commit event handling
  are not exercised here, so this entry cannot establish those two behaviours of commitWork.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:96cd5389e216010c2a0f906a79209a9d6bbd0ae565b544a8fdd0da09a463b5ee
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/UnitOfWorkTest.cls
    sourceDigest: sha256:6bd4d834cbdfcaeb3aa5c9cac7fc0837897aabeed60feb383316f780592e4a51
subject:
  fullName: UnitOfWorkTest
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
  dmlTargets:
    LogEntry__c:
    - insert
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: dml-object
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: UnitOfWork
  - assurance: source-derived-heuristic
    kind: object-token
    target: Level__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Message__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Source__c
  - assurance: source-derived-heuristic
    kind: queries-object
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: soql-field
    target: LogEntry__c.Id
  - assurance: source-derived-heuristic
    kind: soql-field
    target: LogEntry__c.Source__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: LogEntry__c.Id
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: LogEntry__c.Message__c
  sharingModel: omitted
  soqlObjects:
  - LogEntry__c
  status: Active
---

## Purpose

Pins the commit behaviour of UnitOfWork using LogEntry__c as a stand-in object: that records registered as new are inserted and a record registered as dirty is written back, that a record whose type was never declared in the insert order is still inserted, and that a record registered as deleted is removed. Every case builds the unit of work through the system-mode factory, so the user-mode CRUD and field-level enforcement that is the default construction path is never exercised. Nothing here covers the savepoint rollback on a failed commit or the publish-after-commit event handling, so those two behaviours of commitWork remain unpinned.
