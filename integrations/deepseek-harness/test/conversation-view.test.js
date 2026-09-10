import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const ConversationView = require("../../../model_harness/web/conversation-view.js");

test("conversation view preserves only the backend owner identity for sidebar state", () => {
  const remoteConversation = { schema_version: "2", session_id: "session", task_id: "task-1", items: [] };
  assert.equal(ConversationView.buildConversationView({ remoteConversation }).task_id, "task-1");
  const { task_id, ...withoutIdentity } = remoteConversation;
  assert.equal(ConversationView.buildConversationView({ remoteConversation: withoutIdentity }).task_id, null);
});

function event(eventType, values = {}) {
  return {
    event_id: values.event_id || `${eventType}-${values.seq || 1}`,
    turn_id: values.turn_id || "turn-1",
    seq: values.seq || 1,
    time: values.time || "2026-08-24T09:00:00Z",
    event_type: eventType,
    status: values.status || "completed",
    ...values,
  };
}

test("schema v2 keeps raw events for audit and uses backend actions as the only paired truth", () => {
  const remoteConversation = {
    schema_version: "2",
    action_schema_version: "1.0",
    session_id: "session-1",
    running: false,
    execution_running: false,
    interaction_state: "idle",
    can_cancel_agent: false,
    items: [
      { kind: "message", role: "user", event_id: "user-1", seq: 1, text: "训练普通话 ASR" },
      event("coordinator_plan", { seq: 2, actor_role: "orchestrator", title: "先研究再判断资源", steps: [{ step_id: "source", title: "查找来源", owner_role: "research_source", status: "completed" }] }),
      event("delegation", { seq: 3, to_role: "research_source", summary: "查找公开 ASR 训练来源" }),
      event("specialist_status", { seq: 4, actor_role: "research_source", status: "running", summary: "正在检索" }),
      event("tool_call", { seq: 5, actor_role: "research_source", status: "running", call_id: "call-1", tool_name: "search_model_sources", summary: "搜索 Hugging Face 与 GitHub" }),
      event("tool_result", { seq: 6, actor_role: "research_source", call_id: "call-1", result: "找到 4 个候选", object_refs: [{ type: "source_search", id: "search-1" }] }),
      event("specialist_output", { seq: 7, actor_role: "research_source", title: "候选集合已生成", summary: "保留两个可审查候选" }),
      event("final_synthesis", {
        seq: 8,
        actor_role: "orchestrator",
        task_id: "task-1",
        summary: "已完成来源研究，下一步确认模型。",
        payload: {
          synthesis_verdict: { accepted: true, evidence_digest: "digest-1" },
          object_refs: [{ type: "model_source_search", id: "search-1", task_id: "task-1" }],
        },
      }),
    ],
    actions: [{
      schema_version: "1.0",
      action_id: "action-1",
      task_id: "task-1",
      agent_run_id: "run-1",
      session_id: "session-1",
      turn_id: "turn-1",
      call_id: "call-1",
      tool_name: "model_harness_search_model_sources",
      tool_class: "domain",
      actor_role: "research_source",
      started_at_utc: "2026-08-24T09:00:04Z",
      ended_at_utc: "2026-08-24T09:00:05Z",
      duration_ms: 1000,
      status: "completed",
      delegation_id: "delegation-1",
      parent_delegation_id: "delegation-root",
      object_refs: [{ type: "source_search", id: "search-1", task_id: "task-1" }],
      event_result_ref: null,
      error: null,
      truth_type: "observed_result",
      call_event_id: "tool_call-5",
      result_event_id: "tool_result-6",
    }],
    agents: [{
      agent_id: "research_source",
      role_id: "research_source",
      status: "completed",
      lineage_verified: true,
    }],
    delegations: [{
      delegation_id: "delegation-1",
      target_agent_id: "research_source",
      target_agent_label: "Research & Source Agent",
    }],
  };
  const view = ConversationView.buildConversationView({
    remoteConversation,
    ledgerItems: [{ kind: "system_record", evidenceKey: "synthetic-1", label: "不应混入" }],
  });

  assert.equal(view.live_v2, true);
  assert.equal(view.execution_running, false);
  assert.equal(view.interaction_state, "idle");
  assert.equal(view.can_cancel_agent, false);
  assert.deepEqual(view.items.map((item) => item.kind), ["message", "coordinator_plan", "team_activity", "final_synthesis"]);
  assert.equal(view.items.some((item) => item.kind === "evidence_ledger"), false);
  const team = view.items.find((item) => item.kind === "team_activity");
  assert.ok(team);
  assert.equal(team.events.filter((item) => item.kind === "tool_call").length, 1);
  assert.equal(team.events.filter((item) => item.kind === "tool_result").length, 1);
  assert.equal(team.events.find((item) => item.kind === "tool_call").result, null);
  assert.equal(view.actions.length, 1);
  assert.deepEqual(view.actions[0], {
    kind: "action",
    schema_version: "1.0",
    action_id: "action-1",
    render_key: "action-1",
    task_id: "task-1",
    agent_run_id: "run-1",
    session_id: "session-1",
    turn_id: "turn-1",
    call_id: "call-1",
    tool_name: "model_harness_search_model_sources",
    tool_class: "domain",
    actor_role: "research_source",
    started_at_utc: "2026-08-24T09:00:04Z",
    ended_at_utc: "2026-08-24T09:00:05Z",
    duration_ms: 1000,
    status: "completed",
    active_type: null,
    delegation_id: "delegation-1",
    parent_delegation_id: "delegation-root",
    object_refs: [{ type: "source_search", id: "search-1", task_id: "task-1" }],
    event_result_ref: null,
    error: null,
    truth_type: "observed_result",
    call_event_id: "tool_call-5",
    result_event_id: "tool_result-6",
  });
  assert.equal(view.action_schema_version, "1.0");
  assert.deepEqual(view.agents, [{
    agent_id: "research_source",
    role_id: "research_source",
    status: "completed",
    lineage_verified: true,
  }]);
  assert.deepEqual(view.delegations, [{
    delegation_id: "delegation-1",
    target_agent_id: "research_source",
    target_agent_label: "Research & Source Agent",
  }]);
  assert.equal(view.items.filter((item) => item.kind === "final_synthesis").length, 1);
  assert.equal(view.items.find((item) => item.kind === "final_synthesis").completion_eligible, true);
});

