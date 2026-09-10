import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const InteractionShell = require("../../../model_harness/web/interaction-shell.js");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
  }

  append(...children) {
    children.forEach((child) => {
      child.parentNode = this;
      this.children.push(child);
    });
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName);
  }
}

function directChildrenByClass(node, className) {
  return node.children.filter((child) => child.className.split(/\s+/).includes(className));
}

function descendantsByClass(node, className) {
  return node.children.flatMap((child) => [
    ...(child.className.split(/\s+/).includes(className) ? [child] : []),
    ...descendantsByClass(child, className),
  ]);
}

function mountStopControl(documentRef, header, presentation) {
  if (!InteractionShell.canShowTurnStop(presentation)) return null;
  const stop = documentRef.createElement("button");
  stop.className = "ai-turn-stop";
  header.append(stop);
  return stop;
}

function action(values = {}) {
  return {
    action_id: values.action_id || "action-1",
    task_id: values.task_id || "task-1",
    turn_id: values.turn_id || "turn-1",
    tool_class: values.tool_class || "domain",
    actor_role: values.actor_role || "orchestrator",
    status: values.status || "completed",
    object_refs: values.object_refs || [],
    ...values,
  };
}

function projection(task, conversation) {
  return InteractionShell.deriveInteractionProjection({ task, conversation });
}

function workItem(values = {}) {
  return {
    work_item_id: values.work_item_id || "work-item-1",
    task_id: values.task_id || "task-1",
    agent_run_id: values.agent_run_id || "agent-run-1",
    delegation_id: values.delegation_id || "delegation-1",
    parent_delegation_id: values.parent_delegation_id || null,
    child_session_id: values.child_session_id || "child-session-1",
    lineage_verified: values.lineage_verified ?? true,
    role: values.role || { agent_id: "research-source-agent", role_id: "research_source", label: "研究与来源" },
    assignment: values.assignment || { summary: "核对候选模型来源", source_field: "description" },
    status: values.status || "active",
    actions: values.actions || [],
    object_refs: values.object_refs || [],
    ...values,
  };
}

test("a finished background cancellation cannot lock a new native approval", () => {
  const finished = { task_id: "task-1", action_type: "model_binding_analysis", status: "cancelled", domain_status: "cancelled", cancel_requested: true, running: false, worker_running: false };
  const conversation = { schema_version: "2.0", items: [{ kind: "approval", event_id: "approval-new", turn_id: "turn-new", status: "pending", rpc_id: "rpc-new" }], background_actions: [finished] };
  const restored = projection({ task_id: "task-1" }, conversation);
  assert.equal(restored.phase, "awaiting_approval");
  assert.equal(restored.background.cancelling, false);
  assert.equal(projection({ task_id: "task-1" }, { ...conversation, background_actions: [{ ...finished, worker_running: true }] }).background.cancelling, true);
  assert.equal(projection({ task_id: "task-1" }, { ...conversation, background_actions: [{ ...finished, status: "cancel_requested" }] }).background.cancelling, true);
  const training = projection({ task_id: "task-1" }, { ...conversation, background_actions: [{ ...finished, action_type: "training_run", run_id: "run-old" }] });
  assert.equal(training.phase, "awaiting_approval");
  assert.equal(training.background.training_running, false);
});

test("AI turn DOM owns its execution timeline while the user node remains timeline-free", () => {
  const documentRef = new FakeDocument();
  const root = documentRef.createElement("main");
  const userMessage = documentRef.createElement("article");
  userMessage.className = "conversation-message user-message";
  InteractionShell.conversationTurnTarget({ role: "user", root }).append(userMessage);

  const frame = InteractionShell.createAiTurnFrame(documentRef, root, {
    turnId: "turn-1",
    state: "running",
    current: true,
  });
  const timeline = documentRef.createElement("details");
  timeline.className = "action-timeline";
  InteractionShell.conversationTurnTarget({ role: "assistant", root, aiContent: frame.content }).append(timeline);

  assert.equal(frame.content.className, "ai-turn-content");
  assert.equal(timeline.parentNode, frame.content, "the execution timeline must be inside the AI turn content");
  assert.equal(descendantsByClass(userMessage, "action-timeline").length, 0, "the user message must not own execution UI");
  assert.equal(directChildrenByClass(root, "action-timeline").length, 0, "the conversation root must not receive a loose execution timeline");
  assert.deepEqual(root.children.map((child) => child.className), ["conversation-message user-message", "ai-turn"]);
});

test("stop control fails closed outside canonical running or processing states", () => {
  const nonCancelableStates = [
    { phase: "waiting_question", tone: "needs_confirmation" },
    { phase: "waiting_approval", tone: "needs_confirmation" },
    { phase: "paused", status: "paused" },
    { phase: "stopped", tone: "cancelled" },
    { phase: "completed", tone: "completed" },
    { phase: "failed", tone: "failed" },
    { phase: "stopping", tone: "cancelling" },
  ];
  nonCancelableStates.forEach((state) => {
    assert.equal(
      InteractionShell.canShowTurnStop({ current: true, can_cancel: true, ...state }),
      false,
      `${state.phase} must remain non-cancelable even when can_cancel is contradictory`,
    );
  });
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: false, phase: "agent_working", tone: "running" }), false);
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: true, phase: "agent_working", status: "completed" }), false);
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: true, phase: "agent_working", tone: "running" }), true);
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: true, phase: "executing", status: "processing" }), true);

  const documentRef = new FakeDocument();
  const root = documentRef.createElement("main");
  const waiting = InteractionShell.createAiTurnFrame(documentRef, root, { turnId: "waiting", state: "needs_confirmation", current: true });
  const running = InteractionShell.createAiTurnFrame(documentRef, root, { turnId: "running", state: "running", current: true });
  mountStopControl(documentRef, waiting.header, { current: true, can_cancel: true, phase: "waiting_question", tone: "needs_confirmation" });
  mountStopControl(documentRef, running.header, { current: true, can_cancel: true, phase: "agent_working", tone: "running" });
  assert.equal(descendantsByClass(waiting.section, "ai-turn-stop").length, 0, "waiting must not render Stop");
  assert.equal(descendantsByClass(running.section, "ai-turn-stop").length, 1, "a cancelable running turn must render Stop");
});

