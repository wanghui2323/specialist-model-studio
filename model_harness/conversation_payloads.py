from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping, Sequence


CONVERSATION_EVENT_PAYLOAD_MODE = "compact-v1"
CONVERSATION_OBJECT_SCHEMA_VERSION = "1.0"
INTERACTION_PROJECTION_SCHEMA_VERSION = "1.0"
CONVERSATION_RESULT_COMPACT_THRESHOLD_BYTES = 4 * 1024
CONVERSATION_RESULT_PREVIEW_MAX_CHARS = 800

_RESULT_EVENT_TYPES = frozenset(
    {"tool_result", "specialist_output", "delegation"}
)


def engineering_public_projection(value: Any) -> Any:
    """Preserve engineering data keys and virtual mounts, never host controls.

    Execution schemas, authored file maps and open business/config fields are
    data namespaces: a key named ``root`` is not itself a host path. No marker
    replacement is used, so source literals and code digests stay stable.
    """
    import re
    from pathlib import Path
    from .agent_bridge import (
        _AGENT_PUBLIC_REDACTED, _AGENT_PUBLIC_SENSITIVE_KEYS,
        _AGENT_PUBLIC_EMBEDDED_WINDOWS_PATH, _AGENT_PUBLIC_EMBEDDED_FILE_URI,
        _AGENT_PUBLIC_EMBEDDED_KNOWN_ROOT, _AGENT_PUBLIC_EMBEDDED_HOST_ROOT,
        _AGENT_PUBLIC_EMBEDDED_POSIX_PATH, _AGENT_PUBLIC_URL_PREFIX,
        _agent_local_absolute_path, _agent_public_route,
    )

    def virtual_prefix(text: str) -> bool:
        return bool(re.match(r"^/workspace/(?:source|input|output)(?=/|$)", text.strip()))

    def virtual_path(text: str) -> bool:
        return virtual_prefix(text) and "\\" not in text and not any(
            part in {".", ".."} for part in text.split("/")
        ) and not any(ord(char) < 32 for char in text)

    def safe_text(text: str) -> str:
        if _agent_local_absolute_path(text) and not virtual_path(text):
            return _AGENT_PUBLIC_REDACTED
        selected = _AGENT_PUBLIC_EMBEDDED_WINDOWS_PATH.sub(_AGENT_PUBLIC_REDACTED, text)
        selected = _AGENT_PUBLIC_EMBEDDED_FILE_URI.sub(_AGENT_PUBLIC_REDACTED, selected)
        selected = _AGENT_PUBLIC_EMBEDDED_KNOWN_ROOT.sub(_AGENT_PUBLIC_REDACTED, selected)
        selected = _AGENT_PUBLIC_EMBEDDED_HOST_ROOT.sub(
            lambda match: match.group(0) if _AGENT_PUBLIC_URL_PREFIX.search(selected[:match.start()]) else _AGENT_PUBLIC_REDACTED,
            selected,
        )
        return _AGENT_PUBLIC_EMBEDDED_POSIX_PATH.sub(
            lambda match: match.group(0) if _agent_public_route(match.group(0)) or virtual_path(match.group(0)) else _AGENT_PUBLIC_REDACTED,
            selected,
        )

    def project(item: Any, data_namespace: bool = False, path: tuple = ()) -> Any:
        if isinstance(item, dict):
            output = {}
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized = key.strip().lower().replace("-", "_")
                sensitive_key = normalized in _AGENT_PUBLIC_SENSITIVE_KEYS or normalized.endswith("_root")
                path_key = normalized == "path" or normalized.endswith("_path")
                host_value = isinstance(child, Path) or isinstance(child, str) and _agent_local_absolute_path(child) and not virtual_path(child)
                protocol_directory = (path == ("execution_workspace", "protocol")
                                      and key == "working_directory"
                                      and isinstance(child, str) and virtual_path(child))
                if sensitive_key and not protocol_directory and (not data_namespace or host_value) or path_key and host_value:
                    continue
                output[key] = project(child, data_namespace or key in {"execution_spec", "execution_spec_schema"}, (*path, key))
            return output
        if isinstance(item, (list, tuple)):
            return [project(child, data_namespace, (*path, index)) for index, child in enumerate(item)]
        if isinstance(item, Path):
            return _AGENT_PUBLIC_REDACTED
        return safe_text(item) if isinstance(item, str) else item

    result = project(value)

    def retain_frozen_source(record: Any, output: Any) -> None:
        if not isinstance(record, dict) or not isinstance(output, dict):
            return
        spec = record.get("execution_spec")
        if (record.get("object_type") != "ExecutionProposal"
                or not isinstance(record.get("task_id"), str) or not record["task_id"]
                or not re.fullmatch(r"execution-[0-9a-f]{24}", str(record.get("proposal_id", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("proposal_sha256", "")))
                or type(record.get("base_spec_revision")) is not int or record["base_spec_revision"] < 1
                or not isinstance(spec, dict)):
            return
        try:
            from .isolated_execution import ExecutionBundle
            bundle = ExecutionBundle.from_dict(spec.get("bundle"))
            if bundle.digest != spec.get("bundle_sha256"):
                return
        except (TypeError, ValueError):
            return
        # Only the exact source field of a frozen proposal is content. Path
        # literals here do not grant access; metadata/logs remain redacted.
        output["execution_spec"]["bundle"]["files"] = deepcopy(spec["bundle"]["files"])
        output["execution_spec"]["bundle"]["stages"] = deepcopy(spec["bundle"]["stages"])

    if isinstance(value, dict) and isinstance(result, dict):
        retain_frozen_source(value.get("proposal"), result.get("proposal"))
        originals, outputs = value.get("proposals"), result.get("proposals")
        if isinstance(originals, list) and isinstance(outputs, list):
            for original, output in zip(originals, outputs):
                retain_frozen_source(original, output)
    return result


class ConversationPayloadCompactionError(ValueError):
    """Raised when an oversized result cannot retain a retrievable identity."""


def _task_read_promotion_recoveries(
    *, task_id: str, actions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]], training_task_exists: bool,
) -> dict[str, Mapping[str, Any]]:
    """Resolve only observed missing-owner reads after verified promotion.

    A tool name or later coordinator claim is insufficient. Both native pairs,
    exact arguments, the HTTP error envelope, the successful task result, and
    current canonical owner existence must agree. The original action survives.
    """
    if not training_task_exists:
        return {}
    by_id: dict[str, Mapping[str, Any]] = {}
    ambiguous: set[str] = set()
    for event in events:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            continue
        if event_id in by_id:
            ambiguous.add(event_id)
        by_id[event_id] = event

    def pair(action: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
        if (action.get("task_id") != task_id or action.get("truth_type") != "observed_result"
                or action.get("tool_class") != "domain"):
            return None
        call_id, result_id = action.get("call_event_id"), action.get("result_event_id")
        if (not isinstance(call_id, str) or not isinstance(result_id, str)
                or call_id == result_id or call_id in ambiguous or result_id in ambiguous):
            return None
        call, result = by_id.get(call_id), by_id.get(result_id)
        if call is None or result is None:
            return None
        for event, kind in ((call, "tool_call"), (result, "tool_result")):
            if event.get("event_type") != kind or event.get("source") != "dsh":
                return None
            if event.get("root_session_id") != action.get("session_id"):
                return None
            for key in ("task_id", "agent_run_id", "session_id", "turn_id", "call_id"):
                if not isinstance(action.get(key), str) or not action[key] or event.get(key) != action[key]:
                    return None
            payload = event.get("payload")
            if (not isinstance(payload, Mapping)
                    or payload.get("tool_name") != action.get("tool_name")
                    or payload.get("call_id") != action.get("call_id")):
                return None
            for sequence_key in ("seq", "source_seq"):
                if isinstance(event.get(sequence_key), bool) or not isinstance(event.get(sequence_key), int):
                    return None
        if call["seq"] >= result["seq"] or call["source_seq"] >= result["source_seq"]:
            return None
        return call, result

    def object_value(value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                return None
            return parsed if isinstance(parsed, Mapping) else None
        if (isinstance(value, list) and len(value) == 1 and isinstance(value[0], Mapping)
                and value[0].get("type") == "text"):
            return object_value(value[0].get("text"))
        return None

    missing_reads: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    recovered: dict[str, Mapping[str, Any]] = {}
    for action in actions:
        tool = action.get("tool_name")
        if tool not in {"model_harness_get_task", "model_harness_promote_conversation"}:
            continue
        observed = pair(action)
        if observed is None:
            continue
        call, result = observed
        arguments = object_value(call.get("payload", {}).get("arguments")) or {}
        payload = result.get("payload", {})
        if tool == "model_harness_get_task":
            raw = payload.get("result")
            # This is the client/DSH HTTP-error envelope, not free-form model
            # text or a translated substring such as "task does not exist".
            not_found = (isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], Mapping)
                         and raw[0].get("type") == "text" and isinstance(raw[0].get("text"), str)
                         and raw[0]["text"].startswith("Error: Specialist Model Studio 404: "))
            if (action.get("status") == "failed" and payload.get("is_error") is True
                    and arguments.get("task_id") == task_id and not_found):
                missing_reads.append((action, result))
            continue
        promoted = object_value(payload.get("result")) or {}
        task = promoted.get("task")
        conversation = promoted.get("conversation")
        if (action.get("status") != "completed" or action.get("error")
                or payload.get("is_error") is not False or arguments.get("conversation_id") != task_id
                or not isinstance(task, Mapping) or task.get("task_id") != task_id
                or task.get("record_type") != "training_task"
                or not isinstance(conversation, Mapping) or conversation.get("conversation_id") != task_id
                or conversation.get("task_id") != task_id or conversation.get("status") != "bound"):
            continue
        for failed, failure_result in missing_reads:
            if (failed.get("session_id") == action.get("session_id")
                    and failure_result["seq"] < call["seq"]
                    and failure_result["source_seq"] < call["source_seq"]):
                recovered.setdefault(str(failed["action_id"]), action)
    return recovered


