import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
function section(from, to) {
  const start = source.indexOf(from), end = source.indexOf(to, start + from.length);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}
const code = [
  section("const COMPOSER_ATTACHMENT_STATUS", "function datasetUploadReceiptMatches"),
  section("function clearComposerAttachment", "function formatBytes"),
  section("function isPendingHumanCheckpoint", "function inferenceInputQuestionCheckpoint"),
  section("function renderDataset", "function gateEntries"),
  section("async function uploadDataset", "function activateContext"),
].join("\n");

function fixture() {
  const element = () => ({ dataset: {}, hidden: false, disabled: false, textContent: "", title: "", setAttribute(name, value) { this[name] = value; } });
  const ui = new Proxy({}, { get: (target, key) => target[key] ||= element() });
  const state = { selectedTaskId: null, task: null, conversation: { pending: [] }, composerAttachment: null };
  const notices = [], requests = [];
  const context = {
    state, ui, formatBytes: () => "20 KB", createConversationRequestId: () => "upload-a",
    showNotice: (...args) => notices.push(args), hideNotice() {},
    datasetDetail: () => ["未导入", "尚未执行体检"],
    request: async (...args) => { requests.push(args); throw new Error("Unexpected upload"); },
    setButtonBusy() {}, refreshSelected: async () => {},
  };
  vm.runInNewContext(code + "\nglobalThis.api={stageComposerAttachment,syncComposerAttachmentOwner,renderComposerAttachment,renderDataset,datasetUploadAvailability,retryComposerAttachment,clearComposerAttachment};", context);
  return { state, ui, notices, requests, context, api: context.api };
}
function stageHomeFile(f) {
  f.api.stageComposerAttachment({ name: "paired-data.zip", type: "application/zip", size: 20000 });
}
function bindTask(f, task) {
  f.state.selectedTaskId = "task-a";
  f.state.task = { task_id: "task-a", ...task };
  f.api.syncComposerAttachmentOwner("task-a", { adoptAttachment: f.state.composerAttachment });
  f.api.renderDataset(f.state.task);
}

test("a file selected before a goal stays local without an inoperative continue button", () => {
  const f = fixture(); stageHomeFile(f);
  assert.equal(f.ui.attachmentStatus.textContent, "尚未上传");
  assert.equal(f.ui.retryAttachmentButton.hidden, true);
  assert.equal(f.ui.removeAttachmentButton.disabled, false);
  assert.equal(f.state.composerAttachment.request_id, "upload-a");
  assert.equal(f.requests.length, 0);
});

for (const family of ["ocr", "speech_synthesis", "text_classification", "time_series_forecasting"]) {
  test(`home attachment offers read-only inspection for the ${family} integration gap`, async () => {
    const f = fixture(); stageHomeFile(f); const noticeCount = f.notices.length;
    bindTask(f, { status: "needs_recipe", task_spec: { selected_family: family }, capability_decision: { status: "needs_recipe" } });
    assert.equal(f.ui.attachmentStatus.textContent, "尚未上传");
    assert.match(f.ui.attachmentMeta.textContent, /可先上传并检查材料/);
    assert.doesNotMatch(f.ui.attachmentMeta.textContent, /发送任务目标后再导入|先发送任务目标/);
    assert.equal(f.ui.retryAttachmentButton.hidden, false);
    assert.equal(f.ui.retryAttachmentButton.textContent, "检查材料");
    assert.equal(f.ui.removeAttachmentButton.disabled, false);
    assert.equal(f.ui.datasetButton.disabled, false);
    assert.match(f.ui.datasetButton.title, /只读材料检查/);
    assert.equal(f.notices.length, noticeCount, "task polling must not create a persistent warning banner");
    assert.equal(f.requests.length, 0, "polling does not create uploads; creation explicitly resumes its own attachment");
    assert.equal(f.state.composerAttachment.request_id, "upload-a");
  });
}

test("an unbound conversation and a task awaiting output confirmation replace the stale home reason", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { record_type: "conversation_draft", status: "draft" });
  assert.match(f.ui.attachmentMeta.textContent, /可先上传并检查材料/);
  assert.doesNotMatch(f.ui.attachmentMeta.textContent, /先发送/);
  delete f.state.task.record_type;
  f.state.task.status = "needs_confirmation";
  f.state.task.capability_decision = { status: "needs_confirmation" };
  f.api.renderDataset(f.state.task);
  assert.match(f.ui.attachmentMeta.textContent, /可先上传并检查材料/);
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.ui.datasetButton.disabled, false);
});

