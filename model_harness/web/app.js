const STATUS_LABELS = {
  draft: "任务草稿", awaiting_data: "等待数据", needs_recipe: "等待能力构建",
  data_ready: "数据已就绪", ready: "合同已确认", running: "真实训练中",
  completed: "本轮已完成", failed: "运行异常",
};
const RUNNING_STATUSES = new Set(["created", "queued", "preflight", "training", "evaluating", "proposing", "packaging", "needs_input"]);
const EVENT_LABELS = {
  "run.created": "创建运行", "run.queued": "进入训练队列", "run.status_changed": "运行阶段变化",
  "run.preflight_completed": "训练前检查完成", "preflight.completed": "训练前检查完成",
  "run.candidate_completed": "候选模型完成", "training.candidates_completed": "候选模型比较完成", "training.model_selected": "选定本轮模型",
  "run.evaluation_completed": "独立测试集评测完成", "evaluation.completed": "独立测试集评测完成",
  "run.optimization_proposed": "生成优化建议", "optimization.strategies_proposed": "生成优化建议",
  "run.artifact_created": "生成可追溯产物", "artifacts.packaged": "打包可追溯产物", "run.completed": "训练运行完成", "run.failed": "训练运行失败",
};
const ui = Object.fromEntries([
  "sidebar", "sidebarScrim", "menuButton", "newTaskButton", "refreshButton", "taskList", "taskEyebrow", "taskTitle", "runtimePill",
  "taskPlan", "taskPlanTitle", "taskPlanProgress", "taskPlanSteps", "emptyState", "conversation", "conversationIntro", "messageList",
  "runEventList", "pendingZone", "agentWorking", "cancelAgentButton", "composerForm", "composerNotice", "messageInput", "sendButton",
  "datasetButton", "datasetInput", "inspectorDatasetButton", "inspectorEmpty", "inspectorContent", "taskStatus", "contextTabs",
  "stageList", "capabilityState", "capabilitySummary", "capabilityFacts", "datasetCount", "datasetSummary", "contractCard", "contractState",
  "scaffoldRecipeButton",
  "gateGrid", "confirmations", "confirmContractButton", "startThroughAgentButton", "runEventCount", "inspectorEvents", "resultCard",
  "gateResult", "metricGrid", "runId", "artifactCount", "artifactList", "decisionDialog", "dialogKicker", "dialogTitle", "dialogBody", "dialogActions",
].map((id) => [id, document.getElementById(id)]));
const state = { tasks: [], task: null, selectedTaskId: null, conversation: null, runEvents: [], runtimeReady: false, pollTimer: null, pendingMessage: null, lastRenderKey: "" };

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json !== undefined) { headers["content-type"] = "application/json"; options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) { const error = new Error(typeof value === "object" ? value.detail || JSON.stringify(value) : value); error.status = response.status; throw error; }
  return value;
}
function clear(element) { while (element?.firstChild) element.firstChild.remove(); }
function formatTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function shortId(value) { return value && value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value || "—"; }
function showNotice(message, tone = "error") { ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = tone; ui.composerNotice.textContent = message; }
function hideNotice() { ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }
function setButtonBusy(button, busy, busyText) { if (!button.dataset.label) button.dataset.label = button.textContent; button.disabled = busy; button.textContent = busy ? busyText : button.dataset.label; }

