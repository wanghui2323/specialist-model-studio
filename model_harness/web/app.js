const STATUS_LABELS = {
  draft: "任务草稿", needs_clarification: "等待澄清", needs_confirmation: "等待确认",
  awaiting_data: "等待数据", needs_recipe: "准备训练方案",
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
  "workspaceToggleButton", "workspaceExperience", "workspaceEyebrow", "workspaceTitle", "workspacePhaseBadge", "workspaceSummary", "workspacePreparationProgress", "workspaceTeam", "workspaceTeamTitle", "workspaceTeamCount", "workspaceTeamList", "workspaceResults", "workspaceResultsTitle", "workspaceResultCount", "workspaceResultList", "workspaceTechnicalButton", "workspaceTruthNote", "agentCheckpoint", "agentCheckpointStage", "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointSummary", "agentCheckpointBody", "agentCheckpointActions", "agentCheckpointWorkspaceButton", "agentCheckpointWorkspaceLabel", "agentCheckpointWorkspaceHint", "homeComposerSlot", "homeBoundary", "composerWrap",
  "agentWorking", "agentWorkingLabel", "cancelAgentButton", "composerForm", "composerNotice", "composerRetry", "composerRetryHint", "composerRetryButton", "composerHint", "messageInput", "sendButton", "composerMode", "composerModeLabel",
  "composerAttachment", "attachmentType", "attachmentName", "attachmentMeta", "attachmentStatus", "retryAttachmentButton", "removeAttachmentButton", "datasetButton", "datasetButtonLabel", "datasetInput", "recipeSampleInput", "inspectorDatasetButton", "inspectorEmpty", "inspectorContent", "objectViewer", "objectViewerTitle", "objectViewerState", "objectViewerSummary", "objectViewerOverview", "objectViewerIdentity", "objectViewerJson", "taskStatus", "contextTabs",
  "capabilityState", "capabilitySummary", "capabilityFacts", "capabilityAxes", "diagnosticCapabilityState", "diagnosticCapabilityReason", "trainingCapabilityState", "trainingCapabilityReason", "capabilityRecovery", "capabilityNonAction", "datasetCard", "datasetCount", "datasetSummary", "contractCard", "contractState",
  "scaffoldRecipeButton", "recipeExtensionDetails",
  "gateGrid", "confirmations", "confirmContractButton", "approveRunProposalButton", "runEventCount", "inspectorEvents", "resultCard", "closeDialogButton",
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
  "genericSampleFields", "sampleTrialSelectButton", "sampleTrialRunButton", "sampleInferenceList", "artifactBundleCard", "artifactBundleState", "artifactBundleSummary",
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
  "manualEntrypointInput", "trainingPlanFacts", "createTrainingPlanButton", "approveTrainingPlanButton", "trainingPlanDecisionActions", "rejectTrainingPlanButton", "cancelTrainingPlanButton", "trainingPlanConfirmationNote",
  "resourceFeasibilityCard", "resourceFeasibilityState", "resourceFeasibilitySummary", "resourceFeasibilityFacts", "baseImageDigestField",
  "baseImageDigestInput", "resourceFeasibilityReasons", "checkResourceFeasibilityButton", "contractConfirmationNote",
].map((id) => [id, document.getElementById(id)]));
const state = {
  tasks: [], task: null, selectedTaskId: null, selectionLoadingOwnerId: null, conversationRecord: null, conversation: null, runEvents: [], runtimeReady: false, pollTimer: null,
  conversationStream: null, conversationStreamCursor: null, conversationStreamRevision: null, conversationStreamTaskId: null, conversationStreamDegraded: false, conversationFallbackTimer: null, conversationReconnectTimer: null,
  conversationReconcileInFlight: false, conversationReconcileSeq: 0, conversationReconcilePromise: null,
  pendingMessage: null, messageSubmission: null, messageRequestSequence: 0, composerRetryAction: null, composerRetryKind: null, composerAttachment: null, cancelRequestInFlight: false, lastRenderKey: "", selectionToken: 0, hfCapability: null, hfModels: [], hfCard: null,
  modelAssetVerification: null, evidenceRunId: null, evidenceLoaded: false, evaluationReport: null, sampleInferences: [], artifactBundles: [],
  refreshInFlight: false, refreshSeq: 0,
  evidenceErrors: {},
  materialsOwnerId: null, materialInspections: [], materialsLoadedAt: 0, materialsLoadSeq: 0, materialContinuations: new Map(),
  modelSourceProviders: [], modelSourceCandidates: [], modelSourceResolutions: [], modelSourceSearches: [], modelSourceSearch: null, modelSourceMode: "search", modelSourceOperationSeq: 0, modelSourceLoadedTaskId: null, modelSourceCandidateRenderKey: "", modelSourceCheckpointRenderKey: "", modelSourceSearchInFlight: false,
  checkpointCard: null, workspaceAutoKey: null, workspaceProjection: null, workspaceDismissedKey: null, inspectorAutoOpened: false, inspectorOpener: null, inspectorMode: "closed", activeObjectRef: null, activeObjectPayload: null, objectViewerRequestSeq: 0, productRuntime: null, runtimeIssue: null, taskSpecFamilies: [], taskSpecFamiliesError: null, taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false,
  actionTimelineDisclosure: new Map(), actionResultCache: new Map(), actionResultRequests: new Map(),
  noticeDismissTimer: null, runtimeRetryTimer: null, runtimeRetryAttempt: 0, homeAvailabilityProbeSeq: 0, homeTasksReachable: null,
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
  task_understanding: "确认任务理解", capability_resolution: "准备训练方案", data_preparation: "准备训练数据",
  contract_review: "审阅训练合同", ready_to_run: "准备启动训练", evaluation: "审阅评测结果", run_recovery: "处理运行异常",
  source_discovery: "查找模型来源", source_resolution: "确认固定版本", source_snapshot: "读取来源清单", repository_analysis: "审阅仓库分析",
  training_plan: "确认训练计划", resource_probe: "检查本机资源", environment_lock: "冻结训练环境", resource_fit: "判断训练可行性",
};
const IMMUTABLE_COMMIT = /^[0-9a-f]{40}$/;
const EVIDENCE_SHA256 = /^[0-9a-f]{64}$/;
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
const sidebarMedia = window.matchMedia("(max-width:980px)");
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
function isHtmlErrorPayload(value, contentType = "") {
  if (String(contentType).toLowerCase().includes("text/html")) return true;
  if (typeof value !== "string") return false;
  return /^\s*(?:<!doctype\s+html|<html[\s>])/iu.test(value);
}
function responseErrorMessage(status, value, contentType = "") {
  if (status === 429) return "当前请求较多，训练工作台正在保护运行。请稍候片刻再试。";
  if ([502, 503, 504].includes(status)) return "训练工作台服务暂时不可用。任务数据仍会保留，请稍候刷新重试。";
  if (isHtmlErrorPayload(value, contentType)) return `服务返回了异常页面（HTTP ${status}），请稍候刷新重试。`;
  return structuredErrorMessage(value);
}
function isWorkspaceConnectionError(error) { return error?.status === 0 || [502, 503, 504].includes(error?.status); }
async function request(path, options = {}) {
  const { json, timeoutMs = 0, ...requestOptions } = options;
  const headers = { ...(requestOptions.headers || {}) };
  if (json !== undefined) { headers["content-type"] = "application/json"; requestOptions.body = JSON.stringify(json); }
  const controller = timeoutMs > 0 && !requestOptions.signal ? new AbortController() : null;
  const timeout = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  let response, rawValue;
  try {
    response = await fetch(path, { ...requestOptions, headers, ...(controller ? { signal: controller.signal } : {}) });
    rawValue = await response.text();
  } catch (cause) {
    const timedOut = controller?.signal.aborted === true || cause?.name === "AbortError";
    const error = new Error(timedOut ? "训练工作台响应超时，请稍候重试。" : "暂时无法连接训练工作台服务。请检查网络后刷新重试。");
    error.status = 0; error.retryable = true; error.payload = null;
    throw error;
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
  const type = response.headers.get("content-type") || "";
  let value = rawValue;
  if (type.includes("application/json") && rawValue) {
    try {
      value = JSON.parse(rawValue);
    } catch (_cause) {
      if (response.ok) {
        const error = new Error("训练工作台返回的数据暂时无法读取，请刷新后重试。");
        error.status = response.status; error.retryable = true; error.payload = null; error.responseType = type;
        throw error;
      }
    }
  }
  if (!response.ok) {
    const htmlPayload = isHtmlErrorPayload(value, type);
    const error = new Error(responseErrorMessage(response.status, value, type));
    error.status = response.status; error.retryable = [429, 502, 503, 504].includes(response.status); error.payload = htmlPayload ? null : value; error.responseType = type;
    throw error;
  }
  return value;
}
function clear(element) { while (element?.firstChild) element.firstChild.remove(); }
function formatTime(value) { const normalized = typeof value === "number" && value > 0 && value < 1_000_000_000_000 ? value * 1000 : value; const date = new Date(normalized); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function timestampMs(value) { const normalized = typeof value === "number" && value > 0 && value < 1_000_000_000_000 ? value * 1000 : value; const time = new Date(normalized).getTime(); return Number.isFinite(time) ? time : null; }
function formatElapsed(value) { const seconds = Math.max(0, Math.floor(Number(value || 0) / 1000)); if (seconds < 1) return "不足 1 秒"; if (seconds < 60) return `${seconds} 秒`; const minutes = Math.floor(seconds / 60); const remainder = seconds % 60; if (minutes < 60) return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`; const hours = Math.floor(minutes / 60); const minuteRemainder = minutes % 60; return minuteRemainder ? `${hours} 小时 ${minuteRemainder} 分` : `${hours} 小时`; }
function syncAiTurnElapsedLabels(root = document) {
  root.querySelectorAll?.("[data-ai-turn-status-label]").forEach((label) => {
    // Whole-turn timestamps include human waits and cannot prove active work.
    // Keep only the observed state here; operation timings stay in the evidence.
    label.textContent = label.dataset.baseLabel || label.textContent || "";
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
function showNotice(message, tone = "error") { clearNoticeDismissTimer(); state.noticeSequence = (state.noticeSequence || 0) + 1; delete ui.composerNotice.dataset.runtimeSetup; delete ui.composerNotice.dataset.noticeScope; delete ui.composerNotice.dataset.noticeOwnerId; delete ui.composerNotice.dataset.noticeSelectionToken; ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = tone; ui.composerNotice.textContent = message; }
function showConnectionNotice(message, tone = "error", ownerId = null, token = state.selectionToken) { showNotice(message, tone); ui.composerNotice.dataset.noticeScope = "connection"; ui.composerNotice.dataset.noticeOwnerId = ownerId || ""; ui.composerNotice.dataset.noticeSelectionToken = String(token); }
function showRuntimeSetupNotice(message) { clearNoticeDismissTimer(); delete ui.composerNotice.dataset.noticeScope; ui.composerNotice.dataset.runtimeSetup = "true"; ui.composerNotice.hidden = false; ui.composerNotice.dataset.tone = "error"; ui.composerNotice.textContent = message; }
function hideNotice() { clearNoticeDismissTimer(); delete ui.composerNotice.dataset.runtimeSetup; delete ui.composerNotice.dataset.noticeScope; ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }
function clearConnectionNotice(ownerId = null, token = state.selectionToken, noticeSequence = null) {
  const notice = ui.composerNotice.dataset;
  if (notice.noticeScope !== "connection" || (notice.noticeOwnerId || "") !== (ownerId || "")) return;
  if (ownerId && (state.selectedTaskId !== ownerId || state.selectionToken !== token || notice.noticeSelectionToken !== String(token))) return;
  if (noticeSequence !== null && noticeSequence !== (state.noticeSequence || 0)) return;
  const failure = state.lastWorkspaceConnectionFailure;
  if (failure?.notice_sequence === state.noticeSequence) failure.recovered_at = Date.now();
  hideNotice();
}
function showSelectedWorkspaceReadError(error, ownerId, token) {
  if (state.selectedTaskId !== ownerId || state.selectionToken !== token) return;
  if (!isWorkspaceConnectionError(error)) { showNotice(error.message); return; }
  showConnectionNotice(error.message, "error", ownerId, token);
  state.lastWorkspaceConnectionFailure = { owner_id: ownerId, selection_token: token, notice_sequence: state.noticeSequence, error, observed_at: Date.now(), recovered_at: null };
}
function prepareHomeAvailabilityProbe() {
  if (ui.composerNotice.dataset.noticeScope === "connection") showConnectionNotice("正在重新检查训练工作台连接…", "ok");
  else if (ui.composerNotice.dataset.runtimeSetup !== "true") hideNotice();
}
function showTransientNotice(message, tone = "ok", durationMs = 6_000) {
  showNotice(message, tone);
  state.noticeDismissTimer = window.setTimeout(() => { state.noticeDismissTimer = null; ui.composerNotice.hidden = true; ui.composerNotice.textContent = ""; }, durationMs);
}
function setButtonBusy(button, busy, busyText) {
  if (busy) {
    if (!button.busyChildren) button.busyChildren = [...button.childNodes];
    button.replaceChildren(document.createTextNode(busyText || "处理中"));
    button.setAttribute("aria-busy", "true");
  } else {
    if (button.busyChildren) { button.replaceChildren(...button.busyChildren); delete button.busyChildren; }
    button.removeAttribute("aria-busy");
  }
  button.disabled = busy;
  if (ui.closeDialogButton && ui.dialogActions?.contains(button)) ui.closeDialogButton.disabled = Boolean(ui.dialogActions.querySelector('[aria-busy="true"]'));
}
function closeDecisionDialog() {
  if (ui.dialogActions.querySelector('[aria-busy="true"]')) return;
  ui.decisionDialog.close();
}
function createUiIcon(name) {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("aria-hidden", "true"); icon.setAttribute("focusable", "false");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use"); use.setAttribute("href", `/app/static/model-harness-icons.svg?v=2.4.15#${name}`); icon.append(use); return icon;
}
function clearComposerRetry(kind = null) {
  if (kind && state.composerRetryKind !== kind) return;
  state.composerRetryAction = null; state.composerRetryKind = null; ui.composerRetry.hidden = true; ui.composerRetryHint.textContent = ""; ui.composerRetryButton.textContent = "重试"; delete ui.composerRetryButton.dataset.label;
}
function showComposerRetry({ label, hint, kind, action }) {
  state.composerRetryAction = action; state.composerRetryKind = kind; ui.composerRetry.hidden = false; ui.composerRetryHint.textContent = hint; ui.composerRetryButton.textContent = label; delete ui.composerRetryButton.dataset.label;
}
async function invokeComposerRetry() {
  const action = state.composerRetryAction; if (typeof action !== "function") { clearComposerRetry(); return; }
  setButtonBusy(ui.composerRetryButton, true, "重试中");
  try { await action(); }
  finally { if (!ui.composerRetry.hidden) setButtonBusy(ui.composerRetryButton, false, ""); }
}
const COMPOSER_ATTACHMENT_STATUS = { pending: "待核对", validating: "校验中", ready: "已导入", failed: "失败", inspected: "已检查材料", rejected: "检查未通过" };
function attachmentTypeLabel(file) {
  const extension = String(file?.name || "").split(".").pop()?.toUpperCase();
  if (["CSV", "JSONL", "ZIP"].includes(extension)) return extension;
  return String(file?.type || "FILE").split("/").pop()?.slice(0, 8).toUpperCase() || "FILE";
}
function syncPendingAttachmentAvailability(attachment = state.composerAttachment) {
  // A lost upload response is not proof that the file is still local. Keep
  // receipt reconciliation, successful imports and continuation retries intact.
  if (!attachment || attachment.status !== "pending" || attachment.dataset_id || attachment.material_id || ["reconcile", "continuation", "material_reconcile", "material_continuation"].includes(attachment.retry_stage)) return;
  if (attachment.task_id && attachment.task_id !== state.selectedTaskId) return;
  if (materialInspectionMode()) {
    attachment.waiting_on = "material_inspection"; attachment.waiting_action = "inspect_material"; attachment.waiting_action_label = "检查材料";
    attachment.error = "可先上传并检查材料；这不会导入训练数据或启动执行"; attachment.retry_stage = "upload"; attachment.can_retry = true;
    return;
  }
  const availability = datasetUploadAvailability();
  if (availability.blocked) {
    attachment.waiting_on = availability.code;
    attachment.waiting_action = availability.action || null;
    attachment.waiting_action_label = availability.actionLabel || null;
    attachment.error = availability.reason;
    attachment.retry_stage = "upload";
    attachment.can_retry = Boolean(availability.action);
  } else if (attachment.waiting_on) {
    delete attachment.waiting_on;
    delete attachment.waiting_action;
    delete attachment.waiting_action_label;
    attachment.error = null;
    attachment.retry_stage = "upload";
    attachment.can_retry = true;
  }
}
function renderComposerAttachment() {
  const attachment = state.composerAttachment; ui.composerAttachment.hidden = !attachment;
  if (!attachment) return;
  syncPendingAttachmentAvailability(attachment);
  const waiting = attachment.status === "pending" && attachment.waiting_on && !attachment.dataset_id && !["reconcile", "material_reconcile"].includes(attachment.retry_stage);
  const status = waiting ? "尚未上传" : COMPOSER_ATTACHMENT_STATUS[attachment.status] || COMPOSER_ATTACHMENT_STATUS.pending;
  ui.composerAttachment.dataset.waiting = String(Boolean(waiting));
  ui.composerAttachment.dataset.state = attachment.status || "pending"; ui.attachmentType.textContent = attachmentTypeLabel(attachment.file); ui.attachmentName.textContent = attachment.file?.name || "未命名文件"; ui.attachmentName.title = attachment.file?.name || "";
  const details = [attachment.file?.type || attachmentTypeLabel(attachment.file), formatBytes(attachment.file?.size)];
  if (attachment.dataset_id) details.push("已写入当前任务"); if (attachment.material_id) details.push(`材料检查结果 · ${materialFactSummary(attachment.material)}`); if (attachment.note) details.push(attachment.note); if (attachment.error) details.push(attachment.error);
  ui.attachmentMeta.textContent = details.filter(Boolean).join(" · "); ui.attachmentMeta.title = attachment.error || ""; ui.attachmentStatus.textContent = status; ui.attachmentStatus.dataset.state = attachment.status || "pending";
  const canRetry = (attachment.status === "failed" && attachment.can_retry === true) || ["continuation", "material_continuation"].includes(attachment.retry_stage) || (attachment.status === "pending" && attachment.can_retry === true);
  ui.retryAttachmentButton.hidden = !canRetry; ui.retryAttachmentButton.textContent = attachment.retry_stage === "material_dataset_review" ? "重新确认导入" : attachment.retry_stage === "material_continuation" ? "重试AI续接" : attachment.retry_stage === "material_reconcile" ? "核对检查" : waiting && attachment.waiting_action_label ? attachment.waiting_action_label : attachment.retry_stage === "continuation" ? "重试续接" : attachment.retry_stage === "reconcile" ? "核对导入" : attachment.upload_mode === "materials" ? attachment.status === "failed" ? "重试检查" : "检查材料" : attachment.status === "pending" ? "继续处理" : "重试导入";
  ui.removeAttachmentButton.disabled = attachment.status === "validating"; ui.removeAttachmentButton.title = attachment.status === "validating" ? "正在校验，返回结果前不能移除" : attachment.dataset_id ? "从输入框移除；已导入的数据不会被删除" : attachment.material_id ? "从输入框移除；材料检查记录仍然保留" : "从输入框移除文件";
  ui.removeAttachmentButton.setAttribute("aria-label", ui.removeAttachmentButton.title);
}
function updateComposerAttachment(attachment, patch) {
  if (!attachment || state.composerAttachment?.request_id !== attachment.request_id) return false;
  Object.assign(attachment, patch); renderComposerAttachment(); return true;
}
const MATERIAL_UPLOAD_LIMIT = 25 * 1024 * 1024;
function materialInspectionMode(task = state.task, taskId = state.selectedTaskId) {
  if (!taskId || !task || task.task_id !== taskId) return false;
  if (task.control?.next_action?.id === "stage_recipe_samples") return false;
  const nativeUpload = dataUploadQuestionCheckpoint(currentHumanCheckpoint(state.conversation));
  if (nativeUpload && task.recipe_id && datasetUploadFormat(task, null)) return false;
  return task.record_type === "conversation_draft" || task.status === "needs_recipe" || task.capability_decision?.status !== "resolved" || !datasetUploadFormat(task, null);
}
function materialOwnerPath(ownerId = state.selectedTaskId, scope = null) {
  const selectedScope = scope || (state.task?.record_type === "conversation_draft" ? "conversations" : "tasks");
  return `/${selectedScope}/${encodeURIComponent(ownerId)}`;
}
function materialInspectionMatches(record, ownerId, attachment = null) {
  return Boolean(record && record.object_type === "MaterialInspection" && record.owner_id === ownerId
    && /^material-[a-f0-9]{24}$/.test(record.material_id || "") && ["inspected", "rejected"].includes(record.status)
    && /^[a-f0-9]{64}$/.test(record.file?.sha256 || "") && record.dataset_imported === false && record.execution_authorized === false
    && (!attachment || (record.request_id === attachment.request_id && record.file.name === attachment.file.name && record.file.bytes === attachment.file.size)));
}
function resetMaterialInspections(ownerId = null) {
  state.materialsOwnerId = ownerId; state.materialInspections = []; state.materialsLoadedAt = 0; state.materialsLoadSeq = (state.materialsLoadSeq || 0) + 1;
  renderMaterialHistory();
}
function rememberMaterialInspection(record) {
  if (!materialInspectionMatches(record, state.selectedTaskId)) return;
  if (state.materialsOwnerId !== record.owner_id) resetMaterialInspections(record.owner_id);
  state.materialInspections = [record, ...(state.materialInspections || []).filter(item => item.material_id !== record.material_id)];
  renderMaterialHistory();
}
async function loadMaterialInspections(ownerId = state.selectedTaskId, { force = false } = {}) {
  if (!ownerId || ownerId !== state.selectedTaskId) return;
  if (state.materialsOwnerId !== ownerId) resetMaterialInspections(ownerId);
  if (!force && Date.now() - (state.materialsLoadedAt || 0) < 15_000) return;
  const seq = ++state.materialsLoadSeq;
  try {
    const response = await request(`${materialOwnerPath(ownerId)}/materials`, { timeoutMs: 10_000 });
    if (ownerId !== state.selectedTaskId || seq !== state.materialsLoadSeq) return;
    if (response.owner_id !== ownerId || !Array.isArray(response.materials)) throw new Error("材料列表身份不匹配");
    const known = new Map((state.materialInspections || []).map(record => [record.material_id, record]));
    state.materialInspections = response.materials.filter(record => materialInspectionMatches(record, ownerId)).map(record => record.detail_available && known.get(record.material_id)?.detail_available !== true && known.get(record.material_id)?.report ? known.get(record.material_id) : record).sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
    state.materialsLoadedAt = Date.now(); renderMaterialHistory(); void flushDeferredMaterialContinuations();
  } catch (_error) { /* Existing task state stays usable; uploads show their own precise errors. */ }
}
function materialReadEvidence(record, conversation = state.conversation) {
  if (conversation?.task_id !== record.owner_id) return null;
  const byId = new Map(), ambiguous = new Set();
  for (const event of conversation.events || []) { if (byId.has(event.event_id)) ambiguous.add(event.event_id); byId.set(event.event_id, event); }
  const objectValue = value => { try { if (typeof value === "string") return objectValue(JSON.parse(value)); if (Array.isArray(value)) return value.length === 1 && value[0]?.type === "text" ? objectValue(value[0].text) : null; return value && typeof value === "object" ? value : null; } catch (_error) { return null; } };
  for (const action of conversation.actions || []) {
    if (action.task_id !== record.owner_id || action.tool_name !== "model_harness_get_material" || action.status !== "completed" || action.truth_type !== "observed_result" || action.error) continue;
    if (ambiguous.has(action.call_event_id) || ambiguous.has(action.result_event_id)) continue;
    const call = byId.get(action.call_event_id), result = byId.get(action.result_event_id);
    if (!call || !result || call.event_type !== "tool_call" || result.event_type !== "tool_result" || call.source !== "dsh" || result.source !== "dsh") continue;
    if (!["task_id", "agent_run_id", "session_id", "turn_id", "call_id"].every(key => typeof action[key] === "string" && action[key] && call[key] === action[key] && result[key] === action[key])) continue;
    if (![call, result].every(event => event.payload?.tool_name === action.tool_name && event.payload?.call_id === action.call_id)) continue;
    if (!Number.isInteger(call.seq) || !Number.isInteger(result.seq) || call.seq >= result.seq || result.payload.is_error !== false) continue;
    const args = objectValue(call.payload.arguments);
    if (args?.owner_id !== record.owner_id || args?.material_id !== record.material_id) continue;
    const value = objectValue(result.payload.result)?.material;
    if (value?.owner_id === record.owner_id && value?.material_id === record.material_id && ["inspected", "rejected"].includes(value.status)) return { action_id: action.action_id, result_event_id: result.event_id };
    // A compact result still carries the canonical successful call/result pair.
    // Never infer consumption from prose, file names or the shortened preview.
    const ref = result.payload.event_result_ref;
    if (result.payload.result_truncated === true && ref?.task_id === record.owner_id && ref.id === result.event_id && action.event_result_ref?.id === ref.id) return { action_id: action.action_id, result_event_id: result.event_id };
  }
  return null;
}
function materialReplyInProgress(record) {
  return !state.conversation || state.conversation.task_id !== record.owner_id
    || state.conversation.execution_state_observed === false
    || state.conversation.agent_response_running === true
    || state.pendingMessage?.task_id === record.owner_id
    || (state.messageSubmission?.task_id === record.owner_id && state.messageSubmission.status === "sending");
}
async function flushDeferredMaterialContinuations() {
  const ownerId = state.selectedTaskId;
  if (!ownerId || state.materialAutoFlushOwner || state.materialsOwnerId !== ownerId) return;
  state.materialAutoFlushOwner = ownerId;
  try {
    for (const record of state.materialInspections || []) {
      if (state.selectedTaskId !== ownerId) return;
      const continuation = materialContinuation(record);
      if (!continuation.auto_requested || continuation.delivery_started || continuation.status !== "waiting_turn") continue;
      await continueMaterialInspection(record, state.composerAttachment?.material_id === record.material_id ? state.composerAttachment : null);
    }
  } finally { if (state.materialAutoFlushOwner === ownerId) state.materialAutoFlushOwner = null; }
}
function materialContinuationKey(record) { return `specialist-model-studio:material-message:${record.owner_id}:${record.material_id}`; }
function materialContinuation(record) {
  const key = materialContinuationKey(record);
  state.materialContinuations ||= new Map();
  let saved = state.materialContinuations.get(key);
  if (!saved) { try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch (_error) {} }
  if (saved?.owner_id === record.owner_id && saved?.material_id === record.material_id && saved.request_id && saved.message) return saved;
  const label = record.status === "rejected" ? "材料检查发现问题" : "材料已检查";
  return { owner_id: record.owner_id, material_id: record.material_id, request_id: `material-message-${record.material_id}`, status: "pending", message: `${label}（material_id=${record.material_id}）。请结合当前目标解读报告并继续。` };
}
function storeMaterialContinuation(record, continuation) {
  const key = materialContinuationKey(record); state.materialContinuations ||= new Map(); state.materialContinuations.set(key, continuation);
  try { localStorage.setItem(key, JSON.stringify({ ...continuation, in_flight: false })); } catch (_error) {}
}
async function continueMaterialInspection(record, attachment = null, { discussCheckpoint = false } = {}) {
  if (!materialInspectionMatches(record, state.selectedTaskId)) return;
  const continuation = materialContinuation(record);
  if (continuation.status === "accepted" || continuation.in_flight) return;
  if (!discussCheckpoint && !continuation.delivery_started) {
    continuation.auto_requested = true;
    const observedRead = materialReadEvidence(record);
    if (observedRead) {
      continuation.status = "accepted"; continuation.handled_by_tool = observedRead; storeMaterialContinuation(record, continuation);
      if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, error: null, note: null });
      renderMaterialHistory(); return;
    }
    // Uploading while composing must not start a turn with the previous goal.
    // The next submitted message refreshes the task-owned material facts.
    if (ui.messageInput.value.trim()) {
      continuation.auto_requested = false; continuation.status = "awaiting_message"; storeMaterialContinuation(record, continuation);
      if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, note: "材料已检查，可随下方要求一起继续" });
      renderMaterialHistory(); return;
    }
    if (materialReplyInProgress(record)) {
      continuation.status = "waiting_turn"; storeMaterialContinuation(record, continuation);
      if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, note: null });
      renderMaterialHistory(); return;
    }
  }
  const checkpoint = currentHumanCheckpoint(state.conversation);
  if (checkpoint && !continuation.delivery_started && !discussCheckpoint) {
    continuation.status = "deferred"; storeMaterialContinuation(record, continuation);
    if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, note: "报告已就绪，当前确认仍待处理" });
    renderMaterialHistory(); return;
  }
  if (!state.runtimeReady) {
    continuation.status = "failed"; continuation.error = "AI 连接恢复后可重新发送检查报告"; storeMaterialContinuation(record, continuation);
    if (attachment) updateComposerAttachment(attachment, { retry_stage: "material_continuation", can_retry: true, error: "材料检查已保留；AI 连接恢复后可续接" });
    renderMaterialHistory(); return;
  }
  delete continuation.error;
  if (!continuation.delivery_started) continuation.checkpoint_rpc_id = discussCheckpoint ? checkpoint?.rpc_id || null : null;
  continuation.delivery_started = true; continuation.in_flight = true; continuation.status = "pending"; storeMaterialContinuation(record, continuation);
  if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, error: null, note: null, continuation_in_flight: true });
  try {
    const response = await request(conversationTransportPath(record.owner_id, "messages"), { method: "POST", timeoutMs: 30_000, json: { message: continuation.message, mode: DEFAULT_CONVERSATION_MESSAGE_MODE, request_id: continuation.request_id, ...(continuation.checkpoint_rpc_id ? { checkpoint_rpc_id: continuation.checkpoint_rpc_id } : {}) } });
    if (response?.accepted !== true || ["failed", "cancelled", "canceled", "rejected", "interrupted"].includes(runtimeStatusToken(response.status))) throw new Error("AI 尚未确认接收材料检查消息");
    continuation.status = "accepted";
    if (attachment && attachment.task_id === state.selectedTaskId) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, error: null });
  } catch (error) {
    const receipt = error.payload?.detail;
    // The backend compares the original message before returning a terminal
    // receipt. A lost acknowledgement must not create another report message.
    if (receipt?.code === "composer_request_terminal" && receipt.request_id === continuation.request_id && ["completed", "succeeded"].includes(receipt.status)) {
      continuation.status = "accepted";
      if (attachment) updateComposerAttachment(attachment, { retry_stage: null, can_retry: false, error: null });
    } else {
      continuation.status = "failed"; continuation.error = error.message;
      if (attachment) updateComposerAttachment(attachment, { retry_stage: "material_continuation", can_retry: true, error: `材料已保存，报告消息暂未确认：${error.message}` });
    }
  } finally {
    continuation.in_flight = false; storeMaterialContinuation(record, continuation);
    if (attachment) attachment.continuation_in_flight = false;
    if (record.owner_id === state.selectedTaskId) { renderMaterialHistory(); await refreshSelected({ force: true }); }
  }
}
async function completeMaterialInspection(response, attachment, ownerId) {
  const record = response?.material;
  if (!materialInspectionMatches(record, ownerId, attachment)) throw new Error("材料回执与当前会话、文件或请求身份不一致");
  if (state.selectedTaskId !== ownerId || state.composerAttachment !== attachment) return;
  updateComposerAttachment(attachment, { status: record.status, material_id: record.material_id, material: record, error: record.status === "rejected" ? "材料检查发现阻断问题，请展开报告查看" : null, retry_stage: null, can_retry: false });
  rememberMaterialInspection(record);
  await continueMaterialInspection(record, attachment);
}
async function uploadMaterial(file, attachment = state.composerAttachment) {
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) return;
  const ownerId = state.selectedTaskId;
  if (!ownerId || !attachment || attachment.task_id !== ownerId || state.composerAttachment !== attachment || attachment.status === "validating" || attachment.reconciling || attachment.continuation_in_flight) return;
  if (attachment.material_id) { await continueMaterialInspection(attachment.material, attachment); return; }
  attachment.upload_mode = "materials"; attachment.material_scope ||= state.task?.record_type === "conversation_draft" ? "conversations" : "tasks";
  const fail = (message, retryable) => updateComposerAttachment(attachment, { status: "failed", error: message, retry_stage: "material_upload", can_retry: retryable });
  if (!/\.(csv|jsonl|zip)$/i.test(file?.name || "")) { fail("材料检查接受 CSV、JSONL 或 ZIP，请选择对应文件", false); return; }
  if (file.size > MATERIAL_UPLOAD_LIMIT) { fail("材料文件超过 25 MB，请拆分后重新选择", false); return; }
  const base = materialOwnerPath(ownerId, attachment.material_scope);
  const reconcile = async () => {
    const response = await request(`${base}/material-requests/${encodeURIComponent(attachment.request_id)}`, { timeoutMs: 15_000 });
    await completeMaterialInspection(response, attachment, ownerId); return response;
  };
  const uncertain = message => updateComposerAttachment(attachment, { status: "pending", error: message, retry_stage: "material_reconcile", can_retry: true });
  if (attachment.retry_stage === "material_reconcile") {
    try { attachment.reconciling = true; await reconcile(); return; }
    catch (error) { if (error.status !== 404) { uncertain(`暂不能确认材料回执：${error.message}`); return; } }
    finally { attachment.reconciling = false; }
  }
  updateComposerAttachment(attachment, { status: "validating", error: null, waiting_on: null, retry_stage: null, can_retry: false });
  try {
    let response;
    try { response = await request(`${base}/materials`, { method: "POST", timeoutMs: 60_000, body: file, headers: { "content-type": file.type || "application/octet-stream", "x-filename": encodeURIComponent(file.name), "x-request-id": attachment.request_id } }); }
    catch (error) {
      if (!Number.isFinite(error.status) || error.status === 0 || error.status === 408 || error.status >= 500 || error.retryable === true) {
        try { await reconcile(); return; }
        catch (_receiptError) { uncertain("检查响应中断，材料是否已保存尚未确认；可核对服务端回执"); return; }
      }
      fail(`材料未完成检查：${error.message}`, ![409, 413, 422].includes(error.status)); return;
    }
    try { await completeMaterialInspection(response, attachment, ownerId); }
    catch (_invalidResponse) {
      try { await reconcile(); }
      catch (_receiptError) { uncertain("检查响应未能核验，可核对服务端回执；不会重复创建材料记录"); }
    }
  } catch (error) { fail(error.message, false); }
}
function reusableDatasetMaterial(record) {
  const format = datasetUploadFormat(state.task, null);
  return materialInspectionMatches(record, state.selectedTaskId) && record.status === "inspected"
    && /^[a-f0-9]{64}$/.test(record.inspection_sha256 || "") && Boolean(state.task?.recipe_id)
    && !materialInspectionMode() && !datasetUploadAvailability().blocked
    && ["csv", "zip"].includes(format) && record.file.name.toLowerCase().endsWith(`.${format}`);
}
function appendReusableMaterialButton(container, record) {
  if (!reusableDatasetMaterial(record)) return;
  const button = document.createElement("button"); button.type = "button"; button.className = "text-button";
  button.textContent = "使用已上传文件"; button.setAttribute("aria-label", `使用已上传文件 ${record.file.name}`);
  button.addEventListener("click", async () => { button.disabled = true; try { await useMaterialAsDataset(record); } finally { button.disabled = false; } }); container.append(button);
}
function materialDatasetPendingKey(record) { return `specialist-model-studio:material-dataset-pending:${record.owner_id}:${record.material_id}:${record.inspection_sha256}`; }
function saveMaterialDatasetPending(attachment, status = "pending") {
  if (!attachment?.source_material) return;
  const saved = { request_id: attachment.request_id, base_spec_revision: attachment.base_spec_revision, options: attachment.options || {}, status, storage_key: attachment.material_dataset_storage_key };
  try { localStorage.setItem(materialDatasetPendingKey(attachment.source_material), JSON.stringify(saved)); } catch (_error) {}
}
function restoreMaterialDatasetPending(record) {
  try { const saved = JSON.parse(localStorage.getItem(materialDatasetPendingKey(record)) || "null"); return saved && ["pending", "needs_review"].includes(saved.status) && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(saved.request_id || "") && Number.isInteger(saved.base_spec_revision) && saved.base_spec_revision >= 1 ? saved : null; } catch (_error) { return null; }
}
function materialDatasetRequestId(record, options, attachment) {
  const fingerprint = JSON.stringify([record.inspection_sha256, options.targetColumn || "", options.ignoredColumns || "", options.delimiter || ""]);
  const key = `specialist-model-studio:material-dataset:${record.owner_id}:${record.material_id}:${fingerprint}`;
  state.materialDatasetRequests ||= new Map();
  let identity = attachment.force_new_material_request ? null : state.materialDatasetRequests.get(key);
  let savedRevision = null, needsReview = false;
  if (!attachment.force_new_material_request) {
    try { identity ||= localStorage.getItem(key); savedRevision = Number(localStorage.getItem(`${key}:revision`)); needsReview = localStorage.getItem(`${key}:needs-review`) === "true"; } catch (_error) {}
  }
  if (!identity || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(identity)) identity = createConversationRequestId();
  if (Number.isInteger(savedRevision) && savedRevision >= 1) attachment.base_spec_revision = savedRevision;
  attachment.material_dataset_storage_key = key; attachment.material_dataset_needs_review = needsReview;
  state.materialDatasetRequests.set(key, identity);
  try { localStorage.setItem(key, identity); localStorage.setItem(`${key}:revision`, String(attachment.base_spec_revision)); if (attachment.force_new_material_request) localStorage.setItem(`${key}:needs-review`, "false"); } catch (_error) {}
  attachment.force_new_material_request = false;
  return identity;
}
function requireMaterialDatasetReview(attachment, reason) {
  if (attachment.material_dataset_storage_key) { try { localStorage.setItem(`${attachment.material_dataset_storage_key}:needs-review`, "true"); } catch (_error) {} }
  attachment.material_dataset_needs_review = true;
  saveMaterialDatasetPending(attachment, "needs_review");
  updateComposerAttachment(attachment, { status: "failed", error: `导入条件已变化：${reason}。请重新确认当前任务与字段选择`, retry_stage: "material_dataset_review", can_retry: true });
}
async function reviewMaterialDatasetImport(attachment) {
  const ownerId = attachment.task_id; await refreshSelected({ force: true });
  if (state.selectedTaskId !== ownerId || state.composerAttachment !== attachment || !reusableDatasetMaterial(attachment.source_material)) return;
  const revision = state.task?.current_spec_revision;
  if (!Number.isInteger(revision) || revision < 1) { showNotice("尚未读到当前任务版本，请刷新后再确认导入。", "error"); return; }
  attachment.base_spec_revision = revision; attachment.force_new_material_request = true; attachment.material_dataset_needs_review = false;
  delete attachment.upload_context;
  updateComposerAttachment(attachment, { status: "pending", options: {}, error: null, retry_stage: null, can_retry: false });
  await uploadDataset(attachment.file, { attachment });
}
async function useMaterialAsDataset(record) {
  if (!reusableDatasetMaterial(record)) { showNotice("当前材料与训练数据入口不匹配，或还有确认待处理；请先核对当前任务。", "error"); return; }
  const revision = state.task?.current_spec_revision;
  if (!Number.isInteger(revision) || revision < 1) { showNotice("尚未读到当前任务版本，请刷新后再使用这份材料。", "error"); return; }
  const current = state.composerAttachment;
  if (current?.status === "validating" || current?.continuation_in_flight) return;
  if (current?.source_material?.material_id === record.material_id && current.task_id === record.owner_id) { await retryComposerAttachment(); return; }
  const attachment = { task_id: record.owner_id, request_id: createConversationRequestId(), file: { name: record.file.name, size: record.file.bytes }, source_material: record, base_spec_revision: revision, upload_mode: "material_dataset", status: "pending", options: {}, dataset_id: null, error: null, can_retry: false };
  const saved = restoreMaterialDatasetPending(record);
  if (saved) { attachment.request_id = saved.request_id; attachment.base_spec_revision = saved.base_spec_revision; attachment.options = saved.options || {}; attachment.material_dataset_storage_key = saved.storage_key; }
  state.composerAttachment = attachment; renderComposerAttachment();
  if (saved?.status === "needs_review") { requireMaterialDatasetReview(attachment, "上一次请求已要求重新核对"); return; }
  await uploadDataset(attachment.file, { ...attachment.options, attachment });
}
function renderMaterialHistory() {
  if (!ui.composerWrap?.insertBefore || typeof document === "undefined") return;
  let history = document.getElementById("materialInspectionHistory");
  if (!history) { history = document.createElement("details"); history.id = "materialInspectionHistory"; history.className = "material-inspection-history"; ui.composerWrap.insertBefore(history, ui.composerForm); }
  const records = state.materialsOwnerId === state.selectedTaskId ? state.materialInspections || [] : [];
  history.hidden = !records.length; if (!records.length) { history.replaceChildren(); delete history.dataset.renderKey; return; }
  const key = JSON.stringify(records.map(record => [record.material_id, record.status, record.detail_available, record.detail_error, materialContinuation(record).status, materialContinuation(record).in_flight, reusableDatasetMaterial(record)]));
  if (history.dataset.renderKey === key) return;
  history.dataset.renderKey = key; const openIds = new Set([...history.querySelectorAll("details[open]")].map(item => item.dataset.materialId)); history.replaceChildren();
  const heading = document.createElement("summary"); heading.textContent = `已上传文件 · ${records.length} 份`; history.append(heading);
  const labels = { file_count: "文件", row_count: "表格记录合计", image_count: "图片", wav_count: "音频", paired_reference_count: "配对引用", missing_reference_count: "缺失引用", total_audio_seconds: "音频秒数" };
  records.forEach(record => {
    const details = document.createElement("details"); details.className = "material-inspection-report"; details.dataset.materialId = record.material_id; details.open = openIds.has(record.material_id);
    details.addEventListener("toggle", () => { if (details.open && record.detail_available) void loadMaterialDetail(record); });
    const summary = document.createElement("summary"); summary.textContent = `${record.file.name} · ${record.status === "inspected" ? "已检查材料" : "检查未通过"}`; details.append(summary);
    const facts = document.createElement("p"); facts.textContent = Object.entries(labels).filter(([key]) => Number.isFinite(record.report?.facts?.[key])).map(([key, label]) => `${label} ${record.report.facts[key]}`).join(" · "); details.append(facts);
    if (Number.isFinite(record.report?.facts?.row_count) && record.report.facts.row_count > 0) { const note = document.createElement("p"); note.textContent = "表格记录合计包含检查到的各份清单，不代表去重后的训练样本数。"; details.append(note); }
    if (record.detail_available) { const note = document.createElement("p"); note.textContent = record.detail_error || "正在读取完整检查报告…"; details.append(note); }
    (record.report?.tables || []).slice(0, 10).forEach(table => { const item = document.createElement("p"); item.textContent = `${table.file}：${table.row_count} 行，${table.column_count} 列；${(table.columns || []).join("、")}`; details.append(item); });
    [...(record.report?.errors || []).map(item => ({ ...item, severity: "问题" })), ...(record.report?.warnings || []).map(item => ({ ...item, severity: "提示" }))].slice(0, 32).forEach(issue => { const item = document.createElement("p"); item.className = issue.severity === "问题" ? "material-inspection-error" : "material-inspection-note"; item.textContent = `${issue.severity}：${issue.message}${issue.file ? `（${issue.file}）` : ""}`; details.append(item); });
    if (record.report?.facts?.preview_truncated) { const note = document.createElement("p"); note.textContent = "报告明细已按安全上限截断；统计数量仍按完整检查记录显示。"; details.append(note); }
    if (materialContinuation(record).error) { const note = document.createElement("p"); note.textContent = `材料已保存，报告消息尚未确认：${materialContinuation(record).error}`; details.append(note); }
    if (materialContinuation(record).status === "deferred") { const note = document.createElement("p"); note.textContent = "报告已就绪，当前确认仍待处理。选择让 AI 读取报告会先讨论材料，不会批准执行或提交答案。"; details.append(note); }
    const identity = document.createElement("small"); identity.textContent = `材料编号 ${record.material_id} · SHA-256 ${record.file.sha256}`; details.append(identity);
    if (!["accepted", "waiting_turn"].includes(materialContinuation(record).status)) { const action = document.createElement("button"); action.type = "button"; action.className = "text-button"; action.textContent = materialContinuation(record).in_flight ? "正在发送检查报告…" : "让 AI 读取检查报告"; action.disabled = Boolean(materialContinuation(record).in_flight); action.addEventListener("click", async () => { action.disabled = true; action.setAttribute("aria-busy", "true"); try { await continueMaterialInspection(record, null, { discussCheckpoint: true }); } finally { action.disabled = false; action.removeAttribute("aria-busy"); } }); details.append(action); }
    appendReusableMaterialButton(details, record);
    history.append(details);
  });
}
function materialFactSummary(record) {
  const facts = record?.report?.facts || {};
  return [["file_count", "文件"], ["row_count", "表格记录合计"], ["image_count", "图片"], ["wav_count", "音频"], ["paired_reference_count", "配对"]].filter(([key]) => Number.isFinite(facts[key]) && facts[key] > 0).map(([key, label]) => `${label} ${facts[key]}`).concat(`问题 ${record?.report?.error_count ?? record?.report?.errors?.length ?? 0}`).join(" · ");
}
async function loadMaterialDetail(record) {
  if (record.owner_id !== state.selectedTaskId || record.details_loading || !record.detail_available) return;
  record.details_loading = true;
  try {
    const response = await request(`${materialOwnerPath(record.owner_id)}/materials/${encodeURIComponent(record.material_id)}`, { timeoutMs: 15_000 });
    if (!materialInspectionMatches(response?.material, record.owner_id) || response.material.material_id !== record.material_id) throw new Error("检查报告身份不一致");
    if (record.owner_id === state.selectedTaskId) rememberMaterialInspection(response.material);
  } catch (error) { record.detail_error = `完整报告暂未读取：${error.message}。收起后可重新展开。`; renderMaterialHistory(); }
  finally { record.details_loading = false; }
}
function renderMaterialControls() {
  if (!materialInspectionMode()) return;
  const busy = state.composerAttachment?.task_id === state.selectedTaskId && state.composerAttachment.status === "validating";
  ui.datasetButton.disabled = busy || Boolean(state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId); ui.datasetButtonLabel.textContent = busy ? "检查中" : "上传材料";
  ui.datasetButton.title = "上传 CSV、JSONL 或 ZIP 做只读材料检查，不会导入训练数据或授权执行";
  ui.inspectorDatasetButton.disabled = ui.datasetButton.disabled; ui.inspectorDatasetButton.textContent = "上传材料并检查"; ui.inspectorDatasetButton.title = ui.datasetButton.title;
  ui.datasetInput.accept = ".csv,.jsonl,.zip";
}
function datasetUploadReceiptMatches(response, taskId, requestId) {
  const receipt = response?.dataset_upload; const task = response?.task;
  if (!receipt || !task || receipt.object_type !== "DatasetUploadReceipt" || receipt.status !== "completed") return false;
  if (receipt.task_id !== taskId || receipt.request_id !== requestId || task.task_id !== taskId) return false;
  if (typeof receipt.dataset_id !== "string" || !receipt.dataset_id || task.dataset_id !== receipt.dataset_id) return false;
  return Array.isArray(task.dataset_history) && task.dataset_history.includes(receipt.dataset_id);
}
async function reconcileDatasetUploadReceipt(taskId, attachment) {
  if (!taskId || !attachment?.request_id || attachment.task_id !== taskId) throw new Error("数据请求缺少当前任务身份");
  const response = await request(`/tasks/${encodeURIComponent(taskId)}/dataset-upload-receipts/${encodeURIComponent(attachment.request_id)}`);
  if (!datasetUploadReceiptMatches(response, taskId, attachment.request_id)) throw new Error("服务端回执与当前任务数据集不一致");
  return response;
}
async function reconcileComposerDatasetUpload(task) {
  const attachment = state.composerAttachment;
  if (!attachment || attachment.task_id !== task?.task_id || attachment.dataset_id || attachment.retry_stage !== "reconcile" || attachment.reconciling) return false;
  attachment.reconciling = true;
  try {
    const response = await reconcileDatasetUploadReceipt(task.task_id, attachment);
    if (state.selectedTaskId !== task.task_id || state.composerAttachment !== attachment) return false;
    await completeDatasetUpload(response, attachment, task.task_id, attachment.options || {}, attachment.upload_context);
    return true;
  } catch (_error) {
    updateComposerAttachment(attachment, { status: "pending", error: "仍在等待服务端回执；可再次核对或安全重试原请求", retry_stage: "reconcile", can_retry: true });
    return false;
  } finally { attachment.reconciling = false; }
}
function clearComposerAttachment({ force = false } = {}) {
  if (!force && state.composerAttachment?.status === "validating") { showNotice("文件正在校验。请等待真实请求返回后再移除，避免误判是否已经导入。", "ok"); return; }
  const importedDatasetId = state.composerAttachment?.dataset_id || null;
  const inspectedMaterialId = state.composerAttachment?.material_id || null;
  state.composerAttachment = null; ui.datasetInput.value = ""; renderComposerAttachment();
  if (!force) showNotice(importedDatasetId ? "文件条目已从输入框移除；已经导入当前任务的数据仍然保留。" : inspectedMaterialId ? "文件条目已移除；材料检查记录仍可在当前对话中查看。" : "文件已从输入框移除。", "ok");
}
function syncComposerAttachmentOwner(taskId, { adoptAttachment = null } = {}) {
  if (state.materialsOwnerId !== taskId) resetMaterialInspections(taskId);
  const attachment = state.composerAttachment; if (!attachment) return;
  if (!taskId) { if (attachment.task_id) clearComposerAttachment({ force: true }); return; }
  if (!attachment.task_id) {
    if (attachment !== adoptAttachment) { clearComposerAttachment({ force: true }); return; }
    attachment.task_id = taskId; renderComposerAttachment(); return;
  }
  if (attachment.task_id !== taskId) clearComposerAttachment({ force: true });
}
function stageComposerAttachment(file) {
  if (!file) return;
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) { ui.datasetInput.value = ""; showNotice("正在加载当前对话，稍后再上传文件。", "ok"); return; }
  if (state.composerAttachment?.status === "validating") { showNotice("当前文件仍在校验，返回结果前没有替换它。", "ok"); ui.datasetInput.value = ""; return; }
  const attachment = { file, task_id: state.selectedTaskId, request_id: createConversationRequestId(), status: "pending", options: {}, dataset_id: null, error: null, retry_stage: null, can_retry: false, continuation: null };
  state.composerAttachment = attachment; renderComposerAttachment(); ui.datasetInput.value = "";
  if (!state.selectedTaskId) { updateComposerAttachment(attachment, { upload_mode: "materials", can_retry: false, retry_stage: "upload", error: "发送目标后会自动上传并检查材料" }); return; }
  if (materialInspectionMode()) void uploadMaterial(file, attachment);
  else void uploadDataset(file, { attachment });
}
async function resumeNewConversationAttachment(attachment, ownerId) {
  if (!attachment || state.composerAttachment !== attachment || state.selectedTaskId !== ownerId || attachment.task_id !== ownerId || attachment.status !== "pending" || attachment.material_id || attachment.dataset_id) return;
  await uploadMaterial(attachment.file, attachment);
}
async function retryComposerAttachment() {
  const attachment = state.composerAttachment;
  if (!attachment?.file || !attachment.request_id) { showNotice("没有可重试的文件请求；请重新选择文件。", "error"); return; }
  if (attachment.status === "validating" || attachment.reconciling || attachment.continuation_in_flight) return;
  if (!state.selectedTaskId) { showNotice("请先发送任务目标创建任务；文件仍保持待处理。", "ok"); return; }
  if (attachment.task_id && attachment.task_id !== state.selectedTaskId) { showNotice("这个文件请求属于另一项任务，已拒绝跨任务重试。请移除后重新选择。", "error"); return; }
  attachment.task_id = state.selectedTaskId;
  renderComposerAttachment();
  if (attachment.retry_stage === "material_dataset_review") { await reviewMaterialDatasetImport(attachment); return; }
  if (attachment.retry_stage === "material_continuation") { await continueMaterialInspection(attachment.material, attachment); return; }
  if (attachment.upload_mode === "materials" || attachment.waiting_action === "inspect_material") { await uploadMaterial(attachment.file, attachment); return; }
  if (attachment.status === "pending" && attachment.retry_stage === "upload" && attachment.waiting_action === "review_task_spec") { await openTaskSpecDialog(); return; }
  if (attachment.retry_stage === "continuation") { await retryAttachmentContinuation(attachment); return; }
  if (attachment.retry_stage === "reconcile") {
    const reconciled = await reconcileComposerDatasetUpload(state.task);
    if (reconciled) { await refreshSelected({ force: true }); return; }
  }
  if (attachment.dataset_id || attachment.task_id !== state.selectedTaskId) return;
  await uploadDataset(attachment.file, { ...attachment.options, attachment });
}
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
  return [...DATA_UPLOAD_QUESTION_IDS].some((id) => ids.has(id)) ? item : null;
}
function datasetUploadFormat(task = state.task, checkpoint = currentHumanCheckpoint(state.conversation)) {
  const adapter = task?.data_adapter_id || task?.capability_request?.data_adapter;
  if (adapter === "tabular-csv") return "csv";
  if (["image-folder-zip", "audio-keyword-class-folder-zip"].includes(adapter)) return "zip";
  if (["tabular-regression", "tabular-classification"].includes(task?.recipe_id)) return "csv";
  if (["image-folder-classification", "audio-keyword-classification"].includes(task?.recipe_id)) return "zip";
  return checkpoint?.questions?.some((question) => question.id === "csv_upload") ? "csv" : null;
}
function datasetUploadAvailability(task = state.task, checkpoint = currentHumanCheckpoint(state.conversation), taskId = state.selectedTaskId) {
  if (!taskId) return { blocked: true, code: "goal", reason: "发送目标后会自动上传并检查材料" };
  if (state.selectionLoadingOwnerId === taskId) return { blocked: true, code: "loading", reason: "正在加载当前对话，稍后再上传文件" };
  if (!task || task.task_id !== taskId) return { blocked: true, code: "loading", reason: "正在核对当前任务的数据入口；文件尚未上传" };
  if (task.record_type === "conversation_draft") return { blocked: true, code: "task_intake", reason: "目标正在整理，任务的数据入口还未确定；文件尚未上传" };
  if (task.status === "needs_recipe") {
    const preparingRecipe = task.control?.next_action?.id === "stage_recipe_samples";
    return { blocked: true, code: "integration", reason: preparingRecipe ? "请先通过“上传构建样例”准备训练能力；这个文件尚未导入" : "当前训练数据入口尚待验证；可以先上传材料检查，并继续准备训练方案" };
  }
  const uploadCheckpoint = dataUploadQuestionCheckpoint(checkpoint);
  if (task.capability_decision?.status !== "resolved" && !uploadCheckpoint) {
    const decision = task.capability_decision || {};
    const canReview = Boolean(task.task_spec && ["needs_confirmation", "needs_clarification"].includes(decision.status) && (decision.selected_family || decision.candidates?.length) && !checkpoint?.rpc_id);
    return { blocked: true, code: "task_output", reason: "先明确并确认任务的输入与输出；文件尚未上传，可以继续在对话中说明目标", action: canReview ? "review_task_spec" : null, actionLabel: canReview ? decision.status === "needs_clarification" ? "明确任务输出" : "确认任务理解" : null };
  }
  if (task.status === "running" && !uploadCheckpoint) return { blocked: true, code: "running", reason: "当前训练正在运行，结束后再导入新数据；文件尚未上传" };
  if (checkpoint?.rpc_id && isPendingHumanCheckpoint(checkpoint) && !uploadCheckpoint) return { blocked: true, code: "checkpoint", reason: "请先处理当前对话中的确认；文件尚未上传" };
  return { blocked: false, code: null, reason: null };
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
  [ui.datasetButton, ui.inspectorDatasetButton].filter(Boolean).forEach((control) => {
    if (materialInspectionMode()) { delete control.dataset.disabledByDshCheckpoint; return; }
    if (ownedByDsh) {
      if (!control.disabled) { control.disabled = true; control.dataset.disabledByDshCheckpoint = "true"; }
      control.title = datasetUploadAvailability(state.task, currentHumanCheckpoint(conversation)).reason || (dataUploadQuestionCheckpoint(currentHumanCheckpoint(conversation)) ? "请使用对话中准备数据卡片的文件选择按钮" : "请先处理当前对话中的确认；文件导入暂不可用");
    } else if (control.dataset.disabledByDshCheckpoint === "true") {
      const availability = datasetUploadAvailability(state.task, null);
      const recipeSamplesNeeded = control === ui.datasetButton && state.task?.control?.next_action?.id === "stage_recipe_samples";
      control.disabled = recipeSamplesNeeded ? false : availability.blocked;
      control.title = recipeSamplesNeeded ? "上传按类别整理的 PCM WAV 样例 ZIP" : availability.reason || "导入图片、音频 ZIP 或 CSV";
      delete control.dataset.disabledByDshCheckpoint;
    }
  });
  renderMaterialControls();
}
function syncLegacyConfirmationControls(task = state.task, conversation = state.conversation) {
  const checkpoint = currentHumanCheckpoint(conversation);
  const hasCanonicalCheckpoint = Boolean(checkpoint?.rpc_id && isPendingHumanCheckpoint(checkpoint));
  const planAwaitingConfirmation = task?.training_plan?.effective_status === "awaiting_approval" && task.training_plan.stale !== true;
  const contractAwaitingConfirmation = Boolean(task?.contract) && task.contract_confirmed !== true;
  const runAwaitingConfirmation = task?.contract_confirmed === true && task.control?.next_action?.id === "start_training_run" && task.status !== "running";
  const observationDegraded = state.conversationStreamDegraded || conversation?.projection_health?.status === "observation_degraded";

  ui.approveTrainingPlanButton.hidden = true; ui.approveTrainingPlanButton.disabled = true;
  ui.rejectTrainingPlanButton.hidden = true; ui.rejectTrainingPlanButton.disabled = true;
  ui.cancelTrainingPlanButton.hidden = true; ui.cancelTrainingPlanButton.disabled = true;
  ui.confirmContractButton.hidden = true; ui.confirmContractButton.disabled = true;
  ui.approveRunProposalButton.hidden = true; ui.approveRunProposalButton.disabled = true;
  ui.trainingPlanDecisionActions.hidden = true;

  const checkpointCopy = observationDegraded || !state.runtimeReady
    ? "确认仍保留在对话的 HumanCheckpoint 中；当前连接或观察链路不可用，检查点保持只读，恢复后再处理。"
    : "当前确认由对话中的 HumanCheckpoint 接管；这张卡只用于核对证据。";
  const coordinatorCopy = "这张卡只用于核对证据。训练协调器会在对话中提出 HumanCheckpoint；在此之前不会改变任务状态，也不会降低任何 gate。";

  ui.trainingPlanConfirmationNote.hidden = !planAwaitingConfirmation;
  if (planAwaitingConfirmation) {
    ui.trainingPlanConfirmationNote.textContent = hasCanonicalCheckpoint ? checkpointCopy : coordinatorCopy;
    if (hasCanonicalCheckpoint) { ui.approveTrainingPlanButton.hidden = false; ui.approveTrainingPlanButton.disabled = false; }
  }

  const contractNeedsConversation = contractAwaitingConfirmation || runAwaitingConfirmation;
  ui.contractConfirmationNote.hidden = !contractNeedsConversation;
  if (contractNeedsConversation) {
    ui.contractConfirmationNote.textContent = hasCanonicalCheckpoint ? checkpointCopy : coordinatorCopy;
    const navigation = contractAwaitingConfirmation ? ui.confirmContractButton : ui.approveRunProposalButton;
    if (hasCanonicalCheckpoint) { navigation.hidden = false; navigation.disabled = false; }
  }
}
function returnToHumanCheckpoint() {
  const checkpoint = currentHumanCheckpoint(state.conversation);
  if (!checkpoint?.rpc_id || !isPendingHumanCheckpoint(checkpoint)) {
    syncLegacyConfirmationControls();
    showNotice("当前没有可验证的 HumanCheckpoint。训练协调器会在对话中提出确认；本卡不会代替它写入决定。", "ok");
    return;
  }
  closeInspector({ userInitiated: false });
  window.requestAnimationFrame(() => {
    const target = [...ui.messageList.querySelectorAll('.human-checkpoint[data-rpc-id]')]
      .find((card) => card.dataset.rpcId === checkpoint.rpc_id);
    if (!target) {
      showNotice("待确认检查点仍在任务中，但当前对话尚未完整呈现。请刷新或恢复连接；本卡没有写入任何决定。", "error");
      return;
    }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.focus({ preventScroll: true });
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
  if (["cancelled", "canceled", "completed", "failed", "interrupted"].includes(runtimeStatusToken(entry?.status)) && entry?.running !== true && entry?.worker_running !== true) return false;
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
function syncComposerDelivery(conversation = state.conversation) {
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) { ui.composerHint.textContent = "正在加载对话 · 草稿会保存"; ui.sendButton.disabled = true; return; }
  const queued = Boolean(state.runtimeReady && state.selectedTaskId && !currentHumanCheckpoint(conversation) && conversationAgentResponseRunning(conversation));
  const showQueueHint = queued && Boolean(ui.messageInput.value.trim());
  ui.composerHint.textContent = showQueueHint ? "等待回复后发送" : "Enter 发送 · Shift + Enter 换行";
  ui.composerHint.dataset.delivery = showQueueHint ? "queued" : "immediate";
  ui.sendButton.setAttribute("aria-label", showQueueHint ? "等待回复后发送" : "发送消息");
  ui.sendButton.title = showQueueHint ? "等待当前回复结束后发送这条消息" : "发送消息";
}
function queuedConversationMessages(conversation) {
  const observed = new Set((conversation?.items || [])
    .filter((item) => item.type === "user_message" || item.category === "user_message" || (item.kind === "message" && item.role === "user"))
    .map((item) => item.agent_run_id).filter(Boolean));
  return (conversation?.runs || [])
    .filter((run) => run.status === "queued" && run.user_message && !observed.has(run.run_id))
    .map((run) => ({ kind: "message", role: "user", text: run.user_message, time: run.queued_at_utc,
      agent_run_id: run.run_id, request_id: run.composer_request?.request_id, delivery: "queued" }));
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
  const checkpoint = taskId === state.selectedTaskId ? currentHumanCheckpoint(state.conversation) : null;
  const previous = state.messageSubmission;
  if (previous?.task_id === taskId && previous.text === text && previous.status === "failed") {
    previous.status = "sending";
    if (previous.new_request_required === true) {
      previous.request_id = createConversationRequestId();
      previous.checkpoint_rpc_id = checkpoint?.rpc_id || null;
      previous.new_request_required = false;
    }
    return previous;
  }
  const submission = { task_id: taskId, text, request_id: createConversationRequestId(), status: "sending", checkpoint_rpc_id: checkpoint?.rpc_id || null };
  state.messageSubmission = submission;
  return submission;
}
function beginTaskCreationSubmission(text) {
  const previous = state.messageSubmission;
  if (previous?.task_id === null && previous.text === text && previous.status === "failed" && previous.create_request_id) {
    previous.status = "sending";
    if (previous.new_request_required === true) previous.request_id = `${previous.request_id.startsWith("material-intake-") ? "material-intake-" : ""}${createConversationRequestId()}`;
    previous.new_request_required = false;
    return previous;
  }
  const pendingMaterial = !state.selectedTaskId && state.composerAttachment?.file && !state.composerAttachment.task_id && !state.composerAttachment.material_id && !state.composerAttachment.dataset_id;
  const submission = {
    task_id: null,
    text,
    create_request_id: createConversationRequestId(),
    request_id: `${pendingMaterial ? "material-intake-" : ""}${createConversationRequestId()}`,
    status: "sending",
    new_request_required: false,
  };
  state.messageSubmission = submission;
  return submission;
}
async function postQueuedConversationMessage(taskId, text) {
  const submission = beginMessageSubmission(taskId, text);
  const waitingForReply = conversationAgentResponseRunning(state.conversation) && !submission.checkpoint_rpc_id;
  state.pendingMessage = { task_id: taskId, text, time: Date.now(), request_id: submission.request_id };
  renderConversation(true);
  try {
    const response = await request(conversationTransportPath(taskId, "messages"), {
      method: "POST",
      json: { message: text, mode: DEFAULT_CONVERSATION_MESSAGE_MODE, request_id: submission.request_id, ...(submission.checkpoint_rpc_id ? { checkpoint_rpc_id: submission.checkpoint_rpc_id } : {}) },
    });
    const status = runtimeStatusToken(response?.status);
    if (response?.accepted !== true || ["failed", "cancelled", "canceled", "rejected", "interrupted"].includes(status)) {
      const error = new Error(structuredErrorMessage(response, "后端没有接受这条消息"));
      error.payload = response;
      throw error;
    }
    if (state.pendingMessage?.request_id === submission.request_id) {
      state.pendingMessage.agent_run_id = response.agent_run_id;
      state.pendingMessage.delivery = waitingForReply && status === "queued" ? "queued" : "sent";
    }
    if (state.messageSubmission?.request_id === submission.request_id) state.messageSubmission = null;
    clearObservedPendingMessage(taskId, state.conversation);
    renderConversation(true);
    return response;
  } catch (error) {
    if (state.messageSubmission?.request_id === submission.request_id) {
      state.messageSubmission.status = "failed";
      const detail = error?.payload?.detail;
      state.messageSubmission.new_request_required = detail?.new_request_required === true || detail?.code === "checkpoint_changed";
    }
    if (state.pendingMessage?.task_id === taskId && state.pendingMessage.text === text) state.pendingMessage = null;
    throw error;
  }
}
function pendingExecutionIntegration(task, conversation = null, projection = null) {
  if (task?.capability_status !== "needs_recipe" && task?.status !== "needs_recipe") return null;
  if (conversation?.task_id && conversation.task_id !== task?.task_id) return null;
  const failed = new Set(["failed", "error", "identity_error", "blocked", "blocked_security", "blocked_environment", "blocked_resources", "blocked_platform"]);
  if ([task.status, task.current_result?.status, task.current_recipe_build?.status, task.repository_analysis?.status, task.resource_feasibility?.decision].some((value) => failed.has(value))) return null;
  const active = (values) => Array.isArray(values) ? values.filter((item) => item?.active !== false) : [];
  const gapCodes = new Set(["recipe_unavailable", "verified_recipe_unavailable"]);
  const code = (item) => typeof item === "string" ? item : item?.code || item?.reason_code;
  const blockers = [...active(task.blockers), ...active(task.control?.blocked_by), ...active(task.repository_analysis?.downstream_blockers), ...active(task.resource_feasibility?.blockers)];
  if (blockers.some((item) => !gapCodes.has(code(item)))) return null;
  const canonicalPhase = conversation?.interaction_projection?.phase;
  if (canonicalPhase && !["idle", "blocked"].includes(canonicalPhase)) return null;
  if (canonicalPhase === "blocked" && conversation?.interaction_projection?.subject?.object_type === "Risk") return null;
  if (conversation?.projection_health === "observation_degraded" || conversation?.projection_health?.status === "observation_degraded" || conversation?.projection_errors?.length) return null;
  if (conversation?.running === true || conversation?.execution_running === true || conversation?.agent_response_running === true || conversation?.background_action_running === true || conversation?.pending?.length) return null;
  if (active(conversation?.risks).length) return null;
  if (!Array.isArray(conversation?.risks) && (conversation?.actions || []).some((item) => ["failed", "identity_error"].includes(item?.status))) return null;
  if (projection && !["idle", "blocked"].includes(projection.phase)) return null;
  if (projection?.observation?.turn_failure || projection?.observation?.task_failure || projection?.observation?.degraded) return null;
  const explicitBlocker = projection?.observation?.blocker;
  if (explicitBlocker && !gapCodes.has(code(explicitBlocker))) return null;
  return {
    label: "准备训练方案", tone: "needs_recipe", phase: "idle",
    reason_code: "execution_integration_pending", can_cancel: false,
    summary: "围绕当前目标继续准备数据要求、训练路线、资源预算和验证步骤；实际运行需完成方案验证与授权。",
  };
}
function completedTrainingStatus(task) {
  const result = task?.current_result, report = result?.evaluation_report;
  if (task?.status !== "completed" || result?.status !== "completed" || !report || report.run_status !== "completed" || report.task_id !== task.task_id || report.run_id !== result.run_id || result.run_id !== task.current_run_id || !/^[a-f0-9]{64}$/.test(report.report_sha256 || "")) return null;
  if (report.conclusion === "quality_failed") return { label: "训练完成，质量未达标", tone: "needs_confirmation" };
  if (report.release_ready === true) return { label: "独立评估通过", tone: "completed" };
  return { label: "评估完成，仍需审阅", tone: "needs_confirmation" };
}
function workflowStatus(task, conversation = null) {
  if ((conversation && state.conversationStreamDegraded) || conversation?.projection_health === "observation_degraded" || conversation?.projection_health?.status === "observation_degraded") return { label: "需要重新连接", tone: "failed" };
  if (backgroundCancellationPending(conversation)) return { label: "正在停止", tone: "cancelling" };
  const checkpoint = currentHumanCheckpoint(conversation);
  if (checkpoint?.kind === "question") return { label: "等待你的回答", tone: "needs_confirmation" };
  if (checkpoint?.kind === "approval") return { label: approvalPresentation(checkpoint).header, tone: "needs_confirmation" };
  if (conversationAgentResponseRunning(conversation)) return { label: "AI 正在处理", tone: "running" };
  if (conversationHasBackgroundTraining(conversation)) return { label: "后台操作进行中", tone: "running" };
  if (conversation?.interaction_state === "waiting_for_human") return { label: "等待你的决定", tone: "needs_confirmation" };
  if (isConversationDraft(state.conversationRecord, task)) return { label: "等待你的消息", tone: "idle" };
  if (RUNNING_STATUSES.has(task.current_result?.status)) return { label: "后台操作进行中", tone: "running" };
  const trainingOutcome = completedTrainingStatus(task); if (trainingOutcome) return trainingOutcome;
  if (["running", "completed", "failed", "cancelled", "interrupted"].includes(task.status)) return { label: STATUS_LABELS[task.status] || task.status, tone: task.status };
  const integrationPending = pendingExecutionIntegration(task, conversation);
  if (integrationPending) return integrationPending;
  const stage = task.control?.current_stage; const blocked = task.control?.blocked_by?.[0]; const analysisStatus = task.repository_analysis?.status; const planStatus = task.training_plan?.effective_status;
  if (stage === "task_understanding") return { label: task.capability_decision?.status === "needs_confirmation" ? "等待确认" : "等待澄清", tone: "needs_clarification" };
  if (stage === "capability_resolution" || stage === "source_discovery") {
    return blocked
      ? { label: "任务当前受阻", tone: "failed" }
      : { label: "选择模型来源", tone: "needs_recipe" };
  }
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
    waiting_approval: { label: approvalPresentation(currentHumanCheckpoint(conversation) || {}).header, tone: "needs_confirmation" },
    agent_working: { label: "AI 正在处理", tone: "running" },
    background_working: { label: "后台操作进行中", tone: "running" },
    completed: { label: "本轮结果已就绪", tone: "completed" },
    failed: { label: "运行异常", tone: "failed" },
    stopped: { label: "本轮已停止", tone: "cancelled" },
    blocked: { label: "任务当前受阻", tone: "failed" },
  })[value.phase];
  return selected ? { ...selected, phase: value.phase, reason_code: value.phase, can_cancel: value.can_cancel === true } : null;
}
function interactionPresentation(task, conversation = state.conversation, projection = null) {
  if (isConversationDraft(state.conversationRecord, task)) {
    if ((conversation && state.conversationStreamDegraded) || conversation?.projection_health === "observation_degraded" || conversation?.projection_health?.status === "observation_degraded") return { label: "需要重新连接", tone: "failed", phase: "observation_degraded", reason_code: "observation_degraded", can_cancel: false };
    if (backgroundCancellationPending(conversation)) return { label: "正在停止", tone: "cancelling", phase: "stopping", reason_code: "stopping", can_cancel: false };
    const checkpoint = currentHumanCheckpoint(conversation);
    if (checkpoint?.kind === "question") return { label: "等待你的回答", tone: "needs_confirmation", phase: "clarifying", reason_code: "waiting_question", can_cancel: false };
    if (conversationAgentResponseRunning(conversation) || state.pendingMessage?.task_id === task?.task_id) return { label: "AI 正在回应", tone: "running", phase: "executing", reason_code: "agent_working", can_cancel: conversation?.can_cancel_agent === true };
    const canonical = canonicalInteractionPresentation(conversation);
    if (canonical?.phase === "failed") return { ...canonical, label: "本轮未完成" };
    if (canonical?.phase === "stopped") return canonical;
    return { label: "等待你的消息", tone: "idle", phase: "idle", reason_code: "conversation_idle", can_cancel: false };
  }
  const canonical = canonicalInteractionPresentation(conversation);
  const trainingOutcome = completedTrainingStatus(task);
  const integrationPending = pendingExecutionIntegration(task, conversation, projection);
  if ((!canonical || canonical.phase === "blocked") && integrationPending) return integrationPending;
  if (canonical?.phase === "blocked" && completedTaskOutranksStaleBlock(task, conversation)) return { ...(trainingOutcome || { label: "本轮已完成", tone: "completed" }), phase: "completed", reason_code: "task_completed", can_cancel: false };
  if (canonical?.phase === "completed" && trainingOutcome) return { ...canonical, ...trainingOutcome };
  if (canonical) return canonical;
  const projectionStatus = projection ? ({
    clarifying: { label: "等待你的回答", tone: "needs_confirmation" },
    awaiting_approval: { label: approvalPresentation(currentHumanCheckpoint(conversation) || {}).header, tone: "needs_confirmation" },
    executing: { label: backgroundCancellationPending(conversation) ? "正在停止" : conversationAgentResponseRunning(conversation) ? "AI 正在处理" : conversationHasBackgroundTraining(conversation) ? "后台操作进行中" : projection.background?.coordinator_reply_complete ? "后台操作进行中" : "AI 正在处理", tone: backgroundCancellationPending(conversation) ? "cancelling" : "running" },
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
function completedTaskOutranksStaleBlock(task, conversation) {
  if (task?.status !== "completed") return false;
  if ((task.control?.blocked_by || []).length) return false;
  if (currentHumanCheckpoint(conversation)) return false;
  if (conversationAgentResponseRunning(conversation) || conversationHasBackgroundTraining(conversation)) return false;
  return true;
}
function taskListStatus(task, conversation = null) {
  // The selected task owns the only hydrated conversation in this view. Its
  // canonical interaction projection must win over the coarser domain stage;
  // unselected tasks deliberately fall back to persisted task truth instead
  // of borrowing another task's conversation state.
  const taskOwnedConversation = conversation?.task_id === task?.task_id ? conversation : null;
  return taskOwnedConversation ? interactionPresentation(task, taskOwnedConversation) : workflowStatus(task, null);
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
const EVIDENCE_REFRESH_MS = 5000;
function runEvidenceSignature() {
  return JSON.stringify([state.evaluationReport?.report_id || state.evaluationReport?.created_at || null, state.sampleInferences.map((item) => item.check_id), state.artifactBundles.map((item) => item.bundle_id), state.evidenceErrors]);
}
function resetRunEvidence(runId = null) {
  state.evidenceRunId = runId; state.evidenceLoaded = false; state.evidenceLoadedAt = 0; state.evaluationReport = null; state.sampleInferences = []; state.artifactBundles = []; state.evidenceErrors = {};
  ui.sampleTrialInput.value = ""; ui.sampleTrialJson.value = "";
}
function draftId(taskId = state.selectedTaskId) { return taskId || DraftStore?.NEW_TASK || "__new__"; }
function saveDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.write(localStorage, draftId(taskId), ui.messageInput.value); }
function restoreDraft(taskId = state.selectedTaskId) { ui.messageInput.value = DraftStore ? DraftStore.read(localStorage, draftId(taskId)).text : ""; resizeComposer(); }
function clearDraft(taskId = state.selectedTaskId) { if (DraftStore) DraftStore.clear(localStorage, draftId(taskId)); }

function isConversationDraft(record = state.conversationRecord, task = state.task) {
  if (task?.record_type === "conversation_draft") return true;
  if (record?.status !== "unbound") return false;
  const conversationId = record?.conversation_id;
  const ownerId = task?.conversation_id || task?.task_id;
  // The selected intake conversation must never leak its presentation state
  // into unrelated persisted tasks in the sidebar.
  return Boolean(conversationId && (!ownerId || ownerId === conversationId));
}
function conversationDraftTask(record) {
  const conversationId = record?.conversation_id;
  return {
    record_type: "conversation_draft",
    task_id: conversationId,
    conversation_id: conversationId,
    name: record?.title || "新对话",
    status: "draft",
    current_result: null,
    control: { current_stage: "task_understanding", blocked_by: [] },
    created_at_utc: record?.created_at_utc,
    updated_at_utc: record?.updated_at_utc,
  };
}
function conversationTransportPath(ownerId, action = "snapshot", rpcId = null) {
  const id = encodeURIComponent(ownerId);
  const draft = isConversationDraft();
  if (action === "snapshot") return draft ? `/conversations/${id}/conversation` : `/tasks/${id}/conversation`;
  if (action === "stream") return draft ? `/conversations/${id}/conversation/stream` : `/tasks/${id}/conversation/stream`;
  if (action === "messages") return draft ? `/conversations/${id}/messages` : `/tasks/${id}/conversation/messages`;
  if (action === "cancel") return draft ? `/conversations/${id}/cancel` : `/tasks/${id}/conversation/cancel`;
  if (action === "questions") return draft ? `/conversations/${id}/questions/${encodeURIComponent(rpcId)}` : `/tasks/${id}/conversation/questions/${encodeURIComponent(rpcId)}`;
  if (action === "approvals") return draft ? `/conversations/${id}/approvals/${encodeURIComponent(rpcId)}` : `/tasks/${id}/conversation/approvals/${encodeURIComponent(rpcId)}`;
  throw new Error(`未知会话传输动作：${action}`);
}

function renderRuntimeMode(mode) {
  const ready = mode === "agent";
  const checking = mode === "checking";
  const incompatible = mode === "incompatible";
  const providerMissing = mode === "provider";
  const pillText = checking ? "正在连接 AI 服务" : ready ? "AI 服务已连接" : providerMissing ? "模型服务待配置" : incompatible ? "AI 服务版本不兼容" : "AI 服务未连接";
  const composerText = checking ? "正在连接 AI" : ready ? "AI 已连接" : providerMissing ? "先连接模型服务" : incompatible ? "服务版本不兼容 · 对话已暂停" : "AI 未连接 · 对话已暂停";
  ui.runtimePill.dataset.state = checking ? "checking" : ready ? "ready" : "error";
  ui.runtimePill.querySelector("span").textContent = pillText; ui.runtimePill.title = pillText; ui.runtimePill.setAttribute("aria-label", pillText);
  ui.composerMode.dataset.state = checking ? "checking" : ready ? "agent" : "local"; ui.composerModeLabel.textContent = composerText; ui.composerMode.title = ready ? "当前对话可用；只有发生真实工具调用或专家委派时，具体角色才会出现在执行过程里" : providerMissing ? "模型服务尚未配置，因此不会创建任务或启动对话" : checking ? composerText : "当前只允许查看任务事实和手动打开证据面板；不会用固定流程冒充智能协作";
  ui.messageInput.disabled = false; ui.sendButton.disabled = !ready || Boolean(state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) || state.conversation?.execution_state_observed === false; ui.composerWrap.dataset.runtime = ready ? "agent" : checking ? "checking" : "unavailable";
  if (!ready) ui.messageInput.placeholder = checking ? "正在连接 AI…" : providerMissing ? "请先在本机配置模型服务，再开始训练任务" : incompatible ? "AI 服务版本不兼容，请重启正式服务" : "AI 未连接，暂时不能创建或继续对话";
  else ui.messageInput.placeholder = state.selectedTaskId ? "继续询问或补充下一步要求…" : "告诉我，你希望模型帮你完成什么？";
  if (providerMissing) showRuntimeSetupNotice("模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。");
  else if (ui.composerNotice.dataset.runtimeSetup === "true") hideNotice();
  syncComposerDelivery();
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) renderSelectionLoading();
}
function compatibleAgentRuntime(agent) {
  return agent?.available === true && agent.real_agent === true && agent.implementation === "dsh_native_subagents" && agent.conversation_schema_version === "2.0" && agent.conversation_projector_revision === "3.4" && agent.synthesis_verdict_version === "1.0" && agent.conversation_action_schema_version === "1.0" && agent.task_truth_source === "TrainingTask";
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
  if (ui.homeBoundary) ui.homeBoundary.textContent = "说说你想解决的问题。可以从目标开始，也可以先提供材料。";
}
async function loadRuntime() {
  if (state.runtimeRetryTimer) window.clearTimeout(state.runtimeRetryTimer);
  state.runtimeRetryTimer = null;
  state.runtimeIssue = null; renderRuntimeMode("checking");
  try {
    state.productRuntime = await request("/runtime", { timeoutMs: 8_000 });
    applyAgentRuntimeStatus(state.productRuntime.agent);
  } catch (_runtimeError) {
    state.productRuntime = null;
    try { applyAgentRuntimeStatus(await request("/agent/runtime", { timeoutMs: 6_000 })); } catch (_agentError) { state.runtimeReady = false; }
  }
  renderProductBoundary();
  renderRuntimeMode(runtimeDisplayMode());
  if (state.task) renderConversation(true);
  if (state.runtimeReady) {
    state.runtimeRetryAttempt = 0;
    if (state.homeTasksReachable === true) clearConnectionNotice();
  }
  else if (!state.runtimeIssue) {
    const delays = [2_000, 5_000, 10_000, 15_000];
    const delay = delays[Math.min(state.runtimeRetryAttempt, delays.length - 1)];
    state.runtimeRetryAttempt += 1;
    state.runtimeRetryTimer = window.setTimeout(() => loadRuntime(), delay);
  }
}
function reconcileHomeAvailability(tasksFailure = null) {
  if (tasksFailure) {
    state.runtimeReady = false; state.runtimeIssue = null;
    renderRuntimeMode("local");
    showConnectionNotice(`任务列表暂时无法读取：${tasksFailure.message}。你仍可编辑草稿，连接恢复后再发送。`, "error");
    return false;
  }
  if (state.runtimeReady && state.homeTasksReachable === true) { clearConnectionNotice(); return true; }
  if (state.runtimeIssue === "provider") {
    showRuntimeSetupNotice("模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。");
  } else if (state.runtimeIssue === "incompatible") {
    showConnectionNotice("AI 服务版本不兼容，对话已暂停。请重启正式服务后再试。", "error");
  } else {
    showConnectionNotice("暂时无法连接训练工作台服务。请检查网络后重试。", "error");
  }
  return false;
}
async function refreshHomeAvailability({ announce = true } = {}) {
  const probeSeq = ++state.homeAvailabilityProbeSeq;
  state.homeTasksReachable = null;
  if (announce) prepareHomeAvailabilityProbe();
  const results = await Promise.allSettled([loadRuntime(), loadTasks()]);
  if (probeSeq !== state.homeAvailabilityProbeSeq || state.selectedTaskId) return false;
  const tasksFailure = results[1].status === "rejected" ? results[1].reason : null;
  return reconcileHomeAvailability(tasksFailure);
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
async function taskListPayload() {
  const pending = state.taskListLoadPromise || request("/tasks", { timeoutMs: 12_000 });
  state.taskListLoadPromise = pending;
  try { return await pending; }
  finally { if (state.taskListLoadPromise === pending) state.taskListLoadPromise = null; }
}
async function refreshTaskListIfDue({ force = false } = {}) {
  if (document.visibilityState !== "visible" || state.taskListLoadPromise || (!force && Date.now() - (state.taskListRefreshedAt || 0) < 20_000)) return false;
  state.taskListRefreshedAt = Date.now();
  try { await loadTasks({ preserveRows: true }); return true; }
  catch (_error) { return false; }
}
async function loadTasks({ selectFromUrl = false, preserveRows = false } = {}) {
  let payload;
  try { payload = await taskListPayload(); state.homeTasksReachable = true; state.taskListRefreshedAt = Date.now(); if (state.runtimeReady) clearConnectionNotice(); }
  catch (error) { state.homeTasksReachable = false; throw error; }
  state.tasks = payload.tasks || []; renderTaskList({ preserveRows });
  if (selectFromUrl && !state.selectedTaskId) {
    const params = new URL(location.href).searchParams;
    const requestedConversation = params.get("conversation");
    if (requestedConversation) { await selectConversation(requestedConversation); return; }
    const requested = params.get("task");
    if (!requested) { enterHomeState({ focusComposer: false }); return; }
    if (state.tasks.some((task) => task.task_id === requested)) { await selectTask(requested); return; }
    enterHomeState({ focusComposer: false });
    showNotice(`找不到训练任务 ${requested}。没有替你打开其他任务，请从左侧明确选择或新建任务。`);
  }
}
function renderTaskList({ preserveRows = false } = {}) {
  const rows = preserveRows ? [...ui.taskList.querySelectorAll(".task-row")] : [];
  if (rows.length === state.tasks.length && rows.length && state.tasks.every((task) => rows.some((row) => row.dataset.taskId === task.task_id))) {
    state.tasks.forEach((task) => {
      const row = rows.find((item) => item.dataset.taskId === task.task_id);
      const button = row.querySelector(".task-item"), status = row.querySelector(".task-workflow"), time = row.querySelector("time"), archive = row.querySelector(".task-archive-button");
      button.querySelector("b").textContent = task.name; button.setAttribute("aria-current", String(task.task_id === state.selectedTaskId));
      const workflow = taskListStatus(task, task.task_id === state.selectedTaskId ? state.conversation : null), dot = status.querySelector("i");
      dot.dataset.status = workflow.tone; status.replaceChildren(dot, document.createTextNode(workflow.label));
      time.dateTime = task.updated_at_utc || ""; time.textContent = formatRelativeTime(task.updated_at_utc);
      if (archive.getAttribute("aria-busy") !== "true") archive.disabled = task.status === "running";
      archive.title = archive.disabled ? "任务运行中，不能归档" : `归档任务：${task.name}`; archive.setAttribute("aria-label", archive.title);
    });
    return;
  }
  const focused = ui.taskList.contains(document.activeElement) ? { task_id: document.activeElement.dataset.taskId, action: document.activeElement.dataset.action } : null;
  clear(ui.taskList);
  if (!state.tasks.length) { const empty = document.createElement("div"); empty.className = "task-empty"; empty.textContent = "还没有模型任务。先描述一个真实问题。"; ui.taskList.append(empty); return; }
  state.tasks.forEach((task) => {
    const row = document.createElement("div"); row.className = "task-row"; row.dataset.taskId = task.task_id;
    const button = document.createElement("button"); button.type = "button"; button.className = "task-item"; button.dataset.action = "select-task"; button.dataset.taskId = task.task_id; button.setAttribute("aria-current", String(task.task_id === state.selectedTaskId));
    const title = document.createElement("b"); title.textContent = task.name;
    const meta = document.createElement("span"); meta.className = "task-meta";
    const taskConversation = task.task_id === state.selectedTaskId ? state.conversation : null; const workflow = taskListStatus(task, taskConversation); const status = document.createElement("span"); status.className = "task-workflow"; const dot = document.createElement("i"); dot.dataset.status = workflow.tone; status.append(dot, document.createTextNode(workflow.label));
    const time = document.createElement("time"); time.dateTime = task.updated_at_utc || ""; time.textContent = formatRelativeTime(task.updated_at_utc); meta.append(status, time);
    button.append(title, meta);
    const archive = document.createElement("button"); archive.type = "button"; archive.className = "task-archive-button icon-button"; archive.dataset.action = "archive-task"; archive.dataset.taskId = task.task_id;
    archive.disabled = task.status === "running"; archive.title = archive.disabled ? "任务运行中，不能归档" : `归档任务：${task.name}`; archive.setAttribute("aria-label", archive.title);
    archive.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h16v12H4zM3 4h18v3.5H3zM9 11h6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    button.addEventListener("click", () => selectTask(task.task_id)); archive.addEventListener("click", () => confirmTaskArchive(state.tasks.find((item) => item.task_id === task.task_id) || task, archive)); row.append(button, archive); ui.taskList.append(row);
  });
  if (focused) [...ui.taskList.querySelectorAll("button[data-task-id]")].find((button) => button.dataset.taskId === focused.task_id && button.dataset.action === focused.action)?.focus({ preventScroll: true });
}
function syncSelectedTaskListStatus(conversation = state.conversation, projection = null) {
  const task = state.tasks.find((item) => item.task_id === state.selectedTaskId); if (!task) return;
  const button = [...ui.taskList.querySelectorAll(".task-item")].find((item) => item.dataset.taskId === task.task_id); const status = button?.querySelector(".task-workflow"); const dot = status?.querySelector("i"); if (!status || !dot) return;
  const workflow = conversation?.task_id === task.task_id && projection ? interactionPresentation(task, conversation, projection) : taskListStatus(task, conversation); dot.dataset.status = workflow.tone; status.replaceChildren(dot, document.createTextNode(workflow.label));
}
function taskArchiveActivity(task, conversation) {
  if (!conversation || conversation.task_id !== task?.task_id) return "unknown";
  const canonical = conversation.interaction_projection;
  if (canonical?.schema_version === "1.0") {
    if (canonical.phase === "observation_degraded") return "unknown";
    if (canonical.phase === "stopping" || canonical.background?.stopping === true) return "stopping";
    if (["agent_working", "background_working", "waiting_question", "waiting_approval"].includes(canonical.phase) || canonical.background?.running === true) return "active";
    if (["idle", "completed", "stopped", "blocked", "failed"].includes(canonical.phase)) return null;
  }
  // Only current snapshot flags may block archiving. Historical AgentRuns or
  // a stale pending card in an idle conversation are not active execution.
  if (conversation.projection_health?.status === "observation_degraded") return "unknown";
  if (conversation.agent_response_running === true || conversation.background_action_running === true || conversation.execution_running === true || conversation.running === true) return "active";
  if (conversation.interaction_state === "waiting_for_human" && (conversation.pending || []).some(isPendingHumanCheckpoint)) return "active";
  return null;
}
async function taskArchiveSnapshot(task) {
  const response = await request(`/tasks/${encodeURIComponent(task.task_id)}/conversation`, { timeoutMs: 12_000 });
  const activity = taskArchiveActivity(task, response?.conversation);
  if (activity === "unknown") throw new Error("当前执行状态还不能核对，请恢复连接并刷新后再归档。");
  return activity;
}
function openTaskArchiveStopDialog(task) {
    openSimpleDialog({
      kicker: "归档前停止当前轮", title: `先停止“${task.name}”的当前轮？`,
      body: "这个任务仍有 AI 执行或待确认操作。先停止当前轮，待服务端确认全部停止后再归档；已有数据、运行记录和产物都会保留。",
      allowLabel: "请求停止当前轮",
      onAllow: async () => {
        await request(`/tasks/${encodeURIComponent(task.task_id)}/conversation/cancel`, { method: "POST", json: { reason: "用户准备归档任务，先停止当前执行和待确认操作" } });
        if (state.selectedTaskId === task.task_id) await refreshSelected({ force: true }); else await loadTasks();
        showNotice("停止请求已提交。请等待当前轮停止后再次归档；任务目前仍保留在列表中。", "ok");
      },
    });
}
async function confirmTaskArchive(task, trigger = null) {
  if (task.status === "running") { showNotice("真实训练运行中，暂不能归档任务。请等待运行结束或先取消训练。"); return; }
  if (state.archiveChecks?.has(task.task_id)) return;
  (state.archiveChecks ||= new Set()).add(task.task_id);
  if (trigger) setButtonBusy(trigger, true, "核对中");
  let activity;
  try { activity = await taskArchiveSnapshot(task); }
  catch (error) { showNotice(error.message); return; }
  finally { state.archiveChecks.delete(task.task_id); if (trigger) setButtonBusy(trigger, false, ""); }
  if (activity === "stopping") { showNotice("当前轮正在停止。请等待服务端确认全部停止后再归档。", "ok"); return; }
  if (activity === "active") {
    openTaskArchiveStopDialog(task);
    return;
  }
  openSimpleDialog({
    kicker: "任务归档", title: `归档“${task.name}”？`,
    body: "任务只会从默认列表隐藏；数据、Run、指标和产物都会保留。归档后不能再启动新的训练运行。",
    allowLabel: "确认归档",
    onAllow: async () => {
      if (await taskArchiveSnapshot(task)) throw new Error("任务又进入执行或待确认状态。请先停止当前轮，再重试归档。");
      const archivedSelected = task.task_id === state.selectedTaskId;
      try { await request(`/tasks/${encodeURIComponent(task.task_id)}/archive`, { method: "POST" }); }
      catch (error) {
        if (error.status === 409 && error.message.includes("当前消息仍可能在排队")) {
          ui.decisionDialog.close();
          showComposerRetry({ label: "停止当前轮", hint: "服务端确认这个任务仍有已接受的排队消息。先停止当前轮，再归档。", kind: "archive", action: () => openTaskArchiveStopDialog(task) });
        }
        throw error;
      }
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
  state.selectionLoadingOwnerId = null; ui.datasetInput.disabled = false;
  syncComposerAttachmentOwner(null); clearComposerRetry();
  ui.datasetButton.disabled = false; ui.datasetButtonLabel.textContent = "导入数据"; ui.datasetButton.title = "先选择 CSV、JSONL 或 ZIP；发送目标后检查材料或导入训练数据"; ui.datasetInput.accept = ".csv,.jsonl,.zip";
  history.replaceState(null, "", location.pathname); document.body.dataset.view = "home"; ui.homeComposerSlot.append(ui.composerWrap); ui.emptyState.hidden = false; ui.conversation.hidden = true;
  ui.inspector.hidden = true; ui.workspaceToggleButton.hidden = true; ui.mobileViewNav.hidden = true; ui.agentCheckpoint.hidden = true; ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.taskEyebrow.textContent = "SPECIALIST MODEL STUDIO"; ui.taskTitle.textContent = "开始一个模型任务";
  renderRuntimeMode(runtimeDisplayMode()); syncComposerDelivery(null); restoreDraft(null); renderTaskList(); closeSidebar(); closeInspector(); if (focusComposer && state.runtimeReady) ui.messageInput.focus();
}
function openNewTask() {
  saveDraft(); clearDraft(null); clearComposerAttachment({ force: true }); clearComposerRetry(); ui.messageInput.value = ""; resizeComposer(); stopPolling(); state.selectionToken += 1; Object.assign(state, { selectedTaskId: null, task: null, conversationRecord: null, conversation: null, runEvents: [], pendingMessage: null, lastRenderKey: "", taskSpecRevisions: [], taskSpecDescriptionMode: false, taskSpecQuickReplyKey: "", taskSpecAlternativesOpen: false });
  restoreCheckpointCard(); state.workspaceAutoKey = null; state.workspaceDismissedKey = null; state.workspaceProjection = null; state.inspectorAutoOpened = false;
  resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence();
  enterHomeState();
}
function renderSelectionLoading() {
  if (!state.selectionLoadingOwnerId || state.selectionLoadingOwnerId !== state.selectedTaskId) return;
  const ownerId = state.selectedTaskId;
  const selected = state.task?.task_id === ownerId ? state.task : state.tasks.find(task => task.task_id === ownerId);
  ui.taskTitle.textContent = selected?.name || state.conversationRecord?.title || "正在加载对话";
  ui.taskEyebrow.textContent = "正在加载"; ui.taskEyebrow.dataset.status = "neutral";
  ui.taskStatus.textContent = "正在加载对话"; ui.taskStatus.dataset.status = "neutral";
  clear(ui.messageList); ui.messageList.dataset.ownerId = ownerId; ui.messageList.setAttribute("aria-busy", "true");
  const loading = document.createElement("p"); loading.className = "conversation-loading"; loading.dataset.state = "loading"; loading.setAttribute("role", "status");
  loading.textContent = state.conversationStreamDegraded ? "对话暂未加载，请刷新重试；草稿会保留。" : "正在加载这项任务的对话…";
  ui.messageList.append(loading);
  ui.conversationIntro.hidden = true; ui.agentCheckpoint.hidden = true; ui.agentWorking.hidden = true; ui.cancelAgentButton.hidden = true;
  ui.workspaceExperience.hidden = true; ui.inspectorContent.hidden = true; ui.workspaceToggleButton.disabled = true;
  checkpointCards.forEach(card => { card.hidden = true; });
  ui.sendButton.disabled = true; ui.datasetButton.disabled = true; ui.inspectorDatasetButton.disabled = true; ui.datasetInput.disabled = true;
  ui.messageInput.disabled = false; ui.messageInput.placeholder = "可以先写草稿，加载完成后再发送…";
  ui.composerHint.textContent = "正在加载对话 · 草稿会保存";
}
async function selectTask(taskId, { saveCurrentDraft = true } = {}) {
  const switchingOwner = taskId !== state.selectedTaskId;
  if (switchingOwner) { if (saveCurrentDraft) saveDraft(); restoreCheckpointCard(); resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence(); state.task = null; state.conversation = null; state.runEvents = []; state.workspaceAutoKey = null; state.workspaceDismissedKey = null; state.workspaceProjection = null; state.inspectorAutoOpened = false; state.taskSpecRevisions = []; state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; }
  syncComposerAttachmentOwner(taskId); clearComposerRetry(); stopPolling(); hideNotice(); const token = ++state.selectionToken; state.selectedTaskId = taskId; state.conversationRecord = null; state.lastRenderKey = ""; state.pendingMessage = state.pendingMessage?.task_id === taskId ? state.pendingMessage : null; history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
  document.body.dataset.view = "task"; ui.conversationMain.append(ui.composerWrap); renderTaskList(); ui.emptyState.hidden = true; ui.conversation.hidden = false; ui.inspector.hidden = false; ui.workspaceToggleButton.hidden = false; ui.mobileViewNav.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false; closeSidebar(); closeInspector();
  restoreDraft(taskId); if (switchingOwner) { state.selectionLoadingOwnerId = taskId; if (ui.decisionDialog.open) ui.decisionDialog.close(); renderSelectionLoading(); } await refreshSelected({ force: true, token });
  if (state.selectedTaskId === taskId && state.selectionToken === token) {
    startConversationStream(taskId, token);
    state.pollTimer = window.setInterval(() => refreshSelected({ includeConversation: false }), 6000);
  }
}
async function selectConversation(conversationId, { saveCurrentDraft = true, record = null, pendingAttachment = null } = {}) {
  const switchingOwner = conversationId !== state.selectedTaskId;
  if (switchingOwner) {
    if (saveCurrentDraft) saveDraft();
    restoreCheckpointCard(); resetHfDiscovery(); resetModelSourceDiscovery(); resetRunEvidence();
    state.conversation = null; state.runEvents = []; state.workspaceAutoKey = null; state.workspaceDismissedKey = null; state.workspaceProjection = null; state.inspectorAutoOpened = false;
    state.taskSpecRevisions = []; state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false;
  }
  syncComposerAttachmentOwner(conversationId, { adoptAttachment: pendingAttachment }); clearComposerRetry(); stopPolling(); hideNotice();
  const token = ++state.selectionToken; state.selectedTaskId = conversationId; state.conversationRecord = record || { conversation_id: conversationId, status: "unbound", title: "新对话" }; state.task = conversationDraftTask(state.conversationRecord); state.lastRenderKey = "";
  state.pendingMessage = state.pendingMessage?.task_id === conversationId ? state.pendingMessage : null;
  history.replaceState(null, "", `${location.pathname}?conversation=${encodeURIComponent(conversationId)}`);
  document.body.dataset.view = "conversation"; ui.conversationMain.append(ui.composerWrap); renderTaskList(); ui.emptyState.hidden = true; ui.conversation.hidden = false;
  ui.inspector.hidden = true; ui.workspaceToggleButton.hidden = true; ui.mobileViewNav.hidden = true; ui.inspectorEmpty.hidden = false; ui.inspectorContent.hidden = true; ui.agentCheckpoint.hidden = true; closeSidebar(); closeInspector();
  restoreDraft(conversationId); if (switchingOwner) { state.selectionLoadingOwnerId = conversationId; if (ui.decisionDialog.open) ui.decisionDialog.close(); renderSelectionLoading(); } await refreshSelected({ force: true, token });
  if (state.selectedTaskId === conversationId && state.selectionToken === token) {
    startConversationStream(conversationId, token);
    state.pollTimer = window.setInterval(() => refreshSelected({ includeConversation: false }), 6000);
  }
}
async function refreshSelected({ force = false, token = state.selectionToken, includeConversation = true } = {}) {
  const taskId = state.selectedTaskId; if (!taskId || token !== state.selectionToken) return;
  if (state.refreshInFlight && !force) return;
  const seq = ++state.refreshSeq; const noticeSequence = state.noticeSequence || 0; state.refreshInFlight = true;
  let promotedFromConversation = false;
  try {
    if (isConversationDraft()) {
      try {
        const owner = await request(`/conversations/${encodeURIComponent(taskId)}`);
        if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
        if (owner.conversation?.conversation_id !== taskId || (owner.task && owner.task.task_id !== taskId)) throw new Error("返回的对话不属于当前任务，请刷新重试");
        state.conversationRecord = owner.conversation;
        clearConnectionNotice(taskId, token, noticeSequence);
        if (!owner.task) {
          state.task = conversationDraftTask(owner.conversation);
          checkpointCards.forEach((card) => { card.hidden = true; }); ui.agentCheckpoint.hidden = true;
          if (includeConversation) await reconcileConversation(taskId, token, { render: false });
          await loadMaterialInspections(taskId, { force });
          renderConversation(force);
          return;
        }
        promotedFromConversation = true; state.task = owner.task;
        state.tasks = [owner.task, ...state.tasks.filter((item) => item.task_id !== taskId)]; renderTaskList();
        history.replaceState(null, "", `${location.pathname}?task=${encodeURIComponent(taskId)}`);
        document.body.dataset.view = "task"; ui.inspector.hidden = false; ui.workspaceToggleButton.hidden = false; ui.mobileViewNav.hidden = false; ui.inspectorEmpty.hidden = true; ui.inspectorContent.hidden = false;
      } catch (error) {
        if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
        showSelectedWorkspaceReadError(error, taskId, token); return;
      }
    }
    try {
      const previousSpecRevision = state.task?.task_id === taskId ? state.task.current_spec_revision : null;
      const response = await request(`/tasks/${encodeURIComponent(taskId)}`); if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return; if (response.task?.task_id !== taskId) throw new Error("返回的任务身份不一致，请刷新重试"); state.task = response.task;
      clearConnectionNotice(taskId, token, noticeSequence);
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
      if (response.task.current_result?.status === "completed" && (force || !state.evidenceLoaded || Date.now() - (state.evidenceLoadedAt || 0) > EVIDENCE_REFRESH_MS)) {
        await loadRunEvidence(response.task);
        if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      }
    } catch (error) {
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
      showSelectedWorkspaceReadError(error, taskId, token); return;
    }
    if (includeConversation) await reconcileConversation(taskId, token, { render: false });
    if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    await loadMaterialInspections(taskId, { force });
    if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    await reconcileComposerDatasetUpload(state.task);
    if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    renderConversation(force); if (force) {
      await loadTasks();
      if (state.selectedTaskId !== taskId || token !== state.selectionToken || seq !== state.refreshSeq) return;
    }
    if (promotedFromConversation && state.selectedTaskId === taskId && token === state.selectionToken) startConversationStream(taskId, token);
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
  const pending = state.pendingMessage;
  const observed = conversation.items.some((item) => {
    if (!(item.role === "user" || item.category === "user_message" || item.type === "user_message")) return false;
    if (pending.request_id && !pending.agent_run_id) return false;
    return pending.agent_run_id ? item.agent_run_id === pending.agent_run_id : (item.text || item.payload?.text) === pending.text;
  });
  const queued = pending.request_id && queuedConversationMessages(conversation).some((item) => item.request_id === pending.request_id);
  if (observed || queued) state.pendingMessage = null;
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
  const persisted = value.observation_source === "persisted_projection";
  const readOnlyOffline = persisted && value.projection_health === "observation_degraded" && value.execution_state_observed === false && value.pending_observed === false
    && value.interaction_state === "observation_degraded" && value.interaction_projection?.phase === "observation_degraded"
    && value.can_cancel_agent === false && value.interaction_projection?.can_cancel === false
    && value.agent_response_running === null && [null, true].includes(value.running) && [null, true].includes(value.execution_running)
    && typeof value.background_action_running === "boolean" && Array.isArray(value.pending) && value.pending.length === 0 && Array.isArray(value.human_checkpoints) && value.human_checkpoints.length === 0;
  if (persisted && !readOnlyOffline) return false;
  if (!readOnlyOffline) {
    if (![value.running, value.execution_running, value.can_cancel_agent].every((field) => typeof field === "boolean")) return false;
    if ([value.agent_response_running, value.background_action_running].some((field) => field !== undefined && typeof field !== "boolean")) return false;
    if (!["working", "waiting_for_human", "cancelling", "idle", "terminal"].includes(value.interaction_state)) return false;
  }
  if (value.interaction_projection !== undefined && (value.interaction_projection?.schema_version !== "1.0" || typeof value.interaction_projection?.phase !== "string" || typeof value.interaction_projection?.can_cancel !== "boolean")) return false;
  if (!["items", "events", "actions", "pending", "runs", "agents", "delegations", "projection_errors"].every((field) => Array.isArray(value[field]))) return false;
  if (value.work_items !== undefined && !Array.isArray(value.work_items)) return false;
  if (!["agent_turns", "training_runs", "background_actions", "human_checkpoints", "risks", "supported_modes"].every((field) => value[field] === undefined || Array.isArray(value[field]))) return false;
  return value.stream_health && typeof value.stream_health === "object" && ["healthy", "observation_degraded"].includes(value.projection_health);
}
function acceptConversationSnapshot(taskId, token, remoteConversation) {
  if (state.selectedTaskId !== taskId || state.selectionToken !== token || remoteConversation?.task_id !== taskId || !isCanonicalConversationSnapshot(remoteConversation)) return false;
  state.conversation = remoteConversation;
  if (state.selectionLoadingOwnerId === taskId) { state.selectionLoadingOwnerId = null; state.selectionReadyOwnerId = taskId; }
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
  const seq = ++state.conversationReconcileSeq; const noticeSequence = state.noticeSequence || 0; const cursorBefore = state.conversationStreamCursor; state.conversationReconcileInFlight = true;
  const operation = (async () => {
    try {
      const remoteConversation = (await request(conversationTransportPath(taskId, "snapshot"))).conversation;
      if (seq !== state.conversationReconcileSeq || cursorBefore !== state.conversationStreamCursor) return false;
      if (!acceptConversationSnapshot(taskId, token, remoteConversation)) { markConversationStreamDegraded("全量对话返回了不兼容的证据合同。"); return false; }
      if (state.conversation?.projection_health === "healthy") clearConnectionNotice(taskId, token, noticeSequence);
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
  const source = new EventSource(`${conversationTransportPath(taskId, "stream")}${query.size ? `?${query}` : ""}`);
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
      if (state.conversation.execution_state_observed === false || [data.running, data.execution_running, data.agent_response_running].includes(null)) { void reconcileConversation(taskId, token); return; }
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
  if (!state.runtimeReady) ui.messageInput.placeholder = "AI 未连接，暂时不能继续对话";
  else if (state.cancelRequestInFlight || backgroundCancellationPending(conversation)) ui.messageInput.placeholder = "正在停止当前执行，请等待后端确认…";
  else if (uploadCheckpoint) ui.messageInput.placeholder = "还没准备好数据？可以先讨论格式或下一步…";
  else if (checkpoint?.kind === "question") ui.messageInput.placeholder = "继续提问或补充想法；发送后暂缓当前问题…";
  else if (checkpoint?.kind === "approval") ui.messageInput.placeholder = "有疑问可以先讨论；发送不会批准执行…";
  else if (conversationAgentResponseRunning(conversation)) ui.messageInput.placeholder = "继续输入…";
  else if (conversationHasBackgroundTraining(conversation)) ui.messageInput.placeholder = "继续提问或补充信息…";
  else if (isConversationDraft(state.conversationRecord, task)) ui.messageInput.placeholder = "继续补充你的目标、场景或限制…";
  else if (state.taskSpecDescriptionMode && stageKey(task) === "task_understanding") ui.messageInput.placeholder = "直接告诉 AI：模型接收什么、应该输出什么…";
  else ui.messageInput.placeholder = "继续提问、补充信息或调整目标…";
}
function renderTask(task) {
  syncTaskHeader(task);
  renderTaskSpec(task); renderCapability(task); renderModelSource(task); renderRepositoryAnalysis(task); renderTrainingPlan(task); renderResourceFeasibility(task); renderModelAsset(task); renderDataset(task); renderContract(task); renderResult(task); renderRunEvents(); renderRunControl(task);
  syncLegacyConfirmationControls(task, state.conversation);
  syncAgentCheckpoint(task); syncWorkspaceForTask(task);
  syncConversationComposerPlaceholder(state.conversation, task);
  syncComposerDelivery(state.conversation);
  if (state.selectionLoadingOwnerId === state.selectedTaskId) renderSelectionLoading();
}
function stageKey(task) { return task.control?.current_stage || "task_understanding"; }
function stageLabel(value) { if (value?.startsWith("run_")) return "训练与评测"; return STAGE_LABELS[value] || value || "确认任务理解"; }
function nextActionDescription(action, blocked) {
  if (blocked?.message && !["recipe_unavailable", "verified_recipe_unavailable"].includes(blocked.code)) return blocked.message;
  const descriptions = {
    upload_dataset: "导入与任务规格匹配的数据，后端会执行真实体检。", review_capability_gap: "结合目标和已有材料准备训练路线、数据要求与验证方法，按需查证模型来源和资源。",
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
    state.taskSpecDescriptionMode = false; state.taskSpecQuickReplyKey = ""; state.taskSpecAlternativesOpen = false; await refreshTaskSpecView(response.task); showNotice(`需求版本 v${response.task.current_spec_revision} 已保存；下一步将围绕这个目标继续准备训练方案。`, "ok");
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
  if (report.kind === "generic_files") { const parts = [["train", "训练"], ["validation", "验证"], ["test", "独立测试"]].filter(([split]) => report.split_counts?.[split]).map(([split, label]) => { const count = report.split_counts[split]; return `${label} ${count.file_count} 份文件${count.csv_row_count ? ` / ${count.csv_row_count} 行` : ""}`; }); return [`${report.total_files} 份文件`, parts.join(" · ")]; }
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
  if (card === ui.capabilityCard) return ["查看方案准备", "在右侧核对目标、材料与方案准备进展"];
  if (card === ui.repositoryAnalysisCard) return [blocked ? "处理仓库分析阻断" : "查看仓库分析", "在右侧核对入口、依赖、许可证与静态风险证据"];
  if (card === ui.trainingPlanCard) return ["核对训练计划", "在右侧检查入口、资源预算与不可变 Plan Digest"];
  if (card === ui.resourceFeasibilityCard) return [blocked ? "查看当前电脑缺少什么" : "检查本机训练条件", "在右侧查看资源事实、环境阻断与恢复动作"];
  if (card === ui.datasetCard) return ["准备训练数据", "在右侧查看数据体检结果与导入要求"];
  if (card === ui.contractCard) return ["确认训练合同", "在右侧核对数据授权、标签与验收门槛"];
  return ["打开任务证据", "在右侧查看当前步骤产生的对象与证据"];
}
function syncAgentCheckpoint(task) {
  const hasRuntimeCheckpoint = (state.conversation?.pending || []).some((item) => item?.rpc_id && (item.kind === "approval" || item.kind === "question"));
  if (state.runtimeReady || hasRuntimeCheckpoint || state.conversation?.session_id) { restoreCheckpointCard(); clear(ui.agentCheckpointBody); ui.agentCheckpointActions.hidden = true; ui.agentCheckpoint.hidden = true; return; }
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
  else { const goalEstablished = Boolean(task.task_spec?.business_goal && !["needs_clarification", "needs_confirmation"].includes(decision.status)); ui.diagnosticCapabilityState.textContent = goalEstablished ? "准备方案" : "整理目标"; ui.diagnosticCapabilityState.dataset.state = "pending"; ui.diagnosticCapabilityReason.textContent = goalEstablished ? "结合已有材料准备数据规范、训练路线和验证步骤，按需查证公开来源。" : "明确会影响方案的目标信息，同时可以上传材料供检查。"; }
  const trainingCapability = ConversationView.trainingCapabilityProjection(task); const integrationPending = pendingExecutionIntegration(task, state.conversation?.task_id === task.task_id ? state.conversation : null); ui.trainingCapabilityState.textContent = integrationPending?.label || trainingCapability.label; ui.trainingCapabilityState.dataset.state = integrationPending ? "pending" : trainingCapability.state; ui.trainingCapabilityState.dataset.code = trainingCapability.code; ui.trainingCapabilityReason.textContent = integrationPending?.summary || trainingCapability.reason;
  ui.capabilityRecovery.textContent = integrationPending ? "下一步：结合当前目标和已有材料继续准备方案，无需先选择目录中的其他任务类型。" : `下一步：${task.control?.next_action?.description || task.control?.next_action?.label || (activeBlocker?.recovery_actions || [])[0]?.label || "继续在对话中补充当前缺失证据。"}`;
  ui.capabilityNonAction.textContent = integrationPending ? "运行条件：方案、数据与资源通过核验后，再确认具体执行。" : task.capability_status === "matched" ? "不会执行：未完成数据、合同和人工审批前，不创建训练 Run。" : "不会执行：不下载权重、不执行第三方源码、不安装依赖、不创建训练 Run。";
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
  else if (task.capability_status === "matched" && task.recipe_source === "qualified-execution") { ui.capabilityState.textContent = "工程方案已启用"; ui.capabilitySummary.textContent = "本任务的工程实现已通过隔离验证，已形成数据集与训练合同；正式训练需确认合同和执行范围。"; }
  else if (task.capability_status === "matched") { ui.capabilityState.textContent = "现成方案可复用"; ui.capabilitySummary.textContent = `已有 ${task.recipe_id} 可复用；继续核对当前目标、数据和评测要求。`; }
  else if (task.capability_status === "needs_recipe" || task.status === "needs_recipe") { const pending = pendingExecutionIntegration(task, state.conversation?.task_id === task.task_id ? state.conversation : null); ui.capabilityState.textContent = pending?.label || "执行条件待处理"; ui.capabilitySummary.textContent = pending?.summary || "请先核查当前阻断证据与恢复动作，再继续模型研究或接入执行方案。"; }
  else { ui.capabilityState.textContent = "待识别"; ui.capabilitySummary.textContent = "继续描述输入数据、预测目标和运行限制，以匹配或扩展训练方案。"; }
  renderCapabilityAxes(task); addFact("数据模态", request.modality); addFact("任务目标", request.objective); addFact("输出类型", request.target_kind); addFact("训练方案", task.recipe_id); addFact("数据导入方式", task.data_adapter_id || request.data_adapter); if (build) addFact("扩展请求", build.request_id || build.recipe_request_id);
  if (task.staged_assets?.latest) addFact("构建样例", `${task.staged_assets.latest.status} · ${task.staged_assets.latest.report?.file_count || 0} 份样例`);
  if (recipeBuild) { addFact("扩展构建记录", `${recipeBuild.status} · ${shortId(recipeBuild.attempt_id)}`); addFact("候选摘要", recipeBuild.candidate_digest ? shortId(recipeBuild.candidate_digest) : "未生成"); addFact("验证摘要", recipeBuild.validation_digest ? shortId(recipeBuild.validation_digest) : "未生成"); }
  if (task.recipe_version_id) addFact("方案版本", shortId(task.recipe_version_id));
  ui.scaffoldRecipeButton.hidden = Boolean(task.model_binding || recipeBuild) || task.capability_status !== "needs_recipe" || task.control?.next_action?.id === "stage_recipe_samples";
  ui.scaffoldRecipeButton.textContent = build?.status === "scaffold_ready" ? "重新下载适配器参考包" : "下载适配器参考包";
  if (ui.recipeExtensionDetails) ui.recipeExtensionDetails.hidden = ui.scaffoldRecipeButton.hidden;
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
  if (!view) { ui.trainingPlanState.textContent = blockedLicense ? "许可证阻断" : needsMapping ? "等待入口映射" : blockedAnalysis ? "分析风险阻断" : "未生成"; ui.trainingPlanSummary.textContent = blockedLicense ? "静态分析可以查看，但当前许可证策略未放行训练计划、环境或执行。" : needsMapping ? "请先在仓库静态分析中确认训练入口；系统会创建新的可追溯分析 revision，再允许生成计划。" : blockedAnalysis ? "仓库静态分析仍有未解决风险；请先审阅证据或更换来源，不能绕过分析生成计划。" : entries.length ? `将以 ${entries[0].path} 作为计划入口；生成后仍需你核对并批准 digest。` : "当前来源的训练入口仍需核查。可以继续完善数据与评测要求，再由 AI 查证入口或比较其他实现路线。"; return; }
  const plan = view.plan || {}; const status = view.stale ? "已过期" : view.effective_status === "approved" ? "已批准" : view.effective_status === "awaiting_approval" ? "待批准" : statusLabel(view.effective_status);
  ui.trainingPlanState.textContent = status; ui.trainingPlanSummary.textContent = view.stale ? "任务规格或模型来源已经变化，旧计划和审批仍保留但不能继续使用。" : "计划已绑定当前来源和分析；批准只对下面显示的精确 digest 生效。";
  appendFact(ui.trainingPlanFacts, "Revision", `r${plan.revision || "—"} · ${shortId(plan.training_plan_revision_id)}`); appendFact(ui.trainingPlanFacts, "入口", (plan.entrypoint?.argv || []).join(" "), { code: true }); appendFact(ui.trainingPlanFacts, "资源预算", `${formatBytes(plan.resource_budget?.ram_bytes)} RAM · ${formatBytes(plan.resource_budget?.disk_bytes)} 磁盘`); appendFact(ui.trainingPlanFacts, "执行边界", `${plan.execution_policy?.backend || "—"} · CPU-only`); appendFact(ui.trainingPlanFacts, "Plan Digest", plan.plan_sha256, { code: true });
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
  clear(ui.hfCompatibilityChecks); Object.entries(compatibility.checks || {}).forEach(([name, passed]) => { const item = document.createElement("span"); item.dataset.passed = String(passed === true); item.append(createUiIcon(passed === true ? "check" : "alert"), document.createTextNode(`${passed === true ? "通过" : "未通过"} · ${HF_CHECK_LABELS[name] || name}`)); ui.hfCompatibilityChecks.append(item); });
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
  ui.datasetCard.hidden = false;
  const report = task.dataset_report; const [count, summary] = datasetDetail(task); ui.datasetCount.textContent = report ? count : "未导入";
  ui.datasetSummary.textContent = report ? `${summary} · ${report.risks?.[0]?.message || "数据体检完成"}` : "导入图片或音频类别 ZIP、或 CSV；格式需符合当前训练方案的数据导入要求。";
  const recipeSamplesNeeded = task.control?.next_action?.id === "stage_recipe_samples";
  const availability = datasetUploadAvailability(task);
  ui.datasetButtonLabel.textContent = recipeSamplesNeeded ? "上传构建样例" : "导入数据";
  ui.datasetButton.title = recipeSamplesNeeded ? "上传按类别整理的 PCM WAV 样例 ZIP" : availability.reason || "导入图片、音频 ZIP 或 CSV";
  ui.inspectorDatasetButton.textContent = report ? "替换并重新体检" : "导入数据集"; ui.inspectorDatasetButton.title = availability.reason || "导入图片、音频 ZIP 或 CSV"; ui.datasetButton.disabled = recipeSamplesNeeded ? false : availability.blocked; ui.inspectorDatasetButton.disabled = availability.blocked;
  renderComposerAttachment();
  renderMaterialControls();
}
function gateEntries(gates, declared = null) { if (declared && typeof declared === "object") return Object.entries(declared).filter(([, gate]) => Number.isFinite(gate?.threshold) && ["lte", "gte"].includes(gate.operator)).map(([name, gate]) => [gate.threshold, `${name}${gate.operator === "lte" ? " 上限" : " 下限"}`]); return "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates ? [[gates.clean_test_mae_max, "MAE 上限"], [gates.clean_test_rmse_max, "RMSE 上限"], [gates.clean_test_r2_min, "R² 下限"]] : [[gates.clean_test_accuracy_min, "Accuracy"], [gates.clean_test_macro_f1_min, "Macro-F1"], [gates.clean_test_worst_class_recall_min, "最差类 Recall"]]; }
function renderContract(task) {
  const contract = task.contract; ui.contractCard.hidden = !contract; if (!contract) return; ui.contractState.textContent = task.contract_confirmed ? "已冻结" : "待确认"; clear(ui.gateGrid);
  const gates = contract.release_gates || {}; const regressionGates = "clean_test_mae_max" in gates || "clean_test_rmse_max" in gates; const regressionBasis = regressionGates ? contract.release_gate_basis : null;
  const targetColumn = regressionBasis?.target_column || task.dataset_report?.target_column || "目标列";
  gateEntries(gates, contract.execution_spec?.evaluation?.gates).forEach(([value, label]) => { const cell = document.createElement("div"); const b = document.createElement("b"); b.textContent = typeof value === "number" ? contract.execution_spec ? String(value) : value.toFixed(2) : "—"; const span = document.createElement("span"); span.textContent = regressionBasis && (label.startsWith("MAE") || label.startsWith("RMSE")) ? `${label} · 「${targetColumn}」原始单位` : label; cell.append(b, span); ui.gateGrid.append(cell); });
  if (regressionBasis) {
    const improvement = Number(regressionBasis.required_improvement_fraction); const improvementText = Number.isFinite(improvement) ? `，默认要求至少改善 ${Math.round(improvement * 100)}%` : "";
    const basis = document.createElement("p"); basis.className = "gate-basis"; basis.textContent = `系统按当前数据的常数均值基线建议${improvementText}，仍需你确认。`; ui.gateGrid.append(basis);
  }
  ui.confirmations.hidden = false;
  ui.confirmations.querySelectorAll("input").forEach((input) => { input.disabled = true; input.checked = task.confirmations?.[input.dataset.confirm] === true; });
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
function metricEntries(result) { const clean = result?.metrics?.clean_test || {}; if (result?.recipe === "generic-isolated-execution" || Object.keys(clean).some(key => !["mae", "rmse", "r2", "accuracy", "macro_f1", "worst_class_recall"].includes(key))) return Object.entries(clean).filter(([, value]) => Number.isFinite(value)).map(([label, value]) => [value, label]); return "mae" in clean || "rmse" in clean || "r2" in clean ? [[clean.mae, "MAE"], [clean.rmse, "RMSE"], [clean.r2, "R²"]] : [[clean.accuracy, "Accuracy"], [clean.macro_f1, "Macro-F1"], [clean.worst_class_recall, "最差类 Recall"]]; }
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
  const order = ["macro_f1", "accuracy", "worst_class_recall", "mae", "rmse", "r2"]; const entries = [...new Set([...order, ...Object.keys(values || {})])].filter((key) => Number.isFinite(values?.[key])).slice(0, 3);
  return entries.map((key) => `${key} ${values[key].toFixed(3)}`).join(" · ") || "没有可展示的验证指标";
}
function primaryCandidateScore(values, primaryMetric = null) { const entry = [primaryMetric, "macro_f1", "accuracy", "r2", "mae", "rmse", ...Object.keys(values || {})].filter(Boolean).find((key) => typeof values?.[key] === "number"); return entry ? values[entry].toFixed(3) : "—"; }
function renderCandidateComparison(result) {
  const candidates = Object.entries(result.metrics?.validation_candidates || {}); clear(ui.candidateList); ui.candidateCount.textContent = String(candidates.length);
  ui.candidatePolicy.textContent = result.metrics?.test_set_used_for_selection === true ? "警告：当前指标声明测试集参与了选模，证据会被标记为污染。" : `选模策略：${result.metrics?.selection_policy || "validation_only"}；独立测试集不用于候选选择。`;
  if (!candidates.length) { appendEmpty(ui.candidateList, "本轮尚无候选对比证据。"); return; }
  candidates.forEach(([name, values]) => { const row = document.createElement("div"); row.className = "candidate-row"; row.dataset.selected = String(name === result.metrics?.selected_model); const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = `${name}${name === result.metrics?.selected_model ? " · 已选" : ""}`; const detail = document.createElement("small"); detail.textContent = metricSummary(values); const score = document.createElement("em"); score.textContent = primaryCandidateScore(values, state.task?.contract?.execution_spec?.evaluation?.primary_metric); copy.append(title, detail); row.append(copy, score); ui.candidateList.append(row); });
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
function sampleTypeForRecipe(recipe) { return { "image-folder-classification": "image", "audio-keyword-classification": "audio", "tabular-regression": "tabular", "tabular-classification": "tabular" }[recipe] || null; }
function genericInferenceSpec(task = state.task) {
  const result = task?.current_result;
  if (result?.recipe !== "generic-isolated-execution") return null;
  const declaration = result.inference || (task.contract?.recipe === result.recipe ? task.contract.execution_spec?.inference : null);
  return declaration && Array.isArray(declaration.extensions) && Number.isInteger(declaration.max_bytes) ? declaration : null;
}
function sampleTypeForTask(task = state.task) { return genericInferenceSpec(task) ? "generic" : sampleTypeForRecipe(task?.current_result?.recipe); }
function genericUsesFields(spec) { return Boolean(spec?.schema && (spec.extensions.includes(".json") || spec.schema.type === "string" && spec.extensions.includes(".txt"))); }
function genericInputPayload(value, spec) {
  const plainText = typeof value === "string" && spec.extensions.includes(".txt");
  const body = plainText ? value : JSON.stringify(value);
  if (typeof body !== "string" || new TextEncoder().encode(body).length > spec.max_bytes) throw new Error("输入内容超过样本大小限制或格式无效");
  return { body, filename: plainText ? "new-sample.txt" : "new-sample.json", contentType: plainText ? "text/plain; charset=utf-8" : "application/json" };
}
function genericInputEditor(container, schema) {
  const build = (shape = {}, label = "新样本", required = true, depth = 0) => {
    const type = shape.type || (shape.properties ? "object" : "string");
    if (type === "object" && shape.properties && depth < 4 && Object.keys(shape.properties).length <= 64) {
      const group = document.createElement("fieldset"); group.className = "generic-input-group"; const legend = document.createElement("legend"); legend.textContent = shape.title || label; group.append(legend);
      const fields = Object.entries(shape.properties).map(([key, field]) => [key, build(field, key, (shape.required || []).includes(key), depth + 1)]);
      fields.forEach(([, field]) => group.append(field.element));
      return { element: group, read: () => Object.fromEntries(fields.flatMap(([key, field]) => { const value = field.read(); return value === undefined ? [] : [[key, value]]; })) };
    }
    const wrap = document.createElement("label"); wrap.className = "generic-input-field"; const title = document.createElement("span"); title.textContent = `${shape.title || label}${required ? " *" : ""}`; wrap.append(title);
    const choices = Array.isArray(shape.enum) ? shape.enum : type === "boolean" ? [true, false] : null;
    const input = document.createElement(choices ? "select" : ["array", "object", "string"].includes(type) ? "textarea" : "input"); input.setAttribute("aria-label", shape.title || label);
    if (choices) { const empty = document.createElement("option"); empty.value = ""; empty.textContent = "请选择"; input.append(empty); choices.forEach((value, index) => { const option = document.createElement("option"); option.value = String(index); option.textContent = typeof value === "string" ? value : JSON.stringify(value); input.append(option); }); }
    else if (["number", "integer"].includes(type)) { input.type = "number"; input.step = type === "integer" ? "1" : "any"; }
    else { input.rows = type === "string" ? 2 : 3; input.placeholder = ["array", "object"].includes(type) ? `输入 ${type === "array" ? "数组" : "对象"} JSON` : shape.description || ""; }
    if (shape.default !== undefined) input.value = choices ? String(choices.findIndex(value => JSON.stringify(value) === JSON.stringify(shape.default))) : typeof shape.default === "string" ? shape.default : JSON.stringify(shape.default);
    wrap.append(input); if (shape.description) { const hint = document.createElement("small"); hint.textContent = shape.description; wrap.append(hint); }
    return { element: wrap, read: () => {
      const raw = String(input.value || ""); if (!raw.trim()) { if (required) throw new Error(`请填写${shape.title || label}`); return undefined; }
      let value = choices ? choices[Number(raw)] : ["number", "integer"].includes(type) ? Number(raw) : ["array", "object"].includes(type) ? JSON.parse(raw) : raw;
      if (value === undefined || (["number", "integer"].includes(type) && (!Number.isFinite(value) || (type === "integer" && !Number.isInteger(value))))) throw new Error(`${label}的值不符合${type}格式`);
      if (type === "array" && !Array.isArray(value) || type === "object" && (!value || Array.isArray(value) || typeof value !== "object")) throw new Error(`${label}的 JSON 类型不正确`);
      if (typeof value === "number" && (Number.isFinite(shape.minimum) && value < shape.minimum || Number.isFinite(shape.maximum) && value > shape.maximum)) throw new Error(`${label}超出声明范围`);
      return value;
    } };
  };
  const form = build(schema); container.append(form.element); return form.read;
}
function prepareGenericTrialFields(spec) {
  const key = JSON.stringify([state.selectedTaskId, state.task?.current_result?.run_id, spec]);
  if (state.genericTrialSchemaKey === key && state.genericTrialRead) return;
  clear(ui.genericSampleFields); state.genericTrialSchemaKey = key; state.genericTrialRead = genericInputEditor(ui.genericSampleFields, spec.schema);
}
function checkGenericInputFile(file, spec) {
  if (!file || !spec.extensions.some(extension => file.name.toLowerCase().endsWith(extension))) throw new Error(`请选择${spec.extensions.join("、")}格式的新样本`);
  if (file.size > spec.max_bytes) throw new Error(`新样本超过${formatBytes(spec.max_bytes)}限制`);
}
function sampleOutputUrl(check, artifact, taskId = state.selectedTaskId, runId = state.task?.current_result?.run_id) {
  if (check?.status !== "passed" || check.task_id !== taskId || check.run_id !== runId || !check.check_id || !artifact?.name || !/^[a-f0-9]{64}$/.test(artifact.sha256 || "") || !Number.isInteger(artifact.bytes) || artifact.bytes < 0) return null;
  if (typeof artifact.url !== "string" || !artifact.url.startsWith("/") || artifact.url.startsWith("//") || artifact.url.includes("\\")) return null;
  try {
    const url = new URL(artifact.url, location.origin); if (url.origin !== location.origin || url.search || url.hash) return null;
    const prefix = `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inferences/${encodeURIComponent(check.check_id)}/files/`;
    if (!url.pathname.startsWith(prefix)) return null;
    const parts = url.pathname.slice(prefix.length).split("/").map(part => decodeURIComponent(part));
    if (parts.some(part => !part || part === "." || part === ".." || /[\/\\%\x00-\x1f\x7f]/.test(part)) || parts.join("/") !== artifact.name) return null;
    return url.pathname;
  } catch (_error) { return null; }
}
function predictionFieldLabel(key) {
  const labels = { text: "输入文字", sample_rate: "采样率（Hz）", duration_seconds: "时长（秒）", count: "记录数", store_id: "门店", date: "日期", predicted_sales: "预测销量", prediction: "预测值", query_id: "查询", document_id: "文档", score: "得分", rank: "名次", context_source: "历史数据来源", context_tail_end: "历史数据截止日期", context_staleness_days: "历史数据滞后（天）" };
  return labels[key] || key.replaceAll("_", " ");
}
function predictionDisplayValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : String(value);
}
function renderPredictionValue(prediction, target) {
  if (!prediction || typeof prediction !== "object") {
    const value = document.createElement("p"); value.className = "sample-prediction"; value.textContent = predictionDisplayValue(prediction); target.append(value); return;
  }
  const facts = document.createElement("dl"); facts.className = "prediction-facts";
  Object.entries(prediction).slice(0, 24).forEach(([key, value]) => {
    if (value === null || typeof value === "object" || ["wav", "model_route"].includes(key)) return;
    const row = document.createElement("div"), label = document.createElement("dt"), text = document.createElement("dd");
    label.textContent = Array.isArray(prediction) ? `预测值 ${Number(key) + 1}` : predictionFieldLabel(key); text.textContent = predictionDisplayValue(value); row.append(label, text); facts.append(row);
  });
  if (facts.children.length) target.append(facts);
  const records = Array.isArray(prediction) && prediction.every(row => row && typeof row === "object" && !Array.isArray(row)) ? prediction : Object.values(prediction).find(value => Array.isArray(value) && value.length && value.every(row => row && typeof row === "object" && !Array.isArray(row)));
  if (records?.length) {
    const keys = [...new Set(records.slice(0, 50).flatMap(row => Object.keys(row)))].filter(key => records.some(row => row[key] !== null && typeof row[key] !== "object")).slice(0, 8);
    const wrapper = document.createElement("div"); wrapper.className = "prediction-table-scroll";
    const table = document.createElement("table"), caption = document.createElement("caption"), head = document.createElement("thead"), header = document.createElement("tr"), body = document.createElement("tbody");
    caption.textContent = `输出记录 · ${records.length} 条${records.length > 50 ? "（先显示 50 条）" : ""}`; table.append(caption);
    keys.forEach(key => { const th = document.createElement("th"); th.scope = "col"; th.textContent = predictionFieldLabel(key); header.append(th); }); head.append(header); table.append(head);
    records.slice(0, 50).forEach(record => { const tr = document.createElement("tr"); keys.forEach(key => { const td = document.createElement("td"); td.textContent = record[key] === undefined || record[key] === null || typeof record[key] === "object" ? "—" : predictionDisplayValue(record[key]); tr.append(td); }); body.append(tr); });
    table.append(body); wrapper.append(table); target.append(wrapper);
  }
  const details = document.createElement("details"), heading = document.createElement("summary"), raw = document.createElement("pre"); heading.textContent = "输出数据详情"; raw.className = "sample-prediction"; raw.textContent = JSON.stringify(prediction, null, 2); details.append(heading, raw); target.append(details);
}
function renderSamplePrediction(check, target) {
  renderPredictionValue(check.prediction, target);
  for (const artifact of (check.artifacts || []).slice(0, 12)) {
    const url = sampleOutputUrl(check, artifact); if (!url) continue;
    const figure = document.createElement("figure"); figure.className = "sample-output";
    let media;
    if (/^audio\/(?:wav|x-wav|mpeg|mp3|ogg|flac|x-flac|mp4|aac|webm)$/.test(artifact.media_type || "")) { media = document.createElement("audio"); media.controls = true; media.preload = "metadata"; }
    else if (/^image\/(?:png|jpeg|gif|webp|bmp|avif)$/.test(artifact.media_type || "")) { media = document.createElement("img"); media.alt = `模型输出：${artifact.name}`; media.loading = "lazy"; media.decoding = "async"; }
    else if (/^video\/(?:mp4|webm|ogg)$/.test(artifact.media_type || "")) { media = document.createElement("video"); media.controls = true; media.preload = "metadata"; media.playsInline = true; }
    if (media) { media.src = url; figure.append(media); }
    const caption = document.createElement("figcaption"), download = document.createElement("a"); download.href = url; download.download = artifact.name.split("/").at(-1); download.textContent = `${artifact.name} · ${formatBytes(artifact.bytes)}`; caption.append(download); figure.append(caption); target.append(figure);
  }
}
function renderSampleTrials(result) {
  const sampleType = sampleTypeForTask(state.task); const generic = genericInferenceSpec(state.task); const genericFields = genericUsesFields(generic); const unavailable = state.evidenceErrors.samples === "capability_unavailable"; const ready = result.status === "completed" && Boolean(sampleType) && !unavailable; clear(ui.sampleInferenceList);
  if (!ui.sampleTrialRunButton.dataset.busy) ui.sampleTrialRunButton.textContent = "交给协调器试跑";
  ui.sampleJsonField.hidden = sampleType !== "tabular"; ui.sampleTrialSelectButton.hidden = sampleType === "tabular" || genericFields;
  ui.genericSampleFields.hidden = !genericFields; if (genericFields) prepareGenericTrialFields(generic); ui.sampleTrialRunButton.disabled = !ready;
  ui.sampleTrialInput.accept = generic ? generic.extensions.join(",") : sampleType === "image" ? "image/png,image/jpeg,image/webp,image/bmp" : sampleType === "audio" ? ".wav,audio/wav" : "";
  if (unavailable) { ui.sampleTrialState.textContent = "API 不可用"; ui.sampleTrialSummary.textContent = "后端没有接通 task-owned sample-inferences API；页面不会模拟推理结果。"; ui.sampleTrialRunButton.disabled = true; }
  else if (!sampleType) { ui.sampleTrialState.textContent = "不可用"; ui.sampleTrialSummary.textContent = `当前训练方案 ${result.recipe || "未识别"} 还不能试跑原始样本。`; ui.sampleTrialRunButton.disabled = true; }
  else if (result.status !== "completed") { ui.sampleTrialState.textContent = "等待完成"; ui.sampleTrialSummary.textContent = "只有完成且通过产物完整性检查的 Run 才能执行真实新样本试跑。"; }
  else { const selected = ui.sampleTrialInput.files?.[0]; ui.sampleTrialState.textContent = selected ? "样本已选择" : state.sampleInferences.length ? `${state.sampleInferences.length} 次记录` : "未试跑"; ui.sampleTrialSummary.textContent = genericFields ? "按已验证方案的输入字段填写新样本；暂存后再批准一次真实推理。" : generic ? `选择${generic.extensions.join("、")}格式的新样本，最大 ${formatBytes(generic.max_bytes)}；暂存后再批准推理。` : sampleType === "tabular" ? "输入一行与训练特征列匹配的 JSON；暂存后由协调器申请一次授权，再交给评测专家执行。" : selected ? `已选择 ${selected.name} · ${formatBytes(selected.size)}；下一步会先请求授权。` : `选择一份新的${sampleType === "image" ? "图片" : "PCM WAV 音频"}；原始内容不会进入对话或证据报告。`; }
  if (!state.sampleInferences.length) { appendEmpty(ui.sampleInferenceList, "尚无真实新样本试跑记录。"); return; }
  [...state.sampleInferences].reverse().slice(0, 6).forEach((check) => { const row = document.createElement("div"); row.className = "sample-inference-row"; const copy = document.createElement("div"); copy.className = "sample-inference-content"; const title = document.createElement("b"); title.textContent = check.sample?.source_name || check.check_id; const detail = document.createElement("small"); detail.textContent = check.status === "passed" ? `${Number(check.elapsed_ms || 0).toFixed(1)} ms · 样本 SHA ${shortId(check.sample?.sha256)}` : check.reason || "后端阻断了该样本"; const status = document.createElement("em"); status.dataset.state = check.status; status.textContent = check.status === "passed" ? "试跑完成" : "已阻断"; copy.append(title, detail); if (check.status === "passed") renderSamplePrediction(check, copy); row.append(copy, status); ui.sampleInferenceList.append(row); });
}
function renderArtifactBundles(result) {
  const completed = result.status === "completed"; ui.buildArtifactBundleButton.disabled = !completed || !state.runtimeReady || state.evidenceErrors.bundles === "capability_unavailable"; clear(ui.artifactBundleList);
  ui.artifactBundleState.textContent = state.artifactBundles.length ? `${state.artifactBundles.length} 个` : completed ? "尚未生成" : "等待完成";
  ui.artifactBundleSummary.textContent = state.evidenceErrors.bundles ? `交付包读取失败：${state.evidenceErrors.bundles}` : "交付包由训练协调器在你确认后生成；下载也需要单独确认，不会绕过当前任务的授权。";
  if (!state.artifactBundles.length) { appendEmpty(ui.artifactBundleList, completed ? "尚无交付包。你发起请求后，协调器会先说明范围并征求确认。" : "训练完成后才能请求生成交付包。"); return; }
  [...state.artifactBundles].reverse().forEach((bundle) => { const row = document.createElement("div"); row.className = "artifact-bundle-row"; const copy = document.createElement("span"); const title = document.createElement("b"); title.textContent = bundle.bundle_id; const detail = document.createElement("small"); detail.textContent = `${formatBytes(bundle.archive?.size_bytes)} · SHA ${shortId(bundle.archive?.sha256)}`; const download = document.createElement("button"); download.type = "button"; download.className = "artifact-bundle-action"; download.textContent = "请求下载"; download.disabled = !state.runtimeReady; download.title = state.runtimeReady ? "交给训练协调器核对并发起单独下载确认" : "训练协调器未连接，不能发起下载授权"; download.addEventListener("click", () => requestArtifactBundleDownload(result, bundle)); const meta = document.createElement("span"); meta.className = "artifact-bundle-meta"; [[bundle.release_ready ? "release-ready" : "非发布结论"], [bundle.manifest?.privacy_boundary?.raw_data_included === false ? "未打包原始数据文件" : "检查隐私边界"], [`${bundle.manifest?.files?.length || 0} 个文件`]].forEach(([value]) => { const item = document.createElement("i"); item.textContent = value; meta.append(item); }); copy.append(title, detail); row.append(copy, download, meta); ui.artifactBundleList.append(row); });
}
async function loadRunEvidence(task) {
  const taskId = task.task_id; const runId = task.current_run_id; if (!taskId || !runId || task.current_result?.status !== "completed") return;
  const base = `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}`;
  const [evaluation, samples, bundles] = await Promise.allSettled([request(`${base}/evaluation-report`), request(`${base}/sample-inferences`), request(`${base}/artifact-bundles`)]);
  if (state.selectedTaskId !== taskId || state.evidenceRunId !== runId) return;
  const previousSignature = state.evidenceLoaded ? runEvidenceSignature() : null;
  if (evaluation.status === "fulfilled") { state.evaluationReport = evaluation.value.evaluation_report; delete state.evidenceErrors.evaluation; } else state.evidenceErrors.evaluation = [404, 405].includes(evaluation.reason.status) ? "capability_unavailable" : evaluation.reason.message;
  if (samples.status === "fulfilled") { state.sampleInferences = samples.value.sample_inferences || []; delete state.evidenceErrors.samples; } else state.evidenceErrors.samples = [404, 405].includes(samples.reason.status) ? "capability_unavailable" : samples.reason.message;
  if (bundles.status === "fulfilled") { state.artifactBundles = bundles.value.artifact_bundles || []; delete state.evidenceErrors.bundles; } else state.evidenceErrors.bundles = [404, 405].includes(bundles.reason.status) ? "capability_unavailable" : bundles.reason.message;
  state.evidenceLoaded = true; state.evidenceLoadedAt = Date.now();
  if (previousSignature === runEvidenceSignature()) return;
  if (state.task) { renderResult(state.task); renderConversation(true); }
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
  if (!response?.inference_input?.inference_input_id || !response?.inference_input?.sha256 || response.inference_input.task_id !== taskId || response.inference_input.run_id !== runId) throw new Error("样本已上传，但后端没有返回属于当前任务与运行的可验证输入对象。");
  if (state.selectedTaskId !== taskId || state.task?.current_result?.run_id !== runId) throw new Error("已切换任务或运行，样本保留在原任务中；没有续接当前对话。");
  return response.inference_input;
}
async function continueWithInferenceInput(inferenceInput, checkpoint = currentHumanCheckpoint(state.conversation)) {
  if (inferenceInput.task_id !== state.selectedTaskId || inferenceInput.run_id !== state.task?.current_result?.run_id) throw new Error("样本不属于当前任务与运行，已停止续接。");
  if (inferenceInputQuestionCheckpoint(checkpoint)) {
    if (currentHumanCheckpoint(state.conversation)?.rpc_id !== checkpoint.rpc_id) throw new Error("原样本问题已经变化，样本已保留；请按当前对话继续。");
    const answers = inferenceInputCheckpointAnswers(checkpoint, inferenceInput);
    await postQuestionAnswers(checkpoint, answers);
    showTransientNotice("新样本已安全暂存，训练协调器会先请求一次明确授权，再交给评测专家试跑。", "ok");
    await refreshSelected({ force: true });
    return;
  }
  await submitMessage(`我已经选择了一份未参与训练的新样本（输入对象 ${inferenceInput.inference_input_id}，摘要 ${inferenceInput.sha256}）。请先核对它属于当前任务和运行，再申请一次试跑授权；授权后交给评测与交付专家执行，不要直接运行。`);
}
async function runSampleTrial() {
  const taskId = state.selectedTaskId; const result = state.task?.current_result; const runId = result?.run_id; const sampleType = sampleTypeForTask(state.task); const generic = genericInferenceSpec(state.task); if (!taskId || !runId || result.status !== "completed" || !sampleType) return;
  let body; let filename; let contentType;
  if (sampleType === "tabular" && !ui.sampleTrialJson.value.trim()) { showNotice("请先填入一行新样本，字段名与训练时的特征列一致。"); return; }
  if (genericUsesFields(generic)) { try { ({ body, filename, contentType } = genericInputPayload(state.genericTrialRead(), generic)); } catch (error) { showNotice(error.message); return; } }
  else if (sampleType === "tabular") { try { const value = JSON.parse(ui.sampleTrialJson.value); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 必须是一行对象"); body = JSON.stringify(value); filename = "new-sample.json"; contentType = "application/json"; } catch (error) { showNotice(`请输入有效的一行 JSON：${error.message}`); return; } }
  else { const file = ui.sampleTrialInput.files?.[0]; if (generic) { try { checkGenericInputFile(file, generic); } catch (error) { showNotice(error.message); return; } } if (!file) { showNotice("请先选择一份新的图片或 WAV 音频样本。"); return; } body = file; filename = file.name; contentType = file.type || (sampleType === "audio" ? "audio/wav" : "application/octet-stream"); }
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
  const taskId = state.selectedTaskId; const runId = result?.run_id; const bundleId = bundle?.bundle_id; const digest = bundle?.manifest_sha256;
  if (!taskId || !runId || !bundleId || !EVIDENCE_SHA256.test(String(digest || ""))) { showNotice("交付包引用缺少可核对身份，已停止下载请求。", "error"); return; }
  const ref = { type: "artifact_bundle", id: bundleId, task_id: taskId, run_id: runId, digest };
  try {
    const payload = await request(objectRefEndpoint(ref));
    if (state.selectedTaskId !== taskId || !returnedObjectMatchesRef(ref, payload)) { showNotice("服务端返回的交付包身份与点击对象不一致，已停止下载请求。", "error"); return; }
    const exactBundle = payload.artifact_bundle;
    closeInspector();
    await submitMessage(`请下载当前运行 ${exactBundle.run_id} 的交付包 ${exactBundle.bundle_id}。请先核对交付包摘要与完整性，并在真正下载前让我单独确认；不要复用构建授权。`);
  } catch (error) { showNotice(`交付包身份复核失败：${error.message}`, "error"); }
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
  return { items: [], pending: [], running: false };
}
function taskEvidenceLedger(task) {
  if (isConversationDraft(state.conversationRecord, task)) return [];
  const ledger = []; const revisions = state.taskSpecRevisions.length ? state.taskSpecRevisions : task.task_spec ? [task.task_spec] : [];
  if (state.conversation && !state.conversation.session_id) {
    ledger.push({
      kind: "system_record",
      source: "persisted_task_projection",
      status: "warning",
      evidenceKey: `unsent:${task.task_id}`,
      label: "任务已保存，消息尚未发给 AI",
      detail: "业务目标仍是任务草稿，不代表消息已经发送。请在下方发送或使用“发送任务目标”继续。",
      time: task.created_at_utc,
    });
  }
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
  integration_pending: { eyebrow: "训练方案", title: "继续准备训练方案", badge: "准备中", summary: "已有目标和材料会用于准备实现路线、数据要求、资源预算与验证步骤。执行条件核验后再确认运行。", toggle: "查看方案" },
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
function partitionWorkspaceResultRefs(task, refs) {
  const runId = task?.current_run_id || task?.current_result?.run_id || null;
  const current = [], historical = [];
  refs.forEach((ref) => {
    const belongsToRun = ["evaluation_report", "artifact_bundle", "inference_input", "sample_inference_check"].includes(ref.type) || Boolean(ref.run_id);
    (belongsToRun && (!runId || ref.run_id !== runId) ? historical : current).push(ref);
  });
  return { current, historical };
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
  const label = ConversationView?.ROLE_LABELS?.[item.role?.role_id] || item.role?.label || roleLabel(item.role?.role_id);
  const mark = document.createElement("i"); mark.textContent = String(label).slice(0, 2);
  const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = label; const summary = document.createElement("p"); summary.textContent = item.assignment?.summary || "已收到协调器的结构化委派。"; copy.append(title, summary);
  const status = document.createElement("em"); status.textContent = workspaceWorkStatus(item.status); card.append(mark, copy, status); ui.workspaceTeamList.append(card);
}
function renderWorkspaceCoordinator(projection) {
  const action = projection.current_actions?.find((item) => item.status === "running") || projection.current_actions?.at(-1);
  const card = document.createElement("article"); card.className = "workspace-agent-card"; card.dataset.status = action?.status || "running";
  const mark = document.createElement("i"); mark.textContent = "AI"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = "训练协调器"; const summary = document.createElement("p"); summary.textContent = action ? actionTitle(action) : "正在理解任务并决定是否需要训练团队协作。"; copy.append(title, summary); const status = document.createElement("em"); status.textContent = action ? actionStatusLabel(action) : "处理中"; card.append(mark, copy, status); ui.workspaceTeamList.append(card);
}
function catalogGapObjectRef(ref, task = state.task) {
  if (ref?.type !== "blocker" || !task?.task_id || ref.task_id !== task.task_id || !ref.id || !ref.digest) return false;
  const records = [...(task.blockers || []), ...(task.control?.blocked_by || [])];
  return records.some(record => (record.blocker_id || record.blocker_evidence_id) === ref.id
    && (record.content_digest || record.blocker_digest) === ref.digest
    && (!record.task_id || record.task_id === ref.task_id)
    && ["recipe_unavailable", "verified_recipe_unavailable"].includes(record.code));
}
function renderWorkspaceResultRef(ref, target = ui.workspaceResultList, historical = false) {
  const button = document.createElement("button"); button.type = "button"; button.className = "workspace-result-card";
  const catalogGap = catalogGapObjectRef(ref);
  const mark = document.createElement("i"); mark.textContent = catalogGap ? "·" : "✓"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = catalogGap ? "方案匹配记录" : ref.label || ({ model_source_search: "模型候选", dataset_report: "数据体检", evaluation_report: "评测报告", artifact_bundle: "交付产物" })[ref.type] || ref.type; const summary = document.createElement("p"); summary.textContent = `${historical ? "历史运行" : ref.run_id ? "当前运行" : "任务记录"}${ref.run_id ? ` ${shortId(ref.run_id)}` : ""} · ${shortId(ref.id)}`; copy.append(title, summary); const action = document.createElement("em"); action.textContent = "打开"; button.append(mark, copy, action); button.addEventListener("click", () => openObjectRef(ref)); target.append(button);
}
function workspaceEvaluationOutcome(task) {
  if (!InteractionShell?.deriveEvaluationOutcome) return { ready: false, comparison: null, decision: null };
  const result = task?.current_result; const fresh = state.evidenceRunId === result?.run_id ? state.evaluationReport : null;
  return InteractionShell.deriveEvaluationOutcome({ task, evaluation: fresh || result?.evaluation_report || null });
}
function workspaceMetricValue(value) { return Number.isFinite(value) ? value.toFixed(3) : "—"; }
function renderWorkspaceDecision(outcome) {
  const section = document.createElement("section"); section.className = "workspace-evaluation-summary"; section.dataset.recommended = outcome.decision.recommended; section.dataset.interactionKind = "evaluation-verdict";
  const heading = document.createElement("header"); const headingCopy = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "可信评测"; const title = document.createElement("h4"); title.textContent = "模型对比与下一步"; headingCopy.append(kicker, title); const verdict = document.createElement("b"); verdict.dataset.state = outcome.release_ready ? "ready" : "blocked"; verdict.textContent = outcome.release_ready ? "可进入发布审阅" : statusLabel(outcome.conclusion); heading.append(headingCopy, verdict); section.append(heading);
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
function preparationProgressFacts(task) {
  const spec = task.task_spec || {}, plan = task.training_plan, binding = task.model_binding;
  const materialSummary = task.material_inspections || {};
  const records = state.materialsOwnerId === task.task_id ? (state.materialInspections || []).filter(item => item.owner_id === task.task_id) : [];
  const count = Number.isInteger(materialSummary.count) ? materialSummary.count : records.length;
  const latestStatus = materialSummary.latest_status || records[0]?.status;
  const searches = (state.modelSourceSearches || []).filter(item => item.base_spec_revision === task.current_spec_revision && (!item.task_id || item.task_id === task.task_id));
  const resource = task.resource_feasibility || {};
  return [
    { label: "目标", state: spec.business_goal ? "recorded" : "pending", text: spec.business_goal || "待明确影响方案的目标信息" },
    { label: "数据", state: task.dataset_id || count ? "recorded" : "pending", text: task.dataset_id ? `训练数据集已导入 · ${task.dataset_id}` : count ? `已保存 ${count} 份材料；最近一份${latestStatus === "rejected" ? "检查发现问题" : latestStatus === "inspected" ? "已完成材料检查" : "等待检查结果"}，训练数据尚未导入` : "可以先上传材料检查；数据规范可随方案一起准备" },
    { label: "方案", state: plan || binding || searches.length || task.recipe_id ? "recorded" : "pending", text: plan ? plan.stale ? "已保存计划需随目标更新" : plan.effective_status === "approved" ? "执行计划已批准；运行条件仍需核验" : "执行计划草案已记录，待核对" : binding ? binding.status === "stale" ? "模型来源需随目标更新" : "已固定模型来源，继续核查训练实现与验证方法" : searches.length ? `已有 ${searches.length} 次来源检索记录，继续比较适配性` : task.recipe_source === "qualified-execution" && task.current_execution_proposal_id ? `工程方案已启用 · ${task.current_execution_proposal_id}` : task.recipe_id ? `现成方案可复用 · ${task.recipe_id}` : "待准备训练路线与最小验证步骤" },
    { label: "资源", state: ["blocked_platform", "blocked_environment", "blocked_resources"].includes(resource.decision) ? "blocked" : resource.resource_fit_report || resource.resource_probe ? "recorded" : "pending", text: ["blocked_platform", "blocked_environment", "blocked_resources"].includes(resource.decision) ? resource.blockers?.[0]?.message || "当前资源条件有待处理的问题" : resource.decision === "fit" && resource.resource_fit_report ? "静态预算已匹配；运行环境仍需验证" : resource.decision === "fit_with_revision" ? "资源预算需要调整计划后重新确认" : resource.resource_probe ? "已记录资源探测，待与具体方案比较" : "随模型规模和训练方式评估资源需求" },
  ];
}
function renderPreparationProgress(task) {
  const target = ui.workspacePreparationProgress; if (!target) return;
  target.hidden = !task.task_spec || Boolean(task.current_run_id || task.current_result);
  if (target.hidden) { clear(target); return; }
  clear(target); const heading = document.createElement("h3"); heading.textContent = "方案准备进展"; const facts = document.createElement("dl");
  for (const fact of preparationProgressFacts(task)) { const row = document.createElement("div"); row.dataset.state = fact.state; const label = document.createElement("dt"), text = document.createElement("dd"); label.textContent = fact.label; text.textContent = fact.text; row.append(label, text); facts.append(row); }
  const note = document.createElement("small"); note.textContent = "这里记录准备事实；训练进度会在实际运行开始后展示。"; target.append(heading, facts, note);
}
function renderWorkspaceExperience(task, conversation, projection) {
  state.workspaceProjection = projection; const evaluationOutcome = workspaceEvaluationOutcome(task); const displayPhase = pendingExecutionIntegration(task, conversation, projection) ? "integration_pending" : projection.phase === "idle" && evaluationOutcome.ready ? "result_ready" : projection.phase; const basePhaseCopy = WORKSPACE_PHASE_COPY[displayPhase] || WORKSPACE_PHASE_COPY.idle; const phaseCopy = projection.phase === "executing" && projection.background?.coordinator_reply_complete ? { ...basePhaseCopy, title: "协调器已回复，后台任务仍在运行", badge: "后台运行中", summary: "协调器这一轮已经回复，但训练或评测尚未终态。最终指标与发布判断会等真实评测完成后再出现。" } : basePhaseCopy; const specialists = projectionSpecialists(projection); const activeSpecialists = activeProjectionSpecialists(projection); const refs = uniqueTaskObjectRefs(task, projection);
  ui.workspaceExperience.hidden = state.inspectorMode === "object-viewer"; ui.workspaceExperience.dataset.phase = displayPhase; ui.workspaceEyebrow.textContent = phaseCopy.eyebrow; ui.workspaceTitle.textContent = phaseCopy.title; ui.workspacePhaseBadge.textContent = phaseCopy.badge; ui.workspaceSummary.textContent = phaseCopy.summary; ui.workspaceToggleButton.querySelector("span").textContent = phaseCopy.toggle;
  renderPreparationProgress(task);
  clear(ui.workspaceTeamList); const showExecution = projection.phase === "executing" || specialists.length > 0; ui.workspaceTeam.hidden = !showExecution;
  if (showExecution) {
    const visibleSpecialists = activeSpecialists.length ? activeSpecialists : specialists;
    visibleSpecialists.forEach((specialist) => { const item = specialistWorkItem(projection, specialist); if (item) renderWorkspaceAgent({ ...item, status: specialist.status }); });
    if (!activeSpecialists.length && projection.phase === "executing") renderWorkspaceCoordinator(projection);
    ui.workspaceTeamCount.textContent = activeSpecialists.length ? `${activeSpecialists.length} 位协作中` : specialists.length ? `${specialists.length} 类专家记录` : "仅协调器";
    ui.workspaceTeamTitle.textContent = activeSpecialists.length ? "当前智能体协作" : specialists.length ? "本任务智能体记录" : "训练协调器正在处理";
  }
  clear(ui.workspaceResultList); const scopedRefs = partitionWorkspaceResultRefs(task, refs); scopedRefs.current.forEach((ref) => renderWorkspaceResultRef(ref));
  if (scopedRefs.historical.length) {
    const history = document.createElement("details"); history.className = "workspace-history";
    const summary = document.createElement("summary"); summary.textContent = `历史运行证据 · ${scopedRefs.historical.length} 项`;
    const note = document.createElement("p"); note.textContent = "下面属于先前的运行，不用于当前结果判断。原对象与身份仍可逐项打开核对。";
    const list = document.createElement("div"); scopedRefs.historical.forEach((ref) => renderWorkspaceResultRef(ref, list, true)); history.append(summary, note, list); ui.workspaceResultList.append(history);
  }
  const renderedEvaluation = evaluationOutcome.ready ? renderWorkspaceDecision(evaluationOutcome) : false; const resultCount = refs.length + (projection.result?.run_id ? 1 : 0) + (renderedEvaluation ? 1 : 0); ui.workspaceResults.hidden = resultCount === 0; ui.workspaceResultsTitle.textContent = renderedEvaluation ? "评测结果与下一步" : "本轮产生的结果"; ui.workspaceResultCount.textContent = scopedRefs.historical.length ? `${resultCount - scopedRefs.historical.length} 项 · 历史 ${scopedRefs.historical.length} 项` : `${resultCount} 项`;
  if (projection.result?.run_id) { const run = document.createElement("article"); run.className = "workspace-result-card"; const mark = document.createElement("i"); mark.textContent = "R"; const copy = document.createElement("div"); const title = document.createElement("b"); title.textContent = "训练运行"; const summary = document.createElement("p"); summary.textContent = shortId(projection.result.run_id); copy.append(title, summary); const status = document.createElement("em"); status.textContent = evaluationOutcome.ready ? "评测完成" : task.current_result?.status === "completed" ? "训练完成" : "已记录"; run.append(mark, copy, status); ui.workspaceResultList.prepend(run); }
  ui.workspaceTechnicalButton.textContent = renderedEvaluation ? "查看完整评测证据" : "查看训练详情";
  ui.workspaceTechnicalButton.dataset.context = renderedEvaluation ? "evaluation" : workspaceContextForProjection(projection);
  ui.workspaceTruthNote.textContent = renderedEvaluation ? "指标只来自当前 Run 的真实评测；发布、回滚或继续优化仍需人工确认。" : projection.result?.run_id ? "当前 Run 尚无匹配的可信评测，因此不展示指标或发布门。" : specialists.length ? "专家记录只来自当前任务已验证的父子会话；历史记录不会被描述为正在参与。" : "当前没有已验证专家委派；不会用角色配置冒充多智能体协作。";
  if (state.inspectorMode === "object-viewer") { ui.inspectorContent.hidden = true; return; }
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
  // The connection card already explains an unavailable AI service. Keep
  // observation diagnostics in task evidence without stacking a second alert.
  if (!state.runtimeReady) return;
  if (!state.conversationStreamDegraded && conversation.projection_health?.status !== "observation_degraded") return;
  const errors = conversation.projection_errors || [];
  const streamHealth = state.conversation?.stream_health || state.productRuntime?.agent?.stream_health || {};
  const streamLabel = ({ degraded: "连接异常", stopped: "已停止", connecting: "正在重连", healthy: "已连接", not_started: "未启动", not_observed: "未观测" })[streamHealth.status] || "状态未知";
  const card = document.createElement("aside"); card.className = "observation-health"; card.dataset.state = "observation_degraded"; card.setAttribute("role", "status"); card.setAttribute("aria-live", "polite");
  const mark = document.createElement("span"); mark.setAttribute("aria-hidden", "true"); mark.textContent = "!";
  const copy = document.createElement("div"); const title = document.createElement("b"); const detail = document.createElement("p"); const meta = document.createElement("small");
  title.textContent = "对话记录暂未完整同步";
  detail.textContent = "重新连接后再处理待办和确认结果。";
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
  const hasSession = Boolean(conversation?.session_id || state.conversation?.session_id);
  // A healthy conversation should look like a conversation. Agent identity and
  // delegation belong to the concrete AI turn that produced those actions,
  // not to a persistent banner above every message.
  if (state.runtimeReady && hasSession) return;
  if (state.runtimeReady && state.conversation == null) {
    const loading = document.createElement("p"); loading.className = "conversation-loading";
    loading.dataset.state = "loading"; loading.setAttribute("role", "status");
    loading.textContent = "正在恢复对话和执行记录…"; ui.messageList.append(loading); return;
  }
  const card = document.createElement("article"); card.className = "agent-surface-state"; card.dataset.state = state.runtimeReady ? "unsent" : "unavailable";
  const mark = document.createElement("span"); mark.textContent = state.runtimeReady ? "↗" : "!"; mark.setAttribute("aria-hidden", "true");
  const copy = document.createElement("div"); const title = document.createElement("b"); const detail = document.createElement("p");
  title.textContent = state.runtimeReady ? "任务已保存，消息尚未发送" : state.runtimeIssue === "provider" ? "模型服务尚未配置，对话已暂停" : state.runtimeIssue === "incompatible" ? "AI 服务版本不兼容，对话已暂停" : "AI 服务未连接，对话已暂停";
  detail.textContent = state.runtimeReady ? "目标已保存，发送后即可继续。" : state.runtimeIssue === "provider" ? "请在本机配置模型服务并重启，再重新检查连接。" : state.runtimeIssue === "incompatible" ? "请重启与当前页面配套的 AI 服务。" : "可以查看已保存的任务与证据，恢复连接后继续对话。";
  copy.append(title, detail); card.append(mark, copy);
  if (state.runtimeReady && !hasSession) {
    const action = document.createElement("button"); action.type = "button"; action.textContent = "发送任务目标";
    action.addEventListener("click", async () => {
      const goal = String(state.task?.business_goal || "").trim();
      if (!goal) { ui.messageInput.focus(); return; }
      setButtonBusy(action, true, "正在发送");
      try { await submitMessage(goal); }
      finally { setButtonBusy(action, false, ""); }
    });
    card.append(action);
  } else if (!state.runtimeReady) {
    const action = document.createElement("button"); action.type = "button"; action.textContent = state.runtimeIssue === "provider" ? "重新检查模型服务" : "重新检查连接";
    action.addEventListener("click", async () => {
      setButtonBusy(action, true, "检查中");
      try {
        await loadRuntime();
        if (state.runtimeReady && state.selectedTaskId) {
          await refreshSelected({ force: true });
          startConversationStream(state.selectedTaskId, state.selectionToken);
        } else if (state.runtimeIssue === "provider") showRuntimeSetupNotice("模型服务仍未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。");
        else showNotice("AI 仍未连接，请稍后重试。", "error");
      } finally { setButtonBusy(action, false, ""); }
    });
    card.append(action);
  }
  ui.messageList.append(card);
}
function captureConversationViewport() {
  const viewport = ui.conversation.getBoundingClientRect();
  const children = [...ui.messageList.children];
  const index = children.findIndex((element) => element.getBoundingClientRect().bottom > viewport.top);
  const anchor = children[index];
  return { task_id: state.selectedTaskId, top: ui.conversation.scrollTop, index, turn_id: anchor?.dataset?.turnId || null, offset: anchor ? anchor.getBoundingClientRect().top - viewport.top : null };
}
function restoreConversationViewport(snapshot, followLatest = false) {
  if (snapshot.task_id !== state.selectedTaskId) return;
  if (followLatest) { ui.conversation.scrollTop = ui.conversation.scrollHeight; return; }
  const children = [...ui.messageList.children];
  const anchor = snapshot.turn_id ? children.find((element) => element.dataset?.turnId === snapshot.turn_id) : children[snapshot.index];
  ui.conversation.scrollTop = snapshot.top;
  if (anchor && snapshot.offset !== null) ui.conversation.scrollTop += anchor.getBoundingClientRect().top - ui.conversation.getBoundingClientRect().top - snapshot.offset;
}
function renderConversation(force = false) {
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) { renderSelectionLoading(); return; }
  ui.messageList.removeAttribute("aria-busy"); ui.datasetInput.disabled = false; ui.workspaceToggleButton.disabled = false;
  if (state.selectionReadyOwnerId === state.selectedTaskId) { state.selectionReadyOwnerId = null; if (state.task?.task_id === state.selectedTaskId && state.task.record_type !== "conversation_draft") renderTask(state.task); }
  renderComposerAttachment();
  renderMaterialControls(); renderMaterialHistory(); void flushDeferredMaterialContinuations();
  const conversation = conversationView(state.task, state.conversation);
  const projection = interactionProjection(state.task, conversation);
  const draftConversation = isConversationDraft();
  syncConversationComposerPlaceholder(conversation, state.task);
  const workItems = projectionWorkItems(projection);
  const activeSpecialists = activeProjectionSpecialists(projection);
  if (state.runtimeReady) {
    ui.composerModeLabel.textContent = "AI 已连接";
    ui.composerMode.title = activeSpecialists.length ? "当前存在真实专家委派；具体分工只在对应 AI 回合的执行过程中展示" : "当前对话可用；没有真实委派时不显示专家或内部调度信息";
  }
  syncComposerDelivery(conversation);
  if (state.task) syncTaskHeader(state.task, conversation, projection);
  if (state.task && !draftConversation) { syncTaskSpecCheckpointOwnership(conversation); syncLegacyConfirmationControls(state.task, conversation); syncSelectedTaskListStatus(conversation, projection); }
  const observation = conversationObservationKey(conversation);
  const optimistic = state.pendingMessage?.task_id === state.selectedTaskId ? state.pendingMessage : null;
  const items = [...(conversation.items || [])];
  const queuedMessages = queuedConversationMessages(conversation);
  const hasRuntimeCheckpoint = Boolean(projection.checkpoint);
  if (hasRuntimeCheckpoint) ui.agentCheckpoint.hidden = true;
  else if (state.task && !draftConversation) syncAgentCheckpoint(state.task);
  else ui.agentCheckpoint.hidden = true;
  const backgroundRun = activeBackgroundTrainingRun(conversation);
  const serverCancelling = backgroundCancellationPending(conversation);
  const renderKey = JSON.stringify({ schema: conversation.schema_version, actionSchema: conversation.action_schema_version, materials: state.materialsOwnerId === state.selectedTaskId ? (state.materialInspections || []).map(record => [record.material_id, record.inspection_sha256, record.status]) : [], items: conversation.items, actions: conversation.actions, agents: conversation.agents, delegations: conversation.delegations, workItems: conversation.work_items, running: conversation.running, executionRunning: conversation.execution_running, agentResponseRunning: conversation.agent_response_running, backgroundActionRunning: conversation.background_action_running, trainingRun: backgroundRun ? [backgroundRun.training_run_id || backgroundRun.run_id || backgroundRun.action_id, backgroundRun.status, backgroundRun.domain_status, backgroundRun.cancel_requested] : null, interactionState: conversation.interaction_state, canonicalInteraction: conversation.interaction_projection, phase: projection.phase, workspace: projection.workspace, canCancelAgent: conversation.can_cancel_agent, active: conversation.active_event?.action_id || conversation.active_event?.event_id || conversation.active_event?.training_run_id || conversation.active_event?.run_id, observation, queuedMessages, optimistic: optimistic ? [optimistic.text, optimistic.delivery] : null, taskStatus: state.task?.status, runtimeReady: state.runtimeReady, sessionId: state.conversation?.session_id || null });
  if (!force && renderKey === state.lastRenderKey) return;
  const initialRender = !state.lastRenderKey; state.lastRenderKey = renderKey;
  const viewportSnapshot = captureConversationViewport();
  const nearBottom = ui.conversation.scrollHeight - ui.conversation.scrollTop - ui.conversation.clientHeight < 120; clear(ui.messageList); ui.messageList.dataset.projectionHealth = conversation.projection_health?.status || "unknown"; renderProjectionHealth(conversation); renderAgentSurfaceState(conversation, projection);
  projection.turns.forEach((turn) => renderConversationTurn(turn, projection, conversation, workItems));
  queuedMessages.forEach((item) => renderConversationItem(item));
  const optimisticObserved = optimistic && (items.some((item) => item.kind === "message" && item.role === "user" && (optimistic.agent_run_id ? item.agent_run_id === optimistic.agent_run_id : item.text === optimistic.text)) || queuedMessages.some((item) => item.request_id === optimistic.request_id));
  if (optimistic && !optimisticObserved) renderConversationItem({ kind: "message", role: "user", text: optimistic.text, time: optimistic.time, optimistic: !optimistic.delivery, delivery: optimistic.delivery });
  if (!draftConversation) renderWorkspaceExperience(state.task, conversation, projection);
  ui.conversationIntro.hidden = projection.turns.length > 0 || Boolean(projection.actions?.length);
  const agentResponseRunning = conversationAgentResponseRunning(conversation);
  const backgroundTrainingRunning = conversationHasBackgroundTraining(conversation);
  const currentAiTurn = ui.messageList.querySelector('.ai-turn[data-current="true"]');
  const fallbackWorkingSurface = !currentAiTurn && (agentResponseRunning || backgroundTrainingRunning || Boolean(optimistic) || serverCancelling);
  ui.agentWorking.hidden = !fallbackWorkingSurface;
  ui.cancelAgentButton.hidden = Boolean(currentAiTurn) || (conversation.can_cancel_agent !== true && !backgroundRun);
  if (optimistic && !agentResponseRunning && !backgroundTrainingRunning) ui.agentWorkingLabel.textContent = "正在发送";
  else if (backgroundTrainingRunning) ui.agentWorkingLabel.textContent = `后台操作 ${shortId(backgroundRun?.training_run_id || backgroundRun?.run_id || backgroundRun?.action_id)} 正在进行；你可以继续对话`;
  else if (agentResponseRunning && !conversation.active_event) ui.agentWorkingLabel.textContent = "AI 正在处理";
  else ui.agentWorkingLabel.textContent = agentActivityLabel(conversation.active_event);
  syncCancelRequestUi(conversation);
  const followLatest = initialRender || nearBottom || Boolean(optimistic);
  restoreConversationViewport(viewportSnapshot, followLatest);
  requestAnimationFrame(() => { if (renderKey === state.lastRenderKey) restoreConversationViewport(viewportSnapshot, followLatest); });
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
  const cancelled = (turn.items || []).some((item) => item.kind === "turn_cancelled" && terminalEventScope(item) === "root");
  const answered = (turn.items || []).some((item) => ["coordinator_note", "final_synthesis"].includes(item.kind) && (item.text || item.summary));
  const blocked = (turn.items || []).some((item) => item.kind === "blocker");
  if (failed || blocked) return { label: "本轮需要处理", tone: "failed", current: false, can_cancel: false };
  if (cancelled && !answered) return { label: "本轮已停止", tone: "cancelled", current: false, can_cancel: false };
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
function visibleNarrativeIndexes(items) {
  const lastByText = new Map();
  items.forEach((item, index) => {
    if (["coordinator_note", "final_synthesis"].includes(item.kind)) {
      const text = String(item.text || item.summary || "").trim();
      lastByText.set(text || `empty:${index}`, index);
    }
  });
  return new Set(lastByText.values());
}
function closingCoordinatorPlan(item, index, items, current, conversation) {
  const task = state.task, result = task?.current_result;
  return item.kind === "coordinator_plan" && current && task?.current_run_id === result?.run_id
    && ["completed", "failed", "cancelled", "interrupted"].includes(result?.status)
    && !conversationHasActiveWork(conversation) && !currentHumanCheckpoint(conversation)
    && !items.slice(index + 1).some(next => ["coordinator_plan", "coordinator_note", "final_synthesis", "turn_error", "turn_cancelled", "failed", "blocker"].includes(next.kind));
}
function renderConversationTurn(turn, projection, conversation, workItems) {
  const actions = actionsForTurn(turn, projection); let actionsRendered = false; let aiTurn = null; let runSummaryRendered = false; let executionTimeline = null;
  const recordedPlans = [];
  const resolvedCheckpoints = [];
  const items = turn.render_items || turn.items || [];
  const current = projection.current_turn?.group_key === turn.group_key;
  const latestPlanIndex = items.reduce((latest, item, index) => item.kind === "coordinator_plan" ? index : latest, -1);
  const narrativeIndexes = visibleNarrativeIndexes(items);
  const recoveredFailures = recoveredDataExperimentFailures(actions, conversation.risks); const failedAction = actions.find((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action));
  const verifiedRoles = new Set(workItems.map((item) => item.role?.role_id).filter(Boolean));
  const verifiedIds = new Set(workItems.flatMap((item) => [item.delegation_id, item.work_item_id]).filter(Boolean));
  const turnDelegationIds = new Set(actions.map((action) => action.delegation_id).filter(Boolean));
  const turnVerifiedRoles = new Set(workItems.filter((item) => turnDelegationIds.has(item.delegation_id)).map((item) => item.role?.role_id).filter(Boolean));
  const delegations = (conversation.delegations || []).filter((item) => verifiedIds.has(item.delegation_id));
  const ensureAiTurn = () => { if (!aiTurn) aiTurn = createAiTurnContainer(turn, projection, conversation, actions); return aiTurn.content; };
  const turnTarget = (role) => InteractionShell.conversationTurnTarget({ role, root: ui.messageList, aiContent: role === "user" ? null : ensureAiTurn() });
  const settled = state.task?.status === "completed" && ["completed", "idle"].includes(conversation.interaction_projection?.phase) && !currentHumanCheckpoint(conversation) && !conversationHasActiveWork(conversation) && !(state.task.control?.blocked_by || []).length && !(state.task.blockers || []).some((blocker) => blocker.active !== false);
  const turnInteractionState = !current ? "historical" : settled ? "settled" : projection.phase === "executing" ? "working" : ["clarifying", "awaiting_approval"].includes(projection.phase) ? "waiting_for_human" : "idle";
  const renderActions = () => { if (!actionsRendered && actions.length) { executionTimeline = renderActionTimeline(actions, delegations, { interactionState: turnInteractionState, expertCount: turnVerifiedRoles.size, recoveredFailures, target: turnTarget("assistant") }); actionsRendered = true; } };
  items.forEach((item, itemIndex) => {
    if (item.kind === "message" && item.role === "user") { renderConversationItem(item, turnTarget("user")); return; }
    if ((item.kind === "approval" || item.kind === "question") && !isPendingHumanCheckpoint(item)) { resolvedCheckpoints.push(item); return; }
    if (item.kind === "coordinator_plan" && itemIndex !== latestPlanIndex) return;
    if (["coordinator_note", "final_synthesis"].includes(item.kind) && !narrativeIndexes.has(itemIndex)) return;
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
    if (item.kind === "approval" || item.kind === "question") {
      renderActions();
      if (current && !runSummaryRendered) runSummaryRendered = appendRunCheckpointSummary(ensureAiTurn());
      renderHumanCheckpoint(item, { interactive: projection.observation?.degraded !== true && projection.background?.cancelling !== true && state.cancelRequestInFlight !== true, target: ensureAiTurn() }); return;
    }
    if (["final_synthesis", "turn_error", "turn_cancelled", "failed", "blocker"].includes(item.kind)) renderActions();
    const planText = `${item.title || ""} ${item.summary || item.text || ""}`;
    const truthConflict = item.kind === "coordinator_plan" && Boolean(failedAction) && /(?:正在后台运行|已经.{0,8}(?:启动|运行|完成)|训练中|已进入训练)/u.test(planText);
    // Native history can retain an old child as open and tag the closing
    // answer as a plan. Once real work is settled, keep that last answer in
    // the dialogue; this never promotes it to a completion/approval fact.
    if (closingCoordinatorPlan(item, itemIndex, items, current, conversation)) { renderConversationItem({ ...item, kind: "coordinator_note" }, ensureAiTurn()); return; }
    if (item.kind === "coordinator_plan" && actions.length) { recordedPlans.push({ ...item, compact: true, currentInteraction: current, truthConflict }); return; }
    renderConversationItem(item.kind === "coordinator_plan" ? { ...item, compact: true, currentInteraction: current, truthConflict, failedActionTitle: failedAction ? actionTitle(failedAction) : null } : item, ensureAiTurn());
  });
  renderActions();
  if (executionTimeline?.executionBody) {
    recordedPlans.forEach(item => renderCoordinatorProgress(item, executionTimeline.executionBody));
    if (resolvedCheckpoints.length) renderCheckpointHistory(resolvedCheckpoints, executionTimeline.executionBody);
  }
  // Canonical completed Run results remain available after a natural final
  // reply, even when that reply does not carry a final_synthesis object ref.
  // Never attach today's model to a historical turn or an active operation.
  if (current && !runSummaryRendered && !conversationHasActiveWork(conversation) && !currentHumanCheckpoint(conversation)
      && !aiTurn?.content.querySelector(".turn-result-card")) appendRunCheckpointSummary(ensureAiTurn());
  if (!aiTurn && current && ["executing", "clarifying", "awaiting_approval"].includes(projection.phase)) ensureAiTurn();
  if (aiTurn) appendAiTurnPlaceholder(aiTurn.content, aiTurn.presentation);
}
function isWaitingForAnswerAction(action, waitingForHuman = false) {
  if (!waitingForHuman || action.status !== "running") return false;
  const checkpoint = currentHumanCheckpoint(state.conversation);
  if (checkpoint?.call_id && action.call_id) return checkpoint.call_id === action.call_id && checkpoint.session_id === action.session_id;
  return action.tool_name === "ask_user_question" && (!checkpoint?.session_id || checkpoint.session_id === action.session_id);
}
function isUserDeclinedAction(action) {
  return action?.status === "failed" && action?.error?.code === "user_rejected";
}
function actionDisplayStatus(action, waitingForHuman = false) {
  if (isWaitingForAnswerAction(action, waitingForHuman)) return "waiting";
  if (action.status === "cancelled" && action.error?.code === "checkpoint_suspended") return "suspended";
  if (isUserDeclinedAction(action)) return "declined";
  return action.status;
}
function actionStatusLabel(action, { waitingForHuman = false } = {}) {
  const displayStatus = actionDisplayStatus(action, waitingForHuman);
  if (displayStatus === "waiting") return currentHumanCheckpoint(state.conversation)?.kind === "approval" ? "等待批准" : "等待回答";
  if (displayStatus === "suspended") return "已暂缓";
  if (displayStatus === "cancelled") return "已停止";
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
function isProbeMiss(action) {
  const message = `${action?.error?.message || ""} ${action?.error?.code || ""}`;
  return /run not found|recipe build not found|no such file or directory/i.test(message);
}
function readableActionText(message) {
  const text = String(message || "").replace(/\s+/g, " ").trim();
  if (/^started subagent\s+[0-9a-f-]{8,}/i.test(text)) return "已交给对应专家继续处理。";
  if (/run not found/i.test(text)) return "没有找到对应的训练运行，这一步没有改变任务。";
  if (/recipe build not found/i.test(text)) return "没有找到能力构建记录，这一步没有改变任务。";
  return text.slice(0, 220);
}
function formatActionDuration(action) {
  if (!Number.isFinite(action.duration_ms)) return action.status === "running" ? "仍在执行" : "";
  if (action.duration_ms < 1000) return `${Math.round(action.duration_ms)} ms`;
  return `${(action.duration_ms / 1000).toFixed(action.duration_ms < 10_000 ? 1 : 0)} s`;
}
function actionTimelineGlance(actions, waitingForHuman, working, recoveredFailures = new Set(), quietHistory = false) {
  const failed = actions.find((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action) && !isProbeMiss(action));
  if (waitingForHuman) return "当前有待确认事项；请先查看下面的确认卡，历史执行记录可以展开核对";
  if (quietHistory) return failed ? "执行过程已保留 · 含历史异常记录，可展开核对" : "已结束的执行过程，可以展开核对";
  if (failed) return `需要处理：${actionTitle(failed)}`;
  if (actions.length && actions.every((action) => action.status === "cancelled")) return "检查点已暂缓，正在继续讨论";
  const running = actions.find((action) => action.status === "running" && action.tool_class !== "control");
  if (running) return `正在执行：${actionTitle(running)}`;
  if (actions.some(isUserDeclinedAction)) return "你选择暂不执行，关键操作没有启动";
  const completed = [...actions].reverse().find((action) => action.status === "completed");
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
    return { state: "failed", text: readableActionText(error) };
  }
  const result = parseActionResultValue(body.result ?? body.result_preview ?? body.summary ?? body.message);
  if (result?.context_state?.owner_id && result.context_state.grants_execution_authorization === false) {
    const count = Array.isArray(result.context_state.entries) ? result.context_state.entries.length : 0;
    return { state: "completed", text: action.tool_name === "model_harness_record_context_state" ? `已保留 ${count} 项目标与选择。` : `已读取 ${count} 项目标与已回答事项。` };
  }
  if (action?.tool_name === "model_harness_download_artifact_bundle") {
    if (result?.status === "downloaded") {
      return { state: "completed", text: "下载完成：新文件已写入，并通过大小与 SHA-256 校验。" };
    }
    if (result?.status === "download_opened") {
      return { state: "loading", text: "传输已开始，尚未确认本地文件保存完成。" };
    }
  }
  if (result?.proposal?.proposal_id && result.proposal.proposal_sha256) { const proposal = result.proposal; const qualification = result.qualification || proposal.qualification; return { state: proposal.status === "qualification_failed" ? "failed" : proposal.status === "qualifying" ? "loading" : "completed", text: ({ proposed: "工程代码已保存，等待隔离验证。", qualifying: "隔离工程验证正在运行，尚未启动正式训练。", qualified: "隔离验证通过，等待确认启用方案。", qualification_failed: `隔离验证未通过：${qualification?.failure || proposal.failure || "请查看日志后修正方案"}`, activated: "工程方案已启用；训练合同仍需确认，尚未启动正式训练。" })[proposal.status] || `工程方案状态：${proposal.status || "未记录"}` }; }
  if (result?.asset?.object_type === "ExecutionAsset") { const asset = result.asset; return { state: "completed", text: `已获取 ${asset.files?.length || 0} 个文件 · 许可 ${asset.license || "unknown"} · ${asset.license_review_required || asset.license_policy?.decision !== "allow" ? "使用范围待核对" : "许可策略已记录"}` }; }
  const task = result?.task || (result?.task_id && result?.status ? result : null);
  if (task) {
    const status = STATUS_LABELS[task.status] || task.status || "状态未知"; const revision = task.current_spec_revision ? ` · 任务理解第 ${task.current_spec_revision} 版` : ""; const recipe = ({ "tabular-regression": "表格数值回归", "tabular-classification": "表格分类", "image-folder-classification": "图片分类", "digit-classification": "数字分类", "audio-keyword-classification": "音频关键词分类", "generic-isolated-execution": "已验证工程" })[task.recipe_id] || task.recipe_id; const recipeLabel = recipe ? ` · ${recipe}方案` : "";
    return { state: "completed", text: `当前：${status}${revision}${recipeLabel}` };
  }
  const answers = Array.isArray(result?.answers) ? result.answers.flatMap((answer) => [...(Array.isArray(answer.selected) ? answer.selected : []), ...(answer.custom ? [answer.custom] : [])]).filter(Boolean) : [];
  if (answers.length) return { state: "completed", text: `已记录你的选择：${answers.join("、")}` };
  if (action?.tool_name === "model_harness_match_capability" && Array.isArray(result?.matches)) {
    return {
      state: result.matches.length ? "completed" : "completed_empty",
      text: result.matches.length
        ? `能力匹配返回 ${result.matches.length} 项结果`
        : "现成方案目录当前没有匹配项，可以继续准备工程方案。",
    };
  }
  const searchResult = result?.search && typeof result.search === "object" ? result.search : result;
  if (Array.isArray(searchResult?.candidates)) {
    const providerErrors = Array.isArray(searchResult?.provider_errors) ? searchResult.provider_errors : [];
    if (!searchResult.candidates.length && providerErrors.length) {
      return { state: "failed", text: `候选模型搜索未返回结果；${providerErrors.length} 个模型来源失败，请查看完整结果后重试` };
    }
    const partialFailureText = providerErrors.length ? `；${providerErrors.length} 个模型来源部分失败，请查看完整结果` : "";
    return { state: "completed", text: `候选模型返回 ${searchResult.candidates.length} 项结果${partialFailureText}` };
  }
  const collections = [[result?.matches, "能力匹配"], [result?.recipes, "训练方案"], [result?.adapters, "数据适配器"]];
  const collection = collections.find(([items]) => Array.isArray(items));
  if (collection) return { state: "completed", text: `${collection[1]}返回 ${collection[0].length} 项结果` };
  if (typeof result === "string" && /^report accepted by the agent that started you\b/i.test(result.trim())) return { state: "completed", text: "专家结论已交回训练协调器。" };
  if (typeof result === "string" && /^message queued as the next turn for subagent\b/i.test(result.trim())) return { state: "completed", text: "已转交给对应专家继续处理。" };
  if (typeof result === "string" && /^[\[{]/.test(result.trim())) return { state: "completed", text: "结果已保留，可查看完整技术详情。" };
  if (typeof result === "string" && result) return { state: "completed", text: readableActionText(result) };
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
  const copy = document.createElement("div"); const meta = document.createElement("span"); meta.className = "agent-action-meta"; const role = document.createElement("b"); role.textContent = roleLabel(action.actor_role); const timing = document.createElement("small"); timing.textContent = "已完成"; meta.append(role, timing); const title = document.createElement("h4"); title.textContent = actionTitle(action); copy.append(meta, title);
  const evidence = document.createElement("details"); evidence.className = "recovered-action-evidence"; evidence.dataset.originalStatus = action.status; evidence.dataset.actionId = action.action_id || "identity-error"; const summary = document.createElement("summary"); summary.textContent = "查看初次调用记录"; const error = document.createElement("p"); error.className = "agent-action-error"; error.textContent = action.error?.message || action.error?.code || "初次调用没有完成，后续已由正确角色重新执行。"; evidence.append(summary, error); const refs = document.createElement("div"); refs.className = "agent-action-evidence"; appendObjectRefs(refs, action.object_refs || []); if (action.event_result_ref) { const button = document.createElement("button"); button.type = "button"; button.textContent = "技术详情"; button.addEventListener("click", () => openEventResultRef(action.event_result_ref)); refs.append(button); } if (refs.childElementCount) evidence.append(refs); copy.append(evidence);
  const status = document.createElement("em"); status.textContent = "已处理"; row.append(mark, copy, status); target.append(row);
}
function renderActionRow(action, target, { waitingForHuman = false, recovered = false } = {}) {
  if (recovered) { renderRecoveredActionRow(action, target); return; }
  const waitingForAnswer = isWaitingForAnswerAction(action, waitingForHuman); const displayStatus = actionDisplayStatus(action, waitingForHuman);
  const row = document.createElement("article"); row.className = "agent-action"; row.dataset.status = displayStatus; row.dataset.toolClass = action.tool_class; row.dataset.actionId = action.action_id || "identity-error";
  const mark = document.createElement("i"); mark.setAttribute("aria-hidden", "true"); mark.textContent = displayStatus === "failed" || displayStatus === "identity_error" ? "!" : ["declined", "suspended", "cancelled"].includes(displayStatus) ? "—" : displayStatus === "waiting" ? "…" : displayStatus === "running" ? "→" : "✓";
  const copy = document.createElement("div"); const meta = document.createElement("span"); meta.className = "agent-action-meta"; const role = document.createElement("b"); role.textContent = roleLabel(action.actor_role); const timing = document.createElement("small"); const startedAt = action.started_at || action.created_at || action.time; const heartbeatAt = action.last_heartbeat_at || action.updated_at || action.finished_at; const durationLabel = waitingForAnswer || displayStatus === "suspended" ? actionStatusLabel(action, { waitingForHuman }) : formatActionDuration(action); const timingParts = []; if (durationLabel) timingParts.push(durationLabel); if (startedAt) timingParts.push(`开始 ${formatTime(startedAt)}`); if (displayStatus === "running" && heartbeatAt) timingParts.push(`最近事件 ${formatRelativeTime(heartbeatAt)}`); if (action.tool_class === "control") timingParts.push("控制动作"); timing.textContent = timingParts.join(" · "); meta.append(role, timing);
  const title = document.createElement("h4"); title.textContent = actionTitle(action); copy.append(meta, title);
  if (displayStatus === "declined") { const note = document.createElement("p"); note.className = "agent-action-result"; note.dataset.state = "declined"; note.textContent = "你选择暂不执行，系统没有运行这项操作。"; copy.append(note); }
  else if (displayStatus === "suspended") { const note = document.createElement("p"); note.className = "agent-action-result"; note.dataset.state = "suspended"; note.textContent = "已暂缓，未提交答案或批准；保留记录供回看。"; copy.append(note); }
  else if (action.error) { const provider = providerErrorPresentation(action); const error = document.createElement("p"); error.className = "agent-action-error"; error.textContent = provider?.message || action.error.message || action.error.code || "工具失败但没有返回可读原因。"; copy.append(error); appendProviderErrorDetails(copy, provider); }
  else { const result = document.createElement("p"); result.className = "agent-action-result"; result.dataset.actionId = action.action_id || "identity-error"; result.dataset.state = displayStatus; result.textContent = waitingForAnswer ? (currentHumanCheckpoint(state.conversation)?.kind === "approval" ? "尚未执行，等待你明确批准；也可以先讨论。" : "正在等待你的回答，也可以先继续讨论。") : action.status === "running" ? "正在执行，结果返回后会显示在这里。" : action.event_result_ref ? "已返回结果，展开后显示摘要。" : action.object_refs?.length ? `已产生 ${action.object_refs.length} 个可追溯对象。` : "工具已完成，没有返回额外对象。"; copy.append(result); }
  const evidence = document.createElement("div"); evidence.className = "agent-action-evidence"; appendObjectRefs(evidence, action.object_refs || []);
  if (action.event_result_ref) { const button = document.createElement("button"); button.type = "button"; button.textContent = "技术详情"; button.setAttribute("aria-label", `查看“${actionTitle(action)}”的完整脱敏技术详情`); button.addEventListener("click", () => openEventResultRef(action.event_result_ref)); evidence.append(button); }
  if (evidence.childElementCount) copy.append(evidence); const status = document.createElement("em"); status.textContent = actionStatusLabel(action, { waitingForHuman }); row.append(mark, copy, status); target.append(row);
}
function renderDelegationGroup(group, groups, target, visited, depth = 0, { waitingForHuman = false, recoveredFailures = new Set(), quietHistory = false } = {}) {
  if (visited.has(group.id)) return; visited.add(group.id);
  const details = document.createElement("details"); details.className = "delegation-group"; const hasDeclined = group.actions.some(isUserDeclinedAction); const hasFailure = group.actions.some((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action)); const waitingForAnswer = group.actions.some((action) => isWaitingForAnswerAction(action, waitingForHuman)); const running = group.actions.some((action) => action.status === "running" && !isWaitingForAnswerAction(action, waitingForHuman)); details.open = !waitingForHuman && !quietHistory && (hasFailure || running || waitingForAnswer || (!group.unverified && depth === 0)); details.dataset.status = hasFailure ? "failed" : running ? "running" : waitingForAnswer ? "waiting" : hasDeclined ? "declined" : "completed";
  const summary = document.createElement("summary"); const copy = document.createElement("span"); const title = document.createElement("b"); const first = group.actions[0]; const delegationAction = group.actions.find((action) => action.tool_class === "delegation"); const delegatedRole = delegationAction?.tool_name && ConversationView?.ROLE_LABELS?.[delegationAction.tool_name] ? delegationAction.tool_name : null; const summaryRole = group.root ? "orchestrator" : group.binding?.target_agent_id || delegatedRole || first?.actor_role; title.textContent = group.unverified ? "未归属的执行记录" : group.root ? "训练协调器" : roleLabel(summaryRole); const counts = document.createElement("small"); const domainCount = group.actions.filter((action) => action.tool_class === "domain").length; const controlCount = group.actions.filter((action) => action.tool_class === "control").length; const objectCount = group.actions.reduce((total, action) => total + (action.object_refs?.length || 0), 0); counts.textContent = group.unverified ? `${group.actions.length} 项记录 · 不作为当前决定` : `${roleLabel(summaryRole)} · ${domainCount} 个领域动作 · ${controlCount} 个控制动作 · ${objectCount} 个对象`; copy.append(title, counts); const stateLabel = document.createElement("em"); stateLabel.textContent = waitingForHuman || quietHistory ? hasFailure ? "包含失败记录" : "已记录" : hasFailure ? "需要处理" : running ? "执行中" : waitingForAnswer ? "等待你的决定" : hasDeclined ? "你选择暂不执行" : "已结束"; summary.append(copy, stateLabel); details.append(summary);
  const list = document.createElement("div"); list.className = "agent-action-list"; group.actions.forEach((action) => renderActionRow(action, list, { waitingForHuman, recovered: recoveredFailures.has(action) }));
  (group.children || []).map((id) => groups.get(id)).filter(Boolean).forEach((child) => renderDelegationGroup(child, groups, list, visited, depth + 1, { waitingForHuman, recoveredFailures, quietHistory })); details.append(list); target.append(details);
}
function renderActionTimeline(actions, delegations = [], { interactionState = "idle", expertCount = 0, recoveredFailures = new Set(), target = ui.messageList } = {}) {
  if (!actions.length) return; const section = document.createElement("details"); section.className = "action-timeline"; section.dataset.interactionKind = "action-group"; section.setAttribute("aria-label", "智能体真实执行过程");
  const waitingForHuman = interactionState === "waiting_for_human"; const quietHistory = ["settled", "historical"].includes(interactionState); const declinedCount = actions.filter(isUserDeclinedAction).length; const failedCount = actions.filter((action) => ["failed", "identity_error"].includes(action.status) && !recoveredFailures.has(action) && !isUserDeclinedAction(action)).length; const waitingActionCount = actions.filter((action) => isWaitingForAnswerAction(action, waitingForHuman)).length; const runningCount = actions.filter((action) => action.status === "running" && !isWaitingForAnswerAction(action, waitingForHuman)).length; const working = interactionState === "working"; const suspended = actions.some((action) => action.status === "cancelled"); section.dataset.status = waitingForHuman ? "waiting" : quietHistory ? "recorded" : failedCount ? "failed" : runningCount || working ? "running" : waitingActionCount ? "waiting" : declinedCount ? "declined" : suspended ? "suspended" : "completed"; section.dataset.recoveredFailures = String(recoveredFailures.size);
  const turnKey = actions.find((action) => action.turn_id)?.turn_id || actions[0]?.agent_run_id || "unscoped"; const disclosureBase = `${state.selectedTaskId || "task"}:${turnKey}`; const disclosureKey = `${disclosureBase}:${waitingForHuman ? "checkpoint" : quietHistory ? "history" : "execution"}`; const savedOpen = state.actionTimelineManualDisclosure?.get(disclosureBase) ?? state.actionTimelineDisclosure.get(disclosureKey); section.open = savedOpen === undefined ? false : savedOpen; section.dataset.defaultDisclosure = section.open ? "open" : "closed";
  const header = document.createElement("summary"); const copy = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "执行记录"; const title = document.createElement("h3"); title.textContent = "查看执行记录"; const glance = document.createElement("p"); glance.className = "action-timeline-glance"; glance.textContent = actionTimelineGlance(actions, waitingForHuman, working, recoveredFailures, quietHistory); copy.append(kicker, title, glance); const count = document.createElement("b"); const countLabel = () => `${actions.length} 条${failedCount && !quietHistory ? " · 有异常" : ""} · ${section.open ? "收起" : "展开"}`; count.textContent = countLabel(); header.append(copy, count); section.append(header);
  header.addEventListener("click", () => { (state.actionTimelineManualDisclosure ||= new Map()).set(disclosureBase, !section.open); });
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
  else { if (rootAgent.actions.length) renderDelegationGroup(rootAgent, groups, body, visited, 0, { waitingForHuman, recoveredFailures, quietHistory }); roots.forEach((group) => renderDelegationGroup(group, groups, body, visited, 0, { waitingForHuman, recoveredFailures, quietHistory })); if (unverified.actions.length) renderDelegationGroup(unverified, groups, body, visited, 0, { waitingForHuman, recoveredFailures, quietHistory }); }
  section.executionBody = body; section.append(body); target.append(section); hydrateActionTimelineResults(section, actions); return section;
}
function renderCheckpointHistory(items, target = ui.messageList) {
  if (!items.length) return;
  const details = document.createElement("details"); details.className = "checkpoint-history";
  const summary = document.createElement("summary"); const label = document.createElement("span"); const title = document.createElement("b"); title.textContent = "你的批准与回答"; label.append(title); const count = document.createElement("em"); count.textContent = `${items.length} 次`; summary.append(label, count); details.append(summary);
  const list = document.createElement("div"); list.className = "checkpoint-history-list";
  items.slice(-8).forEach((item) => { const row = document.createElement("div"); const name = document.createElement("b"); name.textContent = item.kind === "approval" ? item.title || "关键操作批准" : item.title || item.questions?.[0]?.header || "补充信息"; const status = document.createElement("span"); status.textContent = (item.outcome || item.payload?.outcome) === "superseded_for_discussion" ? "已暂缓 · 继续讨论" : eventStatusLabel(item.status); row.append(name, status); list.append(row); });
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
  const mark = document.createElement("span"); mark.setAttribute("aria-hidden", "true"); mark.append(createUiIcon("alert"));
  const body = document.createElement("div"); const kicker = document.createElement("small"); const title = document.createElement("b"); const copy = document.createElement("p");
  const labels = {
    blocker: ["能力或条件阻断", "当前还不能继续"],
    warning: ["需要留意", "执行存在一项提醒"],
    observation_degraded: ["观察链路异常", "部分实时过程暂时不可见"],
    failed: ["执行异常", "本轮出现失败事件"],
  };
  const provider = item.kind === "failed" ? providerErrorPresentation(item, { turnStopped: terminalEventScope(item) === "root" }) : null;
  const [label, fallbackTitle] = labels[item.kind] || labels.failed; kicker.textContent = label; title.textContent = provider?.title || item.title || fallbackTitle; copy.textContent = provider?.message || item.summary || item.text || item.reason || item.error?.message || "系统没有提供更具体的说明。";
  body.append(kicker, title, copy); appendProviderErrorDetails(body, provider); appendObjectRefs(body, item.object_refs); appendRecoveryActions(body, item); card.append(mark, body); target.append(card);
}
function appendRecoveryActions(container, item = {}) {
  const actions = document.createElement("div"); actions.className = "recovery-actions";
  const refresh = document.createElement("button"); refresh.type = "button"; refresh.textContent = item.kind === "observation_degraded" ? "重新检查连接" : "重新检查当前状态";
  refresh.addEventListener("click", async () => { setButtonBusy(refresh, true, "检查中"); try { if (item.kind === "observation_degraded") await loadRuntime(); if (state.selectedTaskId) await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(refresh, false, ""); } });
  const adjust = document.createElement("button"); adjust.type = "button"; adjust.className = "secondary"; adjust.textContent = "补充要求"; adjust.addEventListener("click", () => { ui.messageInput.focus(); showNotice("请直接说明你希望修改的目标、数据或执行方式；不会自动重试刚才的失败动作。", "ok"); });
  const evidence = document.createElement("button"); evidence.type = "button"; evidence.className = "secondary"; evidence.textContent = "打开任务证据"; evidence.addEventListener("click", () => openInspector("plan"));
  actions.append(refresh, adjust, evidence); container.append(actions);
}
function renderMessage(item, target = ui.messageList) {
  if (item.role !== "user") return renderUnknownEvent({ ...item, contract_error: "only user messages enter renderMessage" }, target);
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "user"; row.dataset.interactionKind = "natural-dialogue"; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "你";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "你"; const time = document.createElement("time"); time.textContent = item.delivery === "queued" ? "等待回复后发送" : item.optimistic ? "正在发送…" : formatTime(item.time); meta.append(author, time);
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
    else if (/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/.test(token)) { const open = document.createElement("button"); open.type = "button"; open.className = "inline-panel-link"; open.textContent = "结果面板"; open.addEventListener("click", () => openInspector(state.task?.current_result?.status === "completed" ? "evaluation" : "plan")); container.append(open); }
    else { const link = document.createElement("a"); link.href = token; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = token; container.append(link); }
    cursor = match.index + token.length;
  }
  if (cursor < value.length) container.append(document.createTextNode(value.slice(cursor)));
}
function markdownTableCells(line) { return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim()); }
function isMarkdownTableDivider(line) { return markdownTableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell)); }
function isMarkdownBlockStart(line, nextLine = "") { const value = line.trim(); return !value || value.startsWith("```") || /^#{1,4}\s+/.test(value) || /^[-*]\s+/.test(value) || /^\d+\.\s+/.test(value) || (value.startsWith("|") && nextLine.trim().startsWith("|") && isMarkdownTableDivider(nextLine)); }
function renderRichText(container, text) {
  container.classList.add("rich-message"); const lines = String(text || "").split(/\r?\n/); let index = 0;
  while (index < lines.length) {
    const line = lines[index]; const trimmed = line.trim(); if (!trimmed) { index += 1; continue; }
    if (trimmed.startsWith("```")) {
      const pre = document.createElement("pre"); pre.className = "rich-code"; const code = document.createElement("code"); const body = []; index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) { body.push(lines[index]); index += 1; }
      index += 1; code.textContent = body.join("\n"); pre.append(code); container.append(pre); continue;
    }
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
const TERMINAL_RESULT_REF_TYPES = new Set(["evaluation_report", "artifact_bundle"]);
function terminalResultRefs(item, task, result) {
  const taskId = task?.task_id; const runId = result?.run_id;
  if (!taskId || !runId || result.status !== "completed") return [];
  return (item.object_refs || []).filter((ref) => (
    TERMINAL_RESULT_REF_TYPES.has(ref?.type)
    && typeof ref.id === "string" && ref.id.length > 0
    && ref.task_id === taskId
    && ref.run_id === runId
    && typeof ref.digest === "string" && EVIDENCE_SHA256.test(ref.digest)
  ));
}
function reportForTerminalRef(ref, task, result) {
  if (!ref) return null;
  const fresh = state.evidenceRunId === result.run_id ? state.evaluationReport : null;
  const report = fresh || result.evaluation_report || null;
  if (!report || report.task_id !== task.task_id || report.run_id !== result.run_id || report.report_id !== ref.id || report.report_sha256 !== ref.digest) return null;
  return report;
}
function bundleForTerminalRef(ref, task, result) {
  if (!ref || state.evidenceRunId !== result.run_id) return null;
  return state.artifactBundles.find((bundle) => bundle?.bundle_id === ref.id && bundle.task_id === task.task_id && bundle.run_id === result.run_id && bundle.manifest_sha256 === ref.digest) || null;
}
function metricPresentation(task, key, value, forGate = false) {
  const common = {
    accuracy: ["准确率", "rate"], macro_f1: ["宏平均 F1", "number"], worst_class_recall: ["最弱类别召回率", "rate"],
    test_cer: ["测试字符错误率", "rate"], challenge_cer: ["挑战字符错误率", "rate"],
    test_exact_match_accuracy: ["测试整句准确率", "rate"], challenge_exact_match_accuracy: ["挑战整句准确率", "rate"],
    ndcg_at_5_mean: ["排序质量 NDCG@5", "number"], overall_mae: ["平均绝对误差", "number"], mae: ["平均绝对误差", "number"],
    rmse: ["均方根误差", "number"], r2: ["拟合优度 R²", "number"], mase: ["相对尺度误差 MASE", "number"], smape: ["对称百分比误差", "percentage_points"],
    mel_cepstral_distortion_db: ["声学失真（dB）", "number"], duration_ratio_deviation_mean: ["时长偏差", "rate"],
    syllable_count_error_rate_energy_envelope_proxy: ["音节计数代理误差", "rate"],
  };
  // Presentation metadata is open; these names never route or restrict a model.
  const custom = task?.contract?.execution_spec?.capability?.metric_display?.[key];
  const [defaultLabel, defaultFormat] = common[key] || [key.replaceAll("_", " "), "number"];
  const label = typeof custom?.label === "string" && custom.label.trim() ? custom.label : defaultLabel;
  const format = ["rate", "percentage_points", "number"].includes(custom?.format) ? custom.format : defaultFormat;
  const shown = format === "rate" ? value * 100 : value;
  const text = forGate ? String(Number(shown.toPrecision(12))) : shown !== 0 && Math.abs(shown) < 0.001 ? shown.toPrecision(3) : shown.toFixed(format === "number" ? 3 : 2);
  return { label, value: text + (format === "number" ? "" : "%") };
}
function terminalResultMetrics(task, result) {
  const clean = result?.metrics?.clean_test || {}; const gates = task?.contract?.release_gates || {};
  const declared = task?.contract?.execution_spec?.evaluation?.gates;
  if (declared) return Object.entries(clean).filter(([, value]) => Number.isFinite(value)).map(([key, value]) => { const gate = declared[key], hasGate = Number.isFinite(gate?.threshold) && ["lte", "gte"].includes(gate.operator); return { key, ...metricPresentation(task, key, value), gate: hasGate ? `${gate.operator === "lte" ? "≤" : "≥"} ${metricPresentation(task, key, gate.threshold, true).value}` : null, passed: hasGate ? gate.operator === "lte" ? value <= gate.threshold : value >= gate.threshold : null }; }).sort((a, b) => Number(a.passed !== false) - Number(b.passed !== false)).slice(0, 3);
  const definitions = [
    ["accuracy", "Accuracy", "clean_test_accuracy_min", "min"],
    ["macro_f1", "Macro-F1", "clean_test_macro_f1_min", "min"],
    ["worst_class_recall", "最差类 Recall", "clean_test_worst_class_recall_min", "min"],
    ["mae", "MAE", "clean_test_mae_max", "max"],
    ["rmse", "RMSE", "clean_test_rmse_max", "max"],
    ["r2", "R²", "clean_test_r2_min", "min"],
  ];
  const metrics = definitions.flatMap(([key, label, gateKey, direction]) => {
    const value = clean[key]; if (!Number.isFinite(value)) return [];
    const gate = gates[gateKey]; const hasGate = Number.isFinite(gate); const passed = hasGate ? direction === "max" ? value <= gate : value >= gate : null;
    return [{ key, label, value: value.toFixed(3), gate: hasGate ? `${direction === "max" ? "≤" : "≥"} ${gate.toFixed(3)}` : null, passed }];
  });
  return metrics.slice(0, 3);
}
function runCheckpointSummaryModel() {
  const task = state.task, result = task?.current_result;
  if (!task || task.status !== "completed" || result?.status !== "completed" || task.current_run_id !== result.run_id) return null;
  const report = state.evidenceRunId === result.run_id ? state.evaluationReport : result.evaluation_report;
  if (!report || report.task_id !== task.task_id || report.run_id !== result.run_id || !EVIDENCE_SHA256.test(report.report_sha256 || "") || report.run_status !== "completed") return null;
  const sample = state.evidenceRunId === result.run_id ? [...(state.sampleInferences || [])].reverse().find(check => check.task_id === task.task_id && check.run_id === result.run_id && check.status === "passed" && EVIDENCE_SHA256.test(check.prediction_sha256 || "")) : null;
  return { taskId: task.task_id, runId: result.run_id, ready: report.release_ready === true, sample,
    metrics: terminalResultMetrics(task, result),
    summary: report.release_ready === true ? "独立测试已通过当前合同的验收门槛。接下来可用新样本检查实际效果。" : `独立评估已完成，当前结论：${statusLabel(report.conclusion || "not_evaluated")}。可继续检查结果和限制。` };
}
function appendRunCheckpointSummary(target) {
  const model = runCheckpointSummaryModel(); if (!model) return false;
  const card = document.createElement("section"); card.className = "turn-result-card"; card.dataset.interactionKind = "run-checkpoint-summary";
  const header = document.createElement("header"), title = document.createElement("h3"), status = document.createElement("b"); title.textContent = "本次评估"; status.textContent = model.ready ? "达到当前标准" : "需要改进"; status.className = "result-verdict"; status.dataset.passed = String(model.ready); header.append(title, status);
  const summary = document.createElement("p"); summary.className = "turn-result-conclusion"; summary.textContent = model.summary; card.append(header, summary);
  const metrics = document.createElement("dl"); metrics.className = "turn-result-metrics";
  model.metrics.forEach(metric => {
    const row = document.createElement("div"), term = document.createElement("dt"), value = document.createElement("dd"), actual = document.createElement("b"), gate = document.createElement("small");
    if (metric.passed !== null) row.dataset.passed = String(metric.passed);
    term.textContent = metric.label; actual.textContent = metric.value; gate.textContent = `${metric.gate ? `标准 ${metric.gate}` : "评估值"}${metric.passed === false ? " · 未达标" : metric.passed === true ? " · 达标" : ""}`; value.append(actual, gate); row.append(term, value); metrics.append(row);
  }); card.append(metrics);
  if (model.sample) {
    const preview = document.createElement("details"), heading = document.createElement("summary"); heading.textContent = "查看试用结果"; preview.className = "trial-result-preview";
    preview.open = typeof model.sample.prediction === "string" || (model.sample.artifacts || []).some(artifact => /^(audio|image|video)\//.test(artifact.media_type || "")); preview.append(heading); renderSamplePrediction(model.sample, preview); card.append(preview);
  }
  const footer = document.createElement("footer"), details = document.createElement("button"); details.type = "button"; details.className = "text-button"; details.textContent = "评估详情";
  details.addEventListener("click", () => { if (state.selectedTaskId === model.taskId && state.task?.current_result?.run_id === model.runId) openInspector("evaluation"); });
  footer.append(details);
  if (!currentHumanCheckpoint(state.conversation) && !conversationHasActiveWork(state.conversation)) {
    const bundle = state.evidenceRunId === model.runId ? [...(state.artifactBundles || [])].reverse().find(record => record.task_id === model.taskId && record.run_id === model.runId && record.status === "completed" && EVIDENCE_SHA256.test(record.manifest_sha256 || "") && EVIDENCE_SHA256.test(record.archive?.sha256 || "")) : null;
    if (bundle) {
      const download = document.createElement("button"); download.type = "button"; download.className = "text-button"; download.textContent = "保存模型包";
      download.addEventListener("click", () => { if (state.selectedTaskId === model.taskId && state.task?.current_result?.run_id === model.runId) requestArtifactBundleDownload({ run_id: model.runId }, bundle); });
      footer.append(download);
    }
  }
  card.append(footer); target.append(card); return true;
}
function terminalResultCardModel(item, projection) {
  const task = state.task; const result = task?.current_result;
  if (item?.kind !== "final_synthesis" || item.completion_eligible !== true || runtimeStatusToken(item.status) !== "completed") return null;
  if (projection?.phase !== "result_ready" || projection.background?.running === true || projection.result?.final?.event_id !== item.event_id) return null;
  const refs = terminalResultRefs(item, task, result); if (!refs.length) return null;
  const evaluationCandidate = refs.find((ref) => ref.type === "evaluation_report") || null; const bundleCandidate = refs.find((ref) => ref.type === "artifact_bundle") || null;
  const report = reportForTerminalRef(evaluationCandidate, task, result); const bundle = bundleForTerminalRef(bundleCandidate, task, result);
  if (!report && !bundle) return null;
  const evaluationRef = report ? evaluationCandidate : null; const bundleRef = bundle ? bundleCandidate : null;
  const conclusion = report
    ? report.release_ready === true ? "这次评测证据已满足当前交付门槛。" : `这次评测已完成，当前结论为“${statusLabel(report.conclusion || "not_evaluated")}”。`
    : "本轮已生成可追溯交付产物；是否发布仍以完整评测证据为准。";
  const artifactStatus = bundle ? `${bundle.release_ready ? "可进入交付审阅" : "交付包已生成"} · ${bundle.manifest?.files?.length || 0} 个文件` : "评测报告已就绪";
  const primaryRef = evaluationRef || bundleRef;
  return {
    conclusion,
    metrics: terminalResultMetrics(task, result),
    artifactStatus,
    state: report?.release_ready === true || bundle?.release_ready === true ? "ready" : "review",
    taskId: task.task_id,
    runId: result.run_id,
    cta: bundle && state.runtimeReady ? { kind: "download", label: "下载现有交付包", bundle } : { kind: "open", label: "打开结果", ref: primaryRef },
  };
}
function appendTerminalResultCard(item, target, projection) {
  const model = terminalResultCardModel(item, projection); if (!model) return false;
  const card = document.createElement("section"); card.className = "turn-result-card"; card.dataset.state = model.state; card.dataset.interactionKind = "result-summary";
  const header = document.createElement("header"); const heading = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "RESULT"; const title = document.createElement("h3"); title.textContent = "本轮结果"; heading.append(kicker, title); const stateLabel = document.createElement("b"); stateLabel.textContent = model.artifactStatus; header.append(heading, stateLabel);
  const conclusion = document.createElement("p"); conclusion.className = "turn-result-conclusion"; conclusion.textContent = model.conclusion; card.append(header, conclusion);
  if (model.metrics.length) {
    const metrics = document.createElement("dl"); metrics.className = "turn-result-metrics";
    model.metrics.forEach((metric) => { const row = document.createElement("div"); if (metric.passed !== null) row.dataset.passed = String(metric.passed); const term = document.createElement("dt"); term.textContent = metric.label; const value = document.createElement("dd"); const actual = document.createElement("b"); actual.textContent = metric.value; const gate = document.createElement("small"); gate.textContent = metric.gate ? `门槛 ${metric.gate}` : "当前评测值"; value.append(actual, gate); row.append(term, value); metrics.append(row); });
    card.append(metrics);
  }
  const footer = document.createElement("footer"); const hint = document.createElement("span"); hint.textContent = "完整证据与身份信息保留在任务工作区"; const action = document.createElement("button"); action.type = "button"; action.textContent = model.cta.label;
  action.addEventListener("click", () => {
    if (state.selectedTaskId !== model.taskId || state.task?.current_result?.run_id !== model.runId) { showNotice("结果身份已经变化，已停止操作。请刷新当前任务后重新打开结果。", "error"); return; }
    if (model.cta.kind === "download") requestArtifactBundleDownload({ run_id: model.runId }, model.cta.bundle); else openObjectRef(model.cta.ref);
  });
  footer.append(hint, action); card.append(footer); target.append(card); return true;
}
function finalSynthesisFallbackRefs(item) {
  return (item?.object_refs || []).filter((ref) => !TERMINAL_RESULT_REF_TYPES.has(ref?.type));
}
function renderFinalSynthesis(item, target = ui.messageList) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "assistant"; row.dataset.messageType = "final_synthesis"; row.dataset.interactionKind = "natural-dialogue"; const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "AI";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "AI"; const time = document.createElement("time"); time.textContent = formatTime(item.time); meta.append(author, time);
  const copy = document.createElement("div"); copy.className = "message-copy"; renderRichText(copy, item.text || item.summary || "AI 没有返回综合结论。"); body.append(meta, copy);
  const projection = interactionProjection(state.task, conversationView(state.task, state.conversation)); if (!appendTerminalResultCard(item, body, projection)) appendObjectRefs(body, finalSynthesisFallbackRefs(item));
  row.append(avatar, body); target.append(row);
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
function renderCoordinatorNote(item, target = ui.messageList) {
  const row = document.createElement("article"); row.className = "message"; row.dataset.role = "assistant"; row.dataset.messageType = "coordinator_note"; row.dataset.interactionKind = "natural-dialogue";
  const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = "AI";
  const body = document.createElement("div"); body.className = "message-body"; const meta = document.createElement("div"); meta.className = "message-meta"; const author = document.createElement("b"); author.textContent = "AI"; const time = document.createElement("time"); time.textContent = formatTime(item.time); meta.append(author, time);
  const content = item.text || item.summary || "AI 没有提供说明。"; body.append(meta);
  // Answer visibility is independent from evidence-backed training completion.
  const copy = document.createElement("div"); copy.className = "message-copy"; renderRichText(copy, humanizeCoordinatorText(content)); body.append(copy);
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
  // The approval subject is a typed runtime fact, never inferred from prose.
  const raw = String(item?.tool_name || item?.name || "").toLowerCase();
  if (raw === "model_harness_acquire_execution_asset") return { header: "等待获取模型文件", title: "获取这组固定版本的模型文件", copy: "仅下载指定公开来源的文件并校验摘要，不执行代码或启动训练。许可信息未明确时仍需核对使用范围。", allow: "批准获取文件", reject: "暂不获取" };
  if (raw === "model_harness_qualify_execution_proposal") return { header: "等待验证工程方案", title: "在隔离环境中验证这份代码", copy: item?.reason || item?.payload?.reason || "此审批没有完整记录资源范围，请先核对对应工程方案的实际镜像、挂载与资格验证限额。", allow: "批准本次工程验证", reject: "暂不验证" };
  if (raw === "model_harness_activate_execution_proposal") return { header: "等待启用工程方案", title: "启用这份已验证的方案", copy: "将对应的方案与验证证据绑定到当前数据集和训练合同；不会确认合同或启动训练。", allow: "批准启用方案", reject: "暂不启用" };
  if (raw === "model_harness_bind_model_source") return { header: "等待确认来源", title: "确认绑定来源并做静态分析", copy: "批准只会绑定已解析的不可变来源，并读取公开源文件保存静态分析证据；不代表批准下载权重、安装代码或训练。", allow: "确认绑定并分析", reject: "暂不绑定" };
  if (raw === "model_harness_decide_training_plan") return { header: "等待确认计划", title: "确认这版执行计划", copy: "请核对计划版本、资源和安全边界；计划批准不等同于运行或能力注册批准。", allow: "确认当前计划", reject: "返回修改" };
  if (raw === "model_harness_register_recipe") return { header: "等待批准注册", title: "批准注册这份已验证能力", copy: "注册必须匹配本次真实验证证据与摘要，不会自动启动训练。", allow: "批准本次注册", reject: "暂不注册" };
  if (raw === "model_harness_check_resource_feasibility") return { header: "等待资源检查", title: "批准检查本机资源条件", copy: "按当前已批准计划记录机器与隔离环境情况；探测到 GPU 不代表当前执行器能使用它。", allow: "批准资源检查", reject: "暂不检查" };
  if (["model_harness_authorize_task_run_start", "model_harness_start_task_run"].includes(raw)) return { header: "等待开始训练", title: "开始这次训练", copy: "使用已确认的数据与方案，进行一次模型训练和独立测试。", allow: "开始训练", reject: "稍后" };
  if (raw === "model_harness_confirm_contract") return { header: "等待确认标准", title: "确认训练目标与标准", copy: "核对这次训练的数据、效果标准和资源预算。后续将按这版标准评估结果。", allow: "确认标准", reject: "调整要求" };
  if (["model_harness_authorize_sample_inference", "model_harness_run_sample_inference"].includes(raw)) return { header: "等待试用", title: "试用这份新输入", copy: "使用当前训练好的模型生成一次结果，不会重新训练或修改模型。", allow: "开始试用", reject: "稍后" };
  if (raw === "model_harness_download_artifact_bundle") return { header: "等待下载", title: "下载模型包", copy: "将已核验的 ZIP 保存为下方的新文件，不会覆盖已有文件。", allow: "下载模型包", reject: "稍后" };
  if (["model_harness_authorize_artifact_bundle_build", "model_harness_build_artifact_bundle"].includes(raw)) return { header: "等待保存模型", title: "保存模型与评估结果", copy: "将模型、评估结果和试用输出打包为 ZIP，便于下载和复用。不包含原始训练数据文件。", allow: "生成模型包", reject: "稍后" };
  if (raw === "model_harness_import_material_dataset") return { header: "等待导入数据", title: "复用已上传材料导入", copy: "按已确认的任务版本和字段选择，将这份已检查材料导入训练数据集并进行体检，无需重新上传；本次批准不会启动训练。", allow: "批准导入并体检", reject: "暂不导入" };
  if (raw === "model_harness_import_dataset") return { header: "等待导入数据", title: "批准导入并体检这份数据", copy: "系统会按当前任务的数据合同读取文件，并留下可追溯的数据指纹。", allow: "批准并继续", reject: "暂不导入" };
  return { header: "等待你的批准", title: item?.title || "批准关键操作", copy: item?.reason || item?.summary || "协调器请求执行会改变任务状态的操作。", allow: "批准并继续", reject: "暂不执行" };
}
function contractApprovalSummary(task) {
  const report = task?.dataset_report; const contract = task?.contract; if (!report && !contract) return [];
  const rows = [];
  if (report?.target_column) rows.push(["预测列", report.target_column]);
  if (report) {
    const [count, summary] = datasetDetail(task);
    rows.push(["数据", [count, summary, report.source_filename || ""].filter(Boolean).join(" · ")]);
    const classes = Object.entries(report.class_counts || {});
    if (classes.length) rows.push(["类别分布", classes.slice(0, 8).map(([label, count]) => `${label}：${count}`).join("，") + (classes.length > 8 ? `，另有 ${classes.length - 8} 类` : "")]);
  }
  const gates = gateEntries(contract?.release_gates || {}, contract?.execution_spec?.evaluation?.gates).filter(([value]) => typeof value === "number");
  const gateNumber = value => contract?.execution_spec ? String(value) : value.toFixed(2);
  const gateText = ([value, label]) => label.endsWith(" 上限") ? `${label.slice(0, -3)} ≤ ${gateNumber(value)}` : `${label.replace(/ 下限$/, "")} ≥ ${gateNumber(value)}`;
  if (gates.length) rows.push(["验收门槛", gates.map(gateText).join("，")]);
  const bundle = contract?.execution_spec?.bundle, limits = bundle?.limits;
  if (limits) {
    rows.push(["执行资源", `${limits.cpus} 核 CPU · ${formatBytes(limits.memory_bytes)} 内存`]);
    rows.push(["时间上限", ["train", "evaluate", "predict"].map(stage => `${({ train: "训练", evaluate: "评估", predict: "新输入预测" })[stage]} ${bundle.stage_limits?.[stage]?.timeout_seconds ?? limits.timeout_seconds} 秒`).join(" · ")]);
  }
  return rows;
}
function appendApprovalScope(card, item) {
  const raw = String(item?.tool_name || item?.name || "").toLowerCase();
  const contractRows = ["model_harness_confirm_contract", "model_harness_authorize_task_run_start", "model_harness_start_task_run"].includes(raw) ? contractApprovalSummary(state.task) : [];
  const executionRows = [];
  if (["model_harness_qualify_execution_proposal", "model_harness_activate_execution_proposal", "model_harness_acquire_execution_asset", "model_harness_download_artifact_bundle"].includes(raw)) {
    const calls = (state.conversation?.events || []).filter(event => event.event_type === "tool_call" && event.task_id === state.selectedTaskId && event.payload?.tool_name === raw && ["session_id", "agent_run_id", "turn_id", "call_id"].every(key => item[key] && event[key] === item[key]));
    if (calls.length === 1) { try {
      const args = typeof calls[0].payload.arguments === "string" ? JSON.parse(calls[0].payload.arguments) : calls[0].payload.arguments;
      if (args?.task_id === state.selectedTaskId) {
        executionRows.push(["工程方案", args.proposal_id], ["代码与配置摘要", args.expected_proposal_sha256], ["验证记录", args.qualification_id], ["验证摘要", args.expected_qualification_sha256], ["使用范围", args.local_experiment_only === true ? "仅本地试验" : undefined], ["模型来源", args.repository], ["固定版本", args.revision], ["文件清单", Array.isArray(args.files) ? args.files.join("、") : undefined]);
        if (raw === "model_harness_download_artifact_bundle") executionRows.push(["保存文件", String(args.destination_path || "").split(/[\\/]/).at(-1)], ["保存位置", /^[\\/]|^[A-Za-z]:/.test(args.destination_path || "") ? "指定的本机位置" : "本地工作区导出目录"], ["交付包", args.bundle_id], ["文件摘要", args.archive_sha256], ["清单摘要", args.manifest_sha256]);
      }
    } catch (_error) {} }
  }
  const fields = [
    ...contractRows, ...executionRows,
    ["方案版本", item.plan_revision || item.recipe_revision || item.contract_revision],
    ["数据指纹", item.dataset_fingerprint || item.data_fingerprint],
    ["批准摘要", item.approval_digest || item.contract_digest || item.digest],
    ["作用范围", item.approval_scope || item.scope],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!fields.length) return;
  const list = document.createElement("dl"), proofList = document.createElement("dl"); list.className = proofList.className = "approval-scope";
  fields.forEach(([label, value]) => { const row = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const detail = document.createElement("dd"); detail.textContent = String(value); row.append(term, detail); (/摘要|指纹|版本|工程方案|验证记录|交付包/.test(label) ? proofList : list).append(row); });
  if (list.childElementCount) card.append(list);
  if (proofList.childElementCount) { const details = document.createElement("details"), summary = document.createElement("summary"); summary.textContent = "核对版本与文件摘要"; details.append(summary, proofList); card.append(details); }
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
  const header = document.createElement("header"); const heading = document.createElement("div"); const kicker = document.createElement("span"); kicker.textContent = "本轮计划"; const title = document.createElement("h3"); title.textContent = item.title || "接下来这样推进"; heading.append(kicker, title); const status = document.createElement("b"); status.textContent = eventStatusLabel(item.status); header.append(heading, status); card.append(header);
  if (item.summary) { const summary = document.createElement("div"); summary.className = "coordinator-plan-summary"; renderRichText(summary, item.summary); card.append(summary); }
  const steps = Array.isArray(item.steps) ? item.steps : Array.isArray(item.plan?.steps) ? item.plan.steps : [];
  if (steps.length) { const list = document.createElement("ol"); list.className = "coordinator-plan-steps"; steps.forEach((step) => { const row = document.createElement("li"); row.dataset.status = step.status || "queued"; const mark = document.createElement("i"); mark.textContent = step.status === "completed" ? "✓" : step.status === "failed" ? "!" : String(step.order || step.index || list.children.length + 1); const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = step.title || step.goal || "计划步骤"; const owner = document.createElement("small"); owner.textContent = roleLabel(step.owner_role || step.role); copy.append(name, owner); row.append(mark, copy); list.append(row); }); card.append(list); }
  appendObjectRefs(card, item.object_refs); target.append(card);
}
function coordinatorProgressPresentation(item, canonical = null) {
  if (item.truthConflict) return { label: "状态说明已降级", hint: `与“${item.failedActionTitle || "失败工具"}”的真实证据冲突`, action: "不作为状态", tone: "failed" };
  const byCanonicalPhase = ({
    observation_degraded: { label: "当前计划", hint: "计划状态不可确认 · 需要重新连接", action: "查看" },
    stopping: { label: "当前计划", hint: "正在停止", action: "展开" },
    waiting_question: { label: "本轮计划", hint: "计划步骤已处理 · 等待你的回答", action: "查看" },
    waiting_approval: { label: "本轮计划", hint: "计划步骤已处理 · 等待你的批准", action: "查看" },
    agent_working: { label: "当前计划", hint: "计划仍在推进 · AI 正在处理", action: "展开" },
    background_working: { label: "当前计划", hint: "计划仍在推进 · 后台操作进行中", action: "展开" },
    blocked: { label: "本轮计划", hint: "计划已暂停 · 当前受阻", action: "查看" },
    failed: { label: "本轮计划", hint: "计划已停止 · 运行异常", action: "查看" },
    stopped: { label: "本轮计划", hint: "本轮已停止", action: "查看" },
    completed: { label: "本轮计划", hint: "已全部完成", action: "查看" },
  })[canonical?.phase];
  if (byCanonicalPhase) return { ...byCanonicalPhase, tone: canonical.tone };
  const completed = item.status === "completed";
  return {
    label: completed ? "本轮计划" : "当前计划",
    hint: completed ? "已全部完成" : item.title || "正在梳理下一步",
    action: completed ? "查看" : "展开",
    tone: completed ? "completed" : item.status || "unknown",
  };
}
function renderCoordinatorProgress(item, target = ui.messageList) {
  const canonical = item.currentInteraction ? canonicalInteractionPresentation(state.conversation) : null;
  const presentation = coordinatorProgressPresentation(item, canonical);
  const details = document.createElement("details"); details.className = "coordinator-progress"; details.dataset.status = presentation.tone; details.dataset.planStatus = item.status; details.dataset.interactionKind = "lightweight-plan"; details.dataset.truthConflict = String(Boolean(item.truthConflict));
  const summary = document.createElement("summary"); const copy = document.createElement("span"); const label = document.createElement("b"); label.textContent = presentation.label; const hint = document.createElement("small"); hint.textContent = presentation.hint; copy.append(label, hint); const stateLabel = document.createElement("em"); stateLabel.textContent = presentation.action; summary.append(copy, stateLabel); details.append(summary);
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
function tabularSamplePlaceholder(task) {
  const columns = (task?.dataset_report?.feature_columns || []).slice(0, 4);
  if (!columns.length) return '{"feature_a": 1.2, "feature_b": 3.4}';
  const more = (task.dataset_report.feature_columns.length > columns.length) ? ", …" : "";
  return `{${columns.map((column) => `${JSON.stringify(column)}: …`).join(", ")}${more}}`;
}
function appendInferenceInputActions(actions, checkpoint) {
  actions.classList.add("data-upload-actions", "inference-input-actions");
  const result = state.task?.current_result; const sampleType = sampleTypeForTask(state.task); const generic = genericInferenceSpec(state.task);
  const hint = document.createElement("small"); hint.textContent = "样本只会成为当前任务和 Run 的一次性输入对象；对话里不会出现本机路径，真正执行前仍需你批准。";
  if (genericUsesFields(generic)) {
    const fields = document.createElement("div"); fields.className = "generic-sample-fields"; const read = genericInputEditor(fields, generic.schema);
    const submit = document.createElement("button"); submit.type = "button"; submit.className = "checkpoint-upload-button"; submit.textContent = "暂存这条新样本";
    submit.addEventListener("click", async () => { let input; try { input = genericInputPayload(read(), generic); } catch (error) { showNotice(error.message); return; } setButtonBusy(submit, true, "正在安全暂存"); try { const staged = await stageInferenceInput({ ...input, sampleType: "generic" }); await continueWithInferenceInput(staged, checkpoint); } catch (error) { showNotice(error.message); } finally { setButtonBusy(submit, false, ""); } });
    actions.append(fields, submit, hint); return;
  }
  if (sampleType === "tabular") {
    const input = document.createElement("textarea"); input.className = "question-custom inference-sample-json"; input.rows = 3; input.placeholder = tabularSamplePlaceholder(state.task); input.setAttribute("aria-label", "输入一行新的表格样本 JSON");
    const submit = document.createElement("button"); submit.type = "button"; submit.className = "checkpoint-upload-button"; submit.textContent = "暂存这条新样本";
    submit.addEventListener("click", async () => {
      let body;
      if (!input.value.trim()) { showNotice("请先填入一行新样本，字段名与训练时的特征列一致。"); input.focus(); return; }
      try { const value = JSON.parse(input.value); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 必须是一行对象"); body = JSON.stringify(value); }
      catch (error) { showNotice(`请输入有效的一行 JSON：${error.message}`); input.focus(); return; }
      setButtonBusy(submit, true, "正在安全暂存");
      try { const staged = await stageInferenceInput({ body, filename: "new-sample.json", contentType: "application/json", sampleType }); await continueWithInferenceInput(staged, checkpoint); }
      catch (error) { showNotice(`新样本暂存失败：${error.message}`); }
      finally { setButtonBusy(submit, false, ""); }
    });
    actions.append(input, submit, hint); return;
  }
  const picker = document.createElement("input"); picker.type = "file"; picker.hidden = true; picker.accept = generic ? generic.extensions.join(",") : sampleType === "image" ? "image/png,image/jpeg,image/webp,image/bmp" : sampleType === "audio" ? ".wav,audio/wav" : "";
  const choose = document.createElement("button"); choose.type = "button"; choose.className = "checkpoint-upload-button"; choose.textContent = sampleType === "image" ? "选择一张新图片" : sampleType === "audio" ? "选择一段新 WAV" : "选择新样本";
  choose.addEventListener("click", () => { picker.value = ""; picker.click(); });
  picker.addEventListener("change", async () => {
    const file = picker.files?.[0]; if (!file || !sampleType) return;
    if (generic) { try { checkGenericInputFile(file, generic); } catch (error) { showNotice(error.message); return; } }
    setButtonBusy(choose, true, "正在安全暂存");
    try { const staged = await stageInferenceInput({ body: file, filename: file.name, contentType: file.type || (sampleType === "audio" ? "audio/wav" : "application/octet-stream"), sampleType }); await continueWithInferenceInput(staged, checkpoint); }
    catch (error) { showNotice(`新样本暂存失败：${error.message}`); }
    finally { setButtonBusy(choose, false, ""); }
  });
  actions.append(picker, choose, hint);
}
function renderHumanCheckpoint(item, { interactive = true, target = ui.messageList } = {}) {
  const card = document.createElement("article"); card.className = "decision-card human-checkpoint"; card.dataset.status = item.status; card.dataset.interactionKind = "human-checkpoint"; if (item.rpc_id) card.dataset.rpcId = item.rpc_id; card.tabIndex = -1; const pending = item.status === "pending" || item.status === "waiting" || !item.status; const discussing = state.messageSubmission?.status === "sending" && state.messageSubmission?.checkpoint_rpc_id === item.rpc_id; const canRespond = pending && interactive && state.runtimeReady && state.conversation?.pending_observed !== false && !discussing; card.dataset.interactive = String(canRespond); const uploadCheckpoint = canRespond ? dataUploadQuestionCheckpoint(item) : null; const inferenceCheckpoint = canRespond ? inferenceInputQuestionCheckpoint(item) : null; const approval = item.kind === "approval" ? approvalPresentation(item) : null;
  if (uploadCheckpoint) card.classList.add("data-upload-checkpoint");
  if (inferenceCheckpoint) card.classList.add("inference-input-checkpoint");
  const inspectMaterials = Boolean(uploadCheckpoint && materialInspectionMode());
  const format = uploadCheckpoint ? datasetUploadFormat(state.task, uploadCheckpoint) : null;
  const cancelling = state.cancelRequestInFlight === true || backgroundCancellationPending(state.conversation);
  const kicker = document.createElement("span"); kicker.textContent = cancelling && pending ? "正在停止 · 暂不可操作" : (!interactive || !state.runtimeReady) && pending ? "连接恢复后再处理" : uploadCheckpoint ? "下一步：准备数据" : inferenceCheckpoint ? "下一步：验证新样本" : pending ? item.kind === "approval" ? "需要你的批准" : "需要你的回答" : "人工检查点已处理";
  const title = document.createElement("h3"); title.textContent = inspectMaterials ? "上传材料，先检查文件和标注" : uploadCheckpoint ? format === "zip" ? "选择按类别整理的数据 ZIP" : "选择数据文件，系统会先识别字段" : inferenceCheckpoint ? "选择一份没参与训练的新样本" : item.kind === "approval" ? approval.title : item.title || item.questions?.[0]?.header || "补充训练信息";
  const copy = document.createElement("p"); copy.textContent = cancelling && pending ? "停止请求已经提交。为避免旧确认继续改变任务，本卡会在后端确认最终状态前保持只读。" : (!interactive || !state.runtimeReady) && pending ? "当前连接或观察链路不完整，这个待办可能已经变化。请先重新连接并刷新，恢复后再作答。" : inspectMaterials ? "选择 CSV、JSONL 或 ZIP，系统会生成只读材料检查报告；这不会创建训练数据集、启动训练或批准执行。" : uploadCheckpoint ? format === "zip" ? "每个类别放在一个子目录，再将这些目录打包为 ZIP。系统会检查文件、标签、样本数量和重复情况。" : "选择 CSV 后，我会先读取真实表头并推荐预测列；你确认后再导入和体检，不需要手填电脑路径。" : inferenceCheckpoint ? "先提供一份全新的样本。系统只做安全暂存；协调器核对范围并征得你批准后，才会交给评测专家执行。" : item.kind === "approval" ? approval.copy : item.summary || item.questions?.[0]?.question || "请回答协调器提出的问题。"; card.append(kicker, title, copy);
  if (item.kind === "approval") { copy.setAttribute("style", "white-space: pre-line"); appendApprovalScope(card, item); }
  if (canRespond && item.rpc_id) {
    const actions = document.createElement("div"); actions.className = "decision-actions";
    if (item.kind === "approval") { const allow = document.createElement("button"); allow.type = "button"; allow.textContent = approval.allow; const reject = document.createElement("button"); reject.type = "button"; reject.textContent = approval.reject; allow.addEventListener("click", () => answerApproval(item, "allowed-once", allow)); reject.addEventListener("click", () => answerApproval(item, "rejected", reject)); actions.append(allow, reject); }
    else if (uploadCheckpoint) {
      actions.classList.add("data-upload-actions"); const choose = document.createElement("button"); choose.type = "button"; choose.className = "checkpoint-upload-button"; choose.textContent = inspectMaterials ? "选择材料文件" : format === "zip" ? "选择 ZIP 文件" : format === "csv" ? "选择 CSV 文件" : "选择 CSV 或 ZIP 文件"; choose.addEventListener("click", () => { ui.datasetInput.accept = inspectMaterials ? ".csv,.jsonl,.zip" : format === "zip" ? ".zip" : format === "csv" ? ".csv" : ".csv,.zip"; ui.datasetInput.value = ""; ui.datasetInput.click(); }); const hint = document.createElement("small"); hint.textContent = inspectMaterials ? "检查完成后会把真实材料编号交给 AI 读取报告；不会将它当作训练数据集编号。" : format === "zip" ? "页面不会展示本机路径；协调器会收到导入后的数据集编号并读取体检摘要。" : "页面不会展示本机路径；协调器会收到导入后的数据集编号、你选择的预测列，并读取字段与体检摘要。"; actions.append(choose, hint);
      if (!inspectMaterials) (state.materialsOwnerId === state.selectedTaskId ? state.materialInspections || [] : []).forEach(record => appendReusableMaterialButton(actions, record));
    } else if (inferenceCheckpoint) appendInferenceInputActions(actions, inferenceCheckpoint);
    else {
      const question = item.questions?.length === 1 ? item.questions[0] : null; const options = question?.options || []; const inline = question && !question.multiSelect && options.length >= 2 && options.length <= 4;
      if (inline) {
        actions.classList.add("human-choice-list");
        options.forEach((option) => { const presentation = optionPresentation(option.label); const button = document.createElement("button"); button.type = "button"; button.className = "human-choice"; button.dataset.recommended = String(presentation.recommended); const label = document.createElement("b"); label.textContent = presentation.label; const detail = document.createElement("small"); detail.textContent = option.description || "选择后，协调器会按这条路径继续。"; button.append(label, detail); button.addEventListener("click", async () => { const buttons = [...actions.querySelectorAll("button")]; buttons.forEach((candidate) => { candidate.disabled = true; }); button.setAttribute("aria-busy", "true"); try { await postQuestionAnswers(item, [{ id: question.id, selected: [option.label] }]); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); buttons.forEach((candidate) => { candidate.disabled = false; }); } finally { button.removeAttribute("aria-busy"); } }); actions.append(button); });
        const custom = document.createElement("button"); custom.type = "button"; custom.className = "human-choice-custom"; custom.textContent = "填写其他答案"; custom.addEventListener("click", () => openQuestionDialog(item)); actions.append(custom);
      } else { const answer = document.createElement("button"); answer.type = "button"; answer.textContent = "填写回答"; answer.addEventListener("click", () => openQuestionDialog(item)); actions.append(answer); }
    }
    card.append(actions);
    const discussion = document.createElement("p"); discussion.className = "checkpoint-discussion-hint"; discussion.textContent = "也可以在下方讨论；发送消息会暂缓当前操作，不会代你批准。"; card.append(discussion);
  }
  appendObjectRefs(card, item.object_refs); target.append(card);
}
function terminalEventScope(item) {
  if (!item?.session_id || !item?.root_session_id) return "unknown";
  if (item.session_id !== item.root_session_id) return "specialist";
  return item.delegation_id ? "unknown" : "root";
}
function providerErrorPresentation(item, { turnStopped = false } = {}) {
  const errors = [item?.error, item?.payload?.error].filter(error => error && typeof error === "object");
  const texts = [item?.summary, item?.text, item?.reason, item?.payload?.text, ...errors.map(error => error.message), typeof item?.error === "string" ? item.error : null].filter(text => typeof text === "string" && text.trim());
  const explicitBalance = texts.some(text => /\binsufficient[ _-]+balance\b/i.test(text)) || errors.some(error => /^insufficient[_-]balance$/i.test(error.code || ""));
  const nativeModelError = ["turn_error", "failed"].includes(item?.kind) || errors.some(error => ["dsh_turn_end", "dsh_event", "provider", "model_provider"].includes(error.source));
  const providerStatus = nativeModelError && errors.some(error => [error.status, error.status_code, error.http_status].some(status => status === 402));
  const contextOverflow = nativeModelError && (errors.some(error => ["CONTEXT_WINDOW_EXCEEDED", "CONTEXT_BUDGET"].includes(error.code)) || texts.some(text => /model input exceeds (?:the verified|the route) text budget|context window exceeded/i.test(text)));
  const missingModelKey = nativeModelError && texts.some(text => /no API key for provider route/i.test(text));
  if (!explicitBalance && !providerStatus && !contextOverflow && !missingModelKey) return null;
  const technical = [...new Set([...texts, ...errors.flatMap(error => [
    ...["status", "status_code", "http_status", "code", "request_id", "requestId"].filter(key => error[key] !== undefined && error[key] !== null).map(key => `${key}: ${String(error[key])}`),
  ])])].join("\n");
  if (contextOverflow) return { title: "这段对话暂时无法继续", message: "这段对话超过模型的处理预算，本次回复未完成。已保存的任务和模型仍可查看，可以重试继续。", technical };
  if (missingModelKey) return { title: "AI 服务尚未配置完成", message: "当前选择的 AI 服务缺少登录或密钥配置，本次回复未完成。请检查服务配置后继续；已有材料和模型会保留。", technical };
  return { title: "模型账户余额不足", message: turnStopped ? "模型账户余额不足，当前回合已停止；恢复额度后继续。" : "模型账户余额不足，本次模型调用未完成；恢复额度后继续。", technical };
}
function appendProviderErrorDetails(container, presentation) {
  if (!presentation?.technical) return;
  const details = document.createElement("details"); details.className = "provider-error-details";
  const summary = document.createElement("summary"); summary.textContent = "技术详情";
  const copy = document.createElement("pre"); copy.textContent = presentation.technical;
  details.append(summary, copy); container.append(details);
}
function renderTurnTerminal(item, target = ui.messageList) {
  const scope = terminalEventScope(item);
  const provider = item.kind === "turn_error" ? providerErrorPresentation(item, { turnStopped: scope === "root" }) : null;
  if (scope !== "root") {
    const card = document.createElement("details"); card.className = "turn-terminal"; card.dataset.status = item.kind === "turn_cancelled" ? "cancelled" : "failed"; card.dataset.terminalScope = scope;
    const title = document.createElement("summary"); title.textContent = scope === "specialist" ? `${roleLabel(item.actor_role)}的本次执行${item.kind === "turn_cancelled" ? "已停止" : "失败"}` : "执行终止记录（归属待核对）";
    const copy = document.createElement("p"); copy.textContent = `这是${scope === "specialist" ? "专家执行" : "归属未确认的执行"}记录，不代表协调器回合已停止。${provider?.message || `原始原因：${item.summary || item.reason || item.error?.message || "运行时未提供原因"}`}`;
    card.append(title, copy); appendProviderErrorDetails(card, provider); appendObjectRefs(card, item.object_refs); target.append(card); return;
  }
  const reasonCode = item.reason_code || item.cancellation_reason || item.error?.code || "";
  if (item.kind === "turn_cancelled" && item.payload?.reason === "checkpoint_discussion") {
    const note = document.createElement("p"); note.className = "checkpoint-discussion-hint";
    note.textContent = "已暂缓这次确认，继续讨论；没有提交答案或批准。"; target.append(note); return;
  }
  const cancelledTitles = { user_cancelled: "你已停止本轮智能体", safety_stop: "安全检查停止了本轮执行", tool_rejected: "关键操作未获批准，本轮已停止", timeout: "等待超时，本轮已停止", stopped_with_checkpoint: "本轮已停在人工确认点" };
  const card = document.createElement("article"); card.className = "turn-terminal"; card.dataset.status = item.kind === "turn_cancelled" ? reasonCode || "stopped" : "failed"; const title = document.createElement("b"); title.textContent = item.kind === "turn_cancelled" ? cancelledTitles[reasonCode] || "本轮智能体已停止" : provider?.title || "本轮智能体执行失败"; const copy = document.createElement("p"); copy.textContent = provider?.message || item.summary || item.reason || item.error?.message || "运行时没有提供失败原因。"; card.append(title, copy); appendProviderErrorDetails(card, provider); appendObjectRefs(card, item.object_refs); appendRecoveryActions(card, item); target.append(card);
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
  if (type === "execution_proposal") return `/tasks/${taskId}/execution-proposals/${id}`;
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
  if (type === "inference_input" && runId) return `/tasks/${taskId}/runs/${runId}/inference-inputs/${id}`;
  if (type === "resource_feasibility") {
    const kind = resourceRefKind(ref); if (kind === "resource_probe") return `/tasks/${taskId}/resource-probes/${id}`; if (kind === "environment_lock") return `/tasks/${taskId}/environment-locks/${id}`; if (kind === "resource_fit_report") return `/tasks/${taskId}/resource-fit-reports/${id}`;
  }
  return null;
}
function objectViewerPresentation(ref, payload) {
  const type = normalizeObjectRefType(ref?.type);
  if (type === "execution_proposal" && payload?.proposal) {
    const proposal = payload.proposal, qualification = payload.qualification || proposal.qualification, bundle = proposal.execution_spec?.bundle || {};
    return { title: "工程方案与验证", rows: [["方案状态", ({ proposed: "代码已保存", qualifying: "隔离验证中", qualified: "隔离验证通过", qualification_failed: "隔离验证未通过", activated: "已启用，训练仍需单独确认" })[proposal.status] || proposal.status], ["代码文件", `${Object.keys(bundle.files || {}).length} 份`], ["运行镜像", bundle.image || "未记录"], ["资源限制", `${formatBytes(bundle.limits?.memory_bytes)} · ${bundle.limits?.cpus ?? "—"} CPU · ${bundle.limits?.timeout_seconds ?? "—"} 秒`], ["验证状态", qualification?.status || "未验证"], ["验证问题", qualification?.failure || "未记录问题"]], note: "工程验证与正式训练分别记录；日志、检查和源代码可在原始证据中核对。", files: Object.keys(bundle.files || {}) };
  }
  if (type === "blocker" && payload?.blocker) {
    const blocker = payload.blocker;
    if (["recipe_unavailable", "verified_recipe_unavailable"].includes(blocker.code)) return { title: "方案匹配记录", rows: [["匹配结果", "当时未匹配到现成训练方案"], ["下一步", "继续准备训练路线、数据要求和资源预算"], ["记录阶段", blocker.stage || "未记录"], ["本记录是否授予运行许可", "否"]], note: "这份记录保留目录匹配事实；目标仍可继续准备方案，实际运行需单独核验与批准。原始代码与身份见技术详情。", files: [] };
    return { title: "当前阻断原因", rows: [["诊断结果", blocker.message || "未记录原因"], ["阻断类型", blocker.code || "未记录"], ["发生阶段", blocker.stage || "未记录"], ["是否允许创建训练", blocker.rule?.run_creation_allowed === false ? "不允许" : "须另行核对执行门槛"]], note: "阻断证据说明当前不能继续的原因，不是训练成功。复核或更换方案不会自动获得执行许可。", files: [] };
  }
  if (type === "inference_input" && payload?.inference_input) {
    const input = payload.inference_input;
    return { title: "独立推理样本", rows: [["文件", input.filename || "未记录"], ["样本类型", input.sample_type || "未记录"], ["使用状态", ({ staged: "待试跑", consumed: "已用于试跑", consuming: "试跑中", failed: "试跑失败" })[input.status] || input.status || "未记录"], ["试跑记录", input.outcome?.sample_inference_check_id || "未记录"]], note: "这里只展示这条输入的保存与使用记录，不代表预测准确度。没有参考答案的试跑只能验证执行链路。", files: [] };
  }
  if (type === "artifact_bundle" && payload?.artifact_bundle) {
    const bundle = payload.artifact_bundle; const manifest = bundle.manifest || {}; const privacy = manifest.privacy_boundary || {};
    const files = Array.isArray(manifest.files) ? manifest.files.filter((file) => typeof file?.path === "string") : [];
    const privacyKnown = ["raw_data_included", "test_references_included", "internal_state_included"].every((key) => privacy[key] === false);
    return { title: "模型交付包", rows: [
      ["生成状态", bundle.status === "completed" ? "已生成" : bundle.status || "未记录"],
      ["文件大小", Number.isFinite(bundle.archive?.size_bytes) ? `${(bundle.archive.size_bytes / 1024).toFixed(1)} KB` : "未记录"],
      ["文件数量", `${files.length} 项（另附清单）`],
      ["发布审阅", bundle.release_ready === true ? "评测允许进入审阅，尚不代表已发布" : "未确认满足发布门槛"],
    ], note: privacyKnown ? "清单确认未打包原始数据文件、最终测试集引用文件或内部运行状态。模型内部的数据上下文仍需单独审查。" : "隐私排除项未完整确认，请展开原始证据核对后再分享。", files: files.map((file) => file.path) };
  }
  if (type === "evaluation_report" && payload?.evaluation_report) {
    const report = payload.evaluation_report; const checks = Array.isArray(report.integrity_checks) ? report.integrity_checks : []; const gates = Object.entries(report.metric_gates || {});
    return { title: "可信评测报告", rows: [
      ["评测结论", report.release_ready === true ? "允许进入发布审阅" : report.conclusion || "未记录"],
      ["证据完整性", `${checks.filter((item) => item.passed === true).length} / ${checks.length} 项通过`],
      ["指标门槛", `${gates.filter(([, passed]) => passed === true).length} / ${gates.length} 项通过`],
      ["最终测试样本", Number.isFinite(report.test_sample_count) ? `${report.test_sample_count} 条` : "未记录"],
      ["测试集污染", report.test_contaminated === false ? "未发现" : report.test_contaminated === true ? "已发现，不能据此发布" : "未记录"],
    ], note: "这是所选 Run 的固定评测证据。指标通过不等同于真实业务验收或生产发布。", files: [] };
  }
  return null;
}
function renderObjectViewerOverview(ref, payload) {
  clear(ui.objectViewerOverview); const presentation = objectViewerPresentation(ref, payload); ui.objectViewerOverview.hidden = !presentation;
  if (!presentation) return;
  const title = document.createElement("h3"); title.textContent = presentation.title; const list = document.createElement("dl");
  presentation.rows.forEach(([label, value]) => { const row = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const detail = document.createElement("dd"); detail.textContent = value; row.append(term, detail); list.append(row); });
  const note = document.createElement("p"); note.textContent = presentation.note; ui.objectViewerOverview.append(title, list, note);
  if (presentation.files.length) { const heading = document.createElement("h4"); heading.textContent = "包内文件"; const files = document.createElement("ul"); presentation.files.forEach((path) => { const item = document.createElement("li"); item.textContent = path; files.append(item); }); ui.objectViewerOverview.append(heading, files); }
}
function objectViewerChrome(ref, stateLabel) {
  if (stateLabel === "读取中") return { label: "读取中", state: "running" };
  if (stateLabel === "读取失败" || stateLabel === "身份不匹配" || stateLabel === "暂不支持") return { label: stateLabel, state: "failed" };
  if (stateLabel !== "读取成功") return { label: stateLabel, state: "recorded" };
  const type = normalizeObjectRefType(ref?.type);
  if (type === "blocker") return { label: "阻断证据", state: "blocked" };
  if (TERMINAL_RESULT_REF_TYPES.has(type)) return { label: "结果证据", state: "recorded" };
  return { label: "已打开记录", state: "recorded" };
}
function setObjectViewerState(ref, { stateLabel, summary, payload = null }) {
  const chrome = objectViewerChrome(ref, stateLabel);
  state.activeObjectPayload = payload; ui.objectViewerState.textContent = chrome.label; ui.objectViewerState.dataset.state = chrome.state; ui.objectViewerTitle.textContent = ref.label || `${ref.type || "对象"} · ${shortId(ref.id)}`; ui.objectViewerSummary.textContent = summary; clear(ui.objectViewerIdentity);
  const identity = [["type", ref.type], ["id", ref.id], ["task_id", ref.task_id], ["run_id", ref.run_id], ["revision", ref.revision || ref.base_spec_revision], ["digest", ref.digest || ref.semantic_digest || ref.plan_sha256 || ref.report_sha256 || ref.manifest_sha256]];
  identity.filter(([, value]) => value !== undefined && value !== null && value !== "").forEach(([label, value]) => { const row = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const detail = document.createElement("dd"); detail.textContent = String(value); row.append(term, detail); ui.objectViewerIdentity.append(row); });
  renderObjectViewerOverview(ref, payload);
  ui.objectViewerJson.textContent = payload ? JSON.stringify(payload, null, 2) : "";
  if (!payload) ui.objectViewer.querySelectorAll("details").forEach((details) => { details.open = false; });
}
function returnedObjectMatchesRef(ref, payload) {
  const type = normalizeObjectRefType(ref?.type);
  if (type === "execution_proposal") { const proposal = payload?.proposal; return Boolean(proposal && proposal.task_id === ref.task_id && proposal.proposal_id === ref.id && proposal.proposal_sha256 === ref.digest); }
  if (type === "blocker") { const blocker = payload?.blocker; return Boolean(blocker && blocker.task_id === ref.task_id && blocker.blocker_id === ref.id && typeof ref.digest === "string" && /^[a-f0-9]{64}$/.test(ref.digest) && blocker.content_digest === ref.digest); }
  if (type === "inference_input") { const input = payload?.inference_input; return Boolean(input && payload?.task?.task_id === ref.task_id && payload?.run_id === ref.run_id && input.task_id === ref.task_id && input.run_id === ref.run_id && input.inference_input_id === ref.id && input.sha256 === ref.digest); }
  if (!TERMINAL_RESULT_REF_TYPES.has(type)) return true;
  if (payload?.task?.task_id !== ref.task_id || payload?.run_id !== ref.run_id) return false;
  if (type === "evaluation_report") {
    const report = payload.evaluation_report;
    return Boolean(report && report.task_id === ref.task_id && report.run_id === ref.run_id && report.report_id === ref.id && report.report_sha256 === ref.digest);
  }
  const bundle = payload.artifact_bundle;
  return Boolean(bundle && bundle.task_id === ref.task_id && bundle.run_id === ref.run_id && bundle.bundle_id === ref.id && bundle.manifest_sha256 === ref.digest);
}
async function openObjectRef(ref) {
  const type = normalizeObjectRefType(ref?.type); const id = String(ref?.id || ref?.object_id || ""); const normalized = { ...ref, type, id };
  if (!state.selectedTaskId || !id) { showNotice("对象引用缺少当前任务或 canonical id，已拒绝打开。", "error"); return; }
  if (normalized.task_id !== state.selectedTaskId) { showNotice("这个对象不属于当前训练任务；没有切换任务，也没有展示错误对象。", "error"); return; }
  const endpoint = objectRefEndpoint(normalized); state.activeObjectRef = normalized; openInspector("object-viewer", { objectRef: normalized });
  if (!endpoint) { setObjectViewerState(normalized, { stateLabel: "暂不支持", summary: `当前版本没有 ${type || "未知类型"} 的精确读取端点；没有回退到通用方案或当前对象。` }); return; }
  const requestSeq = ++state.objectViewerRequestSeq; const taskId = state.selectedTaskId; setObjectViewerState(normalized, { stateLabel: "读取中", summary: "正在读取被点击的历史对象；不会触发新的外部调用。" });
  try { const payload = await request(endpoint); if (requestSeq !== state.objectViewerRequestSeq || taskId !== state.selectedTaskId) return; if (!returnedObjectMatchesRef(normalized, payload)) { setObjectViewerState(normalized, { stateLabel: "身份不匹配", summary: "服务端返回对象的 task、run、id 或 digest 与点击引用不一致；没有展示该对象。" }); showNotice("结果对象身份复核失败，已拒绝打开。", "error"); return; } setObjectViewerState(normalized, { stateLabel: "读取成功", summary: "以下是服务端按 canonical identity 返回的 task-owned 只读对象。", payload }); }
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
  const seen = new Set();
  const unique = refs.filter((ref) => { const key = `${ref.type || ref.object_type || ""}:${ref.id || ref.object_id || ref.digest || ref.label || ""}`; if (seen.has(key)) return false; seen.add(key); return true; });
  if (!unique.length) return; const list = document.createElement("div"); list.className = "object-ref-list"; list.dataset.interactionKind = "artifact-entry";
  unique.forEach((ref) => { const label = ref.label || `${ref.type || "对象"} · ${shortId(ref.id || ref.object_id || ref.digest)}`; if (typeof ref.url === "string" && (/^https?:\/\//.test(ref.url) || ref.url.startsWith("/"))) { const link = document.createElement("a"); link.href = ref.url; link.textContent = label; list.append(link); } else { const button = document.createElement("button"); button.type = "button"; button.textContent = label; button.addEventListener("click", () => openObjectRef(ref)); list.append(button); } }); container.append(list);
}
async function submitMessage(message) {
  const text = message.trim(); if (!text) return;
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) { saveDraft(); showNotice("正在加载当前对话，草稿已保留；加载完成后再发送。", "ok"); return; }
  let attemptedTaskId = state.selectedTaskId; clearComposerRetry("message"); hideNotice(); ui.sendButton.disabled = true; ui.sendButton.dataset.busy = "true";
  try {
    if (!state.runtimeReady) { if (state.runtimeIssue === "provider") showRuntimeSetupNotice("模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务。"); else showNotice("AI 未连接：没有创建或修改任务，也没有启动固定流程替代对话。请先恢复连接。", "error"); return; }
    if (state.conversation?.execution_state_observed === false) { showNotice("当前显示已保存的对话记录；请恢复连接后再发送，草稿会保留。", "ok"); return; }
    if (state.cancelRequestInFlight || backgroundCancellationPending(state.conversation)) { showNotice("当前执行正在停止。为避免新消息与取消请求发生竞态，请等待后端确认最终状态。", "ok"); return; }
    if (!state.selectedTaskId) {
      showNotice("正在开始对话…", "ok");
      const creation = beginTaskCreationSubmission(text);
      const pendingAttachment = state.composerAttachment?.task_id ? null : state.composerAttachment;
      try {
        const created = await request("/conversations", {
          method: "POST",
          timeoutMs: 20_000,
          json: {
            title: "新对话",
            initial_message: text,
            create_request_id: creation.create_request_id,
            message_request_id: creation.request_id,
          },
        });
        const status = runtimeStatusToken(created?.submission?.status);
        if (created?.submission?.accepted !== true || ["failed", "cancelled", "canceled", "rejected", "interrupted"].includes(status)) {
          const error = new Error(structuredErrorMessage(created?.submission, "AI 没有接收首条消息"));
          error.payload = created;
          throw error;
        }
        const conversationId = created.conversation.conversation_id; attemptedTaskId = conversationId; creation.task_id = conversationId;
        state.pendingMessage = { task_id: conversationId, text, time: Date.now() };
        state.messageSubmission = null;
        clearDraft(null); ui.messageInput.value = ""; resizeComposer(); await selectConversation(conversationId, { saveCurrentDraft: false, record: created.conversation, pendingAttachment });
        clearComposerRetry("message"); clearDraft(conversationId); if (state.selectedTaskId === conversationId) { ui.messageInput.value = ""; resizeComposer(); }
        hideNotice();
        await resumeNewConversationAttachment(pendingAttachment, conversationId);
        window.setTimeout(() => refreshSelected({ force: true }), 250); return;
      } catch (error) {
        const detail = error?.payload?.detail;
        creation.status = "failed";
        creation.new_request_required = detail?.new_request_required === true;
        throw error;
      }
    }
    const checkpoint = currentHumanCheckpoint(state.conversation);
    const taskId = state.selectedTaskId; attemptedTaskId = taskId;
    await postQueuedConversationMessage(taskId, text); clearComposerRetry("message"); clearDraft(taskId); if (state.selectedTaskId === taskId) { ui.messageInput.value = ""; resizeComposer(); }
    if (checkpoint) showTransientNotice("已暂缓当前确认，AI 将先回应你的消息；没有批准执行或提交答案。", "ok");
    window.setTimeout(() => refreshSelected({ force: true }), 250);
  } catch (error) {
    if (state.pendingMessage?.task_id === state.selectedTaskId) state.pendingMessage = null;
    const failedSubmission = state.messageSubmission?.status === "failed" ? state.messageSubmission : null;
    if (failedSubmission?.task_id === state.selectedTaskId && !ui.messageInput.value.trim()) { ui.messageInput.value = failedSubmission.text; resizeComposer(); }
    saveDraft(attemptedTaskId); renderConversation(true);
    if (failedSubmission) {
      showNotice(failedSubmission.new_request_required ? `消息未继续：${error.message}。草稿已保留，请刷新后重新发送。` : `消息发送失败：${error.message}。再次发送同一条消息会复用请求编号；“重试发送”不会创建第二条排队请求。`);
      showComposerRetry({ label: failedSubmission.new_request_required ? "刷新后重发" : "重试发送", hint: failedSubmission.new_request_required ? "先核对最新检查点，再将保留的草稿作为新请求发送。" : "复用原请求身份与原消息；不会新建第二条排队请求。", kind: "message", action: async () => {
        const failed = state.messageSubmission;
        if (!failed || failed.status !== "failed" || failed.task_id !== state.selectedTaskId || failed.request_id !== failedSubmission.request_id) { clearComposerRetry("message"); showNotice("原发送请求已经变化，已停止重试。请刷新任务后确认当前状态。", "error"); return; }
        if (ui.messageInput.value.trim() !== failed.text) { showNotice("输入内容已经变化。为避免用旧请求身份发送新内容，请恢复原消息或直接发送为新消息。", "error"); return; }
        if (failed.new_request_required) await refreshSelected({ force: true });
        if (state.selectedTaskId !== failed.task_id) return;
        await submitMessage(failed.text);
      } });
    } else { clearComposerRetry("message"); showNotice(`${error.message}。任务事实不会被伪造；请先刷新任务确认服务端是否已创建记录。`); }
  }
  finally { ui.sendButton.disabled = !state.runtimeReady || Boolean(state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) || state.conversation?.execution_state_observed === false || state.cancelRequestInFlight === true || backgroundCancellationPending(state.conversation); ui.sendButton.dataset.busy = "false"; syncComposerDelivery(); }
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
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "取消"; cancel.addEventListener("click", closeDecisionDialog);
  const allow = document.createElement("button"); allow.type = "button"; allow.className = "allow"; allow.textContent = allowLabel;
  allow.addEventListener("click", async () => {
    if (allow.disabled) return;
    const controls = [...ui.dialogActions.querySelectorAll("button")];
    const disabledBefore = new Map(controls.map((control) => [control, control.disabled]));
    controls.forEach((control) => { control.disabled = true; }); setButtonBusy(allow, true, "执行中");
    try { await onAllow(); ui.decisionDialog.close(); }
    catch (error) { showNotice(error.message); }
    finally { setButtonBusy(allow, false, ""); controls.forEach((control) => { control.disabled = disabledBefore.get(control); }); }
  });
  ui.dialogActions.append(cancel, allow); ui.decisionDialog.showModal();
}
function syncCancelRequestUi(conversation = state.conversation) {
  const cancelling = state.cancelRequestInFlight === true || backgroundCancellationPending(conversation);
  ui.cancelAgentButton.disabled = cancelling || state.conversation?.execution_state_observed === false;
  ui.cancelAgentButton.textContent = cancelling ? "取消中" : "停止执行";
  ui.cancelAgentButton.setAttribute("aria-label", cancelling ? "正在请求停止当前智能协作与任务后台动作" : "请求停止当前智能协作与任务后台动作");
  const inlineCancelButtons = [...ui.messageList.querySelectorAll("[data-ai-turn-cancel]")];
  inlineCancelButtons.forEach((button) => { button.disabled = cancelling; button.textContent = cancelling ? "正在停止" : "停止"; });
  ui.messageInput.disabled = cancelling;
  ui.sendButton.disabled = !state.runtimeReady || Boolean(state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) || state.conversation?.execution_state_observed === false || cancelling;
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) { renderSelectionLoading(); return; }
  if (!cancelling) { delete ui.agentWorking.dataset.status; syncConversationComposerPlaceholder(conversation, state.task); return; }
  ui.messageInput.placeholder = "正在停止当前执行，请等待后端确认…";
  ui.agentWorking.hidden = inlineCancelButtons.length > 0;
  ui.agentWorking.dataset.status = "cancelling";
  ui.agentWorkingLabel.textContent = "正在停止当前智能协作与任务后台动作";
}
function openCancelAgentDialog() {
  if (!state.selectedTaskId || state.cancelRequestInFlight) return;
  if (backgroundCancellationPending(state.conversation)) { showNotice("停止请求已经记录，正在等待当前智能协作与任务后台动作确认；无需重复提交。", "ok"); return; }
  const taskId = state.selectedTaskId;
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "停止当前执行"; ui.dialogTitle.textContent = "请求停止当前任务的执行？";
  const copy = document.createElement("p"); copy.textContent = "确认后会请求停止当前智能协作，以及这个任务所属的排队中或运行中后台动作。最终是否全部停止以任务状态为准。";
  const field = document.createElement("label"); field.className = "cancel-reason-field"; const label = document.createElement("span"); label.textContent = "停止原因（可选）"; const reason = document.createElement("textarea"); reason.rows = 3; reason.maxLength = 500; reason.placeholder = "如需补充原因，可以写在这里"; field.append(label, reason); ui.dialogBody.append(copy, field);
  const back = document.createElement("button"); back.type = "button"; back.className = "reject"; back.textContent = "返回"; back.addEventListener("click", closeDecisionDialog);
  const allow = document.createElement("button"); allow.type = "button"; allow.className = "allow"; allow.textContent = "停止当前执行"; allow.disabled = false;
  allow.addEventListener("click", async () => {
    if (state.cancelRequestInFlight || allow.disabled) return;
    if (state.selectedTaskId !== taskId) { ui.decisionDialog.close(); showNotice("当前任务已经变化，请在对应任务中重新点击停止。", "ok"); return; }
    const cancelReason = reason.value.trim() || "用户请求停止当前执行";
    back.disabled = true; reason.disabled = true;
    state.cancelRequestInFlight = true; syncCancelRequestUi(); setButtonBusy(allow, true, "取消中");
    try {
      await request(conversationTransportPath(taskId, "cancel"), { method: "POST", json: { reason: cancelReason } });
      ui.decisionDialog.close(); showNotice("停止请求已被接受，正在确认当前智能协作与任务后台动作的最终状态。", "ok");
      try { await refreshSelected({ force: true }); } catch (refreshError) { showNotice(`取消请求已提交，但状态刷新失败：${refreshError.message}。请手动刷新确认最终状态。`, "error"); }
    } catch (error) {
      showNotice(`停止请求失败：${error.message}。当前智能协作和后台动作是否停止尚未确认，请刷新后重试。`, "error");
    } finally { state.cancelRequestInFlight = false; setButtonBusy(allow, false, ""); back.disabled = false; reason.disabled = false; renderConversation(true); }
  });
  ui.dialogActions.append(back, allow); ui.decisionDialog.showModal(); window.requestAnimationFrame(() => allow.focus());
}
function navigateToTrainingRecoveryCheckpoint() {
  const taskId = state.selectedTaskId; const result = state.task?.current_result;
  if (!taskId || !result || !TERMINAL_RETRY_STATUSES.has(result.status) || state.task?.control?.next_action?.id !== "retry_training_run") { showNotice("当前没有可恢复的终态 Run；请先刷新任务状态。", "error"); return; }
  closeInspector();
  const checkpoint = currentHumanCheckpoint(state.conversation);
  const checkpointCard = [...ui.messageList.querySelectorAll(".human-checkpoint")].find((card) => card.dataset.rpcId === checkpoint?.rpc_id) || null;
  if (checkpoint && checkpointCard) {
    checkpointCard.scrollIntoView({ block: "center", behavior: "smooth" }); checkpointCard.focus({ preventScroll: true });
    showNotice("请在训练协调器给出的人工确认卡中处理恢复；运行面板不会直接创建新 Run。", "ok");
    return;
  }
  ui.messageInput.focus();
  showNotice(`请在对话中让训练协调器核对旧 Run ${shortId(result.run_id)} 的失败证据并提出恢复方案。只有随后出现的 HumanCheckpoint 才能授权创建新 Run。`, "ok");
}
async function answerApproval(item, outcome, button) {
  if (state.selectionLoadingOwnerId && state.selectionLoadingOwnerId === state.selectedTaskId) return;
  if (item?.task_id && item.task_id !== state.selectedTaskId) return;
  if (!(state.conversation?.pending || []).some(checkpoint => checkpoint.rpc_id === item?.rpc_id)) return;
  const taskId = state.selectedTaskId; const identity = `${taskId}:${item.rpc_id}`;
  if (state.approvalSubmission === identity) return;
  state.approvalSubmission = identity;
  const controls = [...(button.closest?.(".decision-actions")?.querySelectorAll("button") || [button])];
  const disabledBefore = new Map(controls.map((control) => [control, control.disabled]));
  controls.forEach((control) => { control.disabled = true; }); setButtonBusy(button, true, "提交中");
  try { await request(conversationTransportPath(taskId, "approvals", item.rpc_id), { method: "POST", json: { outcome } }); if (state.selectedTaskId === taskId) await refreshSelected({ force: true }); }
  catch (error) { showNotice(error.message); }
  finally { setButtonBusy(button, false, ""); controls.forEach((control) => { control.disabled = disabledBefore.get(control); }); if (state.approvalSubmission === identity) state.approvalSubmission = null; }
}
async function postQuestionAnswers(item, answers, { taskId = state.selectedTaskId } = {}) {
  if (!taskId || !item?.rpc_id) throw new Error("当前问题缺少任务或会话身份，无法提交回答");
  if (state.selectionLoadingOwnerId === taskId || taskId !== state.selectedTaskId || (item.task_id && item.task_id !== taskId)) throw new Error("当前对话仍在加载或问题属于另一项任务，请加载完成后再作答");
  if (!(state.conversation?.pending || []).some(checkpoint => checkpoint.rpc_id === item.rpc_id)) throw new Error("这个问题已不在当前对话的待办中，请刷新后再作答");
  return request(conversationTransportPath(taskId, "questions", item.rpc_id), { method: "POST", json: { answers } });
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
  submit.addEventListener("click", async () => { const selected = options.querySelector("input:checked")?.value; if (!selected) { showNotice("请选择模型唯一输出形式。"); return; } if (!goalInput.value.trim()) { showNotice("业务目标不能为空。"); return; } setButtonBusy(submit, true, "保存中"); try { const response = await request(`/tasks/${encodeURIComponent(task.task_id)}/spec`, { method: "PATCH", json: { base_revision: spec.revision, selected_family: selected, business_goal: goalInput.value.trim(), confirm: true, user_note: editing ? "用户通过产品界面修订" : "用户通过产品界面确认" } }); ui.decisionDialog.close(); state.task = response.task; showNotice(response.task.status === "needs_recipe" ? "目标已确认，接下来结合已有材料准备训练路线、资源预算和验证步骤。" : `任务规格 v${response.task.current_spec_revision} 已保存，同一 task_id 保持不变。`, "ok"); await refreshSelected({ force: true }); } catch (error) { showNotice(error.message); } finally { setButtonBusy(submit, false, ""); } });
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
async function inspectCsvSchema(file, attachment = null) {
  const material = attachment?.source_material;
  if (material) {
    const taskId = state.selectedTaskId;
    if (taskId !== material.owner_id || attachment.task_id !== taskId) throw new Error("材料不属于当前任务");
    const schema = await request(`/tasks/${encodeURIComponent(taskId)}/materials/${encodeURIComponent(material.material_id)}/csv-schema`);
    if (schema.owner_id !== taskId || schema.material_id !== material.material_id || schema.inspection_sha256 !== material.inspection_sha256 || schema.dataset_imported !== false || !Array.isArray(schema.columns) || schema.columns.length < 2 || typeof schema.delimiter !== "string") throw new Error("已保存材料的表头身份不一致");
    const response = await request(`/tasks/${encodeURIComponent(taskId)}/csv-target-recommendation`, { method: "POST", json: { columns: schema.columns } });
    const recommendation = response?.recommendation || {};
    return { ...schema, recommendation, recommended: recommendation.status === "recommended" && schema.columns.includes(recommendation.target_column) ? recommendation.target_column : null };
  }
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
async function askCsvOptions(file, attachment = state.composerAttachment) {
  const ownerId = state.selectedTaskId;
  updateComposerAttachment(attachment, { status: "validating", error: null, can_retry: false, retry_stage: null });
  clear(ui.dialogBody); clear(ui.dialogActions); ui.dialogKicker.textContent = "CSV 数据合同"; ui.dialogTitle.textContent = "确认要预测的字段";
  let schema;
  try { schema = await inspectCsvSchema(file, attachment); }
  catch (error) { if (state.selectedTaskId !== ownerId || (attachment && state.composerAttachment !== attachment)) return; updateComposerAttachment(attachment, { status: "failed", error: `表头校验失败：${error.message}`, retry_stage: "upload", can_retry: true }); showNotice(`读取 CSV 表头失败：${error.message}。可在文件条目中重试，仍会复用原请求身份。`); ui.datasetInput.value = ""; return; }
  if (state.selectedTaskId !== ownerId || (attachment && state.composerAttachment !== attachment)) return;
  updateComposerAttachment(attachment, { status: "pending", error: "等待选择预测目标", retry_stage: "upload", can_retry: true });
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
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "reject"; cancel.textContent = "稍后处理"; cancel.addEventListener("click", () => { ui.decisionDialog.close(); updateComposerAttachment(attachment, { status: "pending", error: "尚未选择预测目标", retry_stage: "upload", can_retry: true }); ui.datasetInput.value = ""; });
  const submit = document.createElement("button"); submit.type = "button"; submit.className = "allow"; submit.textContent = "确认并导入体检"; submit.addEventListener("click", async () => { const selected = targetControl.matches?.("select") ? targetControl.value : targetControl.querySelector('input[name="csv-target-column"]:checked')?.value; if (!selected) { showNotice("请选择一个预测目标字段。"); return; } const selectedOptions = { targetColumn: selected, ignoredColumns: ignoredInput.value.trim(), delimiter: schema.delimiter }; if (attachment) attachment.options = selectedOptions; ui.decisionDialog.close(); await uploadDataset(file, { ...selectedOptions, attachment }); });
  ui.dialogActions.append(cancel, submit); ui.decisionDialog.showModal();
}
async function retryAttachmentContinuation(attachment) {
  const continuation = attachment?.continuation;
  if (!attachment?.dataset_id || !continuation || attachment.task_id !== state.selectedTaskId) { showNotice("原续接请求身份已经变化，已停止重试。请刷新任务确认数据与当前问题。", "error"); return; }
  const retryIdentity = attachment.request_id; updateComposerAttachment(attachment, { retry_stage: null, error: null, can_retry: false });
  try {
    if (continuation.kind === "question") {
      const checkpoint = currentHumanCheckpoint(state.conversation);
      if (!checkpoint || checkpoint.rpc_id !== continuation.rpc_id) throw new Error("当前问题已变化，不能把旧答案写入新的检查点");
      await postQuestionAnswers(checkpoint, continuation.answers, { taskId: attachment.task_id });
    } else if (continuation.kind === "message") {
      if (currentHumanCheckpoint(state.conversation)) throw new Error("当前出现新的人工确认，不能继续发送旧续接消息");
      const failed = state.messageSubmission;
      if (!failed || failed.status !== "failed" || failed.task_id !== attachment.task_id || failed.text !== continuation.text || failed.request_id !== continuation.request_id) throw new Error("原消息请求身份已变化");
      await postQueuedConversationMessage(attachment.task_id, continuation.text);
    } else throw new Error("未知续接类型");
    if (state.composerAttachment?.request_id === retryIdentity) updateComposerAttachment(attachment, { continuation: null, retry_stage: null, error: null, status: "ready" });
    showNotice("数据保持已就绪，协调器已从原请求继续。", "ok"); await refreshSelected({ force: true });
  } catch (error) {
    updateComposerAttachment(attachment, { status: "ready", retry_stage: "continuation", can_retry: true, error: `续接失败：${error.message}` });
    showNotice(`数据已真实导入，没有重复上传；续接失败：${error.message}。重试会复用原问题或消息身份。`, "error");
  }
}
function datasetCoordinatorContinuation(targetColumn) {
  const readableTarget = String(targetColumn || "").replace(/[「」\r\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
  const targetNote = readableTarget ? `，预测目标是「${readableTarget}」` : "";
  return `数据已经上传好了${targetNote}。请先检查数据并给我一版容易理解的训练方案；在我确认方案和启动前，不要开始训练。`;
}
async function completeDatasetUpload(response, attachment, taskId, options, context) {
  if (state.selectedTaskId !== taskId || (attachment && state.composerAttachment !== attachment)) return;
  const receiptDatasetId = response?.dataset_upload?.dataset_id || null;
  const datasetId = receiptDatasetId || response?.task?.dataset_id || null;
  if (receiptDatasetId && !datasetUploadReceiptMatches(response, taskId, attachment?.request_id)) throw new Error("数据请求返回了不属于当前任务或当前请求的回执");
  if (!datasetId || response?.task?.task_id !== taskId) throw new Error("数据请求返回成功，但缺少可核对的数据集身份");
  if (attachment?.completion_handled) return;
  updateComposerAttachment(attachment, { status: "ready", dataset_id: datasetId, error: null, retry_stage: null, can_retry: false, options }); activateContext("data");
  if (attachment) {
    attachment.completion_handled = true; attachment.continuation_in_flight = true;
    if (attachment.source_material) { saveMaterialDatasetPending(attachment, "completed"); const continuation = materialContinuation(attachment.source_material); continuation.status = "accepted"; continuation.used_as_dataset = datasetId; storeMaterialContinuation(attachment.source_material, continuation); }
  }
  const activeCheckpoint = currentHumanCheckpoint(state.conversation);
  const uploadCheckpoint = context?.kind === "question" && activeCheckpoint?.rpc_id === context.rpc_id ? dataUploadQuestionCheckpoint(activeCheckpoint) : null;
  try {
    if (uploadCheckpoint) {
      const answers = dataUploadCheckpointAnswers(uploadCheckpoint, datasetId, options.targetColumn);
      try { await postQuestionAnswers(uploadCheckpoint, answers, { taskId }); updateComposerAttachment(attachment, { continuation: null }); showNotice(options.targetColumn ? "数据已导入，预测列也已提交；协调器会从刚才的问题继续。" : "数据已导入，数据集编号已提交；协调器会从刚才的问题继续。", "ok"); }
      catch (error) { updateComposerAttachment(attachment, { status: "ready", continuation: { kind: "question", rpc_id: uploadCheckpoint.rpc_id, answers }, retry_stage: "continuation", can_retry: true, error: `续接失败：${error.message}` }); showNotice(`数据已真实导入并完成体检（数据集 ${shortId(datasetId)}），但协调器问题续接失败：${error.message}。请不要重复上传；刷新任务后从当前问题继续。重试只会续接原问题，不会重复上传。`, "error"); }
      return;
    }
    // Resume only the checkpoint or message captured before this upload. A
    // delayed receipt must never answer a newer question or grant permission.
    if (context?.kind === "message" && state.runtimeReady && !activeCheckpoint && datasetId) {
      const continuationText = datasetCoordinatorContinuation(options.targetColumn);
      try {
        await postQueuedConversationMessage(taskId, datasetCoordinatorContinuation(options.targetColumn)); updateComposerAttachment(attachment, { continuation: null });
        showNotice("数据已导入并完成体检。训练协调器会读取数据合同并继续完善方案；确认前不会启动训练。", "ok");
      } catch (error) {
        const failed = state.messageSubmission;
        updateComposerAttachment(attachment, { status: "ready", continuation: failed?.status === "failed" ? { kind: "message", text: continuationText, request_id: failed.request_id } : null, retry_stage: failed?.status === "failed" ? "continuation" : null, can_retry: failed?.status === "failed", error: `续接失败：${error.message}` });
        showNotice(`数据已真实导入并完成体检（数据集 ${shortId(datasetId)}），但协调器没有续接成功：${error.message}。${failed?.status === "failed" ? "文件条目会复用原消息身份重试续接，不会重复上传。" : "请刷新任务确认当前对话状态。"}`, "error");
      }
      return;
    }
    const reason = activeCheckpoint
      ? "当前仍有一项决定等待你处理；数据合同已保留，处理后协调器再继续。"
      : context?.kind === "question"
        ? "原数据问题已经变化或处理，已保留数据；请按当前对话继续。"
        : "训练协调器当前不可用，数据合同已保留；恢复连接后可在对话中继续。";
    showNotice(`数据已真实导入并完成体检。${reason}`, "ok");
  } finally { if (attachment) attachment.continuation_in_flight = false; }
}
async function uploadDataset(file, options = {}) {
  const attachment = options.attachment?.request_id ? options.attachment : state.composerAttachment?.file === file ? state.composerAttachment : null;
  const selectedOptions = { targetColumn: options.targetColumn, ignoredColumns: options.ignoredColumns, delimiter: options.delimiter };
  const taskId = state.selectedTaskId; const activeCheckpoint = currentHumanCheckpoint(state.conversation); const uploadCheckpoint = dataUploadQuestionCheckpoint(activeCheckpoint);
  const keepPending = (message) => { updateComposerAttachment(attachment, { status: "pending", error: message, retry_stage: "upload", can_retry: false, options: selectedOptions }); showNotice(message, "ok"); };
  const failUpload = (message, retryable = true) => { updateComposerAttachment(attachment, { status: "failed", error: message, retry_stage: retryable ? "upload" : null, can_retry: retryable, options: selectedOptions }); showNotice(`${message}${retryable ? "。可在文件条目中重试，仍会复用原请求身份。" : "。请先刷新任务确认服务端状态，不要重复上传。"}`, "error"); };
  const awaitReceipt = (message) => { updateComposerAttachment(attachment, { status: "pending", error: message, retry_stage: "reconcile", can_retry: true, options: selectedOptions }); showNotice(`${message}。刷新或点击“核对导入”会读取任务数据集与服务端回执；不会先把它标成失败。`, "ok"); };
  if (!taskId) { keepPending("先发送任务目标创建训练任务，再处理这个文件"); return; }
  if (attachment?.task_id && attachment.task_id !== taskId) { failUpload("文件请求不属于当前任务", false); return; }
  if (attachment && !attachment.task_id) attachment.task_id = taskId;
  const availability = datasetUploadAvailability(state.task, activeCheckpoint, taskId);
  if (availability.blocked) { keepPending(availability.reason); return; }
  const lower = file?.name.toLowerCase() || ""; if (!lower.endsWith(".zip") && !lower.endsWith(".csv")) { failUpload("当前数据导入入口接受类别目录 ZIP 或 CSV；其他材料可先通过材料检查用于准备训练方案", false); return; }
  const format = datasetUploadFormat(state.task, uploadCheckpoint);
  if (format && !lower.endsWith(`.${format}`)) { failUpload(format === "csv" ? "当前任务使用表格数据，请改选 CSV 文件" : "当前任务使用类别目录数据，请改选 ZIP 文件", false); return; }
  if (lower.endsWith(".csv") && !options.targetColumn) { void askCsvOptions(file, attachment); return; }
  updateComposerAttachment(attachment, { status: "validating", error: null, retry_stage: null, can_retry: false, options: selectedOptions });
  if (attachment?.source_material) {
    attachment.request_id = materialDatasetRequestId(attachment.source_material, selectedOptions, attachment);
    if (attachment.material_dataset_needs_review) { requireMaterialDatasetReview(attachment, "上一次请求已要求重新核对"); return; }
    saveMaterialDatasetPending(attachment);
  }
  const uploadContext = uploadCheckpoint ? { kind: "question", rpc_id: uploadCheckpoint.rpc_id } : !activeCheckpoint ? { kind: "message" } : { kind: "none" };
  if (attachment && !attachment.upload_context) attachment.upload_context = uploadContext;
  hideNotice(); setButtonBusy(ui.datasetButton, true, "体检中");
  const headers = { "content-type": lower.endsWith(".csv") ? "text/csv" : "application/zip", "x-filename": encodeURIComponent(file.name) };
  if (attachment?.request_id) headers["x-request-id"] = attachment.request_id;
  if (options.targetColumn) headers["x-target-column"] = encodeURIComponent(options.targetColumn);
  if (options.ignoredColumns) headers["x-ignored-columns"] = options.ignoredColumns.split(",").map((value) => encodeURIComponent(value.trim())).filter(Boolean).join(",");
  if (options.delimiter) headers["x-delimiter"] = encodeURIComponent(options.delimiter);
  try {
    let response;
    try {
      const material = attachment?.source_material;
      if (material) {
        if (!reusableDatasetMaterial(material)) throw Object.assign(new Error("材料或当前训练入口已经变化，请刷新后重试"), { status: 409 });
        response = await request(`/tasks/${encodeURIComponent(taskId)}/dataset-from-material`, { method: "POST", json: {
          material_id: material.material_id, inspection_sha256: material.inspection_sha256, request_id: attachment.request_id, base_spec_revision: attachment.base_spec_revision,
          options: { ...(selectedOptions.targetColumn ? { target_column: selectedOptions.targetColumn } : {}), ...(selectedOptions.ignoredColumns ? { ignored_columns: selectedOptions.ignoredColumns.split(",").map(value => value.trim()).filter(Boolean) } : {}), ...(selectedOptions.delimiter ? { delimiter: selectedOptions.delimiter } : {}) },
        } });
      } else response = await request(`/tasks/${encodeURIComponent(taskId)}/dataset`, { method: "POST", body: file, headers });
    }
    catch (error) {
      if (attachment?.source_material && error.status === 409) { requireMaterialDatasetReview(attachment, error.message); return; }
      const responseMayBeLost = !Number.isFinite(error.status) || error.status === 0 || error.status === 408 || error.status >= 500 || (error.retryable === true && error.status < 400);
      if (responseMayBeLost && attachment?.request_id) {
        updateComposerAttachment(attachment, { status: "validating", error: "响应中断，正在核对服务端回执", retry_stage: null, can_retry: false });
        try { response = await reconcileDatasetUploadReceipt(taskId, attachment); }
        catch (_receiptError) { awaitReceipt(`数据请求的响应未能确认：${error.message}`); return; }
      } else {
        failUpload(`数据导入失败：${error.message}`, error.status === 422);
        return;
      }
    }
    if (state.selectedTaskId !== taskId) return;
    try { await completeDatasetUpload(response, attachment, taskId, selectedOptions, attachment?.upload_context || uploadContext); }
    catch (error) { failUpload(error.message, false); }
    await refreshSelected({ force: true });
  } finally { setButtonBusy(ui.datasetButton, false, ""); ui.datasetInput.value = ""; }
}
function activateContext(name) { const requested = name === "capability" ? "plan" : name; const target = ui.contextTabs.querySelector(`[data-context="${requested}"]`); const selected = target && !target.hidden ? requested : "plan"; document.querySelectorAll("[data-context]").forEach((button) => { const active = button.dataset.context === selected; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); document.querySelectorAll("[data-context-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.contextPanel === selected)); if (state.inspectorMode !== "object-viewer") ui.inspectorSheetTitle.textContent = ({ plan: "方案与证据", data: "数据证据", run: "运行现场", evaluation: "评测报告", artifacts: "交付产物" })[selected] || "方案与证据"; }
function setMobileView(name) { [ui.mobileConversationButton, ui.mobileContextButton, ui.mobileResultButton].forEach((button) => { const active = button.dataset.mobileView === name; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); }
function mobileWorkspace() { return inspectorMedia.matches; }
function overlayWorkspace() { return !dockedWorkspaceMedia.matches; }
function syncInspectorIsolation() {
  const isolated = overlayWorkspace() && ui.inspector.dataset.open === "true";
  const sidebarOffscreen = sidebarMedia.matches && ui.sidebar.dataset.open !== "true";
  ui.sidebar.inert = isolated || sidebarOffscreen; ui.sidebar.setAttribute("aria-hidden", String(isolated || sidebarOffscreen));
  ui.menuButton.setAttribute("aria-expanded", String(!sidebarOffscreen));
  ui.conversationMain.inert = isolated; ui.mobileViewNav.inert = isolated;
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
  if (pendingExecutionIntegration(state.task, state.conversation, state.workspaceProjection)) return "方案准备";
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
    delete ui.inspector.dataset.presentation; ui.workspaceExperience.hidden = true; ui.inspector.scrollTop = 0; ui.inspectorSheetTitle.textContent = "精确证据"; state.inspectorAutoOpened = false;
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
function openSidebar() { ui.sidebar.dataset.open = "true"; ui.sidebarScrim.hidden = false; syncInspectorIsolation(); }
function closeSidebar() { ui.sidebar.dataset.open = "false"; ui.sidebarScrim.hidden = true; syncInspectorIsolation(); }
function stopPolling() { if (state.pollTimer) window.clearInterval(state.pollTimer); state.pollTimer = null; stopConversationStream(); }
function resizeComposer() { ui.messageInput.style.height = "auto"; ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 140)}px`; }

ui.composerForm.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(ui.messageInput.value); });
ui.messageInput.addEventListener("input", () => { if (state.composerRetryKind === "message" && state.messageSubmission?.text !== ui.messageInput.value.trim()) clearComposerRetry("message"); resizeComposer(); saveDraft(); syncComposerDelivery(); });
ui.messageInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composerForm.requestSubmit(); } });
ui.composerRetryButton.addEventListener("click", invokeComposerRetry);
ui.retryAttachmentButton.addEventListener("click", retryComposerAttachment);
ui.removeAttachmentButton.addEventListener("click", () => clearComposerAttachment());
ui.closeDialogButton?.addEventListener("click", closeDecisionDialog);
ui.decisionDialog.addEventListener("cancel", (event) => { if (ui.dialogActions.querySelector('[aria-busy="true"]')) event.preventDefault(); });
ui.newTaskButton.addEventListener("click", openNewTask); ui.refreshButton.addEventListener("click", () => state.selectedTaskId ? refreshSelected({ force: true }) : refreshHomeAvailability());
ui.menuButton.addEventListener("click", openSidebar); ui.sidebarScrim.addEventListener("click", closeSidebar);
ui.datasetButton.addEventListener("click", () => {
  if (state.task?.control?.next_action?.id === "stage_recipe_samples") { ui.recipeSampleInput.click(); return; }
  ui.datasetInput.accept = !state.selectedTaskId || materialInspectionMode() ? ".csv,.jsonl,.zip" : datasetUploadFormat() === "zip" ? ".zip" : datasetUploadFormat() === "csv" ? ".csv" : ".csv,.zip"; ui.datasetInput.click();
}); ui.inspectorDatasetButton.addEventListener("click", () => { ui.datasetInput.accept = materialInspectionMode() ? ".csv,.jsonl,.zip" : datasetUploadFormat() === "zip" ? ".zip" : datasetUploadFormat() === "csv" ? ".csv" : ".csv,.zip"; ui.datasetInput.click(); }); ui.datasetInput.addEventListener("change", () => stageComposerAttachment(ui.datasetInput.files?.[0])); ui.recipeSampleInput.addEventListener("change", () => stageRecipeSamples(ui.recipeSampleInput.files?.[0]));
[
  ui.approveTrainingPlanButton,
  ui.rejectTrainingPlanButton,
  ui.cancelTrainingPlanButton,
  ui.confirmContractButton,
  ui.approveRunProposalButton,
].forEach((control) => control.addEventListener("click", returnToHumanCheckpoint));
ui.modelSourceSearchForm.addEventListener("submit", searchModelSources); ui.modelSourceReferenceForm.addEventListener("submit", resolveModelSourceReference); ui.bindModelSourceButton.addEventListener("click", bindPendingModelSource); ui.cancelModelBindingButton.addEventListener("click", cancelModelBindingAttempt);
ui.viewAllModelSourceCandidatesButton.addEventListener("click", openAllModelSourceCandidates);
ui.repositoryManualMapping.addEventListener("submit", applyRepositoryManualMapping);
ui.createTrainingPlanButton.addEventListener("click", createTrainingPlan);
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
    showNotice("适配器参考包已生成，可供开发者审阅；当前目标仍可在对话中继续准备方案。", "ok"); await refreshSelected({ force: true });
  } catch (error) { showNotice(error.message); }
  finally { setButtonBusy(ui.scaffoldRecipeButton, false, ""); }
});
ui.cancelAgentButton.addEventListener("click", openCancelAgentDialog);
ui.cancelRunButton.addEventListener("click", requestTrainingRunCancellation);
ui.retryRunButton.addEventListener("click", navigateToTrainingRecoveryCheckpoint);
ui.contextTabs.addEventListener("click", (event) => { const button = event.target.closest("[data-context]"); if (button) activateContext(button.dataset.context); });
ui.closeInspectorButton.addEventListener("click", () => closeInspector({ userInitiated: true })); ui.inspectorScrim.addEventListener("click", () => closeInspector({ userInitiated: true }));
ui.workspaceToggleButton.addEventListener("click", () => ui.inspector.dataset.open === "true" ? closeInspector({ userInitiated: true }) : openInspector(workspaceContextForProjection(), { presentation: preferredWorkspacePresentation() }));
ui.workspaceTechnicalButton.addEventListener("click", () => openInspector(ui.workspaceTechnicalButton.dataset.context || workspaceContextForProjection(), { presentation: "technical" }));
ui.mobileConversationButton.addEventListener("click", () => closeInspector({ userInitiated: true })); ui.mobileContextButton.addEventListener("click", () => openInspector("plan", { presentation: "technical" })); ui.mobileResultButton.addEventListener("click", () => openInspector("evaluation", { presentation: "technical" }));
document.addEventListener("keydown", handleInspectorKeydown);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") void refreshTaskListIfDue({ force: true }); });
inspectorMedia.addEventListener("change", () => { syncInspectorIsolation(); if (mobileWorkspace() && ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus()); });
sidebarMedia.addEventListener("change", syncInspectorIsolation);
dockedWorkspaceMedia.addEventListener("change", () => {
  if (!dockedWorkspaceMedia.matches && state.inspectorAutoOpened && ui.inspector.dataset.open === "true") closeInspector({ userInitiated: false });
  if (ui.inspector.dataset.open === "true") ui.inspectorScrim.hidden = dockedWorkspaceMedia.matches;
  syncInspectorIsolation();
  if (state.task) syncWorkspaceForTask(state.task);
  if (!dockedWorkspaceMedia.matches && ui.inspector.dataset.open === "true") window.requestAnimationFrame(() => ui.closeInspectorButton.focus());
});
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
  ui.messageInput.value = button.dataset.prompt; resizeComposer(); saveDraft();
  if (ui.sendButton.disabled) { ui.messageInput.focus(); return; }
  ui.composerForm.requestSubmit();
}));

async function boot() {
  restoreDraft(null); window.setInterval(() => { syncAiTurnElapsedLabels(); void refreshTaskListIfDue(); }, 1000);
  const results = await Promise.allSettled([loadRuntime(), loadHfCapability(), loadModelSourceProviders(), loadTaskSpecFamilies(), loadTasks({ selectFromUrl: true })]);
  const tasksFailure = results[4].status === "rejected" ? results[4].reason : null;
  if (!state.selectedTaskId) enterHomeState({ focusComposer: false });
  resizeComposer();
  if (!state.selectedTaskId) reconcileHomeAvailability(tasksFailure);
}
boot().catch((error) => showNotice(`页面初始化失败：${error.message}`));
