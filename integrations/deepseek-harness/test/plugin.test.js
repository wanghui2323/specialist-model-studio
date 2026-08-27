import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  apply,
  inject,
  ROLE_TOOL_ALLOWLISTS,
  TASK_FAMILIES,
} from "../index.js";

process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN = "bridge-test-token";


const PRESET_SOURCE = readFileSync(
  new URL("../presets/model-training/agent.cordis.yml", import.meta.url),
  "utf8",
);
const BUNDLE_PATCH_SOURCE = readFileSync(
  new URL("../cordis.patch.yml", import.meta.url),
  "utf8",
);

test("bundle links only the credential provider to the launcher-selected store", () => {
  assert.match(BUNDLE_PATCH_SOURCE, /^- id: credentials$/m);
  assert.match(
    BUNDLE_PATCH_SOURCE,
    /^    path: !!js process\.env\.MODEL_HARNESS_DSH_CREDENTIALS_FILE \|\| dshHomePath\('\.credentials\.yaml'\)$/m,
  );
  assert.doesNotMatch(BUNDLE_PATCH_SOURCE, /DEEPSEEK_API_KEY|OPENAI_API_KEY/);
});

function parseDelegateBlocks(source) {
  const lines = source.split("\n");
  const startIndexes = lines
    .map((line, index) => (/^    - id: delegate-/.test(line) ? index : -1))
    .filter((index) => index >= 0);
  return startIndexes.map((startIndex) => {
    let endIndex = lines.length;
    for (let index = startIndex + 1; index < lines.length; index += 1) {
      if (/^(?:    )?- id: /.test(lines[index])) {
        endIndex = index;
        break;
      }
    }
    const blockLines = lines.slice(startIndex, endIndex);
    const block = blockLines.join("\n");
    const id = blockLines[0].replace(/^    - id: /, "");
    const toolName = block.match(/^        toolName: (\S+)$/m)?.[1];
    const personaStart = blockLines.findIndex((line) => line === "        persona: >-");
    const filterStart = blockLines.findIndex((line) => line === "        toolFilter:");
    const persona = blockLines
      .slice(personaStart + 1, filterStart)
      .map((line) => line.trim())
      .join(" ");
    const allow = blockLines
      .slice(filterStart + 1)
      .map((line) => line.match(/^            - (\S+)$/)?.[1])
      .filter(Boolean);
    return { id, toolName, persona, allow, block };
  });
}


function mountPlugin() {
  const tools = [];
  const sections = [];
  const listeners = new Map();
  const ctx = {
    tools: { register(tool) { tools.push(tool); } },
    systemPrompt: { section(value) { sections.push(value); } },
    on(name, handler) { listeners.set(name, handler); },
  };
  apply(ctx);
  return { tools, sections, listeners };
}


function rootAgent() {
  return {
    session: {
      header: { id: "root-session" },
      events: [],
    },
  };
}


function specialistAgent(role, options = {}) {
  const seedLength = options.seedLength || 0;
  const seed = Array.from(
    { length: seedLength },
    (_, index) => ({ type: "message", seq: index }),
  );
  const allow = options.allow || ROLE_TOOL_ALLOWLISTS[role];
  return {
    session: {
      header: {
        id: `${role || "unknown"}-session`,
        origin: "subagent",
        parentSession: options.parentSession || "root-session",
        seedLength,
      },
      events: [
        ...seed,
        {
          type: "subagent/descriptor",
          data: {
            version: options.version || 2,
            mode: options.mode || "continuable",
            provider: options.provider || "spawn",
            label: role || "unknown",
            toolFilter: { allow: allow || [] },
          },
        },
      ],
    },
  };
}


async function executeWithPayload(toolName, args, payload) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => "",
  });
  try {
    const tool = mountPlugin().tools.find((item) => item.name === toolName);
    assert.ok(tool, `missing ${toolName}`);
    return await tool.execute(args, { signal: undefined });
  } finally {
    globalThis.fetch = originalFetch;
  }
}


const DIGEST_A = "a".repeat(64);
const DIGEST_B = "b".repeat(64);
const DIGEST_C = "c".repeat(64);
const COMMIT_A = "d".repeat(40);

function canonicalSha256(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function readyTask(overrides = {}) {
  return {
    task_id: "task-ready-1",
    status: "ready",
    contract_confirmed: true,
    confirmed_contract_sha256: DIGEST_A,
    dataset_id: "dataset-1",
    dataset_report: { fingerprint_sha256: DIGEST_B },
    current_spec_revision: 3,
    current_run_id: null,
    pending_run: null,
    ...overrides,
  };
}

function contractTask(overrides = {}) {
  const revision = {
    contract_revision_id: "contract-revision-1",
    contract_sha256: DIGEST_A,
    task_id: "task-contract-1",
    spec_revision_id: "task-contract-1:spec:r3",
    dataset_id: "dataset-contract-1",
    dataset_fingerprint_sha256: DIGEST_B,
  };
  return {
    task_id: revision.task_id,
    status: "data_ready",
    contract_stale: false,
    current_contract_revision_id: revision.contract_revision_id,
    contract_revision: revision,
    task_spec: { revision_id: revision.spec_revision_id },
    dataset_id: revision.dataset_id,
    dataset_report: { fingerprint_sha256: revision.dataset_fingerprint_sha256 },
    ...overrides,
  };
}

function deliveryTask(overrides = {}) {
  return {
    task_id: "task-delivery-1",
    status: "completed",
    run_ids: ["run-delivery-1"],
    current_run_id: "run-delivery-1",
    ...overrides,
  };
}

function deliveryRun(overrides = {}) {
  return {
    task_id: "task-delivery-1",
    run_id: "run-delivery-1",
    status: "completed",
    ...overrides,
  };
}

function deliveryEvaluation(overrides = {}) {
  return {
    task: deliveryTask(),
    run_id: "run-delivery-1",
    evaluation_report: {
      report_id: "evaluation-delivery-1",
      report_sha256: DIGEST_A,
      task_id: "task-delivery-1",
      run_id: "run-delivery-1",
      run_status: "completed",
      integrity_status: "passed",
      ...overrides,
    },
  };
}

function deliveryInferenceInput(overrides = {}) {
  return {
    inference_input: {
      schema_version: "0.1",
      inference_input_id: "inference-input-delivery-1",
      task_id: "task-delivery-1",
      run_id: "run-delivery-1",
      sample_type: "image",
      filename: "new-part.png",
      sha256: DIGEST_C,
      size_bytes: 109,
      status: "staged",
      record_sha256: DIGEST_B,
      ...overrides,
    },
  };
}

function sampleInferenceAuthorization(checkpointId) {
  return {
    sample_inference_authorization: {
      authorization_id: "delivery-authorization-inference-1",
      authorization_sha256: DIGEST_B,
      task_id: "task-delivery-1",
      action: "run_sample_inference",
      scope_sha256: DIGEST_A,
      scope: {
        action: "run_sample_inference",
        task_id: "task-delivery-1",
        run_id: "run-delivery-1",
        inference_input_id: "inference-input-delivery-1",
        inference_input_sha256: DIGEST_C,
        inference_input_record_sha256: DIGEST_B,
        sample_type: "image",
        size_bytes: 109,
      },
      approval_decision: {
        decision_id: "delivery-approval-inference-1",
        actor: "user",
        checkpoint_id: checkpointId,
        verified_by: "agent_bridge_token",
      },
      issued_at_utc: "2026-08-27T00:00:00+00:00",
      expires_at_utc: "2099-08-27T00:10:00+00:00",
    },
    authorization_token: "backend-inference-token",
  };
}

function deliveryBuildAuthorization({ checkpointId, sampleEvidenceSha256 = null } = {}) {
  return {
    artifact_bundle_authorization: {
      authorization_id: "delivery-authorization-build-1",
      authorization_sha256: DIGEST_B,
      task_id: "task-delivery-1",
      action: "build_artifact_bundle",
      scope_sha256: DIGEST_C,
      scope: {
        action: "build_artifact_bundle",
        task_id: "task-delivery-1",
        run_id: "run-delivery-1",
        evaluation_report_id: "evaluation-delivery-1",
        evaluation_report_sha256: DIGEST_A,
        sample_inference_check_id: sampleEvidenceSha256 ? "sample-1" : null,
        inference_check_id: null,
        sample_inference_evidence_sha256: sampleEvidenceSha256,
        inference_evidence_sha256: null,
      },
      approval_decision: {
        decision_id: "delivery-approval-build-1",
        actor: "user",
        checkpoint_id: checkpointId,
        verified_by: "agent_bridge_token",
      },
      issued_at_utc: "2026-08-27T00:00:00+00:00",
      expires_at_utc: "2099-08-27T00:10:00+00:00",
    },
    authorization_token: "backend-build-token",
  };
}

function runStartAuthorization(checkpointId) {
  return {
    run_authorization: {
      authorization_id: "delivery-authorization-run-1",
      authorization_sha256: DIGEST_B,
      task_id: "task-ready-1",
      action: "start_task_run",
      scope_sha256: DIGEST_C,
      scope: {
        action: "start_task_run",
        task_id: "task-ready-1",
        contract_revision_id: "contract-revision-ready-1",
        contract_sha256: DIGEST_A,
        dataset_id: "dataset-1",
        dataset_fingerprint_sha256: DIGEST_B,
        spec_revision: 3,
        spec_revision_id: "task-ready-1:spec:r3",
        contract_approval_decision_id: "approval-contract-ready-1",
      },
      approval_decision: {
        decision_id: "delivery-approval-run-1",
        actor: "user",
        checkpoint_id: checkpointId,
        verified_by: "agent_bridge_token",
      },
      issued_at_utc: "2026-08-27T00:00:00+00:00",
      expires_at_utc: "2099-08-27T00:10:00+00:00",
    },
    authorization_token: "backend-run-token",
  };
}

function jsonResponse(value, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => value,
    text: async () => JSON.stringify(value),
  };
}


