# Knowledge One-File Entry — frozen contract (T07 Phase 0)

```text
Status:                 CONTRACT FROZEN FOR ADVERSARIAL REVIEW
Owner decision D1:      2026-07-24 — one-file model supersedes "stay on v1, pilot first"
Canonical format:       Markdown + YAML frontmatter (owner decision 2026-07-24)
Implementation:         NOT AUTHORIZED — design artifact only
Companion documents:    docs/knowledge-one-file-impact-map.md (dependency wiring)
                        docs/knowledge-one-file-review-package.md (adversarial review handoff)
Draft schemas:          schemas/knowledge-entry.schema.json (+ 2 profile schemas) — unwired
Prior architecture docs: docs/knowledge-facts-overlay-architecture.md = SHELVED fallback,
                        NOT the operative design (no separate facts lockfile — facts live
                        inside the entry); docs/force-app-knowledge-architecture.md
                        describes the v1 pilot and will be updated at cutover, not before.
```

## 1. Scope of supersession

The one-file model replaces the claim/evidence/review triple **only for repository-derived
knowledge about force-app source artifacts**. Everything else is explicitly retained:

| Content class | Canonical store after this contract |
|---|---|
| Repository-derived artifact knowledge (structure, references, intentional errors, approved descriptions) | **One Knowledge Entry file per logical artifact** (this contract) |
| Org observations (describe, installed packages, reference-data samples) | v1 immutable Evidence YAML + semantic Claims + Reviews — **unchanged** |
| Business/process/vendor/runtime semantics not derivable from source | v1 semantic Claims + Reviews — **unchanged** |
| Human review receipts for v1 claims | v1 Reviews — **unchanged, immutable** |

`.ai/contracts/knowledge-lifecycle.md` currently mandates the three-record model for all
Knowledge. This contract **narrows its scope** to the retained classes above; the lifecycle
contract must be amended in the same change that wires the first entry executor (Phase 1 of
the impact map), never silently.

## 2. Entry file

One canonical file per **logical** Salesforce artifact (Apex class = `.cls` +
`.cls-meta.xml`; LWC = whole bundle; Flow = flow file + activation info):

```text
.ai/knowledge/artifacts/<MetadataType>/<safe-name>.md
```

### 2.1. Frontmatter fields

| Field | Req | Content |
|---|---|---|
| `schemaVersion` | ✓ | integer, this contract = 1 |
| `subject.metadataType` | ✓ | exact metadata type API name (e.g. `Flow`, `CustomField`) |
| `subject.fullName` | ✓ | exact component full name (`Object.Field` for CustomField) |
| `subject.namespace` | ✓ | package namespace or `null` (subscriber-owned) |
| `profile.id` | ✓ | metadata-type profile id (e.g. `salesforce.flow`) |
| `profile.version` | ✓ | semver of the profile schema used at extraction |
| `profile.digest` | ✓ | digest of the profile schema document |
| `scope.sourceApiVersion` | ✓ | component/project API version |
| `scope.sourceTreeDigest` | ✓ | digest of the analysed source scope (NOT a commit SHA — see §5.4) |
| `scope.packageVersionId` |  | `04t…` or `null` (`unversioned-source` scope) |
| `source.fragments[]` | ✓ | every contributing source file: `{path, sourceDigest}` |
| `lifecycle.state` | ✓ | `draft` \| `approved` (user-facing; effectiveness is computed — §4) |
| `lifecycle.contentDigest` | ✓ | `reviewedContentDigest` recomputation input receipt (see §5) |
| `typeFacts` | ✓ | profile-validated structured facts (never free-form `{}`) |
| `intentionalErrors[]` |  | Flow only: source-declared `FlowCustomError` entries (§7) |
| `extractionCoverage` | ✓ | per-section parser coverage: `full` \| `partial` \| `generic` |
| `assurance` | ✓ | per-section marker: `source-exact` \| `source-derived-heuristic` |
| `limitations[]` | ✓ | material extraction limitations (may be empty) |
| `keywords[]` | ✓ | approved-taxonomy terms only (validated at draft time) |
| `candidateKeywords[]` | ✓ | advisory, free-form, never in established ranking |
| `sensitivity` | ✓ | `public` \| `internal-sanitized` (only committable classes) |
| `approval.reviewedContentDigest` | ✓ | `null` until approved |
| `approval.reviewedBy` | ✓ | `null` \| full name matching `knowledge.chatReviewer` |
| `approval.reviewedAt` | ✓ | `null` \| UTC timestamp |
| `approval.mechanism` | ✓ | `null` \| `copilot-chat-entry-confirmation` |

