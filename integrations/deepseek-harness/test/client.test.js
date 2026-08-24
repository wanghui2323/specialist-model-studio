import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, test } from "node:test";

import { ModelHarnessClient, publicProjection } from "../client.js";

const baseUrl = "http://127.0.0.1:8765";
const requests = [];
const originalFetch = globalThis.fetch;

beforeEach(() => {
  requests.length = 0;
  globalThis.fetch = async (url, options = {}) => {
    const requestUrl = new URL(url);
    const body = options.body || "";
    requests.push({
      method: options.method || "GET",
      url: `${requestUrl.pathname}${requestUrl.search}`,
      body,
      headers: Object.fromEntries(new Headers(options.headers || {}).entries()),
    });
    const isJson = new Headers(options.headers || {}).get("content-type") === "application/json";
    const value = requestUrl.pathname === "/recipes/digit-classification/template"
      ? { contract: { recipe: "digit-classification", task_id: "default", business_goal: "default" } }
      : requestUrl.pathname === "/tasks" && (options.method || "GET") === "POST"
        ? { task: { task_id: "real-task-123" } }
        : { ok: true, request_body: body && isJson ? JSON.parse(body) : null };
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});

after(() => {
  globalThis.fetch = originalFetch;
});

test("client exposes no global run-creation or strategy-write methods", () => {
  const client = new ModelHarnessClient(baseUrl);
  assert.equal(client.startRun, undefined);
  assert.equal(client.applyStrategy, undefined);
  assert.equal(typeof client.startTaskRun, "function");
  assert.equal(typeof client.applyTaskStrategy, "function");
  assert.equal(requests.length, 0);
});

test("task lifecycle methods preserve canonical task routes and confirmations", async () => {
  const client = new ModelHarnessClient(baseUrl);
  const created = await client.createTask("parts", "classify parts");
  assert.equal(created.task.task_id, "real-task-123");
  assert.equal(requests.at(-1).url, "/tasks");
  assert.equal(requests.at(-1).headers["x-model-harness-projection"], "agent-v1");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    name: "parts",
    business_goal: "classify parts",
  });

  await client.updateTaskSpec("real-task-123", {
    baseRevision: 1,
    selectedFamily: "image_classification",
    userNote: "confirmed by user",
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/spec");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    base_revision: 1,
    selected_family: "image_classification",
    confirm: true,
    user_note: "confirmed by user",
  });

  await client.configureContract("real-task-123", {
    accuracyMin: 0.82,
    macroF1Min: 0.78,
    worstClassRecallMin: 0.6,
    imageSize: 32,
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/contract");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    release_gates: {
      clean_test_accuracy_min: 0.82,
      clean_test_macro_f1_min: 0.78,
      clean_test_worst_class_recall_min: 0.6,
    },
    recipe_options: { image_size: 32 },
  });

  assert.throws(
    () => client.confirmContract("real-task-123", { data_authorized: true }),
    /three human confirmations/,
  );
  await client.confirmContract("real-task-123", {
    data_authorized: true,
    labels_reviewed: true,
    gates_reviewed: true,
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/confirm");

  await client.startTaskRun("real-task-123");
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/runs");
  assert.equal(requests.at(-1).method, "POST");

  await client.applyTaskStrategy("real-task-123", "parent-run", "balance", true);
  assert.equal(
    requests.at(-1).url,
    "/tasks/real-task-123/runs/parent-run/strategies/balance/apply",
  );

  await client.cancelTaskRun("real-task-123", "parent-run");
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/runs/parent-run/cancel");
});

