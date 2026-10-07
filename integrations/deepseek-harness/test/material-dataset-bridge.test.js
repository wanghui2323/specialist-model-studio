import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
function section(from, to) { const start = source.indexOf(from), end = source.indexOf(to, start + from.length); assert.ok(start >= 0 && end > start); return source.slice(start, end); }
const code = [section("const COMPOSER_ATTACHMENT_STATUS", "function formatBytes"), section("function isPendingHumanCheckpoint", "function inferenceInputQuestionCheckpoint"), section("async function inspectCsvSchema", "function activateContext")].join("\n");
class Element {
  constructor(tag = "div") { this.tag = tag; this.dataset = {}; this.children = []; this.events = {}; this.value = ""; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, fn) { this.events[name] = fn; }
  matches(selector) { return selector === this.tag; }
  querySelector(selector) { return this.children.flatMap(child => [child, ...child.descendants()]).find(child => selector.includes(":checked") ? child.checked : child.tag === selector); }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function fixture({ csv = false, pending = "upload" } = {}) {
  const material = { object_type: "MaterialInspection", owner_id: "task-a", material_id: `material-${"a".repeat(24)}`, request_id: "inspection-a", status: "inspected", inspection_sha256: "b".repeat(64), dataset_imported: false, execution_authorized: false, file: { name: csv ? "table.csv" : "classes.zip", bytes: 1000, sha256: "a".repeat(64) }, report: { facts: {}, errors: [] } };
  const checkpoint = pending === "upload" ? { kind: "question", rpc_id: "upload-rpc", status: "pending", questions: [{ id: "data_upload" }] } : pending === "approval" ? { kind: "approval", rpc_id: "approval-rpc", status: "pending" } : null;
  const state = { selectedTaskId: "task-a", runtimeReady: true, task: { task_id: "task-a", current_spec_revision: 3, recipe_id: csv ? "tabular-regression" : "image-folder-classification", capability_decision: { status: "resolved" }, status: "awaiting_data" }, conversation: { task_id: "task-a", pending: checkpoint ? [checkpoint] : [], agent_response_running: false }, composerAttachment: null, materialInspections: [material], materialsOwnerId: "task-a" };
  const ui = new Proxy({}, { get: (obj, key) => obj[key] ||= new Element() });
  const requests = [], answers = [], notices = [], saved = new Map(); let sequence = 0;
  const context = { state, ui, Map, Date, document: { createElement: tag => new Element(tag) },
    clear: item => item.replaceChildren(), formatBytes: value => `${value} B`, shortId: value => value,
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    createConversationRequestId: () => `request-${++sequence}`, showNotice: (...value) => notices.push(value), hideNotice() {}, setButtonBusy() {}, activateContext() {}, refreshSelected: async () => {},
    postQuestionAnswers: async (...args) => answers.push(args), postQueuedConversationMessage: async (...args) => answers.push(args),
    request: async (path, options) => { requests.push([path, options]);
      if (path.endsWith("/csv-schema")) return { owner_id: "task-a", material_id: material.material_id, inspection_sha256: material.inspection_sha256, columns: ["feature", "price"], delimiter: ",", dataset_imported: false };
      if (path.endsWith("/csv-target-recommendation")) return { recommendation: { status: "recommended", target_column: "price", message: "根据任务目标推荐 price" } };
      return receipt(state.composerAttachment);
    },
  };
  vm.runInNewContext(code + "\nglobalThis.api={useMaterialAsDataset,reusableDatasetMaterial,inspectCsvSchema,askCsvOptions,uploadDataset,retryComposerAttachment,materialContinuation};", context);
  return { material, checkpoint, state, ui, requests, answers, notices, saved, context, api: context.api };
}
function receipt(attachment) { return { task: { task_id: "task-a", dataset_id: "dataset-a", dataset_history: ["dataset-a"] }, dataset_upload: { object_type: "DatasetUploadReceipt", task_id: "task-a", request_id: attachment.request_id, dataset_id: "dataset-a", status: "completed" } }; }

test("retained ZIP imports without browser File bytes and resumes only its original data question", async () => {
  const f = fixture(); await f.api.useMaterialAsDataset(f.material);
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0][0], "/tasks/task-a/dataset-from-material"); assert.equal(f.requests[0][1].body, undefined);
  assert.equal(f.requests[0][1].json.material_id, f.material.material_id); assert.equal(f.requests[0][1].json.inspection_sha256, f.material.inspection_sha256); assert.equal(f.requests[0][1].json.base_spec_revision, 3);
  assert.equal(f.state.composerAttachment.dataset_id, "dataset-a"); assert.equal(f.state.composerAttachment.status, "ready");
  assert.equal(f.answers.length, 1); assert.equal(f.answers[0][0].rpc_id, "upload-rpc"); assert.equal(f.answers[0][1][0].custom, "dataset-a");
  assert.equal(f.api.materialContinuation(f.material).used_as_dataset, "dataset-a");
  await f.api.useMaterialAsDataset(f.material); assert.equal(f.requests.length, 1); assert.equal(f.answers.length, 1);
});

