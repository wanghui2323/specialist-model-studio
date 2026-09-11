# v0.8 审计整改执行方案

本文件是给**执行型 AI 编码代理**的施工单，不是设计讨论稿。
每个任务都给出：精确文件位置、精确改动、**机器可校验的验收门**、以及禁止事项。

审计结论来源：对 v0.7.0-beta.1（commit `395bd6b`）的后端逻辑审计与前端交互审计。
所有行号基于该 commit，改动前请用 `git rev-parse HEAD` 确认。

---

## 0. 给执行代理的硬性规则（必须先读完）

这些规则的优先级高于任何单个任务描述。违反其中任何一条，本次改动即视为失败。

1. **一次只做一个任务。** 完成一个任务、跑通它的验收门、报告结果，然后停下等下一条指令。不要连续做多个任务。
2. **不要扩大范围。** 只改任务里明确点名的文件和行。看到别的问题就记录下来汇报，不要顺手改。
3. **不要重构。** 不改函数签名、不换库、不引入新依赖、不改目录结构、不"顺便优化"命名或格式。
4. **不要改验收门槛和测试断言来让测试通过。** 如果 `acceptance/v0.7-gates.json`、`tests/` 里已有的断言挡住了你，说明你的实现错了，不是断言错了。唯一允许改测试的情况是任务明确要求"新增测试"。
5. **不要碰这些文件**（人工所有，除任务明确指定外）：
   - `acceptance/v0.7-gates.json`
   - `plans/**/loop-tasks.json`
   - `AGENTS.md`
   - 任何已有测试的断言内容
6. **每个任务结束必须跑：** `.venv/bin/python -m unittest discover -s tests`
   基线是 **140 个测试全部通过**。任务后测试数只能增加（新增测试），不能减少，不能有失败。
7. **报告格式固定为：**
   ```
   任务编号：
   改了哪些文件（含行号范围）：
   验收门命令与输出（原样粘贴）：
   单测结果：Ran N tests / OK 或 FAILED
   遗留问题或我拿不准的地方：
   ```
8. **不确定就停下来问，不要猜。** 特别是涉及"这个门槛该设多少""这个策略选哪个"的地方——这些是人工决定，你没有决定权。

---

## 1. 环境准备（只做一次）

```bash
cd /Users/wanghui2100/Documents/Projects/ai-pm-model-harness
git rev-parse HEAD                     # 记录基线 commit
git status --short                     # 必须干净
.venv/bin/python -m unittest discover -s tests   # 必须 Ran 140 tests / OK
```

如果基线单测不是 140 通过，**停下来汇报**，不要开始改。

### 建立前端验收工具（Round 1 需要）

```bash
mkdir -p /tmp/mh-verify && cd /tmp/mh-verify
npm init -y >/dev/null && npm i playwright@1.62.1
```

启动被测服务（每个前端任务验收前都要起）：

```bash
cd /Users/wanghui2100/Documents/Projects/ai-pm-model-harness
.venv/bin/python -m uvicorn --factory model_harness.server:create_app \
  --host 127.0.0.1 --port 8799 > /tmp/mh-server.log 2>&1 &
sleep 4 && curl -s http://127.0.0.1:8799/health
```

验收完关掉：`pkill -f "uvicorn --factory model_harness.server"`

---

## Round 1：前端可信呈现（纯前端，零后端风险）

这一轮解决"界面上两个结论互相矛盾"的问题。只碰 3 个文件：
`model_harness/web/index.html`、`model_harness/web/app.js`、`model_harness/web/styles.css`。

---

### T1 · 五阶段生命周期只保留一处，术语统一

**问题**：顶部 `task-plan` 横向步进条和右侧 `stage-list` 纵向列表是同一个五阶段生命周期的两套实现，五个标签里四个措辞不同（"识别能力/定义任务"、"准备数据/检查数据"、"冻结合同/确认合同"、"交付优化/优化交付"），且两者状态判定逻辑不同，会同屏显示矛盾结论。

**决定（不要再讨论）**：保留右侧 `stage-list` 作为唯一进度面板（它带每步明细）。顶部只保留"当前阶段 + N/5"文字，删掉横向步进条。

#### 改动 1.1 — `model_harness/web/index.html`

删除第 56 行的 `<ol id="taskPlanSteps"></ol>`。改动后该 section 为：

```html
        <section class="task-plan" id="taskPlan" hidden>
          <div class="task-plan-heading"><span>当前计划</span><b id="taskPlanTitle">识别能力并准备数据合同</b><strong id="taskPlanProgress">1 / 5</strong></div>
        </section>
```

#### 改动 1.2 — `model_harness/web/app.js`

在 `STAGE_LABELS` 常量定义之后（第 52 行后）新增唯一术语表：

```js
const LIFECYCLE_STEPS = ["定义任务", "检查数据", "确认合同", "训练评测", "优化交付"];
```

把 `ui` 元素清单（第 20 行）里的 `"taskPlanSteps"` 删掉。

替换整个 `renderPlan` 函数（第 232–236 行）为：

```js
function renderPlan(task) {
  ui.taskPlanTitle.textContent = stageLabel(stageKey(task));
  ui.taskPlanProgress.textContent = `${planState(task)} / 5`;
}
```

注意：旧标签数组 `const labels = ["识别能力", "准备数据", "冻结合同", "训练评测", "交付优化"]`
就在第 233 行 `renderPlan` 内部，随这次替换一起删除——它是"术语两套"的根源。
同时把 `index.html` 第 55 行 `taskPlanTitle` 的占位文案
`识别能力并准备数据合同` 改成 `定义任务`，与新术语表一致。

在 `renderStages`（第 243 行起）里，把 `stages` 数组的标题改为引用 `LIFECYCLE_STEPS`，即把这五行的第一个元素替换掉：

