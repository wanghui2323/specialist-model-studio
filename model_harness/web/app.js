const ACTIVE_STATUSES = new Set([
  "created",
  "queued",
  "preflight",
  "training",
  "evaluating",
  "proposing",
  "packaging",
  "needs_input",
]);

const STATUS_LABELS = {
  idle: "未开始",
  created: "已创建",
  queued: "排队中",
  preflight: "边界检查",
  training: "训练中",
  evaluating: "评测中",
  proposing: "生成策略",
  packaging: "打包制品",
  needs_input: "等待输入",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
  interrupted: "已中断",
};

const STAGE_ORDER = ["preflight", "training", "evaluating", "proposing", "packaging"];
const STREAM_EVENTS = [
  "run.created",
  "run.queued",
  "run.status_changed",
  "preflight.completed",
  "training.model_selected",
  "evaluation.completed",
  "optimization.strategies_proposed",
  "optimization.strategy_approved",
  "artifacts.packaged",
  "run.cancel_requested",
  "run.cancelled",
  "run.failed",
  "run.interrupted",
];

const ui = {
  runList: document.querySelector("#runList"),
  chatLog: document.querySelector("#chatLog"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  quickActions: document.querySelector("#quickActions"),
  newRunButton: document.querySelector("#newRunButton"),
  refreshRunsButton: document.querySelector("#refreshRunsButton"),
  cancelRunButton: document.querySelector("#cancelRunButton"),
  conversationTitle: document.querySelector("#conversationTitle"),
  connectionState: document.querySelector("#connectionState"),
  statusBadge: document.querySelector("#statusBadge"),
  stageList: document.querySelector("#stageList"),
  gateSummary: document.querySelector("#gateSummary"),
  metricGrid: document.querySelector("#metricGrid"),
  strategyList: document.querySelector("#strategyList"),
  lineageSection: document.querySelector("#lineageSection"),
  lineageList: document.querySelector("#lineageList"),
  approvalDialog: document.querySelector("#approvalDialog"),
  approvalTitle: document.querySelector("#approvalTitle"),
  approvalDescription: document.querySelector("#approvalDescription"),
  confirmApprovalButton: document.querySelector("#confirmApprovalButton"),
};

const appState = {
  runs: [],
  selectedRunId: null,
  result: null,
  eventSource: null,
  eventIds: new Set(),
  pendingStrategy: null,
  sending: false,
  refreshTimer: null,
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail || JSON.stringify(body) : body;
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return body;
}

function clearElement(element) {
  while (element.firstChild) element.firstChild.remove();
}

function formatTime(value) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function shortId(runId) {
  if (!runId) return "未选择运行";
  const pieces = runId.split("-");
  return pieces.length > 2 ? pieces.slice(-3).join("-") : runId;
}

function setConnection(status) {
  const active = ACTIVE_STATUSES.has(status);
  ui.connectionState.dataset.state = active ? "working" : status === "completed" ? "live" : "idle";
  ui.connectionState.querySelector("b").textContent = active
    ? "后台执行中"
    : status === "completed"
      ? "证据已生成"
      : "等待任务";
}

function createMessage(role, text, variant = "") {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"} ${variant}`.trim();

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = variant === "error-message" ? "!" : variant === "event-message" ? "·" : "H";

  const content = document.createElement("div");
  content.className = "message-content";
  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = variant === "event-message" ? "运行事件" : "Harness";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  content.append(label, paragraph);
  article.append(avatar, content);
  return article;
}

function appendMessage(role, text, variant = "") {
  ui.chatLog.append(createMessage(role, text, variant));
  ui.chatLog.scrollTop = ui.chatLog.scrollHeight;
}

function eventMessage(record) {
  const payload = record.payload || {};
  if (record.type === "run.queued") return "任务已经进入本地队列，合同快照已冻结。";
  if (record.type === "run.status_changed") {
    const labels = {
      preflight: "正在检查任务合同、数据边界和计算预算。",
      training: "开始比较候选小模型，最终测试集仍保持隔离。",
      evaluating: "候选模型已经选定，正在打开独立测试集并执行压力测试。",
      proposing: "评测完成，正在根据失败差距生成优化策略。",
      packaging: "正在打包模型、指标、哈希和学习报告。",
      completed: "运行完成，模型与评测证据已经持久化。",
      cancelled: "运行已在安全阶段边界取消。",
      interrupted: "运行被标记为中断，恢复时会创建子运行。",
      failed: "运行失败，错误已经记录。",
    };
    return labels[payload.to] || null;
  }
  if (record.type === "training.model_selected") {
    return `验证集选出的模型是 ${payload.selected_model}，选择依据为 ${payload.selection_metric}。`;
  }
  if (record.type === "evaluation.completed") {
    return `独立评测完成，干净测试集 Accuracy 为 ${Number(payload.clean_test_accuracy).toFixed(4)}。`;
  }
  if (record.type === "optimization.strategies_proposed") {
    return `已生成 ${payload.strategy_count} 条优化建议，其中 ${payload.actionable_count} 条可以在批准后执行。`;
  }
  if (record.type === "optimization.strategy_approved") {
    return `策略 ${payload.strategy_id} 已批准，子运行 ${shortId(payload.child_run_id)} 已创建。`;
  }
  if (record.type === "run.cancel_requested") return "取消请求已经记录，等待安全阶段边界。";
  if (record.type === "run.failed") return `运行失败：${payload.error || "未知错误"}`;
  if (record.type === "run.interrupted") return "服务重启期间运行被中断，可以创建子运行恢复。";
  return null;
}

async function loadRuns({ selectFirst = true } = {}) {
  const response = await request("/runs");
  appState.runs = response.runs || [];
  renderRunList();
  if (!appState.selectedRunId && selectFirst && appState.runs.length) {
    await selectRun(appState.runs[0].run_id);
  }
}

function renderRunList() {
  clearElement(ui.runList);
  if (!appState.runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = "还没有运行记录";
    ui.runList.append(empty);
    return;
  }
  appState.runs.forEach((run) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-item";
    button.dataset.child = String(Boolean(run.parent_run_id));
    button.setAttribute("aria-current", String(run.run_id === appState.selectedRunId));

    const main = document.createElement("span");
    main.className = "run-item-main";
    const title = document.createElement("b");
    title.textContent = run.task_id || shortId(run.run_id);
    const dot = document.createElement("i");
    dot.dataset.status = run.status;
    main.append(title, dot);

    const meta = document.createElement("span");
    meta.className = "run-item-meta";
    const stateLabel = document.createElement("span");
    stateLabel.textContent = STATUS_LABELS[run.status] || run.status;
    const time = document.createElement("time");
    time.textContent = formatTime(run.updated_at_utc);
    meta.append(stateLabel, time);

    button.append(main, meta);
    button.addEventListener("click", () => selectRun(run.run_id));
    ui.runList.append(button);
  });
}

