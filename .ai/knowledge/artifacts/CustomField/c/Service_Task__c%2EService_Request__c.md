---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:d17af8a73c31d159b776ee54cda284dfe3f60a7485dc9398ee63cccf063b6dd3
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:d17af8a73c31d159b776ee54cda284dfe3f60a7485dc9398ee63cccf063b6dd3
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
  sourceTreeDigest: sha256:a4cd5e4eafa014c2d1df1866fd394795ae6ea8daa33bc69e063b1606f29ba593
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Service_Request__c.field-meta.xml
    sourceDigest: sha256:6e935de19fef4e5693ef6001bafc8a53c1eab34ff934a88bc98d853c070bf2ff
subject:
  fullName: Service_Task__c.Service_Request__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Service_Request__c
  label: Service Request
  object: Service_Task__c
  referenceTo:
  - Service_Request__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  - assurance: source-exact
    kind: relationship
    target: Service_Request__c
  relationshipLabel: Service Tasks
  relationshipName: Service_Tasks
  relationshipOrder: 0
  reparentableMasterDetail: false
  trackHistory: false
  type: MasterDetail
  writeRequiresMasterRead: false
---

## Purpose

This is the spine of the service work breakdown: it binds every service task to exactly one service request as a hard child, so a task cannot exist unparented, cannot be moved to another request after it is saved because reparenting is switched off, and is deleted along with its parent. Being the primary master-detail is also what makes Service Task's sharing derived rather than its own — the object is Controlled By Parent, so who can see a task follows entirely from who can see its request. Its sharing setting is the permissive one: read access on the parent request is enough to create or edit that request's tasks, so full edit rights on the request are not required to log work under it. Time Log hangs off the same parent in the same way, so a request owns two independent child collections, and nothing in this repo ties a time log back to the task it was worked under. No roll-up summary, Apex, or flow in this package traverses the relationship, so the source shows the structure but no logic that folds task hours or task status back up onto the request.
