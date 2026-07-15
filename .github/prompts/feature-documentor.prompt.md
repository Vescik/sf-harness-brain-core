---
name: feature-documentor
description: Document a Salesforce feature from anchor objects — discover its relations, automations, and UI, draft feature-tagged proposed claims, and render a reviewed dossier.
argument-hint: "feature=<name> anchors=<Object__c,Object__c> [depth=<n>] [hubs=<Object__c,...>] [claimIds=<ID,...>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Use the [feature-documentor skill](../skills/feature-documentor/SKILL.md).

Require a `feature` name and at least one `anchors` object API name; ask once if either is missing.
The crawl reads only tracked `force-app` source at a clean commit, so require a complete inventory
and clean tree first. Crawl the relation graph (outbound lookups/master-detail, reverse child
relationships, junctions) and the automations and UI (flows, approval processes, apex, Lightning and
Visualforce pages, layouts) touching the anchors, keep the boundary tight with `depth` and `hubs`,
and present it for confirmation before drafting.

The outcome is schema-valid `proposed` claims tagged with the feature plus a draft dossier under
`output/feature-dossiers/` — never verified facts: promotion needs a separate human chat approval,
and the dossier is never published to ADO or a production wiki from here. Reconcile against the live
org through the guarded `python scripts/salesforce_read.py retrieve` only when a review org is
configured. Report the boundary summary, crawl and dossier paths, drafted claim IDs, org drift,
limitations, and the required human review.
