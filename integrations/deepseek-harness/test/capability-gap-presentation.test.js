import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const functions = app.slice(app.indexOf("function pendingExecutionIntegration"), app.indexOf("function statusTone"));
const context = {
  state: { conversation: null, conversationStreamDegraded: false, conversationRecord: null },
  RUNNING_STATUSES: new Set(["running", "training"]),
  STATUS_LABELS: { failed: "运行异常", needs_recipe: "准备训练方案" },
  backgroundCancellationPending: (c) => c?.interaction_projection?.phase === "stopping",
  currentHumanCheckpoint: (c) => c?.pending?.[0] || null,
  approvalPresentation: () => ({ header: "等待批准" }),
  conversationAgentResponseRunning: (c) => c?.agent_response_running === true,
  conversationHasBackgroundTraining: (c) => c?.background_action_running === true,
  isConversationDraft: () => false,
};
vm.runInNewContext(`${functions}\nglobalThis.api = { pendingExecutionIntegration, interactionPresentation, workflowStatus, taskListStatus };`, context);
const api = context.api;

function task(overrides = {}) {
  return {
    task_id: "tts-task", status: "needs_recipe", capability_status: "needs_recipe",
    recipe_id: null, current_run_id: null,
    control: { current_stage: "capability_resolution", blocked_by: [{ code: "verified_recipe_unavailable" }] },
    blockers: [{ code: "recipe_unavailable", stage: "build", active: true }],
    ...overrides,
  };
}
function conversation(overrides = {}) {
  return {
    task_id: "tts-task", running: false, execution_running: false,
    agent_response_running: false, background_action_running: false,
    interaction_projection: { schema_version: "1.0", phase: "idle" },
    projection_health: "healthy", risks: [], pending: [], ...overrides,
  };
}

test("a pure missing Recipe is a neutral integration task across list, header and turn", () => {
  const goal = task(); const view = conversation();
  const snapshot = JSON.stringify({ goal, view });
  for (const result of [
    api.workflowStatus(goal), api.taskListStatus(goal), api.taskListStatus(goal, view),
    api.interactionPresentation(goal, view, { phase: "blocked", observation: { task_blocker: true } }),
  ]) {
    assert.equal(result.label, "准备训练方案");
    assert.equal(result.tone, "needs_recipe");
    assert.notEqual(result.phase, "completed");
    assert.match(result.summary, /数据要求.*训练路线.*资源预算.*验证步骤/);
    assert.match(result.summary, /方案验证与授权/);
  }
  assert.equal(JSON.stringify({ goal, view }), snapshot, "presentation must not mutate capabilities or authorize execution");
  assert.equal(goal.current_run_id, null);
  assert.equal(goal.recipe_id, null);
  assert.equal(api.taskListStatus(goal, conversation({ task_id: "other-task", risks: [{ status: "failed", active: true }] })).label, "准备训练方案", "another task's conversation cannot contaminate this task");
});

test("real security, resource, data and unknown blockers stay blocked", () => {
  for (const code of ["blocked_security", "blocked_license", "blocked_resources", "blocked_data", "qualification_failed", "unknown_failure"]) {
    const goal = task({ blockers: [{ code: "recipe_unavailable", active: true }, { code, active: true }] });
    assert.equal(api.pendingExecutionIntegration(goal), null, code);
    const result = api.interactionPresentation(goal, conversation(), { phase: "blocked" });
    assert.equal(result.label, "任务当前受阻", code);
    assert.equal(result.tone, "failed", code);
  }
  assert.equal(api.pendingExecutionIntegration(task({ current_result: { status: "failed" } })), null);
  assert.equal(api.pendingExecutionIntegration(task({ resource_feasibility: { decision: "blocked_environment" } })), null);
  assert.equal(api.workflowStatus(task({ status: "failed" })).tone, "failed");
  assert.equal(api.pendingExecutionIntegration(task({ blockers: [{ code: "blocked_security", active: false }] }))?.label, "准备训练方案", "resolved blockers remain historical");
});

test("active failures, identity errors and untrusted observations cannot be softened", () => {
  for (const status of ["failed", "identity_error"]) {
    const view = conversation({
      interaction_projection: { schema_version: "1.0", phase: "blocked", subject: { object_type: "Risk", object_id: "real-failure" } },
      risks: [{ status, active: true }],
    });
    assert.equal(api.pendingExecutionIntegration(task(), view), null);
    assert.equal(api.interactionPresentation(task(), view).tone, "failed");
  }
  assert.equal(api.pendingExecutionIntegration(task(), conversation({ risks: undefined, actions: [{ status: "failed" }] })), null);
  assert.equal(api.pendingExecutionIntegration(task(), conversation({ projection_health: "observation_degraded" })), null);
  assert.equal(api.pendingExecutionIntegration(task(), conversation(), { phase: "failed", observation: { task_failure: true } }), null);
  assert.equal(api.pendingExecutionIntegration(task(), conversation(), { phase: "blocked", observation: { blocker: { code: "blocked_security" } } }), null);
  assert.equal(api.pendingExecutionIntegration(task(), conversation({ interaction_projection: { schema_version: "1.0", phase: "blocked", subject: { object_type: "Risk" } }, risks: [] })), null, "an unexplained canonical risk is not a capability gap");
});

test("live work and native approvals stay in the foreground", () => {
  for (const [phase, expected] of [["agent_working", "AI 正在处理"], ["waiting_approval", "等待批准"], ["stopping", "正在停止"], ["failed", "运行异常"]]) {
    const view = conversation({ interaction_projection: { schema_version: "1.0", phase } });
    assert.equal(api.interactionPresentation(task(), view).label, expected);
  }
  const pending = conversation({ pending: [{ kind: "approval", rpc_id: "native" }] });
  assert.equal(api.workflowStatus(task(), pending).label, "等待批准");
});

test("capability and workspace renderers use the same neutral presentation without changing projections", () => {
  assert.match(app, /const trainingCapability = ConversationView\.trainingCapabilityProjection\(task\); const integrationPending = pendingExecutionIntegration/);
  assert.match(app, /ui\.capabilitySummary\.textContent = pending\?\.summary/);
  assert.match(app, /const displayPhase = pendingExecutionIntegration\(task, conversation, projection\) \? "integration_pending"/);
  assert.doesNotMatch(app, /现有训练方案无法覆盖该能力|不会伪造训练进度/);
});
