import assert from "node:assert/strict";
import { test } from "node:test";
import { apply } from "../index.js";
import { ModelHarnessClient, publicProjection } from "../client.js";

function mount() {
  const tools = [], listeners = new Map();
  apply({ tools: { register(tool) { tools.push(tool); } }, systemPrompt: { section() {} }, on(name, listener) { listeners.set(name, listener); } });
  return { tools, listeners };
}
function response(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

test("material clients keep the exact owner and material identity in encoded GET routes with agent projection", async () => {
  const client = new ModelHarnessClient("http://localhost:8765");
  const originalFetch = globalThis.fetch, calls = [], signal = new AbortController().signal;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    const parsed = new URL(url), owner = decodeURIComponent(parsed.pathname.split("/")[2]);
    const receipt = { owner_id: owner, material_id: "material-a%1", data_inspected_only: true, dataset_imported: false, execution_authorized: false };
    return response(parsed.pathname.endsWith("/materials") ? { materials: [receipt] } : parsed.pathname.endsWith("/agent-context") ? { owner: { owner_id: owner } } : { material: receipt });
  };
  try {
    const owner = "task-中文", material = "material-a%1";
    await client.listMaterials(owner, signal);
    await client.getMaterial(owner, material, signal);
    await client.rootContext(owner, signal);
    assert.deepEqual(calls.map(call => new URL(call.url).pathname), [
      `/conversations/${encodeURIComponent(owner)}/materials`,
      `/conversations/${encodeURIComponent(owner)}/materials/${encodeURIComponent(material)}`,
      `/conversations/${encodeURIComponent(owner)}/agent-context`,
    ]);
    assert.equal(new URL(calls[1].url).search, "?view=agent");
    for (const call of calls) {
      assert.equal(call.options.method, "GET");
      assert.equal(call.options.signal, signal);
      assert.equal(call.options.body, undefined);
      assert.equal(call.options.headers["X-Model-Harness-Projection"], "agent-v1");
      assert.equal("X-Model-Harness-Agent-Token" in call.options.headers, false);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("root material tools execute before task binding and return inspected evidence without importing or authorizing", async () => {
  const { tools, listeners } = mount(), requests = [], originalFetch = globalThis.fetch;
  assert.equal(typeof listeners.get("agent/pre-step"), "function", "the shipped entrypoint installs the native facts-refresh hook");
  const owner = "task-unbound", material = "material-012345678901234567890123";
  const receipt = { owner_id: owner, material_id: material, status: "inspected", untrusted_content: true, data_inspected_only: true,
    dataset_imported: false, execution_authorized: false, report: { facts: { row_count: 12 }, source_path: "/Users/private/data.csv" } };
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return response(new URL(url).pathname.endsWith("/materials") ? { materials: [receipt] } : { material: receipt }); };
  try {
    const agent = { session: { header: { id: "root" }, events: [] } };
    for (const name of ["model_harness_list_materials", "model_harness_get_material"]) {
      const tool = tools.find(value => value.name === name);
      const args = { owner_id: owner, ...(name.endsWith("get_material") ? { material_id: material } : {}) };
      assert.ok(tool); assert.equal(tool.isConcurrencySafe(args), true);
      const decision = await listeners.get("tools/pre-execute")({ name, agent, arguments: args }, async () => ({ kind: "allow" }));
      assert.equal(decision.kind, "allow");
      const result = await tool.execute(args, { agent });
      const observed = result.material || result.materials[0];
      assert.equal(observed.owner_id, owner); assert.equal(observed.material_id, material);
      assert.equal(observed.dataset_imported, false); assert.equal(observed.execution_authorized, false);
      assert.equal(observed.untrusted_content, true);
      assert.equal("source_path" in observed.report, false);
    }
    assert.equal(requests.length, 2);
    assert.ok(requests.every(value => value.options.method === "GET"));
    assert.equal(new URL(requests[1].url).search, "?view=agent");
  } finally { globalThis.fetch = originalFetch; }
});

test("a missing or wrong-owner material read propagates the real server error without a fake empty report", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => response({ detail: "Material belongs to another owner" }, 404);
  try {
    const client = new ModelHarnessClient();
    await assert.rejects(client.getMaterial("task-wrong", "material-real"), /Specialist Model Studio 404: Material belongs to another owner/);
  } finally { globalThis.fetch = originalFetch; }
});

test("successful HTTP responses still need exact material owner identity and inspection-only scope", async () => {
  const originalFetch = globalThis.fetch, client = new ModelHarnessClient();
  const receipt = { owner_id: "task-1", material_id: "material-1", data_inspected_only: true, dataset_imported: false, execution_authorized: false };
  try {
    for (const override of [{ owner_id: "foreign" }, { material_id: "foreign" }, { data_inspected_only: false }, { dataset_imported: true }, { execution_authorized: true }]) {
      globalThis.fetch = async () => response({ material: { ...receipt, ...override } });
      await assert.rejects(client.getMaterial("task-1", "material-1"), /Material report identity or inspection scope mismatch/);
    }
    for (const value of [{}, { materials: [{ ...receipt, owner_id: "foreign" }] }]) {
      globalThis.fetch = async () => response(value);
      await assert.rejects(client.listMaterials("task-1"), /Material list owner identity mismatch/);
    }
  } finally { globalThis.fetch = originalFetch; }
});


test("material prose preserves field separators while actual host locations stay private", () => {
  const source = {note: '字段 `day_of_week`/`is_weekend`，标签「退货」/「退款」，时间/分组；缓存位于 /tmp/private/data.csv', path: '/Users/person/private/data.csv'};
  const value = publicProjection(source);
  assert.match(value.note, /`day_of_week`\/`is_weekend`/);
  assert.match(value.note, /「退货」\/「退款」/);
  assert.match(value.note, /时间\/分组/);
  assert.doesNotMatch(value.note, /\/tmp\/private/);
  assert.equal('path' in value, false);
});

test("embedded host paths stay private next to Chinese and in file URIs", () => {
  const value = publicProjection({note:"路径/Users/person/private.csv；打开 file:///tmp/private.csv 或 ~/private.csv"});
  assert.doesNotMatch(value.note, /\/Users\/person|\/tmp\/private|~\/private/);
  assert.match(value.note, /\[local-path-redacted\]/);
});

test("task promotion offers canonical naming hints while accepting open capability axes", () => {
  const tool = mount().tools.find(item => item.name === "model_harness_promote_conversation");
  const shape = tool.parameters.properties.capability_request.properties;
  for (const field of ["modality", "objective", "target_kind", "training_route"]) {
    assert.equal(shape[field].type, "string");
    assert.equal(shape[field].enum, undefined, `${field} must preserve unfamiliar goals rather than be a business whitelist`);
  }
  for (const objective of ["classification", "regression", "speech_recognition", "forecasting"]) assert.ok(shape.objective.description.includes(objective));
  for (const modality of ["image", "audio", "text", "tabular"]) assert.ok(shape.modality.description.includes(modality));
  assert.match(shape.objective.description, /normalization hints, not allowed-value limits/);
  assert.match(shape.objective.description, /speech_to_text remain valid/);
});

test("material tool renders valid compact JSON without splitting table evidence", () => {
  const tool = mount().tools.find(item => item.name === "model_harness_get_material");
  const evidence = {material:{report:{tables:[{file:"test.csv",row_count:60},{file:"train.csv",row_count:180}]}}};
  const content = tool.output.render({}, evidence);
  assert.equal(content[0].text, JSON.stringify(evidence));
  assert.deepEqual(JSON.parse(content[0].text), evidence);
});
