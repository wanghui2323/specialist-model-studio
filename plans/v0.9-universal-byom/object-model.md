# v0.9 Universal BYOM 对象模型与状态合同

## 1. 事实源原则

- `TrainingTask` 是用户管理、恢复和继续训练的唯一主对象。模型来源、仓库分析、训练计划、构建、资格试跑、Recipe、数据、正式 Run 和交付包都是它的从属对象。
- 每个可变决策通过不可变 revision 表达；禁止覆盖已批准的来源、计划、环境、合同和证据。
- 后端 Workspace/Repository 是唯一事实源。Web、CLI、Agent/DeepSeek Harness Adapter 和 Worker 只能调用同一命令 API，不能维护第二套状态。
- 工程状态 `implemented / verified / accepted`、任务阶段、运行结果、阻断结果和发布状态是不同字段，不能相互推断。

## 2. 核心对象与所有权

| 对象 | Canonical ID | Owner | 不可变/版本规则 | 创建命令 | 主要读取方 |
| --- | --- | --- | --- | --- | --- |
| `TrainingTask` | `task_id` | Workspace | 创建后永不改变 | `create_training_task` | Web、CLI、Agent、所有子对象 |
| `TaskSpecRevision` | `task_spec_revision_id` | Task service | 每次业务目标/约束变化新建 | `revise_task_spec` | Source planner、Plan builder |
| `ModelSourceBinding` | `source_binding_id` | Source service | 保存用户选择；可 supersede | `bind_model_source` | Provider、任务上下文 |
| `SourceSnapshot` | `source_snapshot_id` | Source service | provider+repo+commit+manifest digest 唯一；禁止覆盖 | `resolve_source_snapshot` | Analyzer、Builder、Contract |
| `RepositoryAnalysis` | `analysis_id` | Analyzer | 绑定 snapshot 与 analyzer version | `analyze_source_snapshot` | Plan builder、UI |
| `TrainingPlanRevision` | `training_plan_revision_id` | Plan service | 任一参数/权限/策略变化新建 revision | `create_training_plan_revision` | Resource service、Builder、Contract |
| `ApprovalRecord` | `approval_id` | Approval service | 绑定 subject type/id/digest；只追加 | `approve_subject` | Guards、审计页 |
| `EnvironmentLock` | `environment_lock_id` | Environment service | 包锁、镜像 digest、平台和权限不可变 | `resolve_environment_lock` | Worker、Qualification、Contract |
| `ResourceFitReport` | `resource_fit_report_id` | Resource service | 绑定 plan+environment+probe snapshot | `evaluate_resource_fit` | Guards、UI |
| `StagedDataAsset` | `staged_data_asset_id` | Data service | 样例隔离保存并带 digest | `stage_build_data` | Builder、Qualification |
| `BuildAttempt` | `build_attempt_id` | Build service | 每次生成/修复只追加；带 parent attempt | `start_build_attempt` | Agent、Worker、UI |
| `QualificationRun` | `qualification_run_id` | Qualification service | 绑定 attempt、snapshot、plan、environment、样例 digest | `start_qualification_run` | Registry、UI |
| `RecipeVersion` | `recipe_version_id` | Capability registry | 资格试跑和批准后不可变注册 | `register_recipe_version` | Dataset importer、Runner |
| `AdapterVersion` | `adapter_version_id` | Capability registry | 与 Recipe/API schema 独立版本 | `register_adapter_version` | Dataset importer、UI |
| `DatasetVersion` | `dataset_version_id` | Data service | 导入后内容寻址；替换数据新建版本 | `import_dataset` | Contract、Runner |
| `TrainingContract` | `contract_revision_id` | Contract service | 所有依赖 digest 冻结；确认只绑定 digest | `freeze_training_contract` | Runner、Evaluation |
| `TrainingRun` | `run_id` | Runner | 单次执行记录只追加 | `start_training_run` | Evaluation、UI |
| `EvaluationReport` | `evaluation_report_id` | Evaluation service | 绑定 run、门槛和测试集 digest | `evaluate_training_run` | UI、Delivery |
| `InferenceCheck` | `inference_check_id` | Inference service | 绑定模型哈希与输入 digest | `run_inference_check` | UI、Delivery |
| `ArtifactBundle` | `artifact_bundle_id` | Delivery service | 生成后 manifest/hash 不可变 | `create_artifact_bundle` | Download、审计 |
| `BlockerEvidence` | `blocker_evidence_id` | 产生阻断的 service | 只追加；恢复后标 resolved_by，不删除 | `record_blocker` | Task projection、UI、审计 |

