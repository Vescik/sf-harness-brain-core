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
  contentDigest: sha256:2e778db1dae5131266f07b54802b029e3b6367e8c9d80e92a45b6645b7f08baf
  state: draft
limitations:
- No Apex class, Flow, validation rule, or layout in this repository reads or writes
  the field, so what consumes the classification downstream, such as billing, rate
  selection, or reporting, is not shown by the source.
- The Work_Type value set is not present in this repository, so which labour categories
  the picklist permits cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:2b63d387067af2b3fa02da5eac72916c0081dc8002597a1eb9c7b75c2c853884
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Work_Type__c.field-meta.xml
    sourceDigest: sha256:0b5f13f16d362b313b4f7ccaaceb571f12634ad922d84f9d6e9d3b9cfe65f5b2
subject:
  fullName: Time_Log__c.Work_Type__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Work_Type__c
  label: Work Type
  object: Time_Log__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  - assurance: source-exact
    kind: uses-value-set
    target: Work_Type
  required: true
  trackHistory: false
  type: Picklist
  valueSetName: Work_Type
---

## Purpose

Work Type records what kind of labour a Time Log line represents, categorising the hours booked against the parent Service Request rather than measuring them. Its allowed categories come from a shared, restricted Work_Type value set, so the same vocabulary is reused wherever that set is applied and a user cannot enter a category outside it; that value set is not present in this repository, so the permitted categories are not visible here. No Apex class, Flow, validation rule, or layout in this repository reads or writes the field, so what consumes the classification downstream — billing, rate selection, or reporting — is not shown by the source.
