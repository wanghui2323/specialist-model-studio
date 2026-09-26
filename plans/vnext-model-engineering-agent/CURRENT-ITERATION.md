# 当前迭代：可靠任务生命周期与执行边界

更新：2026-09-12。基线提交：`ee17ed94d1c91e6352d79baa68219feb80af3a8f`。本页是本方向实施状态的唯一记录；路线图描述目标，不代表已经实现。第 2–5 节保留上一轮证据，第 6 节记录 ModelTrial，第 7 节记录 WorkBuddy 交互对齐。

## 1. 本轮结论

已实现并完成本地测试与 PC 浏览器核验的切片：**任务归档 → 找回 → 只读查看 → 恢复原任务**。同时修复研究子 Agent 暴露根协调器专属工具的矛盾，并验证旧会话识别不放宽权限。

随后用户批准本机隔离环境安装与 CPU 外部模型验证，并允许资源不足时考虑火山引擎。已安装独立命名的本地 OCI 环境，并完成固定公开 ONNX 模型的容器内匿名下载和断网真实推理。它是执行后端的独立可行性证据，不是 Studio 的 `ModelTrial`、训练 Run 或动态资格注册；详细配置、重启复验与边界见第 4 节。

2026-09-12 新增独立 ModelTrial + OCI Job 首版，已通过兼容 ONNX 的产品 API → 真实 CPU 推理 → 持久结果链路；执行器另经真实 `sleep` 作业验证取消、超时与遗留作业停止。API 执行验收预置已绑定公共资产并使用**模拟原生审批事件**，不能据此宣称真实来源绑定、DSH 审批或执行中 ONNX 取消已验收。PC 新增直达试跑入口、保存计划、历史/取消和刷新找回；详见第 6 节。

这属于 M0-01、M0-03 及 M1 的部分交付。**M0、M1 整体尚未验收；M2–M5 未交付，不是通用模型工程 Agent 最终版。** 动态环境构建、任意外部模型适配训练、GPU Worker、可信改进闭环、真实对话交互对标、Git/生产发布仍未完成。

## 2. 实际改动

| 问题 | 现在的行为 | 代码与边界 |
| --- | --- | --- |
| 任务归档后没有产品找回入口 | 左侧“当前任务 / 已归档”；旧任务深链接可打开，刷新仍回到同一任务；空列表解释去向 | `web/index.html`、`web/app.js`；没有合成 task_id 或重建任务 |
| 恢复含义不明确 | `POST /tasks/{task_id}/restore` 只解除归档；重复恢复幂等，不启动 Agent/Run、不重发授权 | `workspace.py`、`server.py`；数据、合同、审批与历史证据保留 |
| 归档时仍有正在执行的动作 | 运行、排队、等待决定、取消未收敛、领域 worker 存活或状态无法核验时返回 409；在途 HTTP 写入与归档提交互斥 | 不把断线当作空闲，不在等待外部请求时持有线程锁 |
| 归档后页面/旧标签还能发起写入 | 对话输入与写操作隐藏；历史待决卡保留但不可操作；服务端统一拒绝归档任务 HTTP 写入 | 保留 GET 阅读和 archive/restore；消费下载授权的 POST 也需先恢复；不宣称任意内部 Python SDK 全部只读 |
| 旧响应覆盖新状态或干扰另一任务 | 按 task 的归档 epoch 拒绝旧 GET；selectionToken 与列表范围修订避免迟到响应改变新视图；失败不乐观恢复 | 不废弃另一任务的 GET；旧请求退出后继续正常轮询；通知标明所属任务 |
| 研究角色可见工具与权限冲突 | 新 research profile 不含来源选择、绑定、HF 资产接入 3 个 root-only 工具；根协调器发起批准 | JS/YAML 同步；旧版精确 profile 仅用于识别历史身份，执行仍按当前白名单及 root 守卫 |
| PC 恢复入口与缓存 | 明确归档状态、保留查看路径、恢复后不自动执行；键盘可切换范围与恢复；统一更新本轮前端缓存标识 | 复用现有 PC 组件；修正归档提示复用 grid 时窄列换行的视觉缺陷；未迭代手机端 |

