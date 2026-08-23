# Model Harness v0.9 Universal BYOM 需求合同

> 版本：v0.9 L0
> 日期：2026-08-23
> 主对象：`TrainingTask`
> 已确认来源：Hugging Face、GitHub
> 决策状态：用户已确认本合同第 3 节的四项产品边界
> 交付状态：本文件创建只代表 `implemented`；必须经机器门禁成为 `verified`，再由用户对同一份证据确认后成为 `accepted`

## 1. 用户结果

Model Harness 面向不具备模型训练工程能力、但拥有业务目标和数据的 AI 产品经理与独立开发者。用户描述要训练的能力，或提供 Hugging Face / GitHub 地址；系统负责把目标模型转化成同一个可恢复的训练任务，并给出二选一的真实结果：

1. **训练路径通过**：形成不可变模型来源、可复现环境、通过资格试跑的训练方案，继续正式训练、评测和交付；
2. **有证据的阻断**：明确阻断类型、检测值、所需条件、可执行恢复建议和重试入口，不播放模拟进度，不生成模型成功产物。

“通用支持”指任意可获得且可通过代码训练的开源模型，都能进入相同的 `发现 → 分析 → 规划 → 资源检查 → 隔离构建 → 资格试跑 → 注册 → 正式训练` 协议，并得到上述两类结果之一。它不等于承诺每个仓库、每台电脑都能成功训练。

## 2. P0 用户流程

```text
业务目标 / HF URL / GitHub URL
→ 创建 TrainingTask（task_id 全程不变）
→ 搜索或确认模型来源
→ 解析为不可变 SourceSnapshot
→ 静态分析仓库、许可、框架、入口、数据和依赖
→ 生成 TrainingPlanRevision
→ 检查本机资源并给出 ResourceFitReport
→ 用户批准不可变计划与执行权限
→ OCI / 等价 OS 沙箱 Worker 构建；失败时输出证据和建议，由人工决定新 attempt
→ QualificationRun 资格试跑
→ 批准并注册 RecipeVersion
→ 回到原 task_id
→ 导入正式数据、冻结 TrainingContract
→ 正式训练、评测、推理和模型交付
```

任何步骤遇到许可不明、代码危险、运行环境缺失、资源不足、数据不兼容或资格试跑失败时，都必须创建 `BlockerEvidence`，保留原 `task_id`，并提供调整模型、参数、数据或环境后重试的入口。

## 3. 已冻结产品边界

1. **来源范围**：v0.9 的首批模型来源只有 Hugging Face 和 GitHub；本地目录、ModelScope、私有 Git 服务进入后续版本。
2. **执行安全**：静态分析可以在主服务中进行；任何来源仓库代码、安装脚本或 Agent 生成代码只能在 OCI 容器或具备等价文件、进程、网络和资源隔离的独立 Worker 中执行。普通宿主子进程不合格；无隔离运行时只能分析并返回 `blocked_environment`。
3. **资源范围**：产品负责检测本地 CPU、GPU/MPS/CUDA、内存、显存、磁盘、平台兼容性，并生成 batch、精度、LoRA、量化、梯度累积等降级方案；v0.9 不购买、分配或调度云 GPU。
4. **通用性口径**：成功产出训练模型和有证据地判定当前条件不可训练，都是 BYOM 编译流程的有效终态；只有前者可以显示“模型训练完成”。阻断不得包装成训练成功。
5. **修复责任**：构建失败时系统只产出证据和可执行建议，由人工决定修改计划、参数、数据或环境后创建新的 `BuildAttempt`。v0.9 不实现 Agent 自动补丁 Loop；Agent 可以提出新 attempt，但不得自动生成代码补丁、覆盖既有证据、降低人工门槛或扩大执行权限。
6. **加速器口径**：v0.9 在隔离边界内一律 CPU 执行。`ResourceProbe` 仍探测 MPS/CUDA/显存，但 `ResourceFitReport` 必须标记为“检测到但 v0.9 不可用”并给出原因（OCI 容器在 macOS 上无法访问 Metal）。资格试跑与正式训练的资源预算必须按 CPU 能力设定。禁止因宿主存在 GPU 而宣称可用。

## 4. 功能需求

### R1 — 模型来源与不可变快照（L1，P0）

- 提供统一 `ModelSourceProvider` 协议：`search`、`inspect`、`resolve_revision`、`snapshot_manifest`。
- HF 模型 ID、revision/tag 必须解析为不可变 commit；GitHub URL、branch/tag 必须解析为完整 commit SHA。
- 保存来源 URL、provider、owner/repository、commit、许可判断、文件清单与哈希；后续分支漂移不能改变已有快照。
- 下载前展示许可、仓库大小、需要执行的远程代码和凭据范围；未知许可或拒绝许可必须阻断执行。
- 取消、网络失败、限流、删除仓库、无效 revision 均不得留下可训练状态。

