# Specialist Model Studio

一个以对话驱动、证据闭环为核心的专业模型工作台：用户描述目标、提供必要数据并保留关键决定权，Studio 用可审查的多智能体动作、模型来源、Recipe、训练、评测和制品组织同一个 `TrainingTask`。既有 v0.7 引擎保留三条真实用户数据切片；v0.9 的 Universal BYOM 对任意公开 Hugging Face / GitHub 训练仓库提供真实的来源发现、不可变版本绑定、静态分析、计划与资源诊断。只有已注册且通过验证的 Recipe 与 Data Adapter 才能创建真实 Run；其他仓库会显式给出 `BlockerEvidence`，不会伪造训练进度。Research Agent 的论文证据链已完成架构设计，尚未作为已实现能力宣传。

> 当前候选版本是 `1.0.0rc1`（API 版本 `1.0.0-rc.1`），功能轨道是 `v1.0-conversation-native`，发布状态仍为 `unreleased_rc`。它只表示已有可供代码审核和受控本地体验的源码 RC 候选，不表示生产就绪，也不表示远程 cold clone、CI、Tag 或 GitHub Prerelease 已通过。

项目远程地址是 <https://github.com/wanghui2323/specialist-model-studio>。远程分支、CI、Tag 和 Release 状态必须在 GitHub 上分别核验，不能由仓库名称、本地分支或版本号代替。v0.9 Universal BYOM 的审核记录保留在 [v0.9 RC 审核指南](docs/v0.9-review-candidate.md)；当前审核从 [v1.0 源码 RC 指南](docs/v1.0-source-release-candidate.md) 开始，产品收口决策见 [v1.0 发布统一方案](plans/v1.0-conversation-native/PRODUCT-RELEASE-UNIFICATION.md)。

### 当前发行边界

`1.0.0rc1` 选择 **源码 RC**：完整产品必须从仓库 checkout 启动，因为真实多智能体 Adapter、preset 与安全 launcher 仍由源码树交付。当前 Python wheel 只包含 Model Harness 后端内核和 Studio 静态页面；它可以运行 `serve`，但不是完整产品发行物，也不会把缺失 Adapter 的 `start` 伪装成成功。正式 Prerelease 前必须用远程精确 commit 做 cold-clone 验收。

## 默认体验：从一句话进入同一个训练任务

默认产品入口是 Specialist Model Studio 工作台，而不是一组需要用户手工拼接的训练命令。用户先说清想得到什么模型；系统把澄清、计划、工具动作、审批、运行和证据组织在同一个可恢复的 `TrainingTask` 下。

v0.9 本地界面候选借鉴了 WorkBuddy 的任务型对话机制，而不是依赖、嵌入或复制 WorkBuddy：

- 对话先形成可确认的任务规格；信息不足时给出具体澄清选项，不猜测训练类型；
- Agent 默认推进可逆的分析步骤，只在缺数据、授权、不可变验收门、安全执行或发布决定处暂停；
- 计划阶段、工具调用和结果留在同一时间线，长工具历史可折叠，关键结论不藏在日志里；
- 工作区同步展示模型来源、数据、计划、资源、阻断和证据；刷新或重启后仍以同一个 `task_id` 恢复；
- `BlockerEvidence` 是一等结果，必须说明事实、规则和恢复动作，不用动画或固定计时器模拟进度。

“WorkBuddy 式”只描述交互设计参考。当前三视口 smoke 和真实 GitHub V3 旅程已在冻结审核候选上执行；它们证明界面与 analysis-only 路径可体验，但不代表 L1/L2 已 verified、用户已验收或版本已发布。

## 先说能做什么

v0.7 有两个内置的用户数据 Recipe、一个经声明式 Recipe Factory 动态注册的音频 Recipe，外加一个教学 Recipe：

