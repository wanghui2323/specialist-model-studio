from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json
from .resource_feasibility import (
    EnvironmentLock,
    ResourceFeasibilityError,
    ResourceFitReport,
    ResourceProbe,
    canonical_json,
    canonical_sha256,
    evaluate_resource_fit,
)


SCHEMA_VERSION = "0.9"
CURRENT_KEYS = (
    "resource_probe",
    "environment_lock",
    "resource_fit_report",
)


class FeasibilityStoreIntegrityError(ResourceFeasibilityError):
    """Raised when persisted feasibility evidence or lineage changed."""


class StaleFeasibilityReferenceError(ContractError):
    """Raised when a fit report does not bind the current probe and lock."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a non-empty string")
    if Path(value).name != value or value in {".", ".."} or "\\" in value:
        raise ContractError(f"invalid {label}: {value!r}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError(f"{label} must be a lowercase sha256 hex digest")
    if value != value.lower() or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{label} must be a lowercase sha256 hex digest")
    return value


def _copy_json(value: Any) -> Any:
    import json

    return json.loads(canonical_json(value).decode("utf-8"))


def _unsigned(record: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != digest_field}


KIND_CONFIG: dict[str, dict[str, Any]] = {
    "resource_probe": {
        "directory": "resource_probes",
        "id_field": "resource_probe_id",
        "digest_field": "probe_sha256",
        "validator": ResourceProbe.from_dict,
    },
    "environment_lock": {
        "directory": "environment_locks",
        "id_field": "environment_lock_id",
        "digest_field": "lock_sha256",
        "validator": EnvironmentLock.from_dict,
    },
    "resource_fit_report": {
        "directory": "resource_fit_reports",
        "id_field": "resource_fit_report_id",
        "digest_field": "report_sha256",
        "validator": ResourceFitReport.from_dict,
    },
}


class FeasibilityStore:
    """Append-only task-scoped storage for V3 feasibility evidence."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.tasks_root = self.workspace_root / "tasks"
        if self.tasks_root.is_symlink():
            raise ContractError("tasks directory cannot be a symlink")
        self._lock = RLock()

    def append_resource_probe(
        self,
        task_id: str,
        probe: ResourceProbe | Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._append(task_id, "resource_probe", probe)

    def append_environment_lock(
        self,
        task_id: str,
        environment_lock: EnvironmentLock | Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._append(task_id, "environment_lock", environment_lock)

    def append_resource_fit_report(
        self,
        task_id: str,
        report: ResourceFitReport | Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._append(task_id, "resource_fit_report", report)

    def get_resource_probe(self, task_id: str, probe_id: str) -> dict[str, Any]:
        return self._get(task_id, "resource_probe", probe_id)

    def get_environment_lock(self, task_id: str, lock_id: str) -> dict[str, Any]:
        return self._get(task_id, "environment_lock", lock_id)

    def get_resource_fit_report(
        self, task_id: str, report_id: str
    ) -> dict[str, Any]:
        return self._get(task_id, "resource_fit_report", report_id)

    def list_resource_probes(self, task_id: str) -> list[dict[str, Any]]:
        return self._list(task_id, "resource_probe")

    def list_environment_locks(self, task_id: str) -> list[dict[str, Any]]:
        return self._list(task_id, "environment_lock")

    def list_resource_fit_reports(self, task_id: str) -> list[dict[str, Any]]:
        return self._list(task_id, "resource_fit_report")

    def current_resource_probe(self, task_id: str) -> dict[str, Any] | None:
        return self._current_record(task_id, "resource_probe")

    def current_environment_lock(self, task_id: str) -> dict[str, Any] | None:
        return self._current_record(task_id, "environment_lock")

    def current_resource_fit_report(self, task_id: str) -> dict[str, Any] | None:
        return self._current_record(task_id, "resource_fit_report")

    def current_bundle(self, task_id: str) -> dict[str, dict[str, Any] | None]:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            state, _events = self._current_state(task_id)
            return {
                kind: (
                    self._read_record_raw(
                        task_id,
                        kind,
                        str(state[kind]["record_id"]),
                    )
                    if state[kind] is not None
                    else None
                )
                for kind in CURRENT_KEYS
            }

    def _append(
        self,
        task_id: str,
        kind: str,
        value: Any,
    ) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        config = self._config(kind)
        selected = value.to_dict() if hasattr(value, "to_dict") else value
        if not isinstance(selected, Mapping):
            raise ContractError(f"{kind} must be an object")
        try:
            record = config["validator"](selected).to_dict()
        except ResourceFeasibilityError:
            raise
        except (TypeError, ValueError) as exc:
            raise ResourceFeasibilityError(f"invalid {kind}: {exc}") from exc

        record_id = _safe_id(record[config["id_field"]], config["id_field"])
        record_digest = _digest(
            record[config["digest_field"]], config["digest_field"]
        )
        with self._lock:
            state, events = self._current_state(task_id)
            if kind == "resource_fit_report":
                self._validate_fit_context(task_id, record, state)

            path = self._record_path(task_id, kind, record_id)
            if path.exists() or path.is_symlink():
                existing = self._read_record_raw(task_id, kind, record_id)
                if canonical_json(existing) != canonical_json(record):
                    raise FeasibilityStoreIntegrityError(
                        f"immutable {kind} changed: {record_id}"
                    )
            else:
                write_json(path, record)

            referenced = next(
                (
                    event
                    for event in events
                    if event["kind"] == kind and event["record_id"] == record_id
                ),
                None,
            )
            if referenced is not None:
                if referenced["record_digest"] != record_digest:
                    raise FeasibilityStoreIntegrityError(
                        f"{kind} event digest changed: {record_id}"
                    )
                return _copy_json(record)

            event = self._create_event(
                task_id=task_id,
                kind=kind,
                record_id=record_id,
                record_digest=record_digest,
                events=events,
            )
            self._write_immutable(self._event_path(task_id, event), event)
            events.append(event)
            updated_state = self._replay(events)
            self._write_pointer(task_id, updated_state, events[-1])
            return _copy_json(record)

    def _get(self, task_id: str, kind: str, record_id: str) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        record_id = _safe_id(record_id, "record id")
        with self._lock:
            record = self._read_record_raw(task_id, kind, record_id)
            # Replaying the append chain cross-checks even a record that was
            # modified and re-hashed by hand against its task-scoped event.
            self._current_state(task_id)
            return _copy_json(record)

    def _list(self, task_id: str, kind: str) -> list[dict[str, Any]]:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            _state, events = self._current_state(task_id)
            return [
                self._read_record_raw(task_id, kind, str(event["record_id"]))
                for event in events
                if event["kind"] == kind
            ]

    def _current_record(
        self, task_id: str, kind: str
    ) -> dict[str, Any] | None:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            state, _events = self._current_state(task_id)
            selected = state[kind]
            if selected is None:
                return None
            return self._read_record_raw(
                task_id,
                kind,
                str(selected["record_id"]),
            )

    def _current_state(
        self, task_id: str
    ) -> tuple[dict[str, dict[str, Any] | None], list[dict[str, Any]]]:
        events = self._load_events(task_id)
        state = self._replay(events)
        self._verify_or_recover_pointer(task_id, state, events)
        return state, events

    def _load_events(self, task_id: str) -> list[dict[str, Any]]:
        event_dir = self._event_dir(task_id)
        if not event_dir.exists():
            if event_dir.is_symlink():
                raise FeasibilityStoreIntegrityError(
                    "feasibility event directory cannot be a symlink"
                )
            return []
        if event_dir.is_symlink() or not event_dir.is_dir():
            raise FeasibilityStoreIntegrityError("feasibility event directory changed")

        events: list[dict[str, Any]] = []
        seen_records: set[tuple[str, str]] = set()
        for path in sorted(event_dir.glob("*.json")):
            if path.is_symlink():
                raise FeasibilityStoreIntegrityError(
                    "feasibility event cannot be a symlink"
                )
            event = self._validate_event(read_json(path), task_id)
            expected_name = f"{int(event['sequence']):08d}-{event['event_id']}.json"
            if path.name != expected_name:
                raise FeasibilityStoreIntegrityError(
                    "feasibility event filename changed"
                )
            key = (str(event["kind"]), str(event["record_id"]))
            if key in seen_records:
                raise FeasibilityStoreIntegrityError(
                    "feasibility record was appended more than once"
                )
            seen_records.add(key)
            events.append(event)

        events.sort(key=lambda item: int(item["sequence"]))
        for index, event in enumerate(events, start=1):
            if event["sequence"] != index:
                raise FeasibilityStoreIntegrityError(
                    "feasibility event sequence changed"
                )
            previous = events[index - 2] if index > 1 else None
            if previous is None:
                if (
                    event["previous_event_id"] is not None
                    or event["previous_event_sha256"] is not None
                ):
                    raise FeasibilityStoreIntegrityError(
                        "first feasibility event predecessor changed"
                    )
            elif (
                event["previous_event_id"] != previous["event_id"]
                or event["previous_event_sha256"] != previous["event_sha256"]
            ):
                raise FeasibilityStoreIntegrityError(
                    "feasibility event chain changed"
                )
            record = self._read_record_raw(
                task_id,
                str(event["kind"]),
                str(event["record_id"]),
            )
            config = self._config(str(event["kind"]))
            if record[config["digest_field"]] != event["record_digest"]:
                raise FeasibilityStoreIntegrityError(
                    "feasibility event references a changed record digest"
                )
        return events

    def _validate_event(
        self, raw: Any, task_id: str
    ) -> dict[str, Any]:
        expected = {
            "schema_version",
            "object_type",
            "event_id",
            "task_id",
            "sequence",
            "kind",
            "record_id",
            "record_digest",
            "previous_event_id",
            "previous_event_sha256",
            "created_at",
            "event_sha256",
        }
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise FeasibilityStoreIntegrityError(
                "feasibility event schema changed"
            )
        event = _copy_json(raw)
        if (
            event["schema_version"] != SCHEMA_VERSION
            or event["object_type"] != "FeasibilityCurrentEvent"
            or event["task_id"] != task_id
        ):
            raise FeasibilityStoreIntegrityError(
                "feasibility event identity changed"
            )
        _safe_id(event["event_id"], "feasibility event id")
        _safe_id(event["record_id"], "feasibility record id")
        self._config(str(event["kind"]))
        _digest(event["record_digest"], "feasibility record digest")
        if (
            isinstance(event["sequence"], bool)
            or not isinstance(event["sequence"], int)
            or event["sequence"] < 1
        ):
            raise FeasibilityStoreIntegrityError(
                "invalid feasibility event sequence"
            )
        if event["sequence"] == 1:
            if (
                event["previous_event_id"] is not None
                or event["previous_event_sha256"] is not None
            ):
                raise FeasibilityStoreIntegrityError(
                    "first feasibility event cannot have a predecessor"
                )
        else:
            _safe_id(event["previous_event_id"], "previous event id")
            _digest(
                event["previous_event_sha256"],
                "previous event sha256",
            )
        if not isinstance(event["created_at"], str) or not event["created_at"]:
            raise FeasibilityStoreIntegrityError(
                "feasibility event created_at changed"
            )
        _digest(event["event_sha256"], "event_sha256")
        if canonical_sha256(_unsigned(event, "event_sha256")) != event["event_sha256"]:
            raise FeasibilityStoreIntegrityError(
                "feasibility event digest changed"
            )
        return event

    def _create_event(
        self,
        *,
        task_id: str,
        kind: str,
        record_id: str,
        record_digest: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        previous = events[-1] if events else None
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "FeasibilityCurrentEvent",
            "event_id": f"fevent_{uuid4().hex}",
            "task_id": task_id,
            "sequence": len(events) + 1,
            "kind": kind,
            "record_id": record_id,
            "record_digest": record_digest,
            "previous_event_id": (previous or {}).get("event_id"),
            "previous_event_sha256": (previous or {}).get("event_sha256"),
            "created_at": _now(),
        }
        event["event_sha256"] = canonical_sha256(event)
        return self._validate_event(event, task_id)

    def _replay(
        self, events: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any] | None]:
        state: dict[str, dict[str, Any] | None] = {
            kind: None for kind in CURRENT_KEYS
        }
        for event in events:
            kind = str(event["kind"])
            state[kind] = {
                "record_id": event["record_id"],
                "record_digest": event["record_digest"],
            }
            if kind in {"resource_probe", "environment_lock"}:
                state["resource_fit_report"] = None
        return state

    def _validate_fit_context(
        self,
        task_id: str,
        report: Mapping[str, Any],
        state: Mapping[str, dict[str, Any] | None],
    ) -> None:
        probe = state["resource_probe"]
        lock = state["environment_lock"]
        if probe is None or lock is None:
            raise StaleFeasibilityReferenceError(
                "a resource fit report requires a current probe and environment lock"
            )
        if (
            report["resource_probe_id"] != probe["record_id"]
            or report["resource_probe_sha256"] != probe["record_digest"]
        ):
            raise StaleFeasibilityReferenceError(
                "resource fit report does not bind the current probe"
            )
        if (
            report["environment_lock_id"] != lock["record_id"]
            or report["environment_lock_sha256"] != lock["record_digest"]
        ):
            raise StaleFeasibilityReferenceError(
                "resource fit report does not bind the current environment lock"
            )
        probe_record = self._read_record_raw(
            task_id, "resource_probe", str(probe["record_id"])
        )
        lock_record = self._read_record_raw(
            task_id, "environment_lock", str(lock["record_id"])
        )
        requirements = report.get("requirements")
        if not isinstance(requirements, Mapping):
            raise FeasibilityStoreIntegrityError(
                "resource fit report requirements changed"
            )
        expected = evaluate_resource_fit(
            training_plan_revision_id=str(report["training_plan_revision_id"]),
            training_plan_sha256=str(report["training_plan_sha256"]),
            resource_budget={
                field: requirements.get(field)
                for field in (
                    "max_seconds",
                    "ram_bytes",
                    "vram_bytes",
                    "disk_bytes",
                )
            },
            environment_lock=lock_record,
            resource_probe=probe_record,
            estimator_version=str(report["estimator_version"]),
        ).to_dict()
        if canonical_json(expected) != canonical_json(report):
            raise FeasibilityStoreIntegrityError(
                "resource fit report does not match deterministic evaluation"
            )

    def _verify_or_recover_pointer(
        self,
        task_id: str,
        state: dict[str, dict[str, Any] | None],
        events: list[dict[str, Any]],
    ) -> None:
        path = self._pointer_path(task_id)
        if not events:
            if path.exists() or path.is_symlink():
                raise FeasibilityStoreIntegrityError(
                    "current feasibility pointer exists without events"
                )
            return
        if not path.is_file():
            if path.is_symlink():
                raise FeasibilityStoreIntegrityError(
                    "current feasibility pointer cannot be a symlink"
                )
            self._write_pointer(task_id, state, events[-1])
            return

        pointer = self._read_pointer(path, task_id)
        sequence = int(pointer["sequence"])
        if sequence > len(events):
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer is ahead of the event chain"
            )
        expected_head = events[sequence - 1]
        expected_state = self._replay(events[:sequence])
        if (
            pointer["head_event_id"] != expected_head["event_id"]
            or pointer["head_event_sha256"] != expected_head["event_sha256"]
            or any(pointer[kind] != expected_state[kind] for kind in CURRENT_KEYS)
        ):
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer projection changed"
            )
        if sequence < len(events):
            # The immutable event was fsynced before an interrupted projection
            # update. Rebuild only the mutable projection from verified history.
            self._write_pointer(task_id, state, events[-1])

    def _read_pointer(self, path: Path, task_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer cannot be a symlink"
            )
        expected = {
            "schema_version",
            "object_type",
            "task_id",
            "sequence",
            "head_event_id",
            "head_event_sha256",
            *CURRENT_KEYS,
            "updated_at",
            "pointer_sha256",
        }
        raw = read_json(path)
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer schema changed"
            )
        pointer = _copy_json(raw)
        if (
            pointer["schema_version"] != SCHEMA_VERSION
            or pointer["object_type"] != "FeasibilityCurrentPointer"
            or pointer["task_id"] != task_id
        ):
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer identity changed"
            )
        if (
            isinstance(pointer["sequence"], bool)
            or not isinstance(pointer["sequence"], int)
            or pointer["sequence"] < 1
        ):
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer sequence changed"
            )
        _safe_id(pointer["head_event_id"], "head event id")
        _digest(pointer["head_event_sha256"], "head event sha256")
        for kind in CURRENT_KEYS:
            selected = pointer[kind]
            if selected is None:
                continue
            if not isinstance(selected, Mapping) or set(selected) != {
                "record_id",
                "record_digest",
            }:
                raise FeasibilityStoreIntegrityError(
                    f"current {kind} pointer changed"
                )
            _safe_id(selected["record_id"], f"current {kind} id")
            _digest(selected["record_digest"], f"current {kind} digest")
        if not isinstance(pointer["updated_at"], str) or not pointer["updated_at"]:
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer updated_at changed"
            )
        _digest(pointer["pointer_sha256"], "pointer_sha256")
        if canonical_sha256(_unsigned(pointer, "pointer_sha256")) != pointer["pointer_sha256"]:
            raise FeasibilityStoreIntegrityError(
                "current feasibility pointer digest changed"
            )
        return pointer

    def _write_pointer(
        self,
        task_id: str,
        state: Mapping[str, dict[str, Any] | None],
        head: Mapping[str, Any],
    ) -> None:
        pointer: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "FeasibilityCurrentPointer",
            "task_id": task_id,
            "sequence": head["sequence"],
            "head_event_id": head["event_id"],
            "head_event_sha256": head["event_sha256"],
            **{kind: _copy_json(state[kind]) for kind in CURRENT_KEYS},
            "updated_at": _now(),
        }
        pointer["pointer_sha256"] = canonical_sha256(pointer)
        write_json(self._pointer_path(task_id), pointer)

    def _read_record_raw(
        self, task_id: str, kind: str, record_id: str
    ) -> dict[str, Any]:
        config = self._config(kind)
        path = self._record_path(task_id, kind, record_id)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"{kind} not found: {record_id}")
        try:
            record = config["validator"](read_json(path)).to_dict()
        except ResourceFeasibilityError as exc:
            raise FeasibilityStoreIntegrityError(
                f"persisted {kind} failed verification: {record_id}: {exc}"
            ) from exc
        if record[config["id_field"]] != record_id:
            raise FeasibilityStoreIntegrityError(
                f"{kind} filename and record id differ"
            )
        return record

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> None:
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise FeasibilityStoreIntegrityError(
                    f"immutable feasibility path changed: {path.name}"
                )
            if canonical_json(read_json(path)) != canonical_json(value):
                raise FeasibilityStoreIntegrityError(
                    f"immutable feasibility record changed: {path.name}"
                )
            return
        write_json(path, dict(value))

    def _config(self, kind: str) -> dict[str, Any]:
        try:
            return KIND_CONFIG[kind]
        except KeyError as exc:
            raise ContractError(f"unsupported feasibility record kind: {kind}") from exc

    def _task_root(self, task_id: str) -> Path:
        task_id = _safe_id(task_id, "task id")
        task_root = self.tasks_root / task_id
        if task_root.is_symlink():
            raise ContractError("task directory cannot be a symlink")
        if not task_root.is_dir():
            raise FileNotFoundError(f"task not found: {task_id}")
        return task_root

    def _root(self, task_id: str) -> Path:
        root = self._task_root(task_id) / "feasibility"
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise FeasibilityStoreIntegrityError(
                "feasibility directory cannot be a symlink or non-directory"
            )
        return root

    def _record_dir(self, task_id: str, kind: str) -> Path:
        directory = self._root(task_id) / str(self._config(kind)["directory"])
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise FeasibilityStoreIntegrityError(
                f"{kind} directory cannot be a symlink or non-directory"
            )
        return directory

    def _record_path(self, task_id: str, kind: str, record_id: str) -> Path:
        return self._record_dir(task_id, kind) / f"{_safe_id(record_id, 'record id')}.json"

    def _event_dir(self, task_id: str) -> Path:
        directory = self._root(task_id) / "current_events"
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise FeasibilityStoreIntegrityError(
                "feasibility event directory cannot be a symlink or non-directory"
            )
        return directory

    def _event_path(self, task_id: str, event: Mapping[str, Any]) -> Path:
        return self._event_dir(task_id) / (
            f"{int(event['sequence']):08d}-{_safe_id(event['event_id'], 'event id')}.json"
        )

    def _pointer_path(self, task_id: str) -> Path:
        return self._root(task_id) / "current.json"


__all__ = [
    "FeasibilityStore",
    "FeasibilityStoreIntegrityError",
    "StaleFeasibilityReferenceError",
]