### R2 — 仓库分析与训练计划（L1–L2，P0）

- 静态分析输出框架、任务类型、训练入口、推理入口、数据 schema、依赖、基础模型、指标、产物和潜在危险动作。
- 分析结果必须引用具体文件和 commit，不允许只给自然语言猜测。
- `TrainingPlanRevision` 必须定义：入口命令、数据映射、超参数、评测、产物、环境、资源预算、网络权限和停止条件。
- 计划修改必须产生新 revision；批准只绑定该 revision 的 digest。模型快照、数据、门槛或执行权限变化后旧批准失效。

### R3 — 环境锁与本机资源适配（L2，P0）

- 采集本机 OS/架构、Python/Node、CPU、RAM、磁盘、CUDA/MPS/GPU/显存和容器/沙箱能力。
- 解析依赖并生成不可变 `EnvironmentLock`：基础镜像 digest、包版本/哈希、系统依赖、执行后端和允许网络域。
- `ResourceFitReport` 必须同时给出需求值、实测值、估算依据、结论和至少一个可行降级方案（若存在）。
- `blocked_resources`、`blocked_platform`、`blocked_environment` 时禁止创建正式 `TrainingRun`。
- 用户采用降级方案时创建新的 `TrainingPlanRevision` 和 `ResourceFitReport`，不得就地改写已批准计划。

### R4 — 隔离构建与人工修复 Loop（L3，P0）

- 构建输入是不可变 `SourceSnapshot + TrainingPlanRevision + EnvironmentLock + StagedDataAsset`。
- Worker 只能访问显式只读输入挂载和独立可写输出目录；禁止宿主 socket、任意宿主路径、未批准网络、越权凭据和无限进程。
- 每次修复产生独立 `BuildAttempt`，记录代码补丁、命令、退出码、结构化日志、耗时、资源、输出哈希和父 attempt。
- 超时、OOM、取消和进程异常必须可强制终止，主服务保持可用，任务可以从最后一个不可变 attempt 恢复。
- 构建失败必须产出 BlockerEvidence 与可执行修复建议；补丁由人工提供，每个补丁产生独立 BuildAttempt 并记录 patch_sha256、patch_origin="human" 与 parent_attempt_id。系统不得自动生成或自动应用补丁。

### R5 — 资格试跑与能力注册（L3–L4，P0）

- `QualificationRun` 使用最小隔离数据、有限步数和严格资源上限，验证数据读取、至少一个训练步、评测、保存、重新加载和单样本推理。
- 通过条件由 schema 声明，至少包括：退出码 0、指标可解析、产物存在且哈希稳定、重载推理成功、无越权事件。
- 只有 `QualificationRun=passed` 且人工批准对应 digest 后，才能注册不可变 `RecipeVersion` 和 `AdapterVersion`。
- 注册后必须恢复原 `task_id`，继续既有 Dataset、Contract、Run、Evaluation 和 Artifact 流程；不得创建第二套“模型项目”。

### R6 — Schema 驱动的训练协议与前端（L4，P0）

- Runner 与 Worker 使用版本化 JSON/NDJSON 消息协议传输阶段、日志、指标、资源、问题、审批、错误和产物，不解析装饰性终端文本作为事实源。
- Recipe 声明数据字段、上传格式、评测指标、推理表单、产物类型和可调参数；前端按 schema 渲染，不为具体模型 ID 增加条件分支。
- 所有进度事件携带 `task_id`、`run_id/attempt_id`、时间、阶段和真实来源；页面刷新与列表重入后可恢复。
- 不支持的字段或协议版本必须明确阻断，不能静默忽略。

### R7 — 正式训练、评测与交付（L4–L5，P0）

- 正式 `TrainingContract` 冻结模型快照、Recipe、Adapter、环境、数据、计划、资源策略和用户验收门槛的 digest。
- 正式训练前再次校验快照、数据、合同和环境完整性；不一致时使批准失效。
- `TrainingRun completed`、`EvaluationReport passed` 与 `ArtifactBundle delivered` 是三个独立事实。
- 模型交付包必须包含模型、来源 commit、Recipe/Adapter 版本、环境锁、合同、指标、推理样例、许可和哈希清单。

### R8 — 阻断、恢复与真值呈现（L1–L5，P0）

