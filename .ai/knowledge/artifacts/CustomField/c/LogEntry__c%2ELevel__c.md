---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:1aead2a8966e972fc7d36e18d66ee84ea2810f874e928947eac9862fc8d958de
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:1aead2a8966e972fc7d36e18d66ee84ea2810f874e928947eac9862fc8d958de
  state: approved
limitations: []
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:e2598fc5bc28e365a4d5527df521626425181d78015269e6c294bae482662e5e
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/LogEntry__c/fields/Level__c.field-meta.xml
    sourceDigest: sha256:5df00805662145f3c7a2b53b0d6adacf50295c6ab9668ac3edc3db29a34e46c9
subject:
  fullName: LogEntry__c.Level__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Severity of the log entry.
  fullName: Level__c
  label: Level
  object: LogEntry__c
  picklistRestricted: true
  picklistSorted: false
  picklistValueCount: 4
  picklistValues:
  - default: false
    fullName: DEBUG
    label: DEBUG
  - default: true
    fullName: INFO
    label: INFO
  - default: false
    fullName: WARN
    label: WARN
  - default: false
    fullName: ERROR
    label: ERROR
  references:
  - assurance: source-exact
    kind: belongs-to
    target: LogEntry__c
  required: false
  type: Picklist
---

## Purpose

Records which severity band a log row was written at, and is what separates routine tracing from something worth investigating in the log table. Logger sets it from the name of its own Level enum, and the picklist is restricted to exactly the four values that enum declares, so the enum and the picklist have to be kept in step with each other. INFO is marked the default, which only matters for rows created outside Logger, since every Logger entry point supplies an explicit level. LoggerTest pins that logging a caught exception lands here as ERROR, and UnitOfWorkTest sets it by hand purely to make its scratch rows insertable.
