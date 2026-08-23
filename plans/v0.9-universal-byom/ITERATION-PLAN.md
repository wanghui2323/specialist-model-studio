# Specialist Model Studio v0.9 Universal BYOM 迭代方案（纵向切片版）

本文件是给**执行型 AI 编码代理**的施工单。设计已完成，代理只实现，不决定范围、门槛或架构。

- 计划基线 commit：`49e0073`
- 权威 schema：`plans/v0.9-universal-byom/object-model.md` §3。**字段以该文件为准，不得自行发明。**
- 权威验收矩阵：`closure-matrix.md`（C01–C15）
- 权威需求：`requirements.md`

---

## 核心排期原则：纵向切片，不横向分层

原 L0–L5 是**横向分层**（来源层 → 环境层 → 构建层 → 训练层）。它的问题是：用户要等到 L4 才能在界面上看到任何东西，L1/L2/L3 只能靠读证据 JSON 验收，人工验收实际上做不了。

本方案改为**纵向切片**：每个版本都同时交付后端 + 界面，结束时用户能在浏览器里点完一条完整路径，看到真实结果或真实阻断。

三条硬规则：

1. **禁止"先把后端全做完再做前端"。** 每个版本必须自带可点击路径。
2. **每个版本的验收动作必须是用户自己能做的操作**，不是读 JSON。JSON 证据是补充，不是验收方式。
3. **v0.7 现有的三个切片（图片分类、CSV 回归、WAV 关键词）必须全程保持可用。** BYOM 是新增入口，不是替换。任何版本导致现有功能回归即视为失败。

`closure-matrix.md` 的 C01–C15 仍然是权威验收矩阵，只是**交付顺序**改了。下表给出映射。

---

## 版本路线图

| 版本 | 用户能看到什么 | 闭环流程 | 预估 | 累计 |
| --- | --- | --- | ---: | ---: |
| **V0** | 无（合同修订） | — | 1–1.5h | 1.5h |
| **V1** | 粘贴 HF/GitHub 地址 → 看到不可变 commit、许可、文件清单 | C01–C04 | 5–8h | 9.5h |
| **V2** | 看到仓库分析：框架、训练入口、数据格式、危险动作，每条带文件引用 | C05 | 4–6h | 15.5h |
| **V3** | 看到"这台机器能不能训练它"+ 降级建议 → **首个完整可交付产品** | C06、C07、C15 | 8–12h | 27.5h |
| **V4** | 看到隔离自检结果：容器可用性、7 项隔离检查 | C07 扩展 | 8–14h | 41.5h |
| **V5** | 看到容器里真实跑出来的日志流 | C08 | 10–16h | 57.5h |
| **V6** | 看到"隔离验证报告"：7 类越权全部被拦截 | C08 负例 | 8–12h | 69.5h |
| **V7** | 看到资格试跑 7 项检查的真实结果 | C09、C10 | 10–16h | 85.5h |
| **V8** | 资格通过 → 注册能力 → 回到原任务继续导入数据 | C11 | 6–10h | 95.5h |
| **V9** | 完整正式训练、评测、推理、交付包 | C12–C14 | 15–25h | 120h |
| **V10** | 盲测第三个模型 + 冷克隆 + 发布 | 全部复验 | 10–20h | 140h |

**V3 是第一个可以停下来对外交付的版本**（累计 ~28 小时，三到四个工作日）。到那时产品能回答"我能不能训练这个模型、需要什么条件"，全程零不可信代码执行。V4 之后才进入执行不可信代码的领域，风险和成本都跃升一个量级。

### 本文件的详细程度是刻意递减的

V0–V2 给完整施工细节。V3 给结构和门禁。V4–V10 只给目标、验收动作和已定门禁。

原因：在 Worker 协议真实跑通之前细化 V7 的任务，只会产出与实际协议不符的虚构内容。**每验收完一个版本，回来找用户细化下一个。**

---

## 用户已冻结的三项决定

