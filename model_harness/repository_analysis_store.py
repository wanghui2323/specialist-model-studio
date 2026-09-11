from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json


_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_ALLOWED_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
}


class RepositoryAnalysisIntegrityError(ContractError):
    """Raised when an immutable analysis lifecycle record fails verification."""


class StaleAnalysisAttemptError(ContractError):
    """Raised when a caller tries to mutate an attempt that is no longer current."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("analysis lifecycle value must be canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


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


def _safe_id(value: str, label: str) -> str:
    selected = str(value)
    if not _RECORD_ID.fullmatch(selected):
        raise ContractError(f"invalid {label}")
    return selected


def _safe_digest(value: str, label: str) -> str:
    selected = str(value).strip().lower()
    if not _SHA256.fullmatch(selected):
        raise ContractError(f"invalid {label}")
    return selected


def _safe_text(value: Any, label: str, maximum: int = 1024) -> str:
    selected = str(value or "").strip()
    if (
        not selected
        or len(selected) > maximum
        or any(ord(character) < 32 for character in selected)
    ):
        raise ContractError(f"invalid {label}")
    return selected


def _safe_message(value: Any, label: str, maximum: int = 1024) -> str:
    """Normalize exception text so recording a failure cannot itself fail."""

    selected = " ".join(str(value or "").split())
    if not selected or len(selected) > maximum:
        raise ContractError(f"invalid {label}")
    return selected


def _json_mapping(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    selected = deepcopy(dict(value))
    _canonical(selected)
    return selected


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    record = deepcopy(dict(value))
    if "content_digest" in record:
        raise RepositoryAnalysisIntegrityError("content_digest is store-owned")
    record["content_digest"] = _digest(record)
    return record


def _verified(value: Any, expected_type: str, source: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryAnalysisIntegrityError(f"invalid record at {source}")
    supplied = value.get("content_digest")
    unsigned = {key: item for key, item in value.items() if key != "content_digest"}
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise RepositoryAnalysisIntegrityError(
            f"analysis lifecycle digest mismatch at {source}"
        )
    if value.get("object_type") != expected_type:
        raise RepositoryAnalysisIntegrityError(
            f"analysis lifecycle type mismatch at {source}"
        )
    return deepcopy(value)


@dataclass(frozen=True)
class AnalysisAttempt:
    schema_version: str
    object_type: str
    attempt_id: str
    task_id: str
    snapshot_id: str
    snapshot_digest: str
    expected_resolved_commit: str
    attempt_sequence: int
    retry_of_attempt_id: str | None
    retry_of_attempt_digest: str | None
    analyzer_version: str
    manual_mapping_revision_id: str | None
    manual_mapping_digest: str | None
    initial_status: str
    execution_policy: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BindingAnalysisAttempt:
    schema_version: str
    object_type: str
    attempt_id: str
    task_id: str
    resolution_id: str
    resolution_digest: str
    expected_resolved_commit: str
    base_spec_revision: int
    analyzer_version: str
    attempt_sequence: int
    retry_of_attempt_id: str | None
    retry_of_attempt_digest: str | None
    initial_status: str
    execution_policy: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisFailureEvidence:
    stage: str
    code: str
    message: str
    retryable: bool
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManualMappingRevision:
    schema_version: str
    object_type: str
    mapping_revision_id: str
    task_id: str
    snapshot_id: str
    snapshot_digest: str
    revision: int
    supersedes_revision_id: str | None
    supersedes_revision_digest: str | None
    mapping: dict[str, Any]
    mapping_digest: str
    created_by: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RepositoryAnalysisStore:
    """Append-only lifecycle storage for static repository analysis.

    An ``AnalysisAttempt`` is an immutable identity record. Its lifecycle is an
    append-only chain of ``AnalysisAttemptState`` events. A replaceable
    ``current.json`` file is only a verified index to immutable pointer
    revisions; it is never the sole source of truth. The store serializes
    already-produced static analysis facts and never imports, installs, or
    executes repository content.
    """

    SCHEMA_VERSION = "0.1"
    EXECUTION_POLICY = "static_only_never_execute"

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        tasks_candidate = self.root / "tasks"
        if tasks_candidate.is_symlink():
            raise ContractError("tasks directory cannot be a symlink")
        tasks_candidate.mkdir(parents=True, exist_ok=True)
        self.tasks_dir = tasks_candidate.resolve()
        self._lock = RLock()

    def create_attempt(
        self,
        task_id: str,
        *,
        snapshot_id: str,
        snapshot_digest: str,
        expected_resolved_commit: str,
        analyzer_version: str,
        retry_of_attempt_id: str | None = None,
        manual_mapping_revision_id: str | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_snapshot = _safe_id(snapshot_id, "snapshot id")
        selected_snapshot_digest = _safe_digest(
            snapshot_digest, "snapshot digest"
        )
        selected_commit = str(expected_resolved_commit).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", selected_commit):
            raise ContractError("invalid expected resolved commit")
        selected_analyzer = _safe_text(
            analyzer_version, "analyzer version", maximum=160
        )

        with self._lock:
            existing_attempts = self.list_attempts(
                selected_task, snapshot_id=selected_snapshot
            )
            retry_record: dict[str, Any] | None = None
            if retry_of_attempt_id is not None:
                retry_record = self.get_attempt_record(
                    selected_task, retry_of_attempt_id
                )
                if retry_record["snapshot_id"] != selected_snapshot:
                    raise ContractError("retry attempt must use the same snapshot")
                if retry_record["snapshot_digest"] != selected_snapshot_digest:
                    raise ContractError("retry snapshot digest changed")
                retry_state = self.get_attempt(
                    selected_task, retry_record["attempt_id"]
                )["current_state"]
                retry_commit = retry_record.get("expected_resolved_commit")
                if retry_commit is None:
                    retry_result = retry_state.get("result")
                    retry_analysis = (
                        retry_result.get("analysis")
                        if isinstance(retry_result, Mapping)
                        else None
                    )
                    if isinstance(retry_analysis, Mapping):
                        retry_commit = retry_analysis.get("resolved_commit")
                if retry_commit is not None and retry_commit != selected_commit:
                    raise ContractError("retry resolved commit changed")
                if retry_state["status"] not in _TERMINAL_STATUSES:
                    raise ContractError("only a terminal analysis attempt can be retried")
                current = self._current_pointer(selected_task, selected_snapshot)
                if current is None or current["attempt_id"] != retry_record["attempt_id"]:
                    raise StaleAnalysisAttemptError(
                        "only the current analysis attempt can be retried"
                    )
            elif existing_attempts:
                raise ContractError(
                    "subsequent analysis attempts must identify the retry source"
                )

            mapping_record: dict[str, Any] | None = None
            if manual_mapping_revision_id is not None:
                mapping_record = self.get_manual_mapping_revision(
                    selected_task, manual_mapping_revision_id
                )
                if mapping_record["snapshot_id"] != selected_snapshot:
                    raise ContractError("manual mapping describes another snapshot")
                if mapping_record["snapshot_digest"] != selected_snapshot_digest:
                    raise ContractError("manual mapping snapshot digest changed")

            sequence = self._next_attempt_sequence(
                selected_task, selected_snapshot
            )
            attempt_id = (
                f"analysis-attempt-r{sequence}-{uuid4().hex[:12]}"
            )
            attempt = AnalysisAttempt(
                schema_version=self.SCHEMA_VERSION,
                object_type="AnalysisAttempt",
                attempt_id=attempt_id,
                task_id=selected_task,
                snapshot_id=selected_snapshot,
                snapshot_digest=selected_snapshot_digest,
                expected_resolved_commit=selected_commit,
                attempt_sequence=sequence,
                retry_of_attempt_id=(
                    retry_record["attempt_id"] if retry_record else None
                ),
                retry_of_attempt_digest=(
                    retry_record["content_digest"] if retry_record else None
                ),
                analyzer_version=selected_analyzer,
                manual_mapping_revision_id=(
                    mapping_record["mapping_revision_id"] if mapping_record else None
                ),
                manual_mapping_digest=(
                    mapping_record["content_digest"] if mapping_record else None
                ),
                initial_status="queued",
                execution_policy=self.EXECUTION_POLICY,
                created_at_utc=_now(),
            )
            attempt_record = _sealed(attempt.to_dict())
            self._write_immutable(
                self._attempt_path(selected_task, attempt_id),
                attempt_record,
                "AnalysisAttempt",
            )
            queued = self._append_state(
                attempt_record,
                status="queued",
                previous=None,
            )
            pointer = self._append_pointer(
                selected_task,
                selected_snapshot,
                attempt_record,
                queued,
                reason="attempt_created",
            )
            return self._projection(attempt_record, queued, pointer)

    def retry(
        self,
        task_id: str,
        attempt_id: str,
        *,
        analyzer_version: str | None = None,
        manual_mapping_revision_id: str | None = None,
        expected_resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        previous = self.get_attempt_record(task_id, attempt_id)
        selected_commit = (
            expected_resolved_commit
            if expected_resolved_commit is not None
            else previous.get("expected_resolved_commit")
        )
        if selected_commit is None:
            previous_state = self.get_attempt(task_id, attempt_id)["current_state"]
            previous_result = previous_state.get("result")
            previous_analysis = (
                previous_result.get("analysis")
                if isinstance(previous_result, Mapping)
                else None
            )
            if isinstance(previous_analysis, Mapping):
                selected_commit = previous_analysis.get("resolved_commit")
        if selected_commit is None:
            raise ContractError(
                "legacy analysis attempt requires expected resolved commit for retry"
            )
        return self.create_attempt(
            task_id,
            snapshot_id=previous["snapshot_id"],
            snapshot_digest=previous["snapshot_digest"],
            expected_resolved_commit=str(selected_commit),
            analyzer_version=analyzer_version or previous["analyzer_version"],
            retry_of_attempt_id=previous["attempt_id"],
            manual_mapping_revision_id=(
                manual_mapping_revision_id
                if manual_mapping_revision_id is not None
                else previous["manual_mapping_revision_id"]
            ),
        )

    def mark_running(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        return self._transition(task_id, attempt_id, status="running")

    def complete(
        self,
        task_id: str,
        attempt_id: str,
        *,
        analysis: Mapping[str, Any],
    ) -> dict[str, Any]:
        selected_analysis = _json_mapping(analysis, "analysis")
        if not selected_analysis:
            raise ContractError("analysis must not be empty")
        supplied_policy = selected_analysis.get("execution_policy")
        if supplied_policy not in {None, self.EXECUTION_POLICY}:
            raise ContractError("analysis result has an unsafe execution policy")
        attempt = self.get_attempt_record(task_id, attempt_id)
        expected_commit = attempt.get("expected_resolved_commit")
        if expected_commit is None:
            raise ContractError(
                "legacy analysis attempt lacks expected resolved commit; retry is required"
            )
        expected_identity = {
            "task_id": attempt["task_id"],
            "source_snapshot_id": attempt["snapshot_id"],
            "resolved_commit": expected_commit,
            "analyzer_version": attempt["analyzer_version"],
        }
        for field, expected in expected_identity.items():
            if selected_analysis.get(field) != expected:
                raise ContractError(
                    f"analysis result {field} does not match immutable attempt"
                )
        return self._transition(
            task_id,
            attempt_id,
            status="completed",
            result={
                "analysis": selected_analysis,
                "analysis_digest": _digest(selected_analysis),
            },
        )

    def fail(
        self,
        task_id: str,
        attempt_id: str,
        *,
        stage: str,
        code: str,
        message: str,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(retryable, bool):
            raise ContractError("retryable must be boolean")
        evidence = AnalysisFailureEvidence(
            stage=_safe_text(stage, "failure stage", maximum=120),
            code=_safe_text(code, "failure code", maximum=160),
            message=_safe_message(message, "failure message", maximum=1000),
            retryable=retryable,
            details=_json_mapping(details or {}, "failure details"),
        )
        return self._transition(
            task_id,
            attempt_id,
            status="failed",
            failure=evidence.to_dict(),
        )

    def cancel(
        self,
        task_id: str,
        attempt_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self._transition(
            task_id,
            attempt_id,
            status="cancelled",
            cancellation={
                "reason": _safe_message(
                    reason, "cancellation reason", maximum=500
                )
            },
        )

    def get_attempt_record(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_attempt = _safe_id(attempt_id, "analysis attempt id")
        path = self._attempt_path(selected_task, selected_attempt)
        if not path.is_file():
            raise FileNotFoundError("analysis attempt not found")
        record = self._read_record(path, "AnalysisAttempt", selected_task)
        if record["attempt_id"] != selected_attempt:
            raise RepositoryAnalysisIntegrityError("analysis attempt identity mismatch")
        return record

    def get_attempt(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        attempt = self.get_attempt_record(task_id, attempt_id)
        states = self._states(attempt)
        if not states:
            raise RepositoryAnalysisIntegrityError("analysis attempt has no state")
        pointer = self._current_pointer(
            attempt["task_id"], attempt["snapshot_id"]
        )
        if pointer is not None and pointer["attempt_id"] != attempt["attempt_id"]:
            pointer = None
        return self._projection(attempt, states[-1], pointer)

    def current_attempt(
        self, task_id: str, snapshot_id: str
    ) -> dict[str, Any] | None:
        selected_task = _safe_task_id(task_id)
        selected_snapshot = _safe_id(snapshot_id, "snapshot id")
        with self._lock:
            pointer = self._current_pointer(selected_task, selected_snapshot)
            if pointer is None:
                return None
            attempt = self.get_attempt_record(
                selected_task, pointer["attempt_id"]
            )
            states = self._states(attempt)
            state = states[-1]
            if state["content_digest"] != pointer["state_digest"]:
                raise RepositoryAnalysisIntegrityError(
                    "current analysis pointer does not reference latest state"
                )
            return self._projection(attempt, state, pointer)

    def list_attempts(
        self, task_id: str, *, snapshot_id: str | None = None
    ) -> list[dict[str, Any]]:
        selected_task = _safe_task_id(task_id)
        selected_snapshot = (
            _safe_id(snapshot_id, "snapshot id") if snapshot_id is not None else None
        )
        records: list[dict[str, Any]] = []
        for path in sorted(self._attempts_dir(selected_task).glob("*/attempt.json")):
            record = self._read_record(path, "AnalysisAttempt", selected_task)
            if selected_snapshot is None or record["snapshot_id"] == selected_snapshot:
                records.append(record)
        records = sorted(
            records,
            key=lambda item: (
                item["snapshot_id"],
                int(item["attempt_sequence"]),
                item["attempt_id"],
            ),
        )
        previous_by_snapshot: dict[str, dict[str, Any]] = {}
        expected_by_snapshot: dict[str, int] = {}
        for record in records:
            snapshot = str(record["snapshot_id"])
            expected = expected_by_snapshot.get(snapshot, 1)
            if record["attempt_sequence"] != expected:
                raise RepositoryAnalysisIntegrityError(
                    "analysis attempt sequence is broken"
                )
            previous = previous_by_snapshot.get(snapshot)
            if record["retry_of_attempt_id"] != (
                previous["attempt_id"] if previous else None
            ) or record["retry_of_attempt_digest"] != (
                previous["content_digest"] if previous else None
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis attempt retry chain is broken"
                )
            if (
                previous is not None
                and record["snapshot_digest"] != previous["snapshot_digest"]
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis attempt snapshot digest changed"
                )
            if (
                previous is not None
                and previous.get("expected_resolved_commit") is not None
                and record.get("expected_resolved_commit")
                != previous.get("expected_resolved_commit")
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis attempt resolved commit changed"
                )
            previous_by_snapshot[snapshot] = record
            expected_by_snapshot[snapshot] = expected + 1
        return records

    def create_manual_mapping_revision(
        self,
        task_id: str,
        *,
        snapshot_id: str,
        snapshot_digest: str,
        mapping: Mapping[str, Any],
        created_by: str = "user",
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_snapshot = _safe_id(snapshot_id, "snapshot id")
        selected_snapshot_digest = _safe_digest(
            snapshot_digest, "snapshot digest"
        )
        selected_mapping = _json_mapping(mapping, "manual mapping")
        if not selected_mapping:
            raise ContractError("manual mapping must not be empty")
        selected_creator = _safe_text(created_by, "mapping creator", maximum=120)

        with self._lock:
            revisions = self.list_manual_mapping_revisions(
                selected_task, selected_snapshot
            )
            previous = revisions[-1] if revisions else None
            if (
                previous is not None
                and previous["snapshot_digest"] != selected_snapshot_digest
            ):
                raise ContractError("manual mapping snapshot digest changed")
            revision = int(previous["revision"]) + 1 if previous else 1
            mapping_digest = _digest(selected_mapping)
            mapping_id = f"analysis-mapping-r{revision}-{uuid4().hex[:12]}"
            record = ManualMappingRevision(
                schema_version=self.SCHEMA_VERSION,
                object_type="ManualMappingRevision",
                mapping_revision_id=mapping_id,
                task_id=selected_task,
                snapshot_id=selected_snapshot,
                snapshot_digest=selected_snapshot_digest,
                revision=revision,
                supersedes_revision_id=(
                    previous["mapping_revision_id"] if previous else None
                ),
                supersedes_revision_digest=(
                    previous["content_digest"] if previous else None
                ),
                mapping=selected_mapping,
                mapping_digest=mapping_digest,
                created_by=selected_creator,
                created_at_utc=_now(),
            )
            sealed = _sealed(record.to_dict())
            self._write_immutable(
                self._mapping_path(selected_task, mapping_id),
                sealed,
                "ManualMappingRevision",
            )
            return sealed

    def get_manual_mapping_revision(
        self, task_id: str, mapping_revision_id: str
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_mapping = _safe_id(mapping_revision_id, "mapping revision id")
        path = self._mapping_path(selected_task, selected_mapping)
        if not path.is_file():
            raise FileNotFoundError("manual mapping revision not found")
        record = self._read_record(path, "ManualMappingRevision", selected_task)
        if record["mapping_revision_id"] != selected_mapping:
            raise RepositoryAnalysisIntegrityError("manual mapping identity mismatch")
        if record["mapping_digest"] != _digest(record["mapping"]):
            raise RepositoryAnalysisIntegrityError("manual mapping digest mismatch")
        return record

    def list_manual_mapping_revisions(
        self, task_id: str, snapshot_id: str
    ) -> list[dict[str, Any]]:
        selected_task = _safe_task_id(task_id)
        selected_snapshot = _safe_id(snapshot_id, "snapshot id")
        records: list[dict[str, Any]] = []
        for path in sorted(self._mappings_dir(selected_task).glob("*.json")):
            record = self._read_record(path, "ManualMappingRevision", selected_task)
            if record["snapshot_id"] == selected_snapshot:
                if record["mapping_digest"] != _digest(record["mapping"]):
                    raise RepositoryAnalysisIntegrityError(
                        "manual mapping digest mismatch"
                    )
                records.append(record)
        records.sort(key=lambda item: (int(item["revision"]), item["mapping_revision_id"]))
        previous: dict[str, Any] | None = None
        for expected_revision, record in enumerate(records, start=1):
            if record["revision"] != expected_revision:
                raise RepositoryAnalysisIntegrityError(
                    "manual mapping revision sequence is broken"
                )
            if record["supersedes_revision_id"] != (
                previous["mapping_revision_id"] if previous else None
            ) or record["supersedes_revision_digest"] != (
                previous["content_digest"] if previous else None
            ):
                raise RepositoryAnalysisIntegrityError(
                    "manual mapping revision chain is broken"
                )
            previous = record
        return records

    def current_manual_mapping(
        self, task_id: str, snapshot_id: str
    ) -> dict[str, Any] | None:
        revisions = self.list_manual_mapping_revisions(task_id, snapshot_id)
        return revisions[-1] if revisions else None

    def _transition(
        self,
        task_id: str,
        attempt_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
        cancellation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_attempt = _safe_id(attempt_id, "analysis attempt id")
        selected_status = str(status).strip().lower()
        if selected_status not in _STATUSES - {"queued"}:
            raise ContractError("invalid analysis attempt status")

        with self._lock:
            attempt = self.get_attempt_record(selected_task, selected_attempt)
            pointer = self._current_pointer(selected_task, attempt["snapshot_id"])
            if pointer is None or pointer["attempt_id"] != selected_attempt:
                raise StaleAnalysisAttemptError("analysis attempt is no longer current")
            states = self._states(attempt)
            previous = states[-1]
            if selected_status not in _ALLOWED_TRANSITIONS.get(
                previous["status"], set()
            ):
                raise ContractError(
                    f"invalid analysis transition {previous['status']} -> {selected_status}"
                )
            state = self._append_state(
                attempt,
                status=selected_status,
                previous=previous,
                result=result,
                failure=failure,
                cancellation=cancellation,
            )
            next_pointer = self._append_pointer(
                selected_task,
                attempt["snapshot_id"],
                attempt,
                state,
                reason=f"status_{selected_status}",
            )
            return self._projection(attempt, state, next_pointer)

    def _append_state(
        self,
        attempt: Mapping[str, Any],
        *,
        status: str,
        previous: Mapping[str, Any] | None,
        result: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
        cancellation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision = int(previous["state_revision"]) + 1 if previous else 1
        semantic = {
            "task_id": attempt["task_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_digest": attempt["content_digest"],
            "state_revision": revision,
            "previous_event_id": previous["event_id"] if previous else None,
            "previous_event_digest": (
                previous["content_digest"] if previous else None
            ),
            "status": status,
            "result": deepcopy(dict(result)) if result is not None else None,
            "failure": deepcopy(dict(failure)) if failure is not None else None,
            "cancellation": (
                deepcopy(dict(cancellation)) if cancellation is not None else None
            ),
        }
        self._validate_state_payload(semantic)
        semantic_digest = _digest(semantic)
        event_id = (
            f"{attempt['attempt_id']}-s{revision}-{status}-{semantic_digest[:10]}"
        )
        record = _sealed(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "AnalysisAttemptState",
                "event_id": event_id,
                **semantic,
                "semantic_digest": semantic_digest,
                "created_at_utc": _now(),
            }
        )
        self._write_immutable(
            self._state_path(attempt["task_id"], attempt["attempt_id"], event_id),
            record,
            "AnalysisAttemptState",
        )
        return record

    def _validate_state_payload(self, value: Mapping[str, Any]) -> None:
        status = value["status"]
        has_result = value["result"] is not None
        has_failure = value["failure"] is not None
        has_cancellation = value["cancellation"] is not None
        if status == "completed" and not has_result:
            raise ContractError("completed analysis state requires a result")
        if status == "failed" and not has_failure:
            raise ContractError("failed analysis state requires failure evidence")
        if status == "cancelled" and not has_cancellation:
            raise ContractError("cancelled analysis state requires a reason")
        expected_count = int(status == "completed") + int(status == "failed") + int(
            status == "cancelled"
        )
        if int(has_result) + int(has_failure) + int(has_cancellation) != expected_count:
            raise ContractError("analysis state payload does not match status")
        _canonical(value)

    def _states(self, attempt: Mapping[str, Any]) -> list[dict[str, Any]]:
        paths = sorted(
            self._states_dir(attempt["task_id"], attempt["attempt_id"]).glob("*.json")
        )
        states = [
            self._read_record(path, "AnalysisAttemptState", attempt["task_id"])
            for path in paths
        ]
        states.sort(key=lambda item: (int(item["state_revision"]), item["event_id"]))
        previous: dict[str, Any] | None = None
        for expected_revision, state in enumerate(states, start=1):
            if state["attempt_id"] != attempt["attempt_id"]:
                raise RepositoryAnalysisIntegrityError(
                    "analysis state attempt identity mismatch"
                )
            if state["attempt_digest"] != attempt["content_digest"]:
                raise RepositoryAnalysisIntegrityError(
                    "analysis state attempt digest mismatch"
                )
            if state["state_revision"] != expected_revision:
                raise RepositoryAnalysisIntegrityError(
                    "analysis state revision sequence is broken"
                )
            if state["previous_event_id"] != (
                previous["event_id"] if previous else None
            ) or state["previous_event_digest"] != (
                previous["content_digest"] if previous else None
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis state chain is broken"
                )
            if previous is None and state["status"] != attempt["initial_status"]:
                raise RepositoryAnalysisIntegrityError(
                    "analysis attempt must start queued"
                )
            if previous is not None and state["status"] not in _ALLOWED_TRANSITIONS.get(
                previous["status"], set()
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis state transition is invalid"
                )
            self._validate_state_payload(state)
            previous = state
        return states

    def _append_pointer(
        self,
        task_id: str,
        snapshot_id: str,
        attempt: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        revisions = self._pointer_revisions(task_id, snapshot_id)
        previous = revisions[-1] if revisions else None
        revision = int(previous["pointer_revision"]) + 1 if previous else 1
        semantic = {
            "task_id": task_id,
            "snapshot_id": snapshot_id,
            "pointer_revision": revision,
            "previous_pointer_id": previous["pointer_id"] if previous else None,
            "previous_pointer_digest": (
                previous["content_digest"] if previous else None
            ),
            "attempt_id": attempt["attempt_id"],
            "attempt_digest": attempt["content_digest"],
            "attempt_sequence": attempt["attempt_sequence"],
            "state_event_id": state["event_id"],
            "state_digest": state["content_digest"],
            "state_revision": state["state_revision"],
            "status": state["status"],
            "selection_reason": _safe_text(reason, "pointer reason", maximum=120),
        }
        semantic_digest = _digest(semantic)
        pointer_id = f"analysis-pointer-r{revision}-{semantic_digest[:12]}"
        pointer = _sealed(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "RepositoryAnalysisPointerRevision",
                "pointer_id": pointer_id,
                **semantic,
                "semantic_digest": semantic_digest,
                "created_at_utc": _now(),
            }
        )
        self._write_immutable(
            self._pointer_revision_path(task_id, snapshot_id, pointer_id),
            pointer,
            "RepositoryAnalysisPointerRevision",
        )
        write_json(self._current_pointer_path(task_id, snapshot_id), pointer)
        return pointer

    def _pointer_revisions(
        self, task_id: str, snapshot_id: str
    ) -> list[dict[str, Any]]:
        records = [
            self._read_record(path, "RepositoryAnalysisPointerRevision", task_id)
            for path in sorted(
                self._pointer_revisions_dir(task_id, snapshot_id).glob("*.json")
            )
        ]
        records.sort(key=lambda item: (int(item["pointer_revision"]), item["pointer_id"]))
        previous: dict[str, Any] | None = None
        for expected_revision, record in enumerate(records, start=1):
            if record["snapshot_id"] != snapshot_id:
                raise RepositoryAnalysisIntegrityError(
                    "analysis pointer snapshot identity mismatch"
                )
            if record["pointer_revision"] != expected_revision:
                raise RepositoryAnalysisIntegrityError(
                    "analysis pointer revision sequence is broken"
                )
            if record["previous_pointer_id"] != (
                previous["pointer_id"] if previous else None
            ) or record["previous_pointer_digest"] != (
                previous["content_digest"] if previous else None
            ):
                raise RepositoryAnalysisIntegrityError(
                    "analysis pointer chain is broken"
                )
            previous = record
        return records

    def _current_pointer(
        self, task_id: str, snapshot_id: str
    ) -> dict[str, Any] | None:
        revisions = self._pointer_revisions(task_id, snapshot_id)
        current_path = self._current_pointer_path(task_id, snapshot_id)
        current: dict[str, Any] | None = None
        if current_path.is_symlink() or (
            current_path.exists() and not current_path.is_file()
        ):
            raise RepositoryAnalysisIntegrityError(
                "current analysis pointer path changed"
            )
        if current_path.is_file():
            if not revisions:
                raise RepositoryAnalysisIntegrityError(
                    "current analysis pointer exists without immutable revisions"
                )
            current = self._read_record(
                current_path, "RepositoryAnalysisPointerRevision", task_id
            )
            if not any(
                item["content_digest"] == current["content_digest"]
                for item in revisions
            ):
                raise RepositoryAnalysisIntegrityError(
                    "current analysis pointer has no immutable revision"
                )

        attempts = self.list_attempts(task_id, snapshot_id=snapshot_id)
        if not attempts:
            if revisions:
                raise RepositoryAnalysisIntegrityError(
                    "analysis pointer exists without an analysis attempt"
                )
            return None
        latest_attempt = attempts[-1]
        states = self._states(latest_attempt)
        if not states:
            states = [
                self._append_state(
                    latest_attempt,
                    status="queued",
                    previous=None,
                )
            ]
        latest_state = states[-1]

        if not revisions:
            latest = self._append_pointer(
                task_id,
                snapshot_id,
                latest_attempt,
                latest_state,
                reason="recovered_after_restart",
            )
            return latest

        latest = revisions[-1]
        self._verify_pointer_target(latest)
        if (
            latest["attempt_id"] != latest_attempt["attempt_id"]
            or latest["state_digest"] != latest_state["content_digest"]
        ):
            latest = self._append_pointer(
                task_id,
                snapshot_id,
                latest_attempt,
                latest_state,
                reason="recovered_after_restart",
            )
        if current is None or current["content_digest"] != latest["content_digest"]:
            write_json(current_path, latest)
        return latest

    def _verify_pointer_target(self, pointer: Mapping[str, Any]) -> None:
        attempt = self.get_attempt_record(pointer["task_id"], pointer["attempt_id"])
        if attempt["content_digest"] != pointer["attempt_digest"]:
            raise RepositoryAnalysisIntegrityError(
                "analysis pointer attempt digest mismatch"
            )
        states = self._states(attempt)
        matching = [
            item for item in states if item["event_id"] == pointer["state_event_id"]
        ]
        if len(matching) != 1 or matching[0]["content_digest"] != pointer["state_digest"]:
            raise RepositoryAnalysisIntegrityError(
                "analysis pointer state digest mismatch"
            )

    def _projection(
        self,
        attempt: Mapping[str, Any],
        state: Mapping[str, Any],
        pointer: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "attempt": deepcopy(dict(attempt)),
            "current_state": deepcopy(dict(state)),
            "pointer": deepcopy(dict(pointer)) if pointer is not None else None,
        }

    def _next_attempt_sequence(self, task_id: str, snapshot_id: str) -> int:
        attempts = self.list_attempts(task_id, snapshot_id=snapshot_id)
        return max((int(item["attempt_sequence"]) for item in attempts), default=0) + 1

    def _task_dir(self, task_id: str) -> Path:
        selected_task = _safe_task_id(task_id)
        task_root = self._owned_dir(
            self.tasks_dir, selected_task, "analysis task directory"
        )
        return self._owned_dir(
            task_root,
            "repository_analysis_lifecycle",
            "repository analysis directory",
        )

    def _attempts_dir(self, task_id: str) -> Path:
        return self._owned_dir(
            self._task_dir(task_id), "attempts", "analysis attempts directory"
        )

    def _attempt_path(self, task_id: str, attempt_id: str) -> Path:
        selected_attempt = _safe_id(attempt_id, "analysis attempt id")
        directory = self._owned_dir(
            self._attempts_dir(task_id),
            selected_attempt,
            "analysis attempt directory",
        )
        return directory / "attempt.json"

    def _states_dir(self, task_id: str, attempt_id: str) -> Path:
        selected_attempt = _safe_id(attempt_id, "analysis attempt id")
        attempt_dir = self._owned_dir(
            self._attempts_dir(task_id),
            selected_attempt,
            "analysis attempt directory",
        )
        return self._owned_dir(
            attempt_dir, "states", "analysis states directory"
        )

    def _state_path(self, task_id: str, attempt_id: str, event_id: str) -> Path:
        selected_event = _safe_id(event_id, "state event id")
        return self._states_dir(task_id, attempt_id) / f"{selected_event}.json"

    def _pointers_dir(self, task_id: str, snapshot_id: str) -> Path:
        selected_snapshot = _safe_id(snapshot_id, "snapshot id")
        pointer_root = self._owned_dir(
            self._task_dir(task_id), "pointers", "analysis pointers directory"
        )
        return self._owned_dir(
            pointer_root, selected_snapshot, "analysis snapshot pointer directory"
        )

    def _pointer_revisions_dir(self, task_id: str, snapshot_id: str) -> Path:
        return self._owned_dir(
            self._pointers_dir(task_id, snapshot_id),
            "revisions",
            "analysis pointer revisions directory",
        )

    def _pointer_revision_path(
        self, task_id: str, snapshot_id: str, pointer_id: str
    ) -> Path:
        selected_pointer = _safe_id(pointer_id, "pointer id")
        return (
            self._pointer_revisions_dir(task_id, snapshot_id)
            / f"{selected_pointer}.json"
        )

    def _current_pointer_path(self, task_id: str, snapshot_id: str) -> Path:
        return self._pointers_dir(task_id, snapshot_id) / "current.json"

    def _mappings_dir(self, task_id: str) -> Path:
        return self._owned_dir(
            self._task_dir(task_id),
            "manual_mappings",
            "analysis mappings directory",
        )

    def _mapping_path(self, task_id: str, mapping_id: str) -> Path:
        return self._mappings_dir(task_id) / f"{_safe_id(mapping_id, 'mapping revision id')}.json"

    def _read_record(
        self, path: Path, expected_type: str, task_id: str
    ) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise RepositoryAnalysisIntegrityError(
                f"analysis lifecycle record path changed at {path}"
            )
        record = _verified(read_json(path), expected_type, path)
        if record.get("task_id") != task_id:
            raise RepositoryAnalysisIntegrityError(
                f"analysis lifecycle task identity mismatch at {path}"
            )
        return record

    def _write_immutable(
        self, path: Path, record: Mapping[str, Any], expected_type: str
    ) -> None:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RepositoryAnalysisIntegrityError(
                f"immutable analysis lifecycle path changed at {path}"
            )
        if path.exists():
            existing = _verified(read_json(path), expected_type, path)
            if existing != dict(record):
                raise RepositoryAnalysisIntegrityError(
                    f"immutable analysis lifecycle record changed at {path}"
                )
            return
        write_json(path, dict(record))

    def _owned_dir(self, parent: Path, name: str, label: str) -> Path:
        candidate = parent / name
        if candidate.is_symlink() or (
            candidate.exists() and not candidate.is_dir()
        ):
            raise RepositoryAnalysisIntegrityError(f"{label} changed")
        candidate.mkdir(parents=False, exist_ok=True)
        resolved_parent = parent.resolve()
        resolved = candidate.resolve()
        if resolved_parent not in resolved.parents:
            raise RepositoryAnalysisIntegrityError(f"unsafe {label}")
        return resolved


class BindingAnalysisAttemptStore:
    """Persist the source-read and static-analysis job before it starts.

    The binding endpoint must not hold an HTTP request open while a provider
    lists a repository tree or while the analyzer reads bounded documents.
    This store gives that background operation an immutable identity and an
    append-only state chain that can still be projected before a binding or
    SourceSnapshot exists.
    """

    SCHEMA_VERSION = "0.1"
    EXECUTION_POLICY = "bounded_source_read_then_static_analysis"

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        tasks_candidate = self.root / "tasks"
        if tasks_candidate.is_symlink():
            raise ContractError("tasks directory cannot be a symlink")
        tasks_candidate.mkdir(parents=True, exist_ok=True)
        self.tasks_dir = tasks_candidate.resolve()
        self._lock = RLock()

    def create_attempt(
        self,
        task_id: str,
        *,
        resolution_id: str,
        resolution_digest: str,
        expected_resolved_commit: str,
        base_spec_revision: int,
        analyzer_version: str,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_resolution = _safe_id(resolution_id, "resolution id")
        selected_digest = _safe_digest(resolution_digest, "resolution digest")
        selected_commit = str(expected_resolved_commit).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", selected_commit):
            raise ContractError("invalid expected resolved commit")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base spec revision must be a positive integer")
        selected_analyzer = _safe_text(
            analyzer_version, "analyzer version", maximum=160
        )

        with self._lock:
            attempts = self.list_attempts(selected_task)
            for existing in attempts:
                if existing["resolution_id"] != selected_resolution:
                    continue
                if (
                    existing["resolution_digest"] != selected_digest
                    or existing["expected_resolved_commit"] != selected_commit
                    or existing["base_spec_revision"] != base_spec_revision
                ):
                    raise RepositoryAnalysisIntegrityError(
                        "binding analysis resolution identity changed"
                    )
            current = self._projection_for_record(attempts[-1]) if attempts else None
            same_request = bool(
                current
                and current["attempt"]["resolution_id"] == selected_resolution
                and current["attempt"]["resolution_digest"] == selected_digest
                and current["attempt"]["expected_resolved_commit"] == selected_commit
                and current["attempt"]["base_spec_revision"] == base_spec_revision
                and current["attempt"].get("analyzer_version") == selected_analyzer
            )
            if current and current["current_state"]["status"] in {
                "queued",
                "running",
            }:
                if same_request:
                    return current
                raise ContractError("another model binding attempt is still active")
            if current and current["current_state"]["status"] == "completed" and same_request:
                return current

            previous_for_resolution = next(
                (
                    item
                    for item in reversed(attempts)
                    if item["resolution_id"] == selected_resolution
                    and item["resolution_digest"] == selected_digest
                    and item["expected_resolved_commit"] == selected_commit
                    and item["base_spec_revision"] == base_spec_revision
                    and item.get("analyzer_version") == selected_analyzer
                ),
                None,
            )
            retry_projection = (
                self._projection_for_record(previous_for_resolution)
                if previous_for_resolution is not None
                else None
            )
            retry_record = (
                previous_for_resolution
                if retry_projection is not None
                and retry_projection["current_state"]["status"]
                in {"failed", "cancelled"}
                else None
            )
            sequence = len(attempts) + 1
            attempt_id = f"binding-analysis-attempt-r{sequence}-{uuid4().hex[:12]}"
            attempt = BindingAnalysisAttempt(
                schema_version=self.SCHEMA_VERSION,
                object_type="BindingAnalysisAttempt",
                attempt_id=attempt_id,
                task_id=selected_task,
                resolution_id=selected_resolution,
                resolution_digest=selected_digest,
                expected_resolved_commit=selected_commit,
                base_spec_revision=base_spec_revision,
                analyzer_version=selected_analyzer,
                attempt_sequence=sequence,
                retry_of_attempt_id=(
                    str(retry_record["attempt_id"]) if retry_record else None
                ),
                retry_of_attempt_digest=(
                    str(retry_record["content_digest"]) if retry_record else None
                ),
                initial_status="queued",
                execution_policy=self.EXECUTION_POLICY,
                created_at_utc=_now(),
            )
            sealed = _sealed(attempt.to_dict())
            self._write_immutable(
                self._attempt_path(selected_task, attempt_id),
                sealed,
                "BindingAnalysisAttempt",
            )
            queued = self._append_state(sealed, status="queued", previous=None)
            return self._projection(sealed, queued)

    def mark_running(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        return self._transition(task_id, attempt_id, status="running")

    def complete(
        self,
        task_id: str,
        attempt_id: str,
        *,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        selected_result = _json_mapping(result, "binding analysis result")
        if not selected_result:
            raise ContractError("binding analysis result must not be empty")
        attempt = self._get_attempt_record(task_id, attempt_id)
        immutable_identity = {
            "task_id": attempt["task_id"],
            "resolution_id": attempt["resolution_id"],
            "resolution_digest": attempt["resolution_digest"],
            "expected_resolved_commit": attempt["expected_resolved_commit"],
            "base_spec_revision": attempt["base_spec_revision"],
            "analyzer_version": attempt["analyzer_version"],
        }
        if "resolution_id" not in selected_result:
            raise ContractError(
                "binding analysis result resolution_id is required"
            )
        for field, expected in immutable_identity.items():
            if (
                field in selected_result
                and _canonical(selected_result[field]) != _canonical(expected)
            ):
                raise ContractError(
                    f"binding analysis result {field} does not match immutable attempt"
                )
            selected_result[field] = deepcopy(expected)
        return self._transition(
            task_id,
            attempt_id,
            status="completed",
            result=selected_result,
        )

    def fail(
        self,
        task_id: str,
        attempt_id: str,
        *,
        stage: str,
        code: str,
        message: str,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(retryable, bool):
            raise ContractError("retryable must be boolean")
        failure = AnalysisFailureEvidence(
            stage=_safe_text(stage, "failure stage", maximum=120),
            code=_safe_text(code, "failure code", maximum=160),
            message=_safe_message(message, "failure message", maximum=1000),
            retryable=retryable,
            details=_json_mapping(details or {}, "failure details"),
        )
        return self._transition(
            task_id,
            attempt_id,
            status="failed",
            failure=failure.to_dict(),
        )

    def cancel(
        self,
        task_id: str,
        attempt_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        """Append a durable cancellation before any binding is committed."""

        return self._transition(
            task_id,
            attempt_id,
            status="cancelled",
            cancellation={
                "reason": _safe_message(
                    reason, "cancellation reason", maximum=500
                )
            },
        )

    def get_attempt(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        record = self._get_attempt_record(task_id, attempt_id)
        return self._projection_for_record(record)

    def current_attempt(self, task_id: str) -> dict[str, Any] | None:
        attempts = self.list_attempts(task_id)
        return self._projection_for_record(attempts[-1]) if attempts else None

    def list_attempts(self, task_id: str) -> list[dict[str, Any]]:
        selected_task = _safe_task_id(task_id)
        records = [
            self._read_record(path, "BindingAnalysisAttempt", selected_task)
            for path in sorted(self._attempts_dir(selected_task).glob("*/attempt.json"))
        ]
        records.sort(
            key=lambda item: (int(item["attempt_sequence"]), item["attempt_id"])
        )
        by_id: dict[str, dict[str, Any]] = {}
        for expected, record in enumerate(records, start=1):
            if record["attempt_sequence"] != expected:
                raise RepositoryAnalysisIntegrityError(
                    "binding analysis attempt sequence is broken"
                )
            retry_id = record.get("retry_of_attempt_id")
            retry_digest = record.get("retry_of_attempt_digest")
            if retry_id is None:
                if retry_digest is not None:
                    raise RepositoryAnalysisIntegrityError(
                        "binding analysis retry digest has no attempt"
                    )
            else:
                previous = by_id.get(str(retry_id))
                if (
                    previous is None
                    or previous["content_digest"] != retry_digest
                    or previous["resolution_id"] != record["resolution_id"]
                    or previous["resolution_digest"] != record["resolution_digest"]
                    or previous["expected_resolved_commit"]
                    != record["expected_resolved_commit"]
                    or previous["base_spec_revision"]
                    != record["base_spec_revision"]
                    or previous.get("analyzer_version")
                    != record.get("analyzer_version")
                ):
                    raise RepositoryAnalysisIntegrityError(
                        "binding analysis retry lineage is broken"
                    )
            by_id[str(record["attempt_id"])] = record
        return records

    def recover_interrupted_attempts(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        for task_path in sorted(self.tasks_dir.iterdir()):
            if task_path.is_symlink() or not task_path.is_dir():
                continue
            if not (task_path / "task.json").is_file():
                continue
            selected_task = _safe_task_id(task_path.name)
            current = self.current_attempt(selected_task)
            if current is None:
                continue
            previous_status = str(current["current_state"]["status"])
            if previous_status not in {"queued", "running"}:
                continue
            recovered.append(
                self.fail(
                    selected_task,
                    str(current["attempt"]["attempt_id"]),
                    stage="binding_and_repository_analysis",
                    code="interrupted_by_restart",
                    message=(
                        "模型来源绑定在服务重启前未形成终态；已保留证据，可重新批准重试。"
                    ),
                    retryable=True,
                    details={"previous_status": previous_status},
                )
            )
        return recovered

    def _transition(
        self,
        task_id: str,
        attempt_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
        cancellation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_attempt = _safe_id(attempt_id, "binding analysis attempt id")
        selected_status = str(status).strip().lower()
        if selected_status not in {"running", "completed", "failed", "cancelled"}:
            raise ContractError("invalid binding analysis attempt status")
        with self._lock:
            current = self.current_attempt(selected_task)
            if (
                current is None
                or current["attempt"]["attempt_id"] != selected_attempt
            ):
                raise StaleAnalysisAttemptError(
                    "binding analysis attempt is no longer current"
                )
            previous = current["current_state"]
            if selected_status not in _ALLOWED_TRANSITIONS.get(
                previous["status"], set()
            ):
                raise ContractError(
                    "invalid binding analysis transition "
                    f"{previous['status']} -> {selected_status}"
                )
            state = self._append_state(
                current["attempt"],
                status=selected_status,
                previous=previous,
                result=result,
                failure=failure,
                cancellation=cancellation,
            )
            return self._projection(current["attempt"], state)

    def _append_state(
        self,
        attempt: Mapping[str, Any],
        *,
        status: str,
        previous: Mapping[str, Any] | None,
        result: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
        cancellation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision = int(previous["state_revision"]) + 1 if previous else 1
        semantic = {
            "task_id": attempt["task_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_digest": attempt["content_digest"],
            "state_revision": revision,
            "previous_event_id": previous["event_id"] if previous else None,
            "previous_event_digest": previous["content_digest"] if previous else None,
            "status": status,
            "result": deepcopy(dict(result)) if result is not None else None,
            "failure": deepcopy(dict(failure)) if failure is not None else None,
            "cancellation": (
                deepcopy(dict(cancellation)) if cancellation is not None else None
            ),
        }
        self._validate_state_payload(semantic)
        semantic_digest = _digest(semantic)
        event_id = (
            f"{attempt['attempt_id']}-s{revision}-{status}-{semantic_digest[:10]}"
        )
        state = _sealed(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "BindingAnalysisAttemptState",
                "event_id": event_id,
                **semantic,
                "semantic_digest": semantic_digest,
                "created_at_utc": _now(),
            }
        )
        self._write_immutable(
            self._state_path(attempt["task_id"], attempt["attempt_id"], event_id),
            state,
            "BindingAnalysisAttemptState",
        )
        return state

    def _validate_state_payload(self, value: Mapping[str, Any]) -> None:
        status = str(value["status"])
        has_result = value.get("result") is not None
        has_failure = value.get("failure") is not None
        has_cancellation = value.get("cancellation") is not None
        if status == "completed" and not has_result:
            raise ContractError("completed binding analysis state requires a result")
        if status == "failed" and not has_failure:
            raise ContractError("failed binding analysis state requires evidence")
        if status == "cancelled" and not has_cancellation:
            raise ContractError("cancelled binding analysis state requires a reason")
        if status in {"queued", "running"} and (
            has_result or has_failure or has_cancellation
        ):
            raise ContractError("active binding analysis state cannot have a result")
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ContractError("invalid binding analysis state")
        expected_count = int(status == "completed") + int(status == "failed") + int(
            status == "cancelled"
        )
        if int(has_result) + int(has_failure) + int(has_cancellation) != expected_count:
            raise ContractError("binding analysis state payload does not match status")
        _canonical(value)

    def _states(self, attempt: Mapping[str, Any]) -> list[dict[str, Any]]:
        states = [
            self._read_record(
                path, "BindingAnalysisAttemptState", str(attempt["task_id"])
            )
            for path in sorted(
                self._states_dir(
                    str(attempt["task_id"]), str(attempt["attempt_id"])
                ).glob("*.json")
            )
        ]
        states.sort(key=lambda item: (int(item["state_revision"]), item["event_id"]))
        previous: dict[str, Any] | None = None
        for expected, state in enumerate(states, start=1):
            if (
                state["attempt_id"] != attempt["attempt_id"]
                or state["attempt_digest"] != attempt["content_digest"]
                or state["state_revision"] != expected
            ):
                raise RepositoryAnalysisIntegrityError(
                    "binding analysis state lineage is broken"
                )
            if state["previous_event_id"] != (
                previous["event_id"] if previous else None
            ) or state["previous_event_digest"] != (
                previous["content_digest"] if previous else None
            ):
                raise RepositoryAnalysisIntegrityError(
                    "binding analysis state chain is broken"
                )
            if previous is None and state["status"] != "queued":
                raise RepositoryAnalysisIntegrityError(
                    "binding analysis attempt must start queued"
                )
            if previous is not None and state["status"] not in _ALLOWED_TRANSITIONS.get(
                previous["status"], set()
            ):
                raise RepositoryAnalysisIntegrityError(
                    "binding analysis transition is invalid"
                )
            self._validate_state_payload(state)
            previous = state
        return states

    def _projection_for_record(self, attempt: Mapping[str, Any]) -> dict[str, Any]:
        states = self._states(attempt)
        if not states:
            raise RepositoryAnalysisIntegrityError(
                "binding analysis attempt has no state"
            )
        return self._projection(attempt, states[-1])

    @staticmethod
    def _projection(
        attempt: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "attempt": deepcopy(dict(attempt)),
            "current_state": deepcopy(dict(state)),
            "pointer": None,
        }

    def _get_attempt_record(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_attempt = _safe_id(attempt_id, "binding analysis attempt id")
        record = self._read_record(
            self._attempt_path(selected_task, selected_attempt),
            "BindingAnalysisAttempt",
            selected_task,
        )
        if record["attempt_id"] != selected_attempt:
            raise RepositoryAnalysisIntegrityError(
                "binding analysis attempt identity mismatch"
            )
        return record

    def _task_dir(self, task_id: str) -> Path:
        selected_task = _safe_task_id(task_id)
        task_root = self._owned_dir(
            self.tasks_dir, selected_task, "binding analysis task directory"
        )
        return self._owned_dir(
            task_root,
            "binding_analysis_lifecycle",
            "binding analysis lifecycle directory",
        )

    def _attempts_dir(self, task_id: str) -> Path:
        return self._owned_dir(
            self._task_dir(task_id), "attempts", "binding analysis attempts directory"
        )

    def _attempt_path(self, task_id: str, attempt_id: str) -> Path:
        selected_attempt = _safe_id(attempt_id, "binding analysis attempt id")
        directory = self._owned_dir(
            self._attempts_dir(task_id),
            selected_attempt,
            "binding analysis attempt directory",
        )
        return directory / "attempt.json"

    def _states_dir(self, task_id: str, attempt_id: str) -> Path:
        selected_attempt = _safe_id(attempt_id, "binding analysis attempt id")
        attempt_dir = self._owned_dir(
            self._attempts_dir(task_id),
            selected_attempt,
            "binding analysis attempt directory",
        )
        return self._owned_dir(
            attempt_dir, "states", "binding analysis states directory"
        )

    def _state_path(self, task_id: str, attempt_id: str, event_id: str) -> Path:
        return self._states_dir(task_id, attempt_id) / (
            f"{_safe_id(event_id, 'binding analysis event id')}.json"
        )

    def _read_record(
        self, path: Path, expected_type: str, task_id: str
    ) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise RepositoryAnalysisIntegrityError(
                f"binding analysis lifecycle record path changed at {path}"
            )
        record = _verified(read_json(path), expected_type, path)
        if record.get("task_id") != task_id:
            raise RepositoryAnalysisIntegrityError(
                f"binding analysis task identity mismatch at {path}"
            )
        return record

    def _write_immutable(
        self, path: Path, record: Mapping[str, Any], expected_type: str
    ) -> None:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RepositoryAnalysisIntegrityError(
                f"immutable binding analysis path changed at {path}"
            )
        if path.exists():
            existing = _verified(read_json(path), expected_type, path)
            if existing != dict(record):
                raise RepositoryAnalysisIntegrityError(
                    f"immutable binding analysis record changed at {path}"
                )
            return
        write_json(path, dict(record))

    def _owned_dir(self, parent: Path, name: str, label: str) -> Path:
        candidate = parent / name
        if candidate.is_symlink() or (
            candidate.exists() and not candidate.is_dir()
        ):
            raise RepositoryAnalysisIntegrityError(f"{label} changed")
        candidate.mkdir(parents=False, exist_ok=True)
        resolved_parent = parent.resolve()
        resolved = candidate.resolve()
        if resolved_parent not in resolved.parents:
            raise RepositoryAnalysisIntegrityError(f"unsafe {label}")
        return resolved


__all__ = [
    "AnalysisAttempt",
    "AnalysisFailureEvidence",
    "BindingAnalysisAttempt",
    "BindingAnalysisAttemptStore",
    "ManualMappingRevision",
    "RepositoryAnalysisIntegrityError",
    "RepositoryAnalysisStore",
    "StaleAnalysisAttemptError",
]
