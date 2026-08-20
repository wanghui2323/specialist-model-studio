from __future__ import annotations

import csv
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.datasets import load_digits
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from ..io_utils import sha256_bytes, write_json
from ..plugin_api import StrategyProposal


@dataclass
class TrainingContext:
    X: np.ndarray
    images: np.ndarray
    y: np.ndarray
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    selected_name: str
    final_model: Any
    validation_results: dict[str, dict[str, Any]]
    augmentations: tuple[str, ...]
    candidate_fit_count: int
    final_fit_count: int


@dataclass
class EvaluationContext:
    clean_prediction: np.ndarray
    metrics: dict[str, Any]


def build_candidates(seed: int) -> dict[str, Any]:
    return {
        "most_frequent_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=3000,
                        solver="lbfgs",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "rbf_svm": Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", SVC(kernel="rbf", C=4.0, gamma="scale")),
            ]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=1,
            random_state=seed,
            n_jobs=1,
        ),
    }


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    recalls = recall_score(
        y_true,
        y_pred,
        labels=list(range(10)),
        average=None,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "worst_class_recall": float(np.min(recalls)),
        "per_class_recall": {
            str(label): float(value) for label, value in enumerate(recalls)
        },
    }


def _load_and_split(contract: dict[str, Any]) -> dict[str, np.ndarray]:
    digits = load_digits()
    X = digits.data.astype(np.float64)
    images = digits.images.astype(np.float64)
    y = digits.target.astype(np.int64)
    seed = int(contract["dataset"]["random_seed"])
    split = contract["dataset"]["split"]
    indices = np.arange(len(y))
    train_val_idx, test_idx = train_test_split(
        indices,
        test_size=float(split["test"]),
        random_state=seed,
        stratify=y,
    )
    validation_fraction_of_remaining = float(split["validation"]) / (
        float(split["train"]) + float(split["validation"])
    )
    train_idx, validation_idx = train_test_split(
        train_val_idx,
        test_size=validation_fraction_of_remaining,
        random_state=seed,
        stratify=y[train_val_idx],
    )
    return {
        "X": X,
        "images": images,
        "y": y,
        "train_idx": train_idx,
        "validation_idx": validation_idx,
        "test_idx": test_idx,
    }


