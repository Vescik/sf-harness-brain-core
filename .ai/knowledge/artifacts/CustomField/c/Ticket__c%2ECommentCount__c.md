---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:3f20cd635bd191a7a277c3da50edbe4f4540497744dede473b00275b9811e7db
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:3f20cd635bd191a7a277c3da50edbe4f4540497744dede473b00275b9811e7db
  state: approved
limitations: []
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:64c039772d665a8e975b9c794ce4085d44c55d80364bd20335efbdeb0afeb950
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/CommentCount__c.field-meta.xml
    sourceDigest: sha256:f631f678915eae4267acc108c83a9c02f3b0242db66444a5a7b900e5a4152d15
subject:
  fullName: Ticket__c.CommentCount__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: CommentCount__c
  label: CommentCount
  object: Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  - assurance: source-exact
    kind: references-field
    target: Ticket_Comment__c.Ticket__c
  summaryForeignKey: Ticket_Comment__c.Ticket__c
  summaryOperation: count
  type: Summary
---

## Purpose

Counts how many Ticket Comment records hang off a ticket, rolled up through the comment's master-detail link to its ticket. Its one consumer in the repository is the Comment_Validation rule, which refuses to save a ticket whose Status is Closed while the count is still zero, telling the user that at least one comment is required before closing. The field is not placed on the Request Item record page, so the number is not surfaced to users there; in this codebase it exists to make the presence or absence of comments checkable from a formula.
