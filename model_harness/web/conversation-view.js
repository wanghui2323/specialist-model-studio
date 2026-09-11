(function attachConversationView(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ModelHarnessConversationView = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function createConversationView() {
  const SCHEMA_VERSION = "2";
  const EVENT_ALIASES = {
    "conversation.user_message": "user_message",
    "agent.final": "final_synthesis",
    "coordinator.plan": "coordinator_plan",
    "orchestrator.plan": "coordinator_plan",
    "delegation.created": "delegation",
    "orchestrator.delegated": "delegation",
    "delegation.started": "delegation",
    "delegation.completed": "specialist_output",
    "specialist.status": "specialist_status",
    "specialist.output": "specialist_output",
    "tool.call": "tool_call",
    "tool/call": "tool_call",
    "tool.started": "tool_call",
    "tool.result": "tool_result",
    "tool/result": "tool_result",
    "tool.completed": "tool_result",
    "human.approval": "approval",
    "approval/requested": "approval",
    "human.question": "question",
    "question/requested": "question",
    "orchestrator.final": "final_synthesis",
    "coordinator.note": "coordinator_note",
    "orchestrator.note": "coordinator_note",
    "turn.error": "turn_error",
    "turn.cancelled": "turn_cancelled",
    "event.failed": "failed",
    "event.warning": "warning",
    "BlockerEvidence": "blocker",
    "blocker_evidence": "blocker",
    "observation.degraded": "observation_degraded",
  };
  const KNOWN_EVENT_TYPES = new Set([
    "user_message", "coordinator_plan", "delegation", "specialist_status", "specialist_output",
    "tool_call", "tool_result", "approval", "question", "final_synthesis", "coordinator_note",
    "turn_error", "turn_cancelled", "failed", "blocker", "warning", "observation_degraded",
  ]);
  const TEAM_EVENT_TYPES = new Set([
    "delegation", "specialist_status", "specialist_output", "tool_call", "tool_result",
  ]);
  const ROLE_LABELS = {
    orchestrator: "训练协调器",
    research_source: "研究与来源",
    data_experiment: "数据与实验",
    resource_safety: "资源与安全",
    build_training: "构建与训练",
    evaluation_delivery: "评测与交付",
    training_orchestrator: "训练协调器",
  };
  const TOOL_LABELS = {
    model_harness_list_recipes: "检查可用训练方案",
    model_harness_list_data_adapters: "检查数据导入方式",
    model_harness_match_capability: "匹配训练能力",
    model_harness_list_tasks: "检查现有训练任务",
    model_harness_create_task: "创建训练任务",
    model_harness_promote_conversation: "建立模型任务",
    model_harness_get_task: "了解当前任务",
    model_harness_update_task_spec: "确认任务理解",
    model_harness_clarify_task_spec: "补充任务理解",
    model_harness_import_dataset: "导入并体检数据",
    model_harness_configure_contract: "设置训练条件",
    model_harness_confirm_contract: "确认训练设置",
    model_harness_authorize_task_run_start: "申请启动本次训练",
    model_harness_start_task_run: "启动真实训练",
    model_harness_get_run: "读取训练结果",
    model_harness_get_events: "读取运行事件",
    model_harness_get_evaluation_report: "读取评测报告",
    model_harness_authorize_sample_inference: "申请本次新样本试跑",
    model_harness_run_sample_inference: "试跑用户新样本",
    model_harness_list_sample_inferences: "查看新样本试跑",
    model_harness_get_sample_inference: "读取试跑证据",
    model_harness_authorize_artifact_bundle_build: "申请构建本次交付包",
    model_harness_build_artifact_bundle: "构建可下载交付包",
    model_harness_list_artifact_bundles: "查看交付包",
    model_harness_get_artifact_bundle: "读取交付包证据",
    model_harness_download_artifact_bundle: "确认并下载交付包",
    model_harness_get_strategies: "分析优化策略",
    model_harness_apply_task_strategy: "执行下一轮优化",
    model_harness_cancel_run: "取消训练运行",
    report: "专家已回传结论",
    model_harness_list_model_source_providers: "检查公开模型来源",
    model_harness_search_model_sources: "联网搜索模型候选",
    model_harness_list_model_source_searches: "读取来源搜索记录",
    model_harness_select_model_source_candidate: "选择模型候选",
    model_harness_resolve_model_source: "固定模型不可变版本",
    model_harness_list_model_source_resolutions: "读取来源固定记录",
    model_harness_bind_model_source: "绑定并静态分析模型来源",
    model_harness_list_model_bindings: "读取模型绑定记录",
    model_harness_get_repository_analysis: "读取仓库静态分析",
    model_harness_create_training_plan: "生成训练计划",
    model_harness_get_training_plan: "读取训练计划",
    model_harness_revise_training_plan: "修订训练计划",
    model_harness_decide_training_plan: "审批训练计划",
    model_harness_check_resource_feasibility: "检查本机资源可行性",
    model_harness_get_resource_feasibility: "读取资源可行性证据",
    model_harness_hf_capability: "检查 Hugging Face 能力边界",
    model_harness_hf_search: "搜索 Hugging Face 模型",
    model_harness_hf_card: "读取 Hugging Face 模型卡",
    model_harness_hf_attach: "绑定 Hugging Face 固定版本",
    model_harness_hf_verify: "验证 Hugging Face 模型资产",
    model_harness_stage_recipe_samples: "暂存 Recipe 构建样例",
    model_harness_scaffold_recipe: "生成 Recipe 构建包",
    model_harness_build_recipe: "构建并验证 Recipe",
    model_harness_get_recipe_build: "读取 Recipe 构建证据",
    model_harness_register_recipe: "注册已验证 Recipe",
    model_harness_reject_recipe: "拒绝 Recipe 注册",
    ask_user_question: "等待你的决定",
    send_message: "转交给专家",
    todo_write: "更新执行计划",
  };
  const ACTIVE_EVENT_TYPES = Object.freeze([
    "domain_action",
    "running_delegation",
    "pending_human_checkpoint",
  ]);
  const ACTION_TOOL_CLASSES = new Set(["domain", "control", "delegation", "unknown"]);
  const ACTION_STATUSES = new Set(["running", "completed", "failed", "cancelled", "identity_error"]);

  function eventType(item) {
    const raw = item?.event_type || item?.type || (KNOWN_EVENT_TYPES.has(item?.kind) ? item.kind : null);
    const aliased = EVENT_ALIASES[raw] || raw || null;
    if (KNOWN_EVENT_TYPES.has(aliased)) return aliased;
    const category = item?.category;
    if (category === "user_message") return "user_message";
    if (category === "final") return "final_synthesis";
    if (category === "narration") return "coordinator_note";
    if (category === "delegation") return /completed|result|output/u.test(String(raw)) ? "specialist_output" : "delegation";
    if (category === "tool") return /completed|result/u.test(String(raw)) ? "tool_result" : "tool_call";
    if (category === "approval" || category === "question") return category;
    if (category === "agent_status") return "specialist_status";
    return aliased;
  }

  function displayValue(value) {
    if (value == null) return null;
    let text;
    if (typeof value === "string") text = value;
    else {
      try { text = JSON.stringify(value); } catch (_error) { text = String(value); }
    }
    return text.length > 800 ? `${text.slice(0, 800)}…（完整结果保留在任务审计事件中）` : text;
  }

  function normalizeRole(value) {
    return value === "training_orchestrator" ? "orchestrator" : value || null;
  }

  function normalizeTime(value) {
    if (typeof value === "number" && value > 0 && value < 1_000_000_000_000) {
      return value * 1000;
    }
    return value || null;
  }

  function typedTruthState(value) {
    if (value == null || value === "") return null;
    const token = String(value).trim().replace(/([a-z0-9])([A-Z])/g, "$1_$2").replace(/[^a-zA-Z0-9]+/g, "_").toLowerCase();
    if (["failed", "failure", "error", "turn_error"].includes(token)) return "failed";
    if (["blocker", "blocked", "blocker_evidence"].includes(token)) return "blocker";
    if (["warning", "warn"].includes(token)) return "warning";
    if (["observation_degraded", "projection_degraded"].includes(token)) return "observation_degraded";
    return null;
  }

  function trainingCapabilityProjection(task) {
    const selected = task && typeof task === "object" ? task : {};
    const result = selected.current_result && typeof selected.current_result === "object"
      ? selected.current_result
      : null;
    const runId = result?.run_id || selected.current_run_id || null;
    const report = result?.evaluation_report && typeof result.evaluation_report === "object"
      ? result.evaluation_report
      : null;
    if (selected.status === "completed" && result?.status === "completed" && runId) {
      const reportBound = report?.run_id === runId;
      const releaseReady = reportBound && report?.release_ready === true;
      return {
        code: reportBound ? "trained_with_evaluation" : "trained_evidence_pending",
        label: "已完成真实训练",
        state: reportBound ? "completed" : "pending",
        reason: reportBound
          ? `Run ${runId} 已完成并生成独立评测；${releaseReady ? "当前离线门槛通过。" : "仍需按评测结论处理，不能声称可发布。"}`
          : `Run ${runId} 已完成，但独立评测证据仍需核对。`,
      };
    }
    const feasibility = selected.resource_feasibility && typeof selected.resource_feasibility === "object"
      ? selected.resource_feasibility
      : {};
    const decision = feasibility.decision || "not_checked";
    if (decision === "fit_with_revision") {
      return {
        code: decision,
        label: "需要调整训练计划",
        state: "pending",
        reason: feasibility.blockers?.[0]?.message || "当前机器可以继续，但必须先批准资源收缩后的新计划。",
      };
    }
    if (["blocked_platform", "blocked_environment", "blocked_resources"].includes(decision)) {
      return {
        code: decision,
        label: "当前环境不满足",
        state: "blocked",
        reason: feasibility.blockers?.[0]?.message || "当前机器或隔离环境不满足已批准计划。",
      };
    }
    if (selected.capability_status === "matched" && selected.recipe_id) {
      return {
        code: decision === "fit" ? "available_resource_fit" : "available_verified_recipe",
        label: "已验证训练方案",
        state: "available",
        reason: `已注册 ${selected.recipe_id}；仍需数据体检、合同确认和运行审批。`,
      };
    }
    if (selected.capability_decision?.selected_family === "audio_classification" && selected.current_recipe_build?.status === "awaiting_registration") {
      return {
        code: "requires_recipe_registration",
        label: "等待注册训练方案",
        state: "pending",
        reason: "可信声明式 Recipe 已验证，但尚未获得人工注册批准。",
      };
    }
    if (selected.capability_status === "needs_recipe") {
      return {
        code: "unavailable_no_verified_recipe",
        label: "暂无可执行训练方案",
        state: "blocked",
        reason: selected.capability_decision?.selected_family === "asr"
          ? "语音转文字可继续静态诊断，但当前没有已验证训练 Recipe。"
          : "当前模型族没有已验证、已注册的训练 Recipe。",
      };
    }
    return {
      code: "capability_pending",
      label: "等待能力判断",
      state: "pending",
      reason: "需求确认前不会声称可以训练。",
    };
  }

  function normalizeStatus(value, fallbackType = null) {
    if (value == null || value === "") return typedTruthState(fallbackType) || "unknown";
    return typedTruthState(value) || String(value);
  }

  function isV2Conversation(conversation) {
    const version = String(conversation?.schema_version || "");
    return version === SCHEMA_VERSION || version.startsWith(`${SCHEMA_VERSION}.`) || (conversation?.items || []).some((item) => Boolean(eventType(item)));
  }

  function eventId(item, index) {
    return String(item?.event_id || item?.id || item?.call_id || item?.rpc_id || `${item?.seq ?? "legacy"}:${eventType(item) || item?.kind || "item"}:${index}`);
  }

  function normalizeEvent(item, index, liveV2) {
    const type = eventType(item);
    const payload = item?.payload && typeof item.payload === "object" ? item.payload : {};
    const resultPreview = item?.result_preview ?? payload.result_preview;
    const resultTruncated = item?.result_truncated === true || payload.result_truncated === true;
    const rawResult = item?.result ?? payload.result;
    const eventResultRef = item?.event_result_ref && typeof item.event_result_ref === "object"
      ? item.event_result_ref
      : payload.event_result_ref && typeof payload.event_result_ref === "object"
        ? payload.event_result_ref
        : null;
    const actorRole = normalizeRole(item?.actor_role || item?.actor?.role || item?.agent_id || (type === "coordinator_plan" || type === "final_synthesis" ? "orchestrator" : null));
    const status = normalizeStatus(item?.status, type);
    const truthType = typedTruthState(item?.truth_type || item?.severity || status || type);
    const base = {
      ...item,
      event_id: eventId(item, index),
      event_type: type,
      actor_role: actorRole,
      time: normalizeTime(item?.time || item?.timestamp || item?.timestamp_utc || item?.received_at),
      status,
      truth_type: truthType,
      title: item?.title || item?.label || null,
      summary: item?.summary || item?.detail || item?.text || payload.text || null,
      text: item?.text || payload.text || null,
      call_id: item?.call_id || payload.call_id || null,
      tool_name: item?.tool_name || payload.tool_name || null,
      to_role: normalizeRole(item?.to_role || item?.specialist_role || payload.target_agent_id),
      result: displayValue(rawResult ?? resultPreview),
      result_preview: displayValue(resultPreview),
      result_truncated: resultTruncated,
      result_size_bytes: item?.result_size_bytes ?? payload.result_size_bytes ?? null,
      result_is_preview: rawResult == null && resultPreview != null && resultTruncated,
      result_notice: resultTruncated ? "当前仅显示脱敏工具结果预览；完整结果请通过只读事件结果查看。" : null,
      event_result_ref: eventResultRef ? { ...eventResultRef } : null,
      rpc_id: item?.rpc_id || payload.rpc_id || null,
      questions: item?.questions || payload.questions || [],
      object_refs: Array.isArray(item?.object_refs) ? item.object_refs : (Array.isArray(payload.object_refs) ? payload.object_refs : []),
    };

    if (type) {
      if (!KNOWN_EVENT_TYPES.has(type)) return { ...base, kind: "unknown_event" };
      if (type === "user_message") return { ...base, kind: "message", role: "user", text: base.text || base.summary || "" };
      if (type === "final_synthesis") {
        if (base.actor_role !== "orchestrator") return { ...base, kind: "unknown_event", contract_error: "final_synthesis must be owned by orchestrator" };
        const verdict = payload.synthesis_verdict && typeof payload.synthesis_verdict === "object"
          ? payload.synthesis_verdict
          : null;
        const classifierAllowed = verdict?.accepted === true;
        const validEvidenceRefs = base.object_refs.filter((ref) => (
          ref && typeof ref === "object"
          && typeof ref.type === "string" && ref.type.length > 0
          && typeof ref.id === "string" && ref.id.length > 0
          && typeof ref.task_id === "string" && ref.task_id.length > 0
          && (!base.task_id || ref.task_id === base.task_id)
        ));
        const completionEligible = classifierAllowed && validEvidenceRefs.length > 0;
        const contractErrors = [];
        if (!classifierAllowed) contractErrors.push("final_synthesis requires classifier permission");
        if (!validEvidenceRefs.length) contractErrors.push("final_synthesis requires evidence object_refs");
        return {
          ...base,
          kind: "final_synthesis",
          text: base.summary || "训练协调器没有返回综合结论。",
          status: completionEligible || base.status !== "completed" ? base.status : "observed",
          truth_type: completionEligible ? "evidence_backed_final" : "unverified_narration",
          synthesis_verdict: verdict,
          classifier_allowed: classifierAllowed,
          completion_eligible: completionEligible,
          contract_error: contractErrors.length ? contractErrors.join("; ") : null,
        };
      }
      if (type === "coordinator_note") return { ...base, kind: "coordinator_note", text: base.summary || "训练协调器没有提供说明。" };
      return { ...base, kind: type };
    }

    if (item?.kind === "message" && item?.role === "user") return { ...base, kind: "message", role: "user", text: item.text || "" };
    if (item?.kind === "message" && item?.role === "assistant") {
      if (liveV2 && item?.message_type === "final_synthesis" && base.actor_role === "orchestrator") return { ...base, kind: "final_synthesis", text: item.text || base.summary || "" };
      return { ...base, kind: "system_record", label: liveV2 ? "未归类的运行时消息" : "旧会话记录", detail: item.text || "没有消息正文" };
    }
    if (item?.kind === "tool") return { ...base, kind: "system_record", label: item.label || "旧工具记录", detail: item.detail || item.result || "没有工具结果摘要" };
    if (item?.kind === "system_record") return { ...base, kind: "system_record", label: item.label || "系统记录", detail: item.detail || item.text || "" };
    return { ...base, kind: "unknown_event", event_type: item?.kind || "unknown" };
  }

  function dedupe(items) {
    const seen = new Set();
    return items.filter((item) => {
      if (seen.has(item.event_id)) return false;
      seen.add(item.event_id);
      return true;
    });
  }

  function compareItems(left, right) {
    const leftSeq = Number(left.seq); const rightSeq = Number(right.seq);
    if (Number.isFinite(leftSeq) && Number.isFinite(rightSeq) && leftSeq !== rightSeq) return leftSeq - rightSeq;
    const leftTime = new Date(left.time || 0).getTime(); const rightTime = new Date(right.time || 0).getTime();
    if (leftTime !== rightTime) return leftTime - rightTime;
    return left.event_id.localeCompare(right.event_id);
  }

  function groupForRender(items) {
    const rendered = []; let teamEvents = []; let teamTurn = null;
    const flushTeam = () => {
      if (!teamEvents.length) return;
      rendered.push({
        kind: "team_activity",
        event_id: `team:${teamTurn || teamEvents[0].event_id}`,
        turn_id: teamTurn,
        events: [...teamEvents],
      });
      teamEvents = []; teamTurn = null;
    };
    items.forEach((item) => {
      if (TEAM_EVENT_TYPES.has(item.kind)) {
        const turn = item.turn_id || "unscoped";
        if (teamEvents.length && turn !== teamTurn) flushTeam();
        teamTurn = turn; teamEvents.push(item); return;
      }
      flushTeam(); rendered.push(item);
    });
    flushTeam();
    return rendered;
  }

  function actionContractError(code, message) {
    return { code, message };
  }

  function normalizeAction(action, index = 0) {
    const source = action && typeof action === "object" ? action : {};
    const actionId = typeof source.action_id === "string" && source.action_id ? source.action_id : null;
    const toolClass = ACTION_TOOL_CLASSES.has(source.tool_class) ? source.tool_class : "unknown";
    const validStatus = ACTION_STATUSES.has(source.status);
    const status = actionId && validStatus ? source.status : "identity_error";
    let error = source.error && typeof source.error === "object" ? { ...source.error } : null;
    if (!actionId) error = actionContractError("missing_action_id", "Backend conversation action is missing action_id.");
    else if (!validStatus) error = actionContractError("invalid_action_status", "Backend conversation action has an unsupported status.");
    const activeType = status === "running" && toolClass === "domain"
      ? "domain_action"
      : status === "running" && toolClass === "delegation"
        ? "running_delegation"
        : null;
    return {
      kind: "action",
      schema_version: source.schema_version || null,
      action_id: actionId,
      render_key: actionId || `invalid-action:${index}`,
      task_id: source.task_id || null,
      agent_run_id: source.agent_run_id || null,
      session_id: source.session_id || null,
      turn_id: source.turn_id || null,
      call_id: source.call_id || null,
      tool_name: source.tool_name || null,
      tool_class: toolClass,
      actor_role: normalizeRole(source.actor_role),
      started_at_utc: source.started_at_utc || null,
      ended_at_utc: source.ended_at_utc || null,
      duration_ms: Number.isFinite(source.duration_ms) && source.duration_ms >= 0 ? source.duration_ms : null,
      status,
      active_type: activeType,
      delegation_id: source.delegation_id || null,
      parent_delegation_id: source.parent_delegation_id || null,
      object_refs: Array.isArray(source.object_refs) ? source.object_refs.map((ref) => ({ ...ref })) : [],
      event_result_ref: source.event_result_ref && typeof source.event_result_ref === "object"
        ? { ...source.event_result_ref }
        : null,
      error,
      truth_type: source.truth_type || (status === "identity_error" ? "identity_error" : null),
      call_event_id: source.call_event_id || null,
      result_event_id: source.result_event_id || null,
    };
  }

  function normalizeActions(actions) {
    return Array.isArray(actions) ? actions.map(normalizeAction) : [];
  }

  function pendingEvents(pending, existing) {
    const known = new Set(existing.map((item) => item.rpc_id).filter(Boolean));
    const lastSeq = existing.reduce((maximum, item) => Number.isFinite(Number(item.seq)) ? Math.max(maximum, Number(item.seq)) : maximum, 0);
    return (pending || []).filter((item) => item?.rpc_id && !known.has(item.rpc_id)).map((item, index) => normalizeEvent({
      ...item,
      event_id: item.event_id || `pending:${item.rpc_id}`,
      event_type: item.kind === "approval" ? "approval" : "question",
      status: "pending",
      time: normalizeTime(item.time || item.received_at),
      seq: item.seq ?? lastSeq + index + 1,
    }, index + existing.length, true));
  }

  function mergePendingDetails(pending, existing) {
    const byRpcId = new Map((pending || []).filter((item) => item?.rpc_id).map((item) => [item.rpc_id, item]));
    const checkpoints = new Map();
    const passthrough = [];
    existing.forEach((item) => {
      if (!item.rpc_id || (item.kind !== "approval" && item.kind !== "question")) {
        passthrough.push(item);
        return;
      }
      const group = checkpoints.get(item.rpc_id) || [];
      group.push(item);
      checkpoints.set(item.rpc_id, group);
    });
    const collapsed = [];
    checkpoints.forEach((group, rpcId) => {
      const live = byRpcId.get(rpcId);
      const terminal = [...group].reverse().find((item) => !["pending", "waiting"].includes(item.status));
      const selected = live ? group[group.length - 1] : (terminal || group[group.length - 1]);
      collapsed.push(normalizeEvent({
        ...selected,
        ...(live || {}),
        event_id: selected.event_id,
        event_type: selected.event_type,
        seq: selected.seq,
        status: live ? "pending" : (terminal?.status || "resolved"),
      }, passthrough.length + collapsed.length, true));
    });
    const reconciled = [...passthrough, ...collapsed];
    return [...reconciled, ...pendingEvents(pending, reconciled)];
  }

  function invalidateCheckpointsAfterTerminal(items) {
    const terminalByTurn = new Map();
    (items || []).forEach((item) => {
      if (!["turn_error", "turn_cancelled"].includes(item?.kind) || !item.turn_id) return;
      const current = terminalByTurn.get(item.turn_id);
      if (!current || compareItems(current, item) <= 0) terminalByTurn.set(item.turn_id, item);
    });
    if (!terminalByTurn.size) return items;
    return (items || []).map((item) => {
      if (!["approval", "question"].includes(item?.kind) || !["pending", "waiting"].includes(item.status) || !item.turn_id) return item;
      const terminal = terminalByTurn.get(item.turn_id);
      if (!terminal) return item;
      return {
        ...item,
        status: "invalidated",
        invalidated_by_event_id: terminal.event_id,
        invalidated_reason: "The owning turn terminated before this checkpoint could be resolved.",
      };
    });
  }

  function evidenceLedger(items) {
    const records = dedupe((items || []).map((item, index) => normalizeEvent({ ...item, kind: "system_record" }, index, false))).sort(compareItems);
    return records.length ? [{ kind: "evidence_ledger", event_id: "persisted-task-evidence", items: records }] : [];
  }

  function pendingCheckpoint(items) {
    return [...items].reverse().find((item) => (item.kind === "approval" || item.kind === "question") && ["pending", "waiting"].includes(item.status)) || null;
  }

  function activeEvent(items, actions = []) {
    const checkpoint = pendingCheckpoint(items);
    if (checkpoint) return { ...checkpoint, active_type: "pending_human_checkpoint" };
    return [...actions].reverse().find((action) => ACTIVE_EVENT_TYPES.includes(action.active_type)) || null;
  }

  function copiedRecords(value, { objectType = null } = {}) {
    if (!Array.isArray(value)) return [];
    return value
      .filter((item) => item && typeof item === "object" && (!objectType || item.object_type === objectType))
      .map((item) => ({ ...item }));
  }

  function canonicalRemoteActiveEvent(value) {
    if (!value || typeof value !== "object") return null;
    if (["TrainingRun", "AgentTurn", "HumanCheckpoint", "BackgroundAction"].includes(value.object_type)) return { ...value };
    if (ACTIVE_EVENT_TYPES.includes(value.active_type)) return { ...value };
    if ((value.kind === "question" || value.kind === "approval") && ["pending", "waiting"].includes(value.status)) return { ...value };
    return null;
  }

  function projectionErrorCode(value) {
    const token = typeof value === "string" ? value.trim() : "";
    return /^[a-z][a-z0-9_.:-]*$/i.test(token) ? token : "projection_error";
  }

  function normalizeProjectionErrors(value) {
    if (value == null) return [];
    const entries = Array.isArray(value) ? value : [value];
    return entries.map((entry, index) => {
      const source = entry && typeof entry === "object" ? entry : { error: entry };
      const nestedError = source.error && typeof source.error === "object" ? source.error : {};
      const rawError = typeof source.error === "string" ? source.error : null;
      const code = projectionErrorCode(source.code || nestedError.code || rawError);
      const message = String(source.message || nestedError.message || rawError || "投影错误没有提供可读原因。");
      const severity = typedTruthState(source.severity || source.status || nestedError.severity) || "observation_degraded";
      const sessionId = source.session_id || source.dsh_session_id || null;
      const turnId = source.turn_id || null;
      const sourceEventId = source.source_event_id || source.event_id || null;
      return {
        kind: "projection_error",
        error_id: String(source.error_id || source.id || `${sessionId || "session-unknown"}:${turnId || "turn-unknown"}:${code}:${index + 1}`),
        code,
        message,
        severity,
        session_id: sessionId,
        turn_id: turnId,
        source_event_id: sourceEventId,
        details: source.details && typeof source.details === "object" ? source.details : null,
      };
    });
  }

  function typedStateCounts(items) {
    const counts = { failed: 0, blocker: 0, warning: 0, observation_degraded: 0 };
    (items || []).forEach((item) => {
      const state = typedTruthState(item?.truth_type || item?.severity || item?.status || item?.kind);
      if (state) counts[state] += 1;
    });
    return counts;
  }

  function deriveProjectionHealth(remote, normalizedItems = [], liveV2 = isV2Conversation(remote)) {
    const projectionErrors = normalizeProjectionErrors(remote?.projection_errors);
    const eventCounts = typedStateCounts(normalizedItems);
    const errorCounts = typedStateCounts(projectionErrors);
    const reportedValue = typeof remote?.projection_health === "string"
      ? remote.projection_health
      : remote?.projection_health?.status || remote?.projection_health?.state;
    const reportedStatus = typedTruthState(reportedValue)
      || (["healthy", "not_observed"].includes(reportedValue) ? reportedValue : null);
    const observationDegraded = projectionErrors.length > 0
      || eventCounts.observation_degraded > 0
      || reportedStatus === "observation_degraded";
    const status = !liveV2
      ? "not_observed"
      : observationDegraded
        ? "observation_degraded"
        : reportedStatus || "healthy";
    return {
      status,
      reported_status: reportedStatus,
      projection_error_count: projectionErrors.length,
      projection_errors: projectionErrors,
      typed_event_counts: eventCounts,
      typed_projection_error_counts: errorCounts,
    };
  }

  function buildConversationView({ remoteConversation, localItems = [], ledgerItems = [] }) {
    const remote = remoteConversation || {};
    const liveSession = Boolean(remote.session_id);
    const liveV2 = liveSession && isV2Conversation(remote);
    const source = liveSession ? (remote.items || []) : localItems;
    let normalized = dedupe(source.map((item, index) => normalizeEvent(item, index, liveV2))).sort(compareItems);
    if (liveV2) normalized = invalidateCheckpointsAfterTerminal(dedupe(mergePendingDetails(remote.pending, normalized)).sort(compareItems));
    const items = groupForRender(normalized);
    if (!liveV2) items.push(...evidenceLedger(ledgerItems));
    const actions = liveV2 ? normalizeActions(remote.actions) : [];
    const projectionHealth = deriveProjectionHealth(remote, normalized, liveV2);
    return {
      schema_version: liveV2 ? SCHEMA_VERSION : "legacy",
      task_id: typeof remote.task_id === "string" ? remote.task_id : null,
      event_payload_mode: liveV2 ? (remote.event_payload_mode || null) : null,
      live_v2: liveV2,
      items,
      actions,
      agents: liveV2 && Array.isArray(remote.agents)
        ? remote.agents.map((item) => ({ ...item }))
        : [],
      delegations: liveV2 && Array.isArray(remote.delegations)
        ? remote.delegations.map((item) => ({ ...item }))
        : [],
      work_items: liveV2 && Array.isArray(remote.work_items)
        ? remote.work_items.map((item) => ({ ...item }))
        : [],
      work_item_schema_version: liveV2 ? (remote.work_item_schema_version || null) : null,
      action_schema_version: liveV2 ? (remote.action_schema_version || null) : null,
      running: liveV2 && remote.running === true,
      execution_running: liveV2 && remote.execution_running === true,
      agent_response_running: liveV2 && remote.agent_response_running === true,
      background_action_running: liveV2 && remote.background_action_running === true,
      interaction_state: liveV2 ? (remote.interaction_state || "idle") : "idle",
      interaction_projection: liveV2 && remote.interaction_projection && typeof remote.interaction_projection === "object"
        ? {
          ...remote.interaction_projection,
          turn_identity: remote.interaction_projection.turn_identity && typeof remote.interaction_projection.turn_identity === "object"
            ? { ...remote.interaction_projection.turn_identity }
            : null,
        }
        : null,
      can_cancel_agent: liveV2 && remote.can_cancel_agent === true,
      active_event: liveV2 ? (canonicalRemoteActiveEvent(remote.active_event) || activeEvent(normalized, actions)) : null,
      runs: liveV2 ? copiedRecords(remote.runs) : [],
      agent_turns: liveV2 ? copiedRecords(remote.agent_turns, { objectType: "AgentTurn" }) : [],
      training_runs: liveV2 ? copiedRecords(remote.training_runs, { objectType: "TrainingRun" }) : [],
      background_actions: liveV2 ? copiedRecords(remote.background_actions) : [],
      human_checkpoints: liveV2 ? copiedRecords(remote.human_checkpoints, { objectType: "HumanCheckpoint" }) : [],
      risks: liveV2 ? copiedRecords(remote.risks) : [],
      primary_attention: liveV2 && remote.primary_attention && typeof remote.primary_attention === "object" ? { ...remote.primary_attention } : null,
      supported_modes: liveV2 && Array.isArray(remote.supported_modes) ? [...remote.supported_modes] : [],
      projection_errors: projectionHealth.projection_errors,
      projection_health: projectionHealth,
    };
  }

  return {
    SCHEMA_VERSION,
    KNOWN_EVENT_TYPES: [...KNOWN_EVENT_TYPES],
    TEAM_EVENT_TYPES: [...TEAM_EVENT_TYPES],
    ACTIVE_EVENT_TYPES,
    ROLE_LABELS,
    TOOL_LABELS,
    eventType,
    isV2Conversation,
    trainingCapabilityProjection,
    normalizeEvent,
    normalizeProjectionErrors,
    deriveProjectionHealth,
    normalizeAction,
    normalizeActions,
    invalidateCheckpointsAfterTerminal,
    groupForRender,
    activeEvent,
    pendingCheckpoint,
    buildConversationView,
  };
});
