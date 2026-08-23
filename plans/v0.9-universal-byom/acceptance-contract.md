# Model Harness v0.9 · Universal BYOM 机器验收合同

> 当前状态：L0 规划与合同冻结中；本文定义目标门禁，不代表对应实现已经存在或通过
> 主对象：`TrainingTask`
> 目标聚合器：`scripts/verify_v09_byom.py`（L5 实现后才可作为验收证据）
> 目标 Gate 定义：`acceptance/v0.9-gates.json`（L5 实现）
> 目标报告 Schema：`acceptance/v0.9-report.schema.json`（L5 实现）

## 1. 通用支持的可检验定义

v0.9 的通用性不是预先内置所有 OCR、ASR、CV、NLP 或预测 Recipe，而是让任意具备可获得代码、权重和训练方式的开源模型进入同一条可审计闭环：

```text
TrainingTask
  -> ModelSource（Hugging Face / GitHub）
  -> immutable SourceSnapshot
  -> RepositoryAnalysis
  -> versioned TrainingPlan
  -> EnvironmentLock + ResourceFitReport
  -> isolated BuildAttempt
  -> QualificationRun
  -> Approved RecipeVersion
  -> DatasetVersion + confirmed TaskContract
  -> TrainingRun
  -> EvaluationReport + SampleInference + ArtifactBundle
```

对每个候选模型，机器结论只能是：

- `qualified`：固定来源、依赖、资源、数据和资格试跑均通过，可以进入正式训练；
- `blocked`：因许可证、来源、平台、资源、数据或安全条件不能继续，并提供结构化阻断证据与可行建议；
- `failed`：构建或执行失败，保留失败尝试、日志、资源使用和可重试方案；
- `completed`：正式训练、评测、推理与制品闭环通过。

“支持”指候选模型能够进入上述同一流程并得到真实、可恢复的结论；不承诺所有第三方仓库一定训练成功。资源不足不能被展示为软件成功，也不能通过静默降低用户确认的质量门槛来绕过。

## 2. 证据与状态合同

- L0–L5 在实现期间只使用 `planned / implementing`；完成编码不能自动升级为验收通过。
- 机器 Gate 的运行结论只允许 `passed / failed / blocked`；`skipped` 不能满足 required gate。
- `implemented`、`verified`、`accepted` 保留为后续证据状态，但本轮 L0 合同创建不得预填这些状态。
- 任一 required gate 为 `failed` 或 `blocked`，对应层级不得退出。
- 用户确认、源码实现、自动验证、本地可用与 GitHub 发布是五个独立事实，不能互相替代。
- 所有证据绑定干净工作树与 40 位 source commit；源码、锁文件、Gate 定义或证据 producer 变化后，旧结论失效。
- `TrainingTask.task_id` 必须贯穿模型选择、构建、资格试跑、正式训练、评测、推理与交付；不得为扩展能力另建不可追溯的“模型项目”。

## 3. 双来源与不可变快照合同

Hugging Face 与 GitHub 必须实现同一 `ModelSourceProvider` 契约，但保留来源特有事实：

| 要求 | Hugging Face | GitHub |
|---|---|---|
| 用户输入 | repository/model URL 或 repo ID | repository URL |
| 不可变标识 | resolved commit SHA | resolved commit SHA |
| 快照证据 | Model Card、文件清单、逐文件 SHA-256、许可 | README/训练入口、tree、submodule/LFS 状态、逐文件 SHA-256、许可 |
| 漂移处理 | branch/tag 更新不改写旧快照 | default branch/tag 更新不改写旧快照 |
| 凭据 | Token 不进入任务、日志、报告或 Git | Token 不进入任务、日志、报告或 Git |
| 失败关闭 | 未知 revision、未知/拒绝许可、哈希不符 | 未知 commit、未知/拒绝许可、submodule/LFS 不完整、哈希不符 |

双来源 Gate 必须证明：同一来源刷新会创建新的 `SourceSnapshot`，不会原地改写已批准版本；拒绝、取消或下载失败不会创建可训练 Recipe、Run 或伪造缓存命中。

## 4. 安全执行与资源适配合同

### 4.1 不可信代码

外部仓库和 Agent 生成代码只能在独立 Worker/OCI 隔离环境中执行。没有可验证隔离运行时时，系统只能完成只读分析并返回 `blocked`，不能回退到主服务进程执行。

required 负向证据至少覆盖：

