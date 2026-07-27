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
  contentDigest: sha256:9d5d8b85ab95d24044549260ab589ba47087ac289f95cf935fd0e9e31de1a35f
  state: draft
limitations:
- What this flow would actually write cannot be read from the source, since the update
  element names a field literally called null__NotFound and the intended behaviour
  survives only in the element labels.
profile:
  digest: sha256:0cac1405840a5cd6ceb010714f644864e0e1859d4bc4106c3e2a459a2a0b31a7
  id: salesforce.flow
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ba4b0fdf62129a318d6cc42c973d65d2de8b97152c5dec66793a14450da39885
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/flows/Ticket_Update.flow-meta.xml
    sourceDigest: sha256:e8df1dcc72d5c34ae32127006a2c521006e0ca8238491f55e35204ca55b521e2
subject:
  fullName: Ticket_Update
  metadataType: Flow
  namespace: null
typeFacts:
  processType: AutoLaunchedFlow
  references:
  - assurance: source-exact
    kind: filters-field
    target: Category__c.Id
  - assurance: source-exact
    kind: operates-on
    target: Ticket__c
  - assurance: source-exact
    kind: queries-object
    target: Category__c
  - assurance: source-exact
    kind: references-field
    target: Ticket__c.Priority__c
  - assurance: source-exact
    kind: writes-field
    target: null__NotFound
  status: InvalidDraft
  trigger:
    object: Ticket__c
    recordTriggerType: Create
    type: RecordAfterSave
  variables:
  - apiName: varCategory
    dataType: String
    isCollection: false
    isInput: true
    isOutput: true
---

## Purpose

Branches on a newly created ticket only when its priority came in blank, then reads a category record and hands off to a record-update element, which the element labels present as defaulting a ticket's priority from its category. What it would actually write cannot be read from the source: the lookup returns the category's default priority into a variable that nothing afterwards consumes, the update element names a field literally called null__NotFound, and it targets the child collection of tickets hanging off the triggering ticket's category rather than the triggering record itself. The lookup filter is broken in the same way, matching the category identifier against a parent-of-parent path on Category__c that has no counterpart in the object's metadata here, since that object carries no parent-category field at all. The intended behaviour therefore survives only in the labels; the wiring underneath it does not resolve.
