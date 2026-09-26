import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => {
  const start = app.indexOf(from); const end = app.indexOf(to, start);
  assert.ok(start >= 0 && end > start, `${from} remains independently testable`);
  return app.slice(start, end);
};
const snapshot = (changes = {}) => ({
  schema_version: "2.0", event_payload_mode: "compact-v1", action_schema_version: "1.0", synthesis_verdict_version: "1.0",
  task_id: "task-1", session_id: "session-1", team_id: "team-1", running: false, execution_running: false,
  agent_response_running: false, background_action_running: false, can_cancel_agent: false, interaction_state: "terminal",
  items: [], events: [], actions: [], pending: [], runs: [], agents: [], delegations: [], projection_errors: [],
  agent_turns: [], background_actions: [], training_runs: [], supported_modes: ["queue_after_turn"],
  projection_health: "healthy", stream_health: { status: "healthy" }, ...changes,
});
const working = () => snapshot({ running: true, execution_running: true, agent_response_running: true, can_cancel_agent: true, interaction_state: "working" });
function element(tag = "div") {
  return { tag, dataset: {}, children: [], handlers: {}, hidden: false, disabled: false, value: "", textContent: "",
    append(...children) { this.children.push(...children); }, addEventListener(name, handler) { this.handlers[name] = handler; },
    setAttribute() {}, querySelectorAll: () => [], focus() {}, showModal() { this.open = true; }, close() { this.open = false; },
  };
}
function harness({ conversation = working(), request = async () => ({ conversation: snapshot() }) } = {}) {
  const state = { selectedTaskId: "task-1", selectionToken: 1, task: { task_id: "task-1" }, conversation,
    runtimeReady: true, composerStopRequests: new Map(), cancelRequestInFlight: false, productRuntime: { agent: { supported_modes: ["queue_after_turn"] } } };
  const ui = Object.fromEntries(["composerDelivery", "composerDeliveryLabel", "composerDeliveryDetail", "composerStopModifyButton", "composerWrap", "sendButton", "messageInput", "cancelAgentButton", "messageList", "agentWorking", "agentWorkingLabel", "dialogBody", "dialogActions", "dialogKicker", "dialogTitle", "decisionDialog"].map((id) => [id, element()]));
  ui.messageInput.value = "保留这条修改后的草稿";
  const calls = { requests: [], notices: [], drafts: [], sent: [], refreshes: 0 };
  const context = { state, ui, document: { createElement: element },
    currentHumanCheckpoint: (value) => value?.pending?.[0] || null,
    request: async (path, options) => { calls.requests.push({ path, options }); return request(path, options); },
    showNotice: (message, tone) => calls.notices.push({ message, tone }),
    saveDraft: (taskId = state.selectedTaskId) => calls.drafts.push({ taskId, text: ui.messageInput.value }),
    conversationTransportPath: (task, action = "snapshot") => `/tasks/${task}/conversation${action === "snapshot" ? "" : `/${action}`}`,
    clear: (node) => { node.children = []; }, setButtonBusy: (button, busy) => { button.dataset.busy = String(busy); },
    syncConversationComposerPlaceholder() {}, renderConversation() {},
    refreshSelected: async () => { calls.refreshes++; },
    window: { requestAnimationFrame: (fn) => fn(), setTimeout() {} },
    clearComposerRetry() {}, hideNotice() {}, clearDraft() {}, resizeComposer() {}, showTransientNotice() {},
    postQueuedConversationMessage: async (task, text) => calls.sent.push({ task, text }),
  };
  vm.runInNewContext([
    section("const BACKGROUND_TRAINING_STATUSES", "function createConversationRequestId"),
    section("function isCanonicalConversationSnapshot", "function acceptConversationSnapshot"),
    section("function syncCancelRequestUi", "function navigateToTrainingRecoveryCheckpoint"),
    section("async function submitMessage", "function deriveTaskName"),
  ].join("\n"), context);
  return { context, state, ui, calls };
}
function fence(state, changes = {}) {
  const value = { task_id: "task-1", snapshot_path: "/tasks/task-1/conversation", request_finished: true, checking: false, ...changes };
  state.composerStopRequests.set(value.task_id, value); return value;
}

