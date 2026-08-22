from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LinearRegression

from model_harness.evidence import (
    ArtifactBundleBuilder,
    EvidenceError,
    EvidenceRepository,
    EvaluationReport,
    InferenceBlocked,
    InferenceCheck,
)
from model_harness.io_utils import read_json, sha256_file, write_json


def create_completed_run(
    root: Path,
    *,
    gates_pass: bool = True,
    test_count: int = 30,
    test_contaminated: bool = False,
    recipe: str = "tabular-regression",
    absolute_model_card: bool = False,
) -> Path:
    run_dir = root / "run-fixture"
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True)
    estimator = LinearRegression().fit(
        np.asarray([[0.0, 0.0], [1.0, 1.0], [2.0, 3.0], [3.0, 5.0]]),
        np.asarray([0.0, 2.0, 5.0, 8.0]),
    )
    joblib.dump(
        {
            "estimator": estimator,
            "feature_columns": ["a", "b"],
            "target_column": "target",
            "task_type": "regression",
        },
        artifact_dir / "model.joblib",
    )
    metrics = {
        "split_counts": {"train": 100, "validation": 25, "test": test_count},
        "clean_test": {"mae": 0.1 if gates_pass else 9.9},
        "gate_checks": {
            "clean_test_mae": gates_pass,
            "model_size_mb": True,
            "all_offline_gates_passed": gates_pass,
        },
        "test_set_used_for_selection": test_contaminated,
    }
    write_json(artifact_dir / "metrics.json", metrics)
    (artifact_dir / "model_card.md").write_text(
        (
            "Model learned from /Users/example/private/data.csv\n"
            if absolute_model_card
            else "# Trusted fixture model\n"
        ),
        encoding="utf-8",
    )
    (artifact_dir / "inference_example.py").write_text(
        "# Load model.joblib and call predict on one explicit row.\n",
        encoding="utf-8",
    )
    write_json(artifact_dir / "failure_samples.json", {"samples": [{"row": 9}]})
    write_json(
        artifact_dir / "dataset_report.json",
        {"source_filename": "private-customer-data.csv"},
    )
    joblib.dump(
        {"X": np.asarray([[99.0, 100.0]]), "predictions": np.asarray([199.0])},
        artifact_dir / "test_reference.joblib",
    )
    (artifact_dir / "raw-user-data.csv").write_text(
        "name,secret\nalice,private\n", encoding="utf-8"
    )
    contract = {
        "task_id": "task-fixture",
        "business_goal": "fixture",
        "recipe": recipe,
    }
    write_json(run_dir / "task_contract.json", contract)
    state = {
        "schema_version": "0.2",
        "task_id": "task-fixture",
        "run_id": "run-fixture",
        "plugin_id": recipe,
        "status": "completed",
    }
    write_json(run_dir / "run_state.json", state)
    (run_dir / "events.ndjson").write_text(
        '{"type":"run.completed"}\n', encoding="utf-8"
    )
    artifacts = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in artifact_dir.iterdir()
        if path.is_file()
    }
    manifest = {
        "schema_version": "0.2",
        "task_id": "task-fixture",
        "run_id": "run-fixture",
        "recipe": recipe,
        "plugin_version": "1.0.0",
        "dependencies": {
            "scikit_learn": "1.7.0",
            "joblib": "1.5.0",
        },
        "contract_snapshot_sha256": sha256_file(run_dir / "task_contract.json"),
        "artifacts": artifacts,
    }
    write_json(run_dir / "run_manifest.json", manifest)
    (run_dir / "private-dataset").mkdir()
    (run_dir / "private-dataset" / "raw.csv").write_text(
        "private,data\n", encoding="utf-8"
    )
    return run_dir


