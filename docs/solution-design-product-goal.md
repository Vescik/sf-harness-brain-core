# Solution Design — product goal

Status: normative. This document states **why Solution Design exists and what "working" means**.
It stands above every plan, diagnosis and runtime design for this workflow: a plan may change how
the goal is reached, but not the goal.

Scope test: **an element that does not serve §1 is out of scope.** That test is the reason this
document exists — without it, "more control" reads as "better product".

---

## 1. The goal

> Given an ADO work item or a written description, the agent delivers a solution design grounded in
> what actually exists in Knowledge and in the org, and verifies its own design several times
> against managed-package constraints, recorded limitations and organization principles — and the
> runtime helps it do that rather than getting in the way.

Three obligations sit inside that sentence, and all three are load-bearing:

1. **Deliver a design.** A session that ends without a document is a product failure, whatever the
   state machine says. Non-completion is not a safe outcome; it is an outcome with no value.
2. **Ground it in what exists.** Reuse before creation, and both stated against measured reality —
   Knowledge entries, the object contract, installed package facts — not against recollection.
3. **Check its own work.** Managed-package limits, recorded limitations and principles are reviewed
   by the agent against its own design, more than once, before a human is asked to approve it.

---

## 2. Who it serves, and what they get

| Reader | What they need from the output |
|---|---|
| The named human approver | One document they can read end to end, whose unknowns are visible before they approve, not after |
| The developer implementing it | An unambiguous list of artefacts to build, and what "done" means per acceptance criterion |
| The reviewer challenging it | The decisions and their alternatives, plus what evidence each rests on |
| The next agent touching this work | Persisted state that reconstructs the design without the chat transcript |

Nobody in that table needs internal identifiers, rule verdicts that passed, or gate mechanics in
the main document. Those belong to machine state or a compact evidence appendix.

---

## 3. What a good design looks like here

- Every in-scope acceptance criterion maps to an artefact, an explicit no-change decision, or a
  named open question — and to a planned verification.
- Every claim about existing state is labelled: measured, or assumed. An assumption is written
  down as an assumption, with its consequence, and survives into the approval screen.
- Ceremony is proportional to risk. A single formula field does not earn the process a data
  migration earns.
- The document is honest about what was not established. "We could not determine X, so the design
  branches" is a good design. "X is fine" without grounding is not.

---

## 4. Construction principles

1. **The runtime advises during the loop and refuses nothing. There is exactly one hard gate:
   human approval.** An unmet condition becomes content in the design — an open item, an
   assumption, an ungrounded label — never a refusal that ends the session empty-handed.
2. **The runtime enforces only what prose cannot.** Three things qualify: that discovery was
   actually performed per subject, that coverage is computed rather than declared, and that
   iteration has a stop. Everything else is guidance in the skill, agent and instruction files.
3. **Evidence is an annotation on the design, not a precondition for writing it.** Missing evidence
   changes a claim's label; it does not prevent the claim from being proposed and reviewed.
4. **Measure before asking a human.** A fact a governed read surface can return — package
   ownership, whether a field exists, an installed version — is read, not elicited. Humans are
   asked about business meaning, vendor guarantees and risk acceptance.
5. **Proportional depth.** The runtime derives how much process a design needs; the model does not
   choose it, and a broad artefact category alone does not make something high risk.
6. **Structural checks are not quality guarantees.** A deterministic checker verifies the
   *structure* of coverage, never the *correctness* of the design. Semantics are verified by an
   independent reviewer and by the human who approves. The number of gates is not a measure of
   quality, and this document refuses to let it become one.

---

## 5. Hard boundaries

These hold regardless of any plan:

- no org mutation from the design role; Salesforce and ADO access is read-only;
- approval is human, named, and bound to the exact candidate digest — a model never approves;
- model prose is not evidence, and an unsupported human assertion does not establish package
  behaviour, schema, deployed state or absence;
- an assumption never closes a change to metadata inside a package namespace;
- an answer that hands the decision back ("your call", "as you see fit") does not close a question;
- persisted state outranks the conversation: candidate, approval and handoff reconstruct from the
  repository alone.

---

## 6. How to tell it is working

Observable, without a baseline to compare against:

- **Deliverability** — a degraded session (sources unavailable) still produces a document with its
  gaps stamped on it, within a small, bounded number of calls.
- **Proportionality** — a one-field change produces a compact design, not a full ceremony.
- **Grounding** — every subject named in the acceptance criteria has a recorded lookup outcome
  before a plan item references it; items without one are visibly labelled.
- **Termination** — the loop either converges or stops at a named blocker with the remaining delta
  written down. It never spins.
- **Honesty** — what could not be established appears in the document, and no verification is
  claimed that was not run.

A failure of any of these is a product defect, even if every test passes.

---

## 7. Precedence

```text
solution-design-product-goal.md      (this document — why, and what "good" means)
    └── plans                        (how, in what order, at what cost)
            └── diagnoses/discovery  (what is broken today, and why)
```

A plan that cannot trace an element to §1 should drop that element rather than justify it. A
diagnosis explains the present; it does not set the target. Where a runtime design and this
document disagree, this document wins and the runtime design is amended.
