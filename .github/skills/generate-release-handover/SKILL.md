---
name: generate-release-handover
description: Compose the monthly vendor release handover from a saved ADO query — per-item summaries, technical tables pulled from linked wiki documentation, and linked Test Cases. Ends on markdown in output/handover/; format export is a manual human step.
---

# Skill: generate-release-handover

The actual procedure behind the `/release-handover` prompt (blueprint section 11). This skill
is the explicit example of the **declarative-output rule** (R6, blueprint section 3): it ends
its work on a markdown file and **never generates or runs any script** (Python, PowerShell or
otherwise). DOCX/PDF export is a separate, manual, human-triggered step via a VS Code extension
(Markdown PDF `yzane.markdown-pdf`; alternative: vscode-pandoc — blueprint section 13).

## Procedure

0. **Fail fast on missing configuration.** The release scope comes from a saved Azure DevOps
   Query, referenced by ID: `<TU_WSTAW_QUERY_ID>`.
   <!-- While this placeholder is empty, this skill CANNOT run: it has no way to determine
   which items belong to the release (blueprint sections 3 and 16 — the WIQL criterion is the
   team's process decision, never guessed). -->
   If the Query ID is still the placeholder above, **stop immediately** with a clear message:
   "Cannot generate the handover: `<TU_WSTAW_QUERY_ID>` is not configured — fill the saved ADO
   Query ID (see HARNESS_BLUEPRINT.md section 16) in generate-release-handover/SKILL.md and
   .ai/templates/release-handover.md." Do not attempt to construct a query, do not guess the
   release scope.
1. **Run the saved ADO Query by its ID** — the list of items in this release.
2. **Per item, call the `fetch-ado-item` skill** with `childDetail=full` (Description +
   Acceptance Criteria in full) and `includeTestCases=true` (formally linked Test Cases, both
   relation sources, deduplicated).
3. **Pull the published technical documentation** from the natively linked wiki page (link type
   "wiki page" on the work item — queryable via the standard work-item relations API). Extract
   the artifact table (same columns as `technical-documentation.md`) and the manual deployment
   steps section. **If an item has no linked wiki page, report it explicitly** ("no published
   technical documentation") — never regenerate and never guess the content.
4. **Compose each item's section** per `.ai/templates/release-handover.md`: a 2-3 sentence
   AI-generated summary from Description + Acceptance Criteria, the technical table, and the
   Tests subsection — if the item has no linked Test Cases, use exactly the fallback text
   *"Tested based on acceptance criteria"* instead of an empty section.
5. **Save the whole document** to `output/handover/<month>.md` and finish by telling the human
   where the file is and how to export it (extension-based, manual) — this skill does not
   export.
