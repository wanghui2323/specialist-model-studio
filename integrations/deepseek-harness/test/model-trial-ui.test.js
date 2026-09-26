import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const html = await readFile(new URL("../../../model_harness/web/index.html", import.meta.url), "utf8");
const start = app.indexOf("function resetModelTrials()");
const end = app.indexOf("function renderHfSearchResults()", start);
assert.ok(start > 0 && end > start);
const source = app.slice(start, end);
const digest = "a".repeat(64);
const task = (id = "task-a") => ({ task_id: id, current_spec_revision: 1, model_asset_binding: { asset_id: "asset-a", manifest_sha256: digest, resolved_commit: "b".repeat(40) }, current_run_id: "existing-run", current_result: { status: "completed" } });
const trial = (overrides = {}) => ({ task_id: "task-a", trial_id: "trial-a", operation: "onnx_image_features", status: "pending_approval", state_revision: 1, plan_sha256: digest, input: { filename: "sample.png", sha256: digest, size_bytes: 10 }, context: { model_repo_id: "public/model", resolved_commit: "b".repeat(40) }, stale: false, ...overrides });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
function appFunction(name) {
  const offset = app.indexOf(`function ${name}(`); const next = app.indexOf("\nfunction ", offset + 1);
  assert.ok(offset >= 0 && next > offset); return app.slice(offset, next);
}

function node(tag = "div") {
  let value = "";
  return {
    tag, children: [], dataset: {}, hidden: false, disabled: false, textContent: "", listeners: {}, files: [],
    get value() { return value; }, set value(next) { value = next; if (!next) this.files = []; },
    append(...children) { this.children.push(...children); }, addEventListener(event, callback) { this.listeners[event] = callback; },
    setAttribute(name, next) { this[name] = next; }, removeAttribute(name) { delete this[name]; }, contains() { return false; }, focus() {},
    replaceChildren(...children) { this.children = children; },
    querySelectorAll(selector) { return this.children.flatMap((child) => [...((selector.startsWith(".") ? child.className === selector.slice(1) : child.tag === selector) ? [child] : []), ...(child.querySelectorAll?.(selector) || [])]); },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
  };
}
const flatten = (element) => [element, ...element.children.flatMap(flatten)];
const text = (element) => flatten(element).map((item) => item.textContent).join("\n");

function harness({ records = [], request, fileReader, storage = new Map() } = {}) {
  const state = {
    task: task(), tasks: [], selectedTaskId: "task-a", selectionToken: 1, taskArchiveEpochs: new Map(), runtimeReady: true,
    modelTrials: records, modelTrialsTaskId: "task-a", modelTrialCapability: { available: true }, modelTrialError: null,
    modelTrialLoading: false, modelTrialOperation: 0, modelTrialLoadSeq: 0, modelTrialBusy: false, modelTrialUnknown: false, modelTrialSampleContext: null,
  };
  const ui = Object.fromEntries(["modelTrialInput", "modelTrialSection", "modelTrialCapability", "modelTrialSample", "modelTrialSelectButton", "modelTrialPrepareButton", "modelTrialRefreshButton", "modelTrialNotice", "modelTrialHistory", "modelTrialReport", "modelTrialReportTitle", "modelTrialReportState", "modelTrialReportSummary", "modelTrialReportFacts", "modelTrialReportOutput", "modelTrialReportLimits", "modelTrialReportActions", "modelTrialReportHistory", "modelTrialReportEvidence", "modelTrialReportJson", "modelTrialReportRefreshButton", "inspector", "inspectorEmpty", "objectViewer", "inspectorContent", "workspaceExperience", "inspectorSheetTitle", "inspectorScrim", "workspaceToggleButton", "closeInspectorButton"].map((id) => [id, node()]));
  ui.workspaceToggleButton.append(node("span"));
  const calls = { requests: [], messages: [], notices: [], fileReads: 0, uuid: 0 };
  const context = {
    state, ui, EVIDENCE_SHA256: /^[a-f0-9]{64}$/, isConversationDraft: () => false,
    crypto: { randomUUID: () => `request-${++calls.uuid}` }, document: { createElement: node, createTextNode: (value) => ({ ...node("text"), textContent: value }), body: node("body"), activeElement: null },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    HTMLElement: class {}, window: { requestAnimationFrame: (fn) => fn() }, dockedWorkspaceMedia: { matches: true }, overlayWorkspace: () => false,
    syncInspectorIsolation() {}, syncWorkspaceForTask() {}, setMobileView() {}, activateContext() {}, workspaceSheetTitle: () => "方案与证据", preferredWorkspacePresentation: () => "experience",
    STATUS_LABELS: { awaiting_data: "等待数据", failed: "运行异常", interrupted: "训练已中断" }, RUNNING_STATUSES: new Set(["running", "training"]),
    backgroundCancellationPending: (conversation) => conversation?.background_actions?.some((item) => item.cancel_requested === true) || false,
    currentHumanCheckpoint: (conversation) => conversation?.pending?.[0] || null,
    conversationAgentResponseRunning: (conversation) => conversation?.agent_response_running === true,
    conversationHasBackgroundTraining: (conversation) => conversation?.background_action_running === true,
    clear: (element) => element.replaceChildren(), appendEmpty: (element, value) => { const p = node("p"); p.textContent = value; element.append(p); },
    shortId: (value) => String(value || "—").slice(0, 10), formatBytes: (value) => `${value} bytes`,
    normalizeObjectRefType: (value) => value,
    showNotice: (value, tone) => calls.notices.push({ value, tone }), closeInspector() {},
    submitMessage: async (message) => calls.messages.push(message),
    request: async (path, options = {}) => { calls.requests.push({ path, ...options }); return request ? request(path, options) : path === "/model-trials/capability" ? { available: true, runtime_digest: digest } : { model_trials: records }; },
    FileReader: class { readAsDataURL(file) { calls.fileReads++; if (fileReader) return fileReader(this, file); this.result = "data:image/png;base64,c2FtcGxl"; this.onload(); } },
  };
  context.renderModelAsset = (value) => context.renderModelTrials(value);
  vm.runInNewContext(source, context);
  const checkpointStart = app.indexOf("function syncAgentCheckpoint(task)");
  const checkpointEnd = app.indexOf("function revealCurrentWorkspaceObject", checkpointStart);
  vm.runInNewContext(app.slice(checkpointStart, checkpointEnd), context);
  for (const id of ["agentCheckpoint", "agentCheckpointBody", "agentCheckpointStage", "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointSummary", "agentCheckpointActions", "agentCheckpointWorkspaceLabel", "agentCheckpointWorkspaceHint", "agentCheckpointWorkspaceButton"]) ui[id] = node();
  context.restoreCheckpointCard = () => {};
  context.checkpointCardFor = () => null;
  for (const name of ["workflowStatus", "canonicalInteractionPresentation", "interactionPresentation", "taskListStatus", "syncTaskHeader", "syncSelectedTaskListStatus"]) vm.runInNewContext(appFunction(name), context);
  for (const name of ["uniqueTaskObjectRefs", "workspaceContextForPhase", "workspaceContextForProjection", "workspacePreference", "saveWorkspacePreference", "workspaceMayAutoOpen", "workspaceAutoTarget", "maybeAutoOpenWorkspace", "syncWorkspaceToggle", "toggleWorkspace", "openInspector", "closeInspector", "handleWorkspaceViewportChange"]) vm.runInNewContext(appFunction(name), context);
  for (const id of ["taskEyebrow", "taskTitle", "taskStatus", "taskList"]) ui[id] = node();
  const selectFile = (overrides = {}) => { ui.modelTrialInput.files = [{ name: "sample.png", size: 10, ...overrides }]; context.selectModelTrialSample(); };
  return { context, state, ui, calls, selectFile, storage };
}

