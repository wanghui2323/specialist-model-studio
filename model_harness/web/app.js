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
  "emptyState", "conversation", "conversationIntro", "messageList",
  "workspaceToggleButton", "workspaceExperience", "workspaceEyebrow", "workspaceTitle", "workspacePhaseBadge", "workspaceSummary", "workspaceTeam", "workspaceTeamTitle", "workspaceTeamCount", "workspaceTeamList", "workspaceResults", "workspaceResultsTitle", "workspaceResultCount", "workspaceResultList", "workspaceTechnicalButton", "workspaceTruthNote", "agentCheckpoint", "agentCheckpointStage", "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointSummary", "agentCheckpointBody", "agentCheckpointActions", "agentCheckpointWorkspaceButton", "agentCheckpointWorkspaceLabel", "agentCheckpointWorkspaceHint", "homeComposerSlot", "homeBoundary", "homeTrainingProof", "composerWrap",
  "agentWorking", "agentWorkingLabel", "cancelAgentButton", "composerForm", "composerNotice", "composerDelivery", "composerDeliveryLabel", "composerDeliveryDetail", "messageInput", "sendButton", "composerMode", "composerModeLabel",
  "datasetButton", "datasetButtonLabel", "datasetInput", "recipeSampleInput", "inspectorDatasetButton", "inspectorEmpty", "inspectorContent", "objectViewer", "objectViewerTitle", "objectViewerState", "objectViewerSummary", "objectViewerIdentity", "objectViewerJson", "taskStatus", "contextTabs",
  "capabilityState", "capabilitySummary", "capabilityFacts", "capabilityAxes", "diagnosticCapabilityState", "diagnosticCapabilityReason", "trainingCapabilityState", "trainingCapabilityReason", "capabilityRecovery", "capabilityNonAction", "datasetCard", "datasetCount", "datasetSummary", "contractCard", "contractState",
  "scaffoldRecipeButton",
  "gateGrid", "confirmations", "confirmContractButton", "approveRunProposalButton", "runEventCount", "inspectorEvents", "resultCard",
  "gateResult", "metricGrid", "runId", "artifactCount", "artifactList", "decisionDialog", "dialogKicker", "dialogTitle", "dialogBody", "dialogActions",
  "taskSpecCard", "taskSpecHeading", "taskSpecStatus",
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
  conversationStream: null, conversationStreamCursor: null, conversationStreamRevision: null, conversationStreamTaskId: null, conversationStreamDegraded: false, conversationFallbackTimer: null, conversationReconnectTimer: null,
  conversationReconcileInFlight: false, conversationReconcileSeq: 0, conversationReconcilePromise: null,
  pendingMessage: null, messageSubmission: null, messageRequestSequence: 0, cancelRequestInFlight: false, lastRenderKey: "", selectionToken: 0, hfCapability: null, hfModels: [], hfCard: null,
  modelAssetVerification: null, evidenceRunId: null, evidenceLoaded: false, evaluationReport: null, sampleInferences: [], artifactBundles: [],
  refreshInFlight: false, refreshSeq: 0,
  evidenceErrors: {},
  modelSourceProviders: [], modelSourceCandidates: [], modelSourceResolutions: [], modelSourceSearches: [], modelSourceSearch: null, modelSourceMode: "search", modelSourceOperationSeq: 0, modelSourceLoadedTaskId: null, modelSourceCandidateRenderKey: "", modelSourceCheckpointRenderKey: "", modelSourceSearchInFlight: false,
  checkpointCard: null, workspaceAutoKey: null, workspaceProjection: null, workspaceDismissedKey: null, inspectorAutoOpened: false, inspectorOpener: null, inspectorMode: "closed", activeObjectRef: null, activeObjectPayload: null, objectViewerRequestSeq: 0, productRuntime: null, runtimeIssue: null, taskSpecFamilies: [], taskSpecFamiliesError: null, taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false,
  actionTimelineDisclosure: new Map(), actionResultCache: new Map(), actionResultRequests: new Map(),
  noticeDismissTimer: null,
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
const ConversationView = window.ModelHarnessConversationView;
const InteractionShell = window.ModelHarnessInteractionShell;
const STAGE_LABELS = {
  task_understanding: "确认任务理解", capability_resolution: "解决能力缺口", data_preparation: "准备训练数据",
  contract_review: "审阅训练合同", ready_to_run: "准备启动训练", evaluation: "审阅评测结果", run_recovery: "处理运行异常",
  source_discovery: "查找模型来源", source_resolution: "确认固定版本", source_snapshot: "读取来源清单", repository_analysis: "审阅仓库分析",
  training_plan: "确认训练计划", resource_probe: "检查本机资源", environment_lock: "冻结训练环境", resource_fit: "判断训练可行性",
};
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
const inspectorMedia = window.matchMedia("(max-width:899px)");
const dockedWorkspaceMedia = window.matchMedia("(min-width:1280px)");

function structuredErrorMessage(value, fallback = "请求失败") {
  const detail = value && typeof value === "object" ? (value.detail ?? value.error ?? value) : value;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail && typeof detail === "object") {
    const message = detail.message || detail.detail || detail.code;
    if (typeof message === "string" && message.trim()) return message.trim();
    try { return JSON.stringify(detail); } catch (_error) { return fallback; }
  }
  return String(detail || fallback);
}
async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json !== undefined) { headers["content-type"] = "application/json"; options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) { const error = new Error(structuredErrorMessage(value)); error.status = response.status; error.payload = value; throw error; }
  return value;
}
function clear(element) { while (element?.firstChild) element.firstChild.remove(); }
function formatTime(value) { const normalized = typeof value === "number" && value > 0 && value < 1_000_000_000_000 ? value * 1000 : value; const date = new Date(normalized); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function timestampMs(value) { const normalized = typeof value === "number" && value > 0 && value < 1_000_000_000_000 ? value * 1000 : value; const time = new Date(normalized).getTime(); return Number.isFinite(time) ? time : null; }
function formatElapsed(value) { const seconds = Math.max(0, Math.floor(Number(value || 0) / 1000)); if (seconds < 1) return "不足 1 秒"; if (seconds < 60) return `${seconds} 秒`; const minutes = Math.floor(seconds / 60); const remainder = seconds % 60; if (minutes < 60) return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`; const hours = Math.floor(minutes / 60); const minuteRemainder = minutes % 60; return minuteRemainder ? `${hours} 小时 ${minuteRemainder} 分` : `${hours} 小时`; }
function syncAiTurnElapsedLabels(root = document) {
  root.querySelectorAll?.("[data-ai-turn-status-label]").forEach((label) => {
    const startedAt = Number(label.dataset.startedAt); const endedAt = Number(label.dataset.endedAt); const live = label.dataset.elapsedLive === "true"; const base = label.dataset.baseLabel || label.textContent || "";
    if (!Number.isFinite(startedAt)) { label.textContent = base; return; }
    const finish = live ? Date.now() : Number.isFinite(endedAt) ? endedAt : startedAt;
    label.textContent = `${base} · ${live ? "" : "已处理 "}${formatElapsed(Math.max(0, finish - startedAt))}`;
  });
}
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
function clearNoticeDismissTimer() { if (state.noticeDismissTimer !== null) { window.clearTimeout(state.noticeDismissTimer); state.noticeDismissTimer = null; } }
function showNotice(message, tone = "error") { clearNoticeDismissTimer(); delete ui.composerNotice.dataset.runtimeSetup; ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = tone; ui.composerNotice.textContent = message; }
function showRuntimeSetupNotice(message) { clearNoticeDismissTimer(); ui.composerNotice.dataset.runtimeSetup = "true"; ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = "error"; ui.composerNotice.textContent = message; }
function hideNotice() { clearNoticeDismissTimer(); delete ui.composerNotice.dataset.runtimeSetup; ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }
function showTransientNotice(message, tone = "ok", durationMs = 6_000) {
  showNotice(message, tone);
  state.noticeDismissTimer = window.setTimeout(() => { state.noticeDismissTimer = null; ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }, durationMs);
}
function setButtonBusy(button, busy, busyText) { if (!button.dataset.label) button.dataset.label = button.textContent; button.disabled = busy; button.textContent = busy ? busyText : button.dataset.label; }
function formatBytes(value) { if (!Number.isFinite(value)) return "大小未知"; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`; if (value < 1024 ** 4) return `${(value / 1024 ** 3).toFixed(1)} GB`; return `${(value / 1024 ** 4).toFixed(1)} TB`; }
function fixedCommit(value) { return typeof value === "string" && IMMUTABLE_COMMIT.test(value.toLowerCase()); }
function statusLabel(value) { return EVIDENCE_STATUS_LABELS[value] || String(value || "未知"); }
function isPendingHumanCheckpoint(item) {
  return Boolean(item && (item.kind === "approval" || item.kind === "question") && ["pending", "waiting", undefined, null].includes(item.status));
}
function currentHumanCheckpoint(conversation = state.conversation) {
  const pending = conversation?.pending || conversation?.items || [];
  return [...pending].reverse().find(isPendingHumanCheckpoint) || null;
}
const DATA_UPLOAD_QUESTION_IDS = new Set(["data_upload", "dataset_upload", "csv_upload", "data_path", "dataset_id"]);
const INFERENCE_INPUT_QUESTION_IDS = new Set(["inference_input_id", "fresh_sample_upload", "sample_upload"]);
function isDatasetUploadQuestionId(value) { return DATA_UPLOAD_QUESTION_IDS.has(String(value || "")); }
function dataUploadQuestionCheckpoint(item) {
  if (!item || item.kind !== "question" || !item.rpc_id || !isPendingHumanCheckpoint(item)) return null;
  const questions = Array.isArray(item.questions) ? item.questions : [];
  const ids = new Set(questions.map((question) => question?.id));
  return [...DATA_UPLOAD_QUESTION_IDS, "target_column"].some((id) => ids.has(id)) ? item : null;
}
function dataUploadCheckpointAnswers(item, datasetId, targetColumn) {
  if (!dataUploadQuestionCheckpoint(item) || !datasetId) return [];
  return item.questions.map((question) => {
    if (isDatasetUploadQuestionId(question.id)) return { id: question.id, selected: [], custom: datasetId };
    if (question.id === "target_column") return { id: question.id, selected: [], custom: targetColumn || "" };
    return { id: question.id, selected: [], custom: "" };
  });
}
function inferenceInputQuestionCheckpoint(item) {
  if (!item || item.kind !== "question" || !item.rpc_id || !isPendingHumanCheckpoint(item)) return null;
  const questions = Array.isArray(item.questions) ? item.questions : [];
  return questions.some((question) => INFERENCE_INPUT_QUESTION_IDS.has(String(question?.id || ""))) ? item : null;
}
function inferenceInputCheckpointAnswers(item, inferenceInput) {
  if (!inferenceInputQuestionCheckpoint(item) || !inferenceInput?.inference_input_id || !inferenceInput?.sha256) return [];
  return item.questions.map((question) => INFERENCE_INPUT_QUESTION_IDS.has(String(question?.id || "")) ? {
    id: question.id,
    selected: [],
    custom: `inference_input_id=${inferenceInput.inference_input_id}; sha256=${inferenceInput.sha256}; sample_type=${inferenceInput.sample_type || "unknown"}`,
  } : { id: question.id, selected: [], custom: "" });
}
function syncTaskSpecCheckpointOwnership(conversation = state.conversation) {
  const ownedByDsh = Boolean(currentHumanCheckpoint(conversation)?.rpc_id);
  ui.taskSpecCard.dataset.writeOwner = ownedByDsh ? "dsh-checkpoint" : "task-spec";
  ui.taskSpecCard.setAttribute("aria-hidden", String(ownedByDsh));
  if (ownedByDsh) {
    state.taskSpecDescriptionMode = false;
    ui.taskSpecCard.hidden = true;
  } else if (state.task?.task_spec) ui.taskSpecCard.hidden = false;
  [ui.editTaskSpecButton, ui.confirmTaskSpecButton, ...ui.taskSpecQuickReplies.querySelectorAll("button")].forEach((control) => {
    if (ownedByDsh && !control.disabled) { control.disabled = true; control.dataset.disabledByDshCheckpoint = "true"; }
    else if (!ownedByDsh && control.dataset.disabledByDshCheckpoint === "true") { control.disabled = false; delete control.dataset.disabledByDshCheckpoint; }
  });
  [ui.confirmContractButton, ui.approveRunProposalButton, ui.datasetButton, ui.inspectorDatasetButton].filter(Boolean).forEach((control) => {
    if (ownedByDsh && !control.disabled) { control.disabled = true; control.dataset.disabledByDshCheckpoint = "true"; }
    else if (!ownedByDsh && control.dataset.disabledByDshCheckpoint === "true") { control.disabled = false; delete control.dataset.disabledByDshCheckpoint; }
  });
}
const BACKGROUND_TRAINING_STATUSES = new Set(["created", "queued", "starting", "preflight", "active", "running", "training", "evaluating", "packaging", "cancel_requested", "cancelling", "stopping"]);
const BACKGROUND_CANCELLING_STATUSES = new Set(["cancel_requested", "cancelling", "stopping"]);
function runtimeStatusToken(value) { return String(value || "").trim().toLowerCase(); }
function conversationAgentResponseRunning(conversation) { return conversation?.agent_response_running === true; }
function conversationTrainingEntries(conversation) {
  const typedRuns = (Array.isArray(conversation?.training_runs) ? conversation.training_runs : [])
    .filter((entry) => entry && typeof entry === "object" && (!entry.object_type || entry.object_type === "TrainingRun"));
  const backgroundRuns = (Array.isArray(conversation?.background_actions) ? conversation.background_actions : [])
    .filter((entry) => entry && typeof entry === "object" && runtimeStatusToken(entry.action_type || entry.object_type) === "training_run");
  return [...typedRuns, ...backgroundRuns];
}
function trainingEntryCancelling(entry) {
  return entry?.cancel_requested === true
    || BACKGROUND_CANCELLING_STATUSES.has(runtimeStatusToken(entry?.status))
    || BACKGROUND_CANCELLING_STATUSES.has(runtimeStatusToken(entry?.domain_status));
}
function trainingEntryRunning(entry) {
  return entry?.running === true
    || entry?.worker_running === true
    || trainingEntryCancelling(entry)
    || BACKGROUND_TRAINING_STATUSES.has(runtimeStatusToken(entry?.status))
    || BACKGROUND_TRAINING_STATUSES.has(runtimeStatusToken(entry?.domain_status));
}
function activeBackgroundTrainingRun(conversation) {
  return conversationTrainingEntries(conversation).find(trainingEntryRunning) || null;
}
function backgroundCancellationPending(conversation) {
  return [
    ...conversationTrainingEntries(conversation),
    ...(Array.isArray(conversation?.runs) ? conversation.runs : []),
    ...(Array.isArray(conversation?.agent_turns) ? conversation.agent_turns : []),
  ].some(trainingEntryCancelling);
}
function conversationHasBackgroundTraining(conversation) {
  return conversation?.background_action_running === true || Boolean(activeBackgroundTrainingRun(conversation));
}
function conversationHasActiveWork(conversation) {
  return conversationAgentResponseRunning(conversation) || conversationHasBackgroundTraining(conversation);
}
const DEFAULT_CONVERSATION_MESSAGE_MODE = "queue_after_turn";
const OPTIONAL_CONVERSATION_MESSAGE_MODES = ["intervene_current", "stop_and_replace"];
function advertisedConversationModes(conversation = state.conversation) {
  const advertised = Array.isArray(conversation?.supported_modes)
    ? conversation.supported_modes
    : Array.isArray(state.productRuntime?.agent?.supported_modes)
      ? state.productRuntime.agent.supported_modes
      : [];
  return new Set(advertised.map((mode) => String(mode || "").trim()).filter(Boolean));
}
function syncComposerDelivery(conversation = state.conversation) {
  const checkpoint = currentHumanCheckpoint(conversation);
  const agentQueued = Boolean(state.runtimeReady && state.selectedTaskId && !checkpoint && conversationAgentResponseRunning(conversation));
  const backgroundRunning = Boolean(state.runtimeReady && state.selectedTaskId && !checkpoint && !agentQueued && conversationHasBackgroundTraining(conversation));
  ui.composerDelivery.hidden = !agentQueued && !backgroundRunning;
  ui.composerWrap.dataset.delivery = agentQueued ? DEFAULT_CONVERSATION_MESSAGE_MODE : backgroundRunning ? "background-training" : "immediate-when-idle";
  if (!agentQueued && !backgroundRunning) return;
  if (backgroundRunning) {
    ui.composerDeliveryLabel.textContent = "后台训练正在运行，可继续对话";
    ui.composerDeliveryDetail.textContent = "你仍可继续和训练协调器交流；新消息会开启新的对话回合，不会被描述为排队到当前训练之后。";
    return;
  }
  const supported = advertisedConversationModes(conversation);
  const unopened = OPTIONAL_CONVERSATION_MESSAGE_MODES.filter((mode) => !supported.has(mode));
  const unopenedLabels = unopened.map((mode) => mode === "intervene_current" ? "实时干预" : "停止并替换");
  ui.composerDeliveryLabel.textContent = "将在本轮结束后继续";
  ui.composerDeliveryDetail.textContent = unopenedLabels.length
    ? `当前消息只会排队，不会改变正在执行的本轮；${unopenedLabels.join("、")}尚未开放。`
    : "当前消息按排队模式提交；只有后端明确声明支持的模式才允许另行选择。";
}
function createConversationRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
    return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  }
  state.messageRequestSequence += 1;
  return `message-${Date.now()}-${state.messageRequestSequence}`;
}
function beginMessageSubmission(taskId, text) {
  const previous = state.messageSubmission;
  if (previous?.task_id === taskId && previous.text === text && previous.status === "failed") {
    previous.status = "sending";
    return previous;
  }
  const submission = { task_id: taskId, text, request_id: createConversationRequestId(), status: "sending" };
  state.messageSubmission = submission;
  return submission;
}
async function postQueuedConversationMessage(taskId, text) {
  const submission = beginMessageSubmission(taskId, text);
  state.pendingMessage = { task_id: taskId, text, time: Date.now() };
  renderConversation(true);
  try {
    const response = await request(`/tasks/${encodeURIComponent(taskId)}/conversation/messages`, {
      method: "POST",
      json: { message: text, mode: DEFAULT_CONVERSATION_MESSAGE_MODE, request_id: submission.request_id },
    });
    const status = runtimeStatusToken(response?.status);
    if (response?.accepted !== true || ["failed", "cancelled", "canceled", "rejected", "interrupted"].includes(status)) {
      const error = new Error(structuredErrorMessage(response, "后端没有接受这条消息"));
      error.payload = response;
      throw error;
    }
    if (state.messageSubmission?.request_id === submission.request_id) state.messageSubmission = null;
    return response;
  } catch (error) {
    if (state.messageSubmission?.request_id === submission.request_id) state.messageSubmission.status = "failed";
    if (state.pendingMessage?.task_id === taskId && state.pendingMessage.text === text) state.pendingMessage = null;
    throw error;
  }
}
function workflowStatus(task, conversation = null) {
  if ((conversation && state.conversationStreamDegraded) || conversation?.projection_health?.status === "observation_degraded") return { label: "需要重新连接", tone: "failed" };
  if (backgroundCancellationPending(conversation)) return { label: "正在停止", tone: "cancelling" };
  const checkpoint = currentHumanCheckpoint(conversation);
  if (checkpoint?.kind === "question") return { label: "等待你的回答", tone: "needs_confirmation" };
  if (checkpoint?.kind === "approval") return { label: "等待你的批准", tone: "needs_confirmation" };
  if (conversationAgentResponseRunning(conversation)) return { label: "AI 正在处理", tone: "running" };
  if (conversationHasBackgroundTraining(conversation)) return { label: "后台训练/评测进行中", tone: "running" };
  if (conversation?.interaction_state === "waiting_for_human") return { label: "等待你的决定", tone: "needs_confirmation" };
  if (RUNNING_STATUSES.has(task.current_result?.status)) return { label: "后台训练/评测进行中", tone: "running" };
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
function canonicalInteractionPresentation(conversation = state.conversation) {
  const value = conversation?.interaction_projection;
  if (!value || value.schema_version !== "1.0" || value.phase === "idle") return null;
  const selected = ({
    observation_degraded: { label: "需要重新连接", tone: "failed" },
    stopping: { label: "正在停止", tone: "cancelling" },
    waiting_question: { label: "等待你的回答", tone: "needs_confirmation" },
    waiting_approval: { label: "等待你的批准", tone: "needs_confirmation" },
    agent_working: { label: "AI 正在处理", tone: "running" },
    background_working: { label: "后台训练/评测进行中", tone: "running" },
    completed: { label: "本轮结果已就绪", tone: "completed" },
    failed: { label: "运行异常", tone: "failed" },
    stopped: { label: "本轮已停止", tone: "cancelled" },
    blocked: { label: "任务当前受阻", tone: "failed" },
  })[value.phase];
  return selected ? { ...selected, phase: value.phase, reason_code: value.phase, can_cancel: value.can_cancel === true } : null;
}
function interactionPresentation(task, conversation = state.conversation, projection = null) {
  const canonical = canonicalInteractionPresentation(conversation);
  if (canonical) return canonical;
  const projectionStatus = projection ? ({
    clarifying: { label: "等待你的回答", tone: "needs_confirmation" },
    awaiting_approval: { label: "等待你的批准", tone: "needs_confirmation" },
    executing: { label: backgroundCancellationPending(conversation) ? "正在停止" : conversationAgentResponseRunning(conversation) ? "AI 正在处理" : conversationHasBackgroundTraining(conversation) ? "后台训练/评测进行中" : projection.background?.coordinator_reply_complete ? "后台训练/评测进行中" : "AI 正在处理", tone: backgroundCancellationPending(conversation) ? "cancelling" : "running" },
    result_ready: { label: "本轮结果已就绪", tone: "completed" },
    blocked: { label: "任务当前受阻", tone: "failed" },
    failed: { label: projection.reason_code === "observation_degraded" ? "需要重新连接" : "运行异常", tone: "failed" },
  })[projection.phase] : null;
  const workflow = projectionStatus || workflowStatus(task, conversation);
  return {
    ...workflow,
    phase: projection?.phase || null,
    reason_code: projection?.reason_code || null,
    can_cancel: conversation?.can_cancel_agent === true && !backgroundCancellationPending(conversation),
  };
}
function syncTaskHeader(task, conversation = state.conversation, projection = null) {
  const workflow = interactionPresentation(task, conversation, projection);
  ui.taskEyebrow.textContent = workflow.label;
  ui.taskEyebrow.dataset.status = workflow.tone;
  ui.taskTitle.textContent = task.name;
  ui.taskStatus.textContent = workflow.label;
  ui.taskStatus.dataset.status = workflow.tone;
}
function statusTone(value) {
  if (["completed", "passed", "sufficient", "release_ready"].includes(value)) return "passed";
  if (["cancelled", "interrupted"].includes(value)) return "cancelled";
  if (["failed", "integrity_failed", "quality_failed"].includes(value)) return "failed";
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
  const incompatible = mode === "incompatible";
  const providerMissing = mode === "provider";
  const pillText = checking ? "正在连接训练协调器" : ready ? "训练协调器已就绪" : providerMissing ? "模型服务待配置" : incompatible ? "AI 服务版本不兼容" : "训练协调器未连接";
  const composerText = checking ? "正在连接训练协调器" : ready ? "训练协调器已连接" : providerMissing ? "先连接模型服务" : incompatible ? "服务版本不兼容 · 对话已暂停" : "训练协调器未连接 · 对话已暂停";
  ui.runtimePill.dataset.state = checking ? "checking" : ready ? "ready" : "error";
  ui.runtimePill.querySelector("span").textContent = pillText; ui.runtimePill.title = pillText; ui.runtimePill.setAttribute("aria-label", pillText);
  ui.composerMode.dataset.state = checking ? "checking" : ready ? "agent" : "local"; ui.composerModeLabel.textContent = composerText; ui.composerMode.title = ready ? "训练协调器可以理解需求、动态规划并调度训练团队" : providerMissing ? "模型服务尚未配置，因此不会创建任务或启动对话" : checking ? composerText : "当前只允许查看任务事实和手动打开证据面板；不会用固定流程冒充智能协作";
  ui.messageInput.disabled = !ready; ui.sendButton.disabled = !ready; ui.composerWrap.dataset.runtime = ready ? "agent" : checking ? "checking" : "unavailable";
  if (!ready) ui.messageInput.placeholder = checking ? "正在连接训练协调器…" : providerMissing ? "请先在本机配置模型服务，再开始训练任务" : incompatible ? "AI 服务版本不兼容，请重启正式服务" : "训练协调器未连接，暂时不能创建或继续对话任务";
  else ui.messageInput.placeholder = state.selectedTaskId ? "继续询问或补充下一步要求…" : "告诉我，你希望模型帮你完成什么？";
  if (providerMissing) showRuntimeSetupNotice("模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。");
  else if (ui.composerNotice.dataset.runtimeSetup === "true") hideNotice();
  syncComposerDelivery();
}
function compatibleAgentRuntime(agent) {
  return agent?.available === true && agent.real_agent === true && agent.implementation === "dsh_native_subagents" && agent.conversation_schema_version === "2.0" && agent.conversation_projector_revision === "3.2" && agent.synthesis_verdict_version === "1.0" && agent.conversation_action_schema_version === "1.0" && agent.task_truth_source === "TrainingTask";
}
function agentProviderReady(agent) { return agent?.provider?.ready === true && agent.provider.active === true && agent.provider.configured === true; }
function applyAgentRuntimeStatus(agent) {
  const transportCompatible = compatibleAgentRuntime(agent); const providerReady = agentProviderReady(agent);
  state.runtimeReady = transportCompatible && providerReady;
  if (agent?.available === true && !transportCompatible) state.runtimeIssue = "incompatible";
  else if (transportCompatible && !providerReady) state.runtimeIssue = "provider";
}
function runtimeDisplayMode() { return state.runtimeReady ? "agent" : state.runtimeIssue === "incompatible" ? "incompatible" : state.runtimeIssue === "provider" ? "provider" : "local"; }
function renderProductBoundary() {
  const byomExecutionAvailable = state.productRuntime?.byom_execution_available === true;
  if (ui.homeBoundary) ui.homeBoundary.textContent = byomExecutionAvailable
    ? "说清楚你想解决的问题就够了。训练协调器会和你一起澄清目标、查找开源模型，并在确认后进入可验证的训练与评测。"
    : "说清楚你想解决的问题就够了。训练协调器会和你一起澄清目标、查找开源模型，并在每个关键决定前停下来确认。";
  if (ui.homeTrainingProof) {
    ui.homeTrainingProof.lastChild.textContent = byomExecutionAvailable ? "确认后进入真实训练" : "确认方案后才执行";
  }
}
async function loadRuntime() {
  state.runtimeIssue = null; renderRuntimeMode("checking");
  try {
    state.productRuntime = await request("/runtime");
    applyAgentRuntimeStatus(state.productRuntime.agent);
  } catch (_runtimeError) {
    state.productRuntime = null;
    try { applyAgentRuntimeStatus(await request("/agent/runtime")); } catch (_agentError) { state.runtimeReady = false; }
  }
  renderProductBoundary();
  renderRuntimeMode(runtimeDisplayMode());
  if (state.task) renderConversation(true);
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
  if (!state.tasks.length) { const empty = document.createElement("div"); empty.className = "task-empty"; empty.textContent = "还没有模型任务。先描述一个真实问题。"; ui.taskList.append(empty); return; }
  state.tasks.forEach((task) => {
    const row = document.createElement("div"); row.className = "task-row"; row.dataset.taskId = task.task_id;
    const button = document.createElement("button"); button.type = "button"; button.className = "task-item"; button.dataset.action = "select-task"; button.dataset.taskId = task.task_id; button.setAttribute("aria-current", String(task.task_id === state.selectedTaskId));
    const title = document.createElement("b"); title.textContent = task.name;
    const meta = document.createElement("span"); meta.className = "task-meta";
    const taskConversation = task.task_id === state.selectedTaskId ? state.conversation : null; const workflow = workflowStatus(task, taskConversation); const status = document.createElement("span"); status.className = "task-workflow"; const dot = document.createElement("i"); dot.dataset.status = workflow.tone; status.append(dot, document.createTextNode(workflow.label));
    const time = document.createElement("time"); time.dateTime = task.updated_at_utc || ""; time.textContent = formatRelativeTime(task.updated_at_utc); meta.append(status, time);
    button.append(title, meta);
    const archive = document.createElement("button"); archive.type = "button"; archive.className = "task-archive-button icon-button"; archive.dataset.action = "archive-task"; archive.dataset.taskId = task.task_id;
    archive.disabled = task.status === "running"; archive.title = archive.disabled ? "任务运行中，不能归档" : `归档任务：${task.name}`; archive.setAttribute("aria-label", archive.title);
    archive.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h16v12H4zM3 4h18v3.5H3zM9 11h6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    button.addEventListener("click", () => selectTask(task.task_id)); archive.addEventListener("click", () => confirmTaskArchive(task)); row.append(button, archive); ui.taskList.append(row);
  });
}
function syncSelectedTaskListStatus(conversation = state.conversation) {
  const task = state.tasks.find((item) => item.task_id === state.selectedTaskId); if (!task) return;
  const button = [...ui.taskList.querySelectorAll(".task-item")].find((item) => item.dataset.taskId === task.task_id); const status = button?.querySelector(".task-workflow"); const dot = status?.querySelector("i"); if (!status || !dot) return;
  const workflow = workflowStatus(task, conversation); dot.dataset.status = workflow.tone; status.replaceChildren(dot, document.createTextNode(workflow.label));
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
  history.replaceState(null, "", location.pathname); document.body.dataset.view = "home"; ui.homeComposerSlot.append(ui.composerWrap); ui.emptyState.hidden = false; ui.conversation.hidden = true;
  ui.inspector.hidden = true; ui.workspaceToggleButton.hidden = true; ui.mobileViewNav.hidden = true; ui.agentCheckpoint.hidden = true; ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.taskEyebrow.textContent = "SPECIALIST MODEL STUDIO"; ui.taskTitle.textContent = "开始一个训练任务";
  renderRuntimeMode(runtimeDisplayMode()); syncComposerDelivery(null); restoreDraft(null); renderTaskList(); closeSidebar(); closeInspector(); if (focusComposer && state.runtimeReady) ui.messageInput.focus();
}
function openNewTask() {
  saveDraft(); clearDraft(null); ui.messageInput.value = ""; resizeComposer(); stopPolling(); state.selectionToken += 1; Object.assign(state, { selectedTaskId: null, task: null, conversation: null, runEvents: [], pendingMessage: null, lastRenderKey: "", taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false });
  restoreCheckpointCard(); state.workspaceAutoKey = null; state.workspaceDismissedKey = null; state.workspaceProjection = null; state.inspectorAutoOpened = false;
  resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence();
  enterHomeState();
}
async function selectTask(taskId, { saveCurrentDraft = true } = {}) {
  if (taskId !== state.selectedTaskId) { if (saveCurrentDraft) saveDraft(); restoreCheckpointCard(); resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence(); state.conversation = null; state.workspaceAutoKey = null; state.workspaceDismissedKey = null; state.workspaceProjection = null; state.inspectorAutoOpened = false; state.taskSpecRevisions = []; state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; }
  stopPolling(); hideNotice(); const token = ++state.selectionToken; state.selectedTaskId = taskId; state.lastRenderKey = ""; state.pendingMessage = state.pendingMessage?.task_id === taskId ? state.pendingMessage : null; history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  document.body.dataset.view = "task"; ui.conversationMain.append(ui.composerWrap); renderTaskList(); ui.emptyState.hidden = true; ui.conversation.hidden = false; ui.inspector.hidden = false; ui.workspaceToggleButton.hidden = false; ui.mobileViewNav.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false; closeSidebar(); closeInspector();
  restoreDraft(taskId); await refreshSelected({ force: true, token });
  if (state.selectedTaskId === taskId && state.selectionToken === token) {
    startConversationStream(taskId, token);
    state.pollTimer = window.setInterval(() => refreshSelected({ includeConversation: false }), 6000);
  }
}
async function refreshSelected({ force = false, token = state.selectionToken, includeConversation = true } = {}) {
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
          const referencedSearch = state.activeObjectRef?.type === "model_source_search"
            ? state.modelSourceSearches.find((item) => item.search_id === state.activeObjectRef.id) || null
            : null;
          state.modelSourceSearch = referencedSearch || (failedSearch ? null : latestSearch);
          state.modelSourceCandidates = [...(state.modelSourceSearch?.candidates || [])];
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
    if (includeConversation) await reconcileConversation(taskId, token, { render: false });
    renderConversation(force); if (force) {
      await loadTasks();
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    }
  } finally {
    if (seq === state.refreshSeq) state.refreshInFlight = false;
  }
}

