# AI PM Model Harness

一个面向AI产品经理和独立开发者的对话式小模型训练Harness：人描述目标、提供必要数据并保留关键决定权，训练Agent调用可审查的Recipe插件完成数据体检、训练、评测、优化和制品交付。

> 当前状态：`v0.6.0-alpha.1` 本地Alpha版。正式入口是 `Model Harness /app` 三栏工作台；DeepSeek Harness作为可选的Agent Loop、工具与审批适配层。后端保存任务、数据、合同、运行和制品事实；仍不宣称生产就绪。

GitHub：https://github.com/wanghui2323/ai-pm-model-harness

## 这一版验证什么

训练一个OCR、语音、CV或预测小模型，难点往往不只是调用某个训练框架，而是持续完成数据检查、模型选择、独立评测、失败诊断和下一轮优化。Harness把它们组织成一项可被Agent代办、又能被人审计的任务：

```text
业务目标 → 能力请求 → Recipe / Data Adapter匹配
                         ├─ 已支持 → 数据 → 合同 → 训练 → 评测 → 制品
                         └─ 未支持 → Recipe Build Request → Code Agent构建包
                                        ↓
               Model Harness三栏工作台 ← 真实事件、指标、制品、审批
                                        ↓
                         可选DeepSeek Harness Agent Loop
```

原始运行不会被优化覆盖。Harness只提出策略；可执行策略也必须获得批准，再创建带 `parent_run_id` 的子运行。

## v0.6 alpha已经支持

- 通用Recipe插件协议、内置插件注册表和Python entry point发现；
- 一个基于scikit-learn Digits数据的数字分类教学Recipe；
- 可解释的能力匹配：模态、任务目标、输出类型、数据适配器与能力标签共同决定Recipe；
- 两个真实用户数据Recipe：图片类别ZIP的多类别分类，以及带目标字段CSV的数值回归；
- 独立的Data Adapter注册表，内置 `image-folder-zip` 和 `tabular-csv`，外部包可通过entry point扩展；
- 未匹配能力会生成持久化Recipe Build Request，不创建伪运行；
- 可下载的Code Agent Recipe构建包，包含Recipe、Data Adapter、入口声明和正反测试骨架；生成代码不会自动执行；
- 持久化训练任务、数据集版本、数据体检报告、人工确认合同和运行谱系；
- ZIP路径穿越、体积、图片数量、解码、类别数量、最小样本、重复泄漏和跨标签冲突检查；
- 比较most-frequent baseline、logistic regression、线性hinge SGD和random forest，使用验证集选择后再打开测试集；
- 训练、验证、独立测试、压力测试和发布门槛检查；
- 版本化、递增序号的NDJSON事件流；
- 后台任务、取消边界、重启中断识别和可审计恢复；
- 基于诊断结果的优化建议，以及批准后执行的父子运行；
- 模型、指标、模型卡、混淆矩阵、测试参考、优化策略和学习报告；
- 本地HTTP/SSE领域服务，为对话Agent提供任务、数据、合同、运行、事件和审批事实；
- 一个响应式三栏训练工作台，统一呈现对话/计划、能力、数据、合同、真实事件、指标和制品；
- DeepSeek Harness profile bundle把通用训练闭环注册成18个模型工具；
- DeepSeek Harness原生持久会话、模型工具调用卡片和变更前审批，对话刷新后仍可回看；
- 对话入口与证据工作台使用同一 `task_id`，可从Agent打开证据，也可从工作台回到Agent；
- 一条命令同时启动本地训练后端和对话宿主；
- 一个供Code Agent调用的 `train-small-model` Skill。

“任意训练场景可进入产品流程”不等于“仓库已经内置任意算法”。当前图片分类和CSV回归可直接训练；OCR检测、目标检测、语音、时序等会先进入Recipe构建路径，只有插件实现、数据适配、依赖与许可审查、正反测试和深度验证全部通过后才可执行。尚未实现自动安装LLM生成代码、云GPU调度或生产部署。

## 两个真实验收场景

运行 `.venv/bin/python scripts/run_real_scenarios.py` 会用公开数据完成两条完整链路，并写出忽略于Git的证据报告：

- scikit-learn/UCI手写数字：1,797张真实数字样本，经图片ZIP Adapter训练；独立测试集Accuracy `0.9833`、Macro-F1 `0.9833`，10个类别门槛全部通过。
- UCI Wine Quality红酒数据：1,599行原始CSV，去重后1,359行、11个特征；独立测试集MAE `0.4683`、RMSE `0.5990`、R² `0.3971`，回归门槛全部通过。

两个场景是首轮验收下限，不是产品能力上限。结果可随依赖、平台和随机实现变化；仓库不提交下载的数据与运行产物。

## 用自己的图片跑一次真实闭环

准备一个ZIP，每个类别一个目录，每类至少5张有效图片：

```text
parts.zip
├── good/
│   ├── 001.jpg
│   └── ...
└── damaged/
    ├── 001.jpg
    └── ...
```

启动对话Harness后，在Agent中说清业务目标。它会依次：

