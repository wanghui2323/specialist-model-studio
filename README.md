# AI PM Model Harness

一个面向AI产品经理和独立开发者的小模型训练Harness：人描述目标、提供必要数据并保留关键决定权，Code Agent调用可审查的Recipe插件完成训练、评测和制品交付。

> 当前状态：`v0.2.0-alpha.1` 本地开发版。已具备插件运行时、后台任务和优化子运行，但还没有正式聊天前端，也不宣称生产就绪。

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

## v0.2 alpha已经支持

- 通用Recipe插件协议、内置插件注册表和Python entry point发现；
- 一个基于scikit-learn Digits数据的数字分类教学Recipe；
- 训练、验证、独立测试、压力测试和发布门槛检查；
- 版本化、递增序号的NDJSON事件流；
- 后台任务、取消边界、重启中断识别和可审计恢复；
- 基于诊断结果的优化建议，以及批准后执行的父子运行；
- 模型、指标、模型卡、混淆矩阵、测试参考、优化策略和学习报告；
- 可选的本地HTTP/SSE服务，为DeepSeek Harness等聊天前端提供稳定后端边界；
- 一个供Code Agent调用的 `train-small-model` Skill。

它仍未实现任意OCR、语音训练、工业检测、自动下载任意模型或云GPU调度。内置Digits只是验证Harness，不代表真实OCR效果。

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

服务提供Recipe列表、创建运行、状态、事件、SSE、取消、恢复和应用策略接口。OpenAPI页面位于 `http://127.0.0.1:8765/docs`。它当前没有鉴权，不应直接暴露到公网。

DeepSeek Harness接入方式和事件映射见 [docs/v0.2-plugin-runtime.md](docs/v0.2-plugin-runtime.md)。核心保持Python和前端无关，DeepSeek Harness将作为首个薄适配器，而不是成为训练运行时的硬依赖。

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
model_harness/server.py         可选HTTP/SSE适配层
model_harness/recipes/          内置教学Recipe
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

先把DeepSeek Harness薄适配器接到当前HTTP/SSE接口，形成第一版聊天任务界面；再增加一个使用真实图片文件夹的轻量CV Recipe，验证插件协议能否跨出教学数据集。
