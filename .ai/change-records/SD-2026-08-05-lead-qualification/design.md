# Solution Design — Automatyczna kwalifikacja i dystrybucja Leadów w Salesforce

Case: `SD-2026-08-05-lead-qualification`

## 1. Executive summary

The design introduces an automated lead-qualification and distribution process on the standard Salesforce Lead object. New Leads are scored, prioritised, routed to the correct sales queue or user, and tracked against an SLA. Sales Managers receive dashboards and reports; Administrators configure scoring, routing and SLA rules through Custom Metadata Types without code deployments.

## 2. Problem and measurable outcome

## 3. Requirement scope and Acceptance Criteria

<!-- BEGIN GENERATED:ACCEPTANCE-CRITERIA -->
| AC ID | Source item | Requirement summary | In scope | Decision refs | Verification refs |
|---|---|---|---|---|---|
| — | — | — | — | — | — |
<!-- END GENERATED:ACCEPTANCE-CRITERIA -->

## 4. Current state and grounding

<!-- BEGIN GENERATED:CURRENT-STATE-GROUNDING -->
| Question | Answer/observation | Authority | Evidence ref | Freshness | Limitations |
|---|---|---|---|---|---|
| — | — | — | — | — | — |
<!-- END GENERATED:CURRENT-STATE-GROUNDING -->

## 5. Configuration and data architecture

<!-- BEGIN GENERATED:DATA-CLASSIFICATIONS -->
| Object / Slice | Schema Ownership | Data Stewardship | Data Role | Assurance | Evidence | Notes |
|---|---|---|---|---|---|---|
| Lead | subscriber-owned | user-generated | transactional | confirmed | — | Custom fields schema ownership only; Lead object itself is platform. |
| LeadScoringRule__mdt | subscriber-owned | admin-maintained | configuration | confirmed | — | — |
| LeadRoutingRule__mdt | subscriber-owned | admin-maintained | configuration | confirmed | — | — |
| SLARule__mdt | subscriber-owned | admin-maintained | configuration | confirmed | — | — |
<!-- END GENERATED:DATA-CLASSIFICATIONS -->

## 6. Options considered

### option-b — Pure Flow implementation

A Flow-only solution could handle record-triggered scoring, routing and notifications. Rejected because Flow becomes hard to test and debug once routing precedence, round-robin counters and BusinessHours SLA calculations are required. Apex service classes give unit-test coverage, bulk safety and clearer error handling for the core transaction logic, while Flow remains appropriate for notifications and scheduled escalation.

## 7. Chosen approach

<!-- BEGIN GENERATED:CONCERN-COVERAGE -->
| Concern | Applicability | Treatment / decision | Questions / risks | Verification |
|---|---|---|---|---|
| data-model-and-configuration-integrity | applicable | #D-001 | — | — |
| security-and-execution-context | applicable | #D-001 | — | — |
| transaction-and-automation | applicable | #D-001 | — | — |
| volume-and-performance | applicable | #D-001 | — | — |
| integrations-and-contracts | applicable | #D-001 | — | — |
| errors-and-observability | applicable | #D-001 | — | — |
| migration-rollout-rollback | applicable | #D-001 | — | — |
<!-- END GENERATED:CONCERN-COVERAGE -->

## 8. Solution Artefacts

