import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
function section(from, to) {
  const start = source.indexOf(from), end = source.indexOf(to, start + from.length);
  assert.ok(start >= 0 && end > start); return source.slice(start, end);
}
const code = [
  section("const COMPOSER_ATTACHMENT_STATUS", "function datasetUploadReceiptMatches"),
  section("function clearComposerAttachment", "function formatBytes"),
  section("function isPendingHumanCheckpoint", "function inferenceInputQuestionCheckpoint"),
].join("\n");
const ownerId = "task-a", materialId = `material-${"a".repeat(24)}`;
function fixture({ filename = "training.csv", draft = false, pending = [] } = {}) {
  const node = () => ({ dataset: {}, hidden: false, disabled: false, value: "", setAttribute(name, value) { this[name] = value; } });
  const ui = new Proxy({}, { get: (target, key) => target[key] ||= node() });
  const attachment = { task_id: ownerId, request_id: "upload-a", file: { name: filename, size: 2000, type: "application/octet-stream" }, status: "pending" };
  const state = { selectedTaskId: ownerId, runtimeReady: true, task: { task_id: ownerId, status: "needs_recipe", ...(draft ? { record_type: "conversation_draft" } : {}) }, conversation: { task_id: ownerId, agent_response_running: false, pending, actions: [], events: [] }, composerAttachment: attachment };
  const requests = [], notices = [], saved = new Map();
  const context = { state, ui, Map, Date, console,
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    formatBytes: value => `${value} B`, createConversationRequestId: () => "upload-a", showNotice: (...args) => notices.push(args),
    runtimeStatusToken: value => String(value || "").toLowerCase(), DEFAULT_CONVERSATION_MESSAGE_MODE: "queue_after_turn",
    conversationTransportPath: (id, action) => state.task?.record_type === "conversation_draft" ? `/conversations/${id}/${action}` : `/tasks/${id}/conversation/${action}`,
    refreshSelected: async () => {},
    request: async (path, options) => { requests.push([path, options]); return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(state.composerAttachment) }; },
  };
  vm.runInNewContext(code + "\nglobalThis.api={uploadMaterial,continueMaterialInspection,materialContinuation,materialInspectionMode,renderComposerAttachment,stageComposerAttachment,syncComposerAttachmentOwner,resumeNewConversationAttachment,retryComposerAttachment,loadMaterialInspections,flushDeferredMaterialContinuations,materialReadEvidence};", context);
  return { state, ui, attachment, requests, notices, saved, context, api: context.api };
}
function record(attachment, { owner = ownerId, status = "inspected", facts = {} } = {}) {
  return { object_type: "MaterialInspection", owner_id: owner, material_id: materialId, request_id: attachment.request_id, status, dataset_imported: false, execution_authorized: false, file: { name: attachment.file.name, bytes: attachment.file.size, sha256: "a".repeat(64) }, report: { facts: { file_count: 1, row_count: 12, ...facts }, tables: [], errors: [], warnings: [] } };
}
const question = { kind: "question", rpc_id: "upload-rpc", status: "pending", questions: [{ id: "data_upload" }] };
const approval = { kind: "approval", rpc_id: "approval-rpc", status: "pending" };

test("upload while composing preserves the draft and waits for the intended message", async () => {
  const f = fixture(); f.ui.messageInput.value = "保留目标，改用新的资源预算";
  await f.api.uploadMaterial(f.attachment.file);
  assert.equal(f.requests.length, 1, "inspection must not submit a synthetic turn ahead of the draft");
  assert.equal(f.attachment.status, "inspected");
  assert.equal(f.api.materialContinuation(f.attachment.material).status, "awaiting_message");
  assert.equal(f.api.materialContinuation(f.attachment.material).auto_requested, false);
  await f.api.flushDeferredMaterialContinuations();
  assert.equal(f.requests.length, 1);
  assert.equal(f.ui.messageInput.value, "保留目标，改用新的资源预算");
  await f.api.continueMaterialInspection(f.attachment.material, null, { discussCheckpoint: true });
  assert.equal(f.requests.length, 2, "the explicit report action remains available");
});

