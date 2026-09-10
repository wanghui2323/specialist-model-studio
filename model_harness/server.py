from __future__ import annotations

import asyncio
import errno
import fcntl
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote

from . import __version__

try:  # optional server dependency
    from fastapi import Body, FastAPI, Header, HTTPException, Query
    from fastapi.responses import (
        FileResponse,
        JSONResponse,
        RedirectResponse,
        Response,
        StreamingResponse,
    )
    from fastapi.staticfiles import StaticFiles
    from starlette.background import BackgroundTask
    from starlette.requests import Request
except ImportError as exc:  # pragma: no cover
    _SERVER_IMPORT_ERROR: ImportError | None = exc
    Request = Any  # type: ignore[misc,assignment]
else:
    _SERVER_IMPORT_ERROR = None

from .agent_bridge import (
    AgentRuntimeError,
    agent_public_projection,
)
from .conversation_stream import (
    ConversationStreamCapacityError,
    TaskConversationStreamBroker,
    parse_stream_cursor,
)
from .contracts import (
    ApprovalDecisionIntegrityError,
    ContractRevisionConflictError,
    ContractRevisionIntegrityError,
)
from .csv_targeting import recommend_csv_target_column
from .multi_agent import (
    ComposerModeUnsupportedError,
    ComposerRequestConflictError,
    ComposerRequestTerminalError,
    ComposerSubmissionError,
    HumanCheckpointAnswerError,
    HumanCheckpointConflictError,
    build_dsh_multi_agent_runtime,
)
from .data_adapters import DataAdapterRegistry
from .errors import ContractError, HarnessError
from .huggingface_catalog import HuggingFaceCatalogError
from .inference_inputs import InferenceInputError, MAX_INFERENCE_INPUT_BYTES
from .model_assets import ModelAssetError
from .model_source_store import ModelSourceIntegrityError, StaleBindingIntentError
from .model_sources import (
    ModelSourceIncompleteError,
    ModelSourceUpstreamError,
    ModelSourceValidationError,
    parse_model_source_reference,
)
from .plugins import PluginRegistry
from .feasibility_store import (
    FeasibilityStoreIntegrityError,
    StaleFeasibilityReferenceError,
)
from .resource_feasibility import ResourceFeasibilityError
from .service import RunService
from .sample_inference import SampleInferenceBlocked
from .source_identity import resolve_runtime_source_root
from .staged_assets import StagedAssetRejected
from .state import TERMINAL_STATUSES
from .training_plans import (
    StaleTrainingPlanError,
    TrainingPlanApprovalRequired,
    TrainingPlanIntegrityError,
)
from .task_specs import FAMILY_DETAILS
from .workspace import TrainingWorkspace
from .workspace import ConversationConflictError


_CONVERSATION_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")


def _conversation_task_id(create_request_id: str) -> str:
    selected = create_request_id.strip()
    if not _CONVERSATION_REQUEST_ID.fullmatch(selected):
        raise ValueError("create_request_id 格式非法")
    digest = hashlib.sha256(
        b"specialist-model-studio:conversation-task:v1\0"
        + selected.encode("utf-8")
    ).hexdigest()
    return f"task-{digest[:32]}"


API_VERSION = "1.0.0-rc.1"
FEATURE_TRACK = "v1.0-conversation-native"
RELEASE_STATUS = "unreleased_rc"


def _resolve_source_revision(source_root: Path) -> str | None:
    """Return the exact checkout commit when this runtime comes from Git."""

    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={source_root}",
                "-C",
                str(source_root),
                "rev-parse",
                "--verify",
                "HEAD",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    candidate = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(candidate) != 40:
        return None
    if any(character not in "0123456789abcdef" for character in candidate):
        return None
    return candidate


def _resolve_source_dirty(source_root: Path) -> bool | None:
    """Report whether the Git checkout differs from its recorded revision."""

    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={source_root}",
                "-C",
                str(source_root),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


class RunsWorkspaceLeaseError(RuntimeError):
    """Raised when another backend already owns the runs workspace."""


_RUNS_LEASE_GUARD = threading.Lock()
_ACTIVE_RUNS_LEASES: set[Path] = set()


class _RunsWorkspaceLease:
    """Process-local and OS-level single-writer lease for one runs directory."""

    FILENAME = ".specialist-model-studio.writer.lock"

    def __init__(self, runs_dir: str | Path) -> None:
        self.runs_dir = Path(runs_dir).expanduser().resolve()
        self.path = self.runs_dir / self.FILENAME
        self._handle: BinaryIO | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        with _RUNS_LEASE_GUARD:
            if self._handle is not None or self.path in _ACTIVE_RUNS_LEASES:
                raise RunsWorkspaceLeaseError(
                    f"runs workspace already has an active writer in this process: "
                    f"{self.runs_dir}"
                )
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                raise RunsWorkspaceLeaseError(
                    f"runs workspace already has an active writer: {self.runs_dir}"
                ) from exc
            self._handle = handle
            _ACTIVE_RUNS_LEASES.add(self.path)

    def release(self) -> None:
        with _RUNS_LEASE_GUARD:
            handle = self._handle
            if handle is None:
                return
            self._handle = None
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                try:
                    handle.close()
                finally:
                    _ACTIVE_RUNS_LEASES.discard(self.path)


