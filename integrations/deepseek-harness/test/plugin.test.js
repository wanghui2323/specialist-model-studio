import assert from "node:assert/strict";
import { test } from "node:test";

import { apply, inject } from "../index.js";


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
  assert.equal(names.size, 18);
  for (const required of [
    "model_harness_list_tasks",
    "model_harness_list_data_adapters",
    "model_harness_match_capability",
    "model_harness_create_task",
    "model_harness_get_task",
    "model_harness_import_dataset",
    "model_harness_scaffold_recipe",
    "model_harness_configure_contract",
    "model_harness_confirm_contract",
    "model_harness_start_task_run",
    "model_harness_get_events",
    "model_harness_get_run",
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

  const priorDenial = { kind: "deny", reason: "policy" };
  assert.deepEqual(
    await listener(
      { name: "model_harness_import_dataset" },
      async () => priorDenial,
    ),
    priorDenial,
  );
});