1. **不做 Agent 自动修复 Loop**（原 MH-931 取消）。构建失败时系统如实报告证据和建议，由**人工**决定修改后创建新 `BuildAttempt`。`patch_origin` 只允许 `"human"`。
2. **v0.9 容器内 CPU-only。** `ResourceProbe` 仍探测 MPS/CUDA/显存，但必须标记为"检测到但 v0.9 不可用"并说明原因（macOS 上 OCI 容器是 Linux VM，无法访问 Metal）。不得因宿主有 GPU 就宣称可用。
3. **`AGENTS.md` 随本版本修订**（见 V0）。

---

## 0. 给执行代理的硬性规则

优先级高于任何单个任务描述。违反任何一条即视为本次改动失败。

1. **一次只做一个任务。** 做完、跑通验收门、按第 8 条格式报告，然后**停下等指令**。
2. **一次只做一个版本。** 一个版本内的所有任务完成并经用户浏览器验收后，才能开始下一个版本。
3. **不要扩大范围。** 只改任务点名的文件。发现别的问题记录汇报，不要顺手改。
4. **不要发明 schema。** 字段去 `object-model.md` §3 查。需要新字段时**停下来问**。
5. **不要改验收门槛、测试断言或矩阵分数。** `closure-matrix.md` 的"当前"列只能由对应 `lN-evidence.json` 更新，禁止因代码提交就改成 6/6。唯一例外是任务明确要求"新增测试"。
6. **不要碰**：`acceptance/v0.7-gates.json`、`plans/v0.9-universal-byom/acceptance-contract.md`、任何已有测试的断言内容。
7. **每个任务结束必须跑** `.venv/bin/python -m unittest discover -s tests`。基线 **194 个通过**。测试数只能增加。
8. **报告格式固定：**
   ```
   版本 / 任务编号：
   改了哪些文件（含行号范围）：
   验收门命令与输出（原样粘贴）：
   单测结果：Ran N tests / OK 或 FAILED
   用户需要在浏览器里验收什么（具体步骤）：
   我拿不准或需要你决定的地方：
   ```
9. **禁止假成功。** 不允许模拟进度、固定计时器、装饰性日志冒充事实、把阻断包装成成功、把 `implemented` 写成 `verified`。这是本项目的核心产品承诺。
10. **标记"真实联网"的任务必须真的联网。** mock 测试保留在单测里，真实验收另走脚本，不允许用 mock 通过。
11. **不确定就停下来问。** "门槛设多少""策略选哪个""要不要加字段"都是人工决定。

---

# V0 · 合同修订（1–1.5h）

L0 当前标记 `verified`，但 `49e0073` 只改了 `plans/` 和一个脚本，没修订 `AGENTS.md`。`AGENTS.md` 是每次代理会话强制注入的规则，现在与 v0.9 合同直接冲突——后续任何执行代理都会同时收到计划和禁止该计划的指令。

**先把 `loop-tasks.json` 的 L0 状态从 `verified` 改回 `implementing`**，V0 全部完成后再改回。

---

## V0-1 · 修订 `AGENTS.md`

三处冲突（第 10–12 行）：

- 第 11 行 `Do not imply arbitrary Hub model fine-tuning or deployment support.` ↔ R1 要求任意 HF 仓库进入训练协议
- 第 12 行 `arbitrary generated Python Recipes ... explicitly unsupported` ↔ R5 要求注册动态 `RecipeVersion`
- 第 10 行 v0.7 三切片基于 `trusted declarative RecipeFactory registration` ↔ v0.9 来源是任意第三方仓库

注意第 12 行原文留了合法出口：`until each has a tested Recipe, Data Adapter, evidence path, and product loop`。v0.9 正是要建立那条证据路径，所以修订方式是**把"禁止"改成"仅经隔离 Worker 路径且满足门禁时支持"，不是删掉边界**。

把第 10–12 行整体替换为：

