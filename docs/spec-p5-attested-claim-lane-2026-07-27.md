# P5 — the human-SME-attested claim lane

> ## ⛔ PARKED — 2026-07-27, same day it was written
>
> Owner moved the operating system to the **one-file Knowledge Entry model** and **parked the v1
> claim registry**. This spec is built entirely on that registry, so **none of it gets
> implemented.** It stays as a decision record — the analysis, the worked schema-valid YAML, the
> proven end-to-end run and the eight convention decisions are all still correct about how the
> registry behaves, should it ever be picked back up.
>
> Accepted consequence: **business meaning is no longer citable.** It lives as prose in the Feature
> Entry — human-approved, digest-pinned, ledger-recorded, never citable — which also means no
> expiry, no searchability, and no home at all for the meaning of managed-package surfaces.
> Context: `docs/knowledge-thread-2026-07-27.md` §7.

Status: **parked specification** (2026-07-27). Predecessor record:
`docs/discovery-2026-07-27-authored-feature-entry.md`. No repo changes made.

> **Rationale, settled after this spec was drafted (2026-07-27, second pass).**
> The spec was commissioned on *"business meaning MUST be citable"*. On review, **citability is the
> wrong justification** — it is nearly inert in this harness (see *Citing it → Enabled, not
> enforced*). **Build P5 anyway, for three other reasons:**
> 1. **Expiry.** A Feature Entry has no `reviewBy` and `additionalProperties: false`. Its prose never
>    goes stale, and source-drift cannot help: business meaning rots with the business, not the code.
>    An attested claim expires by itself and `stale-report` surfaces it.
> 2. **Discoverability.** `knowledge_search.build` projects `store.all_entry_paths()` only, so
>    Feature Entry bodies are the one thing `search --text` cannot find. Claims are queryable and
>    BM25-ranked.
> 3. **Managed-package surfaces** (`ApexPage:npnav__Example` and friends) have no other citable —
>    or even *findable* — home, ever.
>
> Cheaper routes to (1) and (2) were rejected: `reviewBy` on a Feature Entry lands inside
> `reviewedContentDigest`, so adding it later re-approves every feature; a second search projection
> moves `corpus_fingerprint`. Both touch load-bearing digest/index machinery mid-flight, while P5
> needs no schema change at all.
>
> **Scope decisions taken with this:** ship P1 (`from-notes`) *before* P5.1. Mint **2-3 claims per
> feature**, not 5 — feature-level *why* + *process* always, surface claims for managed-package
> components actually worked on, and skip per-object and glossary claims initially; every attested
> claim is a yearly re-attestation obligation. **Open question 3 is closed as NO:** do not make
> `business-meaning` required at the SAFE gate. Accept the new coupling knowingly — `validate_all`
> runs over the whole store on every `require_current=True` check, so the first attested claims mean
> one malformed claim can block human approval of every unrelated change record, which argues for
> P5.2 sooner rather than later.

## Headline

P5 is a **producer** for evidence that the system already accepts. An `attest` mode on
`/curate-knowledge` turns one named accountable person's paragraph into **one immutable
`human-sme-attestation` receipt plus N `proposed` claims**, each promoted by one chat click to a
`verified`, citable `KCLM-` fact.

This was proven, not argued. A discovery agent built a throwaway registry root from the repo's real
schemas, real `config/knowledge-policy.json`, real instructions and real keyword taxonomy, then ran
the real code: **5 claims on 1 shared receipt, all promoted to `verified` rev 2**, rendered into
`business-processes.md` / `object-descriptions.md` / `glossary.md` / `feature-map.md`,
`verify-citations` → `ok`, BM25 `--search` ranking them, and `propose --refresh-verified` →
rev 3 → rev 4 for re-attestation.

**Zero schema, policy or role change is needed.** What *is* needed is one small executor.

### Why an executor is unavoidable

Verified by running the real guard in this repo:

```
knowledge-curator     python -c "import hashlib"   -> False
knowledge-curator     shasum -a 256 f              -> False
knowledge-curator     sha256sum f                  -> False
knowledge-curator     date -u                      -> False
knowledge-curator     …knowledge_registry.py propose      -> True
knowledge-curator     …knowledge_registry.py approve-claim -> True
solution-designer     …knowledge_registry.py propose      -> False
```

No allowlisted script emits a sha256 or a stable id over arbitrary text
(`copilot_role_guard.py:905-914`, `:958-998`). **Without a new subcommand the authoring agent must
invent 64 hex characters, two ids and three timestamps** — the exact fabrication this lane exists to
prevent. Every design that skipped this was silently requiring it.

**Cost:** one new subcommand + three guard entries + one pinned-test edit + one skill + one prompt
mode + two fixtures + one contract test + four CI count moves.

## The unit of attestation

**One attested claim = one (subject, predicate) pair, asserted by one named accountable role, backed
by one session receipt, promoted by one human click.**

This granularity is forced, not chosen. `reconciliation_key = (canonical(subject), predicate,
canonical(scope))` (`knowledge_registry.py:1949`). With P5's scope uniformly all-null the key
collapses to `(subject, predicate)`, so the store holds **exactly one approved meaning per subject
per predicate, globally**. A second one with a different value is a store-wide fatal contradiction
that `validate_all` raises on (`:787-802`) — which then blocks human approval of *every unrelated
change record*, because every `require_current=True` check runs `validate_all` over the whole store
first (`:845-846`).

That invariant is the feature: *"what is this for"* should have one answer at a time, and a genuine
disagreement must surface as a declared `contradicts` pair, not as two coexisting truths. It is also
why the predicate vocabulary is closed rather than stylistic.

Not one claim per feature: a feature with a purpose, a process and a term needs three claims (two
share the subject, differing only by predicate) — verified, both promote cleanly. And not one receipt
per claim: the receipt is the **act** of attestation (one paragraph, one moment, one person), which
is what keeps `independenceKey` honest.

