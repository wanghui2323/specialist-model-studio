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
  "sidebar", "sidebarScrim", "menuButton", "newTaskButton", "refreshButton", "taskList", "taskEyebrow", "taskTitle", "runtimePill", "conversationMain",
  "taskPlan", "taskPlanTitle", "taskPlanProgress", "emptyState", "conversation", "conversationIntro", "messageList",
  "workspaceToggleButton", "agentCheckpoint", "agentCheckpointStage", "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointSummary", "agentCheckpointBody", "agentCheckpointActions", "agentCheckpointWorkspaceButton", "agentCheckpointWorkspaceLabel", "agentCheckpointWorkspaceHint", "homeComposerSlot", "homeBoundary", "homeTrainingProof", "composerWrap",
  "runEventList", "pendingZone", "agentWorking", "cancelAgentButton", "composerForm", "composerNotice", "messageInput", "sendButton", "composerMode", "composerModeLabel",
  "datasetButton", "datasetInput", "recipeSampleInput", "inspectorDatasetButton", "inspectorEmpty", "inspectorContent", "taskStatus", "contextTabs",
  "stageList", "capabilityState", "capabilitySummary", "capabilityFacts", "datasetCard", "datasetCount", "datasetSummary", "contractCard", "contractState",
  "scaffoldRecipeButton",
  "gateGrid", "confirmations", "confirmContractButton", "startThroughAgentButton", "runEventCount", "inspectorEvents", "resultCard",
  "gateResult", "metricGrid", "runId", "artifactCount", "artifactList", "decisionDialog", "dialogKicker", "dialogTitle", "dialogBody", "dialogActions",
  "taskControlPanel", "nextActionCard", "currentStageLabel", "currentStageState", "nextActionLabel", "nextActionDescription", "nextActionButton",
  "taskBlocker", "taskBlockerTitle", "taskBlockerDescription", "taskBlockerActionButton", "taskSpecCard", "taskSpecHeading", "taskSpecStatus",
  "taskSpecVersion", "taskSpecSummary", "taskSpecFacts", "taskSpecInput", "taskSpecObjective", "taskSpecOutput", "taskSpecConstraints", "taskSpecClarification",
  "taskSpecClarificationTitle", "taskSpecClarificationDescription", "taskSpecQuickReplies", "editTaskSpecButton", "confirmTaskSpecButton", "inspector", "inspectorSheetTitle",
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
  "modelSourceCard", "modelSourceState", "modelSourceSummary", "modelSourceBlocker", "modelSourceBlockerTitle", "modelSourceBlockerMessage",
  "modelSourceRetryButton", "modelSourceBinding", "modelSourceFacts", "modelSourceFiles", "modelSourceFileList", "modelSourcePending",
  "pendingSourceRepo", "pendingRequestedRevision", "pendingResolvedCommit", "pendingSourceLicense", "bindModelSourceButton", "cancelModelBindingButton", "modelSourceDiscovery",
  "modelSourceDiscoverySummary", "sourceModeTabs", "modelSourceSearchForm", "modelSourceSearchInput", "searchHfProvider", "searchGithubProvider",
  "modelSourceSearchButton", "modelSourceReferenceForm", "modelSourceReferenceInput", "modelSourceRevisionInput", "modelSourceResolveButton",
  "modelSourceHfToken", "modelSourceGithubToken", "modelSourceSearchEvidence", "modelSourceCandidates",
  "modelSourceCheckpointCard", "modelSourceCheckpointFacts", "modelSourceCheckpointBoundary", "modelSourceCheckpointCandidates", "viewAllModelSourceCandidatesButton",
  "repositoryAnalysisCard", "repositoryAnalysisState", "repositoryAnalysisSummary", "repositoryAnalysisFacts", "repositoryAnalysisEvidence",
  "repositoryAnalysisEvidenceList", "repositoryAnalysisRiskPanel", "repositoryAnalysisRiskList", "repositoryManualMapping", "repositoryManualEntrypointInput",
  "repositoryDatasetArgumentInput", "applyRepositoryManualMappingButton", "trainingPlanCard", "trainingPlanState", "trainingPlanSummary", "manualEntrypointField",
  "manualEntrypointInput", "trainingPlanFacts", "createTrainingPlanButton", "approveTrainingPlanButton", "trainingPlanDecisionActions", "rejectTrainingPlanButton", "cancelTrainingPlanButton",
  "resourceFeasibilityCard", "resourceFeasibilityState", "resourceFeasibilitySummary", "resourceFeasibilityFacts", "baseImageDigestField",
  "baseImageDigestInput", "resourceFeasibilityReasons", "checkResourceFeasibilityButton",
].map((id) => [id, document.getElementById(id)]));
const state = {
  tasks: [], task: null, selectedTaskId: null, conversation: null, runEvents: [], runtimeReady: false, pollTimer: null,
  pendingMessage: null, lastRenderKey: "", selectionToken: 0, hfCapability: null, hfModels: [], hfCard: null,
  modelAssetVerification: null, evidenceRunId: null, evidenceLoaded: false, evaluationReport: null, sampleInferences: [], artifactBundles: [],
  refreshInFlight: false, refreshSeq: 0,
  evidenceErrors: {},
  modelSourceProviders: [], modelSourceCandidates: [], modelSourceResolutions: [], modelSourceSearches: [], modelSourceSearch: null, modelSourceMode: "search", modelSourceOperationSeq: 0, modelSourceLoadedTaskId: null, modelSourceCandidateRenderKey: "", modelSourceCheckpointRenderKey: "", modelSourceSearchInFlight: false,
  checkpointCard: null, workspaceAutoKey: null, inspectorOpener: null, productRuntime: null, taskSpecFamilies: [], taskSpecFamiliesError: null, taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false,
};
const checkpointCards = [ui.taskSpecCard, ui.capabilityCard, ui.modelSourceCheckpointCard, ui.modelSourceCard, ui.repositoryAnalysisCard, ui.trainingPlanCard, ui.resourceFeasibilityCard, ui.datasetCard, ui.contractCard].filter(Boolean);
const checkpointHomes = new Map();
const planPanel = document.querySelector('[data-context-panel="plan"]');
if (planPanel && ui.taskSpecCard) planPanel.prepend(ui.taskSpecCard);
checkpointCards.forEach((card) => {
  const marker = document.createComment(`checkpoint-home:${card.id}`);
  card.parentNode?.insertBefore(marker, card);
  checkpointHomes.set(card, marker);
});
const DraftStore = window.ModelHarnessDraftStore;
const STAGE_LABELS = {
  task_understanding: "确认任务理解", capability_resolution: "解决能力缺口", data_preparation: "准备训练数据",
  contract_review: "审阅训练合同", ready_to_run: "准备启动训练", evaluation: "审阅评测结果", run_recovery: "处理运行异常",
  source_discovery: "查找模型来源", source_resolution: "确认固定版本", source_snapshot: "读取来源清单", repository_analysis: "审阅仓库分析",
  training_plan: "确认训练计划", resource_probe: "检查本机资源", environment_lock: "冻结训练环境", resource_fit: "判断训练可行性",
};
const LIFECYCLE_STEPS = ["定义任务", "检查数据", "确认合同", "训练评测", "优化交付"];
const IMMUTABLE_COMMIT = /^[0-9a-f]{40}$/;
const HF_CHECK_LABELS = {
  known_license: "许可证明确", onnx_payload: "包含 ONNX", preprocess_config: "包含预处理配置",
  local_cpu_runtime: "本机 CPU Runtime", within_local_size_budget: "符合本地大小预算", image_classification_tag: "图像分类标签",
};
const EVIDENCE_STATUS_LABELS = {
  completed: "已完成", completed_empty: "已完成，无匹配", failed: "失败", cancelled: "已取消", interrupted: "已中断", running: "运行中",
  passed: "通过", sufficient: "充分", release_ready: "可交付", quality_failed: "质量未达标",
  integrity_failed: "完整性失败", insufficient_evidence: "证据不足", metrics_missing: "缺少指标", run_incomplete: "运行未完成",
  not_evaluated: "未评测", unknown: "未知",
};
const INSPECTOR_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])';
const inspectorMedia = window.matchMedia("(max-width:720px)");
const dockedWorkspaceMedia = window.matchMedia("(min-width:1184px)");

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
function formatRelativeTime(value) {
  const date = new Date(value); if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} 天前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}
