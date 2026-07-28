---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:b515c7ea40a0c5e001791a66d9440eac8d9f4976535da3acb7a38fb80d692a63
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:b515c7ea40a0c5e001791a66d9440eac8d9f4976535da3acb7a38fb80d692a63
  state: approved
limitations:
- Nothing in this repository references the object, so how tasks are created, how
  their status relates to the parent request's status, and how booked hours relate
  to the request's estimate cannot be read from source.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ae00e07a4b67f74a704f9fa664e0d8a34a5e904185109b3e13af2933d1727a49
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/Service_Task__c.object-meta.xml
    sourceDigest: sha256:044dfb29e1287424cfc50f31466887342603a23a1fd16266d76e6056325c9564
subject:
  fullName: Service_Task__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  enableActivities: true
  enableFeeds: false
  enableHistory: true
  enableReports: true
  enableSearch: true
  externalSharingModel: ControlledByParent
  label: Service Task
  nameField:
    displayFormat: ST-{00000}
    label: Service Task ID
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Service Tasks
  sharingModel: ControlledByParent
---

## Purpose

One record is a unit of work carried out under a parent Service Request, recording the kind of task, its status, the technician who performed it, the date it was worked and the hours booked to it. The parent link is master-detail, so a task cannot exist without a request, takes its sharing from that request, and is deleted with it. Nothing else in this repo references the object at all, with no Apex, flow, validation rule or layout touching it, so how tasks are created, how their status relates to the parent request's status, and how booked hours relate to the request's estimate are all invisible from source.
