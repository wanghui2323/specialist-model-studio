import { createHash } from "node:crypto";

import { defineTool } from "@deepseek-ai/dsh-tools";

import { ModelHarnessClient } from "./client.js";

export const name = "specialist-model-studio-tools";
export const inject = ["tools", "systemPrompt"];
export const TASK_FAMILIES = Object.freeze([
  "image_classification",
  "ocr",
  "object_detection",
  "segmentation",
  "audio_classification",
  "asr",
  "speech_synthesis",
  "tabular_classification",
  "tabular_regression",
  "time_series_forecasting",
  "anomaly_detection",
  "text_classification",
  "named_entity_recognition",
  "classification",
  "regression",
  "custom",
]);

export const ROLE_TOOL_ALLOWLISTS = Object.freeze({
  research_source: Object.freeze([
    "model_harness_list_tasks",
    "model_harness_get_task",
    "model_harness_list_model_source_providers",
    "model_harness_search_model_sources",
    "model_harness_list_model_source_searches",
    "model_harness_select_model_source_candidate",
    "model_harness_resolve_model_source",
    "model_harness_list_model_source_resolutions",
    "model_harness_bind_model_source",
    "model_harness_list_model_bindings",
    "model_harness_get_repository_analysis",
    "model_harness_hf_capability",
    "model_harness_hf_search",
    "model_harness_hf_card",
    "model_harness_hf_attach",
    "model_harness_hf_verify",
  ]),
  data_experiment: Object.freeze([
    "model_harness_get_task",
    "model_harness_list_data_adapters",
    "model_harness_match_capability",
    "model_harness_stage_recipe_samples",
    "model_harness_list_recipes",
  ]),
  resource_safety: Object.freeze([
    "model_harness_get_task",
    "model_harness_list_model_bindings",
    "model_harness_get_repository_analysis",
    "model_harness_create_training_plan",
    "model_harness_get_training_plan",
    "model_harness_revise_training_plan",
    "model_harness_decide_training_plan",
    "model_harness_get_resource_feasibility",
    "model_harness_check_resource_feasibility",
  ]),
  build_training: Object.freeze([
    "model_harness_get_task",
    "model_harness_scaffold_recipe",
    "model_harness_stage_recipe_samples",
    "model_harness_build_recipe",
    "model_harness_get_recipe_build",
    "model_harness_register_recipe",
    "model_harness_reject_recipe",
    "model_harness_list_recipes",
    "model_harness_configure_contract",
    "model_harness_confirm_contract",
    "model_harness_start_task_run",
    "model_harness_get_run",
    "model_harness_get_events",
    "model_harness_get_strategies",
    "model_harness_apply_task_strategy",
    "model_harness_cancel_run",
  ]),
  evaluation_delivery: Object.freeze([
    "model_harness_get_task",
    "model_harness_get_run",
    "model_harness_get_events",
    "model_harness_get_evaluation_report",
    "model_harness_run_sample_inference",
    "model_harness_list_sample_inferences",
    "model_harness_get_sample_inference",
    "model_harness_build_artifact_bundle",
    "model_harness_list_artifact_bundles",
    "model_harness_get_artifact_bundle",
  ]),
});

const ROLE_LABELS = Object.freeze({
  research_source: "research_source（研究与来源）",
  data_experiment: "data_experiment（数据与实验）",
  resource_safety: "resource_safety（资源与安全）",
  build_training: "build_training（构建与训练）",
  evaluation_delivery: "evaluation_delivery（评测与交付）",
});

const SPECIALIST_DELEGATION_TOOLS = new Set(Object.keys(ROLE_TOOL_ALLOWLISTS));
const RUN_AUTHORIZATION_TTL_MS = 10 * 60 * 1000;
const SAMPLE_INFERENCE_AUTHORIZATION_TTL_MS = 10 * 60 * 1000;
const ARTIFACT_BUNDLE_AUTHORIZATION_TTL_MS = 10 * 60 * 1000;

const ORCHESTRATOR_TASK_CONTROL_TOOLS = new Set([
  "model_harness_create_task",
  "model_harness_promote_conversation",
  "model_harness_update_task_spec",
  "model_harness_clarify_task_spec",
  "model_harness_select_model_source_candidate",
  "model_harness_bind_model_source",
  "model_harness_decide_training_plan",
  "model_harness_hf_attach",
  "model_harness_register_recipe",
  "model_harness_reject_recipe",
  "model_harness_configure_contract",
  "model_harness_confirm_contract",
  "model_harness_authorize_task_run_start",
  "model_harness_authorize_sample_inference",
  "model_harness_authorize_artifact_bundle_build",
  "model_harness_apply_task_strategy",
  "model_harness_download_artifact_bundle",
  "model_harness_cancel_run",
]);

const TOOL_ROLE_OWNERS = new Map();
for (const [role, toolNames] of Object.entries(ROLE_TOOL_ALLOWLISTS)) {
  for (const toolName of toolNames) {
    const owners = TOOL_ROLE_OWNERS.get(toolName) || [];
    owners.push(role);
    TOOL_ROLE_OWNERS.set(toolName, owners);
  }
}

function sameToolProfile(actual, expected) {
  if (!Array.isArray(actual) || actual.length !== expected.length) return false;
  if (actual.some((toolName) => typeof toolName !== "string")) return false;
  const actualNames = new Set(actual);
  return actualNames.size === expected.length
    && expected.every((toolName) => actualNames.has(toolName));
}

function specialistRoleFromAgent(agent) {
  const header = agent?.session?.header;
  if (header?.origin !== "subagent") return null;
  if (typeof header.parentSession !== "string" || !header.parentSession) return undefined;
  const events = Array.isArray(agent?.session?.events)
    ? agent.session.events
    : [];
  const childOwnedEvents = events.slice(
    Number.isSafeInteger(header.seedLength) ? header.seedLength : 0,
  );
  const descriptor = childOwnedEvents.find(
    (event) => event?.type === "subagent/descriptor",
  )?.data;
  if (
    descriptor?.version !== 2
    || descriptor.mode !== "continuable"
    || descriptor.provider !== "spawn"
  ) return undefined;
  const allow = descriptor?.toolFilter?.allow;
  return Object.entries(ROLE_TOOL_ALLOWLISTS).find(
    // Recognize the exact prior data profile for session continuity, but use
    // the current allowlist below to deny its removed import permission.
    ([role, expected]) => sameToolProfile(allow, expected)
      || (role === "data_experiment" && sameToolProfile(allow,
        [...expected, "model_harness_import_dataset"])),
  )?.[0];
}

function isOrchestratorDirectTool(toolName) {
  return ORCHESTRATOR_TASK_CONTROL_TOOLS.has(toolName)
    || /^model_harness_(?:get|list)_/.test(toolName);
}

function roleGateDecision(exec) {
  if (!exec.name.startsWith("model_harness_") || !exec.agent) return null;
  const header = exec.agent?.session?.header;
  const role = specialistRoleFromAgent(exec.agent);
  if (header?.origin === "subagent") {
    if (!role) {
      return {
        kind: "deny",
        reason: `无法从 DSH 子会话的持久化 role profile 验证权限；已拒绝 ${exec.name}。请由训练协调器重新创建对应专家会话。`,
      };
    }
    if (!ROLE_TOOL_ALLOWLISTS[role].includes(exec.name)) {
      const owners = TOOL_ROLE_OWNERS.get(exec.name) || [];
      const required = owners.length
        ? owners.map((owner) => ROLE_LABELS[owner]).join(" 或 ")
        : "训练协调器";
      return {
        kind: "deny",
        reason: `当前 DSH 子会话绑定为 ${ROLE_LABELS[role]}，${exec.name} 不在该 profile allowlist；此动作需要 ${required}。请交回训练协调器重新委派。`,
      };
    }
    return null;
  }
  const owners = TOOL_ROLE_OWNERS.get(exec.name) || [];
  if (!owners.length || isOrchestratorDirectTool(exec.name)) return null;
  return {
    kind: "deny",
    reason: `训练协调器不能直接执行 ${exec.name}。该阶段必须由 ${owners.map((owner) => ROLE_LABELS[owner]).join(" 或 ")} 的已绑定 DSH 子会话执行；请先委派，再由协调器综合其证据。`,
  };
}

function canonicalTaskRecord(value) {
  const task = value?.task && typeof value.task === "object" ? value.task : value;
  if (!task || typeof task !== "object") {
    throw new Error("TrainingTask lookup did not return a canonical task record");
  }
  return task;
}

function requireRootSessionId(exec) {
  const header = exec?.agent?.session?.header;
  if (header?.origin === "subagent") {
    throw new Error("Only the root Training Orchestrator can issue run authorization");
  }
  const sessionId = typeof header?.id === "string" ? header.id.trim() : "";
  if (!sessionId) {
    throw new Error("Run authorization requires a verifiable root DSH session");
  }
  return sessionId;
}

function requireCallId(exec) {
  const callId = String(exec?.callId || "").trim();
  if (!callId) {
    throw new Error("This protected model-training action requires a verifiable DSH tool call id");
  }
  return callId;
}

function assertRunAuthorizationBinding(taskValue, binding) {
  const task = canonicalTaskRecord(taskValue);
  const actualFingerprint = String(
    task.dataset_report?.fingerprint_sha256
      || task.dataset?.fingerprint_sha256
      || "",
  ).trim().toLowerCase();
  const checks = [
    [String(task.task_id || ""), binding.task_id, "task id"],
    [String(task.confirmed_contract_sha256 || "").toLowerCase(), binding.contract_sha256, "confirmed contract"],
    [String(task.dataset_id || ""), binding.dataset_id, "dataset id"],
    [actualFingerprint, binding.dataset_fingerprint_sha256, "dataset fingerprint"],
    [Number(task.current_spec_revision), binding.spec_revision, "task spec revision"],
  ];
  for (const [actual, expected, label] of checks) {
    if (actual !== expected) {
      throw new Error(`Run authorization ${label} no longer matches the canonical TrainingTask`);
    }
  }
  if (task.contract_confirmed !== true) {
    throw new Error("Run authorization requires a canonically confirmed training contract");
  }
  const recoverableStatuses = new Set(["failed", "cancelled", "interrupted"]);
  if (task.status !== "ready" && !recoverableStatuses.has(task.status)) {
    throw new Error(`Run authorization requires a ready or recoverable task, received ${String(task.status || "unknown")}`);
  }
  if (task.pending_run) {
    throw new Error("Run authorization cannot be issued while the task owns a pending run");
  }
  if (task.current_run_id && !recoverableStatuses.has(task.status)) {
    throw new Error("Run authorization cannot replace a non-recoverable current run");
  }
  if (!task.current_run_id && recoverableStatuses.has(task.status)) {
    throw new Error("Run authorization requires canonical prior-run lineage for recovery");
  }
  return task;
}

class RunAuthorizationBroker {
  constructor(client, { now = () => Date.now() } = {}) {
    this.client = client;
    this.now = now;
    this.grants = new Map();
  }

  _prune() {
    const now = this.now();
    const cutoff = now - RUN_AUTHORIZATION_TTL_MS;
    for (const [authorizationId, grant] of this.grants) {
      if (
        grant.expires_at_ms <= now
        || (grant.consumed_at_ms && grant.consumed_at_ms <= cutoff)
      ) {
        this.grants.delete(authorizationId);
      }
    }
  }

  _binding(args) {
    const binding = {
      task_id: String(args?.task_id || "").trim(),
      contract_sha256: String(args?.contract_sha256 || "").trim().toLowerCase(),
      dataset_id: String(args?.dataset_id || "").trim(),
      dataset_fingerprint_sha256: String(args?.dataset_fingerprint_sha256 || "").trim().toLowerCase(),
      spec_revision: Number(args?.spec_revision),
    };
    if (!binding.task_id || !binding.dataset_id) {
      throw new Error("Run authorization requires exact task and dataset ids");
    }
    if (!SHA256.test(binding.contract_sha256) || !SHA256.test(binding.dataset_fingerprint_sha256)) {
      throw new Error("Run authorization requires exact SHA-256 contract and dataset fingerprints");
    }
    if (!Number.isSafeInteger(binding.spec_revision) || binding.spec_revision < 1) {
      throw new Error("Run authorization requires a positive task spec revision");
    }
    return binding;
  }

