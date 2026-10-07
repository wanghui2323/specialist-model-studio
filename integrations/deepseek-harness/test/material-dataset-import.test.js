import assert from "node:assert/strict";
import { test } from "node:test";
import { ModelHarnessClient } from "../client.js";
import { apply, ROLE_TOOL_ALLOWLISTS } from "../index.js";

const TASK = "task-material-import", MATERIAL = "material-0123456789abcdef01234567", DIGEST = "a".repeat(64);
const reply = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
function receipt(body, revision = body.base_spec_revision) {
  return { task: { task_id: TASK, current_spec_revision: revision, dataset_id: "dataset-real", contract_confirmed: false, current_run_id: null },
    dataset_upload: { task_id: TASK, request_id: body.request_id, dataset_id: "dataset-real", status: "completed", options: body.options }, idempotent_replay: false };
}
function mount() {
  const tools = [], listeners = new Map();
  apply({ tools: { register(tool) { tools.push(tool); } }, systemPrompt: { section() {} }, on(name, listener) { listeners.set(name, listener); } });
  return { tool: tools.find(tool => tool.name === "model_harness_import_material_dataset"), pre: listeners.get("tools/pre-execute") };
}

test("CSV and ZIP imports reuse retained material through JSON with stable revision-scoped request IDs", async () => {
  const originalFetch = globalThis.fetch, requests = [], client = new ModelHarnessClient(), signal = new AbortController().signal;
  let revision = 3;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (options.method === "GET") return reply({ task: { task_id: TASK, current_spec_revision: revision } });
    return reply(receipt(JSON.parse(options.body)), 201);
  };
  try {
    const csv = { baseSpecRevision: 3, targetColumn: "房价", ignoredColumns: ["编号"], delimiter: ",", dataAdapter: "csv-tabular-regression" };
    const first = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, csv, signal);
    const second = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, csv, signal);
    assert.equal(first.dataset_upload.request_id, second.dataset_upload.request_id);
    const changedColumn = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, { ...csv, targetColumn: "租金" }, signal);
    assert.notEqual(first.dataset_upload.request_id, changedColumn.dataset_upload.request_id);
    revision = 4;
    const changedRevision = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, { ...csv, baseSpecRevision: 4 }, signal);
    assert.notEqual(first.dataset_upload.request_id, changedRevision.dataset_upload.request_id);
    const zipped = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 4, dataAdapter: "image-folder" }, signal);
    assert.equal(zipped.task.current_run_id, null);
    assert.equal(zipped.task.contract_confirmed, false);
    const posts = requests.filter(request => request.options.method === "POST");
    assert.equal(posts.length, 5);
    assert.deepEqual(JSON.parse(posts[0].options.body).options, { target_column: "房价", ignored_columns: ["编号"], delimiter: ",", data_adapter: "csv-tabular-regression" });
    assert.deepEqual(JSON.parse(posts.at(-1).options.body).options, { data_adapter: "image-folder" });
    for (const request of posts) {
      assert.equal(new URL(request.url).pathname, `/tasks/${TASK}/dataset-from-material`);
      assert.equal(request.options.headers["Content-Type"], "application/json");
      assert.equal(request.options.headers["X-Model-Harness-Projection"], "agent-v1");
      assert.equal(request.options.signal, signal);
      const body = JSON.parse(request.options.body);
      assert.equal(body.material_id, MATERIAL); assert.equal(body.inspection_sha256, DIGEST);
      assert.match(body.request_id, /^material-dataset-[0-9a-f]{64}$/);
      assert.equal("dataset_path" in body, false); assert.equal("X-Filename" in request.options.headers, false);
    }
    assert.deepEqual(requests.map(request => request.options.method), Array.from({ length: 5 }, () => ["GET", "POST"]).flat());
  } finally { globalThis.fetch = originalFetch; }
});

