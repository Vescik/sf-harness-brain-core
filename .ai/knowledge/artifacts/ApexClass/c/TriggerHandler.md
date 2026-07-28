---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:3c3f408bd5c0ec0bc776abec5484b6fb9a6aba00a3471ae835d14d7372ec0ecd
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:3c3f408bd5c0ec0bc776abec5484b6fb9a6aba00a3471ae835d14d7372ec0ecd
  state: approved
limitations:
- This repository contains no triggers and no handler subclass other than the test
  one, so the live consumers this framework dispatches for are not visible in source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:6d3d7e2f8611819010b279934ee3a097b31ea016e5f5aeb156b88b145559e696
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/TriggerHandler.cls
    sourceDigest: sha256:6bb4f92b8d49e4f7f502aaa5cc60efc352e3ef06e82be93432cbde330a03f8c5
subject:
  fullName: TriggerHandler
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - SuppressWarnings
  - TestVisible
  apiVersion: '62.0'
  declarationKind: class
  description: Base class for all trigger handlers in Meridian PSA. One trigger per
    object dispatches to a single subclass of this handler. Supports per-handler recursion
    limits and runtime bypass via TriggerBypass__c hierarchy custom setting and FeatureFlag__mdt.
    * Subclasses override the relevant context methods (beforeInsert, afterUpdate,
    ...) and never contain SOQL — queries belong in selectors, business rules in domains.
  dmlOperations:
  - delete
  - insert
  - undelete
  - update
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: FeatureFlags
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: LoopCount
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TriggerBypass
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: TriggerHandlerException
  sharingModel: omitted
  status: Active
---

## Purpose

TriggerHandler is the dispatch and control point every object's trigger is meant to go through: a trigger constructs its handler subclass and calls the single run entry point, and this base decides whether the handler may run at all before routing the invocation to the one context method that matches the current trigger operation, which subclasses override and leave empty otherwise. It refuses to run outside trigger execution, throwing its own exception rather than silently doing nothing, so a handler invoked from ordinary code fails visibly. Three independent off switches are checked in turn and any one of them quietly skips the handler: an in-transaction set that code can toggle through the static bypass helpers for the remainder of the request, a per-handler feature flag, and the admin-editable bypass custom setting. It also guards against runaway re-entry by counting invocations per handler name and throwing once a configured maximum is passed, although that counting only applies to handlers that have registered a limit, since no entry exists in the counter map until setMaxLoopCount is called. The name used as the key for both the bypass checks and the loop counter is derived at runtime from the concrete subclass rather than being declared, so the string an admin puts in the bypass setting has to match the subclass name. The header states the accompanying convention that subclasses hold no SOQL and delegate rules to domain classes, but this repository contains no triggers and no subclass other than the test, so the framework is present without a live consumer.
