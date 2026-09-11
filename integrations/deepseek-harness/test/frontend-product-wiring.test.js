import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "../../../model_harness/web");

async function sources() {
  const [html, legacyCss, visualCss, app] = await Promise.all([
    readFile(join(web, "index.html"), "utf8"),
    readFile(join(web, "styles.css"), "utf8"),
    readFile(join(web, "visual-system.css"), "utf8"),
    readFile(join(web, "app.js"), "utf8"),
  ]);
  return { html, css: `${legacyCss}\n${visualCss}`, legacyCss, visualCss, app };
}

test("gateway failures stay human-readable and never render raw HTML", async () => {
  const { app } = await sources();
  const requestContract = app.slice(
    app.indexOf("function structuredErrorMessage"),
    app.indexOf("function clear(element)"),
  );
  assert.match(requestContract, /status === 429/);
  assert.match(requestContract, /\[502, 503, 504\]\.includes\(status\)/);
  assert.match(requestContract, /服务返回了异常页面（HTTP \$\{status\}）/);
  assert.match(requestContract, /error\.payload = htmlPayload \? null : value/);
  assert.match(requestContract, /暂时无法连接训练工作台服务/);
  assert.doesNotMatch(requestContract, /new Error\(structuredErrorMessage\(value\)\)/);

  const makeResponse = ({ status, type, body }) => ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => name.toLowerCase() === "content-type" ? type : "" },
    text: async () => body,
  });
  const responses = [
    makeResponse({ status: 503, type: "text/html", body: "<html><h1>503 Service Temporarily Unavailable</h1></html>" }),
    makeResponse({ status: 503, type: "application/json", body: "<html><h1>mislabelled gateway error</h1></html>" }),
    makeResponse({ status: 200, type: "application/json", body: "<html>not json</html>" }),
  ];
  const context = {
    fetch: async () => responses.shift(),
    console,
  };
  vm.runInNewContext(`${requestContract}\nglobalThis.__request = request;`, context);

  for (const expected of ["训练工作台服务暂时不可用", "训练工作台服务暂时不可用", "返回的数据暂时无法读取"]) {
    await assert.rejects(
      context.__request("/tasks"),
      (error) => {
        assert.match(error.message, new RegExp(expected));
        assert.equal(error.payload, null);
        assert.doesNotMatch(error.message, /<html|nginx|Service Temporarily Unavailable/i);
        return true;
      },
    );
  }
});

test("request timeout covers stalled response bodies, not only response headers", async () => {
  const { app } = await sources();
  const contract = app.slice(app.indexOf("function structuredErrorMessage"), app.indexOf("function clear(element)"));
  const context = {
    AbortController,
    window: { setTimeout, clearTimeout },
    fetch: async (_url, { signal }) => ({
      ok: true,
      headers: { get: () => "application/json" },
      text: () => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })))),
    }),
  };
  vm.runInNewContext(`${contract}\nglobalThis.__request = request;`, context);
  await assert.rejects(context.__request("/runtime", { timeoutMs: 10 }), /响应超时/);
});

test("new-task retry keeps creation identity and only replaces a terminal message request", async () => {
  const { app } = await sources();
  const contract = app.slice(app.indexOf("function beginTaskCreationSubmission"), app.indexOf("async function postQueuedConversationMessage"));
  let sequence = 0;
  const state = { messageSubmission: null };
  const context = { state, createConversationRequestId: () => `request-${++sequence}` };
  vm.runInNewContext(`${contract}\nglobalThis.__begin = beginTaskCreationSubmission;`, context);
  const original = context.__begin("test goal");
  original.status = "failed";
  const replay = context.__begin("test goal");
  assert.equal(replay.create_request_id, "request-1");
  assert.equal(replay.request_id, "request-2");
  replay.status = "failed";
  replay.new_request_required = true;
  const recovered = context.__begin("test goal");
  assert.equal(recovered.create_request_id, "request-1");
  assert.equal(recovered.request_id, "request-3");
  assert.notEqual(context.__begin("changed goal").create_request_id, "request-1");
});

