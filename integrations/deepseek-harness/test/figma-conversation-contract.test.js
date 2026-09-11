import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const InteractionShell = require("../../../model_harness/web/interaction-shell.js");
const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "../../../model_harness/web");

let sourcePromise;
function sources() {
  sourcePromise ||= Promise.all([
    readFile(join(web, "app.js"), "utf8"),
    readFile(join(web, "index.html"), "utf8"),
    readFile(join(web, "styles.css"), "utf8"),
    readFile(join(web, "visual-system.css"), "utf8"),
  ]).then(([app, html, legacyCss, visualCss]) => ({
    app,
    html,
    css: `${legacyCss}\n${visualCss}`,
  }));
  return sourcePromise;
}

function topLevelFunction(source, name) {
  const declaration = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`, "g");
  const match = declaration.exec(source);
  assert.ok(match, `${name} must remain a separately auditable top-level function`);
  const nextDeclaration = /\n(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(/g;
  nextDeclaration.lastIndex = match.index + match[0].length;
  const next = nextDeclaration.exec(source);
  return source.slice(match.index, next?.index ?? source.length);
}

function executableTerminalResultModel(app, state) {
  const source = [
    'const TERMINAL_RESULT_REF_TYPES = new Set(["evaluation_report", "artifact_bundle"]);',
    'const EVIDENCE_SHA256 = /^[0-9a-f]{64}$/;',
    topLevelFunction(app, "terminalResultRefs"),
    topLevelFunction(app, "reportForTerminalRef"),
    topLevelFunction(app, "bundleForTerminalRef"),
    topLevelFunction(app, "terminalResultMetrics"),
    topLevelFunction(app, "terminalResultCardModel"),
    "return terminalResultCardModel;",
  ].join("\n");
  return new Function("state", "runtimeStatusToken", "statusLabel", source)(
    state,
    (value) => String(value || "").toLowerCase(),
    (value) => String(value || "unknown"),
  );
}

function openingTagForId(html, id) {
  const match = html.match(new RegExp(`<[^>]+\\bid=["']${id}["'][^>]*>`, "i"));
  assert.ok(match, `#${id} must exist`);
  return match[0];
}

function classTokens(node) {
  return String(node.className || "").split(/\s+/).filter(Boolean);
}

function descendantsByClass(node, className) {
  return (node.children || []).flatMap((child) => [
    ...(classTokens(child).includes(className) ? [child] : []),
    ...descendantsByClass(child, className),
  ]);
}

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
  }

  append(...children) {
    children.forEach((child) => {
      child.parentNode = this;
      this.children.push(child);
    });
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName);
  }
}

