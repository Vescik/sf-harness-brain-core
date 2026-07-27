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
  contentDigest: sha256:2e3bf8179fc4bb2c52acb5809568a2865e6e5118ab7942651c23c0288c505696
  state: draft
limitations:
- No flag records ship in this repository, so the set of flags actually in use is
  not visible from source.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:92f18be6511212175a8a734907ffaa1db21af7fe025201e8b744022334db28a1
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/FeatureFlag__mdt/FeatureFlag__mdt.object-meta.xml
    sourceDigest: sha256:100373d07b23f40cca8ac9456defd30e66a71fac10a2e2a2f467e53702fedb86
subject:
  fullName: FeatureFlag__mdt
  metadataType: CustomObject
  namespace: null
typeFacts:
  description: Protected feature flags controlling internal, staged rollout of package
    logic. Invisible to subscribers.
  label: Feature Flag
  objectKind: customMetadataType
  pluralLabel: Feature Flags
---

## Purpose

A framework switch table: one record is a named flag with an on or off state and a short note on what it controls, and the FeatureFlags class loads them all into a cache and treats an unknown flag as off, so a missing record is a disabled feature rather than an error. On top of that, the trigger framework layers a naming convention, where an active flag named Bypass_ plus a handler class name makes TriggerHandler skip that handler, which turns this table into the package-owned kill switch for trigger logic as opposed to the admin-facing TriggerBypass__c hierarchy setting checked alongside it. Its visibility is protected, and the object description ties that to internal staged rollout of package behaviour that subscribers cannot see or change. No flag records ship in this repo, so the set of flags actually in use is not visible from source.
