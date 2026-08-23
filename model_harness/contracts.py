from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ContractError, PluginError
from .plugins import PluginRegistry, default_registry

SUPPORTED_MODES = {"delegate", "guided"}


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


def validate_contract(
    data: dict[str, Any],
    registry: PluginRegistry | None = None,
) -> None:
    if not isinstance(data, dict):
        raise ContractError("contract root must be an object")
    _require_nonempty_text(data, "task_id")
    _require_nonempty_text(data, "business_goal")
    recipe = _require_nonempty_text(data, "recipe")
    selected_registry = registry or default_registry()
    try:
        plugin = selected_registry.get_recipe(recipe)
    except PluginError as exc:
        raise ContractError(str(exc)) from exc

    interaction = _require_mapping(data, "interaction")
    mode = _require_nonempty_text(interaction, "mode")
    if mode not in SUPPORTED_MODES:
        raise ContractError(
            f"interaction.mode must be one of {sorted(SUPPORTED_MODES)}"
        )

    human_gates = data.get("human_gates")
    if not isinstance(human_gates, list) or not human_gates:
        raise ContractError("human_gates must be a non-empty list")

    optimization = data.get("optimization", {})
    if not isinstance(optimization, dict):
        raise ContractError("optimization must be an object")
    if optimization.get("mode", "recommend") != "recommend":
        raise ContractError("v0.2 supports optimization.mode=recommend only")
    if optimization.get("require_approval", True) is not True:
        raise ContractError("v0.2 requires optimization.require_approval=true")
    if "max_iterations" in optimization and (
        not isinstance(optimization["max_iterations"], int)
        or optimization["max_iterations"] < 0
    ):
        raise ContractError("optimization.max_iterations must be a non-negative integer")

    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise ContractError("diagnostics must be an object")
    if "minimum_test_samples" in diagnostics:
        value = diagnostics["minimum_test_samples"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 20:
            raise ContractError(
                "diagnostics.minimum_test_samples must be an integer >= 20"
            )

    plugin.validate_contract(data)


def load_contract(
    path: str | Path,
    registry: PluginRegistry | None = None,
) -> TaskContract:
    contract_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"contract not found: {contract_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    validate_contract(raw, registry=registry)
    return TaskContract(path=contract_path, raw=raw)
