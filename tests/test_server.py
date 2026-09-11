from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.server import (
    RunsWorkspaceLeaseError,
    _RunsWorkspaceLease,
    create_app,
)
from model_harness.multi_agent import (
    ComposerRequestConflictError,
    ComposerRequestTerminalError,
    ComposerSubmissionError,
    HumanCheckpointAnswerError,
    HumanCheckpointConflictError,
)


def _hold_runs_workspace_lease(
    runs_dir: str,
    ready: object,
    release: object,
) -> None:
    lease = _RunsWorkspaceLease(runs_dir)
    try:
        lease.acquire()
        ready.put(("acquired", None))  # type: ignore[attr-defined]
        release.wait(timeout=10)  # type: ignore[attr-defined]
    except BaseException as exc:  # pragma: no cover - reported to parent process
        ready.put(("error", repr(exc)))  # type: ignore[attr-defined]
    finally:
        lease.release()


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ServerTests(unittest.TestCase):
    def test_agent_runtime_separates_transport_and_provider_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            runtime = app.state.conversation_runtime
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                patch.object(runtime.client, "available", return_value=False),
                TestClient(app) as client,  # type: ignore[misc]
            ):
                response = client.get("/agent/runtime")

            self.assertEqual(response.status_code, 200)
            status = response.json()
            self.assertFalse(status["transport_ready"])
            self.assertFalse(status["ready"])
            self.assertEqual(
                status["provider"],
                {
                    "ready": False,
                    "provider": "deepseek-official",
                    "active": False,
                    "configured": False,
                    "source": None,
                    "reason": "agent_transport_unavailable",
                },
            )
            self.assertNotIn("DEEPSEEK_API_KEY", response.text)

    def test_composer_modes_and_cancellation_metadata_are_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            runtime = app.state.conversation_runtime
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                TestClient(app) as client,  # type: ignore[misc]
            ):
                task_id = client.post(
                    "/tasks",
                    json={"name": "ASR", "business_goal": "普通话转文字"},
                ).json()["task"]["task_id"]
                submission = {
                    "accepted": True,
                    "session_id": "session-1",
                    "request_id": "composer-request-1",
                    "composer_mode": "queue_after_turn",
                    "agent_run_id": "agent-run-1",
                    "agent_turn_id": "agent-turn-1",
                    "status": "queued",
                    "idempotent_replay": False,
                }
                with patch.object(
                    runtime, "submit_message", return_value=submission
                ) as submit:
                    queued = client.post(
                        f"/tasks/{task_id}/conversation/messages",
                        json={
                            "message": "继续检查数据",
                            "mode": "queue_after_turn",
                            "request_id": "composer-request-1",
                        },
                    )
                self.assertEqual(queued.status_code, 202)
                self.assertEqual(queued.json(), submission)
                submit.assert_called_once_with(
                    task_id,
                    "ASR",
                    "继续检查数据",
                    composer_mode="queue_after_turn",
                    request_id="composer-request-1",
                    actor="user",
                )
                with patch.object(
                    runtime,
                    "submit_message",
                    side_effect=ComposerRequestConflictError(
                        "request_id 已绑定到不同 payload"
                    ),
                ):
                    conflict = client.post(
                        f"/tasks/{task_id}/conversation/messages",
                        json={
                            "message": "不同消息",
                            "mode": "queue_after_turn",
                            "request_id": "composer-request-1",
                        },
                    )
                self.assertEqual(conflict.status_code, 409)
                self.assertEqual(
                    conflict.json()["detail"]["code"],
                    "composer_request_conflict",
                )
                with patch.object(
                    runtime,
                    "submit_message",
                    side_effect=ComposerRequestTerminalError(
                        request_id="composer-request-1",
                        status="failed",
                    ),
                ):
                    terminal = client.post(
                        f"/tasks/{task_id}/conversation/messages",
                        json={
                            "message": "继续检查数据",
                            "request_id": "composer-request-1",
                        },
                    )
                self.assertEqual(terminal.status_code, 409)
                self.assertEqual(
                    terminal.json()["detail"],
                    {
                        "code": "composer_request_terminal",
                        "message": terminal.json()["detail"]["message"],
                        "request_id": "composer-request-1",
                        "status": "failed",
                        "new_request_required": True,
                    },
                )
                with patch.object(
                    runtime,
                    "submit_message",
                    side_effect=ComposerSubmissionError(
                        request_id="composer-request-first-failure",
                        status="failed",
                        provider_error="session.prompt unavailable",
                    ),
                ):
                    provider_failure = client.post(
                        f"/tasks/{task_id}/conversation/messages",
                        json={
                            "message": "开始",
                            "request_id": "composer-request-first-failure",
                        },
                    )
                self.assertEqual(provider_failure.status_code, 503)
                self.assertEqual(
                    provider_failure.json()["detail"]["code"],
                    "composer_submission_failed",
                )
                self.assertEqual(
                    provider_failure.json()["detail"]["request_id"],
                    "composer-request-first-failure",
                )
                self.assertTrue(
                    provider_failure.json()["detail"]["new_request_required"]
                )

                for mode in ("intervene_current", "stop_and_replace"):
                    with self.subTest(mode=mode):
                        blocked = client.post(
                            f"/tasks/{task_id}/conversation/messages",
                            json={"message": "改变当前执行", "mode": mode},
                        )
                        self.assertEqual(blocked.status_code, 409)
                        self.assertEqual(
                            blocked.json()["detail"]["code"],
                            "composer_mode_not_available",
                        )

                spoofed = client.post(
                    f"/tasks/{task_id}/conversation/cancel",
                    json={
                        "actor": "system",
                        "kind": "safety_stop",
                        "reason": "disk reserve exhausted",
                    },
                )
                self.assertEqual(spoofed.status_code, 422)
                self.assertEqual(
                    spoofed.json()["detail"]["code"],
                    "cancel_actor_spoofing_rejected",
                )

                cancellation = {
                    "accepted": True,
                    "cancelled_session_ids": ["session-1"],
                    "background_actions": [],
                    "cancellation": {
                        "actor": "user",
                        "kind": "user_requested",
                        "reason": "Please stop this task",
                        "scope": "task_execution",
                    },
                }
                with patch.object(
                    runtime, "cancel", return_value=cancellation
                ) as cancel:
                    stopped = client.post(
                        f"/tasks/{task_id}/conversation/cancel",
                        json={
                            "reason": "Please stop this task",
                        },
                    )
                self.assertEqual(stopped.status_code, 200)
                self.assertEqual(stopped.json(), cancellation)
                cancel.assert_called_once_with(
                    task_id,
                    actor="user",
                    reason="Please stop this task",
                    cancellation_kind="user_requested",
                    scope="task_execution",
                )

    def test_question_answer_endpoint_distinguishes_conflict_and_invalid_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            runtime = app.state.conversation_runtime
            with (
                patch.object(runtime, "start"),
                patch.object(runtime, "stop"),
                TestClient(app) as client,  # type: ignore[misc]
            ):
                task_id = client.post(
                    "/tasks",
                    json={"name": "ASR", "business_goal": "普通话转文字"},
                ).json()["task"]["task_id"]
                endpoint = f"/tasks/{task_id}/conversation/questions/rpc-1"

                malformed = client.post(endpoint, json={"answers": {}})
                self.assertEqual(malformed.status_code, 422)

                with patch.object(
                    runtime,
                    "answer_question",
                    side_effect=HumanCheckpointAnswerError("选项内容非法"),
                ):
                    invalid = client.post(
                        endpoint,
                        json={"answers": [{"id": "runtime", "selected": ["GPU"]}]},
                    )
                self.assertEqual(invalid.status_code, 422)
                self.assertEqual(invalid.json()["detail"], "选项内容非法")

                with patch.object(
                    runtime,
                    "answer_question",
                    side_effect=HumanCheckpointConflictError("checkpoint 已失效"),
                ):
                    stale = client.post(
                        endpoint,
                        json={"answers": [{"id": "runtime", "selected": ["CPU"]}]},
                    )
                self.assertEqual(stale.status_code, 409)
                self.assertEqual(stale.json()["detail"], "checkpoint 已失效")

                with patch.object(runtime, "answer_question") as answer_question:
                    accepted = client.post(
                        endpoint,
                        json={"answers": [{"id": "runtime", "selected": ["CPU"]}]},
                    )
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(accepted.json(), {"accepted": True})
                answer_question.assert_called_once_with(
                    task_id,
                    "rpc-1",
                    [{"id": "runtime", "selected": ["CPU"]}],
                )

    def test_second_app_lifespan_fails_before_starting_dsh_event_hub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            first_app = create_app(runs_dir)
            second_app = create_app(runs_dir)

            with (
                patch.object(first_app.state.conversation_runtime, "start") as first_start,
                patch.object(first_app.state.conversation_runtime, "stop") as first_stop,
                patch.object(second_app.state.conversation_runtime, "start") as second_start,
                patch.object(second_app.state.conversation_runtime, "stop") as second_stop,
            ):
                with TestClient(first_app) as first_client:  # type: ignore[misc]
                    self.assertTrue(first_app.state.runs_workspace_lease.held)
                    first_start.assert_called_once_with()
                    with self.assertRaisesRegex(
                        RunsWorkspaceLeaseError,
                        "runs workspace already has an active writer",
                    ):
                        with TestClient(second_app):  # type: ignore[misc]
                            self.fail("the second app must not finish startup")
                    second_start.assert_not_called()
                    second_stop.assert_not_called()
                    self.assertEqual(first_client.get("/health").status_code, 200)

                first_stop.assert_called_once_with()
                self.assertFalse(first_app.state.runs_workspace_lease.held)

    def test_runs_workspace_lease_is_cross_process_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            release = context.Event()
            process = context.Process(
                target=_hold_runs_workspace_lease,
                args=(str(runs_dir), ready, release),
            )
            process.start()
            try:
                status, detail = ready.get(timeout=10)
                self.assertEqual((status, detail), ("acquired", None))
                competing = _RunsWorkspaceLease(runs_dir)
                with self.assertRaisesRegex(
                    RunsWorkspaceLeaseError,
                    "runs workspace already has an active writer",
                ):
                    competing.acquire()
                self.assertFalse(competing.held)
            finally:
                release.set()
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

            self.assertEqual(process.exitcode, 0)
            after_release = _RunsWorkspaceLease(runs_dir)
            after_release.acquire()
            try:
                self.assertTrue(after_release.held)
            finally:
                after_release.release()
            self.assertFalse(after_release.held)

    def test_health_and_recipe_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir, conversation_url="http://127.0.0.1:3999")
            with TestClient(app) as client:  # type: ignore[misc]
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])
                self.assertEqual(health.json()["version"], "1.0.0-rc.1")
                self.assertEqual(health.json()["package_version"], "1.0.0rc1")
                self.assertEqual(
                    health.json()["feature_track"], "v1.0-conversation-native"
                )
                self.assertEqual(health.json()["release_status"], "unreleased_rc")
                self.assertEqual(health.json()["scope"], "backend")
                self.assertFalse(health.json()["agent_required"])
                self.assertEqual(health.json()["primary_experience"], "conversation")
                self.assertEqual(health.json()["conversation_url"], "/app")

                runtime = client.get("/runtime")
                self.assertEqual(runtime.status_code, 200)
                self.assertEqual(runtime.json()["workbench_url"], "/app")
                self.assertEqual(
                    runtime.json()["feature_track"], "v1.0-conversation-native"
                )
                self.assertEqual(runtime.json()["release_status"], "unreleased_rc")
                self.assertEqual(
                    runtime.json()["source_execution_policy"],
                    "static_analysis_only_without_verified_isolation",
                )
                self.assertFalse(runtime.json()["byom_execution_available"])
                identity = runtime.json()["runtime_identity"]
                self.assertEqual(identity["runs_dir"], str(Path(temp_dir).resolve()))
                self.assertEqual(
                    identity["workspace_dir"],
                    str((Path(temp_dir) / "_workspace").resolve()),
                )
                self.assertEqual(
                    identity["source_root"],
                    str(Path(__file__).resolve().parents[1]),
                )
                self.assertRegex(identity["source_revision"], r"^[0-9a-f]{40}$")
                self.assertIsInstance(identity["source_dirty"], bool)
                self.assertEqual(
                    identity["conversation_origin"],
                    "http://127.0.0.1:3999",
                )
                self.assertEqual(
                    runtime.json()["supported_protocol_end"],
                    "resource_feasibility",
                )
                self.assertTrue(
                    runtime.json()["registered_recipe_training_available"]
                )

                openapi = client.get("/openapi.json")
                self.assertEqual(openapi.status_code, 200)
                self.assertEqual(openapi.json()["info"]["version"], "1.0.0-rc.1")

                root = client.get("/", follow_redirects=False)
                self.assertEqual(root.status_code, 307)
                self.assertEqual(root.headers["location"], "/app")

                recipes = client.get("/recipes")
                self.assertEqual(recipes.status_code, 200)
                self.assertEqual(
                    recipes.json()["recipes"][0]["plugin_id"],
                    "digit-classification",
                )

                families = client.get("/task-spec/families")
                self.assertEqual(families.status_code, 200)
                family_values = {
                    item["family"] for item in families.json()["families"]
                }
                self.assertTrue(
                    {"asr", "speech_synthesis", "segmentation", "custom"}
                    <= family_values
                )

                template = client.get("/recipes/digit-classification/template")
                self.assertEqual(template.status_code, 200)
                self.assertEqual(
                    template.json()["contract"]["recipe"],
                    "digit-classification",
                )

                console = client.get("/app")
                self.assertEqual(console.status_code, 200)
                self.assertIn("Specialist Model Studio · 专业模型智能工作台", console.text)
                self.assertIn("想训练一个什么模型？", console.text)
                self.assertIn("先通过对话把目标说清楚", console.text)
                self.assertIn("可联网查找开源模型", console.text)
                self.assertNotIn("Workspace Write", console.text)

                chat = client.post("/chat", json={"message": "有哪些能力"})
                self.assertEqual(chat.status_code, 410)
                self.assertEqual(
                    chat.json()["detail"],
                    {
                        "code": "chat_endpoint_retired",
                        "message": (
                            "The global chat endpoint has been retired. "
                            "Conversation is owned by one TrainingTask and the "
                            "real multi-agent runtime."
                        ),
                        "canonical_endpoint": (
                            "/tasks/{task_id}/conversation/messages"
                        ),
                    },
                )

    def test_strategy_api_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                response = client.post(
                    "/runs/missing/strategies/add-shift-augmentation/apply",
                    json={},
                )
                self.assertEqual(response.status_code, 409)
                self.assertIn("approval_confirmed=true", response.json()["detail"])

    def test_global_run_creation_and_retired_chat_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={"name": "guarded", "business_goal": "still ambiguous"},
                ).json()["task"]
                template = client.get(
                    "/recipes/digit-classification/template"
                ).json()["contract"]
                template["task_id"] = task["task_id"]

                task_owned_guards = (
                    client.post("/runs", json={"contract": template}),
                    client.post("/runs/missing/cancel", json={}),
                    client.post("/runs/missing/resume", json={}),
                    client.post(
                        "/runs/missing/strategies/add-shift-augmentation/apply",
                        json={"approval_confirmed": True},
                    ),
                )
                self.assertTrue(
                    all(response.status_code == 409 for response in task_owned_guards),
                    [response.text for response in task_owned_guards],
                )
                for message in (
                    "/start",
                    "/cancel",
                    "/apply add-shift-augmentation",
                ):
                    with self.subTest(message=message):
                        retired = client.post("/chat", json={"message": message})
                        self.assertEqual(retired.status_code, 410, retired.text)
                        self.assertEqual(
                            retired.json()["detail"]["canonical_endpoint"],
                            "/tasks/{task_id}/conversation/messages",
                        )
                self.assertEqual(app.state.run_service.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
