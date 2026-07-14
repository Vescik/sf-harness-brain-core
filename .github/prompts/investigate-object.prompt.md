---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence for one Salesforce object or component and draft a proposed Knowledge claim.
argument-hint: "objectApiName=<API name> [recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_configured_orgs']
---

Use the [investigate-object skill](../skills/investigate-object/SKILL.md).

Require exactly one `objectApiName` (ask once with `#tool:vscode/askQuestions` if missing). The
name must be on the configured review allowlist; evidence stays bounded, sanitized, and
dual-source reconciled through the guarded review tools and `python scripts/salesforce_read.py`.

The outcome is a schema-valid PROPOSED claim with its immutable evidence — never a verified fact:
promotion needs a separate human chat approval. Report the claim ID, reconciliation status,
limitations, and any drift or contested findings. When the caller provided `recordId`, attach the
evidence references to that work record; otherwise the investigation is a standalone read.
