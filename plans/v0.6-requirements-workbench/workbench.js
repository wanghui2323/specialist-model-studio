const decisions = [
  { id: "general-shell", title: "先做通用 Agent Workbench", description: "规划、工具、审批和 Context 是可复用框架；模型训练作为第一套领域插件接入。" },
  { id: "three-pane", title: "桌面端采用三栏主结构", description: "左侧任务，中间计划/对话/工具，右侧模型、数据、训练、评测等 Context 可视化。" },
  { id: "vertical", title: "首个真实场景只做图片分类", description: "v0.6 继续用图片文件夹分类证明用户数据闭环，不提前声称 OCR、语音或预测能力。" },
  { id: "task-first", title: "第一次消息先创建 Training Task", description: "产品先生成稳定 task_id，再让 Agent 读取并推进，避免重复任务和会话漂移。" },
  { id: "hide-dsh", title: "DSH 只作为内部运行时", description: "3080 不进入正常用户导航；用户只看到 Model Harness 的产品术语与交互。" },
  { id: "human-gates", title: "保留关键人工门禁", description: "数据授权、标签、门槛、模型下载、启动训练和执行优化都需要可追溯的人类决定。" },
  { id: "hf-depth", title: "HF 首轮先做安全资产入口", description: "首轮完成搜索、Model Card、兼容性和批准下载；只有已实现 Recipe 才能进入构建与调优。" },
  { id: "release-gate", title: "真实性与恢复验证后才发布", description: "真实对话、拒绝不变更、刷新恢复和两种屏幕检查全部通过后才推送 GitHub。" },
];

const state = {
  decisions: JSON.parse(localStorage.getItem("model-harness-v06-decisions") || "{}"),
  data: null,
  selectedLoop: "L0",
};

const ui = Object.fromEntries(["decisionList", "confirmedCount", "progressRing", "gateTitle", "gateDescription", "summaryButton", "copyState", "headerGate", "loopTabs", "loopSummary", "taskTable"].map((id) => [id, document.getElementById(id)]));

function clear(element) { while (element.firstChild) element.firstChild.remove(); }

function renderDecisions() {
  clear(ui.decisionList);
  decisions.forEach((decision, index) => {
    const card = document.createElement("article");
    card.className = "decision-card";
    card.dataset.decision = state.decisions[decision.id] || "waiting";
    const number = document.createElement("span"); number.className = "decision-number"; number.textContent = `DECISION ${String(index + 1).padStart(2, "0")}`;
    const title = document.createElement("h3"); title.textContent = decision.title;
    const copy = document.createElement("p"); copy.textContent = decision.description;
    const actions = document.createElement("div"); actions.className = "decision-actions";
    [["agree", "同意"], ["revise", "需要修改"]].forEach(([value, label]) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = label;
      button.setAttribute("aria-pressed", String(state.decisions[decision.id] === value));
      button.addEventListener("click", () => {
        state.decisions[decision.id] = state.decisions[decision.id] === value ? "waiting" : value;
        localStorage.setItem("model-harness-v06-decisions", JSON.stringify(state.decisions));
        renderDecisions();
      });
      actions.append(button);
    });
    card.append(number, title, copy, actions); ui.decisionList.append(card);
  });
  renderGate();
}

function renderGate() {
  const values = decisions.map((decision) => state.decisions[decision.id]);
  const agreed = values.filter((value) => value === "agree").length;
  const revise = values.filter((value) => value === "revise").length;
  const ready = agreed === decisions.length;
  ui.confirmedCount.textContent = `${agreed}/${decisions.length}`;
  ui.progressRing.style.background = `conic-gradient(#6258f4 ${agreed / decisions.length * 360}deg, transparent 0)`;
  ui.summaryButton.disabled = !ready;
  ui.headerGate.dataset.state = ready ? "ready" : "waiting";
  ui.headerGate.lastElementChild.textContent = ready ? "可以形成启动决议" : "等待确认";
  if (revise) {
    ui.gateTitle.textContent = `${revise} 项需要修改`;
    ui.gateDescription.textContent = "先调整需求合同和 Loop，再重新确认；当前任务仍不会启动。";
  } else if (ready) {
    ui.gateTitle.textContent = "需求边界已经一致";
    ui.gateDescription.textContent = "可以生成摘要并回到对话中明确批准启动 L1。";
  } else {
    ui.gateTitle.textContent = "仍在等待产品确认";
    ui.gateDescription.textContent = `${decisions.length - agreed} 项还没有明确同意。工作台不会自动启动开发。`;
  }
}