现有 `AGENTS.md`、task contract、最终测试集隔离和动态执行政策未修改。用户原有 `WORKBUDDY-FLOW-REFERENCE.md`、旧 evidence 目录和工作区数据未改动。

## 3. 验证记录

### 自动化

| 验证对象 | 结果 | 解释 |
| --- | --- | --- |
| 归档切片当轮源码 Python 全量 | **663 / 663 通过**，52.788 秒 | `PYTHONWARNINGS=ignore::DeprecationWarning <qa-python> -m unittest discover -s tests`；命令行缺批准参数的 usage 输出是负例测试预期，不是用例失败；最新复验见第 6 节 |
| 归档切片当轮源码 Node 全量 | **201 / 201 通过** | `node --test integrations/deepseek-harness/test/*.test.js`；新增 16 项归档前端实际函数行为回归、3 项插件角色回归；最新复验见第 6 节 |
| 归档后端集中测试 | **20 项归档用例通过**；与 server、intake 合计 32 项通过 | 真实 TestClient：持久化、同一身份、文件字节保留、无自动执行、所有任务写路由、conversation 别名和并发互斥 |
| 语法与 diff | 通过 | `npm --prefix integrations/deepseek-harness run check`、`node --check model_harness/web/app.js`、`git diff --check` |
| 修改前 HEAD 导出快照 | Node **182 / 182**；Python **649 通过、1 个环境身份错误** | 650 项执行完毕；快照不含 `.git`，`test_health_and_recipe_endpoints` 的 Git revision 断言拿到 null。这不是已通过的完整基线门，也不能称新增回归；当前真实 checkout 的同一测试通过 |

`<qa-python>` 本次实测为 `/tmp/sms-rc-final.laknJM/source/.venv/bin/python`（Python 3.12.12）。原仓库 `.venv` 的 Python 可启动，但本次全量/服务冷启动停在 SciPy 原生模块导入；未重装或改动该环境。使用已有验收环境从当前 checkout 导入项目源码。这个临时环境路径不是可长期依赖的正式启动方案，环境可复现性仍是后续 M1/M5 工作。

### PC 浏览器

独立本地服务：`http://127.0.0.1:8891/app`；只用于本轮验收，不替换原 8877 服务。工作区为 `output/playwright/vnext-m1-archive/runs`，只含两个验收用任务，没有用户原数据。启动时 `MODEL_HARNESS_CONVERSATION_URL=http://127.0.0.1:59999`，不启动 DSH 前端、不调用模型提供商；界面如实显示 AI 未连接。

- UI 发起归档、确认后留在原任务；状态明确“已归档 · 只读”，输入区关闭，恢复入口获得焦点。
- 归档深链接刷新，自动显示已归档范围；GET 证据仍可读取。
- 1280×800、1440×900、1920×1080：无页面横向溢出，恢复入口可见；修复后归档提示高度 76px，不再挤为窄列。
- 注入恢复接口 503：原归档状态保留、错误可见、恢复按钮重新可用。**这是故障注入，不是真实上游故障或模型执行证据。**
- Enter / Space 切换当前和归档范围，键盘恢复同一任务；真实服务端拒绝归档状态下的 PATCH（409）。
- 恢复期间浏览器仅发出 1 次写请求，即 `/tasks/{id}/restore`；无 message/Run 创建请求。恢复后刷新，原 task_id、输入区与当前列表恢复。
- 控制台未发现新增应用脚本异常；保留原有密码字段 DOM 提示，503 故障注入产生一次预期 HTTP 错误。

本地截图：[1280 归档](../../output/playwright/vnext-m1-archive/archived-1280x800.png)、[1440 归档](../../output/playwright/vnext-m1-archive/archived-1440x900.png)、[1920 归档](../../output/playwright/vnext-m1-archive/archived-1920x1080.png)、[1440 恢复](../../output/playwright/vnext-m1-archive/restored-1440x900.png)。截图和验收运行目录均不加入 Git。

