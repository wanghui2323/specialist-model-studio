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

## Agent freedom

The Agent may select reasonable architectures, preprocessing, augmentations and hyperparameters within the contract and compute budget. It may repair implementation errors and stop weak candidates early.

It may not change label meaning, use the final test set for tuning, lower release gates, expand data access, increase paid compute, or publish artifacts without authorization.

## Public-repository boundary

Commit source, schemas, small authorized examples and tests. Do not commit user datasets, customer documents, personal voice recordings, credentials, large checkpoints or model caches. Provide download instructions and checksums only when redistribution terms permit them.
