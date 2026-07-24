# Knowledge One-File Entry — full-spectrum impact map (T07 Phase 0)

Companion to `docs/knowledge-one-file-contract.md`. Sources: three parallel dependency
sweeps (consumers, enforcement layer, contracts/config/docs) executed 2026-07-24 at commit
`d8104bf`. Every touchpoint carries a **phase assignment**; nothing here is executed in
Phase 0.

Phases referenced below:

```text
P0  contract freeze + adversarial review + fixture plan     (this phase — done on paper)
P1  entry executor + schemas wired (draft/approve commands, guard/hook/validator wiring)
P2  consumer read-path migration (search/explain first, then citing skills)
P3  work-record entryRef + SAFE-CLAIM v2 (Tier 1 change-set, owner sign-off)
P4  producer/maintainer skill migration + prompt surface consolidation
P5  parity certification, cutover, v1 repo-claim path retirement
```

## 1. Enforcement layer

| Touchpoint | Location | Change | Phase |
|---|---|---|---|
| Knowledge mutation roles | `scripts/copilot_role_guard.py:147` (`KNOWLEDGE_MUTATION_ROLES`) | reuse as-is for entry commands (curator + investigator) | P1 |
| Command flag allowlists | `copilot_role_guard.py:160-205` (`KNOWLEDGE_COMMAND_FLAGS`) | add `entry-draft` / `entry-approve` flag sets; **must mirror the executor's build_parser** (known drift gotcha) | P1 |
| Command gating logic | `copilot_role_guard.py:407-567` (`knowledge_registry_command_allowed`) | parallel validation branch for entry commands (chunk caps, path shape) | P1 |
| Governed path patterns | `copilot_role_guard.py:957-964` (`is_governed_record_path`) | add `\.ai/knowledge/artifacts/.*\.md` — raw edits denied to every role | P1 |
| Guard↔parser contract test | `tests/test_guard_parser_contract.py:88-133` | extend to pin the new command's flags | P1 |
| Chat-approve trap | `scripts/copilot_safety_hook.py:774-787` | add `ask` trap for the entry-approve command; mechanism string `copilot-chat-entry-confirmation` | P1 |
| Safety-hook tests | `tests/test_safety_hooks.py:367-440` (knowledge path/command pins) | add: artifacts path denied for raw edit; entry-draft allowed for curator/investigator; entry-approve triggers `ask` | P1 |
| Work-record SAFE gate | `scripts/work_record.py:533-548` (`validate_claim_refs`) + call sites `:1058`, `:1219-1220`, `:2418-2420` | accept `entryRef` for intended-source-state grounding (additive param; `require_current` maps to `approved-current` lane) | P3 |
| Claim binding / question resolution | `work_record.py:1752-1850` (`command_bind_claim`), `:1900-1904` (`command_resolve_question`), `:2129` (`_required_reads`) | additive entryRef variants; new `persisted_entry_ref()` parallel to `:516-530` | P3 |
| Validator required files | `scripts/validate_harness.py:178-184` | register the three new schemas once wired (P1), not in P0 | P1 |
| Validator grounding commands | `validate_harness.py:844-849` | add entry-store validate/check command once executor exists | P1 |
| CI workflow | `.github/workflows/harness-ci.yml:69-75` | add entry validate/check step; keep v1 steps until P5 | P1 |
| Preflight capability | `scripts/preflight.py` (no `knowledge` capability today) | **decision recorded: not needed** — role guard + executor validation suffice; revisit only if org-facing entry evidence appears | — |

## 2. Consumers (read path)

| Skill / surface | Today | Change | Phase |
|---|---|---|---|
| `search-knowledge` | `knowledge_registry.py query/explain` over claims | reads entries + v1 claims via unified query (T08b); until then unchanged | P2 |
| `solution-design` | queries Knowledge, cites claimRefs in envelopes | may additionally cite entryRefs after P3; query path swaps in P2 | P2/P3 |
| `check-against-principles` | `query` + `verify-citations` | `verify-citations` learns entryRef verdict vocabulary | P2 |
| `check-feature-coverage` | `query` (keyword/feature) | repoint to unified query | P2 |
| `suggest-test-cases` | `query` | slated for removal by the test-case-creator replacement (separate discovery) — coordinate, do not migrate twice | P2/n.a. |
| `generate-technical-documentation` | `query`; cites claims | may cite entryRefs; template §9 wording follows the test-case-creator outcome | P2/P3 |
| Envelope schemas | `schemas/output-envelope.schema.json`, `change-record.schema.json`, `handoff-envelope.schema.json` (claimRefs/evidenceRefs defs) | **additive** `entryRefs[]` definition; KCLM-/KEVD- grammar untouched | P3 |

## 3. Producers / maintainers (write path)