test("conversation-native BYOM methods preserve revision, digest, and approval seams", async () => {
  const client = new ModelHarnessClient(baseUrl);

  await client.clarifyTaskSpec("voice-task", {
    baseRevision: 1,
    businessGoal: "我想把一段语音转成文字",
    userNote: "用户补充了唯一输出",
  });
  assert.equal(requests.at(-1).url, "/tasks/voice-task/spec");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    base_revision: 1,
    business_goal: "我想把一段语音转成文字",
    user_note: "用户补充了唯一输出",
  });

  await client.modelSourceProviders();
  assert.equal(requests.at(-1).url, "/model-sources/providers");
  await client.searchModelSources("voice-task", {
    query: "wav2vec2 asr training",
    providers: ["huggingface", "github"],
    limitPerProvider: 3,
    baseSpecRevision: 2,
  });
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-source-searches");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    query: "wav2vec2 asr training",
    providers: ["huggingface", "github"],
    limit_per_provider: 3,
    base_spec_revision: 2,
  });
  await client.listModelSourceSearches("voice-task");
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-source-searches");

  assert.throws(
    () => client.selectModelSourceCandidate("voice-task", {
      searchId: "search-1",
      candidateId: "candidate-1",
      baseSpecRevision: 2,
      approvalConfirmed: false,
    }),
    /Explicit user approval/,
  );
  await client.selectModelSourceCandidate("voice-task", {
    searchId: "search-1",
    candidateId: "candidate-1",
    baseSpecRevision: 2,
    approvalConfirmed: true,
  });
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-source-selections");

  await client.resolveModelSource("voice-task", {
    sourceReference: "https://github.com/owner/trainer",
    requestedRevision: "main",
    baseSpecRevision: 2,
  });
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-source-resolutions");
  await client.listModelSourceResolutions("voice-task");
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-source-resolutions");

  assert.throws(
    () => client.bindModelSource("voice-task", "resolution-1", {
      expectedResolvedCommit: "a".repeat(40),
      baseSpecRevision: 2,
      approvalConfirmed: false,
    }),
    /Explicit user approval/,
  );
  await client.bindModelSource("voice-task", "resolution-1", {
    expectedResolvedCommit: "a".repeat(40),
    baseSpecRevision: 2,
    approvalConfirmed: true,
  });
  assert.equal(
    requests.at(-1).url,
    "/tasks/voice-task/model-source-resolutions/resolution-1/bind",
  );
  await client.listModelBindings("voice-task");
  assert.equal(requests.at(-1).url, "/tasks/voice-task/model-bindings");
  await client.repositoryAnalysis("voice-task", "analysis-1");
  assert.equal(
    requests.at(-1).url,
    "/tasks/voice-task/repository-analyses/analysis-1",
  );

  await client.createTrainingPlan("voice-task", {
    baseSpecRevision: 2,
    entrypointPath: "train.py",
    hyperparameters: { epochs: 3 },
    resourceBudget: { max_ram_bytes: 1024 },
  });
  assert.equal(requests.at(-1).url, "/tasks/voice-task/training-plans");
  await client.currentTrainingPlan("voice-task");
  assert.equal(requests.at(-1).url, "/tasks/voice-task/training-plans/current");
  await client.reviseTrainingPlan("voice-task", "plan-1", {
    expectedParentSha256: "b".repeat(64),
    baseSpecRevision: 2,
    hyperparameters: { epochs: 5 },
  });
  assert.equal(
    requests.at(-1).url,
    "/tasks/voice-task/training-plans/plan-1/revisions",
  );

  assert.throws(
    () => client.decideTrainingPlan("voice-task", "plan-2", {
      expectedPlanSha256: "c".repeat(64),
      decision: "approve",
      approvalConfirmed: false,
    }),
    /Explicit user approval/,
  );
  await client.decideTrainingPlan("voice-task", "plan-2", {
    expectedPlanSha256: "c".repeat(64),
    decision: "approve",
    reason: "用户核对了计划摘要",
    approvalConfirmed: true,
  });
  assert.equal(
    requests.at(-1).url,
    "/tasks/voice-task/training-plans/plan-2/decisions",
  );

  await client.currentResourceFeasibility("voice-task");
  assert.equal(requests.at(-1).url, "/tasks/voice-task/resource-feasibility");
  await client.checkResourceFeasibility("voice-task", {
    trainingPlanRevisionId: "plan-2",
    expectedPlanSha256: "c".repeat(64),
    packages: [{ name: "torch", version: "2.5.1" }],
  });
  assert.equal(
    requests.at(-1).url,
    "/tasks/voice-task/resource-feasibility-checks",
  );
});

