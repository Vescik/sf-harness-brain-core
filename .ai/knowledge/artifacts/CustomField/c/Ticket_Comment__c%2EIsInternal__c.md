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
  contentDigest: sha256:18b383b7fd3dcc76eb1e52b01e7f45f16cad72663a5ff176eefeed3016eec813
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
  sourceTreeDigest: sha256:02d4d130c77afbcdd1f57a8bef329b17e2284a22f79d0e04dbed6c6b3a25436d
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Ticket_Comment__c/fields/IsInternal__c.field-meta.xml
    sourceDigest: sha256:c2cbfbc5fa5b4b311ae2a24fb5f89ef11c86e5a5f553d9eea105e615467dd1a4
subject:
  fullName: Ticket_Comment__c.IsInternal__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: 'false'
  fullName: IsInternal__c
  label: IsInternal
  object: Ticket_Comment__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Ticket_Comment__c
  type: Checkbox
---

## Purpose

Records whether a ticket comment is internal, defaulting to not internal so a comment is treated as ordinary unless someone deliberately sets the flag. Nothing in this repository consumes it, as no validation rule, flow, Apex class or record page under force-app branches on the value, and the field carries no description of its own. What being internal is supposed to change, whether that is who may read the comment or whether it is hidden from a customer-facing view, is therefore not visible in the source and would have to be confirmed with the owner.
