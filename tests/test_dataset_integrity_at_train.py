from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.audio_keyword import ADAPTER as AUDIO_ADAPTER
from model_harness.errors import ContractError
from model_harness.io_utils import read_json
from model_harness.recipes.audio_keyword_plugin import PLUGIN as AUDIO_PLUGIN
from model_harness.server import create_app
from tests.test_audio_keyword_engine import _dataset_zip as build_audio_dataset_zip
from tests.contract_confirmation import contract_confirmation_payload
from tests.test_tabular_loop import build_regression_csv
from tests.test_workspace_loop import build_image_dataset_zip
from tests.run_authorization import start_authorized_task_run


@unittest.skipIf(TestClient is None, "server extra is not installed")
class DatasetIntegrityAtTrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.temp_dir.name) / "runs"
        self.app = create_app(self.runs_dir)
        self.app.state.run_service.registry.register_recipe(AUDIO_PLUGIN)
        self.app.state.training_workspace.data_adapters.register(AUDIO_ADAPTER)
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _confirm(self, task_id: str) -> None:
        response = self.client.post(
            f"/tasks/{task_id}/confirm",
            json=contract_confirmation_payload(self.client, task_id),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _create_tabular_task(self) -> tuple[str, dict[str, object]]:
        created = self.client.post(
            "/tasks",
            json={
                "name": "训练前表格完整性",
                "business_goal": "根据设备参数预测质量评分",
                "recipe_id": "tabular-regression",
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
        uploaded = self.client.post(
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
        self._confirm(task_id)
        return task_id, uploaded.json()["task"]["contract"]["dataset"]

    def _create_image_task(self) -> tuple[str, dict[str, object]]:
        created = self.client.post(
            "/tasks",
            json={
                "name": "训练前图片完整性",
                "business_goal": "区分红色和蓝色零件",
                "recipe_id": "image-folder-classification",
                "capability_request": {"family": "image_classification"},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["task"]["task_id"]
        uploaded = self.client.post(
            f"/tasks/{task_id}/dataset",
            content=build_image_dataset_zip(),
            headers={"Content-Type": "application/zip", "X-Filename": "parts.zip"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self._confirm(task_id)
        return task_id, uploaded.json()["task"]["contract"]["dataset"]

    def _create_audio_task(self) -> tuple[str, dict[str, object]]:
        created = self.client.post(
            "/tasks",
            json={
                "name": "训练前音频完整性",
                "business_goal": "识别 yes 和 no 两个本地控制词",
                "recipe_id": "audio-keyword-classification",
                "capability_request": {"family": "audio_classification"},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["task"]["task_id"]
        uploaded = self.client.post(
            f"/tasks/{task_id}/dataset",
            content=build_audio_dataset_zip(),
            headers={"Content-Type": "application/zip", "X-Filename": "keywords.zip"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self._confirm(task_id)
        return task_id, uploaded.json()["task"]["contract"]["dataset"]

    def _assert_integrity_failure(self, task_id: str) -> None:
        started = start_authorized_task_run(self.client, task_id)
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()["task"]["current_run_id"]
        with self.assertRaisesRegex(ContractError, "数据完整性"):
            self.app.state.run_service.wait(run_id, timeout=30)
        state = read_json(self.runs_dir / run_id / "run_state.json")
        self.assertEqual(state["status"], "failed")
        self.assertIn("数据完整性", state["error"])

    def _assert_completed(self, task_id: str) -> None:
        started = start_authorized_task_run(self.client, task_id)
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()["task"]["current_run_id"]
        self.app.state.run_service.wait(run_id, timeout=30)
        self.assertEqual(
            read_json(self.runs_dir / run_id / "run_state.json")["status"],
            "completed",
        )

    def test_tabular_tamper_after_confirmation_fails_run(self) -> None:
        task_id, dataset = self._create_tabular_task()
        with Path(str(dataset["csv_path"])).open("ab") as handle:
            handle.write(b"S-tampered,20.0,100.0,A,1.0\n")
        self._assert_integrity_failure(task_id)

    def test_image_tamper_after_confirmation_fails_run(self) -> None:
        task_id, dataset = self._create_image_task()
        manifest = read_json(Path(str(dataset["manifest_path"])))
        path = Path(str(dataset["root"])) / manifest["samples"][0]["relative_path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        self._assert_integrity_failure(task_id)

    def test_audio_tamper_after_confirmation_fails_run(self) -> None:
        task_id, dataset = self._create_audio_task()
        manifest = read_json(Path(str(dataset["manifest_path"])))
        path = Path(str(dataset["root"])) / manifest["samples"][0]["relative_path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        self._assert_integrity_failure(task_id)

    def test_untampered_datasets_complete_for_all_three_recipes(self) -> None:
        for name, factory in (
            ("tabular", self._create_tabular_task),
            ("image", self._create_image_task),
            ("audio", self._create_audio_task),
        ):
            with self.subTest(recipe=name):
                task_id, _dataset = factory()
                self._assert_completed(task_id)


if __name__ == "__main__":
    unittest.main()
