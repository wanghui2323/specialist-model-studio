from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ..errors import ContractError
from ..io_utils import read_json
from ..plugin_api import RecipeManifest, StrategyProposal
from . import tabular_regression


TABULAR_REGRESSION_TEMPLATE: dict[str, Any] = {
    "schema_version": "0.2",
    "task_id": "custom-tabular-regression",
    "business_goal": "使用自己的表格数据训练一个轻量数值预测模型",
    "recipe": "tabular-regression",
    "interaction": {
        "mode": "delegate",
        "learning_report": True,
        "pause_when": [
            "missing_required_data",
            "data_authorization_unclear",
            "target_not_reviewed",
            "release_gate_change_requested",
            "production_release_requested",
        ],
    },
    "dataset": {
        "kind": "tabular_csv",
        "dataset_id": "",
        "root": "",
        "csv_path": "",
        "manifest_path": "",
        "report_path": "",
        "fingerprint_sha256": "",
        "target_column": "",
        "feature_columns": [],
        "numeric_columns": [],
        "categorical_columns": [],
        "ignored_columns": [],
        "random_seed": 42,
        "split": {"train": 0.60, "validation": 0.20, "test": 0.20},
        "boundary": "随机行划分不能证明跨时间、地点、机器或人群泛化",
    },
    "model_selection": {
        "primary_metric": "validation_mae",
        "candidates": ["mean_baseline", "ridge", "random_forest", "extra_trees"],
        "test_set_policy": "测试集不得用于模型选择或调参，只在候选模型确定并重训后评估",
    },
    "recipe_options": {"forest_estimators": 180},
    "optimization": {"mode": "recommend", "max_iterations": 3, "require_approval": True},
    "release_gates": {
        "clean_test_mae_max": 0.80,
        "clean_test_rmse_max": 1.10,
        "clean_test_r2_min": 0.20,
        "model_size_mb_max": 50.0,
        "single_sample_p95_latency_ms_max": 100.0,
    },
    "diagnostics": {"failure_sample_limit": 24},
    "compute_budget": {"max_candidate_models": 4, "max_rows": 200000, "device": "cpu"},
    "human_gates": [
        "确认数据已授权且必要时脱敏",
        "确认目标列、特征列和泄漏风险",
        "确认离线验收门槛",
        "审查高误差样本",
        "批准下一轮优化",
        "批准生产发布",
    ],
}


SUPPORTED_CANDIDATES = {"mean_baseline", "ridge", "random_forest", "extra_trees"}


