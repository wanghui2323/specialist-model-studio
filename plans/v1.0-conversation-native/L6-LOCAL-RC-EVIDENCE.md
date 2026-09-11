# v1.0 Historical Local Evidence

> 此文件记录 projector `3.1` 与 Python `0.9.0rc1` 时的历史本地验收。当前候选已升级为 projector `3.2` / `1.0.0rc1`，所以下列 `verified` 不能继承为当前公开 RC 证据；必须从远程精确 commit 重新执行 cold clone、完整 `start`、真实对话与浏览器门禁。

Date: 2026-08-25
Scope: isolated local review workspaces only
Release boundary: no GitHub push, CI, cold-clone acceptance, tag or release is asserted here

## Status legend

- `implemented`: source and contract exist;
- `verified`: independently exercised with recorded identities;
- `pending`: not yet closed;
- `blocked`: a typed external or product boundary stopped the flow.

## Runtime contract

| Contract | Verified value |
| --- | --- |
| Domain truth | `TrainingTask` |
| Agent implementation | `dsh_native_subagents` |
| Conversation schema | `2.0` |
| Projector revision | `3.1` |
| Action schema | `1.0` |
| Synthesis verdict | `1.0` |
| Product stream | task-owned SSE with snapshot/delta/state/error/heartbeat |

Projector `3.1` is a real migration boundary. It reprojects original DSH
history so verified child tool events receive `agent_run_id`, `delegation_id`
and `parent_delegation_id`; persisted `3.0` events are not silently upgraded.

## Scenario A - registered Recipe, real tabular regression

Backend evidence workspace: `/tmp/sms-l6-scenario-a.MmkLG0`
TrainingTask: `L6-糖尿病进展回归-41979fc3`

| Gate | Evidence | State |
| --- | --- | --- |
| TaskSpec | r1 -> human-confirmed r2 -> dataset-bound r3 | verified |
| Dataset | `dataset-fd4eab6f12`, 442 rows, 10 numeric features | verified |
| Run | `20260825T014622610490Z-L6---41979fc3`, Ridge, 15 events | verified |
| Evaluation | `evaluation-4f3f3f2d22b0`; MAE 0.1267, RMSE 0.1479, R2 0.3852 | verified |
| New sample | `sample-c84ac6a7af67` | verified |
| Bundle | `bundle-ca9847dc7996`; downloaded archive digest matched | verified |
| Deep verify | integrity and release gates passed | verified |
| Restart/re-entry | task/spec/dataset/run/report/sample/bundle identities stable | verified |
| Negative | two-row CSV returned 422 and created no Dataset or Run | verified |
| Conversation-native entry | provider-backed isolated browser task completed through real checkpoints and tools | verified |

This 6/6 backend loop proves real training and evidence persistence. A second
provider-backed browser run also drove the human steps through the DSH
conversation instead of calling domain endpoints as a hidden test shortcut.

### Scenario A conversation-native browser evidence

Browser workspace: `/private/tmp/specialist-model-studio-rc.0NagtS/runs/_workspace`
TrainingTask: `我有一份设备生产数据-CSV-92ba8135`

| Gate | Evidence | State |
| --- | --- | --- |
| TaskSpec | dialogue clarified numeric regression; r3 bound the reviewed CSV contract | verified |
| Dataset | `dataset-b37f34f078`; 180 rows; `sample_id` explicitly ignored after human review | verified |
| Run | `20260825T023154929596Z-CSV-92ba8135`; Ridge; real task-owned backend Run | verified |
| Evaluation | `evaluation-773abd200d45`; MAE 0.0414, RMSE 0.0483, R2 0.9998; report SHA-256 `30cc1a620800297300bd8bc582d247b019aaac20d80345a1fcf35aa1552eb559` | verified |
| New sample | `sample-ca4e10245466`; prediction 5.1644514934 | verified |
| Bundle | `bundle-eb8f42292bc4`; manifest SHA-256 `e4936822a15f879be60a5c03725abb48b94cceb10cdc7d9a4e3a7713cb627a82`; raw data excluded | verified |
| Download | downloaded archive SHA-256 matched `a78232a7ecc0d4e0ede1364a16e6e2c96a753c9f3cb3eeecff8d91f7fc39bc4c` | verified |
| Inspector | exact task/run-owned Artifact Bundle ObjectRef opened the canonical manifest | verified |
| Negative | separate three-row CSV task returned 422 and kept `dataset_id=null`, `run_ids=[]` | verified |
| Backend restart/re-entry | refresh, exact backend/DSH restart and task-list re-entry kept spec/dataset/run/report/sample/bundle identities stable | verified |

## Scenario B - unsupported ASR, real multi-agent diagnosis

Browser workspace: `/private/tmp/specialist-model-studio-rc.0NagtS/runs/_workspace`
TrainingTask: `离线语音转文字模型-运行在这台-77eda92e`