for (const [scene, filename, facts] of [["语音", "voice-paired.zip", { wav_count: 48 }], ["OCR", "ocr-paired.zip", { image_count: 320 }], ["NLP", "intent.jsonl", { row_count: 156 }], ["时序", "history.csv", { row_count: 1431 }]]) {
  test(`${scene} material upload preserves inspection identity without a Dataset or execution write`, async () => {
    const f = fixture({ filename }); f.context.request = async (path, options) => { f.requests.push([path, options]); return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(f.attachment, { facts }) }; };
    await f.api.uploadMaterial(f.attachment.file);
    assert.equal(f.requests.length, 2); assert.equal(f.requests[0][0], "/tasks/task-a/materials");
    assert.equal(f.requests[0][1].body, f.attachment.file); assert.equal(f.requests[0][1].headers["x-request-id"], "upload-a");
    assert.equal(f.attachment.status, "inspected"); assert.equal(f.attachment.material_id, materialId); assert.equal(f.attachment.dataset_id, undefined);
    assert.equal(f.ui.attachmentStatus.textContent, "已检查材料"); assert.match(f.ui.attachmentMeta.textContent, /未导入训练数据/);
    const message = f.requests[1][1].json;
    assert.match(message.message, new RegExp(materialId)); assert.match(message.message, /解读报告/); assert.doesNotMatch(message.message, /已上传.*回复|\/Users\/|dataset_id=/);
    assert.equal(message.checkpoint_rpc_id, undefined); assert.equal(message.mode, "queue_after_turn");
    await f.api.retryComposerAttachment(); assert.equal(f.requests.length, 2, "one upload and one report across retry clicks");
  });
}

test("draft and unsupported tasks offer inspection while verified import and recipe samples retain their routes", () => {
  const f = fixture({ draft: true }); assert.equal(f.api.materialInspectionMode(), true);
  for (const task of [{ recipe_id: "tabular-classification", status: "needs_dataset", capability_decision: { status: "resolved" } }, { recipe_id: "audio-keyword-classification", status: "needs_recipe", control: { next_action: { id: "stage_recipe_samples" } } }]) {
    f.state.task = { task_id: ownerId, ...task }; assert.equal(f.api.materialInspectionMode(), false);
  }
});

for (const pending of [question, approval]) {
  test(`automatic material inspection does not answer or suspend ${pending.kind}`, async () => {
    const f = fixture({ pending: [pending] }); await f.api.uploadMaterial(f.attachment.file);
    assert.equal(f.requests.length, 1); assert.equal(f.attachment.status, "inspected");
    assert.equal(f.api.materialContinuation(f.attachment.material).status, "deferred"); assert.match(f.attachment.note, /当前确认仍待处理/);
    assert.equal(f.attachment.retry_stage, null); assert.equal(f.attachment.can_retry, false);
    await f.api.continueMaterialInspection(f.attachment.material, null, { discussCheckpoint: true });
    assert.equal(f.requests.length, 2); assert.equal(f.requests[1][1].json.checkpoint_rpc_id, pending.rpc_id);
    assert.match(f.requests[1][0], /messages$/); assert.ok(f.requests.every(([path]) => !/\/questions\/|\/approvals\//.test(path)));
  });
}

test("concurrent upload gestures are one physical request and one continuation", async () => {
  const f = fixture(); let release;
  f.context.request = async (path, options) => { f.requests.push([path, options]); if (path.endsWith("/materials")) return new Promise(resolve => { release = resolve; }); return { accepted: true, status: "queued" }; };
  const first = f.api.uploadMaterial(f.attachment.file); await f.api.uploadMaterial(f.attachment.file);
  assert.equal(f.requests.length, 1); release({ material: record(f.attachment) }); await first;
  assert.equal(f.requests.length, 2);
});

for (const invalid of ["lost", "malformed"]) {
  test(`${invalid} upload acknowledgement reads the exact receipt before sending the report`, async () => {
    const f = fixture(); f.context.request = async (path, options) => {
      f.requests.push([path, options]);
      if (path.endsWith("/materials")) { if (invalid === "lost") throw Object.assign(new Error("lost"), { status: 0 }); return { material: { wrong: true } }; }
      return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(f.attachment) };
    };
    await f.api.uploadMaterial(f.attachment.file); assert.equal(f.attachment.status, "inspected");
    assert.equal(f.requests.length, 3); assert.equal(f.requests[1][0], "/tasks/task-a/material-requests/upload-a");
    assert.equal(f.requests.filter(([path]) => path.endsWith("/materials")).length, 1);
  });
}

test("delayed receipt remains uncertain, then recovers without re-upload or cross-owner continuation", async () => {
  const f = fixture(); let ready = false;
  f.context.request = async (path, options) => { f.requests.push([path, options]); if (path.endsWith("/materials")) throw Object.assign(new Error("lost"), { status: 0 }); if (!ready) throw Object.assign(new Error("not ready"), { status: 404 }); return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(f.attachment) }; };
  await f.api.uploadMaterial(f.attachment.file); assert.equal(f.attachment.retry_stage, "material_reconcile");
  f.attachment.waiting_on = "material_inspection"; f.api.renderComposerAttachment(); assert.equal(f.ui.attachmentStatus.textContent, "待核对");
  ready = true; await f.api.retryComposerAttachment(); assert.equal(f.attachment.status, "inspected"); assert.equal(f.requests.filter(([path]) => path.endsWith("/materials")).length, 1);
});

