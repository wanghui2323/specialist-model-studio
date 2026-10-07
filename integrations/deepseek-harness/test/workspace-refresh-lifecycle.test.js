import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const source = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from) + from.length));

test("visible task-list refresh is throttled, quiet while hidden, and can refresh on return", async () => {
  let now = 100_000, calls = 0;
  const f = { state: {}, document: { visibilityState: "visible" }, Date: { now: () => now }, loadTasks: async options => { calls += 1; assert.equal(options.preserveRows, true); } };
  vm.runInNewContext(section("async function refreshTaskListIfDue", "async function loadTasks") + "\nglobalThis.refresh=refreshTaskListIfDue;", f);
  assert.equal(await f.refresh(), true); assert.equal(calls, 1);
  now += 6000; assert.equal(await f.refresh(), false);
  now += 20_000; f.document.visibilityState = "hidden";
  assert.equal(await f.refresh({ force: true }), false);
  f.document.visibilityState = "visible"; assert.equal(await f.refresh({ force: true }), true); assert.equal(calls, 2);
  f.state.taskListLoadPromise = {}; assert.equal(await f.refresh({ force: true }), false);
});

test("concurrent task-list readers share one network request", async () => {
  let calls = 0, release;
  const f = { state: {}, request: () => { calls += 1; return new Promise(resolve => { release = resolve; }); } };
  vm.runInNewContext(section("async function taskListPayload", "async function refreshTaskListIfDue") + "\nglobalThis.payload=taskListPayload;", f);
  const one = f.payload(), two = f.payload(); assert.equal(calls, 1);
  const payload = { tasks: [] }; release(payload);
  assert.equal(await one, payload); assert.equal(await two, payload); assert.equal(f.state.taskListLoadPromise, null);
});

test("automatic list refresh patches existing rows without replacing the focused task controls", () => {
  const title = {}, dot = { dataset: {} }, time = {}, archive = { getAttribute: () => null, setAttribute() {} };
  const button = { querySelector: () => title, setAttribute() {} };
  const status = { querySelector: () => dot, replaceChildren(...children) { this.children = children; } };
  const row = { dataset: { taskId: "task-a" }, querySelector: selector => ({ ".task-item": button, ".task-workflow": status, "time": time, ".task-archive-button": archive })[selector] };
  const taskList = { querySelectorAll: () => [row] };
  const f = { state: { tasks: [{ task_id: "task-a", name: "已完成的任务", status: "completed" }], selectedTaskId: "task-other", conversation: null },
    ui: { taskList }, taskListStatus: task => ({ tone: task.status, label: "本轮已完成" }), formatRelativeTime: () => "刚刚", document: { activeElement: button, createTextNode: text => ({ textContent: text }) },
    clear() { throw new Error("stable rows must not be removed"); } };
  vm.runInNewContext(section("function renderTaskList", "function syncSelectedTaskListStatus") + "\nrenderTaskList({preserveRows:true});", f);
  assert.equal(f.document.activeElement, button); assert.equal(title.textContent, "已完成的任务"); assert.equal(dot.dataset.status, "completed");
  assert.equal(status.children[1].textContent, "本轮已完成"); assert.equal(f.state.selectedTaskId, "task-other");
});

test("periodic workspace rendering cannot reveal the overview above an exact object viewer", () => {
  const ui = new Proxy({}, { get: (target, key) => target[key] ||= { dataset: {}, querySelector: () => ({}) } });
  const f = { state: { inspectorMode: "object-viewer" }, ui,
    workspaceEvaluationOutcome: () => ({ ready: false }), WORKSPACE_PHASE_COPY: { idle: {} },
    projectionSpecialists: () => [], activeProjectionSpecialists: () => [], uniqueTaskObjectRefs: () => [],
    partitionWorkspaceResultRefs: () => ({ current: [], historical: [] }), clear() {}, workspaceContextForProjection: () => "plan",
  };
  vm.runInNewContext(section("function pendingExecutionIntegration", "function workflowStatus") + section("function preparationProgressFacts", "function workspaceContextForPhase") + "\nglobalThis.render=renderWorkspaceExperience;", f);
  f.render({ task_id: "task-a" }, {}, { phase: "idle", result: {}, workspace: { auto_open: true } });
  assert.equal(ui.workspaceExperience.hidden, true); assert.equal(ui.inspectorContent.hidden, true);
  assert.equal(f.state.inspectorMode, "object-viewer");
});