test("public projection strips host paths but preserves public API routes", () => {
  const localRoot = "/Users/local-user/private/runtime/task-one";
  const source = {
    task: {
      task_id: "task-one",
      dataset_report: {
        root: localRoot,
        manifest_path: `${localRoot}/dataset_manifest.json`,
        report_path: `${localRoot}/dataset_report.json`,
        files: [{ relative_path: "class-a/one.png", path: "class-a/one.png" }],
      },
      contract: { dataset: { root: localRoot } },
      control: { next_action: { href: "/tasks/task-one/confirm" } },
      provider_capabilities: { href: "/model-sources/providers" },
      note: `stored at ${localRoot}/dataset_report.json`,
      other_host_path: "runtime resolved /Applications/Local Tool/cache.bin",
    },
  };

  const projected = publicProjection(source);
  const serialized = JSON.stringify(projected);
  assert.equal(serialized.includes(localRoot), false);
  assert.equal(serialized.includes("/Applications/Local Tool/cache.bin"), false);
  assert.equal("root" in projected.task.dataset_report, false);
  assert.equal("manifest_path" in projected.task.dataset_report, false);
  assert.equal("report_path" in projected.task.dataset_report, false);
  assert.equal(projected.task.control.next_action.href, "/tasks/task-one/confirm");
  assert.equal(
    projected.task.provider_capabilities.href,
    "/model-sources/providers",
  );
  assert.equal(projected.task.dataset_report.files[0].relative_path, "class-a/one.png");
  assert.equal(source.task.dataset_report.root, localRoot, "projection must not mutate local data");
});

test("L3 Hugging Face methods use fixed-commit task APIs and explicit approval", async () => {
  const client = new ModelHarnessClient(baseUrl);
  await client.huggingFaceCapability();
  assert.equal(requests.at(-1).url, "/model-assets/huggingface/capability");

  await client.searchHuggingFaceModels("mobile net", {
    pipelineTag: "image-classification",
    limit: 7,
  });
  let submitted = requests.at(-1);
  assert.match(submitted.url, /^\/model-assets\/huggingface\/search\?/);
  const search = new URL(`http://local${submitted.url}`);
  assert.equal(search.searchParams.get("q"), "mobile net");
  assert.equal(search.searchParams.get("pipeline_tag"), "image-classification");
  assert.equal(search.searchParams.get("limit"), "7");

  const commit = "a".repeat(40);
  await client.huggingFaceModelCard("owner/model", commit);
  submitted = requests.at(-1);
  assert.match(submitted.url, /^\/model-assets\/huggingface\/card\?/);
  const card = new URL(`http://local${submitted.url}`);
  assert.equal(card.searchParams.get("repo_id"), "owner/model");
  assert.equal(card.searchParams.get("revision"), commit);

  assert.throws(
    () => client.attachHuggingFaceModel("task-one", "owner/model", commit, false),
    /Explicit user approval/,
  );
  assert.throws(
    () => client.attachHuggingFaceModel("task-one", "owner/model", "main", true),
    /immutable 40-character commit/,
  );
  await client.attachHuggingFaceModel("task-one", "owner/model", commit, true);
  submitted = requests.at(-1);
  assert.equal(submitted.url, "/tasks/task-one/model-assets/huggingface");
  assert.deepEqual(JSON.parse(submitted.body), {
    repo_id: "owner/model",
    commit,
    approval_confirmed: true,
  });

  await client.verifyTaskModelAsset("task-one");
  assert.equal(requests.at(-1).url, "/tasks/task-one/model-assets/current/verify");
});

