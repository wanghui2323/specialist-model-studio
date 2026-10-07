# DeepSeek Harness Conversation Adapter

Local validation can use an existing **ChatGPT login in Codex CLI** instead of a DeepSeek API key. Set `MODEL_HARNESS_AGENT_PROVIDER=codex-cli` when starting Studio. The adapter uses `codex app-server` over private stdio and explicitly selects `gpt-5.6-sol`; it does not fall back to another model. Run `codex login status` first. A model catalog is not proof of account access: a completed inference is required.

The Studio readiness/selection layer accepts runtime-registered provider IDs, rather than a two-vendor allowlist. For a configured API or local route set `MODEL_HARNESS_AGENT_PROVIDER`, `MODEL_HARNESS_AGENT_MODEL`, and its `MODEL_HARNESS_AGENT_CREDENTIAL_REF`. An explicitly configured local endpoint without authentication can declare `MODEL_HARNESS_AGENT_AUTH=none`; it still needs an active native adapter. This does not register a new protocol or prove connectivity. Credentials remain in the native credential store/environment. The model/effort can be selected with `MODEL_HARNESS_AGENT_MODEL` / `MODEL_HARNESS_AGENT_REASONING_EFFORT`; new specialists use the configured default, and an idle existing root adopts it before submission.

`model-context.js` is the provider-neutral working-set projection. The CLI adapter currently consumes it; other adapters must integrate the same policy at their serialization boundary before claiming equivalent coverage. It never rewrites frozen native messages or durable evidence. Old large tool results and machine notifications become hash-bound historical references; actual user text, recent messages and rich media remain. Native compaction has no execution tools. Route traces under the configured runs workspace record counts/digests/references, never user content or credential values. See [ADR-003](../../plans/v1.0-conversation-native/ADR-003-CONTEXT-RUNTIME.md) for the remaining goal ledger, snapshot/diff, phased summarization and recovery work.

DSH still owns conversation history, specialist roles, tool execution and native approval checkpoints. Codex supplies text and dynamic-tool requests only. Each request uses an ephemeral, read-only model session; shell, apps, plugins, browser and native delegation are disabled. API-key environment variables and the Studio bridge credential are excluded from that process. Codex owns its existing login storage and renewal; Studio never copies its OAuth tokens. Generated training code still runs exclusively through the approved OCI executor.

The optional route was checked with Codex CLI `0.145.0`. Dynamic-tool and history-injection APIs are experimental: incompatible protocol responses fail the model call, rather than silently skipping tools or approvals. Existing DeepSeek sessions need an explicit model-selection change or a new Codex-backed specialist invocation when switching providers. This setting is local validation configuration; it does not replace the independent training, model-quality or release gates.

This package is an optional conversation, multi-agent delegation and approval adapter for Specialist Model Studio. It registers **51** `model_harness_*` compatibility tools against the local Python server and a repository-managed DSH preset with one Training Orchestrator plus five role-scoped specialist agents. It was authored against `dsh` `0.1.0-rc.6`, `@deepseek-ai/dsh-tools` `0.1.0-rc.8` and the `@deepseek-ai/dsh-tool-subagent` `0.1.0-rc.6` schema.

DeepSeek Harness is not forked, copied, or used as the training state store. `TrainingTask`, dataset, contract, `TrainingRun`, event, metric, artifact, lineage, and evidence facts remain in Specialist Model Studio's `model_harness` engine.

## Native multi-agent composition

The `model-training` preset creates a DSH-native root/child topology rather than simulating specialist activity in frontend state:

| Root or delegate tool | Responsibility | Child authority |
|---|---|---|
| Training Orchestrator | User dialogue, lifecycle routing, approval timing and final synthesis | Root session; all domain facts still come from `model_harness_*` |
| `research_source` | Model/source discovery, immutable resolution, binding and static source evidence | Source-only `model_harness_*` allowlist |
| `data_experiment` | Data Adapter, dataset inspection and representative sample evidence | Data-only `model_harness_*` allowlist |
| `resource_safety` | Training plan, isolation policy and machine feasibility | Plan/resource-only `model_harness_*` allowlist |
| `build_training` | Trusted RecipeFactory, frozen contract and canonical TrainingRun | Build/run-only `model_harness_*` allowlist |
| `evaluation_delivery` | EvaluationReport, fresh-sample inference and Artifact Bundle | Evaluation/delivery-only `model_harness_*` allowlist |