test("plugin registers the complete task-first conversational toolchain", () => {
  const mounted = mountPlugin();
  assert.deepEqual(inject, ["tools", "systemPrompt"]);
  const names = new Set(mounted.tools.map((tool) => tool.name));
  assert.equal(names.size, 54);
  for (const required of [
    "model_harness_list_tasks",
    "model_harness_list_data_adapters",
    "model_harness_match_capability",
    "model_harness_create_task",
    "model_harness_update_task_spec",
    "model_harness_get_task",
    "model_harness_clarify_task_spec",
    "model_harness_list_model_source_providers",
    "model_harness_search_model_sources",
    "model_harness_list_model_source_searches",
    "model_harness_select_model_source_candidate",
    "model_harness_resolve_model_source",
    "model_harness_list_model_source_resolutions",
    "model_harness_bind_model_source",
    "model_harness_list_model_bindings",
    "model_harness_get_repository_analysis",
    "model_harness_create_training_plan",
    "model_harness_get_training_plan",
    "model_harness_revise_training_plan",
    "model_harness_decide_training_plan",
    "model_harness_get_resource_feasibility",
    "model_harness_check_resource_feasibility",
    "model_harness_hf_capability",
    "model_harness_hf_search",
    "model_harness_hf_card",
    "model_harness_hf_attach",
    "model_harness_hf_verify",
    "model_harness_import_dataset",
    "model_harness_scaffold_recipe",
    "model_harness_stage_recipe_samples",
    "model_harness_build_recipe",
    "model_harness_get_recipe_build",
    "model_harness_register_recipe",
    "model_harness_reject_recipe",
    "model_harness_configure_contract",
    "model_harness_confirm_contract",
    "model_harness_authorize_task_run_start",
    "model_harness_start_task_run",
    "model_harness_get_events",
    "model_harness_get_run",
    "model_harness_get_evaluation_report",
    "model_harness_authorize_sample_inference",
    "model_harness_run_sample_inference",
    "model_harness_list_sample_inferences",
    "model_harness_get_sample_inference",
    "model_harness_authorize_artifact_bundle_build",
    "model_harness_build_artifact_bundle",
    "model_harness_list_artifact_bundles",
    "model_harness_get_artifact_bundle",
    "model_harness_download_artifact_bundle",
    "model_harness_apply_task_strategy",
  ]) {
    assert.equal(names.has(required), true, `missing ${required}`);
  }
  assert.equal(names.has("model_harness_start_run"), false);
  assert.equal(names.has("model_harness_apply_strategy"), false);
  assert.equal(
    mounted.sections.some((section) => section.name === "domain:model-training-harness"),
    true,
  );
  assert.match(mounted.sections[0].text, /Training Orchestrator/);
  assert.match(mounted.sections[0].text, /research_source owns upstream model and source evidence/);
  assert.match(mounted.sections[0].text, /Delegate independent bounded questions in parallel/);
  assert.match(mounted.sections[0].text, /must synthesize canonical records/);
  assert.match(mounted.sections[0].text, /Never approve on the user's behalf/);
  assert.match(mounted.sections[0].text, /workbench_url/);
  assert.match(mounted.sections[0].text, /EvaluationReport/);
  assert.match(mounted.sections[0].text, /40-character commit/);
  assert.match(mounted.sections[0].text, /ask exactly one high-impact clarification question/);
  assert.match(mounted.sections[0].text, /separate the user's desired outcome from the implementation method/);
  assert.match(mounted.sections[0].text, /first run an existing open model locally \(recommended\)/);
  assert.match(mounted.sections[0].text, /Use a human conversation contract, not an operator log/);
  assert.match(mounted.sections[0].text, /Every decision question must contain two or three plain-language/);
  assert.match(mounted.sections[0].text, /do not end with a technical inventory dump/);
  assert.match(mounted.sections[0].text, /Universal BYOM/);
  assert.match(mounted.sections[0].text, /BlockerEvidence/);
  assert.match(mounted.sections[0].text, /native structured question checkpoint/);
  assert.match(mounted.sections[0].text, /question id must be exactly data_upload/);
  assert.match(mounted.sections[0].text, /“现在上传 CSV\/ZIP”/);
  assert.match(mounted.sections[0].text, /never “我已上传”/);
  assert.match(mounted.sections[0].text, /file picker performs the upload/);
  assert.match(mounted.sections[0].text, /only after model_harness_import_dataset has actually succeeded/);
  assert.match(mounted.sections[0].text, /answer beginning with dataset- is the opaque id of that already-imported Dataset/);
  assert.match(mounted.sections[0].text, /never pass an opaque dataset id back into model_harness_import_dataset/);
  assert.match(mounted.sections[0].text, /question whose id is inference_input_id/);
  assert.match(mounted.sections[0].text, /primary action says “选择新样本”/);
  assert.match(mounted.sections[0].text, /upload alone never authorizes execution/);
  assert.match(mounted.sections[0].text, /model_harness_authorize_task_run_start/);
  assert.match(mounted.sections[0].text, /never set it false/);
  assert.match(mounted.sections[0].text, /copy all six fields from its current contract_revision/);
  assert.match(mounted.sections[0].text, /ApprovalDecision checkpoint_id/);
  assert.match(mounted.sections[0].text, /delegate one real bounded inspection to data_experiment/);
  assert.match(mounted.sections[0].text, /delegate evaluation_delivery with the exact run_id/);
  assert.match(mounted.sections[0].text, /model_harness_authorize_artifact_bundle_build/);
  assert.match(mounted.sections[0].text, /artifact_bundle_authorization_id/);
  assert.match(mounted.sections[0].text, /bundle_request_sha256/);
  assert.match(mounted.sections[0].text, /Never let the child request a second native approval/);
  assert.match(mounted.sections[0].text, /never invent decorative expert activity/);
  assert.match(mounted.sections[0].text, /requires the exact existing approval_checkpoint_id/);
});


test("dataset import treats a product-returned dataset id as an idempotent task lookup", async () => {
  const tool = mountPlugin().tools.find(
    (item) => item.name === "model_harness_import_dataset",
  );
  assert.ok(tool);
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url: String(url), method: options.method || "GET" });
    return jsonResponse({ task: readyTask() });
  };
  try {
    const result = await tool.execute({
      task_id: "task-ready-1",
      dataset_path: "dataset-1",
      target_column: "price",
    }, { signal: undefined });
    assert.equal(result.already_imported, true);
    assert.equal(result.dataset_id, "dataset-1");
    assert.equal(result.dataset_report.fingerprint_sha256, DIGEST_B);
    assert.deepEqual(requests, [{
      url: "http://127.0.0.1:8765/tasks/task-ready-1",
      method: "GET",
    }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("dataset import rejects an opaque id that is not owned by the current task", async () => {
  const tool = mountPlugin().tools.find(
    (item) => item.name === "model_harness_import_dataset",
  );
  assert.ok(tool);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => jsonResponse({ task: readyTask() });
  try {
    await assert.rejects(
      () => tool.execute({
        task_id: "task-ready-1",
        dataset_path: "dataset-other",
      }, { signal: undefined }),
      /does not match the current TrainingTask/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("Recipe registration tool requires an external approval checkpoint id", async () => {
  const tool = mountPlugin().tools.find(
    (item) => item.name === "model_harness_register_recipe",
  );
  assert.ok(tool);
  assert.ok(tool.parameters.required.includes("approval_checkpoint_id"));
  assert.equal("actor" in tool.parameters.properties, false);
  await assert.rejects(
    () => tool.execute({
      task_id: "audio-task",
      attempt_id: "recipe-build-1",
      candidate_digest: DIGEST_A,
      validation_digest: DIGEST_B,
      approval_confirmed: true,
    }, { signal: undefined }),
    /approval_checkpoint_id/,
  );
});


test("artifact bundle tools require an exact root-approved request scope", () => {
  const mounted = mountPlugin();
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_artifact_bundle_build",
  );
  const build = mounted.tools.find(
    (tool) => tool.name === "model_harness_build_artifact_bundle",
  );
  assert.ok(authorize);
  assert.ok(build);
  assert.deepEqual(
    authorize.parameters.required.sort(),
    ["evaluation_report_id", "evaluation_report_sha256", "run_id", "task_id"],
  );
  assert.equal(build.parameters.properties.artifact_bundle_authorization_id.type, "string");
  assert.equal(build.parameters.properties.bundle_request_sha256.type, "string");
  assert.ok(build.parameters.required.includes("artifact_bundle_authorization_id"));
  assert.ok(build.parameters.required.includes("bundle_request_sha256"));
});


test("contract confirmation tool requires the complete immutable revision identity", () => {
  const tool = mountPlugin().tools.find(
    (item) => item.name === "model_harness_confirm_contract",
  );
  assert.ok(tool);
  for (const field of [
    "task_id",
    "contract_revision_id",
    "contract_sha256",
    "spec_revision_id",
    "dataset_id",
    "dataset_fingerprint_sha256",
    "data_authorized",
    "labels_reviewed",
    "gates_reviewed",
  ]) {
    assert.ok(tool.parameters.required.includes(field), `${field} is required`);
  }
});


test("contract confirmation revalidates canonical identity and binds ApprovalDecision to callId", async () => {
  const mounted = mountPlugin();
  const tool = mounted.tools.find(
    (item) => item.name === "model_harness_confirm_contract",
  );
  let canonicalTask = contractTask();
  const args = {
    task_id: canonicalTask.task_id,
    ...canonicalTask.contract_revision,
    data_authorized: true,
    labels_reviewed: true,
    gates_reviewed: true,
  };
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    const requestUrl = new URL(url);
    const method = options.method || "GET";
    requests.push({
      method,
      url: requestUrl.pathname,
      body: options.body ? JSON.parse(options.body) : null,
    });
    if (method === "GET" && requestUrl.pathname === "/tasks/task-contract-1") {
      return jsonResponse({ task: canonicalTask });
    }
    if (method === "POST" && requestUrl.pathname === "/tasks/task-contract-1/confirm") {
      return jsonResponse({ task: { ...canonicalTask, status: "ready" } });
    }
    throw new Error(`unexpected request ${method} ${requestUrl.pathname}`);
  };

  try {
    const result = await tool.execute(args, {
      callId: "dsh-contract-confirm-call-1",
      agent: rootAgent(),
      signal: undefined,
    });
    assert.equal(result.task.status, "ready");
    assert.deepEqual(requests.map((request) => [request.method, request.url]), [
      ["GET", "/tasks/task-contract-1"],
      ["POST", "/tasks/task-contract-1/confirm"],
    ]);
    assert.deepEqual(requests[1].body, {
      data_authorized: true,
      labels_reviewed: true,
      gates_reviewed: true,
      expected_contract_revision: canonicalTask.contract_revision,
      approval: {
        actor: "user",
        checkpoint_id: "dsh-contract-confirm-call-1",
      },
    });

    requests.length = 0;
    canonicalTask = contractTask({
      dataset_report: { fingerprint_sha256: DIGEST_C },
    });
    await assert.rejects(
      () => tool.execute(args, {
        callId: "dsh-contract-confirm-call-stale",
        agent: rootAgent(),
        signal: undefined,
      }),
      /Canonical contract revision changed/,
    );
    assert.deepEqual(requests.map((request) => [request.method, request.url]), [
      ["GET", "/tasks/task-contract-1"],
    ]);

    requests.length = 0;
    await assert.rejects(
      () => tool.execute(args, { agent: rootAgent(), signal: undefined }),
      /verifiable DSH tool call id/,
    );
    assert.equal(requests.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("coordinator prompt keeps vague forecasting and data collection human-native", () => {
  const prompt = mountPlugin().sections.find(
    (section) => section.name === "domain:model-training-harness",
  )?.text;
  assert.ok(prompt);

  assert.match(prompt, /briefly reflect the outcome you heard in the user's own vocabulary/);
  assert.match(prompt, /Resolve an ambiguous business outcome first/);
  assert.match(prompt, /Do not open with tool activity or internal state/);
  assert.match(prompt, /Labels should describe familiar outcomes/);
  assert.match(prompt, /Recommend what best matches the user's goal, never what happens to be easiest/);
  assert.match(prompt, /Treat “time-series model”, “numeric prediction” and “regression” as still ambiguous/);
  assert.match(prompt, /“预测未来一段时间的销量、流量或温度”/);
  assert.match(prompt, /ask whether past order is used to predict a future horizon or whether each row stands alone/);
  assert.match(prompt, /Select time_series_forecasting for future horizons based on ordered history/);
  assert.match(prompt, /Select tabular_regression only when every row is an independent sample/);
  assert.match(prompt, /Never remap genuine forecasting to tabular regression/);
  assert.match(prompt, /drag a representative file into the conversation/);
  assert.match(prompt, /Never ask a human to type a host absolute path or workspace-relative path/);
  assert.match(prompt, /inspect it first and then ask only the next unresolved question/);
  assert.match(prompt, /question id must be exactly data_upload/);
  assert.match(prompt, /primary option or action label must be “现在上传 CSV\/ZIP”/);
  assert.match(prompt, /never “我已上传”/);
  assert.match(prompt, /The product file picker performs the upload/);
  assert.match(prompt, /submit the data_upload answer only after model_harness_import_dataset has actually succeeded/);
  assert.match(prompt, /Other checkpoints use stable ids such as target_column/);
  assert.match(prompt, /never stop the turn with only a prose request/);
});


test("model-source search returns one canonical ObjectRef", async () => {
  const originalFetch = globalThis.fetch;
  let observedRequest;
  let backendPayload = {
    search_id: "search-0a1b2c",
    task_id: "task-voice",
    base_spec_revision: 3,
    candidates: [],
  };
  globalThis.fetch = async (url, options) => {
    observedRequest = { url: String(url), options };
    return {
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => backendPayload,
      text: async () => "",
    };
  };

  try {
    const mounted = mountPlugin();
    const searchTool = mounted.tools.find(
      (tool) => tool.name === "model_harness_search_model_sources",
    );
    assert.ok(searchTool);
    const result = await searchTool.execute(
      {
        task_id: "task-voice",
        base_spec_revision: 3,
        query: "voice cloning",
        providers: ["huggingface", "github"],
      },
      { signal: undefined },
    );

    assert.deepEqual(result.object_refs, [
      {
        type: "model_source_search",
        id: "search-0a1b2c",
        task_id: "task-voice",
        label: "模型候选 · search-0a1b2c",
        base_spec_revision: 3,
      },
    ]);
    assert.equal(
      observedRequest.url,
      "http://127.0.0.1:8765/tasks/task-voice/model-source-searches",
    );
    assert.deepEqual(JSON.parse(observedRequest.options.body), {
      query: "voice cloning",
      providers: ["huggingface", "github"],
      limit_per_provider: 4,
      base_spec_revision: 3,
    });

    backendPayload = {
      search_id: "search-wrong-owner",
      task_id: "another-task",
      base_spec_revision: 3,
      candidates: [],
    };
    await assert.rejects(
      () => searchTool.execute(
        {
          task_id: "task-voice",
          base_spec_revision: 3,
          query: "voice cloning",
        },
        { signal: undefined },
      ),
      /invalid canonical identity/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("source resolution ObjectRefs require exact task, digest, and immutable commit", async () => {
  const taskId = "task-source";
  const resolution = {
    resolution_id: "resolution-1",
    task_id: taskId,
    content_digest: DIGEST_A,
    resolved_commit: COMMIT_A,
    repository: "owner/repo",
  };
  const selected = await executeWithPayload(
    "model_harness_select_model_source_candidate",
    {
      task_id: taskId,
      search_id: "search-1",
      candidate_id: "candidate-1",
      base_spec_revision: 2,
      approval_confirmed: true,
    },
    { resolution },
  );
  assert.deepEqual(selected.object_refs, [{
    type: "model_source_resolution",
    id: "resolution-1",
    task_id: taskId,
    label: "固定来源 · owner/repo",
    digest: DIGEST_A,
    resolved_commit: COMMIT_A,
  }]);
  assert.equal(selected.workbench_url, `http://127.0.0.1:8765/app?task=${taskId}`);

  const redacted = await executeWithPayload(
    "model_harness_resolve_model_source",
    {
      task_id: taskId,
      source_reference: "owner/repo",
      base_spec_revision: 2,
    },
    { resolution: { ...resolution, repository: "/Users/private/Bearer ghp_secret123" } },
  );
  assert.match(redacted.object_refs[0].label, /redacted|model source resolution/i);
  assert.doesNotMatch(JSON.stringify(redacted.object_refs), /\/Users\/|ghp_secret123/);

  await assert.rejects(
    () => executeWithPayload(
      "model_harness_resolve_model_source",
      {
        task_id: taskId,
        source_reference: "owner/repo",
        base_spec_revision: 2,
      },
      { resolution: { ...resolution, task_id: "another-task" } },
    ),
    /invalid canonical identity/,
  );
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_resolve_model_source",
      {
        task_id: taskId,
        source_reference: "owner/repo",
        base_spec_revision: 2,
      },
      { resolution: { ...resolution, content_digest: "bad-digest" } },
    ),
    /invalid digest/,
  );
  const incomplete = await executeWithPayload(
    "model_harness_resolve_model_source",
    {
      task_id: taskId,
      source_reference: "owner/repo",
      base_spec_revision: 2,
    },
    { resolution: { ...resolution, content_digest: undefined } },
  );
  assert.equal("object_refs" in incomplete, false);
});


test("binding, repository analysis, and plan tools emit their persisted identities", async () => {
  const taskId = "task-lifecycle";
  const bindingAttempt = await executeWithPayload(
    "model_harness_bind_model_source",
    {
      task_id: taskId,
      resolution_id: "resolution-1",
      expected_resolved_commit: COMMIT_A,
      base_spec_revision: 1,
      approval_confirmed: true,
    },
    {
      binding_attempt: {
        attempt: {
          attempt_id: "binding-attempt-1",
          task_id: taskId,
          content_digest: DIGEST_A,
        },
        current_state: { status: "queued" },
      },
    },
  );
  assert.deepEqual(bindingAttempt.object_refs[0], {
    type: "model_binding_attempt",
    id: "binding-attempt-1",
    task_id: taskId,
    label: "模型绑定任务 · binding-attempt-1",
    digest: DIGEST_A,
  });
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_bind_model_source",
      {
        task_id: taskId,
        resolution_id: "resolution-1",
        expected_resolved_commit: COMMIT_A,
        base_spec_revision: 1,
        approval_confirmed: true,
      },
      {
        binding_attempt: {
          attempt: {
            attempt_id: "binding-attempt-foreign",
            task_id: "other-task",
            content_digest: DIGEST_A,
          },
        },
      },
    ),
    /invalid canonical identity/,
  );

  const bindings = await executeWithPayload(
    "model_harness_list_model_bindings",
    { task_id: taskId },
    {
      bindings: [{
        binding_revision_id: "binding-r2",
        task_id: taskId,
        content_digest: DIGEST_B,
        revision: 2,
      }],
    },
  );
  assert.deepEqual(bindings.object_refs[0], {
    type: "model_binding",
    id: "binding-r2",
    task_id: taskId,
    label: "模型绑定 · r2",
    digest: DIGEST_B,
    revision: 2,
  });
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_list_model_bindings",
      { task_id: taskId },
      {
        bindings: [{
          binding_revision_id: "binding-r2",
          task_id: taskId,
          content_digest: "bad",
          revision: 2,
        }],
      },
    ),
    /invalid digest/,
  );

  const analysis = await executeWithPayload(
    "model_harness_get_repository_analysis",
    { task_id: taskId, analysis_id: "analysis-1" },
    {
      analysis: {
        analysis_id: "analysis-1",
        task_id: taskId,
        content_digest: DIGEST_C,
      },
    },
  );
  assert.equal(analysis.object_refs[0].type, "repository_analysis");
  assert.equal(analysis.object_refs[0].digest, DIGEST_C);

  const planRecord = {
    training_plan_revision_id: "plan-r3",
    task_id: taskId,
    plan_sha256: DIGEST_A,
    revision: 3,
  };
  for (const [toolName, args] of [
    ["model_harness_create_training_plan", { task_id: taskId, base_spec_revision: 1 }],
    ["model_harness_get_training_plan", { task_id: taskId }],
    ["model_harness_revise_training_plan", {
      task_id: taskId,
      revision_id: "plan-r2",
      expected_parent_sha256: DIGEST_B,
      base_spec_revision: 1,
    }],
    ["model_harness_decide_training_plan", {
      task_id: taskId,
      revision_id: "plan-r3",
      expected_plan_sha256: DIGEST_A,
      decision: "approve",
      approval_confirmed: true,
    }],
  ]) {
    const result = await executeWithPayload(toolName, args, {
      training_plan: { plan: planRecord },
    });
    assert.deepEqual(result.object_refs[0], {
      type: "training_plan",
      id: "plan-r3",
      task_id: taskId,
      label: "训练计划 · r3",
      digest: DIGEST_A,
      revision: 3,
    });
  }
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_training_plan",
      { task_id: taskId },
      { training_plan: { plan: { ...planRecord, plan_sha256: "bad" } } },
    ),
    /invalid digest/,
  );
});


test("repository analysis emits only exact task-owned blocker evidence", async () => {
  const taskId = "task-blocked-analysis";
  const analysisRecord = {
    analysis_id: "analysis-blocked-1",
    task_id: taskId,
    content_digest: DIGEST_C,
    revision: 1,
    status: "blocked",
  };
  const blocker = {
    blocker_id: "blocker-analysis-1",
    task_id: taskId,
    content_digest: DIGEST_A,
    code: "blocked_security",
    related_object_type: "RepositoryAnalysis",
    related_object_id: analysisRecord.analysis_id,
    related_object_digest: analysisRecord.content_digest,
  };
  const blocked = await executeWithPayload(
    "model_harness_get_repository_analysis",
    { task_id: taskId, analysis_id: analysisRecord.analysis_id },
    {
      analysis: { analysis_id: analysisRecord.analysis_id, task_id: taskId, status: "blocked" },
      analysis_record: analysisRecord,
      blockers: [blocker],
    },
  );
  assert.deepEqual(
    blocked.object_refs.map((ref) => [ref.type, ref.id, ref.task_id, ref.digest]),
    [
      ["repository_analysis", analysisRecord.analysis_id, taskId, DIGEST_C],
      ["blocker", blocker.blocker_id, taskId, DIGEST_A],
    ],
  );

  const completed = await executeWithPayload(
    "model_harness_get_repository_analysis",
    { task_id: taskId, analysis_id: "analysis-complete-1" },
    {
      analysis: { analysis_id: "analysis-complete-1", task_id: taskId, status: "complete" },
      analysis_record: {
        ...analysisRecord,
        analysis_id: "analysis-complete-1",
        status: "complete",
      },
      blockers: [],
    },
  );
  assert.deepEqual(completed.object_refs.map((ref) => ref.type), ["repository_analysis"]);

  for (const invalidBlocker of [
    { ...blocker, task_id: "other-task" },
    { ...blocker, blocker_id: undefined },
    { ...blocker, related_object_id: "analysis-other" },
  ]) {
    await assert.rejects(
      () => executeWithPayload(
        "model_harness_get_repository_analysis",
        { task_id: taskId, analysis_id: analysisRecord.analysis_id },
        {
          analysis: { analysis_id: analysisRecord.analysis_id, task_id: taskId, status: "blocked" },
          analysis_record: analysisRecord,
          blockers: [invalidBlocker],
        },
      ),
      /invalid canonical identity|invalid repository analysis lineage/,
    );
  }
});


test("resource feasibility emits exact probe, lock, report, and blocker refs", async () => {
  const taskId = "task-resource";
  const feasibility = {
    resource_probe: {
      resource_probe_id: "probe-1",
      task_id: taskId,
      probe_sha256: DIGEST_A,
    },
    environment_lock: {
      environment_lock_id: "lock-1",
      task_id: taskId,
      lock_sha256: DIGEST_B,
    },
    resource_fit_report: {
      resource_fit_report_id: "report-1",
      task_id: taskId,
      report_sha256: DIGEST_C,
    },
    blockers: [{
      blocker_id: "blocker-1",
      task_id: taskId,
      content_digest: DIGEST_A,
      code: "blocked_resources",
    }],
  };
  for (const [toolName, args] of [
    ["model_harness_get_resource_feasibility", { task_id: taskId }],
    ["model_harness_check_resource_feasibility", {
      task_id: taskId,
      training_plan_revision_id: "plan-r1",
      expected_plan_sha256: DIGEST_A,
    }],
  ]) {
    const result = await executeWithPayload(toolName, args, {
      resource_feasibility: feasibility,
    });
    assert.deepEqual(
      result.object_refs.map((ref) => [ref.type, ref.id, ref.record_kind]),
      [
        ["resource_feasibility", "probe-1", "resource_probe"],
        ["resource_feasibility", "lock-1", "environment_lock"],
        ["resource_feasibility", "report-1", "resource_fit_report"],
        ["blocker", "blocker-1", undefined],
      ],
    );
  }
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_resource_feasibility",
      { task_id: taskId },
      {
        resource_feasibility: {
          ...feasibility,
          resource_probe: { ...feasibility.resource_probe, probe_sha256: "bad" },
        },
      },
    ),
    /invalid digest/,
  );
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_resource_feasibility",
      { task_id: taskId },
      {
        resource_feasibility: {
          ...feasibility,
          blockers: [{ ...feasibility.blockers[0], task_id: "other-task" }],
        },
      },
    ),
    /invalid canonical identity/,
  );
});


test("staged assets and complete Recipe builds emit refs while partial builds do not", async () => {
  const taskId = "task-recipe";
  const temporary = await mkdtemp(join(tmpdir(), "harness-plugin-"));
  const samplePath = join(temporary, "samples.zip");
  await writeFile(samplePath, Buffer.from("zip fixture"));
  try {
    const staged = await executeWithPayload(
      "model_harness_stage_recipe_samples",
      { task_id: taskId, sample_path: samplePath, spec_revision: 4 },
      {
        asset: {
          asset_id: "asset-1",
          task_id: taskId,
          sha256: DIGEST_A,
          spec_revision: 4,
        },
      },
    );
    assert.deepEqual(staged.object_refs[0], {
      type: "staged_asset",
      id: "asset-1",
      task_id: taskId,
      label: "暂存样例 · asset-1",
      digest: DIGEST_A,
      revision: 4,
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }

  const build = {
    attempt_id: "recipe-build-1",
    task_id: taskId,
    candidate_digest: DIGEST_B,
    validation_digest: DIGEST_C,
  };
  const created = await executeWithPayload(
    "model_harness_build_recipe",
    { task_id: taskId },
    { build_attempt: build },
  );
  const fetched = await executeWithPayload(
    "model_harness_get_recipe_build",
    { task_id: taskId, attempt_id: build.attempt_id },
    { recipe_build: build },
  );
  assert.deepEqual(created.object_refs, fetched.object_refs);
  assert.deepEqual(created.object_refs[0], {
    type: "recipe_build",
    id: "recipe-build-1",
    task_id: taskId,
    label: "Recipe Build · recipe-build-1",
    candidate_digest: DIGEST_B,
    validation_digest: DIGEST_C,
  });
  const partial = await executeWithPayload(
    "model_harness_get_recipe_build",
    { task_id: taskId, attempt_id: build.attempt_id },
    { recipe_build: { ...build, validation_digest: undefined } },
  );
  assert.equal("object_refs" in partial, false);
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_recipe_build",
      { task_id: taskId, attempt_id: build.attempt_id },
      { recipe_build: { ...build, validation_digest: "bad" } },
    ),
    /invalid validation_digest/,
  );
});


test("evaluation and existing artifact refs preserve exact run identity across get and list", async () => {
  const taskId = "task-delivery";
  const runId = "run-1";
  const report = {
    report_id: "evaluation-1",
    task_id: taskId,
    run_id: runId,
    report_sha256: DIGEST_A,
  };
  const evaluated = await executeWithPayload(
    "model_harness_get_evaluation_report",
    { task_id: taskId, run_id: runId },
    { task: { task_id: taskId }, run_id: runId, evaluation_report: report },
  );
  assert.deepEqual(evaluated.object_refs[0], {
    type: "evaluation_report",
    id: "evaluation-1",
    task_id: taskId,
    label: "评测报告 · evaluation-1",
    digest: DIGEST_A,
    run_id: runId,
  });

  const bundle = {
    bundle_id: "bundle-1",
    task_id: taskId,
    run_id: runId,
    manifest_sha256: DIGEST_B,
  };
  const cases = [
    ["model_harness_get_artifact_bundle", { task_id: taskId, run_id: runId, bundle_id: bundle.bundle_id }, { run_id: runId, artifact_bundle: bundle }],
    ["model_harness_list_artifact_bundles", { task_id: taskId, run_id: runId }, { run_id: runId, artifact_bundles: [bundle] }],
  ];
  for (const [toolName, args, payload] of cases) {
    const result = await executeWithPayload(toolName, args, payload);
    assert.deepEqual(result.object_refs[0], {
      type: "artifact_bundle",
      id: "bundle-1",
      task_id: taskId,
      label: "交付产物 · bundle-1",
      digest: DIGEST_B,
      run_id: runId,
    });
  }

  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_evaluation_report",
      { task_id: taskId, run_id: runId },
      { run_id: "run-other", evaluation_report: report },
    ),
    /invalid run identity/,
  );
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_artifact_bundle",
      { task_id: taskId, run_id: runId, bundle_id: bundle.bundle_id },
      { run_id: runId, artifact_bundle: { ...bundle, manifest_sha256: "bad" } },
    ),
    /invalid digest/,
  );
  await assert.rejects(
    () => executeWithPayload(
      "model_harness_get_artifact_bundle",
      { task_id: taskId, run_id: runId, bundle_id: bundle.bundle_id },
      { run_id: "run-other", artifact_bundle: bundle },
    ),
    /invalid run identity/,
  );
});