async function loadRuntime() {
  ui.runtimePill.dataset.state = "checking"; ui.runtimePill.querySelector("span").textContent = "正在检查 Agent Runtime";
  try { state.runtimeReady = (await request("/agent/runtime")).available === true; } catch (_error) { state.runtimeReady = false; }
  ui.runtimePill.dataset.state = state.runtimeReady ? "ready" : "error";
  ui.runtimePill.querySelector("span").textContent = state.runtimeReady ? "Agent Runtime 已连接" : "本地训练可用 · Agent 未连接";
}
async function loadTasks({ selectFromUrl = false } = {}) {
  state.tasks = (await request("/tasks")).tasks || []; renderTaskList();
  if (selectFromUrl && !state.selectedTaskId) {
    const requested = new URL(location.href).searchParams.get("task");
    const taskId = state.tasks.some((task) => task.task_id === requested) ? requested : state.tasks[0]?.task_id;
    if (taskId) await selectTask(taskId);
  }
}
function renderTaskList() {
  clear(ui.taskList);
  if (!state.tasks.length) { const empty = document.createElement("div"); empty.className = "task-empty"; empty.textContent = "还没有训练任务。先描述一个真实问题。"; ui.taskList.append(empty); return; }
  state.tasks.forEach((task) => {
    const button = document.createElement("button"); button.type = "button"; button.className = "task-item"; button.setAttribute("aria-current", String(task.task_id === state.selectedTaskId));
    const title = document.createElement("b"); title.textContent = task.name;
    const meta = document.createElement("span"); meta.className = "task-meta";
    const status = document.createElement("span"); const dot = document.createElement("i"); dot.dataset.status = task.status; status.append(dot, document.createTextNode(STATUS_LABELS[task.status] || task.status));
    const time = document.createElement("time"); time.textContent = formatTime(task.updated_at_utc); meta.append(status, time); button.append(title, meta);
    button.addEventListener("click", () => selectTask(task.task_id)); ui.taskList.append(button);
  });
}
function openNewTask() {
  stopPolling(); Object.assign(state, { selectedTaskId: null, task: null, conversation: null, runEvents: [], pendingMessage: null, lastRenderKey: "" });
  history.replaceState(null, "", location.pathname); ui.taskPlan.hidden = true; ui.emptyState.hidden = false; ui.conversation.hidden = true;
  ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.taskEyebrow.textContent = "MODEL TRAINING HARNESS"; ui.taskTitle.textContent = "开始一个训练任务";
  ui.messageInput.placeholder = "描述你想训练的模型，或告诉我下一步怎么做…"; renderTaskList(); closeSidebar(); ui.messageInput.focus();
}
async function selectTask(taskId) {
  stopPolling(); hideNotice(); state.selectedTaskId = taskId; state.lastRenderKey = ""; history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  renderTaskList(); ui.taskPlan.hidden = false; ui.emptyState.hidden = true; ui.conversation.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false; closeSidebar();
  await refreshSelected({ force: true }); state.pollTimer = window.setInterval(() => refreshSelected(), 1400);
}
async function refreshSelected({ force = false } = {}) {
  const taskId = state.selectedTaskId; if (!taskId) return;
  try {
    const response = await request(`/tasks/${encodeURIComponent(taskId)}`); if (state.selectedTaskId !== taskId) return; state.task = response.task;
    if (response.task.current_run_id) { try { state.runEvents = (await request(`/runs/${encodeURIComponent(response.task.current_run_id)}/events`)).events || []; } catch (_error) { state.runEvents = []; } }
    else state.runEvents = [];
    renderTask(response.task);
  } catch (error) { showNotice(error.message); return; }
  try {
    const remoteConversation = (await request(`/tasks/${encodeURIComponent(taskId)}/conversation`)).conversation;
    state.conversation = remoteConversation.session_id ? remoteConversation : null;
    if (state.pendingMessage && remoteConversation.items.some((item) => item.role === "user" && item.text === state.pendingMessage.text)) state.pendingMessage = null;
    if (remoteConversation.session_id) {
      state.runtimeReady = true; ui.runtimePill.dataset.state = "ready"; ui.runtimePill.querySelector("span").textContent = "Agent Runtime 已连接";
    }
  } catch (error) {
    if (error.status === 503) { state.runtimeReady = false; state.conversation = null; ui.runtimePill.dataset.state = "error"; ui.runtimePill.querySelector("span").textContent = "本地训练可用 · Agent 未连接"; }
    else showNotice(error.message);
  }
  renderConversation(force); if (force) await loadTasks();
}

