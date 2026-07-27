---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:ac2bfbaad86bdfa91a918dd09ac3dbcc036697dd208a0550d877603db43a6af3
  state: draft
limitations: []
profile:
  digest: sha256:baaa5f69a92d0b991b9a11f226acc297c7d5373a4b65dd97ddb7359315277c4d
  id: salesforce.validation-rule
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:852f64894768ebe5a0fcd48376a35649a947955529dd74159fdbf4de8afc1ccc
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/validationRules/Comment_Validation.validationRule-meta.xml
    sourceDigest: sha256:a7140b194162e71250a81a474f11b9caeadbe37f52da65fe9b368617e6f05f31
subject:
  fullName: Ticket__c.Comment_Validation
  metadataType: ValidationRule
  namespace: null
typeFacts:
  active: true
  errorCatalog:
  - component: Comment_Validation
    condition: "AND(\n  ISPICKVAL(Status__c, \"Closed\"),\n  CommentCount__c = 0\n\
      )"
    errorMessage: You must add at least one comment before closing the ticket.
    kind: validation-rule
  errorMessagePresent: true
  object: Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  - assurance: source-exact
    kind: operates-on
    target: Ticket__c
  - assurance: source-derived-heuristic
    kind: references-field
    target: Ticket__c.CommentCount__c
  - assurance: source-derived-heuristic
    kind: references-field
    target: Ticket__c.Status__c
---

## Purpose

Stops a ticket being saved as Closed while it has no comments on it, telling the user to add at least one comment before closing. The count it tests is the roll-up of related ticket comment records, so the check is satisfied by any comment linked to the ticket rather than by anything the closer types at the moment of closing. It fires on every save where the status is already Closed, not only on the transition into Closed, so an existing closed ticket whose comments are all removed cannot be saved again until one is restored.
