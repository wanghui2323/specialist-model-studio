from __future__ import annotations

import json
import http.client
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .io_utils import read_json, write_json


class AgentRuntimeError(RuntimeError):
    """Raised when the delegated Agent runtime cannot satisfy a request."""


TOOL_LABELS = {
    "model_harness_list_recipes": "检查可用训练方案",
    "model_harness_list_data_adapters": "检查数据适配器",
    "model_harness_match_capability": "匹配训练能力",
    "model_harness_list_tasks": "检查现有训练任务",
    "model_harness_create_task": "创建训练任务",
    "model_harness_scaffold_recipe": "生成Recipe构建包",
    "model_harness_get_task": "读取训练任务",
    "model_harness_hf_capability": "检查HF能力边界",
    "model_harness_hf_search": "搜索HF模型",
    "model_harness_hf_card": "读取HF模型卡",
    "model_harness_hf_attach": "绑定HF固定版本模型",
    "model_harness_hf_verify": "验证HF模型资产",
    "model_harness_import_dataset": "导入并体检数据",
    "model_harness_configure_contract": "调整训练合同",
    "model_harness_confirm_contract": "确认训练合同",
    "model_harness_start_task_run": "启动真实训练",
    "model_harness_get_run": "读取训练结果",
    "model_harness_get_evaluation_report": "读取评测报告",
    "model_harness_run_sample_inference": "试跑用户新样本",
    "model_harness_list_sample_inferences": "查看新样本试跑",
    "model_harness_get_sample_inference": "读取试跑证据",
    "model_harness_build_artifact_bundle": "构建交付包",
    "model_harness_list_artifact_bundles": "查看交付包",
    "model_harness_get_artifact_bundle": "读取交付包证据",
    "model_harness_download_artifact_bundle": "下载交付包",
    "model_harness_get_events": "读取运行事件",
    "model_harness_get_strategies": "分析优化策略",
    "model_harness_apply_task_strategy": "执行下一轮优化",
    "model_harness_cancel_run": "取消训练运行",
    "ask_user_question": "等待你的决定",
    "todo_write": "更新执行计划",
}


_AGENT_PUBLIC_REDACTED = "[local-path-redacted]"
_AGENT_PUBLIC_SENSITIVE_KEYS = frozenset(
    {
        "root",
        "cwd",
        "working_directory",
        "workspace_root",
        "dataset_root",
        "manifest_path",
        "report_path",
        "contract_path",
        "archive_path",
        "local_path",
        "filesystem_path",
        "source_path",
        "run_dir",
        "task_dir",
        "dataset_dir",
        "artifact_dir",
    }
)
_AGENT_PUBLIC_ROUTE_ROOTS = (
    "/agent",
    "/app",
    "/capabilities",
    "/chat",
    "/data-adapters",
    "/health",
    "/model-assets",
    "/recipes",
    "/runs",
    "/runtime",
    "/tasks",
)
_AGENT_PUBLIC_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_AGENT_PUBLIC_EMBEDDED_WINDOWS_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>]+"
)
_AGENT_PUBLIC_EMBEDDED_POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9:/])/[^\s\"'<>]+"
)


def _agent_public_route(value: str) -> bool:
    return any(
        value == root
        or value.startswith(f"{root}/")
        or value.startswith(f"{root}?")
        for root in _AGENT_PUBLIC_ROUTE_ROOTS
    )


def _agent_local_absolute_path(value: str) -> bool:
    selected = value.strip()
    if not selected:
        return False
    if selected.startswith(("file://", "~/", "~\\")):
        return True
    if _AGENT_PUBLIC_WINDOWS_PATH.match(selected):
        return True
    return selected.startswith("/") and not _agent_public_route(selected)


def _agent_public_text(value: str) -> str:
    if _agent_local_absolute_path(value):
        return _AGENT_PUBLIC_REDACTED
    projected = _AGENT_PUBLIC_EMBEDDED_WINDOWS_PATH.sub(
        _AGENT_PUBLIC_REDACTED,
        value,
    )
    return _AGENT_PUBLIC_EMBEDDED_POSIX_PATH.sub(
        lambda match: (
            match.group(0)
            if _agent_public_route(match.group(0))
            else _AGENT_PUBLIC_REDACTED
        ),
        projected,
    )


