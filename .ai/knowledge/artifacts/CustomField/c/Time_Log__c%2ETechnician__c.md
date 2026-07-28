---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:38194b976a8933a61e884f144a870fdcb0566aa18fcb9905f082a9ebeb4004c2
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:38194b976a8933a61e884f144a870fdcb0566aa18fcb9905f082a9ebeb4004c2
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
  sourceTreeDigest: sha256:43d7ab220e4228e367ea6aac905b460f0425c2eb64bd2774a825d4a324c0234c
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Technician__c.field-meta.xml
    sourceDigest: sha256:813011c46602bf90205ada5795b250778ab07278430a9d9c91a98819ce6bd2c0
subject:
  fullName: Time_Log__c.Technician__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Technician__c
  label: Technician
  object: Time_Log__c
  referenceTo:
  - User
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  - assurance: source-exact
    kind: relationship
    target: User
  relationshipName: Time_Log
  required: false
  trackHistory: false
  type: Lookup
---

## Purpose

Technician__c names the person whose time the entry accounts for, and it is the only place a time log says who did the work; the parent request's own Assigned_Technician__c is a separate lookup that is set independently of it. It is optional, and when the referenced user record is deleted the link is cleared rather than the deletion being blocked, so an entry can outlive its technician and end up unattributed. Nothing in this repo populates or checks it: no Apex or flow stamps it from the running user, and no validation rule requires it to be filled or to agree with the technician assigned on the parent request.