  async issue(args, exec) {
    this._prune();
    const rootSessionId = requireRootSessionId(exec);
    const approvalCheckpointId = requireCallId(exec);
    const binding = this._binding(args);
    const task = await this.client.getTask(binding.task_id, exec.signal);
    assertRunAuthorizationBinding(task, binding);
    const issued = await this.client.authorizeTaskRunStart(
      binding.task_id,
      {
        contractSha256: binding.contract_sha256,
        datasetId: binding.dataset_id,
        datasetFingerprintSha256: binding.dataset_fingerprint_sha256,
        specRevision: binding.spec_revision,
        approvalCheckpointId,
      },
      exec.signal,
    );
    const canonical = issued?.run_authorization;
    const scope = canonical?.scope;
    const approval = canonical?.approval_decision;
    const authorizationId = String(canonical?.authorization_id || "").trim();
    const authorizationToken = String(issued?.authorization_token || "").trim();
    const runRequestSha256 = String(canonical?.scope_sha256 || "").trim().toLowerCase();
    const checks = [
      [String(canonical?.action || ""), "start_task_run", "action"],
      [String(scope?.task_id || ""), binding.task_id, "task id"],
      [String(scope?.contract_sha256 || "").toLowerCase(), binding.contract_sha256, "contract digest"],
      [String(scope?.dataset_id || ""), binding.dataset_id, "dataset id"],
      [String(scope?.dataset_fingerprint_sha256 || "").toLowerCase(), binding.dataset_fingerprint_sha256, "dataset fingerprint"],
      [Number(scope?.spec_revision), binding.spec_revision, "task spec revision"],
      [String(approval?.actor || ""), "user", "approval actor"],
      [String(approval?.checkpoint_id || ""), approvalCheckpointId, "approval checkpoint"],
      [String(approval?.verified_by || ""), "agent_bridge_token", "approval verifier"],
    ];
    for (const [actual, expected, label] of checks) {
      if (actual !== expected) {
        throw new Error(`Run backend authorization ${label} does not match the native approval`);
      }
    }
    if (!authorizationId.startsWith("delivery-authorization-") || !authorizationToken) {
      throw new Error("Run backend did not issue a usable authorization capability");
    }
    if (!SHA256.test(runRequestSha256)) {
      throw new Error("Run backend authorization has no canonical scope digest");
    }
    const issuedAtMs = Date.parse(String(canonical?.issued_at_utc || ""));
    const expiresAtMs = Date.parse(String(canonical?.expires_at_utc || ""));
    if (
      !Number.isFinite(issuedAtMs)
      || !Number.isFinite(expiresAtMs)
      || expiresAtMs <= this.now()
    ) {
      throw new Error("Run backend authorization is already expired or malformed");
    }
    const grant = {
      ...binding,
      authorization_id: authorizationId,
      authorization_token: authorizationToken,
      run_request_sha256: runRequestSha256,
      approval_checkpoint_id: approvalCheckpointId,
      approval_decision_id: approval.decision_id,
      authorization_sha256: canonical.authorization_sha256,
      root_session_id: rootSessionId,
      specialist_role: "build_training",
      status: "issued",
      issued_at_ms: issuedAtMs,
      expires_at_ms: expiresAtMs,
    };
    this.grants.set(authorizationId, grant);
    return {
      run_authorization_id: authorizationId,
      run_request_sha256: grant.run_request_sha256,
      approval_checkpoint_id: grant.approval_checkpoint_id,
      task_id: grant.task_id,
      contract_sha256: grant.contract_sha256,
      dataset_id: grant.dataset_id,
      dataset_fingerprint_sha256: grant.dataset_fingerprint_sha256,
      spec_revision: grant.spec_revision,
      specialist_role: grant.specialist_role,
      expires_at_utc: new Date(grant.expires_at_ms).toISOString(),
      single_use: true,
    };
  }

  reserve(exec) {
    this._prune();
    let callId;
    try {
      callId = requireCallId(exec);
    } catch (error) {
      return { kind: "deny", reason: error.message };
    }
    const authorizationId = String(exec?.arguments?.run_authorization_id || "").trim();
    const taskId = String(exec?.arguments?.task_id || "").trim();
    const grant = this.grants.get(authorizationId);
    if (!authorizationId || !grant) {
      return {
        kind: "deny",
        reason: "启动训练需要根协调器刚刚批准并签发的一次性授权；请返回根会话重新确认。",
      };
    }
    if (grant.status !== "issued" || grant.expires_at_ms <= this.now()) {
      return {
        kind: "deny",
        reason: "本次训练启动授权已使用或已过期；请返回根会话重新确认，不能重放旧授权。",
      };
    }
    const header = exec?.agent?.session?.header;
    const role = specialistRoleFromAgent(exec?.agent);
    if (
      role !== grant.specialist_role
      || header?.origin !== "subagent"
      || header?.parentSession !== grant.root_session_id
    ) {
      return {
        kind: "deny",
        reason: "本次训练启动授权只对原根会话委派的、持久化 role profile 可验证的构建与训练专家有效。",
      };
    }
    if (taskId !== grant.task_id) {
      return {
        kind: "deny",
        reason: "本次训练启动授权绑定了另一个 TrainingTask；已拒绝跨任务使用。",
      };
    }
    grant.status = "reserved";
    grant.reserved_call_id = callId;
    grant.reserved_session_id = header.id;
    return { kind: "allow" };
  }

  async consume(args, exec) {
    const authorizationId = String(args?.run_authorization_id || "").trim();
    const grant = this.grants.get(authorizationId);
    const callId = requireCallId(exec);
    const header = exec?.agent?.session?.header;
    if (
      !grant
      || grant.status !== "reserved"
      || grant.reserved_call_id !== callId
      || grant.reserved_session_id !== header?.id
      || specialistRoleFromAgent(exec?.agent) !== grant.specialist_role
      || header?.parentSession !== grant.root_session_id
      || String(args?.task_id || "").trim() !== grant.task_id
    ) {
      throw new Error("Run authorization was not reserved for this exact specialist tool call");
    }
    grant.status = "consumed";
    grant.consumed_at_ms = this.now();
    const task = await this.client.getTask(grant.task_id, exec.signal);
    assertRunAuthorizationBinding(task, grant);
    return grant;
  }
}

function canonicalInferenceInput(value) {
  const record = value?.inference_input && typeof value.inference_input === "object"
    ? value.inference_input
    : value;
  if (!record || typeof record !== "object") {
    throw new Error("Sample inference authorization requires a canonical inference input");
  }
  return record;
}

function assertSampleInferenceAuthorizationBinding(taskValue, runValue, inputValue, binding) {
  const task = canonicalTaskRecord(taskValue);
  const run = canonicalRunRecord(runValue);
  const input = canonicalInferenceInput(inputValue);
  const checks = [
    [String(task.task_id || ""), binding.task_id, "task id"],
    [String(run.task_id || ""), binding.task_id, "run owner"],
    [String(run.run_id || ""), binding.run_id, "run id"],
    [String(input.task_id || ""), binding.task_id, "input owner"],
    [String(input.run_id || ""), binding.run_id, "input run"],
    [String(input.inference_input_id || ""), binding.inference_input_id, "input id"],
    [String(input.sha256 || "").toLowerCase(), binding.inference_input_sha256, "input digest"],
  ];
  for (const [actual, expected, label] of checks) {
    if (actual !== expected) {
      throw new Error(`Sample inference authorization ${label} no longer matches canonical evidence`);
    }
  }
  if (!Array.isArray(task.run_ids) || !task.run_ids.includes(binding.run_id)) {
    throw new Error("Sample inference authorization run is no longer owned by the TrainingTask");
  }
  if (run.status !== "completed") {
    throw new Error("Sample inference authorization requires a completed canonical TrainingRun");
  }
  if (input.status !== "staged") {
    throw new Error("Sample inference input is already used or unavailable");
  }
  const recordSha256 = String(input.record_sha256 || "").toLowerCase();
  if (!SHA256.test(recordSha256)) {
    throw new Error("Sample inference input has no canonical record digest");
  }
  if (!["image", "audio", "tabular"].includes(String(input.sample_type || ""))) {
    throw new Error("Sample inference input has an unsupported type");
  }
  return { task, run, input, record_sha256: recordSha256 };
}

class SampleInferenceAuthorizationBroker {
  constructor(client, { now = () => Date.now() } = {}) {
    this.client = client;
    this.now = now;
    this.grants = new Map();
  }

  _prune() {
    const now = this.now();
    const cutoff = now - SAMPLE_INFERENCE_AUTHORIZATION_TTL_MS;
    for (const [authorizationId, grant] of this.grants) {
      if (
        grant.expires_at_ms <= now
        || (grant.consumed_at_ms && grant.consumed_at_ms <= cutoff)
      ) {
        this.grants.delete(authorizationId);
      }
    }
  }

  _binding(args) {
    const binding = {
      task_id: String(args?.task_id || "").trim(),
      run_id: String(args?.run_id || "").trim(),
      inference_input_id: String(args?.inference_input_id || "").trim(),
      inference_input_sha256: String(args?.inference_input_sha256 || "").trim().toLowerCase(),
    };
    if (!binding.task_id || !binding.run_id || !binding.inference_input_id) {
      throw new Error("Sample inference authorization requires exact task, run and input ids");
    }
    if (!SHA256.test(binding.inference_input_sha256)) {
      throw new Error("Sample inference authorization requires an exact input SHA-256");
    }
    return binding;
  }

  async _canonicalEvidence(binding, signal) {
    const [taskValue, runValue, inputValue] = await Promise.all([
      this.client.getTask(binding.task_id, signal),
      this.client.status(binding.run_id, signal),
      this.client.getInferenceInput(
        binding.task_id,
        binding.run_id,
        binding.inference_input_id,
        signal,
      ),
    ]);
    return assertSampleInferenceAuthorizationBinding(
      taskValue,
      runValue,
      inputValue,
      binding,
    );
  }

  _scopeMatches(args, grant) {
    return [
      [String(args?.task_id || "").trim(), grant.task_id],
      [String(args?.run_id || "").trim(), grant.run_id],
      [String(args?.inference_input_id || "").trim(), grant.inference_input_id],
      [String(args?.sample_inference_authorization_id || "").trim(), grant.authorization_id],
      [String(args?.sample_inference_request_sha256 || "").trim().toLowerCase(), grant.sample_inference_request_sha256],
    ].every(([actual, expected]) => actual === expected);
  }

  async issue(args, exec) {
    this._prune();
    const rootSessionId = requireRootSessionId(exec);
    const approvalCheckpointId = requireCallId(exec);
    const binding = this._binding(args);
    const evidence = await this._canonicalEvidence(binding, exec.signal);
    const issued = await this.client.authorizeSampleInference(
      binding.task_id,
      binding.run_id,
      {
        inferenceInputId: binding.inference_input_id,
        inferenceInputSha256: binding.inference_input_sha256,
        approvalCheckpointId,
      },
      exec.signal,
    );
    const canonical = issued?.sample_inference_authorization;
    const scope = canonical?.scope;
    const approval = canonical?.approval_decision;
    const authorizationId = String(canonical?.authorization_id || "").trim();
    const authorizationToken = String(issued?.authorization_token || "").trim();
    const requestSha256 = String(canonical?.scope_sha256 || "").trim().toLowerCase();
    const checks = [
      [String(canonical?.action || ""), "run_sample_inference", "action"],
      [String(scope?.task_id || ""), binding.task_id, "task id"],
      [String(scope?.run_id || ""), binding.run_id, "run id"],
      [String(scope?.inference_input_id || ""), binding.inference_input_id, "input id"],
      [String(scope?.inference_input_sha256 || "").toLowerCase(), binding.inference_input_sha256, "input digest"],
      [String(scope?.inference_input_record_sha256 || "").toLowerCase(), evidence.record_sha256, "input record digest"],
      [String(scope?.sample_type || ""), String(evidence.input.sample_type || ""), "sample type"],
      [Number(scope?.size_bytes), Number(evidence.input.size_bytes), "input size"],
      [String(approval?.actor || ""), "user", "approval actor"],
      [String(approval?.checkpoint_id || ""), approvalCheckpointId, "approval checkpoint"],
      [String(approval?.verified_by || ""), "agent_bridge_token", "approval verifier"],
    ];
    for (const [actual, expected, label] of checks) {
      if (actual !== expected) {
        throw new Error(`Sample inference backend authorization ${label} does not match the native approval`);
      }
    }
    if (!authorizationId.startsWith("delivery-authorization-") || !authorizationToken) {
      throw new Error("Sample inference backend did not issue a usable authorization capability");
    }
    if (!SHA256.test(requestSha256)) {
      throw new Error("Sample inference backend authorization has no canonical scope digest");
    }
    const issuedAtMs = Date.parse(String(canonical?.issued_at_utc || ""));
    const expiresAtMs = Date.parse(String(canonical?.expires_at_utc || ""));
    if (
      !Number.isFinite(issuedAtMs)
      || !Number.isFinite(expiresAtMs)
      || expiresAtMs <= this.now()
    ) {
      throw new Error("Sample inference backend authorization is already expired or malformed");
    }
    const grant = {
      ...binding,
      inference_input_record_sha256: evidence.record_sha256,
      authorization_id: authorizationId,
      authorization_token: authorizationToken,
      sample_inference_request_sha256: requestSha256,
      approval_checkpoint_id: approvalCheckpointId,
      approval_decision_id: approval.decision_id,
      authorization_sha256: canonical.authorization_sha256,
      root_session_id: rootSessionId,
      specialist_role: "evaluation_delivery",
      status: "issued",
      issued_at_ms: issuedAtMs,
      expires_at_ms: expiresAtMs,
    };
    this.grants.set(authorizationId, grant);
    return {
      sample_inference_authorization_id: authorizationId,
      sample_inference_request_sha256: requestSha256,
      approval_checkpoint_id: approvalCheckpointId,
      task_id: grant.task_id,
      run_id: grant.run_id,
      inference_input_id: grant.inference_input_id,
      inference_input_sha256: grant.inference_input_sha256,
      specialist_role: grant.specialist_role,
      expires_at_utc: new Date(grant.expires_at_ms).toISOString(),
      single_use: true,
    };
  }

  reserve(exec) {
    this._prune();
    let callId;
    try {
      callId = requireCallId(exec);
    } catch (error) {
      return { kind: "deny", reason: error.message };
    }
    const authorizationId = String(
      exec?.arguments?.sample_inference_authorization_id || "",
    ).trim();
    const grant = this.grants.get(authorizationId);
    if (!authorizationId || !grant) {
      return {
        kind: "deny",
        reason: "试跑新样例需要根协调器刚刚批准并签发的一次性授权；请返回根会话确认这个推理样例。",
      };
    }
    if (grant.status !== "issued" || grant.expires_at_ms <= this.now()) {
      return {
        kind: "deny",
        reason: "本次样例试跑授权已使用或已过期；请重新上传并确认，不能重放旧授权。",
      };
    }
    const header = exec?.agent?.session?.header;
    const role = specialistRoleFromAgent(exec?.agent);
    if (
      role !== grant.specialist_role
      || header?.origin !== "subagent"
      || header?.parentSession !== grant.root_session_id
    ) {
      return {
        kind: "deny",
        reason: "本次样例试跑授权只对原根会话委派的、持久化 role profile 可验证的评测与交付专家有效。",
      };
    }
    if (!this._scopeMatches(exec.arguments, grant)) {
      return {
        kind: "deny",
        reason: "本次样例试跑调用与批准的 task、run、input 或请求摘要不一致。",
      };
    }
    grant.status = "reserved";
    grant.reserved_call_id = callId;
    grant.reserved_session_id = header.id;
    return { kind: "allow" };
  }