test("groups render items by turn and seq while preserving stable source order", () => {
  const rawToolCall = { kind: "tool_call", event_id: "tool-call", turn_id: "turn-1", seq: 3, summary: "不要从我制造 action" };
  const rawToolResult = { kind: "tool_result", event_id: "tool-result", turn_id: "turn-1", seq: 4 };
  const turns = InteractionShell.groupConversationTurns({
    items: [
      { kind: "message", event_id: "user", turn_id: "turn-1", seq: 1 },
      {
        kind: "team_activity",
        event_id: "team:turn-1",
        turn_id: "turn-1",
        events: [rawToolResult, rawToolCall],
      },
      { kind: "coordinator_note", event_id: "note", turn_id: "turn-1", seq: 2 },
      { kind: "message", event_id: "next-user", turn_id: "turn-2", seq: 5 },
    ],
  });

  assert.equal(turns.length, 2);
  assert.equal(turns[0].turn_id, "turn-1");
  assert.deepEqual(turns[0].event_ids, ["user", "note", "tool-call", "tool-result"]);
  assert.equal(turns[0].items[2], rawToolCall);
  assert.deepEqual(turns[0].render_items.map((item) => item.event_id), ["user", "note", "team:turn-1"]);
  assert.equal(turns[0].first_seq, 1);
  assert.equal(turns[0].last_seq, 4);
  assert.deepEqual(turns[1].event_ids, ["next-user"]);
});

test("unscoped records remain separate instead of gaining an invented shared turn", () => {
  const turns = InteractionShell.groupConversationTurns({
    items: [
      { kind: "coordinator_note", event_id: "note-a" },
      { kind: "coordinator_note", event_id: "note-b" },
    ],
  });
  assert.equal(turns.length, 2);
  assert.equal(turns[0].turn_id, null);
  assert.notEqual(turns[0].group_key, turns[1].group_key);
});

test("one canonical AgentTurn owns root, child, unscoped checkpoint, and child actions", () => {
  const conversation = {
    agent_turns: [{ object_type: "AgentTurn", agent_turn_id: "agent-turn-1", agent_run_id: "agent-run-1" }],
    interaction_projection: { turn_identity: { agent_turn_id: "agent-turn-1" } },
    items: [
      { kind: "specialist_status", event_id: "team-status-unscoped", turn_id: "unscoped", agent_run_id: null, seq: 0 },
      { kind: "message", role: "user", event_id: "user-root", turn_id: "root-session:turn:1", agent_run_id: "agent-run-1", seq: 1, text: "训练一个模型" },
      {
        kind: "team_activity",
        event_id: "team-child",
        turn_id: "child-session:turn:1",
        events: [
          { kind: "specialist_status", event_id: "child-status", turn_id: "child-session:turn:1", agent_run_id: "agent-run-1", seq: 2 },
        ],
      },
      { kind: "question", event_id: "question-unscoped", turn_id: null, agent_run_id: "agent-run-1", seq: 3, rpc_id: "rpc-1", status: "pending" },
    ],
    actions: [
      action({ action_id: "root-action", turn_id: "root-session:turn:1", agent_run_id: "agent-run-1" }),
      action({ action_id: "child-action", turn_id: "child-session:turn:1", agent_run_id: "agent-run-1" }),
    ],
  };
  const result = projection({ task_id: "task-1" }, conversation);

  assert.equal(result.turns.length, 1, "raw root, child, and unscoped records must not create duplicate AI cards");
  assert.equal(result.current_turn.agent_turn_id, "agent-turn-1");
  assert.equal(result.turns.filter((turn) => turn.group_key === result.current_turn.group_key).length, 1);
  assert.deepEqual(new Set(result.current_turn.source_turn_ids), new Set(["root-session:turn:1", "child-session:turn:1"]));
  assert.deepEqual(result.current_actions.map((item) => item.action_id), ["root-action", "child-action"]);
  assert.equal(result.checkpoint.rpc_id, "rpc-1");

  const documentRef = new FakeDocument();
  const root = documentRef.createElement("main");
  const userNode = documentRef.createElement("article");
  userNode.className = "conversation-message user-message";
  InteractionShell.conversationTurnTarget({ role: "user", root }).append(userNode);
  result.turns.forEach((turn) => {
    const frame = InteractionShell.createAiTurnFrame(documentRef, root, { turnId: turn.agent_turn_id, current: turn === result.current_turn });
    const timeline = documentRef.createElement("details");
    timeline.className = "action-timeline";
    result.current_actions.forEach((item) => {
      const row = documentRef.createElement("div");
      row.dataset.actionId = item.action_id;
      timeline.append(row);
    });
    InteractionShell.conversationTurnTarget({ role: "assistant", root, aiContent: frame.content }).append(timeline);
  });
  assert.equal(directChildrenByClass(root, "ai-turn").length, 1);
  assert.equal(descendantsByClass(userNode, "action-timeline").length, 0);
  assert.equal(directChildrenByClass(root, "action-timeline").length, 0);
  assert.equal(descendantsByClass(directChildrenByClass(root, "ai-turn")[0], "action-timeline").length, 1);
});