Each delegate is a separate `@deepseek-ai/dsh-tool-subagent` instance using the host `spawn` provider, `backgroundMode: continuable`, a role persona, an explicit `toolFilter.allow`, and `maxDepth: 1`. Independent work may run in parallel; dependent stages and mutable approval decisions remain ordered. The root receives durable child ids and settlement notices, can continue a child through DSH control tools, and is solely responsible for combining canonical evidence into the user-facing conclusion.

The child allowlists contain only `model_harness_*` tools—no shell, generic coding, browser or recursive delegation tool. This is a composition boundary, not a replacement for backend authorization: mutating domain tools still pass through DSH native approval and the Python engine's independent task, digest, isolation and lineage checks. No persona or delegate result counts as human approval.

## Human conversation contract

The root coordinator translates engine state into a short, business-facing dialogue. It reflects the outcome it heard, identifies the single uncertainty that changes the route, and asks one decision at a time. Task ids, lifecycle stages, Recipe/Data Adapter names, family enums and raw tool results stay in the evidence layer instead of becoming conversation copy.

Ambiguous time-series language is deliberately not mapped to the nearest runnable feature. “Numeric prediction” may mean forecasting future values from ordered history or estimating one value for each independent row; the coordinator must clarify that temporal distinction before selecting `time_series_forecasting` or `tabular_regression`. Unsupported forecasting remains an honest capability boundary, not a disguised tabular run.

Data collection is attachment-first. The coordinator asks the user to drag a representative file into the conversation or use “导入数据”, can show a small example format when the data is not ready, and inspects an uploaded file before asking about a discovered target column. It must not ask the user to type host absolute paths or workspace-relative paths.

## Start the complete product

From a source checkout with the server extra and DSH installed, use the single public entry point:

```bash
uv run specialist-model-studio start --host 127.0.0.1 --port 8765
```

The command installs the repository-managed preset, links this adapter, starts or safely reuses the exact backend/DSH pair, verifies the real-agent runtime contract, and prints only `http://127.0.0.1:8765/app`. Port `3080` remains internal.

## Manual adapter setup for development

Install the local package and repository-managed preset:

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

The package declares `dsh.bundle.patch`, so a separate `--patch` argument is not required. The preset installer refuses to overwrite a preset without this project's management marker.

Run the preset installer again after changing or pulling `presets/model-training/*`; DSH mounts the installed copy under `${DSH_HOME:-$HOME/.dsh}/.agent-presets/model-training` for new sessions. Existing sessions retain the composition recorded when they were created.

If an existing DSH profile still opens in the standard preset, select “模型训练模式” in Settings → Agent Preset. Preset changes affect new sessions and preserve existing history.

Override the backend URL only when the target is trusted:

```bash
MODEL_HARNESS_URL=http://127.0.0.1:8765 \
  dsh web --host 127.0.0.1 --port 3080
```

Developers who need the internal runtime URL and verbose startup output can run:

```bash
./scripts/start_conversation_harness.sh
```

The launcher keeps sessions, settings, presets, and runtime files under its
isolated `DSH_HOME`, while configuring only the `credentials` provider with a
separate store path. Set `MODEL_HARNESS_DSH_CREDENTIALS_FILE` to select that
store explicitly. Otherwise, an existing standard user DSH credential store is
reused; if none exists, the isolated home's store remains the fallback. The
launcher does not copy credential values or print the selected path/content,
and provider keys are not forwarded to model tool subprocesses.

Open `http://127.0.0.1:8765/app` for the product experience. Port `3080` is the internal/debug DSH runtime used by that workbench, not a second product frontend. Tool results and child transcripts are projected back into the task-specific conversation backed by the same `TrainingTask.task_id`.

The launcher fails closed when either port is already occupied. It reuses a backend only when `/runtime` proves a live `dsh_native_subagents` Agent, conversation schema `2.0`, projector revision `3.2`, and an exact identity match for this checkout, the configured runs directory, its workspace, and the configured DSH origin. A healthy but stale/cold-clone/local-flow backend is reported as a conflict instead of being presented as a successful Agent startup. Use `MODEL_HARNESS_RUNS_DIR` to select a different runs workspace; the launcher never kills an unidentified process.

