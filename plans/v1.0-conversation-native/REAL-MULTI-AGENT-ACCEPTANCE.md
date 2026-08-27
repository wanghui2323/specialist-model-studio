# Real Multi-Agent Acceptance Record

Date: 2026-08-24
Scope: local review candidate, not a published release

> Historical record: this file preserves the pre-v1.0 acceptance snapshot and
> its then-current test counts. It is not the current RC verdict. Current
> implementation and verification evidence is recorded in
> `L6-LOCAL-RC-EVIDENCE.md`.

## Acceptance decision

The conversation runtime is a real DSH-native multi-agent implementation. It is no longer a frontend simulation of specialist activity.

The product remains evidence-gated: this acceptance proves orchestration, delegation, lineage, tool execution, checkpoint persistence and browser projection. It does **not** claim that ASR was trained or that every public model repository is executable.

## Provider-backed run

| Fact | Observed value |
|---|---|
| Provider/model | `deepseek-official / deepseek-v4-pro` |
| TrainingTask | `真实多智能体-ASR-验收-7232e17a` |
| Root role/session | `training_orchestrator` / `session-91796c89-9e43-4820-958b-2c65ed313f31` |
| Research child | `research_source` / `12f532d0-613c-4a0e-9183-8c69dbcee133` |
| Resource child | `resource_safety` / `9563b3c9-26a0-4ac7-bc05-3ef5dce0a779` |
| Child lineage | both `origin=subagent`, parent is the root session, `lineage_verified=true` |
| Delegations | 2 completed native delegate calls |
| Specialist outputs | 2 completed independent reports |
| Final synthesis | exactly 1, owned by the Training Orchestrator |
| Current run | `waiting_for_human` |
| Pending checkpoint | question RPC `aa0e932f-07e5-43ba-b16f-ae4e7a2634df` |
| Projection errors | none |

The research and resource specialists used their own DSH sessions and role-scoped `model_harness_*` tool allowlists. The research child issued 13 domain calls and the resource child issued 5. The remaining root tool activity covered task reading, native delegation/control and the unresolved human question. The pending question is intentionally not answered by the acceptance run.

## Product projection

The canonical local UI at `http://127.0.0.1:8802/app?task=真实多智能体-ASR-验收-7232e17a` was checked in a desktop viewport and a CDP-emulated 390 × 844 mobile viewport.

- one coordinator conversation is shown;
- specialist activity is folded into auditable team groups;
- completed specialists with expected 404/409 evidence are labelled `已结束 · 受控阻断`, not falsely shown as unfinished;
- exactly one live question card is visible;
- the live activity label reads `等待你的回答：确认任务规格` instead of reusing a stale specialist status;
- the final synthesis renders headings, lists, code and a horizontally scrollable table;
- document horizontal overflow is 0 in both viewports;
- no answer, approval, download, binding or training action was submitted during browser QA.

## Reliability and truth boundaries

- `TrainingTask` remains the only domain truth source. DSH sessions and frontend cards do not own training state.
- The current projector revision filters legacy simulated projections from the live product view.
- Human question request/resolution events are durable and correlated by RPC id; answer text is not persisted into the audit projection.
- Child transcripts are accepted only after DSH parent/origin lineage validation.
- A process-level writer lease rejects a second backend targeting the same `runs/` directory.
- The five specialist agents have role-specific allowlists and no shell, browser, generic coding or recursive delegation authority.
- An unregistered model family remains unsupported even when research finds candidate repositories. ASR currently has no verified executable Recipe in this engine.

## Remaining human gate for the ASR task

The run is correctly paused on `确认任务规格`: whether the goal is ASR for offline Mandarin long recordings with timestamped Simplified-Chinese output. Until the user answers, the system must not bind a candidate, download a model, create a training plan or run training.

## Verification gates

- Python: `418` tests passed.
- Node/adapter/frontend contracts: `41` tests passed.
- JavaScript syntax: product renderer, conversation projector and DSH adapter passed.
- Shell syntax: conversation start and preset install scripts passed.
- Patch hygiene: `git diff --check` passed.
- Writer isolation negative test: a second backend on port 8805 targeting the active `runs/` directory exited with code 3 and `RunsWorkspaceLeaseError` before startup completed.

## Release boundary

This record is local acceptance evidence. It is not proof of a GitHub push, tag, packaged release, cold-clone installation or successful ASR training.

## Canonical 8802 cutover addendum

- The stale 8802 backend and the temporary 8804 review backend were stopped by exact PID; the current 8802 backend and DSH runtime share the repository `runs/` workspace.
- Four non-empty tasks from the legacy 8802 store were copied into the canonical workspace after both stores were backed up. The original stores remain recoverable.
- `/runtime` now exposes and validates `source_root`, `runs_dir`, `workspace_dir` and `conversation_origin`; the startup script rejects a healthy-looking process whose identity does not match.
- The current contract is `dsh_native_subagents`, conversation schema `2.0`, projector revision `3.0`, synthesis verdict `1.0`, and domain truth source `TrainingTask`.
- The existing voice-model task keeps its original task id and TaskSpec revision. No Agent message was sent on the user's behalf during cutover or QA.
- A real provider-backed acceptance task projects two completed native delegations, specialist tool activity, one orchestrator synthesis and one unresolved human question.
- The task screen no longer opens a fixed workflow drawer from stage changes. Free text is accepted only by the conversation runtime, and an unavailable or incompatible runtime fails closed.
- Agent-produced model-search references bind to the exact persisted `search_id`; missing or mismatched references fail visibly instead of opening a generic plan panel.
- Desktop evidence keeps dialogue primary with the evidence workspace closed by default. CDP mobile metrics were `innerWidth=390`, `document.scrollWidth=390` and `conversation.scrollWidth=390`.
