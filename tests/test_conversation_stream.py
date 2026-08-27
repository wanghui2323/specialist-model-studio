from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock
from typing import Any
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional server extra
    TestClient = None  # type: ignore[assignment,misc]

from model_harness.agent_bridge import AgentRuntimeError
from model_harness.conversation_payloads import project_conversation_objects
from model_harness.conversation_stream import TaskConversationStreamBroker
from model_harness.multi_agent import MultiAgentRuntimeError

try:
    from model_harness.server import create_app
except ImportError:  # pragma: no cover - optional training/server extras
    create_app = None  # type: ignore[assignment]


PROJECTOR_REVISION = "3.0"


def conversation_view(
    *,
    task_id: str,
    projector_revision: str = PROJECTOR_REVISION,
    sequence: int | None = None,
    running: bool = False,
    pending: list[dict[str, Any]] | None = None,
    work_items: list[dict[str, Any]] | None = None,
    background_actions: list[dict[str, Any]] | None = None,
    agent_response_running: bool | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    selected_pending = deepcopy(pending or [])
    action_running = running and not bool(selected_pending)
    if sequence is not None:
        event = {
            "event_id": f"event-{task_id}-{sequence}",
            "seq": sequence,
            "task_id": task_id,
            "source_key": f"fixture:{task_id}:{sequence}",
            "projector_revision": projector_revision,
            "event_type": "tool_call",
            "status": "running" if action_running else "completed",
            "payload": {"call_id": f"call-{sequence}"},
        }
        events.append(event)
        actions.append(
            {
                "action_id": f"action-{task_id}-{sequence}",
                "task_id": task_id,
                "status": "running" if action_running else "completed",
                "event_ids": [event["event_id"]],
            }
        )
    selected_background_actions = deepcopy(background_actions or [])
    background_action_running = any(
        item.get("running") is True
        for item in selected_background_actions
        if isinstance(item, dict)
    )
    requested_agent_response_running = (
        running
        if agent_response_running is None
        else agent_response_running
    )
    selected_agent_response_running = (
        requested_agent_response_running and not bool(selected_pending)
    )
    execution_running = selected_agent_response_running or background_action_running
    cancellation_pending = any(
        item.get("cancel_requested") is True and item.get("running") is True
        for item in selected_background_actions
        if isinstance(item, dict)
    )
    agent_runs: list[dict[str, Any]] = []
    if running or selected_pending:
        agent_runs.append(
            {
                "run_id": f"agent-run-{task_id}",
                "agent_turn_id": f"agent-turn-{task_id}",
                "status": (
                    "waiting_for_human"
                    if selected_pending
                    else "running"
                ),
            }
        )
        for action in actions:
            action["agent_run_id"] = agent_runs[0]["run_id"]
    object_projection = project_conversation_objects(
        task_id=task_id,
        agent_runs=agent_runs,
        actions=actions,
        background_actions=selected_background_actions,
        pending=selected_pending,
        agent_response_running=selected_agent_response_running,
        cancellation_pending=cancellation_pending,
        can_cancel=execution_running and not cancellation_pending,
    )
    return {
        "schema_version": "2.0",
        "projector_revision": projector_revision,
        "team_id": f"team-{task_id}",
        "session_id": f"session-{task_id}",
        "running": execution_running or bool(pending),
        "execution_running": execution_running,
        "agent_response_running": selected_agent_response_running,
        "background_action_running": background_action_running,
        "interaction_state": (
            "cancelling"
            if cancellation_pending
            else "waiting_for_human"
            if selected_pending
            else "working"
            if execution_running
            else "idle"
        ),
        "can_cancel_agent": execution_running and not cancellation_pending,
        "events": deepcopy(events),
        "items": deepcopy(events),
        "actions": actions,
        "work_item_schema_version": "1.0",
        "work_items": deepcopy(work_items or []),
        "background_actions": selected_background_actions,
        "agents": [],
        "delegations": [],
        "pending": selected_pending,
        "runs": deepcopy(agent_runs),
        "projection_health": "healthy",
        "projection_errors": [],
        "stream_health": {"status": "healthy"},
        "conversation_objects": object_projection,
        "agent_turns": object_projection["agent_turns"],
        "training_runs": object_projection["training_runs"],
        "human_checkpoints": object_projection["human_checkpoints"],
        "primary_attention": object_projection["primary_attention"],
        "risks": object_projection["risks"],
        "interaction_projection": object_projection[
            "interaction_projection"
        ],
    }


class FakeConversationRuntime:
    def __init__(self) -> None:
        self._lock = RLock()
        self._views: dict[str, dict[str, Any]] = {}
        self._calls: dict[str, int] = {}
        self._fail_after: dict[str, int] = {}
        self._failures: dict[str, AgentRuntimeError] = {}

    def set_view(self, task_id: str, view: dict[str, Any]) -> None:
        with self._lock:
            self._views[task_id] = deepcopy(view)

    def fail_after(
        self,
        task_id: str,
        calls: int,
        error: AgentRuntimeError | None = None,
    ) -> None:
        with self._lock:
            self._fail_after[task_id] = calls
            self._failures[task_id] = error or AgentRuntimeError(
                "fixture runtime disconnected"
            )

    def call_count(self, task_id: str) -> int:
        with self._lock:
            return self._calls.get(task_id, 0)

    def recover(self, task_id: str) -> None:
        with self._lock:
            self._fail_after.pop(task_id, None)
            self._failures.pop(task_id, None)

    def conversation(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            count = self._calls.get(task_id, 0) + 1
            self._calls[task_id] = count
            if count > self._fail_after.get(task_id, 1_000_000):
                raise self._failures[task_id]
            return deepcopy(self._views[task_id])


def parse_frame(frame: bytes) -> dict[str, Any]:
    lines = frame.decode("utf-8").strip().splitlines()
    fields: dict[str, str] = {}
    for line in lines:
        key, value = line.split(":", 1)
        fields[key] = value.strip()
    data = json.loads(fields["data"])
    return {
        "id": fields["id"],
        "event": fields["event"],
        "data": data,
    }


def parse_frames(body: bytes) -> list[dict[str, Any]]:
    return [
        parse_frame(f"{block}\n\n".encode("utf-8"))
        for block in body.decode("utf-8").split("\n\n")
        if block.strip()
    ]


async def next_frame(stream: Any, timeout: float = 1.0) -> dict[str, Any]:
    return parse_frame(await asyncio.wait_for(anext(stream), timeout=timeout))


async def next_event(stream: Any, selected: str) -> dict[str, Any]:
    for _attempt in range(20):
        record = await next_frame(stream)
        if record["event"] == selected:
            return record
    raise AssertionError(f"stream did not emit {selected}")


class ConversationStreamBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runtime = FakeConversationRuntime()
        self.broker = TaskConversationStreamBroker(
            self.runtime,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.025,
            history_limit=8,
        )

    async def asyncTearDown(self) -> None:
        await self.broker.close()

    async def test_snapshot_delta_state_and_actionless_heartbeat(self) -> None:
        task_id = "task-stream-contract"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot = await next_frame(stream)
        self.assertEqual(snapshot["event"], "snapshot")
        self.assertEqual(snapshot["id"], snapshot["data"]["cursor_token"])
        self.assertEqual(snapshot["data"]["task_id"], task_id)
        self.assertEqual(
            snapshot["data"]["projector_revision"], PROJECTOR_REVISION
        )

        pending = [
            {
                "kind": "question",
                "rpc_id": "question-rpc-1",
                "questions": [{"question": "确认验收指标？"}],
            }
        ]
        self.runtime.set_view(
            task_id,
            conversation_view(
                task_id=task_id,
                sequence=1,
                running=True,
                pending=pending,
            ),
        )
        delta = await next_event(stream, "delta")
        state = await next_event(stream, "state")

        self.assertEqual(delta["data"]["events"][0]["event_id"], f"event-{task_id}-1")
        self.assertEqual(state["data"]["pending"], pending)
        self.assertFalse(state["data"]["execution_running"])
        self.assertFalse(state["data"]["agent_response_running"])
        self.assertEqual(state["data"]["interaction_state"], "waiting_for_human")
        self.assertFalse(state["data"]["can_cancel_agent"])
        self.assertEqual(
            state["data"]["interaction_projection"]["phase"],
            "waiting_question",
        )
        self.assertEqual(
            state["data"]["active_event"]["active_type"],
            "human_checkpoint",
        )
        self.assertEqual(state["data"]["active_event"]["rpc_id"], "question-rpc-1")
        self.assertEqual(
            state["data"]["active_event"]["phase"],
            "waiting_question",
        )

        self.runtime.set_view(
            task_id,
            conversation_view(task_id=task_id, sequence=1),
        )
        resolved_delta = await next_event(stream, "delta")
        resolved_state = await next_event(stream, "state")
        self.assertEqual(resolved_state["data"]["pending"], [])
        self.assertIsNone(resolved_state["data"]["active_event"])
        self.assertFalse(resolved_state["data"]["execution_running"])
        self.assertEqual(resolved_state["data"]["interaction_state"], "idle")
        self.assertFalse(resolved_state["data"]["can_cancel_agent"])

        heartbeat = await next_event(stream, "heartbeat")
        self.assertIn("server_time", heartbeat["data"])
        for action_field in ("events", "items", "actions", "active_event"):
            self.assertNotIn(action_field, heartbeat["data"])
        cursors = [
            snapshot["data"]["cursor"],
            delta["data"]["cursor"],
            state["data"]["cursor"],
            resolved_delta["data"]["cursor"],
            resolved_state["data"]["cursor"],
            heartbeat["data"]["cursor"],
        ]
        self.assertEqual(cursors, sorted(set(cursors)))

        await stream.aclose()
        await asyncio.sleep(0)
        diagnostics = self.broker.diagnostics()
        self.assertEqual(diagnostics["active_producers"], 0)
        self.assertEqual(diagnostics["subscribers"][task_id], 0)

    async def test_agent_work_items_are_live_and_removal_forces_snapshot(self) -> None:
        task_id = "task-agent-work-stream"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        initial = await next_frame(stream)
        self.assertEqual(initial["event"], "snapshot")
        self.assertEqual(initial["data"]["conversation"]["work_items"], [])

        active_work = {
            "work_item_id": "agent-work:one",
            "task_id": task_id,
            "delegation_id": "delegate-one",
            "status": "active",
            "actions": [],
            "object_refs": [],
        }
        self.runtime.set_view(
            task_id,
            conversation_view(task_id=task_id, work_items=[active_work]),
        )
        active_delta = await next_event(stream, "delta")
        active_state = await next_event(stream, "state")
        self.assertEqual(active_delta["data"]["work_items"], [active_work])
        self.assertEqual(active_state["data"]["work_items"], [active_work])

        completed_work = {**active_work, "status": "completed"}
        self.runtime.set_view(
            task_id,
            conversation_view(task_id=task_id, work_items=[completed_work]),
        )
        completed_delta = await next_event(stream, "delta")
        completed_state = await next_event(stream, "state")
        self.assertEqual(
            completed_delta["data"]["work_items"],
            [completed_work],
        )
        self.assertEqual(
            completed_state["data"]["work_items"],
            [completed_work],
        )

        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        removal = await next_event(stream, "snapshot")
        self.assertEqual(removal["data"]["conversation"]["work_items"], [])
        await stream.aclose()

    async def test_agent_completion_remains_distinct_from_running_background_action(self) -> None:
        task_id = "task-background-action-stream"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        await next_frame(stream)

        background_action = {
            "action_id": "training-run:run-one",
            "action_type": "training_run",
            "task_id": task_id,
            "run_id": "run-one",
            "status": "cancel_requested",
            "domain_status": "training",
            "running": True,
            "worker_running": True,
            "cancel_requested": True,
        }
        self.runtime.set_view(
            task_id,
            conversation_view(
                task_id=task_id,
                agent_response_running=False,
                background_actions=[background_action],
                pending=[
                    {
                        "kind": "question",
                        "rpc_id": "question-stale-during-cancel",
                    }
                ],
            ),
        )

        delta = await next_event(stream, "delta")
        state = await next_event(stream, "state")
        self.assertEqual(delta["data"]["background_actions"], [background_action])
        self.assertFalse(state["data"]["agent_response_running"])
        self.assertTrue(state["data"]["background_action_running"])
        self.assertTrue(state["data"]["execution_running"])
        self.assertEqual(
            state["data"]["interaction_projection"]["phase"],
            "stopping",
        )
        self.assertEqual(
            state["data"]["active_event"]["active_type"],
            "cancellation",
        )
        self.assertEqual(
            state["data"]["active_event"]["training_run_id"],
            "run-one",
        )
        self.assertFalse(state["data"]["can_cancel_agent"])

        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        settled = await next_event(stream, "snapshot")
        conversation = settled["data"]["conversation"]
        self.assertEqual(conversation["background_actions"], [])
        self.assertFalse(conversation["execution_running"])
        await stream.aclose()

    async def test_last_cursor_replays_delta_and_gap_or_revision_gets_snapshot(self) -> None:
        task_id = "task-resume"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        initial_stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        initial = await next_frame(initial_stream)
        initial_cursor = initial["data"]["cursor"]
        await initial_stream.aclose()

        sequence_one = conversation_view(task_id=task_id, sequence=1)
        self.runtime.set_view(task_id, sequence_one)
        resumed = self.broker.stream(
            task_id,
            after_seq=initial_cursor,
            expected_projector_revision=PROJECTOR_REVISION,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        exact_delta = await next_frame(resumed)
        self.assertEqual(exact_delta["event"], "delta")
        self.assertGreater(exact_delta["data"]["cursor"], initial_cursor)
        await resumed.aclose()

        sequence_two = conversation_view(task_id=task_id, sequence=2)
        for collection in ("events", "items", "actions"):
            sequence_two[collection] = [
                *deepcopy(sequence_one[collection]),
                *sequence_two[collection],
            ]
        self.runtime.set_view(task_id, sequence_two)
        token_resumed = self.broker.stream(
            task_id,
            last_event_id=exact_delta["id"],
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        token_delta = await next_frame(token_resumed)
        self.assertEqual(token_delta["event"], "delta")
        self.assertEqual(
            token_delta["data"]["events"][0]["event_id"],
            f"event-{task_id}-2",
        )
        await token_resumed.aclose()

        jumped = self.broker.stream(
            task_id,
            after_seq=9_999,
            expected_projector_revision=PROJECTOR_REVISION,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        gap_snapshot = await next_frame(jumped)
        self.assertEqual(gap_snapshot["event"], "snapshot")
        self.assertEqual(
            gap_snapshot["data"]["conversation"]["events"][-1]["event_id"],
            f"event-{task_id}-2",
        )
        await jumped.aclose()

        self.runtime.set_view(
            task_id,
            conversation_view(
                task_id=task_id,
                projector_revision="4.0",
                sequence=2,
            ),
        )
        revision_stream = self.broker.stream(
            task_id,
            last_event_id=gap_snapshot["id"],
            runtime_projector_revision="4.0",
        )
        revision_snapshot = await next_event(revision_stream, "snapshot")
        self.assertEqual(revision_snapshot["data"]["projector_revision"], "4.0")
        self.assertEqual(
            revision_snapshot["data"]["conversation"]["events"][0]["event_id"],
            f"event-{task_id}-2",
        )
        await revision_stream.aclose()

    async def test_stream_health_is_fail_closed_until_event_downlink_is_healthy(self) -> None:
        task_id = "task-stream-health"
        connecting = conversation_view(task_id=task_id)
        connecting["stream_health"] = {
            "status": "connecting",
            "consecutive_failures": 1,
        }
        self.runtime.set_view(task_id, connecting)
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot = await next_frame(stream)
        self.assertEqual(snapshot["event"], "snapshot")
        self.assertEqual(
            snapshot["data"]["conversation"]["projection_health"],
            "observation_degraded",
        )
        self.assertEqual(
            snapshot["data"]["conversation"]["interaction_projection"][
                "phase"
            ],
            "observation_degraded",
        )
        self.assertFalse(
            snapshot["data"]["conversation"]["interaction_projection"][
                "can_cancel"
            ]
        )

        healthy = conversation_view(task_id=task_id)
        healthy["stream_health"] = {
            "status": "healthy",
            "consecutive_failures": 0,
        }
        self.runtime.set_view(task_id, healthy)
        recovered = await next_event(stream, "state")
        self.assertEqual(recovered["data"]["projection_health"], "healthy")
        self.assertEqual(recovered["data"]["stream_health"]["status"], "healthy")
        self.assertEqual(
            recovered["data"]["interaction_projection"]["phase"],
            "idle",
        )
        await stream.aclose()

    async def test_projection_identity_change_or_removal_reconciles_with_snapshot(self) -> None:
        task_id = "task-identity-reconciliation"
        empty = conversation_view(task_id=task_id)
        empty["team_id"] = None
        empty["session_id"] = None
        self.runtime.set_view(task_id, empty)
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        initial = await next_frame(stream)
        self.assertEqual(initial["event"], "snapshot")
        self.assertIsNone(initial["data"]["conversation"]["team_id"])

        established = conversation_view(task_id=task_id, sequence=1)
        self.runtime.set_view(task_id, established)
        identity_snapshot = await next_event(stream, "snapshot")
        self.assertEqual(
            identity_snapshot["data"]["conversation"]["team_id"],
            f"team-{task_id}",
        )
        self.assertEqual(
            identity_snapshot["data"]["conversation"]["session_id"],
            f"session-{task_id}",
        )
        self.assertEqual(
            identity_snapshot["data"]["conversation"]["events"][0]["event_id"],
            f"event-{task_id}-1",
        )

        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        removal_snapshot = await next_event(stream, "snapshot")
        self.assertEqual(removal_snapshot["data"]["conversation"]["events"], [])
        self.assertEqual(removal_snapshot["data"]["conversation"]["items"], [])
        self.assertEqual(removal_snapshot["data"]["conversation"]["actions"], [])
        await stream.aclose()

    async def test_bounded_history_reconciles_an_old_cursor_with_snapshot(self) -> None:
        task_id = "task-old-gap"
        runtime = FakeConversationRuntime()
        runtime.set_view(task_id, conversation_view(task_id=task_id))
        broker = TaskConversationStreamBroker(
            runtime,
            poll_interval_seconds=0.002,
            heartbeat_interval_seconds=0.004,
            history_limit=3,
        )
        try:
            stream = broker.stream(
                task_id,
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            first = await next_frame(stream)
            accumulated = conversation_view(task_id=task_id)
            for sequence in range(1, 5):
                latest = conversation_view(task_id=task_id, sequence=sequence)
                for collection in ("events", "items", "actions"):
                    accumulated[collection].extend(latest[collection])
                runtime.set_view(task_id, accumulated)
                await next_event(stream, "delta")
            await stream.aclose()
            self.assertLessEqual(
                broker.diagnostics()["history_sizes"][task_id],
                4,
            )

            recovered = broker.stream(
                task_id,
                after_seq=first["data"]["cursor"],
                expected_projector_revision=PROJECTOR_REVISION,
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            snapshot = await next_frame(recovered)
            self.assertEqual(snapshot["event"], "snapshot")
            self.assertGreater(
                snapshot["data"]["cursor"],
                first["data"]["cursor"],
            )
            await recovered.aclose()
        finally:
            await broker.close()

    async def test_heartbeats_do_not_evict_recoverable_domain_cursor(self) -> None:
        task_id = "task-heartbeat-history"
        runtime = FakeConversationRuntime()
        runtime.set_view(task_id, conversation_view(task_id=task_id))
        broker = TaskConversationStreamBroker(
            runtime,
            poll_interval_seconds=0.001,
            heartbeat_interval_seconds=0.002,
            history_limit=3,
        )
        try:
            stream = broker.stream(
                task_id,
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            initial = await next_frame(stream)
            for _attempt in range(12):
                await next_event(stream, "heartbeat")
            self.assertLessEqual(broker.diagnostics()["history_sizes"][task_id], 4)
            await stream.aclose()

            runtime.set_view(
                task_id,
                conversation_view(task_id=task_id, sequence=1),
            )
            resumed = broker.stream(
                task_id,
                last_event_id=initial["id"],
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            delta = await next_event(resumed, "delta")
            self.assertEqual(
                delta["data"]["events"][0]["event_id"],
                f"event-{task_id}-1",
            )
            await resumed.aclose()
        finally:
            await broker.close()

    async def test_subscribers_share_one_task_producer_and_tasks_stay_isolated(self) -> None:
        task_a = "task-a"
        task_b = "task-b"
        self.runtime.set_view(
            task_a,
            conversation_view(task_id=task_a, sequence=1),
        )
        self.runtime.set_view(
            task_b,
            conversation_view(task_id=task_b, sequence=7),
        )
        first_a = self.broker.stream(
            task_a,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        second_a = self.broker.stream(
            task_a,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        first_b = self.broker.stream(
            task_b,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot_a, snapshot_a_again, snapshot_b = await asyncio.gather(
            next_frame(first_a),
            next_frame(second_a),
            next_frame(first_b),
        )
        self.assertEqual(snapshot_a["data"]["task_id"], task_a)
        self.assertEqual(snapshot_a_again["data"]["task_id"], task_a)
        self.assertEqual(snapshot_b["data"]["task_id"], task_b)
        self.assertEqual(
            snapshot_a["data"]["conversation"]["events"][0]["task_id"],
            task_a,
        )
        self.assertEqual(
            snapshot_b["data"]["conversation"]["events"][0]["task_id"],
            task_b,
        )
        diagnostics = self.broker.diagnostics()
        self.assertEqual(diagnostics["active_producers"], 2)
        self.assertEqual(diagnostics["subscribers"][task_a], 2)
        self.assertEqual(diagnostics["subscribers"][task_b], 1)

        await first_a.aclose()
        await second_a.aclose()
        await asyncio.sleep(0)
        diagnostics = self.broker.diagnostics()
        self.assertEqual(diagnostics["active_producers"], 1)
        self.assertEqual(diagnostics["subscribers"][task_a], 0)
        self.assertEqual(diagnostics["subscribers"][task_b], 1)
        await first_b.aclose()

    async def test_cursor_token_is_owned_by_task_and_broker_epoch(self) -> None:
        task_a = "task-token-a"
        task_b = "task-token-b"
        self.runtime.set_view(task_a, conversation_view(task_id=task_a))
        self.runtime.set_view(task_b, conversation_view(task_id=task_b))

        stream_a = self.broker.stream(
            task_a,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot_a = await next_frame(stream_a)
        await stream_a.aclose()

        cross_task = self.broker.stream(
            task_b,
            last_event_id=snapshot_a["id"],
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot_b = await next_frame(cross_task)
        self.assertEqual(snapshot_b["event"], "snapshot")
        self.assertEqual(snapshot_b["data"]["task_id"], task_b)
        self.assertNotEqual(
            snapshot_b["data"]["stream_id"],
            snapshot_a["data"]["stream_id"],
        )
        await cross_task.aclose()

        replacement = TaskConversationStreamBroker(
            self.runtime,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.025,
        )
        try:
            restarted = replacement.stream(
                task_a,
                last_event_id=snapshot_a["id"],
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            restarted_snapshot = await next_frame(restarted)
            self.assertEqual(restarted_snapshot["event"], "snapshot")
            self.assertNotEqual(
                restarted_snapshot["data"]["stream_id"],
                snapshot_a["data"]["stream_id"],
            )
            await restarted.aclose()
        finally:
            await replacement.close()

    async def test_blocked_projection_disconnect_does_not_start_second_producer(self) -> None:
        task_id = "task-blocked-projection"

        class BlockingRuntime:
            def __init__(self) -> None:
                self.entered = Event()
                self.release = Event()
                self.lock = RLock()
                self.active = 0
                self.max_active = 0

            def conversation(self, selected_task_id: str) -> dict[str, Any]:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                self.entered.set()
                self.release.wait(timeout=2.0)
                with self.lock:
                    self.active -= 1
                return conversation_view(task_id=selected_task_id)

        runtime = BlockingRuntime()
        broker = TaskConversationStreamBroker(
            runtime,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.025,
        )
        try:
            first_stream = broker.stream(
                task_id,
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            first_consumer = asyncio.create_task(anext(first_stream))
            await asyncio.wait_for(asyncio.to_thread(runtime.entered.wait), timeout=1.0)
            first_consumer.cancel()
            await asyncio.gather(first_consumer, return_exceptions=True)
            await first_stream.aclose()

            second_stream = broker.stream(
                task_id,
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            second_consumer = asyncio.create_task(next_frame(second_stream))
            await asyncio.sleep(0.02)
            self.assertEqual(broker.diagnostics()["active_producers"], 1)
            self.assertEqual(runtime.max_active, 1)

            runtime.release.set()
            snapshot = await asyncio.wait_for(second_consumer, timeout=1.0)
            self.assertEqual(snapshot["event"], "snapshot")
            self.assertEqual(runtime.max_active, 1)
            await second_stream.aclose()
            await asyncio.sleep(0.02)
            self.assertEqual(broker.diagnostics()["active_producers"], 0)
        finally:
            runtime.release.set()
            await broker.close()

    async def test_close_waits_for_cancelled_projection_worker(self) -> None:
        task_id = "task-cancelled-get"

        class BlockingRuntime:
            def __init__(self) -> None:
                self.entered = Event()
                self.release = Event()
                self.calls = 0

            def conversation(self, selected_task_id: str) -> dict[str, Any]:
                self.calls += 1
                self.entered.set()
                self.release.wait(timeout=2.0)
                return conversation_view(task_id=selected_task_id)

        runtime = BlockingRuntime()
        broker = TaskConversationStreamBroker(runtime)
        request = asyncio.create_task(broker.conversation(task_id))
        await asyncio.wait_for(asyncio.to_thread(runtime.entered.wait), timeout=1.0)
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)

        close_task = asyncio.create_task(broker.close())
        await asyncio.sleep(0.02)
        self.assertFalse(close_task.done())

        runtime.release.set()
        await asyncio.wait_for(close_task, timeout=1.0)
        self.assertEqual(runtime.calls, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await broker.conversation(task_id)
        self.assertEqual(runtime.calls, 1)

    async def test_cancelled_get_worker_is_adopted_by_next_refresh(self) -> None:
        task_id = "task-adopt-cancelled-get"

        class BlockingRuntime:
            def __init__(self) -> None:
                self.entered = Event()
                self.release = Event()
                self.lock = RLock()
                self.calls = 0
                self.active = 0
                self.max_active = 0

            def conversation(self, selected_task_id: str) -> dict[str, Any]:
                with self.lock:
                    self.calls += 1
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                self.entered.set()
                self.release.wait(timeout=2.0)
                with self.lock:
                    self.active -= 1
                return conversation_view(task_id=selected_task_id)

        runtime = BlockingRuntime()
        broker = TaskConversationStreamBroker(runtime)
        try:
            first = asyncio.create_task(broker.conversation(task_id))
            await asyncio.wait_for(
                asyncio.to_thread(runtime.entered.wait),
                timeout=1.0,
            )
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)

            second = asyncio.create_task(broker.conversation(task_id))
            await asyncio.sleep(0.02)
            self.assertFalse(second.done())
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(runtime.max_active, 1)

            runtime.release.set()
            recovered = await asyncio.wait_for(second, timeout=1.0)
            self.assertEqual(recovered["team_id"], f"team-{task_id}")
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(runtime.max_active, 1)
        finally:
            runtime.release.set()
            await broker.close()

    async def test_cancelled_get_worker_pins_hub_capacity_until_it_finishes(self) -> None:
        task_a = "task-capacity-worker-a"
        task_b = "task-capacity-worker-b"

        class BlockingRuntime:
            def __init__(self) -> None:
                self.entered = Event()
                self.release = Event()
                self.lock = RLock()
                self.active = 0
                self.max_active = 0

            def conversation(self, selected_task_id: str) -> dict[str, Any]:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                self.entered.set()
                if selected_task_id == task_a:
                    self.release.wait(timeout=2.0)
                with self.lock:
                    self.active -= 1
                return conversation_view(task_id=selected_task_id)

        runtime = BlockingRuntime()
        broker = TaskConversationStreamBroker(runtime, max_task_hubs=1)
        try:
            first = asyncio.create_task(broker.conversation(task_a))
            await asyncio.wait_for(
                asyncio.to_thread(runtime.entered.wait),
                timeout=1.0,
            )
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)

            self.assertEqual(broker.diagnostics()["active_projections"], 1)
            with self.assertRaisesRegex(RuntimeError, "capacity"):
                broker.reserve(task_b)

            runtime.release.set()
            for _attempt in range(20):
                if broker.diagnostics()["active_projections"] == 0:
                    break
                await asyncio.sleep(0.005)
            second = await broker.conversation(task_b)
            self.assertEqual(second["team_id"], f"team-{task_b}")
            self.assertEqual(runtime.max_active, 1)
        finally:
            runtime.release.set()
            await broker.close()

    async def test_active_task_capacity_fails_closed_then_reuses_idle_slot(self) -> None:
        runtime = FakeConversationRuntime()
        runtime.set_view("capacity-a", conversation_view(task_id="capacity-a"))
        runtime.set_view("capacity-b", conversation_view(task_id="capacity-b"))
        broker = TaskConversationStreamBroker(
            runtime,
            poll_interval_seconds=0.005,
            heartbeat_interval_seconds=0.025,
            max_task_hubs=1,
        )
        try:
            preflight_a = broker.reserve("capacity-a")
            self.assertEqual(
                broker.diagnostics()["reservations"]["capacity-a"],
                1,
            )
            with self.assertRaisesRegex(RuntimeError, "capacity"):
                broker.reserve("capacity-b")
            preflight_a.release()

            stream_a = broker.stream(
                "capacity-a",
                runtime_projector_revision=PROJECTOR_REVISION,
            )
            await next_frame(stream_a)
            with self.assertRaisesRegex(RuntimeError, "capacity"):
                broker.reserve("capacity-b")
            await stream_a.aclose()
            await asyncio.sleep(0.02)
            reservation_b = broker.reserve("capacity-b")
            reservation_b.release()
            self.assertEqual(broker.diagnostics()["task_hubs"], 1)
        finally:
            await broker.close()

    async def test_projection_mutex_serializes_one_task_but_allows_two_tasks(self) -> None:
        class MeasuringRuntime:
            def __init__(self) -> None:
                self.lock = RLock()
                self.active_by_task: dict[str, int] = {}
                self.max_by_task: dict[str, int] = {}
                self.active_total = 0
                self.max_total = 0

            def reset_peaks(self) -> None:
                with self.lock:
                    self.max_by_task = {}
                    self.max_total = 0

            def conversation(self, task_id: str) -> dict[str, Any]:
                with self.lock:
                    active = self.active_by_task.get(task_id, 0) + 1
                    self.active_by_task[task_id] = active
                    self.max_by_task[task_id] = max(
                        self.max_by_task.get(task_id, 0), active
                    )
                    self.active_total += 1
                    self.max_total = max(self.max_total, self.active_total)
                time.sleep(0.03)
                with self.lock:
                    self.active_by_task[task_id] -= 1
                    self.active_total -= 1
                return conversation_view(task_id=task_id)

        runtime = MeasuringRuntime()
        broker = TaskConversationStreamBroker(runtime)
        try:
            await asyncio.gather(
                broker.conversation("projection-a"),
                broker.conversation("projection-a"),
            )
            self.assertEqual(runtime.max_by_task["projection-a"], 1)
            self.assertEqual(runtime.max_total, 1)

            runtime.reset_peaks()
            await asyncio.gather(
                broker.conversation("projection-a"),
                broker.conversation("projection-b"),
            )
            self.assertEqual(runtime.max_by_task["projection-a"], 1)
            self.assertEqual(runtime.max_by_task["projection-b"], 1)
            self.assertEqual(runtime.max_total, 2)
        finally:
            await broker.close()

    async def test_midstream_runtime_failure_is_typed_and_closes(self) -> None:
        task_id = "task-midstream-error"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        self.runtime.fail_after(task_id, calls=1)
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        snapshot = await next_frame(stream)
        error = await next_event(stream, "error")
        self.assertEqual(snapshot["event"], "snapshot")
        self.assertEqual(error["data"]["code"], "conversation_runtime_unavailable")
        self.assertTrue(error["data"]["recoverable"])
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1.0)
        await asyncio.sleep(0)
        self.assertEqual(self.broker.diagnostics()["active_producers"], 0)

        self.runtime.recover(task_id)
        recovered_stream = self.broker.stream(
            task_id,
            last_event_id=error["id"],
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        recovered = await next_frame(recovered_stream)
        self.assertEqual(recovered["event"], "snapshot")
        self.assertNotEqual(
            recovered["data"]["stream_id"],
            error["data"]["stream_id"],
        )
        await recovered_stream.aclose()

    async def test_midstream_projection_integrity_failure_is_terminal(self) -> None:
        task_id = "task-midstream-integrity"
        self.runtime.set_view(task_id, conversation_view(task_id=task_id))
        self.runtime.fail_after(
            task_id,
            calls=1,
            error=MultiAgentRuntimeError("Agent Team 映射损坏"),
        )
        stream = self.broker.stream(
            task_id,
            runtime_projector_revision=PROJECTOR_REVISION,
        )
        await next_frame(stream)
        error = await next_event(stream, "error")
        self.assertEqual(
            error["data"]["code"],
            "conversation_projection_integrity_failed",
        )
        self.assertFalse(error["data"]["recoverable"])
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1.0)


@unittest.skipIf(
    TestClient is None or create_app is None,
    "server or training extras are not installed",
)
class ConversationStreamHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.temp_dir.name) / "runs"
        self.app = create_app(runs_dir=self.runs_dir)
        self.runtime = self.app.state.conversation_runtime
        self.streams = self.app.state.conversation_streams
        self.streams.poll_interval_seconds = 0.005
        self.streams.heartbeat_interval_seconds = 0.5

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_task(self, client: Any, name: str = "SSE contract") -> str:
        response = client.post(
            "/tasks",
            json={"name": name, "business_goal": "verify task-owned SSE"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["task"]["task_id"])

    def test_task_404_and_preconnect_runtime_unavailable_503(self) -> None:
        with (
            patch.object(self.runtime, "start"),
            patch.object(self.runtime, "stop"),
            patch.object(
                self.runtime,
                "runtime_status",
                return_value={
                    "available": False,
                    "conversation_projector_revision": PROJECTOR_REVISION,
                },
            ) as runtime_status,
            TestClient(self.app) as client,  # type: ignore[misc]
        ):
            missing = client.get("/tasks/missing-task/conversation/stream")
            self.assertEqual(missing.status_code, 404, missing.text)
            runtime_status.assert_not_called()

            task_id = self._create_task(client)
            unavailable = client.get(f"/tasks/{task_id}/conversation/stream")
            self.assertEqual(unavailable.status_code, 503, unavailable.text)
            self.assertEqual(runtime_status.call_count, 1)

    def test_http_wire_headers_last_event_id_and_midstream_error(self) -> None:
        task_id_holder: dict[str, str] = {}

        def first_then_fail(task_id: str) -> dict[str, Any]:
            calls = first_then_fail.calls
            first_then_fail.calls += 1
            if calls:
                raise AgentRuntimeError("fixture disconnected")
            return conversation_view(task_id=task_id)

        first_then_fail.calls = 0
        with (
            patch.object(self.runtime, "start"),
            patch.object(self.runtime, "stop"),
            patch.object(
                self.runtime,
                "runtime_status",
                return_value={
                    "available": True,
                    "conversation_projector_revision": PROJECTOR_REVISION,
                },
            ),
            patch.object(self.runtime, "conversation", side_effect=first_then_fail),
            TestClient(self.app) as client,  # type: ignore[misc]
        ):
            task_id_holder["task_id"] = self._create_task(client)
            response = client.get(
                f"/tasks/{task_id_holder['task_id']}/conversation/stream?after_seq=3",
                headers={"Last-Event-ID": f"{'0' * 32}:{'0' * 12}:999"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(
                response.headers["content-type"].startswith("text/event-stream")
            )
            self.assertEqual(
                response.headers["cache-control"],
                "no-cache, no-transform",
            )
            self.assertEqual(response.headers["x-accel-buffering"], "no")
            records = parse_frames(response.content)
            self.assertEqual([record["event"] for record in records], ["snapshot", "error"])
            self.assertEqual(records[0]["id"], records[0]["data"]["cursor_token"])
            self.assertEqual(
                records[1]["data"]["code"],
                "conversation_runtime_unavailable",
            )

    def test_cursor_inputs_reject_malformed_header_or_negative_sequence(self) -> None:
        with (
            patch.object(self.runtime, "start"),
            patch.object(self.runtime, "stop"),
            patch.object(
                self.runtime,
                "runtime_status",
                return_value={
                    "available": True,
                    "conversation_projector_revision": PROJECTOR_REVISION,
                },
            ),
            TestClient(self.app) as client,  # type: ignore[misc]
        ):
            task_id = self._create_task(client)
            malformed = client.get(
                f"/tasks/{task_id}/conversation/stream",
                headers={"Last-Event-ID": "not-a-cursor"},
            )
            self.assertEqual(malformed.status_code, 422, malformed.text)
            negative = client.get(
                f"/tasks/{task_id}/conversation/stream?after_seq=-1"
            )
            self.assertEqual(negative.status_code, 422, negative.text)


if __name__ == "__main__":
    unittest.main()
