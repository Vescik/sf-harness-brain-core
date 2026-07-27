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
  contentDigest: sha256:975e7d3173efe449dff932c44d5790b6530e67b15f127bece8d1da4d68f85d56
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
  sourceTreeDigest: sha256:0b7aa161aae11fdd1e81258aa96ac33fc8182d57284aac992484c5c78e077537
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket_Comment__c/fields/Body__c.field-meta.xml
    sourceDigest: sha256:dcda618a24b4bc8956f83805c34e1aacb9dcf3f581cef8610db4c55bdcda470c
subject:
  fullName: Ticket_Comment__c.Body__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Comment
  externalId: false
  fullName: Body__c
  label: Body
  length: 255
  object: Ticket_Comment__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket_Comment__c
  required: false
  type: Text
  unique: false
---

## Purpose

Holds the text of a single comment on a Ticket, described in the metadata only as "Comment". It is capped at 255 characters and is not required, so a comment row can be saved with nothing written in it and anything longer than a short remark cannot be stored in one comment. The Comment Count roll-up on Ticket counts comment rows whether or not they carry any text, so that number reflects how many records exist rather than how much was actually written. Nothing in the repo reads or writes this field, so any interface or process that captures and renders comment text lives outside this repo.
