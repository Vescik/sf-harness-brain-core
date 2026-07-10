# Template: Knowledge Entry

<!--
The single, consistent entry format for ALL .ai/knowledge/*.md domain files
(HARNESS_BLUEPRINT.md sections 8 and 13). Used by investigate-object and every other skill
that writes to Knowledge. The "Related" field mirrors the pattern of decisions-log.md —
cross-links between entries are frequent on large, automation-heavy objects and worth
recording explicitly.
R7 note: field names translated to English from the blueprint ("Powiązane" → "Related");
Polish domain/business terms themselves stay verbatim where they appear in entry content
for glossary.md and keyword-taxonomy.md.
-->

### <Name>

- Description: `<what this is / what it does>`
- Confidence level: `<confirmed | probable | to be verified>`
- How established: `<describe | SOQL | sandbox test | vendor documentation | conversation with <who>>`
- Date established: `<date>`
- Keywords: `<optional — terms from .ai/knowledge/keyword-taxonomy.md only; omit if no existing term fits — never invent a new term here, never block the entry on this field>`
- Related: `<other Knowledge entries/files, if applicable>`
