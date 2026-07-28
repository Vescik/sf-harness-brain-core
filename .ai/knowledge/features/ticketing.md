---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:14:19Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:66d3a21b118c0480d7fe6feabd2473ce99823c219a4fe0f7accb5f17a130fbc4
boundary:
  anchors:
  - Ticket__c
  depth: 3
  exclude: []
  hubs:
  - ProductCategory
  - User
  include: []
  membershipAssuranceFloor: source-exact
candidateKeywords: []
keywords: []
kind: feature-entry
lifecycle:
  contentDigest: sha256:66d3a21b118c0480d7fe6feabd2473ce99823c219a4fe0f7accb5f17a130fbc4
  state: approved
limitations: []
schemaVersion: 1
sensitivity: internal-sanitized
subject:
  name: Ticketing
  slug: ticketing
---

## Purpose

A ticket is an issue raised and worked through a conversation: a subject and description, a priority, a status, a due date, and the comments that accumulate against it.

Ticket__c is the parent. Ticket_Comment__c is its master-detail child and can be flagged internal, so a comment thread distinguishes what the customer sees from what the team says to itself. CommentCount__c rolls the comments up, and that roll-up is not decoration: the Comment_Validation rule refuses to save a ticket whose status is Closed while the count is still zero, so a ticket cannot be closed silently. Due_Date_Validation constrains the date.

### The Category trap

`Ticket__c.Category__c` is a lookup to the **standard `ProductCategory`** object. The custom `Category__c` object is something else entirely and points the other way — it carries its own lookup at `Category__c.Ticket__c`, plus a default priority and SLA hours. The two share a word and nothing else. Anyone reading "category" on this feature has to know which one is meant.

### How to get there

A Request Item Lightning page exists, and a Visualforce page `ObjectLinks` with an Apex controller is present in the org. Neither FlexiPage nor ApexPage has an entry profile, so none of that is governed Knowledge and how a user reaches a ticket is not established here.

### What is not automated

`Ticket_Update` is the only flow on the object and it is stored as an **InvalidDraft** — it references a field that no longer exists, which Salesforce records as `null__NotFound`. It does nothing. Category__c.DefaultPriority__c and SLA_Hours__c have no consumer in this repository at all, so whatever they were meant to drive is not built here or not committed.

### Boundary

Anchored on Ticket__c at depth 3: the ticket, its comments, the custom Category__c that points at it, and their fields. It stops at User and ProductCategory, which are shared.

This feature and Service Request share **zero** members — measured, 16 + 15 = 31 and 26 + 20 = 46 across the two boundaries. No field on either object points at the other and no automation spans them. If the business runs them as a single intake process, merge them deliberately rather than by accident.
