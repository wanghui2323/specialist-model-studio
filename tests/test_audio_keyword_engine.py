from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

import numpy as np

from model_harness.audio_keyword import ADAPTER, extract_audio_feature
from model_harness.data_adapters import DataAdapter
from model_harness.errors import ContractError
from model_harness.plugin_api import RecipePlugin
from model_harness.recipes.audio_keyword_plugin import PLUGIN


def _wav_bytes(
    frequency: float,
    *,
    speaker_index: int,
    sample_rate: int = 16_000,
    duration: float = 0.45,
    channels: int = 1,
) -> bytes:
    rng = np.random.default_rng(10_000 + speaker_index)
    time = np.arange(int(sample_rate * duration), dtype=np.float64) / sample_rate
    phase = (speaker_index % 7) * 0.13
    envelope = np.minimum(1.0, np.arange(len(time)) / max(1, sample_rate * 0.02))
    signal = (
        0.58 * np.sin(2 * np.pi * frequency * time + phase)
        + 0.13 * np.sin(2 * np.pi * frequency * 2.01 * time)
        + rng.normal(0.0, 0.012, size=len(time))
    ) * envelope
    signal = np.clip(signal, -1.0, 1.0)
    pcm = np.round(signal * 32767.0).astype("<i2")
    if channels == 2:
        pcm = np.column_stack([pcm, pcm]).reshape(-1)
    payload = io.BytesIO()
    with wave.open(payload, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())
    return payload.getvalue()


def _dataset_zip(*, include_invalid: bool = False) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for speaker_index in range(8):
            speaker = f"speaker{speaker_index:02d}"
            archive.writestr(
                f"yes/{speaker}_nohash_0.wav",
                _wav_bytes(360.0, speaker_index=speaker_index),
            )
            archive.writestr(
                f"no/{speaker}_nohash_0.wav",
                _wav_bytes(960.0, speaker_index=100 + speaker_index),
            )
        if include_invalid:
            archive.writestr(
                "yes/bad-rate_nohash_0.wav",
                _wav_bytes(360.0, speaker_index=800, sample_rate=8_000),
            )
            archive.writestr(
                "no/stereo_nohash_0.wav",
                _wav_bytes(960.0, speaker_index=801, channels=2),
            )
            archive.writestr(
                "no/too-short_nohash_0.wav",
                _wav_bytes(960.0, speaker_index=802, duration=0.10),
            )
            archive.writestr("yes/corrupt_nohash_0.wav", b"not a wav")
    return payload.getvalue()


