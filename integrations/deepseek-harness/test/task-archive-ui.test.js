import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const app = await readFile(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");

function functionSource(name) {
  const start = app.search(new RegExp(`^(?:async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `actual app function ${name} exists`);
  const rest = app.slice(start + 1);
  const next = rest.search(/\n(?:async )?function /);
  assert.ok(next >= 0, `actual app function ${name} has a following declaration`);
  return app.slice(start, start + 1 + next);
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function node(tag = "div") {
  return {
    tag, dataset: {}, attributes: {}, children: [], disabled: false, hidden: false, className: "", listeners: {},
    classList: { add() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    focus() { this.focused = true; },
    querySelectorAll(selector) {
      const matches = (item) => selector.startsWith(".")
        ? String(item.className || "").split(" ").includes(selector.slice(1))
        : item.tag === selector;
      return this.children.flatMap((child) => [
        ...(matches(child) ? [child] : []), ...(child.querySelectorAll?.(selector) || []),
      ]);
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
  };
}

const archivedTask = (overrides = {}) => ({
  task_id: "task-archived", name: "Archived task", status: "completed", current_run_id: "run-archived",
  archived_at_utc: "2026-09-11T01:00:00Z", ...overrides,
});
const activeTask = (overrides = {}) => ({
  task_id: "task-active", name: "Active task", status: "completed", archived_at_utc: null, ...overrides,
});

function harness({ tasks = [archivedTask(), activeTask()], task = tasks[0], href = "http://127.0.0.1:8877/app?task=task-archived", request } = {}) {
  const state = {
    tasks, task, selectedTaskId: task?.task_id || null, conversation: null,
    taskListScope: "active", taskListScopeRevision: 0, taskListRequestSeq: 0, archiveMutations: new Set(), taskArchiveEpochs: new Map(), selectionToken: 0,
    refreshSeq: 0, refreshInFlight: false, runtimeReady: true, cancelRequestInFlight: false,
  };
  const ui = Object.fromEntries([
    "taskList", "activeTasksButton", "archivedTasksButton", "taskArchiveNotice", "restoreTaskButton",
    "messageInput", "sendButton", "taskEyebrow", "taskTitle", "taskStatus", "conversationMain", "composerWrap",
    "emptyState", "conversation", "inspector", "workspaceToggleButton", "mobileViewNav", "inspectorEmpty", "inspectorContent",
    "composerModeLabel", "composerMode", "agentCheckpoint", "messageList", "conversationIntro", "agentWorking", "cancelAgentButton", "agentWorkingLabel",
  ].map((name) => [name, node()]));
  const location = { href, pathname: new URL(href).pathname };
  const calls = { requests: [], notices: [], taskRenders: [], conversationRenders: [], home: [], selectedConversations: [], streams: [] };
  const context = {
    state, ui, location, URL,
    history: { replaceState(_state, _title, path) { location.href = new URL(path, location.href).href; location.pathname = new URL(location.href).pathname; } },
    document: { body: { dataset: {} }, createElement: node, createTextNode: (text) => ({ textContent: text }) },
    window: { requestAnimationFrame: (callback) => callback(), setInterval: () => 1 },
    clear: (element) => element.replaceChildren(), formatRelativeTime: () => "earlier",
    workflowStatus: (value) => ({ label: value.status, tone: value.status }),
    interactionPresentation: () => ({ label: "AI 正在回应", tone: "running" }),
    conversationHasActiveWork: () => false, currentHumanCheckpoint: () => null, backgroundCancellationPending: () => false,
    request: async (path, options = {}) => { calls.requests.push({ path, ...options }); return request ? request(path, options) : { tasks }; },
    showNotice: (text, tone) => calls.notices.push({ text, tone }),
    renderTask: (value) => calls.taskRenders.push(value), renderConversation: (force) => calls.conversationRenders.push(force),
    enterHomeState: (options) => calls.home.push(options),
    selectConversation: async (id) => calls.selectedConversations.push(id),
    refreshSelected: async () => { state.task = state.tasks.find((item) => item.task_id === state.selectedTaskId); },
    startConversationStream: (...args) => calls.streams.push(args),
  };
  for (const name of ["saveDraft", "restoreCheckpointCard", "resetHfDiscovery", "resetModelSourceDiscovery", "resetRunEvidence", "syncComposerAttachmentOwner", "clearComposerRetry", "stopPolling", "hideNotice", "closeSidebar", "closeInspector", "restoreDraft"]) context[name] = () => {};
  for (const name of ["taskListStatus", "syncTaskHeader", "loadTasks", "setTaskListScope", "syncTaskArchivePresentation", "renderTaskList", "syncSelectedTaskListStatus", "changeTaskArchive", "restoreTask", "selectTask"]) {
    vm.runInNewContext(functionSource(name), context);
  }
  return { context, state, ui, calls, location };
}

test("archived task request guard allows evidence reads and restore but rejects task, conversation and run mutations", async () => {
  let fetches = 0;
  const context = {
    state: { task: archivedTask() },
    fetch: async () => { fetches++; return { ok: true, status: 200, headers: { get: () => "application/json" }, text: async () => "{}" }; },
  };
  const start = app.indexOf("function structuredErrorMessage");
  const end = app.indexOf("function clear(element)", start);
  assert.ok(start >= 0 && end > start);
  vm.runInNewContext(app.slice(start, end), context);
  for (const method of [undefined, "GET", "get", "HEAD", "OPTIONS"]) {
    await context.request("/tasks/task-archived/runs/run-archived/evaluation-report", { method });
  }
  for (const path of ["/tasks/task-archived/restore", "/tasks/task-archived/archive"]) await context.request(path, { method: "POST" });
  const allowedFetches = fetches;
  for (const [path, method] of [
    ["/tasks/task-archived/dataset", "POST"], ["/tasks/task-archived/spec", "PATCH"],
    ["/tasks/task-archived/contract/confirm", "POST"], ["/tasks/task-archived/runs", "POST"],
    ["/tasks/task-archived/model-source-resolutions/source/bind", "POST"],
    ["/tasks/task-archived/runs/run-archived/artifact-bundles", "POST"],
    ["/conversations/task-archived/messages", "POST"], ["/conversations/task-archived/approvals/approval", "POST"],
    ["/runs/run-archived/cancel", "POST"], ["/runs/run-archived/strategies/strategy", "post"],
  ]) {
    await assert.rejects(context.request(path, { method }), (error) => error.status === 409 && error.retryable === false && /已归档/.test(error.message));
  }
  assert.equal(fetches, allowedFetches, "rejected writes never reach fetch");
  assert.equal(context.isArchivedTaskWrite("/tasks/task-archived-other/spec", "POST", context.state.task), false);
  assert.equal(context.isArchivedTaskWrite("/tasks/task-archived/spec", "POST", activeTask()), false);
  assert.equal(context.isArchivedTaskWrite("/tasks/task%20with%20space/dataset", "POST", archivedTask({ task_id: "task with space" })), true);
});

test("archive truth outranks stale running/completed state in task lists and the selected header", () => {
  for (const status of ["running", "completed"]) {
    const task = archivedTask({ status });
    const { context, state, ui } = harness({ tasks: [task], task });
    state.conversation = { task_id: task.task_id, agent_run: { status: "running" } };
    context.setTaskListScope("archived");
    context.syncTaskHeader(task, state.conversation, { phase: "executing" });
    context.syncSelectedTaskListStatus(state.conversation, { phase: "executing" });
    assert.equal(ui.taskEyebrow.textContent, "已归档 · 只读");
    assert.equal(ui.taskEyebrow.dataset.status, "archived");
    assert.equal(ui.taskList.querySelector(".task-workflow").querySelector("i").dataset.status, "archived");
    assert.equal(ui.taskList.querySelector(".task-archive-button").dataset.action, "restore-task");
    assert.equal(ui.taskList.querySelector(".task-archive-button").disabled, false);
  }
});

test("archive presentation locks only the selected archived task and reflects its pending restoration", () => {
  const { context, state, ui } = harness();
  state.archiveMutations.add(state.selectedTaskId);
  context.syncTaskArchivePresentation();
  assert.equal(context.document.body.dataset.taskArchived, "true");
  assert.equal(ui.taskArchiveNotice.hidden, false);
  assert.equal(ui.restoreTaskButton.disabled, true);
  assert.equal(ui.messageInput.disabled, true);
  assert.equal(ui.sendButton.disabled, true);
  state.selectedTaskId = "task-active";
  context.syncTaskArchivePresentation();
  assert.equal(context.document.body.dataset.taskArchived, "false");
  assert.equal(ui.taskArchiveNotice.hidden, true);
  assert.equal(ui.restoreTaskButton.disabled, false);
});

test("failed restore and invalid server identity never optimistically restore or reopen execution", async () => {
  for (const response of [new Error("restore unavailable"), { task: activeTask() }, { task: archivedTask() }]) {
    const task = archivedTask();
    const { context, state, calls } = harness({ task, request: async () => { if (response instanceof Error) throw response; return response; } });
    state.taskListScope = "archived";
    await context.restoreTask(task);
    assert.equal(state.task, task);
    assert.ok(state.tasks.find((item) => item.task_id === task.task_id).archived_at_utc);
    assert.equal(state.taskListScope, "archived");
    assert.equal(state.archiveMutations.size, 0);
    assert.equal(calls.requests.length, 1);
    assert.equal(calls.taskRenders.length, 0);
    assert.equal(calls.streams.length, 0);
    assert.equal(calls.notices.some((notice) => notice.tone === "ok"), false);
  }
});

test("duplicate restore clicks share one pending mutation and restoration does not start Agent or Run", async () => {
  const wait = deferred();
  const task = archivedTask();
  const restored = { ...task, archived_at_utc: null };
  const { context, state, ui, calls } = harness({ task, request: async (path) => path.endsWith("/restore") ? wait.promise : { tasks: [restored] } });
  const first = context.restoreTask(task);
  assert.equal(state.archiveMutations.has(task.task_id), true);
  assert.equal(ui.restoreTaskButton.disabled, true);
  assert.equal(state.task.archived_at_utc, task.archived_at_utc);
  await context.restoreTask(task);
  assert.equal(calls.requests.length, 1);
  wait.resolve({ task: restored });
  await first;
  assert.equal(state.task, restored);
  assert.equal(state.taskListScope, "active");
  assert.equal(state.archiveMutations.size, 0);
  assert.equal(ui.restoreTaskButton.disabled, false);
  assert.deepEqual(calls.requests.map(({ path, method }) => [path, method || "GET"]), [
    ["/tasks/task-archived/restore", "POST"], ["/tasks?include_archived=true", "GET"],
  ]);
  assert.equal(calls.streams.length, 0);
  assert.equal(calls.notices.some((notice) => /没有自动启动 AI 或训练/.test(notice.text)), true);
});

test("confirmed archive or restore survives a subsequent list refresh failure", async () => {
  for (const archive of [false, true]) {
    const task = archive ? activeTask() : archivedTask();
    const confirmed = { ...task, archived_at_utc: archive ? "2026-09-11T02:00:00Z" : null };
    const { context, state, calls } = harness({ task, request: async (path) => {
      if (path.startsWith("/tasks?")) throw new Error("list offline");
      return { task: confirmed };
    } });
    await context.changeTaskArchive(task, archive);
    assert.equal(state.task, confirmed);
    assert.equal(state.tasks.find((item) => item.task_id === task.task_id), confirmed);
    assert.equal(state.taskListScope, archive ? "archived" : "active");
    assert.equal(state.archiveMutations.size, 0);
    assert.equal(state.homeTasksReachable, false);
    assert.match(calls.notices.at(-1).text, /状态已保存.*列表刷新失败/);
    assert.ok(calls.notices.at(-1).text.includes(task.name), "refresh failure identifies the task whose mutation was saved");
    assert.equal(calls.streams.length, 0);
  }
});

test("scope switching preserves selected task URL and filters actual list rows across refresh", async () => {
  const { context, state, ui, location, calls } = harness({ href: "http://127.0.0.1:8877/app?task=task-active&view=evidence" });
  context.setTaskListScope("archived");
  assert.equal(new URL(location.href).searchParams.get("task"), "task-active");
  assert.equal(new URL(location.href).searchParams.get("view"), "evidence");
  assert.equal(new URL(location.href).searchParams.get("task_scope"), "archived");
  assert.equal(ui.taskList.querySelectorAll(".task-item")[0].dataset.taskId, "task-archived");
  await context.loadTasks();
  assert.equal(state.taskListScope, "archived");
  assert.equal(ui.archivedTasksButton.attributes["aria-pressed"], "true");
  context.setTaskListScope("unknown");
  assert.equal(state.taskListScope, "active");
  assert.equal(new URL(location.href).searchParams.has("task_scope"), false);
  assert.deepEqual(ui.taskList.querySelectorAll(".task-item").map((item) => item.dataset.taskId), ["task-active"]);
  assert.deepEqual(calls.requests.map((item) => item.path), ["/tasks?include_archived=true"]);
});

test("archived deep links select their exact task even without an archived URL scope", async () => {
  for (const suffix of ["", "&task_scope=archived"]) {
    const { context, state, location, calls } = harness({ task: null, href: `http://127.0.0.1:8877/app?task=task-archived${suffix}` });
    await context.loadTasks({ selectFromUrl: true });
    assert.equal(state.selectedTaskId, "task-archived");
    assert.equal(state.task.task_id, "task-archived");
    assert.equal(state.taskListScope, "archived");
    assert.equal(new URL(location.href).searchParams.get("task"), "task-archived");
    assert.equal(new URL(location.href).searchParams.get("task_scope"), "archived");
    assert.equal(calls.home.length, 0);
    assert.deepEqual(calls.requests.map(({ path, method }) => [path, method || "GET"]), [["/tasks?include_archived=true", "GET"]]);
  }
});

test("missing task deep links do not silently open a different task and archived home scope survives reload", async () => {
  const missing = harness({ task: null, href: "http://127.0.0.1:8877/app?task=missing&task_scope=archived" });
  await missing.context.loadTasks({ selectFromUrl: true });
  assert.equal(missing.state.selectedTaskId, null);
  assert.equal(missing.state.taskListScope, "archived");
  assert.equal(missing.calls.home.length, 1);
  assert.match(missing.calls.notices.at(-1).text, /没有替你打开其他任务/);
  const home = harness({ task: null, href: "http://127.0.0.1:8877/app?task_scope=archived" });
  await home.context.loadTasks({ selectFromUrl: true });
  assert.equal(home.state.taskListScope, "archived");
  assert.equal(home.calls.home.length, 1);
  assert.equal(home.ui.taskList.querySelectorAll(".task-item")[0].dataset.taskId, "task-archived");
});

test("late task-list responses never overwrite a newer archived-scope refresh", async () => {
  const first = deferred(), second = deferred();
  let count = 0;
  const { context, state } = harness({ request: () => (++count === 1 ? first.promise : second.promise) });
  context.setTaskListScope("archived");
  const older = context.loadTasks();
  const newer = context.loadTasks();
  const latest = archivedTask({ name: "Latest archive record" });
  second.resolve({ tasks: [latest] });
  await newer;
  first.resolve({ tasks: [activeTask()] });
  await older;
  assert.equal(state.tasks.length, 1);
  assert.equal(state.tasks[0], latest);
  assert.equal(state.taskListScope, "archived");
  assert.equal(state.homeTasksReachable, true);
});

test("late archive or restore replies preserve the other task the user has selected", async () => {
  for (const archive of [true, false]) {
    const wait = deferred();
    const task = archive ? activeTask() : archivedTask();
    const other = archive ? activeTask({ task_id: "task-other" }) : archivedTask({ task_id: "task-other" });
    const confirmed = { ...task, archived_at_utc: archive ? "2026-09-11T02:00:00Z" : null };
    const { context, state, location, calls } = harness({ tasks: [task, other], task, request: async (path) => path.startsWith("/tasks?") ? { tasks: [confirmed, other] } : wait.promise });
    context.setTaskListScope(archive ? "active" : "archived");
    const operation = context.changeTaskArchive(task, archive);
    await context.selectTask(other.task_id);
    const selectedUrl = location.href;
    const selectedScope = state.taskListScope;
    wait.resolve({ task: confirmed });
    await operation;
    assert.equal(state.selectedTaskId, other.task_id);
    assert.equal(state.task, other);
    assert.equal(state.taskListScope, selectedScope);
    assert.equal(location.href, selectedUrl);
    assert.ok(calls.notices.at(-1).text.includes(task.name), "late mutation notice identifies its owning task");
  }
});

test("explicit scope changes during restoration win even when the final scope equals the starting scope", async () => {
  const wait = deferred();
  const task = archivedTask(), restored = { ...task, archived_at_utc: null };
  const { context, state, location } = harness({ task, request: async (path) => path.startsWith("/tasks?") ? { tasks: [restored] } : wait.promise });
  context.setTaskListScope("archived");
  const operation = context.restoreTask(task);
  context.setTaskListScope("active");
  context.setTaskListScope("archived");
  const userSelectedUrl = location.href;
  wait.resolve({ task: restored });
  await operation;
  assert.equal(state.task, restored, "server truth is applied without undoing the user's navigation");
  assert.equal(state.taskListScope, "archived");
  assert.equal(location.href, userSelectedUrl);
});

test("returning to the same task during restoration does not reuse its older selection token", async () => {
  const wait = deferred();
  const task = archivedTask(), other = archivedTask({ task_id: "task-other" });
  const restored = { ...task, archived_at_utc: null };
  const { context, state, location } = harness({ tasks: [task, other], task, request: async (path) => path.startsWith("/tasks?") ? { tasks: [restored, other] } : wait.promise });
  context.setTaskListScope("archived");
  const scopeRevision = state.taskListScopeRevision;
  const operation = context.restoreTask(task);
  await context.selectTask(other.task_id);
  await context.selectTask(task.task_id);
  const selectedUrl = location.href;
  assert.equal(state.taskListScopeRevision, scopeRevision, "only the selection token changed");
  wait.resolve({ task: restored });
  await operation;
  assert.equal(state.task, restored);
  assert.equal(state.selectedTaskId, task.task_id);
  assert.equal(state.taskListScope, "archived");
  assert.equal(location.href, selectedUrl);
});

test("a pre-mutation task GET cannot undo confirmed archive truth or leave refreshing permanently locked", async () => {
  const oldRead = deferred();
  const task = activeTask({ current_run_id: null, current_spec_revision: 1 });
  const confirmed = { ...task, archived_at_utc: "2026-09-11T02:00:00Z" };
  let reads = 0;
  const { context, state } = harness({ tasks: [task], task, request: async (path) => {
    if (path === `/tasks/${task.task_id}`) return ++reads === 1 ? oldRead.promise : { task: confirmed };
    if (path.startsWith("/tasks?")) return { tasks: [confirmed] };
    if (path.endsWith("/archive")) return { task: confirmed };
    throw new Error(`Unexpected request ${path}`);
  } });
  context.isConversationDraft = () => false;
  context.reconcileComposerDatasetUpload = async () => {};
  state.modelSourceLoadedTaskId = task.task_id;
  vm.runInNewContext(functionSource("refreshSelected"), context);
  const read = context.refreshSelected({ includeConversation: false });
  assert.equal(state.refreshInFlight, true);
  await context.changeTaskArchive(task, true);
  oldRead.resolve({ task });
  await read;
  assert.equal(state.task, confirmed);
  assert.equal(state.tasks[0], confirmed);
  assert.equal(state.refreshInFlight, false);
  await context.refreshSelected({ includeConversation: false });
  assert.equal(reads, 2, "future ordinary refreshes are still possible");
});

test("confirming one task's archive does not discard the selected other task's in-flight refresh", async () => {
  const mutation = deferred(), otherRead = deferred();
  const task = activeTask(), confirmed = { ...task, archived_at_utc: "2026-09-11T02:00:00Z" };
  const other = activeTask({ task_id: "task-other", current_run_id: null, current_spec_revision: 1 });
  const latestOther = { ...other, name: "Fresh other task" };
  const { context, state } = harness({ tasks: [task, other], task, request: async (path) => {
    if (path.endsWith("/archive")) return mutation.promise;
    if (path === "/tasks/task-other") return otherRead.promise;
    if (path.startsWith("/tasks?")) return { tasks: [confirmed, other] };
    throw new Error(`Unexpected request ${path}`);
  } });
  context.isConversationDraft = () => false;
  context.reconcileComposerDatasetUpload = async () => {};
  vm.runInNewContext(functionSource("refreshSelected"), context);
  const operation = context.changeTaskArchive(task, true);
  state.selectedTaskId = other.task_id;
  state.selectionToken += 1;
  state.task = other;
  state.modelSourceLoadedTaskId = other.task_id;
  const read = context.refreshSelected({ includeConversation: false });
  mutation.resolve({ task: confirmed });
  await operation;
  otherRead.resolve({ task: latestOther });
  await read;
  assert.equal(state.task, latestOther);
  assert.equal(state.tasks.find((item) => item.task_id === other.task_id), latestOther);
  assert.equal(state.tasks.find((item) => item.task_id === task.task_id), confirmed);
  assert.equal(state.refreshInFlight, false);
});

test("external restoration re-enables composer input and invalidates the actual conversation render cache", () => {
  const task = archivedTask();
  const { context, state, ui } = harness({ task });
  let rendered = 0;
  state.conversation = { task_id: task.task_id, session_id: "saved-session", items: [], actions: [] };
  Object.assign(context, {
    conversationView: () => state.conversation,
    interactionProjection: () => ({ phase: "idle", turns: [], actions: [], workspace: {} }),
    isConversationDraft: () => false,
    projectionWorkItems: () => [], activeProjectionSpecialists: () => [],
    conversationObservationKey: () => "stable", activeBackgroundTrainingRun: () => null,
    conversationAgentResponseRunning: () => false, conversationHasBackgroundTraining: () => false,
    agentActivityLabel: () => "idle", renderAgentSurfaceState: () => { rendered++; },
    requestAnimationFrame: (callback) => callback(),
  });
  for (const name of ["syncConversationComposerPlaceholder", "syncComposerDelivery", "syncTaskSpecCheckpointOwnership", "syncLegacyConfirmationControls", "syncAgentCheckpoint", "renderProjectionHealth", "renderWorkspaceExperience", "syncCancelRequestUi"]) context[name] = () => {};
  vm.runInNewContext(functionSource("renderConversation"), context);
  context.renderConversation();
  assert.equal(ui.messageInput.disabled, true);
  assert.equal(ui.sendButton.disabled, true);
  assert.equal(rendered, 1);
  context.renderConversation();
  assert.equal(rendered, 1, "unchanged evidence can retain the cached view");
  state.task = { ...task, archived_at_utc: null };
  context.renderConversation();
  assert.equal(ui.messageInput.disabled, false);
  assert.equal(ui.sendButton.disabled, false);
  assert.equal(rendered, 2, "archive-only changes invalidate the cached conversation");
  state.runtimeReady = false;
  context.syncTaskArchivePresentation();
  assert.equal(ui.sendButton.disabled, true, "restoration never bypasses runtime readiness");
  state.runtimeReady = true;
  state.cancelRequestInFlight = true;
  context.syncTaskArchivePresentation();
  assert.equal(ui.messageInput.disabled, true);
  assert.equal(ui.sendButton.disabled, true, "restoration never bypasses cancellation controls");
  state.cancelRequestInFlight = false;
  ui.sendButton.dataset.busy = "true";
  context.syncTaskArchivePresentation();
  assert.equal(ui.sendButton.disabled, true, "restoration never enables a send already in progress");
});
