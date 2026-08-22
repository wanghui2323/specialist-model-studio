from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping
from uuid import uuid4

from .errors import ContractError, HarnessError
from .io_utils import read_json, write_json


class VersionIntegrityError(ContractError):
    """Raised when an immutable Recipe Factory record changed on disk."""


class StaleSpecRevisionError(ContractError):
    """Raised when registration targets an obsolete task-spec revision."""


class RegistrationRecoveryRequired(HarnessError):
    """Raised when the external activation callback must be replayed."""


ActivationCallback = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    None,
]
RevisionResolver = Callable[[str], int]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validation_report_digest(report: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "report_digest"}
    return content_digest(payload)


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    if path.is_file():
        if canonical_json(read_json(path)) != canonical_json(value):
            raise VersionIntegrityError(f"immutable record changed: {path.name}")
        return
    write_json(path, dict(value))


def _safe_record_id(value: str, label: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ContractError(f"invalid {label}: {value!r}")
    return value


@dataclass(frozen=True)
class RecipeVersion:
    schema_version: str
    version_id: str
    task_id: str
    attempt_id: str
    recipe_id: str
    engine: str
    candidate_digest: str
    validation_digest: str
    base_spec_revision: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdapterVersion:
    schema_version: str
    version_id: str
    task_id: str
    attempt_id: str
    adapter_id: str
    engine: str
    candidate_digest: str
    validation_digest: str
    base_spec_revision: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegistrationIntent:
    schema_version: str
    intent_id: str
    task_id: str
    attempt_id: str
    recipe_version_id: str
    adapter_version_id: str
    candidate_digest: str
    validation_digest: str
    base_spec_revision: int
    status: str
    approval: dict[str, Any] | None
    created_at: str
    updated_at: str
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecipeVersionStore:
    """Atomic immutable versions plus recoverable registration transactions.

    The activation callback is deliberately injected by the product layer. It must
    be idempotent for the supplied ``intent_id`` because recovery can replay it
    after a process crash.
    """

    ACTIVE_SCHEMA_VERSION = "0.1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.recipe_dir = self.root / "recipe_versions"
        self.adapter_dir = self.root / "adapter_versions"
        self.intent_dir = self.root / "registration_intents"
        for directory in (self.recipe_dir, self.adapter_dir, self.intent_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.active_path = self.root / "active_versions.json"
        if not self.active_path.is_file():
            write_json(
                self.active_path,
                {"schema_version": self.ACTIVE_SCHEMA_VERSION, "tasks": {}},
            )
        self._lock = RLock()

    def create_registration_intent(
        self,
        *,
        task_id: str,
        attempt_id: str,
        base_spec_revision: int,
        candidate: Mapping[str, Any],
        validation_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        task_id = _safe_record_id(task_id, "task id")
        attempt_id = _safe_record_id(attempt_id, "attempt id")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision must be a positive integer")

        candidate_value = deepcopy(dict(candidate))
        candidate_digest = content_digest(candidate_value)
        report_value = deepcopy(dict(validation_report))
        report_digest = validation_report_digest(report_value)
        if report_value.get("report_digest") != report_digest:
            raise VersionIntegrityError("validation report digest does not match")
        if not report_value.get("valid"):
            raise ContractError("only a passing ValidationReport can be registered")
        if report_value.get("candidate_digest") != candidate_digest:
            raise VersionIntegrityError(
                "ValidationReport does not describe the supplied candidate"
            )

        recipe_manifest = candidate_value.get("recipe_manifest")
        adapter_manifest = candidate_value.get("adapter_manifest")
        if not isinstance(recipe_manifest, dict) or not isinstance(
            adapter_manifest, dict
        ):
            raise ContractError("candidate must contain recipe and adapter manifests")
        recipe_id = str(recipe_manifest.get("plugin_id", ""))
        adapter_id = str(adapter_manifest.get("adapter_id", ""))
        engine = str(candidate_value.get("engine", ""))
        if not recipe_id or not adapter_id or not engine:
            raise ContractError("candidate manifest identifiers are incomplete")

        # A crash may happen after the intent is durable but before its id is
        # copied back to the BuildAttempt. Reuse that intent instead of creating
        # a second approval transaction.
        for intent_path in sorted(self.intent_dir.glob("*/intent.json")):
            existing = read_json(intent_path)
            if (
                existing.get("task_id") == task_id
                and existing.get("attempt_id") == attempt_id
            ):
                if (
                    existing.get("candidate_digest") != candidate_digest
                    or existing.get("validation_digest") != report_digest
                    or int(existing.get("base_spec_revision", 0))
                    != base_spec_revision
                ):
                    raise VersionIntegrityError(
                        "existing registration intent differs from BuildAttempt"
                    )
                return existing

        identity = content_digest(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "candidate_digest": candidate_digest,
                "base_spec_revision": base_spec_revision,
            }
        )[:20]
        recipe_path = self.recipe_dir / f"recipe-version-{identity}.json"
        adapter_path = self.adapter_dir / f"adapter-version-{identity}.json"
        if recipe_path.is_file():
            created_at = str(read_json(recipe_path)["created_at"])
        elif adapter_path.is_file():
            created_at = str(read_json(adapter_path)["created_at"])
        else:
            created_at = utc_now()
        recipe_version = RecipeVersion(
            schema_version="0.1",
            version_id=f"recipe-version-{identity}",
            task_id=task_id,
            attempt_id=attempt_id,
            recipe_id=recipe_id,
            engine=engine,
            candidate_digest=candidate_digest,
            validation_digest=report_digest,
            base_spec_revision=int(base_spec_revision),
            created_at=created_at,
        )
        adapter_version = AdapterVersion(
            schema_version="0.1",
            version_id=f"adapter-version-{identity}",
            task_id=task_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            engine=engine,
            candidate_digest=candidate_digest,
            validation_digest=report_digest,
            base_spec_revision=int(base_spec_revision),
            created_at=created_at,
        )
        intent_id = f"registration-{uuid4().hex[:20]}"
        intent = RegistrationIntent(
            schema_version="0.1",
            intent_id=intent_id,
            task_id=task_id,
            attempt_id=attempt_id,
            recipe_version_id=recipe_version.version_id,
            adapter_version_id=adapter_version.version_id,
            candidate_digest=candidate_digest,
            validation_digest=report_digest,
            base_spec_revision=int(base_spec_revision),
            status="awaiting_approval",
            approval=None,
            created_at=created_at,
            updated_at=created_at,
        )
        with self._lock:
            _write_immutable(
                recipe_path,
                recipe_version.to_dict(),
            )
            _write_immutable(
                adapter_path,
                adapter_version.to_dict(),
            )
            _write_immutable(
                self.intent_dir / intent_id / "candidate.json",
                candidate_value,
            )
            _write_immutable(
                self.intent_dir / intent_id / "validation_report.json",
                report_value,
            )
            self._write_intent(intent.to_dict())
            self._event(intent_id, "registration.awaiting_approval", {})
        return intent.to_dict()

    def get_recipe_version(self, version_id: str) -> dict[str, Any]:
        version_id = _safe_record_id(version_id, "recipe version id")
        return read_json(self.recipe_dir / f"{version_id}.json")

    def get_adapter_version(self, version_id: str) -> dict[str, Any]:
        version_id = _safe_record_id(version_id, "adapter version id")
        return read_json(self.adapter_dir / f"{version_id}.json")

    def get_intent(self, intent_id: str) -> dict[str, Any]:
        intent_id = _safe_record_id(intent_id, "registration intent id")
        path = self.intent_dir / intent_id / "intent.json"
        if not path.is_file():
            raise FileNotFoundError(f"registration intent not found: {intent_id}")
        return read_json(path)

    def reject(
        self,
        intent_id: str,
        *,
        actor: str,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        if not actor.strip():
            raise ContractError("registration rejection requires an actor")
        with self._lock:
            intent = self.get_intent(intent_id)
            if intent["status"] == "rejected":
                return intent
            if intent["status"] != "awaiting_approval":
                raise ContractError(
                    f"cannot reject registration in status {intent['status']}"
                )
            intent.update(
                {
                    "status": "rejected",
                    "approval": {
                        "decision": "rejected",
                        "actor": actor.strip(),
                        "reason": reason.strip(),
                        "decided_at": utc_now(),
                    },
                    "updated_at": utc_now(),
                    "last_error": None,
                }
            )
            self._write_intent(intent)
            self._event(intent_id, "registration.rejected", {"actor": actor})
            return intent

    def approve_and_register(
        self,
        intent_id: str,
        *,
        approval: Mapping[str, Any],
        candidate_digest: str,
        validation_digest: str,
        current_spec_revision: int,
        activate: ActivationCallback | None = None,
    ) -> dict[str, Any]:
        actor = str(approval.get("actor", "")).strip()
        if approval.get("decision") != "approved" or not actor:
            raise ContractError(
                "registration requires an explicit approved decision and actor"
            )
        with self._lock:
            intent = self.get_intent(intent_id)
            if intent["status"] == "registered":
                self._verify_registration_inputs(
                    intent,
                    candidate_digest=candidate_digest,
                    validation_digest=validation_digest,
                    current_spec_revision=current_spec_revision,
                )
                return intent
            if intent["status"] not in {
                "awaiting_approval",
                "applying",
                "recovery_required",
            }:
                raise ContractError(
                    f"cannot approve registration in status {intent['status']}"
                )
            self._verify_registration_inputs(
                intent,
                candidate_digest=candidate_digest,
                validation_digest=validation_digest,
                current_spec_revision=current_spec_revision,
            )
            if intent["status"] == "awaiting_approval":
                intent.update(
                    {
                        "status": "applying",
                        "approval": {
                            "decision": "approved",
                            "actor": actor,
                            "reason": str(approval.get("reason", "")).strip(),
                            "decided_at": utc_now(),
                        },
                        "updated_at": utc_now(),
                        "last_error": None,
                    }
                )
                self._write_intent(intent)
                self._event(intent_id, "registration.approved", {"actor": actor})
            return self._complete_registration(intent, activate)

    def recover_transactions(
        self,
        *,
        resolve_spec_revision: RevisionResolver,
        activate: ActivationCallback | None = None,
    ) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        for path in sorted(self.intent_dir.glob("*/intent.json")):
            intent = read_json(path)
            if intent.get("status") not in {"applying", "recovery_required"}:
                continue
            try:
                current_revision = int(resolve_spec_revision(str(intent["task_id"])))
                self._verify_registration_inputs(
                    intent,
                    candidate_digest=str(intent["candidate_digest"]),
                    validation_digest=str(intent["validation_digest"]),
                    current_spec_revision=current_revision,
                )
                recovered.append(self._complete_registration(intent, activate))
            except Exception as error:  # recovery must leave an inspectable record
                latest = self.get_intent(str(intent["intent_id"]))
                if latest.get("status") != "registered":
                    latest.update(
                        {
                            "status": "recovery_required",
                            "updated_at": utc_now(),
                            "last_error": str(error),
                        }
                    )
                    self._write_intent(latest)
                    self._event(
                        str(intent["intent_id"]),
                        "registration.recovery_failed",
                        {"error": str(error)},
                    )
                    recovered.append(latest)
        return recovered

    def active_for_task(self, task_id: str) -> dict[str, Any] | None:
        task_id = _safe_record_id(task_id, "task id")
        active = read_json(self.active_path)
        selected = active.get("tasks", {}).get(task_id)
        return deepcopy(selected) if isinstance(selected, dict) else None

    def events(self, intent_id: str) -> list[dict[str, Any]]:
        intent_id = _safe_record_id(intent_id, "registration intent id")
        path = self.intent_dir / intent_id / "events.ndjson"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _verify_registration_inputs(
        self,
        intent: Mapping[str, Any],
        *,
        candidate_digest: str,
        validation_digest: str,
        current_spec_revision: int,
    ) -> None:
        if candidate_digest != intent.get("candidate_digest"):
            raise VersionIntegrityError("candidate digest approval does not match intent")
        if validation_digest != intent.get("validation_digest"):
            raise VersionIntegrityError(
                "ValidationReport digest approval does not match intent"
            )
        if isinstance(current_spec_revision, bool) or int(
            current_spec_revision
        ) != int(intent["base_spec_revision"]):
            raise StaleSpecRevisionError(
                "task spec changed after Recipe Factory authoring; rebuild required"
            )
        intent_root = self.intent_dir / str(intent["intent_id"])
        candidate = read_json(intent_root / "candidate.json")
        report = read_json(intent_root / "validation_report.json")
        if content_digest(candidate) != intent["candidate_digest"]:
            raise VersionIntegrityError("candidate content changed after validation")
        if validation_report_digest(report) != intent["validation_digest"]:
            raise VersionIntegrityError("ValidationReport changed after validation")
        if report.get("report_digest") != intent["validation_digest"]:
            raise VersionIntegrityError("ValidationReport self-digest is invalid")
        if not report.get("valid"):
            raise ContractError("registration requires a passing ValidationReport")
        if report.get("candidate_digest") != intent["candidate_digest"]:
            raise VersionIntegrityError("ValidationReport candidate digest is invalid")
        recipe_version = self.get_recipe_version(
            str(intent["recipe_version_id"])
        )
        adapter_version = self.get_adapter_version(
            str(intent["adapter_version_id"])
        )
        recipe_manifest = candidate.get("recipe_manifest", {})
        adapter_manifest = candidate.get("adapter_manifest", {})
        shared_expected = {
            "task_id": intent["task_id"],
            "attempt_id": intent["attempt_id"],
            "candidate_digest": intent["candidate_digest"],
            "validation_digest": intent["validation_digest"],
            "base_spec_revision": intent["base_spec_revision"],
            "engine": candidate.get("engine"),
        }
        for label, version in (
            ("RecipeVersion", recipe_version),
            ("AdapterVersion", adapter_version),
        ):
            for key, expected in shared_expected.items():
                if version.get(key) != expected:
                    raise VersionIntegrityError(
                        f"{label} field changed after validation: {key}"
                    )
        if recipe_version.get("recipe_id") != recipe_manifest.get("plugin_id"):
            raise VersionIntegrityError("RecipeVersion recipe_id changed")
        if adapter_version.get("adapter_id") != adapter_manifest.get("adapter_id"):
            raise VersionIntegrityError("AdapterVersion adapter_id changed")

    def _complete_registration(
        self,
        intent: dict[str, Any],
        activate: ActivationCallback | None,
    ) -> dict[str, Any]:
        intent_id = str(intent["intent_id"])
        recipe_version = self.get_recipe_version(str(intent["recipe_version_id"]))
        adapter_version = self.get_adapter_version(str(intent["adapter_version_id"]))
        candidate = read_json(self.intent_dir / intent_id / "candidate.json")
        try:
            if activate is not None:
                activate(
                    deepcopy(recipe_version),
                    deepcopy(adapter_version),
                    deepcopy(candidate),
                    deepcopy(intent),
                )
            active = read_json(self.active_path)
            tasks = dict(active.get("tasks", {}))
            tasks[str(intent["task_id"])] = {
                "intent_id": intent_id,
                "recipe_version_id": intent["recipe_version_id"],
                "adapter_version_id": intent["adapter_version_id"],
                "candidate_digest": intent["candidate_digest"],
                "validation_digest": intent["validation_digest"],
                "base_spec_revision": intent["base_spec_revision"],
                "activated_at": utc_now(),
            }
            write_json(
                self.active_path,
                {"schema_version": self.ACTIVE_SCHEMA_VERSION, "tasks": tasks},
            )
            intent.update(
                {
                    "status": "registered",
                    "updated_at": utc_now(),
                    "last_error": None,
                }
            )
            self._write_intent(intent)
            self._event(intent_id, "registration.registered", {})
            return intent
        except Exception as error:
            intent.update(
                {
                    "status": "recovery_required",
                    "updated_at": utc_now(),
                    "last_error": str(error),
                }
            )
            self._write_intent(intent)
            self._event(
                intent_id,
                "registration.recovery_required",
                {"error": str(error)},
            )
            raise RegistrationRecoveryRequired(str(error)) from error

    def _write_intent(self, intent: Mapping[str, Any]) -> None:
        intent_id = _safe_record_id(str(intent["intent_id"]), "intent id")
        write_json(self.intent_dir / intent_id / "intent.json", dict(intent))

    def _event(
        self,
        intent_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        event_path = self.intent_dir / intent_id / "events.ndjson"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        sequence = 1
        if event_path.is_file():
            sequence += sum(
                1
                for line in event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        record = {
            "seq": sequence,
            "type": event_type,
            "at": utc_now(),
            "payload": dict(payload),
        }
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
