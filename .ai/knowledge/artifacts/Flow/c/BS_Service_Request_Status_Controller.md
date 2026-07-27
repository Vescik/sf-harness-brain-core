---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  intentionalErrors: source-exact
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  intentionalErrors: full
  typeFacts: full
intentionalErrors:
- basis: source-declared
  elementApiName: Inavlid_Class_Change
  elementLabel: Inavlid Class Change
  kind: flow-custom-error
  limitations: []
  messageTemplate: Invalid Status change
  originTag: customErrors
  presentation:
    mode: record
  reachability:
    decisionGuards:
    - Validate_Service_Request_Status_Change [default]
    triggerContext: Service_Request__c / CreateAndUpdate / RecordBeforeSave
    truncated: false
keywords: []
lifecycle:
  contentDigest: sha256:66838d4841042673401518010a66edba7d1fa3a89c4f48d5a197949bb26c0ff9
  state: draft
limitations: []
profile:
  digest: sha256:0cac1405840a5cd6ceb010714f644864e0e1859d4bc4106c3e2a459a2a0b31a7
  id: salesforce.flow
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:b14c26b64e3b32a631729e31d8da4aa43392b2946b8165e1c098f64e349eab62
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/flows/BS_Service_Request_Status_Controller.flow-meta.xml
    sourceDigest: sha256:28936b9254199a59cb707904b03c35b7ef2a2b25b4800c32ac5c32a1611b475b
subject:
  fullName: BS_Service_Request_Status_Controller
  metadataType: Flow
  namespace: null
typeFacts:
  processType: AutoLaunchedFlow
  references:
  - assurance: source-exact
    kind: operates-on
    target: Service_Request__c
  - assurance: source-exact
    kind: references-field
    target: Service_Request__c.Status__c
  status: Obsolete
  trigger:
    object: Service_Request__c
    recordTriggerType: CreateAndUpdate
    type: RecordBeforeSave
---

## Purpose

Gates status movement on a service request: it compares the prior status with the incoming one before the record saves and lets the save proceed only for the pairs it lists, so status is meant to move along a fixed path rather than jump anywhere. Anything the rules do not match falls to the default outcome, which raises a record-level custom error reading "Invalid Status change" with no field attached, so the message lands on the whole record. The allowed pairs are written entirely as opaque codes from s_1 to s_6, taken from a restricted value set named Status that is not present in this repo, so which business statuses those transitions actually permit cannot be read from the source. Every rule also requires a prior status value, and no listed outcome can therefore match an insert even though the flow is registered for creates as well as updates.
