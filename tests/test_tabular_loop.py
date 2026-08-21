from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.runner import verify_run
from model_harness.server import create_app


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


@unittest.skipIf(TestClient is None, "server extra is not installed")
class TabularLoopTests(unittest.TestCase):
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
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = client.post(f"/tasks/{task_id}/runs")
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


if __name__ == "__main__":
    unittest.main()
