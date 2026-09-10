import tempfile
import unittest

from fastapi.testclient import TestClient
from model_harness.server import create_app
from test_multi_agent_runtime import FakeDshClient, FakeEventHub


class CheckpointDiscussionApiTests(unittest.TestCase):
    def test_both_message_routes_preserve_identity_and_reject_stale_approval(self):
        for route in ("task", "conversation"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root:
                app = create_app(root)
                runtime = app.state.conversation_runtime
                runtime.client = FakeDshClient()
                runtime.events = FakeEventHub()
                with TestClient(app) as client:
                    if route == "task":
                        owner = client.post("/tasks", json={"name": "房价预测", "business_goal": "从面积估算价格"}).json()["task"]["task_id"]
                        runtime.prompt(owner, "房价预测", "准备训练")
                        base = f"/tasks/{owner}/conversation"
                    else:
                        response = client.post("/conversations", json={"title": "新对话", "initial_message": "你好",
                            "create_request_id": "create-1", "message_request_id": "message-1"})
                        self.assertEqual(response.status_code, 201, response.text)
                        owner = response.json()["conversation"]["conversation_id"]
                        base = f"/conversations/{owner}"
                    session = runtime.session_for(owner)
                    runtime.events.pending[session] = [{"kind": "approval", "rpc_id": "approval-1", "approval_id": "call-1", "received_at": 1}]
                    body = {"message": "先解释风险", "request_id": "discussion-1", "checkpoint_rpc_id": "approval-1"}
                    response = client.post(f"{base}/messages", json=body)
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertEqual(response.json()["session_id"], session)
                    self.assertTrue(response.json()["accepted"])
                    self.assertEqual(runtime.client.responses, [])
                    replay = client.post(f"{base}/messages", json=body)
                    self.assertTrue(replay.json()["idempotent_replay"])
                    stale = client.post(f"{base}/messages", json={**body, "request_id": "discussion-2"})
                    self.assertEqual(stale.status_code, 409, stale.text)
                    self.assertEqual(stale.json()["detail"]["code"], "checkpoint_changed")
                    approval = client.post(f"{base}/approvals/approval-1", json={"outcome": "allowed-once"})
                    self.assertIn(approval.status_code, (404, 409), approval.text)
                    self.assertEqual(runtime.client.responses, [])

    def test_malformed_checkpoint_id_never_reaches_cancellation(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(root)
            runtime = app.state.conversation_runtime
            runtime.client = FakeDshClient()
            runtime.events = FakeEventHub()
            with TestClient(app) as client:
                owner = client.post("/tasks", json={"name": "房价预测", "business_goal": "从面积估算价格"}).json()["task"]["task_id"]
                response = client.post(f"/tasks/{owner}/conversation/messages",
                    json={"message": "为什么", "checkpoint_rpc_id": 42})
                self.assertEqual(response.status_code, 422)
                self.assertFalse(any(method == "session.cancel" for method, _ in runtime.client.calls))
