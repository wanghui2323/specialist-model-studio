import assert from "node:assert/strict";
import { test } from "node:test";

import { apply, inject, TASK_FAMILIES } from "../index.js";


function mountPlugin() {
  const tools = [];
  const sections = [];
  const listeners = new Map();
  const ctx = {
    tools: { register(tool) { tools.push(tool); } },
    systemPrompt: { section(value) { sections.push(value); } },
    on(name, handler) { listeners.set(name, handler); },
  };
  apply(ctx);
  return { tools, sections, listeners };
}


test("plugin registers the complete task-first conversational toolchain", () => {
  const mounted = mountPlugin();
  assert.deepEqual(inject, ["tools", "systemPrompt"]);
  const names = new Set(mounted.tools.map((tool) => tool.name));
  assert.equal(names.size, 37);
  for (const required of [
    "model_harness_list_tasks",
    "model_harness_list_data_adapters",
    "model_harness_match_capability",
    "model_harness_create_task",
    "model_harness_update_task_spec",
    "model_harness_get_task",
    "model_harness_hf_capability",
    "model_harness_hf_search",
    "model_harness_hf_card",
    "model_harness_hf_attach",
    "model_harness_hf_verify",
    "model_harness_import_dataset",
    "model_harness_scaffold_recipe",
    "model_harness_stage_recipe_samples",
    "model_harness_build_recipe",
    "model_harness_get_recipe_build",
    "model_harness_register_recipe",
    "model_harness_reject_recipe",
    "model_harness_configure_contract",
    "model_harness_confirm_contract",
    "model_harness_start_task_run",
    "model_harness_get_events",
    "model_harness_get_run",
    "model_harness_get_evaluation_report",
    "model_harness_run_sample_inference",
    "model_harness_list_sample_inferences",
    "model_harness_get_sample_inference",
    "model_harness_build_artifact_bundle",
    "model_harness_list_artifact_bundles",
    "model_harness_get_artifact_bundle",
    "model_harness_download_artifact_bundle",
    "model_harness_apply_task_strategy",
  ]) {
    assert.equal(names.has(required), true, `missing ${required}`);
  }
  assert.equal(
    mounted.sections.some((section) => section.name === "domain:model-training-harness"),
    true,
  );
  assert.match(mounted.sections[0].text, /You are the Model Training Agent/);
  assert.match(mounted.sections[0].text, /workbench_url/);
  assert.match(mounted.sections[0].text, /EvaluationReport/);
  assert.match(mounted.sections[0].text, /40-character commit/);
});


test("task-spec update exposes every canonical specialist family", () => {
  const mounted = mountPlugin();
  const updateTool = mounted.tools.find(
    (tool) => tool.name === "model_harness_update_task_spec",
  );
  assert.ok(updateTool);
  assert.deepEqual(
    updateTool.parameters.properties.selected_family.enum,
    [...TASK_FAMILIES],
  );
  assert.deepEqual(
    [...TASK_FAMILIES],
    [
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
    ],
  );
});


test("mutating training tools use the native DSH approval seam", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  assert.equal(typeof listener, "function");
  const readDecision = await listener(
    { name: "model_harness_get_task" },
    async () => ({ kind: "allow" }),
  );
  assert.deepEqual(readDecision, { kind: "allow" });

  const mutationDecision = await listener(
    { name: "model_harness_start_task_run" },
    async () => ({ kind: "allow" }),
  );
  assert.equal(mutationDecision.kind, "ask");
  assert.match(mutationDecision.reason, /changes local task/);

  const recipeApproval = await listener(
    { name: "model_harness_register_recipe" },
    async () => ({ kind: "allow" }),
  );
  assert.equal(recipeApproval.kind, "ask");

  for (const toolName of [
    "model_harness_hf_attach",
    "model_harness_run_sample_inference",
    "model_harness_build_artifact_bundle",
    "model_harness_download_artifact_bundle",
  ]) {
    const decision = await listener(
      { name: toolName },
      async () => ({ kind: "allow" }),
    );
    assert.equal(decision.kind, "ask", `${toolName} must use native approval`);
  }

  const priorDenial = { kind: "deny", reason: "policy" };
  assert.deepEqual(
    await listener(
      { name: "model_harness_import_dataset" },
      async () => priorDenial,
    ),
    priorDenial,
  );
});
