import { createHash, randomUUID } from "node:crypto";
import { link, mkdir, readFile, stat, unlink, writeFile } from "node:fs/promises";
import { basename, extname, isAbsolute, resolve } from "node:path";

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
  "/agent", "/app", "/capabilities", "/chat", "/conversations", "/data-adapters", "/health",
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

export function compactTaskForAgent(value) {
  if (!value?.task || typeof value.task !== "object") return value;
  const task = structuredClone(value.task);
  // Task identity/approval facts must survive the host tool formatter's byte
  // limit. Full code belongs to the explicit execution-proposal read route,
  // not repeated inside both contract and contract_revision snapshots.
  for (const contract of [task.contract, task.contract_revision?.contract_snapshot]) {
    const spec = contract?.execution_spec;
    if (!spec?.bundle?.files || typeof spec.bundle.files !== "object") continue;
    spec.bundle.source_file_names = Object.keys(spec.bundle.files);
    delete spec.bundle.files;
    spec.source_view = "metadata_only; read the task-owned execution proposal for exact source bytes";
  }
  const revision = task.contract_revision;
  // The immutable snapshot duplicates the current contract on every report,
  // prediction and delivery read. Keep its exact identity; the canonical task
  // and explicit proposal routes retain the full evidence.
  if (task.contract?.execution_spec && revision?.contract_snapshot) {
    delete revision.contract_snapshot;
    revision.snapshot_view = "identity_only; current contract is below; exact snapshot remains in the task evidence store";
  }
  if (task.contract?.execution_spec) {
    const summarizeDataset = dataset => {
      if (!dataset || typeof dataset !== "object") return;
      if (dataset.splits && typeof dataset.splits === "object" && !Array.isArray(dataset.splits)) {
        dataset.split_file_counts = Object.fromEntries(Object.entries(dataset.splits).map(([split, rows]) => [split, Array.isArray(rows) ? rows.length : null]));
        dataset.splits_reference = { sha256: createHash("sha256").update(JSON.stringify(dataset.splits)).digest("hex"),
          evidence_view: "exact file membership remains in the frozen canonical Dataset; use task-owned execution evidence for stage mounts" };
        delete dataset.splits;
      }
      for (const key of ["files", "split_manifest"]) {
        const entries = dataset[key];
        if (!entries || typeof entries !== "object") continue;
        dataset[key + "_reference"] = { sha256: createHash("sha256").update(JSON.stringify(entries)).digest("hex"),
          entries: Array.isArray(entries) ? entries.length : Object.keys(entries).length,
          evidence_view: "read the task-owned dataset evidence for exact members" };
        delete dataset[key];
      }
    };
    summarizeDataset(task.contract.dataset);
    summarizeDataset(task.current_result?.dataset);
    // Qualification details belong to the exact proposal read, not every
    // task envelope. Preserve history identity, status and failure diagnosis.
    for (const proposal of task.execution_proposals || []) {
      const q = proposal.qualification;
      if (!q || typeof q !== "object") continue;
      proposal.qualification = Object.fromEntries(Object.entries(q).filter(([key]) =>
        ["qualification_id", "qualification_sha256", "status", "valid", "passed", "created_at", "proposal_id", "proposal_sha256", "errors", "reason"].includes(key)));
      proposal.qualification.evidence_view = "read the exact execution proposal for qualification checks";
    }
  }
  delete task.contract_revision;
  const early = Object.fromEntries(["task_id", "current_spec_revision", "current_contract_revision_id", "dataset_id", "confirmed_contract_sha256"].filter(key => Object.hasOwn(task, key)).map(key => [key, task[key]]));
  return { ...value, task: { ...early, ...(revision ? { contract_revision: revision } : {}), ...task } };
}

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