```markdown
- v0.7 Beta has three real user-data vertical slices: image-folder classification, CSV tabular regression, and class-folder WAV keyword classification after a trusted declarative RecipeFactory registration. The built-in digits Recipe remains teaching-only. These slices stay supported unchanged in v0.9.
- v0.9 adds Universal BYOM: an arbitrary public Hugging Face or GitHub training repository may enter the `discover → analyze → plan → resource check → isolated build → qualification → register → train` protocol. Support means the repository reaches one of two honest terminal states: a real trained model, or a typed `BlockerEvidence` explaining why this machine cannot train it. It does not promise every repository will train successfully.
- Third-party repository code, install scripts, and human-authored repair patches may only execute inside an OCI container or a worker with equivalent file, process, network and resource isolation. A plain host subprocess is never an acceptable execution backend. Without a verified isolation runtime the system must analyze only and record `blocked_environment`.
- A dynamic RecipeVersion may only be registered after a real QualificationRun passes all declared checks and a human approves that exact evidence digest. Agents may propose new BuildAttempts but must never generate repair patches autonomously, overwrite prior evidence, lower a human gate, or widen execution permissions.
- v0.9 executes CPU-only inside the isolation boundary. ResourceProbe still detects MPS/CUDA/VRAM, but ResourceFitReport must mark accelerators as detected-but-unusable-in-v0.9 and say why. Never claim GPU acceleration because the host has a GPU.
- Keep OCR detection/recognition, ASR, TTS/voice cloning, object detection, segmentation, forecasting, cloud/GPU orchestration, and production deployment explicitly unsupported until each has a tested Recipe, Data Adapter, evidence path, and product loop.
```

其余行**保持不变**。特别不要删除关于私有数据、凭据、`runs/`、数据集安全检查的任何一行——那些边界 v0.9 继续有效。

### 验收门

```bash
rg -n 'Do not imply arbitrary Hub model fine-tuning|arbitrary generated Python Recipes' AGENTS.md
#    期望：空
rg -c 'OCI container or a worker with equivalent|QualificationRun passes|CPU-only inside the isolation boundary' AGENTS.md
#    期望：3
rg -c 'image-folder classification, CSV tabular regression' AGENTS.md
#    期望：1
```

---

## V0-2 · 把两项决定写进合同

`requirements.md` §3（第 40–45 行）末尾追加：

```markdown
5. **修复责任**：构建失败时系统只产出证据和可执行建议，由人工决定修改计划、参数、数据或环境后创建新的 `BuildAttempt`。v0.9 不实现 Agent 自动补丁 Loop；Agent 可以提出新 attempt，但不得自动生成代码补丁、覆盖既有证据、降低人工门槛或扩大执行权限。
6. **加速器口径**：v0.9 在隔离边界内一律 CPU 执行。`ResourceProbe` 仍探测 MPS/CUDA/显存，但 `ResourceFitReport` 必须标记为"检测到但 v0.9 不可用"并给出原因（OCI 容器在 macOS 上无法访问 Metal）。资格试跑与正式训练的资源预算必须按 CPU 能力设定。禁止因宿主存在 GPU 而宣称可用。
```

R4 删除第 78 行 `- Agent 只能提出新 attempt，不能覆盖先前证据、降低人工门槛或自动扩大权限。`，替换为：

```markdown
- 构建失败必须产出 BlockerEvidence 与可执行修复建议；补丁由人工提供，每个补丁产生独立 BuildAttempt 并记录 patch_sha256、patch_origin="human" 与 parent_attempt_id。系统不得自动生成或自动应用补丁。
```

`closure-matrix.md` 第 40 行 C09 整行替换为：

```markdown
| C09 | 构建失败 → 人工修复 → 新 attempt | 新建 child `BuildAttempt` 与 patch digest | 父子 attempt 历史不被覆盖 | 所有 attempt 仍属于原 task | 可从任意失败证据恢复，选择修复或放弃 | 系统不得自动改补丁/降门槛/扩权限；无人工批准不得执行 | 补丁校验失败、重复补丁、取消 | 0/6 | 6/6 | parent ID、patch diff/hash、人工批准记录、拒绝结果、恢复结果 |
```

