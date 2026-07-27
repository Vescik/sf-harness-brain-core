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
  contentDigest: sha256:865b6a15a8cf8cdb9e0a8b81e72d7f9c3418f2dfd17b05de9f4468a88ec286e6
  state: draft
limitations:
- No component in this repository reads or aggregates the value, so any comparison
  of logged hours against Service_Request__c.Estimated_Hours__c happens outside this
  metadata and cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:33e6cc4567db3f28379868eea318a61f66e82d19b9fd027e9820652e452c8562
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Hours__c.field-meta.xml
    sourceDigest: sha256:3f4f201e06122ef8b0a9b9f75f0ca61f14fa23cd34d0dfc7715594fd366abc3c
subject:
  fullName: Time_Log__c.Hours__c
  metadataType: CustomField
  namespace: null
typeFacts:
  externalId: false
  fullName: Hours__c
  label: Hours
  object: Time_Log__c
  precision: 10
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  required: false
  scale: 0
  trackHistory: false
  type: Number
  unique: false
---

## Purpose

Hours__c records how much time was spent on the parent service request, and because it stores no fractional part, effort can only be logged in whole hours, ruling out half-hour and quarter-hour entries. Nothing in this repo aggregates or checks the value: there is no rollup summary on Service_Request__c over its Time_Log children, no Apex or flow that reads the field, and no validation rule rejecting a zero, a negative, or an implausibly large figure. Service_Request__c carries its own Estimated_Hours__c for the up-front estimate of the same work, but no component in this repo compares logged hours against it, so the comparison, if it happens, happens outside this metadata.