function shortId(value) { return value && value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value || "—"; }
function showNotice(message, tone = "error") { ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = tone; ui.composerNotice.textContent = message; }
function hideNotice() { ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }
function setButtonBusy(button, busy, busyText) { if (!button.dataset.label) button.dataset.label = button.textContent; button.disabled = busy; button.textContent = busy ? busyText : button.dataset.label; }
function formatBytes(value) { if (!Number.isFinite(value)) return "大小未知"; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`; if (value < 1024 ** 4) return `${(value / 1024 ** 3).toFixed(1)} GB`; return `${(value / 1024 ** 4).toFixed(1)} TB`; }
function fixedCommit(value) { return typeof value === "string" && IMMUTABLE_COMMIT.test(value.toLowerCase()); }
function statusLabel(value) { return EVIDENCE_STATUS_LABELS[value] || String(value || "未知"); }
function workflowStatus(task) {
  if (["running", "completed", "failed", "cancelled", "interrupted"].includes(task.status)) return { label: STATUS_LABELS[task.status] || task.status, tone: task.status };
  const stage = task.control?.current_stage; const blocked = task.control?.blocked_by?.[0]; const analysisStatus = task.repository_analysis?.status; const planStatus = task.training_plan?.effective_status;
  if (stage === "task_understanding") return { label: task.capability_decision?.status === "needs_confirmation" ? "等待确认" : "等待澄清", tone: "needs_clarification" };
  if (stage === "capability_resolution" || stage === "source_discovery") return { label: "选择模型来源", tone: "needs_recipe" };
  if (stage === "source_resolution") return { label: "确认模型来源", tone: "needs_confirmation" };
  if (stage === "source_snapshot") return { label: "读取来源清单", tone: "needs_confirmation" };
  if (stage === "repository_analysis") return { label: analysisStatus === "blocked" ? "分析已阻断" : ["needs_input", "needs_manual_mapping"].includes(analysisStatus) ? "等待分析映射" : "审阅仓库分析", tone: analysisStatus === "blocked" ? "failed" : "needs_confirmation" };
  if (stage === "training_plan") return { label: planStatus === "awaiting_approval" ? "等待计划批准" : planStatus === "approved" ? "计划已批准" : "生成训练计划", tone: "needs_confirmation" };
  if (stage === "resource_probe") return { label: "等待资源检查", tone: "needs_confirmation" };
  if (stage === "environment_lock") return { label: blocked ? "训练环境阻断" : "冻结训练环境", tone: blocked ? "failed" : "needs_confirmation" };
  if (stage === "resource_fit") return { label: blocked ? "资源证据不足" : "静态预算匹配", tone: blocked ? "failed" : "ready" };
  return { label: STATUS_LABELS[task.status] || task.status || "未知", tone: task.status || "draft" };
}
function statusTone(value) {
  if (["completed", "passed", "sufficient", "release_ready"].includes(value)) return "passed";
  if (["failed", "cancelled", "interrupted", "integrity_failed", "quality_failed"].includes(value)) return "failed";
  if (["insufficient_evidence", "metrics_missing", "run_incomplete", "not_evaluated"].includes(value)) return "warning";
  return "neutral";
}
function hfHeaders() { const token = ui.hfTokenInput.value.trim(); return token ? { "X-HF-Token": token } : {}; }
function modelSourceHeaders(provider = null) {
  const headers = {}; const hfToken = ui.modelSourceHfToken.value.trim(); const githubToken = ui.modelSourceGithubToken.value.trim();
  if ((!provider || provider === "huggingface") && hfToken) headers["X-HF-Token"] = hfToken;
  if ((!provider || provider === "github") && githubToken) headers["X-GitHub-Token"] = githubToken;
  return headers;
}
function clearModelSourceTokens() { ui.modelSourceHfToken.value = ""; ui.modelSourceGithubToken.value = ""; }
function isImageClassificationTask(task) {
  const capability = task?.task_spec?.capability_request || task?.capability_request || {};
  return capability.modality === "image" && capability.objective === "classification";
}
function resetHfDiscovery({ clearToken = true } = {}) {
  state.hfModels = []; state.hfCard = null; state.modelAssetVerification = null; clear(ui.hfSearchResults); ui.hfModelCard.hidden = true;
  if (clearToken) ui.hfTokenInput.value = "";
}
function resetModelSourceDiscovery({ clearTokens = true } = {}) {
  state.modelSourceCandidates = []; state.modelSourceResolutions = []; state.modelSourceSearches = []; state.modelSourceSearch = null; state.modelSourceMode = "search"; state.modelSourceOperationSeq += 1; state.modelSourceLoadedTaskId = null; state.modelSourceCandidateRenderKey = ""; state.modelSourceCheckpointRenderKey = ""; state.modelSourceSearchInFlight = false;
  clear(ui.modelSourceCandidates); clear(ui.modelSourceCheckpointCandidates); ui.modelSourceCheckpointCard.hidden = true; ui.modelSourceSearchInput.value = ""; ui.modelSourceReferenceInput.value = ""; ui.modelSourceRevisionInput.value = ""; ui.manualEntrypointInput.value = ""; ui.baseImageDigestInput.value = ""; ui.repositoryManualEntrypointInput.value = ""; ui.repositoryDatasetArgumentInput.value = "";
  if (clearTokens) clearModelSourceTokens();
}
function resetRunEvidence(runId = null) {
  state.evidenceRunId = runId; state.evidenceLoaded = false; state.evaluationReport = null; state.sampleInferences = []; state.artifactBundles = []; state.evidenceErrors = {};
  ui.sampleTrialInput.value = ""; ui.sampleTrialJson.value = "";
}
function draftId(taskId = state.selectedTaskId) { return taskId || DraftStore?.NEW_TASK || "__new__"; }
function saveDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.write(localStorage, draftId(taskId), ui.messageInput.value); }
function restoreDraft(taskId = state.selectedTaskId) { ui.messageInput.value = DraftStore ? DraftStore.read(localStorage, draftId(taskId)).text : ""; resizeComposer(); }
function clearDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.clear(localStorage, draftId(taskId)); }

function renderRuntimeMode(mode) {
  const ready = mode === "agent";
  const checking = mode === "checking";
  const pillText = checking ? "正在检查 Agent Runtime" : ready ? "Agent Runtime 已连接" : "本地流程模式 · 训练操作仍可用";
  const composerText = checking ? "正在确认协作模式" : ready ? "Agent 协作已连接" : "本地流程模式 · 训练操作可用";
  ui.runtimePill.dataset.state = checking ? "checking" : ready ? "ready" : "error";
  ui.runtimePill.querySelector("span").textContent = pillText; ui.runtimePill.title = pillText; ui.runtimePill.setAttribute("aria-label", pillText);
  ui.composerMode.dataset.state = checking ? "checking" : ready ? "agent" : "local"; ui.composerModeLabel.textContent = composerText; ui.composerMode.title = ready ? "自由对话与本地训练操作均可用" : checking ? composerText : "需求快捷选项、模型搜索、数据导入、合同确认和训练操作仍可用；自由对话需要 Agent Runtime";
}
function renderProductBoundary() {
  const byomExecutionAvailable = state.productRuntime?.byom_execution_available === true;
  if (ui.homeBoundary) ui.homeBoundary.textContent = byomExecutionAvailable
    ? "不需要先会训练。我会先聊清需求，再联网匹配公开模型、准备数据，并在可验证的隔离边界内训练和评测。"
    : "不需要先会训练。我会先聊清需求，再联网匹配公开模型并判断本机可行性。已验证 Recipe 可以真实训练；其他仓库当前会停在可审查的分析或阻断，不会伪造已支持。";
  if (ui.homeTrainingProof) {
    ui.homeTrainingProof.lastChild.textContent = byomExecutionAvailable ? "隔离 BYOM 与 Recipe 真实训练" : "已验证 Recipe 可真实训练";
  }
}
async function loadRuntime() {
  renderRuntimeMode("checking");
  try {
    state.productRuntime = await request("/runtime");
    state.runtimeReady = state.productRuntime.agent?.available === true;
  } catch (_runtimeError) {
    state.productRuntime = null;
    try { state.runtimeReady = (await request("/agent/runtime")).available === true; } catch (_agentError) { state.runtimeReady = false; }
  }
  renderProductBoundary();
  renderRuntimeMode(state.runtimeReady ? "agent" : "local");
}
async function loadHfCapability() {
  try { state.hfCapability = await request("/model-assets/huggingface/capability"); }
  catch (error) { state.hfCapability = { available: false, provider: "huggingface", reason: error.message }; }
  if (state.task) renderModelAsset(state.task);
}
async function loadModelSourceProviders() {
  try { state.modelSourceProviders = (await request("/model-sources/providers")).providers || []; }
  catch (_error) { state.modelSourceProviders = []; }
  if (state.task) renderModelSource(state.task);
}
async function loadTaskSpecFamilies() {
  try { state.taskSpecFamilies = (await request("/task-spec/families")).families || []; state.taskSpecFamiliesError = null; return true; }
  catch (error) { state.taskSpecFamilies = []; state.taskSpecFamiliesError = error.message; return false; }
}
async function loadTasks({ selectFromUrl = false } = {}) {
  state.tasks = (await request("/tasks")).tasks || []; renderTaskList();
  if (selectFromUrl && !state.selectedTaskId) {
    const requested = new URL(location.href).searchParams.get("task");
    if (!requested) { enterHomeState({ focusComposer: false }); return; }
    if (state.tasks.some((task) => task.task_id === requested)) { await selectTask(requested); return; }
    enterHomeState({ focusComposer: false });
    showNotice(`找不到训练任务 ${requested}。没有替你打开其他任务，请从左侧明确选择或新建任务。`);
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
    const workflow = workflowStatus(task); const status = document.createElement("span"); const dot = document.createElement("i"); dot.dataset.status = workflow.tone; status.append(dot, document.createTextNode(workflow.label));
    const capability = task.model_binding ? `已固定 ${modelSourceProviderLabel(task.model_binding.provider)} 来源` : task.recipe_id ? "已匹配本地训练方案" : "等待确认训练方案";
    const facts = document.createElement("span"); facts.className = "task-facts"; facts.textContent = task.dataset_report ? `${capability} · 数据已导入` : capability;
    const time = document.createElement("time"); time.dateTime = task.updated_at_utc || ""; time.textContent = formatRelativeTime(task.updated_at_utc); meta.append(status, time, facts);
    button.append(title, meta);
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
function enterHomeState({ focusComposer = true } = {}) {
  history.replaceState(null, "", location.pathname); document.body.dataset.view = "home"; ui.homeComposerSlot.append(ui.composerWrap); ui.taskPlan.hidden = true; ui.emptyState.hidden = false; ui.conversation.hidden = true;
  ui.taskControlPanel.hidden = true; ui.inspector.hidden = true; ui.workspaceToggleButton.hidden = true; ui.mobileViewNav.hidden = true; ui.agentCheckpoint.hidden = true; ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.taskEyebrow.textContent = "SPECIALIST MODEL STUDIO"; ui.taskTitle.textContent = "开始一个训练任务";
  ui.messageInput.placeholder = "告诉我，你想让模型学会什么？"; restoreDraft(null); renderTaskList(); closeSidebar(); closeInspector(); if (focusComposer) ui.messageInput.focus();
}
function openNewTask() {
  saveDraft(); stopPolling(); state.selectionToken += 1; Object.assign(state, { selectedTaskId: null, task: null, conversation: null, runEvents: [], pendingMessage: null, lastRenderKey: "", taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false });
  restoreCheckpointCard(); state.workspaceAutoKey = null;
  resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence();
  enterHomeState();
}
async function selectTask(taskId) {
  if (taskId !== state.selectedTaskId) { saveDraft(); restoreCheckpointCard(); resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence(); state.workspaceAutoKey = null; state.taskSpecRevisions = []; state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; }
  stopPolling(); hideNotice(); const token = ++state.selectionToken; state.selectedTaskId = taskId; state.lastRenderKey = ""; state.pendingMessage = state.pendingMessage?.task_id === taskId ? state.pendingMessage : null; history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  document.body.dataset.view = "task"; ui.conversationMain.append(ui.composerWrap); renderTaskList(); ui.taskPlan.hidden = true; ui.emptyState.hidden = true; ui.conversation.hidden = false; ui.inspector.hidden = false; ui.workspaceToggleButton.hidden = false; ui.mobileViewNav.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false; closeSidebar(); closeInspector();
  restoreDraft(taskId); await refreshSelected({ force: true, token }); if (state.selectedTaskId === taskId && state.selectionToken === token) state.pollTimer = window.setInterval(() => refreshSelected(), 1400);
}
async function refreshSelected({ force = false, token = state.selectionToken } = {}) {
  const taskId = state.selectedTaskId; if (!taskId || token !== state.selectionToken) return;
  if (state.refreshInFlight && !force) return;
  const seq = ++state.refreshSeq; state.refreshInFlight = true;
  try {
    try {
      const previousSpecRevision = state.task?.task_id === taskId ? state.task.current_spec_revision : null;
      const response = await request(`/tasks/${encodeURIComponent(taskId)}`); if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return; state.task = response.task;
      const sourceStage = ["capability_resolution", "source_discovery", "source_resolution", "source_snapshot", "repository_analysis"].includes(response.task.control?.current_stage);
      const specChanged = previousSpecRevision !== null && previousSpecRevision !== response.task.current_spec_revision;
      if (force || state.modelSourceLoadedTaskId !== taskId || specChanged || (sourceStage && !state.modelSourceSearchInFlight)) {
        try {
          const [sourceResponse, searchResponse, specResponse] = await Promise.all([
            request(`/tasks/${encodeURIComponent(taskId)}/model-source-resolutions`),
            request(`/tasks/${encodeURIComponent(taskId)}/model-source-searches`),
            request(`/tasks/${encodeURIComponent(taskId)}/spec/revisions`),
          ]);
          if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
          state.modelSourceResolutions = sourceResponse.resolutions || []; state.modelSourceSearches = searchResponse.searches || []; state.taskSpecRevisions = specResponse.revisions || [];
          const failedSearch = modelSourceBlocker(response.task)?.stage === "source_discovery";
          const latestSearch = [...state.modelSourceSearches]
            .filter((item) => item.base_spec_revision === response.task.current_spec_revision)
            .sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")) || String(left.search_id || "").localeCompare(String(right.search_id || "")))
            .at(-1) || null;
          state.modelSourceSearch = failedSearch ? null : latestSearch;
          state.modelSourceCandidates = failedSearch ? [] : [...(latestSearch?.candidates || [])];
          state.modelSourceLoadedTaskId = taskId;
        } catch (_error) { state.modelSourceResolutions = []; state.modelSourceSearches = []; state.modelSourceSearch = null; state.modelSourceCandidates = []; state.taskSpecRevisions = response.task.task_spec ? [response.task.task_spec] : []; state.modelSourceLoadedTaskId = taskId; }
      }
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
        state.runtimeReady = true; renderRuntimeMode("agent");
      }
    } catch (error) {
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      if (error.status === 503) { state.runtimeReady = false; state.conversation = null; renderRuntimeMode("local"); }
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
  const workflow = workflowStatus(task); ui.taskEyebrow.textContent = `${stageLabel(stageKey(task))} · ${workflow.label}`; ui.taskTitle.textContent = task.name; ui.taskStatus.textContent = workflow.label; ui.taskStatus.dataset.status = workflow.tone;
  renderControl(task); renderTaskSpec(task); renderPlan(task); renderStages(task); renderCapability(task); renderModelSource(task); renderRepositoryAnalysis(task); renderTrainingPlan(task); renderResourceFeasibility(task); renderModelAsset(task); renderDataset(task); renderContract(task); renderResult(task); renderRunEvents(); renderRunControl(task);
  syncAgentCheckpoint(task); syncWorkspaceForTask(task);
  const actionLabel = ["clarify_task_spec", "confirm_task_spec"].includes(task.control?.next_action?.id) ? "确认任务理解" : task.control?.next_action?.label;
  ui.messageInput.placeholder = state.taskSpecDescriptionMode && stageKey(task) === "task_understanding" ? "直接描述模型接收什么、应该输出什么…" : actionLabel ? `你也可以继续补充：${actionLabel}…` : "继续询问或补充任务信息…";
}
function stageKey(task) { return task.control?.current_stage || "task_understanding"; }
function stageLabel(value) { if (value?.startsWith("run_")) return "训练与评测"; return STAGE_LABELS[value] || value || "确认任务理解"; }
function planState(task) {
  const current = stageKey(task);
  if (["task_understanding", "capability_resolution", "source_discovery", "source_resolution", "source_snapshot", "repository_analysis"].includes(current)) return 1;
  if (current === "data_preparation") return 2;
  if (current === "contract_review") return 3;
  if (current === "ready_to_run" || current.startsWith("run_")) return 4;
  return 5;
}
function nextActionDescription(action, blocked) {
  if (blocked?.message) return blocked.message;
  const descriptions = {
    upload_dataset: "导入与任务规格匹配的数据，后端会执行真实体检。", review_capability_gap: "先联网选择模型或训练仓库；也可以查看仍缺失的训练能力。",
    confirm_training_contract: "确认数据授权、标签或目标字段与离线验收门槛。", start_training_run: "启动后端真实训练，并持续记录事件、指标与产物。",
    view_run_progress: "查看当前 Run 的真实状态；页面不会用动画模拟训练进度。", review_evaluation: "检查独立评测、失败样本与可追溯模型产物。",
    inspect_run_failure: "先阅读失败、取消或中断证据，再决定是否恢复。", retry_training_run: "旧 Run 的状态、错误和事件会保留；确认后由后端基于同一冻结合同创建新的 Run。", clarify_task_spec: "明确模型唯一输出，系统才会匹配训练能力。",
    confirm_task_spec: "确认系统对输入、目标与输出的理解后再检查数据。",
    stage_recipe_samples: "上传少量按类别整理的 PCM WAV 样例 ZIP；样例只用于构建能力，不会被当成正式训练数据。",
    start_recipe_build: "生成受约束的 RecipeSpec，并由可信音频引擎执行白名单、安全边界和版本校验。",
    approve_recipe_registration: "核对候选声明与两个摘要哈希；明确批准后才会把 Recipe / Data Adapter 绑定到当前任务。",
    search_model_sources: "从 Hugging Face 与 GitHub 官方目录查找候选，人工确认后再固定版本。", approve_model_source_binding: "核对请求版本、固定 commit 与许可证；批准后才读取有限仓库清单。", replace_model_source: "当前绑定已因 TaskSpec 更新失效，需要重新选择来源。", review_repository_analysis: "查看固定 commit 的静态分析、代码风险和下一步缺口。", retry_model_source_search: "重试官方目录搜索，失败事实仍保留在当前任务。", edit_or_retry_model_source: "修改地址、权限或版本后在同一任务重试。", retry_model_source_binding: "重新读取固定 commit 的完整文件清单。", review_or_retry_repository_analysis: "检查静态分析阻断并决定如何补充映射。",
  };
  return descriptions[action?.id] || "按照后端给出的唯一下一步继续当前训练任务。";
}
function renderControl(task) {
  const control = task.control || {}; const action = control.next_action || {}; const blocked = control.blocked_by?.[0];
  ui.taskControlPanel.hidden = true; ui.currentStageState.textContent = stageLabel(control.current_stage); ui.nextActionLabel.textContent = action.label || "等待下一步";
  ui.nextActionDescription.textContent = nextActionDescription(action, blocked); ui.nextActionButton.textContent = action.label || "查看任务"; ui.nextActionButton.disabled = !action.id; ui.nextActionCard.dataset.state = blocked ? "blocked" : "ready";
  ui.taskBlocker.hidden = !blocked; if (blocked) { ui.taskBlockerTitle.textContent = "当前步骤需要处理"; ui.taskBlockerDescription.textContent = blocked.message; ui.taskBlockerActionButton.hidden = false; ui.taskBlockerActionButton.textContent = action.label || "处理阻断"; }
}
function valueOrDash(value) { return value === undefined || value === null || value === "" ? "待确认" : String(value); }
function renderTaskSpec(task) {
  const spec = task.task_spec; const decision = task.capability_decision || {}; if (!spec) { ui.taskSpecCard.hidden = true; return; }
  const resolved = decision.status === "resolved"; const visualStatus = resolved ? "confirmed" : String(decision.status || "needs_clarification").replaceAll("_", "-");
  ui.taskSpecCard.hidden = false; ui.taskSpecCard.dataset.status = visualStatus; ui.taskSpecVersion.textContent = `v${spec.revision}`;
  if (resolved) { ui.taskSpecCard.setAttribute("aria-labelledby", "taskSpecHeading"); ui.taskSpecCard.removeAttribute("aria-label"); }
  else { ui.taskSpecCard.removeAttribute("aria-labelledby"); ui.taskSpecCard.setAttribute("aria-label", "任务澄清选项"); }
  ui.taskSpecStatus.textContent = resolved ? "已确认" : decision.status === "needs_confirmation" ? "待确认" : "待澄清";
  ui.taskSpecHeading.textContent = resolved ? "任务理解已经确认" : "任务澄清选项";
  ui.taskSpecSummary.textContent = resolved ? `已确认“${decision.candidates?.find((item) => item.family === decision.selected_family)?.label || decision.selected_family || "训练任务"}”；能力匹配、数据和运行都以这个版本为准。` : decision.status === "needs_confirmation" ? "选择“就是这个”即可确认；如果不符合，再查看后端给出的其他输出。" : "选择最符合预期的一项；这些选项由当前 TaskSpec 的后端判定返回。";
  const capability = spec.capability_request || {}; const candidate = decision.selected_family ? decision.candidates?.find((item) => item.family === decision.selected_family) : null;
  ui.taskSpecInput.textContent = valueOrDash(capability.modality); ui.taskSpecObjective.textContent = valueOrDash(candidate?.label || capability.objective); ui.taskSpecOutput.textContent = valueOrDash(candidate?.output || capability.target_kind);
  const constraints = capability.constraints; ui.taskSpecConstraints.textContent = constraints && Object.keys(constraints).length ? Object.entries(constraints).map(([key, value]) => `${key}: ${value}`).join(" · ") : "本地运行，其他约束待补充";
  ui.taskSpecFacts.hidden = !resolved; ui.taskSpecClarification.hidden = true; ui.taskSpecClarificationTitle.textContent = decision.status === "needs_confirmation" ? "请确认候选任务" : "还需要确认一项信息"; ui.taskSpecClarificationDescription.textContent = decision.question || "请选择模型唯一输出。";
  ui.confirmTaskSpecButton.hidden = true; ui.editTaskSpecButton.textContent = "高级编辑"; ui.editTaskSpecButton.disabled = task.status === "running"; renderTaskSpecQuickReplies(task);
}
function taskSpecCandidateButton(candidate, { featured = false, prefix = "" } = {}) {
  const button = document.createElement("button"); button.type = "button"; button.className = `task-spec-choice${featured ? " featured" : ""}`;
  const label = document.createElement("b"); const output = document.createElement("span"); label.textContent = `${prefix}${candidate.label}`; output.textContent = candidate.output; button.append(label, output);
  button.addEventListener("click", () => patchTaskSpecChoice(candidate, { confirm: featured })); return button;
}
function renderTaskSpecQuickReplies(task, { showAlternatives = state.taskSpecAlternativesOpen, force = false } = {}) {
  const decision = task.capability_decision || {}; const key = JSON.stringify([task.current_spec_revision, decision.status, decision.selected_family, decision.candidates, showAlternatives]);
  if (!force && key === state.taskSpecQuickReplyKey && ui.taskSpecQuickReplies.childElementCount) return;
  state.taskSpecQuickReplyKey = key; state.taskSpecAlternativesOpen = showAlternatives; clear(ui.taskSpecQuickReplies);
  if (decision.status === "resolved") { ui.taskSpecQuickReplies.hidden = true; return; }
  ui.taskSpecQuickReplies.hidden = false; const allCandidates = decision.candidates || []; const candidates = allCandidates.slice(0, 4); const customCandidate = allCandidates.find((item) => item.family === "custom");
  if (customCandidate && !candidates.some((item) => item.family === "custom")) candidates.push(customCandidate);
  if (decision.status === "needs_confirmation") {
    const selected = candidates.find((item) => item.family === decision.selected_family) || candidates[0];
    if (selected) ui.taskSpecQuickReplies.append(taskSpecCandidateButton(selected, { featured: true, prefix: "就是这个：" }));
    const switchOutput = document.createElement("button"); switchOutput.type = "button"; switchOutput.className = "task-spec-switch"; switchOutput.textContent = showAlternatives ? "收起其他输出" : "换一种输出"; switchOutput.addEventListener("click", () => renderTaskSpecQuickReplies(task, { showAlternatives: !showAlternatives, force: true })); ui.taskSpecQuickReplies.append(switchOutput);
    if (showAlternatives) candidates.filter((item) => item.family !== selected?.family).forEach((candidate) => ui.taskSpecQuickReplies.append(taskSpecCandidateButton(candidate)));
  } else candidates.forEach((candidate) => ui.taskSpecQuickReplies.append(taskSpecCandidateButton(candidate)));
  const describe = document.createElement("button"); describe.type = "button"; describe.className = "task-spec-describe"; describe.textContent = "我自己描述"; describe.addEventListener("click", startTaskSpecDescription); ui.taskSpecQuickReplies.append(describe);
  if (!allCandidates.some((item) => item.family === "custom")) {
    const reparse = document.createElement("button"); reparse.type = "button"; reparse.className = "task-spec-reparse"; reparse.textContent = "重新理解当前描述"; reparse.addEventListener("click", () => reparseTaskSpec(reparse)); ui.taskSpecQuickReplies.append(reparse);
  }
}
async function reparseTaskSpec(button) {
  const task = state.task; const spec = task?.task_spec; if (!task || !spec || task.status === "running") return;
  setButtonBusy(button, true, "正在重新理解");
  try {
    const response = await request(`/tasks/${encodeURIComponent(task.task_id)}/spec`, { method: "PATCH", json: { base_revision: spec.revision, business_goal: spec.business_goal, reparse: true, user_note: "用户请求系统使用当前规则重新理解已保存描述" } });
    state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false;
    await refreshTaskSpecView(response.task); showNotice(`已在同一任务创建需求版本 v${response.task.current_spec_revision}；历史版本和原始描述仍然保留。`, "ok");
  } catch (error) { showNotice(`重新理解失败：${error.message}`); }
  finally { setButtonBusy(button, false, ""); }
}
async function patchTaskSpecChoice(candidate, { confirm = false } = {}) {
  const task = state.task; const spec = task?.task_spec; if (!task || !spec || !candidate?.family) return;
  const buttons = [...ui.taskSpecQuickReplies.querySelectorAll("button")]; buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = await request(`/tasks/${encodeURIComponent(task.task_id)}/spec`, { method: "PATCH", json: { base_revision: spec.revision, selected_family: candidate.family, ...(confirm ? { confirm: true } : {}), user_note: confirm ? `用户确认后端候选：${candidate.label}` : `用户选择后端候选：${candidate.label}` } });
    state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; await refreshTaskSpecView(response.task); showNotice(`需求版本 v${response.task.current_spec_revision} 已保存；下一步将按这个输出匹配训练能力。`, "ok");
  } catch (error) { showNotice(error.message); state.taskSpecQuickReplyKey = ""; if (error.status === 409) await refreshSelected({ force: true }); else renderTaskSpecQuickReplies(state.task, { force: true }); }
}
async function refreshTaskSpecView(task) {
  state.task = task; state.modelSourceLoadedTaskId = null;
  try { state.taskSpecRevisions = (await request(`/tasks/${encodeURIComponent(task.task_id)}/spec/revisions`)).revisions || [task.task_spec]; }
  catch (_error) { state.taskSpecRevisions = task.task_spec ? [task.task_spec] : []; }
  renderTask(task); renderConversation(true); await loadTasks();
}
function startTaskSpecDescription() {
  state.taskSpecDescriptionMode = true; ui.messageInput.placeholder = "直接描述模型接收什么、应该输出什么…"; ui.messageInput.focus(); showNotice("请在主输入框补充你的输入与期望输出；提交后会生成新的需求版本。", "ok");
}
function renderPlan(task) {
  ui.taskPlan.hidden = true;
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
  const source = task.model_binding; const sourceStage = source ? `${source.repository} · ${shortId(source.resolved_commit)}` : blocked ? "等待选择模型或训练仓库" : `Recipe：${task.recipe_id || "待确认"}`;
  const stages = [
    [LIFECYCLE_STEPS[0], sourceStage],
    [LIFECYCLE_STEPS[1], hasData ? `${dataCount} · ${dataSummary}` : blocked ? "等待训练方案 / 数据读取器" : "等待导入"],
    [LIFECYCLE_STEPS[2], confirmed ? "授权、标签/目标、门槛已确认" : "等待人工确认"],
    [LIFECYCLE_STEPS[3], finished ? "真实训练与独立评测完成" : result ? `运行状态：${result.status}` : "尚未启动"],
    [LIFECYCLE_STEPS[4], deliveryDetail(task)],
  ];
  const releaseDone = releaseVerdict(task).releaseReady === true;
  const completedEvidence = [Boolean(task.model_binding || task.recipe_id), hasData, confirmed, finished, releaseDone];
  clear(ui.stageList); stages.forEach(([title, detail], index) => {
    const stageState = completedEvidence[index]
      ? "done"
      : index + 1 === current
        ? "active"
        : "waiting";
    const item = document.createElement("li"); item.className = "stage-item"; item.dataset.state = stageState;
    const mark = document.createElement("span"); mark.className = "stage-mark"; mark.textContent = stageState === "done" ? "✓" : String(index + 1);
    const copy = document.createElement("span"); copy.className = "stage-copy"; const b = document.createElement("b"); b.textContent = title; const small = document.createElement("span"); small.textContent = detail; copy.append(b, small);
    const label = document.createElement("span"); label.className = "stage-state"; label.textContent = stageState === "done" ? "完成" : stageState === "active" ? "当前" : "待办"; item.append(mark, copy, label); ui.stageList.append(item);
  });
}

function restoreCheckpointCard() {
  const card = state.checkpointCard; const marker = checkpointHomes.get(card);
  if (card && marker?.parentNode) marker.parentNode.insertBefore(card, marker.nextSibling);
  state.checkpointCard = null;
}
function checkpointCardFor(task) {
  const stage = stageKey(task); const action = task.control?.next_action?.id || "";
  const sourceActions = new Set(["search_model_sources", "approve_model_source_binding", "replace_model_source", "review_repository_analysis", "retry_model_source_search", "edit_or_retry_model_source", "retry_model_source_binding", "review_or_retry_repository_analysis"]);
  const sourceCard = modelSourceCardForCheckpoint(task);
  if (stage === "task_understanding") return ui.taskSpecCard;
  if (["source_discovery", "source_resolution", "source_snapshot"].includes(stage) || sourceActions.has(action)) return sourceCard;
  if (stage === "capability_resolution") return action === "review_capability_gap" && task.capability_decision?.status === "resolved" ? sourceCard : ui.capabilityCard;
  if (stage === "repository_analysis") return task.model_binding ? ui.repositoryAnalysisCard : sourceCard;
  if (stage === "training_plan") return ui.trainingPlanCard;
  if (["resource_probe", "environment_lock", "resource_fit"].includes(stage)) return ui.resourceFeasibilityCard;
  if (stage === "data_preparation") return ui.datasetCard;
  if (["contract_review", "ready_to_run"].includes(stage)) return ui.contractCard;
  return null;
}
function checkpointIsInline(card) { return card === ui.taskSpecCard || card === ui.modelSourceCheckpointCard; }
function checkpointWorkspaceContext(task, card = checkpointCardFor(task)) {
  if (card === ui.datasetCard || card === ui.contractCard) return "data";
  if (task.current_result?.status === "completed") return "evaluation";
  if (task.status === "running" || RUNNING_STATUSES.has(task.current_result?.status)) return "run";
  return "plan";
}
function checkpointWorkspaceCopy(task, card, blocked) {
  if (card === ui.modelSourceCard) return ["搜索并选择模型来源", "在右侧联网搜索、比较候选并确认固定版本"];
  if (card === ui.capabilityCard) return ["查看训练方案", "在右侧核对能力匹配与尚未补齐的模块"];
  if (card === ui.repositoryAnalysisCard) return [blocked ? "处理仓库分析阻断" : "查看仓库分析", "在右侧核对入口、依赖、许可证与静态风险证据"];
  if (card === ui.trainingPlanCard) return ["核对训练计划", "在右侧检查入口、资源预算与不可变 Plan Digest"];
  if (card === ui.resourceFeasibilityCard) return [blocked ? "查看当前电脑缺少什么" : "检查本机训练条件", "在右侧查看资源事实、环境阻断与恢复动作"];
  if (card === ui.datasetCard) return ["准备训练数据", "在右侧查看数据体检结果与导入要求"];
  if (card === ui.contractCard) return ["确认训练合同", "在右侧核对数据授权、标签与验收门槛"];
  return ["打开任务工作区", "在右侧继续处理当前步骤"];
}
function syncAgentCheckpoint(task) {
  const card = checkpointCardFor(task);
  if (!card || card.hidden) { restoreCheckpointCard(); clear(ui.agentCheckpointBody); ui.agentCheckpointActions.hidden = true; ui.agentCheckpoint.hidden = true; return; }
  const inline = checkpointIsInline(card);
  if (inline && (card !== state.checkpointCard || card.parentNode !== ui.agentCheckpointBody)) { restoreCheckpointCard(); clear(ui.agentCheckpointBody); state.checkpointCard = card; ui.agentCheckpointBody.append(card); }
  if (!inline) { restoreCheckpointCard(); clear(ui.agentCheckpointBody); }
  const control = task.control || {}; const action = control.next_action || {}; const blocked = control.blocked_by?.[0];
  ui.agentCheckpoint.hidden = false;
  ui.agentCheckpointStage.textContent = stageLabel(control.current_stage);
  const sourceSummary = card === ui.modelSourceCheckpointCard;
  ui.agentCheckpointTitle.textContent = card === ui.taskSpecCard ? task.capability_decision?.question || action.label || "模型应该输出什么？" : sourceSummary ? `已找到 ${state.modelSourceCandidates.length} 个目录候选，选择一个继续` : action.label || "查看当前任务证据";
  ui.agentCheckpointState.textContent = blocked ? "需要处理" : sourceSummary ? "等待选择" : action.id ? "等待操作" : "仅供核对";
  ui.agentCheckpointState.dataset.state = blocked ? "blocked" : "ready";
  ui.agentCheckpointSummary.textContent = card === ui.taskSpecCard ? (task.capability_decision?.status === "needs_confirmation" ? "一次只确认一个会改变训练方案的问题。请选择最符合的一项，也可以直接补充。" : "请选择一个输出方向；如果都不符合，可以直接在下方输入框补充描述。") : sourceSummary ? "对话中只列出搜索排序靠前的 3 项；完整结果、临时 Token 和手动地址都在训练详情中。" : nextActionDescription(action, blocked);
  ui.agentCheckpointActions.hidden = inline;
  if (!inline) {
    const [label, hint] = checkpointWorkspaceCopy(task, card, blocked);
    ui.agentCheckpointWorkspaceLabel.textContent = label; ui.agentCheckpointWorkspaceHint.textContent = hint;
    ui.agentCheckpointWorkspaceButton.dataset.context = checkpointWorkspaceContext(task, card);
  }
}
function scrollToCheckpoint() {
  if (ui.agentCheckpoint.hidden) return;
  ui.agentCheckpoint.scrollIntoView({ behavior: "smooth", block: "center" });
}
function revealCurrentWorkspaceObject(task = state.task) {
  const card = task ? checkpointCardFor(task) : null;
  if (!card || checkpointIsInline(card) || card.hidden) return;
  window.requestAnimationFrame(() => card.scrollIntoView({ block: "start", behavior: "smooth" }));
}
function syncWorkspaceForTask(task) {
  const stage = stageKey(task); const card = checkpointCardFor(task); const result = task.current_result;
  const context = task.status === "running" || (result && RUNNING_STATUSES.has(result.status)) ? "run" : result?.status === "completed" ? "evaluation" : stage === "data_preparation" || ["contract_review", "ready_to_run"].includes(stage) ? "data" : stage === "task_understanding" ? null : "plan";
  const key = context ? `${task.task_id}:${stage}:${context}:${task.current_run_id || result?.run_id || card?.id || "current"}` : null;
  if (key && state.workspaceAutoKey !== key) { state.workspaceAutoKey = key; if (dockedWorkspaceMedia.matches) { openInspector(context); revealCurrentWorkspaceObject(task); } }
}
function addFact(label, value) { const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label; const selected = document.createElement("b"); selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); ui.capabilityFacts.append(row); }
function bindingAnalysisAttempt(task) { return task.repository_analysis_attempt || task.model_binding_attempt || null; }
function renderCapability(task) {
  const request = task.capability_request || {}; const build = task.recipe_request; const recipeBuild = task.current_recipe_build; const decision = task.capability_decision || {}; const binding = task.model_binding; const analysis = task.repository_analysis; const analysisAttempt = bindingAnalysisAttempt(task); clear(ui.capabilityFacts);
  const analysisStatus = analysisAttempt?.current_state?.status; const analysisFailure = analysisAttempt?.current_state?.failure;
  if (!binding && analysisAttempt) {
    if (["queued", "running"].includes(analysisStatus)) { ui.capabilityState.textContent = analysisStatus === "queued" ? "等待分析" : "分析中"; ui.capabilitySummary.textContent = analysisStatus === "queued" ? "绑定请求已持久化，等待后台读取固定版本；刷新或离开页面不会伪造完成状态。" : "正在读取固定版本并做静态分析；模型来源尚未绑定，也没有执行第三方代码。"; }
    else if (["failed", "cancelled"].includes(analysisStatus)) { ui.capabilityState.textContent = analysisStatus === "failed" ? "绑定分析失败" : "绑定分析已取消"; ui.capabilitySummary.textContent = analysisFailure?.message || "模型来源尚未绑定；请查看失败证据后重试。"; }
    else { ui.capabilityState.textContent = "绑定状态异常"; ui.capabilitySummary.textContent = "后台尝试已经结束，但任务还没有可验证的模型绑定；请刷新或按失败证据重试。"; }
  }
  else if (binding) {
    const analysisBlockers = analysis?.downstream_blockers || [];
    if (binding.status === "stale") { ui.capabilityState.textContent = "来源已过期"; ui.capabilitySummary.textContent = "需求版本已经变化，需要重新选择模型来源。"; }
    else if (analysis) { const analysisBlocked = analysis.status !== "complete" || analysisBlockers.length > 0; ui.capabilityState.textContent = analysisBlocked ? "分析有阻断" : "来源已分析"; ui.capabilitySummary.textContent = analysisBlocked ? "固定版本已完成静态分析，但存在需要处理的风险或证据阻断。" : "固定版本来源与静态仓库分析均已完成；尚未生成或批准训练计划。"; }
    else if (["queued", "running"].includes(analysisStatus)) { ui.capabilityState.textContent = "分析中"; ui.capabilitySummary.textContent = "固定版本来源已经绑定，正在读取受限文件清单并做静态分析；尚未执行仓库代码。"; }
    else if (["failed", "cancelled"].includes(analysisStatus)) { ui.capabilityState.textContent = analysisStatus === "failed" ? "分析失败" : "分析已取消"; ui.capabilitySummary.textContent = analysisFailure?.message || "固定版本已经绑定，但仓库静态分析没有完成；请按证据重试或调整来源。"; }
    else { ui.capabilityState.textContent = "模型已绑定"; ui.capabilitySummary.textContent = "固定版本来源已经建立，但尚无完成的仓库静态分析证据。"; }
  }
  else if (decision.status === "needs_clarification") { ui.capabilityState.textContent = "待澄清"; ui.capabilitySummary.textContent = decision.question || "需要先明确模型唯一输出，尚未匹配训练方案。"; }
  else if (decision.status === "needs_confirmation") { ui.capabilityState.textContent = "待确认"; ui.capabilitySummary.textContent = "后端已形成候选任务规格；确认前不会绑定训练方案或生成运行。"; }
  else if (task.capability_status === "matched") { ui.capabilityState.textContent = "已匹配"; ui.capabilitySummary.textContent = `已选择 ${task.recipe_id}；该训练方案将接入统一的数据、合同、运行、评测和产物闭环。`; }
  else if (task.capability_status === "needs_recipe") { ui.capabilityState.textContent = "待构建"; ui.capabilitySummary.textContent = "现有 Recipe 无法覆盖该能力。系统已持久化构建请求，并且不会伪造训练进度。"; }
  else { ui.capabilityState.textContent = "待识别"; ui.capabilitySummary.textContent = "继续描述输入数据、预测目标和运行限制，以匹配或构建 Recipe。"; }
  addFact("数据模态", request.modality); addFact("任务目标", request.objective); addFact("输出类型", request.target_kind); addFact("Recipe", task.recipe_id); addFact("Data Adapter", task.data_adapter_id || request.data_adapter); if (build) addFact("构建请求", build.request_id || build.recipe_request_id);
  if (task.staged_assets?.latest) addFact("构建样例", `${task.staged_assets.latest.status} · ${task.staged_assets.latest.report?.file_count || 0} 个 WAV`);
  if (recipeBuild) { addFact("BuildAttempt", `${recipeBuild.status} · ${shortId(recipeBuild.attempt_id)}`); addFact("Candidate SHA", recipeBuild.candidate_digest ? shortId(recipeBuild.candidate_digest) : "未生成"); addFact("Validation SHA", recipeBuild.validation_digest ? shortId(recipeBuild.validation_digest) : "未生成"); }
  if (task.recipe_version_id) addFact("RecipeVersion", shortId(task.recipe_version_id));
  ui.scaffoldRecipeButton.hidden = Boolean(task.model_binding) || task.capability_status !== "needs_recipe" || decision.selected_family === "audio_classification";
  ui.scaffoldRecipeButton.textContent = build?.status === "scaffold_ready" ? "重新生成 Code Agent 构建包" : "生成 Code Agent 构建包";
}
function modelSourceBlocker(task) {
  const stages = new Set(["source_discovery", "source_resolution", "source_snapshot", "repository_analysis"]);
  return (task.blockers || []).find((item) => item.active !== false && stages.has(item.stage)) || null;
}
function latestPendingResolution(task) {
  const currentResolutionId = task.model_binding?.resolution_id;
  const attemptedResolutionId = bindingAnalysisAttempt(task)?.attempt?.resolution_id;
  const bindingCreatedAt = String(task.model_binding?.created_at || "");
  return [...state.modelSourceResolutions]
    .filter((item) => item.resolution_id !== currentResolutionId && item.resolution_id !== attemptedResolutionId && item.details?.base_spec_revision === task.current_spec_revision && (!bindingCreatedAt || String(item.created_at || "") > bindingCreatedAt))
    .sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")))
    .at(-1) || null;
}
function hasCurrentModelSourceSearch(task) {
  const search = state.modelSourceSearch; const binding = task.model_binding; const pending = latestPendingResolution(task);
  return Boolean(search?.search_id && search.base_spec_revision === task.current_spec_revision && state.modelSourceCandidates.length && !pending && !modelSourceBlocker(task) && (!binding || binding.status === "stale"));
}
function modelSourceCardForCheckpoint(task) { return hasCurrentModelSourceSearch(task) ? ui.modelSourceCheckpointCard : ui.modelSourceCard; }
function modelSourceProviderLabel(provider) { return provider === "huggingface" ? "Hugging Face" : provider === "github" ? "GitHub" : provider || "未知目录"; }
function modelSourceProviderEvidence(search) {
  const errors = new Map((search.provider_errors || []).map((item) => [item.provider, item]));
  const providers = search.providers?.length ? search.providers : [...new Set(state.modelSourceCandidates.map((item) => item.provider))];
  return providers.map((provider) => {
    const error = errors.get(provider); const count = state.modelSourceCandidates.filter((item) => item.provider === provider).length;
    return error ? `${modelSourceProviderLabel(provider)} 失败` : `${modelSourceProviderLabel(provider)} ${count} 项`;
  }).join(" · ") || "未返回 Provider 证据";
}
function appendSourceCheckpointFact(label, value) {
  const row = document.createElement("div"); const term = document.createElement("dt"); const detail = document.createElement("dd"); term.textContent = label; detail.textContent = value; detail.title = value; row.append(term, detail); ui.modelSourceCheckpointFacts.append(row);
}
function modelSourceCandidateIdentity(candidate) { return [candidate.candidate_id, candidate.provider, candidate.repository, candidate.requested_revision, candidate.license, candidate.license_status, candidate.selection_state]; }
function modelSourceSelectionContext(search = state.modelSourceSearch, task = state.task) { return { taskId: task?.task_id, searchId: search?.search_id, baseSpecRevision: search?.base_spec_revision }; }
function renderModelSourceCheckpoint(task) {
  const search = state.modelSourceSearch; const visible = hasCurrentModelSourceSearch(task); ui.modelSourceCheckpointCard.hidden = !visible;
  if (!visible) { state.modelSourceCheckpointRenderKey = ""; return; }
  const key = JSON.stringify([task.task_id, search.search_id, search.base_spec_revision, search.query_plan, search.providers, search.provider_errors, state.modelSourceCandidates.map(modelSourceCandidateIdentity)]);
  if (key === state.modelSourceCheckpointRenderKey && ui.modelSourceCheckpointCandidates.childElementCount) return;
  state.modelSourceCheckpointRenderKey = key; clear(ui.modelSourceCheckpointFacts); clear(ui.modelSourceCheckpointCandidates);
  appendSourceCheckpointFact("实际搜索词", search.query_plan?.effective_query || "—");
  appendSourceCheckpointFact("Provider", modelSourceProviderEvidence(search));
  appendSourceCheckpointFact("目录结果", `${state.modelSourceCandidates.length} 个候选`);
  const errors = search.provider_errors || [];
  ui.modelSourceCheckpointBoundary.textContent = `${errors.length ? `有 ${errors.length} 个 Provider 返回错误；其余结果仍保留。` : "所有请求目录均已返回。"} 候选只来自官方目录元数据，尚未下载、执行或验证训练适配性。`;
  const selectionContext = modelSourceSelectionContext(search, task);
  state.modelSourceCandidates.slice(0, 3).forEach((candidate) => {
    const button = document.createElement("button"); button.type = "button"; button.className = "source-candidate-compact";
    const identity = document.createElement("span"); const provider = document.createElement("i"); const name = document.createElement("b"); provider.textContent = candidate.provider === "huggingface" ? "HF" : "GH"; name.textContent = candidate.repository; name.title = candidate.repository; identity.append(provider, name);
    const reason = document.createElement("small"); reason.textContent = candidate.why_shortlisted?.[0] || candidate.description || "官方目录返回的候选";
    const action = document.createElement("em"); action.textContent = `${candidate.license_status === "known" ? candidate.license : "License 待审"} · 选择后解析固定版本`;
    button.dataset.searchId = search.search_id; button.dataset.candidateId = candidate.candidate_id; button.setAttribute("aria-label", `选择 ${candidate.repository} 并解析固定版本`); button.append(identity, reason, action); button.addEventListener("click", () => confirmSourceCandidate(candidate, selectionContext)); ui.modelSourceCheckpointCandidates.append(button);
  });
  ui.viewAllModelSourceCandidatesButton.textContent = `查看全部 ${state.modelSourceCandidates.length} 个候选`;
}
function addSourceFact(label, value, { code = false } = {}) {
  const row = document.createElement("div"); const name = document.createElement("span"); const selected = document.createElement(code ? "code" : "b");
  name.textContent = label; selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); ui.modelSourceFacts.append(row);
}
function renderModelSource(task) {
  const resolvedSpec = task.capability_decision?.status === "resolved"; const binding = task.model_binding || null; const attempt = bindingAnalysisAttempt(task); const attemptStatus = attempt?.current_state?.status; const pending = latestPendingResolution(task); const blocker = modelSourceBlocker(task); const locked = task.status === "running";
  ui.modelSourceCard.hidden = false; ui.modelSourceBlocker.hidden = !blocker; ui.modelSourceBinding.hidden = !binding; ui.modelSourcePending.hidden = !pending;
  const bindingActive = !binding && ["queued", "running"].includes(attemptStatus);
  ui.cancelModelBindingButton.hidden = !bindingActive;
  ui.cancelModelBindingButton.disabled = !bindingActive;
  if (blocker) { ui.modelSourceBlockerTitle.textContent = blocker.stage === "source_discovery" ? "官方目录搜索失败" : blocker.stage === "source_resolution" ? "模型地址解析失败" : blocker.stage === "source_snapshot" ? "仓库清单不完整" : "仓库分析被阻断"; ui.modelSourceBlockerMessage.textContent = blocker.message || blocker.code; }
  if (binding) {
    const stale = binding.status === "stale"; const summary = binding.snapshot_summary || {}; const license = binding.license_policy || {};
    ui.modelSourceCard.dataset.state = stale ? "stale" : "active"; ui.modelSourceState.textContent = stale ? "已过期" : "已绑定";
    ui.modelSourceSummary.textContent = stale ? `任务规格已更新；${binding.repository} 的旧绑定仍保留，但不能进入后续执行。` : `${binding.repository} 已固定到不可变 commit；第三方代码仍只做静态检查。`;
    clear(ui.modelSourceFacts); addSourceFact("Provider", binding.provider); addSourceFact("仓库", binding.repository); addSourceFact("请求版本", binding.requested_revision, { code: true }); addSourceFact("固定 Commit", binding.resolved_commit, { code: true }); addSourceFact("License", `${license.spdx || binding.license} · ${license.decision || "review"}`); addSourceFact("文件摘要", `${summary.file_count || 0} 项 · ${formatBytes(summary.known_size_bytes)}${summary.size_semantics === "git_tree_blob_bytes_lfs_may_be_additional" ? "（LFS 另计）" : ""}`); addSourceFact("Manifest", summary.manifest_sha256 || binding.tree_manifest_sha256, { code: true }); addSourceFact("代码策略", summary.remote_code?.declared ? `发现 ${summary.remote_code.file_count} 个代码文件，仅静态分析` : "未发现代码文件");
    clear(ui.modelSourceFileList); (summary.file_preview || []).forEach((file) => { const row = document.createElement("div"); const path = document.createElement("code"); const size = document.createElement("span"); path.textContent = file.path; size.textContent = file.size_bytes === null || file.size_bytes === undefined ? file.kind : formatBytes(file.size_bytes); row.append(path, size); ui.modelSourceFileList.append(row); });
    ui.modelSourceDiscovery.open = stale; ui.modelSourceDiscoverySummary.textContent = stale ? "重新搜索并绑定当前规格" : "更换模型来源";
  } else if (pending) {
    ui.modelSourceCard.dataset.state = blocker ? "blocked" : "pending"; ui.modelSourceState.textContent = blocker ? "需处理" : "待批准"; ui.modelSourceSummary.textContent = "已从官方 Provider 解析到固定 commit；批准前尚未读取仓库文件树。";
  } else if (attempt) {
    const failure = attempt.current_state?.failure;
    ui.modelSourceCard.dataset.state = ["failed", "cancelled"].includes(attemptStatus) ? "blocked" : "pending";
    ui.modelSourceState.textContent = attemptStatus === "queued" ? "等待绑定" : attemptStatus === "running" ? "绑定分析中" : attemptStatus === "failed" ? "绑定失败" : attemptStatus === "cancelled" ? "绑定已取消" : "等待结果";
    ui.modelSourceSummary.textContent = ["queued", "running"].includes(attemptStatus) ? "绑定批准已经记录；后台正在读取固定版本并做静态分析，完成前不会显示为已绑定。" : failure?.message || "绑定尝试已经结束，但尚未产生可验证的模型绑定；请刷新或重试。";
  } else {
    ui.modelSourceCard.dataset.state = blocker ? "blocked" : resolvedSpec ? "idle" : "locked"; ui.modelSourceState.textContent = blocker ? "已阻断" : resolvedSpec ? "待选择" : "等待规格"; ui.modelSourceSummary.textContent = resolvedSpec ? "联网搜索候选或粘贴公开地址；搜索结果只是候选，不等于已经适配本机。" : "先确认任务输入与唯一输出，再按当前 TaskSpec 搜索和绑定模型来源。";
  }
  if (pending) {
    const details = pending.details || {}; ui.pendingSourceRepo.textContent = `${pending.provider} · ${pending.repository}`; ui.pendingRequestedRevision.textContent = pending.requested_revision; ui.pendingResolvedCommit.textContent = pending.resolved_commit; ui.pendingResolvedCommit.title = pending.resolved_commit; ui.pendingSourceLicense.textContent = `${details.license || "unknown"} · ${details.license_status === "known" ? "已声明" : "需审查"}`;
  }
  const availableProviders = new Set(state.modelSourceProviders.filter((item) => item.available !== false && item.search_available !== false).map((item) => item.provider));
  const hfAvailable = availableProviders.has("huggingface"); const githubAvailable = availableProviders.has("github"); const canSearch = resolvedSpec && !locked && availableProviders.size > 0;
  ui.searchHfProvider.disabled = !canSearch || !hfAvailable; ui.searchGithubProvider.disabled = !canSearch || !githubAvailable;
  if (!hfAvailable) ui.searchHfProvider.checked = false; if (!githubAvailable) ui.searchGithubProvider.checked = false;
  [ui.modelSourceSearchInput, ui.modelSourceSearchButton, ui.modelSourceReferenceInput, ui.modelSourceRevisionInput, ui.modelSourceResolveButton].forEach((element) => { element.disabled = !canSearch; });
  ui.bindModelSourceButton.disabled = !pending || locked || !fixedCommit(pending?.resolved_commit); renderModelSourceCandidates(); renderModelSourceCheckpoint(task); renderSourceMode();
  if (state.modelSourceSearch) { const plan = state.modelSourceSearch.query_plan || {}; const errors = state.modelSourceSearch.provider_errors || []; ui.modelSourceSearchEvidence.textContent = `实际搜索词：${plan.effective_query || "—"}；${state.modelSourceCandidates.length} 个候选。${errors.length ? `部分 Provider 失败：${errors.map((item) => `${item.provider}（${item.reason || "未知原因"}）`).join("、")}` : "搜索来自官方 Provider API。"}`; }
  else ui.modelSourceSearchEvidence.textContent = blocker?.stage === "source_discovery" ? `本次搜索失败：${blocker.message || blocker.code}。旧候选已隐藏，请修改条件后重试。` : availableProviders.size ? "搜索只读取官方目录元数据，不代表模型已经适配本机。" : "官方 Provider 能力当前不可用，请检查后端依赖。";
}

async function cancelModelBindingAttempt() {
  const attemptId = bindingAnalysisAttempt(state.task)?.attempt?.attempt_id;
  if (!state.selectedTaskId || !attemptId) {
    showNotice("当前没有可以取消的来源读取任务。");
    return;
  }
  openSimpleDialog({
    kicker: "取消来源读取",
    title: "停止本次模型来源读取与静态分析？",
    body: "取消会保留 Attempt 证据，但不会创建模型绑定、RepositoryAnalysis、Recipe 或训练 Run。之后可以在同一训练任务中重试。",
    allowLabel: "确认取消",
    onAllow: async () => {
      const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-binding-attempts/${encodeURIComponent(attemptId)}/cancel`, {
        method: "POST",
        json: { reason: "用户在来源卡片取消读取与分析" },
      });
      showNotice(result.cancelled ? "本次来源读取已取消，未建立模型绑定。" : "该来源读取已经结束，无需取消。", "ok");
      await refreshSelected({ force: true });
    },
  });
}
function appendFact(container, label, value, { code = false } = {}) {
  const row = document.createElement("div"); const name = document.createElement("span"); const selected = document.createElement(code ? "code" : "b");
  name.textContent = label; selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); container.append(row);
}
const REPOSITORY_ANALYSIS_STATUS_LABELS = {
  complete: "分析完成",
  needs_input: "需要补充信息",
  needs_manual_mapping: "需要补充信息",
  blocked: "已阻断",
};
function analysisItems(value) { return Array.isArray(value) ? value : []; }
function analysisValue(item, keys) {
  if (typeof item === "string") return item;
  for (const key of keys) if (item?.[key] !== undefined && item[key] !== null && item[key] !== "") return String(item[key]);
  return "未命名结论";
}
function entrypointValue(item) {
  const path = analysisValue(item, ["path", "name"]); const confidence = Number(item?.confidence);
  return Number.isFinite(confidence) ? `${path} (${Math.round(confidence * 100)}%)` : path;
}
function parseLegacyAnalysisEvidence(reference) {
  const text = /^(.+):L([1-9][0-9]*)#sha256=([0-9a-f]{64})$/.exec(reference || "");
  if (text) return { kind: "text_line", ref: reference, path: text[1], line: Number(text[2]), document_sha256: text[3] };
  const manifest = /^manifest:([0-9a-f]{64}):(.+)#basis=([^#]+)$/.exec(reference || "");
  if (manifest) return { kind: "manifest_entry", ref: reference, manifest_entry: { tree_manifest_sha256: manifest[1], path: manifest[2], basis: manifest[3] } };
  return { kind: "unknown", ref: reference };
}
function findingEvidence(item) {
  if (Array.isArray(item?.evidence) && item.evidence.length) return item.evidence;
  return analysisItems(item?.evidence_refs).map(parseLegacyAnalysisEvidence);
}
function findingTitle(item, fallback) {
  const value = analysisValue(item, ["code", "model_id", "task", "path", "name"]);
  return value === "未命名结论" ? fallback : value;
}
function appendRepositoryEvidence(target, label, items, analysis) {
  analysisItems(items).forEach((item) => {
    const article = document.createElement("article"); const heading = document.createElement("b"); const evidenceList = findingEvidence(item);
    heading.textContent = `${label} · ${findingTitle(item, "分析结论")}`; article.append(heading);
    if (item?.severity) { const severity = document.createElement("code"); severity.textContent = `风险级别：${item.severity}`; article.append(severity); }
    if (item?.message) { const message = document.createElement("code"); message.textContent = item.message; article.append(message); }
    if (!evidenceList.length) { const missing = document.createElement("code"); missing.textContent = "该结论没有可逐行打开的文本证据。"; article.append(missing); }
    evidenceList.forEach((evidence) => {
      if (evidence.kind === "text_line" && evidence.path && Number.isInteger(Number(evidence.line))) {
        const button = document.createElement("button"); button.type = "button"; button.className = "text-button";
        button.textContent = `${evidence.path}:L${evidence.line} · 查看固定 Commit 的精确摘录`;
        button.title = evidence.resolved_commit || analysis.resolved_commit || "查看静态分析证据";
        button.addEventListener("click", () => openRepositoryEvidenceExcerpt(analysis, evidence, button)); article.append(button); return;
      }
      const manifest = evidence.manifest_entry; const code = document.createElement("code");
      if (evidence.kind === "manifest_entry" || manifest) {
        code.textContent = `Manifest 清单证据：${manifest?.path || evidence.ref || "未知路径"}${manifest?.basis ? ` · ${manifest.basis}` : ""}。该证据来自文件清单，不伪造源码行号，不能逐行打开。`;
      } else code.textContent = evidence.ref || "不可定位的快照元数据证据";
      article.append(code);
    });
    target.append(article);
  });
}
async function openRepositoryEvidenceExcerpt(analysis, evidence, button) {
  const taskId = state.selectedTaskId; const analysisId = analysis?.analysis_id; if (!taskId || !analysisId) { showNotice("当前分析缺少可追溯的 task 或 analysis ID。"); return; }
  setButtonBusy(button, true, "正在读取精确摘录");
  try {
    const query = new URLSearchParams({ path: evidence.path, line: String(evidence.line), context_lines: "3" });
    const response = await request(`/tasks/${encodeURIComponent(taskId)}/repository-analyses/${encodeURIComponent(analysisId)}/evidence?${query.toString()}`);
    if (state.selectedTaskId !== taskId || state.task?.repository_analysis?.analysis_id !== analysisId) return;
    const excerpt = response.evidence || {};
    const expectedCommit = evidence.resolved_commit || analysis.resolved_commit;
    if ((evidence.document_sha256 && excerpt.document_sha256 !== evidence.document_sha256) || (expectedCommit && excerpt.resolved_commit !== expectedCommit)) {
      showNotice("后端返回的摘录与当前分析证据不一致，已停止展示。"); return;
    }
    clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "固定仓库证据"; ui.dialogTitle.textContent = `${excerpt.path || evidence.path}:L${excerpt.requested_line || evidence.line}`;
    const meta = document.createElement("p"); meta.textContent = `Commit ${excerpt.resolved_commit || analysis.resolved_commit || "未知"} · Snapshot ${excerpt.snapshot_id || analysis.source_snapshot_id || "未知"} · SHA-256 ${excerpt.document_sha256 || "未知"}`;
    const source = document.createElement("pre"); source.textContent = analysisItems(excerpt.lines).map((item) => `${Number(item.line) === Number(excerpt.requested_line) ? ">" : " "} ${String(item.line).padStart(4, " ")}  ${item.text}`).join("\n") || "后端没有返回摘录行。";
    ui.dialogBody.append(meta, source); const close = document.createElement("button"); close.type = "button"; close.className = "allow"; close.textContent = "关闭"; close.addEventListener("click", () => ui.decisionDialog.close()); ui.dialogActions.append(close); ui.decisionDialog.showModal();
  } catch (error) { showNotice(`证据读取失败：${error.message}`); }
  finally { setButtonBusy(button, false, ""); }
}
function renderRepositoryAnalysis(task) {
  const binding = task.model_binding; const analysis = task.repository_analysis; const attempt = bindingAnalysisAttempt(task); ui.repositoryAnalysisCard.hidden = !binding && !attempt; if (!binding && !attempt) return;
  clear(ui.repositoryAnalysisFacts); clear(ui.repositoryAnalysisEvidenceList); clear(ui.repositoryAnalysisRiskList); ui.repositoryAnalysisRiskPanel.hidden = true; ui.repositoryManualMapping.hidden = true; ui.repositoryAnalysisCard.dataset.state = "pending";
  if (!analysis) {
    const status = attempt?.current_state?.status; const failure = attempt?.current_state?.failure; const attemptId = attempt?.attempt?.attempt_id;
    ui.repositoryAnalysisState.textContent = status === "queued" ? "已排队" : status === "running" ? "分析中" : status === "failed" ? "失败" : status === "cancelled" ? "已取消" : binding ? "待分析" : "状态异常";
    ui.repositoryAnalysisSummary.textContent = status === "queued" ? "请求已持久化，等待后台读取固定版本。" : status === "running" ? "正在读取受限文件清单并做静态分析；尚未执行第三方代码。" : failure?.message || (binding ? "固定来源已经建立，但尚无可验证的仓库分析结果。" : "分析尝试已经结束，但模型来源尚未绑定；请刷新或重试。");
    appendFact(ui.repositoryAnalysisFacts, "Analysis Attempt", attemptId ? `${status || "未知"} · ${shortId(attemptId)}` : "无生命周期记录");
    if (failure) { appendFact(ui.repositoryAnalysisFacts, "失败代码", failure.code || "unknown_failure", { code: true }); const article = document.createElement("article"); const heading = document.createElement("b"); const evidence = document.createElement("code"); heading.textContent = failure.code || "绑定分析失败"; evidence.textContent = failure.message || "没有错误详情"; article.append(heading, evidence); ui.repositoryAnalysisEvidenceList.append(article); ui.repositoryAnalysisEvidence.open = true; }
    else ui.repositoryAnalysisEvidence.open = false;
    return;
  }
  const contractEntries = analysisItems(analysis.entrypoints); const trainingEntries = analysisItems(analysis.training_entrypoints).length ? analysisItems(analysis.training_entrypoints) : contractEntries.filter((item) => item.kind === "train"); const inferenceEntries = analysisItems(analysis.inference_entrypoints).length ? analysisItems(analysis.inference_entrypoints) : contractEntries.filter((item) => item.kind === "inference");
  const contractDependencies = analysisItems(analysis.dependency_files); const legacyDependencies = analysisItems(analysis.dependency_manifests); const dependencies = contractDependencies.some((item) => typeof item === "object") ? contractDependencies : legacyDependencies.length ? legacyDependencies : contractDependencies;
  const frameworks = analysisItems(analysis.frameworks); const tasks = analysisItems(analysis.task_candidates); const dataContracts = analysisItems(analysis.data_contract_candidates).length ? analysisItems(analysis.data_contract_candidates) : analysisItems(analysis.data_contract_hints); const metrics = analysisItems(analysis.metrics); const artifacts = analysisItems(analysis.artifacts); const weights = analysisItems(analysis.weight_formats); const baseModels = analysisItems(analysis.base_model_candidates); const risks = analysisItems(analysis.risk_findings).length ? analysisItems(analysis.risk_findings) : analysisItems(analysis.risks); const blockers = analysisItems(analysis.downstream_blockers);
  const selectedStatus = analysis.status || (blockers.length ? "blocked" : "complete"); ui.repositoryAnalysisState.textContent = REPOSITORY_ANALYSIS_STATUS_LABELS[selectedStatus] || statusLabel(selectedStatus); ui.repositoryAnalysisCard.dataset.state = selectedStatus === "blocked" || blockers.length ? "blocked" : selectedStatus === "complete" ? "active" : "pending";
  ui.repositoryAnalysisSummary.textContent = selectedStatus === "blocked" || blockers.length ? `静态分析状态为“${REPOSITORY_ANALYSIS_STATUS_LABELS[selectedStatus] || selectedStatus}”；发现 ${risks.length} 项风险、${blockers.length} 项下游阻断，系统不会把它描述成可执行。` : selectedStatus === "needs_input" || selectedStatus === "needs_manual_mapping" ? "固定快照中没有足够证据确认训练入口，需要补充映射后重新分析；系统不会猜测执行命令。" : `已从固定快照识别 ${trainingEntries.length} 个训练入口和 ${inferenceEntries.length} 个推理入口；请逐项核对证据。`;
  appendFact(ui.repositoryAnalysisFacts, "分析状态", REPOSITORY_ANALYSIS_STATUS_LABELS[selectedStatus] || selectedStatus); appendFact(ui.repositoryAnalysisFacts, "Analyzer", analysis.analyzer_version, { code: true }); appendFact(ui.repositoryAnalysisFacts, "Analysis Digest", analysis.analysis_digest || analysis.content_digest, { code: true }); appendFact(ui.repositoryAnalysisFacts, "Snapshot Digest", analysis.snapshot_digest, { code: true }); appendFact(ui.repositoryAnalysisFacts, "固定 Commit", analysis.resolved_commit || binding?.resolved_commit, { code: true }); appendFact(ui.repositoryAnalysisFacts, "Snapshot", analysis.source_snapshot_id || binding?.snapshot_id, { code: true }); appendFact(ui.repositoryAnalysisFacts, "Analysis Attempt", attempt ? `${attempt.current_state?.status || "未知"} · ${shortId(attempt.attempt?.attempt_id)}` : "旧快照，无生命周期记录");
  appendFact(ui.repositoryAnalysisFacts, "框架", frameworks.map((item) => analysisValue(item, ["name"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "任务候选", tasks.map((item) => analysisValue(item, ["task", "name"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "训练入口", trainingEntries.map(entrypointValue).join("、") || "需要补充"); appendFact(ui.repositoryAnalysisFacts, "推理入口", inferenceEntries.map(entrypointValue).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "基础模型", baseModels.map((item) => analysisValue(item, ["model_id", "name"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "数据契约", dataContracts.map((item) => analysisValue(item, ["name", "schema", "path"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "依赖文件", dependencies.map((item) => analysisValue(item, ["path", "name"])).join("、") || "未发现"); appendFact(ui.repositoryAnalysisFacts, "指标", metrics.map((item) => analysisValue(item, ["name"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "产物", artifacts.map((item) => analysisValue(item, ["name", "path"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "权重格式", weights.map((item) => analysisValue(item, ["name"])).join("、") || "未识别"); appendFact(ui.repositoryAnalysisFacts, "执行策略", analysis.execution_policy || "static_only_never_execute");
  [["框架", frameworks], ["任务", tasks], ["训练入口", trainingEntries], ["推理入口", inferenceEntries], ["基础模型", baseModels], ["数据契约", dataContracts], ["依赖", dependencies], ["指标", metrics], ["产物", artifacts], ["权重", weights]].forEach(([label, items]) => appendRepositoryEvidence(ui.repositoryAnalysisEvidenceList, label, items, analysis));
  if (risks.length || blockers.length) { ui.repositoryAnalysisRiskPanel.hidden = false; appendRepositoryEvidence(ui.repositoryAnalysisRiskList, "风险", risks, analysis); appendRepositoryEvidence(ui.repositoryAnalysisRiskList, "阻断", blockers, analysis); }
  ui.repositoryManualMapping.hidden = !["needs_input", "needs_manual_mapping"].includes(selectedStatus);
  ui.repositoryAnalysisEvidence.open = selectedStatus !== "complete";
}
async function applyRepositoryManualMapping(event) {
  event.preventDefault();
  const analysis = state.task?.repository_analysis; const entrypoint = ui.repositoryManualEntrypointInput.value.trim(); const datasetArgument = ui.repositoryDatasetArgumentInput.value.trim();
  if (!analysis?.analysis_id) { showNotice("当前没有可修订的仓库分析。"); return; }
  if (!entrypoint) { showNotice("请填写当前固定快照中的训练入口路径。"); ui.repositoryManualEntrypointInput.focus(); return; }
  setButtonBusy(ui.applyRepositoryManualMappingButton, true, "正在创建分析 revision");
  try {
    const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/repository-analyses/${encodeURIComponent(analysis.analysis_id)}/manual-mappings`, { method: "POST", json: { training_entrypoint: entrypoint, dataset_argument: datasetArgument || null } });
    ui.repositoryManualEntrypointInput.value = ""; ui.repositoryDatasetArgumentInput.value = "";
    showNotice(`已创建新的 RepositoryAnalysis 与 Binding revision：${shortId(result.analysis?.analysis_id)}。`, "ok");
    await refreshSelected({ force: true });
  } catch (error) { showNotice(`映射未生效：${error.message}`); await refreshSelected({ force: true }); }
  finally { setButtonBusy(ui.applyRepositoryManualMappingButton, false, ""); }
}
function renderTrainingPlan(task) {
  const binding = task.model_binding; const analysis = task.repository_analysis; const view = task.training_plan; ui.trainingPlanCard.hidden = !binding; if (!binding) return;
  const blockedLicense = (task.blockers || []).some((item) => item.active !== false && item.stage === "training_plan" && item.code === "blocked_license"); const entries = analysis?.training_entrypoints || []; const needsMapping = ["needs_input", "needs_manual_mapping"].includes(analysis?.status); const blockedAnalysis = Boolean(analysis) && analysis.status !== "complete" && !needsMapping;
  clear(ui.trainingPlanFacts); ui.manualEntrypointField.hidden = true; ui.createTrainingPlanButton.hidden = Boolean(view && !view.stale); ui.createTrainingPlanButton.disabled = blockedLicense || needsMapping || blockedAnalysis; ui.createTrainingPlanButton.textContent = view?.stale ? "基于当前来源生成新 revision" : "生成不可变计划草案"; ui.approveTrainingPlanButton.hidden = true; ui.trainingPlanDecisionActions.hidden = true;
  if (!view) { ui.trainingPlanState.textContent = blockedLicense ? "许可证阻断" : needsMapping ? "等待入口映射" : blockedAnalysis ? "分析风险阻断" : "未生成"; ui.trainingPlanSummary.textContent = blockedLicense ? "静态分析可以查看，但当前许可证策略未放行训练计划、环境或执行。" : needsMapping ? "请先在仓库静态分析中确认训练入口；系统会创建新的可追溯分析 revision，再允许生成计划。" : blockedAnalysis ? "仓库静态分析仍有未解决风险；请先审阅证据或更换来源，不能绕过分析生成计划。" : entries.length ? `将以 ${entries[0].path} 作为计划入口；生成后仍需你核对并批准 digest。` : "当前分析没有可用训练入口，不能生成计划。"; return; }
  const plan = view.plan || {}; const status = view.stale ? "已过期" : view.effective_status === "approved" ? "已批准" : view.effective_status === "awaiting_approval" ? "待批准" : statusLabel(view.effective_status);
  ui.trainingPlanState.textContent = status; ui.trainingPlanSummary.textContent = view.stale ? "任务规格或模型来源已经变化，旧计划和审批仍保留但不能继续使用。" : "计划已绑定当前来源和分析；批准只对下面显示的精确 digest 生效。";
  appendFact(ui.trainingPlanFacts, "Revision", `r${plan.revision || "—"} · ${shortId(plan.training_plan_revision_id)}`); appendFact(ui.trainingPlanFacts, "入口", (plan.entrypoint?.argv || []).join(" "), { code: true }); appendFact(ui.trainingPlanFacts, "资源预算", `${formatBytes(plan.resource_budget?.ram_bytes)} RAM · ${formatBytes(plan.resource_budget?.disk_bytes)} 磁盘`); appendFact(ui.trainingPlanFacts, "执行边界", `${plan.execution_policy?.backend || "—"} · CPU-only`); appendFact(ui.trainingPlanFacts, "Plan Digest", plan.plan_sha256, { code: true });
  ui.approveTrainingPlanButton.hidden = view.effective_status !== "awaiting_approval" || view.stale; ui.approveTrainingPlanButton.disabled = view.stale; ui.trainingPlanDecisionActions.hidden = view.effective_status !== "awaiting_approval" || view.stale;
}
async function createTrainingPlan() {
  if (!state.task?.model_binding) { showNotice("请先选择并绑定模型来源。"); return; }
  if (state.task.training_plan?.stale) { reviseTrainingPlan(); return; }
  if (["needs_input", "needs_manual_mapping"].includes(state.task.repository_analysis?.status)) { showNotice("请先完成仓库分析入口映射。"); return; }
  if (state.task.repository_analysis?.status !== "complete") { showNotice("仓库静态分析仍有未解决风险，不能生成训练计划。"); return; }
  setButtonBusy(ui.createTrainingPlanButton, true, "正在生成计划"); try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/training-plans`, { method: "POST", json: { base_spec_revision: state.task.current_spec_revision } }); showNotice("训练计划草案已生成；请核对入口、资源预算和 digest。", "ok"); await refreshSelected({ force: true }); } catch (error) { showNotice(`计划生成失败：${error.message}`); await refreshSelected({ force: true }); } finally { setButtonBusy(ui.createTrainingPlanButton, false, ""); }
}
function reviseTrainingPlan(changes = {}) {
  const view = state.task?.training_plan; const parent = view?.plan;
  if (!parent) { showNotice("当前没有可修订的训练计划。"); return; }
  const detectedEntrypoint = state.task?.repository_analysis?.training_entrypoints?.[0]?.path;
  const manualEntrypoint = ui.manualEntrypointInput.value.trim();
  const entrypointPath = changes.entrypoint_path || manualEntrypoint || detectedEntrypoint || parent.entrypoint?.argv?.[1];
  const payload = {
    base_spec_revision: state.task.current_spec_revision,
    expected_parent_sha256: parent.plan_sha256,
    entrypoint_path: entrypointPath,
  };
  if (changes.hyperparameters) payload.hyperparameters = changes.hyperparameters;
  if (changes.resource_budget) payload.resource_budget = changes.resource_budget;
  openSimpleDialog({
    kicker: "创建不可变计划 revision", title: `从 r${parent.revision} 生成新计划？`,
    body: `父计划 digest：${parent.plan_sha256}。新 revision 会绑定当前 TaskSpec、来源快照与分析证据；旧计划和旧审批继续保留，但不会授权新计划。`,
    allowLabel: "生成新 revision",
    onAllow: async () => {
      await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/training-plans/${encodeURIComponent(parent.training_plan_revision_id)}/revisions`, { method: "POST", json: payload });
      showNotice("新的训练计划 revision 已生成；必须重新核对并批准新 digest。", "ok");
      await refreshSelected({ force: true });
    },
  });
}
function approveTrainingPlan() {
  const plan = state.task?.training_plan?.plan; if (!plan) { showNotice("当前没有可批准的训练计划。"); return; }
  openSimpleDialog({ kicker: "批准不可变训练计划", title: "确认批准当前 Plan Digest？", body: `你批准的是 ${plan.plan_sha256}。任何入口、参数、资源或权限变化都会生成新 revision，并使本次批准失效。批准后只进行本机资源检查，不会执行仓库代码。`, allowLabel: "批准当前 Digest", onAllow: async () => { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/training-plans/${encodeURIComponent(plan.training_plan_revision_id)}/decisions`, { method: "POST", json: { decision: "approve", expected_plan_sha256: plan.plan_sha256, reason: "用户在产品界面确认" } }); showNotice("当前训练计划 digest 已批准；下一步检查本机资源。", "ok"); await refreshSelected({ force: true }); } });
}
function decideTrainingPlan(decision) {
  const plan = state.task?.training_plan?.plan; if (!plan) { showNotice("当前没有可处理的训练计划。"); return; }
  const rejected = decision === "reject";
  openSimpleDialog({ kicker: "训练计划决策", title: rejected ? "拒绝当前训练计划？" : "取消当前训练计划？", body: `该决策只绑定当前 digest ${plan.plan_sha256}，不会删除历史证据。后续必须创建或重新批准有效 revision 才能继续。`, allowLabel: rejected ? "确认拒绝" : "确认取消", onAllow: async () => { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/training-plans/${encodeURIComponent(plan.training_plan_revision_id)}/decisions`, { method: "POST", json: { decision, expected_plan_sha256: plan.plan_sha256, reason: rejected ? "用户在产品界面拒绝当前计划" : "用户在产品界面取消当前计划" } }); showNotice(rejected ? "当前计划已拒绝，未授权后续资源检查。" : "当前计划已取消，未授权后续资源检查。", "ok"); await refreshSelected({ force: true }); } });
}
function renderResourceFeasibility(task) {
  const planView = task.training_plan; const feasibility = task.resource_feasibility || {}; const probe = feasibility.resource_probe; const lock = feasibility.environment_lock; const report = feasibility.resource_fit_report; const blockers = feasibility.blockers || [];
  ui.resourceFeasibilityCard.hidden = !planView || planView.effective_status !== "approved" || planView.stale; if (ui.resourceFeasibilityCard.hidden) return;
  clear(ui.resourceFeasibilityFacts); clear(ui.resourceFeasibilityReasons); const decision = report?.decision || (blockers.length ? feasibility.decision : "not_checked");
  ui.resourceFeasibilityState.textContent = decision === "fit" ? "静态预算匹配" : decision === "fit_with_revision" ? "建议调整静态预算" : decision === "not_checked" ? "未检查" : "已阻断";
  ui.resourceFeasibilitySummary.textContent = decision === "fit" ? "当前只证明计划预算与本机资源探测相匹配，可以进入环境构建验证；镜像与依赖尚未拉取，环境尚未构建，不能据此认定本机可训练。" : decision === "fit_with_revision" ? "当前静态预算需要降级。采纳建议会创建新 revision，旧批准立即失效，新计划必须重新批准；仍需后续环境构建验证。" : blockers.length ? blockers[0].message : "点击后读取本机资源事实。探测不会安装依赖、下载权重、构建环境或执行仓库代码。";
  if (probe) { appendFact(ui.resourceFeasibilityFacts, "系统", `${probe.os?.name || "未知"} · ${probe.arch?.name || "未知"}`); appendFact(ui.resourceFeasibilityFacts, "CPU / RAM", `${probe.cpu?.logical_count || "未知"} 线程 · ${formatBytes(probe.ram?.available_bytes)}`); appendFact(ui.resourceFeasibilityFacts, "可用磁盘", formatBytes(probe.disk?.free_bytes)); appendFact(ui.resourceFeasibilityFacts, "Python / Node", `${probe.python?.version || "不可用"} · ${probe.node?.version || "不可用"}`); appendFact(ui.resourceFeasibilityFacts, "容器", probe.container_runtime?.available ? `${probe.container_runtime.runtime} 可用` : probe.container_runtime?.reason || "不可用"); appendFact(ui.resourceFeasibilityFacts, "加速器口径", `${probe.accelerator_policy?.mode || "cpu_only"} · ${(probe.accelerator_policy?.detected || []).join("、") || "未检测到"}`); appendFact(ui.resourceFeasibilityFacts, "Probe Digest", probe.probe_sha256, { code: true }); }
  if (lock) { appendFact(ui.resourceFeasibilityFacts, "基础镜像", lock.base_image_digest, { code: true }); appendFact(ui.resourceFeasibilityFacts, "依赖锁", `${lock.packages?.length || 0} 个 Python 包 · ${lock.system_dependencies?.length || 0} 个系统依赖`); appendFact(ui.resourceFeasibilityFacts, "网络范围", (lock.network_allowlist || []).join("、") || "构建时默认断网"); appendFact(ui.resourceFeasibilityFacts, "Environment", lock.lock_sha256, { code: true }); } if (report) appendFact(ui.resourceFeasibilityFacts, "Fit Report", report.report_sha256, { code: true });
  const needsDigest = blockers.some((item) => item.details?.detector === "base_image_digest_validator"); ui.baseImageDigestField.hidden = !needsDigest;
  blockers.forEach((blocker) => {
    const details = blocker.details || {}; const row = document.createElement("article"); const title = document.createElement("b"); const detail = document.createElement("span");
    title.textContent = blocker.code || details.detector || "资源检查阻断";
    const evidence = [];
    if (details.detector) evidence.push(`检测器 ${details.detector}`);
    if (details.required !== undefined) evidence.push(`需要 ${typeof details.required === "object" ? JSON.stringify(details.required) : details.required}`);
    if (details.observed !== undefined) evidence.push(`实测 ${typeof details.observed === "object" ? JSON.stringify(details.observed) : details.observed}`);
    evidence.push(details.retryable === false ? "不可原地重试" : `恢复动作 ${blocker.retry_action || details.retry_action || "重新探测"}`);
    detail.textContent = evidence.join(" · ") || blocker.message || "后端未返回更多资源事实"; row.append(title, detail); ui.resourceFeasibilityReasons.append(row);
  });
  const reasons = report?.reasons || blockers.flatMap((item) => item.details?.reasons || []); reasons.forEach((reason) => { const row = document.createElement("article"); const title = document.createElement("b"); const detail = document.createElement("span"); title.textContent = reason.code || "资源事实"; detail.textContent = `需要 ${reason.required ?? "—"}，实测 ${reason.observed ?? "—"} ${reason.unit || ""}`; row.append(title, detail); ui.resourceFeasibilityReasons.append(row); });
  const alternatives = report?.alternatives || blockers.flatMap((item) => item.details?.alternatives || []); alternatives.forEach((alternative) => { const row = document.createElement("article"); const title = document.createElement("b"); const detail = document.createElement("span"); title.textContent = alternative.creates_new_plan ? "可执行降级方案" : "外部恢复动作"; detail.textContent = alternative.expected_effect || JSON.stringify(alternative.changes || {}); row.append(title, detail); if (alternative.creates_new_plan) { const apply = document.createElement("button"); apply.type = "button"; apply.className = "text-button"; apply.textContent = "用此建议生成新 revision"; apply.addEventListener("click", () => reviseTrainingPlan(alternative.changes || {})); row.append(apply); } ui.resourceFeasibilityReasons.append(row); });
  ui.checkResourceFeasibilityButton.textContent = blockers.length || probe ? "重新探测并检查" : "检查这台机器";
}
async function checkResourceFeasibility() {
  const plan = state.task?.training_plan?.plan; if (!plan || state.task.training_plan.effective_status !== "approved") { showNotice("请先批准当前训练计划 digest。"); return; }
  const digest = ui.baseImageDigestField.hidden ? null : ui.baseImageDigestInput.value.trim() || null; if (digest && !/^sha256:[0-9a-f]{64}$/.test(digest)) { showNotice("基础镜像必须填写 sha256: 开头的 64 位小写十六进制 digest，不能填写 tag。"); return; }
  setButtonBusy(ui.checkResourceFeasibilityButton, true, "正在读取本机事实"); try { const response = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/resource-feasibility-checks`, { method: "POST", json: { training_plan_revision_id: plan.training_plan_revision_id, expected_plan_sha256: plan.plan_sha256, base_image_digest: digest } }); const decision = response.resource_feasibility?.decision; showNotice(decision === "fit" ? "静态资源预算匹配；下一步仍需拉取镜像、构建环境并做资格验证。" : decision === "fit_with_revision" ? "静态检查给出了降级建议；采纳后需重新批准计划并继续环境验证。" : "资源检查形成了真实阻断，请按事实和恢复动作处理。", decision === "fit" ? "ok" : decision === "fit_with_revision" ? "warn" : "error"); await refreshSelected({ force: true }); } catch (error) { showNotice(`资源检查失败：${error.message}`); await refreshSelected({ force: true }); } finally { setButtonBusy(ui.checkResourceFeasibilityButton, false, ""); }
}
function renderSourceMode() {
  ui.sourceModeTabs.querySelectorAll("[data-source-mode]").forEach((button) => { const active = button.dataset.sourceMode === state.modelSourceMode; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  ui.modelSourceSearchForm.hidden = state.modelSourceMode !== "search"; ui.modelSourceReferenceForm.hidden = state.modelSourceMode !== "reference";
}
function renderModelSourceCandidates() {
  const key = JSON.stringify([state.selectedTaskId, state.modelSourceSearch?.search_id || null, state.modelSourceCandidates.map(modelSourceCandidateIdentity)]);
  if (key === state.modelSourceCandidateRenderKey && ui.modelSourceCandidates.childElementCount === state.modelSourceCandidates.length) return;
  state.modelSourceCandidateRenderKey = key; clear(ui.modelSourceCandidates); const selectionContext = modelSourceSelectionContext();
  state.modelSourceCandidates.forEach((candidate) => {
    const article = document.createElement("article"); article.className = "source-candidate"; article.dataset.searchId = selectionContext.searchId || ""; article.dataset.candidateId = candidate.candidate_id; const header = document.createElement("div"); const identity = document.createElement("span"); const provider = document.createElement("i"); const name = document.createElement("b"); const license = document.createElement("em");
    provider.textContent = candidate.provider === "huggingface" ? "HF" : "GH"; name.textContent = candidate.repository; name.title = candidate.repository; identity.append(provider, name); license.textContent = candidate.license_status === "known" ? candidate.license : "License 待审"; license.dataset.state = candidate.license_status; header.append(identity, license);
    const description = document.createElement("p"); description.textContent = candidate.description || "官方目录未提供描述"; const reasons = document.createElement("ul"); [...(candidate.why_shortlisted || []).slice(0, 2), ...(candidate.cautions || []).slice(0, 1)].forEach((text, index) => { const item = document.createElement("li"); item.textContent = text; if (index >= Math.min((candidate.why_shortlisted || []).length, 2)) item.dataset.caution = "true"; reasons.append(item); });
    const select = document.createElement("button"); select.type = "button"; select.className = "secondary-button full-button"; select.dataset.searchId = selectionContext.searchId || ""; select.dataset.candidateId = candidate.candidate_id; select.textContent = "选择并解析固定版本"; select.addEventListener("click", () => confirmSourceCandidate(candidate, selectionContext)); article.append(header, description, reasons, select); ui.modelSourceCandidates.append(article);
  });
}
async function searchModelSources(event) {
  event.preventDefault(); const providers = []; if (ui.searchHfProvider.checked) providers.push("huggingface"); if (ui.searchGithubProvider.checked) providers.push("github"); if (!providers.length) { showNotice("请至少选择一个官方模型目录。"); return; }
  if (!state.task || state.task.capability_decision?.status !== "resolved") { showNotice("请先确认任务理解，再搜索模型来源。"); return; }
  const operation = ++state.modelSourceOperationSeq; hideNotice(); state.modelSourceSearchInFlight = true; setButtonBusy(ui.modelSourceSearchButton, true, "正在联网搜索"); state.modelSourceSearch = null; state.modelSourceCandidates = []; renderModelSource(state.task); syncAgentCheckpoint(state.task); ui.modelSourceSearchEvidence.textContent = "正在请求官方 Provider 目录；尚未产生候选证据。";
  try {
    const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-source-searches`, { method: "POST", headers: modelSourceHeaders(), json: { query: ui.modelSourceSearchInput.value.trim() || null, providers, limit_per_provider: 4, base_spec_revision: state.task.current_spec_revision } });
    if (operation !== state.modelSourceOperationSeq) return; state.modelSourceSearch = result; state.modelSourceCandidates = result.candidates || []; renderModelSource(state.task); syncAgentCheckpoint(state.task); if (!state.modelSourceCandidates.length) showNotice("官方目录没有返回候选，请修改搜索词或粘贴模型地址。"); else hideNotice();
  } catch (error) { if (operation !== state.modelSourceOperationSeq) return; state.modelSourceSearch = null; state.modelSourceCandidates = []; renderModelSource(state.task); syncAgentCheckpoint(state.task); showNotice(`真实搜索失败：${error.message}`); await refreshSelected({ force: true }); }
  finally { if (operation === state.modelSourceOperationSeq) { state.modelSourceSearchInFlight = false; setButtonBusy(ui.modelSourceSearchButton, false, ""); } }
}
function confirmSourceCandidate(candidate, selectionContext = modelSourceSelectionContext()) {
  const { taskId, searchId, baseSpecRevision } = selectionContext;
  if (!taskId || !searchId || !candidate?.candidate_id || taskId !== state.selectedTaskId || searchId !== state.modelSourceSearch?.search_id || baseSpecRevision !== state.task?.current_spec_revision) { showNotice("这组候选已更新，请从当前搜索结果重新选择。"); return; }
  openSimpleDialog({ kicker: "选择模型来源", title: `确认选择 ${candidate.repository}？`, body: `当前只是目录候选。确认后系统会通过 ${candidate.provider} 官方接口把 ${candidate.requested_revision} 解析为固定 commit；仍不会下载权重或执行仓库代码。`, allowLabel: "确认并解析", onAllow: async () => {
    if (taskId !== state.selectedTaskId || searchId !== state.modelSourceSearch?.search_id || baseSpecRevision !== state.task?.current_spec_revision) { showNotice("搜索结果已变化，未提交旧候选。请重新选择。"); return; }
    const operation = ++state.modelSourceOperationSeq; const response = await request(`/tasks/${encodeURIComponent(taskId)}/model-source-selections`, { method: "POST", headers: modelSourceHeaders(candidate.provider), json: { search_id: searchId, candidate_id: candidate.candidate_id, approval_confirmed: true, base_spec_revision: baseSpecRevision } });
    if (operation !== state.modelSourceOperationSeq) return; clearModelSourceTokens(); state.modelSourceCandidates = []; showNotice(`已解析 ${response.resolution.repository} 的固定 commit，请检查后再批准绑定。`, "ok"); await refreshSelected({ force: true });
  } });
}
async function resolveModelSourceReference(event) {
  event.preventDefault(); const value = ui.modelSourceReferenceInput.value.trim(); if (!value) { showNotice("请输入 Hugging Face 或 GitHub 的公开地址。"); return; }
  let provider = null; try { const host = new URL(value).hostname.toLowerCase(); provider = host.endsWith("github.com") ? "github" : host.endsWith("huggingface.co") ? "huggingface" : null; } catch (_error) { provider = null; }
  if (!provider) { showNotice("当前只接受 https://huggingface.co 或 https://github.com 地址。"); return; }
  const operation = ++state.modelSourceOperationSeq; setButtonBusy(ui.modelSourceResolveButton, true, "正在解析");
  try { const response = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-source-resolutions`, { method: "POST", headers: modelSourceHeaders(provider), json: { source_reference: value, requested_revision: ui.modelSourceRevisionInput.value.trim() || null, base_spec_revision: state.task.current_spec_revision } }); if (operation !== state.modelSourceOperationSeq) return; clearModelSourceTokens(); showNotice(`已固定到 ${shortId(response.resolution.resolved_commit)}，请检查并批准绑定。`, "ok"); await refreshSelected({ force: true }); }
  catch (error) { if (operation !== state.modelSourceOperationSeq) return; showNotice(`来源解析失败：${error.message}`); await refreshSelected({ force: true }); }
  finally { if (operation === state.modelSourceOperationSeq) setButtonBusy(ui.modelSourceResolveButton, false, ""); }
}
function approveModelSourceBinding(resolution, { retry = false } = {}) {
  if (!resolution || !fixedCommit(resolution.resolved_commit)) { showNotice("没有可批准的固定模型来源。"); return; }
  openSimpleDialog({ kicker: retry ? "重试失败的绑定分析" : "建立不可变来源快照", title: `${retry ? "重试" : "批准绑定"} ${resolution.repository}？`, body: `${retry ? "将为同一固定版本创建新的可追溯 Attempt；旧失败证据不会被覆盖。" : ""}系统将读取固定 commit ${resolution.resolved_commit} 的文件树和有限文本文件，校验 Manifest 并做静态分析。不会执行第三方代码，也不会下载模型权重。`, allowLabel: retry ? "重试同一固定版本" : "批准读取并绑定", onAllow: async () => {
    const operation = ++state.modelSourceOperationSeq; const response = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/model-source-resolutions/${encodeURIComponent(resolution.resolution_id)}/bind`, { method: "POST", headers: modelSourceHeaders(resolution.provider), json: { approval_confirmed: true, expected_resolved_commit: resolution.resolved_commit, base_spec_revision: state.task.current_spec_revision } }); if (operation !== state.modelSourceOperationSeq) return; clearModelSourceTokens(); const attemptId = response.binding_attempt?.attempt?.attempt_id; showNotice(`${resolution.repository} 已进入固定版本读取与静态分析队列${attemptId ? `（${shortId(attemptId)}）` : ""}；完成前不会显示为已绑定，也不会执行仓库代码。`, "ok"); await refreshSelected({ force: true });
  } });
}
function bindPendingModelSource() {
  approveModelSourceBinding(latestPendingResolution(state.task));
}
function retryFailedModelSourceBinding() {
  const attempt = bindingAnalysisAttempt(state.task); const status = attempt?.current_state?.status; const resolutionId = attempt?.attempt?.resolution_id;
  if (!["failed", "cancelled"].includes(status) || !resolutionId) return false;
  const resolution = state.modelSourceResolutions.find((item) => item.resolution_id === resolutionId);
  if (!resolution) { showNotice("找不到失败 Attempt 对应的固定来源，请刷新后重试或重新选择模型。"); return true; }
  approveModelSourceBinding(resolution, { retry: true }); return true;
}
function addModelAssetFact(label, value, { code = false } = {}) {
  const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label;
  const selected = document.createElement(code ? "code" : "b"); selected.textContent = value || "—"; selected.title = selected.textContent;
  row.append(name, selected); ui.modelAssetFacts.append(row);
}
function renderModelAsset(task) {
  const binding = task.model_asset_binding || null; const applicable = !task.model_binding && (isImageClassificationTask(task) || Boolean(binding));
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
  state.evidenceLoaded = true; if (state.task) { renderResult(state.task); renderConversation(true); }
}
async function refreshEvaluation() {
  const taskId = state.selectedTaskId; const runId = state.task?.current_run_id; if (!taskId || !runId) return; setButtonBusy(ui.refreshEvaluationButton, true, "正在复核");
  try { const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/evaluation-report`); state.evaluationReport = response.evaluation_report; delete state.evidenceErrors.evaluation; renderResult(state.task); renderConversation(true); showNotice("可信评测报告已按当前运行证据重新读取。", "ok"); }
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
  const originalGoal = state.taskSpecRevisions[0]?.business_goal || task.business_goal;
  return { items: [{ kind: "message", role: "user", text: originalGoal, time: task.created_at_utc }], pending: [], running: false };
}
function taskEvidenceTimeline(task) {
  const timeline = []; const revisions = state.taskSpecRevisions.length ? state.taskSpecRevisions : task.task_spec ? [task.task_spec] : [];
  revisions.forEach((spec, index) => {
    const decision = spec.capability_decision || {}; const capability = spec.capability_request || {}; const note = String(spec.user_note || "");
    const selectedCandidate = decision.candidates?.find((item) => item.family === decision.selected_family);
    const confirmedOutput = selectedCandidate?.output || (capability.target_kind && capability.target_kind !== "待确认输出" ? capability.target_kind : selectedCandidate?.label || decision.selected_family || "已确认输出");
    const systemOnlyNote = /^用户通过产品界面(?:修订|确认)$/u.test(note);
    if (index > 0 && note && !systemOnlyNote) timeline.push({ kind: "message", role: "user", evidenceKey: `spec:${spec.revision}:user`, text: note.replace(/^用户(?:补充|选择后端候选|确认后端候选)[:：]?/u, "").trim() || note, time: spec.created_at_utc });
    if (decision.status === "resolved") timeline.push({ kind: "message", role: "assistant", evidenceKey: `spec:${spec.revision}`, text: `需求版本 v${spec.revision} 已确认：${capability.modality || "未知输入"} / ${decision.selected_family || capability.objective || "训练任务"} / ${confirmedOutput}。完整技术字段已写入训练详情。`, time: spec.created_at_utc || task.created_at_utc });
    else if (index > 0) timeline.push({ kind: "message", role: "assistant", evidenceKey: `spec:${spec.revision}`, text: `需求版本 v${spec.revision} 已根据补充重新判定。当前仍需确认：${decision.question || "模型唯一输出"}`, time: spec.created_at_utc });
  });
  [...state.modelSourceSearches].sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || ""))).forEach((search) => {
    const errors = search.provider_errors || []; const count = search.candidates?.length || 0;
    const allProvidersFailed = Boolean(errors.length && errors.length >= (search.providers?.length || 1));
    timeline.push({ kind: "tool", status: count ? "completed" : allProvidersFailed ? "failed" : "completed_empty", evidenceKey: search.search_id, label: "官方模型目录搜索", detail: `${search.query_plan?.effective_query || "自动搜索词"} · ${count} 个候选${errors.length ? ` · ${errors.length} 个 Provider 返回错误` : ""} · ${search.search_id}`, time: search.created_at });
  });
  const binding = task.model_binding;
  if (binding) timeline.push({ kind: "tool", status: binding.status === "stale" ? "failed" : "completed", evidenceKey: binding.binding_revision_id || binding.resolution_id, label: "固定模型来源", detail: `${binding.repository} @ ${shortId(binding.resolved_commit)} · ${binding.status === "stale" ? "已因新规格失效" : "不可变版本已绑定"}`, time: binding.created_at });
  const analysis = task.repository_analysis; const analysisAttempt = bindingAnalysisAttempt(task);
  if (analysis) timeline.push({ kind: "tool", status: analysis.status === "complete" && !(analysis.downstream_blockers || []).length ? "completed" : "failed", evidenceKey: analysis.analysis_digest || analysis.analysis_id, label: "仓库静态分析", detail: `${REPOSITORY_ANALYSIS_STATUS_LABELS[analysis.status] || analysis.status || "未知状态"} · ${(analysis.training_entrypoints || []).length} 个训练入口 · digest ${shortId(analysis.analysis_digest)}`, time: analysis.created_at || analysisAttempt?.current_state?.updated_at || binding?.created_at });
  else if (analysisAttempt) {
    const attemptStatus = analysisAttempt.current_state?.status || "queued"; const failure = analysisAttempt.current_state?.failure; const attemptId = analysisAttempt.attempt?.attempt_id;
    timeline.push({ kind: "tool", status: ["failed", "cancelled"].includes(attemptStatus) ? "failed" : attemptStatus === "completed" ? "completed" : "running", evidenceKey: attemptId, label: "绑定并分析模型来源", detail: `${attemptStatus} · attempt ${shortId(attemptId)}${failure ? ` · ${failure.code || "unknown_failure"}: ${failure.message || "没有错误详情"}` : " · 尚未执行第三方代码"}`, time: analysisAttempt.current_state?.updated_at || analysisAttempt.attempt?.created_at });
  }
  const planView = task.training_plan; const plan = planView?.plan;
  if (plan) {
    timeline.push({ kind: "tool", status: planView.stale ? "failed" : "completed", evidenceKey: plan.training_plan_revision_id, label: "生成不可变训练计划", detail: `r${plan.revision} · digest ${shortId(plan.plan_sha256)}${planView.stale ? " · 已失效" : ""}`, time: plan.created_at });
    if (planView.latest_approval) timeline.push({ kind: "tool", status: planView.latest_approval.decision === "approve" ? "completed" : "failed", evidenceKey: planView.latest_approval.approval_id, label: "训练计划精确审批", detail: `${planView.latest_approval.decision} · 绑定 digest ${shortId(planView.latest_approval.plan_sha256 || plan.plan_sha256)}`, time: planView.latest_approval.created_at });
  }
  const feasibility = task.resource_feasibility || {}; const probe = feasibility.resource_probe; const report = feasibility.resource_fit_report; const blockers = feasibility.blockers || [];
  if (probe) timeline.push({ kind: "tool", status: "completed", evidenceKey: probe.probe_sha256, label: "本机资源探测", detail: `${probe.cpu?.logical_count || "未知"} 线程 · ${formatBytes(probe.ram?.available_bytes)} 可用内存 · digest ${shortId(probe.probe_sha256)}`, time: probe.captured_at });
  if (report || blockers.length) timeline.push({ kind: "tool", status: report?.decision === "fit" ? "completed" : "failed", evidenceKey: report?.report_sha256 || blockers[0]?.blocker_id || `resource:${plan?.training_plan_revision_id}`, label: "训练资源可行性", detail: report ? `${report.decision} · report ${shortId(report.report_sha256)}` : `${feasibility.decision || "blocked"} · ${blockers[0]?.message || blockers[0]?.code || "资源阻断"}`, time: report?.created_at || probe?.captured_at });
  const result = task.current_result; const evaluation = state.evidenceRunId === result?.run_id ? state.evaluationReport || result?.evaluation_report : result?.evaluation_report;
  if (result?.status === "completed" && evaluation) {
    const metrics = metricEntries(result).filter(([value]) => typeof value === "number").map(([value, label]) => `${label} ${value.toFixed(3)}`).join(" · ") || "当前报告没有可展示的核心指标";
    const failure = result.failure_samples?.[0]; const [failureName, failureDetail] = failure ? failureSummary(failure) : ["无", "独立测试集没有记录可展示的失败样本"];
    const conclusion = statusLabel(evaluation.conclusion || result.evaluation_conclusion || "not_evaluated");
    const reasons = [...(evaluation.evidence_reasons || []), ...(evaluation.integrity_errors || [])];
    const gap = reasons.join("；") || (evaluation.release_ready ? "运行、产物、指标与证据充分性均通过" : result.offline_gates_passed ? "离线指标已通过，但交付证据仍未全部满足" : "至少一个离线指标未达到训练合同门槛");
    const next = evaluation.release_ready ? "用一份未参与训练的新样本试跑，确认后生成 Artifact Bundle。" : "在右侧评测报告查看失败样本和门槛差距，再决定补数据、调参数或创建新 Run。";
    const evaluationDigest = evaluation.report_sha256 || evaluation.evaluation_report_id || evaluation.evaluation_id || evaluation.content_sha256 || "embedded-report";
    timeline.push({ kind: "message", role: "assistant", evidenceKey: `result-summary:${result.run_id}:${evaluationDigest}`, text: `本轮真实训练已完成。\n\n结论：${conclusion}\n核心指标：${metrics}\n主要失败样本：${failureName}（${failureDetail}）\n与验收门槛的差距：${gap}\n建议下一步：${next}`, time: evaluation.created_at || result.completed_at || result.updated_at });
  }
  return timeline;
}
function conversationWithEvidence(task, remoteConversation) {
  const base = remoteConversation?.session_id ? remoteConversation : localConversation(task); const items = [...(base.items || [])]; const serialized = JSON.stringify(items);
  taskEvidenceTimeline(task).forEach((item) => { if ((!item.evidenceKey || !serialized.includes(item.evidenceKey)) && (!item.text || !items.some((existing) => existing.text === item.text))) items.push(item); });
  return { ...base, items };
}
function compactConversationItems(items) {
  const compact = []; let completedTools = [];
  const flush = () => {
    if (completedTools.length >= 3) compact.push({ kind: "tool_group", items: completedTools });
    else compact.push(...completedTools);
    completedTools = [];
  };
  items.forEach((item) => {
    if (item.kind === "tool" && item.status === "completed") completedTools.push(item);
    else { flush(); compact.push(item); }
  });
  flush(); return compact;
}
function renderConversation(force = false) {
  const conversation = conversationWithEvidence(state.task, state.conversation);
  const optimistic = state.pendingMessage?.task_id === state.selectedTaskId ? state.pendingMessage : null;
  const renderKey = JSON.stringify({ items: conversation.items?.map((item) => [item.seq, item.status, item.text, item.label, item.detail, item.evidenceKey]), pending: conversation.pending?.map((item) => item.rpc_id), running: conversation.running, optimistic: optimistic?.text, taskStatus: state.task?.status, eventCount: state.runEvents.length });
  if (!force && renderKey === state.lastRenderKey) return; state.lastRenderKey = renderKey;
  const nearBottom = ui.conversation.scrollHeight - ui.conversation.scrollTop - ui.conversation.clientHeight < 120; clear(ui.messageList);
  const items = [...(conversation.items || [])]; if (optimistic && !items.some((item) => item.role === "user" && item.text === optimistic.text)) items.push({ kind: "message", role: "user", text: optimistic.text, time: optimistic.time, optimistic: true });
  compactConversationItems(items).forEach((item) => item.kind === "tool_group" ? renderToolGroup(item.items) : item.kind === "tool" ? renderTool(item) : renderMessage(item)); ui.conversationIntro.hidden = items.length > 0; renderPending(conversation.pending || []); ui.agentWorking.hidden = !conversation.running && !optimistic;
  if (force || nearBottom) requestAnimationFrame(() => { ui.conversation.scrollTop = ui.conversation.scrollHeight; });
}
function renderToolGroup(items) {
  const details = document.createElement("details"); details.className = "tool-history";
  const summary = document.createElement("summary"); const mark = document.createElement("span"); mark.textContent = "✓";
  const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = `已完成 ${items.length} 个准备步骤`; const hint = document.createElement("small"); hint.textContent = `${items[0]?.label || "开始准备"} → ${items.at(-1)?.label || "准备完成"}`; copy.append(title, hint);
  const action = document.createElement("em"); action.textContent = "查看记录"; summary.append(mark, copy, action); details.append(summary);
  const list = document.createElement("div"); list.className = "tool-history-list";
  items.forEach((item) => { const row = document.createElement("div"); const label = document.createElement("b"); label.textContent = item.label; const detail = document.createElement("small"); detail.textContent = item.detail || "真实工具调用已完成"; const time = document.createElement("time"); time.textContent = formatTime(item.time); row.append(label, detail, time); list.append(row); });
  details.append(list); ui.messageList.append(details);
}
function renderMessage(item) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = item.role; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = item.role === "user" ? "你" : "MH";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = item.role === "user" ? "你" : state.runtimeReady ? "训练 Agent" : "Model Studio"; const time = document.createElement("time"); time.textContent = item.optimistic ? "正在提交" : formatTime(item.time); meta.append(author, time);
  const copy = document.createElement("p"); copy.className = "message-copy"; copy.textContent = item.text; body.append(meta, copy); row.append(avatar, body); ui.messageList.append(row);
}
function renderTool(item) {
  const card = document.createElement("article"); card.className = "tool-card"; card.dataset.status = item.status; const icon = document.createElement("span"); icon.className = "tool-icon"; icon.textContent = item.status === "completed" ? "✓" : item.status === "completed_empty" ? "0" : item.status === "failed" ? "!" : "↻";
  const copy = document.createElement("span"); copy.className = "tool-copy"; const title = document.createElement("b"); title.textContent = item.label; const detail = document.createElement("span"); detail.textContent = item.detail || (item.status === "completed" ? "真实工具调用已完成" : item.status === "completed_empty" ? "调用完成，但没有匹配项" : item.status === "failed" ? "工具返回失败" : "正在调用训练工具"); copy.append(title, detail);
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
  const text = message.trim(); if (!text) return; hideNotice(); ui.sendButton.disabled = true; ui.sendButton.dataset.busy = "true";
  try {
    if (!state.selectedTaskId) {
      const created = await request("/tasks", { method: "POST", json: { name: deriveTaskName(text), business_goal: text } }); state.tasks.unshift(created.task); clearDraft(null); ui.messageInput.value = ""; resizeComposer(); await selectTask(created.task.task_id);
      showNotice(created.task.capability_decision?.status === "needs_clarification" ? "任务已创建，但输出形式仍有歧义。请先提交澄清；系统尚未绑定训练方案。" : "任务已创建。请先检查并确认任务理解；确认前不会进入数据或训练。", "ok"); return;
    }
    if (state.taskSpecDescriptionMode && stageKey(state.task) === "task_understanding" && state.task?.capability_decision?.status !== "resolved") {
      const taskId = state.selectedTaskId; const spec = state.task.task_spec; const originalGoal = spec.business_goal.trim(); const nextGoal = `${originalGoal}\n\n用户补充：${text}`;
      state.pendingMessage = { task_id: taskId, text, time: Date.now() }; renderConversation(true);
      const response = await request(`/tasks/${encodeURIComponent(taskId)}/spec`, { method: "PATCH", json: { base_revision: spec.revision, business_goal: nextGoal, user_note: `用户补充：${text}` } });
      state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; state.pendingMessage = null; clearDraft(taskId); ui.messageInput.value = ""; resizeComposer(); await refreshTaskSpecView(response.task); showNotice(`补充说明已写入需求版本 v${response.task.current_spec_revision}，系统已重新判定。`, "ok"); return;
    }
    if (!state.runtimeReady) { showNotice("当前是本地流程模式：需求快捷选项、模型搜索、数据导入、合同确认和训练操作仍可用；只有自由对话需要 Agent Runtime。任务事实没有被伪造。"); return; }
    const taskId = state.selectedTaskId; state.pendingMessage = { task_id: taskId, text, time: Date.now() }; renderConversation(true); await request(`/tasks/${encodeURIComponent(taskId)}/conversation/messages`, { method: "POST", json: { message: text } }); clearDraft(taskId); if (state.selectedTaskId === taskId) { ui.messageInput.value = ""; resizeComposer(); } window.setTimeout(() => refreshSelected({ force: true }), 250);
  } catch (error) { if (state.pendingMessage?.task_id === state.selectedTaskId) state.pendingMessage = null; saveDraft(); renderConversation(true); showNotice(`${error.message}。任务事实不会被伪造。`); }
  finally { ui.sendButton.disabled = false; ui.sendButton.dataset.busy = "false"; }
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

async function openTaskSpecDialog({ editing = false } = {}) {
  const task = state.task; const spec = task?.task_spec; const decision = task?.capability_decision || {}; if (!spec) return;
  if (editing && !state.taskSpecFamilies.length) {
    setButtonBusy(ui.editTaskSpecButton, true, "正在加载模型类型");
    const loaded = await loadTaskSpecFamilies();
    setButtonBusy(ui.editTaskSpecButton, false, "");
    if (!loaded || !state.taskSpecFamilies.length) { showNotice(`模型类型目录加载失败：${state.taskSpecFamiliesError || "没有返回可选类型"}。请重试。`); return; }
  }
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = editing ? "修订任务规格" : decision.status === "needs_clarification" ? "澄清模型输出" : "确认任务理解"; ui.dialogTitle.textContent = editing ? "修改任务描述或输出形式" : decision.question || "确认候选任务规格";
  const goalBlock = document.createElement("section"); goalBlock.className = "question-block"; const goalTitle = document.createElement("b"); goalTitle.textContent = "业务目标"; const goalInput = document.createElement("textarea"); goalInput.className = "question-custom"; goalInput.rows = 3; goalInput.value = spec.business_goal; goalInput.disabled = !editing; goalBlock.append(goalTitle, goalInput); ui.dialogBody.append(goalBlock);
  const familyBlock = document.createElement("section"); familyBlock.className = "question-block"; const familyTitle = document.createElement("b"); familyTitle.textContent = "模型唯一输出"; const options = document.createElement("div"); options.className = "question-options";
  const currentCandidate = (decision.candidates || []).find((item) => item.family === decision.selected_family) || (decision.selected_family ? { family: decision.selected_family, label: decision.selected_family, output: spec.capability_request?.target_kind || "当前任务输出" } : null);
  const candidates = editing ? [...state.taskSpecFamilies] : [...(decision.candidates || [])];
  if (currentCandidate && !candidates.some((item) => item.family === currentCandidate.family)) candidates.unshift(currentCandidate);
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
    openInspector("plan"); await refreshSelected({ force: true });
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
      openInspector("plan"); await refreshSelected({ force: true });
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
        method: "POST", json: { decision: "approved", actor: "local-user", reason: "approved in Specialist Model Studio UI", candidate_digest: build.candidate_digest, validation_digest: build.validation_digest },
      });
      showNotice("版本化 Recipe / Data Adapter 已注册；原任务现在可以导入正式训练数据。", "ok");
      await refreshSelected({ force: true });
    },
  });
}
function performNextAction() {
  const action = state.task?.control?.next_action?.id;
  if (["clarify_task_spec", "confirm_task_spec"].includes(action)) { scrollToCheckpoint(); return; }
  if (action === "upload_dataset") { ui.datasetInput.click(); return; }
  if (action === "stage_recipe_samples") { ui.recipeSampleInput.click(); return; }
  if (action === "start_recipe_build") { startRecipeBuild(); return; }
  if (action === "approve_recipe_registration") { approveRecipeRegistration(); return; }
  if (["review_capability_gap", "search_model_sources", "approve_model_source_binding", "replace_model_source", "review_repository_analysis", "retry_model_source_search", "edit_or_retry_model_source", "retry_model_source_binding", "review_or_retry_repository_analysis", "create_training_plan", "approve_training_plan", "revise_training_plan", "create_revised_training_plan", "map_training_entrypoint", "check_resource_feasibility", "review_resource_feasibility", "provide_base_image_digest", "install_or_start_oci_runtime_then_retry"].includes(action)) { openInspector("plan"); return; }
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
function activateContext(name) { const selected = name === "capability" ? "plan" : name; document.querySelectorAll("[data-context]").forEach((button) => button.classList.toggle("active", button.dataset.context === selected)); document.querySelectorAll("[data-context-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.contextPanel === selected)); ui.inspectorSheetTitle.textContent = ({ plan: "任务方案", data: "数据检查", run: "训练现场", evaluation: "评测报告", artifacts: "交付产物" })[selected] || "训练详情"; }
function setMobileView(name) { [ui.mobileConversationButton, ui.mobileContextButton, ui.mobileResultButton].forEach((button) => { const active = button.dataset.mobileView === name; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); }
function mobileWorkspace() { return inspectorMedia.matches; }
function overlayWorkspace() { return !dockedWorkspaceMedia.matches; }
function syncInspectorIsolation() {
  const isolated = overlayWorkspace() && ui.inspector.dataset.open === "true";
  ui.sidebar.inert = isolated; ui.conversationMain.inert = isolated; ui.mobileViewNav.inert = isolated;
  if (isolated) { ui.inspector.setAttribute("role", "dialog"); ui.inspector.setAttribute("aria-modal", "true"); }
  else { ui.inspector.removeAttribute("role"); ui.inspector.removeAttribute("aria-modal"); }
}
function inspectorFocusables() {
  return [...ui.inspector.querySelectorAll(INSPECTOR_FOCUSABLE)].filter((element) => !element.hidden && !element.disabled && element.getClientRects().length > 0);
}
function handleInspectorKeydown(event) {
  if (ui.inspector.dataset.open !== "true" || !overlayWorkspace() || ui.decisionDialog.open) return;
  if (event.key === "Escape") { event.preventDefault(); closeInspector(); return; }
  if (event.key !== "Tab") return;
  const focusable = inspectorFocusables();
  if (!focusable.length) { event.preventDefault(); ui.closeInspectorButton.focus(); return; }
  const first = focusable[0]; const last = focusable[focusable.length - 1]; const active = document.activeElement;
  if (event.shiftKey && (active === first || !ui.inspector.contains(active))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (active === last || !ui.inspector.contains(active))) { event.preventDefault(); first.focus(); }
}
function openInspector(context = "plan") {
  if (!state.selectedTaskId) return; const opening = ui.inspector.dataset.open !== "true";
  if (opening && document.activeElement instanceof HTMLElement && document.activeElement !== document.body && !ui.inspector.contains(document.activeElement)) state.inspectorOpener = document.activeElement;
  ui.inspector.hidden = false; ui.inspector.inert = false; ui.inspector.setAttribute("aria-hidden", "false"); activateContext(context); ui.inspector.dataset.open = "true"; document.body.dataset.workspace = "open"; ui.inspectorScrim.hidden = dockedWorkspaceMedia.matches; ui.workspaceToggleButton.setAttribute("aria-expanded", "true"); ui.workspaceToggleButton.setAttribute("aria-label", "关闭任务工作区"); setMobileView(["evaluation", "artifacts"].includes(context) ? "result" : "context");
  syncInspectorIsolation();
  if (opening && overlayWorkspace()) window.requestAnimationFrame(() => ui.closeInspectorButton.focus());
}
function closeInspector() {
  const wasOpen = ui.inspector.dataset.open === "true"; const opener = state.inspectorOpener; state.inspectorOpener = null;
  ui.inspector.dataset.open = "false"; document.body.dataset.workspace = "closed"; ui.inspector.inert = true; ui.inspector.setAttribute("aria-hidden", "true"); ui.inspectorScrim.hidden = true; ui.workspaceToggleButton.setAttribute("aria-expanded", "false"); ui.workspaceToggleButton.setAttribute("aria-label", "打开任务工作区"); setMobileView("conversation");
  syncInspectorIsolation();
  const restoreTarget = opener?.isConnected && !opener.disabled ? opener : ui.workspaceToggleButton;
  if (wasOpen && restoreTarget?.isConnected && !restoreTarget.disabled) window.requestAnimationFrame(() => restoreTarget.focus());
}
function openAllModelSourceCandidates() { openInspector("plan"); ui.modelSourceDiscovery.open = true; window.requestAnimationFrame(() => { ui.modelSourceCard.scrollIntoView({ block: "start", behavior: "smooth" }); if (!mobileWorkspace()) ui.modelSourceCandidates.focus({ preventScroll: true }); }); }
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
ui.modelSourceSearchForm.addEventListener("submit", searchModelSources); ui.modelSourceReferenceForm.addEventListener("submit", resolveModelSourceReference); ui.bindModelSourceButton.addEventListener("click", bindPendingModelSource); ui.cancelModelBindingButton.addEventListener("click", cancelModelBindingAttempt);
ui.viewAllModelSourceCandidatesButton.addEventListener("click", openAllModelSourceCandidates);
ui.repositoryManualMapping.addEventListener("submit", applyRepositoryManualMapping);
ui.createTrainingPlanButton.addEventListener("click", createTrainingPlan); ui.approveTrainingPlanButton.addEventListener("click", approveTrainingPlan); ui.rejectTrainingPlanButton.addEventListener("click", () => decideTrainingPlan("reject")); ui.cancelTrainingPlanButton.addEventListener("click", () => decideTrainingPlan("cancel"));
ui.checkResourceFeasibilityButton.addEventListener("click", checkResourceFeasibility);
ui.sourceModeTabs.addEventListener("click", (event) => { const button = event.target.closest("[data-source-mode]"); if (!button) return; state.modelSourceMode = button.dataset.sourceMode; renderSourceMode(); (state.modelSourceMode === "search" ? ui.modelSourceSearchInput : ui.modelSourceReferenceInput).focus(); });
ui.modelSourceRetryButton.addEventListener("click", () => { if (retryFailedModelSourceBinding()) return; ui.modelSourceDiscovery.open = true; if (modelSourceBlocker(state.task)?.stage === "source_resolution") { state.modelSourceMode = "reference"; renderSourceMode(); ui.modelSourceReferenceInput.focus(); } else { state.modelSourceMode = "search"; renderSourceMode(); ui.modelSourceSearchInput.focus(); } });
ui.hfSearchForm.addEventListener("submit", searchHfModels); ui.hfAttachButton.addEventListener("click", attachHfModel); ui.modelAssetVerifyButton.addEventListener("click", verifyModelAsset);
ui.refreshEvaluationButton.addEventListener("click", refreshEvaluation); ui.sampleTrialSelectButton.addEventListener("click", () => ui.sampleTrialInput.click());
ui.sampleTrialInput.addEventListener("change", () => state.task && renderResult(state.task)); ui.sampleTrialRunButton.addEventListener("click", runSampleTrial); ui.buildArtifactBundleButton.addEventListener("click", buildArtifactBundle);
ui.nextActionButton.addEventListener("click", performNextAction); ui.taskBlockerActionButton.addEventListener("click", performNextAction);
ui.agentCheckpointWorkspaceButton.addEventListener("click", () => { openInspector(ui.agentCheckpointWorkspaceButton.dataset.context || "plan"); revealCurrentWorkspaceObject(); });
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
ui.workspaceToggleButton.addEventListener("click", () => ui.inspector.dataset.open === "true" ? closeInspector() : openInspector("plan"));
ui.mobileConversationButton.addEventListener("click", closeInspector); ui.mobileContextButton.addEventListener("click", () => openInspector("plan")); ui.mobileResultButton.addEventListener("click", () => openInspector("evaluation"));
document.addEventListener("keydown", handleInspectorKeydown);
inspectorMedia.addEventListener("change", () => { syncInspectorIsolation(); if (mobileWorkspace() && ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus()); });
dockedWorkspaceMedia.addEventListener("change", () => {
  if (ui.inspector.dataset.open === "true") ui.inspectorScrim.hidden = dockedWorkspaceMedia.matches;
  syncInspectorIsolation();
  if (dockedWorkspaceMedia.matches && state.task) { state.workspaceAutoKey = null; syncWorkspaceForTask(state.task); }
  else if (ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus());
});
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { ui.messageInput.value = button.dataset.prompt; resizeComposer(); ui.messageInput.focus(); }));

async function boot() { restoreDraft(null); await Promise.all([loadRuntime(), loadHfCapability(), loadModelSourceProviders(), loadTaskSpecFamilies(), loadTasks({ selectFromUrl: true })]); if (!state.selectedTaskId) enterHomeState({ focusComposer: false }); resizeComposer(); }
boot().catch((error) => showNotice(`页面初始化失败：${error.message}`));
