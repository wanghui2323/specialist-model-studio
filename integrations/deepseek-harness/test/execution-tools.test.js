import assert from "node:assert/strict";
import { test } from "node:test";
import { isJsonValue } from "@deepseek-ai/dsh-session";
import { apply, ROLE_TOOL_ALLOWLISTS } from "../index.js";
import { ModelHarnessClient, executionPublicProjection, publicProjection } from "../client.js";
const sha = "a".repeat(64), qsha = "b".repeat(64);
const source = 'from pathlib import Path\np = Path("/workspace/input/train/data.csv")\nPath("/workspace/output/model.json").write_text("{}")\n';
const spec = { bundle: { image: `python@sha256:${sha}`, files: { "train.py": source, root: "print(1)" }, stages: { train: ["python", "/workspace/source/train.py"] }, limits: { cpus: 1, memory_bytes: 512 * 1024 * 1024, pids: 64, timeout_seconds: 180, tmpfs_bytes: 64 * 1024 * 1024, max_input_bytes: 256 * 1024 * 1024, max_artifact_bytes: 64 * 1024 * 1024, max_artifact_files: 128, max_log_bytes: 1024 * 1024 } }, inference: { extensions: [".json"], max_bytes: 500, schema: { type: "object", properties: { signal: { type: "number" } } } } };
const envelope = (status = "proposed") => ({ proposal: { task_id: "task-a", proposal_id: "proposal-a", proposal_sha256: sha, base_spec_revision: 1, status, execution_spec: spec } });
function mount() { const tools = [], listeners = new Map(); apply({ tools: { register: item => tools.push(item) }, systemPrompt: { section() {} }, on: (name, fn) => listeners.set(name, fn) }); return { tool: name => tools.find(item => item.name === name), listeners }; }
function response(value, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } }); }
function workspace() { return { execution_workspace: { task_id: "task-a", spec_revision: 1, protocol: { source_directory: "/workspace/source", input_directory: "/workspace/input", output_directory: "/workspace/output", stage_inputs: { qualify: ["train", "validation", "assets", "config.json"] } }, materials: [] } }; }
const root = { session: { header: { id: "root-a" }, events: [] } };
function child(role) { return { session: { header: { id: "child-a", origin: "subagent", parentSession: "root-a", seedLength: 0 }, events: [{ type: "subagent/descriptor", data: { version: 2, mode: "continuable", provider: "spawn", toolFilter: { allow: [...ROLE_TOOL_ALLOWLISTS[role]] } } }] } }; }

test("execution projection preserves protocol virtual paths and source file identities while retaining host redaction", () => {
  const value = executionPublicProjection({ ...envelope(), workspace_root: "/Users/private/work", note: "host /Users/private/data.csv", mounts: ["/workspace/input", "/workspace/source", "/workspace/output", "/workspace/input/../../private"] });
  assert.equal(value.proposal.execution_spec.bundle.files["train.py"], source); assert.equal(value.proposal.execution_spec.bundle.files.root, "print(1)");
  assert.equal(value.proposal.execution_spec.bundle.stages.train[1], "/workspace/source/train.py"); assert.equal(value.workspace_root, undefined);
  assert.doesNotMatch(value.note, /Users/); assert.equal(value.mounts[0], "/workspace/input"); assert.match(value.mounts[3], /redacted/);
  assert.notEqual(publicProjection("/workspace/input"), "/workspace/input", "ordinary domain projections are not broadened");
});

