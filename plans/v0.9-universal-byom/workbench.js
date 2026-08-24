const STATUS_LABELS = {
  planned: "未启动",
  implementing: "实现中",
  implemented: "已实现",
  verified: "已验证",
  accepted: "已验收",
  blocked: "已阻断",
  failed: "失败",
};

const ui = Object.fromEntries([
  "headerState", "loopNav", "loopTitle", "loopOutcome", "progressValue", "progressBar",
  "progressDetail", "loopStatus", "taskList", "decisionList", "baselineHead", "baselineFacts",
  "decisionCount", "gateTarget", "gateCopy", "copyGate", "copyFeedback",
].map((id) => [id, document.getElementById(id)]));

const state = { ledger: null, baseline: null, selectedLoopId: null };

function clear(element) {
  while (element?.firstChild) element.firstChild.remove();
}

function statusLabel(value) {
  return STATUS_LABELS[value] || String(value || "未知");
}

function selectedLoop() {
  return state.ledger?.loops.find((loop) => loop.loop_id === state.selectedLoopId) || state.ledger?.loops[0] || null;
}

function renderDecisions() {
  clear(ui.decisionList);
  const decisions = state.ledger?.confirmed_decisions || [];
  ui.decisionCount.textContent = `${decisions.length} / ${decisions.length}`;
  decisions.forEach((decision) => {
    const item = document.createElement("li");
    item.textContent = decision;
    ui.decisionList.append(item);
  });
  if (!decisions.length) {
    const item = document.createElement("li");
    item.textContent = "任务账本未登记已确认决策。";
    ui.decisionList.append(item);
  }
}

function addFact(label, value) {
  const row = document.createElement("div");
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value;
  row.append(term, description);
  ui.baselineFacts.append(row);
}

function renderBaseline() {
  const baseline = state.baseline;
  ui.baselineHead.textContent = `${baseline.source.baseline_commit} · ${baseline.captured_at}`;
  clear(ui.baselineFacts);
  const python = baseline.verified_baseline.python_tests;
  const node = baseline.verified_baseline.node_tests;
  addFact("历史 Python 回归", `${python.passed} / ${python.passed + python.failed}`);
  addFact("历史 Node 回归", `${node.passed} / ${node.passed + node.failed}`);
  addFact("历史 GitHub 模型源", baseline.current_capability_boundary.github_model_source === "missing" ? "当时尚未实现" : "当时已接入");
  addFact("历史 Recipe Build", baseline.current_capability_boundary.executable_recipe_build === "blocked_environment" ? "当时阻断" : "当时可执行");
  addFact("历史隔离执行", baseline.current_capability_boundary.execution_isolation === "missing" ? "当时尚未实现" : "当时已可用");
}

function currentPhase() {
  const snapshot = state.ledger?.current_status_snapshot || {};
  const explicit = snapshot.current_phase || {};
  const fallbackLoopId = state.ledger?.loops.some((loop) => loop.loop_id === "L2") ? "L2" : state.ledger?.loops[0]?.loop_id;
  const loopId = explicit.loop_id || fallbackLoopId;
  const mappedVersion = Object.entries(snapshot.vertical_mapping || {})
    .find(([, mapping]) => mapping.loop === loopId)?.[0];
  const verticalVersion = explicit.vertical_version || mappedVersion || (loopId === "L2" ? "V3" : null);
  const loop = state.ledger?.loops.find((candidate) => candidate.loop_id === loopId);
  return {
    loopId,
    verticalVersion,
    status: explicit.status || loop?.status || "planned",
  };
}

function renderCurrentPhase() {
  const phase = currentPhase();
  ui.headerState.dataset.state = phase.status;
  ui.headerState.querySelector("b").textContent = [phase.loopId, phase.verticalVersion]
    .filter(Boolean)
    .join(" / ") + ` · ${statusLabel(phase.status)}`;
}

function renderNavigation() {
  clear(ui.loopNav);
  state.ledger.loops.forEach((loop) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-current", String(loop.loop_id === state.selectedLoopId));
    const id = document.createElement("i");
    id.textContent = loop.loop_id;
    const copy = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = loop.name;
    const status = document.createElement("small");
    status.textContent = statusLabel(loop.status);
    copy.append(title, status);
    const indicator = document.createElement("em");
    indicator.dataset.state = loop.status;
    button.append(id, copy, indicator);
    button.addEventListener("click", () => {
      state.selectedLoopId = loop.loop_id;
      render();
    });
    ui.loopNav.append(button);
  });
}