## Decisions — all with a recommended answer

### D1. `contentDigest` preimage — **ADOPT**

```
"sha256:" + sha256(json.dumps(
    {"attestedAt": observedAt, "attestor": collector.name,
     "sourceLocator": sourceLocator, "statement": summary},
    sort_keys=True, separators=(",",":"), ensure_ascii=False
).encode("utf-8")).hexdigest()
```

`grep -n contentDigest scripts/knowledge_registry.py` returns **zero hits** — the registry never
recomputes it, and `tests/test_knowledge_contract.py:522` promotes a claim whose digest is the
literal `sha256:ccc…`. All four preimage fields are stored verbatim in the receipt, so the digest is
**recomputable from the committed file alone** — the only integrity this field can have. Digesting a
side-car notes file would be wrong: `.cache/knowledge-proposals/` is gitignored, so the preimage
would vanish.

### D2. NEW `knowledge_registry.py mint-attestation` — **BUILD IT IN PHASE 1**

```
mint-attestation --statement-file <path> --attestor <key> --attestor-role <text>
                 --locator-handle <handle> --subject <kind:identity> --claim-type <type>
                 [--feature <slug>] [--redaction <text>]…
```

Writes both draft YAMLs into `.cache/knowledge-proposals/` and prints the ids and digest. It
collapses seven other decisions into code: it stamps `assurance: reported`, `completeness
{complete,false,false,[]}`, all-null scope, `keywords: []`, `status: proposed`, `revision: 1`,
`reviewBy = observedAt + 350d`, the derived predicate — and it **refuses a claimType whose
`allowedEvidenceTypes` lacks `human-sme-attestation`**, the pre-check `propose` never performs
(policy is read only inside `evaluate_verify_review`, `:1550-1610`).

### D3. One session receipt backs N claims — **ADOPT**

Every claim in a session carries the same `KEVD-…`; `propose` runs once per claim with the same
`--evidence-file`. `write_evidence_immutable` no-ops on a byte-identical resubmission (`:1351-1363`),
so re-passing is free. Verified: five sequential proposes left exactly one file in
`.ai/knowledge/evidence/`.

### D4. `independenceKey` is mandatory and equals the attestor key — **ADOPT**

`evaluate_verify_review` counts `{r.get("independenceKey", r["evidenceId"]) for r in evidence_records}`
(`:1606`), and `.ai/templates/knowledge-entry.md:129` actively tells authors to *omit* the field — so
independence is **fail-open**: four receipts from one person would count as four sources. Latent
today (every policy sits at `minimumIndependentEvidence: 1`) but the discipline must land before the
minimum is ever raised. `mint-attestation` writes it from `--attestor`, so it cannot be forgotten.

### D5. Closed predicate vocabulary, one per claimType — **ADOPT**

| claimType | predicate |
|---|---|
| `business-meaning` | `serves-business-purpose` |
| `business-process` | `supports-business-process` |
| `glossary` | `means-in-business-language` |

The predicate is the only axis left in `reconciliation_key` once scope is all-null. A free-form
predicate makes two SMEs asserting incompatible meanings about one subject land as `parallel-scope`:
both verified, both effective, and the contradictory-verified check never fires. **That is a
silent-wrong-answer mode, not a loud one.** The flag is `--claim-type`; the predicate is derived,
never passed.

### D6. `assertion.value` = `{description, attestedBy, attestorRole, asOf}`, description ≤ 400 chars — **ADOPT**

`claim_reference_from_result` (`work_record.py:509-521`) deep-copies `assertion` into the frozen
11-field claimRef stored in the change record and every handoff, and **never copies the evidence
record** — so *who attested* and *as of when* only travel with a citation if they are inside the
value. Separately, `value.description` is the only prose that reaches `query --text`, the BM25 corpus
and `descriptionExcerpt`; a bare-string value gets `statement` only, and `statement` renders in no
domain view.

Cost accepted with eyes open: `structured_fact` flattens the whole canonical JSON into one table
cell. The 400-char cap keeps that survivable. Citation payload beats table aesthetics.

### D7. `sourceLocator` = `sme://<attestorKey>/<handle>?attested=<YYYY-MM-DD>` — **ADOPT, default `session`**

`handle` ∈ {`ado-<workItemId>`, `wiki-<slug>`, `session`}. `session` **requires** the limitation
*"Only this receipt records the attestation; re-attestation means re-asking `<attestorKey>`."*

The field has no schema pattern and is dereferenced by nothing, so the skill text is the only
enforcement — same status as the prose-only `soql://` scheme. The honesty lives in `session`, not in
the URL. Note: `knowledge-curator`'s tools are exactly `['read','search','edit/editFiles',
'execute/runInTerminal']` — no ADO, no fetch — so under the hosting role an `ado-` handle can **never**
be verified by the agent. Accept `ado-<id>` only when the human typed it.

### D8. Self-attestation is DISCLOSED, never gated — **ADOPT disclosure only**

`knowledge.chatReviewer` is a human **full name**; the attestor key is a **role slug**. A slug cannot
be compared to a full name, so any "stop if chatReviewer names the attestor" rule is mechanically
inoperable. For a one-consultant engagement they *are* the same person and a gate would make the lane
unusable. The claim carries: *"Self-attested and self-approved in a single-consultant engagement; no
second party corroborated it."* **Do not describe this lane as verified provenance anywhere.**

## Authoring flow

1. Human runs `/curate-knowledge attest project-navigation` and pastes their paragraph — or points at
   a Feature Entry whose `## Purpose` they wrote in the P1 `from-notes` flow. No entry with that slug
   is fine; the tag is advisory.
