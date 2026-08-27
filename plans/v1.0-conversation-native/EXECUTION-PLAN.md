# v1.0 对话原生 · 证据动作流执行计划

状态：L0–L6 本地 RC Gate 已通过；等待用户体验验收，未推送或发布
范围：本地可审核 RC；GitHub push、CI、cold clone、Tag 与 Release 是独立发布门
主对象：`TrainingTask`
训练引擎：`model_harness`
对话运行时：DeepSeek Harness 原生多智能体适配层

---

## 1. 目标与判断

这一版不是继续给现有页面叠卡片，而是把产品呈现反转为：

> 真实动作是主体，模型文字是解释；完成由可追溯领域证据给出，不由模型自述给出。

当前多智能体编排、角色隔离和 `model_harness_*` 工具调用是真实的，但以下边界尚未闭合：

1. 对话层仍可能把无充分证据的模型散文判为完成；
2. continuable child session 的历史证据可能被错误归到新一轮委派；
3. 多数工具没有生产 canonical ObjectRef，前端只有模型搜索结果真正可点开；
4. 对话增量依赖前端轮询触发 transcript projection，直接改成 SSE 会让事件停止产生；
5. 诊断可完成与训练可执行仍混成一个状态；
6. 三代前端和两代对话后端仍有死代码、兼容入口与测试断言交叉存在。

所以本计划同时修复后端投影真值、证据身份、动作呈现和实时传输，不再把问题描述成“底层全部正确，只差视觉”。

---

## 2. v1.0 对外承诺

### 2.1 精确口径

v1.0 的真实承诺是：

> 任意公开 Hugging Face / GitHub 训练仓库可以进入可审计的来源发现与静态可行性诊断；只有与当前已验证 Recipe 和 Data Adapter 匹配的任务，才能创建真实训练 Run。

不要使用以下表述：

- “任意开源模型都能训练”；
- “本机资源够就一定能训练”；
- “来源已绑定”等于“模型已训练”；
- “找到候选模型”等于“候选已经适配当前机器”；
- “生成 Code Agent 构建包”等于“动态 Recipe 已验证并注册”。

### 2.2 能力矩阵

| 能力层级 | 当前模型族 | 允许终态 | 不允许声称 |
| --- | --- | --- | --- |
| 开箱真实训练 | 图片目录分类、CSV 表格回归 | 真实 Run、EvaluationReport、ArtifactBundle 或类型化失败 | 生产就绪、任意模型微调 |
| 批准注册后训练 | WAV 关键词分类 | 可信声明式 Recipe 校验、人工批准注册、真实 Run 与交付 | 默认已注册、ASR、TTS、流式唤醒 |
| 教学 | Digits | 教学闭环 | 用户数据落地能力 |
| 静态诊断 | 其他公开 HF/GitHub 仓库，包括 OCR、ASR、TTS、检测、分割、时序、NLP | 来源候选、不可变版本、许可/仓库分析、训练计划、资源适配结论或 BlockerEvidence | 执行第三方代码、下载即训练、真实训练完成 |

私有来源、限流、许可不明、不可变 revision 缺失或机器资源不足，均可以产生更早的类型化阻断。它们不是“系统失败”，也不是“已支持训练”。

### 2.3 双轴状态

诊断状态和训练状态必须分开：

```text
diagnostic_status:
  not_started | running | completed | blocked

training_status:
  not_ready | available | unavailable_no_verified_recipe |
  blocked_environment | running | completed | failed
```

例如 ASR 可以是：

```text
diagnostic_status = completed
training_status = unavailable_no_verified_recipe
```

这表示诊断链路真实完成、训练明确不可用。不得把整个任务包装成成功，也不得因为训练不可用而隐藏已经完成的诊断成果。

---

## 3. 真值、身份与视觉语义

### 3.1 唯一领域真值

- `TrainingTask`、其版本化 TaskSpec、数据版本、合同、Run、评测和制品是领域真值；
- DSH session、模型文字、前端卡片和动画不能修改或替代领域状态；
- 对话层只能投影真实动作、证据和待决门，不能自行推导“已训练”；
- 人工拥有任务规格确认、数据授权、验收门、来源绑定、Recipe 注册、危险执行与发布批准。

### 3.2 事件身份

每条投影事件必须保留足以唯一归属的身份：

```text
task_id
agent_run_id
session_id / dsh_session_id
turn_id
call_id（工具事件）
delegation_id（委派事件）
parent_delegation_id（子事件）
projector_revision
source_key
event_seq
```

工具 call/result 先在全局事件集合中按 `(session_id, turn_id, call_id)` 配对，再按显式 `delegation_id / parent_delegation_id / dsh_session_id` 嵌套。不得先按 turn 分组后猜配对，也不得只按角色或 child session 前缀归属。

### 3.3 三类异常语义

| 类型 | 含义 | 视觉 | 是否可作为成功证据 |
| --- | --- | --- | --- |
| `failed` | 非预期工具、协议或运行错误 | 红色，默认展开 | 否 |
| `BlockerEvidence` | 规则、能力、资源或安全边界触发的受控阻断 | 琥珀色，显示恢复动作 | 否；但可作为诊断链路的合法终态 |
| `warning` | 不完整、降级或需要注意，但未宣告终止 | 警示色，无成功勾号 | 否 |

`projection_errors` 或事件流不健康时，观察层进入 `observation_degraded`。它不直接篡改 TrainingTask 状态，但必须阻止界面宣告“证据完整”或“本轮完成”。

