# Conversation Native 实现与验收 Loop

> 基线：`INTERACTION-DESIGN-PROPOSAL.md` 已于 2026-08-26 确认
> 主对象：`TrainingTask`
> 原则：一次只修一条真实纵向流程；测试、浏览器可见和产品验收分别记录

## Round 1：结构与状态

范围：任务栏、对话主线、按需 Workspace、顶部权威状态、七类交互形态。

退出门：

- 模糊任务先产生真实澄清问题，不直接选择 Recipe 或开始训练；
- 对话回复结束但后台 Action/Run 活跃时，任务仍显示运行；
- Workspace 只读取 task-owned ObjectRef，不以固定 tab 生成第二套状态；
- 刷新和任务列表重入后保持同一 task ID、待办和 Workspace 对象；
- 桌面 1440×900 与移动 390×844 无横向溢出、遮挡和不可操作主按钮。

## Round 2：执行与干预

范围：真实委派、Action 执行组、后台心跳、三种新消息语义、资源预检、取消级联。

退出门：

- 专家只在 lineage-verified delegation 存在时出现；
- 执行中消息明确为 `intervene_current`、`queue_after_turn` 或
  `stop_and_replace`，不静默覆盖当前请求；
- 停止对话、取消训练、取消整个任务具有不同作用域、actor 和 reason；
- 任务进入 `cancelled` 前，后台 worker 已退出或明确保持 `cancelling`；
- 资源预检覆盖 checkpoint 峰值、磁盘安全余量、可用内存和 swap。

## Round 3：评测、产物与视觉验收

范围：EvaluationReport、基线与候选差值、质量门、Artifact、发布/回滚入口、视觉收口。

退出门：

- 只有同 task/run 的真实完成评测才能生成结果卡；
- 候选退化时显示“实验完成，暂不发布”，发布保持阻断；
- EvaluationReport 首次生成时按规则打开，用户关闭后不反复抢占对话；
- 报告、Run、checkpoint 和 artifact 可沿 ObjectRef 回到真实 lineage；
- 时序模糊任务与至少一条已支持的真实训练任务完成桌面/移动浏览器验收。

## P0 闭环矩阵

| 流程 | 对象效果 | 持久化 | 同一 ID | 重入 | 状态门 | 错误/取消 | 当前分数 |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| 模糊需求 → 澄清 | 已验证 | 已验证 | 已验证 | 已验证 | 已验证 | 仅测试 | 5/6 |
| 人工确认 → 研究执行 | 已验证 | 已验证 | 已验证 | 已验证 | 已验证 | 仅测试 | 5/6 |
| 对话完成 → 后台继续 | 仅测试 | 仅测试 | 仅测试 | 未验证 | 仅测试 | 仅测试 | 0/6 |
| 执行中干预/排队/替换 | 已验证 | 已验证 | 已验证 | 未验证 | 已验证 | 仅测试 | 4/6 |
| 取消 → worker 退出 | 仅测试 | 仅测试 | 仅测试 | 未验证 | 仅测试 | 仅测试 | 0/6 |
| 评测 → 发布门 | 仅测试 | 仅测试 | 仅测试 | 仅测试 | 仅测试 | 仅测试 | 0/6 |

任何一行未达到 6/6，都不能把 v1.0 Conversation Native 标为完成。

> “人工确认 → 研究执行”已在真实浏览器中验证，但不能替代“确认训练方案 →
> 真实 TrainingRun”。当前 v1.0 仍不得标记完成。

## Round 0 浏览器基线

- 模糊任务：`训练一个时序模型-5f980064`；未联网、未下载、未训练；
- 首轮正确停在预测 / 异常 / 独立回归澄清门；
- 真实 Action：`action-d15236407220ebd318e712b3` completed，
  `action-8e034d2a6ea7d9026a4dfa38` waiting；
- task、conversation、runtime、task list API 均为 HTTP 200，Console 0 warning/error；
- P0：旧任务同屏出现 pending HumanCheckpoint 与 DSH interruption，顶部“等待选择”
  和主体“执行失败”冲突；
- P0/P1：固定五 tab Inspector 仍是技术面板，不是对象驱动 Workspace；
- P1：Action 组默认展开压过待办；推荐文案和 `data-recommended` 语义不一致；
- 移动 390×844 无横向溢出，但待办选项不在首屏，Workspace 仍过于技术化。

## 证据记录

### 2026-08-26 Conversation Native 主链路

- 桌面任务：`但还没想清楚是预测未来数值还是判断异常-最好能在-1ce8ef75`；
- 模糊需求真实经过“预测 / 异常 / 独立回归”和“直接使用 / 微调 / 比较候选”
  两个 HumanCheckpoint；
- 训练协调器真实委派 `resource_safety` 与 `research_source` 两名
  lineage-verified 专家；GitHub / Hugging Face 的 7 个候选收敛为 3 个候选；
- 刷新后仍以同一 `task_id` 重入，待办保持为候选选择；Console 无错误；
- stale `running` 团队叙述已改由 canonical work item / agent / delegation 终态覆盖，
  部分失败显示“需要处理 · 部分步骤失败”，不再伪装为持续执行；
- 后端独立测试 61/61；前端独立测试 71/71；8812 运行时报告
  `real_agent=true`、`implementation=dsh_native_subagents`；
- 尚未完成 390×844 最终移动验收；尚未在当前版本的真实浏览器中跑通
  “数据 → TrainingRun → EvaluationReport → Artifact → 发布门”；后台继续、worker
  退出和评测发布目前仍只有自动化测试证据。

每一轮完成时记录：

1. 起始 URL 与 `task_id`；
2. 触发的真实 API/Action；
3. 刷新后的状态；
4. 从任务列表重入后的状态；
5. 下游 Workspace/Run/Evaluation 的同一对象；
6. 一个失败、阻断或取消路径；
7. Console、网络、桌面与移动布局结果。
