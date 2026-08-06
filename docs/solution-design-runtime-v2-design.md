# Solution Design Runtime v2 — bounded evidence loop

Date: 2026-08-06

Status: proposed design; no implementation is included in this document

Scope: replacement of the current Solution Design runtime, not a change to the model or its
reasoning ability

## 1. Executive decision

Keep the public Solution Design loop:

```text
design_open -> design_check -> resolve exactly one next action -> design_apply -> design_check
            -> design_submit -> human decision -> persisted handoff
```

Replace the current low-level state machine behind that loop. Runtime v2 must assume that the
agent will sometimes:

- choose an unsuitable evidence source;
- repeat the same question;
- supply an incomplete `design_apply` payload;
- treat a human answer as a technical fact;
- edit `design.md` between state mutations;
- continue calling tools after no further progress is possible.

The runtime, not the prompt, must make those behaviours bounded and recoverable. The agent may
remain unchanged. Correctness cannot depend on the model remembering operation schemas, selecting
the right authority, deduplicating its own questions, or recognising that a loop has stalled.

This is a clean replacement, not another compatibility layer. The workspace is not yet in
organizational use, so v1 Design Cases do not justify permanent migration machinery or two live
semantics. Public tool names needed by the existing Solution Designer remain stable; deprecated
v1 state, operations, schemas, renderers and implementation-time lifecycle are removed in the
same phases that replace them.

## 2. Evidence from the failed behavioural run

The ADO 242050 run is the acceptance baseline for this design. It exposed a product failure that
the existing structural tests did not:

1. ADO was unavailable at intake.
2. Knowledge had no approved package entry.
3. Repository and org evidence could not establish the package extension point.
4. The runtime repeatedly routed the same uncertainty to a human.
5. `N/A` became a structurally complete human receipt without answering the technical question.
6. The agent inspected operation schemas and source code to learn how to advance the case.
7. Adding the required `D-001` narrative anchor invalidated `caseVersion`; the agent replayed the
   same structured update.
8. A one-field proposal required rule verdicts, decision links, a verification contract, generated
   tables and repeated gates, yet still ended OPEN without a candidate.

The run did retain two valid properties: it changed no Salesforce metadata and did not silently
assert unsupported package behaviour. Runtime v2 preserves those properties without treating
non-completion as success.

## 3. Goals and non-goals

### 3.1 Goals

- Produce a useful design or one terminal, precise blocker through a bounded number of actions.
- Preserve the evidence loop, Knowledge reuse, managed-package constraints, org sampling and
  digest-bound human approval.
- Make the next executable action explicit and runtime-authored.
- Treat uncertainty as first-class state without converting it into a fact.
- Make process depth proportional to the design's actual risk and complexity.
- Generate the required Solution Artefacts table:

  | Object | Artefact Type | API Name | Description |
  |---|---|---|---|

- Keep Windows as the primary supported platform and macOS as a required secondary platform.
- Prefer Python standard-library implementation and existing admitted dependencies. Add no new
  community runtime dependency unless a separate security admission proves it necessary.
- Remove superseded v1 implementation in the replacement phase that makes it unreachable.

### 3.2 Non-goals

- Improving or retraining the agent.
- Letting a human opinion masquerade as package, schema or deployed-state evidence.
- Guessing package internals when Knowledge, vendor material and org evidence are unavailable.
- Deploying, retrieving broadly, mutating org data or changing `force-app/`.
- Replacing the existing Knowledge store or Salesforce read-only facade.
- Running a target-organization or target-managed-package pilot as part of this implementation.
- Owning Development, QA or final implementation review inside the Solution Design runtime.

## 4. Invariants that remain hard

Only controls protecting a real integrity or authority boundary remain unconditional blockers:

1. **No org mutation.** Solution Design remains read-only against Salesforce and ADO.
2. **No model approval.** Candidate and risk decisions still require native VS Code elicitation
   from a named human.
3. **Immutable approval identity.** Human approval binds the exact candidate digest.
4. **Facts retain source authority.** Model prose and an unsupported human assertion cannot prove
   package behaviour, schema, source state, deployed state or absence.
