from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.multi_agent import TaskArchivedError
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import request_task_run_authorization
from tests.test_multi_agent_runtime import FakeDshClient, FakeEventHub, dsh_event


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

    def _fake_agent_runtime(self):
        runtime = self.app.state.conversation_runtime
        runtime.client = FakeDshClient()
        runtime.events = FakeEventHub()
        return runtime

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

    def test_active_agent_blocks_archive_even_when_training_task_is_not_running(self):
        task = self._create_task()
        task_id = str(task["task_id"])
        runtime = self._fake_agent_runtime()
        runtime.submit_message(task_id, "审查", "开始分析")
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("先停止", response.json()["detail"])
        self.assertNotIn("archived_at_utc", json.loads(self._raw_task_path(task_id).read_text()))

    def test_live_question_blocks_but_terminal_stale_question_does_not(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        submitted = runtime.submit_message(task_id, "审查", "等待输入")
        session_id = submitted["session_id"]
        runtime.events.pending[session_id] = [{
            "rpc_id": "question-rpc", "kind": "question", "received_at": 1,
            "questions": [{"id": "q", "question": "继续吗？", "options": []}],
        }]
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        runtime.client.sessions[session_id]["running"] = False
        runtime.client.sessions[session_id]["events"] = [
            dsh_event(1, "user/message", {"source": {"kind": "user"}, "content": [{"type": "text", "text": f"AGENT_RUN_ID: {runtime.store.load_team(task_id)['runs'][-1]['run_id']}\nUSER_MESSAGE:\n等待输入"}]}),
            dsh_event(2, "tool/call", {"callId": "question-call", "name": "ask_user_question", "input": {"questions": runtime.events.pending[session_id][0]["questions"]}}),
            dsh_event(3, "turn/end", {"turn": 1, "reason": {"kind": "interrupted"}}),
        ]
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn((session_id, "question-rpc"), runtime.events.resolved)

    def test_current_canonical_terminal_ignores_historical_running_rows(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        runtime.ensure_team(task_id, "历史审查")
        snapshot = {
            "task_id": task_id,
            "interaction_projection": {"schema_version": "1.0", "phase": "stopped", "background": {"running": False}},
            "projection_health": "healthy", "background_actions": [],
            "runs": [{"run_id": "historical", "status": "running"}],
            "pending": [{"rpc_id": "historical", "kind": "question"}],
        }
        with patch.object(runtime, "_conversation_snapshot", return_value=snapshot):
            response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 200, response.text)

    def test_successfully_ended_turn_does_not_resurrect_its_old_question(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        submitted = runtime.submit_message(task_id, "审查", "等待输入")
        session_id = submitted["session_id"]
        run_id = runtime.store.load_team(task_id)["runs"][-1]["run_id"]
        questions = [{"id": "q", "question": "继续吗？", "options": []}]
        runtime.client.sessions[session_id]["events"] = [
            dsh_event(1, "user/message", {"source": {"kind": "user"}, "content": [{"type": "text", "text": f"AGENT_RUN_ID: {run_id}\nUSER_MESSAGE:\n等待输入"}]}),
            dsh_event(2, "tool/call", {"callId": "old-question", "name": "ask_user_question", "input": {"questions": questions}}),
            dsh_event(3, "question/requested", {"questions": questions}),
            dsh_event(4, "turn/end", {"turn": 1, "reason": {"kind": "completed"}}),
        ]
        runtime.client.sessions[session_id]["running"] = False
        runtime.events.pending[session_id] = [{
            "rpc_id": "old-question-rpc", "kind": "question", "received_at": 1,
            "questions": questions,
        }]
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn((session_id, "old-question-rpc"), runtime.events.resolved)

    def test_stopping_and_unobservable_existing_session_fail_closed(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        runtime.ensure_team(task_id, "审查")
        snapshot = {
            "task_id": task_id, "projection_health": "healthy", "background_actions": [],
            "interaction_projection": {"schema_version": "1.0", "phase": "stopping", "background": {}},
        }
        with patch.object(runtime, "_conversation_snapshot", return_value=snapshot):
            response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("尚未停止", response.json()["detail"])
        runtime.client.is_available = False
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        runtime.client.is_available = True
        original_call = runtime.client.call
        def missing_root(method, payload):
            return {"items": []} if method == "session.list" else original_call(method, payload)
        with patch.object(runtime.client, "call", side_effect=missing_root):
            response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("无法可靠观测", response.json()["detail"])

    def test_archive_prevents_messages_answers_and_approvals_from_restarting_task(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        self.assertEqual(self.client.post(f"/tasks/{task_id}/archive").status_code, 200)
        requests = [
            ("messages", {"message": "继续执行", "request_id": "after-archive"}),
            ("questions/stale-question", {"answers": []}),
            ("approvals/stale-approval", {"outcome": "allowed-once"}),
        ]
        for suffix, payload in requests:
            with self.subTest(suffix=suffix):
                response = self.client.post(f"/tasks/{task_id}/conversation/{suffix}", json=payload)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("归档", response.text)
        self.assertEqual(runtime.client.calls, [])
        self.assertEqual(runtime.client.responses, [])

    def test_native_queue_lag_cannot_make_archive_race_with_a_delayed_prompt(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        submitted = runtime.submit_message(task_id, "审查", "开始分析")
        session_id = submitted["session_id"]
        # DSH accepted the queued prompt but has not yet published running=true
        # or any terminal event. A prior page refresh must not erase that risk.
        runtime.client.sessions[session_id]["running"] = False
        runtime.conversation(task_id)
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("仍可能在排队", response.json()["detail"])
        self.assertNotIn("archived_at_utc", json.loads(self._raw_task_path(task_id).read_text()))
        # An explicit stop that converges can then be archived normally.
        runtime.cancel(task_id)
        response = self.client.post(f"/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 200, response.text)

    def test_archive_commit_and_submit_are_serialized_by_runtime_lock(self):
        task_id = str(self._create_task()["task_id"])
        runtime = self._fake_agent_runtime()
        entered, release, attempting = Event(), Event(), Event()
        def delayed_commit(selected_task_id):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test archive commit was not released")
            return self.app.state.training_workspace.archive_task(selected_task_id)
        def competing_submit():
            attempting.set()
            return runtime.submit_message(task_id, "审查", "并发提交")
        with ThreadPoolExecutor(max_workers=2) as workers:
            archived = workers.submit(runtime.archive_task, task_id, delayed_commit)
            try:
                self.assertTrue(entered.wait(5))
                submitted = workers.submit(competing_submit)
                self.assertTrue(attempting.wait(5))
            finally:
                release.set()
            self.assertTrue(archived.result(timeout=5)["archived_at_utc"])
            with self.assertRaises(TaskArchivedError):
                submitted.result(timeout=5)
        self.assertEqual(runtime.client.calls, [])


if __name__ == "__main__":
    unittest.main()
