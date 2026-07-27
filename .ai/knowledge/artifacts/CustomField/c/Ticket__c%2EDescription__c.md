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
  contentDigest: sha256:f0ceee5416eea2e7f9e1b5a25b5fc18e9c662215b4829d75942cad41ecd56cc9
  state: draft
limitations:
- No validation rule, flow or Apex in this repository reads or writes the field, so
  whether anything outside repository source consumes the description is not visible
  here.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:3d554b3afd54051ea62f4d9527e8c26322f3824df505162a0c87a42117f4058d
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket__c/fields/Description__c.field-meta.xml
    sourceDigest: sha256:b2dae14278103fcd84719fb9a3d7371fbfc4e1fa53b9cf61984444516162aa0a
subject:
  fullName: Ticket__c.Description__c
  metadataType: CustomField
  namespace: null
typeFacts:
  externalId: false
  fullName: Description__c
  label: Description
  length: 255
  object: Ticket__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket__c
  required: true
  type: Text
  unique: false
---

## Purpose

Holds the free-text statement of what the ticket is asking for. It is mandatory at the field level and is also marked required on the Request Item record page, where it sits with Subject and Category in the information section, so a ticket cannot be saved without one; Subject is the optional short title and this is the part that must always be filled in. Nothing else in the repository reads or writes it, as no validation rule, flow or Apex references the field, so it serves as captured narrative for whoever works the ticket rather than as an input to any automation.
