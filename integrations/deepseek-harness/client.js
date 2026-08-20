const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

export class ModelHarnessClient {
  constructor(baseUrl = process.env.MODEL_HARNESS_URL || DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async request(path, { method = "GET", body, signal } = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
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

  cancel(runId, signal) {
    return this.request(`/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      signal,
    });
  }
}
