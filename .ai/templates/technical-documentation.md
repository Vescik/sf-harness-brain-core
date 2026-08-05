# Template: Technical Documentation

<!--
Used by skill: generate-technical-documentation (invoked via /document-metadata-change).
Output location: output/documentation/<itemId>.md
Source: historical design blueprint section 13 (git tag design-history). All 9 sections are mandatory — a section with no
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
approved Knowledge Entries (relation edges) where applicable. If no impact: say so explicitly.
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

<!-- Include any relevant limitations recorded on the approved Knowledge Entries. -->

## 9. Verification Contract

<!--
Projection of the Design Case Verification Contract (`record.json.solutionDesign.verificationContract`)
for the accepted candidate, plus any formally linked ADO Test Cases those entries reference.
This is the canonical verification plan: every in-scope acceptance criterion appears here with an
assertion, method, pass criteria, expected evidence and executor/stage. It is not a relevance
ranking and it is never model-ranked. When the change has no Design Case, state that explicitly
and list only the formally linked Test Cases from the synced inventory.
-->

| Verification ID | AC | Assertion | Method | Pass criteria | Expected evidence | Executor / Stage |
|---|---|---|---|---|---|---|

### Formally linked Test Cases

<!--
Confirmed relations only, from the synced inventory (`/sync-test-cases`). An empty list is stated
explicitly, never inferred as absence of coverage.
-->
