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


class ConversationPayloadCompactionError(ValueError):
    """Raised when an oversized result cannot retain a retrievable identity."""


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
    action_risks_reversed: list[dict[str, Any]] = []
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
                    "kind": "superseded_by_later_success",
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
