"""Bind continuable child invocations to observed parent requests and relays.

Neither elapsed time nor a child's original owner can assign a later invocation.
An exact successful parent call, target session and child relay are all required.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable, Mapping


def complete_history(call: Callable[..., Any], session_id: str) -> dict[str, Any]:
    """Read bounded, contiguous history; never pass a truncated relay set on."""
    request: dict[str, Any] = {"sessionId": session_id, "maxMessages": 240}
    entries: list[dict[str, Any]] = []
    newest: dict[str, Any] | None = None
    for _ in range(20):
        page = call("session.history", request)
        if not isinstance(page, dict) or not isinstance(page.get("events"), list):
            raise ValueError("invalid session history page")
        if newest is None:
            newest = page
        observed = page["events"]
        if request.get("beforeSeq") is not None:
            seqs = [entry.get("event", {}).get("seq") for entry in observed if isinstance(entry, dict)]
            if len(seqs) != len(observed) or any(not isinstance(seq, int) or isinstance(seq, bool) or seq >= request["beforeSeq"] for seq in seqs):
                raise ValueError("session history cursor did not move backwards")
        entries = observed + entries
        if page.get("hasMore") is not True:
            return {**newest, "events": entries, "hasMore": False}
        seqs = [entry.get("event", {}).get("seq") for entry in observed if isinstance(entry, dict)]
        if not seqs or any(not isinstance(seq, int) or isinstance(seq, bool) for seq in seqs) or min(seqs) <= 0:
            raise ValueError("session history has no safe pagination cursor")
        request = {**request, "beforeSeq": min(seqs)}
    raise ValueError("session history exceeds the verified 20-page observation limit")


def structured_arguments(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, Mapping) else {}


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item["text"] for item in value
            if isinstance(item, Mapping) and item.get("type") == "text" and isinstance(item.get("text"), str))
    return ""


def in_source_window(binding: Mapping[str, Any], source_seq: int) -> bool:
    floor = binding.get("child_source_seq_floor")
    ceiling = binding.get("child_source_seq_ceiling")
    return (floor is None or source_seq > floor) and (ceiling is None or source_seq <= ceiling)


def bind_child_invocations(*, team: Mapping[str, Any], child_session_id: str,
                           history: Mapping[str, Any], root_events: list[Mapping[str, Any]]) -> dict[str, Any]:
    result = deepcopy(dict(team))
    delegations = result.get("delegations", {})
    births = [item for item in delegations.values() if isinstance(item, dict)
        and item.get("dsh_session_id") == child_session_id and not item.get("continuation_of")]
    if len(births) != 1:
        return result
    birth = births[0]
    if birth.get("lineage_verified") is not True or birth.get("lineage_origin") != "subagent":
        return result
    root_id = result.get("root_session_id")
    relays = []
    for entry in history.get("events", []):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("event"), Mapping):
            continue
        event = entry.get("event", {})
        data = event.get("data", {})
        if not isinstance(data, Mapping):
            continue
        source = data.get("source", {})
        if not isinstance(source, Mapping):
            continue
        seq = event.get("seq")
        if event.get("type") == "user/message" and source.get("kind") == "coordinator" and isinstance(seq, int) and not isinstance(seq, bool):
            relays.append({"seq": seq, "sender": source.get("senderSessionId"),
                "text": content_text(data.get("content")), "message_id": data.get("id")})
    relays.sort(key=lambda item: item["seq"])
    # Even an unverified relay retires the original invocation's window. Its
    # later actions must fail closed, never silently inherit the birth owner.
    if relays:
        ceilings = [relays[0]["seq"] - 1]
        if isinstance(birth.get("child_source_seq_ceiling"), int):
            ceilings.append(birth["child_source_seq_ceiling"])
        birth["child_source_seq_ceiling"] = min(ceilings)
        # Rebuild these derived bindings from the observed complete relay set.
        # Ambiguous replay must not retain a previously usable assignment.
        for key, item in list(delegations.items()):
            if isinstance(item, dict) and item.get("continuation_of") == birth["delegation_id"]:
                del delegations[key]
    calls = [event for event in root_events if event.get("session_id") == root_id
        and event.get("payload", {}).get("tool_name") in {"send_message", "send_message_to_agent"}
        and "arguments" in event.get("payload", {})]
    for index, relay in enumerate(relays):
        if relay["sender"] != root_id or not relay["text"] or not relay["message_id"]:
            continue
        if sum(other["text"] == relay["text"] and other["sender"] == root_id for other in relays) != 1:
            continue
        matching = []
        for call in calls:
            args = structured_arguments(call["payload"].get("arguments"))
            if args.get("subagent_id") != child_session_id or args.get("message") != relay["text"]:
                continue
            receipts = [event for event in root_events if event.get("session_id") == root_id
                and event.get("call_id") == call.get("call_id")
                and event.get("agent_run_id") == call.get("agent_run_id")
                and event.get("turn_id") == call.get("turn_id")
                and event.get("payload", {}).get("is_error") is False
                and event.get("payload", {}).get("dsh_session_id") == child_session_id]
            if len(receipts) == 1 and call.get("agent_run_id") and call.get("call_id"):
                matching.append((call, receipts[0]))
        if len(matching) != 1:
            continue
        call, receipt = matching[0]
        delegation_id = call["call_id"]
        delegations[delegation_id] = {
            **deepcopy(birth), "delegation_id": delegation_id,
            "continuation_of": birth["delegation_id"],
            "agent_run_id": call["agent_run_id"], "parent_turn_id": call["turn_id"],
            "tool_name": call["payload"]["tool_name"],
            "started_at_utc": call.get("timestamp_utc"),
            "status": "completed", "source_session_id": root_id,
            "child_source_seq_floor": relay["seq"] - 1,
            "child_source_seq_ceiling": relays[index + 1]["seq"] - 1 if index + 1 < len(relays) else None,
            "continuation_evidence": {"parent_call_event_id": call.get("event_id"),
                "parent_result_event_id": receipt.get("event_id"),
                "child_message_id": relay["message_id"], "child_source_seq": relay["seq"],
                "message_sha256": hashlib.sha256(relay["text"].encode()).hexdigest()},
        }
    return result
