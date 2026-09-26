import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, test } from "node:test";

import { ModelHarnessClient, publicProjection } from "../client.js";

const baseUrl = "http://127.0.0.1:8765";
const requests = [];
const originalFetch = globalThis.fetch;
const CONTRACT_REVISION = Object.freeze({
  contract_revision_id: "contract-revision-1",
  contract_sha256: "a".repeat(64),
  task_id: "real-task-123",
  spec_revision_id: "real-task-123:spec:r3",
  dataset_id: "dataset-1",
  dataset_fingerprint_sha256: "b".repeat(64),
});
const CONTRACT_TASK = Object.freeze({
  task_id: "real-task-123",
  contract_stale: false,
  current_contract_revision_id: CONTRACT_REVISION.contract_revision_id,
  contract_revision: CONTRACT_REVISION,
  task_spec: { revision_id: CONTRACT_REVISION.spec_revision_id },
  dataset_id: CONTRACT_REVISION.dataset_id,
  dataset_report: {
    fingerprint_sha256: CONTRACT_REVISION.dataset_fingerprint_sha256,
  },
});

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
        : requestUrl.pathname === "/tasks/real-task-123" && (options.method || "GET") === "GET"
          ? { task: CONTRACT_TASK }
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

test("delivery authorization cannot be requested without the protected bridge token", () => {
  const client = new ModelHarnessClient(baseUrl, "");
  assert.throws(
    () => client.authorizeArtifactBundleBuild(
      "task-one",
      "run-one",
      {
        evaluationReportId: "evaluation-1",
        evaluationReportSha256: "a".repeat(64),
        approvalCheckpointId: "native-call-1",
      },
    ),
    /verified agent-bridge approval channel is unavailable/,
  );
  assert.equal(requests.length, 0);
});

const MODEL_TRIAL = Object.freeze({
  task_id: "task-trial-1", trial_id: "trial-1", plan_sha256: "c".repeat(64),
  status: "pending_approval", stale: false,
  limits: { cpus: 1, memory_bytes: 536870912, timeout_seconds: 30, pids_limit: 128 },
  business_quality_accepted: false, training_run_created: false,
});

function modelTrialOptions() {
  return { expectedPlanSha256: MODEL_TRIAL.plan_sha256, approvalCheckpointId: "native-trial-call-1",
    lineage: { task_id: MODEL_TRIAL.task_id, session_id: "root-session-1", call_id: "native-trial-call-1" } };
}

function respondWithModelTrial(trial = MODEL_TRIAL) {
  const capture = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    const original = await capture(url, options);
    return (options.method || "GET") === "GET"
      ? new Response(JSON.stringify({ model_trial: trial }), { status: 200, headers: { "Content-Type": "application/json" } })
      : original;
  };
}