class AudioKeywordEngineTests(unittest.TestCase):
    def test_adapter_and_plugin_satisfy_public_protocols(self) -> None:
        self.assertIsInstance(ADAPTER, DataAdapter)
        self.assertIsInstance(PLUGIN, RecipePlugin)
        self.assertEqual(
            PLUGIN.manifest.data_adapter, ADAPTER.manifest.adapter_id
        )
        self.assertEqual(PLUGIN.manifest.task_type, "offline-audio-keyword-classification")

    def test_real_pcm_wav_end_to_end_is_speaker_disjoint_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            imported = ADAPTER.import_data(
                root / "datasets",
                _dataset_zip(include_invalid=True),
                "keywords.zip",
                {"sample_rate": 16_000, "channels": 1, "random_seed": 17},
            )
            self.assertEqual(imported.report["total_audio"], 16)
            self.assertEqual(imported.report["class_counts"], {"no": 8, "yes": 8})
            self.assertEqual(imported.report["speaker_count"], 8)
            self.assertEqual(imported.report["rejected_count"], 4)
            rejection_text = " ".join(
                item["reason"] for item in imported.report["rejected_files"]
            )
            self.assertIn("采样率", rejection_text)
            self.assertIn("声道", rejection_text)
            self.assertIn("时长", rejection_text)
            self.assertIn("PCM WAV", rejection_text)

            contract = PLUGIN.template()
            contract["task_id"] = "synthetic-keyword-e2e"
            contract["business_goal"] = "区分两个已分段的本地设备控制词"
            contract["dataset"].update(imported.contract_dataset)
            contract["dataset"]["split"] = {
                "train": 0.50,
                "validation": 0.25,
                "test": 0.25,
            }
            contract["recipe_options"]["clip_seconds"] = 0.50
            contract["recipe_options"]["extra_trees_estimators"] = 50
            PLUGIN.validate_contract(contract)

            training = PLUGIN.train(contract)
            speaker_sets = [
                {str(training.speaker_ids[index]) for index in indices}
                for indices in (
                    training.train_idx,
                    training.validation_idx,
                    training.test_idx,
                )
            ]
            self.assertFalse(speaker_sets[0] & speaker_sets[1])
            self.assertFalse(speaker_sets[0] & speaker_sets[2])
            self.assertFalse(speaker_sets[1] & speaker_sets[2])
            self.assertNotEqual(training.selected_name, "most_frequent_baseline")
            evaluation = PLUGIN.evaluate(training, contract)
            self.assertTrue(evaluation.metrics["speaker_split"]["disjoint"])
            self.assertFalse(evaluation.metrics["test_set_used_for_selection"])
            self.assertGreaterEqual(evaluation.metrics["clean_test"]["macro_f1"], 0.95)

            artifact_dir = root / "artifacts"
            metrics = PLUGIN.package(training, evaluation, contract, artifact_dir)
            self.assertTrue(metrics["gate_checks"]["all_offline_gates_passed"])
            self.assertEqual(PLUGIN.deep_verify(artifact_dir), [])
            for name in (
                "model.joblib",
                "metrics.json",
                "failure_samples.json",
                "dataset_report.json",
                "confusion_matrix.csv",
                "test_reference.joblib",
                "model_card.md",
                "inference_example.py",
            ):
                self.assertTrue((artifact_dir / name).is_file(), name)
            saved_metrics = json.loads(
                (artifact_dir / "metrics.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved_metrics["scope"], "offline_keyword_classification")
            model_card = (artifact_dir / "model_card.md").read_text(encoding="utf-8")
            self.assertIn("does not transcribe speech (ASR)", model_card)
            self.assertIn("streaming wake-word detector", model_card)

            first_feature = extract_audio_feature(
                training.absolute_paths[0], sample_rate=16_000, clip_seconds=0.50
            )
            second_feature = extract_audio_feature(
                training.absolute_paths[0], sample_rate=16_000, clip_seconds=0.50
            )
            np.testing.assert_array_equal(first_feature, second_feature)

    def test_cross_label_duplicate_is_a_blocking_label_conflict(self) -> None:
        duplicate = _wav_bytes(440.0, speaker_index=1)
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("yes/a_nohash_0.wav", duplicate)
            archive.writestr("no/b_nohash_0.wav", duplicate)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ContractError, "不同类别"):
                ADAPTER.import_data(
                    Path(temporary), payload.getvalue(), "conflict.zip", {}
                )
            self.assertEqual(list(Path(temporary).glob("*")), [])

    def test_path_traversal_is_rejected_without_writing_outside_dataset(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(
                "../escape.wav", _wav_bytes(440.0, speaker_index=1)
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ContractError, "不安全路径"):
                ADAPTER.import_data(root / "datasets", payload.getvalue(), "bad.zip", {})
            self.assertFalse((root / "escape.wav").exists())

    def test_contract_rejects_non_speaker_grouped_split(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            imported = ADAPTER.import_data(
                Path(temporary) / "datasets", _dataset_zip(), "keywords.zip", {}
            )
            contract = PLUGIN.template()
            contract["dataset"].update(imported.contract_dataset)
            contract["dataset"]["group_by"] = "file"
            with self.assertRaisesRegex(ContractError, "speaker_id"):
                PLUGIN.validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
