from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

import joblib
import numpy as np
from PIL import Image
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from model_harness.audio_keyword import extract_audio_feature
from model_harness.io_utils import sha256_file, write_json
from model_harness.recipes.image_folder_classification import extract_image_feature
from model_harness.sample_inference import SampleInference, SampleInferenceBlocked
from model_harness.service import RunService


def _wav_bytes(frequency: float, *, sample_rate: int = 16_000) -> bytes:
    timeline = np.arange(int(sample_rate * 0.45), dtype=np.float64) / sample_rate
    signal = 0.65 * np.sin(2 * np.pi * frequency * timeline)
    pcm = np.round(signal * 32767.0).astype("<i2")
    payload = io.BytesIO()
    with wave.open(payload, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())
    return payload.getvalue()


def _write_completed_run(
    runs_dir: Path,
    run_id: str,
    recipe: str,
    contract: dict[str, object],
    model: dict[str, object],
) -> Path:
    run_dir = runs_dir / run_id
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True)
    write_json(run_dir / "task_contract.json", contract)
    write_json(
        run_dir / "run_state.json",
        {
            "schema_version": "0.2",
            "run_id": run_id,
            "task_id": contract["task_id"],
            "plugin_id": recipe,
            "status": "completed",
        },
    )
    joblib.dump(model, artifact_dir / "model.joblib", compress=3)
    model_path = artifact_dir / "model.joblib"
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "0.2",
            "run_id": run_id,
            "task_id": contract["task_id"],
            "recipe": recipe,
            "contract_snapshot_sha256": sha256_file(
                run_dir / "task_contract.json"
            ),
            "artifacts": {
                "model.joblib": {
                    "sha256": sha256_file(model_path),
                    "bytes": model_path.stat().st_size,
                }
            },
        },
    )
    return run_dir


def _image_fixture(root: Path) -> tuple[Path, Path, Path]:
    training = root / "image-training"
    samples = root / "new-samples"
    training.mkdir()
    samples.mkdir(exist_ok=True)
    paths: list[Path] = []
    labels: list[str] = []
    for index, color in enumerate(((220, 20, 20), (180, 30, 30), (20, 20, 220), (30, 30, 180))):
        path = training / f"train-{index}.png"
        Image.new("RGB", (24, 20), color).save(path)
        paths.append(path)
        labels.append("red" if index < 2 else "blue")
    matrix = np.vstack([extract_image_feature(path, 16) for path in paths])
    estimator = LogisticRegression(random_state=7).fit(matrix, labels)
    contract: dict[str, object] = {
        "task_id": "image-task",
        "business_goal": "classify colors",
        "recipe": "image-folder-classification",
        "dataset": {"root": str(training)},
        "recipe_options": {"image_size": 16},
    }
    run_dir = _write_completed_run(
        root / "runs",
        "image-run",
        "image-folder-classification",
        contract,
        {
            "estimator": estimator,
            "labels": ["blue", "red"],
            "image_size": 16,
            "feature_version": "rgb-gradient-v1",
        },
    )
    sample = samples / "customer-red.png"
    Image.new("RGB", (30, 18), (210, 25, 25)).save(sample)
    return run_dir, sample, paths[0]


def _audio_fixture(root: Path) -> tuple[Path, Path]:
    training = root / "audio-training"
    samples = root / "new-samples"
    training.mkdir()
    samples.mkdir(exist_ok=True)
    feature_rows: list[np.ndarray] = []
    labels: list[str] = []
    for index, frequency in enumerate((320.0, 350.0, 900.0, 960.0)):
        path = training / f"clip-{index}.wav"
        path.write_bytes(_wav_bytes(frequency))
        feature_rows.append(
            extract_audio_feature(
                path,
                sample_rate=16_000,
                clip_seconds=0.5,
                n_mels=24,
                n_mfcc=13,
            )
        )
        labels.append("low" if index < 2 else "high")
    estimator = LogisticRegression(random_state=9, max_iter=500).fit(
        np.vstack(feature_rows), labels
    )
    contract: dict[str, object] = {
        "task_id": "audio-task",
        "business_goal": "classify tones",
        "recipe": "audio-keyword-classification",
        "dataset": {"root": str(training), "sample_rate": 16_000},
        "recipe_options": {
            "clip_seconds": 0.5,
            "n_mels": 24,
            "n_mfcc": 13,
        },
    }
    run_dir = _write_completed_run(
        root / "runs",
        "audio-run",
        "audio-keyword-classification",
        contract,
        {
            "estimator": estimator,
            "labels": ["high", "low"],
            "sample_rate": 16_000,
            "clip_seconds": 0.5,
            "n_mels": 24,
            "n_mfcc": 13,
            "feature_version": "log-mel-mfcc-summary-v1",
        },
    )
    sample = samples / "customer-low.wav"
    sample.write_bytes(_wav_bytes(335.0))
    return run_dir, sample