test("foreign task identities and stale revisions cannot issue a new material import", async () => {
  const originalFetch = globalThis.fetch, client = new ModelHarnessClient();
  try {
    for (const task of [{ task_id: "foreign", current_spec_revision: 3 }, { task_id: TASK, current_spec_revision: null }, { task_id: TASK, current_spec_revision: 4 }]) {
      const requests = [];
      globalThis.fetch = async (url, options) => {
        requests.push({ url, options });
        return new URL(url).pathname.includes("dataset-upload-receipts") ? reply({ detail: "No matching import receipt" }, 404) : reply({ task });
      };
      await assert.rejects(client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 3 }));
      assert.ok(requests.every(request => request.options.method === "GET"));
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("lost import response can be reconciled after the import itself advances the spec revision", async () => {
  const originalFetch = globalThis.fetch, client = new ModelHarnessClient(), requests = [];
  let imported;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (options.method === "POST") {
      imported = receipt(JSON.parse(options.body), 4);
      throw new Error("connection lost after commit");
    }
    if (new URL(url).pathname.includes("dataset-upload-receipts")) {
      assert.ok(url.endsWith(imported.dataset_upload.request_id));
      return reply(imported);
    }
    return reply({ task: { task_id: TASK, current_spec_revision: imported ? 4 : 3, dataset_id: imported ? "dataset-real" : null } });
  };
  try {
    await assert.rejects(client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 3 }), /connection lost/);
    const recovered = await client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 3 });
    assert.equal(recovered.idempotent_replay, true);
    assert.equal(recovered.dataset_upload.request_id, imported.dataset_upload.request_id);
    assert.equal(requests.filter(request => request.options.method === "POST").length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test("a material import needs exactly one native root approval and remains forbidden to data specialists", async () => {
  const { tool, pre } = mount(), originalFetch = globalThis.fetch;
  const args = { task_id: TASK, material_id: MATERIAL, inspection_sha256: DIGEST, base_spec_revision: 3, target_column: "price" };
  const agent = { session: { header: { id: "root" }, events: [] } };
  let nativeGates = 0, posts = 0;
  globalThis.fetch = async (url, options) => {
    if (options.method === "GET") return reply({ task: { task_id: TASK, current_spec_revision: 3 } });
    posts++;
    return reply({ ...receipt(JSON.parse(options.body)), object_refs: [{ type: "task_spec", id: "spec-3", task_id: TASK, revision: 3 }] });
  };
  try {
    const decision = await pre({ name: tool.name, agent, arguments: args }, async () => { nativeGates++; return { kind: "allow" }; });
    assert.equal(decision.kind, "ask"); assert.match(decision.reason, /已上传且检查过/);
    const result = await tool.execute(args, { agent });
    assert.equal(nativeGates, 1); assert.equal(posts, 1);
    assert.equal(result.dataset_upload.status, "completed");
    assert.equal(result.object_refs[0].task_id, TASK);
    assert.ok(result.workbench_url.includes(TASK));
    const specialist = { session: { header: { id: "data", origin: "subagent", parentSession: "root", seedLength: 0 }, events: [
      { type: "subagent/descriptor", data: { version: 2, mode: "continuable", provider: "spawn", toolFilter: { allow: ROLE_TOOL_ALLOWLISTS.data_experiment } } },
    ] } };
    assert.equal((await pre({ name: tool.name, agent: specialist, arguments: args }, async () => ({ kind: "allow" }))).kind, "deny");
    const priorDenial = { kind: "deny", reason: "denied upstream" };
    assert.equal(await pre({ name: tool.name, agent, arguments: args }, async () => priorDenial), priorDenial);
  } finally { globalThis.fetch = originalFetch; }
});

test("foreign material-import receipts, mismatched datasets and revision-race responses remain failures", async () => {
  const originalFetch = globalThis.fetch, client = new ModelHarnessClient();
  try {
    for (const mutate of [
      value => { value.task.task_id = "foreign"; },
      value => { value.dataset_upload.task_id = "foreign"; },
      value => { value.dataset_upload.request_id = "foreign"; },
      value => { value.dataset_upload.dataset_id = "foreign"; },
      value => { value.dataset_upload.status = "processing"; },
      value => { value.object_refs = [{ task_id: "foreign" }]; },
    ]) {
      globalThis.fetch = async (_url, options) => {
        if (options.method === "GET") return reply({ task: { task_id: TASK, current_spec_revision: 3 } });
        const value = receipt(JSON.parse(options.body)); mutate(value); return reply(value);
      };
      await assert.rejects(client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 3 }), /invalid canonical task or dataset receipt/);
    }
    globalThis.fetch = async (_url, options) => options.method === "GET"
      ? reply({ task: { task_id: TASK, current_spec_revision: 3 } }) : reply({ detail: "Task spec revision changed" }, 409);
    await assert.rejects(client.importMaterialDataset(TASK, MATERIAL, DIGEST, { baseSpecRevision: 3 }), /409: Task spec revision changed/);
  } finally { globalThis.fetch = originalFetch; }
});