| Skill / command | Today | Change | Phase |
|---|---|---|---|
| `propose-force-app-knowledge`, `batch-knowledge` | draft→propose→approve-claim over claim YAML | become entry-draft/entry-approve workflows (or thin aliases to a consolidated curate flow per evidence-doc §20.9) | P4 |
| `refresh-force-app-knowledge` | refresh waves over stale claims | replaced by drift lanes (`approved-drifted`) + targeted re-approval; no global waves | P4 |
| `investigate-object`, `investigate-config-records` | org evidence + claims | **unchanged** — org observations stay v1 (contract §1) | — |
| `update-relations`, `relation-health` | relation claims per edge | relations become entry `typeFacts.references`/graph projections; relation-claim drafting retires at cutover | P4/P5 |
| `feature-documentor` | feature-crawl/feature-draft + claims | dossier becomes a generated view over entries; fix its broken guard allowlist independently (evidence-doc F-14) | P4 |
| `curate-knowledge` / knowledge-curator agent | batch/refresh/health cockpit | repointed to entry workflows | P4 |
| `curate-knowledge-keywords` | keyword-report → taxonomy | unchanged mechanism; entry `keywords` validated against the same taxonomy | P1 (validation), P4 (workflow) |
| `force_app_knowledge.py` extractors | draft claim YAML from inventory | extractors reused as-is; output target becomes entry `typeFacts` via profiles | P1 |

## 4. Generated surfaces

| Surface | Today | Disposition | Phase |
|---|---|---|---|
| 10 domain Markdown files (`.ai/knowledge/*.md`) | generated claim indexes (`render-indexes`) | remain claim-only until P5; entry indexes are new T08b projections in `.cache/`; domain files retire or shrink at cutover with `--check` parity | P5 |
| `claims-index.json` | generated, unused by engine | unchanged until P5 | P5 |
| `feature-map.md` | generated from feature claims | regenerates from entries at P4+ | P4 |
| Search cache (new) | — | `.cache/knowledge-search/` generated, ignored, non-canonical (T08b design) | T08b |
| `.cache/knowledge-proposals/` | draft pipeline | shrinks to org-observation drafting only after P4 | P4/P5 |

## 5. Contracts / config / templates / docs

| Artifact | Relationship | Change | Phase |
|---|---|---|---|
| `.github/copilot-instructions.md` SAFE-CLAIM-001 | contradiction for repo facts | SAFE-CLAIM v2 text (contract §8) — Tier 1, owner sign-off | P3 |
| SAFE-EVID/PROV/HUMAN/DRIFT-001 | extensions only | frontmatter fields map 1:1 (provenance, mechanism, contest lanes); no text change required | — |
| `.ai/contracts/knowledge-lifecycle.md` | contradicted for repo-derived class | scope narrowing amendment (contract §1) | P1 |
| `.ai/contracts/source-authority.md` | extension | applicability note: entryRef grounds intended-source-state only | P3 |
| `.ai/contracts/execution-contract.md` | extension | envelope wording gains entryRefs alongside claimRefs | P3 |
| `.ai/contracts/tool-capabilities.md` | untouched | no new external tools | — |
| `config/knowledge-policy.json` | extension | entry approval chunk caps mirror `promotion`/`manifestApproval` (≤25 / ≤500); optional per-profile review windows | P1 |
| `config/knowledge-extraction.json` | untouched | toggles keep governing extractors; provenance recorded outside digest | — |
| `config/harness.example.json` `knowledge.chatReviewer` | reused | same reviewer identity source for entry approval | P1 |
| `.ai/templates/knowledge-entry.md` | NORMATIVE (2026-07-16 decision), shows v1 claim skeleton | rewrite to one-file shape **when the executor lands**, same change-set; until then it correctly documents the retained v1 path | P1 |
| `.ai/knowledge/keyword-taxonomy.md` | reused | unchanged; entry keyword validation points at it | P1 |
| `docs/force-app-knowledge-architecture.md` | describes v1 pilot | update at P4/P5; add banner note at P1 pointing to the one-file contract | P1 (banner), P4/P5 |
| `docs/knowledge-facts-overlay-architecture.md` | SHELVED v2 fallback | header already says "approved design"— add SHELVED banner to prevent misreading (docs-only change, allowed in P1 docs pass) | P1 |
| `.ai/memory/decisions-log.md` | decision record | append D1 + format decision when Phase 0 ships | P0 |

## 6. Tests

| Test area | Change | Phase |
|---|---|---|
| `tests/test_knowledge_contract.py` | new entry-schema fixtures (valid draft, valid approved, tamper case from contract §5.5 last row, sentinel rejection, keyword rejection) | P1 |
| `tests/test_guard_parser_contract.py` | pin entry command flags | P1 |
| `tests/test_safety_hooks.py` | entry path/command/ask pins | P1 |
| `tests/test_work_record.py` | entryRef acceptance + `require_current` lane mapping | P3 |
| Determinism suite (new) | same source tree → identical digests on macOS/Linux/Windows; case-fold collision fails closed; reserved-name handling | P1 |
| Fixture families | two independent `Harness*` metadata families (closes §30 follow-up) | P0 (plan) / P1 (data) |

## 7. Completeness check

Every touchpoint reported by the three sweeps appears above with a phase. Items examined and
consciously **unassigned** (no change in any phase): `tool-capabilities.md`,
`knowledge-extraction.json` semantics, preflight capability, salesforce read facade,
ORG-KNOW/MP-*/SF-* instruction rules (policy applies to entries as-is), org-observation
skill flows (`investigate-object`, `investigate-config-records`).