2. Agent persists the paste **verbatim** to `.cache/knowledge-proposals/<slug>.attestation.notes.md`
   — the only writable prefix for both knowledge roles (`copilot_role_guard.py:24-30`).
3. Agent **splits the paste into three buckets** — this is the entire intellectual content of the lane:
   - **(a) attestable** — why it exists, what it is for, what business step it serves, what a
     business word means;
   - **(b) technical, refused** — which component implements it, which page opens which page, what
     is package-owned, what happens at runtime;
   - **(c) Feature Entry prose** — navigation path, screen names, UI wayfinding.
4. Agent asks **exactly two questions** in one `askQuestions` call:
   *Q1: whose accountable role is this — a role key like `sme-project-delivery-lead`, not a login?*
   *Q2: if someone re-asks this in a year, what do they open — an ADO id, a wiki slug, or nobody but
   the role holder?* Everything else is computed.
5. **One confirmation screen, then stop:** the exact sanitized text that becomes `summary` with its
   char count; the three-bucket split table so the author sees which of their own sentences become
   citable and which are refused; one line per proposed claim. Nothing is written until answered.
6. `mint-attestation` once per claim, reusing the same statement file. First call writes the receipt;
   later calls detect the identical digest, reuse the `KEVD-` id, and write only the claim draft.
7. **What the agent still must not do:** rewrite or paraphrase the author's words (sanitize by
   *removal* only, and name every removed surface in `--redaction`); invent an attestor key from git
   config or the repo owner; pass `ado-<id>` for a work item it did not see; set
   `enumerationComplete`/`permissionsProven` true; phrase any assertion as an absence; mint anything
   from bucket (b).
8. `reconcile --claim-file` per claim. `duplicate` → stop. `conflict` → declare exactly those ids,
   sorted, in `contradicts`, or stop. Once declared **neither** claim is effective — the correct
   representation of two SMEs disagreeing.
9. `propose … --expected-revision 0` per claim, then `render-indexes` **once** — `propose` never
   re-renders and `harness-ci.yml:73-74` runs `render-indexes --check` as a hard gate.
10. Agent returns `EVIDENCE COLLECTED` or `INCOMPLETE — NEEDS HUMAN` and **stops**. Its report names
    the attestor key and role, the locator, the digest and its recompute recipe, every claimId with
    type/subject/predicate, the reconciliation class per claim, the limitations, **every sentence it
    refused as technical and where that fact must come from instead**, and the exact per-claim
    `approve-claim` command. It never promotes and never calls its own output `verified`.

## Worked evidence receipt

Canonical home after propose:
`.ai/knowledge/evidence/KEVD-PROJECT-NAVIGATION-ATTESTATION-010E4B41AE.yaml`

Verified schema-valid under `Draft202012Validator` + `scripts.schema_format.FORMAT_CHECKER` (0 errors,
every `allOf` conditional) and accepted by the real registry.

```yaml
schemaVersion: 3
evidenceId: KEVD-PROJECT-NAVIGATION-ATTESTATION-010E4B41AE
  # stable_id("KEVD", "project-navigation-attestation", f"sme-{contentDigest}").
  # Digest in the discriminator: new words -> new digest -> new immutable id.
sourceType: human-sme-attestation
sourceLocator: sme://sme-project-delivery-lead/session?attested=2026-07-27
independenceKey: sme-project-delivery-lead      # keyed on the PERSON, not the receipt
authorityFor:                                   # must contain every claimType this receipt backs (:1580)
  - business-meaning
  - business-process
  - glossary
environment: not-applicable    # human-sme-attestation is absent from the org-bound conditional
orgKey: null                   # FORCED null when not-applicable (:589-593)
packageNamespace: null         # null on BOTH records even for managed-package subjects:
packageVersion: null           #   any non-null value must mirror the claim byte-for-byte (:600-618)
repositoryCommit: null         #   only metadata-repository evidence may carry a commit
observedAt: '2026-07-27T09:15:00Z'   # when the person spoke. Back-dating to buy freshness is THE
                                     #   fabrication mode: evidence age at review measures from here
retrievedAt: '2026-07-27T09:15:00Z'  # when it was written down; >= observedAt, <= reviewedAt
collector:
  kind: human                        # the enum value never written in this repo before P5
  name: sme-project-delivery-lead    # THE ATTESTOR; must equal independenceKey
  version: null
completeness:
  status: complete                   # "partial evidence cannot verify" is a hard review failure (:1584)
  enumerationComplete: false         # a person's word enumerates nothing
  permissionsProven: false           # a person's word proves no permission
  missingSegments: []                # schema forces maxItems 0 when complete — gaps go to claim.limitations
sensitivity: internal-sanitized
sanitization:
  rawDataCommitted: false            # schema const false — declarative, never inspected
  redactions:                        # the only real judgement here. NOTHING scans the text for secrets.
    - customer and account names
    - commercial values and volumes
    - personal identifiers of the attestor and of named colleagues
contentDigest: sha256:32dba22824c34e58bbfc82055ff895812adfbe6e4c5ca2b45bb4b8c0fde01a3f
  # over canonical JSON of {attestedAt, attestor, sourceLocator, statement} — all stored above,
  # so it recomputes from THIS FILE ALONE. Verified to reproduce.
summary: >-                          # AUTHOR'S OWN WORDS, verbatim, sanitized only by removal.
  # Folded `>-`: single newlines collapse to spaces at load, so re-wrapping preserves the digested
  # string. A literal `|-` block would NOT survive re-wrapping — mint-attestation writes folded.
  Project__c is where we run a stone-supply project end to end. The Project navigation on the
  Project record page is the planner's daily entry point: from a project they open the allocation
  screen, work through the batches that belong to that project, and confirm the result against the
  stone record. We built it because planners were reconciling allocations in spreadsheets and
  losing the link back to the project. Kamien__c is the stone itself - a physical block we hold in
  the yard - and an allocation is only finished when a batch is confirmed against one. The
  navigation exists so that a planner never has to leave the project to complete an allocation.
```

