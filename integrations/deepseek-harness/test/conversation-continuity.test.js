import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to));

test("exact result viewer summarizes observed evidence without assuming privacy or publication", () => {
  const context = { normalizeObjectRefType: (v) => v };
  vm.runInNewContext(section("function objectViewerPresentation", "function renderObjectViewerOverview") + "\nglobalThis.present = objectViewerPresentation;", context);
  const unknown = context.present({ type: "artifact_bundle" }, { artifact_bundle: { status: "completed" } });
  assert.match(unknown.note, /未完整确认/);
  assert.equal(unknown.rows[3][1], "未确认满足发布门槛");
  const bundle = context.present({ type: "artifact_bundle" }, { artifact_bundle: {
    status: "completed", release_ready: true, archive: { size_bytes: 1024 },
    manifest: { files: [{ path: "model.joblib" }], privacy_boundary: { raw_data_included: false, test_references_included: false, internal_state_included: false } },
  } });
  assert.equal(bundle.rows[1][1], "1.0 KB");
  assert.match(bundle.rows[3][1], /尚不代表已发布/);
  assert.match(bundle.note, /清单确认/);
  assert.deepEqual([...bundle.files], ["model.joblib"]);
  const report = context.present({ type: "evaluation_report" }, { evaluation_report: {
    integrity_checks: [{ passed: true }, { passed: false }], metric_gates: { mae: true, r2: false }, test_contaminated: true, test_sample_count: 24,
  } });
  assert.equal(report.rows[1][1], "1 / 2 项通过");
  assert.equal(report.rows[2][1], "1 / 2 项通过");
  assert.match(report.rows[4][1], /不能据此发布/);
  assert.equal(context.present({ type: "artifact_bundle" }, { task: {} }), null);
  const blocker = context.present({ type: "blocker" }, { blocker: { code: "recipe_unavailable", message: "没有已验证能力", rule: { run_creation_allowed: false } } });
  assert.equal(blocker.rows[3][1], "不允许");
  assert.match(blocker.note, /不是训练成功/);
});

test("completed evidence header never overrides an active checkpoint or failure", () => {
  const source = section("function renderWorkspaceExperience", "function workspaceContextForPhase");
  const expression = source.match(/const displayPhase = ([^;]+);/)[1];
  for (const phase of ["executing", "clarifying", "awaiting_approval", "blocked"]) {
    assert.equal(vm.runInNewContext(expression, { projection: { phase }, evaluationOutcome: { ready: true } }), phase);
  }
  assert.equal(vm.runInNewContext(expression, { projection: { phase: "idle" }, evaluationOutcome: { ready: true } }), "result_ready");
  assert.equal(vm.runInNewContext(expression, { projection: { phase: "idle" }, evaluationOutcome: { ready: false } }), "idle");
});

test("inference input opens only its exact task run id and content digest", () => {
  const context = { normalizeObjectRefType: (v) => v, TERMINAL_RESULT_REF_TYPES: new Set() };
  vm.runInNewContext(section("function returnedObjectMatchesRef", "async function openObjectRef") + "\nglobalThis.matches = returnedObjectMatchesRef;", context);
  const ref = { type: "inference_input", task_id: "task", run_id: "run", id: "input", digest: "sha" };
  const payload = { task: { task_id: "task" }, run_id: "run", inference_input: { task_id: "task", run_id: "run", inference_input_id: "input", sha256: "sha" } };
  assert.equal(context.matches(ref, payload), true);
  for (const key of ["task_id", "run_id", "inference_input_id", "sha256"]) {
    assert.equal(context.matches(ref, { ...payload, inference_input: { ...payload.inference_input, [key]: "wrong" } }), false);
  }
  assert.equal(context.matches(ref, null), false);
});

test("blocker viewer matches the observed content digest, never the semantic identity digest", () => {
  const context = { normalizeObjectRefType: (v) => v, TERMINAL_RESULT_REF_TYPES: new Set() };
  vm.runInNewContext(section("function returnedObjectMatchesRef", "async function openObjectRef") + "\nglobalThis.matches = returnedObjectMatchesRef;", context);
  const ref = { type: "blocker", task_id: "task", id: "blocker-id", digest: "a".repeat(64) };
  const blocker = { task_id: "task", blocker_id: "blocker-id", content_digest: ref.digest, semantic_digest: "b".repeat(64) };
  assert.equal(context.matches(ref, { blocker }), true);
  for (const key of ["task_id", "blocker_id", "content_digest"]) {
    assert.equal(context.matches(ref, { blocker: { ...blocker, [key]: "wrong" } }), false);
  }
  assert.equal(context.matches({ ...ref, digest: blocker.semantic_digest }, { blocker }), false);
  assert.equal(context.matches({ ...ref, digest: undefined }, { blocker: { ...blocker, content_digest: undefined } }), false);
  assert.equal(context.matches(ref, null), false);
});

