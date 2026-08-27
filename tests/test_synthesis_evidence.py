from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from model_harness.synthesis_evidence import (
    EvidenceObjectRef,
    RunBoundary,
    VerifiedChildBinding,
    evaluate_synthesis_evidence,
)


TASK_ID = "task-asr-1"
TEAM_ID = "team-1"
ROOT_SESSION_ID = "root-session"
PROJECTOR_REVISION = "3.0"
RUN_ID = "agent-run-1"


def event(
    source_seq: int,
    event_type: str,
    *,
    payload: dict[str, Any],
    session_id: str = ROOT_SESSION_ID,
    category: str = "tool",
    status: str = "completed",
    event_id: str | None = None,
    agent_run_id: str | None = RUN_ID,
) -> dict[str, Any]:
    selected_event_id = event_id or f"event-{session_id}-{source_seq}-{event_type}"
    return {
        "schema_version": "2.0",
        "event_id": selected_event_id,
        "seq": source_seq + 10,
        "task_id": TASK_ID,
        "team_id": TEAM_ID,
        "root_session_id": ROOT_SESSION_ID,
        "session_id": session_id,
        "dsh_session_id": session_id,
        "agent_run_id": agent_run_id,
        "source": "dsh",
        "projector_revision": PROJECTOR_REVISION,
        "source_key": f"source:{selected_event_id}",
        "source_seq": source_seq,
        "category": category,
        "type": event_type,
        "event_type": event_type,
        "status": status,
        "payload": payload,
    }