**Not expressible**, which is why accountable scope has to hide inside `collector.name` and `summary`:
the schema has no field for the attestor's role, the accountable scope, the question asked, or the
interview date.

## Worked claim

Canonical home: `.ai/knowledge/claims/KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105.yaml`

Verified end to end: `reconcile` → `new`; `propose` → `proposed` rev 1; `approve-claim` → `verified`
rev 2, `KREV-…-R1-CHAT-VERIFY`; `verify-citations` → `{ok:1}`; rendered into `business-processes.md`
and `feature-map.md`.

```yaml
schemaVersion: 3
claimId: KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105
  # stable_id("KCLM", "Feature:project-navigation", "business-meaning|serves-business-purpose")
  # — a pure function of the reconciliation-relevant parts, so re-attestation lands on the SAME id,
  # which is what --refresh-verified needs.
revision: 1                            # always 1 on a new proposal, paired with --expected-revision 0
domain: business-processes             # author-chosen, NEVER validated against claimType
claimType: business-meaning
subject:
  kind: process                        # no `feature` kind exists in the enum; `process` has zero
  identity: Feature:project-navigation #   producers repo-wide. subject.identity is a free 1-255 string
                                       #   with NO referential integrity — which is exactly what lets a
                                       #   managed-package surface be a subject at all.
assertion:
  predicate: serves-business-purpose    # CLOSED vocabulary. This string is IDENTITY, not prose.
  value:
    description: >-                     # <=400 chars; the only prose reaching query --text / BM25
      The Project navigation exists so that a planner can complete a stone allocation without
      leaving the project record. Before it, allocations were reconciled in spreadsheets and the
      link back to the project was lost.
    attestedBy: sme-project-delivery-lead
    attestorRole: Project delivery lead  # duplicated from the receipt ON PURPOSE — the frozen claimRef
    asOf: '2026-07-27'                   #   copies `assertion`, never the evidence record
statement: >-
  Attested by sme-project-delivery-lead on 2026-07-27: the Project navigation exists so a planner
  can complete a stone allocation without leaving the project record.
status: proposed                       # the only status a model may write
assurance: reported                    # FIXED. The schema admits observed|corroborated|reported and NO
                                       #   code binds assurance to sourceType — `observed` would validate
                                       #   and lie. Pinned by mint-attestation and the contract test.
scope:
  environment: not-applicable
  orgKey: null
  packageNamespace: null
  packageVersion: null
  repositoryCommit: null
evidenceRefs:
  - KEVD-PROJECT-NAVIGATION-ATTESTATION-010E4B41AE   # the ONE session receipt, shared by all 5 claims
reviewRef: null                        # schema-forced null while proposed
observedAt: '2026-07-27T09:15:00Z'
verifiedAt: null
reviewBy: '2027-07-12T09:15:00Z'       # observedAt + 350d. Ceiling is 365; 350 leaves a 15-day buffer
                                       #   so a delayed approval cannot breach reviewBy <= reviewedAt+365.
                                       #   HARD expiry, not a warning: is_fresh gates effectiveness.
sensitivity: internal-sanitized
keywords: []                           # MUST be empty — the "## Terms" list in keyword-taxonomy.md holds
                                       #   only an HTML comment, and enforce_keyword_taxonomy refuses any
                                       #   unlisted term (:1316-1327)
candidateKeywords:                     # max 5; feeds keyword-report for human curation. Polish business
  - project navigation                 #   terms are preserved verbatim here.
  - stone allocation
feature:
  - project-navigation                 # the Feature Entry SLUG, matching FEATURE_SLUG_RE
limitations:                           # where every acknowledged gap goes
  - Attested business meaning only; establishes no technical fact about which components implement
    this, how it is reached, or what it does at runtime.
  - Only this receipt records the attestation; re-attestation means re-asking sme-project-delivery-lead.
  - Self-attested and self-approved in a single-consultant engagement; no second party corroborated it.
supersedes: []
supersededBy: null
contradicts: []                        # non-empty ONLY when reconcile reported an active conflict
```

**Omit `polarity`.** `polarity: negative` is storable on any claimType and immediately demands
`enumerationComplete` *and* `permissionsProven` true on every receipt (`:1594-1601`) — fabrication no
attestation can carry.

## Approval

**Blocking prerequisite, once per workstation.** `config/harness.local.json` has keys
`[$schema, ado, browser, cache, safety, salesforce, schemaVersion, workspace]` — **no `knowledge`
block**. `approve_claim` refuses every promotion by that exact key name (`:1738-1741`). Add
`{"knowledge": {"chatReviewer": "<the approving human>"}}`. The file is gitignored and validated by
preflight against `schemas/harness-config.schema.json`, whose `knowledge` object already requires
`chatReviewer`.

```bash
# --- agent (knowledge-curator) ---
python scripts/knowledge_registry.py mint-attestation \
  --statement-file .cache/knowledge-proposals/project-navigation.attestation.notes.md \
  --attestor sme-project-delivery-lead --attestor-role "Project delivery lead" \
  --locator-handle session \
  --subject process:Feature:project-navigation --claim-type business-meaning \
  --feature project-navigation \
  --redaction "customer and account names" --redaction "commercial values and volumes"

python scripts/knowledge_registry.py reconcile --claim-file <claim>
python scripts/knowledge_registry.py propose --claim-file <claim> --evidence-file <receipt> \
  --expected-revision 0            # no human click here — the safety hook traps only approve-claim
# ... repeat per claim, same --evidence-file
python scripts/knowledge_registry.py render-indexes
# agent STOPS and reports EVIDENCE COLLECTED

# --- human, ONE confirmation per attested claim ---
python scripts/knowledge_registry.py approve-claim \
  --claim-id KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105 --expected-revision 1 \
  --rationale "sme-project-delivery-lead attested the Project navigation purpose on 2026-07-27"
```