def project_conversation_objects(
    *,
    task_id: str,
    agent_runs: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    background_actions: Sequence[Mapping[str, Any]],
    pending: Sequence[Mapping[str, Any]],
    agent_response_running: bool,
    observation_degraded: bool = False,
    cancellation_pending: bool | None = None,
    can_cancel: bool | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    training_task_exists: bool = False,
) -> dict[str, Any]:
    """Build the additive, typed read model used by conversation-native UIs.

    The legacy ``runs`` and ``pending`` collections remain available for old
    clients.  This projection prevents those collections from being mistaken
    for TrainingRuns or ordinary chat messages.  Every projected object keeps
    a durable task-owned identity; no object is synthesized from coordinator
    prose.
    """

    agent_turns: list[dict[str, Any]] = []
    agent_turn_id_by_run_id: dict[str, str] = {}
    for index, raw_run in enumerate(agent_runs):
        run = dict(raw_run)
        turn_id = run.get("agent_turn_id") or run.get("run_id")
        if not isinstance(turn_id, str) or not turn_id:
            continue
        run_id = run.get("run_id")
        if isinstance(run_id, str) and run_id:
            agent_turn_id_by_run_id[run_id] = turn_id
        request = run.get("composer_request")
        request = dict(request) if isinstance(request, Mapping) else {}
        agent_turns.append(
            {
                "object_type": "AgentTurn",
                "agent_turn_id": turn_id,
                "task_id": task_id,
                "agent_run_id": run.get("run_id"),
                "request_id": request.get("request_id"),
                "composer_mode": request.get("mode", "legacy_queue"),
                "actor": request.get("actor"),
                "status": run.get("status"),
                "queued_at_utc": run.get("queued_at_utc"),
                "updated_at_utc": run.get("updated_at_utc"),
                "response_running": bool(
                    agent_response_running and index == len(agent_runs) - 1
                ),
                "cancel": deepcopy(run.get("cancel_request")),
                "discussion_handoff": deepcopy(run.get("discussion_handoff")),
                "error": run.get("error"),
            }
        )

    projected_actions: list[dict[str, Any]] = []
    for raw_action in actions:
        action = deepcopy(dict(raw_action))
        action_id = action.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            continue
        action_run_id = action.get("agent_run_id")
        canonical_agent_turn_id = (
            agent_turn_id_by_run_id.get(action_run_id)
            if isinstance(action_run_id, str)
            else None
        )
        if canonical_agent_turn_id is not None:
            action["agent_turn_id"] = canonical_agent_turn_id
        action["object_type"] = "Action"
        projected_actions.append(action)

    training_runs: list[dict[str, Any]] = []
    for raw_action in background_actions:
        action = dict(raw_action)
        if action.get("action_type") != "training_run":
            continue
        run_id = action.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        training_runs.append(
            {
                "object_type": "TrainingRun",
                "training_run_id": run_id,
                "task_id": task_id,
                "action_id": action.get("action_id"),
                "status": action.get("status"),
                "domain_status": action.get("domain_status"),
                "running": action.get("running") is True,
                "worker_running": action.get("worker_running") is True,
                "cancel_requested": action.get("cancel_requested") is True,
                "cancel": deepcopy(action.get("cancel")),
                "last_event": deepcopy(action.get("last_event")),
                "updated_at_utc": action.get("updated_at_utc"),
            }
        )

    human_checkpoints: list[dict[str, Any]] = []
    latest_agent_run_id = (
        agent_turns[-1].get("agent_run_id") if agent_turns else None
    )
    for raw_item in pending:
        item = dict(raw_item)
        rpc_id = item.get("rpc_id")
        kind = item.get("kind")
        if (
            not isinstance(rpc_id, str)
            or not rpc_id
            or kind not in {"approval", "question"}
        ):
            continue
        checkpoint: dict[str, Any] = {
            "object_type": "HumanCheckpoint",
            "checkpoint_id": f"human-checkpoint:{rpc_id}",
            "task_id": task_id,
            "rpc_id": rpc_id,
            "checkpoint_kind": kind,
            "session_id": item.get("session_id"),
            "status": "waiting_for_human",
            "received_at": item.get("received_at"),
        }
        checkpoint_agent_run_id = item.get("agent_run_id") or latest_agent_run_id
        checkpoint_agent_turn_id = (
            agent_turn_id_by_run_id.get(checkpoint_agent_run_id)
            if isinstance(checkpoint_agent_run_id, str)
            else None
        )
        if isinstance(checkpoint_agent_run_id, str) and checkpoint_agent_run_id:
            checkpoint["agent_run_id"] = checkpoint_agent_run_id
        if checkpoint_agent_turn_id is not None:
            checkpoint["agent_turn_id"] = checkpoint_agent_turn_id
        # Only the explicit decision contract is projected.  Incidental DSH
        # transport/private context must not become user-facing state.
        if kind == "question" and isinstance(item.get("questions"), list):
            checkpoint["questions"] = deepcopy(item["questions"])
        if kind == "approval" and isinstance(item.get("approval_id"), str):
            checkpoint["approval_id"] = item["approval_id"]
        human_checkpoints.append(checkpoint)

    risks: list[dict[str, Any]] = []
    later_success_by_operation: dict[tuple[str, str], dict[str, Any]] = {}
    later_training_starts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    action_risks_reversed: list[dict[str, Any]] = []
    promotion_recoveries = _task_read_promotion_recoveries(
        task_id=task_id, actions=projected_actions, events=events,
        training_task_exists=training_task_exists,
    )

    def paired_result_sequence(action: Mapping[str, Any]) -> int | None:
        """Require an observed pair and its task-owned result order, not prose."""
        if (
            action.get("truth_type") != "observed_result"
            or action.get("task_id") != task_id
            or not all(isinstance(action.get(name), str) and action[name] for name in (
                "agent_run_id", "session_id", "turn_id", "call_id",
                "call_event_id", "result_event_id",
            ))
            or action["call_event_id"] == action["result_event_id"]
        ):
            return None
        ref = action.get("event_result_ref")
        if (
            not isinstance(ref, Mapping)
            or ref.get("type") != "conversation_event_result"
            or ref.get("task_id") != task_id
            or ref.get("id") != action.get("result_event_id")
        ):
            return None
        sequence = ref.get("event_seq")
        return sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None

    # ``projected_actions`` is in canonical observed-event order.  Scan it in
    # reverse so a failed invocation is superseded only by a *later* observed
    # success of the same structured tool operation.  Coordinator prose and
    # error text never participate in the decision.
    for action in reversed(projected_actions):
        tool_name = action.get("tool_name")
        tool_class = action.get("tool_class")
        operation_key = (
            (str(tool_class), tool_name)
            if isinstance(tool_name, str) and tool_name
            else None
        )
        if action.get("status") == "completed" and operation_key is not None:
            later_success_by_operation[operation_key] = action
            if (
                tool_name == "model_harness_start_task_run"
                and tool_class == "domain"
                and not action.get("error")
                and paired_result_sequence(action) is not None
            ):
                scope = (task_id, str(action["agent_run_id"]))
                later_training_starts.setdefault(scope, []).append(action)
            continue
        if action.get("status") not in {"failed", "identity_error"}:
            continue
        # Identity errors are evidence-integrity failures.  A later successful
        # tool invocation cannot repair the malformed historical identity, so
        # only ordinary failed actions are eligible for supersession.
        resolved_by = (
            later_success_by_operation.get(operation_key)
            if action.get("status") == "failed" and operation_key is not None
            else None
        )
        resolution_kind = "superseded_by_later_success"
        if resolved_by is None and action.get("status") == "failed":
            resolved_by = promotion_recoveries.get(str(action["action_id"]))
            if resolved_by is not None:
                resolution_kind = "task_created_by_later_promotion"
        # A registered, authorized training start proves capability resolution
        # has been passed for this same task/AgentRun. It can retire an earlier
        # matching failure even when the unnecessary match tool is not retried.
        # This does not resolve training/delivery errors or confer completion.
        if (
            resolved_by is None and action.get("status") == "failed"
            and tool_name == "model_harness_match_capability" and tool_class == "domain"
        ):
            failure_sequence = paired_result_sequence(action)
            if failure_sequence is not None:
                scope = (task_id, str(action["agent_run_id"]))
                resolved_by = next((
                    candidate for candidate in reversed(later_training_starts.get(scope, []))
                    if paired_result_sequence(candidate) > failure_sequence
                ), None)
                if resolved_by is not None:
                    resolution_kind = "capability_resolved_by_training_start"
        risk = {
            "risk_id": f"risk:{action['action_id']}",
            "source_type": "Action",
            "source_id": action["action_id"],
            "status": action.get("status"),
            "error": deepcopy(action.get("error")),
            "active": resolved_by is None,
            "lifecycle_status": (
                "active" if resolved_by is None else "superseded"
            ),
            "resolution": (
                None
                if resolved_by is None
                else {
                    "kind": resolution_kind,
                    "source_type": "Action",
                    "source_id": resolved_by["action_id"],
                }
            ),
        }
        action_risks_reversed.append(risk)
    risks.extend(reversed(action_risks_reversed))
    for turn in agent_turns:
        if turn.get("status") not in {"failed", "cancelled", "interrupted"}:
            continue
        handoff = turn.get("discussion_handoff") or {}
        suspended = turn.get("status") == "cancelled" and handoff.get("outcome") == "superseded_for_discussion"
        risks.append(
            {
                "risk_id": f"risk:{turn['agent_turn_id']}",
                "source_type": "AgentTurn",
                "source_id": turn["agent_turn_id"],
                "status": turn.get("status"),
                "error": deepcopy(turn.get("error")),
                "active": not suspended,
                "lifecycle_status": "superseded" if suspended else "active",
                "resolution": {"kind": "checkpoint_discussion", "rpc_id": handoff["rpc_id"]} if suspended else None,
            }
        )

    latest_turn = agent_turns[-1] if agent_turns else None
    latest_run_id = (
        latest_turn.get("agent_run_id")
        if isinstance(latest_turn, Mapping)
        else None
    )
    latest_run_actions = [
        action
        for action in projected_actions
        if latest_run_id and action.get("agent_run_id") == latest_run_id
    ]
    latest_run_action = latest_run_actions[-1] if latest_run_actions else None
    active_action = next(
        (
            action
            for action in reversed(latest_run_actions)
            if action.get("status") == "running"
        ),
        None,
    )
    last_completed_action = next(
        (
            action
            for action in reversed(latest_run_actions)
            if action.get("status") == "completed"
        ),
        None,
    )

    cancelling_training = next(
        (
            item
            for item in training_runs
            if item.get("cancel_requested") is True and item.get("running") is True
        ),
        None,
    )
    cancelling_turn = next(
        (
            item
            for item in reversed(agent_turns)
            if item.get("status") == "cancel_requested"
        ),
        None,
    )
    cancelling_background = next(
        (
            dict(item)
            for item in background_actions
            if item.get("cancel_requested") is True
            and item.get("running") is True
        ),
        None,
    )
    running_training = next(
        (item for item in training_runs if item.get("running") is True), None
    )
    running_background = next(
        (
            dict(item)
            for item in background_actions
            if item.get("running") is True
        ),
        None,
    )
    background_running = running_background is not None
    background_stopping = cancelling_background is not None
    selected_cancellation_pending = (
        bool(cancellation_pending)
        if cancellation_pending is not None
        else cancelling_training is not None
        or cancelling_turn is not None
        or background_stopping
    )
    active_risks = [risk for risk in risks if risk.get("active") is True]
    current_source_ids = {action["action_id"] for action in latest_run_actions}
    if isinstance(latest_turn, Mapping):
        current_source_ids.add(latest_turn["agent_turn_id"])
    # Historical failures remain visible and unresolved. They do not become
    # the foreground state of an unrelated new turn. Unknown lineage and
    # identity errors still fail closed across the conversation.
    scoped_source_ids = {action["action_id"] for action in projected_actions
        if action.get("agent_run_id")}
    scoped_source_ids.update(turn["agent_turn_id"] for turn in agent_turns)
    current_risks = [risk for risk in active_risks
        if risk["source_id"] in current_source_ids
        or risk["source_id"] not in scoped_source_ids
        or risk.get("status") == "identity_error"]
    terminal_outcome = None
    if isinstance(latest_turn, Mapping):
        terminal_outcome = {
            "completed": "completed",
            "failed": "failed",
            "cancelled": "stopped",
            "interrupted": "stopped",
        }.get(str(latest_turn.get("status") or ""))

    phase = "idle"
    subject: dict[str, Any] | None = None
    if observation_degraded:
        phase = "observation_degraded"
    elif selected_cancellation_pending:
        phase = "stopping"
        if cancelling_training is not None:
            subject = {
                "object_type": "TrainingRun",
                "object_id": cancelling_training["training_run_id"],
                "training_run_id": cancelling_training["training_run_id"],
            }
        elif cancelling_turn is not None:
            subject = {
                "object_type": "AgentTurn",
                "object_id": cancelling_turn["agent_turn_id"],
                "agent_turn_id": cancelling_turn["agent_turn_id"],
                "agent_run_id": cancelling_turn.get("agent_run_id"),
            }
        elif cancelling_background is not None:
            subject = {
                "object_type": "BackgroundAction",
                "object_id": cancelling_background.get("action_id"),
                "action_id": cancelling_background.get("action_id"),
            }
    elif human_checkpoints:
        checkpoint = human_checkpoints[0]
        phase = (
            "waiting_approval"
            if checkpoint.get("checkpoint_kind") == "approval"
            else "waiting_question"
        )
        subject = {
            "object_type": "HumanCheckpoint",
            "object_id": checkpoint["checkpoint_id"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_kind": checkpoint.get("checkpoint_kind"),
            "rpc_id": checkpoint.get("rpc_id"),
            "agent_turn_id": checkpoint.get("agent_turn_id"),
            "agent_run_id": checkpoint.get("agent_run_id"),
        }
    elif latest_turn is not None and agent_response_running:
        phase = "agent_working"
        subject = {
            "object_type": "AgentTurn",
            "object_id": latest_turn["agent_turn_id"],
            "agent_turn_id": latest_turn["agent_turn_id"],
            "agent_run_id": latest_turn.get("agent_run_id"),
        }
    elif background_running:
        phase = "background_working"
        if running_training is not None:
            subject = {
                "object_type": "TrainingRun",
                "object_id": running_training["training_run_id"],
                "training_run_id": running_training["training_run_id"],
            }
        else:
            subject = {
                "object_type": "BackgroundAction",
                "object_id": running_background.get("action_id"),
                "action_id": running_background.get("action_id"),
            }
    elif terminal_outcome is not None:
        phase = terminal_outcome
        subject = {
            "object_type": "AgentTurn",
            "object_id": latest_turn["agent_turn_id"],
            "agent_turn_id": latest_turn["agent_turn_id"],
            "agent_run_id": latest_turn.get("agent_run_id"),
        }
    elif current_risks:
        phase = "blocked"
        risk = current_risks[-1]
        subject = {
            "object_type": "Risk",
            "object_id": risk["risk_id"],
            "risk_id": risk["risk_id"],
            "source_type": risk.get("source_type"),
            "source_id": risk.get("source_id"),
        }

    requested_can_cancel = (
        bool(can_cancel)
        if can_cancel is not None
        else agent_response_running or background_running
    )
    interaction_projection = {
        "schema_version": INTERACTION_PROJECTION_SCHEMA_VERSION,
        "phase": phase,
        "subject": subject,
        "turn_identity": {
            "agent_turn_id": (
                latest_turn.get("agent_turn_id")
                if isinstance(latest_turn, Mapping)
                else None
            ),
            "agent_run_id": latest_run_id,
            "turn_id": (
                latest_run_action.get("turn_id")
                if isinstance(latest_run_action, Mapping)
                else None
            ),
        },
        "active_action_id": (
            active_action.get("action_id")
            if isinstance(active_action, Mapping)
            else None
        ),
        "last_completed_action_id": (
            last_completed_action.get("action_id")
            if isinstance(last_completed_action, Mapping)
            else None
        ),
        "can_cancel": bool(
            requested_can_cancel
            and phase
            not in {
                "observation_degraded",
                "stopping",
                "completed",
                "failed",
                "stopped",
                "blocked",
                "idle",
            }
        ),
        "terminal_outcome": (
            terminal_outcome
            if phase in {"completed", "failed", "stopped"}
            else None
        ),
        "background": {
            "phase": (
                "stopping"
                if background_stopping
                else "running"
                if background_running
                else "idle"
            ),
            "running": background_running,
            "stopping": background_stopping,
            "action_ids": [
                str(item["action_id"])
                for item in background_actions
                if isinstance(item.get("action_id"), str)
                and item.get("action_id")
            ],
            "training_run_ids": [
                str(item["training_run_id"])
                for item in training_runs
                if isinstance(item.get("training_run_id"), str)
                and item.get("training_run_id")
            ],
        },
    }

    primary_attention: dict[str, Any] | None = None
    if phase == "stopping" and subject is not None:
        primary_attention = {
            "object_type": subject["object_type"],
            "object_id": subject["object_id"],
            "reason": "cancellation_in_progress",
        }
    elif phase in {"waiting_question", "waiting_approval"} and subject is not None:
        primary_attention = {
            "object_type": subject["object_type"],
            "object_id": subject["object_id"],
            "reason": "waiting_for_human",
        }
    elif phase == "agent_working" and subject is not None:
        primary_attention = {
            "object_type": subject["object_type"],
            "object_id": subject["object_id"],
            "reason": "agent_response",
        }
    elif phase == "background_working" and subject is not None:
        primary_attention = {
            "object_type": subject["object_type"],
            "object_id": subject["object_id"],
            "reason": "background_execution",
        }
    elif phase == "blocked" and subject is not None:
        primary_attention = {
            "object_type": subject["object_type"],
            "object_id": subject["object_id"],
            "reason": "recoverable_history",
        }

    return {
        "object_schema_version": CONVERSATION_OBJECT_SCHEMA_VERSION,
        "agent_turns": agent_turns,
        "actions": projected_actions,
        "training_runs": training_runs,
        "human_checkpoints": human_checkpoints,
        "risks": risks,
        "primary_attention": primary_attention,
        "interaction_projection": interaction_projection,
    }


def _canonical_result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _result_size_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _result_preview(value: Any) -> str:
    selected = _canonical_result_text(value)
    if len(selected) <= CONVERSATION_RESULT_PREVIEW_MAX_CHARS:
        return selected
    return f"{selected[: CONVERSATION_RESULT_PREVIEW_MAX_CHARS - 1]}…"


def _event_result_ref(event: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    event_type = str(event.get("event_type") or event.get("type") or "")
    event_id = event.get("event_id")
    task_id = event.get("task_id")
    projector_revision = event.get("projector_revision")
    event_seq = event.get("seq")
    source_key = event.get("source_key")
    if (
        event.get("source") != "dsh"
        or event_type not in _RESULT_EVENT_TYPES
        or not isinstance(payload, Mapping)
        or "result" not in payload
        or not isinstance(event_id, str)
        or not event_id
        or not isinstance(task_id, str)
        or not task_id
        or not isinstance(projector_revision, str)
        or not projector_revision
        or isinstance(event_seq, bool)
        or not isinstance(event_seq, int)
        or event_seq < 1
        or not isinstance(source_key, str)
        or not source_key
    ):
        return None
    return {
        "type": "conversation_event_result",
        "id": event_id,
        "task_id": task_id,
        "projector_revision": projector_revision,
        "event_seq": event_seq,
        "source_key": source_key,
    }


def _compact_event(event: Mapping[str, Any]) -> dict[str, Any]:
    selected = deepcopy(dict(event))
    payload = selected.get("payload")
    if not isinstance(payload, dict) or "result" not in payload:
        return selected
    result = payload["result"]
    size_bytes = _result_size_bytes(result)
    if size_bytes <= CONVERSATION_RESULT_COMPACT_THRESHOLD_BYTES:
        return selected
    result_ref = _event_result_ref(selected)
    if result_ref is None:
        raise ConversationPayloadCompactionError(
            "oversized conversation result has no retrievable event identity"
        )
    del payload["result"]
    payload["result_preview"] = _result_preview(result)
    payload["result_truncated"] = True
    payload["result_size_bytes"] = size_bytes
    payload["event_result_ref"] = result_ref
    return selected


def compact_conversation_response(
    conversation: Mapping[str, Any],
) -> dict[str, Any]:
    """Compact result payloads only at the response boundary.

    The caller must invoke this after synthesis and action classification. The
    append-only event store remains authoritative and is intentionally not
    mutated by this deep-copy transformation.
    """

    selected = deepcopy(dict(conversation))
    selected["event_payload_mode"] = CONVERSATION_EVENT_PAYLOAD_MODE
    for collection_name in ("events", "items"):
        values = selected.get(collection_name)
        if not isinstance(values, list):
            continue
        selected[collection_name] = [
            _compact_event(value) if isinstance(value, Mapping) else deepcopy(value)
            for value in values
        ]
    return selected
