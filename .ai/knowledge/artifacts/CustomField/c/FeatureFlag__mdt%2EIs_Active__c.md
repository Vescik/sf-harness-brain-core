---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:05938959e83304ea175de44d480d828d6b77784d904006d9449d69beb5ebf327
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:05938959e83304ea175de44d480d828d6b77784d904006d9449d69beb5ebf327
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
  sourceTreeDigest: sha256:57c06594bcd632051ef6bdf1d817b7971d67cddf73acf91d50d55bfb882f0939
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/FeatureFlag__mdt/fields/Is_Active__c.field-meta.xml
    sourceDigest: sha256:1f21298f4a8ad24105905023fcbed269cba254c286fc23b3b4005f2a1dd3d615
subject:
  fullName: FeatureFlag__mdt.Is_Active__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: 'false'
  description: When true the flag is on.
  fullName: Is_Active__c
  label: Is Active
  object: FeatureFlag__mdt
  references:
  - assurance: source-exact
    kind: belongs-to
    target: FeatureFlag__mdt
  type: Checkbox
---

## Purpose

This is the switch that makes a feature flag mean anything: FeatureFlags reports a feature enabled only when a flag record with the requested developer name exists and this box is checked, so an unknown flag and an unchecked flag are treated the same way, as off. It defaults to unchecked, so a newly added flag record starts disabled until someone turns it on. The same field drives trigger bypass — TriggerHandler asks FeatureFlags whether its handler is bypassed, which looks for a flag whose name is "Bypass_" followed by the handler name and skips that handler package-wide when this is set. Since it is developer-controlled on protected metadata, flipping it is a package-side rollout action rather than something a subscriber admin can reach.