test("execution clients use task-owned JSON routes and never turn proposal creation into execution", async () => {
  const original = globalThis.fetch, calls = [], client = new ModelHarnessClient("http://localhost", "bridge-proof");
  globalThis.fetch = async (url, options) => { calls.push([new URL(url).pathname, options]); return response(envelope()); };
  try {
    await client.executionWorkspace("task-a"); await client.listExecutionProposals("task-a"); await client.getExecutionProposal("task-a", "proposal-a");
    const saved = await client.createExecutionProposal("task-a", { baseSpecRevision: 4, executionSpec: spec, requestId: "draft-request" });
    assert.deepEqual(calls.map(([url]) => url), ["/tasks/task-a/execution-workspace", "/tasks/task-a/execution-proposals", "/tasks/task-a/execution-proposals/proposal-a", "/tasks/task-a/execution-proposals"]);
    assert.ok(calls.every(([, options]) => options.headers["X-Model-Harness-Projection"] === "agent-execution-v1"));
    assert.deepEqual(JSON.parse(calls[3][1].body), { base_spec_revision: 4, execution_spec: spec, request_id: "draft-request" });
    assert.equal(saved.proposal.execution_spec.bundle.files["train.py"], source); assert.ok(calls.every(([, options]) => !options.headers["X-Model-Harness-Agent-Token"]));
    await client.qualifyExecutionProposal("task-a", "proposal-a", { expectedProposalSha256: sha, approvalCheckpointId: "native-q" });
    assert.deepEqual(JSON.parse(calls[4][1].body), { expected_proposal_sha256: sha, approval: { actor: "user", checkpoint_id: "native-q" } }); assert.equal(calls[4][1].headers["X-Model-Harness-Agent-Token"], "bridge-proof");
    await client.activateExecutionProposal("task-a", "proposal-a", { expectedProposalSha256: sha, qualificationId: "qualification-a", expectedQualificationSha256: qsha, approvalCheckpointId: "native-a" });
    assert.equal(JSON.parse(calls[5][1].body).expected_qualification_sha256, qsha); assert.equal(JSON.parse(calls[5][1].body).approval.checkpoint_id, "native-a");
  } finally { globalThis.fetch = original; }
});

test("execution role and approval gates keep authoring separate from isolated qualification and formal Run permissions", async () => {
  const originalFetch = globalThis.fetch; globalThis.fetch = async url => response(new URL(url).pathname.endsWith("/execution-workspace") ? workspace() : { ...envelope("qualified"), qualification: { task_id: "task-a", proposal_id: "proposal-a", qualification_id: "qualification-a", qualification_sha256: qsha, status: "passed" } });
  try {
  const { listeners } = mount(), gate = listeners.get("tools/pre-execute");
  const exec = (name, agent) => ({ name, agent, arguments: { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha, qualification_id: "qualification-a", expected_qualification_sha256: qsha }, callId: "native-1" });
  const next = async () => ({ kind: "allow" });
  assert.equal((await gate(exec("model_harness_create_execution_proposal", child("build_training")), next)).kind, "allow");
  assert.equal((await gate(exec("model_harness_create_execution_proposal", root), next)).kind, "deny");
  for (const name of ["model_harness_qualify_execution_proposal", "model_harness_activate_execution_proposal"]) {
    assert.equal((await gate(exec(name, child("build_training")), next)).kind, "deny");
    const decision = await gate(exec(name, root), next); assert.equal(decision.kind, "ask"); assert.match(decision.reason, /不批准正式训练|不会启动训练/);
  }
  assert.equal((await gate(exec("model_harness_get_execution_workspace", child("data_experiment")), next)).kind, "deny");
  assert.equal((await gate(exec("model_harness_get_execution_workspace", root), next)).kind, "allow");
  } finally { globalThis.fetch = originalFetch; }
});

test("authoring returns only observed proposal refs and rejects a wrong-owner response", async () => {
  const { tool } = mount(), original = globalThis.fetch; const author = tool("model_harness_create_execution_proposal");
  const args = { task_id: "task-a", base_spec_revision: 1, execution_spec: spec, request_id: "author-a" };
  try {
    globalThis.fetch = async () => response(envelope()); const result = await author.execute(args, { agent: child("build_training") });
    assert.equal(result.object_refs[0].type, "execution_proposal"); assert.equal(result.object_refs[0].digest, sha); assert.equal(result.proposal.status, "proposed");
    globalThis.fetch = async () => response({ proposal: { ...envelope().proposal, task_id: "other" } }); await assert.rejects(author.execute(args, {}), /canonical identity/);
  } finally { globalThis.fetch = original; }
});

test("incomplete or stale activation never asks the human to approve an unusable checkpoint", async () => {
  const { listeners } = mount(), gate = listeners.get("tools/pre-execute"), original = globalThis.fetch;
  const qualification = { task_id: "task-a", proposal_id: "proposal-a", qualification_id: "qualification-a", qualification_sha256: qsha, status: "passed" };
  const args = { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha, qualification_id: "qualification-a", expected_qualification_sha256: qsha };
  let reads = 0, current = { ...envelope("qualified"), qualification };
  globalThis.fetch = async (_url, options) => { assert.equal(options.method, "GET"); reads++; return response(current); };
  const check = arguments_ => gate({ name: "model_harness_activate_execution_proposal", agent: root, arguments: arguments_, callId: "native-a" }, async () => ({ kind: "allow" }));
  try {
    const { qualification_id, ...missing } = args;
    assert.equal((await check(missing)).kind, "deny"); assert.equal(reads, 0);
    assert.equal((await check(args)).kind, "ask");
    for (const change of [{ status: "failed" }, { qualification_id: "old" }, { task_id: "other" }, { qualification_sha256: sha }]) {
      current = { ...envelope("qualified"), qualification: { ...qualification, ...change } };
      assert.equal((await check(args)).kind, "deny");
    }
  } finally { globalThis.fetch = original; }
});

