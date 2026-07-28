---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:eda95542ff947d10075cc44864439b60c15d27f24d2fb9b48c5842104efec153
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:eda95542ff947d10075cc44864439b60c15d27f24d2fb9b48c5842104efec153
  state: approved
limitations:
- No Apex, Flow, validation rule, layout or permission set in the repository reads
  this field, so any assignment, sharing or reporting behaviour built on it lives
  outside this repository.
- The source does not distinguish whether this names the person assigned to do the
  work or the person who actually did it.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:fcadcce995f6e2abb7a794e1ad3da0a621feaccb49f031fb3b1dd1b1069b0992
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Technician__c.field-meta.xml
    sourceDigest: sha256:acbd025723a28d38cc1fb497b8ac98dd11950fb6aeda44798c132bf33868c5bb
subject:
  fullName: Service_Task__c.Technician__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Technician__c
  label: Technician
  object: Service_Task__c
  referenceTo:
  - User
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  - assurance: source-exact
    kind: relationship
    target: User
  relationshipName: Service_Tasks
  required: false
  trackHistory: false
  type: Lookup
---

## Purpose

Records which User is the technician for a Service Task; the source does not distinguish whether that means the person assigned to do the work or the person who actually did it. The parent Service Request carries its own Assigned Technician link and Time Log rows carry their own Technician, so the same worker can be captured in three separate places, and nothing in the repo copies one into another or keeps them in agreement. The link is optional, and deleting the referenced User clears it rather than blocking the delete, so a task can survive with no technician named. No Apex, Flow, validation rule, layout or permission set in the repo reads it, so any assignment, sharing or reporting behaviour built on it lives outside this repo.
