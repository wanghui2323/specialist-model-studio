from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping, Sequence

from .object_refs import (
    CanonicalObjectRef,
    ObjectRefValidationError,
    normalize_object_refs,
)


ACTION_SCHEMA_VERSION = "1.0"

ToolClass = Literal["domain", "control", "delegation", "unknown"]
ActionStatus = Literal["running", "completed", "failed", "identity_error"]
TruthType = Literal["observed_call", "observed_result", "identity_error"]


ActionObjectRef = CanonicalObjectRef


@dataclass(frozen=True)
class EventResultRef:
    type: Literal["conversation_event_result"]
    id: str
    task_id: str
    projector_revision: str
    event_seq: int
    source_key: str


@dataclass(frozen=True)
class ActionError:
    code: str
    message: str


@dataclass(frozen=True)
class ConversationAction:
    schema_version: str
    action_id: str
    task_id: str | None
    agent_run_id: str | None
    session_id: str | None
    turn_id: str | None
    call_id: str | None
    tool_name: str | None
    tool_class: ToolClass
    actor_role: str | None
    started_at_utc: str | None
    ended_at_utc: str | None
    duration_ms: int | None
    status: ActionStatus
    delegation_id: str | None
    parent_delegation_id: str | None
    object_refs: tuple[ActionObjectRef, ...]
    event_result_ref: EventResultRef | None
    error: ActionError | None
    truth_type: TruthType
    call_event_id: str | None
    result_event_id: str | None


_DELEGATION_TOOLS = frozenset(
    {
        "spawn_agent",
        "fork_agent",
        "delegate_task",
        "delegate_to_agent",
        "send_message",
        "send_message_to_agent",
        "research_source",
        "data_experiment",
        "resource_safety",
        "build_training",
        "evaluation_delivery",
    }
)

_CONTROL_TOOLS = frozenset(
    {
        "ask_user_question",
        "request_user_input",
        "list_agents",
        "wait_agent",
        "interrupt_agent",
        "get_agent_status",
    }
)


@dataclass(frozen=True)
class _Identity:
    task_id: str
    agent_run_id: str
    session_id: str
    turn_id: str
    call_id: str

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (
            self.task_id,
            self.agent_run_id,
            self.session_id,
            self.turn_id,
            self.call_id,
        )


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or "")


def _is_call(event: Mapping[str, Any]) -> bool:
    payload = _payload(event)
    return (
        _event_type(event) in {"tool_call", "delegation"}
        and "arguments" in payload
        and "result" not in payload
        and "is_error" not in payload
    )


def _is_result(event: Mapping[str, Any]) -> bool:
    return _event_type(event) in {
        "tool_result",
        "specialist_output",
        "delegation",
    } and ("result" in _payload(event) or "is_error" in _payload(event))


def _string(event: Mapping[str, Any], key: str) -> str | None:
    value = event.get(key)
    return value if isinstance(value, str) and value else None


def _call_id(event: Mapping[str, Any]) -> str | None:
    for value in (event.get("call_id"), _payload(event).get("call_id")):
        if isinstance(value, str) and value:
            return value
    return None


def _tool_name(event: Mapping[str, Any]) -> str | None:
    for value in (event.get("tool_name"), _payload(event).get("tool_name")):
        if isinstance(value, str) and value:
            return value
    return None


def _result_error(event: Mapping[str, Any]) -> ActionError:
    """Preserve an explicit human rejection without presenting it as a system fault."""

    def text_fragments(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, Mapping):
            fragments: list[str] = []
            for key in ("text", "message", "error"):
                if key in value:
                    fragments.extend(text_fragments(value[key]))
            return fragments
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            fragments: list[str] = []
            for item in value:
                fragments.extend(text_fragments(item))
            return fragments
        return []

    observed = " ".join(text_fragments(_payload(event).get("result"))).lower()
    if "the user rejected tool" in observed:
        return ActionError(
            code="user_rejected",
            message="你已拒绝本次授权，操作未执行。",
        )
    return ActionError(
        code="tool_result_error",
        message="工具返回了失败结果；请展开技术详情查看原因。",
    )


def _identity(event: Mapping[str, Any]) -> _Identity | None:
    task_id = _string(event, "task_id")
    agent_run_id = _string(event, "agent_run_id")
    session_id = _string(event, "session_id")
    turn_id = _string(event, "turn_id")
    call_id = _call_id(event)
    if not all((task_id, agent_run_id, session_id, turn_id, call_id)):
        return None
    return _Identity(
        task_id=task_id,
        agent_run_id=agent_run_id,
        session_id=session_id,
        turn_id=turn_id,
        call_id=call_id,
    )


