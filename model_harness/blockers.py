from __future__ import annotations

import hashlib
import json
import re
import fcntl
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .errors import ContractError
from .io_utils import read_json, write_json


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
BLOCKER_EVIDENCE_SCHEMA_VERSION = "0.3"
LEGACY_BLOCKER_SCHEMA_VERSION = "0.1"
PREVIOUS_BLOCKER_SCHEMA_VERSION = "0.2"
LEGACY_SUPERSEDED_ACTION = "superseded_by_v0.2_blocker"
V02_SUPERSEDED_ACTION = "superseded_by_newer_v0.2_blocker"
_OCCURRENCE_IDENTITY_KEY = "__blocker_store_identity_digest"
_OCCURRENCE_INDEX_KEY = "__blocker_store_occurrence"
BLOCKER_EVIDENCE_STAGES = frozenset(
    {
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
)
CANONICAL_BLOCKER_CODES = frozenset(
    {
        "blocked_license",
        "blocked_security",
        "blocked_environment",
        "blocked_platform",
        "blocked_resources",
        "blocked_data",
        "blocked_repository",
        "qualification_failed",
        "recipe_unavailable",
    }
)
V02_CANONICAL_BLOCKER_CODES = CANONICAL_BLOCKER_CODES - {"recipe_unavailable"}
SUPPORTED_BLOCKER_SCHEMA_VERSIONS = frozenset(
    {PREVIOUS_BLOCKER_SCHEMA_VERSION, BLOCKER_EVIDENCE_SCHEMA_VERSION}
)
_SEMANTIC_KEYS = (
    "task_id",
    "stage",
    "code",
    "retry_action",
    "related_object_type",
    "related_object_id",
    "related_object_digest",
    "details",
    "detector",
    "facts",
    "rule",
    "evidence_refs",
    "recovery_actions",
    "retryable",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
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


def _json_mapping(value: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
    try:
        normalized = json.loads(_canonical(dict(value or {})))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"invalid {label}") from exc
    if not isinstance(normalized, dict):  # pragma: no cover - defensive invariant
        raise ContractError(f"invalid {label}")
    return normalized


def _string_list(
    value: Any, label: str, *, fallback: tuple[str, ...] = ()
) -> list[str]:
    selected = fallback if value is None else value
    if not isinstance(selected, (list, tuple)):
        raise ContractError(f"invalid {label}")
    return [_safe_text(item, label, 500) for item in selected]


def verify_blocker_evidence(
    value: Any,
    *,
    allow_active_projection: bool = False,
) -> dict[str, Any]:
    """Verify one sealed v0.9 BlockerEvidence and return its immutable record.

    API responses may add the derived ``active`` projection.  It is deliberately
    excluded from the sealed record because resolution remains a separate,
    append-only ``BlockerResolution`` fact.
    """

    if not isinstance(value, dict):
        raise ContractError("invalid blocker record")
    candidate = deepcopy(value)
    active = candidate.pop("active", None)
    if active is not None and (
        not allow_active_projection or not isinstance(active, bool)
    ):
        raise ContractError("invalid blocker active projection")
    record = _verified(candidate, "BlockerEvidence")
    required = {
        "schema_version",
        "object_type",
        "blocker_id",
        "blocker_evidence_id",
        *_SEMANTIC_KEYS,
        "message",
        "semantic_digest",
        "created_at",
        "created_at_utc",
        "resolved_by",
        "content_digest",
    }
    if set(record) != required:
        raise ContractError("incomplete v0.9 blocker evidence")
    schema_version = record["schema_version"]
    if schema_version not in SUPPORTED_BLOCKER_SCHEMA_VERSIONS:
        raise ContractError("unsupported blocker evidence schema")
    if record["blocker_evidence_id"] != record["blocker_id"]:
        raise ContractError("blocker evidence id alias mismatch")
    if record["created_at"] != record["created_at_utc"]:
        raise ContractError("blocker created-at alias mismatch")
    if record["resolved_by"] is not None:
        raise ContractError("BlockerEvidence must remain immutable")
    if record["stage"] not in BLOCKER_EVIDENCE_STAGES:
        raise ContractError("invalid blocker stage")
    allowed_codes = (
        V02_CANONICAL_BLOCKER_CODES
        if schema_version == PREVIOUS_BLOCKER_SCHEMA_VERSION
        else CANONICAL_BLOCKER_CODES
    )
    if record["code"] not in allowed_codes:
        raise ContractError("non-canonical blocker code")
    _safe_id(record["blocker_id"], "blocker id")
    _safe_task_id(record["task_id"])
    _safe_text(record["message"], "blocker message", 500)
    _safe_text(record["retry_action"], "retry action", 120)
    _safe_text(record["detector"], "blocker detector", 160)
    if not isinstance(record["facts"], Mapping) or not isinstance(
        record["rule"], Mapping
    ):
        raise ContractError("invalid blocker facts or rule")
    _json_mapping(record["facts"], "blocker facts")
    _json_mapping(record["rule"], "blocker rule")
    _json_mapping(record["details"], "blocker details")
    _string_list(record["evidence_refs"], "blocker evidence ref")
    recovery_actions = _string_list(
        record["recovery_actions"], "blocker recovery action"
    )
    if not recovery_actions:
        raise ContractError("blocker recovery actions must not be empty")
    if not isinstance(record["retryable"], bool):
        raise ContractError("invalid blocker retryable flag")
    if record["related_object_type"] is not None:
        _safe_text(record["related_object_type"], "related object type", 80)
    if record["related_object_id"] is not None:
        _safe_id(record["related_object_id"], "related object id")
    if record["related_object_digest"] is not None and not re.fullmatch(
        r"[0-9a-f]{64}", str(record["related_object_digest"])
    ):
        raise ContractError("invalid related object digest")
    try:
        created_at = datetime.fromisoformat(record["created_at_utc"])
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid blocker created-at timestamp") from exc
    if created_at.tzinfo is None:
        raise ContractError("invalid blocker created-at timestamp")
    semantic = {key: record[key] for key in _SEMANTIC_KEYS}
    if record["semantic_digest"] != _digest(semantic):
        raise ContractError("blocker semantic digest mismatch")
    if record["blocker_id"] != f"blocker_{record['semantic_digest'][:24]}":
        raise ContractError("blocker id does not match semantic digest")
    return record


def _verified_blocker_record(value: Any) -> dict[str, Any]:
    record = _verified(value, "BlockerEvidence")
    if record.get("schema_version") in SUPPORTED_BLOCKER_SCHEMA_VERSIONS:
        return verify_blocker_evidence(record)
    return record


def verify_recipe_unavailable_evidence(
    value: Any,
    *,
    allow_active_projection: bool = False,
) -> dict[str, Any]:
    """Verify the immutable snapshots sealed by a recipe capability blocker.

    The task-scoped blocker endpoint is the read path for both historical
    snapshots after ``recipe_request.json`` moves on to a later mutable state.
    This verifier recomputes the RecipeBuildRequest and TaskSpecRevision
    digests so a later resolution cannot erase or rewrite the original gap.
    """

    record = verify_blocker_evidence(
        value,
        allow_active_projection=allow_active_projection,
    )
    if record["stage"] != "build" or record["code"] != "recipe_unavailable":
        raise ContractError("not recipe unavailable evidence")
    if record["related_object_type"] != "RecipeBuildRequest":
        raise ContractError("recipe blocker related object mismatch")

    facts = record["facts"]
    request = _json_mapping(
        facts.get("recipe_build_request_snapshot"),
        "recipe build request snapshot",
    )
    task_spec = _json_mapping(
        facts.get("task_spec_revision_snapshot"),
        "task spec revision snapshot",
    )
    request_digest = _safe_text(
        facts.get("recipe_build_request_digest"),
        "recipe build request digest",
        64,
    )
    task_spec_digest = _safe_text(
        facts.get("task_spec_revision_digest"),
        "task spec revision digest",
        64,
    )
    if not re.fullmatch(r"[0-9a-f]{64}", request_digest):
        raise ContractError("invalid recipe build request digest")
    if not re.fullmatch(r"[0-9a-f]{64}", task_spec_digest):
        raise ContractError("invalid task spec revision digest")
    if _digest(request) != request_digest:
        raise ContractError("recipe build request snapshot digest mismatch")
    if _digest(task_spec) != task_spec_digest:
        raise ContractError("task spec revision snapshot digest mismatch")

    request_id = _safe_id(
        request.get("recipe_request_id"),
        "recipe request id",
    )
    revision_id = _safe_text(
        task_spec.get("revision_id"),
        "task spec revision id",
        240,
    )
    if request.get("task_id") != record["task_id"]:
        raise ContractError("recipe request task identity mismatch")
    if task_spec.get("task_id") != record["task_id"]:
        raise ContractError("task spec task identity mismatch")
    if record["related_object_id"] != request_id:
        raise ContractError("recipe blocker request identity mismatch")
    if record["related_object_digest"] != request_digest:
        raise ContractError("recipe blocker request digest mismatch")
    if request.get("task_spec_revision_id") != revision_id:
        raise ContractError("recipe request task spec identity mismatch")
    if request.get("task_spec_revision_digest") != task_spec_digest:
        raise ContractError("recipe request task spec digest mismatch")
    if facts.get("task_spec_revision_id") != revision_id:
        raise ContractError("recipe blocker task spec identity mismatch")
    if record["details"].get("task_spec_revision_id") != revision_id:
        raise ContractError("recipe blocker details task spec identity mismatch")
    if record["details"].get("task_spec_revision_digest") != task_spec_digest:
        raise ContractError("recipe blocker details task spec digest mismatch")
    if record["details"].get("recipe_request_id") != request_id:
        raise ContractError("recipe blocker details request identity mismatch")
    if record["details"].get("recipe_request_digest") != request_digest:
        raise ContractError("recipe blocker details request digest mismatch")

    original_capability = _json_mapping(
        facts.get("original_capability_request"),
        "original capability request",
    )
    requested_capability = _json_mapping(
        facts.get("requested_capability_request"),
        "requested capability request",
    )
    if task_spec.get("capability_request") != original_capability:
        raise ContractError("recipe blocker original capability mismatch")
    if request.get("original_capability_request") != original_capability:
        raise ContractError("recipe request original capability mismatch")
    if request.get("capability_request") != requested_capability:
        raise ContractError("recipe request capability snapshot mismatch")
    return record


class BlockerStore:
    """Append-only blocker facts plus separate resolution facts.

    BlockerEvidence is never edited to become resolved. A BlockerResolution
    points at it, preserving the original failure after restart and allowing
    the UI to derive active blockers without inventing local state.
    """

    SCHEMA_VERSION = BLOCKER_EVIDENCE_SCHEMA_VERSION

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        self.tasks_dir = (self.root / "tasks").resolve()
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._process_locks: dict[str, tuple[Any, int]] = {}

    @contextmanager
    def _task_process_lock(self, task_id: str) -> Any:
        """Serialize append/resolution allocation across local processes."""

        selected_task = _safe_task_id(task_id)
        held = self._process_locks.get(selected_task)
        if held is not None:
            handle, depth = held
            self._process_locks[selected_task] = (handle, depth + 1)
            try:
                yield
            finally:
                current_handle, current_depth = self._process_locks[selected_task]
                self._process_locks[selected_task] = (
                    current_handle,
                    current_depth - 1,
                )
            return
        lock_path = self._task_dir(selected_task) / ".occurrence.lock"
        handle = lock_path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._process_locks[selected_task] = (handle, 1)
            yield
        finally:
            self._process_locks.pop(selected_task, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

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
        detector: str | None = None,
        facts: Mapping[str, Any] | None = None,
        rule: Mapping[str, Any] | None = None,
        evidence_refs: list[str] | tuple[str, ...] | None = None,
        recovery_actions: list[str] | tuple[str, ...] | None = None,
        retryable: bool | None = None,
    ) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        selected_stage = str(stage).strip().lower()
        if selected_stage not in BLOCKER_EVIDENCE_STAGES:
            raise ContractError("invalid blocker stage")
        selected_code = _safe_text(code, "blocker code", 120)
        if selected_code not in CANONICAL_BLOCKER_CODES:
            raise ContractError("non-canonical blocker code")
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
        selected_details = _json_mapping(details, "blocker details")
        if any(
            key in selected_details
            for key in (_OCCURRENCE_IDENTITY_KEY, _OCCURRENCE_INDEX_KEY)
        ):
            raise ContractError("blocker occurrence metadata is store-owned")
        selected_detector = _safe_text(
            detector
            or selected_details.get("detector")
            or "model_harness.blocker_store@0.2",
            "blocker detector",
            160,
        )
        selected_facts = _json_mapping(
            facts if facts is not None else selected_details,
            "blocker facts",
        )
        selected_rule = _json_mapping(
            rule
            if rule is not None
            else {"code": selected_code, "stage": selected_stage},
            "blocker rule",
        )
        selected_refs = _string_list(
            evidence_refs
            if evidence_refs is not None
            else selected_details.get("evidence_refs"),
            "blocker evidence ref",
        )
        selected_recovery = _string_list(
            recovery_actions
            if recovery_actions is not None
            else selected_details.get("recovery_actions"),
            "blocker recovery action",
            fallback=(selected_retry,),
        )
        selected_retryable = (
            retryable
            if retryable is not None
            else selected_details.get("retryable", True)
        )
        if not isinstance(selected_retryable, bool):
            raise ContractError("invalid blocker retryable flag")
        base_semantic = {
            "task_id": selected_task,
            "stage": selected_stage,
            "code": selected_code,
            "retry_action": selected_retry,
            "related_object_type": related_type,
            "related_object_id": related_id,
            "related_object_digest": related_digest,
            "details": selected_details,
            "detector": selected_detector,
            "facts": selected_facts,
            "rule": selected_rule,
            "evidence_refs": selected_refs,
            "recovery_actions": selected_recovery,
            "retryable": selected_retryable,
        }
        identity_digest = _digest(base_semantic)
        with self._lock, self._task_process_lock(selected_task):
            matching: list[dict[str, Any]] = []
            for existing in self.list(selected_task):
                if existing.get("schema_version") != self.SCHEMA_VERSION:
                    continue
                existing_details = existing.get("details") or {}
                existing_identity = existing_details.get(
                    _OCCURRENCE_IDENTITY_KEY,
                    existing.get("semantic_digest"),
                )
                if existing_identity == identity_digest:
                    matching.append(existing)

            active_matching = [item for item in matching if item.get("active")]
            if active_matching:
                selected_record = deepcopy(sorted(
                    active_matching,
                    key=lambda item: (item["created_at_utc"], item["blocker_id"]),
                )[-1])
                selected_record.pop("active", None)
                created = False
            else:
                occurrence_index = 0
                if matching:
                    occurrence_index = max(
                        int(
                            (item.get("details") or {}).get(
                                _OCCURRENCE_INDEX_KEY,
                                0,
                            )
                        )
                        for item in matching
                    ) + 1
                occurrence_details = deepcopy(selected_details)
                if occurrence_index:
                    occurrence_details[_OCCURRENCE_IDENTITY_KEY] = identity_digest
                    occurrence_details[_OCCURRENCE_INDEX_KEY] = occurrence_index
                semantic = {
                    **base_semantic,
                    "details": occurrence_details,
                }
                semantic_digest = _digest(semantic)
                blocker_id = f"blocker_{semantic_digest[:24]}"
                created_at = _now()
                record = _sealed(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "object_type": "BlockerEvidence",
                        "blocker_id": blocker_id,
                        "blocker_evidence_id": blocker_id,
                        **semantic,
                        "message": selected_message,
                        "semantic_digest": semantic_digest,
                        "created_at": created_at,
                        "created_at_utc": created_at,
                        "resolved_by": None,
                    }
                )
                path = self._evidence_dir(selected_task) / f"{blocker_id}.json"
                if path.exists():
                    selected_record = self._read_evidence_path(selected_task, path)
                    created = False
                else:
                    write_json(path, record)
                    selected_record = record
                    created = True
            self._supersede_active_v01_stage(
                selected_task,
                selected_stage,
                superseding_blocker=selected_record,
            )
            if created:
                self._supersede_active_v02_identity(
                    selected_task,
                    selected_stage,
                    selected_code,
                    superseding_blocker=selected_record,
                )
            return selected_record

    def _supersede_active_v01_stage(
        self,
        task_id: str,
        stage: str,
        *,
        superseding_blocker: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Resolve only active v0.1 blockers replaced by this v0.2 stage fact."""

        resolutions: list[dict[str, Any]] = []
        for blocker in self.list(task_id, active_only=True):
            if (
                blocker.get("schema_version") == LEGACY_BLOCKER_SCHEMA_VERSION
                and blocker.get("stage") == stage
            ):
                resolutions.append(
                    self.resolve(
                        task_id,
                        str(blocker["blocker_id"]),
                        action=LEGACY_SUPERSEDED_ACTION,
                        related_object_type="BlockerEvidence",
                        related_object_id=str(superseding_blocker["blocker_id"]),
                    )
                )
        return resolutions

    def _supersede_active_v02_identity(
        self,
        task_id: str,
        stage: str,
        code: str,
        *,
        superseding_blocker: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Resolve older active v0.2 facts for the same task/stage/code only."""

        superseding_id = str(superseding_blocker["blocker_id"])
        resolutions: list[dict[str, Any]] = []
        for blocker in self.list(task_id, active_only=True):
            if (
                blocker.get("schema_version") in {
                    PREVIOUS_BLOCKER_SCHEMA_VERSION,
                    BLOCKER_EVIDENCE_SCHEMA_VERSION,
                }
                and blocker.get("stage") == stage
                and blocker.get("code") == code
                and blocker.get("blocker_id") != superseding_id
            ):
                resolutions.append(
                    self.resolve(
                        task_id,
                        str(blocker["blocker_id"]),
                        action=V02_SUPERSEDED_ACTION,
                        related_object_type="BlockerEvidence",
                        related_object_id=superseding_id,
                    )
                )
        return resolutions

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
        with self._lock, self._task_process_lock(selected_task):
            path = self._resolution_dir(selected_task) / f"{resolution_id}.json"
            if path.exists():
                return self._read_resolution_path(selected_task, path)
            write_json(path, record)
        return record

    def get(self, task_id: str, blocker_id: str) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        path = self._evidence_dir(selected_task) / f"{_safe_id(blocker_id, 'blocker id')}.json"
        if not path.exists():
            raise FileNotFoundError("blocker not found")
        return self._read_evidence_path(selected_task, path)

    def list(self, task_id: str, *, active_only: bool = False) -> list[dict[str, Any]]:
        selected_task = _safe_task_id(task_id)
        evidence = [
            self._read_evidence_path(selected_task, path)
            for path in sorted(self._evidence_dir(selected_task).glob("*.json"))
        ]
        resolved_ids = {
            record["blocker_id"]
            for record in (
                self._read_resolution_path(selected_task, path)
                for path in sorted(self._resolution_dir(selected_task).glob("*.json"))
            )
        }
        for record in evidence:
            record["active"] = record["blocker_id"] not in resolved_ids
        if active_only:
            evidence = [record for record in evidence if record["active"]]
        return sorted(evidence, key=lambda item: (item["created_at_utc"], item["blocker_id"]))

    def _read_evidence_path(self, task_id: str, path: Path) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        record = _verified_blocker_record(read_json(path))
        if record.get("task_id") != selected_task:
            raise ContractError("blocker evidence task identity mismatch")
        if record.get("blocker_id") != path.stem:
            raise ContractError("blocker evidence file identity mismatch")
        return record

    def _read_resolution_path(self, task_id: str, path: Path) -> dict[str, Any]:
        selected_task = _safe_task_id(task_id)
        record = _verified(read_json(path), "BlockerResolution")
        if record.get("task_id") != selected_task:
            raise ContractError("blocker resolution task identity mismatch")
        if record.get("resolution_id") != path.stem:
            raise ContractError("blocker resolution file identity mismatch")
        blocker_id = record.get("blocker_id")
        if not isinstance(blocker_id, str):
            raise ContractError("blocker resolution blocker identity mismatch")
        try:
            blocker = self.get(selected_task, blocker_id)
        except FileNotFoundError as exc:
            raise ContractError(
                "blocker resolution references blocker outside requested task"
            ) from exc
        if record.get("blocker_digest") != blocker.get("content_digest"):
            raise ContractError("blocker resolution blocker digest mismatch")
        return record

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
