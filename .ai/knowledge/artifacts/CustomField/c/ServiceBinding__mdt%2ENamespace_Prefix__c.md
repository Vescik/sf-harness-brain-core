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
  contentDigest: sha256:db4d9951388cd96dbada36f18a8c99cc534aa09a2b941915ee63bddb90ba6ca1
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
  sourceTreeDigest: sha256:c1c11b480fb74b46da5fe74cca996ab1a1c21acfdc671de3403470d0e931e11b
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/ServiceBinding__mdt/fields/Namespace_Prefix__c.field-meta.xml
    sourceDigest: sha256:b8978564ef995aed6a768a08a59cbc9955aff7fddaf32f76a12b67b308893084
subject:
  fullName: ServiceBinding__mdt.Namespace_Prefix__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Optional namespace prefix of the implementation class (for subscriber
    overrides).
  externalId: false
  fullName: Namespace_Prefix__c
  label: Namespace Prefix
  length: 15
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

Says which namespace the bound implementation class lives in, so a binding can resolve to a class outside the package that ships the record. ServiceLocator attempts the namespace-qualified type lookup first and falls back to the bare class name when that comes back empty, so an empty value is the ordinary case for a class in the same package as the locator. Unlike the other fields on this record it is subscriber-controlled, which is the mechanism behind the override story stated on the object itself: an installing org can repoint a shipped binding at a class in its own namespace.
