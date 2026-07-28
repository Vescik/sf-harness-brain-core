---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:7133d826dc44c6ae8ef3709972091c39bc2e28789d8cd13d3d37584f3a0ba7c2
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:7133d826dc44c6ae8ef3709972091c39bc2e28789d8cd13d3d37584f3a0ba7c2
  state: approved
limitations:
- No code in this repository reads this field, so the maintainers who actually consume
  the note are not visible in source.
- The source does not say whether every binding record is expected to carry a description.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:47fb19c588801fa72f35c5c69b97b2a17be6b5aa5c6bc51888d56b733812e3e5
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/ServiceBinding__mdt/fields/Description__c.field-meta.xml
    sourceDigest: sha256:53b0123e596723512d0f4533480da28fff6e7b2362e4942437630a0937230e94
subject:
  fullName: ServiceBinding__mdt.Description__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: What this binding is for.
  externalId: false
  fullName: Description__c
  label: Description
  length: 255
  object: ServiceBinding__mdt
  references:
  - assurance: source-exact
    kind: belongs-to
    target: ServiceBinding__mdt
  required: false
  type: Text
  unique: false
---

## Purpose

Carries a short human-readable note saying what a given service binding is for, so someone browsing the binding records can tell them apart without reading ServiceLocator. No code in this repo reads it: the locator finds a binding by its record name and then uses only the implementation class and the namespace prefix, so this value informs whoever maintains or overrides the bindings rather than affecting resolution. The source does not say whether every binding is expected to carry one.
