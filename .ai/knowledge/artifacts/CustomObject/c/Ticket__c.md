---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:c8761b187e1bc0375d4a817dda3ed5d1d7c975ce6cd70a7f6c00f0d12155b8a8
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:c8761b187e1bc0375d4a817dda3ed5d1d7c975ce6cd70a7f6c00f0d12155b8a8
  state: approved
limitations:
- Source shows that the category lookup targets the standard ProductCategory object
  rather than this repository's Category object and that the record page is labelled
  Request Item, but not whether either naming mismatch is intentional.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:d48f9f88353c263da69d45ba26d672789155e1fb8c3c69d9b43e04f76842d04f
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/Ticket__c.object-meta.xml
    sourceDigest: sha256:80f52413deb030d25bee41b30b2b62766247a12584822e3b8a7e379d0c55d269
subject:
  fullName: Ticket__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  enableActivities: false
  enableFeeds: false
  enableHistory: false
  enableReports: false
  enableSearch: true
  externalSharingModel: Private
  label: Ticket
  nameField:
    displayFormat: TKT-{00000}
    label: Ticket Name
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Tickets
  sharingModel: ReadWrite
---

## Purpose

A Ticket record is one logged request, carrying a short subject, a required description, a status and a priority taken from shared restricted value sets, an optional due date, and a category link. It is the parent of this small model: Ticket Comment rows hang off it in master-detail and are totalled back onto it as a comment count, and Category records point at it through their own Ticket lookup. Two active validation rules constrain its lifecycle, blocking a move to Closed while it has no comments and requiring a due date once it is Waiting or In Progress. The Ticket Update flow runs after a ticket is created and reads a category default when the priority was left blank, but it is stored as an invalid draft, so the repository shows that intent without a working path that writes the value. Two naming details are worth flagging rather than guessing at: the category lookup on Ticket targets the standard ProductCategory object rather than the custom Category object in this repository, and the record view is overridden by a Lightning page labelled Request Item while the object itself is labelled Ticket.
