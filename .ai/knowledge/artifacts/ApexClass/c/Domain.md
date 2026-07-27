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
  contentDigest: sha256:7a8cf3360ea68f11911a6f863911dbee63b61768bdc0cf7d5535fd8bfb4e1ad9
  state: draft
limitations:
- No subclass of Domain exists in this repository, so what a concrete domain does
  with the trigger records and the prior-version map cannot be read from source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:ebb820bc3081bb590702ac8366c97ba2685bf8c9c282d0c63e97c1418dd10ead
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/Domain.cls
    sourceDigest: sha256:af601474f210e0a07a7c078768bb9c39265d28518a1e667582aa81975a2696b4
subject:
  fullName: Domain
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '62.0'
  declarationKind: class
  description: Abstract base for domain classes. A domain wraps the trigger records
    for one object and holds the per-object business rules invoked from that object's
    trigger handler. Domains contain NO SOQL and NO DML — they mutate in-memory records,
    add errors, and hand persistence to a UnitOfWork owned by the service/handler
    layer.
  kind: ApexClass
  sharingModel: with
  status: Active
---

## Purpose

Domain is the abstract base that per-object domain classes are meant to extend, holding the trigger's records and, when supplied, the map of their pre-update versions so subclasses can compare the two. It gives those subclasses two protected helpers over that pair: one to fetch the prior state of a record by id, and one to test whether a single field differs from it, treating a record with no prior version as changed so insert contexts read as a change on every field. The class deliberately carries no queries and no saves; its comment states that domains mutate records in memory and add errors while persistence is handed to a UnitOfWork owned by the handler or service layer, and the code holds to that. No subclass of Domain exists in this repository yet, so the layer is defined but not populated.
