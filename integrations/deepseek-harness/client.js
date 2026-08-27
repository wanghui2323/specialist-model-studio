import { createHash, randomUUID } from "node:crypto";
import { link, readFile, stat, unlink, writeFile } from "node:fs/promises";
import { basename, extname, resolve } from "node:path";

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";
const MAX_DATASET_BYTES = 200 * 1024 * 1024;
const MAX_RECIPE_SAMPLE_BYTES = 32 * 1024 * 1024;
const MAX_SAMPLE_BYTES = 25 * 1024 * 1024;
const MAX_ARTIFACT_BUNDLE_BYTES = 512 * 1024 * 1024;
const PUBLIC_REDACTED = "[local-path-redacted]";
const PUBLIC_SENSITIVE_KEYS = new Set([
  "root", "cwd", "working_directory", "workspace_root", "dataset_root",
  "manifest_path", "report_path", "contract_path", "archive_path",
  "local_path", "filesystem_path", "source_path", "run_dir", "task_dir",
  "dataset_dir", "artifact_dir",
]);
const PUBLIC_ROUTE_ROOTS = [
  "/agent", "/app", "/capabilities", "/chat", "/data-adapters", "/health",
  "/model-assets", "/model-sources", "/recipes", "/runs", "/runtime", "/tasks",
];
const CONTRACT_REVISION_IDENTITY_FIELDS = Object.freeze([
  "contract_revision_id",
  "contract_sha256",
  "task_id",
  "spec_revision_id",
  "dataset_id",
  "dataset_fingerprint_sha256",
]);

function isPublicRoute(value) {
  return PUBLIC_ROUTE_ROOTS.some((root) => (
    value === root || value.startsWith(`${root}/`) || value.startsWith(`${root}?`)
  ));
}

function isLocalAbsolutePath(value) {
  const selected = String(value).trim();
  return selected.startsWith("file://")
    || selected.startsWith("~/")
    || selected.startsWith("~\\")
    || /^(?:[A-Za-z]:[\\/]|\\\\)/.test(selected)
    || (selected.startsWith("/") && !isPublicRoute(selected));
}

