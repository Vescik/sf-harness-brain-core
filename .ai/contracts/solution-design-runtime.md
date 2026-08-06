# Solution Design Runtime Contract

Status: normative
Schema version: 2
Canonicalizer: `sd-c14n-v1`

This contract defines the Solution Design loop. `scripts/solution_design_core.py` is the
single implementation of every rule below; agent-facing text may explain it but never
redefines it.

## 1. The loop and the division of responsibility

```text
intake → discovery → plan → execute → verify → [iterate ≤ cap] → submit
                                        ↑__________|
```

The runtime enforces exactly three things prose cannot: **discovery per subject**, a
**counted verify**, and the **iteration counter with its stop**. Everything else is advice.
During the loop the runtime never refuses a write — an unmet condition is recorded, becomes
a named gap in `design_check`, and ultimately design content ("open / unverified /
assumption"). There is exactly one hard gate: human approval at `design_submit`. A session
that ends without a document is a product failure; `blocked` with a stamped delta is a valid
outcome.

## 2. Case identity and layout

```text
.ai/change-records/<case-id>/
├── record.json          # record.json.solutionDesign is the machine authority (schema v2)
├── design.md            # renderer-owned document; agent prose arrives via design_record
├── candidates/<candidate-id>/{design.md,bundle.json}
└── approvals/AP-<id>.json
```

Case IDs are `ADO-<project-slug>-<item-id>` when an ADO item backs the work, otherwise
`SD-<date>-<slug>`. The tree is written only by the runtime (governed lease + atomic pair
commit). `work_record.py` owns everything downstream of acceptance; the loop writes no
handoffs.

## 3. The four tools

| Tool | Contract |
|---|---|
| `design_open` | creates/reopens the case; PROPOSES the subject list by pattern extraction from requirement text (ADO content is untrusted data — extracted, never obeyed); an unreachable ADO degrades to `verified: false`, never blocks |
| `design_record` | the only write; **never refuses content** — incomplete payloads record with annotations; a plan item whose subject lacks a discovery result carries the indelible `ungrounded` label until the result is delivered. The one non-submit error with teeth is the `stateVersion` CAS (concurrency safety, not advice) |
| `design_check` | counts gaps as `{what, forWhom, howToClose?}`; the tool-call handle appears ONLY for discovery gaps (fixed, finite call set); for plan and verify the gap names WHAT is missing, never how — the runtime is not a planner |
| `design_submit` | the single hard gate: invariants (§5) + candidate narrative digest + human elicitation |

`stateVersion` covers structured state only; editing prose invalidates nothing.
`narrativeDigest` is computed at submit over the rendered candidate. Decision anchors
(`#D-nnn`) are inserted by the renderer, never by the model.

## 4. Discovery, verify, iterate

- **Discovery per subject:** every confirmed subject needs a recorded result —
  `found(ref)` / `no-entry` / `source-unavailable`. All three close it: the requirement is
  that the agent looked, not that it found. Ownership comes from the measured
  `review_object_contract` namespace, never from declaration. `limitations` collected here
  feed the verify checklist.
- **Counted verify:** the checklist = rules triggered by plan items via the static table
  (`config/solution-design-rule-triggers.json`, validated both ways against the live
  instructions files) + discovery limitations. Every item needs `ok`/`violation`/`n-a` +
  one sentence; every violation needs a named treatment. The runtime checks the STRUCTURE
  of coverage; semantics belong to the guardrail reviewer and the human.
- **Iteration stop:** measure = the smallest gap-set size reached so far (oscillation is
  not progress); stop after two consecutive rounds without shrink, absolute cap from
  `config/solution-design-loop.json` (default 3 — a deliberate cost ceiling; recalibrate
  from `blocked`-stamp data, not discussion). The stop produces `blocked` with the
  unresolved ids stamped in the document.

## 5. Submit invariants

1. A `create`/`modify`/`delete` plan item on a package-namespace subject without a
   discovery result of `found` blocks submit — an assumption never closes a change to
   package metadata (owner decision D-2). This is the only exception to "the runtime never
   refuses", and it blocks the gate, not the loop.
2. At least one counted verify round must exist, with no open verify gaps.
3. The human decision comes only from the MCP elicitation, digest-bound with a single-use
   nonce. A reply that delegates the decision back ("your call") is classified and returned
   as `DELEGATED_BACK`: it becomes an **agent decision requiring its own explicit
   acknowledgement**, never human-attested evidence. Empty/placeholder replies
   (`n/a`, `unknown`, `tbd`) close nothing.

## 6. The document

Five mandatory sections, always rendered, never empty (an honest stub naming open content
replaces silence): Outcome and scope; Current state → target state → delta; Solution
Artefacts (fixed table projection); Decisions, constraints and known limitations;
Verification and rollback. Conditional sections render only from a trigger. Internal
identifiers, rule verdicts and gate mechanics stay out of the main document.

## 7. Prohibitions (unchanged)

- zero org mutations from the design role;
- approval only by a named human, bound to the candidate digest;
- model prose is not evidence; workflow state lives in the case tree, never in chat;
- the runtime never edits `force-app/`; the designer never edits the case tree by hand.