test("retained CSV reads complete saved schema and uses the actual target confirmation dialog before importing", async () => {
  const f = fixture({ csv: true });
  await f.api.useMaterialAsDataset(f.material);
  // uploadDataset deliberately opens the same asynchronous target-field dialog.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.requests.length, 2); assert.match(f.requests[0][0], /materials\/material-[a-f0-9]+\/csv-schema$/); assert.equal(f.requests[1][0], "/tasks/task-a/csv-target-recommendation");
  assert.equal(f.ui.decisionDialog.open, true); assert.equal(f.state.composerAttachment.file.slice, undefined);
  const submit = f.ui.dialogActions.children.find(item => item.textContent === "确认并导入体检"); assert.ok(submit);
  await submit.events.click();
  assert.equal(f.requests.length, 3); const request = f.requests[2]; assert.equal(request[0], "/tasks/task-a/dataset-from-material"); assert.equal(request[1].body, undefined);
  assert.equal(request[1].json.options.target_column, "price"); assert.equal(request[1].json.options.delimiter, ","); assert.equal(f.answers[0][1][0].custom, "dataset-a");
});

test("dataset bridge uses the same receipt when import acknowledgement is lost", async () => {
  const f = fixture(); f.context.request = async (path, options) => { f.requests.push([path, options]); if (path.endsWith("/dataset-from-material")) throw Object.assign(new Error("lost"), { status: 0 }); return receipt(f.state.composerAttachment); };
  await f.api.useMaterialAsDataset(f.material); assert.equal(f.requests.length, 2); assert.match(f.requests[1][0], /dataset-upload-receipts\/request-/);
  assert.equal(f.state.composerAttachment.status, "ready"); assert.equal(f.answers.length, 1);
});

test("refresh reuses the exact saved import request for the same material and field options", async () => {
  const f = fixture(); await f.api.useMaterialAsDataset(f.material); const requestId = f.requests[0][1].json.request_id;
  f.state.composerAttachment = null; f.state.materialDatasetRequests = new Map(); f.state.task.current_spec_revision = 4; await f.api.useMaterialAsDataset(f.material);
  assert.equal(f.requests[1][1].json.request_id, requestId); assert.equal(f.requests[1][1].json.base_spec_revision, 3); assert.equal(f.requests[1][1].body, undefined);
});

for (const condition of ["unsupported-family", "approval", "foreign-owner", "rejected", "wrong-format"]) {
  test(`retained material never bypasses ${condition}`, async () => {
    const f = fixture({ pending: condition === "approval" ? "approval" : "upload" });
    if (condition === "unsupported-family") { f.state.task.status = "needs_recipe"; f.state.task.recipe_id = null; f.state.task.capability_decision.status = "needs_recipe"; }
    if (condition === "foreign-owner") f.material.owner_id = "task-other";
    if (condition === "rejected") f.material.status = "rejected";
    if (condition === "wrong-format") f.material.file.name = "intent.jsonl";
    await f.api.useMaterialAsDataset(f.material); assert.equal(f.requests.length, 0); assert.equal(f.answers.length, 0); assert.equal(f.state.task.recipe_id, condition === "unsupported-family" ? null : "image-folder-classification");
  });
}

test("late CSV schema after a task switch cannot open the old field dialog", async () => {
  const f = fixture({ csv: true }); let release;
  const request = f.context.request; f.context.request = async (path, options) => path.endsWith("/csv-schema") ? new Promise(resolve => { release = resolve; }) : request(path, options);
  await f.api.useMaterialAsDataset(f.material); f.state.selectedTaskId = "task-other"; f.state.composerAttachment = null;
  release({ owner_id: "task-a", material_id: f.material.material_id, inspection_sha256: f.material.inspection_sha256, columns: ["feature", "price"], delimiter: ",", dataset_imported: false });
  await new Promise(resolve => setImmediate(resolve)); assert.notEqual(f.ui.decisionDialog.open, true); assert.equal(f.answers.length, 0);
});

