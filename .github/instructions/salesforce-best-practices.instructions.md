---
applyTo: "**"
---

# Salesforce Best Practices (industry-general)

Source: the industry — independent of the company and of the package vendor. Lowest tier in
the precedence hierarchy: when a rule here conflicts with Organization Principles or Managed
Package Constraints, those win (see `.github/copilot-instructions.md`).

## Bulkification

- Never place SOQL queries or DML statements inside a loop. Collect records, query once,
  operate on collections.
- Write every trigger, Flow and Apex path assuming it will run on a batch of records
  (up to 200 in a trigger context), never on a single record.

## Trigger architecture

- One trigger-handler per object: a single trigger per SObject delegating to a handler class.
  No logic directly in the trigger body.

## Security & sharing

- `with sharing` is the default for Apex classes. Deviate only deliberately, with the reason
  documented at the class declaration.

## Naming conventions (general)

- Apex classes: `PascalCase`.
- Custom fields: `camelCase` (label conventions aside) with the `__c` suffix as Salesforce
  requires. Names should say what the field means, not how it is implemented.
- Company-specific conventions extend (and take precedence over) these — see
  `organization-principles.instructions.md`.

## Governor limits

- Treat governor limits as a design constraint, not a runtime surprise: mind SOQL query
  counts, DML row counts, CPU time and heap in every design and review.

## Testing patterns

- Use `@TestSetup` for shared test data.
- Avoid `SeeAllData=true` — tests create their own data.
- Assert behavior, not just coverage.
