# Knowledge Source Authority

Status: normative
Schema version: 2

Source authority depends on the assertion being made. There is no universal ranking, and
multiple records derived from the same underlying source are not independent corroboration.

Two authorities may support a positive intended-source assertion, and only these two.
**Approved one-file Knowledge Entries** (`entryRef`, SAFE-CLAIM-001, owner-approved 2026-07-24;
the sole governed Knowledge store since the claim registry retired, owner-approved 2026-08-03)
carry `metadata-repository` authority only: they establish the intended
repository-source state of a force-app artifact (positive presence, source-exact,
fully-covered sections) and never deployed state, runtime behavior, business meaning,
package limitations, vendor guarantees, or absence/completeness beyond the machine-emitted
enumeration — see `docs/knowledge-one-file-contract.md` §8.

The second authority is a **governed repository receipt** (`repository-receipt`, SAFE-CLAIM-001
v4, 2026-08-05). It exists because an empty Knowledge store is a normal starting state and a
blanket Knowledge prerequisite would block every first design. The receipt is authored by
`scripts/repository_evidence_adapter.py`, which resolves the entry with `ls-tree` at a full
commit SHA, accepts only regular blob modes, and reads the object by OID with `cat-file`. It
rejects symlinks, submodules, directories, absolute/drive/UNC paths, alternate-data-stream
syntax, traversal, option-like paths and short or ambiguous commits. Reading by object ID rather
than by working-tree path is what removes the read-versus-resolve race and makes the behaviour
identical on Windows and macOS.

What the fallback does **not** license: a model opening a file and reporting what it saw. That
is orientation and stays `UNVERIFIED` in both lanes. Absence and completeness claims stay
outside both lanes entirely.

| Evidence source type | Can establish | Cannot establish alone |
|---|---|---|
| `org-describe` | Accessible object/field/relation schema at observation time | Business meaning, closed package internals, or absence when permissions are incomplete |
| `org-tooling-enumeration` | Accessible automation/configuration inventory when pagination and permissions are complete | Invisible package internals or vendor guarantees |
| `org-soql-sample` | Values of the bounded records observed | Universal behavior, absence, or field semantics |
| `metadata-repository` | Customer-owned intended metadata at an exact commit | Deployed org state without deployment reconciliation |
| `repository-receipt` | Customer-owned intended source at an exact commit/blob OID/range, with coverage stated | Deployed org state, absence beyond the stated range, business meaning, or the current working tree when drift is reported |
| `installed-package-record` | Installed package identity and version | Package behavior or supported extension points |
| `vendor-documentation` | Documented package behavior for the stated versions | Current org configuration |
| `vendor-support-case` | Vendor-confirmed behavior for the case scope and stated versions | Broader behavior outside that scope |
| `salesforce-documentation` | Salesforce platform semantics for the cited release/version | Organization policy or managed-package behavior |
| `ado-approved-artifact` | Approved requirement, design, or business intent | Actual implementation or runtime behavior |
| `human-sme-attestation` | Business terminology or process meaning within the speaker's accountable scope | Technical configuration without technical corroboration |
| `controlled-sandbox-test` | Behavior under the recorded scenario, data, metadata, and package version | Universal behavior outside that fingerprint |

Model output and existing Knowledge are never evidence. Existing Knowledge may lead to relevant
evidence, but it cannot corroborate itself.

## Minimum provenance

Every evidence receipt records:

- source type and reproducible locator;
- an independence key shared by observations that come from the same underlying authority;
- non-production environment and configured org key when applicable;
- observation and retrieval timestamps;
- collector/tool name and version;
- source revision, package version, or repository commit when applicable;
- configurable package namespace as the primary managed-package identity (with an optional local
  package key/name only as an aid);
- completeness, pagination, permissions, and missing segments;
- sensitivity classification and redactions;
- a SHA-256 digest of the sanitized observation;
- a bounded summary that contains no credentials or unnecessary record data.

Only `public` and `internal-sanitized` evidence receipts may be committed. Confidential or
restricted raw data remains outside committed Knowledge and is referenced only by a sanitized
digest/locator that an authorized reviewer can reproduce.

## Assertion-type guidance

These bounds govern what an investigation report may assert and with how much confidence —
none of them makes an assertion citable Knowledge:

- Schema, ownership, relation, and automation assertions require a complete technical source in
  the matching org scope. Repository metadata is corroborating evidence unless deployed state is
  also reconciled.
- Runtime-behavior assertions require a controlled test or multiple applicable observations. One
  SOQL sample remains an observation, not a universal fact.
- Package limitations require vendor evidence tied to package version, or remain a scoped observed
  behavior rather than a vendor rule.
- Business meaning and process assertions require a named accountable SME or approved artifact;
  technical metadata cannot establish semantics by itself.
- Absence assertions require complete enumeration and permission proof, and expire fastest.