test("user messages never own an execution timeline", async () => {
  const documentRef = new FakeDocument();
  const root = documentRef.createElement("main");
  const userMessage = documentRef.createElement("article");
  userMessage.className = "message user-message";
  InteractionShell.conversationTurnTarget({ role: "user", root }).append(userMessage);

  const frame = InteractionShell.createAiTurnFrame(documentRef, root, {
    turnId: "turn-1",
    state: "running",
    current: true,
  });
  const timeline = documentRef.createElement("details");
  timeline.className = "action-timeline";
  InteractionShell.conversationTurnTarget({
    role: "assistant",
    root,
    aiContent: frame.content,
  }).append(timeline);

  assert.equal(timeline.parentNode, frame.content);
  assert.equal(descendantsByClass(userMessage, "action-timeline").length, 0);
  assert.equal(descendantsByClass(frame.section, "action-timeline").length, 1);

  const { app } = await sources();
  const renderTurn = topLevelFunction(app, "renderConversationTurn");
  assert.match(renderTurn, /item\.role === "user"[\s\S]*?turnTarget\("user"\)/);
  assert.match(renderTurn, /renderActionTimeline\([\s\S]*?target:\s*turnTarget\("assistant"\)/);
  assert.doesNotMatch(renderTurn, /renderActionTimeline\([\s\S]*?target:\s*turnTarget\("user"\)/);
});

test("terminal result cards require exact task-owned evaluation or artifact evidence and expose one bounded action", async () => {
  const { app } = await sources();
  const refs = topLevelFunction(app, "terminalResultRefs");
  const report = topLevelFunction(app, "reportForTerminalRef");
  const bundle = topLevelFunction(app, "bundleForTerminalRef");
  const metrics = topLevelFunction(app, "terminalResultMetrics");
  const model = topLevelFunction(app, "terminalResultCardModel");
  const renderer = topLevelFunction(app, "appendTerminalResultCard");
  const finalRenderer = topLevelFunction(app, "renderFinalSynthesis");
  const returnedIdentity = topLevelFunction(app, "returnedObjectMatchesRef");
  const objectOpener = topLevelFunction(app, "openObjectRef");
  const download = topLevelFunction(app, "requestArtifactBundleDownload");

  assert.match(model, /completion_eligible\s*!==\s*true/);
  assert.match(model, /projection\??\.phase\s*!==\s*["']result_ready["']/);
  assert.match(model, /runtimeStatusToken\(item\.status\)\s*!==\s*["']completed["']/);
  assert.match(refs, /TERMINAL_RESULT_REF_TYPES\.has\(ref\??\.type\)/);
  assert.match(refs, /ref\.task_id\s*===\s*taskId/);
  assert.match(refs, /ref\.run_id\s*===\s*runId/);
  assert.match(refs, /ref\.id/);
  assert.match(refs, /EVIDENCE_SHA256\.test\(ref\.digest\)/);
  assert.match(report, /report\.task_id\s*!==\s*task\.task_id/);
  assert.match(report, /report\.run_id\s*!==\s*result\.run_id/);
  assert.match(bundle, /bundle\.task_id\s*===\s*task\.task_id/);
  assert.match(bundle, /bundle\.run_id\s*===\s*result\.run_id/);
  assert.match(model, /if \(!report && !bundle\) return null/);
  assert.match(metrics, /\.slice\(0,\s*3\)/, "the compact result must cap visible metrics at three");
  assert.equal((model.match(/\bcta\s*:/g) || []).length, 1, "the model must expose one CTA slot");
  assert.equal((renderer.match(/createElement\(["']button["']\)/g) || []).length, 1, "the card must render at most one CTA button");
  assert.match(renderer, /turn-result-card/);
  assert.match(finalRenderer, /appendTerminalResultCard\(item,[^;]+projection\)/);
  assert.match(finalRenderer, /finalSynthesisFallbackRefs\(item\)/);
  assert.match(returnedIdentity, /report\.report_id === ref\.id/);
  assert.match(returnedIdentity, /report\.report_sha256 === ref\.digest/);
  assert.match(returnedIdentity, /bundle\.bundle_id === ref\.id/);
  assert.match(returnedIdentity, /bundle\.manifest_sha256 === ref\.digest/);
  assert.match(objectOpener, /returnedObjectMatchesRef\(normalized, payload\)/);
  assert.match(download, /returnedObjectMatchesRef\(ref, payload\)/);

  const task = {
    task_id: "task-1",
    contract: { release_gates: {} },
    current_result: {
      status: "completed",
      run_id: "run-1",
      metrics: { clean_test: { accuracy: 0.91 } },
      evaluation_report: {
        task_id: "task-1",
        run_id: "run-1",
        report_id: "evaluation-1",
        report_sha256: "a".repeat(64),
        conclusion: "release_ready",
        release_ready: true,
      },
    },
  };
  const state = { task, evidenceRunId: null, evaluationReport: null, artifactBundles: [], runtimeReady: true };
  const terminalModel = executableTerminalResultModel(app, state);
  const projection = { phase: "result_ready", background: { running: false }, result: { final: { event_id: "final-1" } } };
  const item = {
    kind: "final_synthesis",
    event_id: "final-1",
    status: "completed",
    completion_eligible: true,
    object_refs: [{ type: "evaluation_report", id: "evaluation-1", task_id: "task-1", run_id: "run-1", digest: "a".repeat(64) }],
  };
  assert.ok(terminalModel(item, projection), "an exact report identity renders one terminal result card");
  assert.equal(terminalModel({ ...item, object_refs: [{ ...item.object_refs[0], digest: "b".repeat(64) }] }, projection), null,
    "a stale report digest must fail closed without a result card or CTA");

  state.task = { ...task, current_result: { ...task.current_result, evaluation_report: null } };
  state.evidenceRunId = "run-1";
  state.artifactBundles = [{ task_id: "task-1", run_id: "run-1", bundle_id: "bundle-1", manifest_sha256: "c".repeat(64), release_ready: false, manifest: { files: [] } }];
  const bundleModel = executableTerminalResultModel(app, state);
  const bundleItem = { ...item, object_refs: [{ type: "artifact_bundle", id: "bundle-1", task_id: "task-1", run_id: "run-1", digest: "c".repeat(64) }] };
  assert.ok(bundleModel(bundleItem, projection), "an exact artifact identity renders one terminal result card");
  assert.equal(bundleModel({ ...bundleItem, object_refs: [{ ...bundleItem.object_refs[0], id: "stale-bundle" }] }, projection), null,
    "a stale artifact id must fail closed without a result card or CTA");
});

test("composer attachment chip has truthful pending validating ready and failed recovery states", async () => {
  const { app, html } = await sources();
  const attachmentTag = openingTagForId(html, "composerAttachment");
  assert.match(attachmentTag, /class=["'][^"']*composer-attachment/);
  for (const id of [
    "attachmentName",
    "attachmentMeta",
    "attachmentStatus",
    "removeAttachmentButton",
    "retryAttachmentButton",
  ]) openingTagForId(html, id);

  const stage = topLevelFunction(app, "stageComposerAttachment");
  const render = topLevelFunction(app, "renderComposerAttachment");
  const retry = topLevelFunction(app, "retryComposerAttachment");
  const clear = topLevelFunction(app, "clearComposerAttachment");
  const csvValidation = topLevelFunction(app, "askCsvOptions");
  const retryContinuation = topLevelFunction(app, "retryAttachmentContinuation");
  const upload = topLevelFunction(app, "uploadDataset");
  const attachmentSource = `${stage}\n${render}\n${retry}\n${clear}\n${csvValidation}\n${retryContinuation}\n${upload}`;

  for (const status of ["pending", "validating", "ready", "failed"]) {
    assert.match(attachmentSource, new RegExp(`["']${status}["']`), `attachment state ${status} must be explicit`);
  }
  assert.match(render, /dataset\.state\s*=\s*attachment\.status|dataset\.state\s*=\s*state\.composerAttachment\.status/);
  assert.match(render, /removeAttachmentButton/);
  assert.match(render, /retryAttachmentButton/);
  assert.match(retry, /request_id/);
  assert.match(upload, /headers\[["']x-request-id["']\]\s*=\s*attachment\.request_id/i, "retryable upload work must keep one request identity");

  const failUpload = upload.match(/const failUpload\s*=\s*\([^;]+;/)?.[0] || "";
  assert.match(failUpload, /status:\s*["']failed["']/);
  assert.doesNotMatch(failUpload, /status:\s*["']ready["']|成功/u, "a failed attachment must not be presented as ready or successful");
});

test("HumanCheckpoint is the only writable confirmation surface", async () => {
  const { app, html } = await sources();
  assert.match(app, /function\s+renderHumanCheckpoint\s*\(/);
  assert.match(app, /answerApproval\(|postQuestionAnswers\(/);
  assert.match(app, /const canRespond = pending && interactive && state\.runtimeReady/, "a disconnected runtime must leave even a cached checkpoint read-only");

  const legacyInspectorControls = [
    "approveTrainingPlanButton",
    "rejectTrainingPlanButton",
    "cancelTrainingPlanButton",
    "confirmContractButton",
    "approveRunProposalButton",
  ];
  const centralPolicy = topLevelFunction(app, "syncLegacyConfirmationControls");
  const navigation = topLevelFunction(app, "returnToHumanCheckpoint");
  legacyInspectorControls.forEach((id) => {
    const tag = openingTagForId(html, id);
    assert.match(tag, /data-confirmation-mode=["']checkpoint-only["']/i, `#${id} must declare checkpoint-only ownership`);
    assert.match(centralPolicy, new RegExp(`ui\\.${id}\\.hidden\\s*=\\s*true`), `#${id} must fail closed before any navigation is exposed`);
    assert.match(centralPolicy, new RegExp(`ui\\.${id}\\.disabled\\s*=\\s*true`), `#${id} must start disabled`);
  });

  assert.match(centralPolicy, /hasCanonicalCheckpoint/);
  assert.match(centralPolicy, /训练协调器会在对话中提出 HumanCheckpoint/);
  assert.match(centralPolicy, /当前连接或观察链路不可用，检查点保持只读/);
  assert.match(navigation, /currentHumanCheckpoint\(state\.conversation\)/);
  assert.match(navigation, /querySelectorAll\('\.human-checkpoint\[data-rpc-id\]'\)/);
  assert.match(navigation, /scrollIntoView\(/);
  assert.match(navigation, /\.focus\(/);
  assert.doesNotMatch(navigation, /request\(|answerApproval\(|postQuestionAnswers\(|submitMessage\(/, "Inspector navigation must never write or manufacture a checkpoint");

  for (const handler of ["confirmContract", "approveTrainingPlan", "decideTrainingPlan", "approveProposedTrainingRun"]) {
    assert.doesNotMatch(app, new RegExp(`(?:async\\s+)?function\\s+${handler}\\s*\\(`), `${handler} must not remain callable from the Inspector script`);
  }
  legacyInspectorControls.forEach((id) => {
    assert.match(app, new RegExp(`ui\\.${id}[\\s\\S]{0,420}returnToHumanCheckpoint`), `#${id} must only share the non-writing checkpoint navigation handler`);
  });
});

test("final and idle turns cannot show Stop or an executing label", async () => {
  const idle = InteractionShell.deriveInteractionProjection({
    task: { task_id: "task-1" },
    conversation: { items: [], actions: [] },
  });
  assert.equal(idle.phase, "idle");
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: true, phase: idle.phase, tone: "idle" }), false);

  const terminal = InteractionShell.deriveInteractionProjection({
    task: { task_id: "task-1" },
    conversation: {
      items: [{
        kind: "final_synthesis",
        event_id: "final-1",
        turn_id: "turn-1",
        seq: 1,
        status: "completed",
        completion_eligible: true,
        object_refs: [{ type: "evaluation_report", id: "evaluation-1", task_id: "task-1" }],
      }],
      actions: [],
    },
  });
  assert.equal(terminal.phase, "result_ready");
  assert.equal(InteractionShell.canShowTurnStop({ current: true, can_cancel: true, phase: terminal.phase, tone: "completed" }), false);

  const { app } = await sources();
  const canonical = topLevelFunction(app, "canonicalInteractionPresentation");
  const projected = topLevelFunction(app, "interactionPresentation");
  const completedLabel = canonical.match(/completed\s*:\s*\{([^}]+)\}/)?.[1] || "";
  const resultReadyLabel = projected.match(/result_ready\s*:\s*\{([^}]+)\}/)?.[1] || "";
  assert.ok(completedLabel && resultReadyLabel, "terminal labels must be explicit");
  assert.doesNotMatch(`${completedLabel}\n${resultReadyLabel}`, /正在执行|执行中/u);
});

test("compact coordinator plans and the selected task obey canonical interaction truth", async () => {
  const { app } = await sources();
  const progressModel = new Function(`${topLevelFunction(app, "coordinatorProgressPresentation")}\nreturn coordinatorProgressPresentation;`)();
  const completedPlan = { status: "completed", title: "计划步骤已完成" };
  const cases = [
    ["waiting_question", "needs_confirmation", "计划步骤已处理 · 等待你的回答"],
    ["waiting_approval", "needs_confirmation", "计划步骤已处理 · 等待你的批准"],
    ["agent_working", "running", "计划仍在推进 · AI 正在处理"],
    ["background_working", "running", "计划仍在推进 · 后台操作进行中"],
    ["blocked", "failed", "计划已暂停 · 当前受阻"],
    ["failed", "failed", "计划已停止 · 运行异常"],
    ["stopped", "cancelled", "本轮已停止"],
    ["completed", "completed", "已全部完成"],
  ];
  for (const [phase, tone, hint] of cases) {
    const presentation = progressModel(completedPlan, { phase, tone });
    assert.equal(presentation.hint, hint, `${phase} must override the coordinator item's completed status`);
    assert.equal(presentation.tone, tone);
  }
  assert.equal(progressModel(completedPlan, null).hint, "已全部完成", "historical plans may fall back to their own terminal status");

  const taskListSource = topLevelFunction(app, "taskListStatus");
  const taskListStatus = new Function("interactionPresentation", "workflowStatus", `${taskListSource}\nreturn taskListStatus;`)(
    () => ({ label: "等待你的回答", tone: "needs_confirmation" }),
    () => ({ label: "选择模型来源", tone: "needs_recipe" }),
  );
  assert.deepEqual(taskListStatus({ task_id: "task-1" }, { task_id: "task-1" }), { label: "等待你的回答", tone: "needs_confirmation" });
  assert.deepEqual(taskListStatus({ task_id: "task-2" }, null), { label: "选择模型来源", tone: "needs_recipe" });
  assert.deepEqual(taskListStatus({ task_id: "task-2" }, { task_id: "task-1" }), { label: "选择模型来源", tone: "needs_recipe" }, "a stale conversation must never overwrite another task's sidebar truth");
  assert.match(
    app,
    /if \(stage === "capability_resolution" \|\| stage === "source_discovery"\) \{[\s\S]*?return blocked[\s\S]*?任务当前受阻[\s\S]*?选择模型来源/,
    "a persisted capability blocker must not be mislabeled as ordinary source selection in the sidebar",
  );
});

test("390px composer controls keep at least 44px hit targets", async () => {
  const { css } = await sources();
  assert.match(css, /\.composer\s+textarea\s*\{[^}]*min-height\s*:\s*44px/);
  assert.match(css, /\.menu-button\s*,\s*\.send-button\s*\{[^}]*width\s*:\s*44px[^}]*height\s*:\s*44px/);
  assert.match(css, /\.attachment-button\s*\{[^}]*min-height\s*:\s*44px/);
  assert.match(css, /--control-lg\s*:\s*44px/);
  assert.match(
    css,
    /body \.human-choice-custom\s*\{[^}]*min-height\s*:\s*var\(--control-lg\)\s*!important/,
    "the free-text alternative must remain touch-sized at 390px",
  );
  assert.match(
    css,
    /@media\s*\(max-width\s*:\s*720px\)[\s\S]*?\.composer-attachment\s+\.attachment-retry\s*\{[^}]*min-height\s*:\s*var\(--control-lg\)/,
    "attachment retry must remain touch-sized at 390px",
  );
  assert.match(
    css,
    /@media\s*\(max-width\s*:\s*720px\)[\s\S]*?\.composer-attachment\s+\.attachment-remove\s*\{[^}]*min-width\s*:\s*var\(--control-lg\)[^}]*min-height\s*:\s*var\(--control-lg\)/,
    "attachment remove must remain touch-sized at 390px",
  );
});