def _augment_fit_data(
    X: np.ndarray,
    y: np.ndarray,
    augmentations: list[str],
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if not augmentations:
        return X, y
    features = [X]
    labels = [y]
    images = X.reshape(-1, 8, 8)
    if "shift_left_right" in augmentations:
        shifted_left = np.zeros_like(images)
        shifted_left[:, :, :-1] = images[:, :, 1:]
        shifted_right = np.zeros_like(images)
        shifted_right[:, :, 1:] = images[:, :, :-1]
        features.extend(
            [
                shifted_left.reshape(len(images), -1),
                shifted_right.reshape(len(images), -1),
            ]
        )
        labels.extend([y, y])
    if "gaussian_noise_sigma_1" in augmentations:
        rng = np.random.default_rng(seed)
        noisy = np.clip(rng.normal(images, 1.0), 0, 16)
        features.append(noisy.reshape(len(images), -1))
        labels.append(y)
    return np.concatenate(features), np.concatenate(labels)


def train(contract: dict[str, Any]) -> TrainingContext:
    data = _load_and_split(contract)
    X = data["X"]
    y = data["y"]
    seed = int(contract["dataset"]["random_seed"])
    candidates = build_candidates(seed)
    requested = contract["model_selection"]["candidates"]
    augmentations = list(
        contract.get("recipe_options", {}).get("augmentations", [])
    )
    candidate_X, candidate_y = _augment_fit_data(
        X[data["train_idx"]],
        y[data["train_idx"]],
        augmentations,
        seed,
    )
    validation_results: dict[str, dict[str, Any]] = {}
    for name in requested:
        model = deepcopy(candidates[name])
        started = time.perf_counter()
        model.fit(candidate_X, candidate_y)
        prediction = model.predict(X[data["validation_idx"]])
        result = classification_metrics(y[data["validation_idx"]], prediction)
        result["fit_seconds"] = float(time.perf_counter() - started)
        validation_results[name] = result

    selected_name = max(
        validation_results,
        key=lambda name: (
            validation_results[name]["macro_f1"],
            validation_results[name]["accuracy"],
        ),
    )
    final_model = deepcopy(candidates[selected_name])
    train_validation_idx = np.concatenate(
        [data["train_idx"], data["validation_idx"]]
    )
    final_X, final_y = _augment_fit_data(
        X[train_validation_idx],
        y[train_validation_idx],
        augmentations,
        seed + 1,
    )
    final_model.fit(final_X, final_y)
    return TrainingContext(
        X=X,
        images=data["images"],
        y=y,
        train_idx=data["train_idx"],
        validation_idx=data["validation_idx"],
        test_idx=data["test_idx"],
        selected_name=selected_name,
        final_model=final_model,
        validation_results=validation_results,
        augmentations=tuple(augmentations),
        candidate_fit_count=int(len(candidate_y)),
        final_fit_count=int(len(final_y)),
    )


def _stress_inputs(images: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    noisy = np.clip(images + rng.normal(0, 4.0, size=images.shape), 0, 16)
    shifted = np.zeros_like(images)
    shifted[:, :, 1:] = images[:, :, :-1]
    return {
        "gaussian_noise_sigma_4": noisy.reshape(len(noisy), -1),
        "shift_right_one_pixel": shifted.reshape(len(shifted), -1),
    }


def _latency(model: Any, X: np.ndarray) -> dict[str, Any]:
    model.predict(X[:10])
    samples = []
    for row in X:
        started = time.perf_counter_ns()
        model.predict(row.reshape(1, -1))
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
        "max_ms": float(np.max(samples)),
        "measurement_note": "当前机器和Python进程中的逐样本同步predict，不是生产端到端SLA",
    }


def evaluate(context: TrainingContext, contract: dict[str, Any]) -> EvaluationContext:
    X_test = context.X[context.test_idx]
    y_test = context.y[context.test_idx]
    prediction = context.final_model.predict(X_test)
    clean = classification_metrics(y_test, prediction)
    seed = int(contract["dataset"]["random_seed"])
    requested_stress = set(contract["diagnostics"]["stress_tests"])
    stress = {
        name: classification_metrics(
            y_test, context.final_model.predict(stressed_X)
        )
        for name, stressed_X in _stress_inputs(
            context.images[context.test_idx], seed
        ).items()
        if name in requested_stress
    }
    metrics = {
        "task_id": contract["task_id"],
        "recipe": contract["recipe"],
        "selected_model": context.selected_name,
        "split_counts": {
            "train": int(len(context.train_idx)),
            "validation": int(len(context.validation_idx)),
            "test": int(len(context.test_idx)),
        },
        "training": {
            "augmentations": list(context.augmentations),
            "candidate_fit_count": context.candidate_fit_count,
            "final_fit_count": context.final_fit_count,
        },
        "dataset_sha256": sha256_bytes(context.X.tobytes(), context.y.tobytes()),
        "validation_candidates": context.validation_results,
        "clean_test": clean,
        "stress_tests": stress,
        "latency": _latency(context.final_model, X_test),
    }
    return EvaluationContext(clean_prediction=prediction, metrics=metrics)


def _gate_checks(metrics: dict[str, Any], gates: dict[str, float]) -> dict[str, bool]:
    checks = {
        "clean_test_accuracy": metrics["clean_test"]["accuracy"]
        >= gates["clean_test_accuracy_min"],
        "clean_test_macro_f1": metrics["clean_test"]["macro_f1"]
        >= gates["clean_test_macro_f1_min"],
        "clean_test_worst_class_recall": metrics["clean_test"]["worst_class_recall"]
        >= gates["clean_test_worst_class_recall_min"],
        "model_size_mb": metrics["model_size_mb"] <= gates["model_size_mb_max"],
        "single_sample_p95_latency_ms": metrics["latency"]["p95_ms"]
        <= gates["single_sample_p95_latency_ms_max"],
    }
    checks["all_offline_gates_passed"] = all(checks.values())
    return checks


def _write_confusion_matrix(path: Path, matrix: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *range(10)])
        for label, row in enumerate(matrix):
            writer.writerow([label, *row.tolist()])


