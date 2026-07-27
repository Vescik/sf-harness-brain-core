---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:76c731d68a8f80ae0d14652187e01c345f5d46431c1c17a5cc33246c7c69e079
  state: draft
limitations:
- The bypass values live in a hierarchy custom setting that is admin-editable org
  data, so which handlers are actually bypassed cannot be read from this repository.
- The source shows only the read side of the setting and never writes it, so what
  populates the bypass list is not visible here.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:cc23be97d429a730ab4b125c2758e584ba7dd812bd3b38695b61d60e4e105970
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/TriggerBypass.cls
    sourceDigest: sha256:17af9d92f16ef13cf1d0385d773d5637981d949307c36eaaa5d79f1437aaf564
subject:
  fullName: TriggerBypass
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - TestVisible
  apiVersion: '62.0'
  declarationKind: class
  description: Runtime, per-org/profile/user trigger bypass backed by the TriggerBypass__c
    hierarchy custom setting. Unlike FeatureFlag__mdt (package-owned, protected),
    this setting is data that admins in any org can toggle — e.g. to silence automation
    during a bulk data load. * The setting stores a semicolon-delimited list of handler
    names to bypass, plus a master "Disable_All__c" switch.
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Bypassed_Handlers__c
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TriggerBypass__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Bypassed_Handlers__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Disable_All__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: TriggerBypass__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: TriggerBypass__c.Bypassed_Handlers__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: TriggerBypass__c.Disable_All__c
  sharingModel: with
  status: Active
---

## Purpose

TriggerBypass answers one question for the trigger framework: should the handler with this name be skipped right now. It resolves the hierarchy custom setting for the current context, so the answer depends on the org, profile, or user level value in effect for the running user, and it treats an absent setting as no bypass so automation stays on by default. A master switch on the setting suppresses every handler at once; otherwise the setting's handler list is split on semicolons and each entry is compared to the requested name with surrounding whitespace trimmed and case ignored, so an admin-typed list is forgiving about spacing and capitalisation. TriggerHandler is the caller, consulting it as one of the gates before a handler runs. Because the switch lives in a custom setting rather than in package metadata, the header notes it is data an admin can toggle in any org, for example to quiet automation during a bulk load, though the source shows only the read side and never writes the setting.
