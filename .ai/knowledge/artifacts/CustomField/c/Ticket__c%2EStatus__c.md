---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:5fb62e6d5f45588955e05a4d87d6368df555699fba984ab9846744d2b55a76ba
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:5fb62e6d5f45588955e05a4d87d6368df555699fba984ab9846744d2b55a76ba
  state: approved
limitations:
- The shared Status value set is not committed to this repository, so the full list
  of stages a ticket can reach is not visible from source.
- The two validation rules are the only stage discipline the source shows, so whether
  any further ordering of stages is enforced elsewhere cannot be read from this repository.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:eb3baba74a9f616d3651e94a26d602d4badf64dabad8f31ee250562116674c47
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Status__c.field-meta.xml
    sourceDigest: sha256:c674c1169801a46884a1dd8f4eb3ef7bd5b1bd50e468f5951b1edc4fae4fab88
subject:
  fullName: Ticket__c.Status__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: '"New"'
  fullName: Status__c
  label: Status
  object: Ticket__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  - assurance: source-exact
    kind: uses-value-set
    target: Status
  required: false
  type: Picklist
  valueSetName: Status
---

## Purpose

Status__c carries the lifecycle stage of a ticket, opening at New and drawing its allowed stages from a shared restricted value set named Status that Service_Request__c and Service_Task__c also bind to; that value set is not committed to this repo, so the full list of stages a ticket can reach is not visible from source. Two active validation rules on Ticket__c use it as the gate for leaving a stage: Comment_Validation refuses a save that sets the ticket to Closed while its rolled-up comment count is zero, and Due_Date_Validation refuses Waiting or In Progress while Due Date is blank. The Request Item record page exposes the field as freely editable with no ordering enforced in the page itself, and no Apex, trigger, or flow in this repo reads or writes it, so those two rules are the only stage discipline the source shows.