test("qualification checks the exact approved proposal and returns running honestly", async () => {
  const previous = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-proof";
  const { tool } = mount(), original = globalThis.fetch, calls = []; let changed = false;
  globalThis.fetch = async (url, options) => { calls.push([new URL(url).pathname, options]); return response(changed ? { proposal: { ...envelope().proposal, proposal_sha256: qsha } } : options.method === "GET" ? envelope() : { ...envelope("qualifying"), qualification: { qualification_id: "qualification-a", status: "running" } }); };
  try {
    const args = { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha }, q = tool("model_harness_qualify_execution_proposal");
    const result = await q.execute(args, { agent: root, callId: "native-q" }); assert.equal(result.proposal.status, "qualifying"); assert.equal(result.qualification.status, "running"); assert.equal(calls.length, 2);
    changed = true; await assert.rejects(q.execute(args, { agent: root, callId: "native-new" }), /changed after approval/); assert.equal(calls.length, 3, "drift causes no qualification POST");
    await assert.rejects(q.execute(args, { agent: child("build_training"), callId: "fake" }), /root Training Orchestrator/); assert.equal(calls.length, 3);
  } finally { globalThis.fetch = original; if (previous === undefined) delete process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; else process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = previous; }
});

test("activation verifies exact passed qualification and never grants a formal Run", async () => {
  const previous = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-proof";
  const { tool } = mount(), original = globalThis.fetch, calls = [];
  let qualification = { task_id: "task-a", proposal_id: "proposal-a", qualification_id: "qualification-a", qualification_sha256: qsha, status: "passed" };
  globalThis.fetch = async (url, options) => { calls.push([new URL(url).pathname, options]); return response({ ...envelope(options.method === "POST" ? "activated" : "qualified"), qualification, task: { task_id: "task-a", contract_confirmed: false }, dataset_id: "dataset-a" }); };
  try {
    const activate = tool("model_harness_activate_execution_proposal");
    const args = { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha, qualification_id: "qualification-a", expected_qualification_sha256: qsha };
    const result = await activate.execute(args, { agent: root, callId: "native-activate" });
    assert.equal(result.task.contract_confirmed, false); assert.equal(result.proposal.status, "activated"); assert.ok(calls.every(([path]) => !/authorizations|\/runs/.test(path)));
    for (const change of [{ status: "running" }, { qualification_id: "another" }, { qualification_sha256: sha }, { task_id: "other" }]) {
      const before = calls.length; qualification = { ...qualification, ...change };
      await assert.rejects(activate.execute(args, { agent: root, callId: "native-other" }), /exact passed qualification/); assert.equal(calls.length, before + 1, "no activation POST on drift");
      qualification = { task_id: "task-a", proposal_id: "proposal-a", qualification_id: "qualification-a", qualification_sha256: qsha, status: "passed" };
    }
  } finally { globalThis.fetch = original; if (previous === undefined) delete process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; else process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = previous; }
});

test("workspace output retains complete schema/protocol and concise real material identities", async () => {
  const { tool } = mount(), original = globalThis.fetch;
  const schema = { properties: { stages: { required: ["qualify", "train", "evaluate", "predict"] } }, "x-protocol": { source: "/workspace/source" } };
  globalThis.fetch = async () => response({ execution_workspace: { task_id: "task-a", execution_spec_schema: schema, protocol: { input_directory: "/workspace/input" }, materials: [{ owner_id: "task-a", material_id: "material-a", inspection_sha256: sha, status: "inspected", report: { facts: { row_count: 20 }, tables: [{ preview: "x".repeat(50000) }] } }], proposals: [] } });
  try { const result = await tool("model_harness_get_execution_workspace").execute({ task_id: "task-a" }, {}); assert.deepEqual(result.execution_workspace.execution_spec_schema, schema); assert.equal(result.execution_workspace.materials[0].inspection_sha256, sha); assert.equal(result.execution_workspace.materials[0].facts.row_count, 20); assert.ok(JSON.stringify(result).length < 2000); }
  finally { globalThis.fetch = original; }
});

