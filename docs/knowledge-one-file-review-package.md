# Knowledge One-File Entry — adversarial review package (T07 Phase 0)

Input documents for a context-free independent reviewer:

1. `docs/knowledge-one-file-contract.md` — the frozen contract under attack
2. `docs/knowledge-one-file-impact-map.md` — dependency wiring and phase plan
3. `schemas/knowledge-entry.schema.json`, `schemas/knowledge-profile-flow.schema.json`,
   `schemas/knowledge-profile-customfield.schema.json` — draft schemas (unwired)
4. Background (optional): `docs/evidence-to-analyse.md` §15–25,
   `docs/evidence-analysis-2026-07-24.md` §4.3–4.4

The reviewer's job is to **break the design on paper** before any code exists. Confirmation
is worthless; refutation is the deliverable.

## 1. Priority attack targets (ordered)

1. **Tamper the approval binding.** Find any sequence of file edits, regenerations, or state
   flips that leaves an entry served as `approved-current` while its reviewable content
   differs from what the human saw (contract §4, §5.3, §5.5 last row). Include: partial
   frontmatter edits, YAML aliasing/duplicate keys, frontmatter/body boundary ambiguity
   (`---` inside body code fences), normalization mismatches (CRLF, Unicode confusables),
   digest-input reordering.
2. **Trigger a global re-approval wave.** Find a realistic collector/profile/config change
   that flips *all* approved entries out of `approved-current` despite unchanged assertions
   (contract §5.1, §5.5) — the failure mode the design exists to prevent. Conversely: find a
   material assertion change that does NOT leave `approved-current` (silent drift).
3. **Smuggle unapproved semantics.** Can prose meaning ride in fields outside
   `semanticsDigest` (keywords, limitations wording, `elementLabel`, coverage notes,
   profile-defined sections missing from the digest)? Anything a consumer would read as
   meaning must be inside the reviewed boundary or clearly advisory.
4. **Executor-bypass writes.** With the artifacts path governed and writes executor-only
   (contract §6.4): enumerate bypasses — git commands, file moves/renames, case-collision
   overwrites on Windows, symlinks, creating a second file with a colliding safe-name,
   editing via generated-view round-trips.
5. **Authority flattening.** Can an `approved-current` entry be cited (via `entryRef`) for
   something repository source cannot establish — deployed state, runtime behavior, package
   limitation, vendor guarantee, completeness/absence (SAFE-CLAIM v2 draft, contract §8)?
   Attack the wording, not the intent.