function publicText(value) {
  if (isLocalAbsolutePath(value)) return PUBLIC_REDACTED;
  return value
    .replace(
      /(^|[^A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s"'<>]+/g,
      (_match, prefix) => `${prefix}${PUBLIC_REDACTED}`,
    )
    .replace(
      /(^|[^A-Za-z0-9:/])(\/[^\s"'<>]+)/g,
      (_match, prefix, path) => `${prefix}${isPublicRoute(path) ? path : PUBLIC_REDACTED}`,
    );
}

export function publicProjection(value) {
  if (Array.isArray(value)) return value.map((item) => publicProjection(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).flatMap(([key, child]) => {
      const normalized = key.trim().toLowerCase().replaceAll("-", "_");
      const sensitive = PUBLIC_SENSITIVE_KEYS.has(normalized)
        || normalized.endsWith("_root")
        || ((normalized === "path" || normalized.endsWith("_path"))
          && typeof child === "string" && isLocalAbsolutePath(child));
      return sensitive ? [] : [[key, publicProjection(child)]];
    }));
  }
  return typeof value === "string" ? publicText(value) : value;
}

export class ModelHarnessClient {
  constructor(
    baseUrl = process.env.MODEL_HARNESS_URL || DEFAULT_BASE_URL,
    agentBridgeToken = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN || "",
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.agentBridgeToken = String(agentBridgeToken || "").trim();
  }

  agentBridgeApprovalHeaders() {
    if (!this.agentBridgeToken) {
      throw new Error("The verified agent-bridge approval channel is unavailable");
    }
    return { "X-Model-Harness-Agent-Token": this.agentBridgeToken };
  }

  async request(path, { method = "GET", body, rawBody, headers = {}, signal } = {}) {
    if (body !== undefined && rawBody !== undefined) {
      throw new Error("request cannot contain both JSON and raw bodies");
    }
    const requestHeaders = {
      ...headers,
      "X-Model-Harness-Projection": "agent-v1",
    };
    let requestBody;
    if (body !== undefined) {
      requestHeaders["Content-Type"] = "application/json";
      requestBody = JSON.stringify(body);
    } else if (rawBody !== undefined) {
      requestBody = rawBody;
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      signal,
      headers: Object.keys(requestHeaders).length ? requestHeaders : undefined,
      body: requestBody,
    });
    const contentType = response.headers.get("content-type") || "";
    const value = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const projected = publicProjection(value);
      const detail = typeof projected === "object"
        ? projected.detail || JSON.stringify(projected)
        : projected;
      throw new Error(`Specialist Model Studio ${response.status}: ${detail}`);
    }
    return publicProjection(value);
  }

  recipes(signal) {
    return this.request("/recipes", { signal });
  }

  dataAdapters(signal) {
    return this.request("/data-adapters", { signal });
  }

  matchCapabilities(capabilityRequest, signal) {
    return this.request("/capabilities/match", {
      method: "POST",
      signal,
      body: { capability_request: capabilityRequest },
    });
  }

  listTasks(signal) {
    return this.request("/tasks", { signal });
  }

  createTask(name, businessGoal, signal) {
    return this.request("/tasks", {
      method: "POST",
      signal,
      body: { name, business_goal: businessGoal },
    });
  }

  getTask(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}`, { signal });
  }

  huggingFaceCapability(signal) {
    return this.request("/model-assets/huggingface/capability", { signal });
  }

  searchHuggingFaceModels(query, { pipelineTag, limit = 10 } = {}, signal) {
    const selectedQuery = String(query || "").trim();
    if (!selectedQuery) throw new Error("Hugging Face search query is required");
    if (!Number.isInteger(limit) || limit < 1 || limit > 20) {
      throw new Error("Hugging Face search limit must be an integer from 1 to 20");
    }
    const parameters = new URLSearchParams({ q: selectedQuery, limit: String(limit) });
    if (pipelineTag) parameters.set("pipeline_tag", pipelineTag);
    return this.request(`/model-assets/huggingface/search?${parameters}`, { signal });
  }

  huggingFaceModelCard(repoId, revision, signal) {
    const parameters = new URLSearchParams({ repo_id: repoId });
    if (revision) parameters.set("revision", revision);
    return this.request(`/model-assets/huggingface/card?${parameters}`, { signal });
  }

  attachHuggingFaceModel(taskId, repoId, commit, approvalConfirmed, signal) {
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before model attachment");
    }
    const normalizedCommit = String(commit || "").trim().toLowerCase();
    if (!/^[0-9a-f]{40}$/.test(normalizedCommit)) {
      throw new Error("Hugging Face model attachment requires an immutable 40-character commit SHA");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-assets/huggingface`,
      {
        method: "POST",
        signal,
        body: {
          repo_id: repoId,
          commit: normalizedCommit,
          approval_confirmed: true,
        },
      },
    );
  }

  verifyTaskModelAsset(taskId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-assets/current/verify`,
      { signal },
    );
  }

  updateTaskSpec(taskId, { baseRevision, selectedFamily, businessGoal, userNote }, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/spec`, {
      method: "PATCH",
      signal,
      body: {
        base_revision: baseRevision,
        selected_family: selectedFamily,
        confirm: true,
        ...(businessGoal ? { business_goal: businessGoal } : {}),
        ...(userNote ? { user_note: userNote } : {}),
      },
    });
  }

  clarifyTaskSpec(taskId, { baseRevision, businessGoal, userNote }, signal) {
    const selectedGoal = String(businessGoal || "").trim();
    if (!selectedGoal) {
      throw new Error("A clarified business goal is required");
    }
    return this.request(`/tasks/${encodeURIComponent(taskId)}/spec`, {
      method: "PATCH",
      signal,
      body: {
        base_revision: baseRevision,
        business_goal: selectedGoal,
        ...(userNote ? { user_note: userNote } : {}),
      },
    });
  }

  modelSourceProviders(signal) {
    return this.request("/model-sources/providers", { signal });
  }

  listModelSourceSearches(taskId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-searches`,
      { signal },
    );
  }

  searchModelSources(taskId, {
    query,
    providers,
    limitPerProvider = 4,
    baseSpecRevision,
  } = {}, signal) {
    if (!Number.isInteger(limitPerProvider) || limitPerProvider < 1 || limitPerProvider > 10) {
      throw new Error("Model-source search limit must be an integer from 1 to 10");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-searches`,
      {
        method: "POST",
        signal,
        body: {
          ...(query ? { query } : {}),
          ...(Array.isArray(providers) && providers.length ? { providers } : {}),
          limit_per_provider: limitPerProvider,
          base_spec_revision: baseSpecRevision,
        },
      },
    );
  }

  selectModelSourceCandidate(taskId, {
    searchId,
    candidateId,
    baseSpecRevision,
    approvalConfirmed,
  }, signal) {
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before selecting a model source");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-selections`,
      {
        method: "POST",
        signal,
        body: {
          search_id: searchId,
          candidate_id: candidateId,
          base_spec_revision: baseSpecRevision,
          approval_confirmed: true,
        },
      },
    );
  }

  resolveModelSource(taskId, {
    sourceReference,
    provider,
    requestedRevision,
    baseSpecRevision,
  }, signal) {
    const selectedReference = String(sourceReference || "").trim();
    if (!selectedReference) throw new Error("A public model-source reference is required");
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-resolutions`,
      {
        method: "POST",
        signal,
        body: {
          source_reference: selectedReference,
          ...(provider ? { provider } : {}),
          ...(requestedRevision ? { requested_revision: requestedRevision } : {}),
          base_spec_revision: baseSpecRevision,
        },
      },
    );
  }

  listModelSourceResolutions(taskId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-resolutions`,
      { signal },
    );
  }

  bindModelSource(taskId, resolutionId, {
    expectedResolvedCommit,
    baseSpecRevision,
    approvalConfirmed,
  }, signal) {
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before binding a fixed model source");
    }
    const commit = String(expectedResolvedCommit || "").trim();
    if (!commit) throw new Error("The expected resolved commit is required");
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/model-source-resolutions/${encodeURIComponent(resolutionId)}/bind`,
      {
        method: "POST",
        signal,
        body: {
          expected_resolved_commit: commit,
          base_spec_revision: baseSpecRevision,
          approval_confirmed: true,
        },
      },
    );
  }

  listModelBindings(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/model-bindings`, {
      signal,
    });
  }

  repositoryAnalysis(taskId, analysisId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/repository-analyses/${encodeURIComponent(analysisId)}`,
      { signal },
    );
  }

  createTrainingPlan(taskId, {
    baseSpecRevision,
    entrypointPath,
    hyperparameters,
    resourceBudget,
  } = {}, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/training-plans`, {
      method: "POST",
      signal,
      body: {
        base_spec_revision: baseSpecRevision,
        ...(entrypointPath ? { entrypoint_path: entrypointPath } : {}),
        ...(hyperparameters ? { hyperparameters } : {}),
        ...(resourceBudget ? { resource_budget: resourceBudget } : {}),
      },
    });
  }

  currentTrainingPlan(taskId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/training-plans/current`,
      { signal },
    );
  }

  reviseTrainingPlan(taskId, revisionId, {
    expectedParentSha256,
    baseSpecRevision,
    entrypointPath,
    hyperparameters,
    resourceBudget,
  }, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/training-plans/${encodeURIComponent(revisionId)}/revisions`,
      {
        method: "POST",
        signal,
        body: {
          expected_parent_sha256: expectedParentSha256,
          base_spec_revision: baseSpecRevision,
          ...(entrypointPath ? { entrypoint_path: entrypointPath } : {}),
          ...(hyperparameters ? { hyperparameters } : {}),
          ...(resourceBudget ? { resource_budget: resourceBudget } : {}),
        },
      },
    );
  }

  decideTrainingPlan(taskId, revisionId, {
    expectedPlanSha256,
    decision,
    reason,
    approvalConfirmed,
  }, signal) {
    const selectedDecision = String(decision || "").trim().toLowerCase();
    if (!["approve", "reject", "cancel"].includes(selectedDecision)) {
      throw new Error("Training-plan decision must be approve, reject, or cancel");
    }
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before deciding a training plan");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/training-plans/${encodeURIComponent(revisionId)}/decisions`,
      {
        method: "POST",
        signal,
        body: {
          expected_plan_sha256: expectedPlanSha256,
          decision: selectedDecision,
          reason: String(reason || "").trim(),
        },
      },
    );
  }

  currentResourceFeasibility(taskId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/resource-feasibility`,
      { signal },
    );
  }

  checkResourceFeasibility(taskId, {
    trainingPlanRevisionId,
    expectedPlanSha256,
    baseImageDigest,
    packages,
  }, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/resource-feasibility-checks`,
      {
        method: "POST",
        signal,
        body: {
          training_plan_revision_id: trainingPlanRevisionId,
          expected_plan_sha256: expectedPlanSha256,
          ...(baseImageDigest ? { base_image_digest: baseImageDigest } : {}),
          ...(packages ? { packages } : {}),
        },
      },
    );
  }

  scaffoldRecipe(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/recipe/scaffold`, {
      method: "POST",
      signal,
    });
  }

  async stageRecipeSamples(taskId, samplePath, specRevision, signal) {
    const resolved = resolve(samplePath);
    if (extname(resolved).toLowerCase() !== ".zip") {
      throw new Error("Recipe samples must be a .zip archive");
    }
    const details = await stat(resolved);
    if (!details.isFile()) throw new Error("Recipe sample path is not a file");
    if (details.size > MAX_RECIPE_SAMPLE_BYTES) {
      throw new Error("Recipe samples exceed the 32MB staging limit");
    }
    const payload = await readFile(resolved);
    return this.request(`/tasks/${encodeURIComponent(taskId)}/staged-assets`, {
      method: "POST",
      signal,
      rawBody: payload,
      headers: {
        "Content-Type": "application/zip",
        "X-Filename": encodeURIComponent(basename(resolved)),
        ...(specRevision !== undefined ? { "X-Spec-Revision": String(specRevision) } : {}),
      },
    });
  }

  startRecipeBuild(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/recipe-builds`, {
      method: "POST",
      signal,
      body: { build_type: "declarative" },
    });
  }

  getRecipeBuild(taskId, attemptId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/recipe-builds/${encodeURIComponent(attemptId)}`,
      { signal },
    );
  }

  registerRecipeBuild(taskId, attemptId, approval, signal) {
    if (approval?.approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before Recipe registration");
    }
    const approvalCheckpointId = String(approval?.approvalCheckpointId || "").trim();
    if (!approvalCheckpointId) {
      throw new Error("Recipe registration requires an explicit approval_checkpoint_id");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/recipe-builds/${encodeURIComponent(attemptId)}/register`,
      {
        method: "POST",
        signal,
        headers: this.agentBridgeApprovalHeaders(),
        body: {
          decision: "approved",
          approval: {
            actor: "user",
            checkpoint_id: approvalCheckpointId,
          },
          reason: approval.reason || "reviewed declarative candidate and validation report",
          candidate_digest: approval.candidateDigest,
          validation_digest: approval.validationDigest,
        },
      },
    );
  }

  rejectRecipeBuild(taskId, attemptId, actor, reason, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/recipe-builds/${encodeURIComponent(attemptId)}/reject`,
      {
        method: "POST",
        signal,
        body: { actor, reason },
      },
    );
  }

  async importDataset(taskId, datasetPath, options = {}, signal) {
    const resolved = resolve(datasetPath);
    const extension = extname(resolved).toLowerCase();
    if (![".zip", ".csv"].includes(extension)) {
      throw new Error("Built-in Data Adapters accept .zip or .csv; register an adapter for other formats");
    }
    const details = await stat(resolved);
    if (!details.isFile()) throw new Error("Dataset path is not a file");
    if (details.size > MAX_DATASET_BYTES) {
      throw new Error("Dataset exceeds the 200MB local import limit");
    }
    const payload = await readFile(resolved);
    return this.request(`/tasks/${encodeURIComponent(taskId)}/dataset`, {
      method: "POST",
      signal,
      rawBody: payload,
      headers: {
        "Content-Type": extension === ".csv" ? "text/csv" : "application/zip",
        "X-Filename": encodeURIComponent(basename(resolved)),
        ...(options.targetColumn ? { "X-Target-Column": encodeURIComponent(options.targetColumn) } : {}),
        ...(options.ignoredColumns?.length ? { "X-Ignored-Columns": options.ignoredColumns.map(encodeURIComponent).join(",") } : {}),
        ...(options.delimiter ? { "X-Delimiter": encodeURIComponent(options.delimiter) } : {}),
        ...(options.dataAdapter ? { "X-Data-Adapter": encodeURIComponent(options.dataAdapter) } : {}),
      },
    });
  }

  configureContract(taskId, { accuracyMin, macroF1Min, worstClassRecallMin, maeMax, rmseMax, r2Min, imageSize }, signal) {
    const releaseGates = {};
    if (accuracyMin !== undefined) releaseGates.clean_test_accuracy_min = accuracyMin;
    if (macroF1Min !== undefined) releaseGates.clean_test_macro_f1_min = macroF1Min;
    if (worstClassRecallMin !== undefined) {
      releaseGates.clean_test_worst_class_recall_min = worstClassRecallMin;
    }
    if (maeMax !== undefined) releaseGates.clean_test_mae_max = maeMax;
    if (rmseMax !== undefined) releaseGates.clean_test_rmse_max = rmseMax;
    if (r2Min !== undefined) releaseGates.clean_test_r2_min = r2Min;
    const recipeOptions = {};
    if (imageSize !== undefined) recipeOptions.image_size = imageSize;
    return this.request(`/tasks/${encodeURIComponent(taskId)}/contract`, {
      method: "PATCH",
      signal,
      body: { release_gates: releaseGates, recipe_options: recipeOptions },
    });
  }

  async confirmContract(
    taskId,
    confirmations,
    expectedContractRevision,
    approval,
    signal,
  ) {
    const required = ["data_authorized", "labels_reviewed", "gates_reviewed"];
    if (required.some((name) => confirmations?.[name] !== true)) {
      throw new Error("All three human confirmations must be explicitly true");
    }
    const selectedTaskId = String(taskId || "").trim();
    if (!selectedTaskId) throw new Error("Contract confirmation requires an exact task id");
    if (!expectedContractRevision || typeof expectedContractRevision !== "object") {
      throw new Error("Contract confirmation requires the exact expected contract revision");
    }
    const expected = Object.fromEntries(CONTRACT_REVISION_IDENTITY_FIELDS.map((field) => [
      field,
      String(expectedContractRevision[field] || "").trim(),
    ]));
    const missingIdentity = CONTRACT_REVISION_IDENTITY_FIELDS.filter(
      (field) => !expected[field],
    );
    if (missingIdentity.length) {
      throw new Error(`Contract confirmation identity is incomplete: ${missingIdentity.join(", ")}`);
    }
    if (expected.task_id !== selectedTaskId) {
      throw new Error("Contract confirmation task id does not match the expected contract revision");
    }
    if (!/^[0-9a-f]{64}$/i.test(expected.contract_sha256)) {
      throw new Error("Contract confirmation requires an exact contract SHA-256");
    }
    if (!/^[0-9a-f]{64}$/i.test(expected.dataset_fingerprint_sha256)) {
      throw new Error("Contract confirmation requires an exact dataset fingerprint SHA-256");
    }
    const actor = String(approval?.actor || "").trim();
    const checkpointId = String(approval?.checkpoint_id || "").trim();
    if (actor !== "user" || !checkpointId) {
      throw new Error("Contract confirmation requires a user ApprovalDecision bound to a DSH checkpoint id");
    }

    const taskResponse = await this.getTask(selectedTaskId, signal);
    const task = taskResponse?.task && typeof taskResponse.task === "object"
      ? taskResponse.task
      : taskResponse;
    const revision = task?.contract_revision;
    if (!task || typeof task !== "object" || task.task_id !== selectedTaskId) {
      throw new Error("Contract confirmation could not verify the canonical TrainingTask");
    }
    if (task.contract_stale === true || !revision || typeof revision !== "object") {
      throw new Error("Contract confirmation requires a current canonical contract revision");
    }
    const mismatches = CONTRACT_REVISION_IDENTITY_FIELDS.filter(
      (field) => String(revision[field] || "").trim() !== expected[field],
    );
    const canonicalContext = {
      contract_revision_id: task.current_contract_revision_id,
      task_id: task.task_id,
      spec_revision_id: task.task_spec?.revision_id,
      dataset_id: task.dataset_id,
      dataset_fingerprint_sha256: task.dataset_report?.fingerprint_sha256,
    };
    mismatches.push(...Object.entries(canonicalContext).flatMap(([field, value]) => (
      String(value || "").trim() === String(revision[field] || "").trim()
        ? []
        : [field]
    )));
    if (mismatches.length) {
      throw new Error(
        `Canonical contract revision changed; refresh before confirming (${[...new Set(mismatches)].sort().join(", ")})`,
      );
    }
    return this.request(`/tasks/${encodeURIComponent(selectedTaskId)}/confirm`, {
      method: "POST",
      signal,
      body: {
        ...Object.fromEntries(required.map((name) => [name, true])),
        expected_contract_revision: expected,
        approval: { actor: "user", checkpoint_id: checkpointId },
      },
    });
  }

  authorizeTaskRunStart(taskId, options = {}, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/run-authorizations`, {
      method: "POST",
      signal,
      headers: this.agentBridgeApprovalHeaders(),
      body: {
        contract_sha256: options.contractSha256,
        dataset_id: options.datasetId,
        dataset_fingerprint_sha256: options.datasetFingerprintSha256,
        spec_revision: options.specRevision,
        approval: {
          actor: "user",
          checkpoint_id: options.approvalCheckpointId,
        },
      },
    });
  }

  startTaskRun(taskId, options = {}, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/runs`, {
      method: "POST",
      signal,
      body: {
        run_authorization_id: options.authorizationId,
        authorization_token: options.authorizationToken,
        run_request_sha256: options.runRequestSha256,
      },
    });
  }

  evaluationReport(taskId, runId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/evaluation-report`,
      { signal },
    );
  }

  getInferenceInput(taskId, runId, inferenceInputId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/inference-inputs/${encodeURIComponent(inferenceInputId)}`,
      { signal },
    );
  }

  authorizeSampleInference(taskId, runId, options = {}, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inference-authorizations`,
      {
        method: "POST",
        signal,
        headers: this.agentBridgeApprovalHeaders(),
        body: {
          inference_input_id: options.inferenceInputId,
          inference_input_sha256: options.inferenceInputSha256,
          approval: {
            actor: "user",
            checkpoint_id: options.approvalCheckpointId,
          },
        },
      },
    );
  }

  runSampleInference(taskId, runId, options = {}, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/inference-inputs/${encodeURIComponent(options.inferenceInputId)}/execute`,
      {
        method: "POST",
        signal,
        body: {
          sample_inference_authorization_id: options.authorizationId,
          authorization_token: options.authorizationToken,
          sample_inference_request_sha256: options.requestSha256,
        },
      },
    );
  }

  listSampleInferences(taskId, runId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inferences`,
      { signal },
    );
  }

  getSampleInference(taskId, runId, checkId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inferences/${encodeURIComponent(checkId)}`,
      { signal },
    );
  }

  authorizeArtifactBundleBuild(taskId, runId, options = {}, signal) {
    const body = {
      evaluation_report_id: options.evaluationReportId,
      evaluation_report_sha256: options.evaluationReportSha256,
      approval: {
        actor: "user",
        checkpoint_id: options.approvalCheckpointId,
      },
    };
    if (options.sampleInferenceCheckId) {
      body.sample_inference_check_id = options.sampleInferenceCheckId;
    }
    if (options.inferenceCheckId) body.inference_check_id = options.inferenceCheckId;
    if (body.sample_inference_check_id && body.inference_check_id) {
      throw new Error("Choose either sample_inference_check_id or inference_check_id");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundle-authorizations`,
      {
        method: "POST",
        signal,
        headers: this.agentBridgeApprovalHeaders(),
        body,
      },
    );
  }

  buildArtifactBundle(taskId, runId, options = {}, signal) {
    const body = {
      artifact_bundle_authorization_id: options.authorizationId,
      authorization_token: options.authorizationToken,
      bundle_request_sha256: options.bundleRequestSha256,
    };
    if (options.sampleInferenceCheckId) {
      body.sample_inference_check_id = options.sampleInferenceCheckId;
    }
    if (options.inferenceCheckId) body.inference_check_id = options.inferenceCheckId;
    if (body.sample_inference_check_id && body.inference_check_id) {
      throw new Error("Choose either sample_inference_check_id or inference_check_id");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles`,
      { method: "POST", signal, body },
    );
  }

  listArtifactBundles(taskId, runId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles`,
      { signal },
    );
  }

  getArtifactBundle(taskId, runId, bundleId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles/${encodeURIComponent(bundleId)}`,
      { signal },
    );
  }

  authorizeArtifactBundleDownload(taskId, runId, bundleId, options = {}, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles/${encodeURIComponent(bundleId)}/download-authorizations`,
      {
        method: "POST",
        signal,
        headers: this.agentBridgeApprovalHeaders(),
        body: {
          manifest_sha256: options.manifestSha256,
          archive_sha256: options.archiveSha256,
          approval: {
            actor: "user",
            checkpoint_id: options.approvalCheckpointId,
          },
        },
      },
    );
  }

  async downloadArtifactBundle(
    taskId,
    runId,
    bundleId,
    destinationPath,
    options = {},
    signal,
  ) {
    const resolved = resolve(destinationPath);
    if (extname(resolved).toLowerCase() !== ".zip") {
      throw new Error("Artifact Bundle destination must use a .zip filename");
    }
    const detail = await this.getArtifactBundle(taskId, runId, bundleId, signal);
    const expectedSha256 = detail?.artifact_bundle?.archive?.sha256;
    const expectedManifestSha256 = detail?.artifact_bundle?.manifest_sha256;
    if (!/^[0-9a-f]{64}$/.test(String(expectedSha256 || ""))) {
      throw new Error("Artifact Bundle metadata has no trusted SHA-256");
    }
    if (
      expectedSha256 !== options.archiveSha256
      || expectedManifestSha256 !== options.manifestSha256
    ) {
      throw new Error("Artifact Bundle download scope no longer matches canonical metadata");
    }
    const response = await fetch(
      `${this.baseUrl}/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles/${encodeURIComponent(bundleId)}/download`,
      {
        method: "POST",
        signal,
        headers: {
          "Content-Type": "application/json",
          "X-Model-Harness-Projection": "agent-v1",
        },
        body: JSON.stringify({
          artifact_bundle_download_authorization_id: options.authorizationId,
          authorization_token: options.authorizationToken,
          download_request_sha256: options.downloadRequestSha256,
        }),
      },
    );
    if (!response.ok) {
      throw new Error(`Specialist Model Studio ${response.status}: Artifact Bundle download failed`);
    }
    const responseAuthorizationId = response.headers.get("x-delivery-authorization-id");
    const responseRequestSha256 = response.headers.get("x-delivery-request-sha256");
    if (
      responseAuthorizationId !== options.authorizationId
      || responseRequestSha256 !== options.downloadRequestSha256
    ) {
      throw new Error("Artifact Bundle download response does not match the approved request");
    }
    const declaredSize = Number(response.headers.get("content-length") || 0);
    if (declaredSize > MAX_ARTIFACT_BUNDLE_BYTES) {
      throw new Error("Artifact Bundle exceeds the 512MB download limit");
    }
    const payload = Buffer.from(await response.arrayBuffer());
    if (payload.length > MAX_ARTIFACT_BUNDLE_BYTES) {
      throw new Error("Artifact Bundle exceeds the 512MB download limit");
    }
    const sha256 = createHash("sha256").update(payload).digest("hex");
    if (sha256 !== expectedSha256) {
      throw new Error("Artifact Bundle download failed SHA-256 verification");
    }
    const temporaryPath = `${resolved}.part-${randomUUID()}`;
    let linked = false;
    try {
      await writeFile(temporaryPath, payload, { flag: "wx" });
      await link(temporaryPath, resolved);
      linked = true;
    } catch (error) {
      throw new Error(`Artifact Bundle destination is unavailable: ${publicText(error.message || String(error))}`);
    } finally {
      await unlink(temporaryPath).catch(() => {});
    }
    if (!linked) throw new Error("Artifact Bundle destination was not created");
    return {
      task_id: taskId,
      run_id: runId,
      bundle_id: bundleId,
      status: "downloaded",
      filename: basename(resolved),
      size_bytes: payload.length,
      sha256,
      artifact_bundle_download_authorization_id: options.authorizationId,
      download_request_sha256: options.downloadRequestSha256,
    };
  }

  status(runId, signal) {
    return this.request(`/runs/${encodeURIComponent(runId)}/result`, { signal });
  }

  events(runId, afterSeq = 0, signal) {
    return this.request(
      `/runs/${encodeURIComponent(runId)}/events?after_seq=${encodeURIComponent(afterSeq)}`,
      { signal },
    );
  }

  strategies(runId, signal) {
    return this.request(`/runs/${encodeURIComponent(runId)}/strategies`, { signal });
  }

  applyTaskStrategy(taskId, runId, strategyId, approvalConfirmed, signal) {
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before applying a strategy");
    }
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/strategies/${encodeURIComponent(strategyId)}/apply`,
      {
        method: "POST",
        signal,
        body: { approval_confirmed: true },
      },
    );
  }

  workbenchUrl(taskId) {
    return `${this.baseUrl}/app?task=${encodeURIComponent(taskId)}`;
  }

  cancelTaskRun(taskId, runId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      signal,
    });
  }
}