## 3. 最小字段合同

以下字段是跨服务和证据检查必须存在的最小集合；实现可以增加字段，但不得改变含义。

### `ModelSourceBinding`

```json
{
  "source_binding_id": "srcbind_*",
  "task_id": "task_*",
  "task_spec_revision_id": "spec_*",
  "provider": "huggingface|github",
  "repository": "owner/name",
  "requested_revision": "main|tag|sha",
  "credentials_scope": [],
  "created_at": "RFC3339",
  "supersedes": null
}
```

### `SourceSnapshot`

```json
{
  "source_snapshot_id": "snapshot_*",
  "source_binding_id": "srcbind_*",
  "provider": "huggingface|github",
  "repository": "owner/name",
  "resolved_commit": "full immutable commit",
  "archive_sha256": "sha256",
  "manifest_sha256": "sha256",
  "license": {"spdx": "Apache-2.0", "decision": "allow|deny|review", "evidence": []},
  "remote_code": {"declared": false, "files": []},
  "snapshot_state": "resolved|blocked|failed",
  "created_at": "RFC3339"
}
```

### `RepositoryAnalysis`

```json
{
  "analysis_id": "analysis_*",
  "source_snapshot_id": "snapshot_*",
  "analyzer_version": "semver+digest",
  "frameworks": ["pytorch"],
  "task_candidates": [{"task": "text-classification", "confidence": 0.9, "evidence_refs": ["train.py:20"]}],
  "entrypoints": [{"kind": "train", "path": "train.py", "symbol": null, "evidence_refs": ["README.md:80"]}],
  "data_contract_candidates": [],
  "dependency_files": ["pyproject.toml"],
  "metrics": [],
  "artifacts": [],
  "risk_findings": [],
  "status": "complete|needs_input|blocked|failed"
}
```

### `TrainingPlanRevision`

```json
{
  "training_plan_revision_id": "plan_*",
  "task_id": "task_*",
  "source_snapshot_id": "snapshot_*",
  "analysis_id": "analysis_*",
  "revision": 1,
  "plan_sha256": "sha256(canonical json)",
  "entrypoint": {"argv": [], "working_dir": "/workspace/source"},
  "dataset_mapping": {},
  "hyperparameters": {},
  "evaluation": {"metrics": [], "gates": {}},
  "artifact_contract": {},
  "resource_budget": {"max_seconds": 0, "ram_bytes": 0, "vram_bytes": 0, "disk_bytes": 0},
  "execution_policy": {"backend": "oci|os_sandbox_worker", "network_allowlist": [], "secret_scopes": []},
  "parent_revision_id": null,
  "status": "draft|awaiting_approval|approved|superseded"
}
```

### `EnvironmentLock` 与 `ResourceFitReport`

```json
{
  "environment_lock_id": "envlock_*",
  "source_snapshot_id": "snapshot_*",
  "platform": {"os": "darwin|linux", "arch": "arm64|x86_64"},
  "execution_backend": "oci|os_sandbox_worker",
  "accelerator_policy": {"mode": "cpu_only", "detected": [], "unusable_reason": "..."},
  "base_image_digest": "sha256|null",
  "packages": [{"name": "torch", "version": "...", "hashes": []}],
  "system_dependencies": [],
  "network_allowlist": [],
  "lock_sha256": "sha256(canonical json)"
}
```

`accelerator_policy.mode` 在 v0.9 只允许 `"cpu_only"`；`detected` 保留宿主探测事实，但发现 MPS/CUDA 时必须填写 `unusable_reason`，任何将其标记为容器可用的输入都必须被校验拒绝。

```json
{
  "resource_fit_report_id": "fit_*",
  "training_plan_revision_id": "plan_*",
  "environment_lock_id": "envlock_*",
  "probe": {"cpu": {}, "ram": {}, "disk": {}, "accelerators": []},
  "requirements": {},
  "decision": "fit|fit_with_changes|blocked_resources|blocked_platform|blocked_environment",
  "reasons": [{"code": "insufficient_vram", "required": 0, "observed": 0, "evidence_ref": "..."}],
  "alternatives": [{"changes": {}, "expected_effect": "...", "creates_new_plan": true}],
  "report_sha256": "sha256(canonical json)"
}
```

