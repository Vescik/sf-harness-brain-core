---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:0cc296ebc82031e31dc35089a7f6f235bcf496e1e442161c31565f4ce1d7c0b4
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:0cc296ebc82031e31dc35089a7f6f235bcf496e1e442161c31565f4ce1d7c0b4
  state: approved
limitations:
- Nothing in this repository reads or writes this lookup, so what attaching a Category
  to a Ticket is meant to mean is not shown by the source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:9417351a4de71a4010d910b830feb2bbd4e33e1868d3486cbb52056ad8351747
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Category__c/fields/Ticket__c.field-meta.xml
    sourceDigest: sha256:99b57d687ffa05375563bb66ed16cb8a58e0a6fd39503f48a254ee2733ba7136
subject:
  fullName: Category__c.Ticket__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Ticket__c
  label: Ticket
  object: Category__c
  referenceTo:
  - Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Category__c
  - assurance: source-exact
    kind: relationship
    target: Ticket__c
  relationshipLabel: Category
  relationshipName: Category
  required: false
  type: Lookup
---

## Purpose

This lookup links a Category record to a single Ticket, and the direction matters: the reference lives on Category, so one Category row can name at most one Ticket while a Ticket can gather many Category rows beneath it in a related list. It is not the counterpart of the Category lookup that sits on Ticket, because that one targets the standard ProductCategory object, so the two similarly named fields describe unrelated links. Nothing in this repository reads or writes this field, as the Ticket Update flow reaches category data through the standard ProductCategory path instead and no Apex class, validation rule, or record page references it, so what attaching a Category to a Ticket is meant to mean is not shown by the source.