## The 51 compatibility tools

The current bundle registers 51 tools in seven groups:

| Group | Count | Scope |
|---|---:|---|
| TrainingTask, specification and discovery | 7 | tasks, adapters, capability matching, creation, clarification, immutable TaskSpec updates and detail |
| Universal model source and repository analysis | 9 | providers, search records, candidate selection, immutable resolution, binding and static analysis |
| Training plan and local resources | 6 | immutable plan revisions, digest decisions, resource probing and feasibility reports |
| Hugging Face fixed ModelAsset path | 5 | capability, search, Model Card, approved fixed-commit attachment and hash verification |
| Data and Recipe Factory | 7 | dataset import, scaffold, audio sample staging, declarative build, review, register, reject |
| Contract and TrainingRun lifecycle | 9 | Recipes, configure/confirm, task-owned start, result/events/strategies, approved optimization and cancellation |
| Evaluation and delivery | 8 | EvaluationReport, raw-sample inference run/list/detail, Artifact Bundle build/list/detail/download |

The executable user-data Recipes are image classification, tabular regression, and offline audio keyword classification. Digits remains a teaching Recipe. A tool count is not an algorithm count and does not imply arbitrary-model support.

Mutating tools pass through DSH native approval. The Python backend independently re-checks task ownership, TaskSpec, data, contract confirmations, Recipe registration, Run state, and parent/child lineage; an approval card cannot bypass these checks.

## Recipe Factory truth boundary

For an audio-classification task with no active Recipe, the Agent can stage a representative class-folder WAV ZIP, submit an allowlisted declarative RecipeSpec, show its candidate and validation digests, and request explicit registration approval.

The inherited trusted declarative audio template is the only executable dynamic Recipe Factory path in the current local engine. Requests to build Python or other executable generated code are persisted as `blocked_environment`; they are not run or silently registered. A scaffold packet is a build contract, not a runnable Recipe.

Other unmatched capabilities remain visible capability gaps. OCR, detection, ASR, TTS, time-series, text, and other unregistered tasks must not be described as trained.

## Evaluation and delivery conversation tools

The Agent can now call the same task-owned HTTP objects used by the workbench for official Hugging Face fixed-commit image assets, `EvaluationReport`, explicit new-sample inference, and privacy-filtered Artifact Bundles. These are orchestration tools around the existing backend; they do not implement alternate training or evidence logic.

HF attachment, raw-sample upload, Bundle construction and Bundle download require DSH native approval, and the backend still enforces immutable commits, task/Run ownership, hashes and privacy boundaries. DSH responses use an `agent-v1` public projection that removes host absolute paths; the local UI retains its richer local projection. Bundle download verifies the server manifest SHA-256 and creates a new user-selected ZIP without overwriting an existing file.

## Boundaries

- Plugin registration proves that DSH loaded the bundle; a provider-backed model call is a separate verification layer.
- Contract tests prove the five delegate definitions and role restrictions, not that a live provider completed a subagent turn. A release check must create a new `model-training` session, observe the five tool schemas, start at least one delegate and verify its durable child transcript plus canonical backend evidence.
- Specialist agents do not make the Python engine support an unregistered algorithm. They may only reach a real trained model or an honest typed blocker through existing domain capabilities.
- The Python server owns a process-level writer lease for its `runs/` workspace. A second backend targeting the same directory is rejected before it can publish events or mutate a task.
- The Python server has no multi-user authentication and must remain on a trusted local interface.
- DSH is optional. The Python training and evidence runtime continues without it.
- DSH is a developer preview; re-test the adapter after any upgrade.
- `1.0.0-rc.2` is a developer source preview candidate. The Python wheel remains backend-only and the actual publication state is recorded by the exact candidate commit, cold-clone/CI evidence and GitHub Prerelease receipt.

## Test

```bash
npm --prefix integrations/deepseek-harness test
npm --prefix integrations/deepseek-harness run check
```

The plugin test asserts the complete 51-name tool set, five continuable delegate contracts, personas, allowlists, absence of child shell/generic tools, coordinator prompt, public projection and native approval seam. It does not prove a live provider response, successful training data, or GitHub publication.