function renderTasks(loop) {
  clear(ui.taskList);
  if (!loop.tasks?.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "本层还没有任务。";
    ui.taskList.append(empty);
    return;
  }
  loop.tasks.forEach((task) => {
    const row = document.createElement("article");
    row.className = "task-row";
    const id = document.createElement("code");
    id.textContent = task.id;
    const copy = document.createElement("span");
    copy.className = "task-copy";
    const title = document.createElement("b");
    title.textContent = task.title;
    const dependency = document.createElement("small");
    dependency.textContent = task.depends_on?.length ? `依赖 ${task.depends_on.join("、")}` : "无前置依赖";
    copy.append(title, dependency);
    const acceptance = document.createElement("div");
    acceptance.className = "task-acceptance";
    const acceptanceCopy = document.createElement("span");
    acceptanceCopy.textContent = task.acceptance || "等待验收定义";
    const evidence = document.createElement("small");
    evidence.className = "task-evidence";
    evidence.textContent = task.evidence_refs?.length
      ? `证据登记（不等于已通过）：${task.evidence_refs.join("；")}`
      : "证据登记：暂无";
    const blockers = document.createElement("small");
    blockers.className = "task-blockers";
    blockers.textContent = task.blocked_by?.length
      ? `当前阻断：${task.blocked_by.join("；")}`
      : "当前阻断：无登记项";
    acceptance.append(acceptanceCopy, evidence, blockers);
    const status = document.createElement("span");
    status.className = "task-status";
    status.dataset.state = task.status;
    status.textContent = statusLabel(task.status);
    row.append(id, copy, acceptance, status);
    ui.taskList.append(row);
  });
}

function renderLoop() {
  const loop = selectedLoop();
  if (!loop) return;
  ui.loopTitle.textContent = `${loop.loop_id} · ${loop.name}`;
  ui.loopOutcome.textContent = loop.outcome;
  ui.loopStatus.dataset.state = loop.status;
  ui.loopStatus.textContent = statusLabel(loop.status);
  const completeStates = new Set(["verified", "accepted"]);
  const completed = loop.tasks.filter((task) => completeStates.has(task.status)).length;
  const percent = loop.tasks.length ? Math.round(completed / loop.tasks.length * 100) : 0;
  ui.progressValue.textContent = `${completed} / ${loop.tasks.length}`;
  ui.progressBar.style.width = `${percent}%`;
  ui.progressDetail.textContent = completed === loop.tasks.length && loop.tasks.length
    ? "本层任务均有 verified / accepted 证据"
    : `仍有 ${loop.tasks.length - completed} 项未达到 verified`;
  ui.gateCopy.textContent = loop.machine_exit_gate?.acceptance || "本层尚未定义机器退出门。";
  ui.gateTarget.textContent = completeStates.has(loop.status) ? "已证实 6/6" : "目标 6/6 · 未证实";
  renderTasks(loop);
}

function render() {
  renderCurrentPhase();
  renderNavigation();
  renderLoop();
}

async function copyCurrentGate() {
  const loop = selectedLoop();
  if (!loop) return;
  const lines = [
    `${loop.loop_id} · ${loop.name}`,
    `目标：${loop.outcome}`,
    `退出门：${loop.machine_exit_gate?.acceptance || "未定义"}`,
    ...loop.tasks.flatMap((task) => [
      `- [${statusLabel(task.status)}] ${task.id} ${task.title}：${task.acceptance}`,
      `  证据登记：${task.evidence_refs?.length ? task.evidence_refs.join("；") : "暂无"}`,
      `  当前阻断：${task.blocked_by?.length ? task.blocked_by.join("；") : "无登记项"}`,
    ]),
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    ui.copyFeedback.textContent = "本层验收清单已复制。";
  } catch (error) {
    ui.copyFeedback.textContent = `复制失败：${error.message}`;
  }
}

async function boot() {
  try {
    const [ledgerResponse, baselineResponse] = await Promise.all([
      fetch("./loop-tasks.json", { cache: "no-store" }),
      fetch("./baseline-evidence.json", { cache: "no-store" }),
    ]);
    if (!ledgerResponse.ok || !baselineResponse.ok) {
      throw new Error(`HTTP ${ledgerResponse.status}/${baselineResponse.status}`);
    }
    state.ledger = await ledgerResponse.json();
    state.baseline = await baselineResponse.json();
    state.selectedLoopId = currentPhase().loopId;
    renderBaseline();
    renderDecisions();
    render();
  } catch (error) {
    clear(ui.taskList);
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = `工作台数据读取失败：${error.message}。请通过本地 HTTP 服务打开此目录。`;
    ui.taskList.append(message);
    ui.copyGate.disabled = true;
  }
}

ui.copyGate.addEventListener("click", copyCurrentGate);
boot();