`object-model.md` 两处：`BuildAttempt`（第 157 行）`patch_sha256` 后追加 `"patch_origin": "human"` 与 `"patch_approval_id": "approval_*"`，并在该 schema 下方注明 `patch_origin 在 v0.9 只允许 "human"，写入 "agent" 或 "auto" 必须被校验拒绝`；`EnvironmentLock`（第 122 行 `execution_backend` 后）追加 `"accelerator_policy": {"mode": "cpu_only", "detected": [], "unusable_reason": "..."}`。

### 验收门

```bash
rg -c '修复责任|加速器口径' plans/v0.9-universal-byom/requirements.md   # 期望 2
rg -n 'Agent 只能提出新 attempt' plans/v0.9-universal-byom/requirements.md  # 期望空
rg -n 'Agent 修复 Loop' plans/v0.9-universal-byom/closure-matrix.md         # 期望空
rg -c 'patch_origin|accelerator_policy' plans/v0.9-universal-byom/object-model.md  # 期望 ≥4
.venv/bin/python scripts/verify_v09_l0.py; echo "exit=$?"                   # 期望 0
```

完成后把 `loop-tasks.json` 的 L0 改回 `verified`（**不是 `accepted`**，那需要用户确认证据），重新生成 `l0-evidence.json` 写入新 commit，提交。

---

# V1 · 粘贴地址就能看到模型来源（5–8h）

**用户可见结果**：在界面上粘贴一个 Hugging Face 或 GitHub 地址，看到系统真实解析出的不可变 commit、许可判定、文件清单和仓库大小。粘一个不存在的或私有的仓库，看到明确的阻断原因和重试入口。

**为什么这是第一个版本**：L1 后端代码已经写完了（`model_sources.py` 457 行、`model_source_store.py` 1638 行、`github_source.py` 388 行、`huggingface_source.py` 293 行），194 个单测通过。缺的只有两件事——真实联网证据和界面。所以这是投入产出比最高的一刀。

对应 C01–C04。

---

## V1-1 · 真实联网验收脚本

**当前问题**：`test_model_source_providers.py` 有 14 处 mock、`test_model_source_api.py` 有 3 处，`github_source.py` 把 origin 钉死在 `api.github.com`。**目前没有任何证据证明真实 API 行为。** 未验证的至少包括：tag→commit 真实解析、429 限流、401 私库、重定向、LFS 指针、大仓库超时。这些大概率会反过来改 Provider 协议，所以必须在写界面之前撞完。

新建 `scripts/verify_v09_l1_live.py`。**不进 CI**（CI 无凭据且会被限流），人工在验收机器上执行。

行为契约：

1. 需要 `MH_LIVE_ACCEPTANCE=1` 才运行，否则打印跳过原因并退出 0。
2. 正例 A（HF）：解析一个公开小仓库的 **tag** 到不可变 commit，建立 `SourceSnapshot`，断言 `resolved_commit` 是 40 位 SHA、`manifest_sha256` 非空、`license.decision` 有值。
3. 正例 B（GitHub）：同上，解析 **branch** 到 commit。
4. 每个正例重跑一次，断言 `manifest_sha256` 与首次完全一致（证明快照可复现）。
5. 进程重启后从存储重读，断言 snapshot ID 与 commit 不变。
6. 结果写入 `l1-evidence.json`，含真实 commit、请求 URL、HTTP 状态、耗时。
7. 任一断言失败即非零退出，且**不写** `verified`。

选仓库的硬约束：小于 50MB、许可明确、有 tag。**具体选哪个由你提议，在报告里说明理由并等用户确认后再写入证据文件。**

### 验收门

```bash
MH_LIVE_ACCEPTANCE=1 .venv/bin/python scripts/verify_v09_l1_live.py; echo "exit=$?"
#    期望 exit=0，l1-evidence.json 含两个真实 40 位 commit
.venv/bin/python scripts/verify_v09_l1_live.py; echo "exit=$?"
#    期望 exit=0 且打印跳过（未设环境变量时绝不联网）
```

---

## V1-2 · 真实负例

