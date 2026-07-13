# Harness evaluations

The deterministic suite proves hook decisions, role path boundaries, frontmatter/wiring contracts,
schema fixtures, and workspace safety configuration without contacting Salesforce or Azure DevOps.

Run:

```bash
python3 scripts/validate_harness.py
python3 -m unittest discover -s tests -v
python3 scripts/run_evals.py
```

`safety-scenarios.yaml` is executable in CI. `agent-scenarios.yaml` is the forward-test checklist
for VS Code because model/tool resolution and handoff rendering require the Copilot host. Record
results in the pull request; a textual answer that merely contains the expected words is not a
pass. Sanitized fixtures intentionally include complete and partial responses so incomplete
evidence behavior can be tested without real business data.