async function selectRun(runId) {
  if (!runId) return;
  closeEventStream();
  appState.selectedRunId = runId;
  appState.eventIds.clear();
  renderRunList();
  setConnection("created");
  try {
    const [result, eventResponse] = await Promise.all([
      request(`/runs/${encodeURIComponent(runId)}/result`),
      request(`/runs/${encodeURIComponent(runId)}/events`),
    ]);
    appState.result = result;
    renderResult(result);
    rebuildConversation(eventResponse.events || [], result);
    if (ACTIVE_STATUSES.has(result.status)) openEventStream(runId);
  } catch (error) {
    appendMessage("assistant", error.message, "error-message");
    setConnection("idle");
  }
}

function rebuildConversation(events, result) {
  clearElement(ui.chatLog);
  const intro = `已打开运行 ${shortId(result.run_id)}。目标：${result.business_goal}`;
  ui.chatLog.append(createMessage("assistant", intro));
  events.forEach((record) => {
    appState.eventIds.add(record.event_id);
    const text = eventMessage(record);
    if (text) ui.chatLog.append(createMessage("assistant", text, "event-message"));
  });
  if (!events.length) ui.chatLog.append(createMessage("assistant", "运行已创建，等待第一条执行事件。", "event-message"));
  ui.chatLog.scrollTop = ui.chatLog.scrollHeight;
}

