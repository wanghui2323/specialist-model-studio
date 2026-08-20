from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .service import RunService
from .state import TERMINAL_STATUSES


def create_app(
    runs_dir: str | Path = "runs",
    max_workers: int = 1,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Query, Request
        from fastapi.responses import JSONResponse, StreamingResponse
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "HTTP server dependencies are missing; install ai-pm-model-harness[server]"
        ) from exc

    service = RunService(runs_dir=runs_dir, max_workers=max_workers)
    app = FastAPI(
        title="AI PM Model Harness",
        version="0.2.0-alpha.1",
        description="Local-first job API for auditable specialist-model training.",
    )
    app.state.run_service = service

    async def optional_json_body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="request body is not JSON") from exc
        if not isinstance(value, dict):
            raise HTTPException(status_code=422, detail="request body must be an object")
        return value

    @app.on_event("shutdown")
    def shutdown() -> None:
        service.close()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.2.0-alpha.1",
            "recovered_runs": service.recovered_runs,
        }

    @app.get("/recipes")
    def recipes() -> dict[str, Any]:
        return {"recipes": service.registry.recipe_manifests()}

    @app.get("/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": service.list_runs()}

    @app.post("/runs")
    async def submit_run(request: Request) -> JSONResponse:
        body = await optional_json_body(request)
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
    async def resume_run(run_id: str, request: Request) -> JSONResponse:
        body = await optional_json_body(request)
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
        request: Request,
    ) -> JSONResponse:
        body = await optional_json_body(request)
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
