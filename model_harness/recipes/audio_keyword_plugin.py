from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ..audio_keyword import (
    AudioEvaluationContext,
    AudioTrainingContext,
    evaluate_audio_keyword,
    package_audio_keyword,
    train_audio_keyword,
)
from ..errors import ContractError
from ..io_utils import read_json
from ..plugin_api import RecipeManifest, StrategyProposal


AUDIO_KEYWORD_TEMPLATE: dict[str, Any] = {
    "schema_version": "0.2",
    "task_id": "custom-audio-keyword-model",
    "business_goal": "使用已分段的短音频训练一个离线关键词分类模型",
    "recipe": "audio-keyword-classification",
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
        "kind": "audio_keyword_class_folder",
        "dataset_id": "",
        "root": "",
        "manifest_path": "",
        "report_path": "",
        "fingerprint_sha256": "",
        "sample_rate": 16000,
        "channels": 1,
        "random_seed": 42,
        "split": {"train": 0.60, "validation": 0.20, "test": 0.20},
        "group_by": "speaker_id",
        "boundary": "说话人隔离划分不能证明跨设备、房间、时间或流式场景泛化",
    },
    "model_selection": {
        "primary_metric": "validation_macro_f1",
        "candidates": [
            "most_frequent_baseline",
            "logistic_regression",
            "extra_trees",
        ],
        "test_set_policy": "测试集不得用于模型选择或调参，只在验证集选模完成并重训后评估",
    },
    "recipe_options": {
        "clip_seconds": 1.0,
        "n_mels": 24,
        "n_mfcc": 13,
        "extra_trees_estimators": 160,
    },
    "optimization": {"mode": "recommend", "max_iterations": 3, "require_approval": True},
    "release_gates": {
        "clean_test_accuracy_min": 0.75,
        "clean_test_macro_f1_min": 0.75,
        "clean_test_worst_class_recall_min": 0.50,
        "model_size_mb_max": 50.0,
        "single_clip_p95_latency_ms_max": 100.0,
    },
    "diagnostics": {"failure_sample_limit": 24},
    "compute_budget": {
        "max_candidate_models": 3,
        "max_audio_files": 20000,
        "device": "cpu",
    },
    "human_gates": [
        "确认音频获取与人声数据使用已授权",
        "确认关键词标签、负类与说话人分组含义",
        "确认离线验收门槛",
        "审查失败音频及现实设备样本",
        "批准下一轮优化",
        "批准任何真实设备或生产发布",
    ],
}


SUPPORTED_CANDIDATES = {
    "most_frequent_baseline",
    "logistic_regression",
    "extra_trees",
}