function renderTask(task) {
  ui.taskEyebrow.textContent = task.task_id; ui.taskTitle.textContent = task.name; ui.taskStatus.textContent = STATUS_LABELS[task.status] || task.status; ui.taskStatus.dataset.status = task.status;
  renderPlan(task); renderStages(task); renderCapability(task); renderDataset(task); renderContract(task); renderResult(task); renderRunEvents();
  ui.messageInput.placeholder = task.status === "needs_recipe" ? "该能力尚无 Recipe；可让 Agent 完善构建请求…" : !task.dataset_id ? "继续描述数据，或直接导入 ZIP / CSV…" : "继续询问、启动训练，或分析本轮结果…";
}
function planState(task) { if (task.status === "needs_recipe" || !task.dataset_id) return 1; if (!task.contract_confirmed) return 2; if (!task.current_run_id) return 3; if (task.current_result?.status !== "completed") return 4; return 5; }
function renderPlan(task) {
  const current = planState(task); const labels = ["识别能力", "准备数据", "冻结合同", "训练评测", "交付优化"];
  ui.taskPlanTitle.textContent = task.status === "needs_recipe" ? "当前能力需要构建 Recipe" : labels[Math.min(current - 1, 4)]; ui.taskPlanProgress.textContent = `${current} / 5`; clear(ui.taskPlanSteps);
  labels.forEach((label, index) => { const item = document.createElement("li"); if (index + 1 < current || current === 5) item.className = "done"; else if (index + 1 === current) item.className = "active"; const mark = document.createElement("i"); mark.textContent = index + 1 < current || current === 5 ? "✓" : String(index + 1); item.append(mark, document.createTextNode(label)); ui.taskPlanSteps.append(item); });
}
function datasetDetail(task) {
  const report = task.dataset_report; if (!report) return ["等待数据集", "尚未执行数据体检"];
  if (typeof report.total_images === "number") return [`${report.total_images} 张图片`, `${report.class_count} 类 · 排除 ${report.rejected_count || 0} 张`];
  return [`${report.row_count || 0} 行数据`, `${report.feature_count || Math.max((report.column_count || 1) - 1, 0)} 个特征 · 目标 ${report.target_column || "—"}`];
}
function renderStages(task) {
  const [dataCount, dataSummary] = datasetDetail(task); const result = task.current_result; const hasData = Boolean(task.dataset_report); const confirmed = task.contract_confirmed === true; const finished = result?.status === "completed"; const blocked = task.status === "needs_recipe";
  const stages = [
    ["定义任务", blocked ? "能力缺口已转为构建请求" : `Recipe：${task.recipe_id || "待匹配"}`, blocked ? "active" : "done"],
    ["检查数据", hasData ? `${dataCount} · ${dataSummary}` : blocked ? "等待 Recipe / Adapter" : "等待导入", hasData ? "done" : blocked ? "waiting" : "active"],
    ["确认合同", confirmed ? "授权、标签/目标、门槛已确认" : "等待人工确认", confirmed ? "done" : hasData ? "active" : "waiting"],
    ["训练评测", finished ? "真实训练与独立评测完成" : result ? `运行状态：${result.status}` : "尚未启动", finished ? "done" : result || confirmed ? "active" : "waiting"],
    ["优化交付", finished ? (result.offline_gates_passed ? "验收通过，可下载制品" : "查看错误样本与下一轮") : "等待评测结果", finished ? "active" : "waiting"],
  ];
  clear(ui.stageList); stages.forEach(([title, detail, stageState], index) => {
    const item = document.createElement("li"); item.className = "stage-item"; item.dataset.state = stageState;
    const mark = document.createElement("span"); mark.className = "stage-mark"; mark.textContent = stageState === "done" ? "✓" : String(index + 1);
    const copy = document.createElement("span"); copy.className = "stage-copy"; const b = document.createElement("b"); b.textContent = title; const small = document.createElement("span"); small.textContent = detail; copy.append(b, small);
    const label = document.createElement("span"); label.className = "stage-state"; label.textContent = stageState === "done" ? "完成" : stageState === "active" ? "当前" : "待办"; item.append(mark, copy, label); ui.stageList.append(item);
  });
}
function addFact(label, value) { const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label; const selected = document.createElement("b"); selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); ui.capabilityFacts.append(row); }
function renderCapability(task) {
  const request = task.capability_request || {}; const build = task.recipe_request; clear(ui.capabilityFacts);
  if (task.capability_status === "matched") { ui.capabilityState.textContent = "已匹配"; ui.capabilitySummary.textContent = `已选择 ${task.recipe_id}；该 Recipe 将接入统一的数据、合同、运行、评测和产物闭环。`; }
  else if (task.capability_status === "needs_recipe") { ui.capabilityState.textContent = "待构建"; ui.capabilitySummary.textContent = "现有 Recipe 无法覆盖该能力。系统已持久化构建请求，并且不会伪造训练进度。"; }
  else { ui.capabilityState.textContent = "待识别"; ui.capabilitySummary.textContent = "继续描述输入数据、预测目标和运行限制，以匹配或构建 Recipe。"; }
  addFact("数据模态", request.modality); addFact("任务目标", request.objective); addFact("输出类型", request.target_kind); addFact("Recipe", task.recipe_id); addFact("Data Adapter", task.data_adapter_id || request.data_adapter); if (build) addFact("构建请求", build.request_id || build.recipe_request_id);
  ui.scaffoldRecipeButton.hidden = task.capability_status !== "needs_recipe";
  ui.scaffoldRecipeButton.textContent = build?.status === "scaffold_ready" ? "重新生成 Code Agent 构建包" : "生成 Code Agent 构建包";
}
function renderDataset(task) {
  const report = task.dataset_report; const [count, summary] = datasetDetail(task); ui.datasetCount.textContent = report ? count : "未导入";
  ui.datasetSummary.textContent = report ? `${summary} · ${report.risks?.[0]?.message || "后端体检完成"}` : "导入图片类别 ZIP 或 CSV；其他格式通过 Data Adapter 插件扩展。";
  ui.inspectorDatasetButton.textContent = report ? "替换并重新体检" : "导入数据集"; const blocked = task.status === "running" || task.status === "needs_recipe"; ui.datasetButton.disabled = blocked; ui.inspectorDatasetButton.disabled = blocked;
}
function gateEntries(gates) { return "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates ? [[gates.clean_test_mae_max, "MAE 上限"], [gates.clean_test_rmse_max, "RMSE 上限"], [gates.clean_test_r2_min, "R² 下限"]] : [[gates.clean_test_accuracy_min, "Accuracy"], [gates.clean_test_macro_f1_min, "Macro-F1"], [gates.clean_test_worst_class_recall_min, "最差类 Recall"]]; }
function renderContract(task) {
  const contract = task.contract; ui.contractCard.hidden = !contract; if (!contract) return; ui.contractState.textContent = task.contract_confirmed ? "已冻结" : "待确认"; clear(ui.gateGrid);
  gateEntries(contract.release_gates || {}).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? value.toFixed(2) : "—"; const span = document.createElement("span"); span.textContent = label; cell.append(b, span); ui.gateGrid.append(cell); });
  const confirmed = task.contract_confirmed === true; ui.confirmations.hidden = confirmed; ui.startThroughAgentButton.hidden = !confirmed || task.status === "running";
  ui.startThroughAgentButton.textContent = task.current_run_id ? "分析结果或开启下一轮" : state.runtimeReady ? "让 Agent 启动真实训练" : "批准并启动真实训练";
  ui.confirmations.querySelectorAll("input").forEach((input) => { input.disabled = task.status === "running"; input.checked = task.confirmations?.[input.dataset.confirm] === true; });
}
function metricEntries(result) { const clean = result?.metrics?.clean_test || {}; return "mae" in clean || "rmse" in clean || "r2" in clean ? [[clean.mae, "MAE"], [clean.rmse, "RMSE"], [clean.r2, "R²"]] : [[clean.accuracy, "Accuracy"], [clean.macro_f1, "Macro-F1"], [clean.worst_class_recall, "最差类 Recall"]]; }
function renderResult(task) {
  const result = task.current_result; ui.resultCard.hidden = !result; clear(ui.artifactList); const artifacts = result?.artifacts || []; ui.artifactCount.textContent = String(artifacts.length);
  artifacts.forEach((artifact) => { const link = document.createElement("a"); link.href = `/runs/${encodeURIComponent(result.run_id)}/artifacts/${encodeURIComponent(artifact.name)}`; link.download = artifact.name; const name = document.createElement("span"); name.textContent = artifact.name; const action = document.createElement("span"); action.textContent = "下载"; link.append(name, action); ui.artifactList.append(link); });
  if (!result) return; const running = RUNNING_STATUSES.has(result.status); ui.gateResult.textContent = running ? "运行中" : result.offline_gates_passed === true ? "验收通过" : result.status === "completed" ? "存在未通过门槛" : "运行异常";
  ui.runId.textContent = shortId(result.run_id); ui.runId.title = result.run_id; clear(ui.metricGrid); metricEntries(result).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? value.toFixed(3) : "—"; const span = document.createElement("span"); span.textContent = label; cell.append(b, span); ui.metricGrid.append(cell); });
}