  async consume(args, exec) {
    const authorizationId = String(
      args?.sample_inference_authorization_id || "",
    ).trim();
    const grant = this.grants.get(authorizationId);
    const callId = requireCallId(exec);
    const header = exec?.agent?.session?.header;
    if (
      !grant
      || grant.status !== "reserved"
      || grant.reserved_call_id !== callId
      || grant.reserved_session_id !== header?.id
      || specialistRoleFromAgent(exec?.agent) !== grant.specialist_role
      || header?.parentSession !== grant.root_session_id
      || !this._scopeMatches(args, grant)
    ) {
      throw new Error("Sample inference authorization was not reserved for this exact specialist tool call");
    }
    grant.status = "consumed";
    grant.consumed_at_ms = this.now();
    const evidence = await this._canonicalEvidence(grant, exec.signal);
    if (evidence.record_sha256 !== grant.inference_input_record_sha256) {
      throw new Error("Sample inference input changed after approval");
    }
    grant.consumed_call_id = callId;
    grant.consumed_session_id = header.id;
    return grant;
  }
}

function canonicalRunRecord(value) {
  const run = value?.run && typeof value.run === "object" ? value.run : value;
  if (!run || typeof run !== "object") {
    throw new Error("TrainingRun lookup did not return a canonical run record");
  }
  return run;
}

function canonicalEvaluationReport(value) {
  const report = value?.evaluation_report;
  if (!report || typeof report !== "object") {
    throw new Error("Artifact Bundle authorization requires a canonical EvaluationReport");
  }
  return report;
}

function canonicalSampleInference(value) {
  const sample = value?.sample_inference && typeof value.sample_inference === "object"
    ? value.sample_inference
    : value;
  if (!sample || typeof sample !== "object") {
    throw new Error("Artifact Bundle authorization did not receive canonical sample inference evidence");
  }
  return sample;
}

function sha256Json(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function sampleInferenceEvidenceDigest(value, binding) {
  const sample = canonicalSampleInference(value);
  const checks = [
    [String(sample.task_id || ""), binding.task_id, "task id"],
    [String(sample.run_id || ""), binding.run_id, "run id"],
    [String(sample.check_id || ""), binding.sample_inference_check_id, "check id"],
  ];
  for (const [actual, expected, label] of checks) {
    if (actual !== expected) {
      throw new Error(`Artifact Bundle sample inference ${label} no longer matches the approved scope`);
    }
  }
  if (sample.status !== "passed" || sample.blocked === true) {
    throw new Error("Artifact Bundle authorization requires a passed sample inference check");
  }
  const inferenceCheckId = String(sample.inference_check_id || "").trim();
  if (!inferenceCheckId) {
    throw new Error("Artifact Bundle sample inference has no trusted inference check id");
  }
  return sha256Json({
    check_id: binding.sample_inference_check_id,
    inference_check_id: inferenceCheckId,
    model_sha256: String(sample.model?.sha256 || "").toLowerCase(),
    prediction_sha256: String(sample.prediction_sha256 || "").toLowerCase(),
    run_id: binding.run_id,
    sample_sha256: String(sample.sample?.sha256 || "").toLowerCase(),
    task_id: binding.task_id,
  });
}

function assertArtifactBundleAuthorizationBinding(
  taskValue,
  runValue,
  evaluationValue,
  binding,
) {
  const task = canonicalTaskRecord(taskValue);
  const run = canonicalRunRecord(runValue);
  const report = canonicalEvaluationReport(evaluationValue);
  const checks = [
    [String(task.task_id || ""), binding.task_id, "task id"],
    [String(run.task_id || ""), binding.task_id, "run owner"],
    [String(run.run_id || ""), binding.run_id, "run id"],
    [String(evaluationValue?.run_id || ""), binding.run_id, "evaluation run id"],
    [String(report.task_id || ""), binding.task_id, "evaluation task id"],
    [String(report.run_id || ""), binding.run_id, "evaluation report run id"],
    [String(report.report_id || ""), binding.evaluation_report_id, "evaluation report id"],
    [String(report.report_sha256 || "").toLowerCase(), binding.evaluation_report_sha256, "evaluation report digest"],
  ];
  for (const [actual, expected, label] of checks) {
    if (actual !== expected) {
      throw new Error(`Artifact Bundle authorization ${label} no longer matches canonical evidence`);
    }
  }
  if (!Array.isArray(task.run_ids) || !task.run_ids.includes(binding.run_id)) {
    throw new Error("Artifact Bundle authorization run is no longer owned by the canonical TrainingTask");
  }
  if (run.status !== "completed" || report.run_status !== "completed") {
    throw new Error("Artifact Bundle authorization requires a completed canonical TrainingRun");
  }
  if (report.integrity_status !== "passed") {
    throw new Error("Artifact Bundle authorization requires a passed integrity report");
  }
  return { task, run, report };
}

class ArtifactBundleAuthorizationBroker {
  constructor(client, { now = () => Date.now() } = {}) {
    this.client = client;
    this.now = now;
    this.grants = new Map();
  }

  _prune() {
    const now = this.now();
    const cutoff = now - ARTIFACT_BUNDLE_AUTHORIZATION_TTL_MS;
    for (const [authorizationId, grant] of this.grants) {
      if (
        grant.expires_at_ms <= now
        || (grant.consumed_at_ms && grant.consumed_at_ms <= cutoff)
      ) {
        this.grants.delete(authorizationId);
      }
    }
  }

  _binding(args) {
    const binding = {
      task_id: String(args?.task_id || "").trim(),
      run_id: String(args?.run_id || "").trim(),
      evaluation_report_id: String(args?.evaluation_report_id || "").trim(),
      evaluation_report_sha256: String(args?.evaluation_report_sha256 || "").trim().toLowerCase(),
      sample_inference_check_id: String(args?.sample_inference_check_id || "").trim(),
      inference_check_id: String(args?.inference_check_id || "").trim(),
    };
    if (!binding.task_id || !binding.run_id || !binding.evaluation_report_id) {
      throw new Error("Artifact Bundle authorization requires exact task, run and evaluation report ids");
    }
    if (!SHA256.test(binding.evaluation_report_sha256)) {
      throw new Error("Artifact Bundle authorization requires an exact EvaluationReport SHA-256");
    }
    if (binding.sample_inference_check_id && binding.inference_check_id) {
      throw new Error("Artifact Bundle authorization accepts only one inference evidence selector");
    }
    return binding;
  }

  async _canonicalEvidence(binding, signal) {
    const [taskValue, runValue, evaluationValue] = await Promise.all([
      this.client.getTask(binding.task_id, signal),
      this.client.status(binding.run_id, signal),
      this.client.evaluationReport(binding.task_id, binding.run_id, signal),
    ]);
    assertArtifactBundleAuthorizationBinding(taskValue, runValue, evaluationValue, binding);
    let sampleInferenceSha256 = null;
    if (binding.sample_inference_check_id) {
      const sampleValue = await this.client.getSampleInference(
        binding.task_id,
        binding.run_id,
        binding.sample_inference_check_id,
        signal,
      );
      sampleInferenceSha256 = sampleInferenceEvidenceDigest(sampleValue, binding);
    }
    return { sample_inference_evidence_sha256: sampleInferenceSha256 };
  }

  _scopeMatches(args, grant) {
    const scopeChecks = [
      [String(args?.task_id || "").trim(), grant.task_id],
      [String(args?.run_id || "").trim(), grant.run_id],
      [String(args?.bundle_request_sha256 || "").trim().toLowerCase(), grant.bundle_request_sha256],
      [String(args?.sample_inference_check_id || "").trim(), grant.sample_inference_check_id],
      [String(args?.inference_check_id || "").trim(), grant.inference_check_id],
    ];
    return scopeChecks.every(([actual, expected]) => actual === expected);
  }

  async issue(args, exec) {
    this._prune();
    const rootSessionId = requireRootSessionId(exec);
    const approvalCheckpointId = requireCallId(exec);
    const binding = this._binding(args);
    const evidence = await this._canonicalEvidence(binding, exec.signal);
    const issued = await this.client.authorizeArtifactBundleBuild(
      binding.task_id,
      binding.run_id,
      {
        evaluationReportId: binding.evaluation_report_id,
        evaluationReportSha256: binding.evaluation_report_sha256,
        approvalCheckpointId,
        sampleInferenceCheckId: binding.sample_inference_check_id || undefined,
        inferenceCheckId: binding.inference_check_id || undefined,
      },
      exec.signal,
    );
    const canonical = issued?.artifact_bundle_authorization;
    const scope = canonical?.scope;
    const authorizationId = String(canonical?.authorization_id || "").trim();
    const authorizationToken = String(issued?.authorization_token || "").trim();
    const requestSha256 = String(canonical?.scope_sha256 || "").trim().toLowerCase();
    const approval = canonical?.approval_decision;
    const checks = [
      [String(canonical?.task_id || ""), binding.task_id, "task id"],
      [String(canonical?.action || ""), "build_artifact_bundle", "action"],
      [String(scope?.task_id || ""), binding.task_id, "scope task id"],
      [String(scope?.run_id || ""), binding.run_id, "scope run id"],
      [String(scope?.evaluation_report_id || ""), binding.evaluation_report_id, "EvaluationReport id"],
      [String(scope?.evaluation_report_sha256 || "").toLowerCase(), binding.evaluation_report_sha256, "EvaluationReport digest"],
      [String(scope?.sample_inference_check_id || ""), binding.sample_inference_check_id, "sample inference selector"],
      [String(scope?.inference_check_id || ""), binding.inference_check_id, "inference selector"],
      [String(scope?.sample_inference_evidence_sha256 || ""), evidence.sample_inference_evidence_sha256 || "", "sample inference evidence"],
      [String(approval?.actor || ""), "user", "approval actor"],
      [String(approval?.checkpoint_id || ""), approvalCheckpointId, "approval checkpoint"],
      [String(approval?.verified_by || ""), "agent_bridge_token", "approval verifier"],
    ];
    for (const [actual, expected, label] of checks) {
      if (actual !== expected) {
        throw new Error(`Artifact Bundle backend authorization ${label} does not match the native approval`);
      }
    }
    if (!authorizationId.startsWith("delivery-authorization-") || !authorizationToken) {
      throw new Error("Artifact Bundle backend did not issue a usable authorization capability");
    }
    if (!SHA256.test(requestSha256)) {
      throw new Error("Artifact Bundle backend authorization has no canonical scope digest");
    }
    const issuedAtMs = Date.parse(String(canonical?.issued_at_utc || ""));
    const expiresAtMs = Date.parse(String(canonical?.expires_at_utc || ""));
    if (
      !Number.isFinite(issuedAtMs)
      || !Number.isFinite(expiresAtMs)
      || expiresAtMs <= this.now()
    ) {
      throw new Error("Artifact Bundle backend authorization is already expired or malformed");
    }
    const grant = {
      ...binding,
      ...evidence,
      authorization_id: authorizationId,
      authorization_token: authorizationToken,
      approval_checkpoint_id: approvalCheckpointId,
      approval_decision_id: approval.decision_id,
      authorization_sha256: canonical.authorization_sha256,
      bundle_request_sha256: requestSha256,
      root_session_id: rootSessionId,
      specialist_role: "evaluation_delivery",
      status: "issued",
      issued_at_ms: issuedAtMs,
      expires_at_ms: expiresAtMs,
    };
    this.grants.set(authorizationId, grant);
    return {
      artifact_bundle_authorization_id: authorizationId,
      approval_checkpoint_id: grant.approval_checkpoint_id,
      bundle_request_sha256: grant.bundle_request_sha256,
      task_id: grant.task_id,
      run_id: grant.run_id,
      evaluation_report_id: grant.evaluation_report_id,
      evaluation_report_sha256: grant.evaluation_report_sha256,
      sample_inference_check_id: grant.sample_inference_check_id || null,
      inference_check_id: grant.inference_check_id || null,
      specialist_role: grant.specialist_role,
      expires_at_utc: new Date(grant.expires_at_ms).toISOString(),
      single_use: true,
    };
  }

  reserve(exec) {
    this._prune();
    let callId;
    try {
      callId = requireCallId(exec);
    } catch (error) {
      return { kind: "deny", reason: error.message };
    }
    const args = exec?.arguments || {};
    const authorizationId = String(args.artifact_bundle_authorization_id || "").trim();
    const grant = this.grants.get(authorizationId);
    if (!authorizationId || !grant) {
      return {
        kind: "deny",
        reason: "构建交付包需要根协调器刚刚批准并签发的一次性授权；请返回根会话确认本次交付范围。",
      };
    }
    if (grant.status !== "issued" || grant.expires_at_ms <= this.now()) {
      return {
        kind: "deny",
        reason: "本次交付包构建授权已使用或已过期；请返回根会话重新确认，不能重放旧授权。",
      };
    }
    const header = exec?.agent?.session?.header;
    const role = specialistRoleFromAgent(exec?.agent);
    if (
      role !== grant.specialist_role
      || header?.origin !== "subagent"
      || header?.parentSession !== grant.root_session_id
    ) {
      return {
        kind: "deny",
        reason: "本次交付包构建授权只对原根会话委派的、持久化 role profile 可验证的评测与交付专家有效。",
      };
    }
    if (!this._scopeMatches(args, grant)) {
      return {
        kind: "deny",
        reason: "本次交付包构建调用与根协调器批准的 task、run 或 bundle request scope 不一致。",
      };
    }
    grant.status = "reserved";
    grant.reserved_call_id = callId;
    grant.reserved_session_id = header.id;
    return { kind: "allow" };
  }

  async consume(args, exec) {
    const authorizationId = String(args?.artifact_bundle_authorization_id || "").trim();
    const grant = this.grants.get(authorizationId);
    const callId = requireCallId(exec);
    const header = exec?.agent?.session?.header;
    if (
      !grant
      || grant.status !== "reserved"
      || grant.reserved_call_id !== callId
      || grant.reserved_session_id !== header?.id
      || specialistRoleFromAgent(exec?.agent) !== grant.specialist_role
      || header?.parentSession !== grant.root_session_id
      || !this._scopeMatches(args, grant)
    ) {
      throw new Error("Artifact Bundle authorization was not reserved for this exact specialist tool call");
    }
    grant.status = "consumed";
    grant.consumed_at_ms = this.now();
    const evidence = await this._canonicalEvidence(grant, exec.signal);
    if (
      evidence.sample_inference_evidence_sha256 !== grant.sample_inference_evidence_sha256
    ) {
      throw new Error("Artifact Bundle authorization evidence changed after approval");
    }
    grant.consumed_call_id = callId;
    grant.consumed_session_id = header.id;
    return grant;
  }

  audit(grant, artifactBundle, canonicalAuthorization) {
    return {
      artifact_bundle_authorization_id: grant.authorization_id,
      approval_checkpoint_id: grant.approval_checkpoint_id,
      bundle_request_sha256: grant.bundle_request_sha256,
      task_id: grant.task_id,
      run_id: grant.run_id,
      bundle_id: artifactBundle?.bundle_id || null,
      manifest_sha256: artifactBundle?.manifest_sha256 || null,
      approval_decision_id: grant.approval_decision_id,
      authorization_sha256: canonicalAuthorization?.authorization_sha256
        || grant.authorization_sha256
        || null,
      specialist_role: grant.specialist_role,
      consumed_call_id: grant.consumed_call_id,
      status: "consumed",
      single_use: true,
    };
  }
}

const APPROVAL_REQUIRED_TOOLS = new Set([
  "model_harness_import_dataset",
  "model_harness_select_model_source_candidate",
  "model_harness_bind_model_source",
  "model_harness_decide_training_plan",
  "model_harness_stage_recipe_samples",
  "model_harness_build_recipe",
  "model_harness_register_recipe",
  "model_harness_reject_recipe",
  "model_harness_scaffold_recipe",
  "model_harness_configure_contract",
  "model_harness_confirm_contract",
  "model_harness_authorize_task_run_start",
  "model_harness_authorize_sample_inference",
  "model_harness_authorize_artifact_bundle_build",
  "model_harness_hf_attach",
  "model_harness_apply_task_strategy",
  "model_harness_cancel_run",
  "model_harness_build_artifact_bundle",
  "model_harness_download_artifact_bundle",
]);

const jsonOutput = {
  schema: { type: "json" },
  render: (_args, value) => [
    { type: "text", text: JSON.stringify(value, null, 2) },
  ],
};

const SHA256 = /^[0-9a-f]{64}$/i;
const COMMIT = /^[0-9a-f]{40}$/i;
const BLOCKER_ID = /^blocker_[0-9a-f]{24}$/;
const BLOCKER_EVIDENCE_SCHEMA_VERSION = "0.3";
const LEGACY_BLOCKER_EVIDENCE_SCHEMA_VERSION = "0.1";
const PREVIOUS_BLOCKER_EVIDENCE_SCHEMA_VERSION = "0.2";
const READABLE_BLOCKER_EVIDENCE_SCHEMA_VERSIONS = new Set([
  LEGACY_BLOCKER_EVIDENCE_SCHEMA_VERSION,
  PREVIOUS_BLOCKER_EVIDENCE_SCHEMA_VERSION,
  BLOCKER_EVIDENCE_SCHEMA_VERSION,
]);
const UNSAFE_LABEL = /(?:^|\s)(?:\/Users\/|\/home\/|\/var\/|[A-Za-z]:[\\/])|authorization\s*:|bearer\s+|(?:hf|ghp|github_pat)_[A-Za-z0-9_-]{8,}|token\s*[=:]/i;

function safeObjectRefLabel(value, type) {
  const selected = typeof value === "string" ? value.trim() : "";
  if (!selected || UNSAFE_LABEL.test(selected)) return type.replaceAll("_", " ");
  return selected.slice(0, 160);
}

function assertTaskIdentity(record, taskId, type) {
  if (record?.task_id !== undefined && record.task_id !== taskId) {
    throw new Error(`${type} returned an invalid canonical identity`);
  }
}

function assertRunIdentity(record, runId, type) {
  if (record?.run_id !== undefined && record.run_id !== runId) {
    throw new Error(`${type} returned an invalid run identity`);
  }
}

function canonicalObjectRef(type, taskId, fields) {
  const id = typeof fields?.id === "string" ? fields.id.trim() : "";
  const returnedTaskId = typeof fields?.task_id === "string" && fields.task_id
    ? fields.task_id
    : taskId;
  if (!id || returnedTaskId !== taskId) {
    throw new Error(`${type} returned an invalid canonical identity`);
  }
  const ref = { type, id, task_id: returnedTaskId };
  if (fields.label) ref.label = safeObjectRefLabel(fields.label, type);
  if (fields.digest !== undefined) {
    if (typeof fields.digest !== "string" || !SHA256.test(fields.digest)) throw new Error(`${type} returned an invalid digest`);
    ref.digest = fields.digest.toLowerCase();
  }
  if (fields.base_spec_revision !== undefined) {
    if (!Number.isInteger(fields.base_spec_revision) || fields.base_spec_revision < 1) throw new Error(`${type} returned an invalid base_spec_revision`);
    ref.base_spec_revision = fields.base_spec_revision;
  }
  if (fields.revision !== undefined) {
    if (!Number.isInteger(fields.revision) || fields.revision < 1) throw new Error(`${type} returned an invalid revision`);
    ref.revision = fields.revision;
  }
  if (fields.resolved_commit !== undefined) {
    if (typeof fields.resolved_commit !== "string" || !COMMIT.test(fields.resolved_commit)) throw new Error(`${type} returned a mutable revision`);
    ref.resolved_commit = fields.resolved_commit.toLowerCase();
  }
  if (fields.run_id !== undefined) {
    if (typeof fields.run_id !== "string" || !fields.run_id) throw new Error(`${type} returned an invalid run_id`);
    ref.run_id = fields.run_id;
  }
  if (fields.record_kind !== undefined) ref.record_kind = fields.record_kind;
  for (const field of ["candidate_digest", "validation_digest"]) {
    if (fields[field] !== undefined) {
      if (typeof fields[field] !== "string" || !SHA256.test(fields[field])) throw new Error(`${type} returned an invalid ${field}`);
      ref[field] = fields[field].toLowerCase();
    }
  }
  return ref;
}

function withObjectRefs(result, refs, taskId) {
  const selected = refs.filter(Boolean);
  selected.forEach((ref) => {
    if (ref.task_id !== taskId) throw new Error("ObjectRef belongs to another task");
  });
  return { ...result, ...(selected.length ? { object_refs: selected } : {}) };
}

function resolutionRef(record, taskId) {
  const selected = record?.resolution || record;
  if (!selected) return null;
  assertTaskIdentity(selected, taskId, "model_source_resolution");
  if (
    !selected.resolution_id
    || !selected.content_digest
    || !selected.resolved_commit
  ) return null;
  return canonicalObjectRef("model_source_resolution", taskId, {
    id: selected.resolution_id,
    task_id: selected.task_id,
    digest: selected.content_digest,
    resolved_commit: selected.resolved_commit,
    label: `固定来源 · ${selected.repository || selected.resolution_id}`,
  });
}

function planRef(envelope, taskId) {
  const record = envelope?.plan || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "training_plan");
  if (!record.training_plan_revision_id || !record.plan_sha256 || !record.revision) return null;
  return canonicalObjectRef("training_plan", taskId, {
    id: record.training_plan_revision_id,
    task_id: record.task_id,
    digest: record.plan_sha256,
    revision: record.revision,
    label: `训练计划 · r${record.revision}`,
  });
}