- 阻断至少分类为：`blocked_license`、`blocked_security`、`blocked_environment`、`blocked_platform`、`blocked_resources`、`blocked_data`、`blocked_repository`、`qualification_failed`。
- 每条阻断记录 detector、事实值、阈值/规则、日志引用、恢复动作和可否重试。
- 阻断是独立事实，不覆盖 `implemented / verified / accepted` 工程状态，也不把任务标为“训练完成”。
- 用户更换来源、模型版本、资源方案或数据后，从受影响的最早阶段重算，下游旧对象保留但标为 superseded。

## 5. L0–L5 执行与退出门槛

| Loop | 用户可见结果 | 必做实现 | `verified` 退出门槛 | `accepted` 条件 |
| --- | --- | --- | --- | --- |
| L0 合同冻结 | 清楚知道产品承诺与限制 | 本需求、对象模型、闭环矩阵、基线证据 | 文件互相引用一致；所有 P0 有 owner、对象、负例和证据要求 | 用户确认四项冻结边界与 L1–L5 范围 |
| L1 模型来源 | HF/GitHub 模型可绑定且不会漂移 | Provider、SourceSnapshot、静态 RepositoryAnalysis、许可门禁 | 两种来源固定 commit；刷新/重启后同 ID；分支漂移、未知许可、网络失败负例通过 | 用户确认来源交互与许可提示可理解 |
| L2 环境资源 | 训练前知道本机能否运行 | EnvironmentLock、ResourceProbe、ResourceFitReport、计划版本 | 真实本机报告；资源不足禁止 Run；降级产生新 revision；重启可恢复 | 用户确认阻断与降级建议可决策 |
| L3 隔离构建 | 系统能安全构建和修复训练方案 | 隔离 Worker、BuildAttempt Loop、QualificationRun、注册审批 | 越权文件/网络/进程负例被拦截；超时可强杀；主服务存活；失败重试不丢证据 | 用户确认执行权限、日志和审批体验 |
| L4 通用训练 | 新模型无需改前端即可完成正式训练 | Worker 协议、schema UI、Register→Resume、正式 Run/Evaluation/Inference | HF 与 GitHub 两条真实纵向切片通过；同 `task_id`；无模型 ID 前端分支 | 用户确认两条真实结果可信可用 |
| L5 盲测验收 | 用未参与开发的模型验证通用性 | 盲测、安全/资源负例、冷克隆、双视口 | 三个模型无 ID 硬编码；全部 P0 6/6；完整测试、重启、冷环境、1440/390 通过 | 用户对精确 commit 和证据包确认；GitHub 发布仍单独记录 |

## 6. 工程状态与产品结果不得混用

每个 Loop 维护以下状态，后端、工作台和验收文件必须分别存储：

```text
planned → implementing → implemented → verified → accepted
```

- `implemented`：代码或合同已存在，但尚未证明能工作；
- `verified`：在精确 source commit 上通过本层机器、真实运行和浏览器门禁；
- `accepted`：用户确认精确的 verified 证据；
- 后续代码变化会使受影响层的 `verified` 失效，但不删除历史证据；
- Git commit、push、PR、CI、merge、tag 和 release 是独立发布状态，不能由 `accepted` 推断。

训练任务另有产品结果：`qualified / blocked / training_failed / evaluation_failed / delivered`。这些结果不改变工程状态。例如一个资源不足任务可以正确产生 `blocked_resources`，证明该阻断流程已 verified，但绝不能显示模型已训练成功。

## 7. 非目标

- 云 GPU 购买、队列、租户计费和跨云调度；
- 生产推理部署、在线扩缩容和模型市场发布；
- 默认信任第三方仓库、`trust_remote_code`、安装脚本或 pickle/joblib 产物；
- 自动接受未知许可证或代替用户完成法律判断；
- 为每种 OCR、ASR、检测、分割、预测任务预写独立页面；
- 用模型关键词、动画、模拟日志或固定计时器宣称支持或进度。

## 8. v0.9 全局完成门槛

- 零个未解决 P0；`closure-matrix.md` 每个 P0 流程达到 6/6，不能以平均分抵消失败项；
- HF 标准仓库、GitHub 自定义训练仓库和代码冻结后选择的盲测仓库，均不依赖模型 ID 硬编码；
- 三个正向场景至少覆盖两种训练框架或两种数据形态，并产出真实资格试跑证据；可训练场景继续产出真实正式训练、评测、推理和交付包；
- 许可拒绝、资源不足、恶意路径/网络/进程、依赖失败、超时、取消、重启恢复均有机器负例；
- `.venv` 测试、Node Harness 测试、协议兼容测试、冷克隆、本机重启、1440×900 与 390×844 真浏览器通过，Console/Network/overflow 无 P0；
- 所有成功或阻断结论能追溯到 task、快照、计划、环境、attempt/run、日志与哈希；
- 只在上述门禁对精确 commit 通过后标记 `verified`；只有用户确认后标记 `accepted`。
