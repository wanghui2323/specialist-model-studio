const STATUS_LABELS = {
  planned: "未启动",
  implementing: "实现中",
  implemented: "已实现",
  verified: "已验证",
  accepted: "已验收",
  passed: "通过",
  pending: "待验证",
  failed: "失败",
};

const ui = Object.fromEntries([
  "headerStatus", "l0Progress", "l0ProgressText", "l0ProgressValue", "gitHead", "gitBranch",
  "readyFamilyCount", "registryCount", "agentState", "serviceVersion", "evidenceGrid", "loopTabs",
  "loopSummary", "taskTable", "closureTable", "reviewTitle", "reviewDescription", "copyReview",
  "copyFeedback", "footerState", "activeLoopId", "activeLoopTitle", "activeLoopOutcome",
].map((id) => [id, document.getElementById(id)]));

const state = { ledger: null, baseline: null, selectedLoop: null };

function clear(element) { while (element.firstChild) element.firstChild.remove(); }
function label(status) { return STATUS_LABELS[status] || status || "未知"; }

function renderBaseline() {
  const baseline = state.baseline;
  ui.gitHead.textContent = baseline.git.head;
  ui.gitBranch.textContent = baseline.git.branch;
  ui.readyFamilyCount.textContent = String(baseline.capabilities.ready_user_data_families.length);
  ui.registryCount.textContent = `${baseline.capabilities.registered_recipes} / ${baseline.capabilities.registered_data_adapters}`;
  const runtime = baseline.service.agent_runtime_available;
  ui.agentState.textContent = runtime === true ? "已连接" : runtime === false ? "未连接" : "待检查";
  ui.serviceVersion.textContent = baseline.service.version ? `${baseline.service.version} · 当前运行` : "当前运行状态待检查";

  const checks = [
    ["项目自动检查", baseline.verification.project_tests],
    ["真实场景运行", baseline.verification.real_scenarios],
    ["桌面端浏览器", baseline.verification.desktop_browser],
    ["移动端浏览器", baseline.verification.mobile_browser],
  ];
  clear(ui.evidenceGrid);
  checks.forEach(([title, check]) => {
    const article = document.createElement("article"); article.className = "evidence-card";
    const header = document.createElement("header");
    const heading = document.createElement("b"); heading.textContent = title;
    const status = document.createElement("span"); status.dataset.status = check.status; status.textContent = label(check.status);
    header.append(heading, status);
    const copy = document.createElement("p");
    copy.textContent = check.summary || check.command || `视口 ${check.viewport || "—"}`;
    article.append(header, copy); ui.evidenceGrid.append(article);
  });

  clear(ui.closureTable);
  baseline.baseline_closure.forEach((flow) => {
    const row = document.createElement("article"); row.className = "closure-row"; row.dataset.state = flow.state;
    const name = document.createElement("b"); name.textContent = flow.flow.replaceAll("-", " ");
    const score = document.createElement("span"); score.className = "score";
    const currentScore = flow.current_score;
    const fill = document.createElement("i"); fill.style.width = `${currentScore === null ? 0 : currentScore / flow.out_of * 100}%`; score.append(fill);
    const value = document.createElement("span"); value.textContent = `${currentScore === null ? "待刷新" : `${currentScore}/${flow.out_of}`} · ${flow.state}`;
    row.append(name, score, value); ui.closureTable.append(row);
  });
}

function renderLoops() {
  clear(ui.loopTabs);
  state.ledger.loops.forEach((loop) => {
    const button = document.createElement("button"); button.type = "button"; button.role = "tab";
    button.setAttribute("aria-selected", String(loop.loop_id === state.selectedLoop));
    const name = document.createTextNode(`${loop.loop_id} · ${loop.name}`);
    const status = document.createElement("span"); status.textContent = label(loop.status);
    button.append(name, status);
    button.addEventListener("click", () => { state.selectedLoop = loop.loop_id; renderLoops(); });
    ui.loopTabs.append(button);
  });
  const loop = state.ledger.loops.find((item) => item.loop_id === state.selectedLoop) || state.ledger.loops[0];
  clear(ui.loopSummary);
  const copy = document.createElement("div");
  const title = document.createElement("h3"); title.textContent = `${loop.loop_id} · ${loop.name}`;
  const outcome = document.createElement("p"); outcome.textContent = loop.outcome; copy.append(title, outcome);
  const status = document.createElement("span"); status.dataset.status = loop.status; status.textContent = label(loop.status);
  ui.loopSummary.append(copy, status);

  clear(ui.taskTable);
  loop.tasks.forEach((task) => {
    const row = document.createElement("article"); row.className = "task-row";
    const id = document.createElement("span"); id.className = "task-id"; id.textContent = task.id;
    const taskTitle = document.createElement("span"); taskTitle.className = "task-title";
    const name = document.createElement("b"); name.textContent = task.title;
    const dependency = document.createElement("small"); dependency.textContent = task.depends_on?.length ? `依赖：${task.depends_on.join("、")}` : "无前置依赖";
    taskTitle.append(name, dependency);
    const evidence = document.createElement("span"); evidence.className = "task-evidence"; evidence.textContent = task.evidence_refs?.join(" · ") || task.acceptance || "等待证据";
    const taskStatus = document.createElement("span"); taskStatus.className = "task-status"; taskStatus.dataset.status = task.status; taskStatus.textContent = label(task.status);
    row.append(id, taskTitle, evidence, taskStatus); ui.taskTable.append(row);
  });
}

