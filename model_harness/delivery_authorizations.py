from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import fcntl
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .errors import HarnessError
from .io_utils import read_json, write_json


DELIVERY_AUTHORIZATION_SCHEMA_VERSION = "0.1"
DEFAULT_AUTHORIZATION_TTL_SECONDS = 10 * 60
_ACTIONS = {
    "start_task_run",
    "run_sample_inference",
    "build_artifact_bundle",
    "download_artifact_bundle",
}


class DeliveryAuthorizationError(HarnessError):
    """Raised when a delivery capability is missing, stale or replayed."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def delivery_scope_sha256(scope: Mapping[str, Any]) -> str:
    return _canonical_sha256(deepcopy(dict(scope)))


def _safe_id(value: Any, label: str) -> str:
    selected = str(value or "").strip()
    if not selected or Path(selected).name != selected:
        raise DeliveryAuthorizationError(f"invalid {label}")
    return selected


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_utc(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DeliveryAuthorizationError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise DeliveryAuthorizationError(f"invalid {label}")
    return parsed.astimezone(UTC)


class DeliveryAuthorizationStore:
    """Persist and atomically consume exact, human-approved delivery grants.

    Callers must hold the owning ``TrainingWorkspace`` lock around issue,
    reserve and completion so canonical evidence validation and state changes
    form one process-level transaction.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, task_id: str, authorization_id: str) -> Path:
        selected_task = _safe_id(task_id, "task id")
        selected_authorization = _safe_id(
            authorization_id, "delivery authorization id"
        )
        return (
            self.root
            / "tasks"
            / selected_task
            / "delivery_authorizations"
            / f"{selected_authorization}.json"
        )

    @contextmanager
    def _task_lock(self, task_id: str) -> Any:
        selected_task = _safe_id(task_id, "task id")
        directory = self.root / "tasks" / selected_task / "delivery_authorizations"
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".authorization.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _with_digest(record: Mapping[str, Any]) -> dict[str, Any]:
        selected = deepcopy(dict(record))
        selected.pop("authorization_sha256", None)
        selected["authorization_sha256"] = _canonical_sha256(selected)
        return selected

    @staticmethod
    def _validate(record: Mapping[str, Any]) -> dict[str, Any]:
        selected = deepcopy(dict(record))
        if selected.get("schema_version") != DELIVERY_AUTHORIZATION_SCHEMA_VERSION:
            raise DeliveryAuthorizationError(
                "unsupported delivery authorization schema"
            )
        _safe_id(selected.get("authorization_id"), "delivery authorization id")
        _safe_id(selected.get("task_id"), "task id")
        if selected.get("action") not in _ACTIONS:
            raise DeliveryAuthorizationError("invalid delivery authorization action")
        if selected.get("status") not in {
            "issued",
            "consuming",
            "consumed",
            "failed",
            "expired",
            "invalidated",
        }:
            raise DeliveryAuthorizationError("invalid delivery authorization status")
        scope = selected.get("scope")
        if not isinstance(scope, dict):
            raise DeliveryAuthorizationError("delivery authorization scope is missing")
        if delivery_scope_sha256(scope) != selected.get("scope_sha256"):
            raise DeliveryAuthorizationError("delivery authorization scope digest changed")
        token_sha256 = str(selected.get("token_sha256") or "")
        if len(token_sha256) != 64:
            raise DeliveryAuthorizationError("delivery authorization token digest is invalid")
        try:
            int(token_sha256, 16)
        except ValueError as exc:
            raise DeliveryAuthorizationError(
                "delivery authorization token digest is invalid"
            ) from exc
        approval = selected.get("approval_decision")
        if not isinstance(approval, dict):
            raise DeliveryAuthorizationError("delivery approval decision is missing")
        decision = dict(approval)
        decision_sha256 = decision.pop("decision_sha256", None)
        if decision.get("decision") != "approved" or decision.get("actor") != "user":
            raise DeliveryAuthorizationError("delivery authorization lacks user approval")
        if decision.get("verified_by") != "agent_bridge_token":
            raise DeliveryAuthorizationError(
                "delivery authorization lacks a verified agent-bridge approval"
            )
        bridge_token_sha256 = str(decision.get("bridge_token_sha256") or "")
        if len(bridge_token_sha256) != 64:
            raise DeliveryAuthorizationError(
                "delivery authorization bridge proof is invalid"
            )
        try:
            int(bridge_token_sha256, 16)
        except ValueError as exc:
            raise DeliveryAuthorizationError(
                "delivery authorization bridge proof is invalid"
            ) from exc
        _safe_id(decision.get("decision_id"), "delivery approval decision id")
        if not str(decision.get("checkpoint_id") or "").strip():
            raise DeliveryAuthorizationError("delivery approval checkpoint is missing")
        if decision.get("scope_sha256") != selected.get("scope_sha256"):
            raise DeliveryAuthorizationError("delivery approval scope changed")
        if _canonical_sha256(decision) != decision_sha256:
            raise DeliveryAuthorizationError("delivery approval decision digest changed")
        expected_digest = selected.get("authorization_sha256")
        if DeliveryAuthorizationStore._with_digest(selected)[
            "authorization_sha256"
        ] != expected_digest:
            raise DeliveryAuthorizationError("delivery authorization digest changed")
        _parse_utc(selected.get("issued_at_utc"), "issued_at_utc")
        _parse_utc(selected.get("expires_at_utc"), "expires_at_utc")
        return selected

    def issue(
        self,
        *,
        task_id: str,
        action: str,
        scope: Mapping[str, Any],
        approval: Mapping[str, Any],
        ttl_seconds: int = DEFAULT_AUTHORIZATION_TTL_SECONDS,
    ) -> tuple[dict[str, Any], str]:
        selected_task = _safe_id(task_id, "task id")
        if action not in _ACTIONS:
            raise DeliveryAuthorizationError("invalid delivery authorization action")
        if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise DeliveryAuthorizationError("invalid delivery authorization TTL")
        actor = str(approval.get("actor") or "").strip()
        checkpoint_id = str(approval.get("checkpoint_id") or "").strip()
        verified_by = str(approval.get("verified_by") or "").strip()
        bridge_token_sha256 = str(
            approval.get("bridge_token_sha256") or ""
        ).strip().lower()
        if actor != "user" or not checkpoint_id:
            raise DeliveryAuthorizationError(
                "delivery authorization requires a user approval checkpoint"
            )
        if verified_by != "agent_bridge_token" or len(bridge_token_sha256) != 64:
            raise DeliveryAuthorizationError(
                "delivery authorization requires a verified agent-bridge approval"
            )
        try:
            int(bridge_token_sha256, 16)
        except ValueError as exc:
            raise DeliveryAuthorizationError(
                "delivery authorization bridge proof is invalid"
            ) from exc
        selected_scope = deepcopy(dict(scope))
        if selected_scope.get("task_id") != selected_task:
            raise DeliveryAuthorizationError(
                "delivery authorization scope belongs to another task"
            )
        if selected_scope.get("action") != action:
            raise DeliveryAuthorizationError("delivery authorization action scope changed")
        scope_sha256 = delivery_scope_sha256(selected_scope)
        issued_at = _utc_now()
        authorization_id = f"delivery-authorization-{uuid4().hex}"
        decision = {
            "decision_id": f"delivery-approval-{uuid4().hex}",
            "decision": "approved",
            "actor": actor,
            "checkpoint_id": checkpoint_id,
            "action": action,
            "scope_sha256": scope_sha256,
            "verified_by": verified_by,
            "bridge_token_sha256": bridge_token_sha256,
            "created_at_utc": _utc_text(issued_at),
        }
        decision["decision_sha256"] = _canonical_sha256(decision)
        token = secrets.token_urlsafe(32)
        record = self._with_digest(
            {
                "schema_version": DELIVERY_AUTHORIZATION_SCHEMA_VERSION,
                "authorization_id": authorization_id,
                "task_id": selected_task,
                "action": action,
                "scope": selected_scope,
                "scope_sha256": scope_sha256,
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "status": "issued",
                "approval_decision": decision,
                "issued_at_utc": _utc_text(issued_at),
                "expires_at_utc": _utc_text(
                    issued_at + timedelta(seconds=ttl_seconds)
                ),
                "consume_started_at_utc": None,
                "completed_at_utc": None,
                "outcome": None,
            }
        )
        path = self._path(selected_task, authorization_id)
        with self._task_lock(selected_task):
            for existing_path in path.parent.glob("delivery-authorization-*.json"):
                existing = self._validate(read_json(existing_path))
                existing_approval = existing.get("approval_decision") or {}
                if (
                    existing.get("action") == action
                    and existing_approval.get("checkpoint_id") == checkpoint_id
                ):
                    raise DeliveryAuthorizationError(
                        "this agent-bridge approval checkpoint already issued an authorization"
                    )
            if path.exists():
                raise DeliveryAuthorizationError("delivery authorization already exists")
            write_json(path, record)
        return self._validate(record), token

    def get(self, task_id: str, authorization_id: str) -> dict[str, Any]:
        path = self._path(task_id, authorization_id)
        if not path.is_file():
            raise DeliveryAuthorizationError("delivery authorization not found")
        record = self._validate(read_json(path))
        if record["task_id"] != task_id:
            raise DeliveryAuthorizationError(
                "delivery authorization belongs to another task"
            )
        return record

    @staticmethod
    def public(record: Mapping[str, Any]) -> dict[str, Any]:
        selected = deepcopy(dict(record))
        selected.pop("token_sha256", None)
        return selected

    def reserve(
        self,
        *,
        task_id: str,
        authorization_id: str,
        authorization_token: str,
        action: str,
        approved_scope_sha256: str,
        current_scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._task_lock(task_id):
            record = self.get(task_id, authorization_id)
            if record["action"] != action:
                raise DeliveryAuthorizationError(
                    "delivery authorization belongs to another action"
                )
            now = _utc_now()
            if record["status"] != "issued":
                raise DeliveryAuthorizationError(
                    "delivery authorization is already used or unavailable"
                )
            if _parse_utc(record["expires_at_utc"], "expires_at_utc") <= now:
                record["status"] = "expired"
                record["completed_at_utc"] = _utc_text(now)
                write_json(
                    self._path(task_id, authorization_id), self._with_digest(record)
                )
                raise DeliveryAuthorizationError("delivery authorization expired")
            token_sha256 = hashlib.sha256(
                str(authorization_token or "").encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(token_sha256, record["token_sha256"]):
                raise DeliveryAuthorizationError("delivery authorization token is invalid")
            current_scope_sha256 = delivery_scope_sha256(current_scope)
            if (
                approved_scope_sha256 != record["scope_sha256"]
                or current_scope_sha256 != record["scope_sha256"]
            ):
                record["status"] = "invalidated"
                record["completed_at_utc"] = _utc_text(now)
                record["outcome"] = {
                    "status": "scope_drift",
                    "current_scope_sha256": current_scope_sha256,
                }
                write_json(
                    self._path(task_id, authorization_id), self._with_digest(record)
                )
                raise DeliveryAuthorizationError(
                    "delivery authorization scope is missing, changed or stale"
                )
            record["status"] = "consuming"
            record["consume_started_at_utc"] = _utc_text(now)
            record["outcome"] = None
            record = self._with_digest(record)
            write_json(self._path(task_id, authorization_id), record)
            return self._validate(record)

    def complete(
        self,
        *,
        task_id: str,
        authorization_id: str,
        succeeded: bool,
        outcome: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._task_lock(task_id):
            record = self.get(task_id, authorization_id)
            if record["status"] != "consuming":
                raise DeliveryAuthorizationError(
                    "delivery authorization is not in a consumable state"
                )
            record["status"] = "consumed" if succeeded else "failed"
            record["completed_at_utc"] = _utc_text(_utc_now())
            record["outcome"] = deepcopy(dict(outcome))
            record = self._with_digest(record)
            write_json(self._path(task_id, authorization_id), record)
            return self._validate(record)
