import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
function section(from, to) { return source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from) + from.length)); }

test("returning home resets the previous task's upload restrictions and recipe label", () => {
  const element = () => ({ dataset: {}, append() {} });
  const ui = new Proxy({}, { get: (target, key) => target[key] ||= element() });
  Object.assign(ui.datasetButton, { disabled: true, title: "上传 WAV 样例 ZIP" });
  ui.datasetButtonLabel.textContent = "上传构建样例"; ui.datasetInput.accept = ".zip";
  const noop = () => {};
  const context = {
    ui, state: { runtimeReady: true }, document: { body: { dataset: {} } },
    history: { replaceState: noop }, location: { pathname: "/" },
    syncComposerAttachmentOwner: noop, clearComposerRetry: noop, renderRuntimeMode: noop,
    runtimeDisplayMode: noop, syncComposerDelivery: noop, restoreDraft: noop,
    renderTaskList: noop, closeSidebar: noop, closeInspector: noop,
  };
  vm.runInNewContext(section("function enterHomeState", "function openNewTask") + "\nenterHomeState({focusComposer:false});", context);
  assert.equal(ui.datasetButton.disabled, false);
  assert.equal(ui.datasetButtonLabel.textContent, "导入数据");
  assert.equal(ui.datasetInput.accept, ".csv,.jsonl,.zip");
  assert.equal(context.document.body.dataset.view, "home");
});

const archiveCode = section("function isPendingHumanCheckpoint", "function currentHumanCheckpoint")
  + section("function taskArchiveActivity", "function enterHomeState");
function fixture(phase = "completed") {
  const task = { task_id: "task-a", name: "模型实验", status: "completed" };
  const conversation = { task_id: "task-a", interaction_projection: { schema_version: "1.0", phase, background: { running: false } }, pending: [] };
  const requests = [], notices = [], dialogs = [];
  const context = {
    state: { selectedTaskId: "task-other", tasks: [] },
    ui: { decisionDialog: { close() {} } },
    request: async (url, options = {}) => { requests.push([url, options]); return { conversation }; },
    openSimpleDialog: value => dialogs.push(value), showNotice: value => notices.push(value),
    loadTasks: async () => {}, refreshSelected: async () => {}, selectTask: async () => {}, openNewTask() {},
  };
  vm.runInNewContext(archiveCode + "\nglobalThis.api={confirmTaskArchive,taskArchiveActivity};", context);
  return { task, conversation, requests, notices, dialogs, context, api: context.api };
}

for (const phase of ["agent_working", "waiting_question", "waiting_approval"]) {
  test(`archive while ${phase} requests stop for the exact task and keeps it visible`, async () => {
    const f = fixture(phase);
    await f.api.confirmTaskArchive(f.task);
    assert.equal(f.dialogs[0].allowLabel, "请求停止当前轮");
    await f.dialogs[0].onAllow();
    assert.equal(f.requests.filter(([url]) => url.endsWith("/archive")).length, 0);
    const stop = f.requests.find(([url]) => url.endsWith("/cancel"));
    assert.equal(stop[0], "/tasks/task-a/conversation/cancel");
    assert.equal(stop[1].method, "POST");
    assert.match(stop[1].json.reason, /归档/);
    assert.match(f.notices.at(-1), /目前仍保留在列表/);
  });
}

test("stopped tasks may archive despite old running AgentRuns and stale pending cards", async () => {
  const f = fixture("stopped");
  f.conversation.runs = [{ status: "running", agent_run_id: "old-run" }];
  f.conversation.pending = [{ kind: "question", rpc_id: "old-question", status: "pending" }];
  await f.api.confirmTaskArchive(f.task);
  assert.equal(f.dialogs[0].allowLabel, "确认归档");
  await f.dialogs[0].onAllow();
  assert.equal(f.requests.filter(([url]) => url.endsWith("/archive")).length, 1);
  assert.equal(f.requests.filter(([url]) => url.endsWith("/cancel")).length, 0);
});

test("a new turn that starts after archive review prevents the browser's archive write", async () => {
  const f = fixture();
  await f.api.confirmTaskArchive(f.task);
  f.conversation.interaction_projection.phase = "agent_working";
  await assert.rejects(f.dialogs[0].onAllow(), /又进入执行/);
  assert.equal(f.requests.filter(([url]) => url.endsWith("/archive")).length, 0);
});

