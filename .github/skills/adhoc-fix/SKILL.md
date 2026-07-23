---
name: adhoc-fix
description: Express lane for a small bounded defect fix (e.g. one broken Flow) — edit repository metadata straight from a recorded diagnosis, without an accepted design record. Deploys stay human; review follows the fix.
user-invocable: false
---

# Ad-hoc defect fix (express lane)

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[Managed Package Constraints](../../instructions/managed-package-constraints.instructions.md).
Run `python scripts/preflight.py --capability salesforce-review`.

This lane is the owner-approved exception (decision of 2026-07-23) to the development-assistant
accepted-design entry gate. It exists so a diagnosed defect — a broken Flow decision, a wrong
validation formula, a mislabeled field — can be fixed in the repository the moment the diagnosis
is in hand. Everything else about the role's boundaries is unchanged: edits stay inside
`force-app/`, `manifest/`, and `tests/e2e/`; the agent never deploys; org changes ship through a
human deploy.

## Entry conditions

- A written diagnosis exists: what is broken, in which component, expected vs. actual behavior,
  and the evidence trail (investigation output, error message, or the user's own description).
  Restate it at the top of the fix note; do not start editing from a vague "something is wrong".
- The fix is small and bounded: one defect, the smallest coherent set of components (typically
  one), no new automation, no object/field schema changes, no permission changes. When the fix
  grows beyond that, stop and route through the normal design lane instead of stretching this one.
- The target is customer-owned metadata. Managed-package internals cannot be fixed here.

## Procedure

1. Retrieve the current org state of the target component before editing, so the fix is based on
   what is deployed, not on a stale local copy:
   `sf project retrieve start --target-org <configured-alias> --metadata <Type:Name>`
   (the safety hook records the receipt; only configured non-production aliases are accepted).
2. Read the retrieved source and confirm the diagnosis against it — the exact element, formula,
   or connector that is wrong. If the retrieved state contradicts the diagnosis, stop and report
   instead of guessing.
3. Consult Knowledge for dependents before touching the component:
   `python scripts/knowledge_registry.py query --subject-identity <component>` and the
   `--uses-object`/`--uses-field` searches, so the fix does not break a consumer you did not know
   about.
4. Make the smallest coherent edit in `force-app/`. Match the existing metadata style; change the
   defective element, not the surrounding structure.
5. Verify what can be verified locally: the XML parses, the changed element is the only
   difference against the retrieved copy, and any referenced fields/labels/subflows exist in the
   local source or verified Knowledge.
6. Write the fix note to `output/documentation/adhoc-fixes/<yyyy-mm-dd>-<component>.md`:
   diagnosis (verbatim), files changed, the exact before → after of the defective element,
   verification performed, the human deploy step (component list for
   `sf project deploy start`), and the rollback path (re-retrieve from the org, which still holds
   the pre-fix state until the human deploys).
7. Hand the outcome to the human: the fix is NOT live until they deploy. Recommend an
   after-the-fact guardrail review — the human opens the guardrail-reviewer role on the fix note
   and changed files; record the verdict by appending a `Review outcome` section to the note.
8. If the defect or its fix reveals durable facts worth keeping (error surface, config meaning),
   propose them through the normal Knowledge lane afterwards; this skill itself writes no claims.

## Prohibitions

- Never deploy, and never run any raw `sf` subcommand other than `project retrieve start` with a
  configured `--target-org`.
- Never fix more than the diagnosed defect in one pass — no drive-by refactors, no "while I'm
  here" cleanups, no scope growth past the bounded-fix entry condition.
- Never edit outside `force-app/`, `manifest/`, `tests/e2e/`, and the fix note; approvals,
  Knowledge, Principles, and records remain out of reach.
- Never present the repository edit as deployed, fixed-in-org, or verified-in-org; until the
  human deploys, the org still runs the defective version.

## Return

Return the fix note path; the diagnosis summary; files changed with the before → after of the
defective element; local verification performed; the exact human deploy command and component
list; the rollback path; and the recommendation to run the after-the-fact guardrail review.