```js
  const stages = [
    [LIFECYCLE_STEPS[0], blocked ? "能力缺口已记录" : `Recipe：${task.recipe_id || "待确认"}`],
    [LIFECYCLE_STEPS[1], hasData ? `${dataCount} · ${dataSummary}` : blocked ? "等待训练方案 / 数据读取器" : "等待导入"],
    [LIFECYCLE_STEPS[2], confirmed ? "授权、标签/目标、门槛已确认" : "等待人工确认"],
    [LIFECYCLE_STEPS[3], finished ? "真实训练与独立评测完成" : result ? `运行状态：${result.status}` : "尚未启动"],
    [LIFECYCLE_STEPS[4], deliveryDetail(task)],
  ];
```

`deliveryDetail` 在 T3 里定义。**T1 阶段先用占位实现**，放在 `renderStages` 之前：

```js
function deliveryDetail(task) {
  return task.current_result?.status === "completed" ? "查看评测结论" : "等待评测结果";
}
```

#### 改动 1.3 — `model_harness/web/styles.css`

删除 `.task-plan ol`、`.task-plan li`、`.task-plan li:after`、`.task-plan li:last-child:after`、`.task-plan li i`、`.task-plan li.done`、`.task-plan li.done i`、`.task-plan li.active`、`.task-plan li.active i` 这些规则（集中在第 5 行）。同时删除第 11 行 `@media(max-width:1180px)` 里的 `.task-plan li{font-size:7px}`，以及第 13 行 `@media(max-width:720px)` 里的 `.task-plan-heading{min-width:620px}` 和 `.task-plan ol{min-width:620px}`，还有第 69 行的 `.task-plan ol{display:none}`。

#### T1 验收门

```bash
# 1. renderPlan 内联的那份标签数组已删除
rg -n '识别能力|准备数据|交付优化' model_harness/web/app.js
#    期望输出：空
#    注意："冻结合同"不要用来检查——它在第 204/205/559/567 行是正常业务文案
#    （"同一冻结合同""已冻结合同"），必须保留。

# 2. 术语表唯一且被两处共用
rg -c 'LIFECYCLE_STEPS' model_harness/web/app.js
#    期望：6（1 处定义 + renderStages 里 5 次引用）

# 3. taskPlanSteps 完全消失
rg -n 'taskPlanSteps' model_harness/web/index.html model_harness/web/app.js
#    期望输出：空

# 4. stage-item 仍然渲染五步（防止误删列表）
rg -n 'stage-item' model_harness/web/app.js
#    期望：第 253 行附近仍有 item.className = "stage-item"

# 5. 单测
.venv/bin/python -m unittest discover -s tests
#    期望：Ran 140 tests / OK
```

**禁止**：不要改 `STAGE_LABELS`（那是后端 stage key 的翻译表，用途不同）。不要动 `planState` 的返回值逻辑（T2 处理）。

---

### T2 · 进度不再提前变绿

**问题**：`planState` 在 `evaluation` 阶段返回 5，而删除前的 `renderPlan` 用 `current === 5` 把全部五步标成"完成"，导致刚进入评测就显示"交付优化 ✓ 5/5"，此时 `release_ready` 还是 `false`。T1 删掉了那个步进条，但右侧列表的第 5 步判定也需要收紧。

#### 改动 2.1 — `model_harness/web/app.js`

在 `renderStages`（第 252 行）把 stageState 判定替换为：

```js
  const releaseDone = releaseVerdict(task).releaseReady === true;
  clear(ui.stageList); stages.forEach(([title, detail], index) => {
    const stageState = index + 1 < current
      ? "done"
      : index + 1 === current
        ? (index === 4 && releaseDone ? "done" : "active")
        : "waiting";
```

（其余循环体不变。注意：原来那段 `(current === 5 && index < 4)` 的分支整体删除。）

`releaseVerdict` 在 T3 定义。**T2 必须和 T3 一起提交**，因为二者互相依赖。如果你先做 T2，请先把 T3 的 `releaseVerdict` 函数加上。

#### T2+T3 联合验收门

见 T3。

**禁止**：不要修改 `planState` 函数本体。它的返回值被 `renderPlan` 和 `renderStages` 共用，改它会连带影响别处。

---

### T3 · 头条结论改由 `conclusion` 驱动

**问题**（这是最严重的一条）：后端 `EvaluationReport` 是六维模型且自洽——真实抓取的一次运行返回
`metric_gate_status=passed` 但 `evidence_status=insufficient_evidence`、`conclusion=insufficient_evidence`、`release_ready=False`（测试集只有 9 条，低于最低 20 条）。
前端把第三个维度（指标门槛）渲染成最大最绿的头条"**门槛通过**"，把真正的结论塞进下面一张次级卡片写成"证据不足"。同屏还有"可下载制品"。用户先读到的是最绿的那个。

#### 改动 3.1 — `model_harness/web/app.js`，新增统一结论函数

放在 `metricEntries`（第 371 行）之前：

```js
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
```

把 T1 里的占位 `deliveryDetail` 替换为真实实现：

```js
function deliveryDetail(task) {
  const result = task.current_result;
  if (!result || result.status !== "completed") return "等待评测结果";
  const verdict = releaseVerdict(task);
  if (verdict.releaseReady) return "证据充分，可生成交付包";
  return `${statusLabel(verdict.conclusion)}：${verdict.reasons[0] || "查看五维评测结论"}`;
}
```

#### 改动 3.2 — 头条徽章

替换 `renderResult` 里第 377 行那一整行（`const running = ...` 到行尾）为：

```js
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
```

#### 改动 3.3 — 把"指标门槛"降为明细行

`renderResult` 里 `metricEntries(result).forEach(...)` 那段之后（第 378 行末），追加一行说明，让指标门槛不再冒充结论：

