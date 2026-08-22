# Adding a training Recipe

Read this reference only when implementing a new task family.

## Required behavior

A Recipe must:

1. declare supported task type, input schema, output schema and device requirements;
2. validate data format and authorization metadata before training;
3. create fixed train, validation and final-test boundaries;
4. include a trivial or established baseline;
5. select candidates without using the final test set;
6. measure product-relevant quality plus model size and inference latency;
7. retain failed slices and diagnostic stress tests;
8. export a model card, metrics, environment versions and reproducible hashes;
9. expose a deterministic integration test using public or generated data;
10. document code, model-weight and dataset licenses separately.

## Plugin protocol

Implement every method in `model_harness.plugin_api.RecipePlugin`:

- `template` returns a new task-contract object;
- `validate_contract` validates all Recipe-specific fields;
- `train`, `evaluate` and `package` own task-specific modeling behavior;
- `propose_strategies` returns evidence-linked recommendations;
- `apply_strategy` changes only explicitly supported, approved parameters;
- `learning_report` explains the run and recommendations to a learner;
- `deep_verify` checks trusted task-specific artifacts after generic hashes pass.

Declare a stable `RecipeManifest`, instantiate the plugin as `PLUGIN`, and register a developer-reviewed external package with:

```toml
[project.entry-points."ai_pm_model_harness.recipes"]
my-recipe = "my_package.recipe:PLUGIN"
```

Core owns state, events, manifests, hashes, cancellation and parent-child lineage. Plugins must not overwrite an existing run directory or mutate a prior run's artifacts.

This entry-point protocol is a source-development interface, not permission for the running Agent to execute generated Python. In v0.7, any new executable plugin must be reviewed, tested and installed outside the product loop by an accountable developer; without a verified isolation environment, Agent-generated code remains `blocked_environment`.

Optimization proposals must separate diagnosis from action. Use `actionable: false` when more data, authorization, labeling or business judgment is required. Applying a supported strategy creates a new contract and child run; it must never weaken release gates or expose the final test set to candidate selection.

## Agent freedom

The Agent may select reasonable architectures, preprocessing, augmentations and hyperparameters within the contract and compute budget. It may repair implementation errors and stop weak candidates early. A persisted optimization strategy still requires the approval declared by the contract.

It may not change label meaning, use the final test set for tuning, lower release gates, expand data access, increase paid compute, or publish artifacts without authorization.

## Public-repository boundary

Commit source, schemas, small authorized examples and tests. Do not commit user datasets, customer documents, personal voice recordings, credentials, large checkpoints or model caches. Provide download instructions and checksums only when redistribution terms permit them.