function conversationStreamEntryKey(value) {
  for (const field of ["event_id", "action_id", "work_item_id", "source_key", "delegation_id", "rpc_id", "training_run_id", "run_id"]) {
    if (typeof value?.[field] === "string" && value[field]) return `${field}:${value[field]}`;
  }
  if (Number.isInteger(value?.seq)) return `seq:${value.seq}`;
  return `json:${JSON.stringify(value)}`;
}
function mergeConversationStreamEntries(current = [], changed = []) {
  const merged = [...(Array.isArray(current) ? current : [])]; const indexes = new Map(merged.map((value, index) => [conversationStreamEntryKey(value), index]));
  for (const value of Array.isArray(changed) ? changed : []) {
    if (!value || typeof value !== "object") continue;
    const key = conversationStreamEntryKey(value); const index = indexes.get(key);
    if (index === undefined) { indexes.set(key, merged.length); merged.push(value); } else merged[index] = value;
  }
  return merged;
}
function clearObservedPendingMessage(taskId, conversation) {
  if (state.pendingMessage?.task_id !== taskId || !Array.isArray(conversation?.items)) return;
  if (conversation.items.some((item) => (item.role === "user" && item.text === state.pendingMessage.text) || (item.category === "user_message" && (item.text || item.payload?.text) === state.pendingMessage.text))) state.pendingMessage = null;
}
function clientDegradedConversation(conversation, message) {
  if (!conversation) return conversation;
  return {
    ...conversation,
    projection_health: "observation_degraded",
    stream_health: {
      ...(conversation.stream_health || {}),
      status: "degraded",
      consecutive_failures: Math.max(1, Number(conversation.stream_health?.consecutive_failures || 0)),
      client_transport_error: message,
    },
  };
}
function isCanonicalConversationSnapshot(value) {
  if (!value || typeof value !== "object" || String(value.schema_version) !== "2.0" || value.event_payload_mode !== "compact-v1" || value.action_schema_version !== "1.0" || value.synthesis_verdict_version !== "1.0") return false;
  if (!(value.session_id === null || typeof value.session_id === "string") || !(value.team_id === null || typeof value.team_id === "string")) return false;
  if (![value.running, value.execution_running, value.can_cancel_agent].every((field) => typeof field === "boolean")) return false;
  if ([value.agent_response_running, value.background_action_running].some((field) => field !== undefined && typeof field !== "boolean")) return false;
  if (!["working", "waiting_for_human", "cancelling", "idle", "terminal"].includes(value.interaction_state)) return false;
  if (value.interaction_projection !== undefined && (value.interaction_projection?.schema_version !== "1.0" || typeof value.interaction_projection?.phase !== "string" || typeof value.interaction_projection?.can_cancel !== "boolean")) return false;
  if (!["items", "events", "actions", "pending", "runs", "agents", "delegations", "projection_errors"].every((field) => Array.isArray(value[field]))) return false;
  if (value.work_items !== undefined && !Array.isArray(value.work_items)) return false;
  if (!["agent_turns", "training_runs", "background_actions", "human_checkpoints", "risks", "supported_modes"].every((field) => value[field] === undefined || Array.isArray(value[field]))) return false;
  return value.stream_health && typeof value.stream_health === "object" && ["healthy", "observation_degraded"].includes(value.projection_health);
}
function acceptConversationSnapshot(taskId, token, remoteConversation) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token || !isCanonicalConversationSnapshot(remoteConversation)) return false;
  state.conversation = remoteConversation;
  if (state.conversationStreamDegraded) state.conversation = clientDegradedConversation(state.conversation, "实时事件流尚未恢复，当前由串行轮询对账。");
  clearObservedPendingMessage(taskId, state.conversation);
  return true;
}
function markConversationStreamDegraded(message) {
  state.conversationStreamDegraded = true;
  if (!state.conversation) state.conversation = { schema_version: "2.0", task_id: state.selectedTaskId, running: false, execution_running: false, agent_response_running: false, background_action_running: false, interaction_state: "idle", can_cancel_agent: false, items: [], events: [], actions: [], pending: [], runs: [], agent_turns: [], training_runs: [], background_actions: [], human_checkpoints: [], risks: [], agents: [], delegations: [], work_items: [], supported_modes: [], projection_errors: [] };
  state.conversation = clientDegradedConversation(state.conversation, message);
  state.lastRenderKey = "";
  if (state.task) renderConversation(true);
}
async function reconcileConversation(taskId, token, { render = true } = {}) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token) return false;
  if (state.conversationReconcileInFlight) return state.conversationReconcilePromise;
  const seq = ++state.conversationReconcileSeq; const cursorBefore = state.conversationStreamCursor; state.conversationReconcileInFlight = true;
  const operation = (async () => {
    try {
      const remoteConversation = (await request(`/tasks/${encodeURIComponent(taskId)}/conversation`)).conversation;
      if (seq !== state.conversationReconcileSeq || cursorBefore !== state.conversationStreamCursor) return false;
      if (!acceptConversationSnapshot(taskId, token, remoteConversation)) { markConversationStreamDegraded("全量对话返回了不兼容的证据合同。"); return false; }
      if (render) renderConversation(true);
      return true;
    } catch (error) {
      if (state.selectedTaskId !== taskId || state.selectionToken !== token || seq !== state.conversationReconcileSeq) return false;
      if (error.status === 503) { state.runtimeReady = false; renderRuntimeMode("local"); }
      markConversationStreamDegraded(error.message || "全量对账失败");
      return false;
    } finally {
      if (seq === state.conversationReconcileSeq) { state.conversationReconcileInFlight = false; state.conversationReconcilePromise = null; }
    }
  })();
  state.conversationReconcilePromise = operation;
  return operation;
}
function closeConversationEventSource() {
  if (state.conversationStream) state.conversationStream.close();
  state.conversationStream = null; state.conversationStreamTaskId = null;
}
function stopConversationStream() {
  closeConversationEventSource();
  if (state.conversationFallbackTimer) window.clearInterval(state.conversationFallbackTimer);
  if (state.conversationReconnectTimer) window.clearTimeout(state.conversationReconnectTimer);
  state.conversationFallbackTimer = null; state.conversationReconnectTimer = null; state.conversationStreamCursor = null; state.conversationStreamRevision = null; state.conversationStreamDegraded = false; state.conversationReconcileInFlight = false; state.conversationReconcilePromise = null; state.conversationReconcileSeq += 1;
}
async function attemptConversationFallbackRecovery(taskId, token) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token || state.conversationStream) return;
  if (!state.runtimeReady) await loadRuntime();
  if (state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  const reconciled = await reconcileConversation(taskId, token);
  if (!reconciled || !state.runtimeReady || state.conversationStream || state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  state.conversationStreamCursor = null; state.conversationStreamRevision = null;
  startConversationStream(taskId, token);
}
function beginConversationFallback(taskId, token, message, { resetCursor = false, reconnect = true, poll = true } = {}) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  closeConversationEventSource();
  if (resetCursor) { state.conversationStreamCursor = null; state.conversationStreamRevision = null; }
  markConversationStreamDegraded(message);
  void reconcileConversation(taskId, token);
  if (poll && !state.conversationFallbackTimer) state.conversationFallbackTimer = window.setInterval(() => { void attemptConversationFallbackRecovery(taskId, token); }, 5000);
  if (reconnect && !state.conversationReconnectTimer) state.conversationReconnectTimer = window.setTimeout(() => {
    state.conversationReconnectTimer = null;
    void attemptConversationFallbackRecovery(taskId, token);
  }, 5000);
}
function recoverConversationStream(taskId, token) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  state.conversationStreamDegraded = false;
  if (state.conversationFallbackTimer) window.clearInterval(state.conversationFallbackTimer);
  if (state.conversationReconnectTimer) window.clearTimeout(state.conversationReconnectTimer);
  state.conversationFallbackTimer = null; state.conversationReconnectTimer = null;
}
async function reconcileBeforeStreamRecovery(taskId, token) {
  if (!state.conversationStreamDegraded || state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  closeConversationEventSource();
  const reconciled = await reconcileConversation(taskId, token);
  if (!reconciled) { beginConversationFallback(taskId, token, "实时流已恢复响应，但全量证据对账尚未完成。"); return; }
  if (state.selectedTaskId !== taskId || state.selectionToken !== token || !state.runtimeReady) return;
  state.conversationStreamCursor = null; state.conversationStreamRevision = null;
  startConversationStream(taskId, token);
}
function acceptConversationStreamEnvelope(data, { snapshot = false } = {}) {
  if (!data || data.schema_version !== "1.0" || data.task_id !== state.selectedTaskId || !Number.isInteger(data.cursor) || data.cursor < 0 || typeof data.projector_revision !== "string") throw new Error("实时事件身份不完整");
  if (!snapshot && state.conversationStreamCursor !== null && data.cursor !== state.conversationStreamCursor + 1) throw new Error("实时事件序号出现缺口");
  if (!snapshot && state.conversationStreamRevision && data.projector_revision !== state.conversationStreamRevision) throw new Error("实时投影版本已经变化");
  state.conversationStreamCursor = data.cursor; state.conversationStreamRevision = data.projector_revision;
}
function parseConversationStreamData(event) {
  try { return JSON.parse(event.data); } catch (_error) { throw new Error("实时事件不是合法 JSON"); }
}
function startConversationStream(taskId, token) {
  if (!state.runtimeReady || state.selectedTaskId !== taskId || state.selectionToken !== token) return;
  closeConversationEventSource();
  if (typeof window.EventSource !== "function") { beginConversationFallback(taskId, token, "当前浏览器不支持实时事件流。"); return; }
  const query = new URLSearchParams();
  if (state.conversationStreamCursor !== null) query.set("after_seq", String(state.conversationStreamCursor));
  const expectedRevision = state.conversationStreamRevision || state.productRuntime?.agent?.conversation_projector_revision;
  if (expectedRevision) query.set("projector_revision", expectedRevision);
  const source = new EventSource(`/tasks/${encodeURIComponent(taskId)}/conversation/stream${query.size ? `?${query}` : ""}`);
  state.conversationStream = source; state.conversationStreamTaskId = taskId;
  const current = () => state.conversationStream === source && state.selectedTaskId === taskId && state.selectionToken === token;
  source.addEventListener("snapshot", (event) => {
    if (!current()) return;
    try {
      const data = parseConversationStreamData(event); acceptConversationStreamEnvelope(data, { snapshot: true });
      if (!isCanonicalConversationSnapshot(data.conversation)) throw new Error("实时快照缺少 canonical conversation");
      recoverConversationStream(taskId, token);
      if (!acceptConversationSnapshot(taskId, token, data.conversation)) return;
      renderConversation(true);
    } catch (error) { beginConversationFallback(taskId, token, error.message, { resetCursor: true }); }
  });
  source.addEventListener("delta", (event) => {
    if (!current()) return;
    try {
      const data = parseConversationStreamData(event); acceptConversationStreamEnvelope(data);
      if (!state.conversation) throw new Error("增量事件缺少可对账快照");
      state.conversation = {
        ...state.conversation,
        events: mergeConversationStreamEntries(state.conversation.events, data.events),
        items: mergeConversationStreamEntries(state.conversation.items, data.items),
        actions: mergeConversationStreamEntries(state.conversation.actions, data.actions),
        work_items: mergeConversationStreamEntries(state.conversation.work_items, data.work_items),
        background_actions: mergeConversationStreamEntries(state.conversation.background_actions, data.background_actions),
        training_runs: mergeConversationStreamEntries(state.conversation.training_runs, data.training_runs),
      };
      clearObservedPendingMessage(taskId, state.conversation); renderConversation(false);
      if (state.conversationStreamDegraded) void reconcileBeforeStreamRecovery(taskId, token);
    } catch (error) { beginConversationFallback(taskId, token, error.message, { resetCursor: true }); }
  });
  source.addEventListener("state", (event) => {
    if (!current()) return;
    try {
      const data = parseConversationStreamData(event); acceptConversationStreamEnvelope(data);
      if (!state.conversation) throw new Error("状态事件缺少可对账快照");
      state.conversation = { ...state.conversation, running: data.running, execution_running: data.execution_running, agent_response_running: data.agent_response_running === true, background_action_running: data.background_action_running === true, interaction_state: data.interaction_state, interaction_projection: data.interaction_projection || state.conversation.interaction_projection || null, can_cancel_agent: data.can_cancel_agent, active_event: data.active_event, pending: data.pending || [], runs: data.runs || [], agent_turns: data.agent_turns || [], training_runs: data.training_runs || [], background_actions: data.background_actions || [], human_checkpoints: data.human_checkpoints || [], risks: data.risks || [], primary_attention: data.primary_attention || null, supported_modes: data.supported_modes || state.conversation.supported_modes || [], agents: data.agents || [], delegations: data.delegations || [], work_items: data.work_items || state.conversation.work_items || [], work_item_schema_version: data.work_item_schema_version || state.conversation.work_item_schema_version, projection_health: data.projection_health, projection_errors: data.projection_errors || [], stream_health: data.stream_health || {} };
      if (state.conversationStreamDegraded) state.conversation = clientDegradedConversation(state.conversation, "实时事件流正在恢复并等待全量对账。");
      renderConversation(false);
      if (state.conversationStreamDegraded) void reconcileBeforeStreamRecovery(taskId, token);
    } catch (error) { beginConversationFallback(taskId, token, error.message, { resetCursor: true }); }
  });
  source.addEventListener("heartbeat", (event) => {
    if (!current()) return;
    try { acceptConversationStreamEnvelope(parseConversationStreamData(event)); if (state.conversationStreamDegraded) void reconcileBeforeStreamRecovery(taskId, token); } catch (error) { beginConversationFallback(taskId, token, error.message, { resetCursor: true }); }
  });
  source.addEventListener("error", (event) => {
    if (!current()) return;
    if (typeof event.data === "string" && event.data) {
      try { const data = parseConversationStreamData(event); acceptConversationStreamEnvelope(data); beginConversationFallback(taskId, token, data.message || data.code || "实时事件流返回错误", { reconnect: data.recoverable !== false, poll: data.recoverable !== false }); }
      catch (error) { beginConversationFallback(taskId, token, error.message, { resetCursor: true }); }
    } else beginConversationFallback(taskId, token, "实时事件连接已中断，当前结果按观察降级处理。");
  });
}

function syncConversationComposerPlaceholder(conversation = state.conversation, task = state.task) {
  const checkpoint = currentHumanCheckpoint(conversation);
  const uploadCheckpoint = dataUploadQuestionCheckpoint(checkpoint);
  const actionLabel = ["clarify_task_spec", "confirm_task_spec"].includes(task?.control?.next_action?.id) ? "确认任务理解" : task?.control?.next_action?.label;
  if (!state.runtimeReady) ui.messageInput.placeholder = "训练协调器未连接，暂时不能继续对话";
  else if (state.cancelRequestInFlight || backgroundCancellationPending(conversation)) ui.messageInput.placeholder = "正在停止当前执行，请等待后端确认…";
  else if (uploadCheckpoint) ui.messageInput.placeholder = "请先在上方选择 CSV 文件…";
  else if (checkpoint?.kind === "question") ui.messageInput.placeholder = "直接回答当前问题…";
  else if (checkpoint?.kind === "approval") ui.messageInput.placeholder = "请使用上方的批准或拒绝按钮…";
  else if (conversationAgentResponseRunning(conversation)) ui.messageInput.placeholder = "补充下一步要求；消息将在本轮结束后处理…";
  else if (conversationHasBackgroundTraining(conversation)) ui.messageInput.placeholder = "继续和训练协调器交流；后台训练不会阻塞新消息…";
  else if (state.taskSpecDescriptionMode && stageKey(task) === "task_understanding") ui.messageInput.placeholder = "直接告诉训练协调器：模型接收什么、应该输出什么…";
  else if (actionLabel) ui.messageInput.placeholder = `告诉训练协调器：${actionLabel}…`;
  else ui.messageInput.placeholder = "继续询问或补充下一步要求…";
}
function renderTask(task) {
  syncTaskHeader(task);
  renderTaskSpec(task); renderCapability(task); renderModelSource(task); renderRepositoryAnalysis(task); renderTrainingPlan(task); renderResourceFeasibility(task); renderModelAsset(task); renderDataset(task); renderContract(task); renderResult(task); renderRunEvents(); renderRunControl(task);
  syncAgentCheckpoint(task); syncWorkspaceForTask(task);
  syncConversationComposerPlaceholder(state.conversation, task);
  syncComposerDelivery(state.conversation);
}
function stageKey(task) { return task.control?.current_stage || "task_understanding"; }
function stageLabel(value) { if (value?.startsWith("run_")) return "训练与评测"; return STAGE_LABELS[value] || value || "确认任务理解"; }
function nextActionDescription(action, blocked) {
  if (blocked?.message) return blocked.message;
  const descriptions = {
    upload_dataset: "导入与任务规格匹配的数据，后端会执行真实体检。", review_capability_gap: "先联网选择模型或训练仓库；也可以查看仍缺失的训练能力。",
    confirm_training_contract: "确认数据授权、标签或目标字段与离线验收门槛。", start_training_run: "启动后端真实训练，并持续记录事件、指标与产物。",
    view_run_progress: "查看当前 Run 的真实状态；页面不会用动画模拟训练进度。", review_evaluation: "检查独立评测、失败样本与可追溯模型产物。",
    inspect_run_failure: "先阅读失败、取消或中断证据，再决定是否恢复。", retry_training_run: "旧 Run 的状态、错误和事件会保留；确认后由后端基于同一冻结合同创建新的 Run。", clarify_task_spec: "明确模型唯一输出，系统才会匹配训练能力。",
    confirm_task_spec: "确认系统对输入、目标与输出的理解后再检查数据。",
    stage_recipe_samples: "上传少量按类别整理的 PCM WAV 样例 ZIP；样例只用于构建能力，不会被当成正式训练数据。",
    start_recipe_build: "生成受约束的训练方案声明，并由可信音频引擎执行白名单、安全边界和版本校验。",
    approve_recipe_registration: "核对候选声明与两个摘要哈希；明确批准后才会把训练方案与数据导入能力绑定到当前任务。",
    search_model_sources: "从 Hugging Face 与 GitHub 官方目录查找候选，人工确认后再固定版本。", approve_model_source_binding: "核对请求版本、固定 commit 与许可证；批准后才读取有限仓库清单。", replace_model_source: "当前绑定已因 TaskSpec 更新失效，需要重新选择来源。", review_repository_analysis: "查看固定 commit 的静态分析、代码风险和下一步缺口。", retry_model_source_search: "重试官方目录搜索，失败事实仍保留在当前任务。", edit_or_retry_model_source: "修改地址、权限或版本后在同一任务重试。", retry_model_source_binding: "重新读取固定 commit 的完整文件清单。", review_or_retry_repository_analysis: "检查静态分析阻断并决定如何补充映射。",
  };
  return descriptions[action?.id] || "按照后端给出的唯一下一步继续当前训练任务。";
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
  ui.confirmTaskSpecButton.hidden = true; ui.editTaskSpecButton.textContent = "高级编辑"; ui.editTaskSpecButton.disabled = task.status === "running"; renderTaskSpecQuickReplies(task); syncTaskSpecCheckpointOwnership();
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
function datasetDetail(task) {
  const report = task.dataset_report; if (!report) return ["等待数据集", "尚未执行数据体检"];
  if (typeof report.total_images === "number") return [`${report.total_images} 张图片`, `${report.class_count} 类 · 排除 ${report.rejected_count || 0} 张`];
  if (typeof report.total_audio === "number") return [`${report.total_audio} 段音频`, `${report.class_count} 类 · ${report.speaker_count} 个说话人分组 · 排除 ${report.rejected_count || 0} 段`];
  return [`${report.row_count || 0} 行数据`, `${report.feature_count || Math.max((report.column_count || 1) - 1, 0)} 个特征 · 目标 ${report.target_column || "—"}`];
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
  return ["打开任务证据", "在右侧查看当前步骤产生的对象与证据"];
}
function syncAgentCheckpoint(task) {
  const hasRuntimeCheckpoint = (state.conversation?.pending || []).some((item) => item?.rpc_id && (item.kind === "approval" || item.kind === "question"));
  if (state.runtimeReady || hasRuntimeCheckpoint) { restoreCheckpointCard(); clear(ui.agentCheckpointBody); ui.agentCheckpointActions.hidden = true; ui.agentCheckpoint.hidden = true; return; }
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
function revealCurrentWorkspaceObject(task = state.task) {
  const card = task ? checkpointCardFor(task) : null;
  if (!card || checkpointIsInline(card) || card.hidden) return;
  window.requestAnimationFrame(() => card.scrollIntoView({ block: "start", behavior: "smooth" }));
}
function availableWorkspaceContexts(task) {
  const result = task?.current_result || null; const stage = stageKey(task); const nextAction = task?.control?.next_action?.id;
  const contexts = new Set(["plan"]);
  if (task?.dataset_report || ["data_preparation", "contract_review", "ready_to_run"].includes(stage) || ["upload_dataset", "confirm_training_contract"].includes(nextAction)) contexts.add("data");
  if (task?.current_run_id || result) contexts.add("run");
  if (result?.status === "completed" || state.evaluationReport) contexts.add("evaluation");
  if ((result?.artifacts || []).length || state.artifactBundles.length) contexts.add("artifacts");
  return contexts;
}
function syncWorkspaceTabs(task) {
  const contexts = availableWorkspaceContexts(task); let visibleCount = 0;
  ui.contextTabs.querySelectorAll("[data-context]").forEach((button) => { button.hidden = !contexts.has(button.dataset.context); if (!button.hidden) visibleCount += 1; });
  ui.contextTabs.style.setProperty("--visible-context-count", String(Math.max(visibleCount, 1)));
  const hasResults = contexts.has("evaluation") || contexts.has("artifacts"); ui.mobileResultButton.disabled = !hasResults;
  const active = ui.contextTabs.querySelector("[data-context].active"); if (active?.hidden) activateContext("plan");
}
function syncWorkspaceForTask(task) { syncWorkspaceTabs(task); }
function addFact(label, value) { const row = document.createElement("div"); const name = document.createElement("span"); name.textContent = label; const selected = document.createElement("b"); selected.textContent = value === undefined || value === null || value === "" ? "—" : String(value); selected.title = selected.textContent; row.append(name, selected); ui.capabilityFacts.append(row); }
function bindingAnalysisAttempt(task) { return task.repository_analysis_attempt || task.model_binding_attempt || null; }
function renderCapabilityAxes(task) {
  const decision = task.capability_decision || {}; const analysis = task.repository_analysis; const binding = task.model_binding; const searches = state.modelSourceSearches.filter((item) => item.base_spec_revision === task.current_spec_revision); const activeBlocker = (task.blockers || []).find((item) => item.active !== false);
  if (analysis?.status === "complete") { ui.diagnosticCapabilityState.textContent = "静态诊断已完成"; ui.diagnosticCapabilityState.dataset.state = "completed"; ui.diagnosticCapabilityReason.textContent = `已绑定不可变来源并形成仓库分析 ${shortId(analysis.analysis_id || analysis.analysis_digest)}。`; }
  else if (binding || searches.length) { ui.diagnosticCapabilityState.textContent = "诊断进行中"; ui.diagnosticCapabilityState.dataset.state = "running"; ui.diagnosticCapabilityReason.textContent = binding ? "来源已固定，正在等待或检查静态分析证据。" : "已有公开目录搜索证据，仍需人工选择并固定版本。"; }
  else { ui.diagnosticCapabilityState.textContent = decision.status === "resolved" ? "可开始诊断" : "等待需求确认"; ui.diagnosticCapabilityState.dataset.state = decision.status === "resolved" ? "available" : "pending"; ui.diagnosticCapabilityReason.textContent = decision.status === "resolved" ? "可以搜索公开来源并做不执行代码的静态分析。" : "先通过对话明确模型唯一输出。"; }
  const trainingCapability = ConversationView.trainingCapabilityProjection(task); ui.trainingCapabilityState.textContent = trainingCapability.label; ui.trainingCapabilityState.dataset.state = trainingCapability.state; ui.trainingCapabilityState.dataset.code = trainingCapability.code; ui.trainingCapabilityReason.textContent = trainingCapability.reason;
  ui.capabilityRecovery.textContent = `恢复动作：${task.control?.next_action?.description || task.control?.next_action?.label || (activeBlocker?.recovery_actions || [])[0]?.label || "继续在对话中补充当前缺失证据。"}`;
  ui.capabilityNonAction.textContent = task.capability_status === "matched" ? "不会执行：未完成数据、合同和人工审批前，不创建训练 Run。" : "不会执行：不下载权重、不执行第三方源码、不安装依赖、不创建训练 Run。";
}
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
  else if (task.capability_status === "needs_recipe") { ui.capabilityState.textContent = "待扩展"; ui.capabilitySummary.textContent = "现有训练方案无法覆盖该能力。系统已记录能力扩展请求，并且不会伪造训练进度。"; }
  else { ui.capabilityState.textContent = "待识别"; ui.capabilitySummary.textContent = "继续描述输入数据、预测目标和运行限制，以匹配或扩展训练方案。"; }
  renderCapabilityAxes(task); addFact("数据模态", request.modality); addFact("任务目标", request.objective); addFact("输出类型", request.target_kind); addFact("训练方案", task.recipe_id); addFact("数据导入方式", task.data_adapter_id || request.data_adapter); if (build) addFact("扩展请求", build.request_id || build.recipe_request_id);
  if (task.staged_assets?.latest) addFact("构建样例", `${task.staged_assets.latest.status} · ${task.staged_assets.latest.report?.file_count || 0} 个 WAV`);
  if (recipeBuild) { addFact("扩展构建记录", `${recipeBuild.status} · ${shortId(recipeBuild.attempt_id)}`); addFact("候选摘要", recipeBuild.candidate_digest ? shortId(recipeBuild.candidate_digest) : "未生成"); addFact("验证摘要", recipeBuild.validation_digest ? shortId(recipeBuild.validation_digest) : "未生成"); }
  if (task.recipe_version_id) addFact("方案版本", shortId(task.recipe_version_id));
  ui.scaffoldRecipeButton.hidden = Boolean(task.model_binding) || task.capability_status !== "needs_recipe" || decision.selected_family === "audio_classification";
  ui.scaffoldRecipeButton.textContent = build?.status === "scaffold_ready" ? "重新生成训练能力扩展包" : "生成训练能力扩展包";
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
    body: "取消会保留本次尝试的证据，但不会创建模型绑定、仓库分析、训练方案或训练运行。之后可以在同一任务中重试。",
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
  ui.datasetSummary.textContent = report ? `${summary} · ${report.risks?.[0]?.message || "数据体检完成"}` : "导入图片或音频类别 ZIP、或 CSV；格式需符合当前训练方案的数据导入要求。";
  const recipeSamplesNeeded = task.control?.next_action?.id === "stage_recipe_samples";
  ui.datasetButtonLabel.textContent = recipeSamplesNeeded ? "上传构建样例" : "导入数据";
  ui.datasetButton.title = recipeSamplesNeeded ? "上传按类别整理的 PCM WAV 样例 ZIP" : "导入图片、音频 ZIP 或 CSV";
  ui.inspectorDatasetButton.textContent = report ? "替换并重新体检" : "导入数据集"; const specReady = task.capability_decision?.status === "resolved"; const uploadCheckpoint = dataUploadQuestionCheckpoint(currentHumanCheckpoint(state.conversation)); const blocked = !uploadCheckpoint && (task.status === "running" || task.status === "needs_recipe" || !specReady); ui.datasetButton.disabled = recipeSamplesNeeded ? false : blocked; ui.inspectorDatasetButton.disabled = blocked;
}
function gateEntries(gates) { return "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates ? [[gates.clean_test_mae_max, "MAE 上限"], [gates.clean_test_rmse_max, "RMSE 上限"], [gates.clean_test_r2_min, "R² 下限"]] : [[gates.clean_test_accuracy_min, "Accuracy"], [gates.clean_test_macro_f1_min, "Macro-F1"], [gates.clean_test_worst_class_recall_min, "最差类 Recall"]]; }
function renderContract(task) {
  const contract = task.contract; ui.contractCard.hidden = !contract; if (!contract) return; ui.contractState.textContent = task.contract_confirmed ? "已冻结" : "待确认"; clear(ui.gateGrid);
  const gates = contract.release_gates || {}; const regressionGates = "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates; const regressionBasis = regressionGates ? contract.release_gate_basis : null;
  const targetColumn = regressionBasis?.target_column || task.dataset_report?.target_column || "目标列";
  gateEntries(gates).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? value.toFixed(2) : "—"; const span = document.createElement("span"); span.textContent = regressionBasis && (label.startsWith("MAE") || label.startsWith("RMSE")) ? `${label} · 「${targetColumn}」原始单位` : label; cell.append(b, span); ui.gateGrid.append(cell); });
  if (regressionBasis) {
    const improvement = Number(regressionBasis.required_improvement_fraction); const improvementText = Number.isFinite(improvement) ? `，默认要求至少改善 ${Math.round(improvement * 100)}%` : "";
    const basis = document.createElement("p"); basis.className = "gate-basis"; basis.textContent = `系统按当前数据的常数均值基线建议${improvementText}，仍需你确认。`; ui.gateGrid.append(basis);
  }
  const confirmed = task.contract_confirmed === true; const nextAction = task.control?.next_action?.id; const checkpointWriteLocked = Boolean(currentHumanCheckpoint(state.conversation)); const contractWriteLocked = task.status === "running" || checkpointWriteLocked; ui.confirmations.hidden = confirmed;
  ui.approveRunProposalButton.hidden = !confirmed || nextAction !== "start_training_run" || task.status === "running";
  ui.confirmContractButton.disabled = contractWriteLocked; ui.approveRunProposalButton.disabled = contractWriteLocked;
  ui.approveRunProposalButton.textContent = "批准当前训练方案并启动";
  ui.confirmations.querySelectorAll("input").forEach((input) => { input.disabled = contractWriteLocked; input.checked = task.confirmations?.[input.dataset.confirm] === true; });
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
  if (!ui.sampleTrialRunButton.dataset.busy) ui.sampleTrialRunButton.textContent = "交给协调器试跑";
  ui.sampleJsonField.hidden = sampleType !== "tabular"; ui.sampleTrialSelectButton.hidden = sampleType === "tabular"; ui.sampleTrialRunButton.disabled = !ready;
  ui.sampleTrialInput.accept = sampleType === "image" ? "image/png,image/jpeg,image/webp,image/bmp" : sampleType === "audio" ? ".wav,audio/wav" : "";
  if (unavailable) { ui.sampleTrialState.textContent = "API 不可用"; ui.sampleTrialSummary.textContent = "后端没有接通 task-owned sample-inferences API；页面不会模拟推理结果。"; ui.sampleTrialRunButton.disabled = true; }
  else if (!sampleType) { ui.sampleTrialState.textContent = "不可用"; ui.sampleTrialSummary.textContent = `当前训练方案 ${result.recipe || "未识别"} 还不能试跑原始样本。`; ui.sampleTrialRunButton.disabled = true; }
  else if (result.status !== "completed") { ui.sampleTrialState.textContent = "等待完成"; ui.sampleTrialSummary.textContent = "只有完成且通过产物完整性检查的 Run 才能执行真实新样本试跑。"; }
  else { const selected = ui.sampleTrialInput.files?.[0]; ui.sampleTrialState.textContent = selected ? "样本已选择" : state.sampleInferences.length ? `${state.sampleInferences.length} 次记录` : "未试跑"; ui.sampleTrialSummary.textContent = sampleType === "tabular" ? "输入一行与训练特征列匹配的 JSON；暂存后由协调器申请一次授权，再交给评测专家执行。" : selected ? `已选择 ${selected.name} · ${formatBytes(selected.size)}；下一步会先请求授权。` : `选择一份新的${sampleType === "image" ? "图片" : "PCM WAV 音频"}；原始内容不会进入对话或证据报告。`; }
  if (!state.sampleInferences.length) { appendEmpty(ui.sampleInferenceList, "尚无真实新样本试跑记录。"); return; }
  [...state.sampleInferences].reverse().slice(0, 6).forEach((check) => { const row = document.createElement("div"); row.className = "sample-inference-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = check.sample?.source_name || check.check_id; const detail = document.createElement("small"); detail.textContent = check.status === "passed" ? `预测：${JSON.stringify(check.prediction)} · ${Number(check.elapsed_ms || 0).toFixed(1)} ms · SHA ${shortId(check.sample?.sha256)}` : check.reason || "后端阻断了该样本"; const status = document.createElement("em"); status.dataset.state = check.status; status.textContent = check.status === "passed" ? "通过" : "已阻断"; copy.append(title, detail); row.append(copy, status); ui.sampleInferenceList.append(row); });
}
function renderArtifactBundles(result) {
  const completed = result.status === "completed"; ui.buildArtifactBundleButton.disabled = !completed || !state.runtimeReady || state.evidenceErrors.bundles === "capability_unavailable"; clear(ui.artifactBundleList);
  ui.artifactBundleState.textContent = state.artifactBundles.length ? `${state.artifactBundles.length} 个` : completed ? "尚未生成" : "等待完成";
  ui.artifactBundleSummary.textContent = state.evidenceErrors.bundles ? `交付包读取失败：${state.evidenceErrors.bundles}` : "交付包由训练协调器在你确认后生成；下载也需要单独确认，不会绕过当前任务的授权。";
  if (!state.artifactBundles.length) { appendEmpty(ui.artifactBundleList, completed ? "尚无交付包。你发起请求后，协调器会先说明范围并征求确认。" : "训练完成后才能请求生成交付包。"); return; }
  [...state.artifactBundles].reverse().forEach((bundle) => { const row = document.createElement("div"); row.className = "artifact-bundle-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = bundle.bundle_id; const detail = document.createElement("small"); detail.textContent = `${formatBytes(bundle.archive?.size_bytes)} · SHA ${shortId(bundle.archive?.sha256)}`; const download = document.createElement("button"); download.type = "button"; download.className = "artifact-bundle-action"; download.textContent = "请求下载"; download.disabled = !state.runtimeReady; download.title = state.runtimeReady ? "交给训练协调器核对并发起单独下载确认" : "训练协调器未连接，不能发起下载授权"; download.addEventListener("click", () => requestArtifactBundleDownload(result, bundle)); const meta = document.createElement("span"); meta.className = "artifact-bundle-meta"; [[bundle.release_ready ? "release-ready" : "非发布结论"], [bundle.manifest?.privacy_boundary?.raw_data_included === false ? "不含原始数据" : "检查隐私边界"], [`${bundle.manifest?.files?.length || 0} 个文件`]].forEach(([value]) => { const item = document.createElement("i"); item.textContent = value; meta.append(item); }); copy.append(title, detail); row.append(copy, download, meta); ui.artifactBundleList.append(row); });
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
async function stageInferenceInput({ body, filename, contentType, sampleType }) {
  const taskId = state.selectedTaskId; const runId = state.task?.current_result?.run_id;
  if (!taskId || !runId) throw new Error("当前任务没有可绑定的新样本运行。");
  const response = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/inference-inputs`, {
    method: "POST",
    body,
    headers: { "Content-Type": contentType, "X-Filename": encodeURIComponent(filename), "X-Sample-Type": sampleType },
  });
  if (!response?.inference_input?.inference_input_id || !response?.inference_input?.sha256) throw new Error("样本已上传，但后端没有返回可验证的输入对象。");
  return response.inference_input;
}
async function continueWithInferenceInput(inferenceInput, checkpoint = currentHumanCheckpoint(state.conversation)) {
  if (inferenceInputQuestionCheckpoint(checkpoint)) {
    const answers = inferenceInputCheckpointAnswers(checkpoint, inferenceInput);
    await postQuestionAnswers(checkpoint, answers);
    showTransientNotice("新样本已安全暂存，训练协调器会先请求一次明确授权，再交给评测专家试跑。", "ok");
    await refreshSelected({ force: true });
    return;
  }
  await submitMessage(`我已经选择了一份未参与训练的新样本（输入对象 ${inferenceInput.inference_input_id}，摘要 ${inferenceInput.sha256}）。请先核对它属于当前任务和运行，再申请一次试跑授权；授权后交给评测与交付专家执行，不要直接运行。`);
}
async function runSampleTrial() {
  const taskId = state.selectedTaskId; const result = state.task?.current_result; const runId = result?.run_id; const sampleType = sampleTypeForRecipe(result?.recipe); if (!taskId || !runId || result.status !== "completed" || !sampleType) return;
  let body; let filename; let contentType;
  if (sampleType === "tabular") { try { const value = JSON.parse(ui.sampleTrialJson.value); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 必须是一行对象"); body = JSON.stringify(value); filename = "new-sample.json"; contentType = "application/json"; } catch (error) { showNotice(`请输入有效的一行 JSON：${error.message}`); return; } }
  else { const file = ui.sampleTrialInput.files?.[0]; if (!file) { showNotice("请先选择一份新的图片或 WAV 音频样本。"); return; } body = file; filename = file.name; contentType = file.type || (sampleType === "audio" ? "audio/wav" : "application/octet-stream"); }
  setButtonBusy(ui.sampleTrialRunButton, true, "正在安全暂存");
  try { const inferenceInput = await stageInferenceInput({ body, filename, contentType, sampleType }); ui.sampleTrialInput.value = ""; if (sampleType === "tabular") ui.sampleTrialJson.value = ""; closeInspector(); await continueWithInferenceInput(inferenceInput); }
  catch (error) { showNotice(`新样本暂存失败：${error.message}`); }
  finally { setButtonBusy(ui.sampleTrialRunButton, false, ""); if (state.task) renderResult(state.task); }
}
async function buildArtifactBundle() {
  const runId = state.task?.current_result?.run_id; if (!state.selectedTaskId || !runId) return; const latestPassed = [...state.sampleInferences].reverse().find((item) => item.status === "passed");
  setButtonBusy(ui.buildArtifactBundleButton, true, "正在请求协调器");
  try {
    closeInspector();
    const inferenceNote = latestPassed ? `；请使用已通过的新样本试跑 ${latestPassed.check_id} 作为交付证据` : "";
    await submitMessage(`请为当前训练运行 ${runId} 构建可下载交付包${inferenceNote}。请先说明将包含和排除的内容，并在真正构建前让我明确确认。`);
  } finally { setButtonBusy(ui.buildArtifactBundleButton, false, ""); if (state.task) renderResult(state.task); }
}
async function requestArtifactBundleDownload(result, bundle) {
  if (!state.selectedTaskId || !result?.run_id || !bundle?.bundle_id) return;
  closeInspector();
  await submitMessage(`请下载当前运行 ${result.run_id} 的交付包 ${bundle.bundle_id}。请先核对交付包摘要与完整性，并在真正下载前让我单独确认；不要复用构建授权。`);
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
  const events = state.runEvents || []; ui.runEventCount.textContent = String(events.length); clear(ui.inspectorEvents);
  if (!events.length) { const empty = document.createElement("p"); empty.textContent = "尚无运行事件；训练启动后只呈现后端真实事件。"; ui.inspectorEvents.append(empty); return; }
  events.forEach((event) => {
    const row = document.createElement("div"); const seq = document.createElement("i"); seq.textContent = event.seq; const side = document.createElement("span"); const name = document.createElement("b"); name.textContent = EVENT_LABELS[event.type] || event.type; const small = document.createElement("small"); small.textContent = eventDetail(event); side.append(name, small); row.append(seq, side); ui.inspectorEvents.append(row);
  });
}
function renderRunControl(task) {
  const result = task.current_result; const active = Boolean(result && RUNNING_STATUSES.has(result.status)); const retryable = Boolean(result && TERMINAL_RETRY_STATUSES.has(result.status) && task.control?.next_action?.id === "retry_training_run"); const cancelRequested = result?.cancel_requested === true;
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
function taskEvidenceLedger(task) {
  const ledger = []; const revisions = state.taskSpecRevisions.length ? state.taskSpecRevisions : task.task_spec ? [task.task_spec] : [];
  revisions.forEach((spec, index) => {
    const decision = spec.capability_decision || {}; const capability = spec.capability_request || {}; const note = String(spec.user_note || "");
    const selectedCandidate = decision.candidates?.find((item) => item.family === decision.selected_family);
    const confirmedOutput = selectedCandidate?.output || (capability.target_kind && capability.target_kind !== "待确认输出" ? capability.target_kind : selectedCandidate?.label || decision.selected_family || "已确认输出");
    const systemOnlyNote = /^用户通过产品界面(?:修订|确认)$/u.test(note);
    if (index > 0 && note && !systemOnlyNote) ledger.push({ kind: "system_record", source: "persisted_task_projection", evidenceKey: `spec:${spec.revision}:user`, label: `需求版本 v${spec.revision} 的用户补充`, detail: note.replace(/^用户(?:补充|选择后端候选|确认后端候选)[:：]?/u, "").trim() || note, time: spec.created_at_utc });
    if (decision.status === "resolved") ledger.push({ kind: "system_record", source: "persisted_task_projection", evidenceKey: `spec:${spec.revision}`, label: `需求版本 v${spec.revision} 已确认`, detail: `${capability.modality || "未知输入"} / ${decision.selected_family || capability.objective || "训练任务"} / ${confirmedOutput}。完整技术字段已写入训练详情。`, time: spec.created_at_utc || task.created_at_utc });
    else if (index > 0) ledger.push({ kind: "system_record", source: "persisted_task_projection", evidenceKey: `spec:${spec.revision}`, label: `需求版本 v${spec.revision} 等待确认`, detail: `系统已根据补充重新判定；当前仍需确认：${decision.question || "模型唯一输出"}`, time: spec.created_at_utc });
  });
  [...state.modelSourceSearches].sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || ""))).forEach((search) => {
    const errors = search.provider_errors || []; const count = search.candidates?.length || 0;
    const allProvidersFailed = Boolean(errors.length && errors.length >= (search.providers?.length || 1));
    ledger.push({ kind: "system_record", source: "persisted_task_projection", status: count ? "completed" : allProvidersFailed ? "failed" : "completed_empty", evidenceKey: search.search_id, label: "官方模型目录搜索记录", detail: `${search.query_plan?.effective_query || "自动搜索词"} · ${count} 个候选${errors.length ? ` · ${errors.length} 个 Provider 返回错误` : ""} · ${search.search_id}`, time: search.created_at });
  });
  const binding = task.model_binding;
  if (binding) ledger.push({ kind: "system_record", source: "persisted_task_projection", status: binding.status === "stale" ? "failed" : "completed", evidenceKey: binding.binding_revision_id || binding.resolution_id, label: "固定模型来源记录", detail: `${binding.repository} @ ${shortId(binding.resolved_commit)} · ${binding.status === "stale" ? "已因新规格失效" : "不可变版本已绑定"}`, time: binding.created_at });
  const analysis = task.repository_analysis; const analysisAttempt = bindingAnalysisAttempt(task);
  if (analysis) ledger.push({ kind: "system_record", source: "persisted_task_projection", status: analysis.status === "complete" && !(analysis.downstream_blockers || []).length ? "completed" : "failed", evidenceKey: analysis.analysis_digest || analysis.analysis_id, label: "仓库静态分析记录", detail: `${REPOSITORY_ANALYSIS_STATUS_LABELS[analysis.status] || analysis.status || "未知状态"} · ${(analysis.training_entrypoints || []).length} 个训练入口 · digest ${shortId(analysis.analysis_digest)}`, time: analysis.created_at || analysisAttempt?.current_state?.updated_at || binding?.created_at });
  else if (analysisAttempt) {
    const attemptStatus = analysisAttempt.current_state?.status || "queued"; const failure = analysisAttempt.current_state?.failure; const attemptId = analysisAttempt.attempt?.attempt_id;
    ledger.push({ kind: "system_record", source: "persisted_task_projection", status: ["failed", "cancelled"].includes(attemptStatus) ? "failed" : attemptStatus === "completed" ? "completed" : "running", evidenceKey: attemptId, label: "绑定与分析记录", detail: `${attemptStatus} · attempt ${shortId(attemptId)}${failure ? ` · ${failure.code || "unknown_failure"}: ${failure.message || "没有错误详情"}` : " · 尚未执行第三方代码"}`, time: analysisAttempt.current_state?.updated_at || analysisAttempt.attempt?.created_at });
  }
  const planView = task.training_plan; const plan = planView?.plan;
  if (plan) {
    ledger.push({ kind: "system_record", source: "persisted_task_projection", status: planView.stale ? "failed" : "completed", evidenceKey: plan.training_plan_revision_id, label: "不可变训练计划记录", detail: `r${plan.revision} · digest ${shortId(plan.plan_sha256)}${planView.stale ? " · 已失效" : ""}`, time: plan.created_at });
    if (planView.latest_approval) ledger.push({ kind: "system_record", source: "persisted_task_projection", status: planView.latest_approval.decision === "approve" ? "completed" : "failed", evidenceKey: planView.latest_approval.approval_id, label: "训练计划审批记录", detail: `${planView.latest_approval.decision} · 绑定 digest ${shortId(planView.latest_approval.plan_sha256 || plan.plan_sha256)}`, time: planView.latest_approval.created_at });
  }
  const feasibility = task.resource_feasibility || {}; const probe = feasibility.resource_probe; const report = feasibility.resource_fit_report; const blockers = feasibility.blockers || [];
  if (probe) ledger.push({ kind: "system_record", source: "persisted_task_projection", status: "completed", evidenceKey: probe.probe_sha256, label: "本机资源探测记录", detail: `${probe.cpu?.logical_count || "未知"} 线程 · ${formatBytes(probe.ram?.available_bytes)} 可用内存 · digest ${shortId(probe.probe_sha256)}`, time: probe.captured_at });
  if (report || blockers.length) ledger.push({ kind: "system_record", source: "persisted_task_projection", status: report?.decision === "fit" ? "completed" : "failed", evidenceKey: report?.report_sha256 || blockers[0]?.blocker_id || `resource:${plan?.training_plan_revision_id}`, label: "训练资源可行性记录", detail: report ? `${report.decision} · report ${shortId(report.report_sha256)}` : `${feasibility.decision || "blocked"} · ${blockers[0]?.message || blockers[0]?.code || "资源阻断"}`, time: report?.created_at || probe?.captured_at });
  const result = task.current_result; const evaluation = state.evidenceRunId === result?.run_id ? state.evaluationReport || result?.evaluation_report : result?.evaluation_report;
  if (result?.status === "completed" && evaluation) {
    const metrics = metricEntries(result).filter(([value]) => typeof value === "number").map(([value, label]) => `${label} ${value.toFixed(3)}`).join(" · ") || "当前报告没有可展示的核心指标";
    const failure = result.failure_samples?.[0]; const [failureName, failureDetail] = failure ? failureSummary(failure) : ["无", "独立测试集没有记录可展示的失败样本"];
    const conclusion = statusLabel(evaluation.conclusion || result.evaluation_conclusion || "not_evaluated");
    const reasons = [...(evaluation.evidence_reasons || []), ...(evaluation.integrity_errors || [])];
    const gap = reasons.join("；") || (evaluation.release_ready ? "运行、产物、指标与证据充分性均通过" : result.offline_gates_passed ? "离线指标已通过，但交付证据仍未全部满足" : "至少一个离线指标未达到训练合同门槛");
    const next = evaluation.release_ready ? "用一份未参与训练的新样本试跑，确认后生成 Artifact Bundle。" : "在右侧评测报告查看失败样本和门槛差距，再决定补数据、调参数或创建新 Run。";
    const evaluationDigest = evaluation.report_sha256 || evaluation.evaluation_report_id || evaluation.evaluation_id || evaluation.content_sha256 || "embedded-report";
    ledger.push({ kind: "system_record", source: "persisted_task_projection", status: "completed", evidenceKey: `result-summary:${result.run_id}:${evaluationDigest}`, label: "评测结果记录", detail: `结论：${conclusion}\n核心指标：${metrics}\n主要失败样本：${failureName}（${failureDetail}）\n与验收门槛的差距：${gap}\n建议下一步：${next}`, time: evaluation.created_at || result.completed_at || result.updated_at });
  }
  return ledger;
}
function conversationView(task, remoteConversation) {
  if (!ConversationView) throw new Error("Conversation schema v2 renderer is unavailable");
  const local = localConversation(task);
  return ConversationView.buildConversationView({ remoteConversation, localItems: local.items, ledgerItems: taskEvidenceLedger(task) });
}
function interactionProjection(task, conversation) {
  if (!InteractionShell) return {
    phase: "failed", reason_code: "interaction_projection_unavailable", turns: [], actions: [], current_actions: [], specialists: [], checkpoint: null,
    result: { ready: false, object_refs: [], run_id: null }, observation: { degraded: true, projection_errors: [] },
    workspace: { mode: "status", context: "error", open: true, auto_key: `${task?.task_id || "task"}:projection-unavailable` },
  };
  return InteractionShell.deriveInteractionProjection({ task, conversation });
}
const WORKSPACE_PHASE_COPY = {
  clarifying: { eyebrow: "需要你的回答", title: "先把需求说清楚", badge: "等待回答", summary: "协调器提出了一个会改变模型路径的问题。请直接在对话中选择或补充。", toggle: "任务信息" },
  awaiting_approval: { eyebrow: "需要你的确认", title: "一项关键操作等待批准", badge: "等待批准", summary: "批准卡会说明操作对象、影响和范围；聊天文字不会被当作授权。", toggle: "待确认" },
  executing: { eyebrow: "实时执行", title: "AI 正在推进当前任务", badge: "执行中", summary: "这里只展示后端已经记录的协调器动作、真实专家委派和可追溯产物。", toggle: "执行进展" },
  result_ready: { eyebrow: "结果已就绪", title: "本轮已经产生可核对结果", badge: "有新结果", summary: "对话给出结论，这里展示同一任务的结果对象、训练运行和评测证据。", toggle: "查看结果" },
  blocked: { eyebrow: "当前受阻", title: "需要选择一条可恢复路径", badge: "需要处理", summary: "能力缺口、资源限制或安全门不会被包装成训练失败；可恢复动作会保留在当前任务。", toggle: "查看阻断" },
  failed: { eyebrow: "本轮异常", title: "执行或观察链路需要恢复", badge: "需要恢复", summary: "技术错误与模型训练结果分开呈现。已完成的任务事实和历史证据不会被覆盖。", toggle: "查看异常" },
  idle: { eyebrow: "当前任务", title: "继续通过对话推进", badge: "等待输入", summary: "需要执行或产生结果时，这里会自适应展开。", toggle: "训练详情" },
};
function uniqueTaskObjectRefs(task, projection) {
  const taskId = task?.task_id; const seen = new Set(); const refs = [];
  const candidates = [...(projection.result?.object_refs || []), ...(projection.actions || []).flatMap((action) => action.object_refs || [])];
  candidates.forEach((ref) => {
    if (!ref?.type || !ref?.id || (taskId && ref.task_id !== taskId)) return;
    const key = `${ref.task_id || "task"}:${ref.type}:${ref.id}`; if (seen.has(key)) return; seen.add(key); refs.push(ref);
  });
  return refs;
}
const ACTIVE_SPECIALIST_STATUSES = new Set(["queued", "active", "running", "waiting", "cancelling"]);
function projectionWorkItems(projection) { return Array.isArray(projection?.work_items) ? projection.work_items : []; }
function projectionSpecialists(projection) { return Array.isArray(projection?.specialists) ? projection.specialists : []; }
function activeProjectionSpecialists(projection) { return projectionSpecialists(projection).filter((item) => ACTIVE_SPECIALIST_STATUSES.has(runtimeStatusToken(item.status))); }
function specialistWorkItem(projection, specialist) {
  const latestId = specialist?.latest_work_item_id;
  if (!latestId) return null;
  return projectionWorkItems(projection).find((item) => item.work_item_id === latestId) || null;
}
function workspaceWorkStatus(value) {
  return ({ queued: "排队中", active: "执行中", running: "执行中", waiting: "等待依赖", cancelling: "正在停止", completed: "已完成", failed: "需要处理", cancelled: "已取消", interrupted: "已中断", observed: "已记录", unknown: "状态未知" })[runtimeStatusToken(value)] || "状态未知";
}
function renderWorkspaceAgent(item) {
  const card = document.createElement("article"); card.className = "workspace-agent-card"; card.dataset.status = item.status || "observed";
  const mark = document.createElement("i"); mark.textContent = String(item.role?.label || roleLabel(item.role?.role_id)).slice(0, 2);
  const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = item.role?.label || roleLabel(item.role?.role_id); const summary = document.createElement("p"); summary.textContent = item.assignment?.summary || "已收到协调器的结构化委派。"; copy.append(title, summary);
  const status = document.createElement("em"); status.textContent = workspaceWorkStatus(item.status); card.append(mark, copy, status); ui.workspaceTeamList.append(card);
}
function renderWorkspaceCoordinator(projection) {
  const action = projection.current_actions?.find((item) => item.status === "running") || projection.current_actions?.at(-1);
  const card = document.createElement("article"); card.className = "workspace-agent-card"; card.dataset.status = action?.status || "running";
  const mark = document.createElement("i"); mark.textContent = "AI"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = "训练协调器"; const summary = document.createElement("p"); summary.textContent = action ? actionTitle(action) : "正在理解任务并决定是否需要训练团队协作。"; copy.append(title, summary); const status = document.createElement("em"); status.textContent = action ? actionStatusLabel(action) : "处理中"; card.append(mark, copy, status); ui.workspaceTeamList.append(card);
}
function renderWorkspaceResultRef(ref) {
  const button = document.createElement("button"); button.type = "button"; button.className = "workspace-result-card";
  const mark = document.createElement("i"); mark.textContent = "✓"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = ref.label || ({ model_source_search: "模型候选", dataset_report: "数据体检", evaluation_report: "评测报告", artifact_bundle: "交付产物" })[ref.type] || ref.type; const summary = document.createElement("p"); summary.textContent = `可追溯对象 · ${shortId(ref.id)}`; copy.append(title, summary); const action = document.createElement("em"); action.textContent = "打开"; button.append(mark, copy, action); button.addEventListener("click", () => openObjectRef(ref)); ui.workspaceResultList.append(button);
}
function workspaceEvaluationOutcome(task) {
  if (!InteractionShell?.deriveEvaluationOutcome) return { ready: false, comparison: null, decision: null };
  const result = task?.current_result; const fresh = state.evidenceRunId === result?.run_id ? state.evaluationReport : null;
  return InteractionShell.deriveEvaluationOutcome({ task, evaluation: fresh || result?.evaluation_report || null });
}
function workspaceMetricValue(value) { return Number.isFinite(value) ? value.toFixed(3) : "—"; }
function renderWorkspaceDecision(outcome) {
  const section = document.createElement("section"); section.className = "workspace-evaluation-summary"; section.dataset.recommended = outcome.decision.recommended; section.dataset.interactionKind = "evaluation-verdict";
  const heading = document.createElement("header"); const headingCopy = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "可信评测"; const title = document.createElement("h4"); title.textContent = "基线对比与人工决策门"; headingCopy.append(kicker, title); const verdict = document.createElement("b"); verdict.dataset.state = outcome.release_ready ? "ready" : "blocked"; verdict.textContent = outcome.release_ready ? "可进入发布审阅" : statusLabel(outcome.conclusion); heading.append(headingCopy, verdict); section.append(heading);
  const comparison = outcome.comparison;
  if (comparison) {
    const flow = document.createElement("div"); flow.className = "workspace-comparison-flow";
    [["基线", comparison.baseline], ["本轮已选", comparison.selected]].forEach(([label, candidate], index) => { if (index) { const arrow = document.createElement("i"); arrow.textContent = "→"; arrow.setAttribute("aria-hidden", "true"); flow.append(arrow); } const card = document.createElement("div"); const name = document.createElement("span"); name.textContent = label; const model = document.createElement("b"); model.textContent = candidate.name; const metric = document.createElement("small"); metric.textContent = `验证集 ${comparison.metric_label} · ${workspaceMetricValue(candidate.value)}`; card.append(name, model, metric); flow.append(card); });
    section.append(flow);
    const degradation = document.createElement("p"); degradation.className = "workspace-degradation"; degradation.dataset.state = comparison.degraded ? "degraded" : comparison.unchanged ? "unchanged" : "improved"; degradation.textContent = comparison.degraded ? "相对基线出现退化" : comparison.unchanged ? "与基线持平" : "相对基线未退化"; section.append(degradation);
  } else {
    const missing = document.createElement("p"); missing.className = "workspace-comparison-missing"; missing.textContent = "评测已完成，但没有同时提供明确基线与已选候选的可比验证指标，因此不展示数值对比。"; section.append(missing);
  }
  const gate = document.createElement("div"); gate.className = "workspace-decision-gate"; gate.dataset.interactive = "false"; const gateHeading = document.createElement("header"); const gateTitle = document.createElement("b"); gateTitle.textContent = "系统建议"; const gateHint = document.createElement("small"); gateHint.textContent = "只读 · 出现真实确认卡后才能执行"; gateHeading.append(gateTitle, gateHint); gate.append(gateHeading);
  const gateCopy = {
    publish: outcome.decision.publish === "ready" ? "可信评测允许进入发布审阅；发布仍需人工确认。" : "评测尚未满足 release-ready，不能发布。",
    rollback: outcome.decision.rollback === "recommended" ? "已观察到相对基线退化，建议回滚或保留基线。" : comparison ? "当前对比没有显示退化，无需回滚。" : "没有可比基线指标，暂不建议自动回滚。",
    optimize: outcome.decision.optimize === "recommended" ? "建议补数据或调整训练方案后创建新 Run。" : outcome.decision.rollback === "recommended" ? "先处理退化，再决定是否继续优化。" : "结果可发布审阅；仍可选择继续优化。",
  };
  [["publish", "发布", outcome.decision.publish], ["rollback", "回滚", outcome.decision.rollback], ["optimize", "继续优化", outcome.decision.optimize]].forEach(([key, label, gateState]) => { const item = document.createElement("div"); item.dataset.state = gateState; item.dataset.decision = key; item.setAttribute("aria-disabled", "true"); const name = document.createElement("span"); name.textContent = label; const stateLabel = document.createElement("em"); stateLabel.textContent = gateState === "recommended" ? "建议" : gateState === "ready" ? "可审阅" : gateState === "blocked" ? "未解锁" : gateState === "not_needed" ? "无需" : "可选"; const copy = document.createElement("small"); copy.textContent = gateCopy[key]; item.append(name, stateLabel, copy); gate.append(item); });
  section.append(gate); ui.workspaceResultList.prepend(section); return true;
}
function renderWorkspaceExperience(task, conversation, projection) {
  state.workspaceProjection = projection; const basePhaseCopy = WORKSPACE_PHASE_COPY[projection.phase] || WORKSPACE_PHASE_COPY.idle; const phaseCopy = projection.phase === "executing" && projection.background?.coordinator_reply_complete ? { ...basePhaseCopy, title: "协调器已回复，后台任务仍在运行", badge: "后台运行中", summary: "协调器这一轮已经回复，但训练或评测尚未终态。最终指标与发布判断会等真实评测完成后再出现。" } : basePhaseCopy; const specialists = projectionSpecialists(projection); const activeSpecialists = activeProjectionSpecialists(projection); const refs = uniqueTaskObjectRefs(task, projection); const evaluationOutcome = workspaceEvaluationOutcome(task);
  ui.workspaceExperience.hidden = false; ui.workspaceExperience.dataset.phase = projection.phase; ui.workspaceEyebrow.textContent = phaseCopy.eyebrow; ui.workspaceTitle.textContent = phaseCopy.title; ui.workspacePhaseBadge.textContent = phaseCopy.badge; ui.workspaceSummary.textContent = phaseCopy.summary; ui.workspaceToggleButton.querySelector("span").textContent = phaseCopy.toggle;
  clear(ui.workspaceTeamList); const showExecution = projection.phase === "executing" || specialists.length > 0; ui.workspaceTeam.hidden = !showExecution;
  if (showExecution) {
    const visibleSpecialists = activeSpecialists.length ? activeSpecialists : specialists;
    visibleSpecialists.forEach((specialist) => { const item = specialistWorkItem(projection, specialist); if (item) renderWorkspaceAgent({ ...item, status: specialist.status }); });
    if (!activeSpecialists.length && projection.phase === "executing") renderWorkspaceCoordinator(projection);
    ui.workspaceTeamCount.textContent = activeSpecialists.length ? `${activeSpecialists.length} 位协作中` : specialists.length ? `${specialists.length} 类专家记录` : "仅协调器";
    ui.workspaceTeamTitle.textContent = activeSpecialists.length ? "当前智能体协作" : specialists.length ? "本任务智能体记录" : "训练协调器正在处理";
  }
  clear(ui.workspaceResultList); refs.forEach(renderWorkspaceResultRef); const renderedEvaluation = evaluationOutcome.ready ? renderWorkspaceDecision(evaluationOutcome) : false; const resultCount = refs.length + (projection.result?.run_id ? 1 : 0) + (renderedEvaluation ? 1 : 0); ui.workspaceResults.hidden = resultCount === 0; ui.workspaceResultsTitle.textContent = renderedEvaluation ? "评测结果与下一步" : "本轮产生的结果"; ui.workspaceResultCount.textContent = `${resultCount} 项`;
  if (projection.result?.run_id) { const run = document.createElement("article"); run.className = "workspace-result-card"; const mark = document.createElement("i"); mark.textContent = "R"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = "训练运行"; const summary = document.createElement("p"); summary.textContent = shortId(projection.result.run_id); copy.append(title, summary); const status = document.createElement("em"); status.textContent = evaluationOutcome.ready ? "评测完成" : task.current_result?.status === "completed" ? "训练完成" : "已记录"; run.append(mark, copy, status); ui.workspaceResultList.prepend(run); }
  ui.workspaceTechnicalButton.textContent = renderedEvaluation ? "查看完整评测证据" : "查看训练详情";
  ui.workspaceTruthNote.textContent = renderedEvaluation ? "指标只来自当前 Run 的真实评测；发布、回滚或继续优化仍需人工确认。" : projection.result?.run_id ? "当前 Run 尚无匹配的可信评测，因此不展示指标或发布门。" : specialists.length ? "专家记录只来自当前任务已验证的父子会话；历史记录不会被描述为正在参与。" : "当前没有已验证专家委派；不会用角色配置冒充多智能体协作。";
  const autoOpen = projection.workspace?.auto_open === true; const autoKey = projection.workspace?.auto_key || `${task.task_id}:${projection.phase}`;
  if (!dockedWorkspaceMedia.matches || !autoOpen) {
    if (state.inspectorAutoOpened && ui.inspector.dataset.open === "true") closeInspector({ userInitiated: false });
    return;
  }
  if (state.workspaceAutoKey === autoKey || state.workspaceDismissedKey === autoKey) return;
  state.workspaceAutoKey = autoKey; openInspector(workspaceContextForProjection(projection), { presentation: projection.workspace?.presentation || "experience", auto: true });
}
function workspaceContextForPhase(phase) { return phase === "result_ready" ? "evaluation" : phase === "executing" ? "run" : "plan"; }
function workspaceContextForProjection(projection = state.workspaceProjection) { return projection?.workspace?.technical_context || workspaceContextForPhase(projection?.phase); }
function conversationObservationKey(conversation) {
  const remote = state.conversation || {};
  const runtimeAgent = state.productRuntime?.agent || {};
  const itemProjectorRevisions = [...new Set((remote.items || []).map((item) => item?.projector_revision).filter(Boolean))];
  const eventVerdicts = (remote.items || []).map((item) => item?.payload?.synthesis_verdict || item?.synthesis_verdict).filter(Boolean);
  const runVerdicts = (remote.runs || []).map((run) => ({
    run_id: run?.run_id || null,
    status: run?.status || null,
    synthesis_verdict_version: run?.synthesis_verdict_version || null,
    accepted_candidate_event_id: run?.accepted_candidate_event_id || null,
    verdict_reason_codes: run?.verdict_reason_codes || [],
  }));
  return {
    projector_revision: remote.conversation_projector_revision || remote.projector_revision || runtimeAgent.conversation_projector_revision || null,
    item_projector_revisions: itemProjectorRevisions,
    verdict: {
      version: remote.synthesis_verdict_version || runtimeAgent.synthesis_verdict_version || null,
      events: eventVerdicts,
      runs: runVerdicts,
    },
    projection_errors: conversation.projection_errors || remote.projection_errors || [],
    projection_health: conversation.projection_health || remote.projection_health || null,
    stream_health: remote.stream_health || runtimeAgent.stream_health || null,
    client_stream_degraded: state.conversationStreamDegraded,
  };
}
function renderProjectionHealth(conversation) {
  if (!state.conversationStreamDegraded && conversation.projection_health?.status !== "observation_degraded") return;
  const errors = conversation.projection_errors || [];
  const streamHealth = state.conversation?.stream_health || state.productRuntime?.agent?.stream_health || {};
  const streamLabel = ({ degraded: "连接异常", stopped: "已停止", connecting: "正在重连", healthy: "已连接", not_started: "未启动", not_observed: "未观测" })[streamHealth.status] || "状态未知";
  const card = document.createElement("aside"); card.className = "observation-health"; card.dataset.state = "observation_degraded"; card.setAttribute("role", "status"); card.setAttribute("aria-live", "polite");
  const mark = document.createElement("span"); mark.setAttribute("aria-hidden", "true"); mark.textContent = "!";
  const copy = document.createElement("div"); const title = document.createElement("b"); const detail = document.createElement("p"); const meta = document.createElement("small");
  title.textContent = "观察链路已降级，当前结果不能视为完整成功";
  detail.textContent = "事件流或投影出现异常，可能遗漏待审批或待回答的问题。请先重新连接并刷新任务，再依据恢复后的证据继续。";
  meta.textContent = `${errors.length ? `已记录 ${errors.length} 项投影异常` : "投影完整性异常"} · 事件流：${streamLabel}`;
  copy.append(title, detail, meta);
  const action = document.createElement("button"); action.type = "button"; action.textContent = "重新连接并刷新";
  action.addEventListener("click", async () => {
    setButtonBusy(action, true, "正在重连");
    try {
      await loadRuntime();
      if (state.runtimeReady && state.selectedTaskId) {
        await refreshSelected({ force: true });
        startConversationStream(state.selectedTaskId, state.selectionToken);
      }
      else showNotice("训练协调器仍未恢复；当前结果继续按观察降级处理。", "error");
    } finally { setButtonBusy(action, false, ""); }
  });
  card.append(mark, copy, action); ui.messageList.append(card);
}
function renderAgentSurfaceState(conversation, projection) {
  const specialists = projectionSpecialists(projection);
  const activeSpecialists = activeProjectionSpecialists(projection);
  const hasSession = Boolean(conversation?.session_id || state.conversation?.session_id);
  if (state.runtimeReady && hasSession && activeSpecialists.length) return;
  const card = document.createElement("article"); card.className = "agent-surface-state"; card.dataset.state = state.runtimeReady ? "ready" : "unavailable";
  const mark = document.createElement("span"); mark.textContent = state.runtimeReady ? "AI" : "!";
  const copy = document.createElement("div"); const title = document.createElement("b"); const detail = document.createElement("p");
  title.textContent = state.runtimeReady ? hasSession ? "当前由训练协调器处理" : "训练协调器已就绪" : state.runtimeIssue === "provider" ? "模型服务尚未配置，对话已暂停" : state.runtimeIssue === "incompatible" ? "AI 服务版本不兼容，对话已暂停" : "训练协调器未连接，对话已暂停";
  detail.textContent = state.runtimeReady ? hasSession ? specialists.length ? `当前没有训练团队成员在执行；本任务保留 ${specialists.length} 类已验证协作记录。再次分工时，新动作会实时出现在对话中。` : "当前由训练协调器处理。需要模型检索、数据诊断、资源评估或训练时，训练团队及其真实动作才会出现在对话中。" : "在下方继续描述目标或问题。协调器会先理解你的目标和已有信息，再规划下一步；需要你决定时，它会停下来问你。" : state.runtimeIssue === "provider" ? "请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动。完成前只能查看已保存的任务与证据，不会创建新任务或伪装智能体结果。" : state.runtimeIssue === "incompatible" ? "当前页面与智能协作服务的协议不匹配。页面不会把旧会话或固定步骤当成实时进展，请重启正式服务。" : "当前页面只能查看已经保存的任务与证据；无法理解新需求、生成计划或调度训练团队，也不会用固定步骤冒充实时进度。";
  copy.append(title, detail); card.append(mark, copy);
  if (!state.runtimeReady) {
    const action = document.createElement("button"); action.type = "button"; action.textContent = state.runtimeIssue === "provider" ? "重新检查模型服务" : "重新检查连接";
    action.addEventListener("click", async () => {
      setButtonBusy(action, true, "检查中");
      try {
        await loadRuntime();
        if (state.runtimeReady && state.selectedTaskId) {
          await refreshSelected({ force: true });
          startConversationStream(state.selectedTaskId, state.selectionToken);
        } else if (state.runtimeIssue === "provider") showRuntimeSetupNotice("模型服务仍未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。");
        else showNotice("训练协调器仍未连接；没有启动任何固定流程替代智能协作。");
      } finally { setButtonBusy(action, false, ""); }
    });
    card.append(action);
  }
  ui.messageList.append(card);
}
function renderConversation(force = false) {
  const conversation = conversationView(state.task, state.conversation);
  const projection = interactionProjection(state.task, conversation);
  syncConversationComposerPlaceholder(conversation, state.task);
  const workItems = projectionWorkItems(projection);
  const activeSpecialists = activeProjectionSpecialists(projection);
  if (state.runtimeReady) {
    ui.composerModeLabel.textContent = activeSpecialists.length ? `训练协调器 · ${activeSpecialists.length} 位专家协作中` : "训练协调器";
    ui.composerMode.title = activeSpecialists.length ? "只统计当前仍在执行、且父子会话身份已验证的专家" : "当前没有专家在执行；历史专家记录不会冒充当前参与者";
  }
  syncComposerDelivery(conversation);
  if (state.task) { syncTaskHeader(state.task, conversation, projection); syncTaskSpecCheckpointOwnership(conversation); syncSelectedTaskListStatus(conversation); }
  const observation = conversationObservationKey(conversation);
  const optimistic = state.pendingMessage?.task_id === state.selectedTaskId ? state.pendingMessage : null;
  const items = [...(conversation.items || [])];
  const hasRuntimeCheckpoint = Boolean(projection.checkpoint);
  if (hasRuntimeCheckpoint) ui.agentCheckpoint.hidden = true;
  else if (state.task) syncAgentCheckpoint(state.task);
  const backgroundRun = activeBackgroundTrainingRun(conversation);
  const serverCancelling = backgroundCancellationPending(conversation);
  const renderKey = JSON.stringify({ schema: conversation.schema_version, actionSchema: conversation.action_schema_version, items: conversation.items, actions: conversation.actions, agents: conversation.agents, delegations: conversation.delegations, workItems: conversation.work_items, running: conversation.running, executionRunning: conversation.execution_running, agentResponseRunning: conversation.agent_response_running, backgroundActionRunning: conversation.background_action_running, trainingRun: backgroundRun ? [backgroundRun.training_run_id || backgroundRun.run_id || backgroundRun.action_id, backgroundRun.status, backgroundRun.domain_status, backgroundRun.cancel_requested] : null, interactionState: conversation.interaction_state, canonicalInteraction: conversation.interaction_projection, phase: projection.phase, workspace: projection.workspace, canCancelAgent: conversation.can_cancel_agent, active: conversation.active_event?.action_id || conversation.active_event?.event_id || conversation.active_event?.training_run_id || conversation.active_event?.run_id, observation, optimistic: optimistic?.text, taskStatus: state.task?.status, runtimeReady: state.runtimeReady, sessionId: state.conversation?.session_id || null });
  if (!force && renderKey === state.lastRenderKey) return; state.lastRenderKey = renderKey;
  const nearBottom = ui.conversation.scrollHeight - ui.conversation.scrollTop - ui.conversation.clientHeight < 120; clear(ui.messageList); ui.messageList.dataset.projectionHealth = conversation.projection_health?.status || "unknown"; renderProjectionHealth(conversation); renderAgentSurfaceState(conversation, projection);
  projection.turns.forEach((turn) => renderConversationTurn(turn, projection, conversation, workItems));
  if (optimistic && !items.some((item) => item.kind === "message" && item.role === "user" && item.text === optimistic.text)) renderConversationItem({ kind: "message", role: "user", text: optimistic.text, time: optimistic.time, optimistic: true });
  renderWorkspaceExperience(state.task, conversation, projection);
  ui.conversationIntro.hidden = projection.turns.length > 0 || Boolean(projection.actions?.length);
  const agentResponseRunning = conversationAgentResponseRunning(conversation);
  const backgroundTrainingRunning = conversationHasBackgroundTraining(conversation);
  const currentAiTurn = ui.messageList.querySelector('.ai-turn[data-current="true"]');
  const fallbackWorkingSurface = !currentAiTurn && (agentResponseRunning || backgroundTrainingRunning || Boolean(optimistic) || serverCancelling);
  ui.agentWorking.hidden = !fallbackWorkingSurface;
  ui.cancelAgentButton.hidden = Boolean(currentAiTurn) || (conversation.can_cancel_agent !== true && !backgroundRun);
  if (optimistic && !agentResponseRunning && !backgroundTrainingRunning) ui.agentWorkingLabel.textContent = "正在发送";
  else if (backgroundTrainingRunning) ui.agentWorkingLabel.textContent = `后台训练 ${shortId(backgroundRun?.training_run_id || backgroundRun?.run_id || backgroundRun?.action_id)} 正在运行；你可以继续和训练协调器交流`;
  else if (agentResponseRunning && !conversation.active_event) ui.agentWorkingLabel.textContent = "训练协调器正在处理";
  else ui.agentWorkingLabel.textContent = agentActivityLabel(conversation.active_event);
  syncCancelRequestUi(conversation);
  if (force || nearBottom) requestAnimationFrame(() => { ui.conversation.scrollTop = ui.conversation.scrollHeight; });
}
function actionsForTurn(turn, projection) {
  const agentRunIds = new Set(turn.agent_run_ids || []); if (turn.agent_run_id) agentRunIds.add(turn.agent_run_id);
  const sourceTurnIds = new Set(turn.source_turn_ids || []); if (turn.turn_id) sourceTurnIds.add(turn.turn_id);
  if (agentRunIds.size) return (projection.actions || []).filter((action) => agentRunIds.has(action.agent_run_id) || (!action.agent_run_id && sourceTurnIds.has(action.turn_id)));
  return (projection.actions || []).filter((action) => turn.turn_id ? sourceTurnIds.has(action.turn_id) : !action.turn_id);
}
function recoveredDataExperimentFailures(actions, risks = []) {
  // Keep the legacy function name for callers, but recovery is no longer a
  // data-experiment UI heuristic.  Only the backend's canonical risk
  // lifecycle can say that a historical failure was superseded by a later
  // successful action; original action status and evidence remain unchanged.
  const recoveredActionIds = InteractionShell.supersededFailureSourceIds(risks);
  return new Set((actions || []).filter((action) => (
    action?.status === "failed" && recoveredActionIds.has(action.action_id)
  )));
}
function aiTurnPresentation(turn, projection, conversation, actions) {
  const current = projection.current_turn?.group_key === turn.group_key;
  if (current) {
    const presentation = interactionPresentation(state.task, conversation, projection);
    return { ...presentation, current: true };
  }
  const failed = InteractionShell.turnHasActiveFailure(turn, actions, conversation.risks);
  const cancelled = (turn.items || []).some((item) => item.kind === "turn_cancelled");
  const blocked = (turn.items || []).some((item) => item.kind === "blocker");
  if (failed || blocked) return { label: "本轮需要处理", tone: "failed", current: false, can_cancel: false };
  if (cancelled) return { label: "本轮已停止", tone: "cancelled", current: false, can_cancel: false };
  return { label: "本轮已处理", tone: "completed", current: false, can_cancel: false };
}
function createAiTurnContainer(turn, projection, conversation, actions) {
  const presentation = aiTurnPresentation(turn, projection, conversation, actions);
  const { section, header, content } = InteractionShell.createAiTurnFrame(document, ui.messageList, {
    turnId: turn.turn_id || turn.group_key,
    state: presentation.tone,
    current: presentation.current,
  });
  const status = document.createElement("span"); status.className = "ai-turn-status"; const dot = document.createElement("i"); dot.setAttribute("aria-hidden", "true"); const label = document.createElement("b"); label.dataset.aiTurnStatusLabel = "true"; label.dataset.baseLabel = presentation.label; label.textContent = presentation.label;
  const turnTimes = (turn.items || []).flatMap((item) => [item.time, item.timestamp_utc, item.started_at_utc, item.updated_at_utc]).map(timestampMs).filter(Number.isFinite).sort((left, right) => left - right);
  if (turnTimes.length) { label.dataset.startedAt = String(turnTimes[0]); label.dataset.endedAt = String(turnTimes.at(-1)); label.dataset.elapsedLive = String(presentation.current && ["running", "cancelling"].includes(presentation.tone)); }
  status.append(dot, label); header.append(status);
  if (InteractionShell.canShowTurnStop(presentation)) {
    const stop = document.createElement("button"); stop.type = "button"; stop.className = "ai-turn-stop"; stop.dataset.aiTurnCancel = "true"; stop.textContent = "停止"; stop.addEventListener("click", openCancelAgentDialog); header.append(stop);
  }
  syncAiTurnElapsedLabels(section);
  return { section, content, presentation };
}
function appendAiTurnPlaceholder(target, presentation) {
  if (target.childElementCount) return;
  const placeholder = document.createElement("p"); placeholder.className = "ai-turn-placeholder";
  placeholder.textContent = presentation.phase === "executing" ? "正在理解任务并准备下一步…" : presentation.phase === "clarifying" ? "我需要你确认一项信息后再继续。" : "这一回合还没有返回可展示的内容。";
  target.append(placeholder);
}
function renderConversationTurn(turn, projection, conversation, workItems) {
  const actions = actionsForTurn(turn, projection); let actionsRendered = false; let aiTurn = null;
  const resolvedCheckpoints = [];
  const items = turn.render_items || turn.items || [];
  const latestPlanIndex = items.reduce((latest, item, index) => item.kind === "coordinator_plan" ? index : latest, -1);
  const finalNarrativeIndex = items.reduce((latest, item, index) => item.kind === "final_synthesis" ? index : latest, -1);
  const latestNoteIndex = items.reduce((latest, item, index) => item.kind === "coordinator_note" ? index : latest, -1);
  const visibleNarrativeIndex = finalNarrativeIndex >= 0 ? finalNarrativeIndex : latestNoteIndex;
  const recoveredFailures = recoveredDataExperimentFailures(actions, conversation.risks); const failedAction = actions.find((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action));
  const verifiedRoles = new Set(workItems.map((item) => item.role?.role_id).filter(Boolean));
  const verifiedIds = new Set(workItems.flatMap((item) => [item.delegation_id, item.work_item_id]).filter(Boolean));
  const turnDelegationIds = new Set(actions.map((action) => action.delegation_id).filter(Boolean));
  const turnVerifiedRoles = new Set(workItems.filter((item) => turnDelegationIds.has(item.delegation_id)).map((item) => item.role?.role_id).filter(Boolean));
  const delegations = (conversation.delegations || []).filter((item) => verifiedIds.has(item.delegation_id));
  const ensureAiTurn = () => { if (!aiTurn) aiTurn = createAiTurnContainer(turn, projection, conversation, actions); return aiTurn.content; };
  const turnTarget = (role) => InteractionShell.conversationTurnTarget({ role, root: ui.messageList, aiContent: role === "user" ? null : ensureAiTurn() });
  const renderActions = () => { if (!actionsRendered && actions.length) { renderActionTimeline(actions, delegations, { interactionState: projection.phase === "executing" ? "working" : ["clarifying", "awaiting_approval"].includes(projection.phase) ? "waiting_for_human" : "idle", expertCount: turnVerifiedRoles.size, recoveredFailures, target: turnTarget("assistant") }); actionsRendered = true; } };
  items.forEach((item, itemIndex) => {
    if (item.kind === "message" && item.role === "user") { renderConversationItem(item, turnTarget("user")); return; }
    if ((item.kind === "approval" || item.kind === "question") && !isPendingHumanCheckpoint(item)) { resolvedCheckpoints.push(item); return; }
    if (item.kind === "coordinator_plan" && itemIndex !== latestPlanIndex) return;
    if (["coordinator_note", "final_synthesis"].includes(item.kind) && itemIndex !== visibleNarrativeIndex) return;
    if (item.kind === "team_activity") {
      const events = (item.events || []).filter((event) => {
        if (!["delegation", "specialist_status", "specialist_output"].includes(event.kind)) return false;
        const role = event.to_role || event.specialist_role || event.actor_role;
        return verifiedRoles.has(role) || verifiedIds.has(event.delegation_id);
      });
      const reconciledEvents = InteractionShell?.reconcileTeamActivityEvents
        ? InteractionShell.reconcileTeamActivityEvents(events, projection.specialists)
        : events;
      if (!actions.length && reconciledEvents.length) renderTeamActivity({ ...item, events: reconciledEvents }, ensureAiTurn());
      return;
    }
    if (item.kind === "approval" || item.kind === "question") { renderActions(); renderHumanCheckpoint(item, { interactive: projection.observation?.degraded !== true && projection.background?.cancelling !== true && state.cancelRequestInFlight !== true, target: ensureAiTurn() }); return; }
    if (["final_synthesis", "turn_error", "turn_cancelled", "failed", "blocker"].includes(item.kind)) renderActions();
    const planText = `${item.title || ""} ${item.summary || item.text || ""}`;
    const truthConflict = item.kind === "coordinator_plan" && Boolean(failedAction) && /(?:正在后台运行|已经.{0,8}(?:启动|运行|完成)|训练中|已进入训练)/u.test(planText);
    renderConversationItem(item.kind === "coordinator_plan" ? { ...item, compact: true, truthConflict, failedActionTitle: failedAction ? actionTitle(failedAction) : null } : item, ensureAiTurn());
  });
  renderActions();
  if (resolvedCheckpoints.length) renderCheckpointHistory(resolvedCheckpoints, turnTarget("assistant"));
  const current = projection.current_turn?.group_key === turn.group_key;
  if (!aiTurn && current && ["executing", "clarifying", "awaiting_approval"].includes(projection.phase)) ensureAiTurn();
  if (aiTurn) appendAiTurnPlaceholder(aiTurn.content, aiTurn.presentation);
}
function isWaitingForAnswerAction(action, waitingForHuman = false) {
  return waitingForHuman && action.status === "running" && action.tool_name === "ask_user_question";
}
function isUserDeclinedAction(action) {
  return action?.status === "failed" && action?.error?.code === "user_rejected";
}
function actionDisplayStatus(action, waitingForHuman = false) {
  if (isWaitingForAnswerAction(action, waitingForHuman)) return "waiting";
  if (isUserDeclinedAction(action)) return "declined";
  return action.status;
}
function actionStatusLabel(action, { waitingForHuman = false } = {}) {
  const displayStatus = actionDisplayStatus(action, waitingForHuman);
  if (displayStatus === "waiting") return "等待回答";
  if (displayStatus === "running") return "执行中";
  if (displayStatus === "completed") return action.object_refs?.length ? "已返回证据" : "工具已返回";
  if (displayStatus === "declined") return "未执行";
  if (displayStatus === "failed") return "执行失败";
  if (displayStatus === "identity_error") return "身份异常";
  return "状态未知";
}
function actionTitle(action) {
  if (action.tool_class === "delegation" && ConversationView?.ROLE_LABELS?.[action.tool_name]) return `委派给${ConversationView.ROLE_LABELS[action.tool_name]}`;
  return ConversationView?.TOOL_LABELS?.[action.tool_name] || (action.tool_name || "未知工具").replace(/^model_harness_/u, "").replaceAll("_", " ");
}
function formatActionDuration(action) {
  if (!Number.isFinite(action.duration_ms)) return action.status === "running" ? "仍在执行" : "未记录耗时";
  if (action.duration_ms < 1000) return `${Math.round(action.duration_ms)} ms`;
  return `${(action.duration_ms / 1000).toFixed(action.duration_ms < 10_000 ? 1 : 0)} s`;
}
function actionTimelineGlance(actions, waitingForHuman, working, recoveredFailures = new Set()) {
  const failed = actions.find((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action));
  if (failed) return `需要处理：${actionTitle(failed)}`;
  const running = actions.find((action) => action.status === "running" && action.tool_class !== "control");
  if (running) return `正在执行：${actionTitle(running)}`;
  if (waitingForHuman) return "本轮工具调用已暂停，正在等待你的回答";
  if (actions.some(isUserDeclinedAction)) return "你选择暂不执行，关键操作没有启动";
  const completed = actions.find((action) => action.status === "completed");
  if (working) return completed ? `AI 正在继续处理 · 最近完成：${actionTitle(completed)}` : "AI 正在规划下一步";
  return completed ? `最近完成：${actionTitle(completed)}` : "工具动作正在同步";
}
function parseActionResultValue(value) {
  if (Array.isArray(value)) {
    const textItem = value.find((item) => item && typeof item === "object" && typeof item.text === "string");
    return parseActionResultValue(textItem ? textItem.text : value[0]);
  }
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text) return "";
  if ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]"))) {
    try { return parseActionResultValue(JSON.parse(text)); } catch (_) { return text; }
  }
  return text;
}
function actionResultSummary(action, payload) {
  const event = payload?.event || payload || {}; const body = event.payload || {};
  if (body.is_error === true || event.status === "failed") {
    const error = body.error?.message || body.error || body.message || body.result_preview || "工具返回失败，但没有可读原因。";
    return { state: "failed", text: String(error).replace(/\s+/g, " ").slice(0, 220) };
  }
  const result = parseActionResultValue(body.result ?? body.result_preview ?? body.summary ?? body.message);
  if (action?.tool_name === "model_harness_download_artifact_bundle") {
    if (result?.status === "downloaded") {
      return { state: "completed", text: "下载完成：新文件已写入，并通过大小与 SHA-256 校验。" };
    }
    if (result?.status === "download_opened") {
      return { state: "loading", text: "传输已开始，尚未确认本地文件保存完成。" };
    }
  }
  const task = result?.task || (result?.task_id && result?.status ? result : null);
  if (task) {
    const status = STATUS_LABELS[task.status] || task.status || "状态未知"; const revision = task.current_spec_revision ? ` · 任务理解第 ${task.current_spec_revision} 版` : ""; const recipe = ({ "tabular-regression": "表格数值回归", "image-folder-classification": "图片分类", "digit-classification": "数字分类" })[task.recipe_id] || task.recipe_id; const recipeLabel = recipe ? ` · ${recipe}方案` : "";
    return { state: "completed", text: `当前：${status}${revision}${recipeLabel}` };
  }
  const answers = Array.isArray(result?.answers) ? result.answers.flatMap((answer) => [...(Array.isArray(answer.selected) ? answer.selected : []), ...(answer.custom ? [answer.custom] : [])]).filter(Boolean) : [];
  if (answers.length) return { state: "completed", text: `已记录你的选择：${answers.join("、")}` };
  const collections = [[result?.matches, "能力匹配"], [result?.recipes, "训练方案"], [result?.adapters, "数据适配器"], [result?.candidates, "候选模型"]];
  const collection = collections.find(([items]) => Array.isArray(items));
  if (collection) return { state: "completed", text: `${collection[1]}返回 ${collection[0].length} 项结果` };
  if (typeof result === "string" && result) return { state: "completed", text: result.replace(/\s+/g, " ").slice(0, 220) };
  return { state: "completed", text: "工具已返回脱敏结果，可继续查看完整内容。" };
}
function actionResultKey(action) {
  const ref = action.event_result_ref;
  return ref?.id && ref?.projector_revision ? `${ref.task_id || state.selectedTaskId}:${ref.projector_revision}:${ref.id}` : null;
}
function setActionResultSummary(node, summary) {
  if (!node?.isConnected || !summary) return; node.dataset.state = summary.state || "completed"; node.textContent = summary.text;
}
async function hydrateActionResultSummary(action, node) {
  const key = actionResultKey(action); const ref = action.event_result_ref;
  if (!key || !ref || action.status !== "completed") return;
  if (ref.task_id && ref.task_id !== state.selectedTaskId) { setActionResultSummary(node, { state: "failed", text: "结果引用不属于当前任务，已停止读取。" }); return; }
  if (state.actionResultCache.has(key)) { setActionResultSummary(node, state.actionResultCache.get(key)); return; }
  node.dataset.state = "loading"; node.textContent = "正在读取结果摘要…";
  if (!state.actionResultRequests.has(key)) {
    const taskId = ref.task_id || state.selectedTaskId; const endpoint = `/tasks/${encodeURIComponent(taskId)}/conversation/events/${encodeURIComponent(ref.id)}?projector_revision=${encodeURIComponent(ref.projector_revision)}`;
    state.actionResultRequests.set(key, request(endpoint).then((payload) => actionResultSummary(action, payload)).catch((error) => ({ state: "failed", text: `结果摘要读取失败：${error.message}` })).then((summary) => { state.actionResultCache.set(key, summary); state.actionResultRequests.delete(key); return summary; }));
  }
  setActionResultSummary(node, await state.actionResultRequests.get(key));
}
function hydrateActionTimelineResults(section, actions) {
  if (!section.open) return; const actionsById = new Map(actions.map((action) => [action.action_id, action]));
  section.querySelectorAll(".agent-action-result[data-action-id]").forEach((node) => { const action = actionsById.get(node.dataset.actionId); if (action) void hydrateActionResultSummary(action, node); });
}
function renderRecoveredActionRow(action, target) {
  const row = document.createElement("article"); row.className = "agent-action"; row.dataset.status = "completed"; row.dataset.toolClass = action.tool_class; row.dataset.actionId = action.action_id || "identity-error"; row.dataset.recoveredFailure = "true";
  const mark = document.createElement("i"); mark.setAttribute("aria-hidden", "true"); mark.textContent = "✓";
  const copy = document.createElement("div"); const meta = document.createElement("span"); meta.className = "agent-action-meta"; const role = document.createElement("b"); role.textContent = roleLabel(action.actor_role); const timing = document.createElement("small"); timing.textContent = "后续执行已恢复"; meta.append(role, timing); const title = document.createElement("h4"); title.textContent = actionTitle(action); copy.append(meta, title);
  const evidence = document.createElement("details"); evidence.className = "recovered-action-evidence"; evidence.dataset.originalStatus = action.status; evidence.dataset.actionId = action.action_id || "identity-error"; const summary = document.createElement("summary"); summary.textContent = "查看当时的技术问题"; const error = document.createElement("p"); error.className = "agent-action-error"; error.textContent = action.error?.message || action.error?.code || "当时的执行失败没有返回可读原因。"; evidence.append(summary, error); const refs = document.createElement("div"); refs.className = "agent-action-evidence"; appendObjectRefs(refs, action.object_refs || []); if (action.event_result_ref) { const button = document.createElement("button"); button.type = "button"; button.textContent = "技术详情"; button.addEventListener("click", () => openEventResultRef(action.event_result_ref)); refs.append(button); } if (refs.childElementCount) evidence.append(refs); copy.append(evidence);
  const status = document.createElement("em"); status.textContent = "已恢复"; row.append(mark, copy, status); target.append(row);
}
function renderActionRow(action, target, { waitingForHuman = false, recovered = false } = {}) {
  if (recovered) { renderRecoveredActionRow(action, target); return; }
  const waitingForAnswer = isWaitingForAnswerAction(action, waitingForHuman); const displayStatus = actionDisplayStatus(action, waitingForHuman);
  const row = document.createElement("article"); row.className = "agent-action"; row.dataset.status = displayStatus; row.dataset.toolClass = action.tool_class; row.dataset.actionId = action.action_id || "identity-error";
  const mark = document.createElement("i"); mark.setAttribute("aria-hidden", "true"); mark.textContent = displayStatus === "failed" || displayStatus === "identity_error" ? "!" : displayStatus === "declined" ? "—" : displayStatus === "waiting" ? "…" : displayStatus === "running" ? "→" : "✓";
  const copy = document.createElement("div"); const meta = document.createElement("span"); meta.className = "agent-action-meta"; const role = document.createElement("b"); role.textContent = roleLabel(action.actor_role); const timing = document.createElement("small"); const startedAt = action.started_at || action.created_at || action.time; const heartbeatAt = action.last_heartbeat_at || action.updated_at || action.finished_at; const timingParts = [waitingForAnswer ? "等待回答" : formatActionDuration(action)]; if (startedAt) timingParts.push(`开始 ${formatTime(startedAt)}`); if (displayStatus === "running" && heartbeatAt) timingParts.push(`最近事件 ${formatRelativeTime(heartbeatAt)}`); if (action.tool_class === "control") timingParts.push("控制动作"); timing.textContent = timingParts.join(" · "); meta.append(role, timing);
  const title = document.createElement("h4"); title.textContent = actionTitle(action); copy.append(meta, title);
  if (displayStatus === "declined") { const note = document.createElement("p"); note.className = "agent-action-result"; note.dataset.state = "declined"; note.textContent = "你选择暂不执行，系统没有运行这项操作。"; copy.append(note); }
  else if (action.error) { const error = document.createElement("p"); error.className = "agent-action-error"; error.textContent = action.error.message || action.error.code || "工具失败但没有返回可读原因。"; copy.append(error); }
  else { const result = document.createElement("p"); result.className = "agent-action-result"; result.dataset.actionId = action.action_id || "identity-error"; result.dataset.state = displayStatus; result.textContent = waitingForAnswer ? "正在等待你的回答。" : action.status === "running" ? "正在执行，结果返回后会显示在这里。" : action.event_result_ref ? "已返回结果，展开后显示摘要。" : action.object_refs?.length ? `已产生 ${action.object_refs.length} 个可追溯对象。` : "工具已完成，没有返回额外对象。"; copy.append(result); }
  const evidence = document.createElement("div"); evidence.className = "agent-action-evidence"; appendObjectRefs(evidence, action.object_refs || []);
  if (action.event_result_ref) { const button = document.createElement("button"); button.type = "button"; button.textContent = "技术详情"; button.setAttribute("aria-label", `查看“${actionTitle(action)}”的完整脱敏技术详情`); button.addEventListener("click", () => openEventResultRef(action.event_result_ref)); evidence.append(button); }
  if (evidence.childElementCount) copy.append(evidence); const status = document.createElement("em"); status.textContent = actionStatusLabel(action, { waitingForHuman }); row.append(mark, copy, status); target.append(row);
}
function renderDelegationGroup(group, groups, target, visited, depth = 0, { waitingForHuman = false, recoveredFailures = new Set() } = {}) {
  if (visited.has(group.id)) return; visited.add(group.id);
  const details = document.createElement("details"); details.className = "delegation-group"; const hasDeclined = group.actions.some(isUserDeclinedAction); const hasFailure = group.actions.some((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action)); const waitingForAnswer = group.actions.some((action) => isWaitingForAnswerAction(action, waitingForHuman)); const running = group.actions.some((action) => action.status === "running" && !isWaitingForAnswerAction(action, waitingForHuman)); details.open = depth === 0 || running || waitingForAnswer || hasFailure; details.dataset.status = hasFailure ? "failed" : running ? "running" : waitingForAnswer ? "waiting" : hasDeclined ? "declined" : "completed";
  const summary = document.createElement("summary"); const copy = document.createElement("span"); const title = document.createElement("b"); const first = group.actions[0]; const delegationAction = group.actions.find((action) => action.tool_class === "delegation"); const delegatedRole = delegationAction?.tool_name && ConversationView?.ROLE_LABELS?.[delegationAction.tool_name] ? delegationAction.tool_name : null; const summaryRole = group.root ? "orchestrator" : group.binding?.target_agent_id || delegatedRole || first?.actor_role; title.textContent = group.unverified ? "未能验证归属的运行时观察" : group.root ? "训练协调器" : roleLabel(summaryRole); const counts = document.createElement("small"); const domainCount = group.actions.filter((action) => action.tool_class === "domain").length; const controlCount = group.actions.filter((action) => action.tool_class === "control").length; const objectCount = group.actions.reduce((total, action) => total + (action.object_refs?.length || 0), 0); counts.textContent = `${roleLabel(summaryRole)} · ${domainCount} 个领域动作 · ${controlCount} 个控制动作 · ${objectCount} 个对象`; copy.append(title, counts); const stateLabel = document.createElement("em"); stateLabel.textContent = hasFailure ? "需要处理" : running ? "执行中" : waitingForAnswer ? "等待回答" : hasDeclined ? "你选择暂不执行" : "已结束"; summary.append(copy, stateLabel); details.append(summary);
  const list = document.createElement("div"); list.className = "agent-action-list"; group.actions.forEach((action) => renderActionRow(action, list, { waitingForHuman, recovered: recoveredFailures.has(action) }));
  (group.children || []).map((id) => groups.get(id)).filter(Boolean).forEach((child) => renderDelegationGroup(child, groups, list, visited, depth + 1, { waitingForHuman, recoveredFailures })); details.append(list); target.append(details);
}
function renderActionTimeline(actions, delegations = [], { interactionState = "idle", expertCount = 0, recoveredFailures = new Set(), target = ui.messageList } = {}) {
  if (!actions.length) return; const section = document.createElement("details"); section.className = "action-timeline"; section.dataset.interactionKind = "action-group"; section.setAttribute("aria-label", "智能体真实执行过程");
  const waitingForHuman = interactionState === "waiting_for_human"; const declinedCount = actions.filter(isUserDeclinedAction).length; const failedCount = actions.filter((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action)).length; const waitingActionCount = actions.filter((action) => isWaitingForAnswerAction(action, waitingForHuman)).length; const runningCount = actions.filter((action) => action.status === "running" && !isWaitingForAnswerAction(action, waitingForHuman)).length; const working = interactionState === "working"; section.dataset.status = failedCount ? "failed" : runningCount || working ? "running" : waitingActionCount ? "waiting" : declinedCount ? "declined" : "completed"; section.dataset.recoveredFailures = String(recoveredFailures.size);
  const turnKey = actions.find((action) => action.turn_id)?.turn_id || actions[0]?.agent_run_id || "unscoped"; const disclosureKey = `${state.selectedTaskId || "task"}:${turnKey}`; const savedOpen = state.actionTimelineDisclosure.get(disclosureKey); section.open = savedOpen === undefined ? Boolean(failedCount) : savedOpen; section.dataset.defaultDisclosure = section.open ? "open" : "closed";
  const header = document.createElement("summary"); const copy = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "执行过程"; const title = document.createElement("h3"); title.textContent = waitingForHuman ? "本轮已经做了什么" : runningCount ? "AI 正在调用工具" : working ? "AI 正在处理" : failedCount ? "执行过程包含需要处理的问题" : declinedCount ? "你选择暂不执行" : "查看智能体执行过程"; const glance = document.createElement("p"); glance.className = "action-timeline-glance"; glance.textContent = actionTimelineGlance(actions, waitingForHuman, working, recoveredFailures); copy.append(kicker, title, glance); const count = document.createElement("b"); const countLabel = () => `${expertCount ? `${expertCount} 位专家 · ` : ""}${actions.length} 项 · ${section.open ? "收起" : "展开"}`; count.textContent = countLabel(); header.append(copy, count); section.append(header);
  section.addEventListener("toggle", () => { state.actionTimelineDisclosure.set(disclosureKey, section.open); count.textContent = countLabel(); hydrateActionTimelineResults(section, actions); });
  const body = document.createElement("div"); body.className = "action-timeline-body";
  const delegationById = new Map((delegations || []).filter((item) => item?.delegation_id).map((item) => [item.delegation_id, item])); const groups = new Map(); const roots = []; const rootAgent = { id: "root-agent", parentId: null, actions: [], children: [], root: true, unverified: false }; const unverified = { id: "unverified", parentId: null, actions: [], children: [], unverified: true };
  actions.forEach((action) => {
    if (!action.delegation_id) { (action.actor_role === "orchestrator" ? rootAgent : unverified).actions.push(action); return; }
    if (!delegationById.has(action.delegation_id)) { unverified.actions.push(action); return; }
    if (!groups.has(action.delegation_id)) groups.set(action.delegation_id, { id: action.delegation_id, parentId: action.parent_delegation_id || null, actions: [], children: [], binding: delegationById.get(action.delegation_id), unverified: false });
    groups.get(action.delegation_id).actions.push(action);
  });
  groups.forEach((group) => { if (group.parentId && groups.has(group.parentId)) groups.get(group.parentId).children.push(group.id); else roots.push(group); });
  const visited = new Set(); const rootOnly = rootAgent.actions.length && !roots.length && !unverified.actions.length;
  if (rootOnly) { const list = document.createElement("div"); list.className = "agent-action-list action-timeline-flat"; rootAgent.actions.forEach((action) => renderActionRow(action, list, { waitingForHuman, recovered: recoveredFailures.has(action) })); body.append(list); }
  else { if (rootAgent.actions.length) renderDelegationGroup(rootAgent, groups, body, visited, 0, { waitingForHuman, recoveredFailures }); roots.forEach((group) => renderDelegationGroup(group, groups, body, visited, 0, { waitingForHuman, recoveredFailures })); if (unverified.actions.length) renderDelegationGroup(unverified, groups, body, visited, 0, { waitingForHuman, recoveredFailures }); }
  section.append(body); target.append(section); hydrateActionTimelineResults(section, actions);
}
function renderCheckpointHistory(items, target = ui.messageList) {
  if (!items.length) return;
  const details = document.createElement("details"); details.className = "checkpoint-history";
  const summary = document.createElement("summary"); const label = document.createElement("span"); const title = document.createElement("b"); title.textContent = "已处理的人工确认"; const hint = document.createElement("small"); hint.textContent = "仅供回看，不是当前待办"; label.append(title, hint); const count = document.createElement("em"); count.textContent = `${items.length} 项`; summary.append(label, count); details.append(summary);
  const list = document.createElement("div"); list.className = "checkpoint-history-list";
  items.slice(-8).forEach((item) => { const row = document.createElement("div"); const name = document.createElement("b"); name.textContent = item.kind === "approval" ? item.title || "关键操作批准" : item.title || item.questions?.[0]?.header || "补充信息"; const status = document.createElement("span"); status.textContent = eventStatusLabel(item.status); row.append(name, status); list.append(row); });
  details.append(list); target.append(details);
}
function renderConversationItem(item, target = ui.messageList) {
  if (item.kind === "message" && item.role === "user") return renderMessage(item, target);
  if (item.kind === "final_synthesis") return renderFinalSynthesis(item, target);
  if (item.kind === "coordinator_note") return renderCoordinatorNote(item, target);
  if (item.kind === "coordinator_plan") return renderCoordinatorPlan(item, target);
  if (item.kind === "team_activity") return renderTeamActivity(item, target);
  if (item.kind === "approval" || item.kind === "question") return renderHumanCheckpoint(item, { target });
  if (item.kind === "turn_error" || item.kind === "turn_cancelled") return renderTurnTerminal(item, target);
  if (["blocker", "warning", "observation_degraded", "failed"].includes(item.kind)) return renderTypedTruthNotice(item, target);
  if (item.kind === "evidence_ledger") return renderEvidenceLedger(item, target);
  if (item.kind === "system_record") return renderSystemRecord(item, target);
  return renderUnknownEvent(item, target);
}
function renderTypedTruthNotice(item, target = ui.messageList) {
  const card = document.createElement("article"); card.className = "truth-notice"; card.dataset.kind = item.kind; card.dataset.interactionKind = "risk-recovery";
  const mark = document.createElement("span"); mark.setAttribute("aria-hidden", "true"); mark.textContent = item.kind === "warning" || item.kind === "observation_degraded" ? "!" : "×";
  const body = document.createElement("div"); const kicker = document.createElement("small"); const title = document.createElement("b"); const copy = document.createElement("p");
  const labels = {
    blocker: ["能力或条件阻断", "当前还不能继续"],
    warning: ["需要留意", "执行存在一项提醒"],
    observation_degraded: ["观察链路异常", "部分实时过程暂时不可见"],
    failed: ["执行异常", "本轮出现失败事件"],
  };
  const [label, fallbackTitle] = labels[item.kind] || labels.failed; kicker.textContent = label; title.textContent = item.title || fallbackTitle; copy.textContent = item.summary || item.text || item.reason || item.error?.message || "系统没有提供更具体的说明。";
  body.append(kicker, title, copy); appendObjectRefs(body, item.object_refs); appendRecoveryActions(body, item); card.append(mark, body); target.append(card);
}
function appendRecoveryActions(container, item = {}) {
  const actions = document.createElement("div"); actions.className = "recovery-actions";
  const refresh = document.createElement("button"); refresh.type = "button"; refresh.textContent = item.kind === "observation_degraded" ? "重新检查连接" : "重新检查当前状态";
  refresh.addEventListener("click", async () => { setButtonBusy(refresh, true, "检查中"); try { if (item.kind === "observation_degraded") await loadRuntime(); if (state.selectedTaskId) await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(refresh, false, ""); } });
  const adjust = document.createElement("button"); adjust.type = "button"; adjust.className = "secondary"; adjust.textContent = "告诉协调器如何调整"; adjust.addEventListener("click", () => { ui.messageInput.focus(); showNotice("请直接说明你希望修改的目标、数据或执行方式；不会自动重试刚才的失败动作。", "ok"); });
  const evidence = document.createElement("button"); evidence.type = "button"; evidence.className = "secondary"; evidence.textContent = "打开任务证据"; evidence.addEventListener("click", () => openInspector("plan"));
  actions.append(refresh, adjust, evidence); container.append(actions);
}
function renderMessage(item, target = ui.messageList) {
  if (item.role !== "user") return renderUnknownEvent({ ...item, contract_error: "only user messages enter renderMessage" }, target);
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "user"; row.dataset.interactionKind = "natural-dialogue"; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "你";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "你"; const time = document.createElement("time"); time.textContent = item.optimistic ? "正在提交" : formatTime(item.time); meta.append(author, time);
  const copy = document.createElement("p"); copy.className = "message-copy"; copy.textContent = item.text; body.append(meta, copy); row.append(avatar, body); target.append(row);
}
function appendInlineMarkdown(container, text) {
  let value = String(text || ""); const strongMarkers = [...value.matchAll(/\*\*/g)];
  if (strongMarkers.length % 2 === 1) { const dangling = strongMarkers.at(-1).index; value = `${value.slice(0, dangling)}${value.slice(dangling + 2)}`; }
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)]+)/g; let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    if (match.index > cursor) container.append(document.createTextNode(value.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("**")) { const strong = document.createElement("strong"); strong.textContent = token.slice(2, -2); container.append(strong); }
    else if (token.startsWith("`")) { const code = document.createElement("code"); code.textContent = token.slice(1, -1); container.append(code); }
    else { const link = document.createElement("a"); link.href = token; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = token; container.append(link); }
    cursor = match.index + token.length;
  }
  if (cursor < value.length) container.append(document.createTextNode(value.slice(cursor)));
}
function markdownTableCells(line) { return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim()); }
function isMarkdownTableDivider(line) { return markdownTableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell)); }
function isMarkdownBlockStart(line, nextLine = "") { const value = line.trim(); return !value || /^#{1,4}\s+/.test(value) || /^[-*]\s+/.test(value) || /^\d+\.\s+/.test(value) || (value.startsWith("|") && nextLine.trim().startsWith("|") && isMarkdownTableDivider(nextLine)); }
function renderRichText(container, text) {
  container.classList.add("rich-message"); const lines = String(text || "").split(/\r?\n/); let index = 0;
  while (index < lines.length) {
    const line = lines[index]; const trimmed = line.trim(); if (!trimmed) { index += 1; continue; }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) { const level = Math.min(4, heading[1].length + 1); const node = document.createElement(`h${level}`); appendInlineMarkdown(node, heading[2]); container.append(node); index += 1; continue; }
    if (trimmed.startsWith("|") && index + 1 < lines.length && lines[index + 1].trim().startsWith("|") && isMarkdownTableDivider(lines[index + 1])) {
      const wrap = document.createElement("div"); wrap.className = "rich-table-wrap"; const table = document.createElement("table"); const head = document.createElement("thead"); const headRow = document.createElement("tr"); markdownTableCells(line).forEach((cell) => { const th = document.createElement("th"); appendInlineMarkdown(th, cell); headRow.append(th); }); head.append(headRow); table.append(head); index += 2; const body = document.createElement("tbody");
      while (index < lines.length && lines[index].trim().startsWith("|")) { const row = document.createElement("tr"); markdownTableCells(lines[index]).forEach((cell) => { const td = document.createElement("td"); appendInlineMarkdown(td, cell); row.append(td); }); body.append(row); index += 1; }
      table.append(body); wrap.append(table); container.append(wrap); continue;
    }
    const unordered = /^[-*]\s+/.test(trimmed); const ordered = /^\d+\.\s+/.test(trimmed);
    if (unordered || ordered) { const list = document.createElement(ordered ? "ol" : "ul"); const matcher = ordered ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/;
      while (index < lines.length) { const itemMatch = lines[index].trim().match(matcher); if (!itemMatch) break; const item = document.createElement("li"); appendInlineMarkdown(item, itemMatch[1]); list.append(item); index += 1; }
      container.append(list); continue;
    }
    const paragraphLines = [trimmed]; index += 1;
    while (index < lines.length && !isMarkdownBlockStart(lines[index], lines[index + 1] || "")) { paragraphLines.push(lines[index].trim()); index += 1; }
    const paragraph = document.createElement("p"); appendInlineMarkdown(paragraph, paragraphLines.join(" ")); container.append(paragraph);
  }
}
function renderFinalSynthesis(item, target = ui.messageList) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "assistant"; row.dataset.messageType = "final_synthesis"; row.dataset.interactionKind = "natural-dialogue"; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "AI";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "训练协调器"; const time = document.createElement("time"); time.textContent = formatTime(item.time); meta.append(author, time);
  const copy = document.createElement("div"); copy.className = "message-copy"; renderRichText(copy, item.text || item.summary || "训练协调器没有返回综合结论。"); body.append(meta, copy); appendObjectRefs(body, item.object_refs); row.append(avatar, body); target.append(row);
}
function humanizeCoordinatorText(value) {
  return String(value || "")
    .replace(/\bTrainingTask\b/gu, "任务记录")
    .replace(/\bTaskSpec\b/gu, "任务理解")
    .replace(/\bRecipeSpec\b/gu, "训练方案声明")
    .replace(/\bRecipe\b/gu, "训练方案")
    .replace(/\bData Adapter\b/giu, "数据导入能力")
    .replace(/数据适配器/gu, "数据导入能力")
    .replace(/后端/gu, "系统");
}
function conversationPreview(value, limit = 460) {
  const paragraphs = String(value || "").split(/\r?\n\s*\r?\n/u).map((paragraph) => paragraph.trim()).filter((paragraph) => paragraph && !/^(?:证据视图|https?:\/\/)/u.test(paragraph));
  const prose = paragraphs.filter((paragraph) => !/^(?:[-*]|\d+\.)\s+/u.test(paragraph));
  const selected = (prose.length ? prose : paragraphs).slice(0, 3).join("\n\n").replace(/[*`]/g, "").trim();
  const text = humanizeCoordinatorText(selected || String(value || ""));
  return text.length > limit ? `${text.slice(0, limit).trim()}…` : text;
}
function latestCoordinatorNoteEventId() {
  return [...(state.conversation?.items || [])].reverse().find((event) => event?.type === "coordinator_note" || event?.event_type === "coordinator_note")?.event_id || null;
}
function appendCoordinatorNextAction(body, item) {
  if (item?.event_id !== latestCoordinatorNoteEventId() || currentHumanCheckpoint(state.conversation) || state.task?.status !== "awaiting_data") return;
  const row = document.createElement("div"); row.className = "message-next-action";
  const button = document.createElement("button"); button.type = "button"; button.className = "checkpoint-upload-button"; button.textContent = state.task?.recipe_id === "tabular-regression" ? "选择 CSV 文件" : "选择数据文件";
  button.addEventListener("click", () => { ui.datasetInput.value = ""; ui.datasetInput.click(); });
  const hint = document.createElement("small"); hint.textContent = "文件会先在本机导入并体检；页面不会要求你填写电脑路径。";
  row.append(button, hint); body.append(row);
}
function renderCoordinatorNote(item, target = ui.messageList) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "assistant"; row.dataset.messageType = "coordinator_note"; row.dataset.interactionKind = "natural-dialogue";
  const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "AI";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "训练协调器"; const truth = document.createElement("span"); truth.className = "message-truth"; truth.textContent = "协调器说明"; truth.title = "这是过程说明，最终结果以任务证据为准"; const time = document.createElement("time"); time.textContent = formatTime(item.time); meta.append(author, truth, time);
  const content = item.text || item.summary || "训练协调器没有提供说明。"; body.append(meta);
  if (content.length > 700 || content.split(/\r?\n/u).length > 10) {
    const preview = document.createElement("div"); preview.className = "message-copy message-preview"; renderRichText(preview, conversationPreview(content)); body.append(preview);
    const details = document.createElement("details"); details.className = "message-detail"; const summary = document.createElement("summary"); summary.textContent = "查看完整技术说明"; const copy = document.createElement("div"); copy.className = "message-copy"; renderRichText(copy, content); details.append(summary, copy); body.append(details);
  } else { const copy = document.createElement("div"); copy.className = "message-copy"; renderRichText(copy, humanizeCoordinatorText(content)); body.append(copy); }
  appendCoordinatorNextAction(body, item);
  row.append(avatar, body); target.append(row);
}
function roleLabel(value) { return ConversationView?.ROLE_LABELS?.[value] || value || "训练团队"; }
const RECOMMENDATION_SUFFIX = /\s*(?:\((?:recommended|推荐)\)|（(?:recommended|推荐)）)\s*$/iu;
function optionPresentation(value) {
  const raw = String(value || "");
  return {
    label: raw.replace(RECOMMENDATION_SUFFIX, "").trim(),
    recommended: RECOMMENDATION_SUFFIX.test(raw),
  };
}
function eventStatusLabel(value) { return ({ queued: "排队中", running: "执行中", waiting: "等待中", pending: "待处理", completed: "已完成", failed: "失败", cancelled: "已取消", rejected: "已拒绝", allowed: "已批准", resolved: "已处理", invalidated: "已失效" })[value] || value || "状态未知"; }
function approvalPresentation(item) {
  const raw = `${item?.title || ""} ${item?.reason || ""} ${item?.summary || ""} ${item?.tool_name || item?.name || ""}`.toLowerCase();
  if (/(?:start_task_run|start.*run|build_training|启动.*训练|开始.*训练)/u.test(raw)) return { title: "批准方案并启动本次训练", copy: "批准后，训练协调器只会按当前已冻结的数据与训练合同启动一次真实 Run。", allow: "批准并启动训练", reject: "暂不启动" };
  if (/(?:confirm_contract|configure_contract|训练合同|contract)/u.test(raw)) return { title: "确认并锁定这版训练合同", copy: "请核对目标、数据、评测门槛和资源限制；批准只对当前版本有效。", allow: "确认并锁定", reject: "返回修改" };
  if (/(?:authorize_sample_inference|sample[ _-]*inference|新样本.*试跑|样本.*试跑)/u.test(raw)) return { title: "批准这次新样本试跑", copy: "批准后只会对当前任务、当前训练结果和这份已上传的新样本执行一次推理；不会重新训练或修改模型。", allow: "批准本次试跑", reject: "暂不试跑" };
  if (/(?:download_artifact_bundle|download.*artifact bundle|下载.*交付包)/u.test(raw)) return { title: "确认下载这个交付包", copy: "批准只允许下载当前任务中这个已核验的 ZIP 一次，并写入你选择的新文件；不会复用构建授权，也不会覆盖已有文件。", allow: "确认并下载", reject: "暂不下载" };
  if (/(?:build_artifact_bundle|artifact bundle|构建.*交付包)/u.test(raw)) return { title: "构建可下载交付包", copy: "批准后会把本次运行中允许交付的模型、指标与预测结果打包；原始数据和内部路径不会进入交付包。", allow: "批准构建交付包", reject: "暂不打包" };
  if (/(?:dataset|data|数据)/u.test(raw)) return { title: "批准导入并体检这份数据", copy: "系统会按当前任务的数据合同读取文件，并留下可追溯的数据指纹。", allow: "批准并继续", reject: "暂不导入" };
  return { title: item?.title || "批准关键操作", copy: item?.reason || item?.summary || "协调器请求执行会改变任务状态的操作。", allow: "批准并继续", reject: "暂不执行" };
}
function appendApprovalScope(card, item) {
  const fields = [
    ["方案版本", item.plan_revision || item.recipe_revision || item.contract_revision],
    ["数据指纹", item.dataset_fingerprint || item.data_fingerprint],
    ["批准摘要", item.approval_digest || item.contract_digest || item.digest],
    ["作用范围", item.approval_scope || item.scope],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!fields.length) return;
  const list = document.createElement("dl"); list.className = "approval-scope";
  fields.forEach(([label, value]) => { const row = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const detail = document.createElement("dd"); detail.textContent = shortId(String(value)); row.append(term, detail); list.append(row); });
  card.append(list);
}
function agentActivityLabel(active) {
  if (active?.kind === "question") return `等待你的回答：${active.title || active.questions?.[0]?.header || "补充训练信息"}`;
  if (active?.kind === "approval") return `等待你的批准：${active.title || "关键操作"}`;
  if (active?.kind === "action") return `${roleLabel(active.actor_role)}正在执行：${active.tool_name || "领域工具"}`;
  return active ? `${roleLabel(active.actor_role)}正在处理：${active.title || active.summary || "当前任务"}` : "当前没有可验证的运行中动作";
}
function renderCoordinatorPlan(item, target = ui.messageList) {
  if (item.compact) { renderCoordinatorProgress(item, target); return; }
  const card = document.createElement("article"); card.className = "coordinator-plan"; card.dataset.status = item.status;
  const header = document.createElement("header"); const heading = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "训练协调器计划"; const title = document.createElement("h3"); title.textContent = item.title || "本轮执行计划"; heading.append(kicker, title); const status = document.createElement("b"); status.textContent = eventStatusLabel(item.status); header.append(heading, status); card.append(header);
  if (item.summary) { const summary = document.createElement("div"); summary.className = "coordinator-plan-summary"; renderRichText(summary, item.summary); card.append(summary); }
  const steps = Array.isArray(item.steps) ? item.steps : Array.isArray(item.plan?.steps) ? item.plan.steps : [];
  if (steps.length) { const list = document.createElement("ol"); list.className = "coordinator-plan-steps"; steps.forEach((step) => { const row = document.createElement("li"); row.dataset.status = step.status || "queued"; const mark = document.createElement("i"); mark.textContent = step.status === "completed" ? "✓" : step.status === "failed" ? "!" : String(step.order || step.index || list.children.length + 1); const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = step.title || step.goal || "计划步骤"; const owner = document.createElement("small"); owner.textContent = roleLabel(step.owner_role || step.role); copy.append(name, owner); row.append(mark, copy); list.append(row); }); card.append(list); }
  appendObjectRefs(card, item.object_refs); target.append(card);
}
function renderCoordinatorProgress(item, target = ui.messageList) {
  const details = document.createElement("details"); details.className = "coordinator-progress"; details.dataset.status = item.status; details.dataset.interactionKind = "lightweight-plan"; details.dataset.truthConflict = String(Boolean(item.truthConflict));
  const summary = document.createElement("summary"); const copy = document.createElement("span"); const label = document.createElement("b"); label.textContent = item.truthConflict ? "状态说明已降级" : "当前计划"; const hint = document.createElement("small"); hint.textContent = item.truthConflict ? `与“${item.failedActionTitle || "失败工具"}”的真实证据冲突` : item.title || "正在梳理下一步"; copy.append(label, hint); const stateLabel = document.createElement("em"); stateLabel.textContent = item.truthConflict ? "不作为状态" : "展开"; summary.append(copy, stateLabel); details.append(summary);
  const body = document.createElement("div"); body.className = "coordinator-progress-body"; if (item.truthConflict) { const warning = document.createElement("p"); warning.className = "coordinator-conflict-note"; warning.textContent = "下面是协调器当时的过程说明。系统已经检测到同轮工具失败，因此不会把其中的“已启动”或“正在运行”当作任务真相。"; body.append(warning); } const content = document.createElement("div"); renderRichText(content, item.summary || "协调器没有提供补充说明。"); body.append(content); appendObjectRefs(body, item.object_refs); details.append(body); target.append(details);
}
function teamEventTitle(item) {
  if (item.kind === "delegation") return item.title || `委派给 ${roleLabel(item.to_role || item.specialist_role || item.actor_role)}`;
  if (item.kind === "specialist_status") return item.title || `${roleLabel(item.actor_role)}状态更新`;
  if (item.kind === "specialist_output") return item.title || `${roleLabel(item.actor_role)}提交产出`;
  if (item.kind === "tool_call") return item.title || item.tool_name || item.name || "执行工具";
  return item.title || item.event_type || "团队事件";
}
function renderTeamActivity(item, target = ui.messageList) {
  const details = document.createElement("details"); details.className = "team-activity"; const events = item.events || [];
  const active = events.some((event) => ["active", "queued", "running", "waiting"].includes(event.status));
  const failedEvents = events.filter((event) => event.status === "failed");
  const failed = failedEvents.length > 0;
  details.open = active; details.dataset.status = failed ? "failed" : active ? "running" : "completed";
  const summary = document.createElement("summary"); const mark = document.createElement("span"); mark.textContent = failed ? "!" : active ? "↻" : "✓"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = "团队执行过程"; const roles = [...new Set(events.map((event) => roleLabel(event.to_role || event.specialist_role || event.actor_role)).filter(Boolean))]; const hint = document.createElement("small"); hint.textContent = roles.length ? roles.join(" · ") : "协调器尚未委派专家"; copy.append(title, hint); const stateLabel = document.createElement("em"); stateLabel.textContent = failed ? "需要处理 · 部分步骤失败" : active ? `执行中 · ${events.length} 项` : `已完成 · ${events.length} 项证据`; summary.append(mark, copy, stateLabel); details.append(summary);
  const list = document.createElement("div"); list.className = "team-event-list";
  events.forEach((event) => { const row = document.createElement("article"); row.className = "team-event"; row.dataset.status = event.status || "unknown"; row.dataset.eventType = event.kind; if (event.status_source) row.dataset.statusSource = event.status_source; const meta = document.createElement("div"); meta.className = "team-event-meta"; const role = document.createElement("span"); role.textContent = roleLabel(event.to_role || event.specialist_role || event.actor_role); const status = document.createElement("b"); status.textContent = event.status === "failed" ? "需要处理" : eventStatusLabel(event.status); meta.append(role, status); const title = document.createElement("h4"); title.textContent = teamEventTitle(event); const summaryText = document.createElement("p"); summaryText.textContent = event.result || event.summary || (event.kind === "tool_call" ? "工具调用已提交，等待真实结果。" : "运行时没有提供摘要。"); row.append(meta, title, summaryText); if (event.result_truncated) { row.dataset.resultPayload = "preview"; const notice = document.createElement("small"); notice.className = "team-event-result-preview"; notice.textContent = event.result_notice || "当前仅显示结果预览。"; row.append(notice); if (event.event_result_ref) { const view = document.createElement("button"); view.type = "button"; view.textContent = "查看完整脱敏结果"; view.addEventListener("click", () => openEventResultRef(event.event_result_ref)); row.append(view); } } appendObjectRefs(row, event.object_refs); list.append(row); });
  details.append(list); target.append(details);
}
function appendInferenceInputActions(actions, checkpoint) {
  actions.classList.add("data-upload-actions", "inference-input-actions");
  const result = state.task?.current_result; const sampleType = sampleTypeForRecipe(result?.recipe);
  const hint = document.createElement("small"); hint.textContent = "样本只会成为当前任务和 Run 的一次性输入对象；对话里不会出现本机路径，真正执行前仍需你批准。";
  if (sampleType === "tabular") {
    const input = document.createElement("textarea"); input.className = "question-custom inference-sample-json"; input.rows = 3; input.placeholder = '{"feature_a": 1.2, "feature_b": 3.4}'; input.setAttribute("aria-label", "输入一行新的表格样本 JSON");
    const submit = document.createElement("button"); submit.type = "button"; submit.className = "checkpoint-upload-button"; submit.textContent = "暂存这条新样本";
    submit.addEventListener("click", async () => {
      let body;
      try { const value = JSON.parse(input.value); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 必须是一行对象"); body = JSON.stringify(value); }
      catch (error) { showNotice(`请输入有效的一行 JSON：${error.message}`); input.focus(); return; }
      setButtonBusy(submit, true, "正在安全暂存");
      try { const staged = await stageInferenceInput({ body, filename: "new-sample.json", contentType: "application/json", sampleType }); await continueWithInferenceInput(staged, checkpoint); }
      catch (error) { showNotice(`新样本暂存失败：${error.message}`); }
      finally { setButtonBusy(submit, false, ""); }
    });
    actions.append(input, submit, hint); return;
  }
  const picker = document.createElement("input"); picker.type = "file"; picker.hidden = true; picker.accept = sampleType === "image" ? "image/png,image/jpeg,image/webp,image/bmp" : sampleType === "audio" ? ".wav,audio/wav" : "";
  const choose = document.createElement("button"); choose.type = "button"; choose.className = "checkpoint-upload-button"; choose.textContent = sampleType === "image" ? "选择一张新图片" : sampleType === "audio" ? "选择一段新 WAV" : "选择新样本";
  choose.addEventListener("click", () => { picker.value = ""; picker.click(); });
  picker.addEventListener("change", async () => {
    const file = picker.files?.[0]; if (!file || !sampleType) return;
    setButtonBusy(choose, true, "正在安全暂存");
    try { const staged = await stageInferenceInput({ body: file, filename: file.name, contentType: file.type || (sampleType === "audio" ? "audio/wav" : "application/octet-stream"), sampleType }); await continueWithInferenceInput(staged, checkpoint); }
    catch (error) { showNotice(`新样本暂存失败：${error.message}`); }
    finally { setButtonBusy(choose, false, ""); }
  });
  actions.append(picker, choose, hint);
}
function renderHumanCheckpoint(item, { interactive = true, target = ui.messageList } = {}) {
  const card = document.createElement("article"); card.className = "decision-card human-checkpoint"; card.dataset.status = item.status; card.dataset.interactionKind = "human-checkpoint"; const pending = item.status === "pending" || item.status === "waiting" || !item.status; const canRespond = pending && interactive; card.dataset.interactive = String(canRespond); const uploadCheckpoint = canRespond ? dataUploadQuestionCheckpoint(item) : null; const inferenceCheckpoint = canRespond ? inferenceInputQuestionCheckpoint(item) : null; const approval = item.kind === "approval" ? approvalPresentation(item) : null;
  if (uploadCheckpoint) card.classList.add("data-upload-checkpoint");
  if (inferenceCheckpoint) card.classList.add("inference-input-checkpoint");
  const cancelling = state.cancelRequestInFlight === true || backgroundCancellationPending(state.conversation);
  const kicker = document.createElement("span"); kicker.textContent = cancelling && pending ? "正在停止 · 暂不可操作" : !interactive && pending ? "连接恢复后再处理" : uploadCheckpoint ? "下一步：准备数据" : inferenceCheckpoint ? "下一步：验证新样本" : pending ? item.kind === "approval" ? "需要你的批准" : "需要你的回答" : "人工检查点已处理";
  const title = document.createElement("h3"); title.textContent = uploadCheckpoint ? "选择数据文件，系统会先识别字段" : inferenceCheckpoint ? "选择一份没参与训练的新样本" : item.kind === "approval" ? approval.title : item.title || item.questions?.[0]?.header || "补充训练信息";
  const copy = document.createElement("p"); copy.textContent = cancelling && pending ? "停止请求已经提交。为避免旧确认继续改变任务，本卡会在后端确认最终状态前保持只读。" : !interactive && pending ? "当前观察链路不完整，这个待办可能已经变化。请先重新连接并刷新，恢复后再作答。" : uploadCheckpoint ? "选择 CSV 后，我会先读取真实表头并推荐预测列；你确认后再导入和体检，不需要手填电脑路径。" : inferenceCheckpoint ? "先提供一份全新的样本。系统只做安全暂存；协调器核对范围并征得你批准后，才会交给评测专家执行。" : item.kind === "approval" ? approval.copy : item.summary || item.questions?.[0]?.question || "请回答协调器提出的问题。"; card.append(kicker, title, copy);
  if (item.kind === "approval") appendApprovalScope(card, item);
  if (canRespond && item.rpc_id) {
    const actions = document.createElement("div"); actions.className = "decision-actions";
    if (item.kind === "approval") { const allow = document.createElement("button"); allow.type = "button"; allow.textContent = approval.allow; const reject = document.createElement("button"); reject.type = "button"; reject.textContent = approval.reject; allow.addEventListener("click", () => answerApproval(item, "allowed-once", allow)); reject.addEventListener("click", () => answerApproval(item, "rejected", reject)); actions.append(allow, reject); }
    else if (uploadCheckpoint) {
      actions.classList.add("data-upload-actions"); const choose = document.createElement("button"); choose.type = "button"; choose.className = "checkpoint-upload-button"; choose.textContent = "选择 CSV 文件"; choose.addEventListener("click", () => { ui.datasetInput.value = ""; ui.datasetInput.click(); }); const hint = document.createElement("small"); hint.textContent = "页面不会展示本机路径；协调器只会收到导入后的数据集编号和你选择的预测列。"; actions.append(choose, hint);
    } else if (inferenceCheckpoint) appendInferenceInputActions(actions, inferenceCheckpoint);
    else {
      const question = item.questions?.length === 1 ? item.questions[0] : null; const options = question?.options || []; const inline = question && !question.multiSelect && options.length >= 2 && options.length <= 4;
      if (inline) {
        actions.classList.add("human-choice-list");
        options.forEach((option) => { const presentation = optionPresentation(option.label); const button = document.createElement("button"); button.type = "button"; button.className = "human-choice"; button.dataset.recommended = String(presentation.recommended); const label = document.createElement("b"); label.textContent = presentation.label; const detail = document.createElement("small"); detail.textContent = option.description || "选择后，协调器会按这条路径继续。"; button.append(label, detail); button.addEventListener("click", async () => { const buttons = [...actions.querySelectorAll("button")]; buttons.forEach((candidate) => { candidate.disabled = true; }); button.setAttribute("aria-busy", "true"); try { await postQuestionAnswers(item, [{ id: question.id, selected: [option.label] }]); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); buttons.forEach((candidate) => { candidate.disabled = false; }); } finally { button.removeAttribute("aria-busy"); } }); actions.append(button); });
        const custom = document.createElement("button"); custom.type = "button"; custom.className = "human-choice-custom"; custom.textContent = "都不符合，我想补充说明"; custom.addEventListener("click", () => { ui.messageInput.focus(); showNotice("请直接在下方输入你的想法；这条消息会回答当前问题，不会启动另一条流程。", "ok"); }); actions.append(custom);
      } else { const answer = document.createElement("button"); answer.type = "button"; answer.textContent = "填写回答"; answer.addEventListener("click", () => openQuestionDialog(item)); actions.append(answer); }
    }
    card.append(actions);
  }
  appendObjectRefs(card, item.object_refs); target.append(card);
}
function renderTurnTerminal(item, target = ui.messageList) {
  const reasonCode = item.reason_code || item.cancellation_reason || item.error?.code || "";
  const cancelledTitles = { user_cancelled: "你已停止本轮智能体", safety_stop: "安全检查停止了本轮执行", tool_rejected: "关键操作未获批准，本轮已停止", timeout: "等待超时，本轮已停止", stopped_with_checkpoint: "本轮已停在人工确认点" };
  const card = document.createElement("article"); card.className = "turn-terminal"; card.dataset.status = item.kind === "turn_cancelled" ? reasonCode || "stopped" : "failed"; const title = document.createElement("b"); title.textContent = item.kind === "turn_cancelled" ? cancelledTitles[reasonCode] || "本轮智能体已停止" : "本轮智能体执行失败"; const copy = document.createElement("p"); copy.textContent = item.summary || item.reason || item.error?.message || "运行时没有提供失败原因。"; card.append(title, copy); appendObjectRefs(card, item.object_refs); appendRecoveryActions(card, item); target.append(card);
}
function renderEvidenceLedger(item, target = ui.messageList) {
  const details = document.createElement("details"); details.className = "evidence-ledger"; const summary = document.createElement("summary"); const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = "任务证据记录"; const hint = document.createElement("small"); hint.textContent = "由持久化任务状态生成，不代表智能体发言"; copy.append(title, hint); const count = document.createElement("em"); count.textContent = `${item.items?.length || 0} 条`; summary.append(copy, count); details.append(summary); const list = document.createElement("div"); list.className = "evidence-ledger-list"; (item.items || []).forEach((record) => renderSystemRecord(record, list)); details.append(list); target.append(details);
}
function renderSystemRecord(item, target = ui.messageList) {
  const row = document.createElement("article"); row.className = "system-record"; row.dataset.status = item.status || "recorded"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = item.label || item.title || "系统记录"; const detail = document.createElement("small"); detail.textContent = item.detail || item.summary || ""; copy.append(title, detail); const time = document.createElement("time"); time.textContent = formatTime(item.time); row.append(copy, time); target.append(row);
}
function renderUnknownEvent(item, target = ui.messageList) {
  const card = document.createElement("article"); card.className = "unknown-event"; card.dataset.status = "unknown"; const title = document.createElement("b"); title.textContent = "未知运行时事件"; const copy = document.createElement("p"); copy.textContent = `${item.event_type || item.kind || "unknown"}${item.contract_error ? ` · ${item.contract_error}` : ""}。该事件未被伪装成协调器消息。`; card.append(title, copy); target.append(card);
}
function normalizeObjectRefType(value) { return value === "source_search" ? "model_source_search" : String(value || ""); }
function resourceRefKind(ref) {
  return ["resource_probe", "environment_lock", "resource_fit_report"].includes(ref?.record_kind) ? ref.record_kind : null;
}
function objectRefEndpoint(ref) {
  const taskId = encodeURIComponent(state.selectedTaskId || ""); const id = encodeURIComponent(String(ref?.id || ref?.object_id || "")); const type = normalizeObjectRefType(ref?.type); const runId = encodeURIComponent(String(ref?.run_id || ""));
  if (!taskId || !id) return null;
  if (type === "model_source_search") return `/tasks/${taskId}/model-source-searches/${id}`;
  if (type === "model_source_resolution") return `/tasks/${taskId}/model-source-resolutions/${id}`;
  if (type === "model_binding") return `/tasks/${taskId}/model-bindings/${id}`;
  if (type === "model_binding_attempt") return `/tasks/${taskId}/model-binding-attempts/${id}`;
  if (type === "repository_analysis") return `/tasks/${taskId}/repository-analyses/${id}`;
  if (type === "training_plan") return `/tasks/${taskId}/training-plans/${id}`;
  if (type === "staged_asset") return `/tasks/${taskId}/staged-assets/${id}`;
  if (type === "recipe_build") return `/tasks/${taskId}/recipe-builds/${id}`;
  if (type === "blocker") return `/tasks/${taskId}/blockers/${id}`;
  if (type === "evaluation_report" && runId) return `/tasks/${taskId}/runs/${runId}/evaluation-report`;
  if (type === "artifact_bundle" && runId) return `/tasks/${taskId}/runs/${runId}/artifact-bundles/${id}`;
  if (type === "resource_feasibility") {
    const kind = resourceRefKind(ref); if (kind === "resource_probe") return `/tasks/${taskId}/resource-probes/${id}`; if (kind === "environment_lock") return `/tasks/${taskId}/environment-locks/${id}`; if (kind === "resource_fit_report") return `/tasks/${taskId}/resource-fit-reports/${id}`;
  }
  return null;
}
function setObjectViewerState(ref, { stateLabel, summary, payload = null }) {
  state.activeObjectPayload = payload; ui.objectViewerState.textContent = stateLabel; ui.objectViewerState.dataset.state = stateLabel === "读取成功" ? "completed" : stateLabel === "读取中" ? "running" : "failed"; ui.objectViewerTitle.textContent = ref.label || `${ref.type || "对象"} · ${shortId(ref.id)}`; ui.objectViewerSummary.textContent = summary; clear(ui.objectViewerIdentity);
  const identity = [["type", ref.type], ["id", ref.id], ["task_id", ref.task_id], ["run_id", ref.run_id], ["revision", ref.revision || ref.base_spec_revision], ["digest", ref.digest || ref.semantic_digest || ref.plan_sha256 || ref.report_sha256 || ref.manifest_sha256]];
  identity.filter(([, value]) => value !== undefined && value !== null && value !== "").forEach(([label, value]) => { const row = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const detail = document.createElement("dd"); detail.textContent = String(value); row.append(term, detail); ui.objectViewerIdentity.append(row); });
  ui.objectViewerJson.textContent = payload ? JSON.stringify(payload, null, 2) : "";
}
async function openObjectRef(ref) {
  const type = normalizeObjectRefType(ref?.type); const id = String(ref?.id || ref?.object_id || ""); const normalized = { ...ref, type, id };
  if (!state.selectedTaskId || !id) { showNotice("对象引用缺少当前任务或 canonical id，已拒绝打开。", "error"); return; }
  if (normalized.task_id !== state.selectedTaskId) { showNotice("这个对象不属于当前训练任务；没有切换任务，也没有展示错误对象。", "error"); return; }
  const endpoint = objectRefEndpoint(normalized); state.activeObjectRef = normalized; openInspector("object-viewer", { objectRef: normalized });
  if (!endpoint) { setObjectViewerState(normalized, { stateLabel: "暂不支持", summary: `当前版本没有 ${type || "未知类型"} 的精确读取端点；没有回退到通用方案或当前对象。` }); return; }
  const requestSeq = ++state.objectViewerRequestSeq; const taskId = state.selectedTaskId; setObjectViewerState(normalized, { stateLabel: "读取中", summary: "正在读取被点击的历史对象；不会触发新的外部调用。" });
  try { const payload = await request(endpoint); if (requestSeq !== state.objectViewerRequestSeq || taskId !== state.selectedTaskId) return; setObjectViewerState(normalized, { stateLabel: "读取成功", summary: "以下是服务端按 canonical identity 返回的 task-owned 只读对象。", payload }); }
  catch (error) { if (requestSeq !== state.objectViewerRequestSeq || taskId !== state.selectedTaskId) return; setObjectViewerState(normalized, { stateLabel: "读取失败", summary: `${error.status || "请求"}：${error.message}` }); }
}
async function openEventResultRef(ref) {
  const eventRef = { ...ref, type: "event_result", id: String(ref?.id || ""), task_id: ref?.task_id || state.selectedTaskId, label: "脱敏工具结果" };
  if (!state.selectedTaskId || eventRef.task_id !== state.selectedTaskId || !eventRef.id || !ref?.projector_revision) { showNotice("工具结果引用身份不完整，已拒绝打开。", "error"); return; }
  state.activeObjectRef = eventRef; openInspector("object-viewer", { objectRef: eventRef }); const requestSeq = ++state.objectViewerRequestSeq; const taskId = state.selectedTaskId; setObjectViewerState(eventRef, { stateLabel: "读取中", summary: "正在读取已持久化并脱敏的 conversation event；不会重新调用工具。" });
  const endpoint = `/tasks/${encodeURIComponent(taskId)}/conversation/events/${encodeURIComponent(eventRef.id)}?projector_revision=${encodeURIComponent(ref.projector_revision)}`;
  try { const payload = await request(endpoint); if (requestSeq !== state.objectViewerRequestSeq || taskId !== state.selectedTaskId) return; setObjectViewerState(eventRef, { stateLabel: "读取成功", summary: "这是运行时观察结果，不等同于领域对象或完成证据。", payload }); }
  catch (error) { if (requestSeq !== state.objectViewerRequestSeq || taskId !== state.selectedTaskId) return; setObjectViewerState(eventRef, { stateLabel: "读取失败", summary: `${error.status || "请求"}：${error.message}` }); }
}
function appendObjectRefs(container, refs = []) {
  if (!refs.length) return; const list = document.createElement("div"); list.className = "object-ref-list"; list.dataset.interactionKind = "artifact-entry";
  refs.forEach((ref) => { const label = ref.label || `${ref.type || "对象"} · ${shortId(ref.id || ref.object_id || ref.digest)}`; if (typeof ref.url === "string" && (/^https?:\/\//.test(ref.url) || ref.url.startsWith("/"))) { const link = document.createElement("a"); link.href = ref.url; link.textContent = label; list.append(link); } else { const button = document.createElement("button"); button.type = "button"; button.textContent = label; button.addEventListener("click", () => openObjectRef(ref)); list.append(button); } }); container.append(list);
}
async function submitMessage(message) {
  const text = message.trim(); if (!text) return; let attemptedTaskId = state.selectedTaskId; hideNotice(); ui.sendButton.disabled = true; ui.sendButton.dataset.busy = "true";
  try {
    if (!state.runtimeReady) { if (state.runtimeIssue === "provider") showRuntimeSetupNotice("模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。"); else showNotice("训练协调器未连接：没有创建或修改任务，也没有启动固定流程替代智能协作。请先恢复连接。", "error"); return; }
    if (state.cancelRequestInFlight || backgroundCancellationPending(state.conversation)) { showNotice("当前执行正在停止。为避免新消息与取消请求发生竞态，请等待后端确认最终状态。", "ok"); return; }
    if (!state.selectedTaskId) {
      const created = await request("/tasks", { method: "POST", json: { name: deriveTaskName(text), business_goal: text } }); state.tasks.unshift(created.task); clearDraft(null); ui.messageInput.value = ""; resizeComposer(); await selectTask(created.task.task_id, { saveCurrentDraft: false }); attemptedTaskId = created.task.task_id; ui.messageInput.value = text; saveDraft(attemptedTaskId); resizeComposer();
      if (state.runtimeReady) {
        const taskId = created.task.task_id;
        await postQueuedConversationMessage(taskId, text); clearDraft(taskId); if (state.selectedTaskId === taskId) { ui.messageInput.value = ""; resizeComposer(); }
        showTransientNotice("任务已创建。协调器会先理解你的目标，再决定下一步；需要你做决定时会停下来问你。", "ok"); window.setTimeout(() => refreshSelected({ force: true }), 250); return;
      }
      showTransientNotice(created.task.capability_decision?.status === "needs_clarification" ? "任务已创建，但输出形式仍有歧义。请先提交澄清；系统尚未绑定训练方案。" : "任务已创建。请先检查并确认任务理解；确认前不会进入数据或训练。", "ok"); return;
    }
    const checkpoint = currentHumanCheckpoint(state.conversation);
    if (checkpoint?.kind === "approval") { showNotice("这是一次会改变任务状态的批准请求。请使用上方明确的“允许”或“拒绝”按钮，聊天文字不会被当作授权。", "error"); return; }
    if (checkpoint?.kind === "question" && checkpoint.rpc_id) {
      if (dataUploadQuestionCheckpoint(checkpoint)) { ui.datasetInput.value = ""; ui.datasetInput.click(); showNotice("这个问题需要先选择 CSV 文件；上传后再指定预测列，我不会要求你填写本机路径。", "ok"); return; }
      if (inferenceInputQuestionCheckpoint(checkpoint)) { const field = ui.messageList.querySelector(".inference-input-checkpoint .inference-sample-json"); const choose = ui.messageList.querySelector(".inference-input-checkpoint .checkpoint-upload-button"); if (field) field.focus(); else choose?.click(); showNotice("这个问题需要一份未参与训练的新样本。样本会先安全暂存，真正试跑前仍会单独征求你的批准。", "ok"); return; }
      if (checkpoint.questions?.length !== 1) { openQuestionDialog(checkpoint); showNotice("这组问题需要分别回答，已为你打开结构化回答面板。", "ok"); return; }
      const question = checkpoint.questions[0]; if (!question?.id) { showNotice("当前问题缺少可验证身份，无法把文字回答写入该检查点。请刷新后重试。", "error"); return; }
      await postQuestionAnswers(checkpoint, [{ id: question.id, selected: [], custom: text }]); clearDraft(state.selectedTaskId); ui.messageInput.value = ""; resizeComposer(); showNotice("回答已提交给当前问题，协调器会从同一任务继续。", "ok"); await refreshSelected({ force: true }); return;
    }
    const taskId = state.selectedTaskId; attemptedTaskId = taskId; const queuedAfterTurn = conversationAgentResponseRunning(state.conversation);
    await postQueuedConversationMessage(taskId, text); clearDraft(taskId); if (state.selectedTaskId === taskId) { ui.messageInput.value = ""; resizeComposer(); }
    showTransientNotice(queuedAfterTurn ? "消息已排队，将在本轮结束后继续。" : "消息已提交给训练协调器。", "ok"); window.setTimeout(() => refreshSelected({ force: true }), 250);
  } catch (error) {
    if (state.pendingMessage?.task_id === state.selectedTaskId) state.pendingMessage = null;
    const failedSubmission = state.messageSubmission?.status === "failed" ? state.messageSubmission : null;
    if (failedSubmission?.task_id === state.selectedTaskId && !ui.messageInput.value.trim()) { ui.messageInput.value = failedSubmission.text; resizeComposer(); }
    saveDraft(attemptedTaskId); renderConversation(true);
    showNotice(failedSubmission ? `消息发送失败：${error.message}。再次发送同一条消息会复用请求编号，不会创建第二条排队请求。` : `${error.message}。任务事实不会被伪造。`);
  }
  finally { ui.sendButton.disabled = !state.runtimeReady || state.cancelRequestInFlight === true || backgroundCancellationPending(state.conversation); ui.sendButton.dataset.busy = "false"; }
}
function deriveTaskName(message) {
  const firstSentence = String(message || "").split(/[。！？!?]/u)[0] || "";
  const cleaned = firstSentence
    .replace(/^(我想|我要|请帮我|帮我)/u, "")
    .replace(/^在[^，,]{1,18}(?:上|中)/u, "")
    .replace(/^(用[^，,]{0,18})?(训练|做|构建)(一个|个)?\s*模型[，,\s]*/u, "")
    .replace(/^把/u, "")
    .replace(/[，,]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return (cleaned || "新的模型任务").slice(0, 24);
}
function openSimpleDialog({ kicker, title, body, allowLabel, onAllow }) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = kicker; ui.dialogTitle.textContent = title; const copy = document.createElement("p"); copy.textContent = body; ui.dialogBody.append(copy);
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => ui.decisionDialog.close());
  const allow = document.createElement("button"); allow.type = "button"; allow.className = "allow"; allow.textContent = allowLabel; allow.addEventListener("click", async () => { setButtonBusy(allow, true, "执行中"); try { await onAllow(); ui.decisionDialog.close(); } catch (error) { showNotice(error.message); } finally { setButtonBusy(allow, false, ""); } });
  ui.dialogActions.append(cancel, allow); ui.decisionDialog.showModal();
}
function syncCancelRequestUi(conversation = state.conversation) {
  const cancelling = state.cancelRequestInFlight === true || backgroundCancellationPending(conversation);
  ui.cancelAgentButton.disabled = cancelling;
  ui.cancelAgentButton.textContent = cancelling ? "取消中" : "停止执行";
  ui.cancelAgentButton.setAttribute("aria-label", cancelling ? "正在请求停止当前智能协作与任务后台动作" : "请求停止当前智能协作与任务后台动作");
  const inlineCancelButtons = [...ui.messageList.querySelectorAll("[data-ai-turn-cancel]")];
  inlineCancelButtons.forEach((button) => { button.disabled = cancelling; button.textContent = cancelling ? "正在停止" : "停止"; });
  ui.messageInput.disabled = !state.runtimeReady || cancelling;
  ui.sendButton.disabled = !state.runtimeReady || cancelling;
  if (!cancelling) { delete ui.agentWorking.dataset.status; syncConversationComposerPlaceholder(conversation, state.task); return; }
  ui.messageInput.placeholder = "正在停止当前执行，请等待后端确认…";
  ui.agentWorking.hidden = inlineCancelButtons.length > 0;
  ui.agentWorking.dataset.status = "cancelling";
  ui.agentWorkingLabel.textContent = "正在停止当前智能协作与任务后台动作";
}
function openCancelAgentDialog() {
  if (!state.selectedTaskId || state.cancelRequestInFlight) return;
  if (backgroundCancellationPending(state.conversation)) { showNotice("停止请求已经记录，正在等待当前智能协作与任务后台动作确认；无需重复提交。", "ok"); return; }
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "停止当前执行"; ui.dialogTitle.textContent = "请求停止当前任务的执行？";
  const copy = document.createElement("p"); copy.textContent = "确认后会请求停止当前智能协作，以及这个任务所属的排队中或运行中后台动作。最终是否全部停止以任务状态为准。";
  const field = document.createElement("label"); field.className = "cancel-reason-field"; const label = document.createElement("span"); label.textContent = "取消理由"; const reason = document.createElement("textarea"); reason.rows = 3; reason.maxLength = 500; reason.placeholder = "例如：需求需要调整，先停止当前执行"; field.append(label, reason); ui.dialogBody.append(copy, field);
  const back = document.createElement("button"); back.type = "button"; back.className = "reject"; back.textContent = "返回"; back.addEventListener("click", () => ui.decisionDialog.close());
  const allow = document.createElement("button"); allow.type = "button"; allow.className = "allow"; allow.textContent = "请求取消"; allow.disabled = true;
  reason.addEventListener("input", () => { allow.disabled = !reason.value.trim(); });
  allow.addEventListener("click", async () => {
    const cancelReason = reason.value.trim(); if (!cancelReason) { showNotice("请先填写取消理由。", "error"); return; }
    state.cancelRequestInFlight = true; syncCancelRequestUi(); setButtonBusy(allow, true, "取消中");
    try {
      await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/conversation/cancel`, { method: "POST", json: { reason: cancelReason } });
      ui.decisionDialog.close(); showNotice("停止请求已被接受，正在确认当前智能协作与任务后台动作的最终状态。", "ok");
      try { await refreshSelected({ force: true }); } catch (refreshError) { showNotice(`取消请求已提交，但状态刷新失败：${refreshError.message}。请手动刷新确认最终状态。`, "error"); }
    } catch (error) {
      showNotice(`停止请求失败：${error.message}。当前智能协作和后台动作是否停止尚未确认，请刷新后重试。`, "error");
    } finally { state.cancelRequestInFlight = false; setButtonBusy(allow, false, ""); renderConversation(true); }
  });
  ui.dialogActions.append(back, allow); ui.decisionDialog.showModal(); window.requestAnimationFrame(() => reason.focus());
}
function approveProposedTrainingRun() {
  openSimpleDialog({ kicker: "启动真实计算", title: "批准本次训练运行？", body: `系统将使用已冻结合同启动 ${state.task?.recipe_id || "当前训练方案"}，并把事件、指标和模型产物写入本地运行目录。`, allowLabel: "批准并启动", onAllow: async () => { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/runs`, { method: "POST" }); showNotice("真实训练已经进入后台队列，运行事件会持续刷新。", "ok"); activateContext("run"); await refreshSelected({ force: true }); } });
}
function approveTrainingRecovery() {
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
async function postQuestionAnswers(item, answers, { taskId = state.selectedTaskId } = {}) {
  if (!taskId || !item?.rpc_id) throw new Error("当前问题缺少任务或会话身份，无法提交回答");
  return request(`/tasks/${encodeURIComponent(taskId)}/conversation/questions/${encodeURIComponent(item.rpc_id)}`, { method: "POST", json: { answers } });
}
function openQuestionDialog(item) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "训练协调器正在等待"; ui.dialogTitle.textContent = item.questions?.[0]?.header || item.title || "补充训练信息"; const fields = [];
  (item.questions || []).forEach((question, index) => { const block = document.createElement("section"); block.className = "question-block"; const title = document.createElement("b"); title.id = `question-label-${index}`; title.textContent = question.question; block.append(title); const options = document.createElement("div"); options.className = "question-options";
    if (question.options?.length) { question.options.forEach((option) => { const presentation = optionPresentation(option.label); const label = document.createElement("label"); label.dataset.recommended = String(presentation.recommended); const input = document.createElement("input"); input.type = question.multiSelect ? "checkbox" : "radio"; input.name = `question-${index}`; input.value = option.label; input.setAttribute("aria-labelledby", title.id); const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = `${presentation.label}${presentation.recommended ? "（推荐）" : ""}`; copy.append(name); if (option.description) { const small = document.createElement("small"); small.textContent = option.description; copy.append(small); } label.append(input, copy); options.append(label); }); const input = document.createElement("input"); input.className = "question-custom"; input.placeholder = "或者直接补充你的想法"; input.setAttribute("aria-labelledby", title.id); input.autocomplete = "off"; block.append(options, input); fields.push({ question, options, input }); }
    else { const input = document.createElement("input"); input.className = "question-custom"; input.placeholder = "输入你的回答"; input.setAttribute("aria-labelledby", title.id); input.autocomplete = "off"; block.append(input); fields.push({ question, input }); } ui.dialogBody.append(block);
  });
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => ui.decisionDialog.close()); const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = "提交回答";
  submit.addEventListener("click", async () => { const answers = fields.map(({ question, options, input }) => ({ id: question.id, selected: options ? [...options.querySelectorAll("input:checked")].map((field) => field.value) : [], ...(input?.value.trim() ? { custom: input.value.trim() } : {}) })); if (answers.some((answer) => !answer.selected.length && !answer.custom)) { showNotice("请先回答训练协调器的问题"); return; } setButtonBusy(submit, true, "提交中"); try { await postQuestionAnswers(item, answers); ui.decisionDialog.close(); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(submit, false, ""); } });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal(); window.requestAnimationFrame(() => { const firstField = fields[0]?.options?.querySelector("input") || fields[0]?.input; firstField?.focus({ preventScroll: true }); });
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
  if (!file.name.toLowerCase().endsWith(".zip")) { showNotice("训练能力扩展样例必须是按类别目录整理的 WAV ZIP。"); ui.recipeSampleInput.value = ""; return; }
  setButtonBusy(ui.datasetButton, true, "正在校验样例");
  try {
    await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/staged-assets`, {
      method: "POST", body: file,
      headers: { "content-type": "application/zip", "x-filename": encodeURIComponent(file.name), "x-spec-revision": String(state.task.current_spec_revision) },
    });
    showNotice("样例 ZIP 已隔离保存并通过安全检查；它没有被导入为正式训练数据。", "ok");
    openInspector("plan"); await refreshSelected({ force: true });
  } catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.datasetButton, false, ""); ui.recipeSampleInput.value = ""; }
}
function requestTrainingRunCancellation() {
  const taskId = state.selectedTaskId; const runId = state.task?.current_run_id; if (!taskId || !runId) return;
  openSimpleDialog({ kicker: "只停止训练运行", title: "请求停止本次训练？", body: "停止请求会在当前阶段边界生效。它不会停止当前对话，也不会删除已经写入的事件和证据。", allowLabel: "请求停止训练", onAllow: async () => { const result = await request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }); showNotice(result.cancel_requested ? "停止请求已提交；系统将在当前阶段边界停止。" : "该运行已经结束，无需再次停止。", "ok"); await refreshSelected({ force: true }); } });
}