1. 查找是否已有任务，没有才创建草稿；
2. 向你索取本地ZIP路径并调用后端体检数据；
3. 解释类别、坏图、重复和风险，与你确认验收门槛；
4. 分别取得数据授权、标签含义和离线门槛三项确认；
5. 在DSH原生审批通过后启动真实训练，并读取真实事件与结果；
6. 给出证据工作台链接；批准某条优化后创建不覆盖父运行的下一轮。

完整边界见 [v0.4真实训练闭环](docs/v0.4-real-training-loop.md)。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .

.venv/bin/small-model-harness list-recipes
.venv/bin/small-model-harness init --recipe digit-classification --output workspaces/my-first-model
.venv/bin/small-model-harness run workspaces/my-first-model/task_contract.json
```

运行结束后，终端会返回 `run_dir`：

```bash
.venv/bin/small-model-harness status runs/<run-id>
.venv/bin/small-model-harness events runs/<run-id>
.venv/bin/small-model-harness explain runs/<run-id>
.venv/bin/small-model-harness strategies runs/<run-id>
.venv/bin/small-model-harness verify runs/<run-id> --deep
```

确认某条建议后，用新运行验证它，不覆盖原运行：

```bash
.venv/bin/small-model-harness apply-strategy \
  runs/<run-id> add-shift-augmentation
```

`--deep` 只应对哈希已经匹配、由本地可信运行生成的Joblib模型使用。不要加载来源不明的Pickle/Joblib文件。

## 启动正式Harness

安装本地后端、DSH插件并只监听本机：

```bash
.venv/bin/python -m pip install -e '.[server]'
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
./scripts/start_conversation_harness.sh
```

打开 `http://127.0.0.1:8765/app` 使用正式三栏工作台。即使DeepSeek Harness没有启动，任务创建、数据导入、合同确认、人工批准启动、运行事件和制品下载仍然可用；自由对话和Agent工具编排需要 `http://127.0.0.1:3080` 的可选运行时。

如果只需要API或手动工作台，仍可单独运行 `.venv/bin/small-model-harness serve`。OpenAPI页面位于 `http://127.0.0.1:8765/docs`。当前服务没有多用户鉴权，不应直接暴露到公网。

## 接入DeepSeek Harness

DeepSeek Harness是可选的对话与审批运行时，不是训练运行时的硬依赖。本项目通过profile bundle接入，没有复制、fork或修改DeepSeek Harness源码：

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
./scripts/install_dsh_preset.sh
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

18个工具覆盖能力匹配、Data Adapter、任务、ZIP/CSV导入、Recipe构建包、合同、运行、事件与优化。项目还安装一个“模型训练模式”preset：保留训练工具、提问、任务跟踪和上下文压缩，不向模型暴露通用Shell或文件编辑工具。数据导入、构建包、合同变更、确认、启动、优化和取消经过DSH原生审批；后端继续独立校验业务前置条件。

通用产品架构见 [docs/v0.6-generic-training-harness.md](docs/v0.6-generic-training-harness.md)，对话架构见 [docs/v0.5-conversational-harness.md](docs/v0.5-conversational-harness.md)，插件开发说明见 [integrations/deepseek-harness/README.md](integrations/deepseek-harness/README.md)。

## 编写外部Recipe

外部包实现 `RecipePlugin` 协议后，通过entry point注册：

```toml
[project.entry-points."ai_pm_model_harness.recipes"]
my-recipe = "my_package.recipe:PLUGIN"
```

插件负责自己的合同验证、训练、评测、打包、优化策略和深度验证；核心负责运行目录、状态、事件、父子关系和通用哈希。详细约束见 [Recipe authoring reference](skills/train-small-model/references/recipe-authoring.md)。

## 项目结构

```text
model_harness/plugin_api.py     Recipe插件协议
model_harness/plugins.py        内置与entry point注册表
model_harness/data_adapters.py  数据导入、体检与外部Adapter注册表
model_harness/recipe_builder.py 未支持能力的Code Agent构建包
model_harness/runner.py         同步执行与通用制品验证
model_harness/service.py        后台任务、取消、恢复、优化子运行
model_harness/workspace.py      训练任务、数据集、合同与运行所有权
model_harness/chat.py           兼容适配器的确定性命令调度
model_harness/server.py         可选HTTP/SSE适配层
model_harness/web/              同一任务的训练证据工作台
model_harness/recipes/          数字教学、图片分类与CSV回归Recipe
integrations/deepseek-harness/  DeepSeek Harness工具bundle
skills/train-small-model/       Code Agent Skill
tests/                          单元与端到端测试
runs/                           本地运行制品，不进入版本控制
```

## 安全和开源边界

- 用户数据、客户合同、个人语音、凭证和下载模型不进入仓库；
- Agent不得为通过测试而降低冻结门槛或打开最终测试集调参；
- 优化建议不会自动执行，真实数据、成本、发布和许可决定仍由人批准；
- 公开数据高分不等于真实场景、影子测试或生产验收；
- 运行LLM生成代码或加载未知模型应使用隔离环境；
- 第三方框架、数据集和模型权重保留各自许可，详见 `THIRD_PARTY.md`。

## 下一步

把Recipe构建包接入隔离的自动验证环境，再增加OCR、语音或工业检测Recipe，以及Hugging Face模型发现/下载与许可审查适配器。无论使用何种对话宿主，任务状态、数据授权、验收门槛、审批和制品仍由Harness后端负责。
