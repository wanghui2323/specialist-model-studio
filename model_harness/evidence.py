from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any
from uuid import uuid4

import joblib
import numpy as np

from .errors import ContractError
from .io_utils import read_json, sha256_file, write_json


EVIDENCE_SCHEMA_VERSION = "0.1"
SUPPORTED_JOBLIB_RECIPES = frozenset(
    {
        "digit-classification",
        "image-folder-classification",
        "tabular-regression",
        "audio-keyword-classification",
    }
)
DELIVERABLE_ALLOWLIST = frozenset(
    {
        "model.joblib",
        "model_card.md",
        "metrics.json",
        "confusion_matrix.csv",
        "optimization_strategies.json",
        "learning_report.md",
        "inference_example.py",
        "label_mapping.json",
        "feature_config.json",
        "model_asset_provenance.json",
        "base_model/model.onnx",
        "base_model/config.json",
    }
)
PRIVATE_OR_INTERNAL_ARTIFACTS = {
    "failure_samples.json": "may contain sample-level user data",
    "dataset_report.json": "internal dataset inventory",
    "test_predictions.csv": "held-out test labels and predictions",
    "test_reference.joblib": "held-out test reference",
    "test_reference.npz": "held-out test reference",
}
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class EvidenceError(ContractError):
    """An evidence object cannot be created from the supplied run."""


