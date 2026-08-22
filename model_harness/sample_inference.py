from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

import joblib
import numpy as np
from PIL import Image

from .audio_keyword import extract_audio_feature
from .evidence import EvidenceError, InferenceBlocked, InferenceCheck
from .io_utils import read_json, sha256_file, write_json
from .recipes.image_folder_classification import extract_packaged_image_feature


SAMPLE_INFERENCE_SCHEMA_VERSION = "0.1"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_SECONDS = 30.0
MAX_TABULAR_BYTES = 1024 * 1024

_CHECK_ID = re.compile(r"^sample-[a-f0-9]{12}$")
_RECIPE_SAMPLE_TYPES = {
    "image-folder-classification": "image",
    "audio-keyword-classification": "audio",
    "tabular-regression": "tabular",
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}


class SampleInferenceBlocked(EvidenceError):
    """A raw sample was rejected before a trusted prediction was accepted."""

    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report
        self.check_id = str(report["check_id"])


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


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


class SampleInference:
    """Inspect one explicit new sample and persist a hash-bound prediction.

    The adapter never selects a sample from a Run, artifact, train, validation,
    or test location. A caller must supply the sample explicitly. Raw bytes and
    absolute paths are deliberately absent from persisted reports.
    """

    def __init__(self, run_dir: str | Path) -> None:
        resolved = Path(run_dir).expanduser().resolve()
        if not resolved.is_dir() or resolved.is_symlink():
            raise EvidenceError("run directory is missing or unsafe")
        self.run_dir = resolved
        self.reports_dir = self.run_dir / "evidence" / "sample_inference"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        reports_resolved = self.reports_dir.resolve()
        if (
            self.reports_dir.is_symlink()
            or reports_resolved != self.reports_dir.absolute()
            or self.run_dir not in reports_resolved.parents
        ):
            raise EvidenceError("sample evidence directory escaped the run directory")
        self._lock = RLock()

    def run(
        self,
        sample: str | Path | dict[str, Any],
        *,
        sample_type: str | None = None,
        expected: Any | None = None,
    ) -> dict[str, Any]:
        check_id = f"sample-{uuid4().hex[:12]}"
        started = time.perf_counter()
        source_name = self._safe_source_name(sample)
        input_sha256: str | None = None
        inspection: dict[str, Any] | None = None
        try:
            context = self._trusted_context()
            expected_type = _RECIPE_SAMPLE_TYPES.get(context["recipe"])
            if expected_type is None:
                raise EvidenceError(
                    f"raw sample inference is unsupported for recipe: {context['recipe']}"
                )
            selected_type = sample_type or expected_type
            if selected_type not in set(_RECIPE_SAMPLE_TYPES.values()):
                raise EvidenceError("sample_type must be image, audio, or tabular")
            if selected_type != expected_type:
                raise EvidenceError(
                    f"recipe requires a {expected_type} sample, not {selected_type}"
                )

            if selected_type == "image":
                path, input_sha256, size = self._external_file(
                    sample,
                    context["contract"],
                    maximum_bytes=MAX_IMAGE_BYTES,
                    kind="image",
                )
                features, inspection = self._image_features(
                    path,
                    context["model"],
                    context["artifact_dir"],
                    input_sha256,
                    size,
                )
            elif selected_type == "audio":
                path, input_sha256, size = self._external_file(
                    sample,
                    context["contract"],
                    maximum_bytes=MAX_AUDIO_BYTES,
                    kind="audio",
                )
                features, inspection = self._audio_features(
                    path,
                    context["model"],
                    input_sha256,
                    size,
                )
            else:
                row, input_sha256, size, source_name = self._tabular_row(
                    sample,
                    context["contract"],
                )
                features, inspection = self._tabular_features(
                    row,
                    context["model"],
                    input_sha256,
                    size,
                    source_name,
                )

            reference: dict[str, Any] = {
                "features": np.asarray(features).reshape(1, -1).tolist(),
            }
            if expected is not None:
                reference["expected"] = expected
            inference = InferenceCheck(self.run_dir).run(reference)
            report = {
                "schema_version": SAMPLE_INFERENCE_SCHEMA_VERSION,
                "check_id": check_id,
                "run_id": context["state"].get("run_id"),
                "task_id": context["state"].get("task_id"),
                "recipe": context["recipe"],
                "status": inference["status"],
                "blocked": False,
                "sample": inspection,
                "contract": {
                    "sha256": context["contract_sha256"],
                },
                "model": {
                    "artifact": "model.joblib",
                    "sha256": context["model_sha256"],
                },
                "features": {
                    "sha256": inference["input"]["sha256"],
                    "shape": inference["input"]["shape"],
                },
                "prediction": inference["output"],
                "prediction_sha256": inference["output_sha256"],
                "reference_match": inference["reference_match"],
                "inference_check_id": inference["check_id"],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 6),
                "created_at": _now(),
            }
            self._persist(report)
            return report
        except SampleInferenceBlocked:
            raise
        except InferenceBlocked as exc:
            report = self._blocked_report(
                check_id,
                str(exc),
                started,
                source_name=source_name,
                input_sha256=input_sha256,
                inspection=inspection,
                inference_check_id=exc.check_id,
            )
            self._persist(report)
            raise SampleInferenceBlocked(str(exc), report) from exc
        except Exception as exc:
            reason = self._public_error(exc)
            report = self._blocked_report(
                check_id,
                reason,
                started,
                source_name=source_name,
                input_sha256=input_sha256,
                inspection=inspection,
            )
            self._persist(report)
            raise SampleInferenceBlocked(reason, report) from exc

    def list(self) -> list[dict[str, Any]]:
        reports = [
            read_json(path)
            for path in self.reports_dir.glob("sample-*.json")
            if path.is_file() and not path.is_symlink()
        ]
        return sorted(
            reports,
            key=lambda item: (str(item.get("created_at", "")), item["check_id"]),
        )

    def get(self, check_id: str) -> dict[str, Any]:
        if not isinstance(check_id, str) or not _CHECK_ID.fullmatch(check_id):
            raise EvidenceError("invalid sample inference check id")
        path = self.reports_dir / f"{check_id}.json"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("sample inference check not found")
        return read_json(path)

    def _trusted_context(self) -> dict[str, Any]:
        try:
            state = read_json(self.run_dir / "run_state.json")
            manifest = read_json(self.run_dir / "run_manifest.json")
            contract = read_json(self.run_dir / "task_contract.json")
        except (OSError, ValueError) as exc:
            raise EvidenceError("run state, manifest, and contract must be readable JSON") from exc
        if not all(isinstance(item, dict) for item in (state, manifest, contract)):
            raise EvidenceError("run state, manifest, and contract must be JSON objects")
        if state.get("status") != "completed":
            raise EvidenceError("sample inference requires a completed run")
        for field in ("run_id", "task_id"):
            if not state.get(field) or state.get(field) != manifest.get(field):
                raise EvidenceError(f"run {field} mismatch")
        recipe = str(manifest.get("recipe") or "")
        if not recipe or recipe != contract.get("recipe"):
            raise EvidenceError("run recipe mismatch")

        contract_path = self.run_dir / "task_contract.json"
        contract_sha256 = sha256_file(contract_path)
        if contract_sha256 != manifest.get("contract_snapshot_sha256"):
            raise EvidenceError("task contract hash mismatch")

        model_path = self.run_dir / "artifacts" / "model.joblib"
        artifact_dir = (self.run_dir / "artifacts").resolve()
        model_resolved = model_path.resolve()
        declared = manifest.get("artifacts", {}).get("model.joblib")
        if (
            not isinstance(declared, dict)
            or model_resolved.parent != artifact_dir
            or not model_resolved.is_file()
            or model_path.is_symlink()
        ):
            raise EvidenceError("model.joblib is missing or unsafe")
        model_sha256 = sha256_file(model_resolved)
        expected_size = declared.get("bytes", declared.get("size_bytes"))
        if model_sha256 != declared.get("sha256"):
            raise EvidenceError("model.joblib hash mismatch")
        if not isinstance(expected_size, int) or model_resolved.stat().st_size != expected_size:
            raise EvidenceError("model.joblib size mismatch")
        try:
            model = joblib.load(model_resolved)
        except Exception as exc:
            raise EvidenceError("trusted Joblib artifact could not be loaded") from exc
        self._validate_preprocessing_contract(recipe, model, contract)
        return {
            "state": state,
            "manifest": manifest,
            "contract": contract,
            "recipe": recipe,
            "model": model,
            "artifact_dir": artifact_dir,
            "contract_sha256": contract_sha256,
            "model_sha256": model_sha256,
        }

    @staticmethod
    def _validate_preprocessing_contract(
        recipe: str,
        model: Any,
        contract: dict[str, Any],
    ) -> None:
        if not isinstance(model, dict) or not callable(
            getattr(model.get("estimator"), "predict", None)
        ):
            raise EvidenceError("model bundle has no supported estimator")
        if recipe == "image-folder-classification":
            if model.get("feature_version") not in {
                "rgb-gradient-v1",
                "hf-onnx-plus-rgb-gradient-v1",
            }:
                raise EvidenceError("unsupported image feature version")
            image_size = model.get("image_size")
            expected_size = contract.get("recipe_options", {}).get("image_size")
            if (
                not isinstance(image_size, int)
                or image_size <= 0
                or image_size != expected_size
            ):
                raise EvidenceError("image preprocessing metadata does not match contract")
            if not isinstance(model.get("labels"), list) or not model["labels"]:
                raise EvidenceError("image label metadata is missing")
        elif recipe == "audio-keyword-classification":
            required = {
                "labels",
                "sample_rate",
                "clip_seconds",
                "n_mels",
                "n_mfcc",
                "feature_version",
            }
            if not required.issubset(model):
                raise EvidenceError("audio preprocessing metadata is incomplete")
            if model.get("feature_version") != "log-mel-mfcc-summary-v1":
                raise EvidenceError("unsupported audio feature version")
            options = contract.get("recipe_options", {})
            dataset = contract.get("dataset", {})
            pairs = (
                (model.get("sample_rate"), dataset.get("sample_rate")),
                (model.get("clip_seconds"), options.get("clip_seconds")),
                (model.get("n_mels"), options.get("n_mels")),
                (model.get("n_mfcc"), options.get("n_mfcc")),
            )
            if any(actual != expected for actual, expected in pairs):
                raise EvidenceError("audio preprocessing metadata does not match contract")
            if model.get("sample_rate") != 16_000:
                raise EvidenceError("raw sample inference currently requires a 16 kHz model")
        elif recipe == "tabular-regression":
            if model.get("task_type") != "regression":
                raise EvidenceError("unsupported tabular model task type")
            columns = model.get("feature_columns")
            dataset = contract.get("dataset", {})
            if (
                not isinstance(columns, list)
                or not columns
                or columns != dataset.get("feature_columns")
                or model.get("target_column") != dataset.get("target_column")
            ):
                raise EvidenceError("tabular preprocessing metadata does not match contract")
        else:
            raise EvidenceError(f"raw sample inference is unsupported for recipe: {recipe}")

    def _external_file(
        self,
        sample: str | Path | dict[str, Any],
        contract: dict[str, Any],
        *,
        maximum_bytes: int,
        kind: str,
    ) -> tuple[Path, str, int]:
        if isinstance(sample, dict):
            raise EvidenceError(f"{kind} inference requires an explicit sample file")
        supplied = Path(sample).expanduser()
        if supplied.is_symlink():
            raise EvidenceError("sample symlinks are not accepted")
        resolved = supplied.resolve()
        if not resolved.is_file():
            raise EvidenceError("sample file is missing or unreadable")
        self._reject_internal_or_dataset_sample(resolved, contract)
        size = resolved.stat().st_size
        if size <= 0:
            raise EvidenceError("sample file is empty")
        if size > maximum_bytes:
            raise EvidenceError(f"{kind} sample exceeds the size limit")
        return resolved, sha256_file(resolved), size

    def _reject_internal_or_dataset_sample(
        self,
        path: Path,
        contract: dict[str, Any],
    ) -> None:
        if _inside(path, self.run_dir):
            raise EvidenceError("Run, artifact, and test files cannot be used as new samples")
        dataset = contract.get("dataset", {})
        if not isinstance(dataset, dict):
            return
        for key, value in dataset.items():
            if not isinstance(value, str) or not value.strip():
                continue
            lowered = str(key).lower()
            if not (
                lowered in {"root", "dataset_root", "data_dir", "train_dir", "test_dir", "validation_dir"}
                or lowered.endswith("_path")
            ):
                continue
            try:
                source = Path(value).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if lowered in {"root", "dataset_root", "data_dir", "train_dir", "test_dir", "validation_dir"}:
                forbidden = _inside(path, source)
            else:
                forbidden = path == source
            if forbidden:
                raise EvidenceError("training, validation, or test data cannot be reused as a new sample")

    @staticmethod
    def _image_features(
        path: Path,
        model: dict[str, Any],
        artifact_dir: Path,
        sha256: str,
        size: int,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if path.suffix.lower() not in _IMAGE_EXTENSIONS:
            raise EvidenceError("image sample extension is unsupported")
        try:
            with Image.open(path) as source:
                image_format = str(source.format or "").upper()
                width, height = source.size
                mode = source.mode
                if image_format not in _IMAGE_FORMATS:
                    raise EvidenceError("image sample format is unsupported")
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise EvidenceError("image dimensions exceed the safety limit")
                source.verify()
            feature = extract_packaged_image_feature(path, artifact_dir)
        except EvidenceError:
            raise
        except Exception as exc:
            raise EvidenceError("image sample is corrupt or unsupported") from exc
        return feature, {
            "type": "image",
            "source_name": path.name,
            "sha256": sha256,
            "size_bytes": size,
            "format": image_format,
            "width": width,
            "height": height,
            "mode": mode,
        }

    @staticmethod
    def _audio_features(
        path: Path,
        model: dict[str, Any],
        sha256: str,
        size: int,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if path.suffix.lower() != ".wav":
            raise EvidenceError("audio sample must be a WAV file")
        try:
            with wave.open(str(path), "rb") as source:
                channels = source.getnchannels()
                sample_rate = source.getframerate()
                sample_width = source.getsampwidth()
                frames = source.getnframes()
                compression = source.getcomptype()
            duration = frames / sample_rate if sample_rate else 0.0
        except (wave.Error, EOFError, OSError) as exc:
            raise EvidenceError("audio sample is not a valid PCM WAV") from exc
        if compression != "NONE":
            raise EvidenceError("audio sample must be uncompressed PCM WAV")
        if channels != 1 or sample_rate != 16_000:
            raise EvidenceError("audio sample must be 16 kHz mono PCM WAV")
        if sample_width not in {1, 2, 3, 4} or frames <= 0:
            raise EvidenceError("audio sample has an unsupported PCM encoding")
        if not 0 < duration <= MAX_AUDIO_SECONDS:
            raise EvidenceError("audio sample duration exceeds the safety limit")
        try:
            feature = extract_audio_feature(
                path,
                sample_rate=int(model["sample_rate"]),
                clip_seconds=float(model["clip_seconds"]),
                n_mels=int(model["n_mels"]),
                n_mfcc=int(model["n_mfcc"]),
            )
        except Exception as exc:
            raise EvidenceError("audio feature extraction failed") from exc
        return feature, {
            "type": "audio",
            "source_name": path.name,
            "sha256": sha256,
            "size_bytes": size,
            "format": "PCM WAV",
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "frame_count": frames,
            "duration_seconds": round(duration, 6),
        }

    def _tabular_row(
        self,
        sample: str | Path | dict[str, Any],
        contract: dict[str, Any],
    ) -> tuple[dict[str, Any], str, int, str]:
        if isinstance(sample, dict):
            row = dict(sample)
            payload = json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if not payload or len(payload) > MAX_TABULAR_BYTES:
                raise EvidenceError("tabular sample exceeds the size limit")
            source_name = "inline.json"
            sha256 = hashlib.sha256(payload).hexdigest()
            size = len(payload)
        else:
            path, sha256, size = self._external_file(
                sample,
                contract,
                maximum_bytes=MAX_TABULAR_BYTES,
                kind="tabular",
            )
            source_name = path.name
            suffix = path.suffix.lower()
            try:
                payload = path.read_bytes()
                text = payload.decode("utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise EvidenceError("tabular sample must be UTF-8 JSON or CSV") from exc
            if suffix == ".json":
                try:
                    decoded = json.loads(text)
                except ValueError as exc:
                    raise EvidenceError("tabular JSON sample is invalid") from exc
                if not isinstance(decoded, dict):
                    raise EvidenceError("tabular JSON must contain exactly one row object")
                row = decoded
            elif suffix == ".csv":
                reader = csv.DictReader(io.StringIO(text, newline=""))
                if not reader.fieldnames or any(not name for name in reader.fieldnames):
                    raise EvidenceError("tabular CSV header is missing or invalid")
                rows = list(reader)
                if len(rows) != 1:
                    raise EvidenceError("tabular CSV must contain exactly one data row")
                row = rows[0]
            else:
                raise EvidenceError("tabular sample must use a .json or .csv extension")
        if not row:
            raise EvidenceError("tabular sample row is empty")
        for value in row.values():
            if isinstance(value, (dict, list, tuple)):
                raise EvidenceError("tabular sample values must be scalar")
            if isinstance(value, float) and not math.isfinite(value):
                raise EvidenceError("tabular sample contains a non-finite number")
        return row, sha256, size, source_name

    @staticmethod
    def _tabular_features(
        row: dict[str, Any],
        model: dict[str, Any],
        sha256: str,
        size: int,
        source_name: str,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        feature_columns = list(model["feature_columns"])
        missing = [name for name in feature_columns if name not in row]
        if missing:
            raise EvidenceError(
                "tabular sample is missing required columns: " + ", ".join(missing)
            )
        supplied_columns = [str(name) for name in row]
        ignored = [name for name in supplied_columns if name not in feature_columns]
        features = np.asarray(
            [[row[name] for name in feature_columns]],
            dtype=object,
        )
        return features.reshape(-1), {
            "type": "tabular",
            "source_name": source_name,
            "sha256": sha256,
            "size_bytes": size,
            "format": "JSON" if source_name.lower().endswith(".json") else "CSV",
            "row_count": 1,
            "supplied_columns": supplied_columns,
            "used_columns": feature_columns,
            "ignored_columns": ignored,
        }

    @staticmethod
    def _safe_source_name(sample: str | Path | dict[str, Any]) -> str:
        if isinstance(sample, dict):
            return "inline.json"
        try:
            return Path(sample).name or "sample"
        except (TypeError, ValueError):
            return "sample"

    @staticmethod
    def _public_error(exc: Exception) -> str:
        if isinstance(exc, EvidenceError):
            return str(exc)
        if isinstance(exc, (TypeError, ValueError, OverflowError)):
            return "sample input is invalid"
        return f"sample inference failed during {type(exc).__name__}"

    def _blocked_report(
        self,
        check_id: str,
        reason: str,
        started: float,
        *,
        source_name: str,
        input_sha256: str | None,
        inspection: dict[str, Any] | None,
        inference_check_id: str | None = None,
    ) -> dict[str, Any]:
        identity: dict[str, Any] = {}
        try:
            state = read_json(self.run_dir / "run_state.json")
            if isinstance(state, dict):
                identity = {
                    "run_id": state.get("run_id"),
                    "task_id": state.get("task_id"),
                }
        except (OSError, ValueError):
            pass
        sample_summary = inspection or {
            "source_name": source_name,
            "sha256": input_sha256,
        }
        return {
            "schema_version": SAMPLE_INFERENCE_SCHEMA_VERSION,
            "check_id": check_id,
            **identity,
            "status": "blocked",
            "blocked": True,
            "reason": reason,
            "sample": sample_summary,
            "inference_check_id": inference_check_id,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 6),
            "created_at": _now(),
        }

    def _persist(self, report: dict[str, Any]) -> None:
        check_id = str(report.get("check_id", ""))
        if not _CHECK_ID.fullmatch(check_id):
            raise EvidenceError("invalid sample inference check id")
        with self._lock:
            write_json(self.reports_dir / f"{check_id}.json", report)


def infer_sample(
    run_dir: str | Path,
    sample: str | Path | dict[str, Any],
    *,
    sample_type: str | None = None,
    expected: Any | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint for one explicit new-sample prediction."""

    return SampleInference(run_dir).run(
        sample,
        sample_type=sample_type,
        expected=expected,
    )
