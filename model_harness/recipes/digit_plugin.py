from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ..errors import ContractError
from ..plugin_api import RecipeManifest, StrategyProposal
from . import digit_classification


DIGIT_CLASSIFICATION_TEMPLATE: dict[str, Any] = {
    "schema_version": "0.2",
    "task_id": "my-first-digit-model",
    "business_goal": "识别8×8灰度手写数字0—9，学习一条可审计的小模型训练闭环",
    "recipe": "digit-classification",
    "interaction": {
        "mode": "delegate",
        "learning_report": True,
        "pause_when": [
            "missing_required_data",
            "data_authorization_unclear",
            "release_gate_change_requested",
            "untrusted_code_or_model_execution",
            "production_release_requested",
        ],
    },
    "dataset": {
        "kind": "sklearn_builtin_digits",
        "source": "sklearn.datasets.load_digits",
        "random_seed": 42,
        "split": {"train": 0.60, "validation": 0.20, "test": 0.20},
        "boundary": "公开教学数据不代表真实票据、相机、字体、扫描设备或工业现场分布",
    },
    "model_selection": {
        "primary_metric": "validation_macro_f1",
        "candidates": [
            "most_frequent_baseline",
            "logistic_regression",
            "rbf_svm",
            "random_forest",
        ],
        "test_set_policy": "测试集不得用于模型选择或调参，只在候选模型确定并重训后评估",
    },
    "recipe_options": {"augmentations": []},
    "optimization": {
        "mode": "recommend",
        "max_iterations": 3,
        "require_approval": True,
    },
    "release_gates": {
        "clean_test_accuracy_min": 0.96,
        "clean_test_macro_f1_min": 0.96,
        "clean_test_worst_class_recall_min": 0.90,
        "model_size_mb_max": 5.0,
        "single_sample_p95_latency_ms_max": 5.0,
    },
    "diagnostics": {
        "stress_tests": ["gaussian_noise_sigma_4", "shift_right_one_pixel"],
        "policy": "压力测试用于暴露分布偏移风险，不由Agent自动改写放行门槛",
    },
    "compute_budget": {
        "max_candidate_models": 4,
        "max_parallel_jobs": 1,
        "device": "cpu",
    },
    "human_gates": [
        "确认标签定义与错误代价",
        "确认私有数据已授权且必要时脱敏",
        "审查失败切片和压力测试",
        "批准真实数据影子测试",
        "批准生产发布",
    ],
}


SUPPORTED_CANDIDATES = {
    "most_frequent_baseline",
    "logistic_regression",
    "rbf_svm",
    "random_forest",
}
SUPPORTED_AUGMENTATIONS = {"shift_left_right", "gaussian_noise_sigma_1"}


