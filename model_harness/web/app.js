const ACTIVE_RUN_STATUSES = new Set(["created", "queued", "preflight", "training", "evaluating", "proposing", "packaging", "needs_input"]);
const TASK_STATUS_LABELS = { draft: "草稿", data_ready: "数据已体检", ready: "合同已确认", running: "运行中", completed: "已完成", failed: "运行异常" };
const RUN_STATUS_LABELS = { created: "已创建", queued: "排队", preflight: "合同检查", training: "训练", evaluating: "评测", proposing: "生成策略", packaging: "打包制品", completed: "完成", cancelled: "取消", failed: "失败", interrupted: "中断" };

const ui = Object.fromEntries([
  "taskList", "newTaskButton", "welcomeCreateButton", "refreshTasksButton", "reloadTaskButton", "welcomePanel", "taskWorkspace", "pageTitle", "serviceState",
  "taskIdLabel", "taskStatus", "taskName", "taskGoal", "notice", "datasetFile", "filePickerTitle", "filePickerHint", "uploadDatasetButton",
  "dataStepState", "datasetReport", "reportSummary", "classBars", "riskList", "previewGrid", "contractStepState", "contractForm", "accuracyGate",
  "macroF1Gate", "recallGate", "imageSize", "saveContractButton", "confirmAuthorization", "confirmLabels", "confirmGates", "confirmContractButton",
  "runStepState", "startRunButton", "cancelRunButton", "runDuration", "runIdLabel", "eventLog", "gateSummary", "metricGrid", "candidateTable",
  "failureBlock", "failureGrid", "strategyBlock", "strategyList", "artifactBlock", "artifactList", "createTaskDialog", "createTaskForm", "newTaskName",
  "newTaskGoal", "createTaskError", "cancelCreateButton", "approvalDialog", "approvalTitle", "approvalDescription"
].map((id) => [id, document.getElementById(id)]));

