(function attachInteractionShell(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ModelHarnessInteractionShell = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function createInteractionShell() {
  const PHASES = Object.freeze([
    "clarifying",
    "awaiting_approval",
    "executing",
    "result_ready",
    "blocked",
    "failed",
    "idle",
  ]);

  const TERMINAL_FAILURE_STATUSES = new Set([
    "failed",
    "failure",
    "error",
    "identity_error",
    "turn_error",
  ]);
  const BLOCKED_STATUSES = new Set([
    "blocked",
    "blocker",
    "blocker_evidence",
    "blocked_environment",
    "blocked_platform",
    "blocked_resources",
  ]);
  const PENDING_STATUSES = new Set(["pending", "waiting"]);
  const EXPECTED_QUESTION_CONTROL_GATES = new Set([
    "task_spec_ambiguous",
    "task_spec_needs_clarification",
    "awaiting_clarification",
    "awaiting_human_clarification",
    "needs_clarification",
  ]);
  const EXPECTED_APPROVAL_CONTROL_GATES = new Set([
    "task_spec_confirmation_required",
    "task_spec_needs_confirmation",
    "awaiting_confirmation",
    "awaiting_human_confirmation",
    "needs_confirmation",
    "awaiting_approval",
  ]);
  const RUNNING_STATUSES = new Set([
    "active", "running", "working", "queued", "starting",
    "created", "preflight", "training", "evaluating", "proposing", "packaging", "needs_input",
  ]);
  const TERMINAL_CANCELLED_STATUSES = new Set(["cancelled", "interrupted"]);
  const TERMINAL_COMPLETED_STATUSES = new Set(["completed", "succeeded", "success"]);
  const ACTIVE_TURN_STATES = new Set([
    "agent_working",
    "background_working",
    "executing",
    "running",
    "processing",
  ]);
  const NON_CANCELABLE_TURN_STATES = new Set([
    "awaiting_approval",
    "blocked",
    "cancelled",
    "cancelling",
    "clarifying",
    "completed",
    "failed",
    "idle",
    "needs_confirmation",
    "observation_degraded",
    "paused",
    "result_ready",
    "stopped",
    "stopping",
    "waiting",
    "waiting_approval",
    "waiting_question",
  ]);

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function normalizedToken(value) {
    return String(value || "")
      .trim()
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .replace(/[^a-zA-Z0-9]+/g, "_")
      .toLowerCase();
  }

  function canShowTurnStop(presentation) {
    if (!isRecord(presentation) || presentation.current !== true || presentation.can_cancel !== true) return false;
    const phase = normalizedToken(presentation.phase);
    const statuses = [presentation.status, presentation.tone].map(normalizedToken).filter(Boolean);
    const states = [phase, ...statuses].filter(Boolean);
    if (states.some((state) => NON_CANCELABLE_TURN_STATES.has(state))) return false;
    if (phase && !ACTIVE_TURN_STATES.has(phase)) return false;
    if (statuses.some((status) => !ACTIVE_TURN_STATES.has(status))) return false;
    return states.some((state) => ACTIVE_TURN_STATES.has(state));
  }

  function createAiTurnFrame(documentRef, root, values = {}) {
    if (!documentRef || typeof documentRef.createElement !== "function") throw new TypeError("documentRef.createElement is required");
    if (!root || typeof root.append !== "function") throw new TypeError("root.append is required");
    const section = documentRef.createElement("section");
    section.className = "ai-turn";
    section.dataset.turnId = String(values.turnId || "");
    section.dataset.state = String(values.state || "");
    section.dataset.current = String(values.current === true);
    const avatar = documentRef.createElement("span");
    avatar.className = "ai-turn-avatar";
    avatar.textContent = "AI";
    avatar.setAttribute("aria-hidden", "true");
    const main = documentRef.createElement("div");
    main.className = "ai-turn-main";
    const header = documentRef.createElement("header");
    header.className = "ai-turn-header";
    const content = documentRef.createElement("div");
    content.className = "ai-turn-content";
    main.append(header, content);
    section.append(avatar, main);
    root.append(section);
    return { section, avatar, main, header, content };
  }

  function conversationTurnTarget({ role, root, aiContent = null } = {}) {
    if (role === "user") {
      if (!root || typeof root.append !== "function") throw new TypeError("root.append is required for a user turn");
      return root;
    }
    if (!aiContent || typeof aiContent.append !== "function") throw new TypeError("aiContent.append is required for an AI turn");
    return aiContent;
  }

  function numericSeq(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function itemIdentity(item, fallback) {
    return String(item?.event_id || item?.id || item?.rpc_id || item?.call_id || fallback);
  }

  function expandItems(items) {
    const expanded = [];
    asArray(items).forEach((item, itemIndex) => {
      if (item?.kind === "team_activity" && Array.isArray(item.events)) {
        item.events.forEach((event, eventIndex) => {
          expanded.push({
            item: event?.turn_id || !item.turn_id ? event : { ...event, turn_id: item.turn_id },
            render_item: item,
            source_index: itemIndex,
            nested_index: eventIndex,
          });
        });
        return;
      }
      expanded.push({ item, render_item: item, source_index: itemIndex, nested_index: 0 });
    });
    return expanded;
  }

  function turnSessionId(turnId) {
    if (typeof turnId !== "string" || !turnId) return null;
    const marker = turnId.lastIndexOf(":turn:");
    return marker > 0 ? turnId.slice(0, marker) : null;
  }

  function verifiedTurnLineage(conversation) {
    const verifiedWorkItems = new Map(asArray(conversation?.work_items)
      .filter((item) => (
        isRecord(item)
        && item.lineage_verified === true
        && typeof item.delegation_id === "string" && item.delegation_id
        && typeof item.child_session_id === "string" && item.child_session_id
      ))
      .map((item) => [item.delegation_id, item]));
    const parentByDelegation = new Map();
    const parentsByChildSession = new Map();
    asArray(conversation?.delegations).forEach((delegation) => {
      if (!isRecord(delegation)) return;
      const workItem = verifiedWorkItems.get(delegation.delegation_id);
      const parentTurnId = typeof delegation.parent_turn_id === "string" && delegation.parent_turn_id
        ? delegation.parent_turn_id
        : null;
      const childSessionId = workItem?.child_session_id;
      const delegatedSessionId = delegation.dsh_session_id || delegation.child_session_id;
      if (!workItem || !parentTurnId || !childSessionId || (delegatedSessionId && delegatedSessionId !== childSessionId)) return;
      parentByDelegation.set(delegation.delegation_id, parentTurnId);
      if (!parentsByChildSession.has(childSessionId)) parentsByChildSession.set(childSessionId, new Set());
      parentsByChildSession.get(childSessionId).add(parentTurnId);
    });

    const uniqueParentForSession = (sessionId) => {
      const parents = parentsByChildSession.get(sessionId);
      return parents?.size === 1 ? [...parents][0] : null;
    };
    const resolve = (turnId, delegationId = null) => {
      if (typeof turnId !== "string" || !turnId) return null;
      let selected = turnId;
      let selectedDelegation = delegationId;
      const visited = new Set();
      while (!visited.has(selected)) {
        visited.add(selected);
        const sessionId = turnSessionId(selected);
        const parent = (selectedDelegation && parentByDelegation.get(selectedDelegation))
          || (sessionId && uniqueParentForSession(sessionId));
        if (!parent || parent === selected) break;
        selected = parent;
        selectedDelegation = null;
      }
      return selected;
    };
    return { resolve, uniqueParentForSession };
  }

  function canonicalAgentTurnIndex(conversation) {
    const byAgentTurnId = new Map();
    const byAgentRunId = new Map();
    asArray(conversation?.agent_turns).forEach((turn) => {
      if (!isRecord(turn)) return;
      const agentTurnId = typeof turn.agent_turn_id === "string" && turn.agent_turn_id
        ? turn.agent_turn_id
        : null;
      const agentRunId = typeof turn.agent_run_id === "string" && turn.agent_run_id
        ? turn.agent_run_id
        : typeof turn.run_id === "string" && turn.run_id
          ? turn.run_id
          : null;
      if (!agentTurnId) return;
      const identity = { agent_turn_id: agentTurnId, agent_run_id: agentRunId };
      byAgentTurnId.set(agentTurnId, identity);
      if (agentRunId) byAgentRunId.set(agentRunId, identity);
    });
    const resolve = (value) => {
      if (!isRecord(value)) return null;
      const agentRunId = typeof value.agent_run_id === "string" && value.agent_run_id
        ? value.agent_run_id
        : null;
      if (agentRunId && byAgentRunId.has(agentRunId)) return byAgentRunId.get(agentRunId);
      const declaredAgentTurnId = typeof value.agent_turn_id === "string" && value.agent_turn_id
        ? value.agent_turn_id
        : typeof value.payload?.agent_turn_id === "string" && value.payload.agent_turn_id
          ? value.payload.agent_turn_id
          : null;
      return declaredAgentTurnId ? byAgentTurnId.get(declaredAgentTurnId) || null : null;
    };
    return {
      resolve,
      onlyIdentity: byAgentTurnId.size === 1 ? [...byAgentTurnId.values()][0] : null,
    };
  }

  /**
   * Rebuilds human-readable turns from the already-normalized conversation view.
   * It intentionally does not inspect prose, pair tool events, or create actions.
   */
  function groupConversationTurns(input) {
    const conversation = Array.isArray(input) ? { items: input } : (input || {});
    const canonicalTurns = canonicalAgentTurnIndex(conversation);
    const lineage = verifiedTurnLineage(conversation);
    const groups = new Map();
    const order = [];
    const lastTurnBySession = new Map();

    expandItems(conversation.items).forEach((entry, expandedIndex) => {
      const item = entry.item;
      if (!isRecord(item)) return;
      const sourceTurnId = typeof item.turn_id === "string" && item.turn_id ? item.turn_id : null;
      const sessionId = typeof item.session_id === "string" && item.session_id
        ? item.session_id
        : typeof item.dsh_session_id === "string" && item.dsh_session_id
          ? item.dsh_session_id
          : turnSessionId(sourceTurnId);
      const inferredTurnId = !sourceTurnId && item.kind !== "message" && sessionId
        ? lineage.uniqueParentForSession(sessionId) || lastTurnBySession.get(sessionId) || null
        : null;
      const backendCurrentAgentTurnId = conversation?.interaction_projection?.turn_identity?.agent_turn_id;
      const uniqueCurrentFallback = canonicalTurns.onlyIdentity
        && canonicalTurns.onlyIdentity.agent_turn_id === backendCurrentAgentTurnId
        && (!sourceTurnId || sourceTurnId === "unscoped")
        && item.kind !== "message"
        ? canonicalTurns.onlyIdentity
        : null;
      const canonicalIdentity = canonicalTurns.resolve(item) || uniqueCurrentFallback;
      const legacyTurnId = lineage.resolve(sourceTurnId || inferredTurnId, item.delegation_id) || null;
      const turnId = canonicalIdentity?.agent_turn_id || legacyTurnId;
      // Unscoped records stay separate. Merging them would invent a shared turn.
      // A record carrying an agent_run_id which joins to a backend AgentTurn
      // is explicitly scoped; this does not invent a relationship between raw
      // DSH turns.
      const key = canonicalIdentity
        ? `agent-turn:${canonicalIdentity.agent_turn_id}`
        : turnId || `unscoped:${itemIdentity(item, expandedIndex)}`;
      if (!groups.has(key)) {
        groups.set(key, {
          turn_id: turnId,
          agent_turn_id: canonicalIdentity?.agent_turn_id || null,
          group_key: key,
          first_seq: null,
          last_seq: null,
          items: [],
          render_items: [],
          event_ids: [],
          _agent_run_ids: new Set(),
          _source_turn_ids: new Set(),
          _render_ids: new Set(),
          _first_index: expandedIndex,
        });
        order.push(key);
      }
      const group = groups.get(key);
      if (canonicalIdentity?.agent_run_id) group._agent_run_ids.add(canonicalIdentity.agent_run_id);
      if (sourceTurnId && sourceTurnId !== "unscoped") group._source_turn_ids.add(sourceTurnId);
      if (legacyTurnId && sessionId) lastTurnBySession.set(sessionId, legacyTurnId);
      group.items.push({
        value: item,
        seq: numericSeq(item.seq),
        source_index: entry.source_index,
        nested_index: entry.nested_index,
        expanded_index: expandedIndex,
      });
      const renderId = itemIdentity(entry.render_item, `${key}:render:${entry.source_index}`);
      if (!group._render_ids.has(renderId)) {
        group._render_ids.add(renderId);
        group.render_items.push(entry.render_item);
      }
    });

    asArray(conversation.actions).forEach((action) => {
      if (!isRecord(action)) return;
      const canonicalIdentity = canonicalTurns.resolve(action);
      const legacyTurnId = typeof action.turn_id === "string" && action.turn_id
        ? lineage.resolve(action.turn_id, action.delegation_id)
        : null;
      const group = canonicalIdentity
        ? groups.get(`agent-turn:${canonicalIdentity.agent_turn_id}`)
        : legacyTurnId ? groups.get(legacyTurnId) : null;
      if (!group) return;
      if (canonicalIdentity?.agent_run_id) group._agent_run_ids.add(canonicalIdentity.agent_run_id);
      if (action.turn_id) group._source_turn_ids.add(action.turn_id);
    });

    return order.map((key) => {
      const group = groups.get(key);
      group.items.sort((left, right) => {
        if (left.seq != null && right.seq != null && left.seq !== right.seq) return left.seq - right.seq;
        return left.expanded_index - right.expanded_index;
      });
      const items = group.items.map((entry) => entry.value);
      const renderItems = group.render_items.map((item, index) => {
        const nestedSequences = item?.kind === "team_activity"
          ? asArray(item.events).map((event) => numericSeq(event?.seq)).filter((seq) => seq != null)
          : [];
        return {
          item,
          index,
          seq: numericSeq(item?.seq) ?? (nestedSequences.length ? Math.min(...nestedSequences) : null),
        };
      }).sort((left, right) => {
        if (left.seq != null && right.seq != null && left.seq !== right.seq) return left.seq - right.seq;
        return left.index - right.index;
      }).map((entry) => entry.item);
      const sequences = group.items.map((entry) => entry.seq).filter((seq) => seq != null);
      return {
        turn_id: group.turn_id,
        agent_turn_id: group.agent_turn_id,
        agent_run_id: [...group._agent_run_ids][0] || null,
        agent_run_ids: [...group._agent_run_ids],
        group_key: group.group_key,
        first_seq: sequences.length ? Math.min(...sequences) : null,
        last_seq: sequences.length ? Math.max(...sequences) : null,
        items,
        render_items: renderItems,
        source_turn_ids: [...group._source_turn_ids],
        event_ids: items.map((item, index) => itemIdentity(item, `${group.group_key}:${index}`)),
      };
    });
  }

  function taskOwned(value, taskId) {
    if (!isRecord(value)) return false;
    if (!taskId) return true;
    return value.task_id === taskId;
  }

  function taskOwnedActions(conversation, taskId) {
    return asArray(conversation?.actions).filter((action) => (
      isRecord(action) && (!taskId || action.task_id === taskId)
    ));
  }

  function latestTurnActions(actions, currentTurn) {
    if (!currentTurn) return actions;
    const agentRunIds = new Set(currentTurn.agent_run_ids || []);
    if (currentTurn.agent_run_id) agentRunIds.add(currentTurn.agent_run_id);
    if (agentRunIds.size) {
      const sourceTurnIds = new Set(currentTurn.source_turn_ids || []);
      return actions.filter((action) => (
        agentRunIds.has(action.agent_run_id)
        || (!action.agent_run_id && sourceTurnIds.has(action.turn_id))
      ));
    }
    if (currentTurn.turn_id) {
      const sourceTurnIds = new Set(currentTurn.source_turn_ids || [currentTurn.turn_id]);
      sourceTurnIds.add(currentTurn.turn_id);
      return actions.filter((action) => sourceTurnIds.has(action.turn_id));
    }
    return actions.filter((action) => !action.turn_id);
  }

  function selectCurrentTurn(turns, conversation) {
    const requestedAgentTurnId = conversation?.interaction_projection?.turn_identity?.agent_turn_id;
    if (typeof requestedAgentTurnId === "string" && requestedAgentTurnId) {
      const selected = turns.find((turn) => turn.agent_turn_id === requestedAgentTurnId);
      if (selected) return selected;
    }
    return turns.reduce((latest, turn, index) => {
      if (!latest) return { turn, index };
      const latestSeq = latest.turn.last_seq == null ? Number.NEGATIVE_INFINITY : latest.turn.last_seq;
      const turnSeq = turn.last_seq == null ? Number.NEGATIVE_INFINITY : turn.last_seq;
      if (turnSeq > latestSeq || (turnSeq === latestSeq && index > latest.index)) return { turn, index };
      return latest;
    }, null)?.turn || null;
  }

  function supersededFailureSourceIds(risks) {
    return new Set(asArray(risks).filter((risk) => (
      isRecord(risk)
      && risk.active === false
      && normalizedToken(risk.lifecycle_status) === "superseded"
      && normalizedToken(risk.resolution?.kind) === "superseded_by_later_success"
      && typeof risk.source_id === "string" && risk.source_id
    )).map((risk) => risk.source_id));
  }

  function canonicalRiskLifecycleAvailable(risks) {
    return asArray(risks).some((risk) => (
      isRecord(risk)
      && typeof risk.active === "boolean"
      && typeof risk.lifecycle_status === "string"
      && typeof risk.source_id === "string"
      && risk.source_id
    ));
  }

  function activeFailureSourceIds(risks) {
    return new Set(asArray(risks).filter((risk) => (
      isRecord(risk)
      && risk.active === true
      && normalizedToken(risk.lifecycle_status) === "active"
      && typeof risk.source_id === "string"
      && risk.source_id
    )).map((risk) => risk.source_id));
  }

  function turnHasActiveFailure(turn, actions, risks) {
    const superseded = supersededFailureSourceIds(risks);
    const canonicalLifecycle = canonicalRiskLifecycleAvailable(risks);
    const activeFailures = activeFailureSourceIds(risks);
    if (asArray(actions).some((action) => (
      TERMINAL_FAILURE_STATUSES.has(normalizedToken(action?.status))
      && (canonicalLifecycle
        ? activeFailures.has(action?.action_id)
        : !superseded.has(action?.action_id))
    ))) return true;
    return asArray(turn?.items).some((item) => (
      (item?.kind === "turn_error" || item?.kind === "failed")
      && (canonicalLifecycle
        ? [itemIdentity(item, ""), turn?.agent_turn_id, turn?.agent_run_id]
          .filter(Boolean)
          .some((identity) => activeFailures.has(identity))
        : !superseded.has(itemIdentity(item, "")))
    ));
  }

  function activeBackgroundWork(task, conversation, actions, checkpoint) {
    // Modern lifecycle flags describe the live execution snapshot. Historical
    // AgentRuns/tool observations are not independent background workers.
    const canonicalExecution = typeof conversation?.execution_running === "boolean";
    const waitingToolNames = new Set(["ask_user_question", "request_user_input"]);
    const waitingForHuman = Boolean(checkpoint?.item);
    const activeActions = actions.filter((action) => {
      if (canonicalExecution) return false;
      if (!RUNNING_STATUSES.has(normalizedToken(action.status))) return false;
      return !(waitingForHuman && waitingToolNames.has(normalizedToken(action.tool_name)));
    });
    const activeRuns = asArray(conversation?.runs).filter((run) => (
      !canonicalExecution && isRecord(run) && RUNNING_STATUSES.has(normalizedToken(run.status))
    ));
    const activeTrainingRuns = asArray(conversation?.training_runs).filter((run) => (
      isRecord(run)
      && (!run.object_type || run.object_type === "TrainingRun")
      && taskOwned(run, task?.task_id || null)
      && (run.running === true || run.worker_running === true || cancellationPending({ runs: [run] }) || RUNNING_STATUSES.has(normalizedToken(run.status)) || RUNNING_STATUSES.has(normalizedToken(run.domain_status)))
    ));
    const activeBackgroundActions = asArray(conversation?.background_actions).filter((backgroundAction) => (
      isRecord(backgroundAction)
      && normalizedToken(backgroundAction.action_type || backgroundAction.object_type) === "training_run"
      && taskOwned(backgroundAction, task?.task_id || null)
      && (backgroundAction.running === true || backgroundAction.worker_running === true || cancellationPending({ runs: [backgroundAction] }) || RUNNING_STATUSES.has(normalizedToken(backgroundAction.status)))
    ));
    const activeTaskResult = isRecord(task?.current_result)
      && RUNNING_STATUSES.has(normalizedToken(task.current_result.status))
      ? task.current_result
      : null;
    return {
      running: activeActions.length > 0 || activeRuns.length > 0 || activeTrainingRuns.length > 0 || activeBackgroundActions.length > 0 || Boolean(activeTaskResult),
      action_ids: activeActions.map((action) => action.action_id).filter(Boolean),
      run_ids: activeRuns.map((run) => run.run_id).filter(Boolean),
      training_run_ids: [...activeTrainingRuns, ...activeBackgroundActions, ...(activeTaskResult ? [activeTaskResult] : [])]
        .map((run) => run.training_run_id || run.run_id)
        .filter(Boolean),
      active_actions: activeActions,
      active_runs: activeRuns,
      active_training_runs: activeTrainingRuns,
      active_background_actions: activeBackgroundActions,
      active_task_result: activeTaskResult,
    };
  }

  function cancellationPending(conversation) {
    const cancellingStatuses = new Set(["cancel_requested", "cancelling", "stopping"]);
    return [
      ...asArray(conversation?.training_runs),
      ...asArray(conversation?.background_actions),
      ...asArray(conversation?.runs),
      ...asArray(conversation?.agent_turns),
    ].some((entry) => isRecord(entry) && !(
      ["cancelled", "canceled", "completed", "failed", "interrupted"].includes(normalizedToken(entry.status))
      && entry.running !== true && entry.worker_running !== true
    ) && (
      entry.cancel_requested === true
      || cancellingStatuses.has(normalizedToken(entry.status))
      || cancellingStatuses.has(normalizedToken(entry.domain_status))
    ));
  }

  function checkpointFromTurns(turns) {
    const checkpoints = turns.flatMap((turn) => turn.items.map((item) => ({ item, turn })))
      .filter(({ item }) => (
        (item.kind === "question" || item.kind === "approval")
        && PENDING_STATUSES.has(normalizedToken(item.status))
      ));
    return checkpoints.length ? checkpoints[checkpoints.length - 1] : null;
  }

  function currentTurnFailure(items, actions, risks = [], turn = null) {
    const superseded = supersededFailureSourceIds(risks);
    const canonicalLifecycle = canonicalRiskLifecycleAvailable(risks);
    const activeFailures = activeFailureSourceIds(risks);
    const failedItem = items.find((item) => (
      (item.kind === "turn_error"
        || item.kind === "failed"
        || TERMINAL_FAILURE_STATUSES.has(normalizedToken(item.status))
        || TERMINAL_FAILURE_STATUSES.has(normalizedToken(item.truth_type)))
      && (canonicalLifecycle
        ? [itemIdentity(item, ""), turn?.agent_turn_id, turn?.agent_run_id]
          .filter(Boolean)
          .some((identity) => activeFailures.has(identity))
        : !superseded.has(itemIdentity(item, "")))
    ));
    if (failedItem) return { source: "event", item: failedItem };
    const failedAction = actions.find((action) => (
      TERMINAL_FAILURE_STATUSES.has(normalizedToken(action.status))
      && (canonicalLifecycle
        ? activeFailures.has(action.action_id)
        : !superseded.has(action.action_id))
    ));
    return failedAction ? { source: "action", action: failedAction } : null;
  }

  function currentTurnBlocker(items) {
    const blocker = items.find((item) => (
      item.kind === "blocker"
      || item.kind === "BlockerEvidence"
      || BLOCKED_STATUSES.has(normalizedToken(item.status))
      || BLOCKED_STATUSES.has(normalizedToken(item.truth_type))
    ));
    return blocker || null;
  }

  function taskFailure(task) {
    const resultStatus = normalizedToken(task?.current_result?.status);
    const taskStatus = normalizedToken(task?.status);
    return TERMINAL_FAILURE_STATUSES.has(resultStatus) || TERMINAL_FAILURE_STATUSES.has(taskStatus);
  }

  function expectedHumanControlGate(blocker, checkpoint) {
    const rawCode = typeof blocker === "string"
      ? blocker
      : isRecord(blocker)
        ? blocker.code || blocker.reason_code || blocker.type || blocker.id
        : null;
    const code = normalizedToken(rawCode);
    if (!checkpoint?.item) {
      return EXPECTED_QUESTION_CONTROL_GATES.has(code)
        || EXPECTED_APPROVAL_CONTROL_GATES.has(code);
    }
    if (checkpoint.item.kind === "question") return EXPECTED_QUESTION_CONTROL_GATES.has(code);
    if (checkpoint.item.kind === "approval") return EXPECTED_APPROVAL_CONTROL_GATES.has(code);
    return false;
  }

  function taskBlocker(task, checkpoint = null) {
    const resultStatus = normalizedToken(task?.current_result?.status);
    const taskStatus = normalizedToken(task?.status);
    if (BLOCKED_STATUSES.has(resultStatus) || BLOCKED_STATUSES.has(taskStatus)) return true;
    return asArray(task?.control?.blocked_by).some((blocker) => (
      blocker?.active !== false && !expectedHumanControlGate(blocker, checkpoint)
    ));
  }

  function taskOwnedRefs(values, taskId) {
    return asArray(values).filter((ref) => (
      isRecord(ref)
      && typeof ref.type === "string" && ref.type.length > 0
      && typeof ref.id === "string" && ref.id.length > 0
      && taskOwned(ref, taskId)
    ));
  }

  function evidenceTimestamp(value) {
    if (!isRecord(value)) return null;
    for (const field of ["completed_at_utc", "created_at_utc", "updated_at_utc", "time", "timestamp"]) {
      const raw = value[field];
      const parsed = typeof raw === "number" ? (raw < 1_000_000_000_000 ? raw * 1000 : raw) : Date.parse(raw);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  }

  function evaluationIdentity(evaluation) {
    if (!isRecord(evaluation)) return null;
    for (const field of ["event_id", "evaluation_event_id", "evidence_digest", "report_digest", "digest", "report_sha256", "content_sha256", "evaluation_report_id", "evaluation_id"]) {
      const value = evaluation[field];
      if (typeof value === "string" && value.trim()) return `${field}:${value.trim()}`;
    }
    return null;
  }

  function deriveResultEvidence(task, turns, actions) {
    const taskId = task?.task_id || null;
    const finalEntries = turns.flatMap((turn, turnIndex) => turn.items.map((item) => ({ item, turnIndex })))
      .filter(({ item }) => item.kind === "final_synthesis");
    const eligibleFinals = finalEntries.filter(({ item }) => {
      if (item.completion_eligible !== true) return false;
      const refs = taskOwnedRefs(item.object_refs, taskId);
      return refs.length > 0 || (!taskId && item.completion_eligible === true);
    });
    const latestFinalEntry = eligibleFinals.length ? eligibleFinals[eligibleFinals.length - 1] : null;
    const latestFinal = latestFinalEntry?.item || null;
    const currentResult = isRecord(task?.current_result) ? task.current_result : null;
    const runId = currentResult?.run_id || task?.current_run_id || null;
    const currentRunMatches = Boolean(
      currentResult
      && normalizedToken(currentResult.status) === "completed"
      && runId
      && (!task?.current_run_id || currentResult.run_id === task.current_run_id)
      && (!currentResult.task_id || !taskId || currentResult.task_id === taskId)
    );
    const evaluation = isRecord(currentResult?.evaluation_report)
      ? currentResult.evaluation_report
      : isRecord(task?.evaluation_report)
        ? task.evaluation_report
        : null;
    const evaluationMatches = Boolean(
      evaluation
      && runId
      && evaluation.run_id === runId
      && (!evaluation.task_id || !taskId || evaluation.task_id === taskId)
    );
    const userEntries = turns.flatMap((turn, turnIndex) => turn.items.map((item) => ({ item, turnIndex })))
      .filter(({ item }) => (item.kind === "message" && item.role === "user") || item.category === "user_message");
    const latestUser = userEntries.length ? userEntries[userEntries.length - 1] : null;
    const resultTurnId = evaluation?.turn_id || currentResult?.turn_id || currentResult?.agent_turn_id || null;
    const resultTurnIndex = resultTurnId ? turns.findIndex((turn) => turn.turn_id === resultTurnId) : -1;
    const evidenceTime = evidenceTimestamp(evaluation) ?? evidenceTimestamp(currentResult) ?? evidenceTimestamp(latestFinal);
    const userTime = evidenceTimestamp(latestUser?.item);
    const evidenceTurnIndex = latestFinalEntry?.turnIndex ?? (resultTurnIndex >= 0 ? resultTurnIndex : null);
    const supersededByNewTurn = Boolean(latestUser && (
      (evidenceTurnIndex != null && latestUser.turnIndex > evidenceTurnIndex)
      || (evidenceTurnIndex == null && evidenceTime != null && userTime != null && userTime > evidenceTime)
      || (evidenceTurnIndex == null && evidenceTime == null)
    ));
    const finalRefs = latestFinal && !supersededByNewTurn ? taskOwnedRefs(latestFinal.object_refs, taskId) : [];
    const matchedRunId = currentRunMatches || evaluationMatches ? runId : null;
    const matchedEvaluationIdentity = evaluationMatches ? evaluationIdentity(evaluation) : null;
    return {
      ready: !supersededByNewTurn && Boolean(latestFinal || currentRunMatches || evaluationMatches),
      final: supersededByNewTurn ? null : latestFinal,
      object_refs: finalRefs,
      run_id: matchedRunId,
      matched_run_id: matchedRunId,
      evaluation: evaluationMatches && !supersededByNewTurn ? evaluation : null,
      evaluation_identity: matchedEvaluationIdentity,
      completion_eligible: !supersededByNewTurn && Boolean(latestFinal),
      superseded_by_new_turn: supersededByNewTurn,
    };
  }

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function baselineCandidateName(candidates) {
    return Object.keys(candidates).find((name) => /(^|[_-])baseline($|[_-])/iu.test(name)) || null;
  }

  function comparableMetric(baseline, selected) {
    const definitions = [
      ["macro_f1", "Macro-F1", "higher"],
      ["accuracy", "Accuracy", "higher"],
      ["worst_class_recall", "最差类 Recall", "higher"],
      ["mae", "MAE", "lower"],
      ["rmse", "RMSE", "lower"],
      ["r2", "R²", "higher"],
    ];
    for (const [key, label, direction] of definitions) {
      const baselineValue = finiteNumber(baseline?.[key]);
      const selectedValue = finiteNumber(selected?.[key]);
      if (baselineValue != null && selectedValue != null) {
        return { key, label, direction, baseline_value: baselineValue, selected_value: selectedValue };
      }
    }
    return null;
  }

  /**
   * Projects a release decision only from a completed task-owned run and its
   * matching evaluation report. Missing comparison evidence stays missing.
   */
  function deriveEvaluationOutcome({ task = null, evaluation = null } = {}) {
    const taskId = task?.task_id || null;
    const result = isRecord(task?.current_result) ? task.current_result : null;
    const runId = result?.run_id || null;
    const report = isRecord(evaluation)
      ? evaluation
      : isRecord(result?.evaluation_report)
        ? result.evaluation_report
        : null;
    const ready = Boolean(
      result
      && normalizedToken(result.status) === "completed"
      && runId
      && report
      && report.run_id === runId
      && (!result.task_id || !taskId || result.task_id === taskId)
      && (!report.task_id || !taskId || report.task_id === taskId)
    );
    if (!ready) return { ready: false, run_id: runId, evaluation: null, comparison: null, decision: null };

    const candidates = isRecord(result.metrics?.validation_candidates)
      ? result.metrics.validation_candidates
      : {};
    const baselineName = baselineCandidateName(candidates);
    const selectedName = typeof result.metrics?.selected_model === "string"
      ? result.metrics.selected_model
      : null;
    const metric = baselineName && selectedName && isRecord(candidates[baselineName]) && isRecord(candidates[selectedName])
      ? comparableMetric(candidates[baselineName], candidates[selectedName])
      : null;
    let comparison = null;
    if (metric) {
      const improvement = metric.direction === "lower"
        ? metric.baseline_value - metric.selected_value
        : metric.selected_value - metric.baseline_value;
      const tolerance = 1e-12;
      comparison = {
        source: "validation_candidates",
        baseline: { name: baselineName, value: metric.baseline_value },
        selected: { name: selectedName, value: metric.selected_value },
        metric: metric.key,
        metric_label: metric.label,
        direction: metric.direction,
        improvement,
        degraded: improvement < -tolerance,
        unchanged: Math.abs(improvement) <= tolerance,
      };
    }
    const releaseReady = report.release_ready === true;
    const recommended = comparison?.degraded
      ? "rollback"
      : releaseReady
        ? "publish"
        : "optimize";
    return {
      ready: true,
      run_id: runId,
      evaluation: report,
      release_ready: releaseReady,
      conclusion: report.conclusion || result.evaluation_conclusion || "not_evaluated",
      comparison,
      decision: {
        recommended,
        publish: releaseReady && comparison?.degraded !== true ? "ready" : "blocked",
        rollback: comparison?.degraded === true ? "recommended" : "not_needed",
        optimize: !releaseReady && comparison?.degraded !== true ? "recommended" : "optional",
      },
    };
  }

  function terminalStatus(values) {
    const statuses = asArray(values).map(normalizedToken).filter(Boolean);
    if (statuses.some((status) => TERMINAL_FAILURE_STATUSES.has(status))) return "failed";
    if (statuses.some((status) => TERMINAL_CANCELLED_STATUSES.has(status))) return "cancelled";
    if (statuses.some((status) => TERMINAL_COMPLETED_STATUSES.has(status))) return "completed";
    return null;
  }

  function effectiveWorkItemStatus(workItem, delegation, agent, ownedActions) {
    // A verified work item and its exact agent/delegation binding are the
    // canonical lifecycle. Historical action and narration events remain in
    // the audit trail, but cannot keep a terminal specialist "running".
    const workItemCanonical = terminalStatus([workItem?.status]);
    if (workItemCanonical) return workItemCanonical;
    const canonical = terminalStatus([delegation?.status, agent?.status]);
    if (canonical) return canonical;
    const observed = [
      workItem?.status,
      delegation?.status,
      agent?.status,
      ...asArray(ownedActions).map((action) => action?.status),
    ].map(normalizedToken).filter(Boolean);
    if (observed.some((status) => TERMINAL_FAILURE_STATUSES.has(status))) return "failed";
    if (observed.some((status) => RUNNING_STATUSES.has(status))) return "running";
    return "observed";
  }

  function workItemRecency(workItem, sourceIndex) {
    const observedSequence = [
      workItem?.observed_updated_sequence,
      workItem?.observed_started_sequence,
    ].find((value) => Number.isSafeInteger(value) && value >= 0);
    const timestamp = [
      workItem?.updated_at_utc,
      workItem?.ended_at_utc,
      workItem?.started_at_utc,
    ].map((value) => Date.parse(value || "")).find(Number.isFinite);
    return {
      observed_sequence: observedSequence ?? null,
      timestamp: timestamp ?? null,
      source_index: sourceIndex,
    };
  }

  function isLaterWorkItem(candidate, current) {
    if (!current) return true;
    const candidateSequence = candidate.recency.observed_sequence;
    const currentSequence = current.recency.observed_sequence;
    if (candidateSequence !== null || currentSequence !== null) {
      if (candidateSequence === null) return false;
      if (currentSequence === null) return true;
      if (candidateSequence !== currentSequence) return candidateSequence > currentSequence;
    }
    const candidateTimestamp = candidate.recency.timestamp;
    const currentTimestamp = current.recency.timestamp;
    if (candidateTimestamp !== null || currentTimestamp !== null) {
      if (candidateTimestamp === null) return false;
      if (currentTimestamp === null) return true;
      if (candidateTimestamp !== currentTimestamp) return candidateTimestamp > currentTimestamp;
    }
    return candidate.recency.source_index > current.recency.source_index;
  }

  function reconcileTeamActivityEvents(events, specialists) {
    const byRole = new Map();
    const byDelegation = new Map();
    asArray(specialists).forEach((specialist) => {
      if (!isRecord(specialist)) return;
      if (specialist.role) byRole.set(specialist.role, specialist);
      asArray(specialist.delegation_ids).forEach((id) => {
        if (id) byDelegation.set(id, specialist);
      });
    });
    return asArray(events).map((event) => {
      if (!isRecord(event)) return event;
      const role = event.to_role || event.specialist_role || event.actor_role;
      const specialist = byDelegation.get(event.delegation_id) || byRole.get(role);
      const canonical = normalizedToken(specialist?.status);
      const historical = normalizedToken(event.status);
      if (!["completed", "failed", "cancelled"].includes(canonical)) return event;
      if (historical && !RUNNING_STATUSES.has(historical) && !PENDING_STATUSES.has(historical) && historical !== "observed") return event;
      return {
        ...event,
        status: canonical,
        historical_status: event.status || null,
        status_source: "canonical_work_item",
      };
    });
  }

  function delegationProjection(conversation, actions, taskId) {
    const workItems = asArray(conversation?.work_items).filter((item) => (
      isRecord(item)
      && item.lineage_verified === true
      && typeof item.work_item_id === "string" && item.work_item_id
      && typeof item.delegation_id === "string" && item.delegation_id
      && typeof item.role?.role_id === "string" && item.role.role_id && item.role.role_id !== "orchestrator"
      && taskOwned(item, taskId)
    ));
    const verifiedDelegationIds = new Set(workItems.map((item) => item.delegation_id));
    const delegations = asArray(conversation?.delegations)
      .filter((delegation) => isRecord(delegation) && verifiedDelegationIds.has(delegation.delegation_id))
      .map((delegation) => ({ ...delegation, provenance: "conversation.work_items" }));
    const delegationById = new Map(delegations.map((delegation) => [delegation.delegation_id, delegation]));
    const agentsById = new Map(asArray(conversation?.agents)
      .filter((agent) => isRecord(agent) && typeof agent.agent_id === "string" && agent.agent_id)
      .map((agent) => [agent.agent_id, agent]));
    const specialistsByRole = new Map();
    workItems.forEach((workItem, sourceIndex) => {
      const role = workItem.role.role_id;
      const ownedActions = actions.filter((action) => action.delegation_id === workItem.delegation_id);
      if (!specialistsByRole.has(role)) {
        specialistsByRole.set(role, {
          role,
          label: workItem.role.label || null,
          work_item_ids: [],
          delegation_ids: [],
          action_ids: [],
          status: "observed",
          latest_work_item_id: null,
          historical_failure_count: 0,
          _work_history: [],
        });
      }
      const specialist = specialistsByRole.get(role);
      specialist.work_item_ids.push(workItem.work_item_id);
      specialist.delegation_ids.push(workItem.delegation_id);
      ownedActions.forEach((action) => {
        if (action.action_id) specialist.action_ids.push(action.action_id);
      });
      specialist._work_history.push({
        work_item_id: workItem.work_item_id,
        status: effectiveWorkItemStatus(
          workItem,
          delegationById.get(workItem.delegation_id),
          agentsById.get(workItem.role.agent_id),
          ownedActions,
        ),
        recency: workItemRecency(workItem, sourceIndex),
      });
    });

    const specialists = [...specialistsByRole.values()].map((specialist) => {
      const { _work_history: workHistory, ...value } = specialist;
      const latest = workHistory.reduce((selected, candidate) => (
        isLaterWorkItem(candidate, selected) ? candidate : selected
      ), null);
      return {
        ...value,
        latest_work_item_id: latest?.work_item_id || null,
        historical_failure_count: workHistory.filter((item) => (
          item.work_item_id !== latest?.work_item_id && item.status === "failed"
        )).length,
        status: latest?.status || "observed",
      };
    });
    return { work_items: workItems, delegations, specialists };
  }

  function workspaceRefTypes(values, taskId) {
    return new Set(taskOwnedRefs(values, taskId).map((ref) => normalizedToken(ref.type)));
  }

  /**
   * Decides how the secondary workspace behaves without reading coordinator
   * prose.  A workspace may be available without opening itself: normal tool
   * calls and a live training run stay in the dialogue until the user asks to
   * inspect them.  Only structured plan approvals, data-quality exceptions,
   * and a first task-owned evaluation may auto-open.
   */
  function workspaceFor({ task, phase, currentTurn, checkpoint, currentActions, activeActions, specialists, resultEvidence, reasonCode }) {
    const taskId = task?.task_id || "task-unscoped";
    const phaseSettings = {
      clarifying: ["decision", "clarification"],
      awaiting_approval: ["decision", "approval"],
      executing: [specialists.length ? "collaboration" : "execution", specialists.length ? "agent_collaboration" : "coordinator_execution"],
      result_ready: ["result", "result"],
      blocked: ["status", "blocker"],
      failed: ["status", "error"],
      idle: ["closed", "idle"],
    };
    const [mode, context] = phaseSettings[phase];
    const checkpointRefTypes = workspaceRefTypes(checkpoint?.item?.object_refs, taskId);
    const turnRefTypes = workspaceRefTypes((currentTurn?.items || []).flatMap((item) => asArray(item?.object_refs)), taskId);
    const planApproval = phase === "awaiting_approval"
      && ["training_plan", "training_plan_revision", "task_contract"].some((type) => checkpointRefTypes.has(type));
    const dataException = ["blocked", "failed"].includes(phase)
      && ["dataset_report", "data_quality_report", "data_inspection"].some((type) => turnRefTypes.has(type));
    // Auto-opening an evaluation is stricter than merely exposing its refs.
    // resultEvidence.evaluation is present only when the report matches the
    // current completed run; a historical task action must never steal focus.
    const evaluationReady = phase === "result_ready"
      && Boolean(resultEvidence.evaluation)
      && Boolean(resultEvidence.matched_run_id)
      && Boolean(resultEvidence.evaluation_identity)
      && resultEvidence.superseded_by_new_turn !== true;
    const autoOpen = planApproval || dataException || evaluationReady;
    const autoReason = planApproval
      ? "plan_confirmation"
      : dataException
        ? "data_exception"
        : evaluationReady
          ? "evaluation_ready"
          : null;
    const technicalContext = planApproval
      ? "plan"
      : dataException
        ? "data"
        : evaluationReady
          ? "evaluation"
          : phase === "executing"
            ? "run"
            : phase === "result_ready"
              ? "evaluation"
              : "plan";
    const presentation = planApproval || dataException ? "technical" : "experience";
    const focusId = checkpoint?.item?.rpc_id
      || resultEvidence.final?.event_id
      || currentActions.find((action) => action.status === "running")?.action_id
      || activeActions.find((action) => RUNNING_STATUSES.has(normalizedToken(action.status)))?.action_id
      || currentActions[currentActions.length - 1]?.action_id
      || resultEvidence.run_id
      || currentTurn?.turn_id
      || "none";
    const evaluationAutoKey = resultEvidence.matched_run_id && resultEvidence.evaluation_identity
      ? [taskId, "evaluation", resultEvidence.matched_run_id, resultEvidence.evaluation_identity].join(":")
      : null;
    return {
      mode,
      context,
      open: mode !== "closed",
      auto_open: autoOpen,
      auto_reason: autoReason,
      technical_context: technicalContext,
      presentation,
      auto_key: evaluationAutoKey || [taskId, phase, currentTurn?.turn_id || currentTurn?.group_key || "no-turn", focusId, reasonCode, autoReason || "manual"].join(":"),
      focus_id: focusId,
    };
  }

  function deriveInteractionProjection({ task = null, conversation = null } = {}) {
    const safeConversation = conversation || {};
    const taskId = task?.task_id || null;
    const turns = groupConversationTurns(safeConversation);
    const currentTurn = selectCurrentTurn(turns, safeConversation);
    const actions = taskOwnedActions(safeConversation, taskId);
    const currentActions = latestTurnActions(actions, currentTurn);
    const currentItems = currentTurn?.items || [];
    const checkpoint = checkpointFromTurns(currentTurn ? [currentTurn] : turns);
    const projectionDegraded = safeConversation?.projection_health?.status === "observation_degraded"
      || asArray(safeConversation?.projection_errors).length > 0;
    const turnFailure = currentTurnFailure(currentItems, currentActions, safeConversation.risks, currentTurn);
    const turnBlocker = currentTurnBlocker(currentItems);
    const observedTaskFailure = taskFailure(task);
    const observedTaskBlocker = taskBlocker(task, checkpoint);
    const resultEvidence = deriveResultEvidence(task, turns, actions);
    const collaboration = delegationProjection(safeConversation, actions, taskId);
    const background = activeBackgroundWork(task, safeConversation, actions, checkpoint);
    const cancelling = cancellationPending(safeConversation);
    const agentResponseRunning = safeConversation.agent_response_running === true;
    const backgroundTrainingRunning = safeConversation.background_action_running === true || background.running;
    const backendRunning = safeConversation.execution_running === true
      || safeConversation.running === true
      || normalizedToken(safeConversation.interaction_state) === "working";

    let phase = "idle";
    let reasonCode = "idle";
    if (projectionDegraded) {
      // Observation health is fail-closed. A checkpoint projected from an
      // untrusted stream may be stale and must not remain actionable.
      phase = "failed";
      reasonCode = "observation_degraded";
    } else if (cancelling) {
      phase = "executing";
      reasonCode = "cancellation_pending";
    } else if (checkpoint?.item?.kind === "approval") {
      phase = "awaiting_approval";
      reasonCode = "pending_approval";
    } else if (checkpoint?.item?.kind === "question") {
      phase = "clarifying";
      reasonCode = "pending_question";
    } else if (agentResponseRunning) {
      phase = "executing";
      reasonCode = "agent_response_running";
    } else if (backgroundTrainingRunning) {
      phase = "executing";
      reasonCode = "observed_active_background_work";
    } else if (turnFailure || observedTaskFailure) {
      phase = "failed";
      reasonCode = turnFailure?.item?.kind === "turn_error" ? "turn_error" : "execution_failed";
    } else if (turnBlocker) {
      phase = "blocked";
      reasonCode = "blocker_evidence";
    } else if (observedTaskBlocker) {
      // A task-level blocker can explain why an action needs human input, but it
      // must not replace that active decision in the foreground interaction.
      phase = "blocked";
      reasonCode = "blocker_evidence";
    } else if (backendRunning) {
      phase = "executing";
      reasonCode = "backend_turn_running";
    } else if (resultEvidence.ready) {
      phase = "result_ready";
      reasonCode = resultEvidence.completion_eligible ? "completion_eligible_final" : "task_result_evidence";
    }

    return {
      phase,
      reason_code: reasonCode,
      turns,
      current_turn: currentTurn,
      actions,
      current_actions: currentActions,
      work_items: collaboration.work_items,
      delegations: collaboration.delegations,
      specialists: collaboration.specialists,
      checkpoint: checkpoint?.item || null,
      result: resultEvidence,
      background: {
        running: agentResponseRunning || backgroundTrainingRunning || backendRunning || cancelling,
        agent_response_running: agentResponseRunning,
        training_running: backgroundTrainingRunning,
        cancelling,
        action_ids: background.action_ids,
        run_ids: background.run_ids,
        training_run_ids: background.training_run_ids,
        coordinator_reply_complete: Boolean(resultEvidence.final),
      },
      observation: {
        degraded: projectionDegraded,
        projection_health: safeConversation.projection_health || null,
        projection_errors: asArray(safeConversation.projection_errors),
        turn_failure: turnFailure,
        blocker: turnBlocker,
        task_failure: observedTaskFailure,
        task_blocker: observedTaskBlocker,
      },
      workspace: workspaceFor({
        task,
        phase,
        currentTurn,
        checkpoint,
        currentActions,
        activeActions: background.active_actions,
        specialists: collaboration.specialists,
        resultEvidence,
        reasonCode,
      }),
    };
  }

  return {
    PHASES,
    canShowTurnStop,
    createAiTurnFrame,
    conversationTurnTarget,
    groupConversationTurns,
    selectCurrentTurn,
    supersededFailureSourceIds,
    activeFailureSourceIds,
    canonicalRiskLifecycleAvailable,
    turnHasActiveFailure,
    deriveInteractionProjection,
    deriveEvaluationOutcome,
    reconcileTeamActivityEvents,
  };
});