| Recipe | 输入 | 真实输出 | 边界 |
|---|---|---|---|
| 图片分类 | `类别/图片` 目录 ZIP | 轻量多类分类器、独立评测与制品 | 不是 OCR、目标检测或分割 |
| 表格回归 | 含数值目标列的 CSV | 回归 Pipeline、MAE/RMSE/R² 与制品 | 尚未内置表格分类、时序预测 |
| 音频关键词分类（动态注册） | 按类别组织的 16 kHz 单声道 PCM WAV ZIP | 离线短音频分类器、说话人隔离评测与制品 | 默认注册表不含此能力；不是 ASR、TTS 或流式唤醒词引擎 |
| Digits 教学 | scikit-learn 内置手写数字 | 完整教学训练闭环 | 不代表用户数据落地能力 |

对于 OCR、目标检测/分割、ASR、TTS、声纹、时序、表格分类、文本分类/NLP 和其他未内置能力，系统会显式进入能力缺口或 Recipe Build Request，不会生成伪训练进度。

**“用户可以提出任务”不等于“已支持任意模型训练”。** 只有已注册、已验证且与 TaskSpec/Data Adapter 匹配的 Recipe 才能创建真实 Run。

## v0.7 的真实闭环

```text
原始目标
  → 版本化 TaskSpec（唯一输出形式）
  → Recipe / Data Adapter 匹配
  → 数据体检与授权
  → 冻结训练合同与验收门槛
  → 真实 Run（状态、事件、指标、制品）
  → EvaluationReport
  → 用户的一条全新样本试跑
  → 隐私过滤的 Artifact Bundle
```

原始 Run 不会被优化覆盖。可执行策略仍需人工批准，并创建带 `parent_run_id` 的子 Run。如果优化决策读取了 `clean_test` 或其他测试证据，子 Run 会标记 `test_contaminated` / `insufficient_evidence`，不能成为 `release_ready`。

### 评测不再只有一个红绿灯

`EvaluationReport` 分开记录 `run_status`、`integrity_status`、`metric_gate_status`、`evidence_status`、`conclusion` 和 `release_ready`。因此“质量门槛失败”不会被写成“模型制品损坏”；完整但效果不足的模型仍会被保留供审查。

### 新样本试跑与交付 Bundle

已完成 Run 可以对一个显式提供的全新样本进行真实 `load + feature extraction + predict`：

- 图片：单个 PNG/JPEG/WEBP/BMP；
- 音频：单个 16 kHz 单声道 PCM WAV；
- 表格：单行 JSON 或 CSV。

试跑会验证 Run/contract/model 哈希，不会从训练集、验证集、测试集或 Run 内部文件偷拿样本。成功与阻断都会留下不含原始内容和绝对路径的可审计记录。

Artifact Bundle 只从可交付白名单取文件，生成带 SHA-256/大小的 manifest，并明确排除原始数据、test references、内部状态和绝对路径。

## Recipe Factory 的当前边界

Recipe Factory 是可持久化的 Build → Validate → Approve → Register 链路，但 v0.7 只允许一种可执行构建：**可信、白名单化的声明式音频关键词 RecipeSpec**。

- 样例 WAV ZIP 先只读暂存和体检，不创建 Run；
- 候选声明和验证都有 digest，注册前需显式批准；
- 注册后才会激活对应 Recipe/Data Adapter 版本；
- 任何 Python/可执行生成代码构建都持久记录为 `blocked_environment`，不被执行，也不被偷偷注册。

可下载的 Code Agent scaffold 是待实现契约，不是可运行 Recipe 的证明。

## Hugging Face 集成的当前边界

v0.7 已实现：

- 通过官方 `huggingface_hub` 客户端搜索与读取模型卡；
- 要求 40 位不可变 commit，拒绝 branch/tag 漂移；
- 下载前需显式批准，只允许声明的小文件；
- 保存 resolved commit、许可信息、文件清单和 SHA-256，重启后继续验证；
- 在 CPU `onnxruntime` 上使用通过验证的 ONNX 作为**图片分类特征提取器**。

它尚不是任意 Hugging Face 模型的通用微调器，也不会执行 remote code。当前 HF 资产只接到图片分类特征链路，没有接到音频、表格、OCR、检测或文本 Recipe。

## v0.9 Universal BYOM RC 的当前边界

`v0.9-universal-byom` 在原有 Recipe 闭环之外增加了一条通用的模型来源入口：

