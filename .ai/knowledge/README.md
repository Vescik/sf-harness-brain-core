# Knowledge Index

Navigational index of `.ai/knowledge/` — one line per file. Read this first before opening any
domain file; it is the only mechanism that tells an agent/skill what lives where. Maintained by
the `update-knowledge-base` skill: it MUST be updated whenever a Knowledge file is added or an
existing file's scope changes (HARNESS_BLUEPRINT.md sections 3 and 8).

General rule for the whole layer: **facts, never rules** — rules belong in
`.github/instructions/` (Principles). Every entry in every domain file uses the single format
defined in `.ai/templates/knowledge-entry.md`.

| File | What lives there |
|---|---|
| [current-implementation.md](current-implementation.md) | Feature catalog — what the system does functionally, roughly how. |
| [business-processes.md](business-processes.md) | Business process ↔ system mapping, from the business user's perspective. |
| [object-relations.md](object-relations.md) | ERD-style relations between objects, especially the lookup-to-reference-data pattern. |
| [object-descriptions.md](object-descriptions.md) | What each object is, who owns it (package / us). |
| [field-descriptions.md](field-descriptions.md) | What each field means, especially fields without an obvious name. |
| [automation-map.md](automation-map.md) | What is actually attached to each object — our Flows, our Apex, known package automation entry points. |
| [integration-map.md](integration-map.md) | External systems connected to the org, direction of data flow. |
| [glossary.md](glossary.md) | Business ↔ technical dictionary — what the business calls it vs its technical name. |
| [known-limitations.md](known-limitations.md) | Growing catalog of discovered managed package limitations at the level of a specific function/page. |
| [keyword-taxonomy.md](keyword-taxonomy.md) | Controlled vocabulary of terms — shared by object descriptions and `.ai/qa/keywords-map.md`; grows only via explicit human confirmation. |

Scaling plan (threshold, not built now — blueprint sections 3 and 8): when
`object-descriptions.md`, `field-descriptions.md` or `automation-map.md` exceed ~15-20 described
objects, split into `.ai/knowledge/objects/<Name>.md` — one file per object combining all three
domains. `object-relations.md` does NOT split this way — it stays a single cross-cutting file.
