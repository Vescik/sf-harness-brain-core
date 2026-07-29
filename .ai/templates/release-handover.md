# Template: Release Handover

<!--
Used by skill: generate-release-handover (invoked via /release-handover, monthly).
Output location: output/handover/<month>.md
Source: historical design blueprint section 13 (git tag design-history).
Declarative-output rule (blueprint sections 3 and 11): the skill ends its work on this
markdown file. DOCX/PDF export is a separate, manual, human-triggered step via a VS Code
extension (Markdown PDF / vscode-pandoc) — never a script generated or run by the agent.

To change the handover document shape, edit THIS file only: headings, their order, and the
repeating item block are read from here at every run, and scripts/validate_handover_output.py
re-derives the expected structure from this file, so edits are enforced automatically on the
next run. Keep the repeat-per-item marker line below — it marks which block repeats per work
item; the render check and the harness audit (scripts/validate_harness.py) require exactly
one. Plain non-placeholder lines (the fallback texts) are treated as fixed text the skill
must reproduce exactly; relative markdown links in templates are link-checked by the audit.
-->

# Release Handover — <release period>

## Header

- Release period: `<month/year>`
- Generated on: `<date>`
- Source query: `<configured ado.releaseQueryId>`
- Query executed at: `<UTC timestamp>`
- Source completeness: `<complete | partial>`

## Handover description

<!-- General introduction: what this release covers, at business level. -->

## Table of contents

<!-- One line per item in the release. -->

- `<User Story ID> - <Title>`

---

<!-- The section below repeats for EVERY item in the release. -->
<!-- repeat-per-item -->

## <User Story ID> - <Title>

<!--
Single metadata line only. The full work-item metadata table (State, Story Points, BA,
Functional Consultant, Tags, ADO Revision) is intentionally NOT part of this document.
-->

Category: `<ADO Category field value>`

### Summary

<!-- AI-generated, 2-3 sentences, from the item's Description + Acceptance Criteria. -->

### Acceptance criteria

<!--
ALL acceptance criteria from the work item's Acceptance Criteria section, complete and in
their original order — never a selected/"key" subset, never reworded into new criteria,
never invented when the section is empty. One bullet per criterion. If the work item has
no Acceptance Criteria section, use exactly the fallback text below instead of the list.
-->

- `<Acceptance criterion>`

No acceptance criteria documented

### Technical table

<!--
Artifacts + manual steps, extracted from the natively linked wiki page (technical
documentation). Same columns as section 3 of technical-documentation.md — see the R2 note
there about the blueprint's "same 4 columns" reference.
If the item has NO attached documentation link: replace the table with exactly the fallback
line below — keep the [Missing Wiki Link] marker, the release manager searches the document
for it to add the link manually — never regenerate or guess the content.
-->

| Component type | Name | Purpose (one sentence) | Manual steps reference |
|---|---|---|---|

No published technical documentation — [Missing Wiki Link]

### Tests

<!--
Every formally linked Test Case (via fetch-ado-item includeTestCases=true — confirmed
coverage, NOT the unconfirmed suggestions from technical-documentation.md section 9),
listed regardless of execution status, Test Runs, or test environment.
One bullet per Test Case: the Test Case title only — no description, steps, outcome, or
any other detail. If there are no linked Test Cases, replace the bullet list with exactly
the fallback text below.
-->

- `<Test Case title>`

Tested based on acceptance criteria