test("canonical background training state survives without a frontend action", () => {
  const remoteActiveEvent = {
    object_type: "TrainingRun",
    task_id: "task-1",
    training_run_id: "training-run-1",
    status: "training",
  };
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      session_id: "session-training",
      agent_response_running: false,
      background_action_running: true,
      interaction_projection: {
        phase: "executing",
        turn_identity: { agent_turn_id: "turn-1", agent_run_id: "agent-run-1" },
      },
      active_event: remoteActiveEvent,
      items: [],
      actions: [],
      runs: [],
      agent_turns: [
        { object_type: "AgentTurn", agent_turn_id: "turn-1", status: "completed" },
        { object_type: "TrainingRun", training_run_id: "wrong-list" },
      ],
      training_runs: [
        { object_type: "TrainingRun", task_id: "task-1", training_run_id: "training-run-1", status: "training", running: true },
        { object_type: "AgentTurn", agent_turn_id: "wrong-type" },
      ],
      background_actions: [{ action_type: "training_run", task_id: "task-1", run_id: "training-run-1", status: "running" }],
      human_checkpoints: [],
      risks: [{ code: "resource_pressure" }],
      primary_attention: { object_type: "TrainingRun", object_id: "training-run-1" },
      supported_modes: ["queue_after_turn"],
    },
  });

  assert.equal(view.agent_response_running, false);
  assert.equal(view.background_action_running, true);
  assert.deepEqual(view.interaction_projection.turn_identity, { agent_turn_id: "turn-1", agent_run_id: "agent-run-1" });
  assert.deepEqual(view.active_event, remoteActiveEvent);
  assert.equal(view.training_runs.length, 1);
  assert.equal(view.training_runs[0].training_run_id, "training-run-1");
  assert.equal(view.agent_turns.length, 1);
  assert.equal(view.background_actions[0].action_type, "training_run");
  assert.deepEqual(view.supported_modes, ["queue_after_turn"]);
});

