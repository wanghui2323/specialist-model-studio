from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:  # optional server dependency
    from starlette.requests import Request
except ImportError:  # pragma: no cover
    Request = Any  # type: ignore[misc,assignment]

from .chat import ChatController
from .service import RunService
from .state import TERMINAL_STATUSES
from .workspace import TrainingWorkspace


def create_app(
    runs_dir: str | Path = "runs",
    max_workers: int = 1,
    workspace_dir: str | Path | None = None,
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

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="AI PM Model Harness",
        version="0.4.0-alpha.1",
        description="Local-first job API for auditable specialist-model training.",
        lifespan=lifespan,
    )
    app.state.run_service = service
    app.state.chat_controller = chat
    app.state.training_workspace = workspace
    app.mount("/app/static", StaticFiles(directory=web_dir), name="app-static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.4.0-alpha.1",
            "recovered_runs": service.recovered_runs,
        }

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app")

    @app.get("/app", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/recipes")
    def recipes() -> dict[str, Any]:
        return {"recipes": service.registry.recipe_manifests()}

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

    @app.post("/tasks/{task_id}/dataset")
    async def upload_task_dataset(
        task_id: str,
        request: Request,
        x_filename: str | None = Header(default=None),
    ) -> JSONResponse:
        filename = unquote(x_filename or "dataset.zip")
        try:
            task = workspace.attach_dataset(task_id, await request.body(), filename)
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
