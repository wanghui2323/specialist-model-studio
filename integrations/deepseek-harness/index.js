import { defineTool } from "@deepseek-ai/dsh-tools";

import { ModelHarnessClient } from "./client.js";

export const name = "specialist-model-studio-tools";
export const inject = ["tools", "systemPrompt"];
export const TASK_FAMILIES = Object.freeze([
  "image_classification",
  "ocr",
  "object_detection",
  "segmentation",
  "audio_classification",
  "asr",
  "speech_synthesis",
  "tabular_classification",
  "tabular_regression",
  "time_series_forecasting",
  "anomaly_detection",
  "text_classification",
  "named_entity_recognition",
  "classification",
  "regression",
  "custom",
]);

const APPROVAL_REQUIRED_TOOLS = new Set([
  "model_harness_import_dataset",
  "model_harness_select_model_source_candidate",
  "model_harness_bind_model_source",
  "model_harness_decide_training_plan",
  "model_harness_stage_recipe_samples",
  "model_harness_build_recipe",
  "model_harness_register_recipe",
  "model_harness_reject_recipe",
  "model_harness_scaffold_recipe",
  "model_harness_configure_contract",
  "model_harness_confirm_contract",
  "model_harness_hf_attach",
  "model_harness_start_task_run",
  "model_harness_start_run",
  "model_harness_apply_task_strategy",
  "model_harness_apply_strategy",
  "model_harness_cancel_run",
  "model_harness_run_sample_inference",
  "model_harness_build_artifact_bundle",
  "model_harness_download_artifact_bundle",
]);

const jsonOutput = {
  schema: { type: "json" },
  render: (_args, value) => [
    { type: "text", text: JSON.stringify(value, null, 2) },
  ],
};

