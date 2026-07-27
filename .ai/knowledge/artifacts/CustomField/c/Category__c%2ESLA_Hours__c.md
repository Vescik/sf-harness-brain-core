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
  contentDigest: sha256:9da047160f9321a234f8c9da5062629e4c6b37b5b504530d86d27bd9ee1d089c
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
  sourceTreeDigest: sha256:837592527d41ffd2bff694a6aa55bf4b3e4fad86da33e58b0947b3999134ea98
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Category__c/fields/SLA_Hours__c.field-meta.xml
    sourceDigest: sha256:fa193ce817482c5849ed0e7f5551ea205165011e06df093d964e8729412ec552
subject:
  fullName: Category__c.SLA_Hours__c
  metadataType: CustomField
  namespace: null
typeFacts:
  externalId: false
  fullName: SLA_Hours__c
  label: SLA Hours
  object: Category__c
  precision: 5
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Category__c
  required: false
  scale: 0
  type: Number
  unique: false
---

## Purpose

SLA Hours records a duration, expressed in hours, against a Category record. Nothing in this repository consumes it, as no formula, roll-up, validation rule, flow, Apex class, or Lightning page reads or writes the value, and the field carries no description or help text. What the hours are measured from and what they are measured to, whether first response, resolution, or something else, is therefore not established anywhere in the source, and the field name is the only evidence of intent.
