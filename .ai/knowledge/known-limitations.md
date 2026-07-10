# Known Limitations

Growing catalog of **discovered managed package limitations at the level of a specific
function/page** (e.g. "VF page X is closed, only fields can be added"). This is fact, not rule —
consulted on demand by `investigate-object`, `check-against-principles` and
`check-feature-coverage` (HARNESS_BLUEPRINT.md sections 3 and 8).

Division of responsibility with Principles: the few, **broad, object-level** constraints worth
being always-active live in `.github/instructions/managed-package-constraints.instructions.md`
(loaded into every request via `applyTo: "**"`). Everything granular — a specific page, a
specific function — lives here, loaded only when needed. Do not duplicate entries between the
two files.

Entry format: `.ai/templates/knowledge-entry.md`.

<!-- No entries yet. Entries are added as limitations are discovered (investigate-object /
update-knowledge-base) — never fabricated at build time. -->