---

## 4. 当前基线

审计时点的可复核基线：

| 项目 | 结果 |
| --- | --- |
| 分支 | `codex/v0.9-universal-byom` |
| 工作树 | 18 个已修改文件，9 个未跟踪文件（包含本计划、L0 基线与 Figma 参考） |
| Python | `Ran 418 tests / OK` |
| Node | `41 pass / 0 fail` |
| Patch hygiene | `git diff --check` 通过 |
| 当前 projector | `2.2` |
| 当前产品真值 | `TrainingTask` |

这只是当前脏工作树的测试快照，不是可回退版本，也不是发布证明。L0 未建立可恢复 checkpoint 前，不得开始删除型任务。

---

## 5. 执行硬规则

以下规则优先于单个 Loop 的实现说明。

1. **按 L0 → L6 连续推进。** 同一 Loop 内完成一个可验证纵向切片后继续，不再每做一个微任务就等待用户。
2. **只在以下情况暂停：** 产品范围需要用户选择、破坏性/外部动作需要授权、安全边界不明确、验收门失败、真实运行环境不可用、同一阻断连续出现且没有安全替代。
3. **先 checkpoint，后删除。** 不使用 `git reset --hard`、`git checkout --`、清空目录或覆盖用户改动。
4. **只修改当前 Loop 明确列出的产品文件和相关测试。** 新发现问题进入残留清单；除非它阻断当前 Gate，不顺手扩范围。
5. **允许更新被明确退役或明确改义行为的旧断言。** 必须报告断言修改前后和理由；不得通过修改无关断言让失败变绿。
6. **不降低验收门。** `task_contract.json`、最终测试集政策、v0.7 gates、许可、安全和人工批准门不得被代理放宽。
7. **复用已有能力。** 保留现有任务事件存储、任务专属 GET 端点、writer lease、pending approval/question 持久化和 v0.7 三条真实用户数据切片；只有在身份规则修正时才改造 `pairToolEvents`。
8. **禁止假成功。** 不使用固定计时器、装饰动画、模型自述、成功 toast 或前端临时状态冒充真实动作或完成。
9. **失败关闭。** 身份缺失、旧投影无法验真、ObjectRef 字段不全、child lineage 不明、SSE gap 无法补齐时降级为未知/阻断，不得降级为完成。
10. **用户数据不用于开发验收。** 浏览器和场景测试使用独立临时 `runs` workspace；不得回答现有用户任务的问题、批准来源、上传真实数据或启动真实用户 Run。
11. **完整结果也要安全。** Object viewer 不显示凭证、秘密、本机绝对路径、原始私有样本或被策略剥离的字段。
12. **验收门先验真。** 所有“期望为空”的 `rg` 门，改动前必须确实有命中；正则元字符场景使用 `rg -F`。假门立即停止并修订计划，不把它算通过。
13. **测试分层。** 每个纵向切片跑 targeted tests；每个 Loop 退出时跑 Python/Node 全量。测试数量不是唯一质量门，减少必须能逐项对应明确退役测试。
14. **浏览器验收必须闭环。** 记录入口、task_id、动作、对象 ID、刷新结果、重新进入结果、下游结果、负例/取消、console/network/layout。
15. **实施与发布分离。** 本地测试、浏览器通过、Git commit、GitHub push、CI、cold clone、Tag、Release 分别报告，不互相替代。

### 每个 Loop 的固定报告

```text
Loop：
完成的纵向切片：
修改文件（含符号或行号）：
改义/删除的旧断言：
targeted tests：
Python 全量：Ran N tests / OK 或 FAILED
Node 全量：N pass / 0 fail 或 FAILED
浏览器证据：route / task_id / object_id / reload / re-entry / negative
未通过项与残留风险：
是否触发人工门：
下一 Loop：
```

---

## 6. Loop 总览

| Loop | 目标 | 主要退出证据 |
| --- | --- | --- |
| L0 | 范围、兼容策略与可恢复基线 | checkpoint + 能力口径 + `/chat` 决策 |
| L1 | 事实内核：事件身份、真值分类器和投影迁移 | classifier 契约 + projector 新版本 + 旧 completed 降级 |
| L2 | 动作与 ObjectRef 证据图 | producer/descriptor 矩阵 + 精确身份负例 |
| L3 | AI-native 对话与三态 Inspector | 可审计动作流 + 点击真实产物 + 双轴能力 UI |
| L4 | SSE 替换前端轮询 | wire contract + 重连对账 + 显式降级 |
| L5 | 退役遗留架构和死 DOM | 全仓残留门 + 恢复/真值回归 |
| L6 | 双场景闭环、文档与本地 RC | 两条 6/6 流 + 全量回归 + 准确发布边界 |

---

# L0 · 范围冻结与可恢复基线

## L0.1 建立 checkpoint

在不覆盖用户改动的前提下，记录：

- 当前 HEAD 和分支；
- `git status --short`；
- tracked diff 的可恢复补丁；
- 7 个 untracked 文件的路径、大小和 SHA-256；
- `runs` workspace 位置和 writer identity；
- Python/Node 基线输出；
- 当前 8802/DSH runtime identity（如服务仍运行）。

checkpoint 可以是经用户允许的本地 WIP commit，也可以是明确路径的补丁与 untracked 文件备份。不得用 stash 作为唯一恢复方式，不得提交 `runs/`、私有数据或凭证。

