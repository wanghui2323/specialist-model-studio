---
name: train-small-model
description: Turn a concrete task and permitted data into an auditable specialist-model training run. Use when an AI product manager or independent developer wants Code Agent to clarify the task, request missing data, select a suitable open-source recipe, train and evaluate a small model, and package reproducible evidence. Do not use it to claim production readiness from a teaching dataset or to silently execute untrusted model code.
---

# Train Small Model

Operate delegation-first and learning-visible. Advance the task independently when the goal, data rights, acceptance criteria and execution environment are clear. Pause only when user input or authorization changes the meaning, risk or cost of the run.

## Start with task fit

Before training, decide whether parameter training is actually needed. Prefer rules, ordinary software, Prompt/RAG or an existing model API when they satisfy the task more safely and cheaply. A contract-review product may combine OCR/layout models with rules, RAG and an LLM; do not describe the entire system as one small model.

When training is appropriate, identify the fixed input, fixed output, error cost, deployment environment and measurable acceptance threshold.

## Create the contract

Read [references/contract-and-gates.md](references/contract-and-gates.md) before creating or changing a task contract.

Ask only for missing information that blocks safe progress. Typical questions concern representative data, label meaning, data authorization, high-cost errors, target hardware and release thresholds. Do not ask the user to choose algorithm details that the Agent can reasonably decide.

Freeze release gates before model selection. Never weaken them merely because a run failed. Keep the final test set outside candidate selection and tuning.

## Select and run a Recipe

Prefer a registered, deterministic Recipe. Check the framework, code, model-weight and dataset licenses separately. Keep downloaded datasets, weights, private data and credentials outside the public repository.

For the implemented v0.2 alpha reference lab, run:

```bash
python -m model_harness.cli init --recipe digit-classification --output workspaces/my-first-model
python -m model_harness.cli run workspaces/my-first-model/task_contract.json
```

The built-in implementation supports only `digit-classification`. Do not imply that OCR, audio, industrial detection or arbitrary model discovery is already implemented. External Recipes can be registered through the plugin protocol. When adding one, read [references/recipe-authoring.md](references/recipe-authoring.md).

Run external or Agent-generated training code in an isolated workspace with a declared compute budget. Stop for approval before expanding cost, accessing sensitive data, loading an untrusted pickle-based model, or publishing externally.

## Evaluate and hand off

Deliver the model together with its task-contract snapshot, metrics, failure slices, model card, environment versions, file hashes, run state and learning report. A high aggregate score is not sufficient; examine the worst class or business-critical slice and at least one plausible distribution shift.

Use deep verification only for a trusted local model after its hash matches:

```bash
python -m model_harness.cli verify runs/<run-id> --deep
```

Report the exact gate reached: local experiment, independent test passed, real-data shadow test, production release, public repository or published article are separate states.

## Guide an optimization run

After a completed run, inspect the persisted proposals:

```bash
python -m model_harness.cli strategies runs/<run-id>
```

Explain each proposal's evidence, expected effect, cost, risk and real-world limitation. A recommendation is not an approval. Never apply a strategy marked `actionable: false`, and never apply an actionable strategy without the user's explicit approval.

After approval, create a child run rather than editing or overwriting the parent:

```bash
python -m model_harness.cli apply-strategy \
  runs/<run-id> <strategy-id>
```

Compare parent and child metrics, including clean-set regressions and stress-test changes. Do not describe a synthetic stress-test gain as production validation.

## Work with long-running tasks

Use `events` to report progress from the versioned event stream. A cancellation request is honored at a safe stage boundary, so distinguish “cancel requested” from “cancelled.” After a process restart, active work becomes `interrupted`; `resume` creates an auditable child run from the frozen contract instead of silently continuing the old run.

The optional HTTP/SSE service is an adapter boundary for chat frontends. Bind it to `127.0.0.1` unless authentication and network controls have been added. Do not claim the DeepSeek Harness frontend adapter exists until its package and interaction tests are present.

## Human-owned decisions

Always leave these decisions to an accountable person:

- label semantics and business error cost;
- permission to use private or customer data;
- independent release-set composition;
- production threshold, shadow/gray release and rollback;
- third-party license acceptance and public publication.
