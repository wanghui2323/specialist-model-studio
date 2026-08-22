from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json
from .recipe_versions import (
    ActivationCallback,
    RecipeVersionStore,
    RevisionResolver,
    canonical_json,
    content_digest,
    utc_now,
    validation_report_digest,
)


class RecipeSpecError(ContractError):
    """A declarative RecipeSpec is unsafe or outside the supported allowlist."""


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_FORBIDDEN_KEYS = {
    "code",
    "command",
    "dependencies",
    "dependency",
    "dynamic_import",
    "entrypoint",
    "executable",
    "file",
    "import",
    "module",
    "package",
    "path",
    "pip",
    "python",
    "requirements",
    "script",
    "shell",
    "source",
    "url",
}
_FORBIDDEN_STRING_MARKERS = (
    "http://",
    "https://",
    "file://",
    "git+",
    "pip install",
    "__import__",
    "subprocess",
    "dynamic import",
)


def _unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    location: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RecipeSpecError(
            f"unknown field(s) at {location}: {', '.join(unknown)}"
        )


def _scan_for_unsafe_values(value: Any, location: str = "RecipeSpec") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            selected = str(key).strip().lower().replace("-", "_")
            if selected in _FORBIDDEN_KEYS:
                raise RecipeSpecError(f"forbidden field at {location}: {key}")
            _scan_for_unsafe_values(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_for_unsafe_values(nested, f"{location}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _FORBIDDEN_STRING_MARKERS):
            raise RecipeSpecError(f"executable or remote value at {location}")


def _required_mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RecipeSpecError(f"{location} must be an object")
    return dict(value)


def _strict_int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecipeSpecError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise RecipeSpecError(f"{label} must be between {minimum} and {maximum}")
    return value


def _strict_float(
    value: Any,
    *,
    minimum: float,
    maximum: float,
    label: str,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecipeSpecError(f"{label} must be numeric")
    selected = float(value)
    if selected < minimum or selected > maximum:
        raise RecipeSpecError(f"{label} must be between {minimum} and {maximum}")
    return selected


def _enum(value: Any, allowed: set[str], label: str) -> str:
    selected = str(value)
    if selected not in allowed:
        raise RecipeSpecError(
            f"{label} must be one of: {', '.join(sorted(allowed))}"
        )
    return selected


def _identifier(value: Any, label: str) -> str:
    selected = str(value)
    if not _IDENTIFIER.fullmatch(selected):
        raise RecipeSpecError(
            f"{label} must be a lowercase identifier with letters, digits and hyphens"
        )
    return selected


@dataclass(frozen=True)
class RecipeSpec:
    schema_version: str
    engine: str
    recipe_id: str
    adapter_id: str
    features: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    resources: dict[str, Any]
    evaluation: dict[str, Any]

    @classmethod
    def template(cls) -> dict[str, Any]:
        """Return the only trusted engine's reviewable default declaration."""

        return {
            "schema_version": "0.1",
            "engine": "sklearn_audio_keyword_v1",
            "recipe_id": "audio-keyword-classification",
            "adapter_id": "audio-keyword-class-folder-zip",
            "features": {
                "kind": "mfcc_log_mel",
                "sample_rate_hz": 16_000,
                "clip_seconds": 1.0,
                "n_mels": 24,
                "n_mfcc": 13,
            },
            "candidates": [
                {"kind": "most_frequent_baseline"},
                {"kind": "logistic_regression"},
                {"kind": "extra_trees", "n_estimators": 160},
            ],
            "resources": {
                "device": "cpu",
                "max_candidate_models": 3,
                "max_audio_files": 20_000,
            },
            "evaluation": {
                "primary_metric": "validation_macro_f1",
                "metrics": ["accuracy", "macro_f1", "worst_class_recall"],
                "validation_fraction": 0.2,
                "test_fraction": 0.2,
                "seed": 42,
                "group_by": "speaker_id",
            },
        }

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> RecipeSpec:
        value = _required_mapping(raw, "RecipeSpec")
        _scan_for_unsafe_values(value)
        _unknown_fields(
            value,
            {
                "schema_version",
                "engine",
                "recipe_id",
                "adapter_id",
                "features",
                "candidates",
                "resources",
                "evaluation",
            },
            "RecipeSpec",
        )
        required = {
            "schema_version",
            "engine",
            "recipe_id",
            "adapter_id",
            "features",
            "candidates",
            "resources",
        }
        missing = sorted(required - set(value))
        if missing:
            raise RecipeSpecError(f"missing RecipeSpec field(s): {', '.join(missing)}")
        if value["schema_version"] != "0.1":
            raise RecipeSpecError("RecipeSpec schema_version must be 0.1")
        if value["engine"] != "sklearn_audio_keyword_v1":
            raise RecipeSpecError(
                "only engine=sklearn_audio_keyword_v1 is allowed in this environment"
            )
        recipe_id = _identifier(value["recipe_id"], "recipe_id")
        adapter_id = _identifier(value["adapter_id"], "adapter_id")
        if recipe_id != "audio-keyword-classification":
            raise RecipeSpecError(
                "sklearn_audio_keyword_v1 requires "
                "recipe_id=audio-keyword-classification"
            )
        if adapter_id != "audio-keyword-class-folder-zip":
            raise RecipeSpecError(
                "sklearn_audio_keyword_v1 requires "
                "adapter_id=audio-keyword-class-folder-zip"
            )
        features = cls._parse_features(value["features"])
        candidates = cls._parse_candidates(value["candidates"])
        resources = cls._parse_resources(value["resources"])
        if len(candidates) > resources["max_candidate_models"]:
            raise RecipeSpecError(
                "candidate count exceeds resources.max_candidate_models"
            )
        evaluation = cls._parse_evaluation(value.get("evaluation", {}))
        return cls(
            schema_version="0.1",
            engine="sklearn_audio_keyword_v1",
            recipe_id=recipe_id,
            adapter_id=adapter_id,
            features=features,
            candidates=tuple(candidates),
            resources=resources,
            evaluation=evaluation,
        )

    @staticmethod
    def _parse_features(raw: Any) -> dict[str, Any]:
        value = _required_mapping(raw, "features")
        _unknown_fields(
            value,
            {
                "kind",
                "sample_rate_hz",
                "clip_seconds",
                "n_mels",
                "n_mfcc",
            },
            "features",
        )
        kind = _enum(
            value.get("kind"), {"mfcc_log_mel"}, "features.kind"
        )
        sample_rate = _strict_int(
            value.get("sample_rate_hz"),
            minimum=16_000,
            maximum=16_000,
            label="features.sample_rate_hz",
        )
        n_mels = _strict_int(
            value.get("n_mels"),
            minimum=12,
            maximum=64,
            label="features.n_mels",
        )
        n_mfcc = _strict_int(
            value.get("n_mfcc"),
            minimum=6,
            maximum=32,
            label="features.n_mfcc",
        )
        if n_mfcc > n_mels:
            raise RecipeSpecError("features.n_mfcc cannot exceed n_mels")
        return {
            "kind": kind,
            "sample_rate_hz": sample_rate,
            "n_mels": n_mels,
            "n_mfcc": n_mfcc,
            "clip_seconds": _strict_float(
                value.get("clip_seconds"),
                minimum=0.25,
                maximum=3.0,
                label="features.clip_seconds",
            ),
        }

    @classmethod
    def _parse_candidates(cls, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise RecipeSpecError("candidates must be a non-empty list")
        if len(raw) > 3:
            raise RecipeSpecError("candidates cannot contain more than 3 entries")
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            value = _required_mapping(item, f"candidates[{index}]")
            kind = _enum(
                value.get("kind"),
                {
                    "extra_trees",
                    "logistic_regression",
                    "most_frequent_baseline",
                },
                f"candidates[{index}].kind",
            )
            if kind in {"most_frequent_baseline", "logistic_regression"}:
                _unknown_fields(
                    value,
                    {"kind"},
                    f"candidates[{index}]",
                )
                candidate = {"kind": kind}
            else:
                _unknown_fields(
                    value,
                    {"kind", "n_estimators"},
                    f"candidates[{index}]",
                )
                candidate = {
                    "kind": kind,
                    "n_estimators": _strict_int(
                        value.get("n_estimators"),
                        minimum=50,
                        maximum=1_000,
                        label=f"candidates[{index}].n_estimators",
                    ),
                }
            if kind in seen:
                raise RecipeSpecError("duplicate candidate kind")
            seen.add(kind)
            selected.append(candidate)
        return selected

    @staticmethod
    def _parse_resources(raw: Any) -> dict[str, Any]:
        value = _required_mapping(raw, "resources")
        _unknown_fields(
            value,
            {"device", "max_candidate_models", "max_audio_files"},
            "resources",
        )
        return {
            "device": _enum(value.get("device"), {"cpu"}, "resources.device"),
            "max_candidate_models": _strict_int(
                value.get("max_candidate_models"),
                minimum=1,
                maximum=3,
                label="resources.max_candidate_models",
            ),
            "max_audio_files": _strict_int(
                value.get("max_audio_files"),
                minimum=12,
                maximum=20_000,
                label="resources.max_audio_files",
            ),
        }

    @staticmethod
    def _parse_evaluation(raw: Any) -> dict[str, Any]:
        value = _required_mapping(raw, "evaluation")
        _unknown_fields(
            value,
            {
                "primary_metric",
                "metrics",
                "validation_fraction",
                "test_fraction",
                "seed",
                "group_by",
            },
            "evaluation",
        )
        primary_metric = _enum(
            value.get("primary_metric", "validation_macro_f1"),
            {"validation_macro_f1"},
            "evaluation.primary_metric",
        )
        metrics = value.get(
            "metrics", ["accuracy", "macro_f1", "worst_class_recall"]
        )
        if (
            not isinstance(metrics, list)
            or not metrics
            or any(
                metric
                not in {"accuracy", "macro_f1", "worst_class_recall"}
                for metric in metrics
            )
        ):
            raise RecipeSpecError(
                "evaluation.metrics contains an unsupported metric"
            )
        if len(set(metrics)) != len(metrics):
            raise RecipeSpecError("evaluation.metrics cannot contain duplicates")
        validation_fraction = _strict_float(
            value.get("validation_fraction", 0.2),
            minimum=0.1,
            maximum=0.3,
            label="evaluation.validation_fraction",
        )
        test_fraction = _strict_float(
            value.get("test_fraction", 0.2),
            minimum=0.1,
            maximum=0.3,
            label="evaluation.test_fraction",
        )
        return {
            "primary_metric": primary_metric,
            "metrics": list(metrics),
            "validation_fraction": validation_fraction,
            "test_fraction": test_fraction,
            "seed": _strict_int(
                value.get("seed", 42),
                minimum=0,
                maximum=2_147_483_647,
                label="evaluation.seed",
            ),
            "group_by": _enum(
                value.get("group_by", "speaker_id"),
                {"speaker_id"},
                "evaluation.group_by",
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["candidates"] = [deepcopy(item) for item in self.candidates]
        return value


@dataclass(frozen=True)
class ValidationReport:
    schema_version: str
    attempt_id: str
    valid: bool
    engine: str | None
    checks: tuple[dict[str, Any], ...]
    errors: tuple[dict[str, Any], ...]
    candidate_digest: str | None
    report_digest: str

    @classmethod
    def create(
        cls,
        *,
        attempt_id: str,
        valid: bool,
        engine: str | None,
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        candidate_digest: str | None,
    ) -> ValidationReport:
        core = {
            "schema_version": "0.1",
            "attempt_id": attempt_id,
            "valid": valid,
            "engine": engine,
            "checks": checks,
            "errors": errors,
            "candidate_digest": candidate_digest,
        }
        return cls(
            **core,
            report_digest=content_digest(core),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["checks"] = [deepcopy(item) for item in self.checks]
        value["errors"] = [deepcopy(item) for item in self.errors]
        return value


@dataclass(frozen=True)
class BuildAttempt:
    schema_version: str
    attempt_id: str
    task_id: str
    base_spec_revision: int
    build_type: str
    status: str
    created_at: str
    updated_at: str
    candidate_digest: str | None = None
    validation_digest: str | None = None
    registration_intent_id: str | None = None
    failure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecipeFactory:
    """Persistent, declaration-only Recipe authoring and validation service."""

    def __init__(
        self,
        root: str | Path,
        *,
        version_store: RecipeVersionStore | None = None,
        recover: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.attempts_dir = self.root / "build_attempts"
        self.attempts_dir.mkdir(parents=True, exist_ok=True)
        self.version_store = version_store or RecipeVersionStore(
            self.root / "versions"
        )
        self._lock = RLock()
        self.recovered_attempts = self.recover_incomplete() if recover else []

    @staticmethod
    def spec_template() -> dict[str, Any]:
        return RecipeSpec.template()

    def start_build(
        self,
        *,
        task_id: str,
        base_spec_revision: int,
        spec: Mapping[str, Any],
        build_type: str = "declarative",
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        if not task_id or Path(task_id).name != task_id:
            raise ContractError(f"invalid task id: {task_id!r}")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision must be a positive integer")
        attempt_id = attempt_id or f"build-{uuid4().hex[:20]}"
        if Path(attempt_id).name != attempt_id:
            raise ContractError(f"invalid attempt id: {attempt_id!r}")
        attempt_dir = self._attempt_dir(attempt_id, require_exists=False)
        if attempt_dir.exists():
            raise ContractError(f"build attempt already exists: {attempt_id}")
        attempt_dir.mkdir(parents=True)
        now = utc_now()
        attempt = BuildAttempt(
            schema_version="0.1",
            attempt_id=attempt_id,
            task_id=task_id,
            base_spec_revision=base_spec_revision,
            build_type=str(build_type),
            status="authoring",
            created_at=now,
            updated_at=now,
        ).to_dict()
        write_json(attempt_dir / "state.json", attempt)
        self._event(attempt_id, "build.authoring_started", {})

        if build_type != "declarative":
            # Never persist submitted source text. This environment only accepts JSON.
            return self._block_executable_build(attempt_id, str(build_type))
        try:
            normalized_raw = json.loads(json.dumps(dict(spec), ensure_ascii=False))
        except (TypeError, ValueError) as error:
            return self._fail_authoring(
                attempt_id,
                code="invalid_recipe_spec",
                message=f"RecipeSpec must be JSON: {error}",
            )
        write_json(attempt_dir / "recipe_spec.json", normalized_raw)
        return self.get_attempt(attempt_id)

    def request_python_build(
        self,
        *,
        task_id: str,
        base_spec_revision: int,
        python_source: str | None = None,
    ) -> dict[str, Any]:
        # ``python_source`` is intentionally ignored and never persisted.
        del python_source
        return self.start_build(
            task_id=task_id,
            base_spec_revision=base_spec_revision,
            spec={},
            build_type="python",
        )

    def validate(self, attempt_id: str) -> dict[str, Any]:
        with self._lock:
            attempt = self.get_attempt(attempt_id)
            if attempt["status"] == "awaiting_registration":
                return attempt
            if attempt["status"] != "authoring":
                raise ContractError(
                    f"cannot validate build in status {attempt['status']}"
                )
            attempt.update({"status": "validating", "updated_at": utc_now()})
            write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
            self._event(attempt_id, "build.validation_started", {})
        return self._finish_validation(attempt_id)

    def cancel(
        self,
        attempt_id: str,
        *,
        reason: str = "cancelled by user",
    ) -> dict[str, Any]:
        with self._lock:
            attempt = self.get_attempt(attempt_id)
            if attempt["status"] == "cancelled":
                return attempt
            if attempt["status"] != "authoring":
                raise ContractError(
                    "only an authoring BuildAttempt can be cancelled"
                )
            attempt.update(
                {
                    "status": "cancelled",
                    "updated_at": utc_now(),
                    "failure": {
                        "code": "cancelled",
                        "message": reason.strip() or "cancelled by user",
                    },
                }
            )
            write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
            self._event(attempt_id, "build.cancelled", {"reason": reason})
            return attempt

    def recover_incomplete(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        for state_path in sorted(self.attempts_dir.glob("*/state.json")):
            attempt = read_json(state_path)
            if attempt.get("status") == "validating":
                recovered.append(self._finish_validation(str(attempt["attempt_id"])))
            elif attempt.get("status") == "authoring":
                recovered.append(attempt)
        return recovered

    def recover_registrations(
        self,
        *,
        resolve_spec_revision: RevisionResolver,
        activate: ActivationCallback | None = None,
    ) -> list[dict[str, Any]]:
        """Replay idempotent product bindings and reconcile BuildAttempt state."""

        recovered = self.version_store.recover_transactions(
            resolve_spec_revision=resolve_spec_revision,
            activate=activate,
        )
        for intent in recovered:
            if intent.get("status") != "registered":
                continue
            attempt_id = str(intent["attempt_id"])
            attempt = self.get_attempt(attempt_id)
            if attempt.get("status") == "registered":
                continue
            attempt.update({"status": "registered", "updated_at": utc_now()})
            write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
            self._event(
                attempt_id,
                "build.registration_recovered",
                {"intent_id": intent["intent_id"]},
            )
        return recovered

    def prepare_registration(self, attempt_id: str) -> dict[str, Any]:
        with self._lock:
            attempt = self.get_attempt(attempt_id)
            if attempt["status"] != "awaiting_registration":
                raise ContractError(
                    "BuildAttempt must pass validation before registration"
                )
            existing = attempt.get("registration_intent_id")
            if existing:
                return self.version_store.get_intent(str(existing))
            attempt_dir = self._attempt_dir(attempt_id)
            candidate = read_json(attempt_dir / "candidate.json")
            report = read_json(attempt_dir / "validation_report.json")
            if content_digest(candidate) != attempt.get("candidate_digest"):
                raise RecipeSpecError(
                    "candidate changed after BuildAttempt validation"
                )
            if (
                validation_report_digest(report)
                != attempt.get("validation_digest")
                or report.get("report_digest")
                != attempt.get("validation_digest")
                or report.get("candidate_digest")
                != attempt.get("candidate_digest")
            ):
                raise RecipeSpecError(
                    "ValidationReport changed after BuildAttempt validation"
                )
            intent = self.version_store.create_registration_intent(
                task_id=str(attempt["task_id"]),
                attempt_id=attempt_id,
                base_spec_revision=int(attempt["base_spec_revision"]),
                candidate=candidate,
                validation_report=report,
            )
            attempt.update(
                {
                    "registration_intent_id": intent["intent_id"],
                    "updated_at": utc_now(),
                }
            )
            write_json(attempt_dir / "state.json", attempt)
            self._event(
                attempt_id,
                "build.awaiting_registration_approval",
                {"intent_id": intent["intent_id"]},
            )
            return intent

    def register(
        self,
        attempt_id: str,
        *,
        approval: Mapping[str, Any],
        candidate_digest: str,
        validation_digest: str,
        current_spec_revision: int,
        activate: ActivationCallback | None = None,
    ) -> dict[str, Any]:
        attempt = self.get_attempt(attempt_id)
        intent_id = attempt.get("registration_intent_id")
        if not intent_id:
            raise ContractError("prepare_registration must run before approval")
        intent = self.version_store.approve_and_register(
            str(intent_id),
            approval=approval,
            candidate_digest=candidate_digest,
            validation_digest=validation_digest,
            current_spec_revision=current_spec_revision,
            activate=activate,
        )
        if intent["status"] == "registered":
            attempt.update({"status": "registered", "updated_at": utc_now()})
            write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
            self._event(
                attempt_id,
                "build.registered",
                {"intent_id": intent["intent_id"]},
            )
        return intent

    def reject_registration(
        self,
        attempt_id: str,
        *,
        actor: str,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        attempt = self.get_attempt(attempt_id)
        intent_id = attempt.get("registration_intent_id")
        if not intent_id:
            raise ContractError("prepare_registration must run before rejection")
        intent = self.version_store.reject(
            str(intent_id), actor=actor, reason=reason
        )
        attempt.update(
            {
                "status": "registration_rejected",
                "updated_at": utc_now(),
                "failure": {"code": "registration_rejected", "message": reason},
            }
        )
        write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
        self._event(
            attempt_id,
            "build.registration_rejected",
            {"intent_id": intent["intent_id"]},
        )
        return intent

    def get_attempt(self, attempt_id: str) -> dict[str, Any]:
        path = self._attempt_dir(attempt_id) / "state.json"
        if not path.is_file():
            raise FileNotFoundError(f"build attempt not found: {attempt_id}")
        return read_json(path)

    def list_attempts(self) -> list[dict[str, Any]]:
        return [
            read_json(path)
            for path in sorted(
                self.attempts_dir.glob("*/state.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        ]

    def candidate(self, attempt_id: str) -> dict[str, Any]:
        attempt = self.get_attempt(attempt_id)
        if not attempt.get("candidate_digest"):
            raise FileNotFoundError("validated candidate is not available")
        candidate = read_json(self._attempt_dir(attempt_id) / "candidate.json")
        if content_digest(candidate) != attempt["candidate_digest"]:
            raise RecipeSpecError("candidate changed after validation")
        return candidate

    def validation_report(self, attempt_id: str) -> dict[str, Any]:
        report = read_json(
            self._attempt_dir(attempt_id) / "validation_report.json"
        )
        if validation_report_digest(report) != report.get("report_digest"):
            raise RecipeSpecError("ValidationReport changed after validation")
        return report

    def events(self, attempt_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        path = self._attempt_dir(attempt_id) / "events.ndjson"
        if not path.is_file():
            return []
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return [record for record in records if int(record["seq"]) > after_seq]

    @staticmethod
    def _candidate(spec: RecipeSpec) -> dict[str, Any]:
        value = spec.to_dict()
        extra_trees = next(
            (
                item
                for item in spec.candidates
                if item["kind"] == "extra_trees"
            ),
            None,
        )
        return {
            "schema_version": "0.1",
            "kind": "declarative_recipe_candidate",
            "engine": spec.engine,
            "recipe_spec": value,
            "compiled_contract_overrides": {
                "model_selection": {
                    "primary_metric": spec.evaluation["primary_metric"],
                    "candidates": [item["kind"] for item in spec.candidates],
                },
                "recipe_options": {
                    "clip_seconds": spec.features["clip_seconds"],
                    "n_mels": spec.features["n_mels"],
                    "n_mfcc": spec.features["n_mfcc"],
                    "extra_trees_estimators": (
                        extra_trees["n_estimators"] if extra_trees else 160
                    ),
                },
                "compute_budget": deepcopy(spec.resources),
                "dataset": {
                    "kind": "audio_keyword_class_folder",
                    "sample_rate": spec.features["sample_rate_hz"],
                    "channels": 1,
                    "random_seed": spec.evaluation["seed"],
                    "group_by": spec.evaluation["group_by"],
                    "split": {
                        "train": 1.0
                        - spec.evaluation["validation_fraction"]
                        - spec.evaluation["test_fraction"],
                        "validation": spec.evaluation["validation_fraction"],
                        "test": spec.evaluation["test_fraction"],
                    },
                },
            },
            "recipe_manifest": {
                "plugin_id": spec.recipe_id,
                "version": "candidate",
                "contract_schema_version": "0.2",
                "task_type": "offline-audio-keyword-classification",
                "input_description": "labelled WAV files grouped by keyword",
                "output_description": "one keyword class per audio clip",
                "device": "cpu",
                "purpose": "user-data",
                "modalities": ["audio"],
                "objectives": ["classification"],
                "data_adapter": spec.adapter_id,
                "target_kinds": ["multiclass", "binary"],
                "capability_tags": [
                    "declarative-factory",
                    "audio-keyword",
                    spec.engine,
                ],
            },
            "adapter_manifest": {
                "adapter_id": spec.adapter_id,
                "version": "candidate",
                "description": "validated WAV keyword folders",
                "modalities": ["audio"],
                "file_extensions": [".zip"],
            },
        }

    def _finish_validation(self, attempt_id: str) -> dict[str, Any]:
        with self._lock:
            attempt = self.get_attempt(attempt_id)
            if attempt["status"] != "validating":
                return attempt
            attempt_dir = self._attempt_dir(attempt_id)
            try:
                raw = read_json(attempt_dir / "recipe_spec.json")
                spec = RecipeSpec.parse(raw)
                candidate = self._candidate(spec)
                candidate_digest = content_digest(candidate)
                self._write_immutable(attempt_dir / "candidate.json", candidate)
                report = ValidationReport.create(
                    attempt_id=attempt_id,
                    valid=True,
                    engine=spec.engine,
                    checks=[
                        {"id": "json_allowlist", "passed": True},
                        {"id": "engine_allowlist", "passed": True},
                        {"id": "feature_bounds", "passed": True},
                        {"id": "candidate_allowlist", "passed": True},
                        {"id": "resource_bounds", "passed": True},
                        {"id": "no_executable_content", "passed": True},
                    ],
                    errors=[],
                    candidate_digest=candidate_digest,
                ).to_dict()
                self._write_immutable(
                    attempt_dir / "validation_report.json", report
                )
                attempt.update(
                    {
                        "status": "awaiting_registration",
                        "updated_at": utc_now(),
                        "candidate_digest": candidate_digest,
                        "validation_digest": report["report_digest"],
                        "failure": None,
                    }
                )
                write_json(attempt_dir / "state.json", attempt)
                self._event(
                    attempt_id,
                    "build.validation_passed",
                    {
                        "candidate_digest": candidate_digest,
                        "validation_digest": report["report_digest"],
                    },
                )
                return attempt
            except RecipeSpecError as error:
                report = ValidationReport.create(
                    attempt_id=attempt_id,
                    valid=False,
                    engine=None,
                    checks=[{"id": "json_allowlist", "passed": False}],
                    errors=[{"code": "invalid_recipe_spec", "message": str(error)}],
                    candidate_digest=None,
                ).to_dict()
                self._write_immutable(
                    attempt_dir / "validation_report.json", report
                )
                attempt.update(
                    {
                        "status": "failed",
                        "updated_at": utc_now(),
                        "validation_digest": report["report_digest"],
                        "failure": {
                            "code": "invalid_recipe_spec",
                            "message": str(error),
                        },
                    }
                )
                write_json(attempt_dir / "state.json", attempt)
                self._event(
                    attempt_id,
                    "build.validation_failed",
                    {"code": "invalid_recipe_spec", "message": str(error)},
                )
                return attempt

    def _block_executable_build(
        self, attempt_id: str, build_type: str
    ) -> dict[str, Any]:
        message = (
            "Executable Recipe builds are blocked in this environment; "
            "submit an allowlisted declarative RecipeSpec JSON."
        )
        attempt = self.get_attempt(attempt_id)
        report = ValidationReport.create(
            attempt_id=attempt_id,
            valid=False,
            engine=None,
            checks=[{"id": "declarative_only", "passed": False}],
            errors=[{"code": "blocked_environment", "message": message}],
            candidate_digest=None,
        ).to_dict()
        self._write_immutable(
            self._attempt_dir(attempt_id) / "validation_report.json", report
        )
        attempt.update(
            {
                "status": "failed",
                "updated_at": utc_now(),
                "validation_digest": report["report_digest"],
                "failure": {
                    "code": "blocked_environment",
                    "message": message,
                    "requested_build_type": build_type,
                },
            }
        )
        write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
        self._event(
            attempt_id,
            "build.blocked_environment",
            {"requested_build_type": build_type},
        )
        return attempt

    def _fail_authoring(
        self, attempt_id: str, *, code: str, message: str
    ) -> dict[str, Any]:
        attempt = self.get_attempt(attempt_id)
        attempt.update(
            {
                "status": "failed",
                "updated_at": utc_now(),
                "failure": {"code": code, "message": message},
            }
        )
        write_json(self._attempt_dir(attempt_id) / "state.json", attempt)
        self._event(attempt_id, "build.authoring_failed", {"code": code})
        return attempt

    def _attempt_dir(
        self, attempt_id: str, *, require_exists: bool = True
    ) -> Path:
        if not attempt_id or Path(attempt_id).name != attempt_id:
            raise ContractError(f"invalid attempt id: {attempt_id!r}")
        selected = (self.attempts_dir / attempt_id).resolve()
        if selected.parent != self.attempts_dir:
            raise ContractError(f"invalid attempt id: {attempt_id!r}")
        if require_exists and not selected.is_dir():
            raise FileNotFoundError(f"build attempt not found: {attempt_id}")
        return selected

    @staticmethod
    def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
        if path.is_file():
            if canonical_json(read_json(path)) != canonical_json(value):
                raise RecipeSpecError(f"immutable factory artifact changed: {path.name}")
            return
        write_json(path, dict(value))

    def _event(
        self,
        attempt_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        path = self._attempt_dir(attempt_id) / "events.ndjson"
        sequence = 1
        if path.is_file():
            sequence += sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        record = {
            "seq": sequence,
            "type": event_type,
            "at": utc_now(),
            "payload": dict(payload),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
