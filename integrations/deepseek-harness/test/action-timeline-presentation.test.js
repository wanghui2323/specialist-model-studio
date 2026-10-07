import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from) + from.length));
class Element {
  constructor() { this.children = []; this.dataset = {}; this.events = {}; this.open = false; }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.events[name] = fn; }
}
function fixture() {
  const target = new Element(); const rendered = [];
  const context = {
    document: { createElement: () => new Element() },
    ui: { messageList: target }, state: { selectedTaskId: "task-a", actionTimelineDisclosure: new Map() },
    isUserDeclinedAction: () => false, isProbeMiss: () => false, isWaitingForAnswerAction: () => false,
    actionTitle: action => action.tool_name,
    renderActionRow: action => rendered.push(action), hydrateActionTimelineResults() {},
  };
  vm.runInNewContext(section("function actionTimelineGlance", "function parseActionResultValue") + section("function renderActionTimeline", "function renderCheckpointHistory") + "\nglobalThis.api={actionTimelineGlance,renderActionTimeline};", context);
  const actions = [
    { actor_role: "orchestrator", turn_id: "turn-a", status: "failed", tool_name: "历史试验" },
    { actor_role: "orchestrator", turn_id: "turn-a", status: "completed", tool_name: "修复数据并生成合同" },
  ];
  return { ...context, target, actions, rendered };
}

test("current confirmation takes foreground while prior failures remain auditable inside a collapsed timeline", () => {
  const f = fixture();
  f.state.actionTimelineDisclosure.set("task-a:turn-a:execution", true);
  f.api.renderActionTimeline(f.actions, [], { interactionState: "waiting_for_human" });
  const timeline = f.target.children[0];
  assert.equal(timeline.open, false);
  assert.equal(timeline.dataset.status, "waiting");
  assert.match(timeline.children[0].children[0].children[2].textContent, /请先查看下面的确认卡/);
  assert.equal(f.rendered[0].status, "failed", "presentation must not rewrite historical failure evidence");
  timeline.open = true; timeline.events.toggle();
  f.api.renderActionTimeline(f.actions, [], { interactionState: "waiting_for_human" });
  assert.equal(f.target.children[1].open, true, "an explicit expansion during this checkpoint survives refresh");
});

test("active failures remain visible without forcing technical details into the dialogue", () => {
  const f = fixture();
  f.api.renderActionTimeline(f.actions);
  assert.equal(f.target.children[0].open, false);
  assert.equal(f.target.children[0].dataset.status, "failed");
  assert.match(f.api.actionTimelineGlance(f.actions, false, false), /需要处理/);
});

test("completed timeline summaries describe the latest completed action", () => {
  const f = fixture();
  const actions = [{ status: "completed", tool_name: "建立模型任务" }, { status: "completed", tool_name: "下载模型交付包" }];
  assert.equal(f.api.actionTimelineGlance(actions, false, false), "最近完成：下载模型交付包");
  assert.equal(actions[0].tool_name, "建立模型任务", "the chronological action list is not mutated");
});

for (const interactionState of ["settled", "historical"]) {
  test(`${interactionState} timelines do not reopen due to old failures and retain manual expansion`, () => {
    const f = fixture();
    f.state.actionTimelineDisclosure.set("task-a:turn-a:execution", true);
    f.api.renderActionTimeline(f.actions, [], { interactionState });
    const timeline = f.target.children[0];
    assert.equal(timeline.open, false);
    assert.equal(timeline.dataset.status, "recorded");
    assert.match(timeline.children[0].children[0].children[2].textContent, /含历史异常记录/);
    assert.equal(f.actions[0].status, "failed");
    timeline.children[0].events.click(); timeline.open = true; timeline.events.toggle();
    f.api.renderActionTimeline(f.actions, [], { interactionState: "settled" });
    assert.equal(f.target.children[1].open, true);
  });
}
