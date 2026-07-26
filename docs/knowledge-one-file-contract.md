# Knowledge One-File Entry — frozen contract v1.1 (T07 Phase 0)

```text
Status:                 CONTRACT v1.1 — adversarial review findings applied
Review outcome:         3 independent reviewers, unanimous ACCEPT WITH REQUIRED CHANGES
                        (2026-07-24); all 34 required changes incorporated below and
                        recorded in docs/knowledge-one-file-review-package.md §6
Owner decision D1:      2026-07-24 — one-file model supersedes "stay on v1, pilot first"
Canonical format:       Markdown + YAML frontmatter (owner decision 2026-07-24)
Implementation:         SHIPPED. P0-P6 are merged on knowledge-relations-p0-p6; this
                        contract is normative for the code, not a proposal ahead of it.
                        Current status of the work lives in exactly one place:
                        docs/knowledge-completion-audit-2026-07-25.md § Disposition.
                        [status line corrected 2026-07-25, wave 3 - it still read
                        "P1 authorized AFTER this v1.1 is accepted"]
Companion documents:    docs/knowledge-one-file-impact-map.md (dependency wiring)
                        docs/knowledge-one-file-review-package.md (review record + evals)
Schemas:                schemas/knowledge-entry.schema.json, knowledge-feature-entry
                        .schema.json and 9 profile schemas covering the 10 profiled
                        types - WIRED: knowledge_store.PROFILES validates every draft
                        against its profile schema (ApexClass and ApexTrigger share one)
                        [was "(+ 2 profile schemas) - unwired"; corrected wave 3]
Prior architecture docs: docs/knowledge-facts-overlay-architecture.md = SHELVED fallback;
                        docs/force-app-knowledge-architecture.md = v1 pilot description,
                        updated at cutover.
```

## 1. Scope of supersession and claim-type home assignment

The one-file model replaces the claim/evidence/review triple **only for repository-derived
knowledge about force-app source artifacts**. Deterministic home assignment is keyed on
`claimType × evidenceType` (review R3-1), enforced by the registry at `propose` time from P2:

| claimType | metadata-repository leg | org/other evidence legs |
|---|---|---|
| `component-description`, `component-inventory` | **entry-home**; v1 drafting frozen at P2 (metadata-repository is their only allowed evidence) | n/a |
| `automation-inventory`, `field-schema`, `object-existence`, `object-relation`, `component-relation`, `integration`, `object-ownership` | **entry-home**; v1 metadata-repository drafting frozen at P2 | **v1-home** (org-describe, tooling, SME, vendor legs stay v1) |
| `reference-data`, `business-meaning`, `process`, `glossary`, `runtime-behavior`, `package-limitation`, and all remaining types | n/a | **v1-home**, unchanged |

**Freeze scoping** (implemented T07 P2): the registry refuses a repository-only proposal for
an entry-home claim type when — and only when — the metadata type has an implemented entry
profile AND this workspace already holds entries. Freezing unconditionally would strand the
repository facts of every metadata type whose profile has not shipped (2 of ~59 today), which is
a capability regression rather than a migration. The freeze therefore widens automatically as
profiles ship, and activates per workspace on adoption.

**Shadowing rule** (review R3-2): once an entry exists for a subject, a v1 claim grounded in
`metadata-repository` evidence may not ground a SAFE verdict for the same subject/predicate;
`validate_claim_refs` reports it as `shadowed-by-entry` (P3 wiring). Cross-system
contradiction (entry facts vs verified v1 claim) must surface as `CONTESTED` in unified
query and `verify-citations` (P2 wiring).

`.ai/contracts/knowledge-lifecycle.md` scope is narrowed accordingly in the same change
that wires the first executor (P1), never silently.

## 2. Entry file

One canonical file per **logical** Salesforce artifact:

```text
.ai/knowledge/artifacts/<MetadataType>/<ns|c>/<safe-name>.md
```

The namespace segment is part of the canonical path (review R2-1): namespaced and
subscriber-owned twins are distinct files by construction.

### 2.1. Frontmatter fields