test("L3 Hugging Face controls are wired to immutable, approved, verified asset APIs", async () => {
  const { html, app } = await sources();
  for (const id of [
    "hfSearchForm", "hfTokenInput", "hfSearchResults", "hfModelCard",
    "hfModelCommit", "hfCompatibilityChecks", "hfAttachButton",
    "modelAssetVerifyButton", "modelAssetVerifyStatus",
  ]) assert.match(html, new RegExp(`id="${id}"`));

  assert.match(app, /\/model-assets\/huggingface\/capability/);
  assert.match(app, /\/model-assets\/huggingface\/search\?/);
  assert.match(app, /\/model-assets\/huggingface\/card\?/);
  assert.match(app, /\/model-assets\/huggingface`/);
  assert.match(app, /\/model-assets\/current\/verify/);
  assert.match(app, /approval_confirmed:\s*true/);
  assert.match(app, /\^\[0-9a-f\]\{40\}\$/);
  assert.match(app, /"X-HF-Token": token/);
  assert.doesNotMatch(app, /localStorage[^\n;]*hfTokenInput/i);
  assert.match(html, /不会自动推进任务或创建 Run/);
});

test("L4 evaluation and raw sample use task-owned APIs while Artifact Bundle mutations stay Agent-gated", async () => {
  const { html, app } = await sources();
  for (const id of [
    "evidenceDimensions", "candidateList", "failureSampleList", "runHistoryList",
    "sampleTrialInput", "sampleTrialRunButton", "sampleInferenceList",
    "buildArtifactBundleButton", "artifactBundleList",
  ]) assert.match(html, new RegExp(`id="${id}"`));

  assert.match(app, /\/evaluation-report/);
  assert.match(app, /\/sample-inferences/);
  assert.match(app, /\/inference-inputs/);
  assert.match(app, /\/artifact-bundles/);
  assert.match(app, /"X-Filename": encodeURIComponent\(filename\)/);
  assert.match(app, /"X-Sample-Type": sampleType/);
  assert.match(app, /async function continueWithInferenceInput\(inferenceInput/);
  assert.match(app, /inferenceInputQuestionCheckpoint\(checkpoint\)/);
  assert.match(app, /await postQuestionAnswers\(checkpoint, answers\)/);
  assert.match(app, /训练协调器会先请求一次明确授权，再交给评测专家试跑/);
  const sampleTrial = app.slice(app.indexOf("async function runSampleTrial()"), app.indexOf("async function buildArtifactBundle()"));
  assert.match(sampleTrial, /await stageInferenceInput/);
  assert.doesNotMatch(sampleTrial, /\/sample-inferences`, \{ method: "POST"/);
  assert.match(app, /async function buildArtifactBundle\(\)/);
  assert.match(app, /await submitMessage\(`请为当前训练运行/);
  assert.match(app, /async function requestArtifactBundleDownload\(result, bundle\)/);
  assert.match(app, /不要复用构建授权/);
  const approvalPresentation = app.slice(app.indexOf("function approvalPresentation"), app.indexOf("function appendApprovalScope"));
  assert.ok(approvalPresentation.indexOf("download_artifact_bundle") < approvalPresentation.indexOf("build_artifact_bundle"), "download approval must be classified before the generic artifact-bundle build copy");
  assert.match(approvalPresentation, /不会复用构建授权，也不会覆盖已有文件/);
  assert.match(approvalPresentation, /批准这次新样本试跑/);
  assert.match(approvalPresentation, /批准本次试跑/);
  assert.match(approvalPresentation, /暂不试跑/);
  assert.match(approvalPresentation, /不会重新训练或修改模型/);
  assert.doesNotMatch(app, /request\(`\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/runs\/\$\{encodeURIComponent\(runId\)\}\/artifact-bundles`, \{ method: "POST"/);
  assert.doesNotMatch(app, /link\.href = `\/tasks\/.*artifact-bundles.*download/);
  assert.match(app, /raw_data_included === false/);
  assert.match(app, /capability_unavailable/);
});

test("Inspector contract review is read-only while DSH HumanCheckpoint keeps the writable approval path", async () => {
  const { app, html } = await sources();
  const renderContract = app.slice(app.indexOf("function renderContract"), app.indexOf("function releaseVerdict"));
  const policy = app.slice(app.indexOf("function syncLegacyConfirmationControls"), app.indexOf("function returnToHumanCheckpoint"));
  const navigation = app.slice(app.indexOf("function returnToHumanCheckpoint"), app.indexOf("const BACKGROUND_TRAINING_STATUSES"));
  assert.match(html, /id="confirmations" data-confirmation-mode="read-only"/);
  assert.equal((html.match(/data-confirm="[^"]+" disabled/g) || []).length, 3);
  assert.match(renderContract, /input\.disabled = true/);
  assert.match(policy, /contractAwaitingConfirmation/);
  assert.match(policy, /runAwaitingConfirmation/);
  assert.match(policy, /hasCanonicalCheckpoint/);
  assert.match(navigation, /currentHumanCheckpoint\(state\.conversation\)/);
  assert.doesNotMatch(navigation, /request\(|postQuestionAnswers\(|answerApproval\(/);
  assert.doesNotMatch(app, /async function confirmContract\(\)/);
  assert.doesNotMatch(app, /workspace-confirm:/);
  assert.match(app, /conversationTransportPath\(state\.selectedTaskId, "approvals", item\.rpc_id\)/);
});

test("regression contract gates explain raw target units and their human-reviewed baseline", async () => {
  const { css, app } = await sources();
  const renderContract = app.slice(app.indexOf("function renderContract"), app.indexOf("function releaseVerdict"));
  assert.match(renderContract, /const regressionGates = "clean_test_mae_max" in gates \|\| "clean_test_rmse_max" in gates/);
  assert.match(renderContract, /const regressionBasis = regressionGates \? contract\.release_gate_basis : null/);
  assert.match(renderContract, /regressionBasis\?\.target_column \|\| task\.dataset_report\?\.target_column/);
  assert.match(renderContract, /label\.startsWith\("MAE"\) \|\| label\.startsWith\("RMSE"\)/);
  assert.match(renderContract, /「\$\{targetColumn\}」原始单位/);
  assert.match(renderContract, /required_improvement_fraction/);
  assert.match(renderContract, /系统按当前数据的常数均值基线建议\$\{improvementText\}，仍需你确认/);
  assert.doesNotMatch(renderContract, /standardized|标准化单位/);
  assert.match(css, /\.gate-grid \.gate-basis\{grid-column:1\/-1/);
});

test("v0.9 model-source flow searches official catalogs and requires two explicit confirmations", async () => {
  const { html, css, app } = await sources();
  for (const id of [
    "modelSourceCard", "modelSourceSearchForm", "modelSourceReferenceForm",
    "modelSourceCandidates", "modelSourcePending", "pendingResolvedCommit",
    "bindModelSourceButton", "modelSourceBlocker", "modelSourceFileList",
    "modelSourceHfToken", "modelSourceGithubToken",
  ]) assert.match(html, new RegExp(`id="${id}"`));

  assert.match(app, /\/model-sources\/providers/);
  assert.match(app, /\/model-source-searches/);
  assert.match(app, /\/model-source-selections/);
  assert.match(app, /\/model-source-resolutions/);
  assert.match(app, /approval_confirmed:\s*true/);
  assert.match(app, /expected_resolved_commit:\s*resolution\.resolved_commit/);
  assert.match(app, /response\.binding_attempt\?\.attempt\?\.attempt_id/);
  assert.match(app, /完成前不会显示为已绑定/);
  assert.doesNotMatch(app, /response\.binding\.repository/);
  assert.match(app, /task\.repository_analysis_attempt \|\| task\.model_binding_attempt/);
  assert.match(app, /if \(!binding && analysisAttempt\)/);
  assert.match(app, /repositoryAnalysisCard\.hidden = !binding && !attempt/);
  assert.match(app, /const analysisBlocked = analysis\.status !== "complete" \|\| analysisBlockers\.length > 0/);
  assert.match(app, /存在需要处理的风险或证据阻断/);
  assert.match(app, /label: "绑定与分析记录"/);
  assert.match(app, /failure\.code \|\| "unknown_failure"/);
  assert.match(app, /function retryFailedModelSourceBinding\(\)/);
  assert.match(app, /旧失败证据不会被覆盖/);
  assert.match(app, /if \(retryFailedModelSourceBinding\(\)\) return/);
  assert.match(app, /搜索结果只是候选，不等于已经适配本机/);
  assert.match(app, /不会执行第三方代码/);
  assert.match(app, /task\.model_binding/);
  assert.doesNotMatch(app, /localStorage[^\n;]*(modelSourceHfToken|modelSourceGithubToken)/i);
  assert.match(css, /\.source-fact-list[^}]*overflow-wrap:anywhere/);
  assert.match(css, /\.source-files>div\{max-height:220px/);
  assert.match(css, /\.source-candidate button\{min-height:44px\}/);
});

test("R3 keeps source search compact in dialogue and complete in the on-demand workspace", async () => {
  const { html, css, app } = await sources();
  for (const id of [
    "modelSourceCheckpointCard", "modelSourceCheckpointFacts", "modelSourceCheckpointCandidates",
    "viewAllModelSourceCandidatesButton", "modelSourceCard", "modelSourceCandidates",
  ]) assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1, `${id} must be unique`);

  assert.match(app, /modelSourceCardForCheckpoint\(task\)/);
  assert.match(app, /hasCurrentModelSourceSearch\(task\) \? ui\.modelSourceCheckpointCard : ui\.modelSourceCard/);
  assert.match(app, /state\.modelSourceCandidates\.slice\(0, 3\)\.forEach/);
  assert.match(app, /state\.modelSourceCandidates\.forEach\(\(candidate\) =>/);
  assert.match(app, /button\.dataset\.searchId = search\.search_id/);
  assert.match(app, /article\.dataset\.searchId = selectionContext\.searchId/);
  assert.match(app, /search_id: searchId, candidate_id: candidate\.candidate_id/);
  assert.match(app, /searchId !== state\.modelSourceSearch\?\.search_id/);
  assert.match(app, /state\.modelSourceCandidateRenderKey/);
  assert.match(app, /key === state\.modelSourceCandidateRenderKey && ui\.modelSourceCandidates\.childElementCount === state\.modelSourceCandidates\.length/);
  assert.match(app, /key === state\.modelSourceCheckpointRenderKey && ui\.modelSourceCheckpointCandidates\.childElementCount/);
  assert.match(app, /card !== state\.checkpointCard \|\| card\.parentNode !== ui\.agentCheckpointBody/);
  assert.match(app, /renderModelSource\(state\.task\); syncAgentCheckpoint\(state\.task\)/);
  assert.match(app, /sourceStage && !state\.modelSourceSearchInFlight/);
  assert.match(app, /state\.modelSourceSearchInFlight = true/);
  assert.match(app, /function openAllModelSourceCandidates\(\) \{ openInspector\("plan"\); ui\.modelSourceDiscovery\.open = true/);
  assert.match(app, /viewAllModelSourceCandidatesButton\.addEventListener\("click", openAllModelSourceCandidates\)/);
  assert.match(app, /ui\.modelSourceCandidates\.focus\(\{ preventScroll: true \}\)/);
  assert.match(app, /候选只来自官方目录元数据，尚未下载、执行或验证训练适配性/);
  assert.doesNotMatch(app, /候选已适配/);
  assert.match(css, /\.source-candidate-compact-list\{[^}]*grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /\.source-search-checkpoint-facts,\.source-candidate-compact-list\{grid-template-columns:1fr\}/);
  assert.match(css, /\.source-search-checkpoint-card \.source-view-all\{width:100%;min-height:44px\}/);
});

test("mobile inspector remains a full-screen sheet with 44px action targets", async () => {
  const { css } = await sources();
  assert.match(css, /@media\(max-width:720px\)[\s\S]*?\.inspector\{position:fixed;inset:0;[^}]*height:100dvh/);
  assert.match(css, /\.menu-button\{display:none;flex:none;width:32px/);
  assert.match(css, /\.menu-button,\.send-button\{width:44px;height:44px\}/);
  assert.match(css, /\.inspector button\{min-height:44px\}/);
  assert.match(css, /\.asset-discovery>summary[^}]*min-height:44px/);
  assert.match(css, /\.sample-trial-actions button[^}]*min-height:44px/);
});

test("desktop primary training actions expose 44px interaction targets", async () => {
  const { css } = await sources();
  assert.match(css, /\.new-task-button\{min-height:44px\}/);
  assert.match(css, /\.composer textarea\{min-height:44px\}/);
  assert.match(css, /\.send-button\{width:44px;height:44px\}/);
});

test("terminal run recovery navigates to the canonical conversation checkpoint without mutating runs", async () => {
  const { html, app } = await sources();
  assert.match(html, /id="retryRunButton"[^>]*hidden/);
  assert.match(html, /id="retryRunButton"[^>]*>回到对话确认恢复<\/button>/);
  assert.match(app, /TERMINAL_RETRY_STATUSES = new Set\(\["failed", "cancelled", "interrupted"\]\)/);
  assert.match(app, /retry_training_run/);
  const recovery = app.slice(app.indexOf("function navigateToTrainingRecoveryCheckpoint"), app.indexOf("async function answerApproval"));
  assert.match(recovery, /function navigateToTrainingRecoveryCheckpoint\(\)/);
  assert.match(recovery, /currentHumanCheckpoint\(state\.conversation\)/);
  assert.match(recovery, /\.human-checkpoint/);
  assert.match(recovery, /只有随后出现的 HumanCheckpoint 才能授权创建新 Run/);
  assert.doesNotMatch(recovery, /request\(|\/runs|openSimpleDialog|submitMessage|answerApproval/);
  assert.match(app, /TERMINAL_RETRY_STATUSES\.has\(result\.status\) && task\.control\?\.next_action\?\.id === "retry_training_run"/);
  assert.match(app, /ui\.retryRunButton\.addEventListener\("click", navigateToTrainingRecoveryCheckpoint\)/);
  assert.doesNotMatch(app, /function approveTrainingRecovery\(|addEventListener\("click", approveTrainingRecovery\)/);
  assert.doesNotMatch(app, /state\.task\.status\s*=\s*"running"/);
});

test("conversation-native shell keeps dialogue primary and reveals only task-owned evidence on demand", async () => {
  const { html, css, app } = await sources();
  const interaction = await readFile(join(web, "interaction-shell.js"), "utf8");
  assert.match(html, /<title>Specialist Model Studio · 专业模型智能工作台<\/title>/);
  assert.match(html, /<strong>Specialist Model Studio<\/strong>/);
  for (const id of [
    "workspaceToggleButton", "agentCheckpoint", "agentCheckpointStage",
    "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointBody",
    "agentCheckpointActions", "agentCheckpointWorkspaceButton", "workspaceExperience",
    "workspaceTeamList", "workspaceResultList", "workspaceTechnicalButton", "workspaceTruthNote",
  ]) assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1, `${id} must be unique`);

  assert.match(html, /id="workspaceToggleButton"[^>]*aria-label="打开任务证据"/);
  const retiredIds = [
    ["task", "ControlPanel"], ["task", "Plan"], ["stage", "List"],
    ["runEvent", "List"], ["pending", "Zone"],
  ].map((parts) => parts.join(""));
  for (const retired of retiredIds) {
    assert.doesNotMatch(html, new RegExp(`id="${retired}"`));
    assert.doesNotMatch(app, new RegExp(retired));
    assert.doesNotMatch(css, new RegExp(retired));
  }
  assert.match(html, /想训练一个什么模型？/);
  assert.match(html, /id="inspectorSheetTitle">方案与证据</);
  assert.match(html, /data-context="plan"[^>]*>方案</);
  assert.match(html, /data-context="data" hidden>数据</);
  assert.match(html, /data-context="run" hidden>运行</);
  assert.match(html, /data-context="evaluation" hidden>评测</);
  assert.match(html, /data-context="artifacts" hidden>产物</);
  assert.match(app, /checkpointHomes = new Map\(\)/);
  assert.match(app, /function workflowStatus\(task, conversation = null\)/);
  assert.match(app, /function conversationHasActiveWork\(conversation\)/);
  assert.match(app, /function conversationAgentResponseRunning\(conversation\)/);
  assert.match(app, /function conversationHasBackgroundTraining\(conversation\)/);
  assert.match(app, /if \(conversationAgentResponseRunning\(conversation\)\) return \{ label: "AI 正在处理"/);
  assert.match(app, /if \(conversationHasBackgroundTraining\(conversation\)\) return \{ label: "后台操作进行中"/);
  assert.match(app, /RUNNING_STATUSES\.has\(task\.current_result\?\.status\)\) return \{ label: "后台操作进行中"/);
  assert.match(app, /\(conversation && state\.conversationStreamDegraded\) \|\| conversation\?\.projection_health/);
  assert.match(app, /function syncTaskHeader\(task, conversation = state\.conversation, projection = null\)/);
  assert.match(app, /function taskListStatus\(task, conversation = null\)/);
  assert.match(app, /const taskOwnedConversation = conversation\?\.task_id === task\?\.task_id \? conversation : null/);
  assert.match(app, /return taskOwnedConversation \? interactionPresentation\(task, taskOwnedConversation\) : workflowStatus\(task, null\)/);
  assert.match(app, /const taskConversation = task\.task_id === state\.selectedTaskId \? state\.conversation : null; const workflow = taskListStatus\(task, taskConversation\)/);
  assert.match(app, /function syncSelectedTaskListStatus\(conversation = state\.conversation, projection = null\)/);
  assert.match(app, /if \(state\.task\) syncTaskHeader\(state\.task, conversation, projection\)/);
  assert.match(app, /if \(state\.task && !draftConversation\) \{ syncTaskSpecCheckpointOwnership\(conversation\); syncLegacyConfirmationControls\(state\.task, conversation\); syncSelectedTaskListStatus\(conversation, projection\); \}/);
  assert.match(app, /stage === "environment_lock"\) return \{ label: blocked \? "训练环境阻断"/);
  assert.match(app, /label: "固定模型来源记录"/);
  assert.match(app, /time\.textContent = formatRelativeTime\(task\.updated_at_utc\)/);
  assert.match(app, /ui\.taskEyebrow\.textContent = workflow\.label/);
  assert.doesNotMatch(app, /stageLabel\(stageKey\(task\)\)\} · \$\{workflow\.label/);
  assert.match(app, /ui\.agentCheckpointBody\.append\(card\)/);
  assert.match(app, /function checkpointIsInline\(card\)/);
  assert.match(app, /function checkpointWorkspaceContext\(task, card = checkpointCardFor\(task\)\)/);
  assert.match(app, /ui\.agentCheckpointActions\.hidden = inline/);
  assert.match(app, /function availableWorkspaceContexts\(task\)/);
  assert.match(app, /function syncWorkspaceTabs\(task\)/);
  assert.match(app, /--visible-context-count/);
  assert.doesNotMatch(app, /dockedWorkspaceMedia\.matches\) \{ openInspector\(context\); revealCurrentWorkspaceObject\(task\); \}/);
  assert.match(app, /function revealCurrentWorkspaceObject\(task = state\.task\)/);
  assert.match(app, /card\.scrollIntoView\(\{ block: "start", behavior: "smooth" \}\)/);
  assert.match(app, /stage === "repository_analysis"\) return task\.model_binding \? ui\.repositoryAnalysisCard : sourceCard/);
  assert.match(app, /stage === "training_plan"\) return ui\.trainingPlanCard/);
  assert.match(app, /const blockedAnalysis = Boolean\(analysis\) && analysis\.status !== "complete"/);
  assert.match(app, /仓库静态分析仍有未解决风险，不能生成训练计划/);
  assert.doesNotMatch(app, /cloneNode\(/);
  assert.match(app, /ui\.inspector\.dataset\.open = "true"/);
  assert.match(app, /ui\.inspector\.dataset\.open = "false"/);
  assert.match(app, /workspaceToggleButton\.setAttribute\("aria-expanded", "true"\)/);
  assert.match(app, /workspaceToggleButton\.setAttribute\("aria-label", "关闭任务证据"\)/);
  assert.match(app, /window\.requestAnimationFrame\(\(\) => ui\.closeInspectorButton\.focus\(\)\)/);
  assert.match(app, /const isolated = overlayWorkspace\(\) && ui\.inspector\.dataset\.open === "true"/);
  assert.match(app, /ui\.sidebar\.inert = isolated; ui\.conversationMain\.inert = isolated; ui\.mobileViewNav\.inert = isolated/);
  assert.match(app, /ui\.inspector\.setAttribute\("aria-modal", "true"\)/);
  assert.match(app, /event\.key === "Escape"[^\n]*closeInspector\(\{ userInitiated: true \}\)/);
  assert.match(app, /event\.key !== "Tab"/);
  assert.match(app, /active === first \|\| !ui\.inspector\.contains\(active\)/);
  assert.match(app, /active === last \|\| !ui\.inspector\.contains\(active\)/);
  assert.match(app, /const restoreTarget = opener\?\.isConnected[^\n]+ui\.workspaceToggleButton/);
  assert.match(app, /inspectorMedia\.addEventListener\("change"/);
  assert.match(css, /--sidebar-width:\s*264px/);
  assert.match(css, /body \.app-shell\s*\{[^}]*grid-template-columns:\s*var\(--sidebar-width\) minmax\(0, 1fr\)/);
  assert.match(css, /\.context-tabs\{grid-template-columns:repeat\(var\(--visible-context-count,1\),minmax\(0,1fr\)\)/);
  assert.match(app, /dockedWorkspaceMedia = window\.matchMedia\("\(min-width:1280px\)"\)/);
  assert.match(css, /@media \(min-width: 1280px\)[\s\S]*body\[data-workspace="open"\] \.app-shell\s*\{[^}]*grid-template-columns:\s*var\(--sidebar-width\) minmax\(560px, 1fr\) var\(--workspace-width\)/);
  assert.match(css, /@media\(min-width:1280px\)[\s\S]*\.inspector\{display:none;[^}]*grid-column:auto[^}]*\}/);
  assert.match(css, /@media\(min-width:1280px\)[\s\S]*body\[data-workspace="open"\] \.inspector\{display:block;grid-column:3;/);
  assert.match(css, /@media\(min-width:1280px\)[\s\S]*\.inspector-scrim:not\(\[hidden\]\)\{display:none!important\}/);
  assert.match(css, /\.inspector\[data-open="true"\]\{[^}]*visibility:visible[^}]*pointer-events:auto[^}]*transform:translateX\(0\)/);
  assert.match(css, /@media\(max-width:720px\)[\s\S]*?\.inspector\{width:100%;z-index:42\}/);
  assert.match(css, /@media\(max-width:720px\)[\s\S]*body\[data-workspace="open"\] \.mobile-view-nav\{display:none\}/);
  for (const asset of ["styles.css", "visual-system.css", "app.js", "conversation-view.js", "interaction-shell.js"]) {
    assert.match(html, new RegExp(`${asset.replace(".", "\\.")}\\?v=2\\.4\\.10-pc-rc`));
  }
  assert.match(app, /function renderAgentSurfaceState\(conversation, projection\)/);
  assert.doesNotMatch(app, /开始 Agent 会话/);
  assert.match(app, /任务已保存，消息尚未发给 AI/);
  assert.match(app, /重新发送后，回复和执行过程才会出现在这里/);
  assert.match(app, /action\.textContent = "发送任务目标"/);
  assert.match(app, /ready \? "AI 已连接"/);
  assert.match(app, /if \(state\.runtimeReady && hasSession\) return/);
  assert.doesNotMatch(app, /当前由训练协调器处理/);
  assert.doesNotMatch(app, /Agent 协作已连接/);
  assert.doesNotMatch(app, /个专家已参与本轮/);
  assert.doesNotMatch(html, /专家已参与本轮/);
  assert.match(interaction, /item\.lineage_verified === true/);
  assert.match(interaction, /typeof item\.delegation_id === "string" && item\.delegation_id/);
  assert.match(interaction, /taskOwned\(item, taskId\)/);
  assert.match(app, /function createAiTurnContainer\(turn, projection, conversation, actions\)/);
  assert.match(app, /function canonicalInteractionPresentation\(conversation = state\.conversation\)/);
  assert.match(app, /value\.schema_version !== "1\.0"/);
  assert.match(app, /waiting_question: \{ label: "等待你的回答", tone: "needs_confirmation" \}/);
  assert.match(app, /interaction_projection: data\.interaction_projection \|\| state\.conversation\.interaction_projection \|\| null/);
  assert.match(interaction, /section\.className = "ai-turn"/);
  assert.match(interaction, /content\.className = "ai-turn-content"/);
  assert.match(app, /InteractionShell\.createAiTurnFrame\(document, ui\.messageList/);
  assert.match(app, /InteractionShell\.canShowTurnStop\(presentation\)/);
  assert.match(app, /function syncAiTurnElapsedLabels\(root = document\)/);
  assert.match(app, /label\.dataset\.elapsedLive = String\(presentation\.current/);
  assert.match(app, /window\.setInterval\(\(\) => syncAiTurnElapsedLabels\(\), 1000\)/);
  assert.doesNotMatch(app, /已按你的选择暂停/);
  assert.match(app, /if \(item\.kind === "message" && item\.role === "user"\) \{ renderConversationItem\(item, turnTarget\("user"\)\); return; \}/);
  assert.match(app, /renderActionTimeline\(actions, delegations, \{ interactionState:[^\n]*expertCount: turnVerifiedRoles\.size, recoveredFailures, target: turnTarget\("assistant"\) \}\)/);
  assert.match(app, /work_items: mergeConversationStreamEntries\(state\.conversation\.work_items, data\.work_items\)/);
  assert.match(app, /当前没有已验证专家委派；不会用角色配置冒充多智能体协作/);
  assert.match(app, /下载完成：新文件已写入，并通过大小与 SHA-256 校验/);
  assert.match(app, /传输已开始，尚未确认本地文件保存完成/);
  assert.match(app, /action\?\.tool_name === "model_harness_download_artifact_bundle"/);
  assert.match(app, /function workspaceEvaluationOutcome\(task\)/);
  assert.match(app, /协调器已回复，后台任务仍在运行/);
  assert.match(app, /InteractionShell\.deriveEvaluationOutcome/);
  assert.match(app, /评测已完成，但没有同时提供明确基线与已选候选的可比验证指标，因此不展示数值对比/);
  assert.match(app, /\[\["publish", "发布", outcome\.decision\.publish\], \["rollback", "回滚", outcome\.decision\.rollback\], \["optimize", "继续优化", outcome\.decision\.optimize\]\]/);
  assert.match(app, /指标只来自当前 Run 的真实评测；发布、回滚或继续优化仍需人工确认/);
  assert.match(css, /\.workspace-comparison-flow/);
  assert.match(css, /\.workspace-decision-gate/);
  assert.match(app, /if \(!dockedWorkspaceMedia\.matches \|\| !autoOpen\)/);
  assert.match(app, /openInspector\(workspaceContextForProjection\(projection\), \{ presentation: projection\.workspace\?\.presentation \|\| "experience", auto: true \}\)/);
  assert.match(app, /ui\.workspaceTechnicalButton\.addEventListener\("click"/);
  assert.match(css, /\.inspector\[data-presentation="experience"\] #inspectorContent\{display:none\}/);
  assert.match(css, /\.inspector\[data-presentation="technical"\] \.workspace-experience\{display:none\}/);
  assert.doesNotMatch(app, /任务已创建并交给训练协调器。它会先读取 TrainingTask/);
  assert.match(css, /body \.send-button\s*\{[^}]*width:\s*var\(--control-lg\)[^}]*height:\s*var\(--control-lg\)[^}]*border-radius:\s*50%/);
  assert.match(app, /function renderCoordinatorPlan\(item, target = ui\.messageList\)/);
  assert.match(app, /item\.kind === "coordinator_plan" \? \{ \.\.\.item, compact: true, currentInteraction: current, truthConflict, failedActionTitle:/);
  assert.match(app, /const latestPlanIndex = items\.reduce\(\(latest, item, index\) => item\.kind === "coordinator_plan" \? index : latest, -1\)/);
  assert.match(app, /if \(item\.kind === "coordinator_plan" && itemIndex !== latestPlanIndex\) return/);
  assert.match(app, /const truthConflict = item\.kind === "coordinator_plan" && Boolean\(failedAction\)/);
  assert.match(app, /details\.dataset\.truthConflict = String\(Boolean\(item\.truthConflict\)\)/);
  assert.match(app, /"状态说明已降级"/);
  assert.match(app, /"不作为状态"/);
  assert.match(app, /function renderCoordinatorProgress\(item, target = ui\.messageList\)/);
  const compactProgress = app.slice(app.indexOf("function renderCoordinatorProgress"), app.indexOf("function teamEventTitle"));
  assert.match(app, /function coordinatorProgressPresentation\(item, canonical = null\)/);
  assert.match(app, /currentInteraction: current/);
  assert.match(compactProgress, /item\.currentInteraction \? canonicalInteractionPresentation\(state\.conversation\) : null/);
  assert.match(compactProgress, /coordinatorProgressPresentation\(item, canonical\)/);
  assert.doesNotMatch(compactProgress, /item\.status === "completed"/);
  assert.match(app, /function renderActionTimeline\(actions, delegations = \[\], \{ interactionState = "idle", expertCount = 0, recoveredFailures = new Set\(\), target = ui\.messageList \} = \{\}\)/);
  assert.match(app, /const waitingForHuman = interactionState === "waiting_for_human"/);
  assert.match(app, /waitingForHuman \? "本轮已经做了什么"/);
  assert.match(app, /function actionTimelineGlance\(actions, waitingForHuman, working, recoveredFailures = new Set\(\)\)/);
  assert.match(app, /function isWaitingForAnswerAction\(action, waitingForHuman = false\)/);
  assert.match(app, /action\.tool_name === "ask_user_question"/);
  assert.match(app, /checkpoint.call_id === action.call_id/);
  assert.match(app, /result\.dataset\.state = displayStatus/);
  assert.match(app, /waitingForAnswer \|\| displayStatus === "suspended" \? actionStatusLabel\(action, \{ waitingForHuman \}\)/);
  assert.match(app, /waitingForAnswer \? "等待你的决定" : hasDeclined/);
  assert.match(app, /function isUserDeclinedAction\(action\)/);
  assert.match(app, /action\?\.error\?\.code === "user_rejected"/);
  assert.match(app, /displayStatus === "declined"/);
  assert.match(app, /你选择暂不执行，系统没有运行这项操作/);
  assert.match(app, /actionTimelineDisclosure: new Map\(\)/);
  assert.match(app, /state\.actionTimelineDisclosure\.set\(disclosureKey, section\.open\)/);
  assert.match(app, /function hydrateActionTimelineResults\(section, actions\)/);
  assert.match(app, /details\.open = depth === 0 \|\| running \|\| waitingForAnswer \|\| hasFailure/);
  assert.match(app, /const rootAgent = \{ id: "root-agent"/);
  assert.match(app, /group\.binding\?\.target_agent_id/);
  assert.match(app, /group\.root \? "训练协调器" : roleLabel\(summaryRole\)/);
  assert.match(css, /\.coordinator-progress\{[^}]*overflow:hidden/);
  assert.match(app, /function renderTeamActivity\(item, target = ui\.messageList\)/);
  assert.match(app, /function renderFinalSynthesis\(item, target = ui\.messageList\)/);
  assert.match(app, /function renderTypedTruthNotice\(item, target = ui\.messageList\)/);
  assert.match(app, /\["blocker", "warning", "observation_degraded", "failed"\]/);
  assert.match(app, /if \(item\.kind === "coordinator_note"\) return renderCoordinatorNote\(item, target\)/);
  assert.match(app, /function renderCoordinatorNote\(item, target = ui\.messageList\)/);
  assert.doesNotMatch(app, /truth\.textContent = "过程说明"/);
  assert.match(app, /Answer visibility is independent from evidence-backed training completion/);
  assert.match(app, /function showTransientNotice\(message, tone = "ok", durationMs = 6_000\)/);
  assert.match(app, /state\.noticeDismissTimer = window\.setTimeout/);
  assert.match(app, /showTransientNotice\(created\.created === false \? "对话已恢复，AI 正在继续处理。" : "对话已开始，AI 正在理解你的需求。"/);
  assert.match(app, /等待你的回答：\$\{active\.title \|\| active\.questions\?\.\[0\]\?\.header/);
  assert.match(app, /function renderRichText\(container, text\)/);
  assert.match(app, /function markdownTableCells\(line\)/);
  assert.match(app, /strongMarkers\.length % 2 === 1/);
  assert.match(app, /container\.append\(document\.createTextNode/);
  assert.match(app, /renderRichText\(copy, item\.text/);
  assert.doesNotMatch(app, /container\.innerHTML\s*=/);
  assert.match(css, /\.rich-table-wrap\{[^}]*overflow-x:auto/);
  assert.match(app, /row\.dataset\.messageType = "final_synthesis"/);
  assert.match(app, /function renderUnknownEvent\(item, target = ui\.messageList\)/);
  assert.doesNotMatch(app, /function compactConversationItems\(items\)/);
});

test("runtime failure stops conversation instead of impersonating an Agent with local workflow", async () => {
  const { html, css, app } = await sources();
  const submit = app.slice(app.indexOf("async function submitMessage"), app.indexOf("function deriveTaskName"));
  assert.match(html, /id="composerMode"[^>]*data-state="checking"/);
  assert.match(html, /id="composerModeLabel">正在连接 AI</);
  assert.match(html, /aria-label="向 Specialist Model Studio 描述模型任务"/);
  assert.doesNotMatch(html, /class="composer-mode"[^>]*>[^<]*训练 Agent/);
  assert.match(app, /function renderRuntimeMode\(mode\)/);
  assert.match(app, /function compatibleAgentRuntime\(agent\)/);
  assert.match(app, /function agentProviderReady\(agent\)/);
  assert.match(app, /agent\?\.provider\?\.ready === true && agent\.provider\.active === true && agent\.provider\.configured === true/);
  assert.match(app, /state\.runtimeReady = transportCompatible && providerReady/);
  assert.match(app, /state\.runtimeIssue = "provider"/);
  assert.match(app, /agent\.real_agent === true && agent\.implementation === "dsh_native_subagents"/);
  assert.match(app, /agent\.conversation_projector_revision === "3\.3" && agent\.synthesis_verdict_version === "1\.0" && agent\.conversation_action_schema_version === "1\.0" && agent\.task_truth_source === "TrainingTask"/);
  assert.match(app, /\["working", "waiting_for_human", "cancelling", "idle", "terminal"\]/);
  assert.match(app, /AI 服务版本不兼容/);
  assert.match(app, /AI 服务未连接/);
  assert.match(app, /AI 未连接 · 对话已暂停/);
  assert.match(app, /renderRuntimeMode\(runtimeDisplayMode\(\)\)/);
  assert.match(app, /模型服务尚未配置。请先在本机为 Specialist Model Studio 配置 DeepSeek API Key，然后重新启动；在此之前不会创建训练任务/);
  assert.match(app, /providerMissing \? "请先在本机配置模型服务，再开始训练任务"/);
  assert.doesNotMatch(app, /DEEPSEEK_API_KEY/);
  assert.match(app, /error\.status === 503\)[^\n]*renderRuntimeMode\("local"\)/);
  assert.match(app, /ui\.messageInput\.disabled = false; ui\.sendButton\.disabled = !ready/);
  assert.match(app, /request\("\/runtime", \{ timeoutMs: 8_000 \}\)/);
  assert.match(app, /request\("\/agent\/runtime", \{ timeoutMs: 6_000 \}\)/);
  assert.match(app, /state\.runtimeRetryTimer = window\.setTimeout\(\(\) => loadRuntime\(\), delay\)/);
  assert.match(app, /state\.selectedTaskId \? "继续询问或补充下一步要求…"/);
  assert.match(app, /没有创建或修改任务，也没有启动固定流程替代对话/);
  assert.match(app, /AI 服务未连接，对话已暂停/);
  assert.doesNotMatch(app, /if \(remoteConversation\.session_id\) \{\s*state\.runtimeReady = true/);
  assert.doesNotMatch(app, /本地流程模式 · 训练操作仍可用/);
  assert.match(css, /\.composer-mode\[data-state="local"\]/);
  assert.match(css, /\.composer-mode:not\(\[data-state="local"\]\)\{display:none\}/);
  assert.match(css, /\.composer-wrap\[data-runtime="unavailable"\]/);
  assert.ok(submit.indexOf("if (!state.runtimeReady)") < submit.indexOf('request("/conversations"'), "Runtime guard must run before conversation creation");
});

test("fresh empty workspace enters the shared home composer state", async () => {
  const { html, app } = await sources();
  assert.match(html, /id="homeComposerSlot"/);
  assert.match(html, /id="homeBoundary"/);
  assert.match(html, /AI 会和你一起澄清目标、查找开源模型，并在每个关键决定前停下来确认/);
  assert.doesNotMatch(html, /匹配开源模型、准备数据、训练和评测/);
  assert.match(app, /function enterHomeState\(\{ focusComposer = true \} = \{\}\)/);
  assert.match(app, /ui\.homeComposerSlot\.append\(ui\.composerWrap\)/);
  assert.match(app, /renderRuntimeMode\(runtimeDisplayMode\(\)\); syncComposerDelivery\(null\)/);
  assert.match(app, /function openNewTask\(\)[\s\S]*?enterHomeState\(\);/);
  assert.match(app, /if \(!state\.selectedTaskId\) enterHomeState\(\{ focusComposer: false \}\)/);
  assert.match(app, /if \(!requested\) \{ enterHomeState\(\{ focusComposer: false \}\); return; \}/);
  assert.match(app, /没有替你打开其他任务/);
  assert.doesNotMatch(app, /requested : state\.tasks\[0\]\?\.task_id/);
});

test("explicitly starting a new task clears a stale home draft without discarding the current task draft", async () => {
  const { app } = await sources();
  const openNewTask = app.slice(app.indexOf("function openNewTask"), app.indexOf("async function selectTask"));
  const saveCurrentIndex = openNewTask.indexOf("saveDraft()");
  const clearHomeIndex = openNewTask.indexOf("clearDraft(null)");
  const clearComposerIndex = openNewTask.indexOf('ui.messageInput.value = ""');
  const resizeIndex = openNewTask.indexOf("resizeComposer()", clearComposerIndex);
  const enterHomeIndex = openNewTask.indexOf("enterHomeState()");
  assert.ok(saveCurrentIndex >= 0 && saveCurrentIndex < clearHomeIndex,
    "the selected task draft must be saved before the dedicated home draft is cleared");
  assert.ok(clearHomeIndex < clearComposerIndex && clearComposerIndex < resizeIndex && resizeIndex < enterHomeIndex,
    "a stale __new__ draft and visible prompt must be cleared before the home composer restores state");
});

test("creating a conversation transfers the submitted prompt once without manufacturing a task", async () => {
  const { app } = await sources();
  const select = app.slice(app.indexOf("async function selectConversation"), app.indexOf("async function refreshSelected"));
  const submit = app.slice(app.indexOf("async function submitMessage"), app.indexOf("function deriveTaskName"));
  const createStart = submit.indexOf('request("/conversations"');
  const createEnd = submit.indexOf("const checkpoint = currentHumanCheckpoint", createStart);
  const createBranch = submit.slice(createStart, createEnd);
  assert.match(select, /async function selectConversation\(conversationId, \{ saveCurrentDraft = true, record = null \} = \{\}\)/);
  assert.match(select, /if \(saveCurrentDraft\) saveDraft\(\)/);
  assert.match(createBranch, /initial_message: text/);
  assert.match(createBranch, /create_request_id: creation\.create_request_id/);
  assert.match(createBranch, /message_request_id: creation\.request_id/);
  assert.match(createBranch, /created\?\.submission\?\.accepted !== true/);
  const clearDraftIndex = createBranch.indexOf("clearDraft(null)");
  const clearComposerIndex = createBranch.indexOf('ui.messageInput.value = ""');
  const selectIndex = createBranch.indexOf("await selectConversation(conversationId, { saveCurrentDraft: false, record: created.conversation })");
  const acceptedIndex = createBranch.indexOf("created?.submission?.accepted !== true");
  assert.ok(acceptedIndex >= 0 && acceptedIndex < clearDraftIndex && clearDraftIndex < clearComposerIndex && clearComposerIndex < selectIndex,
    "the first AI message must be accepted before clearing the home draft or hydrating the conversation");
  assert.doesNotMatch(createBranch, /postQueuedConversationMessage\(/,
    "new conversation creation must not depend on a second browser request for the first message");
  assert.doesNotMatch(createBranch, /state\.tasks\s*=|created\.task/,
    "an unbound conversation must not be inserted into the training-task list");
});

test("unbound intake keeps one conversation identity until the Agent promotes a real task", async () => {
  const { app } = await sources();
  const refresh = app.slice(app.indexOf("async function refreshSelected"), app.indexOf("function conversationStreamEntryKey"));
  const presentation = app.slice(app.indexOf("function interactionPresentation"), app.indexOf("function taskListStatus"));
  const draftGuard = app.slice(app.indexOf("function isConversationDraft"), app.indexOf("function conversationDraftTask"));
  assert.match(app, /conversationRecord: null/);
  assert.match(app, /record_type: "conversation_draft"/);
  assert.match(app, /history\.replaceState\(null, "", `\$\{location\.pathname\}\?conversation=\$\{encodeURIComponent\(conversationId\)\}`\)/);
  assert.match(refresh, /request\(`\/conversations\/\$\{encodeURIComponent\(taskId\)\}`\)/);
  assert.match(refresh, /if \(!owner\.task\)/);
  assert.match(refresh, /history\.replaceState\(null, "", `\$\{location\.pathname\}\?task=\$\{encodeURIComponent\(taskId\)\}`\)/);
  assert.match(refresh, /state\.tasks = \[owner\.task, \.\.\.state\.tasks\.filter/);
  assert.match(presentation, /label: "AI 正在回应"/);
  assert.match(presentation, /label: "等待你的消息"/);
  assert.ok(presentation.indexOf('return { label: "等待你的消息"') < presentation.indexOf('result_ready: { label: "本轮结果已就绪"'),
    "conversation-draft presentation must return before task result labels are considered");
  assert.match(draftGuard, /const ownerId = task\?\.conversation_id \|\| task\?\.task_id/);
  assert.match(draftGuard, /ownerId === conversationId/,
    "the selected intake record must not leak its state into unrelated sidebar tasks");
  assert.match(app, /if \(isConversationDraft\(state\.conversationRecord, task\)\) return \[\]/);
});

test("runtime and family-catalog failures preserve honest product boundaries", async () => {
  const { app } = await sources();
  assert.match(app, /request\("\/runtime", \{ timeoutMs: 8_000 \}\)/);
  assert.match(app, /Promise\.allSettled\(\[loadRuntime\(\), loadHfCapability\(\), loadModelSourceProviders\(\), loadTaskSpecFamilies\(\), loadTasks\(\{ selectFromUrl: true \}\)\]\)/);
  assert.match(app, /任务列表暂时无法读取/);
  assert.match(app, /byom_execution_available === true/);
  assert.match(app, /确认后进入可验证的训练与评测/);
  assert.match(app, /确认方案后才执行/);
  assert.match(app, /taskSpecFamiliesError = error\.message/);
  assert.match(app, /const loaded = await loadTaskSpecFamilies\(\)/);
  assert.match(app, /模型类型目录加载失败/);
});

test("persisted source evidence survives refresh without impersonating live agent events", async () => {
  const { app } = await sources();
  assert.match(app, /request\(`\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/model-source-searches`\)/);
  assert.match(app, /item\.base_spec_revision === response\.task\.current_spec_revision/);
  assert.match(app, /const referencedSearch = state\.activeObjectRef\?\.type === "model_source_search"/);
  assert.match(app, /state\.modelSourceSearch = referencedSearch \|\| \(failedSearch \? null : latestSearch\)/);
  assert.match(app, /state\.modelSourceCandidates = \[\.\.\.\(state\.modelSourceSearch\?\.candidates \|\| \[\]\)\]/);
  assert.match(app, /state\.modelSourceCandidates\.length\) showNotice\("官方目录没有返回候选[^\n]+else hideNotice\(\)/);
  assert.match(app, /ui\.capabilityState\.textContent = "模型已绑定"/);
  assert.match(app, /ui\.capabilityState\.textContent = analysisStatus === "failed" \? "分析失败" : "分析已取消"/);
  assert.match(app, /else if \(analysis\) \{ const analysisBlocked = analysis\.status !== "complete" \|\| analysisBlockers\.length > 0/);
  assert.doesNotMatch(app, /const SPEC_FAMILIES/);
  assert.match(app, /request\("\/task-spec\/families"\)/);
  assert.match(app, /if \(currentCandidate && !candidates\.some\(\(item\) => item\.family === currentCandidate\.family\)\) candidates\.unshift\(currentCandidate\)/);
  assert.match(app, /allProvidersFailed \? "failed" : "completed_empty"/);
  assert.match(app, /const systemOnlyNote = \/\^用户通过产品界面/);
  assert.match(app, /function taskEvidenceLedger\(task\)/);
  assert.match(app, /source: "persisted_task_projection"/);
  assert.match(app, /官方模型目录搜索记录/);
  assert.match(app, /不可变训练计划记录/);
  assert.match(app, /本机资源探测记录/);
  assert.match(app, /ConversationView\.buildConversationView\(\{ remoteConversation, localItems: local\.items, ledgerItems: taskEvidenceLedger\(task\) \}\)/);
  assert.match(app, /由持久化任务状态生成，不代表智能体发言/);
  assert.doesNotMatch(app, /function conversationWithEvidence\(/);
  assert.doesNotMatch(app, /真实工具调用已完成/);
});

test("source, plan, and resource recovery controls fail closed across task changes", async () => {
  const { app } = await sources();
  assert.match(app, /String\(item\.created_at \|\| ""\) > bindingCreatedAt/);
  assert.match(app, /ui\.manualEntrypointInput\.value = ""; ui\.baseImageDigestInput\.value = ""/);
  assert.match(app, /ui\.searchHfProvider\.disabled = !canSearch \|\| !hfAvailable/);
  assert.match(app, /ui\.searchGithubProvider\.disabled = !canSearch \|\| !githubAvailable/);
  assert.match(app, /state\.modelSourceSearch = null; state\.modelSourceCandidates = \[\]/);
  assert.match(app, /training-plans\/\$\{encodeURIComponent\(parent\.training_plan_revision_id\)\}\/revisions/);
  assert.match(app, /expected_parent_sha256: parent\.plan_sha256/);
  assert.match(app, /base_spec_revision: state\.task\.current_spec_revision/);
  assert.match(app, /\^sha256:\[0-9a-f\]\{64\}\$/);
  assert.match(app, /用此建议生成新 revision/);
});

test("task understanding keeps explicit quick replies but routes all free text through the Agent", async () => {
  const { html, css, app } = await sources();
  const submit = app.slice(app.indexOf("async function submitMessage"), app.indexOf("function deriveTaskName"));
  assert.match(html, /id="taskSpecQuickReplies"[^>]*hidden/);
  assert.match(html, /id="editTaskSpecButton"[^>]*>高级编辑</);
  assert.match(app, /const allCandidates = decision\.candidates \|\| \[\]/);
  assert.match(app, /const customCandidate = allCandidates\.find\(\(item\) => item\.family === "custom"\)/);
  assert.match(app, /if \(customCandidate && !candidates\.some\(\(item\) => item\.family === "custom"\)\) candidates\.push\(customCandidate\)/);
  assert.match(app, /prefix: "就是这个："/);
  assert.match(app, /switchOutput\.textContent = showAlternatives \? "收起其他输出" : "换一种输出"/);
  assert.match(app, /describe\.textContent = "我自己描述"/);
  assert.match(app, /reparse\.textContent = "重新理解当前描述"/);
  assert.match(app, /function reparseTaskSpec\(button\)/);
  assert.match(app, /business_goal: spec\.business_goal, reparse: true, user_note: "用户请求系统使用当前规则重新理解已保存描述"/);
  assert.match(app, /历史版本和原始描述仍然保留/);
  assert.match(app, /base_revision: spec\.revision, selected_family: candidate\.family/);
  assert.match(app, /\.\.\.\(confirm \? \{ confirm: true \} : \{\}\)/);
  assert.doesNotMatch(app, /business_goal: nextGoal, user_note: `用户补充：\$\{text\}`/);
  assert.ok(submit.indexOf("if (!state.runtimeReady)") < submit.indexOf('if (!state.selectedTaskId)'), "Runtime guard must own every free-text turn");
  assert.doesNotMatch(submit, /\/spec`/);
  assert.match(submit, /await postQueuedConversationMessage\(taskId, text\)/);
  assert.match(app, /\/spec\/revisions`/);
  assert.match(app, /label: `需求版本 v\$\{spec\.revision\} 等待确认`/);
  assert.match(app, /const confirmedOutput = selectedCandidate\?\.output/);
  assert.doesNotMatch(app, /\$\{capability\.target_kind \|\| "待确认输出"\}/);
  assert.match(app, /error\.status === 409\) await refreshSelected\(\{ force: true \}\)/);
  assert.match(app, /if \(stage === "task_understanding"\) return ui\.taskSpecCard/);
  assert.match(css, /\.task-spec-quick-replies\{display:grid/);
  assert.match(css, /\.task-spec-choice\.featured/);
  assert.match(css, /\.task-spec-reparse/);
});

test("Recipe sample attachment stays reachable while build and registration remain Agent-owned", async () => {
  const { app } = await sources();
  assert.match(app, /next_action\?\.id === "stage_recipe_samples"/);
  assert.match(app, /ui\.recipeSampleInput\.click\(\)/);
  assert.match(app, /\/staged-assets`/);
  assert.doesNotMatch(app, /function startRecipeBuild\(/);
  assert.doesNotMatch(app, /function approveRecipeRegistration\(/);
  assert.doesNotMatch(app, /function performNextAction\(/);
});

test("live runtime checkpoints own the conversation and terminal team groups stay folded", async () => {
  const { app } = await sources();
  assert.match(app, /hasRuntimeCheckpoint/);
  assert.match(app, /state\.conversation = null/);
  assert.match(app, /state\.conversation\?\.pending/);
  assert.match(app, /ui\.dialogTitle\.textContent = item\.questions\?\.\[0\]\?\.header/);
  assert.match(app, /if \(hasRuntimeCheckpoint\) ui\.agentCheckpoint\.hidden = true/);
  assert.match(app, /const active = events\.some\(\(event\) => \["active", "queued", "running", "waiting"\]\.includes\(event\.status\)\)/);
  assert.match(app, /const failed = failedEvents\.length > 0/);
  assert.match(app, /需要处理 · 部分步骤失败/);
  assert.match(app, /已完成 · \$\{events\.length\} 项证据/);
  assert.match(app, /details\.open = active;/);
  assert.doesNotMatch(app, /details\.open = active \|\| failed/);
});

test("observation degradation stays visible and participates in conversation rerenders", async () => {
  const { css, app } = await sources();
  assert.match(app, /function conversationObservationKey\(conversation\)/);
  assert.match(app, /projector_revision: remote\.conversation_projector_revision \|\| remote\.projector_revision \|\| runtimeAgent\.conversation_projector_revision/);
  assert.match(app, /item_projector_revisions: itemProjectorRevisions/);
  assert.match(app, /verdict: \{[\s\S]*?version: remote\.synthesis_verdict_version/);
  assert.match(app, /projection_errors: conversation\.projection_errors/);
  assert.match(app, /projection_health: conversation\.projection_health/);
  assert.match(app, /stream_health: remote\.stream_health/);
  assert.match(app, /const observation = conversationObservationKey\(conversation\)/);
  assert.match(app, /active: conversation\.active_event\?\.action_id \|\| conversation\.active_event\?\.event_id \|\| conversation\.active_event\?\.training_run_id/);
  assert.match(app, /function renderProjectionHealth\(conversation\)/);
  assert.match(app, /projection_health\?\.status !== "observation_degraded"\) return/);
  assert.match(app, /观察链路已降级，当前结果不能视为完整成功/);
  assert.match(app, /可能遗漏待审批或待回答的问题/);
  assert.match(app, /重新连接并刷新/);
  assert.match(app, /renderProjectionHealth\(conversation\); renderAgentSurfaceState\(conversation, projection\)/);
  assert.match(css, /\.observation-health\{[^}]*border:1px solid rgba\(184,117,20,\.26\)[^}]*background:#fffcf6/);
  assert.match(css, /\.observation-health>span\{[^}]*color:var\(--amber\)[^}]*background:var\(--amber-bg\)/);
  assert.match(css, /@media\(max-width:720px\)[\s\S]*?\.agent-surface-state,\.observation-health\{width:100%/);
});

test("Agent object references use the three-state Inspector and exact task-owned endpoints", async () => {
  const { html, css, app } = await sources();
  assert.match(app, /function openObjectRef\(ref\)/);
  assert.match(app, /function objectRefEndpoint\(ref\)/);
  assert.match(app, /model-source-searches\/\$\{id\}/);
  assert.match(app, /model-binding-attempts\/\$\{id\}/);
  assert.match(app, /training-plans\/\$\{id\}/);
  assert.match(app, /runs\/\$\{runId\}\/artifact-bundles\/\$\{id\}/);
  assert.match(app, /normalized\.task_id !== state\.selectedTaskId/);
  assert.match(app, /openInspector\("object-viewer", \{ objectRef: normalized \}\)/);
  assert.match(app, /没有回退到通用方案或当前对象/);
  assert.match(app, /function openEventResultRef\(ref\)/);
  assert.match(app, /conversation\/events\/\$\{encodeURIComponent\(eventRef\.id\)\}\?projector_revision=/);
  assert.match(app, /button\.textContent = "技术详情"/);
  assert.match(app, /state\.inspectorMode = mode/);
  assert.match(app, /state\.inspectorMode = "closed"/);
  assert.doesNotMatch(app, /openInspector\(ref\.workspace_context \|\| ref\.context \|\| "plan"\)/);
  assert.match(html, /id="objectViewer" hidden/);
  assert.match(css, /\.object-viewer\{display:grid/);
  assert.doesNotMatch(app, /startsWith\("probe_"\)/);
});

test("diagnostic and training capability remain separate for ASR", async () => {
  const { html, app } = await sources();
  const conversation = await readFile(join(web, "conversation-view.js"), "utf8");
  assert.match(html, /id="diagnosticCapabilityState"/);
  assert.match(html, /id="trainingCapabilityState"/);
  assert.match(html, /id="capabilityRecovery"/);
  assert.match(html, /id="capabilityNonAction"/);
  assert.match(conversation, /selected_family === "asr"/);
  assert.match(conversation, /unavailable_no_verified_recipe/);
  assert.match(conversation, /语音转文字可继续静态诊断，但当前没有已验证训练 Recipe/);
  assert.match(conversation, /trained_with_evaluation/);
  assert.match(conversation, /decision === "fit_with_revision"/);
  assert.doesNotMatch(app, /feasibility\.decision && feasibility\.decision !== "fit"/);
  assert.match(app, /不下载权重、不执行第三方源码、不安装依赖、不创建训练 Run/);
});

test("Agent questions require an explicit human choice", async () => {
  const { css, app } = await sources();
  assert.doesNotMatch(app, /optionIndex === 0\) input\.checked = true/);
  assert.match(app, /const RECOMMENDATION_SUFFIX = \/\\s\*\(\?:\\\(\(\?:recommended\|推荐\)\\\)\|（\(\?:recommended\|推荐\)）\)\\s\*\$\/iu/);
  assert.match(app, /button\.dataset\.recommended = String\(presentation\.recommended\)/);
  assert.doesNotMatch(app, /index === 0 && \/\\\(Recommended\\\)/);
  assert.match(app, /请先回答训练协调器的问题/);
  assert.match(app, /actions\.classList\.add\("human-choice-list"\)/);
  assert.match(app, /button\.className = "human-choice"/);
  assert.match(app, /postQuestionAnswers\(item, \[\{ id: question\.id, selected: \[option\.label\] \}\]\)/);
  assert.match(app, /custom\.textContent = "填写其他答案"/);
  assert.doesNotMatch(app, /answer\.textContent = "回答问题"/);
  assert.match(css, /\.decision-actions\.human-choice-list\{display:grid/);
  assert.match(css, /\.human-choice\{[^}]*min-height:70px/);
});

test("AI-human mode keeps one decision foregrounded and accepts natural-language answers", async () => {
  const { html, css, app } = await sources();
  assert.match(html, /请先帮我判断是否需要训练/);
  assert.match(app, /function isPendingHumanCheckpoint\(item\)/);
  assert.match(app, /checkpoint\?\.kind === "question"\) return \{ label: "等待你的回答"/);
  assert.match(app, /checkpoint\?\.kind === "approval"\) return \{ label: "等待你的批准"/);
  assert.match(app, /workflowStatus\(task, conversation = null\)/);
  assert.match(app, /syncTaskHeader\(state\.task, conversation, projection\)/);
  assert.match(app, /checkpoint_rpc_id: submission\.checkpoint_rpc_id/);
  assert.match(app, /继续提问或补充想法；发送后暂缓当前问题/);
  assert.match(app, /answer\.addEventListener\("click", \(\) => openQuestionDialog\(item\)\)/);
  assert.match(app, /不会批准执行或代填答案/);
  assert.match(app, /发送不会批准执行/);
  assert.match(app, /conversation\?\.interaction_state === "waiting_for_human"/);
  assert.match(app, /conversationHasActiveWork\(conversation\)/);
  assert.match(app, /function syncTaskSpecCheckpointOwnership\(conversation = state\.conversation\)/);
  assert.match(app, /currentHumanCheckpoint\(conversation\)\?\.rpc_id/);
  assert.match(app, /ui\.taskSpecCard\.hidden = true/);
  assert.match(css, /\.task-spec-card\[data-write-owner="dsh-checkpoint"\]\{display:none!important\}/);
  assert.match(app, /const agentResponseRunning = conversationAgentResponseRunning\(conversation\)/);
  assert.match(app, /const currentAiTurn = ui\.messageList\.querySelector\('\.ai-turn\[data-current="true"\]'\)/);
  assert.match(app, /const fallbackWorkingSurface = !currentAiTurn && \(agentResponseRunning \|\| backgroundTrainingRunning \|\| Boolean\(optimistic\) \|\| serverCancelling\)/);
  assert.match(app, /ui\.cancelAgentButton\.hidden = Boolean\(currentAiTurn\) \|\| \(conversation\.can_cancel_agent !== true && !backgroundRun\)/);
  assert.match(app, /function renderCheckpointHistory\(items, target = ui\.messageList\)/);
  assert.match(app, /document\.createElement\("details"\); section\.className = "action-timeline"/);
  assert.match(css, /\.action-timeline>summary\{/);
  assert.match(css, /\.checkpoint-history\{width:calc/);
  assert.doesNotMatch(app, /renderPendingCheckpointTaskTruth/);
  assert.doesNotMatch(app, /任务同时保留阻断记录|任务同时保留失败状态/);
  assert.match(app, /renderWorkspaceExperience\(state\.task, conversation, projection\)/);
});

test("expected human clarification gates do not impersonate risk evidence", async () => {
  const interaction = await readFile(join(web, "interaction-shell.js"), "utf8");
  assert.match(interaction, /const EXPECTED_QUESTION_CONTROL_GATES = new Set/);
  assert.match(interaction, /"task_spec_ambiguous"/);
  assert.match(interaction, /function expectedHumanControlGate\(blocker, checkpoint\)/);
  assert.match(interaction, /blocker\?\.active !== false && !expectedHumanControlGate\(blocker, checkpoint\)/);
  assert.match(interaction, /const turnBlocker = currentTurnBlocker\(currentItems\)/);
  assert.match(interaction, /blocker: turnBlocker/);
});

test("live Agent and cancellation truth outrank persisted blockers", async () => {
  const { app } = await sources();
  const interaction = await readFile(join(web, "interaction-shell.js"), "utf8");
  const pendingIndex = interaction.indexOf('reasonCode = "pending_question"');
  const cancellingIndex = interaction.indexOf('reasonCode = "cancellation_pending"');
  const agentIndex = interaction.indexOf('reasonCode = "agent_response_running"');
  const backgroundIndex = interaction.indexOf('reasonCode = "observed_active_background_work"', cancellingIndex);
  const failureIndex = interaction.indexOf('reasonCode = turnFailure?.item?.kind === "turn_error"');
  assert.ok(cancellingIndex >= 0 && cancellingIndex < pendingIndex);
  assert.ok(pendingIndex < agentIndex && agentIndex < backgroundIndex && backgroundIndex < failureIndex);
  assert.match(interaction, /task_blocker: observedTaskBlocker/);
  assert.match(app, /else if \(agentResponseRunning && !conversation\.active_event\) ui\.agentWorkingLabel\.textContent = "AI 正在处理"/);
  assert.match(app, /backgroundCancellationPending\(conversation\) \? "正在停止" : conversationAgentResponseRunning/);
});

test("CSV data checkpoints upload first and resume the same Agent question without exposing host paths", async () => {
  const { css, app } = await sources();
  const checkpointRenderer = app.slice(app.indexOf("function renderHumanCheckpoint"), app.indexOf("function renderTurnTerminal"));
  const upload = app.slice(app.indexOf("function datasetCoordinatorContinuation"), app.indexOf("function activateContext"));
  const uploadRecognition = app.slice(app.indexOf("const DATA_UPLOAD_QUESTION_IDS"), app.indexOf("function syncTaskSpecCheckpointOwnership"));
  const datasetRenderer = app.slice(app.indexOf("function renderDataset"), app.indexOf("function gateEntries"));
  assert.match(app, /function dataUploadQuestionCheckpoint\(item\)/);
  assert.match(uploadRecognition, /new Set\(\["data_upload", "dataset_upload", "csv_upload", "data_path", "dataset_id"\]\)/);
  assert.match(uploadRecognition, /\[\.\.\.DATA_UPLOAD_QUESTION_IDS\]\.some\(\(id\) => ids\.has\(id\)\)/);
  assert.doesNotMatch(uploadRecognition, /\[\.\.\.DATA_UPLOAD_QUESTION_IDS, "target_column"\]/);
  assert.doesNotMatch(uploadRecognition, /question\?\.(?:question|header|summary)|item\.(?:title|summary)|includes\([^)]*(?:upload|上传)/);
  assert.match(checkpointRenderer, /选择数据文件，系统会先识别字段/);
  assert.match(checkpointRenderer, /"选择 CSV 文件" : "选择 CSV 或 ZIP 文件"/);
  assert.match(checkpointRenderer, /ui\.datasetInput\.value = ""; ui\.datasetInput\.click\(\)/);
  assert.match(checkpointRenderer, /协调器只会收到导入后的数据集编号和你选择的预测列/);
  assert.doesNotMatch(checkpointRenderer, /绝对路径|相对于工作区|\/Users\//);
  assert.match(app, /const receiptDatasetId = response\?\.dataset_upload\?\.dataset_id \|\| null/);
  assert.match(app, /const datasetId = receiptDatasetId \|\| response\?\.task\?\.dataset_id \|\| null/);
  assert.match(app, /function datasetUploadReceiptMatches\(response, taskId, requestId\)/);
  assert.match(app, /dataset-upload-receipts/);
  assert.match(app, /function dataUploadCheckpointAnswers\(item, datasetId, targetColumn\)/);
  assert.match(app, /isDatasetUploadQuestionId\(question\.id\)/);
  assert.match(app, /question\.id === "target_column"/);
  assert.match(app, /postQuestionAnswers\(uploadCheckpoint, answers, \{ taskId \}\)/);
  assert.match(app, /数据已真实导入并完成体检（数据集 \$\{shortId\(datasetId\)\}），但协调器问题续接失败/);
  assert.match(app, /请不要重复上传；刷新任务后从当前问题继续/);
  const continuation = upload.slice(0, upload.indexOf("async function uploadDataset"));
  assert.match(continuation, /预测目标是「\$\{readableTarget\}」/);
  assert.match(continuation, /请先检查数据并给我一版容易理解的训练方案/);
  assert.match(continuation, /在我确认方案和启动前，不要开始训练/);
  assert.doesNotMatch(continuation, /dataset_id|文件名|本机路径|数据合同|JSON\.stringify/);
  assert.match(upload, /if \(state\.runtimeReady && !activeCheckpoint && datasetId\)/);
  assert.match(upload, /postQueuedConversationMessage\(taskId, datasetCoordinatorContinuation\(options\.targetColumn\)\)/);
  assert.match(upload, /确认前不会启动训练/);
  assert.doesNotMatch(continuation, /file\.?name|file\.?path|\/Users\//);
  assert.doesNotMatch(upload, /\/runs|startTraining|confirmContract\(/);
  assert.ok(upload.indexOf("if (uploadCheckpoint)") < upload.indexOf("if (state.runtimeReady && !activeCheckpoint && datasetId)"),
    "an explicit upload question must be resumed before generic coordinator continuation");
  assert.ok(upload.indexOf('status !== "resolved"') < upload.indexOf('/dataset`'),
    "dataset import and continuation must stay behind confirmed task understanding");
  assert.match(upload, /status !== "resolved" && !uploadCheckpoint/);
  assert.match(datasetRenderer, /const uploadCheckpoint = dataUploadQuestionCheckpoint\(currentHumanCheckpoint\(state\.conversation\)\)/);
  assert.match(datasetRenderer, /const blocked = !uploadCheckpoint && \(task\.status === "running" \|\| task\.status === "needs_recipe" \|\| !specReady\)/);
  assert.match(datasetRenderer, /ui\.datasetButton\.disabled = recipeSamplesNeeded \? false : blocked; ui\.inspectorDatasetButton\.disabled = blocked/);
  const contractRenderer = app.slice(app.indexOf("function renderContract"), app.indexOf("function releaseVerdict"));
  const legacyConfirmationPolicy = app.slice(app.indexOf("function syncLegacyConfirmationControls"), app.indexOf("function returnToHumanCheckpoint"));
  assert.match(contractRenderer, /input\.disabled = true/);
  assert.match(legacyConfirmationPolicy, /ui\.confirmContractButton\.hidden = true; ui\.confirmContractButton\.disabled = true/);
  assert.match(legacyConfirmationPolicy, /ui\.approveRunProposalButton\.hidden = true; ui\.approveRunProposalButton\.disabled = true/);
  assert.match(legacyConfirmationPolicy, /const hasCanonicalCheckpoint = Boolean\(checkpoint\?\.rpc_id && isPendingHumanCheckpoint\(checkpoint\)\)/);
  assert.match(app, /answer\.addEventListener\("click", \(\) => openQuestionDialog\(item\)\)/);
  assert.match(css, /\.data-upload-actions\{display:grid/);
  assert.match(css, /\.data-upload-actions \.checkpoint-upload-button\{/);
  assert.match(app, /function parseDelimitedHeader\(line, delimiter\)/);
  assert.match(app, /async function inspectCsvSchema\(file\)/);
  assert.match(app, /file\.slice\(0, 64 \* 1024\)\.text\(\)/);
  assert.match(app, /const candidates = \[",", ";", "\\t", "\|"\]/);
  assert.match(app, /\/csv-target-recommendation/);
  assert.match(app, /json: \{ columns: selected\.columns \}/);
  assert.match(app, /recommendation\.status === "recommended"/);
  assert.doesNotMatch(app, /selected\.columns\.at\(-1\)/);
  assert.match(app, /input\.checked = column === schema\.recommended/);
  assert.match(app, /确认并导入体检/);
  assert.match(css, /\.csv-schema-overview/);
  assert.match(css, /\.csv-column-choices/);
  assert.match(app, /function humanizeCoordinatorText\(/);
  assert.doesNotMatch(app, /function appendCoordinatorNextAction\(/);
  assert.match(app, /choose\.textContent = state\.task\?\.recipe_id === "tabular-regression" \? "选择 CSV 文件" : "选择 CSV 或 ZIP 文件"/);
});

test("conversation progress uses task-owned SSE with visible five-second fallback", async () => {
  const { html, css, app } = await sources();
  assert.match(app, /new EventSource\(`\$\{conversationTransportPath\(taskId, "stream"\)\}/);
  assert.match(app, /draft \? `\/conversations\/\$\{id\}\/conversation\/stream` : `\/tasks\/\$\{id\}\/conversation\/stream`/);
  for (const eventName of ["snapshot", "delta", "state", "heartbeat", "error"]) {
    assert.match(app, new RegExp(`addEventListener\\("${eventName}"`));
  }
  assert.match(app, /acceptConversationStreamEnvelope/);
  assert.match(app, /function isCanonicalConversationSnapshot\(value\)/);
  assert.match(app, /value\.session_id === null \|\| typeof value\.session_id === "string"/);
  assert.match(app, /value\.action_schema_version !== "1\.0"/);
  assert.match(app, /value\.synthesis_verdict_version !== "1\.0"/);
  assert.match(app, /value\.execution_running, value\.can_cancel_agent/);
  assert.match(app, /agent_response_running: data\.agent_response_running === true/);
  assert.match(app, /training_runs: data\.training_runs \|\| \[\]/);
  assert.match(app, /background_actions: data\.background_actions \|\| \[\]/);
  assert.match(app, /data\.cursor !== state\.conversationStreamCursor \+ 1/);
  assert.match(app, /state\.selectedTaskId === taskId && state\.selectionToken === token/);
  assert.match(app, /function attemptConversationFallbackRecovery\(taskId, token\)/);
  assert.match(app, /window\.setInterval\(\(\) => \{ void attemptConversationFallbackRecovery\(taskId, token\); \}, 5000\)/);
  assert.match(app, /if \(!state\.runtimeReady\) await loadRuntime\(\)/);
  assert.match(app, /const reconciled = await reconcileConversation\(taskId, token\)/);
  assert.match(app, /startConversationStream\(taskId, token\)/);
  assert.match(app, /void reconcileConversation\(taskId, token\)/);
  assert.match(app, /reconcileBeforeStreamRecovery/);
  assert.match(app, /client_stream_degraded: state\.conversationStreamDegraded/);
  assert.match(app, /window\.setInterval\(\(\) => refreshSelected\(\{ includeConversation: false \}\), 6000\)/);
  assert.match(app, /stopConversationStream\(\)/);
  assert.doesNotMatch(app, /data\.conversation\.session_id/);
  assert.doesNotMatch(app, /setInterval\(\(\) => refreshSelected\(\), 1400\)/);
  assert.doesNotMatch(css, /animation:pulse|@keyframes pulse/);
  assert.match(html, /id="agentWorking" hidden><i aria-hidden="true">AI<\/i>/);
});

test("paired backend actions are the primary visible execution timeline", async () => {
  const { css, app } = await sources();
  const interaction = await readFile(join(web, "interaction-shell.js"), "utf8");
  const conversation = await readFile(join(web, "conversation-view.js"), "utf8");
  assert.match(app, /const resolvedCheckpoints = \[\]/);
  assert.match(app, /projection\.turns\.forEach\(\(turn\) => renderConversationTurn\(turn, projection, conversation, workItems\)\)/);
  assert.match(app, /renderCheckpointHistory\(resolvedCheckpoints, turnTarget\("assistant"\)\)/);
  assert.match(app, /resolvedCheckpoints\.push\(item\); return/);
  assert.match(app, /renderActionTimeline\(actions, delegations, \{ interactionState:/);
  assert.match(app, /function renderDelegationGroup\(group, groups, target, visited, depth = 0, \{ waitingForHuman = false, recoveredFailures = new Set\(\) \} = \{\}\)/);
  assert.match(app, /if \(item\.kind === "team_activity"\) \{/);
  assert.match(app, /const events = \(item\.events \|\| \[\]\)\.filter/);
  assert.match(app, /InteractionShell\.reconcileTeamActivityEvents\(events, projection\.specialists\)/);
  assert.match(app, /if \(!actions\.length && reconciledEvents\.length\) renderTeamActivity/);
  assert.match(app, /expertCount: turnVerifiedRoles\.size/);
  assert.match(app, /failed \? "需要处理 · 部分步骤失败"/);
  assert.match(app, /`已完成 · \$\{events\.length\} 项证据`/);
  assert.match(app, /event\.status === "failed" \? "需要处理" : eventStatusLabel\(event\.status\)/);
  assert.match(interaction, /function effectiveWorkItemStatus\(workItem, delegation, agent, ownedActions\)/);
  assert.match(interaction, /status_source: "canonical_work_item"/);
  assert.match(conversation, /agents: liveV2 && Array\.isArray\(remote\.agents\)/);
  assert.match(app, /if \(!delegationById\.has\(action\.delegation_id\)\) \{ unverified\.actions\.push\(action\); return; \}/);
  assert.match(app, /const waitingActionCount = actions\.filter\(\(action\) => isWaitingForAnswerAction\(action, waitingForHuman\)\)\.length/);
  assert.match(app, /section\.open = savedOpen === undefined \? Boolean\(failedCount\) : savedOpen/);
  assert.match(app, /section\.dataset\.defaultDisclosure = section\.open \? "open" : "closed"/);
  assert.match(app, /if \(item\.kind === "approval" \|\| item\.kind === "question"\) \{ renderActions\(\); renderHumanCheckpoint\(item, \{ interactive: projection\.observation\?\.degraded !== true && projection\.background\?\.cancelling !== true && state\.cancelRequestInFlight !== true, target: ensureAiTurn\(\) \}\); return; \}/);
  assert.match(app, /const canRespond = pending && interactive/);
  assert.match(app, /ui\.agentWorking\.hidden = !fallbackWorkingSurface/);
  const timelineRenderer = app.slice(app.indexOf("function renderActionTimeline"), app.indexOf("function renderCheckpointHistory"));
  assert.match(timelineRenderer, /target\.append\(section\)/);
  assert.doesNotMatch(timelineRenderer, /ui\.messageList\.append/);
  assert.match(app, /action\.tool_class === "control"/);
  assert.match(app, /const rootOnly = rootAgent\.actions\.length && !roots\.length && !unverified\.actions\.length/);
  assert.match(app, /list\.className = "agent-action-list action-timeline-flat"/);
  assert.match(app, /button\.textContent = "技术详情"/);
  assert.match(app, /kicker\.textContent = "执行过程"/);
  assert.doesNotMatch(app, /kicker\.textContent = "执行证据"/);
  assert.match(css, /\.action-timeline\{[^}]*border:1px solid rgba\(98,88,244,\.18\)/);
  assert.match(css, /\.action-timeline>summary\{/);
  assert.match(css, /\.action-timeline-glance\{/);
  assert.match(css, /\.agent-action-error,\.agent-action-result\{/);
  assert.match(css, /\.agent-action\[data-tool-class="control"\]\{opacity:\.72\}/);
  assert.match(css, /\.action-timeline\[data-status="waiting"\]>summary>b\{color:var\(--amber\)/);
  assert.match(css, /\.agent-action\[data-status="waiting"\]>i\{color:var\(--amber\)/);
  assert.match(css, /body \.ai-turn\s*\{[^}]*display:\s*grid/);
  assert.match(css, /body \.ai-turn \.action-timeline\s*\{[^}]*border:\s*0/);
});

test("a backend-resolved historical failure stays auditable without remaining current", async () => {
  const { app } = await sources();
  const interaction = await readFile(join(web, "interaction-shell.js"), "utf8");
  const recovery = app.slice(app.indexOf("function recoveredDataExperimentFailures"), app.indexOf("function renderConversationTurn"));
  const recoveredRow = app.slice(app.indexOf("function renderRecoveredActionRow"), app.indexOf("function renderActionRow"));
  const timeline = app.slice(app.indexOf("function renderActionTimeline"), app.indexOf("function renderCheckpointHistory"));
  assert.match(recovery, /InteractionShell\.supersededFailureSourceIds\(risks\)/);
  assert.match(recovery, /InteractionShell\.turnHasActiveFailure\(turn, actions, conversation\.risks\)/);
  assert.match(interaction, /risk\.active === false/);
  assert.match(interaction, /normalizedToken\(risk\.lifecycle_status\) === "superseded"/);
  assert.match(interaction, /normalizedToken\(risk\.resolution\?\.kind\) === "superseded_by_later_success"/);
  assert.match(recovery, /action\?\.status === "failed" && recoveredActionIds\.has\(action\.action_id\)/);
  assert.match(timeline, /recoveredFailures = new Set\(\)/);
  assert.match(timeline, /\["failed", "identity_error"\]\.includes\(action\.status\) && !recoveredFailures\.has\(action\) && !isUserDeclinedAction\(action\)/);
  assert.doesNotMatch(timeline, /recoveredFailures\.size \? "执行已恢复"/);
  assert.doesNotMatch(timeline, /本轮曾遇到问题，后续执行已经恢复/);
  assert.match(recoveredRow, /timing\.textContent = "已由后续正确调用完成"/);
  assert.match(recoveredRow, /summary\.textContent = "查看初次调用记录"/);
  assert.match(recoveredRow, /status\.textContent = "已处理"/);
  assert.match(recoveredRow, /evidence\.dataset\.originalStatus = action\.status/);
  assert.match(recoveredRow, /action\.error\?\.message \|\| action\.error\?\.code/);
  assert.match(recoveredRow, /openEventResultRef\(action\.event_result_ref\)/);
  assert.match(app, /hasFailure = group\.actions\.some\(\(action\) => \["failed", "identity_error"\]\.includes\(action\.status\) && !recoveredFailures\.has\(action\) && !isUserDeclinedAction\(action\)\)/);
  assert.match(app, /stateLabel\.textContent = hasFailure \? "需要处理"/);
});

test("sample-inference and expert handoff actions use product language", async () => {
  const conversationView = await readFile(join(web, "conversation-view.js"), "utf8");
  assert.match(conversationView, /model_harness_authorize_sample_inference:\s*"申请本次新样本试跑"/);
  assert.match(conversationView, /send_message:\s*"转交给专家"/);
});

test("warm editorial visual system keeps dialogue primary and controls consistent", async () => {
  const { html, css, visualCss } = await sources();
  assert.match(html, /MODEL TRAINING AGENT/);
  assert.match(html, /本地优先 · 关键操作需确认 · 结果可追溯/);
  assert.match(visualCss, /--font-sans:\s*-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC"/);
  assert.match(visualCss, /--brand:\s*#5a4fd6/);
  assert.match(visualCss, /--brand-hover:\s*#493fbe/);
  assert.match(visualCss, /--brand-soft:\s*#f0eefc/);
  assert.match(visualCss, /--sidebar-width:\s*264px/);
  assert.match(visualCss, /--radius-lg:\s*16px/);
  assert.match(visualCss, /body \.send-button\s*{[^}]*border-radius:\s*50%/);
  assert.match(visualCss, /body \.decision-actions\.human-choice-list\s*{[^}]*grid-template-columns:\s*1fr/);
  assert.match(visualCss, /body \.workspace-result-card:not\(button\)\s*{[^}]*cursor:\s*default/);
  assert.match(visualCss, /body \.human-checkpoint\s*,/);
  assert.match(css, /#datasetButton \.attachment-label\{[^}]*font-size:12px[^}]*font-weight:500/);
  assert.match(css, /@media\(max-width:720px\)\{#datasetButton\.attachment-button\{[^}]*min-width:44px[^}]*min-height:44px[^}]*justify-content:center/);
});

test("new-task home stays conversation-led while verified specialists appear only inside real execution", async () => {
  const { html, app } = await sources();
  const home = html.slice(html.indexOf('<section class="empty-state"'), html.indexOf('<section class="conversation"'));
  assert.doesNotMatch(home, /专家|Hugging Face|GitHub/);
  assert.match(home, /先通过对话把目标说清楚/);
  assert.match(home, /可联网查找开源模型/);
  assert.doesNotMatch(app, /个专家已参与本轮/);
  assert.match(app, /const workItems = projectionWorkItems\(projection\)/);
  assert.match(app, /const activeSpecialists = activeProjectionSpecialists\(projection\)/);
  assert.match(app, /ui\.composerModeLabel\.textContent = "AI 已连接"/);
  assert.doesNotMatch(app, /ui\.composerModeLabel\.textContent = activeSpecialists\.length \?/);
  assert.match(app, /具体分工只在对应 AI 回合的执行过程中展示/);
  assert.match(app, /const verifiedRoles = new Set\(workItems\.map\(\(item\) => item\.role\?\.role_id\)\.filter\(Boolean\)\)/);
  assert.match(app, /expertCount: turnVerifiedRoles\.size/);
  assert.match(app, /expertCount \? `\$\{expertCount\} 位专家 · ` : ""/);
});

test("evaluation decisions are explicitly read-only until a real approval checkpoint exists", async () => {
  const { visualCss, app } = await sources();
  assert.match(app, /gate\.dataset\.interactive = "false"/);
  assert.match(app, /gateHint\.textContent = "只读 · 出现真实确认卡后才能执行"/);
  assert.match(app, /item\.setAttribute\("aria-disabled", "true"\)/);
  assert.match(app, /stateLabel\.textContent = gateState === "recommended" \? "建议" : gateState === "ready" \? "可审阅"/);
  assert.match(visualCss, /body \.workspace-decision-gate > div\s*\{[^}]*cursor:\s*default/);
});

test("an empty capability match is rendered as an honest boundary, not a system failure", async () => {
  const { app } = await sources();
  const summaryStart = app.indexOf("function parseActionResultValue");
  const summaryEnd = app.indexOf("function actionResultKey");
  const summary = app.slice(summaryStart, summaryEnd);
  const summarize = new Function("STATUS_LABELS", `${summary}\nreturn actionResultSummary;`)({});
  assert.match(summary, /action\?\.tool_name === "model_harness_match_capability" && Array\.isArray\(result\?\.matches\)/);
  assert.match(summary, /state: result\.matches\.length \? "completed" : "completed_empty"/);
  assert.match(app, /当前没有匹配项。这是能力边界，不是系统故障/);
  assert.match(summary, /const searchResult = result\?\.search && typeof result\.search === "object" \? result\.search : result/);
  assert.match(summary, /return \{ state: "failed", text: `候选模型搜索未返回结果；\$\{providerErrors\.length\} 个模型来源失败/);
  assert.match(summary, /return \{ state: "completed", text: `候选模型返回 \$\{searchResult\.candidates\.length\} 项结果\$\{partialFailureText\}`/);
  assert.equal((summary.match(/这是能力边界，不是系统故障/g) || []).length, 1);
  assert.ok(
    summary.indexOf("model_harness_match_capability") < summary.indexOf("provider_errors"),
    "provider errors and other empty collections must not reuse the capability-boundary state",
  );
  assert.deepEqual(
    summarize(
      { tool_name: "model_harness_match_capability" },
      { event: { payload: { result: { matches: [] } } } },
    ),
    { state: "completed_empty", text: "能力匹配已完成：当前没有匹配项。这是能力边界，不是系统故障。" },
  );
  const providerFailure = summarize(
    { tool_name: "model_harness_search_model_sources" },
    { event: { payload: { result: { candidates: [], provider_errors: [{ provider: "huggingface", reason: "timeout" }] } } } },
  );
  assert.equal(providerFailure.state, "failed");
  assert.match(providerFailure.text, /候选模型搜索未返回结果；1 个模型来源失败/);
  assert.doesNotMatch(providerFailure.text, /能力边界|系统故障/);
  const partialProviderFailure = summarize(
    { tool_name: "model_harness_search_model_sources" },
    { event: { payload: { result: { search: { candidates: [{ id: "candidate-1" }], provider_errors: [{ provider: "github", reason: "rate_limit" }] } } } } },
  );
  assert.equal(partialProviderFailure.state, "completed");
  assert.match(partialProviderFailure.text, /候选模型返回 1 项结果；1 个模型来源部分失败/);
  assert.doesNotMatch(partialProviderFailure.text, /能力边界|系统故障/);
  assert.deepEqual(
    summarize(
      { tool_name: "model_harness_list_recipes" },
      { event: { payload: { result: { recipes: [] } } } },
    ),
    { state: "completed", text: "训练方案返回 0 项结果" },
  );
  assert.match(app, /timing\.textContent = "已由后续正确调用完成"/);
  assert.match(app, /status\.textContent = "已处理"/);
  assert.doesNotMatch(app, /timing\.textContent = "后续执行已恢复"/);
});

test("composer queues stable idempotent messages and cancellation stays explicit", async () => {
  const { html, css, app } = await sources();
  assert.match(html, /id="composerDelivery" hidden role="status" aria-live="polite"/);
  assert.match(html, /id="composerDeliveryLabel">将在本轮结束后继续/);
  assert.match(app, /const DEFAULT_CONVERSATION_MESSAGE_MODE = "queue_after_turn"/);
  assert.match(app, /const OPTIONAL_CONVERSATION_MESSAGE_MODES = \["intervene_current", "stop_and_replace"\]/);
  assert.match(app, /Array\.isArray\(conversation\?\.supported_modes\)/);
  assert.match(app, /Array\.isArray\(state\.productRuntime\?\.agent\?\.supported_modes\)/);
  assert.match(app, /const agentQueued = Boolean\(state\.runtimeReady && state\.selectedTaskId && !checkpoint && conversationAgentResponseRunning\(conversation\)\)/);
  assert.match(app, /const backgroundRunning = Boolean\(state\.runtimeReady && state\.selectedTaskId && !checkpoint && !agentQueued && conversationHasBackgroundTraining\(conversation\)\)/);
  assert.match(app, /ui\.composerDeliveryLabel\.textContent = "将在本轮结束后继续"/);
  assert.match(app, /ui\.composerDeliveryLabel\.textContent = "后台操作正在进行，可继续对话"/);
  // Static binding and resource checks also use background actions; never imply a training Run.
  assert.doesNotMatch(app, /后台训练/);
  assert.match(app, /实时干预/);
  assert.match(app, /停止并替换/);
  assert.doesNotMatch(app, /mode:\s*"intervene_current"/);
  assert.doesNotMatch(app, /mode:\s*"stop_and_replace"/);

  assert.match(app, /previous\?\.task_id === taskId && previous\.text === text && previous\.status === "failed"/);
  assert.match(app, /return previous/);
  assert.match(app, /request_id: createConversationRequestId\(\), status: "sending"/);
  assert.match(app, /mode: DEFAULT_CONVERSATION_MESSAGE_MODE, request_id: submission\.request_id/);
  assert.match(app, /response\?\.accepted !== true \|\| \["failed", "cancelled", "canceled", "rejected", "interrupted"\]\.includes\(status\)/);
  assert.match(app, /structuredErrorMessage\(response, "后端没有接受这条消息"\)/);
  assert.match(app, /state\.messageSubmission\?\.request_id === submission\.request_id\) state\.messageSubmission = null/);
  assert.match(app, /state\.messageSubmission\.status = "failed"/);
  assert.match(app, /再次发送同一条消息会复用请求编号/);

  assert.match(app, /checkpoint\?\.kind === "approval"[\s\S]*聊天文字不会被当作授权/);
  assert.doesNotMatch(app, /postQuestionAnswers\(checkpoint, \[\{ id: question\.id, selected: \[\], custom: text \}\]\)/);
  assert.match(app, /conversationTransportPath\(taskId, "questions", item\.rpc_id\)/);

  assert.match(app, /function openCancelAgentDialog\(\)/);
  assert.match(app, /function backgroundCancellationPending\(conversation\)/);
  assert.match(app, /state\.cancelRequestInFlight === true \|\| backgroundCancellationPending\(conversation\)/);
  assert.match(app, /停止请求已经记录/);
  assert.match(app, /当前智能协作与任务后台动作/);
  assert.match(app, /正在停止当前智能协作与任务后台动作/);
  assert.match(app, /json: \{ reason: cancelReason \}/);
  assert.match(app, /停止请求失败：[\s\S]*是否停止尚未确认/);
  assert.doesNotMatch(app, /不会取消正在执行的训练 Run/);
  assert.doesNotMatch(app, /训练 Run 状态未被修改/);
  assert.match(css, /\.composer-delivery\{display:grid/);
  assert.match(css, /\.composer-wrap\[data-delivery="queue_after_turn"\] \.composer/);
  assert.match(css, /\.cancel-reason-field/);
});

test("composer attachment chip exposes honest states and retries the same request identity", async () => {
  const { html, visualCss, app } = await sources();
  for (const id of [
    "composerAttachment", "attachmentType", "attachmentName", "attachmentMeta", "attachmentStatus",
    "retryAttachmentButton", "removeAttachmentButton", "composerRetry", "composerRetryButton", "composerRetryHint",
  ]) assert.match(html, new RegExp(`id="${id}"`));

  assert.match(html, /id="composerAttachment"[^>]*data-state="pending"[^>]*role="group"[^>]*aria-label="所选文件"/);
  assert.match(html, /id="attachmentStatus"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(app, /const COMPOSER_ATTACHMENT_STATUS = \{ pending: "待核对", validating: "校验中", ready: "已就绪", failed: "失败" \}/);
  assert.match(app, /function stageComposerAttachment\(file\)/);
  assert.match(app, /request_id: createConversationRequestId\(\), status: "pending"/);
  assert.match(app, /function retryComposerAttachment\(\)/);
  assert.match(app, /attachment\.status === "failed" && attachment\.can_retry === true/);
  assert.match(app, /await uploadDataset\(attachment\.file, \{ \.\.\.attachment\.options, attachment \}\)/);
  assert.match(app, /headers\["x-request-id"\] = attachment\.request_id/);
  assert.match(app, /const responseMayBeLost = !Number\.isFinite\(error\.status\) \|\| error\.status === 408 \|\| error\.status >= 500/);
  assert.match(app, /response = await reconcileDatasetUploadReceipt\(taskId, attachment\)/);
  assert.match(app, /awaitReceipt\(`数据请求的响应未能确认：\$\{error\.message\}`\)/);
  assert.match(app, /status: "pending", error: message, retry_stage: "reconcile"/);
  assert.match(app, /不会先把它标成失败/);
  assert.match(app, /updateComposerAttachment\(attachment, \{ status: "validating"/);
  assert.match(app, /updateComposerAttachment\(attachment, \{ status: "ready", dataset_id: datasetId/);
  assert.match(app, /retry_stage: "continuation"/);
  assert.match(app, /failed\.request_id !== continuation\.request_id/);
  assert.match(app, /重试只会续接原问题，不会重复上传/);
  assert.match(app, /showComposerRetry\(\{ label: failedSubmission.new_request_required \? "刷新后重发" : "重试发送"/);
  assert.match(app, /failed\.request_id !== failedSubmission\.request_id/);
  assert.match(app, /await submitMessage\(failed\.text\)/);
  assert.match(app, /importedDatasetId \? "文件条目已从输入框移除；已经导入当前任务的数据仍然保留。" : "文件已从输入框移除。"/);
  assert.match(app, /status: "pending", error: "等待选择预测目标", retry_stage: "upload", can_retry: true/);
  assert.doesNotMatch(app, /setInterval\([^\n]*composerAttachment|setTimeout\([^\n]*status:\s*"ready"/);

  assert.match(visualCss, /body \.composer-attachment\s*\{/);
  assert.match(visualCss, /body \.composer-attachment\[data-state="validating"\]/);
  assert.match(visualCss, /body \.composer-attachment\[data-state="ready"\]/);
  assert.match(visualCss, /body \.composer-attachment\[data-state="failed"\]/);
  assert.match(visualCss, /body \.attachment-retry\[hidden\]\s*\{[\s\S]*?display: none;/);
  assert.match(visualCss, /body \.attachment-copy b\s*\{[\s\S]*?font-size: var\(--text-md\);[\s\S]*?line-height: var\(--leading-md\);/);
});

test("terminal synthesis adds one compact result card only for exact task-owned result objects", async () => {
  const { visualCss, app } = await sources();
  const modelStart = app.indexOf("function terminalResultCardModel(item, projection)");
  const modelEnd = app.indexOf("function appendTerminalResultCard", modelStart);
  assert.ok(modelStart >= 0 && modelEnd > modelStart, "terminal result model must remain separately auditable");
  const model = app.slice(modelStart, modelEnd);
  const refs = app.slice(app.indexOf("function terminalResultRefs"), app.indexOf("function reportForTerminalRef"));

  assert.match(model, /item\?\.kind !== "final_synthesis"/);
  assert.match(model, /item\.completion_eligible !== true/);
  assert.match(model, /runtimeStatusToken\(item\.status\) !== "completed"/);
  assert.match(model, /projection\?\.phase !== "result_ready"/);
  assert.match(model, /projection\.background\?\.running === true/);
  assert.match(model, /projection\.result\?\.final\?\.event_id !== item\.event_id/);
  assert.match(refs, /ref\.task_id === taskId/);
  assert.match(refs, /ref\.run_id === runId/);
  assert.match(refs, /typeof ref\.digest === "string" && EVIDENCE_SHA256\.test\(ref\.digest\)/);
  assert.match(refs, /result\.status !== "completed"/);
  assert.match(model, /if \(!report && !bundle\) return null/);
  assert.match(app, /return metrics\.slice\(0, 3\)/);
  assert.match(model, /bundle && state\.runtimeReady \? \{ kind: "download", label: "下载现有交付包"/);
  assert.match(model, /\{ kind: "open", label: "打开结果", ref: primaryRef \}/);
  assert.match(app, /state\.selectedTaskId !== model\.taskId \|\| state\.task\?\.current_result\?\.run_id !== model\.runId/);
  assert.match(app, /requestArtifactBundleDownload\(\{ run_id: model\.runId \}, model\.cta\.bundle\)/);
  assert.match(app, /if \(!appendTerminalResultCard\(item, body, projection\)\) appendObjectRefs\(body, finalSynthesisFallbackRefs\(item\)\)/);
  assert.match(app, /function returnedObjectMatchesRef\(ref, payload\)/);
  assert.match(app, /returnedObjectMatchesRef\(normalized, payload\)/);
  assert.match(app, /returnedObjectMatchesRef\(ref, payload\)/);
  assert.doesNotMatch(model, /innerHTML|dataset_id|report_sha256|manifest_sha256/);

  assert.match(visualCss, /--text-body: 15px;[\s\S]*?--leading-body: 24px;[\s\S]*?--leading-lg: 24px;/);
  assert.match(visualCss, /body \.message-copy\s*\{[\s\S]*?font-size: var\(--text-body\);[\s\S]*?line-height: var\(--leading-body\);/);
  assert.match(visualCss, /body \.rich-message h2,[\s\S]*?body \.rich-message h4\s*\{[\s\S]*?font-size: 16px;[\s\S]*?line-height: 24px;/);
  assert.match(visualCss, /body \.turn-result-card\s*\{[\s\S]*?border-radius: 16px;[\s\S]*?box-shadow: 0 8px 24px/);
  assert.match(visualCss, /body \.turn-result-card h3\s*\{[\s\S]*?font-size: 16px;[\s\S]*?line-height: 24px;/);
  assert.match(visualCss, /body \.turn-result-conclusion\s*\{[\s\S]*?font-size: 15px;[\s\S]*?line-height: 24px;/);
  assert.match(visualCss, /body \.turn-result-card > footer button\s*\{[\s\S]*?background: var\(--brand\);/);
  const mobile = visualCss.slice(visualCss.indexOf("@media (max-width: 720px)"));
  assert.doesNotMatch(mobile, /--text-body\s*:\s*(?:1[0-4]|\d)px|\.message-copy\s*\{[^}]*font-size\s*:\s*(?:1[0-4]|\d)px|turn-result-conclusion\s*\{[^}]*font-size\s*:\s*(?:1[0-4]|\d)px/);
});
