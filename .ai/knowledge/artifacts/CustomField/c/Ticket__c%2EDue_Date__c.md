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
  contentDigest: sha256:b72bc9c25a011009de46e543ef32828390b03dd186eb61e22591d9ea5bccad60
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
  sourceTreeDigest: sha256:f2fc828e316133af2f8fd87f3be7690c4cf2722190b7c86a35fc61e31364b924
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Due_Date__c.field-meta.xml
    sourceDigest: sha256:feb575f25ce04b7bf8cbbd6cab112beec8d9ab94084db02b8d019ef6861bf5da
subject:
  fullName: Ticket__c.Due_Date__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Due_Date__c
  label: Due Date
  object: Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  required: false
  type: DateTime
---

## Purpose

Records when the ticket is due to be dealt with, and is editable on the Request Item record page next to Status, Priority and Owner. It is optional in general, but Due_Date_Validation makes it mandatory the moment Status becomes Waiting or In Progress, blocking the save with the message that a Due Date is required for those statuses; a ticket in another status, such as the default New, can be saved without one. Nothing in the repository derives the value: the Category object carries an SLA Hours field, but no flow, formula or Apex here connects that to this date, so the deadline is whatever a user enters by hand.
