from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json


SCHEMA_VERSION = "0.9"
PLAN_SUBJECT_TYPE = "training_plan_revision"
PLAN_DECISIONS = frozenset({"approve", "reject", "cancel"})


class TrainingPlanIntegrityError(ContractError):
    """Raised when an immutable plan, approval, or pointer changed on disk."""


class StaleTrainingPlanError(ContractError):
    """Raised when an action targets a plan that is no longer current."""


class TrainingPlanApprovalRequired(ContractError):
    """Raised when the exact current plan digest has not been approved."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> bytes:
    """Return the single canonical JSON representation used by plan records."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical JSON: {exc}") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unsigned(record: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    """Exclude only the record's own digest from its digest input."""

    return {key: value for key, value in record.items() if key != digest_field}


def canonical_plan_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(_unsigned(record, "plan_sha256"))


def canonical_approval_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(_unsigned(record, "approval_sha256"))


def _copy_json(value: Any) -> Any:
    return json.loads(canonical_json(value).decode("utf-8"))


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


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    copied = _copy_json(value)
    if not isinstance(copied, dict):  # pragma: no cover - guarded by Mapping
        raise ContractError(f"{label} must be an object")
    return copied


PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "training_plan_revision_id",
        "task_id",
        "base_spec_revision",
        "source_snapshot_id",
        "snapshot_digest",
        "analysis_id",
        "analysis_digest",
        "revision",
        "plan_sha256",
        "entrypoint",
        "dataset_mapping",
        "hyperparameters",
        "evaluation",
        "artifact_contract",
        "resource_budget",
        "execution_policy",
        "parent_revision_id",
        "parent_plan_sha256",
        "status",
        "created_at",
    }
)

REVISION_CHANGE_FIELDS = frozenset(
    {
        "base_spec_revision",
        "source_snapshot_id",
        "snapshot_digest",
        "analysis_id",
        "analysis_digest",
        "entrypoint",
        "dataset_mapping",
        "hyperparameters",
        "evaluation",
        "artifact_contract",
        "resource_budget",
        "execution_policy",
    }
)

APPROVAL_FIELDS = frozenset(
    {
        "schema_version",
        "approval_id",
        "task_id",
        "subject_type",
        "subject_id",
        "digest",
        "decision",
        "actor",
        "reason",
        "sequence",
        "previous_approval_id",
        "previous_approval_sha256",
        "created_at",
        "approval_sha256",
    }
)


def _validate_entrypoint(value: Any) -> dict[str, Any]:
    selected = _mapping(value, "entrypoint")
    if set(selected) != {"argv", "working_dir"}:
        raise ContractError("entrypoint must contain exactly argv and working_dir")
    argv = selected["argv"]
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        raise ContractError("entrypoint.argv must be a non-empty string array")
    working_dir = _non_empty_string(
        selected["working_dir"], "entrypoint.working_dir"
    )
    working_path = PurePosixPath(working_dir)
    if not working_path.is_absolute() or ".." in working_path.parts:
        raise ContractError(
            "entrypoint.working_dir must be an absolute container path without traversal"
        )
    return selected


def _validate_evaluation(value: Any) -> dict[str, Any]:
    selected = _mapping(value, "evaluation")
    if set(selected) != {"metrics", "gates"}:
        raise ContractError("evaluation must contain exactly metrics and gates")
    if not isinstance(selected["metrics"], list) or any(
        not isinstance(metric, str) or not metric for metric in selected["metrics"]
    ):
        raise ContractError("evaluation.metrics must be a string array")
    _mapping(selected["gates"], "evaluation.gates")
    return selected


def _validate_resource_budget(value: Any) -> dict[str, Any]:
    selected = _mapping(value, "resource_budget")
    required = {"max_seconds", "ram_bytes", "vram_bytes", "disk_bytes"}
    if set(selected) != required:
        raise ContractError(
            "resource_budget must contain max_seconds, ram_bytes, vram_bytes, and disk_bytes"
        )
    for field in sorted(required):
        amount = selected[field]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ContractError(f"resource_budget.{field} must be a non-negative integer")
    if selected["max_seconds"] == 0:
        raise ContractError("resource_budget.max_seconds must be greater than zero")
    return selected


