---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
boundary:
  anchors:
  - Service_Request__c
  - Ticket__c
  depth: 1
  exclude: []
  hubs:
  - Account
  - Contact
  - ProductCategory
  - User
  include: []
  membershipAssuranceFloor: source-exact
candidateKeywords: []
keywords: []
kind: feature-entry
lifecycle:
  contentDigest: sha256:e965b14f10e4b5f9eaea9fb0f43538e0b4010b31a606ad9aed0f1c5bf57aa2c4
  state: draft
limitations: []
schemaVersion: 1
sensitivity: internal-sanitized
subject:
  name: Service Delivery
  slug: service-delivery
---

## Purpose

Two service-desk record trees kept in one boundary because both are how work reaches a technician: a service request, with the tasks worked and the hours booked against it, and a ticket, with its comments.

A Service Request is raised against an Account and a Contact, carries a requested service, priority, request and due dates, an hours estimate, a status and an assigned technician. Service Task and Time Log are its master-detail children, so work performed and time booked cannot outlive the request they belong to. A before-save flow gates status movement against a fixed list of allowed prior-to-new pairs and raises a record-level custom error on anything else — but that flow is marked Obsolete, so nothing in source currently constrains status at all. Its transitions are written entirely as opaque codes s_1 to s_6 drawn from a value set that is not in this repository.

A Ticket carries a subject, description, priority, status, due date and a roll-up of its comments. Ticket Comment is its master-detail child and can be marked internal. Two validation rules guard it: one refuses to close a ticket with no comments, the other constrains the due date.

READ THIS BEFORE APPROVING. The two halves share no data link. No field on Service_Request__c points at Ticket__c or the reverse, and no automation in this repository spans them; they are united here only by the claim that both are service-desk intake, which is a business judgement and not something the source shows. If the business runs them as separate processes this boundary should be split into two features.

A second naming trap sits inside the ticket half: Ticket__c.Category__c is a lookup to the STANDARD ProductCategory object, while the custom Category__c object is something else entirely and points the other way, at Ticket__c. The two are unrelated despite the shared word.

The boundary stops at Account, Contact, User and ProductCategory because they are shared across the whole org. Note that on the current reverse-only traversal those hub declarations stop nothing — the walk never reaches them — so they are stated intent, not an active constraint, until traversal direction changes.

Not covered here: the Visualforce page ObjectLinks and its controller, and the two Lightning record pages, have no entry home in the current profile set, so their behaviour is not governed Knowledge. The framework classes (unit of work, selector, domain, trigger handler, logger, feature flags, service locator) are shared infrastructure and are deliberately not members of this feature.
