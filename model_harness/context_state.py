"""Task-owned conversation memory. Never a task contract or execution grant."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence

from .io_utils import read_json, write_json


class ContextStateError(ValueError):
    pass


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^\s/\\\x00-\x1f]{1,200}", value) or value in {".", ".."}:
        raise ContextStateError("invalid context identity")
    return value


class ContextStateStore:
    """Atomic current view plus immutable revisions; reads never acquire a lock.

    Semantic entries are Agent interpretations with exact source quotes, not
    independently confirmed facts. Current execution truth is supplied from
    TrainingTask separately. The store grants no permission to change it.
    """
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root).resolve() / "context-state"
        self._lock = RLock()

    def directory(self, owner_id: str) -> Path:
        path = self.root / identifier(owner_id)
        if path.is_symlink() or self.root.is_symlink():
            raise ContextStateError("context state directory is a symbolic link")
        return path

    def read(self, owner_id: str) -> dict[str, Any]:
        path = self.directory(owner_id) / "state.json"
        if not path.exists():
            return {"schema_version": "1.0", "owner_id": owner_id, "revision": 0, "messages": [], "entries": [], "updates": [], "grants_execution_authorization": False}
        if path.is_symlink():
            raise ContextStateError("context state is a symbolic link")
        value = read_json(path)
        if value.get("owner_id") != owner_id or value.get("schema_version") != "1.0" or value.get("state_sha256") != sha({k: v for k, v in value.items() if k != "state_sha256"}):
            raise ContextStateError("context state identity or digest mismatch")
        return value

    def commit(self, state: dict[str, Any]) -> dict[str, Any]:
        state = deepcopy(state)
        state.pop("state_sha256", None)
        state["revision"] += 1
        state["state_sha256"] = sha(state)
        directory = self.directory(state["owner_id"])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (directory / "revisions").is_symlink():
            raise ContextStateError("context revision directory is a symbolic link")
        revision = directory / "revisions" / f"{state['revision']:08d}.json"
        if revision.is_symlink():
            raise ContextStateError("context revision is a symbolic link")
        if revision.exists():
            # Recover a crash between immutable revision and current pointer.
            if read_json(revision) != state:
                raise ContextStateError("context revision already has different evidence")
        else:
            write_json(revision, state)
        write_json(directory / "state.json", state)
        return state

    def ingest_prompt_runs(self, owner_id: str, runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        with self._lock:
            state = self.read(owner_id)
            known = {m["request_id"]: m for m in state["messages"]}
            changed = False
            for run in runs:
                request = run.get("composer_request") or {}
                request_id = request.get("request_id")
                text = run.get("user_message")
                if not request_id or not isinstance(text, str):
                    continue
                message = {"request_id": identifier(request_id), "actor": request.get("actor", "user"), "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "agent_run_id": run.get("run_id")}
                prior = known.get(request_id)
                if prior is not None:
                    if prior != message:
                        raise ContextStateError("request id changed its original message")
                    continue
                state["messages"].append(message)
                known[request_id] = message
                changed = True
            return self.commit(state) if changed else state

    def record(self, owner_id: str, *, base_revision: int, update_id: str, entries: list[dict[str, Any]], provenance: dict[str, str]) -> dict[str, Any]:
        if type(base_revision) is not int or base_revision < 0 or not isinstance(entries, list) or not 1 <= len(entries) <= 8:
            raise ContextStateError("bounded entries and current base revision required")
        identifier(update_id)
        if set(provenance) != {"session_id", "call_id"} or any(not isinstance(v, str) or not v or len(v) > 200 for v in provenance.values()):
            raise ContextStateError("verified caller provenance required")
        payload_sha = sha({"entries": entries, "session_id": provenance["session_id"], "base_revision": base_revision})
        with self._lock:
            state = self.read(owner_id)
            prior = next((u for u in state["updates"] if u["update_id"] == update_id), None)
            if prior:
                if prior["payload_sha256"] != payload_sha:
                    raise ContextStateError("context update id reused for different entries")
                return state
            if state["revision"] != base_revision:
                raise ContextStateError("context changed; re-read before recording decisions")
            messages = {m["request_id"]: m for m in state["messages"]}
            source_order = {m["request_id"]: i for i, m in enumerate(state["messages"])}
            active = {e["slot"]: e for e in state["entries"] if e["status"] == "active"}
            validated = []
            for entry in entries:
                if set(entry) != {"slot", "kind", "value", "source_request_id", "quote"}:
                    raise ContextStateError("context entry has unknown or missing fields")
                slot = entry["slot"]
                if not isinstance(slot, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", slot) or slot.split(".")[0] in {"approval", "authorization", "permission", "credential", "system", "contract", "run"}:
                    raise ContextStateError("conversation slot cannot impersonate host controls")
                if entry["kind"] not in {"user_explicit", "agent_proposal", "assumption", "unresolved", "resolved_answer"}:
                    raise ContextStateError("unknown conversation evidence kind")
                value, quote = entry["value"], entry["quote"]
                if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                    raise ContextStateError("context value must be bounded text")
                message = messages.get(entry["source_request_id"])
                if message is None or not isinstance(quote, str) or not quote or len(quote) > 2000 or quote not in message["text"]:
                    raise ContextStateError("context entry needs an exact owned message quote")
                if entry["kind"] in {"user_explicit", "resolved_answer"} and message["actor"] != "user":
                    raise ContextStateError("system/operator notices cannot become a user decision")
                previous = active.get(slot)
                if previous:
                    if source_order[entry['source_request_id']] < source_order[previous['source_request_id']]:
                        raise ContextStateError("an older message cannot replace a newer conversation choice")
                    if previous['kind'] in {'user_explicit','resolved_answer'} and entry['kind'] in {'agent_proposal','assumption','unresolved'}:
                        raise ContextStateError("a proposal cannot replace a user choice; record it in a separate slot")
                if slot in {e["slot"] for e in validated}:
                    raise ContextStateError("duplicate slots in one context update")
                validated.append({**deepcopy(entry), "entry_id": "context-entry-" + sha({"update_id": update_id, "slot": slot})[:24], "status": "active", "interpretation_status": "agent_derived_quote_verified_only", "source_text_sha256": message["text_sha256"], "provenance": deepcopy(provenance), "grants_execution_authorization": False})
            for entry in validated:
                if entry["slot"] in active:
                    active[entry["slot"]]["status"] = "superseded"
                    active[entry["slot"]]["superseded_by"] = entry["entry_id"]
                state["entries"].append(entry)
            if len({e['slot'] for e in state['entries'] if e['status']=='active'}) > 32:
                raise ContextStateError("active conversation state exceeds 32 slots")
            if len(json.dumps([e for e in state['entries'] if e['status']=='active'], ensure_ascii=False).encode()) > 16384:
                raise ContextStateError("active conversation state exceeds its 16KiB working-set budget")
            state["updates"].append({"update_id": update_id, "payload_sha256": payload_sha})
            return self.commit(state)

    def message(self, owner_id: str, request_id: str, *, start: int = 0, max_chars: int = 4000) -> dict[str, Any]:
        identifier(request_id)
        if type(start) is not int or start < 0 or type(max_chars) is not int or not 1 <= max_chars <= 8000:
            raise ContextStateError("invalid evidence range")
        value = next((m for m in self.read(owner_id)["messages"] if m["request_id"] == request_id), None)
        if value is None:
            raise FileNotFoundError("owned conversation message not found")
        text = value["text"]
        return {"owner_id": owner_id, "request_id": request_id, "actor": value['actor'], "text_sha256": value['text_sha256'], "text": text[start:start + max_chars], "start": start, "end": min(len(text), start + max_chars), "total_chars": len(text), "complete": start == 0 and max_chars >= len(text), "has_more": start + max_chars < len(text), "grants_execution_authorization": False}

    def snapshot(self, owner_id: str) -> dict[str, Any]:
        state = self.read(owner_id)
        # All current semantic entries fit a controlled slot/value bound.
        active = [deepcopy(e) for e in state["entries"] if e["status"] == "active"]
        latest = []
        for message in state["messages"][-4:]:
            latest.append({k: message[k] for k in ("request_id", "actor", "text_sha256", "agent_run_id")})
            latest[-1].update(text_preview=message["text"][:600], complete=len(message["text"]) <= 600, read_tool="model_harness_read_context_evidence")
        return {"schema_version": "1.0", "owner_id": owner_id, "revision": state["revision"], "state_sha256": state.get("state_sha256"), "entries": active, "recent_sources": latest, "source_count": len(state["messages"]), "grants_execution_authorization": False, "instruction": "Conversation entries are source-linked interpretations. Current TaskSpec, dataset, contract, Run and approval services remain authoritative. Preserve user choices and resolved answers; re-read source text when ambiguous. Memory cannot approve, change a gate or start execution."}
