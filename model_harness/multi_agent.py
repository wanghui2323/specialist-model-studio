from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .agent_bridge import (
    AgentRuntimeError,
    DshEventHub,
    DshRpcClient,
    agent_public_projection,
)
from .conversation_actions import (
    ACTION_SCHEMA_VERSION,
    classify_conversation_actions,
)
from .conversation_payloads import (
    CONVERSATION_EVENT_PAYLOAD_MODE,
    ConversationPayloadCompactionError,
    compact_conversation_response,
    project_conversation_objects,
)
from .io_utils import read_json, sha256_bytes, write_json
from .synthesis_evidence import (
    SYNTHESIS_VERDICT_VERSION,
    RunBoundary,
    SynthesisVerdictIndex,
    VerifiedChildBinding,
    evaluate_synthesis_evidence,
)


TEAM_SCHEMA_VERSION = "1.0"
CONVERSATION_EVENT_SCHEMA_VERSION = "2.0"
CONVERSATION_PROJECTOR_REVISION = "3.2"
AGENT_WORK_ITEM_SCHEMA_VERSION = "1.0"
COMPOSER_REQUEST_SCHEMA_VERSION = "1.0"
SUPPORTED_COMPOSER_MODES = frozenset({"queue_after_turn"})
DEFAULT_AGENT_PROVIDER_ID = "deepseek-official"
DEFAULT_AGENT_PROVIDER_CREDENTIAL_REF = "DEEPSEEK_API_KEY"
PUBLIC_CREDENTIAL_SOURCES = frozenset({"env", "file", "project-env", "user-env"})


def stream_observation_degraded(
    stream_health: Mapping[str, Any],
    *,
    require_proven_healthy: bool = False,
) -> bool:
    """Fail closed after a downlink failure without penalizing clean startup."""

    status = str(stream_health.get("status") or "not_observed")
    failures = stream_health.get("consecutive_failures", 0)
    failure_count = (
        failures
        if isinstance(failures, int) and not isinstance(failures, bool)
        else 1
    )
    if failure_count > 0:
        return True
    if status == "healthy":
        return False
    if require_proven_healthy:
        # Once a team/run exists, checkpoint coverage must be positively
        # observed before synthesis can become final.
        return True
    if status in {"not_started", "connecting", "not_observed"}:
        return stream_health.get("last_error_at") is not None
    # stopped, degraded and unknown states cannot prove checkpoint coverage.
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _safe_task_dir(tasks_dir: Path, task_id: str) -> Path:
    selected = task_id.strip()
    if not selected or selected in {".", ".."} or "/" in selected or "\\" in selected:
        raise MultiAgentRuntimeError("task_id 格式非法")
    task_dir = (tasks_dir / selected).resolve()
    if task_dir.parent != tasks_dir.resolve():
        raise MultiAgentRuntimeError("task_id 越出工作区边界")
    return task_dir


def _agent_turn_id_for_run(
    team: Mapping[str, Any],
    agent_run_id: Any,
) -> str | None:
    """Resolve the product AgentTurn without rewriting the raw DSH turn id."""

    if not isinstance(agent_run_id, str) or not agent_run_id:
        return None
    for run in reversed(list(team.get("runs") or [])):
        if not isinstance(run, Mapping) or run.get("run_id") != agent_run_id:
            continue
        agent_turn_id = run.get("agent_turn_id")
        return (
            agent_turn_id
            if isinstance(agent_turn_id, str) and agent_turn_id
            else None
        )
    return None


class MultiAgentRuntimeError(AgentRuntimeError):
    """Expected failure at the DSH multi-agent product boundary."""


class HumanCheckpointConflictError(MultiAgentRuntimeError):
    """The submitted decision no longer matches the current checkpoint."""


class HumanCheckpointAnswerError(MultiAgentRuntimeError):
    """The submitted question answer is malformed for the current checkpoint."""


class ComposerModeUnsupportedError(MultiAgentRuntimeError):
    """The requested composer mutation has no verified durable backend."""


class ComposerRequestConflictError(MultiAgentRuntimeError):
    """A durable composer request id was reused with different semantics."""


class ComposerRequestTerminalError(MultiAgentRuntimeError):
    """A composer request already owns a terminal AgentTurn."""

    def __init__(self, *, request_id: str, status: str) -> None:
        self.request_id = request_id
        self.status = status
        self.new_request_required = True
        super().__init__(
            f"request_id {request_id} 已绑定到 {status} AgentTurn；"
            "如需再次执行必须创建新的 request_id"
        )


class ComposerSubmissionError(MultiAgentRuntimeError):
    """The first provider submission failed after request persistence."""

    def __init__(
        self,
        *,
        request_id: str,
        status: str,
        provider_error: str,
    ) -> None:
        self.request_id = request_id
        self.status = status
        self.new_request_required = True
        self.provider_error = provider_error
        super().__init__(
            f"无法提交多智能体任务：{provider_error}；"
            f"request_id={request_id} 已终止，重试需要新的 request_id"
        )


class DshTeamClient(Protocol):
    """Narrow provider boundary implemented by :class:`DshRpcClient`."""

    def available(self) -> bool: ...

    def call(self, method: str, payload: dict[str, Any]) -> Any: ...

    def respond(self, rpc_id: str, value: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    agent_label: str
    owns: tuple[str, ...]
    cannot_do: tuple[str, ...]
    permission_profile: tuple[str, ...]
    root: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_label": self.agent_label,
            "owns": list(self.owns),
            "cannot_do": list(self.cannot_do),
            "permission_profile": list(self.permission_profile),
            "root": self.root,
        }


# ADR-001 is the product contract. These are permission profiles, not six
# alternative task stores and not six fictional chat participants.
AGENT_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        agent_id="training_orchestrator",
        agent_label="Training Orchestrator",
        root=True,
        owns=("clarification", "job_routing", "pauses", "human_checkpoints"),
        cannot_do=("invent_tool_results", "silently_approve_work"),
        permission_profile=(
            "read_training_task",
            "delegate_native_subagents",
            "request_human_checkpoint",
        ),
    ),
    AgentProfile(
        agent_id="research_source",
        agent_label="Research & Source Agent",
        owns=("papers", "model_sources", "data_sources", "evidence", "asset_links"),
        cannot_do=("bind_source", "claim_candidate_compatibility"),
        permission_profile=(
            "read_training_task",
            "search_research_sources",
            "read_source_evidence",
            "propose_asset_links",
        ),
    ),
    AgentProfile(
        agent_id="data_experiment",
        agent_label="Data & Experiment Agent",
        owns=("data_requirements", "quality_diagnosis", "hypotheses", "ablations"),
        cannot_do=("lower_quality_gates", "start_training_run"),
        permission_profile=(
            "read_training_task",
            "inspect_dataset",
            "diagnose_data_quality",
            "propose_experiments",
        ),
    ),
    AgentProfile(
        agent_id="resource_safety",
        agent_label="Resource & Safety Agent",
        owns=("compute_fit", "licenses", "dependencies", "untrusted_content_policy"),
        cannot_do=("override_blocker",),
        permission_profile=(
            "read_training_task",
            "inspect_resources",
            "inspect_license",
            "inspect_isolation",
            "report_blocker",
        ),
    ),
    AgentProfile(
        agent_id="build_training",
        agent_label="Build & Training Agent",
        owns=("recipes", "build_plan", "isolated_qualification", "real_runs"),
        cannot_do=("execute_third_party_code_outside_approved_isolation",),
        permission_profile=(
            "read_training_task",
            "propose_training_plan",
            "qualify_in_isolation",
            "start_approved_run",
            "cancel_run",
        ),
    ),
    AgentProfile(
        agent_id="evaluation_delivery",
        agent_label="Evaluation & Delivery Agent",
        owns=("metrics", "failure_analysis", "inference_checks", "reports", "bundles"),
        cannot_do=("mark_failed_gate_release_ready",),
        permission_profile=(
            "read_training_task",
            "read_evaluation_evidence",
            "run_authorized_sample_inference",
            "build_approved_delivery_bundle",
        ),
    ),
)

PROFILE_BY_ID = {profile.agent_id: profile for profile in AGENT_PROFILES}
PROFILE_BY_LABEL = {profile.agent_label: profile for profile in AGENT_PROFILES}
ROOT_PROFILE = next(profile for profile in AGENT_PROFILES if profile.root)