`copilot_safety_hook.py:774-787` matches `knowledge_registry.py` **and** `approve-claim` over the
de-quoted command and returns `ask`. **The allow click IS the review** — nothing cryptographic is
verified. `--expected-revision` is the *pre-promotion* revision. `approve-claim` mints the immutable
`KREV` itself and re-renders the indexes.

**Forbidden on this lane:** `approve-claim --claim-spec A:1 --claim-spec B:1` loops up to 25
approvals behind **one** dialog (`:2581-2600`) while each `auditReceipt.reference` is
`vscode-chat://approve-claim/<claimId>/r<rev>` — one click would certify statements the human never
read back. (`--manifest` is already closed: `manifestApproval.allowedClaimTypes` is pinned to
`component-inventory`.)

### Re-attestation, before `reviewBy`

`approve-claim` **cannot** promote a `stale` claim: it admits `{proposed, stale, contested}` at
`:1753` but hardcodes `reviewType: "promotion"` at `:1784`, which the review schema pins to
`reviewedStatus: "proposed"`. Both non-proposed branches are dead code. The route is:

```bash
mint-attestation --statement-file <NEW notes> …     # new digest -> new KEVD
propose --claim-file <same claimId, revision N+1> --evidence-file <NEW receipt> \
        --expected-revision N --refresh-verified
render-indexes
approve-claim --claim-id <same id> --expected-revision N+1
```

Verified: rev 2 → rev 3 proposed → rev 4 verified. Fail-safe by design — the claim leaves `verified`
the moment it is re-proposed, so every design citing it degrades from `ok` to a not-effective
**warning** (not invalid) until re-approval.

## Citing it

**Ordering trap first.** `bind-claim` refuses once `current_approval(record) is not None`
(`work_record.py:1950-1965`). An attested claim that does not exist at design time can **never** be
added to an approved record. Run the attestation session *before* design approval.

```bash
python scripts/knowledge_registry.py query --feature project-navigation        # -> 5 [measured]
python scripts/knowledge_registry.py query --search "stone allocation planner" # BM25 ranked #1
python scripts/knowledge_registry.py verify-citations \
  --claim-ref KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105:2                     # -> {ok:1}

python scripts/work_record.py bind-claim --record-id ADO-1-48213 \
  --expected-revision <N> --expected-record-hash <hash> --role solution-designer \
  --claim-id KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105
```

`bind-claim` resolves through `effective_knowledge_claim`: status exactly `verified` **and**
`verifiedAt <= now < reviewBy` **and** `contradicts` empty **and** `supersededBy` null **and** no
conflicting scope. It re-hashes the file, then freezes the 11-field claimRef — the description,
`attestedBy`, `attestorRole` and `asOf` all travel there — and recomputes `groundingHash`. Revision
has schema minimum 2, so **only a promoted claim is bindable**.

Then human approval re-runs `validate_claim_refs(require_current=True)`: the claim must *still* be
verified and unexpired. `_assert_not_shadowed` is a no-op here — `business-meaning` is absent from
`ENTRY_HOME_CLAIM_TYPES`, so an approved `Project__c` entry can never shadow the attested meaning.

**What citation buys, exactly three things:** (a) a frozen content snapshot including the attested
prose and the attribution, copied into the change record and every handoff and folded into
`groundingHash`; (b) re-resolution at exactly two moments — human design approval and the
SAFE/complete state; (c) membership in a set a human signed off on.

**What it does not buy:** any link between a *sentence* and a claim. `groundingHash` binds the *set*
of claimRefs, `record.design.sha256` binds the prose, and nothing correlates them. Inline citation is
a text convention enforced by no code. The harness can prove a verified, fresh, uncontested,
human-approved claim carrying that assertion was bound to this record. It cannot prove the sentence
came from it, and it cannot detect a design sentence with no backing claim at all.

**Two coupled costs:** every `require_current=True` check runs `validate_all` over the whole store
first, so one malformed attested claim blocks human approval of every unrelated change record; and
`assert_fresh_environment_receipt` still demands a live verified sandbox org-identity receipt minutes
old, even for a documentation-only change grounded solely on attested meaning.

**Enabled, not enforced.** The SAFE gate requires only that `claimRefs` *or* `entryRefs` is non-empty
(`work_record.py:1409-1412`), and the only claimType ever *demanded* is `object-ownership`. Minting
an attested claim changes no verdict today; omitting one blocks nothing. If *"business meaning MUST
be citable"* is meant as **MUST BE CITED**, that predicate and its mirror at `:2670-2673` are the
single place it lands — a separate owner decision with real blast radius.

## Your scenario, end to end

One session, one receipt, **five claims** — all proposed and promoted to `verified` rev 2 against the
real registry. All carry `independenceKey: sme-project-delivery-lead`, all-null scope,
`assurance: reported`, `feature: [project-navigation]`.

| # | claimId | type / subject / predicate | what it is |
|---|---|---|---|
| 1 | `KCLM-FEATURE-PROJECT-NAVIGATION-46753B0105` | business-meaning / `process:Feature:project-navigation` / serves-business-purpose | **why** the feature exists — the claim a design binds |
| 2 | `KCLM-FEATURE-PROJECT-NAVIGATION-25433BDBB0` | business-process / same subject / supports-business-process | the business path. **This is what feeds test-case creation** — it names the acceptance-relevant sequence and the observable outcome in business terms |
| 3 | `KCLM-PROJECT-C-24AB0375AA` | business-meaning / `object:Project__c` / serves-business-purpose | coexists with any entry facts about the same object |
| 4 | `KCLM-KAMIEN-D1596AA663` | glossary / `term:Kamien` / means-in-business-language | the business **word**, not the API name |
| 5 | `KCLM-APEXPAGE-NPNAV-EXAMPLE-2681FE8DE4` | business-meaning / `surface:ApexPage:npnav__Example` / serves-business-purpose | **the payoff** |

