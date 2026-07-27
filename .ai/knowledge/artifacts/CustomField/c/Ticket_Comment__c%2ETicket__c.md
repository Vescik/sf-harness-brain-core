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
  contentDigest: sha256:9593706d8730d6f7d368c0345af322c6fd47616c338149ecde95e6887b8807dd
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
  sourceTreeDigest: sha256:3ec89c1c25b43fcef8930079e454b90d0816cbd5c00c298f4cdd82a2a6e7fa2c
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket_Comment__c/fields/Ticket__c.field-meta.xml
    sourceDigest: sha256:d568d78ad2ff4bf3cf78bbd143b619a6b0a1607c388cca288fbbad4d2292629f
subject:
  fullName: Ticket_Comment__c.Ticket__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Ticket__c
  label: Ticket
  object: Ticket_Comment__c
  referenceTo:
  - Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket_Comment__c
  - assurance: source-exact
    kind: relationship
    target: Ticket__c
  relationshipLabel: Ticket Comment
  relationshipName: Ticket_Comment
  relationshipOrder: 0
  reparentableMasterDetail: false
  type: MasterDetail
  writeRequiresMasterRead: false
---

## Purpose

The parent link that makes a comment exist only as part of one ticket, and the reason a comment is deleted with the ticket it hangs off. It is declared non-reparentable, so a comment cannot be moved to a different ticket once it is created, and because Ticket Comment is shared as controlled-by-parent it is also this link that decides who can see the comment. It is the foreign key behind the CommentCount roll-up on Ticket, so the comment count that Comment_Validation checks before a ticket may be closed is derived entirely from this relationship. No flow or Apex in the repository populates it, so the ticket a comment belongs to is set by whatever creates the record.