def _stable_id(identity: _Identity) -> str:
    encoded = json.dumps(
        identity.as_tuple(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"action-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _invalid_event_id(event: Mapping[str, Any]) -> str:
    identity = {
        "task_id": event.get("task_id"),
        "agent_run_id": event.get("agent_run_id"),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "call_id": _call_id(event),
        "event_id": event.get("event_id"),
        "source_key": event.get("source_key"),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"action-invalid-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _tool_class(
    tool_name: str | None,
    events: Sequence[Mapping[str, Any]],
) -> ToolClass:
    structured_delegation = any(
        event.get("category") == "delegation"
        or _event_type(event) == "delegation"
        for event in events
    )
    lowered = tool_name.lower() if tool_name else ""
    if structured_delegation or lowered in _DELEGATION_TOOLS:
        return "delegation"
    if lowered.startswith("model_harness_"):
        return "domain"
    if lowered in _CONTROL_TOOLS:
        return "control"
    return "unknown"


def _one_structured_value(
    events: Sequence[Mapping[str, Any]],
    key: str,
) -> tuple[str | None, bool]:
    values = {
        value
        for event in events
        for value in [_string(event, key)]
        if value is not None
    }
    if len(values) > 1:
        return None, False
    return (next(iter(values)) if values else None), True


def _timestamp(event: Mapping[str, Any] | None) -> str | None:
    return _string(event, "timestamp_utc") if event is not None else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    started = _parse_timestamp(started_at)
    ended = _parse_timestamp(ended_at)
    if started is None or ended is None:
        return None
    try:
        duration = (ended - started).total_seconds()
    except TypeError:
        return None
    if duration < 0:
        return None
    return int(round(duration * 1000))


def _canonical_object_refs(
    result: Mapping[str, Any],
    *,
    task_id: str,
) -> tuple[tuple[ActionObjectRef, ...], ActionError | None]:
    value = _payload(result).get("object_refs")
    if value is None:
        return (), None
    try:
        return normalize_object_refs(value, expected_task_id=task_id), None
    except ObjectRefValidationError as exc:
        message = str(exc)
        code = (
            "cross_task_object_ref"
            if "another task" in message
            else "unsupported_object_ref_type"
            if "unknown" in message or "not evidence-ready" in message
            else "invalid_object_ref"
        )
        return (), ActionError(code=code, message=message)


def _event_result_ref(result: Mapping[str, Any]) -> EventResultRef | None:
    event_id = _string(result, "event_id")
    task_id = _string(result, "task_id")
    projector_revision = _string(result, "projector_revision")
    event_seq = result.get("seq")
    source_key = _string(result, "source_key")
    if (
        event_id is None
        or task_id is None
        or projector_revision is None
        or isinstance(event_seq, bool)
        or not isinstance(event_seq, int)
        or event_seq < 1
        or source_key is None
    ):
        return None
    return EventResultRef(
        type="conversation_event_result",
        id=event_id,
        task_id=task_id,
        projector_revision=projector_revision,
        event_seq=event_seq,
        source_key=source_key,
    )


def _identity_error_action(
    *,
    identity: _Identity,
    calls: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    code: str,
    message: str,
) -> ConversationAction:
    events = (*calls, *results)
    tool_names = {name for event in events for name in [_tool_name(event)] if name}
    actor_roles = {
        role for event in events for role in [_string(event, "actor_role")] if role
    }
    delegation_id, _ = _one_structured_value(events, "delegation_id")
    parent_delegation_id, _ = _one_structured_value(
        events,
        "parent_delegation_id",
    )
    return ConversationAction(
        schema_version=ACTION_SCHEMA_VERSION,
        action_id=_stable_id(identity),
        task_id=identity.task_id,
        agent_run_id=identity.agent_run_id,
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        call_id=identity.call_id,
        tool_name=next(iter(tool_names)) if len(tool_names) == 1 else None,
        tool_class=_tool_class(
            next(iter(tool_names)) if len(tool_names) == 1 else None,
            events,
        ),
        actor_role=next(iter(actor_roles)) if len(actor_roles) == 1 else None,
        started_at_utc=_timestamp(calls[0]) if len(calls) == 1 else None,
        ended_at_utc=_timestamp(results[0]) if len(results) == 1 else None,
        duration_ms=None,
        status="identity_error",
        delegation_id=delegation_id,
        parent_delegation_id=parent_delegation_id,
        object_refs=(),
        event_result_ref=(
            _event_result_ref(results[0]) if len(results) == 1 else None
        ),
        error=ActionError(code=code, message=message),
        truth_type="identity_error",
        call_event_id=(
            _string(calls[0], "event_id") if len(calls) == 1 else None
        ),
        result_event_id=(
            _string(results[0], "event_id") if len(results) == 1 else None
        ),
    )


def _missing_identity_action(
    event: Mapping[str, Any],
    *,
    is_call: bool,
) -> ConversationAction:
    tool_name = _tool_name(event)
    return ConversationAction(
        schema_version=ACTION_SCHEMA_VERSION,
        action_id=_invalid_event_id(event),
        task_id=_string(event, "task_id"),
        agent_run_id=_string(event, "agent_run_id"),
        session_id=_string(event, "session_id"),
        turn_id=_string(event, "turn_id"),
        call_id=_call_id(event),
        tool_name=tool_name,
        tool_class=_tool_class(tool_name, (event,)),
        actor_role=_string(event, "actor_role"),
        started_at_utc=_timestamp(event) if is_call else None,
        ended_at_utc=_timestamp(event) if not is_call else None,
        duration_ms=None,
        status="identity_error",
        delegation_id=_string(event, "delegation_id"),
        parent_delegation_id=_string(event, "parent_delegation_id"),
        object_refs=(),
        event_result_ref=_event_result_ref(event) if not is_call else None,
        error=ActionError(
            code="missing_action_identity",
            message="Tool event is missing part of its strict action identity.",
        ),
        truth_type="identity_error",
        call_event_id=_string(event, "event_id") if is_call else None,
        result_event_id=_string(event, "event_id") if not is_call else None,
    )


def _paired_action(
    identity: _Identity,
    call: Mapping[str, Any],
    result: Mapping[str, Any],
) -> ConversationAction:
    events = (call, result)
    call_tool_name = _tool_name(call)
    result_tool_name = _tool_name(result)
    if result_tool_name and call_tool_name != result_tool_name:
        return _identity_error_action(
            identity=identity,
            calls=(call,),
            results=(result,),
            code="tool_name_mismatch",
            message="Call and result expose different structured tool names.",
        )
    delegation_id, delegation_valid = _one_structured_value(events, "delegation_id")
    parent_delegation_id, parent_valid = _one_structured_value(
        events,
        "parent_delegation_id",
    )
    if not delegation_valid or not parent_valid:
        return _identity_error_action(
            identity=identity,
            calls=(call,),
            results=(result,),
            code="delegation_identity_mismatch",
            message="Call and result expose conflicting delegation identity.",
        )
    object_refs, ref_error = _canonical_object_refs(
        result,
        task_id=identity.task_id,
    )
    if ref_error is not None:
        return _identity_error_action(
            identity=identity,
            calls=(call,),
            results=(result,),
            code=ref_error.code,
            message=ref_error.message,
        )
    event_ref = None if object_refs else _event_result_ref(result)
    if not object_refs and event_ref is None:
        return _identity_error_action(
            identity=identity,
            calls=(call,),
            results=(result,),
            code="result_event_identity_missing",
            message="Result has neither a persistent object ref nor event identity.",
        )
    started_at = _timestamp(call)
    ended_at = _timestamp(result)
    is_error = _payload(result).get("is_error") is True or result.get("status") in {
        "failed",
        "cancelled",
    }
    return ConversationAction(
        schema_version=ACTION_SCHEMA_VERSION,
        action_id=_stable_id(identity),
        task_id=identity.task_id,
        agent_run_id=identity.agent_run_id,
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        call_id=identity.call_id,
        tool_name=call_tool_name or result_tool_name,
        tool_class=_tool_class(call_tool_name or result_tool_name, events),
        actor_role=_string(call, "actor_role") or _string(result, "actor_role"),
        started_at_utc=started_at,
        ended_at_utc=ended_at,
        duration_ms=_duration_ms(started_at, ended_at),
        status="failed" if is_error else "completed",
        delegation_id=delegation_id,
        parent_delegation_id=parent_delegation_id,
        object_refs=object_refs,
        event_result_ref=event_ref,
        error=(
            _result_error(result)
            if is_error
            else None
        ),
        truth_type="observed_result",
        call_event_id=_string(call, "event_id"),
        result_event_id=_string(result, "event_id"),
    )


def _running_action(
    identity: _Identity,
    call: Mapping[str, Any],
) -> ConversationAction:
    tool_name = _tool_name(call)
    return ConversationAction(
        schema_version=ACTION_SCHEMA_VERSION,
        action_id=_stable_id(identity),
        task_id=identity.task_id,
        agent_run_id=identity.agent_run_id,
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        call_id=identity.call_id,
        tool_name=tool_name,
        tool_class=_tool_class(tool_name, (call,)),
        actor_role=_string(call, "actor_role"),
        started_at_utc=_timestamp(call),
        ended_at_utc=None,
        duration_ms=None,
        status="running",
        delegation_id=_string(call, "delegation_id"),
        parent_delegation_id=_string(call, "parent_delegation_id"),
        object_refs=(),
        event_result_ref=None,
        error=None,
        truth_type="observed_call",
        call_event_id=_string(call, "event_id"),
        result_event_id=None,
    )


def _action_sort_key(action: ConversationAction) -> tuple[str, str, str]:
    return (
        action.started_at_utc or action.ended_at_utc or "",
        action.call_id or "",
        action.action_id,
    )


def _event_sequence(event: Mapping[str, Any]) -> int | None:
    value = event.get("seq")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def classify_conversation_actions(
    *,
    task_id: str,
    projector_revision: str,
    events: Sequence[Mapping[str, Any]],
) -> tuple[ConversationAction, ...]:
    """Strictly pair current projector tool events without textual inference."""

    selected = [
        event
        for event in events
        if event.get("source") == "dsh"
        and event.get("projector_revision") == projector_revision
        and event.get("task_id") == task_id
        and (_is_call(event) or _is_result(event))
    ]
    groups: dict[
        _Identity,
        dict[str, list[Mapping[str, Any]]],
    ] = {}
    actions: list[ConversationAction] = []
    for event in selected:
        is_call = _is_call(event)
        identity = _identity(event)
        if identity is None:
            actions.append(_missing_identity_action(event, is_call=is_call))
            continue
        group = groups.setdefault(identity, {"calls": [], "results": []})
        group["calls" if is_call else "results"].append(event)

    for identity, group in groups.items():
        calls = group["calls"]
        results = group["results"]
        if len(calls) > 1:
            actions.append(
                _identity_error_action(
                    identity=identity,
                    calls=calls,
                    results=results,
                    code="duplicate_tool_call",
                    message="More than one call shares the strict action identity.",
                )
            )
        elif len(results) > 1:
            actions.append(
                _identity_error_action(
                    identity=identity,
                    calls=calls,
                    results=results,
                    code="duplicate_tool_result",
                    message="More than one result shares the strict action identity.",
                )
            )
        elif not calls:
            actions.append(
                _identity_error_action(
                    identity=identity,
                    calls=(),
                    results=results,
                    code="orphan_tool_result",
                    message="Tool result has no call with the same strict identity.",
                )
            )
        elif not results:
            actions.append(_running_action(identity, calls[0]))
        else:
            actions.append(_paired_action(identity, calls[0], results[0]))

    # Projected event ``seq`` is the canonical observation order across root
    # and child sessions.  DSH timestamps may be epoch integers (and older
    # records may omit them), so sorting only by timestamp/call id can put a
    # successful retry before the failure it actually recovered from.
    event_order_by_id: dict[str, tuple[int, int]] = {}
    for input_index, event in enumerate(selected):
        event_id = _string(event, "event_id")
        if event_id is None:
            continue
        event_seq = _event_sequence(event)
        event_order_by_id[event_id] = (
            event_seq if event_seq is not None else len(selected) + input_index,
            input_index,
        )

    def observed_order(action: ConversationAction) -> tuple[int, int, str, str, str]:
        positions = [
            event_order_by_id[event_id]
            for event_id in (action.call_event_id, action.result_event_id)
            if event_id in event_order_by_id
        ]
        if positions:
            first_seq, first_input_index = min(positions)
        else:
            first_seq, first_input_index = len(selected) * 2, len(selected)
        return (first_seq, first_input_index, *_action_sort_key(action))

    return tuple(sorted(actions, key=observed_order))


__all__ = [
    "ACTION_SCHEMA_VERSION",
    "ActionError",
    "ActionObjectRef",
    "ConversationAction",
    "EventResultRef",
    "classify_conversation_actions",
]