## L0.2 冻结四级能力矩阵

把第 2.2 节作为产品、Agent prompt、runtime 元数据和文档的共同口径。任何实现不得把“诊断可完成”提升为“训练可执行”。

## L0.3 `/chat` 兼容决策门

`/chat` 曾作为公开兼容 API，不能在死代码清理中静默消失。开始 L5 前必须选择一个方案：

- **方案 A（推荐）**：移除 `ChatController` 实现，`/chat` 保留一个版本并稳定返回 HTTP 410，响应包含 canonical conversation endpoint；下一 major 再删除路由。
- **方案 B**：hard delete，返回 404；必须确认没有外部兼容承诺，并写迁移说明。

无论选哪种，`/tasks/{task_id}/conversation/messages` 都是唯一产品对话入口。

## L0.4 人工决定

以下决定需记录到执行报告：

1. `/chat` 选择 A 或 B；
2. direct controls 的定位：保留为 Agent 提议后的人工审批/恢复动作，不建立第二套“手动流程”；
3. 本次 Loop 终点默认为本地可审核 RC；是否继续 GitHub push/CI/cold clone/Release 另行授权。

## L0 Gate

- [x] checkpoint 可恢复且不含 `runs`/凭证/用户数据；
- [x] Python 418、Node 41 或重新测得的精确基线已记录；
- [x] 四级能力矩阵已冻结；
- [x] `/chat` 兼容方案已选；
- [x] direct controls 和本次交付终点已记录；
- [x] 没有修改任何现有用户任务。

L0 未通过时停止，不进入 L1。

---

# L1 · 事实内核：事件身份、真值分类器与投影迁移

目标：让事件分类、conversation items 和 Agent run reconciliation 使用同一份真值判据。

## L1.1 全局事件配对与委派身份

先标准化事件身份，再做任何 UI 分组：

1. tool call/result 按 `(session_id, turn_id, call_id)` 全局配对；
2. delegation tool result 必须保存 `delegation_id` 和真实 `dsh_session_id`；
3. child event 必须带 `parent_delegation_id`；
4. continuable child session 的每次 invocation 必须有明确 turn/span 边界；
5. 无法绑定到本次 delegation 的 child event 标为 `unbound_observation`，不参与完成判断；
6. 控制工具单独分类，不能混入领域工具：`list_agents`、session 管理、delegation、`ask_user_question`、approval/question transport。

不得用以下启发式替代身份：角色名、时间相近、child session 曾经出现过、字符串前缀、当前唯一运行 specialist。

## L1.2 共享 truth classifier

后端建立唯一 classifier。它必须同时驱动：

- 持久化 classified events；
- `/conversation` 的 `items`；
- `final_synthesis` / `coordinator_note`；
- team/delegation 状态；
- Agent run reconciliation；
- `active_event`；
- `observation_degraded`。

前端可以校验和显示类型，但不得重新把文本推断成 completed。

### 工具分类

```text
control
ephemeral_observation
persistent_evidence
domain_transition
human_checkpoint
```

仅成功且身份匹配的 `persistent_evidence` 或 `domain_transition` 可以支撑完成。工具名前缀 `model_harness_*` 本身不构成证据；单独一次 `model_harness_get_task`、`list_tasks` 或 `list_agents` 不能证明研究、训练或交付完成。

### final_synthesis 条件

根消息只有在以下条件全部成立时才可成为 final：

1. 属于当前 `agent_run_id`；
2. 当前根轮次不存在仍运行的 delegation 或待配对 tool_call；
3. 有本次根轮次直接证据，或有通过 `parent_delegation_id` 绑定到本次 invocation 的 child 证据；
4. 证据对象的 `task_id` 与当前任务一致；
5. 没有未处理的 `projection_errors` 或 stream observation gap；
6. final 自身挂出支撑它的 canonical ObjectRefs；
7. 同一 agent run 最多一个 terminal final。

L1 不为补齐功能而发明 ObjectRef。某类领域结果尚未完成 L2 producer 合同时，即使工具成功，也要暂时降级为 `coordinator_note` / evidence pending；L2 补齐真实 producer 后，classifier 才能依据该类 Ref 恢复 final。这是有意的失败关闭，不是用散文兜底。

仅解释进展、启动后台任务、汇报部分结果、查询状态或等待另一专家的文字统一为 `coordinator_plan` / `coordinator_note`，不得标 completed。

### 领域完成条件

- 诊断完成：必须有该诊断阶段对应的持久证据或合法 BlockerEvidence；
- 训练完成：必须有同一 `task_id/run_id` 的领域终态、EvaluationReport，且不得被 Agent 文本覆盖；
- 交付完成：必须有可验证 ArtifactBundle identity/digest；
- pending question/approval：Agent run 为 `waiting_for_human`，不是 failed 或 completed。

## L1.3 projector 语义版本

这是破坏性语义修复，projector revision 从 `2.2` 升到新的 major revision（本计划原定 `3.0`，子智能体身份链语义修正后使用 `3.1`）。同一切片原子更新：

- projector constant；
- runtime contract；
- startup identity gate；
- frontend compatible runtime gate；
- adapter/preset version声明；
- 对应 Python/Node/shell tests。

旧事件不覆盖、不删除。旧 revision 的 `completed` 不能直接继承为当前完成：