### `BuildAttempt` 与 `QualificationRun`

```json
{
  "build_attempt_id": "attempt_*",
  "task_id": "task_*",
  "parent_attempt_id": null,
  "source_snapshot_id": "snapshot_*",
  "training_plan_revision_id": "plan_*",
  "environment_lock_id": "envlock_*",
  "staged_data_asset_id": "staged_*",
  "worker_job_id": "worker_*",
  "patch_sha256": "sha256",
  "patch_origin": "human",
  "patch_approval_id": "approval_*",
  "commands": [],
  "result": "queued|running|passed|failed|cancelled|timed_out|oom|security_violation",
  "exit_code": null,
  "log_ref": "...",
  "resource_usage_ref": "...",
  "output_manifest_sha256": null
}
```

`patch_origin` 在 v0.9 只允许 `"human"`；写入 `"agent"` 或 `"auto"` 必须被校验拒绝。

```json
{
  "qualification_run_id": "qualification_*",
  "build_attempt_id": "attempt_*",
  "qualification_contract_sha256": "sha256",
  "checks": {
    "data_load": "passed|failed",
    "train_step": "passed|failed",
    "metric_parse": "passed|failed",
    "artifact_save": "passed|failed",
    "artifact_reload": "passed|failed",
    "single_inference": "passed|failed",
    "isolation": "passed|failed"
  },
  "result": "passed|failed|cancelled|timed_out|security_violation",
  "evidence_manifest_sha256": "sha256"
}
```

### `BlockerEvidence`

```json
{
  "blocker_evidence_id": "blocker_*",
  "task_id": "task_*",
  "stage": "source|analysis|plan|environment|build|qualification|training|evaluation",
  "code": "blocked_license|blocked_security|blocked_environment|blocked_platform|blocked_resources|blocked_data|blocked_repository|qualification_failed",
  "detector": "component@version",
  "facts": {},
  "rule": {},
  "evidence_refs": [],
  "recovery_actions": [],
  "retryable": true,
  "created_at": "RFC3339",
  "resolved_by": null
}
```

## 4. 关系与失效传播

```text
TrainingTask 1 ── N TaskSpecRevision
TrainingTask 1 ── N ModelSourceBinding 1 ── N SourceSnapshot
SourceSnapshot 1 ── N RepositoryAnalysis
RepositoryAnalysis 1 ── N TrainingPlanRevision
TrainingPlanRevision 1 ── N ResourceFitReport
SourceSnapshot + Plan + EnvironmentLock + StagedDataAsset ── N BuildAttempt
BuildAttempt 1 ── N QualificationRun
QualificationRun(passed) + ApprovalRecord ── 1 RecipeVersion / AdapterVersion
TrainingTask + RecipeVersion + DatasetVersion + Plan + EnvironmentLock ── N TrainingContract
TrainingContract(confirmed) 1 ── N TrainingRun
TrainingRun 1 ── N EvaluationReport / InferenceCheck / ArtifactBundle
TrainingTask 1 ── N BlockerEvidence
```

失效规则：

| 上游变化 | 必须新建 | 必须失效或 supersede |
| --- | --- | --- |
| TaskSpecRevision | Source/Plan 重新判断 | 与旧规格绑定的计划批准 |
| ModelSourceBinding 或 resolved commit | SourceSnapshot、Analysis、Plan、EnvironmentLock | 旧 Build/Qualification/Recipe 对当前任务的可用性 |
| TrainingPlan 参数、门槛或权限 | 新 PlanRevision、ResourceFitReport | 旧计划批准、Qualification |
| EnvironmentLock | 新 BuildAttempt、Qualification | 旧环境下的资格结论 |
| StagedDataAsset | 新 QualificationRun | 旧样例的资格结论不能代表新样例 |
| Recipe/Adapter/Dataset | 新 TrainingContract | 旧合同确认和当前结果标记 |
| TrainingContract 内容 | 新合同 revision | 旧确认；禁止启动新 Run |

历史对象不可删除或改写，只能通过 `supersedes`、`superseded_by` 或 `resolved_by` 建立审计链。

## 5. TrainingTask 派生阶段状态机

任务阶段由最新有效从属对象派生，不允许前端直接写 badge：