test("backend turn identity selects exactly one current AgentTurn before max-seq fallback", () => {
  const result = projection({ task_id: "task-1" }, {
    agent_turns: [
      { object_type: "AgentTurn", agent_turn_id: "agent-turn-selected", agent_run_id: "agent-run-selected" },
      { object_type: "AgentTurn", agent_turn_id: "agent-turn-later", agent_run_id: "agent-run-later" },
    ],
    interaction_projection: { turn_identity: { agent_turn_id: "agent-turn-selected" } },
    items: [
      { kind: "coordinator_note", event_id: "selected", agent_run_id: "agent-run-selected", turn_id: "root:turn:1", seq: 4 },
      { kind: "coordinator_note", event_id: "later", agent_run_id: "agent-run-later", turn_id: "root:turn:2", seq: 99 },
    ],
    actions: [],
  });
  assert.equal(result.current_turn.agent_turn_id, "agent-turn-selected");
  assert.equal(result.turns.filter((turn) => turn.agent_turn_id === result.current_turn.agent_turn_id).length, 1);

  const fallback = InteractionShell.selectCurrentTurn(result.turns, {});
  assert.equal(fallback.agent_turn_id, "agent-turn-later");
});

test("a superseded historical failure remains auditable without an active-failure label", () => {
  const failed = action({ action_id: "failed-once", status: "failed" });
  const risks = [{
    source_type: "Action",
    source_id: "failed-once",
    active: false,
    lifecycle_status: "superseded",
    resolution: { kind: "superseded_by_later_success" },
  }];
  assert.equal(InteractionShell.turnHasActiveFailure({ items: [] }, [failed], risks), false);
  assert.deepEqual([...InteractionShell.supersededFailureSourceIds(risks)], ["failed-once"]);
  assert.equal(InteractionShell.turnHasActiveFailure({ items: [] }, [failed], []), true);
});

test("an idle recovered turn is not reclassified as failed by historical turn-error events", () => {
  const recoveredRisk = {
    source_type: "Action",
    source_id: "failed-once",
    active: false,
    lifecycle_status: "superseded",
    resolution: { kind: "superseded_by_later_success" },
  };
  const conversation = {
    agent_turns: [{
      object_type: "AgentTurn",
      agent_turn_id: "agent-turn-1",
      agent_run_id: "agent-run-1",
      status: "idle_without_final",
    }],
    interaction_projection: {
      schema_version: "1.0",
      phase: "idle",
      turn_identity: { agent_turn_id: "agent-turn-1", agent_run_id: "agent-run-1" },
    },
    items: [
      { kind: "turn_error", event_id: "transient-turn-error", agent_run_id: "agent-run-1", turn_id: "root:turn:1", seq: 1 },
      { kind: "coordinator_note", event_id: "recovered-note", agent_run_id: "agent-run-1", turn_id: "root:turn:1", seq: 2, text: "本轮诊断到此" },
    ],
    actions: [
      action({ action_id: "failed-once", agent_run_id: "agent-run-1", turn_id: "root:turn:1", status: "failed" }),
      action({ action_id: "later-success", agent_run_id: "agent-run-1", turn_id: "root:turn:1", status: "completed" }),
    ],
    risks: [recoveredRisk],
  };
  const result = projection({ task_id: "task-1", status: "needs_confirmation" }, conversation);
  assert.equal(result.phase, "idle");
  assert.equal(result.reason_code, "idle");
  assert.equal(result.observation.turn_failure, null);
  assert.equal(InteractionShell.turnHasActiveFailure(result.current_turn, result.current_actions, conversation.risks), false);
});

test("a canonical active turn risk still produces a failed interaction", () => {
  const conversation = {
    agent_turns: [{ object_type: "AgentTurn", agent_turn_id: "agent-turn-1", agent_run_id: "agent-run-1", status: "failed" }],
    items: [{ kind: "turn_error", event_id: "turn-error-1", agent_run_id: "agent-run-1", turn_id: "root:turn:1", seq: 1 }],
    actions: [],
    risks: [{
      source_type: "AgentTurn",
      source_id: "agent-turn-1",
      active: true,
      lifecycle_status: "active",
      resolution: null,
    }],
  };
  const result = projection({ task_id: "task-1" }, conversation);
  assert.equal(result.phase, "failed");
  assert.equal(result.reason_code, "turn_error");
});

test("pending questions and approvals drive distinct decision phases", () => {
  const clarifying = projection({ task_id: "task-1" }, {
    items: [{ kind: "question", event_id: "question-1", turn_id: "turn-1", seq: 1, rpc_id: "rpc-question", status: "pending" }],
    actions: [],
  });
  assert.equal(clarifying.phase, "clarifying");
  assert.equal(clarifying.workspace.mode, "decision");
  assert.equal(clarifying.workspace.context, "clarification");
  assert.equal(clarifying.checkpoint.rpc_id, "rpc-question");

  const approval = projection({ task_id: "task-1" }, {
    items: [{ kind: "approval", event_id: "approval-1", turn_id: "turn-1", seq: 1, rpc_id: "rpc-approval", status: "pending" }],
    actions: [],
  });
  assert.equal(approval.phase, "awaiting_approval");
  assert.equal(approval.workspace.context, "approval");
});

