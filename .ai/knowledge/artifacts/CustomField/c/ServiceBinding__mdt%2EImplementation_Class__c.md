---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:9199c4f60eba0c6a8cc002bfdad9dbbdca143cf75378b2398d7520cb2911c155
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:9199c4f60eba0c6a8cc002bfdad9dbbdca143cf75378b2398d7520cb2911c155
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
  sourceTreeDigest: sha256:1492b0c13dadc8903950e0e23e85da06a28fed4d695f8118710b3d4356ac6b98
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/ServiceBinding__mdt/fields/Implementation_Class__c.field-meta.xml
    sourceDigest: sha256:5a618e8b06e2e8f38499c31f48838a1ef560bb8208557f3ba66e7a27b00e7747
subject:
  fullName: ServiceBinding__mdt.Implementation_Class__c
  metadataType: CustomField
  namespace: null
typeFacts:
  description: Apex class name that implements the bound interface.
  externalId: false
  fullName: Implementation_Class__c
  label: Implementation Class
  length: 255
  object: ServiceBinding__mdt
  references:
  - assurance: source-exact
    kind: belongs-to
    target: ServiceBinding__mdt
  required: true
  type: Text
  unique: false
---

## Purpose

Holds the name of the concrete Apex class that ServiceLocator instantiates for a binding, and it is the value that turns a logical interface name into a real object. When a caller resolves a binding, the locator reads the matching record and hands this value to the platform type lookup, first qualified by the namespace prefix and then bare, so an unqualified class in the same package still resolves. If neither attempt yields a loadable type, the locator throws a ServiceLocatorException quoting this value, which makes a wrong or renamed class name a failure at the first resolve rather than at deploy time.