- 使用 Hugging Face 或 GitHub 官方 HTTP API 搜索公开仓库，并把候选列表作为服务端 `search record` 保存；
- 只有用户显式选择候选后才解析 revision；branch/tag 会固定为不可变 40 位 commit，再生成可重复校验的文件 manifest；
- 显式绑定来源后，绑定、snapshot、仓库静态分析、训练计划和本机资源适配结论可被审计与重启恢复；
- 私有仓库只有在调用者显式提供凭据 fixture 时才可验证；没有凭据不会声称已验证；
- v0.9 的隔离执行策略是 CPU-only。宿主机即使探测到 MPS/CUDA，也不能被标成容器内可用加速器。
- V3/L2 只做 analysis-only 的计划与资源门禁。若预算依据仍是 `provisional`，系统不会生成 `ResourceFitReport` 或 Run，而是返回不可原地重试的 `blocked_resources`，以 `continue_to_l3_qualification` 指向 L3 后续资格验证；这不表示 V3 内可以补齐或已经训练。

这里的“通用”是指任意公开 Hugging Face/GitHub 训练仓库都可以进入 `discover → analyze → plan → resource check` 协议，并得到可训练方案或有类型的阻断证据；不等于任意仓库都一定能在当前机器完成训练。**没有经过验证的 OCI 或等价隔离运行时，只允许静态分析，绝不执行第三方源码、安装脚本或模型 remote code。** 当前 RC 还不能把“来源已绑定”写成“模型已训练”。

## CLI 与自动化入口（可选）

如果你需要直接操作兼容训练引擎、编写脚本或复核已有 Run，可使用 CLI：

```bash
uv sync --extra server --extra test

uv run specialist-model-studio --version
uv run specialist-model-studio list-recipes
uv run specialist-model-studio init \
  --recipe digit-classification \
  --output workspaces/my-first-model
uv run specialist-model-studio run \
  workspaces/my-first-model/task_contract.json
```

没有安装 `uv` 时，可以先创建虚拟环境，再运行 `python -m pip install -e '.[server,test]'`。Node.js 和 DeepSeek Harness 都不是训练后端的启动前提。

检查一个真实 Run：

```bash
uv run specialist-model-studio status runs/<run-id>
uv run specialist-model-studio events runs/<run-id>
uv run specialist-model-studio explain runs/<run-id>
uv run specialist-model-studio strategies runs/<run-id>
uv run specialist-model-studio verify runs/<run-id> --deep
```

`--deep` 只应对哈希已匹配、由本地可信 Run 生成的 Joblib 模型使用。不要加载来源不明的 Pickle/Joblib。

## 默认入口：启动完整的本地 Studio

首选方式会同时预检并启动 Specialist Model Studio、真实多智能体运行时与本地工作台：

```bash
git clone https://github.com/wanghui2323/specialist-model-studio.git
cd specialist-model-studio
uv sync --frozen --extra server --extra test
npm ci --prefix integrations/deepseek-harness --ignore-scripts
npm ci --prefix acceptance/dsh-runtime --ignore-scripts
export DEEPSEEK_API_KEY="<your-key>"
```

`DEEPSEEK_API_KEY` 只交给 DSH 的 provider/credential 层，不进入浏览器、训练合同或任务证据。也可以先用 DSH 的 Models 设置页写入其本地凭据存储。启动器会隔离会话、设置与运行状态，同时把 credentials provider 连接到凭据文件：可通过 `MODEL_HARNESS_DSH_CREDENTIALS_FILE` 显式选择；未设置时若标准用户 DSH 凭据文件存在，则直接复用该 store。连接不会复制密钥、不会输出文件路径或内容，也不会把密钥写入模型工具环境。然后启动完整产品：

```bash
uv run specialist-model-studio start \
  --runs-dir runs \
  --host 127.0.0.1 \
  --port 8765
```

