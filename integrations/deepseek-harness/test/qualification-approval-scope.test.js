import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { apply } from "../index.js";
import { SOLUTION_CONSULTATION_GUIDANCE as policy } from "../consultation-policy.js";

const sha = "a".repeat(64), toolName = "model_harness_qualify_execution_proposal";
function facts() {
  return {
    proposal: { task_id: "task-scope", proposal_id: "execution-scope", proposal_sha256: sha, base_spec_revision: 4,
      execution_spec: { bundle: { image: `python@sha256:${sha}`, limits: { cpus: 2, memory_bytes: 512 * 1024 ** 2, pids: 64, timeout_seconds: 180, tmpfs_bytes: 64 * 1024 ** 2, max_input_bytes: 256 * 1024 ** 2, max_artifact_bytes: 64 * 1024 ** 2, max_artifact_files: 128, max_log_bytes: 1024 ** 2 } },
        config: { qualify_timeout_seconds: 60 }, data_mapping: [{ material_id: "material-scope", split: "train" }, { material_id: "held-out", split: "test" }] } },
    execution_workspace: { task_id: "task-scope", spec_revision: 4,
      protocol: { source_directory: "/workspace/source", input_directory: "/workspace/input", output_directory: "/workspace/output", stage_inputs: { qualify: ["train", "validation", "assets", "config.json"] } },
      materials: [{ material_id: "material-scope", file: { name: "records.csv" } }, { material_id: "held-out", file: { name: "private-test.csv" } }] },
  };
}
async function decision(value = facts(), extraArgs = {}) {
  const handlers = new Map(), requests = [];
  apply({ tools: { register() {} }, systemPrompt: { section() {} }, on: (name, callback) => handlers.set(name, callback) });
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ path: new URL(url).pathname, method: options.method });
    return new Response(JSON.stringify(new URL(url).pathname.endsWith("/execution-workspace") ? { execution_workspace: value.execution_workspace } : { proposal: value.proposal }), { headers: { "content-type": "application/json" } });
  };
  try {
    const result = await handlers.get("tools/pre-execute")({ name: toolName, agent: { session: { header: { id: "root-scope" }, events: [] } }, arguments: { task_id: "task-scope", proposal_id: "execution-scope", expected_proposal_sha256: sha, ...extraArgs } }, async () => ({ kind: "allow" }));
    assert.equal(requests.length, 2); assert.ok(requests.every(item => item.method === "GET"), "approval facts never execute or change the proposal");
    return result;
  } finally { globalThis.fetch = previous; }
}

test("native approval shows inherited executor 180 seconds even when config claims 60", async () => {
  const result = await decision();
  assert.equal(result.kind, "ask"); assert.match(result.reason, /资格验证最长 180 秒.*继承方案默认上限/);
  assert.doesNotMatch(result.reason, /60 秒/);
  for (const expected of ["CPU 上限 2 核", "内存上限 512 MiB", "进程上限 64", "输入最多 256 MiB", "输出最多 64 MiB / 128 个文件", `python@sha256:${sha}`, "/workspace/source", "/workspace/input", "/workspace/output", '"records.csv"（train）', "不挂载 test 分区"])
    assert.ok(result.reason.includes(expected), expected);
  assert.doesNotMatch(result.reason, /private-test.csv/); assert.match(result.reason, /不批准正式训练/);
});

test("native approval uses the actual tighter qualify stage and preserves the default per-stage distinction", async () => {
  const value = facts(); value.proposal.execution_spec.bundle.stage_limits = { qualify: { timeout_seconds: 60, cpus: 1 } };
  value.proposal.execution_spec.bundle.image = `sha256:${sha}`;
  const result = await decision(value);
  assert.equal(result.kind, "ask"); assert.match(result.reason, /资格验证最长 60 秒.*阶段专用上限/); assert.match(result.reason, /CPU 上限 1 核/);
  assert.match(result.reason, /默认上限为 180 秒\/阶段，不是整项工作的总预算/); assert.ok(result.reason.includes(`固定镜像：sha256:${sha}`));
});