| Gate | Evidence | State |
| --- | --- | --- |
| TaskSpec | ASR confirmed at revision 2 | verified |
| Native delegation | `research_source` and `data_experiment` child sessions | verified |
| Child action identity | 16 actions; 0 identity errors after 3.1 reprojection | verified |
| Action classes | 8 domain, 2 delegation, 2 control, 4 unknown runtime tools | verified |
| Human source choice | visible UI first selected `mtkresearch/Breeze-ASR-25`; its incomplete submodule tree failed closed; the user then explicitly chose `m-bain/whisperX` and approved the exact commit for this invocation | verified |
| Immutable source | `source-resolution-r2-5b5cf9644a8f`; commit `2cfd7b7c5c7bba144954364db747319b50e8232b`; BSD-2-Clause | verified |
| Binding and analysis | attempt `binding-analysis-attempt-r2-61a61673316f`; snapshot `source-snapshot-r1-a507d470c232`; binding `model-binding-r1-e2627d613e55`; analysis `analysis_f2b5fb58b8293d40b334` | verified |
| Typed diagnostic outcome | `blocker_8ec1183c460afd43453c7f79`, `blocked_security`; fixed tree contained `whisperx/assets/pytorch_model.bin`, classified `unsafe_deserialization_format/high`; recovery action `review_repository_risks` | verified/blocked |
| Plan and resource boundary | analysis blocker prevented plan creation; resource decision remained `not_checked` instead of being mislabeled as an environment failure | verified |
| Training boundary | `recipe_id`, paired-audio Adapter, Dataset, plan, model asset and run are all absent; `run_ids=[]` | verified |
| No unsafe execution | no weights downloaded, no repository code or installer executed, no dynamic Python Recipe registered | verified |
| Restart/re-entry | exact backend/DSH restart preserved resolution, binding, analysis, blocker and the empty Run lineage | verified |
| Exact evidence viewers | analysis and `blocked_security` ObjectRefs were emitted by a real read-only Agent action; blocker viewer matched task/id/digest/related analysis | verified |

This flow is a successful diagnostic loop whose honest terminal state is
`blocked`, not a successful training loop. The upstream security blocker means
no training plan or resource-fit report may be invented. ASR also still lacks
a verified Recipe and paired-audio Data Adapter, so the training axis remains
unavailable even if a different repository later passes static analysis.

## Browser and recovery evidence

| Check | Evidence | State |
| --- | --- | --- |
| 1440 x 900 | no document overflow, no animations, console error/warn 0 | verified |
| 390 x 844 | document width equals viewport; current checkpoint is reachable | verified |
| Resolved checkpoint | stale request collapsed to one terminal audit record | verified |
| Automatic recovery | DSH restart triggered full reconcile then fresh SSE | verified |
| Manual recovery | reconnect action triggered GET conversation and SSE 3.1 | verified |
| Coordinator narration | rendered as a non-completion runtime note | verified |
| Team grouping | coordinator, Research & Source, Data & Experiment are distinct | verified |
| CSV Inspector/ObjectRef | task/run-owned Artifact Bundle opened the canonical manifest | verified |
| ASR Blocker ObjectRef | real `model_harness_get_repository_analysis` action emitted analysis + blocker refs; exact blocker endpoint returned `blocked_security` and matching digest | verified |
| Compact result viewer | `compact-v1` truncated event opened its complete persisted result through exact event id/projector/source key without re-executing the tool | verified |
| Response boundary | historical ASR response fell from 985,823 to 582,791 bytes after `compact-v1`; after two more read-only turns it was 639,078 bytes; full append-only event results remained retrievable | verified |
| Console | final desktop pass reported 0 errors and 0 warnings | verified |

Browser screenshots are temporary QA evidence and are intentionally not added
to source control.

## Automated, syntax and packaging gates

| Gate | Evidence | State |
| --- | --- | --- |
| Python | `492/492` tests passed after installing the final wheel | verified |
| Node | `66/66` tests passed | verified |
| Syntax | three JavaScript entrypoints and `start_conversation_harness.sh` passed syntax checks | verified |
| Diff hygiene | `git diff --check` passed; L5 zero-hit searches only retain the documented legacy sentinel, pulse negative assertion and `/chat` 410 compatibility route/tests | verified |
| Clean wheel | `/tmp/sms-wheel-dist-copy-final.fCl5gq/specialist_model_studio-0.9.0rc1-py3-none-any.whl`; SHA-256 `be7d8388af301f5b7b8a26359f333c34f8915f7db885b980fc85d433dd742823` | verified |
| Wheel contents | deleted `model_harness/chat.py` absent; new multi-agent/action/stream/ObjectRef/payload code and final web assets present | verified |
| Outside-cwd CLI | final wheel installed into a clean temporary venv and the project venv; `specialist-model-studio 0.9.0rc1` and `list-recipes` ran outside the repository | verified |

## Residual product boundary

- Any public Hugging Face or GitHub repository may enter source discovery,
  immutable resolution and bounded static diagnosis.
- A repository may proceed to plan and resource feasibility only when upstream
  evidence permits it. A typed source, license, analysis or environment blocker
  is a valid terminal result.
- Only a verified Recipe plus matching Data Adapter and explicit human gates
  may create a TrainingRun. This RC does not claim arbitrary repository
  fine-tuning, third-party code execution, dependency installation or cloud
  scheduling.
- The Figma reference informs the dialogue-first layout and on-demand Inspector;
  it does not provide runtime state or completion evidence.

## Current release state

```text
implemented = true
locally_verified = true
user_accepted = pending
github_pushed = false/not performed
ci_verified = unknown/not performed
cold_clone_verified = unknown/not performed
released = false
```