这些证明本地任务生命周期，不证明真实 DSH 多轮会话、外部模型训练、生产部署或发布。

## 4. M0 环境与对象核查

本机 Apple M4、10 核 CPU、8 核 GPU、16 GiB 内存。**安装前历史观察**：2026-09-11 09:15:41 UTC 可用内存约 2.65 GiB、磁盘空闲约 40.2 GiB（瞬时值，不作资源承诺）；当时未发现可调用 Docker/Podman/nerdctl/container，也未发现已配置的隔离 Worker，项目探测 `container_runtime=false`、`sandbox_worker=false`。这不是安装后的当前运行时状态。MPS 仅宿主硬件发现，仍不能在 v0.9 声称可用。

ResourceProbe 摘要：`df35168a2aeea7230f1cc4c0b8ac9967c2e3863fbc7b06327ed80b71ee1171af`。

2026-09-11 对象边界核查快照（当时尚未实现新 schema；第 6 节新增独立 ModelTrial，不修改下列旧对象的资格边界）：

- `TrainingPlanRevision` 0.9 是严格字段与摘要协议；不能原地塞入新的 operation 字段后复用旧批准。
- `RecipeVersion` 尚无推理/训练操作资格区分；推理合格不能自动获得训练权限。
- `InferenceCheck` 和输入暂存依赖真实已完成 Run，不能伪造 Run 来支持现成模型试跑。
- 后续 `ModelTrial` 应为 task-owned 的独立身份，绑定来源/计划/输入/环境/预算/批准与 worker 血缘；执行完成和质量达标分开，不替换当前训练 Run。

### D02 安装与隔离验证（本次新增）

- 安装：Colima 0.10.3、Lima 2.2.0、Docker CLI 29.8.0，均为官方 arm64 二进制，位于 `/Users/wanghui2100/.local/share/model-harness-runtime/bin`。没有安装 Homebrew、修改 shell 启动文件或启动 DSH 前端。
- Colima 命名实例 `model-harness-cpu`，macOS VZ，aarch64，2 CPU、2 GiB RAM；root disk 与容器数据盘分别设置 10 GiB（稀疏磁盘上限，不是预占 20 GiB）。实测 Linux 可见内存 2,005,448 KiB。
- 实际实例目录为 `/Users/wanghui2100/.colima/model-harness-cpu`，VM 状态在 `.colima/_lima`，下载缓存位于 `Library/Caches/colima`。最初设置的 `COLIMA_HOME` 未改变本版本目录，后续命令不依赖该变量。
- 明确配置 `mount none`、`ssh-agent=false`、`ssh-config=false`、`activate=false`、`port-forwarder none`、禁用 Rosetta/binfmt 和嵌套虚拟化。生成的 Lima 配置未挂载宿主目录、未加载宿主公钥；VM 中无宿主 HOME 挂载。Docker 客户端使用单独 `DOCKER_CONFIG`，所有验证显式指定本机 socket，不继承远程 context。
- 实际 daemon：Linux/arm64 Docker Engine 29.5.2、kernel `6.8.0-117-generic`；socket `unix:///Users/wanghui2100/.colima/model-harness-cpu/docker.sock`。CLI 安装成功与 daemon 可用分别核验。
- 首次拉取镜像因 VM DNS 拒绝失败；只在本命名实例的 Docker daemon 中配置现有本机代理的 VM 网关地址后成功。未修改系统代理、未关闭 TLS 校验。该代理端口是本机当前配置，不是跨机器通用常量。
- Colima 与两份 Lima 压缩包 SHA256 均匹配官方 release API 的 digest；Docker CLI 记录本地 SHA256，`codesign --verify` 通过，但没有宣称验证独立发布的 Docker SHA 清单或签名发布者。手工安装需要显式维护升级，不属于生产运行时部署。