```js
  const gateNote = document.createElement("p");
  gateNote.className = "gate-note";
  gateNote.textContent = result.offline_gates_passed === true
    ? "离线指标门槛已通过；是否可交付另见下方五维结论。"
    : "离线指标门槛未全部通过。";
  ui.metricGrid.after(gateNote);
```

注意：`renderResult` 每次都会重建，需要防止重复插入。在 `clear(ui.metricGrid)` 之后、循环之前加一行：

```js
  ui.resultCard.querySelector(".gate-note")?.remove();
```

#### 改动 3.4 — `model_harness/web/styles.css`，头条徽章配色

在文件末尾追加：

```css
/* v0.8 头条结论徽章：颜色由 conclusion 决定，不再由指标门槛决定 */
#gateResult[data-state="passed"]{color:var(--green)}
#gateResult[data-state="failed"]{color:var(--red)}
#gateResult[data-state="warning"]{color:var(--amber)}
#gateResult[data-state="neutral"]{color:var(--muted)}
.gate-note{margin:0 0 9px!important;color:var(--muted);line-height:1.5}
```

#### T2+T3 验收门

这个门需要真实跑一个"门槛通过但证据不足"的运行，然后断言界面上不再出现"门槛通过"作为头条。

把下面脚本存为 `/tmp/mh-verify/verify-t3.mjs`：

```js
import { chromium } from "playwright";
const TASK = process.env.TASK_ID;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`http://127.0.0.1:8799/app?task=${encodeURIComponent(TASK)}`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.click('[data-context="evaluation"]');
await page.waitForTimeout(600);
const out = await page.evaluate(() => ({
  headline: document.getElementById("gateResult")?.textContent?.trim(),
  headlineState: document.getElementById("gateResult")?.dataset?.state,
  conclusion: document.getElementById("evaluationConclusion")?.textContent?.trim(),
  stage5: [...document.querySelectorAll("#stageList .stage-item")].pop()?.dataset?.state,
  stage5Text: [...document.querySelectorAll("#stageList .stage-item")].pop()?.textContent?.trim(),
}));
const fail = [];
if (out.headline === "门槛通过") fail.push("头条仍然是指标门槛，不是 conclusion");
if (out.headline !== out.conclusion) fail.push(`头条(${out.headline})与五维结论(${out.conclusion})不一致`);
if (out.stage5 === "done") fail.push("release_ready=false 时第 5 步仍被标成完成");
console.log(JSON.stringify(out, null, 2));
console.log(fail.length ? "FAIL:\n" + fail.join("\n") : "PASS");
await browser.close();
process.exit(fail.length ? 1 : 0);
```

跑法（`TASK_ID` 用你自己造的那个证据不足的任务；造法见文末附录 A）：

```bash
cd /tmp/mh-verify
PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" TASK_ID='<你的任务ID>' node verify-t3.mjs
#   期望最后一行：PASS
```

改前基线（我实测）：`headline="门槛通过"`、`conclusion="证据不足"`、`stage5="active"` 但顶部步进条 5/5 全绿 → FAIL。
改后期望：`headline="证据不足"`、`headlineState="warning"`、两者一致 → PASS。

**禁止**：不要为了让头条变绿去改后端的 `minimum_test_samples` 默认值 20。那是人工所有的策略。

---

### T4 · 主按钮直连 API，删掉自动发消息

**问题**：`startThroughAgentButton` 一个按钮四种行为、四种标签，其中最关键的分支是逻辑倒置——Agent Runtime **连上时**，标签写着"让 Agent 启动真实训练"的按钮不调 `POST /tasks/{id}/runs`，只是把一句中文发给 LLM，指望 LLM 自己决定调不调工具；Runtime **没连上时**才走 `startRunDirect()` 真正启动。降级路径确定，正常路径概率性。
另外数据导入成功后和合同确认后各有一处 `submitMessage(...)` 副作用，会往对话里插一句用户没写的话。

#### 改动 4.1 — 按钮行为（`app.js` 第 726–730 行整体替换）

```js
ui.startThroughAgentButton.addEventListener("click", () => {
  if (TERMINAL_RETRY_STATUSES.has(state.task?.current_result?.status)) { retryRunDirect(); return; }
  if (state.task?.current_run_id && state.task.status !== "ready") { openInspector("evaluation"); return; }
  startRunDirect();
});
```

#### 改动 4.2 — 按钮标签（`app.js` 第 368 行第二句）

把
```js
ui.startThroughAgentButton.textContent = retryable ? "保留证据并重新训练" : task.current_run_id ? "分析结果或开启下一轮" : state.runtimeReady ? "让 Agent 启动真实训练" : "批准并启动真实训练";
```
替换为
```js
ui.startThroughAgentButton.textContent = retryable ? "保留证据并重新训练" : task.current_run_id ? "查看本轮评测结论" : "批准并启动真实训练";
```

#### 改动 4.3 — 删掉两处自动发消息

`uploadDataset` 第 685 行，把
```js
  try { await request(...); showNotice("后端已真实导入数据并完成体检。", "ok"); activateContext("data"); await refreshSelected({ force: true }); if (state.runtimeReady) await submitMessage(`我已通过产品界面导入数据集 ${file.name}。请读取真实体检结果并解释风险。`); }
```
改成（只删掉末尾那个 `if (state.runtimeReady) await submitMessage(...)`）：
```js
  try { await request(...); showNotice("后端已真实导入数据并完成体检。", "ok"); activateContext("data"); await refreshSelected({ force: true }); }
```

`confirmContract` 第 692 行同理，删掉末尾的 `if (state.runtimeReady) await submitMessage("我已明确确认数据授权、标签或目标字段和离线验收门槛。请读取最新合同。");`。

#### T4 验收门

```bash
# 1. 按钮不再靠 runtimeReady 决定是否真正启动
rg -n 'runtimeReady.*submitMessage|submitMessage.*启动真实训练' model_harness/web/app.js
#    期望输出：空

