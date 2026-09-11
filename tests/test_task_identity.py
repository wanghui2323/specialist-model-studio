from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional server extra
    TestClient = None  # type: ignore[assignment]

from model_harness.agent_bridge import AgentRuntimeError
from model_harness.data_adapters import DataAdapterRegistry
from model_harness.io_utils import read_json, write_json
from model_harness.plugins import PluginRegistry
from model_harness.server import create_app
from model_harness.service import RunService
from model_harness.workspace import TrainingWorkspace


class TaskIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        registry = PluginRegistry(include_builtins=True)
        registry.discover()
        adapters = DataAdapterRegistry(include_builtins=True)
        adapters.discover()
        self.service = RunService(root / "runs", registry=registry, recover=False)
        self.workspace = TrainingWorkspace(
            root / "workspace",
            self.service,
            data_adapters=adapters,
        )

    def tearDown(self) -> None:
        self.workspace.close()
        self.service.close()
        self.temp_dir.cleanup()

    def _create(self, name: str = "云端体验 CPU 房价回归") -> dict[str, object]:
        return self.workspace.create_task(
            name=name,
            business_goal="根据房屋字段预测价格",
            capability_request={"family": "tabular_regression"},
        )

    def test_new_task_uses_opaque_stable_id_and_keeps_name_as_metadata(self) -> None:
        task = self._create()
        task_id = str(task["task_id"])

        self.assertRegex(task_id, r"^task-[0-9a-f]{32}$")
        self.assertIsNone(re.search(r"云端|CPU|房价|回归", task_id, re.IGNORECASE))
        self.assertEqual(task["name"], "云端体验 CPU 房价回归")

        reopened = self.workspace.get_task(task_id)
        self.assertEqual(reopened["task_id"], task_id)
        self.assertEqual(reopened["name"], task["name"])
        self.assertIn(task_id, {str(item["task_id"]) for item in self.workspace.list_tasks()})

    def test_same_name_is_not_identity_and_name_revision_keeps_id(self) -> None:
        first = self._create()
        second = self._create()
        self.assertNotEqual(first["task_id"], second["task_id"])

        revised = self.workspace.update_task_spec(
            str(first["task_id"]),
            {
                "base_revision": first["current_spec_revision"],
                "name": "房价预测正式任务",
                "user_note": "验证展示名称与对象主键解耦",
            },
        )
        self.assertEqual(revised["task_id"], first["task_id"])
        self.assertEqual(revised["name"], "房价预测正式任务")

    def test_legacy_title_style_id_remains_readable_without_migration(self) -> None:
        created = self._create("历史房价任务")
        source_id = str(created["task_id"])
        legacy_id = "历史房价任务-a1b2c3d4"
        source_dir = self.workspace.tasks_dir / source_id
        legacy_dir = self.workspace.tasks_dir / legacy_id
        shutil.copytree(source_dir, legacy_dir)

        task = read_json(legacy_dir / "task.json")
        task["task_id"] = legacy_id
        task["spec_revision_ids"] = [f"{legacy_id}:spec:r1"]
        write_json(legacy_dir / "task.json", task)
        spec = read_json(legacy_dir / "spec_revisions" / "r1.json")
        spec["task_id"] = legacy_id
        spec["revision_id"] = f"{legacy_id}:spec:r1"
        write_json(legacy_dir / "spec_revisions" / "r1.json", spec)

        reopened = self.workspace.get_task(legacy_id)
        self.assertEqual(reopened["task_id"], legacy_id)
        self.assertEqual(reopened["name"], "历史房价任务")


