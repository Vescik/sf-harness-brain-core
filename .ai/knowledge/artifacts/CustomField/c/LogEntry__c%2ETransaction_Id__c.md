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
  contentDigest: sha256:d6ae6dd3fef6575ffe137fc03391ce249a0e40c6a87df7386abaf45d125dbe31
  state: draft
limitations: []
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:6592ca7d929838f90d69ca7f57261833bec0914c1ec95f492433d47c42272ffb
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/fields/Transaction_Id__c.field-meta.xml
    sourceDigest: sha256:f8b0e542f9d8c04d10281366213c55c1eee3e3809b398908067c25d5e5ef9dbf
subject:
  fullName: LogEntry__c.Transaction_Id__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Request id correlating all log entries in one transaction.
  externalId: true
  fullName: Transaction_Id__c
  label: Transaction Id
  length: 60
  object: LogEntry__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: LogEntry__c
  required: false
  type: Text
  unique: false
---

## Purpose

Stamps each log row with the request id of the transaction that produced it, so every entry Logger buffered and flushed in one execution shares a value and the whole transaction can be read back as a group rather than as scattered rows. Logger sets it on every entry it builds, with no involvement from the caller. It is marked as an external id but not unique, which is consistent with a value that repeats across all rows from the same transaction. No code in this repo queries or filters on it, so the correlation exists for whoever reads the log table rather than being consumed by the package itself.
