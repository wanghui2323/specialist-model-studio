# v1.0 Conversation Native · Figma 参考映射

参考文件：[智能体 UI](https://www.figma.com/design/Uzhw1UJXpLbcpFiwQygKJz/%E6%99%BA%E8%83%BD%E4%BD%93UI?node-id=0-1)

本文件记录可复用的交互结构与视觉 token。Figma 是布局和组件参考，不是产品事实源；所有状态、动作和完成语义仍以 `TrainingTask`、Agent event 和证据对象为准。

## 已读取节点

| Node | 名称 | 用途 |
| --- | --- | --- |
| `189:2841` | 智能体对话 / 上传文件状态 / 未超出一行 | 空白对话、任务历史、快捷入口、附件 composer、轻量右侧信息面板 |
| `206:4770` | 开始对话 / Agent 思考 | 用户消息、AI 等待态与稳定 composer 的空间关系 |
| `33:8586` | 通用智能体 / Agent 思考生成计划 | 紧凑计划、专家分工和单一确认动作 |
| `33:8873` | 通用智能体 / 执行过程 | 多智能体过程、按智能体分组的动作时间线、过程/结果切换 |
| `33:9350` | 通用智能体 / 执行结果 | 完成摘要、指标、建议与产物动作 |
| `640:5972` | 执行模块 / 输出卡片 | 结果字段层级、标签和值的密度、克制边框和圆角 |

后续实现若需要引用位图或图标，必须使用 Figma 导出的真实 asset 或项目中语义一致的既有图标；不得临摹或手写替代 SVG。Figma MCP asset URL 会过期，进入代码前应下载到项目资产目录并记录来源。

## 采用的结构

### 1. 三段式、按需展开

- 左侧约 `220px`：TrainingTask / 历史对话，只承担选择、新建和重入；
- 中央：对话与动作时间线，是默认主视觉；
- 右侧：只在用户点击 Action、ObjectRef、评测或制品时展开，不在空任务时占据固定仪表盘空间；
- 顶部约 `56–64px`：仅显示任务名称、真实能力状态和少量全局动作，删除阶段导航与重复状态摘要。

这保留了参考稿的稳定空间关系，同时服从本产品的 `closed / object-viewer / task-workspace` 三态 Inspector。

### 2. 对话起始态

- 中央使用简短标题与一行能力说明；
- 快捷项改为真实需求入口，例如“用图片训练分类模型”“用 CSV 预测数值”“先诊断一个 Hugging Face 仓库”；
- 快捷项只是生成用户可编辑的对话输入，不直接创建 Run 或伪造执行事件；
- 上传文件以 composer 内附件 chip 呈现，显示文件名、类型、大小、解析状态与移除动作；
- 解析失败必须提供“重新解析/更换文件”，不能只显示错误 toast。

### 3. 一个 AI 回合，五种可见状态

Figma 中的思考、计划、执行与结果不是四张互不相干的页面。在本产品中，它们投影为同一个 canonical `AgentTurn` 的阶段：

| 阶段 | 主对话显示 | 右侧 Workspace | 可写动作 |
| --- | --- | --- | --- |
| `thinking` | 一句当前意图或真实活动指示 | 默认关闭 | 停止当前 Agent（仅真实可取消时） |
| `planning` | 紧凑计划、必要的专家分工 | 用户主动展开完整计划 | 一个 HumanCheckpoint |
| `executing` | 当前动作与最近完成项 | 长任务可打开“过程” | 停止当前 Agent（仅真实可取消时） |
| `waiting_human` | 问题或审批卡，给出明确下一步 | 只读核对对象 | 当前 HumanCheckpoint 的回答 |
| `completed` | ResultCard：结论、最多 3 个指标、一个产物动作 | “结果”保留完整证据 | 打开或下载已验证对象 |

用户消息节点永远不承载执行时间线。Inspector 中的合同、计划和 Run 信息只读；任何会改变状态的确认都必须回到当前 AI 回合的 HumanCheckpoint。

### 4. 多智能体过程

- 参考节点 `33:8873` 的“智能体标题 + 内部时间线”结构；
- 每个区块对应一个真实 `delegation_id`，不是按角色名或时间邻近猜测；
- 区块内每一步对应配对后的 Action：工具名、简述、开始/结束时间、真实耗时、状态；
- Action 产生 ObjectRef 时提供“查看产物”，点击后打开右侧 object viewer；
- 同一 specialist 被连续委派两次时显示两个独立区块；
- control tool、提问和审批不混成训练动作。

### 5. 过程与结果

- 只有任务产生可验证结果后，右侧才出现“过程 / 证据”切换；
- “结果”不是模型散文，而是 EvaluationReport、ArtifactBundle、BlockerEvidence 或其他 canonical object；
- 纯诊断任务允许展示“诊断已完成”，同时独立显示 `training_status=unavailable_no_verified_recipe`；
- 用户可以从结果返回对应 Action、Agent 和 Run lineage。
- ResultCard 只有在 `task_id`、`run_id`、对象 ID 和 digest 全部与当前任务证据一致时才出现；旧对象或无法重新读取的对象不得使用“已就绪”兜底文案。
- 附件重试必须由后端幂等 receipt 保证同一 `request_id + payload_digest` 只产生一个数据集；未知网络结果不允许前端盲目重复提交。

## 视觉 token 映射

| 参考意图 | 项目映射 |
| --- | --- |
| 白色主背景、轻边界 | `--surface: #fff`，`--border-subtle: #ebeef5` |
| 主文字 | `--text-primary: #17191f` |
| 次文字 | `--text-secondary: #495366` |
| 元数据 | `--text-muted: #818999` |
| 对话正文与输入 | `15px / 24px` |
| 卡片小标题 | `16px / 24px` |
| 时间、ID、状态补充 | `12px / 20px` |
| 普通卡片圆角 | `8–12px`，避免层层大圆角 |
| HumanCheckpoint / ResultCard | `16px`，仅用于关键交互和完成摘要 |
| 图标 | `16–20px`；Agent identity 可使用 `24px` |
| 左侧列表行 | `36–44px`，选中态使用低饱和品牌底色 |
| Action 卡片 | `1px` 轻边框、无重阴影，详情按需展开 |

品牌色继续使用 Specialist Model Studio 已有品牌 token，不复制参考稿的红色。颜色首先服务于语义：success、warning、blocked、failed、observation degraded 必须彼此可区分。

## 明确不照搬

- 不照搬静态的“所有任务执行完成”或绿色勾号；完成必须由共享 truth classifier 和领域证据给出；
- 不把右侧面板永久展开为第二个仪表盘；
- 不把模型“思考中”当作可审计过程，只有真实未完成的 tool call / delegation 才显示运行态；
- 不展示虚构智能体头像、评分、使用人数和推荐智能体；
- 不使用固定时间戳、固定步骤数量、预设进度或演示数据；
- 不把任务管理、数据中心、智能体广场等无独立生命周期的模块复制进当前产品导航；
- 不照抄 React/Tailwind 生成代码；实现必须适配现有原生 HTML/CSS/JavaScript 结构与 token。

## L3 视觉验收

- 1440px：左侧稳定，中央对话为主；Inspector 关闭时中央空间不留空洞；
- 390px：历史列表和 Inspector 都变为可关闭 sheet，主对话无横向溢出；
- 空任务、澄清、附件解析、Agent 执行、等待人工、受控阻断、真实结果七种状态均有独立浏览器 fixture；
- 任务切换后，旧 ObjectRef 请求或旧 Agent 流不得写入新任务；
- failed 默认展开且为红色；BlockerEvidence 为琥珀色；warning 不使用成功勾；
- 任一“完成”标记都能追溯到 supporting event IDs、ObjectRef 或领域状态。
