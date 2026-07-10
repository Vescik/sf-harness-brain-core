# Harness Diagrams — Architecture & Process Flows

This file is a diagram-only companion to `HARNESS_BLUEPRINT.md`. It contains no rationale or
decision history — for the "why" behind any diagram here, see the corresponding section in the
blueprint (referenced under each diagram). All diagrams are Mermaid, renderable natively in
GitHub, VS Code preview, and most markdown viewers.

## Table of contents

1. Architecture overview
2. Orchestration
3. Skill process flows

---

## 1. Architecture overview

### 1.1 Brain-core layer map

*Blueprint section 4.*

```mermaid
graph TB
    subgraph GH[".github/ - native, auto-loaded by Copilot"]
        P["Principles<br/>3 .instructions.md files"]
        AG["Orchestration<br/>4 agent profiles"]
        SK["Skills<br/>SKILL.md"]
        PRM["Prompts<br/>.prompt.md"]
    end
    subgraph AID[".ai/ - reference, on-demand"]
        K["Knowledge<br/>10 domains"]
        M["Memory<br/>decisions-log.md"]
        TPL["Templates<br/>output formats"]
        QA["QA<br/>synced test cases"]
    end
    CACHE[(".cache/ - raw, gitignored")]
    OUT["output/ - AI artifacts, visible"]
    AG -->|reads always, every request| P
    AG -->|reads on demand| K
    AG -->|writes findings| M
    SK -->|used by| AG
    PRM -->|invokes| SK
    SK -->|checks and writes| CACHE
    SK -->|applies| TPL
    SK -->|writes result| OUT
    SK -->|syncs index| QA
```

### 1.2 Principles precedence

*Blueprint section 4 and section 7.*

```mermaid
graph LR
    MP["Managed Package Constraints"] -->|overrides| OP["Organization Principles"]
    OP -->|overrides| SFP["Salesforce Best Practices (general)"]
```

### 1.3 Workspace structure — `.github/`

*Blueprint section 5.*

```mermaid
graph TD
    GH[".github/"]
    GH --> CI["copilot-instructions.md"]
    GH --> INSTR["instructions/"]
    GH --> AGENTS["agents/"]
    GH --> SKILLS["skills/"]
    GH --> PROMPTS["prompts/"]

    INSTR --> I1["salesforce-best-practices<br/>.instructions.md"]
    INSTR --> I2["organization-principles<br/>.instructions.md"]
    INSTR --> I3["managed-package-constraints<br/>.instructions.md"]

    AGENTS --> A1["solution-designer.agent.md"]
    AGENTS --> A2["config-investigator.agent.md"]
    AGENTS --> A3["development-assistant.agent.md"]
    AGENTS --> A4["guardrail-reviewer.agent.md"]

    SKILLS --> S1["investigate-object/"]
    SKILLS --> S2["fetch-ado-item/"]
    SKILLS --> S3["check-against-principles/"]
    SKILLS --> S4["generate-technical-documentation/"]
    SKILLS --> S5["check-feature-coverage/"]
    SKILLS --> S6["generate-release-handover/"]
    SKILLS --> S7["fetch-test-case/"]
    SKILLS --> S8["sync-test-cases/"]
    SKILLS --> S9["suggest-test-cases/"]
    SKILLS --> S10["tune-test-case-keywords/"]
    SKILLS --> S11["generate-playwright-test/"]
    SKILLS --> S12["update-knowledge-base/"]

    PROMPTS --> P1["fetch-ado-item.prompt.md"]
    PROMPTS --> P2["document-metadata-change.prompt.md"]
    PROMPTS --> P3["feature-health.prompt.md"]
    PROMPTS --> P4["release-handover.prompt.md"]
    PROMPTS --> P5["sync-test-cases.prompt.md"]
    PROMPTS --> P6["tune-test-case-keywords.prompt.md"]
    PROMPTS --> P7["generate-playwright-test.prompt.md"]
```

### 1.4 Workspace structure — `.ai/`

*Blueprint section 5.*

```mermaid
graph TD
    AI[".ai/"]
    AI --> KNOW["knowledge/"]
    AI --> MEM["memory/"]
    AI --> TEMPL["templates/"]
    AI --> QAD["qa/"]

    KNOW --> K0["README.md<br/>(navigational index)"]
    KNOW --> K1["current-implementation.md"]
    KNOW --> K2["business-processes.md"]
    KNOW --> K3["object-relations.md"]
    KNOW --> K4["object-descriptions.md"]
    KNOW --> K5["field-descriptions.md"]
    KNOW --> K6["automation-map.md"]
    KNOW --> K7["integration-map.md"]
    KNOW --> K8["glossary.md"]
    KNOW --> K9["known-limitations.md"]
    KNOW --> K10["keyword-taxonomy.md"]

    MEM --> M1["decisions-log.md"]

    TEMPL --> T1["technical-documentation.md"]
    TEMPL --> T2["feature-health-report.md"]
    TEMPL --> T3["knowledge-entry.md"]
    TEMPL --> T4["release-handover.md"]

    QAD --> Q1["test-cases/&lt;suiteId&gt;-&lt;name&gt;.md"]
    QAD --> Q2["keywords-map.md"]
    QAD --> Q3["ui-navigation-patterns.md"]
```

