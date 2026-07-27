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
  contentDigest: sha256:155e8fd21ad57a67831400df5701318531a9e1f5421174a9051acff15cd82099
  state: draft
limitations:
- No Apex, Flow, validation rule or layout in the repository reads or writes this
  field, so whether it is meant to feed billing, capacity or reporting is not shown
  in source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:078e9a312b1b1cb3bc047d86936d46410d1898ec6020c9a13e0be6d75f63c6b5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Work_Hours__c.field-meta.xml
    sourceDigest: sha256:af855479469bb88800c1fc53ac5ab847b1a8c0ba1fb26eaaec6753cfaf130f87
subject:
  fullName: Service_Task__c.Work_Hours__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: 0
  externalId: false
  fullName: Work_Hours__c
  label: Work Hours
  object: Service_Task__c
  precision: 10
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  required: false
  scale: 0
  trackHistory: false
  type: Number
  unique: false
---

## Purpose

Holds the amount of time booked against a single Service Task, starting at zero on a new record. Only whole hours can be stored, so half-hour and quarter-hour effort cannot be represented here. Nothing aggregates it: the parent Service Request has an Estimated Hours field but no roll-up of the hours on its tasks, and the separate Time Log object records hours of its own alongside an approval checkbox, so this repo holds two unconnected places where time against a request is captured. No Apex, Flow, validation rule or layout in the repo reads or writes it, so whether it is meant to feed billing, capacity or reporting is not shown in source.
