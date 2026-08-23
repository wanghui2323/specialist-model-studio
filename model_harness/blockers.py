from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .errors import ContractError
from .io_utils import read_json, write_json


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_STAGES = {
    "source_discovery",
    "source_resolution",
    "source_snapshot",
    "repository_analysis",
    "training_plan",
    "resource_probe",
    "environment_lock",
    "resource_fit",
    "build",
    "run",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: str, label: str) -> str:
    selected = str(value)
    if not _ID.fullmatch(selected):
        raise ContractError(f"invalid {label}")
    return selected


def _safe_task_id(value: str) -> str:
    selected = str(value)
    if (
        not selected
        or len(selected) > 160
        or selected in {".", ".."}
        or "/" in selected
        or "\\" in selected
        or "\x00" in selected
        or Path(selected).name != selected
    ):
        raise ContractError("invalid task id")
    return selected


def _safe_text(value: Any, label: str, maximum: int) -> str:
    selected = str(value or "").strip()
    if (
        not selected
        or len(selected) > maximum
        or any(ord(character) < 32 for character in selected)
    ):
        raise ContractError(f"invalid {label}")
    return selected


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    record = deepcopy(dict(value))
    record["content_digest"] = _digest(record)
    return record


def _verified(value: Any, expected_type: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("object_type") != expected_type:
        raise ContractError("invalid blocker record")
    supplied = value.get("content_digest")
    unsigned = {key: item for key, item in value.items() if key != "content_digest"}
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise ContractError("blocker record digest mismatch")
    return deepcopy(value)


class BlockerStore:
    """Append-only blocker facts plus separate resolution facts.

    BlockerEvidence is never edited to become resolved. A BlockerResolution
    points at it, preserving the original failure after restart and allowing
    the UI to derive active blockers without inventing local state.
    """

    SCHEMA_VERSION = "0.1"

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        self.tasks_dir = (self.root / "tasks").resolve()
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(
        self,
        task_id: str,
        *,
        stage: str,
        code: str,
        message: str,
        retry_action: str,
        related_object_type: str | None = None,
        related_object_id: str | None = None,
        related_object_digest: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_stage = str(stage).strip().lower()
        if selected_stage not in _STAGES:
            raise ContractError("invalid blocker stage")
        selected_code = _safe_text(code, "blocker code", 120)
        selected_message = _safe_text(message, "blocker message", 500)
        selected_retry = _safe_text(retry_action, "retry action", 120)
        related_type = (
            _safe_text(related_object_type, "related object type", 80)
            if related_object_type is not None
            else None
        )
        related_id = (
            _safe_id(related_object_id, "related object id")
            if related_object_id is not None
            else None
        )
        related_digest = (
            str(related_object_digest).strip().lower()
            if related_object_digest is not None
            else None
        )
        if related_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", related_digest):
            raise ContractError("invalid related object digest")
        selected_details = deepcopy(dict(details or {}))
        try:
            _canonical(selected_details)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid blocker details") from exc
        semantic = {
            "task_id": selected_task,
            "stage": selected_stage,
            "code": selected_code,
            "retry_action": selected_retry,
            "related_object_type": related_type,
            "related_object_id": related_id,
            "related_object_digest": related_digest,
            "details": selected_details,
        }
        semantic_digest = _digest(semantic)
        blocker_id = f"blocker_{semantic_digest[:24]}"
        record = _sealed(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "BlockerEvidence",
                "blocker_id": blocker_id,
                **semantic,
                "message": selected_message,
                "semantic_digest": semantic_digest,
                "created_at_utc": _now(),
            }
        )
        with self._lock:
            path = self._evidence_dir(selected_task) / f"{blocker_id}.json"
            if path.exists():
                return _verified(read_json(path), "BlockerEvidence")
            write_json(path, record)
        return record

    def resolve(
        self,
        task_id: str,
        blocker_id: str,
        *,
        action: str,
        related_object_type: str | None = None,
        related_object_id: str | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_blocker = _safe_id(blocker_id, "blocker id")
        blocker = self.get(selected_task, selected_blocker)
        semantic = {
            "task_id": selected_task,
            "blocker_id": blocker["blocker_id"],
            "blocker_digest": blocker["content_digest"],
            "action": _safe_text(action, "blocker resolution action", 160),
            "related_object_type": (
                _safe_text(related_object_type, "related object type", 80)
                if related_object_type is not None
                else None
            ),
            "related_object_id": (
                _safe_id(related_object_id, "related object id")
                if related_object_id is not None
                else None
            ),
        }
        semantic_digest = _digest(semantic)
        resolution_id = f"blocker_resolution_{semantic_digest[:24]}"
        record = _sealed(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "BlockerResolution",
                "resolution_id": resolution_id,
                **semantic,
                "semantic_digest": semantic_digest,
                "created_at_utc": _now(),
            }
        )
        with self._lock:
            path = self._resolution_dir(selected_task) / f"{resolution_id}.json"
            if path.exists():
                return _verified(read_json(path), "BlockerResolution")
            write_json(path, record)
        return record

    def get(self, task_id: str, blocker_id: str) -> dict[str, Any]:
        path = self._evidence_dir(_safe_task_id(task_id)) / f"{_safe_id(blocker_id, 'blocker id')}.json"
        if not path.exists():
            raise FileNotFoundError("blocker not found")
        return _verified(read_json(path), "BlockerEvidence")

    def list(self, task_id: str, *, active_only: bool = False) -> list[dict[str, Any]]:
        selected_task = _safe_task_id(task_id)
        evidence = [
            _verified(read_json(path), "BlockerEvidence")
            for path in sorted(self._evidence_dir(selected_task).glob("*.json"))
        ]
        resolved_ids = {
            record["blocker_id"]
            for record in (
                _verified(read_json(path), "BlockerResolution")
                for path in sorted(self._resolution_dir(selected_task).glob("*.json"))
            )
        }
        for record in evidence:
            record["active"] = record["blocker_id"] not in resolved_ids
        if active_only:
            evidence = [record for record in evidence if record["active"]]
        return sorted(evidence, key=lambda item: (item["created_at_utc"], item["blocker_id"]))

    def resolve_active_stage(
        self,
        task_id: str,
        stage: str,
        *,
        action: str,
        related_object_type: str | None = None,
        related_object_id: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_stage = str(stage).strip().lower()
        resolved: list[dict[str, Any]] = []
        for blocker in self.list(task_id, active_only=True):
            if blocker["stage"] == selected_stage:
                resolved.append(
                    self.resolve(
                        task_id,
                        blocker["blocker_id"],
                        action=action,
                        related_object_type=related_object_type,
                        related_object_id=related_object_id,
                    )
                )
        return resolved

    def _task_dir(self, task_id: str) -> Path:
        directory = self.tasks_dir / _safe_task_id(task_id) / "blockers"
        directory.mkdir(parents=True, exist_ok=True)
        resolved = directory.resolve()
        if self.tasks_dir not in resolved.parents:
            raise ContractError("unsafe blocker directory")
        return resolved

    def _evidence_dir(self, task_id: str) -> Path:
        directory = self._task_dir(task_id) / "evidence"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _resolution_dir(self, task_id: str) -> Path:
        directory = self._task_dir(task_id) / "resolutions"
        directory.mkdir(parents=True, exist_ok=True)
        return directory
