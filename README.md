# AI PM Model Harness

一个面向AI产品经理和独立开发者的开源小模型训练Harness：用户描述任务并提供必要数据，Code Agent负责推进训练工程；同一条运行记录同时生成可审计制品和人能读懂的学习报告。

> 当前状态：`v0.1.0` 初始公开版。它是可运行的教学与Harness验证项目，不宣称生产就绪。

GitHub：https://github.com/wanghui2323/ai-pm-model-harness

## 它解决什么问题

不会训练模型的用户，通常不知道应该选择什么开源框架、准备什么数据、如何切分训练/验证/测试集、怎样判断模型是否真的可用。Harness把这些环节组织为一项可持续执行的Agent任务：

```text
目标与边界
→ 任务合同
→ 数据与授权检查
→ Recipe/开源模型选择
→ 受控训练
→ 独立评测与压力测试
→ 模型、指标、环境和学习报告一起交付
```

默认采用“代办模式”：Agent独立推进，只在缺少数据、需要授权、改变验收标准、执行不可信代码或准备发布时暂停。用户随时可以打开“学习视图”，理解本次运行为什么这样做。

## v0.1真正支持什么

- 一份可由人冻结、由机器验证的任务合同；
- 一个基于scikit-learn Digits数据的数字分类参考Recipe；
- 多候选模型比较、验证集选型和最终测试集评估；
- 噪声与像素位移压力测试；
- 模型卡、指标、数据指纹、环境版本和文件哈希；
- 运行状态、事件记录、学习报告和深度制品验证；
- 一个供Code Agent调用的 `train-small-model` Skill。

v0.1尚未实现任意OCR、合同识别、语音训练、工业检测、自动下载任意模型或云GPU调度。它先验证Harness的最小闭环。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .

.venv/bin/small-model-harness list-recipes
.venv/bin/small-model-harness init --recipe digit-classification --output workspaces/my-first-model
.venv/bin/small-model-harness run workspaces/my-first-model/task_contract.json
```

运行结束后，终端会返回 `run_dir`。继续执行：

```bash
.venv/bin/small-model-harness status runs/<run-id>
.venv/bin/small-model-harness explain runs/<run-id>
.venv/bin/small-model-harness verify runs/<run-id> --deep
```

`--deep` 会在校验模型哈希之后加载本次本地运行生成的Joblib模型，并检查预测是否可复现。不要对来源不明的Joblib/Pickle模型使用深度验证。

运行项目测试：

```bash
.venv/bin/python scripts/verify_project.py
```

## 交给Code Agent使用

项目内Skill位于：

```text
skills/train-small-model/SKILL.md
```

在支持Skills的Code Agent中，让Agent使用该Skill，然后描述一个任务。例如：

```text
使用 train-small-model，先带我完成内置的数字分类参考实验。
默认代办执行，但在学习报告里解释数据切分、模型选择和压力测试。
```

## 项目结构

```text
model_harness/                 Harness CLI、状态机、合同和Recipe
examples/digit-classification 第一个可复现实验合同
skills/train-small-model       Code Agent Skill及按需参考资料
tests/                         单元测试和端到端测试
runs/                          本地生成的运行制品，不进入版本控制
```

## 安全和开源边界

- 用户数据、客户合同、个人语音、凭证和下载模型不进入仓库；
- Agent不得为通过测试而降低用户冻结的门槛；
- 公开数据高分不等于真实场景或生产验收；
- 运行LLM生成代码或加载未知模型都应使用隔离环境；
- 第三方框架、数据集和模型权重保留各自许可，详见 `THIRD_PARTY.md`。

## 路线

在参考Recipe稳定后，下一步优先增加一个Apple Silicon可运行的轻量图像分类或检测Recipe，再验证相同Harness能否减少第二个任务的重复工程成本。
