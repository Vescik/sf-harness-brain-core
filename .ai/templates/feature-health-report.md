# Template: Feature Health Report

<!--
Used by skill: check-feature-coverage (invoked via /feature-health, or by the Test Strategist).
Output location: output/feature-health/<featureId>.md
Source: docs/archive/HARNESS_BLUEPRINT.md section 13. All 6 sections are mandatory — a section with no
content gets an explicit "none", it is never silently dropped.
-->

# Feature Health: <Feature title>

## 1. Header

- Feature ID: `<featureId>`
- Title: `<title>`
- BRD attached: `<yes — analyzed in full | no>`
- Generated on: `<date>`

## 2. Coverage summary

<!-- One sentence: full / partial / serious gaps. -->

## 3. Gaps

<!-- Requirements from the Feature/BRD with no covering User Story. If none: "None found." -->

- `<requirement>` — not covered by any Story

## 4. Orphans

<!--
Stories with no clear link to the Feature/BRD. Mark explicitly: this is a signal to check,
not automatically an error (e.g. a technical/enabler story is legitimate).
-->

- `<Story ID> - <title>` — `<why it does not map to any requirement>`

## 5. Open questions

<!-- Ambiguities on either side (Feature/BRD wording or Story wording). -->

## 6. Early warnings

<!--
Conflicts with .ai/knowledge/known-limitations.md, if any Story touches a known managed
package limitation. Catching this here is cheaper than after the design phase.
-->
