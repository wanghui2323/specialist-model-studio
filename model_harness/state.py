from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import write_json


ALLOWED_TRANSITIONS = {
    "created": {"preflight", "failed"},
    "preflight": {"training", "needs_input", "failed"},
    "training": {"evaluating", "failed"},
    "evaluating": {"packaging", "failed"},
    "packaging": {"completed", "failed"},
    "needs_input": {"preflight", "failed"},
    "completed": set(),
    "failed": set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunState:
    def __init__(self, run_dir: Path, task_id: str, run_id: str) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "run_state.json"
        self.events_path = run_dir / "events.ndjson"
        self.data: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "status": "created",
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "error": None,
        }
        self._save()
        self.event("run_created", {"status": "created"})

    def _save(self) -> None:
        self.data["updated_at_utc"] = utc_now()
        write_json(self.state_path, self.data)

    def event(self, name: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp_utc": utc_now(),
            "event": name,
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def transition(self, new_status: str, **extra: Any) -> None:
        current = str(self.data["status"])
        if new_status not in ALLOWED_TRANSITIONS[current]:
            raise RuntimeError(f"invalid run transition: {current} -> {new_status}")
        self.data["status"] = new_status
        self.data.update(extra)
        self._save()
        self.event("status_changed", {"from": current, "to": new_status})

    def fail(self, message: str) -> None:
        current = str(self.data["status"])
        if "failed" not in ALLOWED_TRANSITIONS[current]:
            return
        self.data["status"] = "failed"
        self.data["error"] = message
        self._save()
        self.event("run_failed", {"from": current, "error": message})
