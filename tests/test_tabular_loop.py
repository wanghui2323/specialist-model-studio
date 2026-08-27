from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.contracts import ContractError, validate_contract
from model_harness.data_adapters import DataAdapterRegistry
from model_harness.io_utils import write_json
from model_harness.plugins import PluginRegistry
from model_harness.recipes.tabular_regression import TrainingContext, evaluate
from model_harness.runner import verify_run
from model_harness.server import create_app
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import start_authorized_task_run


def build_regression_csv(row_count: int = 180) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_id", "temperature", "pressure", "machine_type", "quality"])
    for index in range(row_count):
        temperature = 18.0 + (index % 37) * 0.7
        pressure = 90.0 + (index % 23) * 1.3
        machine_type = ["A", "B", "C"][index % 3]
        machine_effect = {"A": 1.2, "B": -0.4, "C": 0.6}[machine_type]
        quality = 0.42 * temperature - 0.08 * pressure + machine_effect + (index % 5) * 0.03
        writer.writerow([f"S-{index:04d}", temperature, pressure, machine_type, round(quality, 4)])
    return output.getvalue().encode("utf-8")


def build_raw_scale_regression_csv(row_count: int = 180) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_id", "signal", "disease_progression"])
    for index in range(row_count):
        target = 25 + ((index * 37) % 322)
        writer.writerow([f"D-{index:04d}", index / 10.0, target])
    return output.getvalue().encode("utf-8")


