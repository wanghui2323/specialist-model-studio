# Model Harness v0.6 执行基线

状态：已获用户批准启动。两个真实场景是最低验收样本，不是产品能力边界。

## 产品目标

Model Harness 是面向非算法用户的通用专用模型训练 Agent：用户描述任意训练目标，系统先识别能力需求，再选择已有 Recipe；如果没有匹配 Recipe，则创建可恢复的 Recipe 构建请求，交给 Code Agent 实现、测试和注册。无论 Recipe 从哪里来，数据合同、人工门禁、运行事件、评测和产物均复用同一套 Harness。

产品不承诺“核心代码内置所有模型”。它承诺的是每个场景都有一条明确且可审计的路径：

```text
用户目标
  → Capability Request
  → 匹配已有 Recipe ───────────────┐
  → 未匹配：Recipe Build Request    │
              → Code Agent          │
              → Contract Tests      │
              → 安全验证与注册 ─────┤
                                    ↓
Dataset Version → Frozen Contract → Run → Evaluation → Artifact
```

## 对象与唯一事实源

| 对象 | Canonical ID | 所有者 | 持久化位置 | 主要读取面 |
| --- | --- | --- | --- | --- |
| Training Task | `task_id` | Training Workspace | `tasks/<task_id>/task.json` | 左侧任务、对话、Context |
| Capability Request | `task_id + revision` | Training Workspace | Task 内嵌 + 历史 | 能力匹配、Recipe Builder |
| Recipe Manifest | `plugin_id + version` | Plugin Registry | 内置或 Python entry point | 能力目录、合同、运行 |
| Data Adapter | `adapter_id + version` | Adapter Registry | 内置或 Python entry point | 数据导入、体检 |
| Recipe Build Request | `recipe_request_id` | Training Workspace | `tasks/<task_id>/recipe_request.json` | Agent、Recipe Builder |
| Dataset Version | `dataset_id` | Training Task | `tasks/<task_id>/datasets/` | 数据 Context、合同 |
| Frozen Contract | `task_id + dataset_id + revision` | Training Task | `task_contract.json` | 门禁、Run |
| Run | `run_id` | Run Service | `runs/<run_id>/` | 事件、评测、产物 |
| Artifact | `run_id + name + sha256` | Run Service | Run manifest | 产物 Context、下载 |

## P0 基线问题

1. `TrainingWorkspace.attach_dataset` 直接写死 `image-folder-classification`，新增场景必须修改核心。
2. `create_task` 不保存 modality、objective、target 或资源约束，无法做能力匹配。
3. Plugin Manifest 只有描述文字，没有可机器匹配的 modality、objective、数据格式与适配器。
4. 未匹配场景没有持久化对象，只能返回“暂不支持”，无法交给 Code Agent 继续完成。
5. 前端原型展示三栏，但正式 `/app` 仍需要把计划、工具事件与 Context 全部绑定真实 Task/Run。

## 三轮闭环

### Loop 1：能力匹配与扩展边界

- 扩展 Recipe Manifest。
- 增加 Data Adapter Registry。
- Task 保存 Capability Request 和 Recipe 选择来源。
- 未匹配时生成 Recipe Build Request，而不是伪装已支持。

退出门槛：同一 `task_id` 能在匹配、未匹配、选择 Recipe、刷新重入之间保持身份连续；不匹配状态能明确恢复。

### Loop 2：第二种真实 Recipe 与通用运行链路

- 保留图片文件夹分类。
- 新增表格回归 Recipe 与 CSV Adapter。
- 两种 Recipe 使用同一合同、Run Service、事件、门禁和 Artifact 机制。

退出门槛：图片分类与表格预测各跑通一个真实公开数据集，均产生独立测试指标和可验证模型制品。

### Loop 3：正式产品前端与真实性回归

- `/app` 首屏直接进入三栏任务工作台。
- 左侧是真实 Task 列表；中间是真实生命周期事件和批准；右侧来自同一 Task/Run。
- 删除所有定时器式模拟执行。

退出门槛：创建、导入、确认、批准、训练、刷新、产物下载、拒绝不变更全部完成浏览器闭环。

## 两个最低真实验收场景

1. 手写数字图片分类：将公开真实数字图像导入图片文件夹 Recipe，验证多类别图片训练闭环。
2. 葡萄酒质量预测：导入公开理化指标 CSV，使用表格回归 Recipe 预测质量评分，验证不同数据模态、指标和模型族。

这两个场景只证明通用内核至少跨越两个训练家族。音频、OCR 检测、目标检测或时序预测在没有 Recipe 时必须进入 Recipe Build Request，不能显示成“已支持”。

## 完成标准

- 所有 P0 流程满足六点闭环：对象效果、持久化、同一 ID、重入、状态守卫、错误/取消。
- 两个真实场景均训练成功，独立测试集未用于模型选择。
- 结果包含 `run_id`、事件序列、数据指纹、指标、失败样本、模型卡、哈希和推理示例。
- 正式前端不含硬编码训练进度，刷新后从后端恢复。
- Python、适配器、浏览器桌面/移动检查全部通过后才发布。