# 2. 导入数据/确认合同不再自动发消息
rg -n 'await submitMessage' model_harness/web/app.js
#    期望输出：空（submitMessage 只应由 composerForm 的 submit 调用）

# 3. 启动训练的唯一入口是 startRunDirect / retryRunDirect
rg -n 'POST.*tasks.*runs|/runs`, \{ method: "POST"' model_harness/web/app.js
#    期望：只出现在 startRunDirect 和 retryRunDirect 两个函数里

.venv/bin/python -m unittest discover -s tests
```

**禁止**：不要顺手新增"让 Agent 分析结果"按钮。用户想问 Agent 就用输入框，不要再加控件。

---

### T5 · 字号下限 12px

**问题**（实测数据）：`body` 是 13px，但右侧 inspector 面板里我用 `getComputedStyle` 量到 **21 个元素是 7px、9 个是 8px**，只有 2 个 11px。那块面板承载全部证据信息（门槛、指标、五维结论、HF 模型卡、候选对比、失败样本、交付包）。汉字在 7px 笔画会糊成一团，CJK 可读下限约 12px。

**这是本轮唯一会影响布局的任务，务必单独提交、单独验收。**

#### 改动 5.1 — `model_harness/web/styles.css` 全局字号映射

对 `styles.css` 里**每一处** `font-size` 按下表替换，不要漏，也不要自己发明中间值：

| 原值 | 新值 |
|---|---|
| 6px | 12px |
| 7px | 12px |
| 8px | 13px |
| 9px | 13px |
| 10px | 14px |
| 11px | 15px |
| 12px | 16px |
| 13px（`body`、`.task-spec-header h2`）| 14px |
| 14px（`.topbar h1`）| 17px |
| 18px（`.decision-dialog h2`）| 20px |
| 28px / 32px（`.empty-state h2`）| 保持不变 |

`font-size:0`（`.mobile-view-nav button>span`，那是 CSS 画图标用的）**保持不变**。

#### 改动 5.2 — 放开被字号撑破的容器

字号变大后，靠 `nowrap + ellipsis` 硬压的行会大面积截断。删除下列选择器里的 `white-space:nowrap` 和 `text-overflow:ellipsis`，并补 `line-height:1.45`：

- `.gate-grid span`、`.metric-grid span`（第 9 行）
- `.capability-facts b`（第 9 行）
- `.asset-fact-list code`、`.asset-fact-list b`（第 103 行）
- `.hf-model-facts dd`（第 137 行）
- `.candidate-row b` 等一组（第 161 行）
- `.stage-copy span`（改为允许换行）

同时把这些固定高度改为最小高度，让内容能撑开：
- `.task-plan-heading{min-height:48px}` → 保持（它是单行）
- `.stage-item{min-height:41px}` → `min-height:52px`
- `.context-tabs button{height:36px}` → `min-height:40px;height:auto`
- `.inspector-header{min-height:56px}` → 保持

顶部 H1 与眉标的 `max-width` 需要放宽：`.topbar h1{max-width:560px}` → `max-width:none;flex:1`。

#### T5 验收门（关键：机器断言，不许目测）

存为 `/tmp/mh-verify/verify-fontsize.mjs`：

```js
import { chromium } from "playwright";
const TASK = process.env.TASK_ID;
const browser = await chromium.launch();
const results = [];
for (const [name, viewport] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  await page.goto(`http://127.0.0.1:8799/app?task=${encodeURIComponent(TASK)}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  for (const tab of ["capability", "data", "run", "evaluation", "artifacts"]) {
    if (name === "mobile") await page.click("#mobileContextButton").catch(() => {});
    await page.click(`[data-context="${tab}"]`).catch(() => {});
    await page.waitForTimeout(300);
    const bad = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll("body *").forEach((el) => {
        const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
        if (!hasText) return;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return;
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size > 0 && size < 12) out.push({ size, text: el.textContent.trim().slice(0, 30) });
      });
      return out;
    });
    bad.forEach((b) => results.push({ viewport: name, tab, ...b }));
  }
  // 顺带查文字截断
  const clipped = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((el) => {
        const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
        if (!hasText || el.offsetParent === null) return false;
        return el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2;
      })
      .map((el) => ({ cls: el.className?.toString().slice(0, 30), text: el.textContent.trim().slice(0, 30) }))
  );
  clipped.forEach((c) => results.push({ viewport: name, kind: "clipped", ...c }));
  await page.close();
}
console.log(JSON.stringify(results, null, 2));
console.log(results.length ? `FAIL: ${results.length} 处问题` : "PASS");
await browser.close();
process.exit(results.length ? 1 : 0);
```

```bash
cd /tmp/mh-verify
PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" TASK_ID='<你的任务ID>' node verify-fontsize.mjs
#   期望最后一行：PASS（既没有 <12px 文字，也没有截断）
```

改前基线：desktop 单个 tab 就有 30 处 <12px。

另外必须补一条静态检查：

```bash
rg -n 'font-size:(6|7|8|9|10|11)px' model_harness/web/styles.css
#   期望输出：空
```

**禁止**：不要用 `transform: scale()`、不要改 `html{font-size}` 来"整体放大"、不要把 px 换成 rem。就按映射表逐个改。

---

## Round 2：前端状态正确性

### T6 · 轮询并发保护

**问题**：`selectTask` 每 1400ms 触发一次 `refreshSelected`（第 156 行），而 `refreshSelected` 内部有 3 个串行 `await`（task → events → conversation）。后端慢于 1.4s 时请求会重叠，先发后到的旧响应覆盖新状态。`selectionToken` 只防任务切换，不防同任务并发。这正是"把旧 run 当作当前结果展示"的风险来源。

#### 改动 — `app.js`

在 `state` 对象（第 42 行）里加两个字段：

```js
  refreshInFlight: false, refreshSeq: 0,
```

`refreshSelected`（第 158 行）函数体最外层加护栏：

```js
async function refreshSelected({ force = false, token = state.selectionToken } = {}) {
  const taskId = state.selectedTaskId; if (!taskId || token !== state.selectionToken) return;
  if (state.refreshInFlight && !force) return;
  const seq = ++state.refreshSeq;
  state.refreshInFlight = true;
  try {
    // ... 原有函数体保持不变，但在每次 await 之后的判断里
    //     把 `token !== state.selectionToken` 改成
    //     `token !== state.selectionToken || seq !== state.refreshSeq`
  } finally {
    state.refreshInFlight = false;
  }
}
```

具体来说，原本三处守卫（第 161、171 行等）都要补 `|| seq !== state.refreshSeq`。

#### T6 验收门

```bash
rg -n 'refreshInFlight|refreshSeq' model_harness/web/app.js
#   期望：至少 5 处命中（state 声明 2 处 + 函数内 3 处以上）
```

再跑一个并发断言，存为 `/tmp/mh-verify/verify-poll.mjs`：

```js
import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage();
let inFlight = 0, maxConcurrent = 0;
await page.route("**/tasks/*", async (route) => {
  inFlight += 1; maxConcurrent = Math.max(maxConcurrent, inFlight);
  await new Promise((r) => setTimeout(r, 2200));   // 人为让后端比轮询间隔慢
  await route.continue();
  inFlight -= 1;
});
await page.goto(`http://127.0.0.1:8799/app?task=${encodeURIComponent(process.env.TASK_ID)}`);
await page.waitForTimeout(12000);
console.log("同时在飞的 /tasks 请求峰值:", maxConcurrent);
console.log(maxConcurrent <= 1 ? "PASS" : "FAIL: 轮询重叠了");
await browser.close();
process.exit(maxConcurrent <= 1 ? 0 : 1);
```

改前基线：峰值应 ≥ 3。改后期望：≤ 1，输出 PASS。

---

### T7 · 任务列表加区分信息

**问题**（我实测撞到）：任务名由 `deriveTaskName()`（第 551 行）从业务目标正则截取，列表项只渲染 `name + 状态点 + 时间`（第 136–143 行）。我跑两次同一个脚本就得到两个都叫"外观质检分类"的任务，侧边栏里视觉上无法区分。任何重试或相似目标都会这样。

#### 改动 — `app.js` 的 `renderTaskList`（第 133–144 行）

在 `meta` 里追加第三段信息：Recipe（或能力状态）+ 数据规模。`/tasks` 列表返回的字段名请先用
`curl -s http://127.0.0.1:8799/tasks | .venv/bin/python -m json.tool | head -60` 确认，然后用真实存在的字段，**不要凭猜写字段名**。

最低要求：每个列表项必须显示 `task_id` 的短形式（用已有的 `shortId()`），使同名任务可区分。

```js
    const idHint = document.createElement("small");
    idHint.className = "task-id-hint";
    idHint.textContent = shortId(task.task_id);
    idHint.title = task.task_id;
    button.append(title, meta, idHint);
```

`styles.css` 末尾追加：

```css
.task-id-hint{display:block;overflow:hidden;color:var(--muted);font-size:12px;text-overflow:ellipsis;white-space:nowrap}
```

#### T7 验收门

用附录 A 的脚本连续造两个**同名**任务，然后：

```js
// /tmp/mh-verify/verify-tasklist.mjs
import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("http://127.0.0.1:8799/app", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
const labels = await page.$$eval(".task-item", (els) => els.map((e) => e.textContent.trim()));
const dupes = labels.length - new Set(labels).size;
console.log(labels);
console.log(dupes === 0 ? "PASS" : `FAIL: ${dupes} 个列表项文本完全相同`);
await browser.close();
process.exit(dupes === 0 ? 0 : 1);
```

---

### T8 · 任务需要终止状态（归档）

**问题**：`server.py`、`workspace.py`、`service.py` 和整个前端**都没有** DELETE / archive / remove。任务只能创建不能移除，侧边栏单向累积。唯一清理办法是手工 `rm -rf runs/_workspace/tasks/<id>`。

**这个任务要改后端，风险高于 Round 1。策略已定，不要自行发挥：做"归档"（软删除），不做物理删除**——因为 AGENTS.md 要求运行证据不被覆盖或丢失。

#### 行为契约（先写测试，再写实现）

在 `tests/` 新增 `test_task_archive.py`，必须包含以下断言：

1. `POST /tasks/{id}/archive` 对一个 `status != "running"` 的任务返回 200，且该任务的 `archived_at_utc` 非空。
2. 归档后 `GET /tasks` 默认**不再**返回该任务；`GET /tasks?include_archived=true` 仍然返回。
3. `GET /tasks/{id}` 归档后仍可访问（证据不丢）。
4. 对 `status == "running"` 的任务归档返回 409，且任务未被修改。
5. 归档一个不存在的 task_id 返回 404。
6. 归档后再 `POST /tasks/{id}/runs` 返回 409（不能给归档任务启动新训练）。
7. `runs/` 目录下该任务的运行目录**仍然存在**（断言目录还在）。

前端：`renderTaskList` 的每个 `.task-item` 加一个归档图标按钮，走 `openSimpleDialog` 二次确认。

#### T8 验收门

```bash
.venv/bin/python -m unittest tests.test_task_archive -v
#   期望：7 个测试全过

.venv/bin/python -m unittest discover -s tests
#   期望：Ran 147 tests / OK（140 + 7）
```

**禁止**：不要加物理删除端点。不要在归档时删 `runs/` 下任何文件。

---

### T9 · 移动端两处硬伤

**问题**：
- `.runtime-pill span{display:none}`（styles.css 第 13 行）让 Agent Runtime 状态变成一个**没有任何标签**的彩色圆点，既无 `aria-label` 也无 `title`。
- `.next-action-copy p{display:none}`（第 66 行）把"唯一下一步"的整段解释藏了，剩下标签和按钮显示**同样六个字**，没有解释。
- `.task-spec-actions{grid-template-columns:1fr 1fr}` 在只剩一个按钮时留半边空白。

#### 改动

`app.js` 的 `loadRuntime`（第 114–119 行）和 `refreshSelected` 里那两处设置 pill 文案的地方，同时设置 `title` 和 `aria-label`：

```js
  const pillText = state.runtimeReady ? "Agent Runtime 已连接" : "Agent 未连接 · 任务操作仍可用";
  ui.runtimePill.querySelector("span").textContent = pillText;
  ui.runtimePill.title = pillText;
  ui.runtimePill.setAttribute("aria-label", pillText);
```

（第 174 行和第 177 行两处也要同样处理。）

`styles.css` 第 66 行：删掉 `.next-action-copy p{display:none}`，改为限制行数而不是隐藏：

```css
  .next-action-copy p{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
```

第 73 行 `.task-spec-actions{display:grid;grid-template-columns:1fr 1fr}` 改为
`.task-spec-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(0,1fr))}`。

#### T9 验收门

```js
// /tmp/mh-verify/verify-mobile.mjs
import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await page.goto(`http://127.0.0.1:8799/app?task=${encodeURIComponent(process.env.TASK_ID)}`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const out = await page.evaluate(() => {
  const pill = document.getElementById("runtimePill");
  const desc = document.getElementById("nextActionDescription");
  return {
    pillAccessible: Boolean(pill?.getAttribute("aria-label") || pill?.title),
    descVisible: desc ? getComputedStyle(desc).display !== "none" : false,
  };
});
const fail = [];
if (!out.pillAccessible) fail.push("runtime pill 在移动端没有可访问名称");
if (!out.descVisible) fail.push("next-action 说明在移动端被隐藏");
console.log(out);
console.log(fail.length ? "FAIL:\n" + fail.join("\n") : "PASS");
await browser.close();
process.exit(fail.length ? 1 : 0);
```

---

## Round 3：后端审计链（风险最高，最后做）

**这一轮开始前必须先跑通 Round 1 和 Round 2 的全部验收门。**

---

### T10 · 人工确认必须绑定合同内容

**问题**（最严重的后端缺陷）：`confirm_contract`（`workspace.py` 第 989–1008 行）只读一遍合同、跑一次 schema 校验，然后写一个布尔值。我 grep 过整个仓库：`contract_snapshot_sha256` 只在 `runner.py:79` 的**打包阶段**计算，也就是训练结束之后。确认那一刻不留任何 digest。所以 `start_run`（第 1017 行）重新从磁盘读合同时，无法证明它读到的就是人确认过的那份。审计记录只能说明"某人在某时点了确认"，不能说明"确认的是这份门槛、这份数据"。这与 AGENTS.md 里"更换数据或修改门槛必须使先前确认失效"对不上。

#### 行为契约（先写测试）

新增 `tests/test_confirmation_binding.py`，必须包含：

1. 正常路径：导入数据 → 确认 → `start_run` 成功，且 `task.json` 里有非空 `confirmed_contract_sha256`。
2. 篡改路径：确认之后，**直接在磁盘上**改写 `task_contract.json`（例如把 `release_gates.clean_test_accuracy_min` 从 0.5 改成 0.0），然后调 `start_run` → 必须抛错，且错误信息包含"重新确认"。
3. 篡改后 `task.json` 的 `contract_confirmed` 被重置为 `False`、`confirmations` 被清空、`status` 回到 `data_ready`。
4. 重新确认之后 `start_run` 又能成功，且新 digest 与新合同一致。
5. `update_contract` 走正常 API 修改门槛后，`confirmed_contract_sha256` 被清空（不是留着旧值）。
6. `attach_dataset` 重新导入数据后，`confirmed_contract_sha256` 被清空。

#### 参考实现（可调整，但必须满足上面 6 条）

`workspace.py` 第 22 行的 import 加上 `sha256_file`：

```python
from .io_utils import read_json, sha256_file, write_json
```

`confirm_contract` 里 `task["contract_confirmed"] = True` 之后加一行：

```python
            task["confirmed_contract_sha256"] = sha256_file(self._contract_path(task_id))