`closure-matrix.md` §4 的 L1 门禁要求这些负例。加进同一脚本，每条真实触发：

1. **不存在的仓库** → 404，产生 `blocked_repository`，不留下可训练状态。
2. **私有仓库无权限** → 401/404，产生 `blocked_repository`，错误信息**不泄露凭据**。
3. **无效 revision** → 产生 `blocked_repository`，**不得静默回落到默认分支**。这条最重要：静默回落到 `main` 是最危险的失败模式，用户会以为训练的是自己指定的版本。
4. **限流** → GitHub 未认证配额 60 次/小时，故意打满，断言得到 403/429 后产生 `retryable: true` 的 blocker，而不是伪装成"仓库不存在"。
5. **未知许可** → 找一个无 LICENSE 的公开仓库，断言 `license.decision` 为 `review` 或 `deny`，且**阻断后续分析**（`object-model.md` §6 状态守卫要求"许可不是 deny"才能分析）。
6. **hash mismatch** → 下载后人为改一个字节再校验，断言检测到并阻断。

**限流负例放最后跑**——打满配额后一小时内无法再做联网验收。

### 验收门

```bash
MH_LIVE_ACCEPTANCE=1 .venv/bin/python scripts/verify_v09_l1_live.py --negatives; echo "exit=$?"
#    期望 exit=0，6 条负例全部按预期分类
rg -c 'blocked_repository|blocked_license' plans/v0.9-universal-byom/l1-evidence.json
#    期望 ≥ 2
```

---

## V1-3 · 来源绑定界面

这是让 V1 变成"可用版本"的关键任务。**不要新建一套前端**，接进现有 `model_harness/web/`。

界面要求：

- 现有任务创建流程里新增一个入口："我有模型地址"，与现有"描述业务目标"并列。
- 输入框接受 HF 和 GitHub 两种 URL 形式，粘贴后显示解析中状态（真实请求，不是动画）。
- 解析成功后展示：provider、`owner/name`、**requested revision 与 resolved commit 并列**（这一对必须都显示，才能让用户看出"我写的是 main，系统钉的是这个 commit"）、许可 SPDX 与判定、仓库大小、文件数、`manifest_sha256`、是否声明 remote code。
- 解析失败展示 `BlockerEvidence`：类型、检测值、原因、恢复建议、重试按钮。
- 复用 v0.8 已建立的界面规范：字号不低于 12px、结论徽章由真实状态驱动、按钮直连 API 不经 LLM、轮询串行化。**这些是 v0.8 已经修好的问题，不要退回去。**

沿用现有 `task_id`——绑定来源不创建新任务对象。

### 验收门

```bash
# 静态：不得有硬编码模型 ID（这是 L5 的硬门禁，从 V1 就开始守）
rg -n 'bert|resnet|gpt2|llama' model_harness/web/app.js
#    期望：空

# 字号回归（沿用 v0.8 的检查）
rg -n 'font-size:(6|7|8|9|10|11)px' model_harness/web/styles.css
#    期望：空

.venv/bin/python -m unittest discover -s tests
```

### 用户浏览器验收（V1 的真正验收方式）

```bash
.venv/bin/python -m uvicorn --factory model_harness.server:create_app --host 127.0.0.1 --port 8799
```

用户在 1440×900 和 390×844 两个视口各做一遍：

1. 粘一个 HF 地址 → 看到 resolved commit 是 40 位 SHA，且与自己输入的 tag/branch 并列显示
2. 粘一个 GitHub 地址 → 同上
3. 粘一个不存在的仓库 → 看到明确阻断原因和重试按钮，不是白屏或通用报错
4. 粘一个私有仓库 → 看到权限不足，且页面上**看不到任何凭据信息**
5. 刷新页面 → 来源绑定仍在，commit 不变
6. 重启后端进程 → 从任务列表重新进入，commit 仍不变

**任何一条不通过，V1 不算完成。**

---

## V1-4 · 归档证据

