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
  contentDigest: sha256:6927afb5235a44487e6d5eecc8afdc064542945415975c13df8c09664c974b05
  state: draft
limitations: []
profile:
  digest: sha256:32e8b969d158d223b90242bbc860f5d2edffeb6897a40d9d4a9795fc7518cd5a
  id: salesforce.custom-field
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:dcaa1099652afc8960f04cf1b56f1d8e0da35e01a49695ed9c56c39c02e3bf3a
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/objects/Time_Log__c/fields/Service_Request__c.field-meta.xml
    sourceDigest: sha256:0dcb8d9f7526d7ee8f9f5677be96ce4ebd8c06ddc0bc3c09be20ba31b232879a
subject:
  fullName: Time_Log__c.Service_Request__c
  metadataType: CustomField
  namespace: null
typeFacts:
  fullName: Service_Request__c
  label: Service Request
  object: Time_Log__c
  referenceTo:
  - Service_Request__c
  references:
  - assurance: source-exact
    kind: belongs-to
    target: Time_Log__c
  - assurance: source-exact
    kind: relationship
    target: Service_Request__c
  relationshipLabel: Time Log
  relationshipName: Time_Log
  relationshipOrder: 0
  reparentableMasterDetail: false
  trackHistory: false
  type: MasterDetail
  writeRequiresMasterRead: false
---

## Purpose

This is the parent link that makes a time log a detail of exactly one service request: an entry cannot exist without a request, it is deleted along with the request, and it cannot be moved to a different request afterwards because reparenting is switched off. The relationship also supplies the whole access model for Time_Log__c, whose sharing is set to follow the parent, so anyone who can see a service request can see its time logs, and editing a log requires write access on the request rather than mere read. On the request side it surfaces the entries as a Time Log related list. No rollup summary field on Service_Request__c aggregates across this relationship, so nothing in this repo totals a request's logged effort on the parent record.