function renderLoops() {
  clear(ui.loopTabs);
  state.data.loops.forEach((loop) => {
    const button = document.createElement("button"); button.type = "button"; button.role = "tab";
    button.setAttribute("aria-selected", String(loop.loop_id === state.selectedLoop));
    button.textContent = `${loop.loop_id} · ${loop.name}`;
    button.addEventListener("click", () => { state.selectedLoop = loop.loop_id; renderLoops(); });
    ui.loopTabs.append(button);
  });
  const loop = state.data.loops.find((item) => item.loop_id === state.selectedLoop) || state.data.loops[0];
  clear(ui.loopSummary);
  const title = document.createElement("h3"); title.textContent = `${loop.loop_id} · ${loop.name}`;
  const copy = document.createElement("p"); copy.textContent = loop.outcome;
  ui.loopSummary.append(title, copy);
  clear(ui.taskTable);
  loop.tasks.forEach((task) => {
    const row = document.createElement("article"); row.className = "task-row";
    const id = document.createElement("span"); id.className = "task-id"; id.textContent = task.id;
    const taskTitle = document.createElement("span"); taskTitle.className = "task-title";
    const name = document.createElement("b"); name.textContent = task.title;
    const dependency = document.createElement("span"); dependency.textContent = task.depends_on?.length ? `依赖：${task.depends_on.join("、")}` : "无前置依赖";
    taskTitle.append(name, dependency);
    const evidence = document.createElement("span"); evidence.className = "task-evidence"; evidence.textContent = task.acceptance || task.evidence || "待补充验收证据";
    const status = document.createElement("span"); status.className = "task-status"; status.dataset.status = task.status; status.textContent = ({ done: "已完成", review: "审查中", planned: "未启动", "awaiting-confirmation": "待确认" })[task.status] || task.status;
    row.append(id, taskTitle, evidence, status); ui.taskTable.append(row);
  });
}

ui.summaryButton.addEventListener("click", async () => {
  const summary = [
    "我确认 Model Harness v0.6 的 8 个产品决策，并批准启动 L1「Agent 工作台骨架」。",
    "本轮采用通用 Agent Workbench 三栏框架，模型训练作为第一套领域插件；Hugging Face 首轮先做到搜索、兼容性与批准下载；DSH 仅作内部运行时。",
  ].join("\n");
  try {
    await navigator.clipboard.writeText(summary);
    ui.copyState.textContent = "确认摘要已复制，请粘贴回项目对话中完成启动批准。";
  } catch {
    ui.copyState.textContent = summary;
  }
});

