# Template: Release Handover

<!--
Used by skill: generate-release-handover (invoked via /release-handover, monthly).
Output location: output/handover/<month>.md
Source: HARNESS_BLUEPRINT.md section 13.
Declarative-output rule (blueprint sections 3 and 11): the skill ends its work on this
markdown file. DOCX/PDF export is a separate, manual, human-triggered step via a VS Code
extension (Markdown PDF / vscode-pandoc) — never a script generated or run by the agent.
-->

# Release Handover — <release period>

## Header

- Release period: `<month/year>`
- Generated on: `<date>`
- Source query: `<TU_WSTAW_QUERY_ID>` <!-- while empty: /release-handover cannot determine which items are in the release and cannot run -->

## Handover description

<!-- General introduction: what this release covers, at business level. -->

## Table of contents

<!-- One line per item in the release. -->

- `<User Story ID> - <Title>`

---

<!-- The section below repeats for EVERY item in the release. -->

## <User Story ID> - <Title>

### Summary

<!-- AI-generated, 2-3 sentences, from the item's Description + Acceptance Criteria. -->

### Technical table

<!--
Artifacts + manual steps, extracted from the natively linked wiki page (technical
documentation). Same columns as section 3 of technical-documentation.md — see the R2 note
there about the blueprint's "same 4 columns" reference.
If the item has NO linked documentation page: state explicitly "No published technical
documentation" — never regenerate or guess the content.
-->

| Component type | Name | Purpose (one sentence) | Manual steps reference |
|---|---|---|---|

### Tests

<!--
Names of formally linked Test Cases (via fetch-ado-item includeTestCases=true — confirmed
coverage, NOT the unconfirmed suggestions from technical-documentation.md section 9).
If there are no linked Test Cases, use exactly the fallback text below instead of leaving
the section empty.
-->

Tested based on acceptance criteria