test("approval fact reads deny stale owners, versions, incomplete limits and unsafe or unknown mount scopes", async () => {
  const changes = [
    value => { value.execution_workspace.task_id = "foreign"; },
    value => { value.execution_workspace.spec_revision = 5; },
    value => { delete value.proposal.execution_spec.bundle.limits.memory_bytes; },
    value => { value.proposal.execution_spec.bundle.stage_limits = { qualify: { timeout_seconds: 181 } }; },
    value => { value.proposal.execution_spec.bundle.image = "python:latest"; },
    value => { value.execution_workspace.protocol.source_directory = "/workspace/output"; },
    value => { value.execution_workspace.protocol.stage_inputs.qualify.push("test"); },
    value => { value.execution_workspace.protocol.stage_inputs.qualify.push("../../private"); },
    value => { delete value.execution_workspace.protocol; },
  ];
  for (const change of changes) { const value = facts(); change(value); assert.equal((await decision(value)).kind, "deny"); }
});

test("license-limited qualification keeps the original warning together with actual resource limits", async () => {
  const value = facts(); value.proposal.assets = [{ asset_id: "asset-scope", repository: "public/model", license: "unknown", license_review_required: true }];
  const result = await decision(value, { local_experiment_only: true });
  assert.equal(result.kind, "ask"); assert.match(result.reason, /公开资产许可信息待核对，本次仅用于本地试验，不作为公开发布依据/); assert.match(result.reason, /资格验证最长 180 秒/);
});

test("actual native reason survives event normalization and renders in the approval card without changing its answer transaction", async () => {
  const { reason } = await decision();
  const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
  const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to));
  const cards = [], answers = [];
  class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.events = {}; this.classList = { add() {} }; }
    append(...items) { this.children.push(...items); }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(name, callback) { this.events[name] = callback; }
  }
  const context = { state: { runtimeReady: true, conversation: { pending_observed: true } }, document: { createElement: tag => new Node(tag) },
    ui: { messageList: { append: card => cards.push(card) } }, backgroundCancellationPending: () => false, dataUploadQuestionCheckpoint: () => null, inferenceInputQuestionCheckpoint: () => null,
    appendApprovalScope() {}, appendObjectRefs() {}, answerApproval: (_item, answer) => answers.push(answer) };
  vm.runInNewContext(readFileSync(new URL("../../../model_harness/web/conversation-view.js", import.meta.url), "utf8"), context);
  vm.runInNewContext(section("function approvalPresentation", "function contractApprovalSummary") + section("function renderHumanCheckpoint", "function terminalEventScope") + "\nglobalThis.render=renderHumanCheckpoint;globalThis.present=approvalPresentation;", context);
  const item = context.ModelHarnessConversationView.normalizeEvent({ event_type: "approval", status: "pending", payload: { reason, tool_name: toolName, rpc_id: "native-scope" } }, 0);
  assert.equal(item.reason, reason); context.render(item);
  assert.equal(cards[0].children[2].textContent, reason); assert.equal(cards[0].children[2].attributes.style, "white-space: pre-line");
  const actions = cards[0].children[3]; assert.equal(actions.children[0].textContent, "批准本次工程验证"); actions.children[0].events.click(); actions.children[1].events.click();
  assert.deepEqual(answers, ["allowed-once", "rejected"]);
  assert.equal(context.present({ tool_name: toolName, payload: { reason } }).copy, reason);
  assert.match(context.present({ tool_name: toolName }).copy, /没有完整记录资源范围/);
});

test("shared policy binds budgets to executor limits and limits follow-up prose to new decision-useful facts", () => {
  assert.match(policy, /CPU、内存和每阶段时长约束.*实际执行器生效的 bundle.limits 或对应 bundle.stage_limits/);
  assert.match(policy, /config 参数、脚本内计时.*不能代替隔离上限/);
  assert.match(policy, /请求原生审批前.*核对每个阶段的有效限额符合用户约束/);
  assert.match(policy, /重新读取最新工作区 schema\/protocol.*不沿用旧缓存/);
  assert.match(policy, /只给必要的新发现、待决策事项和下一动作/);
  assert.match(policy, /完整清单、内部 ID、协议字段.*留在证据视图/);
  assert.match(policy, /材料表格只有帮助当前决策时才呈现/);
});
