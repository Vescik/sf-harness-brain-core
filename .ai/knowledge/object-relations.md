# Object Relations

ERD-style catalog of relations between objects, with particular attention to the
**lookup-to-reference-data pattern**: fields that look like a picklist but are actually lookups
to editable runtime records on a Reference Data object (not picklists, not Custom Metadata
Types). Facts only, never rules. Entry format: `.ai/templates/knowledge-entry.md`.

This file stays a single, cross-cutting file even after the per-object split threshold is
reached elsewhere — a relation by nature involves two objects at once and cannot be cleanly
assigned to one per-object file (HARNESS_BLUEPRINT.md sections 3 and 8).

## Illustrative example (from the blueprint — NOT a verified fact about this org)

<!-- Marked illustrative per the build instruction; replace with real, verified entries. -->

> `Invoice__c.Status__c` is a lookup to the Reference Data object, where individual invoice
> statuses live as ordinary records, editable at runtime — not a picklist, not a Custom
> Metadata Type. This is the shape entries in this file should capture.

<!-- No real entries yet. Entries are added by investigate-object / update-knowledge-base as
facts are established — never fabricated at build time. -->
