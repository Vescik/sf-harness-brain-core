---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:d90147b7179260cd2a954f51d921778ce49689b496f6245fc4fbf713df09b8b9
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:d90147b7179260cd2a954f51d921778ce49689b496f6245fc4fbf713df09b8b9
  state: approved
limitations:
- No Apex, flow, validation rule or rollup in this repository reads the field, so
  whether anything outside repository source depends on its content is not visible
  here.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:328cae8c89b5bcc82e842ba69faf032f94df085ed21dfc32848e36a0397863b2
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Subject__c.field-meta.xml
    sourceDigest: sha256:3e327e7fd233c241db73b89a2cfce227df9c2a6e3d732b18b0d5b585099ff254
subject:
  fullName: Ticket__c.Subject__c
  metadataType: CustomField
  namespace: null
typeFacts:
  externalId: false
  fullName: Subject__c
  label: Subject
  length: 30
  object: Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  required: false
  type: Text
  unique: false
---

## Purpose

Subject__c holds a short, human-readable summary of what a ticket is about, which is the only meaningful identifier a person has for the record, since Ticket__c names itself with a system-assigned auto number in the TKT- series. It is rendered as an editable field on the Request Item record page beside Category and the required Description, and the page marks it optional while Description is the field a user must fill, so the longer narrative belongs there rather than here. No Apex, flow, validation rule, or rollup in this repo reads Subject__c, so nothing downstream depends on its content or on it being populated at all.