test("active composer exposes queue and a separate explicit stop path, not fake intervention modes", () => {
  const { context, ui, calls } = harness();
  context.syncComposerDelivery();
  assert.equal(ui.composerDelivery.hidden, false);
  assert.equal(ui.composerDelivery.dataset.state, "queue");
  assert.match(ui.composerDeliveryDetail.textContent, /发送会排队/);
  assert.match(ui.composerDeliveryDetail.textContent, /实时干预和停止并替换暂不支持/);
  assert.equal(ui.composerStopModifyButton.textContent, "先停止，再修改");
  assert.equal(ui.composerStopModifyButton.disabled, false);
  assert.equal(calls.requests.length, 0);
});

test("background work does not force a new AI message to wait for that work", () => {
  const { context, ui } = harness({ conversation: snapshot({ background_action_running: true, execution_running: true }) });
  context.syncComposerDelivery();
  assert.equal(ui.composerDelivery.dataset.state, "background");
  assert.match(ui.composerDeliveryDetail.textContent, /不必等待后台结束/);
});

test("an explicit empty capability list overrides runtime defaults and cannot dispatch a queued message", async () => {
  const { context, ui, calls } = harness({ conversation: { ...working(), supported_modes: [] } });
  context.syncComposerDelivery();
  assert.equal(ui.composerDelivery.dataset.state, "unavailable");
  assert.equal(ui.sendButton.disabled, true);
  await context.submitMessage(ui.messageInput.value);
  assert.equal(calls.sent.length, 0);
  assert.equal(ui.messageInput.value, "保留这条修改后的草稿");
});

test("advertising unsupported intervention alone never changes the submitted mode", async () => {
  const { context, state, ui, calls } = harness({ conversation: { ...working(), supported_modes: ["intervene_current", "stop_and_replace"] } });
  await context.submitMessage(ui.messageInput.value);
  assert.equal(calls.sent.length, 0);
  state.conversation.supported_modes.push("queue_after_turn");
  await context.submitMessage(ui.messageInput.value);
  assert.equal(calls.sent.length, 1);
  assert.doesNotMatch(section("async function postQueuedConversationMessage", "function workflowStatus"), /mode:\s*"(?:intervene_current|stop_and_replace)"/);
});

test("unknown capability fails closed during execution but a human checkpoint remains a discussion", async () => {
  const { context, state, calls } = harness({ conversation: { ...working(), supported_modes: undefined } });
  state.productRuntime = null;
  await context.submitMessage("下一步");
  assert.equal(calls.sent.length, 0);
  state.conversation.pending = [{ kind: "approval", rpc_id: "approval-1" }];
  await context.submitMessage("为什么需要这一步？");
  assert.equal(calls.sent.length, 1);
});

test("busy send re-entry is a no-op instead of a second queue identity", async () => {
  const { context, ui, calls } = harness();
  ui.sendButton.dataset.busy = "true";
  await context.submitMessage(ui.messageInput.value);
  assert.equal(calls.sent.length, 0);
});

test("late success or failure never overwrites another task's composer draft or notices", async () => {
  for (const fail of [false, true]) {
    let finish;
    const { context, state, ui, calls } = harness();
    context.postQueuedConversationMessage = () => new Promise((resolve, reject) => { finish = fail ? () => reject(new Error("lost response")) : resolve; });
    const sending = context.submitMessage(ui.messageInput.value);
    state.selectedTaskId = "task-2"; state.selectionToken++; state.task = { task_id: "task-2" };
    ui.messageInput.value = "第二个任务的草稿";
    const notices = calls.notices.length;
    finish(); await sending;
    assert.equal(ui.messageInput.value, "第二个任务的草稿");
    assert.equal(calls.drafts.length, 0, "a late receipt must not save task-2 text under task-1");
    assert.equal(calls.notices.length, notices);
  }
});

test("editing the same task's draft during send keeps that new text on acceptance", async () => {
  let finish;
  const { context, ui } = harness();
  context.postQueuedConversationMessage = () => new Promise((resolve) => { finish = resolve; });
  const sending = context.submitMessage(ui.messageInput.value);
  ui.messageInput.value = "发送等待期间补充的新草稿";
  finish(); await sending;
  assert.equal(ui.messageInput.value, "发送等待期间补充的新草稿");
});

