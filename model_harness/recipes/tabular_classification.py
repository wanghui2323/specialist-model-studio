from __future__ import annotations

import csv
import time
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ..data_adapters import verify_training_dataset_integrity
from ..errors import ContractError
from ..io_utils import read_json, write_json
from ..plugin_api import StrategyProposal
from ..tabular_values import normalize_tabular_value, tabular_inference_example


@dataclass
class TrainingContext:
    X: np.ndarray
    y: np.ndarray
    row_numbers: np.ndarray
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    selected_name: str
    final_model: Any
    validation_results: dict[str, dict[str, Any]]
    feature_columns: list[str]
    target_column: str
    labels: list[str]


@dataclass
class EvaluationContext:
    prediction: np.ndarray
    metrics: dict[str, Any]
    failure_samples: list[dict[str, Any]]


def _load_rows(contract: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dataset = contract["dataset"]
    feature_columns = list(dataset["feature_columns"])
    target_column = str(dataset["target_column"])
    numeric_columns = set(dataset.get("numeric_columns", []))
    rows: list[list[Any]] = []
    targets: list[str] = []
    row_numbers: list[int] = []
    with Path(dataset["csv_path"]).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            rows.append([
                normalize_tabular_value(row.get(column), column in numeric_columns)
                for column in feature_columns
            ])
            targets.append(str(row[target_column]).strip())
            row_numbers.append(row_number)
    return (
        np.asarray(rows, dtype=object),
        np.asarray(targets, dtype=object),
        np.asarray(row_numbers, dtype=np.int64),
    )


def _split_indices(
    y: np.ndarray,
    split: dict[str, float],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    train: list[int] = []
    validation: list[int] = []
    test: list[int] = []
    for label in sorted({str(value) for value in y.tolist()}):
        indices = np.flatnonzero(y == label)
        rng.shuffle(indices)
        count = len(indices)
        if count < 5:
            raise ValueError("每个类别至少需要 5 行才能完成分层划分")
        test_count = max(1, int(round(count * float(split["test"]))))
        validation_count = max(1, int(round(count * float(split["validation"]))))
        if test_count + validation_count >= count:
            raise ValueError("表格数据不足以完成训练、验证、测试三段划分")
        test.extend(int(index) for index in indices[:test_count])
        validation.extend(
            int(index) for index in indices[test_count : test_count + validation_count]
        )
        train.extend(int(index) for index in indices[test_count + validation_count :])
    return (
        np.asarray(sorted(train), dtype=np.int64),
        np.asarray(sorted(validation), dtype=np.int64),
        np.asarray(sorted(test), dtype=np.int64),
    )


def _preprocessor(dataset: dict[str, Any]) -> ColumnTransformer:
    feature_columns = list(dataset["feature_columns"])
    numeric = [feature_columns.index(name) for name in dataset.get("numeric_columns", [])]
    categorical = [
        feature_columns.index(name) for name in dataset.get("categorical_columns", [])
    ]
    transformers: list[tuple[str, Any, list[int]]] = []
    if numeric:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(
                            strategy="median", keep_empty_features=True,
                        )),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(
                            missing_values=None, strategy="most_frequent",
                            keep_empty_features=True,
                        )),
                        (
                            "encode",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ),
                    ]
                ),
                categorical,
            )
        )
    return ColumnTransformer(transformers=transformers, remainder="drop")


def _candidate(model: Any, dataset: dict[str, Any]) -> Pipeline:
    return Pipeline([("prepare", _preprocessor(dataset)), ("model", model)])


def _class_weight(contract: dict[str, Any]) -> str | None:
    if contract["recipe_options"]["class_weight_balanced"]:
        return "balanced"
    return None


def _build_candidates(contract: dict[str, Any]) -> dict[str, Any]:
    seed = int(contract["dataset"]["random_seed"])
    trees = int(contract["recipe_options"]["forest_estimators"])
    dataset = contract["dataset"]
    weight = _class_weight(contract)
    return {
        "most_frequent_baseline": _candidate(
            DummyClassifier(strategy="most_frequent"),
            dataset,
        ),
        "logistic_regression": _candidate(
            LogisticRegression(max_iter=500, class_weight=weight),
            dataset,
        ),
        "random_forest": _candidate(
            RandomForestClassifier(
                n_estimators=trees,
                min_samples_leaf=1,
                class_weight=weight,
                random_state=seed,
                n_jobs=1,
            ),
            dataset,
        ),
        "extra_trees": _candidate(
            ExtraTreesClassifier(
                n_estimators=trees,
                min_samples_leaf=1,
                class_weight=weight,
                random_state=seed,
                n_jobs=1,
            ),
            dataset,
        ),
    }


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: list[str],
) -> dict[str, float]:
    recalls = recall_score(
        y_true,
        y_pred,
        labels=labels,
        average=None,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
        "worst_class_recall": float(np.min(recalls)),
    }