test("workspace auto-opens only for structured plan, data exception, or evaluation objects", () => {
  const ordinaryExecution = projection({ task_id: "task-1" }, {
    execution_running: true,
    items: [],
    actions: [action({
      action_id: "download-action",
      status: "running",
      tool_name: "model_harness_download_source_manifest",
    })],
  });
  assert.equal(ordinaryExecution.phase, "executing");
  assert.equal(ordinaryExecution.workspace.auto_open, false);
  assert.equal(ordinaryExecution.workspace.technical_context, "run");

  const liveTraining = projection({
    task_id: "task-1",
    current_result: { task_id: "task-1", run_id: "run-live", status: "training" },
  }, { items: [], actions: [] });
  assert.equal(liveTraining.phase, "executing");
  assert.equal(liveTraining.workspace.auto_open, false, "a live run remains available on demand instead of stealing focus");

  const remoteTrainingWithoutAction = projection({ task_id: "task-1" }, {
    items: [],
    actions: [],
    agent_response_running: false,
    background_action_running: true,
    training_runs: [{ object_type: "TrainingRun", task_id: "task-1", training_run_id: "run-remote", status: "training", running: true }],
  });
  assert.equal(remoteTrainingWithoutAction.phase, "executing");
  assert.deepEqual(remoteTrainingWithoutAction.background.training_run_ids, ["run-remote"]);
  assert.equal(remoteTrainingWithoutAction.workspace.auto_open, false);

  const planApproval = projection({ task_id: "task-1" }, {
    items: [{
      kind: "approval",
      event_id: "approve-plan",
      turn_id: "turn-plan",
      rpc_id: "rpc-plan",
      status: "pending",
      object_refs: [{ type: "training_plan", id: "plan-3", task_id: "task-1" }],
    }],
    actions: [],
  });
  assert.equal(planApproval.workspace.auto_open, true);
  assert.equal(planApproval.workspace.auto_reason, "plan_confirmation");
  assert.equal(planApproval.workspace.presentation, "technical");
  assert.equal(planApproval.workspace.technical_context, "plan");

  const dataException = projection({ task_id: "task-1" }, {
    items: [{
      kind: "blocker",
      event_id: "data-blocker",
      turn_id: "turn-data",
      status: "blocker",
      object_refs: [{ type: "dataset_report", id: "dataset-report-1", task_id: "task-1" }],
    }],
    actions: [],
  });
  assert.equal(dataException.workspace.auto_open, true);
  assert.equal(dataException.workspace.auto_reason, "data_exception");
  assert.equal(dataException.workspace.technical_context, "data");

  const staleEvaluationRef = projection({
    task_id: "task-1",
    current_result: { task_id: "task-1", run_id: "run-current", status: "completed" },
  }, {
    items: [],
    actions: [action({
      action_id: "old-evaluation",
      status: "completed",
      object_refs: [{ type: "evaluation_report", id: "report-old", task_id: "task-1" }],
    })],
  });
  assert.equal(staleEvaluationRef.phase, "result_ready");
  assert.equal(staleEvaluationRef.workspace.auto_open, false, "an evaluation ref from an older action cannot auto-open");

  const currentEvaluation = projection({
    task_id: "task-1",
    current_result: {
      task_id: "task-1",
      run_id: "run-current",
      status: "completed",
      evaluation_report: { task_id: "task-1", run_id: "run-current", report_sha256: "evaluation-digest-current", release_ready: false },
    },
  }, { items: [], actions: [] });
  assert.equal(currentEvaluation.workspace.auto_open, true);
  assert.equal(currentEvaluation.workspace.auto_reason, "evaluation_ready");
});

test("a later user turn makes the previous evaluation historical without changing its auto identity", () => {
  const task = {
    task_id: "task-1",
    current_run_id: "run-1",
    current_result: {
      task_id: "task-1",
      run_id: "run-1",
      status: "completed",
      completed_at_utc: "2026-08-26T01:00:00Z",
      evaluation_report: {
        task_id: "task-1",
        run_id: "run-1",
        event_id: "evaluation-event-1",
        completed_at_utc: "2026-08-26T01:00:00Z",
        release_ready: true,
      },
    },
  };
  const completed = projection(task, { items: [], actions: [] });
  assert.equal(completed.phase, "result_ready");
  assert.equal(completed.workspace.auto_open, true);

  const continued = projection(task, {
    items: [{ kind: "message", role: "user", event_id: "user-after-result", turn_id: "turn-after-result", seq: 10, time: "2026-08-26T01:01:00Z", text: "再优化一次" }],
    actions: [],
  });
  assert.equal(continued.phase, "idle");
  assert.equal(continued.result.ready, false);
  assert.equal(continued.result.superseded_by_new_turn, true);
  assert.equal(continued.workspace.auto_open, false);
  assert.equal(continued.workspace.auto_key, completed.workspace.auto_key);
  assert.equal(continued.workspace.auto_key, "task-1:evaluation:run-1:event_id:evaluation-event-1");
});

test("pending human checkpoints stay in the foreground above task-level blockers", () => {
  const blockedTask = {
    task_id: "task-1",
    status: "needs_recipe",
    control: {
      blocked_by: [{ code: "verified_recipe_unavailable", active: true }],
    },
  };
  const clarifying = projection(blockedTask, {
    items: [{ kind: "question", event_id: "question-1", turn_id: "turn-1", seq: 1, rpc_id: "rpc-question", status: "pending" }],
    actions: [],
  });
  assert.equal(clarifying.phase, "clarifying");
  assert.equal(clarifying.reason_code, "pending_question");
  assert.equal(clarifying.workspace.context, "clarification");
  assert.equal(clarifying.observation.task_blocker, true, "a real recipe blocker remains secondary truth");

  const approval = projection(blockedTask, {
    items: [{ kind: "approval", event_id: "approval-1", turn_id: "turn-1", seq: 1, rpc_id: "rpc-approval", status: "pending" }],
    actions: [],
  });
  assert.equal(approval.phase, "awaiting_approval");
  assert.equal(approval.reason_code, "pending_approval");
  assert.equal(approval.workspace.context, "approval");
});