- 能从原始 DSH transcript 重投影的，生成 `3.1` 事件；
- 不能重投影或身份不足的，公开状态为 `legacy_unverified_completion` / `observation_degraded`；
- 不得改写旧证据来让它满足新规则。

## L1.4 失败、阻断和观察降级

- `failed`：非预期错误，红色语义；
- `BlockerEvidence`：受控阻断，琥珀色语义，包含事实、规则、恢复动作；
- `warning`：非终态告警；
- `projection_errors`：进入 `observation_degraded`，对话顶部持续可见；
- `stream_health` 连续失败：进入 `observation_degraded`，提示可能遗漏审批/问题；恢复后保留一次可审计恢复事件。

`projection_errors`、stream health、projector revision 和 classifier result 必须进入前端 render key，避免状态变化但页面不重渲染。

## L1 行为契约

至少覆盖：

1. 根轮次有当前持久证据且已有 canonical Ref → 可 final；
2. 当前 delegation 的 child 有证据且已有 canonical Ref → 可 final；
3. 纯文本 → coordinator note；
4. control tool 成功 → 仍不可 final；
5. 领域工具失败 → 不可 final；
6. delegation 无 child 证据 → 不可 final；
7. continuable child 的历史证据 → 不可支撑新 invocation；
8. 跨 task ObjectRef → 拒绝；
9. 未配对 tool_call → run 仍 running/observing；
10. pending question/approval → waiting_for_human；
11. 同轮多条 assistant 文字 → 最多一个 terminal final；
12. `get_task` 单独只能支撑任务状态陈述，不能支撑研究/训练完成；
13. projector 2.2 completed 在无法重投影时降级；
14. classifier 输出同时被 items 与 reconciliation 使用；
15. projection error/stream failure 触发 observation_degraded。

## L1 Exit Gate

- [x] classifier 没有“任意 `model_harness_*` 成功即证据”的规则；
- [x] stale child evidence、跨 task、control-only 三个负例通过；
- [x] classified events、items、team run 使用同一 classifier 输出；
- [x] projector 3.1 runtime identity 在后端、前端、启动脚本一致；
- [x] 旧 completion 不被静默继承；
- [x] projection/stream 异常可见且不显示成功；
- [x] Python/Node 全量与启动脚本契约通过；
- [x] `git diff --check` 通过。

---

# L2 · 动作与 ObjectRef 证据图

目标：让每个可审计声明拥有真实、可验证、可定位的证据引用，而不靠前端猜 ID。

## L2.1 ObjectRef descriptor registry

建立一张共享描述表。每个类型至少声明：

```text
type
required_fields
identity_fields
digest_fields
endpoint_builder
response_selector
task_scope_rule
run_scope_rule（如适用）
redaction_policy
```

基础字段：

```json
{
  "type": "repository_analysis",
  "id": "analysis-...",
  "task_id": "task-...",
  "digest": "sha256...",
  "label": "仓库分析"
}
```

Run 产物额外要求 `run_id`；版本化对象额外要求 revision id。缺少 required field 的 Ref 整组失败关闭，投影器不得补字段或从文本推断。

## L2.2 Producer 矩阵

DSH adapter 的领域工具成功结果必须按真实返回值生产 ObjectRef。至少覆盖：

| ObjectRef type | 必需身份 |
| --- | --- |
| `model_source_search` | task_id + search_id + base_spec_revision |
| `model_source_resolution` | task_id + resolution_id + immutable commit |
| `model_binding` | task_id + binding revision id + digest |
| `model_binding_attempt` | task_id + attempt_id |
| `repository_analysis` | task_id + analysis_id + digest |
| `training_plan` | task_id + plan revision id + plan digest |
| `resource_feasibility` | task_id + report/probe identity + digest |
| `staged_asset` | task_id + asset_id + digest |
| `recipe_build` | task_id + attempt_id + candidate/validation digest |
| `evaluation_report` | task_id + run_id + report identity/digest |
| `artifact_bundle` | task_id + run_id + bundle_id + manifest digest |
| `blocker` | task_id + blocker id + evidence digest |

如果真实对象没有稳定 identity/digest，先修对象或精确读取合同，不能让 adapter 发明一个 ID。

## L2.3 精确读取端点

优先复用已有 task-owned GET。`current` 或 list 端点不能用于查看旧 revision 的精确 Ref。缺失时只增加具体、只读、task-owned 的精确端点，例如：

- `/tasks/{task_id}/training-plans/{revision_id}`；
- `/tasks/{task_id}/resource-feasibility/{record_id}`；
- 其他确实缺少的版本化对象读取端点。

不要新建模糊的通用 `/objects/{type}/{id}`，不要从“当前对象”替代历史引用。

## L2.4 无持久对象的 event-result viewer

HF catalog 临时查询、control tool 返回或其他没有领域持久对象的结果，不伪造 ObjectRef。使用持久化 conversation event 的 `(task_id, projector_revision, event_seq/source_key)` 打开 event-result viewer：

- 只显示已经投影并脱敏的 tool result；
- 不重新调用外部 API；
- 不把 event result 当领域完成证据；
- control result 与领域证据视觉分离。

## L2.5 paired action contract

L1 的全局 call/result 配对在 L2 输出稳定的 action 投影，供 L3 直接渲染，不让前端再次猜测：

```text
action_id
task_id
agent_run_id
session_id
turn_id
call_id
delegation_id / parent_delegation_id
tool_name
tool_class
actor_role
started_at / ended_at / duration_ms
status
object_refs
event_result_ref（无持久对象时）
error / blocker / warning
```

