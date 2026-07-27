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
  contentDigest: sha256:814c406fd7c78f33f31b94a72c3a50d3c76b6abd1059e3b106c87109b74e0e23
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
  sourceTreeDigest: sha256:9ff155f48efe748d3d9e57f6087732b9e9aa92217e78f8128ad48312362e1417
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/TriggerBypass__c/fields/Disable_All__c.field-meta.xml
    sourceDigest: sha256:952b29d309636b9c6b8777e875699dab920fda7b4db38e6980892c87d99a48d3
subject:
  fullName: TriggerBypass__c.Disable_All__c
  metadataType: CustomField
  namespace: null
typeFacts:
  defaultValue: 'false'
  description: Master switch to bypass all Meridian PSA triggers for the context user/profile/org.
  fullName: Disable_All__c
  label: Disable All
  object: TriggerBypass__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: TriggerBypass__c
  type: Checkbox
---

## Purpose

This is the all-or-nothing switch on the trigger bypass setting: when it is on, the TriggerBypass class reports every handler name as bypassed and never looks at the named-handler list, so it overrides Bypassed_Handlers__c entirely. It is off by default and the class treats an absent setting record as no bypass, so automation runs unless someone deliberately turns the switch on for a user, a profile, or the whole org. The field's own description calls it a master switch for all Meridian PSA triggers; what this repository actually shows it reaching is any handler routed through TriggerHandler, which consults TriggerBypass last after its in-memory bypass set and the FeatureFlags check. TriggerBypassTest pins the precedence, asserting that the switch wins over a handler name that is not in the bypass list.