async function boot() {
  renderDecisions();
  bindPrototype();
  try {
    const response = await fetch("./loop-tasks.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    renderLoops();
  } catch (error) {
    ui.loopSummary.textContent = `任务账本读取失败：${error.message}。请通过本地 HTTP 服务打开本目录。`;
  }
}

const prototypeContexts = {
  model: `
    <div class="context-model"><span>SELECTED MODEL</span><div><i>HF</i><span><b>google/vit-base-patch16-224</b><small>Image classification · 86.6M</small></span></div><dl><div><dt>Revision</dt><dd>3f1b…c92</dd></div><div><dt>License</dt><dd>Apache-2.0</dd></div><div><dt>Compatibility</dt><dd>Recipe ready</dd></div></dl><button type="button">查看 Model Card <span>↗</span></button></div>
    <div class="context-status"><span><i></i>本机兼容性</span><b>可以进入已实现 Recipe</b><div><i style="width:100%"></i></div><small>内存、依赖与任务类型检查已通过</small></div>`,
  data: `
    <div class="context-status"><span><i></i>数据合同</span><b>零件颜色分类 · v3</b><div><i style="width:88%"></i></div><small><strong>1,248</strong> 张图片 · 4 类 · 12 条待复核</small></div>
    <div class="context-model"><span>DATA QUALITY</span><dl><div><dt>训练 / 验证 / 测试</dt><dd>70 / 15 / 15</dd></div><div><dt>重复样本</dt><dd>7</dd></div><div><dt>疑似错标</dt><dd>5</dd></div><div><dt>授权状态</dt><dd>已确认</dd></div></dl><button type="button">打开数据体检 <span>↗</span></button></div>`,
  training: `
    <div class="context-status"><span><i></i>当前阶段</span><b>训练候选模型</b><div><i style="width:62%"></i></div><small><strong>3 / 4</strong> candidates · 预计还需 18 秒</small></div>
    <div class="context-chart"><header><span>Validation Macro-F1</span><b>0.921</b></header><div class="chart-grid"><span></span><span></span><span></span><i style="height:42%"><em>LR</em></i><i class="best" style="height:86%"><em>SVC</em></i><i style="height:71%"><em>RF</em></i><i class="pending" style="height:22%"><em>ViT</em></i></div><small>数据来自 MH-RUN-018 的事件流</small></div>
    <div class="context-model"><span>HUGGING FACE MODEL</span><div><i>HF</i><span><b>google/vit-base-patch16-224</b><small>Image classification · 86.6M</small></span></div><dl><div><dt>Revision</dt><dd>3f1b…c92</dd></div><div><dt>License</dt><dd>Apache-2.0</dd></div></dl><button type="button">查看 Model Card <span>↗</span></button></div>`,
  evaluation: `
    <div class="context-chart"><header><span>Independent Test Macro-F1</span><b>0.908</b></header><div class="chart-grid"><span></span><span></span><span></span><i style="height:39%"><em>LR</em></i><i class="best" style="height:82%"><em>SVC</em></i><i style="height:66%"><em>RF</em></i><i style="height:58%"><em>ViT</em></i></div><small>独立测试集 · 188 samples · MH-EVAL-006</small></div>
    <div class="context-model"><span>ERROR SLICES</span><dl><div><dt>弱光零件</dt><dd>F1 0.81</dd></div><div><dt>反光表面</dt><dd>F1 0.84</dd></div><div><dt>小尺寸目标</dt><dd>F1 0.79</dd></div></dl><button type="button">查看失败样本 <span>↗</span></button></div>`,
  artifacts: `
    <div class="context-status"><span><i></i>产物血缘</span><b>3 个产物可回溯</b><div><i style="width:100%"></i></div><small>全部关联 MH-RUN-018 与数据合同 v3</small></div>
    <div class="context-model"><span>DELIVERABLES</span><dl><div><dt>best-model.joblib</dt><dd>12.4 MB</dd></div><div><dt>evaluation-report.html</dt><dd>284 KB</dd></div><div><dt>run-manifest.json</dt><dd>18 KB</dd></div></dl><button type="button">打开产物目录 <span>↗</span></button></div>
    <div class="context-model"><span>REPRODUCIBILITY</span><dl><div><dt>Dataset</dt><dd>contract:v3</dd></div><div><dt>Code</dt><dd>recipe:8d2a</dd></div><div><dt>Environment</dt><dd>env:41cc</dd></div></dl><button type="button">查看运行清单 <span>↗</span></button></div>`,
};

function bindPrototype() {
  const taskTitle = document.getElementById("prototypeTaskTitle");
  document.querySelectorAll(".mock-task").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".mock-task").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      taskTitle.textContent = button.dataset.task;
    });
  });

  const panel = document.getElementById("prototypeContextPanel");
  document.querySelectorAll("[data-context]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-context]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      panel.innerHTML = prototypeContexts[button.dataset.context];
    });
  });

  document.querySelectorAll(".approval-actions button").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".approval-card");
      card.dataset.prototypeDecision = button.textContent.includes("批准") ? "approved" : "denied";
      card.querySelector("small").textContent = button.textContent.includes("批准") ? "原型状态 · 已批准，任务可继续" : "原型状态 · 已拒绝，任务保持暂停";
      card.querySelectorAll("button").forEach((item) => { item.disabled = true; });
    });
  });
}

boot();
