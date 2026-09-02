# Specialist Model Studio

**用自然语言协作完成专业模型训练的本地优先 AI 工作台。**

Specialist Model Studio 面向希望训练专业小模型、但不具备完整算法工程能力的 AI 产品经理、独立开发者和业务团队。你只需要描述目标、提供数据并确认关键决定；训练协调器会把需求澄清、开源模型研究、数据检查、训练、评测、新样本验证和交付组织在同一个可恢复的 `TrainingTask` 中。

它不是一个展示固定步骤的训练 Demo。每次真实操作都必须对应可持久化的任务对象、工具动作、人工确认或证据对象；无法训练时，系统会返回可审查的 `BlockerEvidence`，而不是生成假的进度、指标或制品。

> 当前版本：`1.0.0rc1`（API：`1.0.0-rc.1`，功能轨道：`v1.0-conversation-native`）。这是可供代码审核和本地体验的源码 RC，不代表生产就绪，也不自动代表 CI、Tag 或 GitHub Prerelease 已发布。

- 项目地址：<https://github.com/wanghui2323/specialist-model-studio>
- 本地 RC 验收：[v1.0 本地发布验收](plans/v1.0-conversation-native/LOCAL-RELEASE-ACCEPTANCE.md)
- 源码候选说明：[v1.0 源码 RC 指南](docs/v1.0-source-release-candidate.md)
- 产品边界决策：[v1.0 发布统一方案](plans/v1.0-conversation-native/PRODUCT-RELEASE-UNIFICATION.md)

| 发布项 | 当前状态 |
| --- | --- |
| Version | `1.0.0rc1` |
| Source branch | `codex/v1.0-conversation-native` |
| 本地 L0–L5 | 已通过 |
| GitHub 源码分支 | 已发布 `codex/v1.0-conversation-native` |
| GitHub L6 冷克隆 | 完整双旅程复验待执行 |
| Tag / GitHub Prerelease | 未创建 |
| 生产就绪 | 否 |

## 它如何工作

```text
用户描述目标
  → AI 通过对话澄清任务规格
  → 研究模型来源并检查许可证、资源与风险
  → 导入和体检用户数据
  → 人工确认训练合同与验收门槛
  → 专家智能体执行真实训练
  → 独立评测与失败样本分析
  → 用一条全新样本做推理验证
  → 生成带哈希和隐私边界的交付 Bundle
```

- 对话、计划、工具调用、人工确认和结果属于同一个 AI 回合，不拆成互相矛盾的技术面板。
- 根协调器负责澄清、路由和人工检查点；研究、数据、资源、训练和交付由五个真实子智能体按权限分工。
- 长执行过程默认折叠，用户先看到结论、当前状态和下一步；完整脱敏证据仍可随时展开。
- `task_id` 使用与展示名称解耦的不可读稳定 ID（新任务形如 `task-<uuid>`）；Dataset、合同、Run、评测、推理检查和 Bundle 也都有稳定身份，刷新与进程重启后可以恢复。历史名称式任务 ID 继续兼容读取。
- Run、样本推理、Bundle 构建和下载都使用一次性授权，不会因为 Agent 文字说明而越过人工确认。

## 一个产品，三层能力

| 层级 | 对外角色 | 职责 |
| --- | --- | --- |
| Specialist Model Studio | 唯一产品入口 | 对话、确认、执行状态、结果与证据体验 |
| Model Harness | 内部训练引擎 | Task、Data、Contract、Run、Evaluation、Inference 和 Artifact 生命周期 |
| DeepSeek Harness | 内部多智能体插件 | 根协调器、五个专家子会话、工具白名单和 provider 连接 |

本项目不是 DeepSeek Harness 的整体改造或前端换皮。DeepSeek Harness 只提供内部 Agent Loop、原生子智能体、工具调用和会话运行时；产品交互、领域对象、状态真值、训练与证据仍由 Specialist Model Studio / Model Harness 定义。

```text
Specialist Model Studio（对话、确认、过程、结果）
                    │ Conversation API / SSE
                    ▼
Training Orchestrator + 5 specialists
DeepSeek Harness（会话、委派、工具调度）
                    │ model_harness_* 工具白名单
                    ▼
Model Harness（Task、Data、Run、Evaluation、Bundle 真值）
```

多智能体不能绕过 Recipe、Data Adapter、机器资源、安全隔离和人工发布门。

## 当前能力边界

| 状态 | 能力 | 当前准确表述 |
| --- | --- | --- |
| v1 RC 真实端到端验收 | 表格回归 | 已验证数据检查、合同确认、训练、独立评测、新样本推理、Bundle 与下载 |
| 引擎已实现并有自动化测试 | 图片分类 | 支持图片目录 ZIP、轻量分类器、评测、推理与 Bundle；不等于本次 v1 浏览器旅程重新验收 |
| 引擎已实现并有自动化测试 | 声明式音频关键词分类 | 需由 Recipe Factory 构建、验证、批准和注册；不是 ASR、TTS 或流式唤醒词引擎 |
| 教学 | Digits 分类 | 使用 scikit-learn 内置数据完成教学闭环，不代表用户数据落地能力 |
| Analysis-only | 任意公开 Hugging Face / GitHub 训练仓库 | 可发现、固定版本、静态分析、规划和资源判断；不保证能训练 |
| 当前未支持 | OCR、ASR、TTS、检测、分割、时序预测、文本分类等 | 返回类型化阻断或能力建设请求，不创建假的 Run |