<!-- BEGIN GENERATED:SOLUTION-ARTEFACTS -->
| Object | Artefact Type | API Name | Action | Description |
|---|---|---|---|---|
| Lead | CustomObject | Lead | Reuse | Standard Lead object used as the host for custom fields, automation and validation rules. |
| Lead | CustomField | Lead.Lead_Score__c | Create | Numeric lead score from 0 to 100, computed by scoring service. |
| Lead | CustomField | Lead.Lead_Priority__c | Create | Picklist Hot/Warm/Cold derived from Lead Score. |
| Lead | CustomField | Lead.First_Contact_Due_Date__c | Create | SLA deadline for the first contact, computed from BusinessHours. |
| Lead | CustomField | Lead.First_Contact_Date__c | Create | Timestamp of the first completed Call, Email or Meeting activity. |
| Lead | CustomField | Lead.SLA_Status__c | Create | SLA status New/Met/Breached tracked by the SLA service. |
| Lead | CustomField | Lead.Rejection_Reason__c | Create | Picklist reason when Lead is marked Unqualified; Other requires comment. |
| Lead | CustomField | Lead.Budget__c | Create | Estimated budget in PLN used by scoring rules. |
| Lead | CustomField | Lead.Customer_Segment__c | Create | Customer segment such as Enterprise or SMB; drives routing. |
| Lead | CustomField | Lead.Offering_Interest__c | Create | Offering the Lead is interested in; drives routing and scoring. |
| Lead | CustomField | Lead.Number_of_Employees__c | Create | Number of employees at the Lead's company; scoring input. |
| Lead | CustomField | Lead.Assignment_Date__c | Create | Timestamp when the Lead was assigned to an owner or queue. |
| Lead | CustomField | Lead.SLA_Escalated__c | Create | Checkbox indicating SLA breach escalation has been executed once. |
| LeadScoringService | ApexClass | LeadScoringService | Create | Computes Lead Score from configurable scoring rules. |
| LeadRoutingService | ApexClass | LeadRoutingService | Create | Determines owner or queue from country, segment, offering and round-robin. |
| LeadNotificationService | ApexClass | LeadNotificationService | Create | Sends in-app and email notifications to Lead owners. |
| LeadSLAService | ApexClass | LeadSLAService | Create | Computes SLA deadlines and tracks first-contact compliance. |
| Lead | ApexTrigger | LeadTrigger | Create | Single entry-point trigger on Lead that delegates to service classes. |
| LeadAssignmentFlow | Flow | LeadAssignmentFlow | Create | Record-triggered Flow for assignment notifications after routing. |
| LeadEscalationFlow | Flow | LeadEscalationFlow | Create | Scheduled Flow that escalates Leads with breached SLA. |
| LeadScoringRule__mdt | CustomMetadataType | LeadScoringRule__mdt | Create | Admin-configurable scoring rules without code deployment. |
| LeadRoutingRule__mdt | CustomMetadataType | LeadRoutingRule__mdt | Create | Admin-configurable routing rules mapping country/segment/offering to queue. |
| SLARule__mdt | CustomMetadataType | SLARule__mdt | Create | Admin-configurable SLA hours per priority and business hours reference. |
| Sales_Poland | Group | Sales_Poland | Create | Queue for Polish Leads. |
| Sales_DACH | Group | Sales_DACH | Create | Queue for German Leads. |
| Enterprise_Sales | Group | Enterprise_Sales | Create | Queue for Enterprise segment Leads. |
| Unassigned_Leads | Group | Unassigned_Leads | Create | Fallback queue when no routing rule matches. |
| LeadReports | Report | LeadReports | Create | Lead source, owner, priority, SLA and conversion reports. |
| LeadDashboard | Dashboard | LeadDashboard | Create | Manager dashboard with filters and conversion metrics. |
<!-- END GENERATED:SOLUTION-ARTEFACTS -->

## 9. Configuration Artefacts

<!-- BEGIN GENERATED:CONFIGURATION-ARTEFACTS -->
| Object | Configuration Slice / Natural Key | Action | Description |
|---|---|---|---|
| LeadScoringRule__mdt | DeveloperName | Create records | Initial scoring rule records maintained by Salesforce Administrator. |
| LeadRoutingRule__mdt | DeveloperName | Create records | Initial routing rule records mapping country/segment/offering to queues. |
| SLARule__mdt | DeveloperName | Create records | Initial SLA rule records per priority and business hours reference. |
<!-- END GENERATED:CONFIGURATION-ARTEFACTS -->

## 10. Detailed design and interactions

