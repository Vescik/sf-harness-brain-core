---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:6c4fd6c180af68c6d54a8fda5363e94c7a873254900a9e8655c2339c9f528817
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:6c4fd6c180af68c6d54a8fda5363e94c7a873254900a9e8655c2339c9f528817
  state: approved
limitations:
- Statuses, priorities and service types are coded values drawn from global value
  sets that are not in this repository, so what codes such as s_1 and s_6 stand for
  cannot be read from source.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:299ac1efd9967c1c6c8f82cb1099154e178c8118b85adf53837ebf42b84d1610
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/Service_Request__c.object-meta.xml
    sourceDigest: sha256:4d9994862ce9f4621ca6ef98f833fcdec5d95ddf8a4e3306b704d5fe11478e70
subject:
  fullName: Service_Request__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  enableActivities: false
  enableFeeds: false
  enableHistory: true
  enableReports: true
  enableSearch: true
  externalSharingModel: Private
  label: Service Request
  nameField:
    displayFormat: SR-{00000}
    label: Request ID
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Service Requests
  sharingModel: ReadWrite
---

## Purpose

One record is a single service request logged against an Account and a Contact, capturing the type of service asked for and a free-text description, how urgent it is, when it was raised and when it is due, an estimate of hours, its current status, and the technician it is assigned to. It is the parent of two master-detail children, Service Task and Time Log, so the work performed and the time booked against a request are owned by that request and cannot outlive it. The only automation on the object in this repo is a before-save flow that checks each status change against an allowed set of prior-to-new transitions and raises a custom error on anything outside them, and that flow is marked Obsolete, so nothing in source currently constrains status movement. Statuses, priorities and service types are coded values drawn from global value sets that are not in this repo, so what codes such as s_1 and s_6 stand for cannot be read from source.
