"""Task-owned, explicitly approved model trials, independent of TrainingRun.

The service owns intent and evidence. OCI owns processes; a queued thread or
coordinator message is never proof that a container ran or stopped.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import struct
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .errors import HarnessError
from .io_utils import write_json


MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_TRIALS_PER_TASK = 50
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_TRIAL = re.compile(r"trial-[0-9a-f]{32}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_CONTEXT_FIELDS = {"task_id", "spec_revision", "dataset_id", "model_asset_id", "model_manifest_sha256",
                   "model_sha256", "config_sha256", "model_repo_id", "resolved_commit", "binding_sha256", "archived"}
_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
_ACTIVE = {"queued", "starting", "running", "cancel_requested", "observation_degraded"}
_TRANSITIONS = {
    "pending_approval": {"queued", "cancelled"},
    "queued": {"starting", "cancel_requested", "cancelled", "failed", "observation_degraded"},
    "starting": {"starting", "running", "cancel_requested", "succeeded", "failed", "cancelled", "timed_out", "observation_degraded"},
    "running": {"cancel_requested", "succeeded", "failed", "cancelled", "timed_out", "observation_degraded"},
    "cancel_requested": {"cancel_requested", "cancelled", "failed", "timed_out", "observation_degraded"},
    "observation_degraded": {"observation_degraded", "cancel_requested", "cancelled", "failed", "timed_out"},
}


class ModelTrialError(HarnessError):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(error_code)


class ModelTrialConflictError(ModelTrialError):
    pass


class ModelTrialIntegrityError(ModelTrialError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ModelTrialIntegrityError("invalid_trial_json") from error


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _seal(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    record = deepcopy(dict(value))
    record.pop(key, None)
    record[key] = _sha(_canonical(record))
    return record


def _check(condition: bool, code: str, *, conflict: bool = False) -> None:
    if not condition:
        raise (ModelTrialConflictError if conflict else ModelTrialError)(code)


def _safe_id(value: str, *, trial: bool = False) -> str:
    pattern = _TRIAL if trial else _ID
    _check(isinstance(value, str) and bool(pattern.fullmatch(value)), "invalid_trial_id" if trial else "invalid_task_id")
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        if key in result:
            raise ModelTrialIntegrityError("duplicate_json_key")
        result[key] = value
    return result


def _parse(data: str | bytes) -> Any:
    def invalid_constant(_value: str) -> None:
        raise ModelTrialIntegrityError("nonfinite_json_number")
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ModelTrialIntegrityError("invalid_trial_json") from error


def _finite_number(value: Any) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def _read(path: Path, maximum: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise ModelTrialIntegrityError("unsafe_or_oversized_trial_file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise ModelTrialIntegrityError("oversized_trial_file")
        return data
    except OSError as error:
        raise ModelTrialIntegrityError("unreadable_trial_file") from error


def _write_new(path: Path, data: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ModelTrialIntegrityError("immutable_trial_write_failed") from error


def _input(filename: str, value: bytes) -> dict[str, Any]:
    _check(isinstance(filename, str) and 0 < len(filename) <= 160
           and filename not in {".", ".."} and not any(ord(char) < 32 or char in "/\\" for char in filename), "invalid_input_filename")
    _check(isinstance(value, bytes) and 12 <= len(value) <= MAX_INPUT_BYTES, "invalid_input_size")
    extension = Path(filename).suffix.lower()
    supported = (
        (extension == ".png" and value.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension in {".jpg", ".jpeg"} and value.startswith(b"\xff\xd8\xff"))
        or (extension == ".webp" and value[:4] == b"RIFF" and value[8:12] == b"WEBP")
        or (extension == ".bmp" and value[:2] == b"BM")
    )
    _check(supported, "unsupported_or_mismatched_input_format")
    return {"filename": filename, "sha256": _sha(value), "size_bytes": len(value)}


def _safe_warning(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s\"'<>]+", "[path]", value[:2048])
    return "".join(char for char in text if ord(char) >= 32 or char in "\n\t")[:1024]


def _error_code(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", value) else fallback


class ModelTrialService:
    def __init__(self, root: Path, executor: Any | None,
                 context_provider: Callable[[str], dict],
                 payload_provider: Callable[[str, dict, bytes], bytes],
                 lock: Any | None = None):
        self.root = Path(root).resolve()
        self.executor = executor
        self.context_provider = context_provider
        self.payload_provider = payload_provider
        self._lock = lock if lock is not None else threading.RLock()
        self._startup_lock = threading.Lock()
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._cancel_events: dict[tuple[str, str], threading.Event] = {}
        self._workers: set[tuple[str, str]] = set()
        self._recovering: set[tuple[str, str]] = set()
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False

    def _task_dir(self, task_id: str) -> Path:
        _safe_id(task_id)
        parent = self.root / "tasks"
        path = parent / task_id
        _check(not parent.is_symlink() and not path.is_symlink() and path.is_dir(), "task_not_found")
        _check(path.resolve() == path, "unsafe_task_directory")
        return path

    def _directory(self, task_id: str, trial_id: str) -> Path:
        _safe_id(trial_id, trial=True)
        parent = self._task_dir(task_id) / "model_trials"
        path = parent / trial_id
        _check(not parent.is_symlink() and not path.is_symlink() and path.is_dir(), "trial_not_found")
        _check(path.resolve() == path, "unsafe_trial_directory")
        return path

    def _paths(self, task_id: str) -> list[Path]:
        parent = self._task_dir(task_id) / "model_trials"
        _check(not parent.is_symlink(), "unsafe_trial_directory")
        if not parent.exists():
            return []
        _check(parent.is_dir(), "unsafe_trial_directory")
        paths = sorted(parent.iterdir(), key=lambda path: path.name)
        _check(len(paths) <= MAX_TRIALS_PER_TASK, "trial_count_limit")
        for path in paths:
            _safe_id(path.name, trial=True)
            _check(not path.is_symlink() and path.is_dir(), "unsafe_trial_directory")
        return paths

    def _context(self, task_id: str) -> dict:
        self._task_dir(task_id)
        try:
            context = deepcopy(self.context_provider(task_id))
        except Exception as error:
            raise ModelTrialConflictError("trial_context_unavailable") from error
        _check(isinstance(context, dict) and set(context) == _CONTEXT_FIELDS, "invalid_trial_context")
        _check(context["task_id"] == task_id, "cross_task_context")
        _check(type(context["spec_revision"]) is int and context["spec_revision"] > 0, "invalid_spec_revision")
        _check(type(context["archived"]) is bool, "invalid_archive_context")
        _check(context["dataset_id"] is None or isinstance(context["dataset_id"], str), "invalid_dataset_context")
        for key in ("model_manifest_sha256", "model_sha256", "config_sha256", "binding_sha256"):
            _check(isinstance(context[key], str) and bool(_SHA.fullmatch(context[key])), "invalid_model_context_digest")
        for key in ("model_asset_id", "model_repo_id"):
            _check(isinstance(context[key], str) and 0 < len(context[key]) <= 300, "invalid_model_context_identity")
        _check(isinstance(context["resolved_commit"], str) and bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", context["resolved_commit"])), "invalid_model_commit")
        return context

    @staticmethod
    def _context_match(expected: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        return {key: value for key, value in expected.items() if key != "archived"} == {
            key: value for key, value in current.items() if key != "archived"}

    def _runtime(self) -> tuple[str, dict]:
        _check(self.executor is not None, "trial_runtime_unconfigured")
        try:
            digest = self.executor.runtime_digest
            config = self.executor.config
            limits = {"cpus": 1, "memory_bytes": config.memory_bytes, "timeout_seconds": config.timeout_seconds,
                      "pids_limit": config.pids_limit}
        except Exception as error:
            raise ModelTrialError("invalid_trial_runtime_configuration") from error
        _check(isinstance(digest, str) and bool(_SHA.fullmatch(digest)), "invalid_trial_runtime_digest")
        _check(all(type(value) is int and value > 0 for value in limits.values()), "invalid_trial_limits")
        return digest, limits

    def _load(self, task_id: str, trial_id: str) -> tuple[dict, dict, bytes]:
        directory = self._directory(task_id, trial_id)
        plan = _parse(_read(directory / "plan.json", 65536))
        if not isinstance(plan, dict) or _seal(plan, "plan_sha256") != plan:
            raise ModelTrialIntegrityError("trial_plan_digest_mismatch")
        if plan.get("task_id") != task_id or plan.get("trial_id") != trial_id:
            raise ModelTrialIntegrityError("trial_owner_mismatch")
        if plan.get("schema_version") != "1.0" or plan.get("operation") != "onnx_image_features":
            raise ModelTrialIntegrityError("invalid_trial_plan_type")
        data = _read(directory / "input.blob", MAX_INPUT_BYTES)
        if _input(plan.get("input", {}).get("filename"), data) != plan.get("input"):
            raise ModelTrialIntegrityError("trial_input_digest_mismatch")
        events_dir = directory / "events"
        if events_dir.is_symlink() or not events_dir.is_dir():
            raise ModelTrialIntegrityError("trial_events_missing")
        paths = sorted(events_dir.iterdir(), key=lambda path: path.name)
        if not paths or len(paths) > 10000:
            raise ModelTrialIntegrityError("invalid_trial_event_count")
        history = []
        previous = None
        for revision, path in enumerate(paths, 1):
            if path.name != f"{revision:06d}.json":
                raise ModelTrialIntegrityError("trial_event_sequence_broken")
            state = _parse(_read(path, 1024 * 1024))
            if (not isinstance(state, dict) or _seal(state, "record_sha256") != state
                    or state.get("schema_version") != "1.0" or state.get("task_id") != task_id
                    or state.get("trial_id") != trial_id or state.get("plan_sha256") != plan["plan_sha256"]
                    or state.get("state_revision") != revision
                    or state.get("previous_event_sha256") != (previous["record_sha256"] if previous else None)):
                raise ModelTrialIntegrityError("trial_event_integrity_failed")
            status = state.get("status")
            if (previous is None and status != "pending_approval") or (
                    previous is not None and status not in _TRANSITIONS.get(previous["status"], set())):
                raise ModelTrialIntegrityError("invalid_trial_state_transition")
            history.append(state)
            previous = state
        pointer_path = directory / "state.json"
        if pointer_path.exists() or pointer_path.is_symlink():
            pointer = _parse(_read(pointer_path, 1024 * 1024))
            if pointer not in history:
                raise ModelTrialIntegrityError("trial_state_pointer_mismatch")
        # The append-only event is authoritative when a crash interrupted the
        # following atomic pointer write; this read does not rewrite history.
        return plan, history[-1], data

    def _append(self, plan: dict, previous: dict | None, status: str, **changes: Any) -> dict:
        if previous is not None:
            _check(status in _TRANSITIONS.get(previous["status"], set()), "trial_already_terminal", conflict=True)
            state = {key: deepcopy(value) for key, value in previous.items() if key != "record_sha256"}
        else:
            state = {"schema_version": "1.0", "task_id": plan["task_id"], "trial_id": plan["trial_id"],
                     "plan_sha256": plan["plan_sha256"], "approval": None, "result": None, "evidence": None,
                     "container": None, "error_code": None, "cancel_requested": False, "cancellation": None}
        state.update(changes)
        state.update(status=status, state_revision=(previous["state_revision"] + 1 if previous else 1),
                     previous_event_sha256=previous["record_sha256"] if previous else None, updated_at_utc=_now())
        state = _seal(state, "record_sha256")
        directory = self._directory(plan["task_id"], plan["trial_id"])
        _write_new(directory / "events" / f"{state['state_revision']:06d}.json", _canonical(state))
        if (directory / "state.json").is_symlink():
            raise ModelTrialIntegrityError("unsafe_trial_state_pointer")
        write_json(directory / "state.json", state)
        return state

    def _view(self, plan: dict, state: dict, context: dict | None = None) -> dict:
        reasons = []
        try:
            current = context if context is not None else self._context(plan["task_id"])
            if not self._context_match(plan["context"], current):
                reasons.append("task_context_changed")
            if current["archived"]:
                reasons.append("task_archived")
        except ModelTrialError:
            reasons.append("trial_context_unavailable")
        try:
            runtime, limits = self._runtime()
            if runtime != plan["runtime_digest"] or limits != plan["limits"]:
                reasons.append("runtime_configuration_changed")
        except ModelTrialError:
            reasons.append("trial_runtime_unconfigured")
        record = deepcopy(plan)
        record.update({key: deepcopy(value) for key, value in state.items()
                       if key not in {"schema_version", "task_id", "trial_id", "plan_sha256"}})
        record.update(stale=bool(reasons), stale_reasons=reasons,
                      business_quality_accepted=False, training_run_created=False)
        return record

    def _require_current(self, plan: dict) -> dict:
        context = self._context(plan["task_id"])
        _check(not context["archived"], "task_archived", conflict=True)
        _check(self._context_match(plan["context"], context), "task_context_changed", conflict=True)
        runtime, limits = self._runtime()
        _check(runtime == plan["runtime_digest"] and limits == plan["limits"], "runtime_configuration_changed", conflict=True)
        return context

    def create(self, task_id: str, *, filename: str, input_bytes: bytes, request_id: str,
               parent_trial_id: str | None = None) -> dict:
        metadata = _input(filename, input_bytes)
        _check(isinstance(request_id, str) and bool(_REQUEST.fullmatch(request_id)), "invalid_trial_request_id")
        with self._lock:
            _check(not self._closed, "trial_service_closed")
            context = self._context(task_id)
            _check(not context["archived"], "task_archived", conflict=True)
            runtime, limits = self._runtime()
            paths = self._paths(task_id)
            for path in paths:
                plan, state, _ = self._load(task_id, path.name)
                if plan["request_id"] == request_id:
                    _check(plan["input"] == metadata and self._context_match(plan["context"], context)
                           and plan["runtime_digest"] == runtime and plan["parent_trial_id"] == parent_trial_id,
                           "trial_request_id_conflict", conflict=True)
                    return self._view(plan, state, context)
            _check(len(paths) < MAX_TRIALS_PER_TASK, "trial_count_limit")
            if parent_trial_id is not None:
                parent, parent_state, _ = self._load(task_id, parent_trial_id)
                _check(parent_state["status"] in _TERMINAL, "retry_requires_stopped_parent", conflict=True)
                _check(parent["input"] == metadata, "retry_input_changed", conflict=True)
            trial_id = f"trial-{uuid4().hex}"
            plan = _seal({"schema_version": "1.0", "trial_id": trial_id, "task_id": task_id,
                          "operation": "onnx_image_features", "context": context, "input": metadata,
                          "runtime_digest": runtime, "limits": limits, "request_id": request_id,
                          "parent_trial_id": parent_trial_id, "created_at_utc": _now()}, "plan_sha256")
            parent_dir = self._task_dir(task_id) / "model_trials"
            parent_dir.mkdir(exist_ok=True)
            directory = parent_dir / trial_id
            directory.mkdir()
            (directory / "events").mkdir()
            _write_new(directory / "input.blob", input_bytes)
            _write_new(directory / "plan.json", _canonical(plan))
            state = self._append(plan, None, "pending_approval")
            return self._view(plan, state, context)

    def get(self, task_id: str, trial_id: str) -> dict:
        with self._lock:
            plan, state, _ = self._load(task_id, trial_id)
            return self._view(plan, state)

    def list(self, task_id: str) -> list[dict]:
        with self._lock:
            records = [self.get(task_id, path.name) for path in self._paths(task_id)]
            return sorted(records, key=lambda record: (record["created_at_utc"], record["trial_id"]), reverse=True)

    def read_input(self, task_id: str, trial_id: str) -> bytes:
        with self._lock:
            return self._load(task_id, trial_id)[2]

    @staticmethod
    def _approval(plan: dict, approval: dict) -> dict:
        _check(isinstance(approval, dict) and len(_canonical(approval)) <= 8192, "invalid_trial_approval")
        _check(approval.get("actor") == "user" and approval.get("verified_by") == "agent_bridge_token", "unverified_trial_approval")
        proof = approval.get("bridge_token_sha256")
        _check(isinstance(proof, str) and bool(_SHA.fullmatch(proof)), "invalid_trial_bridge_proof")
        checkpoint = approval.get("checkpoint_id")
        _check(isinstance(checkpoint, str) and 0 < len(checkpoint.strip()) <= 200, "missing_trial_checkpoint")
        _check(approval.get("scope_sha256") == plan["plan_sha256"], "trial_approval_scope_mismatch", conflict=True)
        for key, expected in {**plan["context"], "trial_id": plan["trial_id"], "plan_sha256": plan["plan_sha256"]}.items():
            if key in approval:
                _check(approval[key] == expected, "trial_approval_lineage_mismatch", conflict=True)
        if "context" in approval:
            _check(approval["context"] == plan["context"], "trial_approval_lineage_mismatch", conflict=True)
        if "decision" in approval:
            _check(approval["decision"] == "approved", "trial_approval_not_approved")
        decision = _seal(approval, "approval_sha256")
        if "approval_sha256" in approval:
            _check(approval["approval_sha256"] == decision["approval_sha256"], "trial_approval_digest_mismatch", conflict=True)
        return decision

    def approve_and_start(self, task_id: str, trial_id: str, *, expected_plan_sha256: str, approval: dict) -> dict:
        with self._lock:
            _check(self._started and not self._closed, "trial_service_not_started")
            plan, state, _ = self._load(task_id, trial_id)
            _check(expected_plan_sha256 == plan["plan_sha256"], "trial_plan_digest_changed", conflict=True)
            context = self._require_current(plan)
            decision = self._approval(plan, approval)
            if state["approval"] is not None:
                _check(state["approval"] == decision, "trial_approval_replay_conflict", conflict=True)
                return self._view(plan, state, context)
            _check(state["status"] == "pending_approval", "trial_not_awaiting_approval", conflict=True)
            for path in self._paths(task_id):
                _, other, _ = self._load(task_id, path.name)
                if other["approval"] and other["approval"]["checkpoint_id"] == decision["checkpoint_id"]:
                    raise ModelTrialConflictError("trial_checkpoint_already_consumed")
            state = self._append(plan, state, "queued", approval=decision)
            key = (task_id, trial_id)
            self._cancel_events[key] = threading.Event()
            self._queue.put(key)
            return self._view(plan, state, context)

    def _on_started(self, key: tuple[str, str], information: dict) -> None:
        with self._lock:
            plan, state, _ = self._load(*key)
            _check(state["status"] in {"starting", "running", "cancel_requested"}, "trial_dispatch_state_changed", conflict=True)
            _check(isinstance(information, dict) and information.get("runtime_digest") == plan["runtime_digest"], "worker_runtime_identity_mismatch")
            container_id = information.get("container_id")
            _check(isinstance(container_id, str) and bool(_SHA.fullmatch(container_id)), "invalid_worker_container_identity")
            previous = state.get("container")
            _check(not previous or previous["container_id"] == container_id, "worker_container_identity_changed")
            image_id = information.get("image_id")
            _check(isinstance(image_id, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)), "invalid_worker_image_identity")
            container = {key: information.get(key) for key in ("container_id", "image_id", "runtime_digest", "started_at_utc")}
            status = state["status"] if state["status"] == "cancel_requested" else (
                "running" if information.get("phase") == "running" else "starting")
            self._append(plan, state, status, container=container)

    @staticmethod
    def _result(plan: dict, outcome: dict) -> dict:
        _check(type(outcome.get("exit_code")) is int and outcome["exit_code"] == 0
               and outcome.get("cleanup_confirmed") is True, "trial_execution_not_confirmed")
        stdout = outcome.get("stdout")
        _check(isinstance(stdout, str) and len(stdout.encode("utf-8")) <= 1024 * 1024, "invalid_trial_stdout")
        result = _parse(stdout)
        expected_keys = {"schema_version", "task_id", "trial_id", "plan_sha256", "status", "input_sha256", "model_sha256",
                         "config_sha256", "provider", "features", "classes", "output_sha256", "timing"}
        _check(isinstance(result, dict) and set(result) == expected_keys, "invalid_trial_result_schema")
        expected = {"schema_version": "1.0", "task_id": plan["task_id"], "trial_id": plan["trial_id"],
                    "plan_sha256": plan["plan_sha256"], "status": "succeeded", "input_sha256": plan["input"]["sha256"],
                    "model_sha256": plan["context"]["model_sha256"], "config_sha256": plan["context"]["config_sha256"],
                    "provider": "CPUExecutionProvider"}
        _check(all(result.get(key) == value for key, value in expected.items()), "trial_result_identity_mismatch")
        features, classes = result["features"], result["classes"]
        _check(isinstance(features, list) and 0 < len(features) < 4096 and isinstance(classes, list)
               and len(features) == len(classes), "trial_output_shape_mismatch")
        _check(all(_finite_number(value) for value in features), "trial_output_nonfinite")
        _check(all(isinstance(value, str) and 0 < len(value) <= 256 for value in classes), "invalid_trial_classes")
        try:
            packed = struct.pack(f"<{len(features)}f", *features)
            _check(all(math.isfinite(value) for value in struct.unpack(f"<{len(features)}f", packed)), "trial_float32_nonfinite")
        except (OverflowError, struct.error) as error:
            raise ModelTrialError("trial_float32_overflow") from error
        _check(result["output_sha256"] == _sha(packed), "trial_output_digest_mismatch")
        timing = result["timing"]
        _check(isinstance(timing, dict) and len(timing) <= 32 and all(
            isinstance(key, str) and len(key) <= 100 and ((_finite_number(value) and value >= 0)
            or (isinstance(value, str) and len(value) <= 512)) for key, value in timing.items()), "invalid_trial_timing")
        return {**result, "output_dtype": "float32", "output_shape": [len(features)],
                "business_quality_accepted": False, "training_run_created": False}

    @staticmethod
    def _evidence(outcome: dict) -> dict:
        return {"status": outcome.get("status"), "exit_code": outcome.get("exit_code"),
                "container_id": outcome.get("container_id"), "image_id": outcome.get("image_id"),
                "runtime_digest": outcome.get("runtime_digest"), "cleanup_confirmed": outcome.get("cleanup_confirmed") is True,
                "started_at_utc": outcome.get("started_at_utc"), "finished_at_utc": outcome.get("finished_at_utc"),
                "error_code": _error_code(outcome.get("error_code"), "worker_failed") if outcome.get("error_code") else None,
                "stderr_warning": _safe_warning(outcome.get("stderr"))}

    def _finish(self, key: tuple[str, str], outcome: dict) -> None:
        with self._lock:
            plan, state, _ = self._load(*key)
            if state["status"] in _TERMINAL:
                return
            evidence = self._evidence(outcome)
            result = None
            error_code = evidence["error_code"]
            matching = outcome.get("runtime_digest") == plan["runtime_digest"]
            container = state.get("container")
            if container:
                matching = matching and outcome.get("container_id") == container["container_id"] and outcome.get("image_id") == container["image_id"]
            if not matching or outcome.get("cleanup_confirmed") is not True:
                status = "observation_degraded"
                error_code = "worker_evidence_identity_mismatch" if not matching else error_code or "cleanup_not_confirmed"
            elif state["cancel_requested"] or self._closed:
                status, error_code = "cancelled", error_code or "user_cancelled"
            elif outcome.get("status") == "succeeded":
                try:
                    _check(container is not None, "worker_container_evidence_missing")
                    result = self._result(plan, outcome)
                    status = "succeeded"
                except ModelTrialError as error:
                    status, error_code = "failed", error.error_code
            elif outcome.get("status") in {"failed", "cancelled", "timed_out"}:
                status = outcome["status"]
            else:
                status, error_code = "observation_degraded", error_code or "unknown_worker_outcome"
            self._append(plan, state, status, result=result, evidence=evidence, error_code=error_code)

    def _work(self, key: tuple[str, str]) -> None:
        entered_executor = False
        try:
            with self._lock:
                plan, state, data = self._load(*key)
                if state["status"] in _TERMINAL:
                    return
                if self._closed or state["cancel_requested"]:
                    self._append(plan, state, "cancelled", error_code="cancelled_before_dispatch")
                    return
                self._require_current(plan)
                state = self._append(plan, state, "starting")
                self._workers.add(key)
                event = self._cancel_events.setdefault(key, threading.Event())
                record = self._view(plan, state)
            # Payload validation/materialization may be slow. No task lock is
            # held; cancellation remains immediately available.
            payload = self.payload_provider(key[0], record, data)
            _check(isinstance(payload, bytes) and bool(payload), "invalid_worker_payload")
            with self._lock:
                plan, state, latest_data = self._load(*key)
                self._require_current(plan)
                _check(latest_data == data, "trial_input_digest_mismatch")
                if self._closed or state["cancel_requested"] or event.is_set():
                    self._append(plan, state, "cancelled", error_code="cancelled_before_dispatch")
                    return
                entered_executor = True
            outcome = self.executor.execute(job_id=key[1], task_id=key[0], payload=payload,
                                            cancel_event=event, on_started=lambda information: self._on_started(key, information))
            _check(isinstance(outcome, dict), "invalid_worker_outcome")
            self._finish(key, outcome)
        except Exception as error:
            with self._lock:
                try:
                    plan, state, _ = self._load(*key)
                    if state["status"] not in _TERMINAL:
                        status = "observation_degraded" if entered_executor else ("cancelled" if state["cancel_requested"] else "failed")
                        code = error.error_code if isinstance(error, ModelTrialError) else "trial_dispatch_failed"
                        self._append(plan, state, status, error_code=_error_code(code, "trial_dispatch_failed"))
                except Exception:
                    # Corrupt durable evidence must not be overwritten with a
                    # reassuring terminal state. Future reads fail closed.
                    pass
        finally:
            with self._lock:
                self._workers.discard(key)
                self._cancel_events.pop(key, None)

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                self._work(item)
            finally:
                self._queue.task_done()

    def cancel(self, task_id: str, trial_id: str) -> dict:
        with self._lock:
            plan, state, _ = self._load(task_id, trial_id)
            if state["status"] in _TERMINAL:
                return self._view(plan, state)
            if not state["cancel_requested"]:
                status = "cancelled" if state["status"] == "pending_approval" else (
                    "observation_degraded" if state["status"] == "observation_degraded" else "cancel_requested")
                state = self._append(plan, state, status, cancel_requested=True,
                                     cancellation={"actor": "user", "reason": "user_requested", "requested_at_utc": _now()})
            event = self._cancel_events.get((task_id, trial_id))
            if event:
                event.set()
            return self._view(plan, state)

    def background_actions(self, task_id: str) -> list[dict]:
        with self._lock:
            result = []
            for record in self.list(task_id):
                key = (task_id, record["trial_id"])
                worker = key in self._workers or key in self._recovering
                result.append({"action_id": f"model-trial:{record['trial_id']}", "action_type": "model_trial",
                               "id": record["trial_id"], "trial_id": record["trial_id"], "task_id": task_id,
                               "status": record["status"], "domain_status": record["status"],
                               "running": worker or record["status"] in _ACTIVE, "worker_running": worker,
                               "cancel_requested": record["cancel_requested"], "cancel": record["cancellation"],
                               "updated_at_utc": record["updated_at_utc"], "event_seq": record["state_revision"]})
            return result

    def reconcile(self, task_id: str, trial_id: str) -> dict:
        key = (task_id, trial_id)
        with self._lock:
            plan, state, _ = self._load(*key)
            if state["status"] in _TERMINAL or state["status"] == "pending_approval":
                return self._view(plan, state)
            if key in self._workers or key in self._recovering:
                return self._view(plan, state)
            if state["status"] == "queued" and state.get("container") is None:
                state = self._append(plan, state, "cancelled", error_code="service_restarted_before_dispatch", cancel_requested=True,
                                     cancellation={"actor": "system", "reason": "service_restarted", "requested_at_utc": _now()})
                return self._view(plan, state)
            try:
                runtime, _ = self._runtime()
                _check(runtime == plan["runtime_digest"], "runtime_configuration_changed")
            except ModelTrialError as error:
                state = self._append(plan, state, "observation_degraded", error_code=error.error_code)
                return self._view(plan, state)
            self._recovering.add(key)
        try:
            outcome = self.executor.recover(job_id=trial_id, task_id=task_id)
            _check(isinstance(outcome, dict), "invalid_recovery_outcome")
            with self._lock:
                plan, state, _ = self._load(*key)
                container = state.get("container")
                identity_ok = outcome.get("runtime_digest") == plan["runtime_digest"] and (
                    not container or outcome.get("container_id") in {None, container["container_id"]})
                if identity_ok and outcome.get("cleanup_confirmed") is True:
                    state = self._append(plan, state, "cancelled", cancel_requested=True,
                                         error_code="interrupted_execution_stopped", evidence=self._evidence(outcome),
                                         cancellation=state.get("cancellation") or {"actor": "system", "reason": "recovery_stop", "requested_at_utc": _now()})
                else:
                    state = self._append(plan, state, "observation_degraded", error_code="recovery_cleanup_unconfirmed", evidence=self._evidence(outcome))
                return self._view(plan, state)
        except Exception:
            with self._lock:
                plan, state, _ = self._load(*key)
                state = self._append(plan, state, "observation_degraded", error_code="recovery_observation_failed")
                return self._view(plan, state)
        finally:
            with self._lock:
                self._recovering.discard(key)

    def start(self) -> None:
        # Recovery may perform bounded OCI observation outside the task lock;
        # simultaneous startup callers must not create a second consumer.
        with self._startup_lock:
            self._start_once()

    def _start_once(self) -> None:
        with self._lock:
            _check(not self._closed, "trial_service_closed")
            if self._started:
                return
            candidates = []
            tasks_dir = self.root / "tasks"
            if tasks_dir.is_dir() and not tasks_dir.is_symlink():
                for task_dir in sorted(tasks_dir.iterdir()):
                    if task_dir.is_dir() and not task_dir.is_symlink():
                        for path in self._paths(task_dir.name):
                            plan, state, _ = self._load(task_dir.name, path.name)
                            if state["status"] in _ACTIVE:
                                candidates.append((plan["task_id"], plan["trial_id"]))
        # Called only after the server has acquired the workspace lease. Never
        # restart work during recovery, including a queued, already-used grant.
        for task_id, trial_id in candidates:
            self.reconcile(task_id, trial_id)
        with self._lock:
            _check(not self._closed, "trial_service_closed")
            self._started = True
            self._thread = threading.Thread(target=self._loop, name="model-trial-worker", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 20.0) -> None:
        _check(isinstance(timeout, (int, float)) and 0 <= timeout <= 30, "invalid_shutdown_timeout")
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for key, event in list(self._cancel_events.items()):
                event.set()
                try:
                    plan, state, _ = self._load(*key)
                    if state["status"] in _ACTIVE:
                        status = "cancel_requested" if key in self._workers else "cancelled"
                        self._append(plan, state, status, cancel_requested=True, error_code="service_shutdown",
                                     cancellation={"actor": "system", "reason": "service_shutdown", "requested_at_utc": _now()})
                except ModelTrialError:
                    pass
            self._queue.put(None)
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._lock:
            for key in list(self._workers):
                try:
                    plan, state, _ = self._load(*key)
                    if state["status"] in _ACTIVE:
                        self._append(plan, state, "observation_degraded", error_code="shutdown_stop_unconfirmed")
                except ModelTrialError:
                    pass
