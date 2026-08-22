from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image

from model_harness.huggingface_assets import resolve_training_asset
from model_harness.model_assets import DownloadResult, ModelAssetStore
from model_harness.onnx_image_features import (
    CPU_PROVIDER,
    OnnxImageFeatureError,
    OnnxImageFeatureExtractor,
    OnnxRuntimeCapabilityUnavailable,
    onnxruntime_capability,
)


COMMIT = "e" * 40


class AssetFixtureDownloader:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def download(
        self,
        *,
        provider: str,
        repo_id: str,
        revision: str,
        destination: Path,
        allow_patterns: tuple[str, ...],
        token: str | None,
    ) -> DownloadResult:
        (destination / "model.onnx").write_bytes(b"local fake ONNX graph fixture")
        (destination / "config.json").write_text(
            json.dumps(self.config), encoding="utf-8"
        )
        return DownloadResult(resolved_commit=revision, license="apache-2.0")


class FakeSession:
    def __init__(
        self,
        *,
        input_shape: list[Any] | None = None,
        input_count: int = 1,
        output_shape: list[Any] | None = None,
        output_count: int = 1,
        providers: list[str] | None = None,
        output: np.ndarray | None = None,
    ) -> None:
        self.input_shape = input_shape or [1, 3, 8, 8]
        self.input_count = input_count
        self.output_shape = output_shape or [1, 2]
        self.output_count = output_count
        self.providers = providers or [CPU_PROVIDER]
        self.output = output if output is not None else np.asarray([[0.25, 0.75]])
        self.last_feed: dict[str, np.ndarray] | None = None
        self.last_output_names: list[str] | None = None

    def get_providers(self) -> list[str]:
        return self.providers

    def get_inputs(self) -> list[Any]:
        return [
            SimpleNamespace(
                name=f"pixel_values_{index}" if index else "pixel_values",
                type="tensor(float)",
                shape=self.input_shape,
            )
            for index in range(self.input_count)
        ]

    def get_outputs(self) -> list[Any]:
        return [
            SimpleNamespace(
                name=f"features_{index}" if index else "features",
                type="tensor(float)",
                shape=self.output_shape,
            )
            for index in range(self.output_count)
        ]

    def run(
        self, output_names: list[str], feed: dict[str, np.ndarray]
    ) -> list[np.ndarray]:
        self.last_output_names = output_names
        self.last_feed = feed
        return [self.output]


def _config(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "mean": [0.5, 0.25, 0.125],
        "std": [0.5, 0.25, 0.125],
        "input_shape": [1, 3, 8, 8],
        "classes": ["cat", "dog"],
    }
    value.update(updates)
    return value


def _training_asset(root: Path, config: dict[str, Any]):
    store = ModelAssetStore(root / "assets")
    asset = store.download(
        provider="huggingface",
        repo_id="fixture/onnx-image-model",
        requested_revision=COMMIT,
        downloader=AssetFixtureDownloader(config),
        allow_patterns=("*.onnx", "*.json"),
    )
    return store, resolve_training_asset(
        store,
        asset.asset_id,
        required_files=("model.onnx", "config.json"),
    )


