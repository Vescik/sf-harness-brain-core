---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:cbaa96db62ace24df654af8f59fa939265b58ff7d5ae8444c806ca48aa0217b1
  state: draft
limitations:
- The only reads of the object in this repository are in tests, so how these rows
  are consumed operationally and how long they are retained cannot be read from source.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:aaeabfd4a4538613acae68023f0f5df044c09b4e0c1ac31bd9a99218e8278fad
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/LogEntry__c.object-meta.xml
    sourceDigest: sha256:c0388382da95db0b04eaba3498fdf001b2a6d69e9d1ecbd5148e9da5ff684d1c
subject:
  fullName: LogEntry__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  description: Structured diagnostic log entries written by the Logger service. Internal
    package telemetry.
  enableActivities: false
  enableFeeds: false
  enableHistory: false
  enableReports: true
  enableSearch: false
  externalSharingModel: Private
  label: Log Entry
  nameField:
    displayFormat: LOG-{0000000000}
    label: Log Entry Number
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Log Entries
  sharingModel: Private
---

## Purpose

One record is a single diagnostic log line written by the Logger service, carrying a severity, the class or component that emitted it, the message, an optional Apex stack trace, and the request id that ties together every entry produced within one transaction. Call sites never insert a row directly; Logger buffers entries and writes them in a single DML when flushed, in system mode and with its own DML errors swallowed, so this table is a side channel that cannot make the transaction being logged fail, and a transaction that never reaches a flush leaves nothing behind. The only reads of the object in this repo are in LoggerTest and UnitOfWorkTest, which query it to assert what was logged, so how these rows are consumed operationally and how long they are kept is not visible from source.
