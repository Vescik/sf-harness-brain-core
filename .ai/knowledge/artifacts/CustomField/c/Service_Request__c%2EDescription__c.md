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
  contentDigest: sha256:633cef969b51b7096e1d3c3a928799fad650d24e97ca11064b4921e6b9771b97
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
  sourceTreeDigest: sha256:b81865dc728631311e175af1a62ea266e13005fd92394bb3464a0707297f1d55
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Description__c.field-meta.xml
    sourceDigest: sha256:f5b928b33917997e8c4cbea3a438e3b7ec563aa54269f31bd5ba7e55e13103c3
subject:
  fullName: Service_Request__c.Description__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Description__c
  label: Description
  length: 32768
  object: Service_Request__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  trackHistory: false
  type: LongTextArea
---

## Purpose

Holds the free-text account of what the requester wants done, the only narrative field on a service request. The Service Request Lightning record page renders it as a short multi-line box near the top of the detail column, directly under the service being requested, and leaves it optional. No automation in this repo reads it, and neither the field nor the object states what it should contain, so the expected content is left entirely to whoever types it.