function closeEventStream() {
  if (appState.eventSource) appState.eventSource.close();
  appState.eventSource = null;
  if (appState.refreshTimer) window.clearTimeout(appState.refreshTimer);
  appState.refreshTimer = null;
}

function openEventStream(runId) {
  closeEventStream();
  const source = new EventSource(`/runs/${encodeURIComponent(runId)}/events/stream`);
  appState.eventSource = source;
  STREAM_EVENTS.forEach((eventType) => {
    source.addEventListener(eventType, (event) => {
      const record = JSON.parse(event.data);
      if (!appState.eventIds.has(record.event_id)) {
        appState.eventIds.add(record.event_id);
        const text = eventMessage(record);
        if (text) appendMessage("assistant", text, "event-message");
      }
      scheduleRefresh();
    });
  });
  source.onopen = () => setConnection("training");
  source.onerror = async () => {
    await refreshSelected();
    if (!appState.result || !ACTIVE_STATUSES.has(appState.result.status)) closeEventStream();
  };
}

function scheduleRefresh() {
  if (appState.refreshTimer) window.clearTimeout(appState.refreshTimer);
  appState.refreshTimer = window.setTimeout(() => {
    appState.refreshTimer = null;
    refreshSelected().catch((error) => appendMessage("assistant", error.message, "error-message"));
  }, 120);
}

async function refreshSelected() {
  if (!appState.selectedRunId) return;
  const result = await request(`/runs/${encodeURIComponent(appState.selectedRunId)}/result`);
  appState.result = result;
  renderResult(result);
  await loadRuns({ selectFirst: false });
}

function renderResult(result) {
  ui.conversationTitle.textContent = result.task_id || "训练运行";
  ui.statusBadge.textContent = STATUS_LABELS[result.status] || result.status;
  ui.statusBadge.dataset.status = result.status;
  ui.cancelRunButton.disabled = !ACTIVE_STATUSES.has(result.status);
  setConnection(result.status);
  renderStages(result.status);
  renderMetrics(result.metrics, result.offline_gates_passed);
  renderStrategies(result.strategies || []);
  renderLineage(result);
}

function renderStages(status) {
  const currentIndex = STAGE_ORDER.indexOf(status);
  ui.stageList.querySelectorAll("li").forEach((item, index) => {
    let state = "waiting";
    if (status === "completed" || index < currentIndex) state = "done";
    if (index === currentIndex) state = "active";
    item.dataset.state = state;
  });
}

function metricValue(value, digits = 4, suffix = "") {
  return typeof value === "number" ? `${value.toFixed(digits)}${suffix}` : "—";
}

function renderMetrics(metrics, gatesPassed) {
  const clean = metrics?.clean_test || {};
  const latency = metrics?.latency || {};
  const values = [
    [metricValue(clean.accuracy), "Accuracy"],
    [metricValue(clean.macro_f1), "Macro-F1"],
    [metricValue(clean.worst_class_recall), "最差类Recall"],
    [metricValue(latency.p95_ms, 2, " ms"), "p95延迟"],
  ];
  clearElement(ui.metricGrid);
  values.forEach(([value, label]) => {
    const cell = document.createElement("div");
    const strong = document.createElement("b");
    const span = document.createElement("span");
    strong.textContent = value;
    span.textContent = label;
    cell.append(strong, span);
    ui.metricGrid.append(cell);
  });
  ui.gateSummary.textContent = gatesPassed === true ? "离线门槛通过" : gatesPassed === false ? "存在未通过门槛" : "等待评测";
}

