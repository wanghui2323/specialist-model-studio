from __future__ import annotations

import platform
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import sklearn

from .contracts import load_contract, validate_contract
from .errors import ContractError, RunCancelled
from .evidence import EvaluationReport
from .io_utils import read_json, sha256_file, write_json
from .optimization import attach_provenance, propose_strategies_with_provenance
from .plugins import PluginRegistry, default_registry
from .state import RunState


CancelCheck = Callable[[], bool]


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return slug or "model-run"


def new_run_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{_safe_slug(task_id)}"


def _resolve_contract(
    contract: str | Path | dict[str, Any],
    registry: PluginRegistry,
) -> dict[str, Any]:
    if isinstance(contract, dict):
        raw = deepcopy(contract)
        validate_contract(raw, registry=registry)
        return raw
    return load_contract(contract, registry=registry).raw


def _write_manifest(
    run_dir: Path,
    contract: dict[str, Any],
    artifact_dir: Path,
    state: RunState,
    plugin_version: str,
) -> dict[str, Any]:
    artifacts = {
        path.relative_to(artifact_dir).as_posix(): {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(artifact_dir.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    manifest = {
        "schema_version": "0.2",
        "task_id": contract["task_id"],
        "run_id": state.data["run_id"],
        "parent_run_id": state.data.get("parent_run_id"),
        "recipe": contract["recipe"],
        "plugin_version": plugin_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "contract_snapshot_sha256": sha256_file(run_dir / "task_contract.json"),
        "artifacts": artifacts,
        "reproduce": "specialist-model-studio run <task_contract.json>",
    }
    write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def prepare_run(
    contract: str | Path | dict[str, Any],
    runs_dir: str | Path = "runs",
    run_id: str | None = None,
    registry: PluginRegistry | None = None,
    parent_run_id: str | None = None,
    workspace_task_id: str | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    selected_registry = registry or default_registry()
    raw = _resolve_contract(contract, selected_registry)
    plugin = selected_registry.get_recipe(str(raw["recipe"]))
    resolved_runs_dir = Path(runs_dir).expanduser().resolve()
    contract_task_id = str(raw["task_id"])
    resolved_workspace_root = (
        Path(workspace_root).expanduser().resolve()
        if workspace_root is not None
        else resolved_runs_dir / "_workspace"
    )
    owned_task_path = resolved_workspace_root / "tasks" / contract_task_id / "task.json"
    if workspace_task_id is not None and workspace_task_id != contract_task_id:
        raise ContractError("workspace task authorization does not match contract task_id")
    if owned_task_path.is_file() and workspace_task_id != contract_task_id:
        raise ContractError(
            "workspace-owned tasks can only create runs through TrainingWorkspace"
        )
    if workspace_task_id is not None and not owned_task_path.is_file():
        raise ContractError("workspace task authorization references an unknown task")
    selected_run_id = _safe_slug(run_id or new_run_id(contract_task_id))
    run_dir = resolved_runs_dir / selected_run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    state = RunState(
        run_dir,
        str(raw["task_id"]),
        selected_run_id,
        plugin.manifest.plugin_id,
        parent_run_id=parent_run_id,
    )
    write_json(run_dir / "task_contract.json", raw)
    state.transition("queued")
    state.event(
        "run.queued",
        {
            "recipe": raw["recipe"],
            "mode": raw["interaction"]["mode"],
            "parent_run_id": parent_run_id,
        },
    )
    return run_dir


def _check_cancel(state: RunState, cancel_check: CancelCheck | None) -> None:
    persisted = read_json(state.state_path)
    requested = bool(persisted.get("cancel_requested"))
    externally_requested = bool(cancel_check and cancel_check())
    if requested or externally_requested:
        reason = str(persisted.get("cancel_reason", "requested by user"))
        state.data = persisted
        raise RunCancelled(reason)


def execute_run(
    run_dir: str | Path,
    registry: PluginRegistry | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    resolved = Path(run_dir).expanduser().resolve()
    selected_registry = registry or default_registry()
    state = RunState.load(resolved)
    if state.status != "queued":
        raise RuntimeError(f"run must be queued before execution, got {state.status}")
    raw = read_json(resolved / "task_contract.json")
    validate_contract(raw, registry=selected_registry)
    plugin = selected_registry.get_recipe(str(raw["recipe"]))
    run_started = time.perf_counter()
    timings_ms: dict[str, float] = {}
    try:
        _check_cancel(state, cancel_check)
        stage_started = time.perf_counter()
        state.transition("preflight")
        timings_ms["preflight"] = (time.perf_counter() - stage_started) * 1000
        state.event(
            "preflight.completed",
            {
                "recipe": raw["recipe"],
                "mode": raw["interaction"]["mode"],
                "candidate_count": len(raw["model_selection"]["candidates"]),
                "duration_ms": timings_ms["preflight"],
            },
        )

        _check_cancel(state, cancel_check)
        state.transition("training")
        stage_started = time.perf_counter()
        training = plugin.train(raw)
        timings_ms["training"] = (time.perf_counter() - stage_started) * 1000
        candidate_results = getattr(training, "validation_results", {})
        state.event(
            "training.candidates_completed",
            {
                "duration_ms": timings_ms["training"],
                "candidates": [
                    {
                        "name": name,
                        "macro_f1": values.get("macro_f1"),
                        "accuracy": values.get("accuracy"),
                        "mae": values.get("mae"),
                        "rmse": values.get("rmse"),
                        "r2": values.get("r2"),
                        "fit_seconds": values.get("fit_seconds"),
                    }
                    for name, values in candidate_results.items()
                ],
            },
        )
        state.event(
            "training.model_selected",
            {
                "selected_model": training.selected_name,
                "selection_metric": raw["model_selection"]["primary_metric"],
                "duration_ms": timings_ms["training"],
            },
        )

        _check_cancel(state, cancel_check)
        state.transition("evaluating")
        stage_started = time.perf_counter()
        evaluation = plugin.evaluate(training, raw)
        evidence_policy = raw.get("evidence_policy", {})
        inherited_contamination = bool(
            isinstance(evidence_policy, dict)
            and evidence_policy.get("test_contaminated")
        )
        contamination_reasons = (
            [
                str(value)
                for value in evidence_policy.get("contamination_reasons", [])
                if str(value).strip()
            ]
            if isinstance(evidence_policy, dict)
            else []
        )
        evaluation.metrics["test_contaminated"] = bool(
            inherited_contamination
            or evaluation.metrics.get("test_contaminated", False)
        )
        evaluation.metrics["contamination_reasons"] = contamination_reasons
        timings_ms["evaluating"] = (time.perf_counter() - stage_started) * 1000
        state.event(
            "evaluation.completed",
            {
                "clean_test": evaluation.metrics["clean_test"],
                "clean_test_accuracy": evaluation.metrics["clean_test"].get("accuracy"),
                "stress_tests": list(evaluation.metrics.get("stress_tests", {})),
                "failure_count": evaluation.metrics.get("failure_count"),
                "duration_ms": timings_ms["evaluating"],
            },
        )

        _check_cancel(state, cancel_check)
        state.transition("proposing")
        stage_started = time.perf_counter()
        strategies, optimization_provenance = propose_strategies_with_provenance(
            plugin,
            evaluation.metrics,
            raw,
        )
        timings_ms["proposing"] = (time.perf_counter() - stage_started) * 1000
        state.event(
            "optimization.strategies_proposed",
            {
                "strategy_count": len(strategies),
                "actionable_count": sum(item.actionable for item in strategies),
                "test_evidence_used": optimization_provenance[
                    "uses_test_evidence"
                ],
                "duration_ms": timings_ms["proposing"],
            },
        )

        _check_cancel(state, cancel_check)
        state.transition("packaging")
        stage_started = time.perf_counter()
        artifact_dir = resolved / "artifacts"
        metrics = plugin.package(training, evaluation, raw, artifact_dir)
        write_json(
            artifact_dir / "optimization_strategies.json",
            {
                "schema_version": "0.2",
                "run_id": state.data["run_id"],
                "plugin_id": plugin.manifest.plugin_id,
                "mode": raw.get("optimization", {}).get("mode", "recommend"),
                "require_approval": raw.get("optimization", {}).get(
                    "require_approval", True
                ),
                "evidence_provenance": optimization_provenance,
                "strategies": [
                    attach_provenance(item, optimization_provenance)
                    for item in strategies
                ],
            },
        )
        (artifact_dir / "learning_report.md").write_text(
            plugin.learning_report(raw, metrics, strategies),
            encoding="utf-8",
        )
        manifest = _write_manifest(
            resolved,
            raw,
            artifact_dir,
            state,
            plugin.manifest.version,
        )
        timings_ms["packaging"] = (time.perf_counter() - stage_started) * 1000
        state.event(
            "artifacts.packaged",
            {
                "artifact_count": len(manifest["artifacts"]),
                "offline_gates_passed": metrics["gate_checks"][
                    "all_offline_gates_passed"
                ],
                "duration_ms": timings_ms["packaging"],
            },
        )
        total_duration_ms = (time.perf_counter() - run_started) * 1000
        state.transition(
            "completed",
            offline_gates_passed=metrics["gate_checks"][
                "all_offline_gates_passed"
            ],
            artifact_count=len(manifest["artifacts"]),
            timings_ms=timings_ms,
            total_duration_ms=total_duration_ms,
        )
        minimum_test_samples = raw.get("diagnostics", {}).get(
            "minimum_test_samples",
            20,
        )
        if (
            isinstance(minimum_test_samples, bool)
            or not isinstance(minimum_test_samples, int)
            or minimum_test_samples <= 0
        ):
            minimum_test_samples = 20
        try:
            EvaluationReport(resolved).build(
                minimum_test_samples=minimum_test_samples,
                test_contaminated=bool(
                    evaluation.metrics.get("test_contaminated", False)
                ),
            )
        except Exception as exc:
            # Evidence failure must remain visible without rewriting a genuinely
            # completed training Run as a training failure.
            state.event(
                "evidence.evaluation_report_failed",
                {"error": f"{type(exc).__name__}: {exc}"},
                stage="completed",
            )
        return resolved
    except RunCancelled as exc:
        state.cancel(str(exc))
        return resolved
    except Exception as exc:
        state.fail(f"{type(exc).__name__}: {exc}")
        raise


def run_task(
    contract_path: str | Path,
    runs_dir: str | Path = "runs",
    run_id: str | None = None,
    registry: PluginRegistry | None = None,
) -> Path:
    run_dir = prepare_run(
        contract_path,
        runs_dir=runs_dir,
        run_id=run_id,
        registry=registry,
    )
    return execute_run(run_dir, registry=registry)


def verify_run(
    run_dir: str | Path,
    deep: bool = False,
    registry: PluginRegistry | None = None,
) -> dict[str, Any]:
    resolved = Path(run_dir).expanduser().resolve()
    manifest = read_json(resolved / "run_manifest.json")
    state = read_json(resolved / "run_state.json")
    integrity_errors: list[str] = []
    quality_errors: list[str] = []
    if state.get("status") != "completed":
        integrity_errors.append(
            f"run status is {state.get('status')}, expected completed"
        )
    contract_path = resolved / "task_contract.json"
    if sha256_file(contract_path) != manifest["contract_snapshot_sha256"]:
        integrity_errors.append("task contract hash mismatch")
    artifact_dir = resolved / "artifacts"
    for name, expected in manifest["artifacts"].items():
        path = artifact_dir / name
        if not path.is_file():
            integrity_errors.append(f"missing artifact: {name}")
            continue
        if sha256_file(path) != expected["sha256"]:
            integrity_errors.append(f"artifact hash mismatch: {name}")

    metrics_path = artifact_dir / "metrics.json"
    metric_gate_status = "not_evaluated"
    if metrics_path.is_file():
        metrics = read_json(metrics_path)
        if not metrics["gate_checks"]["all_offline_gates_passed"]:
            quality_errors.append("one or more offline gates failed")
            metric_gate_status = "failed"
        else:
            metric_gate_status = "passed"

    deep_verified = False
    if deep and not integrity_errors:
        selected_registry = registry or default_registry()
        plugin = selected_registry.get_recipe(str(manifest["recipe"]))
        plugin_errors = plugin.deep_verify(artifact_dir)
        integrity_errors.extend(plugin_errors)
        deep_verified = not plugin_errors

    report_path = resolved / "evidence" / "evaluation_report.json"
    evaluation_report = read_json(report_path) if report_path.is_file() else None

    return {
        "run_dir": str(resolved),
        "ok": not integrity_errors,
        "integrity_status": "passed" if not integrity_errors else "failed",
        "metric_gate_status": metric_gate_status,
        "release_ready": bool(
            not integrity_errors
            and metric_gate_status == "passed"
            and evaluation_report
            and evaluation_report.get("release_ready")
        ),
        "deep_verified": deep_verified,
        "errors": integrity_errors,
        "quality_errors": quality_errors,
        "evaluation_report": evaluation_report,
        "artifact_count": len(manifest.get("artifacts", {})),
    }


def initialize_workspace(
    recipe: str,
    output: str | Path,
    force: bool = False,
    registry: PluginRegistry | None = None,
) -> Path:
    from .templates import get_template

    output_dir = Path(output).expanduser().resolve()
    contract_path = output_dir / "task_contract.json"
    if contract_path.exists() and not force:
        raise FileExistsError(f"contract already exists: {contract_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(contract_path, get_template(recipe, registry=registry))
    return contract_path