test("ModelTrial list accepts canonical empty and nonempty lists without assuming a TrainingRun", async () => {
  const client = new ModelHarnessClient(baseUrl);
  const capture = globalThis.fetch;
  for (const records of [[], [MODEL_TRIAL]]) {
    globalThis.fetch = async (url, options = {}) => {
      await capture(url, options);
      return new Response(JSON.stringify({ model_trials: records }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    };
    const result = await client.listModelTrials(MODEL_TRIAL.task_id);
    assert.deepEqual(result.model_trials, records);
    assert.equal(requests.at(-1).method, "GET");
    assert.equal(requests.at(-1).url, "/tasks/task-trial-1/model-trials");
    assert.equal(requests.at(-1).headers["x-model-harness-agent-token"], undefined);
  }
});

test("ModelTrial list fails closed on cross-task, duplicate or malformed records", async () => {
  const client = new ModelHarnessClient(baseUrl);
  for (const records of [null, {}, [null], [{ ...MODEL_TRIAL, task_id: "other-task" }],
    [{ ...MODEL_TRIAL, trial_id: "" }], [MODEL_TRIAL, MODEL_TRIAL]]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ model_trials: records }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
    await assert.rejects(() => client.listModelTrials(MODEL_TRIAL.task_id), /invalid or cross-task records/);
  }
});

test("ModelTrial client binds exact refreshed plan, private token, native checkpoint and observed lineage", async () => {
  respondWithModelTrial();
  const client = new ModelHarnessClient(baseUrl, "private-trial-bridge-token");
  await client.executeModelTrial(MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, modelTrialOptions());
  assert.deepEqual(requests.map(({ method, url }) => [method, url]), [
    ["GET", "/tasks/task-trial-1/model-trials/trial-1"],
    ["POST", "/tasks/task-trial-1/model-trials/trial-1/execute"],
  ]);
  assert.equal(requests[0].headers["x-model-harness-agent-token"], undefined);
  assert.equal(requests[1].headers["x-model-harness-agent-token"], "private-trial-bridge-token");
  assert.deepEqual(JSON.parse(requests[1].body), {
    expected_plan_sha256: MODEL_TRIAL.plan_sha256,
    approval: { actor: "user", checkpoint_id: "native-trial-call-1" },
    lineage: { task_id: MODEL_TRIAL.task_id, session_id: "root-session-1", call_id: "native-trial-call-1" },
  });
  assert.doesNotMatch(requests[1].body, /private-trial-bridge-token|approval_confirmed|agent_run_id|turn_id/);
});

test("ModelTrial client rejects missing checkpoint or observed lineage before any request", async () => {
  const client = new ModelHarnessClient(baseUrl, "private-token");
  for (const options of [
    { ...modelTrialOptions(), approvalCheckpointId: "", approvalConfirmed: true },
    { ...modelTrialOptions(), expectedPlanSha256: "not-a-digest" },
    { ...modelTrialOptions(), lineage: { task_id: MODEL_TRIAL.task_id, call_id: "native-trial-call-1" } },
    { ...modelTrialOptions(), lineage: { ...modelTrialOptions().lineage, call_id: "other-call" } },
    { ...modelTrialOptions(), lineage: { ...modelTrialOptions().lineage, task_id: "other-task" } },
  ]) {
    await assert.rejects(() => client.executeModelTrial(MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, options),
      /exact plan SHA-256 and native approval checkpoint|observed task\/session\/call lineage/);
  }
  assert.equal(requests.length, 0);
});

test("ModelTrial client refuses drift, nonpending state and scope expansion without POST", async () => {
  const client = new ModelHarnessClient(baseUrl, "private-token");
  const capture = globalThis.fetch;
  for (const changed of [
    { task_id: "other-task" }, { trial_id: "other-trial" }, { plan_sha256: "d".repeat(64) },
    { stale: true }, { stale: undefined }, { status: "running" }, { status: "succeeded" },
    { limits: { ...MODEL_TRIAL.limits, cpus: 2 } },
    { limits: { ...MODEL_TRIAL.limits, memory_bytes: 1073741824 } },
    { limits: { ...MODEL_TRIAL.limits, timeout_seconds: 60 } },
    { limits: { ...MODEL_TRIAL.limits, pids_limit: 256 } },
  ]) {
    globalThis.fetch = capture;
    requests.length = 0;
    respondWithModelTrial({ ...MODEL_TRIAL, ...changed });
    await assert.rejects(() => client.executeModelTrial(MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, modelTrialOptions()),
      /canonical task\/trial\/plan digest|non-stale pending_approval|exceeds native approval limits/);
    assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  }
});

test("ModelTrial exact same-call replay returns queued or stale succeeded history without POST", async () => {
  const client = new ModelHarnessClient(baseUrl, "private-token");
  const capture = globalThis.fetch;
  const options = modelTrialOptions();
  for (const status of ["queued", "succeeded"]) {
    globalThis.fetch = capture;
    requests.length = 0;
    const record = { ...MODEL_TRIAL, status, stale: status === "succeeded",
      approval: { actor: "user", verified_by: "agent_bridge_token", checkpoint_id: options.approvalCheckpointId,
        scope_sha256: MODEL_TRIAL.plan_sha256, lineage: options.lineage } };
    respondWithModelTrial(record);
    const result = await client.executeModelTrial(MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, options);
    assert.deepEqual(result.model_trial, record);
    assert.equal(result.idempotent_replay, true);
    assert.equal(result.historical_evidence, true);
    assert.equal(result.dispatch_performed, false);
    assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  }
});

test("ModelTrial exact accepted historical replay remains read-only without a bridge token", async () => {
  const options = modelTrialOptions();
  respondWithModelTrial({ ...MODEL_TRIAL, status: "succeeded", stale: true,
    approval: { actor: "user", verified_by: "agent_bridge_token", checkpoint_id: options.approvalCheckpointId,
      scope_sha256: MODEL_TRIAL.plan_sha256, lineage: options.lineage } });
  const result = await new ModelHarnessClient(baseUrl, "").executeModelTrial(
    MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, options,
  );
  assert.equal(result.idempotent_replay, true);
  assert.equal(result.historical_evidence, true);
  assert.equal(result.dispatch_performed, false);
  assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  assert.equal(requests[0].headers["x-model-harness-agent-token"], undefined);
});

test("ModelTrial pending execution without a bridge token reads the plan but never POSTs", async () => {
  respondWithModelTrial();
  await assert.rejects(() => new ModelHarnessClient(baseUrl, "").executeModelTrial(
    MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, modelTrialOptions(),
  ), /verified agent-bridge approval channel is unavailable/);
  assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  assert.equal(requests[0].headers["x-model-harness-agent-token"], undefined);
});

test("ModelTrial history never resumes a different call, session, scope or missing approval", async () => {
  const client = new ModelHarnessClient(baseUrl, "private-token");
  const capture = globalThis.fetch;
  const options = modelTrialOptions();
  const proof = { actor: "user", verified_by: "agent_bridge_token", checkpoint_id: options.approvalCheckpointId,
    scope_sha256: MODEL_TRIAL.plan_sha256, lineage: options.lineage };
  for (const approval of [undefined, { ...proof, checkpoint_id: "different-call" },
    { ...proof, scope_sha256: "d".repeat(64) }, { ...proof, verified_by: "browser" },
    { ...proof, lineage: { ...proof.lineage, session_id: "other-session" } },
    { ...proof, lineage: { ...proof.lineage, call_id: "other-call" } }]) {
    globalThis.fetch = capture;
    requests.length = 0;
    respondWithModelTrial({ ...MODEL_TRIAL, status: "queued", approval });
    await assert.rejects(() => client.executeModelTrial(MODEL_TRIAL.task_id, MODEL_TRIAL.trial_id, options),
      /non-stale pending_approval/);
    assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  }
});

test("task lifecycle methods preserve canonical task routes and confirmations", async () => {
  const client = new ModelHarnessClient(baseUrl, "bridge-test-token");
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

  await client.updateTaskSpec("real-task-123", {
    baseRevision: 2, selectedFamily: "tabular_regression",
    businessGoal: "估算月租金", name: "月租金估算",
  });
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    base_revision: 2, selected_family: "tabular_regression", confirm: true,
    business_goal: "估算月租金", name: "月租金估算",
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

  await assert.rejects(
    () => client.confirmContract("real-task-123", { data_authorized: true }),
    /three human confirmations/,
  );
  const confirmations = {
    data_authorized: true,
    labels_reviewed: true,
    gates_reviewed: true,
  };
  await assert.rejects(
    () => client.confirmContract("real-task-123", confirmations),
    /exact expected contract revision/,
  );
  await client.confirmContract(
    "real-task-123",
    confirmations,
    CONTRACT_REVISION,
    { actor: "user", checkpoint_id: "dsh-confirm-call-1" },
  );
  assert.equal(requests.at(-2).url, "/tasks/real-task-123");
  assert.equal(requests.at(-2).method, "GET");
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/confirm");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    ...confirmations,
    expected_contract_revision: CONTRACT_REVISION,
    approval: { actor: "user", checkpoint_id: "dsh-confirm-call-1" },
  });

  await client.authorizeTaskRunStart("real-task-123", {
    contractSha256: "a".repeat(64),
    datasetId: "dataset-1",
    datasetFingerprintSha256: "b".repeat(64),
    specRevision: 3,
    approvalCheckpointId: "native-run-call-1",
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/run-authorizations");
  assert.equal(
    requests.at(-1).headers["x-model-harness-agent-token"],
    "bridge-test-token",
  );
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    contract_sha256: "a".repeat(64),
    dataset_id: "dataset-1",
    dataset_fingerprint_sha256: "b".repeat(64),
    spec_revision: 3,
    approval: { actor: "user", checkpoint_id: "native-run-call-1" },
  });

  await client.startTaskRun("real-task-123", {
    authorizationId: "delivery-authorization-run-1",
    authorizationToken: "run-token",
    runRequestSha256: "c".repeat(64),
  });
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/runs");
  assert.equal(requests.at(-1).method, "POST");
  assert.deepEqual(JSON.parse(requests.at(-1).body), {
    run_authorization_id: "delivery-authorization-run-1",
    authorization_token: "run-token",
    run_request_sha256: "c".repeat(64),
  });

  await client.applyTaskStrategy("real-task-123", "parent-run", "balance", true);
  assert.equal(
    requests.at(-1).url,
    "/tasks/real-task-123/runs/parent-run/strategies/balance/apply",
  );

  await client.cancelTaskRun("real-task-123", "parent-run");
  assert.equal(requests.at(-1).url, "/tasks/real-task-123/runs/parent-run/cancel");
});

