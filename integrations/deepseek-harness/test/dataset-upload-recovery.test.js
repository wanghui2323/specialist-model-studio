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
const executable = [
  section("function isPendingHumanCheckpoint", "function inferenceInputQuestionCheckpoint"),
  section("function datasetUploadReceiptMatches", "function clearComposerAttachment"),
  section("async function retryComposerAttachment", "function formatBytes"),
  section("async function retryAttachmentContinuation", "function activateContext"),
].join("\n");

function fixture({ recipe = "tabular-regression", adapter, filename = "table.csv", checkpoint = true } = {}) {
  const attachment = { request_id: "upload-a", task_id: "task-a", file: { name: filename }, status: "pending" };
  const question = { kind: "question", rpc_id: "rpc-a", status: "pending", questions: [{ id: "data_upload" }] };
  const state = {
    selectedTaskId: "task-a", runtimeReady: true,
    task: { task_id: "task-a", recipe_id: recipe, data_adapter_id: adapter, capability_decision: { status: "resolved" }, status: "needs_dataset" },
    conversation: { pending: checkpoint ? [question] : [] }, composerAttachment: attachment,
  };
  const notices = [], requests = [], answers = [], messages = [];
  const context = {
    state, ui: { datasetButton: {}, datasetInput: {} },
    hideNotice() {}, setButtonBusy() {}, activateContext() {}, renderComposerAttachment() {}, shortId: value => value,
    updateComposerAttachment(object, patch) { if (state.composerAttachment === object) Object.assign(object, patch); },
    showNotice(message) { notices.push(message); }, refreshSelected: async () => {},
    postQuestionAnswers: async (...args) => answers.push(args),
    postQueuedConversationMessage: async (...args) => messages.push(args),
    request: async (url, options) => { requests.push([url, options]); return receipt(); },
    askCsvOptions() { throw new Error("CSV options must not open for a ZIP"); },
  };
  vm.runInNewContext(`${executable}\nglobalThis.api={uploadDataset,retryComposerAttachment,reconcileComposerDatasetUpload,datasetUploadFormat};`, context);
  return { state, attachment, question, notices, requests, answers, messages, context, api: context.api };
}
function receipt(datasetId = "dataset-a") {
  return {
    task: { task_id: "task-a", dataset_id: datasetId, dataset_history: [datasetId] },
    dataset_upload: { object_type: "DatasetUploadReceipt", task_id: "task-a", request_id: "upload-a", dataset_id: datasetId, status: "completed" },
  };
}
async function upload(f) { await f.api.uploadDataset(f.attachment.file, { attachment: f.attachment, ...(f.attachment.file.name.endsWith(".csv") ? { targetColumn: "target" } : {}) }); }

for (const recipe of ["image-folder-classification", "audio-keyword-classification"]) {
  test(`${recipe} imports ZIP at the generic data checkpoint and resumes it`, async () => {
    const f = fixture({ recipe, filename: "classes.zip" });
    await upload(f);
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0][1].headers["content-type"], "application/zip");
    assert.equal(f.attachment.status, "ready");
    assert.equal(f.answers.length, 1);
    assert.equal(f.answers[0][0].rpc_id, "rpc-a");
    assert.equal(f.answers[0][1][0].custom, "dataset-a");
    assert.equal(f.messages.length, 0);
  });
}

test("adapter identity drives registered recipes; incompatible formats stop before upload", async () => {
  const f = fixture({ recipe: "custom-registered-audio", adapter: "audio-keyword-class-folder-zip", filename: "audio.zip" });
  await upload(f);
  assert.equal(f.attachment.status, "ready");
  for (const recipe of ["tabular-regression", "tabular-classification"]) {
    const wrong = fixture({ recipe, filename: "classes.zip" });
    await upload(wrong);
    assert.equal(wrong.requests.length, 0);
    assert.equal(wrong.attachment.status, "failed");
    assert.match(wrong.attachment.error, /CSV/);
  }
  const wrong = fixture({ recipe: "image-folder-classification", filename: "table.csv" });
  await upload(wrong);
  assert.equal(wrong.requests.length, 0);
  assert.match(wrong.attachment.error, /ZIP/);
});