function recipeBuildRef(envelope, taskId) {
  const record = envelope?.build_attempt || envelope?.recipe_build || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "recipe_build");
  if (!record?.attempt_id || !record.candidate_digest || !record.validation_digest) return null;
  return canonicalObjectRef("recipe_build", taskId, {
    id: record.attempt_id,
    task_id: record.task_id,
    candidate_digest: record.candidate_digest,
    validation_digest: record.validation_digest,
    label: `Recipe Build · ${record.attempt_id}`,
  });
}

function bindingAttemptRef(envelope, taskId) {
  const projection = envelope?.binding_attempt || envelope;
  const record = projection?.attempt || projection;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "model_binding_attempt");
  if (!record.attempt_id || !record.content_digest) return null;
  return canonicalObjectRef("model_binding_attempt", taskId, {
    id: record.attempt_id,
    task_id: record.task_id,
    digest: record.content_digest,
    label: `模型绑定任务 · ${record.attempt_id}`,
  });
}

function bindingRef(record, taskId) {
  const selected = record?.binding || record;
  if (!selected) return null;
  assertTaskIdentity(selected, taskId, "model_binding");
  if (!selected.binding_revision_id || !selected.content_digest || !selected.revision) return null;
  return canonicalObjectRef("model_binding", taskId, {
    id: selected.binding_revision_id,
    task_id: selected.task_id,
    digest: selected.content_digest,
    revision: selected.revision,
    label: `模型绑定 · r${selected.revision}`,
  });
}

function repositoryAnalysisRef(envelope, taskId) {
  const record = envelope?.analysis_record || envelope?.analysis || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "repository_analysis");
  if (!record.analysis_id || !record.content_digest) return null;
  return canonicalObjectRef("repository_analysis", taskId, {
    id: record.analysis_id,
    task_id: record.task_id,
    digest: record.content_digest,
    label: `仓库分析 · ${record.analysis_id}`,
  });
}

function assertCanonicalBlockerIdentity(blocker, taskId) {
  const schemaVersion = blocker?.schema_version;
  const legacy = schemaVersion === LEGACY_BLOCKER_EVIDENCE_SCHEMA_VERSION;
  const aliasValid = legacy
    ? blocker?.blocker_evidence_id === undefined
      || blocker.blocker_evidence_id === blocker.blocker_id
    : blocker?.blocker_evidence_id === blocker?.blocker_id;
  if (
    blocker?.task_id !== taskId
    || !READABLE_BLOCKER_EVIDENCE_SCHEMA_VERSIONS.has(schemaVersion)
    || blocker?.object_type !== "BlockerEvidence"
    || typeof blocker?.blocker_id !== "string"
    || !BLOCKER_ID.test(blocker.blocker_id)
    || !aliasValid
    || typeof blocker?.content_digest !== "string"
    || !SHA256.test(blocker.content_digest)
    || blocker.content_digest !== blocker.content_digest.toLowerCase()
  ) {
    throw new Error("BlockerEvidence returned an invalid canonical identity");
  }
  return blocker;
}

function repositoryAnalysisBlockerRefs(envelope, taskId) {
  if (envelope?.blockers === undefined) return [];
  if (!Array.isArray(envelope.blockers)) {
    throw new Error("repository_analysis returned invalid blockers");
  }
  const analysis = envelope?.analysis_record || envelope?.analysis || envelope;
  if (!analysis?.analysis_id || !analysis?.content_digest) {
    throw new Error("repository_analysis blocker lineage is incomplete");
  }
  return envelope.blockers.map((blocker) => {
    assertCanonicalBlockerIdentity(blocker, taskId);
    if (
      blocker.related_object_type !== "RepositoryAnalysis"
      || blocker.related_object_id !== analysis.analysis_id
      || blocker.related_object_digest !== analysis.content_digest
    ) {
      throw new Error("blocker returned invalid repository analysis lineage");
    }
    return canonicalObjectRef("blocker", taskId, {
      id: blocker.blocker_id,
      task_id: blocker.task_id,
      digest: blocker.content_digest,
      label: `阻塞证据 · ${blocker.code || blocker.blocker_id}`,
    });
  });
}

function repositoryAnalysisRefs(envelope, taskId) {
  return [
    repositoryAnalysisRef(envelope, taskId),
    ...repositoryAnalysisBlockerRefs(envelope, taskId),
  ];
}

function taskBlockerRefs(envelope, taskId) {
  const task = envelope?.task || envelope;
  if (!task || typeof task !== "object") {
    throw new Error("TrainingTask returned an invalid canonical identity");
  }
  if (
    typeof taskId !== "string"
    || !taskId
    || taskId !== taskId.trim()
    || task?.task_id !== taskId
  ) {
    throw new Error("TrainingTask returned an invalid canonical identity");
  }
  if (task.blockers === undefined) return [];
  if (!Array.isArray(task.blockers)) {
    throw new Error("TrainingTask returned invalid blockers");
  }
  return task.blockers.map((blocker) => {
    assertCanonicalBlockerIdentity(blocker, taskId);
    return canonicalObjectRef("blocker", taskId, {
      id: blocker.blocker_id,
      task_id: blocker.task_id,
      digest: blocker.content_digest,
      label: `阻塞证据 · ${blocker.code || blocker.blocker_id}`,
    });
  });
}

function resourceFeasibilityRefs(envelope, taskId) {
  const record = envelope?.resource_feasibility || envelope;
  if (!record) return [];
  const refs = [];
  const add = (item, kind, idField, digestField, label) => {
    if (!item) return;
    assertTaskIdentity(item, taskId, "resource_feasibility");
    if (!item[idField] || !item[digestField]) return;
    refs.push(canonicalObjectRef("resource_feasibility", taskId, {
      id: item[idField],
      task_id: item.task_id,
      digest: item[digestField],
      record_kind: kind,
      label,
    }));
  };
  add(record.resource_probe, "resource_probe", "resource_probe_id", "probe_sha256", "本机资源探针");
  add(record.environment_lock, "environment_lock", "environment_lock_id", "lock_sha256", "隔离环境锁");
  add(record.resource_fit_report, "resource_fit_report", "resource_fit_report_id", "report_sha256", "资源适配报告");
  for (const blocker of Array.isArray(record.blockers) ? record.blockers : []) {
    assertCanonicalBlockerIdentity(blocker, taskId);
    refs.push(canonicalObjectRef("blocker", taskId, {
      id: blocker.blocker_id,
      task_id: blocker.task_id,
      digest: blocker.content_digest,
      label: `阻塞证据 · ${blocker.code || blocker.blocker_id}`,
    }));
  }
  return refs;
}

function stagedAssetRef(envelope, taskId) {
  const record = envelope?.asset || envelope?.staged_asset || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "staged_asset");
  if (!record.asset_id || !record.sha256 || !record.spec_revision) return null;
  return canonicalObjectRef("staged_asset", taskId, {
    id: record.asset_id,
    task_id: record.task_id,
    digest: record.sha256,
    revision: record.spec_revision,
    label: `暂存样例 · ${record.asset_id}`,
  });
}

