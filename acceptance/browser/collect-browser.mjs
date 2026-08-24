#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const LEGACY_VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
const UI_VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
];
const FAMILIES = ["image", "tabular", "audio"];
const V3_JOURNEY_VIEWPORT = { name: "desktop", width: 1440, height: 900 };
const MUTATING_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);
const RESOURCE_STAGES = new Set(["resource_probe", "environment_lock", "resource_fit"]);

function requireArgs(values, keys) {
  for (const key of keys) if (!values[key]) throw new Error(`missing --${key}`);
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || value === undefined) throw new Error(`invalid argument sequence near ${flag || "end"}`);
    values[flag.slice(2)] = value;
  }
  requireArgs(values, ["base-url", "output-dir", "source-commit", "producer-run-id", "chrome"]);
  values.mode ||= "legacy";
  if (values.mode === "legacy" && !values.journeys) throw new Error("missing --journeys");
  if (values.mode === "current-ui") {
    requireArgs(values, ["clarification-task-id", "blocked-task-id"]);
  } else if (values.mode === "v3-journey") {
    requireArgs(values, ["business-goal", "task-family", "provider", "query", "repository", "revision"]);
    if (!/^[a-z0-9_]+$/.test(values["task-family"])) throw new Error("task family must be a lowercase catalog identifier");
    if (!new Set(["github", "huggingface"]).has(values.provider)) throw new Error("provider must be github or huggingface");
    if (!/^[^/\s]+\/[^/\s]+$/.test(values.repository)) throw new Error("repository must use owner/name form");
    if (values.entrypoint && (values.entrypoint.startsWith("/") || values.entrypoint.split("/").includes(".."))) throw new Error("entrypoint must be a safe repository-relative path");
    if (values["base-image-digest"] && !/^sha256:[0-9a-f]{64}$/.test(values["base-image-digest"])) throw new Error("base image digest must be sha256:<64 lowercase hex>");
    const timeout = Number(values["timeout-ms"] || 180_000);
    if (!Number.isInteger(timeout) || timeout < 10_000 || timeout > 900_000) throw new Error("timeout-ms must be an integer between 10000 and 900000");
    values["timeout-ms"] = timeout;
  } else if (values.mode !== "legacy") throw new Error(`unsupported --mode ${values.mode}`);
  return values;
}

