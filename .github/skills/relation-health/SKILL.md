---
name: relation-health
description: Read-only report of verified object-relation/component-relation claims whose source edge no longer exists in current force-app source (component deleted, or the specific reference retargeted/removed), for human stale-marking. Never mutates Knowledge.
user-invocable: false
---

# Relation health report

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md). Requires the
`config-investigator` role.

Knowledge is append-only: deleting a field, removing a Flow element, or retargeting a reference
does not update or remove the claim that was verified against the old edge. This report makes that
drift visible without touching Knowledge itself — the same read-only contract as `coverage` and
`stale-report`.

## Procedure

1. Run `python scripts/preflight.py --capability metadata` and
   `python scripts/force_app_knowledge.py inventory`. Stop on a dirty tree or partial inventory —
   the diff needs a clean, current source snapshot.
2. Run `python scripts/force_app_knowledge.py relation-health --write`. Each orphaned entry carries
   a `reason`: `"component removed"` (the whole source component is gone) or `"edge no longer
   present in source"` (the component still exists, but this specific reference doesn't — e.g. a
   Flow element removed, a field's `referenceTo` retargeted, an LWC's schema import changed).
3. Present the orphaned list to the human. Triage is a genuine judgment call this skill does not
   make automatically: was the removal a legitimate metadata change, or does it suggest a parser
   edge case worth investigating in `force_app_knowledge.py`? Do not guess on the caller's behalf.
4. There is no one-command shortcut to mark an orphan `stale` (`approve-claim` only covers
   `verify`-decision promotion). Marking a claim `stale` goes through the file-based
   `review`/`promote` path per the Knowledge lifecycle contract — a separate, deliberate human step
   this skill does not perform.

## Prohibitions

- Never mark, supersede, or otherwise mutate a claim from this skill — it is report-only.
- Never treat an orphaned entry as proof the underlying relationship is false; it only means the
  claim's specific source edge is no longer observable at the current commit.

## Return

Return `HEALTHY` (zero orphans) or `ORPHANS-FOUND`; the orphaned count and list (claim ID, claim
type, subject identity, reason, revision); and the report path.
