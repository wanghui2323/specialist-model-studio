# DeepSeek Harness Adapter

This package is an optional conversation and approval adapter for Specialist Model Studio. It registers **37** `model_harness_*` compatibility tools against the local Python server. It was authored against `dsh` `0.1.0-rc.6` and `@deepseek-ai/dsh-tools` `0.1.0-rc.8`.

DeepSeek Harness is not forked, copied, or used as the training state store. Task, dataset, contract, Run, event, metric, artifact, lineage, and evidence facts remain in Specialist Model Studio's `model_harness` engine.

## Install into the Web profile

Start the Python service first:

```bash
specialist-model-studio serve --host 127.0.0.1 --port 8765
```

Install the local package and repository-managed preset:

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

The package declares `dsh.bundle.patch`, so a separate `--patch` argument is not required. The preset installer refuses to overwrite a preset without this project's management marker.

If an existing DSH profile still opens in the standard preset, select “模型训练模式” in Settings → Agent Preset. Preset changes affect new sessions and preserve existing history.

Override the backend URL only when the target is trusted:

```bash
MODEL_HARNESS_URL=http://127.0.0.1:8765 \
  dsh web --host 127.0.0.1 --port 3080
```

After one-time installation, both local services can be started with:

```bash
./scripts/start_conversation_harness.sh
```

Open `http://127.0.0.1:3080` for the optional conversation host. Tool results link to the task-specific Specialist Model Studio workbench backed by the same `task_id`.

## The 37 tools

The current bundle registers 37 tools in five groups:

| Group | Count | Scope |
|---|---:|---|
| Task, specification and discovery | 6 | tasks, adapters, capability matching, creation, immutable TaskSpec updates and detail |
| Hugging Face ModelAsset | 5 | capability, search, Model Card, approved fixed-commit attachment and hash verification |
| Data and Recipe Factory | 7 | dataset import, scaffold, audio sample staging, declarative build, review, register, reject |
| Contract and Run lifecycle | 11 | Recipes, configure/confirm, task or teaching Run start, result/events/strategies, approved optimization and cancellation |
| Evaluation and delivery | 8 | EvaluationReport, raw-sample inference run/list/detail, Artifact Bundle build/list/detail/download |

The executable user-data Recipes are image classification, tabular regression, and offline audio keyword classification. Digits remains a teaching Recipe. A tool count is not an algorithm count and does not imply arbitrary-model support.

Mutating tools pass through DSH native approval. The Python backend independently re-checks task ownership, TaskSpec, data, contract confirmations, Recipe registration, Run state, and parent/child lineage; an approval card cannot bypass these checks.

## Recipe Factory truth boundary

For an audio-classification task with no active Recipe, the Agent can stage a representative class-folder WAV ZIP, submit an allowlisted declarative RecipeSpec, show its candidate and validation digests, and request explicit registration approval.

Only the trusted declarative audio template is executable in v0.7. Requests to build Python or other executable generated code are persisted as `blocked_environment`; they are not run or silently registered. A scaffold packet is a build contract, not a runnable Recipe.

Other unmatched capabilities remain visible capability gaps. OCR, detection, ASR, TTS, time-series, text, and other unregistered tasks must not be described as trained.

## L3/L4 conversation tools

The Agent can now call the same task-owned HTTP objects used by the workbench for official Hugging Face fixed-commit image assets, `EvaluationReport`, explicit new-sample inference, and privacy-filtered Artifact Bundles. These are orchestration tools around the existing backend; they do not implement alternate training or evidence logic.

HF attachment, raw-sample upload, Bundle construction and Bundle download require DSH native approval, and the backend still enforces immutable commits, task/Run ownership, hashes and privacy boundaries. DSH responses use an `agent-v1` public projection that removes host absolute paths; the local UI retains its richer local projection. Bundle download verifies the server manifest SHA-256 and creates a new user-selected ZIP without overwriting an existing file.

## Boundaries

- Plugin registration proves that DSH loaded the bundle; a provider-backed model call is a separate verification layer.
- The Python server has no multi-user authentication and must remain on a trusted local interface.
- DSH is optional. The Python training and evidence runtime continues without it.
- DSH is a developer preview; re-test the adapter after any upgrade.
- `0.9.0-rc.1` is an unreleased review-candidate package version. This README does not claim that the current local commit has been pushed, tagged, or released on GitHub.

## Test

```bash
npm --prefix integrations/deepseek-harness test
npm --prefix integrations/deepseek-harness run check
```

The plugin test asserts the complete 37-name tool set, public projection and native approval seam. It does not prove a live provider response, successful training data, or GitHub publication.
