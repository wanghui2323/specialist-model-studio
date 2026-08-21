import { readFile, stat } from "node:fs/promises";
import { basename, extname, resolve } from "node:path";

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";
const MAX_DATASET_BYTES = 200 * 1024 * 1024;

export class ModelHarnessClient {
  constructor(baseUrl = process.env.MODEL_HARNESS_URL || DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async request(path, { method = "GET", body, rawBody, headers = {}, signal } = {}) {
    if (body !== undefined && rawBody !== undefined) {
      throw new Error("request cannot contain both JSON and raw bodies");
    }
    const requestHeaders = { ...headers };
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
      const detail = typeof value === "object" ? value.detail || JSON.stringify(value) : value;
      throw new Error(`Model Harness ${response.status}: ${detail}`);
    }
    return value;
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

  createTask(name, businessGoal, capabilityRequest, signal) {
    return this.request("/tasks", {
      method: "POST",
      signal,
      body: { name, business_goal: businessGoal, capability_request: capabilityRequest },
    });
  }

  getTask(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}`, { signal });
  }

  scaffoldRecipe(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/recipe/scaffold`, {
      method: "POST",
      signal,
    });
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

  cancel(runId, signal) {
    return this.request(`/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      signal,
    });
  }
}
