---
name: generate-technical-documentation
description: Generate technical documentation for one development from its package.xml manifest — cross-referenced against force-app, enriched with ADO and Knowledge context, with suggested Test Cases and human-confirmed manual deployment steps. Ends on markdown in output/documentation/.
---

# Skill: generate-technical-documentation

The actual procedure behind the `/document-metadata-change` prompt (blueprint section 11).
Declarative-output rule applies: this skill ends its work on a markdown file — it never
generates or runs a script (R6).

Precondition (enforced by the calling prompt, deliberately NOT validated here — blueprint
section 3): the given `package.xml` contains the complete metadata of exactly one development.

## Procedure

1. **Load `package.xml`** — the development's manifest.
2. **Locate each `<types><members>` entry in `force-app`**, cross-referencing by type→folder
   mapping (`CustomObject`→`objects/`, `Flow`→`flows/`, `ApexClass`→`classes/`, etc.).
   **If something in the manifest has no counterpart in `force-app`, report it explicitly** —
   never skip it silently.
3. **Build business context**:
   - call the `fetch-ado-item` skill for the work item's title/description (feeds the
     "Business summary" section);
   - call the `investigate-object` skill for metadata elements not yet known;
   - read `.ai/knowledge/object-descriptions.md`, `field-descriptions.md`,
     `business-processes.md`, `automation-map.md` for elements already recorded.
4. **Apply the template** `.ai/templates/technical-documentation.md` — all 9 sections, none
   dropped.
5. **Call the `suggest-test-cases` skill** with the list of touched artifacts + the gathered
   context; fill section 9 ("Suggested Test Cases") with its grouped, rationale-carrying
   output.
6. **Ask the human about manual deployment steps** — automatic analysis of `package.xml` and
   `force-app` can never catch what is not metadata (a Flow activated by hand after deploy, a
   one-off data fix). Use the VS Code interactive-question tool.
   <!-- TODO(verify): exact tool name — vscode/askQuestion vs vscode/askQuestions (blueprint
   sections 6 and 16). -->
   If the answer is "none", write an explicit "None" into section 7 — the absence of
   information must be visible, never silent.
7. **Save to `output/documentation/<itemId>.md`** — ready for a human to publish to the ADO
   wiki (publication itself is a manual human step, and the wiki page is then natively linked
   to the work item as a "wiki page" link type).