def tool_call(
    source_seq: int,
    call_id: str,
    tool_name: str,
    *,
    session_id: str = ROOT_SESSION_ID,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = event(
        source_seq,
        "tool_call",
        payload={
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": arguments or {"task_id": TASK_ID},
        },
        session_id=session_id,
        status="running",
        event_id=f"call-{session_id}-{call_id}",
    )
    selected["call_id"] = call_id
    return selected


def tool_result(
    source_seq: int,
    call_id: str,
    tool_name: str,
    *,
    refs: list[dict[str, Any]] | None = None,
    session_id: str = ROOT_SESSION_ID,
    is_error: bool = False,
    status: str = "completed",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "call_id": call_id,
        "tool_name": tool_name,
        "result": {"ok": not is_error},
        "is_error": is_error,
    }
    if refs is not None:
        payload["object_refs"] = refs
    selected = event(
        source_seq,
        "tool_result",
        payload=payload,
        session_id=session_id,
        status=status,
        event_id=f"result-{session_id}-{call_id}",
    )
    selected["call_id"] = call_id
    return selected


def candidate(source_seq: int, suffix: str = "final") -> dict[str, Any]:
    return event(
        source_seq,
        "synthesis_candidate",
        payload={"text": f"candidate {suffix}"},
        category="synthesis_candidate",
        status="observed",
        event_id=f"candidate-{suffix}",
    )


def run_boundary(
    *,
    child_floor: tuple[str, int] | None = None,
) -> RunBoundary:
    floors = [(ROOT_SESSION_ID, 0)]
    if child_floor is not None:
        floors.append(child_floor)
    return RunBoundary(
        run_id=RUN_ID,
        queued_at_utc="2026-08-25T00:00:00+00:00",
        queue_event_seq=1,
        source_seq_floor_by_session=tuple(floors),
    )


def valid_ref(*, task_id: str = TASK_ID, ref_id: str = "search-1") -> dict[str, Any]:
    return {
        "type": "model_source_search",
        "id": ref_id,
        "task_id": task_id,
        "base_spec_revision": 1,
    }


class SynthesisEvidenceTests(unittest.TestCase):
    def evaluate(
        self,
        events: list[dict[str, Any]],
        *,
        boundary: RunBoundary | None = None,
        boundaries: tuple[RunBoundary, ...] | None = None,
        children: tuple[VerifiedChildBinding, ...] = (),
    ):
        return evaluate_synthesis_evidence(
            task_id=TASK_ID,
            team_id=TEAM_ID,
            root_session_id=ROOT_SESSION_ID,
            projector_revision=PROJECTOR_REVISION,
            events=events,
            runs=boundaries or (boundary or run_boundary(),),
            verified_children=children,
        )

    def test_get_task_is_observation_not_completion_evidence(self) -> None:
        events = [
            tool_call(1, "read-task", "model_harness_get_task"),
            tool_result(2, "read-task", "model_harness_get_task"),
            candidate(3),
        ]

        verdicts = self.evaluate(events)

        final = verdicts.event("candidate-final")
        self.assertIsNotNone(final)
        assert final is not None
        self.assertFalse(final.accepted)
        self.assertEqual(final.effective_type, "coordinator_note")
        self.assertIn("observation_only_tool", final.reason_codes)
        self.assertIsNone(verdicts.run(RUN_ID).accepted_candidate_event_id)  # type: ignore[union-attr]

    def test_valid_task_scoped_object_ref_accepts_and_digest_is_stable(self) -> None:
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
            ),
            candidate(3),
        ]
        before = deepcopy(events)

        forward = self.evaluate(events)
        reversed_input = self.evaluate(list(reversed(events)))

        final = forward.event("candidate-final")
        self.assertIsNotNone(final)
        assert final is not None
        self.assertTrue(final.accepted)
        self.assertEqual(final.effective_type, "final_synthesis")
        self.assertEqual(
            final.evidence_object_refs,
            (
                EvidenceObjectRef(
                    type="model_source_search",
                    id="search-1",
                    task_id=TASK_ID,
                    base_spec_revision=1,
                ),
            ),
        )
        self.assertEqual(
            final.evidence_digest,
            reversed_input.event("candidate-final").evidence_digest,  # type: ignore[union-attr]
        )
        self.assertEqual(events, before)
        self.assertEqual(
            forward.run(RUN_ID).accepted_candidate_event_id,  # type: ignore[union-attr]
            "candidate-final",
        )

    def test_exact_persistent_domain_object_can_support_synthesis(self) -> None:
        plan_digest = "c" * 64
        events = [
            tool_call(1, "plan", "model_harness_get_training_plan"),
            tool_result(
                2,
                "plan",
                "model_harness_get_training_plan",
                refs=[
                    {
                        "type": "training_plan",
                        "id": "plan-r2",
                        "task_id": TASK_ID,
                        "digest": plan_digest,
                        "revision": 2,
                    }
                ],
            ),
            candidate(3),
        ]

        final = self.evaluate(events).event("candidate-final")

        self.assertIsNotNone(final)
        assert final is not None
        self.assertTrue(final.accepted)
        self.assertEqual(final.evidence_object_refs[0].type, "training_plan")

    def test_run_scoped_ref_must_match_the_domain_tool_argument(self) -> None:
        events = [
            tool_call(
                1,
                "report",
                "model_harness_get_evaluation_report",
                arguments={"task_id": TASK_ID, "run_id": "training-run-1"},
            ),
            tool_result(
                2,
                "report",
                "model_harness_get_evaluation_report",
                refs=[
                    {
                        "type": "evaluation_report",
                        "id": "evaluation-1",
                        "task_id": TASK_ID,
                        "run_id": "training-run-2",
                        "digest": "d" * 64,
                    }
                ],
            ),
            candidate(3),
        ]

        final = self.evaluate(events).event("candidate-final")

        self.assertIsNotNone(final)
        assert final is not None
        self.assertFalse(final.accepted)
        self.assertIn("invalid_object_ref", final.reason_codes)

    def test_cross_task_object_ref_rejects_entire_tool_result(self) -> None:
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref(), valid_ref(task_id="another-task", ref_id="foreign")],
            ),
            candidate(3),
        ]

        verdict = self.evaluate(events).event("candidate-final")

        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertFalse(verdict.accepted)
        self.assertIn("cross_task_object_ref", verdict.reason_codes)
        self.assertEqual(verdict.evidence_object_refs, ())

    def test_failed_and_orphan_results_are_rejected(self) -> None:
        cases = {
            "failed": (
                [
                    tool_call(1, "search", "model_harness_search_model_sources"),
                    tool_result(
                        2,
                        "search",
                        "model_harness_search_model_sources",
                        refs=[valid_ref()],
                        is_error=True,
                        status="failed",
                    ),
                    candidate(3),
                ],
                "failed_tool_result",
            ),
            "orphan": (
                [
                    tool_result(
                        2,
                        "missing-call",
                        "model_harness_search_model_sources",
                        refs=[valid_ref()],
                    ),
                    candidate(3),
                ],
                "orphan_tool_result",
            ),
        }
        for name, (events, reason) in cases.items():
            with self.subTest(name=name):
                verdict = self.evaluate(events).event("candidate-final")
                self.assertIsNotNone(verdict)
                assert verdict is not None
                self.assertFalse(verdict.accepted)
                self.assertIn(reason, verdict.reason_codes)

    def test_historical_child_evidence_at_floor_is_rejected(self) -> None:
        child_session_id = "child-session"
        delegation_call = event(
            1,
            "delegation",
            payload={
                "call_id": "delegate-1",
                "tool_name": "research_source",
                "arguments": {"task_id": TASK_ID},
            },
            category="delegation",
            status="running",
            event_id="delegation-call",
        )
        delegation_call["call_id"] = "delegate-1"
        delegation_call["delegation_id"] = "delegate-1"
        delegation_result = event(
            2,
            "delegation",
            payload={
                "call_id": "delegate-1",
                "tool_name": "research_source",
                "result": {"sessionId": child_session_id},
                "dsh_session_id": child_session_id,
                "is_error": False,
            },
            category="delegation",
            status="running",
            event_id="delegation-result",
        )
        delegation_result["call_id"] = "delegate-1"
        delegation_result["delegation_id"] = "delegate-1"
        events = [
            delegation_call,
            delegation_result,
            tool_call(
                9,
                "child-search",
                "model_harness_search_model_sources",
                session_id=child_session_id,
            ),
            tool_result(
                10,
                "child-search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
                session_id=child_session_id,
            ),
            candidate(3),
        ]
        binding = VerifiedChildBinding(
            run_id=RUN_ID,
            delegation_call_id="delegate-1",
            parent_turn_id=f"{ROOT_SESSION_ID}:turn:1",
            parent_session_id=ROOT_SESSION_ID,
            child_session_id=child_session_id,
            created_in_run=False,
        )

        verdict = self.evaluate(
            events,
            boundary=run_boundary(child_floor=(child_session_id, 10)),
            children=(binding,),
        ).event("candidate-final")

        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertFalse(verdict.accepted)
        self.assertIn("historical_child_evidence", verdict.reason_codes)

    def test_only_latest_candidate_in_one_run_can_be_final(self) -> None:
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
            ),
            candidate(3, "early"),
            candidate(4, "latest"),
        ]

        verdicts = self.evaluate(events)

        accepted = [item for item in verdicts.event_verdicts if item.accepted]
        self.assertEqual([item.candidate_event_id for item in accepted], ["candidate-latest"])
        early = verdicts.event("candidate-early")
        self.assertIsNotNone(early)
        assert early is not None
        self.assertEqual(early.reason_codes, ("superseded_synthesis_candidate",))
        self.assertEqual(
            verdicts.run(RUN_ID).accepted_candidate_event_id,  # type: ignore[union-attr]
            "candidate-latest",
        )

    def test_unpaired_root_call_blocks_candidate_despite_other_valid_evidence(self) -> None:
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
            ),
            tool_call(3, "unfinished-read", "model_harness_get_task"),
            candidate(4),
        ]

        verdicts = self.evaluate(events)

        final = verdicts.event("candidate-final")
        run = verdicts.run(RUN_ID)
        self.assertIsNotNone(final)
        self.assertIsNotNone(run)
        assert final is not None and run is not None
        self.assertFalse(final.accepted)
        self.assertIn("unpaired_tool_call", final.reason_codes)
        self.assertIsNone(run.accepted_candidate_event_id)
        self.assertIn("unpaired_tool_call", run.reason_codes)

    def test_result_from_later_run_cannot_pair_earlier_run_call(self) -> None:
        later_run_id = "agent-run-2"
        first = run_boundary()
        second = RunBoundary(
            run_id=later_run_id,
            queued_at_utc="2026-08-25T00:01:00+00:00",
            queue_event_seq=20,
            source_seq_floor_by_session=((ROOT_SESSION_ID, 4),),
        )
        call = tool_call(
            2,
            "shared-call-id",
            "model_harness_search_model_sources",
        )
        later_result = tool_result(
            6,
            "shared-call-id",
            "model_harness_search_model_sources",
            refs=[valid_ref()],
        )
        later_result["agent_run_id"] = later_run_id
        events = [call, candidate(3), later_result]

        verdicts = self.evaluate(events, boundaries=(first, second))

        first_final = verdicts.event("candidate-final")
        first_run = verdicts.run(RUN_ID)
        later_run = verdicts.run(later_run_id)
        self.assertIsNotNone(first_final)
        self.assertIsNotNone(first_run)
        self.assertIsNotNone(later_run)
        assert first_final is not None and first_run is not None and later_run is not None
        self.assertFalse(first_final.accepted)
        self.assertIn("unpaired_tool_call", first_final.reason_codes)
        self.assertIn("unpaired_tool_call", first_run.reason_codes)
        self.assertIsNone(first_run.accepted_candidate_event_id)
        self.assertIsNone(later_run.accepted_candidate_event_id)

    def test_legacy_final_fixture_and_observed_session_id_remain_compatible(self) -> None:
        legacy = candidate(3)
        legacy["category"] = "final"
        legacy["type"] = "final_synthesis"
        legacy["event_type"] = "final_synthesis"
        legacy["observed_session_id"] = legacy.pop("session_id")
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
            ),
            legacy,
        ]

        verdict = self.evaluate(events).event("candidate-final")

        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.effective_type, "final_synthesis")

    def test_explicit_agent_run_id_must_match_boundary_derivation(self) -> None:
        events = [
            tool_call(1, "search", "model_harness_search_model_sources"),
            tool_result(
                2,
                "search",
                "model_harness_search_model_sources",
                refs=[valid_ref()],
            ),
            candidate(3),
        ]
        events[-1]["agent_run_id"] = "another-run"

        verdict = self.evaluate(events).event("candidate-final")

        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertFalse(verdict.accepted)
        self.assertIsNone(verdict.run_id)
        self.assertEqual(verdict.reason_codes, ("candidate_outside_run_boundary",))


if __name__ == "__main__":
    unittest.main()