def _validate_execution_policy(value: Any) -> dict[str, Any]:
    selected = _mapping(value, "execution_policy")
    required = {"backend", "network_allowlist", "secret_scopes"}
    if set(selected) != required:
        raise ContractError(
            "execution_policy must contain backend, network_allowlist, and secret_scopes"
        )
    if selected["backend"] not in {"oci", "os_sandbox_worker"}:
        raise ContractError(
            "execution_policy.backend must be oci or os_sandbox_worker; host execution is forbidden"
        )
    for field in ("network_allowlist", "secret_scopes"):
        values = selected[field]
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise ContractError(f"execution_policy.{field} must be a string array")
    if any("*" in item for item in selected["network_allowlist"]):
        raise ContractError("execution_policy.network_allowlist cannot contain wildcards")
    return selected


def _validate_plan_record(record: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(record, "training plan")
    if set(selected) != PLAN_FIELDS:
        missing = sorted(PLAN_FIELDS - set(selected))
        extra = sorted(set(selected) - PLAN_FIELDS)
        raise TrainingPlanIntegrityError(
            f"training plan schema changed; missing={missing}, extra={extra}"
        )
    if selected["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported training plan schema_version")
    _safe_id(selected["training_plan_revision_id"], "training plan revision id")
    _safe_id(selected["task_id"], "task id")
    _positive_int(selected["base_spec_revision"], "base_spec_revision")
    _safe_id(selected["source_snapshot_id"], "source snapshot id")
    _digest(selected["snapshot_digest"], "snapshot_digest")
    _safe_id(selected["analysis_id"], "analysis id")
    _digest(selected["analysis_digest"], "analysis_digest")
    revision = _positive_int(selected["revision"], "revision")
    _digest(selected["plan_sha256"], "plan_sha256")
    _validate_entrypoint(selected["entrypoint"])
    for field in ("dataset_mapping", "hyperparameters", "artifact_contract"):
        _mapping(selected[field], field)
    _validate_evaluation(selected["evaluation"])
    _validate_resource_budget(selected["resource_budget"])
    _validate_execution_policy(selected["execution_policy"])

    parent_id = selected["parent_revision_id"]
    parent_digest = selected["parent_plan_sha256"]
    if revision == 1:
        if parent_id is not None or parent_digest is not None:
            raise ContractError("revision 1 cannot have a parent")
    else:
        _safe_id(parent_id, "parent revision id")
        _digest(parent_digest, "parent plan sha256")
    if selected["status"] != "awaiting_approval":
        raise TrainingPlanIntegrityError(
            "immutable plan status must remain awaiting_approval; effective status is derived"
        )
    _non_empty_string(selected["created_at"], "created_at")

    observed = canonical_plan_sha256(selected)
    if observed != selected["plan_sha256"]:
        raise TrainingPlanIntegrityError(
            "training plan digest changed; create and approve a new revision"
        )
    return selected


def _validate_approval_record(record: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(record, "approval record")
    if set(selected) != APPROVAL_FIELDS:
        missing = sorted(APPROVAL_FIELDS - set(selected))
        extra = sorted(set(selected) - APPROVAL_FIELDS)
        raise TrainingPlanIntegrityError(
            f"approval schema changed; missing={missing}, extra={extra}"
        )
    if selected["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported approval schema_version")
    _safe_id(selected["approval_id"], "approval id")
    _safe_id(selected["task_id"], "task id")
    if selected["subject_type"] != PLAN_SUBJECT_TYPE:
        raise ContractError("approval subject_type must be training_plan_revision")
    _safe_id(selected["subject_id"], "approval subject id")
    _digest(selected["digest"], "approval subject digest")
    if selected["decision"] not in PLAN_DECISIONS:
        raise ContractError("approval decision must be approve, reject, or cancel")
    _non_empty_string(selected["actor"], "approval actor")
    if not isinstance(selected["reason"], str):
        raise ContractError("approval reason must be a string")
    if selected["decision"] in {"reject", "cancel"} and not selected["reason"].strip():
        raise ContractError("reject and cancel decisions require a reason")
    sequence = _positive_int(selected["sequence"], "approval sequence")
    if sequence == 1:
        if (
            selected["previous_approval_id"] is not None
            or selected["previous_approval_sha256"] is not None
        ):
            raise ContractError("first approval decision cannot have a predecessor")
    else:
        _safe_id(selected["previous_approval_id"], "previous approval id")
        _digest(
            selected["previous_approval_sha256"],
            "previous approval sha256",
        )
    _non_empty_string(selected["created_at"], "approval created_at")
    _digest(selected["approval_sha256"], "approval_sha256")
    if canonical_approval_sha256(selected) != selected["approval_sha256"]:
        raise TrainingPlanIntegrityError("approval record digest changed")
    return selected


@dataclass(frozen=True)
class TrainingPlanRevision:
    """An immutable canonical training-plan record."""

    _canonical_record: bytes

    @classmethod
    def create(
        cls,
        *,
        training_plan_revision_id: str,
        task_id: str,
        base_spec_revision: int,
        source_snapshot_id: str,
        snapshot_digest: str,
        analysis_id: str,
        analysis_digest: str,
        revision: int,
        entrypoint: Mapping[str, Any],
        dataset_mapping: Mapping[str, Any],
        hyperparameters: Mapping[str, Any],
        evaluation: Mapping[str, Any],
        artifact_contract: Mapping[str, Any],
        resource_budget: Mapping[str, Any],
        execution_policy: Mapping[str, Any],
        parent_revision_id: str | None = None,
        parent_plan_sha256: str | None = None,
        created_at: str | None = None,
    ) -> TrainingPlanRevision:
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "training_plan_revision_id": training_plan_revision_id,
            "task_id": task_id,
            "base_spec_revision": base_spec_revision,
            "source_snapshot_id": source_snapshot_id,
            "snapshot_digest": snapshot_digest,
            "analysis_id": analysis_id,
            "analysis_digest": analysis_digest,
            "revision": revision,
            "entrypoint": _copy_json(entrypoint),
            "dataset_mapping": _copy_json(dataset_mapping),
            "hyperparameters": _copy_json(hyperparameters),
            "evaluation": _copy_json(evaluation),
            "artifact_contract": _copy_json(artifact_contract),
            "resource_budget": _copy_json(resource_budget),
            "execution_policy": _copy_json(execution_policy),
            "parent_revision_id": parent_revision_id,
            "parent_plan_sha256": parent_plan_sha256,
            "status": "awaiting_approval",
            "created_at": created_at or utc_now(),
        }
        record["plan_sha256"] = canonical_plan_sha256(record)
        return cls.from_record(record)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> TrainingPlanRevision:
        selected = _validate_plan_record(record)
        return cls(canonical_json(selected))

    @property
    def plan_sha256(self) -> str:
        return str(self.to_dict()["plan_sha256"])

    @property
    def revision_id(self) -> str:
        return str(self.to_dict()["training_plan_revision_id"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_record.decode("utf-8"))


@dataclass(frozen=True)
class ApprovalRecord:
    """An immutable append-only decision bound to one exact plan digest."""

    _canonical_record: bytes

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        task_id: str,
        subject_id: str,
        digest: str,
        decision: str,
        actor: str,
        reason: str,
        sequence: int,
        previous_approval_id: str | None = None,
        previous_approval_sha256: str | None = None,
        created_at: str | None = None,
    ) -> ApprovalRecord:
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "approval_id": approval_id,
            "task_id": task_id,
            "subject_type": PLAN_SUBJECT_TYPE,
            "subject_id": subject_id,
            "digest": digest,
            "decision": decision,
            "actor": actor,
            "reason": reason,
            "sequence": sequence,
            "previous_approval_id": previous_approval_id,
            "previous_approval_sha256": previous_approval_sha256,
            "created_at": created_at or utc_now(),
        }
        record["approval_sha256"] = canonical_approval_sha256(record)
        return cls.from_record(record)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ApprovalRecord:
        selected = _validate_approval_record(record)
        return cls(canonical_json(selected))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_record.decode("utf-8"))