test("archive waits for stopping and refuses unverified conversation ownership", async () => {
  const f = fixture("stopping");
  await f.api.confirmTaskArchive(f.task);
  assert.equal(f.dialogs.length, 0);
  assert.match(f.notices.at(-1), /正在停止/);
  f.conversation.task_id = "another-task";
  await f.api.confirmTaskArchive(f.task);
  assert.equal(f.dialogs.length, 0);
  assert.match(f.notices.at(-1), /还不能核对/);
});

test("legacy snapshots use current execution flags and ignore idle historical pending items", () => {
  const f = fixture(); delete f.conversation.interaction_projection;
  f.conversation.interaction_state = "idle";
  f.conversation.runs = [{ status: "running" }];
  f.conversation.pending = [{ kind: "question", status: "pending" }];
  assert.equal(f.api.taskArchiveActivity(f.task, f.conversation), null);
  f.conversation.interaction_state = "waiting_for_human";
  assert.equal(f.api.taskArchiveActivity(f.task, f.conversation), "active");
  f.conversation.interaction_state = "idle"; f.conversation.agent_response_running = true;
  assert.equal(f.api.taskArchiveActivity(f.task, f.conversation), "active");
});

test("promoting a conversation to a task reveals its imported dataset evidence", () => {
  const ui = new Proxy({}, { get: (target, key) => target[key] ||= {} });
  ui.datasetCard.hidden = true;
  const context = {
    ui, state: { selectedTaskId: "task-a", conversation: { pending: [] } },
    currentHumanCheckpoint: () => null, dataUploadQuestionCheckpoint: () => null,
    renderComposerAttachment() {}, renderMaterialControls() {},
    task: { task_id: "task-a", capability_decision: { status: "resolved" }, dataset_report: { total_images: 90, class_count: 2, rejected_count: 0 } },
  };
  vm.runInNewContext(section("function datasetUploadAvailability", "function dataUploadCheckpointAnswers") + section("function datasetDetail", "function restoreCheckpointCard") + section("function renderDataset", "function gateEntries") + "\nrenderDataset(task);", context);
  assert.equal(ui.datasetCard.hidden, false);
  assert.equal(ui.datasetCount.textContent, "90 张图片");
  assert.match(ui.datasetSummary.textContent, /2 类/);
  assert.equal(ui.datasetButton.disabled, false);
});

for (const [report, expected] of [
  [{ total_images: 90, class_count: 2, class_counts: { red: 45, blue: 45 }, source_filename: "images.zip" }, /90 张图片 · 2 类/],
  [{ total_audio: 120, class_count: 3, speaker_count: 12, source_filename: "words.zip" }, /120 段音频 · 3 类 · 12 个说话人/],
]) {
  test(`contract review includes actual dataset size for ${report.source_filename}`, () => {
    const context = { task: { dataset_report: report } };
    vm.runInNewContext(section("function datasetDetail", "function restoreCheckpointCard") + section("function gateEntries", "function renderContract") + section("function contractApprovalSummary", "function appendApprovalScope") + "\nglobalThis.rows=contractApprovalSummary(task);", context);
    assert.match(context.rows.find(([label]) => label === "数据")[1], expected);
    if (report.class_counts) assert.match(context.rows.find(([label]) => label === "类别分布")[1], /red：45，blue：45/);
  });
}

test("a server-detected queued message offers an explicit stop recovery without automatically cancelling", async () => {
  const f = fixture(); let recovery;
  const previousRequest = f.context.request;
  f.context.showComposerRetry = value => { recovery = value; };
  f.context.request = async (url, options) => {
    if (url.endsWith("/archive")) throw Object.assign(new Error("当前消息仍可能在排队，执行尚未稳定，请先停止当前执行，再归档任务"), { status: 409 });
    return previousRequest(url, options);
  };
  await f.api.confirmTaskArchive(f.task);
  await assert.rejects(f.dialogs[0].onAllow(), /仍可能在排队/);
  assert.equal(recovery.label, "停止当前轮");
  assert.equal(f.requests.filter(([url]) => url.endsWith("/cancel")).length, 0);
  recovery.action();
  assert.equal(f.dialogs[1].allowLabel, "请求停止当前轮");
});

test("archive snapshot checks show busy feedback and ignore repeated clicks until the reply arrives", async () => {
  const f = fixture(); const busy = []; let release;
  f.context.setButtonBusy = (_button, value) => busy.push(value);
  f.context.request = async () => new Promise(resolve => { release = resolve; });
  const first = f.api.confirmTaskArchive(f.task, {});
  await f.api.confirmTaskArchive(f.task, {});
  assert.deepEqual(busy, [true]);
  release({ conversation: f.conversation }); await first;
  assert.deepEqual(busy, [true, false]);
  assert.equal(f.dialogs.length, 1);
});
