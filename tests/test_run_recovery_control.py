from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.io_utils import read_json, write_json
from model_harness.runner import prepare_run
from model_harness.server import create_app
from model_harness.state import RunState
from model_harness.workspace import TrainingWorkspace


def _image_dataset_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for label, color in (("red", (225, 35, 35)), ("blue", (35, 70, 225))):
            for index in range(8):
                image = Image.new("RGB", (20, 20), color)
                image.putpixel((index + 1, index + 1), (255, 255, 255))
                payload = io.BytesIO()
                image.save(payload, format="PNG")
                archive.writestr(f"parts/{label}/{index}.png", payload.getvalue())
    return output.getvalue()


class RunRecoveryControlTests(unittest.TestCase):
    def test_terminal_runs_project_one_task_owned_retry_action(self) -> None:
        workspace = TrainingWorkspace.__new__(TrainingWorkspace)
        spec = {"capability_decision": {"status": "resolved"}}

        for status in ("failed", "cancelled", "interrupted"):
            with self.subTest(status=status):
                control = workspace._control_projection(  # noqa: SLF001
                    {
                        "task_id": "task-retry",
                        "status": status,
                        "capability_status": "matched",
                        "dataset_id": "dataset-one",
                        "contract_confirmed": True,
                    },
                    spec,
                    {"run_id": "run-old", "status": status},
                )

                self.assertEqual(control["current_stage"], "run_recovery")
                self.assertEqual(len(control["blocked_by"]), 1)
                self.assertIn("证据", control["blocked_by"][0]["message"])
                self.assertEqual(
                    control["next_action"],
                    {
                        "id": "retry_training_run",
                        "label": "检查证据并重新训练",
                        "method": "POST",
                        "href": "/tasks/task-retry/runs",
                    },
                )


@unittest.skipIf(TestClient is None, "server extra is not installed")
class RunRecoveryApiTests(unittest.TestCase):
    def test_task_owned_start_api_retries_without_overwriting_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runs_dir = Path(temporary) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "可重试零件分类",
                        "business_goal": "区分红色和蓝色零件",
                        "recipe_id": "image-folder-classification",
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task_id = created.json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=_image_dataset_zip(),
                    headers={
                        "Content-Type": "application/zip",
                        "X-Filename": "parts.zip",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)

                workspace = app.state.training_workspace
                task_path = workspace.tasks_dir / task_id / "task.json"
                contract = read_json(workspace._contract_path(task_id))  # noqa: SLF001
                failed_run = prepare_run(
                    contract,
                    runs_dir,
                    run_id="failed-original",
                    workspace_task_id=task_id,
                    workspace_root=workspace.root,
                )
                RunState.load(failed_run).fail("synthetic worker failure for retry contract test")
                persisted = read_json(task_path)
                persisted.update(
                    {
                        "status": "running",
                        "current_run_id": failed_run.name,
                        "run_ids": [failed_run.name],
                    }
                )
                write_json(task_path, persisted)

                failed_task = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(failed_task["status"], "failed")
                self.assertEqual(
                    failed_task["control"]["next_action"]["id"],
                    "retry_training_run",
                )

                retried = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(retried.status_code, 202, retried.text)
                retry_task = retried.json()["task"]
                new_run_id = retry_task["current_run_id"]
                self.assertNotEqual(new_run_id, failed_run.name)
                self.assertEqual(
                    retry_task["run_ids"],
                    [failed_run.name, new_run_id],
                )
                self.assertEqual(
                    read_json(failed_run / "run_state.json")["status"],
                    "failed",
                )
                old_event_types = {
                    item["type"] for item in app.state.run_service.events(failed_run.name)
                }
                self.assertIn("run.failed", old_event_types)
                app.state.run_service.wait(new_run_id, timeout=30)


if __name__ == "__main__":
    unittest.main()
