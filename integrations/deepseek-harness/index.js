import { defineTool } from "@deepseek-ai/dsh-tools";

import { ModelHarnessClient } from "./client.js";

export const name = "ai-pm-model-harness-tools";
export const inject = ["tools"];

const jsonOutput = {
  schema: { type: "json" },
  render: (_args, value) => [
    { type: "text", text: JSON.stringify(value, null, 2) },
  ],
};

export function apply(ctx) {
  const client = new ModelHarnessClient();

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
}