test("switching tasks while inspection is in flight never attaches or announces material in the new task", async () => {
  const f = fixture(); let release; f.context.request = async (path, options) => { f.requests.push([path, options]); return new Promise(resolve => { release = resolve; }); };
  const first = f.api.uploadMaterial(f.attachment.file); f.api.syncComposerAttachmentOwner("task-b"); f.state.selectedTaskId = "task-b";
  release({ material: record(f.attachment) }); await first;
  assert.equal(f.state.composerAttachment, null); assert.equal(f.requests.length, 1); assert.equal(f.state.materialInspections.length, 0);
});

test("a receipt with wrong ownership or authorization is never accepted as checked material", async () => {
  for (const mutation of [item => { item.owner_id = "task-b"; }, item => { item.dataset_imported = true; }, item => { item.request_id = "another"; }]) {
    const f = fixture(); const bad = record(f.attachment); mutation(bad); f.context.request = async (path, options) => { f.requests.push([path, options]); return { material: bad }; };
    await f.api.uploadMaterial(f.attachment.file); assert.equal(f.attachment.material_id, undefined); assert.equal(f.requests.filter(([path]) => path.endsWith("/messages")).length, 0); assert.equal(f.attachment.retry_stage, "material_reconcile");
  }
});

test("report retries preserve exact request and recover a terminal completed acknowledgement", async () => {
  const f = fixture(); let messages = 0;
  f.context.request = async (path, options) => { f.requests.push([path, options]); if (!path.endsWith("/messages")) return { material: record(f.attachment) }; messages += 1; if (messages === 1) throw Object.assign(new Error("lost"), { status: 0 }); throw Object.assign(new Error("already completed"), { status: 409, payload: { detail: { code: "composer_request_terminal", request_id: options.json.request_id, status: "completed" } } }); };
  await f.api.uploadMaterial(f.attachment.file); assert.equal(f.attachment.retry_stage, "material_continuation");
  await f.api.retryComposerAttachment(); assert.equal(f.api.materialContinuation(f.attachment.material).status, "accepted");
  assert.deepEqual(f.requests[1][1].json, f.requests[2][1].json); assert.equal(f.requests.filter(([path]) => path.endsWith("/materials")).length, 1);
  await f.api.retryComposerAttachment(); assert.equal(f.requests.length, 3);
});

test("home file is adopted only by explicit creation, uploads automatically once, and survives promotion scope", async () => {
  const f = fixture(); f.state.selectedTaskId = null; f.state.task = null; f.api.stageComposerAttachment({ name: "intent.jsonl", size: 1000 });
  const staged = f.state.composerAttachment; assert.equal(f.requests.length, 0); assert.equal(f.ui.retryAttachmentButton.hidden, true);
  f.api.syncComposerAttachmentOwner(ownerId, { adoptAttachment: staged }); f.state.selectedTaskId = ownerId; f.state.task = { task_id: ownerId, record_type: "conversation_draft", status: "draft" };
  await f.api.resumeNewConversationAttachment(staged, ownerId); assert.equal(f.requests.length, 2); assert.equal(f.requests[0][0], "/conversations/task-a/materials");
  delete f.state.task.record_type; await f.api.resumeNewConversationAttachment(staged, ownerId); assert.equal(f.requests.length, 2);
  assert.equal(staged.material_scope, "conversations");
  const other = fixture(); other.state.selectedTaskId = null; other.state.task = null; other.api.stageComposerAttachment({ name: "data.csv", size: 100 });
  other.api.syncComposerAttachmentOwner("task-other"); assert.equal(other.state.composerAttachment, null); assert.equal(other.requests.length, 0);
  const submit = section("async function submitMessage(", "function deriveTaskName");
  assert.match(submit, /selectConversation\(conversationId, \{ saveCurrentDraft: false, record: created.conversation, pendingAttachment \}\)/);
  assert.match(submit, /await resumeNewConversationAttachment\(pendingAttachment, conversationId\)/);
});

