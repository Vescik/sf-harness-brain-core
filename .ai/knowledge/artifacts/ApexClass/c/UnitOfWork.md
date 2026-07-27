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
  contentDigest: sha256:685d6b4fe19e9d0bebb8a4630b1bc4fec995b75312d9dcdc56861d9e600ef1e8
  state: draft
limitations: []
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ca7f21d2b2f5beb20fd12eba657a3fa5ab5a1c321bc18121b7579f5c18b8f216
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/UnitOfWork.cls
    sourceDigest: sha256:936a4302f22b065dfac47b7239309ad60e51bf6a50cf0529741bd24014651f72
subject:
  fullName: UnitOfWork
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '62.0'
  declarationKind: class
  description: 'Lightweight unit-of-work: collects DML across a transaction, commits
    it in a deterministic order in a single commitWork() call, and publishes platform
    events only after the DML succeeds (publish-after-commit). * All DML runs in user
    mode by default (AccessLevel.USER_MODE) so CRUD/FLS is enforced; callers needing
    system context construct with UnitOfWork.systemMode(). * This is intentionally
    a slim, embedded implementation (no external library) so the pattern stays discoverable
    within the package.'
  dmlOperations:
  - delete
  - insert
  - update
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: EventBus
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Logger
  sharingModel: with
  status: Active
---

## Purpose

This is the unit-of-work member of the framework layer: callers register records as new, dirty or deleted and register platform events as they work, and one commitWork call does all the writing, so individual services do not each issue their own DML. Inserts go first in the caller-declared type order and then for any type not named in that order, followed by updates and then deletes, with a savepoint taken up front that is rolled back before the exception is rethrown if any step fails. Platform events are published only after that DML has come through cleanly, and a publish failure is written to Logger instead of being raised, so a caller cannot tell from commitWork that an event was dropped. Writes default to user mode so CRUD and field-level security are enforced, and the systemMode factory is the deliberate opt-out from that. Only the test class constructs it inside this repo, so the production callers the pattern is meant to serve are not visible here.
