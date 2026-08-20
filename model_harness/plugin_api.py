from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RecipeManifest:
    plugin_id: str
    version: str
    contract_schema_version: str
    description: str
    task_type: str
    input_description: str
    output_description: str
    device: str
    purpose: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyProposal:
    strategy_id: str
    title: str
    hypothesis: str
    changes: tuple[str, ...]
    expected_effect: str
    estimated_cost: str
    risk: str
    requires_approval: bool
    actionable: bool
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["changes"] = list(self.changes)
        return value


@runtime_checkable
class RecipePlugin(Protocol):
    manifest: RecipeManifest

    def template(self) -> dict[str, Any]: ...

    def validate_contract(self, contract: dict[str, Any]) -> None: ...

    def train(self, contract: dict[str, Any]) -> Any: ...

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any: ...

    def package(
        self,
        training: Any,
        evaluation: Any,
        contract: dict[str, Any],
        artifact_dir: Path,
    ) -> dict[str, Any]: ...

    def propose_strategies(
        self,
        metrics: dict[str, Any],
        contract: dict[str, Any],
    ) -> list[StrategyProposal]: ...

    def apply_strategy(
        self,
        contract: dict[str, Any],
        strategy_id: str,
    ) -> dict[str, Any]: ...

    def learning_report(
        self,
        contract: dict[str, Any],
        metrics: dict[str, Any],
        strategies: list[StrategyProposal],
    ) -> str: ...

    def deep_verify(self, artifact_dir: Path) -> list[str]: ...
