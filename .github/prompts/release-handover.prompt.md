---
description: Monthly vendor release handover — composes the handover markdown from the saved ADO release query. Usage — /release-handover (no arguments)
---

<!-- THIN WRAPPER (R6 / blueprint section 12): no arguments to parse, call the skill. Zero
business logic here — it lives in .github/skills/generate-release-handover/SKILL.md. Run
monthly by the person responsible for the release ("release manager" — a human role running
this prompt, not an agent persona). -->

No `itemId` argument — the release scope comes from the saved Azure DevOps Query configured in
the skill: `<TU_WSTAW_QUERY_ID>`.
<!-- While this placeholder is empty, the skill fails fast with a pointer to it — this prompt
cannot produce a handover (blueprint sections 3, 12 and 16). -->

Steps:

1. Invoke the **`generate-release-handover` skill**.
2. Finish by telling the human:
   - **where the resulting markdown is** (`output/handover/<month>.md`), and
   - **how to export it to DOCX/PDF manually** — via the VS Code extension **Markdown PDF**
     (`yzane.markdown-pdf`; PDF natively, DOCX with Pandoc installed as backend), or
     **vscode-pandoc** if DOCX styling needs finer control (blueprint section 13).
     **This prompt does not export anything itself** (declarative-output rule, R6).
