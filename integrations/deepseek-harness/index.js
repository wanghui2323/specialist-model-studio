import { defineTool } from "@deepseek-ai/dsh-tools";

import { ModelHarnessClient } from "./client.js";

export const name = "ai-pm-model-harness-tools";
export const inject = ["tools", "systemPrompt"];

const APPROVAL_REQUIRED_TOOLS = new Set([
  "model_harness_import_dataset",
  "model_harness_configure_contract",
  "model_harness_confirm_contract",
  "model_harness_start_task_run",
  "model_harness_start_run",
  "model_harness_apply_task_strategy",
  "model_harness_apply_strategy",
  "model_harness_cancel_run",
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
The user-data workflow is: list or create a persistent task; ask for a local ZIP path organized as class/image; import and explain the inspection report; ask the user to review labels and acceptance gates; configure only requested changes; obtain explicit data_authorized, labels_reviewed, and gates_reviewed confirmations; start the task run; poll canonical events/results; explain failures and strategies; apply an actionable strategy only after explicit approval.
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
      name: "model_harness_create_task",
      description: "Create one persistent user-data model-training task after the user has described a concrete business goal. This creates a draft only; it does not train a model.",
      parameters: {
        name: { type: "string", required: true, description: "Short user-facing task name." },
        business_goal: { type: "string", required: true, description: "Concrete outcome and prediction target in the user's words." },
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
      name: "model_harness_import_dataset",
      description: "Import and inspect a user-authorized local image dataset ZIP into an existing task. The ZIP must use class/image files. Ask before calling and never guess a path.",
      parameters: {
        task_id: { type: "string", required: true },
        dataset_zip_path: { type: "string", required: true, description: "Absolute path or session-workspace-relative path to the ZIP explicitly provided by the user." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Inspect dataset for ${args.task_id}`, rawInput: args.dataset_zip_path }),
      async execute(args, exec) {
        const result = await client.importDataset(args.task_id, args.dataset_zip_path, exec.signal);
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
        image_size: { type: "integer", enum: [16, 24, 32, 48, 64], description: "Square feature-extraction image size." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Configure training contract ${args.task_id}`, rawInput: JSON.stringify(args) }),
      async execute(args, exec) {
        if ([args.accuracy_min, args.macro_f1_min, args.worst_class_recall_min, args.image_size].every((value) => value === undefined)) {
          throw new Error("At least one contract field must be provided");
        }
        const result = await client.configureContract(args.task_id, {
          accuracyMin: args.accuracy_min,
          macroF1Min: args.macro_f1_min,
          worstClassRecallMin: args.worst_class_recall_min,
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
      description: "List the specialist-model training Recipes currently implemented by the local AI PM Model Harness.",
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
      description: "Request cooperative cancellation of an active run. Cancellation becomes final at a safe stage boundary.",
      parameters: {
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.cancel(args.run_id, exec.signal);
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
