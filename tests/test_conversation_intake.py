from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional server extra
    TestClient = None  # type: ignore[assignment]

from model_harness.data_adapters import DataAdapterRegistry
from model_harness.multi_agent import DshMultiAgentRuntime
from model_harness.plugins import PluginRegistry
from model_harness.server import create_app
from model_harness.service import RunService
from model_harness.workspace import ConversationConflictError, TrainingWorkspace


class FakeDshClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}

    def available(self) -> bool:
        return True

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        self.calls.append((method, deepcopy(payload)))
        if method == "llm.providers":
            return {"providers": [{"provider": "deepseek-official", "active": True}]}
        if method == "credentials.describe":
            return {
                "credentials": {
                    "DEEPSEEK_API_KEY": {"configured": True, "source": "env"}
                }
            }
        if method == "session.create":
            session_id = f"dsh-{len(self.sessions) + 1}"
            self.sessions[session_id] = {"running": False, "events": []}
            return {"sessionId": session_id}
        if method == "session.rename":
            return {}
        if method == "session.prompt":
            self.sessions[payload["sessionId"]]["running"] = True
            return {}
        if method == "session.history":
            return {"events": deepcopy(self.sessions[payload["sessionId"]]["events"])}
        if method == "session.list":
            return {
                "items": [
                    {"sessionId": key, "running": value["running"]}
                    for key, value in self.sessions.items()
                ]
            }
        if method == "session.cancel":
            self.sessions[payload["sessionId"]]["running"] = False
            return {}
        raise AssertionError(f"unexpected method: {method}")

    def respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        del rpc_id, value

    def close(self) -> None:
        return None