@unittest.skipIf(TestClient is None, "server extra is not installed")
class TabularLoopTests(unittest.TestCase):
    def test_raw_target_scale_drives_regression_error_gates_and_records_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "疾病进展预测",
                        "business_goal": "根据检查数据预测疾病进展数值",
                        "capability_request": {
                            "modality": "tabular",
                            "objective": "regression",
                            "target_kind": "numeric",
                            "target_column": "disease_progression",
                        },
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task_id = created.json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_raw_scale_regression_csv(),
                    headers={
                        "Content-Type": "text/csv",
                        "X-Filename": "disease.csv",
                        "X-Target-Column": "disease_progression",
                        "X-Ignored-Columns": "sample_id",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                task = uploaded.json()["task"]
                summary = task["dataset_report"]["target_summary"]
                contract = task["contract"]
                gates = contract["release_gates"]
                basis = contract["release_gate_basis"]

                self.assertEqual(summary["value_space"], "raw")
                self.assertEqual(summary["target_transform"], "none")
                self.assertFalse(summary["target_standardized"])
                self.assertGreater(summary["mean_baseline_mae"], 1.0)
                self.assertGreater(summary["mean_baseline_rmse"], 1.0)
                self.assertAlmostEqual(
                    gates["clean_test_mae_max"],
                    summary["mean_baseline_mae"] * 0.9,
                    places=8,
                )
                self.assertAlmostEqual(
                    gates["clean_test_rmse_max"],
                    summary["mean_baseline_rmse"] * 0.9,
                    places=8,
                )
                self.assertNotEqual(gates["clean_test_mae_max"], 0.8)
                self.assertNotEqual(gates["clean_test_rmse_max"], 1.1)
                self.assertEqual(basis["target_column"], "disease_progression")
                self.assertEqual(basis["target_value_space"], "raw")
                self.assertEqual(basis["target_transform"], "none")
                self.assertEqual(basis["metric_unit"], "same_as_target_column")
                self.assertEqual(
                    basis["dataset_fingerprint_sha256"],
                    task["dataset_report"]["fingerprint_sha256"],
                )
                self.assertTrue(basis["requires_human_review"])

                explicitly_changed = client.patch(
                    f"/tasks/{task_id}/contract",
                    json={
                        "release_gates": {
                            "clean_test_mae_max": 40.0,
                            "clean_test_rmse_max": 55.0,
                        }
                    },
                )
                self.assertEqual(
                    explicitly_changed.status_code, 200, explicitly_changed.text
                )
                changed_basis = explicitly_changed.json()["task"]["contract"][
                    "release_gate_basis"
                ]
                self.assertEqual(
                    changed_basis["thresholds"]["clean_test_mae_max"]["source"],
                    "explicit_contract_override",
                )
                self.assertEqual(
                    changed_basis["thresholds"]["clean_test_rmse_max"]["source"],
                    "explicit_contract_override",
                )

    def test_legacy_unitless_regression_defaults_fail_closed_on_raw_wide_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = PluginRegistry(include_builtins=True)
            imported = DataAdapterRegistry(include_builtins=True).get(
                "tabular-csv"
            ).import_data(
                Path(temp_dir) / "datasets",
                build_raw_scale_regression_csv(),
                "disease.csv",
                {
                    "target_column": "disease_progression",
                    "ignored_columns": ["sample_id"],
                    "objective": "regression",
                },
            )
            contract = registry.get_recipe("tabular-regression").template()
            contract["dataset"].update(imported.contract_dataset)
            with self.assertRaisesRegex(
                ContractError,
                "not bound to the raw target scale",
            ):
                validate_contract(contract, registry=registry)

    def test_capability_task_csv_contract_run_and_artifacts_form_a_real_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "质量评分预测",
                        "business_goal": "根据设备参数预测质量评分",
                        "capability_request": {
                            "modality": "tabular",
                            "objective": "regression",
                            "target_kind": "numeric",
                            "target_column": "quality",
                        },
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                task_id = task["task_id"]
                self.assertEqual(task["recipe_id"], "tabular-regression")
                self.assertEqual(task["status"], "awaiting_data")

                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_regression_csv(),
                    headers={
                        "Content-Type": "text/csv",
                        "X-Filename": "quality.csv",
                        "X-Target-Column": "quality",
                        "X-Ignored-Columns": "sample_id",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                task = uploaded.json()["task"]
                self.assertEqual(task["data_adapter_id"], "tabular-csv")
                self.assertEqual(task["dataset_report"]["row_count"], 180)
                self.assertEqual(task["contract"]["recipe"], "tabular-regression")

                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json=contract_confirmation_payload(client, task_id),
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = start_authorized_task_run(client, task_id)
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=30)

                reopened = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(reopened["status"], "completed")
                self.assertEqual(reopened["current_result"]["recipe"], "tabular-regression")
                metrics = reopened["current_result"]["metrics"]
                self.assertLess(metrics["clean_test"]["mae"], 0.8)
                self.assertGreater(metrics["clean_test"]["r2"], 0.2)
                artifact_names = {item["name"] for item in reopened["current_result"]["artifacts"]}
                self.assertIn("model.joblib", artifact_names)
                self.assertIn("test_predictions.csv", artifact_names)
                verification = verify_run(runs_dir / run_id, deep=True)
                self.assertTrue(verification["ok"], verification["errors"])
                self.assertTrue(verification["deep_verified"])

    def test_unmatched_capability_creates_persistent_recipe_build_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "设备异响识别",
                        "business_goal": "从现场音频识别三类设备异响",
                        "capability_request": {
                            "modality": "audio",
                            "objective": "classification",
                            "target_kind": "multiclass",
                        },
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                task_id = task["task_id"]
                self.assertEqual(task["status"], "needs_recipe")
                self.assertEqual(task["recipe_request"]["status"], "needs_implementation")
                request_id = task["recipe_request"]["recipe_request_id"]

                scaffolded = client.post(f"/tasks/{task_id}/recipe/scaffold")
                self.assertEqual(scaffolded.status_code, 201, scaffolded.text)
                scaffold = scaffolded.json()["scaffold"]
                self.assertEqual(scaffold["status"], "scaffold_ready")
                self.assertTrue(all(check["passed"] for check in scaffold["checks"]))
                downloaded = client.get(scaffold["download_url"])
                self.assertEqual(downloaded.status_code, 200, downloaded.text)
                archive_path = Path(temp_dir) / "scaffold.zip"
                archive_path.write_bytes(downloaded.content)
                with zipfile.ZipFile(archive_path) as archive:
                    names = set(archive.namelist())
                self.assertTrue(any(name.endswith("recipe_plugin.py") for name in names))
                self.assertTrue(any(name.endswith("BUILD_REQUEST.json") for name in names))

            restarted = create_app(runs_dir)
            with TestClient(restarted) as client:  # type: ignore[misc]
                reopened = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(reopened["task_id"], task_id)
                self.assertEqual(reopened["recipe_request"]["recipe_request_id"], request_id)
                self.assertEqual(reopened["recipe_request"]["status"], "scaffold_ready")
                self.assertEqual(reopened["run_ids"], [])

    def test_failure_count_tracks_gate_breaches_not_diagnostic_sample_limit(self) -> None:
        class OffsetRegressor:
            def __init__(self, offset: float) -> None:
                self.offset = offset

            def predict(self, values: np.ndarray) -> np.ndarray:
                return np.asarray(values[:, 0], dtype=np.float64) + self.offset

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "dataset_report.json"
            write_json(
                report_path,
                {
                    "dataset_id": "failure-count-dataset",
                    "fingerprint_sha256": "fixture-fingerprint",
                    "row_count": 90,
                    "feature_columns": ["signal"],
                    "target_column": "quality",
                },
            )
            values = np.arange(90, dtype=np.float64)
            test_idx = np.arange(50, 90, dtype=np.int64)

            def context(offset: float) -> TrainingContext:
                return TrainingContext(
                    X=values.reshape(-1, 1),
                    y=values,
                    row_numbers=np.arange(2, 92, dtype=np.int64),
                    train_idx=np.arange(0, 30, dtype=np.int64),
                    validation_idx=np.arange(30, 50, dtype=np.int64),
                    test_idx=test_idx,
                    selected_name=f"offset-{offset}",
                    final_model=OffsetRegressor(offset),
                    validation_results={},
                    feature_columns=["signal"],
                    target_column="quality",
                )

            contract = {
                "task_id": "failure-count-task",
                "recipe": "tabular-regression",
                "dataset": {"report_path": str(report_path)},
                "diagnostics": {"failure_sample_limit": 24},
                "release_gates": {"clean_test_mae_max": 0.8},
            }
            good_evaluation = evaluate(context(0.0), contract)
            bad_evaluation = evaluate(context(2.0), contract)
            good = good_evaluation.metrics
            bad = bad_evaluation.metrics
            self.assertGreater(len(test_idx), 24)
            self.assertGreater(bad["clean_test"]["mae"], good["clean_test"]["mae"])
            self.assertEqual(good["failure_count"], 0)
            self.assertNotEqual(bad["failure_count"], 24)
            self.assertGreater(bad["failure_count"], good["failure_count"])
            self.assertLessEqual(bad["failure_count"], bad["split_counts"]["test"])
            self.assertEqual(
                bad["failure_sample_count"],
                min(24, bad["split_counts"]["test"]),
            )
            self.assertEqual(
                len(bad_evaluation.failure_samples),
                bad["failure_sample_count"],
            )


if __name__ == "__main__":
    unittest.main()