test("action view models preserve backend classes, terminal states, refs, lineage, timing, and errors", () => {
  const actions = ConversationView.normalizeActions([
    {
      action_id: "domain-running",
      tool_name: "model_harness_train",
      tool_class: "domain",
      actor_role: "build_training",
      started_at_utc: "2026-08-25T00:00:00Z",
      status: "running",
      delegation_id: "delegation-child",
      parent_delegation_id: "delegation-parent",
      object_refs: [],
      event_result_ref: null,
      truth_type: "observed_call",
    },
    {
      action_id: "control-completed",
      tool_name: "list_agents",
      tool_class: "control",
      status: "completed",
      ended_at_utc: "2026-08-25T00:00:01Z",
      duration_ms: 250,
      event_result_ref: {
        type: "conversation_event_result",
        id: "result-event-1",
        task_id: "task-1",
        projector_revision: "3.0",
        event_seq: 2,
        source_key: "result-source-1",
      },
    },
    {
      action_id: "delegation-failed",
      tool_name: "spawn_agent",
      tool_class: "delegation",
      status: "failed",
      error: { code: "tool_result_error", message: "agent failed" },
    },
    {
      action_id: "identity-error",
      tool_class: "unknown",
      status: "identity_error",
      error: { code: "orphan_tool_result", message: "no call" },
    },
  ]);

  assert.deepEqual(actions.map((action) => [action.tool_class, action.status]), [
    ["domain", "running"],
    ["control", "completed"],
    ["delegation", "failed"],
    ["unknown", "identity_error"],
  ]);
  assert.equal(actions[0].active_type, "domain_action");
  assert.equal(actions[0].delegation_id, "delegation-child");
  assert.equal(actions[0].parent_delegation_id, "delegation-parent");
  assert.equal(actions[1].duration_ms, 250);
  assert.equal(actions[1].event_result_ref.id, "result-event-1");
  assert.deepEqual(actions[2].error, { code: "tool_result_error", message: "agent failed" });
  assert.deepEqual(actions[3].error, { code: "orphan_tool_result", message: "no call" });
});

test("malformed backend actions fail closed instead of gaining frontend identity", () => {
  const [missingIdentity, invalidStatus] = ConversationView.normalizeActions([
    { tool_class: "domain", status: "running" },
    { action_id: "action-invalid-status", tool_class: "domain", status: "queued" },
  ]);

  assert.equal(missingIdentity.action_id, null);
  assert.match(missingIdentity.render_key, /^invalid-action:/);
  assert.equal(missingIdentity.status, "identity_error");
  assert.equal(missingIdentity.active_type, null);
  assert.equal(missingIdentity.error.code, "missing_action_id");
  assert.equal(invalidStatus.status, "identity_error");
  assert.equal(invalidStatus.error.code, "invalid_action_status");
});

test("raw tool call and result events never manufacture an action when conversation.actions is absent", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-no-actions",
      items: [
        event("tool_call", { seq: 1, call_id: "same-call", status: "running" }),
        event("tool_result", { seq: 2, call_id: "same-call", status: "completed", result: "looks pairable" }),
      ],
    },
  });

  assert.deepEqual(view.actions, []);
  const rawEvents = view.items[0].events;
  assert.deepEqual(rawEvents.map((item) => item.kind), ["tool_call", "tool_result"]);
  assert.equal(rawEvents[0].result, null);
  assert.equal(rawEvents[1].result, "looks pairable");
});

test("a terminal turn invalidates its stale pending checkpoint", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-terminal",
      interaction_state: "waiting_for_human",
      items: [
        event("question", { seq: 1, turn_id: "turn-terminal", rpc_id: "rpc-stale", status: "pending" }),
        event("turn_error", { seq: 2, turn_id: "turn-terminal", status: "failed", summary: "question tool failed" }),
      ],
      pending: [{ kind: "question", rpc_id: "rpc-stale", turn_id: "turn-terminal", status: "pending" }],
      actions: [],
    },
  });

  const checkpoint = view.items.find((item) => item.kind === "question");
  assert.equal(checkpoint.status, "invalidated");
  assert.equal(checkpoint.invalidated_by_event_id, "turn_error-2");
  assert.equal(view.active_event, null);
});