class TabularRegressionPlugin:
    manifest = RecipeManifest(
        plugin_id="tabular-regression",
        version="0.1.0",
        contract_schema_version="0.2",
        description="Train and evaluate lightweight regression models on a user-provided CSV.",
        task_type="tabular-regression",
        input_description="A UTF-8 CSV with a declared numeric target column and at least 30 valid rows.",
        output_description="A trusted local Joblib pipeline, regression metrics, high-error rows and model card.",
        device="cpu",
        purpose="real user-data prediction loop",
        modalities=("tabular",),
        objectives=("regression",),
        data_adapter="tabular-csv",
        target_kinds=("numeric",),
        capability_tags=("prediction", "csv", "regression", "user-data", "lightweight"),
    )

    def template(self) -> dict[str, Any]:
        return deepcopy(TABULAR_REGRESSION_TEMPLATE)

    def validate_contract(self, contract: dict[str, Any]) -> None:
        dataset = contract.get("dataset")
        if not isinstance(dataset, dict) or dataset.get("kind") != "tabular_csv":
            raise ContractError("tabular-regression requires dataset.kind=tabular_csv")
        for key in ("root", "csv_path", "manifest_path", "report_path"):
            value = dataset.get(key)
            if not isinstance(value, str) or not value:
                raise ContractError(f"dataset.{key} is required")
            path = Path(value).expanduser().resolve()
            if key == "root" and not path.is_dir():
                raise ContractError("dataset.root is not a readable directory")
            if key != "root" and not path.is_file():
                raise ContractError(f"dataset.{key} is not a readable file")
        report = read_json(Path(dataset["report_path"]))
        if report.get("fingerprint_sha256") != dataset.get("fingerprint_sha256"):
            raise ContractError("dataset fingerprint does not match the inspected report")
        if report.get("target_kind") != "numeric":
            raise ContractError("tabular-regression requires a numeric target")
        if int(report.get("row_count", 0)) < 30:
            raise ContractError("tabular-regression requires at least 30 valid rows")
        feature_columns = dataset.get("feature_columns")
        if not isinstance(feature_columns, list) or not feature_columns:
            raise ContractError("dataset.feature_columns must be a non-empty list")
        if dataset.get("target_column") in feature_columns:
            raise ContractError("target column must not be included in feature columns")
        split = dataset.get("split")
        if not isinstance(split, dict):
            raise ContractError("dataset.split must be an object")
        ratios = [split.get(name) for name in ("train", "validation", "test")]
        if not all(isinstance(value, (int, float)) and value > 0 for value in ratios):
            raise ContractError("dataset split values must be positive numbers")
        if abs(sum(float(value) for value in ratios) - 1.0) > 1e-9:
            raise ContractError("dataset split train+validation+test must equal 1.0")
        if not isinstance(dataset.get("random_seed"), int):
            raise ContractError("dataset.random_seed must be an integer")

        selection = contract.get("model_selection")
        if not isinstance(selection, dict) or selection.get("primary_metric") != "validation_mae":
            raise ContractError("primary metric must be validation_mae")
        candidates = selection.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ContractError("model_selection.candidates must be a non-empty list")
        unknown = sorted(set(candidates) - SUPPORTED_CANDIDATES)
        if unknown:
            raise ContractError(f"unsupported candidate models: {unknown}")
        options = contract.get("recipe_options")
        if not isinstance(options, dict) or not isinstance(options.get("forest_estimators"), int):
            raise ContractError("recipe_options.forest_estimators must be an integer")
        if not 50 <= int(options["forest_estimators"]) <= 1000:
            raise ContractError("forest_estimators must be between 50 and 1000")
        gates = contract.get("release_gates")
        required_gates = {
            "clean_test_mae_max",
            "clean_test_rmse_max",
            "clean_test_r2_min",
            "model_size_mb_max",
            "single_sample_p95_latency_ms_max",
        }
        if not isinstance(gates, dict) or not required_gates.issubset(gates):
            raise ContractError("release_gates are incomplete")
        if not all(isinstance(gates[key], (int, float)) for key in required_gates):
            raise ContractError("all release gate values must be numeric")
        budget = contract.get("compute_budget")
        if not isinstance(budget, dict) or len(candidates) > int(budget.get("max_candidate_models", 0)):
            raise ContractError("candidate count exceeds compute budget")
        if int(report["row_count"]) > int(budget.get("max_rows", 0)):
            raise ContractError("dataset row count exceeds compute budget")

    def train(self, contract: dict[str, Any]) -> Any:
        return tabular_regression.train(contract)

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any:
        return tabular_regression.evaluate(training, contract)

    def package(self, training: Any, evaluation: Any, contract: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
        return tabular_regression.package(training, evaluation, contract, artifact_dir)

    def propose_strategies(self, metrics: dict[str, Any], contract: dict[str, Any]) -> list[StrategyProposal]:
        strategies: list[StrategyProposal] = []
        current = int(contract["recipe_options"]["forest_estimators"])
        if metrics["clean_test"]["r2"] < 0.65 and current < 320:
            strategies.append(
                StrategyProposal(
                    strategy_id="increase-forest-capacity",
                    title="增加树模型容量",
                    hypothesis="当前验证误差可能来自树模型容量不足。",
                    changes=(f"forest_estimators从{current}调整为320",),
                    expected_effect="可能降低非线性数据的MAE，但增加训练时间和模型大小。",
                    estimated_cost="medium",
                    risk="medium",
                    requires_approval=True,
                    actionable=True,
                    evidence={"current_r2": metrics["clean_test"]["r2"], "current_estimators": current},
                )
            )
        strategies.append(
            StrategyProposal(
                strategy_id="review-high-error-rows",
                title="复核高误差样本与时间/分组泄漏",
                hypothesis="最大误差可能来自异常值、不可见分组或训练分布未覆盖。",
                changes=("复核failure_samples.json", "按业务分组或时间重做独立测试", "检查目标泄漏"),
                expected_effect="判断当前误差来自数据边界还是模型容量。",
                estimated_cost="medium",
                risk="requires-data-review",
                requires_approval=True,
                actionable=False,
                evidence={"failure_count": metrics["failure_count"], "test_mae": metrics["clean_test"]["mae"]},
            )
        )
        return strategies

    def apply_strategy(self, contract: dict[str, Any], strategy_id: str) -> dict[str, Any]:
        if strategy_id != "increase-forest-capacity":
            raise ContractError(f"strategy is not automatically actionable: {strategy_id}")
        updated = deepcopy(contract)
        updated["recipe_options"]["forest_estimators"] = 320
        return updated

    def learning_report(self, contract: dict[str, Any], metrics: dict[str, Any], strategies: list[StrategyProposal]) -> str:
        return tabular_regression.learning_report(contract, metrics, strategies)

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        bundle = joblib.load(artifact_dir / "model.joblib")
        reference = joblib.load(artifact_dir / "test_reference.joblib")
        actual = bundle["estimator"].predict(reference["X"])
        if not np.allclose(actual, reference["predictions"], rtol=1e-9, atol=1e-9):
            return ["persisted model predictions do not match reference"]
        return []


PLUGIN = TabularRegressionPlugin()