test("public asset acquisition is root-approved, immutable and keeps unknown license review unresolved", async () => {
  const previous = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-proof";
  const { tool, listeners } = mount(), original = globalThis.fetch, calls = [], commit = "c".repeat(40);
  const asset = { object_type: "ExecutionAsset", task_id: "task-a", asset_id: `asset-${"d".repeat(24)}`, repository: "org/model", resolved_commit: commit, manifest_sha256: sha, files: [{ path: "config.json", sha256: qsha, bytes: 30 }], license: "unknown", license_policy: { decision: "review" }, license_review_required: true, executable_imported_on_host: false };
  globalThis.fetch = async (url, options) => { calls.push([new URL(url).pathname, options]); return response(options.method === "GET" ? { assets: [asset] } : { asset }); };
  try {
    const args = { task_id: "task-a", repository: "org/model", revision: commit, files: ["config.json"] }, name = "model_harness_acquire_execution_asset", gate = listeners.get("tools/pre-execute");
    assert.equal((await gate({ name, agent: root, arguments: args }, async () => ({ kind: "allow" }))).kind, "ask");
    assert.equal((await gate({ name, agent: child("build_training"), arguments: args }, async () => ({ kind: "allow" }))).kind, "deny");
    const result = await tool(name).execute(args, { agent: root, callId: "native-assets" }); assert.equal(result.asset.license_review_required, true); assert.equal(result.asset.license_policy.decision, "review");
    assert.equal(calls[0][0], "/tasks/task-a/execution-assets"); assert.equal(calls[0][1].headers["X-Model-Harness-Agent-Token"], "bridge-proof"); assert.deepEqual(JSON.parse(calls[0][1].body), { repository: "org/model", revision: commit, files: ["config.json"], approval: { actor: "user", checkpoint_id: "native-assets" } });
    const listed = await tool("model_harness_list_execution_assets").execute({ task_id: "task-a" }, { agent: child("build_training") }); assert.equal(listed.assets[0].asset_id, `asset-${"d".repeat(24)}`);
    await assert.rejects(tool(name).execute({ ...args, revision: "main" }, { agent: root, callId: "native-bad" }), /immutable commit/); assert.equal(calls.length, 2);
    await assert.rejects(tool(name).execute({ ...args, files: ["../outside"] }, { agent: root, callId: "native-path" }), /relative file paths/); assert.equal(calls.length, 2);
  } finally { globalThis.fetch = original; if (previous === undefined) delete process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; else process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = previous; }
});

test("unresolved asset licensing requires an explicit local-only qualification scope and never changes the license verdict", async () => {
  const previous = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-proof";
  const { tool, listeners } = mount(), original = globalThis.fetch, calls = [];
  const assets = [{ asset_id: `asset-${"c".repeat(24)}`, repository: "public/source", license: "unknown", license_review_required: true, license_policy: { decision: "review" } }];
  globalThis.fetch = async (url, options) => { calls.push([new URL(url).pathname, options]); return response(new URL(url).pathname.endsWith("/execution-workspace") ? workspace() : { proposal: { ...envelope(options.method === "GET" ? "proposed" : "qualifying").proposal, assets } }); };
  try {
    const name = "model_harness_qualify_execution_proposal", gate = listeners.get("tools/pre-execute"), args = { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha };
    const missing = await gate({ name, agent: root, arguments: args }, async () => ({ kind: "allow" })); assert.equal(missing.kind, "deny"); assert.match(missing.reason, /许可信息待核对/); assert.equal(args.local_experiment_only, undefined);
    await assert.rejects(tool(name).execute(args, { agent: root, callId: "native-missing" }), /explicitly approved local-experiment-only/); assert.ok(calls.every(([, options]) => options.method === "GET"));
    const localArgs = { ...args, local_experiment_only: true };
    const limited = await gate({ name, agent: root, arguments: localArgs }, async () => ({ kind: "allow" })); assert.equal(limited.kind, "ask"); assert.match(limited.reason, /公开资产许可信息待核对，本次仅用于本地试验，不作为公开发布依据/); assert.match(limited.reason, /public\/source（unknown）/);
    const result = await tool(name).execute(localArgs, { agent: root, callId: "native-local" });
    assert.equal(JSON.parse(calls.at(-1)[1].body).local_experiment_only, true); assert.equal(result.proposal.assets[0].license_policy.decision, "review"); assert.equal(result.proposal.assets[0].license_review_required, true);
    assets.length = 0;
    const ordinary = await gate({ name, agent: root, arguments: args }, async () => ({ kind: "allow" })); assert.equal(ordinary.kind, "ask"); assert.doesNotMatch(ordinary.reason, /许可信息待核对|本地试验/);
    await tool(name).execute(args, { agent: root, callId: "native-ordinary" }); assert.equal(JSON.parse(calls.at(-1)[1].body).local_experiment_only, undefined, "the client never silently defaults local-only permission");
  } finally { globalThis.fetch = original; if (previous === undefined) delete process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; else process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = previous; }
});


