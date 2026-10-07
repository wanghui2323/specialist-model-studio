from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import asdict

from model_harness.conversation_actions import classify_conversation_actions
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
    def test_task_read_404_recovers_only_after_paired_same_owner_promotion(self) -> None:
        def event(sequence, call_id, tool, kind, payload, run):
            return {
                "event_id": f"event-{sequence}", "source": "dsh", "seq": sequence,
                "source_key": f"dsh:root:{sequence}", "source_seq": sequence,
                "projector_revision": "3.3", "task_id": "task-1",
                "agent_run_id": run, "session_id": "root", "root_session_id": "root",
                "turn_id": f"turn-{run}", "call_id": call_id,
                "actor_role": "orchestrator", "event_type": kind, "type": kind,
                "payload": {"call_id": call_id, "tool_name": tool, **payload},
            }
        promoted = {
            "task": {"task_id": "task-1", "record_type": "training_task", "status": "needs_recipe"},
            "conversation": {"conversation_id": "task-1", "task_id": "task-1", "status": "bound"},
            "promoted": True,
        }
        events = [
            event(1, "read", "model_harness_get_task", "tool_call", {"arguments": '{"task_id":"task-1"}'}, "agent-old"),
            event(2, "read", "model_harness_get_task", "tool_result", {"is_error": True, "result": [{"type": "text", "text": "Error: Specialist Model Studio 404: missing"}]}, "agent-old"),
            event(3, "promote", "model_harness_promote_conversation", "tool_call", {"arguments": '{"conversation_id":"task-1"}'}, "agent-new"),
            event(4, "promote", "model_harness_promote_conversation", "tool_result", {"is_error": False, "result": [{"type": "text", "text": json.dumps(promoted)}]}, "agent-new"),
        ]

        def project(observed, exists=True):
            classified = classify_conversation_actions(task_id="task-1", projector_revision="3.3", events=observed)
            return project_conversation_objects(
                task_id="task-1", agent_runs=[
                    {"run_id": "agent-old", "agent_turn_id": "turn-old", "status": "idle_without_final"},
                    {"run_id": "agent-new", "agent_turn_id": "turn-new", "status": "idle_without_final"},
                ], actions=[asdict(action) for action in classified], events=observed,
                training_task_exists=exists, background_actions=[], pending=[], agent_response_running=False,
            )

        result = project(events)
        self.assertEqual(result["actions"][0]["status"], "failed")
        self.assertEqual(result["risks"][0]["status"], "failed")
        self.assertFalse(result["risks"][0]["active"])
        self.assertEqual(result["risks"][0]["resolution"], {
            "kind": "task_created_by_later_promotion", "source_type": "Action",
            "source_id": result["actions"][1]["action_id"],
        })
        self.assertEqual(result["interaction_projection"]["phase"], "idle")
        self.assertTrue(project(events, exists=False)["risks"][0]["active"])

        for name in ("403", "prose_error", "foreign_read", "foreign_promotion", "prose_success",
                     "unbound_result", "foreign_result_task", "foreign_result_conversation", "foreign_result_binding",
                     "missing_pair", "duplicate_event", "different_session", "child_session", "earlier_success",
                     "identity_error", "training_failure", "promotion_error", "unobserved_result",
                     "missing_native_order", "earlier_native_success", "mismatched_payload_call"):
            changed = deepcopy(events)
            if name in {"403", "prose_error"}:
                changed[1]["payload"]["result"][0]["text"] = (
                    "Error: Specialist Model Studio 403: permission denied" if name == "403" else "Task not found; please create it."
                )
            elif name == "foreign_read":
                changed[0]["payload"]["arguments"] = '{"task_id":"task-other"}'
            elif name == "foreign_promotion":
                changed[2]["payload"]["arguments"] = '{"conversation_id":"task-other"}'
            elif name == "prose_success":
                changed[3]["payload"]["result"][0]["text"] = "The task is registered now."
            elif name == "unbound_result":
                changed[3]["payload"]["result"][0]["text"] = json.dumps({**promoted, "task": {"task_id": "task-1", "record_type": "conversation_draft"}})
            elif name in {"foreign_result_task", "foreign_result_conversation", "foreign_result_binding"}:
                foreign = deepcopy(promoted)
                if name == "foreign_result_task":
                    foreign["task"]["task_id"] = "task-other"
                else:
                    foreign["conversation"]["conversation_id" if name == "foreign_result_conversation" else "task_id"] = "task-other"
                changed[3]["payload"]["result"][0]["text"] = json.dumps(foreign)
            elif name == "missing_pair":
                changed.pop(2)
            elif name == "duplicate_event":
                changed.append(deepcopy(changed[3]))
            elif name in {"different_session", "child_session"}:
                for entry in changed[2:]:
                    entry["session_id"] = "child"
                    if name == "different_session":
                        entry["root_session_id"] = "child"
            elif name == "earlier_success":
                changed = changed[2:] + changed[:2]
                for sequence, entry in enumerate(changed, 1):
                    entry["seq"] = entry["source_seq"] = sequence
            elif name == "identity_error":
                changed[1]["turn_id"] = None
            elif name == "training_failure":
                for entry in changed[:2]:
                    entry["payload"]["tool_name"] = "model_harness_start_task_run"
            elif name == "promotion_error":
                changed[3]["payload"]["is_error"] = True
            elif name == "unobserved_result":
                changed[3]["source"] = "runtime"
            elif name == "missing_native_order":
                changed[3].pop("source_seq")
            elif name == "earlier_native_success":
                changed[2]["source_seq"], changed[3]["source_seq"] = -1, 0
            elif name == "mismatched_payload_call":
                changed[3]["payload"]["call_id"] = "different-call"
            with self.subTest(name=name):
                projection = project(changed)
                self.assertTrue(any(risk["active"] for risk in projection["risks"]))
                self.assertFalse(any((risk.get("resolution") or {}).get("kind") == "task_created_by_later_promotion" for risk in projection["risks"]))

    def test_training_start_retires_only_the_proven_earlier_capability_match_failure(self):
        def action(name, tool, status, sequence):
            return {
                "action_id": name, "task_id": "task-1", "agent_run_id": "agent-1",
                "session_id": "session-1", "turn_id": "turn-1", "call_id": f"call-{name}",
                "call_event_id": f"event-call-{name}", "result_event_id": f"event-result-{name}",
                "truth_type": "observed_result", "tool_class": "domain",
                "tool_name": tool, "status": status,
                "error": {"code": "tool_result_error"} if status == "failed" else None,
                "event_result_ref": {
                    "type": "conversation_event_result", "task_id": "task-1",
                    "id": f"event-result-{name}", "event_seq": sequence,
                },
            }
        failed = action("capability", "model_harness_match_capability", "failed", 10)
        started = action("start", "model_harness_start_task_run", "completed", 55)
        def project(actions):
            return project_conversation_objects(
                task_id="task-1", agent_runs=[{"run_id": "agent-1", "agent_turn_id": "agent-turn-1", "status": "idle_without_final"}],
                actions=actions, background_actions=[], pending=[], agent_response_running=False,
            )
        result = project([failed, started])
        risk = result["risks"][0]
        self.assertEqual(risk["status"], "failed")
        self.assertEqual(risk["error"], failed["error"])
        self.assertFalse(risk["active"])
        self.assertEqual(risk["lifecycle_status"], "superseded")
        self.assertEqual(risk["resolution"], {
            "kind": "capability_resolved_by_training_start", "source_type": "Action", "source_id": "start",
        })
        self.assertEqual(result["actions"][0]["status"], "failed")
        self.assertEqual(result["interaction_projection"]["phase"], "idle")
        self.assertIsNone(result["primary_attention"])
        for field, value in [
            ("task_id", "other-task"), ("agent_run_id", "other-run"),
            ("truth_type", "observed_call"), ("call_event_id", None),
            ("result_event_id", None), ("session_id", None),
            ("event_result_ref", None), ("status", "running"),
            ("error", {"code": "start_not_confirmed"}),
        ]:
            with self.subTest(field=field):
                candidate = {**started, field: value}
                blocked = project([failed, candidate])
                self.assertTrue(blocked["risks"][0]["active"])
                self.assertEqual(blocked["interaction_projection"]["phase"], "blocked")
        for ref_override in [
            {"task_id": "other-task"}, {"id": "unpaired-result"},
            {"event_seq": 9}, {"event_seq": 10}, {"event_seq": True},
        ]:
            with self.subTest(ref_override=ref_override):
                candidate = {**started, "event_result_ref": {**started["event_result_ref"], **ref_override}}
                self.assertTrue(project([failed, candidate])["risks"][0]["active"])
        self.assertTrue(project([started, failed])["risks"][0]["active"], "an earlier start is not recovery")
        for failed_override in [
            {"status": "identity_error"}, {"task_id": "other-task"},
            {"agent_run_id": "other-run"}, {"truth_type": "identity_error"},
            {"tool_name": "model_harness_build_artifact_bundle"},
        ]:
            with self.subTest(failed_override=failed_override):
                self.assertTrue(project([{**failed, **failed_override}, started])["risks"][0]["active"])
        delivery_failure = action("delivery", "model_harness_build_artifact_bundle", "failed", 60)
        delivery_blocked = project([failed, started, delivery_failure])
        self.assertFalse(delivery_blocked["risks"][0]["active"])
        self.assertTrue(delivery_blocked["risks"][1]["active"])
        self.assertEqual(delivery_blocked["interaction_projection"]["phase"], "blocked")
        self.assertEqual(delivery_blocked["primary_attention"]["object_id"], "risk:delivery")

    def test_old_failure_stays_auditable_without_blocking_a_new_unrelated_turn(self) -> None:
        def project(status="failed", scope="agent-old"):
            return project_conversation_objects(
                task_id="task-1",
                agent_runs=[
                    {"run_id": "agent-old", "agent_turn_id": "turn-old", "status": "idle_without_final"},
                    {"run_id": "agent-new", "agent_turn_id": "turn-new", "status": "idle_without_final"},
                ],
                actions=[{"action_id": "old-import", "agent_run_id": scope,
                    "status": status, "tool_name": "model_harness_import_dataset", "tool_class": "domain"}],
                background_actions=[], pending=[], agent_response_running=False,
            )
        result = project()
        self.assertEqual(result["interaction_projection"]["phase"], "idle")
        self.assertTrue(result["risks"][0]["active"])
        self.assertIsNone(result["risks"][0]["resolution"])
        self.assertIsNone(result["primary_attention"])
        for status, scope in [("identity_error", "agent-old"), ("failed", None), ("failed", "agent-new")]:
            with self.subTest(status=status, scope=scope):
                self.assertEqual(project(status, scope)["interaction_projection"]["phase"], "blocked")

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
