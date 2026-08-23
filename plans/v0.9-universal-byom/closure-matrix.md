# v0.9 Universal BYOM 六点闭环矩阵

## 1. 评分规则

每个 P0 流程独立按六点计分，每项只有存在可复现证据才得 1 分：

1. **对象效果**：真实创建或改变定义明确的后端对象；
2. **持久化**：重启或刷新后由权威后端返回；
3. **身份连续**：始终使用同一个 `task_id` 和正确的从属对象 ID；
4. **重入恢复**：可从任务列表重新进入、继续、取消或重试；
5. **状态守卫**：前置条件与 digest 真正阻止非法后续动作；
6. **错误/取消**：至少一个负例产生准确、可恢复且无假成功的结果。

任何一条 P0 未达到 6/6 都是本版本阻断项，不允许用平均分、测试总数或其他成功场景抵消。

## 2. L0 基线与目标

| P0 流程 | L0 基线 | 主要缺口 | 目标 | Loop |
| --- | ---: | --- | ---: | --- |
| 训练意图 → TaskSpec | 5/6 | 需把模型来源与任务规格变化的失效传播纳入同一 ID | 6/6 | L1 |
| HF/GitHub → 来源绑定 | 0/6 | GitHub Provider、不可变快照、许可和漂移守卫缺失 | 6/6 | L1 |
| 通用 Build → Test → Register → Resume | 3/6 | 可执行构建被阻断，安全隔离与真实人工修复链路缺失 | 6/6 | L3–L4 |
| 资格试跑 | 0/6 | 无通用最小训练/重载/推理协议和证据 | 6/6 | L3 |
| 动态 Recipe → 正式训练与交付 | 0/6 | Runner/UI 仍非完全 schema 驱动，未证明任意来源接入 | 6/6 | L4–L5 |

基线证据：`baseline-evidence.json`。该文件只记录起点，不代表 v0.9 已实现、验证、验收或发布。

## 3. P0 验收矩阵

