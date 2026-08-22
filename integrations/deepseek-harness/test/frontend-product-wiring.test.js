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

test("mobile inspector remains a full-screen sheet with 44px action targets", async () => {
  const { css } = await sources();
  assert.match(css, /@media\(max-width:720px\)[\s\S]*?\.inspector\{position:fixed;inset:0;[^}]*height:100dvh/);
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
  assert.match(app, /TERMINAL_RETRY_STATUSES\.has\(state\.task\?\.current_result\?\.status\)\) retryRunDirect\(\)/);
  assert.doesNotMatch(app, /state\.task\.status\s*=\s*"running"/);
});