test("automatic upload continuations cannot queue while that exact task has an unresolved stop", async () => {
  const { context, state, calls } = harness();
  fence(state);
  state.selectedTaskId = "task-2";
  context.createConversationRequestId = () => "new-request";
  vm.runInNewContext(section("function beginMessageSubmission", "function workflowStatus"), context);
  await assert.rejects(context.postQueuedConversationMessage("task-1", "文件已导入"), /停止状态尚未确认/);
  assert.equal(calls.requests.length, 0);
  assert.equal(state.messageSubmission, undefined, "no new request identity is allocated");
});

test("stop confirmation requires a complete exact-task healthy observation of no execution", () => {
  const { context } = harness();
  const confirmed = snapshot({ agent_turns: [{ task_id: "task-1", status: "cancelled", response_running: false }], background_actions: [{ task_id: "task-1", status: "cancelled", cancel_requested: true, running: false, worker_running: false }] });
  assert.equal(context.composerStopSnapshotConfirmed(confirmed, "task-1"), true);
  for (const changes of [
    { task_id: "task-2" }, { projection_health: "observation_degraded" }, { agent_response_running: true },
    { agent_response_running: undefined }, { background_action_running: true }, { execution_running: true }, { running: true },
    { pending: [{ kind: "approval" }] }, { interaction_state: "cancelling" }, { background_actions: undefined },
    { background_actions: [{ task_id: "task-1", status: "cancel_requested", running: false }] },
    { background_actions: [{ task_id: "task-1", status: "observation_degraded", running: false }] },
    { background_actions: [{ task_id: "task-1", status: "failed", domain_status: "observation_degraded" }] },
    { background_actions: [{ task_id: "task-1", status: "cancelled", worker_running: true }] },
    { agent_turns: [{ task_id: "task-1", status: "cancelled", response_running: true }] },
    { agent_turns: [{ task_id: "task-2", status: "cancelled" }] },
    { agent_turns: [{ task_id: "task-1" }] },
  ]) assert.equal(context.composerStopSnapshotConfirmed({ ...confirmed, ...changes }, "task-1"), false, JSON.stringify(changes));
});

test("cancel HTTP success and an old idle view cannot release the send fence", async () => {
  const { context, state, ui, calls } = harness({ conversation: snapshot(), request: async () => ({ accepted: true }) });
  fence(state);
  await context.verifyComposerStop();
  await context.submitMessage(ui.messageInput.value);
  assert.equal(state.composerStopRequests.has("task-1"), true);
  assert.equal(ui.sendButton.disabled, true);
  assert.equal(calls.sent.length, 0);
  assert.equal(calls.requests[0].options, undefined, "verification is read-only");
});

test("verification cannot start before cancel settles and failure preserves the draft and fence", async () => {
  const { context, state, ui, calls } = harness({ request: async () => { throw new Error("snapshot unavailable"); } });
  const stop = fence(state, { request_finished: false });
  assert.equal(await context.verifyComposerStop(), false);
  assert.equal(calls.requests.length, 0);
  stop.request_finished = true;
  assert.equal(await context.verifyComposerStop(), false);
  assert.equal(state.composerStopRequests.get("task-1"), stop);
  assert.equal(ui.messageInput.value, "保留这条修改后的草稿");
  assert.equal(ui.sendButton.disabled, true);
});

test("a confirmed stop permits a later manual send but never sends the preserved draft automatically", async () => {
  const { context, state, ui, calls } = harness({ conversation: snapshot() });
  fence(state);
  assert.equal(await context.verifyComposerStop(), true);
  assert.equal(state.composerStopRequests.has("task-1"), false);
  assert.equal(ui.sendButton.disabled, false);
  assert.equal(ui.messageInput.value, "保留这条修改后的草稿");
  assert.equal(calls.sent.length, 0);
  await context.submitMessage(ui.messageInput.value);
  assert.equal(calls.sent.length, 1);
});

test("late stop evidence cannot clear another task's fence or change its draft and notices", async () => {
  let finish;
  const { context, state, ui, calls } = harness({ request: () => new Promise((resolve) => { finish = resolve; }) });
  fence(state);
  const checking = context.verifyComposerStop();
  state.selectedTaskId = "task-2"; state.selectionToken++; state.task = { task_id: "task-2" };
  const second = fence(state, { task_id: "task-2", snapshot_path: "/tasks/task-2/conversation" });
  ui.messageInput.value = "第二个任务的草稿";
  const notices = calls.notices.length;
  finish({ conversation: snapshot() }); await checking;
  assert.equal(state.composerStopRequests.get("task-2"), second);
  assert.equal(ui.messageInput.value, "第二个任务的草稿");
  assert.equal(calls.notices.length, notices);
});