6. **Intentional-error scope creep.** Show a path by which `screen-validation` or
   `fault-path` content (present in today's mixed `errorCatalog`) reaches
   `intentionalErrors[]` or the future error index (contract §7).
7. **Windows identity attacks.** Case-fold collisions, NFKC confusables, path-length
   truncation collisions, reserved names, trailing dots — can two logical artifacts map to
   one file, or one artifact silently to two (contract §3)?
8. **Draft/approved lane bleed.** Any read path where a `draft` entry outranks, interleaves
   with, or masquerades as approved content (contract §4) — including a draft edited to
   carry a copied `approval` block from another entry.
9. **Coexistence contradiction hunt.** With v1 retained for org observations (contract §1):
   find a claim class that is now ambiguously double-homed (could be an entry AND a v1
   claim), or a SAFE verdict that could cite the weaker of the two representations.
10. **Reviewer authority.** Pilot uses a single `knowledge.chatReviewer` for every entry
    (contract §11 KSEM-004 limitation). Argue concretely whether business-meaning body prose
    requires an authority matrix *before* pilot, or whether the single-reviewer carve-out is
    acceptable pilot debt with a named expiry condition.
11. **Volume/ergonomics sanity.** ~10–15k entries as individual committed Markdown files:
    attack Git ergonomics (diff noise, repo growth, index rebuild cost on Windows), the
    ≤25/click approval throughput math for the initial wave, and whether the batching design
    (contract §9) actually beats the measured v1 pain (~1,200 clicks) rather than relocating it.
12. **Phase-plan gaps.** Impact-map completeness: name any consumer, guard, schema, contract,
    or test surface that will break in P1–P5 but has no row in the impact map.

## 2. Verdict format (required)

```text
VERDICT: ACCEPT | ACCEPT WITH REQUIRED CHANGES | RETURN TO DISCOVER | REJECT — SECURITY/AUTHORITY REGRESSION

REQUIRED CHANGES:   numbered, each bound to a contract section and an attack that motivated it
CONFIRMED HOLES:    reproducible attack narrative (steps → wrong outcome)
RISKS ACCEPTED:     severity × likelihood × detectability, with the expiry condition if pilot debt
MISSING EVALS:      concrete scenario + expected outcome, mapped to the golden set below
CUTOVER BLOCKERS:   explicit, testable conditions for P5
```

## 3. Synthetic fixture plan (P1 input; plan only in Phase 0)

Two **independent** synthetic metadata families (closes the §30 follow-up — tests must prove
genericity, not memorize one domain model):

- Family A `HarnessAlpha*`: `HarnessAlphaCase__c` (parent) ← `HarnessAlphaTask__c` (child
  lookup), record-triggered Flow `HarnessAlphaRouter` with 2 `FlowCustomError` elements
  (one record-level, one field-level with `$Label` ref), Apex `HarnessAlphaService`,
  ~40 fields across both objects incl. formula/picklist/external-id.
- Family B `HarnessBeta*`: platform-event-driven shape — `HarnessBetaOrder__c`,
  `HarnessBetaSignal__e`, autolaunched Flow without trigger object, LWC bundle
  `harnessBetaPanel`, validation rule + duplicate rule decoys (must NOT enter
  `intentionalErrors`).
- Scale tiers: smoke ≈ 1k entries, target ≈ 10–15k (≈250 Flows / 400 objects / 8k fields /
  800 Apex proportions from the recorded v1 measurements — used as benchmark input, not as
  facts about any real package), stress ≈ 50k.
- Determinism gates: two builds byte-identical; macOS/Linux/Windows identical; enumeration
  order independence; case-collision and reserved-name fixtures fail closed.
- Edge fixtures: Unicode/Polish names, 90+ char API names, dotted CustomField fullNames,
  namespace vs no-namespace twins, entry whose body contains `---` and fenced YAML.

## 4. Golden-query skeleton (~25 categories; expected results authored with the fixtures)

1. exact entry identity (`Flow:c:HarnessAlphaRouter`) → Top-1
2. exact CustomField identity (`CustomField:c:HarnessAlphaCase__c.Status__c`) → Top-1
3. full API name as free text (camelCase / snake / dotted forms)
4. Polish/Unicode term from an approved Purpose section
5. approved keyword lookup; 6. candidateKeyword must NOT rank in established lane
7. metadataType facet filter; 8. boolean/enum facet (e.g. `field.required=true`)
9. field label vs API name disambiguation
10. `referenceTo` lookup (which fields point at HarnessAlphaCase__c)
11. relation kind precision: writes-field vs reads-field vs filters-field
12. one-hop impact of a CustomField type change
13. namespace twin collision → `ambiguous`, never top-score guess
14. draft vs approved lane separation (same subject in both states)
15. `approved-drifted` visibility (excluded from current, visible in its lane)
16. exact intentional-error source message → owning Flow + element
17. resolved `$Label` default text match
18. safe fingerprint match (merge-field message variant)
19. Custom Error element API name lookup
20. runtime platform exception text → **abstention** (`No intentional Flow error matched.`)
21. ValidationRule/DuplicateRule decoy text → excluded from intentional-error mode
22. prompt-injection text pasted as query → treated as data, zero instruction-following
23. zero-result query → explicit gaps/excludedCounts, no silent relaxation
24. entryRef verification: current / digest-mismatch / scope-mismatch / not-approved
25. tamper fixture (§1.1) → never served as `approved-current`

## 5. Standing constraints the reviewer must respect

- No SQL databases (owner constraint) — files-only designs.
- Windows-first team; no PowerShell dependencies; VS Code Copilot host has no sandbox.
- v1 claims/evidence/reviews remain canonical for org observations — attacks proposing
  their removal are out of scope.
- Screen Validation inclusion is an owner decision, not a reviewer decision — flag, don't decide.
- Implementation is not authorized by this package regardless of verdict.
