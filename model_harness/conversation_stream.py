from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence
from uuid import uuid4

from .agent_bridge import AgentRuntimeError
from .multi_agent import stream_observation_degraded


CONVERSATION_STREAM_SCHEMA_VERSION = "1.0"
CONVERSATION_STREAM_EVENTS = frozenset(
    {"snapshot", "delta", "state", "error", "heartbeat"}
)


class ConversationStreamRuntime(Protocol):
    def conversation(self, task_id: str) -> dict[str, Any]: ...


class ConversationStreamCapacityError(RuntimeError):
    """Raised before connect when every bounded task broadcaster is active."""


@dataclass(frozen=True)
class ConversationStreamCursor:
    stream_id: str
    projector_key: str
    sequence: int


def _projector_key(projector_revision: str) -> str:
    return hashlib.sha256(projector_revision.encode("utf-8")).hexdigest()[:12]


def encode_stream_cursor(
    *,
    stream_id: str,
    projector_revision: str,
    sequence: int,
) -> str:
    return f"{stream_id}:{_projector_key(projector_revision)}:{sequence}"


def parse_stream_cursor(value: str) -> ConversationStreamCursor:
    selected = str(value or "").strip()
    parts = selected.split(":")
    if (
        len(parts) != 3
        or len(parts[0]) != 32
        or any(character not in "0123456789abcdef" for character in parts[0])
        or len(parts[1]) != 12
        or any(character not in "0123456789abcdef" for character in parts[1])
        or not parts[2].isdecimal()
    ):
        raise ValueError("Last-Event-ID is not a valid conversation cursor")
    return ConversationStreamCursor(
        stream_id=parts[0],
        projector_key=parts[1],
        sequence=int(parts[2]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _projector_revision(
    conversation: Mapping[str, Any],
    fallback: str | None,
) -> str:
    explicit = conversation.get("projector_revision")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for collection_name in ("events", "items"):
        values = conversation.get(collection_name)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for value in reversed(values):
            if not isinstance(value, Mapping):
                continue
            selected = value.get("projector_revision")
            if isinstance(selected, str) and selected.strip():
                return selected.strip()
    return fallback or "unknown"


def _entry_key(value: Mapping[str, Any]) -> str:
    for field in (
        "event_id",
        "action_id",
        "work_item_id",
        "source_key",
        "delegation_id",
        "rpc_id",
        "run_id",
    ):
        selected = value.get(field)
        if isinstance(selected, str) and selected:
            return f"{field}:{selected}"
    sequence = value.get("seq")
    if isinstance(sequence, int) and not isinstance(sequence, bool):
        return f"seq:{sequence}"
    return f"digest:{_digest(value)}"


def _changed_entries(before: Any, after: Any) -> list[dict[str, Any]]:
    previous = {
        _entry_key(value): _canonical_json(value)
        for value in before or []
        if isinstance(value, Mapping)
    }
    changed: list[dict[str, Any]] = []
    for value in after or []:
        if not isinstance(value, Mapping):
            continue
        key = _entry_key(value)
        if previous.get(key) != _canonical_json(value):
            changed.append(deepcopy(dict(value)))
    return changed


def _entry_keys(values: Any) -> set[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return set()
    return {
        _entry_key(value)
        for value in values
        if isinstance(value, Mapping)
    }


def _requires_snapshot(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    identity_fields = (
        "schema_version",
        "event_payload_mode",
        "team_id",
        "session_id",
        "action_schema_version",
        "work_item_schema_version",
        "synthesis_verdict_version",
    )
    if any(before.get(field) != after.get(field) for field in identity_fields):
        return True
    # Incremental records can upsert entries, but cannot safely express a
    # canonical removal. Reconcile with a full snapshot so stale finals or
    # actions never survive in the client.
    return any(
        not _entry_keys(before.get(collection)).issubset(
            _entry_keys(after.get(collection))
        )
        for collection in (
            "events",
            "items",
            "actions",
            "work_items",
            "background_actions",
        )
    )


def _active_event(conversation: Mapping[str, Any]) -> dict[str, Any] | None:
    interaction = conversation.get("interaction_projection")
    if isinstance(interaction, Mapping):
        # ``interaction_projection`` is the authoritative 1.0 contract.  Once
        # it is present, do not fall back to the old pending/action precedence:
        # that fallback can label a cancelling run as waiting for a question.
        phase = str(interaction.get("phase") or "idle")
        subject = interaction.get("subject")
        if phase in {"idle", "observation_degraded"} or not isinstance(
            subject,
            Mapping,
        ):
            return None
        selected = deepcopy(dict(subject))
        selected.update(
            {
                "phase": phase,
                "status": (
                    "waiting_for_human"
                    if phase in {"waiting_question", "waiting_approval"}
                    else "running"
                    if phase in {"agent_working", "background_working"}
                    else phase
                ),
                "active_type": (
                    "cancellation"
                    if phase == "stopping"
                    else "human_checkpoint"
                    if phase in {"waiting_question", "waiting_approval"}
                    else "agent_turn"
                    if phase == "agent_working"
                    else "training_run"
                    if phase == "background_working"
                    and subject.get("object_type") == "TrainingRun"
                    else "background_action"
                    if phase == "background_working"
                    else "terminal"
                    if phase in {"completed", "failed", "stopped"}
                    else "risk"
                ),
                "can_cancel": bool(interaction.get("can_cancel")),
                "turn_identity": deepcopy(
                    dict(interaction.get("turn_identity") or {})
                ),
                "active_action_id": interaction.get("active_action_id"),
            }
        )
        return selected
    explicit = conversation.get("active_event")
    if isinstance(explicit, Mapping):
        return deepcopy(dict(explicit))
    pending = conversation.get("pending")
    if isinstance(pending, Sequence) and not isinstance(pending, (str, bytes)):
        checkpoint = next((item for item in pending if isinstance(item, Mapping)), None)
        if checkpoint is not None:
            return {
                "active_type": "human_checkpoint",
                "status": "waiting_for_human",
                "kind": checkpoint.get("kind"),
                "rpc_id": checkpoint.get("rpc_id"),
            }
    actions = conversation.get("actions")
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            if action.get("status") in {
                "queued",
                "running",
                "pending",
                "waiting_for_human",
            }:
                return deepcopy(dict(action))
    background_actions = conversation.get("background_actions")
    if isinstance(background_actions, Sequence) and not isinstance(
        background_actions,
        (str, bytes),
    ):
        for action in background_actions:
            if isinstance(action, Mapping) and action.get("running") is True:
                return deepcopy(dict(action))
    return None


def _state_payload(conversation: Mapping[str, Any]) -> dict[str, Any]:
    interaction = conversation.get("interaction_projection")
    selected_interaction = (
        deepcopy(dict(interaction)) if isinstance(interaction, Mapping) else None
    )
    phase = (
        str(selected_interaction.get("phase") or "idle")
        if selected_interaction is not None
        else None
    )
    legacy_interaction_state = {
        "stopping": "cancelling",
        "waiting_question": "waiting_for_human",
        "waiting_approval": "waiting_for_human",
        "agent_working": "working",
        "background_working": "working",
        "completed": "terminal",
        "failed": "terminal",
        "stopped": "terminal",
        "blocked": "blocked",
        "observation_degraded": "observation_degraded",
        "idle": "idle",
    }.get(phase or "")
    return {
        "running": bool(conversation.get("running")),
        "execution_running": bool(conversation.get("execution_running")),
        "agent_response_running": bool(
            conversation.get("agent_response_running")
        ),
        "background_action_running": bool(
            conversation.get("background_action_running")
        ),
        "interaction_state": (
            legacy_interaction_state
            or conversation.get("interaction_state")
            or "idle"
        ),
        "can_cancel_agent": (
            bool(selected_interaction.get("can_cancel"))
            if selected_interaction is not None
            else bool(conversation.get("can_cancel_agent"))
        ),
        "interaction_projection": selected_interaction,
        "active_event": _active_event(conversation),
        "pending": deepcopy(list(conversation.get("pending") or [])),
        "runs": deepcopy(list(conversation.get("runs") or [])),
        "agents": deepcopy(list(conversation.get("agents") or [])),
        "delegations": deepcopy(list(conversation.get("delegations") or [])),
        "work_items": deepcopy(list(conversation.get("work_items") or [])),
        "background_actions": deepcopy(
            list(conversation.get("background_actions") or [])
        ),
        "agent_turns": deepcopy(list(conversation.get("agent_turns") or [])),
        "training_runs": deepcopy(list(conversation.get("training_runs") or [])),
        "human_checkpoints": deepcopy(
            list(conversation.get("human_checkpoints") or [])
        ),
        "primary_attention": deepcopy(conversation.get("primary_attention")),
        "risks": deepcopy(list(conversation.get("risks") or [])),
        "projection_health": conversation.get("projection_health") or "healthy",
        "projection_errors": deepcopy(
            list(conversation.get("projection_errors") or [])
        ),
        "stream_health": deepcopy(dict(conversation.get("stream_health") or {})),
    }


def _delta_payload(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "events": _changed_entries(before.get("events"), after.get("events")),
        "items": _changed_entries(before.get("items"), after.get("items")),
        "actions": _changed_entries(before.get("actions"), after.get("actions")),
        "work_items": _changed_entries(
            before.get("work_items"),
            after.get("work_items"),
        ),
        "background_actions": _changed_entries(
            before.get("background_actions"),
            after.get("background_actions"),
        ),
    }


def _normalize_observation_health(
    conversation: Mapping[str, Any],
) -> dict[str, Any]:
    selected = deepcopy(dict(conversation))
    stream_health = selected.get("stream_health")
    if not isinstance(stream_health, Mapping):
        stream_health = {"status": "not_observed", "consecutive_failures": 1}
        selected["stream_health"] = stream_health
    if stream_observation_degraded(
        stream_health,
        require_proven_healthy=selected.get("team_id") is not None,
    ) or selected.get("projection_errors"):
        selected["projection_health"] = "observation_degraded"
        interaction = selected.get("interaction_projection")
        if isinstance(interaction, Mapping):
            degraded_interaction = deepcopy(dict(interaction))
            degraded_interaction.update(
                {
                    "phase": "observation_degraded",
                    "subject": None,
                    "can_cancel": False,
                    "terminal_outcome": None,
                }
            )
            selected["interaction_projection"] = degraded_interaction
    return selected


def _agent_runtime_error_contract(
    error: AgentRuntimeError,
) -> tuple[str, str, bool]:
    message = str(error)
    recoverable_prefixes = (
        "无法读取多智能体会话",
        "训练 Agent 运行时不可用",
        "DeepSeek Harness 多智能体运行时不可用",
    )
    if error.__class__ is AgentRuntimeError or message.startswith(
        recoverable_prefixes
    ):
        return (
            "conversation_runtime_unavailable",
            "实时对话观察暂时不可用，请重新连接。",
            True,
        )
    return (
        "conversation_projection_integrity_failed",
        "对话投影证据无法验真，请刷新任务并检查运行时状态。",
        False,
    )


@dataclass(frozen=True)
class ConversationStreamRecord:
    cursor: int
    event: str
    projector_revision: str
    payload: dict[str, Any]

    def as_data(self, task_id: str, stream_id: str) -> dict[str, Any]:
        cursor_token = encode_stream_cursor(
            stream_id=stream_id,
            projector_revision=self.projector_revision,
            sequence=self.cursor,
        )
        return {
            "schema_version": CONVERSATION_STREAM_SCHEMA_VERSION,
            "task_id": task_id,
            "stream_id": stream_id,
            "projector_revision": self.projector_revision,
            "cursor": self.cursor,
            "cursor_token": cursor_token,
            **deepcopy(self.payload),
        }

    def encode(self, task_id: str, stream_id: str) -> bytes:
        if self.event not in CONVERSATION_STREAM_EVENTS:
            raise ValueError(f"unsupported conversation stream event: {self.event}")
        cursor_token = encode_stream_cursor(
            stream_id=stream_id,
            projector_revision=self.projector_revision,
            sequence=self.cursor,
        )
        data = json.dumps(
            self.as_data(task_id, stream_id),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            f"id: {cursor_token}\n"
            f"event: {self.event}\n"
            f"data: {data}\n\n"
        ).encode("utf-8")


class _TaskConversationBroadcaster:
    def __init__(
        self,
        *,
        task_id: str,
        runtime: ConversationStreamRuntime,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        history_limit: int,
    ) -> None:
        self.task_id = task_id
        self.stream_id = uuid4().hex
        self.runtime = runtime
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        # Keep up to history_limit semantic records plus one coalesced
        # heartbeat. Liveness noise must never evict a recoverable domain
        # cursor and force an otherwise unnecessary snapshot.
        self._history_limit = history_limit
        self._history: deque[ConversationStreamRecord] = deque()
        self._condition = asyncio.Condition()
        self._projection_call_lock = asyncio.Lock()
        self._projection_workers: set[asyncio.Task[dict[str, Any]]] = set()
        self._cursor = 0
        self._latest_conversation: dict[str, Any] | None = None
        self._projector_revision: str | None = None
        self._revision_hint: str | None = None
        self._producer_task: asyncio.Task[None] | None = None
        self._subscriber_count = 0
        self._reservation_count = 0
        self._fatal_cursor: int | None = None
        self._projection_generation = 0
        self._closed = False
        self.last_used_at = time.monotonic()

    @property
    def subscriber_count(self) -> int:
        return self._subscriber_count

    @property
    def reservation_count(self) -> int:
        return self._reservation_count

    @property
    def producer_running(self) -> bool:
        return self._producer_task is not None and not self._producer_task.done()

    @property
    def projection_running(self) -> bool:
        return any(not worker.done() for worker in self._projection_workers)

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def history_size(self) -> int:
        return len(self._history)

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            producer = self._producer_task
            self._condition.notify_all()
        if producer is not None and producer is not asyncio.current_task():
            await asyncio.gather(producer, return_exceptions=True)
        # Full GET reconciliation shares this mutex but is not the producer
        # task. Cross the barrier before the runtime/workspace is shut down.
        async with self._projection_call_lock:
            pass
        # A cancelled request releases the coroutine mutex while its to_thread
        # worker keeps running. Track those workers explicitly so shutdown
        # never tears down the runtime/workspace underneath one of them.
        workers = list(self._projection_workers)
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        async with self._condition:
            if self._producer_task is producer:
                self._producer_task = None

    async def subscribe(
        self,
        *,
        after_seq: int | None,
        last_event_cursor: ConversationStreamCursor | None,
        expected_projector_revision: str | None,
        runtime_projector_revision: str | None,
    ) -> AsyncIterator[ConversationStreamRecord]:
        required_generation, had_history = await self._register(
            runtime_projector_revision
        )
        delivered_cursor = (
            last_event_cursor.sequence
            if last_event_cursor is not None
            else after_seq
        )
        try:
            await self._wait_until_ready(required_generation)
            async with self._condition:
                if self._latest_conversation is None:
                    records = list(self._history)
                elif (
                    delivered_cursor is None
                    or (
                        last_event_cursor is not None
                        and (
                            last_event_cursor.stream_id != self.stream_id
                            or last_event_cursor.projector_key
                            != _projector_key(self._projector_revision or "unknown")
                        )
                    )
                    or (
                        expected_projector_revision is not None
                        and expected_projector_revision != self._projector_revision
                    )
                    or (
                        last_event_cursor is None
                        and after_seq is not None
                        and not had_history
                    )
                    or not self._cursor_is_replayable(delivered_cursor)
                ):
                    records = [self._snapshot_for_subscriber()]
                else:
                    records = self._records_after(delivered_cursor)
            for record in records:
                yield record
                delivered_cursor = record.cursor
                if record.event == "error":
                    return

            if delivered_cursor is None:
                async with self._condition:
                    delivered_cursor = self._cursor

            while True:
                async with self._condition:
                    while True:
                        if self._closed:
                            return
                        if not self._cursor_is_replayable(delivered_cursor):
                            records = [self._snapshot_for_subscriber()]
                            break
                        records = self._records_after(delivered_cursor)
                        if records:
                            break
                        if (
                            self._fatal_cursor is not None
                            and delivered_cursor >= self._fatal_cursor
                        ):
                            return
                        await self._condition.wait()
                for record in records:
                    yield record
                    delivered_cursor = record.cursor
                    if record.event == "error":
                        return
        finally:
            await self._unregister()

    async def refresh(self) -> dict[str, Any]:
        """Run one task projection under the same mutex used by the producer."""

        return await self._project_once()

    async def _register(
        self,
        runtime_projector_revision: str | None,
    ) -> tuple[int, bool]:
        async with self._condition:
            if self._closed:
                raise RuntimeError("conversation stream broker is closed")
            self.last_used_at = time.monotonic()
            had_history = self._latest_conversation is not None and bool(self._history)
            self._subscriber_count += 1
            if runtime_projector_revision:
                self._revision_hint = runtime_projector_revision
            if self._producer_task is None or self._producer_task.done():
                if self._fatal_cursor is not None:
                    # A typed error terminates one stream epoch. Reconnect with
                    # a fresh epoch so an error cursor cannot also identify a
                    # later recovery snapshot.
                    self.stream_id = uuid4().hex
                    self._history.clear()
                    self._cursor = 0
                    self._latest_conversation = None
                    self._projector_revision = None
                self._fatal_cursor = None
                required_generation = self._projection_generation + 1
                self._producer_task = asyncio.create_task(
                    self._produce(),
                    name=f"conversation-stream:{self.task_id}",
                )
            else:
                required_generation = self._projection_generation
            return required_generation, had_history

    async def _unregister(self) -> None:
        async with self._condition:
            self.last_used_at = time.monotonic()
            self._subscriber_count = max(0, self._subscriber_count - 1)
            self._condition.notify_all()

    async def _wait_until_ready(self, required_generation: int) -> None:
        async with self._condition:
            while (
                (
                    self._latest_conversation is None
                    or self._projection_generation < required_generation
                )
                and self._fatal_cursor is None
                and not self._closed
            ):
                await self._condition.wait()

    def _cursor_is_replayable(self, cursor: int | None) -> bool:
        if cursor is None or cursor < 0 or cursor > self._cursor:
            return False
        if not self._history:
            return cursor == self._cursor
        oldest = self._history[0].cursor
        return cursor >= oldest - 1

    def _records_after(self, cursor: int) -> list[ConversationStreamRecord]:
        return [record for record in self._history if record.cursor > cursor]

    def _snapshot_for_subscriber(self) -> ConversationStreamRecord:
        assert self._latest_conversation is not None
        return ConversationStreamRecord(
            cursor=self._cursor,
            event="snapshot",
            projector_revision=self._projector_revision or "unknown",
            payload={"conversation": deepcopy(self._latest_conversation)},
        )

    async def _produce(self) -> None:
        last_heartbeat = time.monotonic()
        try:
            while True:
                async with self._condition:
                    if self._closed or self._subscriber_count == 0:
                        return
                try:
                    selected = await self._project_once()
                except asyncio.CancelledError:
                    raise
                except FileNotFoundError:
                    await self._publish_error(
                        code="conversation_task_removed",
                        message="训练任务已不存在，实时对话已停止。",
                        recoverable=False,
                    )
                    return
                except AgentRuntimeError as exc:
                    code, message, recoverable = _agent_runtime_error_contract(exc)
                    await self._publish_error(
                        code=code,
                        message=message,
                        recoverable=recoverable,
                    )
                    return
                except Exception:
                    await self._publish_error(
                        code="conversation_projection_failed",
                        message="实时对话投影失败，请刷新任务后重试。",
                        recoverable=False,
                    )
                    return

                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_interval_seconds:
                    await self._publish(
                        event="heartbeat",
                        projector_revision=self._projector_revision or "unknown",
                        payload={"server_time": _utc_now()},
                    )
                    last_heartbeat = now
                async with self._condition:
                    if self._closed or self._subscriber_count == 0:
                        return
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(),
                            timeout=self.poll_interval_seconds,
                        )
                    except TimeoutError:
                        pass
        except asyncio.CancelledError:
            return

    async def _project_once(self) -> dict[str, Any]:
        async with self._projection_call_lock:
            async with self._condition:
                if self._closed:
                    raise RuntimeError("conversation stream broker is closed")
            # If a cancelled HTTP request left its to_thread call running,
            # adopt that worker instead of starting a concurrent projection
            # for the same task.
            worker = next(
                (
                    candidate
                    for candidate in self._projection_workers
                    if not candidate.done()
                ),
                None,
            )
            if worker is None:
                worker = asyncio.create_task(
                    asyncio.to_thread(
                        self.runtime.conversation,
                        self.task_id,
                    ),
                    name=f"conversation-projection:{self.task_id}",
                )
                self._projection_workers.add(worker)
                worker.add_done_callback(self._projection_workers.discard)
            conversation = await asyncio.shield(worker)
            if not isinstance(conversation, Mapping):
                raise TypeError("conversation projection must be an object")
            selected = _normalize_observation_health(conversation)
            async with self._condition:
                should_publish = not self._closed and self._subscriber_count > 0
            if should_publish:
                await self._accept_projection(selected)
            return selected

    async def _accept_projection(self, conversation: dict[str, Any]) -> None:
        revision = _projector_revision(conversation, self._revision_hint)
        async with self._condition:
            if self._closed or self._subscriber_count == 0:
                return
            previous = deepcopy(self._latest_conversation)
            previous_revision = self._projector_revision
            self._latest_conversation = deepcopy(conversation)
            self._projector_revision = revision
            self._projection_generation += 1
            if (
                previous is None
                or revision != previous_revision
                or _requires_snapshot(previous, conversation)
            ):
                self._append_locked(
                    event="snapshot",
                    projector_revision=revision,
                    payload={"conversation": conversation},
                )
            else:
                delta = _delta_payload(previous, conversation)
                if any(delta.values()):
                    self._append_locked(
                        event="delta",
                        projector_revision=revision,
                        payload=delta,
                    )
                previous_state = _state_payload(previous)
                current_state = _state_payload(conversation)
                if previous_state != current_state:
                    self._append_locked(
                        event="state",
                        projector_revision=revision,
                        payload=current_state,
                    )
            self._condition.notify_all()

    async def _publish_error(
        self,
        *,
        code: str,
        message: str,
        recoverable: bool,
    ) -> None:
        async with self._condition:
            if self._closed or self._subscriber_count == 0:
                return
            record = self._append_locked(
                event="error",
                projector_revision=(
                    self._projector_revision or self._revision_hint or "unknown"
                ),
                payload={
                    "code": code,
                    "message": message,
                    "recoverable": recoverable,
                },
            )
            self._fatal_cursor = record.cursor
            self._condition.notify_all()

    async def _publish(
        self,
        *,
        event: str,
        projector_revision: str,
        payload: Mapping[str, Any],
    ) -> ConversationStreamRecord | None:
        async with self._condition:
            if self._closed or self._subscriber_count == 0:
                return None
            record = self._append_locked(
                event=event,
                projector_revision=projector_revision,
                payload=payload,
            )
            self._condition.notify_all()
            return record

    def _append_locked(
        self,
        *,
        event: str,
        projector_revision: str,
        payload: Mapping[str, Any],
    ) -> ConversationStreamRecord:
        self._cursor += 1
        record = ConversationStreamRecord(
            cursor=self._cursor,
            event=event,
            projector_revision=projector_revision,
            payload=deepcopy(dict(payload)),
        )
        if event == "heartbeat":
            self._history = deque(
                existing
                for existing in self._history
                if existing.event != "heartbeat"
            )
        self._history.append(record)
        semantic_count = sum(
            existing.event != "heartbeat" for existing in self._history
        )
        while semantic_count > self._history_limit:
            for index, existing in enumerate(self._history):
                if existing.event != "heartbeat":
                    del self._history[index]
                    semantic_count -= 1
                    break
        return record


class TaskConversationStreamBroker:
    """Shares one bounded projection producer across subscribers of a task."""

    def __init__(
        self,
        runtime: ConversationStreamRuntime,
        *,
        poll_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 15.0,
        history_limit: int = 256,
        max_task_hubs: int = 64,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if history_limit < 2:
            raise ValueError("history_limit must be at least 2")
        if max_task_hubs < 1:
            raise ValueError("max_task_hubs must be positive")
        self.runtime = runtime
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.history_limit = history_limit
        self.max_task_hubs = max_task_hubs
        self._hubs: dict[str, _TaskConversationBroadcaster] = {}
        self._lock = RLock()
        self._closed = False

    def start(self) -> None:
        with self._lock:
            self._closed = False

    async def close(self) -> None:
        with self._lock:
            self._closed = True
            hubs = list(self._hubs.values())
            self._hubs.clear()
        await asyncio.gather(*(hub.close() for hub in hubs), return_exceptions=True)

    async def stream(
        self,
        task_id: str,
        *,
        after_seq: int | None = None,
        last_event_id: str | None = None,
        expected_projector_revision: str | None = None,
        runtime_projector_revision: str | None = None,
        reservation: ConversationStreamReservation | None = None,
    ) -> AsyncIterator[bytes]:
        owned_reservation = reservation or self.reserve(task_id)
        subscription: AsyncIterator[ConversationStreamRecord] | None = None
        try:
            if owned_reservation.task_id != task_id:
                raise ValueError("conversation stream reservation task mismatch")
            hub = owned_reservation.hub
            last_event_cursor = (
                parse_stream_cursor(last_event_id)
                if last_event_id is not None
                else None
            )
            subscription = hub.subscribe(
                after_seq=after_seq,
                last_event_cursor=last_event_cursor,
                expected_projector_revision=expected_projector_revision,
                runtime_projector_revision=runtime_projector_revision,
            )
            async for record in subscription:
                yield record.encode(task_id, hub.stream_id)
        finally:
            try:
                if subscription is not None:
                    await subscription.aclose()
            finally:
                owned_reservation.release()

    async def conversation(self, task_id: str) -> dict[str, Any]:
        reservation = self.reserve(task_id)
        try:
            return await reservation.hub.refresh()
        finally:
            reservation.release()

    def reserve(self, task_id: str) -> ConversationStreamReservation:
        with self._lock:
            hub = self._hub(task_id)
            hub._reservation_count += 1
            return ConversationStreamReservation(self, task_id, hub)

    def _release_reservation(self, hub: _TaskConversationBroadcaster) -> None:
        with self._lock:
            hub._reservation_count = max(0, hub._reservation_count - 1)

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "closed": self._closed,
                "task_hubs": len(self._hubs),
                "active_producers": sum(
                    1 for hub in self._hubs.values() if hub.producer_running
                ),
                "active_projections": sum(
                    1 for hub in self._hubs.values() if hub.projection_running
                ),
                "subscribers": {
                    task_id: hub.subscriber_count
                    for task_id, hub in self._hubs.items()
                },
                "reservations": {
                    task_id: hub.reservation_count
                    for task_id, hub in self._hubs.items()
                },
                "cursors": {
                    task_id: hub.cursor for task_id, hub in self._hubs.items()
                },
                "history_sizes": {
                    task_id: hub.history_size for task_id, hub in self._hubs.items()
                },
            }

    def _hub(self, task_id: str) -> _TaskConversationBroadcaster:
        with self._lock:
            if self._closed:
                raise RuntimeError("conversation stream broker is closed")
            existing = self._hubs.get(task_id)
            if existing is not None:
                return existing
            if len(self._hubs) >= self.max_task_hubs:
                idle = sorted(
                    (
                        hub
                        for hub in self._hubs.values()
                        if hub.subscriber_count == 0
                        and hub.reservation_count == 0
                        and not hub.producer_running
                        and not hub.projection_running
                    ),
                    key=lambda hub: hub.last_used_at,
                )
                if idle:
                    self._hubs.pop(idle[0].task_id, None)
                else:
                    raise ConversationStreamCapacityError(
                        "conversation stream task capacity is exhausted"
                    )
            hub = _TaskConversationBroadcaster(
                task_id=task_id,
                runtime=self.runtime,
                poll_interval_seconds=self.poll_interval_seconds,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                history_limit=self.history_limit,
            )
            self._hubs[task_id] = hub
            return hub


class ConversationStreamReservation:
    """Pins one task broadcaster across asynchronous HTTP preflight."""

    def __init__(
        self,
        broker: TaskConversationStreamBroker,
        task_id: str,
        hub: _TaskConversationBroadcaster,
    ) -> None:
        self._broker = broker
        self.task_id = task_id
        self.hub = hub
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._broker._release_reservation(self.hub)
