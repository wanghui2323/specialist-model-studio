import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length));
const tick = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
function snapshot(id, text = `对话 ${id}`) {
  return { schema_version: "2.0", task_id: id, event_payload_mode: "compact-v1", action_schema_version: "1.0", synthesis_verdict_version: "1.0", session_id: `session-${id}`, team_id: "team", running: false, execution_running: false, can_cancel_agent: false, agent_response_running: false, background_action_running: false, interaction_state: "idle", interaction_projection: { schema_version: "1.0", phase: "idle", can_cancel: false }, items: [{ text }], events: [], actions: [], pending: [], runs: [], agents: [], delegations: [], projection_errors: [], human_checkpoints: [], stream_health: { status: "healthy" }, projection_health: "healthy" };
}
class Node {
  constructor() { this.dataset = {}; this.attributes = {}; this.children = []; this.disabled = false; this.hidden = false; this.value = ""; this.textContent = ""; this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  close() { this.open = false; }
}
function fixture() {
  const ui = new Proxy({}, { get: (object, key) => object[key] ||= new Node() });
  const pending = new Map(), writes = [], drafts = new Map([["task-b", "B 已存草稿"], ["draft-b", "未发送的补充"]]), state = {
    selectedTaskId: "task-a", task: { task_id: "task-a", name: "任务 A" }, conversation: snapshot("task-a", "A 私有对话"), runtimeReady: true,
    tasks: ["a", "b", "c"].map(id => ({ task_id: `task-${id}`, name: `任务 ${id.toUpperCase()}` })), selectionToken: 1, refreshSeq: 0,
    conversationReconcileSeq: 0, runEvents: [], taskSpecRevisions: [], lastRenderKey: "old-a", materialInspections: [],
  };
  ui.messageInput.value = "A 未发送草稿"; ui.messageList.append({ textContent: "A 私有对话" }, { textContent: "批准 A 的工程验证" }); ui.decisionDialog.open = true;
  const f = { state, ui, checkpointCards: [new Node()], document: { body: { dataset: {} }, createElement: () => new Node() },
    location: { pathname: "/studio" }, history: { replaceState: (_a, _b, url) => { f.url = url; } }, window: { setInterval: () => 1 }, requestAnimationFrame: callback => callback(),
    clear: node => node.replaceChildren(), saveDraft: () => drafts.set(state.selectedTaskId, ui.messageInput.value), restoreDraft: id => { ui.messageInput.value = drafts.get(id) || ""; },
    stopPolling() { state.conversationReconcileSeq += 1; state.conversationReconcileInFlight = false; state.conversationReconcilePromise = null; state.conversationStreamDegraded = false; },
    request(path, options = {}) {
      if (options.method === "POST") { writes.push(path); return Promise.resolve({}); }
      if (/\/(tasks|conversations)\/[^/]+$/.test(path) || path.endsWith("/conversation")) return new Promise((resolve, reject) => pending.set(path, { resolve, reject }));
      return Promise.resolve({ resolutions: [], searches: [], revisions: [] });
    },
    syncComposerAttachmentOwner() {}, clearComposerRetry() {}, hideNotice() {}, restoreCheckpointCard() {}, resetHfDiscovery() {}, resetModelSourceDiscovery() {}, resetRunEvidence() {}, renderTaskList() {}, closeSidebar() {}, closeInspector() {}, startConversationStream() {},
    loadMaterialInspections: async () => {}, reconcileComposerDatasetUpload: async () => {}, loadTasks: async () => {}, loadRunEvidence: async () => {}, modelSourceBlocker: () => null, showNotice: message => { f.notice = message; },
    clearConnectionNotice() {}, clearObservedPendingMessage() {}, clientDegradedConversation: value => value,
    renderTask(task) { ui.taskTitle.textContent = task.name; if (state.selectionLoadingOwnerId) f.renderSelectionLoading(); },
    renderComposerAttachment() {}, renderMaterialControls() {}, renderMaterialHistory() {}, flushDeferredMaterialContinuations() {},
    conversationView: (_task, value) => value, interactionProjection: (_task, value) => ({ turns: value.items, workspace: {}, phase: "idle" }),
    projectionWorkItems: () => [], activeProjectionSpecialists: () => [], syncConversationComposerPlaceholder() {}, syncTaskHeader: task => { ui.taskTitle.textContent = task.name; },
    syncTaskSpecCheckpointOwnership() {}, syncLegacyConfirmationControls() {}, syncSelectedTaskListStatus() {}, conversationObservationKey: () => "", queuedConversationMessages: () => [], syncAgentCheckpoint() {}, activeBackgroundTrainingRun: () => null, backgroundCancellationPending: () => false,
    captureConversationViewport: () => ({}), restoreConversationViewport() {}, renderProjectionHealth() {}, renderAgentSurfaceState() {}, renderConversationTurn: turn => ui.messageList.append({ textContent: turn.text }), renderWorkspaceExperience() {}, conversationAgentResponseRunning: () => false, conversationHasBackgroundTraining: () => false, agentActivityLabel: () => "", currentHumanCheckpoint: () => null,
    setButtonBusy() {}, renderRuntimeMode() {}, updateComposerAttachment() {}, createConversationRequestId: () => "request", materialInspectionMode: () => true,
  };
  vm.runInNewContext(section("function isConversationDraft", "function renderRuntimeMode") + section("function renderSelectionLoading", "function conversationStreamEntryKey") + section("function isCanonicalConversationSnapshot", "function closeConversationEventSource") + section("function renderConversation(force", "function actionsForTurn") + section("function syncComposerDelivery", "function queuedConversationMessages") + section("function syncCancelRequestUi", "function openCancelAgentDialog") + section("async function submitMessage", "function deriveTaskName") + section("function stageComposerAttachment", "async function resumeNewConversationAttachment") + section("async function answerApproval", "function openQuestionDialog") + "\nglobalThis.api={selectTask,selectConversation,acceptConversationSnapshot,renderConversation,syncCancelRequestUi,submitMessage,stageComposerAttachment,answerApproval,postQuestionAnswers};", f);
  return { f, state, ui, pending, writes, drafts };
}
async function releaseOwner(test, id, { draft = false } = {}) {
  const path = `/${draft ? "conversations" : "tasks"}/${id}`;
  assert.ok(test.pending.has(path), path);
  test.pending.get(path).resolve(draft ? { conversation: { conversation_id: id, status: "unbound", title: "目标草稿" } } : { task: { task_id: id, name: `任务 ${id.at(-1).toUpperCase()}`, status: "ready", current_spec_revision: 1 } });
  await tick();
}
async function releaseSnapshot(test, id, { draft = false, value = snapshot(id) } = {}) {
  const path = `/${draft ? "conversations" : "tasks"}/${id}/conversation`; assert.ok(test.pending.has(path), path);
  test.pending.get(path).resolve({ conversation: value }); await tick();
}

test("delayed task switch clears the old dialogue and approvals synchronously while keeping the destination draft editable", async () => {
  const t = fixture(), promise = t.f.api.selectTask("task-b");
  assert.equal(t.ui.messageList.children.length, 1); assert.equal(t.ui.messageList.children[0].dataset.state, "loading");
  assert.equal(t.ui.taskTitle.textContent, "任务 B"); assert.equal(t.ui.decisionDialog.open, false); assert.equal(t.state.task, null);
  assert.equal(t.ui.sendButton.disabled, true); assert.equal(t.ui.datasetButton.disabled, true); assert.equal(t.ui.datasetInput.disabled, true); assert.equal(t.ui.messageInput.disabled, false);
  assert.equal(t.ui.messageInput.value, "B 已存草稿"); assert.equal(t.drafts.get("task-a"), "A 未发送草稿");
  t.ui.messageInput.value = "B 新草稿"; await t.f.api.submitMessage(t.ui.messageInput.value); t.f.api.stageComposerAttachment({ name: "private.csv" });
  await t.f.api.answerApproval({ rpc_id: "old-a", task_id: "task-a" }, "allowed-once", new Node());
  assert.equal(t.drafts.get("task-b"), "B 新草稿"); assert.equal(t.writes.length, 0); assert.equal(t.state.composerAttachment, undefined);
  await releaseOwner(t, "task-b"); assert.equal(t.state.selectionLoadingOwnerId, "task-b"); assert.equal(t.ui.sendButton.disabled, true);
  t.f.api.syncCancelRequestUi(); assert.equal(t.ui.sendButton.disabled, true);
  await releaseSnapshot(t, "task-b"); await promise;
  assert.equal(t.state.selectionLoadingOwnerId, null); assert.equal(t.ui.sendButton.disabled, false); assert.equal(t.ui.datasetInput.disabled, false);
  assert.deepEqual(t.ui.messageList.children.map(item => item.textContent), ["对话 task-b"]); assert.equal(t.ui.messageInput.value, "B 新草稿");
  await t.f.api.answerApproval({ rpc_id: "old-a" }, "allowed-once", new Node()); assert.equal(t.writes.length, 0, "a detached old card cannot post into the new owner even without task_id");
});

test("draft conversation selection also hides old task content until its own canonical snapshot arrives", async () => {
  const t = fixture(), promise = t.f.api.selectConversation("draft-b");
  assert.equal(t.ui.messageList.children[0].dataset.state, "loading"); assert.equal(t.ui.messageInput.value, "未发送的补充"); assert.equal(t.ui.datasetButton.disabled, true);
  await releaseOwner(t, "draft-b", { draft: true }); await releaseSnapshot(t, "draft-b", { draft: true }); await promise;
  assert.equal(t.state.conversation.task_id, "draft-b"); assert.equal(t.state.selectionLoadingOwnerId, null); assert.equal(t.ui.sendButton.disabled, false);
  assert.deepEqual(t.ui.messageList.children.map(item => item.textContent), ["对话 draft-b"]);
});

test("out-of-order owner responses cannot paint a previous selection over the new target", async () => {
  const t = fixture(), b = t.f.api.selectTask("task-b");
  await releaseOwner(t, "task-b");
  const c = t.f.api.selectTask("task-c"); await releaseOwner(t, "task-c");
  await releaseSnapshot(t, "task-c"); await c;
  await releaseSnapshot(t, "task-b"); await b;
  assert.equal(t.state.selectedTaskId, "task-c"); assert.equal(t.state.conversation.task_id, "task-c"); assert.equal(t.ui.taskTitle.textContent, "任务 C");
  assert.deepEqual(t.ui.messageList.children.map(item => item.textContent), ["对话 task-c"]);
});

test("wrong-owner snapshots stay loading and same-owner refresh keeps already displayed history", async () => {
  const t = fixture(), b = t.f.api.selectTask("task-b"); await releaseOwner(t, "task-b");
  await releaseSnapshot(t, "task-b", { value: snapshot("task-a", "wrong owner") }); await b;
  assert.equal(t.state.selectionLoadingOwnerId, "task-b"); assert.equal(t.ui.sendButton.disabled, true); assert.equal(t.ui.messageList.children.length, 1); assert.equal(t.ui.messageList.children[0].dataset.state, "loading");
  const u = fixture(), refresh = u.f.api.selectTask("task-a");
  assert.equal(u.ui.messageList.children[0].textContent, "A 私有对话"); assert.equal(u.state.conversation.task_id, "task-a");
  await releaseOwner(u, "task-a"); await releaseSnapshot(u, "task-a"); await refresh;
  assert.equal(u.ui.messageList.children[0].textContent, "对话 task-a");
});
