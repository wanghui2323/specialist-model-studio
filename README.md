# AI PM Model Harness

一个面向 AI 产品经理和独立开发者的对话式专用小模型训练 Harness：用户描述目标、提供必要数据并保留关键决定权，Harness 用可审查的 Recipe 组织数据体检、训练、评测、优化和制品交付。

> 当前代码版本是 `0.7.0b1`，对外记为 `v0.7.0-beta.1` 本地 Beta。`codex/v0.7-real-training-beta` 开发分支已推送到 GitHub；这仍不表示生产就绪、已合并 `main`、已打 Tag 或已创建 GitHub Release。

项目远程地址是 <https://github.com/wanghui2323/ai-pm-model-harness>；开发分支可在 <https://github.com/wanghui2323/ai-pm-model-harness/tree/codex/v0.7-real-training-beta> 查看。GitHub Release 仍须以远程 Tag 与 Release 页面为准。

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

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[server,test]'
npm ci --prefix integrations/deepseek-harness

.venv/bin/small-model-harness list-recipes
.venv/bin/small-model-harness init \
  --recipe digit-classification \
  --output workspaces/my-first-model
.venv/bin/small-model-harness run \
  workspaces/my-first-model/task_contract.json
```

检查一个真实 Run：

```bash
.venv/bin/small-model-harness status runs/<run-id>
.venv/bin/small-model-harness events runs/<run-id>
.venv/bin/small-model-harness explain runs/<run-id>
.venv/bin/small-model-harness strategies runs/<run-id>
.venv/bin/small-model-harness verify runs/<run-id> --deep
```

`--deep` 只应对哈希已匹配、由本地可信 Run 生成的 Joblib 模型使用。不要加载来源不明的 Pickle/Joblib。

## 启动本地 Harness

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
./scripts/start_conversation_harness.sh
```

- Model Harness 任务工作台：<http://127.0.0.1:8765/app>
- 本地 OpenAPI：<http://127.0.0.1:8765/docs>
- 可选 DeepSeek Harness 对话宿主：<http://127.0.0.1:3080>

没有启动 DeepSeek Harness 时，任务、数据、合同、Run、评测、新样本试跑和 Bundle API 仍可本地使用；自由对话和 Agent 工具编排才依赖 3080 运行时。当前服务没有多用户鉴权，不应直接暴露到公网。

DeepSeek Harness 是可选适配层，不是训练核心的 fork。当前 bundle 注册 **37 个** `model_harness_*` 工具，覆盖任务规格、数据、声明式 Recipe Factory、HF 固定资产、Run、EvaluationReport、新样本试跑和 Bundle。所有结果仍来自本地真实 HTTP 对象；Agent 投影会剥离本机绝对路径。详见 [DeepSeek Harness Adapter](integrations/deepseek-harness/README.md)。

## 真实验收命令

### 1. 官方 Hugging Face 固定 commit 场景

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

### 2. v0.7 L0–L5 fail-closed 验收

```bash
.venv/bin/python scripts/verify_v07_beta.py \
  --output runs/acceptance/manual-v07/acceptance-report.json
```

门槛契约位于 `acceptance/v0.7-gates.json`。脚本只接受 `passed` / `failed` / `blocked`，不允许用 `skipped` 伪装完成。它不接受人工填写的验收结论：每次运行都会生成新 challenge，由受控 producer 实际运行固定 HF 场景、两个浏览器视口、两个服务 PID 和冷克隆，再由聚合器重算制品哈希并实时查询对象。工作树不干净、旧证据目录、缺少联网依赖或任何原始证据不一致都会失败关闭。

如需指定受控制品位置，只能传入一个尚不存在的新目录：

```bash
.venv/bin/python scripts/verify_v07_beta.py \
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
