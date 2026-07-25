# P1 completion note — `belongs-to`

Date: 2026-07-25 · Required output of P1, consumed by P5's acceptance bar
(`docs/knowledge-master-plan-2026-07-25.md` §3, §7, §8)

## N_belongs_to = 16

Definition (master plan §3): **new `component-relation` candidates minted by `belongs-to`**,
CustomMetadata included per owner decision D2.

| Emitting type | New relation candidates |
|---|---|
| RecordType | 7 |
| ApexTrigger | 5 |
| ValidationRule | 2 |
| CustomMetadata | 2 |
| **N_belongs_to** | **16** |

CustomField emits `belongs-to` on every field but mints **no** relation candidate:
`relation_candidates()` returns early for CustomField, whose object references are
`object-relation` claims instead. This is why the candidate count (16) and the edge count (109)
differ — one symbol, two numbers, so both are stated here.

**P5 asserts `582 + N_belongs_to` read from this note, never a literal.** Measured on the
reference corpus after P1: `relations-worklist` reports **598 missing**, up from 582, exactly as
predicted.

## Measured on the reference corpus

189 components from `~/Desktop/salesforce_test_data`, all drafted as entries, indexed.

| Measurement | Before P1 | After P1 |
|---|---|---|
| `belongs-to` edges | 0 | **109** (CustomField 93, RecordType 7, ApexTrigger 5, ValidationRule 2, CustomMetadata 2) |
| CustomField entries with zero outgoing edges | 63 of 93 | **0** |
| CustomObject entries with zero outgoing edges | 20 | **20 — expected** |
| `relations-worklist` missing | 582 | **598** |
| Entries drafted / failed | 189 / 0 | 189 / 0 |

Every `belongs-to` edge carries `assurance: source-exact`, asserted during the gate run:
containment is read from the artifact's own path or declaration, never inferred.

### Why CustomObject stays at 20

`belongs-to` is the **child** side. The parent side (`contains`) would require an entry to know
every other artifact that names it — non-local, forbidden by R1, and a second `factsDigest` move
that would re-open the approval window P1 exists to close. `parse_object` emits no references at
all and correctly still does.

Composition reachability for objects is **P2's** gate, delivered by inverting the `belongs-to`
posting in the index: all 20 objects must return a non-empty `parts`. That is an inbound
measurement and must never be restated as an outgoing-edge count.

## Registration

`belongs-to` is classified in `relation_kinds.OBJECT_REF_KINDS` and
`knowledge_registry.OBJECT_REF_KINDS`. The generic kind contract does **not** pin this: a FIELD
classification leaves the whole suite green while making `--uses-field Assignment__c` match an
*object* name and permanently polluting `usesFields`. Two explicit assertions in
`tests/test_kind_contract.py` pin it, and I verified both fail when the kind is misplaced.