class TrainingPlanStore:
    """Persist immutable plan revisions and append-only digest decisions."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.tasks_root = self.workspace_root / "tasks"
        if self.tasks_root.is_symlink():
            raise ContractError("tasks directory cannot be a symlink")
        self._lock = RLock()

    def create_revision(
        self,
        task_id: str,
        *,
        base_spec_revision: int,
        source_snapshot_id: str,
        snapshot_digest: str,
        analysis_id: str,
        analysis_digest: str,
        entrypoint: Mapping[str, Any],
        dataset_mapping: Mapping[str, Any],
        hyperparameters: Mapping[str, Any],
        evaluation: Mapping[str, Any],
        artifact_contract: Mapping[str, Any],
        resource_budget: Mapping[str, Any],
        execution_policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            if self.list_revisions(task_id):
                raise ContractError(
                    "training plan already exists; create a new immutable revision"
                )
            plan = TrainingPlanRevision.create(
                training_plan_revision_id=f"plan_{uuid4().hex}",
                task_id=task_id,
                base_spec_revision=base_spec_revision,
                source_snapshot_id=source_snapshot_id,
                snapshot_digest=snapshot_digest,
                analysis_id=analysis_id,
                analysis_digest=analysis_digest,
                revision=1,
                entrypoint=entrypoint,
                dataset_mapping=dataset_mapping,
                hyperparameters=hyperparameters,
                evaluation=evaluation,
                artifact_contract=artifact_contract,
                resource_budget=resource_budget,
                execution_policy=execution_policy,
            )
            record = plan.to_dict()
            self._write_immutable(self._revision_path(task_id, plan.revision_id), record)
            self._write_current_pointer(task_id, record)
            return record

    def revise_revision(
        self,
        task_id: str,
        parent_revision_id: str,
        *,
        expected_parent_sha256: str,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        parent_revision_id = _safe_id(parent_revision_id, "parent revision id")
        expected_parent_sha256 = _digest(
            expected_parent_sha256, "expected parent sha256"
        )
        if not isinstance(changes, Mapping) or not changes:
            raise ContractError("revision changes must be a non-empty object")
        unknown = set(changes) - REVISION_CHANGE_FIELDS
        if unknown:
            raise ContractError(
                f"revision changes contain immutable fields: {sorted(unknown)}"
            )

        with self._lock:
            current = self.current_revision(task_id)
            if current is None:
                raise FileNotFoundError("training plan does not exist")
            if current["training_plan_revision_id"] != parent_revision_id:
                raise StaleTrainingPlanError(
                    "only the current training plan can be revised"
                )
            if current["plan_sha256"] != expected_parent_sha256:
                raise StaleTrainingPlanError("parent training plan digest changed")
            # Revision is a state-changing action, so a corrupted decision chain
            # must be surfaced before a child record is written.
            self.list_approvals(task_id, parent_revision_id)

            selected = {
                field: _copy_json(current[field]) for field in REVISION_CHANGE_FIELDS
            }
            for field, value in changes.items():
                selected[field] = _copy_json(value)
            if canonical_json(selected) == canonical_json(
                {field: current[field] for field in REVISION_CHANGE_FIELDS}
            ):
                raise ContractError("revision must change at least one plan field")

            child = TrainingPlanRevision.create(
                training_plan_revision_id=f"plan_{uuid4().hex}",
                task_id=task_id,
                revision=int(current["revision"]) + 1,
                parent_revision_id=parent_revision_id,
                parent_plan_sha256=current["plan_sha256"],
                **selected,
            )
            record = child.to_dict()
            self._write_immutable(self._revision_path(task_id, child.revision_id), record)
            self._write_current_pointer(task_id, record)
            return record

    def get_revision(self, task_id: str, revision_id: str) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        revision_id = _safe_id(revision_id, "training plan revision id")
        with self._lock:
            chain = self._load_revision_chain(task_id)
            selected = next(
                (
                    record
                    for record in chain
                    if record["training_plan_revision_id"] == revision_id
                ),
                None,
            )
            if selected is not None:
                # Cross-check the leaf against the independently sealed current
                # pointer. This also catches a current plan that was modified and
                # re-hashed by hand rather than only a stale self digest.
                self.current_revision(task_id)
                return _copy_json(selected)
        raise FileNotFoundError(f"training plan revision not found: {revision_id}")

    def list_revisions(self, task_id: str) -> list[dict[str, Any]]:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            chain = self._load_revision_chain(task_id)
            if chain:
                self.current_revision(task_id)
            return [_copy_json(item) for item in chain]

    def current_revision(self, task_id: str) -> dict[str, Any] | None:
        task_id = _safe_id(task_id, "task id")
        with self._lock:
            chain = self._load_revision_chain(task_id)
            pointer_path = self._current_pointer_path(task_id)
            if not chain:
                if pointer_path.exists() or pointer_path.is_symlink():
                    raise TrainingPlanIntegrityError(
                        "current plan pointer exists without any revisions"
                    )
                return None

            leaf = chain[-1]
            if not pointer_path.is_file():
                if pointer_path.is_symlink():
                    raise TrainingPlanIntegrityError(
                        "current plan pointer cannot be a symlink"
                    )
                self._write_current_pointer(task_id, leaf)
                return _copy_json(leaf)

            pointer = self._read_pointer(pointer_path, task_id)
            matching = next(
                (
                    record
                    for record in chain
                    if record["training_plan_revision_id"]
                    == pointer["training_plan_revision_id"]
                ),
                None,
            )
            if matching is None or (
                pointer["plan_sha256"] != matching["plan_sha256"]
                or pointer["revision"] != matching["revision"]
            ):
                raise TrainingPlanIntegrityError("current training plan pointer changed")
            if matching["training_plan_revision_id"] != leaf["training_plan_revision_id"]:
                # A revision file was durably sealed before an interrupted pointer update.
                self._write_current_pointer(task_id, leaf)
            return _copy_json(leaf)

    def record_decision(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        decision: str,
        actor: str,
        reason: str = "",
    ) -> dict[str, Any]:
        task_id = _safe_id(task_id, "task id")
        revision_id = _safe_id(revision_id, "training plan revision id")
        expected_plan_sha256 = _digest(
            expected_plan_sha256, "expected plan sha256"
        )
        if decision not in PLAN_DECISIONS:
            raise ContractError("decision must be approve, reject, or cancel")

        with self._lock:
            current = self.current_revision(task_id)
            if current is None:
                raise FileNotFoundError("training plan does not exist")
            if current["training_plan_revision_id"] != revision_id:
                raise StaleTrainingPlanError("cannot decide a superseded training plan")
            if current["plan_sha256"] != expected_plan_sha256:
                raise StaleTrainingPlanError(
                    "displayed plan digest does not match the persisted plan"
                )
            approvals = self.list_approvals(task_id, revision_id)
            previous = approvals[-1] if approvals else None
            approval = ApprovalRecord.create(
                approval_id=f"approval_{uuid4().hex}",
                task_id=task_id,
                subject_id=revision_id,
                digest=expected_plan_sha256,
                decision=decision,
                actor=actor,
                reason=reason,
                sequence=len(approvals) + 1,
                previous_approval_id=(previous or {}).get("approval_id"),
                previous_approval_sha256=(previous or {}).get("approval_sha256"),
            ).to_dict()
            self._write_immutable(
                self._approval_path(task_id, revision_id, approval["approval_id"]),
                approval,
            )
            self._write_approval_head(task_id, revision_id, approval)
            return approval

    def approve(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        actor: str,
        reason: str = "",
    ) -> dict[str, Any]:
        return self.record_decision(
            task_id,
            revision_id,
            expected_plan_sha256=expected_plan_sha256,
            decision="approve",
            actor=actor,
            reason=reason,
        )

    def reject(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.record_decision(
            task_id,
            revision_id,
            expected_plan_sha256=expected_plan_sha256,
            decision="reject",
            actor=actor,
            reason=reason,
        )

    def cancel(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.record_decision(
            task_id,
            revision_id,
            expected_plan_sha256=expected_plan_sha256,
            decision="cancel",
            actor=actor,
            reason=reason,
        )

    def list_approvals(
        self, task_id: str, revision_id: str
    ) -> list[dict[str, Any]]:
        task_id = _safe_id(task_id, "task id")
        revision_id = _safe_id(revision_id, "training plan revision id")
        with self._lock:
            plan = self.get_revision(task_id, revision_id)
            approval_dir = self._approval_dir(task_id, revision_id)
            records: list[dict[str, Any]] = []
            if approval_dir.exists():
                if approval_dir.is_symlink() or not approval_dir.is_dir():
                    raise TrainingPlanIntegrityError("approval directory changed")
                for path in sorted(approval_dir.glob("*.json")):
                    if path.is_symlink():
                        raise TrainingPlanIntegrityError(
                            "approval record cannot be a symlink"
                        )
                    record = ApprovalRecord.from_record(read_json(path)).to_dict()
                    if path.stem != record["approval_id"]:
                        raise TrainingPlanIntegrityError(
                            "approval filename and approval_id differ"
                        )
                    if (
                        record["task_id"] != task_id
                        or record["subject_id"] != revision_id
                        or record["digest"] != plan["plan_sha256"]
                    ):
                        raise TrainingPlanIntegrityError(
                            "approval subject or displayed digest changed"
                        )
                    records.append(record)
            records.sort(key=lambda item: int(item["sequence"]))
            for index, record in enumerate(records, start=1):
                if record["sequence"] != index:
                    raise TrainingPlanIntegrityError("approval sequence changed")
                previous = records[index - 2] if index > 1 else None
                if previous is None:
                    if (
                        record["previous_approval_id"] is not None
                        or record["previous_approval_sha256"] is not None
                    ):
                        raise TrainingPlanIntegrityError(
                            "first approval predecessor changed"
                        )
                elif (
                    record["previous_approval_id"] != previous["approval_id"]
                    or record["previous_approval_sha256"]
                    != previous["approval_sha256"]
                ):
                    raise TrainingPlanIntegrityError("approval chain changed")
            self._verify_approval_head(task_id, revision_id, records)
            return [_copy_json(item) for item in records]

    def effective_status(self, task_id: str, revision_id: str) -> str:
        task_id = _safe_id(task_id, "task id")
        revision_id = _safe_id(revision_id, "training plan revision id")
        plan = self.get_revision(task_id, revision_id)
        # Validate the append-only decision chain even for a superseded plan;
        # history views must not hide a tampered approval behind superseded.
        approvals = self.list_approvals(task_id, revision_id)
        current = self.current_revision(task_id)
        if current is None:
            raise TrainingPlanIntegrityError("plan chain has no current revision")
        if current["training_plan_revision_id"] != revision_id:
            return "superseded"
        if not approvals:
            return str(plan["status"])
        return {
            "approve": "approved",
            "reject": "rejected",
            "cancel": "cancelled",
        }[approvals[-1]["decision"]]

    def revision_view(self, task_id: str, revision_id: str) -> dict[str, Any]:
        plan = self.get_revision(task_id, revision_id)
        approvals = self.list_approvals(task_id, revision_id)
        return {
            "plan": plan,
            "effective_status": self.effective_status(task_id, revision_id),
            "latest_approval": approvals[-1] if approvals else None,
        }

    def authorize_use(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        current_spec_revision: int,
        source_snapshot_id: str,
        snapshot_digest: str,
        analysis_id: str,
        analysis_digest: str,
    ) -> dict[str, Any]:
        """Fail closed unless the exact current lineage and digest are approved."""

        task_id = _safe_id(task_id, "task id")
        revision_id = _safe_id(revision_id, "training plan revision id")
        expected_plan_sha256 = _digest(
            expected_plan_sha256, "expected plan sha256"
        )
        # Keep the current-plan, lineage and latest-decision reads in one
        # critical section. Otherwise a concurrent cancel could be appended
        # after the approval read but before this method returned authorization.
        with self._lock:
            current = self.current_revision(task_id)
            if current is None:
                raise FileNotFoundError("training plan does not exist")
            if current["training_plan_revision_id"] != revision_id:
                raise StaleTrainingPlanError(
                    "superseded training plan cannot authorize use"
                )
            expected_lineage = {
                "plan_sha256": expected_plan_sha256,
                "base_spec_revision": _positive_int(
                    current_spec_revision, "current_spec_revision"
                ),
                "source_snapshot_id": _safe_id(
                    source_snapshot_id, "source snapshot id"
                ),
                "snapshot_digest": _digest(snapshot_digest, "snapshot_digest"),
                "analysis_id": _safe_id(analysis_id, "analysis id"),
                "analysis_digest": _digest(analysis_digest, "analysis_digest"),
            }
            drifted = [
                field
                for field, expected in expected_lineage.items()
                if current[field] != expected
            ]
            if drifted:
                raise StaleTrainingPlanError(
                    f"training plan lineage changed: {', '.join(drifted)}"
                )
            approvals = self.list_approvals(task_id, revision_id)
            if not approvals or approvals[-1]["decision"] != "approve":
                status = self.effective_status(task_id, revision_id)
                raise TrainingPlanApprovalRequired(
                    f"exact training plan digest is not approved (status={status})"
                )
            if approvals[-1]["digest"] != current["plan_sha256"]:
                raise TrainingPlanIntegrityError(
                    "approved and displayed digests differ"
                )
            return _copy_json(current)

    def _load_revision_chain(self, task_id: str) -> list[dict[str, Any]]:
        revision_dir = self._revision_dir(task_id)
        if not revision_dir.exists():
            if revision_dir.is_symlink():
                raise TrainingPlanIntegrityError("revision directory cannot be a symlink")
            return []
        if revision_dir.is_symlink() or not revision_dir.is_dir():
            raise TrainingPlanIntegrityError("revision directory changed")
        records: list[dict[str, Any]] = []
        for path in sorted(revision_dir.glob("*.json")):
            if path.is_symlink():
                raise TrainingPlanIntegrityError("plan revision cannot be a symlink")
            plan = TrainingPlanRevision.from_record(read_json(path)).to_dict()
            if path.stem != plan["training_plan_revision_id"]:
                raise TrainingPlanIntegrityError(
                    "plan filename and training_plan_revision_id differ"
                )
            if plan["task_id"] != task_id:
                raise TrainingPlanIntegrityError("training plan task identity changed")
            records.append(plan)
        records.sort(key=lambda item: int(item["revision"]))
        for index, record in enumerate(records, start=1):
            if record["revision"] != index:
                raise TrainingPlanIntegrityError("training plan revision sequence changed")
            previous = records[index - 2] if index > 1 else None
            if previous is None:
                if (
                    record["parent_revision_id"] is not None
                    or record["parent_plan_sha256"] is not None
                ):
                    raise TrainingPlanIntegrityError("first plan parent changed")
            elif (
                record["parent_revision_id"]
                != previous["training_plan_revision_id"]
                or record["parent_plan_sha256"] != previous["plan_sha256"]
            ):
                raise TrainingPlanIntegrityError("training plan revision chain changed")
        return records

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> None:
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise TrainingPlanIntegrityError(
                    f"immutable record path changed: {path.name}"
                )
            if canonical_json(read_json(path)) != canonical_json(value):
                raise TrainingPlanIntegrityError(
                    f"immutable record changed: {path.name}"
                )
            return
        write_json(path, dict(value))

    def _read_pointer(self, path: Path, task_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise TrainingPlanIntegrityError("current plan pointer changed")
        pointer = read_json(path)
        expected = {
            "schema_version",
            "task_id",
            "training_plan_revision_id",
            "plan_sha256",
            "revision",
            "updated_at",
            "pointer_sha256",
        }
        if not isinstance(pointer, dict) or set(pointer) != expected:
            raise TrainingPlanIntegrityError("current plan pointer schema changed")
        observed = canonical_sha256(_unsigned(pointer, "pointer_sha256"))
        if observed != pointer["pointer_sha256"] or pointer["task_id"] != task_id:
            raise TrainingPlanIntegrityError("current plan pointer digest changed")
        return pointer

    def _write_current_pointer(
        self, task_id: str, plan: Mapping[str, Any]
    ) -> None:
        pointer: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "training_plan_revision_id": plan["training_plan_revision_id"],
            "plan_sha256": plan["plan_sha256"],
            "revision": plan["revision"],
            "updated_at": utc_now(),
        }
        pointer["pointer_sha256"] = canonical_sha256(pointer)
        write_json(self._current_pointer_path(task_id), pointer)

    def _write_approval_head(
        self,
        task_id: str,
        revision_id: str,
        approval: Mapping[str, Any],
    ) -> None:
        head: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "subject_id": revision_id,
            "approval_id": approval["approval_id"],
            "approval_sha256": approval["approval_sha256"],
            "sequence": approval["sequence"],
            "updated_at": utc_now(),
        }
        head["head_sha256"] = canonical_sha256(head)
        write_json(self._approval_head_path(task_id, revision_id), head)

    def _verify_approval_head(
        self,
        task_id: str,
        revision_id: str,
        records: list[dict[str, Any]],
    ) -> None:
        path = self._approval_head_path(task_id, revision_id)
        if not records:
            if path.exists() or path.is_symlink():
                raise TrainingPlanIntegrityError(
                    "approval head exists without approval records"
                )
            return
        if path.is_symlink():
            raise TrainingPlanIntegrityError("approval head is missing or changed")
        if not path.is_file():
            if path.exists():
                raise TrainingPlanIntegrityError(
                    "approval head is missing or changed"
                )
            # The approval record is the immutable fact. A crash after writing
            # it but before replacing the mutable head must be restart-safe.
            self._write_approval_head(task_id, revision_id, records[-1])
            return
        head = read_json(path)
        expected = {
            "schema_version",
            "task_id",
            "subject_id",
            "approval_id",
            "approval_sha256",
            "sequence",
            "updated_at",
            "head_sha256",
        }
        if not isinstance(head, dict) or set(head) != expected:
            raise TrainingPlanIntegrityError("approval head schema changed")
        observed = canonical_sha256(_unsigned(head, "head_sha256"))
        sequence = head.get("sequence")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or sequence > len(records)
        ):
            raise TrainingPlanIntegrityError("approval head changed")
        selected = records[sequence - 1]
        if (
            observed != head["head_sha256"]
            or head["task_id"] != task_id
            or head["subject_id"] != revision_id
            or head["approval_id"] != selected["approval_id"]
            or head["approval_sha256"] != selected["approval_sha256"]
            or head["sequence"] != selected["sequence"]
        ):
            raise TrainingPlanIntegrityError("approval head changed")
        if sequence < len(records):
            self._write_approval_head(task_id, revision_id, records[-1])

    def _task_root(self, task_id: str) -> Path:
        task_id = _safe_id(task_id, "task id")
        task_root = self.tasks_root / task_id
        if task_root.is_symlink():
            raise ContractError("task directory cannot be a symlink")
        if not task_root.is_dir():
            raise FileNotFoundError(f"task not found: {task_id}")
        return task_root

    def _plan_root(self, task_id: str) -> Path:
        return self._checked_directory(
            self._task_root(task_id), "training_plans", "training plan directory"
        )

    def _revision_dir(self, task_id: str) -> Path:
        return self._checked_directory(
            self._plan_root(task_id), "revisions", "plan revision directory"
        )

    def _revision_path(self, task_id: str, revision_id: str) -> Path:
        return self._revision_dir(task_id) / f"{_safe_id(revision_id, 'revision id')}.json"

    def _current_pointer_path(self, task_id: str) -> Path:
        return self._plan_root(task_id) / "current.json"

    def _approval_dir(self, task_id: str, revision_id: str) -> Path:
        approval_root = self._checked_directory(
            self._plan_root(task_id), "approvals", "plan approval directory"
        )
        return self._checked_directory(
            approval_root,
            _safe_id(revision_id, "revision id"),
            "plan revision approval directory",
        )

    def _approval_path(
        self, task_id: str, revision_id: str, approval_id: str
    ) -> Path:
        selected_approval = _safe_id(approval_id, "approval id")
        return (
            self._approval_dir(task_id, revision_id)
            / f"{selected_approval}.json"
        )

    def _approval_head_path(self, task_id: str, revision_id: str) -> Path:
        head_root = self._checked_directory(
            self._plan_root(task_id),
            "approval_heads",
            "plan approval head directory",
        )
        return head_root / f"{_safe_id(revision_id, 'revision id')}.json"

    def _checked_directory(self, parent: Path, name: str, label: str) -> Path:
        candidate = parent / name
        if candidate.is_symlink() or (
            candidate.exists() and not candidate.is_dir()
        ):
            raise TrainingPlanIntegrityError(f"{label} changed")
        if candidate.exists() and parent.resolve() not in candidate.resolve().parents:
            raise TrainingPlanIntegrityError(f"unsafe {label}")
        return candidate


__all__ = [
    "ApprovalRecord",
    "PLAN_DECISIONS",
    "PLAN_SUBJECT_TYPE",
    "StaleTrainingPlanError",
    "TrainingPlanApprovalRequired",
    "TrainingPlanIntegrityError",
    "TrainingPlanRevision",
    "TrainingPlanStore",
    "canonical_approval_sha256",
    "canonical_json",
    "canonical_plan_sha256",
    "canonical_sha256",
]
