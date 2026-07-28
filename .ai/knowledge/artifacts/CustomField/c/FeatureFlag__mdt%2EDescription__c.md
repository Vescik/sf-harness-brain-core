---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:9e512de4a451d35904dd8eb72a28fad03debc0003a927c90ff8bccae146ce070
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:9e512de4a451d35904dd8eb72a28fad03debc0003a927c90ff8bccae146ce070
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
  sourceTreeDigest: sha256:3271c0fda54ac582dac2d138922a0fd869e620fa8cf35e37c1cdf2270c6b262b
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/FeatureFlag__mdt/fields/Description__c.field-meta.xml
    sourceDigest: sha256:75df1a05558ed2e2dace95be0cde75da915526a630558fa75889d72b50261636
subject:
  fullName: FeatureFlag__mdt.Description__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: What this flag controls.
  externalId: false
  fullName: Description__c
  label: Description
  length: 255
  object: FeatureFlag__mdt
  references:
  - assurance: source-exact
    kind: belongs-to
    target: FeatureFlag__mdt
  required: false
  type: Text
  unique: false
---

## Purpose

Carries a short human-readable note saying what the flag it sits on actually controls, so whoever maintains a flag record can tell what it gates without reading the Apex behind it. Nothing in this repo reads it: FeatureFlags consults only the flag's active state, and no layout or component in the package surfaces this field. Because FeatureFlag__mdt is protected and invisible to subscribers, the only audience for the text is whoever maintains the package's own flag records.
