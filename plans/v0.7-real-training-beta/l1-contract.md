# Model Harness v0.7 · L1 任务理解与可信控制面

> 状态：`verified`  
> 授权日期：2026-08-22  
> 验证日期：2026-08-22  
> 主对象：`TrainingTask`  
> 本轮禁止事项：不构建或注册新 Recipe，不训练语音模型，不接入 Hugging Face。

## 1. 本轮用户结果

用户创建或重新进入一个训练任务时，必须能直接回答四个问题：

1. 系统把我的需求理解成了什么；
2. 这个理解是否需要我澄清，如何修改；
3. 当前真正阻塞在哪里，唯一下一步是什么；
4. “停止 Agent”和“取消训练”分别会影响哪个对象。

L1 不是重新设计一张静态工作台。所有可见状态都来自同一个 `task_id` 的后端对象；只有输入草稿属于明确标注的本机 UI 状态。

## 2. 对象与所有权

| 对象 | Canonical ID | Owner | 权威存储 | 作用 |
|---|---|---|---|---|
| TrainingTask | `task_id` | TrainingWorkspace | `tasks/<task_id>/task.json` | 数据、合同、运行与会话的主对象 |
| TaskSpecRevision | `task_id + revision` | TrainingWorkspace | `tasks/<task_id>/spec_revisions/rN.json` | 保存每次任务理解与用户纠错，不覆盖历史 |
| TaskControlProjection | 派生自 `task_id` | TrainingWorkspace | API 响应投影 | 唯一 current stage、blocked reasons、next action |
| ConversationSession | `task_id → session_id` | ConversationBridge | `conversations.json` | 恢复 Agent 会话；不拥有训练状态 |
| ComposerDraft | `task_id` 或 `new-task` | Web UI | 本机 `localStorage` | 切换任务与刷新后恢复未发送输入，不进入训练事实 |
| RunCancellation | `task_id + run_id` | TrainingWorkspace / RunService | Run 状态与事件 | 只取消属于该任务的训练 Run |

## 3. TaskSpecRevision 合同

每个规格版本至少包含：

- `revision`、`revision_id`、`task_id`、`created_at_utc`；
- `business_goal`；
- `capability_request`：`modality`、`objective`、`target_kind`、`data_adapter`、`constraints`；
- `clarification_required` 与可观察的 `clarification_reasons`；
- `source`：创建、用户纠错或迁移。

规则：

- 用户修改规格时保持同一 `task_id`，追加 revision，不覆盖上一版；
- 运行中不能修改规格；
- “识别图片内容”、只说 OCR，或同时指向文字识别、图像分类、目标检测的请求必须进入 `needs_clarification`；
- `needs_clarification` 不得创建 Recipe Build Request、导入正式数据或创建 Run；
- 明确选择图像分类、文字识别或目标检测后，后端重新匹配能力并给出真实边界；
- 修改规格不得让旧合同或旧运行继续显示为当前有效结果。

## 4. 单一控制投影

`GET /tasks`、`GET /tasks/{task_id}` 及所有任务写操作必须返回同结构：

```json
{
  "control": {
    "current_stage": "define_task | capability | data | contract | training | evaluation | delivery",
    "stage_label": "确认任务理解",
    "blocked_by": [
      {"code": "task_spec_clarification", "message": "请先确认模型要输出什么"}
    ],
    "next_action": {
      "type": "clarify_task_spec",
      "label": "确认模型任务",
      "description": "选择图像分类、文字识别或目标检测"
    }
  }
}
```

规则：

- 一个任务同时只显示一个主阶段和一个主下一步；
- 列表、顶部、计划区、Context 与对话 fallback 使用同一投影；
- Agent 离线是协作服务状态，不得改写任务阶段，也不得显示“本地训练可用”作为笼统承诺；
- 训练运行中只允许“查看运行”和“取消训练”；停止 Agent 不得取消 Run。

## 5. API 与作用完整性

| 控件/命令 | 前置条件 | 对象效果 | 负向结果 | 下游证据 |
|---|---|---|---|---|
| 修改任务理解 | 非 running | 追加 TaskSpecRevision | 空字段、无变化或 running 被拒绝 | 同 task_id 刷新后 revision 增加 |
| 确认澄清 | needs_clarification | 新 revision + 重新匹配 | 未选择具体目标不写入 | control 进入 capability/data |
| 导入数据 | next action = import_dataset | 创建 DatasetVersion | 模糊规格、错误格式被阻断 | 数据 Context 与 task.json |
| 停止 Agent | 存在运行会话 | 调用 session.cancel | 无会话返回准确错误 | conversation.running=false；Run 不变 |
| 取消训练 | 当前 task 拥有 active run | RunService cooperative cancel | 非本任务 run、终态 run 被拒绝或 no-op | Run 事件与 task control 更新 |

## 6. 交互结构

### 桌面

- 左侧：Training Task 列表与真实状态；
- 中间顶部：任务理解确认卡、当前阶段、唯一下一步；
- 中间主体：对话、工具、批准与运行事件；
- 右侧：能力、数据、运行、评测、产物证据；
- “停止 Agent”只出现在 Agent working 区；“取消训练”只出现在 Run 区并明确二次确认。

### 390px 移动端

- 顶部显示任务名称、当前阶段和唯一下一步；
- 任务理解卡可以折叠，但有歧义时必须展开；
- Context 使用底部入口或抽屉，不要求用户先滚过完整对话；
- 所有主点击目标至少 44×44px；草稿按 task_id 恢复。

## 7. 六点闭环门槛

| P0 Flow | Object effect | Persist | Same ID | Re-entry | Guard | Error/cancel | 目标 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 创建模糊任务 → 澄清 → 继续 | 1 | 1 | 1 | 1 | 1 | 1 | 6/6 |
| 修改任务理解并保留修订历史 | 1 | 1 | 1 | 1 | 1 | 1 | 6/6 |
| 唯一下一步跨列表/详情/刷新一致 | 1 | 1 | 1 | 1 | 1 | 1 | 6/6 |
| 任务级草稿切换与刷新恢复 | 1 | 1 | 1 | 1 | 1 | 1 | 6/6 |
| 停止 Agent 与取消 Run 分离 | 1 | 1 | 1 | 1 | 1 | 1 | 6/6 |

## 8. L1 退出门槛

- MH-710、MH-711、MH-712 全部达到 `verified`；
- 后端新增测试覆盖规格追加、模糊阻断、同 ID 重入、错误 revision、task-bound cancel；
- 前端静态检查和 DSH adapter 测试通过；
- 真实浏览器完成创建模糊任务、澄清、任务切换草稿、刷新重入和两套取消语义；
- 1440×900 与 390×844 无横向溢出、遮挡、失效主操作或 Console error；
- 用户已于 2026-08-22 授权连续执行 L0–L5 大 Loop；因此 L1 达到 `verified` 后可以进入 L2，但在最终统一验收前仍不标记为 `accepted`。

## 9. 当前交付阻断

本地 L0 已提交为 `9a16c35`。当前 `gh auth status` 明确报告默认账号 token 无效，GitHub connector 写入也返回 403，因此远端 v0.7 分支尚未建立。该问题不阻塞 L1 本地实现，但必须与本地提交、L1 验收和远端发布分别报告。
