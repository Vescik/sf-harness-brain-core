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
  contentDigest: sha256:bb8d5fe50fe729f69a8124e2efcf0dc48a56b7d049f23d227da6ac76ff63c8a4
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
  sourceTreeDigest: sha256:3f81c88ec37f42ca9815359da404d790133e13639a64c28da5dafb7dd9285e53
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/fields/Message__c.field-meta.xml
    sourceDigest: sha256:88ced4c5622d92d60eef1ddd9fab61b27cdaff24cea226b9bb4569f1d785d564
subject:
  fullName: LogEntry__c.Message__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Log message body.
  fullName: Message__c
  label: Message
  length: 32768
  object: LogEntry__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: LogEntry__c
  type: LongTextArea
---

## Purpose

Carries the human-readable body of a log line, whatever text the caller handed to Logger. When Logger is asked to log an exception rather than a string, it composes the value from the exception's type name and message, and LoggerTest pins that the thrown text is still findable in the stored row. Logger truncates the value before assigning it, stopping short of the field's declared capacity. UnitOfWorkTest also writes it, but only as filler on throwaway rows used to exercise unit-of-work registration.
