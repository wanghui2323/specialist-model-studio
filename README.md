# Specialist Model Studio

**用自然对话推进模型任务：准备数据与实现、隔离训练、独立评估、试用和交付。**

当前候选版本为 **`v1.0.0-rc.2` 开发者源码预览版（源码 RC）**（Python `1.0.0rc2`，API/插件 `1.0.0-rc.2`）。它供代码审核、本地体验和问题反馈，**不表示生产就绪**。只有精确提交的远端 CI、冷克隆与页面验收通过并创建 Tag/Prerelease，才算公开发布；版本字符串本身不是发布证据。

- [项目与反馈](https://github.com/wanghui2323/specialist-model-studio)
- [当前版本安装与验收指南](docs/v1.0-source-release-candidate.md)
- [通用训练架构](plans/v1.0-conversation-native/ADR-002-GENERAL-TRAINING-EXECUTION.md)
- [上下文机制](plans/v1.0-conversation-native/ADR-003-CONTEXT-RUNTIME.md)
- [2026-10-06 页面、效果与重载记录](plans/v1.0-conversation-native/OVERALL-ACCEPTANCE-20261006.md)
- [rc.2 发布收尾记录](plans/v1.0-conversation-native/RC2-RELEASE-20261007.md)

## 当前可以验证什么

用户表达目标，Agent 逐步明确输入、输出、路线、数据和资源；必要时从同一对话创建可恢复的 `TrainingTask`。已有 Recipe 是可复用实现，没有现成 Recipe 时由 Agent 准备不可变代码方案，完成真实 OCI 资格验证，再通过本次批准创建 Run。模型类型不构成产品白名单。

```text
对话与材料上传 → 数据版本与方案 → 隔离资格验证
→ 确认训练范围 → 真实训练 → 独立测试
→ 全新输入试用 → 模型包下载 → 独立重载
```

- 从零训练、预训练微调和现成推理是不同路线，保留用户已明确的选择。
- 生成/第三方训练代码只在已验证的受限 OCI worker 内执行；没有隔离环境时只允许静态分析并报告实际环境缺口。
- 训练、评估、试用和交付均绑定任务、版本、摘要与实际证据；上传不代表批准执行。
- 训练/验证用于候选选择，最终测试保持独立；不能为了通过而下调门槛或重复利用已曝光测试选模。
- 运行完成、模型效果达标、公开发布是不同判断。Agent 应说明失败与下一步，不能把有声音或有预测值说成效果合格。

语音、OCR、NLP、时序与未注册的学习排序已经用于代表性真实页面验证。这些是测试样本，不是支持类型清单。排序样例通过；语音/OCR存在质量失败，NLP有否定语义反例，时序新输入存在旧历史上下文问题，详见对应验收记录。

本预览版的实测训练后端为本地 CPU OCI，实测协调模型服务为 Codex CLI。远程 GPU、其他服务等价实测、环境自主构建、总实验预算和完整检查点恢复仍在建设；不以接口存在推定已经验证。

三个内置的用户数据 Recipe（图片目录分类、表格回归、表格分类）继续提供复用路径；音频关键词分类（动态注册）仍保留其声明式验证。这些历史实现不定义通用 Agent 的能力边界。

## 安装与启动

需要 Git、Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 24 LTS/npm，以及可用的 Docker 兼容 Linux 容器服务。当前实测为 macOS + Linux ARM64 worker；原生 Windows 完整旅程尚未验证。

```bash
git clone https://github.com/wanghui2323/specialist-model-studio.git
cd specialist-model-studio
# 发布后使用固定 Tag；发布前以验收记录中的精确 candidate commit 为准。
git checkout v1.0.0-rc.2
uv sync --frozen --extra server --extra test
npm ci --prefix integrations/deepseek-harness --ignore-scripts
npm ci --prefix acceptance/dsh-runtime --ignore-scripts
```

等价的 Python 安装入口为 `uv pip install '.[server,test]'`；发布复现以 `uv.lock` 的冻结安装为准。

准备可复现 CPU 镜像（只有审阅 recipe 和哈希校验的依赖 wheel 进入断网构建上下文，不含模型权重或用户训练数据）：

```bash
uv run python scripts/prepare_cpu_worker.py --configure
```

若已有 operator 配置，脚本会保留它并拒绝默认覆盖。可以使用输出中的不可变 image ID 设置 `MODEL_HARNESS_EXECUTION_IMAGE`，或明确选择 `--replace-config`。macOS 使用 Colima 时，启动服务前先选择正确 `DOCKER_CONTEXT`，并把隔离作业目录共享给 Linux VM；见[完整指南](docs/v1.0-source-release-candidate.md)。

选择可用的协调模型服务。已有 Codex CLI ChatGPT 登录时，可使用目前已实测的路由：

```bash
codex login status
export MODEL_HARNESS_AGENT_PROVIDER=codex-cli
export MODEL_HARNESS_AGENT_MODEL=gpt-5.6-sol
uv run specialist-model-studio start
```

也可配置 DeepSeek 或其他 DSH 已安装的服务适配器；配置后须验证真实调用，不把配置存在当作已接通。DeepSeek API 路由可在本机设置 `DEEPSEEK_API_KEY`，不要把密钥发到聊天、提交到仓库或放进模型包。

`start` 输出一个 Studio `/app` 地址。普通 wheel 的 `uv run specialist-model-studio serve` 仅为 backend-only 开发入口，完整 `start` 仍要求源码 checkout 的运行时、插件和启动器；`agent_required` 为 `false` 的后台演示不能代替真实 Agent 验收。

运行时的 `source_preview_rc` 标记只描述实验源码范围，功能轨道为 `v1.0-conversation-native`；旧版 `unreleased_rc` 同样不是实时 GitHub 发布状态。

## 体验与反馈

1. 用自己的话描述希望得到的模型效果；不需要先选一个系统预设类型。
2. 通过页面上传材料，查看结构与数据问题，再确认会影响下一步的必要决定。
3. 在真实确认卡核对训练/试用/交付范围；发送消息不会代替批准。
4. 查看独立指标与限制，用未参与实验的新输入体验，保存可重载模型包。

模型包排除原始数据文件与内部运行文件；模型状态仍可能保存数据上下文，需要另外审查才能分享。默认保持实验数据、下载的权重、生成声音、凭据与 `runs/` 在版本控制外。代码许可、权重许可、数据许可分别核对。

页面刷新不应丢失任务和已完成产物；停止需要以实际进程与任务状态确认。服务重启后，已中断的执行应如实显示，不能制造“继续运行”的状态。确定性复验覆盖协议行为，它不冒充真实 PID 重启；发布验收另检查实际重启。

反馈请附版本/提交、目标、操作步骤和脱敏现象；不要发送密钥、私人声音、客户原始材料或包含它们的运行目录。

## 开发验证与发布

```bash
uv run python -m unittest discover -s tests
npm test --prefix integrations/deepseek-harness
npm run check --prefix integrations/deepseek-harness
uv run python scripts/verify_project.py
```

[当前发布门槛](acceptance/v1.0-gates.json)要求已注册基线回归和未知目标完整页面链；仅返回“未支持”的阻断不算通用能力通过。历史 rc.1 门槛保存在 `acceptance/archive/v1.0-rc.1-gates.json`，旧报告不自动覆盖新代码。

开源分发范围为源代码、小型合成数据生成器、依赖锁与验收方法。不会默认分发实际模型权重或系统合成声音；没有宣称任意模型都能训练成功。