function renderGate() {
  const active = state.ledger.loops.find((loop) => ["implementing", "implemented"].includes(loop.status)) || state.ledger.loops.filter((loop) => loop.status !== "accepted").at(-1) || state.ledger.loops.at(-1);
  const evidenceTasks = active.tasks;
  const verified = evidenceTasks.filter((task) => ["verified", "accepted"].includes(task.status)).length;
  const percent = evidenceTasks.length ? Math.round(verified / evidenceTasks.length * 100) : 0;
  const allVerified = state.ledger.loops.every((loop) => ["verified", "accepted"].includes(loop.status));
  ui.l0Progress.style.width = `${percent}%`;
  ui.l0ProgressValue.textContent = `${verified}/${evidenceTasks.length}`;
  ui.l0ProgressText.textContent = percent === 100 ? "本层证据已经齐全" : `仍有 ${evidenceTasks.length - verified} 项等待验证`;
  ui.activeLoopId.textContent = active.loop_id; ui.activeLoopTitle.textContent = active.name; ui.activeLoopOutcome.textContent = active.outcome;
  ui.copyReview.disabled = true; ui.copyReview.textContent = allVerified ? "本地 Beta 已验证 · 待用户确认" : "最终统一验收时启用"; ui.headerStatus.dataset.status = percent === 100 ? "verified" : "implementing"; ui.headerStatus.lastElementChild.textContent = allVerified ? "L0–L5 已验证" : `${active.loop_id} ${percent === 100 ? "已验证" : "执行中"}`;
  ui.footerState.textContent = allVerified ? "连续 L0–L5 大 Loop · 本地已验证 · GitHub Release 待定" : `连续 L0–L5 大 Loop · 当前 ${active.loop_id} · 2026-08-22`;
  ui.reviewTitle.textContent = `${active.loop_id} · ${active.name}`;
  ui.reviewDescription.textContent = allVerified ? "六层本地必选门禁均已通过；当前是 verified，仍待用户最终验收，GitHub Release 单独记录。" : percent === 100 ? "本层自动证据已通过；大 Loop 会写入证据账本后进入下一层，最终再统一验收。" : `当前 ${verified}/${evidenceTasks.length} 项通过。任何 P0 闭环未达 6/6 都会停留在本层修复。`;
  ui.copyFeedback.textContent = "逐层 verified 不等于最终 accepted；发布动作仍单独记录。";
}

async function boot() {
  try {
    const [ledgerResponse, baselineResponse] = await Promise.all([fetch("./loop-tasks.json"), fetch("./baseline-evidence.json")]);
    if (!ledgerResponse.ok || !baselineResponse.ok) throw new Error(`HTTP ${ledgerResponse.status}/${baselineResponse.status}`);
    state.ledger = await ledgerResponse.json(); state.baseline = await baselineResponse.json();
    state.selectedLoop = state.ledger.loops.find((loop) => ["implementing", "implemented"].includes(loop.status))?.loop_id || state.ledger.loops.filter((loop) => loop.status !== "accepted").at(-1)?.loop_id || state.ledger.loops.at(-1)?.loop_id;
    renderBaseline(); renderLoops(); renderGate();
  } catch (error) {
    ui.evidenceGrid.textContent = `工作台数据读取失败：${error.message}。请通过本地 HTTP 服务打开本目录。`;
    ui.reviewTitle.textContent = "工作台证据不可用";
  }
}

boot();