class InferenceBlocked(EvidenceError):
    """Inference stopped before a trusted prediction could be accepted."""

    def __init__(self, message: str, check: dict[str, Any]) -> None:
        super().__init__(message)
        self.check = check
        self.check_id = str(check["check_id"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _run_state_evidence_fingerprint(state: dict[str, Any]) -> str:
    """Hash stable outcome fields, excluding event sequence and timestamps."""

    return _canonical_hash(
        {
            key: state.get(key)
            for key in (
                "run_id",
                "task_id",
                "plugin_id",
                "parent_run_id",
                "status",
                "error",
                "offline_gates_passed",
                "artifact_count",
            )
        }
    )


def _safe_run_dir(run_dir: str | Path) -> Path:
    resolved = Path(run_dir).expanduser().resolve()
    if not resolved.is_dir() or resolved.is_symlink():
        raise EvidenceError("run directory is missing or unsafe")
    return resolved


def _safe_subdirectory(run_dir: Path, *parts: str) -> Path:
    path = run_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    if path.is_symlink() or resolved != path.absolute() or run_dir not in resolved.parents:
        raise EvidenceError("evidence directory escaped the run directory")
    return path


def _manifest_artifact_path(artifact_dir: Path, name: Any) -> Path | None:
    """Resolve one manifest entry while permitting safe nested artifacts."""

    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        return None
    pure = PurePosixPath(name)
    if (
        pure.is_absolute()
        or _WINDOWS_ABSOLUTE.match(name)
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        return None
    candidate = artifact_dir.joinpath(*pure.parts)
    current = candidate
    while current != artifact_dir:
        if current.is_symlink():
            return None
        current = current.parent
    try:
        target = candidate.resolve()
    except OSError:
        return None
    if artifact_dir not in target.parents or not target.is_file():
        return None
    return target


def _load_run_files(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        state = read_json(run_dir / "run_state.json")
        manifest = read_json(run_dir / "run_manifest.json")
        contract = read_json(run_dir / "task_contract.json")
    except (OSError, ValueError) as exc:
        raise EvidenceError("run state, manifest, and contract must be readable JSON") from exc
    if not all(isinstance(item, dict) for item in (state, manifest, contract)):
        raise EvidenceError("run state, manifest, and contract must be JSON objects")
    return state, manifest, contract


def _integrity_snapshot(run_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        state, manifest, contract = _load_run_files(run_dir)
    except EvidenceError as exc:
        return {
            "state": {},
            "manifest": {},
            "contract": {},
            "checks": [],
            "errors": [str(exc)],
            "status": "failed",
        }

    identity_fields = ("run_id", "task_id")
    for field in identity_fields:
        values = [state.get(field), manifest.get(field)]
        passed = bool(values[0]) and values[0] == values[1]
        checks.append({"check": f"identity:{field}", "passed": passed})
        if not passed:
            errors.append(f"run {field} mismatch")
    recipe_passed = bool(manifest.get("recipe")) and manifest.get("recipe") == contract.get(
        "recipe"
    )
    checks.append({"check": "identity:recipe", "passed": recipe_passed})
    if not recipe_passed:
        errors.append("run recipe mismatch")

    contract_path = run_dir / "task_contract.json"
    expected_contract_hash = str(manifest.get("contract_snapshot_sha256", ""))
    actual_contract_hash = sha256_file(contract_path)
    contract_passed = bool(expected_contract_hash) and actual_contract_hash == expected_contract_hash
    checks.append(
        {
            "check": "contract_snapshot_sha256",
            "passed": contract_passed,
            "expected_sha256": expected_contract_hash,
            "actual_sha256": actual_contract_hash,
        }
    )
    if not contract_passed:
        errors.append("task contract hash mismatch")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        errors.append("run manifest has no artifact inventory")
        artifacts = {}
    artifact_dir = (run_dir / "artifacts").resolve()
    for name, expected in sorted(artifacts.items()):
        target = _manifest_artifact_path(artifact_dir, name)
        exists = target is not None
        expected_details = expected if isinstance(expected, dict) else {}
        expected_hash = str(expected_details.get("sha256", ""))
        expected_size = expected_details.get("bytes", expected_details.get("size_bytes"))
        actual_hash = sha256_file(target) if target is not None else None
        actual_size = target.stat().st_size if target is not None else None
        passed = bool(
            exists
            and expected_hash
            and actual_hash == expected_hash
            and isinstance(expected_size, int)
            and actual_size == expected_size
        )
        checks.append(
            {
                "check": f"artifact:{name}",
                "passed": passed,
                "sha256": actual_hash,
                "size_bytes": actual_size,
            }
        )
        if not passed:
            errors.append(f"artifact integrity mismatch: {name}")

    return {
        "state": state,
        "manifest": manifest,
        "contract": contract,
        "checks": checks,
        "errors": errors,
        "status": "passed" if not errors else "failed",
    }


class EvaluationReport:
    """Build and persist a truth-preserving evaluation conclusion for one Run."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = _safe_run_dir(run_dir)
        self.evidence_dir = _safe_subdirectory(self.run_dir, "evidence")
        self.path = self.evidence_dir / "evaluation_report.json"
        self._lock = RLock()

    def build(
        self,
        *,
        minimum_test_samples: int = 20,
        test_contaminated: bool = False,
    ) -> dict[str, Any]:
        if (
            isinstance(minimum_test_samples, bool)
            or not isinstance(minimum_test_samples, int)
            or minimum_test_samples <= 0
        ):
            raise EvidenceError("minimum_test_samples must be a positive integer")
        with self._lock:
            integrity = _integrity_snapshot(self.run_dir)
            state = integrity["state"]
            manifest = integrity["manifest"]
            run_status = str(state.get("status") or "unknown")
            metrics_path = self.run_dir / "artifacts" / "metrics.json"
            metrics: dict[str, Any] = {}
            if metrics_path.is_file() and not metrics_path.is_symlink():
                try:
                    loaded = read_json(metrics_path)
                    if isinstance(loaded, dict):
                        metrics = loaded
                except (OSError, ValueError):
                    pass

            gate_checks = metrics.get("gate_checks", {})
            individual_gates = {
                str(name): bool(value)
                for name, value in gate_checks.items()
                if name != "all_offline_gates_passed" and isinstance(value, bool)
            } if isinstance(gate_checks, dict) else {}
            if individual_gates:
                metric_gate_status = (
                    "passed" if all(individual_gates.values()) else "failed"
                )
            else:
                metric_gate_status = "not_evaluated"

            split_counts = metrics.get("split_counts", {})
            raw_test_count = (
                split_counts.get("test", 0) if isinstance(split_counts, dict) else 0
            )
            test_sample_count = (
                int(raw_test_count)
                if isinstance(raw_test_count, (int, float))
                and not isinstance(raw_test_count, bool)
                and np.isfinite(raw_test_count)
                and raw_test_count >= 0
                else 0
            )
            contamination_detected = bool(
                test_contaminated
                or metrics.get("test_contaminated")
                or metrics.get("test_set_used_for_selection") is True
            )
            evidence_reasons: list[str] = []
            if test_sample_count < minimum_test_samples:
                evidence_reasons.append(
                    f"test sample count {test_sample_count} is below {minimum_test_samples}"
                )
            if contamination_detected:
                evidence_reasons.append("test evidence is contaminated or used for selection")
            if not metrics:
                evidence_reasons.append("metrics are missing or unreadable")
            if integrity["status"] != "passed":
                evidence_reasons.append("run artifact integrity is not established")
            evidence_status = (
                "insufficient_evidence" if evidence_reasons else "sufficient"
            )

            release_ready = bool(
                run_status == "completed"
                and integrity["status"] == "passed"
                and metric_gate_status == "passed"
                and evidence_status == "sufficient"
            )
            if run_status != "completed":
                conclusion = "run_incomplete"
            elif integrity["status"] != "passed":
                conclusion = "integrity_failed"
            elif evidence_status != "sufficient":
                conclusion = "insufficient_evidence"
            elif metric_gate_status == "failed":
                conclusion = "quality_failed"
            elif metric_gate_status == "not_evaluated":
                conclusion = "metrics_missing"
            else:
                conclusion = "release_ready"

            previous = self.get(required=False)
            now = _now()
            report = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "report_id": (
                    previous.get("report_id")
                    if previous
                    else f"evaluation-{uuid4().hex[:12]}"
                ),
                "run_id": state.get("run_id") or manifest.get("run_id"),
                "task_id": state.get("task_id") or manifest.get("task_id"),
                "recipe": manifest.get("recipe"),
                "run_status": run_status,
                "integrity_status": integrity["status"],
                "metric_gate_status": metric_gate_status,
                "evidence_status": evidence_status,
                "conclusion": conclusion,
                "release_ready": release_ready,
                "test_sample_count": test_sample_count,
                "minimum_test_samples": minimum_test_samples,
                "test_contaminated": contamination_detected,
                "evidence_reasons": evidence_reasons,
                "metric_gates": individual_gates,
                "integrity_checks": integrity["checks"],
                "integrity_errors": integrity["errors"],
                "inputs": {
                    "run_state_sha256": (
                        sha256_file(self.run_dir / "run_state.json")
                        if (self.run_dir / "run_state.json").is_file()
                        else None
                    ),
                    "run_state_evidence_fingerprint_sha256": (
                        _run_state_evidence_fingerprint(state) if state else None
                    ),
                    "run_manifest_sha256": (
                        sha256_file(self.run_dir / "run_manifest.json")
                        if (self.run_dir / "run_manifest.json").is_file()
                        else None
                    ),
                    "metrics_sha256": (
                        sha256_file(metrics_path) if metrics_path.is_file() else None
                    ),
                },
                "created_at": previous.get("created_at", now) if previous else now,
                "updated_at": now,
            }
            if previous:
                comparable_previous = {
                    key: value
                    for key, value in previous.items()
                    if key != "updated_at"
                }
                comparable_report = {
                    key: value
                    for key, value in report.items()
                    if key != "updated_at"
                }
                if comparable_previous == comparable_report:
                    return previous
            write_json(self.path, report)
            return report

    def get(self, *, required: bool = True) -> dict[str, Any] | None:
        if not self.path.is_file():
            if required:
                raise FileNotFoundError("evaluation report not found")
            return None
        report = read_json(self.path)
        if not isinstance(report, dict) or not report.get("report_id"):
            raise EvidenceError("evaluation report is corrupt")
        return report


class InferenceCheck:
    """Execute and persist a hash-bound prediction against an explicit example."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = _safe_run_dir(run_dir)
        self.checks_dir = _safe_subdirectory(
            self.run_dir,
            "evidence",
            "inference_checks",
        )
        self._lock = RLock()

    def run(self, reference: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(reference, dict):
            raise EvidenceError("inference reference must be an object")
        features = reference.get("features", reference.get("values"))
        if features is None:
            raise EvidenceError("explicit inference features are required")
        check_id = f"inference-{uuid4().hex[:12]}"
        started = time.perf_counter()
        try:
            integrity = _integrity_snapshot(self.run_dir)
            state = integrity["state"]
            manifest = integrity["manifest"]
            if str(state.get("status")) != "completed":
                raise EvidenceError("inference requires a completed run")
            if integrity["status"] != "passed":
                raise EvidenceError("run artifact integrity verification failed")
            recipe = str(manifest.get("recipe") or "")
            if recipe not in SUPPORTED_JOBLIB_RECIPES:
                raise EvidenceError(f"unsupported Joblib recipe: {recipe or 'unknown'}")

            model_path = self._verified_model_path(manifest)
            try:
                model = joblib.load(model_path)
            except Exception as exc:
                raise EvidenceError("trusted Joblib artifact could not be loaded") from exc
            estimator, model_schema = self._supported_estimator(recipe, model)
            feature_array = self._feature_array(features)
            prediction = estimator.predict(feature_array)
            output = _json_safe(np.asarray(prediction))
            expected = reference.get("expected")
            reference_match = (
                None
                if expected is None
                else self._predictions_match(output, _json_safe(expected))
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            report = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "check_id": check_id,
                "run_id": state.get("run_id"),
                "task_id": state.get("task_id"),
                "recipe": recipe,
                "status": "passed" if reference_match is not False else "failed",
                "blocked": False,
                "model": {
                    "artifact": "model.joblib",
                    "sha256": sha256_file(model_path),
                    "schema": model_schema,
                },
                "input": {
                    "sha256": _canonical_hash(_json_safe(features)),
                    "shape": list(feature_array.shape),
                },
                "reference_sha256": (
                    _canonical_hash(_json_safe(expected)) if expected is not None else None
                ),
                "output": output,
                "output_sha256": _canonical_hash(output),
                "reference_match": reference_match,
                "elapsed_ms": round(elapsed_ms, 6),
                "created_at": _now(),
            }
            self._persist(report)
            return report
        except EvidenceError as exc:
            report = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "check_id": check_id,
                "run_id": self._safe_identity("run_id"),
                "task_id": self._safe_identity("task_id"),
                "status": "blocked",
                "blocked": True,
                "reason": str(exc),
                "input": {"sha256": _canonical_hash(_json_safe(features))},
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 6),
                "created_at": _now(),
            }
            self._persist(report)
            raise InferenceBlocked(str(exc), report) from exc

    def list(self) -> list[dict[str, Any]]:
        reports = [read_json(path) for path in self.checks_dir.glob("inference-*.json")]
        return sorted(
            reports,
            key=lambda item: (str(item.get("created_at", "")), item["check_id"]),
        )

    def get(self, check_id: str) -> dict[str, Any]:
        selected = self._validate_check_id(check_id)
        path = self.checks_dir / f"{selected}.json"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("inference check not found")
        return read_json(path)

    def _verified_model_path(self, manifest: dict[str, Any]) -> Path:
        details = manifest.get("artifacts", {}).get("model.joblib")
        if not isinstance(details, dict):
            raise EvidenceError("run manifest does not declare model.joblib")
        path = (self.run_dir / "artifacts" / "model.joblib").resolve()
        artifact_dir = (self.run_dir / "artifacts").resolve()
        if path.parent != artifact_dir or not path.is_file() or path.is_symlink():
            raise EvidenceError("model.joblib is missing or unsafe")
        if sha256_file(path) != details.get("sha256"):
            raise EvidenceError("model.joblib hash mismatch")
        expected_size = details.get("bytes", details.get("size_bytes"))
        if path.stat().st_size != expected_size:
            raise EvidenceError("model.joblib size mismatch")
        return path

    @staticmethod
    def _supported_estimator(recipe: str, model: Any) -> tuple[Any, str]:
        if recipe == "digit-classification":
            estimator = model.get("estimator") if isinstance(model, dict) else model
            schema = "digit-feature-matrix-v1"
        elif recipe == "image-folder-classification":
            required = {"estimator", "labels", "image_size", "feature_version"}
            if not isinstance(model, dict) or not required.issubset(model):
                raise EvidenceError("unsupported image-classification model schema")
            if model.get("feature_version") not in {
                "rgb-gradient-v1",
                "hf-onnx-plus-rgb-gradient-v1",
            }:
                raise EvidenceError("unsupported image feature version")
            estimator = model["estimator"]
            schema = "image-feature-matrix-v1"
        elif recipe == "tabular-regression":
            required = {"estimator", "feature_columns", "task_type"}
            if not isinstance(model, dict) or not required.issubset(model):
                raise EvidenceError("unsupported tabular-regression model schema")
            if model.get("task_type") != "regression":
                raise EvidenceError("unsupported tabular model task type")
            estimator = model["estimator"]
            schema = "tabular-feature-row-v1"
        else:
            required = {
                "estimator",
                "labels",
                "sample_rate",
                "clip_seconds",
                "feature_version",
            }
            if not isinstance(model, dict) or not required.issubset(model):
                raise EvidenceError("unsupported audio-keyword model schema")
            if model.get("feature_version") != "log-mel-mfcc-summary-v1":
                raise EvidenceError("unsupported audio feature version")
            estimator = model["estimator"]
            schema = "audio-feature-matrix-v1"
        if estimator is None or not callable(getattr(estimator, "predict", None)):
            raise EvidenceError("Joblib artifact does not contain a supported estimator")
        estimator_module = type(estimator).__module__
        if not estimator_module.startswith(("sklearn.", "xgboost.", "lightgbm.")):
            raise EvidenceError("estimator implementation is not allowlisted")
        return estimator, schema

    @staticmethod
    def _feature_array(features: Any) -> np.ndarray:
        try:
            array = np.asarray(features)
        except Exception as exc:
            raise EvidenceError("inference features cannot be converted to an array") from exc
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2 or array.size == 0:
            raise EvidenceError("inference features must be one non-empty row or matrix")
        if array.size > 1_000_000:
            raise EvidenceError("inference feature matrix exceeds the safety limit")
        return array

    @staticmethod
    def _predictions_match(actual: Any, expected: Any) -> bool:
        actual_array = np.asarray(actual)
        expected_array = np.asarray(expected)
        if actual_array.shape != expected_array.shape:
            if expected_array.ndim == 0 and actual_array.size == 1:
                expected_array = expected_array.reshape(1)
            else:
                return False
        try:
            return bool(
                np.allclose(
                    actual_array.astype(float),
                    expected_array.astype(float),
                    rtol=1e-9,
                    atol=1e-9,
                )
            )
        except (TypeError, ValueError):
            return bool(np.array_equal(actual_array.astype(str), expected_array.astype(str)))

    def _persist(self, report: dict[str, Any]) -> None:
        with self._lock:
            write_json(self.checks_dir / f"{report['check_id']}.json", report)

    def _safe_identity(self, field: str) -> Any:
        try:
            value = read_json(self.run_dir / "run_state.json")
            return value.get(field) if isinstance(value, dict) else None
        except Exception:
            return None

    @staticmethod
    def _validate_check_id(check_id: str) -> str:
        selected = str(check_id).strip()
        if not re.fullmatch(r"inference-[a-f0-9]{12}", selected):
            raise FileNotFoundError("inference check not found")
        return selected


class ArtifactBundleBuilder:
    """Create an atomic, privacy-filtered deliverable ZIP for one trusted Run."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = _safe_run_dir(run_dir)
        self.bundles_dir = _safe_subdirectory(self.run_dir, "evidence", "bundles")
        self._lock = RLock()

    def build(self, *, inference_check_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            integrity = _integrity_snapshot(self.run_dir)
            if str(integrity["state"].get("status")) != "completed":
                raise EvidenceError("artifact bundles require a completed run")
            if integrity["status"] != "passed":
                raise EvidenceError("artifact bundle blocked by run integrity failure")
            evaluation = EvaluationReport(self.run_dir).get(required=True)
            if evaluation["integrity_status"] != "passed":
                raise EvidenceError("artifact bundle requires a passed integrity report")
            self._require_current_evaluation(evaluation)
            inference: dict[str, Any] | None = None
            if inference_check_id is not None:
                inference = InferenceCheck(self.run_dir).get(inference_check_id)
                if inference.get("status") != "passed":
                    raise EvidenceError("only a passed inference check can enter a bundle")
                expected_model_hash = (
                    integrity["manifest"].get("artifacts", {})
                    .get("model.joblib", {})
                    .get("sha256")
                )
                if (
                    inference.get("run_id") != integrity["state"].get("run_id")
                    or inference.get("model", {}).get("sha256") != expected_model_hash
                ):
                    raise EvidenceError("inference check does not match the current run model")

            bundle_id = f"bundle-{uuid4().hex[:12]}"
            temporary_dir = self.bundles_dir / f".{bundle_id}.{uuid4().hex}.tmp"
            final_dir = self.bundles_dir / bundle_id
            payload_dir = temporary_dir / "payload"
            payload_dir.mkdir(parents=True, exist_ok=False)
            try:
                included: list[dict[str, Any]] = []
                excluded = self._exclusion_ledger(integrity["manifest"])
                manifest_artifacts = integrity["manifest"]["artifacts"]
                for name in sorted(DELIVERABLE_ALLOWLIST & set(manifest_artifacts)):
                    source = (self.run_dir / "artifacts" / name).resolve()
                    if self._contains_absolute_reference(source):
                        excluded.append(
                            {"path": f"artifacts/{name}", "reason": "absolute path content"}
                        )
                        continue
                    target_name = f"artifacts/{name}"
                    target = payload_dir / target_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    included.append(self._file_record(target_name, target))

                generated = {
                    "evidence/evaluation_report.json": evaluation,
                    "environment.json": self._environment_manifest(integrity["manifest"]),
                }
                if inference is not None:
                    generated["evidence/inference_check.json"] = inference
                for name, value in generated.items():
                    target = payload_dir / name
                    write_json(target, value)
                    included.append(self._file_record(name, target))

                bundle_manifest = {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "bundle_id": bundle_id,
                    "run_id": integrity["state"].get("run_id"),
                    "task_id": integrity["state"].get("task_id"),
                    "recipe": integrity["manifest"].get("recipe"),
                    "release_ready": bool(evaluation.get("release_ready")),
                    "evaluation_conclusion": evaluation.get("conclusion"),
                    "files": sorted(included, key=lambda item: item["path"]),
                    "excluded": sorted(
                        excluded,
                        key=lambda item: (item["path"], item["reason"]),
                    ),
                    "privacy_boundary": {
                        "raw_data_included": False,
                        "test_references_included": False,
                        "internal_state_included": False,
                        "absolute_paths_in_manifest": False,
                    },
                    "created_at": _now(),
                }
                manifest_path = payload_dir / "bundle_manifest.json"
                write_json(manifest_path, bundle_manifest)
                archive_path = temporary_dir / "artifact_bundle.zip"
                with zipfile.ZipFile(
                    archive_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:
                    for path in sorted(payload_dir.rglob("*")):
                        if path.is_file():
                            archive.write(path, arcname=path.relative_to(payload_dir).as_posix())
                record = {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "bundle_id": bundle_id,
                    "run_id": integrity["state"].get("run_id"),
                    "status": "completed",
                    "release_ready": bool(evaluation.get("release_ready")),
                    "archive": {
                        "filename": "artifact_bundle.zip",
                        "sha256": sha256_file(archive_path),
                        "size_bytes": archive_path.stat().st_size,
                    },
                    "manifest": bundle_manifest,
                    "created_at": bundle_manifest["created_at"],
                }
                write_json(temporary_dir / "bundle_record.json", record)
                shutil.rmtree(payload_dir)
                os.replace(temporary_dir, final_dir)
                return record
            finally:
                if temporary_dir.exists():
                    shutil.rmtree(temporary_dir, ignore_errors=True)

    def list(self) -> list[dict[str, Any]]:
        records = [
            read_json(path)
            for path in self.bundles_dir.glob("bundle-*/bundle_record.json")
        ]
        return sorted(
            records,
            key=lambda item: (str(item.get("created_at", "")), item["bundle_id"]),
        )

    def get(self, bundle_id: str) -> dict[str, Any]:
        selected = self._validate_bundle_id(bundle_id)
        path = self.bundles_dir / selected / "bundle_record.json"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("artifact bundle not found")
        return read_json(path)

    def bundle_path(self, bundle_id: str) -> Path:
        selected = self._validate_bundle_id(bundle_id)
        bundle_dir = (self.bundles_dir / selected).resolve()
        path = (bundle_dir / "artifact_bundle.zip").resolve()
        if path.parent != bundle_dir or not path.is_file() or path.is_symlink():
            raise FileNotFoundError("artifact bundle archive not found")
        record = self.get(selected)
        if sha256_file(path) != record["archive"]["sha256"]:
            raise EvidenceError("artifact bundle archive hash mismatch")
        return path

    def _exclusion_ledger(self, manifest: dict[str, Any]) -> list[dict[str, str]]:
        excluded = [
            {"path": "task_contract.json", "reason": "internal training contract"},
            {"path": "run_state.json", "reason": "internal run state"},
            {"path": "events.ndjson", "reason": "internal event log"},
            {"path": "datasets/**", "reason": "raw or normalized user data"},
        ]
        artifacts = manifest.get("artifacts", {})
        for name in sorted(artifacts):
            if name in DELIVERABLE_ALLOWLIST:
                continue
            excluded.append(
                {
                    "path": f"artifacts/{name}",
                    "reason": PRIVATE_OR_INTERNAL_ARTIFACTS.get(
                        name, "not in the trusted deliverable allowlist"
                    ),
                }
            )
        return excluded

    def _require_current_evaluation(self, evaluation: dict[str, Any]) -> None:
        inputs = evaluation.get("inputs", {})
        state = read_json(self.run_dir / "run_state.json")
        current = {
            "run_state_evidence_fingerprint_sha256": (
                _run_state_evidence_fingerprint(state)
            ),
            "run_manifest_sha256": sha256_file(self.run_dir / "run_manifest.json"),
            "metrics_sha256": sha256_file(self.run_dir / "artifacts" / "metrics.json"),
        }
        if evaluation.get("run_id") != state.get("run_id") or any(
            inputs.get(name) != value for name, value in current.items()
        ):
            raise EvidenceError("evaluation report is stale for the current run evidence")

    @staticmethod
    def _file_record(name: str, path: Path) -> dict[str, Any]:
        if Path(name).is_absolute() or _WINDOWS_ABSOLUTE.match(name):
            raise EvidenceError("bundle file paths must be relative")
        return {
            "path": name,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

    def _contains_absolute_reference(self, path: Path) -> bool:
        if path.suffix.lower() not in {".json", ".md", ".py", ".csv", ".txt"}:
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True
        if str(self.run_dir) in text:
            return True
        return bool(re.search(r"(?:^|[\s\"'=])(?:/[A-Za-z0-9_.-]+/|[A-Za-z]:[\\/])", text))

    @staticmethod
    def _environment_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "recipe": manifest.get("recipe"),
            "plugin_version": manifest.get("plugin_version"),
            "dependencies": {
                str(name): str(version)
                for name, version in manifest.get("dependencies", {}).items()
                if not Path(str(version)).is_absolute()
                and not _WINDOWS_ABSOLUTE.match(str(version))
            },
        }

    @staticmethod
    def _validate_bundle_id(bundle_id: str) -> str:
        selected = str(bundle_id).strip()
        if not re.fullmatch(r"bundle-[a-f0-9]{12}", selected):
            raise FileNotFoundError("artifact bundle not found")
        return selected


class EvidenceRepository:
    """Small read API used by future Workspace/HTTP integration."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = _safe_run_dir(run_dir)
        self.evaluation = EvaluationReport(self.run_dir)
        self.inference = InferenceCheck(self.run_dir)
        self.bundles = ArtifactBundleBuilder(self.run_dir)

    def report(self) -> dict[str, Any]:
        return {
            "evaluation_report": self.evaluation.get(required=False),
            "inference_checks": self.inference.list(),
            "artifact_bundles": self.bundles.list(),
        }


__all__ = [
    "ArtifactBundleBuilder",
    "DELIVERABLE_ALLOWLIST",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceError",
    "EvidenceRepository",
    "EvaluationReport",
    "InferenceBlocked",
    "InferenceCheck",
    "SUPPORTED_JOBLIB_RECIPES",
]
