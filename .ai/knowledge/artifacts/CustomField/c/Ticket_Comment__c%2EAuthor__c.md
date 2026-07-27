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
  contentDigest: sha256:4536c55fc8008ee7546134bfcb3e857d819128a6a00a272d3a37881569bba242
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
  sourceTreeDigest: sha256:b0377ad439bf831340a625f42664a4a7266c33cc493f661688aef04cd2b28d91
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket_Comment__c/fields/Author__c.field-meta.xml
    sourceDigest: sha256:d2f36a5e1245d0fe43f3fad03fd1ff5b1a0c69c83138f12ebfb48c1928f54db6
subject:
  fullName: Ticket_Comment__c.Author__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Author__c
  label: Author
  object: Ticket_Comment__c
  referenceTo:
  - User
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket_Comment__c
  - assurance: source-exact
    kind: relationship
    target: User
  relationshipName: Ticket_Comment
  required: false
  type: Lookup
---

## Purpose

Credits a User as the writer of a Ticket Comment. Nothing in the repo populates or checks it, so the value is whatever the writing process supplies, it is not guaranteed to match the record's own created-by user, and a comment can be saved with no author at all. Deleting the referenced User clears the link rather than blocking the delete, so an older comment can lose its attribution. No Apex, Flow, validation rule, layout or permission set in the repo reads it, so whether it drives display, notification or any access decision is not visible from source.
