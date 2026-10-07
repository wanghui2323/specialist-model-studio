import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (start, end) => app.slice(app.indexOf(start), app.indexOf(end, app.indexOf(start) + start.length));
const context = { state: { selectedTaskId: "task-a", selectionToken: 2 }, clearObservedPendingMessage() {}, clientDegradedConversation: value => value };
vm.runInNewContext(section("function isCanonicalConversationSnapshot", "function markConversationStreamDegraded") + "\nglobalThis.valid=isCanonicalConversationSnapshot; globalThis.accept=acceptConversationSnapshot;", context);
function healthy() { return { schema_version: "2.0", task_id: "task-a", event_payload_mode: "compact-v1", action_schema_version: "1.0", synthesis_verdict_version: "1.0", session_id: "session-a", team_id: "team-a", running: false, execution_running: false, can_cancel_agent: false, agent_response_running: false, background_action_running: false, interaction_state: "idle", interaction_projection: { schema_version: "1.0", phase: "idle", can_cancel: false }, items: [], events: [], actions: [], pending: [], runs: [], agents: [], delegations: [], projection_errors: [], human_checkpoints: [], stream_health: { status: "healthy" }, projection_health: "healthy" }; }
function offline() { return { ...healthy(), observation_source: "persisted_projection", execution_state_observed: false, pending_observed: false, projection_health: "observation_degraded", interaction_state: "observation_degraded", interaction_projection: { schema_version: "1.0", phase: "observation_degraded", can_cancel: false }, running: null, execution_running: null, agent_response_running: null, stream_health: { status: "degraded" }, items: [{ type: "user_message", text: "已保存的问题", observation_stale: true }], actions: [{ action_id: "historical", status: "running", observation_stale: true }] }; }

test("the exact persisted/degraded snapshot retains historical records without asserting the Agent stopped", () => {
  const value = offline(); assert.equal(context.valid(value), true); assert.equal(context.accept("task-a", 2, value), true);
  assert.equal(context.state.conversation.agent_response_running, null); assert.equal(context.state.conversation.actions[0].status, "running"); assert.equal(context.state.conversation.items[0].text, "已保存的问题");
  const background = { ...value, running: true, execution_running: true, background_action_running: true }; assert.equal(context.valid(background), true);
  assert.equal(context.accept("task-other", 2, value), false);
});

test("offline acceptance never permits old pending approvals or incomplete healthy contracts", () => {
  for (const change of [{ projection_health: "healthy" }, { pending: [{ kind: "approval" }] }, { human_checkpoints: [{ status: "pending" }] }, { pending_observed: true }, { can_cancel_agent: true }, { interaction_projection: { schema_version: "1.0", phase: "idle", can_cancel: false } }, { execution_state_observed: true }, { observation_source: "unknown" }, { interaction_state: "idle" }]) assert.equal(context.valid({ ...offline(), ...change }), false, JSON.stringify(change));
  for (const field of ["running", "execution_running", "agent_response_running", "background_action_running"]) assert.equal(context.valid({ ...healthy(), [field]: null }), false, field);
  assert.equal(context.valid(healthy()), true);
});

test("nullable state events require a complete reconciliation rather than being coerced into idle", () => {
  assert.match(section('source.addEventListener("state"', 'function syncConversationComposerPlaceholder'), /execution_state_observed === false.*includes\(null\).*reconcileConversation\(taskId, token\); return;/);
  assert.match(section("function materialReplyInProgress", "async function flushDeferredMaterialContinuations"), /execution_state_observed === false/);
  assert.match(section("function renderHumanCheckpoint", "function normalizeObjectRefType"), /pending_observed !== false/);
  const presentationContext = { state: { conversation: offline(), conversationStreamDegraded: false }, isConversationDraft: () => false, backgroundCancellationPending: () => false, currentHumanCheckpoint: () => null, approvalPresentation: () => ({}), conversationAgentResponseRunning: () => false, conversationHasBackgroundTraining: () => false, STATUS_LABELS: {} };
  vm.runInNewContext(section("function pendingExecutionIntegration", "function statusTone") + "\nglobalThis.present=interactionPresentation;", presentationContext);
  const presentation = presentationContext.present({ task_id: "task-a", status: "needs_recipe" }, offline());
  assert.equal(presentation.phase, "observation_degraded"); assert.equal(presentation.can_cancel, false); assert.notEqual(presentation.label, "等待你的消息");
});