def create_app(
    runs_dir: str | Path = "runs",
    max_workers: int = 1,
    workspace_dir: str | Path | None = None,
    conversation_url: str | None = None,
) -> Any:
    if _SERVER_IMPORT_ERROR is not None:  # pragma: no cover - optional extra
        raise RuntimeError(
            "HTTP server dependencies are missing; install specialist-model-studio[server]"
        ) from _SERVER_IMPORT_ERROR

    resolved_runs_dir = Path(runs_dir).expanduser().resolve()
    # Dynamic task-owned versions must never leak across app/workspace
    # instances through the process-wide default registries.
    registry = PluginRegistry(include_builtins=True)
    registry.discover()
    data_adapter_registry = DataAdapterRegistry(include_builtins=True)
    data_adapter_registry.discover()
    service = RunService(
        runs_dir=resolved_runs_dir,
        max_workers=max_workers,
        registry=registry,
    )
    workspace = TrainingWorkspace(
        workspace_dir or (resolved_runs_dir / "_workspace"),
        service,
        data_adapters=data_adapter_registry,
    )
    web_dir = Path(__file__).parent / "web"
    resolved_conversation_url = (
        conversation_url
        or os.environ.get("MODEL_HARNESS_CONVERSATION_URL")
        or "http://127.0.0.1:3080"
    ).rstrip("/")
    source_root = resolve_runtime_source_root(
        module_file=Path(__file__),
        prefix=Path(sys.prefix),
    )
    source_revision = _resolve_source_revision(source_root)
    source_dirty = _resolve_source_dirty(source_root)
    conversations = build_dsh_multi_agent_runtime(
        workspace_root=workspace.root,
        dsh_base_url=resolved_conversation_url,
        cwd=source_root,
        background_actions_provider=workspace.task_background_actions,
        background_actions_canceller=workspace.cancel_task_background_actions,
    )
    conversation_streams = TaskConversationStreamBroker(conversations)
    runs_workspace_lease = _RunsWorkspaceLease(resolved_runs_dir)

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        lease_acquired = False
        conversations_started = False
        try:
            runs_workspace_lease.acquire()
            lease_acquired = True
            conversation_streams.start()
            conversations.start()
            conversations_started = True
            yield
        finally:
            try:
                await conversation_streams.close()
            finally:
                try:
                    if conversations_started:
                        conversations.stop()
                finally:
                    try:
                        workspace.close()
                    finally:
                        try:
                            service.close()
                        finally:
                            if lease_acquired:
                                runs_workspace_lease.release()

    app = FastAPI(
        title="Specialist Model Studio",
        version=API_VERSION,
        description="Conversation-first product runtime for auditable specialist-model training.",
        lifespan=lifespan,
    )
    configured_agent_bridge_token = os.environ.get(
        "MODEL_HARNESS_AGENT_BRIDGE_TOKEN", ""
    ).strip()

    def require_agent_bridge_approval_token(supplied: str | None) -> str:
        candidate = str(supplied or "")
        if (
            not configured_agent_bridge_token
            or not candidate
            or not hmac.compare_digest(candidate, configured_agent_bridge_token)
        ):
            raise HTTPException(
                status_code=403,
                detail="a verified agent-bridge approval token is required",
            )
        return hashlib.sha256(
            configured_agent_bridge_token.encode("utf-8")
        ).hexdigest()
    app.state.run_service = service
    app.state.training_workspace = workspace
    app.state.conversation_runtime = conversations
    app.state.conversation_streams = conversation_streams
    app.state.runs_workspace_lease = runs_workspace_lease
    app.mount("/app/static", StaticFiles(directory=web_dir), name="app-static")

    @app.middleware("http")
    async def project_remote_agent_response(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        projection = request.headers.get("x-model-harness-projection", "").lower()
        if projection not in {"agent", "agent-v1"}:
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        chunks = [bytes(chunk) async for chunk in response.body_iterator]
        body = b"".join(chunks)
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                background=response.background,
            )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        return JSONResponse(
            status_code=response.status_code,
            content=agent_public_projection(value),
            headers=headers,
            background=response.background,
        )

    @app.get("/model-assets/huggingface/capability")
    def huggingface_capability() -> dict[str, Any]:
        return workspace.huggingface_catalog.capability()

    @app.get("/model-assets/huggingface/search")
    def search_huggingface_models(
        q: str = Query(..., min_length=1, max_length=160),
        pipeline_tag: str | None = Query(default=None),
        limit: int = Query(default=10, ge=1, le=20),
        x_hf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            return {
                "provider": "huggingface",
                "models": workspace.search_huggingface_models(
                    q,
                    pipeline_tag=pipeline_tag,
                    limit=limit,
                    token=x_hf_token,
                ),
            }
        except HuggingFaceCatalogError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/model-assets/huggingface/card")
    def get_huggingface_model_card(
        repo_id: str = Query(...),
        revision: str | None = Query(default=None),
        x_hf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            return {
                "model": workspace.huggingface_model_card(
                    repo_id,
                    revision=revision,
                    token=x_hf_token,
                )
            }
        except HuggingFaceCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/model-assets/huggingface")
    async def attach_huggingface_model_asset(
        task_id: str,
        body: dict[str, Any] = Body(...),
        x_hf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            return workspace.attach_huggingface_model(
                task_id,
                repo_id=str(body.get("repo_id", "")),
                commit=str(body.get("commit", "")),
                approval_confirmed=body.get("approval_confirmed") is True,
                token=x_hf_token,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, HuggingFaceCatalogError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (HarnessError, ModelAssetError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-assets/current/verify")
    def verify_task_model_asset(task_id: str) -> dict[str, Any]:
        try:
            return workspace.verify_task_model_asset(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ModelAssetError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/model-sources/providers")
    def model_source_providers() -> dict[str, Any]:
        return {"providers": workspace.model_source_provider_capabilities()}

    @app.post("/tasks/{task_id}/model-source-searches")
    async def search_model_sources(
        task_id: str,
        body: dict[str, Any] = Body(...),
        x_hf_token: str | None = Header(default=None),
        x_github_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        raw_providers = body.get("providers")
        providers = (
            [str(item) for item in raw_providers]
            if isinstance(raw_providers, list)
            else None
        )
        try:
            return await asyncio.to_thread(
                workspace.search_model_sources,
                task_id,
                query=(str(body["query"]) if body.get("query") is not None else None),
                providers=providers,
                limit_per_provider=body.get("limit_per_provider", 4),
                base_spec_revision=body.get("base_spec_revision"),
                tokens={"huggingface": x_hf_token, "github": x_github_token},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ModelSourceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModelSourceUpstreamError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-source-searches")
    def list_model_source_searches(task_id: str) -> dict[str, Any]:
        try:
            return {
                "searches": workspace.list_model_source_searches(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-source-searches/{search_id}")
    def get_model_source_search(
        task_id: str,
        search_id: str,
    ) -> dict[str, Any]:
        try:
            return {
                "search": workspace.get_model_source_search(task_id, search_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/model-source-selections")
    async def confirm_model_source_selection(
        task_id: str,
        body: dict[str, Any] = Body(...),
        x_hf_token: str | None = Header(default=None),
        x_github_token: str | None = Header(default=None),
    ) -> JSONResponse:
        try:
            result = await asyncio.to_thread(
                workspace.confirm_model_source_candidate,
                task_id,
                search_id=str(body.get("search_id", "")),
                candidate_id=str(body.get("candidate_id", "")),
                approval_confirmed=body.get("approval_confirmed") is True,
                base_spec_revision=body.get("base_spec_revision"),
                tokens={"huggingface": x_hf_token, "github": x_github_token},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ModelSourceIncompleteError, ModelSourceUpstreamError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ModelSourceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post("/tasks/{task_id}/model-source-resolutions")
    async def create_model_source_resolution(
        task_id: str,
        body: dict[str, Any] = Body(...),
        x_hf_token: str | None = Header(default=None),
        x_github_token: str | None = Header(default=None),
    ) -> JSONResponse:
        provider = str(body.get("provider", "")).strip().lower()
        source_reference = body.get("source_reference")
        if source_reference is not None:
            try:
                parsed_reference = parse_model_source_reference(
                    str(source_reference), provider_hint=provider or None
                )
                provider = parsed_reference["provider"]
            except ModelSourceValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        token = x_github_token if provider == "github" else x_hf_token
        try:
            if source_reference is not None:
                result = workspace.create_model_source_resolution_from_reference(
                    task_id,
                    source_reference=str(source_reference),
                    provider_hint=provider,
                    requested_revision=(
                        str(body["requested_revision"])
                        if body.get("requested_revision") is not None
                        else None
                    ),
                    base_spec_revision=body.get("base_spec_revision"),
                    token=token,
                )
            else:
                result = workspace.create_model_source_resolution(
                    task_id,
                    provider=provider,
                    repository=str(body.get("repository", "")),
                    requested_revision=(
                        str(body["requested_revision"])
                        if body.get("requested_revision") is not None
                        else None
                    ),
                    base_spec_revision=body.get("base_spec_revision"),
                    token=token,
                )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ModelSourceIncompleteError, ModelSourceUpstreamError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ModelSourceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/model-source-resolutions")
    def list_model_source_resolutions(task_id: str) -> dict[str, Any]:
        try:
            return {
                "resolutions": workspace.list_model_source_resolutions(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-source-resolutions/{resolution_id}")
    def get_model_source_resolution(
        task_id: str,
        resolution_id: str,
    ) -> dict[str, Any]:
        try:
            return {
                "resolution": workspace.get_model_source_resolution(
                    task_id, resolution_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/tasks/{task_id}/model-source-resolutions/{resolution_id}/bind"
    )
    async def bind_model_source(
        task_id: str,
        resolution_id: str,
        body: dict[str, Any] = Body(...),
        x_hf_token: str | None = Header(default=None),
        x_github_token: str | None = Header(default=None),
    ) -> JSONResponse:
        try:
            resolution = workspace.get_model_source_resolution(
                task_id, resolution_id
            )
            token = (
                x_github_token
                if resolution.get("provider") == "github"
                else x_hf_token
            )
            result = workspace.queue_model_source_binding(
                task_id,
                resolution_id,
                approval_confirmed=body.get("approval_confirmed") is True,
                expected_resolved_commit=str(
                    body.get("expected_resolved_commit", "")
                ),
                base_spec_revision=body.get("base_spec_revision"),
                token=token,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ModelSourceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ModelSourceIntegrityError, StaleBindingIntentError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        attempt_id = str(result["attempt"]["attempt_id"])
        return JSONResponse(
            status_code=202,
            content={
                "binding_attempt": result,
                "poll_url": (
                    f"/tasks/{task_id}/model-binding-attempts/{attempt_id}"
                ),
            },
        )

    @app.get("/tasks/{task_id}/model-binding-attempts")
    def list_model_binding_attempts(task_id: str) -> dict[str, Any]:
        try:
            return {
                "binding_attempts": workspace.list_model_binding_attempts(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-binding-attempts/current")
    def current_model_binding_attempt(task_id: str) -> dict[str, Any]:
        try:
            attempt = workspace.current_model_binding_attempt(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if attempt is None:
            raise HTTPException(status_code=404, detail="model binding attempt not found")
        return {"binding_attempt": attempt}

    @app.get("/tasks/{task_id}/model-binding-attempts/{attempt_id}")
    def get_model_binding_attempt(
        task_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        try:
            return {
                "binding_attempt": workspace.get_model_binding_attempt(
                    task_id, attempt_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/model-binding-attempts/{attempt_id}/cancel")
    def cancel_model_binding_attempt(
        task_id: str,
        attempt_id: str,
        body: dict[str, Any] = Body(default={}),
    ) -> dict[str, Any]:
        try:
            return workspace.cancel_model_binding_attempt(
                task_id,
                attempt_id,
                reason=str(
                    body.get("reason")
                    or "用户取消模型来源绑定与静态分析"
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-bindings")
    def list_model_bindings(task_id: str) -> dict[str, Any]:
        try:
            return {"bindings": workspace.list_model_bindings(task_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/blockers")
    def list_task_blockers(
        task_id: str,
        active_only: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            return {
                "blockers": workspace.list_blockers(
                    task_id, active_only=active_only
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/blockers/{blocker_id}")
    def get_task_blocker(task_id: str, blocker_id: str) -> dict[str, Any]:
        try:
            return {"blocker": workspace.get_blocker(task_id, blocker_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-bindings/current")
    def current_model_binding(task_id: str) -> dict[str, Any]:
        try:
            binding = workspace.current_model_binding(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if binding is None:
            raise HTTPException(status_code=404, detail="current model binding not found")
        return {"binding": binding}

    @app.get("/tasks/{task_id}/model-bindings/{binding_revision_id}")
    def get_model_binding(
        task_id: str,
        binding_revision_id: str,
    ) -> dict[str, Any]:
        try:
            return {
                "binding": workspace.get_model_binding(
                    task_id, binding_revision_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/repository-analyses/{analysis_id}")
    def get_repository_analysis(
        task_id: str,
        analysis_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.get_repository_analysis_envelope(task_id, analysis_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/tasks/{task_id}/repository-analyses/{analysis_id}/evidence"
    )
    def get_repository_analysis_evidence(
        task_id: str,
        analysis_id: str,
        path: str = Query(...),
        line: int = Query(..., ge=1),
        context_lines: int = Query(default=3, ge=0, le=8),
    ) -> dict[str, Any]:
        try:
            return {
                "evidence": workspace.get_repository_evidence_excerpt(
                    task_id,
                    analysis_id,
                    path=path,
                    line=line,
                    context_lines=context_lines,
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/tasks/{task_id}/repository-analyses/{analysis_id}/manual-mappings"
    )
    def apply_repository_manual_mapping(
        task_id: str,
        analysis_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        try:
            result = workspace.apply_repository_manual_mapping(
                task_id,
                analysis_id,
                training_entrypoint=str(body.get("training_entrypoint") or ""),
                dataset_argument=(
                    str(body["dataset_argument"])
                    if body.get("dataset_argument") is not None
                    else None
                ),
                inference_entrypoint=(
                    str(body["inference_entrypoint"])
                    if body.get("inference_entrypoint") is not None
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, ModelSourceIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post("/tasks/{task_id}/training-plans")
    def create_training_plan(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        try:
            result = workspace.create_training_plan(
                task_id,
                base_spec_revision=body.get("base_spec_revision"),
                entrypoint_path=(
                    str(body["entrypoint_path"])
                    if body.get("entrypoint_path") is not None
                    else None
                ),
                hyperparameters=(
                    dict(body["hyperparameters"])
                    if isinstance(body.get("hyperparameters"), dict)
                    else None
                ),
                resource_budget=(
                    dict(body["resource_budget"])
                    if isinstance(body.get("resource_budget"), dict)
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TrainingPlanIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content={"training_plan": result})

    @app.get("/tasks/{task_id}/training-plans/current")
    def current_training_plan(task_id: str) -> dict[str, Any]:
        try:
            result = workspace.current_training_plan(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, TrainingPlanIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="current training plan not found")
        return {"training_plan": result}

    @app.get("/tasks/{task_id}/training-plans/{revision_id}")
    def get_training_plan(task_id: str, revision_id: str) -> dict[str, Any]:
        try:
            return {
                "training_plan": workspace.get_training_plan(
                    task_id, revision_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, TrainingPlanIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/training-plans/{revision_id}/revisions")
    def revise_training_plan(
        task_id: str,
        revision_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        raw_hyperparameters = body.get("hyperparameters")
        raw_budget = body.get("resource_budget")
        if raw_hyperparameters is not None and not isinstance(raw_hyperparameters, dict):
            raise HTTPException(status_code=422, detail="hyperparameters must be an object")
        if raw_budget is not None and not isinstance(raw_budget, dict):
            raise HTTPException(status_code=422, detail="resource_budget must be an object")
        try:
            result = workspace.revise_training_plan(
                task_id,
                revision_id,
                expected_parent_sha256=str(
                    body.get("expected_parent_sha256", "")
                ),
                base_spec_revision=body.get("base_spec_revision"),
                entrypoint_path=(
                    str(body["entrypoint_path"])
                    if body.get("entrypoint_path") is not None
                    else None
                ),
                hyperparameters=(
                    dict(raw_hyperparameters)
                    if isinstance(raw_hyperparameters, dict)
                    else None
                ),
                resource_budget=(
                    dict(raw_budget) if isinstance(raw_budget, dict) else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            StaleTrainingPlanError,
            TrainingPlanIntegrityError,
            HarnessError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content={"training_plan": result})

    @app.post("/tasks/{task_id}/training-plans/{revision_id}/decisions")
    def decide_training_plan(
        task_id: str,
        revision_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            result = workspace.decide_training_plan(
                task_id,
                revision_id,
                expected_plan_sha256=str(body.get("expected_plan_sha256", "")),
                decision=str(body.get("decision", "")),
                reason=str(body.get("reason", "")),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            StaleTrainingPlanError,
            TrainingPlanApprovalRequired,
            TrainingPlanIntegrityError,
            HarnessError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"training_plan": result}

    @app.get("/tasks/{task_id}/resource-feasibility")
    def current_resource_feasibility(task_id: str) -> dict[str, Any]:
        try:
            return {
                "resource_feasibility": workspace.current_resource_feasibility(
                    task_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ContractError,
            FeasibilityStoreIntegrityError,
            ResourceFeasibilityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/resource-probes/{probe_id}")
    def get_resource_probe(task_id: str, probe_id: str) -> dict[str, Any]:
        try:
            return {"resource_probe": workspace.get_resource_probe(task_id, probe_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ContractError,
            FeasibilityStoreIntegrityError,
            ResourceFeasibilityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/environment-locks/{lock_id}")
    def get_environment_lock(task_id: str, lock_id: str) -> dict[str, Any]:
        try:
            return {
                "environment_lock": workspace.get_environment_lock(
                    task_id, lock_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ContractError,
            FeasibilityStoreIntegrityError,
            ResourceFeasibilityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/resource-fit-reports/{report_id}")
    def get_resource_fit_report(task_id: str, report_id: str) -> dict[str, Any]:
        try:
            return {
                "resource_fit_report": workspace.get_resource_fit_report(
                    task_id, report_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ContractError,
            FeasibilityStoreIntegrityError,
            ResourceFeasibilityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/resource-feasibility-checks")
    def check_resource_feasibility(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        raw_packages = body.get("packages")
        if raw_packages is not None and not isinstance(raw_packages, list):
            raise HTTPException(status_code=422, detail="packages must be an array")
        if isinstance(raw_packages, list) and not all(
            isinstance(item, dict) for item in raw_packages
        ):
            raise HTTPException(
                status_code=422,
                detail="packages entries must be objects",
            )
        try:
            result = workspace.check_resource_feasibility(
                task_id,
                training_plan_revision_id=str(
                    body.get("training_plan_revision_id", "")
                ),
                expected_plan_sha256=str(body.get("expected_plan_sha256", "")),
                base_image_digest=(
                    str(body["base_image_digest"])
                    if body.get("base_image_digest") is not None
                    else None
                ),
                packages=(
                    [dict(item) for item in raw_packages]
                    if isinstance(raw_packages, list)
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            FeasibilityStoreIntegrityError,
            StaleFeasibilityReferenceError,
            ResourceFeasibilityError,
            StaleTrainingPlanError,
            TrainingPlanApprovalRequired,
            TrainingPlanIntegrityError,
            HarnessError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(
            status_code=201, content={"resource_feasibility": result}
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": API_VERSION,
            "package_version": __version__,
            "feature_track": FEATURE_TRACK,
            "release_status": RELEASE_STATUS,
            "scope": "backend",
            "recovered_runs": service.recovered_runs,
            "primary_experience": "conversation",
            "conversation_url": "/app",
            "workbench_url": "/app",
            "runtime_url": "/runtime",
            "agent_required": False,
        }

    @app.get("/runtime")
    def runtime() -> dict[str, Any]:
        return {
            "package_version": __version__,
            "feature_track": FEATURE_TRACK,
            "release_status": RELEASE_STATUS,
            "primary_experience": "conversation",
            "conversation_url": "/app",
            "workbench_url": "/app",
            "source_execution_policy": (
                "static_analysis_only_without_verified_isolation"
            ),
            "byom_execution_available": False,
            "supported_protocol_end": "resource_feasibility",
            "registered_recipe_training_available": True,
            "runtime_identity": {
                "source_root": str(source_root),
                "source_revision": source_revision,
                "source_dirty": source_dirty,
                "runs_dir": str(resolved_runs_dir),
                "workspace_dir": str(workspace.root.resolve()),
                "conversation_origin": resolved_conversation_url,
            },
            "agent": conversations.runtime_status(),
        }

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app")

    @app.get("/app", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/agent/runtime")
    def agent_runtime() -> dict[str, Any]:
        return conversations.runtime_status()

    @app.get("/conversations")
    def list_conversations() -> dict[str, Any]:
        return {"conversations": workspace.list_conversations()}

    @app.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict[str, Any]:
        try:
            conversation = workspace.get_conversation(conversation_id)
            task = (
                workspace.get_task(str(conversation["task_id"]))
                if conversation.get("task_id")
                else None
            )
            return {"conversation": conversation, "task": task}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConversationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/conversations")
    async def create_conversation(body: dict[str, Any] = Body(...)) -> JSONResponse:
        create_request_id = body.get("create_request_id")
        if not isinstance(create_request_id, str):
            raise HTTPException(
                status_code=422,
                detail="create_request_id is required",
            )
        try:
            conversation_id = _conversation_task_id(create_request_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        initial_message = body.get("initial_message")
        message_request_id = body.get("message_request_id")
        if initial_message is not None:
            if not isinstance(initial_message, str) or not initial_message.strip():
                raise HTTPException(
                    status_code=422,
                    detail="initial_message must be non-empty text",
                )
            if not isinstance(message_request_id, str):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "message_request_id is required when initial_message is set"
                    ),
                )
            message_request_id = message_request_id.strip()
            if not _CONVERSATION_REQUEST_ID.fullmatch(message_request_id):
                raise HTTPException(
                    status_code=422,
                    detail="message_request_id 格式非法",
                )
        try:
            conversation, created = workspace.create_conversation(
                conversation_id=conversation_id,
                create_request_id=create_request_id,
                title=str(body.get("title", "")).strip() or "新对话",
            )
        except ConversationConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "conversation_creation_request_conflict",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                },
            ) from exc
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if initial_message is None:
            return JSONResponse(
                status_code=201 if created else 200,
                content={
                    "conversation": conversation,
                    "submission": None,
                    "created": created,
                },
            )
        assert isinstance(initial_message, str)
        assert isinstance(message_request_id, str)
        try:
            submission = conversations.submit_message(
                conversation_id,
                str(conversation.get("title") or "新对话"),
                initial_message,
                composer_mode="queue_after_turn",
                request_id=message_request_id,
                actor="user",
            )
        except ComposerRequestConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_conflict",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                    "request_id": message_request_id,
                },
            ) from exc
        except ComposerRequestTerminalError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_terminal",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except ComposerSubmissionError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "composer_submission_failed",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except (ValueError, ComposerModeUnsupportedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "agent_runtime_unavailable",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                },
            ) from exc
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "conversation": workspace.get_conversation(conversation_id),
                "submission": submission,
                "created": created,
            },
        )

    @app.get("/conversations/{conversation_id}/conversation")
    async def conversation_events(conversation_id: str) -> dict[str, Any]:
        try:
            workspace.get_conversation(conversation_id)
            return {
                "conversation": await conversation_streams.conversation(
                    conversation_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConversationStreamCapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/conversations/{conversation_id}/conversation/stream")
    async def conversation_event_stream(
        request: Request,
        conversation_id: str,
        after_seq: int | None = Query(default=None, ge=0),
        projector_revision: str | None = Query(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            workspace.get_conversation(conversation_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if last_event_id is not None:
            try:
                parse_stream_cursor(last_event_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        resume_cursor = after_seq if last_event_id is None else None
        expected_revision = (
            projector_revision.strip() if projector_revision is not None else None
        )
        if expected_revision == "":
            expected_revision = None
        if expected_revision is not None and len(expected_revision) > 64:
            raise HTTPException(
                status_code=422,
                detail="projector_revision is too long",
            )
        try:
            runtime_status = await asyncio.to_thread(conversations.runtime_status)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if (
            not isinstance(runtime_status, dict)
            or runtime_status.get("available") is not True
        ):
            raise HTTPException(
                status_code=503,
                detail="DeepSeek Harness multi-agent runtime is unavailable",
            )
        runtime_revision = runtime_status.get("conversation_projector_revision")
        runtime_revision = (
            runtime_revision.strip()
            if isinstance(runtime_revision, str) and runtime_revision.strip()
            else None
        )
        try:
            stream_reservation = conversation_streams.reserve(conversation_id)
        except ConversationStreamCapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        async def stream_frames() -> Any:
            stream = conversation_streams.stream(
                conversation_id,
                after_seq=resume_cursor,
                last_event_id=last_event_id,
                expected_projector_revision=expected_revision,
                runtime_projector_revision=runtime_revision,
                reservation=stream_reservation,
            )
            try:
                async for frame in stream:
                    if await request.is_disconnected():
                        break
                    yield frame
            finally:
                await stream.aclose()

        handed_off = False
        try:
            response = StreamingResponse(
                stream_frames(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
                background=BackgroundTask(stream_reservation.release),
            )
            handed_off = True
            return response
        finally:
            if not handed_off:
                stream_reservation.release()

    @app.post("/conversations/{conversation_id}/messages")
    async def conversation_message(
        conversation_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=422, detail="message must be non-empty text")
        composer_mode = body.get("mode", "queue_after_turn")
        if composer_mode not in {
            "queue_after_turn",
            "intervene_current",
            "stop_and_replace",
        }:
            raise HTTPException(status_code=422, detail="unsupported composer mode")
        request_id = body.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise HTTPException(status_code=422, detail="request_id must be text")
        try:
            record = workspace.get_conversation(conversation_id)
            submission = conversations.submit_message(
                conversation_id,
                str(record.get("title") or "新对话"),
                message,
                composer_mode=composer_mode,
                request_id=request_id,
                actor="user",
                **({"checkpoint_rpc_id": body["checkpoint_rpc_id"]}
                   if "checkpoint_rpc_id" in body else {}),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HumanCheckpointConflictError as exc:
            raise HTTPException(status_code=409, detail={"code": "checkpoint_changed", "message": str(exc)}) from exc
        except ComposerModeUnsupportedError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_mode_not_available",
                    "message": str(exc),
                    "requested_mode": composer_mode,
                    "supported_modes": ["queue_after_turn"],
                },
            ) from exc
        except ComposerRequestConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_conflict",
                    "message": str(exc),
                    "request_id": request_id,
                },
            ) from exc
        except ComposerRequestTerminalError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_terminal",
                    "message": str(exc),
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except ComposerSubmissionError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "composer_submission_failed",
                    "message": str(exc),
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content=submission)

    @app.post("/conversations/{conversation_id}/cancel")
    async def cancel_conversation(
        conversation_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, Any]:
        selected = body or {}
        reason = selected.get("reason", "User requested stop")
        if not isinstance(reason, str):
            raise HTTPException(status_code=422, detail="reason must be text")
        if selected.get("actor", "user") != "user" or selected.get(
            "kind", "user_requested"
        ) != "user_requested":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "cancel_actor_spoofing_rejected",
                    "message": (
                        "public conversation cancellation is always attributed "
                        "to the user"
                    ),
                },
            )
        try:
            workspace.get_conversation(conversation_id)
            return conversations.cancel(
                conversation_id,
                actor="user",
                reason=reason,
                cancellation_kind="user_requested",
                scope="conversation_turn",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/conversations/{conversation_id}/questions/{rpc_id}")
    async def answer_conversation_question(
        conversation_id: str,
        rpc_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        answers = body.get("answers")
        if not isinstance(answers, list):
            raise HTTPException(status_code=422, detail="answers must be a list")
        try:
            workspace.get_conversation(conversation_id)
            conversations.answer_question(conversation_id, rpc_id, answers)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HumanCheckpointAnswerError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.post("/conversations/{conversation_id}/promote")
    async def promote_conversation(
        conversation_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        request_id = body.get("request_id")
        if not isinstance(request_id, str):
            raise HTTPException(status_code=422, detail="request_id is required")
        try:
            task, idempotent_replay = workspace.promote_conversation(
                conversation_id,
                request_id=request_id,
                name=str(body.get("name", "")),
                business_goal=str(body.get("business_goal", "")),
                capability_request=(
                    body.get("capability_request")
                    if isinstance(body.get("capability_request"), dict)
                    else {}
                ),
                recipe_id=str(body.get("recipe_id", "")).strip() or None,
            )
            return {
                "conversation": workspace.get_conversation(conversation_id),
                "task": task,
                "promoted": True,
                "idempotent_replay": idempotent_replay,
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConversationConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "conversation_promotion_conflict",
                    "message": str(exc),
                    "conversation_id": conversation_id,
                },
            ) from exc
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/conversation")
    async def task_conversation(task_id: str) -> dict[str, Any]:
        try:
            workspace.get_task(task_id)
            return {
                "conversation": await conversation_streams.conversation(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConversationStreamCapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/conversation/stream")
    async def task_conversation_stream(
        request: Request,
        task_id: str,
        after_seq: int | None = Query(default=None, ge=0),
        projector_revision: str | None = Query(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            workspace.get_task(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if last_event_id is not None:
            try:
                parse_stream_cursor(last_event_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=str(exc),
                ) from exc
        # EventSource automatically advances Last-Event-ID on reconnect while
        # the compatibility after_seq remains fixed in the URL. The header is
        # therefore authoritative whenever both are present.
        resume_cursor = after_seq if last_event_id is None else None

        expected_revision = (
            projector_revision.strip() if projector_revision is not None else None
        )
        if expected_revision == "":
            expected_revision = None
        if expected_revision is not None and len(expected_revision) > 64:
            raise HTTPException(
                status_code=422,
                detail="projector_revision is too long",
            )
        try:
            runtime_status = await asyncio.to_thread(conversations.runtime_status)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if (
            not isinstance(runtime_status, dict)
            or runtime_status.get("available") is not True
        ):
            raise HTTPException(
                status_code=503,
                detail="DeepSeek Harness multi-agent runtime is unavailable",
            )
        runtime_revision = runtime_status.get("conversation_projector_revision")
        runtime_revision = (
            runtime_revision.strip()
            if isinstance(runtime_revision, str) and runtime_revision.strip()
            else None
        )
        # Reserve only after the awaited availability probe. From here to the
        # response hand-off there is no await, so the task hub cannot be
        # evicted by a competing request between preflight and subscription.
        try:
            stream_reservation = conversation_streams.reserve(task_id)
        except ConversationStreamCapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        async def stream_frames() -> Any:
            stream = conversation_streams.stream(
                task_id,
                after_seq=resume_cursor,
                last_event_id=last_event_id,
                expected_projector_revision=expected_revision,
                runtime_projector_revision=runtime_revision,
                reservation=stream_reservation,
            )
            try:
                async for frame in stream:
                    if await request.is_disconnected():
                        break
                    yield frame
            finally:
                await stream.aclose()

        handed_off = False
        try:
            response = StreamingResponse(
                stream_frames(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
                background=BackgroundTask(stream_reservation.release),
            )
            handed_off = True
            return response
        finally:
            if not handed_off:
                stream_reservation.release()

    @app.get("/tasks/{task_id}/conversation/events/{event_id}")
    def task_conversation_event_result(
        task_id: str,
        event_id: str,
        projector_revision: str = Query(...),
    ) -> dict[str, Any]:
        try:
            workspace.get_task(task_id)
            return conversations.conversation_event_result(
                task_id,
                event_id,
                projector_revision=projector_revision,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/conversation/messages")
    async def task_conversation_message(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=422, detail="message must be non-empty text")
        composer_mode = body.get("mode", "queue_after_turn")
        if composer_mode not in {
            "queue_after_turn",
            "intervene_current",
            "stop_and_replace",
        }:
            raise HTTPException(status_code=422, detail="unsupported composer mode")
        request_id = body.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise HTTPException(status_code=422, detail="request_id must be text")
        try:
            task = workspace.get_task(task_id)
            submission = conversations.submit_message(
                task_id,
                task["name"],
                message,
                composer_mode=composer_mode,
                request_id=request_id,
                actor="user",
                **({"checkpoint_rpc_id": body["checkpoint_rpc_id"]}
                   if "checkpoint_rpc_id" in body else {}),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HumanCheckpointConflictError as exc:
            raise HTTPException(status_code=409, detail={"code": "checkpoint_changed", "message": str(exc)}) from exc
        except ComposerModeUnsupportedError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_mode_not_available",
                    "message": str(exc),
                    "requested_mode": composer_mode,
                    "supported_modes": ["queue_after_turn"],
                },
            ) from exc
        except ComposerRequestConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_conflict",
                    "message": str(exc),
                    "request_id": request_id,
                },
            ) from exc
        except ComposerRequestTerminalError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "composer_request_terminal",
                    "message": str(exc),
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except ComposerSubmissionError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "composer_submission_failed",
                    "message": str(exc),
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "new_request_required": exc.new_request_required,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content=submission)

    @app.post("/tasks/{task_id}/conversation/cancel")
    async def cancel_task_conversation(
        task_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, Any]:
        selected = body or {}
        reason = selected.get("reason", "User requested stop")
        if not isinstance(reason, str):
            raise HTTPException(
                status_code=422,
                detail="reason must be text",
            )
        if selected.get("actor", "user") != "user" or selected.get(
            "kind", "user_requested"
        ) != "user_requested":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "cancel_actor_spoofing_rejected",
                    "message": (
                        "public conversation cancellation is always attributed "
                        "to the user; safety/system stops require a trusted "
                        "internal control boundary"
                    ),
                },
            )
        try:
            return conversations.cancel(
                task_id,
                actor="user",
                reason=reason,
                cancellation_kind="user_requested",
                scope="task_execution",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/conversation/approvals/{rpc_id}")
    async def answer_task_approval(
        task_id: str,
        rpc_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        outcome = body.get("outcome")
        if outcome not in {"allowed-once", "rejected"}:
            raise HTTPException(status_code=422, detail="outcome must be allowed-once or rejected")
        try:
            conversations.answer_approval(task_id, rpc_id, outcome)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.post("/tasks/{task_id}/conversation/questions/{rpc_id}")
    async def answer_task_question(
        task_id: str,
        rpc_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        answers = body.get("answers")
        if not isinstance(answers, list):
            raise HTTPException(status_code=422, detail="answers must be a list")
        try:
            conversations.answer_question(task_id, rpc_id, answers)
        except HumanCheckpointAnswerError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.get("/recipes")
    def recipes() -> dict[str, Any]:
        return {"recipes": service.registry.recipe_manifests()}

    @app.get("/data-adapters")
    def data_adapters() -> dict[str, Any]:
        return {"data_adapters": workspace.data_adapters.manifests()}

    @app.get("/task-spec/families")
    def task_spec_families() -> dict[str, Any]:
        return {
            "families": [
                {"family": family, **details}
                for family, details in FAMILY_DETAILS.items()
            ]
        }

    @app.post("/capabilities/match")
    async def match_capabilities(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        capability = body.get("capability_request", body)
        if not isinstance(capability, dict):
            raise HTTPException(status_code=422, detail="capability_request must be an object")
        return {"matches": service.registry.match_recipes(capability)}

    @app.get("/recipes/{recipe_id}/template")
    def recipe_template(recipe_id: str) -> dict[str, Any]:
        try:
            return {"contract": service.registry.get_recipe(recipe_id).template()}
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks")
    def list_tasks(include_archived: bool = Query(False)) -> dict[str, Any]:
        return {"tasks": workspace.list_tasks(include_archived=include_archived)}

    @app.post("/tasks")
    async def create_task(body: dict[str, Any] = Body(...)) -> JSONResponse:
        initial_message = body.get("initial_message")
        create_request_id = body.get("create_request_id")
        message_request_id = body.get("message_request_id")
        if initial_message is not None:
            if not isinstance(initial_message, str) or not initial_message.strip():
                raise HTTPException(
                    status_code=422,
                    detail="initial_message must be non-empty text",
                )
            if not isinstance(create_request_id, str):
                raise HTTPException(
                    status_code=422,
                    detail="create_request_id is required for a conversation task",
                )
            if not isinstance(message_request_id, str):
                raise HTTPException(
                    status_code=422,
                    detail="message_request_id is required for a conversation task",
                )
            message_request_id = message_request_id.strip()
            if not _CONVERSATION_REQUEST_ID.fullmatch(message_request_id):
                raise HTTPException(status_code=422, detail="message_request_id 格式非法")
            try:
                deterministic_task_id = _conversation_task_id(create_request_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            selected_name = str(body.get("name", "")).strip()
            selected_goal = str(body.get("business_goal", "")).strip()
            created = False
            try:
                task = workspace.get_task(deterministic_task_id)
            except FileNotFoundError:
                try:
                    task = workspace.create_task(
                        selected_name,
                        selected_goal,
                        body.get("capability_request")
                        if isinstance(body.get("capability_request"), dict)
                        else {},
                        str(body.get("recipe_id", "")).strip() or None,
                        task_id=deterministic_task_id,
                    )
                    created = True
                except ContractError as create_error:
                    # A concurrent replay can win the deterministic create
                    # after our initial lookup.  Reload the canonical task and
                    # continue through the same identity checks instead of
                    # turning an idempotent retry into a validation failure.
                    try:
                        task = workspace.get_task(deterministic_task_id)
                    except FileNotFoundError:
                        raise HTTPException(status_code=422, detail=str(create_error)) from create_error
                except Exception as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            if (
                task.get("name") != selected_name
                or task.get("business_goal") != selected_goal
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "task_creation_request_conflict",
                        "message": (
                            "create_request_id 已绑定到不同的任务名称或业务目标"
                        ),
                        "task_id": deterministic_task_id,
                    },
                )
            try:
                submission = conversations.submit_message(
                    deterministic_task_id,
                    str(task["name"]),
                    initial_message,
                    composer_mode="queue_after_turn",
                    request_id=message_request_id,
                    actor="user",
                )
            except ComposerRequestConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "composer_request_conflict",
                        "message": str(exc),
                        "task_id": deterministic_task_id,
                        "request_id": message_request_id,
                    },
                ) from exc
            except ComposerRequestTerminalError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "composer_request_terminal",
                        "message": str(exc),
                        "task_id": deterministic_task_id,
                        "request_id": exc.request_id,
                        "status": exc.status,
                        "new_request_required": exc.new_request_required,
                    },
                ) from exc
            except ComposerSubmissionError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "composer_submission_failed",
                        "message": str(exc),
                        "task_id": deterministic_task_id,
                        "request_id": exc.request_id,
                        "status": exc.status,
                        "new_request_required": exc.new_request_required,
                    },
                ) from exc
            except (ValueError, ComposerModeUnsupportedError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except AgentRuntimeError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "agent_runtime_unavailable",
                        "message": str(exc),
                        "task_id": deterministic_task_id,
                    },
                ) from exc
            return JSONResponse(
                status_code=201 if created else 200,
                content={
                    "task": workspace.get_task(deterministic_task_id),
                    "submission": submission,
                    "created": created,
                },
            )
        try:
            task = workspace.create_task(
                str(body.get("name", "")),
                str(body.get("business_goal", "")),
                body.get("capability_request") if isinstance(body.get("capability_request"), dict) else {},
                str(body.get("recipe_id", "")).strip() or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content={"task": task})

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        try:
            return {"task": workspace.get_task(task_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/csv-target-recommendation")
    async def recommend_task_csv_target(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        columns = body.get("columns")
        if not isinstance(columns, list):
            raise HTTPException(status_code=422, detail="columns must be an array")
        try:
            recommendation = recommend_csv_target_column(
                workspace.get_task(task_id),
                columns,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"recommendation": recommendation}

    @app.post("/tasks/{task_id}/archive")
    def archive_task(task_id: str) -> dict[str, Any]:
        try:
            return {"task": workspace.archive_task(task_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/spec/revisions")
    def list_task_spec_revisions(task_id: str) -> dict[str, Any]:
        try:
            revisions = workspace.list_task_spec_revisions(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "task_id": task_id,
            "current_revision": revisions[-1]["revision"],
            "revisions": revisions,
        }

    @app.get("/tasks/{task_id}/spec/revisions/{revision}")
    def get_task_spec_revision(task_id: str, revision: int) -> dict[str, Any]:
        try:
            return {
                "task_spec": workspace.get_task_spec_revision(task_id, revision)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/tasks/{task_id}/spec")
    async def update_task_spec(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            return {"task": workspace.update_task_spec(task_id, body)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/recipe")
    async def select_task_recipe(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        recipe_id = str(body.get("recipe_id", "")).strip()
        if not recipe_id:
            raise HTTPException(status_code=422, detail="recipe_id is required")
        try:
            return {"task": workspace.select_recipe(task_id, recipe_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/recipe/scaffold")
    async def scaffold_task_recipe(task_id: str) -> JSONResponse:
        try:
            scaffold = workspace.scaffold_recipe(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        scaffold["download_url"] = (
            f"/tasks/{task_id}/recipe/scaffolds/{scaffold['archive_name']}"
        )
        return JSONResponse(status_code=201, content={"scaffold": scaffold})

    @app.get("/tasks/{task_id}/recipe/scaffolds/{archive_name}")
    def download_task_recipe_scaffold(task_id: str, archive_name: str) -> FileResponse:
        try:
            return FileResponse(
                workspace.recipe_scaffold_file(task_id, archive_name),
                filename=archive_name,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/staged-assets")
    async def stage_task_asset(
        task_id: str,
        request: Request,
        x_filename: str | None = Header(default=None),
        x_spec_revision: int | None = Header(default=None),
    ) -> JSONResponse:
        filename = unquote(x_filename or "samples.zip")
        try:
            result = workspace.stage_asset(
                task_id,
                await request.body(),
                filename,
                spec_revision=x_spec_revision,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StagedAssetRejected as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "asset_id": exc.asset_id,
                    "status": "quarantined",
                },
            ) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/staged-assets")
    def list_task_staged_assets(task_id: str) -> dict[str, Any]:
        try:
            assets = workspace.list_staged_assets(task_id)
            task = workspace.get_task(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "task_id": task_id,
            "staged_assets": assets,
            "summary": task["staged_assets"],
        }

    @app.get("/tasks/{task_id}/staged-assets/{asset_id}")
    def get_task_staged_asset(task_id: str, asset_id: str) -> dict[str, Any]:
        try:
            asset = workspace.get_staged_asset(task_id, asset_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"staged_asset": asset}

    @app.post("/tasks/{task_id}/recipe-builds")
    async def create_task_recipe_build(
        task_id: str,
        body: dict[str, Any] = Body(default={}),
    ) -> JSONResponse:
        build_type = str(body.get("build_type", "declarative")).strip()
        recipe_spec = body.get("recipe_spec")
        if recipe_spec is not None and not isinstance(recipe_spec, dict):
            raise HTTPException(status_code=422, detail="recipe_spec must be an object")
        try:
            result = workspace.start_recipe_build(
                task_id,
                recipe_spec,
                build_type=build_type,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/recipe-builds")
    def list_task_recipe_builds(task_id: str) -> dict[str, Any]:
        try:
            return {
                "task_id": task_id,
                "recipe_builds": workspace.list_recipe_builds(task_id),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/recipe-builds/{attempt_id}")
    def get_task_recipe_build(task_id: str, attempt_id: str) -> dict[str, Any]:
        try:
            return {"recipe_build": workspace.get_recipe_build(task_id, attempt_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/recipe-builds/{attempt_id}/register")
    async def register_task_recipe_build(
        task_id: str,
        attempt_id: str,
        body: dict[str, Any] = Body(...),
        x_model_harness_agent_token: str | None = Header(
            default=None,
            alias="X-Model-Harness-Agent-Token",
        ),
    ) -> dict[str, Any]:
        bridge_token_sha256 = require_agent_bridge_approval_token(
            x_model_harness_agent_token
        )
        try:
            supplied_approval = body.get("approval")
            if not isinstance(supplied_approval, dict):
                raise ContractError(
                    "Recipe registration requires an explicit approval object"
                )
            actor = str(supplied_approval.get("actor") or "").strip()
            checkpoint_id = str(
                supplied_approval.get("checkpoint_id") or ""
            ).strip()
            if actor != "user":
                raise ContractError(
                    "Recipe registration approval actor must be user"
                )
            if not checkpoint_id:
                raise ContractError(
                    "Recipe registration approval checkpoint_id is required"
                )
            return workspace.register_recipe_build(
                task_id,
                attempt_id,
                {
                    "decision": body.get("decision"),
                    "actor": actor,
                    "checkpoint_id": checkpoint_id,
                    "reason": str(body.get("reason", "")).strip(),
                    "verified_by": "agent_bridge_token",
                    "bridge_token_sha256": bridge_token_sha256,
                },
                candidate_digest=str(body.get("candidate_digest", "")),
                validation_digest=str(body.get("validation_digest", "")),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/recipe-builds/{attempt_id}/reject")
    async def reject_task_recipe_build(
        task_id: str,
        attempt_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            return workspace.reject_recipe_build(
                task_id,
                attempt_id,
                actor=str(body.get("actor", "")).strip(),
                reason=str(body.get("reason", "rejected by user")).strip(),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/dataset")
    async def upload_task_dataset(
        task_id: str,
        request: Request,
        x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
        x_filename: str | None = Header(default=None),
        x_target_column: str | None = Header(default=None),
        x_ignored_columns: str | None = Header(default=None),
        x_delimiter: str | None = Header(default=None),
        x_data_adapter: str | None = Header(default=None),
    ) -> JSONResponse:
        filename = unquote(x_filename or "dataset.zip")
        try:
            options: dict[str, Any] = {}
            if x_target_column:
                options["target_column"] = unquote(x_target_column)
            if x_ignored_columns:
                options["ignored_columns"] = [
                    unquote(value).strip()
                    for value in x_ignored_columns.split(",")
                    if value.strip()
                ]
            if x_delimiter:
                options["delimiter"] = unquote(x_delimiter)
            if x_data_adapter:
                options["data_adapter"] = unquote(x_data_adapter)
            payload = await request.body()
            if x_request_id is not None:
                task, receipt, replayed = workspace.attach_dataset_idempotent(
                    task_id,
                    payload,
                    filename,
                    request_id=x_request_id,
                    options=options,
                )
            else:
                task = workspace.attach_dataset(
                    task_id,
                    payload,
                    filename,
                    options=options,
                )
                receipt = None
                replayed = False
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(
            status_code=201,
            content={
                "task": task,
                "dataset_upload": receipt,
                "idempotent_replay": replayed,
            },
        )

    @app.get(
        "/tasks/{task_id}/dataset-upload-receipts/{request_id}"
    )
    def get_task_dataset_upload_receipt(
        task_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        try:
            return {
                "task": workspace.get_task(task_id),
                "dataset_upload": workspace.get_dataset_upload_receipt(
                    task_id,
                    request_id,
                ),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractError, HarnessError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/tasks/{task_id}/contract")
    async def update_task_contract(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            return {"task": workspace.update_contract(task_id, body)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/contract-revisions")
    async def list_task_contract_revisions(task_id: str) -> dict[str, Any]:
        try:
            return {
                "contract_revisions": workspace.list_contract_revisions(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ContractRevisionIntegrityError, ContractRevisionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/contract-revisions/{contract_revision_id}")
    async def get_task_contract_revision(
        task_id: str, contract_revision_id: str
    ) -> dict[str, Any]:
        try:
            return {
                "contract_revision": workspace.get_contract_revision(
                    task_id, contract_revision_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractRevisionIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/approval-decisions")
    async def list_task_approval_decisions(task_id: str) -> dict[str, Any]:
        try:
            return {
                "approval_decisions": workspace.list_approval_decisions(task_id)
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalDecisionIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/approval-decisions/{approval_decision_id}")
    async def get_task_approval_decision(
        task_id: str, approval_decision_id: str
    ) -> dict[str, Any]:
        try:
            return {
                "approval_decision": workspace.get_approval_decision(
                    task_id, approval_decision_id
                )
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalDecisionIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/confirm")
    async def confirm_task_contract(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            return {"task": workspace.confirm_contract(task_id, body)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ContractRevisionConflictError,
            ContractRevisionIntegrityError,
            ApprovalDecisionIntegrityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/run-authorizations")
    async def authorize_task_run_start(
        task_id: str,
        body: dict[str, Any] | None = Body(default=None),
        x_model_harness_agent_token: str | None = Header(
            default=None,
            alias="X-Model-Harness-Agent-Token",
        ),
    ) -> JSONResponse:
        bridge_token_sha256 = require_agent_bridge_approval_token(
            x_model_harness_agent_token
        )
        selected = body or {}
        try:
            supplied_approval = dict(selected["approval"])
            supplied_approval.update(
                {
                    "verified_by": "agent_bridge_token",
                    "bridge_token_sha256": bridge_token_sha256,
                }
            )
            result = workspace.authorize_task_run_start(
                task_id,
                contract_sha256=str(selected["contract_sha256"]),
                dataset_id=str(selected["dataset_id"]),
                dataset_fingerprint_sha256=str(
                    selected["dataset_fingerprint_sha256"]
                ),
                spec_revision=int(selected["spec_revision"]),
                approval=supplied_approval,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post("/tasks/{task_id}/runs")
    async def start_task_run(
        task_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        selected = body or {}
        try:
            result = workspace.start_run_with_authorization(
                task_id,
                run_authorization_id=str(selected["run_authorization_id"]),
                authorization_token=str(selected["authorization_token"]),
                run_request_sha256=str(selected["run_request_sha256"]),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content=result)

    @app.post("/tasks/{task_id}/runs/{run_id}/cancel")
    async def cancel_task_run(task_id: str, run_id: str) -> dict[str, Any]:
        try:
            return workspace.cancel_run(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/runs/{run_id}/resume")
    async def resume_task_run(task_id: str, run_id: str) -> JSONResponse:
        try:
            task = workspace.resume_run(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content={"task": task})

    @app.post("/tasks/{task_id}/runs/{run_id}/strategies/{strategy_id}/apply")
    async def apply_task_strategy(
        task_id: str,
        run_id: str,
        strategy_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        if (body or {}).get("approval_confirmed") is not True:
            raise HTTPException(status_code=409, detail="strategy application requires approval_confirmed=true")
        try:
            task = workspace.apply_strategy(task_id, run_id, strategy_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content={"task": task})

    @app.get("/tasks/{task_id}/runs/{run_id}/evaluation-report")
    def task_run_evaluation_report(
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.evaluation_report(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/runs/{run_id}/inference-inputs")
    async def create_task_run_inference_input(
        task_id: str,
        run_id: str,
        request: Request,
        x_filename: str | None = Header(default=None, alias="X-Filename"),
        x_sample_type: str | None = Header(default=None, alias="X-Sample-Type"),
    ) -> JSONResponse:
        payload = await request.body()
        if len(payload) > MAX_INFERENCE_INPUT_BYTES:
            raise HTTPException(status_code=413, detail="sample upload exceeds 25MB")
        try:
            result = workspace.stage_inference_input(
                task_id,
                run_id,
                payload,
                filename=unquote(x_filename or "").strip(),
                sample_type=(x_sample_type or "").strip().lower(),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InferenceInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/runs/{run_id}/inference-inputs")
    def list_task_run_inference_inputs(
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.list_inference_inputs(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/tasks/{task_id}/runs/{run_id}/inference-inputs/{inference_input_id}"
    )
    def get_task_run_inference_input(
        task_id: str,
        run_id: str,
        inference_input_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.get_inference_input(
                task_id, run_id, inference_input_id
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/tasks/{task_id}/runs/{run_id}/sample-inference-authorizations"
    )
    async def authorize_task_run_sample_inference(
        task_id: str,
        run_id: str,
        body: dict[str, Any] | None = Body(default=None),
        x_model_harness_agent_token: str | None = Header(
            default=None,
            alias="X-Model-Harness-Agent-Token",
        ),
    ) -> JSONResponse:
        bridge_token_sha256 = require_agent_bridge_approval_token(
            x_model_harness_agent_token
        )
        selected = body or {}
        try:
            supplied_approval = dict(selected["approval"])
            supplied_approval.update(
                {
                    "verified_by": "agent_bridge_token",
                    "bridge_token_sha256": bridge_token_sha256,
                }
            )
            result = workspace.authorize_sample_inference(
                task_id,
                run_id,
                inference_input_id=str(selected["inference_input_id"]),
                inference_input_sha256=str(
                    selected["inference_input_sha256"]
                ),
                approval=supplied_approval,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post(
        "/tasks/{task_id}/runs/{run_id}/inference-inputs/"
        "{inference_input_id}/execute"
    )
    async def execute_task_run_inference_input(
        task_id: str,
        run_id: str,
        inference_input_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        selected = body or {}
        authorization_id = str(
            selected.get("sample_inference_authorization_id") or ""
        )
        try:
            result = workspace.run_sample_inference_with_authorization(
                task_id,
                run_id,
                inference_input_id=inference_input_id,
                sample_inference_authorization_id=authorization_id,
                authorization_token=str(selected.get("authorization_token") or ""),
                sample_inference_request_sha256=str(
                    selected.get("sample_inference_request_sha256") or ""
                ),
            )
        except SampleInferenceBlocked as exc:
            input_view = workspace.get_inference_input(
                task_id, run_id, inference_input_id
            )
            authorization_view = workspace.get_delivery_authorization(
                task_id, authorization_id
            )
            return JSONResponse(
                status_code=422,
                content={
                    "task": workspace.get_task(task_id),
                    "run_id": run_id,
                    "detail": str(exc),
                    "sample_inference": exc.report,
                    "inference_input": input_view["inference_input"],
                    "object_refs": input_view["object_refs"],
                    "sample_inference_authorization": authorization_view[
                        "delivery_authorization"
                    ],
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post("/tasks/{task_id}/runs/{run_id}/sample-inferences")
    async def create_task_run_sample_inference(
        task_id: str,
        run_id: str,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=410,
            content={
                "detail": (
                    "raw sample upload-and-execute was removed; upload bytes to "
                    f"/tasks/{task_id}/runs/{run_id}/inference-inputs, obtain "
                    "one sample-inference authorization, then execute the opaque input id"
                ),
                "replacement": {
                    "upload": f"/tasks/{task_id}/runs/{run_id}/inference-inputs",
                    "authorize": (
                        f"/tasks/{task_id}/runs/{run_id}/"
                        "sample-inference-authorizations"
                    ),
                    "execute_template": (
                        f"/tasks/{task_id}/runs/{run_id}/inference-inputs/"
                        "{inference_input_id}/execute"
                    ),
                },
            },
        )

    @app.get("/tasks/{task_id}/runs/{run_id}/sample-inferences")
    def list_task_run_sample_inferences(
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.list_sample_inferences(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/tasks/{task_id}/runs/{run_id}/sample-inferences/{check_id}"
    )
    def get_task_run_sample_inference(
        task_id: str,
        run_id: str,
        check_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.get_sample_inference(task_id, run_id, check_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/tasks/{task_id}/runs/{run_id}/artifact-bundle-authorizations"
    )
    async def authorize_task_run_artifact_bundle_build(
        task_id: str,
        run_id: str,
        body: dict[str, Any] | None = Body(default=None),
        x_model_harness_agent_token: str | None = Header(
            default=None,
            alias="X-Model-Harness-Agent-Token",
        ),
    ) -> JSONResponse:
        bridge_token_sha256 = require_agent_bridge_approval_token(
            x_model_harness_agent_token
        )
        selected = body or {}
        try:
            supplied_approval = dict(selected["approval"])
            supplied_approval.update(
                {
                    "verified_by": "agent_bridge_token",
                    "bridge_token_sha256": bridge_token_sha256,
                }
            )
            result = workspace.authorize_artifact_bundle_build(
                task_id,
                run_id,
                evaluation_report_id=str(selected["evaluation_report_id"]),
                evaluation_report_sha256=str(
                    selected["evaluation_report_sha256"]
                ),
                approval=supplied_approval,
                sample_inference_check_id=(
                    str(selected["sample_inference_check_id"])
                    if selected.get("sample_inference_check_id")
                    else None
                ),
                inference_check_id=(
                    str(selected["inference_check_id"])
                    if selected.get("inference_check_id")
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/delivery-authorizations/{authorization_id}")
    def get_task_delivery_authorization(
        task_id: str,
        authorization_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.get_delivery_authorization(task_id, authorization_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/runs/{run_id}/artifact-bundles")
    async def build_task_run_artifact_bundle(
        task_id: str,
        run_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        selected = body or {}
        try:
            result = workspace.build_artifact_bundle(
                task_id,
                run_id,
                artifact_bundle_authorization_id=str(
                    selected["artifact_bundle_authorization_id"]
                ),
                authorization_token=str(selected["authorization_token"]),
                bundle_request_sha256=str(selected["bundle_request_sha256"]),
                sample_inference_check_id=(
                    str(selected["sample_inference_check_id"])
                    if selected.get("sample_inference_check_id")
                    else None
                ),
                inference_check_id=(
                    str(selected["inference_check_id"])
                    if selected.get("inference_check_id")
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.get("/tasks/{task_id}/runs/{run_id}/artifact-bundles")
    def list_task_run_artifact_bundles(
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.list_artifact_bundles(task_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/runs/{run_id}/artifact-bundles/{bundle_id}")
    def get_task_run_artifact_bundle(
        task_id: str,
        run_id: str,
        bundle_id: str,
    ) -> dict[str, Any]:
        try:
            return workspace.get_artifact_bundle(task_id, run_id, bundle_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/tasks/{task_id}/runs/{run_id}/artifact-bundles/{bundle_id}/download-authorizations"
    )
    async def authorize_task_run_artifact_bundle_download(
        task_id: str,
        run_id: str,
        bundle_id: str,
        body: dict[str, Any] | None = Body(default=None),
        x_model_harness_agent_token: str | None = Header(
            default=None,
            alias="X-Model-Harness-Agent-Token",
        ),
    ) -> JSONResponse:
        bridge_token_sha256 = require_agent_bridge_approval_token(
            x_model_harness_agent_token
        )
        selected = body or {}
        try:
            supplied_approval = dict(selected["approval"])
            supplied_approval.update(
                {
                    "verified_by": "agent_bridge_token",
                    "bridge_token_sha256": bridge_token_sha256,
                }
            )
            result = workspace.authorize_artifact_bundle_download(
                task_id,
                run_id,
                bundle_id,
                manifest_sha256=str(selected["manifest_sha256"]),
                archive_sha256=str(selected["archive_sha256"]),
                approval=supplied_approval,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=result)

    @app.post(
        "/tasks/{task_id}/runs/{run_id}/artifact-bundles/{bundle_id}/download"
    )
    async def download_task_run_artifact_bundle(
        task_id: str,
        run_id: str,
        bundle_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> FileResponse:
        selected = body or {}
        try:
            path, authorization = workspace.consume_artifact_bundle_download(
                task_id,
                run_id,
                bundle_id,
                artifact_bundle_download_authorization_id=str(
                    selected["artifact_bundle_download_authorization_id"]
                ),
                authorization_token=str(selected["authorization_token"]),
                download_request_sha256=str(selected["download_request_sha256"]),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"{run_id}-{bundle_id}.zip",
            headers={
                "X-Delivery-Authorization-Id": str(
                    authorization["authorization_id"]
                ),
                "X-Delivery-Request-Sha256": str(
                    authorization["scope_sha256"]
                ),
            },
        )

    @app.get("/tasks/{task_id}/datasets/{dataset_id}/{relative_path:path}")
    def task_dataset_file(task_id: str, dataset_id: str, relative_path: str) -> FileResponse:
        try:
            return FileResponse(workspace.dataset_file(task_id, dataset_id, relative_path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat")
    async def retired_chat_endpoint() -> None:
        """Keep one explicit migration release without a second chat runtime."""

        raise HTTPException(
            status_code=410,
            detail={
                "code": "chat_endpoint_retired",
                "message": (
                    "The global chat endpoint has been retired. Conversation is "
                    "owned by one TrainingTask and the real multi-agent runtime."
                ),
                "canonical_endpoint": (
                    "/tasks/{task_id}/conversation/messages"
                ),
            },
        )

    @app.get("/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": service.list_runs()}

    @app.post("/runs")
    async def submit_run(
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        contract = body.get("contract") if isinstance(body, dict) else None
        if not isinstance(contract, dict):
            raise HTTPException(status_code=422, detail="contract must be an object")
        raise HTTPException(
            status_code=409,
            detail=(
                "global run creation is disabled; create and confirm a workspace "
                "task, then POST /tasks/{task_id}/runs"
            ),
        )

    @app.get("/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, Any]:
        try:
            return service.status(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/result")
    def run_result(run_id: str) -> dict[str, Any]:
        try:
            return service.result(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/artifacts/{artifact_name}")
    def run_artifact(run_id: str, artifact_name: str) -> FileResponse:
        try:
            return FileResponse(
                service.artifact_path(run_id, artifact_name),
                filename=artifact_name,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events")
    def run_events(
        run_id: str,
        after_seq: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            return {"events": service.events(run_id, after_seq=after_seq)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events/stream")
    def stream_events(
        run_id: str,
        after_seq: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def generate() -> Any:
            sequence = after_seq
            while True:
                records = service.events(run_id, after_seq=sequence)
                for record in records:
                    sequence = int(record["seq"])
                    data = json.dumps(record, ensure_ascii=False)
                    yield (
                        f"id: {sequence}\n"
                        f"event: {record['type']}\n"
                        f"data: {data}\n\n"
                    )
                status = service.status(run_id)["status"]
                if status in TERMINAL_STATUSES and not records:
                    break
                await asyncio.sleep(0.5)

        try:
            service.status(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        del run_id
        raise HTTPException(
            status_code=409,
            detail=(
                "global run cancellation is disabled; use "
                "/tasks/{task_id}/runs/{run_id}/cancel"
            ),
        )

    @app.post("/runs/{run_id}/resume")
    async def resume_run(
        run_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        del body
        raise HTTPException(
            status_code=409,
            detail=(
                "global run resume is disabled; use "
                "/tasks/{task_id}/runs/{run_id}/resume"
            ),
        )

    @app.get("/runs/{run_id}/strategies")
    def strategies(run_id: str) -> dict[str, Any]:
        try:
            return service.strategies(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/strategies/{strategy_id}/apply")
    async def apply_strategy(
        run_id: str,
        strategy_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        body = body or {}
        if body.get("approval_confirmed") is not True:
            raise HTTPException(
                status_code=409,
                detail="strategy application requires approval_confirmed=true",
            )
        raise HTTPException(
            status_code=409,
            detail=(
                "global strategy application is disabled; use the task-owned "
                "strategy endpoint"
            ),
        )

    return app


def serve(
    runs_dir: str | Path = "runs",
    host: str = "127.0.0.1",
    port: int = 8765,
    max_workers: int = 1,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "HTTP server dependencies are missing; install specialist-model-studio[server]"
        ) from exc
    uvicorn.run(create_app(runs_dir, max_workers=max_workers), host=host, port=port)
