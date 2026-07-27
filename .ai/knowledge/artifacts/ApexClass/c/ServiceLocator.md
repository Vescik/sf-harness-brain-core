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
  contentDigest: sha256:47704651c5ff7d158f16f88240c7cf2f2ef00d5f4bfa5a30ba8d53c3f65e7fbe
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
  sourceTreeDigest: sha256:5ff8c0dd234563509d6f5e06f6fbe37e26f0c90bb68e7b625ede64f4cb8cdc97
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/ServiceLocator.cls
    sourceDigest: sha256:2b78bcfc321a3b9b688193c8f9d7f90c989d534729b61075c0a171c615e3b3a8
subject:
  fullName: ServiceLocator
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - TestVisible
  apiVersion: '62.0'
  declarationKind: class
  description: 'Dependency-injection entry point. Maps a logical interface name to
    a concrete implementing class via ServiceBinding__mdt, so callers depend on interfaces
    and tests can substitute mocks. Subscribers can override a binding by shipping
    their own ServiceBinding__mdt record (a documented extension point). * Type.forName
    is namespace-aware: inside the package, bare class names resolve against the package
    namespace automatically.'
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: ServiceBinding__mdt
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: ServiceLocatorException
  - assurance: source-derived-heuristic
    kind: object-token
    target: Implementation_Class__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Namespace_Prefix__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: ServiceBinding__mdt
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: ServiceBinding__mdt.Implementation_Class__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: ServiceBinding__mdt.Namespace_Prefix__c
  sharingModel: with
  status: Active
---

## Purpose

ServiceLocator is the dependency-injection seam of the framework: a caller asks for an implementation by a logical interface name and gets back a freshly constructed instance of whatever concrete class the binding metadata maps that name to, so call sites can hold an interface instead of a hard-coded class. The binding table is loaded once and cached for the rest of the transaction, and resolution first tries the namespace-qualified type before falling back to the bare class name, so a binding may name either a namespaced class or an unprefixed one. Failures are loud rather than silent: a name with no binding record, and a binding whose implementation class cannot be loaded, each raise the inner ServiceLocatorException instead of returning null. A test-visible map of mock instances is consulted before the binding table, which is the hook tests use to substitute a stub without creating any metadata record. In this repository nothing outside ServiceLocatorTest calls resolve and no binding records are checked in, so the production wiring this class exists to serve is not visible in the source.
