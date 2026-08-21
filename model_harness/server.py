from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:  # optional server dependency
    from starlette.requests import Request
except ImportError:  # pragma: no cover
    Request = Any  # type: ignore[misc,assignment]

from .chat import ChatController
from .agent_bridge import AgentRuntimeError, ConversationBridge, DshEventHub, DshRpcClient
from .service import RunService
from .state import TERMINAL_STATUSES
from .workspace import TrainingWorkspace


def create_app(
    runs_dir: str | Path = "runs",
    max_workers: int = 1,
    workspace_dir: str | Path | None = None,
    conversation_url: str | None = None,
) -> Any:
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Query
        from fastapi.responses import (
            FileResponse,
            JSONResponse,
            RedirectResponse,
            StreamingResponse,
        )
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "HTTP server dependencies are missing; install ai-pm-model-harness[server]"
        ) from exc

    resolved_runs_dir = Path(runs_dir).expanduser().resolve()
    service = RunService(runs_dir=resolved_runs_dir, max_workers=max_workers)
    workspace = TrainingWorkspace(
        workspace_dir or (resolved_runs_dir / "_workspace"),
        service,
    )
    chat = ChatController(service)
    web_dir = Path(__file__).parent / "web"
    resolved_conversation_url = (
        conversation_url
        or os.environ.get("MODEL_HARNESS_CONVERSATION_URL")
        or "http://127.0.0.1:3080"
    ).rstrip("/")
    agent_client = DshRpcClient(resolved_conversation_url)
    agent_events = DshEventHub(agent_client)
    conversations = ConversationBridge(
        workspace.root,
        agent_client,
        agent_events,
        Path(__file__).parent.parent,
    )

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        agent_events.start()
        try:
            yield
        finally:
            agent_events.stop()
            service.close()

    app = FastAPI(
        title="AI PM Model Harness",
        version="0.6.0-alpha.1",
        description="Conversation-first product runtime for auditable specialist-model training.",
        lifespan=lifespan,
    )
    app.state.run_service = service
    app.state.chat_controller = chat
    app.state.training_workspace = workspace
    app.state.conversation_bridge = conversations
    app.mount("/app/static", StaticFiles(directory=web_dir), name="app-static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.6.0-alpha.1",
            "recovered_runs": service.recovered_runs,
            "primary_experience": "conversation",
            "conversation_url": "/app",
            "workbench_url": "/app",
        }

    @app.get("/runtime")
    def runtime() -> dict[str, Any]:
        return {
            "primary_experience": "conversation",
            "conversation_url": "/app",
            "workbench_url": "/app",
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

    @app.get("/tasks/{task_id}/conversation")
    def task_conversation(task_id: str) -> dict[str, Any]:
        try:
            workspace.get_task(task_id)
            return {"conversation": conversations.conversation(task_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/conversation/messages")
    async def task_conversation_message(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=422, detail="message must be non-empty text")
        try:
            task = workspace.get_task(task_id)
            session_id = conversations.prompt(task_id, task["name"], message)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content={"accepted": True, "session_id": session_id})

    @app.post("/tasks/{task_id}/conversation/cancel")
    async def cancel_task_conversation(task_id: str) -> dict[str, Any]:
        try:
            conversations.cancel(task_id)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

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
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.get("/recipes")
    def recipes() -> dict[str, Any]:
        return {"recipes": service.registry.recipe_manifests()}

    @app.get("/data-adapters")
    def data_adapters() -> dict[str, Any]:
        return {"data_adapters": workspace.data_adapters.manifests()}

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
    def list_tasks() -> dict[str, Any]:
        return {"tasks": workspace.list_tasks()}

    @app.post("/tasks")
    async def create_task(body: dict[str, Any] = Body(...)) -> JSONResponse:
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

    @app.post("/tasks/{task_id}/dataset")
    async def upload_task_dataset(
        task_id: str,
        request: Request,
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
            task = workspace.attach_dataset(
                task_id,
                await request.body(),
                filename,
                options=options,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content={"task": task})

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

    @app.post("/tasks/{task_id}/confirm")
    async def confirm_task_contract(
        task_id: str,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        try:
            return {"task": workspace.confirm_contract(task_id, body)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/runs")
    async def start_task_run(task_id: str) -> JSONResponse:
        try:
            task = workspace.start_run(task_id)
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

    @app.get("/tasks/{task_id}/datasets/{dataset_id}/{relative_path:path}")
    def task_dataset_file(task_id: str, dataset_id: str, relative_path: str) -> FileResponse:
        try:
            return FileResponse(workspace.dataset_file(task_id, dataset_id, relative_path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat")
    async def chat_message(
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        message = body.get("message")
        if not isinstance(message, str):
            raise HTTPException(status_code=422, detail="message must be text")
        run_id = body.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            raise HTTPException(status_code=422, detail="run_id must be text")
        try:
            return chat.handle(message, run_id=run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
        try:
            run_dir = service.submit(contract, run_id=body.get("run_id"))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(
            status_code=202,
            content={"run_id": run_dir.name, "status": "queued"},
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
        try:
            accepted = service.cancel(run_id)
            return {"run_id": run_id, "cancel_requested": accepted}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/resume")
    async def resume_run(
        run_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        body = body or {}
        try:
            child = service.resume(run_id, child_run_id=body.get("run_id"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(
            status_code=202,
            content={"run_id": child.name, "parent_run_id": run_id},
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
        try:
            child = service.apply_strategy(
                run_id,
                strategy_id,
                child_run_id=body.get("run_id"),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(
            status_code=202,
            content={
                "run_id": child.name,
                "parent_run_id": run_id,
                "strategy_id": strategy_id,
            },
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
            "HTTP server dependencies are missing; install ai-pm-model-harness[server]"
        ) from exc
    uvicorn.run(create_app(runs_dir, max_workers=max_workers), host=host, port=port)
