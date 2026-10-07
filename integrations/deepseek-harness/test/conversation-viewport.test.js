import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const viewportFunctions = source.slice(source.indexOf("function captureConversationViewport"), source.indexOf("function renderConversation("));
function fixture() {
  const state = { selectedTaskId: "task-a" };
  const viewport = { scrollTop: 800, scrollHeight: 2200, getBoundingClientRect: () => ({ top: 100, bottom: 700 }) };
  let positions = [{ id: "turn-a", top: 0, height: 500 }, { id: "turn-b", top: 500, height: 1200 }, { id: "turn-c", top: 1700, height: 500 }];
  const element = row => ({ dataset: { turnId: row.id }, getBoundingClientRect: () => ({ top: 100 + row.top - viewport.scrollTop, bottom: 100 + row.top + row.height - viewport.scrollTop }) });
  const ui = { conversation: viewport, messageList: { children: positions.map(element) } };
  const context = { state, ui };
  vm.runInNewContext(`${viewportFunctions}\nglobalThis.api={captureConversationViewport,restoreConversationViewport};`, context);
  return { ...context, viewport, redraw(rows = positions) { positions = rows; viewport.scrollTop = 0; ui.messageList.children = positions.map(element); } };
}

test("a refresh preserves reading position after message-list replacement clamps scroll to zero", () => {
  const f = fixture();
  const snapshot = f.api.captureConversationViewport();
  assert.equal(snapshot.turn_id, "turn-b");
  f.redraw();
  assert.equal(f.viewport.scrollTop, 0);
  f.api.restoreConversationViewport(snapshot);
  assert.equal(f.viewport.scrollTop, 800);
  assert.equal(f.ui.messageList.children[1].getBoundingClientRect().top, -200);
});

test("earlier content growth preserves the visible turn instead of shifting the user's text", () => {
  const f = fixture(); const snapshot = f.api.captureConversationViewport();
  f.redraw([{ id: "turn-a", top: 0, height: 650 }, { id: "turn-b", top: 650, height: 1200 }, { id: "turn-c", top: 1850, height: 500 }]);
  f.api.restoreConversationViewport(snapshot);
  assert.equal(f.viewport.scrollTop, 950);
  assert.equal(f.ui.messageList.children[1].getBoundingClientRect().top, -200);
  f.api.restoreConversationViewport(snapshot);
  assert.equal(f.viewport.scrollTop, 950, "the animation-frame correction must be idempotent");
});

test("following latest reaches the bottom; a stale render never scrolls another task", () => {
  const f = fixture(); const snapshot = f.api.captureConversationViewport();
  f.api.restoreConversationViewport(snapshot, true);
  assert.equal(f.viewport.scrollTop, 2200);
  f.state.selectedTaskId = "task-b"; f.viewport.scrollTop = 50;
  f.api.restoreConversationViewport(snapshot, true);
  assert.equal(f.viewport.scrollTop, 50);
});
