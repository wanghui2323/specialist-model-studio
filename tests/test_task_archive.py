from __future__ import annotations

import json
import re
import tempfile
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.agent_bridge import AgentRuntimeError
from model_harness.errors import HarnessError
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import request_task_run_authorization


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

    def _create_ready_task(self) -> dict[str, object]:
        response = self.client.post(
            "/tasks",
            json={
                "name": "待归档房价预测任务",
                "business_goal": "根据面积和卧室数预测房价",
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_kind": "numeric",
                    "target_column": "price",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        task_id = str(response.json()["task"]["task_id"])
        rows = ["area_sqm,bedrooms,price"]
        rows.extend(
            f"{60 + index},{1 + index % 4},{180 + index * 3}"
            for index in range(36)
        )
        uploaded = self.client.post(
            f"/tasks/{task_id}/dataset",
            content=("\n".join(rows) + "\n").encode("utf-8"),
            headers={
                "Content-Type": "text/csv",
                "X-Filename": "houses.csv",
                "X-Target-Column": "price",
            },
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        confirmed = self.client.post(
            f"/tasks/{task_id}/confirm",
            json=contract_confirmation_payload(self.client, task_id),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        return confirmed.json()["task"]

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
        task = self._create_ready_task()
        task_id = str(task["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        response = request_task_run_authorization(
            self.client,
            task_id,
            checkpoint_id="native-run:archived-task",
        )
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

    def test_archive_and_restore_are_idempotent(self) -> None:
        task_id = str(self._create_task()["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        archived_bytes = self._raw_task_path(task_id).read_bytes()
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), archived_bytes)

        response = self.client.post(f"/tasks/{task_id}/restore")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["task"].get("archived_at_utc"))
        restored_bytes = self._raw_task_path(task_id).read_bytes()
        self.assertEqual(self.client.post(f"/tasks/{task_id}/restore").status_code, 200)
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), restored_bytes)
        self.assertIn(task_id, {item["task_id"] for item in self.client.get("/tasks").json()["tasks"]})

    def test_restore_preserves_data_contract_history_and_does_not_run(self) -> None:
        task_id = str(self._create_ready_task()["task_id"])
        runtime = self.app.state.conversation_runtime
        runtime.store.create_team(
            task_id=task_id, root_session_id="session-archive-history",
            title="待归档房价预测任务", agent_preset="model-training",
        )
        run_id = "archive-preserved-result"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir()
        (run_dir / "evidence.txt").write_text("preserved result", encoding="utf-8")
        before_task = self._write_raw_task(task_id, last_run_id=run_id, run_ids=[run_id])
        task_path = self._raw_task_path(task_id)
        preserved_files = {
            path.relative_to(self.runs_dir): path.read_bytes()
            for path in self.runs_dir.rglob("*")
            if path.is_file() and path.resolve() != task_path.resolve()
        }
        idle = {"projection_health": "healthy", "execution_running": False, "pending": [], "runs": []}
        with patch.object(runtime, "conversation", return_value=idle), \
                patch.object(runtime, "submit_message") as submit_message, \
                patch.object(self.app.state.run_service, "submit") as submit_run:
            self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
            reopened = self.client.get(f"/tasks/{task_id}")
            self.assertEqual(reopened.status_code, 200)
            response = self.client.post(f"/tasks/{task_id}/restore")
            self.assertEqual(response.status_code, 200, response.text)
            submit_message.assert_not_called()
            submit_run.assert_not_called()
        after_task = json.loads(task_path.read_text(encoding="utf-8"))
        before_task.pop("updated_at_utc")
        after_task.pop("updated_at_utc")
        self.assertEqual(after_task, before_task)
        after_files = {
            path.relative_to(self.runs_dir): path.read_bytes()
            for path in self.runs_dir.rglob("*") if path.is_file() and path.resolve() != task_path.resolve()
        }
        self.assertEqual(after_files.keys(), preserved_files.keys())
        for path, content in preserved_files.items():
            self.assertEqual(after_files[path], content, str(path))

        # Reload the workspace/service, not just an in-memory API response.
        self.client_context.__exit__(None, None, None)
        self.app = create_app(self.runs_dir)
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()
        reloaded = self.client.get(f"/tasks/{task_id}").json()["task"]
        self.assertEqual(reloaded["task_id"], task_id)
        self.assertTrue(reloaded["contract_confirmed"])
        self.assertEqual(reloaded["dataset_id"], before_task["dataset_id"])
        self.assertEqual(reloaded["run_ids"], [run_id])
        self.assertFalse(reloaded.get("archived_at_utc"))

    def test_restore_missing_or_invalid_identity_does_not_create_directories(self) -> None:
        workspace = self.app.state.training_workspace
        before = set(workspace.tasks_dir.iterdir())
        for action in ("archive", "restore"):
            response = self.client.post(f"/tasks/not-a-real-task/{action}")
            self.assertEqual(response.status_code, 404, response.text)
        for invalid_id in ("", "..", "../other-task", "/tmp/other-task"):
            with self.subTest(task_id=invalid_id), self.assertRaises(HarnessError):
                workspace.restore_task(invalid_id)
        self.assertEqual(set(workspace.tasks_dir.iterdir()), before)

    def test_active_agent_or_pending_checkpoint_prevents_archive(self) -> None:
        task_id = str(self._create_task()["task_id"])
        runtime = self.app.state.conversation_runtime
        before = self._raw_task_path(task_id).read_bytes()
        busy_states = [
            {"execution_running": True},
            {"agent_response_running": True},
            {"runs": [{"status": "queued"}]},
            {"runs": [{"status": "waiting_for_human"}]},
            {"pending": [{"rpc_id": "native-checkpoint", "kind": "approval"}]},
            {"interaction_state": "cancelling"},
        ]
        with patch.object(runtime.store, "load_team", return_value={"task_id": task_id}):
            for fields in busy_states:
                with self.subTest(fields=fields), patch.object(
                    runtime, "conversation", return_value={"projection_health": "healthy", **fields},
                ):
                    response = self.client.post(f"/tasks/{task_id}/archive")
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)

    def test_unknown_agent_observation_fails_closed_without_archive(self) -> None:
        task_id = str(self._create_task()["task_id"])
        runtime = self.app.state.conversation_runtime
        before = self._raw_task_path(task_id).read_bytes()
        with patch.object(runtime.store, "load_team", return_value={"task_id": task_id}):
            for health in ("observation_degraded", None):
                with self.subTest(health=health), patch.object(
                    runtime, "conversation", return_value={"projection_health": health},
                ):
                    self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 409)
            with patch.object(runtime, "conversation", side_effect=AgentRuntimeError("offline")):
                self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 409)
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)

    def test_terminal_domain_status_with_live_worker_prevents_archive(self) -> None:
        task_id = str(self._create_task()["task_id"])
        workspace = self.app.state.training_workspace
        before = self._raw_task_path(task_id).read_bytes()
        future: Future[object] = Future()
        workspace._binding_futures["attempt-archive-test"] = future
        attempt = {"attempt": {"attempt_id": "attempt-archive-test"}, "current_state": {"status": "cancelled"}}
        try:
            with patch.object(workspace, "list_model_binding_attempts", return_value=[attempt]):
                action = workspace.task_background_actions(task_id)[0]
                self.assertTrue(action["worker_running"])
                self.assertEqual(action["status"], "cancel_requested")
                response = self.client.post(f"/tasks/{task_id}/archive")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)
                future.set_result(None)
                # Historical cancellation is not an active worker after it settles.
                self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        finally:
            workspace._binding_futures.pop("attempt-archive-test", None)

    def test_queued_domain_attempt_or_pending_run_prevents_archive(self) -> None:
        task_id = str(self._create_task()["task_id"])
        workspace = self.app.state.training_workspace
        before = self._raw_task_path(task_id).read_bytes()
        with patch.object(workspace, "task_background_actions", return_value=[
            {"action_type": "model_binding_analysis", "status": "queued", "running": True},
        ]):
            self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 409)
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)
        pending = self._write_raw_task(task_id, pending_run={"run_id": "unsettled-intent"})
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 409)
        self.assertEqual(json.loads(self._raw_task_path(task_id).read_text(encoding="utf-8")), pending)

    def test_archived_task_cannot_queue_conversation_work_before_restore(self) -> None:
        task_id = str(self._create_task()["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        with patch.object(self.app.state.conversation_runtime, "submit_message", return_value={"accepted": True}) as submit:
            response = self.client.post(f"/tasks/{task_id}/conversation/messages", json={"message": "继续训练"})
            self.assertEqual(response.status_code, 409, response.text)
            submit.assert_not_called()
            self.assertEqual(self.client.post(f"/tasks/{task_id}/restore").status_code, 200)
            submit.assert_not_called()
            response = self.client.post(f"/tasks/{task_id}/conversation/messages", json={"message": "解释当前状态"})
            self.assertEqual(response.status_code, 202, response.text)
            submit.assert_called_once()

    def test_all_public_task_mutations_fail_closed_while_archived(self) -> None:
        task_id = str(self._create_task()["task_id"])
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        before = self._raw_task_path(task_id).read_bytes()
        guarded_routes = []
        for route in self.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/tasks/{task_id}/") or path.endswith(("/archive", "/restore")):
                continue
            for method in getattr(route, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}:
                target = re.sub(r"\{[^}]+\}", "test-object", path.replace("{task_id}", task_id))
                guarded_routes.append((method, target))
        self.assertGreater(len(guarded_routes), 20)
        for method, path in guarded_routes:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json={})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("归档", response.json()["detail"])
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)
        self.assertEqual(self.client.get(f"/tasks/{task_id}").status_code, 200)

    def test_bound_conversation_alias_cannot_mutate_archived_task(self) -> None:
        workspace = self.app.state.training_workspace
        task_id = f"task-{uuid4().hex}"
        workspace.create_conversation(conversation_id=task_id, create_request_id="archive-alias-create")
        workspace.promote_conversation(
            task_id, request_id="archive-alias-promote", name="房价预测",
            business_goal="根据房屋面积预测价格", capability_request={"family": "tabular_regression"},
        )
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        before = self._raw_task_path(task_id).read_bytes()
        with patch.object(self.app.state.conversation_runtime, "submit_message") as submit:
            for suffix in ("messages", "cancel", "questions/stale-checkpoint", "promote"):
                response = self.client.post(f"/conversations/{task_id}/{suffix}", json={"message": "继续"})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("归档", response.json()["detail"])
            submit.assert_not_called()
        self.assertEqual(self._raw_task_path(task_id).read_bytes(), before)
        self.assertEqual(self.client.get(f"/conversations/{task_id}").status_code, 200)

    def test_in_flight_task_mutation_prevents_archive(self) -> None:
        task_id = str(self._create_task()["task_id"])
        entered, finish = Event(), Event()

        def held_decision(*args: object, **kwargs: object) -> dict[str, object]:
            entered.set()
            if not finish.wait(5):
                raise RuntimeError("test decision was not released")
            return {"decision": "rejected"}

        with patch.object(self.app.state.training_workspace, "decide_training_plan", side_effect=held_decision), \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.client.post, f"/tasks/{task_id}/training-plans/test-plan/decisions", json={})
            try:
                self.assertTrue(entered.wait(5))
                response = self.client.post(f"/tasks/{task_id}/archive")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertNotIn("archived_at_utc", json.loads(self._raw_task_path(task_id).read_text()))
            finally:
                finish.set()
            self.assertEqual(pending.result(timeout=5).status_code, 200)
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)

    def test_archive_admission_prevents_new_task_mutation(self) -> None:
        task_id = str(self._create_task()["task_id"])
        workspace = self.app.state.training_workspace
        archive = workspace.archive_task
        entered, finish = Event(), Event()

        def held_archive(selected_id: str) -> dict[str, object]:
            entered.set()
            if not finish.wait(5):
                raise RuntimeError("test archive was not released")
            return archive(selected_id)

        with patch.object(workspace, "archive_task", side_effect=held_archive), \
                patch.object(workspace, "update_task_spec") as update_spec, \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.client.post, f"/tasks/{task_id}/archive")
            try:
                self.assertTrue(entered.wait(5))
                response = self.client.patch(f"/tasks/{task_id}/spec", json={"business_goal": "改变目标"})
                self.assertEqual(response.status_code, 409, response.text)
                update_spec.assert_not_called()
            finally:
                finish.set()
            self.assertEqual(pending.result(timeout=5).status_code, 200)

    def test_rejected_archive_does_not_interrupt_an_active_agents_tool(self) -> None:
        task_id = str(self._create_task()["task_id"])
        runtime = self.app.state.conversation_runtime
        workspace = self.app.state.training_workspace
        entered, finish = Event(), Event()

        def held_observation(selected_id: str) -> dict[str, object]:
            entered.set()
            if not finish.wait(5):
                raise RuntimeError("test observation was not released")
            return {"projection_health": "healthy", "execution_running": True}

        with patch.object(runtime.store, "load_team", return_value={"task_id": task_id}), \
                patch.object(runtime, "conversation", side_effect=held_observation), \
                patch.object(workspace, "decide_training_plan", return_value={"decision": "rejected"}), \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.client.post, f"/tasks/{task_id}/archive")
            try:
                self.assertTrue(entered.wait(5))
                # An archive that will be rejected must not freeze the active
                # Agent's otherwise valid domain HTTP calls while observing it.
                tool_response = self.client.post(f"/tasks/{task_id}/training-plans/test-plan/decisions", json={})
                self.assertEqual(tool_response.status_code, 200, tool_response.text)
            finally:
                finish.set()
            self.assertEqual(pending.result(timeout=5).status_code, 409)
        self.assertNotIn("archived_at_utc", json.loads(self._raw_task_path(task_id).read_text()))


if __name__ == "__main__":
    unittest.main()
