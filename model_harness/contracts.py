from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_MODES = {"delegate", "guided"}
SUPPORTED_RECIPES = {"digit-classification"}
SUPPORTED_DIGIT_CANDIDATES = {
    "most_frequent_baseline",
    "logistic_regression",
    "rbf_svm",
    "random_forest",
}


class ContractError(ValueError):
    """Raised when a task contract is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class TaskContract:
    path: Path
    raw: dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw["task_id"])

    @property
    def mode(self) -> str:
        return str(self.raw["interaction"]["mode"])

    @property
    def recipe(self) -> str:
        return str(self.raw["recipe"])


def _require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"{key} must be an object")
    return value


def _require_nonempty_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be non-empty text")
    return value.strip()


def validate_contract(data: dict[str, Any]) -> None:
    _require_nonempty_text(data, "task_id")
    _require_nonempty_text(data, "business_goal")
    recipe = _require_nonempty_text(data, "recipe")
    if recipe not in SUPPORTED_RECIPES:
        raise ContractError(
            f"unsupported recipe: {recipe}; supported: {sorted(SUPPORTED_RECIPES)}"
        )

    interaction = _require_mapping(data, "interaction")
    mode = _require_nonempty_text(interaction, "mode")
    if mode not in SUPPORTED_MODES:
        raise ContractError(
            f"interaction.mode must be one of {sorted(SUPPORTED_MODES)}"
        )

    dataset = _require_mapping(data, "dataset")
    if dataset.get("kind") != "sklearn_builtin_digits":
        raise ContractError(
            "v0.1 digit-classification requires dataset.kind=sklearn_builtin_digits"
        )
    split = _require_mapping(dataset, "split")
    ratios = [split.get(name) for name in ("train", "validation", "test")]
    if not all(isinstance(value, (int, float)) and value > 0 for value in ratios):
        raise ContractError("dataset.split values must be positive numbers")
    if abs(sum(float(value) for value in ratios) - 1.0) > 1e-9:
        raise ContractError("dataset.split train+validation+test must equal 1.0")
    if not isinstance(dataset.get("random_seed"), int):
        raise ContractError("dataset.random_seed must be an integer")

    selection = _require_mapping(data, "model_selection")
    if selection.get("primary_metric") != "validation_macro_f1":
        raise ContractError(
            "v0.1 requires model_selection.primary_metric=validation_macro_f1"
        )
    candidates = selection.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ContractError("model_selection.candidates must be a non-empty list")
    unknown_candidates = sorted(set(candidates) - SUPPORTED_DIGIT_CANDIDATES)
    if unknown_candidates:
        raise ContractError(f"unsupported candidate models: {unknown_candidates}")

    gates = _require_mapping(data, "release_gates")
    required_gates = {
        "clean_test_accuracy_min",
        "clean_test_macro_f1_min",
        "clean_test_worst_class_recall_min",
        "model_size_mb_max",
        "single_sample_p95_latency_ms_max",
    }
    missing_gates = sorted(required_gates - set(gates))
    if missing_gates:
        raise ContractError(f"missing release gates: {missing_gates}")
    if not all(isinstance(gates[key], (int, float)) for key in required_gates):
        raise ContractError("all release gate values must be numeric")

    budget = _require_mapping(data, "compute_budget")
    if not isinstance(budget.get("max_candidate_models"), int):
        raise ContractError("compute_budget.max_candidate_models must be an integer")
    if len(candidates) > budget["max_candidate_models"]:
        raise ContractError("candidate count exceeds compute budget")

    human_gates = data.get("human_gates")
    if not isinstance(human_gates, list) or not human_gates:
        raise ContractError("human_gates must be a non-empty list")


def load_contract(path: str | Path) -> TaskContract:
    contract_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"contract not found: {contract_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError("contract root must be an object")
    validate_contract(raw)
    return TaskContract(path=contract_path, raw=raw)
