"""Incremental read model over the provider's append-only event log.

Every refresh still reads native history. A matching sequence anchor permits
reuse of the already observed prefix; timestamps and session running state are
never used to infer an unchanged history or to grant permission.
"""
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Callable

from .continuation_lineage import complete_history


def _seq(entry: Any) -> int | None:
    value = entry.get("event", {}).get("seq") if isinstance(entry, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ProjectionHistoryReader:
    def __init__(self, call: Callable[..., Any], event_types: frozenset[str], max_sessions: int = 32) -> None:
        self.call = call
        self.event_types = event_types | {"turn/start"}
        self.max_sessions = max_sessions
        self._observed: OrderedDict[str, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()

    def _retain(self, history: dict[str, Any]) -> dict[str, Any]:
        return {**history, "events": [entry for entry in history["events"]
            if isinstance(entry, dict) and entry.get("event", {}).get("type") in self.event_types]}

    def _remember(self, session_id: str, history: dict[str, Any], anchor: dict[str, Any] | None) -> dict[str, Any]:
        retained = self._retain(history)
        # Malformed provider entries stay observable but never establish a cache.
        if anchor is not None and _seq(anchor) is not None:
            self._observed[session_id] = (retained, deepcopy(anchor))
            self._observed.move_to_end(session_id)
            while len(self._observed) > self.max_sessions:
                self._observed.popitem(last=False)
        else:
            self._observed.pop(session_id, None)
        return retained

    def _full(self, session_id: str) -> dict[str, Any]:
        self._observed.pop(session_id, None)
        history = complete_history(self.call, session_id)
        events = history["events"]
        return self._remember(session_id, history, events[-1] if events else None)

    def read(self, session_id: str) -> dict[str, Any]:
        cached = self._observed.get(session_id)
        if cached is None:
            return self._full(session_id)
        prefix, anchor = cached
        anchor_seq = _seq(anchor)
        request: dict[str, Any] = {"sessionId": session_id, "maxMessages": 1}
        suffix: list[dict[str, Any]] = []
        newest = None
        for _ in range(20):
            page = self.call("session.history", request)
            if not isinstance(page, dict) or not isinstance(page.get("events"), list):
                self._observed.pop(session_id, None)
                raise ValueError("invalid session history page")
            if newest is None:
                newest = page
            observed = page["events"]
            seqs = [_seq(entry) for entry in observed]
            if any(seq is None for seq in seqs) or any(a >= b for a, b in zip(seqs, seqs[1:])):
                return self._full(session_id)
            if request.get("beforeSeq") is not None and any(seq >= request["beforeSeq"] for seq in seqs):
                self._observed.pop(session_id, None)
                raise ValueError("session history cursor did not move backwards")
            suffix = observed + suffix
            # A complete provider page replaces the prefix, including after reset.
            if page.get("hasMore") is not True:
                return self._remember(session_id, {**newest, "events": suffix, "hasMore": False}, suffix[-1] if suffix else None)
            matching = [entry for entry in observed if _seq(entry) == anchor_seq]
            if matching:
                if matching != [anchor]:
                    return self._full(session_id)
                appended = [entry for entry in suffix if _seq(entry) > anchor_seq]
                result = {**newest, "events": prefix["events"] + appended, "hasMore": False}
                return self._remember(session_id, result, suffix[-1])
            if not seqs or min(seqs) <= 0 or max(seqs) < anchor_seq:
                return self._full(session_id)
            request = {"sessionId": session_id, "beforeSeq": min(seqs), "maxMessages": 240}
        self._observed.pop(session_id, None)
        raise ValueError("session history exceeds the verified 20-page observation limit")