test("contract confirmation fails closed before POST when canonical identity drifts", async () => {
  const client = new ModelHarnessClient(baseUrl);
  const confirmations = {
    data_authorized: true,
    labels_reviewed: true,
    gates_reviewed: true,
  };
  await assert.rejects(
    () => client.confirmContract(
      "real-task-123",
      confirmations,
      { ...CONTRACT_REVISION, dataset_fingerprint_sha256: "c".repeat(64) },
      { actor: "user", checkpoint_id: "dsh-confirm-call-stale" },
    ),
    /Canonical contract revision changed/,
  );
  assert.deepEqual(requests.map((request) => request.url), ["/tasks/real-task-123"]);

  requests.length = 0;
  await assert.rejects(
    () => client.confirmContract(
      "real-task-123",
      confirmations,
      CONTRACT_REVISION,
      { actor: "assistant", checkpoint_id: "dsh-confirm-call-invalid-actor" },
    ),
    /user ApprovalDecision/,
  );
  assert.equal(requests.length, 0);
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
      conversation: { href: "/conversations/task-one" },
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
  assert.equal(projected.task.conversation.href, "/conversations/task-one");
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

test("L4 evidence methods preserve task ownership and opaque inference input grants", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-evidence-"));
  try {
    const client = new ModelHarnessClient(baseUrl, "bridge-test-token");

    await client.evaluationReport("task-one", "run-one");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/evaluation-report",
    );

    await client.getInferenceInput("task-one", "run-one", "inference-input-1");
    let submitted = requests.at(-1);
    assert.equal(
      submitted.url,
      "/tasks/task-one/runs/run-one/inference-inputs/inference-input-1",
    );

    await client.authorizeSampleInference("task-one", "run-one", {
      inferenceInputId: "inference-input-1",
      inferenceInputSha256: "e".repeat(64),
      approvalCheckpointId: "native-inference-call-1",
    });
    submitted = requests.at(-1);
    assert.equal(
      submitted.url,
      "/tasks/task-one/runs/run-one/sample-inference-authorizations",
    );
    assert.equal(submitted.method, "POST");
    assert.equal(submitted.headers["x-model-harness-agent-token"], "bridge-test-token");
    assert.deepEqual(JSON.parse(submitted.body), {
      inference_input_id: "inference-input-1",
      inference_input_sha256: "e".repeat(64),
      approval: { actor: "user", checkpoint_id: "native-inference-call-1" },
    });

    await client.runSampleInference("task-one", "run-one", {
      inferenceInputId: "inference-input-1",
      authorizationId: "delivery-authorization-inference-1",
      authorizationToken: "one-time-inference-token",
      requestSha256: "f".repeat(64),
    });
    submitted = requests.at(-1);
    assert.equal(
      submitted.url,
      "/tasks/task-one/runs/run-one/inference-inputs/inference-input-1/execute",
    );
    assert.equal(submitted.method, "POST");
    assert.deepEqual(JSON.parse(submitted.body), {
      sample_inference_authorization_id: "delivery-authorization-inference-1",
      authorization_token: "one-time-inference-token",
      sample_inference_request_sha256: "f".repeat(64),
    });

    await client.listSampleInferences("task-one", "run-one");
    assert.equal(requests.at(-1).url, "/tasks/task-one/runs/run-one/sample-inferences");
    await client.getSampleInference("task-one", "run-one", "sample-1");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/sample-inferences/sample-1",
    );

    await client.authorizeArtifactBundleBuild("task-one", "run-one", {
      evaluationReportId: "evaluation-1",
      evaluationReportSha256: "a".repeat(64),
      approvalCheckpointId: "native-build-call-1",
      sampleInferenceCheckId: "sample-1",
    });
    submitted = requests.at(-1);
    assert.equal(
      submitted.url,
      "/tasks/task-one/runs/run-one/artifact-bundle-authorizations",
    );
    assert.equal(submitted.headers["x-model-harness-agent-token"], "bridge-test-token");
    assert.deepEqual(JSON.parse(submitted.body), {
      evaluation_report_id: "evaluation-1",
      evaluation_report_sha256: "a".repeat(64),
      approval: { actor: "user", checkpoint_id: "native-build-call-1" },
      sample_inference_check_id: "sample-1",
    });

    await client.buildArtifactBundle("task-one", "run-one", {
      authorizationId: "delivery-authorization-1",
      authorizationToken: "one-time-token",
      bundleRequestSha256: "b".repeat(64),
      sampleInferenceCheckId: "sample-1",
    });
    submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/task-one/runs/run-one/artifact-bundles");
    assert.deepEqual(JSON.parse(submitted.body), {
      artifact_bundle_authorization_id: "delivery-authorization-1",
      authorization_token: "one-time-token",
      bundle_request_sha256: "b".repeat(64),
      sample_inference_check_id: "sample-1",
    });
    await client.listArtifactBundles("task-one", "run-one");
    assert.equal(requests.at(-1).url, "/tasks/task-one/runs/run-one/artifact-bundles");
    await client.getArtifactBundle("task-one", "run-one", "bundle-1");
    assert.equal(
      requests.at(-1).url,
      "/tasks/task-one/runs/run-one/artifact-bundles/bundle-1",
    );
    await client.authorizeArtifactBundleDownload(
      "task-one",
      "run-one",
      "bundle-1",
      {
        manifestSha256: "c".repeat(64),
        archiveSha256: "d".repeat(64),
        approvalCheckpointId: "native-download-call-1",
      },
    );
    submitted = requests.at(-1);
    assert.equal(
      submitted.url,
      "/tasks/task-one/runs/run-one/artifact-bundles/bundle-1/download-authorizations",
    );
    assert.equal(submitted.headers["x-model-harness-agent-token"], "bridge-test-token");
    assert.deepEqual(JSON.parse(submitted.body), {
      manifest_sha256: "c".repeat(64),
      archive_sha256: "d".repeat(64),
      approval: { actor: "user", checkpoint_id: "native-download-call-1" },
    });
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
    globalThis.fetch = async (url, options = {}) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/download")) {
        assert.equal(options.method, "POST");
        assert.deepEqual(JSON.parse(options.body), {
          artifact_bundle_download_authorization_id: "delivery-authorization-download-1",
          authorization_token: "download-token",
          download_request_sha256: "c".repeat(64),
        });
        return new Response(bundleBytes, {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "X-Delivery-Authorization-Id": "delivery-authorization-download-1",
            "X-Delivery-Request-Sha256": "c".repeat(64),
          },
        });
      }
      return new Response(JSON.stringify({
        artifact_bundle: {
          manifest_sha256: "b".repeat(64),
          archive: { sha256 },
          report_path: `${temp}/bundle.json`,
        },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const client = new ModelHarnessClient(baseUrl, "bridge-test-token");
    const result = await client.downloadArtifactBundle(
      "task-one",
      "run-one",
      "bundle-one",
      destination,
      {
        authorizationId: "delivery-authorization-download-1",
        authorizationToken: "download-token",
        downloadRequestSha256: "c".repeat(64),
        manifestSha256: "b".repeat(64),
        archiveSha256: sha256,
      },
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

test("relative Artifact Bundle destinations stay inside runtime workspace exports", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-bundle-workspace-"));
  const bundleBytes = Buffer.from("workspace-artifact-bundle-bytes");
  const sha256 = createHash("sha256").update(bundleBytes).digest("hex");
  const exportRoot = join(temp, "runtime", "_workspace", "exports");
  const filename = "housing-price-bundle.zip";
  try {
    globalThis.fetch = async (url, options = {}) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/download")) {
        return new Response(bundleBytes, {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "X-Delivery-Authorization-Id": "download-auth-workspace",
            "X-Delivery-Request-Sha256": "d".repeat(64),
          },
        });
      }
      return new Response(JSON.stringify({
        artifact_bundle: {
          manifest_sha256: "e".repeat(64),
          archive: { sha256 },
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = new ModelHarnessClient(baseUrl, "", exportRoot);
    const result = await client.downloadArtifactBundle(
      "task-one",
      "run-one",
      "bundle-one",
      filename,
      {
        authorizationId: "download-auth-workspace",
        authorizationToken: "download-token",
        downloadRequestSha256: "d".repeat(64),
        manifestSha256: "e".repeat(64),
        archiveSha256: sha256,
      },
    );

    assert.deepEqual(await readFile(join(exportRoot, filename)), bundleBytes);
    assert.equal(result.destination_scope, "workspace_exports");
    assert.equal(JSON.stringify(result).includes(temp), false);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("relative Artifact Bundle destinations reject path traversal", async () => {
  const client = new ModelHarnessClient(baseUrl, "", join(tmpdir(), "model-harness-exports"));
  await assert.rejects(
    client.downloadArtifactBundle(
      "task-one",
      "run-one",
      "bundle-one",
      "../outside.zip",
    ),
    /must use a filename only/,
  );
});

test("relative Artifact Bundle destinations fail closed without a runtime workspace", async () => {
  let requested = false;
  globalThis.fetch = async () => {
    requested = true;
    throw new Error("network must not be reached");
  };
  const client = new ModelHarnessClient(baseUrl, "", "");

  await assert.rejects(
    client.downloadArtifactBundle(
      "task-one",
      "run-one",
      "bundle-one",
      "delivery.zip",
    ),
    /runtime workspace export directory is unavailable/i,
  );
  assert.equal(requested, false);
});

test("Artifact Bundle download never overwrites an existing destination or leaves a partial file", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-bundle-existing-"));
  const bundleBytes = Buffer.from("new-bundle-bytes");
  const sha256 = createHash("sha256").update(bundleBytes).digest("hex");
  const destination = join(temp, "delivery.zip");
  await writeFile(destination, Buffer.from("keep-existing"));
  try {
    globalThis.fetch = async (url) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/download")) {
        return new Response(bundleBytes, {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "X-Delivery-Authorization-Id": "download-auth-existing",
            "X-Delivery-Request-Sha256": "e".repeat(64),
          },
        });
      }
      return new Response(JSON.stringify({
        artifact_bundle: {
          manifest_sha256: "f".repeat(64),
          archive: { sha256 },
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = new ModelHarnessClient(baseUrl);
    await assert.rejects(
      client.downloadArtifactBundle(
        "task-one",
        "run-one",
        "bundle-one",
        destination,
        {
          authorizationId: "download-auth-existing",
          authorizationToken: "download-token",
          downloadRequestSha256: "e".repeat(64),
          manifestSha256: "f".repeat(64),
          archiveSha256: sha256,
        },
      ),
      /destination is unavailable/,
    );
    assert.equal((await readFile(destination)).toString(), "keep-existing");
    assert.deepEqual(await readdir(temp), ["delivery.zip"]);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("Artifact Bundle download rejects response headers outside the approved scope", async () => {
  const temp = await mkdtemp(join(tmpdir(), "model-harness-bundle-scope-"));
  const bundleBytes = Buffer.from("bundle-scope-bytes");
  const sha256 = createHash("sha256").update(bundleBytes).digest("hex");
  const destination = join(temp, "delivery.zip");
  try {
    globalThis.fetch = async (url) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/download")) {
        return new Response(bundleBytes, {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "X-Delivery-Authorization-Id": "wrong-authorization",
            "X-Delivery-Request-Sha256": "0".repeat(64),
          },
        });
      }
      return new Response(JSON.stringify({
        artifact_bundle: {
          manifest_sha256: "a".repeat(64),
          archive: { sha256 },
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const client = new ModelHarnessClient(baseUrl);
    await assert.rejects(
      client.downloadArtifactBundle(
        "task-one",
        "run-one",
        "bundle-one",
        destination,
        {
          authorizationId: "download-auth-scope",
          authorizationToken: "download-token",
          downloadRequestSha256: "b".repeat(64),
          manifestSha256: "a".repeat(64),
          archiveSha256: sha256,
        },
      ),
      /does not match the approved request/,
    );
    assert.deepEqual(await readdir(temp), []);
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
    const client = new ModelHarnessClient(baseUrl, "bridge-test-token");

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
        approvalConfirmed: false,
      }),
      /Explicit user approval/,
    );
    assert.throws(
      () => client.registerRecipeBuild("audio-task", "attempt-1", {
        candidateDigest: "candidate",
        validationDigest: "validation",
        approvalConfirmed: true,
      }),
      /approval_checkpoint_id/,
    );
    await client.registerRecipeBuild("audio-task", "attempt-1", {
      candidateDigest: "candidate",
      validationDigest: "validation",
      approvalCheckpointId: "native-recipe-approval-call",
      reason: "reviewed",
      approvalConfirmed: true,
    });
    submitted = requests.at(-1);
    assert.equal(submitted.url, "/tasks/audio-task/recipe-builds/attempt-1/register");
    assert.equal(
      submitted.headers["x-model-harness-agent-token"],
      "bridge-test-token",
    );
    assert.deepEqual(JSON.parse(submitted.body), {
      decision: "approved",
      approval: {
        actor: "user",
        checkpoint_id: "native-recipe-approval-call",
      },
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