class FakeEventHub:
    def bind_workspace(self, root: Path) -> None:
        self.root = root

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def stream_health(self) -> dict[str, Any]:
        return {
            "connected_at": "2026-09-04T00:00:00+00:00",
            "last_event_at": "2026-09-04T00:00:00+00:00",
            "last_error_at": None,
            "consecutive_failures": 0,
            "recovered_at": None,
            "status": "healthy",
        }

    def pending_for(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        return []


class ConversationWorkspaceTests(unittest.TestCase):
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

    def test_unbound_conversation_is_not_a_training_task(self) -> None:
        conversation_id = "task-11111111111111111111111111111111"
        conversation, created = self.workspace.create_conversation(
            conversation_id=conversation_id,
            create_request_id="create-greeting-1",
            title="新对话",
        )

        self.assertTrue(created)
        self.assertEqual(conversation["status"], "unbound")
        self.assertIsNone(conversation["task_id"])
        self.assertEqual(self.workspace.list_tasks(), [])
        self.assertFalse((self.workspace.tasks_dir / conversation_id / "task.json").exists())
        self.assertFalse(
            (self.workspace.tasks_dir / conversation_id / "spec_revisions").exists()
        )

    def test_runtime_session_stays_owned_by_conversation_after_promotion(self) -> None:
        conversation_id = "task-22222222222222222222222222222222"
        self.workspace.create_conversation(
            conversation_id=conversation_id,
            create_request_id="create-clear-goal-1",
        )
        client = FakeDshClient()
        runtime = DshMultiAgentRuntime(
            workspace_root=self.workspace.root,
            client=client,
            events=FakeEventHub(),
            cwd=self.workspace.root,
        )
        submission = runtime.submit_message(
            conversation_id,
            "新对话",
            "我想根据每套房的面积和房龄预测价格",
            request_id="message-clear-goal-1",
        )
        session_id = submission["session_id"]
        conversation_team = (
            self.workspace.conversations_dir
            / conversation_id
            / "agent_team"
            / "team.json"
        )
        self.assertTrue(conversation_team.is_file())

        task, replayed = self.workspace.promote_conversation(
            conversation_id,
            request_id="promote-call-1",
            name="房价预测",
            business_goal="根据每套房的面积和房龄预测价格",
            capability_request={"family": "tabular_regression"},
        )

        self.assertFalse(replayed)
        self.assertEqual(task["task_id"], conversation_id)
        self.assertEqual(
            self.workspace.get_conversation(conversation_id)["status"], "bound"
        )
        self.assertEqual(runtime.session_for(conversation_id), session_id)
        self.assertEqual(len(self.workspace.list_tasks()), 1)
        self.assertFalse(
            (self.workspace.tasks_dir / conversation_id / "agent_team").exists()
        )

        same_task, replayed = self.workspace.promote_conversation(
            conversation_id,
            request_id="promote-call-1",
            name="房价预测",
            business_goal="根据每套房的面积和房龄预测价格",
            capability_request={"family": "tabular_regression"},
        )
        self.assertTrue(replayed)
        self.assertEqual(same_task["task_id"], task["task_id"])
        with self.assertRaises(ConversationConflictError):
            self.workspace.promote_conversation(
                conversation_id,
                request_id="promote-call-2",
                name="另一个任务",
                business_goal="识别合同图片",
            )

    def test_unbound_conversation_skips_task_background_observation_and_cancel(self) -> None:
        conversation_id = "task-33333333333333333333333333333333"
        self.workspace.create_conversation(
            conversation_id=conversation_id,
            create_request_id="create-greeting-3",
        )
        provider_calls: list[str] = []
        cancel_calls: list[str] = []

        def task_actions(owner_id: str) -> list[dict[str, Any]]:
            provider_calls.append(owner_id)
            raise FileNotFoundError("must not query task actions for intake")

        def cancel_task_actions(
            owner_id: str, cancellation: dict[str, Any]
        ) -> list[dict[str, Any]]:
            del cancellation
            cancel_calls.append(owner_id)
            raise FileNotFoundError("must not cancel task actions for intake")

        client = FakeDshClient()
        runtime = DshMultiAgentRuntime(
            workspace_root=self.workspace.root,
            client=client,
            events=FakeEventHub(),
            cwd=self.workspace.root,
            background_actions_provider=task_actions,
            background_actions_canceller=cancel_task_actions,
        )
        runtime.submit_message(
            conversation_id,
            "新对话",
            "您好",
            request_id="message-greeting-3",
        )

        projected = runtime.conversation(conversation_id)
        self.assertEqual(projected["background_actions"], [])
        self.assertNotIn(
            "background-actions:observation-error",
            {item.get("action_id") for item in projected.get("actions", [])},
        )
        self.assertEqual(provider_calls, [])

        cancelled = runtime.cancel(
            conversation_id,
            reason="停止当前回复",
            scope="conversation_turn",
        )
        self.assertEqual(cancel_calls, [])
        self.assertEqual(cancelled["background_actions"], [])


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ConversationHttpTests(unittest.TestCase):
    def test_atomic_first_message_creates_only_conversation_until_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            runtime = app.state.conversation_runtime
            submission = {
                "accepted": True,
                "session_id": "session-intake",
                "request_id": "message-intake-1",
                "composer_mode": "queue_after_turn",
                "agent_run_id": "agent-run-intake",
                "agent_turn_id": "agent-turn-intake",
                "status": "queued",
                "idempotent_replay": False,
            }
            payload = {
                "create_request_id": "create-intake-1",
                "message_request_id": "message-intake-1",
                "initial_message": "您好",
            }
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                patch.object(runtime, "submit_message", return_value=submission),
                TestClient(app) as client,  # type: ignore[misc]
            ):
                created = client.post("/conversations", json=payload)
                self.assertEqual(created.status_code, 201, created.text)
                body = created.json()
                conversation_id = body["conversation"]["conversation_id"]
                self.assertEqual(body["conversation"]["status"], "unbound")
                self.assertIsNone(body["conversation"]["task_id"])
                self.assertEqual(client.get("/tasks").json()["tasks"], [])

                promoted = client.post(
                    f"/conversations/{conversation_id}/promote",
                    json={
                        "request_id": "conversation-promote-call-1",
                        "name": "房价预测",
                        "business_goal": "根据每套房的面积和房龄预测价格",
                        "capability_request": {"family": "tabular_regression"},
                    },
                )
                self.assertEqual(promoted.status_code, 200, promoted.text)
                self.assertEqual(promoted.json()["conversation"]["status"], "bound")
                self.assertEqual(len(client.get("/tasks").json()["tasks"]), 1)

                replay = client.post(
                    f"/conversations/{conversation_id}/promote",
                    json={
                        "request_id": "conversation-promote-call-1",
                        "name": "房价预测",
                        "business_goal": "根据每套房的面积和房龄预测价格",
                        "capability_request": {"family": "tabular_regression"},
                    },
                )
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertTrue(replay.json()["idempotent_replay"])


if __name__ == "__main__":
    unittest.main()
