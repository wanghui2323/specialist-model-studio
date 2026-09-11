# L2 ObjectRef 与动作证据图审计

日期：2026-08-25
状态：实现中，待全量回归与浏览器验收
适用 projector：`3.1`
ObjectRef schema：`1.0`
Action schema：`1.0`

## 1. 约束

1. ObjectRef 只能由领域工具的结构化真实返回值生成，模型文本和前端不得发明。
2. 每个 Ref 必须属于当前 `task_id`；运行产物还必须属于同一 `run_id`。
3. 描述表要求的 identity、revision、commit 或 digest 任一缺失时，整组 Ref 失败关闭。
4. 历史对象必须使用精确 task-owned GET；`current` 和 list 不能代替被引用版本。
5. 没有持久领域对象的结果只生成 EventResultRef，不参与领域完成判定。
6. label 可能泄露绝对路径或 credential 时退化成安全类型名；canonical Ref 不保留额外字段。
7. `get_task`、list 和 control 结果只用于观察；只有返回精确持久对象及合格 Ref 的领域工具才能支撑该阶段 synthesis，Run 产物还要与工具参数中的 `run_id` 一致。

共享描述表位于 `model_harness/object_refs.py`。后端 projector、truth classifier 与 action projector 统一调用该表；前端只消费已经验证的 Ref。

## 2. Producer / descriptor / viewer 矩阵

| ObjectRef | 真实 producer 工具 | 强制身份或摘要 | 精确读取端点 | response selector |
| --- | --- | --- | --- | --- |
| `model_source_search` | `model_harness_search_model_sources` | task + search + TaskSpec revision | `/tasks/{task}/model-source-searches/{id}` | `search` |
| `model_source_resolution` | `model_harness_select_model_source_candidate`, `model_harness_resolve_model_source` | task + resolution + immutable commit + digest | `/tasks/{task}/model-source-resolutions/{id}` | `resolution` |
| `model_binding_attempt` | `model_harness_bind_model_source` | task + attempt + digest | `/tasks/{task}/model-binding-attempts/{id}` | `binding_attempt` |
| `model_binding` | `model_harness_list_model_bindings` | task + binding revision + revision + digest | `/tasks/{task}/model-bindings/{id}` | `binding` |
| `repository_analysis` | `model_harness_get_repository_analysis` | task + analysis + digest | `/tasks/{task}/repository-analyses/{id}` | `analysis` |
| `training_plan` | create/revise/decide/get training plan | task + plan revision + revision + plan digest | `/tasks/{task}/training-plans/{id}` | `training_plan` |
| `resource_feasibility` | get/check resource feasibility | task + record kind + record id + digest | probe/lock/report 各自精确端点 | record body |
| `staged_asset` | `model_harness_stage_recipe_samples` | task + asset + spec revision + SHA-256 | `/tasks/{task}/staged-assets/{id}` | `staged_asset` |
| `recipe_build` | build/get validated Recipe | task + attempt + candidate digest + validation digest | `/tasks/{task}/recipe-builds/{id}` | `recipe_build` |
| `evaluation_report` | `model_harness_get_evaluation_report` | task + run + report + report digest | `/tasks/{task}/runs/{run}/evaluation-report` | report body |
| `artifact_bundle` | build/get/list Artifact Bundle | task + run + bundle + manifest digest | `/tasks/{task}/runs/{run}/artifact-bundles/{id}` | bundle body |
| `blocker` | get/check resource feasibility | task + blocker + evidence digest | `/tasks/{task}/blockers/{id}` | `blocker` |

`EvaluationReport.report_sha256` 排除易变的 `updated_at` 后计算；Artifact Bundle 在 manifest 和 bundle record 同时保存 `manifest_sha256`。旧记录没有摘要时可以继续作为历史 JSON 被读取，但 adapter 不得为其生产 evidence-ready Ref。

## 3. 无持久对象的结果

`EventResultRef` 的 canonical identity 为：

```text
type=event_result
id
task_id
projector_revision
event_seq
source_key
```

读取入口为：

```text
GET /tasks/{task_id}/conversation/events/{event_id}?projector_revision=3.1
```

它只读取已持久化且已脱敏的投影事件，不重放工具、不重新请求网络，也不作为 final synthesis 的完成证据。

## 4. Paired action contract

`model_harness/conversation_actions.py` 以 `(task_id, agent_run_id, session_id, turn_id, call_id)` 配对 action。输出保留 delegation lineage、真实起止时间、耗时、状态、ObjectRefs、EventResultRef 与错误语义。

- 领域、控制、委派工具分级；control 不计入领域动作数。
- 未配对 call 保持 `running`；孤立或身份冲突 result 为 `identity_error`。
- ObjectRef 整组通过共享 registry 验证后才挂到 action。
- action、conversation items 与 run reconciliation 不从工具名或模型散文推断完成。

## 5. 负例与回归要求

必须持续覆盖：canonical 正例、跨 task、缺 ID、缺 digest、run 错配、未知类型、JSON wrapper、非结构化文本、绝对路径与 credential label 脱敏、历史 revision 精确读取、EventResultRef 不升级为完成证据。

L2 只有在 Python/Node 全量、启动契约和 `git diff --check` 全部通过后关闭。前端能够显示一个按钮，不等于 producer、精确 GET 或证据身份已经验收。
