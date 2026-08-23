const STATUS_LABELS = {
  draft: "任务草稿", needs_clarification: "等待澄清", needs_confirmation: "等待确认",
  awaiting_data: "等待数据", needs_recipe: "等待能力构建",
  data_ready: "数据已就绪", ready: "合同已确认", running: "真实训练中",
  completed: "本轮已完成", failed: "运行异常", cancelled: "训练已取消", interrupted: "训练已中断",
};
const RUNNING_STATUSES = new Set(["created", "queued", "preflight", "training", "evaluating", "proposing", "packaging", "needs_input"]);
const TERMINAL_RETRY_STATUSES = new Set(["failed", "cancelled", "interrupted"]);
const EVENT_LABELS = {
  "run.created": "创建运行", "run.queued": "进入训练队列", "run.status_changed": "运行阶段变化",
  "run.preflight_completed": "训练前检查完成", "preflight.completed": "训练前检查完成",
  "run.candidate_completed": "候选模型完成", "training.candidates_completed": "候选模型比较完成", "training.model_selected": "选定本轮模型",
  "run.evaluation_completed": "独立测试集评测完成", "evaluation.completed": "独立测试集评测完成",
  "run.optimization_proposed": "生成优化建议", "optimization.strategies_proposed": "生成优化建议",
  "run.artifact_created": "生成可追溯产物", "artifacts.packaged": "打包可追溯产物", "run.completed": "训练运行完成", "run.failed": "训练运行失败",
  "run.cancel_requested": "已请求取消训练", "run.cancelled": "训练已取消", "run.interrupted": "训练已中断",
};
const ui = Object.fromEntries([
  "sidebar", "sidebarScrim", "menuButton", "newTaskButton", "refreshButton", "taskList", "taskEyebrow", "taskTitle", "runtimePill",
  "taskPlan", "taskPlanTitle", "taskPlanProgress", "emptyState", "conversation", "conversationIntro", "messageList",
  "runEventList", "pendingZone", "agentWorking", "cancelAgentButton", "composerForm", "composerNotice", "messageInput", "sendButton",
  "datasetButton", "datasetInput", "recipeSampleInput", "inspectorDatasetButton", "inspectorEmpty", "inspectorContent", "taskStatus", "contextTabs",
  "stageList", "capabilityState", "capabilitySummary", "capabilityFacts", "datasetCount", "datasetSummary", "contractCard", "contractState",
  "scaffoldRecipeButton",
  "gateGrid", "confirmations", "confirmContractButton", "startThroughAgentButton", "runEventCount", "inspectorEvents", "resultCard",
  "gateResult", "metricGrid", "runId", "artifactCount", "artifactList", "decisionDialog", "dialogKicker", "dialogTitle", "dialogBody", "dialogActions",
  "taskControlPanel", "nextActionCard", "currentStageLabel", "currentStageState", "nextActionLabel", "nextActionDescription", "nextActionButton",
  "taskBlocker", "taskBlockerTitle", "taskBlockerDescription", "taskBlockerActionButton", "taskSpecCard", "taskSpecHeading", "taskSpecStatus",
  "taskSpecVersion", "taskSpecSummary", "taskSpecInput", "taskSpecObjective", "taskSpecOutput", "taskSpecConstraints", "taskSpecClarification",
  "taskSpecClarificationTitle", "taskSpecClarificationDescription", "editTaskSpecButton", "confirmTaskSpecButton", "inspector", "inspectorSheetTitle",
  "closeInspectorButton", "cancelRunButton", "retryRunButton", "runControlStatus", "runControlLabel", "runControlDescription", "mobileViewNav", "mobileConversationButton",
  "mobileContextButton", "mobileResultButton", "inspectorScrim", "modelAssetCard", "modelAssetState", "modelAssetSummary", "modelAssetBinding",
  "modelAssetFacts", "modelAssetVerifyStatus", "modelAssetVerifyButton", "hfDiscovery", "hfCapabilityStatus", "hfSearchForm", "hfSearchInput",
  "hfTokenInput", "hfSearchButton", "hfSearchResults", "hfModelCard", "hfModelRepo", "hfCompatibilityState", "hfModelCommit",
  "hfModelLicense", "hfCompatibilityChecks", "hfCompatibilityReasons", "hfModelFiles", "hfAttachButton", "refreshEvaluationButton",
  "evaluationEvidenceCard", "evaluationConclusion", "evidenceDimensions", "evaluationReasons", "candidateComparisonCard", "candidateCount",
  "candidatePolicy", "candidateList", "failureSampleCard", "failureSampleCount", "failureSampleList", "runHistoryCard", "runHistoryCount",
  "runHistoryList", "sampleTrialCard", "sampleTrialState", "sampleTrialSummary", "sampleTrialInput", "sampleJsonField", "sampleTrialJson",
  "sampleTrialSelectButton", "sampleTrialRunButton", "sampleInferenceList", "artifactBundleCard", "artifactBundleState", "artifactBundleSummary",
  "buildArtifactBundleButton", "artifactBundleList",
].map((id) => [id, document.getElementById(id)]));
const state = {
  tasks: [], task: null, selectedTaskId: null, conversation: null, runEvents: [], runtimeReady: false, pollTimer: null,
  pendingMessage: null, lastRenderKey: "", selectionToken: 0, hfCapability: null, hfModels: [], hfCard: null,
  modelAssetVerification: null, evidenceRunId: null, evidenceLoaded: false, evaluationReport: null, sampleInferences: [], artifactBundles: [],
  refreshInFlight: false, refreshSeq: 0,
  evidenceErrors: {},
};
const DraftStore = window.ModelHarnessDraftStore;
const STAGE_LABELS = {
  task_understanding: "确认任务理解", capability_resolution: "解决能力缺口", data_preparation: "准备训练数据",
  contract_review: "审阅训练合同", ready_to_run: "准备启动训练", evaluation: "审阅评测结果", run_recovery: "处理运行异常",
};
const LIFECYCLE_STEPS = ["定义任务", "检查数据", "确认合同", "训练评测", "优化交付"];
const SPEC_FAMILIES = [
  { family: "image_classification", label: "整张图片分类", output: "为每张图片输出一个类别" },
  { family: "ocr", label: "OCR 文字识别", output: "输出图片中的文字内容" },
  { family: "object_detection", label: "目标检测与定位", output: "输出目标类别与边界框坐标" },
  { family: "audio_classification", label: "语音分类 / 关键词识别", output: "为每段音频输出一个类别" },
  { family: "tabular_regression", label: "表格数值预测", output: "为每行样本输出一个数值" },
];
const IMMUTABLE_COMMIT = /^[0-9a-f]{40}$/;
const HF_CHECK_LABELS = {
  known_license: "许可证明确", onnx_payload: "包含 ONNX", preprocess_config: "包含预处理配置",
  local_cpu_runtime: "本机 CPU Runtime", within_local_size_budget: "符合本地大小预算", image_classification_tag: "图像分类标签",
};
const EVIDENCE_STATUS_LABELS = {
  completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断", running: "运行中",
  passed: "通过", sufficient: "充分", release_ready: "可交付", quality_failed: "质量未达标",
  integrity_failed: "完整性失败", insufficient_evidence: "证据不足", metrics_missing: "缺少指标", run_incomplete: "运行未完成",
  not_evaluated: "未评测", unknown: "未知",
};

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json !== undefined) { headers["content-type"] = "application/json"; options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) { const error = new Error(typeof value === "object" ? value.detail || JSON.stringify(value) : value); error.status = response.status; error.payload = value; throw error; }
  return value;
}
function clear(element) { while (element?.firstChild) element.firstChild.remove(); }
function formatTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function shortId(value) { return value && value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value || "—"; }
function showNotice(message, tone = "error") { ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = tone; ui.composerNotice.textContent = message; }
function hideNotice() { ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }
function setButtonBusy(button, busy, busyText) { if (!button.dataset.label) button.dataset.label = button.textContent; button.disabled = busy; button.textContent = busy ? busyText : button.dataset.label; }
function formatBytes(value) { if (!Number.isFinite(value)) return "大小未知"; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB`; }
function fixedCommit(value) { return typeof value === "string" && IMMUTABLE_COMMIT.test(value.toLowerCase()); }
function statusLabel(value) { return EVIDENCE_STATUS_LABELS[value] || String(value || "未知"); }
function statusTone(value) {
  if (["completed", "passed", "sufficient", "release_ready"].includes(value)) return "passed";
  if (["failed", "cancelled", "interrupted", "integrity_failed", "quality_failed"].includes(value)) return "failed";
  if (["insufficient_evidence", "metrics_missing", "run_incomplete", "not_evaluated"].includes(value)) return "warning";
  return "neutral";
}
function hfHeaders() { const token = ui.hfTokenInput.value.trim(); return token ? { "X-HF-Token": token } : {}; }
function isImageClassificationTask(task) {
  const capability = task?.task_spec?.capability_request || task?.capability_request || {};
  return capability.modality === "image" && capability.objective === "classification";
}
function resetHfDiscovery({ clearToken = true } = {}) {
  state.hfModels = []; state.hfCard = null; state.modelAssetVerification = null; clear(ui.hfSearchResults); ui.hfModelCard.hidden = true;
  if (clearToken) ui.hfTokenInput.value = "";
}
function resetRunEvidence(runId = null) {
  state.evidenceRunId = runId; state.evidenceLoaded = false; state.evaluationReport = null; state.sampleInferences = []; state.artifactBundles = []; state.evidenceErrors = {};
  ui.sampleTrialInput.value = ""; ui.sampleTrialJson.value = "";
}
function draftId(taskId = state.selectedTaskId) { return taskId || DraftStore?.NEW_TASK || "__new__"; }
function saveDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.write(localStorage, draftId(taskId), ui.messageInput.value); }
function restoreDraft(taskId = state.selectedTaskId) { ui.messageInput.value = DraftStore ? DraftStore.read(localStorage, draftId(taskId)).text : ""; resizeComposer(); }
function clearDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.clear(localStorage, draftId(taskId)); }

async function loadRuntime() {
  const checkingText = "正在检查 Agent Runtime";
  ui.runtimePill.dataset.state = "checking"; ui.runtimePill.querySelector("span").textContent = checkingText; ui.runtimePill.title = checkingText; ui.runtimePill.setAttribute("aria-label", checkingText);
  try { state.runtimeReady = (await request("/agent/runtime")).available === true; } catch (_error) { state.runtimeReady = false; }
  ui.runtimePill.dataset.state = state.runtimeReady ? "ready" : "error";
  const pillText = state.runtimeReady ? "Agent Runtime 已连接" : "Agent 未连接 · 任务操作仍可用";
  ui.runtimePill.querySelector("span").textContent = pillText;
  ui.runtimePill.title = pillText;
  ui.runtimePill.setAttribute("aria-label", pillText);
}
async function loadHfCapability() {
  try { state.hfCapability = await request("/model-assets/huggingface/capability"); }
  catch (error) { state.hfCapability = { available: false, provider: "huggingface", reason: error.message }; }
  if (state.task) renderModelAsset(state.task);
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
    const row = document.createElement("div"); row.className = "task-row"; row.dataset.taskId = task.task_id;
    const button = document.createElement("button"); button.type = "button"; button.className = "task-item"; button.dataset.action = "select-task"; button.dataset.taskId = task.task_id; button.setAttribute("aria-current", String(task.task_id === state.selectedTaskId));
    const title = document.createElement("b"); title.textContent = task.name;
    const meta = document.createElement("span"); meta.className = "task-meta";
    const status = document.createElement("span"); const dot = document.createElement("i"); dot.dataset.status = task.status; status.append(dot, document.createTextNode(STATUS_LABELS[task.status] || task.status));
    const capability = task.recipe_id ? `Recipe ${shortId(task.recipe_id)}` : STATUS_LABELS[task.capability_status] || task.capability_status || "能力待确认";
    const dataCount = task.dataset_report ? datasetDetail(task)[0] : "未导入数据";
    const facts = document.createElement("span"); facts.className = "task-facts"; facts.textContent = `${capability} · ${dataCount}`; facts.title = `${task.recipe_id ? `Recipe ${task.recipe_id}` : capability} · ${dataCount}`;
    const time = document.createElement("time"); time.textContent = formatTime(task.updated_at_utc); meta.append(status, facts, time);
    const idHint = document.createElement("small"); idHint.className = "task-id-hint"; idHint.textContent = shortId(task.task_id); idHint.title = task.task_id;
    button.append(title, meta, idHint);
    const archive = document.createElement("button"); archive.type = "button"; archive.className = "task-archive-button icon-button"; archive.dataset.action = "archive-task"; archive.dataset.taskId = task.task_id;
    archive.disabled = task.status === "running"; archive.title = archive.disabled ? "任务运行中，不能归档" : `归档任务：${task.name}`; archive.setAttribute("aria-label", archive.title);
    archive.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h16v12H4zM3 4h18v3.5H3zM9 11h6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    button.addEventListener("click", () => selectTask(task.task_id)); archive.addEventListener("click", () => confirmTaskArchive(task)); row.append(button, archive); ui.taskList.append(row);
  });
}
function confirmTaskArchive(task) {
  if (task.status === "running") { showNotice("真实训练运行中，暂不能归档任务。请等待运行结束或先取消训练。"); return; }
  openSimpleDialog({
    kicker: "任务归档", title: `归档“${task.name}”？`,
    body: "任务只会从默认列表隐藏；数据、Run、指标和产物都会保留。归档后不能再启动新的训练运行。",
    allowLabel: "确认归档",
    onAllow: async () => {
      const archivedSelected = task.task_id === state.selectedTaskId;
      await request(`/tasks/${encodeURIComponent(task.task_id)}/archive`, { method: "POST" });
      await loadTasks();
      if (archivedSelected) {
        const nextTaskId = state.tasks[0]?.task_id;
        if (nextTaskId) await selectTask(nextTaskId); else openNewTask();
      }
      showNotice("任务已归档；训练数据、运行记录和产物仍然保留。", "ok");
    },
  });
}
function openNewTask() {
  saveDraft(); stopPolling(); state.selectionToken += 1; Object.assign(state, { selectedTaskId: null, task: null, conversation: null, runEvents: [], pendingMessage: null, lastRenderKey: "" });
  resetHfDiscovery(); resetRunEvidence();
  history.replaceState(null, "", location.pathname); ui.taskPlan.hidden = true; ui.emptyState.hidden = false; ui.conversation.hidden = true;
  ui.taskControlPanel.hidden = true; ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.taskEyebrow.textContent = "MODEL TRAINING HARNESS"; ui.taskTitle.textContent = "开始一个训练任务";
  ui.messageInput.placeholder = "描述你想训练的模型，或告诉我下一步怎么做…"; restoreDraft(null); renderTaskList(); closeSidebar(); closeInspector(); ui.messageInput.focus();
}
async function selectTask(taskId) {
  if (taskId !== state.selectedTaskId) { saveDraft(); resetHfDiscovery(); resetRunEvidence(); }
  stopPolling(); hideNotice(); const token = ++state.selectionToken; state.selectedTaskId = taskId; state.lastRenderKey = ""; state.pendingMessage = state.pendingMessage?.task_id === taskId ? state.pendingMessage : null; history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  renderTaskList(); ui.taskPlan.hidden = false; ui.emptyState.hidden = true; ui.conversation.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false; closeSidebar();
  restoreDraft(taskId); await refreshSelected({ force: true, token }); if (state.selectedTaskId === taskId && state.selectionToken === token) state.pollTimer = window.setInterval(() => refreshSelected(), 1400);
}
async function refreshSelected({ force = false, token = state.selectionToken } = {}) {
  const taskId = state.selectedTaskId; if (!taskId || token !== state.selectionToken) return;
  if (state.refreshInFlight && !force) return;
  const seq = ++state.refreshSeq; state.refreshInFlight = true;
  try {
    try {
      const response = await request(`/tasks/${encodeURIComponent(taskId)}`); if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return; state.task = response.task;
      const selectedRunId = response.task.current_run_id || null; if (state.evidenceRunId !== selectedRunId) resetRunEvidence(selectedRunId);
      if (response.task.current_run_id) {
        try {
          const runEvents = (await request(`/runs/${encodeURIComponent(response.task.current_run_id)}/events`)).events || [];
          if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
          state.runEvents = runEvents;
        } catch (_error) {
          if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
          state.runEvents = [];
        }
      }
      else state.runEvents = [];
      renderTask(response.task);
      if (response.task.current_result?.status === "completed" && (force || !state.evidenceLoaded)) {
        await loadRunEvidence(response.task);
        if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      }
    } catch (error) {
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      showNotice(error.message); return;
    }
    try {
      const remoteConversation = (await request(`/tasks/${encodeURIComponent(taskId)}/conversation`)).conversation;
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      state.conversation = remoteConversation.session_id ? remoteConversation : null;
      if (state.pendingMessage?.task_id === taskId && remoteConversation.items.some((item) => item.role === "user" && item.text === state.pendingMessage.text)) state.pendingMessage = null;
      if (remoteConversation.session_id) {
        const pillText = "Agent Runtime 已连接";
        state.runtimeReady = true; ui.runtimePill.dataset.state = "ready"; ui.runtimePill.querySelector("span").textContent = pillText; ui.runtimePill.title = pillText; ui.runtimePill.setAttribute("aria-label", pillText);
      }
    } catch (error) {
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      if (error.status === 503) { const pillText = "Agent 未连接 · 任务操作仍可用"; state.runtimeReady = false; state.conversation = null; ui.runtimePill.dataset.state = "error"; ui.runtimePill.querySelector("span").textContent = pillText; ui.runtimePill.title = pillText; ui.runtimePill.setAttribute("aria-label", pillText); }
      else showNotice(error.message);
    }
    renderConversation(force); if (force) {
      await loadTasks();
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    }
  } finally {
    if (seq === state.refreshSeq) state.refreshInFlight = false;
  }
}

function renderTask(task) {
  ui.taskEyebrow.textContent = task.task_id; ui.taskTitle.textContent = task.name; ui.taskStatus.textContent = STATUS_LABELS[task.status] || task.status; ui.taskStatus.dataset.status = task.status;
  renderControl(task); renderTaskSpec(task); renderPlan(task); renderStages(task); renderCapability(task); renderModelAsset(task); renderDataset(task); renderContract(task); renderResult(task); renderRunEvents(); renderRunControl(task);
  ui.messageInput.placeholder = task.control?.next_action?.label ? `你也可以继续补充：${task.control.next_action.label}…` : "继续询问或补充任务信息…";
}
function stageKey(task) { return task.control?.current_stage || "task_understanding"; }
function stageLabel(value) { if (value?.startsWith("run_")) return "训练与评测"; return STAGE_LABELS[value] || value || "确认任务理解"; }
function planState(task) {
  const current = stageKey(task);
  if (["task_understanding", "capability_resolution"].includes(current)) return 1;
  if (current === "data_preparation") return 2;
  if (current === "contract_review") return 3;
  if (current === "ready_to_run" || current.startsWith("run_")) return 4;
  return 5;
}
function nextActionDescription(action, blocked) {
  if (blocked?.message) return blocked.message;
  const descriptions = {
    upload_dataset: "导入与任务规格匹配的数据，后端会执行真实体检。", review_capability_gap: "当前没有已验证的训练方案；先查看缺口与构建状态。",
    confirm_training_contract: "确认数据授权、标签或目标字段与离线验收门槛。", start_training_run: "启动后端真实训练，并持续记录事件、指标与产物。",
    view_run_progress: "查看当前 Run 的真实状态；页面不会用动画模拟训练进度。", review_evaluation: "检查独立评测、失败样本与可追溯模型产物。",
    inspect_run_failure: "先阅读失败、取消或中断证据，再决定是否恢复。", retry_training_run: "旧 Run 的状态、错误和事件会保留；确认后由后端基于同一冻结合同创建新的 Run。", clarify_task_spec: "明确模型唯一输出，系统才会匹配训练能力。",
    confirm_task_spec: "确认系统对输入、目标与输出的理解后再检查数据。",
    stage_recipe_samples: "上传少量按类别整理的 PCM WAV 样例 ZIP；样例只用于构建能力，不会被当成正式训练数据。",
    start_recipe_build: "生成受约束的 RecipeSpec，并由可信音频引擎执行白名单、安全边界和版本校验。",
    approve_recipe_registration: "核对候选声明与两个摘要哈希；明确批准后才会把 Recipe / Data Adapter 绑定到当前任务。",
  };
  return descriptions[action?.id] || "按照后端给出的唯一下一步继续当前训练任务。";
}
function renderControl(task) {
  const control = task.control || {}; const action = control.next_action || {}; const blocked = control.blocked_by?.[0];
  ui.taskControlPanel.hidden = false; ui.currentStageState.textContent = stageLabel(control.current_stage); ui.nextActionLabel.textContent = action.label || "等待下一步";
  ui.nextActionDescription.textContent = nextActionDescription(action, blocked); ui.nextActionButton.textContent = action.label || "查看任务"; ui.nextActionButton.disabled = !action.id; ui.nextActionCard.dataset.state = blocked ? "blocked" : "ready";
  ui.taskBlocker.hidden = !blocked; if (blocked) { ui.taskBlockerTitle.textContent = "当前步骤需要处理"; ui.taskBlockerDescription.textContent = blocked.message; ui.taskBlockerActionButton.hidden = false; ui.taskBlockerActionButton.textContent = action.label || "处理阻断"; }
}
function valueOrDash(value) { return value === undefined || value === null || value === "" ? "待确认" : String(value); }
function renderTaskSpec(task) {
  const spec = task.task_spec; const decision = task.capability_decision || {}; if (!spec) { ui.taskSpecCard.hidden = true; return; }
  const resolved = decision.status === "resolved"; const visualStatus = resolved ? "confirmed" : String(decision.status || "needs_clarification").replaceAll("_", "-");
  ui.taskSpecCard.hidden = false; ui.taskSpecCard.dataset.status = visualStatus; ui.taskSpecVersion.textContent = `v${spec.revision}`;
  ui.taskSpecStatus.textContent = resolved ? "已确认" : decision.status === "needs_confirmation" ? "待确认" : "待澄清";
  ui.taskSpecHeading.textContent = resolved ? "任务理解已经确认" : decision.status === "needs_confirmation" ? "请检查系统对任务的理解" : "请先澄清模型要输出什么";
  ui.taskSpecSummary.textContent = resolved ? `已确认“${decision.candidates?.[0]?.label || decision.selected_family || "训练任务"}”；能力匹配、数据和运行都以这个版本为准。` : decision.question || "确认后系统才会匹配训练能力。";
  const capability = spec.capability_request || {}; const candidate = decision.selected_family ? decision.candidates?.find((item) => item.family === decision.selected_family) : null;
  ui.taskSpecInput.textContent = valueOrDash(capability.modality); ui.taskSpecObjective.textContent = valueOrDash(candidate?.label || capability.objective); ui.taskSpecOutput.textContent = valueOrDash(candidate?.output || capability.target_kind);
  const constraints = capability.constraints; ui.taskSpecConstraints.textContent = constraints && Object.keys(constraints).length ? Object.entries(constraints).map(([key, value]) => `${key}: ${value}`).join(" · ") : "本地运行，其他约束待补充";
  ui.taskSpecClarification.hidden = resolved; ui.taskSpecClarificationTitle.textContent = decision.status === "needs_confirmation" ? "请确认候选任务" : "还需要确认一项信息"; ui.taskSpecClarificationDescription.textContent = decision.question || "请选择模型唯一输出。";
  ui.confirmTaskSpecButton.hidden = resolved; ui.confirmTaskSpecButton.textContent = decision.status === "needs_confirmation" ? "确认任务理解" : "提交澄清"; ui.editTaskSpecButton.disabled = task.status === "running";
}
function renderPlan(task) {
  ui.taskPlanTitle.textContent = stageLabel(stageKey(task));
  ui.taskPlanProgress.textContent = `${planState(task)} / 5`;
}
function datasetDetail(task) {
  const report = task.dataset_report; if (!report) return ["等待数据集", "尚未执行数据体检"];
  if (typeof report.total_images === "number") return [`${report.total_images} 张图片`, `${report.class_count} 类 · 排除 ${report.rejected_count || 0} 张`];
  if (typeof report.total_audio === "number") return [`${report.total_audio} 段音频`, `${report.class_count} 类 · ${report.speaker_count} 个说话人分组 · 排除 ${report.rejected_count || 0} 段`];
  return [`${report.row_count || 0} 行数据`, `${report.feature_count || Math.max((report.column_count || 1) - 1, 0)} 个特征 · 目标 ${report.target_column || "—"}`];
}
function deliveryDetail(task) {
  const result = task.current_result;
  if (!result || result.status !== "completed") return "等待评测结果";
  const verdict = releaseVerdict(task);
  if (verdict.releaseReady) return "证据充分，可生成交付包";
  return `${statusLabel(verdict.conclusion)}：${verdict.reasons[0] || "查看五维评测结论"}`;
}
function renderStages(task) {
  const [dataCount, dataSummary] = datasetDetail(task); const result = task.current_result; const hasData = Boolean(task.dataset_report); const confirmed = task.contract_confirmed === true; const finished = result?.status === "completed"; const blocked = task.status === "needs_recipe"; const current = planState(task);
  const stages = [
    [LIFECYCLE_STEPS[0], blocked ? "能力缺口已记录" : `Recipe：${task.recipe_id || "待确认"}`],
    [LIFECYCLE_STEPS[1], hasData ? `${dataCount} · ${dataSummary}` : blocked ? "等待训练方案 / 数据读取器" : "等待导入"],
    [LIFECYCLE_STEPS[2], confirmed ? "授权、标签/目标、门槛已确认" : "等待人工确认"],
    [LIFECYCLE_STEPS[3], finished ? "真实训练与独立评测完成" : result ? `运行状态：${result.status}` : "尚未启动"],
    [LIFECYCLE_STEPS[4], deliveryDetail(task)],
  ];
  const releaseDone = releaseVerdict(task).releaseReady === true;
  clear(ui.stageList); stages.forEach(([title, detail], index) => {
    const stageState = index + 1 < current
      ? "done"
      : index + 1 === current
        ? (index === 4 && releaseDone ? "done" : "active")
        : "waiting";
    const item = document.createElement("li"); item.className = "stage-item"; item.dataset.state = stageState;
    const mark = document.createElement("span"); mark.className = "stage-mark"; mark.textContent = stageState === "done" ? "✓" : String(index + 1);
    const copy = document.createElement("span"); copy.className = "stage-copy"; const b = document.createElement("b"); b.textContent = title; const small = document.createElement("span"); small.textContent = detail; copy.append(b, small);
    const label = document.createElement("span"); label.className = "stage-state"; label.textContent = stageState === "done" ? "完成" : stageState === "active" ? "当前" : "待办"; item.append(mark, copy, label); ui.stageList.append(item);
  });
}
function addFact(label, value) { const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label; const selected = document.createElement("b"); selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); ui.capabilityFacts.append(row); }
function renderCapability(task) {
  const request = task.capability_request || {}; const build = task.recipe_request; const recipeBuild = task.current_recipe_build; const decision = task.capability_decision || {}; clear(ui.capabilityFacts);
  if (decision.status === "needs_clarification") { ui.capabilityState.textContent = "待澄清"; ui.capabilitySummary.textContent = decision.question || "需要先明确模型唯一输出，尚未匹配训练方案。"; }
  else if (decision.status === "needs_confirmation") { ui.capabilityState.textContent = "待确认"; ui.capabilitySummary.textContent = "后端已形成候选任务规格；确认前不会绑定训练方案或生成运行。"; }
  else if (task.capability_status === "matched") { ui.capabilityState.textContent = "已匹配"; ui.capabilitySummary.textContent = `已选择 ${task.recipe_id}；该训练方案将接入统一的数据、合同、运行、评测和产物闭环。`; }
  else if (task.capability_status === "needs_recipe") { ui.capabilityState.textContent = "待构建"; ui.capabilitySummary.textContent = "现有 Recipe 无法覆盖该能力。系统已持久化构建请求，并且不会伪造训练进度。"; }
  else { ui.capabilityState.textContent = "待识别"; ui.capabilitySummary.textContent = "继续描述输入数据、预测目标和运行限制，以匹配或构建 Recipe。"; }
  addFact("数据模态", request.modality); addFact("任务目标", request.objective); addFact("输出类型", request.target_kind); addFact("Recipe", task.recipe_id); addFact("Data Adapter", task.data_adapter_id || request.data_adapter); if (build) addFact("构建请求", build.request_id || build.recipe_request_id);
  if (task.staged_assets?.latest) addFact("构建样例", `${task.staged_assets.latest.status} · ${task.staged_assets.latest.report?.file_count || 0} 个 WAV`);
  if (recipeBuild) { addFact("BuildAttempt", `${recipeBuild.status} · ${shortId(recipeBuild.attempt_id)}`); addFact("Candidate SHA", recipeBuild.candidate_digest ? shortId(recipeBuild.candidate_digest) : "未生成"); addFact("Validation SHA", recipeBuild.validation_digest ? shortId(recipeBuild.validation_digest) : "未生成"); }
  if (task.recipe_version_id) addFact("RecipeVersion", shortId(task.recipe_version_id));
  ui.scaffoldRecipeButton.hidden = task.capability_status !== "needs_recipe" || decision.selected_family === "audio_classification";
  ui.scaffoldRecipeButton.textContent = build?.status === "scaffold_ready" ? "重新生成 Code Agent 构建包" : "生成 Code Agent 构建包";
}
function addModelAssetFact(label, value, { code = false } = {}) {
  const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label;
  const selected = document.createElement(code ? "code" : "b"); selected.textContent = value || "—"; selected.title = selected.textContent;
  row.append(name, selected); ui.modelAssetFacts.append(row);
}
function renderModelAsset(task) {
  const binding = task.model_asset_binding || null; const applicable = isImageClassificationTask(task) || Boolean(binding);
  ui.modelAssetCard.hidden = !applicable; if (!applicable) return;
  const verification = task.model_asset_verification || state.modelAssetVerification; clear(ui.modelAssetFacts);
  ui.modelAssetBinding.hidden = !binding; ui.modelAssetCard.dataset.state = binding && verification?.ok ? "verified" : binding ? "warning" : "neutral";
  if (binding) {
    ui.modelAssetState.textContent = verification?.ok ? "已验证" : "已绑定";
    ui.modelAssetSummary.textContent = `已绑定 ${binding.repository || binding.repo_id || "Hugging Face 模型"}；训练合同会引用固定资产清单，不会跟随仓库后续变化。`;
    addModelAssetFact("仓库", binding.repository || binding.repo_id); addModelAssetFact("固定 Commit", binding.resolved_commit, { code: true });
    addModelAssetFact("License", binding.license); addModelAssetFact("Asset ID", binding.asset_id, { code: true }); addModelAssetFact("Manifest", binding.manifest_sha256, { code: true });
    ui.modelAssetVerifyStatus.dataset.state = verification?.ok ? "passed" : verification ? "failed" : "neutral";
    ui.modelAssetVerifyStatus.textContent = verification?.ok ? `完整性复核通过 · ${verification.asset?.files?.length || binding.files?.length || 0} 个白名单文件` : verification ? `完整性复核失败：${(verification.errors || []).join("、") || "未知错误"}` : "尚未执行完整性复核";
  } else {
    ui.modelAssetState.textContent = "未绑定"; ui.modelAssetSummary.textContent = "可从 Hugging Face 查找兼容的 ONNX 图像特征模型。选择模型不会自动推进任务或创建 Run。";
  }
  const available = state.hfCapability?.available === true;
  ui.hfCapabilityStatus.dataset.state = available ? "available" : state.hfCapability ? "unavailable" : "checking";
  ui.hfCapabilityStatus.textContent = available ? "官方 Hugging Face API 可用；只下载白名单文件并固定到不可变 commit。" : state.hfCapability ? `Hugging Face 能力不可用：${state.hfCapability.reason || "capability_unavailable"}` : "正在检查官方 Hugging Face 能力…";
  const locked = task.status === "running"; ui.hfSearchInput.disabled = !available || locked; ui.hfTokenInput.disabled = !available || locked; ui.hfSearchButton.disabled = !available || locked;
  ui.modelAssetVerifyButton.disabled = !binding; renderHfSearchResults(); renderHfCard();
}
function renderHfSearchResults() {
  clear(ui.hfSearchResults); if (!state.hfModels.length) return;
  state.hfModels.forEach((model) => {
    const button = document.createElement("button"); button.type = "button"; button.className = "hf-search-result";
    const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = model.repository || "未知仓库";
    const detail = document.createElement("small"); detail.textContent = `${model.pipeline_tag || "pipeline 未知"} · ${Number(model.downloads || 0).toLocaleString("zh-CN")} 次下载`;
    const action = document.createElement("em"); action.textContent = "检查"; copy.append(name, detail); button.append(copy, action);
    button.addEventListener("click", () => loadHfModelCard(model, button)); ui.hfSearchResults.append(button);
  });
}
async function searchHfModels(event) {
  event.preventDefault(); const query = ui.hfSearchInput.value.trim(); if (!query) { showNotice("请输入 Hugging Face 模型仓库或搜索词。"); return; }
  if (state.hfCapability?.available !== true) { showNotice(`Hugging Face 搜索不可用：${state.hfCapability?.reason || "capability_unavailable"}`); return; }
  setButtonBusy(ui.hfSearchButton, true, "正在搜索"); clear(ui.hfSearchResults); state.hfModels = []; state.hfCard = null; ui.hfModelCard.hidden = true;
  try {
    const params = new URLSearchParams({ q: query, pipeline_tag: "image-classification", limit: "8" });
    const response = await request(`/model-assets/huggingface/search?${params}`, { headers: hfHeaders() }); state.hfModels = response.models || [];
    renderHfSearchResults(); if (!state.hfModels.length) { const empty = document.createElement("p"); empty.className = "hf-search-empty"; empty.textContent = "官方目录没有返回匹配模型。请调整仓库名或关键词。"; ui.hfSearchResults.append(empty); }
  } catch (error) { const empty = document.createElement("p"); empty.className = "hf-search-empty"; empty.textContent = `真实搜索失败：${error.message}`; ui.hfSearchResults.append(empty); }
  finally { setButtonBusy(ui.hfSearchButton, false, ""); if (state.task) renderModelAsset(state.task); }
}
async function loadHfModelCard(model, button) {
  setButtonBusy(button, true, "读取中");
  try {
    const params = new URLSearchParams({ repo_id: model.repository }); if (fixedCommit(model.revision)) params.set("revision", model.revision.toLowerCase());
    const response = await request(`/model-assets/huggingface/card?${params}`, { headers: hfHeaders() }); state.hfCard = response.model; renderHfCard();
  } catch (error) { state.hfCard = null; renderHfCard(); showNotice(`模型卡读取失败：${error.message}`); }
  finally { setButtonBusy(button, false, ""); }
}
function renderHfCard() {
  const card = state.hfCard; ui.hfModelCard.hidden = !card; if (!card) return;
  const compatibility = card.compatibility || {}; const compatible = compatibility.state === "compatible_candidate"; const immutable = fixedCommit(card.revision);
  ui.hfModelRepo.textContent = card.repository || "—"; ui.hfModelCommit.textContent = card.revision || "未解析"; ui.hfModelCommit.title = card.revision || ""; ui.hfModelLicense.textContent = card.license || "unknown";
  ui.hfCompatibilityState.dataset.state = compatible && immutable ? "compatible" : "unsupported";
  ui.hfCompatibilityState.textContent = compatible && immutable ? "可绑定候选" : compatibility.state === "needs_license_review" ? "需许可证审查" : "不兼容";
  clear(ui.hfCompatibilityChecks); Object.entries(compatibility.checks || {}).forEach(([name, passed]) => { const item = document.createElement("span"); item.dataset.passed = String(passed === true); item.textContent = `${passed === true ? "✓" : "×"} ${HF_CHECK_LABELS[name] || name}`; ui.hfCompatibilityChecks.append(item); });
  const reasons = [...(compatibility.blocking_reasons || [])]; if (!immutable) reasons.unshift("revision_not_immutable_commit"); ui.hfCompatibilityReasons.textContent = reasons.length ? `阻断原因：${reasons.join("、")}` : "全部兼容性检查来自后端模型卡。";
  clear(ui.hfModelFiles); (card.files || []).filter((file) => ["model.onnx", "config.json", "README.md"].includes(file.path)).forEach((file) => { const row = document.createElement("div"); const name = document.createElement("code"); name.textContent = file.path; const size = document.createElement("span"); size.textContent = formatBytes(file.size_bytes); row.append(name, size); ui.hfModelFiles.append(row); });
  ui.hfAttachButton.disabled = !compatible || !immutable || state.task?.status === "running";
}
function attachHfModel() {
  const card = state.hfCard; if (!card || !fixedCommit(card.revision) || card.compatibility?.state !== "compatible_candidate") { showNotice("只有通过兼容性检查且固定到 40 位 commit 的模型才能绑定。"); return; }
  openSimpleDialog({
    kicker: "固定并下载模型资产", title: "批准本次 Hugging Face 下载？",
    body: `仓库：${card.repository}；Commit：${card.revision}；License：${card.license || "unknown"}。系统只会下载 model.onnx、config.json、README.md，完成哈希校验后原子激活；不会自动创建训练 Run。`,
    allowLabel: "批准下载并绑定", onAllow: async () => {
      const response = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-assets/huggingface`, { method: "POST", headers: hfHeaders(), json: { repo_id: card.repository, commit: card.revision, approval_confirmed: true } });
      state.task = response.task; state.modelAssetVerification = response.task.model_asset_verification || null; ui.hfTokenInput.value = "";
      showNotice("模型资产已按固定 commit 下载、校验并绑定；尚未创建训练 Run。", "ok"); await refreshSelected({ force: true });
    },
  });
}
async function verifyModelAsset() {
  if (!state.selectedTaskId) return; setButtonBusy(ui.modelAssetVerifyButton, true, "复核中");
  try { state.modelAssetVerification = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-assets/current/verify`); renderModelAsset(state.task); showNotice(state.modelAssetVerification.ok ? "本地模型资产清单与文件哈希一致。" : "本地模型资产复核失败，资产已阻断。", state.modelAssetVerification.ok ? "ok" : "error"); }
  catch (error) { state.modelAssetVerification = { ok: false, errors: [error.message] }; renderModelAsset(state.task); showNotice(`模型资产复核失败：${error.message}`); }
  finally { setButtonBusy(ui.modelAssetVerifyButton, false, ""); if (state.task) renderModelAsset(state.task); }
}
function renderDataset(task) {
  const report = task.dataset_report; const [count, summary] = datasetDetail(task); ui.datasetCount.textContent = report ? count : "未导入";
  ui.datasetSummary.textContent = report ? `${summary} · ${report.risks?.[0]?.message || "后端体检完成"}` : "导入图片/音频类别 ZIP 或 CSV；格式必须与当前 Recipe 的 Data Adapter 一致。";
  ui.inspectorDatasetButton.textContent = report ? "替换并重新体检" : "导入数据集"; const specReady = task.capability_decision?.status === "resolved"; const blocked = task.status === "running" || task.status === "needs_recipe" || !specReady; ui.datasetButton.disabled = blocked; ui.inspectorDatasetButton.disabled = blocked;
}
function gateEntries(gates) { return "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates ? [[gates.clean_test_mae_max, "MAE 上限"], [gates.clean_test_rmse_max, "RMSE 上限"], [gates.clean_test_r2_min, "R² 下限"]] : [[gates.clean_test_accuracy_min, "Accuracy"], [gates.clean_test_macro_f1_min, "Macro-F1"], [gates.clean_test_worst_class_recall_min, "最差类 Recall"]]; }
function renderContract(task) {
  const contract = task.contract; ui.contractCard.hidden = !contract; if (!contract) return; ui.contractState.textContent = task.contract_confirmed ? "已冻结" : "待确认"; clear(ui.gateGrid);
  gateEntries(contract.release_gates || {}).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? value.toFixed(2) : "—"; const span = document.createElement("span"); span.textContent = label; cell.append(b, span); ui.gateGrid.append(cell); });
  const confirmed = task.contract_confirmed === true; ui.confirmations.hidden = confirmed; ui.startThroughAgentButton.hidden = !confirmed || task.status === "running";
  const retryable = TERMINAL_RETRY_STATUSES.has(task.current_result?.status); ui.startThroughAgentButton.textContent = retryable ? "保留证据并重新训练" : task.current_run_id ? "查看本轮评测结论" : "批准并启动真实训练";
  ui.confirmations.querySelectorAll("input").forEach((input) => { input.disabled = task.status === "running"; input.checked = task.confirmations?.[input.dataset.confirm] === true; });
}
function releaseVerdict(task) {
  const result = task?.current_result;
  if (!result) return { conclusion: "not_evaluated", releaseReady: false, reasons: [] };
  const fresh = state.evidenceRunId === result.run_id ? state.evaluationReport : null;
  const report = fresh || result.evaluation_report || null;
  return {
    conclusion: report?.conclusion || result.evaluation_conclusion || "not_evaluated",
    releaseReady: report?.release_ready === true,
    reasons: [...(report?.evidence_reasons || []), ...(report?.integrity_errors || [])],
  };
}
function metricEntries(result) { const clean = result?.metrics?.clean_test || {}; return "mae" in clean || "rmse" in clean || "r2" in clean ? [[clean.mae, "MAE"], [clean.rmse, "RMSE"], [clean.r2, "R²"]] : [[clean.accuracy, "Accuracy"], [clean.macro_f1, "Macro-F1"], [clean.worst_class_recall, "最差类 Recall"]]; }
function renderResult(task) {
  const result = task.current_result; ui.resultCard.hidden = !result; clear(ui.artifactList); const artifacts = result?.artifacts || []; ui.artifactCount.textContent = String(artifacts.length);
  artifacts.forEach((artifact) => { const link = document.createElement("a"); link.href = `/runs/${encodeURIComponent(result.run_id)}/artifacts/${encodeURIComponent(artifact.name)}`; link.download = artifact.name; const name = document.createElement("span"); name.textContent = artifact.name; const action = document.createElement("span"); action.textContent = "下载"; link.append(name, action); ui.artifactList.append(link); });
  [ui.evaluationEvidenceCard, ui.candidateComparisonCard, ui.failureSampleCard, ui.runHistoryCard, ui.sampleTrialCard, ui.artifactBundleCard].forEach((card) => { card.hidden = !result; });
  if (!result) { clear(ui.evidenceDimensions); clear(ui.candidateList); clear(ui.failureSampleList); clear(ui.runHistoryList); clear(ui.sampleInferenceList); clear(ui.artifactBundleList); return; }
  const running = RUNNING_STATUSES.has(result.status);
  const verdict = releaseVerdict(task);
  const headline = running
    ? "运行中"
    : result.status === "cancelled"
      ? "已取消"
      : result.status === "interrupted"
        ? "已中断"
        : result.status === "completed"
          ? statusLabel(verdict.conclusion)
          : "运行异常";
  ui.gateResult.textContent = headline;
  ui.gateResult.dataset.state = running ? "neutral" : statusTone(verdict.conclusion);
  ui.runId.textContent = shortId(result.run_id); ui.runId.title = result.run_id; clear(ui.metricGrid); ui.resultCard.querySelector(".gate-note")?.remove(); metricEntries(result).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? value.toFixed(3) : "—"; const span = document.createElement("span"); span.textContent = label; cell.append(b, span); ui.metricGrid.append(cell); });
  const gateNote = document.createElement("p");
  gateNote.className = "gate-note";
  gateNote.textContent = result.offline_gates_passed === true
    ? "离线指标门槛已通过；是否可交付另见下方五维结论。"
    : "离线指标门槛未全部通过。";
  ui.metricGrid.after(gateNote);
  const evaluationUnavailable = state.evidenceErrors.evaluation === "capability_unavailable"; ui.refreshEvaluationButton.disabled = result.status !== "completed" || evaluationUnavailable; ui.refreshEvaluationButton.textContent = evaluationUnavailable ? "评测 API 不可用" : "刷新可信评测报告";
  renderEvaluationEvidence(result); renderCandidateComparison(result); renderFailureSamples(result); renderRunHistory(task, result); renderSampleTrials(result); renderArtifactBundles(result);
}
function appendEmpty(container, message) { const empty = document.createElement("p"); empty.className = "hf-search-empty"; empty.textContent = message; container.append(empty); }
function renderEvaluationEvidence(result) {
  const report = state.evaluationReport || result.evaluation_report; clear(ui.evidenceDimensions);
  const dimensions = [
    ["运行状态", report?.run_status || result.run_status || result.status, "训练 Run 是否真实完成"],
    ["产物完整性", report?.integrity_status || result.integrity_status || "not_evaluated", `${report?.integrity_checks?.length || 0} 项身份、合同与文件哈希检查`],
    ["指标门槛", report?.metric_gate_status || result.metric_gate_status || "not_evaluated", `${Object.keys(report?.metric_gates || {}).length} 项离线验收门槛`],
    ["证据充分性", report?.evidence_status || result.evidence_status || "not_evaluated", report ? `独立测试 ${report.test_sample_count} / 最低 ${report.minimum_test_samples}` : "等待可信评测报告"],
    ["交付结论", report?.conclusion || result.evaluation_conclusion || "not_evaluated", report?.release_ready ? "满足发布证据要求" : "不代表可以发布"],
  ];
  dimensions.forEach(([label, value, detail]) => { const row = document.createElement("div"); row.className = "evidence-dimension"; const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = label; const small = document.createElement("small"); small.textContent = detail; const status = document.createElement("em"); status.dataset.state = statusTone(value); status.textContent = statusLabel(value); copy.append(name, small); row.append(copy, status); ui.evidenceDimensions.append(row); });
  const conclusion = report?.conclusion || result.evaluation_conclusion || "not_evaluated"; ui.evaluationConclusion.textContent = statusLabel(conclusion);
  const reasons = report?.evidence_reasons || []; const integrityErrors = report?.integrity_errors || []; const endpointError = state.evidenceErrors.evaluation;
  ui.evaluationReasons.textContent = [...reasons, ...integrityErrors].join("；") || (endpointError ? `评测 API：${endpointError}` : report?.release_ready ? "五个维度均通过，可以生成 release-ready Artifact Bundle。" : "结论来自当前 Run 的真实状态、指标和证据文件。");
}
function metricSummary(values) {
  const order = ["macro_f1", "accuracy", "worst_class_recall", "mae", "rmse", "r2"]; const entries = order.filter((key) => typeof values?.[key] === "number").slice(0, 3);
  return entries.map((key) => `${key} ${values[key].toFixed(3)}`).join(" · ") || "没有可展示的验证指标";
}
function primaryCandidateScore(values) { const entry = ["macro_f1", "accuracy", "r2", "mae", "rmse"].find((key) => typeof values?.[key] === "number"); return entry ? values[entry].toFixed(3) : "—"; }
function renderCandidateComparison(result) {
  const candidates = Object.entries(result.metrics?.validation_candidates || {}); clear(ui.candidateList); ui.candidateCount.textContent = String(candidates.length);
  ui.candidatePolicy.textContent = result.metrics?.test_set_used_for_selection === true ? "警告：当前指标声明测试集参与了选模，证据会被标记为污染。" : `选模策略：${result.metrics?.selection_policy || "validation_only"}；独立测试集不用于候选选择。`;
  if (!candidates.length) { appendEmpty(ui.candidateList, "本轮尚无候选对比证据。"); return; }
  candidates.forEach(([name, values]) => { const row = document.createElement("div"); row.className = "candidate-row"; row.dataset.selected = String(name === result.metrics?.selected_model); const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = `${name}${name === result.metrics?.selected_model ? " · 已选" : ""}`; const detail = document.createElement("small"); detail.textContent = metricSummary(values); const score = document.createElement("em"); score.textContent = primaryCandidateScore(values); copy.append(title, detail); row.append(copy, score); ui.candidateList.append(row); });
}
function failureSummary(sample) {
  const reference = sample.relative_path || (sample.row_number ? `第 ${sample.row_number} 行` : sample.source_name) || "诊断样本";
  const details = Object.entries(sample).filter(([key]) => !["relative_path", "row_number", "source_name"].includes(key)).slice(0, 4).map(([key, value]) => `${key}: ${typeof value === "number" ? value.toFixed(4) : value}`);
  return [reference, details.join(" · ")];
}
function renderFailureSamples(result) {
  const samples = result.failure_samples || []; const count = result.metrics?.failure_count ?? samples.length; clear(ui.failureSampleList); ui.failureSampleCount.textContent = String(count);
  if (!samples.length) { appendEmpty(ui.failureSampleList, count ? `后端记录 ${count} 个失败，但没有返回可展示的诊断样本。` : "独立测试集中没有记录误判样本。"); return; }
  samples.slice(0, 8).forEach((sample, index) => { const [reference, detail] = failureSummary(sample); const row = document.createElement("div"); row.className = "failure-sample-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = reference; const small = document.createElement("small"); small.textContent = detail; const order = document.createElement("em"); order.textContent = `#${index + 1}`; copy.append(title, small); row.append(copy, order); ui.failureSampleList.append(row); });
}
function renderRunHistory(task, result) {
  const runIds = task.run_ids || []; const history = result.optimization_history || []; clear(ui.runHistoryList); ui.runHistoryCount.textContent = String(runIds.length);
  if (!runIds.length) { appendEmpty(ui.runHistoryList, "尚无训练运行。"); return; }
  runIds.forEach((runId, index) => { const decision = history.find((item) => item.parent_run_id === runId); const current = runId === task.current_run_id; const row = document.createElement("div"); row.className = "run-history-row"; const order = document.createElement("i"); order.textContent = index + 1; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = shortId(runId); title.title = runId; const detail = document.createElement("small"); detail.textContent = decision ? `已批准策略 ${decision.strategy_id}${decision.test_contaminated ? " · 测试证据污染" : " · 验证证据驱动"}` : current ? `当前 Run · ${result.status}` : "历史 Run"; const status = document.createElement("em"); status.dataset.state = current ? "current" : "history"; status.textContent = current ? "当前" : "历史"; copy.append(title, detail); row.append(order, copy, status); ui.runHistoryList.append(row); });
}
function sampleTypeForRecipe(recipe) { return { "image-folder-classification": "image", "audio-keyword-classification": "audio", "tabular-regression": "tabular" }[recipe] || null; }
function renderSampleTrials(result) {
  const sampleType = sampleTypeForRecipe(result.recipe); const unavailable = state.evidenceErrors.samples === "capability_unavailable"; const ready = result.status === "completed" && Boolean(sampleType) && !unavailable; clear(ui.sampleInferenceList);
  ui.sampleJsonField.hidden = sampleType !== "tabular"; ui.sampleTrialSelectButton.hidden = sampleType === "tabular"; ui.sampleTrialRunButton.disabled = !ready;
  ui.sampleTrialInput.accept = sampleType === "image" ? "image/png,image/jpeg,image/webp,image/bmp" : sampleType === "audio" ? ".wav,audio/wav" : "";
  if (unavailable) { ui.sampleTrialState.textContent = "API 不可用"; ui.sampleTrialSummary.textContent = "后端没有接通 task-owned sample-inferences API；页面不会模拟推理结果。"; ui.sampleTrialRunButton.disabled = true; }
  else if (!sampleType) { ui.sampleTrialState.textContent = "不可用"; ui.sampleTrialSummary.textContent = `当前 Recipe ${result.recipe || "unknown"} 没有原始样本推理适配器。`; ui.sampleTrialRunButton.disabled = true; }
  else if (result.status !== "completed") { ui.sampleTrialState.textContent = "等待完成"; ui.sampleTrialSummary.textContent = "只有完成且通过产物完整性检查的 Run 才能执行真实新样本试跑。"; }
  else { const selected = ui.sampleTrialInput.files?.[0]; ui.sampleTrialState.textContent = selected ? "样本已选择" : state.sampleInferences.length ? `${state.sampleInferences.length} 次记录` : "未试跑"; ui.sampleTrialSummary.textContent = sampleType === "tabular" ? "输入一行与训练特征列匹配的 JSON。额外字段会被报告但不参与预测。" : selected ? `已选择 ${selected.name} · ${formatBytes(selected.size)}` : `选择一份新的${sampleType === "image" ? "图片" : "PCM WAV 音频"}；原始内容不会写入证据报告。`; }
  if (!state.sampleInferences.length) { appendEmpty(ui.sampleInferenceList, "尚无真实新样本试跑记录。"); return; }
  [...state.sampleInferences].reverse().slice(0, 6).forEach((check) => { const row = document.createElement("div"); row.className = "sample-inference-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = check.sample?.source_name || check.check_id; const detail = document.createElement("small"); detail.textContent = check.status === "passed" ? `预测：${JSON.stringify(check.prediction)} · ${Number(check.elapsed_ms || 0).toFixed(1)} ms · SHA ${shortId(check.sample?.sha256)}` : check.reason || "后端阻断了该样本"; const status = document.createElement("em"); status.dataset.state = check.status; status.textContent = check.status === "passed" ? "通过" : "已阻断"; copy.append(title, detail); row.append(copy, status); ui.sampleInferenceList.append(row); });
}
function renderArtifactBundles(result) {
  const completed = result.status === "completed"; ui.buildArtifactBundleButton.disabled = !completed || state.evidenceErrors.bundles === "capability_unavailable"; clear(ui.artifactBundleList);
  ui.artifactBundleState.textContent = state.artifactBundles.length ? `${state.artifactBundles.length} 个` : completed ? "尚未生成" : "等待完成";
  ui.artifactBundleSummary.textContent = state.evidenceErrors.bundles ? `Artifact Bundle API：${state.evidenceErrors.bundles}` : "生成经过完整性校验、隐私过滤且可下载复核的交付 ZIP；生成并不等同于质量门槛通过。";
  if (!state.artifactBundles.length) { appendEmpty(ui.artifactBundleList, completed ? "尚无交付包。生成时会自动排除原始数据、测试参考和内部运行状态。" : "训练完成后才能生成交付包。"); return; }
  [...state.artifactBundles].reverse().forEach((bundle) => { const row = document.createElement("div"); row.className = "artifact-bundle-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = bundle.bundle_id; const detail = document.createElement("small"); detail.textContent = `${formatBytes(bundle.archive?.size_bytes)} · SHA ${shortId(bundle.archive?.sha256)}`; const link = document.createElement("a"); link.href = `/tasks/${encodeURIComponent(state.selectedTaskId)}/runs/${encodeURIComponent(result.run_id)}/artifact-bundles/${encodeURIComponent(bundle.bundle_id)}/download`; link.download = `${result.run_id}-${bundle.bundle_id}.zip`; link.textContent = "下载 ZIP"; const meta = document.createElement("span"); meta.className = "artifact-bundle-meta"; [[bundle.release_ready ? "release-ready" : "非发布结论"], [bundle.manifest?.privacy_boundary?.raw_data_included === false ? "不含原始数据" : "检查隐私边界"], [`${bundle.manifest?.files?.length || 0} 个文件`]].forEach(([value]) => { const item = document.createElement("i"); item.textContent = value; meta.append(item); }); copy.append(title, detail); row.append(copy, link, meta); ui.artifactBundleList.append(row); });
}
async function loadRunEvidence(task) {
  const taskId = task.task_id; const runId = task.current_run_id; if (!taskId || !runId || task.current_result?.status !== "completed") return;
  const base = `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}`;
  const [evaluation, samples, bundles] = await Promise.allSettled([request(`${base}/evaluation-report`), request(`${base}/sample-inferences`), request(`${base}/artifact-bundles`)]);
  if (state.selectedTaskId !== taskId || state.evidenceRunId !== runId) return;
  if (evaluation.status === "fulfilled") { state.evaluationReport = evaluation.value.evaluation_report; delete state.evidenceErrors.evaluation; } else state.evidenceErrors.evaluation = [404, 405].includes(evaluation.reason.status) ? "capability_unavailable" : evaluation.reason.message;
  if (samples.status === "fulfilled") { state.sampleInferences = samples.value.sample_inferences || []; delete state.evidenceErrors.samples; } else state.evidenceErrors.samples = [404, 405].includes(samples.reason.status) ? "capability_unavailable" : samples.reason.message;
  if (bundles.status === "fulfilled") { state.artifactBundles = bundles.value.artifact_bundles || []; delete state.evidenceErrors.bundles; } else state.evidenceErrors.bundles = [404, 405].includes(bundles.reason.status) ? "capability_unavailable" : bundles.reason.message;
  state.evidenceLoaded = true; if (state.task) renderResult(state.task);
}
async function refreshEvaluation() {
  const taskId = state.selectedTaskId; const runId = state.task?.current_run_id; if (!taskId || !runId) return; setButtonBusy(ui.refreshEvaluationButton, true, "正在复核");
  try { const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/evaluation-report`); state.evaluationReport = response.evaluation_report; delete state.evidenceErrors.evaluation; renderResult(state.task); showNotice("可信评测报告已按当前运行证据重新读取。", "ok"); }
  catch (error) { state.evidenceErrors.evaluation = [404, 405].includes(error.status) ? "capability_unavailable" : error.message; renderResult(state.task); showNotice(`评测报告不可用：${error.message}`); }
  finally { setButtonBusy(ui.refreshEvaluationButton, false, ""); if (state.task) renderResult(state.task); }
}
async function runSampleTrial() {
  const taskId = state.selectedTaskId; const result = state.task?.current_result; const runId = result?.run_id; const sampleType = sampleTypeForRecipe(result?.recipe); if (!taskId || !runId || result.status !== "completed" || !sampleType) return;
  let body; let filename; let contentType;
  if (sampleType === "tabular") { try { const value = JSON.parse(ui.sampleTrialJson.value); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 必须是一行对象"); body = JSON.stringify(value); filename = "new-sample.json"; contentType = "application/json"; } catch (error) { showNotice(`请输入有效的一行 JSON：${error.message}`); return; } }
  else { const file = ui.sampleTrialInput.files?.[0]; if (!file) { showNotice("请先选择一份新的图片或 WAV 音频样本。"); return; } body = file; filename = file.name; contentType = file.type || (sampleType === "audio" ? "audio/wav" : "application/octet-stream"); }
  setButtonBusy(ui.sampleTrialRunButton, true, "真实推理中");
  try { const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inferences`, { method: "POST", body, headers: { "Content-Type": contentType, "X-Filename": encodeURIComponent(filename), "X-Sample-Type": sampleType } }); state.sampleInferences = [...state.sampleInferences.filter((item) => item.check_id !== response.sample_inference.check_id), response.sample_inference]; ui.sampleTrialInput.value = ""; if (sampleType === "tabular") ui.sampleTrialJson.value = ""; renderResult(state.task); showNotice(`新样本真实试跑完成：${JSON.stringify(response.sample_inference.prediction)}`, "ok"); }
  catch (error) { const check = error.payload?.sample_inference; if (check) state.sampleInferences = [...state.sampleInferences.filter((item) => item.check_id !== check.check_id), check]; renderResult(state.task); showNotice(`新样本试跑被后端阻断：${check?.reason || error.message}`); }
  finally { setButtonBusy(ui.sampleTrialRunButton, false, ""); if (state.task) renderResult(state.task); }
}
async function buildArtifactBundle() {
  const taskId = state.selectedTaskId; const runId = state.task?.current_result?.run_id; if (!taskId || !runId) return; const latestPassed = [...state.sampleInferences].reverse().find((item) => item.status === "passed");
  setButtonBusy(ui.buildArtifactBundleButton, true, "正在校验打包");
  try { const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles`, { method: "POST", json: latestPassed ? { sample_inference_check_id: latestPassed.check_id } : {} }); state.artifactBundles = [...state.artifactBundles.filter((item) => item.bundle_id !== response.artifact_bundle.bundle_id), response.artifact_bundle]; renderResult(state.task); showNotice(response.artifact_bundle.release_ready ? "可信 Artifact Bundle 已生成，评测结论为 release-ready。" : "Artifact Bundle 已生成，但当前评测结论不是 release-ready。", "ok"); }
  catch (error) { state.evidenceErrors.bundles = [404, 405].includes(error.status) ? "capability_unavailable" : error.message; renderResult(state.task); showNotice(`Artifact Bundle 生成失败：${error.message}`); }
  finally { setButtonBusy(ui.buildArtifactBundleButton, false, ""); if (state.task) renderResult(state.task); }
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
    const card = document.createElement("article"); card.className = "run-event"; const failed = ["run.failed", "run.cancelled", "run.interrupted"].includes(event.type); const terminal = event.type === "run.completed" || failed; card.dataset.state = failed ? "failed" : terminal ? "completed" : "running";
    const icon = document.createElement("i"); icon.textContent = failed ? "!" : terminal ? "✓" : event.seq;
    const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = EVENT_LABELS[event.type] || event.type; const detail = document.createElement("small"); detail.textContent = eventDetail(event); copy.append(title, detail);
    const time = document.createElement("em"); time.textContent = formatTime(event.timestamp_utc); card.append(icon, copy, time); ui.runEventList.append(card);
    const row = document.createElement("div"); const seq = document.createElement("i"); seq.textContent = event.seq; const side = document.createElement("span"); const name = document.createElement("b"); name.textContent = EVENT_LABELS[event.type] || event.type; const small = document.createElement("small"); small.textContent = eventDetail(event); side.append(name, small); row.append(seq, side); ui.inspectorEvents.append(row);
  });
}
function renderRunControl(task) {
  const result = task.current_result; const active = Boolean(result && RUNNING_STATUSES.has(result.status)); const retryable = Boolean(result && TERMINAL_RETRY_STATUSES.has(result.status)); const cancelRequested = result?.cancel_requested === true;
  ui.cancelRunButton.hidden = !active; ui.cancelRunButton.disabled = cancelRequested; ui.cancelRunButton.textContent = cancelRequested ? "已请求取消" : "取消训练";
  ui.retryRunButton.hidden = !retryable; ui.retryRunButton.disabled = !retryable;
  ui.runControlStatus.hidden = !result; if (!result) return;
  ui.runControlStatus.dataset.state = result.status; ui.runControlLabel.textContent = cancelRequested ? "取消请求已提交" : active ? "真实训练运行中" : result.status === "completed" ? "训练运行已完成" : result.status === "cancelled" ? "训练已取消" : result.status === "interrupted" ? "训练已中断" : "训练运行异常";
  const terminalReason = result.error || result.cancel_reason;
  ui.runControlDescription.textContent = cancelRequested ? "后端会在当前阶段边界停止；这不会停止 Agent 对话。" : active ? "这里只呈现后端真实状态；取消训练不会停止 Agent 对话。" : retryable ? `旧 Run ${shortId(result.run_id)} · ${result.status}${terminalReason ? ` · ${terminalReason}` : ""}。事件和证据不会被新 Run 覆盖。` : `Run ${shortId(result.run_id)} · ${result.status}`;
}
function localConversation(task) {
  if (!task) return { items: [], pending: [], running: false };
  const control = task.control || {}; const blocked = control.blocked_by?.[0]; const action = control.next_action;
  const blockedText = blocked?.message ? `${blocked.message.replace(/[。！？!?]+$/u, "")}。` : "";
  const statusText = `${stageLabel(control.current_stage)}。${blockedText}${action?.label ? `唯一下一步：${action.label}。` : ""}这些状态来自后端任务对象，刷新后仍保持同一 task_id。`;
  return { items: [{ kind: "message", role: "user", text: task.business_goal, time: task.created_at_utc }, { kind: "message", role: "assistant", text: statusText, time: task.updated_at_utc }], pending: [], running: false };
}
function renderConversation(force = false) {
  const conversation = state.conversation || localConversation(state.task);
  const optimistic = state.pendingMessage?.task_id === state.selectedTaskId ? state.pendingMessage : null;
  const renderKey = JSON.stringify({ items: conversation.items?.map((item) => [item.seq, item.status, item.text]), pending: conversation.pending?.map((item) => item.rpc_id), running: conversation.running, optimistic: optimistic?.text, taskStatus: state.task?.status, eventCount: state.runEvents.length });
  if (!force && renderKey === state.lastRenderKey) return; state.lastRenderKey = renderKey;
  const nearBottom = ui.conversation.scrollHeight - ui.conversation.scrollTop - ui.conversation.clientHeight < 120; clear(ui.messageList);
  const items = [...(conversation.items || [])]; if (optimistic && !items.some((item) => item.role === "user" && item.text === optimistic.text)) items.push({ kind: "message", role: "user", text: optimistic.text, time: optimistic.time, optimistic: true });
  items.forEach((item) => item.kind === "tool" ? renderTool(item) : renderMessage(item)); ui.conversationIntro.hidden = items.length > 0; renderPending(conversation.pending || []); ui.agentWorking.hidden = !conversation.running && !optimistic;
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
async function submitMessage(message) {
  const text = message.trim(); if (!text) return; hideNotice(); setButtonBusy(ui.sendButton, true, "…");
  try {
    if (!state.selectedTaskId) {
      const created = await request("/tasks", { method: "POST", json: { name: deriveTaskName(text), business_goal: text } }); state.tasks.unshift(created.task); clearDraft(null); ui.messageInput.value = ""; resizeComposer(); await selectTask(created.task.task_id);
      showNotice(created.task.capability_decision?.status === "needs_clarification" ? "任务已创建，但输出形式仍有歧义。请先提交澄清；系统尚未绑定训练方案。" : "任务已创建。请先检查并确认任务理解；确认前不会进入数据或训练。", "ok"); return;
    }
    if (!state.runtimeReady) { showNotice("这条自由对话需要 Agent Runtime；右侧的数据、合同与训练操作仍可直接使用。任务事实没有被伪造。"); return; }
    const taskId = state.selectedTaskId; state.pendingMessage = { task_id: taskId, text, time: Date.now() }; renderConversation(true); await request(`/tasks/${encodeURIComponent(taskId)}/conversation/messages`, { method: "POST", json: { message: text } }); clearDraft(taskId); if (state.selectedTaskId === taskId) { ui.messageInput.value = ""; resizeComposer(); } window.setTimeout(() => refreshSelected({ force: true }), 250);
  } catch (error) { if (state.pendingMessage?.task_id === state.selectedTaskId) state.pendingMessage = null; saveDraft(); renderConversation(true); showNotice(`${error.message}。任务事实不会被伪造。`); }
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
function retryRunDirect() {
  const taskId = state.selectedTaskId; const result = state.task?.current_result;
  if (!taskId || !result || !TERMINAL_RETRY_STATUSES.has(result.status)) { showNotice("只有失败、取消或中断的 Run 可以从这里重新训练；请先刷新任务状态。"); return; }
  openInspector("run");
  const reason = result.error || result.cancel_reason || "后端没有记录补充原因";
  openSimpleDialog({
    kicker: "保留旧 Run 证据", title: "基于同一冻结合同重新训练？",
    body: `旧 Run：${result.run_id}；状态：${result.status}；原因：${reason}。确认后会调用当前任务的启动接口创建一个新的 Run；旧事件、错误和产物不会被覆盖，页面也不会在后端返回前伪造运行状态。`,
    allowLabel: "保留证据并重新训练",
    onAllow: async () => {
      const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs`, { method: "POST" });
      const newRunId = response.task?.current_run_id;
      showNotice(newRunId ? `后端已创建新 Run ${shortId(newRunId)}；真实事件会持续刷新。` : "后端已接受重新训练请求；正在读取新 Run。", "ok");
      activateContext("run"); await refreshSelected({ force: true });
    },
  });
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

function openTaskSpecDialog({ editing = false } = {}) {
  const task = state.task; const spec = task?.task_spec; const decision = task?.capability_decision || {}; if (!spec) return;
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = editing ? "修订任务规格" : decision.status === "needs_clarification" ? "澄清模型输出" : "确认任务理解"; ui.dialogTitle.textContent = editing ? "修改任务描述或输出形式" : decision.question || "确认候选任务规格";
  const goalBlock = document.createElement("section"); goalBlock.className = "question-block"; const goalTitle = document.createElement("b"); goalTitle.textContent = "业务目标"; const goalInput = document.createElement("textarea"); goalInput.className = "question-custom"; goalInput.rows = 3; goalInput.value = spec.business_goal; goalInput.disabled = !editing; goalBlock.append(goalTitle, goalInput); ui.dialogBody.append(goalBlock);
  const familyBlock = document.createElement("section"); familyBlock.className = "question-block"; const familyTitle = document.createElement("b"); familyTitle.textContent = "模型唯一输出"; const options = document.createElement("div"); options.className = "question-options";
  const candidates = editing ? SPEC_FAMILIES : decision.candidates || [];
  candidates.forEach((candidate, index) => { const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = "task-spec-family"; input.value = candidate.family; input.checked = candidate.family === decision.selected_family || (!decision.selected_family && index === 0); const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = candidate.label; const detail = document.createElement("small"); detail.textContent = candidate.output; copy.append(name, detail); label.append(input, copy); options.append(label); });
  familyBlock.append(familyTitle, options); ui.dialogBody.append(familyBlock);
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => ui.decisionDialog.close());
  const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = editing ? "保存新版本" : decision.status === "needs_clarification" ? "提交澄清" : "确认任务理解";
  submit.addEventListener("click", async () => { const selected = options.querySelector("input:checked")?.value; if (!selected) { showNotice("请选择模型唯一输出形式。"); return; } if (!goalInput.value.trim()) { showNotice("业务目标不能为空。"); return; } setButtonBusy(submit, true, "保存中"); try { const response = await request(`/tasks/${encodeURIComponent(task.task_id)}/spec`, { method: "PATCH", json: { base_revision: spec.revision, selected_family: selected, business_goal: goalInput.value.trim(), confirm: true, user_note: editing ? "用户通过产品界面修订" : "用户通过产品界面确认" } }); ui.decisionDialog.close(); state.task = response.task; showNotice(response.task.status === "needs_recipe" ? "任务规格已确认，但当前没有已验证训练方案；系统不会伪造训练运行。" : `任务规格 v${response.task.current_spec_revision} 已保存，同一 task_id 保持不变。`, "ok"); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(submit, false, ""); } });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal();
}
async function stageRecipeSamples(file) {
  if (!file || !state.selectedTaskId) return;
  if (!file.name.toLowerCase().endsWith(".zip")) { showNotice("Recipe 构建样例必须是按类别目录整理的 WAV ZIP。"); ui.recipeSampleInput.value = ""; return; }
  setButtonBusy(ui.nextActionButton, true, "正在校验样例");
  try {
    await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/staged-assets`, {
      method: "POST", body: file,
      headers: { "content-type": "application/zip", "x-filename": encodeURIComponent(file.name), "x-spec-revision": String(state.task.current_spec_revision) },
    });
    showNotice("样例 ZIP 已隔离保存并通过安全检查；它没有被导入为正式训练数据。", "ok");
    openInspector("capability"); await refreshSelected({ force: true });
  } catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.nextActionButton, false, ""); ui.recipeSampleInput.value = ""; }
}
function startRecipeBuild() {
  openSimpleDialog({
    kicker: "构建可信训练能力", title: "生成并验证语音关键词 Recipe？",
    body: "系统只接受受约束的 RecipeSpec JSON，并映射到内置可信音频引擎。任何 Python、Shell、依赖或远程 URL 都会被阻断且不会执行。",
    allowLabel: "生成并验证",
    onAllow: async () => {
      const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/recipe-builds`, { method: "POST", json: {} });
      showNotice(result.build_attempt.status === "awaiting_registration" ? "Recipe 声明已通过验证；仍需核对摘要并明确批准注册。" : `构建结果：${result.build_attempt.status}`, result.build_attempt.status === "awaiting_registration" ? "ok" : "error");
      openInspector("capability"); await refreshSelected({ force: true });
    },
  });
}
function approveRecipeRegistration() {
  const build = state.task?.current_recipe_build;
  if (!build?.candidate_digest || !build?.validation_digest) { showNotice("缺少可核验的候选或验证摘要，不能注册。"); return; }
  openSimpleDialog({
    kicker: "注册版本化能力", title: "批准本次 Recipe / Data Adapter 注册？",
    body: `Build ${shortId(build.attempt_id)} 已通过声明式验证。Candidate SHA：${shortId(build.candidate_digest)}；Validation SHA：${shortId(build.validation_digest)}。批准后只绑定当前 task_id，不会创建 Run。`,
    allowLabel: "核对并批准注册",
    onAllow: async () => {
      await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/recipe-builds/${encodeURIComponent(build.attempt_id)}/register`, {
        method: "POST", json: { decision: "approved", actor: "local-user", reason: "approved in Model Harness UI", candidate_digest: build.candidate_digest, validation_digest: build.validation_digest },
      });
      showNotice("版本化 Recipe / Data Adapter 已注册；原任务现在可以导入正式训练数据。", "ok");
      await refreshSelected({ force: true });
    },
  });
}
function performNextAction() {
  const action = state.task?.control?.next_action?.id;
  if (["clarify_task_spec", "confirm_task_spec"].includes(action)) { openTaskSpecDialog(); return; }
  if (action === "upload_dataset") { ui.datasetInput.click(); return; }
  if (action === "stage_recipe_samples") { ui.recipeSampleInput.click(); return; }
  if (action === "start_recipe_build") { startRecipeBuild(); return; }
  if (action === "approve_recipe_registration") { approveRecipeRegistration(); return; }
  if (action === "review_capability_gap") { openInspector("capability"); return; }
  if (action === "confirm_training_contract") { openInspector("data"); return; }
  if (action === "start_training_run") { startRunDirect(); return; }
  if (action === "retry_training_run") { retryRunDirect(); return; }
  if (action === "view_run_progress" || action === "inspect_run_failure") { openInspector("run"); return; }
  if (action === "review_evaluation") { openInspector("evaluation"); return; }
  ui.taskSpecCard?.scrollIntoView({ behavior: "smooth", block: "center" });
}
function cancelRun() {
  const taskId = state.selectedTaskId; const runId = state.task?.current_run_id; if (!taskId || !runId) return;
  openSimpleDialog({ kicker: "只取消训练 Run", title: "请求取消本次训练？", body: "取消请求会在当前阶段边界生效。它不会停止 Agent 对话，也不会删除已经写入的事件和证据。", allowLabel: "请求取消训练", onAllow: async () => { const result = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }); showNotice(result.cancel_requested ? "取消请求已提交；后端将在当前阶段边界停止。" : "该运行已经结束，无需再次取消。", "ok"); await refreshSelected({ force: true }); } });
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
  if (state.task?.capability_decision?.status !== "resolved") { showNotice("请先澄清并确认任务理解；确认前不会导入数据或启动训练。"); return; }
  if (state.task?.status === "needs_recipe") { showNotice("当前能力还没有可执行 Recipe。请先完成并注册 Recipe / Data Adapter。"); return; }
  const lower = file?.name.toLowerCase() || ""; if (!lower.endsWith(".zip") && !lower.endsWith(".csv")) { showNotice("当前已注册的 Data Adapter 接受类别目录 ZIP 或 CSV；其他格式需要经过能力构建与注册。"); return; }
  if (lower.endsWith(".csv") && !options.targetColumn) { askCsvOptions(file); return; }
  hideNotice(); setButtonBusy(ui.datasetButton, true, "体检中");
  const headers = { "content-type": lower.endsWith(".csv") ? "text/csv" : "application/zip", "x-filename": encodeURIComponent(file.name) };
  if (options.targetColumn) headers["x-target-column"] = encodeURIComponent(options.targetColumn);
  if (options.ignoredColumns) headers["x-ignored-columns"] = options.ignoredColumns.split(",").map((value) => encodeURIComponent(value.trim())).filter(Boolean).join(",");
  if (options.delimiter) headers["x-delimiter"] = encodeURIComponent(options.delimiter);
  try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/dataset`, { method: "POST", body: file, headers }); showNotice("后端已真实导入数据并完成体检。", "ok"); activateContext("data"); await refreshSelected({ force: true }); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.datasetButton, false, ""); ui.datasetInput.value = ""; }
}
async function confirmContract() {
  const fields = [...ui.confirmations.querySelectorAll("input")]; if (fields.some((field) => !field.checked)) { showNotice("请明确勾选数据授权、标签/目标字段和验收门槛三项确认。"); return; }
  setButtonBusy(ui.confirmContractButton, true, "确认中");
  try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/confirm`, { method: "POST", json: Object.fromEntries(fields.map((field) => [field.dataset.confirm, true])) }); showNotice("训练合同已经真实冻结。", "ok"); await refreshSelected({ force: true }); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.confirmContractButton, false, ""); }
}
function activateContext(name) { document.querySelectorAll("[data-context]").forEach((button) => button.classList.toggle("active", button.dataset.context === name)); document.querySelectorAll("[data-context-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.contextPanel === name)); ui.inspectorSheetTitle.textContent = ["evaluation", "artifacts"].includes(name) ? "训练结果" : "任务上下文"; }
function setMobileView(name) { [ui.mobileConversationButton, ui.mobileContextButton, ui.mobileResultButton].forEach((button) => { const active = button.dataset.mobileView === name; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); }
function openInspector(context = "capability") { activateContext(context); if (window.matchMedia("(max-width: 720px)").matches) { ui.inspector.dataset.mobileOpen = "true"; ui.inspectorScrim.hidden = false; setMobileView(["evaluation", "artifacts"].includes(context) ? "result" : "context"); } }
function closeInspector() { ui.inspector.dataset.mobileOpen = "false"; ui.inspectorScrim.hidden = true; setMobileView("conversation"); }
function openSidebar() { ui.sidebar.dataset.open = "true"; ui.sidebarScrim.hidden = false; }
function closeSidebar() { ui.sidebar.dataset.open = "false"; ui.sidebarScrim.hidden = true; }
function stopPolling() { if (state.pollTimer) window.clearInterval(state.pollTimer); state.pollTimer = null; }
function resizeComposer() { ui.messageInput.style.height = "auto"; ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 140)}px`; }