def train(contract: dict[str, Any]) -> TrainingContext:
    verify_training_dataset_integrity(contract["dataset"])
    X, y, row_numbers = _load_rows(contract)
    if len({tuple(row) for row in X}) != len(X):
        raise ContractError("分类数据存在重复有效特征或标签冲突，请重新导入以完成去重检查")
    dataset = contract["dataset"]
    labels = sorted({str(value) for value in y.tolist()})
    train_idx, validation_idx, test_idx = _split_indices(
        y,
        dataset["split"],
        int(dataset["random_seed"]),
    )
    candidates = _build_candidates(contract)
    validation_results: dict[str, dict[str, Any]] = {}
    for name in contract["model_selection"]["candidates"]:
        model = deepcopy(candidates[name])
        started = time.perf_counter()
        model.fit(X[train_idx], y[train_idx])
        prediction = model.predict(X[validation_idx])
        result = classification_metrics(y[validation_idx], prediction, labels)
        result["fit_seconds"] = float(time.perf_counter() - started)
        validation_results[name] = result
    selected_name = max(
        validation_results,
        key=lambda name: (
            validation_results[name]["macro_f1"],
            validation_results[name]["accuracy"],
            validation_results[name]["worst_class_recall"],
        ),
    )
    final_model = deepcopy(candidates[selected_name])
    final_indices = np.concatenate([train_idx, validation_idx])
    final_model.fit(X[final_indices], y[final_indices])
    return TrainingContext(
        X=X,
        y=y,
        row_numbers=row_numbers,
        train_idx=train_idx,
        validation_idx=validation_idx,
        test_idx=test_idx,
        selected_name=selected_name,
        final_model=final_model,
        validation_results=validation_results,
        feature_columns=list(dataset["feature_columns"]),
        target_column=str(dataset["target_column"]),
        labels=labels,
    )


def _latency(context: TrainingContext) -> dict[str, Any]:
    samples: list[float] = []
    for index in context.test_idx[: min(100, len(context.test_idx))]:
        started = time.perf_counter_ns()
        context.final_model.predict(context.X[int(index)].reshape(1, -1))
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
        "max_ms": float(np.max(samples)),
        "measurement_note": "本机同步执行单行预处理和predict，不是生产网络SLA",
    }


def evaluate(context: TrainingContext, contract: dict[str, Any]) -> EvaluationContext:
    prediction = context.final_model.predict(context.X[context.test_idx])
    clean = classification_metrics(
        context.y[context.test_idx],
        prediction,
        context.labels,
    )
    mismatches = context.y[context.test_idx] != prediction
    limit = int(contract.get("diagnostics", {}).get("failure_sample_limit", 24))
    failures: list[dict[str, Any]] = []
    for position in np.flatnonzero(mismatches)[:limit]:
        source_index = int(context.test_idx[int(position)])
        failures.append(
            {
                "row_number": int(context.row_numbers[source_index]),
                "actual": str(context.y[source_index]),
                "predicted": str(prediction[int(position)]),
            }
        )
    report = read_json(Path(contract["dataset"]["report_path"]))
    counts = Counter(str(value) for value in context.y.tolist())
    ordered_counts = [counts[label] for label in context.labels]
    imbalance = max(ordered_counts) / max(1, min(ordered_counts))
    metrics = {
        "task_id": contract["task_id"],
        "recipe": contract["recipe"],
        "selected_model": context.selected_name,
        "labels": context.labels,
        "split_counts": {
            "train": int(len(context.train_idx)),
            "validation": int(len(context.validation_idx)),
            "test": int(len(context.test_idx)),
        },
        "dataset": {
            "dataset_id": report["dataset_id"],
            "fingerprint_sha256": report["fingerprint_sha256"],
            "row_count": report["row_count"],
            "feature_count": len(report["feature_columns"]),
            "target_column": report["target_column"],
            "class_counts": {label: counts[label] for label in context.labels},
            "imbalance_ratio": float(imbalance),
        },
        "validation_candidates": context.validation_results,
        "clean_test": clean,
        "failure_count": int(np.sum(mismatches)),
        "failure_sample_count": len(failures),
        "latency": _latency(context),
        "confusion_matrix": confusion_matrix(
            context.y[context.test_idx],
            prediction,
            labels=context.labels,
        ).tolist(),
    }
    return EvaluationContext(prediction=prediction, metrics=metrics, failure_samples=failures)


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