const appState = {
  tasks: [],
  task: null,
  selectedTaskId: null,
  eventSource: null,
  eventIds: new Set(),
  pendingStrategy: null,
  refreshTimer: null,
  pollingTimer: null,
  contractDirty: false,
};

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const response = await fetch(path, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail || JSON.stringify(body) : body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function clear(element) { while (element.firstChild) element.firstChild.remove(); }
function shortId(value) { return value ? value.length > 28 ? `${value.slice(0, 15)}…${value.slice(-9)}` : value : "—"; }
function formatClock(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function formatDuration(ms) { if (typeof ms !== "number") return "—"; return ms < 1000 ? `${ms.toFixed(ms < 10 ? 1 : 0)} ms` : `${(ms / 1000).toFixed(2)} s`; }
function formatBytes(bytes) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / 1024 / 1024).toFixed(2)} MB`; }
function encodeRelativePath(path) { return path.split("/").map(encodeURIComponent).join("/"); }
function setBusy(button, busy, text) { if (!button.dataset.defaultText) button.dataset.defaultText = button.textContent; button.disabled = busy; button.textContent = busy ? text : button.dataset.defaultText; }

function showNotice(message, tone = "ok") {
  ui.notice.hidden = false;
  ui.notice.dataset.tone = tone;
  ui.notice.textContent = message;
}

function hideNotice() { ui.notice.hidden = true; ui.notice.textContent = ""; }

function setStepState(element, text, state) {
  element.textContent = text;
  element.dataset.state = state;
}

async function loadTasks({ selectFromUrl = false } = {}) {
  const response = await request("/tasks");
  appState.tasks = response.tasks || [];
  renderTaskList();
  if (selectFromUrl && !appState.selectedTaskId) {
    const requested = new URL(location.href).searchParams.get("task");
    const target = appState.tasks.some((item) => item.task_id === requested) ? requested : appState.tasks[0]?.task_id;
    if (target) await selectTask(target);
  }
}

function renderTaskList() {
  clear(ui.taskList);
  if (!appState.tasks.length) {
    const empty = document.createElement("div");
    empty.className = "sidebar-empty";
    empty.textContent = "还没有训练任务";
    ui.taskList.append(empty);
    return;
  }
  appState.tasks.forEach((task) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-item";
    button.setAttribute("aria-current", String(task.task_id === appState.selectedTaskId));
    const title = document.createElement("b");
    title.textContent = task.name;
    const meta = document.createElement("span");
    const state = document.createElement("span");
    const dot = document.createElement("i");
    dot.dataset.status = task.status;
    state.append(dot, document.createTextNode(` ${TASK_STATUS_LABELS[task.status] || task.status}`));
    const time = document.createElement("time");
    time.textContent = formatClock(task.updated_at_utc).slice(0, 5);
    meta.append(state, time);
    button.append(title, meta);
    button.addEventListener("click", () => selectTask(task.task_id));
    ui.taskList.append(button);
  });
}

async function selectTask(taskId) {
  closeRunChannel();
  appState.selectedTaskId = taskId;
  history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  renderTaskList();
  await refreshTask({ resetEvents: true });
}

async function refreshTask({ resetEvents = false } = {}) {
  if (!appState.selectedTaskId) return;
  const response = await request(`/tasks/${encodeURIComponent(appState.selectedTaskId)}`);
  appState.task = response.task;
  renderTask(response.task);
  if (resetEvents) appState.eventIds.clear();
  await loadCurrentRun({ rebuild: resetEvents });
  await loadTasks();
}

function renderTask(task) {
  ui.welcomePanel.hidden = true;
  ui.taskWorkspace.hidden = false;
  ui.pageTitle.textContent = "模型训练工作台";
  ui.taskIdLabel.textContent = task.task_id;
  ui.taskName.textContent = task.name;
  ui.taskGoal.textContent = task.business_goal;
  ui.taskStatus.textContent = TASK_STATUS_LABELS[task.status] || task.status;
  ui.taskStatus.dataset.status = task.status;

  const hasData = Boolean(task.dataset_report);
  const confirmed = Boolean(task.contract_confirmed);
  const running = task.status === "running";
  setStepState(ui.dataStepState, hasData ? "体检完成" : "待导入", hasData ? "done" : "waiting");
  setStepState(ui.contractStepState, confirmed ? "已冻结" : hasData ? "等待确认" : "等待数据", confirmed ? "done" : hasData ? "ready" : "waiting");
  setStepState(ui.runStepState, running ? "后端运行中" : task.status === "completed" ? "本轮完成" : confirmed ? "可以启动" : "等待合同", running ? "running" : task.status === "completed" ? "done" : confirmed ? "ready" : "waiting");
  renderDataset(task);
  renderContract(task, hasData, running);
  ui.startRunButton.disabled = !confirmed || running;
  ui.startRunButton.textContent = task.current_run_id ? "按当前合同复跑" : "开始真实训练";
  const result = task.current_result;
  ui.cancelRunButton.disabled = !result || !ACTIVE_RUN_STATUSES.has(result.status);
  if (!result) resetRunResult();
}

function renderDataset(task) {
  const report = task.dataset_report;
  ui.datasetReport.hidden = !report;
  if (!report) return;
  clear(ui.reportSummary);
  [[report.total_images, "有效图片"], [report.class_count, "类别"], [report.rejected_count, "排除坏图"], [report.duplicate_groups, "重复组"]].forEach(([value, label]) => {
    const cell = document.createElement("div");
    const strong = document.createElement("b"); strong.textContent = value;
    const span = document.createElement("span"); span.textContent = label;
    cell.append(strong, span); ui.reportSummary.append(cell);
  });
  clear(ui.classBars);
  const maximum = Math.max(...Object.values(report.class_counts));
  Object.entries(report.class_counts).forEach(([label, count]) => {
    const row = document.createElement("div"); row.className = "class-row";
    const name = document.createElement("span"); name.textContent = label;
    const track = document.createElement("span"); track.className = "class-track";
    const fill = document.createElement("i"); fill.style.width = `${Math.max(4, count / maximum * 100)}%`; track.append(fill);
    const value = document.createElement("b"); value.textContent = count;
    row.append(name, track, value); ui.classBars.append(row);
  });
  clear(ui.riskList);
  report.risks.forEach((risk) => {
    const item = document.createElement("span"); item.className = "risk-item"; item.dataset.level = risk.level; item.textContent = risk.message; ui.riskList.append(item);
  });
  clear(ui.previewGrid);
  report.previews.forEach((preview) => {
    const card = document.createElement("div"); card.className = "preview-card";
    const image = document.createElement("img"); image.alt = `${preview.label} 数据预览`; image.loading = "lazy";
    image.src = `/tasks/${encodeURIComponent(task.task_id)}/datasets/${encodeURIComponent(report.dataset_id)}/${encodeRelativePath(preview.relative_path)}`;
    const label = document.createElement("span"); label.textContent = preview.label;
    card.append(image, label); ui.previewGrid.append(card);
  });
}

function renderContract(task, enabled, running) {
  const contract = task.contract;
  const controls = [ui.accuracyGate, ui.macroF1Gate, ui.recallGate, ui.imageSize, ui.saveContractButton, ui.confirmAuthorization, ui.confirmLabels, ui.confirmGates];
  controls.forEach((control) => { control.disabled = !enabled || running; });
  if (contract) {
    ui.accuracyGate.value = contract.release_gates.clean_test_accuracy_min;
    ui.macroF1Gate.value = contract.release_gates.clean_test_macro_f1_min;
    ui.recallGate.value = contract.release_gates.clean_test_worst_class_recall_min;
    ui.imageSize.value = String(contract.recipe_options.image_size);
  }
  const confirmations = task.confirmations || {};
  appState.contractDirty = false;
  ui.confirmAuthorization.checked = confirmations.data_authorized === true;
  ui.confirmLabels.checked = confirmations.labels_reviewed === true;
  ui.confirmGates.checked = confirmations.gates_reviewed === true;
  updateConfirmationButton();
}

function updateConfirmationButton() {
  const allowed = appState.task?.dataset_report && appState.task?.status !== "running";
  ui.confirmContractButton.disabled = !allowed || appState.contractDirty || !ui.confirmAuthorization.checked || !ui.confirmLabels.checked || !ui.confirmGates.checked;
}

async function loadCurrentRun({ rebuild = false } = {}) {
  const task = appState.task;
  const runId = task?.current_run_id;
  if (!runId) return;
  const [result, eventResponse] = await Promise.all([
    request(`/runs/${encodeURIComponent(runId)}/result`),
    request(`/runs/${encodeURIComponent(runId)}/events`),
  ]);
  renderRunResult(result);
  if (rebuild || !ui.eventLog.querySelector(".event-row")) rebuildEvents(eventResponse.events || []);
  else (eventResponse.events || []).forEach(appendEvent);
  if (ACTIVE_RUN_STATUSES.has(result.status) && !appState.eventSource) openRunChannel(runId);
  if (!ACTIVE_RUN_STATUSES.has(result.status)) closeRunChannel();
}

function resetRunResult() {
  ui.runDuration.textContent = "尚未运行";
  ui.runIdLabel.textContent = "—";
  ui.gateSummary.textContent = "等待评测";
  clear(ui.eventLog); const empty = document.createElement("li"); empty.className = "empty-row"; empty.textContent = "确认合同后才能启动训练"; ui.eventLog.append(empty);
  renderMetrics(null);
  ui.failureBlock.hidden = true; ui.strategyBlock.hidden = true; ui.artifactBlock.hidden = true;
}

function renderRunResult(result) {
  ui.runIdLabel.textContent = shortId(result.run_id);
  ui.runIdLabel.title = result.run_id;
  const lineage = result.parent_run_id ? ` · 优化子运行，父运行 ${shortId(result.parent_run_id)}` : "";
  ui.runDuration.textContent = result.total_duration_ms ? `本轮真实耗时 ${formatDuration(result.total_duration_ms)}${lineage}` : `${RUN_STATUS_LABELS[result.status] || result.status} · 正在计时${lineage}`;
  ui.cancelRunButton.disabled = !ACTIVE_RUN_STATUSES.has(result.status);
  renderMetrics(result.metrics, result.offline_gates_passed);
  renderFailures(result);
  renderStrategies(result);
  renderArtifacts(result);
}

function renderMetrics(metrics, passed) {
  const clean = metrics?.clean_test || {};
  const latency = metrics?.latency || {};
  const values = [[clean.accuracy, "Accuracy"], [clean.macro_f1, "Macro-F1"], [clean.worst_class_recall, "最差类 Recall"], [latency.p95_ms, "端到端 p95"]];
  clear(ui.metricGrid);
  values.forEach(([value, label], index) => {
    const cell = document.createElement("div");
    const strong = document.createElement("b"); strong.textContent = typeof value === "number" ? index === 3 ? `${value.toFixed(1)} ms` : value.toFixed(4) : "—";
    const span = document.createElement("span"); span.textContent = label; cell.append(strong, span); ui.metricGrid.append(cell);
  });
  ui.gateSummary.textContent = passed === true ? "离线门槛通过" : passed === false ? "存在未通过门槛" : "等待评测";
  clear(ui.candidateTable);
  Object.entries(metrics?.validation_candidates || {}).forEach(([name, values]) => {
    const row = document.createElement("div"); row.className = "candidate-row";
    const title = document.createElement("b"); title.textContent = name;
    const score = document.createElement("span"); score.textContent = `F1 ${Number(values.macro_f1).toFixed(4)}`;
    const time = document.createElement("span"); time.textContent = `${Number(values.fit_seconds).toFixed(3)}s`;
    row.append(title, score, time); ui.candidateTable.append(row);
  });
}

function renderFailures(result) {
  const failures = result.failure_samples || [];
  ui.failureBlock.hidden = !result.metrics;
  clear(ui.failureGrid);
  if (!failures.length) { const empty = document.createElement("div"); empty.className = "empty-row"; empty.textContent = "本轮测试集没有误判样本"; ui.failureGrid.append(empty); return; }
  const datasetId = result.dataset?.dataset_id;
  failures.forEach((failure) => {
    const card = document.createElement("div"); card.className = "failure-card";
    const image = document.createElement("img"); image.alt = `真实 ${failure.actual}，预测 ${failure.predicted}`; image.loading = "lazy";
    image.src = `/tasks/${encodeURIComponent(result.task_id)}/datasets/${encodeURIComponent(datasetId)}/${encodeRelativePath(failure.relative_path)}`;
    const text = document.createElement("span"); text.textContent = `${failure.actual} → ${failure.predicted}`;
    card.append(image, text); ui.failureGrid.append(card);
  });
}

function renderStrategies(result) {
  const strategies = result.strategies || [];
  ui.strategyBlock.hidden = !strategies.length;
  clear(ui.strategyList);
  strategies.forEach((strategy) => {
    const card = document.createElement("article"); card.className = "strategy-card";
    const title = document.createElement("h5"); title.textContent = strategy.title;
    const copy = document.createElement("p"); copy.textContent = strategy.hypothesis;
    const effect = document.createElement("p"); effect.textContent = `预期：${strategy.expected_effect}`;
    const meta = document.createElement("div"); meta.className = "strategy-meta";
    [`成本 ${strategy.estimated_cost}`, `风险 ${strategy.risk}`, strategy.actionable ? "可执行" : "需要补充数据"].forEach((value) => { const tag = document.createElement("span"); tag.textContent = value; meta.append(tag); });
    card.append(title, copy, effect, meta);
    if (strategy.actionable) {
      const button = document.createElement("button"); button.type = "button"; button.className = "button button-secondary"; button.textContent = "审查并批准";
      button.addEventListener("click", () => openApproval(strategy)); card.append(button);
    }
    ui.strategyList.append(card);
  });
}

function renderArtifacts(result) {
  const artifacts = result.artifacts || [];
  ui.artifactBlock.hidden = !artifacts.length;
  clear(ui.artifactList);
  artifacts.forEach((artifact) => {
    const link = document.createElement("a"); link.className = "artifact-link"; link.download = artifact.name;
    link.href = `/runs/${encodeURIComponent(result.run_id)}/artifacts/${encodeURIComponent(artifact.name)}`;
    const name = document.createElement("b"); name.textContent = artifact.name;
    const meta = document.createElement("span"); meta.textContent = `${formatBytes(artifact.bytes)} · ${artifact.sha256.slice(0, 10)}…`;
    link.append(name, meta); ui.artifactList.append(link);
  });
}

function rebuildEvents(events) {
  clear(ui.eventLog); appState.eventIds.clear();
  events.forEach(appendEvent);
  if (!events.length) { const empty = document.createElement("li"); empty.className = "empty-row"; empty.textContent = "运行已创建，等待后端第一条事件"; ui.eventLog.append(empty); }
}

function eventDescription(record) {
  const payload = record.payload || {};
  if (record.type === "run.created") return ["运行对象已持久化", "已分配 run_id"];
  if (record.type === "run.queued") return ["进入本地执行队列", `Recipe: ${payload.recipe}`];
  if (record.type === "run.status_changed") return [`阶段切换：${RUN_STATUS_LABELS[payload.to] || payload.to}`, `${payload.from} → ${payload.to}`];
  if (record.type === "preflight.completed") return ["合同验证完成", `${payload.candidate_count} 个候选模型`];
  if (record.type === "training.candidates_completed") return ["候选训练完成", `${payload.candidates?.length || 0} 个候选产生验证指标`];
  if (record.type === "training.model_selected") return [`选择 ${payload.selected_model}`, `依据 ${payload.selection_metric}`];
  if (record.type === "evaluation.completed") return ["独立测试完成", `Accuracy ${Number(payload.clean_test_accuracy).toFixed(4)}${payload.failure_count == null ? "" : ` · 误判 ${payload.failure_count}`}`];
  if (record.type === "optimization.strategies_proposed") return ["优化建议生成", `${payload.strategy_count} 条建议 · ${payload.actionable_count} 条可批准执行`];
  if (record.type === "artifacts.packaged") return ["制品打包完成", `${payload.artifact_count} 个文件 · ${payload.offline_gates_passed ? "门槛通过" : "存在未通过门槛"}`];
  if (record.type === "run.cancel_requested") return ["取消请求已记录", "将在安全阶段边界生效"];
  if (record.type === "run.failed") return ["运行失败", payload.error || "未知错误"];
  return null;
}

function appendEvent(record) {
  if (appState.eventIds.has(record.event_id)) return;
  appState.eventIds.add(record.event_id);
  const description = eventDescription(record);
  if (!description) return;
  ui.eventLog.querySelector(".empty-row")?.remove();
  const row = document.createElement("li"); row.className = "event-row";
  const time = document.createElement("time"); time.textContent = formatClock(record.timestamp_utc);
  const dot = document.createElement("i");
  const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = description[0]; const detail = document.createElement("small"); detail.textContent = description[1]; copy.append(title, detail);
  const duration = document.createElement("span"); duration.textContent = typeof record.payload?.duration_ms === "number" ? formatDuration(record.payload.duration_ms) : `#${record.seq}`;
  row.append(time, dot, copy, duration); ui.eventLog.append(row); ui.eventLog.scrollTop = ui.eventLog.scrollHeight;
}

