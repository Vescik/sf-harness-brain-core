# Template: Technical Documentation

<!--
Used by skill: generate-technical-documentation (invoked via /document-metadata-change).
Output location: output/documentation/<itemId>.md
Source: HARNESS_BLUEPRINT.md section 13. All 9 sections are mandatory — a section with no
content gets an explicit "none" / explanation, it is never silently dropped.
-->

# <Title>

## 1. Header

- Work item ID: `<itemId>`
- Work item type: `<Feature | User Story | Bug | Task>`
- Generated on: `<date>`

## 2. Business summary

<!-- 2-3 sentences, business language, sourced from the ADO work item (fetch-ado-item). -->

## 3. Scope of change

<!--
List of components from the development's package.xml — type + name, each with one sentence
on what it is for.
	The operational v2 contract defines the fourth column as "Manual steps reference" so the
	technical-documentation and release-handover tables share one stable schema.
-->

| Component type | Name | Purpose (one sentence) | Manual steps reference |
|---|---|---|---|
| `<e.g. CustomField>` | `<API name>` | `<why this component exists in this change>` | `<see section 7 / none>` |

## 4. Technical details per component

<!-- One subsection per component from section 3. -->

### `<Component name>`

<!-- What it does, how it is configured/implemented, anything non-obvious. -->

## 5. Impact on existing system

<!--
Reference .github/instructions/managed-package-constraints.instructions.md and
.ai/knowledge/object-relations.md where applicable. If no impact: say so explicitly.
-->

## 6. Verification approach

<!-- How the change was / can be verified on the sandbox. -->

## 7. Manual deployment steps

<!--
Filled from the human's answer to the question asked at the end of the flow
	(`vscode/askQuestions`, verified against the current VS Code tool inventory).
If the answer is "none", this section keeps an explicit "None" — it never disappears.
-->

## 8. Known limitations / open questions

<!-- Include anything relevant from .ai/knowledge/known-limitations.md. -->

## 9. Suggested Test Cases

<!--
Result of the suggest-test-cases skill. Grouped by confidence. Each suggestion carries an
explicit match rationale. These are UNCONFIRMED suggestions for review — do not confuse with
the "Tests" section of release-handover.md, which lists formally linked (confirmed) Test Cases.
If there are no hits: state that explicitly and suggest /sync-test-cases for the relevant
suite instead of leaving an empty section.
-->

### High probability

- `<Test Case ID>` — `<title>` — rationale: `<why this matches>`

### Worth checking

- `<Test Case ID>` — `<title>` — rationale: `<why this might match>`
