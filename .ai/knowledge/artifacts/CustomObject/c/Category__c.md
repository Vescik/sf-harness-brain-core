---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:166ad1c278bf3894ee700c7c66dd62128215b5fd331ce892b0d0c726493a70c9
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:166ad1c278bf3894ee700c7c66dd62128215b5fd331ce892b0d0c726493a70c9
  state: approved
limitations:
- Nothing in this repository reads the SLA hours value, so whatever would enforce
  or report on an SLA is not visible from source.
- The object carries no description and has reporting and search disabled, so the
  source gives no indication of who is meant to maintain these records.
- The source does not explain why the Category field on Ticket points at the standard
  ProductCategory object rather than at this one, so the intended join between the
  two cannot be read here.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:211fd89911e8f2d8ef6fa750e54e048ec6b965ad0badc471dc1e3dea32a0c67f
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Category__c/Category__c.object-meta.xml
    sourceDigest: sha256:9a4fb4ce6e63500e9154c931e7daf3e208d4f134a095fdfce2a967b6264dbeb3
subject:
  fullName: Category__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  enableActivities: false
  enableFeeds: false
  enableHistory: false
  enableReports: false
  enableSearch: false
  externalSharingModel: Private
  label: Category
  nameField:
    label: Category Name
    type: Text
  objectKind: customObject
  pluralLabel: Category
  sharingModel: ReadWrite
---

## Purpose

One record is a ticket category holding a default priority and an SLA duration expressed in hours. The only consumer in this repo is the Ticket Update flow, which runs on Ticket creation when Priority is blank, looks up a Category record and reads its default priority into a flow variable; nothing anywhere in the repo reads the SLA hours value, so whatever would enforce or report on an SLA is not visible from source. The link between this object and tickets is a lookup pointing from Category to a single Ticket, while the Category field on Ticket points at the standard ProductCategory object rather than at this one, so the two are not joined by the field whose name implies it and the source does not explain the split. The object carries no description and has reporting and search disabled, so the source gives no indication of who is meant to maintain these records.
