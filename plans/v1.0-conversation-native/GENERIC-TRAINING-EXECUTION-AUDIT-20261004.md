# 通用训练执行链审计与外部框架协议建议

核查日期：2026-10-04。范围：当前本地代码及官方文档；没有安装框架、修改中央运行代码或据此声称未知领域已训练成功。本文给出接口设计建议，新增 OCI worker 的真实隔离资格由独立验收确认。

建议保留薄 Harness 作为任务、数据版本、授权、Run 和最终结论的唯一事实源。外部框架进入受控 worker；通用 ExecutionBundle 描述工程实现。现成 Recipes 提供加速路径，新的任务语义不应要求新增核心分支。

## 当前链路与必要修改

真实训练仍应从 `TrainingWorkspace.start_run_with_authorization`（`model_harness/workspace.py:4854`）进入 `start_run:4925`、`RunService.submit`（`model_harness/service.py:72`）、`runner.prepare_run:88` 和 `execute_run:156`。先持久化规范 Run，再调 worker。OCI stage execution 是此 Run 的执行证据；准备和资格验证可以有自己的阶段记录，但不是另一种 TrainingRun。

| 层 | 当前具体依赖 | 必要变化及可复用部分 |
|---|---|---|
| Recipe / execution | `plugin_api.py:53` 只有 Python `train/evaluate/package` 等方法；`contracts.py:330`、`runner.py:99` 必须从 registry 找 Recipe | 保留受信任插件接口，提供一个通用 OCI wrapper；外部实现是冻结的 bundle 数据，不能把第三方 entry-point 直接 import 到宿主。增加运行上下文：run identity、事件输出、取消、资源预算、产物目录。领域变化只改变 bundle。 |
| Runner | `runner.py:194` 要求候选列表；`:205` 调 `train(raw)`；`:215` 写固定 accuracy/F1/MAE 指标；`:229` 要求 `selected_name`；`:260` 使用 `metrics.clean_test` | 定义通用阶段结果：候选/检查点引用、命名指标、观测范围、阶段状态。runner 维护状态机、异常和计时；worker 返回 JSON 事实，不返回待宿主反序列化的模型对象。旧插件通过兼容桥继续工作。 |
| Dataset | `data_adapters.py:52` 的完整性函数只认三种 kind；`workspace.py:3645` 导入要求 DataAdapter 与 Recipe 对应，`:3700` 在 catalog miss 中止 | Dataset 必须能由通用材料清单、字段/schema、转换程序摘要、冻结 split 清单构成。宿主校验文件/索引哈希和路径；自定义解码、转换在隔离环境执行。复用 DataImportResult、dataset id/history、导入回执与合同失效机制。 |
| Registry | `data_adapters.py:486` 和 `plugins.py:30` 本身支持扩展，但 `discover()` 会执行 Python entry-point 加载 | 可以复用 registry 的索引和接口检查；外部代码的动态执行必须留在 OCI，登记的是受信任 wrapper + 经过资格验证的 descriptor。不要给每个新任务建立宿主 Python 插件。 |
| Manifest | `runner.py:50` 收集任意相对产物，已支持递归哈希；`:73` 却记录宿主 Python/numpy/sklearn/joblib | 保留文件清单、合同哈希与父 Run；环境字段改为实际 worker 的 image digest、依赖锁、代码/入口摘要、材料/split摘要及 execution/qualification 引用。宿主环境和模型运行环境分别记录。 |
| Evaluation | `evidence.py:271` 的完整性、质量门槛、证据充分性、发布结论分离可复用；`:301` 消费 plugin 自报 gate bool；`:312` 只看 test count；`contracts.py:364` 固定至少20样本 | 通用评价声明指标名称、方向/阈值、评价单位、分组/时间约束和测试隔离政策；受信任侧依据冻结合同核算 gates。已有分类/回归默认政策保留，不能把样本单位与充分性规则套给所有新领域。报告必须说明采用的评价程序与数据摘要。 |
| 新样例 | `inference_inputs.py:22` 只有 image/audio/tabular；`sample_inference.py:36/112` 固定 recipe/type；`:269` 强制 model.joblib，`:287` 宿主 joblib.load；`evidence.py:471/549` 也绑定 joblib | 用声明式输入 schema、媒体类型、大小约束、转换与 predict 入口替换业务枚举。保留 opaque inference_input_id、task/run归属、单次授权、哈希与防测试样本复用。由同一固定 worker 载入模型并产出 PredictionEvidence；未知模型不得在宿主反序列化。 |
| Artifact | `evidence.py:33/723/835` 按全局文件名 allowlist 交付，未知权重/分片/config会被排除；`:704` 推理绑定 model.joblib 哈希；`service.py:337` 只允许平面 artifact 名称 | 以批准冻结的 artifact declaration（角色、媒体/schema、相对路径、sha、隐私分类）选择交付文件，模型身份是产物集合摘要。保留完整性、排除原数据/测试参考、原子 ZIP、下载授权及当前 EvaluationReport 校验；经 manifest 安全校验后允许嵌套分片目录。 |
| 调优与恢复 | `service.py:432` 已保留 parent→child Run；`optimization.py:59` 追踪测试证据污染；`contracts.py:351` 当前仅 recommend | 复用父子谱系和污染事实；通用策略需引用 immutable proposal、参数/代码差异、证据与预算，经过对应授权再建 child Run。模型状态恢复还需绑定环境、数据/split、代码与优化器兼容性，不能仅凭一个 checkpoint 文件名。 |

