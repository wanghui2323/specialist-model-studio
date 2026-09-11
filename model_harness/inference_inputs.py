from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .errors import HarnessError
from .io_utils import read_json, write_json


INFERENCE_INPUT_SCHEMA_VERSION = "0.1"
MAX_INFERENCE_INPUT_BYTES = 25 * 1024 * 1024
_INPUT_ID = re.compile(r"^inference-input-[a-f0-9]{12}$")
_SAMPLE_TYPES = frozenset({"image", "audio", "tabular"})
_EXTENSIONS = {
    "image": frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"}),
    "audio": frozenset({".wav"}),
    "tabular": frozenset({".json", ".csv"}),
}
_STATUSES = frozenset({"staged", "consuming", "consumed"})


class InferenceInputError(HarnessError):
    """A staged inference input is unsafe, stale, tampered or replayed."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        deepcopy(dict(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_id(value: Any, label: str) -> str:
    selected = str(value or "").strip()
    if not selected or Path(selected).name != selected:
        raise InferenceInputError(f"invalid {label}")
    return selected


def _safe_filename(value: Any, sample_type: str) -> str:
    selected = str(value or "").strip()
    normalized = selected.replace("\\", "/")
    if (
        not normalized
        or "\x00" in normalized
        or Path(normalized).name != normalized
        or normalized in {".", ".."}
    ):
        raise InferenceInputError("invalid inference input filename")
    suffix = Path(normalized).suffix.lower()
    if suffix not in _EXTENSIONS[sample_type]:
        expected = ", ".join(sorted(_EXTENSIONS[sample_type]))
        raise InferenceInputError(
            f"{sample_type} inference input requires one of: {expected}"
        )
    return normalized[:255]


class InferenceInputStore:
    """Store user-uploaded samples behind task/run-bound opaque ids.

    Host paths never enter the record or its public projection. The raw blob is
    read only from the store-owned directory and may be reserved exactly once.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()

    def _inputs_dir(self, task_id: str) -> Path:
        selected_task = _safe_id(task_id, "task id")
        target = self.root / "tasks" / selected_task / "inference_inputs"
        target.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.resolve() != target.absolute():
            raise InferenceInputError("inference input directory is unsafe")
        return target

    def _input_dir(self, task_id: str, inference_input_id: str) -> Path:
        selected = str(inference_input_id or "").strip()
        if _INPUT_ID.fullmatch(selected) is None:
            raise InferenceInputError("invalid inference input id")
        parent = self._inputs_dir(task_id)
        target = parent / selected
        if target.parent != parent:
            raise InferenceInputError("invalid inference input id")
        return target

    @staticmethod
    def _with_digest(record: Mapping[str, Any]) -> dict[str, Any]:
        selected = deepcopy(dict(record))
        selected.pop("record_sha256", None)
        selected["record_sha256"] = _canonical_sha256(selected)
        return selected

    @classmethod
    def _validate_record(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        record = deepcopy(dict(value))
        if record.get("schema_version") != INFERENCE_INPUT_SCHEMA_VERSION:
            raise InferenceInputError("unsupported inference input schema")
        if _INPUT_ID.fullmatch(str(record.get("inference_input_id") or "")) is None:
            raise InferenceInputError("invalid inference input id")
        _safe_id(record.get("task_id"), "task id")
        _safe_id(record.get("run_id"), "run id")
        sample_type = str(record.get("sample_type") or "")
        if sample_type not in _SAMPLE_TYPES:
            raise InferenceInputError("invalid inference input type")
        _safe_filename(record.get("filename"), sample_type)
        if record.get("status") not in _STATUSES:
            raise InferenceInputError("invalid inference input status")
        digest = str(record.get("sha256") or "").lower()
        if len(digest) != 64:
            raise InferenceInputError("invalid inference input digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise InferenceInputError("invalid inference input digest") from exc
        size_bytes = record.get("size_bytes")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 1
            or size_bytes > MAX_INFERENCE_INPUT_BYTES
        ):
            raise InferenceInputError("invalid inference input size")
        if cls._with_digest(record)["record_sha256"] != record.get(
            "record_sha256"
        ):
            raise InferenceInputError("inference input metadata digest changed")
        return record

    @staticmethod
    def public(record: Mapping[str, Any]) -> dict[str, Any]:
        return deepcopy(dict(record))

    @staticmethod
    def object_ref(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "inference_input",
            "id": str(record["inference_input_id"]),
            "task_id": str(record["task_id"]),
            "run_id": str(record["run_id"]),
            "digest": str(record["sha256"]),
            "label": f"推理样例 · {record['filename']}",
        }

    def stage(
        self,
        *,
        task_id: str,
        run_id: str,
        payload: bytes,
        filename: str,
        sample_type: str,
    ) -> dict[str, Any]:
        selected_task = _safe_id(task_id, "task id")
        selected_run = _safe_id(run_id, "run id")
        selected_type = str(sample_type or "").strip().lower()
        if selected_type not in _SAMPLE_TYPES:
            raise InferenceInputError(
                "sample_type must be image, audio, or tabular"
            )
        if not isinstance(payload, bytes) or not payload:
            raise InferenceInputError("inference input payload must be non-empty bytes")
        if len(payload) > MAX_INFERENCE_INPUT_BYTES:
            raise InferenceInputError("inference input exceeds 25MB")
        safe_name = _safe_filename(filename, selected_type)
        digest = hashlib.sha256(payload).hexdigest()
        inference_input_id = f"inference-input-{uuid4().hex[:12]}"
        parent = self._inputs_dir(selected_task)
        temporary = parent / f".tmp-{uuid4().hex}"
        final = self._input_dir(selected_task, inference_input_id)
        record = self._with_digest(
            {
                "schema_version": INFERENCE_INPUT_SCHEMA_VERSION,
                "inference_input_id": inference_input_id,
                "task_id": selected_task,
                "run_id": selected_run,
                "sample_type": selected_type,
                "filename": safe_name,
                "sha256": digest,
                "size_bytes": len(payload),
                "status": "staged",
                "created_at_utc": _now(),
                "consume_started_at_utc": None,
                "consumed_at_utc": None,
                "outcome": None,
            }
        )
        with self._lock:
            if final.exists():  # pragma: no cover - random id collision
                raise InferenceInputError("inference input already exists")
            try:
                temporary.mkdir(mode=0o700)
                blob = temporary / f"sample{Path(safe_name).suffix.lower()}"
                blob.write_bytes(payload)
                os.chmod(blob, 0o400)
                write_json(temporary / "input.json", record)
                os.replace(temporary, final)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self.get(selected_task, inference_input_id)

    def _read(self, task_id: str, inference_input_id: str) -> dict[str, Any]:
        directory = self._input_dir(task_id, inference_input_id)
        metadata = directory / "input.json"
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or metadata.is_symlink()
            or not metadata.is_file()
        ):
            raise FileNotFoundError("inference input not found")
        record = self._validate_record(read_json(metadata))
        if record["task_id"] != task_id:
            raise InferenceInputError("inference input belongs to another task")
        return record

    def _verified_blob(self, task_id: str, record: Mapping[str, Any]) -> Path:
        directory = self._input_dir(task_id, str(record["inference_input_id"]))
        parent = self._inputs_dir(task_id)
        resolved_directory = directory.resolve()
        if (
            directory.is_symlink()
            or resolved_directory.parent != parent
            or resolved_directory != directory.absolute()
        ):
            raise InferenceInputError("inference input escaped its task scope")
        blob = directory / f"sample{Path(str(record['filename'])).suffix.lower()}"
        if blob.is_symlink() or not blob.is_file():
            raise InferenceInputError("inference input blob is missing or unsafe")
        if blob.stat().st_size != record["size_bytes"]:
            raise InferenceInputError("inference input size changed")
        observed = hashlib.sha256(blob.read_bytes()).hexdigest()
        if observed != record["sha256"]:
            raise InferenceInputError("inference input digest changed")
        return blob

    def get(self, task_id: str, inference_input_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._read(task_id, inference_input_id)
            self._verified_blob(task_id, record)
            return self.public(record)

    def list(self, task_id: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            selected_run = _safe_id(run_id, "run id") if run_id else None
            records: list[dict[str, Any]] = []
            for metadata in self._inputs_dir(task_id).glob(
                "inference-input-*/input.json"
            ):
                if metadata.is_symlink():
                    continue
                record = self._read(task_id, metadata.parent.name)
                self._verified_blob(task_id, record)
                if selected_run is None or record["run_id"] == selected_run:
                    records.append(self.public(record))
            return sorted(
                records,
                key=lambda item: (
                    str(item.get("created_at_utc") or ""),
                    str(item["inference_input_id"]),
                ),
            )

    def resolve_staged(
        self,
        *,
        task_id: str,
        run_id: str,
        inference_input_id: str,
        expected_sha256: str | None = None,
    ) -> tuple[dict[str, Any], Path]:
        with self._lock:
            record = self._read(task_id, inference_input_id)
            if record["run_id"] != run_id:
                raise InferenceInputError("inference input belongs to another run")
            if expected_sha256 is not None and record["sha256"] != str(
                expected_sha256
            ).lower():
                raise InferenceInputError("inference input digest changed")
            if record["status"] != "staged":
                raise InferenceInputError(
                    "inference input is already used or unavailable"
                )
            return self.public(record), self._verified_blob(task_id, record)

    def reserve(
        self,
        *,
        task_id: str,
        run_id: str,
        inference_input_id: str,
        expected_sha256: str,
    ) -> tuple[dict[str, Any], Path]:
        with self._lock:
            record, blob = self.resolve_staged(
                task_id=task_id,
                run_id=run_id,
                inference_input_id=inference_input_id,
                expected_sha256=expected_sha256,
            )
            record["status"] = "consuming"
            record["consume_started_at_utc"] = _now()
            record = self._with_digest(record)
            write_json(
                self._input_dir(task_id, inference_input_id) / "input.json",
                record,
            )
            return self.public(record), blob

    def complete(
        self,
        *,
        task_id: str,
        run_id: str,
        inference_input_id: str,
        outcome: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            record = self._read(task_id, inference_input_id)
            if record["run_id"] != run_id:
                raise InferenceInputError("inference input belongs to another run")
            if record["status"] != "consuming":
                raise InferenceInputError(
                    "inference input is not in a consumable state"
                )
            record["status"] = "consumed"
            record["consumed_at_utc"] = _now()
            record["outcome"] = deepcopy(dict(outcome))
            record = self._with_digest(record)
            write_json(
                self._input_dir(task_id, inference_input_id) / "input.json",
                record,
            )
            return self.public(record)


__all__ = [
    "INFERENCE_INPUT_SCHEMA_VERSION",
    "MAX_INFERENCE_INPUT_BYTES",
    "InferenceInputError",
    "InferenceInputStore",
]