@unittest.skipIf(TestClient is None, "server extra is not installed")
class TaskIdentityHttpTests(unittest.TestCase):
    def test_conversation_task_creation_is_idempotent_and_submits_first_message_before_hydration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            runtime = app.state.conversation_runtime
            first_submission = {
                "accepted": True,
                "session_id": "session-atomic",
                "request_id": "message-request-atomic",
                "composer_mode": "queue_after_turn",
                "agent_run_id": "agent-run-atomic",
                "agent_turn_id": "agent-turn-atomic",
                "status": "queued",
                "idempotent_replay": False,
            }
            replay_submission = {**first_submission, "idempotent_replay": True}
            payload = {
                "name": "普通话离线转写",
                "business_goal": "把普通话录音转成文字并部署在本地设备",
                "initial_message": "把普通话录音转成文字并部署在本地设备",
                "create_request_id": "create-request-atomic",
                "message_request_id": "message-request-atomic",
            }
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                patch.object(
                    runtime,
                    "submit_message",
                    side_effect=[first_submission, replay_submission],
                ) as submit,
                TestClient(app) as client,  # type: ignore[misc]
            ):
                created = client.post("/tasks", json=payload)
                replayed = client.post("/tasks", json=payload)

            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(replayed.status_code, 200, replayed.text)
            self.assertTrue(created.json()["created"])
            self.assertFalse(replayed.json()["created"])
            task_id = created.json()["task"]["task_id"]
            self.assertEqual(replayed.json()["task"]["task_id"], task_id)
            self.assertRegex(task_id, r"^task-[0-9a-f]{32}$")
            self.assertEqual(submit.call_count, 2)
            self.assertEqual(submit.call_args.args[0], task_id)
            self.assertEqual(submit.call_args.kwargs["request_id"], payload["message_request_id"])
            self.assertTrue(replayed.json()["submission"]["idempotent_replay"])
            self.assertEqual(
                [item["task_id"] for item in app.state.training_workspace.list_tasks()],
                [task_id],
            )

    def test_failed_first_submission_retries_same_task_and_rejects_changed_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            runtime = app.state.conversation_runtime
            payload = {
                "name": "发送恢复验收",
                "business_goal": "先澄清目标",
                "initial_message": "先澄清目标",
                "create_request_id": "create-recovery",
                "message_request_id": "message-recovery",
            }
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                patch.object(runtime, "submit_message", side_effect=[
                    AgentRuntimeError("temporary runtime failure"),
                    {"accepted": True, "status": "queued"},
                ]) as submit,
                TestClient(app) as client,
            ):
                failed = client.post("/tasks", json=payload)
                retried = client.post("/tasks", json=payload)
                conflict = client.post("/tasks", json={**payload, "business_goal": "另一目标"})
                self.assertEqual(failed.status_code, 503, failed.text)
                self.assertEqual(retried.status_code, 200, retried.text)
                self.assertEqual(failed.json()["detail"]["task_id"], retried.json()["task"]["task_id"])
                self.assertEqual(conflict.status_code, 409, conflict.text)
                self.assertEqual(submit.call_count, 2)
                self.assertEqual(len(client.get("/tasks").json()["tasks"]), 1)

    def test_invalid_conversation_request_does_not_create_a_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            runtime = app.state.conversation_runtime
            payload = {
                "name": "非法请求验收", "business_goal": "澄清目标",
                "initial_message": "澄清目标", "create_request_id": "valid-create",
                "message_request_id": "valid-message",
            }
            with patch.object(runtime, "start"), patch.object(runtime, "stop"), TestClient(app) as client:
                for invalid in [
                    {"message_request_id": ""}, {"message_request_id": "../invalid"},
                    {"create_request_id": "../invalid"}, {"initial_message": " "},
                ]:
                    response = client.post("/tasks", json={**payload, **invalid})
                    self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(client.get("/tasks").json()["tasks"], [])

    def test_http_route_uses_opaque_new_id_and_reloads_legacy_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "云端体验 CPU 房价回归",
                        "business_goal": "根据房屋字段预测价格",
                        "capability_request": {"family": "tabular_regression"},
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                source_id = str(task["task_id"])
                self.assertRegex(source_id, r"^task-[0-9a-f]{32}$")

                workspace = app.state.training_workspace
                legacy_id = "云端体验-CPU-房价回归-d4c0e8a3"
                source_dir = workspace.tasks_dir / source_id
                legacy_dir = workspace.tasks_dir / legacy_id
                shutil.copytree(source_dir, legacy_dir)
                legacy_task = read_json(legacy_dir / "task.json")
                legacy_task["task_id"] = legacy_id
                legacy_task["spec_revision_ids"] = [f"{legacy_id}:spec:r1"]
                write_json(legacy_dir / "task.json", legacy_task)
                legacy_spec = read_json(legacy_dir / "spec_revisions" / "r1.json")
                legacy_spec["task_id"] = legacy_id
                legacy_spec["revision_id"] = f"{legacy_id}:spec:r1"
                write_json(legacy_dir / "spec_revisions" / "r1.json", legacy_spec)

                reopened = client.get(f"/tasks/{quote(legacy_id, safe='')}")
                self.assertEqual(reopened.status_code, 200, reopened.text)
                self.assertEqual(reopened.json()["task"]["task_id"], legacy_id)


if __name__ == "__main__":
    unittest.main()