以上位置是本次审计时的行号。中央代码并发演进后应按函数名复核。

## 最小共享协议

一个 ExecutionBundle 应冻结下列信息，而不是新增某个领域的枚举：

1. task/spec/ContractRevision/Dataset/split 身份与摘要。
2. 源代码固定版本、代码包摘要、OCI image digest、依赖锁与安装/网络政策。
3. prepare/train/evaluate/predict 入口，各自的输入输出 schema 与允许挂载集合。
4. 最大训练步数/时长/内存/CPU或GPU/磁盘/重试预算、检查点和恢复契约。
5. validation 选择指标、最终测试程序和独立测试准入政策、由人拥有的验收门槛。
6. 模型与交付产物声明、模型依赖关系、推理入口及输出 schema。
7. qualification 和各阶段 execution evidence；退出码、事件、实际环境、输入输出哈希与失败原因。

把 bundle 的摘要放进现有冻结合同，现有合同确认与 run-start grant 就能约束具体实现；bundle、数据或规则变更会自然使旧授权失效。worker 不自行决定 task 完成、发布通过或批准下一次训练。

训练过程只挂载 train/validation；选定实现与检查点后，独立最终评估阶段才获得 final-test。仅记录 split 名字或随机 seed 不足以证明划分被冻结，应保存样本标识/分组规则/顺序与文件摘要。这个控制属于 Harness，不能委托模型散文来保证。

## 官方框架比选