Claims 1 and 2 share a subject with no collision because the predicate differs — precisely why the
vocabulary is closed.

**Claim 5 is the payoff.** `ApexPage` is absent from `knowledge_store.PROFILES`, so this surface can
*never* have a Knowledge Entry; and the component is not in force-app, so no `metadata-repository`
evidence can ever exist for it. **The claim registry is the only citable home its meaning will ever
have.** Its mandatory limitation: *"Does not establish that this page exists, how it is reached, or
what it renders; the component is not in force-app and no repository or org evidence backs it."*

### The managed-package half, honestly

P5 records the business **posture** toward the package (claim 5: this is the vendor-supplied screen
the planner works in; gaps here are vendor requests, not local builds). It records nothing technical
about it, and cannot:

| Your sentence | Where it actually has to come from |
|---|---|
| "the navigation is built in a managed package"; "X/Y/Z belong to the package" | `object-ownership` → `installed-package-record` / `org-describe`. The schema then **forces** a non-null `packageNamespace` *and* `packageVersion` that the receipt must mirror byte-for-byte. An SME cannot attest it. Route: `/investigate-object`. The managed **objects** are describable from an org even though the VF/FlexiPage **components** are not in force-app. |
| "the package is installed" | `package-installation` → `installed-package-record` |
| "clicking the navigation opens Example"; "its buttons open the second VF page" | `runtime-behavior` → controlled-sandbox-test / org-soql-sample / vendor-documentation / vendor-support-case. **`human-sme-attestation` is not among them.** A person's word about what a button does is not evidence. The honest reframe is claim 2's business step, never the mechanism. |
| "what the Example page does" as a component description | `component-description` and `component-inventory` admit `metadata-repository` **only**, which additionally requires a `repositoryCommit` the packaged component does not have. **There is no lane, ever, for a hand-written technical description of a managed-package component through this registry.** This is the hard ceiling of P5 and the skill must state it at the confirmation screen. |
| "reached through a Lightning Page" | No entry profile, not in force-app, and routing is not something an SME can establish. Its *business role* could be a `surface` business-meaning claim; its configuration cannot be attested at all. In practice: Feature Entry body. |

**Knowledge Entries** (unchanged lane): `Project__c`, `Kamien__c` and their fields, if and only if
they are in force-app. Their source-derived facts must never be attested. Nothing links a claim to an
entry — an envelope wanting both uses `claimRefs` + `entryRefs`.

**Feature Entry prose** (P1, never citable): the UI wayfinding. `Feature:` is excluded from every
entryRef by a `(?!Feature:)` negative lookahead in three schemas. The Feature Entry says what the
feature **is** and where its boundary runs; the attested claims say what it is **for**, and only
those are citable.

Measured after the five passes: `validate` → `{claims 5, evidence 1, reviews 5, rules 50}`;
`query --feature project-navigation` → 5; `query --text kamien` → 1; six KCLM rows in
`business-processes.md`; the glossary claim in `glossary.md`; `## project-navigation` in
`feature-map.md`.

## The feature bridge

Two joins, both convention:

1. `feature: ["project-navigation"]` — the Feature Entry **slug**. Three read-only consumers:
   `query --feature`, the claims-index rows, and the `## <feature>` grouping in
   `.ai/knowledge/feature-map.md`. Invisible to `work_record.py` (the substring "feature" does not
   occur in that 2960-line file), to `groundingHash`, to every SAFE gate, and to the BM25 corpus.
2. `subject.identity: "Feature:project-navigation"` on the feature-level claims, so
   `query --subject-identity` finds them and a reader of `business-processes.md` sees the join.

**Nothing validates either.** `knowledge_registry.py` never opens `.ai/knowledge/features/`.

**A live convention collision P5 must pin:** `force_app_knowledge.feature_draft` writes the feature
**display name** into the tag (`:6367-6369`) while `knowledge_store` keys on the lowercase-hyphen
**slug**. Two producers, two formats, no detector — `feature-map.md` would grow two headings for one
feature the first time both run. P5 pins the slug and `mint-attestation` validates `--feature`
against `FEATURE_SLUG_RE`.

**Does the dossier surface it? No — and the gap is inverted.** `run_feature_dossier` reads exactly
two sources: the entry search index and the Feature Entry file; `knowledge_search.py` has never
imported `knowledge_registry`. So after Phase 1 the attested *why* is citable and queryable but
**invisible in the human-facing dossier**, while the Feature Entry's own `## Purpose` is visible and
uncitable by construction. P5.3 closes this.

## Phases

### P5.1 — the lane, shippable alone (L)

Satisfies the owner decision on its own: business meaning becomes citable.

- **NEW** `mint-attestation` in `scripts/knowledge_registry.py` (see D2).
- **NEW** guard wiring in `copilot_role_guard.py`: `mint-attestation` in
  `KNOWLEDGE_COMMAND_FLAGS` with its flag frozenset, added to the two mutation-role grants, plus a
  handler branch requiring `--statement-file` / `--attestor` / `--subject` / `--claim-type`,
  containment of every path under `.cache/knowledge-proposals/`, and regex-pinned `--attestor` and
  `--feature`.
- **NEW** `.github/skills/attest-business-meaning/SKILL.md` — authority basis, the three-bucket
  split, the two questions, the confirmation screen, the closed predicates, the subject spellings,
  the command sequence, Prohibitions, Return contract.
- `attest <slug>` mode paragraph + `argument-hint` on `curate-knowledge.prompt.md`, and
  `vscode/askQuestions` added to its `tools` array.