- 越界路径、`..`、绝对路径、symlink/hardlink 逃逸；
- 读取宿主私有文件、环境变量、凭据和其他任务数据；
- 未批准网络访问、依赖源和下载 URL；
- 任意 shell、子进程、fork bomb、超时、CPU/RAM/磁盘配额耗尽；
- 篡改源快照、环境锁、数据 Manifest、合同或其他 Run 制品；
- Worker 被强杀、主服务重启后仍能恢复同一 `BuildAttempt`，且不会注册半成品 Recipe。

### 4.2 本地资源

`ResourceFitReport` 必须真实检测 OS、架构、CPU、RAM、磁盘以及可用的 CUDA/MPS/其他加速能力，并与固定模型、数据规模和 `TrainingPlan` 绑定。

- 资源足够：形成可执行计划和预计资源区间；
- 资源不足但可降级：batch size、精度、LoRA/冻结层、量化或模型替代建议必须生成新 `TrainingPlanRevision`，经用户确认后生效；
- 资源不足且不可降级：在创建 `TrainingRun` 前失败关闭；
- `bool`、负数、未知设备和伪造探测值不能通过资源 Schema；
- 任何降级都不得修改人类确认的测试集政策或 release gates。

## 5. L0–L5 机器退出门

### L0 · 通用能力合同与事实基线

required：

1. 需求工作台、对象/状态机、能力边界、双来源、安全边界和发布分级可被结构化校验；
2. 当前 Python、Node、服务、注册表、浏览器和已验证训练家族全部重新取证，不继承旧数字；
3. “已内置 Recipe”“可进入通用构建流程”“已在当前机器训练成功”三类能力在 API/UI/文档中分开；
4. 本文件与 `loop-tasks.json` Schema 校验通过，且所有 L0–L5 状态仍为 `planned / implementing`；
5. 不得因规划合同存在而显示 v0.9 已实现、已验证或已发布。

### L1 · ModelSource 与仓库分析

required：

1. HF 与 GitHub Provider 均能从用户输入解析并固定到真实 40 位 commit；
2. 创建可复核的 `SourceSnapshot`、许可结论、文件/哈希 Manifest 和 `RepositoryAnalysis`；
3. branch/tag 漂移、哈希篡改、未知许可、无训练入口、私有仓库无凭据、取消和网络中断均有失败关闭证据；
4. 重启后仍由同一 `task_id` 找回相同 source/commit；刷新只创建新版本，不改写历史；
5. 不执行仓库代码也能完成 L1，任何分析器不得在主进程 import 第三方模块。

### L2 · 环境锁与资源资格

required：

1. 框架、训练入口、数据契约、依赖、模型大小和硬件需求形成版本化 `TrainingPlan`；
2. 环境解析得到哈希约束的 `EnvironmentLock`，不接受浮动 Git branch 或未批准依赖源；
3. `ResourceFitReport` 使用实时本机探测，并能区分 `fit / fit_with_revision / blocked`；
4. CPU/RAM/磁盘/GPU 不足、平台不兼容、依赖冲突、预计制品越界全部在 Run 前阻断；
5. 降级策略生成新计划版本并重新确认，不改变测试集和 release gates。

### L3 · Build → Test → Register → Resume

required：

1. Code Agent 只在隔离 Worker 中生成/修改 Recipe、Data Adapter、Evaluator、Inference 和 Exporter；
2. 每次修复产生新的不可变 `BuildAttempt`，失败日志、输入快照、环境和资源使用可复核；
3. 资格试跑使用受限小样本与预算，超时/取消/强杀不会注册 Recipe 或创建正式 Run；
4. 只有全部安全、Schema、单测和资格试跑通过的精确 `RecipeVersion` 才能原子注册；
5. 注册成功自动回到原 `task_id`，继续数据确认和正式训练；失败可恢复并保持原任务身份；
6. 恶意仓库负向矩阵全部失败关闭，主服务在 Worker 崩溃后保持可用。

### L4 · Schema 驱动的训练、评测与前端

required：

1. Runner/Worker 使用版本化 JSON/NDJSON 协议，不依赖 UI 中的模型 ID 特判；
2. Recipe 的数据要求、参数、指标、失败样本、推理表单和交付物由 Schema 驱动；
3. 新注册模型无需修改 `model_harness/web/app.js` 即可完成上传、确认、训练、评测、推理和下载；
4. 数据或合同变化使旧确认失效；训练入口复核数据哈希；Run/模型/评测/推理/Bundle 保持同一血缘；
5. 完成、质量通过、证据充分和可发布分别给出结论；无假进度、假成功或演示输出；
6. 失败、取消、重试、主服务重启和 Worker 重启后可从同一任务恢复。

