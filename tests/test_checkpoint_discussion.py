"""Conversation handoff tests; fake transport proves protocol, not live AI quality."""
from copy import deepcopy
from unittest.mock import patch
import unittest

import test_multi_agent_runtime as fixtures
from model_harness.agent_bridge import AgentRuntimeError
from model_harness.multi_agent import (
    DshMultiAgentRuntime, HumanCheckpointConflictError, ComposerRequestConflictError,
)
from model_harness.io_utils import read_json
from model_harness.conversation_actions import classify_conversation_actions
from model_harness.conversation_payloads import project_conversation_objects
from test_conversation_actions import tool_call, tool_result, PROJECTOR_REVISION


class CheckpointDiscussionTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown
    def _waiting(self, kind="question"):
        session = self.runtime.prompt(self.task_id, "ASR", "准备数据")
        self.events.pending[session] = [{
            "rpc_id": "waiting-1", "kind": kind, "approval_id": "approval-1",
            "received_at": 1, "questions": [{"id": "data_upload", "question": "上传数据"}],
        }]
        return session

    def _discuss(self, message="我还没有数据，怎么办？", rpc="waiting-1"):
        return self.runtime.submit_message(
            self.task_id, "ASR", message, request_id="discuss-1", checkpoint_rpc_id=rpc,
        )

    def test_discussion_preserves_task_and_session_without_answer_or_approval(self):
        for kind in ("question", "approval"):
            with self.subTest(kind=kind):
                self.tearDown()
                self.setUp()
                try:
                    session = self._waiting(kind)
                    previous = self.runtime.store.load_team(self.task_id)["runs"][-1]["run_id"]
                    task = deepcopy(self.task)
                    cancelled_workers = []
                    self.runtime.background_actions_canceller = lambda *args: cancelled_workers.append(args)
                    result = self._discuss()
                    self.assertEqual(result["session_id"], session)
                    self.assertEqual(result["checkpoint_discussion"]["outcome"], "superseded_for_discussion")
                    self.assertEqual(read_json(self.task_dir / "task.json"), task)
                    self.assertEqual(self.client.responses, [])
                    self.assertEqual(cancelled_workers, [])
                    self.assertEqual(self.events.pending_for(session), [])
                    team = self.runtime.store.load_team(self.task_id)
                    self.assertEqual(len(team["runs"]), 2)
                    self.assertEqual(team["runs"][0]["status"], "cancelled")
                    self.assertNotEqual(previous, team["runs"][1]["run_id"])
                    resolved = [e for e in self.runtime.store.list_events(self.task_id)
                                if e.get("payload", {}).get("phase") == "resolved"]
                    self.assertEqual(resolved[-1]["agent_run_id"], previous)
                    with self.assertRaises(HumanCheckpointConflictError):
                        self.runtime.answer_approval(self.task_id, "waiting-1", "allowed-once")
                    last_prompt = [p for method, p in self.client.calls if method == "session.prompt"][-1]
                    self.assertIn("CHECKPOINT_DISCUSSION", last_prompt["content"][0]["text"])
                    self.assertIn("未批准、未回答", last_prompt["content"][0]["text"])
                finally:
                    self.tearDown()

    def test_discussion_replay_survives_runtime_reload_without_recancelling(self):
        self._waiting()
        result = self._discuss()
        self.runtime = DshMultiAgentRuntime(workspace_root=self.root, client=self.client,
                                           events=self.events, cwd=self.root)
        calls = len(self.client.calls)
        replay = self._discuss()
        self.assertEqual(replay["agent_run_id"], result["agent_run_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(any(method in {"session.cancel", "session.prompt"}
                             for method, _ in self.client.calls[calls:]))
        with self.assertRaises(ComposerRequestConflictError):
            self._discuss("换一个目标")
        with self.assertRaises(ComposerRequestConflictError):
            self._discuss(rpc="another-checkpoint")

    def test_stale_checkpoint_never_cancels_or_sends(self):
        self._waiting()
        calls = len(self.client.calls)
        with self.assertRaises(HumanCheckpointConflictError):
            self._discuss(rpc="stale")
        self.assertFalse(any(method in {"session.cancel", "session.prompt"}
                             for method, _ in self.client.calls[calls:]))
        self.assertEqual(len(self.runtime.store.load_team(self.task_id)["runs"]), 1)

    def test_failed_cancellation_keeps_pending_and_does_not_accept_message(self):
        session = self._waiting("approval")
        self.client.fail_methods.add("session.cancel")
        with self.assertRaises(AgentRuntimeError):
            self._discuss()
        self.assertTrue(self.events.pending_for(session))
        self.assertEqual(self.client.responses, [])
        self.assertEqual(len(self.runtime.store.load_team(self.task_id)["runs"]), 1)

    def test_unobserved_cancellation_fails_closed(self):
        session = self._waiting()
        call = self.client.call
        def still_busy(method, payload):
            if method == "session.cancel":
                return {}
            return call(method, payload)
        self.client.call = still_busy
        with patch("model_harness.multi_agent.monotonic", side_effect=[0, 3]):
            with self.assertRaises(HumanCheckpointConflictError):
                self._discuss()
        self.assertTrue(self.events.pending_for(session))
        self.assertEqual(len(self.runtime.store.load_team(self.task_id)["runs"]), 1)

    def test_suspended_action_requires_exact_resolution_identity(self):
        call = tool_call()
        resolved = {**call, "source": "dsh_pending", "event_type": "approval", "type": "approval",
                    "payload": {"phase": "resolved", "outcome": "superseded_for_discussion"}}
        def classify(evidence):
            return classify_conversation_actions(task_id="task-1", projector_revision=PROJECTOR_REVISION,
                                                 events=[call, evidence])[0]
        suspended = classify(resolved)
        self.assertEqual(suspended.status, "cancelled")
        self.assertEqual(suspended.error.code, "checkpoint_suspended")
        self.assertEqual(suspended.object_refs, ())
        self.assertIsNone(suspended.result_event_id)
        for key in ("task_id", "agent_run_id", "session_id", "turn_id", "call_id"):
            with self.subTest(key=key):
                self.assertEqual(classify({**resolved, key: "other"}).status, "running")
        aborted = classify_conversation_actions(task_id="task-1", projector_revision=PROJECTOR_REVISION,
            events=[call, tool_result(is_error=True), resolved])[0]
        self.assertEqual(aborted.status, "cancelled")
        self.assertIsNotNone(aborted.result_event_id)
        succeeded = classify_conversation_actions(task_id="task-1", projector_revision=PROJECTOR_REVISION,
            events=[call, tool_result(), resolved])[0]
        self.assertEqual(succeeded.status, "completed")

    def test_only_explicit_discussion_cancellation_is_a_resolved_historical_risk(self):
        projection = project_conversation_objects(task_id="task-1", actions=[], background_actions=[],
            pending=[], agent_response_running=False, agent_runs=[
                {"run_id": "old", "status": "cancelled", "discussion_handoff": {"rpc_id": "rpc-1", "outcome": "superseded_for_discussion"}},
                {"run_id": "failed", "status": "failed", "error": "real failure"},
                {"run_id": "new", "status": "observed"},
            ])
        self.assertFalse(projection["risks"][0]["active"])
        self.assertEqual(projection["risks"][0]["resolution"]["kind"], "checkpoint_discussion")
        self.assertTrue(projection["risks"][1]["active"])

    def test_queued_messages_are_not_discarded_by_discussion(self):
        session = self._waiting()
        self.runtime.submit_message(self.task_id, "ASR", "已经排队的要求", request_id="queued-1")
        with self.assertRaises(HumanCheckpointConflictError):
            self._discuss()
        self.assertTrue(self.events.pending_for(session))
        self.assertFalse(any(method == "session.cancel" for method, _ in self.client.calls))