### 1.5 Workspace structure — `.cache/` and `output/`

*Blueprint section 13.*

```mermaid
graph TD
    CACHE[".cache/ (gitignored)"]
    CACHE --> C1["ado-items/&lt;id&gt;.json"]
    CACHE --> C2["test-cases/&lt;id&gt;.json"]

    OUTPUT["output/ (visible)"]
    OUTPUT --> O1["documentation/&lt;itemId&gt;.md"]
    OUTPUT --> O2["feature-health/&lt;featureId&gt;.md"]
    OUTPUT --> O3["handover/&lt;month&gt;.md"]
    OUTPUT --> O4["generated-tests/&lt;name&gt;.spec.ts"]
```

---

## 2. Orchestration

### 2.1 Five-agent SDLC pipeline

*Blueprint section 10.*

```mermaid
flowchart LR
    FH["/feature-health<br/>(Feature-level gate)"] --> ADO1["ADO: work item"] --> SD["Solution Designer<br/>(solution-designer)"]
    SD <-->|on demand| CI["Config Investigator<br/>(config-investigator)"]
    SD --> DEV["Development Assistant<br/>(development-assistant)"]
    DEV <-->|on demand| CI
    DEV <-->|on demand| TS["Test Strategist<br/>(test-strategist)"]
    DEV --> GR["Guardrail Reviewer<br/>(guardrail-reviewer)"]
    GR --> ADO2["ADO: note / wiki"]
```

*Test Strategist is on-demand, not phase-locked (same nature as Config Investigator). Its
distinct decision: assess whether the QA inventory is fresh, whether existing coverage
suffices, or whether new Playwright automation is needed — see blueprint section 3.*

### 2.2 Standalone tools — entry points

*Blueprint section 10 (closing note) and section 12. `/release-handover` and
`/tune-test-case-keywords` remain independent of any agent. `/sync-test-cases` and
`/generate-playwright-test` are multi-consumer: triggered directly by a human, or orchestrated
by Test Strategist when broader judgment about coverage sufficiency is needed.*

```mermaid
graph TD
    DEV_DONE["Development complete"] --> PW["/generate-playwright-test"]
    MONTHLY["Monthly cadence"] --> RH["/release-handover"]
    QA_NEED["QA needs a test inventory"] --> STC["/sync-test-cases"]
    ADMIN["Admin curation session"] --> TTK["/tune-test-case-keywords"]
    TS2["Test Strategist judgment"] -.->|may also invoke| PW
    TS2 -.->|may also invoke| STC
```

---

## 3. Skill process flows

### 3.1 `fetch-ado-item`

*Blueprint section 11. Also accepts `childDetail=<summary|full>` and
`includeTestCases=<true|false>` — not shown as branches here to keep the core flow readable;
see blueprint section 11 for both parameters.*

```mermaid
flowchart TD
    F["Fetch item by ID"] --> CH{"Fresh cache?"}
    CH -->|yes| CACHED["Use .cache/ado-items/id.json"]
    CH -->|no| Q{"Mode provided?"}
    Q -->|no| INFER["Check Work Item Type<br/>pick default mode"]
    Q -->|yes| MODE{"single or hierarchy?"}
    INFER --> MODE
    MODE -->|single| S1["Only the specified item"]
    MODE -->|hierarchy| H1{"Has a parent?"}
    H1 -->|yes| H2["Parent + its children + own children<br/>1 level deep, tiered detail"]
    H1 -->|no| H3["Fallback: own children only<br/>+ explicit note about missing parent"]
    CACHED --> RES["Return context"]
    S1 --> RES
    H2 --> RES
    H3 --> RES
```

### 3.2 `investigate-object`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["Check Knowledge first<br/>README.md, then the relevant file"] --> B["Describe schema /<br/>describe reference records"]
    B --> C{"Risk acceptable<br/>for a sandbox test?"}
    C -->|yes| D["Controlled test on sandbox"]
    C -->|no| E["Ask a human instead of guessing"]
    D --> F["Write finding using knowledge-entry.md format<br/>+ optional keywords"]
    E --> F
```

### 3.3 `check-against-principles`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["Proposed change"] --> B["Check Managed Package Constraints<br/>+ known-limitations.md"]
    B --> C["Check Organization Principles"]
    C --> D["Check Salesforce Best Practices"]
    D --> E{"Verdict"}
    E -->|clean| F["Safe to proceed"]
    E -->|issues found| G["Needs fixes / Stop - too risky"]
```