class AudioKeywordClassificationPlugin:
    manifest = RecipeManifest(
        plugin_id="audio-keyword-classification",
        version="0.1.0",
        contract_schema_version="0.2",
        description=(
            "Train an offline classifier for pre-segmented labelled PCM WAV keyword "
            "clips with speaker-disjoint selection and testing."
        ),
        task_type="offline-audio-keyword-classification",
        input_description=(
            "A class-folder ZIP of mono 16 kHz PCM WAV clips whose Speech Commands "
            "style filename prefixes identify speaker groups."
        ),
        output_description=(
            "A trusted local Joblib classifier, independent-test metrics, failures "
            "and model card; not ASR or a streaming wake-word runtime."
        ),
        device="cpu",
        purpose="real user-data feasibility loop",
        modalities=("audio",),
        objectives=("classification",),
        data_adapter="audio-keyword-class-folder-zip",
        target_kinds=("multiclass", "binary"),
        capability_tags=(
            "audio",
            "keyword-classification",
            "speaker-disjoint",
            "user-data",
            "lightweight",
            "offline-only",
        ),
    )

    def template(self) -> dict[str, Any]:
        return deepcopy(AUDIO_KEYWORD_TEMPLATE)

    def validate_contract(self, contract: dict[str, Any]) -> None:
        dataset = contract.get("dataset")
        if (
            not isinstance(dataset, dict)
            or dataset.get("kind") != "audio_keyword_class_folder"
        ):
            raise ContractError(
                "audio-keyword-classification requires dataset.kind=audio_keyword_class_folder"
            )
        for key in ("root", "manifest_path", "report_path"):
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
            raise ContractError(
                "dataset fingerprint does not match the inspected report"
            )
        if int(report.get("class_count", 0)) < 2:
            raise ContractError("at least two keyword classes are required")
        if int(report.get("minimum_class_count", 0)) < 6:
            raise ContractError("every keyword class requires at least six valid clips")
        if int(report.get("speaker_count", 0)) < 5:
            raise ContractError("at least five speaker groups are required")
        if int(dataset.get("sample_rate", 0)) != int(report.get("sample_rate", -1)):
            raise ContractError("dataset sample rate does not match the inspected report")
        if int(dataset.get("channels", 0)) != 1 or int(report.get("channels", 0)) != 1:
            raise ContractError("the current recipe requires mono PCM WAV")
        if dataset.get("group_by") != "speaker_id":
            raise ContractError("audio split must group by speaker_id")
        split = dataset.get("split")
        if not isinstance(split, dict):
            raise ContractError("dataset.split must be an object")
        ratios = [split.get(name) for name in ("train", "validation", "test")]
        if not all(
            isinstance(value, (int, float)) and value > 0 for value in ratios
        ):
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
        if not isinstance(options, dict):
            raise ContractError("recipe_options must be an object")
        clip_seconds = options.get("clip_seconds")
        if not isinstance(clip_seconds, (int, float)) or not 0.25 <= float(
            clip_seconds
        ) <= 3.0:
            raise ContractError("clip_seconds must be between 0.25 and 3.0")
        n_mels = options.get("n_mels")
        n_mfcc = options.get("n_mfcc")
        if not isinstance(n_mels, int) or not 12 <= n_mels <= 64:
            raise ContractError("n_mels must be an integer between 12 and 64")
        if not isinstance(n_mfcc, int) or not 6 <= n_mfcc <= min(32, n_mels):
            raise ContractError("n_mfcc must be between 6 and min(32, n_mels)")
        estimators = options.get("extra_trees_estimators")
        if not isinstance(estimators, int) or not 50 <= estimators <= 1000:
            raise ContractError("extra_trees_estimators must be between 50 and 1000")

        gates = contract.get("release_gates")
        required_gates = {
            "clean_test_accuracy_min",
            "clean_test_macro_f1_min",
            "clean_test_worst_class_recall_min",
            "model_size_mb_max",
            "single_clip_p95_latency_ms_max",
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
        if not isinstance(budget, dict) or len(candidates) > int(
            budget.get("max_candidate_models", 0)
        ):
            raise ContractError("candidate count exceeds compute budget")
        if int(report["total_audio"]) > int(budget.get("max_audio_files", 0)):
            raise ContractError("dataset audio count exceeds compute budget")

    def train(self, contract: dict[str, Any]) -> AudioTrainingContext:
        return train_audio_keyword(contract)

    def evaluate(
        self, training: AudioTrainingContext, contract: dict[str, Any]
    ) -> AudioEvaluationContext:
        return evaluate_audio_keyword(training, contract)

    def package(
        self,
        training: AudioTrainingContext,
        evaluation: AudioEvaluationContext,
        contract: dict[str, Any],
        artifact_dir: Path,
    ) -> dict[str, Any]:
        return package_audio_keyword(training, evaluation, contract, artifact_dir)

    def propose_strategies(
        self, metrics: dict[str, Any], contract: dict[str, Any]
    ) -> list[StrategyProposal]:
        return [
            StrategyProposal(
                strategy_id="collect-device-and-noise-slices",
                title="补充真实设备与环境切片",
                hypothesis=(
                    "说话人隔离测试仍可能高估跨麦克风、房间和噪声条件的表现。"
                ),
                changes=(
                    "按麦克风、房间、距离和噪声建立独立评测切片",
                    "加入长负样本并统计误触发",
                ),
                expected_effect="暴露离线切片未覆盖的真实部署风险。",
                estimated_cost="medium",
                risk="requires-new-data-and-runtime-evaluation",
                requires_approval=True,
                actionable=False,
                evidence={
                    "test_macro_f1": metrics["clean_test"]["macro_f1"],
                    "speaker_split_disjoint": metrics["speaker_split"]["disjoint"],
                },
            )
        ]

    def apply_strategy(
        self, contract: dict[str, Any], strategy_id: str
    ) -> dict[str, Any]:
        raise ContractError(
            f"strategy requires reviewed external audio and is not automatic: {strategy_id}"
        )

    def learning_report(
        self,
        contract: dict[str, Any],
        metrics: dict[str, Any],
        strategies: list[StrategyProposal],
    ) -> str:
        candidates = "\n".join(
            f"- `{name}`：验证集 Macro-F1 {values['macro_f1']:.4f}，训练 {values['fit_seconds']:.3f}s"
            for name, values in metrics["validation_candidates"].items()
        )
        return f"""# Learning Report

## 边界

{contract['business_goal']}

这是已分段短WAV的离线关键词分类，不是ASR，也不是流式唤醒词检测。

## 选模证据

{candidates}

胜出模型为 `{metrics['selected_model']}`；说话人在训练、验证、测试之间不重叠，测试集未参与选模。

## 独立测试

- Accuracy：{metrics['clean_test']['accuracy']:.4f}
- Macro-F1：{metrics['clean_test']['macro_f1']:.4f}
- 最差类别 Recall：{metrics['clean_test']['worst_class_recall']:.4f}
- 失败样本：{metrics['failure_count']}
- 离线门槛：{'all passed' if metrics['gate_checks']['all_offline_gates_passed'] else 'has failures'}

## 下一轮

补充真实设备、房间、噪声与长负样本后，才能评估误触发和流式部署可行性。这些证据不会被当前离线分类结果替代。
"""

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        bundle = joblib.load(artifact_dir / "model.joblib")
        reference = joblib.load(artifact_dir / "test_reference.joblib")
        actual = bundle["estimator"].predict(reference["X"])
        if not np.array_equal(actual, reference["predictions"]):
            return ["persisted model predictions do not match reference"]
        if bundle.get("scope") != "offline_keyword_classification":
            return ["persisted model scope is missing or incorrect"]
        return []


PLUGIN = AudioKeywordClassificationPlugin()