function evaluationReportRef(envelope, taskId, runId) {
  assertRunIdentity(envelope, runId, "evaluation_report");
  const record = envelope?.evaluation_report || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "evaluation_report");
  assertRunIdentity(record, runId, "evaluation_report");
  if (!record.report_id || !record.report_sha256) return null;
  return canonicalObjectRef("evaluation_report", taskId, {
    id: record.report_id,
    task_id: record.task_id,
    run_id: record.run_id || runId,
    digest: record.report_sha256,
    label: `评测报告 · ${record.report_id}`,
  });
}

function inferenceInputRef(envelope, taskId, runId) {
  const record = envelope?.inference_input || envelope;
  if (!record) return null;
  assertTaskIdentity(record, taskId, "inference_input");
  assertRunIdentity(record, runId, "inference_input");
  if (!record.inference_input_id || !record.sha256) return null;
  return canonicalObjectRef("inference_input", taskId, {
    id: record.inference_input_id,
    task_id: record.task_id,
    run_id: record.run_id || runId,
    digest: record.sha256,
    label: `推理样例 · ${record.filename || record.inference_input_id}`,
  });
}

function artifactBundleRef(record, taskId, runId) {
  if (record?.artifact_bundle) {
    assertTaskIdentity(record, taskId, "artifact_bundle");
    assertRunIdentity(record, runId, "artifact_bundle");
  }
  const selected = record?.artifact_bundle || record;
  if (!selected) return null;
  assertTaskIdentity(selected, taskId, "artifact_bundle");
  assertRunIdentity(selected, runId, "artifact_bundle");
  if (!selected.bundle_id || !selected.manifest_sha256) return null;
  return canonicalObjectRef("artifact_bundle", taskId, {
    id: selected.bundle_id,
    task_id: selected.task_id,
    run_id: selected.run_id || runId,
    digest: selected.manifest_sha256,
    label: `交付产物 · ${selected.bundle_id}`,
  });
}

