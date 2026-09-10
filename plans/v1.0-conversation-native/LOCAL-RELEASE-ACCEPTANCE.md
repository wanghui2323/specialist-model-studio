# Specialist Model Studio v1.0 本地发布验收

> 历史证据：下述结论仅绑定 `e88ef7a...`，不自动适用于之后的对话重构。当前 PC 收尾状态见 [2026-09-10 最终候选账本](FINAL-PC-RELEASE-20260910.md)。

验收日期：2026-08-30

验收分支：`codex/v1.0-conversation-native`

验收源码提交：`e88ef7ab1855855bc97dc95669ddb5eec6eef514`

产品版本：`1.0.0rc1`

当前结论：**本地 RC 通过，可进入首轮产品审核与体验；远端公开发布尚未完成。**

## 1. 发布边界

- 对外产品只有一个：**Specialist Model Studio**。
- **Model Harness** 是产品内部的训练任务、数据、合同、运行、评测与产物引擎，不作为第二套对外产品。
- **DeepSeek Harness 0.1.0-rc.6** 作为内部多智能体运行插件使用，不接管产品信息架构、前端或领域真值。
- 当前真实多智能体实现为 `dsh_native_subagents`：根协调器 `training_orchestrator`，以及 `research_source`、`data_experiment`、`resource_safety`、`build_training`、`evaluation_delivery` 五个有权限边界的专家。
- 当前内置、已验证的训练能力为：图片文件夹分类、表格回归和教学数字分类。其他方向可进入需求澄清、来源研究、资源检查和能力建设请求，但在没有已验证 Recipe 与 Data Adapter 时不得创建假的 Run。

## 2. 验收分层

| 层级 | 结果 | 主要证据 |
| --- | --- | --- |
| L0 发布真值 | 通过 | 分支、版本、产品名与内部引擎边界一致 |
| L1 运行时 | 通过 | `source_revision=e88ef7a...`、`source_dirty=false`、provider ready、DSH 锁定版本校验通过 |
| L2 AI 对话与多智能体 | 通过 | AI 回合持有计划、工具动作、人工确认、结果与状态；专家只在真实子会话动作存在时出现 |
| L3 真实训练闭环 | 通过 | 120 行房价 CSV 完成数据体检、合同确认、训练、评测、样本推理、Bundle 与下载 |
| L4 诚实边界 | 通过 | 无效 CSV 未创建 Dataset/Run；ASR 产生 typed Blocker 且没有伪造训练结果 |
| L5 浏览器与视觉 | 通过 | 1440×900 与 390×844 均无横向溢出；移动端无小于 44px 的可见操作目标；控制台 0 错误 |
| L6 GitHub 远端冷克隆 | 未执行 | 需要先获得推送授权，将当前提交推送到 GitHub 后才能从远端精确 SHA 冷克隆复验 |

因此，“本地 RC 通过”不等于“GitHub 公开版本已发布”。

## 3. 真实房价回归闭环

任务：`我有一份房屋-CSV-数据-每行是一套房子-7d9387aa`

- 数据：`acceptance/fixtures/housing-regression-120.csv`
- Dataset：`dataset-338b345fe5`
- 数据指纹：`c52210321392e804eee171b33601c36a5787a56256ad28b4649c3411032e49aa`
- 规模：120 行、4 列；特征 `area_sqm`、`bedrooms`、`building_age_years`；目标 `price`
- Recipe：`tabular-regression`
- Data Adapter：`tabular-csv`
- Run：`20260829T123435898379Z-CSV-----7d9387aa`
- 切分：72 / 24 / 24
- 选中模型：Ridge
- 测试 MAE：`2371.633316257778`
- 测试 RMSE：`2796.3361736968454`
- 测试 R²：`0.9994050643966345`
- 模型大小：约 `0.001196 MB`
- 单样本 P95：`0.74372235 ms`

评测报告：

- ID：`evaluation-9dbca5a49970`
- SHA-256：`24e37a9ae5f7fdc6fc1fb0ab809a8094b8dbcf41ec105861daf99722a0a10037`
- `run_status=completed`
- `integrity_status=passed`
- `metric_gate_status=passed`
- `evidence_status=sufficient`
- `conclusion=release_ready`
- 独立测试样本数：24

新样本推理：