test("expected clarification gates are not rendered as risks beside their matching checkpoint", () => {
  const task = {
    task_id: "task-1",
    status: "needs_clarification",
    control: { blocked_by: ["task_spec_ambiguous"] },
  };
  const checkpoint = { kind: "question", event_id: "question-1", turn_id: "turn-1", seq: 1, rpc_id: "rpc-question", status: "pending" };
  const expectedGate = projection(task, { items: [checkpoint], actions: [] });
  assert.equal(expectedGate.phase, "clarifying");
  assert.equal(expectedGate.observation.task_blocker, false);
  assert.equal(expectedGate.observation.blocker, null);

  const explicitBlocker = projection(task, {
    items: [
      checkpoint,
      { kind: "blocker", event_id: "blocker-1", turn_id: "turn-1", seq: 2, status: "blocker", summary: "真实资源不足" },
    ],
    actions: [],
  });
  assert.equal(explicitBlocker.phase, "clarifying");
  assert.equal(explicitBlocker.observation.task_blocker, false);
  assert.equal(explicitBlocker.observation.blocker.event_id, "blocker-1", "explicit blocker evidence remains observable");
});

test("a persisted task-spec confirmation gate remains a waiting state after its Agent checkpoint closes", () => {
  const task = {
    task_id: "task-1",
    status: "needs_confirmation",
    control: { blocked_by: [{ code: "task_spec_confirmation_required", active: true }] },
  };
  const result = projection(task, {
    agent_turns: [{ object_type: "AgentTurn", agent_turn_id: "agent-turn-1", agent_run_id: "agent-run-1", status: "idle_without_final" }],
    items: [{ kind: "coordinator_note", event_id: "note-1", agent_run_id: "agent-run-1", turn_id: "root:turn:1", seq: 1, text: "诊断到此" }],
    actions: [],
    risks: [],
  });
  assert.equal(result.phase, "idle");
  assert.equal(result.observation.task_blocker, false);
});

test("authoritative live work stays above blocker and failure facts", () => {
  const blockedTask = {
    task_id: "task-1",
    status: "needs_recipe",
    control: { blocked_by: [{ code: "verified_recipe_unavailable", active: true }] },
  };
  const activeAgent = projection(blockedTask, {
    items: [],
    actions: [action({ action_id: "failed-tool", status: "failed", turn_id: null })],
    interaction_state: "working",
    agent_response_running: true,
    background_action_running: false,
    active_event: null,
    primary_attention: { object_type: "AgentTurn", reason: "agent_response", object_id: "agent-turn-1" },
  });
  assert.equal(activeAgent.phase, "executing");
  assert.equal(activeAgent.reason_code, "agent_response_running");
  assert.equal(activeAgent.observation.task_blocker, true, "the blocker remains secondary truth");
  assert.equal(activeAgent.observation.turn_failure.action.action_id, "failed-tool", "the failed tool remains in evidence");

  const backgroundTraining = projection(blockedTask, {
    items: [], actions: [], agent_response_running: false, background_action_running: true,
    training_runs: [{ object_type: "TrainingRun", task_id: "task-1", training_run_id: "run-1", status: "training", running: true }],
  });
  assert.equal(backgroundTraining.phase, "executing");
  assert.equal(backgroundTraining.reason_code, "observed_active_background_work");

  const cancelling = projection(blockedTask, {
    items: [], actions: [], agent_response_running: true, background_action_running: true,
    training_runs: [{ object_type: "TrainingRun", task_id: "task-1", training_run_id: "run-1", status: "cancel_requested", cancel_requested: true }],
  });
  assert.equal(cancelling.phase, "executing");
  assert.equal(cancelling.reason_code, "cancellation_pending");

  const checkpoint = projection(blockedTask, {
    items: [{ kind: "question", event_id: "question-live", turn_id: "turn-1", seq: 1, rpc_id: "rpc-live", status: "pending" }],
    actions: [],
    agent_response_running: true,
    training_runs: [{ object_type: "TrainingRun", task_id: "task-1", training_run_id: "run-1", status: "cancel_requested", cancel_requested: true }],
  });
  assert.equal(checkpoint.phase, "executing");
  assert.equal(checkpoint.reason_code, "cancellation_pending");

  const failedTaskWithActiveAgent = projection({ task_id: "task-1", status: "failed" }, {
    items: [], actions: [], agent_response_running: true, interaction_state: "working",
  });
  assert.equal(failedTaskWithActiveAgent.phase, "executing");
  assert.equal(failedTaskWithActiveAgent.observation.task_failure, true);
});

test("execution uses only backend actions and never promotes raw tool prose to an action", () => {
  const backendAction = action({ action_id: "real-action", status: "running" });
  const view = projection({ task_id: "task-1" }, {
    execution_running: true,
    interaction_state: "working",
    items: [{
      kind: "team_activity",
      event_id: "team:turn-1",
      turn_id: "turn-1",
      events: [
        { kind: "tool_call", event_id: "raw-call", turn_id: "turn-1", seq: 1, actor_role: "research_source" },
        { kind: "specialist_status", event_id: "raw-status", turn_id: "turn-1", seq: 2, actor_role: "research_source", summary: "我是专家" },
      ],
    }],
    actions: [backendAction, action({ action_id: "wrong-task", task_id: "task-other", status: "running" })],
    delegations: [],
  });

  assert.equal(view.phase, "executing");
  assert.deepEqual(view.actions, [backendAction]);
  assert.equal(view.current_actions[0], backendAction);
  assert.equal(view.specialists.length, 0);
  assert.equal(view.workspace.mode, "execution");
});