function digestText(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

function writeNdjson(filePath, records) {
  const values = records.length ? records : [{ kind: "producer", level: "info", message: "no records" }];
  fs.writeFileSync(filePath, `${values.map((item) => JSON.stringify(item)).join("\n")}\n`, { flag: "wx" });
}

function safeRequestRecord(kind, request, extra = {}) {
  const selected = new URL(request.url());
  return {
    kind,
    method: request.method(),
    path: selected.pathname,
    resource_type: request.resourceType(),
    ...extra,
  };
}

function normalizeRepository(value) {
  return String(value || "").trim().toLowerCase();
}

function requireRecord(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} is missing`);
  return value;
}

function requireText(value, label, pattern = null) {
  const selected = String(value || "").trim();
  if (!selected || (pattern && !pattern.test(selected))) throw new Error(`${label} is invalid or missing`);
  return selected;
}

function snapshotV3Lineage(task) {
  const binding = requireRecord(task?.model_binding, "model binding");
  const analysis = requireRecord(task?.repository_analysis, "repository analysis");
  const planView = requireRecord(task?.training_plan, "training plan view");
  const plan = requireRecord(planView.plan, "training plan");
  const approval = requireRecord(planView.latest_approval, "training plan approval");
  const feasibility = requireRecord(task?.resource_feasibility, "resource feasibility");
  const probe = requireRecord(feasibility.resource_probe, "resource probe");
  const blocker = (feasibility.blockers || []).find((item) => item?.active !== false && RESOURCE_STAGES.has(item?.stage));
  requireRecord(blocker, "active resource blocker");
  return {
    task_id: requireText(task.task_id, "task id"),
    resolution: {
      id: requireText(binding.resolution_id, "resolution id"),
      digest: requireText(binding.resolution_digest, "resolution digest", /^[0-9a-f]{64}$/),
      requested_revision: requireText(binding.requested_revision, "requested revision"),
      resolved_commit: requireText(binding.resolved_commit, "resolved commit", /^[0-9a-f]{40}$/),
    },
    binding: {
      id: requireText(binding.binding_revision_id, "binding revision id"),
      digest: requireText(binding.content_digest, "binding digest", /^[0-9a-f]{64}$/),
    },
    snapshot: {
      id: requireText(binding.snapshot_id, "snapshot id"),
      digest: requireText(binding.snapshot_digest, "snapshot digest", /^[0-9a-f]{64}$/),
    },
    analysis: {
      id: requireText(analysis.analysis_id, "analysis id"),
      digest: requireText(analysis.analysis_digest || binding.analysis_digest, "analysis digest", /^[0-9a-f]{64}$/),
      analyzer_version: requireText(analysis.analyzer_version, "analyzer version"),
    },
    plan: {
      id: requireText(plan.training_plan_revision_id, "training plan revision id"),
      digest: requireText(plan.plan_sha256, "training plan digest", /^[0-9a-f]{64}$/),
      revision: Number(plan.revision),
    },
    approval: {
      id: requireText(approval.approval_id, "approval id"),
      digest: requireText(approval.approval_sha256, "approval digest", /^[0-9a-f]{64}$/),
      plan_digest: requireText(approval.digest, "approved plan digest", /^[0-9a-f]{64}$/),
    },
    probe: {
      id: requireText(probe.resource_probe_id, "resource probe id"),
      digest: requireText(probe.probe_sha256, "resource probe digest", /^[0-9a-f]{64}$/),
    },
    blocker: {
      id: requireText(blocker.blocker_id, "blocker id"),
      digest: requireText(blocker.content_digest, "blocker digest", /^[0-9a-f]{64}$/),
      stage: requireText(blocker.stage, "blocker stage"),
      code: requireText(blocker.code, "blocker code"),
      detector: requireText(blocker.detector || blocker.details?.detector, "blocker detector"),
    },
  };
}

function v3RequiredRouteContracts(taskId, binding, analysis, plan, { manualMapping = false } = {}) {
  const taskPath = `/tasks/${encodeURIComponent(taskId)}`;
  const contracts = [
    { name: "task_created", method: "POST", path: "/tasks", statuses: [201], min: 1, max: 1 },
    { name: "task_spec_confirmed", method: "PATCH", path: `${taskPath}/spec`, statuses: [200], min: 1 },
    { name: "source_searched", method: "POST", path: `${taskPath}/model-source-searches`, statuses: [200], min: 1, max: 1 },
    { name: "source_selected", method: "POST", path: `${taskPath}/model-source-selections`, statuses: [201], min: 1, max: 1 },
    { name: "source_bound", method: "POST", path: `${taskPath}/model-source-resolutions/${encodeURIComponent(binding.resolution_id)}/bind`, statuses: [202], min: 1, max: 1 },
    { name: "plan_created", method: "POST", path: `${taskPath}/training-plans`, statuses: [201], min: 1, max: 1 },
    { name: "plan_approved", method: "POST", path: `${taskPath}/training-plans/${encodeURIComponent(plan.training_plan_revision_id)}/decisions`, statuses: [200], min: 1, max: 1 },
    { name: "resource_checked", method: "POST", path: `${taskPath}/resource-feasibility-checks`, statuses: [201], min: 1, max: 2 },
  ];
  if (manualMapping) contracts.splice(5, 0, {
    name: "analysis_mapped",
    method: "POST",
    path: `${taskPath}/repository-analyses/${encodeURIComponent(analysis.base_analysis_id)}/manual-mappings`,
    statuses: [201],
    min: 1,
    max: 1,
  });
  return contracts;
}

function assertRequiredRoutes(network, contracts) {
  const results = {};
  for (const contract of contracts) {
    const matches = network.filter((item) => item.kind === "response" && item.method === contract.method && item.path === contract.path);
    const valid = matches.filter((item) => contract.statuses.includes(item.status));
    const max = contract.max ?? Number.POSITIVE_INFINITY;
    if (matches.length !== valid.length || valid.length < contract.min || valid.length > max) {
      throw new Error(`${contract.name} route contract failed: observed ${JSON.stringify(matches)}`);
    }
    results[contract.name] = valid.map((item) => ({ method: item.method, path: item.path, status: item.status }));
  }
  const allowed = new Set(contracts.map((item) => `${item.method} ${item.path}`));
  const unexpected = network.filter((item) => item.kind === "response" && MUTATING_METHODS.has(item.method) && !allowed.has(`${item.method} ${item.path}`));
  if (unexpected.length) throw new Error(`unexpected mutating browser routes: ${JSON.stringify(unexpected)}`);
  return results;
}

async function responseJson(response, label) {
  let value;
  try { value = await response.json(); }
  catch (_error) { throw new Error(`${label} did not return JSON`); }
  if (!response.ok()) throw new Error(`${label} failed with HTTP ${response.status()}: ${JSON.stringify(value)}`);
  return value;
}

async function waitForUiResponse(page, { method, path: expectedPath, statuses, timeout }, action) {
  const waiter = page.waitForResponse((response) => {
    const request = response.request();
    return request.method() === method && new URL(response.url()).pathname === expectedPath;
  }, { timeout });
  await action();
  const response = await waiter;
  if (!statuses.includes(response.status())) {
    let responseBody = "";
    try { responseBody = (await response.text()).slice(0, 2000); }
    catch (_ignored) { /* best effort diagnostic only */ }
    throw new Error(`${method} ${expectedPath} returned HTTP ${response.status()}${responseBody ? `: ${responseBody}` : ""}`);
  }
  return response;
}

async function getTaskProjection(page, baseUrl, taskId) {
  const response = await page.request.get(`${baseUrl}/tasks/${encodeURIComponent(taskId)}`);
  return requireRecord((await responseJson(response, "task projection")).task, "task projection");
}

async function waitForTaskProjection(page, baseUrl, taskId, predicate, { timeout, label }) {
  const deadline = Date.now() + timeout;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await getTaskProjection(page, baseUrl, taskId);
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
  throw new Error(`${label} timed out; last task state: ${JSON.stringify(latest?.control || latest?.status || null)}`);
}

async function ensurePlanWorkspaceOpen(page) {
  const open = await page.locator("body").getAttribute("data-workspace") === "open";
  if (!open) await page.locator("#workspaceToggleButton:visible").click();
  await page.waitForFunction(() => document.body.dataset.workspace === "open");
  const planTab = page.locator('#contextTabs [data-context="plan"]');
  if (!(await planTab.getAttribute("class") || "").includes("active")) await planTab.click();
  await page.locator('[data-context-panel="plan"]:not([hidden])').waitFor({ state: "visible" });
}

async function waitForTaskShell(page, taskId) {
  await page.waitForFunction(
    (expected) => new URL(window.location.href).searchParams.get("task") === expected
      && document.querySelector("#taskTitle")?.textContent?.trim(),
    taskId,
    { timeout: 20_000 },
  );
}

async function waitForTask(page, taskId) {
  await waitForTaskShell(page, taskId);
  await page.waitForFunction(
    () => document.querySelector("#resultCard")?.hidden === false,
    { timeout: 20_000 },
  );
}

async function openTask(page, baseUrl, taskId) {
  await page.goto(`${baseUrl}/app?task=${encodeURIComponent(taskId)}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await waitForTask(page, taskId);
}

