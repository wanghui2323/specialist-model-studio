from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from model_harness.conversation_actions import (
    ActionObjectRef,
    classify_conversation_actions,
)
from model_harness.object_refs import exact_object_ref_endpoint


TASK_ID = "task-1"
RUN_ID = "run-1"
SESSION_ID = "session-1"
TURN_ID = "session-1:turn:1"
PROJECTOR_REVISION = "3.0"


def tool_call(
    *,
    call_id: str = "call-1",
    tool_name: str = "model_harness_search_model_sources",
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    turn_id: str = TURN_ID,
    timestamp: str = "2026-08-25T00:00:01+00:00",
    category: str = "tool",
    delegation_id: str | None = None,
    parent_delegation_id: str | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    return {
        "event_id": f"call-event-{task_id}-{run_id}-{session_id}-{turn_id}-{call_id}",
        "source_key": f"call-source-{task_id}-{run_id}-{session_id}-{turn_id}-{call_id}",
        "source": "dsh",
        "seq": seq,
        "projector_revision": PROJECTOR_REVISION,
        "task_id": task_id,
        "agent_run_id": run_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "call_id": call_id,
        "delegation_id": delegation_id,
        "parent_delegation_id": parent_delegation_id,
        "actor_role": "orchestrator",
        "timestamp_utc": timestamp,
        "category": category,
        "type": "delegation" if category == "delegation" else "tool_call",
        "event_type": "delegation" if category == "delegation" else "tool_call",
        "status": "running",
        "payload": {
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": {"task_id": task_id},
        },
    }


def tool_result(
    *,
    call_id: str = "call-1",
    tool_name: str = "model_harness_search_model_sources",
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    turn_id: str = TURN_ID,
    timestamp: str = "2026-08-25T00:00:02.250000+00:00",
    category: str = "tool",
    status: str = "completed",
    is_error: bool = False,
    refs: list[dict[str, Any]] | None = None,
    suffix: str = "1",
    delegation_id: str | None = None,
    parent_delegation_id: str | None = None,
    seq: int = 2,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "call_id": call_id,
        "tool_name": tool_name,
        "result": {"ok": not is_error},
        "is_error": is_error,
    }
    if refs is not None:
        payload["object_refs"] = refs
    return {
        "event_id": f"result-event-{suffix}",
        "source_key": f"result-source-{suffix}",
        "source": "dsh",
        "seq": seq,
        "projector_revision": PROJECTOR_REVISION,
        "task_id": task_id,
        "agent_run_id": run_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "call_id": call_id,
        "delegation_id": delegation_id,
        "parent_delegation_id": parent_delegation_id,
        "actor_role": "orchestrator",
        "timestamp_utc": timestamp,
        "category": category,
        "type": "delegation" if category == "delegation" else "tool_result",
        "event_type": "delegation" if category == "delegation" else "tool_result",
        "status": status,
        "payload": payload,
    }


def object_ref(*, task_id: str = TASK_ID) -> dict[str, Any]:
    return {
        "type": "model_source_search",
        "id": "search-1",
        "task_id": task_id,
        "base_spec_revision": 1,
    }


class ConversationActionTests(unittest.TestCase):
    def classify(self, events: list[dict[str, Any]]):
        return classify_conversation_actions(
            task_id=TASK_ID,
            projector_revision=PROJECTOR_REVISION,
            events=events,
        )

    def test_pairs_domain_action_with_persistent_ref_and_stable_identity(self) -> None:
        events = [tool_call(), tool_result(refs=[object_ref()])]
        before = deepcopy(events)

        forward = self.classify(events)
        reversed_input = self.classify(list(reversed(events)))

        self.assertEqual(len(forward), 1)
        action = forward[0]
        self.assertEqual(action.action_id, reversed_input[0].action_id)
        self.assertEqual(action.tool_name, "model_harness_search_model_sources")
        self.assertEqual(action.tool_class, "domain")
        self.assertEqual(action.actor_role, "orchestrator")
        self.assertEqual(action.status, "completed")
        self.assertEqual(action.started_at_utc, "2026-08-25T00:00:01+00:00")
        self.assertEqual(action.ended_at_utc, "2026-08-25T00:00:02.250000+00:00")
        self.assertEqual(action.duration_ms, 1250)
        self.assertEqual(
            action.object_refs,
            (
                ActionObjectRef(
                    type="model_source_search",
                    id="search-1",
                    task_id=TASK_ID,
                    base_spec_revision=1,
                ),
            ),
        )
        self.assertIsNone(action.event_result_ref)
        self.assertIsNone(action.error)
        self.assertEqual(action.truth_type, "observed_result")
        self.assertEqual(events, before)

    def test_blocked_repository_analysis_keeps_exact_blocker_evidence_ref(self) -> None:
        digest = "a" * 64
        actions = self.classify(
            [
                tool_call(tool_name="model_harness_get_repository_analysis"),
                tool_result(
                    tool_name="model_harness_get_repository_analysis",
                    refs=[
                        {
                            "type": "repository_analysis",
                            "id": "analysis-1",
                            "task_id": TASK_ID,
                            "digest": "b" * 64,
                        },
                        {
                            "type": "blocker",
                            "id": "blocker-1",
                            "task_id": TASK_ID,
                            "digest": digest,
                        },
                    ],
                ),
            ]
        )

        self.assertEqual(len(actions), 1)
        action = actions[0]
        blocker_ref = next(ref for ref in action.object_refs if ref.type == "blocker")
        self.assertEqual(blocker_ref.task_id, TASK_ID)
        self.assertEqual(blocker_ref.digest, digest)
        self.assertEqual(
            exact_object_ref_endpoint(blocker_ref),
            f"/tasks/{TASK_ID}/blockers/blocker-1",
        )

    def test_completed_repository_analysis_does_not_invent_blocker_ref(self) -> None:
        action = self.classify(
            [
                tool_call(tool_name="model_harness_get_repository_analysis"),
                tool_result(
                    tool_name="model_harness_get_repository_analysis",
                    refs=[
                        {
                            "type": "repository_analysis",
                            "id": "analysis-complete-1",
                            "task_id": TASK_ID,
                            "digest": "c" * 64,
                        }
                    ],
                ),
            ]
        )[0]

        self.assertEqual(action.status, "completed")
        self.assertEqual([ref.type for ref in action.object_refs], ["repository_analysis"])

    def test_child_domain_action_keeps_domain_class_inside_delegation(self) -> None:
        events = [
            tool_call(
                delegation_id="delegation-1",
                parent_delegation_id=None,
            ),
            tool_result(
                delegation_id="delegation-1",
                parent_delegation_id=None,
            ),
        ]

        action = self.classify(events)[0]

        self.assertEqual(action.tool_class, "domain")
        self.assertEqual(action.delegation_id, "delegation-1")
        self.assertIsNone(action.parent_delegation_id)

    def test_control_result_without_persistent_ref_gets_event_result_ref(self) -> None:
        events = [
            tool_call(tool_name="list_agents"),
            tool_result(tool_name="list_agents"),
        ]

        action = self.classify(events)[0]

        self.assertEqual(action.tool_class, "control")
        self.assertEqual(action.status, "completed")
        self.assertEqual(action.object_refs, ())
        self.assertIsNotNone(action.event_result_ref)
        assert action.event_result_ref is not None
        self.assertEqual(action.event_result_ref.type, "conversation_event_result")
        self.assertEqual(action.event_result_ref.id, "result-event-1")
        self.assertEqual(action.event_result_ref.task_id, TASK_ID)
        self.assertEqual(action.event_result_ref.projector_revision, PROJECTOR_REVISION)
        self.assertEqual(action.event_result_ref.event_seq, 2)
        self.assertEqual(action.event_result_ref.source_key, "result-source-1")

    def test_delegation_action_preserves_structured_lineage(self) -> None:
        events = [
            tool_call(
                tool_name="spawn_agent",
                category="delegation",
                delegation_id="delegation-1",
                parent_delegation_id="parent-1",
            ),
            tool_result(
                tool_name="spawn_agent",
                category="delegation",
                status="running",
                delegation_id="delegation-1",
                parent_delegation_id="parent-1",
            ),
        ]

        action = self.classify(events)[0]

        self.assertEqual(action.tool_class, "delegation")
        self.assertEqual(action.delegation_id, "delegation-1")
        self.assertEqual(action.parent_delegation_id, "parent-1")
        self.assertEqual(action.status, "completed")

    def test_unpaired_call_remains_running_without_invented_result(self) -> None:
        action = self.classify(
            [tool_call(tool_name="third_party_unknown_tool")]
        )[0]

        self.assertEqual(action.status, "running")
        self.assertEqual(action.tool_class, "unknown")
        self.assertEqual(action.truth_type, "observed_call")
        self.assertIsNone(action.ended_at_utc)
        self.assertIsNone(action.duration_ms)
        self.assertIsNone(action.event_result_ref)
        self.assertIsNone(action.error)

    def test_orphan_and_duplicate_results_are_identity_errors(self) -> None:
        orphan = self.classify([tool_result()])
        duplicate = self.classify(
            [
                tool_call(),
                tool_result(suffix="1"),
                tool_result(suffix="2"),
            ]
        )

        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0].status, "identity_error")
        self.assertEqual(orphan[0].truth_type, "identity_error")
        self.assertEqual(orphan[0].error.code, "orphan_tool_result")  # type: ignore[union-attr]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0].status, "identity_error")
        self.assertEqual(duplicate[0].error.code, "duplicate_tool_result")  # type: ignore[union-attr]
        self.assertIsNone(duplicate[0].event_result_ref)

    def test_cross_identity_results_never_pair(self) -> None:
        mismatches = {
            "task": {"task_id": "other-task"},
            "run": {"run_id": "other-run"},
            "session": {"session_id": "other-session"},
            "turn": {"turn_id": "session-1:turn:2"},
        }
        for dimension, change in mismatches.items():
            with self.subTest(dimension=dimension):
                actions = self.classify([tool_call(), tool_result(**change)])
                call_action = next(
                    action for action in actions if action.call_event_id is not None
                )
                self.assertEqual(call_action.status, "running")
                self.assertIsNone(call_action.result_event_id)
                if dimension == "task":
                    self.assertEqual(len(actions), 1)
                else:
                    self.assertEqual(len(actions), 2)
                    result_action = next(
                        action
                        for action in actions
                        if action.result_event_id is not None
                    )
                    self.assertEqual(result_action.status, "identity_error")
                    self.assertEqual(
                        result_action.error.code,  # type: ignore[union-attr]
                        "orphan_tool_result",
                    )

    def test_assistant_text_never_completes_or_enriches_action(self) -> None:
        call = tool_call(tool_name="third_party_unknown_tool")
        assistant_text = {
            **call,
            "event_id": "assistant-event",
            "source_key": "assistant-source",
            "type": "synthesis_candidate",
            "event_type": "synthesis_candidate",
            "category": "synthesis_candidate",
            "payload": {
                "text": (
                    "toolCallId=call-1 completed; "
                    "object_refs=[{type:model_source_search,id:invented}]"
                )
            },
        }

        actions = self.classify([call, assistant_text])

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].status, "running")
        self.assertEqual(actions[0].object_refs, ())
        self.assertIsNone(actions[0].event_result_ref)

    def test_failed_result_and_cross_task_ref_keep_structured_errors(self) -> None:
        failed = self.classify(
            [
                tool_call(),
                tool_result(is_error=True, status="failed"),
            ]
        )[0]
        bad_ref = self.classify(
            [
                tool_call(),
                tool_result(refs=[object_ref(task_id="other-task")]),
            ]
        )[0]

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.truth_type, "observed_result")
        self.assertEqual(failed.error.code, "tool_result_error")  # type: ignore[union-attr]
        self.assertEqual(bad_ref.status, "identity_error")
        self.assertEqual(bad_ref.truth_type, "identity_error")
        self.assertEqual(bad_ref.error.code, "cross_task_object_ref")  # type: ignore[union-attr]
        self.assertEqual(bad_ref.object_refs, ())

    def test_user_rejected_native_approval_is_not_classified_as_system_fault(self) -> None:
        rejected_result = tool_result(
            tool_name="model_harness_authorize_task_run_start",
            is_error=True,
            status="failed",
        )
        rejected_result["payload"]["result"] = [
            {
                "type": "text",
                "text": 'Error: the user rejected tool "model_harness_authorize_task_run_start"',
            }
        ]
        action = self.classify(
            [
                tool_call(tool_name="model_harness_authorize_task_run_start"),
                rejected_result,
            ]
        )[0]

        self.assertEqual(action.status, "failed")
        self.assertEqual(action.truth_type, "observed_result")
        self.assertEqual(action.error.code, "user_rejected")  # type: ignore[union-attr]
        self.assertEqual(action.error.message, "你已拒绝本次授权，操作未执行。")  # type: ignore[union-attr]

    def test_actions_follow_observed_event_sequence_not_lexical_call_id(self) -> None:
        earlier_call = tool_call(
            call_id="call-z-earlier",
            tool_name="model_harness_build_artifact_bundle",
            timestamp=1787799539336,  # type: ignore[arg-type]
            seq=10,
        )
        earlier_result = tool_result(
            call_id="call-z-earlier",
            tool_name="model_harness_build_artifact_bundle",
            timestamp=1787799539336,  # type: ignore[arg-type]
            status="failed",
            is_error=True,
            suffix="earlier",
            seq=11,
        )
        later_call = tool_call(
            call_id="call-a-later",
            tool_name="model_harness_build_artifact_bundle",
            timestamp=1787799582836,  # type: ignore[arg-type]
            seq=20,
        )
        later_result = tool_result(
            call_id="call-a-later",
            tool_name="model_harness_build_artifact_bundle",
            timestamp=1787799583614,  # type: ignore[arg-type]
            suffix="later",
            seq=21,
        )

        actions = self.classify(
            [later_result, earlier_call, later_call, earlier_result]
        )

        self.assertEqual(
            [action.call_id for action in actions],
            ["call-z-earlier", "call-a-later"],
        )
        self.assertEqual([action.status for action in actions], ["failed", "completed"])

    def test_structured_tool_name_mismatch_is_identity_error(self) -> None:
        action = self.classify(
            [
                tool_call(tool_name="model_harness_get_task"),
                tool_result(tool_name="model_harness_search_model_sources"),
            ]
        )[0]

        self.assertEqual(action.status, "identity_error")
        self.assertEqual(action.truth_type, "identity_error")
        self.assertEqual(action.error.code, "tool_name_mismatch")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