test("a home attachment retains its inspection intent when a training adapter becomes supported", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_confirmation", capability_decision: { status: "needs_confirmation" } });
  Object.assign(f.state.task, { status: "needs_dataset", recipe_id: "image-folder-classification", data_adapter_id: "image-folder-zip", capability_decision: { status: "resolved" } });
  f.api.renderDataset(f.state.task);
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.ui.retryAttachmentButton.textContent, "检查材料");
  assert.equal(f.ui.datasetButton.disabled, false);
  assert.equal(f.state.composerAttachment.error, null);
  assert.equal(f.state.composerAttachment.waiting_on, undefined);
  assert.equal(f.state.composerAttachment.request_id, "upload-a");
  assert.equal(f.requests.length, 0, "becoming supported does not silently upload or authorize anything");
});

test("pending task understanding still permits read-only material inspection without deciding the task specification", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_confirmation", task_spec: { revision: 1, business_goal: "预测未来七天销量" }, capability_decision: { status: "needs_confirmation", selected_family: "time_series_forecasting" } });
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.ui.retryAttachmentButton.textContent, "检查材料");
  assert.equal(f.ui.attachmentStatus.textContent, "尚未上传");
  assert.equal(f.requests.length, 0);
  assert.equal(f.state.task.capability_decision.selected_family, "time_series_forecasting");
  assert.equal(f.state.composerAttachment.dataset_id, null);
  f.state.conversation.pending = [{ kind: "question", status: "pending", rpc_id: "native-spec-question", questions: [{ id: "model_output" }] }];
  f.api.renderComposerAttachment();
  assert.equal(f.ui.retryAttachmentButton.hidden, false, "material inspection does not answer the existing question");
});

test("lost-response reconciliation remains uncertain and retryable instead of claiming not uploaded", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_recipe", capability_decision: { status: "needs_recipe" } });
  Object.assign(f.state.composerAttachment, { status: "pending", retry_stage: "reconcile", can_retry: true, error: "响应中断，等待服务端回执" });
  f.api.renderComposerAttachment();
  assert.equal(f.ui.attachmentStatus.textContent, "待核对");
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.ui.retryAttachmentButton.textContent, "核对导入");
  assert.match(f.ui.attachmentMeta.textContent, /响应中断/);
  assert.equal(f.ui.composerAttachment.dataset.waiting, "false");
});

test("imported files and continuation retries keep the actual successful upload state", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_recipe", capability_decision: { status: "needs_recipe" } });
  Object.assign(f.state.composerAttachment, { status: "ready", dataset_id: "dataset-a", retry_stage: "continuation", can_retry: true, error: "已导入，续接请求失败" });
  f.api.renderComposerAttachment();
  assert.equal(f.ui.attachmentStatus.textContent, "已导入");
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.ui.retryAttachmentButton.textContent, "重试续接");
  assert.match(f.ui.removeAttachmentButton.title, /已导入的数据不会被删除/);
});

test("native data questions still allow their upload while other approvals do not activate stale attachments", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_confirmation", recipe_id: "image-folder-classification", capability_decision: { status: "needs_confirmation" } });
  f.state.conversation.pending = [{ kind: "question", status: "pending", rpc_id: "upload-question", questions: [{ id: "data_upload" }] }];
  f.api.renderDataset(f.state.task);
  assert.equal(f.ui.retryAttachmentButton.hidden, false);
  assert.equal(f.api.datasetUploadAvailability().blocked, false);
  f.state.task.capability_decision.status = "resolved";
  f.state.conversation.pending = [{ kind: "approval", status: "pending", rpc_id: "approval-a" }];
  f.api.renderDataset(f.state.task);
  assert.equal(f.ui.retryAttachmentButton.hidden, true);
  assert.match(f.ui.attachmentMeta.textContent, /当前对话中的确认/);
});

test("trusted recipe sample preparation keeps its dedicated button without pretending to import data", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_recipe", control: { next_action: { id: "stage_recipe_samples" } }, capability_decision: { status: "needs_recipe" } });
  assert.equal(f.ui.datasetButton.disabled, false);
  assert.equal(f.ui.datasetButtonLabel.textContent, "上传构建样例");
  assert.match(f.ui.attachmentMeta.textContent, /上传构建样例/);
  assert.equal(f.ui.retryAttachmentButton.hidden, true);
  assert.equal(f.ui.attachmentStatus.textContent, "尚未上传");
});

test("removing a staged unavailable file leaves ordinary interaction and task ownership intact", () => {
  const f = fixture(); stageHomeFile(f);
  bindTask(f, { status: "needs_recipe", capability_decision: { status: "needs_recipe" } });
  f.api.clearComposerAttachment();
  assert.equal(f.state.composerAttachment, null);
  assert.equal(f.ui.composerAttachment.hidden, true);
  assert.equal(f.state.selectedTaskId, "task-a");
  assert.equal(f.requests.length, 0);
});

test("task and conversation refreshes update attachment availability before an unchanged-view early return", () => {
  const render = section("function renderConversation(", "function actionsForTurn");
  assert.ok(render.indexOf("renderComposerAttachment();") < render.indexOf("renderKey === state.lastRenderKey"));
  assert.match(section("function renderDataset", "function gateEntries"), /renderComposerAttachment\(\)/);
});