for (const status of [0, 200, 503]) {
  test(`lost upload response (${status}) reconciles exact receipt and continues once`, async () => {
    const f = fixture();
    f.context.request = async (url, options) => {
      f.requests.push([url, options]);
      if (url.endsWith("/dataset")) throw Object.assign(new Error("lost response"), { status, retryable: true });
      return receipt();
    };
    await upload(f);
    assert.equal(f.requests.length, 2);
    assert.match(f.requests[1][0], /dataset-upload-receipts\/upload-a$/);
    assert.equal(f.attachment.status, "ready");
    assert.equal(f.answers.length, 1);
    await f.api.retryComposerAttachment();
    assert.equal(f.requests.length, 2);
    assert.equal(f.answers.length, 1);
  });
}

for (const checkpoint of [true, false]) {
  test(`delayed receipt resumes ${checkpoint ? "original question" : "coordinator message"} with no re-upload`, async () => {
    const f = fixture({ checkpoint }); let ready = false;
    f.context.request = async (url, options) => {
      f.requests.push([url, options]);
      if (url.endsWith("/dataset")) throw Object.assign(new Error("network interrupted"), { status: 0 });
      if (!ready) throw Object.assign(new Error("not ready"), { status: 404 });
      return receipt();
    };
    await upload(f);
    assert.equal(f.attachment.retry_stage, "reconcile");
    ready = true;
    await f.api.retryComposerAttachment();
    assert.equal(f.attachment.status, "ready");
    assert.equal(f.requests.filter(([url]) => url.endsWith("/dataset")).length, 1);
    assert.equal(f.answers.length, checkpoint ? 1 : 0);
    assert.equal(f.messages.length, checkpoint ? 0 : 1);
    await f.api.retryComposerAttachment();
    assert.equal(f.answers.length + f.messages.length, 1);
  });
}

test("delayed receipt never answers a newer checkpoint or bypasses its approval", async () => {
  const f = fixture(); let ready = false;
  f.context.request = async url => {
    if (!ready) throw Object.assign(new Error("network interrupted"), { status: 0 });
    return receipt();
  };
  await upload(f);
  f.state.conversation.pending = [{ ...f.question, rpc_id: "new-approval", kind: "approval" }];
  ready = true;
  await f.api.retryComposerAttachment();
  assert.equal(f.attachment.dataset_id, "dataset-a");
  assert.equal(f.answers.length + f.messages.length, 0);
});

test("question continuation retry uses original RPC and never uploads again", async () => {
  const f = fixture(); let reject = true;
  f.context.postQuestionAnswers = async (...args) => {
    f.answers.push(args);
    if (reject) throw new Error("connection lost");
  };
  await upload(f);
  assert.equal(f.attachment.retry_stage, "continuation");
  reject = false;
  await f.api.retryComposerAttachment();
  assert.equal(f.requests.length, 1);
  assert.equal(f.answers.length, 2);
  assert.equal(f.answers[0][0].rpc_id, f.answers[1][0].rpc_id);
  assert.deepEqual(f.answers[0][1], f.answers[1][1]);
  assert.equal(f.attachment.retry_stage, null);
});

test("concurrent receipt checks and task changes cannot duplicate or cross-submit continuation", async () => {
  const f = fixture(); let release;
  f.attachment.retry_stage = "reconcile";
  f.attachment.upload_context = { kind: "question", rpc_id: "rpc-a" };
  f.context.request = async () => new Promise(resolve => { release = resolve; });
  const first = f.api.retryComposerAttachment();
  await f.api.retryComposerAttachment();
  f.state.selectedTaskId = "task-b";
  release(receipt());
  await first;
  assert.equal(f.answers.length + f.messages.length, 0);
  assert.equal(f.attachment.dataset_id, undefined);
});

test("mismatched server receipt never becomes a ready dataset or continuation", async () => {
  const f = fixture();
  f.context.request = async () => ({ ...receipt(), dataset_upload: { ...receipt().dataset_upload, request_id: "other-request" } });
  await upload(f);
  assert.equal(f.attachment.status, "failed");
  assert.equal(f.answers.length + f.messages.length, 0);
});