function openRunChannel(runId) {
  closeEventSourceOnly();
  const source = new EventSource(`/runs/${encodeURIComponent(runId)}/events/stream?after_seq=0`);
  appState.eventSource = source;
  ["run.created", "run.queued", "run.status_changed", "preflight.completed", "training.candidates_completed", "training.model_selected", "evaluation.completed", "optimization.strategies_proposed", "artifacts.packaged", "run.cancel_requested", "run.cancelled", "run.failed", "run.interrupted"].forEach((type) => {
    source.addEventListener(type, (event) => { appendEvent(JSON.parse(event.data)); scheduleTaskRefresh(); });
  });
  source.onerror = () => scheduleTaskRefresh();
  appState.pollingTimer = window.setInterval(() => refreshTask().catch(handleGlobalError), 1500);
}

function closeEventSourceOnly() { if (appState.eventSource) appState.eventSource.close(); appState.eventSource = null; }
function closeRunChannel() { closeEventSourceOnly(); if (appState.pollingTimer) window.clearInterval(appState.pollingTimer); appState.pollingTimer = null; if (appState.refreshTimer) window.clearTimeout(appState.refreshTimer); appState.refreshTimer = null; }
function scheduleTaskRefresh() { if (appState.refreshTimer) window.clearTimeout(appState.refreshTimer); appState.refreshTimer = window.setTimeout(() => { appState.refreshTimer = null; refreshTask().catch(handleGlobalError); }, 180); }

