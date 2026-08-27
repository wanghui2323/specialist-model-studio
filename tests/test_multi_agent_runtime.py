from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from model_harness.agent_bridge import AgentRuntimeError
from model_harness.io_utils import read_json, write_json
from model_harness.multi_agent import (
    AGENT_PROFILES,
    CONVERSATION_EVENT_SCHEMA_VERSION,
    ComposerModeUnsupportedError,
    ComposerRequestConflictError,
    ComposerRequestTerminalError,
    ComposerSubmissionError,
    DshConversationV2Projector,
    DshMultiAgentRuntime,
    HumanCheckpointAnswerError,
    HumanCheckpointConflictError,
    MultiAgentRuntimeError,
)


class FakeDshClient:
    def __init__(
        self,
        *,
        available: bool = True,
        fail_methods: set[str] | None = None,
        provider_active: bool = True,
        credential_configured: bool = True,
        credential_source: str | None = "env",
    ) -> None:
        self.is_available = available
        self.fail_methods = set(fail_methods or ())
        self.provider_active = provider_active
        self.credential_configured = credential_configured
        self.credential_source = credential_source
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.closed = False

    def available(self) -> bool:
        return self.is_available

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        self.calls.append((method, deepcopy(payload)))
        if not self.is_available:
            raise AssertionError("unavailable client must not receive RPC calls")
        if method in self.fail_methods:
            raise AgentRuntimeError(f"offline during {method}")
        if method == "llm.providers":
            return {
                "providers": [
                    {
                        "provider": "deepseek-official",
                        "displayName": "DeepSeek",
                        "active": self.provider_active,
                    }
                ]
            }
        if method == "credentials.describe":
            credential = {
                "configured": self.credential_configured,
                "writable": True,
            }
            if self.credential_source is not None:
                credential["source"] = self.credential_source
            return {"credentials": {"DEEPSEEK_API_KEY": credential}}
        if method == "session.create":
            session_id = f"dsh-{len(self.sessions) + 1}"
            self.sessions[session_id] = {
                "running": False,
                "events": [],
                "title": None,
            }
            return {"sessionId": session_id}
        if method == "session.rename":
            self.sessions[payload["sessionId"]]["title"] = payload["title"]
            return {}
        if method == "session.prompt":
            self.sessions[payload["sessionId"]]["running"] = True
            return {}
        if method == "session.history":
            return {"events": deepcopy(self.sessions[payload["sessionId"]]["events"])}
        if method == "session.list":
            return {
                "items": [
                    {
                        "sessionId": session_id,
                        "running": value["running"],
                        **(
                            {"parentSessionId": value["parentSessionId"]}
                            if value.get("parentSessionId")
                            else {}
                        ),
                        **({"origin": value["origin"]} if value.get("origin") else {}),
                    }
                    for session_id, value in self.sessions.items()
                ]
            }
        if method == "session.cancel":
            self.sessions[payload["sessionId"]]["running"] = False
            return {}
        raise AssertionError(f"unexpected method: {method}")

    def respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        self.responses.append((rpc_id, deepcopy(value)))

    def close(self) -> None:
        self.closed = True


class FakeEventHub:
    def __init__(self) -> None:
        self.bound_root: Path | None = None
        self.started = False
        self.stopped = False
        self.pending: dict[str, list[dict[str, Any]]] = {}
        self.resolved: list[tuple[str, str]] = []
        self.health: dict[str, Any] = {
            "connected_at": "2026-08-24T00:00:00+00:00",
            "last_event_at": "2026-08-24T00:00:00+00:00",
            "last_error_at": None,
            "consecutive_failures": 0,
            "recovered_at": None,
            "status": "healthy",
        }

    def bind_workspace(self, root: Path) -> None:
        self.bound_root = root

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def pending_for(self, session_id: str) -> list[dict[str, Any]]:
        return deepcopy(self.pending.get(session_id, []))

    def stream_health(self) -> dict[str, Any]:
        return deepcopy(self.health)

    def resolve_local(self, session_id: str, rpc_id: str) -> None:
        self.resolved.append((session_id, rpc_id))
        self.pending[session_id] = [
            item
            for item in self.pending.get(session_id, [])
            if item.get("rpc_id") != rpc_id
        ]


def dsh_event(
    sequence: int,
    event_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": {
            "seq": sequence,
            "time": f"2026-08-24T00:00:{sequence:02d}+00:00",
            "type": event_type,
            "data": data,
        }
    }


class DshMultiAgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.task_id = "模型-普通话录音转文字-23c3ac51"
        self.task_dir = self.root / "tasks" / self.task_id
        self.task = {
            "schema_version": "0.9",
            "task_id": self.task_id,
            "name": "普通话录音转文字",
            "status": "needs_recipe",
            "current_spec_revision": 1,
        }
        write_json(self.task_dir / "task.json", self.task)
        self.client = FakeDshClient()
        self.events = FakeEventHub()
        self.runtime = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=self.client,  # type: ignore[arg-type]
            events=self.events,  # type: ignore[arg-type]
            cwd=self.root,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _latest_agent_run_id(self) -> str:
        team = read_json(self.task_dir / "agent_team" / "team.json")
        return str(team["runs"][-1]["run_id"])

    def _root_history_with_candidate(
        self,
        *,
        run_id: str,
        tool_name: str,
        result: Any,
        candidate_text: str,
        call_task_id: str | None = None,
        is_error: bool = False,
    ) -> list[dict[str, Any]]:
        call_id = "evidence-call"
        return [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                f"USER_MESSAGE:\n{candidate_text}"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": call_id,
                    "name": tool_name,
                    "agentId": "training_orchestrator",
                    "input": {
                        "task_id": call_task_id or self.task_id,
                        "base_spec_revision": 1,
                    },
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "error": "tool failed" if is_error else None,
                    "message": {
                        "content": [
                            {
                                "toolCallId": call_id,
                                "isError": is_error,
                                "content": result,
                            }
                        ]
                    },
                },
            ),
            dsh_event(
                4,
                "assistant/message",
                {
                    "agentId": "training_orchestrator",
                    "message": {
                        "content": [{"type": "text", "text": candidate_text}]
                    },
                },
            ),
        ]

    def test_runtime_exposes_exact_adr_roles_and_no_fallback(self) -> None:
        status = self.runtime.runtime_status()

        self.assertTrue(status["available"])
        self.assertTrue(status["transport_ready"])
        self.assertTrue(status["ready"])
        self.assertTrue(status["real_agent"])
        self.assertEqual(
            status["provider"],
            {
                "ready": True,
                "provider": "deepseek-official",
                "active": True,
                "configured": True,
                "source": "env",
                "reason": None,
            },
        )
        self.assertEqual(status["implementation"], "dsh_native_subagents")
        self.assertIsNone(status["fallback_mode"])
        self.assertEqual(status["supported_modes"], ["queue_after_turn"])
        self.assertEqual(
            [status["root_agent"]["agent_label"]]
            + [item["agent_label"] for item in status["specialist_agents"]],
            [
                "Training Orchestrator",
                "Research & Source Agent",
                "Data & Experiment Agent",
                "Resource & Safety Agent",
                "Build & Training Agent",
                "Evaluation & Delivery Agent",
            ],
        )
        self.assertEqual(len(AGENT_PROFILES), 6)
        self.assertTrue(
            all(profile.permission_profile for profile in AGENT_PROFILES)
        )

    def test_unavailable_dsh_fails_closed_without_creating_a_fake_team(self) -> None:
        client = FakeDshClient(available=False)
        runtime = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=client,  # type: ignore[arg-type]
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )

        runtime_status = runtime.runtime_status()
        self.assertEqual(runtime_status["reason"], "dsh_runtime_unavailable")
        self.assertFalse(runtime_status["transport_ready"])
        self.assertFalse(runtime_status["provider"]["ready"])
        self.assertEqual(
            runtime_status["provider"]["reason"],
            "agent_transport_unavailable",
        )
        with self.assertRaisesRegex(MultiAgentRuntimeError, "运行时不可用"):
            runtime.prompt(self.task_id, "ASR", "帮我训练普通话 ASR")

        self.assertFalse((self.task_dir / "agent_team" / "team.json").exists())
        self.assertEqual(client.calls, [])

    def test_missing_model_credential_is_visible_without_exposing_a_secret(self) -> None:
        runtime = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=FakeDshClient(credential_configured=False),  # type: ignore[arg-type]
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )

        status = runtime.runtime_status()

        self.assertTrue(status["transport_ready"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["reason"], "llm_credential_missing")
        self.assertEqual(
            status["provider"],
            {
                "ready": False,
                "provider": "deepseek-official",
                "active": True,
                "configured": False,
                "source": None,
                "reason": "llm_credential_missing",
            },
        )
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(status))

    def test_provider_probe_failure_and_unknown_source_fail_safe(self) -> None:
        failing = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=FakeDshClient(  # type: ignore[arg-type]
                fail_methods={"llm.providers"},
            ),
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )
        self.assertEqual(
            failing.runtime_status()["provider"]["reason"],
            "llm_provider_probe_unavailable",
        )

        sanitized = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=FakeDshClient(  # type: ignore[arg-type]
                credential_source="/private/credentials.yaml",
            ),
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )
        self.assertEqual(sanitized.runtime_status()["provider"]["source"], "other")

    def test_empty_conversation_exposes_explicit_interaction_state(self) -> None:
        conversation = self.runtime.conversation(self.task_id)

        self.assertFalse(conversation["running"])
        self.assertFalse(conversation["execution_running"])
        self.assertEqual(conversation["interaction_state"], "idle")
        self.assertFalse(conversation["can_cancel_agent"])
        self.assertEqual(
            conversation["interaction_projection"]["phase"],
            "idle",
        )
        self.assertEqual(conversation["supported_modes"], ["queue_after_turn"])

    def test_prompt_creates_only_root_session_and_preserves_training_task(self) -> None:
        before = read_json(self.task_dir / "task.json")

        session_id = self.runtime.prompt(
            self.task_id,
            "普通话 ASR",
            "先研究适合本机的开源模型",
        )

        self.assertEqual(session_id, "dsh-1")
        self.assertEqual(len(self.client.sessions), 1)
        self.assertEqual(read_json(self.task_dir / "task.json"), before)
        prompt_call = next(
            payload
            for method, payload in self.client.calls
            if method == "session.prompt"
        )
        instruction = prompt_call["content"][0]["text"]
        self.assertIn("Training Orchestrator", instruction)
        self.assertIn("原生、可继续的 subagent", instruction)
        self.assertIn("research_source: Research & Source Agent", instruction)
        self.assertIn("不要生成虚构的多角色群聊", instruction)
        self.assertIn(self.task_id, instruction)
        self.assertIn(f'EXACT_TASK_ID_JSON: "{self.task_id}"', instruction)
        self.assertIn("严禁只传末尾 8 位短码", instruction)
        self.assertIn("结构化 question checkpoint", instruction)
        self.assertIn("稳定 question id", instruction)
        self.assertIn("model_harness_authorize_task_run_start", instruction)
        self.assertIn("run_authorization_id", instruction)
        self.assertIn("绝不能设为 false", instruction)
        team = read_json(self.task_dir / "agent_team" / "team.json")
        self.assertEqual(team["root_session_id"], "dsh-1")
        self.assertEqual(team["implementation"], "dsh_native_subagents")
        self.assertEqual(len(team["agents"]), 1)
        self.assertEqual(team["runs"][0]["task_spec_revision"], 1)

    def test_real_dsh_history_does_not_upgrade_unverified_root_text(self) -> None:
        session_id = self.runtime.prompt(
            self.task_id,
            "普通话 ASR",
            "研究并给出下一步",
        )
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": "runtime envelope\nUSER_MESSAGE:\n研究并给出下一步",
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-1",
                    "name": "spawn_agent",
                    "agentId": "training_orchestrator",
                    "input": {
                        "targetAgentId": "research_source",
                        "targetAgentLabel": "Research & Source Agent",
                    },
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "delegate-1",
                                "content": {
                                    "agentId": "research_source",
                                    "sessionId": "dsh-child-1",
                                },
                            }
                        ]
                    }
                },
            ),
            dsh_event(
                4,
                "subagent/status",
                {
                    "agentId": "research_source",
                    "agentLabel": "Research & Source Agent",
                    "sessionId": "dsh-child-1",
                    "status": "completed",
                },
            ),
            dsh_event(
                5,
                "tool/call",
                {
                    "callId": "tool-1",
                    "name": "model_harness_get_task",
                    "agentId": "training_orchestrator",
                    "input": {"task_id": self.task_id},
                },
            ),
            dsh_event(
                6,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "tool-1",
                                "content": {"status": "needs_recipe"},
                            }
                        ]
                    }
                },
            ),
            dsh_event(
                7,
                "tool/call",
                {
                    "callId": "control-1",
                    "name": "list_agents",
                    "agentId": "training_orchestrator",
                    "input": {},
                },
            ),
            dsh_event(
                8,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "control-1",
                                "content": {"agents": []},
                            }
                        ]
                    }
                },
            ),
            dsh_event(
                9,
                "assistant/message",
                {
                    "agentId": "training_orchestrator",
                    "message": {
                        "content": [
                            {"type": "text", "text": "已完成真实研究，当前需要 Recipe。"}
                        ]
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions["dsh-child-1"] = {
            "running": False,
            "events": [],
            "title": "research",
            "parentSessionId": session_id,
            "origin": "subagent",
        }

        first = self.runtime.conversation(self.task_id)
        second = self.runtime.conversation(self.task_id)

        self.assertEqual(first["schema_version"], CONVERSATION_EVENT_SCHEMA_VERSION)
        self.assertEqual(len(first["events"]), len(second["events"]))
        self.assertIn(
            "research_source",
            {item["agent_id"] for item in first["agents"]},
        )
        child = next(
            item for item in first["agents"] if item["agent_id"] == "research_source"
        )
        second_child = next(
            item for item in second["agents"] if item["agent_id"] == "research_source"
        )
        self.assertEqual(child["dsh_session_id"], "dsh-child-1")
        self.assertEqual(
            child["lineage_verified_at_utc"],
            second_child["lineage_verified_at_utc"],
        )
        self.assertEqual(len(first["delegations"]), 1)
        self.assertEqual(first["delegations"][0]["status"], "completed")
        self.assertTrue(
            any(
                item["event_type"] == "tool_call"
                and item["payload"].get("tool_name") == "list_agents"
                for item in first["items"]
            )
        )
        categories = {item["category"] for item in first["events"]}
        self.assertTrue(
            {"delegation", "agent_status", "tool", "narration"} <= categories
        )
        self.assertTrue(
            all("agent_id" in item and "agent_label" in item for item in first["events"])
        )
        narration = next(
            item for item in first["events"] if item["category"] == "narration"
        )
        self.assertEqual(
            narration["payload"]["text"],
            "已完成真实研究，当前需要 Recipe。",
        )
        self.assertFalse(narration["payload"]["synthesis_verdict"]["accepted"])
        self.assertIn(
            "observation_only_tool",
            narration["payload"]["synthesis_verdict"]["reason_codes"],
        )
        self.assertEqual(first["runs"][-1]["status"], "idle_without_final")

    def test_verified_child_tool_pair_projects_as_completed_action(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "委派专家读取任务")
        run_id = self._latest_agent_run_id()
        child_session_id = "dsh-child-action"
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n委派专家读取任务"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-action",
                    "name": "spawn_agent",
                    "agentId": "training_orchestrator",
                    "input": {"targetAgentId": "research_source"},
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "callId": "delegate-action",
                    "result": {
                        "agentId": "research_source",
                        "sessionId": child_session_id,
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_session_id] = {
            "running": False,
            "title": "research",
            "parentSessionId": session_id,
            "origin": "subagent",
            "events": [
                dsh_event(
                    1,
                    "tool/call",
                    {
                        "callId": "child-tool",
                        "name": "model_harness_get_task",
                        "input": {"task_id": self.task_id},
                    },
                ),
                dsh_event(
                    2,
                    "tool/result",
                    {"callId": "child-tool", "result": {"ok": True}},
                ),
            ],
        }

        conversation = self.runtime.conversation(self.task_id)

        child_action = next(
            action
            for action in conversation["actions"]
            if action["call_id"] == "child-tool"
        )
        self.assertEqual(child_action["status"], "completed")
        self.assertEqual(child_action["tool_class"], "domain")
        self.assertEqual(child_action["agent_run_id"], run_id)
        self.assertEqual(child_action["delegation_id"], "delegate-action")
        self.assertIsNone(child_action["parent_delegation_id"])
        self.assertIsNone(child_action["error"])

    def test_verified_native_delegation_projects_real_agent_work_item(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "委派专家查找模型")
        run_id = self._latest_agent_run_id()
        child_session_id = "dsh-child-work-item"
        object_ref = {
            "type": "model_source_search",
            "id": "search-from-child",
            "task_id": self.task_id,
            "base_spec_revision": 1,
        }
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n委派专家查找模型"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-work-item",
                    "name": "spawn_agent",
                    "agentId": "training_orchestrator",
                    "input": {
                        "targetAgentId": "research_source",
                        "description": "查找本地 ASR 候选",
                        "prompt": "这段长提示不能成为用户可见的任务摘要",
                    },
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "callId": "delegate-work-item",
                    "result": {
                        "agentId": "research_source",
                        "sessionId": child_session_id,
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_session_id] = {
            "running": False,
            "title": "research",
            "parentSessionId": session_id,
            "origin": "subagent",
            "events": [
                dsh_event(
                    1,
                    "tool/call",
                    {
                        "callId": "child-search",
                        "name": "model_harness_search_model_sources",
                        "input": {"task_id": self.task_id},
                    },
                ),
                dsh_event(
                    2,
                    "tool/result",
                    {
                        "callId": "child-search",
                        "result": {"object_refs": [object_ref]},
                    },
                ),
                dsh_event(3, "turn/end", {"reason": {"kind": "completed"}}),
            ],
        }

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(conversation["work_item_schema_version"], "1.0")
        self.assertEqual(len(conversation["work_items"]), 1)
        work_item = conversation["work_items"][0]
        self.assertEqual(work_item["task_id"], self.task_id)
        self.assertEqual(work_item["agent_run_id"], run_id)
        self.assertEqual(work_item["delegation_id"], "delegate-work-item")
        self.assertEqual(work_item["child_session_id"], child_session_id)
        self.assertTrue(work_item["lineage_verified"])
        self.assertEqual(work_item["role"]["agent_id"], "research_source")
        self.assertEqual(
            work_item["assignment"],
            {
                "summary": "查找本地 ASR 候选",
                "source_field": "description",
            },
        )
        self.assertNotIn(
            "这段长提示",
            json.dumps(work_item["assignment"], ensure_ascii=False),
        )
        self.assertEqual(work_item["status"], "completed")
        self.assertEqual(
            {action["call_id"] for action in work_item["actions"]},
            {"delegate-work-item", "child-search"},
        )
        self.assertEqual(work_item["object_refs"], [object_ref])
        self.assertIsNone(work_item["failure"])
        self.assertIsNotNone(work_item["ended_at_utc"])

    def test_repeated_delegation_of_same_role_keeps_each_verified_work_item(self) -> None:
        session_id = self.runtime.prompt(
            self.task_id,
            "ASR",
            "两次委派评测与交付专家",
        )
        run_id = self._latest_agent_run_id()
        child_ids = ["dsh-evaluation-first", "dsh-evaluation-second"]
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n两次委派评测与交付专家"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-evaluation-first",
                    "name": "spawn_agent",
                    "agentId": "training_orchestrator",
                    "input": {
                        "targetAgentId": "evaluation_delivery",
                        "description": "读取评测报告",
                    },
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "callId": "delegate-evaluation-first",
                    "result": {
                        "agentId": "evaluation_delivery",
                        "sessionId": child_ids[0],
                    },
                },
            ),
            dsh_event(
                4,
                "tool/call",
                {
                    "callId": "delegate-evaluation-second",
                    "name": "spawn_agent",
                    "agentId": "training_orchestrator",
                    "input": {
                        "targetAgentId": "evaluation_delivery",
                        "description": "构建交付包",
                    },
                },
            ),
            dsh_event(
                5,
                "tool/result",
                {
                    "callId": "delegate-evaluation-second",
                    "result": {
                        "agentId": "evaluation_delivery",
                        "sessionId": child_ids[1],
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        for index, child_id in enumerate(child_ids, start=1):
            self.client.sessions[child_id] = {
                "running": False,
                "title": f"evaluation-{index}",
                "parentSessionId": session_id,
                "origin": "subagent",
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {
                            "callId": f"evaluation-action-{index}",
                            "name": "model_harness_get_evaluation_report",
                            "input": {"task_id": self.task_id},
                        },
                    ),
                    dsh_event(
                        2,
                        "tool/result",
                        {
                            "callId": f"evaluation-action-{index}",
                            "result": {"ok": True},
                        },
                    ),
                    dsh_event(3, "turn/end", {"reason": {"kind": "completed"}}),
                ],
            }

        conversation = self.runtime.conversation(self.task_id)

        evaluation_items = [
            item
            for item in conversation["work_items"]
            if item["role"]["agent_id"] == "evaluation_delivery"
        ]
        self.assertEqual(len(evaluation_items), 2)
        self.assertEqual(
            {item["child_session_id"] for item in evaluation_items},
            set(child_ids),
        )
        self.assertTrue(all(item["lineage_verified"] for item in evaluation_items))
        self.assertEqual(
            {item["delegation_id"] for item in evaluation_items},
            {"delegate-evaluation-first", "delegate-evaluation-second"},
        )
        self.assertEqual(
            [item["child_session_id"] for item in evaluation_items],
            child_ids,
        )
        self.assertTrue(
            all(
                isinstance(item["observed_updated_sequence"], int)
                for item in evaluation_items
            )
        )
        self.assertLess(
            evaluation_items[0]["observed_updated_sequence"],
            evaluation_items[1]["observed_updated_sequence"],
        )
        role_summary = next(
            item
            for item in conversation["agents"]
            if item["agent_id"] == "evaluation_delivery"
        )
        self.assertTrue(role_summary["lineage_verified"])
        self.assertEqual(role_summary["dsh_session_id"], child_ids[1])

    def test_agent_work_item_preserves_verified_child_turn_error(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "委派专家验证资源")
        run_id = self._latest_agent_run_id()
        child_session_id = "dsh-child-failed-work-item"
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n委派专家验证资源"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-failure",
                    "name": "spawn_agent",
                    "input": {
                        "targetAgentId": "resource_safety",
                        "summary": "验证本机资源",
                    },
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "callId": "delegate-failure",
                    "result": {
                        "agentId": "resource_safety",
                        "sessionId": child_session_id,
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_session_id] = {
            "running": False,
            "title": "safety",
            "parentSessionId": session_id,
            "origin": "subagent",
            "events": [
                dsh_event(
                    1,
                    "turn/end",
                    {
                        "reason": {
                            "kind": "error",
                            "error": {
                                "code": "RESOURCE_PROBE_FAILED",
                                "message": "GPU probe did not return",
                                "requestId": "probe-request-1",
                            },
                        }
                    },
                )
            ],
        }

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(len(conversation["work_items"]), 1)
        work_item = conversation["work_items"][0]
        self.assertEqual(work_item["status"], "failed")
        self.assertEqual(work_item["assignment"]["summary"], "验证本机资源")
        self.assertEqual(work_item["assignment"]["source_field"], "summary")
        self.assertEqual(work_item["failure"]["code"], "RESOURCE_PROBE_FAILED")
        self.assertEqual(
            work_item["failure"]["message"],
            "GPU probe did not return",
        )
        self.assertEqual(
            work_item["failure"]["request_id"],
            "probe-request-1",
        )
        self.assertIsNotNone(work_item["failure"]["event_id"])

    def test_delegation_assignment_does_not_infer_from_prompt_text(self) -> None:
        self.assertIsNone(
            self.runtime._structured_delegation_assignment(
                {
                    "arguments": {
                        "prompt": "请研究模型并给出结论",
                    }
                }
            )
        )

    def test_conversation_preserves_object_refs_from_real_dsh_tool_result(self) -> None:
        session_id = self.runtime.prompt(
            self.task_id,
            "普通话 ASR",
            "查找模型候选",
        )
        object_ref = {
            "type": "model_source_search",
            "id": "search-0a1b2c",
            "task_id": self.task_id,
            "label": "模型候选 · search-0a1b2c",
            "base_spec_revision": 1,
        }
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "tool/call",
                {
                    "callId": "search-call",
                    "name": "model_harness_search_model_sources",
                },
            ),
            dsh_event(
                2,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "search-call",
                                "content": json.dumps(
                                    {"object_refs": [object_ref]},
                                    ensure_ascii=False,
                                ),
                            }
                        ]
                    }
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        result_event = next(
            item
            for item in conversation["items"]
            if item["event_type"] == "tool_result"
        )
        self.assertEqual(result_event["payload"]["object_refs"], [object_ref])
        persisted = self.runtime.store.list_events(self.task_id)
        persisted_result = next(
            item for item in persisted if item["event_type"] == "tool_result"
        )
        self.assertEqual(persisted_result["payload"]["object_refs"], [object_ref])

    def test_search_evidence_upgrades_candidate_and_shares_verdict_digest(self) -> None:
        session_id = self.runtime.prompt(
            self.task_id,
            "普通话 ASR",
            "查找并总结模型候选",
        )
        run_id = self._latest_agent_run_id()
        object_ref = {
            "type": "model_source_search",
            "id": "search-evidence-1",
            "task_id": self.task_id,
            "base_spec_revision": 1,
        }
        self.client.sessions[session_id]["events"] = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_search_model_sources",
            result=json.dumps({"object_refs": [object_ref]}, ensure_ascii=False),
            candidate_text="已找到可审查的模型候选。",
        )
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        final_event = next(
            item for item in conversation["events"] if item["category"] == "final"
        )
        final_item = next(
            item for item in conversation["items"] if item["category"] == "final"
        )
        run = conversation["runs"][-1]
        event_verdict = final_event["payload"]["synthesis_verdict"]
        item_verdict = final_item["payload"]["synthesis_verdict"]
        self.assertEqual(run["run_id"], run_id)
        self.assertEqual(run["status"], "completed")
        self.assertTrue(event_verdict["accepted"])
        self.assertEqual(final_event["event_id"], final_item["event_id"])
        self.assertEqual(
            run["synthesis_candidate_event_id"],
            final_event["event_id"],
        )
        self.assertEqual(
            run["synthesis_evidence_event_ids"],
            event_verdict["supporting_event_ids"],
        )
        self.assertEqual(
            run["synthesis_evidence_digest"],
            event_verdict["evidence_digest"],
        )
        self.assertEqual(event_verdict, item_verdict)
        self.assertEqual(final_event["payload"]["object_refs"], [object_ref])
        action = next(
            item
            for item in conversation["actions"]
            if item["tool_name"] == "model_harness_search_model_sources"
        )
        self.assertEqual(conversation["action_schema_version"], "1.0")
        self.assertEqual(action["status"], "completed")
        self.assertEqual(action["tool_class"], "domain")
        self.assertEqual(action["agent_run_id"], run_id)
        self.assertEqual(action["object_refs"], [object_ref])

    def test_get_task_and_candidate_text_do_not_complete_run(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "读取任务后总结")
        run_id = self._latest_agent_run_id()
        self.client.sessions[session_id]["events"] = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_get_task",
            result={"task": {"task_id": self.task_id, "status": "needs_recipe"}},
            candidate_text="任务已经完成分析。",
        )
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(conversation["runs"][-1]["status"], "idle_without_final")
        self.assertFalse(
            any(item["category"] == "final" for item in conversation["events"])
        )
        narration = next(
            item for item in conversation["events"] if item["category"] == "narration"
        )
        self.assertIn(
            "observation_only_tool",
            narration["payload"]["synthesis_verdict"]["reason_codes"],
        )
        action = next(
            item
            for item in conversation["actions"]
            if item["tool_name"] == "model_harness_get_task"
        )
        event_ref = action["event_result_ref"]
        self.assertEqual(event_ref["task_id"], self.task_id)
        self.assertEqual(event_ref["projector_revision"], "3.2")
        viewed = self.runtime.conversation_event_result(
            self.task_id,
            event_ref["id"],
            projector_revision=event_ref["projector_revision"],
        )
        self.assertFalse(viewed["completion_evidence"])
        self.assertEqual(viewed["event"]["event_id"], event_ref["id"])
        with self.assertRaises(FileNotFoundError):
            self.runtime.conversation_event_result(
                self.task_id,
                event_ref["id"],
                projector_revision="2.2",
            )

    def test_large_tool_result_is_compact_only_in_conversation_response(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "读取完整任务诊断")
        run_id = self._latest_agent_run_id()
        tail = "EXACT-EVENT-RESULT-TAIL"
        full_result = f"{'diagnostic-row;' * 500}{tail}"
        self.client.sessions[session_id]["events"] = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_get_task",
            result=full_result,
            candidate_text="任务诊断完成，等待下一步。",
        )
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(conversation["event_payload_mode"], "compact-v1")
        action = next(
            item
            for item in conversation["actions"]
            if item["tool_name"] == "model_harness_get_task"
        )
        self.assertEqual(action["status"], "completed")
        event_ref = action["event_result_ref"]
        self.assertIsNotNone(event_ref)
        assert event_ref is not None
        returned_event = next(
            item
            for item in conversation["events"]
            if item["event_id"] == event_ref["id"]
        )
        returned_item = next(
            item
            for item in conversation["items"]
            if item["event_id"] == event_ref["id"]
        )
        for selected in (returned_event, returned_item):
            payload = selected["payload"]
            self.assertNotIn("result", payload)
            self.assertTrue(payload["result_truncated"])
            self.assertNotIn(tail, payload["result_preview"])
            self.assertEqual(payload["event_result_ref"], event_ref)

        serialized_conversation = json.dumps(conversation, ensure_ascii=False)
        self.assertNotIn(tail, serialized_conversation)
        persisted_text = (
            self.task_dir / "agent_team" / "events.ndjson"
        ).read_text(encoding="utf-8")
        self.assertIn(tail, persisted_text)
        viewed = self.runtime.conversation_event_result(
            self.task_id,
            event_ref["id"],
            projector_revision=event_ref["projector_revision"],
        )
        self.assertEqual(viewed["event"]["payload"]["result"], full_result)
        self.assertFalse(viewed["completion_evidence"])

    def test_dsh_provider_turn_error_fails_agent_run_without_mutating_task(self) -> None:
        task_before = read_json(self.task_dir / "task.json")
        session_id = self.runtime.prompt(
            self.task_id,
            "ASR",
            "继续研究可用模型",
        )
        run_id = self._latest_agent_run_id()
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n继续研究可用模型"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "turn/end",
                {
                    "turn": 1,
                    "reason": {
                        "kind": "error",
                        "error": {
                            "message": "DeepSeek API credential is missing",
                            "code": "MISSING_CREDENTIAL",
                            "status": 401,
                            "providerRetryAfterMs": 2500,
                            "requestId": "provider-request-1",
                        },
                    },
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        turn_error = next(
            item
            for item in conversation["items"]
            if item["event_type"] == "turn_error"
        )
        self.assertEqual(turn_error["projector_revision"], "3.2")
        self.assertEqual(turn_error["status"], "failed")
        self.assertEqual(
            turn_error["payload"]["error"],
            {
                "code": "MISSING_CREDENTIAL",
                "message": "DeepSeek API credential is missing",
                "source": "dsh_turn_end",
                "status": 401,
                "provider_retry_after_ms": 2500,
                "request_id": "provider-request-1",
            },
        )
        run = conversation["runs"][-1]
        self.assertEqual(run["run_id"], run_id)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "DeepSeek API credential is missing")
        self.assertEqual(run["terminal_error_code"], "MISSING_CREDENTIAL")
        self.assertEqual(run["terminal_error_event_id"], turn_error["event_id"])
        self.assertIn("dsh_turn_error", run["synthesis_reason_codes"])
        self.assertEqual(
            read_json(self.task_dir / "agent_team" / "team.json")["status"],
            "failed",
        )
        self.assertEqual(read_json(self.task_dir / "task.json"), task_before)

    def test_turn_error_overrides_an_earlier_synthesis_candidate_in_same_run(self) -> None:
        task_before = read_json(self.task_dir / "task.json")
        session_id = self.runtime.prompt(
            self.task_id,
            "ASR",
            "查找模型后继续执行",
        )
        run_id = self._latest_agent_run_id()
        object_ref = {
            "type": "model_source_search",
            "id": "search-before-provider-error",
            "task_id": self.task_id,
            "base_spec_revision": 1,
        }
        history = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_search_model_sources",
            result=json.dumps({"object_refs": [object_ref]}, ensure_ascii=False),
            candidate_text="已找到可审查的模型候选。",
        )
        history.append(
            dsh_event(
                5,
                "turn/end",
                {
                    "turn": 1,
                    "reason": {
                        "kind": "error",
                        "error": {
                            "message": "Provider request failed",
                            "code": "PROVIDER_ERROR",
                        },
                    },
                },
            )
        )
        self.client.sessions[session_id]["events"] = history
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        run = conversation["runs"][-1]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["terminal_error_code"], "PROVIDER_ERROR")
        self.assertIn("dsh_turn_error", run["synthesis_reason_codes"])
        self.assertEqual(read_json(self.task_dir / "task.json"), task_before)

    def test_cross_task_object_ref_does_not_complete_run(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "查找模型候选")
        run_id = self._latest_agent_run_id()
        foreign_ref = {
            "type": "model_source_search",
            "id": "foreign-search",
            "task_id": "another-training-task",
            "base_spec_revision": 1,
        }
        self.client.sessions[session_id]["events"] = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_search_model_sources",
            result=json.dumps({"object_refs": [foreign_ref]}, ensure_ascii=False),
            candidate_text="已找到模型候选。",
        )
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(conversation["runs"][-1]["status"], "idle_without_final")
        self.assertFalse(
            any(item["category"] == "final" for item in conversation["events"])
        )
        narration = next(
            item for item in conversation["events"] if item["category"] == "narration"
        )
        self.assertIn(
            "cross_task_object_ref",
            narration["payload"]["synthesis_verdict"]["reason_codes"],
        )
        self.assertEqual(narration["payload"]["object_refs"], [])

    def test_unhealthy_stream_states_block_final_and_healthy_recovers(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "查找模型候选")
        run_id = self._latest_agent_run_id()
        object_ref = {
            "type": "model_source_search",
            "id": "search-under-degraded-stream",
            "task_id": self.task_id,
            "base_spec_revision": 1,
        }
        self.client.sessions[session_id]["events"] = self._root_history_with_candidate(
            run_id=run_id,
            tool_name="model_harness_search_model_sources",
            result=json.dumps({"object_refs": [object_ref]}, ensure_ascii=False),
            candidate_text="已找到模型候选。",
        )
        self.client.sessions[session_id]["running"] = False
        cases = (
            ("degraded", 2),
            ("connecting", 2),
            ("connecting", 0),
            ("not_started", 1),
            ("not_started", 0),
            ("stopped", 0),
            ("healthy", 1),
            ("unknown_state", 0),
        )
        for status, failures in cases:
            with self.subTest(status=status, failures=failures):
                self.events.health.update(
                    {
                        "last_error_at": (
                            "2026-08-24T00:00:05+00:00"
                            if failures
                            else None
                        ),
                        "consecutive_failures": failures,
                        "status": status,
                    }
                )
                conversation = self.runtime.conversation(self.task_id)

                self.assertEqual(
                    conversation["projection_health"],
                    "observation_degraded",
                )
                self.assertEqual(
                    conversation["runs"][-1]["status"],
                    "observation_degraded",
                )
                self.assertFalse(
                    any(
                        item["category"] == "final"
                        for item in conversation["events"]
                    )
                )
                self.assertFalse(
                    any(
                        item["category"] == "final"
                        for item in conversation["items"]
                    )
                )
                narration = next(
                    item
                    for item in conversation["events"]
                    if item["category"] == "narration"
                )
                verdict = narration["payload"]["synthesis_verdict"]
                self.assertFalse(verdict["accepted"])
                self.assertIn("observation_degraded", verdict["reason_codes"])
                self.assertIsNotNone(verdict["evidence_digest"])
                self.assertEqual(narration["payload"]["object_refs"], [])

                self.events.health.update(
                    {
                        "consecutive_failures": 0,
                        "status": "healthy",
                    }
                )
                recovered = self.runtime.conversation(self.task_id)
                self.assertEqual(recovered["projection_health"], "healthy")
                self.assertEqual(recovered["runs"][-1]["status"], "completed")
                self.assertTrue(
                    any(item["category"] == "final" for item in recovered["events"])
                )

    def test_clean_initial_stream_states_do_not_degrade_empty_task(self) -> None:
        for status in ("not_started", "connecting", "not_observed"):
            with self.subTest(status=status):
                self.events.health.update(
                    {
                        "connected_at": None,
                        "last_error_at": None,
                        "consecutive_failures": 0,
                        "status": status,
                    }
                )
                conversation = self.runtime.conversation(self.task_id)
                self.assertIsNone(conversation["team_id"])
                self.assertEqual(conversation["projection_health"], "healthy")

        self.events.health.update(
            {
                "last_error_at": None,
                "consecutive_failures": 0,
                "status": "stopped",
            }
        )
        stopped = self.runtime.conversation(self.task_id)
        self.assertEqual(stopped["projection_health"], "observation_degraded")
        self.assertEqual(
            stopped["interaction_projection"]["phase"],
            "observation_degraded",
        )

    def test_empty_history_never_synthesizes_agent_reply(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "请分析")
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        self.assertFalse(
            any(event["category"] == "final" for event in conversation["events"])
        )
        self.assertEqual(conversation["runs"][-1]["status"], "idle_without_final")
        self.assertEqual(conversation["work_items"], [])

    def test_conversation_reads_verified_child_history_and_tracks_aggregate_running(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "并行研究")
        run_id = self._latest_agent_run_id()
        child_id = "12f532d0-613c-4a0e-9183-8c69dbcee133"
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n并行研究"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "delegate-1",
                    "name": "research_source",
                    "input": {"description": "查找模型候选"},
                },
            ),
            dsh_event(
                3,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "delegate-1",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"started subagent {child_id}",
                                    }
                                ],
                            }
                        ]
                    }
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_id] = {
            "running": True,
            "events": [
                dsh_event(
                    1,
                    "tool/call",
                    {"callId": "hf-1", "name": "model_harness_hf_search"},
                )
            ],
            "title": "research",
            "parentSessionId": session_id,
            "origin": "subagent",
        }

        active = self.runtime.conversation(self.task_id)
        self.assertTrue(active["running"])
        self.assertTrue(active["execution_running"])
        self.assertEqual(active["interaction_state"], "working")
        self.assertTrue(active["can_cancel_agent"])
        self.assertEqual(
            active["interaction_projection"]["phase"],
            "agent_working",
        )
        child_tool = next(
            item
            for item in active["items"]
            if item["payload"].get("tool_name") == "model_harness_hf_search"
        )
        self.assertEqual(child_tool["agent_id"], "research_source")
        self.assertEqual(active["delegations"][0]["status"], "running")
        self.assertEqual(len(active["work_items"]), 1)
        self.assertEqual(active["work_items"][0]["status"], "active")
        self.assertEqual(
            active["work_items"][0]["assignment"]["summary"],
            "查找模型候选",
        )

        self.client.sessions[child_id]["running"] = False
        self.client.sessions[child_id]["events"].extend(
            [
                dsh_event(
                    2,
                    "assistant/message",
                    {"message": {"content": [{"type": "text", "text": "研究完成"}]}},
                ),
                dsh_event(3, "turn/end", {"reason": {"kind": "completed"}}),
            ]
        )
        settled = self.runtime.conversation(self.task_id)

        self.assertFalse(settled["running"])
        child = next(
            item for item in settled["agents"] if item["agent_id"] == "research_source"
        )
        self.assertEqual(child["status"], "completed")
        self.assertEqual(settled["delegations"][0]["status"], "completed")
        self.assertEqual(settled["work_items"][0]["status"], "completed")
        self.assertTrue(
            any(item["event_type"] == "specialist_output" for item in settled["items"])
        )

    def test_approval_and_question_are_routed_to_observed_child_session(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "研究")
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "subagent/status",
                {
                    "agentId": "resource_safety",
                    "agentLabel": "Resource & Safety Agent",
                    "sessionId": "dsh-child-safety",
                    "status": "running",
                },
            )
        ]
        self.client.sessions[session_id]["running"] = True
        self.client.sessions["dsh-child-safety"] = {
            "running": True,
            "events": [],
            "title": "safety",
            "parentSessionId": session_id,
            "origin": "subagent",
        }
        self.runtime.conversation(self.task_id)
        self.events.pending["dsh-child-safety"] = [
            {
                "rpc_id": "approval-rpc",
                "kind": "approval",
                "approval_id": "approval-1",
                "received_at": 1,
            },
            {
                "rpc_id": "question-rpc",
                "kind": "question",
                "received_at": 2,
                "questions": [
                    {
                        "id": "q1",
                        "question": "使用哪种运行环境？",
                    }
                ],
            },
        ]

        self.runtime.answer_approval(self.task_id, "approval-rpc", "allowed-once")
        self.runtime.answer_question(
            self.task_id,
            "question-rpc",
            [{"questionId": "q1", "answer": "CPU only"}],
        )

        self.assertEqual(self.client.responses[0][0], "approval-rpc")
        self.assertEqual(
            self.client.responses[0][1]["sessionId"],
            "dsh-child-safety",
        )
        self.assertEqual(self.client.responses[1][0], "question-rpc")
        self.assertEqual(
            self.events.resolved,
            [
                ("dsh-child-safety", "approval-rpc"),
                ("dsh-child-safety", "question-rpc"),
            ],
        )
        pending_audit = [
            item
            for item in self.runtime.store.list_events(self.task_id)
            if item.get("source") == "dsh_pending"
        ]
        self.assertTrue(pending_audit)
        self.assertTrue(
            all(item["projector_revision"] == "3.2" for item in pending_audit)
        )
        self.assertTrue(
            all(item["source_key"].startswith("dsh-pending:3.2:") for item in pending_audit)
        )

    def test_pending_question_keeps_originating_agent_turn_and_tool_call(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "Regression", "预测房价")
        run_id = self._latest_agent_run_id()
        team = read_json(self.task_dir / "agent_team" / "team.json")
        agent_turn_id = str(team["runs"][-1]["agent_turn_id"])
        questions = [
            {
                "id": "target_kind",
                "question": "price 是连续数值还是类别？",
            }
        ]
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "user/message",
                {
                    "source": {"kind": "user"},
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"AGENT_RUN_ID: {run_id}\n"
                                "USER_MESSAGE:\n预测 price"
                            ),
                        }
                    ],
                },
            ),
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "question-call-1",
                    "name": "ask_user_question",
                    "input": {"questions": questions},
                },
            ),
            dsh_event(
                3,
                "question/requested",
                {"questions": questions},
            ),
        ]
        self.client.sessions[session_id]["running"] = True
        self.events.pending[session_id] = [
            {
                "rpc_id": "question-rpc-1",
                "kind": "question",
                "received_at": 1,
                "questions": questions,
            }
        ]

        conversation = self.runtime.conversation(self.task_id)
        checkpoint = next(
            item
            for item in conversation["items"]
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "requested"
        )

        self.assertEqual(checkpoint["turn_id"], f"{session_id}:turn:1")
        self.assertEqual(checkpoint["call_id"], "question-call-1")
        self.assertEqual(checkpoint["agent_run_id"], run_id)
        self.assertEqual(checkpoint["agent_turn_id"], agent_turn_id)
        self.assertEqual(checkpoint["payload"]["call_id"], "question-call-1")

    def test_pending_question_lag_keeps_agent_turn_and_appends_correlation(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "Regression", "预测 price")
        team = read_json(self.task_dir / "agent_team" / "team.json")
        run_id = str(team["runs"][-1]["run_id"])
        agent_turn_id = str(team["runs"][-1]["agent_turn_id"])
        questions = [
            {
                "id": "target_kind",
                "question": "price 是连续数值还是类别？",
            }
        ]
        user_event = dsh_event(
            1,
            "user/message",
            {
                "source": {"kind": "user"},
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"AGENT_RUN_ID: {run_id}\n"
                            "USER_MESSAGE:\n预测 price"
                        ),
                    }
                ],
            },
        )
        self.client.sessions[session_id]["events"] = [user_event]
        self.client.sessions[session_id]["running"] = True
        self.events.pending[session_id] = [
            {
                "rpc_id": "question-rpc-lag",
                "kind": "question",
                "received_at": 1,
                "questions": questions,
            }
        ]

        first = self.runtime.conversation(self.task_id)
        self.assertEqual(first["pending"][0]["agent_run_id"], run_id)
        self.assertEqual(first["pending"][0]["agent_turn_id"], agent_turn_id)
        first_requested = next(
            item
            for item in first["items"]
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "requested"
        )
        self.assertEqual(first_requested["agent_turn_id"], agent_turn_id)
        self.assertIsNone(first_requested["turn_id"])
        self.assertIsNone(first_requested["call_id"])

        self.client.sessions[session_id]["events"] = [
            user_event,
            dsh_event(
                2,
                "tool/call",
                {
                    "callId": "question-call-lag",
                    "name": "ask_user_question",
                    "input": {"questions": questions},
                },
            ),
            dsh_event(
                3,
                "question/requested",
                {"questions": questions},
            ),
        ]

        second = self.runtime.conversation(self.task_id)
        self.assertEqual(second["pending"][0]["agent_turn_id"], agent_turn_id)
        self.assertEqual(second["pending"][0]["turn_id"], f"{session_id}:turn:1")
        self.assertEqual(second["pending"][0]["call_id"], "question-call-lag")
        requested_audit = [
            item
            for item in self.runtime.store.list_events(self.task_id)
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "requested"
            and item.get("payload", {}).get("rpc_id") == "question-rpc-lag"
        ]
        self.assertEqual(len(requested_audit), 2)
        correlated = requested_audit[-1]
        self.assertEqual(correlated["agent_run_id"], run_id)
        self.assertEqual(correlated["agent_turn_id"], agent_turn_id)
        self.assertEqual(correlated["turn_id"], f"{session_id}:turn:1")
        self.assertEqual(correlated["call_id"], "question-call-lag")
        self.assertEqual(
            correlated["payload"]["supersedes_event_id"],
            requested_audit[0]["event_id"],
        )
        self.assertTrue(
            all(
                item["agent_turn_id"] == agent_turn_id
                for item in second["items"]
                if item.get("agent_run_id") == run_id
            )
        )
        self.assertTrue(
            all(
                action["agent_turn_id"] == agent_turn_id
                for action in second["actions"]
                if action.get("agent_run_id") == run_id
            )
        )

        self.runtime.answer_question(
            self.task_id,
            "question-rpc-lag",
            [
                {
                    "questionId": "target_kind",
                    "answer": "连续数值",
                }
            ],
        )
        resolved = next(
            item
            for item in reversed(self.runtime.store.list_events(self.task_id))
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "resolved"
            and item.get("payload", {}).get("rpc_id") == "question-rpc-lag"
        )
        self.assertEqual(resolved["agent_run_id"], run_id)
        self.assertEqual(resolved["agent_turn_id"], agent_turn_id)
        self.assertEqual(resolved["turn_id"], f"{session_id}:turn:1")
        self.assertEqual(resolved["call_id"], "question-call-lag")

    def test_only_current_projector_revision_drives_canonical_team_and_run(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "检查旧投影隔离")
        self.client.sessions[session_id]["running"] = False
        team_path = self.task_dir / "agent_team" / "team.json"
        team = read_json(team_path)
        team["agents"]["canonical-agent"] = {
            "agent_id": "canonical-agent",
            "agent_label": "Canonical Agent",
            "role_id": None,
            "status": "observed",
            "observed_from_dsh": True,
        }
        team["delegations"]["canonical-delegation"] = {
            "delegation_id": "canonical-delegation",
            "source_agent_id": "training_orchestrator",
            "target_agent_id": "canonical-agent",
            "target_agent_label": "Canonical Agent",
            "status": "completed",
        }
        write_json(team_path, team)
        for revision, suffix in ((None, "none"), ("1.9", "old")):
            self.runtime.store.append_event(
                task_id=self.task_id,
                event={
                    "source": "dsh",
                    "projector_revision": revision,
                    "source_key": f"legacy:{suffix}:ghost",
                    "timestamp_utc": "2026-08-24T00:01:00+00:00",
                    "agent_id": f"ghost-{suffix}",
                    "agent_label": "Ghost Agent",
                    "category": "delegation",
                    "type": "delegation",
                    "status": "completed",
                    "payload": {
                        "call_id": f"ghost-{suffix}",
                        "target_agent_id": f"ghost-{suffix}",
                    },
                },
            )
            self.runtime.store.append_event(
                task_id=self.task_id,
                event={
                    "source": "dsh",
                    "projector_revision": revision,
                    "source_key": f"legacy:{suffix}:final",
                    "timestamp_utc": "2026-08-24T00:01:01+00:00",
                    "agent_id": "training_orchestrator",
                    "agent_label": "Training Orchestrator",
                    "category": "final",
                    "type": "final_synthesis",
                    "status": "completed",
                    "payload": {"text": "legacy fake final"},
                },
            )

        conversation = self.runtime.conversation(self.task_id)

        agent_ids = {item["agent_id"] for item in conversation["agents"]}
        self.assertIn("canonical-agent", agent_ids)
        self.assertNotIn("ghost-none", agent_ids)
        self.assertNotIn("ghost-old", agent_ids)
        self.assertEqual(
            {item["delegation_id"] for item in conversation["delegations"]},
            {"canonical-delegation"},
        )
        self.assertEqual(conversation["runs"][-1]["status"], "idle_without_final")
        self.assertFalse(
            any(
                item["source_key"] == "legacy:none:final"
                for item in conversation["events"]
            )
        )
        self.assertTrue(
            any(
                item["source_key"] == "legacy:none:final"
                for item in self.runtime.store.list_events(self.task_id)
            )
        )
        self.assertFalse(
            any(item.get("payload", {}).get("text") == "legacy fake final" for item in conversation["items"])
        )

    def test_pending_audit_kind_matching_waiting_state_and_secret_redaction(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "需要人工决定")
        self.client.sessions[session_id]["running"] = False
        secret = "private-answer-never-persist"
        self.events.pending[session_id] = [
            {
                "rpc_id": "approval-rpc",
                "kind": "approval",
                "approval_id": "approval-1",
                "received_at": 1,
                "private_context": secret,
            },
            {
                "rpc_id": "question-rpc",
                "kind": "question",
                "received_at": 2,
                "question": secret,
                "questions": [
                    {
                        "id": "q1",
                        "question": "请补充运行约束",
                    }
                ],
            },
        ]

        first = self.runtime.conversation(self.task_id)
        second = self.runtime.conversation(self.task_id)

        self.assertTrue(first["running"])
        self.assertFalse(first["execution_running"])
        self.assertEqual(first["interaction_state"], "waiting_for_human")
        self.assertFalse(first["can_cancel_agent"])
        self.assertEqual(
            first["interaction_projection"]["phase"],
            "waiting_approval",
        )
        self.assertEqual(first["runs"][-1]["status"], "waiting_for_human")
        self.assertEqual(len(first["human_checkpoints"]), 2)
        self.assertEqual(
            first["primary_attention"]["object_type"],
            "HumanCheckpoint",
        )
        self.assertEqual(first["agent_turns"][-1]["object_type"], "AgentTurn")
        requested = [
            item
            for item in second["events"]
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "requested"
        ]
        self.assertEqual(len(requested), 2)
        self.assertNotIn(secret, json.dumps(requested, ensure_ascii=False))
        with self.assertRaisesRegex(MultiAgentRuntimeError, "类型不匹配"):
            self.runtime.answer_question(
                self.task_id,
                "approval-rpc",
                [{"questionId": "wrong", "answer": secret}],
            )
        self.assertEqual(self.client.responses, [])

        self.runtime.answer_approval(self.task_id, "approval-rpc", "allowed-once")
        self.runtime.answer_question(
            self.task_id,
            "question-rpc",
            [{"questionId": "q1", "answer": secret}],
        )

        persisted = self.runtime.store.list_events(self.task_id)
        resolved = [
            item
            for item in persisted
            if item.get("source") == "dsh_pending"
            and item.get("payload", {}).get("phase") == "resolved"
        ]
        self.assertEqual(len(resolved), 2)
        outcomes = {item["category"]: item["payload"]["outcome"] for item in resolved}
        self.assertEqual(outcomes, {"approval": "allowed-once", "question": "answered"})
        question = next(item for item in resolved if item["category"] == "question")
        self.assertEqual(question["payload"]["answer_count"], 1)
        self.assertNotIn(secret, json.dumps(persisted, ensure_ascii=False))

    def test_question_answers_are_validated_against_current_checkpoint(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "选择本地运行环境")
        self.client.sessions[session_id]["running"] = False
        self.events.pending[session_id] = [
            {
                "rpc_id": "question-rpc",
                "kind": "question",
                "received_at": 1,
                "questions": [
                    {
                        "id": "runtime",
                        "question": "模型要在哪种环境运行？",
                        "options": [
                            {"label": "CPU"},
                            {"label": "Metal"},
                        ],
                        "multiSelect": False,
                        "required": True,
                        "allow_custom": False,
                    }
                ],
            }
        ]

        with self.assertRaisesRegex(HumanCheckpointConflictError, "question id"):
            self.runtime.answer_question(
                self.task_id,
                "question-rpc",
                [{"id": "other", "selected": ["CPU"]}],
            )
        for invalid, message in (
            ({"id": "runtime", "selected": ["GPU"]}, "未提供的选项"),
            ({"id": "runtime", "selected": []}, "必答题"),
            (
                {"id": "runtime", "selected": [], "custom": "CUDA"},
                "不允许自定义回答",
            ),
            (
                {"id": "runtime", "selected": ["CPU", "Metal"]},
                "单选题",
            ),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(HumanCheckpointAnswerError, message):
                    self.runtime.answer_question(
                        self.task_id,
                        "question-rpc",
                        [invalid],
                    )
        self.assertEqual(self.client.responses, [])

        self.runtime.answer_question(
            self.task_id,
            "question-rpc",
            [{"id": "runtime", "selected": ["CPU"]}],
        )

        self.assertEqual(
            self.client.responses[-1],
            (
                "question-rpc",
                {
                    "sessionId": session_id,
                    "answer": {
                        "answers": [{"id": "runtime", "selected": ["CPU"]}]
                    },
                },
            ),
        )
        with self.assertRaisesRegex(HumanCheckpointConflictError, "已经失效"):
            self.runtime.answer_question(
                self.task_id,
                "question-rpc",
                [{"id": "runtime", "selected": ["CPU"]}],
            )

    def test_terminal_turn_invalidates_unanswerable_pending_question(self) -> None:
        task_before = read_json(self.task_dir / "task.json")
        session_id = self.runtime.prompt(self.task_id, "ASR", "等待人工决定")
        self.events.pending[session_id] = [
            {
                "rpc_id": "stale-question-rpc",
                "kind": "question",
                "received_at": 1,
                "questions": [
                    {
                        "id": "next_path",
                        "question": "继续静态分析吗？",
                        "options": [{"label": "继续", "description": "只做静态分析"}],
                    }
                ],
            }
        ]
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                3,
                "turn/end",
                {"turn": 1, "reason": {"kind": "interrupted"}},
            )
        ]
        self.client.sessions[session_id]["running"] = False

        conversation = self.runtime.conversation(self.task_id)

        self.assertEqual(conversation["pending"], [])
        self.assertFalse(conversation["running"])
        self.assertEqual(conversation["runs"][-1]["status"], "failed")
        self.assertEqual(conversation["runs"][-1]["terminal_error_code"], "TURN_INTERRUPTED")
        self.assertIn((session_id, "stale-question-rpc"), self.events.resolved)
        audit = [
            event
            for event in self.runtime.store.list_events(self.task_id)
            if event.get("source") == "dsh_pending"
            and event.get("payload", {}).get("rpc_id") == "stale-question-rpc"
        ]
        self.assertEqual(
            [event["payload"]["phase"] for event in audit],
            ["requested", "resolved"],
        )
        self.assertEqual(
            audit[-1]["payload"]["outcome"],
            "invalidated_by_turn_terminal",
        )
        self.assertEqual(
            audit[-1]["payload"]["terminal_error_code"],
            "TURN_INTERRUPTED",
        )
        with self.assertRaisesRegex(MultiAgentRuntimeError, "已经失效"):
            self.runtime.answer_question(
                self.task_id,
                "stale-question-rpc",
                [{"id": "next_path", "selected": ["继续"]}],
            )
        self.assertEqual(self.client.responses, [])
        self.assertEqual(read_json(self.task_dir / "task.json"), task_before)

    def test_child_session_requires_current_dsh_lineage_before_mapping_or_pending(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "验证子会话血缘")
        child_id = "12f532d0-613c-4a0e-9183-8c69dbcee999"
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                1,
                "tool/call",
                {"callId": "delegate-1", "name": "research_source"},
            ),
            dsh_event(
                2,
                "tool/result",
                {
                    "message": {
                        "content": [
                            {
                                "toolCallId": "delegate-1",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"started subagent {child_id}",
                                    }
                                ],
                            }
                        ]
                    }
                },
            ),
        ]
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_id] = {
            "running": True,
            "events": [
                dsh_event(
                    1,
                    "assistant/message",
                    {"message": {"content": [{"type": "text", "text": "untrusted"}]}},
                )
            ],
            "title": "wrong lineage",
            "parentSessionId": "another-root",
            "origin": "user",
        }
        self.events.pending[child_id] = [
            {
                "rpc_id": "untrusted-rpc",
                "kind": "approval",
                "approval_id": "untrusted-approval",
                "received_at": 1,
            }
        ]

        conversation = self.runtime.conversation(self.task_id)

        child = next(
            item for item in conversation["agents"] if item["agent_id"] == "research_source"
        )
        self.assertFalse(child["lineage_verified"])
        self.assertNotIn("dsh_session_id", child)
        self.assertEqual(child["candidate_dsh_session_id"], child_id)
        self.assertEqual(
            conversation["projection_errors"],
            [{"session_id": child_id, "error": "dsh_subagent_lineage_mismatch"}],
        )
        self.assertEqual(conversation["pending"], [])
        self.assertEqual(conversation["work_items"], [])
        self.assertFalse(
            any(
                method == "session.history" and payload.get("sessionId") == child_id
                for method, payload in self.client.calls
            )
        )
        with self.assertRaisesRegex(MultiAgentRuntimeError, "失效"):
            self.runtime.answer_approval(
                self.task_id,
                "untrusted-rpc",
                "allowed-once",
            )

    def test_fresh_training_task_revision_is_used_for_every_prompt(self) -> None:
        self.runtime.prompt(self.task_id, "ASR", "第一轮")
        updated = read_json(self.task_dir / "task.json")
        updated["current_spec_revision"] = 2
        updated["status"] = "awaiting_data"
        write_json(self.task_dir / "task.json", updated)

        self.runtime.prompt(self.task_id, "ASR", "第二轮")

        prompt_calls = [
            payload
            for method, payload in self.client.calls
            if method == "session.prompt"
        ]
        self.assertIn("observed_spec_revision=2", prompt_calls[-1]["content"][0]["text"])
        team = read_json(self.task_dir / "agent_team" / "team.json")
        self.assertEqual(team["runs"][-1]["task_spec_revision"], 2)
        self.assertEqual(read_json(self.task_dir / "task.json"), updated)

    def test_task_team_sessions_are_reused_and_isolated_across_restart(self) -> None:
        task_a_session = self.runtime.prompt(self.task_id, "ASR", "第一轮")
        task_b_id = "零件分类-task-b"
        task_b_dir = self.root / "tasks" / task_b_id
        write_json(
            task_b_dir / "task.json",
            {
                "schema_version": "0.9",
                "task_id": task_b_id,
                "name": "零件分类",
                "status": "awaiting_data",
                "current_spec_revision": 1,
            },
        )
        task_b_session = self.runtime.prompt(task_b_id, "零件分类", "第一轮")
        self.assertNotEqual(task_a_session, task_b_session)

        restarted = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=self.client,  # type: ignore[arg-type]
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )
        self.assertEqual(restarted.session_for(self.task_id), task_a_session)
        self.assertEqual(restarted.session_for(task_b_id), task_b_session)
        restarted.prompt(self.task_id, "ASR", "第二轮")
        self.assertEqual(
            [method for method, _payload in self.client.calls].count("session.create"),
            2,
        )

    def test_runtime_rpc_failures_preserve_training_task_truth(self) -> None:
        task_before = (self.task_dir / "task.json").read_bytes()
        create_failure = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=FakeDshClient(  # type: ignore[arg-type]
                fail_methods={"session.create"}
            ),
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )
        with self.assertRaisesRegex(MultiAgentRuntimeError, "session.create"):
            create_failure.prompt(self.task_id, "ASR", "开始")
        self.assertEqual((self.task_dir / "task.json").read_bytes(), task_before)
        self.assertFalse((self.task_dir / "agent_team" / "team.json").exists())

        prompt_client = FakeDshClient(fail_methods={"session.prompt"})
        prompt_failure = DshMultiAgentRuntime(
            workspace_root=self.root,
            client=prompt_client,  # type: ignore[arg-type]
            events=FakeEventHub(),  # type: ignore[arg-type]
            cwd=self.root,
        )
        with self.assertRaises(ComposerSubmissionError) as failure_context:
            prompt_failure.submit_message(
                self.task_id,
                "ASR",
                "开始",
                request_id="composer-request-provider-failure",
            )
        self.assertEqual(
            failure_context.exception.request_id,
            "composer-request-provider-failure",
        )
        self.assertEqual(failure_context.exception.status, "failed")
        self.assertTrue(failure_context.exception.new_request_required)
        self.assertEqual((self.task_dir / "task.json").read_bytes(), task_before)
        team = read_json(self.task_dir / "agent_team" / "team.json")
        self.assertEqual(team["runs"][-1]["status"], "failed")
        self.assertIn("session.prompt", team["runs"][-1]["error"])
        prompt_call_count = len(
            [call for call in prompt_client.calls if call[0] == "session.prompt"]
        )
        with self.assertRaises(ComposerRequestTerminalError) as replay_context:
            prompt_failure.submit_message(
                self.task_id,
                "ASR",
                "开始",
                request_id="composer-request-provider-failure",
            )
        self.assertEqual(replay_context.exception.status, "failed")
        self.assertTrue(replay_context.exception.new_request_required)
        self.assertEqual(
            len([call for call in prompt_client.calls if call[0] == "session.prompt"]),
            prompt_call_count,
        )

    def test_cancel_and_lifecycle_interfaces_delegate_to_dsh(self) -> None:
        task_before = (self.task_dir / "task.json").read_bytes()
        session_id = self.runtime.prompt(self.task_id, "ASR", "开始")
        self.runtime.start()
        self.runtime.cancel(self.task_id)
        self.runtime.stop()

        self.assertTrue(self.events.started)
        self.assertTrue(self.events.stopped)
        self.assertIn(
            ("session.cancel", {"sessionId": session_id}),
            self.client.calls,
        )
        team = read_json(self.task_dir / "agent_team" / "team.json")
        self.assertEqual(team["runs"][-1]["status"], "cancel_requested")
        self.assertEqual((self.task_dir / "task.json").read_bytes(), task_before)

    def test_cancel_cascade_marks_every_active_agent_run_without_fake_activity(
        self,
    ) -> None:
        self.runtime.submit_message(
            self.task_id,
            "ASR",
            "第一轮",
            request_id="composer-request-first",
        )
        self.runtime.submit_message(
            self.task_id,
            "ASR",
            "第二轮",
            request_id="composer-request-second",
        )
        team = read_json(self.task_dir / "agent_team" / "team.json")
        first, second = team["runs"]
        self.runtime.store.update_run(
            task_id=self.task_id,
            run_id=first["run_id"],
            status="running",
        )
        self.runtime.store.update_run(
            task_id=self.task_id,
            run_id=second["run_id"],
            status="waiting_for_human",
        )

        result = self.runtime.cancel(
            self.task_id,
            actor="user",
            reason="Stop both turns",
            cancellation_kind="user_requested",
        )

        team = read_json(self.task_dir / "agent_team" / "team.json")
        self.assertEqual(
            [run["status"] for run in team["runs"]],
            ["cancel_requested", "cancel_requested"],
        )
        self.assertEqual(
            [run["cancel_request"] for run in team["runs"]],
            [result["cancellation"], result["cancellation"]],
        )
        session_id = result["cancelled_session_ids"][0]
        self.client.sessions[session_id]["running"] = True
        cancelling = self.runtime.conversation(self.task_id)
        self.assertTrue(cancelling["running"])
        self.assertEqual(cancelling["interaction_state"], "cancelling")
        self.assertEqual(
            cancelling["interaction_projection"]["phase"],
            "stopping",
        )
        self.assertFalse(cancelling["interaction_projection"]["can_cancel"])
        self.assertFalse(cancelling["can_cancel_agent"])
        self.assertEqual(
            cancelling["primary_attention"],
            {
                "object_type": "AgentTurn",
                "object_id": second["agent_turn_id"],
                "reason": "cancellation_in_progress",
            },
        )
        self.assertEqual(
            [turn["status"] for turn in cancelling["agent_turns"]],
            ["cancel_requested", "cancel_requested"],
        )

        self.client.sessions[session_id]["running"] = False
        self.client.sessions[session_id]["events"] = [
            dsh_event(
                10,
                "turn/end",
                {"turn": 2, "reason": {"kind": "cancelled"}},
            )
        ]
        conversation = self.runtime.conversation(self.task_id)
        self.assertFalse(conversation["running"])
        self.assertEqual(conversation["interaction_state"], "terminal")
        self.assertEqual(
            conversation["interaction_projection"]["phase"],
            "stopped",
        )
        self.assertFalse(
            any(turn["response_running"] for turn in conversation["agent_turns"])
        )
        self.assertEqual(
            [turn["status"] for turn in conversation["agent_turns"]],
            ["cancelled", "cancelled"],
        )
        settled = read_json(self.task_dir / "agent_team" / "team.json")["runs"]
        self.assertEqual(
            [run["cancellation_convergence"] for run in settled],
            ["observed_turn_cancelled", "observed_turn_cancelled"],
        )
        self.assertEqual(
            len({run["terminal_cancel_event_id"] for run in settled}),
            1,
        )

    def test_composer_request_is_durable_and_unverified_modes_fail_closed(self) -> None:
        submission = self.runtime.submit_message(
            self.task_id,
            "ASR",
            "排在当前回合之后",
            composer_mode="queue_after_turn",
            request_id="composer-request-client-1",
            actor="user",
        )

        self.assertEqual(submission["request_id"], "composer-request-client-1")
        self.assertEqual(submission["composer_mode"], "queue_after_turn")
        team = read_json(self.task_dir / "agent_team" / "team.json")
        run = team["runs"][-1]
        self.assertEqual(run["agent_turn_id"], submission["agent_turn_id"])
        self.assertEqual(
            run["composer_request"],
            {
                "schema_version": "1.0",
                "request_id": "composer-request-client-1",
                "mode": "queue_after_turn",
                "actor": "user",
                "submitted_at_utc": run["composer_request"]["submitted_at_utc"],
            },
        )
        prompt_calls_before = len(
            [call for call in self.client.calls if call[0] == "session.prompt"]
        )
        replay = self.runtime.submit_message(
            self.task_id,
            "ASR",
            "排在当前回合之后",
            composer_mode="queue_after_turn",
            request_id="composer-request-client-1",
            actor="user",
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["agent_turn_id"], submission["agent_turn_id"])
        self.assertEqual(
            len([call for call in self.client.calls if call[0] == "session.prompt"]),
            prompt_calls_before,
        )
        with self.assertRaises(ComposerRequestConflictError):
            self.runtime.submit_message(
                self.task_id,
                "ASR",
                "同一个 id 不能改成另一条消息",
                composer_mode="queue_after_turn",
                request_id="composer-request-client-1",
                actor="user",
            )
        self.runtime.store.update_run(
            task_id=self.task_id,
            run_id=submission["agent_run_id"],
            status="cancelled",
        )
        with self.assertRaises(ComposerRequestTerminalError) as terminal_context:
            self.runtime.submit_message(
                self.task_id,
                "ASR",
                "排在当前回合之后",
                composer_mode="queue_after_turn",
                request_id="composer-request-client-1",
                actor="user",
            )
        self.assertEqual(terminal_context.exception.status, "cancelled")
        self.assertTrue(terminal_context.exception.new_request_required)
        for mode in ("intervene_current", "stop_and_replace"):
            with self.subTest(mode=mode):
                with self.assertRaises(ComposerModeUnsupportedError):
                    self.runtime.submit_message(
                        self.task_id,
                        "ASR",
                        "不要伪造执行语义",
                        composer_mode=mode,
                        request_id=f"request-{mode}",
                    )
        self.assertEqual(
            len([call for call in self.client.calls if call[0] == "session.prompt"]),
            prompt_calls_before,
        )
        self.assertEqual(
            len(read_json(self.task_dir / "agent_team" / "team.json")["runs"]),
            1,
        )

    def test_agent_stop_cascades_and_background_action_stays_distinct(self) -> None:
        session_id = self.runtime.prompt(self.task_id, "ASR", "开始后台训练")
        run_id = self._latest_agent_run_id()
        child_session_id = "dsh-child-cancel-cascade"
        team = read_json(self.task_dir / "agent_team" / "team.json")
        team["agents"]["build_training"] = {
            "agent_id": "build_training",
            "agent_label": "Build & Training Agent",
            "role_id": "build_training",
            "dsh_session_id": child_session_id,
            "lineage_verified": True,
            "lineage_origin": "subagent",
            "lineage_parent_session_id": session_id,
            "status": "completed",
        }
        team["delegations"]["delegate-training"] = {
            "delegation_id": "delegate-training",
            "parent_delegation_id": None,
            "agent_run_id": run_id,
            "source_agent_id": "training_orchestrator",
            "source_session_id": session_id,
            "target_agent_id": "build_training",
            "target_agent_label": "Build & Training Agent",
            "dsh_session_id": child_session_id,
            "status": "running",
        }
        write_json(self.task_dir / "agent_team" / "team.json", team)
        self.client.sessions[session_id]["running"] = False
        self.client.sessions[child_session_id] = {
            "running": False,
            "events": [],
            "title": "training",
            "parentSessionId": session_id,
            "origin": "subagent",
        }
        observed = {
            "action_id": "training-run:run-1",
            "action_type": "training_run",
            "task_id": self.task_id,
            "run_id": "run-1",
            "status": "training",
            "running": True,
            "worker_running": True,
            "cancel_requested": False,
        }
        cancelled: list[tuple[str, dict[str, Any]]] = []
        self.runtime.background_actions_provider = lambda _task_id: [observed]

        def cancel_actions(
            task_id: str, cancellation: Mapping[str, Any]
        ) -> list[dict[str, Any]]:
            cancelled.append((task_id, dict(cancellation)))
            return [
                {
                    **observed,
                    "status": "cancel_requested",
                    "cancel_requested": True,
                }
            ]

        self.runtime.background_actions_canceller = cancel_actions

        conversation = self.runtime.conversation(self.task_id)

        self.assertFalse(conversation["agent_response_running"])
        self.assertTrue(conversation["background_action_running"])
        self.assertTrue(conversation["execution_running"])
        self.assertEqual(
            conversation["interaction_projection"]["phase"],
            "background_working",
        )
        self.assertEqual(conversation["background_actions"], [observed])
        self.assertEqual(conversation["supported_modes"], ["queue_after_turn"])
        self.assertEqual(
            conversation["training_runs"][0]["training_run_id"], "run-1"
        )
        self.assertEqual(
            conversation["primary_attention"]["object_type"], "TrainingRun"
        )

        team = read_json(self.task_dir / "agent_team" / "team.json")
        team["agents"]["build_training"]["status"] = "running"
        team["delegations"]["delegate-training"]["status"] = "running"
        write_json(self.task_dir / "agent_team" / "team.json", team)
        self.client.sessions[child_session_id]["running"] = True

        result = self.runtime.cancel(self.task_id)

        self.assertEqual(
            result["cancelled_session_ids"],
            [session_id, child_session_id],
        )
        self.assertEqual(
            cancelled,
            [
                (
                    self.task_id,
                    {
                        "cancellation_id": cancelled[0][1]["cancellation_id"],
                        "actor": "user",
                        "kind": "user_requested",
                        "reason": "User requested stop",
                        "scope": "task_execution",
                        "requested_at_utc": cancelled[0][1]["requested_at_utc"],
                    },
                )
            ],
        )
        self.assertTrue(result["background_actions"][0]["cancel_requested"])
        self.assertIn(
            ("session.cancel", {"sessionId": child_session_id}),
            self.client.calls,
        )
        cascade_event = next(
            event
            for event in self.runtime.store.list_events(self.task_id)
            if event.get("event_type") == "agent.cancel_cascade_requested"
        )
        self.assertEqual(cascade_event["payload"]["cascade_errors"], [])

    def test_background_action_can_be_cancelled_before_agent_team_exists(self) -> None:
        observed = {
            "action_id": "training-run:run-without-team",
            "action_type": "training_run",
            "task_id": self.task_id,
            "run_id": "run-without-team",
            "status": "training",
            "running": True,
            "worker_running": True,
            "cancel_requested": False,
        }
        cancelled: list[tuple[str, dict[str, Any]]] = []
        self.runtime.background_actions_provider = lambda _task_id: [observed]

        def cancel_actions(
            task_id: str, cancellation: Mapping[str, Any]
        ) -> list[dict[str, Any]]:
            cancelled.append((task_id, dict(cancellation)))
            return [
                {
                    **observed,
                    "status": "cancel_requested",
                    "cancel_requested": True,
                }
            ]

        self.runtime.background_actions_canceller = cancel_actions

        conversation = self.runtime.conversation(self.task_id)
        result = self.runtime.cancel(self.task_id)

        self.assertTrue(conversation["can_cancel_agent"])
        self.assertFalse(conversation["agent_response_running"])
        self.assertTrue(conversation["background_action_running"])
        self.assertEqual(result["cancelled_session_ids"], [])
        self.assertTrue(result["background_actions"][0]["cancel_requested"])
        self.assertEqual(
            cancelled,
            [
                (
                    self.task_id,
                    {
                        "cancellation_id": cancelled[0][1]["cancellation_id"],
                        "actor": "user",
                        "kind": "user_requested",
                        "reason": "User requested stop",
                        "scope": "task_execution",
                        "requested_at_utc": cancelled[0][1]["requested_at_utc"],
                    },
                )
            ],
        )


