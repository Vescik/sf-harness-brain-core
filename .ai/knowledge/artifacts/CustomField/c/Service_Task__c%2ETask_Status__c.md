---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:65805bd0959620d015c8e990612c556bec643d5429c00451357ec27344f369e6
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:65805bd0959620d015c8e990612c556bec643d5429c00451357ec27344f369e6
  state: approved
limitations:
- Nothing in the repository reads or writes this field, so what advances a task from
  one state to the next, and whether it is meant to influence the parent request status,
  is not shown in source.
- The shared Status value set is not present in this repository, so which task states
  this field permits cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:8f4f1ad912676da3ed262594c90437c5346ff0f5bd79b81f59a23e43a1442b17
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Task_Status__c.field-meta.xml
    sourceDigest: sha256:f426e08103895d9918f2546111f060f301c4b94e7994e360d2471c4109e1ea59
subject:
  fullName: Service_Task__c.Task_Status__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Task_Status__c
  label: Task Status
  object: Service_Task__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  - assurance: source-exact
    kind: uses-value-set
    target: Status
  required: true
  trackHistory: false
  type: Picklist
  valueSetName: Status
---

## Purpose

Marks where a single unit of work on a Service Request currently stands. Its allowed values are drawn from the shared org-wide Status value set that the Service Request and Ticket status fields also use, so task progress is expressed in the same vocabulary as the parent request and as support tickets, but that value set is not present in this repo, so the states themselves cannot be read from source. A Service Task cannot be saved without a value here, and values outside the shared set are refused. Nothing in the repo reads or writes it, and there is no Apex, Flow, validation rule, layout or permission set touching Service Task at all, so what advances a task from one state to the next, and whether it is meant to influence the parent request status, is not shown anywhere in source.