function eventDetail(event) {
  const payload = event.payload || {};
  if (event.type === "run.status_changed") return `${payload.from || "—"} → ${payload.to || event.stage}`;
  if (event.type === "run.candidate_completed") { const score = payload.accuracy ?? payload.mae; return `${payload.candidate || payload.name || "候选模型"}${typeof score === "number" ? ` · ${score.toFixed(4)}` : ""}`; }
  if (event.type === "run.evaluation_completed") return `独立测试集 · ${Object.entries(payload).filter(([, value]) => typeof value === "number").slice(0, 3).map(([key, value]) => `${key} ${value.toFixed(3)}`).join(" · ")}`;
  if (event.type === "run.artifact_created") return payload.name || "制品已写入";
  return event.stage || event.type;
}
function renderRunEvents() {
  const events = state.runEvents || []; ui.runEventCount.textContent = String(events.length); clear(ui.runEventList); clear(ui.inspectorEvents);
  if (!events.length) { const empty = document.createElement("p"); empty.textContent = "尚无运行事件；训练启动后只呈现后端真实事件。"; ui.inspectorEvents.append(empty); return; }
  events.forEach((event) => {
    const card = document.createElement("article"); card.className = "run-event"; const terminal = event.type === "run.completed" || event.type === "run.failed"; card.dataset.state = event.type === "run.failed" ? "failed" : terminal ? "completed" : "running";
    const icon = document.createElement("i"); icon.textContent = event.type === "run.failed" ? "!" : terminal ? "✓" : event.seq;
    const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = EVENT_LABELS[event.type] || event.type; const detail = document.createElement("small"); detail.textContent = eventDetail(event); copy.append(title, detail);
    const time = document.createElement("em"); time.textContent = formatTime(event.timestamp_utc); card.append(icon, copy, time); ui.runEventList.append(card);
    const row = document.createElement("div"); const seq = document.createElement("i"); seq.textContent = event.seq; const side = document.createElement("span"); const name = document.createElement("b"); name.textContent = EVENT_LABELS[event.type] || event.type; const small = document.createElement("small"); small.textContent = eventDetail(event); side.append(name, small); row.append(seq, side); ui.inspectorEvents.append(row);
  });
}
function localConversation(task) {
  if (!task) return { items: [], pending: [], running: false };
  let statusText;
  if (task.status === "needs_recipe") statusText = `当前能力尚无可执行 Recipe。我已保存 Recipe Build Request（${task.recipe_request?.recipe_request_id || "待分配"}），在 Recipe 与 Data Adapter 验证通过前不会生成训练运行。`;
  else if (!task.dataset_id) statusText = `已匹配 Recipe：${task.recipe_id}。下一步请导入与 ${task.data_adapter_id || task.capability_request?.data_adapter || "该能力"} 对应的数据。`;
  else if (!task.contract_confirmed) statusText = "后端数据体检已完成。请检查右侧的数据摘要与验收门槛，并明确确认数据授权、标签或目标字段、验收门槛。";
  else if (!task.current_run_id) statusText = "训练合同已冻结。你可以批准并启动真实训练；启动后这里会逐条显示后端运行事件。";
  else if (task.status === "running") statusText = `真实运行 ${shortId(task.current_run_id)} 正在执行；当前已收到 ${state.runEvents.length} 条后端事件。`;
  else statusText = `运行 ${shortId(task.current_run_id)} 已${task.status === "completed" ? "完成" : "结束"}。评测指标、门槛状态和可下载产物来自后端运行目录。`;
  return { items: [{ kind: "message", role: "user", text: task.business_goal, time: task.created_at_utc }, { kind: "message", role: "assistant", text: statusText, time: task.updated_at_utc }], pending: [], running: false };
}
function renderConversation(force = false) {
  const conversation = state.conversation || localConversation(state.task);
  const renderKey = JSON.stringify({ items: conversation.items?.map((item) => [item.seq, item.status, item.text]), pending: conversation.pending?.map((item) => item.rpc_id), running: conversation.running, optimistic: state.pendingMessage?.text, taskStatus: state.task?.status, eventCount: state.runEvents.length });
  if (!force && renderKey === state.lastRenderKey) return; state.lastRenderKey = renderKey;
  const nearBottom = ui.conversation.scrollHeight - ui.conversation.scrollTop - ui.conversation.clientHeight < 120; clear(ui.messageList);
  const items = [...(conversation.items || [])]; if (state.pendingMessage && !items.some((item) => item.role === "user" && item.text === state.pendingMessage.text)) items.push({ kind: "message", role: "user", text: state.pendingMessage.text, time: state.pendingMessage.time, optimistic: true });
  items.forEach((item) => item.kind === "tool" ? renderTool(item) : renderMessage(item)); ui.conversationIntro.hidden = items.length > 0; renderPending(conversation.pending || []); ui.agentWorking.hidden = !conversation.running && !state.pendingMessage;
  if (force || nearBottom) requestAnimationFrame(() => { ui.conversation.scrollTop = ui.conversation.scrollHeight; });
}
function renderMessage(item) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = item.role; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = item.role === "user" ? "你" : "MH";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = item.role === "user" ? "你" : state.runtimeReady ? "训练 Agent" : "Model Harness"; const time = document.createElement("time"); time.textContent = item.optimistic ? "正在提交" : formatTime(item.time); meta.append(author, time);
  const copy = document.createElement("p"); copy.className = "message-copy"; copy.textContent = item.text; body.append(meta, copy); row.append(avatar, body); ui.messageList.append(row);
}
function renderTool(item) {
  const card = document.createElement("article"); card.className = "tool-card"; card.dataset.status = item.status; const icon = document.createElement("span"); icon.className = "tool-icon"; icon.textContent = item.status === "completed" ? "✓" : item.status === "failed" ? "!" : "↻";
  const copy = document.createElement("span"); copy.className = "tool-copy"; const title = document.createElement("b"); title.textContent = item.label; const detail = document.createElement("span"); detail.textContent = item.status === "completed" ? "真实工具调用已完成" : item.status === "failed" ? "工具返回失败" : "正在调用训练工具"; copy.append(title, detail);
  const status = document.createElement("span"); status.className = "tool-status"; status.textContent = formatTime(item.time); card.append(icon, copy, status); ui.messageList.append(card);
}
function renderPending(pending) {
  clear(ui.pendingZone); pending.forEach((item) => {
    const card = document.createElement("article"); card.className = "decision-card"; const kicker = document.createElement("span"); kicker.textContent = item.kind === "approval" ? "需要你的批准" : "Agent 正在等你的回答"; const title = document.createElement("h3"); title.textContent = item.kind === "approval" ? item.title : item.questions?.[0]?.header || "补充训练信息"; const copy = document.createElement("p"); copy.textContent = item.kind === "approval" ? item.reason : item.questions?.[0]?.question || "请回答 Agent 提出的问题。"; const actions = document.createElement("div"); actions.className = "decision-actions";
    if (item.kind === "approval") { const allow = document.createElement("button"); allow.type = "button"; allow.textContent = "仅本次允许"; const reject = document.createElement("button"); reject.type = "button"; reject.textContent = "拒绝"; allow.addEventListener("click", () => answerApproval(item, "allowed-once", allow)); reject.addEventListener("click", () => answerApproval(item, "rejected", reject)); actions.append(allow, reject); }
    else { const answer = document.createElement("button"); answer.type = "button"; answer.textContent = "回答问题"; answer.addEventListener("click", () => openQuestionDialog(item)); actions.append(answer); }
    card.append(kicker, title, copy, actions); ui.pendingZone.append(card);
  });
}
function inferCapability(text) {
  const value = text.toLowerCase();
  if (/语音|声音|录音|关键词|audio|speech/.test(value)) return { modality: "audio", objective: /转写|识别文字|asr/.test(value) ? "transcription" : "classification", target_kind: "multiclass", tags: ["speech", "user-data"] };
  if (/时序|时间序列|销量预测|需求预测|forecast/.test(value)) return { modality: "time-series", objective: "forecasting", target_kind: "numeric", tags: ["forecasting", "user-data"] };
  if (/目标检测|缺陷检测|物体检测|框出|bounding/.test(value)) return { modality: "image", objective: "detection", target_kind: "bounding-box", tags: ["detection", "industrial", "user-data"] };
  if (/csv|表格|回归|评分|价格预测|质量预测|数值预测/.test(value)) return { modality: "tabular", objective: "regression", target_kind: "numeric", data_adapter: "tabular-csv", tags: ["regression", "user-data"] };
  if (/图片|图像|照片|零件|数字|ocr|分类|识别/.test(value)) return { modality: "image", objective: "classification", target_kind: "multiclass", data_adapter: "image-folder-zip", tags: ["classification", "user-data"] };
  return { modality: "custom", objective: "custom", target_kind: "custom", tags: ["user-data"] };
}
async function submitMessage(message) {
  const text = message.trim(); if (!text) return; hideNotice(); setButtonBusy(ui.sendButton, true, "…");
  try {
    if (!state.selectedTaskId) {
      const created = await request("/tasks", { method: "POST", json: { name: deriveTaskName(text), business_goal: text, capability_request: inferCapability(text) } }); state.tasks.unshift(created.task); ui.messageInput.value = ""; resizeComposer(); await selectTask(created.task.task_id);
      if (!state.runtimeReady) { showNotice("训练任务已经真实创建。Agent Runtime 未连接，但数据导入、合同确认与本地训练仍可继续。", "ok"); return; }
    }
    if (!state.runtimeReady) { showNotice("这条自由对话需要 Agent Runtime；右侧的数据、合同与训练操作仍可直接使用。任务事实没有被伪造。"); return; }
    state.pendingMessage = { text, time: Date.now() }; renderConversation(true); await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/messages`, { method: "POST", json: { message: text } }); ui.messageInput.value = ""; resizeComposer(); window.setTimeout(() => refreshSelected({ force: true }), 250);
  } catch (error) { state.pendingMessage = null; renderConversation(true); showNotice(`${error.message}。任务事实不会被伪造。`); }
  finally { setButtonBusy(ui.sendButton, false, ""); }
}
function deriveTaskName(message) { const cleaned = message.replace(/^(我想|我要|请帮我|帮我)?(用[^，。]{0,12})?(训练|做|构建)(一个|个)?/u, "").replace(/[。！？!?,，]/g, " ").trim(); return (cleaned.split(/\s+/).slice(0, 2).join(" ") || "新的模型训练任务").slice(0, 32); }
function openSimpleDialog({ kicker, title, body, allowLabel, onAllow }) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = kicker; ui.dialogTitle.textContent = title; const copy = document.createElement("p"); copy.textContent = body; ui.dialogBody.append(copy);
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => ui.decisionDialog.close());
  const allow = document.createElement("button"); allow.type = "button"; allow.className = "allow"; allow.textContent = allowLabel; allow.addEventListener("click", async () => { setButtonBusy(allow, true, "执行中"); try { await onAllow(); ui.decisionDialog.close(); } catch (error) { showNotice(error.message); } finally { setButtonBusy(allow, false, ""); } });
  ui.dialogActions.append(cancel, allow); ui.decisionDialog.showModal();
}
function startRunDirect() {
  openSimpleDialog({ kicker: "启动真实计算", title: "批准本次训练运行？", body: `系统将使用已冻结合同启动 ${state.task?.recipe_id || "当前 Recipe"}，并把事件、指标和模型产物写入本地运行目录。`, allowLabel: "批准并启动", onAllow: async () => { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/runs`, { method: "POST" }); showNotice("真实训练已经进入后端队列，运行事件会持续刷新。", "ok"); activateContext("run"); await refreshSelected({ force: true }); } });
}
async function answerApproval(item, outcome, button) { setButtonBusy(button, true, "提交中"); try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/approvals/${encodeURIComponent(item.rpc_id)}`, { method: "POST", json: { outcome } }); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(button, false, ""); } }
function openQuestionDialog(item) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "Agent 正在等待"; ui.dialogTitle.textContent = "补充训练信息"; const fields = [];
  (item.questions || []).forEach((question, index) => { const block = document.createElement("section"); block.className = "question-block"; const title = document.createElement("b"); title.textContent = question.question; block.append(title); const options = document.createElement("div"); options.className = "question-options";
    if (question.options?.length) { question.options.forEach((option, optionIndex) => { const label = document.createElement("label"); const input = document.createElement("input"); input.type = question.multiSelect ? "checkbox" : "radio"; input.name = `question-${index}`; input.value = option.label; if (!question.multiSelect && optionIndex === 0) input.checked = true; const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = option.label; copy.append(name); if (option.description) { const small = document.createElement("small"); small.textContent = option.description; copy.append(small); } label.append(input, copy); options.append(label); }); block.append(options); fields.push({ question, options }); }
    else { const input = document.createElement("input"); input.className = "question-custom"; input.placeholder = "输入你的回答"; block.append(input); fields.push({ question, input }); } ui.dialogBody.append(block);
  });
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => ui.decisionDialog.close()); const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = "提交回答";
  submit.addEventListener("click", async () => { const answers = fields.map(({ question, options, input }) => ({ id: question.id, selected: options ? [...options.querySelectorAll("input:checked")].map((field) => field.value) : [], ...(input?.value.trim() ? { custom: input.value.trim() } : {}) })); if (answers.some((answer) => !answer.selected.length && !answer.custom)) { showNotice("请先回答 Agent 的问题"); return; } setButtonBusy(submit, true, "提交中"); try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/questions/${encodeURIComponent(item.rpc_id)}`, { method: "POST", json: { answers } }); ui.decisionDialog.close(); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(submit, false, ""); } });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal();
}

