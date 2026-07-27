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
  contentDigest: sha256:b5570b861ae23f2a53db20d06829d882767508e907c94a70a187dcaaee018495
  state: draft
limitations: []
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ebe0fcec188db6d9cbd125ad7875ec7039860ce353ef81e45c8eef5b14f7889d
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/Time_Log__c.object-meta.xml
    sourceDigest: sha256:a7b3b51b092d2d0c3adfcc32a44a5bfa32b23743473226b3e6007eda63accdcb
subject:
  fullName: Time_Log__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  compactLayoutAssignment: SYSTEM
  deploymentStatus: Deployed
  enableActivities: false
  enableFeeds: false
  enableHistory: true
  enableReports: true
  enableSearch: false
  externalSharingModel: ControlledByParent
  label: Time Log
  nameField:
    displayFormat: TL-{00000}
    label: Time Log Name
    type: AutoNumber
  objectKind: customObject
  pluralLabel: Time Log
  sharingModel: ControlledByParent
---

## Purpose

A Time Log record is one block of hours booked against a Service Request, naming the technician who did the work, the date it was done, a required work type drawn from a restricted value set, and whether the entry has been approved. It exists only underneath a Service Request in master-detail, so a time log is never reachable apart from the request it belongs to. Nothing in this repository reads or writes it: no Apex class, flow, validation rule, or roll-up consumes the hours, and no automation sets the approved flag, so who approves an entry and what approval unlocks is not visible in the source.