test("model-training preset registers five continuable role delegates", () => {
  const delegates = parseDelegateBlocks(PRESET_SOURCE);
  assert.equal(delegates.length, 5);
  assert.deepEqual(
    delegates.map((delegate) => delegate.toolName),
    Object.keys(ROLE_TOOL_ALLOWLISTS),
  );

  for (const delegate of delegates) {
    assert.match(delegate.id, /^delegate-/);
    assert.match(delegate.block, /^      name: '@deepseek-ai\/dsh-tool-subagent'$/m);
    assert.match(delegate.block, /^        provider: spawn$/m);
    assert.match(delegate.block, /^        backgroundMode: continuable$/m);
    assert.match(delegate.block, /^        maxDepth: 1$/m);
    assert.match(delegate.persona, /Agent/);
    assert.match(delegate.persona, /model_harness_\*/);
    assert.match(delegate.persona, /Training Orchestrator owns synthesis/);
    assert.match(delegate.persona, /Never/);
    assert.deepEqual(delegate.allow, ROLE_TOOL_ALLOWLISTS[delegate.toolName]);
  }
});


test("role delegates expose only domain facts and no shell or generic tools", () => {
  const delegates = parseDelegateBlocks(PRESET_SOURCE);
  for (const delegate of delegates) {
    assert.ok(delegate.allow.length > 0, `${delegate.toolName} requires a non-empty allowlist`);
    for (const toolName of delegate.allow) {
      assert.match(toolName, /^model_harness_[a-z0-9_]+$/);
      assert.doesNotMatch(
        toolName,
        /(?:shell|bash|terminal|exec|read_file|write_file|subagent|computer|browser|web_search|generic)/,
      );
    }
  }
  assert.doesNotMatch(PRESET_SOURCE, /^        toolName: subagent$/m);
});


