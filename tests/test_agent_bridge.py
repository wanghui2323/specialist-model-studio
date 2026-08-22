from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.agent_bridge import (
    AgentRuntimeError,
    ConversationBridge,
    DshEventHub,
)
from model_harness.io_utils import read_json, write_json
from model_harness.runner import execute_run, prepare_run
from model_harness.server import create_app
from model_harness.state import RunState
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE


class FakeDshClient:
    def __init__(self, fail_methods: set[str] | None = None) -> None:
        self.fail_methods = set(fail_methods or ())
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        self.calls.append((method, dict(payload)))
        if method in self.fail_methods:
            raise AgentRuntimeError(f"offline during {method}")
        if method == "session.create":
            session_id = f"session-{len(self.sessions) + 1}"
            self.sessions[session_id] = {"running": False, "events": []}
            return {"sessionId": session_id}
        if method == "session.rename":
            self.sessions[payload["sessionId"]]["title"] = payload["title"]
            return {}
        if method == "session.prompt":
            self.sessions[payload["sessionId"]]["running"] = True
            return {}
        if method == "session.cancel":
            self.sessions[payload["sessionId"]]["running"] = False
            return {}
        if method == "session.history":
            return {"events": list(self.sessions[payload["sessionId"]]["events"])}
        if method == "session.list":
            return {
                "items": [
                    {"sessionId": session_id, "running": details["running"]}
                    for session_id, details in self.sessions.items()
                ]
            }
        raise AssertionError(f"unexpected fake DSH method: {method}")

    def respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        self.responses.append((rpc_id, value))


def build_bridge(
    root: Path,
    client: FakeDshClient,
) -> tuple[ConversationBridge, DshEventHub]:
    events = DshEventHub(client)  # type: ignore[arg-type]
    bridge = ConversationBridge(  # type: ignore[arg-type]
        root,
        client,
        events,
        root,
    )
    return bridge, events


def runtime_event(rpc_id: str, payload: dict[str, Any]) -> str:
    return json.dumps({"rpcId": rpc_id, "payload": payload})


def attach_queued_run(app: Any, task_id: str, run_id: str) -> Path:
    contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
    contract["task_id"] = task_id
    run_dir = prepare_run(
        contract,
        app.state.run_service.runs_dir,
        run_id=run_id,
        registry=app.state.run_service.registry,
    )
    workspace = app.state.training_workspace
    task_path = workspace.root / "tasks" / task_id / "task.json"
    task = read_json(task_path)
    task["current_run_id"] = run_id
    task["run_ids"] = [*task.get("run_ids", []), run_id]
    task["status"] = "running"
    write_json(task_path, task)
    return run_dir


