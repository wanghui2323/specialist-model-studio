from __future__ import annotations

import json
import unittest
from copy import deepcopy

from model_harness.conversation_payloads import (
    CONVERSATION_EVENT_PAYLOAD_MODE,
    CONVERSATION_RESULT_PREVIEW_MAX_CHARS,
    INTERACTION_PROJECTION_SCHEMA_VERSION,
    ConversationPayloadCompactionError,
    compact_conversation_response,
    project_conversation_objects,
)
from model_harness.conversation_stream import (
    ConversationStreamRecord,
    _delta_payload,
)


def result_event(result: object) -> dict[str, object]:
    return {
        "event_id": "event-large-result",
        "source_key": "dsh:3.1:session-1:3:tool/result",
        "source": "dsh",
        "seq": 7,
        "projector_revision": "3.1",
        "task_id": "task-1",
        "event_type": "tool_result",
        "type": "tool_result",
        "category": "tool",
        "payload": {
            "call_id": "call-1",
            "tool_name": "model_harness_get_task",
            "result": result,
        },
    }


class ConversationPayloadCompactionTests(unittest.TestCase):
    def test_actions_and_checkpoints_bind_to_canonical_agent_turn(self) -> None:
        projection = project_conversation_objects(
            task_id="task-identity",
            agent_runs=[
                {
                    "run_id": "agent-run-identity",
                    "agent_turn_id": "agent-turn-identity",
                    "status": "running",
                }
            ],
            actions=[
                {
                    "action_id": "action-identity",
                    "agent_run_id": "agent-run-identity",
                    "turn_id": "dsh-child-session:turn:1",
                    "status": "running",
                }
            ],
            background_actions=[],
            pending=[
                {
                    "rpc_id": "rpc-identity",
                    "kind": "question",
                    "agent_run_id": "agent-run-identity",
                    "session_id": "dsh-root-session",
                }
            ],
            agent_response_running=False,
        )

        self.assertEqual(
            projection["actions"][0]["agent_turn_id"],
            "agent-turn-identity",
        )
        self.assertEqual(
            projection["actions"][0]["turn_id"],
            "dsh-child-session:turn:1",
        )
        self.assertEqual(
            projection["human_checkpoints"][0]["agent_turn_id"],
            "agent-turn-identity",
        )
        self.assertEqual(
            projection["interaction_projection"]["subject"]["agent_turn_id"],
            "agent-turn-identity",
        )

    def test_typed_objects_keep_checkpoint_primary_and_failure_visible(self) -> None:
        projection = project_conversation_objects(
            task_id="task-1",
            agent_runs=[
                {
                    "run_id": "agent-run-1",
                    "agent_turn_id": "agent-turn-1",
                    "status": "failed",
                    "error": "tool failed",
                    "composer_request": {
                        "request_id": "request-1",
                        "mode": "queue_after_turn",
                        "actor": "user",
                    },
                }
            ],
            actions=[
                {
                    "action_id": "action-1",
                    "status": "failed",
                    "error": {"code": "UPSTREAM", "message": "failed"},
                }
            ],
            background_actions=[
                {
                    "action_id": "training-run:run-1",
                    "action_type": "training_run",
                    "run_id": "run-1",
                    "status": "cancel_requested",
                    "running": True,
                    "worker_running": True,
                    "cancel_requested": True,
                    "cancel": {
                        "actor": "system",
                        "kind": "safety_stop",
                        "reason": "disk reserve exhausted",
                    },
                    "last_event": {"type": "run.cancel_requested", "seq": 4},
                }
            ],
            pending=[
                {
                    "rpc_id": "rpc-1",
                    "kind": "question",
                    "session_id": "session-1",
                    "questions": [{"id": "q1", "question": "继续吗？"}],
                    "private_context": "must-not-project",
                }
            ],
            agent_response_running=False,
        )

        self.assertEqual(
            projection["primary_attention"],
            {
                "object_type": "TrainingRun",
                "object_id": "run-1",
                "reason": "cancellation_in_progress",
            },
        )
        self.assertEqual(projection["agent_turns"][0]["request_id"], "request-1")
        self.assertEqual(projection["training_runs"][0]["cancel"]["actor"], "system")
        self.assertEqual(len(projection["risks"]), 2)
        self.assertEqual(
            projection["interaction_projection"]["schema_version"],
            INTERACTION_PROJECTION_SCHEMA_VERSION,
        )
        self.assertEqual(
            projection["interaction_projection"]["phase"],
            "stopping",
        )
        self.assertFalse(projection["interaction_projection"]["can_cancel"])
        self.assertNotIn(
            "must-not-project",
            json.dumps(projection, ensure_ascii=False),
        )

    def test_interaction_projection_has_one_ordered_authoritative_phase(self) -> None:
        def project(**overrides: object) -> dict[str, object]:
            values: dict[str, object] = {
                "task_id": "task-interaction",
                "agent_runs": [],
                "actions": [],
                "background_actions": [],
                "pending": [],
                "agent_response_running": False,
            }
            values.update(overrides)
            return project_conversation_objects(**values)  # type: ignore[arg-type]

        idle = project()["interaction_projection"]
        self.assertEqual(idle["phase"], "idle")
        self.assertIsNone(idle["subject"])
        self.assertFalse(idle["can_cancel"])

        waiting_question = project(
            pending=[{"rpc_id": "q-1", "kind": "question"}],
        )["interaction_projection"]
        self.assertEqual(waiting_question["phase"], "waiting_question")
        self.assertEqual(waiting_question["subject"]["rpc_id"], "q-1")

        waiting_approval = project(
            pending=[{"rpc_id": "a-1", "kind": "approval"}],
        )["interaction_projection"]
        self.assertEqual(waiting_approval["phase"], "waiting_approval")

        active = project(
            agent_runs=[
                {
                    "run_id": "run-active",
                    "agent_turn_id": "turn-active",
                    "status": "running",
                }
            ],
            actions=[
                {
                    "action_id": "action-active",
                    "agent_run_id": "run-active",
                    "turn_id": "tool-turn-active",
                    "status": "running",
                }
            ],
            background_actions=[
                {
                    "action_id": "training-run:bg-active",
                    "action_type": "training_run",
                    "run_id": "bg-active",
                    "running": True,
                }
            ],
            agent_response_running=True,
            can_cancel=True,
        )["interaction_projection"]
        self.assertEqual(active["phase"], "agent_working")
        self.assertEqual(active["subject"]["agent_turn_id"], "turn-active")
        self.assertEqual(active["turn_identity"]["agent_run_id"], "run-active")
        self.assertEqual(active["turn_identity"]["turn_id"], "tool-turn-active")
        self.assertEqual(active["active_action_id"], "action-active")
        self.assertTrue(active["background"]["running"])
        self.assertTrue(active["can_cancel"])

        background = project(
            background_actions=[
                {
                    "action_id": "training-run:bg-only",
                    "action_type": "training_run",
                    "run_id": "bg-only",
                    "running": True,
                }
            ],
            can_cancel=True,
        )["interaction_projection"]
        self.assertEqual(background["phase"], "background_working")
        self.assertEqual(background["subject"]["training_run_id"], "bg-only")

        stopping = project(
            background_actions=[
                {
                    "action_id": "training-run:bg-stop",
                    "action_type": "training_run",
                    "run_id": "bg-stop",
                    "running": True,
                    "cancel_requested": True,
                }
            ],
            pending=[{"rpc_id": "q-stale", "kind": "question"}],
            cancellation_pending=True,
            can_cancel=True,
        )["interaction_projection"]
        self.assertEqual(stopping["phase"], "stopping")
        self.assertEqual(stopping["subject"]["training_run_id"], "bg-stop")
        self.assertFalse(stopping["can_cancel"])

        degraded = project(
            pending=[{"rpc_id": "q-hidden", "kind": "question"}],
            observation_degraded=True,
            cancellation_pending=True,
        )["interaction_projection"]
        self.assertEqual(degraded["phase"], "observation_degraded")
        self.assertIsNone(degraded["subject"])

        for status, expected in (
            ("completed", "completed"),
            ("failed", "failed"),
            ("cancelled", "stopped"),
            ("interrupted", "stopped"),
        ):
            with self.subTest(status=status):
                terminal = project(
                    agent_runs=[
                        {
                            "run_id": f"run-{status}",
                            "agent_turn_id": f"turn-{status}",
                            "status": status,
                        }
                    ]
                )["interaction_projection"]
                self.assertEqual(terminal["phase"], expected)
                self.assertEqual(terminal["terminal_outcome"], expected)
                self.assertFalse(terminal["can_cancel"])

        blocked = project(
            actions=[{"action_id": "action-failed", "status": "failed"}],
        )["interaction_projection"]
        self.assertEqual(blocked["phase"], "blocked")
        self.assertEqual(blocked["subject"]["object_type"], "Risk")

    def test_later_success_supersedes_same_operation_risk_but_keeps_audit(self) -> None:
        projection = project_conversation_objects(
            task_id="task-1",
            agent_runs=[],
            actions=[
                {
                    "action_id": "action-build-failed",
                    "tool_name": "model_harness_build_artifact_bundle",
                    "tool_class": "domain",
                    "status": "failed",
                    "error": {
                        "code": "tool_result_error",
                        "message": "first attempt failed",
                    },
                },
                {
                    "action_id": "action-approval-rejected",
                    "tool_name": "model_harness_authorize_artifact_bundle_build",
                    "tool_class": "domain",
                    "status": "failed",
                    "error": {
                        "code": "user_rejected",
                        "message": "user declined",
                    },
                },
                {
                    "action_id": "action-approval-completed",
                    "tool_name": "model_harness_authorize_artifact_bundle_build",
                    "tool_class": "domain",
                    "status": "completed",
                },
                {
                    "action_id": "action-build-completed",
                    "tool_name": "model_harness_build_artifact_bundle",
                    "tool_class": "domain",
                    "status": "completed",
                },
            ],
            background_actions=[],
            pending=[],
            agent_response_running=False,
        )

        self.assertIsNone(projection["primary_attention"])
        self.assertEqual(len(projection["risks"]), 2)
        self.assertEqual(
            [risk["lifecycle_status"] for risk in projection["risks"]],
            ["superseded", "superseded"],
        )
        self.assertEqual(
            projection["risks"][0]["resolution"],
            {
                "kind": "superseded_by_later_success",
                "source_type": "Action",
                "source_id": "action-build-completed",
            },
        )
        self.assertEqual(
            projection["risks"][1]["resolution"]["source_id"],
            "action-approval-completed",
        )
        self.assertEqual(
            projection["risks"][1]["error"]["code"],
            "user_rejected",
        )

    def test_failure_after_success_remains_current_and_identity_error_never_auto_resolves(self) -> None:
        projection = project_conversation_objects(
            task_id="task-1",
            agent_runs=[],
            actions=[
                {
                    "action_id": "action-success-first",
                    "tool_name": "model_harness_build_artifact_bundle",
                    "tool_class": "domain",
                    "status": "completed",
                },
                {
                    "action_id": "action-failed-later",
                    "tool_name": "model_harness_build_artifact_bundle",
                    "tool_class": "domain",
                    "status": "failed",
                    "error": {"code": "tool_result_error"},
                },
                {
                    "action_id": "action-identity-error",
                    "tool_name": "model_harness_authorize_artifact_bundle_build",
                    "tool_class": "domain",
                    "status": "identity_error",
                    "error": {"code": "duplicate_tool_result"},
                },
                {
                    "action_id": "action-success-after-identity-error",
                    "tool_name": "model_harness_authorize_artifact_bundle_build",
                    "tool_class": "domain",
                    "status": "completed",
                },
            ],
            background_actions=[],
            pending=[],
            agent_response_running=False,
        )

        self.assertTrue(projection["risks"][0]["active"])
        self.assertTrue(projection["risks"][1]["active"])
        self.assertEqual(
            projection["primary_attention"],
            {
                "object_type": "Risk",
                "object_id": "risk:action-identity-error",
                "reason": "recoverable_history",
            },
        )

    def test_large_results_are_compacted_without_mutating_truth_objects(self) -> None:
        tail = "TAIL-MUST-NOT-LEAK"
        event = result_event(f"{'A' * 6000}{tail}")
        verdict_event = {
            "event_id": "event-final",
            "source_key": "dsh:3.1:session-1:4:assistant/message",
            "source": "dsh",
            "seq": 8,
            "projector_revision": "3.1",
            "task_id": "task-1",
            "event_type": "final_synthesis",
            "type": "final_synthesis",
            "category": "final",
            "payload": {
                "synthesis_verdict": {
                    "accepted": True,
                    "supporting_event_ids": ["event-large-result"],
                    "evidence_digest": "digest-1",
                },
                "object_refs": [
                    {
                        "type": "model_source_search",
                        "id": "search-1",
                        "task_id": "task-1",
                    }
                ],
            },
        }
        response = {
            "schema_version": "2.0",
            "events": [deepcopy(event), deepcopy(verdict_event)],
            "items": [deepcopy(event), deepcopy(verdict_event)],
            "actions": [
                {
                    "action_id": "action-1",
                    "status": "completed",
                    "object_refs": verdict_event["payload"]["object_refs"],
                }
            ],
            "synthesis_verdict_version": "1.0",
        }
        before = deepcopy(response)

        compact = compact_conversation_response(response)

        self.assertEqual(response, before)
        self.assertEqual(compact["event_payload_mode"], CONVERSATION_EVENT_PAYLOAD_MODE)
        self.assertEqual(compact["actions"], response["actions"])
        self.assertEqual(
            compact["events"][1]["payload"],
            verdict_event["payload"],
        )
        for collection in ("events", "items"):
            payload = compact[collection][0]["payload"]
            self.assertNotIn("result", payload)
            self.assertTrue(payload["result_truncated"])
            self.assertGreater(payload["result_size_bytes"], 4096)
            self.assertLessEqual(
                len(payload["result_preview"]),
                CONVERSATION_RESULT_PREVIEW_MAX_CHARS,
            )
            self.assertNotIn(tail, payload["result_preview"])
            self.assertEqual(
                payload["event_result_ref"],
                {
                    "type": "conversation_event_result",
                    "id": "event-large-result",
                    "task_id": "task-1",
                    "projector_revision": "3.1",
                    "event_seq": 7,
                    "source_key": "dsh:3.1:session-1:3:tool/result",
                },
            )

        self.assertNotIn(tail, json.dumps(compact, ensure_ascii=False))

    def test_small_results_remain_exact(self) -> None:
        event = result_event({"status": "needs_recipe"})
        compact = compact_conversation_response(
            {"events": [event], "items": [deepcopy(event)]}
        )

        self.assertEqual(
            compact["events"][0]["payload"]["result"],
            {"status": "needs_recipe"},
        )
        self.assertNotIn("result_preview", compact["events"][0]["payload"])

    def test_large_result_without_exact_event_identity_fails_closed(self) -> None:
        event = result_event("A" * 5000)
        del event["event_id"]

        with self.assertRaises(ConversationPayloadCompactionError):
            compact_conversation_response({"events": [event], "items": []})

    def test_snapshot_and_delta_frames_never_rehydrate_result_tail(self) -> None:
        tail = "SSE-TAIL-MUST-NOT-LEAK"
        compact = compact_conversation_response(
            {
                "schema_version": "2.0",
                "events": [result_event(f"{'B' * 6000}{tail}")],
                "items": [],
                "actions": [],
            }
        )
        snapshot = ConversationStreamRecord(
            cursor=1,
            event="snapshot",
            projector_revision="3.1",
            payload={"conversation": compact},
        ).encode("task-1", "a" * 32)
        delta = ConversationStreamRecord(
            cursor=2,
            event="delta",
            projector_revision="3.1",
            payload=_delta_payload(
                {"events": [], "items": [], "actions": []},
                compact,
            ),
        ).encode("task-1", "a" * 32)

        self.assertNotIn(tail.encode(), snapshot)
        self.assertNotIn(tail.encode(), delta)
        self.assertIn(b'"result_truncated":true', snapshot)
        self.assertIn(b'"result_truncated":true', delta)


if __name__ == "__main__":
    unittest.main()