```text
draft
→ source_required
→ source_resolving
→ source_ready
→ analysis_ready
→ plan_awaiting_approval
→ resource_check
→ build_ready
→ building
→ qualification_ready
→ qualification_running
→ capability_awaiting_approval
→ data_required
→ contract_awaiting_confirmation
→ training_ready
→ training
→ evaluating
→ delivery_ready
→ delivered
```

任一阶段可产生 `blocked` 投影，但 `blocked` 不是覆盖式生命周期状态：

```json
{
  "task_id": "task_*",
  "stage": "resource_check",
  "next_action": "apply_plan_alternative",
  "active_blocker_id": "blocker_*",
  "latest_successful_stage": "plan_awaiting_approval"
}
```

解除阻断后根据上游变化从最早受影响阶段继续，`task_id` 不变。

## 6. 状态守卫

| 动作 | 必须满足 | 失败结果 |
| --- | --- | --- |
| 分析来源 | SourceSnapshot resolved；许可不是 deny | 创建 BlockerEvidence；不创建 Analysis complete |
| 批准计划 | plan digest 与展示 digest 一致；许可已决策 | 拒绝批准或要求重新确认 |
| 启动 BuildAttempt | 计划已批准；ResourceFit 非 blocked；隔离后端已验证 | `blocked_environment/resources`；不得启动普通宿主进程 |
| 启动 QualificationRun | BuildAttempt passed；所有输入 digest 一致 | attempt 留存，返回 typed failure |
| 注册 RecipeVersion | QualificationRun passed；批准绑定 evidence digest | 不注册；原任务保持 qualification 阶段 |
| 确认 TrainingContract | 所有引用存在且 digest 一致；门槛为用户所有 | 旧确认失效 |
| 启动 TrainingRun | Contract confirmed；资源复检通过；数据/来源/环境未漂移 | 禁止 Run 并记录 blocker |
| 创建 ArtifactBundle | Run completed；EvaluationReport 存在；模型可重载 | 交付失败不改变 Run/Evaluation 事实 |

## 7. Worker 协议与隔离合同

### Job 输入

主服务只传对象 ID、不可变 digest、声明式权限和短期输出凭据。Worker 根据受控对象存储解析输入，不接受任意宿主绝对路径。

```json
{
  "protocol_version": "byom-worker/0.1",
  "job_id": "worker_*",
  "task_id": "task_*",
  "kind": "build|qualification|train|evaluate|infer",
  "input_refs": [],
  "resource_limits": {},
  "mounts": [{"ref": "snapshot_*", "mode": "ro"}],
  "network_allowlist": [],
  "secret_scopes": [],
  "timeout_seconds": 0
}
```

### NDJSON 事件

每行必须包含 `protocol_version,event_id,job_id,task_id,sequence,timestamp,type,payload`。允许事件类型：`stage_started`、`log`、`metric`、`resource`、`question`、`approval_required`、`artifact`、`warning`、`failed`、`completed`。缺序、重复 event_id、未知必填字段或 digest 不一致必须使消费者失败关闭。

### 隔离最低条件

- 输入挂载只读，输出挂载独占可写；
- 禁止 Docker/宿主 socket、设备和宿主工作区；GPU 设备必须显式授权；
- 默认网络拒绝，仅构建阶段可按域名 allowlist 开放；训练阶段默认离线；
- CPU、RAM、磁盘、GPU、pids、wall time 均有上限；取消和超时可强杀进程组；
- secret 只按 job scope 注入、日志脱敏、结束即撤销；
- OCI 或 OS sandbox profile 自检失败时，不执行来源代码并记录 `blocked_environment`。

## 8. 工程状态、产品结果与发布状态

```json
{
  "loop_status": "planned|implementing|implemented|verified|accepted",
  "task_result": "in_progress|qualified|blocked|training_failed|evaluation_failed|delivered",
  "publication": {
    "commit": "local|recorded",
    "push": "not_started|done",
    "ci": "not_started|passed|failed",
    "release": "not_started|published"
  }
}
```

不允许的推断：

- `implemented` 不推出 `verified`；
- 自动测试通过不推出用户 `accepted`；
- `blocked` 流程被正确验证不推出模型 `delivered`；
- 本地 commit 不推出 push、CI、Tag 或 Release；
- Worker 事件 `completed` 不推出 Evaluation passed 或 Bundle delivered。
