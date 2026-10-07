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
  assert.equal(blocker.title, "方案匹配记录");
  assert.equal(blocker.rows[3][1], "否");
  assert.match(blocker.note, /目标仍可继续准备方案/);
  const unsafe = context.present({ type: "blocker" }, { blocker: { code: "blocked_security", message: "禁止执行不安全代码", rule: { run_creation_allowed: false } } });
  assert.equal(unsafe.title, "当前阻断原因"); assert.equal(unsafe.rows[3][1], "不允许");
});

test("completed evidence header never overrides an active checkpoint or failure", () => {
  const source = section("function renderWorkspaceExperience", "function workspaceContextForPhase");
  const expression = source.match(/const displayPhase = ([^;]+);/)[1];
  const expressionWithCapabilities = section("function pendingExecutionIntegration", "function workflowStatus") + "\n" + expression;
  for (const phase of ["executing", "clarifying", "awaiting_approval", "blocked"]) {
    assert.equal(vm.runInNewContext(expressionWithCapabilities, { task: {}, conversation: null, projection: { phase }, evaluationOutcome: { ready: true } }), phase);
  }
  assert.equal(vm.runInNewContext(expressionWithCapabilities, { task: {}, conversation: null, projection: { phase: "idle" }, evaluationOutcome: { ready: true } }), "result_ready");
  assert.equal(vm.runInNewContext(expressionWithCapabilities, { task: {}, conversation: null, projection: { phase: "idle" }, evaluationOutcome: { ready: false } }), "idle");
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

test("specialist termination never claims the coordinator stopped or exposes whole-turn recovery", () => {
  const rendered = []; let recoveries = 0;
  const context = { roleLabel: () => "研究与来源", appendObjectRefs() {}, appendRecoveryActions() { recoveries++; },
    ui: { messageList: { append: (node) => rendered.push(node) } },
    document: { createElement: (tag) => ({ tag, dataset: {}, children: [], append(...children) { this.children.push(...children); } }) } };
  vm.runInNewContext(section("function terminalEventScope", "function renderEvidenceLedger") + "\nglobalThis.scope = terminalEventScope; globalThis.render = renderTurnTerminal;", context);
  const root = { kind: "turn_cancelled", session_id: "root", root_session_id: "root", summary: "stopped" };
  context.render({ ...root, session_id: "child", delegation_id: "delegation", actor_role: "research_source" });
  assert.equal(rendered[0].tag, "details");
  assert.equal(rendered[0].children[0].textContent, "研究与来源的本次执行已停止");
  assert.equal(recoveries, 0);
  context.render({ ...root, session_id: undefined });
  assert.equal(rendered[1].dataset.terminalScope, "unknown");
  assert.equal(recoveries, 0);
  context.render(root);
  assert.equal(rendered[2].children[0].textContent, "本轮智能体已停止");
  assert.equal(recoveries, 1);
  assert.equal(context.scope({ ...root, delegation_id: "conflicting" }), "unknown");
  assert.match(section("function aiTurnPresentation", "function createAiTurnContainer"), /terminalEventScope\(item\) === "root"/);
});

test("completed cancellation audit flags do not keep a training entry live", () => {
  const context = { BACKGROUND_CANCELLING_STATUSES: new Set(["cancel_requested", "cancelling", "stopping"]), BACKGROUND_TRAINING_STATUSES: new Set(["running", "cancel_requested"]), runtimeStatusToken: (v) => String(v || "").toLowerCase() };
  vm.runInNewContext(section("function trainingEntryCancelling", "function activeBackgroundTrainingRun") + "\nglobalThis.cancelling=trainingEntryCancelling; globalThis.running=trainingEntryRunning;", context);
  const finished = { status: "cancelled", domain_status: "cancelled", cancel_requested: true, running: false, worker_running: false };
  assert.equal(context.cancelling(finished), false);
  assert.equal(context.running(finished), false);
  assert.equal(context.cancelling({ ...finished, worker_running: true }), true);
  assert.equal(context.running({ ...finished, worker_running: true }), true);
  assert.equal(context.cancelling({ ...finished, status: "cancel_requested" }), true);
});

test("native approval labels use the tool identity, never generic data or compute prose", () => {
  const context = {};
  vm.runInNewContext(section("function approvalPresentation", "function appendApprovalScope") + "\nglobalThis.present = approvalPresentation;", context);
  const reason = "changes local task, data, compute, or approval state; start training and artifact bundle";
  const binding = context.present({ tool_name: "model_harness_bind_model_source", reason });
  assert.equal(binding.allow, "确认绑定并分析");
  assert.match(binding.copy, /不代表批准下载权重、安装代码或训练/);
  assert.equal(context.present({ tool_name: "model_harness_import_dataset", reason }).title, "批准导入并体检这份数据");
  const reuse = context.present({ tool_name: "model_harness_import_material_dataset", reason });
  assert.equal(reuse.title, "复用已上传材料导入"); assert.equal(reuse.allow, "批准导入并体检"); assert.equal(reuse.reject, "暂不导入");
  assert.match(reuse.copy, /无需重新上传/); assert.match(reuse.copy, /本次批准不会启动训练/);
  assert.equal(context.present({ tool_name: "unrecognized_action", reason }).title, "批准关键操作");
  assert.equal(context.present({ reason: "dataset train contract" }).title, "批准关键操作");
  for (const [tool_name, allow] of [
    ["model_harness_authorize_task_run_start", "开始训练"],
    ["model_harness_confirm_contract", "确认标准"],
    ["model_harness_authorize_artifact_bundle_build", "生成模型包"],
    ["model_harness_download_artifact_bundle", "下载模型包"],
    ["model_harness_authorize_sample_inference", "开始试用"],
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
    assert.equal(vm.runInNewContext(expression, { current: false, settled: false, projection: { phase } }), "historical");
  }
  assert.equal(vm.runInNewContext(expression, { current: true, settled: false, projection: { phase: "awaiting_approval" } }), "waiting_for_human");
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

test("an unavailable AI service shows one actionable connection card without duplicate stream alerts", () => {
  const rendered = [];
  class Node {
    constructor() { this.dataset = {}; this.children = []; this.textContent = ""; }
    append(...children) { this.children.push(...children); }
    setAttribute() {}
    addEventListener() {}
  }
  const context = { state: { runtimeReady: false, conversation: { session_id: "saved-session" }, conversationStreamDegraded: true },
    ui: { messageList: { append: node => rendered.push(node) } }, document: { createElement: () => new Node() } };
  vm.runInNewContext(section("function renderProjectionHealth", "function renderConversation(") + "\nglobalThis.render={renderProjectionHealth,renderAgentSurfaceState};", context);
  const saved = { session_id: "saved-session", projection_health: { status: "observation_degraded" } };
  context.render.renderProjectionHealth(saved);
  context.render.renderAgentSurfaceState(saved, {});
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].dataset.state, "unavailable");
  assert.equal(rendered[0].children[1].children[0].textContent, "AI 服务未连接，对话已暂停");
  assert.equal(rendered[0].children[1].children[1].textContent, "可以查看已保存的任务与证据，恢复连接后继续对话。");
  assert.equal(rendered[0].children[2].textContent, "重新检查连接");
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
      clearComposerRetry() {}, hideNotice() {}, clearDraft() {}, resizeComposer() {}, resumeNewConversationAttachment: async () => {},
      showTransientNotice() {}, refreshSelected() {}, syncComposerDelivery() {},
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
    conversationAgentResponseRunning: () => false, clearObservedPendingMessage() {},
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

test("message submission stays quiet on ordinary and queued success while checkpoint and failure feedback remain", async () => {
  for (const scenario of ["ordinary", "created", "queued", "checkpoint", "failed"]) {
    const text = "请继续", notices = [], transient = [], retries = [];
    let activeNotice = "上一条提示";
    const state = { runtimeReady: true, selectedTaskId: scenario === "created" ? null : "task-1", conversation: {} };
    const ui = { sendButton: { dataset: {} }, messageInput: { value: text } };
    const context = {
      state, ui, clearComposerRetry() {}, hideNotice() { activeNotice = null; }, clearDraft() {}, saveDraft() {}, resizeComposer() {}, resumeNewConversationAttachment: async () => {}, renderConversation() {}, refreshSelected() {}, syncComposerDelivery() {},
      showNotice(value) { notices.push(value); activeNotice = value; },
      showTransientNotice(value) { transient.push(value); activeNotice = value; },
      showComposerRetry(value) { retries.push(value); },
      backgroundCancellationPending: () => false,
      currentHumanCheckpoint: () => scenario === "checkpoint" ? { kind: "approval", rpc_id: "approval-1" } : null,
      conversationAgentResponseRunning: () => scenario === "queued",
      beginTaskCreationSubmission: () => ({ create_request_id: "create-1", request_id: "message-1" }),
      runtimeStatusToken: value => value,
      request: async () => ({ created: true, submission: { accepted: true, status: "queued" }, conversation: { conversation_id: "conversation-1" } }),
      selectConversation: async id => { state.selectedTaskId = id; },
      postQueuedConversationMessage: async () => {
        if (scenario === "failed") {
          state.messageSubmission = { status: "failed", task_id: "task-1", text, request_id: "message-1" };
          throw new Error("网络中断");
        }
        return { accepted: true };
      },
      window: { setTimeout() {} },
    };
    vm.runInNewContext(section("async function submitMessage", "function deriveTaskName") + "\nglobalThis.submit = submitMessage;", context);
    await context.submit(text);
    assert.equal(ui.sendButton.disabled, false, scenario);
    if (scenario === "ordinary" || scenario === "created") {
      assert.equal(activeNotice, null, `${scenario}: accepted messages must not leave a success banner`);
      assert.equal(transient.length, 0, scenario);
      assert.equal(ui.messageInput.value, "", scenario);
      assert.equal(notices.length, scenario === "created" ? 1 : 0, scenario);
      if (scenario === "created") assert.match(notices[0], /正在开始对话/);
    } else if (scenario === "queued") {
      assert.equal(activeNotice, null); assert.equal(transient.length, 0); assert.equal(ui.messageInput.value, "");
    } else if (scenario === "checkpoint") {
      assert.equal(transient.length, 1); assert.match(transient[0], /已暂缓当前确认.*没有批准执行或提交答案/);
    } else {
      assert.match(activeNotice, /消息发送失败.*网络中断/);
      assert.equal(retries.length, 1); assert.equal(retries[0].label, "重试发送");
      assert.equal(ui.messageInput.value, text); assert.equal(transient.length, 0);
    }
  }
});

test("queue feedback stays beside a nonempty draft or its exact submitted user message and clears on handoff", async () => {
  const element = () => ({ children: [], dataset: {}, attrs: {}, append(...nodes) { this.children.push(...nodes); }, setAttribute(key, value) { this.attrs[key] = value; } });
  const ui = { composerHint: element(), sendButton: element(), messageInput: { value: "" }, messageList: element() };
  const state = { runtimeReady: true, selectedTaskId: "task-1", conversation: { agent_response_running: true, items: [], pending: [], runs: [] } };
  const context = { state, ui, document: { createElement: element }, formatTime: () => "12:00",
    createConversationRequestId: () => "request-new", renderConversation() {}, runtimeStatusToken: value => value,
    conversationTransportPath: () => "/tasks/task-1/conversation/messages", DEFAULT_CONVERSATION_MESSAGE_MODE: "queue_after_turn",
    request: async () => ({ accepted: true, status: "queued", agent_run_id: "run-new" }),
  };
  const functions = section("function isPendingHumanCheckpoint", "const DATA_UPLOAD_QUESTION_IDS")
    + section("function conversationAgentResponseRunning", "function conversationTrainingEntries")
    + section("function syncComposerDelivery", "function createConversationRequestId")
    + section("function beginMessageSubmission", "function pendingExecutionIntegration")
    + section("function clearObservedPendingMessage", "function clientDegradedConversation")
    + section("function renderMessage", "function appendInlineMarkdown");
  vm.runInNewContext(functions + "\nglobalThis.api={syncComposerDelivery,postQueuedConversationMessage,clearObservedPendingMessage,queuedConversationMessages,renderMessage};", context);
  const { api } = context;
  for (const value of ["", " \n "]) {
    ui.messageInput.value = value; api.syncComposerDelivery();
    assert.equal(ui.composerHint.dataset.delivery, "immediate"); assert.equal(ui.sendButton.attrs["aria-label"], "发送消息");
  }
  ui.messageInput.value = "同一句消息"; api.syncComposerDelivery();
  assert.equal(ui.composerHint.textContent, "等待回复后发送"); assert.equal(ui.sendButton.attrs["aria-label"], "等待回复后发送");
  state.conversation.agent_response_running = false;
  for (const background of [false, true]) {
    state.conversation.background_action_running = background; api.syncComposerDelivery();
    assert.equal(ui.composerHint.dataset.delivery, "immediate"); assert.match(ui.composerHint.textContent, /^Enter 发送/);
  }
  state.conversation.agent_response_running = true;
  state.conversation.pending = [{ kind: "approval", rpc_id: "approval-1", status: "pending" }];
  api.syncComposerDelivery(); assert.equal(ui.sendButton.attrs["aria-label"], "发送消息");
  state.conversation.pending = [];
  const oldMessage = { kind: "message", role: "user", text: "同一句消息", agent_run_id: "run-old" };
  state.conversation.items = [oldMessage];
  const submission = api.postQueuedConversationMessage("task-1", "同一句消息");
  api.clearObservedPendingMessage("task-1", state.conversation);
  assert.equal(state.pendingMessage.request_id, "request-new", "same-text history cannot clear a request before its server identity arrives");
  await submission;
  assert.equal(state.pendingMessage.delivery, "queued"); assert.equal(state.pendingMessage.agent_run_id, "run-new");
  assert.equal(state.pendingMessage.request_id, "request-new", "an older identical message must not claim this request");
  api.renderMessage({ ...state.pendingMessage, role: "user" }); api.renderMessage(oldMessage);
  const labels = ui.messageList.children.map(row => row.children[1].children[0].children[1].textContent);
  assert.deepEqual(labels, ["等待回复后发送", "12:00"]);
  state.conversation.runs = [
    { run_id: "run-old", status: "completed", user_message: "同一句消息" },
    { run_id: "run-new", status: "queued", user_message: "同一句消息", composer_request: { request_id: "request-new" } },
  ];
  api.clearObservedPendingMessage("task-1", state.conversation);
  assert.equal(state.pendingMessage, null, "canonical queue evidence replaces the optimistic copy");
  assert.deepEqual([...api.queuedConversationMessages(state.conversation)].map(item => item.agent_run_id), ["run-new"]);
  const keyExpression = section("function renderConversation(", "function actionsForTurn").match(/const renderKey = (JSON\.stringify[^\n]+);/)[1];
  const renderKey = () => vm.runInNewContext(keyExpression, { state, conversation: state.conversation,
    projection: { phase: "executing", workspace: {} }, backgroundRun: null, observation: "same", optimistic: null,
    queuedMessages: api.queuedConversationMessages(state.conversation) });
  const queuedKey = renderKey();
  state.conversation.items.push({ ...oldMessage, agent_run_id: "run-new" });
  assert.equal(api.queuedConversationMessages(state.conversation).length, 0, "an observed user message is no longer rendered as waiting");
  state.conversation.items.pop(); state.conversation.runs[1].status = "running";
  assert.equal(api.queuedConversationMessages(state.conversation).length, 0);
  assert.notEqual(renderKey(), queuedKey, "a canonical queue transition must invalidate the renderer cache even when messages are unchanged");
});


test("home conversation creation marks only a new local attachment and preserves failed request identity", () => {
  for (const [attachment, expectedPrefix] of [[null, false], [{ file: { name: "data.zip" }, task_id: null }, true], [{ file: { name: "old.csv" }, task_id: "task-other" }, false]]) {
    let sequence = 0; const state = { selectedTaskId: null, composerAttachment: attachment, messageSubmission: null };
    const context = { state, createConversationRequestId: () => `request-${++sequence}` };
    vm.runInNewContext(section("function beginTaskCreationSubmission", "async function postQueuedConversationMessage") + "\nglobalThis.begin = beginTaskCreationSubmission;", context);
    const first = context.begin("请检查材料并给出方案"); const requestId = first.request_id, createId = first.create_request_id;
    assert.equal(requestId.startsWith("material-intake-"), expectedPrefix);
    assert.equal(createId, "request-1", "creation identity itself does not signal a material upload");
    first.status = "failed"; state.composerAttachment = null;
    const retry = context.begin("请检查材料并给出方案");
    assert.equal(retry.request_id, requestId); assert.equal(retry.create_request_id, createId); assert.equal(sequence, 2);
    assert.equal(retry.material_id, undefined); assert.equal(retry.execution_authorized, undefined);
  }
});