5. **Unknown is not Safe.** A package-facing mutation with unknown ownership or extension support
   cannot receive a Safe verdict.
6. **Explicit uncertainty is not evidence.** It can become a constraint, implementation
   prerequisite or accepted risk, but never changes a claim's status to confirmed.
7. **AC coverage is machine-checkable.** Every in-scope AC maps to at least one artefact or an
   explicit no-change decision and to planned verification.
8. **Persisted state outranks chat.** Candidate, approval and handoff remain reconstructible from
   the repository without conversation history.

Everything else is either derived automatically, conditional on a concrete trigger, or advisory.

## 5. Architecture

### 5.1 One runtime process

Replace the Node server -> NDJSON worker -> Python core chain with one Python MCP process:

```text
VS Code MCP
    |
    v
solution_design_mcp_server.py
    |-- case store and candidate snapshot
    |-- gate compiler
    |-- action compiler
    |-- evidence planner
    |-- renderer
    `-- adapters
         |-- ADO intake adapter
         |-- Knowledge and repository adapters
         `-- reference importer for Salesforce review envelopes
```

The process uses the Python standard library for JSON-RPC framing, path handling, hashing,
temporary files and locking. Existing admitted `jsonschema` and PyYAML may remain where already
required by the workspace. No MCP SDK or additional framework is introduced merely to replace a
small stdio protocol surface.

Per-case access uses an operating-system lock held only during a mutation:

- Windows: `msvcrt.locking`;
- macOS/Linux: `fcntl.flock`;
- one explicit lock file per case;
- no TTL, stale-lock quarantine or process-spawn journal is required because the OS releases the
  lock when the process exits.

Writes use a same-directory temporary file, flush, `fsync` where supported and `os.replace`.
Candidate directories are written completely under a temporary name and renamed only after their
manifest and digest validate.

### 5.2 Stable public tools

The existing Solution Designer may keep its current loop and public grants. Runtime v2 preserves:

- `design_open`
- `design_context`
- `design_check`
- `design_apply`
- the governed evidence import tools
- `design_submit`
- `design_request_human_input`
- `design_request_candidate_decision`
- `design_request_writer_transfer`
- `design_start_development` as a handoff boundary only

Internally there are no 18 public operation kinds. `design_apply` accepts two typed modes:

1. `designPatch` — current/target/delta, artefacts, decisions, constraints and verification;
2. `actionResolution` — resolve the exact `nextAction` returned by the runtime.

Its MCP schema uses `oneOf` with closed payloads. The tool definition exposes every required
field. The agent never needs to inspect Python code, tests or the state schema to construct an
operation.

### 5.3 Small canonical state

Persist only authored or authoritative facts:

```text
case
|-- identity and writer
|-- workflow state and stateVersion
|-- intake
|   |-- source locator/revision/status
|   `-- acceptance criteria
|-- design
|   |-- currentState
|   |-- targetState
|   |-- delta
|   |-- artefacts
|   |-- decisions
|   |-- constraints
|   `-- verification
|-- claims
|   `-- evidence or explicit uncertainty
|-- action ledger
`-- candidate reference
```

Do not persist separate copies of:

- `nextFocus`;
- applicable concerns;
- applicable rule verdicts that merely say PASS;
- generated questions;
- generated tables;
- risk tier;
- coverage matrices;
- document anchors.

Those are deterministic projections. Persist only an exception, material decision, evidence
receipt, accepted constraint or failed rule. This removes drift between authored questions,
computed concerns and rendered output.

### 5.4 Separate state concurrency from narrative currency

Runtime v2 replaces `caseVersion` with two independent values returned together:

- `stateVersion` — opaque token over structured state only; required for state mutations;
- `narrativeDigest` — current `design.md` digest; observed and validated at submit.

Editing `design.md` does not invalidate a structured mutation. `design_submit` takes a per-case
lock, reloads the newest state and narrative, renders generated sections, validates both and
creates one candidate snapshot atomically. Candidate digest binds both.