test("specialists require a lineage-verified work item", () => {
  const noDelegation = projection({ task_id: "task-1" }, {
    items: [{ kind: "coordinator_note", event_id: "note", turn_id: "turn-1", seq: 1 }],
    actions: [action({ action_id: "ungrounded-specialist", actor_role: "research_source", status: "running" })],
    delegations: [],
  });
  assert.deepEqual(noDelegation.specialists, []);

  const withExplicitDelegation = projection({ task_id: "task-1" }, {
    items: [{ kind: "coordinator_note", event_id: "note", turn_id: "turn-1", seq: 1 }],
    actions: [action({
      action_id: "delegated-action",
      actor_role: "research_source",
      delegation_id: "delegation-1",
      status: "running",
    })],
    delegations: [{
      delegation_id: "delegation-1",
      target_agent_id: "research_source",
      target_agent_label: "研究与来源",
    }],
    work_items: [workItem()],
  });
  assert.equal(withExplicitDelegation.specialists.length, 1);
  assert.deepEqual(withExplicitDelegation.specialists[0].action_ids, ["delegated-action"]);
  assert.equal(withExplicitDelegation.specialists[0].status, "running");
  assert.equal(withExplicitDelegation.workspace.mode, "collaboration");

  const withActionLineage = projection({ task_id: "task-1" }, {
    items: [{ kind: "coordinator_note", event_id: "note", turn_id: "turn-1", seq: 1 }],
    actions: [action({
      action_id: "lineage-action",
      actor_role: "data_experiment",
      delegation_id: "delegation-from-action",
      status: "running",
    })],
    delegations: [],
    work_items: [],
  });
  assert.deepEqual(withActionLineage.delegations, []);
  assert.deepEqual(withActionLineage.specialists, []);

  const unverified = projection({ task_id: "task-1" }, {
    items: [],
    actions: [],
    delegations: [{ delegation_id: "delegation-1", target_agent_id: "research_source" }],
    work_items: [workItem({ lineage_verified: false })],
  });
  assert.deepEqual(unverified.specialists, []);
});

test("terminal canonical work items override stale running team narration", () => {
  const conversation = {
    items: [],
    actions: [
      action({ action_id: "research-stale", actor_role: "research_source", delegation_id: "delegation-research", status: "running" }),
      action({ action_id: "safety-stale", actor_role: "resource_safety", delegation_id: "delegation-safety", status: "running" }),
    ],
    agents: [
      { agent_id: "research-source-agent", role_id: "research_source", status: "completed", lineage_verified: true },
      { agent_id: "resource-safety-agent", role_id: "resource_safety", status: "failed", lineage_verified: true },
    ],
    delegations: [
      { delegation_id: "delegation-research", target_agent_id: "research-source-agent", status: "completed" },
      { delegation_id: "delegation-safety", target_agent_id: "resource-safety-agent", status: "failed" },
    ],
    work_items: [
      workItem({
        work_item_id: "work-research",
        delegation_id: "delegation-research",
        child_session_id: "child-research",
        role: { agent_id: "research-source-agent", role_id: "research_source", label: "研究与来源" },
        status: "completed",
      }),
      workItem({
        work_item_id: "work-safety",
        delegation_id: "delegation-safety",
        child_session_id: "child-safety",
        role: { agent_id: "resource-safety-agent", role_id: "resource_safety", label: "资源与安全" },
        status: "failed",
      }),
    ],
  };

  const view = projection({ task_id: "task-1" }, conversation);
  assert.deepEqual(view.specialists.map((item) => [item.role, item.status]), [
    ["research_source", "completed"],
    ["resource_safety", "failed"],
  ]);

  const events = InteractionShell.reconcileTeamActivityEvents([
    { kind: "specialist_status", actor_role: "research_source", delegation_id: "delegation-research", status: "running", summary: "正在搜索" },
    { kind: "specialist_status", actor_role: "resource_safety", delegation_id: "delegation-safety", status: "running", summary: "正在检查资源" },
  ], view.specialists);
  assert.deepEqual(events.map((item) => item.status), ["completed", "failed"]);
  assert.equal(events.some((item) => item.status === "running"), false);
  assert.equal(events[0].historical_status, "running");
  assert.equal(events[1].status_source, "canonical_work_item");
});

test("latest verified work item determines repeated specialist status while retaining historical failures", () => {
  const latest = workItem({
    work_item_id: "work-evaluation-latest",
    delegation_id: "delegation-evaluation-latest",
    child_session_id: "child-evaluation-latest",
    role: { agent_id: "evaluation-delivery-agent", role_id: "evaluation_delivery", label: "评测与交付" },
    status: "completed",
    observed_updated_sequence: 20,
  });
  const historicalFailure = workItem({
    work_item_id: "work-evaluation-failed",
    delegation_id: "delegation-evaluation-failed",
    child_session_id: "child-evaluation-failed",
    role: { agent_id: "evaluation-delivery-agent", role_id: "evaluation_delivery", label: "评测与交付" },
    status: "failed",
    observed_updated_sequence: 10,
  });
  const view = projection({ task_id: "task-1" }, {
    items: [],
    actions: [
      action({ action_id: "evaluation-latest", actor_role: "evaluation_delivery", delegation_id: latest.delegation_id, status: "completed" }),
      action({ action_id: "evaluation-failed", actor_role: "evaluation_delivery", delegation_id: historicalFailure.delegation_id, status: "failed" }),
    ],
    // A stale role aggregate must not override the latest verified work item.
    agents: [{ agent_id: "evaluation-delivery-agent", role_id: "evaluation_delivery", status: "failed", lineage_verified: true }],
    delegations: [
      { delegation_id: latest.delegation_id, target_agent_id: "evaluation-delivery-agent", status: "completed" },
      { delegation_id: historicalFailure.delegation_id, target_agent_id: "evaluation-delivery-agent", status: "failed" },
    ],
    // Deliberately reversed: event sequence, not payload array position, defines recency.
    work_items: [latest, historicalFailure],
  });

  assert.equal(view.specialists.length, 1);
  assert.equal(view.specialists[0].status, "completed");
  assert.equal(view.specialists[0].latest_work_item_id, "work-evaluation-latest");
  assert.equal(view.specialists[0].historical_failure_count, 1);
  assert.deepEqual(view.specialists[0].work_item_ids, ["work-evaluation-latest", "work-evaluation-failed"]);
  assert.deepEqual(view.specialists[0].action_ids, ["evaluation-latest", "evaluation-failed"]);
});