class ProjectorUnitTests(unittest.TestCase):
    @staticmethod
    def _verified_child_team(*, nested: bool = False) -> dict[str, Any]:
        team: dict[str, Any] = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "runs": [{"run_id": "agent-run-1"}],
            "agents": {
                "training_orchestrator": {
                    "agent_id": "training_orchestrator",
                    "dsh_session_id": "root",
                },
                "research_source": {
                    "agent_id": "research_source",
                    "agent_label": "Research & Source Agent",
                    "dsh_session_id": "child-1",
                    "lineage_verified": True,
                    "lineage_origin": "subagent",
                    "lineage_parent_session_id": "root",
                },
            },
            "delegations": {
                "delegate-1": {
                    "delegation_id": "delegate-1",
                    "agent_run_id": "agent-run-1",
                    "source_agent_id": "training_orchestrator",
                    "target_agent_id": "research_source",
                    "dsh_session_id": "child-1",
                }
            },
        }
        if nested:
            team["agents"]["resource_safety"] = {
                "agent_id": "resource_safety",
                "agent_label": "Resource & Safety Agent",
                "dsh_session_id": "child-2",
                "lineage_verified": True,
                "lineage_origin": "subagent",
                "lineage_parent_session_id": "child-1",
            }
            team["delegations"]["delegate-2"] = {
                "delegation_id": "delegate-2",
                "parent_delegation_id": "delegate-1",
                "agent_run_id": "agent-run-1",
                "source_agent_id": "research_source",
                "target_agent_id": "resource_safety",
                "dsh_session_id": "child-2",
            }
        return team

    def test_verified_child_tool_events_inherit_run_and_delegation_identity(
        self,
    ) -> None:
        projected = DshConversationV2Projector().project(
            task_id="task",
            team=self._verified_child_team(),
            session_id="child-1",
            session_agent_id="research_source",
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {"callId": "tool-1", "name": "model_harness_get_task"},
                    ),
                    dsh_event(
                        2,
                        "tool/result",
                        {"callId": "tool-1", "result": {"ok": True}},
                    ),
                ]
            },
        )

        self.assertEqual(len(projected), 2)
        self.assertTrue(
            all(item["agent_run_id"] == "agent-run-1" for item in projected)
        )
        self.assertTrue(
            all(item["delegation_id"] == "delegate-1" for item in projected)
        )
        self.assertTrue(
            all(item["parent_delegation_id"] is None for item in projected)
        )

    def test_child_projection_fails_closed_without_unique_verified_topology(
        self,
    ) -> None:
        unverified = self._verified_child_team()
        unverified["agents"]["research_source"]["lineage_verified"] = False
        ambiguous = self._verified_child_team()
        ambiguous["delegations"]["delegate-duplicate"] = {
            **ambiguous["delegations"]["delegate-1"],
            "delegation_id": "delegate-duplicate",
        }
        for label, team in (("unverified", unverified), ("ambiguous", ambiguous)):
            with self.subTest(label=label):
                projected = DshConversationV2Projector().project(
                    task_id="task",
                    team=team,
                    session_id="child-1",
                    session_agent_id="research_source",
                    history={
                        "events": [
                            dsh_event(
                                1,
                                "tool/call",
                                {
                                    "callId": "tool-1",
                                    "name": "model_harness_get_task",
                                },
                            )
                        ]
                    },
                )

                self.assertIsNone(projected[0]["agent_run_id"])
                self.assertIsNone(projected[0]["delegation_id"])
                self.assertIsNone(projected[0]["parent_delegation_id"])

    def test_nested_child_projection_preserves_delegation_chain(self) -> None:
        projector = DshConversationV2Projector()
        team = self._verified_child_team(nested=True)
        parent_projection = projector.project(
            task_id="task",
            team=team,
            session_id="child-1",
            session_agent_id="research_source",
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {
                            "callId": "delegate-2",
                            "name": "spawn_agent",
                            "input": {"targetAgentId": "resource_safety"},
                        },
                    ),
                    dsh_event(
                        2,
                        "tool/result",
                        {
                            "callId": "delegate-2",
                            "result": {
                                "agentId": "resource_safety",
                                "sessionId": "child-2",
                            },
                        },
                    ),
                ]
            },
        )
        nested_projection = projector.project(
            task_id="task",
            team=team,
            session_id="child-2",
            session_agent_id="resource_safety",
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {"callId": "tool-2", "name": "model_harness_get_task"},
                    ),
                    dsh_event(
                        2,
                        "tool/result",
                        {"callId": "tool-2", "result": {"ok": True}},
                    ),
                ]
            },
        )

        self.assertTrue(
            all(item["delegation_id"] == "delegate-2" for item in parent_projection)
        )
        self.assertTrue(
            all(
                item["parent_delegation_id"] == "delegate-1"
                for item in parent_projection
            )
        )
        self.assertTrue(
            all(item["delegation_id"] == "delegate-2" for item in nested_projection)
        )
        self.assertTrue(
            all(
                item["parent_delegation_id"] == "delegate-1"
                for item in nested_projection
            )
        )

    def test_projector_does_not_invent_events_for_unknown_history(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }

        projected = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(1, "unrecognized/runtime/event", {"value": 1})
                ]
            },
        )

        self.assertEqual(projected, [])

    def test_projector_fails_closed_for_non_completed_turn_end(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }

        projected = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(
                        1,
                        "turn/end",
                        {"turn": 1, "reason": {"kind": "blocked"}},
                    )
                ]
            },
        )

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["type"], "turn_error")
        self.assertEqual(projected[0]["status"], "failed")
        self.assertEqual(
            projected[0]["payload"]["error"]["code"],
            "TURN_BLOCKED",
        )

    def test_tool_result_projects_only_observed_object_refs_from_supported_wrappers(
        self,
    ) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }
        object_ref = {
            "type": "model_source_search",
            "id": "search-0a1b2c",
            "task_id": "task-voice",
            "label": "模型候选 · search-0a1b2c",
            "base_spec_revision": 3,
        }
        serialized = json.dumps(
            {"object_refs": [object_ref]},
            ensure_ascii=False,
        )
        result_shapes = {
            "object": {"object_refs": [object_ref]},
            "json-string": serialized,
            "content-wrapper": {
                "content": [{"type": "text", "text": serialized}]
            },
        }

        for label, result in result_shapes.items():
            with self.subTest(label=label):
                projected = projector.project(
                    task_id="task-voice",
                    team=team,
                    history={
                        "events": [
                            dsh_event(
                                1,
                                "tool/call",
                                {
                                    "callId": "search-call",
                                    "name": "model_harness_search_model_sources",
                                },
                            ),
                            dsh_event(
                                2,
                                "tool/result",
                                {
                                    "message": {
                                        "content": [
                                            {
                                                "toolCallId": "search-call",
                                                "content": result,
                                            }
                                        ]
                                    }
                                },
                            ),
                        ]
                    },
                )

                tool_result = projected[-1]
                self.assertEqual(tool_result["type"], "tool_result")
                self.assertEqual(
                    tool_result["payload"]["object_refs"],
                    [object_ref],
                )
                self.assertEqual(tool_result["payload"]["result"], result)

        unstructured = projector.project(
            task_id="task-voice",
            team=team,
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/result",
                        {
                            "result": (
                                "object_refs=[{type:model_source_search,id:invented}]"
                            )
                        },
                    )
                ]
            },
        )
        self.assertNotIn("object_refs", unstructured[0]["payload"])

    def test_native_delegate_start_is_running_until_child_turn_finishes(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }
        projected = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {"callId": "delegate-1", "name": "research_source"},
                    ),
                    dsh_event(
                        2,
                        "tool/result",
                        {
                            "message": {
                                "content": [
                                    {
                                        "toolCallId": "delegate-1",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "started subagent 12f532d0-613c-4a0e-9183-8c69dbcee133",
                                            }
                                        ],
                                    }
                                ]
                            }
                        },
                    ),
                ]
            },
        )

        self.assertEqual([item["type"] for item in projected], ["delegation", "delegation"])
        self.assertEqual(projected[-1]["status"], "running")
        self.assertEqual(
            projected[-1]["payload"]["dsh_session_id"],
            "12f532d0-613c-4a0e-9183-8c69dbcee133",
        )

    def test_root_work_message_is_plan_and_child_history_keeps_child_identity(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }
        root_projection = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(
                        1,
                        "assistant/message",
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "并行启动两个专家。"},
                                    {"type": "tool-call", "name": "research_source"},
                                ]
                            }
                        },
                    )
                ]
            },
        )
        child_projection = projector.project(
            task_id="task",
            team=team,
            session_id="child-1",
            session_agent_id="research_source",
            session_agent_label="Research & Source Agent",
            history={
                "events": [
                    dsh_event(
                        1,
                        "tool/call",
                        {"callId": "tool-1", "name": "model_harness_hf_search"},
                    ),
                    dsh_event(
                        2,
                        "assistant/message",
                        {"message": {"content": [{"type": "text", "text": "候选已取证。"}]}},
                    ),
                    dsh_event(3, "turn/end", {"reason": {"kind": "completed"}}),
                ]
            },
        )

        self.assertEqual(root_projection[0]["type"], "coordinator_plan")
        self.assertEqual(
            [item["type"] for item in child_projection],
            ["tool_call", "specialist_output", "specialist_status"],
        )
        self.assertTrue(
            all(item["agent_id"] == "research_source" for item in child_projection)
        )
        self.assertEqual(child_projection[-1]["status"], "completed")

    def test_runtime_policy_and_session_patch_events_are_not_product_activity(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }
        projected = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(1, "approval/policy", {"policy": "ask"}),
                    dsh_event(2, "session/messages/patch", {"inserted": ["internal"]}),
                ]
            },
        )

        self.assertEqual(projected, [])

    def test_root_has_one_synthesis_candidate_after_all_native_children_report(self) -> None:
        projector = DshConversationV2Projector()
        team = {
            "root_session_id": "root",
            "root_agent_id": "training_orchestrator",
            "agents": {},
        }
        child_id = "12f532d0-613c-4a0e-9183-8c69dbcee133"
        projected = projector.project(
            task_id="task",
            team=team,
            history={
                "events": [
                    dsh_event(
                        1,
                        "assistant/message",
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "启动研究专家"},
                                    {"type": "tool-call", "name": "research_source"},
                                ]
                            }
                        },
                    ),
                    dsh_event(2, "tool/call", {"callId": "d1", "name": "research_source"}),
                    dsh_event(
                        3,
                        "tool/result",
                        {
                            "message": {
                                "content": [
                                    {
                                        "toolCallId": "d1",
                                        "content": [
                                            {"type": "text", "text": f"started subagent {child_id}"}
                                        ],
                                    }
                                ]
                            }
                        },
                    ),
                    dsh_event(
                        4,
                        "assistant/message",
                        {"message": {"content": [{"type": "text", "text": "仍在等待研究"}]}},
                    ),
                    dsh_event(
                        5,
                        "user/message",
                        {
                            "source": {
                                "kind": "subagent-report",
                                "senderSessionId": child_id,
                            },
                            "content": [{"type": "text", "text": "研究报告"}],
                        },
                    ),
                    dsh_event(
                        6,
                        "assistant/message",
                        {"message": {"content": [{"type": "text", "text": "最终综合"}]}},
                    ),
                ]
            },
        )

        self.assertEqual(
            [item["type"] for item in projected].count("synthesis_candidate"),
            1,
        )
        waiting = next(
            item for item in projected if item.get("payload", {}).get("text") == "仍在等待研究"
        )
        self.assertEqual(waiting["type"], "coordinator_plan")


if __name__ == "__main__":
    unittest.main()
