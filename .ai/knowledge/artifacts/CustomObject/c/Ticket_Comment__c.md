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
  contentDigest: sha256:542b1ab03fddc51600d8130bf5643458f0117a9eaf9313b37db1eaf0f3888e09
  state: draft
limitations: []
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:29a1c5d250f26c7f75d6c354085ffdc9a34e7e4ed078c0b17a1c6d4e7745fa0d
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket_Comment__c/Ticket_Comment__c.object-meta.xml
    sourceDigest: sha256:8148a1535165d946b075bba8dd5f8b2d9e99e83e670b6e39471f7776fe181da2
subject:
  fullName: Ticket_Comment__c
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
  externalSharingModel: ControlledByParent
  label: Ticket Comment
  nameField:
    displayFormat: TC-{000000}
    label: Ticket Comment Name
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Ticket Comment
  sharingModel: ControlledByParent
---

## Purpose

A Ticket Comment record is one note recorded against a Ticket, holding the comment text, a lookup to the User credited as its author, and a flag marking the comment as internal. It exists only underneath a Ticket, and the master-detail parent makes comment visibility follow the parent ticket rather than being granted on its own. Its rows are what the Ticket comment-count roll-up totals, and that roll-up is what the Comment Validation rule tests, so a Ticket cannot be saved as Closed until at least one of these records exists under it. Nothing in this repository reads the internal flag, so what marking a comment internal is meant to change is not visible in the source.