def package(
    context: TrainingContext,
    evaluation: EvaluationContext,
    contract: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model.joblib"
    joblib.dump(
        {
            "estimator": context.final_model,
            "feature_columns": context.feature_columns,
            "numeric_columns": list(contract["dataset"]["numeric_columns"]),
            "categorical_columns": list(contract["dataset"]["categorical_columns"]),
            "feature_value_policy": "typed_values_missing_none_v1",
            "target_column": context.target_column,
            "labels": context.labels,
            "task_type": "classification",
        },
        model_path,
        compress=3,
    )
    metrics = evaluation.metrics
    metrics["model_size_mb"] = float(model_path.stat().st_size / (1024 * 1024))
    metrics["gate_checks"] = _gate_checks(metrics, contract["release_gates"])
    write_json(artifact_dir / "metrics.json", metrics)
    write_json(artifact_dir / "failure_samples.json", {"samples": evaluation.failure_samples})
    write_json(
        artifact_dir / "dataset_report.json",
        read_json(Path(contract["dataset"]["report_path"])),
    )
    with (artifact_dir / "confusion_matrix.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *context.labels])
        for label, row in zip(context.labels, metrics["confusion_matrix"], strict=True):
            writer.writerow([label, *row])
    with (artifact_dir / "test_predictions.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_number", "actual", "predicted"])
        for index, predicted in zip(context.test_idx, evaluation.prediction, strict=True):
            writer.writerow(
                [
                    int(context.row_numbers[int(index)]),
                    str(context.y[int(index)]),
                    str(predicted),
                ]
            )
    joblib.dump(
        {
            "X": context.X[context.test_idx],
            "predictions": evaluation.prediction,
        },
        artifact_dir / "test_reference.joblib",
        compress=3,
    )
    gate_lines = "\n".join(
        f"- `{name}`: {'PASS' if passed else 'FAIL'}"
        for name, passed in metrics["gate_checks"].items()
    )
    (artifact_dir / "model_card.md").write_text(
        f"""# Model Card: {contract['task_id']}

## Intended use

{contract['business_goal']}

This local model assigns a class in `{context.target_column}` from a user-imported CSV. Offline evaluation is not production-release approval.

## Data and selection

- Dataset fingerprint: `{metrics['dataset']['fingerprint_sha256']}`
- Rows: {metrics['dataset']['row_count']}; features: {metrics['dataset']['feature_count']}
- Classes: {", ".join(context.labels)}
- Selected model: `{metrics['selected_model']}` by validation macro-F1
- Test accuracy: {metrics['clean_test']['accuracy']:.4f}
- Test macro-F1: {metrics['clean_test']['macro_f1']:.4f}
- Worst-class recall: {metrics['clean_test']['worst_class_recall']:.4f}
- Local p95: {metrics['latency']['p95_ms']:.2f} ms
- Model size: {metrics['model_size_mb']:.3f} MB

## Offline gates

{gate_lines}

## Known limits

- Stratified row splitting cannot prove generalization across time, sites, machines or populations.
- Review misclassified rows before production use.
- Load Joblib artifacts only from trusted runs after hash verification.
""",
        encoding="utf-8",
    )
    (artifact_dir / "inference_example.py").write_text(
        tabular_inference_example(),
        encoding="utf-8",
    )
    return metrics


def learning_report(
    contract: dict[str, Any],
    metrics: dict[str, Any],
    strategies: list[StrategyProposal],
) -> str:
    candidates = "\n".join(
        f"- `{name}`：验证集 Macro-F1 {values['macro_f1']:.4f}，准确率 {values['accuracy']:.4f}，训练 {values['fit_seconds']:.3f}s"
        for name, values in metrics["validation_candidates"].items()
    )
    strategy_lines = "\n".join(
        f"- `{item.strategy_id}`：{item.title}（{'批准后可执行' if item.actionable else '需要补充外部条件'}）"
        for item in strategies
    )
    return f"""# Learning Report

## 任务和数据

{contract['business_goal']}

本轮读取 {metrics['dataset']['row_count']} 行表格数据和 {metrics['dataset']['feature_count']} 个特征，目标列为 `{metrics['dataset']['target_column']}`。类别按分层划分。数据指纹为 `{metrics['dataset']['fingerprint_sha256']}`。

## Harness实际比较了什么

{candidates}

胜出模型为 `{metrics['selected_model']}`。模型选择只使用验证集；测试集在选择完成后才打开。

## 验收结果

- 准确率：{metrics['clean_test']['accuracy']:.4f}
- Macro-F1：{metrics['clean_test']['macro_f1']:.4f}
- 最差类别召回：{metrics['clean_test']['worst_class_recall']:.4f}
- 本地p95：{metrics['latency']['p95_ms']:.2f} ms
- 离线门槛：{'全部通过' if metrics['gate_checks']['all_offline_gates_passed'] else '存在未通过项'}

## 下一轮建议

{strategy_lines}

以上只是建议，本轮没有自动执行。人还需要决定是否批准优化，以及这个离线结果能否进入业务使用。不能直接上线。
"""