class DshAgentTeamStore:
    """Persist DSH runtime lineage under its conversation or task owner.

    ``conversation.json`` is canonical before binding and ``task.json`` is
    canonical for model-training state after promotion.  This store contains
    only runtime mappings, prompt-run lineage and real DSH event projections.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.tasks_dir = self.workspace_root / "tasks"
        self.conversations_dir = self.workspace_root / "conversations"
        self._lock = RLock()

    def load_task(self, task_id: str) -> dict[str, Any]:
        task_path = _safe_task_dir(self.tasks_dir, task_id) / "task.json"
        conversation_path = (
            _safe_task_dir(self.conversations_dir, task_id) / "conversation.json"
        )
        owner_path = task_path if task_path.is_file() else conversation_path
        if not owner_path.is_file():
            raise MultiAgentRuntimeError(
                f"Conversation 或 TrainingTask 不存在: {task_id}"
            )
        task = read_json(owner_path)
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            raise MultiAgentRuntimeError("会话事实源损坏或 owner id 不匹配")
        return task

    def create_team(
        self,
        *,
        task_id: str,
        root_session_id: str,
        title: str,
        agent_preset: str,
    ) -> dict[str, Any]:
        task = self.load_task(task_id)
        now = _utc_now()
        team = {
            "schema_version": TEAM_SCHEMA_VERSION,
            "team_id": f"team-{uuid4().hex}",
            "task_id": task_id,
            "title": title,
            "status": "idle",
            "engine": "DeepSeek Harness",
            "implementation": "dsh_native_subagents",
            "agent_preset": agent_preset,
            "root_agent_id": ROOT_PROFILE.agent_id,
            "root_session_id": root_session_id,
            "task_spec_revision_at_creation": task.get("current_spec_revision"),
            "profiles": [profile.as_dict() for profile in AGENT_PROFILES],
            "agents": {
                ROOT_PROFILE.agent_id: {
                    "agent_id": ROOT_PROFILE.agent_id,
                    "agent_label": ROOT_PROFILE.agent_label,
                    "role_id": ROOT_PROFILE.agent_id,
                    "dsh_session_id": root_session_id,
                    "parent_agent_id": None,
                    "status": "idle",
                    "observed_from_dsh": True,
                }
            },
            "delegations": {},
            "runs": [],
            "event_seq": 0,
            "projected_source_keys": [],
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        with self._lock:
            path = self._team_path(task_id)
            if path.is_file():
                raise MultiAgentRuntimeError("TrainingTask 已存在 Agent Team")
            write_json(path, team)
            self.append_event(
                task_id=task_id,
                event={
                    "source": "runtime",
                    "source_key": f"runtime:team-created:{team['team_id']}",
                    "timestamp_utc": now,
                    "agent_id": ROOT_PROFILE.agent_id,
                    "agent_label": ROOT_PROFILE.agent_label,
                    "category": "agent_status",
                    "type": "team.created",
                    "status": "idle",
                    "payload": {
                        "root_session_id": root_session_id,
                        "implementation": "dsh_native_subagents",
                    },
                },
            )
        return self.load_team(task_id) or {}

    def load_team(self, task_id: str) -> dict[str, Any] | None:
        self.load_task(task_id)
        path = self._team_path(task_id)
        if not path.is_file():
            return None
        with self._lock:
            team = read_json(path)
            if (
                not isinstance(team, dict)
                or team.get("task_id") != task_id
                or team.get("schema_version") != TEAM_SCHEMA_VERSION
            ):
                raise MultiAgentRuntimeError("Agent Team 映射损坏")
            last_seq = max(
                (int(item.get("seq", 0)) for item in self.list_events(task_id)),
                default=0,
            )
            if int(team.get("event_seq", 0)) < last_seq:
                team["event_seq"] = last_seq
                team["updated_at_utc"] = _utc_now()
                write_json(path, team)
        return team

    def update_team(self, task_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            team = self.load_team(task_id)
            if team is None:
                raise MultiAgentRuntimeError("TrainingTask 还没有 Agent Team")
            team.update(deepcopy(changes))
            team["updated_at_utc"] = _utc_now()
            write_json(self._team_path(task_id), team)
        return team

    def prompt_run_for_request(
        self,
        task_id: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        team = self.load_team(task_id)
        if team is None:
            return None
        matches = [
            run
            for run in team.get("runs", [])
            if isinstance(run, Mapping)
            and isinstance(run.get("composer_request"), Mapping)
            and run["composer_request"].get("request_id") == request_id
        ]
        if len(matches) > 1:
            raise MultiAgentRuntimeError(
                "composer request identity is not unique for this task"
            )
        return deepcopy(dict(matches[0])) if matches else None

    def append_prompt_run(
        self,
        *,
        task_id: str,
        user_message: str,
        task_snapshot: Mapping[str, Any],
        composer_request_id: str,
        composer_mode: str,
        actor: str,
        source_seq_floor_by_session: Mapping[str, int] | None = None,
        source_boundary_complete: bool = False,
    ) -> dict[str, Any]:
        now = _utc_now()
        agent_turn_id = f"agent-turn-{uuid4().hex}"
        run = {
            "run_id": f"agent-run-{uuid4().hex}",
            "agent_turn_id": agent_turn_id,
            "status": "queued",
            "user_message": user_message,
            "composer_request": {
                "schema_version": COMPOSER_REQUEST_SCHEMA_VERSION,
                "request_id": composer_request_id,
                "mode": composer_mode,
                "actor": actor,
                "submitted_at_utc": now,
            },
            "task_digest": _json_digest(task_snapshot),
            "task_spec_revision": task_snapshot.get("current_spec_revision"),
            "queued_at_utc": now,
            "updated_at_utc": now,
            "error": None,
            "source_seq_floor_by_session": dict(source_seq_floor_by_session or {}),
            "source_boundary_complete": bool(source_boundary_complete),
        }
        with self._lock:
            team = self.load_team(task_id)
            if team is None:
                raise MultiAgentRuntimeError("TrainingTask 还没有 Agent Team")
            if any(
                isinstance(existing, Mapping)
                and isinstance(existing.get("composer_request"), Mapping)
                and existing["composer_request"].get("request_id")
                == composer_request_id
                for existing in team.get("runs", [])
            ):
                raise ComposerRequestConflictError(
                    "request_id 已由并发请求持久化，请以相同 payload 重试"
                )
            team["runs"].append(run)
            team["status"] = "queued"
            team["updated_at_utc"] = now
            write_json(self._team_path(task_id), team)
        queued_event = self.append_event(
            task_id=task_id,
            event={
                "source": "runtime",
                "source_key": f"runtime:prompt:{run['run_id']}",
                "timestamp_utc": now,
                "agent_id": ROOT_PROFILE.agent_id,
                "agent_label": ROOT_PROFILE.agent_label,
                "agent_run_id": run["run_id"],
                "session_id": team.get("root_session_id"),
                "dsh_session_id": team.get("root_session_id"),
                "category": "agent_status",
                "type": "agent.prompt_queued",
                "status": "queued",
                "payload": {
                    "run_id": run["run_id"],
                    "agent_turn_id": agent_turn_id,
                    "composer_request_id": composer_request_id,
                    "composer_mode": composer_mode,
                    "actor": actor,
                    "task_digest": run["task_digest"],
                    "task_spec_revision": run["task_spec_revision"],
                },
            },
        )
        with self._lock:
            team = self.load_team(task_id)
            assert team is not None
            persisted_run = next(
                item for item in team["runs"] if item["run_id"] == run["run_id"]
            )
            persisted_run["conversation_event_seq_at_queue"] = queued_event["seq"]
            persisted_run["updated_at_utc"] = _utc_now()
            write_json(self._team_path(task_id), team)
        return deepcopy(persisted_run)

    def update_run(
        self,
        *,
        task_id: str,
        run_id: str,
        status: str,
        error: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            team = self.load_team(task_id)
            if team is None:
                raise MultiAgentRuntimeError("TrainingTask 还没有 Agent Team")
            run = next(
                (item for item in team["runs"] if item.get("run_id") == run_id),
                None,
            )
            if run is None:
                raise MultiAgentRuntimeError(f"Agent run 不存在: {run_id}")
            previous_status = run.get("status")
            run["status"] = status
            run["error"] = error
            if evidence is not None:
                if previous_status == "completed" and status != "completed":
                    run.setdefault("status_reconciled_from", "completed")
                run.update(deepcopy(dict(evidence)))
            run["updated_at_utc"] = _utc_now()
            team["status"] = status
            team["updated_at_utc"] = _utc_now()
            write_json(self._team_path(task_id), team)
        return deepcopy(run)

    def append_event(self, *, task_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            path = self._team_path(task_id)
            team = read_json(path)
            source_key = str(event.get("source_key") or "")
            if not source_key:
                raise MultiAgentRuntimeError("conversation event 缺少 source_key")
            if source_key in set(team.get("projected_source_keys", [])):
                existing = next(
                    (
                        item
                        for item in self.list_events(task_id)
                        if item.get("source_key") == source_key
                    ),
                    None,
                )
                return existing or {}
            sequence = int(team.get("event_seq", 0)) + 1
            agent_run_id = event.get("agent_run_id")
            canonical_agent_turn_id = _agent_turn_id_for_run(team, agent_run_id)
            record = {
                "schema_version": CONVERSATION_EVENT_SCHEMA_VERSION,
                "event_id": str(uuid4()),
                "seq": sequence,
                "task_id": task_id,
                "team_id": team["team_id"],
                "root_session_id": team["root_session_id"],
                "source": str(event.get("source") or "dsh"),
                "projector_revision": event.get("projector_revision"),
                "source_key": source_key,
                "source_seq": event.get("source_seq"),
                "timestamp_utc": event.get("timestamp_utc") or _utc_now(),
                "agent_id": event.get("agent_id"),
                "agent_label": event.get("agent_label"),
                "actor_role": (
                    "orchestrator"
                    if event.get("agent_id") == ROOT_PROFILE.agent_id
                    else event.get("agent_id")
                ),
                "agent_run_id": agent_run_id,
                "agent_turn_id": (
                    canonical_agent_turn_id or event.get("agent_turn_id")
                ),
                "session_id": event.get("session_id"),
                "dsh_session_id": event.get("dsh_session_id"),
                "turn_id": event.get("turn_id"),
                "call_id": event.get("call_id"),
                "delegation_id": event.get("delegation_id"),
                "parent_delegation_id": event.get("parent_delegation_id"),
                "category": event.get("category"),
                "type": event.get("type"),
                "event_type": event.get("type"),
                "status": event.get("status"),
                "payload": agent_public_projection(dict(event.get("payload") or {})),
            }
            events_path = self._events_path(task_id)
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            team["event_seq"] = sequence
            team.setdefault("projected_source_keys", []).append(source_key)
            team["updated_at_utc"] = _utc_now()
            write_json(path, team)
        return record

    def persist_projection(
        self,
        *,
        task_id: str,
        events: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [self.append_event(task_id=task_id, event=event) for event in events]

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        path = self._events_path(task_id)
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def current_projection_events(self, task_id: str) -> list[dict[str, Any]]:
        """Return only DSH facts emitted by the active projector revision.

        Older projections stay in the append-only audit ledger, but they must
        not drive the current Agent Team or run lifecycle.
        """

        return [
            event
            for event in self.list_events(task_id)
            if event.get("source") == "dsh"
            and event.get("projector_revision") == CONVERSATION_PROJECTOR_REVISION
        ]

    def get_projected_event(
        self,
        task_id: str,
        event_id: str,
        *,
        projector_revision: str,
    ) -> dict[str, Any]:
        selected = str(event_id or "").strip()
        if not selected:
            raise FileNotFoundError("conversation event not found")
        event = next(
            (
                item
                for item in self.list_events(task_id)
                if item.get("event_id") == selected
                and item.get("projector_revision") == projector_revision
            ),
            None,
        )
        if event is None:
            raise FileNotFoundError("conversation event not found")
        return deepcopy(event)

    def _team_path(self, task_id: str) -> Path:
        return self._runtime_owner_dir(task_id) / "agent_team" / "team.json"

    def _events_path(self, task_id: str) -> Path:
        return self._runtime_owner_dir(task_id) / "agent_team" / "events.ndjson"

    def _runtime_owner_dir(self, owner_id: str) -> Path:
        # A conversation remains the durable owner of its DSH session even
        # after it binds a TrainingTask.  This keeps intake and execution in
        # one event lineage without moving files underneath the projector.
        conversation_dir = _safe_task_dir(self.conversations_dir, owner_id)
        if (conversation_dir / "conversation.json").is_file():
            return conversation_dir
        return _safe_task_dir(self.tasks_dir, owner_id)


class DshConversationV2Projector:
    """Projects only observed DSH history into product conversation events."""

    DELEGATION_TOOLS = {
        "spawn_agent",
        "fork_agent",
        "delegate_task",
        "delegate_to_agent",
        "send_message",
        "send_message_to_agent",
    }
    SPECIALIST_DELEGATION_TOOLS = {
        profile.agent_id: profile
        for profile in AGENT_PROFILES
        if not profile.root
    }

    def project(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        history: Any,
        session_id: str | None = None,
        session_agent_id: str | None = None,
        session_agent_label: str | None = None,
    ) -> list[dict[str, Any]]:
        entries = history.get("events", []) if isinstance(history, dict) else []
        root_session_id = str(team["root_session_id"])
        observed_session_id = session_id or root_session_id
        root_agent_id = str(team["root_agent_id"])
        default_agent_id = session_agent_id or root_agent_id
        default_agent_label = session_agent_label
        is_root_session = observed_session_id == root_session_id
        child_identity = (
            self._verified_child_projection_identity(
                team=team,
                session_id=observed_session_id,
                expected_agent_id=session_agent_id,
            )
            if not is_root_session
            else None
        )
        if child_identity is not None:
            default_agent_id = child_identity["agent_id"]
            default_agent_label = (
                child_identity["agent_label"] or default_agent_label
            )
        tools: dict[str, dict[str, Any]] = {}
        projected: list[dict[str, Any]] = []
        open_child_sessions: set[str] = set()
        turn_number = 0
        current_agent_run_id: str | None = (
            child_identity["agent_run_id"] if child_identity is not None else None
        )
        owning_delegation_id: str | None = (
            child_identity["delegation_id"] if child_identity is not None else None
        )
        owning_parent_delegation_id: str | None = (
            child_identity["parent_delegation_id"]
            if child_identity is not None
            else None
        )
        for index, entry in enumerate(entries):
            raw_event = entry.get("event", {}) if isinstance(entry, dict) else {}
            if not isinstance(raw_event, dict):
                continue
            event_type = str(raw_event.get("type") or "")
            data = raw_event.get("data", {})
            if not isinstance(data, dict):
                data = {}
            if event_type in {
                "subagent/completed",
                "subagent/failed",
                "subagent/cancelled",
                "subagent/status",
            } and str(data.get("status") or "").lower() in {
                "completed",
                "failed",
                "cancelled",
                "ready",
            }:
                completed_session_id = self._find_session_id(data)
                if completed_session_id:
                    open_child_sessions.discard(completed_session_id)
            source_seq = raw_event.get("seq")
            source_key = self._source_key(
                root_session_id=observed_session_id,
                source_seq=source_seq,
                index=index,
                event_type=event_type,
                data=data,
            )
            agent_id, agent_label = self._agent_identity(
                data=data,
                team=team,
                default_agent_id=default_agent_id,
            )
            agent_label = agent_label or default_agent_label
            base = {
                "source": "dsh",
                "projector_revision": CONVERSATION_PROJECTOR_REVISION,
                "source_key": source_key,
                "source_seq": source_seq,
                "timestamp_utc": raw_event.get("time") or _utc_now(),
                "agent_id": agent_id,
                "agent_label": agent_label,
                "agent_run_id": current_agent_run_id,
                "session_id": observed_session_id,
                "dsh_session_id": observed_session_id,
                "turn_id": f"{observed_session_id}:turn:{max(turn_number, 1)}",
                "delegation_id": owning_delegation_id,
                "parent_delegation_id": owning_parent_delegation_id,
            }
            if event_type == "user/message":
                if not is_root_session:
                    continue
                source = data.get("source", {})
                if isinstance(source, dict) and source.get("kind") in {
                    "subagent-report",
                    "subagent-settled",
                }:
                    sender_session_id = source.get("senderSessionId")
                    if isinstance(sender_session_id, str):
                        open_child_sessions.discard(sender_session_id)
                if isinstance(source, dict) and source.get("kind") not in {None, "user"}:
                    continue
                turn_number += 1
                base["turn_id"] = f"{observed_session_id}:turn:{turn_number}"
                text = _text_content(data.get("content"))
                run_match = re.search(
                    r"(?:^|\n)AGENT_RUN_ID:\s*([A-Za-z0-9._:-]+)",
                    text,
                )
                current_agent_run_id = run_match.group(1) if run_match else None
                marker = "USER_MESSAGE:\n"
                if marker in text:
                    text = text.split(marker, 1)[1]
                if text:
                    projected.append(
                        {
                            **base,
                            "agent_run_id": current_agent_run_id,
                            "category": "user_message",
                            "type": "user_message",
                            "status": "completed",
                            "payload": {"text": text},
                        }
                    )
            elif event_type == "assistant/message":
                message = data.get("message", {})
                content = message.get("content") if isinstance(message, dict) else None
                text = _text_content(content)
                if text:
                    work_tool_call = any(
                        isinstance(block, dict)
                        and block.get("type") == "tool-call"
                        and block.get("name") != "ask_user_question"
                        for block in (content if isinstance(content, list) else [])
                    )
                    if is_root_session and (work_tool_call or open_child_sessions):
                        category = "plan"
                        projected_type = "coordinator_plan"
                    elif is_root_session:
                        category = "synthesis_candidate"
                        projected_type = "synthesis_candidate"
                    else:
                        category = "agent_status" if work_tool_call else "specialist_output"
                        projected_type = "specialist_status" if work_tool_call else "specialist_output"
                    projected.append(
                        {
                            **base,
                            "category": category,
                            "type": projected_type,
                            "status": (
                                "running"
                                if projected_type == "specialist_status"
                                else "observed"
                                if projected_type == "synthesis_candidate"
                                else "completed"
                            ),
                            "payload": {"text": text},
                        }
                    )
            elif event_type == "tool/call":
                call_id = self._first_string(data, ("callId", "call_id", "toolCallId"))
                name = self._first_string(data, ("name", "toolName", "tool_name")) or "unknown"
                category = "delegation" if self._is_delegation_tool(name) else "tool"
                target_agent_id = self._target_agent_id(data)
                target_agent_label = self._target_agent_label(data)
                profile = self.SPECIALIST_DELEGATION_TOOLS.get(name.lower())
                if profile is not None:
                    target_agent_id = target_agent_id or profile.agent_id
                    target_agent_label = target_agent_label or profile.agent_label
                record = {
                    **base,
                    "call_id": call_id,
                    "delegation_id": (
                        call_id if category == "delegation" else owning_delegation_id
                    ),
                    "parent_delegation_id": (
                        owning_delegation_id
                        if category == "delegation"
                        else owning_parent_delegation_id
                    ),
                    "category": category,
                    "type": "delegation" if category == "delegation" else "tool_call",
                    "status": "running",
                    "payload": {
                        "call_id": call_id,
                        "tool_name": name,
                        "arguments": self._tool_arguments(data),
                        "target_agent_id": target_agent_id,
                        "target_agent_label": target_agent_label,
                    },
                }
                if call_id:
                    tools[call_id] = record
                projected.append(record)
            elif event_type == "tool/result":
                call_id, is_error, result = self._tool_result(data)
                original = tools.get(call_id or "", {})
                category = str(original.get("category") or "tool")
                object_refs = self._object_refs_from_tool_result(result)
                started_child_session_id = (
                    self._find_session_id(result) if category == "delegation" else None
                )
                delegation_started = bool(started_child_session_id and not is_error)
                if delegation_started and started_child_session_id:
                    open_child_sessions.add(started_child_session_id)
                payload = {
                    "call_id": call_id,
                    "tool_name": original.get("payload", {}).get("tool_name"),
                    "target_agent_id": original.get("payload", {}).get(
                        "target_agent_id"
                    ),
                    "target_agent_label": original.get("payload", {}).get(
                        "target_agent_label"
                    ),
                    "result": result,
                    "dsh_session_id": started_child_session_id,
                    "is_error": is_error,
                }
                if object_refs:
                    payload["object_refs"] = object_refs
                projected.append(
                    {
                        **base,
                        "call_id": call_id,
                        "delegation_id": (
                            call_id
                            if category == "delegation"
                            else owning_delegation_id
                        ),
                        "parent_delegation_id": (
                            owning_delegation_id
                            if category == "delegation"
                            else owning_parent_delegation_id
                        ),
                        "category": category,
                        "type": (
                            "delegation"
                            if delegation_started
                            else "specialist_output"
                            if category == "delegation"
                            else "tool_result"
                        ),
                        "status": (
                            "failed"
                            if is_error
                            else "running"
                            if delegation_started
                            else "completed"
                        ),
                        "payload": payload,
                    }
                )
            elif event_type == "turn/end":
                reason = data.get("reason", {})
                reason = reason if isinstance(reason, Mapping) else {}
                reason_kind = str(reason.get("kind") or "unknown")
                if reason_kind == "completed":
                    if not is_root_session:
                        projected.append(
                            {
                                **base,
                                "category": "agent_status",
                                "type": "specialist_status",
                                "status": "completed",
                                "payload": {"reason": reason_kind},
                            }
                        )
                    continue
                if reason_kind in {"aborted", "cancelled"}:
                    projected.append(
                        {
                            **base,
                            "category": "agent_status",
                            "type": "turn_cancelled",
                            "status": "cancelled",
                            "payload": {
                                "reason": reason_kind,
                                "text": "本轮 DSH 智能体任务已取消。",
                            },
                        }
                    )
                    continue
                failure = self._turn_failure(reason)
                projected.append(
                    {
                        **base,
                        "category": "agent_status",
                        "type": "turn_error",
                        "status": "failed",
                        "payload": {
                            "reason": reason_kind,
                            "text": failure["message"],
                            "error": failure,
                        },
                    }
                )
            elif event_type in {"approval/requested", "approval/resolved"}:
                projected.append(
                    {
                        **base,
                        "category": "approval",
                        "type": "approval",
                        "status": "pending" if event_type.endswith("requested") else "completed",
                        "payload": data,
                    }
                )
            elif event_type in {"question/requested", "question/resolved"}:
                projected.append(
                    {
                        **base,
                        "category": "question",
                        "type": "question",
                        "status": "pending" if event_type.endswith("requested") else "completed",
                        "payload": data,
                    }
                )
            elif event_type in {
                "agent/started",
                "agent/status",
                "agent/completed",
                "agent/failed",
                "subagent/created",
                "subagent/started",
                "subagent/status",
                "subagent/completed",
                "subagent/failed",
                "subagent/cancelled",
            }:
                projected.append(
                    {
                        **base,
                        "category": "agent_status",
                        "type": "specialist_status",
                        "status": self._status_from_event(event_type, data),
                        "payload": data,
                    }
                )
        return projected

    @classmethod
    def _turn_failure(cls, reason: Mapping[str, Any]) -> dict[str, Any]:
        """Keep DSH's typed turn failure without inferring from error text."""

        reason_kind = str(reason.get("kind") or "unknown")
        raw_error = reason.get("error")
        error = raw_error if isinstance(raw_error, Mapping) else {}
        defaults = {
            "blocked": (
                "TURN_BLOCKED",
                "DSH 在进入模型步骤前阻止了本轮执行。",
            ),
            "interrupted": (
                "TURN_INTERRUPTED",
                "DSH 会话在本轮完成前被中断。",
            ),
            "max-tokens": (
                "MAX_TOKENS",
                "模型达到输出 token 上限，本轮未正常完成。",
            ),
            "failed": ("UNKNOWN", "DSH 智能体本轮执行失败。"),
            "error": ("UNKNOWN", "DSH provider 请求失败。"),
            "unknown": ("UNKNOWN_TURN_END", "DSH 返回了未知的失败终止原因。"),
        }
        default_code, default_message = defaults.get(
            reason_kind,
            ("UNKNOWN_TURN_END", "DSH 返回了未知的失败终止原因。"),
        )
        code = cls._first_string(error, ("code",)) or default_code
        message = cls._first_string(error, ("message",))
        if message is None and isinstance(raw_error, str) and raw_error.strip():
            message = raw_error.strip()
        failure: dict[str, Any] = {
            "code": code,
            "message": message or default_message,
            "source": "dsh_turn_end",
        }
        status = error.get("status")
        if isinstance(status, int) and not isinstance(status, bool):
            failure["status"] = status
        retry_after = error.get("providerRetryAfterMs")
        if isinstance(retry_after, (int, float)) and not isinstance(
            retry_after, bool
        ):
            failure["provider_retry_after_ms"] = retry_after
        request_id = cls._first_string(error, ("requestId", "request_id"))
        if request_id is not None:
            failure["request_id"] = request_id
        return failure

    @classmethod
    def _verified_child_projection_identity(
        cls,
        *,
        team: Mapping[str, Any],
        session_id: str,
        expected_agent_id: str | None,
    ) -> dict[str, str | None] | None:
        """Resolve child ownership only from a unique, verified team binding."""

        root_session_id = team.get("root_session_id")
        root_agent_id = team.get("root_agent_id")
        delegations = team.get("delegations")
        runs = team.get("runs")
        if (
            not isinstance(root_session_id, str)
            or not isinstance(root_agent_id, str)
            or not isinstance(delegations, Mapping)
            or not isinstance(runs, list)
        ):
            return None
        run_ids = {
            str(run["run_id"])
            for run in runs
            if isinstance(run, Mapping)
            and isinstance(run.get("run_id"), str)
            and run.get("run_id")
        }

        def resolve(
            selected_session_id: str,
            visited: frozenset[str],
        ) -> dict[str, str | None] | None:
            if selected_session_id in visited or selected_session_id == root_session_id:
                return None
            bindings: list[dict[str, Any]] = []
            for key, value in delegations.items():
                if not isinstance(value, Mapping):
                    continue
                delegation_id = value.get("delegation_id")
                if not isinstance(delegation_id, str) or not delegation_id:
                    continue
                if str(key) != delegation_id:
                    continue
                if (
                    value.get("dsh_session_id") != selected_session_id
                    or value.get("agent_run_id") not in run_ids
                    or not isinstance(value.get("target_agent_id"), str)
                    or not value.get("target_agent_id")
                ):
                    continue
                bindings.append(dict(value))
            if len(bindings) != 1:
                return None
            binding = bindings[0]
            agent_id = str(binding["target_agent_id"])
            if (
                binding.get("lineage_verified") is True
                and binding.get("lineage_origin") == "subagent"
                and isinstance(binding.get("lineage_parent_session_id"), str)
                and binding.get("lineage_parent_session_id")
            ):
                parent_session_id = str(binding["lineage_parent_session_id"])
            else:
                # Compatibility for persisted v2 teams created before lineage
                # moved from role aggregation onto delegation instances.
                legacy_agents = team.get("agents")
                matches = [
                    dict(agent)
                    for agent in legacy_agents.values()
                    if isinstance(legacy_agents, Mapping)
                    and isinstance(agent, Mapping)
                    and agent.get("dsh_session_id") == selected_session_id
                    and agent.get("agent_id") == agent_id
                    and agent.get("lineage_verified") is True
                    and agent.get("lineage_origin") == "subagent"
                    and isinstance(agent.get("lineage_parent_session_id"), str)
                    and agent.get("lineage_parent_session_id")
                ] if isinstance(legacy_agents, Mapping) else []
                if len(matches) != 1:
                    return None
                parent_session_id = str(matches[0]["lineage_parent_session_id"])
            parent_delegation_id = binding.get("parent_delegation_id")
            source_agent_id = binding.get("source_agent_id")
            if parent_session_id == root_session_id:
                if source_agent_id != root_agent_id or parent_delegation_id is not None:
                    return None
            else:
                parent = resolve(
                    parent_session_id,
                    visited | frozenset({selected_session_id}),
                )
                if (
                    parent is None
                    or source_agent_id != parent["agent_id"]
                    or parent_delegation_id != parent["delegation_id"]
                    or binding.get("agent_run_id") != parent["agent_run_id"]
                ):
                    return None
            return {
                "agent_id": agent_id,
                "agent_label": (
                    str(binding["target_agent_label"])
                    if isinstance(binding.get("target_agent_label"), str)
                    and binding.get("target_agent_label")
                    else None
                ),
                "agent_run_id": str(binding["agent_run_id"]),
                "delegation_id": str(binding["delegation_id"]),
                "parent_delegation_id": (
                    str(parent_delegation_id)
                    if isinstance(parent_delegation_id, str)
                    and parent_delegation_id
                    else None
                ),
            }

        identity = resolve(session_id, frozenset())
        if (
            identity is not None
            and expected_agent_id is not None
            and identity["agent_id"] != expected_agent_id
        ):
            return None
        return identity

    @staticmethod
    def _source_key(
        *,
        root_session_id: str,
        source_seq: Any,
        index: int,
        event_type: str,
        data: Mapping[str, Any],
    ) -> str:
        identity = {
            "root_session_id": root_session_id,
            "source_seq": source_seq,
            "index": index if source_seq is None else None,
            "event_type": event_type,
            "data_digest": _json_digest(data),
        }
        return f"dsh:{CONVERSATION_PROJECTOR_REVISION}:{_json_digest(identity)}"

    @staticmethod
    def _is_delegation_tool(name: str) -> bool:
        lowered = name.lower()
        return (
            lowered in DshConversationV2Projector.DELEGATION_TOOLS
            or lowered in DshConversationV2Projector.SPECIALIST_DELEGATION_TOOLS
            or lowered.startswith("delegate_")
            or lowered.startswith("subagent_")
            or lowered == "followup_task"
        )

    @classmethod
    def _agent_identity(
        cls,
        *,
        data: Mapping[str, Any],
        team: Mapping[str, Any],
        default_agent_id: str,
    ) -> tuple[str, str | None]:
        agent_id = cls._find_nested_string(
            data,
            ("agentId", "agent_id", "actorAgentId", "sourceAgentId"),
        ) or default_agent_id
        agents = team.get("agents", {})
        known = agents.get(agent_id, {}) if isinstance(agents, dict) else {}
        label = known.get("agent_label") if isinstance(known, dict) else None
        observed_label = cls._find_nested_string(
            data,
            ("agentLabel", "agent_label", "roleLabel", "role_label"),
        )
        label = observed_label or label
        if label is None and agent_id in PROFILE_BY_ID:
            label = PROFILE_BY_ID[agent_id].agent_label
        return agent_id, str(label) if label is not None else None

    @classmethod
    def _target_agent_id(cls, data: Mapping[str, Any]) -> str | None:
        return cls._find_nested_string(
            data,
            ("targetAgentId", "target_agent_id", "subagentId", "subagent_id"),
        )

    @classmethod
    def _target_agent_label(cls, data: Mapping[str, Any]) -> str | None:
        return cls._find_nested_string(
            data,
            ("targetAgentLabel", "target_agent_label", "roleLabel", "role_label"),
        )

    @classmethod
    def _find_session_id(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("sessionId", "session_id", "subagentSessionId", "subagentId"):
                selected = value.get(key)
                if isinstance(selected, str) and selected:
                    return selected
            for child in value.values():
                found = cls._find_session_id(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_session_id(child)
                if found:
                    return found
        elif isinstance(value, str):
            match = re.search(
                r"\b(?:started\s+)?subagent\s+([0-9a-f]{8}-[0-9a-f-]{27,})\b",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1)
        return None

    @classmethod
    def _find_nested_string(
        cls,
        value: Any,
        keys: Sequence[str],
    ) -> str | None:
        if isinstance(value, dict):
            for key in keys:
                selected = value.get(key)
                if isinstance(selected, str) and selected.strip():
                    return selected.strip()
            for child in value.values():
                found = cls._find_nested_string(child, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_nested_string(child, keys)
                if found:
                    return found
        return None

    @staticmethod
    def _first_string(value: Mapping[str, Any], keys: Sequence[str]) -> str | None:
        for key in keys:
            selected = value.get(key)
            if isinstance(selected, str) and selected.strip():
                return selected.strip()
        return None

    @staticmethod
    def _tool_arguments(data: Mapping[str, Any]) -> Any:
        for key in ("input", "arguments", "args", "params"):
            if key in data:
                return data[key]
        return None

    @staticmethod
    def _tool_result(data: Mapping[str, Any]) -> tuple[str | None, bool, Any]:
        call_id = DshConversationV2Projector._first_string(
            data,
            ("callId", "call_id", "toolCallId"),
        )
        content = data.get("message", {}).get("content") if isinstance(data.get("message"), dict) else None
        first = content[0] if isinstance(content, list) and content else {}
        if call_id is None and isinstance(first, dict):
            call_id = DshConversationV2Projector._first_string(
                first,
                ("toolCallId", "callId", "call_id"),
            )
        is_error = bool(data.get("error"))
        if isinstance(first, dict):
            is_error = is_error or bool(first.get("isError"))
        result = first.get("content") if isinstance(first, dict) and "content" in first else data.get("result")
        return call_id, is_error, result

    @classmethod
    def _object_refs_from_tool_result(cls, result: Any) -> list[dict[str, Any]]:
        """Read observed ObjectRefs without deriving or completing missing fields."""

        found, refs = cls._locate_object_refs(result, depth=0)
        return refs if found else []

    @classmethod
    def _locate_object_refs(
        cls,
        value: Any,
        *,
        depth: int,
    ) -> tuple[bool, list[dict[str, Any]]]:
        if depth > 6:
            return False, []
        if isinstance(value, str):
            selected = value.strip()
            if not selected or len(selected) > 1_000_000 or selected[0] not in "[{\"":
                return False, []
            try:
                decoded = json.loads(selected)
            except (json.JSONDecodeError, TypeError, ValueError):
                return False, []
            return cls._locate_object_refs(decoded, depth=depth + 1)
        if isinstance(value, Mapping):
            if "object_refs" in value:
                refs = value.get("object_refs")
                if not isinstance(refs, list):
                    return True, []
                if not all(
                    isinstance(item, Mapping)
                    and isinstance(item.get("type"), str)
                    and bool(item.get("type"))
                    and isinstance(item.get("id"), str)
                    and bool(item.get("id"))
                    for item in refs
                ):
                    return True, []
                return True, deepcopy([dict(item) for item in refs])
            if "content" in value:
                return cls._locate_object_refs(
                    value.get("content"),
                    depth=depth + 1,
                )
            if value.get("type") == "text" and "text" in value:
                return cls._locate_object_refs(
                    value.get("text"),
                    depth=depth + 1,
                )
            return False, []
        if isinstance(value, list):
            for item in value:
                found, refs = cls._locate_object_refs(item, depth=depth + 1)
                if found:
                    return True, refs
        return False, []

    @staticmethod
    def _status_from_event(event_type: str, data: Mapping[str, Any]) -> str:
        explicit = data.get("status")
        if isinstance(explicit, str) and explicit:
            return explicit
        lowered = event_type.lower()
        if any(token in lowered for token in ("failed", "error")):
            return "failed"
        if any(token in lowered for token in ("completed", "finished", "stopped")):
            return "completed"
        if any(token in lowered for token in ("started", "running", "created")):
            return "running"
        return "observed"


class DshMultiAgentRuntime:
    """Task-owned projection of DSH's real native subagent runtime.

    The root DSH session is the Training Orchestrator. DSH native delegation,
    spawn/fork, continuable subagents and tool loop remain inside DSH; Python
    does not emulate an LLM coordinator or invent expert messages.
    """

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        client: DshTeamClient,
        events: DshEventHub,
        cwd: str | Path,
        agent_preset: str = "model-training",
        projector: DshConversationV2Projector | None = None,
        background_actions_provider: (
            Callable[[str], Sequence[Mapping[str, Any]]] | None
        ) = None,
        background_actions_canceller: (
            Callable[[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None
        ) = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.cwd = Path(cwd).expanduser().resolve()
        self.client = client
        self.events = events
        self.events.bind_workspace(self.workspace_root)
        self.agent_preset = agent_preset
        self.store = DshAgentTeamStore(self.workspace_root)
        self.projector = projector or DshConversationV2Projector()
        self.background_actions_provider = background_actions_provider
        self.background_actions_canceller = background_actions_canceller
        self._lock = RLock()

    def runtime_status(self) -> dict[str, Any]:
        try:
            available = bool(self.client.available())
        except Exception:  # pragma: no cover - adapter safety boundary
            available = False
        provider = self._provider_readiness(transport_ready=available)
        ready = available and provider["ready"] is True
        stream_health = self._stream_health_snapshot()
        return {
            "available": available,
            "transport_ready": available,
            "ready": ready,
            "real_agent": available,
            "engine": "DeepSeek Harness",
            "implementation": "dsh_native_subagents",
            "fallback_mode": None,
            "reason": (
                None
                if ready
                else "dsh_runtime_unavailable"
                if not available
                else provider["reason"]
            ),
            "provider": provider,
            "root_agent": ROOT_PROFILE.as_dict(),
            "specialist_agents": [
                profile.as_dict() for profile in AGENT_PROFILES if not profile.root
            ],
            "conversation_schema_version": CONVERSATION_EVENT_SCHEMA_VERSION,
            "conversation_projector_revision": CONVERSATION_PROJECTOR_REVISION,
            "synthesis_verdict_version": SYNTHESIS_VERDICT_VERSION,
            "conversation_action_schema_version": ACTION_SCHEMA_VERSION,
            "supported_modes": sorted(SUPPORTED_COMPOSER_MODES),
            "stream_health": stream_health,
            "task_truth_source": "TrainingTask",
        }

    def _provider_readiness(self, *, transport_ready: bool) -> dict[str, Any]:
        """Return a non-secret readiness projection for the configured LLM.

        DSH transport health alone cannot prove that an Agent turn can reach a
        model.  This probe deliberately reads only provider activation and the
        credential *description* contract; it never resolves or returns a
        credential value.  Unknown response shapes and protocol failures fail
        closed so the product cannot present a runnable composer on guesswork.
        """

        status: dict[str, Any] = {
            "ready": False,
            "provider": DEFAULT_AGENT_PROVIDER_ID,
            "active": False,
            "configured": False,
            "source": None,
            "reason": "agent_transport_unavailable",
        }
        if not transport_ready:
            return status

        try:
            provider_payload = self.client.call("llm.providers", {})
            if not isinstance(provider_payload, Mapping):
                raise ValueError("provider response is not an object")
            provider_rows = provider_payload.get("providers")
            if not isinstance(provider_rows, list):
                raise ValueError("provider directory is missing")
            status["active"] = any(
                isinstance(row, Mapping)
                and row.get("provider") == DEFAULT_AGENT_PROVIDER_ID
                and row.get("active") is True
                for row in provider_rows
            )
        except Exception:  # pragma: no cover - exact adapter failures vary
            status["reason"] = "llm_provider_probe_unavailable"
            return status

        try:
            credential_payload = self.client.call(
                "credentials.describe",
                {"refs": [DEFAULT_AGENT_PROVIDER_CREDENTIAL_REF]},
            )
            if not isinstance(credential_payload, Mapping):
                raise ValueError("credential response is not an object")
            credential_rows = credential_payload.get("credentials")
            if not isinstance(credential_rows, Mapping):
                raise ValueError("credential directory is missing")
            credential = credential_rows.get(DEFAULT_AGENT_PROVIDER_CREDENTIAL_REF)
            if not isinstance(credential, Mapping):
                raise ValueError("credential description is missing")
            status["configured"] = credential.get("configured") is True
            raw_source = credential.get("source")
            if status["configured"] and isinstance(raw_source, str):
                status["source"] = (
                    raw_source if raw_source in PUBLIC_CREDENTIAL_SOURCES else "other"
                )
        except Exception:  # pragma: no cover - exact adapter failures vary
            status["reason"] = "llm_credential_probe_unavailable"
            return status

        if not status["active"]:
            status["reason"] = "llm_provider_inactive"
            return status
        if not status["configured"]:
            status["reason"] = "llm_credential_missing"
            return status
        status["ready"] = True
        status["reason"] = None
        return status

    def _stream_health_snapshot(self) -> dict[str, Any]:
        reader = getattr(self.events, "stream_health", None)
        if not callable(reader):
            return {
                "connected_at": None,
                "last_event_at": None,
                "last_error_at": None,
                "consecutive_failures": 0,
                "recovered_at": None,
                "status": "not_observed",
            }
        try:
            value = reader()
        except Exception:  # pragma: no cover - adapter safety boundary
            value = None
        if not isinstance(value, Mapping):
            return {
                "connected_at": None,
                "last_event_at": None,
                "last_error_at": None,
                "consecutive_failures": 1,
                "recovered_at": None,
                "status": "degraded",
            }
        return deepcopy(dict(value))

    def start(self) -> None:
        self.events.start()

    def stop(self) -> None:
        self.events.stop()

    def session_for(self, task_id: str) -> str | None:
        team = self.store.load_team(task_id)
        return str(team["root_session_id"]) if team else None

    def ensure_team(self, task_id: str, title: str) -> dict[str, Any]:
        task = self.store.load_task(task_id)
        existing = self.store.load_team(task_id)
        if existing is not None:
            return existing
        with self._lock:
            existing = self.store.load_team(task_id)
            if existing is not None:
                return existing
            if not self.runtime_status()["available"]:
                raise MultiAgentRuntimeError("DeepSeek Harness 多智能体运行时不可用")
            try:
                value = self.client.call(
                    "session.create",
                    {"cwd": str(self.cwd), "agentPreset": self.agent_preset},
                )
            except AgentRuntimeError as exc:
                raise MultiAgentRuntimeError(f"无法创建根 Agent 会话：{exc}") from exc
            root_session_id = value.get("sessionId") if isinstance(value, dict) else None
            if not isinstance(root_session_id, str) or not root_session_id:
                raise MultiAgentRuntimeError("DeepSeek Harness 未返回根 Agent 会话 ID")
            try:
                self.client.call(
                    "session.rename",
                    {"sessionId": root_session_id, "title": title},
                )
            except AgentRuntimeError:
                pass
            return self.store.create_team(
                task_id=task_id,
                root_session_id=root_session_id,
                title=title or str(task.get("name") or task_id),
                agent_preset=self.agent_preset,
            )

    # Canonical task-owned conversation entry. DSH queues the real root-agent
    # turn; callers retrieve live progress via ``conversation``.
    def submit_message(
        self,
        task_id: str,
        title: str,
        message: str,
        *,
        composer_mode: str = "queue_after_turn",
        request_id: str | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        selected = message.strip()
        if not selected:
            raise ValueError("message 不能为空")
        if composer_mode not in SUPPORTED_COMPOSER_MODES:
            raise ComposerModeUnsupportedError(
                f"composer mode {composer_mode!r} 尚无经过验证的 durable 执行语义；"
                "当前仅支持 queue_after_turn"
            )
        selected_actor = actor.strip() if isinstance(actor, str) else ""
        if selected_actor not in {"user", "system", "operator"}:
            raise ValueError("actor 必须是 user、operator 或 system")
        selected_request_id = (
            request_id.strip() if isinstance(request_id, str) else ""
        )
        if selected_request_id and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", selected_request_id
        ):
            raise ValueError("request_id 格式非法")
        selected_request_id = (
            selected_request_id or f"composer-request-{uuid4().hex}"
        )
        task = self.store.load_task(task_id)
        team = self.ensure_team(task_id, title)
        existing_run = self.store.prompt_run_for_request(
            task_id,
            selected_request_id,
        )
        if existing_run is not None:
            existing_request = existing_run.get("composer_request")
            assert isinstance(existing_request, Mapping)
            if (
                existing_run.get("user_message") != selected
                or existing_request.get("mode") != composer_mode
                or existing_request.get("actor") != selected_actor
            ):
                raise ComposerRequestConflictError(
                    "request_id 已绑定到不同的 message、mode 或 actor"
                )
            existing_status = str(existing_run.get("status") or "unknown")
            if existing_status not in {
                "queued",
                "running",
                "waiting_for_human",
            }:
                raise ComposerRequestTerminalError(
                    request_id=selected_request_id,
                    status=existing_status,
                )
            return self._composer_submission(
                team=team,
                run=existing_run,
                idempotent_replay=True,
            )
        source_floors, boundary_complete = self._capture_source_seq_boundary(team)
        run = self.store.append_prompt_run(
            task_id=task_id,
            user_message=selected,
            task_snapshot=task,
            composer_request_id=selected_request_id,
            composer_mode=composer_mode,
            actor=selected_actor,
            source_seq_floor_by_session=source_floors,
            source_boundary_complete=boundary_complete,
        )
        instruction = self._root_instruction(
            task_id=task_id,
            agent_run_id=run["run_id"],
            current_spec_revision=task.get("current_spec_revision"),
            record_type=str(task.get("record_type") or "training_task"),
            user_message=selected,
        )
        try:
            self.client.call(
                "session.prompt",
                {
                    "sessionId": team["root_session_id"],
                    "mode": "queue",
                    "content": [{"type": "text", "text": instruction}],
                    "clientTimeZone": "Asia/Shanghai",
                },
            )
        except AgentRuntimeError as exc:
            failed_run = self.store.update_run(
                task_id=task_id,
                run_id=run["run_id"],
                status="failed",
                error=str(exc),
            )
            raise ComposerSubmissionError(
                request_id=selected_request_id,
                status=str(failed_run.get("status") or "failed"),
                provider_error=str(exc),
            ) from exc
        return self._composer_submission(team=team, run=run)

    @staticmethod
    def _composer_submission(
        *,
        team: Mapping[str, Any],
        run: Mapping[str, Any],
        idempotent_replay: bool = False,
    ) -> dict[str, Any]:
        request = run.get("composer_request")
        if not isinstance(request, Mapping):
            raise MultiAgentRuntimeError("AgentTurn 缺少 durable composer request")
        return {
            "accepted": True,
            "session_id": str(team["root_session_id"]),
            "request_id": request["request_id"],
            "composer_mode": request["mode"],
            "agent_run_id": run["run_id"],
            "agent_turn_id": run["agent_turn_id"],
            "status": run.get("status"),
            "idempotent_replay": idempotent_replay,
        }

    def prompt(
        self,
        task_id: str,
        title: str,
        message: str,
        *,
        composer_mode: str = "queue_after_turn",
        request_id: str | None = None,
        actor: str = "user",
    ) -> str:
        """Compatibility wrapper returning the root session identity."""

        submission = self.submit_message(
            task_id,
            title,
            message,
            composer_mode=composer_mode,
            request_id=request_id,
            actor=actor,
        )
        return str(submission["session_id"])

    def _capture_source_seq_boundary(
        self,
        team: Mapping[str, Any],
    ) -> tuple[dict[str, int], bool]:
        """Capture fail-closed DSH watermarks before a new Agent run is queued."""

        root_session_id = str(team["root_session_id"])
        session_ids = {root_session_id}
        for agent in team.get("agents", {}).values():
            if not isinstance(agent, Mapping) or agent.get("lineage_verified") is not True:
                continue
            child_session_id = agent.get("dsh_session_id")
            if isinstance(child_session_id, str) and child_session_id:
                session_ids.add(child_session_id)
        floors: dict[str, int] = {}
        complete = True
        for session_id in sorted(session_ids):
            try:
                history = self.client.call(
                    "session.history",
                    {"sessionId": session_id, "maxMessages": 240},
                )
            except AgentRuntimeError:
                complete = False
                continue
            entries = history.get("events", []) if isinstance(history, Mapping) else []
            floors[session_id] = max(
                (
                    int(raw_event.get("seq", 0))
                    for entry in entries
                    if isinstance(entry, Mapping)
                    for raw_event in [entry.get("event", {})]
                    if isinstance(raw_event, Mapping)
                ),
                default=0,
            )
        return floors, complete and root_session_id in floors

    def _background_actions(self, task_id: str) -> list[dict[str, Any]]:
        owner = self.store.load_task(task_id)
        if owner.get("record_type") == "conversation_draft":
            # Intake has no TrainingTask, dataset, build or Run ownership yet.
            # Calling the task provider here would manufacture an observation
            # failure for a healthy greeting/capability conversation.
            return []
        provider = self.background_actions_provider
        if provider is None:
            return []
        try:
            observed = provider(task_id)
        except Exception as exc:
            return [
                {
                    "action_id": "background-actions:observation-error",
                    "action_type": "observation_error",
                    "task_id": task_id,
                    "status": "observation_degraded",
                    "running": False,
                    "worker_running": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ]
        selected: list[dict[str, Any]] = []
        for action in observed:
            if not isinstance(action, Mapping):
                continue
            value = deepcopy(dict(action))
            if value.get("task_id") != task_id:
                continue
            action_id = value.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                continue
            selected.append(value)
        return selected

    def conversation(self, task_id: str) -> dict[str, Any]:
        team = self.store.load_team(task_id)
        background_actions = self._background_actions(task_id)
        background_action_running = any(
            action.get("running") is True for action in background_actions
        )
        background_cancel_pending = any(
            action.get("cancel_requested") is True
            and action.get("running") is True
            for action in background_actions
        )
        stream_health = self._stream_health_snapshot()
        stream_is_degraded = stream_observation_degraded(
            stream_health,
            require_proven_healthy=team is not None,
        )
        if team is None:
            object_projection = project_conversation_objects(
                task_id=task_id,
                agent_runs=[],
                actions=[],
                background_actions=background_actions,
                pending=[],
                agent_response_running=False,
                observation_degraded=stream_is_degraded,
                cancellation_pending=background_cancel_pending,
                can_cancel=(
                    background_action_running and not background_cancel_pending
                ),
            )
            return {
                "schema_version": CONVERSATION_EVENT_SCHEMA_VERSION,
                "event_payload_mode": CONVERSATION_EVENT_PAYLOAD_MODE,
                "team_id": None,
                "session_id": None,
                "running": background_action_running,
                "execution_running": background_action_running,
                "agent_response_running": False,
                "background_action_running": background_action_running,
                "background_actions": background_actions,
                "interaction_state": (
                    "cancelling"
                    if background_cancel_pending
                    else "working"
                    if background_action_running
                    else "idle"
                ),
                "can_cancel_agent": (
                    background_action_running and not background_cancel_pending
                ),
                "items": [],
                "events": [],
                "actions": [],
                "action_schema_version": ACTION_SCHEMA_VERSION,
                "work_items": [],
                "work_item_schema_version": AGENT_WORK_ITEM_SCHEMA_VERSION,
                "agents": [],
                "delegations": [],
                "pending": [],
                "runs": [],
                "projection_health": (
                    "observation_degraded"
                    if stream_is_degraded
                    else "healthy"
                ),
                "projection_errors": [],
                "stream_health": stream_health,
                "synthesis_verdict_version": SYNTHESIS_VERDICT_VERSION,
                "supported_modes": sorted(SUPPORTED_COMPOSER_MODES),
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
        root_session_id = str(team["root_session_id"])
        try:
            history = self.client.call(
                "session.history",
                {"sessionId": root_session_id, "maxMessages": 240},
            )
            summaries = self.client.call("session.list", {})
        except AgentRuntimeError as exc:
            raise MultiAgentRuntimeError(f"无法读取多智能体会话：{exc}") from exc
        summary_items = summaries.get("items", []) if isinstance(summaries, dict) else []
        summaries_by_session = {
            str(item["sessionId"]): item
            for item in summary_items
            if isinstance(item, dict) and item.get("sessionId")
        }
        root_running = bool(summaries_by_session.get(root_session_id, {}).get("running"))
        projection = self.projector.project(
            task_id=task_id,
            team=team,
            history=history,
        )
        self.store.persist_projection(task_id=task_id, events=projection)
        # Reconcile once before child reads so real delegate tool results can
        # establish each DSH child session id. Do not close the task run while
        # a newly discovered child may still be working.
        team = self._reconcile_team(task_id=task_id, running=True)
        team, projection_errors = self._verify_child_lineage(
            task_id=task_id,
            team=team,
            summaries_by_session=summaries_by_session,
        )
        child_running = False
        observed_child_sessions: set[str] = set()
        for delegation in team.get("delegations", {}).values():
            if not isinstance(delegation, dict):
                continue
            if (
                delegation.get("lineage_verified") is not True
                or delegation.get("lineage_origin") != "subagent"
            ):
                continue
            child_session_id = delegation.get("dsh_session_id")
            if (
                not isinstance(child_session_id, str)
                or not child_session_id
                or child_session_id in observed_child_sessions
            ):
                continue
            observed_child_sessions.add(child_session_id)
            child_summary = summaries_by_session.get(child_session_id)
            if not isinstance(child_summary, dict):
                continue
            lineage_parent_session_id = delegation.get(
                "lineage_parent_session_id"
            )
            if (
                not isinstance(lineage_parent_session_id, str)
                or child_summary.get("parentSessionId") != lineage_parent_session_id
                or child_summary.get("origin") != "subagent"
            ):
                projection_errors.append(
                    {
                        "session_id": child_session_id,
                        "error": "dsh_subagent_lineage_mismatch",
                    }
                )
                continue
            child_running = child_running or bool(child_summary.get("running"))
            try:
                child_history = self.client.call(
                    "session.history",
                    {"sessionId": child_session_id, "maxMessages": 240},
                )
            except AgentRuntimeError as exc:
                projection_errors.append(
                    {"session_id": child_session_id, "error": str(exc)}
                )
                continue
            child_projection = self.projector.project(
                task_id=task_id,
                team=team,
                history=child_history,
                session_id=child_session_id,
                session_agent_id=str(
                    delegation.get("target_agent_id") or "specialist"
                ),
                session_agent_label=(
                    str(delegation["target_agent_label"])
                    if delegation.get("target_agent_label")
                    else None
                ),
            )
            self.store.persist_projection(task_id=task_id, events=child_projection)
        # Compatibility for DSH status-only child observations that predate a
        # concrete delegation record. They may answer native checkpoints but
        # still cannot become user-facing work items without a delegation.
        for agent in team.get("agents", {}).values():
            if (
                not isinstance(agent, dict)
                or agent.get("agent_id") == ROOT_PROFILE.agent_id
                or agent.get("lineage_verified") is not True
            ):
                continue
            child_session_id = agent.get("dsh_session_id")
            if (
                not isinstance(child_session_id, str)
                or not child_session_id
                or child_session_id in observed_child_sessions
            ):
                continue
            child_summary = summaries_by_session.get(child_session_id)
            if (
                not isinstance(child_summary, dict)
                or child_summary.get("origin") != "subagent"
                or child_summary.get("parentSessionId")
                != agent.get("lineage_parent_session_id")
            ):
                continue
            observed_child_sessions.add(child_session_id)
            child_running = child_running or bool(child_summary.get("running"))
            try:
                child_history = self.client.call(
                    "session.history",
                    {"sessionId": child_session_id, "maxMessages": 240},
                )
            except AgentRuntimeError as exc:
                projection_errors.append(
                    {"session_id": child_session_id, "error": str(exc)}
                )
                continue
            child_projection = self.projector.project(
                task_id=task_id,
                team=team,
                history=child_history,
                session_id=child_session_id,
                session_agent_id=str(agent.get("agent_id") or "specialist"),
                session_agent_label=(
                    str(agent["agent_label"]) if agent.get("agent_label") else None
                ),
            )
            self.store.persist_projection(task_id=task_id, events=child_projection)
        pending = self._pending(team, summaries_by_session=summaries_by_session)
        self._persist_pending_requested(task_id=task_id, team=team, pending=pending)
        pending = self._invalidate_pending_after_terminal(
            task_id=task_id,
            team=team,
            pending=pending,
        )
        # A native question/approval keeps the DSH turn open, but the model is
        # blocked on the human and is not actively executing. Keep the legacy
        # ``running`` flag for compatibility while exposing truthful execution
        # and cancellation semantics to AI-human clients.
        agent_response_running = (root_running or child_running) and not bool(
            pending
        )
        execution_running = agent_response_running or background_action_running
        running = execution_running or bool(pending)
        team = self._require_team(task_id)
        current_projection = self.store.current_projection_events(task_id)
        run_boundaries = self._run_boundaries(team)
        verdict_index = evaluate_synthesis_evidence(
            task_id=task_id,
            team_id=str(team["team_id"]),
            root_session_id=root_session_id,
            projector_revision=CONVERSATION_PROJECTOR_REVISION,
            events=current_projection,
            runs=run_boundaries,
            verified_children=self._verified_child_bindings(team, run_boundaries),
        )
        observation_degraded = bool(projection_errors) or stream_is_degraded
        team = self._reconcile_team(
            task_id=task_id,
            running=execution_running,
            waiting_for_human=bool(pending),
            verdict_index=verdict_index,
            observation_degraded=observation_degraded,
            session_terminal_observed=(
                root_session_id in summaries_by_session
                and not root_running
                and not child_running
                and not pending
            ),
        )
        agent_cancel_pending = any(
            isinstance(run, Mapping) and run.get("status") == "cancel_requested"
            for run in team.get("runs", [])
        )
        background_cancel_pending = any(
            action.get("cancel_requested") is True
            and action.get("running") is True
            for action in background_actions
        )
        cancellation_pending = agent_cancel_pending or background_cancel_pending
        lifecycle_running = running or cancellation_pending
        effective_projection = self._effective_projection_events(
            self.store.current_projection_events(task_id),
            verdict_index,
            allow_final=not observation_degraded and not lifecycle_running,
            suppression_reason=(
                "observation_degraded" if observation_degraded else "run_not_terminal"
            ),
        )
        pending_events = [
            event
            for event in self.store.list_events(task_id)
            if event.get("source") == "dsh_pending"
            and event.get("projector_revision")
            == CONVERSATION_PROJECTOR_REVISION
        ]
        events = sorted(
            [*effective_projection, *pending_events],
            key=lambda event: int(event.get("seq", 0)),
        )
        events = [deepcopy(event) for event in events]
        for event in events:
            canonical_agent_turn_id = _agent_turn_id_for_run(
                team,
                event.get("agent_run_id"),
            )
            if canonical_agent_turn_id is not None:
                event["agent_turn_id"] = canonical_agent_turn_id
        actions: list[dict[str, Any]] = []
        for action in classify_conversation_actions(
            task_id=task_id,
            projector_revision=CONVERSATION_PROJECTOR_REVISION,
            events=effective_projection,
        ):
            value = asdict(action)
            canonical_agent_turn_id = _agent_turn_id_for_run(
                team,
                value.get("agent_run_id"),
            )
            if canonical_agent_turn_id is not None:
                value["agent_turn_id"] = canonical_agent_turn_id
            value["object_refs"] = [ref.as_dict() for ref in action.object_refs]
            actions.append(value)
        work_items = self._agent_work_items(
            task_id=task_id,
            team=team,
            actions=actions,
            events=effective_projection,
        )
        delegation_statuses = {
            str(value.get("delegation_id")): value.get("status")
            for value in team.get("delegations", {}).values()
            if isinstance(value, dict) and value.get("delegation_id")
        }
        conversation_items: list[dict[str, Any]] = []
        for event in events:
            if (
                event.get("source") not in {"dsh", "dsh_pending"}
                or event.get("projector_revision") != CONVERSATION_PROJECTOR_REVISION
            ):
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            if event.get("event_type") in {"approval", "question"} and not payload.get("rpc_id"):
                # Live human checkpoints come from the WebSocket pending
                # channel, which owns their rpc identity and answer contract.
                continue
            if (
                event.get("event_type") == "specialist_status"
                and event.get("agent_id") == ROOT_PROFILE.agent_id
                and event.get("status") == "observed"
            ):
                continue
            selected = deepcopy(event)
            canonical_agent_turn_id = _agent_turn_id_for_run(
                team,
                selected.get("agent_run_id"),
            )
            if canonical_agent_turn_id is not None:
                selected["agent_turn_id"] = canonical_agent_turn_id
            call_id = payload.get("call_id")
            if (
                event.get("event_type") == "delegation"
                and isinstance(call_id, str)
                and delegation_statuses.get(call_id)
            ):
                selected["status"] = delegation_statuses[call_id]
            if (
                event.get("agent_id") == ROOT_PROFILE.agent_id
                and event.get("event_type") in {"delegation", "specialist_output"}
                and not payload.get("target_agent_id")
            ):
                # Older projections classified list_agents as a delegation.
                # Preserve the observed audit event while presenting it as the
                # coordinator control tool it actually was.
                result_event = "result" in payload
                selected["category"] = "tool"
                selected["type"] = "tool_result" if result_event else "tool_call"
                selected["event_type"] = selected["type"]
            conversation_items.append(selected)
        object_projection = project_conversation_objects(
            task_id=task_id,
            agent_runs=team["runs"],
            actions=actions,
            background_actions=background_actions,
            pending=pending,
            agent_response_running=agent_response_running,
            observation_degraded=observation_degraded,
            cancellation_pending=cancellation_pending,
            can_cancel=execution_running and not cancellation_pending,
        )
        response = {
            "schema_version": CONVERSATION_EVENT_SCHEMA_VERSION,
            "team_id": team["team_id"],
            "session_id": root_session_id,
            "running": lifecycle_running,
            "execution_running": execution_running,
            "agent_response_running": agent_response_running,
            "background_action_running": background_action_running,
            "background_actions": background_actions,
            "interaction_state": (
                "cancelling"
                if cancellation_pending
                else "waiting_for_human"
                if pending
                else "working"
                if execution_running
                else "terminal"
                if team.get("runs")
                and team["runs"][-1].get("status")
                in {"completed", "failed", "cancelled", "interrupted"}
                else "idle"
            ),
            "can_cancel_agent": execution_running and not cancellation_pending,
            "items": conversation_items,
            "events": events,
            "actions": actions,
            "action_schema_version": ACTION_SCHEMA_VERSION,
            "work_items": work_items,
            "work_item_schema_version": AGENT_WORK_ITEM_SCHEMA_VERSION,
            "agents": list(team["agents"].values()),
            "delegations": list(team["delegations"].values()),
            "pending": pending,
            "runs": deepcopy(team["runs"]),
            "projection_health": (
                "observation_degraded" if observation_degraded else "healthy"
            ),
            "projection_errors": deepcopy(projection_errors),
            "stream_health": stream_health,
            "synthesis_verdict_version": verdict_index.version,
            "supported_modes": sorted(SUPPORTED_COMPOSER_MODES),
            "audit_event_count": len(self.store.list_events(task_id)),
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
        try:
            return compact_conversation_response(response)
        except ConversationPayloadCompactionError as exc:
            raise MultiAgentRuntimeError(
                "对话结果过大且缺少可追溯事件身份，已停止返回不完整投影"
            ) from exc

    def _agent_work_items(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        actions: Sequence[Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Project verified native subagent delegations into user-facing work.

        This is deliberately a derived read model. It never creates work from
        coordinator narration, role names, or an unverified child session.
        """

        raw_delegations = team.get("delegations")
        raw_runs = team.get("runs")
        if (
            not isinstance(raw_delegations, Mapping)
            or not isinstance(raw_runs, list)
        ):
            return []
        run_ids = {
            str(run["run_id"])
            for run in raw_runs
            if isinstance(run, Mapping)
            and isinstance(run.get("run_id"), str)
            and run.get("run_id")
        }
        projected: list[dict[str, Any]] = []
        for raw_delegation in raw_delegations.values():
            if not isinstance(raw_delegation, Mapping):
                continue
            delegation = dict(raw_delegation)
            delegation_id = delegation.get("delegation_id")
            agent_run_id = delegation.get("agent_run_id")
            target_agent_id = delegation.get("target_agent_id")
            child_session_id = delegation.get("dsh_session_id")
            if not all(
                isinstance(value, str) and bool(value)
                for value in (
                    delegation_id,
                    agent_run_id,
                    target_agent_id,
                    child_session_id,
                )
            ):
                continue
            delegation_id = str(delegation_id)
            agent_run_id = str(agent_run_id)
            target_agent_id = str(target_agent_id)
            child_session_id = str(child_session_id)
            if agent_run_id not in run_ids:
                continue
            identity = DshConversationV2Projector._verified_child_projection_identity(
                team=team,
                session_id=child_session_id,
                expected_agent_id=target_agent_id,
            )
            if (
                identity is None
                or identity.get("delegation_id") != delegation_id
                or identity.get("agent_run_id") != agent_run_id
            ):
                continue
            profile = PROFILE_BY_ID.get(target_agent_id)
            agent = {
                "agent_id": target_agent_id,
                "role_id": profile.agent_id if profile else target_agent_id,
                "agent_label": identity.get("agent_label")
                or delegation.get("target_agent_label")
                or (profile.agent_label if profile else None),
                "status": delegation.get("status") or "observed",
            }
            selected_actions = [
                deepcopy(dict(action))
                for action in actions
                if action.get("task_id") == task_id
                and action.get("agent_run_id") == agent_run_id
                and action.get("delegation_id") == delegation_id
            ]
            selected_events = [
                event
                for event in events
                if event.get("task_id") == task_id
                and event.get("agent_run_id") == agent_run_id
                and (
                    event.get("delegation_id") == delegation_id
                    or event.get("session_id") == child_session_id
                    or (
                        event.get("agent_id") == target_agent_id
                        and self._find_session_id(event.get("payload"))
                        == child_session_id
                    )
                )
            ]
            observed_sequences = [
                value
                for event in selected_events
                for value in (event.get("seq"),)
                if isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
            ]
            observed_started_sequence = min(observed_sequences, default=None)
            observed_updated_sequence = max(observed_sequences, default=None)
            status = self._agent_work_item_status(
                delegation=delegation,
                agent=agent,
                actions=selected_actions,
                events=selected_events,
            )
            object_refs = self._agent_work_item_object_refs(selected_actions)
            failure = self._agent_work_item_failure(
                actions=selected_actions,
                events=selected_events,
            )
            timestamps = [
                value
                for value in (
                    delegation.get("started_at_utc"),
                    delegation.get("updated_at_utc"),
                    *(action.get("started_at_utc") for action in selected_actions),
                    *(action.get("ended_at_utc") for action in selected_actions),
                    *(event.get("timestamp_utc") for event in selected_events),
                )
                if isinstance(value, str) and value
            ]
            started_at = (
                delegation.get("started_at_utc")
                if isinstance(delegation.get("started_at_utc"), str)
                and delegation.get("started_at_utc")
                else min(timestamps, default=None)
            )
            updated_at = max(timestamps, default=started_at)
            assignment = delegation.get("assignment")
            assignment = (
                deepcopy(dict(assignment))
                if isinstance(assignment, Mapping)
                else {"summary": None, "source_field": None}
            )
            projected.append(
                {
                    "schema_version": AGENT_WORK_ITEM_SCHEMA_VERSION,
                    "work_item_id": (
                        "agent-work:"
                        + _json_digest(
                            {
                                "task_id": task_id,
                                "agent_run_id": agent_run_id,
                                "delegation_id": delegation_id,
                            }
                        )[:20]
                    ),
                    "task_id": task_id,
                    "agent_run_id": agent_run_id,
                    "delegation_id": delegation_id,
                    "parent_delegation_id": delegation.get(
                        "parent_delegation_id"
                    ),
                    "child_session_id": child_session_id,
                    "lineage_verified": True,
                    "role": {
                        "agent_id": target_agent_id,
                        "role_id": agent.get("role_id") or target_agent_id,
                        "label": agent.get("agent_label")
                        or delegation.get("target_agent_label"),
                    },
                    "assignment": assignment,
                    "status": status,
                    "actions": selected_actions,
                    "object_refs": object_refs,
                    "failure": failure,
                    # Projected DSH timestamps are optional and older sessions
                    # may expose them as epoch numbers.  The persisted event
                    # sequence is the canonical ordering signal for repeated
                    # delegations of the same specialist role.
                    "observed_started_sequence": observed_started_sequence,
                    "observed_updated_sequence": observed_updated_sequence,
                    "started_at_utc": started_at,
                    "updated_at_utc": updated_at,
                    "ended_at_utc": (
                        updated_at
                        if status in {"completed", "failed", "cancelled"}
                        else None
                    ),
                }
            )
        return sorted(
            projected,
            key=lambda item: (
                (
                    int(item["observed_updated_sequence"])
                    if isinstance(item.get("observed_updated_sequence"), int)
                    else -1
                ),
                str(item.get("started_at_utc") or ""),
                str(item.get("delegation_id") or ""),
            ),
        )

    @staticmethod
    def _agent_work_item_status(
        *,
        delegation: Mapping[str, Any],
        agent: Mapping[str, Any],
        actions: Sequence[Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
    ) -> str:
        statuses = {
            str(value)
            for value in (
                delegation.get("status"),
                agent.get("status"),
                *(action.get("status") for action in actions),
                *(event.get("status") for event in events),
            )
            if isinstance(value, str) and value
        }
        if statuses & {"failed", "identity_error"}:
            return "failed"
        if statuses & {"cancelled", "interrupted"}:
            return "cancelled"
        if "completed" in statuses and not statuses & {
            "running",
            "queued",
            "pending",
        }:
            return "completed"
        if (
            delegation.get("status") == "completed"
            or agent.get("status") == "completed"
        ):
            return "completed"
        return "active"

    @staticmethod
    def _agent_work_item_object_refs(
        actions: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            refs = action.get("object_refs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, Mapping):
                    continue
                value = dict(ref)
                key = _json_digest(value)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(deepcopy(value))
        return selected

    @staticmethod
    def _agent_work_item_failure(
        *,
        actions: Sequence[Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        # A typed DSH turn error is more informative than the generic paired
        # tool-result failure, so prefer the latest observed event error.
        for event in reversed(list(events)):
            if event.get("status") != "failed":
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            raw_error = payload.get("error")
            if isinstance(raw_error, Mapping):
                failure = deepcopy(dict(raw_error))
            elif isinstance(raw_error, str) and raw_error.strip():
                failure = {
                    "message": raw_error.strip(),
                    "source": "dsh_event",
                }
            elif isinstance(payload.get("text"), str) and payload.get("text"):
                failure = {
                    "message": str(payload["text"]),
                    "source": "dsh_event",
                }
            else:
                continue
            failure["event_id"] = event.get("event_id")
            return failure
        for action in reversed(list(actions)):
            if action.get("status") not in {"failed", "identity_error"}:
                continue
            raw_error = action.get("error")
            if not isinstance(raw_error, Mapping):
                continue
            failure = deepcopy(dict(raw_error))
            failure.setdefault("source", "conversation_action")
            failure["action_id"] = action.get("action_id")
            if isinstance(action.get("event_result_ref"), Mapping):
                failure["event_result_ref"] = deepcopy(
                    dict(action["event_result_ref"])
                )
            return failure
        return None

    def conversation_event_result(
        self,
        task_id: str,
        event_id: str,
        *,
        projector_revision: str,
    ) -> dict[str, Any]:
        if projector_revision != CONVERSATION_PROJECTOR_REVISION:
            raise FileNotFoundError("conversation event not found")
        event = self.store.get_projected_event(
            task_id,
            event_id,
            projector_revision=projector_revision,
        )
        payload = event.get("payload")
        if (
            event.get("source") != "dsh"
            or event.get("event_type")
            not in {"tool_result", "specialist_output", "delegation"}
            or not isinstance(payload, Mapping)
            or "result" not in payload
        ):
            raise FileNotFoundError("conversation tool result not found")
        return {
            "event": event,
            "read_only": True,
            "completion_evidence": False,
        }

    def cancel(
        self,
        task_id: str,
        *,
        actor: str = "user",
        reason: str = "User requested stop",
        cancellation_kind: str = "user_requested",
        scope: str = "task_execution",
    ) -> dict[str, Any]:
        owner = self.store.load_task(task_id)
        conversation_only = owner.get("record_type") == "conversation_draft"
        if actor not in {"user", "operator", "system"}:
            raise ValueError("actor 必须是 user、operator 或 system")
        if cancellation_kind not in {
            "user_requested",
            "operator_requested",
            "safety_stop",
            "system_shutdown",
            "superseded",
        }:
            raise ValueError("cancellation_kind 非法")
        if cancellation_kind == "safety_stop" and actor == "user":
            raise ValueError("safety_stop 必须由 operator 或 system 发起")
        if cancellation_kind == "system_shutdown" and actor != "system":
            raise ValueError("system_shutdown 必须由 system 发起")
        if cancellation_kind == "operator_requested" and actor != "operator":
            raise ValueError("operator_requested 必须由 operator 发起")
        selected_reason = reason.strip() if isinstance(reason, str) else ""
        if not selected_reason:
            raise ValueError("reason 不能为空")
        cancellation = {
            "cancellation_id": f"cancel-request-{uuid4().hex}",
            "actor": actor,
            "kind": cancellation_kind,
            "reason": selected_reason,
            "scope": scope,
            "requested_at_utc": _utc_now(),
        }
        team = self.store.load_team(task_id)
        session_ids: list[str] = []
        if team is not None:
            session_ids.append(str(team["root_session_id"]))
            session_ids.extend(
                sorted(
                    {
                        str(agent["dsh_session_id"])
                        for agent in team.get("agents", {}).values()
                        if isinstance(agent, Mapping)
                        and agent.get("lineage_verified") is True
                        and isinstance(agent.get("dsh_session_id"), str)
                        and agent.get("dsh_session_id") != team["root_session_id"]
                        and agent.get("status")
                        not in {"completed", "failed", "cancelled", "interrupted"}
                    }
                )
            )
        cancelled_session_ids: list[str] = []
        cascade_errors: list[dict[str, str]] = []
        for session_id in session_ids:
            try:
                self.client.call(
                    "session.cancel",
                    {"sessionId": session_id},
                )
                cancelled_session_ids.append(session_id)
            except AgentRuntimeError as exc:
                cascade_errors.append(
                    {"target": f"dsh_session:{session_id}", "error": str(exc)}
                )
        background_actions: list[dict[str, Any]] = []
        if self.background_actions_canceller is not None and not conversation_only:
            try:
                background_actions = [
                    deepcopy(dict(action))
                    for action in self.background_actions_canceller(
                        task_id,
                        cancellation,
                    )
                    if isinstance(action, Mapping)
                ]
            except Exception as exc:
                cascade_errors.append(
                    {
                        "target": "task_background_actions",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        runs = team.get("runs", []) if team is not None else []
        for run in runs:
            if not isinstance(run, Mapping) or run.get("status") not in {
                "queued",
                "running",
                "waiting_for_human",
            }:
                continue
            run_id = run.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                continue
            self.store.update_run(
                task_id=task_id,
                run_id=run_id,
                status="cancel_requested",
                evidence={"cancel_request": cancellation},
            )
        if team is not None:
            self.store.append_event(
                task_id=task_id,
                event={
                    "source": "runtime",
                    "source_key": f"runtime:cancel:{uuid4().hex}",
                    "timestamp_utc": _utc_now(),
                    "agent_id": ROOT_PROFILE.agent_id,
                    "agent_label": ROOT_PROFILE.agent_label,
                    "category": "agent_status",
                    "type": "agent.cancel_cascade_requested",
                    "status": "cancel_requested",
                    "payload": {
                        "cancelled_session_ids": cancelled_session_ids,
                        "background_actions": background_actions,
                        "cascade_errors": cascade_errors,
                        "cancellation": cancellation,
                    },
                },
            )
        if cascade_errors:
            raise MultiAgentRuntimeError(
                "取消请求未能覆盖全部后台工作："
                + "; ".join(item["error"] for item in cascade_errors)
            )
        return {
            "accepted": True,
            "cancelled_session_ids": cancelled_session_ids,
            "background_actions": background_actions,
            "cancellation": cancellation,
        }

    def answer_approval(
        self,
        task_id: str,
        rpc_id: str,
        outcome: str,
    ) -> None:
        team = self._require_team(task_id)
        session_id, item = self._pending_item(
            team,
            rpc_id,
            expected_kind="approval",
        )
        try:
            self.client.respond(
                rpc_id,
                {
                    "sessionId": session_id,
                    "approvalId": item.get("approval_id"),
                    "outcome": outcome,
                },
            )
        except AgentRuntimeError as exc:
            raise MultiAgentRuntimeError(f"无法提交批准决定：{exc}") from exc
        self._persist_pending_resolved(
            task_id=task_id,
            team=team,
            session_id=session_id,
            item=item,
            outcome=outcome,
        )
        self.events.resolve_local(session_id, rpc_id)

    def answer_question(
        self,
        task_id: str,
        rpc_id: str,
        answers: list[dict[str, Any]],
    ) -> None:
        team = self._require_team(task_id)
        session_id, item = self._pending_item(
            team,
            rpc_id,
            expected_kind="question",
        )
        validated_answers = self._validate_question_answers(item, answers)
        try:
            self.client.respond(
                rpc_id,
                {
                    "sessionId": session_id,
                    "answer": {"answers": validated_answers},
                },
            )
        except AgentRuntimeError as exc:
            raise MultiAgentRuntimeError(f"无法提交问题答案：{exc}") from exc
        self._persist_pending_resolved(
            task_id=task_id,
            team=team,
            session_id=session_id,
            item=item,
            outcome="answered",
            answer_count=len(validated_answers),
        )
        self.events.resolve_local(session_id, rpc_id)

    @staticmethod
    def _validate_question_answers(
        item: Mapping[str, Any],
        answers: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        questions = item.get("questions")
        if not isinstance(questions, list) or not questions:
            raise HumanCheckpointConflictError(
                "当前待决问题缺少可验证的问题契约，请刷新任务后重试"
            )
        if len(answers) != len(questions):
            raise HumanCheckpointConflictError(
                "提交的回答数量与当前待决问题不匹配，请刷新任务后重试"
            )

        validated: list[dict[str, Any]] = []
        for index, (question, answer) in enumerate(zip(questions, answers, strict=True)):
            if not isinstance(question, Mapping):
                raise HumanCheckpointConflictError(
                    "当前待决问题契约无效，请刷新任务后重试"
                )
            question_id = question.get("id")
            if not isinstance(question_id, str) or not question_id.strip():
                raise HumanCheckpointConflictError(
                    "当前待决问题缺少稳定身份，请刷新任务后重试"
                )
            if not isinstance(answer, Mapping):
                raise HumanCheckpointAnswerError(
                    f"第 {index + 1} 个回答必须是对象"
                )
            answer_id = answer.get("id", answer.get("questionId"))
            if answer_id != question_id:
                raise HumanCheckpointConflictError(
                    "提交的 question id 与当前待决问题不匹配，请刷新任务后重试"
                )

            options = question.get("options", [])
            if options is None:
                options = []
            if not isinstance(options, list):
                raise HumanCheckpointConflictError(
                    f"待决问题 {question_id} 的选项契约无效，请刷新任务后重试"
                )
            option_labels: list[str] = []
            for option in options:
                if not isinstance(option, Mapping):
                    raise HumanCheckpointConflictError(
                        f"待决问题 {question_id} 的选项契约无效，请刷新任务后重试"
                    )
                label = option.get("label")
                if not isinstance(label, str) or not label:
                    raise HumanCheckpointConflictError(
                        f"待决问题 {question_id} 的选项缺少有效标签，请刷新任务后重试"
                    )
                option_labels.append(label)
            if len(set(option_labels)) != len(option_labels):
                raise HumanCheckpointConflictError(
                    f"待决问题 {question_id} 包含重复选项，请刷新任务后重试"
                )

            raw_selected = answer.get("selected")
            raw_custom = answer.get("custom")
            if raw_selected is None and "answer" in answer:
                legacy_answer = answer.get("answer")
                if not isinstance(legacy_answer, str):
                    raise HumanCheckpointAnswerError(
                        f"问题 {question_id} 的 answer 必须是文本"
                    )
                if legacy_answer in option_labels:
                    raw_selected = [legacy_answer]
                else:
                    raw_selected = []
                    raw_custom = legacy_answer
            if not isinstance(raw_selected, list) or not all(
                isinstance(value, str) and value for value in raw_selected
            ):
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 的 selected 必须是非空文本数组"
                )
            if len(set(raw_selected)) != len(raw_selected):
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 不能重复选择同一选项"
                )
            unknown = [value for value in raw_selected if value not in option_labels]
            if unknown:
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 包含当前 checkpoint 未提供的选项"
                )

            multi_select = question.get("multiSelect", False)
            if not isinstance(multi_select, bool):
                raise HumanCheckpointConflictError(
                    f"待决问题 {question_id} 的 multiSelect 契约无效，请刷新任务后重试"
                )
            required = question.get("required", True)
            if not isinstance(required, bool):
                raise HumanCheckpointConflictError(
                    f"待决问题 {question_id} 的 required 契约无效，请刷新任务后重试"
                )
            allow_custom = question.get(
                "allow_custom", question.get("allowCustom", True)
            )
            if not isinstance(allow_custom, bool):
                raise HumanCheckpointConflictError(
                    f"待决问题 {question_id} 的 allow_custom 契约无效，请刷新任务后重试"
                )

            custom: str | None = None
            if raw_custom is not None:
                if not isinstance(raw_custom, str) or not raw_custom.strip():
                    raise HumanCheckpointAnswerError(
                        f"问题 {question_id} 的 custom 必须是非空文本"
                    )
                if not allow_custom:
                    raise HumanCheckpointAnswerError(
                        f"问题 {question_id} 不允许自定义回答"
                    )
                custom = raw_custom
            if not multi_select and len(raw_selected) > 1:
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 是单选题，只能选择一个选项"
                )
            if not multi_select and raw_selected and custom is not None:
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 是单选题，选项和自定义回答不能同时提交"
                )
            if required and not raw_selected and custom is None:
                raise HumanCheckpointAnswerError(
                    f"问题 {question_id} 是必答题"
                )

            selected_answer: dict[str, Any] = {
                "id": question_id,
                "selected": list(raw_selected),
            }
            if custom is not None:
                selected_answer["custom"] = custom
            validated.append(selected_answer)
        return validated

    def _require_team(self, task_id: str) -> dict[str, Any]:
        team = self.store.load_team(task_id)
        if team is None:
            raise MultiAgentRuntimeError("这个 TrainingTask 还没有多智能体会话")
        return team

    @staticmethod
    def _pending_fallback_identity(
        team: Mapping[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        """Bind an early websocket checkpoint to its durable AgentTurn.

        The pending channel can lead session.history by one observation.  A
        verified child delegation is the strongest fallback; the root session
        belongs to the latest queued run.  This deliberately does not invent a
        raw DSH ``turn_id`` or ``call_id``.
        """

        agent_run_id: str | None = None
        for delegation in reversed(list(team.get("delegations", {}).values())):
            if (
                isinstance(delegation, Mapping)
                and delegation.get("dsh_session_id") == session_id
                and delegation.get("lineage_verified") is True
                and delegation.get("lineage_origin") == "subagent"
                and isinstance(delegation.get("agent_run_id"), str)
            ):
                agent_run_id = str(delegation["agent_run_id"])
                break
        if agent_run_id is None and session_id == team.get("root_session_id"):
            runs = [run for run in team.get("runs", []) if isinstance(run, Mapping)]
            if runs and isinstance(runs[-1].get("run_id"), str):
                agent_run_id = str(runs[-1]["run_id"])
        agent_turn_id = _agent_turn_id_for_run(team, agent_run_id)
        return {
            "agent_run_id": agent_run_id,
            "agent_turn_id": agent_turn_id,
        }

    def _pending(
        self,
        team: Mapping[str, Any],
        *,
        summaries_by_session: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        if summaries_by_session is None:
            try:
                summaries = self.client.call("session.list", {})
            except AgentRuntimeError as exc:
                raise MultiAgentRuntimeError(
                    f"无法验证 Agent 待决请求血缘：{exc}"
                ) from exc
            summary_items = (
                summaries.get("items", []) if isinstance(summaries, dict) else []
            )
            summaries_by_session = {
                str(item["sessionId"]): item
                for item in summary_items
                if isinstance(item, dict) and item.get("sessionId")
            }
        root_session_id = str(team["root_session_id"])
        session_ids = {root_session_id}
        for delegation in team.get("delegations", {}).values():
            if (
                not isinstance(delegation, Mapping)
                or delegation.get("lineage_verified") is not True
                or delegation.get("lineage_origin") != "subagent"
            ):
                continue
            session_id = delegation.get("dsh_session_id")
            if (
                not isinstance(session_id, str)
                or not session_id
            ):
                continue
            summary = summaries_by_session.get(session_id)
            if (
                isinstance(summary, Mapping)
                and summary.get("parentSessionId")
                == delegation.get("lineage_parent_session_id")
                and summary.get("origin") == "subagent"
            ):
                session_ids.add(session_id)
        for agent in team.get("agents", {}).values():
            if not isinstance(agent, Mapping):
                continue
            session_id = agent.get("dsh_session_id")
            if (
                agent.get("lineage_verified") is not True
                or agent.get("lineage_origin") != "subagent"
                or not isinstance(session_id, str)
                or not session_id
            ):
                continue
            summary = summaries_by_session.get(session_id)
            if (
                isinstance(summary, Mapping)
                and summary.get("parentSessionId")
                == agent.get("lineage_parent_session_id")
                and summary.get("origin") == "subagent"
            ):
                session_ids.add(session_id)
        for session_id in session_ids:
            for item in self.events.pending_for(session_id):
                selected = {**item, "session_id": session_id}
                observed = self._pending_origin_identity(
                    task_id=str(team["task_id"]),
                    session_id=session_id,
                    item=selected,
                )
                fallback = self._pending_fallback_identity(team, session_id)
                agent_run_id = (
                    observed.get("agent_run_id")
                    or selected.get("agent_run_id")
                    or fallback.get("agent_run_id")
                )
                agent_turn_id = _agent_turn_id_for_run(team, agent_run_id) or (
                    selected.get("agent_turn_id")
                    or fallback.get("agent_turn_id")
                )
                if isinstance(agent_run_id, str) and agent_run_id:
                    selected["agent_run_id"] = agent_run_id
                if isinstance(agent_turn_id, str) and agent_turn_id:
                    selected["agent_turn_id"] = agent_turn_id
                for field in ("turn_id", "call_id"):
                    if observed.get(field):
                        selected[field] = observed[field]
                values.append(selected)
        return sorted(values, key=lambda item: str(item.get("received_at") or ""))

    def _pending_item(
        self,
        team: Mapping[str, Any],
        rpc_id: str,
        *,
        expected_kind: str,
    ) -> tuple[str, dict[str, Any]]:
        pending = self._pending(team)
        self._persist_pending_requested(
            task_id=str(team["task_id"]),
            team=team,
            pending=pending,
        )
        pending = self._invalidate_pending_after_terminal(
            task_id=str(team["task_id"]),
            team=team,
            pending=pending,
        )
        for item in pending:
            if item.get("rpc_id") == rpc_id:
                if item.get("kind") != expected_kind:
                    raise HumanCheckpointConflictError(
                        f"待决请求类型不匹配：需要 {expected_kind}"
                    )
                return str(item["session_id"]), item
        raise HumanCheckpointConflictError("这条待决请求已经失效")

    @staticmethod
    def _timestamp_seconds(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            selected = float(value)
            return selected / 1000.0 if selected > 1_000_000_000_000 else selected
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None

    def _invalidate_pending_after_terminal(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        pending: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Retire a checkpoint whose DSH turn already ended unsuccessfully.

        DSH can leave a durable question/approval request behind after the
        owning turn is interrupted.  Such an RPC rejects every answer and must
        not remain rendered as a live human checkpoint.
        """

        terminal_by_session: dict[str, tuple[float, Mapping[str, Any]]] = {}
        for event in self.store.current_projection_events(task_id):
            if event.get("event_type") not in {"turn_error", "turn_cancelled"}:
                continue
            session_id = event.get("session_id")
            timestamp = self._timestamp_seconds(event.get("timestamp_utc"))
            if not isinstance(session_id, str) or not session_id or timestamp is None:
                continue
            current = terminal_by_session.get(session_id)
            if current is None or timestamp >= current[0]:
                terminal_by_session[session_id] = (timestamp, event)

        active: list[dict[str, Any]] = []
        for raw_item in pending:
            item = dict(raw_item)
            session_id = item.get("session_id")
            received_at = self._timestamp_seconds(item.get("received_at"))
            terminal = (
                terminal_by_session.get(session_id)
                if isinstance(session_id, str)
                else None
            )
            if (
                terminal is None
                or received_at is None
                or terminal[0] < received_at
            ):
                active.append(item)
                continue
            self._persist_pending_resolved(
                task_id=task_id,
                team=team,
                session_id=str(session_id),
                item=item,
                outcome="invalidated_by_turn_terminal",
                terminal_event=terminal[1],
            )
            self.events.resolve_local(str(session_id), str(item.get("rpc_id") or ""))
        return active

    def _verify_child_lineage(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        summaries_by_session: Mapping[str, Mapping[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Verify every observed delegation, including repeated use of one role.

        ``agents`` is a role-level summary and therefore cannot be the source of
        truth for child ownership when the coordinator delegates the same role
        more than once.  Lineage is persisted on the delegation instance; the
        role summary is retained only as a compatibility/read-model aggregate.
        """

        root_session_id = str(team["root_session_id"])
        agents = deepcopy(team.get("agents", {}))
        delegations = deepcopy(team.get("delegations", {}))
        errors: list[dict[str, str]] = []
        changed = False
        delegations_by_session: dict[str, list[dict[str, Any]]] = {}
        for raw in delegations.values():
            if not isinstance(raw, dict):
                continue
            session_id = raw.get("dsh_session_id")
            if isinstance(session_id, str) and session_id:
                delegations_by_session.setdefault(session_id, []).append(raw)

        def verified_parent_chain(
            session_id: str,
            visiting: frozenset[str] = frozenset(),
        ) -> bool:
            if session_id == root_session_id:
                return True
            if session_id in visiting:
                return False
            bindings = delegations_by_session.get(session_id, [])
            if len(bindings) != 1:
                return False
            binding = bindings[0]
            summary = summaries_by_session.get(session_id)
            parent_session_id = (
                summary.get("parentSessionId")
                if isinstance(summary, Mapping)
                else None
            )
            if (
                not isinstance(summary, Mapping)
                or summary.get("origin") != "subagent"
                or not isinstance(parent_session_id, str)
                or binding.get("source_session_id") != parent_session_id
            ):
                return False
            return verified_parent_chain(
                parent_session_id,
                visiting | frozenset({session_id}),
            )

        for delegation in delegations.values():
            if not isinstance(delegation, dict):
                continue
            candidate = delegation.get("dsh_session_id")
            if not isinstance(candidate, str) or not candidate:
                continue
            summary = summaries_by_session.get(candidate)
            parent_session_id = (
                summary.get("parentSessionId")
                if isinstance(summary, Mapping)
                else None
            )
            verified = (
                isinstance(summary, Mapping)
                and summary.get("origin") == "subagent"
                and isinstance(parent_session_id, str)
                and verified_parent_chain(candidate)
            )
            before = deepcopy(delegation)
            if verified:
                already_verified = (
                    delegation.get("lineage_verified") is True
                    and delegation.get("lineage_parent_session_id")
                    == parent_session_id
                    and delegation.get("lineage_origin") == "subagent"
                )
                delegation["lineage_verified"] = True
                delegation["lineage_parent_session_id"] = parent_session_id
                delegation["lineage_origin"] = "subagent"
                if not already_verified:
                    delegation["lineage_verified_at_utc"] = _utc_now()
                delegation.pop("lineage_error", None)
            else:
                delegation["lineage_verified"] = False
                delegation["lineage_error"] = "dsh_subagent_lineage_mismatch"
                delegation.pop("lineage_parent_session_id", None)
                delegation.pop("lineage_origin", None)
                delegation.pop("lineage_verified_at_utc", None)
            changed = changed or delegation != before

        # Preserve the legacy role-level projection, selecting the latest
        # delegation for that role.  Historical delegation instances remain
        # independently verifiable through ``team.delegations``.
        for agent_id, agent in agents.items():
            if not isinstance(agent, dict) or agent_id == ROOT_PROFILE.agent_id:
                continue
            matches = [
                value
                for value in delegations.values()
                if isinstance(value, Mapping)
                and value.get("target_agent_id") == agent_id
                and isinstance(value.get("dsh_session_id"), str)
                and value.get("dsh_session_id")
            ]
            if not matches:
                candidate = agent.get("candidate_dsh_session_id") or agent.get(
                    "dsh_session_id"
                )
                if not isinstance(candidate, str) or not candidate:
                    continue
                summary = summaries_by_session.get(candidate)
                parent_session_id = (
                    summary.get("parentSessionId")
                    if isinstance(summary, Mapping)
                    else None
                )
                before = deepcopy(agent)
                if (
                    isinstance(summary, Mapping)
                    and summary.get("origin") == "subagent"
                    and parent_session_id == root_session_id
                ):
                    agent["dsh_session_id"] = candidate
                    agent.pop("candidate_dsh_session_id", None)
                    agent["lineage_verified"] = True
                    agent["lineage_parent_session_id"] = parent_session_id
                    agent["lineage_origin"] = "subagent"
                    agent["lineage_verified_at_utc"] = agent.get(
                        "lineage_verified_at_utc"
                    ) or _utc_now()
                    agent.pop("lineage_error", None)
                else:
                    agent["candidate_dsh_session_id"] = candidate
                    agent.pop("dsh_session_id", None)
                    agent["lineage_verified"] = False
                    agent["lineage_error"] = "dsh_subagent_lineage_mismatch"
                    agent.pop("lineage_parent_session_id", None)
                    agent.pop("lineage_origin", None)
                    agent.pop("lineage_verified_at_utc", None)
                    errors.append(
                        {
                            "session_id": candidate,
                            "error": "dsh_subagent_lineage_mismatch",
                        }
                    )
                changed = changed or agent != before
                continue
            selected = matches[-1]
            candidate = str(selected["dsh_session_id"])
            before = deepcopy(agent)
            if selected.get("lineage_verified") is True:
                agent["dsh_session_id"] = candidate
                agent.pop("candidate_dsh_session_id", None)
                agent["lineage_verified"] = True
                agent["lineage_parent_session_id"] = selected.get(
                    "lineage_parent_session_id"
                )
                agent["lineage_origin"] = "subagent"
                agent["lineage_verified_at_utc"] = selected.get(
                    "lineage_verified_at_utc"
                ) or _utc_now()
                agent.pop("lineage_error", None)
            else:
                agent["candidate_dsh_session_id"] = candidate
                agent.pop("dsh_session_id", None)
                agent["lineage_verified"] = False
                agent["lineage_error"] = "dsh_subagent_lineage_mismatch"
                agent.pop("lineage_parent_session_id", None)
                agent.pop("lineage_origin", None)
                agent.pop("lineage_verified_at_utc", None)
                errors.append(
                    {
                        "session_id": candidate,
                        "error": "dsh_subagent_lineage_mismatch",
                    }
                )
            changed = changed or agent != before
        if changed:
            team = self.store.update_team(
                task_id,
                agents=agents,
                delegations=delegations,
            )
        return dict(team), errors

    def _persist_pending_requested(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        pending: Sequence[Mapping[str, Any]],
    ) -> None:
        for item in pending:
            kind = str(item.get("kind") or "")
            rpc_id = str(item.get("rpc_id") or "")
            session_id = str(item.get("session_id") or "")
            if kind not in {"approval", "question"} or not rpc_id or not session_id:
                continue
            origin = self._pending_origin_identity(
                task_id=task_id,
                session_id=session_id,
                item=item,
            )
            fallback = self._pending_fallback_identity(team, session_id)
            agent_run_id = (
                origin.get("agent_run_id")
                or item.get("agent_run_id")
                or fallback.get("agent_run_id")
            )
            agent_turn_id = _agent_turn_id_for_run(team, agent_run_id) or (
                item.get("agent_turn_id") or fallback.get("agent_turn_id")
            )
            source_turn_id = origin.get("turn_id") or item.get("turn_id")
            call_id = origin.get("call_id") or item.get("call_id")
            agent_id, agent_label = self._agent_for_session(team, session_id)
            agent_id = str(origin.get("agent_id") or agent_id)
            agent_label = origin.get("agent_label") or agent_label
            payload: dict[str, Any] = {
                "phase": "requested",
                "rpc_id": rpc_id,
                "kind": kind,
                "session_id": session_id,
                "received_at": item.get("received_at"),
            }
            if origin.get("event_id"):
                payload["origin_event_id"] = origin.get("event_id")
            if call_id:
                payload["call_id"] = call_id
            if kind == "approval" and item.get("approval_id"):
                payload["approval_id"] = item.get("approval_id")
            base_source_key = (
                f"dsh-pending:{CONVERSATION_PROJECTOR_REVISION}:"
                f"{kind}:{rpc_id}:requested"
            )
            requested = next(
                (
                    event
                    for event in reversed(self.store.list_events(task_id))
                    if event.get("source") == "dsh_pending"
                    and event.get("event_type") == kind
                    and event.get("payload", {}).get("phase") == "requested"
                    and event.get("payload", {}).get("rpc_id") == rpc_id
                ),
                None,
            )
            desired_identity = {
                "agent_run_id": agent_run_id,
                "agent_turn_id": agent_turn_id,
                "turn_id": source_turn_id,
                "call_id": call_id,
            }
            if requested is not None:
                improves_identity = any(
                    desired_identity[field]
                    and desired_identity[field] != requested.get(field)
                    for field in desired_identity
                )
                if not improves_identity:
                    continue
                payload["supersedes_event_id"] = requested.get("event_id")
                source_key = (
                    f"{base_source_key}:correlation:"
                    f"{_json_digest(desired_identity)[:16]}"
                )
            else:
                source_key = base_source_key
            self.store.append_event(
                task_id=task_id,
                event={
                    "source": "dsh_pending",
                    "projector_revision": CONVERSATION_PROJECTOR_REVISION,
                    "source_key": source_key,
                    "timestamp_utc": _utc_now(),
                    "agent_id": agent_id,
                    "agent_label": agent_label,
                    "agent_run_id": agent_run_id,
                    "agent_turn_id": agent_turn_id,
                    "session_id": session_id,
                    "dsh_session_id": session_id,
                    "turn_id": source_turn_id,
                    "call_id": call_id,
                    "category": kind,
                    "type": kind,
                    "status": "pending",
                    "payload": payload,
                },
            )

    def _pending_origin_identity(
        self,
        *,
        task_id: str,
        session_id: str,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind a live RPC checkpoint to the DSH turn that created it.

        The pending websocket channel owns the answerable ``rpc_id`` but, for
        questions, does not repeat the originating tool call id.  Session
        history does contain the canonical requested event and tool call, so
        bind by protocol identity/content inside the same session instead of
        guessing from wall-clock proximity.
        """

        events = [
            event
            for event in self.store.current_projection_events(task_id)
            if event.get("session_id") == session_id
        ]
        kind = str(item.get("kind") or "")
        direct_call_id = str(item.get("call_id") or "")
        approval_id = str(item.get("approval_id") or "")
        questions = item.get("questions")

        for event in reversed(events):
            if event.get("event_type") != kind or event.get("status") != "pending":
                continue
            payload = event.get("payload")
            payload = payload if isinstance(payload, Mapping) else {}
            event_call_id = str(
                event.get("call_id")
                or payload.get("callId")
                or payload.get("call_id")
                or ""
            )
            if direct_call_id and event_call_id and event_call_id != direct_call_id:
                continue
            if approval_id and str(payload.get("approvalId") or "") != approval_id:
                continue
            if kind == "question" and isinstance(questions, list):
                if payload.get("questions") != questions:
                    continue
            if not event_call_id and kind == "question":
                for candidate in reversed(events):
                    candidate_payload = candidate.get("payload")
                    candidate_payload = (
                        candidate_payload
                        if isinstance(candidate_payload, Mapping)
                        else {}
                    )
                    if (
                        candidate.get("event_type") == "tool_call"
                        and candidate.get("turn_id") == event.get("turn_id")
                        and candidate_payload.get("tool_name")
                        == "ask_user_question"
                    ):
                        event_call_id = str(
                            candidate.get("call_id")
                            or candidate_payload.get("call_id")
                            or ""
                        )
                        break
            return {
                "event_id": event.get("event_id"),
                "turn_id": event.get("turn_id"),
                "call_id": event_call_id or direct_call_id or None,
                "agent_run_id": event.get("agent_run_id"),
                "agent_id": event.get("agent_id"),
                "agent_label": event.get("agent_label"),
            }

        expected_tool = (
            "ask_user_question" if kind == "question" else str(item.get("tool_name") or "")
        )
        completed_calls = {
            str(event.get("call_id") or event.get("payload", {}).get("call_id") or "")
            for event in events
            if event.get("event_type") == "tool_result"
            and isinstance(event.get("payload"), Mapping)
        }
        for event in reversed(events):
            payload = event.get("payload")
            payload = payload if isinstance(payload, Mapping) else {}
            call_id = str(event.get("call_id") or payload.get("call_id") or "")
            if event.get("event_type") != "tool_call":
                continue
            if expected_tool and payload.get("tool_name") != expected_tool:
                continue
            if direct_call_id and call_id != direct_call_id:
                continue
            if call_id and call_id in completed_calls:
                continue
            return {
                "event_id": event.get("event_id"),
                "turn_id": event.get("turn_id"),
                "call_id": call_id or direct_call_id or None,
                "agent_run_id": event.get("agent_run_id"),
                "agent_id": event.get("agent_id"),
                "agent_label": event.get("agent_label"),
            }
        return {}

    def _persist_pending_resolved(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        session_id: str,
        item: Mapping[str, Any],
        outcome: str,
        answer_count: int | None = None,
        terminal_event: Mapping[str, Any] | None = None,
    ) -> None:
        kind = str(item.get("kind"))
        rpc_id = str(item.get("rpc_id"))
        requested = next(
            (
                event
                for event in reversed(self.store.list_events(task_id))
                if event.get("source") == "dsh_pending"
                and event.get("event_type") == kind
                and event.get("payload", {}).get("phase") == "requested"
                and event.get("payload", {}).get("rpc_id") == rpc_id
            ),
            None,
        )
        observed_origin = self._pending_origin_identity(
            task_id=task_id,
            session_id=session_id,
            item=item,
        )
        fallback = self._pending_fallback_identity(team, session_id)
        agent_run_id = (
            observed_origin.get("agent_run_id")
            or item.get("agent_run_id")
            or (requested or {}).get("agent_run_id")
            or fallback.get("agent_run_id")
        )
        agent_turn_id = _agent_turn_id_for_run(team, agent_run_id) or (
            item.get("agent_turn_id")
            or (requested or {}).get("agent_turn_id")
            or fallback.get("agent_turn_id")
        )
        source_turn_id = (
            observed_origin.get("turn_id")
            or item.get("turn_id")
            or (requested or {}).get("turn_id")
        )
        call_id = (
            observed_origin.get("call_id")
            or item.get("call_id")
            or (requested or {}).get("call_id")
        )
        agent_id, agent_label = self._agent_for_session(team, session_id)
        agent_id = str(observed_origin.get("agent_id") or agent_id)
        agent_label = observed_origin.get("agent_label") or agent_label
        safe_outcome = (
            outcome
            if outcome
            in {
                "allowed-once",
                "allowed-always",
                "denied",
                "rejected",
                "cancelled",
                "answered",
                "invalidated_by_turn_terminal",
            }
            else "submitted"
        )
        payload: dict[str, Any] = {
            "phase": "resolved",
            "rpc_id": rpc_id,
            "kind": kind,
            "session_id": session_id,
            "outcome": safe_outcome,
        }
        if answer_count is not None:
            payload["answer_count"] = answer_count
        requested_payload = (
            requested.get("payload")
            if isinstance(requested, Mapping)
            and isinstance(requested.get("payload"), Mapping)
            else {}
        )
        origin_event_id = (
            observed_origin.get("event_id")
            or requested_payload.get("origin_event_id")
        )
        if origin_event_id:
            payload["origin_event_id"] = origin_event_id
        if requested is not None:
            payload["requested_event_id"] = requested.get("event_id")
        if call_id:
            payload["call_id"] = call_id
        if terminal_event is not None:
            payload["terminal_event_id"] = terminal_event.get("event_id")
            terminal_payload = terminal_event.get("payload")
            if isinstance(terminal_payload, Mapping):
                payload["terminal_reason"] = terminal_payload.get("reason")
                error = terminal_payload.get("error")
                if isinstance(error, Mapping) and error.get("code"):
                    payload["terminal_error_code"] = error.get("code")
        self.store.append_event(
            task_id=task_id,
            event={
                "source": "dsh_pending",
                "projector_revision": CONVERSATION_PROJECTOR_REVISION,
                "source_key": (
                    f"dsh-pending:{CONVERSATION_PROJECTOR_REVISION}:"
                    f"{kind}:{rpc_id}:resolved"
                ),
                "timestamp_utc": _utc_now(),
                "agent_id": agent_id,
                "agent_label": agent_label,
                "agent_run_id": agent_run_id,
                "agent_turn_id": agent_turn_id,
                "session_id": session_id,
                "dsh_session_id": session_id,
                "turn_id": source_turn_id,
                "call_id": call_id,
                "category": kind,
                "type": kind,
                "status": "completed",
                "payload": payload,
            },
        )

    @staticmethod
    def _agent_for_session(
        team: Mapping[str, Any],
        session_id: str,
    ) -> tuple[str, str | None]:
        for delegation in team.get("delegations", {}).values():
            if (
                isinstance(delegation, Mapping)
                and delegation.get("dsh_session_id") == session_id
                and delegation.get("lineage_verified") is True
                and delegation.get("lineage_origin") == "subagent"
            ):
                return str(delegation.get("target_agent_id") or "specialist"), (
                    str(delegation["target_agent_label"])
                    if delegation.get("target_agent_label")
                    else None
                )
        for agent in team.get("agents", {}).values():
            if isinstance(agent, dict) and agent.get("dsh_session_id") == session_id:
                return str(agent.get("agent_id")), (
                    str(agent["agent_label"]) if agent.get("agent_label") else None
                )
        return ROOT_PROFILE.agent_id, ROOT_PROFILE.agent_label

    @staticmethod
    def _run_boundaries(team: Mapping[str, Any]) -> tuple[RunBoundary, ...]:
        boundaries: list[RunBoundary] = []
        for run in team.get("runs", []):
            if not isinstance(run, Mapping) or not isinstance(run.get("run_id"), str):
                continue
            raw_floors = run.get("source_seq_floor_by_session", {})
            floors = (
                tuple(
                    sorted(
                        (str(session_id), int(source_seq))
                        for session_id, source_seq in raw_floors.items()
                        if isinstance(session_id, str)
                        and session_id
                        and isinstance(source_seq, int)
                        and not isinstance(source_seq, bool)
                    )
                )
                if isinstance(raw_floors, Mapping)
                else ()
            )
            boundaries.append(
                RunBoundary(
                    run_id=str(run["run_id"]),
                    queued_at_utc=str(run.get("queued_at_utc") or ""),
                    queue_event_seq=int(run.get("conversation_event_seq_at_queue", 0)),
                    source_seq_floor_by_session=floors,
                    boundary_complete=run.get("source_boundary_complete") is True,
                )
            )
        return tuple(boundaries)

    @staticmethod
    def _verified_child_bindings(
        team: Mapping[str, Any],
        boundaries: Sequence[RunBoundary],
    ) -> tuple[VerifiedChildBinding, ...]:
        boundary_by_run = {boundary.run_id: boundary for boundary in boundaries}
        bindings: list[VerifiedChildBinding] = []
        for delegation in team.get("delegations", {}).values():
            if not isinstance(delegation, Mapping):
                continue
            run_id = delegation.get("agent_run_id")
            call_id = delegation.get("delegation_id")
            child_session_id = delegation.get("dsh_session_id")
            if (
                not isinstance(run_id, str)
                or run_id not in boundary_by_run
                or not isinstance(call_id, str)
                or not call_id
                or not isinstance(child_session_id, str)
                or not child_session_id
            ):
                continue
            floor_sessions = dict(
                boundary_by_run[run_id].source_seq_floor_by_session
            )
            bindings.append(
                VerifiedChildBinding(
                    run_id=run_id,
                    delegation_call_id=call_id,
                    parent_turn_id=str(delegation.get("parent_turn_id") or ""),
                    parent_session_id=str(team.get("root_session_id") or ""),
                    child_session_id=child_session_id,
                    created_in_run=child_session_id not in floor_sessions,
                    lineage_verified=(
                        delegation.get("lineage_verified") is True
                        and delegation.get("lineage_origin") == "subagent"
                    ),
                )
            )
        return tuple(bindings)

    @staticmethod
    def _effective_projection_events(
        events: Sequence[Mapping[str, Any]],
        verdict_index: SynthesisVerdictIndex,
        *,
        allow_final: bool,
        suppression_reason: str | None = None,
    ) -> list[dict[str, Any]]:
        effective: list[dict[str, Any]] = []
        for event in events:
            selected = deepcopy(dict(event))
            if event.get("category") not in {"synthesis_candidate", "final"}:
                effective.append(selected)
                continue
            event_id = event.get("event_id")
            verdict = (
                verdict_index.event(event_id)
                if isinstance(event_id, str)
                else None
            )
            accepted = bool(verdict and verdict.accepted and allow_final)
            selected["category"] = "final" if accepted else "narration"
            selected["type"] = "final_synthesis" if accepted else "coordinator_note"
            selected["event_type"] = selected["type"]
            selected["status"] = "completed" if accepted else "observed"
            selected["truth_type"] = (
                "evidence_backed_final" if accepted else "unverified_narration"
            )
            payload = selected.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            reason_codes = list(verdict.reason_codes) if verdict else [
                "missing_synthesis_verdict"
            ]
            if verdict and verdict.accepted and not allow_final:
                reason_codes.append(suppression_reason or "run_not_terminal")
            payload["synthesis_verdict"] = {
                "version": verdict_index.version,
                "accepted": accepted,
                "reason_codes": sorted(set(reason_codes)),
                "supporting_event_ids": (
                    list(verdict.evidence_event_ids) if verdict else []
                ),
                "evidence_digest": verdict.evidence_digest if verdict else None,
            }
            payload["object_refs"] = (
                [ref.as_dict() for ref in verdict.evidence_object_refs]
                if verdict and accepted
                else []
            )
            selected["payload"] = payload
            effective.append(selected)
        return effective

    def _reconcile_team(
        self,
        *,
        task_id: str,
        running: bool,
        waiting_for_human: bool = False,
        verdict_index: SynthesisVerdictIndex | None = None,
        observation_degraded: bool = False,
        session_terminal_observed: bool = False,
    ) -> dict[str, Any]:
        team = self._require_team(task_id)
        # team.json rows are canonical and are preserved. Only the current
        # projector revision may add observations or drive run lifecycle.
        events = self.store.current_projection_events(task_id)
        agents = deepcopy(team.get("agents", {}))
        delegations = {
            key: value
            for key, value in deepcopy(team.get("delegations", {})).items()
            if isinstance(value, dict) and value.get("target_agent_id")
        }
        for event in events:
            agent_id = event.get("agent_id")
            if isinstance(agent_id, str) and agent_id and agent_id not in agents:
                profile = PROFILE_BY_ID.get(agent_id)
                agents[agent_id] = {
                    "agent_id": agent_id,
                    "agent_label": event.get("agent_label")
                    or (profile.agent_label if profile else None),
                    "role_id": profile.agent_id if profile else None,
                    "candidate_dsh_session_id": self._find_session_id(
                        event.get("payload")
                    ),
                    "parent_agent_id": ROOT_PROFILE.agent_id,
                    "status": event.get("status") or "observed",
                    "observed_from_dsh": event.get("source") == "dsh",
                    "projector_revision": CONVERSATION_PROJECTOR_REVISION,
                    "lineage_verified": False,
                }
            if event.get("category") == "agent_status" and agent_id in agents:
                agents[agent_id]["status"] = event.get("status") or "observed"
            if event.get("category") == "delegation":
                payload = event.get("payload", {})
                if not isinstance(payload, dict) or not payload.get(
                    "target_agent_id"
                ):
                    # DSH control tools such as list_agents are observable
                    # coordinator activity, not user-facing work delegation.
                    continue
                observed_assignment = self._structured_delegation_assignment(
                    payload
                )
                call_id = payload.get("call_id") if isinstance(payload, dict) else None
                delegation_id = str(call_id or event["source_key"])
                current = delegations.get(
                    delegation_id,
                    {
                        "delegation_id": delegation_id,
                        "parent_delegation_id": event.get(
                            "parent_delegation_id"
                        ),
                        "agent_run_id": event.get("agent_run_id"),
                        "source_agent_id": event.get("agent_id"),
                        "source_session_id": event.get("session_id"),
                        "target_agent_id": payload.get("target_agent_id")
                        if isinstance(payload, dict)
                        else None,
                        "target_agent_label": payload.get("target_agent_label")
                        if isinstance(payload, dict)
                        else None,
                        "tool_name": payload.get("tool_name")
                        if isinstance(payload, dict)
                        else None,
                        "parent_turn_id": event.get("turn_id"),
                        "dsh_session_id": self._find_session_id(payload),
                        "started_at_utc": event.get("timestamp_utc"),
                        **(
                            {"assignment": observed_assignment}
                            if observed_assignment is not None
                            else {}
                        ),
                    },
                )
                if observed_assignment is not None:
                    current["assignment"] = observed_assignment
                if event.get("agent_run_id"):
                    current["agent_run_id"] = event.get("agent_run_id")
                if event.get("parent_delegation_id"):
                    current["parent_delegation_id"] = event.get(
                        "parent_delegation_id"
                    )
                if event.get("session_id"):
                    current["source_session_id"] = event.get("session_id")
                if event.get("turn_id"):
                    current["parent_turn_id"] = event.get("turn_id")
                observed_delegation_session = self._find_session_id(payload)
                if observed_delegation_session:
                    current["dsh_session_id"] = observed_delegation_session
                current["status"] = event.get("status")
                current["updated_at_utc"] = event.get("timestamp_utc")
                delegations[delegation_id] = current
                target_agent_id = current.get("target_agent_id")
                if (
                    isinstance(target_agent_id, str)
                    and target_agent_id
                    and target_agent_id not in agents
                ):
                    profile = PROFILE_BY_ID.get(target_agent_id)
                    agents[target_agent_id] = {
                        "agent_id": target_agent_id,
                        "agent_label": current.get("target_agent_label")
                        or (profile.agent_label if profile else None),
                        "role_id": profile.agent_id if profile else None,
                        "candidate_dsh_session_id": self._find_session_id(payload),
                        "parent_agent_id": current.get("source_agent_id"),
                        "status": event.get("status") or "observed",
                        "observed_from_dsh": event.get("source") == "dsh",
                        "projector_revision": CONVERSATION_PROJECTOR_REVISION,
                        "lineage_verified": False,
                    }
                elif isinstance(target_agent_id, str) and target_agent_id in agents:
                    observed_session_id = self._find_session_id(payload)
                    if observed_session_id:
                        if agents[target_agent_id].get("dsh_session_id") != observed_session_id:
                            agents[target_agent_id][
                                "candidate_dsh_session_id"
                            ] = observed_session_id
                            agents[target_agent_id]["lineage_verified"] = False
                        elif current.get("lineage_verified") is True:
                            # Replaying older delegation events may temporarily
                            # set a candidate for the same role. The newest
                            # verified delegation restores the role aggregate;
                            # per-delegation lineage remains canonical.
                            agents[target_agent_id].pop(
                                "candidate_dsh_session_id", None
                            )
                            agents[target_agent_id]["lineage_verified"] = True
                            agents[target_agent_id]["lineage_origin"] = (
                                current.get("lineage_origin") or "subagent"
                            )
                            agents[target_agent_id][
                                "lineage_parent_session_id"
                            ] = current.get("lineage_parent_session_id")
                            agents[target_agent_id][
                                "lineage_verified_at_utc"
                            ] = current.get("lineage_verified_at_utc") or _utc_now()
                            agents[target_agent_id].pop("lineage_error", None)
                    agents[target_agent_id]["status"] = event.get("status") or "observed"
        for delegation in delegations.values():
            target_agent_id = delegation.get("target_agent_id")
            target = agents.get(target_agent_id) if isinstance(target_agent_id, str) else None
            if isinstance(target, dict) and target.get("status") in {
                "completed",
                "failed",
                "cancelled",
            }:
                delegation["status"] = target["status"]
        run_updates: list[dict[str, Any]] = []
        if team.get("runs"):
            run_updates.extend(
                self._converge_cancel_requested_runs(
                    task_id=task_id,
                    team=team,
                    events=events,
                    session_terminal_observed=(
                        session_terminal_observed and not observation_degraded
                    ),
                )
            )
            if run_updates:
                team = self._require_team(task_id)
            latest = team["runs"][-1]
            if latest.get("status") == "cancel_requested":
                pass
            elif waiting_for_human and latest.get("status") in {
                "queued",
                "running",
                "waiting_for_human",
            }:
                run_updates.append(
                    self.store.update_run(
                        task_id=task_id,
                        run_id=latest["run_id"],
                        status="waiting_for_human",
                    )
                )
            elif running and latest.get("status") in {
                "queued",
                "waiting_for_human",
            }:
                run_updates.append(
                    self.store.update_run(
                        task_id=task_id,
                        run_id=latest["run_id"],
                        status="running",
                    )
                )
            elif (
                not running
                and verdict_index is not None
                and latest.get("status") not in {
                    "cancelled",
                    "interrupted",
                }
            ):
                run_id = str(latest["run_id"])
                verdict = verdict_index.run(run_id)
                accepted = bool(
                    verdict and verdict.accepted_candidate_event_id
                )
                turn_error = self._latest_run_turn_error(
                    events=events,
                    team=team,
                    run=latest,
                )
                reason_codes = list(verdict.reason_codes) if verdict else [
                    "missing_run_verdict"
                ]
                if observation_degraded:
                    reason_codes.append("observation_degraded")
                if turn_error is not None:
                    error_payload = turn_error.get("payload", {})
                    typed_error = (
                        error_payload.get("error")
                        if isinstance(error_payload, Mapping)
                        and isinstance(error_payload.get("error"), Mapping)
                        else {}
                    )
                    reason_codes.append("dsh_turn_error")
                else:
                    typed_error = {}
                terminal_status = (
                    "failed"
                    if turn_error is not None
                    else "observation_degraded"
                    if observation_degraded
                    else "completed"
                    if accepted
                    else "idle_without_final"
                )
                terminal_error = (
                    str(typed_error.get("message") or "DSH 智能体本轮执行失败。")
                    if terminal_status == "failed"
                    else None
                )
                evidence = {
                    "synthesis_verdict_version": verdict_index.version,
                    "synthesis_candidate_event_id": (
                        verdict.accepted_candidate_event_id if verdict else None
                    ),
                    "synthesis_evidence_event_ids": (
                        list(verdict.evidence_event_ids) if verdict else []
                    ),
                    "synthesis_evidence_digest": (
                        verdict.evidence_digest if verdict else None
                    ),
                    "synthesis_reason_codes": sorted(set(reason_codes)),
                    "terminal_error_event_id": (
                        turn_error.get("event_id") if turn_error is not None else None
                    ),
                    "terminal_error_code": (
                        typed_error.get("code") if terminal_status == "failed" else None
                    ),
                }
                if latest.get("status") == "observation_degraded" and (
                    terminal_status != "observation_degraded"
                ):
                    self.store.append_event(
                        task_id=task_id,
                        event={
                            "source": "runtime",
                            "source_key": (
                                f"runtime:observation-recovered:{run_id}:"
                                f"{verdict_index.version}"
                            ),
                            "timestamp_utc": _utc_now(),
                            "agent_id": ROOT_PROFILE.agent_id,
                            "agent_label": ROOT_PROFILE.agent_label,
                            "agent_run_id": run_id,
                            "category": "agent_status",
                            "type": "observation.recovered",
                            "status": "observed",
                            "payload": {"run_id": run_id},
                        },
                    )
                if observation_degraded:
                    self.store.append_event(
                        task_id=task_id,
                        event={
                            "source": "runtime",
                            "source_key": (
                                f"runtime:observation-degraded:{run_id}:"
                                f"{verdict_index.version}"
                            ),
                            "timestamp_utc": _utc_now(),
                            "agent_id": ROOT_PROFILE.agent_id,
                            "agent_label": ROOT_PROFILE.agent_label,
                            "agent_run_id": run_id,
                            "category": "agent_status",
                            "type": "observation.degraded",
                            "status": "observation_degraded",
                            "payload": {"run_id": run_id},
                        },
                    )
                if (
                    latest.get("status") != terminal_status
                    or latest.get("error") != terminal_error
                    or any(
                        latest.get(key) != value for key, value in evidence.items()
                    )
                ):
                    run_updates.append(
                        self.store.update_run(
                            task_id=task_id,
                            run_id=run_id,
                            status=terminal_status,
                            error=terminal_error,
                            evidence=evidence,
                        )
                    )
            if verdict_index is not None:
                for historical in team["runs"][:-1]:
                    if historical.get("status") != "completed":
                        continue
                    historical_run_id = str(historical.get("run_id") or "")
                    if not historical_run_id:
                        continue
                    historical_verdict = verdict_index.run(historical_run_id)
                    historical_accepted = bool(
                        historical_verdict
                        and historical_verdict.accepted_candidate_event_id
                    )
                    historical_status = (
                        "completed"
                        if historical_accepted
                        else "idle_without_final"
                    )
                    historical_evidence = {
                        "synthesis_verdict_version": verdict_index.version,
                        "synthesis_candidate_event_id": (
                            historical_verdict.accepted_candidate_event_id
                            if historical_verdict
                            else None
                        ),
                        "synthesis_evidence_event_ids": (
                            list(historical_verdict.evidence_event_ids)
                            if historical_verdict
                            else []
                        ),
                        "synthesis_evidence_digest": (
                            historical_verdict.evidence_digest
                            if historical_verdict
                            else None
                        ),
                        "synthesis_reason_codes": (
                            list(historical_verdict.reason_codes)
                            if historical_verdict
                            else ["missing_run_verdict"]
                        ),
                    }
                    if historical.get("status") != historical_status or any(
                        historical.get(key) != value
                        for key, value in historical_evidence.items()
                    ):
                        run_updates.append(
                            self.store.update_run(
                                task_id=task_id,
                                run_id=historical_run_id,
                                status=historical_status,
                                evidence=historical_evidence,
                            )
                        )
        _ = run_updates
        current_team = self._require_team(task_id)
        latest_run = (
            current_team.get("runs", [])[-1]
            if current_team.get("runs")
            else {}
        )
        return self.store.update_team(
            task_id,
            agents=agents,
            delegations=delegations,
            status=(
                "waiting_for_human"
                if waiting_for_human
                else "running"
                if running
                else "observation_degraded"
                if observation_degraded
                else "failed"
                if latest_run.get("status") == "failed"
                else "idle"
            ),
        )

    @staticmethod
    def _structured_delegation_assignment(
        payload: Mapping[str, Any],
    ) -> dict[str, str] | None:
        """Read the short assignment label only from structured tool args."""

        arguments = payload.get("arguments")
        if not isinstance(arguments, Mapping):
            return None
        for field in ("description", "summary"):
            value = arguments.get(field)
            if isinstance(value, str) and value.strip():
                return {
                    "summary": value.strip(),
                    "source_field": field,
                }
        return None

    @staticmethod
    def _latest_run_turn_error(
        *,
        events: Sequence[Mapping[str, Any]],
        team: Mapping[str, Any],
        run: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """Select an observed current-revision turn error owned by the Agent run."""

        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return None
        root_session_id = team.get("root_session_id")
        raw_floors = run.get("source_seq_floor_by_session", {})
        floors = raw_floors if isinstance(raw_floors, Mapping) else {}
        root_floor = (
            floors.get(root_session_id)
            if isinstance(root_session_id, str)
            else None
        )
        matches: list[Mapping[str, Any]] = []
        for event in events:
            if (
                event.get("event_type") != "turn_error"
                or event.get("status") != "failed"
            ):
                continue
            if event.get("agent_run_id") == run_id:
                matches.append(event)
                continue
            source_seq = event.get("source_seq")
            if (
                run.get("source_boundary_complete") is True
                and event.get("session_id") == root_session_id
                and isinstance(root_floor, int)
                and not isinstance(root_floor, bool)
                and isinstance(source_seq, int)
                and not isinstance(source_seq, bool)
                and source_seq > root_floor
            ):
                matches.append(event)
        return matches[-1] if matches else None

    def _converge_cancel_requested_runs(
        self,
        *,
        task_id: str,
        team: Mapping[str, Any],
        events: Sequence[Mapping[str, Any]],
        session_terminal_observed: bool,
    ) -> list[dict[str, Any]]:
        """Settle every AgentRun owned by one observed cancel cascade.

        A root-session cancellation terminates the queued/current turns in the
        same durable cancellation scope.  One terminal observation therefore
        settles the whole group, not only ``runs[-1]``.
        """

        groups: dict[str, list[Mapping[str, Any]]] = {}
        for run in team.get("runs", []):
            if not isinstance(run, Mapping) or run.get("status") != "cancel_requested":
                continue
            request = run.get("cancel_request")
            if not isinstance(request, Mapping):
                continue
            cancellation_id = request.get("cancellation_id")
            group_id = (
                str(cancellation_id)
                if isinstance(cancellation_id, str) and cancellation_id
                else f"legacy:{_json_digest(request)}"
            )
            groups.setdefault(group_id, []).append(run)

        updates: list[dict[str, Any]] = []
        for group_id, runs in groups.items():
            observed_cancel = next(
                (
                    event
                    for run in runs
                    for event in [
                        self._latest_run_turn_cancelled(
                            events=events,
                            team=team,
                            run=run,
                        )
                    ]
                    if event is not None
                ),
                None,
            )
            if observed_cancel is None and not session_terminal_observed:
                continue
            convergence_source = (
                "observed_turn_cancelled"
                if observed_cancel is not None
                else "observed_session_terminal_after_cancel"
            )
            for run in runs:
                updates.append(
                    self.store.update_run(
                        task_id=task_id,
                        run_id=str(run["run_id"]),
                        status="cancelled",
                        evidence={
                            "terminal_cancel_event_id": (
                                observed_cancel.get("event_id")
                                if observed_cancel is not None
                                else None
                            ),
                            "cancellation_convergence": convergence_source,
                            "cancellation_group_id": group_id,
                        },
                    )
                )
        return updates

    @staticmethod
    def _latest_run_turn_cancelled(
        *,
        events: Sequence[Mapping[str, Any]],
        team: Mapping[str, Any],
        run: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """Select an observed cancellation owned by the requested AgentRun."""

        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return None
        root_session_id = team.get("root_session_id")
        raw_floors = run.get("source_seq_floor_by_session", {})
        floors = raw_floors if isinstance(raw_floors, Mapping) else {}
        root_floor = (
            floors.get(root_session_id)
            if isinstance(root_session_id, str)
            else None
        )
        matches: list[Mapping[str, Any]] = []
        for event in events:
            if (
                event.get("event_type") != "turn_cancelled"
                or event.get("status") != "cancelled"
            ):
                continue
            if event.get("agent_run_id") == run_id:
                matches.append(event)
                continue
            source_seq = event.get("source_seq")
            if (
                run.get("source_boundary_complete") is True
                and event.get("session_id") == root_session_id
                and isinstance(root_floor, int)
                and not isinstance(root_floor, bool)
                and isinstance(source_seq, int)
                and not isinstance(source_seq, bool)
                and source_seq > root_floor
            ):
                matches.append(event)
        return matches[-1] if matches else None

    @staticmethod
    def _find_session_id(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("sessionId", "session_id", "subagentSessionId", "subagentId"):
                selected = value.get(key)
                if isinstance(selected, str) and selected:
                    return selected
            for child in value.values():
                found = DshMultiAgentRuntime._find_session_id(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = DshMultiAgentRuntime._find_session_id(child)
                if found:
                    return found
        elif isinstance(value, str):
            match = re.search(
                r"\b(?:started\s+)?subagent\s+([0-9a-f]{8}-[0-9a-f-]{27,})\b",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _root_instruction(
        *,
        task_id: str,
        agent_run_id: str,
        current_spec_revision: Any,
        record_type: str,
        user_message: str,
    ) -> str:
        profiles = "\n".join(
            f"- {profile.agent_id}: {profile.agent_label}; owns={','.join(profile.owns)}; "
            f"cannot={','.join(profile.cannot_do)}"
            for profile in AGENT_PROFILES
            if not profile.root
        )
        selected_record_type = str(record_type or "training_task").strip()
        if selected_record_type == "conversation_draft":
            return (
                "你是 Specialist Model Studio 面向用户的模型训练伙伴。"
                "当前是尚未绑定 TrainingTask 的普通对话，不是训练执行阶段。"
                "先理解用户这句话属于问候、产品/能力咨询、模糊训练意图，还是已经包含明确输入与输出的训练目标。\n"
                "若是问候，请像人一样简短回应并邀请用户说出想解决的问题；若是产品或能力咨询，"
                "直接回答，不要借机创建任务。若训练意图仍模糊，先复述已理解的部分，再用普通对话只问一个"
                "真正影响方案的问题。以上三种情况都禁止调用 model_harness_*、ask_user_question 或委派专家，"
                "也不得声称任务、训练或分析已经开始。intake 中 model_harness_* 的唯一例外是"
                " model_harness_promote_conversation，且只适用于下述明确目标。\n"
                "只有当用户已经给出足够具体的业务结果，至少能辨认主要输入和期望输出时，"
                "才调用一次 model_harness_promote_conversation。conversation_id 必须逐字复制下面的规范值；"
                "name 要简短，business_goal 必须忠实使用用户的说法，不得补造数据、设备或验收标准。"
                "提升成功后，才可调用 model_harness_get_task 并进入任务编排。不得调用 model_harness_create_task。\n"
                "用户只需要看到一个连贯的 AI 对话。不要在正文里宣布当前由哪个内部 Agent 处理；"
                "只有真实子 Agent 执行了动作时，才允许在对应动作记录中标明角色。"
                "不得输出私有思维链、隐藏推理或伪造的思考过程；只呈现简洁意图、真实动作、观察结果与结论。\n"
                "不要因为标题、历史任务或一句问候推断业务目标，也不要把自然澄清渲染成表单。\n"
                f"CONVERSATION_MODE: INTAKE\n"
                f"EXACT_CONVERSATION_ID_JSON: {json.dumps(task_id, ensure_ascii=False)}\n"
                f"CONVERSATION_ID: {task_id}\n"
                f"AGENT_RUN_ID: {agent_run_id}\n\n"
                f"USER_MESSAGE:\n{user_message}"
            )
        return (
            "你是 Specialist Model Studio 面向用户的模型训练伙伴，并在内部承担 Training Orchestrator。"
            "当前对话已绑定 TrainingTask；TrainingTask 是唯一任务事实源。"
            "先判断用户当前这句话是否真的在推进、查询或修改这个任务。纯问候请自然简短回应；"
            "与当前任务事实无关的一般产品能力、方法或流程问题请直接回答。以上情况不得调用"
            " model_harness_get_task、ask_user_question 或任何专家，也不得改变任务或暗示开始了新工作。\n"
            "只有当用户要继续当前任务、查询其状态，或请求一个会读取/改变领域事实的动作时，"
            "才先用下面给出的精确 task_id 调用 model_harness_get_task。禁止先调用 model_harness_list_tasks，"
            "不得创建第二个任务，也不得从聊天记忆推断任务状态。"
            "每次调用 model_harness_* 时，task_id 参数必须逐字复制完整 canonical 值，不得截断、改写，"
            "也不得根据任务标题自行构造。不得再次调用 model_harness_promote_conversation。\n"
            "需要专业工作时，使用 DeepSeek Harness 已提供的原生、可继续的 subagent "
            "delegate/spawn/fork 能力。专家必须使用下面固定的 agent_id 与职责；"
            "专家结果回到根会话，用户只看到一个 Orchestrator 对话和真实过程事件，"
            "不要生成虚构的多角色群聊。所有领域事实和副作用只能来自 model_harness_* 工具。\n"
            "只有本轮成功领域工具返回的、与当前 task_id 一致的 canonical ObjectRef "
            "才能支撑完成结论；get_task、list 类和 Agent 散文都不是完成证据。"
            "如果证据不足，请如实说明仍在等待什么，不要声称训练、评测或交付已经完成。\n"
            "任务已绑定后，缺少数据文件、目标列或其他用户输入时，必须使用 ask_user_question 创建一次只问一个字段的"
            "结构化 question checkpoint，并使用稳定 question id（例如 data_upload 或 target_column）；"
            "禁止只用自然语言提出请求后结束回合。用户上传或回答后应解析同一个 rpc_id 并续接根会话。\n"
            "启动真实训练前，根会话必须调用 model_harness_authorize_task_run_start，让用户只批准一次当前"
            "合同、数据指纹和任务版本；再把返回的 run_authorization_id 交给 build_training 专家。"
            "该专家委派必须保持 continuable（省略 run_in_background 或设为 true，绝不能设为 false），"
            "并仅能用该授权调用一次 model_harness_start_task_run；不得用普通问答替代启动审批或二次索要审批。\n"
            "对用户保持一个连贯的 AI 身份，不要在正文顶部或每轮开头宣布由哪个内部 Agent 处理。"
            "只有真实子 Agent 执行了动作时，才在对应动作记录中标注其角色。不得输出私有思维链、"
            "隐藏推理或伪造的思考过程；只呈现简洁意图、真实动作、观察结果与结论。\n"
            f"CONVERSATION_MODE: TASK_BOUND\n"
            f"EXACT_TASK_ID_JSON: {json.dumps(task_id, ensure_ascii=False)}\n"
            f"TrainingTask: {task_id}; observed_spec_revision={current_spec_revision}\n"
            f"AGENT_RUN_ID: {agent_run_id}\n"
            f"SPECIALIST_PROFILES:\n{profiles}\n\n"
            f"USER_MESSAGE:\n{user_message}"
        )


def build_dsh_multi_agent_runtime(
    *,
    workspace_root: str | Path,
    dsh_base_url: str,
    cwd: str | Path,
    background_actions_provider: (
        Callable[[str], Sequence[Mapping[str, Any]]] | None
    ) = None,
    background_actions_canceller: (
        Callable[[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None
    ) = None,
) -> DshMultiAgentRuntime:
    """Build the production path; no scripted or Anthropic fallback is added."""

    # DSH web currently closes some unary HTTP responses even when the socket
    # advertises keep-alive. A fresh connection per RPC avoids ambiguous
    # post-send disconnects without replaying mutating Agent requests.
    client = DshRpcClient(dsh_base_url, reuse_unary_connection=False)
    events = DshEventHub(client)
    return DshMultiAgentRuntime(
        workspace_root=workspace_root,
        client=client,
        events=events,
        cwd=cwd,
        background_actions_provider=background_actions_provider,
        background_actions_canceller=background_actions_canceller,
    )
