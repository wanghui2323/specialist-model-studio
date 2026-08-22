# Model Harness v0.7 · L2 声明式 Recipe Factory

> 状态：`implemented`（核心对象与后端纵向已实现，尚未经 v0.7 L0–L5 聚合验收）  
> 执行授权：2026-08-22 连续 L0–L5 大 Loop  
> 首个动态扩展家族：已切分 WAV 语音关键词分类  
> 明确范围外：ASR、TTS、流式唤醒词部署、在宿主机执行 Agent 生成的任意 Python。

## 1. 用户结果

一个确认后的语音关键词分类任务，在没有现成训练方案时，可以在同一 `task_id` 内完成：

```text
安全暂存样例
→ 创建 BuildAttempt
→ 提交受约束 RecipeSpec(JSON)
→ 可信引擎验证
→ 用户批准原子注册 RecipeVersion / AdapterVersion
→ 原任务 Resume 到 awaiting_data
→ 正式数据导入、合同确认、真实训练、独立评测与产物
```

注册成功前不得创建 Run；暂存样例不得自动变成正式训练数据。

## 2. 安全边界

当前环境没有通过自检的 OCI 容器运行时，`sandbox-exec` 也不可用。因此 v0.7 只执行后端内置可信原语，不加载或执行生成代码。

允许的声明式规格：

- `engine = sklearn_audio_keyword_v1`；
- 受控 WAV 读取与 16kHz 单声道标准化；
- allowlist 特征参数与候选模型；
- 受控训练时长、样本数、文件数和输出大小。

禁止：Python、Shell、URL、动态依赖、宿主路径、动态 import、Pickle 输入和 `trust_remote_code`。任意代码构建必须返回 `blocked_environment`。

## 3. 权威对象

| 对象 | 稳定身份 | 关键状态 |
|---|---|---|
| StagedDataAsset | `asset_id` | staged / quarantined / consumed / superseded |
| RecipeBuildRequest | `request_id + spec_revision` | awaiting_samples / ready_to_build / resolved / superseded |
| BuildAttempt | `attempt_id` | authoring / validating / awaiting_registration / registered / failed / cancelled / registration_rejected |
| RecipeCandidate | `candidate_id + sha256` | immutable |
| ValidationReport | `report_id` | passed / failed，逐 gate 保存证据 |
| RecipeVersion | `version_id + candidate_digest + validation_digest` | 不可变版本记录；不在记录本身改写 active/revoked |
| AdapterVersion | `version_id + candidate_digest + validation_digest` | 不可变版本记录；不在记录本身改写 active/revoked |
| ActiveVersions projection | `task_id` | 任务级 recipe_version_id / adapter_version_id 激活投影 |
| RegistrationIntent | `intent_id` | awaiting_approval / applying / registered / rejected / recovery_required |

TaskSpec 变化会让旧 BuildAttempt 和 Candidate 失效；注册必须校验 `base_spec_revision`、candidate digest、ValidationReport 与明确批准。

`blocked_environment` 是 `BuildAttempt.status = failed` 下的结构化 `failure.code`，不是第二套状态机。`cancelled` 只允许从 `authoring` 进入；进入 `validating` 后由可重放验证流程收敛。注册回调必须按 `intent_id` 幂等，崩溃后由 `recovery_required` 重放，只有回调成功才更新任务级激活投影。

## 4. 音频训练合同

正式数据是类别目录 ZIP：

```text
dataset.zip
  yes/*.wav
  no/*.wav
  unknown/*.wav
```

Speech Commands 风格文件名用于提取 speaker id，并按 speaker 分组隔离 train / validation / test。仅接受可解码 PCM WAV；拒绝路径穿越、符号链接、加密 ZIP、压缩炸弹、跨标签重复、损坏音频和不合理时长。

可信引擎使用 SciPy 音频特征和 scikit-learn 候选模型；只按验证集选模，最后一次打开独立测试集。产物至少包含模型、标签映射、特征配置、评测指标、失败样本摘要、模型卡和深度验证报告。

## 5. 当前 API 暴露边界

产品 HTTP 层当前已暴露：

```text
POST /tasks/{task_id}/staged-assets
GET  /tasks/{task_id}/staged-assets
GET  /tasks/{task_id}/staged-assets/{asset_id}

POST /tasks/{task_id}/recipe-builds
GET  /tasks/{task_id}/recipe-builds
GET  /tasks/{task_id}/recipe-builds/{attempt_id}
POST /tasks/{task_id}/recipe-builds/{attempt_id}/register
POST /tasks/{task_id}/recipe-builds/{attempt_id}/reject
```

核心 `RecipeFactory` 已提供 `events()`、`cancel()`、`recover_incomplete()` 和 `recover_registrations()`，但当前 HTTP 路由未对外暴露独立 events/cancel/recovery 操作。因此这些能力只能作为核心测试证据，不能在浏览器验收前宣称为已验证用户功能。

## 6. L2 退出门槛

1. 样例暂存：对象持久、刷新可重入、恶意 ZIP/WAV 被拒绝、`run_ids` 不变；
2. BuildAttempt：真实状态与事件、失败/取消/重启恢复，不用动画模拟；
3. Register/Resume：同一 task_id、精确版本与摘要、事务恢复、拒绝和失败零 active version；
4. 真实语音闭环：正式 WAV ZIP、合同确认、真实训练、独立评测、模型产物和深度验证；
5. 任意生成代码路径保持 `blocked_environment`，不因“大 Loop”授权而放宽安全边界。

当前判定是 `implemented`，不是 `verified` 或 `accepted`。只有定向负例、真实音频训练、进程重启与两视口用户旅程都进入同一份 commit-bound 验收报告后，才能升级状态。