def _tabular_fixture(root: Path) -> Path:
    training = root / "tabular-training"
    training.mkdir()
    csv_path = training / "train.csv"
    csv_path.write_text("a,b,target\n0,0,0\n1,2,5\n2,3,8\n", encoding="utf-8")
    estimator = Pipeline(
        [("scale", StandardScaler()), ("model", LinearRegression())]
    ).fit(
        np.asarray([[0.0, 0.0], [1.0, 2.0], [2.0, 3.0]]),
        np.asarray([0.0, 5.0, 8.0]),
    )
    contract: dict[str, object] = {
        "task_id": "tabular-task",
        "business_goal": "predict target",
        "recipe": "tabular-regression",
        "dataset": {
            "csv_path": str(csv_path),
            "feature_columns": ["a", "b"],
            "target_column": "target",
        },
    }
    return _write_completed_run(
        root / "runs",
        "tabular-run",
        "tabular-regression",
        contract,
        {
            "estimator": estimator,
            "feature_columns": ["a", "b"],
            "target_column": "target",
            "task_type": "regression",
        },
    )


class SampleInferenceTests(unittest.TestCase):
    def test_real_image_audio_and_tabular_samples_predict_and_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_run, image_sample, _ = _image_fixture(root)
            audio_run, audio_sample = _audio_fixture(root)
            tabular_run = _tabular_fixture(root)

            image = SampleInference(image_run).run(image_sample)
            audio = SampleInference(audio_run).run(audio_sample)
            tabular = SampleInference(tabular_run).run(
                {"a": 4.0, "b": 7.0, "request_id": "new-1"}
            )

            self.assertEqual(image["sample"]["type"], "image")
            self.assertEqual(image["sample"]["format"], "PNG")
            self.assertEqual(image["prediction"], ["red"])
            self.assertEqual(audio["sample"]["type"], "audio")
            self.assertEqual(audio["sample"]["sample_rate"], 16_000)
            self.assertEqual(audio["prediction"], ["low"])
            self.assertEqual(tabular["sample"]["used_columns"], ["a", "b"])
            self.assertEqual(tabular["sample"]["ignored_columns"], ["request_id"])
            self.assertAlmostEqual(tabular["prediction"][0], 18.0, places=5)
            self.assertTrue(image["inference_check_id"].startswith("inference-"))
            self.assertNotIn(str(image_sample.resolve()), json.dumps(image))

            reopened = SampleInference(image_run)
            self.assertEqual(reopened.get(image["check_id"]), image)
            self.assertEqual(reopened.list(), [image])

            with RunService(root / "runs", recover=False) as service:
                via_service = service.sample_inference(
                    "tabular-run",
                    {"a": 2.0, "b": 3.0},
                    sample_type="tabular",
                )
                self.assertEqual(via_service["status"], "passed")
                self.assertEqual(
                    service.sample_inference_check(
                        "tabular-run", via_service["check_id"]
                    ),
                    via_service,
                )
                self.assertEqual(
                    service.sample_inference_checks("tabular-run"),
                    [tabular, via_service],
                )

    def test_single_row_csv_is_supported_but_multirow_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = _tabular_fixture(root)
            samples = root / "new-samples"
            samples.mkdir()
            one = samples / "one.csv"
            one.write_text("a,b,trace\n4,7,c-1\n", encoding="utf-8")
            check = SampleInference(run_dir).run(one)
            self.assertEqual(check["status"], "passed")
            self.assertEqual(check["sample"]["format"], "CSV")
            self.assertEqual(check["sample"]["ignored_columns"], ["trace"])

            two = samples / "two.csv"
            two.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
            with self.assertRaises(SampleInferenceBlocked) as blocked:
                SampleInference(run_dir).run(two)
            self.assertIn("exactly one data row", str(blocked.exception))
            self.assertEqual(blocked.exception.report["status"], "blocked")
            self.assertEqual(
                SampleInference(run_dir).get(blocked.exception.check_id),
                blocked.exception.report,
            )

    def test_training_data_bad_audio_and_tampering_are_blocked_and_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_run, _, training_image = _image_fixture(root)
            with self.assertRaises(SampleInferenceBlocked) as reused:
                SampleInference(image_run).run(training_image)
            self.assertIn("training, validation, or test", str(reused.exception))
            self.assertIsNone(reused.exception.report["sample"]["sha256"])

            audio_run, _ = _audio_fixture(root)
            invalid_audio = root / "new-samples" / "bad-rate.wav"
            invalid_audio.write_bytes(_wav_bytes(440.0, sample_rate=8_000))
            with self.assertRaises(SampleInferenceBlocked) as invalid:
                SampleInference(audio_run).run(invalid_audio)
            self.assertIn("16 kHz mono", str(invalid.exception))

            tabular_run = _tabular_fixture(root)
            contract_path = tabular_run / "task_contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["business_goal"] = "tampered"
            write_json(contract_path, contract)
            with self.assertRaises(SampleInferenceBlocked) as contract_error:
                SampleInference(tabular_run).run({"a": 1.0, "b": 2.0})
            self.assertIn("contract hash mismatch", str(contract_error.exception))

            model_path = image_run / "artifacts" / "model.joblib"
            with model_path.open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaises(SampleInferenceBlocked) as model_error:
                SampleInference(image_run).run(root / "new-samples" / "customer-red.png")
            self.assertIn("model.joblib hash mismatch", str(model_error.exception))
            self.assertEqual(
                len(SampleInference(image_run).list()),
                2,
            )


if __name__ == "__main__":
    unittest.main()