test("native approval labels use the tool identity, never generic data or compute prose", () => {
  const context = {};
  vm.runInNewContext(section("function approvalPresentation", "function appendApprovalScope") + "\nglobalThis.present = approvalPresentation;", context);
  const reason = "changes local task, data, compute, or approval state; start training and artifact bundle";
  const binding = context.present({ tool_name: "model_harness_bind_model_source", reason });
  assert.equal(binding.allow, "确认绑定并分析");
  assert.match(binding.copy, /不代表批准下载权重、安装代码或训练/);
  assert.equal(context.present({ tool_name: "model_harness_import_dataset", reason }).title, "批准导入并体检这份数据");
  assert.equal(context.present({ tool_name: "unrecognized_action", reason }).title, "批准关键操作");
  assert.equal(context.present({ reason: "dataset train contract" }).title, "批准关键操作");
  for (const [tool_name, allow] of [
    ["model_harness_authorize_task_run_start", "批准并启动训练"],
    ["model_harness_confirm_contract", "确认并锁定"],
    ["model_harness_authorize_artifact_bundle_build", "批准构建交付包"],
    ["model_harness_download_artifact_bundle", "确认并下载"],
    ["model_harness_authorize_sample_inference", "批准本次试跑"],
  ]) assert.equal(context.present({ tool_name, reason }).allow, allow);
});

test("later follow-up does not erase earlier results within the same AI turn", () => {
  const context = {};
  vm.runInNewContext(section("function visibleNarrativeIndexes", "function renderConversationTurn") + "\nglobalThis.visible = visibleNarrativeIndexes;", context);
  const visible = context.visible([
    { kind: "coordinator_note", text: "训练完成，R² 0.9，MAE 100 元。" },
    { kind: "coordinator_note", text: "要试新样本还是打包？" },
    { kind: "final_synthesis", text: "要试新样本还是打包？" },
  ]);
  assert.deepEqual([...visible], [0, 2]);
});

test("historical action timelines never borrow a newer turn's waiting or running state", () => {
  const source = section("function renderConversationTurn", "function isWaitingForAnswerAction");
  const expression = source.match(/const turnInteractionState = ([^;]+);/)[1];
  for (const phase of ["executing", "clarifying", "awaiting_approval"]) {
    assert.equal(vm.runInNewContext(expression, { current: false, projection: { phase } }), "idle");
  }
  assert.equal(vm.runInNewContext(expression, { current: true, projection: { phase: "awaiting_approval" } }), "waiting_for_human");
});

test("task hydration never offers to resend before checking its saved conversation", () => {
  const rendered = [];
  const context = { state: { runtimeReady: true, conversation: null },
    ui: { messageList: { append: (node) => rendered.push(node) } },
    document: { createElement: (tag) => ({ tag, dataset: {}, setAttribute() {} }) } };
  vm.runInNewContext(section("function renderAgentSurfaceState", "function renderConversation(") + "\nglobalThis.surface = renderAgentSurfaceState;", context);
  context.surface({}, {});
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].dataset.state, "loading");
  assert.equal(rendered[0].textContent, "正在恢复对话和执行记录…");
});

for (const [kind, id, message] of [
  ["approval", "train", "这一步有什么风险？"],
  ["question", "data_upload", "我没有数据，能给我一个格式例子吗？"],
  ["question", "target_column", "我想改成预测金额"],
  ["question", "inference_input_id", "新样本和测试集有什么区别？"],
  ["question", "method", "为什么推荐这个模型？"],
]) {
  test(`composer discusses ${id} without approving, answering or opening a picker`, async () => {
    const sent = [];
    const ui = { sendButton: { dataset: {} }, messageInput: { value: message } };
    const state = { runtimeReady: true, selectedTaskId: "task-1", conversation: {} };
    const context = { state, ui,
      clearComposerRetry() {}, hideNotice() {}, clearDraft() {}, resizeComposer() {},
      showTransientNotice() {}, refreshSelected() {},
      backgroundCancellationPending: () => false,
      currentHumanCheckpoint: () => ({ kind, rpc_id: "rpc-1", questions: [{ id }] }),
      conversationAgentResponseRunning: () => true,
      postQueuedConversationMessage: async (task, text) => sent.push({ task, text }),
      window: { setTimeout() {} },
    };
    vm.runInNewContext(section("async function submitMessage", "function deriveTaskName") + "\nglobalThis.submit = submitMessage;", context);
    await context.submit(message);
    assert.deepEqual(sent, [{ task: "task-1", text: message }]);
    assert.equal(ui.messageInput.value, "");
    assert.equal(ui.sendButton.disabled, false);
  });
}