### 2.2. Body (attested semantics)

Markdown sections after the frontmatter — the prose a human actually vouches for:

- `## Purpose` (required for approval; 2–6 sentences, agent-drafted, human-reviewed)
- `## Business context` (optional)
- profile-defined optional sections (declared in the profile schema, never invented ad hoc)

The body must never contain: credentials, raw record data, runtime payloads, instructions,
copies of `typeFacts` (no duplicated truth), or claims about closed-package internals,
runtime behavior, or vendor guarantees (those remain v1 semantic claims with evidence).

## 3. Identity and Windows path policy

Canonical identity (stable, citation-grade):

```text
<MetadataType>:<namespace|c>:<FullName>       e.g.  Flow:c:EngagementRouter
                                                    CustomField:pkg:Order__c.Status__c
```

Path derivation: `safe-name` = NFKC-normalized `FullName` with `.` → `__`, characters outside
`[A-Za-z0-9_-]` percent-encoded, truncated at 100 chars with an 8-char digest suffix on
truncation. Build-time checks (fail closed):

- case-fold collision between two identities → error, never silent overwrite;
- Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`) → digest-suffixed;
- trailing dots/spaces stripped; full path length budget ≤ 200 chars from repo root;
- grouping by object/feature/domain is a **generated view concern**, never canonical identity
  (a Flow changing its trigger object must not move its canonical file).

## 4. Lifecycle lanes and effectiveness

User-facing state is binary (`draft` | `approved`). Effective lane is **computed at read
time** — never stored, never trusted from the file alone:

```text
approved-current      state == approved
                      AND approval.reviewedContentDigest == recomputed reviewedContentDigest
                      AND scope.sourceTreeDigest matches the requested source scope
                      AND profile.version is supported
