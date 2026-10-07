import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  get childElementCount() { return this.children.length; }
  text() { return this.textContent + this.children.map(node => node.text()).join(" "); }
}

test("download confirmation shows only the exact current call's filename and retains inspectable hashes", () => {
  const item = { tool_name: "model_harness_download_artifact_bundle", session_id: "root", agent_run_id: "turn-owner", turn_id: "turn-1", call_id: "download-1" };
  const args = { task_id: "task-a", destination_path: "/Users/private/exports/ranking.zip", bundle_id: "bundle-a", archive_sha256: "a".repeat(64), manifest_sha256: "b".repeat(64) };
  const event = { ...item, event_type: "tool_call", task_id: "task-a", payload: { tool_name: item.tool_name, arguments: args } };
  const state = { selectedTaskId: "task-a", conversation: { events: [event] } };
  const start = app.indexOf("function appendApprovalScope"), end = app.indexOf("function agentActivityLabel", start);
  const context = { state, document: { createElement: tag => new Element(tag) }, contractApprovalSummary: () => [] };
  vm.runInNewContext(app.slice(start, end) + "\nglobalThis.render=appendApprovalScope;", context);
  const card = new Element("article"); context.render(card, item);
  assert.match(card.text(), /ranking.zip/); assert.doesNotMatch(card.text(), /Users\/private/);
  assert.match(card.text(), /a{64}/); assert.ok(card.children.some(node => node.tag === "details"));
  for (const altered of [{ ...event, task_id: "other" }, { ...event, call_id: "older" }]) {
    state.conversation.events = [altered]; const next = new Element("article"); context.render(next, item); assert.equal(next.text(), "");
  }
  state.conversation.events = [event, event]; const ambiguous = new Element("article"); context.render(ambiguous, item); assert.equal(ambiguous.text(), "");
});
