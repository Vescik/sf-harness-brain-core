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
  contentDigest: sha256:1103e60d556af7d12ec4efeee6adc39d52eaca3d78aee6ec3abb8fece8e2241f
  state: draft
limitations:
- Nothing in this repository sets, clears, or validates the assignment, so how a technician
  is actually chosen in practice cannot be established from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:90505712997279a89819135d68ab1b6051623c57c94ac2afe7a3d5d7cae309c5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Assigned_Technician__c.field-meta.xml
    sourceDigest: sha256:18197ea4f26508a25c1ade92c7d46b61c9b5181e342a5adc8c81bd6635fc6ece
subject:
  fullName: Service_Request__c.Assigned_Technician__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Assigned_Technician__c
  label: Assigned Technician
  object: Service_Request__c
  referenceTo:
  - User
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: relationship
    target: User
  relationshipName: Service_Requests
  required: false
  trackHistory: false
  type: Lookup
---

## Purpose

Records which internal user is responsible for the request as a whole. It is separate from the record owner, which the Lightning record page shows in its own section, and separate again from the technician named on each Service Task and Time Log, so the person assigned to the request is not automatically the person who does or logs the work. Nothing in this repo sets, clears, or validates it: it is filled in by hand on the record page, the status flow does not look at it, and no rule requires an assignment before a request moves out of its starting status.