| 选项 | 适合承担的协议部分 | 当前项目建议 |
|---|---|---|
| Ray Train / Tune | Train 的 Checkpoint 是任意内容的目录引用，训练循环报告 metrics/checkpoint 并显式加载恢复状态；Tune接受用户训练函数、命名指标和搜索空间。[Train Checkpoints](https://docs.ray.io/en/latest/train/user-guides/checkpoints.html)、[Tune Trainable](https://docs.ray.io/en/latest/tune/api/trainable.html) | 作为可选计算/试验调度后端；达到并行试验、多worker、多节点需求时接入。Ray trial ID映射回既有Run/child Run，不能取代本项目任务、授权和证据身份。 |
| Accelerate | 对既有 PyTorch 模型、优化器与 dataloader 做分布式运行接入；checkpoint保存模型、优化器、RNG、GradScaler，可注册额外状态，恢复预期来自同一训练脚本。[接入已有代码](https://huggingface.co/docs/accelerate/en/basic_tutorials/migration)、[Checkpointing](https://huggingface.co/docs/accelerate/en/usage_guides/checkpoint) | 作为 PyTorch 实现包内部的轻量组件，适合先接入；它不定义本项目所有任务的 I/O、冻结 split、审批或发布契约。 |
| MLflow | PythonModel/pyfunc 支持自定义预测逻辑和 artifact 依赖，signature能描述输入输出；适合跟踪与模型交换。[PythonModel](https://mlflow.org/docs/latest/ml/model/python_model)、[Signatures](https://mlflow.org/docs/latest/model/signatures/) | 可选 tracking/export integration。保留本地 canonical run_id 映射，不同时引入第二套决定训练完成的控制面。嵌套文件、模型依赖和签名可借鉴其格式。 |
| AutoTrain / TRL / PEFT | AutoTrain提供特定任务的预置训练器；TRL面向 transformer语言模型的SFT/偏好与强化学习等训练方法；PEFT提供参数高效适配与相应模型产物格式。[AutoTrain任务](https://huggingface.co/docs/autotrain/index)、[TRL](https://huggingface.co/docs/trl/en/index)、[PEFT产物](https://huggingface.co/docs/peft/en/developer_guides/checkpoint) | 作为Agent为某个实现选择的可替换依赖/加速方案，不把其任务列表、AutoModel类或trainer名称提升成本产品白名单；不据此声称包揽所有领域。 |

Ray Tune 提供 `num_samples`、`max_concurrent_trials`、`time_budget_s` 等控制，但官方明确资源声明主要用于调度，不会自动强制目标函数资源占用；函数式训练的时间停止依赖中间 report，卡死的训练循环不能靠该机制及时中断。OCI/cgroup预算、watchdog和取消仍需 Harness/worker落实。[TuneConfig](https://docs.ray.io/en/latest/tune/api/doc/ray.tune.TuneConfig.html)、[资源说明](https://docs.ray.io/en/latest/tune/tutorials/tune-resources.html)、[停止条件](https://docs.ray.io/en/latest/tune/tutorials/tune-stopping.html)

Ray Train失败恢复仍要求训练代码自行消费checkpoint；`Trainer.restore` 等旧接口已在官方新版文档中标为弃用，集成时应锁定框架版本及对应API，不能复制旧例子后认为恢复已完成。[故障恢复](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)

MLflow数据跟踪可以记录schema、source、context和digest，但不同Dataset实现的digest算法不同：MetaDataset可仅对metadata计算，EvaluationDataset对大数据可采用采样行。**不能用这些摘要替代本项目对完整材料、转换和split的固定摘要。** 模型加载还假设依赖已可用；自定义Python模型会执行代码，应在受控运行环境内加载。[Dataset最佳实践](https://mlflow.org/docs/latest/ml/dataset/#best-practices)、[MLflow Models](https://mlflow.org/docs/latest/ml/model/index.html)、[pyfunc接口](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.pyfunc.html)

PEFT产物通常只包含adapter参数与配置，仍依赖原始模型。通用Artifact不能把“一个权重文件”视为完整模型；需要记录固定基座版本、adapter/config和加载逻辑的依赖关系。[PEFT checkpoint格式](https://huggingface.co/docs/peft/en/developer_guides/checkpoint)

最终评估应与搜索/调优分离：Ray官方示例在取得最佳候选后另行执行holdout测试；scikit-learn官方说明测试集不得参与模型选择，预处理也只能在训练部分拟合。将这些规范落实为冻结数据与worker访问权限，是本项目的设计责任。[Ray独立测试示例](https://docs.ray.io/en/latest/tune/examples/tune-pytorch-cifar.html)、[防数据泄漏](https://scikit-learn.org/stable/common_pitfalls.html)

综合这些官方能力与当前本地实现，建议先完成 **薄Harness + 通用OCI执行包 + 按需Accelerate/其他原生训练库**；MLflow提供可选导出/跟踪，Ray提供后续可选并发与分布式能力。此选择是架构判断，不是对某个框架性能或覆盖所有任务的保证。

## 通用性验收门

增加一个此前未知的输入结构/输出目标时，只新增或生成实现包和数据映射，不修改核心family枚举、runner条件、推理类型或交付文件名列表；通过页面上传→Dataset→授权Run→独立Evaluation→Artifact→全新输入推理。另验证：目标漂移使旧批准失效、材料/代码/环境篡改失败、预算硬停止、取消及重启恢复、测试污染有明确证据、任意产物不能冒充完整模型。

附：本次仅修正 `integrations/deepseek-harness/test/material-tools.test.js:117` 的旧枚举断言，改为开放string并保留canonical提示/旧别名的验证；该测试文件8/8通过。未重跑完整测试，也未作真实框架执行验收。
