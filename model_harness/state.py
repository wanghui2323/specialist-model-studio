from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .io_utils import read_json, write_json


SCHEMA_VERSION = "0.2"
_STATE_IO_LOCK = RLock()
ACTIVE_STATUSES = {
    "created",
    "queued",
    "preflight",
    "training",
    "evaluating",
    "proposing",
    "packaging",
    "needs_input",
}
TERMINAL_STATUSES = {"completed", "cancelled", "failed", "interrupted"}
ALLOWED_TRANSITIONS = {
    "created": {"queued", "preflight", "cancelled", "failed", "interrupted"},
    "queued": {"preflight", "cancelled", "failed", "interrupted"},
    "preflight": {
        "training",
        "needs_input",
        "cancelled",
        "failed",
        "interrupted",
    },
    "training": {"evaluating", "cancelled", "failed", "interrupted"},
    "evaluating": {"proposing", "cancelled", "failed", "interrupted"},
    "proposing": {"packaging", "cancelled", "failed", "interrupted"},
    "packaging": {"completed", "cancelled", "failed", "interrupted"},
    "needs_input": {"queued", "preflight", "cancelled", "failed", "interrupted"},
    "completed": set(),
    "cancelled": set(),
    "failed": set(),
    "interrupted": set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunState:
    def __init__(
        self,
        run_dir: Path,
        task_id: str,
        run_id: str,
        plugin_id: str,
        parent_run_id: str | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "run_state.json"
        self.events_path = run_dir / "events.ndjson"
        self._lock = RLock()
        self.data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "run_id": run_id,
            "plugin_id": plugin_id,
            "parent_run_id": parent_run_id,
            "status": "created",
            "event_seq": 0,
            "cancel_requested": False,
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "error": None,
        }
        self._save()
        self.event("run.created", {"status": "created"}, stage="created")

    @classmethod
    def load(cls, run_dir: str | Path) -> RunState:
        resolved = Path(run_dir).expanduser().resolve()
        instance = cls.__new__(cls)
        instance.run_dir = resolved
        instance.state_path = resolved / "run_state.json"
        instance.events_path = resolved / "events.ndjson"
        instance._lock = RLock()
        instance.data = read_json(instance.state_path)
        if instance.data.get("schema_version") == SCHEMA_VERSION:
            last_sequence = 0
            if instance.events_path.is_file():
                for line in instance.events_path.read_text(
                    encoding="utf-8"
                ).splitlines():
                    if line.strip():
                        record = json.loads(line)
                        last_sequence = max(
                            last_sequence,
                            int(record.get("seq", 0)),
                        )
            instance.data["event_seq"] = max(
                int(instance.data.get("event_seq", 0)),
                last_sequence,
            )
        return instance

    @property
    def status(self) -> str:
        return str(self.data["status"])

    @property
    def cancel_requested(self) -> bool:
        return bool(self.data.get("cancel_requested", False))

    def _save(self) -> None:
        with _STATE_IO_LOCK:
            self._merge_persisted_control_state()
            self.data["updated_at_utc"] = utc_now()
            write_json(self.state_path, self.data)

    def _merge_persisted_control_state(self) -> None:
        """Never let a stale worker overwrite a concurrent cancel request."""

        if not self.state_path.is_file():
            return
        persisted = read_json(self.state_path)
        self.data["event_seq"] = max(
            int(self.data.get("event_seq", 0)),
            int(persisted.get("event_seq", 0)),
        )
        if persisted.get("cancel_requested") is True:
            self.data["cancel_requested"] = True
            if persisted.get("cancel_reason") is not None:
                self.data["cancel_reason"] = persisted.get("cancel_reason")
            if isinstance(persisted.get("cancel_request"), dict):
                self.data["cancel_request"] = dict(persisted["cancel_request"])

    def event(
        self,
        event_type: str,
        payload: dict[str, Any],
        stage: str | None = None,
    ) -> dict[str, Any]:
        with self._lock, _STATE_IO_LOCK:
            self._merge_persisted_control_state()
            sequence = int(self.data.get("event_seq", 0)) + 1
            record = {
                "schema_version": SCHEMA_VERSION,
                "event_id": str(uuid4()),
                "seq": sequence,
                "timestamp_utc": utc_now(),
                "run_id": self.data["run_id"],
                "task_id": self.data["task_id"],
                "type": event_type,
                "stage": stage or self.status,
                "plugin_id": self.data["plugin_id"],
                "payload": payload,
            }
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.data["event_seq"] = sequence
            self._save()
            return record

    def transition(self, new_status: str, **extra: Any) -> None:
        with self._lock:
            current = self.status
            if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
                raise RuntimeError(f"invalid run transition: {current} -> {new_status}")
            self.data["status"] = new_status
            self.data.update(extra)
            self._save()
            self.event(
                "run.status_changed",
                {"from": current, "to": new_status},
                stage=new_status,
            )

    def request_cancel(
        self,
        reason: str = "requested by user",
        *,
        actor: str = "user",
        cancellation_kind: str = "user_requested",
        scope: str = "training_run",
    ) -> bool:
        with self._lock:
            if self.status not in ACTIVE_STATUSES:
                return False
            request = {
                "actor": actor,
                "kind": cancellation_kind,
                "reason": reason,
                "scope": scope,
                "requested_at_utc": utc_now(),
            }
            self.data["cancel_requested"] = True
            self.data["cancel_reason"] = reason
            self.data["cancel_request"] = request
            self._save()
            self.event("run.cancel_requested", request)
            return True

    def cancel(
        self,
        reason: str = "requested by user",
        *,
        actor: str = "user",
        cancellation_kind: str = "user_requested",
        scope: str = "training_run",
    ) -> None:
        current = self.status
        if "cancelled" not in ALLOWED_TRANSITIONS.get(current, set()):
            return
        request = self.data.get("cancel_request")
        if not isinstance(request, dict):
            request = {
                "actor": actor,
                "kind": cancellation_kind,
                "reason": reason,
                "scope": scope,
                "requested_at_utc": utc_now(),
            }
        effective_reason = str(request.get("reason") or reason)
        self.transition(
            "cancelled",
            cancel_reason=effective_reason,
            cancel_request=request,
        )
        self.event("run.cancelled", {"from": current, **request})

    def interrupt(self, message: str) -> None:
        current = self.status
        if "interrupted" not in ALLOWED_TRANSITIONS.get(current, set()):
            return
        self.transition("interrupted", error=message)
        self.event("run.interrupted", {"from": current, "error": message})

    def fail(self, message: str) -> None:
        current = self.status
        if "failed" not in ALLOWED_TRANSITIONS.get(current, set()):
            return
        self.transition("failed", error=message)
        self.event("run.failed", {"from": current, "error": message})
