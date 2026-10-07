import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length));
function fixture() {
  const task = { task_id: "task-a", status: "ready", current_spec_revision: 1 };
  const state = { task, selectedTaskId: task.task_id, selectionToken: 1, refreshSeq: 0, noticeDismissTimer: null, conversationReconcileSeq: 0, runtimeReady: true };
  const ui = { composerNotice: { dataset: {}, hidden: true, textContent: "" } };
  const f = { state, ui, window: { clearTimeout() {} }, Date, isConversationDraft: () => false, modelSourceBlocker: () => null,
    nextRead: async () => ({ task }), request: path => path === `/tasks/${state.selectedTaskId}` ? f.nextRead() : Promise.resolve({}),
    renderTask() {}, resetRunEvidence() {}, loadRunEvidence: async () => {}, loadMaterialInspections: async () => {}, reconcileComposerDatasetUpload: async () => {}, renderConversation() {}, loadTasks: async () => {},
    isWorkspaceConnectionError: error => error?.status === 0 || [502, 503, 504].includes(error?.status),
    reconcileConversation: async () => true,
  };
  vm.runInNewContext(section("function clearNoticeDismissTimer", "function prepareHomeAvailabilityProbe") + section("async function refreshSelected", "function conversationStreamEntryKey") + "\nglobalThis.api={refreshSelected,showNotice,showRuntimeSetupNotice,showConnectionNotice,clearConnectionNotice,showSelectedWorkspaceReadError};", f);
  return { f, state, ui, task };
}
const disconnected = () => Object.assign(new Error("暂时无法连接训练工作台服务。请检查网络后刷新重试。"), { status: 0 });

test("the current owner's successful automatic refresh retires only its typed connection banner and retains the original error", async () => {
  const t = fixture(), error = disconnected(); t.f.nextRead = async () => { throw error; };
  await t.f.api.refreshSelected({ includeConversation: false });
  assert.equal(t.ui.composerNotice.hidden, false); assert.equal(t.ui.composerNotice.dataset.noticeScope, "connection"); assert.equal(t.ui.composerNotice.dataset.noticeOwnerId, "task-a");
  assert.equal(t.state.lastWorkspaceConnectionFailure.error, error);
  t.f.nextRead = async () => ({ task: t.task }); await t.f.api.refreshSelected({ includeConversation: false });
  assert.equal(t.ui.composerNotice.hidden, true); assert.equal(t.ui.composerNotice.textContent, ""); assert.equal(t.state.lastWorkspaceConnectionFailure.error, error); assert.ok(Number.isFinite(t.state.lastWorkspaceConnectionFailure.recovered_at));
});

test("validation, upload failures and provider setup notices are not erased by workspace recovery", async () => {
  const t = fixture();
  for (const message of ["请先选择预测字段", "上传失败：服务返回 503，请核对回执", "暂时无法连接训练工作台服务。请检查网络后刷新重试。文件仍待核对"]) {
    t.f.api.showNotice(message); await t.f.api.refreshSelected({ includeConversation: false });
    assert.equal(t.ui.composerNotice.hidden, false); assert.equal(t.ui.composerNotice.textContent, message);
  }
  t.f.api.showRuntimeSetupNotice("模型服务尚未配置"); await t.f.api.refreshSelected({ includeConversation: false }); assert.equal(t.ui.composerNotice.textContent, "模型服务尚未配置"); assert.equal(t.ui.composerNotice.hidden, false);
  t.f.nextRead = async () => { throw Object.assign(new Error("任务字段无效"), { status: 422 }); }; await t.f.api.refreshSelected({ includeConversation: false });
  assert.equal(t.ui.composerNotice.dataset.noticeScope, undefined); assert.equal(t.ui.composerNotice.textContent, "任务字段无效");
});

test("home health checks, another owner and an older selection token cannot dismiss a task-specific error", async () => {
  const t = fixture(); t.f.api.showSelectedWorkspaceReadError(disconnected(), "task-a", 1);
  t.f.api.clearConnectionNotice(); assert.equal(t.ui.composerNotice.hidden, false, "global service reachability is not the selected owner snapshot");
  t.state.selectedTaskId = "task-b"; t.state.selectionToken = 2; t.f.nextRead = async () => ({ task: { task_id: "task-b" } }); await t.f.api.refreshSelected({ includeConversation: false });
  assert.equal(t.ui.composerNotice.hidden, false); assert.equal(t.state.lastWorkspaceConnectionFailure.recovered_at, null);
  t.state.selectedTaskId = "task-a"; t.f.api.clearConnectionNotice("task-a", 2); assert.equal(t.ui.composerNotice.hidden, false);
});

test("an older successful request cannot erase a newer connection failure on the same owner", async () => {
  const t = fixture(); let resolveRead;
  t.f.api.showSelectedWorkspaceReadError(disconnected(), "task-a", 1);
  t.f.nextRead = () => new Promise(resolve => { resolveRead = resolve; }); const pending = t.f.api.refreshSelected({ includeConversation: false });
  const newest = Object.assign(new Error("新的连接失败"), { status: 503 }); t.f.api.showSelectedWorkspaceReadError(newest, "task-a", 1);
  resolveRead({ task: t.task }); await pending;
  assert.equal(t.ui.composerNotice.hidden, false); assert.equal(t.ui.composerNotice.textContent, "新的连接失败"); assert.equal(t.state.lastWorkspaceConnectionFailure.recovered_at, null);
  t.f.nextRead = async () => ({ task: t.task }); await t.f.api.refreshSelected({ includeConversation: false }); assert.equal(t.ui.composerNotice.hidden, true);
});

test("late failed reads cannot replace the notice belonging to a newly selected owner", async () => {
  const t = fixture(); let rejectRead;
  t.f.nextRead = () => new Promise((_resolve, reject) => { rejectRead = reject; }); const pending = t.f.api.refreshSelected({ includeConversation: false });
  t.state.selectedTaskId = "task-b"; t.state.selectionToken = 2; t.f.api.showNotice("B 的字段需要确认"); rejectRead(disconnected()); await pending;
  assert.equal(t.ui.composerNotice.textContent, "B 的字段需要确认"); assert.equal(t.state.lastWorkspaceConnectionFailure, undefined);
});

test("a healthy canonical conversation reconciliation also retires the matching connection banner", async () => {
  const t = fixture(); t.f.api.showSelectedWorkspaceReadError(disconnected(), "task-a", 1);
  Object.assign(t.f, { conversationTransportPath: () => "/tasks/task-a/conversation", request: async () => ({ conversation: { task_id: "task-a", projection_health: "healthy" } }),
    acceptConversationSnapshot: (id, token, value) => { if (id !== t.state.selectedTaskId || token !== t.state.selectionToken || id !== value.task_id) return false; t.state.conversation = value; return true; }, markConversationStreamDegraded() {} });
  vm.runInNewContext(section("async function reconcileConversation", "function closeConversationEventSource") + "\nglobalThis.reconcile=reconcileConversation;", t.f);
  assert.equal(await t.f.reconcile("task-a", 1), true); assert.equal(t.ui.composerNotice.hidden, true);
  t.f.api.showSelectedWorkspaceReadError(disconnected(), "task-a", 1); t.f.request = async () => ({ conversation: { task_id: "task-a", projection_health: "observation_degraded" } });
  await t.f.reconcile("task-a", 1); assert.equal(t.ui.composerNotice.hidden, false, "an offline/degraded snapshot is not a confirmed conversation recovery");
});