- Specialist Model Studio：<http://127.0.0.1:8765/app>
- 命令只展示产品工作台地址；DeepSeek Harness 端口属于内部运行时，不作为第二个产品入口。
- DeepSeek Harness CLI 由 `acceptance/dsh-runtime/package-lock.json` 精确锁定为 `0.1.0-rc.6`；启动器只使用仓库内 `acceptance/dsh-runtime/node_modules/.bin/dsh`，不依赖机器上碰巧安装的全局版本。
- DSH 的 session、settings、preset 与运行状态默认隔离在所选运行目录的 `runs/.dsh`；凭据 store 是唯一独立连接的 provider 状态。需要多套完全隔离的验收环境时，可把 `MODEL_HARNESS_DSH_CREDENTIALS_FILE` 指向该环境自己的凭据文件，并显式设置 `MODEL_HARNESS_RUNS_DIR` 或 `DSH_HOME`。
- 启动器会校验当前 checkout、runs 工作区、Agent 合同与 DSH 连接；端口被其他实例占用或身份不一致时会拒绝复用，不会终止未知进程。
- 首个真实对话回合仍是 provider/API Key 的最终可调用性验证；仅看到端口健康不等于大模型调用成功。

当前服务没有多用户鉴权，不应直接暴露到公网。

### 高级入口：只启动后端

```bash
uv run specialist-model-studio serve \
  --runs-dir runs \
  --host 127.0.0.1 \
  --port 8765
```

`serve` 只启动后端 HTTP/SSE API，保留给自动化、诊断或不需要自然语言协作的兼容场景。`/health` 的 `scope` 为 `backend` 且 `agent_required` 为 `false`；后端健康不代表真实对话 Agent 已连接。需要完整产品体验时应使用 `start`。

开发者仍可直接运行 `./scripts/start_conversation_harness.sh` 查看内部运行时地址与详细启动日志。只有这个非公开开发入口允许显式设置 `MODEL_HARNESS_ALLOW_SYSTEM_DSH=1` 退回 PATH 上的系统 CLI；默认公开 `start` 和 L6 验收都会拒绝这种未锁定 fallback。

DeepSeek Harness 是可选适配层，不是训练核心的 fork。当前 preset 创建一个 `Training Orchestrator` 根会话和五个独立、可续跑的原生子智能体：`research_source`、`data_experiment`、`resource_safety`、`build_training`、`evaluation_delivery`。每个子智能体都有独立 DSH session、角色提示词和显式 `model_harness_*` 工具白名单；前端只呈现一个协调器对话，并把专家调用折叠为可检查的团队执行过程。所有任务状态和结果仍来自本地真实 HTTP 对象；Agent 投影会剥离本机绝对路径。详见 [DeepSeek Harness Adapter](integrations/deepseek-harness/README.md)。

同一个 `runs/` 工作区只允许一个后端写入者；第二个服务会在启动阶段因 writer lease 失败退出，避免两个 Agent/服务并发改写 `TrainingTask`。多智能体不会把未注册算法变成可训练能力：只要缺少已验证 Recipe、Data Adapter、隔离执行或机器资源，就必须返回可审查的类型化阻断，不能展示伪训练进度。

### v1.0 对话与事件合同

- 唯一产品对话入口是 `POST /tasks/{task_id}/conversation/messages`；旧 `POST /chat` 在兼容期固定返回 HTTP 410 和 canonical endpoint，不再运行关键词流程。
- 任务专属 `GET /tasks/{task_id}/conversation/stream` 使用 SSE 输出 `snapshot / delta / state / error / heartbeat`；断线后依据 cursor 对账，版本变化或 gap 会返回全量 snapshot。
- 当前合同是 conversation schema `2.0`、projector revision `3.2`、action schema `1.0`、synthesis verdict `1.0`。`3.1` 为已验证的子智能体工具动作补齐 `agent_run_id / delegation_id / parent_delegation_id`；`3.2` 进一步把人工确认绑定到其来源 AI 回合与工具调用，旧投影不会被当成新证据。
- 前端只把真实 tool call/result 配对为 Action；协调器文字说明会标记为“不作为完成证据”，失败、受控阻断和观察降级不使用成功语义。
- DSH provider 的非成功 `turn/end` 会投影为类型化失败并结束当前 Agent run，但不会改写 `TrainingTask`；已经被终止轮次遗留的 question/approval 会持久化为失效审计记录，不再显示成可反复提交的人工检查点。
- 人工问题不预选答案；用户必须显式选择后才能提交。完成的真实训练、未检查资源、需要调整计划和环境阻断是四种不同状态。

