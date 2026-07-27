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
  contentDigest: sha256:097420818b9f03835512c5a4cff477e2ae964f8936435384197833dc48bc2ee7
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
  sourceTreeDigest: sha256:944a101346b050e01e41909fdd438e2ce972cc1c1170282da53546983973e153
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Request_Priority__c.field-meta.xml
    sourceDigest: sha256:8b22202a2627892fd5885c3504aec1b1e9257b6a1781ecbfe5717daa06ab4fd6
subject:
  fullName: Service_Request__c.Request_Priority__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Request_Priority__c
  label: Request Priority
  object: Service_Request__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: uses-value-set
    target: Priority
  required: true
  trackHistory: false
  type: Picklist
  valueSetName: Priority
---

## Purpose

Records how urgent a service request is, chosen from a restricted, org-wide Priority value set that is not defined in this repo, so the options a user can actually pick are not visible from the source here. It is mandatory, and the Service Request Record Lightning page marks it required as well, so no request is saved without one. Despite that, nothing in this package acts on the value: there are no triggers or Apex classes here at all, no validation rule mentions it, and the single flow over this object branches only on Request Status. Whether priority is meant to drive routing, queue ordering, or a response target is not something the source shows.
