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
  contentDigest: sha256:5c5189d82c6e233d5e11532e3b5636d925ab33e540a03ecdb590a62ab279b2f0
  state: draft
limitations: []
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:b6f7ebf8384e7c07c23dbe2e0915748871b27e49000014c8832abf802a2e8f70
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/LoggerTest.cls
    sourceDigest: sha256:5ca460e8edee04ba6b931b882de2459c9ed16ec9ab4b80203db320e94e4b236e
subject:
  fullName: LoggerTest
  metadataType: ApexClass
  namespace: null
typeFacts:
  annotations:
  - IsTest
  apiVersion: '62.0'
  declarationKind: class
  isTest: true
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: IllegalArgumentException
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Logger
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Message__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Level__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Message__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Source__c
  - assurance: source-derived-heuristic
    kind: object-token
    target: Stack_Trace__c
  - assurance: source-derived-heuristic
    kind: queries-object
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: soql-field
    target: LogEntry__c.Source__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: LogEntry__c.Level__c
  - assurance: source-derived-heuristic
    kind: var-field-ref
    target: LogEntry__c.Message__c
  sharingModel: omitted
  soqlObjects:
  - LogEntry__c
  status: Active
---

## Purpose

Pins Logger's buffer-and-flush contract from the caller's side: that one call at each of the four levels followed by a single flush persists exactly four rows attributed to that source; that a caught exception passed to the error entry point lands as a row at level ERROR whose message still carries the exception's own text alongside the captured stack; and that flushing an empty buffer writes nothing at all. Between them these fix the parts other classes lean on — that flush is safe to call unconditionally, that a batch of calls collapses into one write, and that exception detail survives into the stored row. The system-mode insert and the swallowing of the flush's own DML errors are not covered by these tests.