test("L4 evidence methods preserve task ownership and raw sample headers", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-evidence-"));
  try {
    const samplePath = join(temp, "new-row.json");
    await writeFile(samplePath, JSON.stringify({ temperature: 21.5 }));
    const client = new ModelHarnessClient(baseUrl);

    await client.evaluationReport("task-one", "run-one");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/evaluation-report",
    );

    await client.runSampleInference(
      "task-one",
      "run-one",
      samplePath,
      "tabular",
    );
    let submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/task-one/runs/run-one/sample-inferences");
    assert.equal(submitted.method, "POST");
    assert.equal(submitted.headers["x-sample-type"], "tabular");
    assert.equal(decodeURIComponent(submitted.headers["x-filename"]), "new-row.json");
    assert.equal(Buffer.from(submitted.body).toString(), JSON.stringify({ temperature: 21.5 }));

    await client.listSampleInferences("task-one", "run-one");
    assert.equal(requests.at(-1).url, "/tasks/task-one/runs/run-one/sample-inferences");
    await client.getSampleInference("task-one", "run-one", "sample-1");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/sample-inferences/sample-1",
    );

    await client.buildArtifactBundle("task-one", "run-one", {
      sampleInferenceCheckId: "sample-1",
    });
    submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/task-one/runs/run-one/artifact-bundles");
    assert.deepEqual(JSON.parse(submitted.body), {
      sample_inference_check_id: "sample-1",
    });
    await client.listArtifactBundles("task-one", "run-one");
    assert.equal(requests.at(-1).url, "/tasks/task-one/runs/run-one/artifact-bundles");
    await client.getArtifactBundle("task-one", "run-one", "bundle-1");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/artifact-bundles/bundle-1",
    );
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("Artifact Bundle download verifies SHA-256 and returns no host path", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-bundle-"));
  const bundleBytes = Buffer.from("real-artifact-bundle-bytes");
  const sha256 = createHash("sha256").update(bundleBytes).digest("hex");
  const destination = join(temp, "delivery.zip");
  try {
    globalThis.fetch = async (url) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/download")) {
        return new Response(bundleBytes, {
          status: 200,
          headers: { "Content-Type": "application/zip" },
        });
      }
      return new Response(JSON.stringify({
        artifact_bundle: { archive: { sha256 }, report_path: `${temp}/bundle.json` },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const client = new ModelHarnessClient(baseUrl);
    const result = await client.downloadArtifactBundle(
      "task-one",
      "run-one",
      "bundle-one",
      destination,
    );
    assert.deepEqual(await readFile(destination), bundleBytes);
    assert.equal(result.status, "downloaded");
    assert.equal(result.filename, "delivery.zip");
    assert.equal(result.sha256, sha256);
    assert.equal(JSON.stringify(result).includes(temp), false);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("importDataset reads the approved local ZIP and preserves its filename", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-dsh-"));
  try {
    const datasetPath = join(temp, "零件图片.zip");
    await writeFile(datasetPath, Buffer.from("zip-test-payload"));
    const client = new ModelHarnessClient(baseUrl);
    await client.importDataset("task-one", datasetPath);
    const submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/task-one/dataset");
    assert.equal(submitted.method, "POST");
    assert.equal(submitted.headers["content-type"], "application/zip");
    assert.equal(decodeURIComponent(submitted.headers["x-filename"]), "零件图片.zip");
    assert.equal(Buffer.from(submitted.body).toString(), "zip-test-payload");
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("Recipe Factory methods preserve staging, digest approval and task-scoped routes", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-recipe-"));
  try {
    const samplePath = join(temp, "关键词样例.zip");
    await writeFile(samplePath, Buffer.from("recipe-sample-payload"));
    const client = new ModelHarnessClient(baseUrl);

    await client.stageRecipeSamples("audio-task", samplePath, 2);
    let submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/audio-task/staged-assets");
    assert.equal(submitted.headers["x-spec-revision"], "2");
    assert.equal(decodeURIComponent(submitted.headers["x-filename"]), "关键词样例.zip");

    await client.startRecipeBuild("audio-task");
    submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/audio-task/recipe-builds");
    assert.deepEqual(JSON.parse(submitted.body), { build_type: "declarative" });

    await client.getRecipeBuild("audio-task", "attempt-1");
    assert.equal(requests.at(-1).url, "/tasks/audio-task/recipe-builds/attempt-1");

    assert.throws(
      () => client.registerRecipeBuild("audio-task", "attempt-1", {
        candidateDigest: "candidate",
        validationDigest: "validation",
        actor: "local-user",
        approvalConfirmed: false,
      }),
      /Explicit user approval/,
    );
    await client.registerRecipeBuild("audio-task", "attempt-1", {
      candidateDigest: "candidate",
      validationDigest: "validation",
      actor: "local-user",
      reason: "reviewed",
      approvalConfirmed: true,
    });
    submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/audio-task/recipe-builds/attempt-1/register");
    assert.deepEqual(JSON.parse(submitted.body), {
      decision: "approved",
      actor: "local-user",
      reason: "reviewed",
      candidate_digest: "candidate",
      validation_digest: "validation",
    });

    await client.rejectRecipeBuild("audio-task", "attempt-2", "local-user", "unsafe labels");
    assert.equal(requests.at(-1).url, "/tasks/audio-task/recipe-builds/attempt-2/reject");
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
