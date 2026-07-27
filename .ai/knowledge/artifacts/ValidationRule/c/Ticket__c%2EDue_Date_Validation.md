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
  contentDigest: sha256:86dcfc9ca83fe63ef6656340afca4e1c217b9fa5d86b2806aafe1490847927f5
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
  sourceTreeDigest: sha256:42d36c7b1ac8c0d05f84f5847ac79673b977347bc798593a6a570c90da2b2544
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/validationRules/Due_Date_Validation.validationRule-meta.xml
    sourceDigest: sha256:4936c8c073400f27363648b450d6c18887d538628da1ace633819f9846f5fb3a
subject:
  fullName: Ticket__c.Due_Date_Validation
  metadataType: ValidationRule
  namespace: null
typeFacts:
  active: true
  errorCatalog:
  - component: Due_Date_Validation
    condition: "AND(\n  ISBLANK(Due_Date__c),\n  OR(\n    ISPICKVAL(Status__c, \"\
      Waiting\"),\n    ISPICKVAL(Status__c, \"In Progress\")\n  )\n)"
    errorMessage: Due Date is required when Ticket is Waiting or In Progress.
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
    target: Ticket__c.Due_Date__c
  - assurance: source-derived-heuristic
    kind: references-field
    target: Ticket__c.Status__c
---

## Purpose

Stops a Ticket being saved with an empty Due Date while its Status is Waiting or In Progress, and the save fails with a message stating that a Due Date is required in those two states. Tickets in any other status can be saved with no due date, so the requirement is scoped to those two working states rather than applied to the field generally. The Status picklist draws on a global value set that is not present in this repo, so the source here cannot confirm that the two literal values the rule tests still match the stored picklist values.
