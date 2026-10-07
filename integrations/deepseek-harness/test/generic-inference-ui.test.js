import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
const app = readFileSync(new URL("../../../model_harness/web/app.js", import.meta.url), "utf8");
function section(from, to) { const start = app.indexOf(from); return app.slice(start, app.indexOf(to, start + from.length)); }
class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.value = ""; this.classList = { add() {} }; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  flat() { return this.children.flatMap(item => [item, ...item.flat()]); }
  click() { this.clicked = true; }
}
function fixture(declaration = { extensions: [".json"], max_bytes: 2048, schema: { type: "object", required: ["sensor", "window"], properties: { sensor: { type: "number", minimum: 0 }, window: { type: "integer" }, mode: { type: "string", enum: ["stable", "rapid"] }, enabled: { type: "boolean" } } } }) {
  const checkpoint = { kind: "question", rpc_id: "input-question", status: "pending", questions: [{ id: "inference_input_id" }] };
  const state = { selectedTaskId: "task-a", conversation: { pending: [checkpoint] }, task: { task_id: "task-a", current_result: { recipe: "generic-isolated-execution", run_id: "run-a", status: "completed" }, contract: { recipe: "generic-isolated-execution", execution_spec: { inference: declaration } } } };
  const actions = new Element(), requests = [], answers = [], notices = [];
  const context = { state, TextEncoder, INFERENCE_INPUT_QUESTION_IDS: new Set(["inference_input_id"]), ui: {}, document: { createElement: tag => new Element(tag) }, formatBytes: size => `${size} B`, showNotice: message => notices.push(message), showTransientNotice() {}, setButtonBusy() {}, refreshSelected: async () => {},
    currentHumanCheckpoint: conversation => conversation.pending[0], isPendingHumanCheckpoint: item => item.status === "pending", postQuestionAnswers: async (...args) => answers.push(args),
    request: async (path, options) => { requests.push([path, options]); return { inference_input: { task_id: "task-a", run_id: "run-a", inference_input_id: "input-a", sha256: "a".repeat(64), sample_type: "generic" } }; },
  };
  vm.runInNewContext(section("function sampleTypeForRecipe", "function renderSampleTrials") + section("function inferenceInputQuestionCheckpoint", "function syncTaskSpecCheckpointOwnership") + section("async function stageInferenceInput", "async function runSampleTrial") + section("function appendInferenceInputActions", "function renderHumanCheckpoint") + "\nglobalThis.api={appendInferenceInputActions,genericInferenceSpec,genericInputEditor,checkGenericInputFile,stageInferenceInput};", context);
  return { context, state, checkpoint, actions, requests, answers, notices, api: context.api };
}

test("generic sample fields follow the declared schema and stage actual JSON into the original question without executing", async () => {
  const f = fixture(); f.api.appendInferenceInputActions(f.actions, f.checkpoint);
  const fields = f.actions.flat().filter(item => item["aria-label"]);
  assert.deepEqual(fields.map(item => item["aria-label"]), ["sensor", "window", "mode", "enabled"]);
  fields[0].value = "2.5"; fields[1].value = "4"; fields[2].value = "1"; fields[3].value = "1";
  await f.actions.children.find(item => item.tag === "button").events.click();
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0][0], "/tasks/task-a/runs/run-a/inference-inputs");
  assert.equal(f.requests[0][1].headers["X-Sample-Type"], "generic"); assert.deepEqual(JSON.parse(f.requests[0][1].body), { sensor: 2.5, window: 4, mode: "rapid", enabled: false });
  assert.equal(f.answers.length, 1); assert.equal(f.answers[0][0].rpc_id, "input-question"); assert.match(f.answers[0][1][0].custom, /inference_input_id=input-a/);
  assert.ok(f.requests.every(([path]) => !/sample-inferences|authorizations|execution-proposals/.test(path)), "upload remains staging only");
});

