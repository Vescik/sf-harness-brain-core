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
  contentDigest: sha256:bc14542af236c2fca03836461cb748d17f6d0253bb62484662f3ee45a537a221
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
  sourceTreeDigest: sha256:42d7494146e8b2e21aa5c9cc0232080993dec8ebd565a3d56cd402d585dcb27a
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/ServiceLocatorTest.cls
    sourceDigest: sha256:54c863b02a1ba82b58a26347feb5c2b4211c04881294f045869d65cc21cad8d6
subject:
  fullName: ServiceLocatorTest
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - IsTest
  apiVersion: '62.0'
  declarationKind: class
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: MockGreeter
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: ServiceLocator
  sharingModel: omitted
  status: Active
---

## Purpose

This test pins the two ends of ServiceLocator resolution. It confirms that an instance registered through the test-only mock hook is what comes back from a resolve call, and that the returned object really satisfies the interface it was registered under, so the mock path can stand in for a real binding. It also confirms that asking for a name with no binding raises ServiceLocatorException rather than returning null or an empty result. The interface and its implementation are declared inside the test class itself, so nothing here depends on binding metadata existing in the org; the consequence is that the metadata-driven lookup, the namespace fallback, and the unloadable-class failure remain unpinned by this class.