approved-drifted      approved, digest matches, but source has moved on (facts regenerable)
approved-expired      approved, but profile/policy review window elapsed (policy-driven)
draft                 state == draft (never served alongside approved results)
scope-mismatch        citation asks for a different source scope than the entry carries
unsupported-profile   profile version revoked or unknown to the reader
```

Rules: a draft never outranks or interleaves with approved results; `approved-drifted` is
visible but excluded from `approved-current` consumers; SAFE verdicts may cite only
`approved-current` entries (see §8).

## 5. Digest boundary (the anti-reapproval-wave core)

Three digests, computed with the existing `canonical_digest` / `file_sha256` utilities
(`scripts/knowledge_registry.py:253-259`):

### 5.1. `factsDigest`

Canonical JSON serialization of `{typeFacts, intentionalErrors, material limitations}` —
**excluding** collector version, extraction config, timestamps, and coverage metadata.
Consequence: a collector upgrade that produces byte-identical assertions changes nothing;
a collector upgrade that changes an assertion flips exactly the affected entries to
`approved-drifted` — never a global re-approval wave.

### 5.2. `semanticsDigest`

Digest of the body after normalization: LF line endings, NFKC, trailing-whitespace strip.
The body is what the human read; nothing outside it may alter this digest.

### 5.3. `reviewedContentDigest`

```text
reviewedContentDigest = canonical_digest({
  identity:        "<MetadataType>:<ns|c>:<FullName>",
  profileMajor:    profile.id + "@" + major(profile.version),
  factsDigest:     …,
  semanticsDigest: …,
})
```

Approval binds to this value and nothing else. Explicitly excluded (so their change cannot
silently invalidate or silently preserve approval): `keywords`/`candidateKeywords` (advisory),
`extractionCoverage` metadata, collector identity, `scope.sourceTreeDigest` (drift is a lane,
not an approval bit).

### 5.4. No self-reference, no timestamps

Digest inputs never include the containing commit SHA or a generation timestamp (the two
FAIL classes of the shelved v2 design). `scope.sourceTreeDigest` is a digest of the analysed
source tree content, computable before any commit exists.

### 5.5. Invalidation matrix

| Change | factsDigest | semanticsDigest | reviewedContentDigest | Result |
|---|---|---|---|---|
| Body prose edited | – | changes | changes | state forced back to `draft` |
| Source changed → facts regenerated differently | changes | – | changes | `approved-drifted` lane; re-approval shows the facts diff |
| Collector bump, identical assertions | – | – | – | nothing; stays `approved-current` |
| Collector bump, changed assertion | changes | – | changes | `approved-drifted` (only affected entries) |
| Profile MAJOR bump | – | – | changes | `approved-drifted` until re-approval |
| Profile MINOR/PATCH bump | – | – | – | stays current (schema-compatible) |
| Keywords/coverage/limitations(non-material) edits | – | – | – | stays current |
| Frontmatter `state` flipped to `approved` by hand | – | – | mismatch vs `approval.reviewedContentDigest == null` | entry is NOT effective — computed lane wins |

The last row is the tamper case: because effectiveness is computed (§4), editing
`lifecycle.state` or pasting a stale digest cannot make an entry effective — the recomputed
`reviewedContentDigest` will not match `approval.reviewedContentDigest` unless the exact
reviewed content is present. **This is the primary adversarial-review target.**

## 6. Four design decisions (resolved; prime review targets)

1. **Approval command shape** — a separate executor subcommand (working name
   `knowledge_store.py entry-approve`, final naming at Phase 1) with its own flag allowlist
   wired into the role guard and pinned by the guard↔parser contract test. `approve-claim`
   is NOT overloaded; the two lifecycles stay operationally distinct.
2. **Citation type** — a new `entryRef`:
   ```yaml
   entryRef:
     entryId: "Flow:c:EngagementRouter"
     reviewedContentDigest: "sha256:…"
     factsDigest: "sha256:…"
     sourceTreeDigest: "sha256:…"
     profile: "salesforce.flow@1"
   ```
   Added **additively** to the three envelope schemas (`output-envelope`, `change-record`,
   `handoff-envelope`); `claimRef`/`evidenceRef` grammar untouched; no reinterpretation of
   historical claim IDs. `verify-citations` verdicts for entryRefs:
   `current | historically-valid | digest-mismatch | scope-mismatch | not-approved | missing`.
3. **Approval mechanism** — the existing chat-approve pattern
   (`scripts/copilot_safety_hook.py:774-787` precedent): agent runs the approve command only
   after the user invokes `/approve-drafts-knowledge`; the safety hook answers `ask`; the
   human click is recorded as mechanism `copilot-chat-entry-confirmation`; reviewer identity
   comes from local `knowledge.chatReviewer`. Work-record approval stays reserved for design
   sign-off and remains human-terminal-only.
4. **Draft location** — drafts live **in place** at `.ai/knowledge/artifacts/` with
   `lifecycle.state: draft`. The path is a governed path (role guard
   `is_governed_record_path`): raw file edits are denied to every role; all writes flow
   through deterministic executor commands (`entry-draft`, `entry-approve`) available to
   `config-investigator` and `knowledge-curator` only. The `<AGENT_…>` sentinel rejection
   carries over: an entry containing an unfilled sentinel can never be approved. No second
   draft directory, no draft/canonical split.

## 7. Flow intentional errors (pilot scope)

`intentionalErrors[]` may contain **only** author-declared `FlowCustomError` elements:

- kind fixed to `flow-custom-error`; extractor origin must be the `FlowCustomError` element —
  `screen-validation` and `fault-path` records from the current `errorCatalog` are excluded
  and must not migrate into this field;
- per entry: `elementApiName`, `elementLabel`, `messageTemplate` (source text),
  `resolvedDefaultText` (only if actually read), `customLabelRefs[]`, `presentation`
  (`record` | `field` + optional field), `reachability` (trigger context, static decision
  guards, `truncated` flag), `basis: source-declared`, `limitations[]`;
- static reachability is never presented as runtime execution proof;
- Screen Validation stays an OPEN owner decision and is out of v1;
- runtime faults, platform error codes, and hypothesized root causes never enter the entry.

## 8. SAFE-CLAIM v2 draft (Tier 1 change — requires owner sign-off, not part of Phase 0)

Proposed amended text (target: `.github/copilot-instructions.md`, SAFE-CLAIM-001):

> Material factual assertions require governed grounding:
> — a **current, schema-valid `entryRef`** may ground assertions about the *intended
>   repository-source state* of a force-app artifact in matching scope
>   (`approved-current` lane only);
> — all other material assertions (deployed org state, runtime behavior, business meaning,
>   package limitations, vendor guarantees, completeness/absence) require an **effective
>   `claimRef` with applicable `evidenceRef`s**, exactly as today.
> Model output, chat recollection, generated views, and draft entries are never evidence.

Companion changes in the same future change-set: `knowledge-lifecycle.md` scope narrowing
(§1), `source-authority.md` applicability note, `work_record.py` `validate_claim_refs`
extension to accept entryRefs where intended-source-state grounding suffices (touchpoints
enumerated in the impact map). None of this is executed in Phase 0.

## 9. Approval flow and batching

`/approve-drafts-knowledge` (future prompt; specified here, not created):

1. User invokes the prompt (conscious act = declaration that drafts were reviewed).
2. Agent lists the exact entry set: identity + `reviewedContentDigest` + a facts/semantics
   diff summary per entry.
3. Agent runs the approve executor; safety hook answers `ask`; the human click approves
   **only the displayed digest set** — any content change after display fails closed.
4. Chunking respects `config/knowledge-policy.json` promotion caps: ≤ 25 entries per
   confirmation click; bulk component-inventory-style manifests ≤ 500 with an explicit
   manifest confirmation, mirroring the existing `manifestApproval` policy.
5. Executor stamps `approval.*`, flips `lifecycle.state`, and regenerates affected search
   projections (Phase T08b concern).
6. A failed validation (schema, sentinel, keyword, sensitivity) rejects the whole chunk with
   a named reason; partial approval of a chunk is not possible.

## 10. Keywords, sensitivity, taxonomy

- `keywords[]` accepts only terms present in the approved keyword taxonomy at draft time
  (machine-checked; unapproved terms reject the draft operation, mirroring v1);
- `candidateKeywords[]` is advisory and excluded from established ranking (T08 rule);
- taxonomy growth stays human-curated via the existing curation workflow;
- `sensitivity` limited to `public` | `internal-sanitized`; the collector's sanitizer runs
  before anything reaches the entry (unchanged pipeline position).

## 11. Acceptance-criteria mapping (self-check)

| Criterion | Where satisfied |
|---|---|
| KARCH-001 separate type identities | §1 table; entry vs claim vs evidence remain distinct types with distinct refs (§6.2) |
| KARCH-002 views are not authority | generated projections/dossiers excluded from citations (§4, §6.2); only entry file is canonical |
| KFACT-002 no timestamps / self-SHA in deterministic payload | §5.4 |
| KFACT-003 facts bound to source scope + config identity | §2.1 (`scope.*`, `source.fragments`, profile digest); collector identity outside digest but inside provenance |
| KFACT-004 stable ID, digest, locator, assurance, limitations | §2.1, §3 |
| KSEM-001 agent creates only drafts | §6.4 (executor-only writes; draft state) |
| KSEM-002 approval is a separate receipt | §2.1 `approval.*` + §5.3 binding (recorded in-file but digest-bound; tamper case §5.5) |
| KSEM-003 approval binds exact digest, scope, dependencies | §5.3, §9.3 |
| KSEM-004 reviewer authority matches claim type | pilot: single `chatReviewer` (documented limitation → review package question Q10) |
| KUX-002 deterministic facts need no per-record human approval | facts regeneration alone never demands re-approval (§5.5 rows 3, 6, 7) |
| KUX-003 approval shows semantic diff + dependencies | §9.2 |

## 12. Explicit non-goals (Phase 0 and this contract)

No storage/engine code; no prompt/skill/agent/guard/hook/work_record/schema-registration
changes; no migration of v1 records; no Screen Validation; no runtime error catalog; no
vector search; no SQL (files only — standing owner constraint); no fixture data generation;
no cutover or deprecation of v1 query paths before parity certification (T08b gates).