class OnnxImageFeatureTests(unittest.TestCase):
    def test_common_three_dimensional_config_is_normalized_to_batched_nchw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(input_shape=[3, 8, 8])
            _, asset = _training_asset(Path(temporary), config)
            extractor = OnnxImageFeatureExtractor(
                asset,
                session_factory=lambda model_path, providers: FakeSession(),
            )
            self.assertEqual(extractor.input_shape, (1, 3, 8, 8))

    def test_verified_asset_preprocesses_rgb_and_extracts_finite_flat_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, asset = _training_asset(root, _config())
            session = FakeSession()
            factory_calls: list[dict[str, Any]] = []

            def session_factory(model_path: str, *, providers: list[str]) -> FakeSession:
                factory_calls.append(
                    {"model_path": model_path, "providers": list(providers)}
                )
                return session

            extractor = OnnxImageFeatureExtractor(
                asset, session_factory=session_factory
            )
            image_path = root / "sample.png"
            Image.new("RGB", (16, 12), (128, 64, 32)).save(image_path)
            result = extractor.extract(image_path)

            self.assertEqual(factory_calls[0]["providers"], [CPU_PROVIDER])
            self.assertEqual(Path(factory_calls[0]["model_path"]).name, "model.onnx")
            self.assertEqual(result.features.shape, (2,))
            np.testing.assert_allclose(result.features, [0.25, 0.75])
            self.assertEqual(result.classes, ("cat", "dog"))
            self.assertGreaterEqual(result.init_ms, 0.0)
            self.assertGreaterEqual(result.preprocess_ms, 0.0)
            self.assertGreaterEqual(result.inference_ms, 0.0)
            self.assertGreaterEqual(result.total_ms, result.inference_ms)
            self.assertIsNotNone(session.last_feed)
            tensor = session.last_feed["pixel_values"]
            self.assertEqual(tensor.shape, (1, 3, 8, 8))
            self.assertEqual(tensor.dtype, np.float32)
            np.testing.assert_allclose(
                tensor[0, :, 0, 0],
                [
                    ((128 / 255.0) - 0.5) / 0.5,
                    ((64 / 255.0) - 0.25) / 0.25,
                    ((32 / 255.0) - 0.125) / 0.125,
                ],
                rtol=1e-5,
                atol=1e-5,
            )
            self.assertEqual(session.last_output_names, ["features"])

            provenance = result.provenance
            self.assertEqual(provenance.model_asset_id, asset.asset.asset_id)
            self.assertEqual(provenance.provider, "huggingface")
            self.assertEqual(provenance.resolved_commit, COMMIT)
            self.assertEqual(provenance.manifest_sha256, asset.asset.manifest_sha256)
            model_record = next(
                item for item in asset.asset.files if item.relative_path == "model.onnx"
            )
            self.assertEqual(provenance.model_sha256, model_record.sha256)
            self.assertTrue(store.verify(asset.asset.asset_id).ok)
            serialized = result.to_dict()
            self.assertEqual(serialized["feature_count"], 2)
            self.assertIn("measurement_note", serialized["timing"])

    def test_dynamic_shape_and_multiple_inputs_are_rejected(self) -> None:
        cases = {
            "dynamic": (FakeSession(input_shape=[1, 3, "height", 8]), "dynamic_input"),
            "multiple": (FakeSession(input_count=2), "must_have_one_input"),
        }
        for name, (session, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                _, asset = _training_asset(Path(temporary), _config())
                with self.assertRaisesRegex(OnnxImageFeatureError, expected):
                    OnnxImageFeatureExtractor(
                        asset,
                        session_factory=lambda model_path, providers, selected=session: selected,
                    )

    def test_cpu_only_provider_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, asset = _training_asset(Path(temporary), _config())
            session = FakeSession(
                providers=["CoreMLExecutionProvider", CPU_PROVIDER]
            )
            with self.assertRaisesRegex(OnnxImageFeatureError, "not_cpu_only"):
                OnnxImageFeatureExtractor(
                    asset,
                    session_factory=lambda model_path, providers: session,
                )

    def test_nan_and_oversized_outputs_are_rejected(self) -> None:
        cases = {
            "nan": (
                FakeSession(output=np.asarray([[np.nan, 0.0]], dtype=np.float32)),
                4,
                "non_finite",
            ),
            "oversized": (
                FakeSession(
                    output_shape=[1, 5],
                    output=np.zeros((1, 5), dtype=np.float32),
                ),
                4,
                "declared_output_too_large",
            ),
        }
        for name, (session, maximum, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, asset = _training_asset(root, _config())
                if name == "oversized":
                    with self.assertRaisesRegex(OnnxImageFeatureError, expected):
                        OnnxImageFeatureExtractor(
                            asset,
                            session_factory=lambda model_path, providers, selected=session: selected,
                            max_output_elements=maximum,
                        )
                    continue
                extractor = OnnxImageFeatureExtractor(
                    asset,
                    session_factory=lambda model_path, providers, selected=session: selected,
                    max_output_elements=maximum,
                )
                image_path = root / "sample.png"
                Image.new("RGB", (8, 8), "white").save(image_path)
                with self.assertRaisesRegex(OnnxImageFeatureError, expected):
                    extractor.extract(image_path)

    def test_invalid_config_is_rejected_before_session_initialization(self) -> None:
        cases = {
            "zero_std": _config(std=[1.0, 0.0, 1.0]),
            "dynamic_config_shape": _config(input_shape=[1, 3, None, 8]),
            "wrong_channels": _config(input_shape=[1, 1, 8, 8]),
            "duplicate_classes": _config(classes=["same", "same"]),
        }
        for name, config in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                _, asset = _training_asset(Path(temporary), config)
                called = False

                def factory(model_path: str, providers: list[str]) -> FakeSession:
                    nonlocal called
                    called = True
                    return FakeSession()

                with self.assertRaisesRegex(OnnxImageFeatureError, "invalid_config"):
                    OnnxImageFeatureExtractor(asset, session_factory=factory)
                self.assertFalse(called)

    def test_asset_tamper_between_resolution_and_initialization_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, asset = _training_asset(root, _config())
            asset.file("config.json").write_text(
                json.dumps(_config(classes=["changed", "classes"])),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OnnxImageFeatureError, "integrity_mismatch"):
                OnnxImageFeatureExtractor(
                    asset,
                    session_factory=lambda model_path, providers: FakeSession(),
                )

    def test_missing_runtime_and_missing_cpu_provider_are_explicit_capabilities(self) -> None:
        def unavailable() -> Any:
            raise OnnxRuntimeCapabilityUnavailable(
                "capability_unavailable:onnxruntime"
            )

        missing = onnxruntime_capability(runtime_loader=unavailable)
        self.assertFalse(missing["available"])
        self.assertEqual(missing["reason"], "capability_unavailable:onnxruntime")
        no_cpu = onnxruntime_capability(
            runtime_loader=lambda: SimpleNamespace(
                get_available_providers=lambda: ["CoreMLExecutionProvider"]
            )
        )
        self.assertFalse(no_cpu["available"])
        self.assertEqual(
            no_cpu["reason"], "capability_unavailable:onnxruntime_cpu_provider"
        )


if __name__ == "__main__":
    unittest.main()
