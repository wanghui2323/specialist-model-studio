# Task contract and human gates

Read this reference when creating, reviewing or changing a training task contract.

## Contract objects

| Object | Why it exists | What breaks when absent |
| --- | --- | --- |
| Business goal | Connects model output to a user-visible decision | The Agent optimizes a metric with no product meaning |
| Recipe | Binds the run to implemented, reviewable code | “Model selection” becomes arbitrary code generation |
| Dataset boundary | Records source, authorization, split and known gaps | Leakage or unlicensed data can create misleading results |
| Selection metric | Decides which candidate wins before the test set opens | The Agent can overfit the final answer |
| Release gates | Makes failure reportable without redefining success | A failed run can silently lower its own bar |
| Compute budget | Bounds iterations, parallel jobs and devices | Autonomous tuning can create uncontrolled cost |
| Optimization policy | Bounds iteration count and records approval rules | Suggestions can become an unreviewed autonomous loop |
| Human gates | Names decisions that need accountable approval | Agent output is mistaken for production authorization |

## Minimum user questions

Ask a user only when the answer cannot be inferred safely:

1. What fixed input will the model receive and what fixed output should it return?
2. Which mistakes are most expensive or dangerous?
3. Is the data authorized, representative and labeled consistently?
4. Which hardware, latency, model-size or offline constraints apply?
5. What evidence is required before shadow testing or release?

Do not ask users without modeling expertise to choose an architecture, optimizer or hyperparameter unless the product decision truly depends on it.

## Immutable during a run

- test-set membership and access policy;
- release thresholds;
- primary model-selection metric;
- data authorization boundary;
- maximum compute budget without additional approval.

An optimization iteration is always a new child run. Record the parent run, approved strategy and resulting contract. Do not mutate the parent contract, model, metrics, events or manifest.

If one must change, close the run, record the reason, create a new contract version and start a new run.