test("root persona is an evidence-bound Training Orchestrator", () => {
  const rootPersona = PRESET_SOURCE.match(
    /^    text: >-\n([\s\S]*?)\n\n- id: agent-instructions$/m,
  )?.[1];
  assert.ok(rootPersona);
  assert.match(rootPersona, /You are the Training Orchestrator/);
  for (const role of Object.keys(ROLE_TOOL_ALLOWLISTS)) {
    assert.match(rootPersona, new RegExp(role));
  }
  assert.match(rootPersona, /Start independent delegations[\s\S]*in parallel/);
  assert.match(rootPersona, /keep dependent phases ordered/);
  assert.match(rootPersona, /combining their evidence into one user-facing/);
  assert.match(rootPersona, /Never fabricate progress, results, files, metrics/);
  assert.match(rootPersona, /Never approve on the user's behalf/);
  assert.match(rootPersona, /distinguish the[\s\S]*desired outcome from the implementation method/);
  assert.match(rootPersona, /run an[\s\S]*existing open model first \(recommended\)/);
  assert.match(rootPersona, /Speak like a thoughtful model-training partner, not an operator log/);
  assert.match(rootPersona, /A vague “time-series model”, “numeric prediction” or “regression” is not enough/);
  assert.match(rootPersona, /Select time_series_forecasting[\s\S]*tabular_regression only/);
  assert.match(rootPersona, /Never ask the user to type an absolute or workspace-relative path/);
  assert.match(rootPersona, /native structured[\s\S]*question checkpoint/);
  assert.match(rootPersona, /question id must be exactly data_upload/);
  assert.match(rootPersona, /primary option or action[\s\S]*“现在上传 CSV\/ZIP”/);
  assert.match(rootPersona, /never “我已上传”/);
  assert.match(rootPersona, /product file picker performs the upload/);
  assert.match(rootPersona, /submit[\s\S]*data_upload answer only after model_harness_import_dataset has actually succeeded/);
  assert.match(rootPersona, /answer beginning with dataset- is the opaque id of that already-imported Dataset/);
  const dataPersona = parseDelegateBlocks(PRESET_SOURCE).find((delegate) => delegate.toolName === "data_experiment").persona;
  assert.match(dataPersona, /value beginning with dataset- is an opaque already-imported Dataset id/);
  assert.match(dataPersona, /never call model_harness_import_dataset with that value/);
  assert.match(rootPersona, /stable id such as target_column/);
  assert.match(rootPersona, /question whose id is[\s\S]*inference_input_id/);
  assert.match(rootPersona, /primary action says “选择新样本”/);
  assert.match(rootPersona, /Never ask for[\s\S]*sample path/);
  assert.match(rootPersona, /single native sample-inference[\s\S]*approval/);
  assert.match(rootPersona, /model_harness_authorize_task_run_start/);
  assert.match(rootPersona, /run_authorization_id/);
  assert.match(rootPersona, /never use false for a privileged specialist delegation/);
  assert.match(rootPersona, /all six current[\s\S]*contract_revision identity fields/);
  assert.match(rootPersona, /native[\s\S]*callId is the user ApprovalDecision checkpoint_id/);
  assert.match(rootPersona, /delegate one real bounded inspection to data_experiment/);
  assert.match(rootPersona, /delegate evaluation_delivery with the[\s\S]*exact run_id/);
  assert.match(rootPersona, /model_harness_authorize_artifact_bundle_build/);
  assert.match(rootPersona, /artifact_bundle_authorization_id/);
  assert.match(rootPersona, /bundle_request_sha256/);
  assert.match(rootPersona, /spend the grant[\s\S]*exactly once on model_harness_build_artifact_bundle/);
  assert.match(rootPersona, /never as decorative narration/);
  const buildDelegate = parseDelegateBlocks(PRESET_SOURCE).find(
    (delegate) => delegate.toolName === "build_training",
  );
  assert.match(buildDelegate.persona, /fresh run_authorization_id/);
  assert.match(buildDelegate.persona, /model_harness_start_task_run once/);
  assert.match(buildDelegate.persona, /leave model_harness_confirm_contract/);
  const evaluationDelegate = parseDelegateBlocks(PRESET_SOURCE).find(
    (delegate) => delegate.toolName === "evaluation_delivery",
  );
  assert.match(evaluationDelegate.persona, /fresh artifact_bundle_authorization_id/);
  assert.match(evaluationDelegate.persona, /bundle_request_sha256/);
  assert.match(evaluationDelegate.persona, /model_harness_build_artifact_bundle once/);
  assert.match(PRESET_SOURCE, /name: '@deepseek-ai\/dsh-tool-subagent-control'/);
  assert.match(PRESET_SOURCE, /name: '@deepseek-ai\/dsh-tool-subagent-control\/list-agents'/);
});


test("task-spec update exposes every canonical specialist family", () => {
  const mounted = mountPlugin();
  const updateTool = mounted.tools.find(
    (tool) => tool.name === "model_harness_update_task_spec",
  );
  assert.ok(updateTool);
  assert.deepEqual(
    updateTool.parameters.properties.selected_family.enum,
    [...TASK_FAMILIES],
  );
  assert.deepEqual(
    [...TASK_FAMILIES],
    [
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
    ],
  );
});


test("mutating training tools use the native DSH approval seam", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  assert.equal(typeof listener, "function");
  const readDecision = await listener(
    { name: "model_harness_get_task" },
    async () => ({ kind: "allow" }),
  );
  assert.deepEqual(readDecision, { kind: "allow" });

  for (const conversationalTool of [
    "model_harness_clarify_task_spec",
    "model_harness_update_task_spec",
  ]) {
    const conversationDecision = await listener(
      { name: conversationalTool },
      async () => ({ kind: "allow" }),
    );
    assert.deepEqual(
      conversationDecision,
      { kind: "allow" },
      `${conversationalTool} follows the user's explicit chat answer without a duplicate native approval`,
    );
  }

  const mutationDecision = await listener(
    {
      name: "model_harness_authorize_task_run_start",
      agent: rootAgent(),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(mutationDecision.kind, "ask");
  assert.match(mutationDecision.reason, /仅允许当前根会话委派/);
  assert.match(mutationDecision.reason, /启动一次本地训练/);

  const sampleInferenceAuthorizationDecision = await listener(
    {
      name: "model_harness_authorize_sample_inference",
      agent: rootAgent(),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(sampleInferenceAuthorizationDecision.kind, "ask");
  assert.match(sampleInferenceAuthorizationDecision.reason, /评测与交付专家/);
  assert.match(sampleInferenceAuthorizationDecision.reason, /一次真实推理/);
  assert.match(sampleInferenceAuthorizationDecision.reason, /不授权读取本地路径/);

  const bundleAuthorizationDecision = await listener(
    {
      name: "model_harness_authorize_artifact_bundle_build",
      agent: rootAgent(),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(bundleAuthorizationDecision.kind, "ask");
  assert.match(bundleAuthorizationDecision.reason, /评测与交付专家/);
  assert.match(bundleAuthorizationDecision.reason, /一次隐私过滤交付包/);
  assert.match(bundleAuthorizationDecision.reason, /不授权下载/);

  const startWithoutGrant = await listener(
    {
      name: "model_harness_start_task_run",
      callId: "start-without-grant",
      arguments: { task_id: "task-1" },
      agent: specialistAgent("build_training"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(startWithoutGrant.kind, "deny");
  assert.match(startWithoutGrant.reason, /一次性授权/);

  const inferenceWithoutGrant = await listener(
    {
      name: "model_harness_run_sample_inference",
      callId: "inference-without-grant",
      arguments: {
        task_id: "task-1",
        run_id: "run-1",
        inference_input_id: "inference-input-1",
      },
      agent: specialistAgent("evaluation_delivery"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(inferenceWithoutGrant.kind, "deny");
  assert.match(inferenceWithoutGrant.reason, /一次性授权/);

  const bundleWithoutGrant = await listener(
    {
      name: "model_harness_build_artifact_bundle",
      callId: "bundle-without-grant",
      arguments: { task_id: "task-1", run_id: "run-1" },
      agent: specialistAgent("evaluation_delivery"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(bundleWithoutGrant.kind, "deny");
  assert.match(bundleWithoutGrant.reason, /一次性授权/);

  assert.equal(
    ROLE_TOOL_ALLOWLISTS.evaluation_delivery.includes(
      "model_harness_download_artifact_bundle",
    ),
    false,
  );
  const childDownload = await listener(
    {
      name: "model_harness_download_artifact_bundle",
      callId: "child-download",
      arguments: { task_id: "task-1", run_id: "run-1", bundle_id: "bundle-1" },
      agent: specialistAgent("evaluation_delivery"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(childDownload.kind, "deny");
  assert.match(childDownload.reason, /不在该 profile allowlist/);

  const recipeApproval = await listener(
    { name: "model_harness_register_recipe" },
    async () => ({ kind: "allow" }),
  );
  assert.equal(recipeApproval.kind, "ask");

  for (const toolName of [
    "model_harness_hf_attach",
    "model_harness_select_model_source_candidate",
    "model_harness_bind_model_source",
    "model_harness_decide_training_plan",
    "model_harness_download_artifact_bundle",
  ]) {
    const decision = await listener(
      { name: toolName },
      async () => ({ kind: "allow" }),
    );
    assert.equal(decision.kind, "ask", `${toolName} must use native approval`);
  }

  const priorDenial = { kind: "deny", reason: "policy" };
  assert.deepEqual(
    await listener(
      { name: "model_harness_import_dataset" },
      async () => priorDenial,
    ),
    priorDenial,
  );
});


test("root Training Orchestrator must delegate domain work to the owning specialist", async () => {
  const listener = mountPlugin().listeners.get("tools/pre-execute");
  const cases = [
    ["model_harness_search_model_sources", "research_source"],
    ["model_harness_match_capability", "data_experiment"],
    ["model_harness_check_resource_feasibility", "resource_safety"],
    ["model_harness_build_recipe", "build_training"],
    ["model_harness_run_sample_inference", "evaluation_delivery"],
    ["model_harness_build_artifact_bundle", "evaluation_delivery"],
  ];
  for (const [toolName, owner] of cases) {
    const decision = await listener(
      { name: toolName, agent: rootAgent() },
      async () => ({ kind: "allow" }),
    );
    assert.equal(decision.kind, "deny", `${toolName} must not run in the root session`);
    assert.match(decision.reason, /训练协调器不能直接执行/);
    assert.match(decision.reason, new RegExp(owner));
    assert.match(decision.reason, /请先委派/);
  }
});


test("root orchestrator keeps clarification, canonical reads and human checkpoint control", async () => {
  const listener = mountPlugin().listeners.get("tools/pre-execute");
  for (const toolName of [
    "model_harness_clarify_task_spec",
    "model_harness_update_task_spec",
    "model_harness_get_task",
    "model_harness_list_recipes",
    "model_harness_get_resource_feasibility",
    "model_harness_get_evaluation_report",
  ]) {
    assert.deepEqual(
      await listener(
        { name: toolName, agent: rootAgent() },
        async () => ({ kind: "allow" }),
      ),
      { kind: "allow" },
      `${toolName} is a root clarification/read tool`,
    );
  }

  for (const checkpointTool of [
    "model_harness_select_model_source_candidate",
    "model_harness_bind_model_source",
    "model_harness_decide_training_plan",
    "model_harness_hf_attach",
    "model_harness_register_recipe",
    "model_harness_confirm_contract",
    "model_harness_apply_task_strategy",
    "model_harness_cancel_run",
  ]) {
    const checkpointDecision = await listener(
      { name: checkpointTool, agent: rootAgent() },
      async () => ({ kind: "allow" }),
    );
    assert.equal(checkpointDecision.kind, "ask", `${checkpointTool} stays on the root approval seam`);
    assert.match(checkpointDecision.reason, /changes local task/);
  }

  const downloadDecision = await listener(
    { name: "model_harness_download_artifact_bundle", agent: rootAgent() },
    async () => ({ kind: "allow" }),
  );
  assert.equal(downloadDecision.kind, "ask");
  assert.match(downloadDecision.reason, /Agent Bridge/);
  assert.match(downloadDecision.reason, /一次下载授权/);

  for (const controlTool of [
    "research_source",
    "data_experiment",
    "subagent-control",
    "request_user_input",
  ]) {
    assert.deepEqual(
      await listener(
        { name: controlTool, agent: rootAgent() },
        async () => ({ kind: "allow" }),
      ),
      { kind: "allow" },
      `${controlTool} is outside the model-harness domain gate`,
    );
  }
});


test("privileged specialist delegation must preserve a continuable persisted role profile", async () => {
  const listener = mountPlugin().listeners.get("tools/pre-execute");
  for (const toolName of Object.keys(ROLE_TOOL_ALLOWLISTS)) {
    const foreground = await listener(
      {
        name: toolName,
        arguments: { run_in_background: false },
        agent: rootAgent(),
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(foreground.kind, "deny", `${toolName} must not become a one-shot child`);
    assert.match(foreground.reason, /可继续的 DSH 子会话/);
    assert.match(foreground.reason, /不能用一次性前台子会话/);

    assert.deepEqual(
      await listener(
        { name: toolName, arguments: {}, agent: rootAgent() },
        async () => ({ kind: "allow" }),
      ),
      { kind: "allow" },
      `${toolName} may use its configured continuable default`,
    );
  }
});


test("bound specialist sessions continue only inside their exact role profile", async () => {
  const listener = mountPlugin().listeners.get("tools/pre-execute");
  const allowedCases = [
    ["research_source", "model_harness_search_model_sources"],
    ["data_experiment", "model_harness_match_capability"],
    ["resource_safety", "model_harness_check_resource_feasibility"],
    ["build_training", "model_harness_get_recipe_build"],
    ["evaluation_delivery", "model_harness_get_evaluation_report"],
  ];
  for (const [role, toolName] of allowedCases) {
    assert.deepEqual(
      await listener(
        { name: toolName, agent: specialistAgent(role) },
        async () => ({ kind: "allow" }),
      ),
      { kind: "allow" },
      `${role} must retain ${toolName}`,
    );
  }

  const approvedMutation = await listener(
    {
      name: "model_harness_start_task_run",
      callId: "start-without-root-grant",
      arguments: { task_id: "task-1" },
      agent: specialistAgent("build_training"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(approvedMutation.kind, "deny");
  assert.match(approvedMutation.reason, /一次性授权/);

  const wrongRole = await listener(
    {
      name: "model_harness_search_model_sources",
      agent: specialistAgent("data_experiment"),
    },
    async () => ({ kind: "allow" }),
  );
  assert.equal(wrongRole.kind, "deny");
  assert.match(wrongRole.reason, /data_experiment/);
  assert.match(wrongRole.reason, /research_source/);
  assert.match(wrongRole.reason, /重新委派/);

  const reused = specialistAgent("build_training");
  reused.session.events.push(
    { type: "message", data: { role: "assistant", content: "first bounded turn completed" } },
    { type: "message", data: { role: "user", content: "continue the same bounded role" } },
  );
  assert.deepEqual(
    await listener(
      { name: "model_harness_get_events", agent: reused },
      async () => ({ kind: "allow" }),
    ),
    { kind: "allow" },
    "a reused continuable child keeps its exact persisted descriptor",
  );
});


test("root approval issues one exact grant that only the bound build specialist can spend once", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_task_run_start",
  );
  const start = mounted.tools.find(
    (tool) => tool.name === "model_harness_start_task_run",
  );
  const authorizationArgs = {
    task_id: "task-ready-1",
    contract_sha256: DIGEST_A,
    dataset_id: "dataset-1",
    dataset_fingerprint_sha256: DIGEST_B,
    spec_revision: 3,
  };
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || "GET";
    requests.push({ url: String(url), method, body: options.body });
    if (method === "GET" && String(url).endsWith("/tasks/task-ready-1")) {
      return jsonResponse(readyTask());
    }
    if (method === "POST" && String(url).endsWith("/tasks/task-ready-1/run-authorizations")) {
      assert.equal(options.headers["X-Model-Harness-Agent-Token"], "bridge-test-token");
      assert.deepEqual(JSON.parse(options.body), {
        contract_sha256: DIGEST_A,
        dataset_id: "dataset-1",
        dataset_fingerprint_sha256: DIGEST_B,
        spec_revision: 3,
        approval: { actor: "user", checkpoint_id: "authorize-call" },
      });
      return jsonResponse(runStartAuthorization("authorize-call"), 201);
    }
    if (method === "POST" && String(url).endsWith("/tasks/task-ready-1/runs")) {
      assert.deepEqual(JSON.parse(options.body), {
        run_authorization_id: "delivery-authorization-run-1",
        authorization_token: "backend-run-token",
        run_request_sha256: DIGEST_C,
      });
      return jsonResponse({
        task: readyTask({ current_run_id: "run-1", status: "running" }),
        run: { run_id: "run-1", status: "queued" },
      });
    }
    throw new Error(`unexpected request ${method} ${url}`);
  };

  try {
    const approval = await listener(
      {
        name: authorize.name,
        callId: "authorize-call",
        arguments: authorizationArgs,
        agent: rootAgent(),
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(approval.kind, "ask");

    const grant = await authorize.execute(authorizationArgs, {
      callId: "authorize-call",
      agent: rootAgent(),
      signal: undefined,
    });
    assert.equal(grant.single_use, true);
    assert.equal(grant.specialist_role, "build_training");
    assert.equal(grant.task_id, authorizationArgs.task_id);
    assert.equal(grant.run_authorization_id, "delivery-authorization-run-1");
    assert.equal(grant.run_request_sha256, DIGEST_C);

    const startArgs = {
      task_id: authorizationArgs.task_id,
      run_authorization_id: grant.run_authorization_id,
    };
    const wrongParent = specialistAgent("build_training", { parentSession: "other-root" });
    const wrongParentDecision = await listener(
      {
        name: start.name,
        callId: "wrong-parent-start",
        arguments: startArgs,
        agent: wrongParent,
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(wrongParentDecision.kind, "deny");
    assert.match(wrongParentDecision.reason, /原根会话委派/);

    const buildAgent = specialistAgent("build_training");
    const startExec = {
      name: start.name,
      callId: "authorized-start",
      arguments: startArgs,
      agent: buildAgent,
      signal: undefined,
    };
    assert.deepEqual(
      await listener(startExec, async () => ({ kind: "allow" })),
      { kind: "allow" },
    );
    const started = await start.execute(startArgs, startExec);
    assert.equal(started.run.run_id, "run-1");
    assert.match(started.workbench_url, /task=task-ready-1/);

    const replay = await listener(
      { ...startExec, callId: "replayed-start" },
      async () => ({ kind: "allow" }),
    );
    assert.equal(replay.kind, "deny");
    assert.match(replay.reason, /已使用或已过期/);
    assert.equal(requests.filter((request) => request.method === "POST").length, 2);
    assert.equal(requests.filter((request) => request.method === "GET").length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("a stale canonical binding invalidates the grant before the run side effect", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_task_run_start",
  );
  const start = mounted.tools.find(
    (tool) => tool.name === "model_harness_start_task_run",
  );
  const authorizationArgs = {
    task_id: "task-ready-1",
    contract_sha256: DIGEST_A,
    dataset_id: "dataset-1",
    dataset_fingerprint_sha256: DIGEST_B,
    spec_revision: 3,
  };
  let canonicalTask = readyTask();
  let postCount = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || "GET";
    if (method === "GET" && String(url).endsWith("/tasks/task-ready-1")) {
      return jsonResponse(canonicalTask);
    }
    if (method === "POST" && String(url).endsWith("/tasks/task-ready-1/run-authorizations")) {
      return jsonResponse(runStartAuthorization("authorize-stale"), 201);
    }
    if (method === "POST" && String(url).endsWith("/tasks/task-ready-1/runs")) {
      postCount += 1;
      return jsonResponse({ run: { run_id: "must-not-start" } });
    }
    throw new Error(`unexpected request ${method} ${url}`);
  };

  try {
    const grant = await authorize.execute(authorizationArgs, {
      callId: "authorize-stale",
      agent: rootAgent(),
      signal: undefined,
    });
    const args = {
      task_id: authorizationArgs.task_id,
      run_authorization_id: grant.run_authorization_id,
    };
    const exec = {
      name: start.name,
      callId: "start-stale",
      arguments: args,
      agent: specialistAgent("build_training"),
      signal: undefined,
    };
    assert.deepEqual(
      await listener(exec, async () => ({ kind: "allow" })),
      { kind: "allow" },
    );
    canonicalTask = readyTask({ confirmed_contract_sha256: DIGEST_C });
    await assert.rejects(
      start.execute(args, exec),
      /confirmed contract no longer matches/,
    );
    canonicalTask = readyTask();
    const replay = await listener(
      { ...exec, callId: "start-stale-replay" },
      async () => ({ kind: "allow" }),
    );
    assert.equal(replay.kind, "deny");
    assert.equal(postCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("root approval lets only the bound delivery specialist spend one opaque inference-input grant", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_sample_inference",
  );
  const runInference = mounted.tools.find(
    (tool) => tool.name === "model_harness_run_sample_inference",
  );
  assert.equal("sample_path" in runInference.parameters.properties, false);
  assert.equal("inference_input_id" in runInference.parameters.properties, true);
  const authorizationArgs = {
    task_id: "task-delivery-1",
    run_id: "run-delivery-1",
    inference_input_id: "inference-input-delivery-1",
    inference_input_sha256: DIGEST_C,
  };
  const originalFetch = globalThis.fetch;
  let executed = 0;
  globalThis.fetch = async (url, options = {}) => {
    const selectedUrl = String(url);
    const method = options.method || "GET";
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1")) {
      return jsonResponse(deliveryTask());
    }
    if (method === "GET" && selectedUrl.endsWith("/runs/run-delivery-1/result")) {
      return jsonResponse(deliveryRun());
    }
    if (
      method === "GET"
      && selectedUrl.endsWith(
        "/tasks/task-delivery-1/runs/run-delivery-1/inference-inputs/inference-input-delivery-1",
      )
    ) {
      return jsonResponse(deliveryInferenceInput());
    }
    if (
      method === "POST"
      && selectedUrl.endsWith(
        "/tasks/task-delivery-1/runs/run-delivery-1/sample-inference-authorizations",
      )
    ) {
      assert.equal(options.headers["X-Model-Harness-Agent-Token"], "bridge-test-token");
      assert.deepEqual(JSON.parse(options.body), {
        inference_input_id: "inference-input-delivery-1",
        inference_input_sha256: DIGEST_C,
        approval: { actor: "user", checkpoint_id: "authorize-inference" },
      });
      return jsonResponse(sampleInferenceAuthorization("authorize-inference"), 201);
    }
    if (
      method === "POST"
      && selectedUrl.endsWith(
        "/tasks/task-delivery-1/runs/run-delivery-1/inference-inputs/inference-input-delivery-1/execute",
      )
    ) {
      executed += 1;
      assert.deepEqual(JSON.parse(options.body), {
        sample_inference_authorization_id: "delivery-authorization-inference-1",
        authorization_token: "backend-inference-token",
        sample_inference_request_sha256: DIGEST_A,
      });
      return jsonResponse({
        task: deliveryTask(),
        run_id: "run-delivery-1",
        inference_input: deliveryInferenceInput({ status: "consumed" }).inference_input,
        sample_inference: {
          task_id: "task-delivery-1",
          run_id: "run-delivery-1",
          check_id: "sample-delivery-1",
          status: "passed",
        },
      }, 201);
    }
    throw new Error(`unexpected request ${method} ${url}`);
  };

  try {
    const grant = await authorize.execute(authorizationArgs, {
      callId: "authorize-inference",
      agent: rootAgent(),
      signal: undefined,
    });
    assert.equal(grant.single_use, true);
    assert.equal(grant.specialist_role, "evaluation_delivery");
    assert.equal(grant.sample_inference_request_sha256, DIGEST_A);
    assert.equal(grant.object_refs[0].type, "inference_input");

    const inferenceArgs = {
      task_id: authorizationArgs.task_id,
      run_id: authorizationArgs.run_id,
      inference_input_id: authorizationArgs.inference_input_id,
      sample_inference_authorization_id: grant.sample_inference_authorization_id,
      sample_inference_request_sha256: grant.sample_inference_request_sha256,
    };
    const exec = {
      name: runInference.name,
      callId: "run-inference-once",
      arguments: inferenceArgs,
      agent: specialistAgent("evaluation_delivery"),
      signal: undefined,
    };
    assert.deepEqual(
      await listener(exec, async () => ({ kind: "allow" })),
      { kind: "allow" },
    );
    const result = await runInference.execute(inferenceArgs, exec);
    assert.equal(result.sample_inference.status, "passed");
    assert.equal(result.object_refs[0].type, "inference_input");
    assert.equal(JSON.stringify(result).includes("/Users/"), false);
    assert.equal(executed, 1);

    const replay = await listener(
      { ...exec, callId: "run-inference-replay" },
      async () => ({ kind: "allow" }),
    );
    assert.equal(replay.kind, "deny");
    assert.match(replay.reason, /已使用或已过期/);
    assert.equal(executed, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("root approval issues one exact Artifact Bundle grant that only the bound delivery specialist can spend once", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_artifact_bundle_build",
  );
  const build = mounted.tools.find(
    (tool) => tool.name === "model_harness_build_artifact_bundle",
  );
  const authorizationArgs = {
    task_id: "task-delivery-1",
    run_id: "run-delivery-1",
    evaluation_report_id: "evaluation-delivery-1",
    evaluation_report_sha256: DIGEST_A,
    sample_inference_check_id: "sample-1",
  };
  const sampleInference = {
    task_id: authorizationArgs.task_id,
    run_id: authorizationArgs.run_id,
    check_id: authorizationArgs.sample_inference_check_id,
    status: "passed",
    blocked: false,
    sample: { sha256: DIGEST_B },
    model: { sha256: DIGEST_C },
    prediction_sha256: DIGEST_B,
    inference_check_id: "inference-1",
  };
  const artifactBundle = {
    bundle_id: "bundle-delivery-1",
    task_id: authorizationArgs.task_id,
    run_id: authorizationArgs.run_id,
    manifest_sha256: DIGEST_C,
  };
  const sampleEvidenceSha256 = canonicalSha256({
    check_id: "sample-1",
    inference_check_id: "inference-1",
    model_sha256: DIGEST_C,
    prediction_sha256: DIGEST_B,
    run_id: authorizationArgs.run_id,
    sample_sha256: DIGEST_B,
    task_id: authorizationArgs.task_id,
  });
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    const selectedUrl = String(url);
    const method = options.method || "GET";
    requests.push({ url: selectedUrl, method, body: options.body });
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1")) {
      return jsonResponse({ task: deliveryTask() });
    }
    if (method === "GET" && selectedUrl.endsWith("/runs/run-delivery-1/result")) {
      return jsonResponse(deliveryRun());
    }
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1/runs/run-delivery-1/evaluation-report")) {
      return jsonResponse(deliveryEvaluation());
    }
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1/runs/run-delivery-1/sample-inferences/sample-1")) {
      return jsonResponse({
        task: deliveryTask(),
        run_id: authorizationArgs.run_id,
        sample_inference: sampleInference,
      });
    }
    if (method === "POST" && selectedUrl.endsWith("/tasks/task-delivery-1/runs/run-delivery-1/artifact-bundle-authorizations")) {
      assert.equal(options.headers["X-Model-Harness-Agent-Token"], "bridge-test-token");
      assert.deepEqual(JSON.parse(options.body), {
        evaluation_report_id: "evaluation-delivery-1",
        evaluation_report_sha256: DIGEST_A,
        approval: { actor: "user", checkpoint_id: "authorize-bundle-call" },
        sample_inference_check_id: "sample-1",
      });
      return jsonResponse(deliveryBuildAuthorization({
        checkpointId: "authorize-bundle-call",
        sampleEvidenceSha256,
      }), 201);
    }
    if (method === "POST" && selectedUrl.endsWith("/tasks/task-delivery-1/runs/run-delivery-1/artifact-bundles")) {
      assert.deepEqual(JSON.parse(options.body), {
        artifact_bundle_authorization_id: "delivery-authorization-build-1",
        authorization_token: "backend-build-token",
        bundle_request_sha256: DIGEST_C,
        sample_inference_check_id: "sample-1",
      });
      return jsonResponse({
        task: deliveryTask(),
        run_id: authorizationArgs.run_id,
        artifact_bundle: artifactBundle,
      }, 201);
    }
    throw new Error(`unexpected request ${method} ${url}`);
  };

  try {
    const approval = await listener(
      {
        name: authorize.name,
        callId: "authorize-bundle-call",
        arguments: authorizationArgs,
        agent: rootAgent(),
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(approval.kind, "ask");

    const grant = await authorize.execute(authorizationArgs, {
      callId: "authorize-bundle-call",
      agent: rootAgent(),
      signal: undefined,
    });
    assert.equal(grant.single_use, true);
    assert.equal(grant.specialist_role, "evaluation_delivery");
    assert.equal(grant.approval_checkpoint_id, "authorize-bundle-call");
    assert.equal(grant.task_id, authorizationArgs.task_id);
    assert.equal(grant.run_id, authorizationArgs.run_id);
    assert.equal(grant.evaluation_report_sha256, DIGEST_A);
    assert.equal(grant.artifact_bundle_authorization_id, "delivery-authorization-build-1");
    assert.match(grant.bundle_request_sha256, /^[0-9a-f]{64}$/);

    const buildArgs = {
      task_id: authorizationArgs.task_id,
      run_id: authorizationArgs.run_id,
      artifact_bundle_authorization_id: grant.artifact_bundle_authorization_id,
      bundle_request_sha256: grant.bundle_request_sha256,
      sample_inference_check_id: authorizationArgs.sample_inference_check_id,
    };
    const wrongParentDecision = await listener(
      {
        name: build.name,
        callId: "wrong-parent-bundle",
        arguments: buildArgs,
        agent: specialistAgent("evaluation_delivery", { parentSession: "other-root" }),
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(wrongParentDecision.kind, "deny");
    assert.match(wrongParentDecision.reason, /原根会话委派/);

    const changedScopeDecision = await listener(
      {
        name: build.name,
        callId: "changed-scope-bundle",
        arguments: { ...buildArgs, sample_inference_check_id: "sample-other" },
        agent: specialistAgent("evaluation_delivery"),
      },
      async () => ({ kind: "allow" }),
    );
    assert.equal(changedScopeDecision.kind, "deny");
    assert.match(changedScopeDecision.reason, /bundle request scope/);

    const buildExec = {
      name: build.name,
      callId: "build-bundle-call",
      arguments: buildArgs,
      agent: specialistAgent("evaluation_delivery"),
      signal: undefined,
    };
    assert.deepEqual(
      await listener(buildExec, async () => ({ kind: "allow" })),
      { kind: "allow" },
    );
    const built = await build.execute(buildArgs, buildExec);
    assert.equal(built.artifact_bundle.bundle_id, artifactBundle.bundle_id);
    assert.deepEqual(built.object_refs[0], {
      type: "artifact_bundle",
      id: artifactBundle.bundle_id,
      task_id: authorizationArgs.task_id,
      label: `交付产物 · ${artifactBundle.bundle_id}`,
      digest: DIGEST_C,
      run_id: authorizationArgs.run_id,
    });
    assert.deepEqual(built.artifact_bundle_authorization, {
      artifact_bundle_authorization_id: grant.artifact_bundle_authorization_id,
      approval_checkpoint_id: "authorize-bundle-call",
      bundle_request_sha256: grant.bundle_request_sha256,
      task_id: authorizationArgs.task_id,
      run_id: authorizationArgs.run_id,
      bundle_id: artifactBundle.bundle_id,
      manifest_sha256: DIGEST_C,
      approval_decision_id: "delivery-approval-build-1",
      authorization_sha256: DIGEST_B,
      specialist_role: "evaluation_delivery",
      consumed_call_id: "build-bundle-call",
      status: "consumed",
      single_use: true,
    });

    const replay = await listener(
      { ...buildExec, callId: "replayed-bundle-call" },
      async () => ({ kind: "allow" }),
    );
    assert.equal(replay.kind, "deny");
    assert.match(replay.reason, /已使用或已过期/);
    assert.equal(requests.filter((request) => request.method === "POST").length, 2);
    assert.equal(requests.filter((request) => request.method === "GET").length, 8);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("Artifact Bundle authorization fails closed on EvaluationReport drift before the build side effect", async () => {
  const mounted = mountPlugin();
  const listener = mounted.listeners.get("tools/pre-execute");
  const authorize = mounted.tools.find(
    (tool) => tool.name === "model_harness_authorize_artifact_bundle_build",
  );
  const build = mounted.tools.find(
    (tool) => tool.name === "model_harness_build_artifact_bundle",
  );
  const authorizationArgs = {
    task_id: "task-delivery-1",
    run_id: "run-delivery-1",
    evaluation_report_id: "evaluation-delivery-1",
    evaluation_report_sha256: DIGEST_A,
  };
  let canonicalEvaluation = deliveryEvaluation();
  let postCount = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    const selectedUrl = String(url);
    const method = options.method || "GET";
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1")) {
      return jsonResponse({ task: deliveryTask() });
    }
    if (method === "GET" && selectedUrl.endsWith("/runs/run-delivery-1/result")) {
      return jsonResponse(deliveryRun());
    }
    if (method === "GET" && selectedUrl.endsWith("/tasks/task-delivery-1/runs/run-delivery-1/evaluation-report")) {
      return jsonResponse(canonicalEvaluation);
    }
    if (method === "POST" && selectedUrl.endsWith("/artifact-bundle-authorizations")) {
      return jsonResponse(deliveryBuildAuthorization({
        checkpointId: "authorize-stale-bundle",
      }), 201);
    }
    if (method === "POST" && selectedUrl.endsWith("/artifact-bundles")) {
      postCount += 1;
      return jsonResponse({ artifact_bundle: { bundle_id: "must-not-build" } }, 201);
    }
    throw new Error(`unexpected request ${method} ${url}`);
  };

  try {
    const grant = await authorize.execute(authorizationArgs, {
      callId: "authorize-stale-bundle",
      agent: rootAgent(),
      signal: undefined,
    });
    const buildArgs = {
      task_id: authorizationArgs.task_id,
      run_id: authorizationArgs.run_id,
      artifact_bundle_authorization_id: grant.artifact_bundle_authorization_id,
      bundle_request_sha256: grant.bundle_request_sha256,
    };
    const buildExec = {
      name: build.name,
      callId: "build-stale-bundle",
      arguments: buildArgs,
      agent: specialistAgent("evaluation_delivery"),
      signal: undefined,
    };
    assert.deepEqual(
      await listener(buildExec, async () => ({ kind: "allow" })),
      { kind: "allow" },
    );
    canonicalEvaluation = deliveryEvaluation({ report_sha256: DIGEST_C });
    await assert.rejects(
      build.execute(buildArgs, buildExec),
      /evaluation report digest no longer matches canonical evidence/,
    );
    const replay = await listener(
      { ...buildExec, callId: "replayed-stale-bundle" },
      async () => ({ kind: "allow" }),
    );
    assert.equal(replay.kind, "deny");
    assert.equal(postCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("subagent role identity fails closed and ignores inherited descriptors", async () => {
  const listener = mountPlugin().listeners.get("tools/pre-execute");
  const oneShot = specialistAgent("build_training", { mode: "one-shot" });
  const oneShotDecision = await listener(
    { name: "model_harness_get_task", agent: oneShot },
    async () => ({ kind: "allow" }),
  );
  assert.equal(oneShotDecision.kind, "deny");
  assert.match(oneShotDecision.reason, /持久化 role profile/);

  const unknown = specialistAgent("data_experiment", {
    allow: [...ROLE_TOOL_ALLOWLISTS.data_experiment, "model_harness_search_model_sources"],
  });
  const unknownDecision = await listener(
    { name: "model_harness_match_capability", agent: unknown },
    async () => ({ kind: "allow" }),
  );
  assert.equal(unknownDecision.kind, "deny");
  assert.match(unknownDecision.reason, /无法从 DSH 子会话/);

  const seeded = specialistAgent("data_experiment", { seedLength: 1 });
  seeded.session.events[0] = {
    type: "subagent/descriptor",
    data: {
      version: 2,
      mode: "continuable",
      provider: "spawn",
      label: "inherited research profile",
      toolFilter: { allow: ROLE_TOOL_ALLOWLISTS.research_source },
    },
  };
  assert.deepEqual(
    await listener(
      { name: "model_harness_match_capability", agent: seeded },
      async () => ({ kind: "allow" }),
    ),
    { kind: "allow" },
  );
  const inheritedEscalation = await listener(
    { name: "model_harness_search_model_sources", agent: seeded },
    async () => ({ kind: "allow" }),
  );
  assert.equal(inheritedEscalation.kind, "deny");
  assert.match(inheritedEscalation.reason, /data_experiment/);

  const priorDenial = { kind: "deny", reason: "higher-priority policy" };
  assert.equal(
    await listener(
      { name: "model_harness_build_recipe", agent: rootAgent() },
      async () => priorDenial,
    ),
    priorDenial,
  );
});
