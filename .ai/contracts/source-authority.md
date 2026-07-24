# Knowledge Source Authority

Status: normative
Schema version: 2

Source authority depends on the claim being made. There is no universal ranking, and multiple
records derived from the same underlying source are not independent corroboration.

Approved one-file Knowledge Entries (`entryRef`, SAFE-CLAIM-001 v2, owner-approved
2026-07-24) carry `metadata-repository` authority only: they establish the intended
repository-source state of a force-app artifact (positive presence, source-exact,
fully-covered sections) and never deployed state, runtime behavior, business meaning,
package limitations, vendor guarantees, or absence/completeness beyond the machine-emitted
enumeration — see `docs/knowledge-one-file-contract.md` §8.

| Evidence source type | Can establish | Cannot establish alone |
|---|---|---|
| `org-describe` | Accessible object/field/relation schema at observation time | Business meaning, closed package internals, or absence when permissions are incomplete |
| `org-tooling-enumeration` | Accessible automation/configuration inventory when pagination and permissions are complete | Invisible package internals or vendor guarantees |
| `org-soql-sample` | Values of the bounded records observed | Universal behavior, absence, or field semantics |
| `metadata-repository` | Customer-owned intended metadata at an exact commit | Deployed org state without deployment reconciliation |
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

## Claim-type guidance

- Schema, ownership, relation, and automation claims require a complete technical source in the
  matching org scope. Repository metadata is corroborating evidence unless deployed state is also
  reconciled.
- Runtime-behavior claims require a controlled test or multiple applicable observations. One SOQL
  sample remains an observation, not a universal fact.
- Package limitations require vendor evidence tied to package version, or remain a scoped observed
  behavior rather than a vendor rule.
- Business meaning and process claims require a named accountable SME or approved artifact;
  technical metadata cannot establish semantics by itself.
- Negative claims require complete enumeration, permission proof, and the shorter negative-claim
  freshness policy.