export function apply(ctx) {
  const client = new ModelHarnessClient();

  ctx.systemPrompt.section({
    name: "domain:model-training-harness",
    order: 118,
    text: `You are the Model Training Agent: a conversation-first operator for people who do not train models professionally. Turn a concrete business goal into an auditable specialist-model training task while keeping the user in control of data authorization, label meaning, acceptance gates, compute, and optimization.
For specialist-model training requests, use the model_harness_* tools as the only source of task, dataset, run, metric, artifact, lineage, and approval facts. Do not use shell commands or generic coding tools to bypass the domain lifecycle.
The user-data workflow is: create one persistent task from the user's raw business goal; read task.control and task.capability_decision; ask exactly one high-impact clarification question at a time and offer the backend candidates as concise choices. Never invent modality, objective or output shape in model_harness_create_task. Use model_harness_clarify_task_spec when the user answers in their own words, and model_harness_update_task_spec only after the user chooses an exact output family. Do not expose a full field checklist unless the user asks to edit advanced details.
After the TaskSpec is resolved, the Universal BYOM workflow is: read official source-provider capabilities; search Hugging Face and GitHub metadata; show candidates with provider, repository, revision, license and risk facts; require the user to select one exact candidate; resolve and bind one immutable commit only with explicit approval; read the static repository analysis; propose an immutable training plan; require approval of the exact plan digest; and run the local resource-feasibility check. Candidate families and search results are not proof of runnable support. Arbitrary repositories may honestly terminate with typed BlockerEvidence when this machine, v0.9 CPU-only policy, dependency metadata, or verified OCI isolation is insufficient. Never execute third-party repository code on the host and never claim every repository can train successfully.
For the three validated built-in capabilities, import and explain the inspection report, review labels or target fields and acceptance gates, collect the three explicit confirmations, start the task run, poll canonical events/results, and explain failures or strategies. For an audio-classification task in needs_recipe, ask for a representative class-folder WAV ZIP, stage it, run the trusted declarative Recipe build, show the candidate_digest and validation_digest, and register it only after explicit human approval. The factory never executes generated Python. Other unmatched capabilities remain buildable requests, not runnable training support.
For an image-classification task, Hugging Face is an optional fixed feature extractor, not arbitrary fine-tuning: inspect capability, search and the model card; require an exact 40-character commit; attach only after native approval and approval_confirmed=true; then verify the local asset before training. Never ask for or transmit a Hugging Face token through chat tools.
After a completed task-owned Run, read the EvaluationReport dimensions before making a release claim. A user-authorized raw image, WAV or one-row JSON/CSV may be tried through model_harness_run_sample_inference; never substitute training or test data. Build an Artifact Bundle only from trusted evidence, and download it only to a user-selected new .zip path after native approval. Treat integrity, metric gates, evidence sufficiency and release conclusion as separate facts.
Work like an execution agent, not a form wizard: ask only for information that the tools cannot discover, say what is happening before a meaningful tool call, and after each phase summarize the evidence, the unresolved decision, and the next action. When a tool returns workbench_url, include it as the evidence view for that same task_id.
Never use the teaching digit run as a substitute for a user's OCR, speech, forecasting, or industrial vision task. Never invent progress, metrics, approvals, files, or completed work. Never describe a queued or running job as completed. A returned workbench_url is an evidence view for the same task_id, not a separate source of truth.`,
  });

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_tasks",
      description: "List persistent user-data training tasks and their canonical lifecycle state. Use this before creating a duplicate task.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: () => ({ card: "generic", title: "List model-training tasks" }),
      async execute(_args, exec) {
        return client.listTasks(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_data_adapters",
      description: "List installed Data Adapters and their supported modalities and file extensions.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.dataAdapters(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_match_capability",
      description: "Explainably match a normalized capability request to installed Recipes before creating a task.",
      parameters: {
        modality: { type: "string", required: true },
        objective: { type: "string", required: true },
        target_kind: { type: "string", required: true },
        data_adapter: { type: "string" },
        tags: { type: "array", items: { type: "string" } },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.matchCapabilities({
          modality: args.modality,
          objective: args.objective,
          target_kind: args.target_kind,
          ...(args.data_adapter ? { data_adapter: args.data_adapter } : {}),
          ...(args.tags ? { tags: args.tags } : {}),
        }, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_create_task",
      description: "Create one persistent user-data model-training task after the user has described a concrete business goal. This creates a draft only; it does not train a model.",
      parameters: {
        name: { type: "string", required: true, description: "Short user-facing task name." },
        business_goal: { type: "string", required: true, description: "The user's raw business goal without inferred modality or output fields." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Create training task: ${args.name}`, rawInput: args.business_goal }),
      async execute(args, exec) {
        const result = await client.createTask(args.name, args.business_goal, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(result.task.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_update_task_spec",
      description: "Create an immutable TaskSpec revision after the user explicitly confirms one output family. Keeps the same task_id and never starts training.",
      parameters: {
        task_id: { type: "string", required: true },
        base_revision: { type: "integer", required: true, description: "Current revision returned by model_harness_get_task." },
        selected_family: { type: "string", required: true, enum: TASK_FAMILIES },
        business_goal: { type: "string", description: "Optional corrected business goal in the user's words." },
        user_note: { type: "string", description: "Short reason for the revision." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Confirm task specification ${args.task_id}`, rawInput: args.selected_family }),
      async execute(args, exec) {
        const result = await client.updateTaskSpec(args.task_id, {
          baseRevision: args.base_revision,
          selectedFamily: args.selected_family,
          businessGoal: args.business_goal,
          userNote: args.user_note,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_task",
      description: "Read the canonical task, inspected dataset, frozen contract, current run, results and lineage for one task_id.",
      parameters: {
        task_id: { type: "string", required: true, description: "Task id returned by model_harness_create_task or model_harness_list_tasks." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: (args) => ({ card: "generic", title: `Inspect training task ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.getTask(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_clarify_task_spec",
      description: "Persist the user's free-form clarification as a new immutable TaskSpec revision, then let the backend re-evaluate the one remaining question. This does not confirm a capability or start training.",
      parameters: {
        task_id: { type: "string", required: true },
        base_revision: { type: "integer", required: true },
        business_goal: { type: "string", required: true, description: "Complete revised business goal in the user's words, including their latest clarification." },
        user_note: { type: "string", description: "Short audit note describing the user's clarification." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Clarify task ${args.task_id}`, rawInput: args.user_note || args.business_goal }),
      async execute(args, exec) {
        const result = await client.clarifyTaskSpec(args.task_id, {
          baseRevision: args.base_revision,
          businessGoal: args.business_goal,
          userNote: args.user_note,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_providers",
      description: "List current Hugging Face and GitHub source-discovery capabilities and limitations before searching.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.modelSourceProviders(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_search_model_sources",
      description: "Search official Hugging Face and GitHub metadata for candidates tied to the current TaskSpec revision. Results are suggestions, not compatibility approval.",
      parameters: {
        task_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        query: { type: "string", description: "Optional search query; omit to let the backend derive it from the confirmed TaskSpec." },
        providers: { type: "array", items: { type: "string", enum: ["huggingface", "github"] } },
        limit_per_provider: { type: "integer", description: "1 to 10 candidates per provider; defaults to 4." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Search model sources for ${args.task_id}`, rawInput: args.query || "TaskSpec-derived query" }),
      async execute(args, exec) {
        const result = await client.searchModelSources(args.task_id, {
          query: args.query,
          providers: args.providers,
          limitPerProvider: args.limit_per_provider === undefined ? 4 : args.limit_per_provider,
          baseSpecRevision: args.base_spec_revision,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_searches",
      description: "List persisted source searches for one task so the agent can recover after reload without repeating network search.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.listModelSourceSearches(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_select_model_source_candidate",
      description: "Record the user's explicit selection of one exact search candidate and resolve its immutable upstream commit. Selection is approval-gated and does not execute repository code.",
      parameters: {
        task_id: { type: "string", required: true },
        search_id: { type: "string", required: true },
        candidate_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Select model source for ${args.task_id}`, rawInput: args.candidate_id }),
      async execute(args, exec) {
        const result = await client.selectModelSourceCandidate(args.task_id, {
          searchId: args.search_id,
          candidateId: args.candidate_id,
          baseSpecRevision: args.base_spec_revision,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_resolve_model_source",
      description: "Resolve a user-provided public Hugging Face or GitHub reference to immutable upstream metadata without executing its code.",
      parameters: {
        task_id: { type: "string", required: true },
        source_reference: { type: "string", required: true },
        provider: { type: "string", enum: ["huggingface", "github"] },
        requested_revision: { type: "string" },
        base_spec_revision: { type: "integer", required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Resolve model source for ${args.task_id}`, rawInput: args.source_reference }),
      async execute(args, exec) {
        const result = await client.resolveModelSource(args.task_id, {
          sourceReference: args.source_reference,
          provider: args.provider,
          requestedRevision: args.requested_revision,
          baseSpecRevision: args.base_spec_revision,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_resolutions",
      description: "List persisted fixed-revision resolution records for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.listModelSourceResolutions(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_bind_model_source",
      description: "Bind one resolved repository at the exact displayed commit and run bounded static analysis. Requires explicit user approval and never executes third-party code.",
      parameters: {
        task_id: { type: "string", required: true },
        resolution_id: { type: "string", required: true },
        expected_resolved_commit: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Bind fixed source for ${args.task_id}`, rawInput: args.expected_resolved_commit }),
      async execute(args, exec) {
        const result = await client.bindModelSource(args.task_id, args.resolution_id, {
          expectedResolvedCommit: args.expected_resolved_commit,
          baseSpecRevision: args.base_spec_revision,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_bindings",
      description: "List current, stale and historical model-source bindings for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.listModelBindings(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_repository_analysis",
      description: "Read one immutable static repository analysis, including evidence-backed entrypoint, metric, artifact and dependency candidates.",
      parameters: {
        task_id: { type: "string", required: true },
        analysis_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.repositoryAnalysis(args.task_id, args.analysis_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_create_training_plan",
      description: "Create an immutable training-plan proposal bound to the current TaskSpec, fixed source and analysis evidence. This proposes work but does not approve or execute it.",
      parameters: {
        task_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        entrypoint_path: { type: "string" },
        hyperparameters: { type: "object", additionalProperties: true },
        resource_budget: { type: "object", additionalProperties: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Propose training plan for ${args.task_id}`, rawInput: args.entrypoint_path || "analysis-selected entrypoint" }),
      async execute(args, exec) {
        const result = await client.createTrainingPlan(args.task_id, {
          baseSpecRevision: args.base_spec_revision,
          entrypointPath: args.entrypoint_path,
          hyperparameters: args.hyperparameters,
          resourceBudget: args.resource_budget,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_training_plan",
      description: "Read the current immutable training-plan revision and its exact digest and effective approval status.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.currentTrainingPlan(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_revise_training_plan",
      description: "Create a child training-plan revision from the exact current parent digest. Earlier approval never carries to the child revision.",
      parameters: {
        task_id: { type: "string", required: true },
        revision_id: { type: "string", required: true },
        expected_parent_sha256: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        entrypoint_path: { type: "string" },
        hyperparameters: { type: "object", additionalProperties: true },
        resource_budget: { type: "object", additionalProperties: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Revise training plan ${args.revision_id}`, rawInput: args.expected_parent_sha256 }),
      async execute(args, exec) {
        const result = await client.reviseTrainingPlan(args.task_id, args.revision_id, {
          expectedParentSha256: args.expected_parent_sha256,
          baseSpecRevision: args.base_spec_revision,
          entrypointPath: args.entrypoint_path,
          hyperparameters: args.hyperparameters,
          resourceBudget: args.resource_budget,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_decide_training_plan",
      description: "Approve, reject or cancel the exact displayed training-plan digest. Requires explicit user approval and never starts execution by itself.",
      parameters: {
        task_id: { type: "string", required: true },
        revision_id: { type: "string", required: true },
        expected_plan_sha256: { type: "string", required: true },
        decision: { type: "string", required: true, enum: ["approve", "reject", "cancel"] },
        reason: { type: "string", description: "Required for reject and cancel." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `${args.decision} training plan ${args.revision_id}`, rawInput: args.expected_plan_sha256 }),
      async execute(args, exec) {
        const result = await client.decideTrainingPlan(args.task_id, args.revision_id, {
          expectedPlanSha256: args.expected_plan_sha256,
          decision: args.decision,
          reason: args.reason,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_resource_feasibility",
      description: "Read the current resource probe, fit report and typed blockers for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.currentResourceFeasibility(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_check_resource_feasibility",
      description: "Probe the local machine and compare it with one exact approved plan under the v0.9 CPU-only isolation policy. This may return typed blockers instead of a fit report.",
      parameters: {
        task_id: { type: "string", required: true },
        training_plan_revision_id: { type: "string", required: true },
        expected_plan_sha256: { type: "string", required: true },
        base_image_digest: { type: "string" },
        packages: { type: "array", items: { type: "object", additionalProperties: true } },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Check local resources for ${args.task_id}`, rawInput: args.training_plan_revision_id }),
      async execute(args, exec) {
        const result = await client.checkResourceFeasibility(args.task_id, {
          trainingPlanRevisionId: args.training_plan_revision_id,
          expectedPlanSha256: args.expected_plan_sha256,
          baseImageDigest: args.base_image_digest,
          packages: args.packages,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_capability",
      description: "Read the installed Hugging Face capability boundary and dependency status. This does not search, download, attach, or train a model.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.huggingFaceCapability(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_search",
      description: "Search official Hugging Face metadata for candidate image feature models. Search results are not compatibility approval or attachment.",
      parameters: {
        query: { type: "string", required: true },
        pipeline_tag: { type: "string", description: "Optional official pipeline tag such as image-classification." },
        limit: { type: "integer", description: "Maximum results from 1 to 20; defaults to 10." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: (args) => ({ card: "generic", title: `Search Hugging Face: ${args.query}` }),
      async execute(args, exec) {
        return client.searchHuggingFaceModels(args.query, {
          pipelineTag: args.pipeline_tag,
          limit: args.limit === undefined ? 10 : args.limit,
        }, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_card",
      description: "Read one official Hugging Face model card at an optional immutable revision and expose Specialist Model Studio compatibility checks.",
      parameters: {
        repo_id: { type: "string", required: true },
        revision: { type: "string", description: "Prefer an exact 40-character commit SHA." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.huggingFaceModelCard(args.repo_id, args.revision, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_attach",
      description: "Download, verify and attach an approved public Hugging Face ONNX image feature asset at one immutable commit. This is not arbitrary fine-tuning and requires native approval.",
      parameters: {
        task_id: { type: "string", required: true },
        repo_id: { type: "string", required: true },
        commit: { type: "string", required: true, description: "Exact 40-character hexadecimal commit SHA." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Attach ${args.repo_id} to ${args.task_id}`, rawInput: args.commit }),
      async execute(args, exec) {
        const result = await client.attachHuggingFaceModel(
          args.task_id,
          args.repo_id,
          args.commit,
          args.approval_confirmed,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_verify",
      description: "Deep-verify the task's currently attached ModelAsset and its immutable file hashes before training.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.verifyTaskModelAsset(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_import_dataset",
      description: "Import and inspect a user-authorized local dataset through an installed Data Adapter. Built-ins accept class-folder image ZIP and CSV regression data. Ask before calling and never guess a path.",
      parameters: {
        task_id: { type: "string", required: true },
        dataset_path: { type: "string", required: true, description: "Absolute path or session-workspace-relative path explicitly provided by the user." },
        target_column: { type: "string", description: "Required for the built-in CSV regression adapter." },
        ignored_columns: { type: "array", items: { type: "string" }, description: "Optional CSV columns excluded from training." },
        delimiter: { type: "string", description: "Optional one-character CSV delimiter." },
        data_adapter: { type: "string", description: "Explicit adapter id when more than one can read the file." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Inspect dataset for ${args.task_id}`, rawInput: args.dataset_path }),
      async execute(args, exec) {
        const result = await client.importDataset(args.task_id, args.dataset_path, {
          targetColumn: args.target_column,
          ignoredColumns: args.ignored_columns,
          delimiter: args.delimiter,
          dataAdapter: args.data_adapter,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_scaffold_recipe",
      description: "Generate a reviewable Code Agent build packet for a task in needs_recipe. This does not execute or register generated code.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Generate Recipe build packet for ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.scaffoldRecipe(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_stage_recipe_samples",
      description: "Stage and safely inspect a user-authorized class-folder WAV ZIP as Recipe construction evidence. This does not create a formal dataset or start training.",
      parameters: {
        task_id: { type: "string", required: true },
        sample_path: { type: "string", required: true, description: "User-provided local .zip path." },
        spec_revision: { type: "integer", description: "Current immutable TaskSpec revision for optimistic concurrency." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Stage Recipe samples for ${args.task_id}`, rawInput: args.sample_path }),
      async execute(args, exec) {
        const result = await client.stageRecipeSamples(
          args.task_id,
          args.sample_path,
          args.spec_revision,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_build_recipe",
      description: "Compile and validate the trusted declarative audio-keyword Recipe from staged samples. It cannot execute Python, install dependencies, or register itself.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Build and validate Recipe for ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.startRecipeBuild(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_recipe_build",
      description: "Read one immutable Recipe build candidate and its validation evidence before an approval decision.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.getRecipeBuild(args.task_id, args.attempt_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_register_recipe",
      description: "Atomically register an already validated declarative Recipe candidate. Requires the exact candidate and validation digests plus explicit human approval.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
        candidate_digest: { type: "string", required: true },
        validation_digest: { type: "string", required: true },
        actor: { type: "string", required: true, description: "Human approver identity; never fabricate this value." },
        reason: { type: "string", description: "Optional human review note." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Approve Recipe registration ${args.attempt_id}` }),
      async execute(args, exec) {
        const result = await client.registerRecipeBuild(args.task_id, args.attempt_id, {
          candidateDigest: args.candidate_digest,
          validationDigest: args.validation_digest,
          actor: args.actor,
          reason: args.reason,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_reject_recipe",
      description: "Reject a Recipe candidate with a human reason. Rejection never changes the installed Recipe registry.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
        actor: { type: "string", required: true },
        reason: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        const result = await client.rejectRecipeBuild(
          args.task_id,
          args.attempt_id,
          args.actor,
          args.reason,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_configure_contract",
      description: "Update explicit offline acceptance gates or image size on an inspected task. This invalidates prior confirmation. Do not lower gates merely to make a run pass.",
      parameters: {
        task_id: { type: "string", required: true },
        accuracy_min: { type: "number", description: "Required clean-test Accuracy from 0 to 1." },
        macro_f1_min: { type: "number", description: "Required clean-test Macro-F1 from 0 to 1." },
        worst_class_recall_min: { type: "number", description: "Required worst-class Recall from 0 to 1." },
        mae_max: { type: "number", description: "Maximum independent-test MAE for regression." },
        rmse_max: { type: "number", description: "Maximum independent-test RMSE for regression." },
        r2_min: { type: "number", description: "Minimum independent-test R-squared for regression." },
        image_size: { type: "integer", enum: [16, 24, 32, 48, 64], description: "Square feature-extraction image size." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Configure training contract ${args.task_id}`, rawInput: JSON.stringify(args) }),
      async execute(args, exec) {
        if ([args.accuracy_min, args.macro_f1_min, args.worst_class_recall_min, args.mae_max, args.rmse_max, args.r2_min, args.image_size].every((value) => value === undefined)) {
          throw new Error("At least one contract field must be provided");
        }
        const result = await client.configureContract(args.task_id, {
          accuracyMin: args.accuracy_min,
          macroF1Min: args.macro_f1_min,
          worstClassRecallMin: args.worst_class_recall_min,
          maeMax: args.mae_max,
          rmseMax: args.rmse_max,
          r2Min: args.r2_min,
          imageSize: args.image_size,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_confirm_contract",
      description: "Record the user's three explicit confirmations for data authorization, label meaning, and offline gates. Never infer or self-approve these confirmations.",
      parameters: {
        task_id: { type: "string", required: true },
        data_authorized: { type: "boolean", const: true, required: true },
        labels_reviewed: { type: "boolean", const: true, required: true },
        gates_reviewed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Confirm training contract ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.confirmContract(args.task_id, args, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_start_task_run",
      description: "Start a real background training run for a confirmed user-data task. Call only after task state proves the three confirmations are recorded.",
      parameters: {
        task_id: { type: "string", required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Start real training for ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.startTaskRun(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_recipes",
      description: "List the specialist-model training Recipes currently implemented by the local Specialist Model Studio engine.",
      parameters: {},
      output: jsonOutput,
      async execute(_args, exec) {
        return client.recipes(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_apply_task_strategy",
      description: "Apply one actionable strategy to a task-owned completed run, creating a child run without replacing the parent. Requires the user's explicit approval of the named strategy.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        strategy_id: { type: "string", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Apply ${args.strategy_id} to ${args.run_id}` }),
      async execute(args, exec) {
        const result = await client.applyTaskStrategy(
          args.task_id,
          args.run_id,
          args.strategy_id,
          args.approval_confirmed,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_start_run",
      description: "Start an auditable specialist-model training run from an implemented Recipe. This creates a persistent run and returns its run_id.",
      parameters: {
        recipe: {
          type: "string",
          enum: ["digit-classification"],
          description: "Implemented Recipe id. The current built-in Recipe is teaching-only.",
        },
        business_goal: { type: "string", description: "Optional user-visible goal copied into the frozen task contract." },
        task_id: { type: "string", description: "Optional stable task label." },
        run_id: { type: "string", description: "Optional caller-selected run id." },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.startRun({
          recipe: args.recipe,
          businessGoal: args.business_goal,
          taskId: args.task_id,
          runId: args.run_id,
          signal: exec.signal,
        });
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_run",
      description: "Get canonical state, metrics, optimization history and lineage for one persistent training run.",
      parameters: {
        run_id: { type: "string", required: true, description: "Run id returned by model_harness_start_run." },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.status(args.run_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_evaluation_report",
      description: "Read the task-owned EvaluationReport and its separate run, integrity, metric-gate, evidence and conclusion dimensions.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.evaluationReport(args.task_id, args.run_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_run_sample_inference",
      description: "Run one explicit, user-authorized raw image, 16 kHz mono PCM WAV, or one-row JSON/CSV sample against a completed task-owned Run. This persists auditable inference evidence and never selects a training/test sample automatically.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        sample_path: { type: "string", required: true, description: "Local path explicitly provided by the user." },
        sample_type: { type: "string", required: true, enum: ["image", "audio", "tabular"] },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Try a new ${args.sample_type} sample on ${args.run_id}`, rawInput: args.sample_path }),
      async execute(args, exec) {
        const result = await client.runSampleInference(
          args.task_id,
          args.run_id,
          args.sample_path,
          args.sample_type,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_sample_inferences",
      description: "List persisted raw-sample inference checks for one task-owned Run.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.listSampleInferences(args.task_id, args.run_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_sample_inference",
      description: "Read one persisted raw-sample inference inspection and its hash-bound prediction evidence.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        check_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.getSampleInference(
          args.task_id,
          args.run_id,
          args.check_id,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_build_artifact_bundle",
      description: "Build a privacy-filtered, hashed Artifact Bundle from a task-owned Run and optional trusted inference check. Raw data, test references, absolute paths and internal state remain excluded.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        sample_inference_check_id: { type: "string", description: "Passed raw sample check to include as inference evidence." },
        inference_check_id: { type: "string", description: "Alternative low-level trusted inference check; mutually exclusive with sample_inference_check_id." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Build Artifact Bundle for ${args.run_id}` }),
      async execute(args, exec) {
        const result = await client.buildArtifactBundle(args.task_id, args.run_id, {
          sampleInferenceCheckId: args.sample_inference_check_id,
          inferenceCheckId: args.inference_check_id,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_artifact_bundles",
      description: "List privacy-filtered Artifact Bundles already built for one task-owned Run.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.listArtifactBundles(args.task_id, args.run_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_artifact_bundle",
      description: "Read one Artifact Bundle manifest, privacy boundary, hashes and download metadata without returning host filesystem paths.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        bundle_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.getArtifactBundle(
          args.task_id,
          args.run_id,
          args.bundle_id,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_download_artifact_bundle",
      description: "Download one Artifact Bundle through its real task-owned API, verify the manifest SHA-256, and create a new user-selected local .zip file. Existing files are never overwritten.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        bundle_id: { type: "string", required: true },
        destination_path: { type: "string", required: true, description: "New local .zip destination explicitly selected by the user." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Download Artifact Bundle ${args.bundle_id}`, rawInput: args.destination_path }),
      async execute(args, exec) {
        return client.downloadArtifactBundle(
          args.task_id,
          args.run_id,
          args.bundle_id,
          args.destination_path,
          exec.signal,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_events",
      description: "Read versioned run events after a sequence number. Use this to explain current progress without inventing state.",
      parameters: {
        run_id: { type: "string", required: true },
        after_seq: { type: "integer", description: "Return only events with a larger sequence number." },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.events(args.run_id, args.after_seq || 0, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_strategies",
      description: "Get evidence-linked optimization strategies for a completed run. Recommendations are not approvals.",
      parameters: {
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.strategies(args.run_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_apply_strategy",
      description: "Apply one actionable optimization strategy by creating a child run. Call only after the user explicitly approves the named strategy.",
      parameters: {
        run_id: { type: "string", required: true, description: "Completed parent run id." },
        strategy_id: { type: "string", required: true, description: "Exact strategy id returned by model_harness_get_strategies." },
        approval_confirmed: {
          type: "boolean",
          const: true,
          required: true,
          description: "Must be true only after explicit user approval.",
        },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.applyStrategy(
          args.run_id,
          args.strategy_id,
          args.approval_confirmed,
          exec.signal,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_cancel_run",
      description: "Request cooperative cancellation of a task-owned active run. This never cancels the Agent conversation.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.cancelTaskRun(args.task_id, args.run_id, exec.signal);
      },
    }),
  );

  ctx.on("tools/pre-execute", async (exec, next) => {
    const decision = await next();
    if (decision.kind !== "allow" || !APPROVAL_REQUIRED_TOOLS.has(exec.name)) {
      return decision;
    }
    return {
      kind: "ask",
      reason: `Model-training action ${exec.name} changes local task, data, compute, or approval state.`,
    };
  });
}