def _write_model_card(
    path: Path,
    contract: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    stress_lines = "\n".join(
        f"- `{name}`：Accuracy {values['accuracy']:.4f}，Macro-F1 {values['macro_f1']:.4f}，最差类别Recall {values['worst_class_recall']:.4f}"
        for name, values in metrics["stress_tests"].items()
    )
    gate_lines = "\n".join(
        f"- `{name}`：{'PASS' if passed else 'FAIL'}"
        for name, passed in metrics["gate_checks"].items()
    )
    path.write_text(
        f"""# Model Card: {contract['task_id']}

## Intended use

{contract['business_goal']}

This is an educational reference run. It is not evidence of fitness for customer data or production release.

## Selection and evaluation

- Selected model: `{metrics['selected_model']}`
- Selection metric: validation Macro-F1
- Split counts: train {metrics['split_counts']['train']}, validation {metrics['split_counts']['validation']}, test {metrics['split_counts']['test']}
- Clean test Accuracy: {metrics['clean_test']['accuracy']:.4f}
- Clean test Macro-F1: {metrics['clean_test']['macro_f1']:.4f}
- Worst-class Recall: {metrics['clean_test']['worst_class_recall']:.4f}
- Model size: {metrics['model_size_mb']:.4f} MB
- Single-sample p95 latency: {metrics['latency']['p95_ms']:.4f} ms

## Offline gates

{gate_lines}

## Diagnostic stress tests

{stress_lines}

## Known limits

- Public 8×8 digits do not represent customer documents, cameras, fonts or devices.
- The dataset has no user, device or time-group metadata, so cross-domain generalization is unproven.
- Stress inputs are synthetic diagnostics, not estimates of production frequency.
- Local latency is not an end-to-end service SLA.
- The Joblib model must only be loaded from a trusted source after hash verification.
""",
        encoding="utf-8",
    )


def package(
    context: TrainingContext,
    evaluation: EvaluationContext,
    contract: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model.joblib"
    joblib.dump(context.final_model, model_path, compress=3)
    metrics = evaluation.metrics
    metrics["model_size_mb"] = float(model_path.stat().st_size / (1024 * 1024))
    metrics["gate_checks"] = _gate_checks(metrics, contract["release_gates"])
    write_json(artifact_dir / "metrics.json", metrics)
    _write_confusion_matrix(
        artifact_dir / "confusion_matrix.csv",
        confusion_matrix(
            context.y[context.test_idx],
            evaluation.clean_prediction,
            labels=list(range(10)),
        ),
    )
    np.savez_compressed(
        artifact_dir / "test_reference.npz",
        X=context.X[context.test_idx],
        y=context.y[context.test_idx],
        predictions=evaluation.clean_prediction,
    )
    _write_model_card(artifact_dir / "model_card.md", contract, metrics)
    return metrics


def learning_report(
    contract: dict[str, Any],
    metrics: dict[str, Any],
    strategies: list[StrategyProposal],
) -> str:
    candidates = "\n".join(
        f"- `{name}`：validation Macro-F1 {values['macro_f1']:.4f}"
        for name, values in metrics["validation_candidates"].items()
    )
    stresses = "\n".join(
        f"- `{name}`：Accuracy {values['accuracy']:.4f}，最差类别Recall {values['worst_class_recall']:.4f}"
        for name, values in metrics["stress_tests"].items()
    )
    failed = [
        name
        for name, passed in metrics["gate_checks"].items()
        if name != "all_offline_gates_passed" and not passed
    ]
    gate_summary = "全部通过" if not failed else f"未通过：{', '.join(failed)}"
    strategy_lines = "\n".join(
        f"- `{item.strategy_id}`：{item.title}（{'可批准后自动执行' if item.actionable else '需要人工补充条件'}）"
        for item in strategies
    )
    active_augmentations = metrics["training"]["augmentations"]
    augmentation_summary = (
        "、".join(f"`{name}`" for name in active_augmentations)
        if active_augmentations
        else "无"
    )
    return f"""# Learning Report

## 这次任务是什么

{contract['business_goal']}

Harness使用 `{contract['recipe']}` Recipe。当前任务是多类别分类：输入固定长度的像素特征，输出0—9中的一个类别。

## 为什么需要三份数据

- 训练集用于拟合候选模型；
- 验证集用于比较候选模型，决定谁胜出；
- 测试集不参与选择，只在最终模型确定后检查未知样本表现。

本次切分为训练 {metrics['split_counts']['train']}、验证 {metrics['split_counts']['validation']}、测试 {metrics['split_counts']['test']}。本轮训练增强：{augmentation_summary}。

## Agent比较了什么

{candidates}

胜出模型是 `{metrics['selected_model']}`。选择依据是合同中冻结的验证集Macro-F1，而不是最终测试集分数。

## 最终结果怎样理解

- Clean Accuracy：{metrics['clean_test']['accuracy']:.4f}
- Clean Macro-F1：{metrics['clean_test']['macro_f1']:.4f}
- Worst-class Recall：{metrics['clean_test']['worst_class_recall']:.4f}
- Model size：{metrics['model_size_mb']:.4f} MB
- Single-sample p95：{metrics['latency']['p95_ms']:.4f} ms
- Offline gates：{gate_summary}

Accuracy看整体答对比例；Macro-F1让每个数字类别获得相同权重；Worst-class Recall直接暴露最容易漏掉的类别。

## 为什么高分仍然不能直接上线

{stresses}

压力测试通过人为加入噪声或移动像素，检查输入分布变化时模型是否脆弱。它们只负责暴露风险，不代表真实业务中的发生概率，也不会被Agent用来自动修改用户冻结的门槛。

## Harness建议下一步做什么

{strategy_lines}

以上只是建议，本轮没有自动执行。可执行策略也必须由人批准后创建一条新的子运行，原始合同、指标和模型不会被覆盖。

## 人还需要决定什么

- 真实任务中的错误代价和标签语义；
- 客户数据是否授权、是否代表真实设备和环境；
- 哪些失败切片必须进入独立发布集；
- 何时进入影子测试、灰度和生产发布。

这份报告帮助用户理解本次运行，但不把教学实验包装成生产验收。
"""