class AgentBridgeTests(unittest.TestCase):
    def test_pending_approval_and_question_survive_restart_until_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = FakeDshClient()
            bridge, events = build_bridge(root, client)
            session_id = bridge.ensure_session("task-a", "Task A")

            events._consume(  # noqa: SLF001 - runtime envelope is the unit under test
                runtime_event(
                    "rpc-approval",
                    {
                        "type": "approval/requested",
                        "sessionId": session_id,
                        "approvalId": "approval-1",
                        "toolName": "model_harness_start_task_run",
                        "reason": "start the frozen run",
                    },
                )
            )
            events._consume(  # noqa: SLF001 - runtime envelope is the unit under test
                runtime_event(
                    "rpc-question",
                    {
                        "type": "question/requested",
                        "sessionId": session_id,
                        "questions": [
                            {"id": "metric", "question": "Which metric?"}
                        ],
                    },
                )
            )

            stored = read_json(root / DshEventHub.PENDING_STATE_FILENAME)
            self.assertEqual(stored["schema_version"], "0.1")
            self.assertEqual(
                set(stored["sessions"][session_id]),
                {"rpc-approval", "rpc-question"},
            )

            restarted, restarted_events = build_bridge(root, client)
            conversation = restarted.conversation("task-a")
            self.assertEqual(conversation["session_id"], session_id)
            self.assertEqual(
                {item["kind"] for item in conversation["pending"]},
                {"approval", "question"},
            )

            restarted.answer_approval("task-a", "rpc-approval", "allowed-once")
            restarted.answer_question(
                "task-a",
                "rpc-question",
                [{"id": "metric", "selected": ["macro_f1"]}],
            )
            self.assertEqual(restarted_events.pending_for(session_id), [])

            final_bridge, final_events = build_bridge(root, client)
            self.assertEqual(final_bridge.session_for("task-a"), session_id)
            self.assertEqual(final_events.pending_for(session_id), [])
            self.assertEqual(
                read_json(root / DshEventHub.PENDING_STATE_FILENAME)["sessions"],
                {},
            )

    def test_task_session_mapping_is_reused_and_isolated_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = FakeDshClient()
            bridge, _events = build_bridge(root, client)

            task_a_session = bridge.ensure_session("task-a", "Task A")
            self.assertEqual(
                bridge.ensure_session("task-a", "Task A renamed"),
                task_a_session,
            )
            task_b_session = bridge.ensure_session("task-b", "Task B")
            self.assertNotEqual(task_a_session, task_b_session)
            self.assertEqual(
                [method for method, _payload in client.calls].count("session.create"),
                2,
            )

            restarted, _restarted_events = build_bridge(root, client)
            self.assertEqual(
                restarted.ensure_session("task-a", "Task A after restart"),
                task_a_session,
            )
            self.assertEqual(restarted.session_for("task-b"), task_b_session)
            self.assertEqual(
                [method for method, _payload in client.calls].count("session.create"),
                2,
            )

    def test_offline_session_creation_does_not_mutate_task_or_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_path = root / "tasks" / "task-a" / "task.json"
            run_path = root / "runs" / "run-a" / "run_state.json"
            write_json(task_path, {"task_id": "task-a", "status": "ready"})
            write_json(run_path, {"run_id": "run-a", "status": "queued"})
            task_before = task_path.read_bytes()
            run_before = run_path.read_bytes()
            client = FakeDshClient(fail_methods={"session.create"})
            bridge, events = build_bridge(root, client)

            with self.assertRaisesRegex(AgentRuntimeError, "offline"):
                bridge.prompt("task-a", "Task A", "start")

            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(run_path.read_bytes(), run_before)
            self.assertFalse((root / "conversations.json").exists())
            self.assertEqual(events.pending_for("missing-session"), [])
            self.assertFalse((root / DshEventHub.PENDING_STATE_FILENAME).exists())

            prompt_client = FakeDshClient(fail_methods={"session.prompt"})
            prompt_bridge, _prompt_events = build_bridge(root, prompt_client)
            with self.assertRaisesRegex(AgentRuntimeError, "offline"):
                prompt_bridge.prompt("task-a", "Task A", "start")
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(run_path.read_bytes(), run_before)
            self.assertEqual(
                prompt_bridge.session_for("task-a"),
                "session-1",
            )

    def test_cancel_calls_only_session_cancel_and_preserves_task_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = FakeDshClient()
            bridge, events = build_bridge(root, client)
            session_id = bridge.ensure_session("task-a", "Task A")
            events._consume(  # noqa: SLF001 - runtime envelope is the unit under test
                runtime_event(
                    "rpc-approval",
                    {
                        "type": "approval/requested",
                        "sessionId": session_id,
                        "approvalId": "approval-1",
                        "toolName": "model_harness_start_task_run",
                    },
                )
            )
            task_path = root / "tasks" / "task-a" / "task.json"
            run_path = root / "runs" / "run-a" / "run_state.json"
            write_json(task_path, {"task_id": "task-a", "status": "running"})
            write_json(run_path, {"run_id": "run-a", "status": "training"})
            task_before = task_path.read_bytes()
            run_before = run_path.read_bytes()
            mapping_before = (root / "conversations.json").read_bytes()
            pending_before = (root / DshEventHub.PENDING_STATE_FILENAME).read_bytes()
            client.calls.clear()

            bridge.cancel("task-a")

            self.assertEqual(
                client.calls,
                [("session.cancel", {"sessionId": session_id})],
            )
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(run_path.read_bytes(), run_before)
            self.assertEqual((root / "conversations.json").read_bytes(), mapping_before)
            self.assertEqual(
                (root / DshEventHub.PENDING_STATE_FILENAME).read_bytes(),
                pending_before,
            )

            client.calls.clear()
            with self.assertRaisesRegex(AgentRuntimeError, "还没有启动"):
                bridge.cancel("task-without-session")
            self.assertEqual(client.calls, [])

    @unittest.skipIf(TestClient is None, "server extra is not installed")
    def test_task_owned_run_cancel_rejects_cross_task_and_preserves_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            workspace = app.state.training_workspace
            task_a = workspace.create_task(
                "Task A",
                "Run a local digit reference model for task A",
                recipe_id="digit-classification",
            )
            task_b = workspace.create_task(
                "Task B",
                "Run a local digit reference model for task B",
                recipe_id="digit-classification",
            )
            run_a = attach_queued_run(app, task_a["task_id"], "run-a")
            attach_queued_run(app, task_b["task_id"], "run-b")

            agent_client = FakeDshClient()
            agent_bridge, _agent_events = build_bridge(workspace.root, agent_client)
            agent_bridge.ensure_session(task_a["task_id"], "Task A")
            mapping_before = (workspace.root / "conversations.json").read_bytes()
            sessions_before = deepcopy(agent_client.sessions)
            conversation_before = agent_bridge.conversation(task_a["task_id"])
            run_b_state_path = app.state.run_service.runs_dir / "run-b" / "run_state.json"
            run_b_before = run_b_state_path.read_bytes()

            with TestClient(app) as client:  # type: ignore[misc]
                rejected = client.post(
                    f"/tasks/{task_a['task_id']}/runs/run-b/cancel"
                )
                self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertIn("不属于当前训练任务", rejected.json()["detail"])
                self.assertEqual(run_b_state_path.read_bytes(), run_b_before)

                accepted = client.post(
                    f"/tasks/{task_a['task_id']}/runs/run-a/cancel"
                )
                self.assertEqual(accepted.status_code, 200, accepted.text)
                self.assertTrue(accepted.json()["cancel_requested"])
                self.assertEqual(accepted.json()["run"]["task_id"], task_a["task_id"])
                self.assertTrue(
                    app.state.run_service.status("run-a")["cancel_requested"]
                )

                self.assertEqual(
                    (workspace.root / "conversations.json").read_bytes(),
                    mapping_before,
                )
                self.assertEqual(agent_client.sessions, sessions_before)
                self.assertEqual(
                    agent_bridge.conversation(task_a["task_id"]),
                    conversation_before,
                )

                execute_run(run_a, registry=app.state.run_service.registry)
                reopened = client.get(f"/tasks/{task_a['task_id']}")
                self.assertEqual(reopened.status_code, 200, reopened.text)
                self.assertEqual(reopened.json()["task"]["status"], "cancelled")
                self.assertEqual(
                    reopened.json()["task"]["current_result"]["status"],
                    "cancelled",
                )
                self.assertFalse(
                    app.state.run_service.status("run-b")["cancel_requested"]
                )
                RunState.load(app.state.run_service.runs_dir / "run-b").interrupt(
                    "service restart"
                )
                reopened_b = client.get(f"/tasks/{task_b['task_id']}")
                self.assertEqual(reopened_b.status_code, 200, reopened_b.text)
                self.assertEqual(reopened_b.json()["task"]["status"], "interrupted")
                self.assertEqual(
                    reopened_b.json()["task"]["current_result"]["status"],
                    "interrupted",
                )


if __name__ == "__main__":
    unittest.main()