test("compact-v1 result preview is explicit and keeps the exact event result ref", () => {
  const eventResultRef = {
    type: "conversation_event_result",
    id: "result-event-large",
    task_id: "task-1",
    projector_revision: "3.1",
    event_seq: 9,
    source_key: "dsh:3.1:session-1:9:tool/result",
  };
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      event_payload_mode: "compact-v1",
      session_id: "session-1",
      items: [event("tool_result", {
        payload: {
          result_preview: "前 800 字符的脱敏结果…",
          result_truncated: true,
          result_size_bytes: 8192,
          event_result_ref: eventResultRef,
        },
      })],
      actions: [],
    },
  });

  const normalized = view.items[0].events[0];
  assert.equal(view.event_payload_mode, "compact-v1");
  assert.equal(normalized.result, "前 800 字符的脱敏结果…");
  assert.equal(normalized.result_preview, "前 800 字符的脱敏结果…");
  assert.equal(normalized.result_truncated, true);
  assert.equal(normalized.result_is_preview, true);
  assert.equal(normalized.result_size_bytes, 8192);
  assert.match(normalized.result_notice, /仅显示.*预览/);
  assert.deepEqual(normalized.event_result_ref, eventResultRef);
});

test("active state has an explicit fail-closed whitelist", () => {
  assert.deepEqual(ConversationView.ACTIVE_EVENT_TYPES, [
    "domain_action",
    "running_delegation",
    "pending_human_checkpoint",
  ]);
  const passiveView = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-active-passive",
      active_event: event("warning", { status: "running" }),
      items: [
        event("specialist_status", { status: "running" }),
        event("warning", { status: "running" }),
        event("coordinator_note", { status: "running" }),
        event("final_synthesis", {
          seq: 4,
          actor_role: "orchestrator",
          task_id: "task-active",
          payload: {
            synthesis_verdict: { accepted: true },
            object_refs: [{ type: "evaluation_report", id: "report-1", task_id: "task-active" }],
          },
        }),
      ],
      actions: [
        { action_id: "control-running", tool_class: "control", status: "running" },
        { action_id: "domain-complete", tool_class: "domain", status: "completed" },
        { action_id: "delegation-complete", tool_class: "delegation", status: "completed" },
      ],
    },
  });
  assert.equal(passiveView.active_event, null);

  const domainView = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-active-domain",
      items: [],
      actions: [{ action_id: "domain-running", tool_class: "domain", status: "running", actor_role: "build_training" }],
    },
  });
  assert.equal(domainView.active_event.action_id, "domain-running");
  assert.equal(domainView.active_event.active_type, "domain_action");

  const delegationView = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-active-delegation",
      items: [],
      actions: [{ action_id: "delegation-running", tool_class: "delegation", status: "running" }],
    },
  });
  assert.equal(delegationView.active_event.active_type, "running_delegation");
});

test("local and legacy modes render persisted facts as an explicit evidence ledger", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: null,
    localItems: [{ kind: "message", role: "user", text: "识别零件缺陷", time: "2026-08-24T09:00:00Z" }],
    ledgerItems: [
      { kind: "system_record", evidenceKey: "spec:1", label: "需求版本 v1 已确认", detail: "image / classification" },
      { kind: "system_record", evidenceKey: "search:1", label: "模型搜索记录", detail: "3 个候选" },
    ],
  });

  assert.equal(view.live_v2, false);
  assert.deepEqual(view.items.map((item) => item.kind), ["message", "evidence_ledger"]);
  assert.equal(view.items[1].items.every((item) => item.kind === "system_record"), true);
  assert.equal(view.items.some((item) => item.kind === "final_synthesis"), false);
});

test("unknown events and invalid specialist synthesis fail visibly", () => {
  const remoteConversation = {
    schema_version: "2",
    session_id: "session-2",
    items: [
      event("provider_magic", { seq: 1, summary: "unrecognized" }),
      event("final_synthesis", { seq: 2, actor_role: "research_source", summary: "专家不能充当协调器" }),
    ],
  };
  const view = ConversationView.buildConversationView({ remoteConversation });
  assert.deepEqual(view.items.map((item) => item.kind), ["unknown_event", "unknown_event"]);
  assert.match(view.items[1].contract_error, /orchestrator/);
});

test("pending approvals and questions join the stream once by rpc identity", () => {
  const approval = event("approval", { seq: 2, event_id: "approval-event", rpc_id: "rpc-1", status: "pending", title: "启动训练" });
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-3",
      items: [approval],
      pending: [
        { kind: "approval", rpc_id: "rpc-1", title: "重复批准" },
        { kind: "question", rpc_id: "rpc-2", questions: [{ id: "metric", question: "使用哪个指标？" }] },
      ],
    },
  });
  assert.deepEqual(view.items.map((item) => item.kind), ["approval", "question"]);
  assert.equal(view.items.filter((item) => item.rpc_id === "rpc-1").length, 1);
  assert.equal(view.active_event.kind, "question");
  assert.equal(view.active_event.rpc_id, "rpc-2");
});