export function apply(ctx) {
  const client = new ModelHarnessClient();
  const runAuthorizationBroker = new RunAuthorizationBroker(client);
  const sampleInferenceAuthorizationBroker = new SampleInferenceAuthorizationBroker(client);
  const artifactBundleAuthorizationBroker = new ArtifactBundleAuthorizationBroker(client);

  ctx.systemPrompt.section({
    name: "domain:model-training-harness",
    order: 118,
    text: `This is the Specialist Model Studio multi-agent training system for people who do not train models professionally. The user experiences one thoughtful AI training partner. Internally, the root session coordinates specialist work, but internal topology is not a product headline. A role-scoped child must follow its specialist persona, remain inside that role and return evidence to the root rather than impersonating the user-facing assistant.
Match delegation to the current lifecycle phase: research_source owns upstream model and source evidence; data_experiment owns dataset and adapter evidence; resource_safety owns plan, isolation and machine-fit evidence; build_training owns trusted Recipe, contract and TrainingRun execution; evaluation_delivery owns EvaluationReport, fresh-sample inference and artifact evidence. Delegate independent bounded questions in parallel, but keep dependent or approval-mutating phases ordered. Give a fresh child a standalone prompt with the exact task_id, current revision or digest and required return format. The Training Orchestrator must synthesize canonical records into the final user-facing conclusion; a delegate's prose is not a replacement for a model_harness_* fact.
For specialist-model training requests, use the model_harness_* tools as the only source of task, dataset, run, metric, artifact, lineage, and approval facts. Do not use shell commands or generic coding tools to bypass the domain lifecycle.
Conversation and training-task lifecycles are separate. An unbound conversation is an intake space, not a TrainingTask. Resolve an ambiguous business outcome first through ordinary conversation in intake mode. Greet a greeting naturally and answer capability, product or process questions directly. For greetings, capability questions and vague model requests, do not call any model_harness_* tool, create a structured checkpoint, delegate a specialist or imply that training has started. Reflect a vague request and ask one concise natural-language question that changes the route; natural intake clarification must not use ask_user_question. The sole model_harness_* exception in intake is model_harness_promote_conversation, and it is allowed only when the user's message provides a concrete desired outcome with enough input/output meaning to become a real training work item. Call it once with the exact conversation id, a short faithful name and a business_goal written in the user's terms. Do not infer that goal from a greeting, task title or earlier unrelated task. Only after promotion succeeds may you call model_harness_get_task, create structured checkpoints, match capabilities or delegate specialists. Never use model_harness_create_task inside an already-created conversation.
In task-bound mode, first decide whether the current message actually advances, queries or changes the bound task. A greeting or general product, capability, method or process question that does not depend on current task facts gets a natural direct answer; do not call model_harness_get_task, create a checkpoint, delegate a specialist, mutate the task or imply that work started. Only for current-task work, read task.control and task.capability_decision before using their facts, then ask exactly one high-impact clarification question at a time. Before capability matching, source search or specialist delegation, separate the user's desired outcome from the implementation method. If “train” or “build” may mean “make this work locally,” clarify the implementation path conversationally. Before recommending an action, check current executable capabilities. Arbitrary external models support discovery, static analysis, planning and resource checks only; do not recommend immediate pretrained inference or adaptation training as an available button. Real training and fresh-sample trials require a registered verified Recipe, matching Data Adapter and their normal evidence and approval gates. Use model_harness_clarify_task_spec when the user answers in their own words, and model_harness_update_task_spec only after the user's business outcome identifies one exact output family. Do not expose a full field checklist unless the user asks to edit advanced details.
Use a human conversation contract, not an operator log. Before each clarification, briefly reflect the outcome you heard in the user's own vocabulary and name the one uncertainty that changes the route. Keep that reflection to one or two short sentences, then ask the question. Do not open with tool activity or internal state such as “I read the task”, “the backend cannot determine”, “the task is in clarification”, or “no capability/Recipe/dataset has been selected”. Do not make the user learn TrainingTask, TaskSpec, Recipe, Data Adapter, ObjectRef, family enum, blocker code, repository revision, workspace path or other implementation vocabulary. Keep raw tool output, ids, digests and detailed risk tables in attached evidence objects rather than the main conversation.
For intake, ordinary prose is the interface; do not render a form card for a greeting, capability question or first clarification. Task binding must not change conversation into a form wizard. Ordinary clarification, follow-up questions, explanations and goal changes stay conversational. Use a native structured question checkpoint only when an actual upload or exact user-owned choice is necessary. If offering choices, explain their consequences and mark unavailable execution paths clearly. Labels should describe familiar outcomes such as “预测未来一周的销量”, “判断一段设备信号是否异常”, or “根据一条客户记录估算金额”, not model-family names. Recommend what best matches the user's goal, never what happens to be easiest for the current implementation. Ask one question at a time; do not combine a file request, target-field question and acceptance-gate checklist in the same turn.

Answer the current question first, then add relevant evidence and one useful next step. Do not repeat the whole plan for a short follow-up. Distinguish technical feasibility from this product's executable capabilities: unsupported here does not mean technically impossible. Sample sizes, method comparisons and error thresholds are suggestions to validate, not unsupported absolutes or user-approved gates. Distinguish a discussed new goal from the saved task; claim the task was changed only after its canonical update tool succeeds. When the old display name explicitly describes the old outcome, align it with the changed goal using the same update_task_spec call's name field; preserve unrelated custom names unless asked.
Treat “time-series model”, “numeric prediction” and “regression” as still ambiguous until temporal semantics are explicit. For a vague time-series request, first distinguish: “预测未来一段时间的销量、流量或温度”; “根据每条独立记录估算一个金额或分数”; or “找出异常时段、判断一段信号的状态”. A natural opening is: “可以。你想让模型利用按时间记录的数据得出结果；现在需要先确认，它是在预测未来，还是判断已经发生的一段数据。” Do not announce that a task record was read. If the user chooses only “numeric prediction” or “regression”, ask whether past order is used to predict a future horizon or whether each row stands alone before selecting an exact family. Select time_series_forecasting for future horizons based on ordered history. Select tabular_regression only when every row is an independent sample and order/time is not part of the prediction. Never remap genuine forecasting to tabular regression merely because tabular regression is currently runnable; explain the current product boundary in plain language and offer source research or a capability-build path instead of pretending to train it.
At the data stage, ask the user to drag a representative file into the conversation or use the visible “导入数据” action. If they are not ready to upload, offer to show a tiny example format or let them paste column names and three to five sample rows. Never ask a human to type a host absolute path or workspace-relative path. Use a native structured question checkpoint when the user is ready to supply a real file or make an exact field selection. If the user has no data, asks why, or changes their goal, first address that message in natural language; do not force a file picker, repeat answered fields or immediately recreate a suspended checkpoint. When the missing input is the training dataset, the native question id must be exactly data_upload and its primary option or action label must be “现在上传 CSV/ZIP”, never “我已上传”. The product file picker performs the upload; submit the data_upload answer only after model_harness_import_dataset has actually succeeded for the same task. A data_upload answer beginning with dataset- is the opaque id of that already-imported Dataset, never a host path. Read the current task, verify that its dataset_id matches, and continue from its dataset_report; never pass an opaque dataset id back into model_harness_import_dataset. Other checkpoints use stable ids such as target_column. An attachment or answer must resolve that same checkpoint so the root session can resume. After an attachment is available, inspect it first and then ask only the next unresolved question using discovered business-facing names, for example which visible column is the value to predict.
After the TaskSpec is resolved, the Universal BYOM workflow is: read official source-provider capabilities; search Hugging Face and GitHub metadata; show candidates with provider, repository, revision, license and risk facts; require the user to select one exact candidate; resolve and bind one immutable commit only with explicit approval; read the static repository analysis; propose an immutable training plan; require approval of the exact plan digest; and run the local resource-feasibility check. Candidate families and search results are not proof of runnable support. Arbitrary repositories may honestly terminate with typed BlockerEvidence when this machine, v0.9 CPU-only policy, dependency metadata, or verified OCI isolation is insufficient. Never execute third-party repository code on the host and never claim every repository can train successfully.
For the three validated built-in capabilities, import and explain the inspection report, review labels or target fields and acceptance gates, collect the three explicit confirmations, start the task run, poll canonical events/results, and explain failures or strategies. After data import succeeds and before presenting contract confirmation, delegate one real bounded inspection to data_experiment with the exact task_id, dataset_id, dataset fingerprint and spec revision, then synthesize only canonical tool evidence returned by that child. Immediately before model_harness_confirm_contract, re-read the canonical TrainingTask and copy all six fields from its current contract_revision: contract_revision_id, contract_sha256, task_id, spec_revision_id, dataset_id and dataset_fingerprint_sha256. The root Training Orchestrator performs this confirmation; the tool's native approval callId becomes the user ApprovalDecision checkpoint_id. Never reuse a cached revision, invent an identity field or confirm after task, spec, contract or dataset drift. Starting a run uses a two-step least-authority handoff: in the root session call model_harness_authorize_task_run_start with the exact current task id, confirmed contract digest, dataset id, dataset fingerprint and spec revision, and let its native approval be the single human start gate. Then delegate build_training as a continuable child (omit run_in_background or set it true; never set it false), pass the returned run_authorization_id, and let that verified child call model_harness_start_task_run exactly once with the same task id and authorization id. After the Run completes, delegate evaluation_delivery with the exact run_id to read the canonical EvaluationReport and return its exact report_id and report_sha256. A new-sample trial also uses a two-step least-authority handoff. If no input object exists yet, ask exactly one native structured question whose id is inference_input_id and whose primary action says “选择新样本”; never ask for a path. The product file picker uploads raw bytes directly to the task/run-bound inference-input endpoint and returns an opaque inference_input_id plus SHA-256; no host path enters chat or a tool call, and upload alone never authorizes execution. In the root session call model_harness_authorize_sample_inference for that exact task, run, input id and digest, then pass its one-shot grant to the same continuable evaluation_delivery child, which may call model_harness_run_sample_inference exactly once without a second native approval. Building a delivery bundle uses another two-step least-authority handoff: the root re-reads the same task, run and EvaluationReport, then calls model_harness_authorize_artifact_bundle_build with the exact task_id, run_id, report identity and optional inference evidence selector; its native approval is the single human bundle-build gate. Delegate or continue evaluation_delivery with the returned artifact_bundle_authorization_id and bundle_request_sha256, and let that verified child call model_harness_build_artifact_bundle exactly once with the identical scope. Never let the child request a second native approval, reuse a grant, change the inference selector or build for another task/run. Download is a separate root-only native approval: re-read the exact bundle_id, manifest_sha256 and archive.sha256, then call model_harness_download_artifact_bundle once with those hashes and a new user-selected ZIP path. Its verified bridge call obtains and consumes a distinct backend one-shot download authorization; a bundle-build grant never authorizes downloading or replay. A specialist is shown only when a real DSH child performed that phase's bounded tool work; never invent decorative expert activity. Do not use an ordinary question as run, sample-inference, bundle-build or bundle-download approval. For an audio-classification task in needs_recipe, ask for a representative class-folder WAV ZIP, stage it, run the trusted declarative Recipe build, show its candidate_digest and validation_digest, and register it only after explicit human approval. model_harness_register_recipe requires the exact existing approval_checkpoint_id; never invent or generate one. The factory never executes generated Python. Other unmatched capabilities remain buildable requests, not runnable training support.
For artifact downloads, interpret “workspace default location” as one new ZIP filename only; the runtime resolves it inside its configured workspace exports directory. Use an absolute ZIP destination only when the user explicitly selected it through the host UI, and never infer a destination from the process working directory.
For an image-classification task, Hugging Face is an optional fixed feature extractor, not arbitrary fine-tuning: inspect capability, search and the model card; require an exact 40-character commit; attach only after native approval and approval_confirmed=true; then verify the local asset before training. Never ask for or transmit a Hugging Face token through chat tools.
After a completed task-owned Run, read the EvaluationReport dimensions before making a release claim. A user-uploaded raw image, WAV or one-row JSON/CSV may be tried only through the task-bound inference_input_id plus the root-approved one-shot sample-inference grant; never accept a local path and never substitute training or test data. Build an Artifact Bundle only from trusted evidence, and download it only to a user-selected new .zip path after native approval. Treat integrity, metric gates, evidence sufficiency and release conclusion as separate facts.
Work like an execution agent, not a form wizard: ask only for information that the tools cannot discover, say what is happening before a meaningful tool call, and after each phase summarize the evidence, the unresolved decision, and the next action. Never reveal private chain-of-thought, hidden reasoning tokens or a fabricated thinking transcript; show only concise action intent, actual tool/delegation status, observed evidence and the resulting decision. Never put a persistent “which agent is handling this” announcement in conversational prose. Mention a specialist role only inside the real action item produced by an actual DSH child. When a requested training capability has no verified Recipe or matching Data Adapter, do not end with a technical inventory dump. Say in plain language that real training is unavailable in the current engine, distinguish that from available source diagnosis, and offer concrete next paths: research candidates, record a capability-build request, or inspect the technical evidence. Pretrained inference and adaptation for arbitrary repositories are not implemented execution paths; never imply otherwise. When a tool returns workbench_url, include it as the evidence view for that same task_id.
Never use the teaching digit run as a substitute for a user's OCR, speech, forecasting, or industrial vision task. Neither the Training Orchestrator nor a specialist child may invent progress, metrics, approvals, files, compatibility, blockers or completed work. Never approve on the user's behalf, treat a delegate statement as approval, weaken a human gate, or describe a queued or running job as completed. A returned workbench_url is an evidence view for the same task_id, not a separate source of truth.`,
  });

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_tasks",
      description: "List persistent user-data training tasks and their canonical lifecycle state. Use this before creating a duplicate task.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: () => ({ card: "generic", title: "List model-training tasks" }),
      async execute(_args, exec) {
        return client.listTasks(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_data_adapters",
      description: "List installed Data Adapters and their supported modalities and file extensions.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.dataAdapters(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_match_capability",
      description: "Explainably match a normalized capability request to installed Recipes before creating a task.",
      parameters: {
        modality: { type: "string", required: true },
        objective: { type: "string", required: true },
        target_kind: { type: "string", required: true },
        data_adapter: { type: "string" },
        tags: { type: "array", items: { type: "string" } },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.matchCapabilities({
          modality: args.modality,
          objective: args.objective,
          target_kind: args.target_kind,
          ...(args.data_adapter ? { data_adapter: args.data_adapter } : {}),
          ...(args.tags ? { tags: args.tags } : {}),
        }, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_create_task",
      description: "Legacy non-conversation entry: create one persistent TrainingTask after a concrete business goal. In an existing conversation use model_harness_promote_conversation instead. This never starts training.",
      parameters: {
        name: { type: "string", required: true, description: "Short user-facing task name." },
        business_goal: { type: "string", required: true, description: "The user's raw business goal without inferred modality or output fields." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Create training task: ${args.name}`, rawInput: args.business_goal }),
      async execute(args, exec) {
        const result = await client.createTask(args.name, args.business_goal, exec.signal);
        return withObjectRefs(
          { ...result, workbench_url: client.workbenchUrl(result.task.task_id) },
          taskBlockerRefs(result, result.task.task_id),
          result.task.task_id,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_promote_conversation",
      description: "Bind one unbound conversation to a real TrainingTask after the user has stated a concrete model outcome. Greetings, capability questions and vague intent must stay unbound and must not call this tool.",
      parameters: {
        conversation_id: { type: "string", required: true, description: "Exact unbound conversation id provided by the host instruction." },
        name: { type: "string", required: true, description: "Short user-facing task name faithful to the concrete outcome." },
        business_goal: { type: "string", required: true, description: "Concrete desired outcome in the user's own terms; never derive this from a greeting or title alone." },
        capability_request: { type: "object", additionalProperties: true, description: "Optional normalized capability only when modality, objective and output are explicit in the conversation." },
        recipe_id: { type: "string", description: "Optional exact verified Recipe selected from observed evidence." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `建立训练任务：${args.name}`, rawInput: args.business_goal }),
      async execute(args, exec) {
        const callId = requireCallId(exec);
        const requestId = `conversation-promote-${createHash("sha256")
          .update(callId)
          .digest("hex")
          .slice(0, 32)}`;
        const result = await client.promoteConversation(args.conversation_id, {
          requestId,
          name: args.name,
          businessGoal: args.business_goal,
          capabilityRequest: args.capability_request,
          recipeId: args.recipe_id,
        }, exec.signal);
        const taskId = String(result?.task?.task_id || result?.conversation?.task_id || "").trim();
        if (!taskId || taskId !== String(args.conversation_id || "").trim()) {
          throw new Error("Conversation promotion did not preserve the canonical conversation/task identity");
        }
        return withObjectRefs(
          { ...result, workbench_url: client.workbenchUrl(taskId) },
          taskBlockerRefs(result, taskId),
          taskId,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_update_task_spec",
      description: "Create an immutable TaskSpec revision after the user explicitly confirms one output family. Keeps the same task_id and never starts training.",
      parameters: {
        task_id: { type: "string", required: true },
        base_revision: { type: "integer", required: true, description: "Current revision returned by model_harness_get_task." },
        selected_family: { type: "string", required: true, enum: TASK_FAMILIES },
        business_goal: { type: "string", description: "Optional corrected business goal in the user's words." },
        name: { type: "string", description: "Optional display name aligned with a changed business goal; preserve an unrelated custom name unless the user requests renaming." },
        user_note: { type: "string", description: "Short reason for the revision." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Confirm task specification ${args.task_id}`, rawInput: args.selected_family }),
      async execute(args, exec) {
        const result = await client.updateTaskSpec(args.task_id, {
          baseRevision: args.base_revision,
          selectedFamily: args.selected_family,
          businessGoal: args.business_goal,
          name: args.name,
          userNote: args.user_note,
        }, exec.signal);
        return withObjectRefs(
          { ...result, workbench_url: client.workbenchUrl(args.task_id) },
          taskBlockerRefs(result, args.task_id),
          args.task_id,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_task",
      description: "Read the canonical task, inspected dataset, frozen contract, current run, results and lineage for one task_id.",
      parameters: {
        task_id: { type: "string", required: true, description: "Task id returned by model_harness_promote_conversation, model_harness_create_task or model_harness_list_tasks." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: (args) => ({ card: "generic", title: `Inspect training task ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.getTask(args.task_id, exec.signal);
        return withObjectRefs(
          { ...result, workbench_url: client.workbenchUrl(args.task_id) },
          taskBlockerRefs(result, args.task_id),
          args.task_id,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_clarify_task_spec",
      description: "Persist the user's free-form clarification as a new immutable TaskSpec revision, then let the backend re-evaluate the one remaining question. This does not confirm a capability or start training.",
      parameters: {
        task_id: { type: "string", required: true },
        base_revision: { type: "integer", required: true },
        business_goal: { type: "string", required: true, description: "Complete revised business goal in the user's words, including their latest clarification." },
        user_note: { type: "string", description: "Short audit note describing the user's clarification." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Clarify task ${args.task_id}`, rawInput: args.user_note || args.business_goal }),
      async execute(args, exec) {
        const result = await client.clarifyTaskSpec(args.task_id, {
          baseRevision: args.base_revision,
          businessGoal: args.business_goal,
          userNote: args.user_note,
        }, exec.signal);
        return withObjectRefs(
          { ...result, workbench_url: client.workbenchUrl(args.task_id) },
          taskBlockerRefs(result, args.task_id),
          args.task_id,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_providers",
      description: "List current Hugging Face and GitHub source-discovery capabilities and limitations before searching.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.modelSourceProviders(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_search_model_sources",
      description: "Search official Hugging Face and GitHub metadata for candidates tied to the current TaskSpec revision. Results are suggestions, not compatibility approval.",
      parameters: {
        task_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        query: { type: "string", description: "Optional search query; omit to let the backend derive it from the confirmed TaskSpec." },
        providers: { type: "array", items: { type: "string", enum: ["huggingface", "github"] } },
        limit_per_provider: { type: "integer", description: "1 to 10 candidates per provider; defaults to 4." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Search model sources for ${args.task_id}`, rawInput: args.query || "TaskSpec-derived query" }),
      async execute(args, exec) {
        const result = await client.searchModelSources(args.task_id, {
          query: args.query,
          providers: args.providers,
          limitPerProvider: args.limit_per_provider === undefined ? 4 : args.limit_per_provider,
          baseSpecRevision: args.base_spec_revision,
        }, exec.signal);
        const searchId = typeof result?.search_id === "string"
          ? result.search_id.trim()
          : "";
        const resultTaskId = typeof result?.task_id === "string"
          ? result.task_id.trim()
          : "";
        const resultRevision = result?.base_spec_revision;
        if (
          !searchId
          || resultTaskId !== args.task_id
          || !Number.isInteger(resultRevision)
          || resultRevision !== args.base_spec_revision
        ) {
          throw new Error("Model-source search returned an invalid canonical identity");
        }
        return {
          ...withObjectRefs(result, [canonicalObjectRef("model_source_search", args.task_id, {
            id: searchId,
            task_id: resultTaskId,
            label: `模型候选 · ${searchId}`,
            base_spec_revision: resultRevision,
          })], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_searches",
      description: "List persisted source searches for one task so the agent can recover after reload without repeating network search.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.listModelSourceSearches(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_select_model_source_candidate",
      description: "Record the user's explicit selection of one exact search candidate and resolve its immutable upstream commit. Selection is approval-gated and does not execute repository code.",
      parameters: {
        task_id: { type: "string", required: true },
        search_id: { type: "string", required: true },
        candidate_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Select model source for ${args.task_id}`, rawInput: args.candidate_id }),
      async execute(args, exec) {
        const result = await client.selectModelSourceCandidate(args.task_id, {
          searchId: args.search_id,
          candidateId: args.candidate_id,
          baseSpecRevision: args.base_spec_revision,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [resolutionRef(result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_resolve_model_source",
      description: "Resolve a user-provided public Hugging Face or GitHub reference to immutable upstream metadata without executing its code.",
      parameters: {
        task_id: { type: "string", required: true },
        source_reference: { type: "string", required: true },
        provider: { type: "string", enum: ["huggingface", "github"] },
        requested_revision: { type: "string" },
        base_spec_revision: { type: "integer", required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Resolve model source for ${args.task_id}`, rawInput: args.source_reference }),
      async execute(args, exec) {
        const result = await client.resolveModelSource(args.task_id, {
          sourceReference: args.source_reference,
          provider: args.provider,
          requestedRevision: args.requested_revision,
          baseSpecRevision: args.base_spec_revision,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [resolutionRef(result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_source_resolutions",
      description: "List persisted fixed-revision resolution records for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.listModelSourceResolutions(args.task_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_bind_model_source",
      description: "Bind one resolved repository at the exact displayed commit and run bounded static analysis. Requires explicit user approval and never executes third-party code.",
      parameters: {
        task_id: { type: "string", required: true },
        resolution_id: { type: "string", required: true },
        expected_resolved_commit: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Bind fixed source for ${args.task_id}`, rawInput: args.expected_resolved_commit }),
      async execute(args, exec) {
        const result = await client.bindModelSource(args.task_id, args.resolution_id, {
          expectedResolvedCommit: args.expected_resolved_commit,
          baseSpecRevision: args.base_spec_revision,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [
            bindingAttemptRef(result, args.task_id),
            ...repositoryAnalysisRefs(result, args.task_id),
          ], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_model_bindings",
      description: "List current, stale and historical model-source bindings for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.listModelBindings(args.task_id, exec.signal);
        const refs = (Array.isArray(result?.bindings) ? result.bindings : [])
          .map((record) => bindingRef(record, args.task_id));
        return {
          ...withObjectRefs(result, refs, args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_repository_analysis",
      description: "Read one immutable static repository analysis, including evidence-backed entrypoint, metric, artifact and dependency candidates.",
      parameters: {
        task_id: { type: "string", required: true },
        analysis_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.repositoryAnalysis(args.task_id, args.analysis_id, exec.signal);
        return {
          ...withObjectRefs(result, repositoryAnalysisRefs(result, args.task_id), args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_create_training_plan",
      description: "Create an immutable training-plan proposal bound to the current TaskSpec, fixed source and analysis evidence. This proposes work but does not approve or execute it.",
      parameters: {
        task_id: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        entrypoint_path: { type: "string" },
        hyperparameters: { type: "object", additionalProperties: true },
        resource_budget: { type: "object", additionalProperties: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Propose training plan for ${args.task_id}`, rawInput: args.entrypoint_path || "analysis-selected entrypoint" }),
      async execute(args, exec) {
        const result = await client.createTrainingPlan(args.task_id, {
          baseSpecRevision: args.base_spec_revision,
          entrypointPath: args.entrypoint_path,
          hyperparameters: args.hyperparameters,
          resourceBudget: args.resource_budget,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [planRef(result?.training_plan || result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_training_plan",
      description: "Read the current immutable training-plan revision and its exact digest and effective approval status.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.currentTrainingPlan(args.task_id, exec.signal);
        return {
          ...withObjectRefs(result, [planRef(result?.training_plan || result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_revise_training_plan",
      description: "Create a child training-plan revision from the exact current parent digest. Earlier approval never carries to the child revision.",
      parameters: {
        task_id: { type: "string", required: true },
        revision_id: { type: "string", required: true },
        expected_parent_sha256: { type: "string", required: true },
        base_spec_revision: { type: "integer", required: true },
        entrypoint_path: { type: "string" },
        hyperparameters: { type: "object", additionalProperties: true },
        resource_budget: { type: "object", additionalProperties: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Revise training plan ${args.revision_id}`, rawInput: args.expected_parent_sha256 }),
      async execute(args, exec) {
        const result = await client.reviseTrainingPlan(args.task_id, args.revision_id, {
          expectedParentSha256: args.expected_parent_sha256,
          baseSpecRevision: args.base_spec_revision,
          entrypointPath: args.entrypoint_path,
          hyperparameters: args.hyperparameters,
          resourceBudget: args.resource_budget,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [planRef(result?.training_plan || result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_decide_training_plan",
      description: "Approve, reject or cancel the exact displayed training-plan digest. Requires explicit user approval and never starts execution by itself.",
      parameters: {
        task_id: { type: "string", required: true },
        revision_id: { type: "string", required: true },
        expected_plan_sha256: { type: "string", required: true },
        decision: { type: "string", required: true, enum: ["approve", "reject", "cancel"] },
        reason: { type: "string", description: "Required for reject and cancel." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `${args.decision} training plan ${args.revision_id}`, rawInput: args.expected_plan_sha256 }),
      async execute(args, exec) {
        const result = await client.decideTrainingPlan(args.task_id, args.revision_id, {
          expectedPlanSha256: args.expected_plan_sha256,
          decision: args.decision,
          reason: args.reason,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [planRef(result?.training_plan || result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_resource_feasibility",
      description: "Read the current resource probe, fit report and typed blockers for one task.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.currentResourceFeasibility(args.task_id, exec.signal);
        return {
          ...withObjectRefs(result, resourceFeasibilityRefs(result, args.task_id), args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_check_resource_feasibility",
      description: "Probe the local machine and compare it with one exact approved plan under the v0.9 CPU-only isolation policy. This may return typed blockers instead of a fit report.",
      parameters: {
        task_id: { type: "string", required: true },
        training_plan_revision_id: { type: "string", required: true },
        expected_plan_sha256: { type: "string", required: true },
        base_image_digest: { type: "string" },
        packages: { type: "array", items: { type: "object", additionalProperties: true } },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Check local resources for ${args.task_id}`, rawInput: args.training_plan_revision_id }),
      async execute(args, exec) {
        const result = await client.checkResourceFeasibility(args.task_id, {
          trainingPlanRevisionId: args.training_plan_revision_id,
          expectedPlanSha256: args.expected_plan_sha256,
          baseImageDigest: args.base_image_digest,
          packages: args.packages,
        }, exec.signal);
        return {
          ...withObjectRefs(result, resourceFeasibilityRefs(result, args.task_id), args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_capability",
      description: "Read the installed Hugging Face capability boundary and dependency status. This does not search, download, attach, or train a model.",
      parameters: {},
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(_args, exec) {
        return client.huggingFaceCapability(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_search",
      description: "Search official Hugging Face metadata for candidate image feature models. Search results are not compatibility approval or attachment.",
      parameters: {
        query: { type: "string", required: true },
        pipeline_tag: { type: "string", description: "Optional official pipeline tag such as image-classification." },
        limit: { type: "integer", description: "Maximum results from 1 to 20; defaults to 10." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      presentCall: (args) => ({ card: "generic", title: `Search Hugging Face: ${args.query}` }),
      async execute(args, exec) {
        return client.searchHuggingFaceModels(args.query, {
          pipelineTag: args.pipeline_tag,
          limit: args.limit === undefined ? 10 : args.limit,
        }, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_card",
      description: "Read one official Hugging Face model card at an optional immutable revision and expose Specialist Model Studio compatibility checks.",
      parameters: {
        repo_id: { type: "string", required: true },
        revision: { type: "string", description: "Prefer an exact 40-character commit SHA." },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return client.huggingFaceModelCard(args.repo_id, args.revision, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_attach",
      description: "Download, verify and attach an approved public Hugging Face ONNX image feature asset at one immutable commit. This is not arbitrary fine-tuning and requires native approval.",
      parameters: {
        task_id: { type: "string", required: true },
        repo_id: { type: "string", required: true },
        commit: { type: "string", required: true, description: "Exact 40-character hexadecimal commit SHA." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Attach ${args.repo_id} to ${args.task_id}`, rawInput: args.commit }),
      async execute(args, exec) {
        const result = await client.attachHuggingFaceModel(
          args.task_id,
          args.repo_id,
          args.commit,
          args.approval_confirmed,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_hf_verify",
      description: "Deep-verify the task's currently attached ModelAsset and its immutable file hashes before training.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.verifyTaskModelAsset(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_import_dataset",
      description: "Import and inspect a user-authorized local dataset through an installed Data Adapter. Built-ins accept class-folder image ZIP and CSV regression data. Ask before calling and never guess a path. A dataset-* value is an already-imported opaque id, not a path; this tool will verify and return its canonical task record without importing again.",
      parameters: {
        task_id: { type: "string", required: true },
        dataset_path: { type: "string", required: true, description: "Absolute path or session-workspace-relative path explicitly provided by the user." },
        target_column: { type: "string", description: "Required for the built-in CSV regression adapter." },
        ignored_columns: { type: "array", items: { type: "string" }, description: "Optional CSV columns excluded from training." },
        delimiter: { type: "string", description: "Optional one-character CSV delimiter." },
        data_adapter: { type: "string", description: "Explicit adapter id when more than one can read the file." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Inspect dataset for ${args.task_id}`, rawInput: args.dataset_path }),
      async execute(args, exec) {
        const datasetReference = String(args.dataset_path || "").trim();
        if (/^dataset-[A-Za-z0-9_-]+$/u.test(datasetReference)) {
          const current = await client.getTask(args.task_id, exec.signal);
          const task = current?.task;
          if (!task || task.dataset_id !== datasetReference) {
            throw new Error("The opaque dataset id does not match the current TrainingTask; refresh the task instead of importing it as a path");
          }
          return {
            ...current,
            already_imported: true,
            dataset_id: task.dataset_id,
            dataset_report: task.dataset_report || null,
            workbench_url: client.workbenchUrl(args.task_id),
          };
        }
        const result = await client.importDataset(args.task_id, args.dataset_path, {
          targetColumn: args.target_column,
          ignoredColumns: args.ignored_columns,
          delimiter: args.delimiter,
          dataAdapter: args.data_adapter,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_scaffold_recipe",
      description: "Generate a reviewable Code Agent build packet for a task in needs_recipe. This does not execute or register generated code.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Generate Recipe build packet for ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.scaffoldRecipe(args.task_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_stage_recipe_samples",
      description: "Stage and safely inspect a user-authorized class-folder WAV ZIP as Recipe construction evidence. This does not create a formal dataset or start training.",
      parameters: {
        task_id: { type: "string", required: true },
        sample_path: { type: "string", required: true, description: "User-provided local .zip path." },
        spec_revision: { type: "integer", description: "Current immutable TaskSpec revision for optimistic concurrency." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Stage Recipe samples for ${args.task_id}`, rawInput: args.sample_path }),
      async execute(args, exec) {
        const result = await client.stageRecipeSamples(
          args.task_id,
          args.sample_path,
          args.spec_revision,
          exec.signal,
        );
        return {
          ...withObjectRefs(result, [stagedAssetRef(result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_build_recipe",
      description: "Compile and validate the trusted declarative audio-keyword Recipe from staged samples. It cannot execute Python, install dependencies, or register itself.",
      parameters: { task_id: { type: "string", required: true } },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Build and validate Recipe for ${args.task_id}` }),
      async execute(args, exec) {
        const result = await client.startRecipeBuild(args.task_id, exec.signal);
        return {
          ...withObjectRefs(result, [recipeBuildRef(result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_recipe_build",
      description: "Read one immutable Recipe build candidate and its validation evidence before an approval decision.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.getRecipeBuild(args.task_id, args.attempt_id, exec.signal);
        return {
          ...withObjectRefs(result, [recipeBuildRef(result, args.task_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_register_recipe",
      description: "Atomically register an already validated declarative Recipe candidate. Requires the exact candidate and validation digests plus explicit human approval.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
        candidate_digest: { type: "string", required: true },
        validation_digest: { type: "string", required: true },
        approval_checkpoint_id: { type: "string", required: true, description: "Existing explicit human-approval checkpoint id; never fabricate or generate this value." },
        reason: { type: "string", description: "Optional human review note." },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Approve Recipe registration ${args.attempt_id}` }),
      async execute(args, exec) {
        const result = await client.registerRecipeBuild(args.task_id, args.attempt_id, {
          candidateDigest: args.candidate_digest,
          validationDigest: args.validation_digest,
          approvalCheckpointId: args.approval_checkpoint_id,
          reason: args.reason,
          approvalConfirmed: args.approval_confirmed,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_reject_recipe",
      description: "Reject a Recipe candidate with a human reason. Rejection never changes the installed Recipe registry.",
      parameters: {
        task_id: { type: "string", required: true },
        attempt_id: { type: "string", required: true },
        actor: { type: "string", required: true },
        reason: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        const result = await client.rejectRecipeBuild(
          args.task_id,
          args.attempt_id,
          args.actor,
          args.reason,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_configure_contract",
      description: "Update explicit offline acceptance gates or image size on an inspected task. This invalidates prior confirmation. Do not lower gates merely to make a run pass.",
      parameters: {
        task_id: { type: "string", required: true },
        accuracy_min: { type: "number", description: "Required clean-test Accuracy from 0 to 1." },
        macro_f1_min: { type: "number", description: "Required clean-test Macro-F1 from 0 to 1." },
        worst_class_recall_min: { type: "number", description: "Required worst-class Recall from 0 to 1." },
        mae_max: { type: "number", description: "Maximum independent-test MAE for regression." },
        rmse_max: { type: "number", description: "Maximum independent-test RMSE for regression." },
        r2_min: { type: "number", description: "Minimum independent-test R-squared for regression." },
        image_size: { type: "integer", enum: [16, 24, 32, 48, 64], description: "Square feature-extraction image size." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Configure training contract ${args.task_id}`, rawInput: JSON.stringify(args) }),
      async execute(args, exec) {
        if ([args.accuracy_min, args.macro_f1_min, args.worst_class_recall_min, args.mae_max, args.rmse_max, args.r2_min, args.image_size].every((value) => value === undefined)) {
          throw new Error("At least one contract field must be provided");
        }
        const result = await client.configureContract(args.task_id, {
          accuracyMin: args.accuracy_min,
          macroF1Min: args.macro_f1_min,
          worstClassRecallMin: args.worst_class_recall_min,
          maeMax: args.mae_max,
          rmseMax: args.rmse_max,
          r2Min: args.r2_min,
          imageSize: args.image_size,
        }, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_confirm_contract",
      description: "Record the user's three explicit confirmations against one exact canonical contract revision. Re-read the task immediately before calling and copy all six immutable identity fields; any task, spec, contract or dataset drift fails closed.",
      parameters: {
        task_id: { type: "string", required: true },
        contract_revision_id: { type: "string", required: true },
        contract_sha256: { type: "string", required: true },
        spec_revision_id: { type: "string", required: true },
        dataset_id: { type: "string", required: true },
        dataset_fingerprint_sha256: { type: "string", required: true },
        data_authorized: { type: "boolean", const: true, required: true },
        labels_reviewed: { type: "boolean", const: true, required: true },
        gates_reviewed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Confirm training contract ${args.task_id}` }),
      async execute(args, exec) {
        const checkpointId = requireCallId(exec);
        const expectedContractRevision = {
          contract_revision_id: args.contract_revision_id,
          contract_sha256: args.contract_sha256,
          task_id: args.task_id,
          spec_revision_id: args.spec_revision_id,
          dataset_id: args.dataset_id,
          dataset_fingerprint_sha256: args.dataset_fingerprint_sha256,
        };
        const result = await client.confirmContract(
          args.task_id,
          {
            data_authorized: args.data_authorized,
            labels_reviewed: args.labels_reviewed,
            gates_reviewed: args.gates_reviewed,
          },
          expectedContractRevision,
          { actor: "user", checkpoint_id: checkpointId },
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_authorize_task_run_start",
      description: "Ask once in the root session for permission to start this exact confirmed task, then issue a short-lived single-use grant bound to its contract, dataset and spec revision. This tool never starts training itself.",
      parameters: {
        task_id: { type: "string", required: true },
        contract_sha256: { type: "string", required: true, description: "Exact confirmed_contract_sha256 from the current TrainingTask." },
        dataset_id: { type: "string", required: true, description: "Exact dataset_id from the current TrainingTask." },
        dataset_fingerprint_sha256: { type: "string", required: true, description: "Exact dataset_report.fingerprint_sha256 from the current TrainingTask." },
        spec_revision: { type: "integer", required: true, description: "Exact current_spec_revision from the current TrainingTask." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `批准启动本次本地训练 · ${args.task_id}` }),
      async execute(args, exec) {
        return runAuthorizationBroker.issue(args, exec);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_start_task_run",
      description: "Start one real background training run from the verified build_training child. Requires the short-lived single-use grant issued by the root's approved model_harness_authorize_task_run_start call.",
      parameters: {
        task_id: { type: "string", required: true },
        run_authorization_id: { type: "string", required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Start real training for ${args.task_id}` }),
      async execute(args, exec) {
        const authorization = await runAuthorizationBroker.consume(args, exec);
        const result = await client.startTaskRun(
          args.task_id,
          {
            authorizationId: authorization.authorization_id,
            authorizationToken: authorization.authorization_token,
            runRequestSha256: authorization.run_request_sha256,
          },
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_recipes",
      description: "List the specialist-model training Recipes currently implemented by the local Specialist Model Studio engine.",
      parameters: {},
      output: jsonOutput,
      async execute(_args, exec) {
        return client.recipes(exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_apply_task_strategy",
      description: "Apply one actionable strategy to a task-owned completed run, creating a child run without replacing the parent. Requires the user's explicit approval of the named strategy.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        strategy_id: { type: "string", required: true },
        approval_confirmed: { type: "boolean", const: true, required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Apply ${args.strategy_id} to ${args.run_id}` }),
      async execute(args, exec) {
        const result = await client.applyTaskStrategy(
          args.task_id,
          args.run_id,
          args.strategy_id,
          args.approval_confirmed,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_run",
      description: "Get canonical state, metrics, optimization history and lineage for one persistent training run.",
      parameters: {
        run_id: { type: "string", required: true, description: "Run id returned by model_harness_start_task_run." },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.status(args.run_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_evaluation_report",
      description: "Read the task-owned EvaluationReport and its separate run, integrity, metric-gate, evidence and conclusion dimensions.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.evaluationReport(args.task_id, args.run_id, exec.signal);
        return {
          ...withObjectRefs(result, [evaluationReportRef(result, args.task_id, args.run_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_authorize_sample_inference",
      description: "Ask once in the root session for permission to run one already-uploaded, task/run-bound inference input, then issue a short-lived single-use grant for the verified evaluation_delivery child. This tool never reads a host path or runs inference itself.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        inference_input_id: { type: "string", required: true, description: "Opaque id returned by the task-bound upload endpoint." },
        inference_input_sha256: { type: "string", required: true, description: "Exact SHA-256 returned with the uploaded inference input." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Confirm one new-sample trial on ${args.run_id}`, rawInput: args.inference_input_id }),
      async execute(args, exec) {
        const grant = await sampleInferenceAuthorizationBroker.issue(args, exec);
        return withObjectRefs(
          grant,
          [canonicalObjectRef("inference_input", args.task_id, {
            id: args.inference_input_id,
            task_id: args.task_id,
            run_id: args.run_id,
            digest: args.inference_input_sha256,
            label: `推理样例 · ${args.inference_input_id}`,
          })],
          args.task_id,
        );
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_run_sample_inference",
      description: "Spend the root-approved one-shot grant from the verified evaluation_delivery child to run one already-uploaded task/run-bound inference input. No host path crosses the conversation or tool boundary.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        inference_input_id: { type: "string", required: true },
        sample_inference_authorization_id: { type: "string", required: true },
        sample_inference_request_sha256: { type: "string", required: true },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `Try one approved new sample on ${args.run_id}`, rawInput: args.inference_input_id }),
      async execute(args, exec) {
        const grant = await sampleInferenceAuthorizationBroker.consume(args, exec);
        const result = await client.runSampleInference(
          args.task_id,
          args.run_id,
          {
            inferenceInputId: args.inference_input_id,
            authorizationId: grant.authorization_id,
            authorizationToken: grant.authorization_token,
            requestSha256: grant.sample_inference_request_sha256,
          },
          exec.signal,
        );
        return {
          ...withObjectRefs(
            result,
            [inferenceInputRef(result, args.task_id, args.run_id)],
            args.task_id,
          ),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_sample_inferences",
      description: "List persisted raw-sample inference checks for one task-owned Run.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.listSampleInferences(args.task_id, args.run_id, exec.signal);
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_sample_inference",
      description: "Read one persisted raw-sample inference inspection and its hash-bound prediction evidence.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        check_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.getSampleInference(
          args.task_id,
          args.run_id,
          args.check_id,
          exec.signal,
        );
        return { ...result, workbench_url: client.workbenchUrl(args.task_id) };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_authorize_artifact_bundle_build",
      description: "Ask once in the root session for permission to build one privacy-filtered Artifact Bundle from this exact completed task-owned Run and EvaluationReport, then issue a short-lived single-use grant for the verified evaluation_delivery child. This tool never builds or downloads the bundle itself.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        evaluation_report_id: { type: "string", required: true, description: "Exact report_id from the current canonical EvaluationReport." },
        evaluation_report_sha256: { type: "string", required: true, description: "Exact report_sha256 from the current canonical EvaluationReport." },
        sample_inference_check_id: { type: "string", description: "Exact passed sample inference check to include; mutually exclusive with inference_check_id." },
        inference_check_id: { type: "string", description: "Exact trusted low-level inference check to include; mutually exclusive with sample_inference_check_id." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `确认构建交付包 · ${args.run_id}` }),
      async execute(args, exec) {
        return artifactBundleAuthorizationBroker.issue(args, exec);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_build_artifact_bundle",
      description: "Build one privacy-filtered, hashed Artifact Bundle from the verified evaluation_delivery child. Requires the root-approved, short-lived single-use grant bound to the exact task, Run, EvaluationReport and optional inference evidence scope. Raw data, test references, absolute paths and internal state remain excluded.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        artifact_bundle_authorization_id: { type: "string", required: true },
        bundle_request_sha256: { type: "string", required: true, description: "Exact bundle_request_sha256 returned by model_harness_authorize_artifact_bundle_build." },
        sample_inference_check_id: { type: "string", description: "Passed raw sample check to include as inference evidence." },
        inference_check_id: { type: "string", description: "Alternative low-level trusted inference check; mutually exclusive with sample_inference_check_id." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `正在生成交付包 · ${args.run_id}` }),
      async execute(args, exec) {
        const authorization = await artifactBundleAuthorizationBroker.consume(args, exec);
        const result = await client.buildArtifactBundle(args.task_id, args.run_id, {
          authorizationId: authorization.authorization_id,
          authorizationToken: authorization.authorization_token,
          bundleRequestSha256: authorization.bundle_request_sha256,
          sampleInferenceCheckId: args.sample_inference_check_id,
          inferenceCheckId: args.inference_check_id,
        }, exec.signal);
        return {
          ...withObjectRefs(result, [artifactBundleRef(result, args.task_id, args.run_id)], args.task_id),
          artifact_bundle_authorization: artifactBundleAuthorizationBroker.audit(
            authorization,
            result?.artifact_bundle,
            result?.artifact_bundle_authorization,
          ),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_list_artifact_bundles",
      description: "List privacy-filtered Artifact Bundles already built for one task-owned Run.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.listArtifactBundles(args.task_id, args.run_id, exec.signal);
        assertRunIdentity(result, args.run_id, "artifact_bundle");
        const refs = (Array.isArray(result?.artifact_bundles) ? result.artifact_bundles : [])
          .map((record) => artifactBundleRef(record, args.task_id, args.run_id));
        return {
          ...withObjectRefs(result, refs, args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_artifact_bundle",
      description: "Read one Artifact Bundle manifest, privacy boundary, hashes and download metadata without returning host filesystem paths.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        bundle_id: { type: "string", required: true },
      },
      output: jsonOutput,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        const result = await client.getArtifactBundle(
          args.task_id,
          args.run_id,
          args.bundle_id,
          exec.signal,
        );
        assertRunIdentity(result, args.run_id, "artifact_bundle");
        return {
          ...withObjectRefs(result, [artifactBundleRef(result, args.task_id, args.run_id)], args.task_id),
          workbench_url: client.workbenchUrl(args.task_id),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_download_artifact_bundle",
      description: "After one native root approval, obtain and immediately consume a backend-persisted single-use download authorization bound to the exact task, Run, bundle, manifest and archive hashes. Verify the downloaded archive and create a new .zip file; a filename-only destination is stored in the configured runtime workspace exports directory, while an absolute destination is used only when the user explicitly selected it. Existing files are never overwritten.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
        bundle_id: { type: "string", required: true },
        manifest_sha256: { type: "string", required: true, description: "Exact current bundle manifest_sha256 approved by the user." },
        archive_sha256: { type: "string", required: true, description: "Exact current bundle archive.sha256 approved by the user." },
        destination_path: { type: "string", required: true, description: "A new .zip filename for the runtime workspace exports directory, or an absolute .zip destination explicitly selected by the user." },
      },
      output: jsonOutput,
      presentCall: (args) => ({ card: "generic", title: `确认下载交付包 · ${args.bundle_id}`, rawInput: args.destination_path }),
      async execute(args, exec) {
        requireRootSessionId(exec);
        const checkpointId = requireCallId(exec);
        const manifestSha256 = String(args.manifest_sha256 || "").trim().toLowerCase();
        const archiveSha256 = String(args.archive_sha256 || "").trim().toLowerCase();
        if (!SHA256.test(manifestSha256) || !SHA256.test(archiveSha256)) {
          throw new Error("Artifact Bundle download requires exact manifest and archive SHA-256 values");
        }
        const detail = await client.getArtifactBundle(
          args.task_id,
          args.run_id,
          args.bundle_id,
          exec.signal,
        );
        const bundle = detail?.artifact_bundle;
        assertTaskIdentity(detail, args.task_id, "artifact_bundle");
        assertRunIdentity(detail, args.run_id, "artifact_bundle");
        if (
          bundle?.bundle_id !== args.bundle_id
          || bundle?.manifest_sha256 !== manifestSha256
          || bundle?.archive?.sha256 !== archiveSha256
        ) {
          throw new Error("Artifact Bundle download approval no longer matches canonical metadata");
        }
        const issued = await client.authorizeArtifactBundleDownload(
          args.task_id,
          args.run_id,
          args.bundle_id,
          {
            manifestSha256,
            archiveSha256,
            approvalCheckpointId: checkpointId,
          },
          exec.signal,
        );
        const authorization = issued?.artifact_bundle_download_authorization;
        const authorizationToken = String(issued?.authorization_token || "").trim();
        const scope = authorization?.scope;
        const scopeSha256 = String(authorization?.scope_sha256 || "").trim().toLowerCase();
        const approval = authorization?.approval_decision;
        const checks = [
          [String(authorization?.action || ""), "download_artifact_bundle", "action"],
          [String(scope?.task_id || ""), args.task_id, "task id"],
          [String(scope?.run_id || ""), args.run_id, "run id"],
          [String(scope?.bundle_id || ""), args.bundle_id, "bundle id"],
          [String(scope?.manifest_sha256 || ""), manifestSha256, "manifest digest"],
          [String(scope?.archive_sha256 || ""), archiveSha256, "archive digest"],
          [String(approval?.actor || ""), "user", "approval actor"],
          [String(approval?.checkpoint_id || ""), checkpointId, "approval checkpoint"],
          [String(approval?.verified_by || ""), "agent_bridge_token", "approval verifier"],
        ];
        for (const [actual, expected, label] of checks) {
          if (actual !== expected) {
            throw new Error(`Artifact Bundle download authorization ${label} changed`);
          }
        }
        if (
          !String(authorization?.authorization_id || "").startsWith("delivery-authorization-")
          || !authorizationToken
          || !SHA256.test(scopeSha256)
        ) {
          throw new Error("Artifact Bundle download authorization is incomplete");
        }
        const downloaded = await client.downloadArtifactBundle(
          args.task_id,
          args.run_id,
          args.bundle_id,
          args.destination_path,
          {
            authorizationId: authorization.authorization_id,
            authorizationToken,
            downloadRequestSha256: scopeSha256,
            manifestSha256,
            archiveSha256,
          },
          exec.signal,
        );
        return {
          ...downloaded,
          artifact_bundle_download_authorization: {
            authorization_id: authorization.authorization_id,
            scope_sha256: scopeSha256,
            approval_decision_id: approval.decision_id,
            approval_checkpoint_id: checkpointId,
            status: "consumed",
            single_use: true,
          },
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_events",
      description: "Read versioned run events after a sequence number. Use this to explain current progress without inventing state.",
      parameters: {
        run_id: { type: "string", required: true },
        after_seq: { type: "integer", description: "Return only events with a larger sequence number." },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.events(args.run_id, args.after_seq || 0, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_get_strategies",
      description: "Get evidence-linked optimization strategies for a completed run. Recommendations are not approvals.",
      parameters: {
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.strategies(args.run_id, exec.signal);
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "model_harness_cancel_run",
      description: "Request cooperative cancellation of a task-owned active run. This never cancels the Agent conversation.",
      parameters: {
        task_id: { type: "string", required: true },
        run_id: { type: "string", required: true },
      },
      output: jsonOutput,
      async execute(args, exec) {
        return client.cancelTaskRun(args.task_id, args.run_id, exec.signal);
      },
    }),
  );

  ctx.on("tools/pre-execute", async (exec, next) => {
    const decision = await next();
    if (decision.kind !== "allow") {
      return decision;
    }
    if (
      SPECIALIST_DELEGATION_TOOLS.has(exec.name)
      && exec.arguments?.run_in_background === false
    ) {
      return {
        kind: "deny",
        reason: "模型训练领域专家必须使用可继续的 DSH 子会话，以持久化并验证精确 role profile。请省略 run_in_background 或设为 true；不能用一次性前台子会话承接权限动作。",
      };
    }
    const roleDecision = roleGateDecision(exec);
    if (roleDecision) return roleDecision;
    if (exec.name === "model_harness_start_task_run") {
      return runAuthorizationBroker.reserve(exec);
    }
    if (exec.name === "model_harness_run_sample_inference") {
      return sampleInferenceAuthorizationBroker.reserve(exec);
    }
    if (exec.name === "model_harness_build_artifact_bundle") {
      return artifactBundleAuthorizationBroker.reserve(exec);
    }
    if (!APPROVAL_REQUIRED_TOOLS.has(exec.name)) return decision;
    if (exec.name === "model_harness_bind_model_source") {
      return { kind: "ask", reason: `确认后绑定固定版本 ${exec.arguments?.expected_resolved_commit || "未提供"} 并读取公开源文件做静态分析；不下载权重、不安装或执行第三方代码、不启动训练。` };
    }
    if (exec.name === "model_harness_authorize_task_run_start") {
      return {
        kind: "ask",
        reason: "确认后，仅允许当前根会话委派的构建与训练专家，按当前合同、数据指纹与任务版本启动一次本地训练；不授权后续优化、发布或其他任务。",
      };
    }
    if (exec.name === "model_harness_authorize_sample_inference") {
      return {
        kind: "ask",
        reason: "确认后，仅允许当前根会话委派的评测与交付专家，对这个 task、已完成 Run 和已上传样例执行一次真实推理；不授权读取本地路径、使用其他样例、重放或发布。",
      };
    }
    if (exec.name === "model_harness_authorize_artifact_bundle_build") {
      return {
        kind: "ask",
        reason: "确认后，仅允许当前根会话委派的评测与交付专家，按当前 task、已完成 Run、EvaluationReport 与所选推理证据构建一次隐私过滤交付包；不授权下载、发布、其他运行或第二次构建。",
      };
    }
    if (exec.name === "model_harness_download_artifact_bundle") {
      return {
        kind: "ask",
        reason: "确认后，仅允许当前根会话通过受保护的 Agent Bridge，为这个 task、已完成 Run、bundle_id、manifest 与 archive 摘要签发并消费一次下载授权，并写入用户选择的新 ZIP；不授权覆盖文件、发布、其他交付包或重放下载。",
      };
    }
    return {
      kind: "ask",
      reason: `Model-training action ${exec.name} changes local task, data, compute, or approval state.`,
    };
  });
}
