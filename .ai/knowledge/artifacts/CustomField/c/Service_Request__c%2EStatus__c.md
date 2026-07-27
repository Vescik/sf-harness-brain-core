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
  contentDigest: sha256:333a4b3bd12c8026a7c199a00e6b72971050c35d2d9033aab9e4b96a3b283a38
  state: draft
limitations:
- Nothing in this repository defines which field drives the path component the record
  page header carries.
- The Status value set is org-wide and not defined in this repository, so the business
  meaning behind the stored status codes cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:d4d0f26e41a56af63488cca4dd6273a9de1f4dc3d31df526a7f63ee3d40b127e
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Status__c.field-meta.xml
    sourceDigest: sha256:a30adecdd1dc07d0ff979049224bbb94c0429327d1387d27f8a999de5c94afa9
subject:
  fullName: Service_Request__c.Status__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Status__c
  label: Request Status
  object: Service_Request__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: uses-value-set
    target: Status
  required: true
  trackHistory: false
  type: Picklist
  valueSetName: Status
---

## Purpose

Holds where a service request sits in its lifecycle, and it is the only value on the object with any enforcement written against it. The values come from a restricted, org-wide Status value set that is not defined in this repo — the same set Service Task's own status draws on — so the human-readable meaning behind the stored codes is not visible from the source here. A before-save record-triggered flow, BS_Service_Request_Status_Controller, gates every change: from s_1 it permits only s_6, s_5, or s_3; from s_6 only s_2, s_5, or s_3; from s_2 only s_4, s_5, or s_3; anything else falls to the default outcome, which raises the custom error "Invalid Status change" as a record-level message. The flow's rule labels — Allowed New, Allowed Assigned, Allowed InProgress — name the prior state each branch guards, and s_5 and s_3 are reachable from every gated state, which reads as the terminal pair. Two things the source shows plainly and a reader should not miss: the flow is configured to fire on create as well as update, yet no rule can match a create, where the prior record carries no status, so an insert falls straight through to the error branch; and the flow's own metadata marks it Obsolete, so as committed this gate is not in force. The field is required, and the record page marks it required again and carries a path component in its header, though nothing in this repo defines which field that path is driven by.