test("CSV import keeps the version observed when its field dialog opened, then requires explicit review after 409", async () => {
  const f = fixture({ csv: true }); const originalRequest = f.context.request;
  f.context.request = async (path, options) => {
    if (path.endsWith("/dataset-from-material") && options.json.base_spec_revision !== f.state.task.current_spec_revision) {
      f.requests.push([path, options]); throw Object.assign(new Error("task spec changed"), { status: 409 });
    }
    return originalRequest(path, options);
  };
  await f.api.useMaterialAsDataset(f.material); await new Promise(resolve => setImmediate(resolve));
  f.state.task.current_spec_revision = 4;
  await f.ui.dialogActions.children.find(item => item.textContent === "确认并导入体检").events.click();
  const failedRequest = f.requests.find(([path]) => path.endsWith("/dataset-from-material"));
  assert.equal(failedRequest[1].json.base_spec_revision, 3); assert.equal(f.state.composerAttachment.retry_stage, "material_dataset_review");
  assert.equal(f.ui.retryAttachmentButton.textContent, "重新确认导入"); assert.equal(f.answers.length, 0);
  assert.equal(f.requests.filter(([path]) => path.endsWith("/dataset-from-material")).length, 1, "409 does not silently replace the revision and resend");
  await f.api.retryComposerAttachment(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.ui.decisionDialog.open, true, "explicit retry reopens field confirmation");
  await f.ui.dialogActions.children.find(item => item.textContent === "确认并导入体检").events.click();
  const imported = f.requests.filter(([path]) => path.endsWith("/dataset-from-material"));
  assert.equal(imported.length, 2); assert.equal(imported[1][1].json.base_spec_revision, 4);
  assert.notEqual(imported[1][1].json.request_id, failedRequest[1].json.request_id); assert.equal(f.answers.length, 1);
});

test("reload after a rejected ZIP import preserves the old request and requires review before another write", async () => {
  const f = fixture(); const originalRequest = f.context.request;
  f.context.request = async (path, options) => { f.requests.push([path, options]); throw Object.assign(new Error("task spec changed"), { status: 409 }); };
  await f.api.useMaterialAsDataset(f.material); const failed = f.requests[0][1].json;
  assert.equal(failed.base_spec_revision, 3); assert.equal(f.answers.length, 0);
  f.state.composerAttachment = null; f.state.materialDatasetRequests = new Map(); f.state.task.current_spec_revision = 4;
  f.context.request = originalRequest;
  await f.api.useMaterialAsDataset(f.material);
  assert.equal(f.requests.length, 1, "opening saved material after reload must not auto-resend a known conflicting request");
  assert.equal(f.state.composerAttachment.base_spec_revision, 3); assert.equal(f.state.composerAttachment.request_id, failed.request_id); assert.equal(f.state.composerAttachment.retry_stage, "material_dataset_review");
  await f.api.retryComposerAttachment(); assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1][1].json.base_spec_revision, 4); assert.notEqual(f.requests[1][1].json.request_id, failed.request_id); assert.equal(f.answers.length, 1);
});

test("reload retry of an uncertain CSV import retains original field choices and revision without silently selecting new defaults", async () => {
  const f = fixture({ csv: true }); const originalRequest = f.context.request;
  f.context.request = async (path, options) => {
    if (path.endsWith("/dataset-from-material")) { f.requests.push([path, options]); throw Object.assign(new Error("lost"), { status: 0 }); }
    if (path.includes("dataset-upload-receipts")) throw Object.assign(new Error("not available"), { status: 404 });
    return originalRequest(path, options);
  };
  await f.api.useMaterialAsDataset(f.material); await new Promise(resolve => setImmediate(resolve));
  await f.ui.dialogActions.children.find(item => item.textContent === "确认并导入体检").events.click();
  const first = f.requests.find(([path]) => path.endsWith("/dataset-from-material"))[1].json;
  assert.equal(f.state.composerAttachment.retry_stage, "reconcile");
  f.state.composerAttachment = null; f.state.materialDatasetRequests = new Map(); f.state.task.current_spec_revision = 8;
  f.context.request = originalRequest; f.requests.length = 0;
  await f.api.useMaterialAsDataset(f.material);
  assert.equal(f.requests.length, 1, "replay bypasses schema/default selection because these fields were already confirmed");
  assert.equal(f.requests[0][0], "/tasks/task-a/dataset-from-material"); assert.deepEqual(f.requests[0][1].json, first);
  assert.equal(f.requests[0][1].json.options.target_column, "price"); assert.equal(f.requests[0][1].json.base_spec_revision, 3);
});
