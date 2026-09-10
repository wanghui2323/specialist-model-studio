# Specialist Model Studio · 产品与发布收口方案

## 结论

对外只发布一个产品：`Specialist Model Studio`。

`Model Harness` 不再作为第二个产品、第二套界面或第二个用户入口出现；它是 Studio 内部负责训练对象、数据合同、运行、评测、制品和证据的核心引擎。DeepSeek Harness 是内部智能体运行时适配层，SciAgent Research 是同一 `TrainingTask` 下的可选研究插件。

```text
Specialist Model Studio
├── 对话与人工确认
├── 任务工作区：数据、训练、评测、结果
├── 训练团队：协调器与按需专家
├── Model Harness：内部训练与证据引擎
├── DeepSeek Harness Adapter：内部智能体运行时
└── SciAgent Research：可选研究插件（尚未作为当前能力发布）
```

用户只访问 `/app`，也只需要理解“任务、训练方案、数据、运行、评测、结果”。`Recipe`、`Data Adapter`、provider、projector revision 和工具调用标识只出现在技术详情或开发者文档中。

## 产品边界

| 层级 | 对外名称 | 职责 | 是否独立发布 |
| --- | --- | --- | --- |
| 产品 | Specialist Model Studio | 完整用户体验、任务生命周期和发布品牌 | 是，唯一入口 |
| 训练内核 | Model Harness | TrainingTask、合同、Run、评测、制品、证据 | 否，随产品交付 |
| 智能体运行时 | DeepSeek Harness Adapter | 大模型调用、多智能体委派、工具编排 | 否，内部组件 |
| 研究能力 | SciAgent Research | 论文与模型来源研究 | 否，同一任务的可选插件 |

保留 `model_harness` Python 包名、`model_harness_*` 工具前缀和既有对象标识，避免破坏兼容性；这些名称不构成对外产品品牌。

## P0：首个公开候选版的发布阻断

### 1. 一条命令启动完整产品

新增唯一公开入口 `specialist-model-studio start`，完成：

1. 本机资源、端口、Python/Node、智能体运行时和模型 provider 预检；
2. 启动 Model Harness 后端与 DeepSeek Harness Adapter；
3. 校验 conversation schema、projector revision、工作区身份和 provider 可用性；
4. 只向用户输出 Studio 地址 `/app`；内部端口只进入诊断日志；
5. 任一必要组件失败时明确终止，不能让用户进入“看似可用、实际未连接”的页面。

现有 `serve` 降级为开发者命令“仅启动训练引擎 API”。

### 2. 一个可安装发行物

当前 wheel 只打包 `model_harness*`，不能被描述为完整产品。`1.0.0-rc.1` 已选择第二条路径：

- 将 Adapter、preset、launcher 和必要静态资源纳入统一发行物；
- **首个 RC 明确标为源码发行**，安装说明只保留经过 cold-clone 验证的一条路径；wheel 仅标注 backend-only，不能作为完整 Studio 发布。

内部 npm Adapter 不单独对外发布，应设置为 private。

### 3. 一个版本真值

首个完整候选版统一使用 `1.0.0-rc.1`，同步 Python 包、Adapter、API runtime、文档、验收脚本和 UI；conversation projector 统一为 `3.2`。在完成 Tag 和 GitHub Prerelease 前，状态始终写为 `unreleased_rc`。

### 4. 一个能力承诺

公开能力表只按真实执行状态分三类：

- `可直接训练`：已有注册、验证通过的训练方案与数据导入方式；
- `可扩展接入`：能够分析公开模型/仓库并生成构建计划，但必须经过构建、测试、注册后才能训练；
- `暂不支持`：缺少真实执行链，返回明确阻断和下一步，不模拟进度。

SciAgent Research 在论文对象、工具和证据链完成前标为 planned plugin。

### 5. 一个 GitHub 发布事实

本地通过、浏览器可见或存在版本号都不等于已发布。候选版必须依次完成：

1. 冻结并审查当前工作树；
2. 提交并推送审核分支；
3. 新 CI 全绿；
4. cold clone 后一条命令启动；
5. 完成真实任务与阻断任务验收；
6. 创建 Tag、GitHub Prerelease 与源码归档 checksum；在 Adapter、preset、launcher 纳入统一发行物前，不上传或宣传 backend-only wheel 为完整 Studio。

## P1：默认产品面的统一

- 默认 UI 使用“训练协调器 / 训练团队 / 训练方案 / 数据导入 / 扩展训练能力”。
- `Agent Runtime`、`Recipe`、`Data Adapter`、`Code Agent`、`MH` 只在技术详情展示。
- `small-model-harness` 保留一个版本的兼容别名，但从主 README 移除并给出弃用提示。
- 历史原型移入或标记为 `docs/history`，避免读者误认为存在第二套产品。
- 仓库首页、description、topics、截图和启动说明全部以 Specialist Model Studio 为唯一品牌。

## 发布验收场景

### 场景 A：真实表格回归训练

用户用自然语言描述房价预测任务，系统澄清连续值目标，确认数据合同，导入 CSV，人工确认训练方案，产生真实 Run、指标、制品和可追溯证据。刷新、重新进入任务后状态一致。

### 场景 B：尚未内置的语音或视觉任务

系统先澄清目标和部署约束，再检索公开模型；若当前没有可验证的训练方案，展示模型候选、资源判断和能力构建计划，并在构建/测试/注册之前停止，绝不伪造训练完成。

按产品负责人 2026-09-10 的 PC-only 范围确认，两种场景在 1280×800、1440×900、1920×1080 验证对话回合归属、唯一主状态、等待/停止语义、失败恢复和证据查看。手机不再作为本次发布门；其他证据与人工批准门不变。

## 执行 Loop

1. **Release truth**：统一版本、合同、能力矩阵与 planned 状态。
2. **One-command product**：实现完整启动、预检与故障闭环。
3. **One-brand surface**：完成 UI、CLI、README 和历史文档的品牌收口。
4. **Cold product acceptance**：全新目录安装并跑通两个验收场景。
5. **GitHub RC**：提交、CI、cold clone、Tag、Prerelease 与校验和。

只有 5 个阶段都形成独立证据，才能把它称为“可对外审核的首个完整版本”。
