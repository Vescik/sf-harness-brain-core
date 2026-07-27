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
  contentDigest: sha256:63bab92cb3f055fea10c80b12fc3ae39b053b3e1d615fe2f8c800cd75500b589
  state: draft
limitations:
- The listed rows come from the running org's global describe and its own domain,
  so which objects a search actually returns cannot be read from this repository's
  source.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:b3519ada9b16c40e6429fc4d1b84e95be105831ff7c16a7ddda98372aef75ce9
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/ObjectLinksCtrl.cls
    sourceDigest: sha256:0e7a620e035de440f3291d56b1e90b92e46bb3077f57fef00438b225fa3d0cbb
subject:
  fullName: ObjectLinksCtrl
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '65.0'
  declarationKind: class
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Row
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: RowSorter
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: URL
  sharingModel: with
  status: Active
---

## Purpose

Backing controller for the ObjectLinks Visualforce page, an in-org lookup that turns a search word into a clickable list of objects. On page load it reads the search word from the page's f query-string parameter, walks every object returned by the global describe, and keeps those whose API name or label contains that word case-insensitively; an absent or empty parameter keeps everything. Each match becomes a row of API name, label and a deep link to that object's Lightning list view built on the org's own domain, and the rows are sorted alphabetically by label then API name before the page renders them as a bulleted list of links. Nothing is queried or written — the whole result comes from schema describes — and there is no test class for this controller in the repository.
