# Knowledge One-File Entry — frozen contract v1.1 (T07 Phase 0)

```text
Status:                 CONTRACT v1.1 — adversarial review findings applied
Review outcome:         3 independent reviewers, unanimous ACCEPT WITH REQUIRED CHANGES
                        (2026-07-24); all 34 required changes incorporated below and
                        recorded in docs/knowledge-one-file-review-package.md §6
Owner decision D1:      2026-07-24 — one-file model supersedes "stay on v1, pilot first"
Canonical format:       Markdown + YAML frontmatter (owner decision 2026-07-24)
Implementation:         P1 authorized AFTER this v1.1 is accepted; storage code follows
                        the impact-map phase plan
Companion documents:    docs/knowledge-one-file-impact-map.md (dependency wiring)
                        docs/knowledge-one-file-review-package.md (review record + evals)
Draft schemas:          schemas/knowledge-entry.schema.json (+ 2 profile schemas) — unwired
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
| Collector bump, changed assertion OR coverage/assurance regression | `approved-drifted` (only affected entries) |
| Profile MAJOR bump | `approved-drifted` until re-approval; MINOR/PATCH stays current |
| `sensitivity` flip | `reviewedContentDigest` changes → re-approval required |
| `notes`/`candidateKeywords` edits | stays current (advisory) |
| `keywords` edit | stays current, but only executor-mediated + ledger-logged |
| Frontmatter `state`/approval block hand-edited | recomputation or ledger mismatch → not effective |
| Old approved bytes restored (git revert/restore) | ledger-latest check fails → `revoked`/not current (§6.1; review R1-1) |

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

## 11. Explicit non-goals (unchanged from v1.0)

No storage/engine code in Phase 0; no changes yet to prompts, skills, agents, guard, hook,
work_record, registered schemas, contracts, templates; no v1 migration/deletion; no Screen
Validation; no runtime error catalog; no vector search; no SQL; no cutover before parity
certification. P1 implementation proceeds only against this v1.1 text plus the impact-map
phase plan.