test("narrated finals do not unlock results without task-owned completion evidence", () => {
  const task = { task_id: "task-1", status: "waiting" };
  const narrationOnly = projection(task, {
    items: [{
      kind: "final_synthesis",
      event_id: "final-narration",
      turn_id: "turn-1",
      seq: 1,
      completion_eligible: false,
      object_refs: [{ type: "evaluation_report", id: "report-1", task_id: "task-1" }],
    }],
    actions: [],
  });
  assert.equal(narrationOnly.phase, "idle");
  assert.equal(narrationOnly.result.ready, false);

  const wrongOwner = projection(task, {
    items: [{
      kind: "final_synthesis",
      event_id: "final-wrong-task",
      turn_id: "turn-1",
      seq: 1,
      completion_eligible: true,
      object_refs: [{ type: "evaluation_report", id: "report-other", task_id: "task-other" }],
    }],
    actions: [],
  });
  assert.equal(wrongOwner.phase, "idle");

  const verifiedFinal = projection(task, {
    items: [{
      kind: "final_synthesis",
      event_id: "final-verified",
      turn_id: "turn-1",
      seq: 1,
      completion_eligible: true,
      object_refs: [{ type: "evaluation_report", id: "report-verified", task_id: "task-1" }],
    }],
    actions: [],
  });
  assert.equal(verifiedFinal.phase, "result_ready");
  assert.equal(verifiedFinal.workspace.mode, "result");
  assert.equal(verifiedFinal.workspace.auto_open, false, "a final ref without a matching current run remains on demand");
  assert.equal(verifiedFinal.workspace.auto_reason, null);
  assert.equal(verifiedFinal.workspace.presentation, "experience");
  assert.equal(verifiedFinal.result.final.event_id, "final-verified");
});

test("a completed task-owned run or evaluation is real result evidence", () => {
  const completed = projection({
    task_id: "task-1",
    status: "completed",
    current_run_id: "run-1",
    current_result: {
      task_id: "task-1",
      status: "completed",
      run_id: "run-1",
      evaluation_report: { task_id: "task-1", run_id: "run-1", release_ready: false },
    },
  }, { items: [], actions: [] });

  assert.equal(completed.phase, "result_ready");
  assert.equal(completed.result.run_id, "run-1");
  assert.equal(completed.result.evaluation.run_id, "run-1");
  assert.equal(completed.reason_code, "task_result_evidence");
});

test("a coordinator final cannot complete the task while task-owned background work is active", () => {
  const activeTraining = action({
    action_id: "training-action",
    turn_id: "turn-1",
    tool_name: "model_harness_start_training_run",
    status: "running",
  });
  const view = projection({ task_id: "task-1", status: "completed" }, {
    items: [{
      kind: "final_synthesis",
      event_id: "coordinator-final",
      turn_id: "turn-2",
      seq: 2,
      completion_eligible: true,
      object_refs: [{ type: "training_run", id: "run-1", task_id: "task-1" }],
    }],
    actions: [activeTraining],
    runs: [{ run_id: "agent-run-1", status: "completed" }],
  });

  assert.equal(view.result.ready, true, "the coordinator reply remains valid evidence");
  assert.equal(view.background.coordinator_reply_complete, true);
  assert.equal(view.background.running, true);
  assert.deepEqual(view.background.action_ids, ["training-action"]);
  assert.equal(view.phase, "executing");
  assert.equal(view.reason_code, "observed_active_background_work");
  assert.equal(view.workspace.context, "coordinator_execution");
});

test("a queued agent run also keeps the task in execution after a coordinator final", () => {
  const view = projection({ task_id: "task-1", status: "completed" }, {
    items: [{
      kind: "final_synthesis",
      event_id: "coordinator-final",
      turn_id: "turn-1",
      seq: 1,
      completion_eligible: true,
      object_refs: [{ type: "training_run", id: "run-1", task_id: "task-1" }],
    }],
    actions: [],
    runs: [{ run_id: "agent-run-queued", status: "queued" }],
  });

  assert.equal(view.phase, "executing");
  assert.deepEqual(view.background.run_ids, ["agent-run-queued"]);
});

test("an active task training result stays in execution after the agent turn is terminal", () => {
  const view = projection({
    task_id: "task-1",
    status: "completed",
    current_result: { task_id: "task-1", run_id: "training-run-1", status: "evaluating" },
  }, {
    items: [{
      kind: "final_synthesis",
      event_id: "coordinator-final",
      turn_id: "turn-1",
      seq: 1,
      completion_eligible: true,
      object_refs: [{ type: "training_run", id: "training-run-1", task_id: "task-1" }],
    }],
    actions: [],
    runs: [{ run_id: "agent-run-1", status: "completed" }],
  });

  assert.equal(view.phase, "executing");
  assert.deepEqual(view.background.training_run_ids, ["training-run-1"]);
  assert.equal(view.result.run_id, null, "a non-terminal training result is not completion evidence");
});

