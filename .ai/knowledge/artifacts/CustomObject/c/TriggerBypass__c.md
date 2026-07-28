---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:3b6e357763b1b6a089d07d3e628b7db0a5be703b8429d98d527182c88ed1c299
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:3b6e357763b1b6a089d07d3e628b7db0a5be703b8429d98d527182c88ed1c299
  state: approved
limitations:
- The bypass values are data rather than packaged metadata and are toggled per org
  by admins, so which handlers are actually bypassed anywhere is not in this repository.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:9776d23cabcfb315399f0389776d37b39a17f292b1f16e78a236cb9b66beae8f
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/TriggerBypass__c/TriggerBypass__c.object-meta.xml
    sourceDigest: sha256:6e41946a67638117a7449c98ba3fc24b9f459bb3de4353d63888471007212806
subject:
  fullName: TriggerBypass__c
  metadataType: CustomObject
  namespace: null
typeFacts:
  customSettingsType: Hierarchy
  description: Hierarchy custom setting for runtime trigger bypass per org/profile/user.
    Data, not upgraded with the package.
  enableFeeds: false
  label: Trigger Bypass
  objectKind: customSetting
---

## Purpose

This is a framework switch table rather than a business record: a hierarchy custom setting whose value resolves per user, per profile, or org-wide, holding a master Disable All checkbox and a semicolon-delimited list of trigger handler names to skip. The TriggerBypass class reads it and answers whether a named handler is bypassed, treating Disable All as an unconditional yes and otherwise matching the requested handler name case-insensitively against the list. TriggerHandler consults that answer as the last of three bypass checks before it lets a handler run, after an in-memory bypass set and the FeatureFlag metadata check. Because it is a custom setting it is data rather than packaged metadata, and the class header states this is deliberate so that admins in any org can toggle it without a deployment, giving the silencing of automation during a bulk data load as the example use.
