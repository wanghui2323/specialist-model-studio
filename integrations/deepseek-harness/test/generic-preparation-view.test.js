import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const view = require("../../../model_harness/web/conversation-view.js");
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../../../model_harness/web/index.html", import.meta.url), "utf8");
function section(from, to) { return app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length)); }
const context = { state: { materialsOwnerId: null, materialInspections: [], modelSourceSearches: [] } };
vm.runInNewContext(section("function preparationProgressFacts", "function renderPreparationProgress") + section("function nextActionDescription", "function valueOrDash") + "\nglobalThis.facts=preparationProgressFacts; globalThis.next=nextActionDescription;", context);

for (const family of ["new_model_family", "custom_multimodal_goal", "user_defined_architecture"]) {
  test(`catalog miss preserves the ${family} goal and preparation path without fabricating execution`, () => {
    const task = { task_id: "task-a", status: "needs_recipe", capability_status: "needs_recipe", capability_decision: { selected_family: family }, task_spec: { business_goal: "解决当前业务任务", revision: 1 }, recipe_id: null, current_run_id: null };
    const before = JSON.stringify(task); const capability = view.trainingCapabilityProjection(task), facts = context.facts(task);
    assert.equal(capability.state, "pending"); assert.equal(capability.label, "准备训练方案"); assert.match(capability.reason, /现成方案.*继续准备/);
    assert.equal(facts.length, 4); assert.equal(facts[0].text, task.task_spec.business_goal); assert.equal(facts[2].state, "pending");
    assert.match(facts[2].text, /训练路线.*验证步骤/); assert.doesNotMatch(JSON.stringify(facts), /已启动|训练完成|不支持|改成分类/);
    assert.equal(JSON.stringify(task), before);
  });
}

test("preparation facts show retained material separately from the real Dataset and ignore another task's materials", () => {
  const task = { task_id: "task-a", task_spec: { business_goal: "业务目标" }, material_inspections: { count: 2, latest_status: "rejected" } };
  context.state.materialsOwnerId = "other"; context.state.materialInspections = [{ owner_id: "other", status: "inspected" }];
  let facts = context.facts(task); assert.match(facts[1].text, /2 份材料.*检查发现问题.*训练数据尚未导入/);
  delete task.material_inspections; facts = context.facts(task); assert.equal(facts[1].state, "pending");
  task.dataset_id = "dataset-verified"; facts = context.facts(task); assert.match(facts[1].text, /训练数据集已导入.*dataset-verified/);
});

test("source and plan facts advance only with owned records and do not count stale or foreign searches as progress", () => {
  const task = { task_id: "task-a", current_spec_revision: 2, task_spec: { business_goal: "业务目标" } };
  context.state.modelSourceSearches = [{ base_spec_revision: 1, search_id: "old" }]; assert.equal(context.facts(task)[2].state, "pending");
  context.state.modelSourceSearches = [{ task_id: "other", base_spec_revision: 2, search_id: "foreign" }]; assert.equal(context.facts(task)[2].state, "pending");
  context.state.modelSourceSearches = [{ task_id: "task-a", base_spec_revision: 2, search_id: "current" }]; assert.match(context.facts(task)[2].text, /1 次来源检索记录/);
  task.model_binding = { status: "stale" }; assert.match(context.facts(task)[2].text, /来源需随目标更新/);
  task.training_plan = { stale: false, effective_status: "approved" }; assert.match(context.facts(task)[2].text, /执行计划已批准.*运行条件仍需核验/);
  task.training_plan.stale = true; assert.match(context.facts(task)[2].text, /计划需随目标更新/);
});

test("real security and resource blockers stay explicit while directory misses do not become a blanket refusal", () => {
  const gap = { code: "recipe_unavailable", active: true, message: "目录无匹配" };
  const task = { task_id: "task-a", capability_status: "needs_recipe", blockers: [gap], task_spec: { business_goal: "业务目标" } };
  assert.equal(view.trainingCapabilityProjection(task).state, "pending");
  for (const code of ["blocked_security", "blocked_license", "qualification_failed"]) {
    task.blockers = [gap, { code, active: true, message: "真实阻断原因" }]; assert.equal(view.trainingCapabilityProjection(task).state, "blocked"); assert.equal(view.trainingCapabilityProjection(task).reason, "真实阻断原因");
  }
  task.resource_feasibility = { decision: "blocked_resources", blockers: [{ message: "实测内存不足" }] };
  assert.equal(context.facts(task)[3].state, "blocked"); assert.equal(context.facts(task)[3].text, "实测内存不足");
  assert.match(context.next({ id: "review_capability_gap" }, gap), /结合目标和已有材料准备训练路线/);
  assert.equal(context.next({ id: "review_capability_gap" }, { code: "blocked_security", message: "真实安全阻断" }), "真实安全阻断");
});