test("live pending details enrich the durable checkpoint audit event", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      session_id: "session-checkpoint",
      items: [event("question", { seq: 4, rpc_id: "rpc-question", questions: [], summary: null })],
      pending: [
        {
          kind: "question",
          rpc_id: "rpc-question",
          questions: [{ id: "confirm", header: "确认任务规格", question: "这是语音识别任务吗？" }],
        },
      ],
    },
  });

  assert.equal(view.items.length, 1);
  assert.equal(view.items[0].status, "pending");
  assert.equal(view.items[0].questions[0].header, "确认任务规格");
  assert.equal(view.items[0].questions[0].question, "这是语音识别任务吗？");
});

test("resolved human checkpoints collapse stale requests by canonical rpc identity", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      session_id: "session-resolved-checkpoint",
      items: [
        event("question", {
          seq: 9,
          event_id: "question-requested",
          rpc_id: "rpc-resolved",
          status: "pending",
          questions: [{ id: "target", question: "需要什么输出？" }],
        }),
        event("question", {
          seq: 10,
          event_id: "question-resolved",
          rpc_id: "rpc-resolved",
          status: "completed",
          summary: "已回答",
        }),
      ],
      pending: [],
    },
  });

  const checkpoints = view.items.filter((item) => item.rpc_id === "rpc-resolved");
  assert.equal(checkpoints.length, 1);
  assert.equal(checkpoints[0].status, "completed");
  assert.equal(checkpoints[0].event_id, "question-resolved");
  assert.equal(view.active_event, null);
});

test("pending websocket timestamps in seconds normalize to browser milliseconds", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      session_id: "session-time",
      items: [],
      pending: [
        {
          kind: "question",
          rpc_id: "rpc-time",
          received_at: 1_787_553_177.5,
          questions: [{ id: "confirm", question: "确认任务吗？" }],
        },
      ],
    },
  });

  assert.equal(view.items[0].time, 1_787_553_177_500);
});

test("final synthesis without an explicit status never defaults to completed", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-final-status",
      items: [
        {
          event_id: "final-without-status",
          event_type: "final_synthesis",
          actor_role: "orchestrator",
          summary: "这只是一次综合说明，没有完成状态证据。",
        },
      ],
    },
  });

  assert.equal(view.items[0].kind, "final_synthesis");
  assert.equal(view.items[0].status, "unknown");
  assert.notEqual(view.items[0].status, "completed");
});

test("final synthesis needs both classifier permission and evidence refs before showing completed", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2",
      session_id: "session-final-gate",
      items: [
        event("final_synthesis", {
          event_id: "final-without-classifier",
          seq: 1,
          task_id: "task-1",
          actor_role: "orchestrator",
          object_refs: [{ type: "evaluation_report", id: "report-1", task_id: "task-1" }],
        }),
        event("final_synthesis", {
          event_id: "final-without-evidence",
          seq: 2,
          task_id: "task-1",
          actor_role: "orchestrator",
          payload: { synthesis_verdict: { accepted: true, evidence_digest: "digest-2" } },
        }),
        event("final_synthesis", {
          event_id: "final-accepted",
          seq: 3,
          task_id: "task-1",
          actor_role: "orchestrator",
          truth_type: "unverified_narration",
          payload: {
            synthesis_verdict: { accepted: true, evidence_digest: "digest-3" },
            object_refs: [{ type: "evaluation_report", id: "report-3", task_id: "task-1" }],
          },
        }),
      ],
    },
  });

  const [withoutClassifier, withoutEvidence, accepted] = view.items;
  assert.equal(withoutClassifier.status, "observed");
  assert.equal(withoutClassifier.completion_eligible, false);
  assert.match(withoutClassifier.contract_error, /classifier permission/);
  assert.equal(withoutEvidence.status, "observed");
  assert.equal(withoutEvidence.completion_eligible, false);
  assert.match(withoutEvidence.contract_error, /evidence object_refs/);
  assert.equal(accepted.status, "completed");
  assert.equal(accepted.completion_eligible, true);
  assert.equal(accepted.truth_type, "evidence_backed_final");
  assert.equal(accepted.contract_error, null);
});

