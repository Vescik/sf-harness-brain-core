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
  contentDigest: sha256:578ae49b835da3bb96599ac5d5ff535961e02aeae492278af082b3566e1411c5
  state: draft
limitations:
- The only reader in this repository is a flow stored as an invalid draft that never
  writes the value back, so what this field drives at runtime cannot be established
  from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ba6e96a543a5fe291e3a5e159e76c4e435d403912e5c80d8237e075d41a1284f
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Category__c/fields/DefaultPriority__c.field-meta.xml
    sourceDigest: sha256:41497b85ed9b0722db231b67e179984102041d4e2d4430d32856cc6030393043
subject:
  fullName: Category__c.DefaultPriority__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: '"p_1"'
  fullName: DefaultPriority__c
  label: DefaultPriority
  object: Category__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Category__c
  - assurance: source-exact
    kind: uses-value-set
    target: Priority
  required: false
  type: Picklist
  valueSetName: Priority
---

## Purpose

On a Category record this carries the priority that the ticket-creation automation treats as the fallback when a new ticket arrives without one of its own, and it draws on the same restricted Priority value set as the Ticket priority field, so the two values are directly interchangeable. The only reader in this repository is the Ticket Update flow, which on ticket creation branches when the incoming priority is blank, looks up a Category record, and pulls this value into a flow variable. That flow never puts the value back onto the ticket, because its update step references a field that does not resolve and the flow is stored as an invalid draft, so the field currently informs nothing that runs. No record page, validation rule, formula, or Apex class in the repository reads it either.
