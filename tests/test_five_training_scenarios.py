from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from model_harness.audio_keyword import ADAPTER
from model_harness.io_utils import read_json, write_json
from model_harness.plugins import PluginRegistry
from model_harness.recipes.audio_keyword_plugin import PLUGIN as AUDIO_PLUGIN
from model_harness.runner import verify_run
from model_harness.service import RunService
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE
from tests.test_audio_keyword_engine import _dataset_zip
from tests.test_tabular_loop import build_regression_csv
from tests.test_workspace_loop import build_image_dataset_zip

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import start_authorized_task_run


def _classification_csv() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_id", "signal", "batch", "decision"])
    for index in range(72):
        label = "pass" if index < 48 else "defect"
        signal = 8.0 + (index % 5) * 0.1 if label == "pass" else 1.0 + (index % 4) * 0.1
        batch = ["morning", "evening"][index % 2]
        writer.writerow([f"C-{index:04d}", signal, batch, label])
    return output.getvalue().encode("utf-8")


def _optimize(client, app, task_id: str, run_id: str, strategy_id: str) -> str:
    optimized = client.post(
        f"/tasks/{task_id}/runs/{run_id}/strategies/{strategy_id}/apply",
        json={"approval_confirmed": True},
    )
    if optimized.status_code != 202:
        raise AssertionError(optimized.text)
    child_run_id = optimized.json()["task"]["current_run_id"]
    if child_run_id == run_id:
        raise AssertionError("optimization reused the parent run")
    app.state.run_service.wait(child_run_id, timeout=120)
    return child_run_id