- `.github/agents/knowledge-curator.agent.md`: skill in the Load list, argument-hint, **and the
  charter amendment** (see Do not do).
- **NEW** fixtures `evals/fixtures/knowledge-evidence.attestation.yaml` and
  `knowledge-claim.attested.yaml` — the repo's first committed `human-sme-attestation` records, with
  a real recomputable digest.
- **NEW** `tests/test_attestation_lane.py`.
- `config/harness.local.json` `knowledge.chatReviewer` documented as a setup prerequisite.

### P5.2 — make the digest a machine-checked field (M)

- The registry recomputes `contentDigest` for every `human-sme-attestation` receipt inside `propose`
  and `validate_all`, and refuses a mismatch. **This would be the first machine-checked digest
  anywhere in the claim lane.** Zero new flags, so the guard/parser contract is untouched.
- `approve-claim` refuses a `--claim-spec` batch containing any claim whose evidence includes an
  attestation receipt: one human click per attested statement, always.
- Propose-time refusal for `assurance != reported`, wrong `completeness`, `polarity: negative`, or a
  predicate outside the closed vocabulary.

### P5.3 — the feature bridge (M)

- `feature-check` warns when a `claim.feature` tag matches no Feature Entry slug, and when an
  approved Feature Entry has no effective attested meaning (already a CI gate at
  `validate_harness.py:1016`).
- `force_app_knowledge.py:6369` writes the slug, not the display name.
- **Resolve the `output/feature-dossiers/<slug>.md` collision first** — `run_feature_dossier` and
  `render_dossier` write the same path with different content models; whichever ran last silently
  replaces the other.
- A *"What this feature is for (attested)"* section in `run_feature_dossier`, each row printing its
  KCLM id as the citable handle, preserving the file's "generated view, never citable" framing.

### P5.4 — expiry and authority cleanup (M)

- A `reattest <slug>` sub-mode driving mint → `propose --refresh-verified` → approve.
- Fix or formally document the dead `stale`/`contested` branches in `approve_claim`.
- `stale-report` surfaces attested claims separately **with their attestor key**, so the human knows
  who to go back to before `reviewBy` lapses.
- Resolve the `integration` divergence: policy admits `human-sme-attestation` while
  `source-authority.md:27` forbids technical configuration without corroboration. **Recommendation:
  remove it from `integration.allowedEvidenceTypes`** — the business-ownership half of an integration
  is a `business-meaning` claim about the integration subject.
- Wire the declared `invalidationTriggers` (`business-owner-change`) or delete them: nothing computes
  or fires a trigger today and `approve_claim` hardcodes `triggeredInvalidators: []`.

## CI checklist (P5.1)

- `scripts/validate_harness.py:25` — `EXPECTED_COUNTS` skills **25 → 26**. Prompts stays 24 (the lane
  is a *mode*, not a new prompt file), which also leaves the slash-command identity assertion at
  `:382-387` untouched.
- `tests/test_repo_map.py:62` — `assertEqual(25, len(first["skills"]))` → 26. Lines 63 (prompts) and
  64 (contracts) do **not** move.
- `scripts/render_repo_map.py:31` — `WORD_BUDGET` **875 → 890**, and record the raise in the existing
  history comment at `:29-31` per its own convention. Measured headroom: `wordCount` is 872, i.e.
  **3 words**; one skill line plus the curator's Loads entry costs ~9-10.
- `scripts/validate_harness.py:1087` — the hand-copied duplicate `<= 875` → 890. **Missing this half
  is the standard trip.**
- Re-run `python scripts/render_repo_map.py render` and commit both `.ai/repo-map.md` and `.json`.
- **NEW** `tests/test_guard_parser_contract.py:207-232` — `test_role_grants_are_pinned` asserts
  `{"propose","approve-claim"} == commands - _KNOWLEDGE_READ_COMMANDS`; it becomes three-valued. The
  test's own comment names this as a deliberate reviewed change. Its sibling assertion is satisfied
  automatically once the flag allowlist entry exists.
- **NEW** the guard/parser mirror is enforced **both ways** by `contract()` (`:62-90`): every
  `mint-attestation` argparse flag must appear in the guard frozenset or in
  `INTENTIONALLY_EXCLUDED_FLAGS` with a rationale.
- **NEW** `tests/test_attestation_lane.py` — recompute `contentDigest` over both fixtures and over
  every `human-sme-attestation` receipt in `.ai/knowledge/evidence/`; assert `collector.kind ==
  "human"` and `collector.name == independenceKey`; assert `completeness == {complete,false,false,[]}`;
  assert `authorityFor ⊆ {business-meaning, business-process, glossary}`; assert the `sme://` locator
  shape; and per backed claim assert `assurance == "reported"`, `polarity` absent, `keywords == []`,
  all-null scope, predicate in the closed vocabulary, `reviewBy == observedAt + 350d`, and `feature`
  matching `FEATURE_SLUG_RE`.
- `curate-knowledge.prompt.md` frontmatter `tools` must gain `vscode/askQuestions` (in
  `ALLOWED_TOOLS` at `validate_harness.py:54`; `investigate-config-records.prompt.md:6` is the
  precedent).
- The new SKILL.md needs `name` == folder, `description` 1-1024, `user-invocable: false`, the literal
  phrase **"shared execution contract"** in the body, `python ` prefix + forward slashes on every
  backticked guarded command, and every relative link resolving on disk.
- `evals/agent-scenarios.yaml` — two scenarios with unique kebab-case ids:
  `attestation-without-named-accountable-role` (expect `INCOMPLETE — NEEDS HUMAN`) and
  `attested-claim-cannot-carry-technical-configuration` (the agent refuses the runtime/description
  sentences and names which it dropped).
