from __future__ import annotations

import importlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .huggingface_assets import TrainingModelAsset
from .io_utils import sha256_file
from .model_assets import ModelAssetError, ModelAssetFile


CPU_PROVIDER = "CPUExecutionProvider"
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_ELEMENTS = 3 * 4096 * 4096
DEFAULT_MAX_OUTPUT_ELEMENTS = 1_000_000


class OnnxImageFeatureError(ModelAssetError):
    """A sanitized ONNX image feature contract or inference failure."""


class OnnxRuntimeCapabilityUnavailable(OnnxImageFeatureError):
    """ONNX Runtime or its CPU provider is unavailable."""


@dataclass(frozen=True)
class ImageFeatureConfig:
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    input_shape: tuple[int, int, int, int]
    classes: tuple[str, ...]


@dataclass(frozen=True)
class OnnxFeatureProvenance:
    model_asset_id: str
    provider: str
    repo_id: str
    requested_revision: str
    resolved_commit: str
    manifest_sha256: str
    model_relative_path: str
    model_sha256: str
    config_relative_path: str
    config_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OnnxImageFeatureResult:
    features: np.ndarray
    classes: tuple[str, ...]
    provenance: OnnxFeatureProvenance
    init_ms: float
    preprocess_ms: float
    inference_ms: float
    total_ms: float

    def to_dict(self, *, include_features: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "classes": list(self.classes),
            "feature_count": int(self.features.size),
            "provenance": self.provenance.to_dict(),
            "timing": {
                "init_ms": self.init_ms,
                "preprocess_ms": self.preprocess_ms,
                "inference_ms": self.inference_ms,
                "total_ms": self.total_ms,
                "measurement_note": (
                    "local monotonic-clock timings for extractor initialization, "
                    "Pillow preprocessing and ONNX Runtime session.run"
                ),
            },
        }
        if include_features:
            value["features"] = self.features.tolist()
        return value


def _runtime_module() -> Any:
    try:
        return importlib.import_module("onnxruntime")
    except ImportError as exc:
        raise OnnxRuntimeCapabilityUnavailable(
            "capability_unavailable:onnxruntime"
        ) from exc


def onnxruntime_capability(
    *, runtime_loader: Callable[[], Any] | None = None
) -> dict[str, Any]:
    loader = runtime_loader or _runtime_module
    try:
        runtime = loader()
        providers = tuple(str(item) for item in runtime.get_available_providers())
    except OnnxRuntimeCapabilityUnavailable as exc:
        return {"available": False, "reason": str(exc), "providers": []}
    except Exception:
        return {
            "available": False,
            "reason": "capability_unavailable:onnxruntime_probe_failed",
            "providers": [],
        }
    if CPU_PROVIDER not in providers:
        return {
            "available": False,
            "reason": "capability_unavailable:onnxruntime_cpu_provider",
            "providers": list(providers),
        }
    return {
        "available": True,
        "provider": CPU_PROVIDER,
        "providers": list(providers),
    }


def _default_session_factory(model_path: str, *, providers: list[str]) -> Any:
    runtime = _runtime_module()
    available = tuple(str(item) for item in runtime.get_available_providers())
    if CPU_PROVIDER not in available:
        raise OnnxRuntimeCapabilityUnavailable(
            "capability_unavailable:onnxruntime_cpu_provider"
        )
    return runtime.InferenceSession(model_path, providers=providers)


def _finite_triplet(value: Any, field: str, *, positive: bool) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise OnnxImageFeatureError(f"invalid_config:{field}")
    selected: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise OnnxImageFeatureError(f"invalid_config:{field}")
        number = float(item)
        if not np.isfinite(number) or (positive and number <= 0):
            raise OnnxImageFeatureError(f"invalid_config:{field}")
        selected.append(number)
    return selected[0], selected[1], selected[2]