test("typed failure blocker warning and observation states survive normalization", () => {
  const cases = [
    [{ event_type: "failed" }, "failed"],
    [{ event_type: "BlockerEvidence" }, "blocker"],
    [{ event_type: "warning" }, "warning"],
    [{ event_type: "observation_degraded" }, "observation_degraded"],
    [{ event_type: "tool.result", status: "BlockerEvidence" }, "blocker"],
  ];

  cases.forEach(([input, expected], index) => {
    const normalized = ConversationView.normalizeEvent({ event_id: `typed-${index}`, ...input }, index, true);
    assert.equal(normalized.status, expected);
    assert.equal(normalized.truth_type, expected);
  });
});

test("projection errors use one reducer contract and degrade observation health", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: {
      schema_version: "2.0",
      session_id: "root-session",
      items: [event("tool_result", { status: "failed", call_id: "orphan-result" })],
      projection_errors: [
        { session_id: "child-session", error: "dsh_subagent_lineage_mismatch" },
        { event_id: "source-event-2", code: "payload_missing", message: "工具结果缺少 payload", severity: "warning" },
      ],
    },
  });

  assert.equal(view.projection_health.status, "observation_degraded");
  assert.equal(view.projection_health.projection_error_count, 2);
  assert.deepEqual(view.projection_errors[0], {
    kind: "projection_error",
    error_id: "child-session:turn-unknown:dsh_subagent_lineage_mismatch:1",
    code: "dsh_subagent_lineage_mismatch",
    message: "dsh_subagent_lineage_mismatch",
    severity: "observation_degraded",
    session_id: "child-session",
    turn_id: null,
    source_event_id: null,
    details: null,
  });
  assert.equal(view.projection_errors[1].severity, "warning");
  assert.equal(view.projection_errors[1].source_event_id, "source-event-2");
  assert.equal(view.projection_health.typed_event_counts.failed, 1);
  assert.deepEqual(view.projection_health.typed_projection_error_counts, {
    failed: 0,
    blocker: 0,
    warning: 1,
    observation_degraded: 1,
  });
});

test("projection health does not claim live observation for a legacy reducer view", () => {
  const view = ConversationView.buildConversationView({
    remoteConversation: null,
    localItems: [{ kind: "message", role: "user", text: "离线任务" }],
  });

  assert.equal(view.projection_health.status, "not_observed");
  assert.equal(view.projection_health.projection_error_count, 0);
});

test("training capability never treats not_checked as an environment blocker", () => {
  const completed = ConversationView.trainingCapabilityProjection({
    status: "completed",
    capability_status: "matched",
    recipe_id: "tabular-regression",
    resource_feasibility: { decision: "not_checked", blockers: [] },
    current_run_id: "run-1",
    current_result: {
      status: "completed",
      run_id: "run-1",
      evaluation_report: { run_id: "run-1", release_ready: true },
    },
  });
  const ready = ConversationView.trainingCapabilityProjection({
    status: "data_ready",
    capability_status: "matched",
    recipe_id: "tabular-regression",
    resource_feasibility: { decision: "not_checked", blockers: [] },
  });
  const blocked = ConversationView.trainingCapabilityProjection({
    status: "needs_recipe",
    capability_status: "needs_recipe",
    capability_decision: { selected_family: "asr" },
    resource_feasibility: {
      decision: "blocked_resources",
      blockers: [{ message: "内存不足" }],
    },
  });

  assert.deepEqual(
    { code: completed.code, label: completed.label, state: completed.state },
    { code: "trained_with_evaluation", label: "已完成真实训练", state: "completed" },
  );
  assert.equal(ready.code, "available_verified_recipe");
  assert.equal(ready.state, "available");
  assert.equal(blocked.code, "blocked_resources");
  assert.equal(blocked.state, "blocked");
  assert.equal(blocked.reason, "内存不足");
});

test("visible training actions have product language labels", () => {
  assert.equal(ConversationView.TOOL_LABELS.model_harness_update_task_spec, "确认任务理解");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_start_task_run, "启动真实训练");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_search_model_sources, "联网搜索模型候选");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_authorize_task_run_start, "申请启动本次训练");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_authorize_artifact_bundle_build, "申请构建本次交付包");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_build_artifact_bundle, "构建可下载交付包");
  assert.equal(ConversationView.TOOL_LABELS.model_harness_download_artifact_bundle, "确认并下载交付包");
  assert.equal(ConversationView.TOOL_LABELS.report, "专家已回传结论");
});
