# Solution Design Runtime Contract

Status: normative
Schema version: 1
Gate evaluator: `sd-gate-v1`
Canonicalizer: `sd-c14n-v1`

This contract defines the Design Case: one canonical, versioned unit of Solution Design work.
It replaces the five-phase narrative Solution Design flow. `scripts/solution_design_core.py`
is the single implementation of every rule below; agent-facing text may explain it but never
redefines it.

## 1. Case identity and layout

```text
.ai/change-records/<case-id>/
├── record.json          # record.json.solutionDesign is the machine authority
├── design.md            # human narrative; never duplicates status or approvals
├── evidence/EV-<id>.json
├── candidates/<candidate-id>/{design.md,bundle.json}
├── approvals/AP-<id>.json
├── reviews/DR-<id>.json
├── divergences/DV-<id>.json
└── handoffs/HO-<id>.json
```

Case IDs are `ADO-<project-slug>-<item-id>` when an ADO item backs the work, otherwise
`SD-<date>-<stable-id>`. Binding an ADO item later does not change an existing identity. One case
is one accepted design lineage.

Runtime scratch — per-case leases, transaction journals, recovery metadata — lives outside the case
tree under `.ai/.runtime/solution-design/`. It is ignored, never cited as evidence and never
included in a candidate. Writer-transfer and candidate-decision receipts are `AP-*` records under
`approvals/`, because both are human decisions captured from the same elicitation surface.

## 2. Durable states

| State | Meaning | Designer may edit |
|---|---|---|
| `draft` | Active discovery/design/verification loop | yes |
| `awaiting_human_input` | A pre-candidate material question or risk acceptance needs a trusted human/vendor receipt | no candidate exists; alternative evidence reopens `draft` |
| `candidate` | Immutable snapshot created by a successful submit | no |
| `awaiting_design_review` | High-risk candidate awaiting independent challenge | no |
| `awaiting_human` | Candidate awaiting a named human decision | no |
| `accepted` | Exact candidate approved and eligible for Development | no |
| `development` | Implementation against an accepted candidate | no design edits |
| `review` | Implementation verification and independent final review | no design edits |
| `complete` | Accepted outcome and evidence complete | no |

`READY` is an evaluation result, not a state. There is **no generic `blocked` state**: a missing
dependency stays a routed OPEN obligation in `draft`, and a missing human decision uses
`awaiting_human_input`.

### Allowed transitions

```text
draft                 -> draft | awaiting_human_input | candidate
awaiting_human_input  -> draft
candidate             -> awaiting_design_review | awaiting_human | draft
awaiting_design_review-> awaiting_human | awaiting_human_input | draft
awaiting_human        -> accepted | draft
accepted              -> development | draft
development           -> review | draft
review                -> complete | development | draft
complete              -> (terminal)
```

Nothing may reach `accepted`, `development` or `complete` by any path not listed. There is no
generic `set-status` operation and no CLI mutation path.

### Draft focus

Within `draft`, `nextFocus` is computed from the open obligations, never set by the model. Route
priority is `requirements` → `grounding` → `design` → `verification` → `human-input`; `none` means
every gate is READY.

## 3. Versioning

`caseVersion` is opaque, formatted `cv1_<64 hex>`, and computed over `stateSequence`, the
normalized structured state and the current `design.md` byte digest. It excludes timestamps and
unrelated work-record state. Every read returns it; every mutation of an existing case requires
`expectedCaseVersion`; first creation instead proves case-path absence atomically. A stale caller
receives the new token and reloads. The agent never manages a separate revision plus document hash.

`design.md` is normalized to UTF-8 without BOM and LF before rendering or hashing, so Windows,
macOS and Linux produce identical digests.

`candidateDigest` is a separate, immutable approval identity formatted `sha256:<64 hex>`. It is
never reused as `caseVersion`, and `caseVersion` is never reused as an approval identity.

Both use `sd-c14n-v1`: recursive Unicode NFC on strings and keys with collision rejection; only
null, booleans, strings, arrays, objects and signed 64-bit integers (binary floats forbidden);
`json.dumps(..., ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))`;
UTF-8 without BOM and without a trailing newline. `work_record.py`'s `canonical_bytes` is a
different, laxer serializer and is never substituted for it.

## 4. Closure authority

A blocking question declares which authorities may answer it. Model prose is never one of them.

| Assertion | Sufficient authority |
|---|---|
| Intended customer-owned source state | current source-exact Knowledge, or a governed repository receipt once the source-authority migration is active |
| Accessible deployed schema | current object-contract receipt |
| Current sandbox record/configuration observation | current SOQL/config snapshot receipt |
| Business meaning | approved ADO artifact or an accountable human SME |
| Package limitation / extension point | versioned vendor source, approved package rule, or an explicit human decision acknowledging uncertainty |
| Production volume | production-authoritative human or system source; a sandbox count is not sufficient |
| Absence | complete enumeration with permission, pagination and freshness proof |

