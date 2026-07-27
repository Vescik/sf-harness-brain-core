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
  contentDigest: sha256:7ddf6c09584438f03c0052ad17990580404687f84b4ceb1037b66e3895a496ae
  state: draft
limitations:
- Nothing in this repository enqueues through AsyncOrchestrator, so the scheduling
  conflict detection, billing generation and sync consumers its header names are not
  visible here.
profile:
  digest: sha256:44befc9f4bd46b9096290865218f48ded970545375c83ba8a8ba463c5bace3b6
  id: salesforce.apex
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:dc8ba874def10a1d4eab28bad69bb9e75a6185cca9dd2620185bc604f8ae3368
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/classes/AsyncOrchestrator.cls
    sourceDigest: sha256:af8f3f66ffd474cc000a37d1c4d28f09c69fc5951e75fdb50d6935999359be58
subject:
  fullName: AsyncOrchestrator
  metadataType: ApexClass
  namespace: null
typeFacts:
  apiVersion: '62.0'
  declarationKind: class
  description: Thin helper for enqueuing Queueable jobs with a standard finalizer
    that captures job failures to the log. Centralizes async chaining so error handling
    is consistent across modules (scheduling conflict detection, billing generation,
    sync).
  kind: ApexClass
  references:
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: Logger
  - assurance: source-derived-heuristic
    kind: invokes-class
    target: LoggingFinalizer
  sharingModel: with
  status: Active
---

## Purpose

AsyncOrchestrator is the single sanctioned way to put a Queueable on the async queue, so that every background job in the package inherits the same failure handling instead of each caller inventing its own. Before enqueuing it checks whether the transaction has any queueable slots left and, when it does not, records a WARN log entry naming the job, flushes it, and returns null rather than letting the enqueue throw. Otherwise it enqueues the job with its own LoggingFinalizer attached, which fires when the job ends in an unhandled exception and writes an ERROR log entry carrying the async job id and the exception message, so a job that dies in the background is never silent. Its header comment names scheduling conflict detection, billing generation and sync as the intended consumers, but nothing in this repository enqueues through it yet.