test("model trial is an asset-card auxiliary entry, never a synthetic conversation action or TrainingRun", () => {
  assert.ok(html.indexOf('id="modelTrialSection"') > html.indexOf('id="modelAssetBinding"'));
  assert.ok(html.indexOf('id="modelTrialSection"') < html.indexOf('id="hfDiscovery"'));
  assert.match(app, /await loadModelTrials\(response.task\)/);
  assert.match(app, /function resetHfDiscovery[^]*?resetModelTrials\(\)/);
  assert.doesNotMatch(source, /approval_confirmed|actor\s*:\s*["']user|state\.task\.(?:status|current_run_id|current_result)\s*=/);
  assert.doesNotMatch(source, /object_refs\s*:|actions\.push|\/execute["'`]/);
  assert.match(app, /raw === "model_harness_execute_model_trial"[^\n]*CPU、内存与超时上限[^\n]*批准本次隔离试跑/);
});

test("refresh and historical success are GET-only, retain training truth and never run automatically", async () => {
  const record = trial({ status: "succeeded", result: { features: [0.1, -1], classes: ["a", "b"], provider: "CPUExecutionProvider" } });
  const { context, state, ui, calls } = harness({ records: [record] });
  const before = JSON.stringify(state.task);
  await context.loadModelTrials();
  assert.equal(calls.requests.length, 2);
  assert.ok(calls.requests.every((item) => !item.method));
  assert.equal(calls.messages.length, 0);
  assert.equal(JSON.stringify(state.task), before);
  assert.match(text(ui.modelTrialHistory), /执行已完成/);
  assert.match(text(ui.modelTrialHistory), /不是训练完成.*不代表业务准确率/);
  assert.match(text(ui.modelTrialHistory), /"features"/);
});

test("trial section collapses and evidence disclosure survives unchanged refresh and state updates", () => {
  assert.match(html, /<details class="model-trial-section"/);
  const record = trial({ limits: { cpus: 2, memory_bytes: 1024, timeout_seconds: 60 } });
  const { context, state, ui } = harness({ records: [record] }); context.renderModelTrials(state.task);
  const row = ui.modelTrialHistory.children[0]; const disclosure = row.children.find((item) => item.tag === "details");
  disclosure.open = true; disclosure.listeners.toggle(); context.renderModelTrials(state.task);
  assert.equal(ui.modelTrialHistory.children[0], row, "unchanged polls preserve DOM and keyboard focus");
  state.modelTrials = [{ ...record, status: "running", state_revision: 2 }]; context.renderModelTrials(state.task);
  assert.equal(ui.modelTrialHistory.children[0].children.find((item) => item.tag === "details").open, true);
  assert.match(text(ui.modelTrialHistory), /单张图片.*\n资源上限：2 CPU.*超时 60 秒/);
});

test("canonical newest-first history preserves starting state and its stop control", () => {
  const records = [trial({ trial_id: "newest", status: "starting" }), trial({ trial_id: "older", status: "cancelled" })];
  const { context, state, ui } = harness({ records }); context.renderModelTrials(state.task);
  assert.equal(context.validModelTrial(records[0], state.selectedTaskId), true);
  assert.equal(ui.modelTrialHistory.children[0].dataset.trialId, "newest");
  assert.match(text(ui.modelTrialHistory.children[0]), /隔离环境启动中[^]*请求停止/);
});

test("observed task-owned trial becomes a non-AI main summary without pretending training completed", () => {
  const { context, state, ui, calls } = harness({ records: [trial({ status: "succeeded" })] });
  delete state.task.current_run_id; delete state.task.current_result; state.task.status = "awaiting_data"; state.runtimeReady = false;
  const before = JSON.stringify(state.task); context.syncAgentCheckpoint(state.task);
  assert.equal(ui.agentCheckpoint.hidden, false); assert.equal(ui.agentCheckpoint.dataset.kind, "model-trial-summary");
  assert.match(ui.agentCheckpointStage.textContent, /非 AI 回复/);
  assert.equal(ui.agentCheckpointWorkspaceLabel.textContent, "查看试跑报告");
  assert.equal(ui.agentCheckpointWorkspaceButton.dataset.target, "model-trial");
  assert.match(ui.agentCheckpointSummary.textContent, /尚未创建训练 Run.*如果选择继续训练，再准备训练数据/);
  assert.equal(JSON.stringify(state.task), before); assert.equal(calls.messages.length, 0); assert.equal(calls.requests.length, 0);
  state.modelTrialError = "offline"; context.syncAgentCheckpoint(state.task);
  assert.equal(ui.agentCheckpointState.textContent, "状态待刷新"); assert.match(ui.agentCheckpointSummary.textContent, /上次记录/);
});

test("uncertain request outcomes remain explicit in the trial shortcut until GET reconciliation", async () => {
  for (const status of ["succeeded", "cancelled", "pending_approval"]) {
    const { context, state, ui, calls } = harness({ records: [trial({ status })] });
    delete state.task.current_run_id; delete state.task.current_result; state.task.status = "awaiting_data";
    context.syncAgentCheckpoint(state.task); assert.equal(ui.agentCheckpoint.dataset.readError, "false");
    state.modelTrialUnknown = true; assert.equal(state.modelTrialError, null);
    context.syncAgentCheckpoint(state.task);
    assert.equal(ui.agentCheckpoint.hidden, false);
    assert.equal(ui.agentCheckpoint.dataset.readError, "true", "uncertain writes must not match normal-state deduplication selectors");
    assert.equal(ui.agentCheckpointState.dataset.state, "observation_degraded");
    assert.equal(ui.agentCheckpointState.textContent, "状态待刷新");
    assert.equal(ui.agentCheckpointWorkspaceHint.textContent, "sample.png · 状态待核验");
    assert.match(ui.agentCheckpointSummary.textContent, /上次记录[^]*请求结果尚未确认[^]*不会自动重发请求/);
    assert.doesNotMatch(ui.agentCheckpointSummary.textContent, /最新记录|当前读取失败/);
    assert.equal(context.modelTrialCanWrite(), false);
    await context.loadModelTrials();
    assert.equal(state.modelTrialUnknown, false);
    assert.equal(ui.agentCheckpoint.dataset.readError, "false");
    assert.equal(ui.agentCheckpointWorkspaceHint.textContent, `sample.png · ${context.modelTrialStatusLabel(status)}`);
    assert.ok(calls.requests.every((call) => !call.method)); assert.equal(calls.messages.length, 0);
  }
});

test("trial summary never overrides real checkpoints, active agent/training or foreign/missing evidence", () => {
  for (const mutate of [
    (state) => { state.conversation = { pending: [{ kind: "approval", rpc_id: "approval-a" }] }; },
    (state) => { state.conversation = { pending: [{ kind: "question", rpc_id: "question-a" }] }; },
    (state) => { state.conversation = { agent_response_running: true }; },
    (state) => { state.task.status = "running"; },
    (state) => { state.task.current_run_id = "run-a"; },
    (state) => { state.task.current_result = { status: "running" }; },
    (state) => { state.task.run_ids = ["previous-run"]; },
    (state) => { state.task.archived_at_utc = "2026-09-12"; },
    (state) => { state.modelTrialsTaskId = "other"; },
    (state) => { state.modelTrials = [trial({ task_id: "other" })]; },
    (state) => { state.modelTrials = []; },
  ]) {
    const { context, state, ui } = harness({ records: [trial()] }); delete state.task.current_result; delete state.task.current_run_id;
    mutate(state); assert.equal(context.modelTrialTaskSummary(state.task), null); context.syncAgentCheckpoint(state.task);
    assert.equal(ui.agentCheckpoint.hidden, true); assert.equal(ui.agentCheckpoint.dataset.kind, undefined);
  }
});

test("model trial entry opens its readable report directly without technical tabs or new requests", () => {
  const { context, state, ui, calls } = harness({ records: [trial()] });
  assert.equal(context.openModelTrialWorkspace(), true);
  assert.equal(state.inspectorMode, "model-trial"); assert.equal(ui.modelTrialReport.hidden, false);
  assert.equal(ui.inspectorContent.hidden, true); assert.equal(ui.workspaceExperience.hidden, true); assert.equal(ui.objectViewer.hidden, true);
  assert.equal(ui.inspectorSheetTitle.textContent, "模型试跑报告"); assert.equal(ui.inspector.dataset.presentation, undefined);
  assert.match(ui.modelTrialReportSummary.textContent, /尚未执行/); assert.doesNotMatch(text(ui.modelTrialReportOutput), /0\.1/);
  state.selectedTaskId = "other"; assert.equal(context.openModelTrialWorkspace(), false); assert.equal(calls.requests.length, 0);
  context.renderModelTrialReport(); assert.equal(ui.modelTrialReport.hidden, true);
});

test("model trial report header preserves file and state without repeating the sheet title", () => {
  const reportStart = html.indexOf('id="modelTrialReport"');
  const headerEnd = html.indexOf("</header>", reportStart);
  const reportHeader = html.slice(reportStart, headerEnd);
  assert.ok(reportStart > 0 && headerEnd > reportStart);
  assert.match(reportHeader, /<h2 id="modelTrialReportTitle">这次图片试跑<\/h2>/);
  assert.match(reportHeader, /id="modelTrialReportState"/);
  assert.doesNotMatch(reportHeader, /<span>模型试跑报告<\/span>/);
});

test("readable successful report renders exact raw values and timing, not probabilities or quality claims", () => {
  const record = trial({ status: "succeeded", result: { features: [2.25, -0.75], classes: ["cat", "dog"], timing: { inference_ms: 12.34 } } });
  const { context, ui, calls } = harness({ records: [record] }); context.openModelTrialWorkspace();
  assert.equal(ui.modelTrialReportTitle.textContent, "sample.png");
  assert.match(text(ui.modelTrialReportFacts), /public\/model[^]*12\.34 ms/);
  assert.match(text(ui.modelTrialReportOutput), /cat[^]*2\.25[^]*dog[^]*-0\.75/);
  assert.doesNotMatch(text(ui.modelTrialReportOutput), /%|准确率|概率/);
  assert.match(ui.modelTrialReportLimits.textContent, /不是训练完成.*不代表业务准确率/);
  assert.doesNotMatch(text(ui.modelTrialReportFacts), /trial-a|plan_sha256/);
  assert.match(ui.modelTrialReportJson.textContent, /trial-a/); assert.ok(!ui.modelTrialReportEvidence.open);
  assert.equal(calls.requests.length, 0); assert.equal(calls.messages.length, 0);
});

test("non-success, stopping and unknown states never render incidental result fields", () => {
  for (const status of ["pending_approval", "running", "cancel_requested", "cancelled", "failed", "timed_out", "blocked_environment", "observation_degraded"]) {
    const { context, ui } = harness({ records: [trial({ status, result: { features: [123.456], classes: ["accidental"] } })] });
    context.openModelTrialWorkspace(); assert.equal(ui.modelTrialReport.dataset.status, status);
    assert.doesNotMatch(text(ui.modelTrialReportOutput), /123\.456|accidental/);
    if (status === "cancel_requested") assert.match(ui.modelTrialReportSummary.textContent, /不能视为已停止/);
    if (status === "observation_degraded") assert.match(ui.modelTrialReportSummary.textContent, /不能|证据不足/);
  }
});

test("malformed successful output fails visibly instead of becoming a green readable result", () => {
  for (const result of [null, { features: [0.5], classes: [] }, { features: [Infinity], classes: ["cat"] }, { features: [1], classes: [{}] }]) {
    const { context, ui } = harness({ records: [trial({ status: "succeeded", result })] }); context.openModelTrialWorkspace();
    assert.equal(ui.modelTrialReport.dataset.status, "observation_degraded"); assert.equal(ui.modelTrialReportState.textContent, "输出待核验");
    assert.match(text(ui.modelTrialReportOutput), /暂无可读/);
  }
});

test("report limits default output to twelve original-order values and resets details on explicit record change", () => {
  const values = Array.from({ length: 20 }, (_, index) => index - 10);
  const { context, ui } = harness({ records: [trial({ trial_id: "first", status: "succeeded", result: { features: values, classes: values.map((_, index) => `label-${index}`) } }), trial({ trial_id: "second" })] });
  context.openModelTrialWorkspace("first"); assert.equal(ui.modelTrialReportOutput.querySelectorAll("li").length, 12);
  assert.match(text(ui.modelTrialReportOutput), /前 12 项，共 20 项/); assert.match(ui.modelTrialReportJson.textContent, /label-19/);
  assert.match(text(ui.modelTrialReportOutput), /非预测排名/);
  assert.match(text(ui.modelTrialReportOutput), /名称来自模型配置.*原始序号.*不一定是分类标签/);
  assert.match(text(ui.modelTrialReportOutput), /不是得分最高的 12 项/);
  assert.equal(text(ui.modelTrialReportOutput.querySelectorAll("li")[0]), "\nlabel-0\n-10");
  assert.equal(text(ui.modelTrialReportOutput.querySelectorAll("li")[11]), "\nlabel-11\n1");
  ui.modelTrialReportEvidence.open = true; context.renderModelTrialReport(); assert.equal(ui.modelTrialReportEvidence.open, true);
  ui.modelTrialReportHistory.children[1].listeners.click(); assert.equal(ui.modelTrialReportEvidence.open, false);
  assert.equal(ui.modelTrialReportHistory.children[1]["aria-pressed"], "true");
});

test("archived stale report remains readable while every execution control is disabled", () => {
  const { context, state, ui, calls } = harness({ records: [trial({ status: "failed", stale: true })] }); state.task.archived_at_utc = "2026-09-12";
  context.openModelTrialWorkspace(); assert.match(ui.modelTrialReportSummary.textContent, /历史记录/);
  assert.match(ui.modelTrialReportLimits.textContent, /任务已归档/);
  assert.ok(ui.modelTrialReportActions.children.every((button) => button.disabled)); assert.equal(calls.requests.length, 0);
  state.modelTrialError = "network"; context.renderModelTrialReport(); assert.equal(ui.modelTrialReportState.textContent, "状态待刷新");
  assert.match(ui.modelTrialReportSummary.textContent, /上次已保存记录/);
});

test("exact task and trial selection survives reload without writes, missing selection is not replaced", async () => {
  const records = [trial({ trial_id: "newest" }), trial({ trial_id: "older", status: "cancelled" })];
  const first = harness({ records }); first.context.openModelTrialWorkspace("older");
  const restored = harness({ records, storage: first.storage }); await restored.context.loadModelTrials();
  assert.equal(restored.state.modelTrialReportSelection.trial_id, "older"); assert.equal(restored.ui.modelTrialReportState.textContent, "已停止");
  assert.ok(restored.calls.requests.every((call) => !call.method)); assert.equal(restored.calls.messages.length, 0);
  const missing = harness({ records: [records[0]], storage: first.storage }); await missing.context.loadModelTrials();
  assert.equal(missing.state.modelTrialReportSelection.trial_id, "older"); assert.match(missing.ui.modelTrialReportTitle.textContent, /暂不可读取/);
  assert.equal(missing.ui.modelTrialReportJson.textContent, "");
  assert.equal(missing.ui.modelTrialReportHistory.hidden, false);
  assert.equal(missing.ui.modelTrialReportHistory.children.length, 1);
  const beforeClicks = missing.calls.requests.length;
  missing.ui.modelTrialReportHistory.children[0].listeners.click();
  assert.equal(missing.state.modelTrialReportSelection.trial_id, "newest");
  assert.match(missing.ui.modelTrialReportSummary.textContent, /计划已保存/);
  assert.equal(missing.calls.requests.length, beforeClicks); assert.equal(missing.calls.messages.length, 0);
  const foreign = harness({ records, storage: first.storage }); foreign.state.selectedTaskId = "task-b"; foreign.state.task = task("task-b");
  assert.equal(foreign.context.modelTrialReportPreference(), null); assert.equal(foreign.context.openModelTrialWorkspace("older"), false);
});

test("closing report preserves its exact selection but does not reopen on a refresh", async () => {
  const { context, state, ui, storage } = harness({ records: [trial()] }); context.openModelTrialWorkspace();
  context.closeInspector({ userInitiated: true }); assert.equal(ui.modelTrialReport.hidden, true);
  assert.equal(JSON.parse(storage.get("model-harness:trial-report:task-a")).open, false);
  await context.loadModelTrials(); assert.equal(state.inspectorMode, "closed");
  const reentry = harness({ records: [trial()], storage }); await reentry.context.loadModelTrials();
  assert.notEqual(reentry.state.inspectorMode, "model-trial"); reentry.context.openModelTrialWorkspace();
  assert.equal(reentry.state.modelTrialReportSelection.trial_id, "trial-a");
});

test("workspace does not auto-open for ordinary prose, phase flags or foreign execution identities", () => {
  const { context, state, ui } = harness(); delete state.task.current_result; delete state.task.current_run_id;
  for (const projection of [
    { phase: "executing", workspace: { auto_open: true }, current_turn: { items: [{ text: "训练已完成" }] } },
    { actions: [{ task_id: "other", action_id: "foreign" }] },
    { work_items: [{ task_id: "task-a", work_item_id: "unverified", delegation_id: "delegation", lineage_verified: false }] },
    { result: { object_refs: [{ task_id: "other", type: "evaluation_report", id: "foreign" }] } },
  ]) assert.equal(context.maybeAutoOpenWorkspace(state.task, projection), false);
  assert.notEqual(ui.inspector.dataset.open, "true");
});

test("observed actions work items and exact background runs auto-open a readable workspace without writes", () => {
  for (const kind of ["action", "work_item", "training"]) {
    const { context, state, ui, calls } = harness(); delete state.task.current_result; delete state.task.current_run_id;
    const projection = { phase: "executing", workspace: { auto_open: false, technical_context: "run", presentation: "experience" }, actions: [], work_items: [] };
    if (kind === "action") projection.actions = [{ task_id: "task-a", action_id: "observed-action" }];
    if (kind === "work_item") projection.work_items = [{ task_id: "task-a", work_item_id: "work-1", delegation_id: "delegation-1", lineage_verified: true }];
    if (kind === "training") state.conversation = { task_id: "task-a", training_runs: [{ task_id: "task-a", training_run_id: "training-1" }] };
    const before = JSON.stringify(state.task); assert.equal(context.maybeAutoOpenWorkspace(state.task, projection), true);
    assert.equal(ui.inspector.dataset.open, "true"); assert.equal(ui.inspector.dataset.presentation, "experience");
    assert.equal(ui.workspaceToggleButton.querySelector("span").textContent, "收起工作区"); assert.equal(ui.workspaceToggleButton["aria-expanded"], "true");
    assert.equal(JSON.stringify(state.task), before); assert.equal(calls.requests.length, 0); assert.equal(calls.messages.length, 0);
  }
});

test("manual workspace close survives phase changes polls and same-task reentry", () => {
  const { context, state, ui, storage } = harness();
  context.maybeAutoOpenWorkspace(); context.toggleWorkspace();
  assert.equal(context.workspacePreference(), "closed"); assert.equal(ui.workspaceToggleButton["aria-expanded"], "false");
  for (const phase of ["executing", "result_ready", "failed", "awaiting_approval"]) {
    state.workspaceProjection = { phase, workspace: { auto_open: true, auto_key: `new-${phase}` }, actions: [{ task_id: "task-a", action_id: `action-${phase}` }] };
    assert.equal(context.maybeAutoOpenWorkspace(), false); context.syncWorkspaceToggle(); assert.equal(ui.inspector.dataset.open, "false");
  }
  const reentry = harness({ storage }); assert.equal(reentry.context.maybeAutoOpenWorkspace(), false);
  assert.notEqual(reentry.ui.inspector.dataset.open, "true");
  reentry.context.toggleWorkspace(); assert.equal(reentry.ui.inspector.dataset.open, "true"); assert.equal(reentry.context.workspacePreference(), "auto");
});

test("workspace close preference belongs to one task and is not borrowed by a new task", () => {
  const { context, state, ui } = harness(); context.openInspector(); context.closeInspector({ userInitiated: true });
  state.task = task("task-b"); state.selectedTaskId = "task-b"; state.selectionToken++;
  assert.equal(context.workspacePreference(), "auto"); assert.equal(context.maybeAutoOpenWorkspace(), true);
  assert.equal(ui.inspector.dataset.open, "true"); context.closeInspector();
  state.task = task(); state.selectedTaskId = "task-a"; state.selectionToken++;
  assert.equal(context.maybeAutoOpenWorkspace(), false); assert.equal(context.workspacePreference(), "closed");
});

test("new observed trial automatically opens its report and exact selection survives manual close and reopening", async () => {
  const records = [trial({ trial_id: "newest" }), trial({ trial_id: "older", status: "cancelled" })];
  const { context, state, ui, storage, calls } = harness({ records }); delete state.task.current_result; delete state.task.current_run_id;
  await context.loadModelTrials(); assert.equal(state.inspectorMode, "model-trial"); assert.equal(state.inspectorAutoOpened, true);
  context.openModelTrialWorkspace("older"); context.toggleWorkspace();
  assert.equal(state.modelTrialReportSelection.trial_id, "older"); assert.equal(context.workspacePreference(), "closed");
  await context.loadModelTrials(); assert.equal(state.inspectorMode, "closed");
  const reentry = harness({ records, storage }); delete reentry.state.task.current_result; delete reentry.state.task.current_run_id;
  await reentry.context.loadModelTrials(); assert.notEqual(reentry.state.inspectorMode, "model-trial");
  reentry.context.toggleWorkspace(); assert.equal(reentry.state.modelTrialReportSelection.trial_id, "older");
  assert.equal(reentry.context.workspacePreference(), "auto"); assert.equal(reentry.ui.workspaceToggleButton.querySelector("span").textContent, "收起工作区");
  assert.ok([...calls.requests, ...reentry.calls.requests].every((call) => !call.method)); assert.equal(reentry.calls.messages.length, 0);
});

test("auto-opened generic execution may advance to its first trial, but selected reports are never replaced", () => {
  const { context, state, ui } = harness(); delete state.task.current_result; delete state.task.current_run_id;
  state.workspaceProjection = { phase: "executing", actions: [{ task_id: "task-a", action_id: "action-1" }] };
  assert.equal(context.maybeAutoOpenWorkspace(), true); assert.equal(state.inspectorMode, "task-workspace");
  state.modelTrials = [trial()]; assert.equal(context.maybeAutoOpenWorkspace(), true); assert.equal(state.inspectorMode, "model-trial");
  state.modelTrials = [trial({ trial_id: "newer" }), trial()];
  assert.equal(context.maybeAutoOpenWorkspace(), false); assert.equal(state.modelTrialReportSelection.trial_id, "trial-a");
  context.openInspector("object-viewer", { objectRef: { type: "evaluation_report", task_id: "task-a", id: "observed-report" } });
  assert.equal(context.maybeAutoOpenWorkspace(), false); assert.equal(state.inspectorMode, "object-viewer");
  context.syncWorkspaceToggle(); assert.equal(ui.workspaceToggleButton.querySelector("span").textContent, "收起工作区");
});

test("same toggle reopens the exact observed object and never manufactures a replacement reference", () => {
  const { context, state, calls } = harness(); const ref = { task_id: "task-a", type: "evaluation_report", id: "observed-report", digest };
  context.openInspector("object-viewer", { objectRef: ref }); context.toggleWorkspace();
  let reopened; context.openObjectRef = (value) => { reopened = value; }; context.toggleWorkspace();
  assert.equal(reopened, ref); assert.equal(state.workspaceTargets.get("task-a").objectRef, ref);
  assert.equal(calls.requests.length, 0); assert.equal(calls.messages.length, 0);
});

test("reopening a persisted tool event uses its original event reader rather than a domain object route", () => {
  const { context } = harness(); const ref = { task_id: "task-a", type: "event_result", id: "event-observed", projector_revision: "projector-1" };
  context.openInspector("object-viewer", { objectRef: ref }); context.toggleWorkspace();
  let reopened; context.openEventResultRef = (value) => { reopened = value; }; context.openObjectRef = () => assert.fail("event is not a domain object");
  context.toggleWorkspace(); assert.equal(reopened, ref);
});

test("storage failures still respect manual close in this page and narrow layouts do not auto-open", () => {
  const { context, state, ui } = harness(); context.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  context.openInspector(); context.closeInspector({ userInitiated: true });
  assert.equal(context.maybeAutoOpenWorkspace(), false); assert.equal(ui.inspector.dataset.open, "false");
  context.saveWorkspacePreference("auto"); context.dockedWorkspaceMedia.matches = false;
  assert.equal(context.maybeAutoOpenWorkspace(), false); assert.equal(ui.inspector.dataset.open, "false");
  state.selectedTaskId = "other"; assert.equal(context.workspaceMayAutoOpen(), false);
});

test("900px PC dock keeps the conversation editable while its workspace is open", () => {
  assert.match(app, /dockedWorkspaceMedia = window\.matchMedia\("\(min-width:900px\)"\)/);
  assert.match(app, /dockedWorkspaceMedia\.addEventListener\("change", handleWorkspaceViewportChange\)/);
  for (const width of [900, 1024, 1279, 1440]) {
    const { context, ui } = harness(); context.dockedWorkspaceMedia.matches = width >= 900;
    for (const id of ["sidebar", "conversationMain", "mobileViewNav"]) ui[id] = node();
    for (const name of ["overlayWorkspace", "syncInspectorIsolation"]) vm.runInNewContext(appFunction(name), context);
    context.openInspector();
    assert.equal(ui.conversationMain.inert, false); assert.equal(ui.inspectorScrim.hidden, true);
    assert.equal(ui.inspector["aria-modal"], undefined); assert.equal(ui.inspector.dataset.open, "true");
  }
});

test("shrinking below 900 closes both manual and automatic workspace once without persisting a manual close", () => {
  for (const auto of [true, false]) {
    const { context, state, ui, storage } = harness({ records: [trial()] });
    for (const id of ["sidebar", "conversationMain", "mobileViewNav"]) ui[id] = node();
    for (const name of ["overlayWorkspace", "syncInspectorIsolation"]) vm.runInNewContext(appFunction(name), context);
    context.openModelTrialWorkspace(null, { auto }); const before = JSON.stringify([...storage.entries()]);
    const priorSelection = JSON.stringify(state.modelTrialReportSelection); let closes = 0; const close = context.closeInspector;
    context.closeInspector = (options) => { closes++; assert.equal(options.userInitiated, false); close(options); };
    context.dockedWorkspaceMedia.matches = false; context.handleWorkspaceViewportChange();
    assert.equal(closes, 1); assert.equal(ui.inspector.dataset.open, "false"); assert.equal(ui.conversationMain.inert, false);
    assert.equal(ui.inspectorScrim.hidden, true); assert.equal(context.workspacePreference(), "auto");
    assert.equal(JSON.stringify([...storage.entries()]), before); assert.equal(JSON.stringify(state.modelTrialReportSelection), priorSelection);
    context.handleWorkspaceViewportChange(); assert.equal(closes, 1, "repeated viewport observation does not close or reopen again");
    context.dockedWorkspaceMedia.matches = true; context.handleWorkspaceViewportChange();
    assert.equal(closes, 1); assert.equal(ui.inspector.dataset.open, "false", "the resize callback itself never reopens");
    context.toggleWorkspace(); assert.equal(ui.inspector.dataset.open, "true"); assert.equal(ui.conversationMain.inert, false);
  }
});

test("an explicit workspace open below 900 retains the existing overlay and close recovery", () => {
  const { context, ui } = harness(); context.dockedWorkspaceMedia.matches = false;
  for (const id of ["sidebar", "conversationMain", "mobileViewNav"]) ui[id] = node();
  for (const name of ["overlayWorkspace", "syncInspectorIsolation"]) vm.runInNewContext(appFunction(name), context);
  context.openInspector(); assert.equal(ui.conversationMain.inert, true); assert.equal(ui.inspectorScrim.hidden, false); assert.equal(ui.inspector["aria-modal"], "true");
  context.closeInspector({ userInitiated: true }); assert.equal(ui.conversationMain.inert, false); assert.equal(ui.inspectorScrim.hidden, true);
});

test("trial GET completion synchronizes header sidebar and checkpoint from the same observation", async () => {
  const { context, state, ui } = harness({ records: [], request: async (path) => path.endsWith("capability") ? { available: true } : { model_trials: [trial({ status: "cancelled" })] } });
  delete state.task.current_result; delete state.task.current_run_id; state.task.status = "awaiting_data";
  state.conversation = { task_id: "task-a", interaction_projection: { schema_version: "1.0", phase: "idle" } }; state.tasks = [state.task];
  const button = node("button"); button.className = "task-item"; button.dataset.taskId = "task-a";
  const row = node(); row.className = "task-workflow"; row.append(node("i")); button.append(row); ui.taskList.append(button);
  context.syncTaskHeader(state.task); assert.equal(ui.taskEyebrow.textContent, "等待数据");
  await context.loadModelTrials();
  assert.equal(ui.taskEyebrow.textContent, "模型试跑 · 已停止"); assert.match(text(row), /模型试跑 · 已停止/);
  assert.equal(ui.agentCheckpointState.textContent, "已停止"); assert.equal(state.task.status, "awaiting_data");
});

test("selected task header and sidebar use observed trial state without changing underlying waiting-data status", () => {
  for (const [status, label] of [["cancelled", "模型试跑 · 已停止"], ["succeeded", "试跑记录可查看"], ["pending_approval", "模型试跑 · 等待原生审批"]]) {
    const { context, state, ui } = harness({ records: [trial({ status })] }); delete state.task.current_result; delete state.task.current_run_id;
    state.task.status = "awaiting_data"; state.conversation = { task_id: state.task.task_id, agent_response_running: false, interaction_projection: { schema_version: "1.0", phase: "completed" } };
    state.tasks = [state.task]; const button = node("button"); button.className = "task-item"; button.dataset.taskId = state.task.task_id;
    const row = node(); row.className = "task-workflow"; const dot = node("i"); row.append(dot); button.append(row); ui.taskList.append(button);
    const before = JSON.stringify(state.task);
    context.syncTaskHeader(state.task, state.conversation, { phase: "idle" });
    assert.equal(ui.taskEyebrow.textContent, label); assert.equal(ui.taskStatus.textContent, label);
    assert.equal(context.taskListStatus(state.task, state.conversation).label, label);
    context.syncSelectedTaskListStatus(state.conversation, { phase: "idle" }); assert.match(text(row), new RegExp(label));
    assert.equal(JSON.stringify(state.task), before);
    if (status === "pending_approval") { context.syncAgentCheckpoint(state.task); assert.match(ui.agentCheckpointSummary.textContent, /查看计划或已有输出/); assert.doesNotMatch(ui.agentCheckpointSummary.textContent, /可以先查看试跑输出/); }
  }
});

test("trial display never borrows another task cache or overrides protected failure stopping and human states", () => {
  const cases = [
    (state) => { state.conversation.interaction_projection.phase = "failed"; },
    (state) => { state.conversation.interaction_projection.phase = "observation_degraded"; },
    (state) => { state.conversation.interaction_projection.phase = "stopping"; },
    (state) => { state.conversation.interaction_projection.phase = "waiting_approval"; },
    (state) => { state.conversation.interaction_projection.phase = "waiting_question"; },
    (state) => { state.conversation.agent_response_running = true; },
    (state) => { state.conversation.background_action_running = true; },
    (state) => { state.conversation.projection_health = { status: "observation_degraded" }; },
    (state) => { state.conversation.background_actions = [{ cancel_requested: true }]; },
    (state) => { state.task.status = "failed"; },
    (state) => { state.conversation.pending = [{ kind: "approval", rpc_id: "rpc" }]; },
    (state) => { state.task.current_run_id = "actual-training"; },
    (state) => { state.task.archived_at_utc = "today"; },
    (state) => { state.modelTrialsTaskId = "other"; },
    (state) => { state.selectedTaskId = "other"; },
  ];
  for (const mutate of cases) {
    const { context, state } = harness({ records: [trial({ status: "succeeded" })] }); delete state.task.current_result; delete state.task.current_run_id;
    state.task.status = "awaiting_data"; state.conversation = { task_id: state.task.task_id, interaction_projection: { schema_version: "1.0", phase: "idle" } };
    mutate(state); assert.equal(context.modelTrialDisplayStatus(state.task, state.conversation), null);
  }
  const { context, state } = harness({ records: [trial({ status: "succeeded" })] }); delete state.task.current_result; delete state.task.current_run_id; state.task.status = "awaiting_data";
  const other = { task_id: "task-b", status: "awaiting_data" };
  assert.equal(context.taskListStatus(other, { task_id: "task-b" }).label, "等待数据");
  assert.equal(context.modelTrialDisplayStatus(state.task, { task_id: "task-b" }), null);
  assert.equal(context.modelTrialDisplayStatus(state.task, null, { phase: "failed" }), null);
  state.modelTrialError = "offline"; assert.equal(context.modelTrialDisplayStatus(state.task).label, "试跑状态待核验");
});

test("prepare saves one pending plan with local base64 input and no approval or message", async () => {
  const record = trial();
  const { context, state, ui, calls, selectFile } = harness({ request: async (path, options) => options.method ? { model_trial: record } : path.endsWith("capability") ? { available: true } : { model_trials: [record] } });
  selectFile(); await context.prepareModelTrial();
  const writes = calls.requests.filter((item) => item.method);
  assert.equal(writes.length, 1); assert.equal(writes[0].path, "/tasks/task-a/model-trials");
  assert.deepEqual(JSON.parse(JSON.stringify(writes[0].json)), { filename: "sample.png", input_base64: "c2FtcGxl", request_id: "request-1" });
  assert.equal(calls.messages.length, 0); assert.equal(ui.modelTrialInput.files.length, 0); assert.equal(state.modelTrialBusy, false);
  assert.equal(state.modelTrials[0].trial_id, record.trial_id);
});

test("invalid, empty and oversized samples never reach FileReader or API", async () => {
  for (const file of [{ name: "script.py" }, { size: 0 }, { size: 4 * 1024 * 1024 + 1 }]) {
    const { context, calls, selectFile } = harness(); selectFile(file); await context.prepareModelTrial();
    assert.equal(calls.fileReads, 0); assert.equal(calls.requests.length, 0);
  }
});

test("double click sends at most one prepare request", async () => {
  const wait = deferred(); const { context, calls, selectFile } = harness({ request: async (_path, options) => options.method ? wait.promise : { model_trials: [] } });
  selectFile(); const first = context.prepareModelTrial(); await Promise.resolve(); await context.prepareModelTrial();
  assert.equal(calls.requests.length, 1); wait.resolve({ model_trial: trial() }); await first;
  assert.equal(calls.requests.filter((item) => item.method).length, 1);
});

test("network uncertainty keeps sample and blocks another create until explicit GET reconciliation", async () => {
  const { context, state, ui, calls, selectFile } = harness({ request: async (path, options) => { if (options.method) throw new Error("network lost"); return path.endsWith("capability") ? { available: true } : { model_trials: [trial()] }; } });
  selectFile(); await context.prepareModelTrial(); await context.prepareModelTrial();
  assert.equal(calls.requests.length, 1); assert.equal(state.modelTrialUnknown, true); assert.equal(ui.modelTrialInput.files.length, 1);
  assert.match(ui.modelTrialNotice.textContent, /不会自动重发/);
  await context.loadModelTrials(); assert.equal(state.modelTrialUnknown, false);
  assert.equal(calls.requests.filter((item) => item.method).length, 1);
});

test("prepare and mutation failures synchronize the task header and shortcut before any poll", async () => {
  for (const action of ["prepare", "cancel"]) {
    const record = trial({ status: action === "prepare" ? "cancelled" : "running" });
    const { context, state, ui, calls, selectFile } = harness({ records: [record], request: async () => { throw new Error("response lost"); } });
    delete state.task.current_result; delete state.task.current_run_id; state.task.status = "awaiting_data";
    context.saveWorkspacePreference("closed"); context.syncModelTrialPresentation();
    assert.equal(ui.agentCheckpoint.dataset.readError, "false");
    if (action === "prepare") { selectFile(); await context.prepareModelTrial(); }
    else await context.mutateModelTrial(record, action);
    // No explicit presentation call or poll after the failed request.
    assert.equal(state.modelTrialUnknown, true); assert.equal(state.modelTrialBusy, false);
    assert.equal(ui.taskEyebrow.textContent, "试跑状态待核验");
    assert.equal(ui.agentCheckpoint.dataset.readError, "true");
    assert.match(ui.agentCheckpointSummary.textContent, /请求结果尚未确认/);
    assert.equal(ui.agentCheckpointWorkspaceHint.textContent, "sample.png · 状态待核验");
    assert.notEqual(ui.inspector.dataset.open, "true", "failure refresh must still respect the user's closed workspace");
    assert.equal(calls.requests.length, 1); assert.equal(calls.requests[0].method, "POST");
    assert.equal(calls.messages.length, 0);
  }
});

test("late prepare and mutation failures do not synchronize a different selected task", async () => {
  for (const action of ["prepare", "cancel"]) {
    const wait = deferred();
    const record = trial({ status: "running" });
    const { context, state, ui, calls, selectFile } = harness({ records: [record], request: async () => { await wait.promise; throw new Error("late response lost"); } });
    let synchronizations = 0; context.syncModelTrialPresentation = () => { synchronizations += 1; };
    if (action === "prepare") selectFile();
    const pending = action === "prepare" ? context.prepareModelTrial() : context.mutateModelTrial(record, action);
    await Promise.resolve(); await Promise.resolve();
    assert.equal(calls.requests.length, 1);
    state.selectedTaskId = "task-b"; state.task = task("task-b"); state.selectionToken += 1;
    ui.taskEyebrow.textContent = "B 的既有状态";
    wait.resolve(); await pending;
    assert.equal(synchronizations, 0); assert.equal(state.modelTrialUnknown, false);
    assert.equal(ui.taskEyebrow.textContent, "B 的既有状态"); assert.equal(calls.notices.length, 0);
  }
});

test("unavailable isolation disables preparing but preserves historical evidence", async () => {
  const { context, state, ui, calls, selectFile } = harness({ records: [trial({ status: "failed" })] });
  state.modelTrialCapability = { available: false, reason: "runtime_unconfigured" };
  selectFile(); await context.prepareModelTrial();
  assert.equal(calls.requests.length, 0); assert.equal(ui.modelTrialPrepareButton.disabled, true);
  assert.match(ui.modelTrialCapability.textContent, /runtime_unconfigured/); assert.equal(ui.modelTrialHistory.children.length, 1);
});

test("archived tasks are read-only across sample preparation, approval, retry, stop and reconcile", async () => {
  const { context, state, ui, calls, selectFile } = harness({ records: [trial()] }); state.task.archived_at_utc = "2026-09-12";
  selectFile(); await context.prepareModelTrial(); await context.requestModelTrialApproval(trial());
  for (const [action, status] of [["cancel", "running"], ["retry", "failed"], ["reconcile", "observation_degraded"]]) await context.mutateModelTrial(trial({ status }), action);
  assert.equal(calls.requests.length, 0); assert.equal(calls.messages.length, 0); assert.equal(ui.modelTrialSelectButton.disabled, true);
  await context.loadModelTrials(); assert.equal(calls.requests.length, 2); assert.ok(calls.requests.every((item) => !item.method));
  assert.match(ui.modelTrialNotice.textContent, /恢复任务不会自动试跑/);
});

test("approval re-reads exact trial and sends identity only to the existing coordinator", async () => {
  const record = trial(); const { context, state, calls } = harness({ records: [record], request: async () => ({ model_trial: record }) });
  await context.requestModelTrialApproval(record);
  assert.equal(calls.requests.length, 1); assert.equal(calls.requests[0].method, undefined);
  assert.equal(calls.messages.length, 1); assert.match(calls.messages[0], /task_id=task-a[^]*trial_id=trial-a[^]*plan_sha256=/);
  assert.equal(calls.messages[0], `请核对这次模型试跑计划，说明用途和资源范围，并向我申请执行批准。\n\n关联的试跑计划：\ntask_id=task-a\ntrial_id=trial-a\nplan_sha256=${digest}`);
  assert.doesNotMatch(calls.messages[0], /model_harness_execute_model_trial|model_harness_get_model_trial/);
  assert.doesNotMatch(calls.messages[0], /c2FtcGxl|base64|sample\.png/); assert.equal(state.modelTrialBusy, false);
});

test("approval fails closed for disconnected runtime, stale or changed plan, wrong owner and state", async () => {
  for (const bad of [trial({ task_id: "other" }), trial({ plan_sha256: "c".repeat(64) }), trial({ trial_id: "wrong" }), trial({ stale: true }), trial({ status: "running" })]) {
    const { context, calls } = harness({ request: async () => ({ model_trial: bad }) }); await context.requestModelTrialApproval(trial()); assert.equal(calls.messages.length, 0);
  }
  const { context, state, calls } = harness(); state.runtimeReady = false; await context.requestModelTrialApproval(trial());
  assert.equal(calls.requests.length, 0);
});

test("task switch A-B-A fences late list and approval responses despite same task id", async () => {
  for (const action of ["list", "approval"]) {
    const wait = deferred(); const { context, state, calls } = harness({ request: async (path) => path.endsWith("capability") ? { available: true } : wait.promise });
    const pending = action === "list" ? context.loadModelTrials() : context.requestModelTrialApproval(trial());
    state.selectedTaskId = "task-b"; state.selectionToken++; context.resetModelTrials(); state.task = task("task-b");
    state.selectedTaskId = "task-a"; state.selectionToken++; context.resetModelTrials(); state.task = task();
    wait.resolve(action === "list" ? { model_trials: [trial()] } : { model_trial: trial() }); await pending;
    assert.equal(state.modelTrials.length, 0); assert.equal(calls.messages.length, 0);
  }
});

test("archive epoch and model/spec changes fence late reads and clear selected file", async () => {
  for (const mutate of [(state) => state.taskArchiveEpochs.set("task-a", 1), (state) => state.task.current_spec_revision++, (state) => { state.task.model_asset_binding.manifest_sha256 = "c".repeat(64); }]) {
    const wait = deferred(); const { context, state, calls, ui, selectFile } = harness({ request: async () => wait.promise });
    selectFile(); const pending = context.requestModelTrialApproval(trial()); mutate(state); context.renderModelTrials(state.task);
    wait.resolve({ model_trial: trial() }); await pending; assert.equal(calls.messages.length, 0); assert.equal(state.modelTrialBusy, false);
    if (state.taskArchiveEpochs.size === 0) assert.equal(ui.modelTrialInput.files.length, 0);
  }
});

test("switch or context change while reading file prevents POST and reset clears selected sample", async () => {
  let reader; const { context, state, ui, calls, selectFile } = harness({ fileReader: (value) => { reader = value; } });
  selectFile(); const pending = context.prepareModelTrial(); state.selectionToken++; context.resetModelTrials();
  reader.result = "data:image/png;base64,c2FtcGxl"; reader.onload(); await pending;
  assert.equal(calls.requests.length, 0); assert.equal(ui.modelTrialInput.files.length, 0); assert.equal(state.modelTrialBusy, false);
});

test("out of order reads and older operation responses cannot replace newer canonical records", async () => {
  const waits = [deferred(), deferred()]; let i = 0;
  const { context, state } = harness({ request: async (path) => path.endsWith("capability") ? { available: true } : waits[i++].promise });
  const first = context.loadModelTrials(); const second = context.loadModelTrials();
  waits[1].resolve({ model_trials: [trial({ state_revision: 2, status: "running" })] }); await second;
  waits[0].resolve({ model_trials: [trial()] }); await first; assert.equal(state.modelTrials[0].state_revision, 2);
});

test("invalid list response preserves old evidence and disables writes without inventing records", async () => {
  for (const records of [[trial({ task_id: "other" })], [trial(), trial()], [trial({ plan_sha256: "missing" })]]) {
    const good = trial(); const { context, state, ui } = harness({ records: [good], request: async (path) => path.endsWith("capability") ? { available: true } : { model_trials: records } });
    await context.loadModelTrials(); assert.equal(state.modelTrials[0], good); assert.ok(state.modelTrialError); assert.equal(ui.modelTrialSelectButton.disabled, true);
  }
});

test("cancel_requested remains stopping; retry creates a new pending plan and never automatically approves", async () => {
  for (const [action, original, returned] of [["cancel", "running", trial({ status: "cancel_requested" })], ["retry", "timed_out", trial({ trial_id: "trial-retry" })], ["reconcile", "observation_degraded", trial({ status: "observation_degraded" })]]) {
    const { context, state, ui, calls } = harness({ records: [trial({ status: original })], request: async (path, options) => options.method ? { model_trial: returned } : path.endsWith("capability") ? { available: true } : { model_trials: [returned] } });
    await context.mutateModelTrial(trial({ status: original }), action);
    const writes = calls.requests.filter((item) => item.method); assert.equal(writes.length, 1); assert.ok(writes[0].path.endsWith(`/${action}`));
    assert.equal(Object.keys(writes[0].json).length, action === "retry" ? 1 : 0); assert.equal(calls.messages.length, 0); assert.equal(state.modelTrialBusy, false);
    if (action === "cancel") assert.match(text(ui.modelTrialHistory), /正在停止.*\n[^]*等待后端确认/);
    if (action === "reconcile") assert.match(text(ui.modelTrialHistory), /不能确认仍在运行或已经停止/);
  }
});

test("unsupported action, stale retry and mismatched mutation identity never create usable new result", async () => {
  const { context, calls } = harness(); await context.mutateModelTrial(trial({ status: "failed", stale: true }), "retry"); await context.mutateModelTrial(trial(), "execute");
  assert.equal(calls.requests.length, 0);
  const wrong = harness({ request: async () => ({ model_trial: trial({ task_id: "other" }) }) });
  await wrong.context.mutateModelTrial(trial({ status: "running" }), "cancel"); assert.equal(wrong.state.modelTrialUnknown, true); assert.equal(wrong.state.modelTrials.length, 0);
});
