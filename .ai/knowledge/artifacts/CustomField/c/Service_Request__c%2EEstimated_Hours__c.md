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
  contentDigest: sha256:f27b17d9ddd7efb8c9f37f6918d1bdc57635c3a0e701c8a7cf93dd42042ad639
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
  sourceTreeDigest: sha256:67cf20960d65e82d6aa0132554e8580ba5ca12c733a3f50ca2f5fc38ffbfe1c5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Estimated_Hours__c.field-meta.xml
    sourceDigest: sha256:744a8dd82ef3e4467a9c137ea0018994599c7da9fbcc278c4eec879526a72ee0
subject:
  fullName: Service_Request__c.Estimated_Hours__c
  metadataType: CustomField
  namespace: null
typeFacts:
  externalId: false
  fullName: Estimated_Hours__c
  label: Estimated Hours
  object: Service_Request__c
  precision: 2
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  required: false
  scale: 0
  trackHistory: false
  type: Number
  unique: false
---

## Purpose

Captures the up-front effort estimate a user types onto a service request, before any work is logged against it. It appears on the Service Request Record Lightning page in the Information section as an optional editable field, with no default and no floor or ceiling enforced. Actual effort is recorded elsewhere, on the request's master-detail children, but this package defines no roll-up summary, Apex, or flow that totals those hours or compares them with the estimate, so nothing here consumes the value once it is entered. Whether the estimate is meant for scheduling, quoting, or variance reporting is not something the source shows.