下载来源：[Colima 官方安装](https://colima.run/docs/installation/)、[Lima 官方安装](https://lima-vm.io/docs/installation/)、[Docker 官方静态二进制说明](https://docs.docker.com/engine/install/binaries/)。版本与本地哈希以本轮证据为准，不代表永远是最新版本。

### 独立运行时证据

新增可信脚本 `scripts/verify_local_oci.py`：只能连接显式本地 Unix socket、只能运行已经下载的官方 Alpine 固定 digest，检查 daemon/image OS 与架构一致，不自动 pull。所有 Docker 操作有超时；只按本次随机 name、label 和实际 container ID 清理，拒绝覆盖历史证据。

真实 [isolation-01.json](../../output/local-oci/20260911/isolation-01.json) 通过：非 root 65534、只读根文件系统写入失败、宿主 HOME 不可见、仅 loopback、IPv4/IPv6 无外部路由、capabilities 清零、NoNewPrivs=1、16 MiB tmpfs 可写，以及 cgroup 的 1 CPU / 128 MiB / 32 PID 限制。容器由运行态真实停止并按精确 ID 删除。固定 Alpine digest：`sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40`。

这不是对任意恶意代码的隔离安全认证，也不是产品任务取消、断线恢复、超时整棵进程树回收或远程 Worker 的完整验收；对应产品协议仍需实现和测试。

### 固定外部模型的 CPU 实跑

新增 `scripts/probe_hf_onnx_cpu.py`，仅做固定来源的 `prepare → infer`。它拒绝宿主执行、root、非官方 HF endpoint、凭据环境与任意工作目录；推理要求仅 loopback。复用现有资产下载/校验、`OnnxImageFeatureExtractor`，未编写第三方仓库 repair patch 或模型专属适配器。

- 模型：`pyronear/mobilenet_v3_small`，commit `a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674`，Apache-2.0；匿名下载仅 README、config、ONNX 三个文件，模型 6,068,953 字节，SHA256 `8fd451f919499e30e879eda19bfd2b249ceec77e4f1c02f7b022730e365ae897`，匹配本次官方 HF API 的 LFS OID。
- 基础镜像固定 `python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`，实际 Python 3.12.14 / Linux arm64。18 个依赖全部使用仓库 `requirements-lock.txt` 的版本约束及官方 PyPI 二进制 wheels，在非 root、限额容器内安装。安装报告保留 wheel URL/哈希；未在宿主导入模型或安装原生依赖。
- 准备阶段下载匿名公共资产，不挂用户数据/代码目录。之后冻结为仅本地镜像 `sha256:fc5ab3b7383cd944c9867aed02c728e1ddb44a9ca25e0f8236156fafeee64202`；推理另建容器，`--network none --read-only --user 65534:65534 --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128`，删除 capabilities、禁止提权、无宿主挂载，显式配置 `/work` 的 32 MiB tmpfs，另保留容器私有默认 `/dev/shm`（64 MiB）。
- [首轮真实推理](../../output/local-oci/20260911/inference-01.json)：连续两次 + 新 extractor 重新加载一次，三次输出 float32 `[1]`、finite 且一致，输出 SHA256 `279d2449db2600c1a78c3c2deb0bb7c36d289bd119704fa2567f9e4cbbd8f52c`。CPUExecutionProvider，单次 `session.run` 约 2.4–3.3 ms，初始化约 7.0–26.2 ms，进程峰值 RSS 92,114,944 字节（约 88 MiB）；这是单张合成图的瞬时观测，不是性能基准或资源预测。
- ONNX Runtime 打印 CPU vendor 识别 warning，单独保留在 stderr；没有隐藏 warning，也没有因此宣称 GPU。合成输入没有业务 ground truth，输出不是准确率、概率或业务达标证据。
- [宿主执行负例](../../output/local-oci/20260911/host-execution-rejected.json) 返回 `linux_container_required` 且进程 exit 1，未导入第三方依赖。没有生成 `TrainingRun`、`QualificationRun`、RecipeVersion 或批准任何合同/来源对象。

该次验证的模型、依赖镜像、运行输出均在本地非 Git 状态；原用户任务和原有应用服务没有切换到此环境。安装路径没有自动加入原服务 PATH；截至该次验证，Studio Worker 尚未接线，不能把 standalone 实跑投射成产品能力已开放。第 6 节新增的是兼容 ONNX 的受限产品试跑，不是任意模型的通用 Worker 验收。

### 重启、回归与清理

- 完整停止并重启 Colima VM 后，新建独立容器从同一冻结 image ID 执行推理：[重启后推理](../../output/local-oci/20260911/inference-after-restart.json)。[VM 原生日志摘录](../../output/local-oci/20260911/vm-lifecycle.jsonl) 记录 17:53:02 重新启动 VZ，处于 17:52:28 首轮推理和 17:54:17 第二轮推理之间，17:55:36 最终停止；不凭文件名推导重启。两轮共 6 次输出摘要全部一致；两个容器均 exit 0、非 OOM、无宿主挂载，模型、脚本与输入摘要相同。重启后进程峰值约 86.6 MiB，单次推理约 2.7–22.5 ms，进一步说明这些时延不是基准承诺。
- 重启后再次执行 [隔离负例探针](../../output/local-oci/20260911/isolation-after-restart.json)，同样通过并验证临时容器删除。
- 2026-09-11 该次复验自动化：Python **690 / 690**（60.884 秒）、Node **201 / 201**。新增 12 个 OCI 参数/身份/限额/清理 mock 用例、15 个模型试跑安全边界 mock 用例；mock 与上面的真实容器证据分开。该次未重新进行 PC 浏览器或完整 Agent 用户旅程验收；2026-09-12 增量见第 6 节。
- 4 个本轮准备/推理容器均先确认 label、精确 ID、已退出且 exit 0 后删除；运行日志、依赖安装报告、源码哈希和冻结镜像保留，可重新创建容器，不删除原用户任务或数据。
- 2026-09-11 该次验证结束时停止命名 VM，释放其运行内存；启动配置与缓存保留。**已安装、已验证、已停止**是该次结束时的历史观察，不代表后续当前服务或 VM 状态。

### 在本机复验（不启动 Studio 或 DSH）

以下路径对应本轮本机，不是云端部署脚本。首先启动保存的 profile：

```sh
runtime_bin=/Users/wanghui2100/.local/share/model-harness-runtime/bin
runtime_config=/Users/wanghui2100/.local/share/model-harness-runtime/docker-config
runtime_endpoint=unix:///Users/wanghui2100/.colima/model-harness-cpu/docker.sock
PATH="$runtime_bin:$PATH" DOCKER_CONFIG="$runtime_config" "$runtime_bin/colima" --profile model-harness-cpu start
```

对已缓存镜像做同样的只读离线推理（`--rm` 仅删除本次临时容器，输出到终端；这条 standalone 命令不使用第 6 节产品控制器的超时与取消协议）：

```sh
"$runtime_bin/docker" --config "$runtime_config" -H "$runtime_endpoint" run --rm --pull=never \
  --network none --read-only --user 65534:65534 \
  --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128 \
  --cap-drop ALL --security-opt no-new-privileges --ipc private --cgroupns private \
  --tmpfs /work:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  sha256:fc5ab3b7383cd944c9867aed02c728e1ddb44a9ca25e0f8236156fafeee64202
PATH="$runtime_bin:$PATH" DOCKER_CONFIG="$runtime_config" "$runtime_bin/colima" --profile model-harness-cpu stop
```

独立隔离检查用 `scripts/verify_local_oci.py --docker-binary <上述 docker 绝对路径> --endpoint <上述本机 socket> --image alpine@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40 --output <父目录已存在的新 JSON 文件>`。不要复用旧输出路径覆盖历史证据。完整冷机安装包/一键重建与远程执行器尚未交付，本次冻结镜像不是生产部署产物。

## 5. 上一轮后续安排与未决门

2026-09-11 记录的下一包：版本化 `ModelTrial` / Worker 协议与负例测试、只读后端能力投影、兼容旧 schema 和验收数据设计；其受限实现增量现见第 6 节。D02 的本机安装与小型 CPU 实测已获得授权并实施；任意来源的动态执行工具仍不可据此开放，不把模型代码导入宿主控制平面，不从安装成功推导 D01 自主修复授权。

进入真实动态工程前必须解决 [D01–D05](DECISIONS.md)：

1. D01：是否允许隔离边界内的 Agent 自主编码及限额修复；执行预算、终止条件、可执行命令和人工批准边界需要明确。
2. D02：本机 OCI CPU 前置环境已可验证；第 6 节补充受限 OCI Job 协议，通用产品 Worker、GPU 与云端资格仍未完成。火山引擎仅是资源不足时的条件性后备，目前没有可用实例规格/SSH 别名或新购预算；没有创建付费资源或外发用户数据，不能降级到宿主 subprocess 执行第三方代码。
3. D03–D05：最先验收的任务与数据、比较预算/冻结门槛、经验和数据复用权限。不能把六种任务名称列出来就计为六项支持。

2026-09-11 历史交付状态：该轮未提交 Git、未 push、未打 tag、未部署生产，也未修改任何既有“unsupported”能力声明；不以该记录推断后续 Git 或服务状态。

## 6. 2026-09-12：受限 ModelTrial 产品切片

### 实现范围与对象责任

本包把“任务已绑定兼容 ONNX 资产 → 上传单张样本 → 保存待批准计划 → 精确批准 → OCI CPU 试跑 → 持久原始输出”接入产品。这里只接受当前合法绑定与 PNG/JPEG/WebP/BMP 单张输入（最大 4 MiB）；不是任意仓库安装器，不新增第三方模型适配器，也不授予训练或发布权限。

| 对象 / 入口 | 已实现责任 | 不能据此推导 |
| --- | --- | --- |
| `model_harness/model_trials.py` | task-owned 独立 trial_id；不可变 plan/input、带摘要的追加事件和原子状态指针；输入/绑定/TaskSpec/环境变化使旧计划 stale；幂等请求、精确审批、防重发、新身份重试 | 不复用或伪造 TrainingRun，不改写合同或最终测试集门槛，不原位覆盖失败历史 |
| `model_harness/oci_jobs.py` | 显式本机 Unix socket、固定镜像和入口命令、隔离/限额摘要；真实创建与运行状态分开；有界取消/超时、精确所有权清理；停止未确认保持 `observation_degraded` 并阻止归档 | 执行器接口可复用不等于任意来源/命令已获产品授权；不自动 pull、不降级到宿主执行、不声称 GPU 可用 |
| `model_harness/oci_trial_runner.py` | 仅从 stdin 接收已固定资产与输入；在 Linux 非 root 断网容器中解码/执行 ONNX；输出归属、输入/模型/配置摘要、有限 float32 值与原始字节摘要由服务再核验 | CPU 输出只是本次执行证据，不是概率、准确率、业务达标、QualificationRun 或 RecipeVersion |
| workspace / server / DSH 桥接 | 创建、读取、批准执行、取消、重试、reconcile 与启动恢复；真实 bridge token 加唯一 root tool-call 血缘和 exact task/trial/plan 参数；归档准入与后台动作联动 | 浏览器 `actor=user` 或聊天表示同意不是授权；测试中的模拟审批不是用户在真实 DSH 的批准 |
| PC 工作台 | 直达“查看模型试跑”、保存样本/计划、待批/停止/历史/原始输出；任务切换、上下文变化及迟到响应隔离；明确“本任务记录，非 AI 回答” | 页面展示成功不能替代领域证据，也不能把任务仍“等待数据”误改为训练完成；本轮未做手机端 |

### 分层验收证据

| 验收层 | 实测结果与证据 | 范围限制 |
| --- | --- | --- |
| Python 自动化 | [最终日志](../../output/model-trial/20260912/python-tests-final.log)：**778 / 778 通过**，70.432 秒 | 单元 / TestClient 与 mock 边界测试；日志中的必填批准参数 usage 是负例预期。不是 778 次真实模型运行，不累加此前 663/690 等计数 |
| Node 自动化 | [最终日志](../../output/model-trial/20260912/node-tests-final.log)：**228 / 228 通过**，0 failed | 插件与实际前端函数行为回归；不能证明真实 DSH 会话或浏览器全旅程 |
| 产品 API → 真实 OCI 推理 | [成功记录](../../output/model-trial/20260912/real-product-trial-task-934171532b5043abac8732f8ea810e72.json)：`trial-19fdabf273fa49298b99cf8480dcf6c8`，exit 0、`cleanup_confirmed=true`、`succeeded`；无 bridge token 的批准请求返回 403 | [验收脚本](../../output/model-trial/20260912/verify_product_trial.py)预置已校验公共资产及任务绑定，并 mock root session / native tool-call 事件。真实执行从“已绑定资产”开始，不证明原生 HF 接入/绑定批准、真实 DSH 审批与对话闭环 |
| 真实 OCI 生命周期 | [controls 记录](../../output/model-trial/20260912/real-oci-controls.json)：timeout 2.196 秒、cancel 1.177 秒，均 exit 137 且清理确认；recover 先观察精确标记容器 `running=true`，再停止并确认清理 | [控制验证脚本](../../output/model-trial/20260912/verify_controls.py)使用可信 `sleep` 作业，不是 ONNX 中断、模型质量或原生人工批准测试；时延是单次观察，不作保证 |
| 服务重启后读取持久状态 | [重启前](../../output/model-trial/20260912/before-server-restart.json) / [重启后](../../output/model-trial/20260912/after-server-restart.json)：同 3 个 trial_id 的 `cancelled@2`、`cancelled@2`、`succeeded@5` 保持一致 | 证明该次终态读取没有丢身份或回退状态；不能替代执行中进程崩溃恢复。运行中遗留作业停止由上一行独立验证 |
| PC 浏览器 | 主线验收完成选择样本、保存待批准计划、刷新后找回、取消未执行计划、查看原始输出；[1280×800](../../output/playwright/model-trial-20260912/trial-1280.png)、[1440×900](../../output/playwright/model-trial-20260912/trial-1440.png)、[1920×1080](../../output/playwright/model-trial-20260912/trial-1920.png)保留页面证据 | 截图可见协调器未连接、待批按钮不可用和“未创建训练 Run”；这些截图证明对应页面状态，不单独证明每个操作的网络时序，也不是一次真实 AI 多轮体验 |

成功用例固定 `pyronear/mobilenet_v3_small@a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674`，模型 SHA256 `8fd451f919499e30e879eda19bfd2b249ceec77e4f1c02f7b022730e365ae897`；本次 runtime digest `f6529edb6018f537ad06456f06733c498e87a8ec96cec409be316cac71028ee9`、本地 image ID `sha256:41c355a8bf1dbbbe537cb9c3d2ae31dd350a444797a84e1733454efd163b6d3d`。限制为 1 CPU / 512 MiB / 128 PID / 30 秒；服务协议拒绝网络、宿主挂载与提权。该记录是当前本机固定环境的验证，不是冷机安装包或跨机器资格认证。

输入为 204 字节的公开合成 PNG；结果 `CPUExecutionProvider`、float32 shape `[1]`、原始值 `[2.4693212509155273]`，输出 SHA256 `279d2449db2600c1a78c3c2deb0bb7c36d289bd119704fa2567f9e4cbbd8f52c`，与第 4 节相同输入的独立探针输出摘要一致。CPU vendor warning 仍保留；`business_quality_accepted=false`、`training_run_created=false`。这不是业务准确率或训练达标证据。[源码摘要快照](../../output/model-trial/20260912/source-sha256.txt)记录当次文件身份，不自动代表后续修改后的源码。

### 失败历史与仍未通过的门

- [首轮记录](../../output/model-trial/20260912/real-product-trial.json)为 `observation_degraded` / `container_observation_unavailable`，没有确认清理；[第二轮记录](../../output/model-trial/20260912/real-product-trial-task-68333c77eec240d2b39bd1c88c5ebc40.json)因 Docker logging 配置不兼容 exit 128，结果 `failed`、清理确认。两份失败证据保留，不用第三轮独立 task/trial 的成功改写它们。
- [早期 Python 日志](../../output/model-trial/20260912/python-tests.log)中的 event/state JSON 字节格式比较失败同样保留；测试已改为分别核验不可变事件和原子指针，最终结果以 778 项全绿日志为准，不删除失败记录粉饰验收。
- **真实 DSH 对话 → 原生审批 → 精确工具调用 → 试跑 → AI 解释结果尚未验收。** 下一道产品门是该条真实链路，以及其中用户拒绝、修改目标、失败重试和刷新恢复；当前 mock 原生事件不能替代它。
- D01 自主生成/执行第三方 repair 仍待批准，D03–D05 的任务、质量门与复用范围仍待确认。动态构建/资格注册、任意模型适配训练、GPU/云端、业务对照优势和完整交付链没有因此完成；既有 unsupported 声明继续有效。
- 本节只登记技术切片及对应本地证据，不声明 M0/M1 整体验收、Git 发布或生产部署，也不据历史测试推断当前应用服务或 VM 的运行/停止状态。运行输出、权重、镜像和截图保留在本地证据区，不作为源代码交付物。

## 7. PC 交互对齐 WorkBuddy（2026-09-12）

用户决定：**“迭代对齐 workbuddy 的交互形态，同时有我们的产品调性”**。沿用[原交互参考](../v1.0-conversation-native/WORKBUDDY-FLOW-REFERENCE.md)，不修改或替换原截图；目标是任务侧栏、连续对话、按需成果区的完整用户路径，不是复刻商标或增加独立流程。

### 问题与本轮范围

此前真实 DSH 验收已发现并修复缺少试跑列表工具、原生 JSON 字符串参数校验不匹配、精确同调用历史读取误需执行凭证。Python 780 / Node 238 当轮通过，但真实回复仍过长，顶部“等待数据”与试跑“已停止”冲突，不能据此判定交互达标。

| 需求 | 本轮实现方向 | 可观察退出条件 |
| --- | --- | --- |
| WB-R13 直接审阅成果 | 同一右侧工作区增加可读试跑报告；原始值、输入、执行状态与局限优先，ID/hash/JSON按需展开 | 从对话页一次点击到具体报告；成功/取消/待批分别准确呈现；刷新仍读同 task/trial |
| WB-R01 一致状态 | 试跑读取后统一刷新顶栏、选中任务行和摘要；保留真实失败、降级、审批与后台优先级 | 本页不再一处等待数据、一处已停止；其他任务不借用当前缓存 |
| WB-R02 执行中可控制 | 后端仅 queue_after_turn。保留真实排队，增加先停止、保留草稿、核验后再修改；不冒充实时干预或原子停止替换 | POST取消成功不能直接解锁；独立权威观察确认停止才可新发；失败可核对、草稿不丢、不自动发送 |
| WB-R08 简洁交流 | 人类可读工具标签；UI生成试跑请求的关联字段折叠，完整原消息仍存档；协调器短结论优先 | 真实 AI 能读已有结果；默认摘要无需复制内部编号，完整技术数据不挤占正文 |
| Studio PC 调性 | 中性灰白、克制紫色、保留原品牌；加宽结果阅读区，减少装饰与卡片嵌套 | 1280/1440/1920下并列阅读、无页面横向溢出，重要控件可用；本轮不迭代手机端 |

技术沿用现有静态前端、DSH后台会话、task-owned领域结果和隔离执行，不引入新UI框架、不放宽任何执行/审批/发布门。实施按成果面板、输入控制、视觉系统分文件区并行，主线负责集成、真实对话与PC验收。当前为实施中，验收结论待下方实际证据补齐。
