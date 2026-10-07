import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from) + from.length));
class Control {
  constructor(...children) { this.childNodes = children; this.attributes = {}; this.disabled = false; }
  replaceChildren(...nodes) { this.childNodes = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
}
function busyFixture() {
  const context = {
    ui: {}, document: { createTextNode: text => ({ textContent: text }) },
  };
  vm.runInNewContext(section("function setButtonBusy", "function createUiIcon") + "\nglobalThis.api={setButtonBusy,closeDecisionDialog};", context);
  return context;
}
test("busy buttons restore their original icon and live label nodes instead of flattening markup", () => {
  const f = busyFixture(); const icon = { tag: "svg" }, label = { tag: "span", textContent: "导入数据" };
  const button = new Control(icon, label);
  f.api.setButtonBusy(button, true, "体检中");
  assert.equal(button.disabled, true); assert.equal(button.attributes["aria-busy"], "true");
  f.api.setButtonBusy(button, true, "核对中");
  label.textContent = "上传构建样例";
  f.api.setButtonBusy(button, false);
  assert.equal(button.childNodes[0], icon); assert.equal(button.childNodes[1], label);
  assert.equal(button.childNodes[1].textContent, "上传构建样例");
  assert.equal(button.disabled, false); assert.equal(button.attributes["aria-busy"], undefined);
});
test("dialog close cannot imply cancellation while a submission is in flight", () => {
  const f = busyFixture(); let busy = true, closed = 0;
  f.ui.dialogActions = { querySelector: () => busy ? {} : null };
  f.ui.decisionDialog = { close: () => { closed += 1; } };
  f.api.closeDecisionDialog(); assert.equal(closed, 0);
  busy = false; f.api.closeDecisionDialog(); assert.equal(closed, 1);
});
test("approval disables both opposing actions and deduplicates the same checkpoint", async () => {
  const f = busyFixture(); let release; const requests = [];
  const allow = new Control({ textContent: "批准" }), reject = new Control({ textContent: "拒绝" });
  const parent = { querySelectorAll: () => [allow, reject] };
  allow.closest = reject.closest = () => parent;
  Object.assign(f, {
    state: { selectedTaskId: "task-a", conversation: { pending: [{ rpc_id: "rpc-a" }] } }, setButtonBusy: f.api.setButtonBusy,
    request: (path, options) => { requests.push([path, options]); return new Promise(resolve => { release = resolve; }); },
    conversationTransportPath: (task, action, rpc) => `${task}/${action}/${rpc}`,
    refreshSelected: async () => {}, showNotice() {},
  });
  vm.runInNewContext(section("async function answerApproval", "async function postQuestionAnswers") + "\nglobalThis.approve=answerApproval;", f);
  const first = f.approve({ rpc_id: "rpc-a" }, "allowed-once", allow);
  assert.equal(allow.disabled, true); assert.equal(reject.disabled, true);
  await f.approve({ rpc_id: "rpc-a" }, "rejected", reject);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "task-a/approvals/rpc-a");
  release({}); await first;
  assert.equal(allow.disabled, false); assert.equal(reject.disabled, false);
});
test("workspace groups older run evidence without discarding or relabeling its identities", () => {
  const context = {};
  vm.runInNewContext(section("function partitionWorkspaceResultRefs", "const ACTIVE_SPECIALIST_STATUSES") + "\nglobalThis.partition=partitionWorkspaceResultRefs;", context);
  const old = { type: "evaluation_report", id: "old-evaluation", run_id: "old-run" };
  const latest = { type: "artifact_bundle", id: "new-bundle", run_id: "new-run" };
  const sourceRef = { type: "model_source_search", id: "source" };
  const unknown = { type: "evaluation_report", id: "unscoped" };
  const result = context.partition({ current_run_id: "new-run" }, [old, latest, sourceRef, unknown]);
  assert.deepEqual([...result.current], [latest, sourceRef]);
  assert.deepEqual([...result.historical], [old, unknown]);
  assert.equal(result.historical[0], old);
  const replaced = context.partition({ current_run_id: null, current_result: null }, [old, latest]);
  assert.equal(replaced.current.length, 0); assert.equal(replaced.historical.length, 2);
});

