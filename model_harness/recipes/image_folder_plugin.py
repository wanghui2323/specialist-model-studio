from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ..errors import ContractError
from ..io_utils import read_json
from ..plugin_api import RecipeManifest, StrategyProposal
from . import image_folder_classification


IMAGE_FOLDER_TEMPLATE: dict[str, Any] = {
    "schema_version": "0.2",
    "task_id": "custom-image-model",
    "business_goal": "使用自己的图片训练一个轻量分类模型",
    "recipe": "image-folder-classification",
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
        "kind": "image_folder",
        "dataset_id": "",
        "root": "",
        "manifest_path": "",
        "report_path": "",
        "fingerprint_sha256": "",
        "random_seed": 42,
        "split": {"train": 0.60, "validation": 0.20, "test": 0.20},
        "boundary": "文件级随机划分不能证明跨人员、设备、时间或现场泛化",
    },
    "model_selection": {
        "primary_metric": "validation_macro_f1",
        "candidates": [
            "most_frequent_baseline",
            "logistic_regression",
            "linear_hinge_sgd",
            "random_forest",
        ],
        "test_set_policy": "测试集不得用于模型选择或调参，只在候选模型确定并重训后评估",
    },
    "recipe_options": {"image_size": 24, "class_weight_balanced": False},
    "optimization": {"mode": "recommend", "max_iterations": 3, "require_approval": True},
    "release_gates": {
        "clean_test_accuracy_min": 0.75,
        "clean_test_macro_f1_min": 0.75,
        "clean_test_worst_class_recall_min": 0.50,
        "model_size_mb_max": 50.0,
        "single_sample_p95_latency_ms_max": 100.0,
    },
    "diagnostics": {"failure_sample_limit": 24},
    "compute_budget": {"max_candidate_models": 4, "max_images": 10000, "device": "cpu"},
    "human_gates": [
        "确认数据已授权且必要时脱敏",
        "确认类别目录和标签含义",
        "确认离线验收门槛",
        "审查失败样本",
        "批准下一轮优化",
        "批准生产发布",
    ],
}


SUPPORTED_CANDIDATES = {
    "most_frequent_baseline",
    "logistic_regression",
    "linear_hinge_sgd",
    "random_forest",
}