A receipt closes an obligation only when its `sourceType` is allowed for the demanded authority,
its status is `current`, its `validationPurpose` is `design-evidence`, its `environmentFitness` is
not `non-representative-devmp`, and its completeness is not `incomplete`. A
`transport-mechanics` / `non-representative-devmp` receipt may prove that the transport works; it
can never close a target-package concern, question, decision or risk.

`NEEDS_HUMAN` is a routing status, never a successful closure.

## 5. Computed gates

`design_check` is read-only and runs every gate against one locked snapshot. It returns `READY`,
`OPEN` or `MALFORMED`, and each gap carries gate ID, affected entity, required closure type and
route. It never edits the narrative and never closes an obligation. `design_submit` is the only
design completeness gate; an `OPEN` draft stays editable.

| Gate | Enforces |
|---|---|
| SD-G0 | runtime capability ceiling — an unimplemented capability is always OPEN and can never be accepted as N/A or human risk acceptance |
| SD-G1 | requirement integrity: source present and current, hierarchy detail, stable AC identity, explicit inclusion/exclusion, no unresolved contradiction |
| SD-G2 | scope integrity: identity/type/action, ownership and host ownership, evidence on mutating targets, extension-point status on package-facing targets, a disposition on every frontier component, a typed classification behind every configuration artefact |
| SD-G3 | concern coverage and claim/evidence integrity, including concerns the model failed to author |
| SD-G4 | probe closure, fitness re-entry and durable replay for rechecked hard probes |
| SD-G5 | decision integrity: anchors, links, alternatives or a justified triviality reason, no contested premise |
| SD-G6 | risk integrity: assessed impact, mitigation or a pre-candidate human acceptance receipt, required closures, verification where mitigation must be proven |
| SD-G7 | every in-scope AC maps to a decision, an implementation target and a Verification Contract entry |
| SD-G8 | rule verdicts, hard-rule violations, tension mitigation, limitation linkage, rule-definition digest freshness |
| SD-G9 | blocking questions, placeholders in authored narrative, decision anchors, document currency |
| SD-G10 | candidate risk tier — selects the next transition, never blocks candidate creation |

Concern applicability is computed from ACs, artefact type and action, component and host ownership,
configuration classification and requirement scope. An applicable concern is closed only by a
design treatment, a linked material question/decision/risk route, or a concrete risk plus
verification. A `not-applicable` disposition needs a trigger-aware rationale, and it is rejected
whenever the triggers are in fact present. The word "considered" closes nothing.

## 6. Rule applicability

`config/solution-design-rule-map.json` selects which canonical rule IDs enter a case. Validation is
bidirectional: every mapped ID exists exactly once across the instruction sources, no mapping
references an unknown rule, and **every canonical hard-rule ID has either a selector entry or an
explicit `manualApplicability` entry with defined blocking semantics**. An unmapped hard rule fails
registry validation rather than disappearing from the engine. A hard rule's severity cannot be
lowered by a lower tier. A candidate binds the exact normalized rule definition digest; if the rule
text changes, the verdict is stale.

`manualApplicability` blocking semantics:

- `enforced-outside-design-gates` — a hook, role guard, transition or receipt schema enforces it,
  so no designer verdict is meaningful;
- `designer-declared-verdict-required` — applicability is not derivable from structured scope
  facts, so the designer owes a verdict whenever the design relies on it;
- `never-blocks-submit` — the rule constrains rule authoring or process, not one case.

## 7. Capability ceiling

`config/solution-design-capabilities.json` declares the implemented concern profiles, probe and
evidence kinds, component and configuration actions, adapters, risk policies, transitions and
generated-output sections, with a `gateEvaluatorVersion`. A case that needs a capability the
manifest does not declare receives an `UNSUPPORTED_CAPABILITY` OPEN obligation and cannot create a
candidate, approval or handoff. Every candidate binds the manifest digest and evaluator version;
unless a migration is explicitly classified non-material and proven compatible, a version mismatch
supersedes a pending candidate/approval/handoff and returns the case to `draft`.

## 8. Ownership

Eight users work concurrently across different cases. Exactly one named writer may mutate a case at
a time; everyone else is read-only for it. Transfer is an explicit current-owner elicitation that
names the target writer, changes the state sequence, emits a transfer receipt and invalidates the
prior writer's `caseVersion`; v1 does not require the target to accept. The filesystem lease
protects one checkout — it is not a distributed lock. Candidate bundles bind
`submittedFromCaseVersion` so repository reconciliation and CI reject sibling candidates from one
parent version before integration. An agent acting for the assigned writer shares that identity and
never invents or transfers ownership.

## 9. What this contract does not permit

- Making Markdown the authoritative workflow state.
- Blocking an ordinary draft write on completeness.
- Closing a hard obligation with model prose, `N/A`, or the word "considered".
- Approving through chat, a terminal command, or a model-supplied decision field.
- Introducing a material business answer, package guarantee or accepted risk at approval time: it
  becomes pre-candidate evidence first, recomputes the gates, and is hashed into a new candidate.
- Keeping a second Solution Design creation or approval semantics reachable.
