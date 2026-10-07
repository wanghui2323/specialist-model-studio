"""Reproduce reverse pre-step callbacks while the outbound RPC scope is held."""
from __future__ import annotations

from copy import deepcopy
from threading import Event, Thread
from unittest.mock import patch
import unittest

from tests import test_multi_agent_runtime as fixtures
from model_harness.io_utils import read_json, write_json


class RootContextLivenessTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown

    def test_raw_owner_business_goal_and_current_spec_notes_enter_the_live_context(self):
        path=self.runtime.store.tasks_dir/self.task_id/'task.json'
        task=read_json(path);task['business_goal']='只整理全店每日销量，不启动训练';task['current_spec_revision']=2;write_json(path,task)
        write_json(path.parent/'spec_revisions/r2.json',{'task_id':self.task_id,'revision':2,'revision_id':self.task_id+':spec:r2','business_goal':task['business_goal'],'user_note':'预算以后确认'})
        snapshot=self.runtime.root_context(self.task_id)
        self.assertEqual(snapshot['canonical_goal']['business_goal'],task['business_goal'])
        self.assertEqual(snapshot['canonical_goal']['user_note'],'预算以后确认')
        self.assertFalse(snapshot['scope']['grants_execution_authorization'])

    def callback_snapshot(self):
        done = Event()
        values, errors = [], []
        def read():
            try:
                values.append(self.runtime.root_context(self.task_id))
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        worker = Thread(target=read, daemon=True)
        worker.start()
        completed = done.wait(0.75)
        if completed:
            worker.join()
        return completed, values, errors, worker

    def test_callback_reads_atomic_facts_without_runtime_store_or_event_reconciliation_locks(self):
        self.runtime.prompt(self.task_id, "目标", "创建原生回合")
        with self.runtime._lock, self.runtime.store._lock, patch.object(self.runtime.store, "load_team", side_effect=AssertionError("callback must not reconcile team events")), patch.object(self.runtime.store, "list_events", side_effect=AssertionError("callback must not scan the event ledger")), patch.object(self.client, "call", side_effect=AssertionError("callback must not call DSH")):
            completed, values, errors, worker = self.callback_snapshot()
        worker.join(1)
        self.assertTrue(completed, "a pre-step callback must not wait for the outbound runtime/store lock")
        self.assertEqual(errors, [])
        self.assertEqual(values[0]["owner"]["owner_id"], self.task_id)
        self.assertFalse(values[0]["control"]["stop_automatic_continuations"])

    def test_prompt_and_stop_can_wait_for_a_reverse_callback_without_deadlocking(self):
        original = self.client.call
        observed = []
        workers = []
        def rpc(method, payload):
            if method in {"session.prompt", "session.cancel"}:
                completed, values, errors, worker = self.callback_snapshot()
                workers.append(worker)
                self.assertTrue(completed, f"{method} waited for a callback blocked by its own RPC scope")
                self.assertFalse(errors)
                observed.append((method, values[0]["control"]["stop_automatic_continuations"]))
            return original(method, payload)
        self.client.call = rpc
        self.runtime.submit_message(self.task_id, "目标", "开始工作", request_id="callback-first")
        self.runtime.cancel(self.task_id)
        self.runtime.submit_message(self.task_id, "目标", "新的用户要求", request_id="callback-resume")
        for worker in workers:
            worker.join(1)
        self.assertEqual(observed, [("session.prompt", False), ("session.cancel", True), ("session.prompt", False)])

    def test_full_history_replay_indexes_the_ledger_once_and_preserves_existing_audit_records(self):
        self.runtime.prompt(self.task_id, "目标", "事件重放")
        events = [{"source": "dsh", "source_key": f"replay-source-{index}", "type": "tool_result", "payload": {"text": "x" * 4096}} for index in range(80)]
        original = self.runtime.store.persist_projection(task_id=self.task_id, events=events)
        event_path = self.runtime.store._events_path(self.task_id)
        before = event_path.read_bytes()
        replay = deepcopy(events)
        replay[0]["payload"] = {"text": "must not overwrite the observed result"}
        with patch.object(self.runtime.store, "list_events", wraps=self.runtime.store.list_events) as scans, patch.object(self.runtime.store, "append_event", wraps=self.runtime.store.append_event) as appends:
            result = self.runtime.store.persist_projection(task_id=self.task_id, events=replay)
        self.assertEqual(result, original)
        self.assertEqual(scans.call_count, 2, "one sequence-recovery read and one source-key index, independent of history length")
        self.assertEqual(appends.call_count, 0)
        self.assertEqual(event_path.read_bytes(), before)
        path = self.runtime.store._team_path(self.task_id)
        team = read_json(path)
        team["event_seq"] = 0  # Simulate crash after event append, before team commit.
        write_json(path, team)
        new_event = {"source": "dsh", "source_key": "next-distinct-event", "type": "tool_result", "payload": {}}
        result = self.runtime.store.persist_projection(task_id=self.task_id, events=[*events, new_event, new_event])
        self.assertEqual(result[-1]["event_id"], result[-2]["event_id"])
        self.assertGreater(result[-1]["seq"], original[-1]["seq"])


if __name__ == "__main__":
    unittest.main()
