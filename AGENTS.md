# AI PM Model Harness Boundaries

This project is an educational, agent-operated harness for auditable specialist-model training.

- Keep the default experience delegation-first: the agent advances independently and pauses only for missing data, authorization, immutable acceptance criteria, unsafe execution, or release approval.
- Preserve an optional learning view from the same run. Do not build a separate tutorial workflow that diverges from execution evidence.
- Treat `task_contract.json` release gates and test-set policy as human-owned. Agents may report failure but must not weaken gates or reuse the final test set for model selection.
- Keep source code, small public examples, schemas, and validation logic in the repository. Keep private user data, credentials, generated voice, customer documents, large datasets, downloaded weights, and run outputs outside version control.
- `runs/`, `.venv/`, model caches, and downloaded datasets are reproducible local state, not source artifacts.
- v0.1 supports only the registered digit-classification reference recipe. Future directories or documentation must not imply broader implemented support.
- Local tests prove reproducibility of the reference lab, not production readiness or publication to GitHub.