1. C01–C04 按 `closure-matrix.md` §5 模板写入 `l1-evidence.json`，含 `source_commit`、六个布尔项、`score`。
2. **`score` 必须由脚本从六个布尔项算出，禁止手写 6**（矩阵 §5 明文要求）。
3. 更新矩阵"当前"列——**只改 C01–C04**，其余保持原值。
4. `loop-tasks.json` 的 MH-910、MH-912 改 `verified`。**不写 `accepted`**，那要用户确认。

### 验收门

```bash
.venv/bin/python -c "
import json; d=json.load(open('plans/v0.9-universal-byom/l1-evidence.json'))
flows={f['flow_id']:f for f in d['flows']}
assert set(flows) >= {'C01','C02','C03','C04'}, set(flows)
dims=['object_effect','persistence','identity_continuity','reentry_recovery','state_guard','error_cancel']
for k,f in flows.items():
    got=sum(1 for x in dims if f[x]['passed'])
    assert f['score']==got, (k, f['score'], got)
print('C01-C04 score 与布尔项一致')
"
```

---

# V2 · 看懂这个仓库（4–6h）

**用户可见结果**：来源绑定后，界面展示系统对仓库的静态分析——用什么框架、训练入口在哪个文件、需要什么数据格式、有哪些危险动作。每一条都带**具体文件和 commit 引用**，不是自然语言猜测。

`repository_analysis.py` 已有 609 行，`test_repository_analysis.py` 已有 207 行。这一版主要是补全分析维度和接界面。

对应 C05。

## 任务

**V2-1 分析结果补全**：按 `object-model.md` §3 `RepositoryAnalysis` schema 补齐 `frameworks`、`task_candidates`、`entrypoints`、`data_contract_candidates`、`dependency_files`、`metrics`、`artifacts`、`risk_findings`。硬要求：**每条结论必须有 `evidence_refs` 指向 `文件:行号`**，`requirements.md` R2 明文禁止只给自然语言猜测。缺入口、解析失败、许可 deny 时状态分别为 `needs_input` / `failed` / `blocked`。

**V2-2 分析界面**：展示上述字段，`risk_findings` 单独成区并显著标记（用户要据此决定是否授权执行）。`needs_input` 时提供补充信息后重试的入口。

**V2-3 负例**：许可 deny 的快照不得产生 `complete` 分析（§6 状态守卫）；损坏快照、缺训练入口、分析中取消，各一条。

### 用户浏览器验收

1. 绑定一个标准 HF 仓库 → 看到框架、训练入口文件名、数据格式，每条能点开看到引用的文件和行号
2. 绑定一个含 `trust_remote_code` 或安装脚本的仓库 → 危险动作被显著标出
3. 绑定一个无训练代码的仓库（如纯权重仓库）→ 看到 `needs_input` 或明确阻断，不是假装分析成功
4. 刷新和重启后分析结果一致

---

# V3 · 这台机器能不能训练它（8–12h）

**用户可见结果**：看到本机真实资源（CPU、内存、磁盘、加速器、容器运行时可用性）、这个训练计划需要什么、以及结论——可训练 / 可训练但需调整（附具体降级方案）/ 阻断（附检测值和原因）。

**V3 完成时产品就可独立交付了。** 它回答"我能不能训练这个模型、需要什么条件"，全程零不可信代码执行。对目标用户（有业务目标和数据、没有训练工程能力）来说这可能是价值最高的问题。

对应 C06、C07、C15。

## 任务概要

**V3-1 `TrainingPlanRevision` 与 digest 审批**：`plan_sha256` 必须是 canonical JSON（`sort_keys=True`、固定分隔符）的 sha256，否则字段顺序变化就会改 digest——这一点必须在实现里写死并有测试。任何参数/权限/门槛变化产生新 revision，`parent_revision_id` 成链，旧的标 `superseded`，**禁止就地改写**。`ApprovalRecord` 只绑定 `(subject_type, subject_id, digest)`，展示的 digest 与批准的 digest 必须同值。必须有篡改测试：批准后直接改磁盘上的 plan JSON → 后续动作拒绝并要求重新批准（与 v0.8 T10 的合同绑定同一模式）。