class DigitClassificationPlugin:
    manifest = RecipeManifest(
        plugin_id="digit-classification",
        version="0.2.0",
        contract_schema_version="0.2",
        description="Compare lightweight classifiers on the scikit-learn digits dataset.",
        task_type="multiclass-classification",
        input_description="One 8x8 grayscale digit image represented by 64 numeric pixels.",
        output_description="One integer class label from 0 through 9.",
        device="cpu",
        purpose="reference learning and harness validation",
    )

    def template(self) -> dict[str, Any]:
        return deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)

    def validate_contract(self, contract: dict[str, Any]) -> None:
        dataset = contract.get("dataset")
        if not isinstance(dataset, dict) or dataset.get("kind") != "sklearn_builtin_digits":
            raise ContractError(
                "digit-classification requires dataset.kind=sklearn_builtin_digits"
            )
        split = dataset.get("split")
        if not isinstance(split, dict):
            raise ContractError("dataset.split must be an object")
        ratios = [split.get(name) for name in ("train", "validation", "test")]
        if not all(isinstance(value, (int, float)) and value > 0 for value in ratios):
            raise ContractError("dataset.split values must be positive numbers")
        if abs(sum(float(value) for value in ratios) - 1.0) > 1e-9:
            raise ContractError("dataset.split train+validation+test must equal 1.0")
        if not isinstance(dataset.get("random_seed"), int):
            raise ContractError("dataset.random_seed must be an integer")

        selection = contract.get("model_selection")
        if not isinstance(selection, dict):
            raise ContractError("model_selection must be an object")
        if selection.get("primary_metric") != "validation_macro_f1":
            raise ContractError(
                "digit-classification requires primary_metric=validation_macro_f1"
            )
        candidates = selection.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ContractError("model_selection.candidates must be a non-empty list")
        unknown = sorted(set(candidates) - SUPPORTED_CANDIDATES)
        if unknown:
            raise ContractError(f"unsupported candidate models: {unknown}")

        options = contract.get("recipe_options", {"augmentations": []})
        augmentations = (
            options.get("augmentations", []) if isinstance(options, dict) else None
        )
        if not isinstance(augmentations, list):
            raise ContractError("recipe_options.augmentations must be a list")
        unknown_augmentations = sorted(set(augmentations) - SUPPORTED_AUGMENTATIONS)
        if unknown_augmentations:
            raise ContractError(f"unsupported augmentations: {unknown_augmentations}")

        gates = contract.get("release_gates")
        required_gates = {
            "clean_test_accuracy_min",
            "clean_test_macro_f1_min",
            "clean_test_worst_class_recall_min",
            "model_size_mb_max",
            "single_sample_p95_latency_ms_max",
        }
        if not isinstance(gates, dict):
            raise ContractError("release_gates must be an object")
        missing = sorted(required_gates - set(gates))
        if missing:
            raise ContractError(f"missing release gates: {missing}")
        if not all(isinstance(gates[key], (int, float)) for key in required_gates):
            raise ContractError("all release gate values must be numeric")

        budget = contract.get("compute_budget")
        if not isinstance(budget, dict) or not isinstance(
            budget.get("max_candidate_models"), int
        ):
            raise ContractError("compute_budget.max_candidate_models must be an integer")
        if len(candidates) > budget["max_candidate_models"]:
            raise ContractError("candidate count exceeds compute budget")

    def train(self, contract: dict[str, Any]) -> Any:
        return digit_classification.train(contract)

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any:
        return digit_classification.evaluate(training, contract)

    def package(
        self,
        training: Any,
        evaluation: Any,
        contract: dict[str, Any],
        artifact_dir: Path,
    ) -> dict[str, Any]:
        return digit_classification.package(training, evaluation, contract, artifact_dir)

    def propose_strategies(
        self,
        metrics: dict[str, Any],
        contract: dict[str, Any],
    ) -> list[StrategyProposal]:
        strategies: list[StrategyProposal] = []
        clean = float(metrics["clean_test"]["accuracy"])
        stresses = metrics.get("stress_tests", {})
        active = set(contract.get("recipe_options", {}).get("augmentations", []))
        shifted = stresses.get("shift_right_one_pixel")
        if (
            shifted
            and clean - float(shifted["accuracy"]) > 0.20
            and "shift_left_right" not in active
        ):
            strategies.append(
                StrategyProposal(
                    strategy_id="add-shift-augmentation",
                    title="加入左右位移增强",
                    hypothesis="模型对像素位置过于敏感，训练时加入轻微位移可改善位置偏移鲁棒性。",
                    changes=("训练集加入左移和右移一像素的副本",),
                    expected_effect="优先改善shift压力测试，干净集指标可能轻微波动。",
                    estimated_cost="low",
                    risk="low",
                    requires_approval=True,
                    actionable=True,
                    evidence={"clean_accuracy": clean, "shift_accuracy": shifted["accuracy"]},
                )
            )
        noisy = stresses.get("gaussian_noise_sigma_4")
        if (
            noisy
            and clean - float(noisy["accuracy"]) > 0.20
            and "gaussian_noise_sigma_1" not in active
        ):
            strategies.append(
                StrategyProposal(
                    strategy_id="add-noise-augmentation",
                    title="加入轻度噪声增强",
                    hypothesis="模型只见过干净像素，加入低强度噪声可降低对采集噪声的敏感度。",
                    changes=("训练集加入sigma=1的高斯噪声副本",),
                    expected_effect="可能改善噪声压力测试，但不能代替真实设备样本。",
                    estimated_cost="low",
                    risk="medium",
                    requires_approval=True,
                    actionable=True,
                    evidence={"clean_accuracy": clean, "noise_accuracy": noisy["accuracy"]},
                )
            )
        strategies.append(
            StrategyProposal(
                strategy_id="collect-representative-data",
                title="补充真实场景数据",
                hypothesis="教学数据与真实票据、相机或工业现场存在分布差异。",
                changes=("收集并授权一批代表真实设备和失败类型的数据", "建立独立发布集"),
                expected_effect="验证模型是否具有真实业务价值，而不仅是教学数据高分。",
                estimated_cost="medium",
                risk="requires-data-review",
                requires_approval=True,
                actionable=False,
                evidence={"dataset_boundary": contract["dataset"].get("boundary", "")},
            )
        )
        return strategies

    def apply_strategy(
        self,
        contract: dict[str, Any],
        strategy_id: str,
    ) -> dict[str, Any]:
        updated = deepcopy(contract)
        augmentations = updated.setdefault("recipe_options", {}).setdefault(
            "augmentations", []
        )
        mapping = {
            "add-shift-augmentation": "shift_left_right",
            "add-noise-augmentation": "gaussian_noise_sigma_1",
        }
        augmentation = mapping.get(strategy_id)
        if augmentation is None:
            raise ContractError(f"strategy is not automatically actionable: {strategy_id}")
        if augmentation not in augmentations:
            augmentations.append(augmentation)
        return updated

    def learning_report(
        self,
        contract: dict[str, Any],
        metrics: dict[str, Any],
        strategies: list[StrategyProposal],
    ) -> str:
        return digit_classification.learning_report(contract, metrics, strategies)

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        errors: list[str] = []
        model = joblib.load(artifact_dir / "model.joblib")
        reference = np.load(artifact_dir / "test_reference.npz")
        actual = model.predict(reference["X"])
        if not np.array_equal(actual, reference["predictions"]):
            errors.append("persisted model predictions do not match reference")
        return errors


PLUGIN = DigitClassificationPlugin()