```

`start_run` 里把
```python
            if not task.get("contract_confirmed"):
                raise HarnessError("必须先确认数据授权、标签和验收门槛")
            contract = read_json(self._contract_path(task_id))
```
替换为
```python
            if not task.get("contract_confirmed"):
                raise HarnessError("必须先确认数据授权、标签和验收门槛")
            contract_path = self._contract_path(task_id)
            confirmed_digest = task.get("confirmed_contract_sha256")
            if not confirmed_digest or confirmed_digest != sha256_file(contract_path):
                task["contract_confirmed"] = False
                task["confirmations"] = {}
                task["confirmed_contract_sha256"] = None
                task["status"] = "data_ready"
                task["updated_at_utc"] = _utc_now()
                write_json(self._task_path(task_id), task)
                raise HarnessError(
                    "训练合同在确认之后被修改，必须重新确认数据授权、标签和验收门槛"
                )
            contract = read_json(contract_path)
```

`update_contract`（第 978 行附近）和 `attach_dataset`（第 945 行附近）里，凡是已经写 `task["contract_confirmed"] = False` 的地方，同一处补 `task["confirmed_contract_sha256"] = None`。

#### T10 验收门

```bash
.venv/bin/python -m unittest tests.test_confirmation_binding -v
#   期望 6 个测试全过
.venv/bin/python -m unittest discover -s tests
#   期望测试数 = 前一轮 + 6，全部 OK
```

**禁止**：不要改 `runner.py` 里已有的 `contract_snapshot_sha256`。那是运行期证据，和确认期 digest 是两件事，都要保留。

---

### T11 · 训练入口重新校验数据完整性

**问题**：数据指纹只在导入时对比一次（`tabular_regression_plugin.py:113`），训练时三个 recipe 都直接读磁盘活文件——`tabular_regression.py:47`、`image_folder_classification.py:266`、`audio_keyword.py:609`。图片和音频的 manifest 给每个样本存了 sha256，但训练时不比对。结果是数据在导入后被改动，指纹字段和报告仍然一致，证据链照样声称"用的是体检过的那份数据"。同理 `max_images` / `max_rows` 这类算力上限也只在导入时校验。

#### 行为契约（先写测试，这是本任务的真正规格）

新增 `tests/test_dataset_integrity_at_train.py`，对**三个 recipe 各一条**：

1. 表格：导入 CSV → 确认 → 在磁盘上往 `dataset.csv` 追加一行 → `start_run` → 运行必须以 `failed` 结束，且 `run_state.json` 的 error 包含数据完整性字样。
2. 图片：导入 ZIP → 确认 → 覆写 manifest 里某一张图片的字节 → `start_run` → 同上。
3. 音频：同样模式。
4. 反向断言：**不改动任何文件**时三个 recipe 都能正常 `completed`（防止实现过严把正常路径也挡了）。

#### 实现提示

三个 recipe 的指纹算法不同，实现时必须照抄各自的导入逻辑，不要自己发明：

- **表格**：`data_adapters.py:231` 是 `hashlib.sha256(normalized_csv.read_bytes()).hexdigest()`，所以训练前 `sha256_file(csv_path)` 与 `dataset["fingerprint_sha256"]` 比较即可。
- **图片**：`workspace.py:218` 是
  `sha256("\n".join(f"{label}:{sha256}" for sample in sorted(samples, key=relative_path)))`。
  最省事且等价的做法：遍历 `dataset_manifest.json` 的 `samples`，逐个 `sha256_file` 与 manifest 里记录的 `sha256` 比对；全部一致即等价于聚合指纹一致。
- **音频**：先读 `audio_keyword.py:368` 附近确认它的聚合公式，再用同样的"逐样本比对"策略。

建议把公共部分放成一个函数，位置由你决定，但**不要新建模块文件**。

#### T11 验收门

```bash
.venv/bin/python -m unittest tests.test_dataset_integrity_at_train -v
#   期望 4 个测试全过（3 个篡改被拦 + 1 个正常路径不受影响）
.venv/bin/python -m unittest discover -s tests
```

另外必须确认没把训练拖慢太多：

```bash
time .venv/bin/python -m unittest tests.test_workspace_loop
#   基线约 1-2 秒；改后不应超过基线的 3 倍
```

---

### T12 · 表格 `failure_count` 是个常数

**问题**：回归没有"预测错/对"的阈值，`tabular_regression.py` 第 219–222 行把误差降序排序后取前 N 个，然后第 251 行 `"failure_count": len(failures)`。这个值**永远等于 `min(24, 测试集大小)`**，不管模型好坏。对比图片 recipe 用的是真实错分数量（`image_folder_classification.py:428`）。更糟的是这个常数被当作优化证据喂给策略推荐（`tabular_regression_plugin.py:206`），还直接显示在前端失败样本计数上（`app.js:414`）。

#### 改动 — `model_harness/recipes/tabular_regression.py`

`evaluate` 函数里，把第 251 行
```python
        "failure_count": len(failures),
