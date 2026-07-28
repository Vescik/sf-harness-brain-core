---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:14:07Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:d8beb884415121fe8950ff2d85a4188e519a163fbc96d98c1ab212ae2eed4c19
boundary:
  anchors:
  - Service_Request__c
  depth: 3
  exclude: []
  hubs:
  - Account
  - Contact
  - User
  include: []
  membershipAssuranceFloor: source-exact
candidateKeywords: []
keywords: []
kind: feature-entry
lifecycle:
  contentDigest: sha256:d8beb884415121fe8950ff2d85a4188e519a163fbc96d98c1ab212ae2eed4c19
  state: approved
limitations: []
schemaVersion: 1
sensitivity: internal-sanitized
subject:
  name: Service Request
  slug: service-request
---

## Purpose

A service request is work asked for by a customer and delivered by a technician: who asked, what they asked for, when it is due, who is doing it, and how long it took.

Service_Request__c is the parent record, raised against an Account and a Contact, carrying the requested service, a priority, request and due dates, an hours estimate, a status and an assigned technician. Service_Task__c and Time_Log__c are its master-detail children, so the individual pieces of work and the hours booked against them are owned by the request and cannot outlive it. Time is recorded twice over: Service_Task__c.Work_Hours__c against a task, Time_Log__c.Hours__c against the request directly, and nothing in this repository reconciles the two or rolls either up.

### How to get there

A Service Request record page exists as a Lightning page. Neither the page nor any navigation to it is governed Knowledge — FlexiPage has no entry profile — so how a user actually arrives at one of these records is not established here.

### What is not automated

The only automation on the object is a before-save flow that gates status movement against a fixed list of allowed prior-to-new transitions and raises a record-level custom error on anything else. That flow is marked **Obsolete**, and every one of its rules requires a prior status value, so no rule can match an insert even though the flow is registered for creates. Nothing in source currently constrains status movement at all. Its transitions are written entirely as opaque codes s_1 to s_6 drawn from a value set that is not in this repository.

Nothing reads Approved__c on a time log, nothing enforces the hours estimate, and no roll-up exists from either time-recording path.

### Boundary

Anchored on Service_Request__c at depth 3: the request, its two children, and their fields. It stops at Account, Contact and User, which are shared across the whole org.

This feature and Ticketing share **zero** members — measured, 16 + 15 = 31 and 26 + 20 = 46 across the two boundaries. No field on either object points at the other and no automation spans them. They were one draft feature until that was measured. If the business runs them as a single intake process, merge them deliberately rather than by accident.
