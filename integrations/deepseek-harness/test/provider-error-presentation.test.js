import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length));
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ""; this.open = false; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
}
function fixture() {
  const list = new Node("div"), context = { document: { createElement: tag => new Node(tag) }, ui: { messageList: list },
    roleLabel: () => "构建专家", appendObjectRefs() {}, appendRecoveryActions() {}, createUiIcon: () => new Node("svg"),
    isWaitingForAnswerAction: () => false, actionDisplayStatus: () => "failed", actionTitle: () => "专家执行", formatActionDuration: () => "", actionStatusLabel: () => "失败",
  };
  vm.runInNewContext(section("function terminalEventScope", "function renderEvidenceLedger") + section("function renderTypedTruthNotice", "function appendRecoveryActions") + section("function renderActionRow", "function renderDelegationGroup") + "\nglobalThis.api={providerErrorPresentation,renderTurnTerminal,renderTypedTruthNotice,renderActionRow};", context);
  return { ...context, list };
}
function text(node, visibleOnly = false) { return [node.textContent, ...(node.tag === "details" && !node.open && visibleOnly ? node.children.slice(0, 1) : node.children).map(child => text(child, visibleOnly))].filter(Boolean).join("\n"); }
const balance = { kind: "turn_error", session_id: "root", root_session_id: "root", status: "failed", summary: "Insufficient Balance (request_id: req-private)", payload: { error: { source: "dsh_turn_end", code: "API_ERROR", status: 402, request_id: "req-private", message: "Insufficient Balance" } } };

test("root provider balance failure is actionable Chinese with original diagnostics collapsed", () => {
  const f = fixture(), original = JSON.stringify(balance); f.api.renderTurnTerminal(balance);
  const card = f.list.children[0]; assert.equal(card.dataset.status, "failed");
  assert.match(text(card, true), /模型账户余额不足，当前回合已停止；恢复额度后继续/);
  assert.doesNotMatch(text(card, true), /Insufficient Balance|req-private|request_id|训练失败|数据丢失/);
  const details = card.children.find(node => node.tag === "details"); assert.ok(details); assert.equal(details.open, false);
  assert.match(text(details), /Insufficient Balance.*request_id: req-private/); assert.match(text(details), /status: 402/);
  assert.equal(JSON.stringify(balance), original, "presentation cannot rewrite provider evidence or task state");
});

test("typed 402 in a native payload works without relying on an English message", () => {
  const f = fixture(); f.api.renderTurnTerminal({ ...balance, summary: "请求失败", payload: { error: { status: 402, requestId: "typed-request" } } });
  assert.match(text(f.list.children[0], true), /模型账户余额不足/); assert.doesNotMatch(text(f.list.children[0], true), /typed-request/); assert.match(text(f.list.children[0]), /requestId: typed-request/);
});

test("role failures and native action errors use the same mapping without claiming the parent turn stopped", () => {
  const f = fixture(), child = { ...balance, session_id: "child", delegation_id: "delegation-a", actor_role: "build_training" };
  f.api.renderTurnTerminal(child); const childCard = f.list.children[0]; childCard.open = true;
  assert.match(text(childCard, true), /模型账户余额不足，本次模型调用未完成；恢复额度后继续/);
  assert.match(text(childCard, true), /不代表协调器回合已停止/); assert.doesNotMatch(text(childCard, true), /当前回合已停止|req-private/);
  f.api.renderTypedTruthNotice({ ...child, kind: "failed", title: "Insufficient Balance (request_id: req-private)" });
  assert.match(text(f.list.children[1], true), /模型账户余额不足/); assert.doesNotMatch(text(f.list.children[1], true), /Insufficient Balance|req-private/);
  f.api.renderActionRow({ status: "failed", actor_role: "build_training", error: { ...balance.payload.error } }, f.list);
  assert.match(text(f.list.children[2], true), /模型账户余额不足/); assert.doesNotMatch(text(f.list.children[2], true), /req-private|当前回合已停止/);
});

test("unrelated network, authentication, limits and domain payment errors retain their actual meaning", () => {
  const f = fixture();
  for (const [status, message] of [[503, "Network unavailable"], [401, "Unauthorized"], [429, "Rate limit exceeded"], [500, "request number 402 failed"]]) {
    const item = { ...balance, summary: message, payload: { error: { status, message } } }; assert.equal(f.api.providerErrorPresentation(item), null);
    f.api.renderTurnTerminal(item); assert.match(text(f.list.children.at(-1), true), new RegExp(message)); assert.doesNotMatch(text(f.list.children.at(-1), true), /余额不足/);
  }
  assert.equal(f.api.providerErrorPresentation({ error: { source: "dataset_tool", status: 402, message: "Dataset purchase required" } }), null);
});

test("the recovery button uses a user-facing label and only focuses the editable composer", () => {
  let focused = 0; const notices = [];
  class ButtonNode extends Node {
    constructor(tag) { super(tag); this.events = {}; }
    addEventListener(name, callback) { this.events[name] = callback; }
  }
  const context = { document: { createElement: tag => new ButtonNode(tag) }, ui: { messageInput: { focus: () => { focused++; } } }, showNotice: (...args) => notices.push(args), request() { throw new Error("this action must not submit or retry work"); } };
  vm.runInNewContext(section("function appendRecoveryActions", "function renderMessage") + "\nglobalThis.append=appendRecoveryActions;", context);
  const container = new ButtonNode("article"); context.append(container, { kind: "turn_error" });
  const button = container.children[0].children[1]; assert.equal(button.textContent, "补充要求");
  button.events.click(); assert.equal(focused, 1); assert.match(notices[0][0], /请直接说明你希望修改的目标、数据或执行方式/); assert.match(notices[0][0], /不会自动重试/);
});

test("context overflow and missing model credentials explain the user impact without exposing technical strings", () => {
  const f = fixture();
  for (const [summary, title] of [["The model input exceeds the route text budget; compact the session before another inference round", "这段对话暂时无法继续"], ['llm-deepseek: no API key for provider route "deepseek-official"; store DEEPSEEK_API_KEY', "AI 服务尚未配置完成"]]) {
    f.api.renderTurnTerminal({kind:'turn_error',session_id:'root',root_session_id:'root',summary});
    const card = f.list.children.at(-1);
    assert.match(text(card,true),new RegExp(title));
    assert.doesNotMatch(text(card,true),/text budget|API_KEY|provider route/);
    assert.match(text(card),new RegExp(summary.includes('text budget')?'text budget':'API_KEY'));
  }
  assert.equal(f.api.providerErrorPresentation({error:{source:'dataset_tool',code:'CONTEXT_BUDGET',message:'dataset budget exceeded'}}),null);
});