**V3-2 真实 `ResourceProbe`**：OS/架构、CPU、RAM、磁盘、Python/Node、容器运行时可用性、加速器。**按冻结决定 2**，探测到 MPS/CUDA 时必须写 `accelerator_policy: {"mode": "cpu_only", "detected": ["mps"], "unusable_reason": "..."}`。docker 不可用时返回 `available: false` 带原因，**不抛异常**。

**V3-3 `EnvironmentLock`**：`lock_sha256` 同样是 canonical JSON 的 sha256。`base_image_digest` 必须是 `sha256:...` 形式的**镜像 digest 而非 tag**——tag 会漂移，与整个版本的不可变前提冲突。校验拒绝：tag 形式的镜像、含 `*` 的 network allowlist、缺 version/hashes 的包、`mode` 不是 `cpu_only`。

**V3-4 `ResourceFitReport`**：`reasons` 每条必须同时有 `required`、`observed`、`evidence_ref`——"资源不足"没有数字就不是证据。`alternatives` 至少一个可行降级（batch、精度、梯度累积、LoRA、更小模型）且 `creates_new_plan: true`。`blocked_*` 时禁止创建 `BuildAttempt` 和 `TrainingRun`（§6 守卫），并按 C15 产生 `BlockerEvidence`。

**V3-5 界面 + C15 阻断呈现**：把上述三份报告做成用户能读懂的页面。阻断必须显示 detector、事实值、阈值、恢复动作、能否重试。**沿用 v0.8 已确立的原则：结论徽章由真实状态驱动，不许指标门槛冒充结论。**

**V3-6 `verified` 失效机制**：`requirements.md` §6 声明"代码变化使受影响层 `verified` 失效"，但目前没有任何东西执行这条——它只是一次性写死的字符串。新建 `scripts/check_v09_status.py`：每个 `lN-evidence.json` 记 `source_commit` 与 `owned_paths`，用 `git diff --name-only <commit>..HEAD -- <paths>` 检查；有变化则该层必须降级，脚本非零退出。**只报告，不自动改** `loop-tasks.json`（状态变更是人工动作）。到 V3 已有三层证据，这个机制开始有实际作用。

### 用户浏览器验收

1. 看到本机真实资源数字（与 `top`/`df` 对得上）
2. 有 MPS 的机器上看到"检测到 MPS，但 v0.9 不可用"及原因，**不显示 GPU 加速可用**
3. 一个合理计划 → 结论"可训练"
4. 一个荒谬计划（如要求 999GB 内存）→ 阻断，带 required/observed 两个数字
5. 关掉 docker → 看到 `blocked_environment`，且**训练按钮不可用**
6. 采纳一个降级建议 → 产生新计划版本，旧批准显示已失效
7. 重启后全部可恢复

**V3 验收通过后停下来找用户**，决定是继续 V4 还是先交付这一版。

---

# V4–V10 · 待前一版验收后细化

以下只给目标、验收动作和已定门禁。**不要现在开始做。**

## V4 · 隔离自检（8–14h）

**用户可见**：一个"执行环境"页面，显示容器运行时是否可用、镜像 digest、以及隔离自检各项结果（只读挂载、网络拒绝、资源上限、强杀能力）。自检失败时明确告知不能执行来源代码。

**这里是全项目风险最高的转折点。** 代码库目前**没有任何进程隔离基础设施**——搜 `docker|podman|OCI|subprocess|Popen|seccomp|cgroup|setrlimit` 在 `model_harness/` 只命中两处字符串常量（`repository_analysis.py:530` 和 `recipe_factory.py:59` 的危险模式黑名单），没有一处真实子进程执行。现在的训练全在主进程内跑。所以这是从零建设。

**止损规则**：V4 超过 **12 小时**仍未通过验收就停下汇报，不要继续往下堆。此时正确动作是启用 `requirements.md` 边界 #2 已定义的降级模式（不执行来源代码，只分析并返回 `blocked_environment`），把 V3 那一版作为交付版本，由用户决定是否继续投入。

