---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:982dc028c2cebc718e2a7a3c5ed51c32b74f1e2611fad75198aa671b52e01b8c
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:982dc028c2cebc718e2a7a3c5ed51c32b74f1e2611fad75198aa671b52e01b8c
  state: approved
limitations:
- What the due date is meant to drive is not visible in this repository, since no
  Apex, flow, or validation rule here reads it.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:1b336cb2617a848b54ca2d4b0e54b2352825e57cccb6df4a852abf3acf5c9378
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Due_Date__c.field-meta.xml
    sourceDigest: sha256:f3fcf378e5d5c4c1d48274e80d898d06260d61cce12f09a98696eb3dbfe23736
subject:
  fullName: Service_Request__c.Due_Date__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Due_Date__c
  label: Due Date
  object: Service_Request__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  required: false
  trackHistory: false
  type: Date
---

## Purpose

Holds the due date entered by hand on a service request; nothing in this package derives it, defaults it, or recalculates it. It is surfaced on the Service Request Record Lightning page in the Information section as a plain editable field and is left optional, so a request saves without one. No Apex, flow, or validation rule in this repo reads it or checks it against Request Date, so the source shows no consequence for leaving it blank or letting it pass, and what the date is meant to drive is not visible here. Ticket__c defines a separate, unrelated field of the same name that does carry a validation rule behind it.
