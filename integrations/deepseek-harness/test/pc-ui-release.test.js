import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
const section = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from) + from.length));

test("a completed training run with failed quality is never presented as a green completed outcome", () => {
  const context = {}; vm.runInNewContext(section("function completedTrainingStatus", "function workflowStatus") + "\nglobalThis.status=completedTrainingStatus;", context);
  const report = { task_id: "task-a", run_id: "run-a", run_status: "completed", report_sha256: "a".repeat(64), conclusion: "quality_failed", release_ready: false };
  const task = { task_id: "task-a", status: "completed", current_run_id: "run-a", current_result: { status: "completed", run_id: "run-a", evaluation_report: report } };
  assert.match(context.status(task).label, /质量未达标/); assert.notEqual(context.status(task).tone, "completed");
  for (const changed of [{ run_id: "old" }, { task_id: "foreign" }, { report_sha256: "missing" }, { run_status: "running" }]) {
    task.current_result.evaluation_report = { ...report, ...changed }; assert.equal(context.status(task), null);
  }
});
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ""; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  querySelectorAll() { return [...(this.dataset.aiTurnStatusLabel ? [this] : []), ...this.children.flatMap(child => child.querySelectorAll())]; }
}
function fixture(presentation) {
  let now = Date.parse("2026-10-04T03:30:00Z");
  class ClockDate extends Date { static now() { return now; } }
  const f = { Date: ClockDate, ui: { messageList: new Node("div") }, document: { createElement: tag => new Node(tag) }, aiTurnPresentation: () => presentation,
    InteractionShell: { canShowTurnStop: () => false, createAiTurnFrame(_document, list) { const frame = { section: new Node("section"), header: new Node("header"), content: new Node("div") }; frame.section.append(frame.header, frame.content); list.append(frame.section); return frame; } } };
  vm.runInNewContext(section("function timestampMs", "function formatRelativeTime") + section("function createAiTurnContainer", "function appendAiTurnPlaceholder") + "\nglobalThis.api={createAiTurnContainer,syncAiTurnElapsedLabels};", f);
  return { f, advance: ms => { now += ms; } };
}

test("a long human approval wait is not labeled as AI processing time and stays quiet across timer ticks", () => {
  const t = fixture({ label: "等待验证工程方案", tone: "needs_confirmation", phase: "waiting_approval", current: true });
  const frame = t.f.api.createAiTurnContainer({ group_key: "turn", items: [{ time: "2026-10-04T03:00:00Z" }, { time: "2026-10-04T03:29:00Z" }] }, {}, {}, []);
  const label = frame.section.querySelectorAll()[0]; assert.equal(label.textContent, "等待验证工程方案");
  t.advance(5 * 60_000); t.f.api.syncAiTurnElapsedLabels(frame.section);
  assert.equal(label.textContent, "等待验证工程方案"); assert.doesNotMatch(label.textContent, /已处理|分钟|秒/);
});

test("resuming after a long human wait never appends whole-turn elapsed time to an active status", () => {
  const t = fixture({ label: "AI 正在处理", tone: "running", current: true });
  const frame = t.f.api.createAiTurnContainer({ items: [{ time: "2026-10-04T03:29:50Z" }] }, {}, {}, []);
  const label = frame.section.querySelectorAll()[0]; assert.equal(label.textContent, "AI 正在处理");
  assert.equal(label.dataset.startedAt, undefined);
  // A previously rendered node may still carry obsolete timer metadata.
  label.dataset.startedAt = String(Date.parse("2026-10-04T02:47:02Z")); label.dataset.elapsedLive = "true";
  t.advance(42 * 60_000); t.f.api.syncAiTurnElapsedLabels(frame.section); assert.equal(label.textContent, "AI 正在处理");
  for (const status of ["等待你的回答", "本轮已处理", "本轮已停止", "模型账户余额不足"]) {
    label.dataset.baseLabel = status; label.dataset.elapsedLive = "false"; t.f.api.syncAiTurnElapsedLabels(frame.section); assert.equal(label.textContent, status);
  }
});

test("the coupled PC UI scripts and styles use one incremented cache version and resolve to local files", () => {
  const html = readFileSync(new URL("../../../model_harness/web/index.html", import.meta.url), "utf8");
  const names = ["app.js", "conversation-view.js", "interaction-shell.js", "styles.css", "visual-system.css"];
  const versions = names.map(name => {
    const match = [...html.matchAll(/(?:src|href)="\/app\/static\/([^"?]+)\?v=([^"#]+)"/g)].find(item => item[1] === name);
    assert.ok(match, name); assert.equal(existsSync(new URL(`../../../model_harness/web/${name}`, import.meta.url)), true); return match[2];
  });
  assert.deepEqual([...new Set(versions)], ["2.4.53-pc-rc"]);
});

test("persistent result uses only the current canonical completed Run and owned prediction", () => {
  const report={task_id:'task-owned',run_id:'run-owned',run_status:'completed',report_sha256:'a'.repeat(64),release_ready:false,conclusion:'quality_failed'};
  const sample={task_id:'task-owned',run_id:'run-owned',status:'passed',prediction_sha256:'b'.repeat(64),prediction:'actual'};
  const f={state:{task:{task_id:'task-owned',status:'completed',current_run_id:'run-owned',current_result:{run_id:'run-owned',status:'completed',evaluation_report:report}},evidenceRunId:'run-owned',evaluationReport:report,sampleInferences:[sample]},EVIDENCE_SHA256:/^[a-f0-9]{64}$/,terminalResultMetrics:()=>[],statusLabel:x=>x};
  vm.runInNewContext(section('function runCheckpointSummaryModel','function appendRunCheckpointSummary')+'\nglobalThis.model=runCheckpointSummaryModel;',f);
  assert.equal(f.model().ready,false);assert.equal(f.model().sample,sample);
  f.state.sampleInferences=[{...sample,task_id:'foreign'}];assert.equal(f.model().sample,undefined);
  f.state.evaluationReport={...report,run_id:'old'};assert.equal(f.model(),null);
  f.state.evaluationReport=report;f.state.task.current_run_id='new';assert.equal(f.model(),null);
});

test("a misclassified closing answer remains readable without treating active work or historical plans as completion",()=>{
  const f={state:{task:{current_run_id:'run-current',current_result:{run_id:'run-current',status:'completed'}}},conversationHasActiveWork:c=>c.running,currentHumanCheckpoint:c=>c.pending};
  vm.runInNewContext(section('function closingCoordinatorPlan','function renderConversationTurn')+'\nglobalThis.closing=closingCoordinatorPlan;',f);
  const item={kind:'coordinator_plan',text:'已保存，质量仍未达标'},done={running:false,pending:null};
  assert.equal(f.closing(item,0,[item,{kind:'turn_finished'}],true,done),true);
  assert.equal(f.closing(item,0,[item],false,done),false);
  assert.equal(f.closing(item,0,[item],true,{...done,running:true}),false);
  assert.equal(f.closing(item,0,[item],true,{...done,pending:{kind:'approval'}}),false);
  assert.equal(f.closing(item,0,[item,{kind:'turn_error'}],true,done),false);
  assert.equal(f.closing(item,0,[item,{kind:'coordinator_note'}],true,done),false);
  f.state.task.current_run_id='another-run';assert.equal(f.closing(item,0,[item],true,done),false);
});