test("plain text uses the declared txt transport even when structured JSON is also allowed", async () => {
  const f = fixture({ extensions: [".txt", ".json"], max_bytes: 2048, schema: { oneOf: [{ type: "string" }, { type: "object", properties: { text: { type: "string" } } }] } });
  f.api.appendInferenceInputActions(f.actions, f.checkpoint);
  f.actions.flat().find(item => item["aria-label"] === "新样本").value = "新的中文输入";
  await f.actions.children.find(item => item.tag === "button").events.click();
  assert.equal(f.requests[0][1].body, "新的中文输入");
  assert.equal(f.requests[0][1].headers["X-Filename"], "new-sample.txt");
  assert.equal(f.requests[0][1].headers["Content-Type"], "text/plain; charset=utf-8");
  assert.equal(f.answers.length, 1);
});

test("invalid required/numeric/schema values stop before upload", async () => {
  const f = fixture(); f.api.appendInferenceInputActions(f.actions, f.checkpoint); const button = f.actions.children.find(item => item.tag === "button");
  await button.events.click(); assert.equal(f.requests.length, 0); assert.match(f.notices.at(-1), /请填写sensor/);
  const fields = f.actions.flat().filter(item => item["aria-label"]); fields[0].value = "-1"; fields[1].value = "4";
  await button.events.click(); assert.equal(f.requests.length, 0); assert.match(f.notices.at(-1), /超出声明范围/);
  fields[0].value = "1"; fields[1].value = "1.5"; await button.events.click(); assert.equal(f.requests.length, 0); assert.match(f.notices.at(-1), /integer/);
});

test("generic file sample picker follows extensions and byte limits without model-family cases", async () => {
  const f = fixture({ extensions: [".bin", ".custom"], max_bytes: 128 }); f.api.appendInferenceInputActions(f.actions, f.checkpoint);
  const picker = f.actions.children.find(item => item.tag === "input"); assert.equal(picker.accept, ".bin,.custom");
  picker.files = [{ name: "sample.bin", size: 256 }]; await picker.events.change(); assert.equal(f.requests.length, 0); assert.match(f.notices.at(-1), /超过/);
  picker.files = [{ name: "sample.custom", size: 64 }]; await picker.events.change(); assert.equal(f.requests.length, 1); assert.equal(f.requests[0][1].body, picker.files[0]); assert.equal(f.answers.length, 1);
});

test("stale/foreign inference receipts never answer the current task question", async () => {
  const f = fixture(); f.context.request = async () => ({ inference_input: { task_id: "other", run_id: "run-a", inference_input_id: "input-a", sha256: "a".repeat(64) } });
  await assert.rejects(f.api.stageInferenceInput({ body: "{}", filename: "a.json", contentType: "application/json", sampleType: "generic" }), /属于当前任务与运行/); assert.equal(f.answers.length, 0);
  f.context.request = async () => { f.state.selectedTaskId = "other"; return { inference_input: { task_id: "task-a", run_id: "run-a", inference_input_id: "input-a", sha256: "a".repeat(64) } }; };
  await assert.rejects(f.api.stageInferenceInput({ body: "{}", filename: "a.json", contentType: "application/json", sampleType: "generic" }), /已切换任务/); assert.equal(f.answers.length, 0);
});

test("run-bound inference declaration wins over a changed current contract", () => {
  const f = fixture(); f.state.task.current_result.inference = { extensions: [".fixed"], max_bytes: 9 };
  assert.deepEqual(f.api.genericInferenceSpec().extensions, [".fixed"]);
  f.state.task.current_result.recipe = "unknown-unqualified"; assert.equal(f.api.genericInferenceSpec(), null);
});

