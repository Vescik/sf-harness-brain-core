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
  contentDigest: sha256:7e243f8500069e70fd22bd0e788be5cf8d4cf10e566720262416c3ab6b3fe6a8
  state: draft
limitations:
- The per-module test-data factory classes the header says build on this base are
  absent and no class here calls TestData, so its intended callers are not visible
  in this repository.
- The three capability permission sets wired into the full-access helper are not in
  this repository, so what access they grant cannot be read from source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:c87fbe86149e234398f7e7c245776572d3fb70214c63326dda3d524fe1026e1e
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/TestData.cls
    sourceDigest: sha256:08891f306dec0ad7be70fd14b6a40f0a2afee89bb9a6c4079efcbb2972deab69
subject:
  fullName: TestData
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - IsTest
  apiVersion: '62.0'
  declarationKind: class
  description: Base test-data utilities shared by every module's TestDataFactory_*.
    Provides running-user helpers and permission-set assignment so tests can exercise
    FLS/sharing as a real persona rather than as an admin. * Only referenced from
    @IsTest code; annotated so it is excluded from the org's production code footprint.
  dmlOperations:
  - insert
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: PermissionSetAssignment
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: User
  - assurance: source-derived-heuristic
    kind: queries-object
    target: PermissionSet
  - assurance: source-derived-heuristic
    kind: queries-object
    target: Profile
  - assurance: source-derived-heuristic
    kind: soql-field
    target: PermissionSet.Name
  - assurance: source-derived-heuristic
    kind: soql-field
    target: Profile.Name
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: PermissionSet.Id
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: Profile.Id
  sharingModel: omitted
  soqlObjects:
  - PermissionSet
  - Profile
  status: Active
---

## Purpose

TestData is the shared test-only helper that manufactures the persona a test runs as. It hands out a per-transaction counter and counter-plus-timestamp names so repeated runs do not collide on unique fields such as username and alias, and it creates a minimal Standard User and assigns permission sets looked up by API name. The point of that user, per the class header, is that tests execute inside a runAs block as an ordinary licensed persona, so user-mode queries and DML are actually exercised against real field-level and record-type access instead of passing trivially as the running administrator. Permission-set assignment is tolerant by design: a null or empty name list is a no-op and names that match no permission set are simply skipped, so a missing permission set produces a user with less access rather than a failed setup. Three named capability permission sets are wired into the full-access helper, but neither those permission sets nor the per-module factory classes the header says build on this base exist in this repository, and no class here calls TestData, so its intended callers are not visible in the source.
