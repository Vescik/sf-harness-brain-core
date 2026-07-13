# Archived design history

Everything in this folder is **historical input, not runtime authority**. It is retained as
provenance for how the harness was designed, built, and reviewed. Where any file here conflicts
with the root `README.md`, `SETUP.md`, `docs/`, or `.ai/contracts/`, the current files win.

| File | What it is | Status notes |
|---|---|---|
| `HARNESS_BLUEPRINT.md` | Original binding design blueprint | **Polish-language.** Superseded by the current English docs; kept for design rationale only. |
| `HARNESS_DIAGRAMS.md` | Companion diagrams to the blueprint | Known drift: some sections show four agents; the built harness has five. |
| `BUILD_REPORT.md` | Audit report of the original scaffold build | Placeholder/flag inventories reflect the pre-hardening state. |
| `HANDOFF_FOR_FABLE.md` | First independent review handoff | Review verdict and fixes are recorded in `BUILD_REPORT.md`. |
| `HANDOFF_FOR_FABLE_CHECKER.md` | Second review handoff (audit-fix verification) | Written before its changes were committed; its "nothing was committed", untracked-file, and test-count statements no longer describe the repository. |

Do not update these files to track the current system; append to the current docs instead.