### 3.4 `generate-technical-documentation`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["Load package.xml<br/>(development manifest)"] --> B["Locate in force-app<br/>cross-reference by type and name"]
    B --> C["Build context<br/>fetch-ado-item + investigate-object + Knowledge"]
    C --> D["Apply template<br/>.ai/templates/"]
    D --> G["suggest-test-cases<br/>fills Suggested Test Cases section"]
    G --> E["Ask about manual deployment steps<br/>vscode/askQuestion"]
    E --> F["Save result<br/>output/documentation/, ready for ADO wiki"]
```

### 3.5 `check-feature-coverage`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["fetch-ado-item<br/>mode=hierarchy childDetail=full"] --> B["Extract requirements<br/>from Feature + BRD (if attached)"]
    B --> C["Extract what each<br/>User Story actually claims"]
    C --> D["Cross-check both directions:<br/>gaps + orphans"]
    D --> E["Check known-limitations.md<br/>for early warnings"]
    E --> F["Save report<br/>output/feature-health/"]
```

### 3.6 `generate-release-handover`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["ADO Query (Query ID)<br/>list of items in the release"] --> B["fetch-ado-item per item<br/>childDetail=full + includeTestCases"]
    B --> C["Wiki: fetch technical documentation<br/>via native link"]
    C --> D["Compose per-item section<br/>summary + table + tests"]
    D --> E["Save markdown<br/>output/handover/"]
```

*Note: DOCX/PDF export happens afterward as a manual, human-triggered step via a VS Code
extension — intentionally not part of this skill (see blueprint section 3, declarative-output
decision).*

### 3.7 `fetch-test-case`

*Blueprint section 11. Extracted from `sync-test-cases` for reuse — same pattern as
`fetch-ado-item`.*

```mermaid
flowchart TD
    A["Test Case ID"] --> B{"Fresh cache?"}
    B -->|yes| C["Use .cache/test-cases/id.json"]
    B -->|no| D["Fetch via Test Plans API"]
    D --> E["Write to cache"]
    C --> F["Return full detail"]
    E --> F
```

### 3.8 `sync-test-cases`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["Link / Suite ID / Plan ID"] --> B{"Specific suite given?"}
    B -->|no, plan only| C["Enumerate all suites in the plan"]
    B -->|yes| D["Test Plans API: list Test Case IDs in suite"]
    C --> D
    D --> E["fetch-test-case per ID"]
    E --> F["Write lightweight index to .ai/qa/"]
    F --> G["Check keywords-map.md for<br/>orphaned entries, report if found"]
```

### 3.9 `suggest-test-cases`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["Touched artifacts<br/>+ Feature/Story context"] --> B{"Match in<br/>keywords-map.md?"}
    B -->|yes| C["Hard match<br/>high confidence"]
    B -->|no or partial| D["Expand vocabulary via<br/>object-descriptions / business-processes"]
    D --> E["Model reasoning over<br/>titles in .ai/qa (not a keyword algorithm)"]
    C --> F["Group results:<br/>high confidence vs worth checking"]
    E --> F
```

### 3.10 `tune-test-case-keywords`

*Blueprint section 11. Admin tool, human-in-the-loop.*

```mermaid
flowchart TD
    A["Test Case ID"] --> B["Fetch title/description<br/>from .cache/test-cases"]
    B --> C["Suggest candidate keywords<br/>from keyword-taxonomy.md"]
    C --> D{"Human<br/>confirms?"}
    D -->|yes / edits| E["Write to keywords-map.md"]
    D -->|term outside taxonomy| F["Ask whether to extend<br/>keyword-taxonomy.md"]
    F --> E
```

### 3.11 `generate-playwright-test`

*Blueprint section 11. Two equally-supported input sources — an existing Test Case, or steps
described directly by a tester in chat.*

```mermaid
flowchart TD
    A1["testCaseId: fetch-test-case"] --> C["Check ui-navigation-patterns.md"]
    A2["Steps described in chat"] --> C
    C --> D["Playwright: navigate live<br/>collect accessibility snapshot"]
    D --> N{"New UI quirk<br/>discovered?"}
    N -->|yes| S["Suggest adding to<br/>ui-navigation-patterns.md"]
    N -->|no| E
    S --> E["Generate script<br/>stable, accessibility-based selectors"]
    E --> F["Save for human review<br/>output/generated-tests/"]
```

### 3.12 `update-knowledge-base`

*Blueprint section 11.*

```mermaid
flowchart TD
    A["New finding to write"] --> B{"Target file obvious?"}
    B -->|yes| C["Write directly"]
    B -->|no| D["Route to the correct Knowledge file"]
    D --> E["Update README.md index"]
    C --> E
```
