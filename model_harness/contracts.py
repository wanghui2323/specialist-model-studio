from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractError, PluginError
from .launch_preflight import validate_launch_resource_policy
from .plugins import PluginRegistry, default_registry

SUPPORTED_MODES = {"delegate", "guided"}
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONTRACT_REVISION_SCHEMA_VERSION = "0.1"
CONTRACT_REVISION_SUBJECT_TYPE = "contract_revision"


class ContractRevisionConflictError(ContractError):
    """Raised when a confirmation does not target the current exact revision."""


class ContractRevisionIntegrityError(ContractError):
    """Raised when an immutable contract revision changed after persistence."""


class ApprovalDecisionIntegrityError(ContractError):
    """Raised when an immutable contract approval changed after persistence."""


def _canonical_json(value: Any) -> bytes:
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


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    """Serialize without reordering nested contract fields."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _persisted_json_sha256(value: Any) -> str:
    """Match the stable JSON representation written by ``io_utils.write_json``."""

    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not JSON serializable: {exc}") from exc


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be non-empty text")
    return value.strip()


def _safe_record_id(value: Any, label: str) -> str:
    selected = _nonempty(value, label)
    if Path(selected).name != selected or selected in {".", ".."} or "\\" in selected:
        raise ContractError(f"invalid {label}: {selected!r}")
    return selected


def _sha256(value: Any, label: str) -> str:
    selected = _nonempty(value, label)
    if not _SHA256_PATTERN.fullmatch(selected):
        raise ContractError(f"{label} must be a lowercase sha256 hex digest")
    return selected


def _record_sha256(record: Mapping[str, Any], digest_field: str) -> str:
    return _canonical_sha256(
        {key: value for key, value in record.items() if key != digest_field}
    )


CONTRACT_REVISION_FIELDS = frozenset(
    {
        "schema_version",
        "contract_revision_id",
        "contract_sha256",
        "task_id",
        "spec_revision_id",
        "dataset_id",
        "dataset_fingerprint_sha256",
        "created_at_utc",
        "contract_snapshot",
        "revision_sha256",
    }
)


APPROVAL_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "approval_decision_id",
        "task_id",
        "subject_type",
        "contract_revision_id",
        "contract_sha256",
        "decision",
        "actor",
        "checkpoint_id",
        "confirmations",
        "created_at_utc",
        "decision_sha256",
    }
)


@dataclass(frozen=True)
class ContractRevision:
    """An immutable contract snapshot bound to TaskSpec and dataset identities."""

    _record: bytes

    @classmethod
    def create(
        cls,
        *,
        contract_revision_id: str,
        task_id: str,
        spec_revision_id: str,
        dataset_id: str,
        dataset_fingerprint_sha256: str,
        contract_snapshot: Mapping[str, Any],
        created_at_utc: str | None = None,
    ) -> ContractRevision:
        snapshot = _copy_json(contract_snapshot)
        record: dict[str, Any] = {
            "schema_version": CONTRACT_REVISION_SCHEMA_VERSION,
            "contract_revision_id": contract_revision_id,
            "contract_sha256": _persisted_json_sha256(snapshot),
            "task_id": task_id,
            "spec_revision_id": spec_revision_id,
            "dataset_id": dataset_id,
            "dataset_fingerprint_sha256": dataset_fingerprint_sha256,
            "created_at_utc": created_at_utc or datetime.now(UTC).isoformat(),
            "contract_snapshot": snapshot,
        }
        record["revision_sha256"] = _record_sha256(record, "revision_sha256")
        return cls.from_record(record)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> ContractRevision:
        record = _copy_json(value)
        if not isinstance(record, dict):
            raise ContractRevisionIntegrityError("contract revision must be an object")
        if set(record) != CONTRACT_REVISION_FIELDS:
            raise ContractRevisionIntegrityError("contract revision schema changed")
        if record["schema_version"] != CONTRACT_REVISION_SCHEMA_VERSION:
            raise ContractRevisionIntegrityError("unsupported contract revision schema")
        _safe_record_id(record["contract_revision_id"], "contract revision id")
        _safe_record_id(record["task_id"], "task id")
        _nonempty(record["spec_revision_id"], "spec_revision_id")
        _safe_record_id(record["dataset_id"], "dataset id")
        _sha256(record["dataset_fingerprint_sha256"], "dataset fingerprint")
        _nonempty(record["created_at_utc"], "created_at_utc")
        snapshot = record["contract_snapshot"]
        if not isinstance(snapshot, dict):
            raise ContractRevisionIntegrityError("contract_snapshot must be an object")
        if snapshot.get("task_id") != record["task_id"]:
            raise ContractRevisionIntegrityError(
                "contract snapshot belongs to another task"
            )
        _sha256(record["contract_sha256"], "contract_sha256")
        if _persisted_json_sha256(snapshot) != record["contract_sha256"]:
            raise ContractRevisionIntegrityError("contract snapshot digest changed")
        _sha256(record["revision_sha256"], "revision_sha256")
        if _record_sha256(record, "revision_sha256") != record["revision_sha256"]:
            raise ContractRevisionIntegrityError("contract revision digest changed")
        return cls(_json_bytes(record))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._record.decode("utf-8"))

    def identity(self) -> dict[str, str]:
        record = self.to_dict()
        return {
            key: str(record[key])
            for key in (
                "contract_revision_id",
                "contract_sha256",
                "task_id",
                "spec_revision_id",
                "dataset_id",
                "dataset_fingerprint_sha256",
            )
        }


@dataclass(frozen=True)
class ApprovalDecision:
    """An append-only human decision bound to one exact ContractRevision."""

    _record: bytes

    @classmethod
    def create(
        cls,
        *,
        approval_decision_id: str,
        revision: Mapping[str, Any],
        actor: str,
        checkpoint_id: str,
        confirmations: Mapping[str, Any],
        created_at_utc: str | None = None,
    ) -> ApprovalDecision:
        selected_revision = ContractRevision.from_record(revision).to_dict()
        record: dict[str, Any] = {
            "schema_version": CONTRACT_REVISION_SCHEMA_VERSION,
            "approval_decision_id": approval_decision_id,
            "task_id": selected_revision["task_id"],
            "subject_type": CONTRACT_REVISION_SUBJECT_TYPE,
            "contract_revision_id": selected_revision["contract_revision_id"],
            "contract_sha256": selected_revision["contract_sha256"],
            "decision": "approved",
            "actor": actor,
            "checkpoint_id": checkpoint_id,
            "confirmations": _copy_json(confirmations),
            "created_at_utc": created_at_utc or datetime.now(UTC).isoformat(),
        }
        record["decision_sha256"] = _record_sha256(record, "decision_sha256")
        return cls.from_record(record)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> ApprovalDecision:
        record = _copy_json(value)
        if not isinstance(record, dict):
            raise ApprovalDecisionIntegrityError("approval decision must be an object")
        if set(record) != APPROVAL_DECISION_FIELDS:
            raise ApprovalDecisionIntegrityError("approval decision schema changed")
        if record["schema_version"] != CONTRACT_REVISION_SCHEMA_VERSION:
            raise ApprovalDecisionIntegrityError("unsupported approval decision schema")
        _safe_record_id(record["approval_decision_id"], "approval decision id")
        _safe_record_id(record["task_id"], "task id")
        if record["subject_type"] != CONTRACT_REVISION_SUBJECT_TYPE:
            raise ApprovalDecisionIntegrityError("approval subject must be contract_revision")
        _safe_record_id(record["contract_revision_id"], "contract revision id")
        _sha256(record["contract_sha256"], "contract_sha256")
        if record["decision"] != "approved":
            raise ApprovalDecisionIntegrityError("contract confirmation must be approved")
        _nonempty(record["actor"], "approval actor")
        _nonempty(record["checkpoint_id"], "checkpoint_id")
        confirmations = record["confirmations"]
        if not isinstance(confirmations, dict):
            raise ApprovalDecisionIntegrityError("confirmations must be an object")
        required = ("data_authorized", "labels_reviewed", "gates_reviewed")
        if any(confirmations.get(field) is not True for field in required):
            raise ApprovalDecisionIntegrityError(
                "approval decision is missing required confirmations"
            )
        _nonempty(record["created_at_utc"], "created_at_utc")
        _sha256(record["decision_sha256"], "decision_sha256")
        if _record_sha256(record, "decision_sha256") != record["decision_sha256"]:
            raise ApprovalDecisionIntegrityError("approval decision digest changed")
        return cls(_json_bytes(record))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._record.decode("utf-8"))


@dataclass(frozen=True)
class TaskContract:
    path: Path
    raw: dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw["task_id"])

    @property
    def mode(self) -> str:
        return str(self.raw["interaction"]["mode"])

    @property
    def recipe(self) -> str:
        return str(self.raw["recipe"])


def _require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"{key} must be an object")
    return value


def _require_nonempty_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be non-empty text")
    return value.strip()


def validate_contract(
    data: dict[str, Any],
    registry: PluginRegistry | None = None,
) -> None:
    if not isinstance(data, dict):
        raise ContractError("contract root must be an object")
    _require_nonempty_text(data, "task_id")
    _require_nonempty_text(data, "business_goal")
    recipe = _require_nonempty_text(data, "recipe")
    selected_registry = registry or default_registry()
    try:
        plugin = selected_registry.get_recipe(recipe)
    except PluginError as exc:
        raise ContractError(str(exc)) from exc

    interaction = _require_mapping(data, "interaction")
    mode = _require_nonempty_text(interaction, "mode")
    if mode not in SUPPORTED_MODES:
        raise ContractError(
            f"interaction.mode must be one of {sorted(SUPPORTED_MODES)}"
        )

    human_gates = data.get("human_gates")
    if not isinstance(human_gates, list) or not human_gates:
        raise ContractError("human_gates must be a non-empty list")

    optimization = data.get("optimization", {})
    if not isinstance(optimization, dict):
        raise ContractError("optimization must be an object")
    if optimization.get("mode", "recommend") != "recommend":
        raise ContractError("v0.2 supports optimization.mode=recommend only")
    if optimization.get("require_approval", True) is not True:
        raise ContractError("v0.2 requires optimization.require_approval=true")
    if "max_iterations" in optimization and (
        not isinstance(optimization["max_iterations"], int)
        or optimization["max_iterations"] < 0
    ):
        raise ContractError("optimization.max_iterations must be a non-negative integer")

    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise ContractError("diagnostics must be an object")
    if "minimum_test_samples" in diagnostics:
        value = diagnostics["minimum_test_samples"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 20:
            raise ContractError(
                "diagnostics.minimum_test_samples must be an integer >= 20"
            )

    validate_launch_resource_policy(data.get("launch_resource_policy"))

    model_binding = data.get("model_binding")
    if model_binding is not None:
        if not isinstance(model_binding, dict):
            raise ContractError("model_binding must be an object")
        for key in (
            "model_binding_revision_id",
            "source_snapshot_id",
            "repository_analysis_id",
            "provider",
            "repository",
        ):
            _require_nonempty_text(model_binding, key)
        if model_binding["provider"] not in {"github", "huggingface"}:
            raise ContractError("model_binding.provider is unsupported")
        commit = _require_nonempty_text(model_binding, "resolved_commit")
        if not _COMMIT_PATTERN.fullmatch(commit):
            raise ContractError("model_binding.resolved_commit must be a full commit")
        for key in (
            "binding_digest",
            "source_snapshot_digest",
            "repository_analysis_digest",
            "tree_manifest_sha256",
        ):
            digest = _require_nonempty_text(model_binding, key)
            if not _SHA256_PATTERN.fullmatch(digest):
                raise ContractError(f"model_binding.{key} must be sha256")
        bound_revision = model_binding.get("bound_spec_revision")
        if (
            isinstance(bound_revision, bool)
            or not isinstance(bound_revision, int)
            or bound_revision < 1
        ):
            raise ContractError(
                "model_binding.bound_spec_revision must be a positive integer"
            )

    plugin.validate_contract(data)


def load_contract(
    path: str | Path,
    registry: PluginRegistry | None = None,
) -> TaskContract:
    contract_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"contract not found: {contract_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    validate_contract(raw, registry=registry)
    return TaskContract(path=contract_path, raw=raw)
