import test from "node:test";
import assert from "node:assert/strict";

import DraftStore from "../../../model_harness/web/draft-store.js";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

test("drafts are isolated by training task and survive store re-entry", () => {
  const storage = memoryStorage();
  DraftStore.write(storage, "task-a", "A 的未发送内容", 101);
  DraftStore.write(storage, "task-b", "B 的未发送内容", 202);

  assert.deepEqual(DraftStore.read(storage, "task-a"), {
    text: "A 的未发送内容",
    updatedAt: 101,
  });
  assert.deepEqual(DraftStore.read(storage, "task-b"), {
    text: "B 的未发送内容",
    updatedAt: 202,
  });
  assert.equal(DraftStore.read(storage, null).text, "");
});

test("successful send clears only the selected task draft", () => {
  const storage = memoryStorage();
  DraftStore.write(storage, "task-a", "send me");
  DraftStore.write(storage, "task-b", "keep me");

  DraftStore.clear(storage, "task-a");

  assert.equal(DraftStore.read(storage, "task-a").text, "");
  assert.equal(DraftStore.read(storage, "task-b").text, "keep me");
});

test("malformed local state fails closed to an empty draft", () => {
  const storage = memoryStorage();
  storage.setItem(DraftStore.key("task-a"), "not-json");
  assert.deepEqual(DraftStore.read(storage, "task-a"), {
    text: "",
    updatedAt: null,
  });
});