test("stop entry only saves draft and opens explicit scope confirmation", () => {
  const { context, ui, calls } = harness();
  context.stopBeforeComposerChange();
  assert.equal(ui.decisionDialog.open, true);
  assert.equal(calls.requests.length, 0);
  assert.match(ui.dialogBody.children[0].textContent, /当前 AI.*本任务/);
  assert.match(ui.dialogBody.children[0].textContent, /不会自动替换消息/);
  assert.equal(calls.drafts[0].text, "保留这条修改后的草稿");
});

test("an old stop confirmation cannot target a newly selected or archived task", async () => {
  for (const change of [(state) => { state.selectedTaskId = "task-2"; state.selectionToken++; }, (state) => { state.task.archived_at_utc = "now"; }]) {
    const { context, state, ui, calls } = harness();
    context.openCancelAgentDialog();
    ui.dialogBody.children[1].children[1].value = "需求调整";
    change(state);
    await ui.dialogActions.children[1].handlers.click();
    assert.equal(calls.requests.length, 0);
    assert.equal(state.composerStopRequests.size, 0);
  }
});

test("stop confirmation needs no typed reason and records the explicit UI action by default", async () => {
  for (const value of ["", "   "]) {
    const { context, ui, calls } = harness({ request: async (_path, options) => options?.method === "POST" ? { accepted: true } : { conversation: snapshot() } });
    context.openCancelAgentDialog();
    assert.equal(ui.dialogBody.children[1].children[0].textContent, "备注（可选）");
    assert.equal(ui.dialogActions.children[1].disabled, false);
    ui.dialogBody.children[1].children[1].value = value;
    await ui.dialogActions.children[1].handlers.click();
    assert.equal(calls.requests[0].options.json.reason, "用户在工作台请求停止当前任务执行");
    assert.equal(calls.requests[0].options.method, "POST");
  }
});

test("an optional stop remark is sent as the user's original text", async () => {
  const { context, ui, calls } = harness({ request: async (_path, options) => options?.method === "POST" ? { accepted: true } : { conversation: snapshot() } });
  context.openCancelAgentDialog();
  const remark = "  我想先调整输入范围，再继续。  ";
  ui.dialogBody.children[1].children[1].value = remark;
  await ui.dialogActions.children[1].handlers.click();
  assert.equal(calls.requests[0].options.json.reason, remark);
});

test("confirmed cancel uses exact task path then a fresh read, retaining unresolved stop and draft", async () => {
  const { context, state, ui, calls } = harness({ request: async (_path, options) => options?.method === "POST" ? { accepted: true } : { conversation: working() } });
  context.openCancelAgentDialog();
  ui.dialogBody.children[1].children[1].value = "需求调整";
  await ui.dialogActions.children[1].handlers.click();
  assert.deepEqual(calls.requests.map(({ path, options }) => [path, options?.method || "GET"]), [["/tasks/task-1/conversation/cancel", "POST"], ["/tasks/task-1/conversation", "GET"]]);
  assert.equal(state.composerStopRequests.has("task-1"), true);
  assert.equal(ui.sendButton.disabled, true);
  assert.equal(ui.messageInput.value, "保留这条修改后的草稿");
  assert.equal(calls.sent.length, 0);
});

test("failed cancel permits another explicit stop request without dropping the unresolved fence", async () => {
  const { context, state, ui, calls } = harness({ request: async (_path, options) => { if (options?.method === "POST") throw new Error("partial cascade"); return { conversation: working() }; } });
  context.openCancelAgentDialog(); ui.dialogBody.children[1].children[1].value = "需求调整";
  await ui.dialogActions.children[1].handlers.click();
  const firstFence = state.composerStopRequests.get("task-1");
  assert.equal(firstFence.rpc_failed, true);
  assert.equal(ui.composerStopModifyButton.textContent, "重试停止");
  context.stopBeforeComposerChange();
  assert.equal(ui.decisionDialog.open, true);
  assert.equal(state.composerStopRequests.get("task-1"), firstFence);
  assert.equal(calls.requests.length, 2, "opening a retry dialog is not another cancellation");
});