function askCsvOptions(file) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "CSV 数据合同"; ui.dialogTitle.textContent = "指定预测目标字段";
  const fields = [["目标字段", "例如 quality", true], ["忽略字段", "可选，多个字段用逗号分隔", false], ["分隔符", "留空自动识别；也可输入 ; 或 ,", false]].map(([label, placeholder, required]) => {
    const block = document.createElement("section"); block.className = "question-block"; const title = document.createElement("b"); title.textContent = label; const input = document.createElement("input"); input.className = "question-custom"; input.placeholder = placeholder; input.required = required; block.append(title, input); ui.dialogBody.append(block); return input;
  });
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => { ui.decisionDialog.close(); ui.datasetInput.value = ""; });
  const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = "导入并体检"; submit.addEventListener("click", async () => { if (!fields[0].value.trim()) { showNotice("CSV 回归任务必须指定目标字段。"); return; } ui.decisionDialog.close(); await uploadDataset(file, { targetColumn: fields[0].value.trim(), ignoredColumns: fields[1].value.trim(), delimiter: fields[2].value }); });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal();
}
async function uploadDataset(file, options = {}) {
  if (!state.selectedTaskId) { showNotice("先发送一条消息创建训练任务，再导入数据集。"); return; }
  if (state.task?.status === "needs_recipe") { showNotice("当前能力还没有可执行 Recipe。请先完成并注册 Recipe / Data Adapter。"); return; }
  const lower = file?.name.toLowerCase() || ""; if (!lower.endsWith(".zip") && !lower.endsWith(".csv")) { showNotice("当前内置 Data Adapter 支持图片 ZIP 和 CSV；其他格式需要插件。"); return; }
  if (lower.endsWith(".csv") && !options.targetColumn) { askCsvOptions(file); return; }
  hideNotice(); setButtonBusy(ui.datasetButton, true, "体检中");
  const headers = { "content-type": lower.endsWith(".csv") ? "text/csv" : "application/zip", "x-filename": encodeURIComponent(file.name) };
  if (options.targetColumn) headers["x-target-column"] = encodeURIComponent(options.targetColumn);
  if (options.ignoredColumns) headers["x-ignored-columns"] = options.ignoredColumns.split(",").map((value) => encodeURIComponent(value.trim())).filter(Boolean).join(",");
  if (options.delimiter) headers["x-delimiter"] = encodeURIComponent(options.delimiter);
  try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/dataset`, { method: "POST", body: file, headers }); showNotice("后端已真实导入数据并完成体检。", "ok"); activateContext("data"); await refreshSelected({ force: true }); if (state.runtimeReady) await submitMessage(`我已通过产品界面导入数据集 ${file.name}。请读取真实体检结果并解释风险。`); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.datasetButton, false, ""); ui.datasetInput.value = ""; }
}
async function confirmContract() {
  const fields = [...ui.confirmations.querySelectorAll("input")]; if (fields.some((field) => !field.checked)) { showNotice("请明确勾选数据授权、标签/目标字段和验收门槛三项确认。"); return; }
  setButtonBusy(ui.confirmContractButton, true, "确认中");
  try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/confirm`, { method: "POST", json: Object.fromEntries(fields.map((field) => [field.dataset.confirm, true])) }); showNotice("训练合同已经真实冻结。", "ok"); await refreshSelected({ force: true }); if (state.runtimeReady) await submitMessage("我已明确确认数据授权、标签或目标字段和离线验收门槛。请读取最新合同。"); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.confirmContractButton, false, ""); }
}
function activateContext(name) { document.querySelectorAll("[data-context]").forEach((button) => button.classList.toggle("active", button.dataset.context === name)); document.querySelectorAll("[data-context-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.contextPanel === name)); }
function openSidebar() { ui.sidebar.dataset.open = "true"; ui.sidebarScrim.hidden = false; }
function closeSidebar() { ui.sidebar.dataset.open = "false"; ui.sidebarScrim.hidden = true; }
function stopPolling() { if (state.pollTimer) window.clearInterval(state.pollTimer); state.pollTimer = null; }
function resizeComposer() { ui.messageInput.style.height = "auto"; ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 140)}px`; }

ui.composerForm.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(ui.messageInput.value); });
ui.messageInput.addEventListener("input", resizeComposer);
ui.messageInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composerForm.requestSubmit(); } });
ui.newTaskButton.addEventListener("click", openNewTask); ui.refreshButton.addEventListener("click", () => state.selectedTaskId ? refreshSelected({ force: true }) : loadTasks());
ui.menuButton.addEventListener("click", openSidebar); ui.sidebarScrim.addEventListener("click", closeSidebar);
ui.datasetButton.addEventListener("click", () => state.selectedTaskId ? ui.datasetInput.click() : showNotice("先用一句话创建训练任务，再导入数据。")); ui.inspectorDatasetButton.addEventListener("click", () => ui.datasetInput.click()); ui.datasetInput.addEventListener("change", () => uploadDataset(ui.datasetInput.files?.[0]));
ui.confirmContractButton.addEventListener("click", confirmContract);
ui.scaffoldRecipeButton.addEventListener("click", async () => {
  setButtonBusy(ui.scaffoldRecipeButton, true, "正在生成");
  try {
    const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/recipe/scaffold`, { method: "POST" });
    const link = document.createElement("a"); link.href = result.scaffold.download_url; link.download = result.scaffold.archive_name; document.body.append(link); link.click(); link.remove();
    showNotice("已生成可审查的 Code Agent 构建包。该脚手架不会被自动执行，完成实现和测试后再注册。", "ok"); await refreshSelected({ force: true });
  } catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.scaffoldRecipeButton, false, ""); }
});
ui.startThroughAgentButton.addEventListener("click", () => {
  if (state.task?.current_run_id && state.task.status !== "ready") { if (state.runtimeReady) submitMessage("请读取当前运行的真实结果，解释失败样本和下一轮优化。"); else showNotice("连接 Agent Runtime 后可对话分析；指标和产物仍可在右侧查看。"); }
  else if (state.runtimeReady) submitMessage("请基于已确认的训练合同启动真实训练。执行关键操作前向我请求批准。"); else startRunDirect();
});
ui.cancelAgentButton.addEventListener("click", async () => { try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/cancel`, { method: "POST" }); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } });
ui.contextTabs.addEventListener("click", (event) => { const button = event.target.closest("[data-context]"); if (button) activateContext(button.dataset.context); });
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { ui.messageInput.value = button.dataset.prompt; resizeComposer(); ui.messageInput.focus(); }));

async function boot() { await Promise.all([loadRuntime(), loadTasks({ selectFromUrl: true })]); resizeComposer(); }
boot().catch((error) => showNotice(`页面初始化失败：${error.message}`));