Decision anchors are renderer-owned. A decision `D-001` automatically renders an anchor and row;
the agent is never required to edit the narrative solely to satisfy a machine gate.

## 6. Compiled next action

`design_check` no longer returns only a route category. It returns at most one executable
`nextAction`:

```json
{
  "result": "OPEN",
  "status": "draft",
  "progress": "actionable",
  "nextAction": {
    "actionId": "ACT-0042",
    "kind": "external-read",
    "reason": "Confirm whether the target object permits a subscriber-owned custom field.",
    "tool": "salesforce-readonly/review_object_contract",
    "arguments": {
      "objectApiName": "Example__DeliveryGroup__c"
    },
    "continuationTool": "solution-design/design_apply",
    "continuationMode": "actionResolution-with-receiptRef",
    "retryPolicy": "once-per-org-and-package-fingerprint"
  }
}
```

For an internal state update, it returns the exact `design_apply` shape. For human input, it
returns the obligation identifier; the runtime owns the question wording and available outcomes.

Properties:

- the runtime chooses authority and tool from the claim type;
- only one action is active at a time;
- an `actionId` is idempotent;
- replay returns the original result and cannot create another question or receipt;
- an agent-supplied target or authority cannot override the action;
- a new action is issued only after material state or evidence changes.

The existing route (`requirements`, `grounding`, `design`, `verification`, `human-input`) may remain
as explanatory metadata, but it is not the execution contract.

## 7. Bounded evidence planner

### 7.1 Claim-driven source selection

The runtime derives an evidence need from a material claim, then selects the narrowest sufficient
source:

| Claim | First source | Fallback | Human may establish |
|---|---|---|---|
| Approved requirement/business intent | ADO revision | requirement owner | intent only |
| Customer-owned intended source | approved Knowledge | repository receipt | no |
| Accessible deployed schema | object contract | controlled sandbox test | no |
| Record-driven configuration shape | bounded SOQL envelope | accountable SME | meaning, not observed values |
| Package extension support | versioned vendor/package rule | controlled observation | explicit uncertainty decision only |
| Production volume | production-authoritative source | production owner | bounded estimate with stated scope |

`NO_ENTRY`, unavailable transport and incomplete enumeration are evidence outcomes, not new
questions by themselves.

### 7.2 Attempt budget

For one claim fingerprint:

- one attempt per technical source and source fingerprint;
- one clarification from a human for a fact within that person's authority;
- one uncertainty decision when the technical fact remains unavailable;
- no automatic retry until configuration, source revision, package version or org identity changes.

The claim fingerprint includes assertion type, subject, package/org scope and required authority.
Two differently worded questions about the same claim resolve to the same fingerprint.

`design_check` may refresh executor-owned local sources such as ADO, Knowledge and repository
receipts within this budget. Salesforce reads stay behind the existing read-only facade: the
runtime returns the exact external call and a continuation token, rather than asking the agent to
invent a query or import mapping. Object-contract and installed-package responses gain the same
ignored, content-addressed transient-envelope pattern already used by SOQL. `design_apply`
re-opens and verifies that envelope from `receiptRef`; the model never transcribes the contract
into evidence and no new public import tool is required.

### 7.3 Degradation outcomes

After sources are exhausted, classify the unknown:

1. **Design-blocking fact** — different answers lead to materially different or potentially
   undeployable designs. Status becomes `blocked`; no candidate is created.
2. **Implementation prerequisite** — the design contains a complete branch for pass and fail, so
   a reviewable candidate may be created, but it cannot enter `accepted` or produce a Development
   handoff until the prerequisite is confirmed. If there is no complete failure branch, the fact
   is design-blocking instead.
3. **Accepted risk** — a named risk owner may accept a bounded consequence. Acceptance does not
   confirm the underlying technical claim.
4. **Advisory unknown** — disclosed in the design but does not block candidate creation.

This distinction prevents both unsafe guessing and endless attempts to prove a fact that is not
available during Solution Design.

## 8. Human input contract