同一个 `call_id` 在不同 session/turn 下不能碰撞；未配对 call 保持 running；孤立 result 标 identity error。control action 可以显示但不计入领域动作数。

## L2 producer tests

每种 producer 至少验证：

- canonical 正例；
- task identity 错配；
- 缺 ID；
- 缺 digest（该类型要求时）；
- run_id 错配（Run 产物）；
- wrapper/JSON string 正确透传；
- 非结构化模型文本不得生成 Ref；
- credential/absolute-path redaction。

## L2 Exit Gate

- [x] producer/descriptor 矩阵无“只有前端 endpoint、没有 producer”的空行；
- [x] 每个 Ref 可构造精确 task-owned GET；
- [x] 历史 revision 不被 `current` 冒充；
- [x] EvaluationReport/ArtifactBundle 带 run_id；
- [x] 无持久对象只进入 event-result viewer；
- [x] paired action 身份、耗时、状态、Ref 和 delegation 归属完整；
- [x] 跨 task、缺字段、未知 type 均显式失败；
- [x] Python/Node 全量通过；
- [x] `git diff --check` 通过。

---

# L3 · AI-native 动作对话与三态 Inspector

视觉与布局参考见 `plans/v1.0-conversation-native/FIGMA-REFERENCE.md`。采用参考稿的轻量顶栏、任务历史、中心对话、附件 composer、按智能体动作时间线和按需右侧面板；不照搬其静态完成状态、永久右栏、品牌红色或演示数据。

目标：用户首先看到真实工作过程，再按需查看证据和任务领域状态。

## L3.1 动作项成为主时间线

`tool_call` / `tool_result` 不再被折叠成模糊的 team summary。配对后形成一等 action item，至少显示：

- 真实工具名；
- 角色元数据；
- running/completed/failed/blocked 状态；
- 真实开始/结束时间和耗时；
- ObjectRefs 或 event-result 入口；
- 失败/阻断的具体原因。

control tools 独立、低权重呈现，不计入领域动作数量。

## L3.2 按显式 delegation 嵌套

一次 delegation 是一个可展开工作单元：

- 依据 `delegation_id / parent_delegation_id`，不依据 turn 猜测；
- 标题是“做了什么”，角色只是元数据；
- 显示领域工具数、control tool 数和产物数；
- running 默认展开；
- completed 可折叠；
- failed/BlockerEvidence 默认展开；
- 无法绑定的 child event 放入“未能验证归属的运行时观察”，不塞进任意 specialist。

## L3.3 ACTIVE_EVENT_TYPES 独立

用于“当前正在做什么”的类型必须单独定义，不能复用所有可渲染类型：

- 未完成的领域 tool_call；
- 正在运行的 delegation；
- pending human checkpoint 作为独立 checkpoint，不冒充 tool activity。

final、narration、completed action、warning 和历史 specialist output 都不能驱动“正在处理”。没有真实活动时不显示呼吸灯或处理中动画。

## L3.4 散文降级

- `coordinator_plan`：说明计划，无成功徽章；
- `coordinator_note`：明确“模型叙述，不代表任务状态”；
- `specialist_output`：作为该 delegation 的解释性交付，不替代 ObjectRef；
- `final_synthesis`：只有 L1 classifier 允许时出现，并显示支撑 Ref；
- 前端不得给缺 status 的 final 默认补 `completed`。

## L3.5 Inspector 三态

Inspector 只有三种状态：

1. **closed**：默认状态，对话占主视觉；
2. **object-viewer**：用户点击 ObjectRef/event result，显示精确对象；
3. **task-workspace**：用户主动打开任务数据、运行、评测或产物域视图。

禁止：

- 页面加载自动打开；
- stage change 自动打开；
- ObjectRef 找不到时退回 generic plan tab；
- 用当前对象替代被点击的旧 revision；
- 关闭后刷新又自动恢复为打开。

Object viewer 必须显示 type、canonical id、task_id、digest、run_id/revision（如适用）和脱敏后的完整 JSON。未知类型显示“暂不支持查看”，404/identity mismatch 显示真实错误。

## L3.6 双轴能力界面

在来源选择前和任务上下文内同时显示：

- 当前诊断能力；
- 当前训练能力；
- 为什么不可训练；
- 可恢复动作；
- 不会执行的动作。

ASR 示例不得显示“下一步继续训练”。它可以继续完成静态诊断，但训练 CTA 必须禁用并显示 `unavailable_no_verified_recipe`。WAV 关键词显示“需可信声明式 Recipe 注册后可训练”，不能显示“已注册”。

## L3.7 projection/stream health 可见

- `projection_errors` 在对话顶部持久显示；
- failed 默认展开、BlockerEvidence 琥珀、warning 独立；
- `projection_errors` 和 `stream_health` 必须进入 render key；
- observation degraded 时不显示“证据完整”。

## L3 browser matrix

至少使用临时 workspace 验收：

1. 有根动作 + 两个并行 child delegation + final；
2. continuable child 被第二次调用，不串入旧动作；
3. failed tool；
4. BlockerEvidence；
5. projection error；
6. pending question；
7. 一个真实 ObjectRef；
8. 一个 event-result；
9. 未知 Ref；
10. ASR 诊断完成/训练不可用；
11. 图片分类训练可用。