async function openTaskShell(page, baseUrl, taskId) {
  await page.goto(`${baseUrl}/app?task=${encodeURIComponent(taskId)}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await waitForTaskShell(page, taskId);
}

async function observeFamily(page, baseUrl, family, journey, mobile) {
  await openTask(page, baseUrl, journey.task_id);
  if (mobile) {
    await page.locator("#mobileResultButton").click();
    await page.locator("#evaluationEvidenceCard").waitFor({ state: "visible" });
  } else {
    await page.locator('[data-context="evaluation"]').click();
  }
  const evaluationText = (await page.locator("#evaluationEvidenceCard").innerText()).trim();
  await page.locator('[data-context="artifacts"]').click();
  await page.locator("#artifactBundleCard").waitFor({ state: "visible" });
  const bundleText = (await page.locator("#artifactBundleCard").innerText()).trim();
  if (!bundleText.includes(journey.artifact_bundle_id)) {
    throw new Error(`${family} bundle id is not visible in the product UI`);
  }
  return {
    task_id: journey.task_id,
    run_id: journey.run_id,
    evaluation_report_id: journey.evaluation_report_id,
    inference_check_id: journey.inference_check_id,
    artifact_bundle_id: journey.artifact_bundle_id,
    evaluation_text: evaluationText,
    bundle_text: bundleText,
  };
}

async function collectRun(browser, viewport, args, journeys) {
  const runDirectory = path.join(args["output-dir"], viewport.name);
  fs.mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
  const network = [];
  const consoleRecords = [];
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1 });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  const page = await context.newPage();
  page.on("response", (response) => {
    const request = response.request();
    if (request.url().startsWith(args["base-url"])) network.push(safeRequestRecord("response", request, { status: response.status() }));
  });
  page.on("requestfailed", (request) => network.push(safeRequestRecord("requestfailed", request, { error: request.failure()?.errorText || "unknown" })));
  page.on("console", (message) => {
    consoleRecords.push({ kind: "console", level: message.type(), text: message.text().slice(0, 2000) });
  });
  page.on("pageerror", (error) => consoleRecords.push({ kind: "pageerror", level: "error", text: String(error).slice(0, 2000) }));

  const first = journeys.image.task_id;
  const second = journeys.tabular.task_id;
  const firstDraft = `controlled-first-${args["producer-run-id"]}-${viewport.name}`;
  const secondDraft = `controlled-second-${args["producer-run-id"]}-${viewport.name}`;
  const startUrl = `${args["base-url"]}/app?task=${encodeURIComponent(first)}`;
  await openTask(page, args["base-url"], first);
  await page.locator("#messageInput").fill(firstDraft);
  await openTask(page, args["base-url"], second);
  await page.locator("#messageInput").fill(secondDraft);
  await openTask(page, args["base-url"], first);
  const firstRestored = (await page.locator("#messageInput").inputValue()) === firstDraft;
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForTask(page, first);
  const firstSurvivedReload = (await page.locator("#messageInput").inputValue()) === firstDraft;
  await openTask(page, args["base-url"], second);
  const secondRestored = (await page.locator("#messageInput").inputValue()) === secondDraft;

  const familyObservations = {};
  for (const family of FAMILIES) {
    familyObservations[family] = await observeFamily(page, args["base-url"], family, journeys[family], viewport.name === "mobile");
  }
  let contextReachable = false;
  let resultsReachable = false;
  if (viewport.name === "mobile") {
    await page.locator('[data-context="plan"]').click();
    contextReachable = await page.locator('[data-context-panel="plan"]').isVisible();
    await page.locator('[data-context="evaluation"]').click();
    resultsReachable = await page.locator("#evaluationEvidenceCard").isVisible();
  } else {
    await page.locator('[data-context="plan"]').click();
    contextReachable = await page.locator('[data-context-panel="plan"]').isVisible();
    await page.locator('[data-context="evaluation"]').click();
    resultsReachable = await page.locator("#evaluationEvidenceCard").isVisible();
  }
  const targetSelectors = viewport.name === "mobile"
    ? ["#closeInspectorButton", '[data-context="evaluation"]', '[data-context="artifacts"]']
    : ["#newTaskButton", "#messageInput", "#sendButton"];
  const measurements = await page.evaluate((selectors) => ({
    horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
    primary_targets: selectors.map((selector) => {
      const bounds = document.querySelector(selector)?.getBoundingClientRect();
      return { selector, width: bounds?.width || 0, height: bounds?.height || 0 };
    }),
  }), targetSelectors);
  measurements.context_reachable = contextReachable;
  measurements.results_reachable = resultsReachable;

  const screenshotPath = path.join(runDirectory, "final.png");
  const networkPath = path.join(runDirectory, "network.ndjson");
  const consolePath = path.join(runDirectory, "console.ndjson");
  const tracePath = path.join(runDirectory, "trace.zip");
  const endUrl = page.url();
  await page.screenshot({ path: screenshotPath, fullPage: false });
  await context.tracing.stop({ path: tracePath });
  await context.close();
  writeNdjson(networkPath, network);
  writeNdjson(consolePath, consoleRecords);
  const consoleErrorCount = consoleRecords.filter((item) => item.level === "error" || item.kind === "pageerror").length;
  const requestFailureCount = network.filter((item) => item.kind === "requestfailed").length;
  const httpErrorCount = network.filter((item) => item.kind === "response" && item.status >= 400).length;
  return {
    viewport: { width: viewport.width, height: viewport.height },
    start_url: startUrl,
    end_url: endUrl,
    drafts: {
      first_task_id: first,
      second_task_id: second,
      first_value_sha256: digestText(firstDraft),
      second_value_sha256: digestText(secondDraft),
      first_restored: firstRestored,
      first_survived_reload: firstSurvivedReload,
      second_restored: secondRestored,
    },
    families: familyObservations,
    measurements,
    console_error_count: consoleErrorCount,
    request_failure_count: requestFailureCount,
    http_error_count: httpErrorCount,
  };
}

function uiFailure(assertions) {
  return Object.entries(assertions).filter(([, passed]) => !passed).map(([name]) => name);
}

async function collectUiRun(browser, viewport, args) {
  const runDirectory = path.join(args["output-dir"], viewport.name);
  fs.mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
  const network = [];
  const consoleRecords = [];
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1 });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  const page = await context.newPage();
  page.on("response", (response) => {
    const request = response.request();
    if (request.url().startsWith(args["base-url"])) network.push(safeRequestRecord("response", request, { status: response.status() }));
  });
  page.on("requestfailed", (request) => network.push(safeRequestRecord("requestfailed", request, { error: request.failure()?.errorText || "unknown" })));
  page.on("console", (message) => consoleRecords.push({ kind: "console", level: message.type(), text: message.text().slice(0, 2000) }));
  page.on("pageerror", (error) => consoleRecords.push({ kind: "pageerror", level: "error", text: String(error).slice(0, 2000) }));

  const clarificationTaskId = args["clarification-task-id"];
  const blockedTaskId = args["blocked-task-id"];
  await openTaskShell(page, args["base-url"], clarificationTaskId);
  await page.locator("#agentCheckpoint:not([hidden])").waitFor({ state: "visible", timeout: 20_000 });
  await page.waitForTimeout(700);
  const clarification = await page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      const bounds = element?.getBoundingClientRect();
      return element && bounds ? {
        x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
        visible: bounds.width > 0 && bounds.height > 0 && bounds.bottom > 0 && bounds.top < window.innerHeight,
      } : null;
    };
    return {
      title: document.querySelector("#taskTitle")?.textContent?.trim() || "",
      stage: document.querySelector("#taskEyebrow")?.textContent?.trim() || "",
      question: document.querySelector("#agentCheckpointTitle")?.textContent?.trim() || "",
      quick_options: [...document.querySelectorAll("#taskSpecQuickReplies button")].map((button) => button.innerText.trim()),
      workspace_state: document.body.dataset.workspace,
      checkpoint: box("#agentCheckpoint"),
      composer: box("#composerForm"),
      horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
    };
  });
  await page.screenshot({ path: path.join(runDirectory, "clarification.png"), fullPage: false });

  await openTaskShell(page, args["base-url"], blockedTaskId);
  await page.locator(".tool-history").waitFor({ state: "visible", timeout: 20_000 });
  await page.locator('.tool-card[data-status="failed"]').waitFor({ state: "visible", timeout: 20_000 });
  const blocker = await page.evaluate(() => ({
    initial_workspace_state: document.body.dataset.workspace,
    completed_tool_groups: document.querySelectorAll(".tool-history").length,
    completed_tool_rows: document.querySelectorAll(".tool-history-list > div").length,
    completed_tool_group_open: document.querySelector(".tool-history")?.open === true,
    failed_tools: document.querySelectorAll('.tool-card[data-status="failed"]').length,
    failed_tools_inside_completed_group: document.querySelectorAll('.tool-history .tool-card[data-status="failed"]').length,
    checkpoint_detail_cards: document.querySelectorAll("#agentCheckpoint .inspector-card, #agentCheckpoint .task-spec-card").length,
    resource_card_inside_checkpoint: Boolean(document.querySelector("#agentCheckpoint #resourceFeasibilityCard")),
    checkpoint_height: document.querySelector("#agentCheckpoint")?.getBoundingClientRect().height || 0,
    checkpoint_title: document.querySelector("#agentCheckpointTitle")?.textContent?.trim() || "",
  }));

  const docked = viewport.width >= 1184;
  let desktopAutoOpened = false;
  if (docked) {
    desktopAutoOpened = await page.waitForFunction(() => document.body.dataset.workspace === "open", null, { timeout: 2_000 }).then(() => true).catch(() => false);
    if (!desktopAutoOpened) await page.locator("#agentCheckpointWorkspaceButton").click();
  } else {
    if (await page.locator("body").getAttribute("data-workspace") === "open") {
      await page.locator("#closeInspectorButton").click();
      await page.waitForFunction(() => document.body.dataset.workspace === "closed");
    }
    await page.locator("#agentCheckpointWorkspaceButton").click();
  }
  await page.waitForFunction(() => document.body.dataset.workspace === "open" && document.querySelector(".inspector")?.dataset.open === "true");
  await page.waitForTimeout(850);
  const workspace = await page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      const bounds = element?.getBoundingClientRect();
      return element && bounds ? { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height, right: bounds.right, bottom: bounds.bottom } : null;
    };
    const inspector = document.querySelector(".inspector");
    const main = document.querySelector(".conversation-main");
    const nav = document.querySelector(".mobile-view-nav");
    const resource = document.querySelector("#resourceFeasibilityCard")?.getBoundingClientRect();
    return {
      state: document.body.dataset.workspace,
      sidebar: box(".sidebar"),
      main: box(".conversation-main"),
      inspector: box(".inspector"),
      scrim: box(".inspector-scrim"),
      resource_card: box("#resourceFeasibilityCard"),
      resource_visible_height: resource ? Math.max(0, Math.min(resource.bottom, window.innerHeight) - Math.max(resource.top, 0)) : 0,
      scrim_display: getComputedStyle(document.querySelector(".inspector-scrim")).display,
      nav_display: getComputedStyle(nav).display,
      main_inert: main.inert,
      nav_inert: nav.inert,
      role: inspector.getAttribute("role"),
      aria_modal: inspector.getAttribute("aria-modal"),
      active_element: document.activeElement?.id || document.activeElement?.className || document.activeElement?.tagName,
      horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
    };
  });
  await page.screenshot({ path: path.join(runDirectory, "workspace.png"), fullPage: false });

  await page.locator("#closeInspectorButton").click();
  await page.waitForFunction(() => document.body.dataset.workspace === "closed");
  await page.waitForTimeout(100);
  const closeState = await page.evaluate(() => ({
    workspace_state: document.body.dataset.workspace,
    active_element: document.activeElement?.id || document.activeElement?.className || document.activeElement?.tagName,
    nav_display: getComputedStyle(document.querySelector(".mobile-view-nav")).display,
    horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
  }));

  let mobileNavigation = null;
  if (viewport.name === "mobile") {
    await page.locator("#mobileContextButton").click();
    await page.waitForFunction(() => document.body.dataset.workspace === "open");
    await page.waitForTimeout(100);
    const contextOpen = await page.evaluate(() => ({
      nav_display: getComputedStyle(document.querySelector(".mobile-view-nav")).display,
      active_context: document.querySelector("[data-context].active")?.dataset.context || "",
      focus: document.activeElement?.id || "",
    }));
    await page.locator("#closeInspectorButton").click();
    await page.waitForFunction(() => document.body.dataset.workspace === "closed");
    await page.waitForTimeout(100);
    const contextCloseFocus = await page.evaluate(() => document.activeElement?.id || "");
    await page.locator("#mobileResultButton").click();
    await page.waitForFunction(() => document.body.dataset.workspace === "open");
    await page.waitForTimeout(100);
    const resultOpen = await page.evaluate(() => ({
      nav_display: getComputedStyle(document.querySelector(".mobile-view-nav")).display,
      active_context: document.querySelector("[data-context].active")?.dataset.context || "",
      focus: document.activeElement?.id || "",
    }));
    await page.locator("#closeInspectorButton").click();
    await page.waitForFunction(() => document.body.dataset.workspace === "closed");
    await page.waitForTimeout(100);
    const resultCloseFocus = await page.evaluate(() => document.activeElement?.id || "");
    mobileNavigation = { context_open: contextOpen, context_close_focus: contextCloseFocus, result_open: resultOpen, result_close_focus: resultCloseFocus };
  }

  await page.screenshot({ path: path.join(runDirectory, "final.png"), fullPage: false });
  const networkPath = path.join(runDirectory, "network.ndjson");
  const consolePath = path.join(runDirectory, "console.ndjson");
  const tracePath = path.join(runDirectory, "trace.zip");
  await context.tracing.stop({ path: tracePath });
  await context.close();
  writeNdjson(networkPath, network);
  writeNdjson(consolePath, consoleRecords);
  const consoleErrorCount = consoleRecords.filter((item) => item.level === "error" || item.kind === "pageerror").length;
  const requestFailureCount = network.filter((item) => item.kind === "requestfailed").length;
  const httpErrorCount = network.filter((item) => item.kind === "response" && item.status >= 400).length;

  const assertions = {
    clarification_clear: Boolean(clarification.title && clarification.stage && clarification.question && clarification.quick_options.length >= 3 && clarification.checkpoint?.visible && clarification.composer?.visible),
    clarification_has_no_horizontal_overflow: clarification.horizontal_overflow_px === 0,
    completed_tools_are_compacted: blocker.completed_tool_groups >= 1 && blocker.completed_tool_rows >= 3 && blocker.completed_tool_group_open === false,
    blocker_is_independent: blocker.failed_tools >= 1 && blocker.failed_tools_inside_completed_group === 0 && blocker.checkpoint_detail_cards === 0 && blocker.resource_card_inside_checkpoint === false && blocker.checkpoint_height <= 240,
    workspace_has_no_horizontal_overflow: workspace.horizontal_overflow_px === 0 && closeState.horizontal_overflow_px === 0,
    workspace_focus_restored: closeState.active_element === (docked ? "workspaceToggleButton" : "agentCheckpointWorkspaceButton"),
    current_workspace_object_is_visible: workspace.resource_visible_height >= 120,
    console_has_no_errors: consoleErrorCount === 0,
    network_has_no_failures: requestFailureCount === 0 && httpErrorCount === 0,
  };
  if (viewport.name === "desktop") {
    assertions.desktop_workspace_auto_opens = desktopAutoOpened;
    assertions.desktop_three_columns_coexist = workspace.sidebar?.width === 244 && workspace.main?.width >= 600 && workspace.inspector?.width >= 340 && Math.abs(workspace.main.right - workspace.inspector.x) < 1;
    assertions.desktop_workspace_is_non_modal = workspace.scrim_display === "none" && workspace.main_inert === false && workspace.role === null;
  } else {
    assertions.overlay_is_modal = workspace.scrim_display !== "none" && workspace.main_inert === true && workspace.role === "dialog" && workspace.aria_modal === "true";
    assertions.overlay_reaches_right_edge = Math.abs(workspace.inspector.right - viewport.width) < 1;
  }
  if (viewport.name === "mobile") {
    assertions.mobile_workspace_is_full_screen = Math.abs(workspace.inspector.x) < 1 && Math.abs(workspace.inspector.y) < 1 && Math.abs(workspace.inspector.width - viewport.width) < 1 && Math.abs(workspace.inspector.height - viewport.height) < 1;
    assertions.mobile_nav_strategy_is_consistent = workspace.nav_display === "none" && closeState.nav_display === "grid" && mobileNavigation?.context_open.nav_display === "none" && mobileNavigation.context_open.focus === "closeInspectorButton" && mobileNavigation.context_close_focus === "mobileContextButton" && mobileNavigation.result_open.nav_display === "none" && mobileNavigation.result_open.active_context === "evaluation" && mobileNavigation.result_close_focus === "mobileResultButton";
  }

  return {
    viewport: { width: viewport.width, height: viewport.height },
    clarification_task_id: clarificationTaskId,
    blocked_task_id: blockedTaskId,
    clarification,
    blocker,
    workspace,
    close_state: closeState,
    mobile_navigation: mobileNavigation,
    assertions,
    failures: uiFailure(assertions),
    console_error_count: consoleErrorCount,
    request_failure_count: requestFailureCount,
    http_error_count: httpErrorCount,
  };
}

async function getTaskCollectionCounts(page, baseUrl, taskId) {
  const taskPath = `${baseUrl}/tasks/${encodeURIComponent(taskId)}`;
  const endpoints = [
    ["searches", "model-source-searches"],
    ["resolutions", "model-source-resolutions"],
    ["bindings", "model-bindings"],
  ];
  const result = {};
  for (const [field, endpoint] of endpoints) {
    const response = await page.request.get(`${taskPath}/${endpoint}`);
    const payload = await responseJson(response, endpoint);
    if (!Array.isArray(payload[field])) throw new Error(`${endpoint} did not return ${field}`);
    result[field] = payload[field].length;
  }
  return result;
}

function activeResourceBlocker(task) {
  return (task?.resource_feasibility?.blockers || []).find((item) => item?.active !== false && RESOURCE_STAGES.has(item?.stage)) || null;
}

async function collectV3Journey(browser, args) {
  const runDirectory = path.join(args["output-dir"], "v3-journey");
  fs.mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
  const network = [];
  const consoleRecords = [];
  const timeout = args["timeout-ms"];
  const context = await browser.newContext({
    viewport: { width: V3_JOURNEY_VIEWPORT.width, height: V3_JOURNEY_VIEWPORT.height },
    deviceScaleFactor: 1,
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  const page = await context.newPage();
  page.on("response", (response) => {
    const request = response.request();
    if (request.url().startsWith(args["base-url"])) network.push(safeRequestRecord("response", request, { status: response.status() }));
  });
  page.on("requestfailed", (request) => network.push(safeRequestRecord("requestfailed", request, { error: request.failure()?.errorText || "unknown" })));
  page.on("console", (message) => consoleRecords.push({ kind: "console", level: message.type(), text: message.text().slice(0, 2000) }));
  page.on("pageerror", (error) => consoleRecords.push({ kind: "pageerror", level: "error", text: String(error).slice(0, 2000) }));

  const networkPath = path.join(runDirectory, "network.ndjson");
  const consolePath = path.join(runDirectory, "console.ndjson");
  const tracePath = path.join(runDirectory, "trace.zip");
  const failurePath = path.join(runDirectory, "failure.png");
  let traceStopped = false;
  let contextClosed = false;
  let logsWritten = false;
  let taskId = null;
  let partial = {};

  try {
    await page.goto(`${args["base-url"]}/app`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.locator("#messageInput").waitFor({ state: "visible", timeout: 20_000 });
    if (await page.locator("#newTaskButton:visible").count()) await page.locator("#newTaskButton:visible").click();
    await page.locator("#messageInput").fill(args["business-goal"]);
    const createResponse = await waitForUiResponse(page, {
      method: "POST", path: "/tasks", statuses: [201], timeout,
    }, () => page.locator("#sendButton").click());
    const created = await responseJson(createResponse, "task creation");
    taskId = requireText(created.task?.task_id, "created task id");
    partial.task_id = taskId;
    await waitForTaskShell(page, taskId);

    await page.locator("#editTaskSpecButton:visible").click();
    await page.locator("#decisionDialog[open]").waitFor({ state: "visible", timeout: 20_000 });
    const familyInput = page.locator(`input[name="task-spec-family"][value="${args["task-family"]}"]`);
    if (!(await familyInput.count())) {
      const observed = await page.locator('input[name="task-spec-family"]').evaluateAll((items) => items.map((item) => item.value));
      throw new Error(`task family ${args["task-family"]} is not available in the UI: ${JSON.stringify(observed)}`);
    }
    await familyInput.check();
    const taskPath = `/tasks/${encodeURIComponent(taskId)}`;
    const specResponse = await waitForUiResponse(page, {
      method: "PATCH", path: `${taskPath}/spec`, statuses: [200], timeout,
    }, () => page.locator("#dialogActions .allow").click());
    const confirmed = await responseJson(specResponse, "task spec confirmation");
    if (confirmed.task?.capability_decision?.status !== "resolved") throw new Error("task spec did not become resolved after UI confirmation");
    await page.locator("#decisionDialog").waitFor({ state: "hidden", timeout });
    await page.waitForFunction(() => document.querySelector("#taskSpecStatus")?.textContent?.trim() === "已确认", null, { timeout: 20_000 });

    await ensurePlanWorkspaceOpen(page);
    const providerSelectors = { github: "#searchGithubProvider", huggingface: "#searchHfProvider" };
    for (const [provider, selector] of Object.entries(providerSelectors)) {
      const input = page.locator(selector);
      if (provider === args.provider) await input.check();
      else await input.uncheck();
    }
    await page.locator("#modelSourceSearchInput").fill(args.query);
    const searchResponse = await waitForUiResponse(page, {
      method: "POST", path: `${taskPath}/model-source-searches`, statuses: [200], timeout,
    }, () => page.locator("#modelSourceSearchButton").click());
    const search = await responseJson(searchResponse, "model source search");
    const candidate = (search.candidates || []).find((item) => item.provider === args.provider && normalizeRepository(item.repository) === normalizeRepository(args.repository));
    if (!candidate) throw new Error(`official search did not return ${args.provider}:${args.repository}`);
    if (String(candidate.requested_revision) !== String(args.revision)) {
      throw new Error(`catalog candidate revision ${candidate.requested_revision} did not match --revision ${args.revision}`);
    }
    requireText(candidate.candidate_id, "candidate id");
    partial.search_id = search.search_id;
    partial.candidate_id = candidate.candidate_id;

    await ensurePlanWorkspaceOpen(page);
    const candidateButton = page.locator(`#modelSourceCandidates button[data-candidate-id="${candidate.candidate_id}"]`);
    await candidateButton.waitFor({ state: "visible", timeout: 20_000 });
    await candidateButton.click();
    await page.locator("#decisionDialog[open]").waitFor({ state: "visible", timeout: 10_000 });
    const selectionResponse = await waitForUiResponse(page, {
      method: "POST", path: `${taskPath}/model-source-selections`, statuses: [201], timeout,
    }, () => page.locator("#dialogActions .allow").click());
    const selection = await responseJson(selectionResponse, "model source selection");
    await page.locator("#decisionDialog").waitFor({ state: "hidden", timeout });
    const resolution = requireRecord(selection.resolution, "source resolution");
    if (resolution.provider !== args.provider || normalizeRepository(resolution.repository) !== normalizeRepository(args.repository)) throw new Error("source resolution identity drifted from the confirmed candidate");
    if (String(resolution.requested_revision) !== String(args.revision)) throw new Error("source resolution revision drifted from the confirmed candidate");
    requireText(resolution.resolved_commit, "resolved commit", /^[0-9a-f]{40}$/);
    partial.resolution_id = resolution.resolution_id;

    await ensurePlanWorkspaceOpen(page);
    await page.locator("#bindModelSourceButton:visible").waitFor({ state: "visible", timeout: 20_000 });
    await page.locator("#bindModelSourceButton:visible").click();
    await page.locator("#decisionDialog[open]").waitFor({ state: "visible", timeout: 10_000 });
    const bindPath = `${taskPath}/model-source-resolutions/${encodeURIComponent(resolution.resolution_id)}/bind`;
    const bindResponse = await waitForUiResponse(page, {
      method: "POST", path: bindPath, statuses: [202], timeout,
    }, () => page.locator("#dialogActions .allow").click());
    const queued = await responseJson(bindResponse, "source binding");
    await page.locator("#decisionDialog").waitFor({ state: "hidden", timeout });
    partial.binding_attempt_id = queued.binding_attempt?.attempt?.attempt_id || null;

    let task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => {
      const status = item.repository_analysis?.status;
      const attemptStatus = item.repository_analysis_attempt?.current_state?.status || item.model_binding_attempt?.current_state?.status;
      return ["complete", "needs_input", "needs_manual_mapping", "blocked"].includes(status) || ["failed", "cancelled"].includes(attemptStatus);
    }, { timeout, label: "source binding and repository analysis" });
    const attemptStatus = task.repository_analysis_attempt?.current_state?.status || task.model_binding_attempt?.current_state?.status;
    if (!task.model_binding && ["failed", "cancelled"].includes(attemptStatus)) throw new Error(`source binding attempt ended as ${attemptStatus}`);

    let manualMapping = false;
    let baseAnalysisId = task.repository_analysis?.analysis_id || null;
    if (["needs_input", "needs_manual_mapping"].includes(task.repository_analysis?.status)) {
      if (!args.entrypoint) throw new Error("repository analysis requires manual mapping but --entrypoint was not provided");
      manualMapping = true;
      await ensurePlanWorkspaceOpen(page);
      await page.locator("#repositoryManualMapping:visible").waitFor({ state: "visible", timeout: 20_000 });
      await page.locator("#repositoryManualEntrypointInput").fill(args.entrypoint);
      if (args["dataset-argument"]) await page.locator("#repositoryDatasetArgumentInput").fill(args["dataset-argument"]);
      const mappingPath = `${taskPath}/repository-analyses/${encodeURIComponent(baseAnalysisId)}/manual-mappings`;
      const mappingResponse = await waitForUiResponse(page, {
        method: "POST", path: mappingPath, statuses: [201], timeout,
      }, () => page.locator("#applyRepositoryManualMappingButton").click());
      await responseJson(mappingResponse, "repository manual mapping");
      task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => item.repository_analysis?.status === "complete", { timeout, label: "manual repository analysis revision" });
    }
    if (task.repository_analysis?.status !== "complete") throw new Error(`repository analysis ended as ${task.repository_analysis?.status || "missing"}`);
    if (args.entrypoint && !(task.repository_analysis.training_entrypoints || []).some((item) => item.path === args.entrypoint)) throw new Error(`analysis did not confirm requested entrypoint ${args.entrypoint}`);
    if (args.metric && !(task.repository_analysis.metrics || []).some((item) => item.name === args.metric)) throw new Error(`analysis did not confirm requested metric ${args.metric}`);

    await ensurePlanWorkspaceOpen(page);
    await page.locator("#createTrainingPlanButton:visible:not([disabled])").waitFor({ state: "visible", timeout: 20_000 });
    const planCreateResponse = await waitForUiResponse(page, {
      method: "POST", path: `${taskPath}/training-plans`, statuses: [201], timeout,
    }, () => page.locator("#createTrainingPlanButton:visible").click());
    await responseJson(planCreateResponse, "training plan creation");
    task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => Boolean(item.training_plan?.plan), { timeout, label: "training plan projection" });
    const plan = requireRecord(task.training_plan.plan, "training plan");
    if (args.entrypoint && plan.entrypoint?.argv?.[1] !== args.entrypoint) throw new Error("training plan entrypoint drifted from the confirmed analysis");
    if (args.metric && !(plan.evaluation?.metrics || []).includes(args.metric)) throw new Error("training plan metric drifted from the confirmed analysis");

    await ensurePlanWorkspaceOpen(page);
    await page.locator("#approveTrainingPlanButton:visible").waitFor({ state: "visible", timeout: 20_000 });
    await page.locator("#approveTrainingPlanButton:visible").click();
    await page.locator("#decisionDialog[open]").waitFor({ state: "visible", timeout: 10_000 });
    const approvalPath = `${taskPath}/training-plans/${encodeURIComponent(plan.training_plan_revision_id)}/decisions`;
    const approvalResponse = await waitForUiResponse(page, {
      method: "POST", path: approvalPath, statuses: [200], timeout,
    }, () => page.locator("#dialogActions .allow").click());
    await responseJson(approvalResponse, "training plan approval");
    await page.locator("#decisionDialog").waitFor({ state: "hidden", timeout });
    task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => item.training_plan?.effective_status === "approved" && item.training_plan?.latest_approval?.decision === "approve", { timeout, label: "training plan approval projection" });

    await ensurePlanWorkspaceOpen(page);
    await page.locator("#checkResourceFeasibilityButton:visible").waitFor({ state: "visible", timeout: 20_000 });
    const resourcePath = `${taskPath}/resource-feasibility-checks`;
    const firstResourceResponse = await waitForUiResponse(page, {
      method: "POST", path: resourcePath, statuses: [201], timeout,
    }, () => page.locator("#checkResourceFeasibilityButton:visible").click());
    await responseJson(firstResourceResponse, "resource feasibility check");
    task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => Boolean(item.resource_feasibility?.resource_probe) && Boolean(activeResourceBlocker(item) || item.resource_feasibility?.resource_fit_report), { timeout, label: "resource feasibility projection" });
    let blocker = activeResourceBlocker(task);
    let baseImageDigestUsed = false;
    if (blocker?.details?.detector === "base_image_digest_validator" && args["base-image-digest"]) {
      await ensurePlanWorkspaceOpen(page);
      await page.locator("#baseImageDigestInput:visible").fill(args["base-image-digest"]);
      const retryResponse = await waitForUiResponse(page, {
        method: "POST", path: resourcePath, statuses: [201], timeout,
      }, () => page.locator("#checkResourceFeasibilityButton:visible").click());
      await responseJson(retryResponse, "resource feasibility retry");
      baseImageDigestUsed = true;
      const previousProbeId = task.resource_feasibility.resource_probe.resource_probe_id;
      task = await waitForTaskProjection(page, args["base-url"], taskId, (item) => item.resource_feasibility?.resource_probe?.resource_probe_id !== previousProbeId && Boolean(activeResourceBlocker(item) || item.resource_feasibility?.resource_fit_report), { timeout, label: "resource feasibility retry projection" });
      blocker = activeResourceBlocker(task);
    }
    if (!blocker) throw new Error("V3 journey requires a typed active resource blocker but none was produced");

    const beforeReload = snapshotV3Lineage(task);
    if (beforeReload.resolution.id !== resolution.resolution_id) throw new Error("current binding does not reference the confirmed source resolution");
    if (beforeReload.resolution.requested_revision !== String(args.revision)) throw new Error("current binding requested revision drifted");
    if (beforeReload.plan.digest !== beforeReload.approval.plan_digest) throw new Error("approval is not bound to the exact current plan digest");
    const countsBeforeReload = await getTaskCollectionCounts(page, args["base-url"], taskId);
    await page.screenshot({ path: path.join(runDirectory, "before-reload.png"), fullPage: false });
    const mutatingResponsesBeforeReload = network.filter((item) => item.kind === "response" && MUTATING_METHODS.has(item.method)).length;

    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await waitForTaskShell(page, taskId);
    await page.waitForFunction(() => document.querySelector("#trainingPlanFacts")?.textContent?.includes("Plan Digest"), null, { timeout: 20_000 });
    const reloadedTask = await getTaskProjection(page, args["base-url"], taskId);
    const afterReload = snapshotV3Lineage(reloadedTask);
    const countsAfterReload = await getTaskCollectionCounts(page, args["base-url"], taskId);
    const mutatingResponsesAfterReload = network.filter((item) => item.kind === "response" && MUTATING_METHODS.has(item.method)).length;
    if (JSON.stringify(afterReload) !== JSON.stringify(beforeReload)) throw new Error("reload changed V3 lineage IDs or digests");
    if (JSON.stringify(countsAfterReload) !== JSON.stringify(countsBeforeReload)) throw new Error("reload created a duplicate search, resolution, or binding revision");
    if (mutatingResponsesAfterReload !== mutatingResponsesBeforeReload) throw new Error("reload emitted a mutating request");
    await page.screenshot({ path: path.join(runDirectory, "after-reload.png"), fullPage: false });

    const routeContracts = v3RequiredRouteContracts(taskId, {
      resolution_id: beforeReload.resolution.id,
    }, {
      base_analysis_id: baseAnalysisId,
    }, { training_plan_revision_id: beforeReload.plan.id }, { manualMapping });
    const requiredRoutes = assertRequiredRoutes(network, routeContracts);
    const consoleErrorCount = consoleRecords.filter((item) => item.level === "error" || item.kind === "pageerror").length;
    const requestFailureCount = network.filter((item) => item.kind === "requestfailed").length;
    const httpErrorCount = network.filter((item) => item.kind === "response" && item.status >= 400).length;
    if (consoleErrorCount || requestFailureCount || httpErrorCount) throw new Error(`browser diagnostics failed: console=${consoleErrorCount}, request=${requestFailureCount}, http=${httpErrorCount}`);

    await context.tracing.stop({ path: tracePath });
    traceStopped = true;
    writeNdjson(networkPath, network);
    writeNdjson(consolePath, consoleRecords);
    logsWritten = true;
    await context.close();
    contextClosed = true;
    return {
      viewport: { width: V3_JOURNEY_VIEWPORT.width, height: V3_JOURNEY_VIEWPORT.height },
      task_id: taskId,
      parameters: {
        provider: args.provider,
        query: args.query,
        repository: args.repository,
        revision: args.revision,
        task_family: args["task-family"],
        entrypoint: args.entrypoint || null,
        metric: args.metric || null,
        base_image_digest_supplied: args["base-image-digest"] || null,
        base_image_digest_used: baseImageDigestUsed,
      },
      source_search: { search_id: search.search_id, candidate_id: candidate.candidate_id },
      manual_mapping_applied: manualMapping,
      required_routes: requiredRoutes,
      lineage_before_reload: beforeReload,
      lineage_after_reload: afterReload,
      counts_before_reload: countsBeforeReload,
      counts_after_reload: countsAfterReload,
      reload_mutating_request_count: mutatingResponsesAfterReload - mutatingResponsesBeforeReload,
      console_error_count: consoleErrorCount,
      request_failure_count: requestFailureCount,
      http_error_count: httpErrorCount,
    };
  } catch (error) {
    partial.error = String(error?.stack || error);
    try { await page.screenshot({ path: failurePath, fullPage: false }); } catch (_ignored) { /* best effort evidence */ }
    if (!traceStopped) {
      try { await context.tracing.stop({ path: tracePath }); traceStopped = true; } catch (_ignored) { /* best effort evidence */ }
    }
    if (!logsWritten) {
      writeNdjson(networkPath, network);
      writeNdjson(consolePath, consoleRecords);
      logsWritten = true;
    }
    if (!contextClosed) {
      try { await context.close(); contextClosed = true; } catch (_ignored) { /* best effort cleanup */ }
    }
    error.v3JourneyPartial = partial;
    throw error;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!/^[0-9a-f]{40}$/.test(args["source-commit"])) throw new Error("source commit must be an immutable SHA");
  if (!/^evidence-/.test(args["producer-run-id"])) throw new Error("producer run id is invalid");
  if (!fs.existsSync(args.chrome)) throw new Error("system Chrome executable is missing");
  fs.mkdirSync(args["output-dir"], { recursive: false, mode: 0o700 });
  const browser = await chromium.launch({ executablePath: args.chrome, headless: true });
  try {
    if (args.mode === "current-ui") {
      const runs = [];
      for (const viewport of UI_VIEWPORTS) runs.push(await collectUiRun(browser, viewport, args));
      const report = {
        schema_version: "0.2-ui",
        mode: "current_ui",
        source_commit: args["source-commit"],
        producer_run_id: args["producer-run-id"],
        status: runs.every((run) => run.failures.length === 0) ? "passed" : "failed",
        runs,
      };
      const reportPath = path.join(args["output-dir"], "ui-browser-report.json");
      fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
      if (report.status !== "passed") throw new Error(`current UI browser acceptance failed; inspect ${reportPath}`);
    } else if (args.mode === "v3-journey") {
      const reportPath = path.join(args["output-dir"], "v3-browser-journey-report.json");
      let report;
      try {
        const journey = await collectV3Journey(browser, args);
        report = {
          schema_version: "0.1-v3-browser-journey",
          mode: "v3_journey",
          source_commit: args["source-commit"],
          producer_run_id: args["producer-run-id"],
          status: "passed",
          journey,
        };
      } catch (error) {
        report = {
          schema_version: "0.1-v3-browser-journey",
          mode: "v3_journey",
          source_commit: args["source-commit"],
          producer_run_id: args["producer-run-id"],
          status: "failed",
          error: String(error?.stack || error),
          partial: error?.v3JourneyPartial || null,
        };
      }
      fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
      if (report.status !== "passed") throw new Error(`V3 browser journey failed; inspect ${reportPath}`);
    } else {
      const journeyReport = JSON.parse(fs.readFileSync(args.journeys, "utf8"));
      if (journeyReport.status !== "passed" || journeyReport.mode !== "official_hf_fixed_commit") throw new Error("browser evidence requires the official HF three-family runtime");
      const journeys = journeyReport.journey_families;
      if (JSON.stringify(Object.keys(journeys)) !== JSON.stringify(FAMILIES)) throw new Error("journey families drifted");
      const runs = [];
      for (const viewport of LEGACY_VIEWPORTS) runs.push(await collectRun(browser, viewport, args, journeys));
      fs.writeFileSync(path.join(args["output-dir"], "browser-report.json"), `${JSON.stringify({ schema_version: "0.1", source_commit: args["source-commit"], producer_run_id: args["producer-run-id"], runs }, null, 2)}\n`, { flag: "wx" });
    }
  } finally {
    await browser.close();
  }
}

export {
  assertRequiredRoutes,
  normalizeRepository,
  parseArgs,
  snapshotV3Lineage,
  v3RequiredRouteContracts,
};

const invokedAsScript = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedAsScript) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
}