function renderStrategies(strategies) {
  clearElement(ui.strategyList);
  if (!strategies.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("span");
    icon.className = "empty-icon";
    icon.setAttribute("aria-hidden", "true");
    const copy = document.createElement("p");
    copy.textContent = "完成独立评测后，这里会展示有证据的优化建议。";
    empty.append(icon, copy);
    ui.strategyList.append(empty);
    return;
  }

  strategies.forEach((strategy) => {
    const card = document.createElement("article");
    card.className = "strategy-card";
    card.dataset.actionable = String(strategy.actionable);
    const title = document.createElement("h4");
    title.textContent = strategy.title;
    const hypothesis = document.createElement("p");
    hypothesis.textContent = strategy.hypothesis;
    const effect = document.createElement("p");
    effect.textContent = `预期：${strategy.expected_effect}`;
    const meta = document.createElement("div");
    meta.className = "strategy-meta";
    [`成本 ${strategy.estimated_cost}`, `风险 ${strategy.risk}`, strategy.actionable ? "可执行" : "需要外部条件"].forEach((text) => {
      const tag = document.createElement("span");
      tag.textContent = text;
      meta.append(tag);
    });
    card.append(title, hypothesis, effect, meta);
    if (strategy.actionable) {
      const action = document.createElement("button");
      action.type = "button";
      action.className = "strategy-action";
      action.textContent = "审查并批准";
      action.addEventListener("click", () => openApproval(strategy));
      card.append(action);
    }
    ui.strategyList.append(card);
  });
}

function renderLineage(result) {
  const items = [];
  if (result.parent_run_id) items.push(`父运行：${shortId(result.parent_run_id)}`);
  (result.child_run_ids || []).forEach((id) => items.push(`子运行：${shortId(id)}`));
  ui.lineageSection.hidden = !items.length;
  clearElement(ui.lineageList);
  items.forEach((text) => {
    const chip = document.createElement("div");
    chip.className = "lineage-chip";
    chip.textContent = text;
    ui.lineageList.append(chip);
  });
}

function openApproval(strategy) {
  appState.pendingStrategy = strategy;
  ui.approvalTitle.textContent = strategy.title;
  ui.approvalDescription.textContent = `${strategy.hypothesis} ${strategy.expected_effect}`;
  ui.approvalDialog.showModal();
}

async function sendChat(message) {
  const text = message.trim();
  if (!text || appState.sending) return;
  appState.sending = true;
  ui.sendButton.disabled = true;
  ui.messageInput.disabled = true;
  try {
    const response = await request("/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, run_id: appState.selectedRunId }),
    });
    if (response.run_id && response.run_id !== appState.selectedRunId) {
      await loadRuns({ selectFirst: false });
      await selectRun(response.run_id);
    }
    appendMessage("user", text);
    appendMessage("assistant", response.message);
    if (response.data?.metrics || response.data?.status) {
      appState.result = response.data;
      if (response.data.status) renderResult(response.data);
    }
    await loadRuns({ selectFirst: false });
  } catch (error) {
    appendMessage("user", text);
    appendMessage("assistant", error.message, "error-message");
  } finally {
    appState.sending = false;
    ui.sendButton.disabled = false;
    ui.messageInput.disabled = false;
    ui.messageInput.value = "";
    resizeComposer();
    ui.messageInput.focus();
  }
}

function resizeComposer() {
  ui.messageInput.style.height = "auto";
  ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 132)}px`;
}

ui.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChat(ui.messageInput.value);
});

ui.messageInput.addEventListener("input", resizeComposer);
ui.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ui.composer.requestSubmit();
  }
});

ui.quickActions.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-message]");
  if (button) sendChat(button.dataset.message);
});

ui.newRunButton.addEventListener("click", () => sendChat("开始数字识别实验"));
ui.refreshRunsButton.addEventListener("click", () => loadRuns({ selectFirst: false }));
ui.cancelRunButton.addEventListener("click", () => sendChat("取消当前运行"));

ui.approvalDialog.addEventListener("close", () => {
  if (ui.approvalDialog.returnValue === "confirm" && appState.pendingStrategy) {
    sendChat(`批准 ${appState.pendingStrategy.strategy_id}`);
  }
  appState.pendingStrategy = null;
});

window.addEventListener("beforeunload", closeEventStream);

loadRuns().catch((error) => {
  appendMessage("assistant", `无法读取本地服务：${error.message}`, "error-message");
  setConnection("idle");
});
