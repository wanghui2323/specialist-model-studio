from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import ContractError
from ..io_utils import read_json
from ..plugin_api import RecipeManifest, StrategyProposal


TABULAR_CLASSIFICATION_TEMPLATE: dict[str, Any] = {
    "schema_version": "0.2",
    "task_id": "custom-tabular-classification",
    "business_goal": "使用自己的表格数据训练一个轻量分类模型",
    "recipe": "tabular-classification",
    "interaction": {
        "mode": "delegate",
        "learning_report": True,
        "pause_when": [
            "missing_required_data",
            "data_authorization_unclear",
            "labels_not_reviewed",
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
        "boundary": "分层行划分不能证明跨时间、地点、机器或人群泛化",
    },
    "model_selection": {
        "primary_metric": "validation_macro_f1",
        "candidates": [
            "most_frequent_baseline",
            "logistic_regression",
            "random_forest",
            "extra_trees",
        ],
        "test_set_policy": "测试集不得用于模型选择或调参，只在候选模型确定并重训后评估",
    },
    "recipe_options": {"forest_estimators": 80, "class_weight_balanced": False},
    "optimization": {"mode": "recommend", "max_iterations": 3, "require_approval": True},
    "release_gates": {
        "clean_test_accuracy_min": 0.75,
        "clean_test_macro_f1_min": 0.75,
        "clean_test_worst_class_recall_min": 0.50,
        "model_size_mb_max": 50.0,
        "single_sample_p95_latency_ms_max": 100.0,
    },
    "diagnostics": {"failure_sample_limit": 24},
    "compute_budget": {"max_candidate_models": 4, "max_rows": 200000, "device": "cpu"},
    "human_gates": [
        "确认数据已授权且必要时脱敏",
        "确认目标类别和特征列",
        "确认离线验收门槛",
        "审查分错的样本",
        "批准下一轮优化",
        "批准生产发布",
    ],
}


SUPPORTED_CANDIDATES = {
    "most_frequent_baseline",
    "logistic_regression",
    "random_forest",
    "extra_trees",
}


def _class_counts(csv_path: Path, target_column: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or target_column not in reader.fieldnames:
            raise ContractError("分类目标列不在已导入的 CSV 中")
        for row in reader:
            label = str(row.get(target_column) or "").strip()
            if label:
                counts[label] += 1
    return counts


class TabularClassificationPlugin:
    manifest = RecipeManifest(
        plugin_id="tabular-classification",
        version="0.1.0",
        contract_schema_version="0.2",
        description="Train and evaluate lightweight classifiers on a user-provided CSV.",
        task_type="tabular-classification",
        input_description="A UTF-8 CSV with a declared categorical target and at least five rows in every class.",
        output_description="A trusted local Joblib pipeline, classification metrics, misclassified rows and model card.",
        device="cpu",
        purpose="real user-data classification loop",
        modalities=("tabular",),
        objectives=("classification",),
        data_adapter="tabular-csv",
        target_kinds=("binary", "multiclass"),
        capability_tags=("classification", "csv", "user-data", "lightweight"),
    )

    def template(self) -> dict[str, Any]:
        return deepcopy(TABULAR_CLASSIFICATION_TEMPLATE)

    def validate_contract(self, contract: dict[str, Any]) -> None:
        dataset = contract.get("dataset")
        if not isinstance(dataset, dict) or dataset.get("kind") != "tabular_csv":
            raise ContractError("tabular-classification requires dataset.kind=tabular_csv")
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
        if report.get("target_kind") != "categorical":
            raise ContractError("tabular-classification requires a categorical target")
        if int(report.get("row_count", 0)) < 30:
            raise ContractError("tabular-classification requires at least 30 valid rows")
        counts = _class_counts(Path(dataset["csv_path"]), str(dataset.get("target_column")))
        # Older inspected datasets lack this additive field. When supplied,
        # the Agent-visible count summary must agree with the actual CSV.
        if "class_counts" in report and report["class_counts"] != dict(counts):
            raise ContractError("分类类别数量与导入报告不一致，请重新导入以复查数据")
        if len(counts) < 2:
            raise ContractError("tabular-classification requires at least two classes")
        if min(counts.values()) < 5:
            raise ContractError("every class must contain at least five rows")
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
        if (
            not isinstance(selection, dict)
            or selection.get("primary_metric") != "validation_macro_f1"
        ):
            raise ContractError("primary metric must be validation_macro_f1")
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
        if not isinstance(options.get("class_weight_balanced"), bool):
            raise ContractError("recipe_options.class_weight_balanced must be boolean")
        gates = contract.get("release_gates")
        required_gates = {
            "clean_test_accuracy_min",
            "clean_test_macro_f1_min",
            "clean_test_worst_class_recall_min",
            "model_size_mb_max",
            "single_sample_p95_latency_ms_max",
        }
        if not isinstance(gates, dict) or not required_gates.issubset(gates):
            raise ContractError("release_gates are incomplete")
        if not all(isinstance(gates[key], (int, float)) for key in required_gates):
            raise ContractError("all release gate values must be numeric")
        for key in (
            "clean_test_accuracy_min",
            "clean_test_macro_f1_min",
            "clean_test_worst_class_recall_min",
        ):
            if not 0 <= float(gates[key]) <= 1:
                raise ContractError(f"{key} must be between 0 and 1")
        budget = contract.get("compute_budget")
        if not isinstance(budget, dict) or len(candidates) > int(budget.get("max_candidate_models", 0)):
            raise ContractError("candidate count exceeds compute budget")
        if int(report["row_count"]) > int(budget.get("max_rows", 0)):
            raise ContractError("dataset row count exceeds compute budget")

    def train(self, contract: dict[str, Any]) -> Any:
        from . import tabular_classification

        return tabular_classification.train(contract)

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any:
        from . import tabular_classification

        return tabular_classification.evaluate(training, contract)

    def package(
        self,
        training: Any,
        evaluation: Any,
        contract: dict[str, Any],
        artifact_dir: Path,
    ) -> dict[str, Any]:
        from . import tabular_classification

        return tabular_classification.package(training, evaluation, contract, artifact_dir)

    def propose_strategies(
        self,
        metrics: dict[str, Any],
        contract: dict[str, Any],
    ) -> list[StrategyProposal]:
        strategies: list[StrategyProposal] = []
        options = contract["recipe_options"]
        dataset = metrics["dataset"]
        if float(dataset["imbalance_ratio"]) >= 1.5 and not options["class_weight_balanced"]:
            strategies.append(
                StrategyProposal(
                    strategy_id="balance-class-weights",
                    title="启用类别平衡权重",
                    hypothesis="类别行数不均衡可能使模型偏向样本较多的类别。",
                    changes=("候选分类器启用 class_weight=balanced",),
                    expected_effect="优先改善少数类别召回，整体准确率可能小幅波动。",
                    estimated_cost="low",
                    risk="low",
                    requires_approval=True,
                    actionable=True,
                    evidence={
                        "imbalance_ratio": dataset["imbalance_ratio"],
                        "class_counts": dataset["class_counts"],
                    },
                )
            )
        selected = str(metrics["selected_model"])
        validation = metrics["validation_candidates"][selected]
        current = int(options["forest_estimators"])
        if float(validation["macro_f1"]) < 0.90 and current < 160:
            strategies.append(
                StrategyProposal(
                    strategy_id="increase-forest-capacity",
                    title="增加树模型容量",
                    hypothesis="验证集仍有分类错误，树模型容量可能不足。",
                    changes=(f"forest_estimators从{current}调整为160",),
                    expected_effect="可能提高非线性边界的验证 Macro-F1，同时增加训练时间和模型大小。",
                    estimated_cost="medium",
                    risk="medium",
                    requires_approval=True,
                    actionable=True,
                    evidence={
                        "validation_macro_f1": validation["macro_f1"],
                        "current_estimators": current,
                    },
                )
            )
        strategies.append(
            StrategyProposal(
                strategy_id="review-misclassified-rows",
                title="复核分错样本与分组泄漏",
                hypothesis="剩余错误可能来自错标、不可见分组或训练分布未覆盖。",
                changes=("复核分错行", "按业务分组重做独立测试", "检查目标泄漏"),
                expected_effect="判断当前误差来自数据边界还是模型容量。",
                estimated_cost="medium",
                risk="requires-data-review",
                requires_approval=True,
                actionable=False,
                evidence={
                    "validation_macro_f1": validation["macro_f1"],
                    "row_count": dataset["row_count"],
                },
            )
        )
        return strategies

    def apply_strategy(self, contract: dict[str, Any], strategy_id: str) -> dict[str, Any]:
        updated = deepcopy(contract)
        if strategy_id == "balance-class-weights":
            updated["recipe_options"]["class_weight_balanced"] = True
            return updated
        if strategy_id == "increase-forest-capacity":
            updated["recipe_options"]["forest_estimators"] = 160
            return updated
        raise ContractError(f"strategy is not automatically actionable: {strategy_id}")

    def learning_report(
        self,
        contract: dict[str, Any],
        metrics: dict[str, Any],
        strategies: list[StrategyProposal],
    ) -> str:
        from . import tabular_classification

        return tabular_classification.learning_report(contract, metrics, strategies)

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        import joblib
        import numpy as np

        bundle = joblib.load(artifact_dir / "model.joblib")
        reference = joblib.load(artifact_dir / "test_reference.joblib")
        actual = bundle["estimator"].predict(reference["X"])
        if not np.array_equal(actual, reference["predictions"]):
            return ["persisted model predictions do not match reference"]
        return []


PLUGIN = TabularClassificationPlugin()