页面结构参考了用户提供的 Figma 智能体设计稿：对话为主区、真实执行过程按智能体分组、证据工作区按需展开。Figma 只影响布局和视觉 token，不定义运行状态或完成语义。详见 [Figma 参考映射](plans/v1.0-conversation-native/FIGMA-REFERENCE.md)。

## 真实验收命令

### 1. v1.0 RC 报告合同与发布门

先从当前 checkout 生成一份**全部为 `blocked`** 的报告模板。报告写入被 Git 忽略的 `runs/`，因此不会因为生成报告本身把候选源码变脏：

```bash
SMS_V10_SHA="$(git rev-parse HEAD)"
SMS_V10_REPORT="runs/acceptance/v1.0/acceptance-report.json"

uv run python scripts/verify_v10_rc.py template \
  --output "${SMS_V10_REPORT}" \
  --source-root "${PWD}" \
  --expected-source-commit "${SMS_V10_SHA}"
```

模板不是通过证明。每个改为 `passed` 的 gate 都必须引用位于报告目录下的真实证据文件，并写入该文件的 SHA-256；绝对路径、`..` 逃逸、软链接、缺失文件、摘要不匹配、`skipped`、伪造 summary、commit 不一致和 dirty 状态不一致都会失败关闭。先只校验报告结构和所有证据摘要：

```bash
uv run python scripts/verify_v10_rc.py validate \
  --report "${SMS_V10_REPORT}" \
  --source-root "${PWD}" \
  --expected-source-commit "${SMS_V10_SHA}"
```

完成 L0–L6 的真实本地、浏览器、provider 和远程 detached cold-clone 旅程后，再要求 public RC 门通过。此命令还要求报告与当前 checkout 都是同一个精确 commit，且 `source_dirty=false`：

```bash
uv run python scripts/verify_v10_rc.py validate \
  --report "${SMS_V10_REPORT}" \
  --source-root "${PWD}" \
  --expected-source-commit "${SMS_V10_SHA}" \
  --require-public-rc
```

只有精确候选已合并、Tag、GitHub Prerelease 和源码 checksum 证据也被 release gate 引用后，才可运行 `--require-github-release`。门定义见 `acceptance/v1.0-gates.json`，报告结构见 `acceptance/v1.0-report.schema.json`。

### 2. v0.9 L1 真实来源闭环（显式选择联网）

默认运行不会联网，只用于确认门禁保持关闭：

```bash
uv run python scripts/verify_v09_l1_live.py
```

只有显式设置 `MH_LIVE_ACCEPTANCE=1` 才会访问 Hugging Face/GitHub 官方 API。下面的命令把证据写入 Git 忽略的 `runs/`，并运行安全的真实不存在仓库、无效 revision 负例：

```bash
MH_LIVE_ACCEPTANCE=1 \
MH_L1_EVIDENCE_PATH=runs/acceptance/v09-l1-live.json \
uv run python scripts/verify_v09_l1_live.py --negatives
```

公共正例只读取固定仓库的元数据与小型静态文档，不下载 Hugging Face LFS 权重，也不执行来源代码。rate-limit 只验证合成 transport 契约，不主动耗尽官方额度。没有显式私库 fixture 时，证据必须写 `not_run`，不能声称私库已验证。

### 3. 官方 Hugging Face 固定 commit 场景

```bash
.venv/bin/python scripts/run_hf_real_scenario.py
```

该脚本会真实联网，使用官方 HF 客户端读取模型卡和下载默认公开模型的固定 commit，然后完成显式批准、哈希验证、CPU ONNX 特征提取、图片分类训练、深度验证、EvaluationReport、全新图片试跑、隐私 Bundle 和应用实例重建查询。它不冒充真实 PID 重启；进程级重启由 L5 独立门禁验证。报告默认写入 `runs/acceptance/hf-real/<timestamp>/report.json`，数据和下载制品不进入 Git。