硬约束：都没有容器运行时时返回 `blocked_environment`，**绝不回落到宿主子进程**（边界 #2 明文禁止）。

## V5 · 容器里真实跑起来（10–16h）

**用户可见**：点"开始构建"，看到容器里真实产生的日志流，退出码、耗时、资源占用都是真的。

按 `object-model.md` §7 实现 NDJSON 协议。**§7 的失败关闭要求是硬性的**：缺序、重复 `event_id`、未知必填字段、digest 不一致必须使消费者失败关闭，不得静默忽略。这是 v0.7 那个"解析装饰性终端文本当事实"问题的根治。

## V6 · 隔离验证报告（8–12h）

**用户可见**：一个报告页，7 类越权尝试全部显示被拦截。

先在 `tests/fixtures/hostile_repos/` 建 7 个极小的攻击样本（路径逃逸、宿主 socket、未批准网络、fork bomb、无限循环、内存耗尽、凭据外泄），**离线、确定、可重复**，不要从网上抓恶意仓库。每个 fixture 配 README 说明测什么、为什么无害。

每条负例必须断言四件事：状态正确、产生 `BlockerEvidence`、**宿主未受影响**（目标路径不存在、无残留进程、宿主文件未改）、不产生任何成功产物。**只断言"抛了异常"而不断言宿主未受影响的测试不算完成。** 这 7 个测试是隔离层的全部价值所在。

## V7 · 资格试跑（10–16h）

**用户可见**：7 项检查（`data_load`、`train_step`、`metric_parse`、`artifact_save`、`artifact_reload`、`single_inference`、`isolation`，字段名以 `object-model.md` §3 为准）的真实结果，以及失败时的人工修复入口。

**按冻结决定 2**，预算按 CPU 设定：1–5 步、极小样本、wall time ≤ 300 秒。预算给大了在 CPU 上根本跑不完。

人工修复流程（取代原 MH-931）：失败产出证据和建议但**不自动应用**；补丁必须 `patch_origin: "human"` 且有 `patch_approval_id`；每个补丁产生 child attempt，父 attempt 永不覆盖。

## V8 · 注册与恢复（6–10h）

**用户可见**：资格通过 → 批准 → 注册能力 → **回到原任务**继续导入数据。

硬门禁：注册后 `task_id` 不变，**不得创建第二套"模型项目"**（R5 明文禁止）。

## V9 · 正式训练闭环（15–25h）

**用户可见**：导入真实数据 → 冻结合同 → 正式训练 → 评测 → 推理 → 下载交付包。

硬门禁（`closure-matrix.md` §4）：**前端代码不得存在验收用模型 ID 的专用条件分支**。建议做成静态检查脚本进 CI，把验收模型 ID 作为禁用字符串扫 `model_harness/web/`。

## V10 · 盲测与发布（10–20h）

**用户可见**：一个开发期从未用过的第三方模型，不改核心代码即完成流程。

有一条容易忽略的前置：`release_tiers` 把 `github_ci_verified` 和 `github_released` 定义为独立层级，要求"远程同一 commit 的 required checks 通过"和"GitHub API 验证 merge、精确 tag、公开 Release 及制品哈希"。但当前 CI 只跑 Python 单测 + Node adapter，**联网验收、浏览器、冷克隆都不在 CI 里**。要么扩 CI，要么在证据里如实标注这些门禁是本地执行的。这个决定留到 V10。

---

## 附录 · 单测基线

| 时点 | 期望测试数 |
| --- | ---: |
| 起点（`49e0073` + L1 工作树） | 194 |
| V0 完成 | 194（只改文档） |
| V1 完成 | 194（联网验收走脚本，不进单测） |
| V2 完成 | 约 205 |
| V3 完成 | 约 235 |
| V4 完成 | 约 245 |
| V6 完成 | 约 260 |
| V7 完成 | 约 280 |

数字只能增加。任何一步测试数下降或出现失败，停下汇报，不要继续。
