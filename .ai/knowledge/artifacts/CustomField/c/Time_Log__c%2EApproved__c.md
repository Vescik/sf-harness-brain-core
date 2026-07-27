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
  contentDigest: sha256:6ba572d80b780f9de80870b99985f6895d4b39076e12a64a70ef6ef54ffce940
  state: draft
limitations:
- No Apex, flow, validation rule, record page, or permission set in this repository
  touches the field, so who may approve an entry, at what point, and what an approval
  unlocks downstream cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:4b16a40c33e6a2cf79adbf498c5bb2776446a85a779b264a5dfb72b9866a5784
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Approved__c.field-meta.xml
    sourceDigest: sha256:156110c92395e049180aba6a813d350583b64d24717e4d20bd6f884c1728e1cc
subject:
  fullName: Time_Log__c.Approved__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: 'false'
  fullName: Approved__c
  label: Approved
  object: Time_Log__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  trackHistory: false
  type: Checkbox
---

## Purpose

Approved__c is the sign-off marker on a time log entry, and every new record starts unapproved. Nothing in this repo sets, clears, or reads it: no Apex, flow, validation rule, record page, or permission set touches the field, so who is entitled to approve an entry, at what point, and what an approval unlocks downstream are all invisible from source. The field also opts out of history tracking even though Time_Log__c has history tracking switched on at the object level, so a flip of this flag leaves no field-level audit trail in the configuration as committed here.
