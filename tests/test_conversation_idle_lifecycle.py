"""Live refresh reconciliation must not resurrect historical execution."""
from threading import Event, Thread
from unittest.mock import patch
import unittest

import test_multi_agent_runtime as fixtures


class ConversationIdleLifecycleTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown

    def _finished_discussion(self):
        session = self.runtime.prompt(self.task_id, "ASR", "只讨论")
        run = self.runtime.store.load_team(self.task_id)["runs"][-1]
        self.client.sessions[session]["events"] = [
            fixtures.dsh_event(1, "user/message", {"source": {"kind": "user"},
                "content": [{"type": "text", "text": f"AGENT_RUN_ID: {run['run_id']}\nUSER_MESSAGE:\n只讨论"}]}),
            fixtures.dsh_event(2, "assistant/message", {"message": {
                "content": [{"type": "text", "text": "说明，不代表执行完成。"}]}}),
            fixtures.dsh_event(3, "turn/end", {"reason": {"kind": "completed"}}),
        ]
        self.client.sessions[session]["running"] = False
        self.runtime.conversation(self.task_id)
        return session, run["run_id"]

    def test_discovery_pass_does_not_resurrect_finished_run_or_team(self):
        _, run_id = self._finished_discussion()
        before = self.runtime.store.load_team(self.task_id)
        self.assertEqual(before["runs"][-1]["status"], "idle_without_final")
        after = self.runtime._reconcile_team(
            task_id=self.task_id, running=True, reconcile_lifecycle=False)
        self.assertEqual(after["runs"], before["runs"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["runs"][-1]["run_id"], run_id)

    def test_exact_root_stop_repairs_old_running_without_completing_new_run(self):
        session, old_run = self._finished_discussion()
        self.runtime.prompt(self.task_id, "ASR", "继续讨论")
        self.runtime.store.update_run(task_id=self.task_id, run_id=old_run, status="running")
        snapshot = self.runtime.conversation(self.task_id)
        runs = self.runtime.store.load_team(self.task_id)["runs"]
        self.assertEqual(runs[0]["status"], "idle_without_final")
        self.assertTrue(runs[0]["terminal_stop_event_id"])
        self.assertEqual(runs[1]["status"], "running")
        self.assertTrue(snapshot["execution_running"])
        # A stop belonging to the old turn never terminates a queued new turn.
        self.runtime.prompt(self.task_id, "ASR", "排队问题")
        self.runtime.conversation(self.task_id)
        runs = self.runtime.store.load_team(self.task_id)["runs"]
        self.assertEqual(runs[1]["status"], "running")
        self.assertEqual(runs[2]["status"], "running")
        stops = [e for e in self.runtime.store.current_projection_events(self.task_id)
                 if e.get("event_type") == "turn_finished"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["session_id"], session)
        self.assertEqual(stops[0]["agent_run_id"], old_run)
        self.assertEqual(stops[0]["status"], "observed")

    def test_snapshot_serializes_with_submit_lock(self):
        entered, finished = Event(), Event()
        def refresh():
            entered.set()
            self.runtime.conversation(self.task_id)
            finished.set()
        with patch.object(self.runtime, "_conversation_snapshot", return_value={}) as snapshot:
            with self.runtime._lock:
                worker = Thread(target=refresh)
                worker.start()
                self.assertTrue(entered.wait(1))
                self.assertFalse(finished.wait(0.03))
                snapshot.assert_not_called()
            worker.join(2)
            self.assertTrue(finished.is_set())
            snapshot.assert_called_once_with(self.task_id)
