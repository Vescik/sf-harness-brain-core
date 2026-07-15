---
name: feature-documentor
description: Document a feature end to end — crawl an anchor object's relations (lookups, reverse child relationships, junctions) and its automations and UI (flows, approval processes, apex, Lightning/Visualforce pages), draft feature-tagged proposed claims, and render a human-readable dossier. Reconcile against the live org when available; never self-verify.
user-invocable: false
---

# Document a feature

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[Knowledge lifecycle](../../../.ai/contracts/knowledge-lifecycle.md),
[source authority contract](../../../.ai/contracts/source-authority.md),
[inventory-force-app skill](../inventory-force-app/SKILL.md),
[propose-force-app-knowledge skill](../propose-force-app-knowledge/SKILL.md), and
[update-knowledge-base skill](../update-knowledge-base/SKILL.md).

## Entry gate

Require the `config-investigator` role, a feature name, and at least one anchor object API name.
Anchors that resolve to configured allowlisted objects may also be reconciled against the org; the
crawl itself reads only repository source. Require a complete current inventory and every `force-app`
file tracked and clean at the exact inventory commit. Stop on untracked/modified metadata,
source-tree drift, parser errors, or a changed `HEAD` — `metadata-repository` evidence cannot be
bound to a commit otherwise.

## Procedure

1. Run `python scripts/preflight.py --capability metadata`, then
   `python scripts/force_app_knowledge.py inventory`.
2. Crawl the boundary:
   `python scripts/force_app_knowledge.py feature-crawl --feature "<Feature>" --anchors <Object__c,Object__c> [--depth 1] [--hub <UtilityObject__c>]`.
   The crawl follows lookups and master-detail outward and reverse child relationships inward,
   flags junction objects, and collects the flows, approval processes, apex, LWC/Aura, Lightning
   pages, Visualforce pages, layouts, and other components that touch the boundary. Objects on the
   `--hub` stop-list stay relation endpoints but are never expanded.
3. **Present the boundary for confirmation.** Report the objects, outbound/inbound relations,
   junctions, and component counts from the crawl file, plus its stated limitations (FlexiPage,
   formula, and roll-up associations are not derivable from source; deployed org state is not yet
   reconciled). Do not draft or propose the whole set by default — let the human confirm or narrow
   the anchors/depth/hubs first.
4. Draft feature-tagged claims and the dossier:
   `python scripts/force_app_knowledge.py feature-draft --feature "<Feature>"`. This drafts schema-v3
   `proposed` claims for boundary components only — each carrying the `feature` tag — and renders
   `output/feature-dossiers/<slug>.md`. Drafts are not canonical or verified.
5. **Write the AI descriptions.** For every behavior-bearing draft (Flow, Apex, trigger, approval
   process, LWC/Aura) you intend to propose, read the component's actual source and replace the
   `<AGENT_...>` sentinel with 2–6 grounded sentences (purpose, entry conditions, key steps, what it
   reads or changes), exactly as [propose-force-app-knowledge](../propose-force-app-knowledge/SKILL.md)
   requires. Refine `candidateKeywords` (drafts arrive pre-seeded from the component's usage
   registry — keep the apt object/field-derived terms and add the visible business/feature terms).
   The registry rejects an unfilled sentinel at propose time.
6. **Optional live-org reconcile (deep discovery).** When a review org is configured, retrieve the
   deployed boundary artifacts to catch org-only components and drift:
   `python scripts/salesforce_read.py retrieve --org <alias> --metadata Flow:<name> --metadata ApexClass:<name> --metadata FlexiPage:<name> --metadata ApprovalProcess:<name>`
   (allowlisted types only, ≤25 components per call, `review_org_identity` gate first). Record
   disk-vs-org drift as claim limitations and in the dossier's Limitations section. Degrade
   gracefully to repository-only when no org is available and mark completeness partial.
7. Before selecting candidates, look up what the registry already knows so proposals never duplicate
   related Knowledge: `python scripts/knowledge_registry.py query --subject-identity <identity>` and
   `python scripts/knowledge_registry.py query --feature "<Feature>"`.
8. Only when the caller explicitly selects claim IDs, submit each through
   `python scripts/knowledge_registry.py propose ...`, then offer chat-approved promotion with
   `python scripts/knowledge_registry.py approve-claim --claim-id <id> --expected-revision <n>`. The
   safety hook stops each invocation for the human's confirmation; promotion re-renders the domain
   indexes and `feature-map.md`. Never edit canonical Knowledge directly.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, arbitrary SOQL/SOSL, an alias, a directory, a Tooling
  flag, or an unguarded Salesforce MCP tool.
- Never crawl without an anchor or expand an unbounded graph; use `--depth` and `--hub` to keep the
  feature boundary tight, and confirm it with the human before drafting.
- Never treat a source token, FlexiPage, or formula as a proven object relation beyond what the
  crawl derived, and never treat a missing component as proof of absence.
- Never publish the dossier to ADO, a wiki, or a production surface — it is a draft artifact only.
- Never call a proposed observation `confirmed` or `verified`; promotion is a separate human step.

## Return

Return `DRAFTED`, `PROPOSED`, or `BLOCKED`; the feature and its slug; the boundary summary (objects,
relations, junctions, component counts); the crawl and dossier paths; claim/evidence IDs and
revisions; org-reconcile drift; limitations; and the required human review before any promotion.
