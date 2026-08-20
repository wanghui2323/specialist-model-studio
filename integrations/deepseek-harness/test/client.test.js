import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, test } from "node:test";

import { ModelHarnessClient } from "../client.js";

const baseUrl = "http://127.0.0.1:8765";
const requests = [];
const originalFetch = globalThis.fetch;

beforeEach(() => {
  requests.length = 0;
  globalThis.fetch = async (url, options = {}) => {
    const requestUrl = new URL(url);
    const body = options.body || "";
    requests.push({
      method: options.method || "GET",
      url: `${requestUrl.pathname}${requestUrl.search}`,
      body,
      headers: Object.fromEntries(new Headers(options.headers || {}).entries()),
    });
    const isJson = new Headers(options.headers || {}).get("content-type") === "application/json";
    const value = requestUrl.pathname === "/recipes/digit-classification/template"
      ? { contract: { recipe: "digit-classification", task_id: "default", business_goal: "default" } }
      : requestUrl.pathname === "/tasks" && (options.method || "GET") === "POST"
        ? { task: { task_id: "real-task-123" } }
        : { ok: true, request_body: body && isJson ? JSON.parse(body) : null };
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});

after(() => {
  globalThis.fetch = originalFetch;
});

test("startRun freezes caller overrides into submitted contract", async () => {
  const client = new ModelHarnessClient(baseUrl);
  const result = await client.startRun({
    recipe: "digit-classification",
    businessGoal: "teaching goal",
    taskId: "dsh-lab",
  });
  assert.equal(result.ok, true);
  const submitted = requests.at(-1);
  assert.equal(submitted.url, "/runs");
  assert.equal(JSON.parse(submitted.body).contract.business_goal, "teaching goal");
  assert.equal(JSON.parse(submitted.body).contract.task_id, "dsh-lab");
});

test("applyStrategy requires and forwards explicit approval", async () => {
  const client = new ModelHarnessClient(baseUrl);
  assert.throws(
    () => client.applyStrategy("parent", "strategy", false),
    /Explicit user approval/,
  );
  const result = await client.applyStrategy("parent", "strategy", true);
  assert.equal(result.ok, true);
  const submitted = requests.at(-1);
  assert.equal(
    submitted.url,
    "/runs/parent/strategies/strategy/apply",
  );
  assert.deepEqual(JSON.parse(submitted.body), { approval_confirmed: true });
});

test("task lifecycle methods preserve canonical task routes and confirmations", async () => {
  const client = new ModelHarnessClient(baseUrl);
  const created = await client.createTask("parts", "classify parts", undefined);
  assert.equal(created.task.task_id, "real-task-123");
  assert.equal(requests.at(-1).url, "/tasks");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    name: "parts",
    business_goal: "classify parts",
  });

  await client.configureContract("real-task-123", {
    accuracyMin: 0.82,
    macroF1Min: 0.78,
    worstClassRecallMin: 0.6,
    imageSize: 32,
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/contract");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    release_gates: {
      clean_test_accuracy_min: 0.82,
      clean_test_macro_f1_min: 0.78,
      clean_test_worst_class_recall_min: 0.6,
    },
    recipe_options: { image_size: 32 },
  });

  assert.throws(
    () => client.confirmContract("real-task-123", { data_authorized: true }),
    /three human confirmations/,
  );
  await client.confirmContract("real-task-123", {
    data_authorized: true,
    labels_reviewed: true,
    gates_reviewed: true,
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/confirm");

  await client.startTaskRun("real-task-123");
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/runs");
  assert.equal(requests.at(-1).method, "POST");

  await client.applyTaskStrategy("real-task-123", "parent-run", "balance", true);
  assert.equal(
    requests.at(-1).url,
    "/tasks/real-task-123/runs/parent-run/strategies/balance/apply",
  );
});

test("importDataset reads the approved local ZIP and preserves its filename", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-dsh-"));
  try {
    const datasetPath = join(temp, "零件图片.zip");
    await writeFile(datasetPath, Buffer.from("zip-test-payload"));
    const client = new ModelHarnessClient(baseUrl);
    await client.importDataset("task-one", datasetPath);
    const submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/task-one/dataset");
    assert.equal(submitted.method, "POST");
    assert.equal(submitted.headers["content-type"], "application/zip");
    assert.equal(decodeURIComponent(submitted.headers["x-filename"]), "零件图片.zip");
    assert.equal(Buffer.from(submitted.body).toString(), "zip-test-payload");
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
