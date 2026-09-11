# Specialist Model Studio v0.9 · V1–V3 纵向执行与 Loop 映射

本文件只负责把用户可见版本、L0–L5 机器层级、C01–C15 闭环和任务依赖映射到同一张表。施工细节仍以 `ITERATION-PLAN.md` 为准，评分仍以 `closure-matrix.md` 为准，状态仍以 `loop-tasks.json` 为准。

## 1. 唯一映射

| 版本 | Loop | 流程 | 版本结束时用户可见结果 | Loop 退出条件 |
| --- | --- | --- | --- | --- |
| V0 | L0 | 合同基线 | 需求、对象、安全边界、证据分级可审阅 | 当前冻结 commit 的 L0 合同、哈希、浏览器与状态失效证据有效 |
| V1 | L1 第一段 | C01–C04 | HF/GitHub 地址解析为固定 commit、许可与 Manifest | 只形成 L1 部分证据，不允许单独退出 L1 |
| V2 | L1 第二段 | C05 | 静态分析框架、入口、数据、依赖、指标、产物与风险 | C01–C05 在同一冻结 commit 全部 6/6 |
| V3 | L2 | C06、C07、C15 | analysis-only 的计划审批、环境锁、本机资源证据与真实阻断；provisional budget 只交接到 L3 | C06、C07、C15 在同一冻结 commit 全部 6/6；不包含资格试跑或训练 |
| V4–V7 | L3 | C08–C10、C15 | 隔离构建、人工修复、资格试跑 | L3 安全与资格门全部通过 |
| V8–V9 | L4 | C11–C14 | 注册后回原任务并完成正式训练交付 | L4 两条真实纵向训练闭环通过 |
| V10 | L5 | C01–C15 复验 | 冻结后第三模型盲测与冷复现 | 全部 P0 6/6；发布链仍单独登记 |

## 2. V1–V3 依赖顺序

```text
L0 current evidence
  └─ MH-910 双来源与不可变快照
       └─ MH-912 来源解析负例、漂移、取消、重启
            └─ MH-911 只读仓库分析
                 └─ MH-913 分析负例、手工映射、取消、恢复
                      └─ L1 exit: C01–C05 = 6/6
                           └─ MH-920 不可变训练计划与审批
                                └─ MH-921 EnvironmentLock
                                     └─ MH-922 ResourceFit 与降级 revision
                                          └─ MH-923 资源/平台/环境负例与 C15
                                               └─ MH-924 verified 失效检查
                                                    └─ L2 exit: C06/C07/C15 = 6/6
```

来源负例不再依赖仓库分析，因此 V1 不会反向等待 V2。分析负例独立为 MH-913。状态失效机制独立为 MH-924，不能被“资源单测通过”隐含替代。

## 3. 当前状态（2026-08-24）

| 范围 | 工程状态 | 已有检查 | 未关闭门禁 |
| --- | --- | --- | --- |
| L0/V0 | `implemented` | 历史合同与工作台证据存在 | 现有 evidence 缺 `owned_paths` 且文件哈希漂移 |
| V1 | `implemented` | 来源/分析测试纳入外部新 wheel 的 Python 388/388 完整 suite；冻结候选上 HF/GitHub 公开正例、3 条安全负例与 snapshot 篡改负例通过 | 私有仓库未认证/已认证双态 fixture 缺失，formal L1 保持 `blocked`；尚无 C01–C04 完整 evidence |
| V2 | `implemented` | Analyzer/Store/API 定向测试通过；真实 GitHub 仓库已经浏览器完成搜索、固定 commit、绑定、分析与刷新重入 | C05 尚未形成 6/6 完整 `l1-evidence.json` |
| V3/L2 | `implemented` | 外部新 wheel Python 388/388、Node 29/29；两个仓库外 CLI、包外服务、任务重启和 task-owned 授权负例通过；冻结候选的 1440/1024/390 smoke 通过；真实 GitHub V3 旅程完成计划/审批/资源检查，刷新前后血缘一致，并诚实终止于 `blocked_environment`；provisional budget 不生成 ResourceFitReport/Run，只产生 `retryable=false` 的 `continue_to_l3_qualification` 交接 | 尚无 C06/C07/C15 全部 6/6 的 `l2-evidence.json`；V3 不包含 L3 资格试跑或训练 |
| L3–L5 | `planned` | 无 | 对应隔离、训练、盲测与发布门 |

本轮实现开始前的基线 commit 为 `ce8130d58250c25ee991ca192104de37bf7b2468`。V1–V3 已进入冻结审核分支和 Draft PR，精确审核 commit 以 Git/PR HEAD 为准；该基线只用于定位实现起点，不是 V1–V3 verified commit。

## 4. 状态写入规则

- `implemented`：代码/合同已经进入工作树或 commit，但尚未完成整层真实证据。
- `verified`：对应 Loop 的全部 Cxx 在同一冻结 commit 达到 6/6，完整回归、浏览器、重启及所需联网门通过。
- `accepted`：用户明确确认同一 verified commit 与证据。
- V1 完成、V2 完成或 V3 实现完成都不能单独推导 `local_byom_verified`。
- V3 只形成 analysis-only 的可交付审阅版本；provisional budget 的 `continue_to_l3_qualification` 是不可在 V3 原地重试的跨层交接，不代表资格证据已经补齐，也不代表模型已训练。在 L3–L5 通过前，不得称完整 BYOM 训练已验证或 release-ready。

## 5. 证据文件归属

- `l0-evidence.json`：L0 当前合同证据，必须补齐 `owned_paths` 并重新生成。
- `l1-evidence.json`：V1 追加 C01–C04，V2 追加 C05；五行全部 6/6 后关闭 L1。
- `l2-evidence.json`：V3 的 C06、C07、C15。
- `l3-evidence.json` 至 `l5-evidence.json`：按 `closure-matrix.md` 对应层级生成。
- GitHub push、CI、merge、tag 和 Release 不写入上述本地工程状态，继续使用独立 release gate。