```
替换为
```python
        "failure_count": int(
            np.sum(errors > float(contract["release_gates"]["clean_test_mae_max"]))
        ),
        "failure_sample_count": len(failures),
```

即：**回归的"失败"定义为单行绝对误差超过合同里 MAE 上限**（这个门槛已经存在于 `release_gates`，见 `_gate_checks` 第 258 行），而导出的诊断样本条数单独记为 `failure_sample_count`。

#### 行为契约

新增测试（可加进已有的 `tests/test_tabular_loop.py`，这是本方案唯一允许改已有测试文件的地方，且只允许**追加**新测试方法）：

1. 构造一个测试集 > 24 行、且明显欠拟合的数据，断言 `failure_count != 24` 且 `failure_count` 随模型变差而变大。
2. 断言 `failure_count <= split_counts.test`。
3. 断言 `failure_sample_count == min(24, test_size)`。

#### T12 验收门

```bash
rg -n 'failure_count' model_harness/recipes/tabular_regression.py
#   期望：failure_count 用 np.sum(...) 计算，且存在独立的 failure_sample_count

.venv/bin/python -m unittest tests.test_tabular_loop -v
.venv/bin/python -m unittest discover -s tests
```

---

### T13 · `minimum_test_samples` 加校验

**问题**：`diagnostics.minimum_test_samples` 在 `contracts.py` 里**完全没有校验**（`validate_contract` 第 46–85 行不检查 `diagnostics`）。`runner.py:306` 读它、只在非正整数时回落到 20。填 1 就能让"证据充分"通过，从而让一个只有 1 条测试样本的运行变成 `release_ready`。

#### 改动 — `model_harness/contracts.py`

在 `validate_contract` 的 `plugin.validate_contract(data)` 之前插入：

```python
    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise ContractError("diagnostics must be an object")
    if "minimum_test_samples" in diagnostics:
        value = diagnostics["minimum_test_samples"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 20:
            raise ContractError(
                "diagnostics.minimum_test_samples must be an integer >= 20"
            )
```

**下限 20 是人工决定的策略，不要改成别的数，也不要做成可配置。**

#### 行为契约

新增 `tests/test_diagnostics_gate.py`：
1. `minimum_test_samples = 1` → `validate_contract` 抛 `ContractError`。
2. `= 19` → 抛错。`= 20` → 通过。`= 50` → 通过。
3. `= True` → 抛错（bool 不算 int）。
4. 字段缺失 → 通过（保持向后兼容）。
5. 三个内置 recipe 的模板合同都能通过校验（防止改动把默认模板打挂）。

#### T13 验收门

```bash
.venv/bin/python -m unittest tests.test_diagnostics_gate -v
.venv/bin/python -m unittest discover -s tests
```

---

## 明确不做（需要人工决策，不要交给 AI 代理）

以下几项审计有发现，但**不在本方案内**，代理不得自行处理：

1. **entry-point 插件任意代码执行**（`plugins.py:41`、`data_adapters.py:313`）。`entry_point.load()` 会在服务启动时导入并执行任何注册了 `ai_pm_model_harness.recipes` 的第三方包，没有签名/白名单/沙箱。这和 AGENTS.md 里"禁止任意生成 Python Recipe"直接冲突。要砍掉 `discover()` 还是明确承认这个入口存在，是产品决定。
2. **`joblib.load` 反序列化**训练产物（`audio_keyword.py:827` 等）等价于 pickle，篡改产物目录可导致 RCE。是否换格式需要单独评估。
3. **`release_gates` 可被调低后重新确认**。校验只检查 `0 <= 值 <= 1`，允许改成 0。是否设门槛下限是人工策略。
4. **`approval_confirmed` 只在 HTTP 层强制**（`server.py:662`），`service.apply_strategy` 本身不检查，`chat.py:56` 匹配到"批准"二字就直接调。要不要把批准语义下沉到 service 层，涉及对话层设计。
5. **README / CURRENT_WORK.md 的数字表述**。当前写"39/39、133/133"，实测是 140 个测试（文档说 133，有漂移）、7.1 秒跑完、CI 只跑 Python 单测 + Node adapter，`verify_v07_beta.py` 和浏览器/HF/冷克隆全不在 CI 里。改成诚实表述是文档决定，不是代码改动。

---

## 附录 A：造一个"证据不足"的测试任务

Round 1 的多个验收门需要一个真实完成、但 `release_ready=false` 的运行。存为 `/tmp/mh-verify/make-task.py`：

```python
"""造一个真实完成但证据不足的图片分类任务，用于前端验收。"""
import io, json, struct, sys, time, urllib.parse, urllib.request, zipfile, zlib

BASE = "http://127.0.0.1:8799"

def call(path, method="GET", body=None, headers=None, raw=False):
    data, hdrs = None, dict(headers or {})
    if body is not None:
        data = body if raw else json.dumps(body).encode()
        if not raw:
            hdrs["content-type"] = "application/json"
    req = urllib.request.Request(
        f"{BASE}{urllib.parse.quote(path, safe='/?&=')}", data=data, method=method, headers=hdrs
    )
    with urllib.request.urlopen(req) as r:
        payload = r.read()
    return json.loads(payload) if payload else {}

def png(color, size=16):
    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))
    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for label, base in {"合格": (40, 170, 90), "缺陷": (200, 60, 60), "待检": (60, 90, 200)}.items():
        for i in range(14):                      # 42 张 → 测试集 9 条 < 20，必然证据不足
            z.writestr(f"{label}/{label}-{i:02d}.png", png(tuple(min(255, c + i * 3) for c in base)))