| ID | 流程与入口 | 对象效果 | 持久化 | 同一 ID | 重入恢复 | 状态守卫 | 错误/取消 | 当前 | 目标 | 必须保存的证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| C01 | 创建/澄清训练任务 | 新建 `TrainingTask`、`TaskSpecRevision` | 重启后列表和详情一致 | URL、API、子对象均为原 `task_id` | 从列表继续澄清；取消不改 revision | 未确认规格不得批准计划 | 空目标、并发更新、取消 | 5/6 | 6/6 | route、task/spec ID、重启结果、并发负例、API response |
| C02 | HF 搜索/URL → 来源绑定 | 新建 `ModelSourceBinding` | 刷新仍返回选择 | 绑定属于原 task | 可更换来源并保留历史 | 无有效仓库不得 resolve | 不存在模型、401/429、取消 | 0/6 | 6/6 | provider request、binding ID、重启、失败响应 |
| C03 | GitHub URL → 来源绑定 | 新建 `ModelSourceBinding` | 同 C02 | 同 C02 | 同 C02 | 只接受允许的 URL/provider | 私库无权限、恶意 URL、取消 | 0/6 | 6/6 | URL normalization、binding ID、权限负例 |
| C04 | revision → 不可变快照 | 新建 `SourceSnapshot` 与 manifest | commit/hash 重启后不变 | snapshot 关联 task/binding | 可从失败重新 resolve | 未 resolve commit 或许可 deny 不可分析/执行 | 分支漂移、删除 revision、hash mismatch | 0/6 | 6/6 | requested vs resolved revision、commit、manifest hash、漂移测试 |
| C05 | 快照 → 仓库分析 | 新建 `RepositoryAnalysis` | 分析引用文件和版本可重读 | analysis 绑定 snapshot/task | needs_input 后补信息重试 | deny/危险/损坏快照不得 complete | 缺入口、解析失败、取消 | 0/6 | 6/6 | framework/entrypoint/data evidence refs、负例、analyzer version |
| C06 | 分析 → 训练计划审批 | 新建 `TrainingPlanRevision`、`ApprovalRecord` | 计划/digest/审批重启不变 | plan 仍属于原 task/snapshot | 修改创建新 revision | 审批只绑定展示 digest；上游变化失效 | 篡改计划、过期审批、拒绝 | 0/6 | 6/6 | plan JSON/digest、approval subject、tamper test、revision chain |
| C07 | 计划 → 环境锁与资源报告 | 新建 `EnvironmentLock`、`ResourceFitReport` | 实测值与结论可恢复 | report 绑定 plan/env/task | 选择降级方案创建新 plan | blocked 不得 Build/Run | 资源不足、无沙箱、平台不兼容 | 0/6 | 6/6 | probe output、lock hash、阻断 API、替代方案 revision |
| C08 | 批准计划 → 隔离 BuildAttempt | Worker 真实执行并创建 attempt/evidence | 日志、退出码、输出 hash 可重读 | attempt 绑定原 task/plan/snapshot | 中断后可查看并创建 child attempt | 无批准/无隔离/资源阻断禁止执行 | 路径逃逸、未准网络、fork bomb、timeout、cancel | 0/6 | 6/6 | worker job、sandbox profile、logs、resource usage、五类负例 |
| C09 | 构建失败 → 人工修复 → 新 attempt | 新建 child `BuildAttempt` 与 patch digest | 父子 attempt 历史不被覆盖 | 所有 attempt 仍属于原 task | 可从任意失败证据恢复，选择修复或放弃 | 系统不得自动改补丁/降门槛/扩权限；无人工批准不得执行 | 补丁校验失败、重复补丁、取消 | 0/6 | 6/6 | parent ID、patch diff/hash、人工批准记录、拒绝结果、恢复结果 |
| C10 | Build passed → QualificationRun | 真实执行数据读取、训练步、评测、保存/重载/推理 | checks、指标、产物、hash 可重读 | qualification 绑定 attempt/task | 失败可用新 attempt 重试 | 任一必选 check 失败不得注册 | OOM、坏数据、坏产物、security violation | 0/6 | 6/6 | 七项 checks、artifact reload、inference、negative logs |
| C11 | Qualification passed → Register/Resume | 新建不可变 Recipe/Adapter；任务进入数据阶段 | 注册表和任务重启一致 | 恢复同一 `task_id`，不建模型项目 | 从任务列表继续导入数据 | 资格未过或批准 digest 不符不得注册 | 重复注册、篡改证据、拒绝审批 | 3/6 | 6/6 | recipe/adapter IDs、approval digest、task route before/after/restart |
| C12 | schema → 数据/评测/推理 UI | UI 从 Recipe schema 渲染，导入 `DatasetVersion` | 刷新后字段和数据状态一致 | dataset/schema 关联 task/recipe | 可更换数据并使合同失效 | schema 版本不兼容禁止继续 | 缺字段、未知类型、坏文件、取消 | 0/6 | 6/6 | 无模型 ID 分支检查、DOM/API、dataset hash、invalid schema test |
| C13 | 合同确认 → 正式 TrainingRun | 新建真实 `TrainingContract`、`TrainingRun` | 重启后 run/日志/资源可恢复 | contract/run/task ID 链一致 | failed/cancelled 可保留证据重跑 | 来源/数据/环境/合同 digest 漂移阻断 | OOM、tamper、cancel、进程重启 | 0/6 | 6/6 | confirmation hash、run logs、resource trace、restart/tamper tests |
| C14 | Run → Evaluation/Inference/Bundle | 新建真实 Report、Check、Bundle | 指标、文件和 hashes 可重读/校验 | 全部引用同 run/task/model hash | 可下载、重验、下一轮 | Run complete 不等于 eval passed；eval failed 不得伪装交付成功 | 样本不足、门槛失败、artifact tamper | 0/6 | 6/6 | metrics/gates、inference I/O、bundle manifest、tamper result |
| C15 | 任一阶段 → 有证据阻断/恢复 | 新建 `BlockerEvidence`，任务投影为 blocked | 重启仍显示原因和恢复动作 | blocker 属于原 task/阶段 | 修复条件后从最早受影响阶段重试 | blocked 禁止非法下游动作 | detector failure、重复重试、取消 | 0/6 | 6/6 | blocker code/facts/rule/refs、disabled API、resolved_by chain |

“当前”列是 L0 基线判断；后续只能由对应 evidence 文件更新，不能因为代码提交自动改成 6/6。

## 4. 每个 Loop 的机器门禁

### L0 — 合同冻结

- `requirements.md`、`object-model.md`、`closure-matrix.md` 中四项边界一致；
- C01–C15 每行都有对象效果、守卫、负例和证据；
- `baseline-evidence.json` 精确记录 branch、commit、测试和当前能力；
- 创建 `l0-evidence.json` 后才可把 L0 标记 `verified`；用户确认该证据后才可标记 `accepted`。

### L1 — 来源与分析

