from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app


@unittest.skipIf(TestClient is None, "server extra is not installed")
class TaskArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.temp_dir.name) / "runs"
        self.app = create_app(self.runs_dir)
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _create_task(self, name: str = "待归档任务") -> dict[str, object]:
        response = self.client.post(
            "/tasks",
            json={"name": name, "business_goal": "验证任务软归档生命周期"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["task"]

    def _raw_task_path(self, task_id: str) -> Path:
        return self.app.state.training_workspace.tasks_dir / task_id / "task.json"

    def _write_raw_task(self, task_id: str, **changes: object) -> dict[str, object]:
        path = self._raw_task_path(task_id)
        task = json.loads(path.read_text(encoding="utf-8"))
        task.update(changes)
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        return task

    def test_archive_non_running_task_persists_timestamp(self) -> None:
        task = self._create_task()
        response = self.client.post(f"/tasks/{task['task_id']}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["task"]["archived_at_utc"])

    def test_archived_task_is_filtered_from_default_list(self) -> None:
        task = self._create_task()
        task_id = str(task["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        visible_ids = {item["task_id"] for item in self.client.get("/tasks").json()["tasks"]}
        all_ids = {
            item["task_id"]
            for item in self.client.get("/tasks?include_archived=true").json()["tasks"]
        }
        self.assertNotIn(task_id, visible_ids)
        self.assertIn(task_id, all_ids)

    def test_archived_task_detail_remains_accessible(self) -> None:
        task = self._create_task()
        task_id = str(task["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        response = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["task"]["task_id"], task_id)
        self.assertTrue(response.json()["task"]["archived_at_utc"])

    def test_running_task_cannot_be_archived_and_is_unchanged(self) -> None:
        task = self._create_task()
        task_id = str(task["task_id"])
        before = self._write_raw_task(task_id, status="running")
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        after = json.loads(self._raw_task_path(task_id).read_text(encoding="utf-8"))
        self.assertEqual(after, before)
        self.assertNotIn("archived_at_utc", after)

    def test_archiving_missing_task_returns_404(self) -> None:
        response = self.client.post("/tasks/not-a-real-task/archive")
        self.assertEqual(response.status_code, 404, response.text)

    def test_archived_task_cannot_start_new_run(self) -> None:
        task = self._create_task()
        task_id = str(task["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        response = self.client.post(f"/tasks/{task_id}/runs")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("归档", response.json()["detail"])

    def test_archiving_preserves_existing_run_directory(self) -> None:
        task = self._create_task()
        task_id = str(task["task_id"])
        run_id = "archive-evidence-run"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "evidence.txt").write_text("preserve me", encoding="utf-8")
        self._write_raw_task(
            task_id,
            status="completed",
            current_run_id=None,
            last_run_id=run_id,
            run_ids=[run_id],
        )
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(run_dir.is_dir())
        self.assertEqual((run_dir / "evidence.txt").read_text(encoding="utf-8"), "preserve me")


if __name__ == "__main__":
    unittest.main()