`design_request_human_input` binds only `caseId`, `stateVersion` and runtime-issued `actionId`.
The agent cannot provide `authorityRole`, arbitrary target IDs or the final question text.

The runtime selects one of three forms.

### 8.1 Fact form

- `Provide an answer within my authority`
- `I cannot establish this fact`
- `Cancel`

The first option requires a non-empty answer and, when the claim is technical, an eligible source
reference. `N/A`, `unknown`, `not sure` and equivalent normalized values cannot close a fact.
The second option marks the source exhausted; it does not create a complete fact receipt.

### 8.2 Uncertainty decision form

- `Use the conditional design`
- `Accept the stated risk`
- `Stop; evidence is required`

The form displays the exact unknown, consequence, constraint, fallback branch and affected
artefacts. It creates a decision or risk receipt, never a technical evidence receipt.

### 8.3 Candidate form

Candidate approval remains digest-bound and separate from pre-candidate fact/uncertainty input.
No answer given during candidate approval can introduce a new technical fact or modify scope.
A candidate with an unresolved implementation prerequisite may be inspected and challenged, but
the final approval action remains unavailable until the prerequisite closes.

One obligation can have at most one active elicitation. Repeated calls return
`ALREADY_REQUESTED` with the same action identifier and current status.

## 9. Proportional gates

### 9.1 Complexity profile

The runtime derives one profile; the model does not choose it.

**Simple** requires all of:

- at most two created or modified subscriber-owned artefacts;
- no delete/retire;
- no new save-transaction automation, integration, elevated permission or data migration;
- no configuration-record mass change;
- no unresolved package extension dependency;
- one transaction boundary.

**High risk** is triggered only by concrete conditions such as:

- package-facing save automation;
- destructive or irreversible migration;
- security boundary or elevated permission change;
- integration contract change;
- unresolved supported-extension dependency;
- material volume/limit exposure;
- accepted high-impact uncertainty.

Everything else is Standard. A custom object, configuration record or managed-package namespace
alone does not automatically make a design high risk.

### 9.2 Five gates

Replace the current ten-gate matrix with five product-facing gates:

| Gate | Blocks when |
|---|---|
| `INTAKE` | requirement/AC scope is missing, contradictory or unattested |
| `DESIGN` | there is no target/delta, affected artefact, decision or explicit no-change outcome |
| `EVIDENCE` | a design-critical claim has neither eligible evidence nor a valid degradation outcome |
| `COVERAGE` | an in-scope AC lacks an artefact/decision mapping or planned verification |
| `INTEGRITY` | candidate, approval, authority, version or immutable snapshot invariants fail |

Salesforce and organization principles are evaluated from triggers. Passing rules are derived and
not persisted. Only a violated rule, tension, constraint or required treatment appears in the
case. Independent challenge is required for High-risk candidates; Simple and Standard candidates
go directly to the named human unless a concrete rule requires challenge.

### 9.3 Required design depth

| Profile | Minimum |
|---|---|
| Simple | current/target/delta, artefacts, one decision or triviality reason, AC coverage, verification, limitations |
| Standard | Simple plus alternatives, transactions/security/rollback where triggered |
| High | Standard plus independent challenge, explicit risk treatments and evidence recheck plan |

One verification entry may cover multiple ACs when assertion, method, executor and expected
evidence are genuinely identical. The runtime should not force one row per AC.

## 10. Human document

The default `design.md` contains five mandatory sections:

1. Outcome and scope
2. Current state -> target state -> delta
3. Solution Artefacts
4. Decisions, constraints and known limitations
5. Verification and rollback

Optional sections for configuration records, security, transactions, integrations, migration,
volume and observability appear only when triggered. Empty sections are not generated.

The Solution Artefacts projection is always:

| Object | Artefact Type | API Name | Description |
|---|---|---|---|
| `Example__DeliveryGroup__c` | Custom Field — Formula | `Provisional_Status__c` | Derives the requested status without modifying package-owned metadata. |

Internal IDs, rule verdicts, receipts and gate details belong in the machine state or a compact
evidence appendix, not the main design. A reviewer can still inspect them through
`design_context(view="audit")`.