test("minimal backend workspace briefs remain lossless JSON without synthesizing absent facts", async () => {
  const { tool } = mount(), original = globalThis.fetch;
  const material = { material_id: "material-012345678901234567890123", inspection_sha256: sha, status: "inspected", file: { name: "series.csv", bytes: 23, sha256: qsha } };
  globalThis.fetch = async () => response({ execution_workspace: { task_id: "task-a", materials: [material], proposals: [
    { proposal_id: "proposal-a", proposal_sha256: sha, status: "proposed", qualification: null },
    { proposal_id: "proposal-b", proposal_sha256: qsha, status: "qualifying", qualification: { status: "running", qualification_id: "qualification-b" } },
    { proposal_id: "proposal-c", proposal_sha256: qsha, status: "proposed" },
  ], protocol: { input_directory: "/workspace/input" } } });
  try {
    const result = await tool("model_harness_get_execution_workspace").execute({ task_id: "task-a" }, {});
    assert.equal(isJsonValue(result), true, "use the actual DSH lossless-JSON validator, not JSON.stringify which silently drops undefined");
    assert.deepEqual(result.execution_workspace.materials[0], material);
    assert.equal(Object.hasOwn(result.execution_workspace.materials[0], "owner_id"), false); assert.equal(Object.hasOwn(result.execution_workspace.materials[0], "facts"), false); assert.equal(Object.hasOwn(result.execution_workspace.materials[0], "error_count"), false);
    assert.equal(result.execution_workspace.proposals[0].qualification, null);
    assert.deepEqual(result.execution_workspace.proposals[1].qualification, { status: "running", qualification_id: "qualification-b" });
    assert.equal(Object.hasOwn(result.execution_workspace.proposals[1], "failure"), false); assert.equal(Object.hasOwn(result.execution_workspace.proposals[2], "qualification"), false);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
  } finally { globalThis.fetch = original; }
});

test("proposal create/get/list and running qualification outputs satisfy the native lossless JSON boundary", async () => {
  const previous = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-proof";
  const { tool } = mount(), original = globalThis.fetch;
  globalThis.fetch = async (url, options) => response(new URL(url).pathname.endsWith("/execution-proposals") && options.method === "GET" ? { proposals: [{ ...envelope().proposal, qualification: null }] } : { ...envelope(new URL(url).pathname.endsWith("/qualify") ? "qualifying" : "proposed"), qualification: new URL(url).pathname.endsWith("/qualify") ? { qualification_id: "qualification-a", status: "running" } : null });
  try {
    for (const [name, args, agent] of [
      ["model_harness_create_execution_proposal", { task_id: "task-a", base_spec_revision: 1, execution_spec: spec, request_id: "new" }, child("build_training")],
      ["model_harness_get_execution_proposal", { task_id: "task-a", proposal_id: "proposal-a" }, root],
      ["model_harness_list_execution_proposals", { task_id: "task-a" }, root],
      ["model_harness_qualify_execution_proposal", { task_id: "task-a", proposal_id: "proposal-a", expected_proposal_sha256: sha }, root],
    ]) {
      const value = await tool(name).execute(args, { agent, callId: "native-qualification" }); assert.equal(isJsonValue(value), true, name); assert.deepEqual(JSON.parse(JSON.stringify(value)), value, name);
    }
  } finally { globalThis.fetch = original; if (previous === undefined) delete process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN; else process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = previous; }
});
