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
  contentDigest: sha256:edc0ff23c15d5f01fe565ef0a6d01b1f220f373f77991b8d6e9fd8ea78688e82
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
  sourceTreeDigest: sha256:919e6d5b3ce139db977530b0b296d5f031e9176357df39d904447286c618fe4a
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/fields/Source__c.field-meta.xml
    sourceDigest: sha256:6baa0b27ae16d7c925136b0b7fb1fd9c4722cfee2086af7bae9b0768827d40b4
subject:
  fullName: LogEntry__c.Source__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Originating class or component name.
  externalId: false
  fullName: Source__c
  label: Source
  length: 255
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

Names the class or component that emitted a log row, and is the practical grouping key for pulling one component's diagnostics out of the log table. Every Logger entry point takes it as the caller's first argument and stores it verbatim; Logger never derives it from the running stack, so it is only as accurate as the string the caller chose to pass. Both LoggerTest and UnitOfWorkTest filter their queries on it to isolate the rows they just wrote, which is the same way it would be used to read real diagnostics back. Nothing in the source constrains the value to a real class name.
