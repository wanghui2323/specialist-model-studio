from __future__ import annotations

import unittest
from copy import deepcopy

from model_harness.continuation_lineage import bind_child_invocations, complete_history
from model_harness.multi_agent import DshConversationV2Projector


def raw(seq, kind, data):
    return {"event": {"seq": seq, "type": kind, "data": data}}


class ContinuationLineageTests(unittest.TestCase):
    def test_complete_history_preserves_old_relays_across_message_pages(self):
        calls = []
        def call(method, request):
            calls.append((method, dict(request)))
            return {"events": [raw(1, "turn/start", {})], "hasMore": False} if request.get("beforeSeq") == 20 else {"events": [raw(20, "user/message", {})], "hasMore": True}
        history = complete_history(call, "child")
        self.assertEqual([item["event"]["seq"] for item in history["events"]], [1, 20])
        self.assertFalse(history["hasMore"])
        self.assertEqual(calls[1], ("session.history", {"sessionId": "child", "maxMessages": 240, "beforeSeq": 20}))

    def test_incomplete_or_repeating_history_fails_closed(self):
        for page in ({"events": [], "hasMore": True}, {"events": [raw(20, "user/message", {})], "hasMore": True}, {"events": "invalid"}):
            with self.subTest(page=page), self.assertRaises(ValueError):
                complete_history(lambda *args: page, "child")

    def setUp(self):
        self.team = {"root_session_id": "root", "root_agent_id": "training_orchestrator",
            "runs": [{"run_id": "run-old"}, {"run_id": "run-new"}], "agents": {},
            "delegations": {"birth": {"delegation_id": "birth", "dsh_session_id": "child",
                "agent_run_id": "run-old", "target_agent_id": "evaluation_delivery",
                "source_agent_id": "training_orchestrator", "source_session_id": "root",
                "lineage_verified": True, "lineage_origin": "subagent",
                "lineage_parent_session_id": "root", "parent_delegation_id": None}}}
        self.calls = []
        for call_id, message in [("trial", "Try exact sample"), ("bundle", "Build exact bundle")]:
            self.calls.extend([
                {"event_id": f"{call_id}-call", "session_id": "root", "call_id": call_id,
                    "agent_run_id": "run-new", "turn_id": "root:turn:2",
                    "payload": {"tool_name": "send_message", "arguments": {"subagent_id": "child", "message": message}}},
                {"event_id": f"{call_id}-result", "session_id": "root", "call_id": call_id,
                    "agent_run_id": "run-new", "turn_id": "root:turn:2",
                    "payload": {"tool_name": "send_message", "is_error": False, "dsh_session_id": "child"}},
            ])
        self.history = {"events": [
            raw(1, "turn/start", {"turn": 1}),
            raw(2, "tool/call", {"callId": "evaluate", "name": "model_harness_get_evaluation_report"}),
            raw(10, "turn/start", {"turn": 2}),
            raw(11, "user/message", {"id": "relay-trial", "source": {"kind": "coordinator", "senderSessionId": "root"}, "content": [{"type": "text", "text": "Try exact sample"}]}),
            raw(12, "tool/call", {"callId": "trial-work", "name": "model_harness_run_sample_inference"}),
            raw(20, "turn/start", {"turn": 3}),
            raw(21, "user/message", {"id": "relay-bundle", "source": {"kind": "coordinator", "senderSessionId": "root"}, "content": [{"type": "text", "text": "Build exact bundle"}]}),
            raw(22, "tool/call", {"callId": "bundle-work", "name": "model_harness_build_artifact_bundle"}),
        ]}

    def bind(self, calls=None, history=None, team=None):
        return bind_child_invocations(team=team or self.team, child_session_id="child",
            history=history or self.history, root_events=calls if calls is not None else self.calls)

    def project(self, team, history=None):
        return DshConversationV2Projector().project(task_id="task", team=team,
            session_id="child", session_agent_id="evaluation_delivery", history=history or self.history)

    def test_relay_binds_each_invocation_without_reassigning_historical_actions(self):
        team = self.bind()
        actions = [item for item in self.project(team) if item["type"] == "tool_call"]
        self.assertEqual([(item["agent_run_id"], item["delegation_id"], item["turn_id"]) for item in actions], [
            ("run-old", "birth", "child:turn:1"),
            ("run-new", "trial", "child:turn:2"),
            ("run-new", "bundle", "child:turn:3"),
        ])
        self.assertEqual(self.bind(team=team), team)
        self.assertNotIn("child_source_seq_ceiling", self.team["delegations"]["birth"])

    def test_unknown_relay_does_not_inherit_birth_or_previous_invocation(self):
        team = self.bind(calls=self.calls[:2])
        actions = [item for item in self.project(team) if item["type"] == "tool_call"]
        self.assertEqual(actions[1]["delegation_id"], "trial")
        self.assertIsNone(actions[2]["agent_run_id"])

    def test_duplicate_or_rejected_parent_receipt_fails_closed(self):
        for mutate in ("duplicate", "denied", "wrong-target", "wrong-run"):
            calls = deepcopy(self.calls)
            if mutate == "duplicate": calls.append(deepcopy(calls[0]))
            if mutate == "denied": calls[1]["payload"]["is_error"] = True
            if mutate == "wrong-target": calls[1]["payload"]["dsh_session_id"] = "other"
            if mutate == "wrong-run": calls[1]["agent_run_id"] = "other"
            with self.subTest(mutate=mutate):
                self.assertNotIn("trial", self.bind(calls=calls)["delegations"])

    def test_ambiguous_relay_revokes_derived_binding_but_keeps_original_evidence(self):
        team = self.bind()
        history = deepcopy(self.history)
        history["events"].append(raw(31, "user/message", {"id": "duplicate-relay",
            "source": {"kind": "coordinator", "senderSessionId": "root"},
            "content": [{"type": "text", "text": "Try exact sample"}]}))
        self.assertNotIn("trial", self.bind(team=team, history=history)["delegations"])
        self.assertIn("trial", team["delegations"])

    def test_wrong_sender_or_prose_only_match_never_binds(self):
        history = deepcopy(self.history)
        history["events"][3]["event"]["data"]["source"]["senderSessionId"] = "unrelated"
        self.assertNotIn("trial", self.bind(history=history)["delegations"])
        calls = deepcopy(self.calls)
        calls[0]["payload"]["arguments"] = {"message": "child: Try exact sample"}
        self.assertNotIn("trial", self.bind(calls=calls)["delegations"])
