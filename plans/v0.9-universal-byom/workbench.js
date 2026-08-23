const STATUS_LABELS = {
  planned: "未启动",
  implementing: "实现中",
  implemented: "已实现",
  verified: "已验证",
  accepted: "已验收",
  blocked: "已阻断",
  failed: "失败",
};

const DECISION_LABELS = [
  "首批接入 Hugging Face 与 GitHub，并固定不可变 Commit。",
  "不可信代码只能进入独立 Worker / OCI；没有隔离环境则只分析不执行。",
  "只做本机资源检测、适配与阻断，不建设云 GPU 调度。",
  "通用支持以统一闭环和证据结论定义，不以 Recipe 数量定义。",
];

const ui = Object.fromEntries([
  "headerState", "loopNav", "loopTitle", "loopOutcome", "progressValue", "progressBar",
  "progressDetail", "loopStatus", "taskList", "decisionList", "baselineHead", "baselineFacts",
  "gateCopy", "copyGate", "copyFeedback",
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
  DECISION_LABELS.forEach((decision) => {
    const item = document.createElement("li");
    item.textContent = decision;
    ui.decisionList.append(item);
  });
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
  ui.baselineHead.textContent = baseline.source.baseline_commit;
  clear(ui.baselineFacts);
  addFact("Python 回归", `${baseline.verified_baseline.python_tests.passed} / ${baseline.verified_baseline.python_tests.passed}`);
  addFact("Node 回归", `${baseline.verified_baseline.node_tests.passed} / ${baseline.verified_baseline.node_tests.passed}`);
  addFact("GitHub 模型源", baseline.current_capability_boundary.github_model_source === "missing" ? "尚未实现" : "已接入");
  addFact("可执行 Recipe Build", baseline.current_capability_boundary.executable_recipe_build === "blocked_environment" ? "当前阻断" : "可执行");
  addFact("隔离执行", baseline.current_capability_boundary.execution_isolation === "missing" ? "尚未实现" : "已可用");
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
    const acceptance = document.createElement("span");
    acceptance.className = "task-acceptance";
    acceptance.textContent = task.acceptance || "等待验收定义";
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
  ui.progressDetail.textContent = completed === loop.tasks.length ? "本层机器证据已经齐全" : `仍有 ${loop.tasks.length - completed} 项未达到 verified`;
  ui.gateCopy.textContent = loop.machine_exit_gate?.acceptance || "本层尚未定义机器退出门。";
  ui.headerState.dataset.state = loop.status;
  ui.headerState.querySelector("b").textContent = `${loop.loop_id} ${statusLabel(loop.status)}`;
  renderTasks(loop);
}

function render() {
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
    ...loop.tasks.map((task) => `- [${statusLabel(task.status)}] ${task.id} ${task.title}：${task.acceptance}`),
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    ui.copyFeedback.textContent = "本层验收清单已复制。";
  } catch (error) {
    ui.copyFeedback.textContent = `复制失败：${error.message}`;
  }
}

async function boot() {
  renderDecisions();
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
    state.selectedLoopId = state.ledger.loops.find((loop) => loop.status === "implementing")?.loop_id || state.ledger.loops[0]?.loop_id;
    renderBaseline();
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
