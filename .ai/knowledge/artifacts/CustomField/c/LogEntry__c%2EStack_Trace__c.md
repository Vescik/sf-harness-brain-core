---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:20bf85500298f7084b623ce7786edaa780b4cb947c4b088fe961f442c232a74d
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:20bf85500298f7084b623ce7786edaa780b4cb947c4b088fe961f442c232a74d
  state: approved
limitations:
- No test in this repository asserts on the trace contents, so what a stored stack
  trace actually holds cannot be established from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:1a065e01054fd37462e5a7f100278fb4c831c18dddec639f8e5a0fdad752c411
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/fields/Stack_Trace__c.field-meta.xml
    sourceDigest: sha256:f9ad86787edf65c6aeb57187fdf784136e5f37627c8342947685bb620a2520f3
subject:
  fullName: LogEntry__c.Stack_Trace__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Captured Apex stack trace, when available.
  fullName: Stack_Trace__c
  label: Stack Trace
  length: 32768
  object: LogEntry__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: LogEntry__c
  type: LongTextArea
---

## Purpose

Holds the Apex stack trace captured when a log row originated from a caught exception. Only one Logger path fills it — the error entry point that accepts an Exception, which stores the exception's stack trace string; every other path passes nothing, so a populated value is what distinguishes an exception log from a hand-written message. Logger truncates the trace before assigning it, stopping short of the field's declared capacity. LoggerTest selects this field on the exception path but asserts on the level and message instead, so the trace contents themselves are not pinned by any test.
