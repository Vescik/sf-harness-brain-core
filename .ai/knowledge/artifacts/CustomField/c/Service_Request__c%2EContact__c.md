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
  contentDigest: sha256:b4a41b39cc9bf05e047031fe9de3ed1b804f11cd113213dac48b8dae0f9c219e
  state: draft
limitations:
- No code, flow, or validation rule in this repository reads, defaults, or requires
  this field, so whatever populates it in practice is not visible in source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:0c6e23820b637f5aa927a42ec87eb25f9e8dfe5e5284bbee1496ec10802fbc47
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Contact__c.field-meta.xml
    sourceDigest: sha256:32fdbbabb69c7355f779dba92ca76b79f5e09241a4eb194587c2e8a82f72ea6b
subject:
  fullName: Service_Request__c.Contact__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Contact__c
  label: Contact
  object: Service_Request__c
  referenceTo:
  - Contact
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: relationship
    target: Contact
  relationshipLabel: Service Requests
  relationshipName: Service_Requests
  required: false
  trackHistory: false
  type: Lookup
---

## Purpose

Points at the person to deal with for a service request, sitting beside the account link as the individual-level counterpart to it. It is exposed only on the Service Request Lightning record page as an editable field, and no code, flow, or validation rule in this repo reads it, defaults it, or requires it. The lookup is unfiltered, so nothing here forces the chosen contact to belong to the account on the same request, and deleting that contact silently empties the field rather than stopping the delete.
