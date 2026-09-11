# v1.0 Conversation Native · L0 基线

记录时间：2026-08-25（Asia/Shanghai）
基线性质：本地工作区 checkpoint；不是 Release。

## 可恢复 checkpoint

- Branch：`codex/checkpoint-v1.0-l0-20260825`
- Snapshot commit：`a87cf8cceb154970ec7e40e41ab0f361260b0885`
- Tree：`d10fca8ba0cd71f13086c55f3554003cd178300f`
- Tracked binary diff SHA-256：`44a011f7cb50ea71c942f9b0da7ceb340f73dcd561d9099810c798d1e39addbc`
- Untracked manifest SHA-256：`eace89b3c318a03093b3f3d4655a740ae3de080fb7b01ec2d1e9b78205bcf731`
- Restore drill：逐一从 snapshot commit 读取全部 modified/untracked 文件并与工作区 SHA-256 比较，通过。
- Excluded：`runs/`、`.venv/`、`node_modules/`、凭证、Token、私有数据和模型缓存。

checkpoint 使用独立临时 index 创建，没有切换当前分支、修改当前 index、stash、停止服务或改变现有用户任务。创建 checkpoint 后对本文件追加的 checkpoint 元数据不属于产品代码变化。

## Git 身份

- Branch：`codex/v0.9-universal-byom`
- HEAD：`e84ac5c2607c58a7ef300bf696de32199b3a9f7b`
- 已修改文件：18
- 未跟踪文件：9
- 已跟踪 diff：1,475 insertions / 197 deletions
- `git diff --check`：通过

本轮必须保留现有工作区，不得执行 `reset --hard`、`checkout --`、破坏性清理或用测试 fixture 覆盖 canonical user tasks。

## 关键未跟踪成果指纹

| 文件 | SHA-256 |
| --- | --- |
| `model_harness/multi_agent.py` | `1e5f26514667663bb51e68afe46c0685456fb728355c993f4558b44355756370` |
| `model_harness/web/conversation-view.js` | `a44a9b234e85c1894d66ab8a1510812329aafe03b1a341af399fabf45e08b1d0` |
| `tests/test_multi_agent_runtime.py` | `797f47440e76592c943b4adaae1e0cfefe21fa5b3bdb620ac3c19bba501303a7` |
| `plans/v1.0-conversation-native/REAL-MULTI-AGENT-ACCEPTANCE.md` | `a9f14b673a2a0c68f835a4a7df60724a90915abd6ad2176bf0ce2b589a29e51d` |

其余未跟踪文件为既有 Node 对话测试、启动脚本测试以及本轮的 `EXECUTION-PLAN.md`、`FIGMA-REFERENCE.md`、`L0-BASELINE.md`。最终 checkpoint manifest 记录全部 9 个文件的大小和哈希。

这些指纹只用于发现意外覆盖；后续经批准的有意修改应记录在对应 Level 的验收证据中，而不是要求指纹保持不变。

## 回归基线

| Gate | 命令 | 结果 |
| --- | --- | --- |
| Python | `./.venv/bin/python -m unittest discover -s tests` | 418 passed |
| Node | `npm test`（`integrations/deepseek-harness`） | 41 passed |
| Project verifier | `./.venv/bin/python scripts/verify_project.py` | exit 0；Python、Node、Node syntax 全通过 |
| Patch hygiene | `git diff --check` | exit 0 |

测试数量不是不可变化的产品指标。只有在明确退役行为、迁移等价断言并登记原因时才允许删除旧断言；不得通过修改无关断言制造绿灯。

## 运行时基线

- 本地入口：`http://127.0.0.1:8802/app`
- Runtime：`available=true`
- `real_agent=true`
- Engine：`DeepSeek Harness`
- Implementation：`dsh_native_subagents`
- 对话 schema：`2.0`
- Projector revision：`2.2`
- 领域事实源：`TrainingTask`

运行时可用不等于证据投影流健康，也不等于模型训练完成；L1 将把这三类状态分离。

## 冻结的能力口径

1. 开箱真实训练：图片分类、CSV 回归。
2. 可信声明式 Recipe 注册后可训练：class-folder WAV 关键词分类。
3. 教学：内置 digits Recipe。
4. 仅诊断：任意公开 Hugging Face/GitHub 训练仓库可进入来源发现和静态可行性诊断；ASR、TTS、OCR、检测、分割等在没有已验证 Recipe/Data Adapter 时不得创建训练 Run。

界面必须分别呈现 `diagnostic_status` 与 `training_status`，不能把“诊断完成”包装成“训练完成”。

## L0 决策与完成状态

- `/chat` 采用兼容方案 A：移除关键词 `ChatController` 后保留一个版本的 HTTP 410 迁移端点；canonical 入口是 `/tasks/{task_id}/conversation/messages`。
- direct controls 仅作为 Agent 提议后的人工批准、恢复和取消动作，不形成第二套手动工作流。
- 本次交付终点是本地可审核 RC；GitHub push、CI、cold clone、Tag 与正式 Release 分别验收和授权。
- L0 Gate：通过。允许进入 L1 事实内核；不得把本地 checkpoint 或测试基线称为发布。
- 本地 8802 可用不代表 CI、cold clone、GitHub push、Tag 或 Release 已验证。
