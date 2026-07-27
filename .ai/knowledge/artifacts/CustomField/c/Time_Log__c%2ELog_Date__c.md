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
  contentDigest: sha256:6afa84e4fc191a009972a7ae44c5f7a326efec04e2e35de6824839621b821661
  state: draft
limitations:
- No Apex, flow, or record page in this repository reads the field, so any grouping
  of time logs into a week, a month, or a billing period happens outside the metadata
  committed here and cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:47aedfb396f868e7a9d9731952fc3b8ba57855aac5e75e445aa7b703ac1714d8
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Log_Date__c.field-meta.xml
    sourceDigest: sha256:7968fe4635cff84f91c749fceee254af1ab72752485bb3727063f304ce829362
subject:
  fullName: Time_Log__c.Log_Date__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Log_Date__c
  label: Log Date
  object: Time_Log__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  required: false
  trackHistory: false
  type: Date
---

## Purpose

Log_Date__c is the day the logged effort is attributed to, which need not be the day the record was created, since the field is typed in rather than defaulted from the save. Nothing in this repo constrains it: it is optional, it has no default, and no validation rule keeps it inside the parent service request's own dates or blocks a date in the future. No Apex, flow, or record page here reads it either, so any grouping of time logs into a week, a month, or a billing period is done outside the metadata committed to this repo.
