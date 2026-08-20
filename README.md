# AI PM Model Harness

一个面向AI产品经理和独立开发者的小模型训练Harness：人描述目标、提供必要数据并保留关键决定权，Code Agent调用可审查的Recipe插件完成训练、评测和制品交付。

> 当前状态：`v0.4.0-alpha.1` 本地Alpha版。除了数字分类教学Recipe，现在已经支持从用户自己的图片文件夹ZIP完成数据体检、合同确认、真实训练、失败样本、制品下载和批准式优化子运行；仍不宣称生产就绪。

GitHub：https://github.com/wanghui2323/ai-pm-model-harness

## 这一版验证什么

训练一个OCR、语音、CV或预测小模型，难点往往不只是调用某个训练框架，而是持续完成数据检查、模型选择、独立评测、失败诊断和下一轮优化。Harness把它们组织成一项可被Agent代办、又能被人审计的任务：

```text
任务合同
  ↓
Recipe插件 → 训练 → 独立评测 → 优化建议 → 可验证制品
  ↑                                  ↓
插件注册表                    人批准后创建子运行
                                      ↓
                               新合同、新模型、新证据
```

原始运行不会被优化覆盖。Harness只提出策略；可执行策略也必须获得批准，再创建带 `parent_run_id` 的子运行。

## v0.4 alpha已经支持

- 通用Recipe插件协议、内置插件注册表和Python entry point发现；
- 一个基于scikit-learn Digits数据的数字分类教学Recipe；
- 一个真实用户数据纵向切片：上传 `类别/图片.jpg` 结构的ZIP，训练轻量多类别图片分类模型；
- 持久化训练任务、数据集版本、数据体检报告、人工确认合同和运行谱系；
- ZIP路径穿越、体积、图片数量、解码、类别数量、最小样本、重复泄漏和跨标签冲突检查；
- 比较most-frequent baseline、logistic regression、linear SVC和random forest，使用验证集选择后再打开测试集；
- 训练、验证、独立测试、压力测试和发布门槛检查；
- 版本化、递增序号的NDJSON事件流；
- 后台任务、取消边界、重启中断识别和可审计恢复；
- 基于诊断结果的优化建议，以及批准后执行的父子运行；
- 模型、指标、模型卡、混淆矩阵、测试参考、优化策略和学习报告；
- 可选的本地HTTP/SSE服务，为DeepSeek Harness等聊天前端提供稳定后端边界；
- 一个无需配置大模型即可使用的响应式任务工作台，支持数据导入、合同冻结、真实事件耗时、失败样本、制品和策略审批；
- 一个DeepSeek Harness profile bundle，把Recipe、运行、事件、策略、取消等能力注册成7个模型工具；
- 一个供Code Agent调用的 `train-small-model` Skill。

它仍未实现OCR检测/识别、目标检测、语音训练、预测模型、自动下载任意模型、云GPU调度或生产部署。图片分类Recipe验证的是“用户数据训练闭环”，不是完整工业视觉平台。

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

启动本地服务后打开 `/app`：

1. 创建训练任务并写清业务目标；
2. 上传ZIP，查看类别数量、坏图、重复和数据风险；
3. 保存Accuracy、Macro-F1、最差类Recall和图片尺寸；
4. 明确确认数据授权、标签含义和离线验收门槛；
5. 启动训练，查看真实时间戳、候选指标、失败样本和可下载模型；
6. 审查优化建议，批准后创建不覆盖父运行的下一轮。

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

## 启动任务服务

安装可选依赖并只监听本机：

```bash
.venv/bin/python -m pip install -e '.[server]'
.venv/bin/small-model-harness serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/app` 即可使用任务工作台。训练任务、数据体检、确认合同、运行和事件是事实源，刷新页面会使用URL中的 `task_id` 从持久化状态恢复视图。旧的确定性聊天接口仍用于兼容适配器，但不再冒充主训练体验。

服务同时提供Recipe列表、创建运行、结果、事件、SSE、取消、恢复和应用策略接口。OpenAPI页面位于 `http://127.0.0.1:8765/docs`。它当前没有鉴权，不应直接暴露到公网。

## 接入DeepSeek Harness

DeepSeek Harness是可选宿主，不是训练运行时的硬依赖。先保持Model Harness服务运行，再安装本地profile bundle：

```bash
npm --prefix integrations/deepseek-harness install --ignore-scripts
dsh plugin --profile web add "$PWD/integrations/deepseek-harness"
dsh web --host 127.0.0.1 --port 3080
```

在DSH中可以要求Agent调用 `model_harness_list_recipes`、`model_harness_start_run`、`model_harness_get_run`、`model_harness_get_events`、`model_harness_get_strategies`、`model_harness_apply_strategy` 和 `model_harness_cancel_run`。应用策略仍要求明确的 `approval_confirmed: true`。

真实数据闭环见 [docs/v0.4-real-training-loop.md](docs/v0.4-real-training-loop.md)，DSH边界见 [docs/v0.3-conversation-console.md](docs/v0.3-conversation-console.md)，插件开发说明见 [integrations/deepseek-harness/README.md](integrations/deepseek-harness/README.md)。

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
model_harness/runner.py         同步执行与通用制品验证
model_harness/service.py        后台任务、取消、恢复、优化子运行
model_harness/workspace.py      训练任务、数据集、合同与运行所有权
model_harness/chat.py           兼容适配器的确定性命令调度
model_harness/server.py         可选HTTP/SSE适配层
model_harness/web/              独立响应式训练控制台
model_harness/recipes/          数字教学与用户图片分类Recipe
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

把DSH工具扩展到训练任务和数据合同，让模型可以询问缺失信息并调度已确认任务；随后增加OCR、语音或工业检测中的一个独立Recipe。无论使用何种对话宿主，任务状态、数据授权、验收门槛、审批和制品仍由Harness后端负责。