- HF 与 GitHub 各完成一个公开仓库正例；tag/branch 均解析为不可变 commit；
- 进程重启、任务列表重入和上游分支漂移后，原 snapshot hash 不变；
- 未知/拒绝许可、无效 revision、私库无权限、下载 hash mismatch 负例通过；
- C01–C06 全部达到 6/6，保存 `l1-evidence.json`。

### L2 — 环境与资源

- 在验收机器产生真实 ResourceProbe、EnvironmentLock 和 ResourceFitReport；
- 至少一个 fit 正例、一个资源不足阻断、一个缺隔离环境阻断；
- 应用 batch/precision/LoRA 等建议后产生新计划 revision，旧批准失效；
- C07、C15 达到 6/6，保存 `l2-evidence.json`。

### L3 — 隔离构建与资格试跑

- OCI 或等价 OS sandbox 自检通过；普通宿主子进程路径被拒绝；
- 真实仓库至少完成一次失败→新 attempt 修复→资格试跑通过；
- 路径逃逸、宿主 socket/文件、未批准网络、无限进程、timeout、cancel、OOM 至少各一条负例；
- 资格试跑七项检查全部存在，失败不得注册；
- C08–C10、C15 达到 6/6，保存 `l3-evidence.json`。

### L4 — Schema 驱动正式训练

- 一个 HF 标准模型和一个 GitHub 自定义训练仓库完成 Register→Resume→Dataset→Contract→Run→Evaluation→Inference→Bundle；
- 两条路径沿用原 task ID；前端代码不存在这两个模型 ID 的专用条件分支；
- 重启后从任务列表重入，日志、指标、表单和产物一致；
- schema 不兼容、数据坏文件、合同篡改、训练取消和评测失败负例通过；
- C11–C14 达到 6/6，保存 `l4-evidence.json`。

### L5 — 通用性盲测与全局验收

- 代码冻结后选择一个开发期未使用的公开模型仓库；不改核心 UI/Runner/Provider 即完成资格试跑，资源允许时完成正式训练；若资源或许可阻断，则阻断必须符合 C15，并另选一个资源适配仓库完成正向盲测；
- 三个验收仓库不得在核心代码中出现模型 ID 硬编码；至少覆盖 HF/GitHub 两来源和两类数据/训练形态；
- Python、Node、Worker 协议、安全负例、重启、冷克隆全部通过；
- 真浏览器 1440×900 和 390×844 完成创建、来源、审批、执行、阻断/恢复、结果重入；Console 错误、失败请求和横向溢出记录清楚且无 P0；
- C01–C15 全部 6/6，零未解决 P0，保存 `l5-evidence.json`；用户只对精确 commit 的证据包作 `accepted` 决策。

## 5. 单条流程证据模板

每条 Cxx 必须至少保存：

```json
{
  "flow_id": "C00",
  "source_commit": "full sha",
  "started_at": "RFC3339",
  "start_route_or_command": "...",
  "task_id": "task_*",
  "created_object_ids": [],
  "object_effect": {"passed": false, "evidence_refs": []},
  "persistence": {"passed": false, "restart_or_reload": "...", "evidence_refs": []},
  "identity_continuity": {"passed": false, "evidence_refs": []},
  "reentry_recovery": {"passed": false, "evidence_refs": []},
  "state_guard": {"passed": false, "negative_case": "...", "evidence_refs": []},
  "error_cancel": {"passed": false, "negative_case": "...", "evidence_refs": []},
  "score": 0,
  "browser": {
    "desktop": {"viewport": "1440x900", "screenshot": null},
    "mobile": {"viewport": "390x844", "screenshot": null},
    "console_errors": null,
    "request_failures": null,
    "horizontal_overflow": null
  },
  "result": "failed|passed",
  "finished_at": "RFC3339"
}
```

评分器必须根据六个布尔项计算 `score`，不接受人工直接写 6。证据引用文件不存在、source commit 不一致或对象 ID 链断裂时，本行保持未通过。

## 6. 状态登记规则

| 状态 | 允许写入的前提 | 禁止表述 |
| --- | --- | --- |
| `implemented` | 本 Loop 代码和测试已写入工作树/commit | “已经可用”“已验收” |
| `verified` | 本 Loop 所有机器门禁在精确 commit 通过，证据可重放 | “用户已确认”“已发布” |
| `accepted` | 用户明确确认同一 verified commit 与证据 | “已推送”“已发布 Release” |

阻断结果另写 `BlockerEvidence`。一个阻断流程可以达到 C15 的 6/6，证明系统诚实且可恢复；该训练任务的产品结果仍是 `blocked`，不会产生 `delivered`。
