from __future__ import annotations

"""Compile a reviewable V3 plan from one immutable source analysis.

The compiler is deliberately static: it consumes only persisted TaskSpec,
SourceSnapshot and RepositoryAnalysis facts and never imports or executes the
third-party repository.  Its output fits the existing TrainingPlanRevision
schema while carrying the evidence that explains each proposed choice.
"""

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .errors import ContractError


GIB = 1024**3
WEIGHT_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".gguf",
    ".h5",
    ".joblib",
    ".keras",
    ".onnx",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return deepcopy(dict(value))


def _sequence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _names(items: Any, field: str = "name") -> list[str]:
    result: list[str] = []
    for item in _sequence(items):
        value = str(item.get(field) or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _evidence_refs(items: Any) -> list[str]:
    refs: list[str] = []
    for item in _sequence(items):
        values = item.get("evidence_refs")
        if not isinstance(values, list):
            continue
        for value in values:
            selected = str(value or "").strip()
            if selected and selected not in refs:
                refs.append(selected)
    return refs


def _resource_estimate(snapshot: Mapping[str, Any]) -> dict[str, int]:
    known_bytes = 0
    weight_bytes = 0
    for item in _sequence(snapshot.get("files")):
        value = item.get("size_bytes")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        known_bytes += value
        if PurePosixPath(str(item.get("path") or "")).suffix.lower() in WEIGHT_SUFFIXES:
            weight_bytes += value
    ram = max(4 * GIB, weight_bytes * 2 + known_bytes + GIB)
    disk = max(5 * GIB, known_bytes * 3 + GIB)
    return {
        "max_seconds": 3600,
        "ram_bytes": ram,
        "vram_bytes": 0,
        "disk_bytes": disk,
    }


def _resource_estimate_basis(
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    known_bytes = 0
    known_weight_bytes = 0
    for item in _sequence(snapshot.get("files")):
        value = item.get("size_bytes")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        known_bytes += value
        if PurePosixPath(str(item.get("path") or "")).suffix.lower() in WEIGHT_SUFFIXES:
            known_weight_bytes += value
    external_models = _names(analysis.get("base_model_candidates"), "model_id")
    limitations = ["user_dataset_size_is_not_bound_to_the_source_snapshot"]
    if external_models:
        limitations.append("external_base_model_weight_size_is_not_verified")
    if known_weight_bytes == 0:
        limitations.append("no_in_snapshot_weight_bytes_were_observed")
    return {
        "method": "bounded_source_snapshot_heuristic/0.2",
        "status": "provisional",
        "known_snapshot_bytes": known_bytes,
        "known_weight_bytes": known_weight_bytes,
        "external_base_model_candidates": external_models,
        "limitations": limitations,
        "meaning": (
            "resource_budget is a reviewable planning bound, not a measured "
            "training requirement or environment qualification"
        ),
    }


def compile_training_plan(
    *,
    task_spec: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
    selected_entrypoint: str,
    hyperparameters: Mapping[str, Any] | None = None,
    resource_budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic plan fields backed by current static evidence."""

    selected_spec = _mapping(task_spec, "task spec")
    selected_snapshot = _mapping(snapshot, "source snapshot")
    selected_analysis = _mapping(analysis, "repository analysis")
    entrypoint = str(selected_entrypoint or "").strip()
    if not entrypoint or PurePosixPath(entrypoint).is_absolute() or ".." in PurePosixPath(entrypoint).parts:
        raise ContractError("selected entrypoint must be a safe repository-relative path")
    if PurePosixPath(entrypoint).suffix.lower() != ".py":
        raise ContractError(
            "V3 static plans currently support only analyzed Python training entrypoints"
        )
    files = {
        str(item.get("path")): item
        for item in _sequence(selected_snapshot.get("files"))
        if item.get("kind") in {"blob", "executable"}
    }
    if entrypoint not in files:
        raise ContractError("selected entrypoint is not in the immutable source snapshot")

    entrypoints = _sequence(selected_analysis.get("training_entrypoints"))
    selected_entry = next(
        (item for item in entrypoints if str(item.get("path")) == entrypoint),
        None,
    )
    if selected_entry is None:
        raise ContractError(
            "selected entrypoint is not an analyzed training entrypoint in this revision"
        )
    plan_basis = {
        "analyzer_version": selected_analysis.get("analyzer_version"),
        "resolved_commit": selected_analysis.get("resolved_commit"),
        "frameworks": _sequence(selected_analysis.get("frameworks")),
        "task_candidates": _sequence(selected_analysis.get("task_candidates")),
        "base_model_candidates": _sequence(
            selected_analysis.get("base_model_candidates")
        ),
        "dependency_files": _sequence(
            selected_analysis.get("dependency_files")
            or selected_analysis.get("dependency_manifests")
        ),
        "source_artifact_candidates": _sequence(selected_analysis.get("artifacts")),
        "resource_estimate_basis": _resource_estimate_basis(
            selected_snapshot,
            selected_analysis,
        ),
        "entrypoint_evidence": deepcopy(
            (selected_entry or {}).get("evidence")
            or (selected_entry or {}).get("evidence_refs")
            or []
        ),
    }
    data_contracts = _sequence(
        selected_analysis.get("data_contract_candidates")
        or selected_analysis.get("data_contract_hints")
    )
    manual_mapping = selected_analysis.get("manual_mapping")
    manual_mapping_value = (
        manual_mapping.get("mapping")
        if isinstance(manual_mapping, Mapping)
        and isinstance(manual_mapping.get("mapping"), Mapping)
        else {}
    )
    dataset_argument = str(
        manual_mapping_value.get("dataset_argument") or ""
    ).strip()
    analyzed_metrics = _names(selected_analysis.get("metrics"))
    capability = deepcopy(selected_spec.get("capability_request") or {})
    primary_metric = str(capability.get("primary_metric") or "").strip()
    metrics = [primary_metric] if primary_metric else analyzed_metrics
    if not metrics:
        raise ContractError(
            "repository analysis has no evidence-backed evaluation metric; manual mapping is required"
        )
    metric_evidence = _evidence_refs(selected_analysis.get("metrics"))
    if primary_metric:
        metric_evidence.insert(
            0,
            f"task_spec_revision:{selected_spec.get('revision', 'unknown')}:primary_metric",
        )
    budget = _resource_estimate(selected_snapshot)
    if resource_budget is not None:
        supplied_budget = _mapping(resource_budget, "resource budget")
        budget.update(supplied_budget)

    required_artifacts = ["trained-model", "metrics.json"]
    return {
        "entrypoint": {
            "argv": ["python", entrypoint],
            "working_dir": "/workspace/source",
        },
        "dataset_mapping": {
            "source": "current_task_spec",
            "capability": capability,
            "data_contract_candidates": data_contracts,
            "requires_user_data_contract": True,
            "entrypoint_argument": dataset_argument or None,
            "container_data_path": "/workspace/data",
            "plan_basis": plan_basis,
        },
        "hyperparameters": deepcopy(dict(hyperparameters or {})),
        "evaluation": {
            "metrics": metrics,
            "gates": {
                "requires_human_confirmation": True,
                "evidence_refs": metric_evidence,
                "analyzer_metric_candidates": analyzed_metrics,
            },
        },
        "artifact_contract": {
            "output_dir": "/workspace/output",
            "required": required_artifacts,
            "evidence_refs": [],
            "qualification": "output_paths_require_L3_build_or_manual_mapping",
        },
        "resource_budget": budget,
        "execution_policy": {
            "backend": "oci",
            "network_allowlist": [],
            "secret_scopes": [],
        },
    }