test("evaluation outcome uses only matching completed evidence and explicit baseline candidates", () => {
  const task = {
    task_id: "task-1",
    current_result: {
      task_id: "task-1",
      status: "completed",
      run_id: "run-1",
      metrics: {
        selected_model: "trained_candidate",
        validation_candidates: {
          mean_baseline: { mae: 1.2, r2: 0.1 },
          trained_candidate: { mae: 0.7, r2: 0.6 },
        },
      },
      evaluation_report: {
        task_id: "task-1",
        run_id: "run-1",
        conclusion: "release_ready",
        release_ready: true,
      },
    },
  };
  const outcome = InteractionShell.deriveEvaluationOutcome({ task });
  assert.equal(outcome.ready, true);
  assert.equal(outcome.comparison.metric, "mae");
  assert.equal(outcome.comparison.baseline.name, "mean_baseline");
  assert.equal(outcome.comparison.selected.name, "trained_candidate");
  assert.equal(outcome.comparison.degraded, false);
  assert.equal(outcome.decision.recommended, "publish");
  assert.equal(outcome.decision.publish, "ready");

  const wrongRun = InteractionShell.deriveEvaluationOutcome({
    task,
    evaluation: { task_id: "task-1", run_id: "run-other", release_ready: true },
  });
  assert.equal(wrongRun.ready, false);

  const noBaseline = InteractionShell.deriveEvaluationOutcome({
    task: {
      ...task,
      current_result: {
        ...task.current_result,
        metrics: {
          selected_model: "trained_candidate",
          validation_candidates: { trained_candidate: { accuracy: 0.9 } },
        },
      },
    },
  });
  assert.equal(noBaseline.ready, true);
  assert.equal(noBaseline.comparison, null, "missing baseline must not create an invented metric comparison");
});

test("evaluation degradation recommends rollback instead of publication", () => {
  const outcome = InteractionShell.deriveEvaluationOutcome({
    task: {
      task_id: "task-1",
      current_result: {
        task_id: "task-1",
        status: "completed",
        run_id: "run-1",
        metrics: {
          selected_model: "fine_tuned",
          validation_candidates: {
            most_frequent_baseline: { macro_f1: 0.72 },
            fine_tuned: { macro_f1: 0.61 },
          },
        },
        evaluation_report: { task_id: "task-1", run_id: "run-1", release_ready: true },
      },
    },
  });

  assert.equal(outcome.comparison.degraded, true);
  assert.equal(outcome.decision.recommended, "rollback");
  assert.equal(outcome.decision.publish, "blocked");
  assert.equal(outcome.decision.rollback, "recommended");
});

test("observation degradation fails closed above a possibly stale checkpoint", () => {
  const final = {
    kind: "final_synthesis",
    event_id: "final-1",
    turn_id: "turn-1",
    seq: 1,
    completion_eligible: true,
    object_refs: [{ type: "artifact_bundle", id: "bundle-1", task_id: "task-1" }],
  };
  const degraded = projection({ task_id: "task-1" }, {
    projection_health: { status: "observation_degraded" },
    projection_errors: [{ code: "lineage_mismatch" }],
    items: [final, { kind: "question", event_id: "question", turn_id: "turn-1", seq: 2, status: "pending" }],
    actions: [],
  });
  assert.equal(degraded.phase, "failed");
  assert.equal(degraded.reason_code, "observation_degraded");
  assert.equal(degraded.observation.degraded, true);
  assert.equal(degraded.workspace.context, "error");

  // The raw checkpoint remains inspectable for diagnosis but is not the
  // authoritative foreground while projection health is degraded.
  assert.equal(degraded.checkpoint.kind, "question");
});

test("a canonical pending checkpoint stays primary over task failure while failure truth remains observable", () => {
  const final = {
    kind: "final_synthesis",
    event_id: "final-1",
    turn_id: "turn-1",
    seq: 1,
    completion_eligible: true,
    object_refs: [{ type: "artifact_bundle", id: "bundle-1", task_id: "task-1" }],
  };

  const turnError = projection({ task_id: "task-1" }, {
    items: [
      final,
      { kind: "turn_error", event_id: "turn-error", turn_id: "turn-1", seq: 2, status: "failed" },
    ],
    actions: [],
  });
  assert.equal(turnError.phase, "failed");
  assert.equal(turnError.reason_code, "turn_error");

  const failedTaskWithApproval = projection({ task_id: "task-1", status: "failed" }, {
    items: [{ kind: "approval", event_id: "approval", turn_id: "turn-2", rpc_id: "rpc-approval", status: "pending" }],
    actions: [],
  });
  assert.equal(failedTaskWithApproval.phase, "awaiting_approval");
  assert.equal(failedTaskWithApproval.observation.task_failure, true);
});

test("observation degradation remains the primary phase when no checkpoint is pending", () => {
  const degraded = projection({ task_id: "task-1" }, {
    projection_health: { status: "observation_degraded" },
    projection_errors: [{ code: "lineage_mismatch" }],
    items: [],
    actions: [],
  });
  assert.equal(degraded.phase, "failed");
  assert.equal(degraded.reason_code, "observation_degraded");
  assert.equal(degraded.workspace.context, "error");
});

test("typed blockers remain distinct from failures", () => {
  const blocked = projection({ task_id: "task-1" }, {
    items: [{ kind: "blocker", event_id: "blocker", turn_id: "turn-1", seq: 1, status: "blocker" }],
    actions: [],
  });
  assert.equal(blocked.phase, "blocked");
  assert.equal(blocked.workspace.mode, "status");
  assert.equal(blocked.workspace.context, "blocker");
});

test("UMD build exposes the same browser API without a module loader", () => {
  const filename = new URL("../../../model_harness/web/interaction-shell.js", import.meta.url);
  const source = fs.readFileSync(filename, "utf8");
  const context = { globalThis: {} };
  vm.runInNewContext(source, context, { filename: "interaction-shell.js" });
  assert.deepEqual(
    Array.from(context.globalThis.ModelHarnessInteractionShell.PHASES),
    Array.from(InteractionShell.PHASES),
  );
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.groupConversationTurns, "function");
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.deriveInteractionProjection, "function");
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.deriveEvaluationOutcome, "function");
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.canShowTurnStop, "function");
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.createAiTurnFrame, "function");
  assert.equal(typeof context.globalThis.ModelHarnessInteractionShell.conversationTurnTarget, "function");
});
