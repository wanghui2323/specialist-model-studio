"""Use DSH's actual ownership-scoped interrupt protocol, never child session.cancel."""
from __future__ import annotations

import unittest
from copy import deepcopy

from tests import test_multi_agent_runtime as fixtures
from model_harness.agent_bridge import AgentRuntimeError
from model_harness.io_utils import read_json, write_json
from model_harness.multi_agent import MultiAgentRuntimeError


class SubagentCancellationTests(unittest.TestCase):
    setUp = fixtures.DshMultiAgentRuntimeTests.setUp
    tearDown = fixtures.DshMultiAgentRuntimeTests.tearDown

    def child(self, parent, child_id, *, running=True):
        self.client.sessions[child_id] = {"running": running, "events": [], "title": "fixture", "origin": "subagent", "parentSessionId": parent}

    def test_exact_tree_uses_native_subagent_routing_and_cancels_both_backend_worker_types(self):
        root = self.runtime.prompt(self.task_id, "目标", "开始工作")
        self.child(root, "child")
        self.child("child", "grandchild")
        self.client.sessions["foreign-root"] = {"running": True, "events": [], "title": "another task"}
        self.child("foreign-root", "foreign-child")
        team = self.runtime.store.load_team(self.task_id)
        team["agents"]["stale-foreign"] = {"dsh_session_id": "foreign-child", "lineage_verified": True, "lineage_parent_session_id": root, "status": "running"}
        write_json(self.task_dir / "agent_team/team.json", team)
        workers = [
            {"action_id": "qualification:one", "action_type": "qualification", "running": True},
            {"action_id": "training-run:one", "action_type": "training_run", "running": True},
        ]
        calls = []
        self.runtime.background_actions_canceller = lambda owner, cancellation: calls.append((owner, cancellation)) or [{**item, "cancel_requested": True} for item in workers]
        result = self.runtime.cancel(self.task_id, reason="停止当前任务")
        self.assertEqual(result["cancelled_session_ids"], [root, "child", "grandchild"])
        self.assertFalse(result["termination_observed"])
        self.assertTrue(all(item["cancel_requested"] for item in result["background_actions"]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], self.task_id)
        interrupts = [payload for method, payload in self.client.calls if method == "subagent.interrupt"]
        self.assertEqual(interrupts, [
            {"parentSessionId": root, "childSessionId": "child", "mode": "continuable"},
            {"parentSessionId": "child", "childSessionId": "grandchild", "mode": "continuable"},
        ])
        self.assertFalse(any(method == "session.cancel" and payload["sessionId"] in {"child", "grandchild", "foreign-child", "foreign-root"} for method, payload in self.client.calls))
        self.assertTrue(self.client.sessions["foreign-child"]["running"])
        self.assertTrue(self.client.sessions["foreign-root"]["running"])

    def test_acknowledged_child_interrupt_does_not_mean_stopped_until_observed_quiet(self):
        root = self.runtime.prompt(self.task_id, "目标", "开始工作")
        self.child(root, "slow-child")
        original_call = self.client.call
        def delayed_interrupt(method, payload):
            if method == "subagent.interrupt":
                self.client.calls.append((method, deepcopy(payload)))
                return {"accepted": True}
            return original_call(method, payload)
        self.client.call = delayed_interrupt
        self.runtime.cancel(self.task_id)
        self.client.sessions[root]["events"] = [fixtures.dsh_event(10, "turn/end", {"turn": 1, "reason": {"kind": "cancelled"}})]
        while_child_active = self.runtime.conversation(self.task_id)
        self.assertTrue(while_child_active["execution_running"])
        self.assertEqual(while_child_active["runs"][-1]["status"], "cancel_requested")
        self.assertEqual(while_child_active["interaction_projection"]["phase"], "stopping")
        self.client.sessions["slow-child"]["running"] = False
        quiet = self.runtime.conversation(self.task_id)
        self.assertFalse(quiet["execution_running"])
        self.assertEqual(quiet["runs"][-1]["status"], "cancelled")
        self.assertEqual(quiet["interaction_projection"]["phase"], "stopped")

    def test_repeated_stop_is_noop_safe_and_old_cancel_scope_cannot_stop_a_new_submission(self):
        root = self.runtime.prompt(self.task_id, "目标", "旧工作")
        self.child(root, "child")
        first = self.runtime.cancel(self.task_id)
        second = self.runtime.cancel(self.task_id)
        self.assertEqual(first["cancelled_session_ids"], second["cancelled_session_ids"])
        self.assertTrue(self.runtime.root_context(self.task_id)["control"]["stop_automatic_continuations"])
        self.runtime.conversation(self.task_id)
        old_run_id = self.runtime.store.load_team(self.task_id)["runs"][-1]["run_id"]
        self.runtime.submit_message(self.task_id, "目标", "现在开始新的工作", request_id="after-user-stop")
        self.assertFalse(self.runtime.root_context(self.task_id)["control"]["stop_automatic_continuations"])
        before = len([1 for method, _ in self.client.calls if method in {"session.cancel", "subagent.interrupt"}])
        current = self.runtime.conversation(self.task_id)
        self.assertNotEqual(current["runs"][-1]["run_id"], old_run_id)
        self.assertEqual(current["runs"][-1]["status"], "running")
        self.assertTrue(current["execution_running"])
        self.assertEqual(before, len([1 for method, _ in self.client.calls if method in {"session.cancel", "subagent.interrupt"}]))

    def test_failed_native_child_rpc_is_visible_and_does_not_skip_background_stop(self):
        root = self.runtime.prompt(self.task_id, "目标", "开始工作")
        self.child(root, "child")
        self.client.fail_methods.add("subagent.interrupt")
        background_stops = []
        self.runtime.background_actions_canceller = lambda owner, cancellation: background_stops.append(owner) or []
        with self.assertRaisesRegex(MultiAgentRuntimeError, "subagent.interrupt"):
            self.runtime.cancel(self.task_id)
        self.assertEqual(background_stops, [self.task_id])
        self.assertTrue(self.client.sessions["child"]["running"])
        event = self.runtime.store.list_events(self.task_id)[-1]
        self.assertEqual(event["payload"]["cascade_errors"][0]["target"], "dsh_session:child")
        self.assertEqual(self.runtime.store.load_team(self.task_id)["runs"][-1]["status"], "cancel_requested")
        self.assertNotIn(("session.cancel", {"sessionId": "child"}), self.client.calls)

    def test_missing_ack_or_unsupported_running_mode_remains_an_unresolved_stop(self):
        root = self.runtime.prompt(self.task_id, "目标", "开始工作")
        self.child(root, "child")
        self.client.sessions["child"]["mode"] = "one-shot"
        with self.assertRaisesRegex(MultiAgentRuntimeError, "one-shot"):
            self.runtime.cancel(self.task_id)
        self.assertTrue(self.client.sessions["child"]["running"])
        self.client.sessions["child"]["mode"] = "continuable"
        original_call = self.client.call
        def no_ack(method, payload):
            if method == "subagent.interrupt":
                return {}
            return original_call(method, payload)
        self.client.call = no_ack
        with self.assertRaisesRegex(MultiAgentRuntimeError, "acknowledge"):
            self.runtime.cancel(self.task_id)


if __name__ == "__main__":
    unittest.main()