- Reserved-token scan: never use `HarnessEngagement`, `HarnessInvoice`, `HarnessBilling`,
  `ExampleManagedObject__c` (`validate_harness.py:36-41`). `Project__c`, `Kamien__c`,
  `ApexPage:npnav__Example` and `Feature:project-navigation` are all clear.
- **Do not** add the new skill to `docs/knowledge-master-plan-2026-07-25.md` §7 —
  `check_knowledge_consumer_sets` would then oblige Set A/Set B membership this lane does not have.
  Its input is a human, not the index.
- No schema change, no policy change, no new writable path, no new role, no `work_record.py` change
  in P5.1. `tests/test_knowledge_contract.py` needs no edit.

## Do not do

- **Do not** let the authoring agent write `contentDigest`, either `stable_id`, or any timestamp by
  hand. Verified against the real guard: `python -c`, `shasum`, `sha256sum`, `certutil`,
  `git hash-object` and `date` are **all denied** for both knowledge roles. Ship `mint-attestation`
  first, or the lane's flagship integrity property is a 64-character invention.
- **Do not** batch attested claims through `approve-claim --claim-spec`.
- **Do not** ship the separation-of-duties comparison — a role slug cannot be compared to a full name.
- **Do not** create a new prompt file. Prompts are pinned at 24 in two independent assertions plus
  `test_repo_map.py:63`, and the atlas has 3 words of headroom.
- **Do not** leave the `knowledge-curator` charter as written. Its description says *"Maintains
  governed Knowledge from repository source"*, body line 16 says *"from repository source alone"*,
  step 4 says *"Describe only what the source shows"*, and stop-rule 6 says *"a description you
  cannot ground in source — pause and report, never improvise"*. **A compliant curator must refuse
  this task.** Amend all four with an explicit carve-out — this is a charter change, not bookkeeping.
  (Harmless to the word budget: `one_liner` truncates to 5 words and the first 5 are unchanged.)
- **Do not** set `polarity: negative` or phrase any attested assertion as an absence.
- **Do not** put package identity in `scope`. `verify_evidence_scope` requires every non-null package
  field to be byte-identical on both records, so scoping an attested claim to a namespace forces a
  namespace onto a human interview. Package identity belongs in `subject.identity`. (Asymmetry to
  note: `object-ownership: package-owned` claims are schema-**forced** to carry a non-null namespace
  and version, so they cannot follow the P5 all-null rule.)
- **Do not** write `summary` as a literal `|-` block — folding (`>-`) survives re-wrapping, a literal
  block does not, and any reformatting silently breaks the digest.
- **Do not** attest a technical fact, and do not let the agent quietly drop the refusal. Every
  refused sentence must be named back to the author with the lane it actually needs.
- **Do not** design any P5 guarantee on `verify-citations`. It is advisory and unwired: CI runs
  `validate`, `render-indexes --check` and `stale-report`, never `verify-citations`.
- **Do not** offer `Feature:<slug>` as an entryRef anywhere — three schemas reject it with a
  `(?!Feature:)` negative lookahead, deliberately.
- **Do not** widen `KNOWLEDGE_MUTATION_ROLES`.

## Open questions

1. **Attestor key format and registry.** `sme-project-delivery-lead` is a role slug with no
   directory, allowlist or config anywhere. Without a pinned list, two sessions key the same person
   differently and `independenceKey` silently degrades. Cheapest fix: an `attestors` array in
   `config/harness.local.json` (gitignored, per-workstation) that `mint-attestation` validates
   against — which needs a `schemas/harness-config.schema.json` edit that preflight enforces.
2. Should `mint-attestation` **warn** when the statement contains a leak signature (15/18-char
   Salesforce ids, e-mail addresses, `://` hosts, long entropy runs)?
   `force_app_knowledge.sanitize_literal:335-360` already implements exactly those regexes and never
   touches receipts. Reusing it as a warning — never a rewrite, the words must stay verbatim — is
   nearly free and is the only inspection this lane would ever have.
3. **Does "MUST be citable" mean "MUST BE CITED"?** Today the SAFE gate accepts any one claim or
   entry, so an attested claim changes no verdict. Making `business-meaning` *required* lands in one
   predicate and its mirror — with real blast radius on every existing record.
4. `assertion.value` renders as one flattened table cell in the domain views. Is the 400-char cap the
   right trade, or should the views special-case an attested claim the way `claims_index_row` already
   special-cases `value.description` into `descriptionExcerpt`?
5. `business-meaning` about a **UI surface** has no natural domain — `DOMAIN_VIEWS` has no
   feature/surface bucket. Widen the view descriptions, or file surface claims under
   `current-implementation`?
6. Resolve `integration` by removing `human-sme-attestation` (recommended) or by raising its
   `minimumIndependentEvidence` and requiring a technical co-receipt?
7. Should `mint-attestation` be reachable by `config-investigator` at all, or only by
   `knowledge-curator`? The curator has no org surface (correct for a lane whose input is a person)
   but also **no work-record surface** — `work_record.py append-evidence` is available to the
   investigator and not to the curator. If an attestation must ever attach to a governed work record,
   only the investigator can do it.
8. Should re-attestation require genuinely **new** words? Today the digest is folded into the
   `evidenceId`, so identical words produce the identical `KEVD` and `write_evidence_immutable`
   no-ops — the refresh would reuse the year-old receipt and its year-old `observedAt`, which then
   fails the `reviewedAt − observedAt <= maxReviewAgeDays` check. Either `mint-attestation` refuses
   an unchanged statement on refresh, or the preimage must include the re-attestation date.

## Method note

Produced by a 12-agent workflow (5 parallel readers → 3 independent specs under different priors →
3 adversarial critics → synthesis). One reader built a throwaway registry root from the repo's real
schemas and config and ran the full lane end to end; two critics independently validated the worked
YAML with `jsonschema` against the real schemas (0 errors each). The guard denials in the Headline
were re-verified by hand in this session.
