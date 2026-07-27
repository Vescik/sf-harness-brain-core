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
  contentDigest: sha256:e5cd2aedfb886a810d20793f009c34438619b42eada50481e453d23e8b14aa42
  state: draft
limitations:
- No binding records ship in this repository, so which logical service names are bound
  to which implementation classes cannot be read from source.
profile:
  digest: sha256:850a05f5e27ba994b11c25331c7b63a6c5721b2d16723e4d4897afa3bcf72b23
  id: salesforce.custom-object
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:1137bd84e0e477a8a242949e894f43599b4b2991d7ebc93ea16b5963f0e77a77
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/ServiceBinding__mdt/ServiceBinding__mdt.object-meta.xml
    sourceDigest: sha256:89578718317cd36de2c6af1d8d79ed089c14f461166551e0babc2e5bcf29154e
subject:
  fullName: ServiceBinding__mdt
  metadataType: CustomObject
  namespace: null
typeFacts:
  description: Maps a logical interface/binding name to a concrete Apex implementation
    class. Public so subscribers can override bindings (documented extension point).
  label: Service Binding
  objectKind: customMetadataType
  pluralLabel: Service Bindings
---

## Purpose

A dependency-injection binding table: one record names a logical service or interface and records the Apex class that implements it, together with the namespace that class should be resolved in. ServiceLocator loads every record into a cache and instantiates the bound class on demand, raising its own exception when a requested name has no record or when the named class cannot be loaded, so callers depend on a binding name and never on a concrete type, and tests can swap in a mock instead. Unlike the package's protected feature flags this object is deliberately public, and the object description states that subscribers can ship their own record to override an implementation, making the table the package's documented extension point. No binding records ship in this repo, so the bindings actually in play are not visible from source.