test("material list reload keeps a previously read full report and discards late responses after task switch", async () => {
  const f = fixture(); const full = record(f.attachment); f.state.materialsOwnerId = ownerId; f.state.materialsLoadSeq = 0; f.state.materialInspections = [full];
  f.context.request = async () => ({ owner_id: ownerId, materials: [{ ...full, detail_available: true, report: { facts: {} } }] });
  await f.api.loadMaterialInspections(ownerId, { force: true }); assert.equal(f.state.materialInspections[0], full);
  let release; f.context.request = async () => new Promise(resolve => { release = resolve; });
  const load = f.api.loadMaterialInspections(ownerId, { force: true }); f.state.selectedTaskId = "task-b"; f.api.syncComposerAttachmentOwner("task-b");
  release({ owner_id: ownerId, materials: [full] }); await load; assert.equal(f.state.materialInspections.length, 0);
});

test("real submitMessage creation resumes its selected home file through the upload and report helpers", async () => {
  const f = fixture(); f.state.selectedTaskId = null; f.state.task = null;
  f.api.stageComposerAttachment({ name: "series.csv", size: 800 }); const staged = f.state.composerAttachment;
  Object.assign(f.context, {
    clearComposerRetry() {}, hideNotice() {}, clearDraft() {}, saveDraft() {}, resizeComposer() {}, renderConversation() {}, syncComposerDelivery() {},
    backgroundCancellationPending: () => false, beginTaskCreationSubmission: () => ({ create_request_id: "create-a", request_id: "first-message" }),
    window: { setTimeout() {} },
    selectConversation: async (id, options) => { f.api.syncComposerAttachmentOwner(id, { adoptAttachment: options.pendingAttachment }); f.state.selectedTaskId = id; f.state.task = { task_id: id, record_type: "conversation_draft" }; },
    request: async (path, options) => {
      f.requests.push([path, options]);
      if (path === "/conversations") return { submission: { accepted: true, status: "queued" }, conversation: { conversation_id: ownerId } };
      return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(f.state.composerAttachment) };
    },
  });
  vm.runInNewContext(section("async function submitMessage(", "function deriveTaskName") + "\nglobalThis.submit=submitMessage;", f.context);
  f.ui.messageInput.value = "按这份历史数据预测未来七天";
  await f.context.submit(f.ui.messageInput.value);
  assert.equal(f.requests.length, 2, "initial reply gets the opportunity to read the uploaded material itself");
  f.state.pendingMessage = null; await f.api.flushDeferredMaterialContinuations();
  assert.equal(f.requests.length, 3); assert.equal(f.requests[0][0], "/conversations"); assert.equal(f.requests[1][0], "/conversations/task-a/materials"); assert.equal(f.requests[2][0], "/conversations/task-a/messages");
  assert.equal(f.requests[0][1].json.initial_message, "按这份历史数据预测未来七天");
  assert.equal(staged.status, "inspected"); assert.equal(f.state.composerAttachment, staged); assert.equal(f.ui.messageInput.value, "");
});

for (const [filename, size] of [["audio.exe", 100], ["large.zip", 25 * 1024 * 1024 + 1]]) {
  test(`invalid local selection ${filename} exposes replacement guidance without a network write`, async () => {
    const f = fixture({ filename }); f.attachment.file.size = size;
    await f.api.uploadMaterial(f.attachment.file); assert.equal(f.requests.length, 0); assert.equal(f.attachment.status, "failed"); assert.equal(f.attachment.can_retry, false);
    assert.match(f.attachment.error, /选择/); assert.equal(f.ui.removeAttachmentButton.disabled, false);
  });
}

function readEvidence(f, { owner = ownerId, id = materialId, status = "completed", compact = false } = {}) {
  const identity = { task_id: owner, agent_run_id: "agent-run-a", session_id: "session-a", turn_id: "turn-a", call_id: "call-a" };
  const action = { ...identity, action_id: "action-a", tool_name: "model_harness_get_material", tool_class: "domain", status, truth_type: "observed_result", call_event_id: "call-event", result_event_id: "result-event", event_result_ref: { id: "result-event", task_id: owner, projector_revision: "3.3" } };
  const call = { ...identity, event_id: "call-event", source: "dsh", event_type: "tool_call", seq: 10, payload: { tool_name: action.tool_name, call_id: identity.call_id, arguments: JSON.stringify({ owner_id: owner, material_id: id }) } };
  const result = { ...identity, event_id: "result-event", source: "dsh", event_type: "tool_result", seq: 11, payload: { tool_name: action.tool_name, call_id: identity.call_id, is_error: status !== "completed", ...(compact ? { result_truncated: true, event_result_ref: action.event_result_ref } : { result: [{ type: "text", text: JSON.stringify({ material: { owner_id: owner, material_id: id, status: "inspected" } }) }] }) } };
  f.state.conversation.actions = [action]; f.state.conversation.events = [call, result]; return { action, call, result };
}

