---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:5828fd42f50b64146455a53c7d45fbd86cd9bd5004e16b09790698e63034d882
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:5828fd42f50b64146455a53c7d45fbd86cd9bd5004e16b09790698e63034d882
  state: approved
limitations:
- Beyond the record page and one InvalidDraft flow nothing in this repository reads
  the field, so whether the classification drives any working behaviour is not visible
  from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:bcac472b3979edb86a5447a7fb00ab9b279d5295796b1c38b5f322ad6cd8b9f5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Category__c.field-meta.xml
    sourceDigest: sha256:5b064948f6c82ae4e335bcb24351441d3981ebd8179c8f1a267b57d7d03a9254
subject:
  fullName: Ticket__c.Category__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Category__c
  label: Category
  object: Ticket__c
  referenceTo:
  - ProductCategory
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  - assurance: source-exact
    kind: relationship
    target: ProductCategory
  relationshipLabel: Tickets
  relationshipName: Tickets
  required: false
  type: Lookup
---

## Purpose

Classifies a ticket by pointing it at a ProductCategory record, and is exposed for editing on the Request Item record page alongside Subject and Description. Deleting the referenced category does not remove the ticket, it simply clears the classification and leaves the ticket uncategorised. The Ticket Update flow reads through this lookup, walking up the product category hierarchy to a grandparent, in order to fetch a default priority for a newly created ticket. That path does not hold together in the source, because the flow's lookup queries the custom Category object rather than the ProductCategory this field actually references, and the flow is saved as InvalidDraft. Beyond the record page and that flow nothing in the repository reads the field, so the classification is not shown driving any working behaviour here.
