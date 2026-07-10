---
name: update-knowledge-base
description: Route a new finding to the correct Knowledge file (consulting the README index instead of guessing) and keep that index up to date whenever a Knowledge file is added or changes scope.
---

# Skill: update-knowledge-base

Two jobs at once, because they complete each other (blueprint section 3): without the index
this skill has nothing to route with; without this skill nothing keeps the index current.
Called by `investigate-object` — and any other skill writing to Knowledge — whenever the target
file is not obvious.

## Job 1 — Routing

1. **Consult `.ai/knowledge/README.md`** (the navigational index — one sentence per file) to
   decide which domain file a given finding belongs to. Never guess, never create a duplicate
   entry in the wrong place.
2. If the target file is obvious from the index — write the finding there directly, using the
   `.ai/templates/knowledge-entry.md` format (facts only — if it reads like a rule, it belongs
   in `.github/instructions/`, not Knowledge; flag it instead of writing it here).
3. If no existing file fits, propose where it should live (a new file only if genuinely no
   domain covers it) and confirm with the human before creating one.

## Job 2 — Index maintenance

Whenever a Knowledge file is **added** or an existing file's **scope changes**, update
`.ai/knowledge/README.md` in the same operation — one line per file, kept accurate. This is
what keeps navigation from silently rotting with every new Knowledge file (the exact failure
that happened when `known-limitations.md` was added — blueprint section 3).
