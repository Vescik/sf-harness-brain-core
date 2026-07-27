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
  contentDigest: sha256:7e6517c535386f46503a38f547ec71bc1d4ab3d568626cc450878feed4aabe51
  state: draft
limitations:
- Any scheduling or timesheet logic that depends on this field is not visible in this
  repository.
- The source does not say whether this is the day the work is scheduled for or the
  day it was performed, and there is no default, validation or consumer in the repository
  to settle the question.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:497c8ad8453900f8c1f9c76c6165af34f1a9d8952903ae56648b6f359cdacccf
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Task__c/fields/Work_Date__c.field-meta.xml
    sourceDigest: sha256:b7fe6a8a936fbb29484f467b0ef5f6cdfd08af473749b9d093718fd8640eb048
subject:
  fullName: Service_Task__c.Work_Date__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Work_Date__c
  label: Work Date
  object: Service_Task__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Task__c
  required: false
  trackHistory: false
  type: Date
---

## Purpose

Carries the calendar day associated with the work on a Service Task. The source does not say whether that is the day the work is scheduled for or the day it was performed, and there is no default, no validation and no consumer anywhere in the repo to settle the question. The parent Service Request separately carries a Request Date and a Due Date, and Time Log rows carry their own Log Date, none of which are derived from or checked against this one. It is optional, so a Service Task can exist with no date at all, and any scheduling or timesheet logic that depends on it is not visible in this repo.
