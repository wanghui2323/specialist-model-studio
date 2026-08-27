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
    r"(?<![\w:/])/[^\s\"'<>]+"
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


class DshRpcClient:
    """Small product-facing adapter over DeepSeek Harness's public HTTP RPC."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        *,
        reuse_unary_connection: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("DSH bridge currently requires an http:// host")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.reuse_unary_connection = reuse_unary_connection
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
                    if response.will_close or not self.reuse_unary_connection:
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
        # Availability is a probe, not part of a transactional RPC sequence.
        # Use a fresh connection so a server-side keep-alive timeout cannot turn
        # an otherwise healthy DSH runtime into a false-negative gate for the
        # following session.create call.
        with self._rpc_lock:
            self._close_rpc_connection_locked()
        try:
            self.call("session.list", {})
        except AgentRuntimeError:
            return False
        finally:
            with self._rpc_lock:
                self._close_rpc_connection_locked()
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
        self._stream_connection: Any | None = None
        self._health_lock = threading.RLock()
        self._stream_health: dict[str, Any] = {
            "connected_at": None,
            "last_event_at": None,
            "last_error_at": None,
            "consecutive_failures": 0,
            "recovered_at": None,
            "status": "not_started",
        }

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
        self._mark_stream_connecting()
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
        self._mark_stream_stopped()

    def stream_health(self) -> dict[str, Any]:
        """Return a thread-safe snapshot of the event downlink health."""

        with self._health_lock:
            return dict(self._stream_health)

    def _mark_stream_connecting(self) -> None:
        with self._health_lock:
            self._stream_health["status"] = "connecting"

    def _mark_stream_connected(self) -> None:
        now = time.time()
        with self._health_lock:
            if self._stream_health["consecutive_failures"]:
                self._stream_health["recovered_at"] = now
            self._stream_health["connected_at"] = now
            self._stream_health["consecutive_failures"] = 0
            self._stream_health["status"] = "healthy"

    def _mark_stream_event(self) -> None:
        with self._health_lock:
            self._stream_health["last_event_at"] = time.time()

    def _mark_stream_failure(self) -> None:
        with self._health_lock:
            self._stream_health["last_error_at"] = time.time()
            self._stream_health["consecutive_failures"] += 1
            self._stream_health["status"] = "degraded"

    def _mark_stream_stopped(self) -> None:
        with self._health_lock:
            self._stream_health["status"] = "stopped"

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
            self._mark_stream_connecting()
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
                    if response.status == 426:
                        # DSH rc.6 moved ordinary network event downlinks from
                        # SSE to WebSocket. Keep the SSE branch for compatible
                        # in-process/older hosts, then upgrade explicitly.
                        with self._stream_lock:
                            if self._stream_connection is connection:
                                self._stream_connection = None
                        connection.close()
                        self._consume_websocket()
                        continue
                    if response.status >= 400:
                        raise AgentRuntimeError(
                            f"Agent 事件流返回 HTTP {response.status}"
                        )
                    self._mark_stream_connected()
                    buffer: list[str] = []
                    while not self._stop.is_set():
                        raw_line = response.readline()
                        if not raw_line:
                            if self._stop.is_set():
                                return
                            raise AgentRuntimeError("Agent SSE 事件流意外结束")
                        if self._stop.is_set():
                            return
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line:
                            if line.startswith("data: "):
                                buffer.append(line[6:])
                            continue
                        if buffer:
                            self._mark_stream_event()
                            self._consume("".join(buffer))
                            buffer = []
                finally:
                    with self._stream_lock:
                        if self._stream_connection is connection:
                            self._stream_connection = None
                    connection.close()
            except Exception:
                if not self._stop.is_set():
                    self._mark_stream_failure()
            if not self._stop.is_set():
                self._stop.wait(self.RECONNECT_DELAY_SECONDS)

    def _consume_websocket(self) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise AgentRuntimeError(
                "DSH WebSocket 事件桥缺少 websockets；请安装 server 依赖"
            ) from exc

        uri = f"ws://{self.client.host}:{self.client.port}/api/events.mux"
        websocket = connect(
            uri,
            proxy=None,
            open_timeout=5,
            close_timeout=1,
            ping_interval=20,
            ping_timeout=20,
        )
        with self._stream_lock:
            if self._stop.is_set():
                websocket.close()
                return
            self._stream_connection = websocket
        self._mark_stream_connected()
        try:
            while not self._stop.is_set():
                try:
                    raw = websocket.recv(timeout=1.0)
                except TimeoutError:
                    continue
                if raw is None:
                    if self._stop.is_set():
                        return
                    raise AgentRuntimeError("Agent WebSocket 事件流意外结束")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                self._mark_stream_event()
                self._consume(str(raw))
        finally:
            with self._stream_lock:
                if self._stream_connection is websocket:
                    self._stream_connection = None
            websocket.close()

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
                    "call_id": payload.get("callId"),
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