class ImageFolderClassificationPlugin:
    manifest = RecipeManifest(
        plugin_id="image-folder-classification",
        version="0.1.0",
        contract_schema_version="0.2",
        description="Train and evaluate lightweight classifiers on a user-provided image-folder ZIP.",
        task_type="multiclass-image-classification",
        input_description="A ZIP containing class/image files with at least two classes and five valid images per class.",
        output_description="A trusted local Joblib model bundle, metrics, failures, reports and optimization proposals.",
        device="cpu",
        purpose="real user-data feasibility loop",
        modalities=("image",),
        objectives=("classification",),
        data_adapter="image-folder-zip",
        target_kinds=("multiclass", "binary"),
        capability_tags=("cv", "image-folder", "user-data", "lightweight"),
    )

    def template(self) -> dict[str, Any]:
        return deepcopy(IMAGE_FOLDER_TEMPLATE)

    def validate_contract(self, contract: dict[str, Any]) -> None:
        dataset = contract.get("dataset")
        if not isinstance(dataset, dict) or dataset.get("kind") != "image_folder":
            raise ContractError("image-folder-classification requires dataset.kind=image_folder")
        required_paths = ("root", "manifest_path", "report_path")
        for key in required_paths:
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
        if int(report.get("class_count", 0)) < 2:
            raise ContractError("dataset must contain at least two classes")
        if int(report.get("minimum_class_count", 0)) < 5:
            raise ContractError("every class must contain at least five valid images")
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
        if not isinstance(selection, dict) or selection.get("primary_metric") != "validation_macro_f1":
            raise ContractError("primary metric must be validation_macro_f1")
        candidates = selection.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ContractError("model_selection.candidates must be a non-empty list")
        unknown = sorted(set(candidates) - SUPPORTED_CANDIDATES)
        if unknown:
            raise ContractError(f"unsupported candidate models: {unknown}")

        options = contract.get("recipe_options")
        if not isinstance(options, dict):
            raise ContractError("recipe_options must be an object")
        image_size = options.get("image_size")
        if not isinstance(image_size, int) or image_size not in {16, 24, 32, 48, 64}:
            raise ContractError("recipe_options.image_size must be one of 16, 24, 32, 48, 64")
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
        for key in ("clean_test_accuracy_min", "clean_test_macro_f1_min", "clean_test_worst_class_recall_min"):
            if not 0 <= float(gates[key]) <= 1:
                raise ContractError(f"{key} must be between 0 and 1")
        budget = contract.get("compute_budget")
        if not isinstance(budget, dict) or len(candidates) > int(budget.get("max_candidate_models", 0)):
            raise ContractError("candidate count exceeds compute budget")
        if int(report["total_images"]) > int(budget.get("max_images", 0)):
            raise ContractError("dataset image count exceeds compute budget")

    def train(self, contract: dict[str, Any]) -> Any:
        return image_folder_classification.train(contract)

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any:
        return image_folder_classification.evaluate(training, contract)

    def package(self, training: Any, evaluation: Any, contract: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
        return image_folder_classification.package(training, evaluation, contract, artifact_dir)

    def propose_strategies(self, metrics: dict[str, Any], contract: dict[str, Any]) -> list[StrategyProposal]:
        strategies: list[StrategyProposal] = []
        options = contract["recipe_options"]
        dataset = metrics["dataset"]
        if dataset["imbalance_ratio"] >= 1.5 and not options["class_weight_balanced"]:
            strategies.append(
                StrategyProposal(
                    strategy_id="balance-class-weights",
                    title="启用类别平衡权重",
                    hypothesis="类别数量不均衡可能使模型偏向样本较多的类别。",
                    changes=("候选模型启用class_weight=balanced",),
                    expected_effect="优先改善少数类别Recall，整体Accuracy可能小幅波动。",
                    estimated_cost="low",
                    risk="low",
                    requires_approval=True,
                    actionable=True,
                    evidence={"imbalance_ratio": dataset["imbalance_ratio"], "class_counts": dataset["class_counts"]},
                )
            )
        current_size = int(options["image_size"])
        if metrics["clean_test"]["macro_f1"] < 0.90 and current_size < 48:
            next_size = 32 if current_size < 32 else 48
            strategies.append(
                StrategyProposal(
                    strategy_id="increase-image-resolution",
                    title=f"把训练分辨率提高到{next_size}×{next_size}",
                    hypothesis="当前缩放可能丢失区分类别所需的局部形状。",
                    changes=(f"image_size从{current_size}调整为{next_size}",),
                    expected_effect="可能改善细粒度类别，但会增加训练时间和模型大小。",
                    estimated_cost="medium",
                    risk="medium",
                    requires_approval=True,
                    actionable=True,
                    evidence={"current_macro_f1": metrics["clean_test"]["macro_f1"], "current_image_size": current_size},
                )
            )
        strategies.append(
            StrategyProposal(
                strategy_id="review-and-collect-failures",
                title="复核失败样本并补充代表性数据",
                hypothesis="当前错误可能来自错标、模糊输入或训练数据没有覆盖的真实变化。",
                changes=("复核failure_samples.json", "按真实设备和错误类型补充数据", "重新确认数据授权与标签"),
                expected_effect="区分数据问题和模型问题，建立更可信的下一轮数据集。",
                estimated_cost="medium",
                risk="requires-data-review",
                requires_approval=True,
                actionable=False,
                evidence={"failure_count": metrics["failure_count"], "minimum_class_count": dataset["minimum_class_count"]},
            )
        )
        return strategies

    def apply_strategy(self, contract: dict[str, Any], strategy_id: str) -> dict[str, Any]:
        updated = deepcopy(contract)
        if strategy_id == "balance-class-weights":
            updated["recipe_options"]["class_weight_balanced"] = True
            return updated
        if strategy_id == "increase-image-resolution":
            current = int(updated["recipe_options"]["image_size"])
            updated["recipe_options"]["image_size"] = 32 if current < 32 else 48
            return updated
        raise ContractError(f"strategy is not automatically actionable: {strategy_id}")

    def learning_report(self, contract: dict[str, Any], metrics: dict[str, Any], strategies: list[StrategyProposal]) -> str:
        return image_folder_classification.learning_report(contract, metrics, strategies)

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        errors: list[str] = []
        bundle = joblib.load(artifact_dir / "model.joblib")
        reference = np.load(artifact_dir / "test_reference.npz")
        actual = bundle["estimator"].predict(reference["X"])
        if not np.array_equal(actual, reference["predictions"]):
            errors.append("persisted model predictions do not match reference")
        return errors


PLUGIN = ImageFolderClassificationPlugin()
