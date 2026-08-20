from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from .errors import ContractError, HarnessError
from .io_utils import read_json
from .plugins import PluginRegistry, default_registry
from .runner import execute_run, prepare_run
from .state import ACTIVE_STATUSES, RunState, TERMINAL_STATUSES


class RunService:
    """Persistent local job service for CLI, HTTP and future chat adapters."""

    def __init__(
        self,
        runs_dir: str | Path = "runs",
        max_workers: int = 1,
        registry: PluginRegistry | None = None,
        recover: bool = True,
    ) -> None:
        self.runs_dir = Path(runs_dir).expanduser().resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.registry = registry or default_registry()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="model-harness",
        )
        self._futures: dict[str, Future[Path]] = {}
        self._lock = RLock()
        self.recovered_runs = self.recover_stale_runs() if recover else []

    def recover_stale_runs(self) -> list[str]:
        recovered: list[str] = []
        for state_path in sorted(self.runs_dir.glob("*/run_state.json")):
            state = RunState.load(state_path.parent)
            if state.data.get("schema_version") != "0.2":
                continue
            if state.status in ACTIVE_STATUSES:
                state.interrupt(
                    "service restarted while run was active; resume creates an auditable child run"
                )
                recovered.append(str(state.data["run_id"]))
        return recovered

    def submit(
        self,
        contract: str | Path | dict[str, Any],
        run_id: str | None = None,
        parent_run_id: str | None = None,
    ) -> Path:
        run_dir = prepare_run(
            contract,
            runs_dir=self.runs_dir,
            run_id=run_id,
            registry=self.registry,
            parent_run_id=parent_run_id,
        )
        selected_run_id = run_dir.name
        future = self._executor.submit(
            execute_run,
            run_dir,
            self.registry,
        )
        with self._lock:
            self._futures[selected_run_id] = future
        return run_dir

    def status(self, run_id: str) -> dict[str, Any]:
        return read_json(self._run_dir(run_id) / "run_state.json")

    def list_runs(self) -> list[dict[str, Any]]:
        states = [
            read_json(path)
            for path in sorted(
                self.runs_dir.glob("*/run_state.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        ]
        return states

    def events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        path = self._run_dir(run_id) / "events.ndjson"
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if int(record["seq"]) > after_seq:
                records.append(record)
        return records

    def wait(self, run_id: str, timeout: float | None = None) -> Path:
        with self._lock:
            future = self._futures.get(run_id)
        if future is not None:
            return future.result(timeout=timeout)
        state = self.status(run_id)
        if state["status"] in TERMINAL_STATUSES:
            return self._run_dir(run_id)
        raise HarnessError(f"run is not owned by this service instance: {run_id}")

    def cancel(self, run_id: str, reason: str = "requested by user") -> bool:
        state = RunState.load(self._run_dir(run_id))
        if not state.request_cancel(reason):
            return False
        with self._lock:
            future = self._futures.get(run_id)
        if future is not None and future.cancel():
            latest = RunState.load(self._run_dir(run_id))
            latest.cancel(reason)
        return True

    def resume(self, run_id: str, child_run_id: str | None = None) -> Path:
        source = self._run_dir(run_id)
        state = read_json(source / "run_state.json")
        if state["status"] not in {"failed", "cancelled", "interrupted"}:
            raise HarnessError(
                f"only failed, cancelled or interrupted runs can resume; got {state['status']}"
            )
        return self.submit(
            read_json(source / "task_contract.json"),
            run_id=child_run_id,
            parent_run_id=run_id,
        )

    def strategies(self, run_id: str) -> dict[str, Any]:
        return read_json(
            self._run_dir(run_id)
            / "artifacts"
            / "optimization_strategies.json"
        )

    def result(self, run_id: str) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        state = read_json(run_dir / "run_state.json")
        contract = read_json(run_dir / "task_contract.json")
        artifact_dir = run_dir / "artifacts"
        metrics_path = artifact_dir / "metrics.json"
        strategies_path = artifact_dir / "optimization_strategies.json"
        failures_path = artifact_dir / "failure_samples.json"
        manifest_path = run_dir / "run_manifest.json"
        metrics = read_json(metrics_path) if metrics_path.is_file() else None
        manifest = read_json(manifest_path) if manifest_path.is_file() else None
        child_run_ids = [
            item["run_id"]
            for item in self.list_runs()
            if item.get("parent_run_id") == run_id
        ]
        return {
            "run_id": run_id,
            "task_id": state["task_id"],
            "recipe": contract["recipe"],
            "business_goal": contract["business_goal"],
            "status": state["status"],
            "parent_run_id": state.get("parent_run_id"),
            "child_run_ids": child_run_ids,
            "offline_gates_passed": state.get("offline_gates_passed"),
            "metrics": metrics,
            "strategies": (
                read_json(strategies_path)["strategies"]
                if strategies_path.is_file()
                else []
            ),
            "optimization_history": contract.get("optimization_history", []),
            "dataset": contract.get("dataset"),
            "failure_samples": (
                read_json(failures_path).get("samples", [])
                if failures_path.is_file()
                else []
            ),
            "artifacts": (
                [
                    {"name": name, **details}
                    for name, details in manifest.get("artifacts", {}).items()
                ]
                if manifest
                else []
            ),
            "timings_ms": state.get("timings_ms", {}),
            "total_duration_ms": state.get("total_duration_ms"),
            "error": state.get("error"),
        }

    def artifact_path(self, run_id: str, artifact_name: str) -> Path:
        if not artifact_name or Path(artifact_name).name != artifact_name:
            raise HarnessError("invalid artifact name")
        artifact_dir = (self._run_dir(run_id) / "artifacts").resolve()
        target = (artifact_dir / artifact_name).resolve()
        if target.parent != artifact_dir or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {artifact_name}")
        return target

    def apply_strategy(
        self,
        run_id: str,
        strategy_id: str,
        child_run_id: str | None = None,
    ) -> Path:
        source = self._run_dir(run_id)
        state = read_json(source / "run_state.json")
        if state["status"] != "completed":
            raise HarnessError("optimization strategies require a completed parent run")
        proposals = self.strategies(run_id)["strategies"]
        proposal = next(
            (item for item in proposals if item["strategy_id"] == strategy_id),
            None,
        )
        if proposal is None:
            raise ContractError(f"unknown strategy: {strategy_id}")
        if not proposal["actionable"]:
            raise ContractError(f"strategy requires external input: {strategy_id}")

        contract = read_json(source / "task_contract.json")
        history = list(contract.get("optimization_history", []))
        max_iterations = int(
            contract.get("optimization", {}).get("max_iterations", 3)
        )
        if len(history) >= max_iterations:
            raise ContractError(
                f"optimization iteration limit reached: {max_iterations}"
            )
        plugin = self.registry.get_recipe(str(contract["recipe"]))
        updated = plugin.apply_strategy(deepcopy(contract), strategy_id)
        updated["optimization_history"] = [
            *history,
            {
                "parent_run_id": run_id,
                "strategy_id": strategy_id,
                "decision": "approved",
            },
        ]
        child = self.submit(
            updated,
            run_id=child_run_id,
            parent_run_id=run_id,
        )
        parent_state = RunState.load(source)
        parent_state.event(
            "optimization.strategy_approved",
            {"strategy_id": strategy_id, "child_run_id": child.name},
            stage="completed",
        )
        return child

    def close(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id:
            raise HarnessError(f"invalid run id: {run_id!r}")
        run_dir = (self.runs_dir / run_id).resolve()
        if run_dir.parent != self.runs_dir or not run_dir.is_dir():
            raise FileNotFoundError(f"run not found: {run_id}")
        return run_dir

    def __enter__(self) -> RunService:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