## 11. State and terminal behaviour

Keep the existing public `READY`, `OPEN`, `MALFORMED` vocabulary so the unchanged agent can
continue its loop. Add explicit progress semantics:

| `result` | `status` | Meaning |
|---|---|---|
| `OPEN` | `draft` | one actionable next step exists |
| `OPEN` | `awaiting_human_input` | one elicitation is pending; do not create another |
| `OPEN` | `blocked` | no current closure path; retry only after one named dependency changes |
| `READY` | `draft` | candidate may be created |
| `READY` | candidate/review/approval states | immutable workflow transition in progress |

A blocked response contains:

- one blocker statement;
- the missing authority/evidence;
- whether a conditional design is possible;
- the exact event that permits reopening;
- `nextAction: null` and `retryableNow: false`.

Repeated `design_check` returns the same short payload. It does not add receipts, questions or
new prose.

## 12. Boundary with Development and Review

Solution Design ends after:

1. candidate creation;
2. independent challenge when required;
3. human approval;
4. a persisted handoff to the existing work-record lifecycle.

Implementation divergence, verification executions, Development/Review status and final verdict
belong to the existing downstream work record. Runtime v2 does not maintain a second P7 lifecycle.
`design_start_development` validates the accepted candidate and unresolved implementation
prerequisites, emits the handoff and stops owning workflow state.

Compatibility wrappers may exist only inside the replacement commit that migrates callers. They
must not persist after all active grants and tests point at the downstream lifecycle.

## 13. Implementation phases

### P0 — behavioural baseline and contract freeze

Deliverables:

- encode the ADO 242050 behavioural run as a sanitized scenario;
- record current call count, human prompts, retries, final status and document size;
- define the v2 state, action and candidate schemas;
- freeze the hard invariants and public tool-name compatibility list.

Exit:

- the scenario fails against v1 for the expected reasons;
- no implementation is accepted without improving the behavioural outcome;
- structural test counts are explicitly non-acceptance evidence.

### P1 — single-process store and small state

Deliverables:

- Python MCP server and OS-lock adapter;
- state v2 with authored facts only;
- independent `stateVersion` and `narrativeDigest`;
- candidate snapshot/digest path;
- deterministic v2 renderer.

Removal in the same phase:

- Node-to-worker NDJSON bridge;
- lease TTL/quarantine machinery used only by that bridge;
- v1 state schema and duplicate derived collections after their v2 replacements pass tests.

Exit:

- Windows and macOS atomic-write/concurrency tests pass;
- editing the narrative never causes a stale structured write;
- a process crash cannot produce a valid partial candidate.

### P2 — action compiler and typed `design_apply`

Deliverables:

- one runtime-authored `nextAction`;
- closed `oneOf` schemas for `designPatch` and `actionResolution`;
- action idempotency and fingerprint deduplication;
- concise context/audit views.

Removal in the same phase:

- the 18 stringly typed v1 operation kinds;
- model-facing payloads that accept arbitrary authority, target or status;
- tests that construct readiness through direct `record.json` edits.

Exit:

- no scenario requires reading repository code to form a tool call;
- duplicate or replayed actions do not change state;
- an invalid payload names the exact missing field and returns the valid schema fragment.

### P3 — evidence planner and degradation policy

Deliverables:

- claim fingerprints and per-source attempt budgets;
- automatic local ADO/Knowledge/repository evidence planning;
- exact Salesforce external-call packets, content-addressed object/package envelopes and
  continuation tokens;
- the four degradation outcomes;
- durable `blocked` semantics.

Removal in the same phase:

- unbounded probe/question retry behaviour;
- `NO_ENTRY` or unavailable transport becoming repeated human questions;
- generic human routing where no eligible human authority exists.

Exit:

- each source is attempted at most once per unchanged fingerprint;
- an unavailable ADO/Knowledge/org path reaches a stable outcome;
- no technical unknown can be converted to confirmed by risk acceptance.

### P4 — human decision forms

Deliverables:

- fact, uncertainty and candidate forms;
- runtime-owned wording and allowed outcomes;
- semantic handling of `N/A`, unknown and refusal;
- one-active-elicitation enforcement.

Removal in the same phase:

- arbitrary free-text human receipts marked complete solely because text is non-empty;
- agent-supplied `authorityRole`, target and question identity;
- repeated equivalent questions with new IDs.

Exit:

- `N/A` never closes a fact;
- a human can explicitly choose conditional design or stop;
- repeated requests return the same pending outcome without a second prompt.

### P5 — proportional gates and adaptive document

Deliverables:

- Simple/Standard/High classifier;
- five v2 gates;
- trigger-derived principle evaluation;
- five-section base document and conditional sections;
- required Solution Artefacts table;
- runtime-owned decision anchors.

Removal in the same phase:

- 17 empty scaffold sections;
- persisted PASS verdicts and applicable-concern bookkeeping;
- anchor-presence gate against agent-authored prose;
- risk triggers based only on broad artefact categories.

Exit:

- the one-field scenario produces a compact design without irrelevant sections;
- Simple work is not sent through high-risk challenge without a concrete trigger;
- every AC remains traceable to a design outcome and verification.

### P6 — downstream handoff and v1 retirement

Deliverables:

- accepted-candidate handoff to the existing work-record lifecycle;
- one downstream owner for implementation divergence and verification;
- updated contracts, capability map, validator and repo map;
- complete retired-surface manifest.

Removal in the same phase:

- Solution Design P7 implementation/review state and receipts;
- obsolete schemas, renderers, operations, tests and documentation;
- compatibility wrappers once all active callers are migrated.

Exit:

- repository-wide reachability checks find no v1 mutation path;
- only one implementation/review lifecycle remains;
- no dual state or fallback lane is shipped.

### P7 — behavioural qualification

Qualification is Windows-first and includes macOS parity. It does not include a target
organization/package pilot.

Required scenarios:

1. simple one-field design with nine ACs;
2. ADO unavailable;
3. Knowledge `NO_ENTRY`;
4. Salesforce review dependency unavailable;
5. human responds `N/A`;
6. agent repeats the same question and action;
7. narrative edit between check and apply;
8. package-owned object with unknown extension support;
9. record-driven configuration requiring bounded sampling;
10. high-risk design requiring independent challenge.

Exit budgets for the simple degraded scenario:

- at most one attempt per unchanged evidence source;
- at most two human elicitations in the whole case: one fact/uncertainty decision and one candidate
  approval;
- no duplicate questions;
- no stale replay caused by narrative editing;
- no direct schema/code inspection;
- no more than six mutating Solution Design calls before READY or stable blocked;
- one compact blocker when completion is impossible;
- no empty generated sections;
- zero Salesforce or ADO writes.

The qualification report must show call traces and outcomes, not only unit-test totals.

## 14. Test strategy

### 14.1 Unit tests

- canonical state and candidate digests;
- Windows/Unix lock adapters;
- atomic replace and crash recovery;
- action fingerprinting and idempotency;
- authority matrix;
- semantic human outcomes;
- complexity classifier and five gates;
- renderer and artefact table;
- candidate/handoff prerequisite enforcement.

### 14.2 Contract tests

- every MCP tool has a closed schema;
- every `nextAction` names an available tool and valid arguments;
- public prompt grants match server tools;
- no model-facing input can set receipt authority, workflow status or approval identity;
- source-authority and managed-package rules remain stricter than general Salesforce guidance.

### 14.3 Behavioural tests

Use a scripted deliberately imperfect client, not a helper that directly constructs READY state.
The client should:

- omit optional fields;
- replay old actions;
- answer `N/A`;
- edit narrative before applying state;
- retry an unavailable source;
- attempt to turn accepted uncertainty into technical evidence.

The runtime passes only when it corrects, bounds or terminates each behaviour without requiring a
prompt change.

### 14.4 Live host checks

- native Windows VS Code MCP initialization and elicitation;
- Windows lock and `os.replace` behaviour;
- macOS parity;
- VS Code Policy Diagnostics for human decision tools;
- optional dev org transport smoke may prove mechanics only and remains explicitly
  non-representative of the future target package.

