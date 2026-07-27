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
  contentDigest: sha256:c5979ed8579cead9ca93fe915a7d47f1fe091b3c60909e7fa80878ca300616a2
  state: draft
limitations:
- The only consumer visible here is a Lightning record page, so anything outside this
  repository that populates or reads the link cannot be seen from source.
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:3aad505e92251c58aad3cd90f8267ac1aeccd78646fb8f6d7f9b6ad6dd48ee7f
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Service_Request__c/fields/Account__c.field-meta.xml
    sourceDigest: sha256:427ed7492248f68986e7c1b52990a6c85db5aa4674121d0226495470ecfa0ea3
subject:
  fullName: Service_Request__c.Account__c
  metadataType: CustomField
  namespace: null
typeFacts:
  deleteConstraint: SetNull
  fullName: Account__c
  label: Account
  object: Service_Request__c
  referenceTo:
  - Account
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Service_Request__c
  - assurance: source-exact
    kind: relationship
    target: Account
  relationshipLabel: Service Requests
  relationshipName: Service_Requests
  required: false
  trackHistory: false
  type: Lookup
---

## Purpose

Ties a service request to the customer organisation it was raised for, which is the only link from the request back to the standard customer record. The one consumer in this repo is the Service Request Lightning record page, where it sits in the detail column next to the contact and the assigned technician as a plain editable field; no Apex class, trigger, or flow here reads or populates it. Deleting the referenced account clears the link instead of blocking the delete, so a request can survive with no customer attached. Nothing in the source makes it mandatory or keeps it consistent with the contact chosen on the same record.