- 输入：`{"area_sqm":120,"bedrooms":3,"building_age_years":15}`
- 输入对象：`inference-input-734c02fdf0a3`
- 输入 SHA-256：`4f51ac81cb6539efe7a3559b301775ddd77ccf09d6cd938b94d3494b46bc9943`
- 检查对象：`sample-a3320b8affd6`
- 推理检查：`inference-f9d41c1df9f2`
- 预测：`477814.9360585906`
- 预测 SHA-256：`3ff2d93eeaa3788ffbd2facf007a9520d983cf33547d012c3dfd4425c3393fbe`
- 模型 SHA-256：`e8fcb2a6d3967788e80d8aa9686957891428824ac57c6146f3e5b7b51e61142e`

交付包：

- Bundle：`bundle-4c83f7009353`
- Manifest SHA-256：`8429a2c9eab8ddf1ff575c34553c816db2d926df54c85a04fcdcb831df7dc4ab`
- Archive SHA-256：`ef441b1c67daa14ffcb6dfd0e96dbf2d033b800ad4e9ea0cbc9923da61790785`
- 大小：9,852 字节
- 隐私边界：不包含原始数据、测试引用、内部状态或清单绝对路径
- 下载位置：运行时 `_workspace/exports`，不污染源码 checkout
- 下载文件 SHA-256 与归档哈希一致，一次性授权已消费

## 4. 两条失败关闭证据

### 4.1 无效 CSV

任务：`验收负例-缺少目标列-8cbea3ac`

- 上传缺少 `price` 目标列的 CSV 返回 HTTP 422。
- 操作前后 `dataset_id=null`、`dataset_history=[]`、`current_run_id=null`、`run_ids=[]`。
- 没有因为失败上传而创建 Dataset 或 Run。

### 4.2 ASR 未支持能力

任务：`训练一个普通话录音转文字模型-在这台电脑上离线运-738b4c2a`

用户经过 AI 对话确认后选择“提交 ASR 训练能力建设请求”。系统最终状态：

- `status=needs_recipe`
- `family=asr`
- `recipe_id=null`
- `data_adapter_id=null`
- `dataset_id=null`
- `current_run_id=null`
- `run_ids=[]`
- `control.current_stage=capability_resolution`
- Blocker：`blocker_d2f23dd5b411e66836807c8f`
- Blocker code：`recipe_unavailable`
- Reason：`verified_recipe_unavailable`
- Digest：`cf6e2a02bcc6d652ec967c0941b447a90bab79d586a14c860bd29f169069d70c`
- `run_creation_allowed=false`

浏览器刷新和新会话重入后，侧栏、页头与 AI 回合统一显示“任务当前受阻”；没有“训练完成”或虚假指标。工具失败摘要使用产品中文，不再暴露英文内部句子。

## 5. 自动化回归

最终提交 `e88ef7a...`：

- Python：`587 passed`，另有 `277 subtests passed`。
- Node：`150 passed`。
- `npm run check`：通过。
- `bash -n scripts/start_conversation_harness.sh`：通过。
- `git diff --check`：通过。

Python 的 247 条 warning 均来自 NumPy / joblib / sklearn 的已知弃用提示，没有测试失败。

## 6. 浏览器验收

- 1440×900：房价完成态与 ASR 阻断态均无横向溢出。
- 390×844：`scrollWidth=clientWidth=390`；无小于 44px 的可见按钮、输入框或可操作控件。
- 新浏览器会话：控制台 Errors 0、Warnings 0。
- AI 执行过程位于对应 AI 回合内；用户消息不持有执行时间线。
- 运行、等待回答、阻断和完成均只有一个权威主状态。

持久化截图：

- `acceptance/evidence/v1.0-local-rc-e88ef7a/housing-final-1440x900.png`
- `acceptance/evidence/v1.0-local-rc-e88ef7a/housing-final-390x844.png`
- `acceptance/evidence/v1.0-local-rc-e88ef7a/asr-blocker-1440x900.png`
- `acceptance/evidence/v1.0-local-rc-e88ef7a/asr-blocker-390x844.png`

## 7. 版本输出结论

当前提交可作为 **Specialist Model Studio v1.0.0-rc.1 本地审核候选**：

- 可以真实执行已注册 Recipe 的训练闭环。
- 可以通过对话澄清、人工确认、多智能体分工和可追溯对象呈现训练过程。
- 对未支持方向诚实失败关闭，不将“能研究/能构建请求”冒充“已经能训练”。
- 可以用于首轮用户体验、代码审核与发布前评审。

公开发布的最后一道门是：获得明确推送授权后，将当前分支推送到 GitHub，再从远端精确提交做一次无本地缓存、无预存 runs 的 L6 冷克隆复验。远端复验通过前，发布状态保持 `unreleased_rc`。