name = sys.argv[1] if len(sys.argv) > 1 else "外观质检分类"
task = call("/tasks", "POST", {"name": name, "business_goal": "我想用产线拍摄的图片训练一个外观缺陷分类模型。"})["task"]
tid = task["task_id"]
call(f"/tasks/{tid}/spec", "PATCH", {
    "base_revision": task["current_spec_revision"], "selected_family": "image_classification",
    "business_goal": task["business_goal"], "confirm": True, "user_note": "ui verify",
})
call(f"/tasks/{tid}/dataset", "POST", buf.getvalue(),
     {"content-type": "application/zip", "x-filename": "quality.zip"}, raw=True)
call(f"/tasks/{tid}/confirm", "POST",
     {"data_authorized": True, "labels_reviewed": True, "gates_reviewed": True})
call(f"/tasks/{tid}/runs", "POST")
for _ in range(120):
    time.sleep(1)
    r = (call(f"/tasks/{tid}")["task"].get("current_result") or {})
    if r.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
        print("run:", r.get("run_id"), r.get("status"), "gates:", r.get("offline_gates_passed"))
        break
print("TASK_ID=" + tid)
```

```bash
cd /Users/wanghui2100/Documents/Projects/ai-pm-model-harness
.venv/bin/python /tmp/mh-verify/make-task.py
# 预期：run ... completed gates: True   （门槛通过但 release_ready=false，正是我们要的对照）
```

**验收结束后务必清理**，不要把测试任务留在工作区：

```bash
rm -rf "runs/_workspace/tasks/<TASK_ID>" "runs/<RUN_ID>"
```

---

## 附录 B：改前基线（用于对照，不要修改这些数字）

我在 commit `395bd6b` 上实测得到的基线，代理汇报时应能复现同样的"改前"结果：

| 项目 | 改前实测值 |
|---|---|
| Python 单测 | Ran 140 tests / OK / 7.1 秒 |
| 前端控制台错误 | 0（desktop 1440×900 与 mobile 390×844 均为 0） |
| 横向溢出 | 无 |
| inspector 面板 7px 文字元素 | 21 个 |
| inspector 面板 8px 文字元素 | 9 个 |
| 交互目标 < 44px | 20 个（最小 `#taskBlockerActionButton` 为 72×11px） |
| 一次真实运行的六维结论 | `metric_gate_status=passed` / `evidence_status=insufficient_evidence` / `conclusion=insufficient_evidence` / `release_ready=False` / 测试样本 9 vs 最低 20 |
| 头条徽章显示 | "门槛通过"（绿），与 `conclusion` 不一致 |
| 顶部步进条 vs 右侧阶段列表 | 5/5 全绿"完成" vs 第 5 步"当前"，矛盾 |
