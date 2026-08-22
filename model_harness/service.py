from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from .evidence import (
    ArtifactBundleBuilder,
    EvidenceRepository,
    EvaluationReport,
    InferenceCheck,
)
from .errors import ContractError, HarnessError
from .io_utils import read_json
from .plugins import PluginRegistry, default_registry
from .runner import execute_run, prepare_run
from .sample_inference import SampleInference
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
        evaluation_report = None
        evaluation_report_error = None
        if state.get("status") == "completed":
            try:
                evaluation_report = self.evaluation_report(run_id)
            except Exception as exc:
                evaluation_report_error = f"{type(exc).__name__}: {exc}"
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
            "cancel_requested": bool(state.get("cancel_requested", False)),
            "cancel_reason": state.get("cancel_reason"),
            "parent_run_id": state.get("parent_run_id"),
            "child_run_ids": child_run_ids,
            "offline_gates_passed": state.get("offline_gates_passed"),
            "run_status": state["status"],
            "integrity_status": (
                evaluation_report.get("integrity_status")
                if evaluation_report
                else "not_evaluated"
            ),
            "metric_gate_status": (
                evaluation_report.get("metric_gate_status")
                if evaluation_report
                else "not_evaluated"
            ),
            "evidence_status": (
                evaluation_report.get("evidence_status")
                if evaluation_report
                else "not_evaluated"
            ),
            "evaluation_conclusion": (
                evaluation_report.get("conclusion")
                if evaluation_report
                else "not_evaluated"
            ),
            "release_ready": bool(
                evaluation_report and evaluation_report.get("release_ready")
            ),
            "evaluation_report": evaluation_report,
            "evaluation_report_error": evaluation_report_error,
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

    def evaluation_report(
        self,
        run_id: str,
        *,
        rebuild: bool = False,
        minimum_test_samples: int = 20,
    ) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        reports = EvaluationReport(run_dir)
        existing = reports.get(required=False)
        if existing is not None and not rebuild:
            persisted_minimum = existing.get("minimum_test_samples")
            if (
                isinstance(persisted_minimum, int)
                and not isinstance(persisted_minimum, bool)
                and persisted_minimum > 0
            ):
                minimum_test_samples = persisted_minimum
        metrics_path = run_dir / "artifacts" / "metrics.json"
        metrics = read_json(metrics_path) if metrics_path.is_file() else {}
        return reports.build(
            minimum_test_samples=minimum_test_samples,
            test_contaminated=bool(
                isinstance(metrics, dict) and metrics.get("test_contaminated")
            ),
        )

    def inference_check(
        self,
        run_id: str,
        reference: dict[str, Any],
    ) -> dict[str, Any]:
        return InferenceCheck(self._run_dir(run_id)).run(reference)

    def inference_checks(self, run_id: str) -> list[dict[str, Any]]:
        return InferenceCheck(self._run_dir(run_id)).list()

    def sample_inference(
        self,
        run_id: str,
        sample: str | Path | dict[str, Any],
        *,
        sample_type: str | None = None,
        expected: Any | None = None,
    ) -> dict[str, Any]:
        return SampleInference(self._run_dir(run_id)).run(
            sample,
            sample_type=sample_type,
            expected=expected,
        )

    def sample_inference_checks(self, run_id: str) -> list[dict[str, Any]]:
        return SampleInference(self._run_dir(run_id)).list()

    def sample_inference_check(
        self,
        run_id: str,
        check_id: str,
    ) -> dict[str, Any]:
        return SampleInference(self._run_dir(run_id)).get(check_id)

    def build_artifact_bundle(
        self,
        run_id: str,
        *,
        inference_check_id: str | None = None,
    ) -> dict[str, Any]:
        return ArtifactBundleBuilder(self._run_dir(run_id)).build(
            inference_check_id=inference_check_id
        )

    def artifact_bundles(self, run_id: str) -> list[dict[str, Any]]:
        return ArtifactBundleBuilder(self._run_dir(run_id)).list()

    def artifact_bundle_path(self, run_id: str, bundle_id: str) -> Path:
        return ArtifactBundleBuilder(self._run_dir(run_id)).bundle_path(bundle_id)

    def evidence_report(self, run_id: str) -> dict[str, Any]:
        return EvidenceRepository(self._run_dir(run_id)).report()

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
        strategy_document = self.strategies(run_id)
        proposals = strategy_document["strategies"]
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
        proposal_provenance = proposal.get("evidence_provenance")
        if isinstance(proposal_provenance, dict):
            uses_test_evidence = bool(
                proposal_provenance.get("uses_test_evidence")
            )
            provenance_reasons = [
                str(value)
                for value in proposal_provenance.get(
                    "contamination_reasons",
                    [],
                )
                if str(value).strip()
            ]
        else:
            # An older proposal without provenance cannot be assumed clean.
            uses_test_evidence = True
            provenance_reasons = [
                "optimization proposal has no evidence provenance"
            ]
        parent_policy = contract.get("evidence_policy", {})
        parent_contaminated = bool(
            isinstance(parent_policy, dict)
            and parent_policy.get("test_contaminated")
        )
        parent_reasons = (
            [
                str(value)
                for value in parent_policy.get("contamination_reasons", [])
                if str(value).strip()
            ]
            if isinstance(parent_policy, dict)
            else []
        )
        contaminated = bool(parent_contaminated or uses_test_evidence)
        contamination_reasons = list(
            dict.fromkeys([*parent_reasons, *provenance_reasons])
        )
        updated["evidence_policy"] = {
            "test_contaminated": contaminated,
            "contamination_reasons": contamination_reasons,
            "source_run_ids": list(
                dict.fromkeys(
                    [
                        *(
                            parent_policy.get("source_run_ids", [])
                            if isinstance(parent_policy, dict)
                            else []
                        ),
                        run_id,
                    ]
                )
            ),
            "optimization_strategy_id": strategy_id,
        }
        updated["optimization_history"] = [
            *history,
            {
                "parent_run_id": run_id,
                "strategy_id": strategy_id,
                "decision": "approved",
                "evidence_provenance": proposal_provenance,
                "test_contaminated": contaminated,
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
            {
                "strategy_id": strategy_id,
                "child_run_id": child.name,
                "test_contaminated": contaminated,
                "contamination_reasons": contamination_reasons,
            },
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
