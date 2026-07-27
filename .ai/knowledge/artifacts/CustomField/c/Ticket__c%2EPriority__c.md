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
  contentDigest: sha256:fee3bc1e97548d8763bd9b6af6f3778b06c6a943defa88078c53db7203bec1a6
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
  sourceTreeDigest: sha256:f3cfa8321088178b68ffeae38c38d140a6e39d865074ca7b5addf626f9d3e5cb
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Priority__c.field-meta.xml
    sourceDigest: sha256:6fe5e90817ae891162883bd4ea941273351f6ffc1300d47eca412853a003f25c
subject:
  fullName: Ticket__c.Priority__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: '"p_1"'
  fullName: Priority__c
  label: Priority
  object: Ticket__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  - assurance: source-exact
    kind: uses-value-set
    target: Priority
  required: false
  type: Picklist
  valueSetName: Priority
---

## Purpose

Carries the urgency assigned to a ticket, taken from a restricted Priority value set that is shared with the DefaultPriority field on the Category object, so a category's default and a ticket's own priority are expressed in the same vocabulary. That value set is not part of this repository, so the meaning and ordering of its codes cannot be read from the source here. The field is editable on the Request Item record page beside Status and Due Date. The Ticket Update flow is the only automation that touches it: on ticket creation it branches when the priority is blank, then looks up a category to read its default priority, but the update step writes to a field named null__NotFound and the flow is saved as InvalidDraft, so the source shows no working path that fills this field automatically.