class EvaluationReportTests(unittest.TestCase):
    def test_release_dimensions_are_separate_and_report_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir))
            report = EvaluationReport(run_dir).build(minimum_test_samples=20)

            self.assertEqual(report["run_status"], "completed")
            self.assertEqual(report["integrity_status"], "passed")
            self.assertEqual(report["metric_gate_status"], "passed")
            self.assertEqual(report["evidence_status"], "sufficient")
            self.assertEqual(report["conclusion"], "release_ready")
            self.assertTrue(report["release_ready"])

            reopened = EvaluationReport(run_dir).get()
            self.assertEqual(reopened, report)
            rebuilt = EvaluationReport(run_dir).build(minimum_test_samples=20)
            self.assertEqual(rebuilt["report_id"], report["report_id"])
            self.assertEqual(
                EvidenceRepository(run_dir).report()["evaluation_report"]["report_id"],
                report["report_id"],
            )

    def test_quality_failure_does_not_turn_artifact_integrity_red(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir), gates_pass=False)
            report = EvaluationReport(run_dir).build()

            self.assertEqual(report["integrity_status"], "passed")
            self.assertEqual(report["metric_gate_status"], "failed")
            self.assertEqual(report["evidence_status"], "sufficient")
            self.assertEqual(report["conclusion"], "quality_failed")
            self.assertFalse(report["release_ready"])

    def test_small_or_contaminated_test_evidence_cannot_be_release_ready(self) -> None:
        cases = (
            {"test_count": 3, "test_contaminated": False},
            {"test_count": 30, "test_contaminated": True},
        )
        for index, options in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temp_dir:
                run_dir = create_completed_run(Path(temp_dir), **options)
                report = EvaluationReport(run_dir).build(minimum_test_samples=20)
                self.assertEqual(report["integrity_status"], "passed")
                self.assertEqual(report["metric_gate_status"], "passed")
                self.assertEqual(report["evidence_status"], "insufficient_evidence")
                self.assertEqual(report["conclusion"], "insufficient_evidence")
                self.assertFalse(report["release_ready"])


class InferenceCheckTests(unittest.TestCase):
    def test_hash_bound_joblib_prediction_is_real_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir))
            model = joblib.load(run_dir / "artifacts" / "model.joblib")
            expected = model["estimator"].predict([[4.0, 7.0]]).tolist()

            check = InferenceCheck(run_dir).run(
                {"features": [4.0, 7.0], "expected": expected}
            )

            self.assertEqual(check["status"], "passed")
            self.assertFalse(check["blocked"])
            self.assertTrue(check["reference_match"])
            self.assertEqual(check["output"], expected)
            self.assertEqual(check["input"]["shape"], [1, 2])
            self.assertNotIn("features", check["input"])
            self.assertGreaterEqual(check["elapsed_ms"], 0)
            reopened = InferenceCheck(run_dir)
            self.assertEqual(reopened.get(check["check_id"]), check)
            self.assertEqual(reopened.list(), [check])

    def test_tampered_or_unsupported_joblib_is_blocked_and_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tampered = create_completed_run(Path(temp_dir) / "tampered")
            with (tampered / "artifacts" / "model.joblib").open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaises(InferenceBlocked) as blocked:
                InferenceCheck(tampered).run({"features": [1.0, 2.0]})
            self.assertIn("integrity", str(blocked.exception))
            self.assertEqual(blocked.exception.check["status"], "blocked")
            self.assertEqual(
                InferenceCheck(tampered).get(blocked.exception.check_id)["status"],
                "blocked",
            )

            unsupported = create_completed_run(
                Path(temp_dir) / "unsupported",
                recipe="custom-unsafe-recipe",
            )
            with self.assertRaises(InferenceBlocked) as unsupported_error:
                InferenceCheck(unsupported).run({"features": [1.0, 2.0]})
            self.assertIn("unsupported Joblib recipe", str(unsupported_error.exception))


