---
name: check-feature-coverage
description: Analyze whether a Feature (and attached BRD) is fully covered by its User Stories — gaps, orphans, open questions and early warnings against known package limitations. Ends on a markdown report in output/feature-health/.
---

# Skill: check-feature-coverage

The actual procedure behind the `/feature-health` prompt (blueprint section 11) — a gate run
**before** the Solution Design phase: a gap caught now costs a conversation; caught after
design, it costs a redesign.

Two authorized consumers (blueprint section 3): the `/feature-health` gate (unchanged owner)
and the **Test Strategist**, when its own judgment requires checking Feature/BRD coverage.

## Procedure

1. **Fetch the full hierarchy**: call the `fetch-ado-item` skill with
   `mode=hierarchy childDetail=full` — the Feature plus every Story in full text. If the
   Feature has a BRD attached, fetch the attachment's **full content** — this is the single
   deliberate exception to the "attachments: metadata in cache, content on demand" rule
   (blueprint section 13): here the content IS the subject of the analysis.
2. **Extract requirements** from the Feature/BRD — an explicit list if the structure allows,
   otherwise inferred from the text (and marked as inferred).
3. **Extract what each User Story actually claims** — title, description, acceptance criteria
   if present.
4. **Cross-check in both directions**:
   - **Gaps** — requirements with no covering Story.
   - **Orphans** — Stories with no clear link to the Feature/BRD. Not automatically wrong
     (e.g. a technical/enabler story is legitimate) — but worth naming explicitly.
5. **Check `.ai/knowledge/known-limitations.md`** against the objects/functions the Stories
   touch — a conflict with a package limitation caught here is far cheaper than after design.
6. **Save the report** to `output/feature-health/<featureId>.md` using
   `.ai/templates/feature-health-report.md`: coverage summary, gaps, orphans, open questions,
   early warnings. All six sections, none dropped.
