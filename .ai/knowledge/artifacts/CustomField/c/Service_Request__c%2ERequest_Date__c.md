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
  contentDigest: sha256:61a68fb422341df76b9cd3e7b51323bcecd975f10b66553760e8515effa145ae
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
  sourceTreeDigest: sha256:09ea0ac0acc54a42fa46ce9f43fba3b4257ee9096b87a355d5b1a84a6396f230
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Request_Date__c.field-meta.xml
    sourceDigest: sha256:b74f9ed5da79d04e70d71b0639babc640cac8ea85f4f774f418160d108ea5cd2
subject:
  fullName: Service_Request__c.Request_Date__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Request_Date__c
  label: Request Date
  object: Service_Request__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  required: true
  trackHistory: false
  type: Date
---

## Purpose

Carries the date a service request is dated from, and is one of only three values on the object the platform makes mandatory, alongside Request Status and Request Priority. The Service Request Record Lightning page marks it required a second time, and the metadata sets no default, so the value is typed by whoever creates the record rather than stamped automatically at insert. No Apex, flow, or validation rule in this repo reads it, compares it with Due Date, or confines it to the past, so the source shows nothing that consumes the value and nothing that constrains what a user may enter.
