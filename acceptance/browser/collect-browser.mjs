#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
const FAMILIES = ["image", "tabular", "audio"];

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || value === undefined) throw new Error(`invalid argument sequence near ${flag || "end"}`);
    values[flag.slice(2)] = value;
  }
  for (const key of ["base-url", "journeys", "output-dir", "source-commit", "producer-run-id", "chrome"]) {
    if (!values[key]) throw new Error(`missing --${key}`);
  }
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

async function waitForTask(page, taskId) {
  await page.waitForFunction(
    (expected) => new URL(window.location.href).searchParams.get("task") === expected
      && document.querySelector("#taskTitle")?.textContent?.trim(),
    taskId,
    { timeout: 20_000 },
  );
  await page.waitForFunction(
    () => document.querySelector("#resultCard")?.hidden === false,
    { timeout: 20_000 },
  );
}

async function openTask(page, baseUrl, taskId) {
  await page.goto(`${baseUrl}/app?task=${encodeURIComponent(taskId)}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await waitForTask(page, taskId);
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
    await page.locator("#mobileContextButton").click();
    contextReachable = await page.locator('[data-context-panel="capability"]').isVisible();
    await page.locator("#mobileResultButton").click();
    resultsReachable = await page.locator("#evaluationEvidenceCard").isVisible();
  } else {
    await page.locator('[data-context="capability"]').click();
    contextReachable = await page.locator('[data-context-panel="capability"]').isVisible();
    await page.locator('[data-context="evaluation"]').click();
    resultsReachable = await page.locator("#evaluationEvidenceCard").isVisible();
  }
  const targetSelectors = viewport.name === "mobile"
    ? ["#mobileConversationButton", "#mobileContextButton", "#mobileResultButton"]
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

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!/^[0-9a-f]{40}$/.test(args["source-commit"])) throw new Error("source commit must be an immutable SHA");
  if (!/^evidence-/.test(args["producer-run-id"])) throw new Error("producer run id is invalid");
  if (!fs.existsSync(args.chrome)) throw new Error("system Chrome executable is missing");
  const journeyReport = JSON.parse(fs.readFileSync(args.journeys, "utf8"));
  if (journeyReport.status !== "passed" || journeyReport.mode !== "official_hf_fixed_commit") throw new Error("browser evidence requires the official HF three-family runtime");
  const journeys = journeyReport.journey_families;
  if (JSON.stringify(Object.keys(journeys)) !== JSON.stringify(FAMILIES)) throw new Error("journey families drifted");
  fs.mkdirSync(args["output-dir"], { recursive: false, mode: 0o700 });
  const browser = await chromium.launch({ executablePath: args.chrome, headless: true });
  try {
    const runs = [];
    for (const viewport of VIEWPORTS) runs.push(await collectRun(browser, viewport, args, journeys));
    fs.writeFileSync(path.join(args["output-dir"], "browser-report.json"), `${JSON.stringify({ schema_version: "0.1", source_commit: args["source-commit"], producer_run_id: args["producer-run-id"], runs }, null, 2)}\n`, { flag: "wx" });
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