function simpleDialogFixture() {
  class DialogNode extends Control {
    constructor(tag = "div") { super(); this.tag = tag; this.events = {}; }
    set textContent(value) { this.childNodes = [{ textContent: value }]; }
    get textContent() { return this.childNodes.map(node => node.textContent || "").join(""); }
    append(...nodes) { this.childNodes.push(...nodes); }
    addEventListener(name, listener) { this.events[name] = listener; }
    querySelectorAll() { return this.childNodes.filter(node => node.tag === "button"); }
    querySelector() { return this.querySelectorAll().find(node => node.attributes["aria-busy"] === "true") || null; }
    contains(node) { return this.childNodes.includes(node); }
  }
  const notices = [], ui = {
    dialogBody: new DialogNode(), dialogActions: new DialogNode(), dialogKicker: {}, dialogTitle: {}, closeDialogButton: new DialogNode("button"),
    decisionDialog: { open: false, closes: 0, showModal() { this.open = true; }, close() { this.open = false; this.closes += 1; } },
  };
  const f = { ui, document: { createElement: tag => new DialogNode(tag), createTextNode: textContent => ({ textContent }) }, clear: node => node.replaceChildren(), showNotice: value => notices.push(value) };
  vm.runInNewContext(section("function setButtonBusy", "function createUiIcon") + section("function openSimpleDialog", "function syncCancelRequestUi") + "\nglobalThis.open=openSimpleDialog;", f);
  return { ...f, notices };
}

test("generic dialog blocks both footer cancel and the close icon while its operation is pending", async () => {
  const f = simpleDialogFixture(); let release, submissions = 0;
  f.open({ title: "停止当前轮", body: "停止后再归档", allowLabel: "请求停止当前轮", onAllow: () => { submissions += 1; return new Promise(resolve => { release = resolve; }); } });
  const [cancel, allow] = f.ui.dialogActions.querySelectorAll("button");
  const pending = allow.events.click();
  assert.equal(cancel.disabled, true); assert.equal(allow.disabled, true); assert.equal(f.ui.closeDialogButton.disabled, true);
  cancel.events.click();
  assert.equal(f.ui.decisionDialog.open, true, "even a stale queued click must pass the common busy guard");
  await allow.events.click(); assert.equal(submissions, 1);
  release(); await pending;
  assert.equal(f.ui.decisionDialog.closes, 1);
  assert.equal(cancel.disabled, false); assert.equal(allow.disabled, false); assert.equal(f.ui.closeDialogButton.disabled, false);
  assert.equal(allow.textContent, "请求停止当前轮");
});

test("generic dialog restores preexisting disabled state after an operation fails", async () => {
  const f = simpleDialogFixture();
  f.open({ title: "核对", body: "说明", allowLabel: "确认", onAllow: async () => { throw new Error("提交失败"); } });
  const [cancel, allow] = f.ui.dialogActions.querySelectorAll("button");
  cancel.disabled = true;
  await allow.events.click();
  assert.equal(cancel.disabled, true); assert.equal(allow.disabled, false); assert.equal(f.ui.closeDialogButton.disabled, false);
  assert.equal(f.ui.decisionDialog.open, true); assert.deepEqual(f.notices, ["提交失败"]);
});

test("result evidence precedes secondary team records in both visual and accessible DOM order", () => {
  const html = readFileSync(new URL("../../../model_harness/web/index.html", import.meta.url), "utf8");
  const results = html.indexOf('id="workspaceResults"'), team = html.indexOf('id="workspaceTeam"');
  assert.ok(results >= 0 && team > results);
  assert.match(section("function renderWorkspaceDecision", "function renderWorkspaceExperience"), /模型对比与下一步/);
});

