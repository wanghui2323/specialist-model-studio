# Model Harness v0.7 · L5 机器验收合同

> 状态：本地 Beta `verified`；GitHub Release pending
> 聚合器：`scripts/verify_v07_beta.py`  
> Gate 定义：`acceptance/v0.7-gates.json`  
> 报告 Schema：`acceptance/report.schema.json`  
> 受控证据 Manifest Schema：`acceptance/external-evidence.schema.json`

## 1. 一键执行与输出

```bash
.venv/bin/python scripts/verify_v07_beta.py
```

每次执行使用全新临时 runtime，并写入：

```text
runs/acceptance/v0.7-<UTC>-<8hex>/acceptance-report.json
runs/acceptance/v0.7-<UTC>-<8hex>/logs/*.log
```

报告中只允许 `passed / failed / blocked`。`skipped` 是非法状态；任一本地 required gate 为 `failed` 或 `blocked`，`local_beta_verified` 必须为 `false`。

## 2. 自动执行的真实 Hugging Face 场景

聚合器会直接运行：

```text
scripts/run_hf_real_scenario.py
repo_id = pyronear/mobilenet_v3_small
commit  = a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674
```

不另外执行只下载资产却不训练的 HF 探针。这一条真实场景必须在同一血缘中产生：

- 官方 `huggingface_hub` 固定 commit 下载与逐文件哈希；
- 100 张图片数据集与至少 20 个独立测试样本；
- CPU ONNX 特征、真实候选训练、耗时和事件；
- `EvaluationReport`、新图片 `SampleInference`、经下载哈希复核的 `ArtifactBundle`；
- 重建应用实例后任务、Run、ModelAsset 与 commit 不变。

这条“应用实例 restart”证据不会冒充 L5 的真实 OS 进程 PID 切换门禁。

## 3. 浏览器、进程重启与冷克隆证据

聚合器不接收人工填写的结论 JSON。每次运行时它会：

1. 生成不可预测的本轮 challenge；
2. 只在当前工作树干净且 HEAD 为 40 位 commit 时，启动仓库内固定版本的 `scripts/collect_v07_external_evidence.py`；
3. 用固定 `playwright-core` 和本机 Chrome 实际运行 1440×900、390×844 两个视口，保留 PNG、Trace、Console 和 Network 原始记录；
4. 对同一三家族 runtime 启动两个不同 OS PID，确认旧端口关闭、新进程可访问；
5. 用 `git clone --no-local --no-hardlinks` 创建冷克隆，按锁文件安装 Python、DSH 和浏览器证据依赖，再跑全量测试与离线三家族最小闭环；
6. 由聚合器独立执行严格 JSON Schema、producer 源文件哈希、制品路径/大小/SHA-256、PNG 尺寸、原始日志、实时 HTTP 对象所有权、Bundle 下载哈希和 PID 存活复核。

冷克隆必须使用全新的源码目录、`.venv`、运行对象和 Hugging Face 模型缓存。允许复用 `uv` / `npm` 的内容寻址包缓存以避免把公网下载速度误作产品门禁；安装仍由锁文件与包完整性哈希约束，并以 copy 模式生成新的虚拟环境。

默认受控制品写入本轮验收报告目录下的 `controlled-external-evidence/`。如需指定位置，只能提供一个尚不存在的新目录：

```bash
.venv/bin/python scripts/verify_v07_beta.py \
  --controlled-evidence-dir /absolute/path/to/fresh-evidence-dir \
  --output /absolute/path/acceptance-report.json
```

预先存在的目录、旧 challenge、手写 JSON、源文件哈希漂移、symlink/越界制品、篡改日志和无法实时查询的 PID 都会失败关闭。`acceptance/external-evidence.schema.json` 是 producer manifest 契约；浏览器、进程重启和冷克隆另有各自的 report schema。

GitHub 发布链不读取这个 manifest。聚合器独立通过 `gh api` 查询当前 source commit、关联已合并 PR、成功 Check Run、精确 tag 和公开 Release；认证、网络或远程对象缺失时保持 `blocked/failed`。

## 4. 六层退出门槛

| 层级 | 机器退出条件 |
|---|---|
| L0 | 临时 runtime 隔离；干净的 40 位 source commit；状态合同；版本同步；health/OpenAPI；全量 Python/Node；注册表与宣称一致 |
| L1 | 歧义阻断、同 ID 修订、控制投影、双取消、拒绝零血缘，加双视口草稿/刷新 |
| L2 | 暂存不起 Run、恶意数据、BuildAttempt 事件与恢复、声明式限制、digest 批准原子性、真实音频训练 |
| L3 | 产品 HF API、拒绝零缓存、Token/许可/哈希/篡改、合同血缘、真实耗时事件、中断下载恢复，加固定 commit 真实 HF 训练 |
| L4 | 结论拆分、三家族 EvaluationReport、候选/失败/父子 Run、原样本重入、篡改阻断、Bundle 哈希/隐私/重入 |
| L5 | 集成负向、三家族完整旅程、双视口、真实 PID 重启、冷克隆、零 P0；GitHub 发布链单独定级 |

## 5. 本地 Beta 与 GitHub Release

`L5-release-chain` 是唯一 `required=false, required_for_github_release=true` 的 gate：

- 它为 `blocked/failed` 时，`github_released=false`；
- 它不改写已经独立得出的 `local_beta_verified`；
- 只有所有本地 required gate 通过，且发布链也通过，`github_released` 才能为 `true`。

账本中的 L2–L5 可以标记为 `verified`，但只对最近一次由聚合器绑定的干净 source commit 成立；任何源码变化都必须完整重跑。本地结论不会替代用户 `accepted`，也不会替代 GitHub 的 PR、CI、merge、Tag 或 Release 证据。