class ArtifactBundleTests(unittest.TestCase):
    def test_nested_model_asset_artifacts_are_verified_and_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir))
            artifact_dir = run_dir / "artifacts"
            base_model = artifact_dir / "base_model"
            base_model.mkdir()
            (base_model / "model.onnx").write_bytes(b"safe fixture onnx")
            write_json(
                base_model / "config.json",
                {"input_shape": [3, 8, 8], "classes": ["feature"]},
            )
            write_json(
                artifact_dir / "model_asset_provenance.json",
                {"provider": "huggingface", "resolved_commit": "a" * 40},
            )
            manifest = read_json(run_dir / "run_manifest.json")
            for path in (
                base_model / "model.onnx",
                base_model / "config.json",
                artifact_dir / "model_asset_provenance.json",
            ):
                name = path.relative_to(artifact_dir).as_posix()
                manifest["artifacts"][name] = {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            write_json(run_dir / "run_manifest.json", manifest)

            evaluation = EvaluationReport(run_dir).build()
            self.assertEqual(evaluation["integrity_status"], "passed")
            record = ArtifactBundleBuilder(run_dir).build()
            archive_path = ArtifactBundleBuilder(run_dir).bundle_path(
                record["bundle_id"]
            )
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("artifacts/base_model/model.onnx", names)
            self.assertIn("artifacts/base_model/config.json", names)
            self.assertIn("artifacts/model_asset_provenance.json", names)

    def test_bundle_is_atomic_hashed_and_excludes_private_or_internal_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(
                Path(temp_dir), absolute_model_card=True
            )
            EvaluationReport(run_dir).build()
            model = joblib.load(run_dir / "artifacts" / "model.joblib")
            expected = model["estimator"].predict([[2.0, 4.0]]).tolist()
            inference = InferenceCheck(run_dir).run(
                {"features": [2.0, 4.0], "expected": expected}
            )
            builder = ArtifactBundleBuilder(run_dir)

            record = builder.build(inference_check_id=inference["check_id"])
            archive_path = builder.bundle_path(record["bundle_id"])

            self.assertEqual(record["status"], "completed")
            self.assertEqual(sha256_file(archive_path), record["archive"]["sha256"])
            self.assertEqual(builder.get(record["bundle_id"]), record)
            self.assertEqual(builder.list(), [record])
            self.assertFalse(any(builder.bundles_dir.glob(".*.tmp")))
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("artifacts/model.joblib", names)
                self.assertIn("artifacts/metrics.json", names)
                self.assertIn("evidence/evaluation_report.json", names)
                self.assertIn("evidence/inference_check.json", names)
                self.assertIn("environment.json", names)
                self.assertIn("bundle_manifest.json", names)
                for forbidden in (
                    "artifacts/test_reference.joblib",
                    "artifacts/failure_samples.json",
                    "artifacts/dataset_report.json",
                    "artifacts/raw-user-data.csv",
                    "task_contract.json",
                    "run_state.json",
                    "events.ndjson",
                    "artifacts/model_card.md",
                ):
                    self.assertNotIn(forbidden, names)

                manifest = json.loads(archive.read("bundle_manifest.json"))
                self.assertFalse(manifest["privacy_boundary"]["raw_data_included"])
                self.assertFalse(
                    manifest["privacy_boundary"]["test_references_included"]
                )
                self.assertFalse(
                    manifest["privacy_boundary"]["absolute_paths_in_manifest"]
                )
                self.assertNotIn(str(run_dir), json.dumps(manifest))
                for item in manifest["files"]:
                    payload = archive.read(item["path"])
                    self.assertEqual(len(payload), item["size_bytes"])
                    self.assertEqual(
                        __import__("hashlib").sha256(payload).hexdigest(),
                        item["sha256"],
                    )
                excluded_paths = {item["path"] for item in manifest["excluded"]}
                self.assertIn("artifacts/test_reference.joblib", excluded_paths)
                self.assertIn("artifacts/model_card.md", excluded_paths)
                self.assertIn("datasets/**", excluded_paths)

            reopened = EvidenceRepository(run_dir).report()
            self.assertEqual(reopened["artifact_bundles"][0]["bundle_id"], record["bundle_id"])

    def test_bundle_rejects_tampered_source_even_after_old_evaluation_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir))
            EvaluationReport(run_dir).build()
            (run_dir / "artifacts" / "metrics.json").write_text(
                "{}\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(EvidenceError, "integrity"):
                ArtifactBundleBuilder(run_dir).build()

    def test_bundle_rejects_a_stale_report_even_when_new_artifacts_are_self_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = create_completed_run(Path(temp_dir))
            EvaluationReport(run_dir).build()
            metrics_path = run_dir / "artifacts" / "metrics.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["clean_test"]["mae"] = 0.2
            write_json(metrics_path, metrics)
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["metrics.json"] = {
                "sha256": sha256_file(metrics_path),
                "bytes": metrics_path.stat().st_size,
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(EvidenceError, "stale"):
                ArtifactBundleBuilder(run_dir).build()


if __name__ == "__main__":
    unittest.main()