@unittest.skipIf(TestClient is None, "server extra is not installed")
class FiveTrainingScenarioTests(unittest.TestCase):
    def test_digit_classification_trains_and_records_contaminated_optimization(self) -> None:
        contract = dict(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"] = dict(contract["model_selection"])
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                parent = service.submit(contract, run_id="digits-parent")
                service.wait(parent.name, timeout=120)
                parent_result = service.result(parent.name)
                self.assertEqual(parent_result["run_status"], "completed")
                self.assertTrue(parent_result["release_ready"])
                verification = verify_run(parent, deep=True)
                self.assertTrue(verification["ok"], verification["errors"])

                child = service.apply_strategy(
                    parent.name,
                    "add-shift-augmentation",
                    child_run_id="digits-child",
                )
                service.wait(child.name, timeout=120)
                child_contract = read_json(child / "task_contract.json")
                child_result = service.result(child.name)
                self.assertEqual(child_result["run_status"], "completed")
                self.assertTrue(child_contract["evidence_policy"]["test_contaminated"])
                self.assertFalse(child_result["release_ready"])

    def test_image_folder_classification_trains_and_optimizes_without_test_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "零件颜色分类",
                        "business_goal": "区分红色零件和蓝色零件",
                        "recipe_id": "image-folder-classification",
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task_id = created.json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_zip(),
                    headers={"X-Filename": "parts.zip"},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                updated = client.patch(
                    f"/tasks/{task_id}/contract",
                    json={
                        "release_gates": {
                            "clean_test_accuracy_min": 0.5,
                            "clean_test_macro_f1_min": 0.5,
                            "clean_test_worst_class_recall_min": 0.5,
                        }
                    },
                )
                self.assertEqual(updated.status_code, 200, updated.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json=contract_confirmation_payload(client, task_id),
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = start_authorized_task_run(client, task_id)
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=120)
                parent = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(parent["status"], "completed")
                self.assertTrue(
                    parent["current_result"]["metrics"]["gate_checks"]["all_offline_gates_passed"]
                )
                child_run_id = _optimize(client, app, task_id, run_id, "balance-class-weights")
                child_contract = read_json(
                    app.state.run_service.runs_dir / child_run_id / "task_contract.json"
                )
                self.assertFalse(child_contract["evidence_policy"]["test_contaminated"])
                self.assertTrue(child_contract["recipe_options"]["class_weight_balanced"])
                child = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(child["status"], "completed")
                self.assertTrue(verify_run(app.state.run_service.runs_dir / child_run_id, deep=True)["ok"])

    def test_tabular_regression_trains_and_optimizes_without_test_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
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
                task_id = created.json()["task"]["task_id"]
                self.assertEqual(created.json()["task"]["recipe_id"], "tabular-regression")
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_regression_csv(60),
                    headers={
                        "Content-Type": "text/csv",
                        "X-Filename": "quality.csv",
                        "X-Target-Column": "quality",
                        "X-Ignored-Columns": "sample_id",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                updated = client.patch(
                    f"/tasks/{task_id}/contract",
                    json={"recipe_options": {"forest_estimators": 50}},
                )
                self.assertEqual(updated.status_code, 200, updated.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json=contract_confirmation_payload(client, task_id),
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = start_authorized_task_run(client, task_id)
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=120)
                parent = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(parent["status"], "completed")
                self.assertTrue(
                    parent["current_result"]["metrics"]["gate_checks"]["all_offline_gates_passed"]
                )
                child_run_id = _optimize(client, app, task_id, run_id, "increase-forest-capacity")
                child_contract = read_json(
                    app.state.run_service.runs_dir / child_run_id / "task_contract.json"
                )
                self.assertFalse(child_contract["evidence_policy"]["test_contaminated"])
                self.assertEqual(child_contract["recipe_options"]["forest_estimators"], 160)
                self.assertEqual(client.get(f"/tasks/{task_id}").json()["task"]["status"], "completed")
                self.assertTrue(verify_run(app.state.run_service.runs_dir / child_run_id, deep=True)["ok"])

    def test_tabular_classification_trains_and_optimizes_without_test_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "来料合格分类",
                        "business_goal": "根据检测信号判断来料是合格还是缺陷",
                        "capability_request": {
                            "modality": "tabular",
                            "objective": "classification",
                            "target_kind": "binary",
                            "target_column": "decision",
                        },
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                task_id = task["task_id"]
                self.assertEqual(task["recipe_id"], "tabular-classification")
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=_classification_csv(),
                    headers={
                        "Content-Type": "text/csv",
                        "X-Filename": "incoming.csv",
                        "X-Target-Column": "decision",
                        "X-Ignored-Columns": "sample_id",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                self.assertEqual(uploaded.json()["task"]["dataset_report"]["target_kind"], "categorical")
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json=contract_confirmation_payload(client, task_id),
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = start_authorized_task_run(client, task_id)
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=120)
                parent = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(parent["status"], "completed")
                metrics = parent["current_result"]["metrics"]
                self.assertNotEqual(metrics["selected_model"], "most_frequent_baseline")
                self.assertTrue(metrics["gate_checks"]["all_offline_gates_passed"])
                self.assertGreaterEqual(metrics["clean_test"]["macro_f1"], 0.75)
                child_run_id = _optimize(client, app, task_id, run_id, "balance-class-weights")
                child_contract = read_json(
                    app.state.run_service.runs_dir / child_run_id / "task_contract.json"
                )
                self.assertFalse(child_contract["evidence_policy"]["test_contaminated"])
                self.assertTrue(child_contract["recipe_options"]["class_weight_balanced"])
                self.assertEqual(client.get(f"/tasks/{task_id}").json()["task"]["status"], "completed")
                verification = verify_run(app.state.run_service.runs_dir / child_run_id, deep=True)
                self.assertTrue(verification["ok"], verification["errors"])

    def test_audio_keyword_classification_trains_and_optimizes_without_test_reuse(self) -> None:
        registry = PluginRegistry()
        registry.register_recipe(AUDIO_PLUGIN)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            imported = ADAPTER.import_data(
                root / "datasets",
                _dataset_zip(),
                "keywords.zip",
                {"sample_rate": 16_000, "channels": 1, "random_seed": 17},
            )
            contract = AUDIO_PLUGIN.template()
            contract["task_id"] = "keyword-scenario"
            contract["business_goal"] = "区分两个已分段的本地控制词"
            contract["dataset"].update(imported.contract_dataset)
            contract["dataset"]["split"] = {"train": 0.50, "validation": 0.25, "test": 0.25}
            contract["recipe_options"]["clip_seconds"] = 0.50
            contract["recipe_options"]["extra_trees_estimators"] = 50
            AUDIO_PLUGIN.validate_contract(contract)
            write_json(root / "task_contract.json", contract)
            with RunService(root / "runs", registry=registry, recover=False) as service:
                parent = service.submit(contract, run_id="audio-parent")
                service.wait(parent.name, timeout=120)
                parent_result = service.result(parent.name)
                self.assertEqual(parent_result["run_status"], "completed")
                self.assertTrue(
                    parent_result["metrics"]["gate_checks"]["all_offline_gates_passed"]
                )
                self.assertNotEqual(
                    parent_result["metrics"]["selected_model"],
                    "most_frequent_baseline",
                )
                self.assertFalse(
                    service.strategies(parent.name)["evidence_provenance"]["uses_test_evidence"]
                )
                child = service.apply_strategy(
                    parent.name,
                    "increase-extra-trees",
                    child_run_id="audio-child",
                )
                service.wait(child.name, timeout=120)
                child_contract = read_json(child / "task_contract.json")
                child_result = service.result(child.name)
                self.assertEqual(child_result["run_status"], "completed")
                self.assertFalse(child_contract["evidence_policy"]["test_contaminated"])
                self.assertEqual(child_contract["recipe_options"]["extra_trees_estimators"], 120)
                self.assertTrue(
                    child_result["metrics"]["gate_checks"]["all_offline_gates_passed"]
                )
                self.assertTrue(verify_run(child, deep=True, registry=registry)["ok"])


if __name__ == "__main__":
    unittest.main()