### L5 · 冻结后盲测与可复现验收

required：

1. 在干净 40 位 commit 上冻结产品代码、测试、Gate 和 evidence producer；
2. 冻结前完成一个 HF 标准模型和一个 GitHub 自定义训练仓库的真实纵向闭环；
3. 冻结后才由独立、可复核的选择规则指定第三个未参与开发的盲测模型；其 repo/model ID 不得出现在产品源码、Fixture、Recipe 注册表或前两个场景分支中；
4. 三个场景均从真实来源快照进入同一任务闭环；盲测允许成功或有证据的产品级阻断，但不得用新增模型特判修复；若修改产品代码，必须重新冻结并重新选择盲测；
5. 完成恶意仓库、资源不足、许可拒绝、来源漂移、依赖冲突、下载中断、取消、Worker 强杀和制品篡改负向矩阵；
6. 1440×900 与 390×844 真浏览器完成创建、来源选择、构建、阻断/恢复、训练和交付；刷新与从任务列表重入保持同一 ID，Console、失败请求、横向溢出、遮挡和不可达主操作均为 0；
7. 使用不同 OS PID 完成主服务/Worker 停止与重启，旧端口关闭，持久对象、事件和制品仍可复核；
8. `git clone --no-local --no-hardlinks` 冷克隆，在全新源码目录、虚拟环境和 runtime 中按锁文件完成全量 Python/Node、安全负向和三个最小真实闭环；
9. 所有 P0 流程按六点闭环合同达到 6/6，且没有未解决 P0。

## 6. 盲测防作弊规则

- 盲测选择 Manifest 必须记录候选集合、过滤条件、选择时间、选择者/随机种子、repo ID、resolved commit 与 SHA-256；
- 选择发生在冻结 commit 之后，候选仓库在此前不得作为实现 Fixture 或硬编码分支；
- 验收器扫描产品源码、测试 Fixture、默认 Recipe 和场景脚本，命中盲测 repo/model ID 即失败；证据 Manifest 中的必要记录除外；
- 盲测失败时只允许修改通用 Provider、Analyzer、Planner、Worker 协议或 Schema；任何修改都会产生新冻结 commit，并使旧盲测失效；
- “人工预跑后再宣布为盲测”、复用已下载私有缓存却不复核来源、或用手写结果 JSON 均失败关闭。

## 7. 浏览器与六点闭环证据

每条 P0 旅程必须自动记录：

1. 起始路由与 `task_id`；
2. 创建或变更的权威对象及版本；
3. 页面刷新后的持久结果；
4. 从任务列表重新进入后的身份连续性；
5. 下游 Build/Run/Evaluation/Artifact 结果；
6. 至少一个错误、取消、资源阻断或权限拒绝路径；
7. Console、Network、桌面/移动截图、Trace、overflow 和主操作可达性。

单元测试、静态截图、成功 Toast 或动画不能替代上述证据。

## 8. 本地验收与 GitHub 发布分级

最终报告必须独立输出：

| 结论 | 必要条件 | 不能替代 |
|---|---|---|
| `implementation_complete` | 对应任务实现完成 | 自动验证、用户验收 |
| `local_byom_verified` | 所有本地 required gates 在当前冻结 commit 通过 | GitHub push/PR/CI/Release |
| `user_accepted` | 用户明确确认当前证据与边界 | 本地或 GitHub 技术证据 |
| `github_ci_verified` | 远程 commit 与本地冻结 commit 相同，required checks 通过 | merge/tag/release |
| `github_released` | PR/merge、精确 tag、公开 Release 与制品哈希由 GitHub API 实时验证 | 本地可用性 |

GitHub 发布链必须是 `required_for_github_release=true`、`required_for_local=false` 的独立 Gate。未认证、未 push、PR 未合并、CI 缺失、tag/Release 不存在或远程 commit 不一致时保持 `blocked/failed`，不得改写已经独立得出的本地结论。

## 9. 验收边界

- v0.9 不建设云 GPU 调度；仅负责本机资源探测、建议和正确阻断。
- 未知或不兼容的闭源服务、无训练代码的推理端点不属于 BYOM 训练成功范围，但必须得到可解释的分析结论。
- 本合同不批准主进程加载第三方 entry point，也不批准不可信 pickle/joblib 反序列化。
- 合同、测试或界面中的“任何模型”均必须使用第 1 节的流程定义，不得改写成“所有仓库必然训练成功”。
