# Decisions Log

Persistent, versioned cross-work-item memory of the project — distinct from VS Code's built-in
Memory tool (local, per-machine), Copilot Memory, canonical Knowledge claims, and active work
records. This file records durable architectural decisions; it is not the workflow state store.

Two kinds of entries belong here:

1. **Discoveries of system facts with practical consequences** (e.g. "we established that field
   X controls Y — this changes the plan for Z").
2. **Accepted cross-work-item architectural decisions** whose effect outlives an individual work
   record. Active designs, approvals, evidence, coverage assessments, reviews, and handoffs live
   under `.ai/change-records/<record-id>/` and are referenced here only when they establish a
   durable project decision.

System facts are canonical Knowledge claims and must not be duplicated here. Chat-only decisions
are not durable.

## Entry format (template — copy for each new entry)

```
## <date> - <short title>
- Context: ...
- Finding / decision: ...
- Impact: ...
- Approved by: <who>
- Related: <link to a knowledge/ file or another entry>
```

---

<!-- No real entries yet. Entries are appended below this line as they occur — never
fabricated at build time. -->