可显式指定公开仓库与 40 位 commit：

```bash
.venv/bin/python scripts/run_hf_real_scenario.py \
  --repo-id pyronear/mobilenet_v3_small \
  --commit a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674
```

### 4. v0.7 L0–L5 fail-closed 验收

```bash
.venv/bin/python scripts/verify_v07_beta.py \
  --user-approval-checkpoint-id "<user-confirmed-checkpoint-id>" \
  --output runs/acceptance/manual-v07/acceptance-report.json
```

门槛契约位于 `acceptance/v0.7-gates.json`。脚本只接受 `passed` / `failed` / `blocked`，不允许用 `skipped` 伪装完成。它不接受人工填写的验收结论：每次运行都会生成新 challenge，由受控 producer 实际运行固定 HF 场景、两个浏览器视口、两个服务 PID 和冷克隆，再由聚合器重算制品哈希并实时查询对象。工作树不干净、旧证据目录、缺少联网依赖或任何原始证据不一致都会失败关闭。

如需指定受控制品位置，只能传入一个尚不存在的新目录：

```bash
.venv/bin/python scripts/verify_v07_beta.py \
  --user-approval-checkpoint-id "<user-confirmed-checkpoint-id>" \
  --controlled-evidence-dir /absolute/path/to/fresh-evidence-dir
```

GitHub commit、PR、CI、tag 和 Release 由 `gh api` 独立查询；发布链缺失不会冒充失败的本地 Beta，也不会被手写 URL 补齐。

仅检查仓库单元/集成测试：

```bash
.venv/bin/python scripts/verify_project.py
```

更完整的能力账本和发布语义见 [v0.7 Beta 能力与边界](docs/v0.7-beta-boundaries.md)。

## 项目结构

```text
model_harness/task_specs.py       TaskSpec 修订与能力决策
model_harness/plugin_api.py       Recipe 协议
model_harness/data_adapters.py    数据导入与体检协议
model_harness/recipe_factory.py   可信声明式 Recipe Factory
model_harness/model_assets.py     固定版本模型资产和哈希
model_harness/model_sources.py    HF/GitHub 通用来源合同与不可变快照
model_harness/model_source_store.py  搜索、选择、绑定和重启恢复
model_harness/repository_analysis.py 仓库静态分析合同
model_harness/training_plans.py   版本化训练计划与人工批准
model_harness/resource_feasibility.py 本机资源探测和 CPU-only 适配结论
model_harness/runner.py           真实训练执行与验证
model_harness/evidence.py         评测、推理和 Bundle 证据
model_harness/sample_inference.py 用户新样本试跑
model_harness/service.py          Run 服务与父子谱系
model_harness/workspace.py        Task/Data/Contract/Run 所有权
model_harness/server.py           本地 HTTP/SSE 适配层
model_harness/web/                对话式训练任务工作台
model_harness/recipes/            内置 Recipe
integrations/deepseek-harness/    可选 DSH profile bundle
tests/                            单元与端到端测试
runs/                             本地数据/运行/验收证据，不入 Git
```

## 安全与开源边界

- 用户数据、客户合同、个人语音、凭证和下载模型不进入仓库；
- 生产数据、成本、门槛修改、优化、注册和发布仍由人批准；
- 公开数据高分不等于真实现场、影子测试或生产验收；
- 加载未知 Joblib/Pickle、执行生成代码或远程模型代码均不在当前可信边界内；
- 第三方框架、数据集和模型权重保留各自许可，详见 `THIRD_PARTY.md`。

## 下一步（未实现）

- 在真正隔离的构建环境中验证第三方/生成 Recipe，而不是在主进程执行 Python；
- 按独立 Recipe + Data Adapter + 真实验收数据增加 OCR、检测、ASR/TTS、时序和文本能力；
- 将 HF 资产边界扩展到经单独审查的其他 Recipe；
- 补齐多用户鉴权、远程计算隔离、生产影子评测和部署。