1. **Lead creation** — A Lead is created manually, via import or through an integration. A single `LeadTrigger` fires on before/after insert and update.
2. **Scoring** — `LeadScoringService` reads active `LeadScoringRule__mdt` records and calculates `Lead_Score__c`, clamped to 0–100.
3. **Priority** — `Lead_Priority__c` is set to Hot (80–100), Warm (50–79) or Cold (0–49) from the score.
4. **Routing** — `LeadRoutingService` evaluates `LeadRoutingRule__mdt` by country, customer segment and offering (product) interest, applies round-robin within the matched queue, and sets `OwnerId` and `Assignment_Date__c`.
5. **SLA** — `LeadSLAService` uses the priority and `SLARule__mdt` with `BusinessHours` to set `First_Contact_Due_Date__c`.
6. **Notification** — After successful assignment, `LeadAssignmentFlow` sends an in-app notification; for Hot Leads it also sends email.
7. **First contact** — When a completed Task of type Call, Email or Meeting is logged, `LeadSLAService` sets `First_Contact_Date__c`, computes minutes-to-contact and updates `SLA_Status__c` to Met or Breached.
8. **Escalation** — `LeadEscalationFlow` runs on a schedule, finds Leads whose `First_Contact_Due_Date__c` has passed with no first contact, sets `SLA_Escalated__c` and notifies the owner and manager.
9. **Qualification / conversion** — Sales users move the Lead through statuses. Conversion uses standard Salesforce lead conversion with an optional Opportunity.

## 11. Security, transactions, volume and error handling

- **Sharing** — Apex service classes use `with sharing` and rely on the platform for object/field/record access; queues and sharing rules control Lead visibility.
- **Bulk safety** — All SOQL and DML are collection-based; no queries or DML inside loops.
- **Recursion** — The trigger delegates to a single static flag / check in `LeadTriggerHandler`; Flows avoid recursive updates by checking change flags.
- **Error handling** — Service methods throw `LeadQualificationException` with context; Flow faults route to an error log object and an admin alert.
- **Limits** — Scoring rules are cached in a static map per transaction; routing round-robin uses a single indexed query.

## 12. Decisions

### D-001

Automation framework: Apex trigger with service classes for scoring, routing and SLA; Flow for notifications and escalations.


<!-- BEGIN GENERATED:DECISIONS -->
| Decision ID | Decision | Rationale | Alternatives rejected | Evidence | ACs | Risks |
|---|---|---|---|---|---|---|
| D-001 | Apex trigger with service classes for scoring, routing and SLA; Flow for notifications and escalations. | Apex provides testability, bulk safety and complex conditional logic needed for scoring thresholds, routing precedence and BusinessHours-based SLA. Flow is sufficient for declarative notification and time-based escalation paths and reduces code volume for simple record updates. | Apex for transaction-heavy business logic and Flow for declarative notifications is the established team pattern; no materially different alternative satisfies bulk safety, testability and admin configurability together. | EV-20260805T204726Z-8d3a99b7a689 | — | — |
<!-- END GENERATED:DECISIONS -->

## 13. Risks and Known Limitations

<!-- BEGIN GENERATED:RISKS-LIMITATIONS -->
| ID | Type | Risk / limitation | Impact | Mitigation / acceptance | Evidence | Verification |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |
<!-- END GENERATED:RISKS-LIMITATIONS -->

## 14. Verification Contract

<!-- BEGIN GENERATED:VERIFICATION-CONTRACT -->
| Verification ID | AC | Assertion | Method | Pass criteria | Expected evidence | Executor / Stage |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |
<!-- END GENERATED:VERIFICATION-CONTRACT -->

## 15. Rollout, migration and rollback

- Deploy metadata in a single release: Custom Fields, Custom Metadata Types, Apex, Flows, Queues, Reports and Dashboard.
- Seed initial `LeadScoringRule__mdt`, `LeadRoutingRule__mdt` and `SLARule__mdt` records via a post-deployment step; keep the full seed set in version control for rollback.
- Rollback: revert the deployment and deactivate the trigger via a feature flag if needed.

## 16. Open questions

- What is the expected daily volume of new Leads? This affects the risk tier and limit budget.
- Which BusinessHours record should be used for SLA calculation?
- Are there existing Lead custom fields that overlap with the proposed fields (e.g., a budget or segment field)?

## 17. Evidence appendix

<!-- BEGIN GENERATED:EVIDENCE-APPENDIX -->
| Evidence ID | Source type | Subject | Observed/source revision | Completeness | Freshness | Limitations |
|---|---|---|---|---|---|---|
| EV-20260805T202244Z-231673598df2 | human-sme-attestation | — | 2026-08-05T20:22:44Z | complete | current | human-asserted |
| EV-20260805T204726Z-8d3a99b7a689 | repository-receipt | — | 2026-08-05T20:47:26Z | complete | current | source-exact |
<!-- END GENERATED:EVIDENCE-APPENDIX -->