for (const compact of [true, false]) {
  test(`a successful exact material read during the initial reply prevents a second report turn (${compact ? "compact" : "full"} canonical result)`, async () => {
    const f = fixture(); f.state.conversation.agent_response_running = true;
    await f.api.uploadMaterial(f.attachment.file); assert.equal(f.requests.length, 1); assert.equal(f.api.materialContinuation(f.attachment.material).status, "waiting_turn");
    readEvidence(f, { compact }); await f.api.flushDeferredMaterialContinuations();
    assert.equal(f.api.materialContinuation(f.attachment.material).status, "accepted"); assert.equal(f.requests.length, 1);
    f.state.conversation.agent_response_running = false; await f.api.flushDeferredMaterialContinuations(); await f.api.flushDeferredMaterialContinuations();
    assert.equal(f.requests.length, 1);
    // Simulate a reload: persisted exact handled evidence must not resend.
    f.state.materialContinuations = new Map(); await f.api.continueMaterialInspection(f.attachment.material); assert.equal(f.requests.length, 1);
  });
}

for (const condition of ["unread", "failed", "different-owner", "different-material", "prose-only", "get-task-summary", "mismatched-result"]) {
  test(`deferred ${condition} material is announced exactly once after the active reply ends`, async () => {
    const f = fixture(); f.state.conversation.agent_response_running = true; await f.api.uploadMaterial(f.attachment.file);
    if (condition === "failed") readEvidence(f, { status: "failed" });
    if (condition === "different-owner") readEvidence(f, { owner: "task-other" });
    if (condition === "different-material") readEvidence(f, { id: `material-${"b".repeat(24)}` });
    if (condition === "prose-only") f.state.conversation.items = [{ role: "assistant", text: `我已看过 ${materialId} 和 training.csv` }];
    if (condition === "get-task-summary") { const e = readEvidence(f); e.action.tool_name = e.call.payload.tool_name = e.result.payload.tool_name = "model_harness_get_task"; }
    if (condition === "mismatched-result") { const e = readEvidence(f); e.result.payload.result = { material: { material_id: "wrong", owner_id: ownerId, status: "inspected" } }; }
    await f.api.flushDeferredMaterialContinuations(); assert.equal(f.requests.length, 1);
    f.state.conversation.agent_response_running = false;
    await Promise.all([f.api.flushDeferredMaterialContinuations(), f.api.flushDeferredMaterialContinuations()]);
    assert.equal(f.requests.length, 2); assert.match(f.requests[1][0], /messages$/);
    await f.api.flushDeferredMaterialContinuations(); assert.equal(f.requests.length, 2);
  });
}

test("pending automatic material continuation survives reload but never leaks across a task switch", async () => {
  const f = fixture(); f.state.conversation.agent_response_running = true; await f.api.uploadMaterial(f.attachment.file);
  f.state.materialContinuations = new Map(); f.state.conversation.agent_response_running = false;
  f.state.selectedTaskId = "task-other"; await f.api.flushDeferredMaterialContinuations(); assert.equal(f.requests.length, 1);
  f.state.selectedTaskId = ownerId; await f.api.flushDeferredMaterialContinuations(); assert.equal(f.requests.length, 2);
});

test("manual report discussion and newly uploaded material remain independent of another completed material read", async () => {
  const f = fixture({ pending: [approval] }); f.state.conversation.agent_response_running = true; await f.api.uploadMaterial(f.attachment.file);
  await f.api.continueMaterialInspection(f.attachment.material, null, { discussCheckpoint: true });
  assert.equal(f.requests.length, 2); assert.equal(f.requests[1][1].json.checkpoint_rpc_id, approval.rpc_id);
  const other = fixture(); readEvidence(other); const fresh = record(other.attachment); fresh.material_id = `material-${"b".repeat(24)}`;
  await other.api.continueMaterialInspection(fresh); assert.equal(other.requests.length, 1); assert.match(other.requests[0][1].json.message, new RegExp(fresh.material_id));
});

test("aggregate table records are labeled as records rather than unique training samples", async () => {
  const f = fixture(); f.context.request = async (path, options) => {
    f.requests.push([path, options]); return path.endsWith("/messages") ? { accepted: true, status: "queued" } : { material: record(f.attachment, { facts: { row_count: 2904, table_count: 4 } }) };
  };
  await f.api.uploadMaterial(f.attachment.file); assert.match(f.ui.attachmentMeta.textContent, /表格记录合计 2904/); assert.doesNotMatch(f.ui.attachmentMeta.textContent, /训练样本.*2904|2904.*训练样本/);
  assert.match(section("function renderMaterialHistory", "function materialFactSummary"), /不代表去重后的训练样本数/);
});