function openCreateDialog() { ui.createTaskError.hidden = true; ui.createTaskForm.reset(); ui.createTaskDialog.showModal(); window.setTimeout(() => ui.newTaskName.focus(), 0); }
function openApproval(strategy) { appState.pendingStrategy = strategy; ui.approvalTitle.textContent = strategy.title; ui.approvalDescription.textContent = `${strategy.hypothesis} ${strategy.expected_effect}`; ui.approvalDialog.showModal(); }

function handleGlobalError(error) { ui.serviceState.dataset.state = "error"; ui.serviceState.querySelector("b").textContent = "服务请求失败"; if (appState.task) showNotice(error.message, "error"); }

ui.newTaskButton.addEventListener("click", openCreateDialog);
ui.welcomeCreateButton.addEventListener("click", openCreateDialog);
ui.cancelCreateButton.addEventListener("click", () => ui.createTaskDialog.close("cancel"));
ui.refreshTasksButton.addEventListener("click", () => loadTasks().catch(handleGlobalError));
ui.reloadTaskButton.addEventListener("click", () => refreshTask({ resetEvents: true }).catch(handleGlobalError));
ui.createTaskForm.addEventListener("submit", async (event) => {
  event.preventDefault(); ui.createTaskError.hidden = true;
  try {
    const response = await request("/tasks", { method: "POST", json: { name: ui.newTaskName.value, business_goal: ui.newTaskGoal.value } });
    ui.createTaskDialog.close("created"); await loadTasks(); await selectTask(response.task.task_id); showNotice("训练任务草稿已创建。下一步导入自己的图片 ZIP。");
  } catch (error) { ui.createTaskError.hidden = false; ui.createTaskError.textContent = error.message; }
});
ui.datasetFile.addEventListener("change", () => {
  const file = ui.datasetFile.files[0]; ui.uploadDatasetButton.disabled = !file;
  ui.filePickerTitle.textContent = file ? file.name : "选择图片数据集";
  ui.filePickerHint.textContent = file ? `${formatBytes(file.size)} · 点击可重新选择` : "最大 200MB；每类至少 5 张有效图片";
});
ui.uploadDatasetButton.addEventListener("click", async () => {
  const file = ui.datasetFile.files[0]; if (!file || !appState.selectedTaskId) return; hideNotice(); setBusy(ui.uploadDatasetButton, true, "正在体检…");
  try {
    const response = await request(`/tasks/${encodeURIComponent(appState.selectedTaskId)}/dataset`, { method: "POST", headers: { "Content-Type": "application/zip", "X-Filename": encodeURIComponent(file.name) }, body: file });
    appState.task = response.task; renderTask(response.task); await loadTasks(); showNotice(`数据体检完成：${response.task.dataset_report.total_images} 张有效图片，${response.task.dataset_report.class_count} 个类别。`);
  } catch (error) { showNotice(error.message, "error"); } finally { setBusy(ui.uploadDatasetButton, false); ui.uploadDatasetButton.disabled = !ui.datasetFile.files[0]; }
});
ui.contractForm.addEventListener("submit", async (event) => {
  event.preventDefault(); hideNotice(); setBusy(ui.saveContractButton, true, "保存中…");
  try {
    const response = await request(`/tasks/${encodeURIComponent(appState.selectedTaskId)}/contract`, { method: "PATCH", json: { release_gates: { clean_test_accuracy_min: Number(ui.accuracyGate.value), clean_test_macro_f1_min: Number(ui.macroF1Gate.value), clean_test_worst_class_recall_min: Number(ui.recallGate.value) }, recipe_options: { image_size: Number(ui.imageSize.value) } } });
    appState.task = response.task; renderTask(response.task); showNotice("验收门槛已保存。修改合同会清除旧确认，请重新勾选三项确认。你现在还没有启动训练。");
  } catch (error) { showNotice(error.message, "error"); } finally { setBusy(ui.saveContractButton, false); }
});
[ui.confirmAuthorization, ui.confirmLabels, ui.confirmGates].forEach((control) => control.addEventListener("change", updateConfirmationButton));
[ui.accuracyGate, ui.macroF1Gate, ui.recallGate, ui.imageSize].forEach((control) => {
  const markDirty = () => {
    appState.contractDirty = true;
    setStepState(ui.contractStepState, "有未保存修改", "running");
    updateConfirmationButton();
  };
  control.addEventListener("input", markDirty);
  control.addEventListener("change", markDirty);
});
ui.confirmContractButton.addEventListener("click", async () => {
  hideNotice(); setBusy(ui.confirmContractButton, true, "确认中…");
  try {
    const response = await request(`/tasks/${encodeURIComponent(appState.selectedTaskId)}/confirm`, { method: "POST", json: { data_authorized: ui.confirmAuthorization.checked, labels_reviewed: ui.confirmLabels.checked, gates_reviewed: ui.confirmGates.checked } });
    appState.task = response.task; renderTask(response.task); await loadTasks(); showNotice("合同已经冻结。训练仍未开始，点击“开始真实训练”后才会创建运行。 ");
  } catch (error) { showNotice(error.message, "error"); } finally { setBusy(ui.confirmContractButton, false); updateConfirmationButton(); }
});
ui.startRunButton.addEventListener("click", async () => {
  hideNotice(); setBusy(ui.startRunButton, true, "正在创建运行…");
  try {
    const response = await request(`/tasks/${encodeURIComponent(appState.selectedTaskId)}/runs`, { method: "POST" });
    appState.task = response.task; appState.eventIds.clear(); renderTask(response.task); await loadCurrentRun({ rebuild: true }); await loadTasks(); showNotice("运行已在后端创建。下方记录来自真实事件文件，页面刷新不会丢失。 ");
  } catch (error) { showNotice(error.message, "error"); } finally { setBusy(ui.startRunButton, false); if (appState.task) renderTask(appState.task); }
});
ui.cancelRunButton.addEventListener("click", async () => {
  const runId = appState.task?.current_run_id; if (!runId) return;
  try { await request(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }); showNotice("取消请求已记录，将在下一个安全阶段边界生效。 "); await refreshTask(); } catch (error) { showNotice(error.message, "error"); }
});
ui.approvalDialog.addEventListener("close", async () => {
  const strategy = appState.pendingStrategy; appState.pendingStrategy = null;
  if (ui.approvalDialog.returnValue !== "confirm" || !strategy) return;
  const taskId = appState.selectedTaskId; const runId = appState.task?.current_run_id;
  try {
    const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/strategies/${encodeURIComponent(strategy.strategy_id)}/apply`, { method: "POST", json: { approval_confirmed: true } });
    appState.task = response.task; appState.eventIds.clear(); renderTask(response.task); await loadCurrentRun({ rebuild: true }); await loadTasks(); showNotice(`已批准“${strategy.title}”，新的子运行已创建。父运行证据保持不变。`);
  } catch (error) { showNotice(error.message, "error"); }
});
window.addEventListener("beforeunload", closeRunChannel);

loadTasks({ selectFromUrl: true }).catch(handleGlobalError);