ui.composerForm.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(ui.messageInput.value); });
ui.messageInput.addEventListener("input", () => { resizeComposer(); saveDraft(); });
ui.messageInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composerForm.requestSubmit(); } });
ui.newTaskButton.addEventListener("click", openNewTask); ui.refreshButton.addEventListener("click", () => state.selectedTaskId ? refreshSelected({ force: true }) : loadTasks());
ui.menuButton.addEventListener("click", openSidebar); ui.sidebarScrim.addEventListener("click", closeSidebar);
ui.datasetButton.addEventListener("click", () => state.selectedTaskId ? ui.datasetInput.click() : showNotice("先用一句话创建训练任务，再导入数据。")); ui.inspectorDatasetButton.addEventListener("click", () => ui.datasetInput.click()); ui.datasetInput.addEventListener("change", () => uploadDataset(ui.datasetInput.files?.[0])); ui.recipeSampleInput.addEventListener("change", () => stageRecipeSamples(ui.recipeSampleInput.files?.[0]));
ui.confirmContractButton.addEventListener("click", confirmContract);
ui.hfSearchForm.addEventListener("submit", searchHfModels); ui.hfAttachButton.addEventListener("click", attachHfModel); ui.modelAssetVerifyButton.addEventListener("click", verifyModelAsset);
ui.refreshEvaluationButton.addEventListener("click", refreshEvaluation); ui.sampleTrialSelectButton.addEventListener("click", () => ui.sampleTrialInput.click());
ui.sampleTrialInput.addEventListener("change", () => state.task && renderResult(state.task)); ui.sampleTrialRunButton.addEventListener("click", runSampleTrial); ui.buildArtifactBundleButton.addEventListener("click", buildArtifactBundle);
ui.nextActionButton.addEventListener("click", performNextAction); ui.taskBlockerActionButton.addEventListener("click", performNextAction);
ui.confirmTaskSpecButton.addEventListener("click", () => openTaskSpecDialog()); ui.editTaskSpecButton.addEventListener("click", () => openTaskSpecDialog({ editing: true }));
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
  if (TERMINAL_RETRY_STATUSES.has(state.task?.current_result?.status)) { retryRunDirect(); return; }
  if (state.task?.current_run_id && state.task.status !== "ready") { openInspector("evaluation"); return; }
  startRunDirect();
});
ui.cancelAgentButton.addEventListener("click", () => openSimpleDialog({ kicker: "只停止 Agent", title: "停止当前 Agent 回合？", body: "这只会停止智能协作服务的当前回合，不会取消正在执行的训练 Run。", allowLabel: "停止 Agent", onAllow: async () => { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/cancel`, { method: "POST" }); showNotice("Agent 回合已停止；训练 Run 状态未被修改。", "ok"); await refreshSelected({ force: true }); } }));
ui.cancelRunButton.addEventListener("click", cancelRun);
ui.retryRunButton.addEventListener("click", retryRunDirect);
ui.contextTabs.addEventListener("click", (event) => { const button = event.target.closest("[data-context]"); if (button) activateContext(button.dataset.context); });
ui.closeInspectorButton.addEventListener("click", closeInspector); ui.inspectorScrim.addEventListener("click", closeInspector);
ui.mobileConversationButton.addEventListener("click", closeInspector); ui.mobileContextButton.addEventListener("click", () => openInspector("capability")); ui.mobileResultButton.addEventListener("click", () => openInspector("evaluation"));
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { ui.messageInput.value = button.dataset.prompt; resizeComposer(); ui.messageInput.focus(); }));

async function boot() { restoreDraft(null); await Promise.all([loadRuntime(), loadHfCapability(), loadTasks({ selectFromUrl: true })]); resizeComposer(); }
boot().catch((error) => showNotice(`页面初始化失败：${error.message}`));