test("ambiguous send retry preserves both message identity and checkpoint identity", async () => {
  const requests = [];
  let checkpoint = { rpc_id: "rpc-1" };
  let attempt = 0;
  const state = { selectedTaskId: "task-1", conversation: {} };
  const context = { state,
    currentHumanCheckpoint: () => checkpoint,
    createConversationRequestId: () => "request-1",
    renderConversation() {},
    conversationTransportPath: (task, suffix) => `/tasks/${task}/conversation/${suffix}`,
    DEFAULT_CONVERSATION_MESSAGE_MODE: "queue_after_turn",
    runtimeStatusToken: (v) => v,
    request: async (url, options) => {
      requests.push(JSON.parse(JSON.stringify({ url, body: options.json })));
      if (++attempt === 1) throw new Error("network receipt lost");
      return { accepted: true, status: "queued" };
    },
  };
  vm.runInNewContext(section("function beginMessageSubmission", "function workflowStatus") + "\nglobalThis.send = postQueuedConversationMessage;", context);
  await assert.rejects(context.send("task-1", "为什么？"), /receipt lost/);
  assert.equal(state.messageSubmission.status, "failed");
  checkpoint = null; // A reconnect may no longer show the suspended card.
  await context.send("task-1", "为什么？");
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(requests[1].body.checkpoint_rpc_id, "rpc-1");
  assert.equal(state.messageSubmission, null);
});

test("a definitive stale-checkpoint rejection requires a fresh request identity", async () => {
  let sequence = 0;
  let checkpoint = { rpc_id: "stale" };
  const state = { selectedTaskId: "task-1", conversation: {} };
  const context = { state, currentHumanCheckpoint: () => checkpoint,
    createConversationRequestId: () => `request-${++sequence}` };
  vm.runInNewContext(section("function beginMessageSubmission", "function beginTaskCreationSubmission") + "\nglobalThis.begin = beginMessageSubmission;", context);
  const first = context.begin("task-1", "为什么？");
  const originalId = first.request_id;
  first.status = "failed";
  first.new_request_required = true;
  checkpoint = { rpc_id: "current" };
  const retry = context.begin("task-1", "为什么？");
  assert.notEqual(retry.request_id, originalId);
  assert.equal(retry.checkpoint_rpc_id, "current");
  assert.equal(retry.text, "为什么？");
});

test("a background continuation never borrows the selected task's checkpoint", () => {
  const context = { state: { selectedTaskId: "task-2", conversation: {} },
    currentHumanCheckpoint: () => ({ rpc_id: "task-2-checkpoint" }),
    createConversationRequestId: () => "request-1" };
  vm.runInNewContext(section("function beginMessageSubmission", "function beginTaskCreationSubmission") + "\nglobalThis.begin = beginMessageSubmission;", context);
  assert.equal(context.begin("task-1", "文件已导入").checkpoint_rpc_id, null);
});

test("approval waiting matches exact call lineage without relabelling a background action", () => {
  const checkpoint = { kind: "approval", call_id: "call-1", session_id: "session-1" };
  const context = { state: { conversation: {} }, currentHumanCheckpoint: () => checkpoint };
  vm.runInNewContext(section("function isWaitingForAnswerAction", "function actionTitle") + "\nglobalThis.label = actionStatusLabel;", context);
  const action = { status: "running", tool_name: "model_harness_confirm_contract", call_id: "call-1", session_id: "session-1" };
  assert.equal(context.label(action, { waitingForHuman: true }), "等待批准");
  assert.equal(context.label({ ...action, call_id: "background-call" }, { waitingForHuman: true }), "执行中");
  assert.equal(context.label({ ...action, session_id: "other-session" }, { waitingForHuman: true }), "执行中");
  assert.equal(context.label({ ...action, status: "failed" }, { waitingForHuman: true }), "执行失败");
});

test("ordinary long answers retain every paragraph and list without a technical disclosure", () => {
  const tags = [];
  const rendered = [];
  const element = (tag) => { tags.push(tag); return { dataset: {}, append() {} }; };
  const context = {
    ui: { messageList: element("main") }, document: { createElement: element },
    formatTime: () => "12:00", humanizeCoordinatorText: (v) => v,
    renderRichText: (_node, text) => rendered.push(text), appendCoordinatorNextAction() {},
  };
  vm.runInNewContext(section("function renderCoordinatorNote", "function roleLabel") + "\nglobalThis.render = renderCoordinatorNote;", context);
  const text = "这是完整的方案说明。".repeat(90) + "\n- 第一个方案\n- 第二个方案\n最后一段不能丢失";
  context.render({ text, time: "2026-09-10" });
  assert.deepEqual(rendered, [text]);
  assert.equal(tags.includes("details"), false);
});

test("rich tables cannot impose an intrinsic width on an entire AI turn", async () => {
  const css = await readFile(new URL("../../../model_harness/web/visual-system.css", import.meta.url), "utf8");
  assert.match(css, /body \.ai-turn-main,\s*body \.ai-turn-content\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(css, /body \.ai-turn-content > \*\s*\{\s*min-width: 0/);
  assert.match(css, /body \.rich-message table\s*\{\s*min-width: 100%/);
});