def agent_public_projection(value: Any) -> Any:
    """Return the path-safe object contract exposed to a remote Agent.

    Local APIs and the product UI keep their full local projection.  The DSH
    boundary uses this recursive copy so dataset, contract, model-asset and
    evidence objects cannot reveal host filesystem locations.
    """

    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.strip().lower().replace("-", "_")
            sensitive = (
                normalized in _AGENT_PUBLIC_SENSITIVE_KEYS
                or normalized.endswith("_root")
                or (
                    normalized == "path" or normalized.endswith("_path")
                )
                and isinstance(child, (str, Path))
                and _agent_local_absolute_path(str(child))
            )
            if sensitive:
                continue
            projected[key] = agent_public_projection(child)
        return projected
    if isinstance(value, (list, tuple)):
        return [agent_public_projection(item) for item in value]
    if isinstance(value, Path):
        return _AGENT_PUBLIC_REDACTED
    if isinstance(value, str):
        return _agent_public_text(value)
    return value


def _text_content(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


class DshRpcClient:
    """Small product-facing adapter over DeepSeek Harness's public HTTP RPC."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("DSH bridge currently requires an http:// host")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self._rpc_lock = threading.RLock()
        self._rpc_connection: http.client.HTTPConnection | None = None

    def connection(self, timeout: float | None = None) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout_seconds if timeout is None else timeout,
        )

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        rpc_id = f"model-harness-{uuid4()}"
        envelope = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload,
        }
        status, body = self._post_envelope(
            f"/api/{method}",
            envelope,
            error_prefix="训练 Agent 运行时不可用",
        )
        if status >= 400:
            raise AgentRuntimeError(f"训练 Agent 返回 HTTP {status}")
        result = body.get("result", {}) if isinstance(body, dict) else {}
        if body.get("rpcId") != rpc_id or not result.get("ok"):
            error = result.get("error", {})
            message = error.get("message") or "训练 Agent 返回了无效响应"
            raise AgentRuntimeError(str(message))
        return result.get("value")

    def respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        envelope = {
            "type": "client-response",
            "rpcId": rpc_id,
            "result": {"ok": True, "value": value},
        }
        status, receipt = self._post_envelope(
            "/api/respond",
            envelope,
            error_prefix="无法提交你的决定",
        )
        if status >= 400:
            raise AgentRuntimeError(f"无法提交你的决定：HTTP {status}")
        if receipt.get("accepted") is not True:
            raise AgentRuntimeError("该决定已失效，请刷新任务后重试")

    def _post_envelope(
        self,
        path: str,
        envelope: dict[str, Any],
        *,
        error_prefix: str,
    ) -> tuple[int, dict[str, Any]]:
        encoded = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        with self._rpc_lock:
            for _attempt in range(2):
                request_sent = False
                connection = self._rpc_connection
                if connection is None:
                    connection = self.connection()
                    self._rpc_connection = connection
                try:
                    connection.request(
                        "POST",
                        path,
                        body=encoded,
                        headers={
                            "content-type": "application/json",
                            "connection": "keep-alive",
                        },
                    )
                    request_sent = True
                    response = connection.getresponse()
                    raw = response.read().decode("utf-8")
                    body = json.loads(raw)
                    if response.will_close:
                        self._close_rpc_connection_locked()
                    if not isinstance(body, dict):
                        raise json.JSONDecodeError("response is not an object", raw, 0)
                    return response.status, body
                except (
                    OSError,
                    http.client.HTTPException,
                    TimeoutError,
                    json.JSONDecodeError,
                ) as exc:
                    last_error = exc
                    self._close_rpc_connection_locked()
                    if request_sent:
                        break
            raise AgentRuntimeError(f"{error_prefix}：{last_error}") from last_error

    def _close_rpc_connection_locked(self) -> None:
        connection = self._rpc_connection
        self._rpc_connection = None
        if connection is not None:
            connection.close()

    def close(self) -> None:
        """Release the reusable unary connection during application shutdown."""

        with self._rpc_lock:
            self._close_rpc_connection_locked()

    def available(self) -> bool:
        try:
            self.call("session.list", {})
        except AgentRuntimeError:
            return False
        return True


class DshEventHub:
    """Keeps DSH approval and question requests visible and restart-safe."""

    PENDING_SCHEMA_VERSION = "0.1"
    PENDING_STATE_FILENAME = "conversation_pending.json"
    STREAM_TIMEOUT_SECONDS = 300.0
    RECONNECT_DELAY_SECONDS = 2.0

    def __init__(self, client: DshRpcClient) -> None:
        self.client = client
        self._pending: dict[str, dict[str, dict[str, Any]]] = {}
        self._state_path: Path | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream_lock = threading.RLock()
        self._stream_connection: http.client.HTTPConnection | None = None

    def bind_workspace(self, root: Path) -> None:
        """Bind pending requests to the workspace before consuming runtime events."""

        state_path = root.expanduser().resolve() / self.PENDING_STATE_FILENAME
        with self._lock:
            if self._state_path is not None and self._state_path != state_path:
                raise RuntimeError("DSH event hub is already bound to another workspace")
            self._state_path = state_path
            if state_path.is_file():
                value = read_json(state_path)
                sessions = value.get("sessions") if isinstance(value, dict) else None
                if (
                    not isinstance(value, dict)
                    or value.get("schema_version") != self.PENDING_SCHEMA_VERSION
                    or not isinstance(sessions, dict)
                ):
                    raise AgentRuntimeError("Agent待决状态文件格式无效")
                self._pending = self._normalize_pending(sessions)
            elif self._pending:
                self._persist_locked()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="dsh-event-hub")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._stream_lock:
            connection = self._stream_connection
            self._stream_connection = None
            if connection is not None:
                connection.close()
        if self._thread:
            self._thread.join(timeout=self.RECONNECT_DELAY_SECONDS + 1.0)
        close_client = getattr(self.client, "close", None)
        if callable(close_client):
            close_client()

    def pending_for(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            values = self._pending.get(session_id, {})
            return sorted((dict(item) for item in values.values()), key=lambda item: item["received_at"])

    def resolve_local(self, session_id: str, rpc_id: str) -> None:
        with self._lock:
            bucket = self._pending.get(session_id, {})
            if bucket.pop(rpc_id, None) is None:
                return
            if not bucket:
                self._pending.pop(session_id, None)
            self._persist_locked()

    @staticmethod
    def _normalize_pending(value: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
        pending: dict[str, dict[str, dict[str, Any]]] = {}
        for session_id, raw_bucket in value.items():
            if not isinstance(session_id, str) or not isinstance(raw_bucket, dict):
                raise AgentRuntimeError("Agent待决状态文件格式无效")
            bucket: dict[str, dict[str, Any]] = {}
            for rpc_id, raw_item in raw_bucket.items():
                if (
                    not isinstance(rpc_id, str)
                    or not isinstance(raw_item, dict)
                    or raw_item.get("rpc_id") != rpc_id
                    or raw_item.get("session_id") != session_id
                    or raw_item.get("kind") not in {"approval", "question"}
                    or not isinstance(raw_item.get("received_at"), (int, float))
                ):
                    raise AgentRuntimeError("Agent待决状态文件格式无效")
                bucket[rpc_id] = dict(raw_item)
            if bucket:
                pending[session_id] = bucket
        return pending

    def _persist_locked(self) -> None:
        if self._state_path is None:
            return
        write_json(
            self._state_path,
            {
                "schema_version": self.PENDING_SCHEMA_VERSION,
                "sessions": self._pending,
            },
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connection = self.client.connection(
                    timeout=self.STREAM_TIMEOUT_SECONDS
                )
                with self._stream_lock:
                    if self._stop.is_set():
                        connection.close()
                        return
                    self._stream_connection = connection
                try:
                    connection.request(
                        "GET",
                        "/api/events.mux",
                        headers={
                            "accept": "text/event-stream",
                            "connection": "keep-alive",
                        },
                    )
                    response = connection.getresponse()
                    if response.status >= 400:
                        raise AgentRuntimeError(
                            f"Agent 事件流返回 HTTP {response.status}"
                        )
                    buffer: list[str] = []
                    while not self._stop.is_set():
                        raw_line = response.readline()
                        if not raw_line:
                            break
                        if self._stop.is_set():
                            return
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line:
                            if line.startswith("data: "):
                                buffer.append(line[6:])
                            continue
                        if buffer:
                            self._consume("".join(buffer))
                            buffer = []
                finally:
                    with self._stream_lock:
                        if self._stream_connection is connection:
                            self._stream_connection = None
                    connection.close()
            except Exception:
                pass
            if not self._stop.is_set():
                self._stop.wait(self.RECONNECT_DELAY_SECONDS)

    def _consume(self, raw: str) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return
        rpc_id = envelope.get("rpcId")
        payload = envelope.get("payload", {})
        if not isinstance(rpc_id, str) or not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str):
            return
        with self._lock:
            bucket = self._pending.setdefault(session_id, {})
            changed = False
            if event_type == "approval/requested":
                bucket[rpc_id] = {
                    "kind": "approval",
                    "rpc_id": rpc_id,
                    "session_id": session_id,
                    "approval_id": payload.get("approvalId"),
                    "tool_name": payload.get("toolName"),
                    "title": TOOL_LABELS.get(payload.get("toolName"), "执行关键操作"),
                    "reason": payload.get("reason") or "Agent 请求执行会改变训练任务状态的操作。",
                    "received_at": time.time(),
                }
                changed = True
            elif event_type == "question/requested":
                bucket[rpc_id] = {
                    "kind": "question",
                    "rpc_id": rpc_id,
                    "session_id": session_id,
                    "questions": payload.get("questions", []),
                    "received_at": time.time(),
                }
                changed = True
            elif event_type == "approval/resolved":
                approval_id = payload.get("approvalId")
                for key, value in list(bucket.items()):
                    if value.get("approval_id") == approval_id:
                        bucket.pop(key, None)
                        changed = True
            elif event_type == "question/resolved":
                changed = bucket.pop(str(payload.get("questionRpcId")), None) is not None
            if not bucket:
                self._pending.pop(session_id, None)
            if changed:
                self._persist_locked()


class ConversationBridge:
    """Owns the stable mapping between a training task and one DSH session."""

    def __init__(self, root: Path, client: DshRpcClient, events: DshEventHub, cwd: Path) -> None:
        self.path = root / "conversations.json"
        self.client = client
        self.events = events
        self.events.bind_workspace(root)
        self.cwd = cwd.resolve()
        self._lock = threading.RLock()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "available": self.client.available(),
            "engine": "DeepSeek Harness",
            "role": "底层会话、Agent Loop、工具与审批运行时",
        }

    def session_for(self, task_id: str) -> str | None:
        with self._lock:
            return self._read().get(task_id, {}).get("session_id")

    def ensure_session(self, task_id: str, title: str) -> str:
        with self._lock:
            mappings = self._read()
            existing = mappings.get(task_id, {}).get("session_id")
            if isinstance(existing, str) and existing:
                return existing
            value = self.client.call(
                "session.create",
                {"cwd": str(self.cwd), "agentPreset": "model-training"},
            )
            session_id = value.get("sessionId") if isinstance(value, dict) else None
            if not isinstance(session_id, str) or not session_id:
                raise AgentRuntimeError("训练 Agent 未返回有效会话 ID")
            try:
                self.client.call("session.rename", {"sessionId": session_id, "title": title})
            except AgentRuntimeError:
                pass
            mappings[task_id] = {
                "session_id": session_id,
                "created_at": time.time(),
            }
            write_json(self.path, mappings)
        return session_id

    def prompt(self, task_id: str, title: str, message: str) -> str:
        session_id = self.ensure_session(task_id, title)
        instruction = (
            f"你正在 Specialist Model Studio 中推进训练任务 `{task_id}`。"
            "训练任务本身是唯一事实源；先用 model_harness_get_task 读取状态，"
            "再根据用户这条消息决定下一步，不要创建第二个任务。\n\n"
            f"用户消息：{message.strip()}"
        )
        self.client.call(
            "session.prompt",
            {
                "sessionId": session_id,
                "mode": "queue",
                "content": [{"type": "text", "text": instruction}],
                "clientTimeZone": "Asia/Shanghai",
            },
        )
        return session_id

    def cancel(self, task_id: str) -> None:
        session_id = self.session_for(task_id)
        if not session_id:
            raise AgentRuntimeError("这个任务还没有启动 Agent 会话")
        self.client.call("session.cancel", {"sessionId": session_id})

    def answer_approval(self, task_id: str, rpc_id: str, outcome: str) -> None:
        session_id = self._require_session(task_id)
        pending = {item["rpc_id"]: item for item in self.events.pending_for(session_id)}
        item = pending.get(rpc_id)
        if not item or item.get("kind") != "approval":
            raise AgentRuntimeError("这条批准请求已经失效")
        self.client.respond(
            rpc_id,
            {
                "sessionId": session_id,
                "approvalId": item["approval_id"],
                "outcome": outcome,
            },
        )
        self.events.resolve_local(session_id, rpc_id)

    def answer_question(self, task_id: str, rpc_id: str, answers: list[dict[str, Any]]) -> None:
        session_id = self._require_session(task_id)
        self.client.respond(
            rpc_id,
            {"sessionId": session_id, "answer": {"answers": answers}},
        )
        self.events.resolve_local(session_id, rpc_id)

    def conversation(self, task_id: str) -> dict[str, Any]:
        session_id = self.session_for(task_id)
        if not session_id:
            return {
                "session_id": None,
                "running": False,
                "items": [],
                "pending": [],
            }
        history = self.client.call(
            "session.history",
            {"sessionId": session_id, "maxMessages": 120},
        )
        summaries = self.client.call("session.list", {}).get("items", [])
        summary = next((item for item in summaries if item.get("sessionId") == session_id), {})
        return {
            "session_id": session_id,
            "running": bool(summary.get("running")),
            "items": self._fold_history(history.get("events", [])),
            "pending": self.events.pending_for(session_id),
        }

    def _require_session(self, task_id: str) -> str:
        session_id = self.session_for(task_id)
        if not session_id:
            raise AgentRuntimeError("这个任务还没有启动 Agent 会话")
        return session_id

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        value = read_json(self.path)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _fold_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        tools: dict[str, dict[str, Any]] = {}
        for entry in entries:
            event = entry.get("event", {})
            event_type = event.get("type")
            data = event.get("data", {})
            base = {"seq": event.get("seq", 0), "time": event.get("time")}
            if event_type == "user/message" and data.get("source", {}).get("kind") == "user":
                text = _text_content(data.get("content"))
                marker = "用户消息："
                if marker in text and "你正在 Specialist Model Studio 中" in text:
                    text = text.split(marker, 1)[1]
                if text:
                    items.append({**base, "kind": "message", "role": "user", "text": text})
            elif event_type == "assistant/message":
                text = _text_content(data.get("message", {}).get("content"))
                if text:
                    items.append({**base, "kind": "message", "role": "assistant", "text": text})
            elif event_type == "tool/call":
                call_id = data.get("callId")
                tool = {
                    **base,
                    "kind": "tool",
                    "call_id": call_id,
                    "name": data.get("name", "unknown"),
                    "label": TOOL_LABELS.get(data.get("name"), "执行训练工具"),
                    "status": "running",
                }
                if isinstance(call_id, str):
                    tools[call_id] = tool
                items.append(tool)
            elif event_type == "tool/result":
                block = (data.get("message", {}).get("content") or [{}])[0]
                call_id = block.get("toolCallId") if isinstance(block, dict) else None
                tool = tools.get(call_id)
                if tool:
                    tool["status"] = "failed" if block.get("isError") or data.get("error") else "completed"
                    tool["result"] = _text_content(block.get("content"))[:500]
        return sorted(items, key=lambda item: item.get("seq", 0))