test("home shortcuts are examples and developer scaffolding stays outside the primary preparation flow", () => {
  assert.match(html, /现成训练方案快捷示例/); assert.match(html, /也可以直接描述其他目标/);
  assert.doesNotMatch(html, /语音转文字、OCR、检测等尚未支持训练|需要构建还是当前不支持/);
  assert.match(html, /<details[^>]+id="recipeExtensionDetails"[^>]*hidden>[\s\S]*?<summary>开发者参考（可选）<\/summary>/);
  assert.match(html, /id="workspacePreparationProgress" hidden/);
  assert.doesNotMatch(app, /完成实现和测试后再注册|当前分析没有可用训练入口，不能生成计划/);
});

test("pure catalog-miss objects use a neutral label while keeping canonical ref, history and security failures intact", () => {
  const element = () => ({ children: [], append(...nodes) { this.children.push(...nodes); }, addEventListener(name, handler) { this[name] = handler; } });
  const target = element(), opened = [];
  const task = { task_id: "task-a", status: "needs_recipe", capability_status: "needs_recipe", blockers: [{ blocker_id: "gap-a", task_id: "task-a", code: "recipe_unavailable", content_digest: "digest-a" }] };
  const f = { state: { task }, ui: { workspaceResultList: target }, document: { createElement: element }, shortId: value => value, openObjectRef: ref => opened.push(ref) };
  vm.runInNewContext(section("function catalogGapObjectRef", "function workspaceEvaluationOutcome") + "\nglobalThis.render=renderWorkspaceResultRef;", f);
  const gap = { type: "blocker", task_id: "task-a", id: "gap-a", digest: "digest-a", label: "阻塞证据 · recipe_unavailable" };
  const before = JSON.stringify({ task, gap }); f.render(gap, target, true);
  assert.equal(target.children[0].children[0].textContent, "·"); assert.equal(target.children[0].children[1].children[0].textContent, "方案匹配记录");
  assert.match(target.children[0].children[1].children[1].textContent, /历史运行/); target.children[0].click(); assert.equal(opened[0], gap); assert.equal(JSON.stringify({ task, gap }), before);
  task.blockers.push({ blocker_id: "security-a", task_id: "task-a", code: "blocked_security", content_digest: "digest-b" });
  f.render({ ...gap, id: "security-a", digest: "digest-b", label: "安全阻断" }); assert.equal(target.children[1].children[1].children[0].textContent, "安全阻断");
  f.render({ ...gap, id: "unknown", label: "阻塞证据 · recipe_unavailable" }); assert.equal(target.children[2].children[1].children[0].textContent, "阻塞证据 · recipe_unavailable", "display prose alone must not reclassify an unverified object");
});

test("inspector heading follows the same pure-gap predicate without softening real resource failures", () => {
  const task = { task_id: "task-a", status: "needs_recipe", blockers: [{ code: "recipe_unavailable" }] };
  const f = { state: { task, conversation: { task_id: "task-a", projection_health: "healthy", risks: [], pending: [], interaction_projection: { phase: "idle" } }, workspaceProjection: { phase: "blocked" } } };
  vm.runInNewContext(section("function pendingExecutionIntegration", "function workflowStatus") + section("function workspaceSheetTitle", "function openInspector") + "\nglobalThis.title=workspaceSheetTitle;", f);
  assert.equal(f.title("plan", "experience"), "方案准备");
  task.blockers.push({ code: "blocked_resources", message: "内存不足" }); assert.equal(f.title("plan", "experience"), "恢复任务");
  task.blockers = [{ code: "blocked_security", message: "未通过安全检查" }]; assert.equal(f.title("plan", "experience"), "恢复任务");
});