桌面 1440px 与移动 390px 均检查：无横向溢出、主动作不被遮挡、Inspector 焦点/关闭/返回正确、44px 触控目标、console/network 无未解释错误。

## L3 Exit Gate

- [x] 时间线主体是真实 action，不是组织状态板；
- [x] global pairing 与 delegation nesting 身份连续；
- [x] control tools 不计领域动作；
- [x] final 有 Ref，散文无完成徽章；
- [x] Inspector 默认 closed，点击后精确 object-viewer；
- [x] 双轴能力状态与真实 Recipe 注册状态一致；
- [x] failed/blocker/warning/observation_degraded 视觉不同；
- [x] frontend contract、Node 全量、Python 全量和真实浏览器通过；
- [x] `git diff --check` 通过。

---

# L4 · 对话 SSE 线协议与可靠降级

目标：进度感来自真实增量事件，而不是 1.4 秒前端轮询和 pulse 动画。

## L4.1 服务端 producer

新增 task-owned SSE endpoint：

```text
GET /tasks/{task_id}/conversation/stream
```

SSE producer 自己负责触发或订阅 transcript projection。不能假设另一个 GET `/conversation` 会持续刷新 store。

同一 task 的多个浏览器订阅应复用有界 producer/broadcaster，避免每个连接独立高频拉取 DSH。客户端断开后释放订阅；最后一个订阅离开时停止空转。

## L4.2 wire contract

事件类型固定为：

| SSE event | 用途 | 关键字段 |
| --- | --- | --- |
| `snapshot` | 首次连接或 gap 对账 | schema/projector revision、cursor、完整 conversation view |
| `delta` | cursor 之后的持久事件增量 | cursor、events/items delta |
| `state` | running、checkpoint、observation health | cursor、active event、stream health |
| `error` | 可恢复或终止错误 | code、message、recoverable、cursor |
| `heartbeat` | 断连检测，不代表工作进度 | server time、cursor |

要求：

- 每个 snapshot/delta/state 有单调 cursor；
- SSE `id:` 使用可恢复 cursor；
- 支持 `Last-Event-ID`，也可保留显式 `after_seq` 作为测试/兼容入口；
- heartbeat 不进入对话动作计数；
- 响应设置 no-cache/no-buffering 语义；
- 请求 task 不存在返回 404；
- DSH 在连接前不可用返回 503；
- 连接中运行时失效发送 typed error 后关闭或进入明确降级。

## L4.3 gap reconciliation

重连时：

1. cursor 有效且 projector revision 一致 → 只发缺失 delta；
2. cursor 过旧、未知、跳号或 revision 改变 → 发新 snapshot；
3. 客户端发现 seq gap → 立即 GET 全量 `/conversation` 对账；
4. 对账前界面标 `observation_degraded`；
5. 不允许重复 action 或漏掉 pending question/approval。

## L4.4 前端订阅与任务切换

- 首次选择任务先取全量或接收 snapshot；
- 使用 `EventSource` 订阅真实增量；
- 每次任务切换递增 selection token，旧 stream 回调不得写入新任务；
- 切换或销毁页面时关闭旧 EventSource；
- SSE 失败时显示“实时事件已降级”，再进入 ≥5 秒串行轮询；
- 恢复 SSE 后全量对账并退出降级；
- 保留 `refreshInFlight` / `refreshSeq` 保护，防止旧响应覆盖新状态；
- 任务领域状态可以低频刷新，但 conversation 不再正常态 1.4 秒轮询。

## L4.5 删除假进度

- 删除 pulse/keyframes 及固定动画；
- 只根据 L3 `ACTIVE_EVENT_TYPES` 显示真实工具名或委派；
- pending question 显示“等待你的回答”，不是“正在训练”；
- 无活动时不显示处理中。

## L4 contract tests

至少覆盖：

1. 首次 snapshot；
2. 后续 delta；
3. Last-Event-ID 精确续传；
4. cursor gap → snapshot reconciliation；
5. projector revision change → snapshot；
6. 无重复/无丢失；
7. 两 task 隔离；
8. pending approval/question 不丢；
9. DSH unavailable 503；
10. midstream error；
11. heartbeat 不进入动作；
12. 客户端断开释放 producer；
13. task switch token 阻止旧 stream 更新；
14. fallback 可见且 ≥5 秒；
15. 恢复后对账并清除 degraded。

## L4 Exit Gate

- [x] 正常态不再每 1.4 秒请求 `/conversation`；
- [x] SSE producer 能独立产生新 transcript projection；
- [x] snapshot/delta/state/error/heartbeat 契约均有测试；
- [x] Last-Event-ID、gap、revision change 可恢复；
- [x] task switch 不串流；
- [x] DSH 断开不会静默丢审批/问题；
- [x] 页面只显示真实 active tool/delegation；
- [x] Python/Node 全量与浏览器断线重连通过；
- [x] `git diff --check` 通过。

---

# L5 · 退役遗留架构与死界面

目标：在事实内核、动作证据、AI-native 交互和 SSE 均已通过独立 Gate 后，才删除被新路径完整替代的实现。L5 只做可证明的减法，不承担真值迁移或新功能建设。

## L5.1 删除旧 `ConversationBridge`

删除生产不可达的 `ConversationBridge` 前，先确认 L1/L4 已经让现行实现覆盖并测试：

- `DshRpcClient`；
- `DshEventHub`；
- pending approval/question 持久化；
- RPC identity 关联；
- restart recovery；
- stream reconnect / stream health；
- `conversation_pending.json` 历史证据读取。