function executionVirtualPrefix(value) { return /^\/workspace\/(?:source|input|output)(?=\/|$)/.test(String(value).trim()); }
function executionVirtualPath(value) { return executionVirtualPrefix(value) && !String(value).includes("\\") && !String(value).split("/").some(part => part === "." || part === "..") && !/[\x00-\x1f]/.test(String(value)); }
function publicText(value, preserveVirtualPaths = false) {
  if (isLocalAbsolutePath(value) && !(preserveVirtualPaths && executionVirtualPath(value))) return PUBLIC_REDACTED;
  return value
    .replace(
      /(^|[^A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s"'<>]+/g,
      (_match, prefix) => `${prefix}${PUBLIC_REDACTED}`,
    )
    .replace(/(?:file:\/\/|~\/)[^\s"'<>`“”‘’「」『』]+/g, PUBLIC_REDACTED)
    .replace(
      /(^|[^A-Za-z0-9:/])(\/(?:Users|home|private|tmp|var|etc|Applications|Library|System|Volumes|opt|usr|srv|mnt|media)(?:\/[^\s"'<>`“”‘’「」『』]+)+)/g,
      (_match, prefix) => `${prefix}${PUBLIC_REDACTED}`,
    )
    .replace(
      /(^|[^\p{L}\p{N}_:/])(\/[^\s"'<>`「」“”‘’]+)/gu,
      (_match, prefix, path) => `${prefix}${isPublicRoute(path) || preserveVirtualPaths && executionVirtualPath(path) ? path : PUBLIC_REDACTED}`,
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

// These are protocol-owned virtual mounts, never host filesystem locations.
// Protect them only for execution protocol envelopes; ordinary projections keep
// their original path-redaction policy. Source text is otherwise unchanged.
export function executionPublicProjection(value) {
  const project = (item, dataNamespace = false, path = []) => {
    if (Array.isArray(item)) return item.map((child, index) => project(child, dataNamespace, [...path, index]));
    if (item && typeof item === "object") {
      const data = dataNamespace;
      return Object.fromEntries(Object.entries(item).flatMap(([key, child]) => {
        const normalized = key.trim().toLowerCase().replaceAll("-", "_");
        const sensitive = PUBLIC_SENSITIVE_KEYS.has(normalized) || normalized.endsWith("_root");
        const pathKey = normalized === "path" || normalized.endsWith("_path");
        const hostValue = typeof child === "string" && isLocalAbsolutePath(child) && !executionVirtualPath(child);
        const protocolDirectory = path.length === 2 && path[0] === "execution_workspace" && path[1] === "protocol" && key === "working_directory" && typeof child === "string" && executionVirtualPath(child);
        if (sensitive && !protocolDirectory && (!data || hostValue) || pathKey && hostValue) return [];
        return [[key, project(child, data || ["execution_spec", "execution_spec_schema"].includes(key), [...path, key])]];
      }));
    }
    return typeof item === "string" ? publicText(item, true) : item;
  };
  const result = project(value);
  const retainFrozenSource = (record, output) => {
    const spec = record?.execution_spec, bundle = spec?.bundle;
    if (!output || record?.object_type !== "ExecutionProposal" || typeof record.task_id !== "string" || !record.task_id
      || !/^execution-[a-f0-9]{24}$/.test(record.proposal_id || "") || !/^[a-f0-9]{64}$/.test(record.proposal_sha256 || "")
      || !Number.isInteger(record.base_spec_revision) || record.base_spec_revision < 1 || !/^[a-f0-9]{64}$/.test(spec?.bundle_sha256 || "")
      || !/^(?:[A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[a-f0-9]{64}$/.test(bundle?.image || "") || !bundle.files || Array.isArray(bundle.files)
      || !Object.values(bundle.files).every(source => typeof source === "string") || !bundle.stages || typeof bundle.stages !== "object" || !Object.values(bundle.stages).every(argv => Array.isArray(argv) && argv.length > 0 && argv.every(arg => typeof arg === "string"))) return;
    output.execution_spec.bundle.files = { ...bundle.files };
    output.execution_spec.bundle.stages = Object.fromEntries(Object.entries(bundle.stages).map(([stage, argv]) => [stage, [...argv]]));
  };
  // The backend has already verified the frozen bundle and proposal digests.
  // Only these response positions contain source definitions, never log data.
  retainFrozenSource(value?.proposal, result?.proposal);
  if (Array.isArray(value?.proposals) && Array.isArray(result?.proposals)) value.proposals.forEach((record, index) => retainFrozenSource(record, result.proposals[index]));
  return result;
}

export class ModelHarnessClient {
  constructor(
    baseUrl = process.env.MODEL_HARNESS_URL || DEFAULT_BASE_URL,
    agentBridgeToken = process.env.MODEL_HARNESS_AGENT_BRIDGE_TOKEN || "",
    artifactExportDir = process.env.MODEL_HARNESS_ARTIFACT_EXPORT_DIR
      || (process.env.MODEL_HARNESS_RUNS_DIR
        ? resolve(process.env.MODEL_HARNESS_RUNS_DIR, "_workspace", "exports")
        : ""),
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.agentBridgeToken = String(agentBridgeToken || "").trim();
    const selectedExportDir = String(artifactExportDir || "").trim();
    if (selectedExportDir && !isAbsolute(selectedExportDir)) {
      throw new Error("Artifact Bundle export directory must be absolute");
    }
    this.artifactExportDir = selectedExportDir ? resolve(selectedExportDir) : null;
  }

  agentBridgeApprovalHeaders() {
    if (!this.agentBridgeToken) {
      throw new Error("The verified agent-bridge approval channel is unavailable");
    }
    return { "X-Model-Harness-Agent-Token": this.agentBridgeToken };
  }

  async request(path, { method = "GET", body, rawBody, headers = {}, signal, executionProjection = false } = {}) {
    if (body !== undefined && rawBody !== undefined) {
      throw new Error("request cannot contain both JSON and raw bodies");
    }
    const requestHeaders = {
      ...headers,
      "X-Model-Harness-Projection": executionProjection ? "agent-execution-v1" : "agent-v1",
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
    return compactTaskForAgent(executionProjection ? executionPublicProjection(value) : publicProjection(value));
  }

  recipes(signal) {
    return this.request("/recipes", { signal });
  }

  dataAdapters(signal) {
    return this.request("/data-adapters", { signal });
  }

  localResources(signal) {
    return this.request("/resources/local", { signal });
  }

  async listMaterials(ownerId, signal) {
    const result = await this.request(`/conversations/${encodeURIComponent(ownerId)}/materials`, { signal });
    if (!Array.isArray(result?.materials) || result.materials.some(material => material?.owner_id !== ownerId)) {
      throw new Error("Material list owner identity mismatch");
    }
    return result;
  }

  async getMaterial(ownerId, materialId, signal) {
    const result = await this.request(`/conversations/${encodeURIComponent(ownerId)}/materials/${encodeURIComponent(materialId)}?view=agent`, { signal });
    const material = result?.material;
    if (material?.owner_id !== ownerId || material?.material_id !== materialId || material?.data_inspected_only !== true || material?.dataset_imported !== false || material?.execution_authorized !== false) {
      throw new Error("Material report identity or inspection scope mismatch");
    }
    return result;
  }

  rootContext(ownerId, signal) {
    return this.request(`/conversations/${encodeURIComponent(ownerId)}/agent-context`, { signal });
  }

  contextState(ownerId, signal) {
    return this.request(`/conversations/${encodeURIComponent(ownerId)}/context-state`, {signal});
  }

  recordContextState(ownerId, body, signal) {
    return this.request(`/conversations/${encodeURIComponent(ownerId)}/context-state`, {method:"POST",body,signal,headers:this.agentBridgeApprovalHeaders()});
  }
  contextSnapshots(ownerId, signal) {
    return this.request(`/conversations/${encodeURIComponent(ownerId)}/context-snapshots`,{signal});
  }
  contextSnapshot(ownerId,snapshotId,options,signal) {
    const query=new URLSearchParams(Object.entries(options).filter(([,value])=>value!==undefined).map(([key,value])=>[key,String(value)]));
    return this.request(`/conversations/${encodeURIComponent(ownerId)}/context-snapshots/${encodeURIComponent(snapshotId)}?${query}`,{signal});
  }

  async contextEvidence(ownerId, options, signal) {
    const query=new URLSearchParams(Object.entries(options).filter(([,value])=>value!==undefined).map(([key,value])=>[key,String(value)]));
    const value=await this.request(`/conversations/${encodeURIComponent(ownerId)}/context-evidence?${query}`,{signal});
    const evidence=value?.evidence;
    if (evidence?.owner_id!==ownerId) throw new Error('Context evidence owner mismatch');
    if (options.kind==='execution_source' && options.filename!==undefined) {
      if (evidence.proposal_id!==options.object_id || evidence.filename!==options.filename || evidence.encoding!=='base64-utf8' || typeof evidence.content_base64!=='string' || evidence.content_base64.length>100000) throw new Error('Frozen source fragment identity mismatch');
      const fragment=Buffer.from(evidence.content_base64,'base64');
      if (createHash('sha256').update(fragment).digest('hex')!==evidence.slice_sha256) throw new Error('Frozen source fragment digest mismatch');
      evidence.text=fragment.toString('utf8');delete evidence.content_base64;
    }
    return value;
  }

  getConversation(conversationId, signal) {
    return this.request(`/conversations/${encodeURIComponent(conversationId)}`, { signal });
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

  promoteConversation(
    conversationId,
    {
      requestId,
      name,
      businessGoal,
      capabilityRequest,
      recipeId,
    },
    signal,
  ) {
    const selectedConversationId = String(conversationId || "").trim();
    const selectedRequestId = String(requestId || "").trim();
    const selectedName = String(name || "").trim();
    const selectedGoal = String(businessGoal || "").trim();
    if (!selectedConversationId) throw new Error("Conversation id is required");
    if (!selectedRequestId) throw new Error("Conversation promotion requires a stable request id");
    if (!selectedName || !selectedGoal) {
      throw new Error("Conversation promotion requires a concrete task name and business goal");
    }
    return this.request(
      `/conversations/${encodeURIComponent(selectedConversationId)}/promote`,
      {
        method: "POST",
        signal,
        body: {
          request_id: selectedRequestId,
          name: selectedName,
          business_goal: selectedGoal,
          ...(capabilityRequest ? { capability_request: capabilityRequest } : {}),
          ...(recipeId ? { recipe_id: recipeId } : {}),
        },
      },
    );
  }

  async getTask(taskId, signal) {
    return compactTaskForAgent(await this.request(`/tasks/${encodeURIComponent(taskId)}`, { signal }));
  }

  listExecutionAssets(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-assets`, { signal });
  }

  acquireExecutionAsset(taskId, { repository, revision, files, approvalCheckpointId }, signal) {
    if (!approvalCheckpointId || !/^[a-f0-9]{40}$/.test(revision || "")) throw new Error("Asset acquisition requires a full immutable commit and native approval");
    if (!Array.isArray(files) || !files.length || files.length > 64 || files.some(file => typeof file !== "string" || file.startsWith("/") || file.includes("\\") || file.split("/").some(part => !part || part === "." || part === ".."))) throw new Error("Asset acquisition requires explicit safe relative file paths");
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-assets`, { method: "POST", signal, headers: this.agentBridgeApprovalHeaders(),
      body: { repository, revision, files, approval: { actor: "user", checkpoint_id: approvalCheckpointId } } });
  }

  executionWorkspace(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-workspace`, { signal, executionProjection: true });
  }

  listExecutionProposals(taskId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-proposals`, { signal, executionProjection: true });
  }

  getExecutionProposal(taskId, proposalId, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-proposals/${encodeURIComponent(proposalId)}`, { signal, executionProjection: true });
  }

  createExecutionProposal(taskId, { baseSpecRevision, executionSpec, requestId }, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-proposals`, {
      method: "POST", signal, executionProjection: true,
      body: { base_spec_revision: baseSpecRevision, execution_spec: executionSpec, request_id: requestId },
    });
  }

  qualifyExecutionProposal(taskId, proposalId, { expectedProposalSha256, approvalCheckpointId, localExperimentOnly }, signal) {
    if (!approvalCheckpointId || !/^[a-f0-9]{64}$/.test(expectedProposalSha256 || "")) throw new Error("Qualification requires an exact proposal digest and native approval checkpoint");
    if (localExperimentOnly !== undefined && typeof localExperimentOnly !== "boolean") throw new Error("localExperimentOnly must be an explicit boolean");
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-proposals/${encodeURIComponent(proposalId)}/qualify`, {
      method: "POST", signal, executionProjection: true, headers: this.agentBridgeApprovalHeaders(),
      body: { expected_proposal_sha256: expectedProposalSha256, ...(localExperimentOnly !== undefined ? { local_experiment_only: localExperimentOnly } : {}), approval: { actor: "user", checkpoint_id: approvalCheckpointId } },
    });
  }

  activateExecutionProposal(taskId, proposalId, { expectedProposalSha256, qualificationId, expectedQualificationSha256, approvalCheckpointId }, signal) {
    if (!approvalCheckpointId || !qualificationId || ![expectedProposalSha256, expectedQualificationSha256].every(value => /^[a-f0-9]{64}$/.test(value || ""))) throw new Error("Activation requires exact proposal and qualification digests plus native approval");
    return this.request(`/tasks/${encodeURIComponent(taskId)}/execution-proposals/${encodeURIComponent(proposalId)}/activate`, {
      method: "POST", signal, executionProjection: true, headers: this.agentBridgeApprovalHeaders(),
      body: { expected_proposal_sha256: expectedProposalSha256, qualification_id: qualificationId, expected_qualification_sha256: expectedQualificationSha256, approval: { actor: "user", checkpoint_id: approvalCheckpointId } },
    });
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

  updateTaskSpec(taskId, { baseRevision, selectedFamily, businessGoal, name, userNote, capabilityRequest }, signal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/spec`, {
      method: "PATCH",
      signal,
      body: {
        base_revision: baseRevision,
        selected_family: selectedFamily,
        confirm: true,
        ...(name ? { name } : {}),
        ...(businessGoal ? { business_goal: businessGoal } : {}),
        ...(userNote ? { user_note: userNote } : {}),
        ...(capabilityRequest !== undefined ? { capability_request: capabilityRequest } : {}),
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

  async importMaterialDataset(taskId, materialId, inspectionSha256, options = {}, signal) {
    if (typeof taskId !== "string" || !taskId || taskId.trim() !== taskId) throw new Error("Material import requires an exact task id");
    if (typeof materialId !== "string" || !/^material-[0-9a-f]{24}$/u.test(materialId)) throw new Error("Material import requires an observed material id");
    if (typeof inspectionSha256 !== "string" || !/^[0-9a-f]{64}$/u.test(inspectionSha256)) throw new Error("Material import requires an exact inspection SHA-256");
    if (!Number.isSafeInteger(options.baseSpecRevision) || options.baseSpecRevision < 1) throw new Error("Material import requires the observed task spec revision");
    const importOptions = {};
    for (const [name, value] of [["target_column", options.targetColumn], ["ignored_columns", options.ignoredColumns], ["delimiter", options.delimiter], ["data_adapter", options.dataAdapter]]) {
      if (value !== undefined) importOptions[name] = value;
    }
    const identity = { task_id: taskId, base_spec_revision: options.baseSpecRevision, material_id: materialId, inspection_sha256: inspectionSha256, options: importOptions };
    const requestId = `material-dataset-${createHash("sha256").update(JSON.stringify(identity)).digest("hex")}`;
    const verifyResult = result => {
      const receipt = result?.dataset_upload;
      if (result?.task?.task_id !== taskId || receipt?.task_id !== taskId || receipt?.request_id !== requestId
        || receipt?.status !== "completed" || !receipt.dataset_id || receipt.dataset_id !== result.task.dataset_id
        || (result.object_refs !== undefined && (!Array.isArray(result.object_refs) || result.object_refs.some(ref => ref?.task_id !== taskId)))) {
        throw new Error("Material import returned an invalid canonical task or dataset receipt");
      }
      return result;
    };
    const current = await this.getTask(taskId, signal);
    const task = current?.task && typeof current.task === "object" ? current.task : current;
    if (task?.task_id !== taskId || !Number.isSafeInteger(task.current_spec_revision) || task.current_spec_revision < 1) {
      throw new Error("Material import could not verify the canonical TrainingTask identity and revision");
    }
    if (task.current_spec_revision !== options.baseSpecRevision) {
      // The import itself may append the adapter to the TaskSpec. Recover only
      // an exact completed receipt for these approved arguments, never post a
      // new mutation against a changed task under the old approval.
      const replay = await this.request(`/tasks/${encodeURIComponent(taskId)}/dataset-upload-receipts/${encodeURIComponent(requestId)}`, { signal });
      return { ...verifyResult(replay), idempotent_replay: true };
    }
    const result = await this.request(`/tasks/${encodeURIComponent(taskId)}/dataset-from-material`, {
      method: "POST", signal,
      body: { material_id: materialId, inspection_sha256: inspectionSha256, base_spec_revision: task.current_spec_revision, request_id: requestId, options: importOptions },
    });
    return verifyResult(result);
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
    const selectedDestination = String(destinationPath || "").trim();
    if (!selectedDestination) {
      throw new Error("Artifact Bundle destination is required");
    }
    const userSelectedAbsolutePath = isAbsolute(selectedDestination);
    if (!userSelectedAbsolutePath && /[\\/]/.test(selectedDestination)) {
      throw new Error("Workspace export destinations must use a filename only");
    }
    if (!userSelectedAbsolutePath && !this.artifactExportDir) {
      throw new Error("Runtime workspace export directory is unavailable");
    }
    const resolved = userSelectedAbsolutePath
      ? resolve(selectedDestination)
      : resolve(this.artifactExportDir, selectedDestination);
    if (extname(resolved).toLowerCase() !== ".zip") {
      throw new Error("Artifact Bundle destination must use a .zip filename");
    }
    if (!userSelectedAbsolutePath) {
      await mkdir(this.artifactExportDir, { recursive: true });
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
      destination_scope: userSelectedAbsolutePath
        ? "user_selected_path"
        : "workspace_exports",
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
