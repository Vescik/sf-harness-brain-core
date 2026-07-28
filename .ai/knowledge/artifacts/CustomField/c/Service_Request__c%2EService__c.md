---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:b5a249f543228334ad4ca587757e837319087c5792262cddbc17b71838e3b4d2
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:b5a249f543228334ad4ca587757e837319087c5792262cddbc17b71838e3b4d2
  state: approved
limitations:
- Nothing in this package branches on the field, so what the classification is used
  for once it is set is not visible here.
- The Service_Type value set is org-wide and not defined in this repository, so the
  available categories cannot be read from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:edb0467457622806ad41814bcddd36ed0a758b0555ca294c3a58ee0270c654cd
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Service__c.field-meta.xml
    sourceDigest: sha256:35ec521d7f1164631e6257940ce6294655d4182a802b6213477ae2323cb28266
subject:
  fullName: Service_Request__c.Service__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Service__c
  label: Service Type
  object: Service_Request__c
  picklistRestricted: true
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: uses-value-set
    target: Service_Type
  required: false
  trackHistory: false
  type: Picklist
  valueSetName: Service_Type
---

## Purpose

Classifies what kind of work a service request is for, picked from a restricted, org-wide Service_Type value set that is not defined in this repo, so the available categories are not visible from the source here. Its label and its API name disagree — it presents to users as Service Type but is addressed in queries, reports, and formulas as Service__c — which is the trap to watch for when tracing references to it. It is optional and renders as an ordinary editable field on the Service Request Record Lightning page, immediately after Request Priority. Nothing in this package branches on it, defaults it, or requires it, so the source does not show what the classification is used for once it is set.