test("known workspace roles use the existing Chinese presentation map instead of English runtime labels", async () => {
  const { createRequire } = await import("node:module");
  const ConversationView = createRequire(import.meta.url)("../../../model_harness/web/conversation-view.js");
  const cards = [];
  const f = { ConversationView, document: { createElement: () => ({ children: [], dataset: {}, append(...children) { this.children.push(...children); } }) },
    ui: { workspaceTeamList: { append: node => cards.push(node) } }, roleLabel: value => value, workspaceWorkStatus: () => "已完成" };
  vm.runInNewContext(section("function renderWorkspaceAgent", "function renderWorkspaceCoordinator") + "\nglobalThis.render=renderWorkspaceAgent;", f);
  const item = { status: "completed", role: { role_id: "data_experiment", label: "Data & Experiment Agent" } };
  f.render(item);
  assert.equal(cards[0].children[0].textContent, "数据");
  assert.equal(cards[0].children[1].children[0].textContent, ConversationView.ROLE_LABELS.data_experiment);
  assert.equal(item.role.label, "Data & Experiment Agent", "display localization must not rewrite runtime evidence");
});


function stopDialogFixture() {
  const f = simpleDialogFixture();
  const create = f.document.createElement; f.document.createElement = tag => { const node = create(tag); node.value = ""; node.focus = () => { node.focused = true; }; return node; };
  Object.assign(f, { state: { selectedTaskId: "task-a", conversation: {}, cancelRequestInFlight: false }, window: { requestAnimationFrame: callback => callback() }, backgroundCancellationPending: () => false, syncCancelRequestUi() {}, renderConversation() {}, refreshSelected: async () => {}, conversationTransportPath: (task, action) => `/tasks/${task}/conversation/${action}` });
  vm.runInNewContext(section("function openCancelAgentDialog", "function navigateToTrainingRecoveryCheckpoint") + "\nglobalThis.openStop=openCancelAgentDialog;", f);
  return f;
}

test("stop dialog accepts the existing stop intent with an optional reason, one request and preserved in-flight guard", async () => {
  const f = stopDialogFixture(), requests = []; let release;
  f.request = (path, options) => { requests.push([path, options]); return new Promise(resolve => { release = resolve; }); };
  f.openStop(); const [back, allow] = f.ui.dialogActions.querySelectorAll("button");
  assert.equal(allow.disabled, false); assert.equal(allow.focused, true);
  const field = f.ui.dialogBody.childNodes.find(node => node.tag === "label"); assert.equal(field.childNodes[0].textContent, "停止原因（可选）");
  const pending = allow.events.click(); assert.equal(requests.length, 1); assert.equal(requests[0][0], "/tasks/task-a/conversation/cancel"); assert.equal(requests[0][1].json.reason, "用户请求停止当前执行");
  assert.equal(back.disabled, true); assert.equal(allow.disabled, true); assert.equal(f.state.cancelRequestInFlight, true);
  await allow.events.click(); assert.equal(requests.length, 1); back.events.click(); assert.equal(f.ui.decisionDialog.open, true);
  release({ accepted: true }); await pending; assert.equal(f.state.cancelRequestInFlight, false); assert.equal(f.ui.decisionDialog.open, false); assert.match(f.notices.at(-1), /正在确认.*最终状态/);
});

test("a user-written stop reason is retained and a request failure never claims cancellation succeeded", async () => {
  const f = stopDialogFixture(), requests = []; f.request = async (path, options) => { requests.push([path, options]); throw new Error("连接中断"); };
  f.openStop(); const field = f.ui.dialogBody.childNodes.find(node => node.tag === "label"); field.childNodes[1].value = "  需要修改验收目标  ";
  const allow = f.ui.dialogActions.querySelectorAll("button")[1]; await allow.events.click();
  assert.equal(requests[0][1].json.reason, "需要修改验收目标"); assert.equal(f.ui.decisionDialog.open, true); assert.equal(allow.disabled, false); assert.equal(f.state.cancelRequestInFlight, false); assert.match(f.notices.at(-1), /停止请求失败.*是否停止尚未确认/);
});

test("an old stop dialog cannot cancel the task selected after it opened", async () => {
  const f = stopDialogFixture(); let requests = 0; f.request = async () => { requests += 1; };
  f.openStop(); f.state.selectedTaskId = "task-b"; await f.ui.dialogActions.querySelectorAll("button")[1].events.click();
  assert.equal(requests, 0); assert.match(f.notices.at(-1), /当前任务已经变化/);
});