def _load_config(path: Path) -> ImageFeatureConfig:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnnxImageFeatureError("invalid_config:json") from exc
    if not isinstance(value, dict):
        raise OnnxImageFeatureError("invalid_config:root")
    mean = _finite_triplet(value.get("mean"), "mean", positive=False)
    std = _finite_triplet(value.get("std"), "std", positive=True)
    raw_shape = value.get("input_shape")
    if (
        not isinstance(raw_shape, list)
        or len(raw_shape) not in {3, 4}
        or not all(
            isinstance(item, int) and not isinstance(item, bool) and item > 0
            for item in raw_shape
        )
    ):
        raise OnnxImageFeatureError("invalid_config:input_shape")
    input_shape = (1, *raw_shape) if len(raw_shape) == 3 else tuple(raw_shape)
    if input_shape[0] != 1 or input_shape[1] != 3:
        raise OnnxImageFeatureError("invalid_config:input_shape_must_be_1x3xhxw")
    height, width = input_shape[2], input_shape[3]
    if (
        height > MAX_IMAGE_SIDE
        or width > MAX_IMAGE_SIDE
        or 3 * height * width > MAX_IMAGE_ELEMENTS
    ):
        raise OnnxImageFeatureError("invalid_config:input_shape_too_large")
    raw_classes = value.get("classes")
    if (
        not isinstance(raw_classes, list)
        or not raw_classes
        or len(raw_classes) > DEFAULT_MAX_OUTPUT_ELEMENTS
        or any(
            not isinstance(item, str) or not item.strip() or len(item.strip()) > 200
            for item in raw_classes
        )
    ):
        raise OnnxImageFeatureError("invalid_config:classes")
    classes = tuple(item.strip() for item in raw_classes)
    if len(set(classes)) != len(classes):
        raise OnnxImageFeatureError("invalid_config:duplicate_classes")
    return ImageFeatureConfig(
        mean=mean,
        std=std,
        input_shape=(input_shape[0], input_shape[1], height, width),
        classes=classes,
    )


def _asset_file(asset: TrainingModelAsset, relative_path: str) -> ModelAssetFile:
    for item in asset.asset.files:
        if item.relative_path == relative_path:
            return item
    raise OnnxImageFeatureError(f"required_asset_file_missing:{relative_path}")


