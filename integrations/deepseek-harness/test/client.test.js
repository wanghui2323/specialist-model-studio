import assert from "node:assert/strict";
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
    });
    const value = requestUrl.pathname === "/recipes/digit-classification/template"
      ? { contract: { recipe: "digit-classification", task_id: "default", business_goal: "default" } }
      : { ok: true, request_body: body ? JSON.parse(body) : null };
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
