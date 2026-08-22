import { createHash } from "node:crypto";
import { readFile, stat, writeFile } from "node:fs/promises";
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
  "/model-assets", "/recipes", "/runs", "/runtime", "/tasks",
];

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
  constructor(baseUrl = process.env.MODEL_HARNESS_URL || DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
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
      throw new Error(`Model Harness ${response.status}: ${detail}`);
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
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/recipe-builds/${encodeURIComponent(attemptId)}/register`,
      {
        method: "POST",
        signal,
        body: {
          decision: "approved",
          actor: approval.actor,
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

  confirmContract(taskId, confirmations, signal) {
    const required = ["data_authorized", "labels_reviewed", "gates_reviewed"];
    if (required.some((name) => confirmations?.[name] !== true)) {
      throw new Error("All three human confirmations must be explicitly true");
    }
    return this.request(`/tasks/${encodeURIComponent(taskId)}/confirm`, {
      method: "POST",
      signal,
      body: Object.fromEntries(required.map((name) => [name, true])),
    });
  }

  startTaskRun(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/runs`, {
      method: "POST",
      signal,
    });
  }

  evaluationReport(taskId, runId, signal) {
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/evaluation-report`,
      { signal },
    );
  }

  async runSampleInference(taskId, runId, samplePath, sampleType, signal) {
    const resolved = resolve(samplePath);
    let details;
    let payload;
    try {
      details = await stat(resolved);
      if (!details.isFile()) throw new Error("not a file");
      if (details.size > MAX_SAMPLE_BYTES) {
        throw new Error("sample exceeds the 25MB inference limit");
      }
      payload = await readFile(resolved);
    } catch (error) {
      throw new Error(`Sample input is unavailable: ${publicText(error.message || String(error))}`);
    }
    const normalizedType = String(sampleType || "").trim().toLowerCase();
    if (!["image", "audio", "tabular"].includes(normalizedType)) {
      throw new Error("sample_type must be image, audio, or tabular");
    }
    const extension = extname(resolved).toLowerCase();
    const contentType = extension === ".json"
      ? "application/json"
      : extension === ".csv"
        ? "text/csv"
        : extension === ".wav"
          ? "audio/wav"
          : extension === ".png"
            ? "image/png"
            : extension === ".jpg" || extension === ".jpeg"
              ? "image/jpeg"
              : "application/octet-stream";
    return this.request(
      `/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/sample-inferences`,
      {
        method: "POST",
        signal,
        rawBody: payload,
        headers: {
          "Content-Type": contentType,
          "X-Filename": encodeURIComponent(basename(resolved)),
          "X-Sample-Type": normalizedType,
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

  buildArtifactBundle(taskId, runId, options = {}, signal) {
    const body = {};
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

  async downloadArtifactBundle(taskId, runId, bundleId, destinationPath, signal) {
    const resolved = resolve(destinationPath);
    if (extname(resolved).toLowerCase() !== ".zip") {
      throw new Error("Artifact Bundle destination must use a .zip filename");
    }
    const detail = await this.getArtifactBundle(taskId, runId, bundleId, signal);
    const expectedSha256 = detail?.artifact_bundle?.archive?.sha256;
    if (!/^[0-9a-f]{64}$/.test(String(expectedSha256 || ""))) {
      throw new Error("Artifact Bundle metadata has no trusted SHA-256");
    }
    const response = await fetch(
      `${this.baseUrl}/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/artifact-bundles/${encodeURIComponent(bundleId)}/download`,
      {
        signal,
        headers: { "X-Model-Harness-Projection": "agent-v1" },
      },
    );
    if (!response.ok) {
      throw new Error(`Model Harness ${response.status}: Artifact Bundle download failed`);
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
    try {
      await writeFile(resolved, payload, { flag: "wx" });
    } catch (error) {
      throw new Error(`Artifact Bundle destination is unavailable: ${publicText(error.message || String(error))}`);
    }
    return {
      task_id: taskId,
      run_id: runId,
      bundle_id: bundleId,
      status: "downloaded",
      filename: basename(resolved),
      size_bytes: payload.length,
      sha256,
    };
  }

  async startRun({ recipe = "digit-classification", businessGoal, taskId, runId, signal } = {}) {
    const template = await this.request(`/recipes/${encodeURIComponent(recipe)}/template`, { signal });
    const contract = template.contract;
    if (businessGoal) contract.business_goal = businessGoal;
    if (taskId) contract.task_id = taskId;
    return this.request("/runs", {
      method: "POST",
      signal,
      body: { contract, run_id: runId },
    });
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

  applyStrategy(runId, strategyId, approvalConfirmed, signal) {
    if (approvalConfirmed !== true) {
      throw new Error("Explicit user approval is required before applying a strategy");
    }
    return this.request(
      `/runs/${encodeURIComponent(runId)}/strategies/${encodeURIComponent(strategyId)}/apply`,
      {
        method: "POST",
        signal,
        body: { approval_confirmed: true },
      },
    );
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
