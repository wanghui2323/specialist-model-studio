import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const begin = app.indexOf("function aiTurnPresentation(");
const end = app.indexOf("function createAiTurnContainer(", begin);
function fixture() {
  const context = {
    state: { task: { status: "awaiting_data" }, conversationStreamDegraded: false },
    interactionPresentation: () => ({ label: "等待数据", tone: "awaiting_data" }),
    currentHumanCheckpoint: (conversation) => conversation.pending?.[0] || null,
    InteractionShell: { turnHasActiveFailure: (_turn, actions) => actions.some((action) => action.status === "failed") },
    terminalEventScope: () => "root",
  };
  vm.runInNewContext(app.slice(begin, end), context);
  const turn = { group_key: "turn-a", items: [{ kind: "coordinator_note", text: "已有结果可查看" }] };
  const projection = { current_turn: { group_key: "turn-a" } };
  const conversation = { interaction_projection: { phase: "idle" }, agent_response_running: false, background_action_running: false, pending: [], risks: [] };
  return { context, turn, projection, conversation, run: (actions = []) => context.aiTurnPresentation(turn, projection, conversation, actions) };
}
test("idle observed reply uses reply lifecycle and does not imply training completion", () => {
  const f = fixture();
  assert.equal(f.run().label, "本轮回复已结束");
  assert.equal(f.run().tone, "idle");
  assert.equal(f.context.state.task.status, "awaiting_data");
});
test("reply-only presentation cannot conceal work, approval, degraded observation or failure", () => {
  for (const patch of [
    { agent_response_running: true }, { background_action_running: true },
    { interaction_projection: { phase: "waiting_approval" } },
    { pending: [{ kind: "approval" }] }, { agent_response_running: undefined },
  ]) {
    const f = fixture(); Object.assign(f.conversation, patch);
    assert.notEqual(f.run().label, "本轮回复已结束");
  }
  const degraded = fixture(); degraded.context.state.conversationStreamDegraded = true;
  assert.notEqual(degraded.run().label, "本轮回复已结束");
  assert.notEqual(fixture().run([{ status: "failed" }]).label, "本轮回复已结束");
  const empty = fixture(); empty.turn.items = [];
  assert.notEqual(empty.run().label, "本轮回复已结束");
});
