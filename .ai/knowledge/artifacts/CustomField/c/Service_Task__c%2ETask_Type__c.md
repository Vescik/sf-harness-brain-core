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
  contentDigest: sha256:6255fdd577cc649b9c49b5b854967cf67e97b7a6668fd9bb5a2a0c8e44b84b32
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
  sourceTreeDigest: sha256:7de62b80cc5cf6eda653ae8826bd7b9ff18fe1e8fe038631f486eef56fb1f228
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Task_Type__c.field-meta.xml
    sourceDigest: sha256:cfec464469467f3e966dd4c0c4d5b59a3ac876c4ccfe6780aa301f330a10d63c
subject:
  fullName: Service_Task__c.Task_Type__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Task_Type__c
  label: Task Type
  object: Service_Task__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  - assurance: source-exact
    kind: uses-value-set
    target: Task_Type
  required: true
  trackHistory: false
  type: Picklist
  valueSetName: Task_Type
---

## Purpose

Classifies the kind of work a Service Task represents, and no task can be saved without one. The categories come from a shared Task Type value set rather than being defined on the field itself, and that value set is not part of this repo, so the choices it offers cannot be read from source. It is a different vocabulary from the Work Type used on Time Log records, so task classification and time-entry classification are not guaranteed to line up. No Apex, Flow, validation rule or layout in the repo branches on this value, so nothing here shows the classification driving any downstream behaviour.