test("generic observed metrics and immutable gates are rendered without a classification/regression whitelist", () => {
  const context = {};
  vm.runInNewContext(section("function gateEntries", "function renderContract") + section("function metricEntries", "function renderResult") + section("function metricPresentation", "function terminalResultCardModel") + "\nglobalThis.api={gateEntries,metricEntries,terminalResultMetrics};", context);
  const gates = { edit_error: { operator: "lte", threshold: 0.0001 }, score_z: { operator: "gte", threshold: 0.7 } };
  assert.deepEqual(JSON.parse(JSON.stringify(context.api.gateEntries({}, gates))), [[0.0001, "edit_error 上限"], [0.7, "score_z 下限"]]);
  const result = { recipe: "generic-isolated-execution", metrics: { clean_test: { edit_error: 0.2, score_z: 0.9 } } };
  assert.deepEqual(JSON.parse(JSON.stringify(context.api.metricEntries(result))), [[0.2, "edit_error"], [0.9, "score_z"]]);
  const metrics = context.api.terminalResultMetrics({ contract: { execution_spec: { evaluation: { gates } } } }, result);
  assert.equal(metrics[0].gate, "≤ 0.0001"); assert.equal(metrics[0].passed, false); assert.equal(metrics[1].passed, true);
});

function mediaFixture() {
  const state = { selectedTaskId: "task-a", task: { current_result: { run_id: "run-a" } } };
  const context = { state, URL, location: { origin: "http://127.0.0.1:8878" }, document: { createElement: tag => new Element(tag) }, formatBytes: bytes => `${bytes} B` };
  vm.runInNewContext(section("function sampleOutputUrl", "function renderSampleTrials") + "\nglobalThis.api={sampleOutputUrl,renderSamplePrediction};", context);
  const artifact = (name, media_type) => ({ name, media_type, bytes: 64, sha256: "a".repeat(64), url: `/tasks/task-a/runs/run-a/sample-inferences/sample-a/files/${name.split("/").map(encodeURIComponent).join("/")}` });
  const check = { check_id: "sample-a", task_id: "task-a", run_id: "run-a", status: "passed", prediction: "模型已生成输出", artifacts: [artifact("声音.wav", "audio/x-wav"), artifact("view/prediction.png", "image/png"), artifact("clip.mp4", "video/mp4")] };
  return { ...context, api: context.api, check };
}