class OnnxImageFeatureExtractor:
    def __init__(
        self,
        asset: TrainingModelAsset,
        *,
        session_factory: Callable[..., Any] | None = None,
        max_output_elements: int = DEFAULT_MAX_OUTPUT_ELEMENTS,
    ) -> None:
        init_started = time.perf_counter_ns()
        if (
            asset.asset.status != "active"
            or asset.asset.security_status != "verified"
            or not asset.asset.resolved_commit
        ):
            raise OnnxImageFeatureError("model_asset_not_verified")
        if not isinstance(max_output_elements, int) or max_output_elements <= 0:
            raise OnnxImageFeatureError("invalid_max_output_elements")
        self.max_output_elements = max_output_elements
        self.model_path = asset.file("model.onnx")
        self.config_path = asset.file("config.json")
        model_record = _asset_file(asset, "model.onnx")
        config_record = _asset_file(asset, "config.json")
        model_sha256 = sha256_file(self.model_path)
        config_sha256 = sha256_file(self.config_path)
        if (
            self.model_path.is_symlink()
            or not self.model_path.is_file()
            or model_sha256 != model_record.sha256
        ):
            raise OnnxImageFeatureError("model_asset_integrity_mismatch:model.onnx")
        if (
            self.config_path.is_symlink()
            or not self.config_path.is_file()
            or config_sha256 != config_record.sha256
        ):
            raise OnnxImageFeatureError("model_asset_integrity_mismatch:config.json")
        self.config = _load_config(self.config_path)
        if len(self.config.classes) > self.max_output_elements:
            raise OnnxImageFeatureError("configured_output_too_large")
        self.provenance = OnnxFeatureProvenance(
            model_asset_id=asset.asset.asset_id,
            provider=asset.asset.provider,
            repo_id=asset.asset.repo_id,
            requested_revision=asset.asset.requested_revision,
            resolved_commit=asset.asset.resolved_commit,
            manifest_sha256=asset.asset.manifest_sha256,
            model_relative_path="model.onnx",
            model_sha256=model_sha256,
            config_relative_path="config.json",
            config_sha256=config_sha256,
        )
        factory = session_factory or _default_session_factory
        try:
            self.session = factory(
                str(self.model_path), providers=[CPU_PROVIDER]
            )
        except OnnxRuntimeCapabilityUnavailable:
            raise
        except Exception:
            raise OnnxImageFeatureError("onnx_session_initialization_failed") from None
        providers = tuple(str(item) for item in self.session.get_providers())
        if providers != (CPU_PROVIDER,):
            raise OnnxImageFeatureError("onnx_session_is_not_cpu_only")
        inputs = tuple(self.session.get_inputs())
        if len(inputs) != 1:
            raise OnnxImageFeatureError("onnx_model_must_have_one_input")
        selected_input = inputs[0]
        input_name = getattr(selected_input, "name", None)
        input_type = getattr(selected_input, "type", None)
        raw_session_shape = getattr(selected_input, "shape", None)
        if not isinstance(input_name, str) or not input_name:
            raise OnnxImageFeatureError("onnx_input_name_missing")
        if input_type != "tensor(float)":
            raise OnnxImageFeatureError("onnx_input_must_be_float32")
        if (
            not isinstance(raw_session_shape, (list, tuple))
            or len(raw_session_shape) != 4
            or not all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in raw_session_shape
            )
        ):
            raise OnnxImageFeatureError("onnx_dynamic_input_shape_rejected")
        session_shape = tuple(int(item) for item in raw_session_shape)
        if session_shape != self.config.input_shape:
            raise OnnxImageFeatureError("onnx_input_shape_config_mismatch")
        outputs = tuple(self.session.get_outputs())
        if len(outputs) != 1:
            raise OnnxImageFeatureError("onnx_model_must_have_one_output")
        self.input_name = input_name
        self.output_name = getattr(outputs[0], "name", None)
        output_type = getattr(outputs[0], "type", None)
        if not isinstance(self.output_name, str) or not self.output_name:
            raise OnnxImageFeatureError("onnx_output_name_missing")
        if output_type != "tensor(float)":
            raise OnnxImageFeatureError("onnx_output_must_be_float32")
        declared_output_shape = getattr(outputs[0], "shape", None)
        if isinstance(declared_output_shape, (list, tuple)) and all(
            isinstance(item, int) and not isinstance(item, bool) and item > 0
            for item in declared_output_shape
        ):
            declared_size = math.prod(int(item) for item in declared_output_shape)
            if declared_size > self.max_output_elements:
                raise OnnxImageFeatureError("onnx_declared_output_too_large")
        self.init_ms = (time.perf_counter_ns() - init_started) / 1_000_000

    @property
    def classes(self) -> tuple[str, ...]:
        return self.config.classes

    @property
    def input_shape(self) -> tuple[int, int, int, int]:
        return self.config.input_shape

    def preprocess(self, image_path: str | Path) -> np.ndarray:
        path = Path(image_path).expanduser().resolve()
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                height, width = self.config.input_shape[2:]
                resized = image.resize((width, height), Image.Resampling.BILINEAR)
                pixels = np.asarray(resized, dtype=np.float32) / 255.0
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise OnnxImageFeatureError("image_decode_or_resize_failed") from None
        mean = np.asarray(self.config.mean, dtype=np.float32).reshape(1, 1, 3)
        std = np.asarray(self.config.std, dtype=np.float32).reshape(1, 1, 3)
        normalized = (pixels - mean) / std
        tensor = np.ascontiguousarray(
            normalized.transpose(2, 0, 1)[None, ...], dtype=np.float32
        )
        if tensor.shape != self.config.input_shape or not np.all(np.isfinite(tensor)):
            raise OnnxImageFeatureError("preprocessed_tensor_invalid")
        return tensor

    def extract(self, image_path: str | Path) -> OnnxImageFeatureResult:
        total_started = time.perf_counter_ns()
        preprocess_started = time.perf_counter_ns()
        tensor = self.preprocess(image_path)
        preprocess_ms = (time.perf_counter_ns() - preprocess_started) / 1_000_000
        inference_started = time.perf_counter_ns()
        try:
            outputs = self.session.run(
                [self.output_name], {self.input_name: tensor}
            )
        except Exception:
            raise OnnxImageFeatureError("onnx_inference_failed") from None
        inference_ms = (time.perf_counter_ns() - inference_started) / 1_000_000
        if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
            raise OnnxImageFeatureError("onnx_runtime_output_contract_failed")
        output = np.asarray(outputs[0])
        if (
            output.ndim < 2
            or output.shape[0] != 1
            or output.size == 0
            or output.size > self.max_output_elements
            or not np.issubdtype(output.dtype, np.floating)
        ):
            raise OnnxImageFeatureError("onnx_output_shape_or_type_invalid")
        features = np.ascontiguousarray(output.reshape(-1), dtype=np.float32)
        if features.size != len(self.config.classes):
            raise OnnxImageFeatureError("onnx_output_classes_mismatch")
        if not np.all(np.isfinite(features)):
            raise OnnxImageFeatureError("onnx_output_contains_non_finite_values")
        total_ms = (time.perf_counter_ns() - total_started) / 1_000_000
        return OnnxImageFeatureResult(
            features=features,
            classes=self.config.classes,
            provenance=self.provenance,
            init_ms=self.init_ms,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            total_ms=total_ms,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "provider": CPU_PROVIDER,
            "input_name": self.input_name,
            "output_name": self.output_name,
            "input_shape": list(self.config.input_shape),
            "classes": list(self.config.classes),
            "init_ms": self.init_ms,
            "provenance": self.provenance.to_dict(),
        }