保留以上现行组件和测试。只删除旧 bridge 类、旧装配、旧写入路径以及仅证明旧 bridge 自身存在的测试。不得删除历史 `conversations.json` 文件，也不得因删旧类而降低 pending/restart 测试覆盖。

## L5.2 处理 `/chat` 与 `ChatController`

按 L0 已记录的决定执行：

- 两种方案都删除关键词匹配 `ChatController` 和其业务测试；
- 方案 A：保留最小 HTTP 410 compatibility route、canonical endpoint 和迁移测试；
- 方案 B：hard delete，并将 server 负例明确为 404；
- 同时处理 `tests/test_server.py` 中全部 `/chat` 断言，不能只删除 `tests/test_chat.py`；
- 文档口径留到 L6 统一核对。

## L5.3 删除被现行界面替代的 dead DOM

删除确认不可达的：

- `#taskControlPanel`；
- `#taskPlan`；
- `#stageList`；
- 对应纯旧版 renderer、ui 引用和 CSS；
- `#runEventList` 双写容器；
- `#pendingZone` 永久隐藏容器；
- 已被真实 ACTIVE_EVENT_TYPES 替代的 pulse DOM/CSS 残留。

同时更新或删除 `frontend-product-wiring.test.js` 中明确断言这些旧 DOM 和隐藏 CSS 仍存在的旧测试。这属于“明确退役行为断言”，必须在报告里展示改动前后。

不要按名字误删：

- `syncAgentCheckpoint`；
- `releaseVerdict`；
- 现行 `agentCheckpoint`；
- `inspectorEvents`；
- pending question/approval 渲染；
- L3 三态 Inspector；
- L4 SSE fallback / reconciliation；
- 仍服务 task-owned direct recovery action 的代码。

先建立引用图和运行路径证据；只有完全无现行消费者、且新路径已有测试的分支才删除。

## L5.4 纠正 direct action 命名

按 L0 决定保留的 direct run/retry/cancel controls 必须表达“Agent 提议后的人工审批或恢复动作”，并调用 canonical TrainingTask API。不得声称“让 Agent 启动”，不得拥有独立 task state，也不得成为首页第二套手动向导。

## L5 targeted gates

改动前先证明下列词确有命中，改动后再检查：

```bash
rg -n 'ConversationBridge|conversations\.json' model_harness/ tests/
rg -n 'taskControlPanel|taskPlan|stageList|runEventList|pendingZone' \
  model_harness/web/ integrations/deepseek-harness/test/
rg -n 'startThroughAgent|animation:pulse|@keyframes pulse' \
  model_harness/web/ integrations/deepseek-harness/test/
```

`conversations.json` 历史文件本身不删除，只要求生产代码不再写入。

`/chat` Gate 根据 L0 决定：

```bash
# 方案 A：只允许 HTTP 410 compatibility route、迁移文案和对应测试命中
rg -n '/chat|ChatController' model_harness/ tests/

# 方案 B：生产代码与测试均应零命中
rg -n '/chat|ChatController' model_harness/ tests/
```

正向保护门：

```bash
rg -n 'DshRpcClient|DshEventHub|conversation_pending|stream_health' \
  model_harness/ tests/
rg -n 'syncAgentCheckpoint|releaseVerdict' model_harness/web/app.js
```

这些正向门不要求符号一定永久保留，而是要求执行者对每个仍命中的现行消费者逐项解释；任何计划删除必须先证明等价能力已经由 L1–L4 覆盖。

## L5 Exit Gate

- [x] 只有通过 L1–L4 新路径替代的遗留实现被删除；
- [x] pending approval/question、restart recovery、stream health 与 SSE reconnect 测试仍通过；
- [x] `/chat` 行为与 L0 决策一致；
- [x] 明确退役对象全仓只剩允许的兼容/历史文档命中；
- [x] Python 测试变化已逐项对应新增契约与退役实现，最终 `492/492` 通过；
- [x] Node `66/66` 通过，旧 DOM 断言已按明确退役行为修订；
- [x] 临时任务打开、刷新、重启、重新进入后，对话、checkpoint、Object viewer、SSE fallback 和结果区均正常；
- [x] direct controls 没有形成第二套状态机；
- [x] 无现有用户任务被修改；
- [x] `git diff --check` 通过。

---

# L6 · 双场景闭环、文档与本地 RC

目标：用一个真实可训练场景和一个真实仅诊断场景证明产品边界，而不是只证明 UI 可点击。

## L6.1 场景 A：已验证 Recipe 真实训练

优先选择图片分类或 CSV 回归，使用独立临时 workspace 和非私有验收数据。必须从对话入口完成：

```text
需求澄清
→ TaskSpec 确认
→ Recipe/Data Adapter 匹配
→ 数据导入与体检
→ 训练合同与三项人工确认
→ 真实 Run
→ 运行事件
→ EvaluationReport
→ 全新样本试跑
→ ArtifactBundle
```

记录同一 task_id、spec revision、dataset id、run_id、report identity、bundle id/digest。刷新、服务重启和从任务列表重新进入后身份不变。

## L6.2 场景 B：ASR/TTS 静态诊断

从模糊需求进入对话，至少完成：

```text
澄清唯一输出形式
→ 人工确认 TaskSpec
→ 公开来源搜索
→ 明确选择候选
→ 不可变 revision / license / repository analysis
→ training plan / resource feasibility（若前置证据允许）
→ diagnostic_status = completed 或 typed blocked
→ training_status = unavailable_no_verified_recipe / blocked_environment
```