| Field | Req | Content |
|---|---|---|
| `schemaVersion` | ✓ | integer, this contract = 1 |
| `subject.metadataType` | ✓ | exact metadata type API name |
| `subject.fullName` | ✓ | exact component full name (`Object.Field` for CustomField) |
| `subject.namespace` | ✓ | package namespace or `null`. The literal value `"c"` is **rejected** (reserved as the subscriber sentinel in identity/paths; also Salesforce's default LWC namespace) (review R2-4) |
| `profile.id` / `.version` / `.digest` | ✓ | metadata-type profile identity |
| `scope.sourceApiVersion` | ✓ | component/project API version |
| `scope.sourceTreeDigest` | ✓ | **fragment-scope digest**: canonical digest over the entry's own `source.fragments` (path, sourceDigest) set — NOT a whole-tree digest and never a commit SHA (review R1-8; prevents per-commit corpus-wide drift waves) |
| `scope.packageVersionId` |  | `04t…` or `null` |
| `source.fragments[]` | ✓ | every contributing source file: `{path, sourceDigest}` |
| `lifecycle.state` | ✓ | `draft` \| `approved` (user-facing; effectiveness computed — §4) |
| `lifecycle.contentDigest` | ✓ | recomputation receipt |
| `typeFacts` | ✓ | profile-validated structured facts |
| `intentionalErrors[]` |  | Flow only (§7) |
| `extractionCoverage` | ✓ | per-section coverage; **required for every populated section**; digest-bound (§5.1) |
| `assurance` | ✓ | per-section markers; **required for every populated section**; section marker = weakest member; per-edge markers required inside `references[]`; digest-bound (reviews R1-6, R2-9) |
| `limitations[]` | ✓ | **all** limitations are digest-bound; no materiality sub-classes (review R1-7) |
| `notes[]` |  | advisory, digest-excluded free text; consumers must never present it as approved content |
| `keywords[]` | ✓ | approved-taxonomy terms only; digest-excluded but **mutable only via audited executor events** (ledger-logged) (review R1-12) |
| `candidateKeywords[]` | ✓ | advisory, free-form, never in established ranking |
| `sensitivity` | ✓ | `public` \| `internal-sanitized`; **digest-bound** (inside `reviewedContentDigest`) — a sensitivity flip forces re-approval (review R1-12) |
| `approval.reviewedContentDigest` | ✓ | `null` until approved |
| `approval.reviewedBy` / `.reviewedAt` / `.mechanism` | ✓ | mirror of the ledger record (§6.1); the **ledger**, not the file, is authoritative for who/when/how (review R2-12) |

### 2.2. Body (attested semantics)

- `## Purpose` — required for approval; 2–6 sentences; agent-drafted, human-reviewed.
- **Pilot restriction** (review R3-3): the approvable body is `## Purpose` only.
  `entry-draft` rejects a non-empty `## Business context` or any profile-defined section.
  Named expiry of this restriction: the earlier of (i) enabling any additional approvable
  body section, or (ii) P3 owner sign-off of SAFE-CLAIM v2 — either event requires a
  reviewer-authority matrix first (recorded in the decisions log at P1).

Body must never contain: credentials, raw record data, runtime payloads, instructions,
copies of `typeFacts`, or claims about closed-package internals / runtime behavior /
vendor guarantees (v1 semantic claims with evidence remain the home for those).

## 3. Identity, encoding, and Windows path policy

Canonical identity: `<MetadataType>:<ns|c>:<FullName>` (the `c` sentinel cannot collide
with a real namespace — §2.1 rejects literal `"c"`).

**Safe-name encoding (injective — review R2-2):** NFKC-normalize `FullName`, then
percent-encode every character outside `[A-Za-z0-9_-]` **including `.`** (no `.` → `__`
mapping; `__` is meaningful in Salesforce names). Percent-encoding is applied before
truncation.

**Truncation (review R2-3):** if the encoded name exceeds 100 chars, truncate at a
boundary that never splits a `%XX` triplet and append `-<8-char digest>` where the digest
is computed over the **full pre-truncation NFKC identity** (never over the truncated
prefix). If the final path still exceeds the ≤200-char budget, the build **fails closed**
naming both the identity and the budget.

**Build-time collision policy (generalized):** the build rejects ANY two identities whose
final derived paths are equal under Windows case-fold — covering case-fold collisions,
NFKC confusables, trailing-dot/space stripping, truncation collisions, and crafted names
equal to another name's truncated+suffixed form. Windows reserved device names get a
digest suffix. The error names both identities (never silent overwrite).

**Path↔identity round-trip (reviews R1-9, R2-11):** at build and read time, a file is
effective only if `derived_path(identity embedded in frontmatter) == actual path` AND the
identity resolves to exactly one file. A byte-copy at a second path, or two files claiming
one identity, fails closed (`ambiguous` / not effective — never served).

**No reparse points (review R1-10):** symlinks/junctions anywhere under `.ai/knowledge/`
fail the build; governed-path matching casefolds the relative path before matching.

## 4. Lifecycle lanes and effectiveness

User-facing state is binary. The effective lane is **computed at read time by the
reader/verify executor** — never stored, never trusted from the file alone:

```text
approved-current      state == approved
                      AND approval.reviewedContentDigest == recomputed reviewedContentDigest
                      AND that digest is the LATEST ledger record for this identity (§6.1)
                      AND path↔identity round-trip passes (§3)
                      AND scope.sourceTreeDigest matches the requested source scope
                      AND profile.version is supported
approved-drifted      approved + ledger-latest, but fragment-scope digest has moved on
approved-expired      approved, but policy review window elapsed
draft                 state == draft (never served alongside approved results)
scope-mismatch        citation asks for a different source scope
unsupported-profile   profile version revoked or unknown
revoked               a ledger revocation is the latest record for this identity (§6.1)
```

**Read-side rule (review R2-10):** any assertion of an entry's lane or an entryRef's
currency may be made **only from the reader/verify executor's output receipt**
(SAFE-TOOL-001 alignment). Directly reading frontmatter never establishes approval; an
agent reporting `approved` from a raw file read violates the contract. Golden eval 25
covers the honest reader; eval R-06 covers the lazy reader.

## 5. Digest boundary

Three digests over **parsed canonical content** (§5.6), reusing `canonical_digest` /
`file_sha256` (`scripts/knowledge_registry.py:253-259`; executor wraps `file_sha256`
output with the `sha256:` prefix — review R1-4 nit).

### 5.1. `factsDigest`

Canonical serialization of `{typeFacts, intentionalErrors, limitations,
extractionCoverage, assurance}` — coverage and assurance ARE digest-bound (a
`full`→`partial` regression is a material weakening and must flip the lane; review R1-6).
Excluded: collector version/config, timestamps, `notes`, `keywords`, `candidateKeywords`.

**Array ordering (review R1-5):** canonicalization sorts `references[]` by
`(kind, target)`, `variables[]` by `apiName`, `customLabelRefs[]` lexically, and
`limitations[]`/`extractionCoverage`/`assurance` by key; `operations[]` keeps source order
(execution order is semantic). Enumeration-order changes in the collector therefore never
change `factsDigest`.

### 5.2. `semanticsDigest`

Digest of the body after normalization: LF, NFC, trailing-whitespace strip. Everything a
consumer reads as approved meaning must live here or in §5.1's bound set.

### 5.3. `reviewedContentDigest`

```text
reviewedContentDigest = canonical_digest({
  identity, profileMajor, factsDigest, semanticsDigest, sensitivity
})
```

`sensitivity` is inside (review R1-12). Excluded and therefore mutable without approval
impact: `notes`, `candidateKeywords`, and `keywords` (the latter only via ledger-logged
executor events). Approval provenance (who/when/how) is authoritative in the **ledger**,
not the file (§6.1) — mutating the file's `approval.reviewedBy` mismatches the ledger and
fails validation.

### 5.4. No self-reference, no timestamps

Digest inputs never include the containing commit SHA or generation timestamps. The
fragment-scope digest (§2.1) is computable before any commit exists.

### 5.5. Invalidation matrix

| Change | Result |
|---|---|
| Body prose edited | `semanticsDigest` changes → state forced to `draft` |
| Source fragment changed → facts regenerate differently | `approved-drifted`; re-approval shows executor-rendered diff |
| Collector bump, identical canonical assertions (incl. reordered arrays) | nothing — stays `approved-current` |
| Collector bump, changed assertion OR coverage/assurance regression | `approved-drifted` (only affected entries) — **NOT IMPLEMENTED, see below** |
| Profile MAJOR bump | `approved-drifted` until re-approval; MINOR/PATCH stays current |
| `sensitivity` flip | `reviewedContentDigest` changes → re-approval required |
| `notes`/`candidateKeywords` edits | stays current (advisory) |
| `keywords` edit | stays current, but only executor-mediated + ledger-logged |
| Frontmatter `state`/approval block hand-edited | recomputation or ledger mismatch → not effective |
| Old approved bytes restored (git revert/restore) | ledger-latest check fails → `revoked`/not current (§6.1; review R1-1) |

**Unimplemented row — collector/assurance drift (recorded 2026-07-25).** `compute_lane` decides
`approved-current` vs `approved-drifted` solely from `regenerate_fragment_digest`, which compares
**source-file bytes**. Nothing re-runs the collector, nothing diffs assurance, and no entry records
a collector version. So a change that alters what the collector *derives* from unchanged bytes —
notably an assurance regression — moves no lane and is never surfaced.

Two consequences worth stating plainly, because reading this matrix would otherwise suggest the
opposite:

- Ordering is the **only** control over a vocabulary or assurance change, not belt-and-braces. Such
  a change must land before the affected entries are approved; afterwards it is invisible. The
  ordering being relied on is **owner decision D1** (`docs/knowledge-master-plan-2026-07-25.md` §9):
  *"P0 + P1, one release, before any entry approval."* D1 is named here because it is the control,
  not because it is context — an implementer who reads this row and then reopens the digest window
  has removed the only thing standing between the store and a permanent silent divergence. There is
  no second mechanism to fall back on.
- The rule that derives an edge's assurance from its kind therefore has exactly one implementation
  (`relation_kinds.edge_assurance`, called only from the store's adapters). A second derivation at
  projection time could disagree with an approved entry forever, with nothing to detect it.

**What "invisible" means, measured (2026-07-25).** On the 189-entry reference corpus, all
`approved-current`: take an approved `ApexClass` entry whose `assurance.typeFacts` is
`source-derived-heuristic`, change the vocabulary so the same edges would now derive `source-exact`,
and re-read. The entry's lane is still `approved-current`, its `factsDigest` is byte-identical
(`sha256:1a197ff0…` before and after), and `entry-check` returns `PASS` over all 189 entries. The
assurance marker a human approved and the assurance the collector would now produce have diverged,
and **every gate in the system reports health.** That is the failure this row describes; it is not
hypothetical and it is not detected anywhere.

The direction of the divergence does not soften it. A heuristic → `source-exact` flip is the
*dangerous* direction: it leaves entries marked heuristic that the collector now believes are
exact, so §8.1 refuses grounding that would in fact be sound — annoying but safe. The reverse flip
leaves entries marked `source-exact` that are really heuristic, and §8.1 will ground on them. Only
D1's ordering decides which of those a release produces.

Making collector-version and assurance drift detectable is open work, not a shipped guarantee.

### 5.6. Canonical parse specification (review R1-4)

One shared strict parser is used by the executor, lane computation, and all projections:

- exactly one frontmatter block: the file starts with `---\n`, frontmatter ends at the
  first subsequent `\n---\n`; any later `---` belongs to the body (fixture-pinned);
- YAML 1.2 core schema; duplicate keys, anchors, aliases, and merge keys are **rejected**
  (closes the last-key-wins smuggle, review R1 H6);
- scalars: no 1.1 coercions (`NO`, sexagesimals, bare dates); ints and floats are distinct;
  `null` and absent-optional-field normalize identically in canonical serialization;
- strings inside typeFacts/body: NFC; identity normalization: NFKC (§3);
- the parser is versioned; a parser version bump is treated like a profile MAJOR bump for
  lane purposes unless byte-equivalence is proven on the corpus.

## 6. Approval mechanism

### 6.1. Append-only approval ledger (review R1-1 — load-bearing)

A governed, files-only, append-only ledger:

```text
.ai/knowledge/artifacts-ledger.jsonl
```

One JSON line per action: `{sequence, action: approve|revoke, identity,
reviewedContentDigest, reviewedBy, reviewedAt, mechanism, chunkId}`. Rules:

- written only by the approve/revoke executor; the path is governed (raw edits denied);
- `approved-current` requires the entry's recomputed digest to equal the **latest** ledger
  record for its identity — this defeats byte-replay of previously approved versions,
  provides **revocation** (`entry-revoke`, human-confirmed like approval), and quarantines
  any file present under the artifacts path before governance wiring (no ledger record →
  never effective; review R1-11);
- validator checks: monotonic sequence, append-only history (previous lines immutable
  across commits), every `approve` references an identity that exists and round-trips;
- the file's `approval.*` block is a convenience mirror; on mismatch the ledger wins and
  the entry is not effective.

### 6.2. Digest-pinned approval command (review R1-2)

`entry-approve` requires the exact digest set on the command line (per-entry
`--entry <identity>:<reviewedContentDigest>` pairs, or `--manifest <path>` whose file
digest is itself pinned as an argument). The safety-hook `ask` prompt displays the pinned
digests; the executor recomputes at execution time and **fails the whole chunk on any
mismatch** — a draft mutated between display and click cannot be approved (TOCTOU closed).
Precedent: `approve-claim --expected-revision` pinning.

### 6.3. Executor-rendered review surface (review R1-3)

The diff/summary a human approves against is generated **by the executor**, written to a
reviewable artifact (`output/knowledge-approvals/<chunkId>.md`): full body text for any
new/changed prose, canonical facts diff for fact changes. Agent-authored prose is never
the review surface.

### 6.4. Flow and batching

1. User invokes `/approve-drafts-knowledge` (conscious act).
2. Executor renders the review artifact (§6.3) and prints the digest-pinned command.
3. Safety hook answers `ask`; the human click approves only the pinned digest set;
   mechanism recorded as `copilot-chat-entry-confirmation`; reviewer identity from
   `knowledge.chatReviewer` is validated **at approval time** and stored in the ledger.
4. **Chunk caps** (review R3-4): entries with new/changed `semanticsDigest` (prose) are
   approvable only on the ≤25-per-click path. The ≤500 manifest path is restricted to
   **facts-only re-approvals**: entries whose `semanticsDigest` is unchanged versus their
   latest ledger-approved digest (drift re-approvals, sensitivity-unchanged). Initial
   approvals of prose-bearing entries can never ride the manifest path.
5. Validation (schema, sentinel, keyword-taxonomy, sensitivity, path round-trip) is
   all-or-nothing per chunk. **Stamping is per-file with a journaled resume point**
   (chunkId in the ledger): after a crash or a Windows `PermissionError`, entries whose
   stamp+ledger line completed are effective, the rest are not, and the executor reports a
   deterministic resume list (review R3-9 — §9.6 "atomic chunk" claim corrected).
6. Executor commands are the only write path (`entry-draft`, `entry-approve`,
   `entry-revoke`, keyword-edit); **all structured frontmatter (`typeFacts`,
   `intentionalErrors`, `source.*`, `scope.*`) is derived by the executor running the
   collector against source — never accepted as caller-supplied payload.** Callers author
   only body prose and `candidateKeywords` (review R2-5). The `<AGENT_…>` sentinel
   rejection carries over.

### 6.5. "No agent self-approval" — what the invariant means, and what enforces it

The master plan states *no agent self-approval* among its per-phase invariants, and the wording
reads like a code-level refusal. It is not one, and it was never meant to be: §6.1–6.4 make the
**human's chat click the approval mechanism**, and the click can only be spent on a command the
agent is then permitted to run. So the ruling, stated plainly because a reader who infers it from
the guard tables infers the opposite:

- `scripts/copilot_role_guard.py` **deliberately permits** `entry-approve`, `entry-revoke`,
  `feature-approve` and `feature-revoke` to the two knowledge mutation roles
  (`knowledge-curator`, `config-investigator`). Those rows are the design, not a hole. Deleting
  them does not harden anything — it removes the executor's only write path to the ledger and
  leaves a human with a rendered review artifact and nothing to click.
- The enforcement point is **`scripts/copilot_safety_hook.py`**, which answers `ask` for
  `(?:entry|feature)-(?:approve|revoke)` — one alternation over both record kinds, because
  approving a Feature boundary rule is the same act as approving an entry. The agent proposes the
  digest-pinned command (§6.2); the human's answer is what executes it; the mechanism recorded in
  the ledger is `copilot-chat-entry-confirmation`.
- The invariant therefore reads: **no approval record is ever written without a human click**, and
  it is violated by an approval command the hook does not intercept — never by a guard row.

That is now pinned rather than argued.
`tests/test_safety_hooks.py::test_every_approval_command_is_chat_confirmed_and_authoring_is_not`
partitions `copilot_role_guard.KNOWLEDGE_STORE_MUTATION_COMMANDS` by verb and asserts both
directions: all four approve/revoke commands return `ask`, and all four authoring commands
(`entry-draft`, `entry-describe`, `feature-propose`, `feature-describe`) do not — they write no
approval record and must not spend a click. The set is read from the guard, so a ninth mutation
command lands in one bucket or the other and is asserted the moment it is added. Before that test
the hook's coverage was pinned for two of the eight, which is how the completion audit could
record "the hook fires for 2 of the 8 mutation commands" as an open finding against an invariant
that was in fact holding.

## 7. Flow intentional errors (pilot scope)

`intentionalErrors[]` admits **only** author-declared `FlowCustomError` elements, and the
discriminator is structural, not asserted (review R2-6):

- each item carries `originTag: customErrors` (const) — the executor verifies the element
  exists under the flow XML's `<customErrors>` tag class at extraction time; a
  screen-validation or fault-path record relabeled `flow-custom-error` fails this check
  because the executor, not the caller, derives the items (§6.4.6);
- the migration mapping from today's collector kinds (`custom-error` →
  `flow-custom-error`) is one-to-one on origin tag, never on message shape;
- fields per item: as v1.0 (elementApiName, messageTemplate, resolvedDefaultText only if
  read, customLabelRefs, presentation, reachability with `truncated`, basis, limitations);
- static reachability is never runtime execution proof, and a template match never
  attributes an org error to this Flow (§8.2);
- Screen Validation remains an OPEN owner decision, outside v1;
- the v1 BM25 path over the mixed `errorCatalog` remains live until P5 parity cutover —
  consumers of "intentional errors" must use the entry-backed mode from P2 on; the legacy
  path answers only legacy queries and is retired at P5 (review R2 back-door flag).

## 8. SAFE-CLAIM v2 (Tier 1 change — OWNER-APPROVED 2026-07-24, implemented in P3)

### 8.1. Grounding rule (tightened per reviews R2-7, R1-6)

> Material factual assertions require governed grounding:
> — a **current, schema-valid `entryRef`** (currency established solely by a
>   reader/verify executor receipt) may ground **positive presence assertions** about the
>   intended repository-source state of a force-app artifact, for sections marked
>   `source-exact` with `extractionCoverage: full`, in matching scope
>   (`approved-current` lane only);
> — **absence and completeness assertions over source** ("X does not reference Y",
>   "these are all the fields") are NOT grounded by an entryRef unless the cited section's
>   digest-bound coverage is `full` AND the assertion is the machine-emitted enumeration
>   itself — interpretive absence claims require a v1 `claimRef` with completeness proof,
>   exactly as today;
> — deployed org state, runtime behavior, business meaning, package limitations, vendor
>   guarantees require an effective `claimRef` + applicable `evidenceRef`s, as today.
> Model output, chat recollection, generated views, draft entries, and raw frontmatter
> reads are never evidence.

### 8.1a. The grounding rule is enforced at the citation boundary (2026-07-25)

§8.1 was a rule the store told the truth for and no consumer checked. `work_record.py` contained
zero occurrences of the string `assurance`, so `validate_entry_refs` accepted an `entryRef` for an
entry whose `assurance.typeFacts` was `source-derived-heuristic` — the lane was checked, the
digests were checked, and the marker the whole three-digest boundary exists to protect was not.
A design document could ground *"class X operates on Assignment\_\_c"* on a regex match against a
comment, with no warning and no gap.

It is now enforced where it has consequences: binding or validating an `entryRef` reads the
**approved frontmatter** — never the caller's reference — and refuses unless **every populated
section** is marked `source-exact` with `extractionCoverage: full`. Every section, because an
`entryRef` names no section: it binds the whole entry, so any section a reader could take it
against has to qualify. The refusal names the section and both markers and points at a `claimRef`
as the alternative, because "refused" without a next step is how a fail-closed gate gets disabled.

**Measured blast radius — 58 of 189 entries in the reference package become ungroundable.**

| Type | Ungroundable | In package | Why |
|---|---|---|---|
| ApexClass | 48 | 52 | `object-token` / `invokes-class` / `soql-field` / `var-field-ref` — regex over source |
| ApexTrigger | 5 | 5 | same |
| **ValidationRule** | **2** | **2** | same, through the formula's object tokens |
| CustomField | 3 | 93 | formula fields whose references are token-derived |
| CustomObject, PermissionSet, RecordType, CustomMetadata, LWC | 0 | 37 | structural XML parsing throughout |

Two of those rows deserve a reader's attention. The plan's §0.1 predicted *"after P0, ApexClass and
ApexTrigger entries become ungroundable"* and stopped there — so **ValidationRule losing repository
grounding entirely (2 of 2) is new information**, and it is the type most likely to be cited in a
design document, because a validation rule is exactly the kind of business constraint a solution
design wants to assert. **CustomField is not all-or-nothing** either: 3 of 93 fail while 90 pass, so
"CustomField entries are groundable" is false as a blanket statement and a consumer must check per
entry rather than per type.

This is the fix working, not a regression: those entries were always heuristic and were always
marked so. What changed is that the marker now has teeth. An assertion that needs one of the 58
still has a route — a v1 `claimRef` carrying its own evidence — and that route is the one that was
always correct for an inference.

### 8.2. Runtime attribution rule (review R2-8)

Matching a runtime-observed error message to an `intentionalErrors[].messageTemplate`
grounds only: "the repository source at scope D declares this template on element E of
Flow F". It never grounds "this org error was produced by Flow F" — deployed versions may
differ and other automations can emit identical text. Consumer answer templates must use
the source-declaration phrasing (golden evals 16/18/20 wording).

### 8.3. Shadowing (review R3-2)

When an `approved-current` or `approved-drifted` entry exists for a subject, a v1 claim
whose supporting evidence is `metadata-repository` cannot ground SAFE for the same
subject/predicate; `validate_claim_refs` (P3) rejects or reports `shadowed-by-entry`.

## 9. Keywords, sensitivity, taxonomy

- `keywords[]`: approved-taxonomy terms only, validated at draft time; edits ledger-logged;
- `candidateKeywords[]`: advisory; excluded from established ranking;
- consumers never present `keywords`, `candidateKeywords`, `notes`, or coverage values as
  approved content (review R1-12);
- `sensitivity`: `public` | `internal-sanitized`; digest-bound (§5.3); sanitizer runs in
  the collector before anything reaches an entry.

## 10. Acceptance-criteria mapping (self-check, v1.1)

| Criterion | Where satisfied |
|---|---|
| KARCH-001 separate type identities | §1 table; entryRef distinct from claimRef/evidenceRef (§8) |
| KARCH-002 views are not authority | §4 read-side rule; §6.3 executor-rendered surfaces; projections non-citable |
| KFACT-002 no timestamps/self-SHA in payload | §5.4 |
| KFACT-003 facts bound to source scope + config identity | §2.1 fragment-scope digest; profile digest; parser version §5.6 |
| KFACT-004 stable ID, digest, locator, assurance, limitations | §2.1, §3; per-edge assurance required |
| KSEM-001 agent creates only drafts | §6.4.6 executor-only writes; caller-supplied facts rejected |
| KSEM-002 approval separate receipt | §6.1 append-only ledger (authoritative), file mirror secondary |
| KSEM-003 approval binds exact digest/scope/deps | §5.3, §6.2 digest-pinned command |
| KSEM-004 reviewer authority matches type | §2.2 Purpose-only pilot + named expiry + authority-matrix precondition |
| KUX-002 deterministic facts need no per-record approval | §5.5 (reorder/no-op collector bumps change nothing) |
| KUX-003 approval shows semantic diff + deps | §6.3 executor-rendered artifact |

## 10a. Retirement of the v1 repository path (P4/P5)

Retirement is **per metadata type**, never a global flip. A type leaves the v1 repository
path only when all of the following hold; until then its repository facts stay in the claim
registry and nothing about it changes:

1. an entry profile exists for the type (schema + adapter + facets + tests);
2. the workspace holds entries, so an alternative home is actually reachable;
3. entry coverage for the type is known — `knowledge_store.py entry-coverage` lists source
   components with no entry as gaps, and types with no profile separately as "no home yet";
4. citations for the type verify: `verify-citations` returns `current` for its entryRefs.

What retirement means in practice, and what is already enforced:

| Behaviour | State |
|---|---|
| New repository claims for the type | refused at `propose` (`enforce_entry_home_freeze`) |
| Collector drafting for the type | skipped, reported as `skippedEntryHome` in the draft manifest |
| Refresh waves for the type | replaced by the `approved-drifted` lane + per-entry re-approval |
| Relation claims for the type | replaced by entry `typeFacts.references` and the search relation graph |
| Existing historical claims | **kept and never reinterpreted**; they remain valid history and are shadowed for SAFE grounding by an approved entry on the same subject |
| Generated domain indexes / `claims-index.json` | continue to render the claim layer only; entry reporting lives in `entry-coverage` and the search index |

Types with no profile keep every v1 behaviour unchanged. This is why the freeze, the
collector skip, and the shadowing rule are all keyed on the profile set: coverage widens as
profiles ship, and no step of the migration can strand a metadata type without a home.

Full removal of the v1 repository-claim code paths stays gated on parity certification
against a real package (contract §12) — retiring behaviour per type is safe, deleting the
machinery is not, while unprofiled types still depend on it.

## 11. Explicit non-goals (unchanged from v1.0)

No storage/engine code in Phase 0; no changes yet to prompts, skills, agents, guard, hook,
work_record, registered schemas, contracts, templates; no v1 migration/deletion; no Screen
Validation; no runtime error catalog; no vector search; no SQL; no cutover before parity
certification. P1 implementation proceeds only against this v1.1 text plus the impact-map
phase plan.

## 12. Parity certification — RESERVED

Reserved for the parity-certification procedure that §10a and §11 gate the deletion of the
v1 repository-claim machinery on. Nothing is specified here yet; the number is held so it
cannot be silently reused for something else (owner decision D7, 2026-07-25).

## 13. Feature Entries

A **Feature Entry** is a human-approved **boundary rule** plus a human description of what
the feature is. It is the only Knowledge record in this contract whose subject is not a
Salesforce artifact, and it is deliberately not an entry: it has no source, no collector, no
profile, no facts, and it is never citable.

**Membership is never approved and never stored.** Membership is a function of the rule AND
of the package, so storing it would mean every new artifact drifts every feature that could
contain it, and a reviewer would be re-approving a list they never read. What a human
approves is the rule and the prose; membership is recomputed on demand from the rule against
the current index and reported as **advisory**.

### 13.1. What a Feature Entry holds

Schema: `schemas/knowledge-feature-entry.schema.json`, `kind: feature-entry` (the
discriminator exists for any reader that meets both record shapes).

| Block | Content |
|---|---|
| `subject` | `slug` (the identity, §13.2) and a human `name` |
| `boundary` | the RULE: `anchors` (≥1), `hubs`, `depth` (0-4), `include`, `exclude`, `membershipAssuranceFloor` |
| body | `## Purpose` — what the feature IS, written by a human; `<AGENT_…>` sentinels are rejected exactly as in §6.4 |
| `lifecycle` / `approval` | `draft`/`approved` plus the ledger mirror (§13.5) |

`hubs` are objects kept as an edge target but never expanded through; without them one shared
object (User, Account, a resource table) drags the whole model in at the next hop. Depth alone
cannot express a feature: measured on a 20-object package, depth 1 from one anchor reaches 3
objects, depth 2 reaches 13, and depth 4 saturates at 17, because every hop expands both along
an object's own lookups and along every field pointing at it. Anchors, hubs and explicit
include/exclude are what make a boundary a decision rather than a radius.

`membershipAssuranceFloor` is the weakest edge assurance allowed to *carry* membership
(§8.1 vocabulary). It is the second thing that stops a rule becoming a dragnet: measured on
one real boundary, 23 of 29 Apex members joined only through heuristic edges — classes that
merely mention the object name. Below-floor artifacts are still found, counted and labelled;
they are not presented as members.

### 13.2. Identity — `Feature:<slug>`, two segments

Canonical identity is `Feature:<slug>` — **two** segments, where `slug` matches
`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`, is ≤60 chars, and may not begin with a Windows reserved
device name.

Two rather than three is a safety decision, not a style one (owner decision D5). Artifact
identity is `<MetadataType>:<ns|c>:<FullName>` (§3), and `work_record.entry_relative_path`
unpacks a citation with `identity.split(":", 2)`. A **three**-segment `Feature:…:…` identity
would satisfy that unpack and resolve to a path under `ARTIFACTS_ROOT` that does not exist —
a Feature offered as an `entryRef` would fail silently, as a missing file. Two segments cannot
be unpacked that way, so the same mistake raises immediately.

Four independent things must therefore stay true, and none of them is allowed to be the only
one:

1. `entryId` in the three envelope schemas (`output-envelope`, `change-record`,
   `handoff-envelope`) carries an explicit `^(?!Feature:)` lookahead **backstopping** the
   three-segment pattern — the pattern alone blocks a Feature only incidentally;
2. `entry_relative_path`'s unpack fails loudly on two segments (above);
3. Feature files live outside `ARTIFACTS_ROOT` (§13.3), so no reader ever enumerates one as
   an entry;
4. a Feature has no `factsDigest`, `sourceTreeDigest` or `profile`, all of which an
   `entryRef` requires — there is nothing honest to put in those fields.

### 13.3. Where the files live, and that they are governed

```text
.ai/knowledge/features/<slug>.md
```

**Outside `ARTIFACTS_ROOT` by construction**, so `all_entry_paths()` and
`corpus_fingerprint()` never see a Feature. This keeps a Feature out of the artifact index
(§13.2 block 3) and keeps feature edits from invalidating the artifact corpus fingerprint.

Both the feature file and its ledger (§13.4) are **governed record paths**
(`is_governed_record_path`, matched case-folded per §3): raw edits are denied by the role
guard and writes happen only through the executor. The *file* needs its own arm, not just the
ledger — without it an agent could rewrite an approved boundary rule through the ordinary
write path and the digest pin would never see it, which is a direct breach of "agents never
self-approve".

The no-reparse-point rule of §3 applies. For single-feature commands it is scoped to the
features root: a `feature-status --slug` must not walk the entire artifact tree to prove a
symlink is absent.

### 13.4. The feature ledger is a separate file

```text
.ai/knowledge/features-ledger.jsonl
```

Same shape and same append-only rules as §6.1: one JSON line per action, monotonic
`sequence`, previous lines immutable, written only by the approve/revoke executor, and the
ledger — not the file's `approval` mirror — is authoritative.

It is a **separate** file from `.ai/knowledge/artifacts-ledger.jsonl` (owner decision D4)
because the artifact ledger's stamp is folded into every projection's reuse key: a shared file
would discard the whole artifact index on every feature approval. `feature-check` validates
this ledger's sequence and orphans exactly as `entry-check` does for the artifact ledger.

An `approve` record carries `{sequence, action, identity, reviewedContentDigest,
boundaryDigest, semanticsDigest, membershipDigest, reviewedBy, reviewedAt, mechanism,
chunkId}`; a `revoke` record carries `{sequence, action, identity, rationale, reviewedBy,
reviewedAt, mechanism}`. `membershipDigest` is a **digest, never a list** — see §13.7.

### 13.5. Approval mechanism

Identical in mechanism to §6, with the review surface adapted to what is actually being
approved:

1. `feature-propose` writes (or, with `--replace`, rewrites) the rule as a **draft**. An
   authored description survives a rule change; a rule change never survives as approved.
2. `feature-describe` writes the `## Purpose` prose from a file and returns the feature to
   `draft` — the previous approval covered the previous text.
3. `feature-review` renders the executor-authored review artifact under
   `output/knowledge-approvals/<chunkId>-feature-review.md`: the rule, field by field, the
   attested body verbatim, and the digest-pinned approve command. It states in the artifact
   that the reviewer is approving a rule and a description, **not** a member list.
4. `feature-approve --feature Feature:<slug>:sha256:<digest>` recomputes at execution time and
   fails the chunk on any mismatch (TOCTOU closed, §6.2). The safety hook answers `ask` and
   names what is being approved; the click is recorded as
   `copilot-chat-entry-confirmation`.
5. `feature-revoke --slug --rationale` appends a revocation, which is then the latest record.

`reviewedContentDigest` covers exactly `{identity, kind, schemaVersion, boundaryDigest,
semanticsDigest, sensitivity}`. **Membership is absent from it by construction** — that is
what makes an approved feature immune to package growth. `boundaryDigest` is taken over the
canonicalized rule, with `anchors`, `hubs`, `include` and `exclude` sorted and de-duplicated:
they are sets in meaning, so reordering them is not a re-approval.

Lanes are computed at read time, never trusted from the file (§4), with the same vocabulary
minus what cannot apply: a Feature has no source fragment, so `approved-drifted`,
`scope-mismatch` and `unsupported-profile` are unreachable. Only an edit to the rule, an edit
to the prose, or a ledger move can change a Feature's lane.

### 13.6. `feature-approve` never depends on the index

A governed human approval must not be blocked by a disposable cache. `feature-approve`
succeeds with a **stale or absent index**, recording `membershipDigest: null` (§13.7). The
reverse — refusing to record a human's decision because a `.cache/` directory is missing —
would put a cache in the approval path, which "never authority" forbids.

### 13.7. Membership: recomputed, advisory, and where its baseline lives

Membership is produced by `knowledge_search.py tree --feature <slug>`: a lane-filtered
traversal from the anchors, honouring hubs, depth, include/exclude and the assurance floor.
It is **lane-filtered** because postings contain draft, revoked and not-effective entries —
unfiltered, an approved feature's tree would present drafts as members with citation blocks,
and the drift baseline would invert (`changed: true` when someone drafts an unrelated entry,
`changed: false` when a real member is approved).

Because §13 rules a member list out of the ledger, the baseline lives in two places with two
different jobs:

| Layer | Home | Answers |
|---|---|---|
| `membershipDigest` | the ledger `approve` record | **whether** membership changed |
| identity list | `.cache/knowledge-search/feature-baseline-<slug>.json`, written by `tree` | **what** was added or removed |

The ledger's `membershipDigest` is the membership the approved rule produced against the index
**at approval time**, or `null` when no index was reachable (§13.6). A digest is not a member
list and cannot re-approve on drift, which is why it is admissible in a permanent
human-attributed record where identities the reviewer was told they were not approving are
not. The `.cache/` identity list is disposable, git-ignored and never authority.

`feature-drift` therefore answers in two layers:

- **`changed` comes from the ledger digest** versus the digest recomputed now. This is
  portable: it works on a machine that never held the approver's cache, which on a team of
  per-developer caches is the normal case. If the ledger record's `membershipDigest` is
  `null`, or the feature is not approved, `changed` is **`"unknown"`** with a gap naming the
  reason.
- **added/removed detail comes from the `.cache/` identity list.** An absent or foreign
  baseline makes the detail unavailable — reported as a gap naming the reason and the remedy —
  while `changed` still answers from the digest.

**`changed: false` is never reported for an absent baseline.** That inversion — "no baseline"
read as "nothing moved" — is the entire reason this split exists.

**Truncation answers honestly.** When the membership traversal hits its limits, the result
reports `truncated: true` and `changedWithinTruncatedPrefix` instead of a bare `changed`
value. The traversal is deterministic, so a truncated prefix is a real answer about a real
prefix; `changed: null` on every large feature would make the command useless exactly where
features matter, and silence is not an option.

A boundary rule that differs from the approved one is reported separately as
`boundaryRuleChanged` — that is a **re-approval**, not drift.

### 13.8. A generated view is never Knowledge

`tree`, `feature-dossier` and any file they write (`output/feature-dossiers/…`) are
**generated views**. They are not Knowledge, they are not approved, and they are never
citable — the member list in them is advisory and the dossier says so in its own first
paragraph. A reader who wants a citable reference is pointed at the executor receipt
(`knowledge_store.py entry-status --identity <Identity>`), never at a hand-built `entryRef`:
a projection's digests are content digests and `validate_entry_refs` rejects them outright.

## 14. Retrieval output: where the lane guarantee is visible

§4 computes lanes and §8.1 decides what may be cited, but a consumer only ever meets those rules
through a command's JSON. This section records the two shapes that carry the guarantee, because
both changed once already after the lane filter was applied to rows and not to the anchor — and a
consumer that reads a shape this contract never wrote down is a consumer that will read it wrong.

### 14.1. `context --identity` buckets by lane, and by relation kind

Approved and non-approved rows are **never in the same array**. Every bucket has an
`approved-current`-only array and a sibling `…NonCurrent` array that is populated only when a
caller opts into other lanes with `--state`:

`parts` / `partsNonCurrent` · `permissions` / `permissionsNonCurrent` · `incoming` /
`incomingNonCurrent` · `chains` / `chainsNonCurrent`.

A row keeps its own `lifecycle` label as well. The label alone was the previous design and it was
not enough: an array a caller iterates is an array a caller trusts, and the one place a lane label
reliably goes unread is inside a row that arrived in the approved bucket.

`incoming`, `incomingNonCurrent` and `outgoing` are **dictionaries keyed by relation kind**, not
flat arrays — `{"object-token": [...], "operates-on": [...]}`. A consumer written against the old
flat array does not degrade gracefully here; it fails, which is the intended outcome for a shape
change that alters what a row means.

The remaining keys: `outcome`, `artifactId`, `lifecycle`, `subject{facets, purpose, assurance,
coverage, limitations, citation}`, `partsCoverage{basis, entriesByType}` (§R5's denominator),
`chainsMeta{direction, depth, limitsHit[], excluded{lifecycle, heuristicEdge}, note}`,
`intentionalErrors`, `sourceCoverage`, `excludedCounts{lifecycle, heuristicEdge, cap}`, `gaps[]`,
`counts{documentReads, postingBytesRead}`, `indexGeneration`.

A chain row is `{node, hop, lifecycle, resolved, path[{from, kind, to, via, assurance}],
minAssurance, hydrated}`. `chains` requires `--include-heuristic` for the reason R6 gives: the
default answer to "how does this work?" is empty or near-empty for almost every Apex anchor, and
`--direction` governs which way the walk runs.

### 14.2. `impact` verifies its anchor, and says so

`impact` returns `anchorIdentity` and `anchorLifecycle` beside the caller-supplied `anchor`, and
every served row carries `hydrated`. The anchor is re-read and re-digested exactly as the rows are.

An **`ANCHOR:` gap is mandatory whenever the anchor is anything less than a verified entry in a
requested lane** — three cases, all executed against the reference corpus:

| Anchor state | `anchorLifecycle` | Gap |
|---|---|---|
| Approved-current, hydration passes | the lane | none — silence here means verified, and only here |
| Revoked, drifted, or tampered | the computed lane | names the lane and says the facts are *not* approved-current knowledge and must not be cited |
| No entry projects the identity | `null` | says the walk descends from a **name**, not from approved knowledge, and that this is absence of an ENTRY rather than absence of the artifact |

The last row is the one worth keeping. A traversal from an unknown name still returns edges, so a
reader who saw only the rows would read "nothing is wrong" out of a result that verified nothing.

## 15. The source-drift window: what a `lifecycle` label is, and is not

§4 says a lane is computed from the entry file and the ledger. §14 says every retrieval row wears
one. Neither said **when** it was computed, and the honest answer is not "now" for most rows. This
section states the window, because a consumer that reads `lifecycle: approved-current` as a
statement about the store right now will cite an entry the store has already moved.

### 15.1. Rows are index-fresh; the anchor is store-fresh

`corpus_fingerprint` stamps entry files and the ledger. `hydrate` re-digests the **entry file**.
Nothing under `force-app/` is in either — so appending one line to a Flow makes
`knowledge_store.compute_lane` return `approved-drifted` immediately while the index goes on
serving that entry as `approved-current`, hydrated, until the next `build`.

Every retrieval result therefore carries a `lifecycleBasis` object, and a standing gap saying the
same thing in prose. The values are a closed vocabulary:

| Field | Value | Meaning |
|---|---|---|
| `rows` | `index-fresh` | computed when this generation was built; nothing invalidates it on a source edit |
| `anchor` | `store-fresh` | re-checked against the working tree on this call (`explain`, `context`, and `impact` when an entry projects the identity) |
| `anchor` | `no-entry` | `impact` on a bare or unknown name — there is no entry to re-check, so nothing about the anchor is verified |
| `anchor` | `not-applicable` | `search` — it has no anchor; every hit is a row, including the one a caller named |

`lifecycleBasis` is on all four surfaces that serve lane-labelled rows: `search`, `explain`,
`impact`, `context --identity`. It is machine-readable on purpose. The eight Set A consumer
surfaces compose these arrays, and a prose gap in a `gaps[]` array is the thing an agent is least
likely to read.

### 15.2. What "store-fresh" actually verifies at the anchor

`verify_anchor` runs three checks, in this order, and each failure is an `ANCHOR:` gap:

1. **Lane membership** — the anchor's lane is inside the requested `--state` set (§14.2).
2. **Hydration** — the entry file is re-read and re-digested whole, so an edit to frontmatter the
   `reviewedContentDigest` never covered is caught (`hydrated: false` is not a fact).
3. **Source drift** — every fragment in the entry's recorded `source.fragments` is re-hashed
   against the working tree, and a mismatch names **which files moved**, states that the store
   computes `approved-drifted` for the entry right now, and tells the reader to rebuild before
   citing it.

Check 3 is gated on two preconditions, both load-bearing. It runs only **after hydration passes**,
because until the entry file is proved unchanged the projection's record of its own fragments is
itself in question; and only in lane **`approved-current`**, because that is the one lane where
`compute_lane` and the index can disagree — raising drift on a draft would report a state the store
does not recognise.

### 15.3. Rows are disclosed, not re-checked — and why that is the right trade

Serving rows get checks 1 and 2 as the index recorded them; they do **not** get check 3. That is
deliberate. §4.2 spent two rounds removing per-file work from the per-query path, and re-hashing
every served row's fragments would spend exactly what that bought. The window is stated instead of
implied, which is what R5 asks for and what silence was not. Closing it means either per-row
fragment hashing on the query path or a `force-app/` term in the freshness fingerprint — the same
cost, on every call, for a failure mode the next section already contains.

### 15.4. The citation boundary does not trust the index at all

None of the above can launder a stale entry into a work record. `work_record.validate_entry_refs`
resolves lanes through `knowledge_store.compute_lane` over the entry files and the ledger — it
never reads the index — and it additionally requires the entry to be groundable under §8.1a. So a
row served as `approved-current` from a generation built before a source edit **cannot be bound**
as a verified `entryRef`: the boundary recomputes and refuses.

The blast radius of the window is therefore bounded to what a reader does with a retrieval answer
by hand. That is not nothing — `context --identity` is the documented step-1 lookup for all eight
Set A consumer surfaces — which is why the disclosure is mandatory rather than advisory, and why
the anchor, the row a caller is most likely to act on, is the one that pays for the check.
