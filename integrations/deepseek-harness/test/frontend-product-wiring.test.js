import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "../../../model_harness/web");

async function sources() {
  const [html, css, app] = await Promise.all([
    readFile(join(web, "index.html"), "utf8"),
    readFile(join(web, "styles.css"), "utf8"),
    readFile(join(web, "app.js"), "utf8"),
  ]);
  return { html, css, app };
}

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

test("L4 evaluation, raw sample, and Artifact Bundle controls call task-owned evidence APIs", async () => {
  const { html, app } = await sources();
  for (const id of [
    "evidenceDimensions", "candidateList", "failureSampleList", "runHistoryList",
    "sampleTrialInput", "sampleTrialRunButton", "sampleInferenceList",
    "buildArtifactBundleButton", "artifactBundleList",
  ]) assert.match(html, new RegExp(`id="${id}"`));

  assert.match(app, /\/evaluation-report/);
  assert.match(app, /\/sample-inferences/);
  assert.match(app, /\/artifact-bundles/);
  assert.match(app, /\/download`/);
  assert.match(app, /"X-Filename": encodeURIComponent\(filename\)/);
  assert.match(app, /"X-Sample-Type": sampleType/);
  assert.match(app, /sample_inference_check_id: latestPassed\.check_id/);
  assert.match(app, /raw_data_included === false/);
  assert.match(app, /capability_unavailable/);
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
  assert.match(app, /label: "绑定并分析模型来源"/);
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

test("terminal runs expose an Agent-independent task-owned retry path", async () => {
  const { html, app } = await sources();
  assert.match(html, /id="retryRunButton"[^>]*hidden/);
  assert.match(app, /TERMINAL_RETRY_STATUSES = new Set\(\["failed", "cancelled", "interrupted"\]\)/);
  assert.match(app, /retry_training_run/);
  assert.match(app, /function retryRunDirect\(\)/);
  assert.match(app, /request\(`\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/runs`, \{ method: "POST" \}\)/);
  assert.match(app, /旧事件、错误和产物不会被覆盖/);
  assert.match(app, /页面也不会在后端返回前伪造运行状态/);
  assert.match(app, /TERMINAL_RETRY_STATUSES\.has\(state\.task\?\.current_result\?\.status\)\) \{ retryRunDirect\(\); return; \}/);
  assert.doesNotMatch(app, /state\.task\.status\s*=\s*"running"/);
});

test("conversation-native shell keeps dialogue and a stage-aware desktop workspace side by side", async () => {
  const { html, css, app } = await sources();
  assert.match(html, /<title>Specialist Model Studio · 专业模型智能工作台<\/title>/);
  assert.match(html, /<strong>Specialist Model Studio<\/strong>/);
  for (const id of [
    "workspaceToggleButton", "agentCheckpoint", "agentCheckpointStage",
    "agentCheckpointTitle", "agentCheckpointState", "agentCheckpointBody",
    "agentCheckpointActions", "agentCheckpointWorkspaceButton",
  ]) assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1, `${id} must be unique`);

  assert.match(html, /id="taskControlPanel" hidden/);
  assert.match(html, /id="workspaceToggleButton"[^>]*aria-label="打开任务工作区"/);
  assert.match(html, /id="taskPlan" hidden/);
  assert.match(html, /id="stageList" hidden/);
  assert.match(html, /data-context="plan"[^>]*>方案</);
  assert.match(html, /data-context="data"[^>]*>数据</);
  assert.match(html, /data-context="run"[^>]*>训练</);
  assert.match(html, /data-context="evaluation"[^>]*>评测</);
  assert.match(html, /data-context="artifacts"[^>]*>产物</);
  assert.match(app, /checkpointHomes = new Map\(\)/);
  assert.match(app, /function workflowStatus\(task\)/);
  assert.match(app, /stage === "environment_lock"\) return \{ label: blocked \? "训练环境阻断"/);
  assert.match(app, /task\.model_binding \? `已固定 \$\{modelSourceProviderLabel\(task\.model_binding\.provider\)\} 来源`/);
  assert.match(app, /time\.textContent = formatRelativeTime\(task\.updated_at_utc\)/);
  assert.match(app, /ui\.taskEyebrow\.textContent = `\$\{stageLabel\(stageKey\(task\)\)\} · \$\{workflow\.label\}`/);
  assert.match(app, /ui\.agentCheckpointBody\.append\(card\)/);
  assert.match(app, /function checkpointIsInline\(card\)/);
  assert.match(app, /function checkpointWorkspaceContext\(task, card = checkpointCardFor\(task\)\)/);
  assert.match(app, /ui\.agentCheckpointActions\.hidden = inline/);
  assert.match(app, /dockedWorkspaceMedia\.matches\) \{ openInspector\(context\); revealCurrentWorkspaceObject\(task\); \}/);
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
  assert.match(app, /workspaceToggleButton\.setAttribute\("aria-label", "关闭任务工作区"\)/);
  assert.match(app, /window\.requestAnimationFrame\(\(\) => ui\.closeInspectorButton\.focus\(\)\)/);
  assert.match(app, /const isolated = overlayWorkspace\(\) && ui\.inspector\.dataset\.open === "true"/);
  assert.match(app, /ui\.sidebar\.inert = isolated; ui\.conversationMain\.inert = isolated; ui\.mobileViewNav\.inert = isolated/);
  assert.match(app, /ui\.inspector\.setAttribute\("aria-modal", "true"\)/);
  assert.match(app, /event\.key === "Escape"[^\n]*closeInspector\(\)/);
  assert.match(app, /event\.key !== "Tab"/);
  assert.match(app, /active === first \|\| !ui\.inspector\.contains\(active\)/);
  assert.match(app, /active === last \|\| !ui\.inspector\.contains\(active\)/);
  assert.match(app, /const restoreTarget = opener\?\.isConnected[^\n]+ui\.workspaceToggleButton/);
  assert.match(app, /inspectorMedia\.addEventListener\("change"/);
  assert.match(css, /\.app-shell\{grid-template-columns:244px minmax\(0,1fr\)\}/);
  assert.match(app, /dockedWorkspaceMedia = window\.matchMedia\("\(min-width:1184px\)"\)/);
  assert.match(css, /@media\(min-width:1184px\)[\s\S]*body\[data-workspace="open"\] \.app-shell\{grid-template-columns:244px minmax\(0,1fr\) clamp\(340px,32vw,460px\)\}/);
  assert.match(css, /@media\(min-width:1184px\)[\s\S]*\.inspector\{display:none;[^}]*grid-column:auto[^}]*\}/);
  assert.match(css, /@media\(min-width:1184px\)[\s\S]*body\[data-workspace="open"\] \.inspector\{display:block;grid-column:3;/);
  assert.match(css, /@media\(min-width:1184px\)[\s\S]*\.inspector-scrim:not\(\[hidden\]\)\{display:none!important\}/);
  assert.match(css, /\.inspector\[data-open="true"\]\{[^}]*visibility:visible[^}]*pointer-events:auto[^}]*transform:translateX\(0\)/);
  assert.match(css, /@media\(max-width:720px\)[\s\S]*?\.inspector\{width:100%;z-index:42\}/);
  assert.match(css, /@media\(max-width:720px\)[\s\S]*body\[data-workspace="open"\] \.mobile-view-nav\{display:none\}/);
  assert.match(css, /#taskControlPanel,#taskPlan,#stageList\{display:none!important\}/);
  assert.match(app, /function compactConversationItems\(items\)/);
  assert.match(app, /kind: "tool_group"/);
  assert.match(app, /result-summary:\$\{result\.run_id\}:\$\{evaluationDigest\}/);
});

test("runtime fallback is visible as a local workflow without disabling real task actions", async () => {
  const { html, css, app } = await sources();
  assert.match(html, /id="composerMode"[^>]*data-state="checking"/);
  assert.match(html, /id="composerModeLabel">正在确认协作模式</);
  assert.match(html, /aria-label="向 Specialist Model Studio 描述训练需求"/);
  assert.doesNotMatch(html, /class="composer-mode"[^>]*>[^<]*训练 Agent/);
  assert.match(app, /function renderRuntimeMode\(mode\)/);
  assert.match(app, /本地流程模式 · 训练操作仍可用/);
  assert.match(app, /本地流程模式 · 训练操作可用/);
  assert.match(app, /renderRuntimeMode\(state\.runtimeReady \? "agent" : "local"\)/);
  assert.match(app, /error\.status === 503\)[^\n]*renderRuntimeMode\("local"\)/);
  assert.match(app, /当前是本地流程模式：需求快捷选项、模型搜索、数据导入、合同确认和训练操作仍可用/);
  assert.match(css, /\.composer-mode\[data-state="local"\]/);
  assert.match(css, /\.composer-mode:not\(\[data-state="local"\]\)\{display:none\}/);
  assert.doesNotMatch(app, /if \(!state\.runtimeReady\)[^\n]*startRunDirect/);
});

test("fresh empty workspace enters the shared home composer state", async () => {
  const { html, app } = await sources();
  assert.match(html, /id="homeComposerSlot"/);
  assert.match(html, /id="homeBoundary"/);
  assert.match(html, /已验证 Recipe 可以真实训练；其他仓库当前会停在可审查的分析或阻断/);
  assert.doesNotMatch(html, /匹配开源模型、准备数据、训练和评测/);
  assert.match(app, /function enterHomeState\(\{ focusComposer = true \} = \{\}\)/);
  assert.match(app, /ui\.homeComposerSlot\.append\(ui\.composerWrap\)/);
  assert.match(app, /ui\.messageInput\.placeholder = "告诉我，你想让模型学会什么？"/);
  assert.match(app, /function openNewTask\(\)[\s\S]*?enterHomeState\(\);/);
  assert.match(app, /if \(!state\.selectedTaskId\) enterHomeState\(\{ focusComposer: false \}\)/);
  assert.match(app, /if \(!requested\) \{ enterHomeState\(\{ focusComposer: false \}\); return; \}/);
  assert.match(app, /没有替你打开其他任务/);
  assert.doesNotMatch(app, /requested : state\.tasks\[0\]\?\.task_id/);
});

test("runtime and family-catalog failures preserve honest product boundaries", async () => {
  const { app } = await sources();
  assert.match(app, /request\("\/runtime"\)/);
  assert.match(app, /byom_execution_available === true/);
  assert.match(app, /已验证 Recipe 可以真实训练/);
  assert.match(app, /taskSpecFamiliesError = error\.message/);
  assert.match(app, /const loaded = await loadTaskSpecFamilies\(\)/);
  assert.match(app, /模型类型目录加载失败/);
});

test("persisted source search and evidence timeline survive refresh without stale candidates", async () => {
  const { app } = await sources();
  assert.match(app, /request\(`\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/model-source-searches`\)/);
  assert.match(app, /item\.base_spec_revision === response\.task\.current_spec_revision/);
  assert.match(app, /state\.modelSourceCandidates = failedSearch \? \[\] : \[\.\.\.\(latestSearch\?\.candidates \|\| \[\]\)\]/);
  assert.match(app, /state\.modelSourceCandidates\.length\) showNotice\("官方目录没有返回候选[^\n]+else hideNotice\(\)/);
  assert.match(app, /ui\.capabilityState\.textContent = "模型已绑定"/);
  assert.match(app, /ui\.capabilityState\.textContent = analysisStatus === "failed" \? "分析失败" : "分析已取消"/);
  assert.match(app, /else if \(analysis\) \{ const analysisBlocked = analysis\.status !== "complete" \|\| analysisBlockers\.length > 0/);
  assert.doesNotMatch(app, /const SPEC_FAMILIES/);
  assert.match(app, /request\("\/task-spec\/families"\)/);
  assert.match(app, /if \(currentCandidate && !candidates\.some\(\(item\) => item\.family === currentCandidate\.family\)\) candidates\.unshift\(currentCandidate\)/);
  assert.match(app, /allProvidersFailed \? "failed" : "completed_empty"/);
  assert.match(app, /const systemOnlyNote = \/\^用户通过产品界面/);
  assert.match(app, /function taskEvidenceTimeline\(task\)/);
  assert.match(app, /官方模型目录搜索/);
  assert.match(app, /生成不可变训练计划/);
  assert.match(app, /本机资源探测/);
  assert.match(app, /conversationWithEvidence\(state\.task, state\.conversation\)/);
  assert.match(app, /item\.detail \|\| \(item\.status === "completed"/);
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

test("task understanding is a backend-driven quick-reply conversation with advanced editing only", async () => {
  const { html, css, app } = await sources();
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
  assert.match(app, /stageKey\(state\.task\) === "task_understanding"/);
  assert.match(app, /state\.taskSpecDescriptionMode && stageKey\(state\.task\) === "task_understanding"/);
  assert.match(app, /business_goal: nextGoal, user_note: `用户补充：\$\{text\}`/);
  assert.ok(app.indexOf('stageKey(state.task) === "task_understanding"') < app.indexOf('if (!state.runtimeReady)'), "TaskSpec supplement must bypass Agent Runtime");
  assert.match(app, /\/spec\/revisions`/);
  assert.match(app, /需求版本 v\$\{spec\.revision\} 已根据补充重新判定/);
  assert.match(app, /const confirmedOutput = selectedCandidate\?\.output/);
  assert.doesNotMatch(app, /\$\{capability\.target_kind \|\| "待确认输出"\}/);
  assert.match(app, /error\.status === 409\) await refreshSelected\(\{ force: true \}\)/);
  assert.match(app, /\["clarify_task_spec", "confirm_task_spec"\][^\n]*scrollToCheckpoint\(\)/);
  assert.match(css, /\.task-spec-quick-replies\{display:grid/);
  assert.match(css, /\.task-spec-choice\.featured/);
  assert.match(css, /\.task-spec-reparse/);
});