必须证明：

- 没有下载权重；
- 没有执行第三方源码、install script 或 remote code；
- 没有注册动态 Python Recipe；
- 没有创建训练 Run；
- 界面仍可打开每个诊断证据；
- 训练 CTA 禁用且原因准确；
- BlockerEvidence 有恢复动作，不显示成功勾号。

## L6.3 可选场景 C：WAV 关键词注册后训练

如果时间和环境允许，额外证明“批准注册后训练”不是文案：

```text
needs_recipe
→ 安全暂存 WAV class-folder ZIP
→ 可信声明式 RecipeSpec
→ candidate/validation digest
→ 人工批准注册
→ 数据导入
→ 真实训练与评测
```

不允许执行生成 Python、Shell、依赖安装或远程 URL。

## L6.4 文档与长期约束

### `AGENTS.md`

保留 OCI、QualificationRun、CPU-only、测试集和人工批准红线。把任意仓库的现行协议写为：

```text
discover → analyze → plan → resource check
```

将：

```text
isolated build → qualification → register → train
```

明确标为未实现的未来能力。

新增长期约束：

- completion 必须由共享 truth classifier 和真实领域证据决定；
- 模型散文不能改变任务状态；
- BlockerEvidence 不用成功标记；
- continuable child 的历史证据不能支撑新 invocation；
- ObjectRef 必须来自工具真实结果，前端不得发明。

### `README.md`

人工核对并只修失准处：

- 两个开箱 Recipe + 一个批准注册后 Recipe；
- 任意公开 HF/GitHub 仓库只做静态诊断；
- DSH 是对话编排适配层，不扩大训练能力；
- `/chat` 的最终兼容策略；
- SSE 与 projector revision 的实际版本；
- 本地 RC 不等于发布。

不要重写已经准确的章节，不改历史验收记录；新增本轮验收记录。

## L6.5 六点闭环矩阵

两个 P0 场景分别独立评分，不取平均：

| Flow | Object effect | Persist | Same ID | Re-entry | Guard | Error/cancel | 必须得分 |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| 已验证 Recipe 真实训练 | Run/report/bundle | 刷新/重启 | task/spec/run/ref 一致 | 列表重入/恢复 | 合同与人审门 | 无效数据/取消/失败 | 6/6 |
| 未注册模型族静态诊断 | analysis/plan/fit/blocker | 刷新/重启 | task/ref 一致 | 列表重入/恢复 | 禁止训练 | 来源失败/阻断 | 6/6 |

## L6 Final Gate

### 代码与合同

```bash
.venv/bin/python -m unittest discover -s tests
cd integrations/deepseek-harness && npm test
node --check model_harness/web/app.js
node --check model_harness/web/conversation-view.js
node --check integrations/deepseek-harness/index.js
bash -n scripts/start_conversation_harness.sh
git diff --check
```

### 产品

- [x] 两条 P0 流均为 6/6；
- [x] 零未解决 P0；
- [x] classifier、items、run reconciliation 无分叉；
- [x] 所有承诺的 ObjectRef producer/viewer 可达；
- [x] 无假进度、假完成、假训练或静默失败；
- [x] failed/BlockerEvidence/warning/observation_degraded 清晰区分；
- [x] 桌面 1440px 与移动 390px 通过；
- [x] 刷新、进程重启、任务列表重入通过；
- [x] runtime identity、writer lease、SSE reconnect 负例通过；
- [x] canonical 用户 tasks 未被验收改写；
- [x] 残余生产边界明确。

### 发布状态

只有本地 Gate 通过时，状态为：

```text
implemented = true
locally_verified = true
user_accepted = pending
github_pushed = unknown/false
ci_verified = unknown/false
cold_clone_verified = unknown/false
released = false
```

GitHub push、CI、cold clone、Tag 或 Release 必须获得后续授权并分别验证，不能因为 L6 通过而自动声明完成。

---

## 7. 真实 Gate 的通用格式

任何主动作都要记录：

```text
入口 route：
TrainingTask ID：
前置状态：
用户动作：
调用 command/API：
产生或修改的对象：
canonical ID / digest：
刷新结果：
从列表重新进入结果：
下游证据：
无效/失败/取消结果：
console / network / layout：
```

以下都不能单独证明产品闭环：

- 测试数量增加；
- build 通过；
- 页面出现成功文案；
- Agent 说“已完成”；
- 有工具调用但没有持久对象；
- ObjectRef 可点击但指向 current 而非被引用版本；
- 本地浏览器通过但没有刷新/重入/负例；
- 本地 RC 有版本号但未 push/CI/release。

---

## 8. 完成定义

本计划只有在以下条件全部成立时结束：

1. L0–L6 每个 Exit Gate 有真实证据；
2. 两条 P0 用户流各自 6/6；
3. 共享 truth classifier 约束事件、items 和 run reconciliation；
4. 证据身份能跨 root、delegation、child turn、ObjectRef 和领域对象追溯；
5. 静态诊断完成与训练不可用能同时准确表达；
6. 无已知 P0、无假成功、无用户数据污染；
7. 实施、验证、验收和发布状态分别报告。

若其中任何一项缺失，报告最后一个独立通过的 Gate 和剩余阻断，不使用“基本完成”“看起来可用”或测试总数代替完成。
