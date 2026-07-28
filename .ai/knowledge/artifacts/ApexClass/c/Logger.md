---
approval:
  mechanism: copilot-chat-entry-confirmation
  reviewedAt: '2026-07-28T20:12:56Z'
  reviewedBy: Dominik Machowski
  reviewedContentDigest: sha256:fe20819b7be1014a2dc0684ff2b5bde29b52d76ee691582da0491b2dfd2b1515
assurance:
  typeFacts: source-derived-heuristic
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:fe20819b7be1014a2dc0684ff2b5bde29b52d76ee691582da0491b2dfd2b1515
  state: approved
limitations: []
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:5d858536956f2f27c387fbd3e38bbdc41f46e4155b5f5899a4f70ed48882a4be
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/Logger.cls
    sourceDigest: sha256:8cb69f17d04797bdf28de50a537db78d6b523efd281575cff40cc6bbb39cb204
subject:
  fullName: Logger
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '62.0'
  declarationKind: class
  description: 'Centralized structured logging to LogEntry__c. Buffers entries and
    flushes them in a single DML at the end of the transaction (or on explicit flush),
    running in system mode so logging never fails on FLS for the running user. * SYSTEM
    MODE: log writes are deliberately system-context so diagnostics are captured regardless
    of the caller''s object permissions. This is one of the few sanctioned system-mode
    paths in the package (see docs/conventions/security.md).'
  dmlOperations:
  - insert
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: BUFFER
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: LogEntry__c
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Request
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
    kind: object-token
    target: Transaction_Id__c
  sharingModel: without
  status: Active
---

## Purpose

Logger is the package's single logging facade: callers name a source and a message at DEBUG, INFO, WARN or ERROR, or hand it a caught exception so the type, message and stack trace are captured for them, and the entry is held in a static in-memory buffer rather than saved on the spot. Flushing writes everything accumulated so far in one insert and clears the buffer, so a transaction that logs many times still spends a single DML; each entry is stamped with the current request id so the rows from one transaction can be grouped afterwards, and long messages and stacks are trimmed to fit their fields. Two failure modes are absorbed on purpose: the insert runs in system mode so diagnostics are captured regardless of the running user's permissions, and any error raised by the flush itself is caught and only echoed to the debug log, so logging can never break the transaction it was recording. The class comment calls this out as one of the few sanctioned system-mode paths in the package. It is the failure sink the async finalizer and the unit-of-work write to when their work fails.