## 15. Observability and budgets

Persist no chain-of-thought or raw record data. Emit sanitized diagnostic counters:

- action count by kind;
- evidence attempts by source and fingerprint;
- duplicate/replay count;
- human elicitation count;
- transitions to blocked/READY;
- design profile and generated-section count;
- elapsed runtime time, excluding human waiting time;
- response byte size.

Recommended initial budgets, adjustable only from behavioural evidence:

- `design_check` response <= 4 KiB in summary view;
- one active next action;
- one active human elicitation;
- one evidence attempt per unchanged source fingerprint;
- zero persisted raw SOQL rows outside the existing governed exception;
- Simple design base document contains five mandatory sections.

Budget overflow returns a named diagnostic and stable blocker. It never silently truncates an
authority, AC list or candidate input.

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Simplification admits weak designs | hard authority/integrity invariants remain; uncertainty is explicit and cannot become Safe |
| Conditional design postpones a critical decision | classify design-blocking facts separately; Development handoff refuses unresolved prerequisites |
| Agent ignores `nextAction` | all other mutations are rejected with the same canonical action packet; no parallel question can be created |
| Single Python server has protocol defects | small stdio contract fixtures, native VS Code tests, no external SDK surface |
| Removing v1 breaks hidden consumers | repository-wide grants/reachability audit and same-phase caller migration before deletion |
| Complexity classifier under-classifies | High triggers are positive and testable; rule violations can always elevate, never lower, risk |
| Eight users collide | per-case OS locks, immutable candidates and Git integration checks; different cases remain independent |
| Security regresses through a new dependency | no new dependency by default; any exception requires separate admission, lock and vulnerability review |

## 17. Definition of Done

Runtime v2 is complete only when all of the following are true:

- the unchanged Solution Designer can execute the existing public loop;
- ADO 242050-equivalent work reaches a compact candidate or one stable blocker within the stated
  budgets;
- `N/A` cannot close a factual obligation;
- repeated questions/actions are idempotent;
- narrative editing cannot invalidate structured-state writes;
- no agent reads implementation code to discover an operation payload;
- Solution Artefacts use `Object | Artefact Type | API Name | Description`;
- package, Knowledge, Known Limitations, Managed Package Constraints, Organization Principles and
  Salesforce Best Practices are evaluated through the claim/gate compiler;
- Simple work receives Simple ceremony;
- candidate approval remains native-human and digest-bound;
- Development cannot begin with a design-blocking fact or unresolved implementation prerequisite;
- implementation/review state exists in one downstream lifecycle only;
- all v1 mutation paths, schemas, renderers, tests and documentation are removed or explicitly
  retained as historical decision records;
- Windows-first and macOS behavioural qualification passes;
- validation output distinguishes structural correctness from behavioural product readiness.

## 18. Expected outcome for the failed example

For the observed one-field case, v2 should behave as follows:

1. `design_open` records ADO as temporarily unavailable and does not retry it within the same
   source fingerprint.
2. The requirement owner attests the nine ACs once if no approved ADO revision is available.
3. The runtime derives one proposed subscriber-owned formula-field artefact.
4. Knowledge `NO_ENTRY` is recorded as a source outcome, not an absence fact and not another human
   question.
5. The runtime requests the exact object contract once.
6. If extension support remains unknown, it asks one uncertainty decision: use a conditional
   design with a pre-implementation verification branch, or stop for vendor evidence.
7. Choosing the conditional branch creates a constraint, not a technical fact.
8. `design_apply` records the artefact, decision and shared verification in one typed patch.
9. The renderer creates the decision anchor and compact document automatically.
10. `design_submit` either creates a constrained candidate or returns one stable package-extension
    blocker. A constrained candidate cannot be finally approved or handed to Development until its
    prerequisite closes. The runtime does not ask the same question again.

The quality target is not merely fewer calls. It is a runtime in which every call either adds
material information, records a real decision, or terminates an unavailable path.
