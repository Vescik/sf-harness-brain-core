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
  contentDigest: sha256:55b1a040371c61455e57d6cbb41505a30d7fa347a6bd760914d5604508a81204
  state: draft
limitations:
- The bypass list is admin-editable data on a hierarchy custom setting rather than
  packaged configuration, so which handlers are actually bypassed in any org cannot
  be read from this repository.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:650b32c0151e0eff8095b145b5bcde8094e522dd6d61b51af4b9ac59df953cf5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/TriggerBypass__c/fields/Bypassed_Handlers__c.field-meta.xml
    sourceDigest: sha256:603f989df7aa43047d95a30078ffb2c7d9c7be2f7b1a26243be3e1dc70c4f1df
subject:
  fullName: TriggerBypass__c.Bypassed_Handlers__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Semicolon-delimited list of trigger handler names to bypass.
  externalId: false
  fullName: Bypassed_Handlers__c
  label: Bypassed Handlers
  length: 255
  object: TriggerBypass__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: TriggerBypass__c
  required: false
  type: Text
  unique: false
---

## Purpose

This field names the individual trigger handlers that should stop running for the current user, profile, or org, holding them as one semicolon-delimited string rather than as separate records. The TriggerBypass class splits the stored value on semicolons and compares each trimmed entry case-insensitively against the handler name it is asked about, treating a blank value as no bypass at all. TriggerHandler consults TriggerBypass as the last of three gates before dispatching a handler, after its own in-memory bypass set and the FeatureFlags check, so a name listed here suppresses that handler's work at runtime. Because the value lives on a hierarchy custom setting it is admin-editable data rather than packaged configuration — the class comment gives silencing automation during a bulk data load as the motivating case — and nothing validates the names, so a typo or a renamed handler simply never matches and the handler keeps running.
