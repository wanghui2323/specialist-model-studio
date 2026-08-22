(function attachDraftStore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ModelHarnessDraftStore = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function createDraftStore() {
  const PREFIX = "model-harness:draft:v1:";
  const NEW_TASK = "__new__";

  function identity(taskId) {
    return String(taskId || NEW_TASK);
  }

  function key(taskId) {
    return `${PREFIX}${identity(taskId)}`;
  }

  function read(storage, taskId) {
    try {
      const raw = storage.getItem(key(taskId));
      if (!raw) return { text: "", updatedAt: null };
      const value = JSON.parse(raw);
      return {
        text: typeof value?.text === "string" ? value.text : "",
        updatedAt: Number.isFinite(value?.updatedAt) ? value.updatedAt : null,
      };
    } catch (_error) {
      return { text: "", updatedAt: null };
    }
  }

  function write(storage, taskId, text, updatedAt = Date.now()) {
    const selected = String(text || "");
    if (!selected) {
      storage.removeItem(key(taskId));
      return { text: "", updatedAt: null };
    }
    const value = { text: selected, updatedAt };
    storage.setItem(key(taskId), JSON.stringify(value));
    return value;
  }

  function clear(storage, taskId) {
    storage.removeItem(key(taskId));
  }

  return { PREFIX, NEW_TASK, key, read, write, clear };
});