function parseDelimitedHeader(line, delimiter) {
  const values = []; let current = ""; let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') { current += '"'; index += 1; }
      else quoted = !quoted;
    } else if (character === delimiter && !quoted) { values.push(current.trim()); current = ""; }
    else current += character;
  }
  values.push(current.trim()); return values.map((value) => value.replace(/^"|"$/gu, "")).filter(Boolean);
}
async function inspectCsvSchema(file) {
  const preview = await file.slice(0, 64 * 1024).text();
  const line = preview.split(/\r?\n/u).find((candidate) => candidate.trim()) || "";
  const candidates = [",", ";", "\t", "|"];
  const ranked = candidates.map((delimiter) => ({ delimiter, columns: parseDelimitedHeader(line, delimiter) })).sort((left, right) => right.columns.length - left.columns.length);
  const selected = ranked[0];
  if (!line || selected.columns.length < 2) throw new Error("没有从 CSV 首行识别出至少两个字段，请检查文件是否包含表头和正确的分隔符。");
  const taskId = state.selectedTaskId;
  if (!taskId) throw new Error("当前训练任务不存在，无法安全判断预测目标。");
  const response = await request(`/tasks/${encodeURIComponent(taskId)}/csv-target-recommendation`, {
    method: "POST",
    json: { columns: selected.columns },
  });
  const recommendation = response?.recommendation || {};
  const recommended = recommendation.status === "recommended" && selected.columns.includes(recommendation.target_column)
    ? recommendation.target_column
    : null;
  return { columns: selected.columns, delimiter: selected.delimiter, recommended, recommendation };
}
async function askCsvOptions(file) {
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "CSV 数据合同"; ui.dialogTitle.textContent = "确认要预测的字段";
  let schema;
  try { schema = await inspectCsvSchema(file); }
  catch (error) { showNotice(`读取 CSV 表头失败：${error.message}`); ui.datasetInput.value = ""; return; }
  const overview = document.createElement("section"); overview.className = "csv-schema-overview"; const fileName = document.createElement("b"); fileName.textContent = file.name; const meta = document.createElement("span"); const delimiterLabel = schema.delimiter === "\t" ? "Tab" : schema.delimiter; meta.textContent = `${formatBytes(file.size)} · 识别到 ${schema.columns.length} 个字段 · 分隔符 ${delimiterLabel}`; overview.append(fileName, meta); ui.dialogBody.append(overview);
  const targetBlock = document.createElement("section"); targetBlock.className = "question-block csv-target-block"; const targetTitle = document.createElement("b"); targetTitle.textContent = "哪一列是模型要预测的结果？"; const targetHint = document.createElement("small"); targetHint.textContent = schema.recommended ? `${schema.recommendation.message} 请核对后再导入。` : schema.recommendation.message || "任务里还没有唯一的预测目标，请手动选择后再导入。"; targetBlock.append(targetTitle, targetHint);
  let targetControl;
  if (schema.columns.length <= 12) {
    targetControl = document.createElement("div"); targetControl.className = "csv-column-choices";
    schema.columns.forEach((column) => { const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = "csv-target-column"; input.value = column; input.checked = column === schema.recommended; const copy = document.createElement("span"); copy.textContent = column; if (column === schema.recommended) { const badge = document.createElement("em"); badge.textContent = "推荐"; copy.append(badge); } label.append(input, copy); targetControl.append(label); });
  } else {
    targetControl = document.createElement("select"); targetControl.className = "question-custom csv-column-select"; targetControl.setAttribute("aria-label", "选择预测目标字段"); schema.columns.forEach((column) => { const option = document.createElement("option"); option.value = column; option.textContent = column === schema.recommended ? `${column}（推荐）` : column; option.selected = column === schema.recommended; targetControl.append(option); });
  }
  targetBlock.append(targetControl); ui.dialogBody.append(targetBlock);
  const advanced = document.createElement("details"); advanced.className = "csv-advanced-options"; const advancedSummary = document.createElement("summary"); advancedSummary.textContent = "高级设置（可选）"; const ignoredBlock = document.createElement("section"); ignoredBlock.className = "question-block"; const ignoredTitle = document.createElement("b"); ignoredTitle.textContent = "忽略字段"; const ignoredInput = document.createElement("input"); ignoredInput.className = "question-custom"; ignoredInput.placeholder = "多个字段用逗号分隔"; ignoredBlock.append(ignoredTitle, ignoredInput); advanced.append(advancedSummary, ignoredBlock); ui.dialogBody.append(advanced);
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", () => { ui.decisionDialog.close(); ui.datasetInput.value = ""; });
  const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = "确认并导入体检"; submit.addEventListener("click", async () => { const selected = targetControl.matches?.("select") ? targetControl.value : targetControl.querySelector('input[name="csv-target-column"]:checked')?.value; if (!selected) { showNotice("请选择一个预测目标字段。"); return; } ui.decisionDialog.close(); await uploadDataset(file, { targetColumn: selected, ignoredColumns: ignoredInput.value.trim(), delimiter: schema.delimiter }); });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal();
}
function datasetCoordinatorContinuation(targetColumn) {
  const readableTarget = String(targetColumn || "").replace(/[「」\r\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
  const targetNote = readableTarget ? `，预测目标是「${readableTarget}」` : "";
  return `数据已经上传好了${targetNote}。请先检查数据并给我一版容易理解的训练方案；在我确认方案和启动前，不要开始训练。`;
}
async function uploadDataset(file, options = {}) {
  const taskId = state.selectedTaskId; const activeCheckpoint = currentHumanCheckpoint(state.conversation); const uploadCheckpoint = dataUploadQuestionCheckpoint(activeCheckpoint);
  if (!taskId) { showNotice("先发送一条消息创建训练任务，再导入数据集。"); return; }
  if (state.task?.capability_decision?.status !== "resolved" && !uploadCheckpoint) { showNotice("请先澄清并确认任务理解；确认前不会导入数据或启动训练。"); return; }
  if (state.task?.status === "needs_recipe") { showNotice("当前能力还没有可执行训练方案。请先完成训练能力扩展并确认数据导入方式。"); return; }
  const lower = file?.name.toLowerCase() || ""; if (!lower.endsWith(".zip") && !lower.endsWith(".csv")) { showNotice("当前数据导入方式接受类别目录 ZIP 或 CSV；其他格式需要先扩展并验证训练能力。"); return; }
  if (uploadCheckpoint && !lower.endsWith(".csv")) { showNotice("协调器当前正在等待表格数据，请选择 CSV 文件；没有上传这个文件。", "error"); return; }
  if (lower.endsWith(".csv") && !options.targetColumn) { void askCsvOptions(file); return; }
  hideNotice(); setButtonBusy(ui.datasetButton, true, "体检中");
  const headers = { "content-type": lower.endsWith(".csv") ? "text/csv" : "application/zip", "x-filename": encodeURIComponent(file.name) };
  if (options.targetColumn) headers["x-target-column"] = encodeURIComponent(options.targetColumn);
  if (options.ignoredColumns) headers["x-ignored-columns"] = options.ignoredColumns.split(",").map((value) => encodeURIComponent(value.trim())).filter(Boolean).join(",");
  if (options.delimiter) headers["x-delimiter"] = encodeURIComponent(options.delimiter);
  try {
    let response;
    try { response = await request(`/tasks/${encodeURIComponent(taskId)}/dataset`, { method: "POST", body: file, headers }); }
    catch (error) { showNotice(`数据导入失败：${error.message}`); return; }
    const datasetId = response?.task?.dataset_id || null; activateContext("data");
    if (uploadCheckpoint) {
      if (!datasetId) { showNotice("数据已经导入并完成体检，但后端没有返回可核对的数据集编号，因此尚未替你续接协调器问题。请刷新任务，不要重复上传。", "error"); await refreshSelected({ force: true }); return; }
      const answers = dataUploadCheckpointAnswers(uploadCheckpoint, datasetId, options.targetColumn);
      try { await postQuestionAnswers(uploadCheckpoint, answers, { taskId }); showNotice("数据已导入，预测列也已提交；协调器会从刚才的问题继续。", "ok"); }
      catch (error) { showNotice(`数据已真实导入并完成体检（数据集 ${shortId(datasetId)}），但协调器问题续接失败：${error.message}。请不要重复上传；刷新任务后从当前问题继续。`, "error"); }
      await refreshSelected({ force: true }); return;
    }
    if (state.runtimeReady && !activeCheckpoint && datasetId) {
      try {
        await postQueuedConversationMessage(taskId, datasetCoordinatorContinuation(options.targetColumn));
        showNotice("数据已导入并完成体检。训练协调器会读取数据合同并继续完善方案；确认前不会启动训练。", "ok");
      } catch (error) {
        showNotice(`数据已真实导入并完成体检（数据集 ${shortId(datasetId)}），但协调器没有续接成功：${error.message}。请不要重复上传；可以在对话中要求它读取当前数据集。`, "error");
      }
      await refreshSelected({ force: true }); return;
    }
    const reason = activeCheckpoint
      ? "当前仍有一项决定等待你处理；数据合同已保留，处理后协调器再继续。"
      : !datasetId
        ? "后端没有返回可核对的数据集编号，协调器尚未自动续接。请刷新任务，不要重复上传。"
        : "训练协调器当前不可用，数据合同已保留；恢复连接后可在对话中继续。";
    showNotice(`数据已真实导入并完成体检。${reason}`, datasetId ? "ok" : "error"); await refreshSelected({ force: true });
  } finally { setButtonBusy(ui.datasetButton, false, ""); ui.datasetInput.value = ""; }
}
async function confirmContract() {
  const fields = [...ui.confirmations.querySelectorAll("input")]; if (fields.some((field) => !field.checked)) { showNotice("请明确勾选数据授权、标签/目标字段和验收门槛三项确认。"); return; }
  const revision = state.task?.contract_revision;
  const identityFields = ["contract_revision_id", "contract_sha256", "task_id", "spec_revision_id", "dataset_id", "dataset_fingerprint_sha256"];
  if (!revision || identityFields.some((field) => !revision[field])) {
    showNotice("当前页面还没有拿到可核对的合同版本与数据指纹。请刷新任务后再确认；本次没有写入批准。", "error");
    return;
  }
  const checkpoint = currentHumanCheckpoint(state.conversation);
  const payload = {
    ...Object.fromEntries(fields.map((field) => [field.dataset.confirm, true])),
    expected_contract_revision: Object.fromEntries(identityFields.map((field) => [field, revision[field]])),
    approval: {
      actor: "user",
      checkpoint_id: checkpoint?.checkpoint_id || checkpoint?.rpc_id || `workspace-confirm:${revision.contract_revision_id}`,
    },
  };
  setButtonBusy(ui.confirmContractButton, true, "确认中");
  try { await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/confirm`, { method: "POST", json: payload }); showNotice("这版训练合同与当前数据指纹已经锁定。", "ok"); await refreshSelected({ force: true }); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.confirmContractButton, false, ""); }
}
function activateContext(name) { const requested = name === "capability" ? "plan" : name; const target = ui.contextTabs.querySelector(`[data-context="${requested}"]`); const selected = target && !target.hidden ? requested : "plan"; document.querySelectorAll("[data-context]").forEach((button) => button.classList.toggle("active", button.dataset.context === selected)); document.querySelectorAll("[data-context-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.contextPanel === selected)); ui.inspectorSheetTitle.textContent = ({ plan: "方案与证据", data: "数据证据", run: "运行现场", evaluation: "评测报告", artifacts: "交付产物" })[selected] || "方案与证据"; }
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
  if (event.key === "Escape") { event.preventDefault(); closeInspector({ userInitiated: true }); return; }
  if (event.key !== "Tab") return;
  const focusable = inspectorFocusables();
  if (!focusable.length) { event.preventDefault(); ui.closeInspectorButton.focus(); return; }
  const first = focusable[0]; const last = focusable[focusable.length - 1]; const active = document.activeElement;
  if (event.shiftKey && (active === first || !ui.inspector.contains(active))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (active === last || !ui.inspector.contains(active))) { event.preventDefault(); first.focus(); }
}
function preferredWorkspacePresentation() {
  return state.workspaceProjection?.workspace?.presentation || (["executing", "result_ready", "blocked", "failed"].includes(state.workspaceProjection?.phase) ? "experience" : "technical");
}
function workspaceSheetTitle(context, presentation) {
  if (presentation === "experience") return ({ executing: "执行进展", result_ready: "本轮结果", blocked: "恢复任务", failed: "恢复运行" })[state.workspaceProjection?.phase] || "任务进展";
  return ({ plan: "方案与证据", data: "数据证据", run: "运行现场", evaluation: "评测报告", artifacts: "交付产物" })[context] || "方案与证据";
}
function openInspector(context = "plan", { objectRef = null, presentation = null, auto = false } = {}) {
  if (!state.selectedTaskId) return; const opening = ui.inspector.dataset.open !== "true";
  const mode = context === "object-viewer" ? "object-viewer" : "task-workspace"; state.inspectorMode = mode; ui.inspector.dataset.mode = mode;
  state.activeObjectRef = objectRef; if (objectRef) ui.inspector.dataset.objectType = normalizeObjectRefType(objectRef.type); else delete ui.inspector.dataset.objectType;
  if (opening && document.activeElement instanceof HTMLElement && document.activeElement !== document.body && !ui.inspector.contains(document.activeElement)) state.inspectorOpener = document.activeElement;
  ui.inspector.hidden = false; ui.inspector.inert = false; ui.inspector.setAttribute("aria-hidden", "false"); ui.inspectorEmpty.hidden = true; ui.objectViewer.hidden = mode !== "object-viewer"; ui.inspectorContent.hidden = mode !== "task-workspace";
  if (mode === "task-workspace") {
    const chosenPresentation = presentation || preferredWorkspacePresentation(); ui.inspector.dataset.presentation = chosenPresentation; ui.workspaceExperience.hidden = false; activateContext(context); ui.inspectorSheetTitle.textContent = workspaceSheetTitle(context, chosenPresentation); state.inspectorAutoOpened = Boolean(auto);
  } else {
    delete ui.inspector.dataset.presentation; ui.workspaceExperience.hidden = true; ui.inspectorSheetTitle.textContent = "精确证据"; state.inspectorAutoOpened = false;
  }
  ui.inspector.dataset.open = "true"; document.body.dataset.workspace = "open"; ui.inspectorScrim.hidden = dockedWorkspaceMedia.matches; ui.workspaceToggleButton.setAttribute("aria-expanded", "true"); ui.workspaceToggleButton.setAttribute("aria-label", "关闭任务证据"); setMobileView(["evaluation", "artifacts"].includes(context) ? "result" : "context");
  syncInspectorIsolation();
  if (opening && overlayWorkspace()) window.requestAnimationFrame(() => ui.closeInspectorButton.focus());
}
function closeInspector({ userInitiated = false } = {}) {
  const wasOpen = ui.inspector.dataset.open === "true"; const opener = state.inspectorOpener; state.inspectorOpener = null;
  if (userInitiated && state.workspaceProjection?.workspace?.auto_key) state.workspaceDismissedKey = state.workspaceProjection.workspace.auto_key;
  state.activeObjectRef = null; state.activeObjectPayload = null; state.inspectorMode = "closed"; state.inspectorAutoOpened = false; state.objectViewerRequestSeq += 1; delete ui.inspector.dataset.objectType; delete ui.inspector.dataset.presentation; ui.inspector.dataset.mode = "closed"; ui.inspectorSheetTitle.textContent = "方案与证据"; ui.objectViewer.hidden = true;
  ui.inspector.dataset.open = "false"; document.body.dataset.workspace = "closed"; ui.inspector.inert = true; ui.inspector.setAttribute("aria-hidden", "true"); ui.inspectorScrim.hidden = true; ui.workspaceToggleButton.setAttribute("aria-expanded", "false"); ui.workspaceToggleButton.setAttribute("aria-label", "打开任务证据"); setMobileView("conversation");
  syncInspectorIsolation();
  const restoreTarget = opener?.isConnected && !opener.disabled ? opener : ui.workspaceToggleButton;
  if (wasOpen && restoreTarget?.isConnected && !restoreTarget.disabled) window.requestAnimationFrame(() => restoreTarget.focus());
}
function openAllModelSourceCandidates() { openInspector("plan"); ui.modelSourceDiscovery.open = true; window.requestAnimationFrame(() => { ui.modelSourceCard.scrollIntoView({ block: "start", behavior: "smooth" }); if (!mobileWorkspace()) ui.modelSourceCandidates.focus({ preventScroll: true }); }); }
function openSidebar() { ui.sidebar.dataset.open = "true"; ui.sidebarScrim.hidden = false; }
function closeSidebar() { ui.sidebar.dataset.open = "false"; ui.sidebarScrim.hidden = true; }
function stopPolling() { if (state.pollTimer) window.clearInterval(state.pollTimer); state.pollTimer = null; stopConversationStream(); }
function resizeComposer() { ui.messageInput.style.height = "auto"; ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 140)}px`; }

ui.composerForm.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(ui.messageInput.value); });
ui.messageInput.addEventListener("input", () => { resizeComposer(); saveDraft(); });
ui.messageInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composerForm.requestSubmit(); } });
ui.newTaskButton.addEventListener("click", openNewTask); ui.refreshButton.addEventListener("click", () => state.selectedTaskId ? refreshSelected({ force: true }) : loadTasks());
ui.menuButton.addEventListener("click", openSidebar); ui.sidebarScrim.addEventListener("click", closeSidebar);
ui.datasetButton.addEventListener("click", () => {
  if (!state.selectedTaskId) { showNotice("先用一句话创建训练任务，再导入数据。"); return; }
  if (state.task?.control?.next_action?.id === "stage_recipe_samples") { ui.recipeSampleInput.click(); return; }
  ui.datasetInput.click();
}); ui.inspectorDatasetButton.addEventListener("click", () => ui.datasetInput.click()); ui.datasetInput.addEventListener("change", () => uploadDataset(ui.datasetInput.files?.[0])); ui.recipeSampleInput.addEventListener("change", () => stageRecipeSamples(ui.recipeSampleInput.files?.[0]));
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
ui.agentCheckpointWorkspaceButton.addEventListener("click", () => { openInspector(ui.agentCheckpointWorkspaceButton.dataset.context || "plan"); revealCurrentWorkspaceObject(); });
ui.confirmTaskSpecButton.addEventListener("click", () => openTaskSpecDialog()); ui.editTaskSpecButton.addEventListener("click", () => openTaskSpecDialog({ editing: true }));
ui.scaffoldRecipeButton.addEventListener("click", async () => {
  setButtonBusy(ui.scaffoldRecipeButton, true, "正在生成");
  try {
    const result = await request(`/tasks/${encodeURIComponent(state.selectedTaskId)}/recipe/scaffold`, { method: "POST" });
    const link = document.createElement("a"); link.href = result.scaffold.download_url; link.download = result.scaffold.archive_name; document.body.append(link); link.click(); link.remove();
    showNotice("已生成可审查的训练能力扩展包。该扩展包不会被自动执行，完成实现和测试后再注册。", "ok"); await refreshSelected({ force: true });
  } catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.scaffoldRecipeButton, false, ""); }
});
ui.approveRunProposalButton.addEventListener("click", approveProposedTrainingRun);
ui.cancelAgentButton.addEventListener("click", openCancelAgentDialog);
ui.cancelRunButton.addEventListener("click", requestTrainingRunCancellation);
ui.retryRunButton.addEventListener("click", approveTrainingRecovery);
ui.contextTabs.addEventListener("click", (event) => { const button = event.target.closest("[data-context]"); if (button) activateContext(button.dataset.context); });
ui.closeInspectorButton.addEventListener("click", () => closeInspector({ userInitiated: true })); ui.inspectorScrim.addEventListener("click", () => closeInspector({ userInitiated: true }));
ui.workspaceToggleButton.addEventListener("click", () => ui.inspector.dataset.open === "true" ? closeInspector({ userInitiated: true }) : openInspector(workspaceContextForProjection(), { presentation: preferredWorkspacePresentation() }));
ui.workspaceTechnicalButton.addEventListener("click", () => openInspector(workspaceContextForProjection(), { presentation: "technical" }));
ui.mobileConversationButton.addEventListener("click", () => closeInspector({ userInitiated: true })); ui.mobileContextButton.addEventListener("click", () => openInspector("plan", { presentation: "technical" })); ui.mobileResultButton.addEventListener("click", () => openInspector("evaluation", { presentation: "technical" }));
document.addEventListener("keydown", handleInspectorKeydown);
inspectorMedia.addEventListener("change", () => { syncInspectorIsolation(); if (mobileWorkspace() && ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus()); });
dockedWorkspaceMedia.addEventListener("change", () => {
  if (!dockedWorkspaceMedia.matches && state.inspectorAutoOpened && ui.inspector.dataset.open === "true") closeInspector({ userInitiated: false });
  if (ui.inspector.dataset.open === "true") ui.inspectorScrim.hidden = dockedWorkspaceMedia.matches;
  syncInspectorIsolation();
  if (state.task) syncWorkspaceForTask(state.task);
  if (!dockedWorkspaceMedia.matches && ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus());
});
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { ui.messageInput.value = button.dataset.prompt; resizeComposer(); ui.messageInput.focus(); }));

async function boot() { restoreDraft(null); window.setInterval(() => syncAiTurnElapsedLabels(), 1000); await Promise.all([loadRuntime(), loadHfCapability(), loadModelSourceProviders(), loadTaskSpecFamilies(), loadTasks({ selectFromUrl: true })]); if (!state.selectedTaskId) enterHomeState({ focusComposer: false }); resizeComposer(); }
boot().catch((error) => showNotice(`页面初始化失败：${error.message}`));