test("generated audio/image/video previews use only exact owned server artifact routes and do not autoplay", () => {
  const f = mediaFixture(), target = new Element(); f.api.renderSamplePrediction(f.check, target);
  assert.equal(target.children[0].textContent, "模型已生成输出");
  const media = target.flat().filter(item => ["audio", "img", "video"].includes(item.tag));
  assert.deepEqual(media.map(item => item.tag), ["audio", "img", "video"]);
  assert.equal(media[0].controls, true); assert.equal(media[0].preload, "metadata"); assert.equal(media[0].autoplay, undefined);
  assert.match(media[0].src, /^\/tasks\/task-a\/runs\/run-a\/sample-inferences\/sample-a\/files\//);
  assert.equal(media[1].loading, "lazy"); assert.equal(media[2].controls, true); assert.equal(media[2].preload, "metadata");
});

test("foreign, external, ambiguous or unverified artifact URLs are never embedded", () => {
  const f = mediaFixture(), base = f.check.artifacts[0];
  for (const url of ["https://example.com/a.wav", "//example.com/a.wav", base.url.replace("task-a", "other"), base.url.replace("run-a", "other"), base.url.replace("sample-a", "other"), `${base.url}?redirect=x`, `${base.url}#x`, "/tasks/task-a/runs/run-a/sample-inferences/sample-a/files/%2e%2e/secret.wav", "/tasks/task-a/runs/run-a/sample-inferences/sample-a/files/%252e%252e/secret.wav"]) {
    assert.equal(f.api.sampleOutputUrl(f.check, { ...base, url }), null, url);
  }
  assert.equal(f.api.sampleOutputUrl({ ...f.check, task_id: "other" }, base), null);
  assert.equal(f.api.sampleOutputUrl({ ...f.check, status: "failed" }, base), null);
  assert.equal(f.api.sampleOutputUrl(f.check, { ...base, sha256: "bad" }), null);
  const target = new Element(); f.api.renderSamplePrediction({ ...f.check, prediction: "<img src=x onerror=alert(1)>", artifacts: [{ ...base, url: "javascript:alert(1)" }] }, target);
  assert.equal(target.children[0].textContent, "<img src=x onerror=alert(1)>"); assert.equal(target.children.length, 1);
});

test("structured predictions are readable JSON and SVG/HTML outputs never become active embeds", () => {
  const f = mediaFixture(), target = new Element();
  f.check.prediction = { labels: ["alpha", "beta"], value: 2.5 };
  f.check.artifacts = [{ ...f.check.artifacts[1], name: "output.svg", media_type: "image/svg+xml", url: "/tasks/task-a/runs/run-a/sample-inferences/sample-a/files/output.svg" }];
  f.api.renderSamplePrediction(f.check, target);
  assert.equal(target.children[0].tag, "dl"); const raw = target.flat().find(item => item.tag === "pre"); assert.equal(raw.textContent, JSON.stringify(f.check.prediction, null, 2)); assert.equal(target.flat().find(item => item.tag === "details").open, undefined);
  assert.ok(!target.flat().some(item => ["img", "iframe", "object", "embed"].includes(item.tag))); assert.equal(target.flat().filter(item => item.tag === "a").length, 1);
});

test("engineering summaries distinguish saved code, running qualification, passed evidence and unconfirmed training", () => {
  const context = { readableActionText: value => value, STATUS_LABELS: {} };
  vm.runInNewContext(section("function parseActionResultValue", "function actionResultKey") + "\nglobalThis.summary=actionResultSummary;", context);
  const summary = status => context.summary({}, { payload: { result: { proposal: { proposal_id: "proposal-a", proposal_sha256: "a".repeat(64), status } } } });
  assert.match(summary("proposed").text, /代码已保存.*等待隔离验证/); assert.equal(summary("qualifying").state, "loading"); assert.match(summary("qualifying").text, /尚未启动正式训练/);
  assert.match(summary("qualified").text, /等待确认启用/); assert.equal(summary("qualification_failed").state, "failed"); assert.match(summary("activated").text, /合同仍需确认.*尚未启动正式训练/);
  const asset = context.summary({}, { payload: { result: { asset: { object_type: "ExecutionAsset", license: "unknown", license_review_required: true, license_policy: { decision: "review" }, files: [{}] } } } });
  assert.match(asset.text, /许可 unknown.*使用范围待核对/); assert.doesNotMatch(asset.text, /许可策略已记录/);
});

test("a declared plain-text input is typed directly and staged as UTF-8 text without requiring a file upload", async () => {
  const f = fixture({ extensions: [".txt"], max_bytes: 100, schema: { type: "string", title: "输入内容" } });
  f.api.appendInferenceInputActions(f.actions, f.checkpoint); const input = f.actions.flat().find(item => item["aria-label"] === "输入内容");
  assert.ok(input); input.value = "请处理这段内容";
  await f.actions.children.find(item => item.tag === "button").events.click();
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0][1].body, "请处理这段内容"); assert.equal(f.requests[0][1].headers["X-Filename"], "new-sample.txt");
  assert.equal(f.requests[0][1].headers["Content-Type"], "text/plain; charset=utf-8"); assert.equal(f.answers.length, 1);
});

test("generic Dataset facts show real files and split rows rather than fabricated table features", () => {
  const context = {};
  vm.runInNewContext(section("function datasetDetail", "function restoreCheckpointCard") + "\nglobalThis.detail=datasetDetail;", context);
  const facts = context.detail({ dataset_report: { kind: "generic_files", total_files: 3, split_counts: { train: { file_count: 1, csv_row_count: 80 }, validation: { file_count: 1, csv_row_count: 20 }, test: { file_count: 1, csv_row_count: 20 } } } });
  assert.equal(facts[0], "3 份文件"); assert.match(facts[1], /训练 1 份文件 \/ 80 行/); assert.match(facts[1], /独立测试 1 份文件 \/ 20 行/); assert.doesNotMatch(facts[1], /0 个特征|目标 —/);
});
