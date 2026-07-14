# force-app Knowledge Creation Architecture

Status: implemented, governed pilot

## Objective

Create reusable Salesforce Knowledge from the repository-root `force-app` without turning file
names, labels, model inference, dirty working-tree state, or generated prose into verified facts.
The workflow extends the existing schema-v3 claim/evidence/review lifecycle; it does not create a
parallel Markdown Knowledge store.

## Research basis

- Salesforce IDE deploy and retrieve commands operate on DX source format, which is designed for
  version-control workflows. This supports using committed source files as evidence of intended
  customer-owned state: [Salesforce Source Format](https://developer.salesforce.com/docs/platform/code-builder/guide/codebuilder-source-format.html).
- Metadata support varies by type and API version, so extractor coverage must be bounded and
  explicit rather than universal: [Salesforce Metadata Coverage Report](https://developer.salesforce.com/docs/metadata-coverage/53).
- Salesforce Code Analyzer v5 analyzes Apex, Visualforce, Flow, and Lightning source and can emit
  machine-readable findings. Those findings are a future quality/security evidence input, not
  business meaning: [Code Analyzer overview](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/code-analyzer.html).
- GitHub Copilot project skills are repository folders containing `SKILL.md` and optional
  resources, while custom agents provide scoped tools and role instructions. This implementation
  keeps deterministic procedures in hidden skills and routes public prompts to the existing
  guarded investigator: [Agent Skills](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills) and
  [custom agent configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration).

## Governed flow

```mermaid
flowchart LR
    A["root force-app"] --> B["metadata preflight"]
    B --> C["sanitized inventory"]
    C --> D{"complete and clean at HEAD?"}
    D -->|no| E["BLOCKED or inventory-only"]
    D -->|yes| F["schema-v3 claim/evidence drafts"]
    F --> G{"explicit claim IDs selected?"}
    G -->|no| H["draft manifest only"]
    G -->|yes| I["knowledge_registry propose"]
    I --> J["canonical proposed claims"]
    J --> K["separate immutable human review"]
    K --> L["promotion and generated indexes"]
```

The model and investigator can create `proposed` claims directly. Promotion stays human-governed
in one of two ways: the investigator may request
`knowledge_registry.py approve-claim --claim-id <id> --expected-revision <n>`, which the safety
hook stops for the human's chat-confirmation click (recorded as `copilot-chat-confirmation` with
the reviewer named in `knowledge.chatReviewer` local configuration, then auto-promoted and
re-indexed), or a human runs the file-based `review`/`promote` commands directly for external
mechanisms (owner decision 2026-07-14).

## Functionalities and artifacts

| Functionality | Artifact | Contract |
|---|---|---|
| Source inventory | `.cache/knowledge-proposals/force-app-inventory.json` | `schemas/force-app-knowledge-inventory.schema.json` |
| Candidate generation | `.cache/knowledge-proposals/force-app-drafts/*.yaml` | existing claim/evidence schema v3 |
| Candidate manifest | `.cache/knowledge-proposals/force-app-drafts/manifest.json` | `schemas/force-app-knowledge-draft-manifest.schema.json` |
| Proposal submission | `.ai/knowledge/claims/`, `.ai/knowledge/evidence/` | `scripts/knowledge_registry.py propose` |
| Review/promotion | `.ai/knowledge/reviews/`, generated domain indexes | existing Knowledge lifecycle |

All cache artifacts are ignored. Canonical evidence remains sanitized and contains a source
locator, exact repository commit, file revision digest, collector identity, timestamps,
completeness, limitations, and a digest of the sanitized observation.

## Extracted coverage

- Objects: labels, deployment and sharing values; candidate positive existence claims.
- Fields: label/type/selected flags/formula/references; field-schema and relation candidates.
- Apex and Flow: declarations, trigger/start configuration and bounded references; automation
  inventory candidates.
- Named/external credentials and remote sites: component identity, label, endpoint host only;
  integration candidates.
- Approval processes: object, label, active flag, step count, entry-criteria presence; automation
  inventory candidates.
- AI description layer: behavior-bearing components (Flow, Apex, triggers, approval processes,
  LWC/Aura) additionally draft a `component-description` claim whose description the agent writes
  from the actual source before proposing (the registry rejects unfilled `<AGENT_...>`
  sentinels). These claims are `assurance: inferred` and become `verified` only through the human
  chat approval; they answer "what does this component do", which structural facts alone cannot.
- LWC/Aura: exposure, targets and source-declared references; generic `component-inventory`
  candidates (repository presence alone does not establish runtime behavior).
- Every other source-format metadata file (layouts, permission sets, custom metadata, labels,
  queues, …): metadata type derived from the file suffix, label/fullName facts, and a generic
  `component-inventory` candidate — coverage is total, so a recognized source file never drafts
  nothing (2026-07-14 upgrade).
- Non-metadata files: path, category and digest only, explicitly counted as generic coverage.

## Batch conversion (`/batch-knowledge`)

Large architectures are converted one metadata type per batch through the five-phase
`batch-knowledge` skill: DISCOVER (inventory + existing-claim query + `knowledge.chatReviewer`
check) → PLAN (per-component dispositions, chunks of ≤25, expected approval clicks) → VERIFY PLAN
(clean-tree re-check, reconciliation, explicit human go-ahead) → EXECUTE (per chunk:
`draft --metadata-type <Type>`, agent-written descriptions, `propose`, one
`approve-claim --claim-spec <id>:<rev> …` batch = one human confirmation) → VERIFY (registry
query against the plan, `render-indexes --check`, batch report under `output/documentation/`).
Stop rules (dirty tree, propose failure, reconciliation conflict, ungroundable description)
pause the batch instead of improvising.

Credential values, source bodies, records, tokens, private keys, and inferred business semantics
are never included.

## Prompts, agent, and skills

Public prompts:

- `/inventory-force-app` — inventory only.
- `/propose-force-app-knowledge` — draft and optionally submit explicitly selected IDs.
- `/refresh-force-app-knowledge` — run the two stages in sequence.

All prompts route to the existing `config-investigator`, whose hook permits only fixed-root
metadata preflight, the bounded inventory/draft commands, and the already governed registry
proposal command. New hidden skills are `inventory-force-app` and
`propose-force-app-knowledge`.

## Evidence boundaries

- Dirty, modified, or untracked `force-app` can be inventoried but cannot become
  `metadata-repository` evidence tied to `HEAD`.
- Repository metadata establishes intended source at a commit, not deployed org state.
- Labels/descriptions do not establish business meaning or ownership.
- Static source does not establish runtime order, side effects, effective permissions, inaccessible
  managed-package internals, or absence.
- Source/org reconciliation remains a later investigator step through the existing guarded
  Salesforce review surface when the claim policy requires it.

## Current live blockers

At implementation time, metadata preflight stops because local harness configuration still has
placeholder values. The root `force-app` also contains untracked changes. These are correctly
reported as blockers; no canonical Knowledge claim was created from the current source tree.