房价回归验收使用 120 行 CSV 闭环完成了 Dataset、合同、Run、评测、新样本推理、Bundle 与下载；Ridge 测试集 R² 为 `0.999405`，评测结论为 `release_ready`。无效 CSV 返回 HTTP 422 且没有创建 Dataset / Run；ASR 返回 `recipe_unavailable` 且没有伪造训练。自动化回归为 Python `587 passed`（另有 277 个 subtests）和 Node `150 passed`；1440px / 390px 浏览器验收均无横向溢出，控制台 0 错误。完整对象 ID、哈希、指标和截图见 [本地 RC 验收报告](plans/v1.0-conversation-native/LOCAL-RELEASE-ACCEPTANCE.md)。

## “通用训练”意味着什么

用户可以从 Hugging Face 或 GitHub 搜索公开模型与训练仓库，显式选择候选并固定到不可变 commit。系统随后可以执行来源快照、许可证检查、仓库静态分析、训练计划和本机资源诊断。

“通用”表示不同模型方向可以进入同一套 `discover → analyze → plan → qualify → train/evaluate or block` 协议，**不表示任意仓库一定能在当前机器训练**：

- 只有已注册、已验证并与 TaskSpec / Data Adapter 匹配的 Recipe 才能创建真实 Run；
- 没有经过验证的 OCI 或等价隔离运行时，只允许静态分析，不执行第三方安装脚本、生成 Python 或模型 remote code；
- 私有仓库需要用户显式提供凭据；没有凭据不会声称已验证；
- 本机算力、内存、磁盘、许可证或数据不满足要求时，系统必须停止并给出类型化恢复建议。

例如，当前 ASR 任务会先通过对话确认“普通话录音转文字”的目标，再生成 `recipe_unavailable` 阻断和能力建设请求；它不会冒充已经训练出语音识别模型。

## 真实训练与交付证据

训练完成不只看一个成功标签：

- `EvaluationReport` 分开记录运行完整性、指标门槛、证据充分性和最终发布结论；
- 新样本试跑会重新加载模型并执行真实特征处理与预测，同时校验输入和模型哈希；
- Artifact Bundle 只包含可交付白名单文件，并显式排除原始数据、测试引用、内部状态和绝对路径；
- 原始 Run 不会被优化覆盖；读取 held-out test 证据的优化子 Run 会标记为 `test_contaminated`，不能冒充独立发布证据；
- 未支持能力、无效数据和资源不足都有可持久化的失败关闭路径。

Recipe Factory 当前只允许可信、白名单化的声明式构建。候选和验证都有 digest，注册前必须人工批准；可下载的 Code Agent scaffold 只是待实现契约，不是可执行 Recipe 的证明。

## 快速开始：启动完整的本地 Studio

首选方式会同时预检并启动 Specialist Model Studio、真实多智能体运行时与本地工作台：

前置条件：Python `>=3.11`、[`uv`](https://docs.astral.sh/uv/)、Node.js / npm，以及可调用的 DeepSeek provider 凭据。

```bash
git clone --branch codex/v1.0-conversation-native \
  https://github.com/wanghui2323/specialist-model-studio.git
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

## 可选：训练引擎 CLI

如果你只需要操作兼容训练引擎、编写自动化脚本或复核已有 Run，可以不启动对话 Agent：

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

没有安装 `uv` 时，可以创建虚拟环境，再运行 `python -m pip install -e '.[server,test]'`。Node.js 和 DeepSeek Harness 不是后端 CLI 的启动前提，但完整的对话式 Studio 需要仓库锁定的 DSH runtime。

检查一个真实 Run：

```bash
uv run specialist-model-studio status runs/<run-id>
uv run specialist-model-studio events runs/<run-id>
uv run specialist-model-studio explain runs/<run-id>
uv run specialist-model-studio strategies runs/<run-id>
uv run specialist-model-studio verify runs/<run-id> --deep
```

`--deep` 只应对哈希已匹配、由本地可信 Run 生成的 Joblib 模型使用。不要加载来源不明的 Pickle/Joblib。

### 高级入口：只启动后端

```bash
uv run specialist-model-studio serve \
  --runs-dir runs \
  --host 127.0.0.1 \
  --port 8765
```

`serve` 只启动后端 HTTP/SSE API，保留给自动化、诊断或不需要自然语言协作的兼容场景。`/health` 的 `scope` 为 `backend` 且 `agent_required` 为 `false`；后端健康不代表真实对话 Agent 已连接。需要完整产品体验时应使用 `start`。

开发者仍可直接运行 `./scripts/start_conversation_harness.sh` 查看内部运行时地址与详细启动日志。只有这个非公开开发入口允许显式设置 `MODEL_HARNESS_ALLOW_SYSTEM_DSH=1` 退回 PATH 上的系统 CLI；默认公开 `start` 和 L6 验收都会拒绝这种未锁定 fallback。

DeepSeek Harness 对 Model Harness 后端和 CLI 是可选适配层，但对完整 conversation-native Studio 是必需的内部运行时；它不是训练核心的 fork。当前 preset 创建一个 `Training Orchestrator` 根会话和五个独立、可续跑的原生子智能体：`research_source`、`data_experiment`、`resource_safety`、`build_training`、`evaluation_delivery`。每个子智能体都有独立 DSH session、角色提示词和显式 `model_harness_*` 工具白名单；前端只呈现一个协调器对话，并把专家调用折叠为可检查的团队执行过程。所有任务状态和结果仍来自本地真实 HTTP 对象；Agent 投影会剥离本机绝对路径。当前 `research_source` 负责模型来源研究与候选整理；完整论文检索、证据抽取、引用追踪及 Universal-SciAgent 协议接入仍是规划能力。详见 [DeepSeek Harness Adapter](integrations/deepseek-harness/README.md)。

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
integrations/deepseek-harness/    内部 DSH 多智能体 profile bundle
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
