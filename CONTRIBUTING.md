# Contributing

Specialist Model Studio is in alpha. Small, reviewable contributions that preserve its audit and safety boundaries are preferred.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[server]'
.venv/bin/python scripts/verify_project.py
```

## Contribution types

- bug fixes with a regression test;
- Recipe plugins with public or generated integration-test data;
- contract, event or artifact compatibility improvements;
- chat adapters that remain thin clients of the HTTP/event contracts;
- documentation that clearly separates teaching runs from production evidence.

New Recipes must follow `skills/train-small-model/references/recipe-authoring.md`. Do not add private datasets, customer files, credentials, large checkpoints or model caches. Code, data and model-weight licenses must be reviewed separately.

## Pull requests

Describe the user problem, contract or API changes, safety impact and exact verification performed. Breaking schema or event changes require a version update and migration note. Optimization features must retain explicit approval and parent-child lineage.
